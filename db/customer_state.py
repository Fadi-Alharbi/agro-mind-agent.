"""
db/customer_state.py
────────────────────
Transactional helpers for customer-facing state that spans chat, diagnosis,
cart, orders, and follow-ups.
"""

from __future__ import annotations

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
from memory.customer_memory import CustomerMemory
from rag.catalog_loader import get_product_by_id


def _ensure_customer(session_id: str, external_id: Optional[str]) -> int:
    """Ensure the customer/session rows exist and return customer_id."""
    memory = CustomerMemory(session_id, external_id=external_id)
    if not memory.customer_id:
        raise ValueError("Could not resolve customer for session.")
    return memory.customer_id


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


def checkout_cart(session_id: str, external_id: Optional[str]) -> dict:
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

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        orders: list[Order] = []
        for idx, item in enumerate(cart.items, start=1):
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
    return {
        "id": message.id,
        "session_id": message.session_id,
        "role": message.role,
        "content": message.content,
        "intent": message.intent,
        "has_image": message.has_image,
        "attachments": attachments,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def get_chat_history(
    session_id: str,
    external_id: Optional[str],
    limit: int = 80,
    *,
    include_images: bool = False,
) -> dict:
    """Return recent message history across all sessions for a customer."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        session_ids = list(
            db.scalars(select(DBSession.id).where(DBSession.customer_id == customer_id)).all()
        )
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


def login_customer(username: str, password: str, session_id: str) -> dict:
    """Resolve an existing customer or create a new local customer identity."""
    username = (username or "").strip()
    password = (password or "").strip()
    if not username:
        raise ValueError("Username is required.")
    if password != "123456":
        raise PermissionError("Invalid password.")

    external_id = username if ":" in username else f"demo:{username.lower()}"
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
            customer = Customer(external_id=external_id, name=username)
            db.add(customer)
            db.flush()
        if not customer.external_id:
            customer.external_id = external_id
        db_session = db.get(DBSession, session_id)
        if db_session is None:
            db.add(DBSession(id=session_id, customer_id=customer.id))
        else:
            db_session.customer_id = customer.id
        db.commit()
        return {
            "id": customer.id,
            "external_id": customer.external_id,
            "username": _display_username(customer),
            "name": customer.name or "",
            "location": customer.location or "",
            "crop_type": customer.crop_type or "",
            "created_at": customer.created_at.isoformat() if customer.created_at else None,
        }
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
        unit_price = product.group_price if is_group_buy else product.single_price
        if item:
            item.quantity += max(1, quantity)
            item.unit_price = unit_price
        else:
            db.add(CartItem(
                cart_id=cart.id,
                product_id=product_id,
                quantity=max(1, quantity),
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
    return {
        "id": t.id,
        "start_date": t.start_date,
        "crop": t.crop,
        "disease": t.disease,
        "product_id": t.product_id,
        "duration": t.duration,
        "instructions": t.instructions,
        "status": t.status,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


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
) -> dict:
    """Record an active treatment so the next session can proactively check in."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        treatment = Treatment(
            customer_id=customer_id,
            session_id=session_id,
            start_date=start_date,
            crop=crop,
            disease=disease,
            product_id=product_id,
            duration=duration,
            instructions=instructions,
            status="active",
        )
        db.add(treatment)
        db.commit()
        db.refresh(treatment)
        return _treatment_to_dict(treatment)
    finally:
        db.close()


def get_active_treatments(session_id: str, external_id: Optional[str]) -> list[dict]:
    """Return the customer's active treatments across all of their sessions."""
    customer_id = _ensure_customer(session_id, external_id)
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(Treatment)
            .where(Treatment.customer_id == customer_id, Treatment.status == "active")
            .order_by(Treatment.id.desc())
        ).all()
        return [_treatment_to_dict(t) for t in rows]
    finally:
        db.close()
