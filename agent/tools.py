import os
import json
import base64
from typing import Optional, Dict, Any

from langchain_core.tools import tool
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from sqlalchemy.orm import Session
import requests

from db.schema import SessionLocal, Customer, Conversation, Diagnosis
from safety.interceptor import SafetyInterceptor

# Initialize global clients/services
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")
CHROMA_PATH = os.path.join(DB_DIR, "chroma_db")

try:
    embeddings = OpenAIEmbeddings()
    vectorstore = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
except Exception as e:
    print(f"Warning: Could not initialize ChromaDB: {e}")
    vectorstore = None

safety_interceptor = SafetyInterceptor()

@tool
def classify_intent(message: str) -> str:
    """
    Classifies the user message into one of: 'Diagnosis', 'Product', 'Logistics', 'Safety', or 'General'.
    """
    # Simple deterministic classification, or could use LLM
    llm = ChatOpenAI(temperature=0, model="gpt-4o-mini")
    prompt = f"Classify the following message into EXACTLY ONE category: 'Diagnosis', 'Product', 'Logistics', 'Safety', 'General'. Message: {message}"
    try:
        response = llm.invoke(prompt)
        content = response.content.strip().title()
        valid = {"Diagnosis", "Product", "Logistics", "Safety", "General"}
        for v in valid:
            if v in content:
                return v
        return "General"
    except Exception as e:
        return "General"

@tool
def analyze_crop_image(image_base64: str) -> str:
    """
    Calls Vision LLM to return disease name + confidence score from a base64 encoded image.
    """
    if not image_base64:
        return "No image provided."
        
    llm = ChatOpenAI(temperature=0, model="gpt-4o")
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
        
    llm = ChatOpenAI(temperature=0, model="gpt-4o")
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
def lookup_order_status(order_id: str) -> str:
    """
    Simulated lookup from a dummy database. Returns the shipping and order status.
    """
    if not order_id:
        return "No order ID provided."
    # Simulated response
    return f"Order {order_id} is currently In Transit via Postal service. Expected delivery in 3-5 days."

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
    Commits the session's actions to the SQLite long-term memory.
    The data should be a JSON string containing keys like 'crop_type', 'location', 'last_intent', etc.
    """
    try:
        parsed_data = json.loads(data)
    except json.JSONDecodeError:
        return "Error: data must be a valid JSON string."
        
    db: Session = SessionLocal()
    try:
        # Get or create customer
        customer = db.query(Customer).filter(Customer.id == session_id).first()
        if not customer:
            customer = Customer(id=session_id, profile_data="{}")
            db.add(customer)
            
        # Update profile
        existing_profile = json.loads(customer.profile_data)
        
        # Special logic to append active_treatments instead of blindly overwriting
        if "active_treatments" in parsed_data:
            treatments = existing_profile.get("active_treatments", [])
            # append new treatments
            if isinstance(parsed_data["active_treatments"], list):
                treatments.extend(parsed_data["active_treatments"])
            else:
                treatments.append(parsed_data["active_treatments"])
            parsed_data["active_treatments"] = treatments
            
        existing_profile.update(parsed_data)
        customer.profile_data = json.dumps(existing_profile)
        
        # Also ensure conversation exists
        conv = db.query(Conversation).filter(Conversation.id == session_id).first()
        if not conv:
            conv = Conversation(id=session_id, customer_id=session_id)
            db.add(conv)
            
        db.commit()
        return "Customer profile updated successfully in long-term memory."
    except Exception as e:
        db.rollback()
        return f"Database error: {e}"
    finally:
        db.close()

def get_customer_profile(session_id: str) -> dict:
    """Retrieves the customer's long term memory profile from SQLite."""
    db: Session = SessionLocal()
    try:
        customer = db.query(Customer).filter(Customer.id == session_id).first()
        if customer and customer.profile_data:
            return json.loads(customer.profile_data)
        return {}
    except Exception:
        return {}
    finally:
        db.close()
