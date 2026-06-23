"""
frontend/app.py
───────────────
Agro-Mind Streamlit chat UI.
Includes chat history, image upload, product cards, cart actions, and safety
escalation banners.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import uuid
from datetime import datetime
from io import BytesIO
from typing import Optional

import requests
import streamlit as st

# ── Page configuration ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Agro-Mind | Agricultural Support",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── API endpoint ───────────────────────────────────────────────────────────────
API_URL = os.getenv("AGRO_MIND_API_URL", "http://localhost:8000")
GROUP_BUY_MIN_QUANTITY = 10

# ── Quick-question chip sets ────────────────────────────────────────────────────
STARTER_QS = [
    "My tomato leaves have spots, what's wrong?",
    "How do I mix the medicine with water?",
    "How many days after spraying before harvest?",
    "What courier service do you use?",
    "I need an invoice for my order",
]
FOLLOWUP_QS = [
    "How do I mix it with water?",
    "Days before harvest?",
    "Track my order",
]

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* === Google Fonts === */
  @import url('https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap');

  /* === Design tokens — light agricultural, sunlit field readability ===
     OKLCH, neutrals tinted toward the brand green, one confident accent. */
  :root {
    --bg:          oklch(0.967 0.009 150);  /* warm green-white, daylight */
    --surface:     oklch(0.985 0.006 150);  /* faint panel wash */
    --surface-2:   oklch(0.995 0.004 150);  /* elevated: bubbles, cards */
    --border:      oklch(0.45 0.02 150 / 0.18);
    --border-2:    oklch(0.45 0.02 150 / 0.30);
    --text:        oklch(0.27 0.022 155);   /* deep green-charcoal */
    --text-muted:  oklch(0.50 0.018 155);
    --text-faint:  oklch(0.64 0.013 155);
    --accent:      oklch(0.58 0.135 150);   /* one confident agricultural green */
    --accent-ink:  oklch(0.99 0.005 150);   /* near-white on accent fill */
    --accent-soft: oklch(0.58 0.135 150 / 0.12);
    --warn:        oklch(0.58 0.12 70);     /* amber, deepened for light bg */
    --danger:      oklch(0.55 0.17 28);     /* red, deepened for light bg */
    --mono:        'Space Mono', monospace;

    /* Spacing scale — one rhythm: tight within groups, generous between */
    --space-2xs: 4px;
    --space-xs:  8px;
    --space-sm:  12px;
    --space-md:  18px;
    --space-lg:  28px;
    --radius-sm: 8px;
    --radius-md: 12px;
    --measure:   68ch;   /* readable line-length cap for chat */
    --touch:     44px;   /* minimum comfortable touch target */
  }

  /* === Global === */
  html, body, [class*="css"] {
    font-family: 'Hanken Grotesk', sans-serif !important;
  }
  .mono { font-family: var(--mono) !important; }

  /* === Flat surface, no glow === */
  .stApp {
    background: var(--bg);
    color: var(--text);
  }
  .block-container { padding-top: 6rem; }

  /* === Sidebar — quiet panel for diagnostics === */
  [data-testid="stSidebar"] {
    background: oklch(0.94 0.012 150) !important;
    border-right: 1px solid var(--border);
  }
  [data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }

  /* === Header — flat bar, logo mark + connection status === */
  .agro-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 4px 2px 18px 2px;
    margin-bottom: 18px;
    border-bottom: 1px solid var(--border);
  }
  .agro-brand { display: flex; align-items: center; gap: 12px; }
  /* Brand sits in a top-bar column, not .agro-header — size it explicitly so it
     does not inherit Streamlit's oversized default h1. */
  .agro-brand h1 {
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    line-height: 1.1 !important;
    margin: 0 !important;
    padding: 0 !important;
    letter-spacing: -0.3px;
    color: var(--text);
  }
  .agro-mark {
    width: 26px; height: 26px; border-radius: 7px;
    background: var(--accent-soft);
    border: 1.5px solid var(--accent);
    display: grid; place-items: center;
    color: var(--accent); font-size: 0.95rem;
  }
  .agro-header h1 {
    font-size: 1.35rem;
    font-weight: 600;
    color: var(--text);
    margin: 0;
    letter-spacing: -0.2px;
  }
  .agro-status {
    display: inline-flex; align-items: center; gap: 7px;
    font-size: 0.82rem; color: var(--text-muted);
    font-weight: 500;
  }
  .agro-status .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .agro-status.off { color: var(--text-faint); }
  .agro-status.off .dot { background: var(--text-faint); box-shadow: none; }

  /* === Chat messages — quiet surfaces, one accent for the agent ===
     Width is capped by a readable measure (~ch) and centred to its side
     with auto margins. On a phone the bubble breathes to ~92% width;
     on desktop it never sprawls past a comfortable line length. */
  .user-bubble {
    background: var(--surface-2);
    border-radius: 14px 14px 4px 14px;
    padding: var(--space-sm) var(--space-md);
    margin: var(--space-xs) 0 var(--space-xs) auto;
    max-width: min(92%, 56ch);
    width: fit-content;
    color: var(--text);
    font-size: 0.95rem;
    line-height: 1.55;
    border: 1px solid var(--border);
  }

  .agent-bubble {
    background: oklch(0.95 0.03 150);
    border-radius: 14px 14px 14px 4px;
    padding: var(--space-sm) var(--space-md);
    margin: var(--space-xs) auto var(--space-xs) 0;
    max-width: min(94%, var(--measure));
    color: var(--text);
    font-size: 0.95rem;
    line-height: 1.6;
    border: 1px solid var(--border-2);
  }
  /* Generous gap between turns; the agent's product card hugs its bubble. */
  .user-bubble { margin-top: var(--space-md); }

  /* === Product card — flat datasheet === */
  .pcard {
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: var(--radius-md);
    padding: var(--space-md) var(--space-lg);
    margin: var(--space-sm) 0;
    max-width: var(--measure);
    color: var(--text);
  }
  .pcard-name { font-size: 1.15rem; font-weight: 700; color: var(--text); }
  .pcard-meta {
    font-family: var(--mono);
    font-size: 0.78rem;
    color: var(--text-muted);
    margin-top: var(--space-2xs);
  }
  .pcard-rule { height: 1px; background: var(--border); margin: var(--space-md) 0; }
  .pcard-row {
    display: flex; justify-content: space-between; gap: var(--space-sm);
    font-size: 0.88rem; padding: var(--space-2xs) 0;
  }
  .pcard-row .lbl { color: var(--text-muted); }
  .pcard-row .val { color: var(--text); text-align: right; }
  .pcard-row .val.mono { font-family: var(--mono); color: var(--accent); }
  .pcard-prices { display: flex; gap: var(--space-sm); margin-top: var(--space-2xs); }
  .pcard-price {
    flex: 1;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: var(--space-sm);
  }
  .pcard-price .plbl { font-size: 0.72rem; color: var(--text-muted); }
  .pcard-price .pval { font-family: var(--mono); font-size: 1.15rem; font-weight: 700; margin-top: var(--space-2xs); }
  .pcard-price.single .pval { color: var(--text); }
  .pcard-price.group  .pval { color: var(--warn); }

  /* === Safety banner — calm but unmistakable, no perpetual motion === */
  .safety-banner {
    background: oklch(0.95 0.04 28);
    border: 1px solid oklch(0.55 0.17 28 / 0.45);
    border-radius: var(--radius-md);
    padding: var(--space-md) var(--space-lg);
    margin: var(--space-sm) 0;
    max-width: var(--measure);
  }
  .safety-banner h3 { color: var(--danger); margin: 0 0 8px 0; font-size: 1.02rem; font-weight: 600; }
  .safety-banner p { color: oklch(0.38 0.08 28); margin: 4px 0; font-size: 0.9rem; line-height: 1.55; }

  /* === Intent badges — quiet tinted, not solid blocks === */
  .badge-diagnosis { background: rgba(90,160,210,0.16);  color: oklch(0.45 0.11 235); border-color: rgba(90,160,210,0.35); }
  .badge-logistics { background: rgba(217,164,65,0.18);  color: oklch(0.50 0.10 70);  border-color: rgba(217,164,65,0.40); }
  .badge-product   { background: var(--accent-soft);     color: oklch(0.45 0.13 150); border-color: rgba(95,179,92,0.40); }
  .badge-safety    { background: rgba(224,106,90,0.16);   color: oklch(0.48 0.16 28);  border-color: rgba(224,106,90,0.40); }
  .badge-qa        { background: rgba(160,140,200,0.18);  color: oklch(0.45 0.13 300); border-color: rgba(160,140,200,0.38); }

  .intent-badge {
    display: inline-block;
    border-radius: 7px;
    padding: 2px 9px;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.3px;
    margin-bottom: 6px;
    border: 1px solid transparent;
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
  .stTextInput input, .stTextArea textarea,
  [data-testid="stChatInput"] textarea {
    background: var(--surface-2) !important;
    border: 1px solid var(--border-2) !important;
    border-radius: 12px !important;
    color: var(--text) !important;
    padding: 12px 16px !important;
  }
  .stTextInput input:focus, .stTextArea textarea:focus,
  [data-testid="stChatInput"] textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-soft) !important;
  }
  [data-testid="stChatInput"] { background: transparent !important; }
  [data-testid="stChatInput"] textarea { padding-left: 54px !important; }
  [data-testid="stChatInput"] button { color: var(--accent) !important; }

  /* === Image attachment button, direct file picker inside chat input === */
  [data-testid="stFileUploader"] {
    position: relative;
    height: 0 !important;
    min-height: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    overflow: visible !important;
    width: 40px !important;
    z-index: 20;
    background: transparent !important;
    border: 0 !important;
  }
  [data-testid="stFileUploader"] label {
    display: none !important;
  }
  [data-testid="stFileUploaderDropzone"] {
    position: absolute !important;
    left: 10px !important;
    top: 12px !important;
    width: 38px !important;
    height: 38px !important;
    min-height: 38px !important;
    padding: 0 !important;
    overflow: hidden !important;
    border: 0 !important;
    background: transparent !important;
  }
  /* Kill every label, instruction and attached-file row Streamlit renders so
     none of it leaks out beside the 38px icon button. */
  [data-testid="stFileUploaderDropzone"] svg,
  [data-testid="stFileUploaderDropzone"] span,
  [data-testid="stFileUploaderDropzone"] p,
  [data-testid="stFileUploaderDropzone"] small,
  [data-testid="stFileUploaderDropzoneInstructions"],
  [data-testid="stFileUploaderFile"],
  [data-testid="stFileUploaderFileData"],
  [data-testid="stFileUploaderFileName"],
  [data-testid="stFileUploaderDeleteBtn"] {
    display: none !important;
  }
  [data-testid="stFileUploaderDropzone"] button {
    position: absolute !important;
    inset: 0 !important;
    width: 38px !important;
    height: 38px !important;
    min-height: 38px !important;
    padding: 0 !important;
    font-size: 0 !important;
    border-radius: 10px !important;
    border-color: transparent !important;
    background: transparent !important;
    color: var(--text-muted) !important;
    box-shadow: none !important;
  }
  [data-testid="stFileUploaderDropzone"] button::before {
    content: "";
    display: block;
    width: 20px;
    height: 20px;
    margin: auto;
    background: currentColor;
    mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='3' y='3' width='18' height='18' rx='2' ry='2'/%3E%3Ccircle cx='9' cy='9' r='2'/%3E%3Cpath d='m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21'/%3E%3C/svg%3E") center / contain no-repeat;
  }
  [data-testid="stFileUploaderDropzone"] button:hover {
    color: var(--accent) !important;
    background: var(--accent-soft) !important;
    border-color: var(--border-2) !important;
  }

  /* === Buttons — solid quiet green, no gradient, restrained motion ===
     Min height meets a comfortable touch target for one-handed field use. */
  .stButton > button {
    background: var(--surface-2) !important;
    color: var(--text) !important;
    border: 1px solid var(--border-2) !important;
    border-radius: 10px !important;
    font-weight: 500 !important;
    padding: 10px 18px !important;
    min-height: var(--touch) !important;
    transition: border-color .18s ease, background .18s ease !important;
    box-shadow: none !important;
  }
  .stButton > button:hover {
    border-color: var(--accent) !important;
    background: var(--accent-soft) !important;
  }
  /* Primary action (Checkout etc.) */
  .stButton > button[kind="primary"] {
    background: var(--accent) !important;
    color: var(--accent-ink) !important;
    border-color: var(--accent) !important;
    font-weight: 600 !important;
  }
  .stButton > button[kind="primary"]:hover {
    background: #6fc06b !important;
  }

  /* === Suggestion chips (empty-state prompts) === */
  .chip-row .stButton > button {
    text-align: left !important;
    justify-content: flex-start !important;
    border-radius: 12px !important;
    padding: 14px 18px !important;
    color: var(--text) !important;
    font-weight: 400 !important;
  }

  @media (prefers-reduced-motion: reduce) {
    .stButton > button { transition: none !important; }
  }

  /* === Dividers === */
  hr { border-color: var(--border) !important; }

  /* === Metrics === */
  [data-testid="stMetric"] {
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px;
  }
  [data-testid="stMetricValue"] { color: var(--text) !important; }

  /* === File uploader === */
  [data-testid="stFileUploader"] {
    background: var(--surface-2) !important;
    border: 1px dashed var(--border-2) !important;
    border-radius: 12px !important;
  }
  .upload-preview-note {
    font-size: 0.78rem;
    color: var(--text-muted);
    margin-top: 8px;
  }
  .user-upload {
    margin-top: 10px;
  }
  .user-upload img {
    display: block;
    width: min(100%, 360px);
    max-height: 280px;
    object-fit: cover;
    border-radius: 10px;
    border: 1px solid var(--border-2);
    margin-left: auto;
  }
  .user-upload-name {
    font-size: 0.72rem;
    color: var(--text-faint);
    margin-top: 6px;
    text-align: right;
  }

  /* === Spinner === */
  .stSpinner > div { border-top-color: var(--accent) !important; }

  /* === Section headings in side panel === */
  .panel-title {
    display: flex; align-items: center; gap: 8px;
    font-size: 0.95rem; font-weight: 600; color: var(--text);
    margin: 2px 0 10px 0;
  }
  .rail-empty {
    font-size: 0.82rem;
    color: var(--text-muted);
    line-height: 1.5;
    padding: 6px 0;
  }

  /* === Timestamp === */
  .msg-ts {
    font-size: 0.68rem;
    color: var(--text-faint);
    margin-top: 6px;
    text-align: right;
  }
</style>
""", unsafe_allow_html=True)

