"""
frontend/app.py
───────────────
Agro-Mind AI — Premium Streamlit Chat Interface
Meticulously updated to feature beautiful, dynamic, bilingual horizontal 
product sliders with standalone "Add to Cart" functional execution.
"""

from __future__ import annotations

import base64
import json
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

# ── Custom CSS (with premium horizontal flex-scrolling and cart design) ────────
st.markdown("""
<style>
  /* === Google Font === */
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Cairo:wght@400;600;700&display=swap');

  /* === Global === */
  html, body, [class*="css"] {
    font-family: 'Inter', 'Cairo', sans-serif !important;
  }

  /* === Dark background === */
  .stApp {
    background: linear-gradient(135deg, #0a1628 0%, #0d2137 50%, #0a1a10 100%) !important;
    color: #e8f5e9 !important;
  }

  /* === Sidebar === */
  [data-testid="stSidebar"] {
    background: linear-gradient(180deg, #061020 0%, #0a1a10 100%) !important;
    border-right: 1px solid #1e4d2b !important;
  }
  [data-testid="stSidebar"] * { color: #b2dfdb !important; }

  /* === Header === */
  .agro-header {
    background: linear-gradient(135deg, #1b5e20, #004d40, #0d47a1) !important;
    border-radius: 16px !important;
    padding: 24px 32px !important;
    margin-bottom: 24px !important;
    box-shadow: 0 8px 32px rgba(0,150,50,0.25) !important;
    border: 1px solid rgba(76,175,80,0.3) !important;
  }
  .agro-header h1 {
    font-size: 2.2rem !important;
    font-weight: 700 !important;
    color: #a5d6a7 !important;
    margin: 0 !important;
  }

  /* === Chat messages === */
  .user-bubble {
    background: linear-gradient(135deg, #1565c0, #0277bd) !important;
    border-radius: 18px 18px 4px 18px !important;
    padding: 14px 18px !important;
    margin: 8px 0 8px 15% !important;
    color: #e3f2fd !important;
    box-shadow: 0 4px 12px rgba(21,101,192,0.3) !important;
  }

  .agent-bubble {
    background: linear-gradient(135deg, #1b5e20, #2e7d32) !important;
    border-radius: 18px 18px 18px 4px !important;
    padding: 14px 18px !important;
    margin: 8px 15% 8px 0 !important;
    color: #e8f5e9 !important;
    box-shadow: 0 4px 12px rgba(27,94,32,0.3) !important;
  }

  /* === PREMIUM HORIZONTAL SCROLL INTERFACE === */
  .product-slider-wrapper {
    display: flex !important;
    overflow-x: auto !important;
    gap: 20px !important;
    padding: 15px 10px !important;
    scroll-behavior: smooth !important;
    scrollbar-width: thin !important;
    scrollbar-color: #4caf50 #0d2137 !important;
  }
  
  .product-slider-wrapper::-webkit-scrollbar {
    height: 8px !important;
  }
  .product-slider-wrapper::-webkit-scrollbar-thumb {
    background: #4caf50 !important;
    border-radius: 10px !important;
  }

  .horizontal-card {
    min-width: 300px !important;
    max-width: 300px !important;
    background: linear-gradient(135deg, #0d2137, #132d4a) !important;
    border: 2px solid rgba(76,175,80,0.4) !important;
    border-radius: 16px !important;
    padding: 20px !important;
    box-shadow: 0 6px 20px rgba(0,0,0,0.4) !important;
    display: flex !important;
    flex-direction: column !important;
    justify-content: space-between !important;
  }
  
  .horizontal-card:hover {
    border-color: rgba(76,175,80,0.9) !important;
    transform: translateY(-4px) !important;
    transition: all 0.2s ease-in-out !important;
  }

  .product-id {
    font-size: 0.75rem !important;
    color: #81c784 !important;
    font-weight: 600 !important;
    letter-spacing: 1px !important;
  }
  .product-name {
    font-size: 1.15rem !important;
    font-weight: 700 !important;
    color: #ffffff !important;
    margin: 4px 0 !important;
  }
  .product-type-badge {
    display: inline-block !important;
    background: rgba(76,175,80,0.2) !important;
    border: 1px solid rgba(76,175,80,0.4) !important;
    border-radius: 20px !important;
    padding: 2px 10px !important;
    font-size: 0.75rem !important;
    color: #81c784 !important;
  }
  .price-group {
    font-size: 1.4rem !important;
    font-weight: 700 !important;
    color: #ff7043 !important;
    margin: 10px 0 2px 0 !important;
  }
  .price-single {
    font-size: 0.9rem !important;
    color: #b0bec5 !important;
    text-decoration: line-through !important;
    margin-bottom: 10px !important;
  }
  .dosage-info {
    background: rgba(0,0,0,0.3) !important;
    border-radius: 8px !important;
    padding: 10px !important;
    font-size: 0.85rem !important;
    color: #b2dfdb !important;
    border-left: 3px solid #4caf50 !important;
  }

  /* === Custom Native Buttons Overrides === */
  div.stButton > button {
    width: 100% !important;
    background: linear-gradient(135deg, #2e7d32 0%, #1565c0 100%) !important;
    color: white !important;
    border-radius: 10px !important;
    border: none !important;
    padding: 8px 16px !important;
    font-weight: bold !important;
  }
  
  /* === Safety banner === */
  .safety-banner {
    background: linear-gradient(135deg, #b71c1c, #880e4f) !important;
    border: 2px solid #ef5350 !important;
    border-radius: 12px !important;
    padding: 20px 24px !important;
    box-shadow: 0 0 30px rgba(239,83,80,0.4) !important;
  }
  .msg-ts {
    font-size: 0.7rem !important;
    color: rgba(255,255,255,0.3) !important;
    text-align: right !important;
  }
</style>
""", unsafe_allow_html=True)

