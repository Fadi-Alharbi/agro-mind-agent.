"""
rag/retrieve.py
───────────────
The public retrieval API the agent calls. Sits above both the semantic
(Chroma + embeddings) and keyword retrievers and returns ProductRecord objects.

Why a layer on top:
  • Resolves the import direction cleanly — vector_store depends on
    catalog_loader, so the keyword/semantic union lives here, not in either.
  • Provides graceful degradation: if embeddings are unavailable (no API key,
    no network), we fall back to the original keyword search instead of failing
    the whole request. The fallback is logged loudly — it is a degraded mode,
    not a silent one.
"""

from __future__ import annotations

import logging

from rag.catalog_loader import ProductRecord, get_product_by_id, search_catalog
from rag.vector_store import semantic_search

logger = logging.getLogger("agro_mind.rag")


def retrieve_products(query: str, k: int = 3) -> list[ProductRecord]:
    """Semantic retrieval with a keyword fallback. Returns up to k ProductRecords."""
    try:
        hits = semantic_search(query, k=k)
        records = [rec for pid, _ in hits if (rec := get_product_by_id(pid))]
        if records:
            return records
        logger.warning("Semantic search returned no usable products — falling back to keyword.")
    except Exception as exc:  # noqa: BLE001 — degrade, don't crash the request
        logger.warning("Semantic search failed (%s) — falling back to keyword search.", exc)

    return search_catalog(query, max_results=k)
