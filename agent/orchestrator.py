from typing import TypedDict, Annotated, Optional
import base64
import operator
import json
import re
import threading

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage

from agent.llm import get_chat_llm
from db.customer_state import get_order_context
from memory.customer_memory import CustomerMemory
from agent.tools import (
    classify_intent,
    analyze_crop_image,
    recommend_product,
    retrieve_agronomy_knowledge,
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

async def diagnosis_node(state: AgentState):
    """Handle image and crop diagnosis.

    Image path : vision LLM → product recommendation (2 sync calls via tools).
    Text path  : ChromaDB retrieval (no LLM) → single async LLM call; tokens
                 stream to the client via astream stream_mode='messages'.
    """
    img = state.get("image_bytes")
    if img:
        # Vision path — sync tools, tokens don't stream (acceptable).
        encoded = base64.b64encode(img).decode("utf-8") if isinstance(img, bytes) else img
        analysis = analyze_crop_image.invoke(encoded)
        recommendation = recommend_product.invoke({"diagnosis": analysis, "crop": state["message"]})
        if "No suitable product found" in recommendation:
            final_text = (
                f"Diagnosis:\n{analysis}\n\n"
                f"Notice: We do not have a specific product in our catalog for this, "
                f"but here is some expert advice:\n\n"
                f"{recommendation.replace('No suitable product found in our catalog for this specific issue.', '')}"
            )
        else:
            final_text = f"Diagnosis:\n{analysis}\n\nRecommended Solution & Usage:\n{recommendation}"
        return {"response_text": final_text}

    # Text path — async LLM call so tokens stream to the client.
    llm = get_chat_llm(temperature=0)
    profile = get_customer_profile(state["session_id"])
    context_str = f"Customer context: {json.dumps(profile)}.\n" if profile else ""

    # Fast ChromaDB retrieval — no LLM involved.
    catalog_context = retrieve_agronomy_knowledge.invoke(state["message"])

    combined_prompt = (
        "You are an agricultural AI support agent.\n"
        "Task: diagnose the crop issue AND recommend a product from the catalog.\n\n"
        "Rules:\n"
        "- Keep your answer under 150 words.\n"
        "- Plain text only — no markdown bold (**).\n"
        "- Do NOT write product name, price, or ingredients in your text.\n"
        "- CRITICAL RULE: If you find a matching product in the catalog, YOU MUST literally write the exact string [PRODUCT: AFXXXX] (e.g., [PRODUCT: AF0058]) at the very end of your answer.\n"
        "- If no catalog product fits, give expert advice with no product tag.\n\n"
        f"{context_str}"
        f"Catalog results:\n{catalog_context}\n\n"
        f"Crop issue: {state['message']}"
    )

    final_text = (await llm.ainvoke(combined_prompt)).content
    return {"response_text": final_text}

async def logistics_node(state: AgentState):
    from db.customer_state import list_orders
    llm = get_chat_llm(temperature=0)
    order_id = state.get("order_id")
    
    if order_id:
        context = get_order_context(state["session_id"], None, order_id)
    else:
        orders_data = list_orders(state["session_id"], None)
        orders = orders_data.get("orders", []) if isinstance(orders_data, dict) else []
        if orders:
            # Provide the latest orders as context
            context = "Customer's recent orders:\n" + "\n".join(
                f"- Order ID: {o['id']}, Status: {o['status']}, Tracking: {o.get('tracking_number')}, ETA: {o.get('estimated_delivery')}, Product: {o.get('product_name')}"
                for o in orders[:3]
            )
        else:
            context = "The customer has no recent orders."
            
    prompt = f"""You are a helpful agricultural customer support agent.
The user is asking about logistics, shipping, or order status.
Here is the available order information for this customer:
{context}

Answer the user's question clearly and concisely. If they have an order, summarize its status and provide the tracking number.
Keep it conversational, plain text without markdown bold asterisks (**).
User message: {state['message']}"""
    
    final_text = (await llm.ainvoke(prompt)).content
    return {"response_text": final_text}

def product_node(state: AgentState):
    recommendation = recommend_product.invoke({"diagnosis": state["message"], "crop": state["message"]})
    
    if "No suitable product found" in recommendation:
        final_text = f"Notice: We do not have a specific product in our catalog for this, but here is some expert advice:\n\n{recommendation.replace('No suitable product found in our catalog for this specific issue.', '')}"
    else:
        final_text = f"Recommended Solution & Usage:\n{recommendation}"
        
    return {"response_text": final_text}

from agent.tools import get_customer_profile

async def general_node(state: AgentState):
    llm = get_chat_llm(temperature=0.3)
    profile = get_customer_profile(state["session_id"])
    memory_context = profile.get("context", "") if profile else ""

    if state["message"] == "INIT_SESSION":
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
            return {"response_text": (await llm.ainvoke(prompt)).content, "intent": "greeting"}

        if memory_context:
            prompt = f"""You are a friendly agricultural expert greeting a returning farmer.
Use ONLY the recalled profile below to open with a warm, personalised check-in:
ask how their crop is doing and whether the previous issue has improved.
Keep it short and conversational, plain text without markdown bold asterisks (**).

Recalled profile:
{memory_context}"""
            return {"response_text": (await llm.ainvoke(prompt)).content, "intent": "greeting"}

        return {"response_text": "Hello! I am Agro-Mind, your agricultural assistant. How can I help you today?", "intent": "greeting"}

    MASTER_SYSTEM_INSTRUCTIONS = """You are an agricultural AI support agent.
Your goal is to provide accurate, evidence-based, and concise answers while minimizing response latency.
Instructions:
- Use only the retrieved context and conversation memory when answering.
- Do not repeat information unnecessarily.
- If multiple retrieved documents contain similar information, summarize them into a single concise answer.
- Limit responses to the information necessary to solve the user's problem.
- When confidence is low or information is insufficient, clearly state the limitation instead of generating speculative content.
- For plant disease diagnosis: State the most likely diagnosis. Provide confidence level. Give the top recommended actions. Avoid lengthy explanations unless requested.
- For logistics inquiries: Return only the relevant order status, ETA, and next steps.
- For follow-up conversations: Use memory to reference previous interactions. Ask at most one relevant follow-up question.
- Prioritize clarity, correctness, and speed.
- Keep responses under 150 words unless the user explicitly requests a detailed explanation."""

    context_str = f"Context from previous interactions: {memory_context}. " if memory_context else ""
    prompt = f"{MASTER_SYSTEM_INSTRUCTIONS}\n\n{context_str}Answer nicely and format your response clearly using plain text without markdown bold asterisks (**). User message: {state['message']}"
    response = (await llm.ainvoke(prompt)).content
    return {"response_text": response}

def _extract_treatment_json(raw: str) -> dict:
    """Parse a treatment JSON object from an LLM reply that may be fenced."""
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


def _save_treatment_in_background(session_id: str, response_text: str, user_message: str) -> None:
    """Extract treatment details from the LLM response and persist them.

    Runs in a daemon thread so the user receives their reply immediately
    without waiting for this extra LLM call to complete.
    """
    from datetime import datetime
    from db.customer_state import add_treatment

    extract_prompt = (
        "Extract the recommended treatment from the text as STRICT JSON with keys "
        '"crop", "disease", "product_id", "duration", "quantity_per_dose", "instructions". '
        "For quantity_per_dose: extract the dosage per application (e.g. '400-600g', '50ml'). "
        "Use null for anything missing. Reply with ONLY the JSON object.\n\n"
        f"Text: {response_text}\n"
        f"User message: {user_message}"
    )
    try:
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
                quantity_per_dose=details.get("quantity_per_dose"),
            )
    except Exception:
        pass


