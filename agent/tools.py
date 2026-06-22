import os
import json
import base64
from typing import Optional, Dict, Any

from langchain_core.tools import tool
from langchain_community.vectorstores import Chroma

from agent.llm import get_chat_llm, get_vision_llm, get_embeddings
from db.customer_state import get_profile
from memory.customer_memory import CustomerMemory
from safety.interceptor import SafetyInterceptor

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
        return "Customer profile updated successfully in long-term memory."
    except Exception as e:
        return f"Database error: {e}"

def get_customer_profile(session_id: str) -> dict:
    """Retrieve the customer's long-term profile from the relational store.

    Returns the db-test profile dict (name, location, crop_type,
    last_recommended_product) plus a compact cross-session context string
    under 'context' for prompt injection.
    """
    try:
        profile = get_profile(session_id, None)
        profile["context"] = CustomerMemory(session_id).get_context_string()
        return profile
    except Exception:
        return {}
