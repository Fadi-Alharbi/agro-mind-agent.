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
import copy
import logging
import os
import threading
import time
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


# ── Small backend TTL cache ────────────────────────────────────────────────────
# The UI makes the same authenticated read calls repeatedly during Streamlit
# reruns. Keep these short-lived and clear them on writes so stale cart/profile
# state does not hang around.
_cache_lock = threading.RLock()
_ttl_cache: dict[tuple, tuple[float, object]] = {}


def _cached(key: tuple, ttl_seconds: float, loader):
    now = time.monotonic()
    with _cache_lock:
        cached = _ttl_cache.get(key)
        if cached and cached[0] > now:
            return copy.deepcopy(cached[1])

    value = loader()
    with _cache_lock:
        _ttl_cache[key] = (now + ttl_seconds, copy.deepcopy(value))
    return value


def _clear_session_cache(session_id: Optional[str]) -> None:
    if not session_id:
        return
    with _cache_lock:
        for key in list(_ttl_cache):
            if session_id in key:
                _ttl_cache.pop(key, None)


def _clear_cache_prefix(prefix: str) -> None:
    with _cache_lock:
        for key in list(_ttl_cache):
            if key and key[0] == prefix:
                _ttl_cache.pop(key, None)


# ── Lazy agent singleton ───────────────────────────────────────────────────────
_agent = None


def get_agent():
    global _agent
    if _agent is None:
        from agent.orchestrator import AgroMindAgent
        _agent = AgroMindAgent()
    return _agent


def _seed_products_background() -> None:
    try:
        from db.seed import seed_products
        seed_products()
    except Exception as exc:  # noqa: BLE001
        logger.warning("DB product seed skipped (%s).", exc)


# ── Lifespan (startup/shutdown) ────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🌿 Agro-Mind AI starting up …")
    # Initialise the relational DB (creates tables incl. treatments) and seed
    # the product catalog. Both are idempotent and must never block startup.
    try:
        from db.engine import init_db
        init_db()
    except Exception as exc:  # noqa: BLE001
        logger.warning("DB init skipped (%s).", exc)
    else:
        threading.Thread(target=_seed_products_background, daemon=True).start()
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
def get_catalog():
    """Return the full product catalog."""
    from rag.catalog_loader import get_catalog
    return _cached(
        ("catalog",),
        300,
        lambda: (lambda products: {
            "count": len(products),
            "products": [p.to_dict() for p in products],
        })(get_catalog()),
    )


