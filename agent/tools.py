"""
agent/tools.py
──────────────
The agent's capability tools — Fadi's LangGraph tool design, adapted to our
team's stack:

  • All LLMs/embeddings come from agent.llm (Qwen via DashScope), never OpenAI.
  • Retrieval uses the Chroma store built by rag.ingest (Qwen embeddings).
  • Long-term memory goes through OUR relational CustomerMemory, which links a
    returning customer across chats via external_id — not Fadi's per-session
    JSON blob.

The eight @tool capabilities map to the proposal's eight tools (slide 4).
Memory persistence is internal plumbing, exposed as plain helpers below.
"""

from __future__ import annotations

import base64
import os
from typing import Optional

from langchain_chroma import Chroma
from langchain_core.tools import tool

from agent.llm import get_chat_llm, get_embeddings, get_vision_llm
from memory.customer_memory import CustomerMemory
from rag.catalog_loader import get_product_by_id
from safety.interceptor import SafetyInterceptor

# ── Shared services ────────────────────────────────────────────────────────────
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")
CHROMA_PATH = os.path.join(DB_DIR, "chroma_db")
COLLECTION_NAME = "agronomy_catalog"

try:
    vectorstore = Chroma(
        persist_directory=CHROMA_PATH,
        embedding_function=get_embeddings(),
        collection_name=COLLECTION_NAME,
    )
except Exception as e:  # noqa: BLE001
    print(f"Warning: Could not initialize ChromaDB: {e}")
    vectorstore = None

safety_interceptor = SafetyInterceptor()


# ── 1. Intent classification ───────────────────────────────────────────────────
@tool
def classify_intent(message: str) -> str:
    """Classify a message into one of: Diagnosis, Product, Logistics, Safety, General."""
    llm = get_chat_llm(temperature=0)
    prompt = (
        "Classify the following message into EXACTLY ONE category: "
        "'Diagnosis', 'Product', 'Logistics', 'Safety', 'General'. "
        f"Reply with only the category word. Message: {message}"
    )
    try:
        content = llm.invoke(prompt).content.strip().title()
        for v in ("Diagnosis", "Product", "Logistics", "Safety", "General"):
            if v in content:
                return v
        return "General"
    except Exception:
        return "General"


# ── 2. Vision diagnosis ─────────────────────────────────────────────────────────
@tool
def analyze_crop_image(image_base64: str) -> str:
    """Identify the plant and any disease/pest from a base64-encoded crop image."""
    if not image_base64:
        return "No image provided."

    llm = get_vision_llm(temperature=0)
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": (
                "Analyze this crop image. Identify the plant and any disease or pest "
                "present. Return the disease name and a confidence score."
            )},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
        ]},
    ]
    try:
        return llm.invoke(messages).content
    except Exception as e:  # noqa: BLE001
        return f"Error analyzing image: {e}"


# ── 3. Knowledge retrieval (RAG) ────────────────────────────────────────────────
@tool
def retrieve_agronomy_knowledge(query: str) -> str:
    """Retrieve relevant catalog products from the vector DB. Never invent products."""
    if not vectorstore:
        return "Knowledge base unavailable."
    docs = vectorstore.similarity_search(query, k=6)
    if not docs:
        return "No matching products found in the catalog."
    return "\n\n---\n\n".join(d.page_content for d in docs)


