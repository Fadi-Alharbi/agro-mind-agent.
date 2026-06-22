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

import json as _json

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
    # Initialise the relational DB (creates tables incl. treatments) and seed
    # the product catalog. Both are idempotent and must never block startup.
    try:
        from db.engine import init_db
        from db.seed import seed_products
        init_db()
        seed_products()
    except Exception as exc:  # noqa: BLE001
        logger.warning("DB init/seed skipped (%s).", exc)
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
    api_key_set = bool(
        os.getenv("QWEN_API_KEY", "") or os.getenv("DASHSCOPE_API_KEY", "")
    )
    return {
        "status": "ok",
        "api_key_configured": api_key_set,
        "model": os.getenv("QWEN_MODEL", "qwen-plus"),
        "vision_model": os.getenv("QWEN_VISION_MODEL", "qwen-vl-plus"),
        "backend": "Qwen (DashScope)",
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


@app.post("/chat_stream")
async def chat_stream(request: ChatRequest):
    """Streaming chat endpoint.

    Yields newline-delimited JSON (application/x-ndjson).
    Each line is one of:
      {"type": "token",    "content": "<text chunk>"}   — LLM token as it arrives
      {"type": "metadata", "data":    {<ChatResponse>}}  — final structured result
      {"type": "error",    "content": "<message>"}       — on failure
    """
    agent = get_agent()

    image_bytes: Optional[bytes] = None
    if request.image_base64:
        try:
            image_bytes = base64.b64decode(request.image_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 image data.")

    async def generate():
        try:
            async for event in agent.stream(
                session_id=request.session_id,
                user_text=request.message,
                image_bytes=image_bytes,
                order_id=request.order_id,
            ):
                yield _json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:
            logger.error("Stream failed: %s", exc, exc_info=True)
            yield _json.dumps({"type": "error", "content": str(exc)}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


# ── Cart & checkout ─────────────────────────────────────────────────────────────

class CartAddRequest(BaseModel):
    session_id: str
    product_id: str = Field(..., min_length=1)
    quantity: int = Field(default=1, ge=1, le=100)
    is_group_buy: bool = Field(default=True)


class SessionRequest(BaseModel):
    session_id: str


@app.get("/cart")
async def view_cart(session_id: str):
    """Return the active cart for a session."""
    from db.customer_state import get_cart
    try:
        return get_cart(session_id, None)
    except Exception as exc:
        logger.error("get_cart failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/cart/add")
async def cart_add(request: CartAddRequest):
    """Add (or increment) a product in the active cart, returning the new cart."""
    from db.customer_state import add_cart_item, get_cart
    try:
        add_cart_item(
            request.session_id,
            None,
            request.product_id,
            quantity=request.quantity,
            is_group_buy=request.is_group_buy,
        )
        return get_cart(request.session_id, None)
    except Exception as exc:
        logger.error("cart_add failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/cart/clear")
async def cart_clear(request: SessionRequest):
    """Empty the active cart."""
    from db.customer_state import clear_cart
    try:
        return clear_cart(request.session_id, None)
    except Exception as exc:
        logger.error("cart_clear failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/checkout")
async def checkout(request: SessionRequest):
    """Convert the active cart into DB-backed orders with tracking numbers."""
    from db.customer_state import checkout_cart
    try:
        return checkout_cart(request.session_id, None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("checkout failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/orders")
async def orders(session_id: str):
    """List the customer's DB-backed orders (with tracking)."""
    from db.customer_state import list_orders
    try:
        return list_orders(session_id, None)
    except Exception as exc:
        logger.error("list_orders failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/order/{order_id}")
async def get_single_order(order_id: str, session_id: str):
    """Get a specific order by ID."""
    from db.customer_state import get_order
    try:
        return get_order(session_id, None, order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("get_order failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/treatments")
async def get_treatments(session_id: str):
    """Return active treatments with daily task lists for the given session."""
    from db.customer_state import get_active_treatments
    try:
        return {"treatments": get_active_treatments(session_id, None)}
    except Exception as exc:
        logger.error("get_treatments failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/tasks/today")
async def todays_tasks(session_id: str):
    """Return today's pending treatment tasks for the given session."""
    from db.customer_state import get_todays_tasks
    try:
        return {"tasks": get_todays_tasks(session_id, None)}
    except Exception as exc:
        logger.error("todays_tasks failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


class TaskDoneRequest(BaseModel):
    session_id: str
    treatment_id: int
    day: int


@app.post("/tasks/done")
async def mark_task_done(request: TaskDoneRequest):
    """Toggle a daily treatment task as done/undone."""
    from db.customer_state import mark_task_done as _mark
    try:
        return _mark(request.session_id, None, request.treatment_id, request.day)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("mark_task_done failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
