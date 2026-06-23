"""
db/customer_state.py
────────────────────
Transactional helpers for customer-facing state that spans chat, diagnosis,
cart, orders, and follow-ups.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from db.engine import SessionLocal
from db.models import (
    Cart,
    CartItem,
    Customer,
    Diagnosis,
    Message,
    Order,
    Product,
    Session as DBSession,
    Treatment,
)
from rag.catalog_loader import get_product_by_id


GROUP_BUY_MIN_QUANTITY = 10
_PASSWORD_SCHEME = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 260_000
_SHIPPED_MEMORY_STATUSES = ("shipped", "out_for_delivery", "delivered")
TREATMENT_ORDER_STATUSES = ("shipped", "out_for_delivery", "delivered")


def _hash_password(password: str) -> str:
    salt = secrets.token_urlsafe(18)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PASSWORD_ITERATIONS,
    ).hex()
    return f"{_PASSWORD_SCHEME}${_PASSWORD_ITERATIONS}${salt}${digest}"


def _verify_password(password: str, stored_hash: Optional[str]) -> bool:
    if not stored_hash:
        return False
    try:
        scheme, iterations, salt, expected = stored_hash.split("$", 3)
        if scheme != _PASSWORD_SCHEME:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
    except Exception:
        return False
    return hmac.compare_digest(digest, expected)


def _new_session_id(db) -> str:
    """Create a unique session id that is not already present in the DB."""
    while True:
        session_id = str(uuid.uuid4())
        if db.get(DBSession, session_id) is None:
            return session_id


def _customer_login_payload(
    customer: Customer,
    session_id: str,
    *,
    session_changed: bool,
) -> dict:
    return {
        "id": customer.id,
        "external_id": customer.external_id,
        "username": _display_username(customer),
        "name": customer.name or "",
        "location": customer.location or "",
        "crop_type": customer.crop_type or "",
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
        "session_id": session_id,
        "session_changed": session_changed,
    }


def _validate_group_buy_quantity(quantity: int) -> None:
    if quantity < GROUP_BUY_MIN_QUANTITY:
        raise ValueError(
            f"Group buy requires at least {GROUP_BUY_MIN_QUANTITY} units. "
            f"Current group quantity would be {quantity}."
        )


def _ensure_customer(session_id: str, external_id: Optional[str]) -> int:
    """Return the customer id for an active authenticated session."""
    db = SessionLocal()
    try:
        db_session = db.get(DBSession, (session_id or "").strip())
        if (
            db_session is None
            or db_session.customer_id is None
            or not db_session.is_authenticated
            or db_session.ended_at is not None
        ):
            raise PermissionError("Login is required.")
        db_session.last_active = datetime.now(timezone.utc)
        db.commit()
        return db_session.customer_id
    finally:
        db.close()


def require_authenticated_session(session_id: str) -> dict:
    """Validate that the session is active and authenticated."""
    customer_id = _ensure_customer(session_id, None)
    return {"customer_id": customer_id, "session_id": session_id}


def _active_cart(db, customer_id: int, session_id: Optional[str] = None) -> Cart:
    cart = db.scalars(
        select(Cart)
        .where(Cart.customer_id == customer_id, Cart.status == "active")
        .order_by(Cart.id.desc())
        .limit(1)
    ).first()
    if cart is not None:
        return cart

    cart = Cart(customer_id=customer_id, session_id=session_id, status="active")
    db.add(cart)
    db.flush()
    return cart


def _cart_to_dict(cart: Cart) -> dict:
    items: list[dict] = []
    total = 0.0
    for item in cart.items:
        product = item.product
        line_total = float(item.unit_price or 0.0) * int(item.quantity or 0)
        total += line_total
        items.append({
            "id": item.id,
            "product_id": item.product_id,
            "product_name": product.english_name or product.product_name if product else item.product_id,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "line_total": line_total,
            "is_group_buy": item.is_group_buy,
            "source": item.source,
            "diagnosis_id": item.diagnosis_id,
        })
    return {
        "id": cart.id,
        "customer_id": cart.customer_id,
        "session_id": cart.session_id,
        "status": cart.status,
        "items": items,
        "total_amount": total,
        "group_buy_min_quantity": GROUP_BUY_MIN_QUANTITY,
    }


def _order_to_dict(order: Order) -> dict:
    product = order.product
    return {
        "id": order.id,
        "customer_id": order.customer_id,
        "product_id": order.product_id,
        "product_name": (
            product.english_name or product.product_name
            if product else order.product_id
        ),
        "cart_id": order.cart_id,
        "diagnosis_id": order.diagnosis_id,
        "quantity": order.quantity,
        "total_amount": order.total_amount,
        "is_group_buy": order.is_group_buy,
        "status": order.status,
        "tracking_number": order.tracking_number,
        "courier": order.courier,
        "shipped_from": order.shipped_from,
        "estimated_delivery": order.estimated_delivery,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }


def _product_name(product: Optional[Product], fallback: Optional[str] = None) -> str:
    if product is None:
        return fallback or ""
    return product.english_name or product.product_name or product.id


def _is_pesticide_product_filter():
    return func.lower(Product.product_type).like("%pesticide%")


def get_pesticide_memory_for_customer(db, customer_id: Optional[int], limit: int = 5) -> dict:
    """Return pesticides the customer is currently holding or has shipped.

    This is derived from cart/order state so memory cannot drift out of sync:
    active cart rows mean "in cart"; shipped/out-for-delivery/delivered order
    rows mean the pesticide has left the warehouse.
    """
    if not customer_id:
        return {"cart": [], "shipped": [], "current": None}

    limit = max(1, min(int(limit or 5), 20))

    cart_rows = db.execute(
        select(CartItem, Cart, Product)
        .join(Cart, CartItem.cart_id == Cart.id)
        .join(Product, CartItem.product_id == Product.id)
        .where(
            Cart.customer_id == customer_id,
            Cart.status == "active",
            _is_pesticide_product_filter(),
        )
        .order_by(Cart.updated_at.desc(), CartItem.updated_at.desc(), CartItem.id.desc())
        .limit(limit)
    ).all()
    cart_items = [
        {
            "state": "cart",
            "cart_id": cart.id,
            "product_id": item.product_id,
            "product_name": _product_name(product, item.product_id),
            "product_type": product.product_type if product else "",
            "quantity": item.quantity,
            "is_group_buy": item.is_group_buy,
        }
        for item, cart, product in cart_rows
    ]

    shipped_rows = db.execute(
        select(Order, Product)
        .join(Product, Order.product_id == Product.id)
        .where(
            Order.customer_id == customer_id,
            Order.status.in_(_SHIPPED_MEMORY_STATUSES),
            _is_pesticide_product_filter(),
        )
        .order_by(Order.updated_at.desc(), Order.created_at.desc(), Order.id.desc())
        .limit(limit)
    ).all()
    shipped_orders = [
        {
            "state": "shipped",
            "order_id": order.id,
            "product_id": order.product_id,
            "product_name": _product_name(product, order.product_id),
            "product_type": product.product_type if product else "",
            "quantity": order.quantity,
            "status": order.status,
            "tracking_number": order.tracking_number,
            "estimated_delivery": order.estimated_delivery,
        }
        for order, product in shipped_rows
    ]

    current = cart_items[0] if cart_items else (shipped_orders[0] if shipped_orders else None)
    return {"cart": cart_items, "shipped": shipped_orders, "current": current}


def format_pesticide_memory_lines(memory: Optional[dict], limit: int = 3) -> list[str]:
    """Format pesticide memory as compact prompt-safe profile lines."""
    if not memory:
        return []

    lines: list[str] = []
    cart_items = (memory.get("cart") or [])[:limit]
    shipped_orders = (memory.get("shipped") or [])[:limit]

    if cart_items:
        labels = [
            f"{item.get('product_name') or item.get('product_id')} "
            f"({item.get('product_id')}, qty {item.get('quantity')})"
            for item in cart_items
        ]
        lines.append(f"- Pesticides in active cart: {'; '.join(labels)}")

    if shipped_orders:
        labels = []
        for order in shipped_orders:
            order_label = (
                f"{order.get('product_name') or order.get('product_id')} "
                f"({order.get('product_id')}, order {order.get('order_id')}, "
                f"status {order.get('status')})"
            )
            if order.get("tracking_number"):
                order_label += f", tracking {order.get('tracking_number')}"
            labels.append(order_label)
        lines.append(f"- Shipped pesticides: {'; '.join(labels)}")

    current = memory.get("current")
    if current:
        lines.append(
            "- Current pesticide reference for 'it/this product': "
            f"{current.get('product_name') or current.get('product_id')} "
            f"({current.get('product_id')}, from {current.get('state')})"
        )

    return lines


def get_pesticide_memory(session_id: str, external_id: Optional[str]) -> dict:
    """Return active-cart and shipped pesticide memory for the logged-in customer."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        return get_pesticide_memory_for_customer(db, customer_id)
    finally:
        db.close()


