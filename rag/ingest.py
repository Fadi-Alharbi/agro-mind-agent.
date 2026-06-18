"""
rag/ingest.py
─────────────
Build the Chroma vector store from the product catalog — Fadi's RAG design,
adapted to run on Qwen embeddings (via agent.llm) instead of OpenAI.

Run once to (re)build the index:

    python -m rag.ingest

The store is persisted under db/chroma_db so the agent's retrieval tools can
load it read-only at request time.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document

from agent.llm import get_embeddings
from rag.catalog_loader import get_catalog

load_dotenv()

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")
CHROMA_PATH = os.path.join(DB_DIR, "chroma_db")
COLLECTION_NAME = "agronomy_catalog"


def _product_document(p) -> Document:
    """A rich, multilingual text block per product — what gets embedded."""
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
    }
    return Document(page_content=content, metadata=metadata)


def ingest_catalog() -> int:
    """Embed every product with Qwen and persist to Chroma. Returns the count."""
    products = get_catalog()
    if not products:
        print("No products found in catalog. Check the tra/ directory.")
        return 0

    print(f"Loaded {len(products)} products. Preparing documents …")
    documents = [_product_document(p) for p in products]

    print("Initializing Qwen embeddings (text-embedding-v3) …")
    embeddings = get_embeddings()

    print(f"Ingesting into ChromaDB at {CHROMA_PATH} …")
    Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=CHROMA_PATH,
        collection_name=COLLECTION_NAME,
    )
    print(f"Ingestion complete: {len(documents)} products indexed.")
    return len(documents)


if __name__ == "__main__":
    ingest_catalog()