# ── Session state initialisation ───────────────────────────────────────────────
# Stable customer identity: stored in the URL query params after login so it
# survives refresh and links the profile/cart/history across chats.
if "logged_in" not in st.session_state:
    existing_uid = st.query_params.get("uid")
    st.session_state.logged_in = bool(existing_uid)
    st.session_state.user_id = existing_uid or ""
if "user_id" not in st.session_state:
    st.session_state.user_id = st.query_params.get("uid") or ""
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "uploaded_image" not in st.session_state:
    st.session_state.uploaded_image = None
if "cart" not in st.session_state:
    st.session_state.cart = []

if not st.session_state.logged_in:
    try:
        customers_response = requests.get(f"{API_URL}/customers", params={"limit": 50}, timeout=4)
        customers_response.raise_for_status()
        existing_customers = customers_response.json().get("customers", [])
    except Exception:
        existing_customers = []

    st.markdown("""
    <div class="agro-header">
      <h1>🌿 Agro-Mind AI Login</h1>
      <p>سجل دخولك عشان نحفظ ملفك، محادثاتك، السلة، والمشاكل الزراعية.</p>
    </div>
    """, unsafe_allow_html=True)
    with st.form("demo_login"):
        customer_options = ["New customer / عميل جديد"] + [
            (
                f"{customer.get('username') or customer.get('external_id')} "
                f"- {customer.get('crop_type') or 'no crop'} "
                f"({customer.get('message_count', 0)} msgs)"
            )
            for customer in existing_customers
        ]
        selected_customer = st.selectbox(
            "Existing customers / العملاء السابقون",
            customer_options,
            index=0,
        )
        selected_index = customer_options.index(selected_customer)
        selected_record = existing_customers[selected_index - 1] if selected_index > 0 else None
        username_default = selected_record.get("external_id") if selected_record else ""
        username = st.text_input(
            "Username / اسم المستخدم",
            value=username_default,
            placeholder="mayadah",
        ).strip()
        password = st.text_input("Password / كلمة المرور", type="password").strip()
        submitted = st.form_submit_button("Login / دخول", use_container_width=True)
    if submitted:
        try:
            login_response = requests.post(
                f"{API_URL}/auth/login",
                json={
                    "username": username,
                    "password": password,
                    "session_id": st.session_state.session_id,
                },
                timeout=5,
            )
            login_response.raise_for_status()
            login_data = login_response.json()
            st.session_state.user_id = login_data["external_id"]
            st.session_state.logged_in = True
            st.query_params["uid"] = st.session_state.user_id
            st.rerun()
        except requests.exceptions.HTTPError:
            st.error("Password is 123456 / كلمة المرور 123456")
        except Exception as exc:
            st.error(f"Could not login: {exc}")
    st.stop()

# ── Helper functions ───────────────────────────────────────────────────────────
def _is_arabic(text: str) -> bool:
    """Detect if the text contains Arabic characters to toggle display labels."""
    return any("\u0600" <= char <= "\u06FF" for char in text)

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