_rail_empty = '<div class="rail-empty">{}</div>'


# ── Session state initialisation ───────────────────────────────────────────────
if "session_id" not in st.session_state:
    st.session_state.session_id = "guest"
if "messages" not in st.session_state:
    st.session_state.messages = []
if "uploaded_image" not in st.session_state:
    st.session_state.uploaded_image = None
if "tracked_orders" not in st.session_state:
    st.session_state.tracked_orders = []
if "theme" not in st.session_state:
    st.session_state.theme = "light"


# ── Theme tokens — injected per session_state.theme so the whole palette can
#    flip between light and dark at runtime. The static CSS above holds the light
#    values as defaults; this block overrides them (and the few element colours
#    that can't be a plain token) for whichever theme is active. ──────────────────
_THEMES = {
    "light": {
        "bg": "oklch(0.967 0.009 150)", "surface": "oklch(0.985 0.006 150)",
        "surface_2": "oklch(0.995 0.004 150)",
        "border": "oklch(0.45 0.02 150 / 0.18)", "border_2": "oklch(0.45 0.02 150 / 0.30)",
        "text": "oklch(0.27 0.022 155)", "muted": "oklch(0.50 0.018 155)",
        "faint": "oklch(0.64 0.013 155)",
        "accent": "oklch(0.58 0.135 150)", "accent_ink": "oklch(0.99 0.005 150)",
        "accent_soft": "oklch(0.58 0.135 150 / 0.12)",
        "warn": "oklch(0.58 0.12 70)", "danger": "oklch(0.55 0.17 28)",
        "bubble": "oklch(0.95 0.03 150)", "sidebar": "oklch(0.94 0.012 150)",
        "banner": "oklch(0.95 0.04 28)", "banner_text": "oklch(0.38 0.08 28)",
        "b_diag": "oklch(0.45 0.11 235)", "b_log": "oklch(0.50 0.10 70)",
        "b_prod": "oklch(0.45 0.13 150)", "b_saf": "oklch(0.48 0.16 28)",
        "b_qa": "oklch(0.45 0.13 300)",
    },
    "dark": {
        "bg": "#0e110f", "surface": "#15191600", "surface_2": "#181d19",
        "border": "rgba(126,150,132,0.14)", "border_2": "rgba(126,150,132,0.24)",
        "text": "#e7ebe7", "muted": "#8c958d", "faint": "#5c655d",
        "accent": "#5fb35c", "accent_ink": "#0e110f",
        "accent_soft": "rgba(95,179,92,0.12)",
        "warn": "#d9a441", "danger": "#e06a5a",
        "bubble": "#161b17", "sidebar": "#0c0f0d",
        "banner": "#16110f", "banner_text": "#f0d6d1",
        "b_diag": "#9cc6e6", "b_log": "#e0bd76", "b_prod": "#8fce8c",
        "b_saf": "#e6998c", "b_qa": "#bcaee0",
    },
}
_t = _THEMES.get(st.session_state.theme, _THEMES["light"])
st.markdown(f"""
<style>
  :root {{
    --bg: {_t['bg']}; --surface: {_t['surface']}; --surface-2: {_t['surface_2']};
    --border: {_t['border']}; --border-2: {_t['border_2']};
    --text: {_t['text']}; --text-muted: {_t['muted']}; --text-faint: {_t['faint']};
    --accent: {_t['accent']}; --accent-ink: {_t['accent_ink']};
    --accent-soft: {_t['accent_soft']}; --warn: {_t['warn']}; --danger: {_t['danger']};
  }}
  .stApp {{ background: {_t['bg']}; color: {_t['text']}; }}
  .agent-bubble {{ background: {_t['bubble']} !important; }}
  [data-testid="stSidebar"] {{ background: {_t['sidebar']} !important; }}
  .safety-banner {{ background: {_t['banner']} !important; }}
  .safety-banner p {{ color: {_t['banner_text']} !important; }}
  .badge-diagnosis {{ color: {_t['b_diag']} !important; }}
  .badge-logistics {{ color: {_t['b_log']} !important; }}
  .badge-product   {{ color: {_t['b_prod']} !important; }}
  .badge-safety    {{ color: {_t['b_saf']} !important; }}
  .badge-qa        {{ color: {_t['b_qa']} !important; }}
  /* Keep Streamlit's own widget text in step with the active theme. */
  .stCheckbox label, .stCheckbox label p,
  [data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] * {{ color: {_t['text']} !important; }}
  [data-testid="stMetricValue"] {{ color: {_t['text']} !important; }}
  [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {{ color: {_t['muted']} !important; }}
</style>
""", unsafe_allow_html=True)


