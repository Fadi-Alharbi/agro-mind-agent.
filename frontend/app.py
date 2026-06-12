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
    <div class="product-card">
      <div class="product-id">📦 {pid}</div>
      <div class="product-name">🌱 {name}</div>
      <span class="product-type-badge">{ptype}</span>
      <div style="margin-top:8px;font-size:0.85rem;color:#546e7a;">
        <strong style="color:#2e7d32;">🌾 Crops:</strong> {crops}<br>
        <strong style="color:#2e7d32;">🧪 Ingredients:</strong> {ingredients}
      </div>
      <div class="price-group">¥{gp:.0f} <span style="font-size:0.8rem;font-weight:400;color:#f4511e;">group</span></div>
      <div class="price-single">Single: ¥{sp:.0f}</div>
      <div class="dosage-info">
        <strong>📋 Dosage:</strong> {dosage}
      </div>
    </div>
    """


def _send_message(message: str, image_bytes: Optional[bytes], order_id: Optional[str]) -> dict:
    """Call the FastAPI /chat endpoint and return the response dict."""
    payload: dict = {
        "session_id": st.session_state.session_id,
        "message": message,
    }
    if image_bytes:
        payload["image_base64"] = base64.b64encode(image_bytes).decode()
    if order_id:
        payload["order_id"] = order_id

    try:
        response = requests.post(f"{API_URL}/chat", json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
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
    except Exception as exc:
        return {
            "intent": "general_qa",
            "safety_risk_detected": False,
            "escalate_human": False,
            "response_text": f"An error occurred: {exc}",
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


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 👤 User Login")
    login_id = st.text_input("Enter Name or Phone", value="" if st.session_state.session_id == "guest" else st.session_state.session_id)
    if st.button("Login / Switch User", use_container_width=True):
        if login_id and login_id.strip():
            if login_id.strip() != st.session_state.session_id:
                st.session_state.session_id = login_id.strip()
                st.session_state.messages = []
                st.rerun()
                
    st.markdown("---")
    
    st.markdown("### 🔌 System Status")
    backend_ok = _check_backend()
    status_color = "#4caf50" if backend_ok else "#ef5350"
    status_label = "Connected" if backend_ok else "Offline"
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;">'
        f'<div style="width:10px;height:10px;border-radius:50%;background:{status_color};'
        f'box-shadow:0 0 8px {status_color};"></div>'
        f'<span style="font-size:0.85rem;">Backend: {status_label}</span></div>',
        unsafe_allow_html=True,
    )

    st.markdown("### 📸 Image Upload")
    st.markdown("<span style='font-size:0.85rem;color:#80cbc4;'>Please use the attachment button in the main chat box to upload an image.</span>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📦 Order Tracking")
    order_id_input = st.text_input(
        "Order ID (optional)", placeholder="e.g. PDD2026060312345", key="order_id"
    )

    st.markdown("---")
    st.markdown("### 🎯 Quick Questions")
    quick_questions = [
        "What courier service do you use?",
        "How do I mix the medicine with water?",
        "My tomato leaves have spots, what's wrong?",
        "How many days after spraying before harvest?",
        "I need an invoice for my order",
    ]
    for qq in quick_questions:
        if st.button(qq, key=f"qq_{hash(qq)}", use_container_width=True):
            st.session_state["quick_input"] = qq
            st.rerun()

    st.markdown("---")
    st.markdown("### ℹ️ About")
    st.markdown(
        """
        <div style="font-size:0.8rem;color:#78909c;line-height:1.6;">
        <b>Agro-Mind AI</b><br>
        Pinduoduo Agricultural Support<br>
        Ships from: Zhejiang, China<br>
        Courier: Postal (邮政)<br>
        Delivery: 3–5 business days<br><br>
        <b>Session ID:</b><br>
        <code style="font-size:0.7rem;">{sid}</code>
        </div>
        """.format(sid=st.session_state.session_id[:18] + "…"),
        unsafe_allow_html=True,
    )

    if st.button("🔄 New Session", use_container_width=True):
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.uploaded_image = None
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

    # Display proactive banner if backend passed active_treatments 
    try:
        import sqlite3
        import json
        conn = sqlite3.connect("db/agromind.db")
        cur = conn.cursor()
        cur.execute("SELECT profile_data FROM customers WHERE id=?", (st.session_state.session_id,))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            profile = json.loads(row[0])
            treatments = profile.get("active_treatments", [])
            if treatments:
                st.info(f"📅 **Active Treatments Reminder:**\n\n" + "\n".join(f"- {t}" for t in treatments))
    except Exception as e:
        pass

    # ── Chat history display ───────────────────────────────────────────────────
    chat_container = st.container()
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

                    # Product cards
                    products = data.get("matched_products", [])
                    if products:
                        for prod in products[:2]:
                            st.markdown(_render_product_card(prod), unsafe_allow_html=True)
                            
                            # Interactive "Add to Cart" Controls
                            prod_id = prod.get('product_id', str(uuid.uuid4())[:6])
                            prod_name = prod.get('product_name', 'Product')
                            
                            # Use container for a clean layout below the card
                            with st.container():
                                col_qty, col_btn1, col_btn2 = st.columns([1, 2, 2])
                                with col_qty:
                                    qty = st.number_input("Qty", min_value=1, max_value=100, value=1, key=f"qty_{ts}_{prod_id}", label_visibility="collapsed")
                                with col_btn1:
                                    if st.button(f"🛒 Add {qty} to Cart", key=f"btn_{ts}_{prod_id}", use_container_width=True):
                                        st.session_state.messages.append({
                                            "role": "assistant",
                                            "content": f"✅ Successfully added **{qty}x {prod_name}** to your cart! You can view it in your order summary.",
                                            "ts": datetime.now().strftime("%H:%M"),
                                            "data": {"intent": "logistics"}
                                        })
                                        st.rerun()
                                with col_btn2:
                                    if st.button("👥 Start Group Purchase", key=f"btn_grp_{ts}_{prod_id}", use_container_width=True):
                                        st.session_state.messages.append({
                                            "role": "assistant",
                                            "content": f"🎉 You've started a group purchase for **{prod_name}**! Share the link with friends to get the discounted price.",
                                            "ts": datetime.now().strftime("%H:%M"),
                                            "data": {"intent": "logistics"}
                                        })
                                        st.rerun()

    # ── Input area ─────────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)

    # Handle quick-input from sidebar buttons
    default_text = st.session_state.pop("quick_input", "")

    with st.form(key="chat_form", clear_on_submit=True):
        user_input = st.text_area(
            "Your message",
            value=default_text,
            placeholder="Ask about your crop disease, order status, product dosage…",
            height=90,
            label_visibility="collapsed",
            key="user_input",
        )
        
        col_img, col_btn = st.columns([8, 2])
        with col_img:
            uploaded_file = st.file_uploader(
                "Upload Image (Optional)",
                type=["jpg", "jpeg", "png", "webp"],
                label_visibility="collapsed",
                key="inline_uploader"
            )
        with col_btn:
            # Add some vertical spacing to align button with uploader
            st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
            submit = st.form_submit_button("Send ➤", use_container_width=True)

    if submit and (user_input.strip() or uploaded_file):
        if uploaded_file:
            st.session_state.uploaded_image = uploaded_file.read()
            
        ts_now = datetime.now().strftime("%H:%M")
        # Record user turn
        st.session_state.messages.append({
            "role": "user",
            "content": user_input.strip(),
            "ts": ts_now,
            "has_image": st.session_state.uploaded_image is not None,
        })

        with st.spinner("🌿 Analyzing your question…"):
            response_data = _send_message(
                message=user_input.strip(),
                image_bytes=st.session_state.uploaded_image,
                order_id=order_id_input.strip() or None,
            )

        # Clear image after sending
        st.session_state.uploaded_image = None

        # Record agent turn
        st.session_state.messages.append({
            "role": "assistant",
            "content": response_data.get("response_text", ""),
            "ts": datetime.now().strftime("%H:%M"),
            "data": response_data,
        })

        st.rerun()


# ── Right column — stats & catalog preview ─────────────────────────────────────
with col_info:
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
        catalog_resp = requests.get(f"{API_URL}/catalog", timeout=5)
        if catalog_resp.status_code == 200:
            catalog_data = catalog_resp.json()
            products_list = catalog_data.get("products", [])
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
    except Exception:
        st.markdown(
            '<div style="font-size:0.78rem;color:#546e7a;">Catalog unavailable (backend offline)</div>',
            unsafe_allow_html=True,
        )
