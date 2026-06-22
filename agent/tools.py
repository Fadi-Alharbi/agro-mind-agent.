import os
import json
import base64
import threading
import time
from typing import Optional, Dict, Any

from langchain_core.tools import tool
from langchain_community.vectorstores import Chroma

from agent.llm import get_chat_llm, get_vision_llm, get_embeddings
from db.customer_state import get_profile
from memory.customer_memory import CustomerMemory
from safety.interceptor import SafetyInterceptor

# ── Profile cache ──────────────────────────────────────────────────────────────
# get_customer_profile opens 3 separate remote MySQL connections (~5s total).
# Caching in memory reduces this to 0ms for every message after the first.
_PROFILE_TTL = 60.0  # seconds before re-fetching from DB
_profile_cache: dict[str, tuple[float, dict]] = {}
_profile_fetching: set[str] = set()
_profile_lock = threading.Lock()


def _get_context_string_no_init(session_id: str) -> str:
    """Read the customer context string WITHOUT creating the session row.

    CustomerMemory.__init__ calls _ensure_session() which INSERTs a new row if
    none exists.  When two background threads run concurrently for the same
    session_id (_bg_user_turn + _fetch_profile_bg), both try to INSERT the same
    primary key — one waits on the MySQL row-lock for 5+ seconds before failing
    with a duplicate-key error.  This function avoids _ensure_session() entirely.
    """
    from db.engine import SessionLocal
    from db.models import Customer, Message, Session as DBSession
    from sqlalchemy import select, func as sa_func

    db = SessionLocal()
    try:
        sess = db.get(DBSession, session_id)
        if sess is None:
            return ""  # session not yet created; context will be empty

        customer = db.get(Customer, sess.customer_id) if sess.customer_id else None

        # Gather all session IDs for this customer (cross-chat memory)
        if sess.customer_id:
            all_session_ids = list(
                db.scalars(
                    select(DBSession.id).where(DBSession.customer_id == sess.customer_id)
                ).all()
            )
        else:
            all_session_ids = [session_id]

        recent_issues = db.scalars(
            select(Message.content)
            .where(Message.session_id.in_(all_session_ids), Message.intent == "diagnosis")
            .order_by(Message.id.desc())
            .limit(3)
        ).all()
        interaction_count = db.scalar(
            select(sa_func.count(Message.id)).where(Message.session_id.in_(all_session_ids))
        )

        parts: list[str] = ["[Customer Profile]"]
        if len(all_session_ids) > 1:
            parts.append(f"- Returning customer ({len(all_session_ids)} chats)")
        if customer and customer.crop_type:
            parts.append(f"- Crop: {customer.crop_type}")
        if customer and customer.location:
            parts.append(f"- Location: {customer.location}")
        if customer and customer.last_recommended_product:
            parts.append(f"- Last recommended product: {customer.last_recommended_product}")
        if recent_issues:
            parts.append(f"- Recent issues: {'; '.join(i[:120] for i in recent_issues)}")
        if interaction_count:
            parts.append(f"- Total interactions: {interaction_count}")

        return "\n".join(parts) if len(parts) > 1 else ""
    finally:
        db.close()


def _fetch_profile_bg(session_id: str) -> None:
    """Background thread: fetch from DB and populate cache.

    Uses _get_context_string_no_init to avoid racing with _bg_user_turn on
    MySQL session-row insertion (which previously caused 5+ second lock waits).
    """
    try:
        profile = get_profile(session_id, None)
        profile["context"] = _get_context_string_no_init(session_id)
        with _profile_lock:
            _profile_cache[session_id] = (time.time(), profile)
    except Exception:
        with _profile_lock:
            _profile_cache[session_id] = (time.time(), {})
    finally:
        with _profile_lock:
            _profile_fetching.discard(session_id)

# Initialize global clients/services
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")
CHROMA_PATH = os.path.join(DB_DIR, "chroma_db")

try:
    embeddings = get_embeddings()
    vectorstore = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
except Exception as e:
    print(f"Warning: Could not initialize ChromaDB: {e}")
    vectorstore = None

safety_interceptor = SafetyInterceptor()

