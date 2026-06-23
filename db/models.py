"""
db/models.py
────────────
SQLAlchemy ORM models for Agro-Mind — the relational schema described in
docs/DATABASE_PLAN.md.

Relationships:
    customers ──< sessions ──< messages
        │
        ├──< diagnoses
        ├──< carts ──< cart_items
        ├──< orders ──< refunds
        │       └──> products (FK)
        ├──< follow_ups
        └──< escalations  (via session)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from datetime import datetime
from db.engine import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Customers ───────────────────────────────────────────────────────────────────
class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    location: Mapped[Optional[str]] = mapped_column(String(255))
    crop_type: Mapped[Optional[str]] = mapped_column(String(128))
    last_recommended_product: Mapped[Optional[str]] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    sessions: Mapped[list["Session"]] = relationship(back_populates="customer")
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")
    follow_ups: Mapped[list["FollowUp"]] = relationship(back_populates="customer")
    diagnoses: Mapped[list["Diagnosis"]] = relationship(back_populates="customer")
    carts: Mapped[list["Cart"]] = relationship(back_populates="customer")
    treatments: Mapped[list["Treatment"]] = relationship(back_populates="customer")


# ── Sessions ──────────────────────────────────────────────────────────────────
class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # UUID
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), index=True)
    last_intent: Mapped[Optional[str]] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_active: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    customer: Mapped["Customer"] = relationship(back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    diagnoses: Mapped[list["Diagnosis"]] = relationship(back_populates="session")


# ── Messages ──────────────────────────────────────────────────────────────────
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[Optional[str]] = mapped_column(String(64))
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    session: Mapped["Session"] = relationship(back_populates="messages")
    diagnosis: Mapped[Optional["Diagnosis"]] = relationship(back_populates="message")
    attachments: Mapped[list["MessageAttachment"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class MessageAttachment(Base):
    __tablename__ = "message_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    mime_type: Mapped[str] = mapped_column(String(128), default="image/jpeg")
    data_base64: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    message: Mapped["Message"] = relationship(back_populates="attachments")


# ── Products ──────────────────────────────────────────────────────────────────
class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 'AF0001'
    product_name: Mapped[str] = mapped_column(String(512), default="")
    english_name: Mapped[str] = mapped_column(String(512), default="")
    product_type: Mapped[str] = mapped_column(String(255), default="")
    crops: Mapped[str] = mapped_column(Text, default="")
    specification: Mapped[str] = mapped_column(String(512), default="")
    main_ingredients: Mapped[str] = mapped_column(Text, default="")
    how_to_use: Mapped[str] = mapped_column(Text, default="")
    water_ratio: Mapped[str] = mapped_column(Text, default="")
    group_price: Mapped[float] = mapped_column(Float, default=25.0)
    single_price: Mapped[float] = mapped_column(Float, default=35.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    orders: Mapped[list["Order"]] = relationship(back_populates="product")
    diagnoses: Mapped[list["Diagnosis"]] = relationship(back_populates="recommended_product")
    cart_items: Mapped[list["CartItem"]] = relationship(back_populates="product")


# ── Diagnoses / crop issues ───────────────────────────────────────────────────
class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    session_id: Mapped[Optional[str]] = mapped_column(ForeignKey("sessions.id"), index=True)
    message_id: Mapped[Optional[int]] = mapped_column(ForeignKey("messages.id"), index=True)
    crop_type: Mapped[Optional[str]] = mapped_column(String(128))
    problem_summary: Mapped[str] = mapped_column(Text, default="")
    diagnosis_text: Mapped[str] = mapped_column(Text, default="")
    symptoms: Mapped[Optional[str]] = mapped_column(Text)
    # low | medium | high | critical | unknown
    severity: Mapped[str] = mapped_column(String(32), default="unknown")
    recommended_product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("products.id"))
    # open | monitoring | resolved | escalated
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    customer: Mapped["Customer"] = relationship(back_populates="diagnoses")
    session: Mapped[Optional["Session"]] = relationship(back_populates="diagnoses")
    message: Mapped[Optional["Message"]] = relationship(back_populates="diagnosis")
    recommended_product: Mapped[Optional["Product"]] = relationship(back_populates="diagnoses")
    cart_items: Mapped[list["CartItem"]] = relationship(back_populates="diagnosis")
    orders: Mapped[list["Order"]] = relationship(back_populates="diagnosis")
    follow_ups: Mapped[list["FollowUp"]] = relationship(back_populates="diagnosis")


# ── Carts ─────────────────────────────────────────────────────────────────────
class Cart(Base):
    __tablename__ = "carts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    session_id: Mapped[Optional[str]] = mapped_column(ForeignKey("sessions.id"), index=True)
    # active | converted | abandoned | cleared
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    customer: Mapped["Customer"] = relationship(back_populates="carts")
    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart", cascade="all, delete-orphan"
    )


class CartItem(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    is_group_buy: Mapped[bool] = mapped_column(Boolean, default=True)
    # recommended | manual | follow_up
    source: Mapped[str] = mapped_column(String(32), default="manual")
    diagnosis_id: Mapped[Optional[int]] = mapped_column(ForeignKey("diagnoses.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    cart: Mapped["Cart"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship(back_populates="cart_items")
    diagnosis: Mapped[Optional["Diagnosis"]] = relationship(back_populates="cart_items")


# ── Orders ────────────────────────────────────────────────────────────────────
class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # 'ORD-2026-0001'
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), index=True)
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("products.id"))
    cart_id: Mapped[Optional[int]] = mapped_column(ForeignKey("carts.id"), index=True)
    diagnosis_id: Mapped[Optional[int]] = mapped_column(ForeignKey("diagnoses.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    is_group_buy: Mapped[bool] = mapped_column(Boolean, default=False)
    # pending | paid | packed | shipped | out_for_delivery | delivered | cancelled
    status: Mapped[str] = mapped_column(String(32), default="pending")
    tracking_number: Mapped[Optional[str]] = mapped_column(String(128))
    courier: Mapped[Optional[str]] = mapped_column(String(128))
    shipped_from: Mapped[Optional[str]] = mapped_column(String(255))
    estimated_delivery: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    customer: Mapped["Customer"] = relationship(back_populates="orders")
    product: Mapped["Product"] = relationship(back_populates="orders")
    diagnosis: Mapped[Optional["Diagnosis"]] = relationship(back_populates="orders")
    refunds: Mapped[list["Refund"]] = relationship(back_populates="order")


# ── Refunds ───────────────────────────────────────────────────────────────────
class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    reason: Mapped[Optional[str]] = mapped_column(String(255))
    # approved | under_review | rejected
    status: Mapped[str] = mapped_column(String(32), default="under_review")
    return_required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    order: Mapped["Order"] = relationship(back_populates="refunds")


# ── Escalations (safety) ────────────────────────────────────────────────────────
class Escalation(Base):
    __tablename__ = "escalations"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=False)
    risk_category = Column(String, nullable=False)
    triggered_phrase = Column(Text, nullable=True)
    human_summary = Column(Text, nullable=True)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# ── Follow-ups (proactive re-engagement) ──────────────────────
class FollowUp(Base):
    __tablename__ = "follow_ups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[Optional[str]] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("products.id"))
    diagnosis_id: Mapped[Optional[int]] = mapped_column(ForeignKey("diagnoses.id"), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    # pending | sent | answered | cancelled
    status: Mapped[str] = mapped_column(String(32), default="pending")
    result_note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    customer: Mapped["Customer"] = relationship(back_populates="follow_ups")
    diagnosis: Mapped[Optional["Diagnosis"]] = relationship(back_populates="follow_ups")


# ── Active treatments (Fadi's treatment tracking → proactive check-ins) ──────────
class Treatment(Base):
    """An ongoing treatment a customer is applying, used for the proactive
    INIT_SESSION greeting (recall crop/disease/product and elapsed days)."""

    __tablename__ = "treatments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    session_id: Mapped[Optional[str]] = mapped_column(ForeignKey("sessions.id"))
    start_date: Mapped[str] = mapped_column(String(32))  # YYYY-MM-DD
    crop: Mapped[Optional[str]] = mapped_column(String(128))
    disease: Mapped[Optional[str]] = mapped_column(String(255))
    # free string, not a FK — an LLM-extracted id may not exist in the catalog
    product_id: Mapped[Optional[str]] = mapped_column(String(32))
    duration: Mapped[Optional[str]] = mapped_column(String(128))
    instructions: Mapped[Optional[str]] = mapped_column(Text)
    quantity_per_dose: Mapped[Optional[str]] = mapped_column(String(128))   # e.g. "400-600g" or "50ml"
    daily_tasks: Mapped[Optional[str]] = mapped_column(Text)               # JSON list of daily task dicts
    # active | completed | cancelled
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    customer: Mapped["Customer"] = relationship(back_populates="treatments")