def get_cart(session_id: str, external_id: Optional[str]) -> dict:
    """Return the active DB-backed cart for this customer."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        cart = _active_cart(db, customer_id, session_id=session_id)
        db.commit()
        cart = db.scalars(
            select(Cart)
            .options(selectinload(Cart.items).selectinload(CartItem.product))
            .where(Cart.id == cart.id)
        ).one()
        return _cart_to_dict(cart)
    finally:
        db.close()


def list_orders(session_id: str, external_id: Optional[str]) -> dict:
    """Return DB-backed orders for the logged-in customer."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        orders = db.scalars(
            select(Order)
            .options(selectinload(Order.product))
            .where(Order.customer_id == customer_id)
            .order_by(Order.created_at.desc(), Order.id.desc())
        ).all()
        return {"customer_id": customer_id, "orders": [_order_to_dict(order) for order in orders]}
    finally:
        db.close()


def get_order(session_id: str, external_id: Optional[str], order_id: str) -> dict:
    """Return one order only if it belongs to the logged-in customer."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        order = db.scalars(
            select(Order)
            .options(selectinload(Order.product))
            .where(Order.id == order_id, Order.customer_id == customer_id)
        ).first()
        if order is None:
            raise ValueError(f"Order {order_id} was not found for this customer.")
        return _order_to_dict(order)
    finally:
        db.close()


def get_order_context(session_id: str, external_id: Optional[str], order_id: Optional[str]) -> str:
    """Return a prompt-safe order summary for logistics answers."""
    if not order_id:
        return "No order ID provided."
    try:
        order = get_order(session_id, external_id, order_id)
    except ValueError:
        return f"Order ID {order_id} was not found for this logged-in customer."

    return (
        f"Verified order from database:\n"
        f"- Order ID: {order['id']}\n"
        f"- Status: {order['status']}\n"
        f"- Product: {order.get('product_name') or order.get('product_id')}\n"
        f"- Quantity: {order['quantity']}\n"
        f"- Total: ¥{float(order['total_amount'] or 0):.2f}\n"
        f"- Tracking number: {order.get('tracking_number') or 'not issued yet'}\n"
        f"- Courier: {order.get('courier') or 'not assigned yet'}\n"
        f"- Shipped from: {order.get('shipped_from') or 'not shipped yet'}\n"
        f"- Estimated delivery: {order.get('estimated_delivery') or 'not available yet'}\n"
        f"- Created at: {order.get('created_at') or 'unknown'}\n"
        "Use only this verified order data. If the user asks about a different order, ask them to select or enter a valid order number."
    )


def _product_display_name(product: Optional[Product], product_id: Optional[str]) -> str:
    if product:
        return product.english_name or product.product_name or product_id or "purchased product"
    if product_id:
        record = get_product_by_id(product_id)
        if record:
            return record.english_name or record.product_name or record.product_id
        return product_id
    return "purchased product"


def _checkout_treatment_details(item: CartItem) -> dict:
    product = item.product
    product_label = _product_display_name(product, item.product_id)
    dosage = (product.water_ratio or "").strip() if product else ""
    usage = (product.how_to_use or "").strip() if product else ""
    spec = (product.specification or "").strip() if product else ""

    instruction_parts = []
    if usage:
        instruction_parts.append(usage)
    if dosage and dosage.casefold() not in usage.casefold():
        instruction_parts.append(f"Water ratio: {dosage}")
    if spec:
        instruction_parts.append(f"Specification: {spec}")

    return {
        "crop": None,
        "disease": None,
        "duration": "5 days",
        "instructions": "\n".join(instruction_parts) or f"Use {product_label} according to the product label.",
        "quantity_per_dose": dosage or None,
    }


def _create_checkout_treatment(
    db,
    *,
    customer_id: int,
    session_id: str,
    item: CartItem,
    start_date: str,
) -> Optional[Treatment]:
    if not item.product_id:
        return None

    existing = db.scalars(
        select(Treatment).where(
            Treatment.customer_id == customer_id,
            Treatment.product_id == item.product_id,
            Treatment.status == "active",
        )
    ).first()
    if existing is not None:
        return existing

    details = _checkout_treatment_details(item)
    tasks = _generate_daily_tasks(
        start_date=start_date,
        duration_str=details["duration"],
        product_id=item.product_id,
        quantity_per_dose=details["quantity_per_dose"],
        crop=details["crop"],
        disease=details["disease"],
    )
    import json as _json

    treatment = Treatment(
        customer_id=customer_id,
        session_id=session_id,
        start_date=start_date,
        crop=details["crop"],
        disease=details["disease"],
        product_id=item.product_id,
        duration=details["duration"],
        instructions=details["instructions"],
        quantity_per_dose=details["quantity_per_dose"],
        daily_tasks=_json.dumps(tasks, ensure_ascii=False) if tasks else None,
        status="active",
    )
    db.add(treatment)
    return treatment


def checkout_cart(
    session_id: str,
    external_id: Optional[str],
    *,
    create_treatment_plan: bool = False,
) -> dict:
    """Convert the active cart into one or more DB-backed orders."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        cart = db.scalars(
            select(Cart)
            .options(selectinload(Cart.items).selectinload(CartItem.product))
            .where(Cart.customer_id == customer_id, Cart.status == "active")
            .order_by(Cart.id.desc())
            .limit(1)
        ).first()
        if cart is None or not cart.items:
            raise ValueError("Cart is empty.")

        now = datetime.now(timezone.utc)
        stamp = now.strftime("%Y%m%d%H%M%S")
        treatment_start = now.strftime("%Y-%m-%d")
        orders: list[Order] = []
        for idx, item in enumerate(cart.items, start=1):
            if item.is_group_buy and int(item.quantity or 0) < GROUP_BUY_MIN_QUANTITY:
                _validate_group_buy_quantity(int(item.quantity or 0))
            line_total = float(item.unit_price or 0.0) * int(item.quantity or 0)
            order = Order(
                id=f"PDD{stamp}-{customer_id}-{idx}",
                customer_id=customer_id,
                product_id=item.product_id,
                cart_id=cart.id,
                diagnosis_id=item.diagnosis_id,
                quantity=item.quantity,
                total_amount=line_total,
                is_group_buy=item.is_group_buy,
                status="shipped",
                tracking_number=f"YT{stamp}{customer_id:04d}{idx:02d}",
                courier="Postal Courier",
                shipped_from="Zhejiang Province",
                estimated_delivery="3-5 business days",
            )
            db.add(order)
            if create_treatment_plan:
                _create_checkout_treatment(
                    db,
                    customer_id=customer_id,
                    session_id=session_id,
                    item=item,
                    start_date=treatment_start,
                )
            orders.append(order)
        cart.status = "converted"
        db.commit()
        for order in orders:
            db.refresh(order)
        return {"orders": [_order_to_dict(order) for order in orders]}
    finally:
        db.close()


