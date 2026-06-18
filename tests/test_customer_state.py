from __future__ import annotations

import uuid

from db.customer_state import (
    add_cart_item,
    checkout_cart,
    clear_cart,
    create_diagnosis,
    get_all_customer_histories,
    get_cart,
    get_chat_history,
    get_order,
    get_order_context,
    list_orders,
)
from db.engine import SessionLocal, init_db
from db.models import Product
from memory.customer_memory import CustomerMemory


def test_diagnosis_and_cart_are_customer_backed():
    init_db()
    external_id = f"test-user-{uuid.uuid4()}"
    session_id = f"test-session-{uuid.uuid4()}"
    product_id = "TEST0001"

    db = SessionLocal()
    try:
        product = db.get(Product, product_id) or Product(id=product_id)
        product.product_name = "Test Product"
        product.english_name = "Test Product"
        product.product_type = "Fungicide"
        product.crops = "Tomato"
        product.specification = "100ml"
        product.main_ingredients = "Test active"
        product.how_to_use = "Apply safely"
        product.water_ratio = "1:100"
        product.group_price = 12.0
        product.single_price = 18.0
        product.active = True
        db.merge(product)
        db.commit()
    finally:
        db.close()

    diagnosis_id = create_diagnosis(
        session_id,
        external_id,
        problem_summary="Tomato leaves have yellow spots",
        diagnosis_text="Likely early fungal pressure.",
        recommended_product_id=product_id,
    )
    assert diagnosis_id > 0

    cart = add_cart_item(
        session_id,
        external_id,
        product_id,
        diagnosis_id=diagnosis_id,
        source="recommended",
    )
    assert cart["items"][0]["product_id"] == product_id
    assert cart["items"][0]["diagnosis_id"] == diagnosis_id
    assert cart["items"][0]["unit_price"] == 12.0

    loaded = get_cart(session_id, external_id)
    assert loaded["items"][0]["source"] == "recommended"

    checkout = checkout_cart(session_id, external_id)
    assert checkout["orders"][0]["product_id"] == product_id
    assert checkout["orders"][0]["status"] == "shipped"
    assert checkout["orders"][0]["tracking_number"].startswith("YT")
    order_id = checkout["orders"][0]["id"]

    orders = list_orders(session_id, external_id)
    assert orders["orders"][0]["id"] == order_id

    order = get_order(session_id, external_id, order_id)
    assert order["customer_id"] == orders["customer_id"]
    assert "Verified order from database" in get_order_context(session_id, external_id, order_id)
    assert "was not found" in get_order_context(session_id, external_id, "PDD-OTHER")

    cleared = clear_cart(session_id, external_id)
    assert cleared["status"] == "active"
    assert cleared["items"] == []


def test_full_history_includes_image_attachments():
    init_db()
    external_id = f"history-user-{uuid.uuid4()}"
    session_id = f"history-session-{uuid.uuid4()}"
    memory = CustomerMemory(session_id, external_id=external_id)
    memory.append_turn(
        "user",
        "leaf has spots",
        has_image=True,
        image_base64="aW1hZ2UtYnl0ZXM=",
        image_mime_type="image/png",
    )
    memory.append_turn("assistant", "diagnosis response")

    user_history = get_chat_history(
        session_id,
        external_id,
        limit=0,
        include_images=True,
    )
    assert len(user_history["messages"]) >= 2
    assert user_history["messages"][0]["has_image"] is True
    assert user_history["messages"][0]["attachments"][0]["mime_type"] == "image/png"
    assert user_history["messages"][0]["attachments"][0]["data_base64"] == "aW1hZ2UtYnl0ZXM="

    all_history = get_all_customer_histories(include_images=True)
    customer = next(c for c in all_history["customers"] if c["external_id"] == external_id)
    assert customer["messages"][0]["attachments"][0]["size_bytes"] == 11
