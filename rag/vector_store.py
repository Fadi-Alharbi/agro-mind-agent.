"""
rag/vector_store.py
───────────────────
Chroma-backed semantic retrieval for the product catalog — the "R" in RAG.

Design notes:
  • We embed text ourselves (rag.embeddings) and hand Chroma raw vectors via
    `embeddings=`/`query_embeddings=`. This sidesteps Chroma's EmbeddingFunction
    protocol, which has changed across versions, and keeps the embedding source
    in one place.
  • The collection is persistent (on disk) so we index once and reuse across
    restarts. `index_catalog()` is idempotent: it only (re)embeds when the
    on-disk count doesn't match the catalog.
  • Distance space is cosine — the natural choice for normalized text embeddings.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.types import PyEmbedding

from rag.catalog_loader import ProductRecord, get_catalog
from rag.embeddings import embed_query, embed_texts

logger = logging.getLogger("agro_mind.rag")

_CHROMA_PATH = Path(__file__).resolve().parent / "chroma_store"
_COLLECTION_NAME = "products"

_client: ClientAPI | None = None


def _embeddable_text(rec: ProductRecord) -> str:
    """The text we embed for a product — the fields a farmer's query might match."""
    return " | ".join(
        part
        for part in (
            rec.product_name,
            rec.english_name,
            rec.product_type,
            rec.crops,
            rec.main_ingredients,
            rec.how_to_use,
        )
        if part
    )


def _get_collection():
    """Return the persistent Chroma collection, creating the client once."""
    global _client
    if _client is None:
        _CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
    return _client.get_or_create_collection(
        name=_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def index_catalog(force: bool = False) -> int:
    """Embed and index every product. Idempotent — skips work if already current.

    Returns the number of products in the collection after indexing.
    """
    catalog = get_catalog()
    collection = _get_collection()

    if not force and collection.count() == len(catalog) and len(catalog) > 0:
        logger.info("RAG index already current (%d products) — skipping.", len(catalog))
        return collection.count()

    if collection.count() > 0:
        # Rebuild cleanly so removed/renamed products don't linger.
        existing = collection.get()["ids"]
        if existing:
            collection.delete(ids=existing)

    if not catalog:
        logger.warning("Catalog is empty — nothing to index.")
        return 0

    documents = [_embeddable_text(rec) for rec in catalog]
    logger.info("Embedding %d products via DashScope …", len(documents))
    vectors = cast(list[PyEmbedding], embed_texts(documents))

    collection.add(
        ids=[rec.product_id for rec in catalog],
        embeddings=vectors,
        documents=documents,
        metadatas=[{"product_id": rec.product_id} for rec in catalog],
    )
    logger.info("RAG index built: %d products.", len(catalog))
    return collection.count()


def semantic_search(query: str, k: int = 3) -> list[tuple[str, float]]:
    """Return up to k (product_id, similarity) pairs ranked by semantic relevance.

    Similarity is 1 - cosine_distance, so higher is better (1.0 == identical).
    """
    collection = _get_collection()
    if collection.count() == 0:
        index_catalog()
        collection = _get_collection()

    result = collection.query(
        query_embeddings=[cast(PyEmbedding, embed_query(query))],
        n_results=min(k, collection.count()),
    )
    ids_rows = result["ids"]
    distance_rows = result["distances"]
    if not ids_rows or not distance_rows:
        return []

    ids = ids_rows[0]
    distances = distance_rows[0]
    return [(pid, 1.0 - dist) for pid, dist in zip(ids, distances)]