@tool
def classify_intent(message: str) -> str:
    """
    Classifies the user message into one of: 'Diagnosis', 'Product', 'Logistics', or 'General'.
    Uses fast keyword matching — no LLM call needed.
    """
    msg_lower = message.lower()

    _LOGISTICS = [
        "order", "shipping", "delivery", "track", "courier", "refund", "return",
        "invoice", "packaging", "damage", "receipt", "arrived", "dispatch",
        "transit", "postal", "parcel", "shipment", "sent", "express", "when will",
        "how long", "delivery time",
    ]
    _DIAGNOSIS = [
        "disease", "pest", "leaf", "leaves", "spot", "spots", "yellow", "yellowing",
        "wilting", "fungus", "blight", "rot", "dying", "infected", "mold", "mould",
        "bug", "insect", "symptom", "sick", "wrong with", "what's wrong", "problem with",
        "aphid", "mite", "rust", "scab", "wilt", "mosaic", "powdery", "downy",
        "necrosis", "lesion", "canker", "deficiency", "curl", "white powder",
        "black spot", "brown spot", "my crop", "my plant", "my tomato", "my rice",
        "my strawberry", "my citrus", "not growing", "falling off",
    ]
    _PRODUCT = [
        "recommend", "which product", "buy", "purchase", "price", "dosage",
        "how much", "effective", "best product", "what to use", "herbicide",
        "pesticide", "fungicide", "insecticide", "treatment for", "what medicine",
        "which medicine", "what chemical", "suggest",
    ]

    logistics_score = sum(1 for k in _LOGISTICS if k in msg_lower)
    diagnosis_score = sum(1 for k in _DIAGNOSIS if k in msg_lower)
    product_score   = sum(1 for k in _PRODUCT   if k in msg_lower)

    best = max(logistics_score, diagnosis_score, product_score)
    if best == 0:
        return "General"
    if logistics_score == best:
        return "Logistics"
    if diagnosis_score >= product_score:
        return "Diagnosis"
    return "Product"

@tool
def analyze_crop_image(image_base64: str) -> str:
    """
    Calls Vision LLM to return disease name + confidence score from a base64 encoded image.
    """
    if not image_base64:
        return "No image provided."
        
    llm = get_vision_llm(temperature=0)
    prompt = "Analyze this crop image. Identify the plant and any disease or pest present. Return the disease name and a confidence score."
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
        ]}
    ]
    try:
        response = llm.invoke(messages)
        return response.content
    except Exception as e:
        return f"Error analyzing image: {e}"

@tool
def retrieve_agronomy_knowledge(query: str) -> str:
    """
    Queries the Vector DB built from the catalog to find relevant products and their details.
    Strict constraint: The agent MUST NOT hallucinate product data outside of what is retrieved.
    """
    if not vectorstore:
        return "Knowledge base unavailable."
    
    docs = vectorstore.similarity_search(query, k=6)
    if not docs:
        return "No matching products found in the catalog."
    
    results = []
    for d in docs:
        results.append(d.page_content)
    
    return "\n\n---\n\n".join(results)

@tool
def recommend_product(diagnosis: str, crop: str) -> str:
    """
    Retrieves product matches from the catalog based on the diagnosis and crop, and verifies if they help.
    """
    # Create a broad query to capture general fungicides or treatments
    query = f"treatment fungicide pesticide for {crop} disease {diagnosis}"
    raw_results = retrieve_agronomy_knowledge.invoke(query)
    
    if "No matching products found" in raw_results:
        return raw_results
        
    llm = get_chat_llm(temperature=0)
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

    prompt = f"""
    {MASTER_SYSTEM_INSTRUCTIONS}
    
    Review the following products from our catalog to see if any can treat the diagnosed issue.
    
    Diagnosis: {diagnosis}
    Crop: {crop}
    
    Raw Catalog Results:
    {raw_results}
    
    Instruction:
    Provide your diagnosis and general expert advice on how to treat the problem. 
    If a product from the catalog mentions that "practice has shown" it is effective for the crop, or if it is generally suitable for the problem, YOU MUST recommend it. Do NOT write any pedantic warnings, legal disclaimers, or explanations about whether the product is "officially registered" for the crop. Treat "practice has shown" as a fully valid recommendation.
    You MUST NOT write the product's name, price, dosage, ingredients, or any other details about the product in your text response. The text response must only contain your general agricultural advice. The system will display the product cards automatically.
    Instead, at the very end of your response, output a hidden tag for each recommended product exactly in this format: `[PRODUCT: THE_ID]`.
    
    Example: "This looks like early blight. To treat it, ensure good air circulation and apply a suitable broad-spectrum fungicide as directed. [PRODUCT: AF0035] [PRODUCT: BG0012]"
    
    Format your response clearly using plain text spacing and newlines. DO NOT use markdown bold asterisks (**) anywhere in your response.
    
    If NONE of the products help with this specific diagnosis, YOU MUST reply with exactly: "No suitable product found in our catalog for this specific issue." followed by your best expert agricultural advice on how the user can manage or treat the problem using general methods. Do not invent catalog products.
    """
    return llm.invoke(prompt).content

