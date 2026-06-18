"""
agent/llm.py
────────────
Qwen adaptation layer for the LangChain / LangGraph agent.

Fadi's architecture is written against OpenAI (ChatOpenAI / OpenAIEmbeddings).
Our team's constraint is to run it on Qwen instead. We do that without rewriting
the agent: DashScope exposes an OpenAI-compatible endpoint, so the same
LangChain classes work once pointed at it. Every model/embedding in the agent
is created through these factories — the only place the provider is configured.
"""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

_API_KEY = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or ""
_BASE_URL = os.getenv(
    "QWEN_BASE_URL",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)

_TEXT_MODEL = os.getenv("QWEN_MODEL", "qwen-plus")
_VISION_MODEL = os.getenv("QWEN_VISION_MODEL", "qwen-vl-plus")
_EMBED_MODEL = os.getenv("QWEN_EMBED_MODEL", "text-embedding-v3")


def get_chat_llm(temperature: float = 0.0, model: str | None = None) -> ChatOpenAI:
    """A Qwen chat model. `model` overrides the default text model when given."""
    return ChatOpenAI(
        model=model or _TEXT_MODEL,
        base_url=_BASE_URL,
        api_key=_API_KEY,
        temperature=temperature,
    )


def get_vision_llm(temperature: float = 0.0) -> ChatOpenAI:
    """A Qwen vision-capable chat model for crop-image diagnosis."""
    return ChatOpenAI(
        model=_VISION_MODEL,
        base_url=_BASE_URL,
        api_key=_API_KEY,
        temperature=temperature,
    )


def get_embeddings() -> OpenAIEmbeddings:
    """Qwen multilingual embeddings for the Chroma vector store.

    `check_embedding_ctx_length=False` is essential: LangChain otherwise tries
    to tokenize with tiktoken using OpenAI model names, which fails for Qwen.
    """
    return OpenAIEmbeddings(
        model=_EMBED_MODEL,
        base_url=_BASE_URL,
        api_key=_API_KEY,
        check_embedding_ctx_length=False,
        # DashScope's text-embedding-v3 caps each request at 10 inputs.
        chunk_size=10,
    )