def get_profile(session_id: str, external_id: Optional[str]) -> dict:
    """Return the saved customer profile for the logged-in demo user."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        customer = db.get(Customer, customer_id)
        if customer is None:
            return {}
        return {
            "id": customer.id,
            "external_id": customer.external_id,
            "name": customer.name or "",
            "location": customer.location or "",
            "crop_type": customer.crop_type or "",
            "last_recommended_product": customer.last_recommended_product,
            "pesticide_memory": get_pesticide_memory_for_customer(db, customer_id),
            "created_at": customer.created_at.isoformat() if customer.created_at else None,
        }
    finally:
        db.close()


def _message_to_dict(message: Message, *, include_images: bool = False) -> dict:
    attachments = []
    if include_images:
        attachments = [
            {
                "id": attachment.id,
                "mime_type": attachment.mime_type,
                "data_base64": attachment.data_base64,
                "size_bytes": attachment.size_bytes,
                "created_at": attachment.created_at.isoformat() if attachment.created_at else None,
            }
            for attachment in message.attachments
        ]
    content = message.content or ""
    recommended_product_id = None
    matched_products: list[dict] = []
    if message.role == "assistant":
        import re

        product_ids = re.findall(r"\[PRODUCT:\s*([A-Z0-9]+)\]", content)
        if not product_ids:
            fallback = re.search(r"Product ID:\s*([A-Z0-9]+)", content)
            if fallback:
                product_ids = [fallback.group(1)]
        if product_ids:
            recommended_product_id = product_ids[0]
            for product_id in product_ids:
                record = get_product_by_id(product_id)
                if record:
                    matched_products.append(record.to_dict())
            content = re.sub(r"\[PRODUCT:\s*[A-Z0-9]+\]", "", content).strip()
            content = re.sub(
                r"Product ID:\s*[A-Z0-9]+.*",
                "",
                content,
                flags=re.IGNORECASE,
            ).strip()
    return {
        "id": message.id,
        "session_id": message.session_id,
        "role": message.role,
        "content": content,
        "intent": message.intent,
        "has_image": message.has_image,
        "attachments": attachments,
        "recommended_product_id": recommended_product_id,
        "matched_products": matched_products,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def get_chat_history(
    session_id: str,
    external_id: Optional[str],
    limit: int = 80,
    *,
    include_images: bool = False,
    all_sessions: bool = False,
) -> dict:
    """Return recent message history for the selected session by default."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        if all_sessions:
            session_ids = list(
                db.scalars(select(DBSession.id).where(DBSession.customer_id == customer_id)).all()
            )
        else:
            current_session = db.get(DBSession, session_id)
            if current_session is None or current_session.customer_id != customer_id:
                session_ids = []
            else:
                session_ids = [session_id]
        if not session_ids:
            return {"messages": []}
        query = (
            select(Message)
            .options(selectinload(Message.attachments))
            .where(Message.session_id.in_(session_ids))
            .order_by(Message.created_at.desc(), Message.id.desc())
        )
        if limit > 0:
            query = query.limit(max(1, min(limit, 1000)))
        rows = db.scalars(query).all()
        messages = [
            _message_to_dict(message, include_images=include_images)
            for message in reversed(rows)
        ]
        return {"customer_id": customer_id, "messages": messages}
    finally:
        db.close()


