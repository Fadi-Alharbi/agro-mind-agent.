"""
frontend/app.py
───────────────
Agro-Mind AI — Premium Streamlit Chat Interface
Dark agricultural theme with chat history, image upload, product cards,
and safety escalation banners.
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import datetime
from io import BytesIO
from typing import Optional

import requests
import streamlit as st

# ── Page configuration ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Agro-Mind AI | Smart Agricultural Support",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── API endpoint ───────────────────────────────────────────────────────────────
API_URL = "http://localhost:8000"

# ── Custom CSS (dark green premium theme) ─────────────────────────────────────
st.markdown("""
<style>
  /* === Google Font === */
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

  /* === Global === */
  html, body, [class*="css"] {
    font-family: 'Inter', sans-serif !important;
  }

  /* === Dark background === */
  .stApp {
    background: linear-gradient(135deg, #0a1628 0%, #0d2137 50%, #0a1a10 100%);
    color: #e8f5e9;
  }

  /* === Sidebar === */
  [data-testid="stSidebar"] {
    background: linear-gradient(180deg, #061020 0%, #0a1a10 100%) !important;
    border-right: 1px solid #1e4d2b;
  }
  [data-testid="stSidebar"] * { color: #b2dfdb !important; }

  /* === Header === */
  .agro-header {
    background: linear-gradient(135deg, #1b5e20, #004d40, #0d47a1);
    border-radius: 16px;
    padding: 24px 32px;
    margin-bottom: 24px;
    box-shadow: 0 8px 32px rgba(0,150,50,0.25);
    border: 1px solid rgba(76,175,80,0.3);
  }
  .agro-header h1 {
    font-size: 2.2rem;
    font-weight: 700;
    color: #a5d6a7;
    margin: 0;
    letter-spacing: -0.5px;
  }
  .agro-header p {
    color: #80cbc4;
    font-size: 0.95rem;
    margin: 8px 0 0 0;
    opacity: 0.9;
  }

  /* === Chat messages === */
  .user-bubble {
    background: linear-gradient(135deg, #1565c0, #0277bd);
    border-radius: 18px 18px 4px 18px;
    padding: 14px 18px;
    margin: 8px 0 8px 15%;
    color: #e3f2fd;
    font-size: 0.95rem;
    box-shadow: 0 4px 12px rgba(21,101,192,0.3);
    border: 1px solid rgba(100,181,246,0.2);
  }

  .agent-bubble {
    background: linear-gradient(135deg, #1b5e20, #2e7d32);
    border-radius: 18px 18px 18px 4px;
    padding: 14px 18px;
    margin: 8px 15% 8px 0;
    color: #e8f5e9;
    font-size: 0.95rem;
    box-shadow: 0 4px 12px rgba(27,94,32,0.3);
    border: 1px solid rgba(129,199,132,0.2);
  }

  /* === Product cards === */
  .product-card {
    background: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 12px;
    padding: 16px 20px;
    margin: 12px 0;
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    transition: all 0.2s ease;
    color: #263238;
  }
  .product-card:hover {
    border-color: #81c784;
    box-shadow: 0 6px 16px rgba(76,175,80,0.15);
    transform: translateY(-2px);
  }
  .product-id {
    font-size: 0.75rem;
    color: #78909c;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
  }
  .product-name {
    font-size: 1.2rem;
    font-weight: 700;
    color: #1b5e20;
    margin: 4px 0;
  }
  .product-type-badge {
    display: inline-block;
    background: #e8f5e9;
    border: 1px solid #a5d6a7;
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 0.75rem;
    color: #2e7d32;
    margin: 4px 0;
  }
  .price-group {
    font-size: 1.3rem;
    font-weight: 700;
    color: #e65100;
    margin: 8px 0 2px 0;
  }
  .price-single {
    font-size: 0.9rem;
    color: #78909c;
    text-decoration: line-through;
  }
  .dosage-info {
    background: #f5f5f5;
    border-radius: 8px;
    padding: 10px 14px;
    margin-top: 10px;
    font-size: 0.85rem;
    color: #37474f;
    border-left: 4px solid #66bb6a;
  }

  /* === Safety banner === */
  .safety-banner {
    background: linear-gradient(135deg, #b71c1c, #880e4f);
    border: 2px solid #ef5350;
    border-radius: 12px;
    padding: 20px 24px;
    margin: 12px 0;
    box-shadow: 0 0 30px rgba(239,83,80,0.4);
    animation: pulse-border 2s infinite;
  }
  @keyframes pulse-border {
    0%, 100% { box-shadow: 0 0 20px rgba(239,83,80,0.4); }
    50% { box-shadow: 0 0 40px rgba(239,83,80,0.7); }
  }
  .safety-banner h3 { color: #ffcdd2; margin: 0 0 8px 0; font-size: 1.1rem; }
  .safety-banner p { color: #ffebee; margin: 4px 0; font-size: 0.9rem; }

  /* === Status badges === */
  .badge-diagnosis { background: #1565c0; color: #e3f2fd; }
  .badge-logistics { background: #e65100; color: #fff3e0; }
  .badge-product { background: #1b5e20; color: #e8f5e9; }
  .badge-safety { background: #b71c1c; color: #ffebee; }
  .badge-qa { background: #4a148c; color: #f3e5f5; }

  .intent-badge {
    display: inline-block;
    border-radius: 20px;
    padding: 3px 12px;
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 6px;
  }

  /* === Escalation indicator === */
  .escalate-tag {
    background: rgba(239,83,80,0.2);
    border: 1px solid #ef5350;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 0.78rem;
    color: #ef5350;
    margin-top: 4px;
    display: inline-block;
  }

  /* === Input area === */
  .stTextInput input, .stTextArea textarea {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(76,175,80,0.3) !important;
    border-radius: 12px !important;
    color: #e8f5e9 !important;
    padding: 12px 16px !important;
  }
  .stTextInput input:focus, .stTextArea textarea:focus {
    border-color: rgba(76,175,80,0.8) !important;
    box-shadow: 0 0 0 2px rgba(76,175,80,0.15) !important;
  }

  /* === Buttons === */
  .stButton > button {
    background: linear-gradient(135deg, #2e7d32, #1565c0) !important;
    color: white !important;
    border: none !important;
    border-radius: 12px !important;
    font-weight: 600 !important;
    padding: 12px 24px !important;
    transition: all 0.2s ease !important;
    box-shadow: 0 4px 12px rgba(46,125,50,0.3) !important;
  }
  .stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 24px rgba(46,125,50,0.4) !important;
  }

  /* === Dividers === */
  hr { border-color: rgba(76,175,80,0.15) !important; }

  /* === Metrics === */
  [data-testid="stMetric"] {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(76,175,80,0.2);
    border-radius: 10px;
    padding: 12px;
  }

  /* === File uploader === */
  [data-testid="stFileUploader"] {
    background: rgba(255,255,255,0.03) !important;
    border: 2px dashed rgba(76,175,80,0.3) !important;
    border-radius: 12px !important;
  }

  /* === Spinner === */
  .stSpinner > div { border-top-color: #4caf50 !important; }

  /* === Timestamp === */
  .msg-ts {
    font-size: 0.7rem;
    color: rgba(255,255,255,0.3);
    margin-top: 4px;
    text-align: right;
  }
</style>
""", unsafe_allow_html=True)


# ── Session state initialisation ───────────────────────────────────────────────
if "session_id" not in st.session_state:
    st.session_state.session_id = "guest"
if "messages" not in st.session_state:
    st.session_state.messages = []
if "uploaded_image" not in st.session_state:
    st.session_state.uploaded_image = None
if "tracked_orders" not in st.session_state:
    st.session_state.tracked_orders = []


# ── Helper functions ───────────────────────────────────────────────────────────

def _intent_badge(intent: str) -> str:
    badge_map = {
        "diagnosis": ("badge-diagnosis", "🔬 Diagnosis"),
        "logistics": ("badge-logistics", "📦 Logistics"),
        "product_recommendation": ("badge-product", "🛒 Product"),
        "safety_escalation": ("badge-safety", "🚨 Safety"),
        "general_qa": ("badge-qa", "💬 General QA"),
    }
    cls, label = badge_map.get(intent, ("badge-qa", intent))
    return f'<span class="intent-badge {cls}">{label}</span>'


def _render_product_card(product: dict) -> str:
    pid = product.get("product_id", "")
    name = product.get("product_name", "Unknown")
    ptype = product.get("product_type", "")
    crops = product.get("crops", "")[:100]
    dosage = product.get("water_ratio") or product.get("how_to_use", "")[:120]
    gp = product.get("group_price", 0)
    sp = product.get("single_price", 0)
    ingredients = product.get("main_ingredients", "")[:100]

    return f"""
    <div style="background: linear-gradient(145deg, #1e2a24, #26382f); border: 1px solid rgba(76,175,80,0.4); border-radius: 12px; padding: 20px; box-shadow: 0 8px 32px rgba(0,0,0,0.25); color: #fff;">
      <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px;">
         <div>
            <div style="font-size: 1.25rem; font-weight: 700; color: #a5d6a7;">🌱 {name}</div>
            <div style="font-size: 0.8rem; color: #b0bec5; margin-top: 6px;">📦 Product Code: <span style="color: #fff;">{pid}</span> &nbsp;|&nbsp; <span style="background: rgba(76,175,80,0.2); padding: 4px 10px; border-radius: 6px; color: #c5e1a5;">{ptype}</span></div>
         </div>
      </div>
      
      <div style="background: rgba(0,0,0,0.25); border-radius: 8px; padding: 14px; margin-bottom: 16px; border: 1px solid rgba(255,255,255,0.05);">
        <div style="font-size: 0.9rem; color: #cfd8dc; margin-bottom: 8px;">
          <strong style="color: #81c784;">🌾 Target Crops:</strong> {crops}
        </div>
        <div style="font-size: 0.9rem; color: #cfd8dc; margin-bottom: 8px;">
          <strong style="color: #81c784;">🧪 Active Ingredients:</strong> {ingredients}
        </div>
        <div style="font-size: 0.9rem; color: #cfd8dc;">
          <strong style="color: #81c784;">📋 Indications & Dosage:</strong> {dosage}
        </div>
      </div>

      <div style="display: flex; gap: 12px;">
        <div style="flex: 1; background: rgba(76,175,80,0.15); border: 1px solid rgba(76,175,80,0.3); border-radius: 8px; padding: 12px; text-align: center;">
          <div style="font-size: 0.85rem; color: #b0bec5; margin-bottom: 4px;">Single Price 🛒</div>
          <div style="font-size: 1.3rem; font-weight: 700; color: #fff;">¥{sp:.0f}</div>
        </div>
        <div style="flex: 1; background: rgba(255,152,0,0.15); border: 1px solid rgba(255,152,0,0.3); border-radius: 8px; padding: 12px; text-align: center;">
          <div style="font-size: 0.85rem; color: #b0bec5; margin-bottom: 4px;">Group Price 👥</div>
          <div style="font-size: 1.3rem; font-weight: 700; color: #ffb74d;">¥{gp:.0f}</div>
        </div>
      </div>
    </div>
    """


def _send_message(message: str, image_bytes: Optional[bytes], order_id: Optional[str]) -> dict:
    """Call the FastAPI /chat endpoint (non-streaming fallback)."""
    payload: dict = {
        "session_id": st.session_state.session_id,
        "message": message,
    }
    if image_bytes:
        payload["image_base64"] = base64.b64encode(image_bytes).decode()
    if order_id:
        payload["order_id"] = order_id

    try:
        response = requests.post(f"{API_URL}/chat", json=payload, timeout=120)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        return _connection_error_response()
    except Exception as exc:
        return _error_response(str(exc))


def _connection_error_response() -> dict:
    return {
        "intent": "general_qa",
        "safety_risk_detected": False,
        "escalate_human": False,
        "response_text": (
            "⚠️ Cannot connect to the backend server. "
            "Please make sure the FastAPI server is running:\n\n"
            "`uvicorn main:app --reload --port 8000`"
        ),
        "recommended_product_id": None,
        "group_purchase_triggered": False,
        "human_summary_brief": None,
        "matched_products": [],
        "session_id": st.session_state.session_id,
    }


def _error_response(msg: str) -> dict:
    return {
        "intent": "general_qa",
        "safety_risk_detected": False,
        "escalate_human": False,
        "response_text": f"An error occurred: {msg}",
        "recommended_product_id": None,
        "group_purchase_triggered": False,
        "human_summary_brief": None,
        "matched_products": [],
        "session_id": st.session_state.session_id,
    }


def _stream_turn(pending: dict) -> dict:
    """Call /chat_stream and display tokens live as they arrive.

    Shows each token inside the agent-bubble CSS div as it comes in.
    Returns the final response_data dict (same shape as /chat response).
    """
    payload: dict = {"session_id": st.session_state.session_id, "message": pending["message"]}
    if pending.get("image_bytes"):
        payload["image_base64"] = base64.b64encode(pending["image_bytes"]).decode()
    if pending.get("order_id"):
        payload["order_id"] = pending["order_id"]

    full_text = ""
    response_data: dict = {}
    placeholder = st.empty()

    try:
        with requests.post(
            f"{API_URL}/chat_stream",
            json=payload,
            stream=True,
            timeout=120,
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                try:
                    event = json.loads(line)
                except Exception:
                    continue

                if event.get("type") == "token":
                    full_text += event["content"]
                    # Strip [PRODUCT: ID] tags from the live display so they
                    # never appear to the user — product cards render separately.
                    display = re.sub(r"\[PRODUCT:.*", "", full_text, flags=re.DOTALL).strip()
                    placeholder.markdown(
                        f'<div class="agent-bubble">🤖 {display}▌</div>',
                        unsafe_allow_html=True,
                    )
                elif event.get("type") == "metadata":
                    response_data = event["data"]
                elif event.get("type") == "error":
                    full_text = f"An error occurred: {event.get('content', 'Unknown error')}"

    except requests.exceptions.ConnectionError:
        response_data = _connection_error_response()
    except Exception as exc:
        response_data = _error_response(str(exc))

    placeholder.empty()

    # Use the streamed text if metadata didn't include response_text (fallback).
    if not response_data.get("response_text") and full_text:
        display = re.sub(r"\[PRODUCT:.*", "", full_text, flags=re.DOTALL).strip()
        response_data["response_text"] = display

    return response_data


def _process_turn(message: str, image_bytes: Optional[bytes], order_id: Optional[str]) -> None:
    """Queue a chat turn: record the user message now and mark it pending.

    The backend call is deferred to the pending-turn processor (which runs
    after the next rerun, below the chat history). This two-phase flow makes
    the user's bubble appear immediately, with the spinner shown beneath it —
    instead of the spinner appearing before the message is visible.
    Shared by the form submit and the quick-question buttons."""
    message = (message or "").strip()
    if not message and not image_bytes:
        return
    st.session_state.messages.append({
        "role": "user",
        "content": message,
        "ts": datetime.now().strftime("%H:%M"),
        "has_image": image_bytes is not None,
    })
    st.session_state["pending_turn"] = {
        "message": message,
        "image_bytes": image_bytes,
        "order_id": order_id,
    }


# ── Cart API helpers ───────────────────────────────────────────────────────────
def _cart_add(product_id: str, quantity: int, is_group_buy: bool = False) -> dict:
    """Add a product to the DB-backed cart via the backend."""
    try:
        r = requests.post(
            f"{API_URL}/cart/add",
            json={
                "session_id": st.session_state.session_id,
                "product_id": product_id,
                "quantity": quantity,
                "is_group_buy": is_group_buy,
            },
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"error": str(exc)}


# ── Treatment / Task API helpers ────────────────────────────────────────────────
def _get_treatments() -> list:
    try:
        r = requests.get(
            f"{API_URL}/treatments",
            params={"session_id": st.session_state.session_id},
            timeout=8,
        )
        r.raise_for_status()
        return r.json().get("treatments", [])
    except Exception:
        return []


def _mark_task_done(treatment_id: int, day: int) -> dict:
    try:
        r = requests.post(
            f"{API_URL}/tasks/done",
            json={
                "session_id": st.session_state.session_id,
                "treatment_id": treatment_id,
                "day": day,
            },
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"error": str(exc)}


def _get_cart() -> dict:
    try:
        r = requests.get(
            f"{API_URL}/cart", params={"session_id": st.session_state.session_id}, timeout=10
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"items": [], "total_amount": 0}


def _checkout() -> dict:
    try:
        r = requests.post(
            f"{API_URL}/checkout",
            json={"session_id": st.session_state.session_id},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"error": str(exc)}


def _check_backend() -> bool:
    try:
        r = requests.get(f"{API_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="text-align:center; padding: 12px 0 8px 0;">
      <div style="font-size:1.5rem; font-weight:700; color:#a5d6a7; letter-spacing:-0.5px;">🌿 Agro-Mind</div>
      <div style="font-size:0.78rem; color:#546e7a; margin-top:2px;">Smart Agricultural Assistant</div>
    </div>
    """, unsafe_allow_html=True)
    
    # User Login
    st.markdown("---")
    st.markdown("**👤 User**")
    login_id = st.text_input("Name or Phone", value="" if st.session_state.session_id == "guest" else st.session_state.session_id, label_visibility="collapsed", placeholder="Enter Name or Phone")
    if st.button("Login / Switch User", use_container_width=True):
        if login_id and login_id.strip():
            if login_id.strip() != st.session_state.session_id:
                st.session_state.session_id = login_id.strip()
                st.session_state.messages = []
                st.rerun()
    
    # System Status
    backend_ok = _check_backend()
    status_color = "#4caf50" if backend_ok else "#ef5350"
    status_label = "Connected ✅" if backend_ok else "Offline ⚠️"
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:8px;margin:8px 0 0 0;">'
        f'<div style="width:9px;height:9px;border-radius:50%;background:{status_color};box-shadow:0 0 6px {status_color};"></div>'
        f'<span style="font-size:0.8rem;">Backend: {status_label}</span></div>',
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # ── 📋 Tasks ─────────────────────────────────────────────────────────────────
    with st.expander("📋  Tasks", expanded=False):
        try:
            treatments = _get_treatments()
            if not treatments:
                st.markdown('<div style="font-size:0.82rem;color:#546e7a;">No active treatment tasks.</div>', unsafe_allow_html=True)
            else:
                for tr in treatments:
                    tasks = tr.get("daily_tasks", [])
                    product_id = tr.get("product_id", "")
                    crop = tr.get("crop") or ""
                    disease = tr.get("disease") or ""
                    total_days = len(tasks)
                    done_count = sum(1 for t in tasks if t.get("done"))
                    pct = int((done_count / total_days) * 100) if total_days else 0
                    crop_label = crop if crop else product_id
                    disease_label = f" ({disease})" if disease else ""
                    status_icon = "✅" if done_count == total_days else "🌱"
                    st.markdown(f"""
                    <div style="background:rgba(76,175,80,0.07);border:1px solid rgba(76,175,80,0.2);border-radius:9px;padding:10px 12px;margin-bottom:4px;">
                      <div style="font-size:0.85rem;font-weight:600;color:#a5d6a7;">{status_icon} {crop_label}{disease_label}</div>
                      <div style="font-size:0.72rem;color:#546e7a;margin-top:2px;">💊 {product_id} &nbsp;|&nbsp; {done_count}/{total_days} days</div>
                      <div style="background:rgba(0,0,0,0.25);border-radius:5px;height:5px;overflow:hidden;margin-top:7px;">
                        <div style="height:5px;border-radius:5px;background:linear-gradient(90deg,#2e7d32,#66bb6a);width:{max(2,pct)}%;"></div>
                      </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Show all tasks under this treatment in the sidebar
                    for task in tasks:
                        day_num = task.get("day", 0)
                        task_date = task.get("date", "")
                        task_desc = task.get("task", "")
                        is_done = task.get("done", False)
                        
                        col_check, col_info_col = st.columns([1, 9])
                        with col_check:
                            checked = st.checkbox("", value=is_done, key=f"sb_full_task_{tr['id']}_{day_num}", label_visibility="collapsed")
                            if checked != is_done:
                                _mark_task_done(tr["id"], day_num)
                                st.rerun()
                        with col_info_col:
                            done_style = "opacity:0.4;text-decoration:line-through;" if is_done else ""
                            st.markdown(
                                f'<div style="font-size:0.75rem;color:#b0bec5;margin-bottom:4px;{done_style}">'
                                f'<span style="color:#78909c;">Day {day_num} ({task_date}):</span> {task_desc}'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        except Exception:
            st.markdown('<div style="font-size:0.82rem;color:#ef5350;">Error loading tasks.</div>', unsafe_allow_html=True)

    # ── 🛒 Cart ──────────────────────────────────────────────────────────────────
    cart = _get_cart()
    cart_items = cart.get("items", [])
    cart_count = len(cart_items)
    cart_label = f"🛒  Cart ({cart_count} items)" if cart_count else "🛒  Cart"
    with st.expander(cart_label, expanded=(cart_count > 0)):
        if not cart_items:
            st.markdown('<div style="font-size:0.82rem;color:#546e7a;">Your cart is empty. Add a product from the chat recommendations.</div>', unsafe_allow_html=True)
        else:
            for it in cart_items:
                tag = "👥 Group" if it.get("is_group_buy") else "🛒 Single"
                st.markdown(
                    f'<div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:10px 12px;margin-bottom:6px;">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;">'
                    f'<span style="font-size:0.82rem;color:#4db6ac;font-weight:600;">{it["product_id"]}</span>'
                    f'<span style="font-size:0.78rem;background:rgba(76,175,80,0.15);border-radius:5px;padding:2px 8px;color:#81c784;">¥{it.get("line_total",0):.2f}</span>'
                    f'</div>'
                    f'<div style="font-size:0.75rem;color:#78909c;margin-top:3px;">{tag} × {it["quantity"]}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            st.markdown(
                f'<div style="text-align:right;font-size:1rem;color:#a5d6a7;font-weight:700;padding:6px 0;">Total: ¥{cart.get("total_amount",0):.2f}</div>',
                unsafe_allow_html=True,
            )
            col_co, col_cl = st.columns(2)
            with col_co:
                if st.button("✅ Checkout", use_container_width=True, key="sb_checkout_btn"):
                    res = _checkout()
                    if res.get("error"):
                        st.error(f"Checkout failed: {res['error']}")
                    else:
                        orders = res.get("orders", [])
                        # Store order IDs for tracking
                        if "tracked_orders" not in st.session_state:
                            st.session_state.tracked_orders = []
                        for o in orders:
                            st.session_state.tracked_orders.append(o)
                        lines = "\n".join(
                            f"- Order `{o['id']}` — tracking `{o.get('tracking_number')}` ({o.get('courier')}, {o.get('estimated_delivery')})"
                            for o in orders
                        )
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": f"✅ Order placed! {len(orders)} order(s) created:\n\n{lines}\n\nYou can track your shipment in the sidebar under 'Shipment Tracking'.",
                            "ts": datetime.now().strftime("%H:%M"),
                            "data": {"intent": "logistics"},
                        })
                        st.rerun()
            with col_cl:
                if st.button("🗑️ Clear", use_container_width=True, key="sb_clear_cart_btn"):
                    try:
                        requests.post(f"{API_URL}/cart/clear", json={"session_id": st.session_state.session_id}, timeout=10)
                    except Exception:
                        pass
                    st.rerun()

    # ── 🚚 Shipment Tracking ─────────────────────────────────────────────────────
    with st.expander("🚚  Shipment Tracking", expanded=False):
        # Manual order ID input
        order_id_input = st.text_input(
            "Order ID", placeholder="e.g. PDD2026060312345", key="order_id",
            label_visibility="collapsed"
        )
        if st.button("🔍 Track Order", use_container_width=True, key="track_btn"):
            if order_id_input.strip():
                try:
                    r = requests.get(f"{API_URL}/order/{order_id_input.strip()}", params={"session_id": st.session_state.session_id}, timeout=10)
                    if r.status_code == 200:
                        order_data = r.json()
                    else:
                        order_data = None
                except Exception:
                    order_data = None
                
                if order_data:
                    status = order_data.get("status", "Unknown")
                    tracking = order_data.get("tracking_number", "N/A")
                    courier = order_data.get("courier", "N/A")
                    eta = order_data.get("estimated_delivery", "N/A")
                    status_emoji = {"pending": "⏳", "shipped": "🚚", "delivered": "✅", "cancelled": "❌"}.get(status.lower(), "📦")
                    st.markdown(f"""
                    <div style="background:rgba(76,175,80,0.1);border:1px solid rgba(76,175,80,0.3);border-radius:10px;padding:14px;margin-top:8px;">
                      <div style="font-size:0.9rem;font-weight:700;color:#a5d6a7;">{status_emoji} {status.title()}</div>
                      <div style="font-size:0.78rem;color:#b0bec5;margin-top:8px;line-height:1.8;">
                        📦 Order: <span style="color:#fff;">{order_id_input.strip()}</span><br>
                        📬 Tracking: <span style="color:#4db6ac;">{tracking}</span><br>
                        🚚 Courier: <span style="color:#fff;">{courier}</span><br>
                        📅 ETA: <span style="color:#ffb74d;">{eta}</span>
                      </div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown('<div style="font-size:0.82rem;color:#ef5350;margin-top:8px;">Order not found. Please check the order ID.</div>', unsafe_allow_html=True)
            else:
                st.warning("Please enter an Order ID.")

        # Show previously placed orders from this session
        if st.session_state.get("tracked_orders"):
            st.markdown('<div style="font-size:0.78rem;color:#78909c;margin-top:12px;margin-bottom:4px;">Recent Orders (this session):</div>', unsafe_allow_html=True)
            for o in st.session_state.get("tracked_orders", []):
                st.markdown(
                    f'<div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:10px;margin-bottom:6px;">'
                    f'<div style="font-size:0.78rem;color:#4db6ac;font-weight:600;">Order #{o.get("id","")}</div>'
                    f'<div style="font-size:0.73rem;color:#78909c;margin-top:4px;line-height:1.7;">'
                    f'📬 {o.get("tracking_number","N/A")}<br>🚚 {o.get("courier","N/A")}<br>📅 ETA: {o.get("estimated_delivery","N/A")}'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

    # ── 🎯 Quick Questions ────────────────────────────────────────────────────────
    with st.expander("🎯  Quick Questions", expanded=False):
        quick_questions = [
            "What courier service do you use?",
            "How do I mix the medicine with water?",
            "My tomato leaves have spots, what's wrong?",
            "How many days after spraying before harvest?",
            "I need an invoice for my order",
        ]
        for qq in quick_questions:
            if st.button(qq, key=f"sb_qq_{hash(qq)}", use_container_width=True):
                _process_turn(qq, None, None)
                st.rerun()

    # ── ℹ️ About ──────────────────────────────────────────────────────────────────
    with st.expander("ℹ️  About", expanded=False):
        sid = st.session_state.session_id
        st.markdown(
            f'<div style="font-size:0.78rem;color:#78909c;line-height:1.7;">'
            f'<b style="color:#b2dfdb;">Agro-Mind AI</b><br>'
            f'Pinduoduo Agricultural Support<br>'
            f'Ships from: Zhejiang, China<br>'
            f'Courier: Postal (邮政)<br>'
            f'Delivery: 3–5 business days<br><br>'
            f'<b>Session ID:</b><br>'
            f'<code style="font-size:0.68rem;">{sid[:18]}…</code>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if st.button("🔄 New Session", use_container_width=True, key="sb_new_session"):
            st.session_state.session_id = str(uuid.uuid4())
            st.session_state.messages = []
            st.session_state.uploaded_image = None
            st.session_state.tracked_orders = []
            st.rerun()


# ── Main layout ────────────────────────────────────────────────────────────────
col_main, col_info = st.columns([3, 1])

with col_main:
    # Header
    st.markdown("""
    <div class="agro-header">
      <h1>🌿 Agro-Mind AI</h1>
      <p>Your intelligent agricultural support on Pinduoduo — crop diagnosis, product recommendations, and order management.</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Main Chat Layout ────────────────────────────────────────────────────────────

    # Auto-trigger INIT_SESSION on new load
    if not st.session_state.messages:
        try:
            response_data = _send_message(message="INIT_SESSION", image_bytes=None, order_id=None)
            if response_data.get("response_text"):
                # If backend returns a greeting/proactive message, display it
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response_data["response_text"],
                    "ts": datetime.now().strftime("%H:%M"),
                    "intent": response_data.get("intent", "greeting")
                })
        except Exception:
            pass

    # ── Today's Tasks + Overdue Reminders (main chat area) ─────────────────────
    try:
        treatments = _get_treatments()
        if treatments:
            from datetime import date, timedelta
            today_str = datetime.now().strftime("%Y-%m-%d")
            yesterday_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

            # Collect today's tasks and overdue (not done) past tasks
            todays_tasks = []       # [{"treatment": tr, "task": t}]
            overdue_tasks = []      # [{"treatment": tr, "task": t}]

            for tr in treatments:
                for task in tr.get("daily_tasks", []):
                    task_date = task.get("date", "")
                    is_done = task.get("done", False)
                    if task_date == today_str:
                        todays_tasks.append({"treatment": tr, "task": task})
                    elif task_date < today_str and not is_done:
                        overdue_tasks.append({"treatment": tr, "task": task})

            if todays_tasks or overdue_tasks:
                # ── Overdue reminder banner ────────────────────────────────────
                if overdue_tasks:
                    overdue_html = ""
                    for item in overdue_tasks:
                        tr = item["treatment"]
                        task = item["task"]
                        crop = tr.get("crop") or tr.get("product_id", "")
                        disease = tr.get("disease") or ""
                        desc = task.get("task", "")
                        task_date = task.get("date", "")
                        overdue_html += (
                            f'<div style="display:flex;align-items:flex-start;gap:10px;padding:8px 0;border-bottom:1px solid rgba(255,87,34,0.15);">'
                            f'<span style="font-size:1rem;margin-top:2px;">⚠️</span>'
                            f'<div>'
                            f'<div style="font-size:0.85rem;color:#ff8a65;font-weight:600;">{crop}{(" — " + disease) if disease else ""}</div>'
                            f'<div style="font-size:0.78rem;color:#b0bec5;margin-top:2px;">{desc}</div>'
                            f'<div style="font-size:0.7rem;color:#78909c;margin-top:2px;">Was due: {task_date}</div>'
                            f'</div></div>'
                        )
                    st.markdown(f"""
                    <div style="background:linear-gradient(135deg,#1a0e00,#2a1500);border:1px solid rgba(255,87,34,0.4);border-radius:14px;padding:16px 20px;margin-bottom:14px;box-shadow:0 4px 20px rgba(255,87,34,0.15);">
                      <div style="font-size:1rem;font-weight:700;color:#ff8a65;margin-bottom:12px;">⏰ Overdue Tasks — Not Completed Yet!</div>
                      {overdue_html}
                    </div>
                    """, unsafe_allow_html=True)

                # ── Today's tasks banner ────────────────────────────────────────
                if todays_tasks:
                    all_done_today = all(item["task"].get("done", False) for item in todays_tasks)
                    tasks_html = ""
                    for item in todays_tasks:
                        tr = item["treatment"]
                        task = item["task"]
                        is_done = task.get("done", False)
                        crop = tr.get("crop") or tr.get("product_id", "")
                        disease = tr.get("disease") or ""
                        desc = task.get("task", "")
                        day_num = task.get("day", 0)
                        tr_id = tr.get("id", 0)
                        done_style = "opacity:0.5;text-decoration:line-through;" if is_done else ""
                        done_icon = " ✅" if is_done else ""
                        tasks_html += (
                            f'<div style="display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-bottom:1px solid rgba(76,175,80,0.12);">'
                            f'<span style="font-size:1.1rem;margin-top:1px;">{"✅" if is_done else "🌱"}</span>'
                            f'<div style="flex:1;{done_style}">'
                            f'<div style="font-size:0.9rem;color:#a5d6a7;font-weight:600;">{crop}{(" — " + disease) if disease else ""}{done_icon}</div>'
                            f'<div style="font-size:0.82rem;color:#cfd8dc;margin-top:3px;">{desc}</div>'
                            f'</div>'
                            f'</div>'
                        )

                    header_color = "#a5d6a7" if not all_done_today else "#66bb6a"
                    header_text = "📅 Today's Tasks" if not all_done_today else "🎉 All Done for Today!"
                    border_color = "rgba(76,175,80,0.4)" if not all_done_today else "rgba(102,187,106,0.6)"

                    st.markdown(f"""
                    <div style="background:linear-gradient(135deg,#0d2b1a,#0a2240);border:1px solid {border_color};border-radius:14px;padding:16px 20px;margin-bottom:16px;box-shadow:0 4px 20px rgba(0,0,0,0.3);">
                      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                        <div style="font-size:1rem;font-weight:700;color:{header_color};">{header_text}</div>
                        <div style="font-size:0.75rem;color:#546e7a;">{datetime.now().strftime("%A, %b %d")}</div>
                      </div>
                      {tasks_html}
                    </div>
                    """, unsafe_allow_html=True)

                    # Checkboxes to mark tasks done (one per treatment today)
                    for item in todays_tasks:
                        tr = item["treatment"]
                        task = item["task"]
                        is_done = task.get("done", False)
                        day_num = task.get("day", 0)
                        tr_id = tr.get("id", 0)
                        crop = tr.get("crop") or tr.get("product_id", "")
                        col_chk, col_lbl = st.columns([1, 10])
                        with col_chk:
                            checked = st.checkbox("", value=is_done, key=f"main_today_{tr_id}_{day_num}", label_visibility="collapsed")
                            if checked != is_done:
                                _mark_task_done(tr_id, day_num)
                                st.rerun()
                        with col_lbl:
                            st.markdown(f'<div style="font-size:0.82rem;color:#78909c;padding-top:6px;">Mark done: {crop} Day {day_num}</div>', unsafe_allow_html=True)

    except Exception:
        pass

    # ── Chat Area Fragment ────────────────────────────────────────────────────────
    @st.fragment
    def chat_interface():
        chat_container = st.container()
        
        uploaded_file = st.file_uploader(
            "Upload Image (Optional)",
            type=["jpg", "jpeg", "png", "webp"],
            label_visibility="collapsed",
            key="inline_uploader"
        )
        
        # 1. Input area
        prompt = st.chat_input("Ask about your crop disease, order status, product dosage…")
        
        # Handle quick-input from sidebar buttons
        default_text = st.session_state.pop("quick_input", "")
        if default_text and not prompt:
            # We can't automatically submit a chat_input, so we use _process_turn directly
            # Note: This is handled by the sidebar button already, but if needed we can handle it here.
            pass

        if prompt:
            user_text = prompt
            image_bytes = uploaded_file.read() if uploaded_file else None
                
            _process_turn(user_text, image_bytes, st.session_state.get("order_id", "").strip() or None)
            
        # 2. Render messages
        with chat_container:
            if not st.session_state.messages:
                st.markdown("""
                <div style="text-align:center;padding:40px 20px;opacity:0.6;">
                  <div style="font-size:3rem;">🌾</div>
                  <div style="font-size:1.1rem;color:#80cbc4;margin-top:12px;">
                    Dear customer, I'm here to help!
                  </div>
                  <div style="font-size:0.85rem;color:#546e7a;margin-top:8px;">
                    Ask about crops, pests, products, or your orders.
                  </div>
                </div>
                """, unsafe_allow_html=True)

            for msg in st.session_state.messages:
                ts = msg.get("ts", "")
                if msg["role"] == "user":
                    img_note = " 📷" if msg.get("has_image") else ""
                    st.markdown(
                        f'<div class="user-bubble">👤 {msg["content"]}{img_note}'
                        f'<div class="msg-ts">{ts}</div></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    data = msg.get("data", {})
                    intent = data.get("intent", "general_qa")
                    badge_html = _intent_badge(intent)

                    # Safety escalation banner
                    if data.get("safety_risk_detected"):
                        st.markdown(f"""
                        <div class="safety-banner">
                          <h3>🚨 Safety Alert — Human Support Activated</h3>
                          <p>{data.get('response_text', '')}</p>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        escalate_html = ""
                        if data.get("escalate_human"):
                            escalate_html = '<div class="escalate-tag">👨‍🌾 Escalated to human agronomist</div>'

                        st.markdown(
                            f'<div class="agent-bubble">'
                            f'{badge_html}<br>'
                            f'🤖 {data.get("response_text", msg["content"])}'
                            f'{escalate_html}'
                            f'<div class="msg-ts">{ts}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                        # Product cards (Carousel)
                        products = data.get("matched_products", [])
                        if products:
                            idx_key = f"prod_idx_{ts}"
                            if idx_key not in st.session_state:
                                st.session_state[idx_key] = 0
                                
                            if st.session_state[idx_key] >= len(products):
                                st.session_state[idx_key] = 0
                                
                            current_prod = products[st.session_state[idx_key]]
                            st.markdown(_render_product_card(current_prod), unsafe_allow_html=True)
                            
                            with st.container():
                                prod_id = current_prod.get('product_id', str(uuid.uuid4())[:6])
                                prod_name = current_prod.get('product_name', 'Product')
                                
                                st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
                                col_qty, col_btn1, col_btn2 = st.columns([1, 2, 2])
                                with col_qty:
                                    qty = st.number_input("Qty", min_value=1, max_value=100, value=1, key=f"qty_{ts}_{prod_id}", label_visibility="collapsed")
                                with col_btn1:
                                    if st.button(f"🛒 Single ({qty})", key=f"btn_{ts}_{prod_id}", use_container_width=True):
                                        result = _cart_add(prod_id, qty, is_group_buy=False)
                                        if result.get("error"):
                                            st.session_state.messages.append({"role": "assistant", "content": f"⚠️ Error: {result['error']}", "ts": datetime.now().strftime("%H:%M"), "data": {"intent": "logistics"}})
                                        else:
                                            st.session_state.messages.append({"role": "assistant", "content": f"✅ Added **{qty}x {prod_name}** to cart. Total: ¥{result.get('total_amount', 0):.2f}.", "ts": datetime.now().strftime("%H:%M"), "data": {"intent": "logistics"}})
                                        st.rerun() # Full app rerun to update sidebar cart
                                with col_btn2:
                                    if st.button(f"👥 Group ({qty})", key=f"btn_grp_{ts}_{prod_id}", use_container_width=True):
                                        result = _cart_add(prod_id, qty, is_group_buy=True)
                                        if result.get("error"):
                                            st.session_state.messages.append({"role": "assistant", "content": f"⚠️ Error: {result['error']}", "ts": datetime.now().strftime("%H:%M"), "data": {"intent": "logistics"}})
                                        else:
                                            st.session_state.messages.append({"role": "assistant", "content": f"👥 Added **{qty}x {prod_name}** to group purchase. Check cart.", "ts": datetime.now().strftime("%H:%M"), "data": {"intent": "logistics"}})
                                        st.rerun()

                            if len(products) > 1:
                                st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
                                col_prev, col_status, col_next = st.columns([1, 2, 1])
                                with col_prev:
                                    if st.button("⬅️ Prev", key=f"prev_{ts}", use_container_width=True):
                                        st.session_state[idx_key] = (st.session_state[idx_key] - 1) % len(products)
                                        st.rerun(scope="fragment")
                                with col_status:
                                    st.markdown(f"<div style='text-align: center; color: #b0bec5; font-size: 0.9rem; margin-top: 6px;'>Product {st.session_state[idx_key] + 1} of {len(products)}</div>", unsafe_allow_html=True)
                                with col_next:
                                    if st.button("Next ➡️", key=f"next_{ts}", use_container_width=True):
                                        st.session_state[idx_key] = (st.session_state[idx_key] + 1) % len(products)
                                        st.rerun(scope="fragment")

            # 3. Stream pending turn
            if st.session_state.get("pending_turn"):
                pending = st.session_state.pop("pending_turn")
                response_data = _stream_turn(pending)
                st.session_state.uploaded_image = None
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response_data.get("response_text", ""),
                    "ts": datetime.now().strftime("%H:%M"),
                    "data": response_data,
                })
                st.rerun(scope="fragment")

    chat_interface()


# ── Right column — cart, stats & catalog preview ───────────────────────────────
with col_info:
    # ── Shopping cart ──────────────────────────────────────────────────────────
    st.markdown("### 🛒 Cart")
    cart = _get_cart()
    cart_items = cart.get("items", [])
    if not cart_items:
        st.markdown(
            '<div style="font-size:0.82rem;color:#546e7a;">Your cart is empty. '
            'Add a recommended product from the chat.</div>',
            unsafe_allow_html=True,
        )
    else:
        for it in cart_items:
            tag = "👥" if it.get("is_group_buy") else "🛒"
            st.markdown(
                f'<div style="font-size:0.8rem;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.05);">'
                f'{tag} <span style="color:#4db6ac;">{it["product_id"]}</span> '
                f'<span style="color:#cfd8dc;">×{it["quantity"]}</span> '
                f'<span style="color:#81c784;float:right;">¥{it.get("line_total", 0):.2f}</span></div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            f'<div style="font-size:0.95rem;color:#e8f5e9;margin-top:8px;font-weight:600;">'
            f'Total: ¥{cart.get("total_amount", 0):.2f}</div>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ Checkout", use_container_width=True, key="checkout_btn"):
                res = _checkout()
                if res.get("error"):
                    st.error(f"Checkout failed: {res['error']}")
                else:
                    orders = res.get("orders", [])
                    lines = "\n".join(
                        f"- Order `{o['id']}` — tracking `{o.get('tracking_number')}` "
                        f"({o.get('courier')}, {o.get('estimated_delivery')})"
                        for o in orders
                    )
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": f"✅ Order placed! {len(orders)} order(s) created:\n\n{lines}\n\n"
                                   "Ask about your order status anytime (logistics).",
                        "ts": datetime.now().strftime("%H:%M"),
                        "data": {"intent": "logistics"},
                    })
                    st.rerun()
        with c2:
            if st.button("🗑️ Clear", use_container_width=True, key="clear_cart_btn"):
                try:
                    requests.post(
                        f"{API_URL}/cart/clear",
                        json={"session_id": st.session_state.session_id},
                        timeout=10,
                    )
                except Exception:
                    pass
                st.rerun()

    st.markdown("---")
    st.markdown("### 📊 Session Stats")

    user_msgs = sum(1 for m in st.session_state.messages if m["role"] == "user")
    agent_msgs = sum(1 for m in st.session_state.messages if m["role"] == "assistant")
    safety_flags = sum(
        1 for m in st.session_state.messages
        if m["role"] == "assistant" and m.get("data", {}).get("safety_risk_detected")
    )

    st.metric("Messages sent", user_msgs)
    st.metric("Responses", agent_msgs)
    if safety_flags:
        st.metric("⚠️ Safety flags", safety_flags, delta=None)

    st.markdown("---")
    st.markdown("### 🗂️ Intent Legend")
    legend = [
        ("🔬", "Diagnosis", "#1565c0"),
        ("📦", "Logistics", "#e65100"),
        ("🛒", "Product Rec.", "#1b5e20"),
        ("💬", "General QA", "#4a148c"),
        ("🚨", "Safety", "#b71c1c"),
    ]
    for icon, label, color in legend:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0;">'
            f'<div style="width:8px;height:8px;border-radius:50%;background:{color};"></div>'
            f'<span style="font-size:0.82rem;color:#b0bec5;">{icon} {label}</span></div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.markdown("### 📋 Quick Catalog")
    try:
        @st.cache_data(ttl=300)
        def _get_cached_catalog():
            resp = requests.get(f"{API_URL}/catalog", timeout=5)
            if resp.status_code == 200:
                return resp.json().get("products", [])
            return None
            
        products_list = _get_cached_catalog()
        if products_list is not None:
            st.markdown(
                f'<div style="font-size:0.8rem;color:#81c784;margin-bottom:8px;">'
                f'{len(products_list)} products available</div>',
                unsafe_allow_html=True,
            )
            for prod in products_list[:8]:
                st.markdown(
                    f'<div style="font-size:0.78rem;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.05);">'
                    f'<span style="color:#4db6ac;">{prod["product_id"]}</span> '
                    f'<span style="color:#cfd8dc;">{prod["product_name"][:30]}</span></div>',
                    unsafe_allow_html=True,
                )
            if len(products_list) > 8:
                st.markdown(
                    f'<div style="font-size:0.75rem;color:#546e7a;margin-top:4px;">+ {len(products_list)-8} more…</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div style="font-size:0.78rem;color:#546e7a;">Catalog unavailable (backend offline)</div>',
                unsafe_allow_html=True,
            )
    except Exception:
        st.markdown(
            '<div style="font-size:0.78rem;color:#546e7a;">Catalog unavailable (backend offline)</div>',
            unsafe_allow_html=True,
        )