def memory_node(state: AgentState):
    """Stage 4: persist the turn's outcome to relational long-term memory.

    Treatment extraction (which needs an extra LLM call) is handled in a
    background thread inside AgroMindAgent.run() so the user is not blocked.
    """
    intent = state.get("intent")
    session_id = state["session_id"]

    profile_dict = {
        "last_intent": intent,
        "last_recommended_product": state.get("recommended_product_id"),
    }
    if intent in ("Diagnosis", "Product"):
        profile_dict["infestation_note"] = f"{intent}: {state.get('message', '')[:120]}"
    update_customer_profile.invoke(
        {"session_id": session_id, "data": json.dumps(profile_dict)}
    )
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

        _raw_text = final_state.get("response_text", "")
        _intent   = final_state.get("intent", "")
        if _intent in ("Diagnosis", "Product") and "No suitable product found" not in _raw_text:
            # Run in a background thread to prevent blocking the user's response
            threading.Thread(
                target=_save_treatment_in_background,
                args=(session_id, _raw_text, user_text),
                daemon=True
            ).start()

        # Attach a product card ONLY for an explicit recommendation.
        # The recommend_product tool marks a genuine pick with "Product ID: X".
        # Plain catalog IDs mentioned inside general advice (e.g. dilution
        # examples like "AF0039 states…") must NOT trigger a product card, and
        # a "No suitable product found" answer must attach nothing at all.
        text = final_state.get("response_text", "")
        from rag.catalog_loader import get_product_by_id

        products = []
        rec_id = None
        no_product = (
            "No suitable product found" in text
            or "We do not have a specific product" in text
        )
        if not no_product:
            # Match new prompt format: [PRODUCT: THE_ID]
            matches = re.findall(r"\[PRODUCT:\s*([A-Z0-9]+)\]", text)
            # Fallback for old format just in case: Product ID: THE_ID
            if not matches:
                fallback_match = re.search(r"Product ID:\s*([A-Z0-9]+)", text)
                if fallback_match:
                    matches = [fallback_match.group(1)]

            if matches:
                rec_id = matches[0]
                for p_id in matches:
                    product_record = get_product_by_id(p_id)
                    if product_record:
                        products.append(product_record.to_dict())
                
                # Strip product tags from text so they don't show to user
                text = re.sub(r"\[PRODUCT:\s*[A-Z0-9]+\]", "", text).strip()
                text = re.sub(r"Product ID:\s*[A-Z0-9]+.*", "", text, flags=re.IGNORECASE).strip()
                final_state["response_text"] = text

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

    async def stream(
        self,
        session_id: str,
        user_text: str,
        image_bytes: Optional[bytes] = None,
        order_id: Optional[str] = None,
    ):
        """Async generator for streaming responses.

        Yields dicts of two shapes:
          {"type": "token",    "content": "<text chunk>"}
          {"type": "metadata", "data":    {<AgentResponse dict>}}

        Tokens come from async LangGraph nodes (general_node, diagnosis_node
        text path). Nodes that use sync tools (product_node, image diagnosis)
        yield no tokens — their full response arrives in the metadata event.
        """
        # Prepare the user-turn save closure (started AFTER first token to avoid
        # GIL contention with the asyncio event loop during the LLM call).
        _user_turn_started = False
        _user_turn_fn = None
        if user_text != "INIT_SESSION":
            image_b64 = base64.b64encode(image_bytes).decode("utf-8") if image_bytes else None
            def _user_turn_fn(_sid=session_id, _txt=user_text, _b64=image_b64, _img=image_bytes):
                try:
                    CustomerMemory(_sid).append_turn(
                        "user", _txt,
                        has_image=_img is not None,
                        image_base64=_b64,
                    )
                except Exception:
                    pass

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

        # astream with ["values", "messages"] gives us:
        #   "messages" chunks → (AIMessageChunk, metadata) for token streaming
        #   "values"   chunks → complete state snapshot after each node
        final_state: dict = dict(initial_state)

        async for chunk in self.app.astream(
            initial_state,
            stream_mode=["values", "messages"],
        ):
            mode, data = chunk
            if mode == "messages":
                msg_chunk, _ = data
                content = getattr(msg_chunk, "content", "") or ""
                if content:
                    # Defer user-turn DB save until after the first token so the
                    # background thread's GIL activity doesn't delay token delivery.
                    if not _user_turn_started and _user_turn_fn:
                        _user_turn_started = True
                        threading.Thread(target=_user_turn_fn, daemon=True).start()
                    yield {"type": "token", "content": content}
            else:  # "values" — complete state snapshot; last one is final
                final_state = data

        # If no tokens streamed (product/logistics nodes), start DB save now.
        if not _user_turn_started and _user_turn_fn:
            threading.Thread(target=_user_turn_fn, daemon=True).start()

        # ── Post-processing (mirrors run()) ────────────────────────────────
        if final_state.get("response_text"):
            _asst_text = final_state["response_text"]
            threading.Thread(
                target=lambda: CustomerMemory(session_id).append_turn("assistant", _asst_text),
                daemon=True,
            ).start()

        _raw_text = final_state.get("response_text", "")
        _intent   = final_state.get("intent", "")
        if _intent in ("Diagnosis", "Product") and "No suitable product found" not in _raw_text:
            threading.Thread(
                target=_save_treatment_in_background,
                args=(session_id, _raw_text, user_text),
                daemon=True,
            ).start()

        text = _raw_text
        from rag.catalog_loader import get_product_by_id
        products = []
        rec_id = None
        no_product = (
            "No suitable product found" in text
            or "We do not have a specific product" in text
        )
        if not no_product:
            matches = re.findall(r"\[PRODUCT:\s*([A-Z0-9]+)\]", text)
            if not matches:
                fb = re.search(r"Product ID:\s*([A-Z0-9]+)", text)
                if fb:
                    matches = [fb.group(1)]
            if matches:
                rec_id = matches[0]
                for p_id in matches:
                    rec = get_product_by_id(p_id)
                    if rec:
                        products.append(rec.to_dict())
                text = re.sub(r"\[PRODUCT:\s*[A-Z0-9]+\]", "", text).strip()
                text = re.sub(r"Product ID:\s*[A-Z0-9]+.*", "", text, flags=re.IGNORECASE).strip()

        response = AgentResponse(
            intent=final_state.get("intent", "General").lower(),
            safety_risk_detected=final_state.get("safety_risk_detected", False),
            escalate_human=final_state.get("escalate_human", False),
            response_text=text,
            recommended_product_id=rec_id,
            group_purchase_triggered=bool(rec_id),
            human_summary_brief=final_state.get("human_summary_brief"),
            matched_products=products,
            session_id=session_id,
        )
        yield {"type": "metadata", "data": response.to_dict()}