def list_customer_sessions(session_id: str, external_id: Optional[str]) -> dict:
    """Return chat sessions for the authenticated customer only."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        sessions = db.scalars(
            select(DBSession)
            .where(DBSession.customer_id == customer_id, DBSession.ended_at.is_(None))
            .order_by(DBSession.last_active.desc(), DBSession.started_at.desc())
        ).all()

        rows = []
        for chat_session in sessions:
            first_user_message = db.scalars(
                select(Message)
                .where(
                    Message.session_id == chat_session.id,
                    Message.role == "user",
                )
                .order_by(Message.created_at.asc(), Message.id.asc())
                .limit(1)
            ).first()
            latest_message = db.scalars(
                select(Message)
                .where(Message.session_id == chat_session.id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            ).first()
            message_count = db.scalar(
                select(func.count(Message.id)).where(Message.session_id == chat_session.id)
            ) or 0
            title = (first_user_message.content if first_user_message else "").strip()
            if not title:
                title = "New chat"
            if len(title) > 64:
                title = f"{title[:61].rstrip()}..."

            updated_at = (
                latest_message.created_at
                if latest_message and latest_message.created_at
                else chat_session.last_active or chat_session.started_at
            )
            rows.append({
                "session_id": chat_session.id,
                "title": title,
                "message_count": int(message_count),
                "updated_at": updated_at.isoformat() if updated_at else None,
                "is_current": chat_session.id == session_id,
            })

        return {"customer_id": customer_id, "sessions": rows}
    finally:
        db.close()


def get_all_customer_histories(
    *,
    include_images: bool = False,
    message_limit_per_customer: int = 0,
) -> dict:
    """Return complete chat history grouped by every customer."""
    db = SessionLocal()
    try:
        customers = db.scalars(
            select(Customer).order_by(Customer.created_at.asc(), Customer.id.asc())
        ).all()
        payload: list[dict] = []
        for customer in customers:
            session_ids = list(
                db.scalars(select(DBSession.id).where(DBSession.customer_id == customer.id)).all()
            )
            query = (
                select(Message)
                .options(selectinload(Message.attachments))
                .where(Message.session_id.in_(session_ids))
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
            if message_limit_per_customer > 0:
                query = query.limit(min(message_limit_per_customer, 1000))
            messages = db.scalars(query).all() if session_ids else []
            payload.append({
                "id": customer.id,
                "external_id": customer.external_id,
                "username": _display_username(customer),
                "name": customer.name or "",
                "location": customer.location or "",
                "crop_type": customer.crop_type or "",
                "last_recommended_product": customer.last_recommended_product,
                "created_at": customer.created_at.isoformat() if customer.created_at else None,
                "session_ids": session_ids,
                "message_count": len(messages),
                "messages": [
                    _message_to_dict(message, include_images=include_images)
                    for message in messages
                ],
            })
        return {"customers": payload}
    finally:
        db.close()


def update_profile(
    session_id: str,
    external_id: Optional[str],
    *,
    name: Optional[str] = None,
    location: Optional[str] = None,
    crop_type: Optional[str] = None,
) -> dict:
    """Persist editable customer profile fields."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        customer = db.get(Customer, customer_id)
        if customer is None:
            raise ValueError("Customer profile was not found.")
        customer.name = (name or "").strip() or None
        customer.location = (location or "").strip() or None
        customer.crop_type = (crop_type or "").strip() or None
        db.commit()
        return {
            "id": customer.id,
            "external_id": customer.external_id,
            "name": customer.name or "",
            "location": customer.location or "",
            "crop_type": customer.crop_type or "",
            "last_recommended_product": customer.last_recommended_product,
            "created_at": customer.created_at.isoformat() if customer.created_at else None,
        }
    finally:
        db.close()


