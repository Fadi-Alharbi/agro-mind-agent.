from typing import TypedDict, Annotated, Optional
import base64
import operator
import json
import re
import threading

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage

from agent.llm import get_chat_llm
from db.customer_state import get_order, get_order_context, get_pesticide_memory
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
from agent.web_context import (
    asks_for_web_context,
    extract_location_hint,
    get_weather_context,
    format_web_context_for_prompt,
)

# Backward-compatible alias used by older tests. In production this still
# returns the Qwen/DashScope-configured LangChain client from agent.llm.
ChatOpenAI = get_chat_llm

_ORDER_ID_RE = re.compile(r"\bPDD\d{14}-\d+-\d+\b", re.IGNORECASE)
_USAGE_TERMS = (
    "how to use", "how i use", "how do i use", "use it", "use this",
    "usage", "directions", "instruction", "instructions", "dilution",
    "dilute", "mix", "mixed", "water ratio", "dosage", "dose",
    "application rate", "spray rate",
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


class _NoopMemory:
    """Fallback when the persistence layer is unavailable."""

    def append_turn(self, *args, **kwargs) -> int:
        return 0

    def chat_history(self) -> list[dict]:
        return []


def _session_memory(session_id: str):
    try:
        return CustomerMemory(session_id)
    except Exception:
        return _NoopMemory()


def _recent_chat_history(session_id: str, current_message: str, limit: int = 6) -> list[dict]:
    """Read recent turns, excluding the current user message when already saved."""
    try:
        history = _session_memory(session_id).chat_history()
    except Exception:
        return []

    if history and history[-1].get("role") == "user" and history[-1].get("text") == current_message:
        history = history[:-1]
    return history[-limit:]


def _contextualize_short_sales_reply(session_id: str, message: str) -> Optional[str]:
    """Expand short farmer replies using the immediately preceding chat context."""
    stripped = (message or "").strip()
    if not stripped:
        return None

    short_weed_replies = {
        "متسلقة", "متسلقه", "متسلق", "متسلقات",
        "ورقية", "عريضة", "عريضه", "عشبية", "عشبيه",
        "حشائش", "حشايش", "اعشاب", "أعشاب",
    }
    if stripped not in short_weed_replies and len(stripped.split()) > 3:
        return None

    history_text = " ".join(
        turn.get("text", "") for turn in _recent_chat_history(session_id, stripped)
    ).lower()
    weed_context = any(term in history_text for term in (
        "حشائش", "حشايش", "اعشاب", "أعشاب", "weed", "weeds", "herbicide",
    ))
    orchard_context = any(term in history_text for term in (
        "حمضيات", "بستان", "ليمون", "برتقال", "citrus", "orchard", "fruit tree",
    ))

    if stripped in short_weed_replies and weed_context:
        crop_context = "citrus orchard" if orchard_context else "the crop mentioned earlier"
        return (
            "The farmer is answering a previous clarification question about weed type. "
            f"Context: {crop_context}. Weed type: {stripped}. "
            "Recommend a suitable catalog product now; do not require a structured prompt."
        )

    return None


async def _llm_content(llm, prompt: str) -> str:
    """Call async LLMs when available, with sync fallback for test doubles."""
    try:
        result = llm.ainvoke(prompt)
        if hasattr(result, "__await__"):
            return (await result).content
    except TypeError:
        pass
    return llm.invoke(prompt).content


def _extract_order_id(message: str) -> Optional[str]:
    match = _ORDER_ID_RE.search(message or "")
    return match.group(0) if match else None


def _is_usage_question(message: str) -> bool:
    normalized = (message or "").casefold()
    return any(term in normalized for term in _USAGE_TERMS)


def _find_catalog_product_in_text(message: str):
    from rag.catalog_loader import get_catalog, get_product_by_id

    raw = message or ""
    normalized = raw.casefold()

    for token in re.findall(r"\b[A-Z]{2}\d{4}\b", raw, flags=re.IGNORECASE):
        product = get_product_by_id(token)
        if product:
            return product

    products = sorted(
        get_catalog(),
        key=lambda rec: max(len(rec.product_name or ""), len(rec.english_name or "")),
        reverse=True,
    )
    for product in products:
        for name in (product.product_name, product.english_name):
            if name and len(name) >= 4 and name.casefold() in normalized:
                return product

    return None


def _resolve_usage_product(state: AgentState):
    from rag.catalog_loader import get_product_by_id

    order_id = state.get("order_id") or _extract_order_id(state.get("message", ""))
    if order_id:
        try:
            order = get_order(state["session_id"], None, order_id)
        except ValueError:
            return None, f"Order {order_id} was not found for this customer."

        product_id = order.get("product_id")
        product = get_product_by_id(product_id) if product_id else None
        if product:
            return product, None
        return None, f"Order {order_id} does not have a catalog product attached."

    product = _find_catalog_product_in_text(state.get("message", ""))
    if product:
        return product, None

    try:
        memory = get_pesticide_memory(state["session_id"], None)
    except Exception:
        memory = {}
    remembered = memory.get("current") if isinstance(memory, dict) else None
    remembered_product_id = remembered.get("product_id") if remembered else None
    if remembered_product_id:
        product = get_product_by_id(remembered_product_id)
        if product:
            return product, None

    return None, None


def _format_product_usage(product) -> str:
    name = product.english_name or product.product_name
    lines = [
        f"Usage for {name} ({product.product_id}):",
    ]

    if product.main_ingredients:
        lines.append(f"Active ingredient: {product.main_ingredients}")
    if product.water_ratio:
        lines.append(f"Dilution: {product.water_ratio}.")

    how_to = product.how_to_use or ""
    if "Dilute 1000-1500 times" in how_to:
        lines.append("For citrus spider mites: dilute 1000-1500 times and spray.")
    elif how_to:
        first_instruction = next(
            (line.strip() for line in how_to.splitlines() if line.strip() and not line.startswith("|")),
            "",
        )
        if first_instruction:
            lines.append(f"Label direction: {first_instruction}")

    if "underside of the leaves" in how_to:
        lines.append("Spray evenly and thoroughly, especially the underside of leaves.")
    if "windy days" in how_to or "rain is expected" in how_to:
        lines.append("Do not spray on windy days or when rain is expected within 1 hour.")
    if "safe interval" in how_to and "21 days" in how_to:
        lines.append("For citrus, keep a 21-day pre-harvest safety interval.")
    if "maximum number of uses per season is once" in how_to:
        lines.append("Do not use more than once per season on citrus.")

    lines.append(
        "Wear protective gloves/clothing, avoid high heat, and follow the physical product label if it differs from this catalog record."
    )
    return "\n".join(lines)


_UNKNOWN_USAGE_PRODUCT_MESSAGE = (
    "Which product are you asking about? Please send the product name, catalog code, "
    "order ID, or select the product first so I can give the exact mixing ratio. "
    "Do not guess dilution rates across medicines."
)


# --- Graph Nodes ---

def safety_check_node(state: AgentState):
    """Stage 1: Check for safety risks"""
    msg = state["message"]
    risk = detect_escalation_risk.invoke(msg)
    if risk:
        alert_text = create_human_alert.invoke({
            "session_id": state["session_id"],
            "message": msg,
            "risk_category": "safety",
        })
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

    contextual_message = _contextualize_short_sales_reply(
        state["session_id"], state["message"]
    )
    if contextual_message:
        return {"intent": "Product", "message": contextual_message}

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

    final_text = await _llm_content(llm, combined_prompt)
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
    
    final_text = await _llm_content(llm, prompt)
    return {"response_text": final_text}

def product_node(state: AgentState):
    if _is_usage_question(state["message"]):
        product, error = _resolve_usage_product(state)
        if error:
            return {"response_text": error}
        if product:
            return {"response_text": _format_product_usage(product)}
        return {"response_text": _UNKNOWN_USAGE_PRODUCT_MESSAGE}

    recommendation = recommend_product.invoke({"diagnosis": state["message"], "crop": state["message"]})
    
    if "No suitable product found" in recommendation:
        final_text = f"Notice: We do not have a specific product in our catalog for this, but here is some expert advice:\n\n{recommendation.replace('No suitable product found in our catalog for this specific issue.', '')}"
    else:
        final_text = f"Recommended Solution & Usage:\n{recommendation}"
        
    return {"response_text": final_text}

from agent.tools import get_customer_profile

async def general_node(state: AgentState):
    llm = ChatOpenAI(temperature=0.3)

    # Memory/profile should come from DB-backed profile.
    # Cache is only optimization inside get_customer_profile, not the source of truth.
    try:
        profile = get_customer_profile(state["session_id"])
    except Exception:
        profile = {}

    memory_context = profile.get("context", "") if profile else ""

    # Optional web/weather context.
    # Use it only for weather, season, local spray timing, and climate-related questions.
    # Never use it for product identity, dosage, price, or catalog claims.
    web_context_prompt = ""
    if (
        asks_for_web_context
        and extract_location_hint
        and get_weather_context
        and format_web_context_for_prompt
        and asks_for_web_context(state["message"])
    ):
        location = extract_location_hint(state["message"])

        if location:
            weather_context = get_weather_context(location)
            web_context_prompt = format_web_context_for_prompt(weather_context)
        else:
            return {
                "response_text": (
                    "I can use local weather context for spray timing, but I need the city first. "
                    "Please send the city name and the crop issue."
                ),
                "intent": "General",
            }

    if state["message"] == "INIT_SESSION":
        from datetime import datetime
        from db.customer_state import get_active_treatments

        try:
            treatments = get_active_treatments(state["session_id"], None)
        except Exception:
            treatments = []

        if treatments:
            today = datetime.now().strftime("%Y-%m-%d")

            prompt = f"""You are a friendly agricultural expert checking up on a returning farmer.

Today's date is {today}.

Customer memory:
{memory_context or "No previous memory available."}

Active treatments on record:
{json.dumps(treatments, ensure_ascii=False)}

Instructions:
1. Identify the crop and the issue being treated.
2. Calculate how many days have passed since start_date if available.
3. Ask how the crop is doing.
4. Ask whether the treatment was applied today.
5. If duration is available, remind them how many days are left.
6. Keep it short, warm, and conversational.
7. Plain text only. Do not use markdown bold asterisks (**)."""
            return {
                "response_text": await _llm_content(llm, prompt),
                "intent": "greeting",
            }

        if memory_context:
            prompt = f"""You are a friendly agricultural expert greeting a returning farmer.

Use ONLY the recalled profile below to open with a short personalized check-in.
Ask how their crop is doing and whether the previous issue has improved.

Recalled profile:
{memory_context}

Instructions:
- Keep it short.
- Ask one relevant follow-up question.
- Plain text only.
- Do not use markdown bold asterisks (**)."""
            return {
                "response_text": await _llm_content(llm, prompt),
                "intent": "greeting",
            }

        return {
            "response_text": (
                "Hello! I am Agro-Mind, your agricultural assistant. "
                "How can I help you today?"
            ),
            "intent": "greeting",
        }

    MASTER_SYSTEM_INSTRUCTIONS = """You are an agricultural AI support agent.

Your goal is to provide accurate, evidence-based, and concise answers.

Instructions:
- Use only retrieved context, catalog context, and conversation memory when answering.
- Do not invent product names, product IDs, dosage, prices, or catalog claims.
- If information is insufficient, clearly say what is missing.
- For plant disease questions, give likely diagnosis and practical next steps.
- For logistics inquiries, return only relevant order status, ETA, and next steps.
- For follow-up conversations, use memory to reference previous interactions.
- Ask at most one relevant follow-up question.
- Keep responses under 150 words unless the user asks for details.
- Plain text only. Do not use markdown bold asterisks (**)."""

    context_parts = []

    if memory_context:
        context_parts.append(f"Conversation/customer memory:\n{memory_context}")

    if web_context_prompt:
        context_parts.append(web_context_prompt)

    context_str = "\n\n".join(context_parts)

    prompt = f"""{MASTER_SYSTEM_INSTRUCTIONS}

{context_str}

User message:
{state["message"]}

Answer clearly and concisely."""

    response = await _llm_content(llm, prompt)
    return {"response_text": response}
# //
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
        mem = _session_memory(session_id)
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
        # Persist the user turn before the agent runs so reopening the session
        # immediately still shows the user's message.
        if user_text != "INIT_SESSION":
            image_b64 = base64.b64encode(image_bytes).decode("utf-8") if image_bytes else None
            try:
                _session_memory(session_id).append_turn(
                    "user",
                    user_text,
                    has_image=image_bytes is not None,
                    image_base64=image_b64,
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
                    yield {"type": "token", "content": content}
            else:  # "values" — complete state snapshot; last one is final
                final_state = data

        # ── Post-processing (mirrors run()) ────────────────────────────────
        if final_state.get("response_text"):
            _asst_text = final_state["response_text"]
            threading.Thread(
                target=lambda: _session_memory(session_id).append_turn("assistant", _asst_text),
                daemon=True,
            ).start()

        _raw_text = final_state.get("response_text", "")
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
