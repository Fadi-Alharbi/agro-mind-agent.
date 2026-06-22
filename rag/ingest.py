import os
import csv
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from rag.catalog_loader import get_catalog
from agent.llm import get_embeddings
from dotenv import load_dotenv

load_dotenv()

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")
CHROMA_PATH = os.path.join(DB_DIR, "chroma_db")
RAG_DIR = os.path.dirname(os.path.abspath(__file__))

def ingest_catalog():
    print("Loading catalog...")
    products = get_catalog()
    documents = []
    if products:
        print(f"Loaded {len(products)} products. Preparing documents...")
        for p in products:
            content = (
                f"Product ID: {p.product_id}\n"
                f"Product Name: {p.product_name}\n"
                f"English Name: {p.english_name}\n"
                f"Category/Type: {p.product_type}\n"
                f"Target Crops: {p.crops}\n"
                f"Active Ingredients: {p.main_ingredients}\n"
                f"Usage Instructions: {p.how_to_use}\n"
                f"Dosage/Dilution: {p.water_ratio}\n"
                f"Price: Group ¥{p.group_price:.0f}, Single ¥{p.single_price:.0f}\n"
            )
            metadata = {
                "product_id": p.product_id,
                "product_name": p.product_name,
                "product_type": p.product_type,
                "crops": p.crops,
                "group_price": p.group_price,
                "single_price": p.single_price,
                "doc_type": "product"
            }
            documents.append(Document(page_content=content, metadata=metadata))
    
    # Ingest Crop Recommendations
    crop_csv_path = os.path.join(RAG_DIR, "Crop_recommendation.csv")
    if os.path.exists(crop_csv_path):
        print(f"Loading Crop recommendations from {crop_csv_path}...")
        try:
            with open(crop_csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    label = row.get("label", "")
                    content = (
                        f"Optimal Conditions for Crop: {label}\n"
                        f"Nitrogen (N) required: {row.get('N')}\n"
                        f"Phosphorus (P) required: {row.get('P')}\n"
                        f"Potassium (K) required: {row.get('K')}\n"
                        f"Temperature: {row.get('temperature')} °C\n"
                        f"Humidity: {row.get('humidity')} %\n"
                        f"pH value: {row.get('ph')}\n"
                        f"Rainfall: {row.get('rainfall')} mm\n"
                    )
                    metadata = {"doc_type": "crop_recommendation", "crop": label}
                    documents.append(Document(page_content=content, metadata=metadata))
            print("Crop recommendations loaded.")
        except Exception as e:
            print(f"Error loading {crop_csv_path}: {e}")

    # Ingest Farmer Advisory (sample 500 rows to save time/cost)
    advisory_csv_path = os.path.join(RAG_DIR, "farmer_advisory_full.csv")
    if os.path.exists(advisory_csv_path):
        print(f"Loading Farmer Advisory sample from {advisory_csv_path}...")
        try:
            with open(advisory_csv_path, 'r', encoding='utf-8', errors='replace') as f:
                reader = csv.DictReader(f)
                count = 0
                for row in reader:
                    if count >= 500:
                        break
                    crop = row.get("Crop", "")
                    prob = row.get("Problem_Type", "")
                    content = (
                        f"Farmer Case / Advisory\n"
                        f"Crop: {crop}\n"
                        f"Problem Type: {prob}\n"
                        f"Farmer Message: {row.get('Farmer_Message')}\n"
                        f"Advisor Reply: {row.get('Advisor_Reply')}\n"
                        f"Recommended Product: {row.get('Product_Recommended')}\n"
                    )
                    metadata = {"doc_type": "advisory", "crop": crop, "problem": prob}
                    documents.append(Document(page_content=content, metadata=metadata))
                    count += 1
            print(f"Loaded {count} farmer advisory cases.")
        except Exception as e:
            print(f"Error loading {advisory_csv_path}: {e}")

    if not documents:
        print("No documents to ingest.")
        return

    print("Initializing Qwen (DashScope) Embeddings...")
    embeddings = get_embeddings()
    
    print(f"Ingesting {len(documents)} total documents into ChromaDB at {CHROMA_PATH}...")
    vectorstore = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=CHROMA_PATH
    )
    print("Ingestion complete. ChromaDB is ready.")

if __name__ == "__main__":
    ingest_catalog()