def list_customers(limit: int = 25) -> list[dict]:
    """Return recent customers that can be selected from the local login screen."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(
                Customer,
                func.count(Message.id.distinct()).label("message_count"),
                func.count(Diagnosis.id.distinct()).label("diagnosis_count"),
            )
            .outerjoin(DBSession, DBSession.customer_id == Customer.id)
            .outerjoin(Message, Message.session_id == DBSession.id)
            .outerjoin(Diagnosis, Diagnosis.customer_id == Customer.id)
            .group_by(Customer.id)
            .order_by(Customer.created_at.desc(), Customer.id.desc())
            .limit(max(1, min(limit, 100)))
        ).all()
        customers: list[dict] = []
        for customer, message_count, diagnosis_count in rows:
            customers.append({
                "id": customer.id,
                "external_id": customer.external_id,
                "username": _display_username(customer),
                "name": customer.name or "",
                "location": customer.location or "",
                "crop_type": customer.crop_type or "",
                "message_count": int(message_count or 0),
                "diagnosis_count": int(diagnosis_count or 0),
                "created_at": customer.created_at.isoformat() if customer.created_at else None,
            })
        return customers
    finally:
        db.close()


def login_customer(
    username: str,
    password: str,
    session_id: Optional[str] = None,
) -> dict:
    """Resolve an existing customer or create a new password-backed identity."""
    username = (username or "").strip()
    password = password or ""
    if not username:
        raise ValueError("Username is required.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")

    external_id = username if ":" in username else f"demo:{username.lower()}"
    requested_session_id = (session_id or "").strip()
    if requested_session_id.lower() in {"guest", "anonymous"}:
        requested_session_id = ""

    db = SessionLocal()
    try:
        customer = db.scalars(
            select(Customer).where(
                (Customer.external_id == external_id)
                | (Customer.external_id == username)
                | (func.lower(Customer.name) == username.lower())
            )
        ).first()
        if customer is None:
            customer = Customer(
                external_id=external_id,
                name=username,
                password_hash=_hash_password(password),
            )
            db.add(customer)
            db.flush()
        elif customer.password_hash:
            if not _verify_password(password, customer.password_hash):
                raise PermissionError("Invalid username or password.")
        else:
            customer.password_hash = _hash_password(password)
        if not customer.external_id:
            customer.external_id = external_id

        active_session_id = requested_session_id
        session_changed = False
        if active_session_id:
            db_session = db.get(DBSession, active_session_id)
            if db_session is None:
                db.add(DBSession(
                    id=active_session_id,
                    customer_id=customer.id,
                    is_authenticated=True,
                ))
            elif (
                db_session.customer_id == customer.id
                and db_session.is_authenticated
                and db_session.ended_at is None
            ):
                db_session.last_active = datetime.now(timezone.utc)
            else:
                active_session_id = _new_session_id(db)
                db.add(DBSession(
                    id=active_session_id,
                    customer_id=customer.id,
                    is_authenticated=True,
                ))
                session_changed = True
        else:
            active_session_id = _new_session_id(db)
            db.add(DBSession(
                id=active_session_id,
                customer_id=customer.id,
                is_authenticated=True,
            ))
            session_changed = True

        db.commit()
        return _customer_login_payload(
            customer,
            active_session_id,
            session_changed=session_changed,
        )
    finally:
        db.close()


def logout_customer(session_id: Optional[str]) -> dict:
    """Invalidate the current DB session and return a fresh anonymous id."""
    previous_session_id = (session_id or "").strip() or None
    db = SessionLocal()
    try:
        if previous_session_id:
            db_session = db.get(DBSession, previous_session_id)
            if db_session is not None:
                now = datetime.now(timezone.utc)
                db_session.is_authenticated = False
                db_session.ended_at = now
                db_session.last_active = now
                db.commit()
        return {
            "logged_in": False,
            "session_id": str(uuid.uuid4()),
            "previous_session_id": previous_session_id,
            "session_changed": True,
        }
    finally:
        db.close()


def create_customer_session(session_id: str) -> dict:
    """Create a fresh chat session for the already logged-in customer."""
    session_id = (session_id or "").strip()
    if not session_id:
        raise PermissionError("Login is required before creating a new session.")

    db = SessionLocal()
    try:
        current_session = db.get(DBSession, session_id)
        if (
            current_session is None
            or current_session.customer_id is None
            or not current_session.is_authenticated
            or current_session.ended_at is not None
        ):
            raise PermissionError("Login is required before creating a new session.")

        customer = db.get(Customer, current_session.customer_id)
        if customer is None:
            raise PermissionError("Logged-in customer was not found.")

        new_session_id = _new_session_id(db)
        db.add(DBSession(
            id=new_session_id,
            customer_id=customer.id,
            is_authenticated=True,
        ))
        db.commit()
        return _customer_login_payload(
            customer,
            new_session_id,
            session_changed=True,
        )
    finally:
        db.close()


def resume_session(session_id: str) -> dict:
    """Return the login payload for an active, authenticated session.

    Used to rehydrate the UI after a browser reload: the session_id is read from
    a persistent cookie, and this confirms the DB session is still authenticated
    (not logged out, not ended) before the customer is restored. The validity
    check mirrors ``_ensure_customer`` so the cookie can never outlive a logout.
    """
    session_id = (session_id or "").strip()
    if not session_id:
        raise PermissionError("Login is required.")

    db = SessionLocal()
    try:
        db_session = db.get(DBSession, session_id)
        if (
            db_session is None
            or db_session.customer_id is None
            or not db_session.is_authenticated
            or db_session.ended_at is not None
        ):
            raise PermissionError("Session is not active.")

        customer = db.get(Customer, db_session.customer_id)
        if customer is None:
            raise PermissionError("Logged-in customer was not found.")

        db_session.last_active = datetime.now(timezone.utc)
        db.commit()
        return _customer_login_payload(
            customer,
            session_id,
            session_changed=False,
        )
    finally:
        db.close()


def _display_username(customer: Customer) -> str:
    external_id = customer.external_id or ""
    if external_id.startswith("demo:"):
        return external_id.split(":", 1)[1]
    return customer.name or external_id or f"customer-{customer.id}"


def add_cart_item(
    session_id: str,
    external_id: Optional[str],
    product_id: str,
    *,
    quantity: int = 1,
    is_group_buy: bool = True,
    diagnosis_id: Optional[int] = None,
    source: str = "manual",
) -> dict:
    """Add or increment a product in the active cart."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        product = db.get(Product, product_id)
        if product is None:
            record = get_product_by_id(product_id)
            if record is None:
                raise ValueError(f"Unknown product_id: {product_id}")
            product = Product(
                id=record.product_id,
                product_name=record.product_name,
                english_name=record.english_name,
                product_type=record.product_type,
                crops=record.crops,
                specification=record.specification,
                main_ingredients=record.main_ingredients,
                how_to_use=record.how_to_use,
                water_ratio=record.water_ratio,
                group_price=record.group_price,
                single_price=record.single_price,
                active=True,
            )
            db.add(product)
            db.flush()

        cart = _active_cart(db, customer_id, session_id=session_id)
        item = db.scalars(
            select(CartItem).where(
                CartItem.cart_id == cart.id,
                CartItem.product_id == product_id,
                CartItem.diagnosis_id == diagnosis_id,
                CartItem.is_group_buy == is_group_buy,
            )
        ).first()
        next_quantity = (int(item.quantity or 0) if item else 0) + max(1, quantity)
        if is_group_buy and next_quantity < GROUP_BUY_MIN_QUANTITY:
            _validate_group_buy_quantity(next_quantity)
        unit_price = product.group_price if is_group_buy else product.single_price
        if item:
            item.quantity = next_quantity
            item.unit_price = unit_price
        else:
            db.add(CartItem(
                cart_id=cart.id,
                product_id=product_id,
                quantity=next_quantity,
                unit_price=unit_price,
                is_group_buy=is_group_buy,
                diagnosis_id=diagnosis_id,
                source=source,
            ))

        db.commit()
        cart = db.scalars(
            select(Cart)
            .options(selectinload(Cart.items).selectinload(CartItem.product))
            .where(Cart.id == cart.id)
        ).one()
        return _cart_to_dict(cart)
    finally:
        db.close()