# ── Helper functions ───────────────────────────────────────────────────────────

def _intent_badge(intent: str) -> str:
    badge_map = {
        "diagnosis": ("badge-diagnosis", "Diagnosis"),
        "logistics": ("badge-logistics", "Logistics"),
        "product_recommendation": ("badge-product", "Product"),
        "safety_escalation": ("badge-safety", "Safety"),
        "general_qa": ("badge-qa", "General QA"),
    }
    cls, label = badge_map.get(intent, ("badge-qa", intent))
    return f'<span class="intent-badge {cls}">{label}</span>'


def _render_uploaded_image(
    image_bytes: Optional[bytes],
    mime_type: Optional[str] = None,
    filename: Optional[str] = None,
) -> str:
    if not image_bytes:
        return ""

    image_mime = mime_type or "image/jpeg"
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    name_html = ""
    if filename:
        name_html = f'<div class="user-upload-name">{html.escape(filename)}</div>'

    return (
        '<div class="user-upload">'
        f'<img src="data:{image_mime};base64,{encoded}" alt="Uploaded crop photo">'
        f'{name_html}'
        '</div>'
    )


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
    <div class="pcard">
      <div class="pcard-name">{name}</div>
      <div class="pcard-meta">Code <b>{pid}</b> · {ptype}</div>
      <div class="pcard-rule"></div>
      <div class="pcard-row"><span class="lbl">Target crops</span><span class="val">{crops}</span></div>
      <div class="pcard-row"><span class="lbl">Active ingredient</span><span class="val">{ingredients}</span></div>
      <div class="pcard-row"><span class="lbl">Dilution</span><span class="val mono">{dosage}</span></div>
      <div class="pcard-rule"></div>
      <div class="pcard-prices">
        <div class="pcard-price single">
          <div class="plbl">Single</div>
          <div class="pval">¥{sp:.0f}</div>
        </div>
        <div class="pcard-price group">
          <div class="plbl">Group · min {GROUP_BUY_MIN_QUANTITY}</div>
          <div class="pval">¥{gp:.0f}</div>
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