@app.get("/catalog/preview")
def get_catalog_preview(limit: int = 8):
    """Return a small catalog payload for sidebar previews."""
    from rag.catalog_loader import get_catalog
    limit = max(1, min(limit, 50))
    def load():
        products = get_catalog()
        return {
            "count": len(products),
            "products": [
                {
                    "product_id": p.product_id,
                    "product_name": p.product_name,
                    "english_name": p.english_name,
                    "product_type": p.product_type,
                }
                for p in products[:limit]
            ],
        }
    return _cached(("catalog_preview", limit), 300, load)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main chat endpoint. Accepts text and optional base64-encoded image.
    Returns structured JSON response from the Agro-Mind agent.
    """
    from db.customer_state import require_authenticated_session

    try:
        require_authenticated_session(request.session_id)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

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

    _clear_session_cache(request.session_id)
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
    from db.customer_state import require_authenticated_session

    try:
        require_authenticated_session(request.session_id)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

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
        finally:
            _clear_session_cache(request.session_id)

    return StreamingResponse(generate(), media_type="application/x-ndjson")


# ── Cart & checkout ─────────────────────────────────────────────────────────────

class CartAddRequest(BaseModel):
    session_id: str
    product_id: str = Field(..., min_length=1)
    quantity: int = Field(default=1, ge=1, le=100)
    is_group_buy: bool = Field(default=True)


class SessionRequest(BaseModel):
    session_id: str


class CheckoutRequest(SessionRequest):
    create_treatment_plan: bool = Field(default=False)


class LogoutRequest(BaseModel):
    session_id: Optional[str] = None


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=6, max_length=128)
    session_id: Optional[str] = Field(default=None, max_length=64)


class ProfileUpdateRequest(BaseModel):
    session_id: str
    name: Optional[str] = None
    location: Optional[str] = None
    crop_type: Optional[str] = None


@app.post("/login")
def login(request: LoginRequest):
    """Log in or create a customer and return the DB-backed profile/session."""
    from db.customer_state import login_customer

    try:
        payload = login_customer(
            request.username,
            request.password,
            request.session_id,
        )
        _clear_session_cache(payload.get("session_id"))
        return payload
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("login failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/logout")
def logout(request: LogoutRequest):
    """Invalidate the current DB session and return a fresh anonymous id."""
    from db.customer_state import logout_customer

    try:
        payload = logout_customer(request.session_id)
        _clear_session_cache(request.session_id)
        return payload
    except Exception as exc:
        logger.error("logout failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/session/new")
def new_session(request: SessionRequest):
    """Create a fresh DB-backed session for the current logged-in customer."""
    from db.customer_state import create_customer_session

    try:
        payload = create_customer_session(request.session_id)
        _clear_session_cache(request.session_id)
        _clear_session_cache(payload.get("session_id"))
        return payload
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.error("new_session failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/session")
def session_status(session_id: str):
    """Return the authenticated customer for a still-active session.

    Used by the frontend to rehydrate login state from a persistent cookie after
    a reload. Returns 401 once the session has been logged out or has expired.
    """
    from db.customer_state import resume_session

    try:
        return _cached(
            ("session", session_id),
            10,
            lambda: resume_session(session_id),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.error("resume_session failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/sessions")
def sessions(session_id: str):
    """Return the authenticated customer's chat sessions for sidebar navigation."""
    from db.customer_state import list_customer_sessions

    try:
        return _cached(
            ("sessions", session_id),
            20,
            lambda: list_customer_sessions(session_id, None),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.error("list_customer_sessions failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/profile")
def profile(session_id: str):
    """Return the DB-backed customer profile for the current session."""
    from db.customer_state import get_profile

    try:
        return _cached(
            ("profile", session_id),
            20,
            lambda: get_profile(session_id, None),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.error("get_profile failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/profile")
def update_profile_api(request: ProfileUpdateRequest):
    """Update editable customer profile fields."""
    from db.customer_state import update_profile

    try:
        payload = update_profile(
            request.session_id,
            None,
            name=request.name,
            location=request.location,
            crop_type=request.crop_type,
        )
        _clear_session_cache(request.session_id)
        return payload
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.error("update_profile failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/history")
def history(
    session_id: str,
    limit: int = 50,
    include_images: bool = False,
    all_sessions: bool = False,
):
    """Return DB-backed chat history for the current customer/session."""
    from db.customer_state import get_chat_history

    try:
        return _cached(
            ("history", session_id, limit, include_images, all_sessions),
            15,
            lambda: get_chat_history(
                session_id,
                None,
                limit=limit,
                include_images=include_images,
                all_sessions=all_sessions,
            ),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.error("get_chat_history failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/cart")
def view_cart(session_id: str):
    """Return the active cart for a session."""
    from db.customer_state import get_cart
    try:
        return _cached(
            ("cart", session_id),
            10,
            lambda: get_cart(session_id, None),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.error("get_cart failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/cart/add")
def cart_add(request: CartAddRequest):
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
        _clear_session_cache(request.session_id)
        return get_cart(request.session_id, None)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.error("cart_add failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/cart/clear")
def cart_clear(request: SessionRequest):
    """Empty the active cart."""
    from db.customer_state import clear_cart
    try:
        payload = clear_cart(request.session_id, None)
        _clear_session_cache(request.session_id)
        return payload
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.error("cart_clear failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/checkout")
def checkout(request: CheckoutRequest):
    """Convert the active cart into DB-backed orders with tracking numbers."""
    from db.customer_state import checkout_cart
    try:
        payload = checkout_cart(
            request.session_id,
            None,
            create_treatment_plan=request.create_treatment_plan,
        )
        _clear_session_cache(request.session_id)
        return payload
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("checkout failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/orders")
def orders(session_id: str):
    """List the customer's DB-backed orders (with tracking)."""
    from db.customer_state import list_orders
    try:
        return _cached(
            ("orders", session_id),
            10,
            lambda: list_orders(session_id, None),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.error("list_orders failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/order/{order_id}")
def get_single_order(order_id: str, session_id: str):
    """Get a specific order by ID."""
    from db.customer_state import get_order
    try:
        return _cached(
            ("order", session_id, order_id),
            10,
            lambda: get_order(session_id, None, order_id),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("get_order failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/treatments")
def get_treatments(session_id: str):
    """Return active treatments with daily task lists for the given session."""
    from db.customer_state import get_active_treatments
    try:
        return _cached(
            ("treatments", session_id),
            15,
            lambda: {"treatments": get_active_treatments(session_id, None)},
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.error("get_treatments failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/tasks/today")
def todays_tasks(session_id: str):
    """Return today's pending treatment tasks for the given session."""
    from db.customer_state import get_todays_tasks
    try:
        return _cached(
            ("tasks_today", session_id),
            15,
            lambda: {"tasks": get_todays_tasks(session_id, None)},
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.error("todays_tasks failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/followups/due")
def due_followups(session_id: str):
    """Return today's due follow-up tasks for the given session only.

    Scoped to the caller's session_id to avoid leaking other customers'
    follow-ups (IDOR). Mirrors /tasks/today.
    """
    from db.customer_state import get_todays_tasks
    try:
        return _cached(
            ("followups_due", session_id),
            15,
            lambda: (lambda tasks: {
                "count": len(tasks),
                "followups": tasks,
            })(get_todays_tasks(session_id, None)),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.error("due_followups failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

class TaskDoneRequest(BaseModel):
    session_id: str
    treatment_id: int
    day: int


@app.post("/tasks/done")
def mark_task_done(request: TaskDoneRequest):
    """Toggle a daily treatment task as done/undone."""
    from db.customer_state import mark_task_done as _mark
    try:
        payload = _mark(request.session_id, None, request.treatment_id, request.day)
        _clear_session_cache(request.session_id)
        return payload
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("mark_task_done failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