def clear_cart(session_id: str, external_id: Optional[str]) -> dict:
    """Mark the active cart as cleared and return a fresh empty cart snapshot."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        cart = db.scalars(
            select(Cart)
            .where(Cart.customer_id == customer_id, Cart.status == "active")
            .order_by(Cart.id.desc())
            .limit(1)
        ).first()
        if cart:
            cart.status = "cleared"
        fresh = Cart(customer_id=customer_id, session_id=session_id, status="active")
        db.add(fresh)
        db.commit()
        db.refresh(fresh)
        return _cart_to_dict(fresh)
    finally:
        db.close()


def create_diagnosis(
    session_id: str,
    external_id: Optional[str],
    *,
    problem_summary: str,
    diagnosis_text: str,
    recommended_product_id: Optional[str] = None,
    severity: str = "unknown",
) -> int:
    """Persist a structured crop issue linked to the latest diagnosis message."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        customer = db.get(Customer, customer_id)
        db_session = db.get(DBSession, session_id)
        message = db.scalars(
            select(Message)
            .where(Message.session_id == session_id, Message.role == "user")
            .order_by(Message.id.desc())
            .limit(1)
        ).first()
        diagnosis = Diagnosis(
            customer_id=customer_id,
            session_id=db_session.id if db_session else session_id,
            message_id=message.id if message else None,
            crop_type=customer.crop_type if customer else None,
            problem_summary=problem_summary,
            diagnosis_text=diagnosis_text,
            recommended_product_id=recommended_product_id,
            severity=severity,
            status="open",
        )
        db.add(diagnosis)
        db.commit()
        return diagnosis.id
    finally:
        db.close()