@st.cache_data(ttl=10, show_spinner=False)
def _fetch_backend_ok(api_url: str) -> bool:
    try:
        r = requests.get(f"{api_url}/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


@st.cache_data(ttl=5, show_spinner=False)
def _fetch_cart(api_url: str, session_id: str) -> dict:
    try:
        r = requests.get(
            f"{api_url}/cart",
            params={"session_id": session_id},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"items": [], "total_amount": 0}

@st.cache_data(ttl=10)
def _fetch_profile(api_url: str, session_id: str) -> dict:
    try:
        r = requests.get(
            f"{api_url}/profile",
            params={"session_id": session_id},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _update_profile(api_url: str, session_id: str, name: str, location: str, crop_type: str) -> dict:
    try:
        r = requests.post(
            f"{api_url}/profile",
            json={
                "session_id": session_id,
                "name": name,
                "location": location,
                "crop_type": crop_type,
            },
            timeout=10,
        )
        if r.status_code == 200:
            _fetch_profile.clear()
            return r.json()
        return {"error": r.text}
    except Exception as exc:
        return {"error": str(exc)}


@st.cache_data(ttl=10)
def _fetch_history(api_url: str, session_id: str) -> dict:
    try:
        r = requests.get(
            f"{api_url}/history",
            params={"session_id": session_id, "limit": 20},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"messages": []}

@st.cache_data(ttl=15, show_spinner=False)
def _fetch_treatments(api_url: str, session_id: str) -> list:
    try:
        r = requests.get(
            f"{api_url}/treatments",
            params={"session_id": session_id},
            timeout=5,
        )
        r.raise_for_status()
        return r.json().get("treatments", [])
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_catalog_preview(api_url: str, limit: int = 8) -> dict:
    try:
        r = requests.get(
            f"{api_url}/catalog/preview",
            params={"limit": limit},
            timeout=4,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"count": 0, "products": []}


@st.cache_data(ttl=15, show_spinner=False)
def _fetch_profile(api_url: str, session_id: str) -> dict:
    try:
        r = requests.get(
            f"{api_url}/profile",
            params={"session_id": session_id},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def _update_profile(
    api_url: str,
    session_id: str,
    name: str,
    location: str,
    crop_type: str,
) -> dict:
    try:
        r = requests.post(
            f"{api_url}/profile",
            json={
                "session_id": session_id,
                "name": name,
                "location": location,
                "crop_type": crop_type,
            },
            timeout=10,
        )
        r.raise_for_status()
        _fetch_profile.clear()
        return r.json()
    except Exception as exc:
        return {"error": str(exc)}


def _clear_session_caches() -> None:
    _fetch_cart.clear()
    _fetch_treatments.clear()
    _fetch_profile.clear()


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
                        f'<div class="agent-bubble">{display}▌</div>',
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


def _process_turn(
    message: str,
    image_bytes: Optional[bytes],
    order_id: Optional[str],
    image_mime_type: Optional[str] = None,
    image_name: Optional[str] = None,
) -> None:
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
        "image_bytes": image_bytes,
        "image_mime_type": image_mime_type,
        "image_name": image_name,
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
        _fetch_cart.clear()
        return r.json()
    except requests.HTTPError as exc:
        detail = str(exc)
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                detail = response.json().get("detail", detail)
            except Exception:
                detail = response.text or detail
        return {"error": detail}
    except Exception as exc:
        return {"error": str(exc)}


# ── Treatment / Task API helpers ────────────────────────────────────────────────
def _get_treatments() -> list:
    return _fetch_treatments(API_URL, st.session_state.session_id)


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
        _fetch_treatments.clear()
        return r.json()
    except Exception as exc:
        return {"error": str(exc)}


def _get_cart() -> dict:
    return _fetch_cart(API_URL, st.session_state.session_id)


def _checkout() -> dict:
    try:
        r = requests.post(
            f"{API_URL}/checkout",
            json={"session_id": st.session_state.session_id},
            timeout=20,
        )
        r.raise_for_status()
        _fetch_cart.clear()
        return r.json()
    except Exception as exc:
        return {"error": str(exc)}


def _check_backend() -> bool:
    return _fetch_backend_ok(API_URL)


# ── Top bar ─────────────────────────────────────────────────────────────────────
_connected = _check_backend()
_status_cls = "agro-status" if _connected else "agro-status off"
_status_txt = "Connected" if _connected else "Offline"

_tb_brand, _tb_status, _tb_theme, _tb_login, _tb_about = st.columns(
    [4, 1.7, 1.3, 1.3, 1.3], gap="small", vertical_alignment="center"
)
with _tb_brand:
    st.markdown('<div class="agro-brand"><h1>Agro-Mind</h1></div>', unsafe_allow_html=True)
with _tb_status:
    st.markdown(
        f'<div class="{_status_cls}"><span class="dot"></span>{_status_txt}</div>',
        unsafe_allow_html=True,
    )
with _tb_theme:
    _is_dark = st.toggle("Dark", value=(st.session_state.theme == "dark"), key="theme_toggle")
    _new_theme = "dark" if _is_dark else "light"
    if _new_theme != st.session_state.theme:
        st.session_state.theme = _new_theme
        st.rerun()
with _tb_login:
    with st.popover("Sign in", use_container_width=True):
        login_id = st.text_input(
            "Name or Phone",
            value="" if st.session_state.session_id == "guest" else st.session_state.session_id,
            label_visibility="visible",
            placeholder="Enter Name or Phone",
        )
        if st.button("Sign in / switch", use_container_width=True):
            if login_id and login_id.strip():
                if login_id.strip() != st.session_state.session_id:
                    st.session_state.session_id = login_id.strip()
                    st.session_state.messages = []
                    _clear_session_caches()
                    st.rerun()
with _tb_about:
    with st.popover("About", use_container_width=True):
        sid = st.session_state.session_id
        st.markdown(
            f'<div style="font-size:0.78rem;color:var(--text-muted);line-height:1.7;">'
            f'<b style="color:var(--text);">Agro-Mind</b><br>'
            f'Pinduoduo Agricultural Support<br>'
            f'Ships from: Zhejiang, China<br>'
            f'Courier: Postal (邮政)<br>'
            f'Delivery: 3–5 business days<br><br>'
            f'<b>Session ID:</b><br>'
            f'<code class="mono" style="font-size:0.68rem;">{sid[:18]}…</code>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if st.button("New session", use_container_width=True, key="new_session"):
            st.session_state.session_id = str(uuid.uuid4())
            st.session_state.messages = []
            st.session_state.uploaded_image = None
            st.session_state.tracked_orders = []
            _clear_session_caches()
            st.rerun()

st.markdown(
    '<div style="border-bottom:1px solid var(--border);margin:4px 0 18px 0;"></div>',
    unsafe_allow_html=True,
)


# ── Layout — chat + always-visible rail ─────────────────────────────────────────
cart = _get_cart(); cart_items = cart.get("items", [])
treatments = _get_treatments()
tracked = st.session_state.get("tracked_orders") or []

# Rail is always present so cart, treatment plan and shipment stay visible.
col_main, col_rail = st.columns([3, 1.15], gap="large")

with col_main:
    # ── Chat Area Fragment ────────────────────────────────────────────────────────
    @st.fragment
    def chat_interface():
        chat_container = st.container()

        # Mid-conversation follow-up chips sit just above the chat input.
        if st.session_state.messages:
            _fu_cols = st.columns(len(FOLLOWUP_QS))
            for _i, _q in enumerate(FOLLOWUP_QS):
                with _fu_cols[_i]:
                    if st.button(_q, key=f"followup_{_i}", use_container_width=True):
                        _process_turn(_q, None, None)
                        st.rerun(scope="fragment")

        # The uploader's native Browse button is styled as an image icon inside the chat input.
        uploaded_file = st.file_uploader(
            "Upload Image (Optional)",
            type=["jpg", "jpeg", "png", "webp"],
            label_visibility="collapsed",
            key="inline_uploader",
        )
        if uploaded_file:
            preview_bytes = uploaded_file.getvalue()
            st.image(
                preview_bytes,
                caption=uploaded_file.name,
                use_container_width=True,
            )
            st.markdown(
                '<div class="upload-preview-note">This photo will be sent with your next message.</div>',
                unsafe_allow_html=True,
            )

        # 1. Input area
        prompt = st.chat_input("Ask about your crop disease, order status, product dosage…")

        if prompt:
            user_text = prompt
            image_bytes = uploaded_file.getvalue() if uploaded_file else None
            image_mime_type = uploaded_file.type if uploaded_file else None
            image_name = uploaded_file.name if uploaded_file else None

            _process_turn(
                user_text,
                image_bytes,
                st.session_state.get("order_id", "").strip() or None,
                image_mime_type,
                image_name,
            )

        # 2. Render messages
        with chat_container:
            if not st.session_state.messages:
                st.markdown("""
                <div style="text-align:center;padding:48px 20px 20px 20px;">
                  <div style="font-size:1.15rem;color:var(--text-muted);font-weight:400;">
                    Ask about crop disease, order status, or product dosage.
                  </div>
                </div>
                """, unsafe_allow_html=True)

                st.markdown('<div class="chip-row">', unsafe_allow_html=True)
                _, _chip_col, _ = st.columns([1, 4, 1])
                with _chip_col:
                    for _i, _sug in enumerate(STARTER_QS):
                        if st.button(_sug, key=f"sugg_{_i}", use_container_width=True):
                            _process_turn(_sug, None, None)
                            st.rerun(scope="fragment")
                st.markdown('</div>', unsafe_allow_html=True)

            for msg in st.session_state.messages:
                ts = msg.get("ts", "")
                if msg["role"] == "user":
                    content = html.escape(msg.get("content") or "Photo attached")
                    image_html = _render_uploaded_image(
                        msg.get("image_bytes"),
                        msg.get("image_mime_type"),
                        msg.get("image_name"),
                    )
                    st.markdown(
                        f'<div class="user-bubble">{content}{image_html}'
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
                          <h3>Safety Alert — Human Support Activated</h3>
                          <p>{data.get('response_text', '')}</p>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        escalate_html = ""
                        if data.get("escalate_human"):
                            escalate_html = '<div class="escalate-tag">Escalated to human agronomist</div>'

                        st.markdown(
                            f'<div class="agent-bubble">'
                            f'{badge_html}<br>'
                            f'{data.get("response_text", msg["content"])}'
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
                                group_eligible = qty >= GROUP_BUY_MIN_QUANTITY
                                with col_btn1:
                                    if st.button(f"Single ({qty})", key=f"btn_{ts}_{prod_id}", use_container_width=True):
                                        result = _cart_add(prod_id, qty, is_group_buy=False)
                                        if result.get("error"):
                                            st.session_state.messages.append({"role": "assistant", "content": f"⚠️ Error: {result['error']}", "ts": datetime.now().strftime("%H:%M"), "data": {"intent": "logistics"}})
                                        else:
                                            st.session_state.messages.append({"role": "assistant", "content": f"✅ Added **{qty}x {prod_name}** to cart. Total: ¥{result.get('total_amount', 0):.2f}.", "ts": datetime.now().strftime("%H:%M"), "data": {"intent": "logistics"}})
                                        st.rerun() # Full app rerun to update sidebar cart
                                with col_btn2:
                                    if st.button(
                                        f"Group ({qty})",
                                        key=f"btn_grp_{ts}_{prod_id}",
                                        use_container_width=True,
                                        disabled=not group_eligible,
                                        help=f"Group buy starts at {GROUP_BUY_MIN_QUANTITY} units.",
                                    ):
                                        result = _cart_add(prod_id, qty, is_group_buy=True)
                                        if result.get("error"):
                                            st.session_state.messages.append({"role": "assistant", "content": f"⚠️ Error: {result['error']}", "ts": datetime.now().strftime("%H:%M"), "data": {"intent": "logistics"}})
                                        else:
                                            st.session_state.messages.append({"role": "assistant", "content": f"👥 Added **{qty}x {prod_name}** to group purchase. Check cart.", "ts": datetime.now().strftime("%H:%M"), "data": {"intent": "logistics"}})
                                        st.rerun()
                                if not group_eligible:
                                    st.caption(f"Group buy starts at {GROUP_BUY_MIN_QUANTITY} units.")

                            if len(products) > 1:
                                st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
                                col_prev, col_status, col_next = st.columns([1, 2, 1])
                                with col_prev:
                                    if st.button("Prev", key=f"prev_{ts}", use_container_width=True):
                                        st.session_state[idx_key] = (st.session_state[idx_key] - 1) % len(products)
                                        st.rerun(scope="fragment")
                                with col_status:
                                    st.markdown(f"<div style='text-align: center; color: var(--text-muted); font-size: 0.9rem; margin-top: 6px;'>Product {st.session_state[idx_key] + 1} of {len(products)}</div>", unsafe_allow_html=True)
                                with col_next:
                                    if st.button("Next", key=f"next_{ts}", use_container_width=True):
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


# ── Order rail — appears only with cart / treatment / shipment data ─────────────
if col_rail is not None:
    with col_rail:
        rail_cart = _get_cart()
        rail_items = rail_cart.get("items", [])
        rail_treatments = _get_treatments()
        rail_orders = st.session_state.get("tracked_orders") or []

        # 1. Cart ──────────────────────────────────────────────────────────────
        if rail_items:
            st.markdown('<div class="panel-title">Cart</div>', unsafe_allow_html=True)
            for it in rail_items:
                kind = "Group" if it.get("is_group_buy") else "Single"
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
                    f'font-size:0.82rem;padding:5px 0;border-bottom:1px solid var(--border);">'
                    f'<span><span class="mono" style="color:var(--accent);">{it["product_id"]}</span> '
                    f'<span style="color:var(--text-muted);">{kind} × {it["quantity"]}</span></span>'
                    f'<span class="mono" style="color:var(--text);">¥{it.get("line_total", 0):.2f}</span></div>',
                    unsafe_allow_html=True,
                )
            st.markdown(
                f'<div class="mono" style="text-align:right;font-weight:700;margin-top:8px;">'
                f'Total ¥{rail_cart.get("total_amount", 0):.2f}</div>',
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Checkout", use_container_width=True, key="checkout_btn", type="primary"):
                    res = _checkout()
                    if res.get("error"):
                        st.error(f"Checkout failed: {res['error']}")
                    else:
                        orders = res.get("orders", [])
                        for o in orders:
                            st.session_state.tracked_orders.append(o)
                        lines = "\n".join(
                            f"- Order `{o['id']}` — tracking `{o.get('tracking_number')}` "
                            f"({o.get('courier')}, {o.get('estimated_delivery')})"
                            for o in orders
                        )
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": f"Order placed! {len(orders)} order(s) created:\n\n{lines}\n\n"
                                       "Ask about your order status anytime (logistics).",
                            "ts": datetime.now().strftime("%H:%M"),
                            "data": {"intent": "logistics"},
                        })
                        st.rerun()
            with c2:
                if st.button("Clear", use_container_width=True, key="clear_cart_btn"):
                    try:
                        requests.post(
                            f"{API_URL}/cart/clear",
                            json={"session_id": st.session_state.session_id},
                            timeout=10,
                        )
                    except Exception:
                        pass
                    _fetch_cart.clear()
                    st.rerun()

        # 2. Treatment plan ────────────────────────────────────────────────────
        st.markdown('<div class="pcard-rule"></div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">Treatment plan</div>', unsafe_allow_html=True)
        if not rail_treatments:
            st.markdown(_rail_empty.format("No active treatment plan yet."), unsafe_allow_html=True)
        else:
            for tr in rail_treatments:
                tasks = tr.get("daily_tasks", [])
                crop = tr.get("crop") or tr.get("product_id", "")
                total_days = len(tasks)
                done_count = sum(1 for t in tasks if t.get("done"))
                st.markdown(
                    f'<div style="font-size:0.82rem;color:var(--text-muted);margin-bottom:4px;">'
                    f'{crop} · {done_count}/{total_days} days</div>',
                    unsafe_allow_html=True,
                )
                for task in tasks:
                    day = task.get("day", 0)
                    date_str = task.get("date", "")
                    is_done = task.get("done", False)
                    checked = st.checkbox(
                        f"Day {day} · {date_str}",
                        value=is_done,
                        key=f"rail_task_{tr['id']}_{day}",
                    )
                    if checked != is_done:
                        _mark_task_done(tr["id"], day)
                        st.rerun()

        # 3. Shipment ──────────────────────────────────────────────────────────
        st.markdown('<div class="pcard-rule"></div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">Shipment</div>', unsafe_allow_html=True)
        if not rail_orders:
            st.markdown(_rail_empty.format("No shipments yet. Place an order to track it."), unsafe_allow_html=True)
        else:
            for o in rail_orders:
                st.markdown(
                    f'<div style="font-size:0.78rem;padding:6px 0;border-bottom:1px solid var(--border);line-height:1.7;">'
                    f'<span class="mono" style="color:var(--accent);">{o.get("tracking_number","N/A")}</span><br>'
                    f'<span style="color:var(--text-muted);">{o.get("courier","N/A")} · ETA {o.get("estimated_delivery","N/A")}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


# ── Sidebar — customer profile + diagnostics ────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="agro-brand"><h1>Agro-Mind</h1></div>', unsafe_allow_html=True)

    # Customer profile — DB-backed, editable.
    with st.expander("Customer Profile", expanded=True):
        profile = _fetch_profile(API_URL, st.session_state.session_id)

        current_name = profile.get("name", "")
        current_location = profile.get("location", "")
        current_crop = profile.get("crop_type", "")
        last_product = profile.get("last_recommended_product")

        name = st.text_input("Name", value=current_name, key="profile_name")
        location = st.text_input("Location", value=current_location, key="profile_location")
        crop_type = st.text_input("Crop", value=current_crop, key="profile_crop")

        if last_product:
            st.caption(f"Last recommended product: {last_product}")

        if st.button("Save Profile", use_container_width=True, key="save_profile_btn"):
            result = _update_profile(
                API_URL,
                st.session_state.session_id,
                name,
                location,
                crop_type,
            )
            if result.get("error"):
                st.error(result["error"])
            else:
                st.success("Profile saved.")
                st.rerun()

    st.markdown('<div class="pcard-rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Session Stats</div>', unsafe_allow_html=True)

    user_msgs = sum(1 for m in st.session_state.messages if m["role"] == "user")
    agent_msgs = sum(1 for m in st.session_state.messages if m["role"] == "assistant")
    safety_flags = sum(
        1 for m in st.session_state.messages
        if m["role"] == "assistant" and m.get("data", {}).get("safety_risk_detected")
    )

    st.metric("User messages", user_msgs)
    st.metric("Agent responses", agent_msgs)
    if safety_flags:
        st.metric("Safety flags", safety_flags, delta=None)

    st.markdown("---")
    st.markdown('<div class="panel-title">Intent Legend</div>', unsafe_allow_html=True)
    legend = [
        ("Diagnosis", "#1565c0"),
        ("Logistics", "#e65100"),
        ("Product Rec.", "#1b5e20"),
        ("General QA", "#4a148c"),
        ("Safety", "#b71c1c"),
    ]
    for label, color in legend:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0;">'
            f'<div style="width:8px;height:8px;border-radius:50%;background:{color};"></div>'
            f'<span style="font-size:0.82rem;color:var(--text);">{label}</span></div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.markdown('<div class="panel-title">Quick Catalog</div>', unsafe_allow_html=True)
    catalog_data = _fetch_catalog_preview(API_URL, 8)
    products_list = catalog_data.get("products", [])
    if products_list:
        total_products = catalog_data.get("count", len(products_list))
        st.markdown(
            f'<div style="font-size:0.8rem;color:var(--accent);margin-bottom:8px;">'
            f'{total_products} products available</div>',
            unsafe_allow_html=True,
        )
        for prod in products_list:
            st.markdown(
                f'<div style="font-size:0.78rem;padding:4px 0;border-bottom:1px solid var(--border);">'
                f'<span class="mono" style="color:var(--accent);">{prod["product_id"]}</span> '
                f'<span style="color:var(--text);">{prod["product_name"][:30]}</span></div>',
                unsafe_allow_html=True,
            )
        if total_products > len(products_list):
            st.markdown(
                f'<div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px;">+ {total_products-len(products_list)} more…</div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div style="font-size:0.78rem;color:var(--text-muted);">Catalog unavailable (backend offline)</div>',
            unsafe_allow_html=True,
        )
