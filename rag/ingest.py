import os
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from rag.catalog_loader import get_catalog
from dotenv import load_dotenv

load_dotenv()

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")
CHROMA_PATH = os.path.join(DB_DIR, "chroma_db")

def ingest_catalog():
    print("Loading catalog...")
    products = get_catalog()
    if not products:
        print("No products found in catalog. Check tra/ directory.")
        return
    
    print(f"Loaded {len(products)} products. Preparing documents...")
    documents = []
    for p in products:
        # Create a rich text representation for the vector DB
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
            "single_price": p.single_price
        }
        documents.append(Document(page_content=content, metadata=metadata))
    
    print("Initializing OpenAI Embeddings...")
    embeddings = OpenAIEmbeddings()
    
    print(f"Ingesting into ChromaDB at {CHROMA_PATH}...")
    vectorstore = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=CHROMA_PATH
    )
    print("Ingestion complete. ChromaDB is ready.")

if __name__ == "__main__":
    ingest_catalog()