# ── Active treatments (proactive check-ins) ─────────────────────────────────────
def _treatment_to_dict(t: Treatment) -> dict:
    import json as _json
    daily_tasks = []
    if t.daily_tasks:
        try:
            daily_tasks = _json.loads(t.daily_tasks)
        except Exception:
            daily_tasks = []
    product_name = None
    if t.product_id:
        record = get_product_by_id(t.product_id)
        if record:
            product_name = record.english_name or record.product_name
    return {
        "id": t.id,
        "start_date": t.start_date,
        "crop": t.crop,
        "disease": t.disease,
        "product_id": t.product_id,
        "product_name": product_name,
        "duration": t.duration,
        "quantity_per_dose": t.quantity_per_dose,
        "instructions": t.instructions,
        "daily_tasks": daily_tasks,
        "status": t.status,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _generate_daily_tasks(
    start_date: str,
    duration_str: Optional[str],
    product_id: Optional[str],
    quantity_per_dose: Optional[str],
    crop: Optional[str],
    disease: Optional[str],
) -> list[dict]:
    """Build a list of daily task dicts from treatment metadata.

    Parses numeric days out of duration_str (e.g. '4 days', '3-5 days' → 4, '1 week' → 7).
    Returns [] when duration cannot be determined.
    """
    import re
    from datetime import timedelta

    if not duration_str:
        duration_str = "5 days"

    # Try to extract a number of days
    nums = re.findall(r"\d+", duration_str)
    if not nums:
        nums = ["5"]  # Default to 5 if no numbers found
    days = int(nums[0])
    if "week" in duration_str.lower():
        days *= 7
    if days <= 0 or days > 90:
        return []

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
    except Exception:
        return []

    qty_label = f" — {quantity_per_dose}" if quantity_per_dose else ""
    disease_label = f" ({disease})" if disease else ""
    crop_label = f" [{crop}]" if crop else ""
    product_label = product_id or "treatment"
    if product_id:
        record = get_product_by_id(product_id)
        if record:
            product_label = record.english_name or record.product_name or record.product_id

    tasks = []
    for i in range(days):
        day_date = start + timedelta(days=i)
        tasks.append({
            "day": i + 1,
            "date": day_date.strftime("%Y-%m-%d"),
            "task": f"Apply {product_label}{qty_label}{disease_label}{crop_label}",
            "done": False,
        })
    return tasks


def add_treatment(
    session_id: str,
    external_id: Optional[str],
    *,
    start_date: str,
    crop: Optional[str] = None,
    disease: Optional[str] = None,
    product_id: Optional[str] = None,
    duration: Optional[str] = None,
    instructions: Optional[str] = None,
    quantity_per_dose: Optional[str] = None,
) -> dict:
    """Record an active treatment so the next session can proactively check in."""
    import json as _json
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        # Build per-day tasks automatically
        tasks = _generate_daily_tasks(
            start_date=start_date,
            duration_str=duration,
            product_id=product_id,
            quantity_per_dose=quantity_per_dose,
            crop=crop,
            disease=disease,
        )
        treatment = Treatment(
            customer_id=customer_id,
            session_id=session_id,
            start_date=start_date,
            crop=crop,
            disease=disease,
            product_id=product_id,
            duration=duration,
            instructions=instructions,
            quantity_per_dose=quantity_per_dose,
            daily_tasks=_json.dumps(tasks, ensure_ascii=False) if tasks else None,
            status="active",
        )
        db.add(treatment)
        db.commit()
        db.refresh(treatment)
        return _treatment_to_dict(treatment)
    finally:
        db.close()


def mark_task_done(session_id: str, external_id: Optional[str], treatment_id: int, day: int) -> dict:
    """Toggle the done state for a specific day in a treatment's daily_tasks list."""
    import json as _json
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        treatment = db.scalars(
            select(Treatment).where(
                Treatment.id == treatment_id,
                Treatment.customer_id == customer_id,
            )
        ).first()
        if treatment is None:
            raise ValueError(f"Treatment {treatment_id} not found.")
        tasks = _json.loads(treatment.daily_tasks or "[]")
        for t in tasks:
            if t.get("day") == day:
                t["done"] = not t.get("done", False)
                break
        treatment.daily_tasks = _json.dumps(tasks, ensure_ascii=False)
        # Auto-complete treatment when all tasks done
        if tasks and all(t.get("done") for t in tasks):
            treatment.status = "completed"
        db.commit()
        db.refresh(treatment)
        return _treatment_to_dict(treatment)
    finally:
        db.close()


def get_active_treatments(session_id: str, external_id: Optional[str]) -> list[dict]:
    """Return active treatment plans for purchased/shipped products only."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        ordered_product_ids = (
            select(Order.product_id)
            .where(
                Order.customer_id == customer_id,
                Order.product_id.is_not(None),
                Order.status.in_(TREATMENT_ORDER_STATUSES),
            )
        )
        rows = db.scalars(
            select(Treatment)
            .where(
                Treatment.customer_id == customer_id,
                Treatment.status == "active",
                Treatment.product_id.in_(ordered_product_ids),
            )
            .order_by(Treatment.id.desc())
        ).all()
        return [_treatment_to_dict(t) for t in rows]
    finally:
        db.close()


def get_todays_tasks(session_id: str, external_id: Optional[str]) -> list[dict]:
    """Return pending tasks for today across all active treatments."""
    from datetime import date
    today_str = date.today().strftime("%Y-%m-%d")
    treatments = get_active_treatments(session_id, external_id)
    todays = []
    for tr in treatments:
        for task in tr.get("daily_tasks", []):
            if task.get("date") == today_str and not task.get("done"):
                todays.append({
                    "treatment_id": tr["id"],
                    "crop": tr.get("crop"),
                    "disease": tr.get("disease"),
                    "product_id": tr.get("product_id"),
                    **task,
                })
    return todays
def create_escalation(
    session_id: str,
    external_id=None,
    *,
    risk_category: str,
    triggered_phrase: str,
    human_summary: str,
) -> dict:
    from db.engine import SessionLocal
    from db.models import Escalation

    db = SessionLocal()
    try:
        escalation = Escalation(
            session_id=session_id,
            risk_category=risk_category,
            triggered_phrase=triggered_phrase,
            human_summary=human_summary,
            resolved=False,
        )

        db.add(escalation)
        db.commit()
        db.refresh(escalation)

        return {
            "id": escalation.id,
            "session_id": escalation.session_id,
            "risk_category": escalation.risk_category,
            "resolved": escalation.resolved,
        }
    finally:
        db.close()
