"""
rag/embeddings.py
─────────────────
DashScope (Qwen) text embeddings — the retrieval half of the RAG pipeline.

Reuses the same API key / base URL the chat agent already uses, so no new
credentials or SDK are required: we call the OpenAI-compatible `/embeddings`
endpoint with `httpx` directly.

`text-embedding-v3` is multilingual (Arabic / English / Chinese), which matters
because the catalog is translated — a query in Arabic must match an English
product description. That is exactly what keyword search could not do.
"""

from __future__ import annotations

import os

import httpx

# ── Config (mirrors agent/orchestrator.py) ─────────────────────────────────────
_API_KEY = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or ""
_BASE_URL = os.getenv(
    "QWEN_BASE_URL",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
).rstrip("/")
_EMBED_MODEL = os.getenv("QWEN_EMBED_MODEL", "text-embedding-v3")
_EMBEDDINGS_URL = f"{_BASE_URL}/embeddings"

# text-embedding-v3 caps each request at 10 inputs.
_BATCH_SIZE = 10
EMBED_DIM = 1024  # dimensionality of text-embedding-v3 vectors


class EmbeddingError(RuntimeError):
    """Raised when the embedding endpoint cannot be reached or returns an error."""


def _check_api_key() -> None:
    if not _API_KEY:
        raise EmbeddingError(
            "QWEN_API_KEY (or DASHSCOPE_API_KEY) is not configured — "
            "embeddings cannot be generated. Set your key in .env."
        )
    if not _API_KEY.isascii():
        raise EmbeddingError(
            "API key contains non-ASCII characters — you likely left the "
            "placeholder value in .env. Put your real Qwen/DashScope key there."
        )


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts, returning one 1024-d vector per input (order preserved)."""
    _check_api_key()
    if not texts:
        return []

    vectors: list[list[float]] = []
    with httpx.Client(timeout=30) as client:
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start : start + _BATCH_SIZE]
            response = client.post(
                _EMBEDDINGS_URL,
                headers={
                    "Authorization": f"Bearer {_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"model": _EMBED_MODEL, "input": batch},
            )
            if response.status_code != 200:
                raise EmbeddingError(
                    f"Embedding request failed ({response.status_code}): "
                    f"{response.text[:300]}"
                )
            data = response.json()["data"]
            # The API guarantees results in input order via the `index` field.
            data.sort(key=lambda item: item["index"])
            vectors.extend(item["embedding"] for item in data)

    return vectors


def embed_query(text: str) -> list[float]:
    """Embed a single query string and return its vector."""
    return embed_texts([text])[0]