def _send_message(message: str, image_bytes: Optional[bytes], order_id: Optional[str]) -> dict:
    payload: dict = {
        "session_id": st.session_state.session_id,
        "external_id": st.session_state.user_id,
        "message": message,
    }
    if image_bytes:
        payload["image_base64"] = base64.b64encode(image_bytes).decode()
    if order_id:
        payload["order_id"] = order_id

    try:
        response = requests.post(f"{API_URL}/chat", json=payload, timeout=75)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {
            "intent": "general_qa",
            "safety_risk_detected": False,
            "escalate_human": False,
            "response_text": (
                "The assistant is taking longer than expected to respond. "
                "Please try again in a moment, or check that the model/API connection is healthy."
            ),
            "recommended_product_id": None,
            "group_purchase_triggered": False,
            "human_summary_brief": None,
            "matched_products": [],
            "session_id": st.session_state.session_id,
        }
    except Exception as exc:
        return {
            "intent": "general_qa",
            "safety_risk_detected": False,
            "escalate_human": False,
            "response_text": f"Could not reach the chat backend: {exc}",
            "recommended_product_id": None,
            "group_purchase_triggered": False,
            "human_summary_brief": None,
            "matched_products": [],
            "session_id": st.session_state.session_id,
        }

def _check_backend() -> bool:
    try:
        r = requests.get(f"{API_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False

def _load_cart() -> dict:
    try:
        response = requests.get(
            f"{API_URL}/cart",
            params={
                "session_id": st.session_state.session_id,
                "external_id": st.session_state.user_id,
            },
            timeout=5,
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        return {"items": st.session_state.get("cart", []), "total_amount": 0}

def _add_cart_item(product_id: str, diagnosis_id: Optional[int], source: str = "manual") -> dict:
    response = requests.post(
        f"{API_URL}/cart/items",
        json={
            "session_id": st.session_state.session_id,
            "external_id": st.session_state.user_id,
            "product_id": product_id,
            "quantity": 1,
            "is_group_buy": True,
            "diagnosis_id": diagnosis_id,
            "source": source,
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()

def _clear_cart() -> dict:
    response = requests.delete(
        f"{API_URL}/cart",
        params={
            "session_id": st.session_state.session_id,
            "external_id": st.session_state.user_id,
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()

def _load_orders() -> list[dict]:
    try:
        response = requests.get(
            f"{API_URL}/orders",
            params={
                "session_id": st.session_state.session_id,
                "external_id": st.session_state.user_id,
            },
            timeout=5,
        )
        response.raise_for_status()
        return response.json().get("orders", [])
    except Exception:
        return []

def _checkout_cart() -> list[dict]:
    response = requests.post(
        f"{API_URL}/orders/checkout",
        json={
            "session_id": st.session_state.session_id,
            "external_id": st.session_state.user_id,
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json().get("orders", [])

def _load_profile() -> dict:
    try:
        response = requests.get(
            f"{API_URL}/profile",
            params={
                "session_id": st.session_state.session_id,
                "external_id": st.session_state.user_id,
            },
            timeout=5,
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        return {"name": "", "location": "", "crop_type": ""}

def _save_profile(name: str, location: str, crop_type: str) -> dict:
    try:
        response = requests.put(
            f"{API_URL}/profile",
            json={
                "session_id": st.session_state.session_id,
                "external_id": st.session_state.user_id,
                "name": name,
                "location": location,
                "crop_type": crop_type,
            },
            timeout=4,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("Database request timed out. For the local demo, use SQLite or check the remote DB connection.") from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Could not save profile: {exc}") from exc

def _load_chat_history(limit: int = 0) -> list[dict]:
    try:
        response = requests.get(
            f"{API_URL}/chat-history",
            params={
                "session_id": st.session_state.session_id,
                "external_id": st.session_state.user_id,
                "limit": limit,
                "include_images": True,
            },
            timeout=8,
        )
        response.raise_for_status()
        rows = response.json().get("messages", [])
        messages: list[dict] = []
        for row in rows:
            created_at = row.get("created_at") or ""
            ts = created_at[11:16] if len(created_at) >= 16 else ""
            message = {
                "role": row.get("role", "assistant"),
                "content": row.get("content", ""),
                "ts": ts,
                "has_image": bool(row.get("has_image", False)),
            }
            attachments = row.get("attachments") or []
            if attachments:
                message["image_base64"] = attachments[0].get("data_base64")
                message["image_mime_type"] = attachments[0].get("mime_type", "image/jpeg")
            if row.get("role") == "assistant":
                message["data"] = {
                    "intent": row.get("intent") or "general_qa",
                    "response_text": row.get("content", ""),
                    "safety_risk_detected": False,
                    "escalate_human": False,
                    "matched_products": [],
                }
            messages.append(message)
        return messages
    except Exception:
        return []


if st.session_state.logged_in and st.session_state.get("history_loaded_for") != st.session_state.user_id:
    if not st.session_state.messages:
        st.session_state.messages = _load_chat_history()
    st.session_state.history_loaded_for = st.session_state.user_id

# ── Sidebar layout ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🌿 Agro-Mind AI")
    st.markdown("---")

    backend_ok = _check_backend()
    status_color = "#4caf50" if backend_ok else "#ef5350"
    status_label = "Connected" if backend_ok else "Offline"
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;">'
        f'<div style="width:10px;height:10px;border-radius:50%;background:{status_color};"></div>'
        f'<span style="font-size:0.85rem;">Backend: {status_label}</span></div>',
        unsafe_allow_html=True,
    )

    profile = _load_profile() if backend_ok else {"name": "", "location": "", "crop_type": ""}
    with st.expander("👤 My Farm Profile / ملفي", expanded=not bool(profile.get("crop_type"))):
        with st.form("profile_form"):
            profile_name = st.text_input("Name / الاسم", value=profile.get("name", ""))
            profile_location = st.text_input("Location / الموقع", value=profile.get("location", ""))
            profile_crop = st.text_input("Main crop / المحصول", value=profile.get("crop_type", ""))
            save_profile = st.form_submit_button("Save Profile / حفظ الملف", use_container_width=True)
        if save_profile:
            if backend_ok:
                try:
                    _save_profile(profile_name, profile_location, profile_crop)
                    st.success("Profile saved / تم حفظ الملف")
                except RuntimeError as exc:
                    st.error(str(exc))
            else:
                st.warning("Backend is offline. Profile was not saved.")

    if st.button("Logout / تسجيل خروج", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.user_id = ""
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.cart = []
        st.session_state.history_loaded_for = ""
        st.query_params.clear()
        st.rerun()

    st.markdown("### 🛒 Your Cart / العربة")
    cart_snapshot = _load_cart() if backend_ok else {"items": st.session_state.cart, "total_amount": 0}
    st.session_state.cart = cart_snapshot.get("items", [])
    if st.session_state.cart:
        for idx, item in enumerate(st.session_state.cart):
            product_id = item.get("product_id") or item.get("id")
            name = item.get("product_name") or item.get("name") or product_id
            quantity = item.get("quantity", 1)
            unit_price = item.get("unit_price") or item.get("price") or 0
            st.markdown(f"**{idx+1}.** `({product_id})` {name} × {quantity} - ¥{unit_price}")
        total = cart_snapshot.get("total_amount", 0)
        if total:
            st.caption(f"Total / الإجمالي: ¥{total:.0f}")
        if st.button("🔴 Clear Cart", use_container_width=True):
            if backend_ok:
                _clear_cart()
            st.session_state.cart = []
            st.rerun()
        if backend_ok and st.button("Create Order / إنشاء طلب", use_container_width=True):
            try:
                created_orders = _checkout_cart()
                st.session_state.cart = []
                if created_orders:
                    st.session_state.order_id = created_orders[0]["id"]
                    st.toast(f"Order created: {created_orders[0]['id']}", icon="📦")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not create order: {exc}")
    else:
        st.caption("Cart is empty / العربة فارغة")

    st.markdown("---")
    st.markdown("### 📸 Image Upload")
    uploaded_file = st.file_uploader(
        "Upload crop photo", type=["jpg", "jpeg", "png", "webp"], label_visibility="collapsed"
    )
    if uploaded_file:
        st.session_state.uploaded_image = uploaded_file.read()
        st.image(BytesIO(st.session_state.uploaded_image), caption="Uploaded image", use_container_width=True)
        if st.button("🗑️ Remove image", key="remove_img"):
            st.session_state.uploaded_image = None
            st.rerun()

    st.markdown("---")
    st.markdown("### 📦 Order Tracking")
    saved_orders = _load_orders() if backend_ok else []
    selected_order_id = ""
    if saved_orders:
        order_labels = [
            (
                f"{order['id']} - {order.get('status', 'unknown')} - "
                f"{order.get('tracking_number') or 'no tracking'} - "
                f"{order.get('product_name') or order.get('product_id')}"
            )
            for order in saved_orders
        ]
        selected_label = st.selectbox("Saved orders / الطلبات المحفوظة", order_labels)
        selected_order_id = saved_orders[order_labels.index(selected_label)]["id"]
        selected_order = saved_orders[order_labels.index(selected_label)]
        st.caption(
            f"Status: {selected_order.get('status')} | "
            f"Tracking: {selected_order.get('tracking_number') or 'not issued'} | "
            f"Total: ¥{float(selected_order.get('total_amount') or 0):.0f}"
        )
    else:
        st.caption("No saved orders for this customer yet.")
    manual_order_id = st.text_input("Order ID", placeholder="PDD2026...", key="order_id") or ""
    order_id_input = manual_order_id.strip() or selected_order_id

    if st.button("🔄 New Session", use_container_width=True):
        # New conversation thread, but the SAME user_id — so the agent still
        # recognises the returning customer and recalls their profile.
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.uploaded_image = None
        st.rerun()

    st.caption(f"👤 Returning ID: `{st.session_state.user_id[:8]}`")

# ── Main Layout ────────────────────────────────────────────────────────────────
col_main, col_info = st.columns([3, 1])

with col_main:
    st.markdown("""
    <div class="agro-header">
      <h1>🌿 Agro-Mind AI (العقل الزراعي)</h1>
      <p>Bilingual AI support for Pinduoduo agricultural stores — Intelligent scrollable catalog & direct cart adding.</p>
    </div>
    """, unsafe_allow_html=True)

    # Chat history viewport
    chat_container = st.container()
    with chat_container:
        if not st.session_state.messages:
            st.markdown('<div style="text-align:center;padding:40px;opacity:0.6;">🌾 Welcome / أهلاً بك في العقل الزراعي</div>', unsafe_allow_html=True)

        for msg in st.session_state.messages:
            ts = msg.get("ts", "")
            is_user = msg["role"] == "user"
            
            if is_user:
                st.markdown(f'<div class="user-bubble">👤 {msg["content"]}<div class="msg-ts">{ts}</div></div>', unsafe_allow_html=True)
                if msg.get("image_base64"):
                    try:
                        st.image(
                            BytesIO(base64.b64decode(msg["image_base64"])),
                            caption="Uploaded image",
                            use_container_width=True,
                        )
                    except Exception:
                        st.caption("Uploaded image could not be rendered.")
            else:
                data = msg.get("data", {})
                resp_text = data.get("response_text", msg["content"])
                arabic_ui = _is_arabic(resp_text)
                
                # Check for Safety Escalations
                if data.get("safety_risk_detected"):
                    st.markdown(f'<div class="safety-banner"><h3>🚨 Safety Intercept Active</h3><p>{resp_text}</p></div>', unsafe_allow_html=True)
                else:
                    badge_html = _intent_badge(data.get("intent", "general_qa"))
                    escalate_html = '<div class="escalate-tag">👨‍🌾 Escalated to human</div>' if data.get("escalate_human") else ""
                    
                    st.markdown(
                        f'<div class="agent-bubble">{badge_html}<br>🤖 {resp_text}{escalate_html}<div class="msg-ts">{ts}</div></div>',
                        unsafe_allow_html=True
                    )

                    # ── STUNNING BILINGUAL HORIZONTAL PRODUCTS CAROUSEL (SCROLL RIGHT) ──
                    products = data.get("matched_products", [])
                    if products:
                        st.markdown("<p style='font-size:0.9rem;color:#81c784;margin-left:10px;'>⬅️ Scroll Right to see more products / اسحب لليمين لرؤية باقي المنتجات ➡️</p>", unsafe_allow_html=True)
                        
                        # Generate horizontally-aligned interactive UI using dynamic layout columns
                        item_count = len(products)
                        cols = st.columns(item_count)
                        
                        for idx, prod in enumerate(products):
                            pid = prod.get("product_id", "")
                            name = prod.get("product_name", "Unknown")
                            ptype = prod.get("product_type", "")
                            crops = prod.get("crops", "")[:80]
                            dosage = prod.get("water_ratio") or prod.get("how_to_use", "")
                            gp = prod.get("group_price", 0)
                            sp = prod.get("single_price", 0)
                            
                            # Language alignment within the product description card
                            labels = {
                                "crops": "المحاصيل:" if arabic_ui else "Crops:",
                                "group": "سعر المجموعة:" if arabic_ui else "Group price:",
                                "single": "فردي:" if arabic_ui else "Single:",
                                "dosage": "📋 الجرعة الاستخدامية:" if arabic_ui else "📋 Dosage Sheet:",
                                "btn": "🛒 إضافة للسلة" if arabic_ui else "🛒 Add to Cart"
                            }
                            
                            with cols[idx]:
                                st.markdown(f"""
                                <div class="horizontal-card">
                                    <div>
                                        <div class="product-id">{pid}</div>
                                        <div class="product-name">🌱 {name}</div>
                                        <span class="product-type-badge">{ptype}</span>
                                        <div style="margin-top:6px;font-size:0.82rem;color:#b0bec5;">
                                            <strong>{labels['crops']}</strong> {crops}
                                        </div>
                                    </div>
                                    <div>
                                        <div class="price-group">¥{gp:.0f} <span style="font-size:0.75rem;font-weight:400;color:#ff8a65;">{labels['group']}</span></div>
                                        <div class="price-single">{labels['single']} ¥{sp:.0f}</div>
                                        <div class="dosage-info">
                                            {labels['dosage']}<br>{dosage}
                                        </div>
                                    </div>
                                </div>
                                """, unsafe_allow_html=True)
                                
                                # Standalone action button for absolute transactional support inside the layout
                                if st.button(labels["btn"], key=f"cart_{st.session_state.session_id}_{pid}_{idx}"):
                                    try:
                                        st.session_state.cart = _add_cart_item(
                                            pid,
                                            data.get("diagnosis_id"),
                                            source="recommended" if data.get("diagnosis_id") else "manual",
                                        ).get("items", [])
                                        st.toast(f"🛒 Added {pid} to your merchant cart!", icon="🌿")
                                    except Exception as exc:
                                        st.session_state.cart.append({"id": pid, "name": name, "price": gp})
                                        st.toast(f"Cart saved locally only: {exc}", icon="⚠️")

    # ── Input Area ─────────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    default_text = str(st.session_state.pop("quick_input", "") or "")

    with st.form(key="chat_form", clear_on_submit=True):
        user_input = st.text_area("Your message", value=default_text, placeholder="Ask in Arabic or English / اسأل بالعربية أو الإنجليزية...", height=90, label_visibility="collapsed", key="user_input") or ""
        submit = st.form_submit_button("Send / إرسال ➤", use_container_width=True)

    user_text = user_input.strip()

    if submit and user_text:
        ts_now = datetime.now().strftime("%H:%M")
        st.session_state.messages.append({
            "role": "user",
            "content": user_text,
            "ts": ts_now,
            "has_image": st.session_state.uploaded_image is not None,
        })

        with st.spinner("🌿 Processing turn..."):
            response_data = _send_message(
                message=user_text,
                image_bytes=st.session_state.uploaded_image,
                order_id=order_id_input.strip() or None,
            )

        st.session_state.uploaded_image = None
        st.session_state.messages.append({
            "role": "assistant",
            "content": response_data.get("response_text", ""),
            "ts": datetime.now().strftime("%H:%M"),
            "data": response_data,
        })
        st.rerun()

# ── Right column — Session Stats ───────────────────────────────────────────────
with col_info:
    st.markdown("### 📊 Session Stats")
    user_msgs = sum(1 for m in st.session_state.messages if m["role"] == "user")
    agent_msgs = sum(1 for m in st.session_state.messages if m["role"] == "assistant")
    st.metric("Messages sent", user_msgs)
    st.metric("Responses", agent_msgs)
    
    st.markdown("---")
    st.markdown("### 🗂️ Intent Legend")
    legend = [("🔬", "Diagnosis", "#1565c0"), ("📦", "Logistics", "#e65100"), ("🛒", "Product Rec.", "#1b5e20"), ("💬", "General QA", "#4a148c")]
    for icon, label, color in legend:
        st.markdown(f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0;"><div style="width:8px;height:8px;border-radius:50%;background:{color};"></div><span style="font-size:0.82rem;color:#b0bec5;">{icon} {label}</span></div>', unsafe_allow_html=True)