# ── 4. Product recommendation ───────────────────────────────────────────────────
@tool
def recommend_product(diagnosis: str, crop: str) -> str:
    """Recommend a catalog product for a diagnosis/crop, grounded only in retrieved data."""
    query = f"treatment fungicide pesticide for {crop} disease {diagnosis}"
    raw_results = retrieve_agronomy_knowledge.invoke(query)
    if "No matching products found" in raw_results:
        return raw_results

    llm = get_chat_llm(temperature=0)
    prompt = f"""
    You are an expert agriculturalist. Review the following products from our catalog to see if any can treat the diagnosed issue.

    Diagnosis: {diagnosis}
    Crop: {crop}

    Raw Catalog Results:
    {raw_results}

    Instruction:
    If a product clearly helps with the diagnosis (including broad-spectrum fungicides/pesticides known to treat such issues for this crop), recommend it.
    You must format your recommendation to explicitly include "Product ID: [THE_ID]" so it can be parsed.
    Example: "Product ID: AF0035 - Universal Fungicide Liquid. This is a broad-spectrum fungicide suitable for tomatoes that will treat the blight."

    IMPORTANT: You must thoroughly explain HOW the product solves the problem and clearly state the dosage and instructions on how to use it based on the catalog data.
    Reply in the same language as the user's message. DO NOT use markdown bold asterisks (**) anywhere.

    If NONE of the products help with this specific diagnosis, YOU MUST reply with exactly: "No suitable product found in our catalog for this specific issue." followed by your best expert agricultural advice using general methods. Do not invent catalog products.
    """
    return llm.invoke(prompt).content


# ── 5. Product safety constraints ───────────────────────────────────────────────
@tool
def check_product_safety(product_id: str) -> str:
    """Return safety/usage constraints for a given product ID from the catalog."""
    record = get_product_by_id(product_id.strip())
    if not record:
        return f"Safety constraints not found for product {product_id}."
    return (
        f"Safety constraints for {record.product_id}:\n"
        f"Product Name: {record.product_name}\n"
        f"English Name: {record.english_name}\n"
        f"Category/Type: {record.product_type}\n"
        f"Target Crops: {record.crops}\n"
        f"Active Ingredients: {record.main_ingredients}\n"
        f"Usage Instructions: {record.how_to_use}\n"
        f"Dosage/Dilution: {record.water_ratio}\n"
    )


# ── 6. Order status ─────────────────────────────────────────────────────────────
@tool
def lookup_order_status(order_id: str) -> str:
    """Look up the shipping/order status for an order ID (simulated)."""
    if not order_id:
        return "No order ID provided."
    return f"Order {order_id} is currently In Transit via Postal service. Expected delivery in 3-5 days."


# ── 7. Safety / escalation detection ────────────────────────────────────────────
@tool
def detect_escalation_risk(message: str) -> bool:
    """Return True if the message indicates a safety/poisoning risk needing escalation."""
    return not safety_interceptor.check(message).is_safe


# ── 8. Human alert ──────────────────────────────────────────────────────────────
@tool
def create_human_alert() -> str:
    """Stop automated recommendations and return safe fallback text for a human handoff."""
    return (
        "Dear customer, your safety and life are of utmost importance. "
        "Automated support has been stopped to protect your health. "
        "A human expert has been alerted to assist you immediately. "
        "Please know that you are not alone — help is on the way. "
        "If you are in immediate danger, please call your local emergency services."
    )


# ── Long-term memory plumbing (our relational, cross-session store) ─────────────
def get_customer_context(session_id: str, external_id: Optional[str] = None) -> str:
    """Cross-session profile string for prompt injection (empty if first contact)."""
    try:
        return CustomerMemory(session_id, external_id=external_id).get_context_string()
    except Exception:
        return ""


def persist_memory(
    session_id: str,
    external_id: Optional[str] = None,
    *,
    last_intent: Optional[str] = None,
    last_product_id: Optional[str] = None,
    infestation_note: Optional[str] = None,
    crop_type: Optional[str] = None,
    location: Optional[str] = None,
) -> None:
    """Persist the turn's outcome to the returning-customer profile."""
    try:
        CustomerMemory(session_id, external_id=external_id).update(
            last_intent=last_intent,
            last_product_id=last_product_id,
            infestation_note=infestation_note,
            crop_type=crop_type,
            location=location,
        )
    except Exception:
        pass  # Memory is best-effort; never fail the request over it.
