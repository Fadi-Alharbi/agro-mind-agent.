from typing import TypedDict, Annotated, Optional
import base64
import operator
import json

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage

from agent.llm import get_chat_llm
from db.customer_state import get_order_context
from memory.customer_memory import CustomerMemory
from agent.tools import (
    classify_intent,
    analyze_crop_image,
    recommend_product,
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
        llm = get_chat_llm(temperature=0)
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
    # Real DB-backed order/tracking lookup (db-test schema). The session id
    # scopes the query to this customer's own orders inside get_order_context.
    order_id = state.get("order_id")
    status = get_order_context(state["session_id"], None, order_id)
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
    llm = get_chat_llm(temperature=0.3)
    # Long-term memory now comes from the relational store: get_customer_profile
    # returns a 'context' string summarising the returning customer across chats
    # (crop, location, recent diagnoses) via CustomerMemory.get_context_string().
    profile = get_customer_profile(state["session_id"])
    memory_context = profile.get("context", "") if profile else ""

    if state["message"] == "INIT_SESSION":
        # Proactive greeting, richest first: recall the customer's active
        # treatments and check in on them (crop/disease/elapsed days). If there
        # are none, fall back to the recalled cross-session profile, then to a
        # generic hello.
        from datetime import datetime
        from db.customer_state import get_active_treatments
        try:
            treatments = get_active_treatments(state["session_id"], None)
        except Exception:
            treatments = []

        if treatments:
            today = datetime.now().strftime("%Y-%m-%d")
            prompt = f"""You are a friendly agricultural expert checking up on your farmer friend.
Today's date is {today}.
The customer has these active treatments on record (JSON): {json.dumps(treatments, ensure_ascii=False)}

Instruction:
1. Identify the crop and the disease being treated.
2. Calculate how many days have passed since 'start_date'.
3. Ask explicitly how the crop is doing ("How are the tomatoes doing?").
4. Ask whether they applied the treatment today.
5. If a 'duration' is given, remind them how many days are left.
6. Be warm and conversational, plain text without markdown bold asterisks (**)."""
            return {"response_text": llm.invoke(prompt).content, "intent": "greeting"}

        if memory_context:
            prompt = f"""You are a friendly agricultural expert greeting a returning farmer.
Use ONLY the recalled profile below to open with a warm, personalised check-in:
ask how their crop is doing and whether the previous issue has improved.
Keep it short and conversational, plain text without markdown bold asterisks (**).

Recalled profile:
{memory_context}"""
            return {"response_text": llm.invoke(prompt).content, "intent": "greeting"}

        return {"response_text": "Hello! I am Agro-Mind, your agricultural assistant. How can I help you today?", "intent": "greeting"}

    context_str = f"Context from previous interactions: {memory_context}. " if memory_context else ""
    prompt = f"You are an agricultural assistant. {context_str}Answer nicely and format your response clearly using plain text without markdown bold asterisks (**). User message: {state['message']}"
    response = llm.invoke(prompt).content
    return {"response_text": response}

def _extract_treatment_json(raw: str) -> dict:
    """Parse a treatment JSON object from an LLM reply that may be fenced."""
    import re
    try:
        return json.loads(raw.strip())
    except Exception:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return {}
    return {}


def memory_node(state: AgentState):
    """Stage 4: persist the turn's outcome to relational long-term memory."""
    intent = state.get("intent")
    session_id = state["session_id"]

    profile_dict = {
        "last_intent": intent,
        "last_recommended_product": state.get("recommended_product_id"),
    }
    # Mark diagnosis/product turns so they surface under "Recent issues" when a
    # returning customer is recalled by CustomerMemory.get_context_string().
    if intent in ("Diagnosis", "Product"):
        profile_dict["infestation_note"] = f"{intent}: {state.get('message', '')[:120]}"
    update_customer_profile.invoke(
        {"session_id": session_id, "data": json.dumps(profile_dict)}
    )

    # Treatment tracking (Fadi's feature, now relational): when a product was
    # recommended, extract structured details and persist them as an active
    # treatment so the next INIT_SESSION can proactively check in.
    if intent in ("Diagnosis", "Product") and "Product ID:" in state.get("response_text", ""):
        try:
            from datetime import datetime
            from db.customer_state import add_treatment

            extract_prompt = (
                "Extract the recommended treatment from the text as STRICT JSON with keys "
                '"crop", "disease", "product_id", "duration", "instructions". '
                "Use null for anything missing. Reply with ONLY the JSON object.\n\n"
                f"Text: {state.get('response_text')}\n"
                f"User message: {state.get('message')}"
            )
            details = _extract_treatment_json(
                get_chat_llm(temperature=0).invoke(extract_prompt).content
            )
            if details.get("product_id"):
                add_treatment(
                    session_id,
                    None,
                    start_date=datetime.now().strftime("%Y-%m-%d"),
                    crop=details.get("crop"),
                    disease=details.get("disease"),
                    product_id=details.get("product_id"),
                    duration=details.get("duration"),
                    instructions=details.get("instructions"),
                )
        except Exception:
            pass

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
        
        # Persist the user's turn first, so the relational memory (messages
        # table) is populated for cross-session recall and context building.
        mem = CustomerMemory(session_id)
        if user_text != "INIT_SESSION":
            image_b64 = base64.b64encode(image_bytes).decode("utf-8") if image_bytes else None
            mem.append_turn(
                "user",
                user_text,
                has_image=image_bytes is not None,
                image_base64=image_b64,
            )

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

        # Persist the assistant's reply to complete the conversation record.
        if final_state.get("response_text"):
            mem.append_turn("assistant", final_state.get("response_text", ""))

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
