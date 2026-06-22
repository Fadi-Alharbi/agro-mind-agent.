"""
tools/agriculture_tools.py
──────────────────────────
All callable tools available to the Agro-Mind agent.
Includes order management, product catalog search, and agronomic utilities.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from rag.catalog_loader import search_catalog as _catalog_search, get_product_by_id, ProductRecord


# ── Order tracking ─────────────────────────────────────────────────────────────

_ORDER_STATUSES = [
    "Payment confirmed — order is being packed in Zhejiang warehouse.",
    "Shipped via postal courier from Hangzhou, Zhejiang. Estimated delivery: 3-5 business days.",
    "In transit — package scanned at regional sorting hub.",
    "Out for delivery — courier will attempt delivery today.",
    "Delivered — package marked as received at pickup station.",
    "Delivery attempted — please collect from courier station within 7 days.",
]


def track_order(order_id: str) -> dict:
    """
    Return mock order tracking status for a given order ID.
    In production this would call the PDD logistics API.
    """
    if not order_id or not order_id.strip():
        return {"error": "Invalid order ID", "order_id": order_id}

    seed = sum(ord(c) for c in order_id)
    idx = seed % len(_ORDER_STATUSES)
    status = _ORDER_STATUSES[idx]

    shipped_date = datetime.now(timezone.utc) - timedelta(days=(seed % 4))
    estimated_delivery = shipped_date + timedelta(days=4)

    return {
        "order_id": order_id,
        "status": status,
        "shipped_from": "Hangzhou, Zhejiang Province",
        "courier": "Postal Courier (邮政快递)",
        "shipped_date": shipped_date.strftime("%Y-%m-%d"),
        "estimated_delivery": estimated_delivery.strftime("%Y-%m-%d"),
    }


# ── Refund processing ──────────────────────────────────────────────────────────

_VALID_REFUND_REASONS = [
    "liquid_leak", "crushed_cap", "packaging_damage", "wrong_item",
    "missing_items", "product_expired", "not_received",
]


def initiate_refund(order_id: str, reason: str) -> dict:
    """
    Initiate a refund request for an order.
    Returns the refund decision and next steps.
    """
    if not order_id:
        return {"error": "Order ID is required"}

    reason_lower = reason.lower().replace(" ", "_")
    is_valid = any(r in reason_lower for r in _VALID_REFUND_REASONS)

    if is_valid:
        return {
            "order_id": order_id,
            "refund_status": "approved",
            "refund_type": "refund_only",
            "return_required": False,
            "message": (
                "Refund approved — no return needed. "
                "The refund will appear in your account within 1-3 business days. "
                "We apologize for the inconvenience!"
            ),
        }
    else:
        return {
            "order_id": order_id,
            "refund_status": "under_review",
            "refund_type": "standard_return",
            "return_required": True,
            "message": (
                "Your refund request is under review. "
                "Please apply via the Pinduoduo app and select the appropriate reason. "
                "Our team will respond within 24 hours."
            ),
        }


# ── Invoice handling ───────────────────────────────────────────────────────────

_INVOICE_THRESHOLD = 100.0  # Yuan


def request_invoice(order_id: str, amount: float) -> dict:
    """
    Process an invoice request. Only supported for orders over 100 Yuan.
    """
    if amount < _INVOICE_THRESHOLD:
        return {
            "eligible": False,
            "order_id": order_id,
            "amount": amount,
            "threshold": _INVOICE_THRESHOLD,
            "message": (
                f"Dear customer, invoices are only supported for orders over "
                f"¥{_INVOICE_THRESHOLD:.0f}. Your order total is ¥{amount:.2f}. "
                "Please contact us if you have other questions!"
            ),
        }

    return {
        "eligible": True,
        "order_id": order_id,
        "amount": amount,
        "invoice_type": "General VAT Invoice (增值税普通发票)",
        "processing_time": "3-5 business days",
        "message": (
            f"Dear customer, your invoice request for ¥{amount:.2f} has been submitted. "
            "Please provide your company name and tax ID via the chat. "
            "The invoice will be emailed or mailed within 3-5 business days."
        ),
    }


# ── Product catalog search ─────────────────────────────────────────────────────

def search_products(query: str, crop: Optional[str] = None, max_results: int = 3) -> list[dict]:
    """
    Search the product catalog by query keywords and optional crop filter.
    Returns a list of product dicts with pricing.
    """
    results = _catalog_search(query, crop, max_results)
    return [r.to_dict() for r in results]


def get_product(product_id: str) -> Optional[dict]:
    """
    Retrieve a single product by ID (e.g. 'AF0001').
    Returns None if not found.
    """
    rec = get_product_by_id(product_id)
    return rec.to_dict() if rec else None


# ── Soil & weather (agronomic utilities) ───────────────────────────────────────

def get_weather_forecast(location: str) -> str:
    """
    Return a weather advisory for agricultural planning.
    (Stub implementation — in production would call a weather API.)
    """
    return (
        f"Weather advisory for {location}: "
        "Expected temperature 22-28°C, humidity 65-75%. "
        "Suitable conditions for pesticide application. "
        "Avoid spraying if rain is forecast within 4 hours."
    )


def analyze_soil(ph_level: float, moisture: float) -> str:
    """
    Provide soil health recommendations based on pH and moisture.
    """
    advice = []

    if ph_level < 5.5:
        advice.append("Soil is strongly acidic (pH < 5.5). Apply agricultural lime to raise pH.")
    elif ph_level < 6.0:
        advice.append("Soil is mildly acidic (pH 5.5–6.0). Consider adding lime for sensitive crops.")
    elif ph_level > 7.5:
        advice.append("Soil is alkaline (pH > 7.5). Apply sulfur or acidifying fertilizer.")
    else:
        advice.append(f"Soil pH {ph_level:.1f} is optimal for most crops.")

    if moisture < 20:
        advice.append("Soil moisture is low — irrigation recommended before pesticide application.")
    elif moisture > 80:
        advice.append("Soil moisture is high — risk of waterlogging and root rot. Improve drainage.")
    else:
        advice.append(f"Soil moisture {moisture:.0f}% is within acceptable range.")

    return " | ".join(advice)
