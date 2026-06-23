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
API_URL = os.getenv("AGRO_MIND_API_URL", "http://127.0.0.1:8000")
GROUP_BUY_MIN_QUANTITY = 10

# ── Persistent session id (URL query param) ─────────────────────────────────────
# We keep only the opaque session_id in the URL query string so a reload (or
# reopening the same link) can re-attach to the still-authenticated DB session.
# This is fully built into Streamlit — no external iframe component — so it never
# fails to load or stalls the page. The id is a random UUID, and the backend
# rejects it after logout, so a leaked URL cannot revive a closed session.
SESSION_QUERY_PARAM = "sid"

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
    --measure:   84ch;   /* readable line-length cap for chat */
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
    min-width: 300px !important;
    max-width: 300px !important;
  }
  [data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }
  [data-testid="stSidebarCollapseButton"],
  [data-testid="collapsedControl"] {
    display: none !important;
  }

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
    display: block;
    background: oklch(0.985 0.018 150);
    border-radius: 14px 14px 4px 14px;
    padding: var(--space-sm) var(--space-md);
    margin: var(--space-sm) 0 var(--space-sm) auto;
    max-width: min(78%, 58ch);
    width: fit-content;
    color: var(--text);
    font-size: 0.95rem;
    line-height: 1.55;
    overflow-wrap: anywhere;
    border: 1px solid oklch(0.58 0.135 150 / 0.28);
  }

  .agent-bubble {
    background: oklch(0.95 0.03 150);
    border-radius: 14px 14px 14px 4px;
    padding: var(--space-sm) var(--space-md);
    margin: var(--space-xs) auto var(--space-xs) 0;
    width: 100%;
    max-width: 100%;
    color: var(--text);
    font-size: 0.95rem;
    line-height: 1.6;
    border: 1px solid var(--border-2);
  }
  .response-loader {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 76px;
    min-height: 24px;
  }
  .response-loader span {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--accent);
    opacity: 0.42;
    animation: responsePulse 1.1s ease-in-out infinite;
  }
  .response-loader span:nth-child(2) { animation-delay: .16s; }
  .response-loader span:nth-child(3) { animation-delay: .32s; }
  @keyframes responsePulse {
    0%, 80%, 100% { transform: translateY(0); opacity: 0.34; }
    40% { transform: translateY(-4px); opacity: 0.95; }
  }
  /* Generous gap between turns; the agent's product card hugs its bubble. */
  .user-bubble { margin-top: var(--space-md); }

  /* === Chat show container: primary working surface === */
  [class*="st-key-chat_show_container"] {
    min-height: 280px;
    max-height: none;
    overflow: visible;
    padding: var(--space-sm) 0;
    margin: 0 0 var(--space-md) 0;
    width: 100%;
    scroll-behavior: smooth;
  }
  [class*="st-key-chat_show_container"] [data-testid="stVerticalBlock"] {
    gap: var(--space-sm);
  }
  [class*="st-key-chat_show_container"] .element-container:has(.user-bubble),
  [class*="st-key-chat_show_container"] .element-container:has(.agent-bubble),
  [class*="st-key-chat_show_container"] .element-container:has(.safety-banner) {
    width: 100%;
  }
  .chat-empty {
    min-height: 210px;
    display: grid;
    place-items: center;
    text-align: center;
    padding: var(--space-lg) var(--space-md);
    color: var(--text-muted);
    font-size: 1.02rem;
    line-height: 1.45;
  }

  /* === Product card — one flat datasheet with purchase controls === */
  [class*="st-key-product_card_"] {
    background: oklch(0.99 0.006 150);
    border: 1px solid var(--border-2);
    border-radius: var(--radius-sm);
    padding: 0;
    margin: var(--space-xs) 0 var(--space-md) 0;
    width: min(100%, 560px);
    max-width: 560px;
    box-sizing: border-box;
    overflow: visible;
    color: var(--text);
  }
  [class*="st-key-product_card_"] *,
  [class*="st-key-product_card_"] *::before,
  [class*="st-key-product_card_"] *::after {
    box-sizing: border-box;
  }
  .pcard {
    background: transparent;
    border: 0;
    border-radius: 0;
    padding: 0;
    margin: 0;
    width: 100%;
    max-width: 100%;
    color: var(--text);
    overflow: visible;
    min-width: 0;
  }
  .pcard-head {
    display: flex;
    justify-content: space-between;
    gap: var(--space-md);
    align-items: flex-start;
    padding: 12px 14px 10px 14px;
    background: oklch(0.965 0.018 150);
    border-bottom: 1px solid var(--border);
    border-radius: calc(var(--radius-sm) - 1px) calc(var(--radius-sm) - 1px) 0 0;
    min-width: 0;
    max-width: 100%;
  }
  .pcard-head > div:first-child {
    min-width: 0;
    max-width: 100%;
  }
  .pcard-name {
    font-size: 0.95rem;
    line-height: 1.25;
    font-weight: 700;
    color: var(--text);
    display: block;
    max-width: 100%;
    overflow: visible;
    overflow-wrap: anywhere;
    word-break: break-word;
    white-space: normal;
  }
  .pcard-meta {
    font-family: var(--mono);
    font-size: 0.72rem;
    color: var(--text-muted);
    margin-top: var(--space-2xs);
    overflow-wrap: anywhere;
  }
  .pcard-code {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-top: 6px;
    color: var(--text-muted);
    font-size: 0.7rem;
  }
  .pcard-code b {
    color: var(--text);
    font-family: var(--mono);
  }
  .pcard-chip {
    flex: 0 0 auto;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 3px 7px;
    font-size: 0.64rem;
    font-weight: 600;
    color: var(--text-muted);
    background: var(--surface);
  }
  .pcard-rule { height: 1px; background: var(--border); margin: 0; }
  .pcard-body {
    padding: 10px 14px;
    min-width: 0;
    max-width: 100%;
    overflow: visible;
  }
  .pcard-detail-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 8px;
    min-width: 0;
    max-width: 100%;
    overflow: visible;
  }
  .pcard-row {
    min-width: 0;
    max-width: 100%;
    overflow: visible;
  }
  .pcard-row .lbl {
    display: block;
    color: var(--text-muted);
    font-size: 0.68rem;
    line-height: 1.2;
    min-width: 0;
    margin-bottom: 4px;
    text-transform: uppercase;
    letter-spacing: 0;
  }
  .pcard-row .val {
    color: var(--text);
    font-size: 0.76rem;
    min-width: 0;
    max-width: 100%;
    text-align: left;
    overflow-wrap: anywhere;
    word-break: break-word;
    hyphens: auto;
    line-height: 1.35;
    display: block;
    overflow: visible;
    white-space: normal;
  }
  .pcard-row .val.mono {
    font-family: var(--mono);
    color: var(--text);
    white-space: normal;
  }
  .pcard-prices {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0;
    border-bottom: 1px solid var(--border);
  }
  .pcard-price {
    min-width: 0;
    padding: 9px 14px;
  }
  .pcard-price.group { border-left: 1px solid var(--border); }
  .pcard-price .plbl { font-size: 0.68rem; color: var(--text-muted); }
  .pcard-price .pval { font-family: var(--mono); font-size: 1rem; font-weight: 700; margin-top: 2px; }
  .pcard-price.single .pval { color: var(--text); }
  .pcard-price.group  .pval { color: var(--warn); }
  .pcard-action-title {
    font-size: 0.74rem;
    color: var(--text-muted);
    font-weight: 600;
    margin: 10px 14px 6px 14px;
  }
  .pcard-buy-note,
  .pcard-position {
    color: var(--text-muted);
    font-size: 0.76rem;
    line-height: 1.45;
    text-align: center;
    margin-top: 6px;
  }
  [class*="st-key-product_card_"] .stNumberInput input {
    min-height: 38px !important;
    text-align: center !important;
    font-family: var(--mono) !important;
  }
  [class*="st-key-product_card_"] .stButton > button {
    min-height: 38px !important;
    padding: 8px 12px !important;
    white-space: normal !important;
    font-weight: 700 !important;
    border-color: var(--accent) !important;
    background: var(--accent) !important;
    color: var(--accent-ink) !important;
  }
  [class*="st-key-product_card_"] .stButton > button:hover {
    background: oklch(0.52 0.13 150) !important;
    border-color: oklch(0.52 0.13 150) !important;
  }
  [class*="st-key-product_card_"] .stButton > button:disabled,
  [class*="st-key-product_card_"] .stButton > button:disabled:hover {
    background: oklch(0.90 0.006 150) !important;
    border-color: var(--border) !important;
    color: var(--text-faint) !important;
  }
  [class*="st-key-product_card_"] [data-testid="column"] {
    min-width: 0 !important;
  }
  [class*="st-key-product_card_"] [data-testid="stHorizontalBlock"] {
    padding: 0 14px 12px 14px !important;
  }

  @media (max-width: 900px) {
    .agent-bubble,
    [class*="st-key-product_card_"],
    [class*="st-key-chat_show_container"] {
      width: 100%;
    }
    .pcard-detail-grid {
      grid-template-columns: 1fr;
      gap: 8px;
    }
  }

  @media (max-width: 640px) {
    .pcard-head {
      display: block;
      padding: 14px;
    }
    .pcard-chip {
      display: inline-flex;
      margin-top: var(--space-xs);
    }
    .pcard-prices {
      grid-template-columns: 1fr;
    }
    .pcard-price.group {
      border-left: 0;
      border-top: 1px solid var(--border);
    }
    .pcard-body {
      padding: 12px 14px;
    }
    [class*="st-key-product_card_"] [data-testid="stHorizontalBlock"] {
      padding: 0 14px 14px 14px !important;
    }
  }

  /* === Safety banner — calm but unmistakable, no perpetual motion === */
  .safety-banner {
    background: oklch(0.95 0.04 28);
    border: 1px solid oklch(0.55 0.17 28 / 0.45);
    border-radius: var(--radius-md);
    padding: var(--space-md) var(--space-lg);
    margin: var(--space-sm) 0;
    width: 100%;
    max-width: 100%;
  }
  .safety-banner h3 { color: var(--danger); margin: 0 0 8px 0; font-size: 1.02rem; font-weight: 600; }
  .safety-banner p { color: oklch(0.38 0.08 28); margin: 4px 0; font-size: 0.9rem; line-height: 1.55; }

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
    background: var(--surface-2) !important;
    border: 1px solid var(--border-2) !important;
    border-radius: 12px !important;
    color: var(--text) !important;
    padding: 12px 16px !important;
  }
  .stTextInput input:focus, .stTextArea textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-soft) !important;
  }

  /* === Composer: real one-line row (image, input, send) === */
  .st-key-composer_row {
    height: 56px !important;
    min-height: 56px !important;
    padding: 0 6px !important;
    border: 1px solid var(--border-2) !important;
    border-radius: 12px !important;
    background: var(--surface-2) !important;
    overflow: hidden !important;
    width: 100% !important;
  }
  .st-key-composer_row [data-testid="stHorizontalBlock"] {
    align-items: center !important;
    gap: 0 !important;
    height: 100% !important;
    min-height: 0 !important;
  }
  .st-key-composer_row:focus-within {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-soft) !important;
  }
  .st-key-composer_row [data-testid="stHorizontalBlock"] [data-testid="column"],
  .st-key-composer_row [data-testid="stHorizontalBlock"] [data-testid="column"] > div,
  .st-key-composer_row [data-testid="stVerticalBlock"],
  .st-key-composer_row [data-testid="stElementContainer"] {
    height: 100% !important;
    min-height: 0 !important;
    display: flex !important;
    align-items: center !important;
  }
  .st-key-composer_row [data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(2) {
    flex: 1 1 auto !important;
    min-width: 0 !important;
  }
  .st-key-composer_row .stTextInput,
  .st-key-composer_row .stTextInput > div,
  .st-key-composer_row .stTextInput [data-baseweb="input"] {
    width: 100% !important;
    height: 100% !important;
    min-height: 0 !important;
    background: transparent !important;
    border: 0 !important;
    box-shadow: none !important;
  }
  .st-key-composer_row .stTextInput input {
    height: 54px !important;
    min-height: 54px !important;
    padding: 0 10px !important;
    background: transparent !important;
    border: 0 !important;
    border-radius: 0 !important;
    color: var(--text) !important;
    font-size: 1rem !important;
    box-shadow: none !important;
  }
  .st-key-composer_row .stTextInput input:focus {
    border: 0 !important;
    box-shadow: none !important;
  }
  .st-key-composer_row .stButton > button {
    width: 42px !important;
    height: 42px !important;
    min-height: 42px !important;
    padding: 0 !important;
    display: grid !important;
    place-items: center !important;
    border: 0 !important;
    border-radius: 10px !important;
    background: transparent !important;
    color: var(--accent) !important;
    box-shadow: none !important;
  }
  .st-key-composer_row .stButton > button:hover {
    background: var(--accent-soft) !important;
  }
  /* Native Material icon (set in Python: st.button(":material/send:")) — no CSS
     glyph hacks; Streamlit renders it, we just size and color it. */
  .st-key-composer_row .stButton > button [data-testid="stIconMaterial"] {
    font-size: 22px !important;
    width: 22px !important;
    height: 22px !important;
    color: var(--accent) !important;
  }

  /* === Image attachment button in composer === */
  [data-testid="stFileUploader"] {
    position: static !important;
    height: 42px !important;
    min-height: 42px !important;
    padding: 0 !important;
    margin: 0 !important;
    overflow: hidden !important;
    width: 42px !important;
    z-index: 20;
    background: transparent !important;
    border: 0 !important;
  }
  [data-testid="stFileUploader"] label {
    display: none !important;
  }
  [data-testid="stFileUploaderDropzone"] {
    position: static !important;
    width: 42px !important;
    height: 42px !important;
    min-height: 42px !important;
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
    position: static !important;
    width: 42px !important;
    height: 42px !important;
    min-height: 42px !important;
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
  /* Button labels follow the button's own color, never the global theme text
     color (prevents invisible same-on-same labels). */
  .stButton > button p,
  .stButton > button span,
  .stButton > button div { color: inherit !important; }

  /* === Suggestion chips (empty-state prompts) === */
  .chip-row .stButton > button {
    text-align: left !important;
    justify-content: flex-start !important;
    border-radius: 12px !important;
    padding: 14px 18px !important;
    color: var(--text) !important;
    font-weight: 400 !important;
  }

  @media (max-width: 760px) {
    [class*="st-key-chat_show_container"] {
      min-height: 50vh;
      max-height: none;
      padding: var(--space-md) var(--space-sm);
      margin-left: calc(var(--space-sm) * -1);
      margin-right: calc(var(--space-sm) * -1);
      border-left: 0;
      border-right: 0;
      border-radius: 0;
    }
    .chat-empty {
      min-height: 170px;
      font-size: 0.96rem;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .stButton > button { transition: none !important; }
    [class*="st-key-chat_show_container"] { scroll-behavior: auto; }
    .response-loader span { animation: none !important; }
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
  .composer-upload-preview {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    max-width: min(100%, 360px);
    margin: 8px 0 4px 54px;
    padding: 7px 9px;
    border: 1px solid var(--border-2);
    border-radius: 10px;
    background: var(--surface-2);
    color: var(--text-muted);
    font-size: 0.78rem;
  }
  .composer-upload-preview img {
    width: 58px;
    height: 44px;
    object-fit: cover;
    border-radius: 7px;
    border: 1px solid var(--border);
  }
  .composer-upload-preview span {
    min-width: 0;
    max-width: 230px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .user-upload {
    margin-top: 10px;
  }
  .user-upload img {
    display: block;
    width: 132px;
    max-width: 100%;
    max-height: 96px;
    object-fit: cover;
    border-radius: 8px;
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

  /* === Header navigation === */
  [class*="st-key-top_nav"] .stButton > button {
    min-height: 38px !important;
    padding: 8px 12px !important;
    border-radius: var(--radius-sm) !important;
    font-size: 0.84rem !important;
    font-weight: 600 !important;
  }

  /* === App footer === */
  .app-footer-rule {
    height: 1px;
    background: var(--border);
    margin: 30px 0 18px 0;
  }
  [class*="st-key-app_footer"] {
    padding-bottom: 18px;
  }
  .app-footer-brand {
    color: var(--text);
    font-size: 1rem;
    line-height: 1.25;
    font-weight: 700;
    margin-bottom: 5px;
  }
  .app-footer-kicker {
    color: var(--text-muted);
    font-size: 0.72rem;
    line-height: 1.2;
    font-weight: 700;
    letter-spacing: 0;
    margin-bottom: 7px;
    text-transform: uppercase;
  }
  .app-footer-sub {
    color: var(--text-muted);
    font-size: 0.78rem;
    line-height: 1.5;
  }
  .app-footer-list {
    color: var(--text-muted);
    font-size: 0.78rem;
    line-height: 1.7;
  }
  .app-footer-list b {
    color: var(--text);
    font-weight: 600;
  }
  .app-footer-session {
    color: var(--text-muted);
    font-size: 0.76rem;
    line-height: 1.6;
    overflow-wrap: anywhere;
  }
  .app-footer-session code {
    color: var(--text-muted);
    font-size: 0.68rem;
  }
  [class*="st-key-app_footer"] button {
    min-height: 38px !important;
    border-radius: var(--radius-sm) !important;
    font-size: 0.84rem !important;
    font-weight: 600 !important;
  }

  /* === Profile main view === */
  .profile-heading {
    max-width: 820px;
    margin: 12px 0 18px 0;
  }
  .profile-heading h2 {
    margin: 0 0 6px 0;
    color: var(--text);
    font-size: 1.45rem;
    line-height: 1.2;
    font-weight: 700;
  }
  .profile-heading p {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.92rem;
    line-height: 1.55;
  }
  /* No decorative card wrapping a form: the two profile sections sit directly on
     the page, separated by the column layout and their titles. Inputs keep their
     own control border, but never inside another box (no nested cards). */
  [class*="st-key-profile_panel"],
  [class*="st-key-memory_panel"] {
    background: transparent;
    border: 0;
    border-radius: 0;
    padding: 0;
  }
  .profile-meta-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--space-sm);
    margin: 0 0 var(--space-md) 0;
  }
  .profile-meta {
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 10px 12px;
    min-height: 64px;
  }
  .profile-meta .lbl {
    display: block;
    color: var(--text-muted);
    font-size: 0.72rem;
    line-height: 1.2;
    margin-bottom: 6px;
  }
  .profile-meta .val {
    color: var(--text);
    font-size: 0.92rem;
    line-height: 1.35;
    overflow-wrap: anywhere;
  }
  .memory-row {
    padding: 9px 0;
    border-bottom: 1px solid var(--border);
    color: var(--text-muted);
    font-size: 0.82rem;
    line-height: 1.55;
  }
  .memory-row:last-child { border-bottom: 0; }
  .memory-role {
    color: var(--text-muted);
    font-family: var(--mono);
    font-size: 0.72rem;
    margin-right: 8px;
    text-transform: uppercase;
  }
  /* No nested cards: a Streamlit form inside a panel must not draw its own box. */
  [data-testid="stForm"] {
    border: 0 !important;
    padding: 0 !important;
    background: transparent !important;
  }
  .history-loaded-note {
    color: var(--text-muted);
    font-size: 0.78rem;
    line-height: 1.35;
    margin: 0 0 var(--space-sm) 0;
    text-align: center;
  }

  @media (max-width: 820px) {
    .profile-meta-grid { grid-template-columns: 1fr; }
    [class*="st-key-profile_panel"],
    [class*="st-key-memory_panel"] { padding: var(--space-md); }
  }
</style>
""", unsafe_allow_html=True)

_rail_empty = '<div class="rail-empty">{}</div>'


# ── Session state initialisation ───────────────────────────────────────────────
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "active_customer" not in st.session_state:
    st.session_state.active_customer = None
if "customer_username" not in st.session_state:
    st.session_state.customer_username = ""
if "messages" not in st.session_state:
    st.session_state.messages = []
if "uploaded_image" not in st.session_state:
    st.session_state.uploaded_image = None
if "tracked_orders" not in st.session_state:
    st.session_state.tracked_orders = []
if "upload_reset_nonce" not in st.session_state:
    st.session_state.upload_reset_nonce = 0
if "message_reset_nonce" not in st.session_state:
    st.session_state.message_reset_nonce = 0
if "active_view" not in st.session_state:
    st.session_state.active_view = "Chat"
if st.session_state.active_view not in {"Chat", "Profile"}:
    st.session_state.active_view = "Chat"
if "history_loaded_count" not in st.session_state:
    st.session_state.history_loaded_count = 0
if "cart_snapshot" not in st.session_state:
    st.session_state.cart_snapshot = {"items": [], "total_amount": 0}
if "show_previous_chats" not in st.session_state:
    st.session_state.show_previous_chats = False
if "show_treatment_plan" not in st.session_state:
    st.session_state.show_treatment_plan = False
if "load_current_history" not in st.session_state:
    st.session_state.load_current_history = False


# ── Single light theme ──────────────────────────────────
#    The light tokens above ARE the theme. No dark override: a sunlit, high-
#    contrast surface is what a farmer reads outdoors, and it keeps the green a
#    single restrained accent for actions, active nav and status, not neon-on-
#    black decoration.




# ── Surgical UI cleanup overrides ──────────────────────────────────────────────
st.markdown("""
<style>
  /* Hide Streamlit demo chrome and reduce the oversized vertical gap. */
  [data-testid="stHeader"],
  [data-testid="stToolbar"],
  [data-testid="stDecoration"],
  #MainMenu,
  footer {
    visibility: hidden !important;
    height: 0 !important;
  }

  .block-container {
    padding-top: 2.2rem !important;
    padding-bottom: 1.2rem !important;
    max-width: none !important;
    width: 100% !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
  }

  /* Sidebar should feel like a control panel, not a second dashboard. */
  [data-testid="stSidebar"] .block-container {
    padding-top: 1.2rem !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
  }

  /* Keep the uploader as a compact image icon beside the message field. */
  [data-testid="stFileUploader"] {
    position: static !important;
    height: 42px !important;
    min-height: 42px !important;
    width: 42px !important;
    overflow: hidden !important;
    margin: 0 !important;
    padding: 0 !important;
    border: 0 !important;
    background: transparent !important;
    z-index: 20;
  }
  [data-testid="stFileUploader"] label {
    display: none !important;
  }
  [data-testid="stFileUploaderDropzone"] {
    position: static !important;
    width: 42px !important;
    height: 42px !important;
    min-height: 42px !important;
    padding: 0 !important;
    overflow: hidden !important;
    border: 0 !important;
    background: transparent !important;
  }
  [data-testid="stFileUploaderDropzone"] svg,
  [data-testid="stFileUploaderDropzone"] span,
  [data-testid="stFileUploaderFile"],
  [data-testid="stFileUploaderFileData"],
  [data-testid="stFileUploaderFileName"],
  [data-testid="stFileUploaderDeleteBtn"] {
    display: none !important;
  }
  [data-testid="stFileUploaderDropzone"] button {
    position: static !important;
    width: 42px !important;
    height: 42px !important;
    min-height: 42px !important;
    padding: 0 !important;
    font-size: 0 !important;
    border: 1px solid transparent !important;
    border-radius: 10px !important;
    color: var(--text-muted) !important;
    background: transparent !important;
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
  [data-testid="stFileUploaderDropzone"] p,
  [data-testid="stFileUploaderDropzone"] small,
  [data-testid="stFileUploaderDropzoneInstructions"] {
    display: none !important;
  }

  /* Main empty state: tighter and calmer. */
  .chip-row .stButton > button {
    min-height: 40px !important;
    padding: 10px 14px !important;
  }

  /* Smaller metrics if any remain. */
  [data-testid="stMetric"] {
    padding: 10px !important;
  }
</style>
""", unsafe_allow_html=True)

# ── Helper functions ───────────────────────────────────────────────────────────

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


def _render_composer_upload_preview(
    image_bytes: bytes,
    mime_type: Optional[str],
    filename: str,
) -> str:
    image_mime = mime_type or "image/jpeg"
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return (
        '<div class="composer-upload-preview">'
        f'<img src="data:{image_mime};base64,{encoded}" alt="">'
        f'<span>{html.escape(filename)}</span>'
        '</div>'
    )


def _render_response_loader() -> str:
    return (
        '<div class="agent-bubble" aria-live="polite" aria-label="Assistant response loading">'
        '<div class="response-loader">'
        '<span></span><span></span><span></span>'
        '</div>'
        '</div>'
    )


def _clean_product_value(value: object, max_chars: int | None = 220) -> str:
    text = " ".join(str(value or "").split())
    if max_chars and len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _price_text(value: object) -> str:
    try:
        return f"¥{float(value):.0f}"
    except (TypeError, ValueError):
        return "N/A"


def _product_row(label: str, value: object, *, mono: bool = False, max_chars: int | None = None) -> str:
    clean = _clean_product_value(value, max_chars=max_chars)
    if not clean:
        return ""
    val_cls = "val mono" if mono else "val"
    return (
        '<div class="pcard-row">'
        f'<span class="lbl">{html.escape(label)}</span>'
        f'<span class="{val_cls}">{html.escape(clean)}</span>'
        '</div>'
    )


def _render_product_card(product: dict) -> str:
    pid = _clean_product_value(product.get("product_id", ""), max_chars=24)
    local_name = _clean_product_value(product.get("product_name", ""), max_chars=140)
    english_name = _clean_product_value(product.get("english_name", ""), max_chars=140)
    name = english_name or local_name or "Unknown product"
    secondary_name = local_name if local_name and local_name != name else ""
    ptype = _clean_product_value(product.get("product_type", ""), max_chars=28)
    dosage = product.get("water_ratio") or product.get("how_to_use", "")

    rows = "".join([
        _product_row("Ingredient", product.get("main_ingredients")),
        _product_row("Dilution", dosage, mono=True),
        _product_row("Crops", product.get("crops")),
    ])

    secondary_html = (
        f'<div class="pcard-meta">{html.escape(secondary_name)}</div>'
        if secondary_name
        else ""
    )
    type_html = f" · {html.escape(ptype)}" if ptype else ""

    return f"""
    <div class="pcard">
      <div class="pcard-head">
        <div>
          <div class="pcard-name">{html.escape(name)}</div>
          {secondary_html}
          <div class="pcard-code"><b>{html.escape(pid)}</b><span>{type_html.lstrip(" · ")}</span></div>
        </div>
        <div class="pcard-chip">Catalog match</div>
      </div>
      <div class="pcard-prices">
        <div class="pcard-price single">
          <div class="plbl">Single</div>
          <div class="pval">{_price_text(product.get("single_price"))}</div>
        </div>
        <div class="pcard-price group">
          <div class="plbl">Group · min {GROUP_BUY_MIN_QUANTITY}</div>
          <div class="pval">{_price_text(product.get("group_price"))}</div>
        </div>
      </div>
      <div class="pcard-body">
        <div class="pcard-detail-grid">
          {rows}
        </div>
      </div>
    </div>
    """


def _send_message(message: str, image_bytes: Optional[bytes], order_id: Optional[str]) -> dict:
    """Call the FastAPI /chat endpoint (non-streaming fallback)."""
    if not _is_logged_in():
        return _error_response("Sign in before sending messages.")
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
            "Can't reach the backend server. "
            "Make sure the FastAPI server is running:<br>"
            "<code class=\"mono\">uvicorn main:app --reload --port 8000</code>"
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
def _fetch_history(
    api_url: str,
    session_id: str,
    include_images: bool = False,
    all_sessions: bool = False,
) -> dict:
    try:
        r = requests.get(
            f"{api_url}/history",
            params={
                "session_id": session_id,
                "limit": 30,
                "include_images": include_images,
                "all_sessions": all_sessions,
            },
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"messages": []}


@st.cache_data(ttl=10, show_spinner=False)
def _fetch_chat_sessions(api_url: str, session_id: str) -> dict:
    try:
        r = requests.get(
            f"{api_url}/sessions",
            params={"session_id": session_id},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"sessions": []}


def _history_timestamp(raw_ts: Optional[str]) -> str:
    if not raw_ts:
        return ""
    try:
        dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        if dt.date() == datetime.now().date():
            return dt.strftime("%H:%M")
        return dt.strftime("%b %d %H:%M")
    except Exception:
        return ""


def _chat_list_timestamp(raw_ts: Optional[str]) -> str:
    if not raw_ts:
        return ""
    try:
        dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        now = datetime.now()
        if dt.date() == now.date():
            return dt.strftime("%H:%M")
        if dt.year == now.year:
            return dt.strftime("%b %d")
        return dt.strftime("%b %d, %Y")
    except Exception:
        return ""


def _decode_history_attachment(message: dict) -> tuple[Optional[bytes], Optional[str], Optional[str]]:
    attachments = message.get("attachments") or []
    if not attachments:
        return None, None, None
    attachment = attachments[0] or {}
    image_b64 = attachment.get("data_base64")
    if not image_b64:
        return None, None, None
    try:
        return (
            base64.b64decode(image_b64),
            attachment.get("mime_type") or "image/jpeg",
            "Stored crop photo",
        )
    except Exception:
        return None, None, None


def _history_message_to_ui(message: dict) -> dict:
    role = "assistant" if message.get("role") == "assistant" else "user"
    content = message.get("content") or message.get("text") or ""
    ts = _history_timestamp(message.get("created_at") or message.get("ts"))

    if role == "user":
        image_bytes, image_mime_type, image_name = _decode_history_attachment(message)
        return {
            "role": "user",
            "content": content,
            "ts": ts,
            "has_image": bool(message.get("has_image")),
            "image_bytes": image_bytes,
            "image_mime_type": image_mime_type,
            "image_name": image_name,
        }

    intent = message.get("intent") or "general_qa"
    matched_products = message.get("matched_products") or []
    recommended_product_id = message.get("recommended_product_id")
    return {
        "role": "assistant",
        "content": content,
        "ts": ts,
        "data": {
            "intent": intent,
            "safety_risk_detected": False,
            "escalate_human": False,
            "response_text": content,
            "recommended_product_id": recommended_product_id,
            "group_purchase_triggered": bool(recommended_product_id),
            "matched_products": matched_products,
        },
    }


def _load_stored_chat_history() -> None:
    """Hydrate the visible chat from DB history after sign-in/session restore."""
    if (
        not _is_logged_in()
        or not st.session_state.get("load_current_history")
        or st.session_state.get("messages")
        or st.session_state.get("pending_turn")
    ):
        return

    history = _fetch_history(API_URL, st.session_state.session_id, include_images=True)
    rows = history.get("messages", []) if isinstance(history, dict) else []
    if not rows:
        return

    st.session_state.messages = [_history_message_to_ui(row) for row in rows]
    st.session_state.history_loaded_count = len(st.session_state.messages)
    st.session_state.load_current_history = False

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


def _login_customer(api_url: str, username: str, password: str) -> dict:
    try:
        r = requests.post(
            f"{api_url}/login",
            json={
                "username": username,
                "password": password,
                "session_id": st.session_state.session_id,
            },
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as exc:
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                return {"error": response.json().get("detail", response.text)}
            except Exception:
                return {"error": response.text or str(exc)}
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": str(exc)}


def _logout_customer(api_url: str) -> dict:
    try:
        r = requests.post(
            f"{api_url}/logout",
            json={"session_id": st.session_state.session_id},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {
            "logged_in": False,
            "session_id": str(uuid.uuid4()),
            "session_changed": True,
        }


def _start_new_customer_session(api_url: str) -> dict:
    try:
        r = requests.post(
            f"{api_url}/session/new",
            json={"session_id": st.session_state.session_id},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as exc:
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                return {"error": response.json().get("detail", response.text)}
            except Exception:
                return {"error": response.text or str(exc)}
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": str(exc)}


def _switch_chat_session(api_url: str, session_id: str) -> dict:
    if not session_id or session_id == st.session_state.get("session_id"):
        return {}
    payload = _resume_session(api_url, session_id)
    if payload:
        _apply_logged_in_session(payload)
        st.session_state.load_current_history = True
        return payload
    return {"error": "Could not open that chat. Please sign in again."}


def _clear_session_caches() -> None:
    _fetch_cart.clear()
    _fetch_history.clear()
    _fetch_chat_sessions.clear()
    _fetch_treatments.clear()
    _fetch_profile.clear()


def _read_saved_session() -> Optional[str]:
    """Read the persisted session id from the URL query string."""
    try:
        value = st.query_params.get(SESSION_QUERY_PARAM)
    except Exception:
        return None
    return value or None


def _persist_saved_session(session_id: str) -> None:
    """Persist the active session id in the URL so a reload stays signed in."""
    if not session_id:
        return
    try:
        if st.query_params.get(SESSION_QUERY_PARAM) != session_id:
            st.query_params[SESSION_QUERY_PARAM] = session_id
    except Exception:
        pass


def _clear_saved_session() -> None:
    """Drop the persisted session id from the URL (on logout or when it goes stale)."""
    try:
        if SESSION_QUERY_PARAM in st.query_params:
            del st.query_params[SESSION_QUERY_PARAM]
    except Exception:
        pass


def _resume_session(api_url: str, session_id: str) -> dict:
    """Ask the backend whether this session_id is still authenticated.

    Returns the login payload on success, or {} when the session is no longer
    valid (logged out / expired) so the caller can drop the stale cookie."""
    try:
        r = requests.get(
            f"{api_url}/session",
            params={"session_id": session_id},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _is_logged_in() -> bool:
    return bool(st.session_state.get("logged_in") and st.session_state.get("session_id"))


def _reset_local_conversation() -> None:
    st.session_state.messages = []
    st.session_state.history_loaded_count = 0
    st.session_state.uploaded_image = None
    st.session_state.upload_reset_nonce += 1
    st.session_state.message_reset_nonce += 1
    st.session_state.tracked_orders = []
    st.session_state.cart_snapshot = {"items": [], "total_amount": 0}
    st.session_state.show_previous_chats = False
    st.session_state.show_treatment_plan = False
    st.session_state.load_current_history = False
    st.session_state.pop("pending_turn", None)
    for key in list(st.session_state.keys()):
        if str(key).startswith("prod_idx_"):
            del st.session_state[key]


def _apply_logged_in_session(payload: dict) -> None:
    st.session_state.session_id = payload["session_id"]
    st.session_state.logged_in = True
    st.session_state.active_customer = {
        "id": payload.get("id"),
        "external_id": payload.get("external_id"),
        "username": payload.get("username") or "",
        "name": payload.get("name") or "",
        "location": payload.get("location") or "",
        "crop_type": payload.get("crop_type") or "",
    }
    st.session_state.customer_username = (
        payload.get("username") or payload.get("name") or ""
    )
    _reset_local_conversation()
    _clear_session_caches()
    # NOTE: the cookie is NOT written here. This helper is always followed by
    # st.rerun(), and a cookie write right before a rerun never reaches the
    # browser (the JS component is torn down first). The actual write happens in
    # the session-cookie sync block near the top of the script, which runs in a
    # stable render cycle.


def _apply_logged_out_session(payload: Optional[dict] = None) -> None:
    payload = payload or {}
    st.session_state.session_id = payload.get("session_id") or str(uuid.uuid4())
    st.session_state.logged_in = False
    st.session_state.active_customer = None
    st.session_state.customer_username = ""
    _reset_local_conversation()
    _clear_session_caches()
    # Forget the persisted session so the next reload is anonymous. query_params
    # writes are reliable (no iframe), so this removal takes effect immediately;
    # resetting the restore guard keeps the sync block consistent.
    st.session_state.pop("_session_restore_tried", None)
    _clear_saved_session()


def _stream_turn(pending: dict) -> dict:
    """Call /chat_stream and display tokens live as they arrive.

    Shows each token inside the agent-bubble CSS div as it comes in.
    Returns the final response_data dict (same shape as /chat response).
    """
    if not _is_logged_in():
        return _error_response("Sign in before sending messages.")
    payload: dict = {"session_id": st.session_state.session_id, "message": pending["message"]}
    if pending.get("image_bytes"):
        payload["image_base64"] = base64.b64encode(pending["image_bytes"]).decode()
    if pending.get("order_id"):
        payload["order_id"] = pending["order_id"]

    full_text = ""
    response_data: dict = {}
    placeholder = st.empty()
    placeholder.markdown(_render_response_loader(), unsafe_allow_html=True)

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
    if not _is_logged_in():
        return
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
    if not _is_logged_in():
        return {"error": "Sign in before adding products to the cart."}
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
        cart = r.json()
        st.session_state.cart_snapshot = cart
        return cart
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
    if not _is_logged_in():
        return []
    return _fetch_treatments(API_URL, st.session_state.session_id)


def _mark_task_done(treatment_id: int, day: int) -> dict:
    if not _is_logged_in():
        return {"error": "Sign in before updating treatment tasks."}
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
    if not _is_logged_in():
        return {"items": [], "total_amount": 0}
    return _fetch_cart(API_URL, st.session_state.session_id)


def _checkout(create_treatment_plan: bool = False) -> dict:
    if not _is_logged_in():
        return {"error": "Sign in before checkout."}
    try:
        r = requests.post(
            f"{API_URL}/checkout",
            json={
                "session_id": st.session_state.session_id,
                "create_treatment_plan": create_treatment_plan,
            },
            timeout=20,
        )
        r.raise_for_status()
        _fetch_cart.clear()
        _fetch_treatments.clear()
        return r.json()
    except Exception as exc:
        return {"error": str(exc)}


def _check_backend() -> bool:
    return _fetch_backend_ok(API_URL)


def _render_app_footer(status_text: str) -> None:
    st.markdown('<div class="app-footer-rule"></div>', unsafe_allow_html=True)
    with st.container(key="app_footer"):
        user_label = "Not signed in"
        if _is_logged_in():
            active_customer = st.session_state.get("active_customer") or {}
            user_label = active_customer.get("username") or active_customer.get("name") or "Signed in"

        _ft_brand, _ft_shipping, _ft_account, _ft_action = st.columns(
            [1.7, 1.8, 1.6, 1.0], gap="medium", vertical_alignment="top"
        )
        with _ft_brand:
            st.markdown(
                '<div class="app-footer-kicker">About</div>'
                '<div class="app-footer-brand">Agro-Mind</div>'
                '<div class="app-footer-sub">Pinduoduo Agricultural Support for crop diagnosis, dosage guidance, cart, and order tracking.</div>',
                unsafe_allow_html=True,
            )
        with _ft_shipping:
            st.markdown(
                '<div class="app-footer-kicker">Shipping</div>'
                '<div class="app-footer-list">'
                '<b>Ships from:</b> Zhejiang, China<br>'
                '<b>Courier:</b> Postal (邮政)<br>'
                '<b>Delivery:</b> 3-5 business days'
                '</div>',
                unsafe_allow_html=True,
            )
        with _ft_account:
            st.markdown(
                f'<div class="app-footer-kicker">Account</div>'
                f'<div class="app-footer-session">'
                f'<b>User:</b> {html.escape(user_label)}<br>'
                f'<b>Status:</b> {html.escape(status_text)}'
                f'</div>',
                unsafe_allow_html=True,
            )
        # with _ft_action:
        #     st.markdown('<div class="app-footer-kicker">Actions</div>', unsafe_allow_html=True)
        #     if st.button("New session", use_container_width=True, key="footer_new_session"):
        #         if _is_logged_in():
        #             new_session_result = _start_new_customer_session(API_URL)
        #             if new_session_result.get("error"):
        #                 st.error(new_session_result["error"])
        #             else:
        #                 _apply_logged_in_session(new_session_result)
        #                 st.rerun()
        #         else:
        #             _apply_logged_out_session({"session_id": str(uuid.uuid4())})
        #             st.rerun()


def _render_profile_view() -> None:
    st.markdown(
        '<div class="profile-heading">'
        '<h2>Profile</h2>'
        '</div>',
        unsafe_allow_html=True,
    )

    if not _is_logged_in():
        st.info("Sign in from Account to load and save a database-backed profile.")
        return

    profile = _fetch_profile(API_URL, st.session_state.session_id)
    current_name = profile.get("name", "")
    current_location = profile.get("location", "")
    current_crop = profile.get("crop_type", "")
    last_product = profile.get("last_recommended_product")
    active_customer = st.session_state.get("active_customer") or {}
    signed_in_as = active_customer.get("username") or active_customer.get("name") or "Signed in"

    st.markdown(
        '<div class="profile-meta-grid">'
        f'<div class="profile-meta"><span class="lbl">Signed in</span>'
        f'<span class="val">{html.escape(signed_in_as)}</span></div>'
        f'<div class="profile-meta"><span class="lbl">Crop</span>'
        f'<span class="val">{html.escape(current_crop or "Not set")}</span></div>'
        f'<div class="profile-meta"><span class="lbl">Location</span>'
        f'<span class="val">{html.escape(current_location or "Not set")}</span></div>'
        '</div>',
        unsafe_allow_html=True,
    )

    profile_col, memory_col = st.columns([1.2, 1], gap="large")

    with profile_col:
        with st.container(key="profile_panel"):
            st.markdown('<div class="panel-title">Customer Profile</div>', unsafe_allow_html=True)
            with st.form("customer_profile_form", clear_on_submit=False):
                name = st.text_input("Name", value=current_name, key="profile_name")
                location = st.text_input("Location", value=current_location, key="profile_location")
                crop_type = st.text_input("Crop", value=current_crop, key="profile_crop")
                if last_product:
                    st.caption(f"Last recommended product: {last_product}")
                save_profile = st.form_submit_button("Save Profile", use_container_width=True)

            if save_profile:
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
                    active_customer.update({
                        "name": name,
                        "location": location,
                        "crop_type": crop_type,
                    })
                    st.session_state.active_customer = active_customer
                    st.success("Profile saved.")

    with memory_col:
        with st.container(key="memory_panel"):
            st.markdown('<div class="panel-title">Recent Memory</div>', unsafe_allow_html=True)
            history = _fetch_history(
                API_URL,
                st.session_state.session_id,
                all_sessions=True,
            )
            messages = history.get("messages", []) if isinstance(history, dict) else []

            if not messages:
                st.markdown(_rail_empty.format("No stored customer memory yet."), unsafe_allow_html=True)
            else:
                st.caption(f"Stored messages: {len(messages)}")
                for msg in messages[-6:]:
                    role = html.escape(str(msg.get("role", "")) or "entry")
                    content = msg.get("content") or msg.get("text") or ""
                    st.markdown(
                        '<div class="memory-row">'
                        f'<span class="memory-role">{role}</span>'
                        f'{html.escape(str(content)[:180])}'
                        '</div>',
                        unsafe_allow_html=True,
                    )


# ── Session sync — restore on reload, persist while signed in ───────────────────
# The persisted session id lives in the URL query string (st.query_params), which
# is built into Streamlit and available immediately on the first run — no iframe
# component to load, so there is no stall and no flash before restore.
if not st.session_state.get("logged_in"):
    # Fresh session_state (reload / reopened link) but the URL may still point at
    # a live DB session — re-attach so the user stays signed in until logout. The
    # per-session_id guard stops a stale id from retrying the lookup every rerun.
    _saved_sid = _read_saved_session()
    if _saved_sid and st.session_state.get("_session_restore_tried") != _saved_sid:
        st.session_state["_session_restore_tried"] = _saved_sid
        _restored = _resume_session(API_URL, _saved_sid)
        if _restored.get("session_id") and not _restored.get("error"):
            _apply_logged_in_session(_restored)
            st.rerun()
        else:
            # Stale id (logged out / expired) — drop it from the URL.
            _clear_saved_session()
elif _read_saved_session() != st.session_state.session_id:
    # Signed in but the URL id is missing/outdated — write the active one.
    _persist_saved_session(st.session_state.session_id)


# ── Top bar ─────────────────────────────────────────────────────────────────────
_connected = _check_backend()
_status_cls = "agro-status" if _connected else "agro-status off"
_status_txt = "Connected" if _connected else "Offline"

_tb_brand, _tb_status, _tb_nav, _tb_login = st.columns(
    [3.2, 1.35, 1.8, 1.25], gap="small", vertical_alignment="center"
)
with _tb_brand:
    st.markdown(
        '<div class="agro-brand"><span class="agro-mark">A</span><h1>Agro-Mind</h1></div>',
        unsafe_allow_html=True,
    )
with _tb_status:
    st.markdown(
        f'<div class="{_status_cls}"><span class="dot"></span>{_status_txt}</div>',
        unsafe_allow_html=True,
    )
with _tb_nav:
    with st.container(key="top_nav"):
        nav_chat, nav_profile = st.columns(2, gap="small")
        with nav_chat:
            if st.button(
                "Chat",
                key="nav_chat",
                use_container_width=True,
                type="primary" if st.session_state.active_view == "Chat" else "secondary",
            ):
                st.session_state.active_view = "Chat"
                st.rerun()
        with nav_profile:
            if st.button(
                "Profile",
                key="nav_profile",
                use_container_width=True,
                type="primary" if st.session_state.active_view == "Profile" else "secondary",
            ):
                st.session_state.active_view = "Profile"
                st.rerun()
with _tb_login:
    if _is_logged_in():
        if st.button("Logout", use_container_width=True):
            logout_result = _logout_customer(API_URL)
            _apply_logged_out_session(logout_result)
            st.rerun()
    else:
        with st.popover("Sign in", use_container_width=True):
            login_id = st.text_input(
                "Name or Phone",
                value=st.session_state.get("customer_username", ""),
                label_visibility="visible",
                placeholder="Enter Name or Phone",
            )
            login_password = st.text_input(
                "Password",
                type="password",
                label_visibility="visible",
                placeholder="Enter password",
            )
            st.caption("First sign-in creates the account. After that, use the same password.")
            if st.button("Sign in / create", use_container_width=True):
                if login_id and login_id.strip() and login_password:
                    login_result = _login_customer(
                        API_URL,
                        login_id.strip(),
                        login_password,
                    )
                    if login_result.get("error"):
                        st.error(login_result["error"])
                    else:
                        _apply_logged_in_session(login_result)
                        st.rerun()
                else:
                    st.warning("Enter a name or phone and password.")

st.markdown(
    '<div style="border-bottom:1px solid var(--border);margin:4px 0 18px 0;"></div>',
    unsafe_allow_html=True,
)

if st.session_state.active_view == "Profile":
    _render_profile_view()
    _render_app_footer(_status_txt)
    st.stop()

_profile_status = st.session_state.get("active_customer") or {}
if _is_logged_in() and _profile_status:
    st.caption(
        f"Profile loaded · Crop: {_profile_status.get('crop_type') or '—'} · "
        f"Location: {_profile_status.get('location') or '—'}"
    )
else:
    st.caption("Sign in to load a database-backed customer profile.")

_load_stored_chat_history()

# ── Layout — chat stays full-width; operational panels live in the sidebar ─────
col_main = st.container()

with col_main:
    # ── Chat Area Fragment ────────────────────────────────────────────────────────
    @st.fragment
    def chat_interface():
        chat_container = st.container(key="chat_show_container")

        # Mid-conversation follow-up chips sit just above the chat input.
        if st.session_state.messages:
            _fu_cols = st.columns(len(FOLLOWUP_QS))
            for _i, _q in enumerate(FOLLOWUP_QS):
                with _fu_cols[_i]:
                    if st.button(
                        _q,
                        key=f"followup_{_i}",
                        use_container_width=True,
                        disabled=not _is_logged_in(),
                    ):
                        _process_turn(_q, None, None)
                        st.rerun(scope="fragment")

        with st.container(key="composer_row"):
            attach_col, input_col, send_col = st.columns(
                [0.06, 0.88, 0.06],
                gap="small",
                vertical_alignment="center",
            )
            with attach_col:
                uploaded_file = st.file_uploader(
                    "Attach crop image",
                    type=["jpg", "jpeg", "png", "webp"],
                    label_visibility="collapsed",
                    key=f"inline_uploader_{st.session_state.upload_reset_nonce}",
                    disabled=not _is_logged_in(),
                )
            with input_col:
                composer_text = st.text_input(
                    "Message",
                    placeholder="Ask about your crop disease, order status, product dosage...",
                    label_visibility="collapsed",
                    key=f"composer_message_{st.session_state.message_reset_nonce}",
                    disabled=not _is_logged_in(),
                )
            with send_col:
                send_clicked = st.button(
                    ":material/send:",
                    key="composer_send",
                    use_container_width=True,
                    disabled=not _is_logged_in(),
                )
        upload_preview_slot = st.empty()

        if send_clicked:
            user_text = (composer_text or "").strip()
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
            st.session_state.message_reset_nonce += 1
            if uploaded_file:
                st.session_state.upload_reset_nonce += 1
            st.rerun(scope="fragment")

        if uploaded_file and not send_clicked:
            preview_bytes = uploaded_file.getvalue()
            upload_preview_slot.markdown(
                _render_composer_upload_preview(
                    preview_bytes,
                    uploaded_file.type,
                    uploaded_file.name,
                ),
                unsafe_allow_html=True,
            )

        # 2. Render messages
        with chat_container:
            if st.session_state.get("history_loaded_count", 0) > 0:
                count = st.session_state.history_loaded_count
                word = "message" if count == 1 else "messages"
                st.markdown(
                    f'<div class="history-loaded-note">Loaded {count} previous {word}.</div>',
                    unsafe_allow_html=True,
                )

            if not st.session_state.messages:
                if not _is_logged_in():
                    st.markdown("""
                    <div class="chat-empty">
                      <div>Sign in to load your profile and start a database-backed chat.</div>
                    </div>
                    """, unsafe_allow_html=True)
                    return
                st.markdown("""
                <div class="chat-empty">
                  <div>Ask about crop disease, order status, or product dosage.</div>
                </div>
                """, unsafe_allow_html=True)

                st.markdown('<div class="chip-row">', unsafe_allow_html=True)
                _, _chip_col, _ = st.columns([1, 4, 1])
                with _chip_col:
                    for _i, _sug in enumerate(STARTER_QS):
                        if st.button(
                            _sug,
                            key=f"sugg_{_i}",
                            use_container_width=True,
                            disabled=not _is_logged_in(),
                        ):
                            _process_turn(_sug, None, None)
                            st.rerun(scope="fragment")
                st.markdown('</div>', unsafe_allow_html=True)

            for msg_idx, msg in enumerate(st.session_state.messages):
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

                    # Safety escalation banner
                    if data.get("safety_risk_detected"):
                        st.markdown(f"""
                        <div class="safety-banner">
                          <h3>Safety alert: human support activated</h3>
                          <p>{data.get('response_text', '')}</p>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        escalate_html = ""
                        if data.get("escalate_human"):
                            escalate_html = '<div class="escalate-tag">Escalated to human agronomist</div>'

                        st.markdown(
                            f'<div class="agent-bubble">'
                            f'{data.get("response_text", msg["content"])}'
                            f'{escalate_html}'
                            f'<div class="msg-ts">{ts}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                        # Product cards (Carousel)
                        products = data.get("matched_products", [])
                        if products:
                            idx_key = f"prod_idx_{msg_idx}_{ts}"
                            if idx_key not in st.session_state:
                                st.session_state[idx_key] = 0

                            if st.session_state[idx_key] >= len(products):
                                st.session_state[idx_key] = 0

                            current_prod = products[st.session_state[idx_key]]
                            prod_id = current_prod.get("product_id", str(uuid.uuid4())[:6])
                            prod_name = (
                                current_prod.get("english_name")
                                or current_prod.get("product_name")
                                or "Product"
                            )
                            product_key = f"{msg_idx}_{ts}_{prod_id}"
                            safe_card_key = re.sub(r"[^a-zA-Z0-9_]", "_", product_key)

                            with st.container(key=f"product_card_{safe_card_key}"):
                                st.markdown(_render_product_card(current_prod), unsafe_allow_html=True)

                                st.markdown(
                                    '<div class="pcard-rule"></div>'
                                    '<div class="pcard-action-title">Add to cart</div>',
                                    unsafe_allow_html=True,
                                )
                                col_qty, col_btn1, col_btn2 = st.columns(
                                    [0.72, 1, 1],
                                    gap="small",
                                    vertical_alignment="bottom",
                                )
                                with col_qty:
                                    qty = st.number_input(
                                        "Quantity",
                                        min_value=1,
                                        max_value=100,
                                        value=1,
                                        key=f"qty_{product_key}",
                                    )
                                group_eligible = qty >= GROUP_BUY_MIN_QUANTITY
                                with col_btn1:
                                    if st.button(
                                        "Add single",
                                        key=f"btn_{product_key}",
                                        use_container_width=True,
                                        disabled=not _is_logged_in(),
                                    ):
                                        result = _cart_add(prod_id, qty, is_group_buy=False)
                                        if result.get("error"):
                                            st.session_state.messages.append({"role": "assistant", "content": f"Couldn't add to cart: {html.escape(str(result['error']))}", "ts": datetime.now().strftime("%H:%M"), "data": {"intent": "logistics"}})
                                        else:
                                            st.session_state.messages.append({"role": "assistant", "content": f"Added <b>{qty}× {html.escape(prod_name)}</b> to cart. Total ¥{result.get('total_amount', 0):.2f}.", "ts": datetime.now().strftime("%H:%M"), "data": {"intent": "logistics"}})
                                        st.rerun() # Full app rerun to update sidebar cart
                                with col_btn2:
                                    if st.button(
                                        "Add group",
                                        key=f"btn_grp_{product_key}",
                                        use_container_width=True,
                                        disabled=(not group_eligible) or (not _is_logged_in()),
                                        help=f"Group buy starts at {GROUP_BUY_MIN_QUANTITY} units.",
                                    ):
                                        result = _cart_add(prod_id, qty, is_group_buy=True)
                                        if result.get("error"):
                                            st.session_state.messages.append({"role": "assistant", "content": f"Couldn't add to cart: {html.escape(str(result['error']))}", "ts": datetime.now().strftime("%H:%M"), "data": {"intent": "logistics"}})
                                        else:
                                            st.session_state.messages.append({"role": "assistant", "content": f"Added <b>{qty}× {html.escape(prod_name)}</b> to the group purchase. See cart.", "ts": datetime.now().strftime("%H:%M"), "data": {"intent": "logistics"}})
                                        st.rerun()
                                if not group_eligible:
                                    st.markdown(
                                        f'<div class="pcard-buy-note">Group buy starts at {GROUP_BUY_MIN_QUANTITY} units.</div>',
                                        unsafe_allow_html=True,
                                    )

                                if len(products) > 1:
                                    st.markdown('<div class="pcard-rule"></div>', unsafe_allow_html=True)
                                    col_prev, col_status, col_next = st.columns(
                                        [1, 1.4, 1],
                                        gap="small",
                                        vertical_alignment="center",
                                    )
                                    with col_prev:
                                        if st.button("Previous", key=f"prev_{msg_idx}_{ts}", use_container_width=True):
                                            st.session_state[idx_key] = (st.session_state[idx_key] - 1) % len(products)
                                            st.rerun(scope="fragment")
                                    with col_status:
                                        st.markdown(
                                            f'<div class="pcard-position">Product {st.session_state[idx_key] + 1} of {len(products)}</div>',
                                            unsafe_allow_html=True,
                                        )
                                    with col_next:
                                        if st.button("Next", key=f"next_{msg_idx}_{ts}", use_container_width=True):
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
                _fetch_chat_sessions.clear()
                st.rerun(scope="fragment")

    chat_interface()


# ── Footer — About ─────────────────────────────────────────────────────────────
_render_app_footer(_status_txt)


# ── Sidebar — session controls ─────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="agro-brand"><h1>Agro-Mind</h1></div>', unsafe_allow_html=True)

    st.markdown('<div class="panel-title">Account</div>', unsafe_allow_html=True)
    if _is_logged_in():
        active_customer = st.session_state.get("active_customer") or {}
        st.caption(
            f"Signed in: `{active_customer.get('username') or active_customer.get('name')}`"
        )
    else:
        # st.caption("No logged-in database session.")
        st.caption("")


    if st.button("New chat", use_container_width=True, key="sidebar_new_session", type="primary"):
        if _is_logged_in():
            new_session_result = _start_new_customer_session(API_URL)
            if new_session_result.get("error"):
                st.error(new_session_result["error"])
            else:
                _apply_logged_in_session(new_session_result)
                st.rerun()
        else:
            _apply_logged_out_session({"session_id": str(uuid.uuid4())})
            st.rerun()

    st.markdown('<div class="pcard-rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Cart</div>', unsafe_allow_html=True)

    if not _is_logged_in():
        st.markdown(_rail_empty.format("Sign in to use the cart."), unsafe_allow_html=True)
    else:
        sidebar_cart = _get_cart()
        st.session_state.cart_snapshot = sidebar_cart
        sidebar_items = sidebar_cart.get("items", [])

        if not sidebar_items:
            st.markdown(_rail_empty.format("Cart is empty."), unsafe_allow_html=True)
        else:
            for it in sidebar_items:
                kind = "Group" if it.get("is_group_buy") else "Single"
                product_id = html.escape(str(it.get("product_id", "")))
                quantity = html.escape(str(it.get("quantity", "")))
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
                    f'gap:8px;font-size:0.82rem;padding:6px 0;border-bottom:1px solid var(--border);">'
                    f'<span style="min-width:0;"><span class="mono" style="color:var(--text);">{product_id}</span><br>'
                    f'<span style="color:var(--text-muted);">{kind} × {quantity}</span></span>'
                    f'<span class="mono" style="color:var(--text);white-space:nowrap;">¥{it.get("line_total", 0):.2f}</span></div>',
                    unsafe_allow_html=True,
                )

            st.markdown(
                f'<div class="mono" style="text-align:right;font-weight:700;margin-top:8px;">'
                f'Total ¥{sidebar_cart.get("total_amount", 0):.2f}</div>',
                unsafe_allow_html=True,
            )
            create_plan = st.checkbox(
                "Create treatment plan",
                value=False,
                key="checkout_create_treatment_plan",
                help="Create a daily treatment plan during checkout.",
            )
            cart_action_col, clear_action_col = st.columns(2)
            with cart_action_col:
                if st.button("Checkout", use_container_width=True, key="checkout_btn", type="primary"):
                    res = _checkout(create_treatment_plan=create_plan)
                    if res.get("error"):
                        st.error(f"Checkout failed: {res['error']}")
                    else:
                        orders = res.get("orders", [])
                        st.session_state.cart_snapshot = {"items": [], "total_amount": 0}
                        for o in orders:
                            st.session_state.tracked_orders.append(o)
                        lines = "".join(
                            f'<div style="padding:3px 0;">Order '
                            f'<span class="mono" style="color:var(--text);">{html.escape(str(o["id"]))}</span> '
                            f'· tracking <span class="mono">{html.escape(str(o.get("tracking_number", "")))}</span> '
                            f'<span style="color:var(--text-muted);">'
                            f'({html.escape(str(o.get("courier", "")))}, {html.escape(str(o.get("estimated_delivery", "")))})'
                            f'</span></div>'
                            for o in orders
                        )
                        order_word = "order" if len(orders) == 1 else "orders"
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": f"Order placed. {len(orders)} {order_word} created.<br>{lines}"
                                       "<br>Ask about your order status anytime."
                                       + (" Treatment plan created." if create_plan else ""),
                            "ts": datetime.now().strftime("%H:%M"),
                            "data": {"intent": "logistics"},
                        })
                        st.rerun()
            with clear_action_col:
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
                    st.session_state.cart_snapshot = {"items": [], "total_amount": 0}
                    st.rerun()

    if st.session_state.get("tracked_orders"):
        st.markdown('<div class="pcard-rule"></div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">Shipment</div>', unsafe_allow_html=True)
        for o in st.session_state.tracked_orders:
            st.markdown(
                f'<div style="font-size:0.78rem;padding:6px 0;border-bottom:1px solid var(--border);line-height:1.7;">'
                f'<span class="mono" style="color:var(--text);">{html.escape(str(o.get("tracking_number","N/A")))}</span><br>'
                f'<span style="color:var(--text-muted);">{html.escape(str(o.get("courier","N/A")))} · '
                f'ETA {html.escape(str(o.get("estimated_delivery","N/A")))}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div class="pcard-rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Previous chats</div>', unsafe_allow_html=True)

    if not _is_logged_in():
        st.markdown(_rail_empty.format("Sign in to see previous chats."), unsafe_allow_html=True)
    else:
        if not st.session_state.get("show_previous_chats"):
            if st.button("Load previous chats", use_container_width=True, key="load_previous_chats"):
                st.session_state.show_previous_chats = True
                st.rerun()
        else:
            chat_sessions_payload = _fetch_chat_sessions(API_URL, st.session_state.session_id)
            chat_sessions = chat_sessions_payload.get("sessions", []) if isinstance(chat_sessions_payload, dict) else []

            if not chat_sessions:
                st.markdown(_rail_empty.format("No previous chats yet."), unsafe_allow_html=True)
            else:
                for idx, chat in enumerate(chat_sessions):
                    title = str(chat.get("title") or "New chat")
                    updated = _chat_list_timestamp(chat.get("updated_at"))
                    count = int(chat.get("message_count") or 0)
                    meta = " · ".join(part for part in [updated, f"{count} msg"] if part)
                    label = title if not meta else f"{title}\n{meta}"
                    is_current = bool(chat.get("is_current"))

                    if st.button(
                        label,
                        key=f"chat_session_{idx}",
                        use_container_width=True,
                        disabled=is_current,
                        type="primary" if is_current else "secondary",
                    ):
                        switch_result = _switch_chat_session(
                            API_URL,
                            str(chat.get("session_id") or ""),
                        )
                        if switch_result.get("error"):
                            st.error(switch_result["error"])
                        else:
                            st.session_state.active_view = "Chat"
                            st.rerun()

    st.markdown('<div class="pcard-rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Treatment plan</div>', unsafe_allow_html=True)

    if not _is_logged_in():
        st.markdown(_rail_empty.format("Sign in to see treatment plans."), unsafe_allow_html=True)
    elif not st.session_state.get("show_treatment_plan"):
        if st.button("Load treatment plan", use_container_width=True, key="load_treatment_plan"):
            st.session_state.show_treatment_plan = True
            st.rerun()
    else:
        sidebar_treatments = _get_treatments()
        if not sidebar_treatments:
            st.markdown(
                _rail_empty.format("No active plan. Select the treatment-plan option during checkout to create one."),
                unsafe_allow_html=True,
            )
        else:
            for tr in sidebar_treatments:
                tasks = tr.get("daily_tasks", [])
                product_label = tr.get("product_name") or tr.get("crop") or tr.get("product_id", "")
                total_days = len(tasks)
                done_count = sum(1 for t in tasks if t.get("done"))
                st.markdown(
                    f'<div style="font-size:0.82rem;color:var(--text-muted);margin-bottom:4px;">'
                    f'{html.escape(str(product_label))} · {done_count}/{total_days} days</div>',
                    unsafe_allow_html=True,
                )
                for task in tasks:
                    day = task.get("day", 0)
                    date_str = task.get("date", "")
                    is_done = task.get("done", False)
                    checked = st.checkbox(
                        f"Day {day} · {date_str}",
                        value=is_done,
                        key=f"sidebar_task_{tr['id']}_{day}",
                    )
                    if checked != is_done:
                        _mark_task_done(tr["id"], day)
                        st.rerun()