@tool
def check_product_safety(product_id: str) -> str:
    """
    Extracts safety/usage constraints for a given product ID.
    """
    if not vectorstore:
        return "Knowledge base unavailable."
        
    # We can search the vectorstore for the product ID specifically
    docs = vectorstore.similarity_search(f"Product ID: {product_id}", k=1)
    if not docs:
        return f"Safety constraints not found for product {product_id}."
        
    return f"Safety constraints for {product_id}:\n{docs[0].page_content}"

@tool
def detect_escalation_risk(message: str) -> bool:
    """
    Checks if a safety/poisoning intent is detected in the message. 
    Returns True if an escalation is required.
    """
    result = safety_interceptor.check(message)
    return not result.is_safe

@tool
def create_human_alert() -> str:
    """
    Stops autonomous product recommendations, alerts a human, and provides safe fallback text.
    """
    return (
        "Dear customer, your safety and life are of utmost importance. "
        "Automated support has been stopped to protect your health. "
        "A human expert has been alerted to assist you immediately. "
        "Please know that you are not alone — help is on the way. "
        "If you are in immediate danger, please call your local emergency services."
    )

@tool
def update_customer_profile(session_id: str, data: str) -> str:
    """
    Commits the session's actions to the relational long-term memory (db-test schema).
    The data should be a JSON string with keys like 'crop_type', 'location',
    'last_intent', 'last_recommended_product'.
    """
    try:
        parsed_data = json.loads(data)
    except json.JSONDecodeError:
        return "Error: data must be a valid JSON string."

    try:
        CustomerMemory(session_id).update(
            crop_type=parsed_data.get("crop_type"),
            location=parsed_data.get("location"),
            last_intent=parsed_data.get("last_intent"),
            infestation_note=parsed_data.get("infestation_note"),
            last_product_id=(
                parsed_data.get("last_recommended_product")
                or parsed_data.get("last_product_id")
            ),
        )
        invalidate_profile_cache(session_id)
        return "Customer profile updated successfully in long-term memory."
    except Exception as e:
        return f"Database error: {e}"

def get_customer_profile(session_id: str) -> dict:
    """Return customer profile, served from memory cache (0 ms after first fetch).

    First call for a session_id returns {} immediately and starts a background
    DB fetch (~5s). The next message (and all subsequent ones) gets the real
    profile from cache at 0ms. Cache TTL is 60s; invalidated on profile update.
    """
    with _profile_lock:
        entry = _profile_cache.get(session_id)
        if entry:
            ts, profile = entry
            if time.time() - ts < _PROFILE_TTL:
                return profile  # Cache hit — 0 ms

        # Cache miss or stale — trigger background fetch, return stale/empty now
        if session_id not in _profile_fetching:
            _profile_fetching.add(session_id)
            threading.Thread(
                target=_fetch_profile_bg, args=(session_id,), daemon=True
            ).start()

        return entry[1] if entry else {}


def invalidate_profile_cache(session_id: str) -> None:
    """Expire the cached profile so the next call re-fetches from DB."""
    with _profile_lock:
        _profile_cache.pop(session_id, None)
        _profile_fetching.discard(session_id)
