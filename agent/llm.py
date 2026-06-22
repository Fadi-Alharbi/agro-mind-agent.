"""
agent/llm.py
────────────
Qwen adaptation layer for the LangChain / LangGraph agent.

Fadi's architecture is written against OpenAI (ChatOpenAI / OpenAIEmbeddings).
Our team's constraint is to run it on Qwen instead. We do that without rewriting
the agent: DashScope exposes an OpenAI-compatible endpoint, so the same
LangChain classes work once pointed at it. Every model/embedding in the agent
is created through these factories — the only place the provider is configured.

Env is read lazily inside each factory (not captured at import time) and we
load_dotenv() here, so the API key resolves correctly regardless of import
order — e.g. when `rag.ingest` imports this module before calling load_dotenv.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

load_dotenv()

_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _api_key() -> str:
    return os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or ""


def _base_url() -> str:
    return os.getenv("QWEN_BASE_URL", _DEFAULT_BASE_URL)


def get_chat_llm(temperature: float = 0.0, model: str | None = None) -> ChatOpenAI:
    """A Qwen chat model. `model` overrides the default text model when given."""
    return ChatOpenAI(
        model=model or os.getenv("QWEN_MODEL", "qwen-turbo"),
        base_url=_base_url(),
        api_key=_api_key(),
        temperature=temperature,
        streaming=True,
    )


def get_vision_llm(temperature: float = 0.0) -> ChatOpenAI:
    """A Qwen vision-capable chat model for crop-image diagnosis."""
    return ChatOpenAI(
        model=os.getenv("QWEN_VISION_MODEL", "qwen-vl-plus"),
        base_url=_base_url(),
        api_key=_api_key(),
        temperature=temperature,
        streaming=True,
    )


def get_embeddings() -> OpenAIEmbeddings:
    """Qwen multilingual embeddings for the Chroma vector store.

    `check_embedding_ctx_length=False` is essential: LangChain otherwise tries
    to tokenize with tiktoken using OpenAI model names, which fails for Qwen.
    """
    return OpenAIEmbeddings(
        model=os.getenv("QWEN_EMBED_MODEL", "text-embedding-v3"),
        base_url=_base_url(),
        api_key=_api_key(),
        check_embedding_ctx_length=False,
        # DashScope's text-embedding-v3 caps each request at 10 inputs.
        chunk_size=10,
    )
