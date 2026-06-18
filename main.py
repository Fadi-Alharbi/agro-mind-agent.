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
    from db.engine import init_db
    init_db()        # Create tables if they don't exist (idempotent)
    # Build the Chroma RAG index once if it isn't on disk yet (run
    # `python -m rag.ingest` to rebuild after a catalog change).
    try:
        import os
        from rag.ingest import CHROMA_PATH, ingest_catalog
        if not os.path.isdir(CHROMA_PATH) or not os.listdir(CHROMA_PATH):
            ingest_catalog()
    except Exception as exc:  # noqa: BLE001 — don't block startup on indexing
        logger.warning("RAG index build skipped (%s).", exc)
    get_agent()      # Warm up model connection
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
    # Stable browser identifier — links a returning customer across chats.
    external_id: Optional[str] = Field(default=None)


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
    diagnosis_id: Optional[int] = None


class CartItemRequest(BaseModel):
    session_id: str
    external_id: Optional[str] = None
    product_id: str
    quantity: int = Field(default=1, ge=1, le=99)
    is_group_buy: bool = True
    diagnosis_id: Optional[int] = None
    source: str = "manual"


class CheckoutRequest(BaseModel):
    session_id: str
    external_id: Optional[str] = None


class ProfileUpdateRequest(BaseModel):
    session_id: str
    external_id: str
    name: Optional[str] = Field(default=None, max_length=255)
    location: Optional[str] = Field(default=None, max_length=255)
    crop_type: Optional[str] = Field(default=None, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=128)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


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
    api_key_set = bool(os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY"))
    return {
        "status": "ok",
        "api_key_configured": api_key_set,
        "provider": "qwen",
        "model": os.getenv("QWEN_MODEL", "qwen-plus"),
        "vision_model": os.getenv("QWEN_VISION_MODEL", "qwen-vl-plus"),
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


@app.get("/cart")
async def get_cart(session_id: str, external_id: Optional[str] = None):
    """Return the active DB-backed cart for a returning customer."""
    from db.customer_state import get_cart as load_cart
    try:
        return load_cart(session_id, external_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/profile")
async def get_profile(session_id: str, external_id: str):
    """Return the saved profile for the demo login user."""
    from db.customer_state import get_profile as load_profile
    try:
        return load_profile(session_id, external_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/chat-history")
async def chat_history(
    session_id: str,
    external_id: str,
    limit: int = 0,
    include_images: bool = False,
):
    """Return recent chat history for the selected returning customer."""
    from db.customer_state import get_chat_history
    try:
        return get_chat_history(session_id, external_id, limit, include_images=include_images)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/customers/history")
async def customer_histories(
    include_images: bool = False,
    message_limit_per_customer: int = 0,
):
    """Return full chat history grouped by every customer."""
    from db.customer_state import get_all_customer_histories
    try:
        return get_all_customer_histories(
            include_images=include_images,
            message_limit_per_customer=message_limit_per_customer,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/customers")
async def customers(limit: int = 25):
    """Return recent customers for the local login selector."""
    from db.customer_state import list_customers
    try:
        return {"customers": list_customers(limit)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/auth/login")
async def login(request: LoginRequest):
    """Resolve an existing customer identity for the local UI login."""
    from db.customer_state import login_customer
    try:
        return login_customer(request.username, request.password, request.session_id)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/profile")
async def update_profile(request: ProfileUpdateRequest):
    """Save editable profile fields for the demo login user."""
    from db.customer_state import update_profile as save_profile
    try:
        return save_profile(
            request.session_id,
            request.external_id,
            name=request.name,
            location=request.location,
            crop_type=request.crop_type,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/cart/items")
async def add_cart_item(request: CartItemRequest):
    """Add a product to the active DB-backed cart."""
    from db.customer_state import add_cart_item as add_item
    try:
        return add_item(
            request.session_id,
            request.external_id,
            request.product_id,
            quantity=request.quantity,
            is_group_buy=request.is_group_buy,
            diagnosis_id=request.diagnosis_id,
            source=request.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/cart")
async def clear_cart(session_id: str, external_id: Optional[str] = None):
    """Clear the active cart and start a fresh one."""
    from db.customer_state import clear_cart as clear_active_cart
    try:
        return clear_active_cart(session_id, external_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/orders")
async def orders(session_id: str, external_id: Optional[str] = None):
    """Return orders owned by the logged-in customer."""
    from db.customer_state import list_orders
    try:
        return list_orders(session_id, external_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/orders/{order_id}")
async def order_detail(order_id: str, session_id: str, external_id: Optional[str] = None):
    """Return one order only if it belongs to the logged-in customer."""
    from db.customer_state import get_order
    try:
        return get_order(session_id, external_id, order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/orders/checkout")
async def checkout(request: CheckoutRequest):
    """Convert the active customer cart into DB-backed orders."""
    from db.customer_state import checkout_cart
    try:
        return checkout_cart(request.session_id, request.external_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
            external_id=request.external_id,
        )
    except Exception as exc:
        logger.error("Agent run failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    return ChatResponse(**result.to_dict())


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
