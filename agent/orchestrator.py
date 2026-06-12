from typing import TypedDict, Annotated, Optional
import operator
import json

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from agent.tools import (
    classify_intent, 
    analyze_crop_image, 
    recommend_product, 
    lookup_order_status, 
    detect_escalation_risk, 
    create_human_alert, 
    update_customer_profile
)

# Return contract expected by backend
class AgentResponse:
    def __init__(self, **kwargs):
        self.intent = kwargs.get("intent", "General")
        self.safety_risk_detected = kwargs.get("safety_risk_detected", False)
        self.escalate_human = kwargs.get("escalate_human", False)
        self.response_text = kwargs.get("response_text", "")
        self.recommended_product_id = kwargs.get("recommended_product_id")
        self.group_purchase_triggered = kwargs.get("group_purchase_triggered", False)
        self.human_summary_brief = kwargs.get("human_summary_brief")
        self.matched_products = kwargs.get("matched_products", [])
        self.session_id = kwargs.get("session_id", "")

    def to_dict(self):
        return {
            "intent": self.intent.lower() if self.intent else "general_qa",
            "safety_risk_detected": self.safety_risk_detected,
            "escalate_human": self.escalate_human,
            "response_text": self.response_text,
            "recommended_product_id": self.recommended_product_id,
            "group_purchase_triggered": self.group_purchase_triggered,
            "human_summary_brief": self.human_summary_brief,
            "matched_products": self.matched_products,
            "session_id": self.session_id,
        }

class AgentState(TypedDict):
    session_id: str
    message: str
    image_bytes: Optional[bytes]
    order_id: Optional[str]
    
    intent: str
    safety_risk_detected: bool
    escalate_human: bool
    response_text: str
    recommended_product_id: Optional[str]
    group_purchase_triggered: bool
    human_summary_brief: Optional[str]
    matched_products: list

# --- Graph Nodes ---

def safety_check_node(state: AgentState):
    """Stage 1: Check for safety risks"""
    msg = state["message"]
    risk = detect_escalation_risk.invoke(msg)
    if risk:
        alert_text = create_human_alert.invoke("")
        return {
            "safety_risk_detected": True,
            "escalate_human": True,
            "intent": "Safety",
            "response_text": alert_text,
            "human_summary_brief": "Automated safety override triggered."
        }
    return {"safety_risk_detected": False}

def intent_node(state: AgentState):
    """Stage 2: Classify intent if no safety risk"""
    if state.get("image_bytes"):
        return {"intent": "Diagnosis"}
    
    if state["message"] == "INIT_SESSION":
        return {"intent": "General"}
        
    intent = classify_intent.invoke(state["message"])
    return {"intent": intent}

def diagnosis_node(state: AgentState):
    """Handle image and crop diagnosis"""
    img = state.get("image_bytes")
    if img:
        import base64
        # We need a base64 string for the Vision model, so encode the raw bytes
        encoded = base64.b64encode(img).decode("utf-8") if isinstance(img, bytes) else img
        analysis = analyze_crop_image.invoke(encoded)
    else:
        # Text-based diagnosis using LLM
        llm = ChatOpenAI(temperature=0, model="gpt-4o")
        profile = get_customer_profile(state["session_id"])
        context_str = f"Context: {json.dumps(profile)}. " if profile else ""
        expert_prompt = f"You are a highly precise agricultural expert. Diagnose this crop issue accurately. Do not guess if unsure. Format your response clearly using plain text without markdown bold asterisks (**). {context_str}Issue: {state['message']}"
        analysis = llm.invoke(expert_prompt).content

    # Try to recommend product based on analysis
    recommendation = recommend_product.invoke({"diagnosis": analysis, "crop": state["message"]})
    
    if "No suitable product found" in recommendation:
        # Provide the diagnosis, a warning about no product, and the AI's general advice.
        final_text = f"Diagnosis:\n{analysis}\n\nNotice: We do not have a specific product in our catalog for this, but here is some expert advice:\n\n{recommendation.replace('No suitable product found in our catalog for this specific issue.', '')}"
    else:
        final_text = f"Diagnosis:\n{analysis}\n\nRecommended Solution & Usage:\n{recommendation}"
    
    return {
        "response_text": final_text
    }

def logistics_node(state: AgentState):
    order_id = state.get("order_id") or "UNKNOWN"
    status = lookup_order_status.invoke(order_id)
    return {"response_text": status}

def product_node(state: AgentState):
    recommendation = recommend_product.invoke({"diagnosis": state["message"], "crop": state["message"]})
    
    if "No suitable product found" in recommendation:
        final_text = f"Notice: We do not have a specific product in our catalog for this, but here is some expert advice:\n\n{recommendation.replace('No suitable product found in our catalog for this specific issue.', '')}"
    else:
        final_text = f"Recommended Solution & Usage:\n{recommendation}"
        
    return {"response_text": final_text}

from agent.tools import get_customer_profile

