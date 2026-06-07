"""
main.py
───────
FastAPI application entry point for Agro-Mind AI.

Endpoints:
  POST /chat       — Main chat endpoint
  GET  /health     — Liveness check
  GET  /catalog    — Full product catalog listing
"""

from __future__ import annotations

import base64
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("agro_mind")


# ── Lazy agent singleton ───────────────────────────────────────────────────────
_agent = None


def get_agent():
    global _agent
    if _agent is None:
        from agent.orchestrator import AgroMindAgent
        _agent = AgroMindAgent()
    return _agent


# ── Lifespan (startup/shutdown) ────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🌿 Agro-Mind AI starting up …")
    get_agent()  # Warm up model connection
    yield
    logger.info("🌿 Agro-Mind AI shutting down …")


# ── App creation ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Agro-Mind AI API",
    description=(
        "Single-agent multimodal customer support system for Pinduoduo agricultural store. "
        "Handles crop diagnosis, product recommendations, logistics, and safety escalation."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ──────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: str = Field(..., min_length=1, max_length=4000)
    image_base64: Optional[str] = Field(default=None)
    order_id: Optional[str] = Field(default=None)


class ChatResponse(BaseModel):
    intent: str
    safety_risk_detected: bool
    escalate_human: bool
    response_text: str
    recommended_product_id: Optional[str]
    group_purchase_triggered: bool
    human_summary_brief: Optional[str]
    matched_products: list[dict]
    session_id: str


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "message": "🌿 Welcome to Agro-Mind AI (العقل الزراعي)",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    api_key_set = bool(os.getenv("GOOGLE_API_KEY", ""))
    return {
        "status": "ok",
        "api_key_configured": api_key_set,
        "model": os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
    }


@app.get("/catalog")
async def get_catalog():
    """Return the full product catalog."""
    from rag.catalog_loader import get_catalog
    products = get_catalog()
    return {
        "count": len(products),
        "products": [p.to_dict() for p in products],
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main chat endpoint. Accepts text and optional base64-encoded image.
    Returns structured JSON response from the Agro-Mind agent.
    """
    agent = get_agent()

    # Decode image if provided
    image_bytes: Optional[bytes] = None
    if request.image_base64:
        try:
            image_bytes = base64.b64decode(request.image_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 image data.")

    try:
        result = await agent.run(
            session_id=request.session_id,
            user_text=request.message,
            image_bytes=image_bytes,
            order_id=request.order_id,
        )
    except Exception as exc:
        logger.error("Agent run failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    return ChatResponse(**result.to_dict())


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
