"""
db/models.py
────────────
SQLAlchemy ORM models for Agro-Mind — the relational schema described in
docs/DATABASE_PLAN.md.

Relationships:
    customers ──< sessions ──< messages
        │
        ├──< orders ──< refunds
        │       └──> products (FK)
        ├──< follow_ups
        └──< escalations  (via session)
"""

from __future__ import annotations

from datetime import datetime, timezone

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

from db.engine import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Customers ───────────────────────────────────────────────────────────────────
class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    crop_type: Mapped[str | None] = mapped_column(String(128))
    last_recommended_product: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    sessions: Mapped[list["Session"]] = relationship(back_populates="customer")
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")
    follow_ups: Mapped[list["FollowUp"]] = relationship(back_populates="customer")


# ── Sessions ──────────────────────────────────────────────────────────────────
class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # UUID
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    last_intent: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_active: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    customer: Mapped["Customer"] = relationship(back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


# ── Messages ──────────────────────────────────────────────────────────────────
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(64))
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    session: Mapped["Session"] = relationship(back_populates="messages")


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


# ── Orders ────────────────────────────────────────────────────────────────────
class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # 'ORD-2026-0001'
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    is_group_buy: Mapped[bool] = mapped_column(Boolean, default=False)
    # pending | paid | packed | shipped | out_for_delivery | delivered | cancelled
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    customer: Mapped["Customer"] = relationship(back_populates="orders")
    product: Mapped["Product"] = relationship(back_populates="orders")
    refunds: Mapped[list["Refund"]] = relationship(back_populates="order")


# ── Refunds ───────────────────────────────────────────────────────────────────
class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    reason: Mapped[str | None] = mapped_column(String(255))
    # approved | under_review | rejected
    status: Mapped[str] = mapped_column(String(32), default="under_review")
    return_required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    order: Mapped["Order"] = relationship(back_populates="refunds")


# ── Escalations (safety) ────────────────────────────────────────────────────────
class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"), index=True)
    risk_category: Mapped[str | None] = mapped_column(String(64))
    triggered_phrase: Mapped[str | None] = mapped_column(String(512))
    human_summary: Mapped[str | None] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ── Follow-ups (proactive re-engagement — Proposal slide 7) ──────────────────────
class FollowUp(Base):
    __tablename__ = "follow_ups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"))
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    # pending | sent | answered | cancelled
    status: Mapped[str] = mapped_column(String(32), default="pending")
    result_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    customer: Mapped["Customer"] = relationship(back_populates="follow_ups")