def general_node(state: AgentState):
    llm = ChatOpenAI(temperature=0.3, model="gpt-4o")
    # Retrieve long term memory
    profile = get_customer_profile(state["session_id"])
    context_str = ""
    if profile:
        context_str = f"Context from previous interaction: {json.dumps(profile)}. "
        
    if state["message"] == "INIT_SESSION":
        # Proactive Greeting logic
        active_treatments = profile.get("active_treatments", []) if profile else []
        if active_treatments:
            from datetime import datetime
            today = datetime.now().strftime('%Y-%m-%d')
            prompt = f"""You are a friendly agricultural expert checking up on your farmer friend.
Today's date is {today}.
The user has these active treatments on record: {active_treatments}

Instruction:
1. Identify the crop and the disease being treated.
2. Calculate how many days have passed since the 'Start Date'.
3. Ask explicitly about the crop ("How are the tomatoes doing?").
4. Ask if they sprayed the pesticide/treatment today.
5. Remind them how many days are left in their treatment duration (if a duration is specified).
6. Format clearly using plain text without markdown bold asterisks (**). Be very friendly and conversational."""
            response = llm.invoke(prompt).content
            return {"response_text": response, "intent": "greeting"}
        else:
            return {"response_text": "Hello! I am Agro-Mind, your agricultural assistant. How can I help you today?", "intent": "greeting"}

    prompt = f"You are an agricultural assistant. {context_str}Answer nicely and format your response clearly using plain text without markdown bold asterisks (**). User message: {state['message']}"
    response = llm.invoke(prompt).content
    return {"response_text": response}

def memory_node(state: AgentState):
    """Stage 4: Update SQLite memory"""
    profile_dict = {
        "last_intent": state.get("intent"),
        "last_interaction": state["message"],
        "last_recommended_product": state.get("recommended_product_id")
    }
    
    # If the agent recommended a treatment, extract it and save it as an active treatment
    if state.get("intent") in ["Diagnosis", "Product"] and "Product ID:" in state.get("response_text", ""):
        try:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(temperature=0, model="gpt-4o-mini")
            from datetime import datetime
            today = datetime.now().strftime('%Y-%m-%d')
            extract_prompt = f"Extract the recommended treatment details from this text. Format exactly as: 'Start Date: {today} | Crop: [Crop Name] | Disease: [Disease Name] | Product: [Product ID] | Duration: [e.g. 6 days or 2 times per season] | Instructions: [Brief usage instructions]'. If none found, reply 'NONE'. Text: {state.get('response_text')} User Message Context: {state.get('message')}"
            treatment_summary = llm.invoke(extract_prompt).content
            if treatment_summary != "NONE":
                profile_dict["active_treatments"] = [treatment_summary]
        except Exception:
            pass

    profile_data = json.dumps(profile_dict)
    update_customer_profile.invoke({"session_id": state["session_id"], "data": profile_data})
    return state

# --- Routing Logic ---

def route_after_safety(state: AgentState):
    if state.get("safety_risk_detected"):
        return "memory_node"
    return "intent_node"

def route_intent(state: AgentState):
    intent = state.get("intent", "General")
    if intent == "Diagnosis":
        return "diagnosis_node"
    elif intent == "Logistics":
        return "logistics_node"
    elif intent == "Product":
        return "product_node"
    else:
        return "general_node"

# --- Build Graph ---

graph_builder = StateGraph(AgentState)

graph_builder.add_node("safety_check_node", safety_check_node)
graph_builder.add_node("intent_node", intent_node)
graph_builder.add_node("diagnosis_node", diagnosis_node)
graph_builder.add_node("logistics_node", logistics_node)
graph_builder.add_node("product_node", product_node)
graph_builder.add_node("general_node", general_node)
graph_builder.add_node("memory_node", memory_node)

graph_builder.set_entry_point("safety_check_node")
graph_builder.add_conditional_edges("safety_check_node", route_after_safety)
graph_builder.add_conditional_edges("intent_node", route_intent)

for node in ["diagnosis_node", "logistics_node", "product_node", "general_node"]:
    graph_builder.add_edge(node, "memory_node")

graph_builder.add_edge("memory_node", END)
langgraph_app = graph_builder.compile()

# --- Wrapper for FastAPI compatibility ---

class AgroMindAgent:
    def __init__(self):
        self.app = langgraph_app

    async def run(
        self,
        session_id: str,
        user_text: str,
        image_bytes: Optional[bytes] = None,
        order_id: Optional[str] = None,
    ) -> AgentResponse:
        
        initial_state = {
            "session_id": session_id,
            "message": user_text,
            "image_bytes": image_bytes,
            "order_id": order_id,
            "intent": "General",
            "safety_risk_detected": False,
            "escalate_human": False,
            "response_text": "",
            "recommended_product_id": None,
            "group_purchase_triggered": False,
            "human_summary_brief": None,
            "matched_products": [],
        }

        # LangGraph invoke
        final_state = await self.app.ainvoke(initial_state)

        # Parse matched products if they were found in text
        text = final_state.get("response_text", "")
        import re
        from rag.catalog_loader import get_product_by_id
        
        products = []
        rec_id = None
        # Look for typical ID patterns like AF0001, PDD001, etc.
        match = re.search(r"([A-Z]{2}\d{4,})", text)
        if match:
            rec_id = match.group(1)
            product_record = get_product_by_id(rec_id)
            if product_record:
                products.append(product_record.to_dict())
            else:
                # Fallback
                products.append({
                    "product_id": rec_id,
                    "product_name": "Recommended Product",
                    "product_type": "Treatment",
                    "group_price": 25.0,
                    "single_price": 35.0
                })

        return AgentResponse(
            intent=final_state.get("intent", "General").lower(),
            safety_risk_detected=final_state.get("safety_risk_detected", False),
            escalate_human=final_state.get("escalate_human", False),
            response_text=final_state.get("response_text", ""),
            recommended_product_id=rec_id,
            group_purchase_triggered=bool(rec_id),
            human_summary_brief=final_state.get("human_summary_brief"),
            matched_products=products,
            session_id=session_id
        )
