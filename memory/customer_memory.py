"""
memory/customer_memory.py
─────────────────────────
Per-session customer memory, backed by the relational database
(sessions / messages / customers tables).

The public interface is unchanged from the old JSON version — the agent
orchestrator calls it the same way — but data now lives in MySQL/SQLite
instead of memory/sessions/<id>.json files.

Design notes:
  • Each method opens and closes its own DB session, so it is safe to call
    from the async memory-update background task.
  • One Customer row is created per chat session for now. Linking a returning
    customer across sessions (via external_id) is Phase-2 step C2.
  • "Recent issues" are derived from messages whose intent == 'diagnosis',
    instead of a separate infestation_history list.
"""

from __future__ import annotations

import base64
from typing import Optional

from sqlalchemy import func, select

from db.customer_state import (
    format_pesticide_memory_lines,
    get_pesticide_memory_for_customer,
)
from db.engine import SessionLocal
from db.models import Customer, Message, MessageAttachment, Session as DBSession


class CustomerMemory:
    """Per-session memory persisted to the database."""

    def __init__(self, session_id: str, external_id: Optional[str] = None) -> None:
        self.session_id = session_id
        self.external_id = external_id
        self.customer_id: Optional[int] = None
        self._ensure_session()

    # ── Setup ──────────────────────────────────────────────────────────────────

    def _ensure_session(self) -> None:
        """Attach this session to the right Customer, creating rows as needed.

        Cross-session memory hinges here: when an external_id is supplied we
        look up the existing Customer and reuse it, so a returning user's
        profile (crop, location, history) carries across chats. Without an
        external_id we fall back to an anonymous, per-session Customer.
        """
        db = SessionLocal()
        try:
            sess = db.get(DBSession, self.session_id)
            if sess is not None:
                self.customer_id = sess.customer_id
                return

            customer = None
            if self.external_id:
                customer = db.scalars(
                    select(Customer).where(Customer.external_id == self.external_id)
                ).first()
            if customer is None:
                customer = Customer(external_id=self.external_id)
                db.add(customer)
                db.flush()  # assign customer.id

            sess = DBSession(id=self.session_id, customer_id=customer.id)
            db.add(sess)
            db.commit()
            self.customer_id = customer.id
        finally:
            db.close()

    def _customer_session_ids(self, db) -> list[str]:
        """All session ids for this customer — the span of cross-chat memory."""
        if not self.customer_id:
            return [self.session_id]
        return list(
            db.scalars(
                select(DBSession.id).where(DBSession.customer_id == self.customer_id)
            ).all()
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def update(
        self,
        crop_type: Optional[str] = None,
        location: Optional[str] = None,
        infestation_note: Optional[str] = None,
        last_product_id: Optional[str] = None,
        last_intent: Optional[str] = None,
    ) -> None:
        """Merge new information into the customer/session records."""
        db = SessionLocal()
        try:
            customer = db.get(Customer, self.customer_id) if self.customer_id else None
            sess = db.get(DBSession, self.session_id)

            if customer:
                if crop_type:
                    customer.crop_type = crop_type
                if location:
                    customer.location = location
                if last_product_id:
                    customer.last_recommended_product = last_product_id

            if sess and last_intent:
                sess.last_intent = last_intent

            # infestation_note marks the latest user turn as a diagnosis, so it
            # surfaces under "Recent issues" without a separate history table.
            if infestation_note and sess:
                latest_user_msg = db.scalars(
                    select(Message)
                    .where(Message.session_id == self.session_id, Message.role == "user")
                    .order_by(Message.id.desc())
                    .limit(1)
                ).first()
                if latest_user_msg:
                    latest_user_msg.intent = "diagnosis"

            db.commit()
        finally:
            db.close()

    def get_context_string(self) -> str:
        """Return a compact context string to inject into the LLM prompt."""
        db = SessionLocal()
        try:
            customer = db.get(Customer, self.customer_id) if self.customer_id else None
            # Recent issues span ALL of this customer's sessions, so a new chat
            # recalls diagnoses from previous chats — the "profile across chats".
            customer_sessions = self._customer_session_ids(db)
            recent_issues = db.scalars(
                select(Message.content)
                .where(Message.session_id.in_(customer_sessions), Message.intent == "diagnosis")
                .order_by(Message.id.desc())
                .limit(3)
            ).all()
            interaction_count = db.scalar(
                select(func.count(Message.id)).where(Message.session_id.in_(customer_sessions))
            )
            returning = len(customer_sessions) > 1

            parts: list[str] = ["[Customer Profile]"]
            if returning:
                parts.append(f"- Returning customer ({len(customer_sessions)} chats)")
            if customer and customer.crop_type:
                parts.append(f"- Crop: {customer.crop_type}")
            if customer and customer.location:
                parts.append(f"- Location: {customer.location}")
            if customer and customer.last_recommended_product:
                parts.append(f"- Last recommended product: {customer.last_recommended_product}")
            if recent_issues:
                parts.append(f"- Recent issues: {'; '.join(i[:120] for i in recent_issues)}")
            if interaction_count:
                parts.append(f"- Total interactions: {interaction_count}")
            pesticide_memory = get_pesticide_memory_for_customer(db, self.customer_id)
            parts.extend(format_pesticide_memory_lines(pesticide_memory))

            return "\n".join(parts) if len(parts) > 1 else ""
        finally:
            db.close()

    def chat_history(self) -> list[dict]:
        """Return the stored conversation turns (list of {role, text} dicts)."""
        db = SessionLocal()
        try:
            rows = db.scalars(
                select(Message)
                .where(Message.session_id == self.session_id)
                .order_by(Message.id.asc())
            ).all()
            return [
                {"role": m.role, "text": m.content, "ts": m.created_at.isoformat()}
                for m in rows
            ]
        finally:
            db.close()

    def append_turn(
        self,
        role: str,
        text: str,
        *,
        has_image: bool = False,
        image_base64: Optional[str] = None,
        image_mime_type: str = "image/jpeg",
    ) -> int:
        """Append a conversation turn to the message history."""
        db = SessionLocal()
        try:
            message = Message(
                session_id=self.session_id,
                role=role,
                content=text,
                has_image=has_image or bool(image_base64),
            )
            db.add(message)
            db.flush()
            if image_base64:
                try:
                    size_bytes = len(base64.b64decode(image_base64))
                except Exception:
                    size_bytes = len(image_base64)
                db.add(MessageAttachment(
                    message_id=message.id,
                    mime_type=image_mime_type,
                    data_base64=image_base64,
                    size_bytes=size_bytes,
                ))
            db.commit()
            return message.id
        finally:
            db.close()

    def load(self) -> dict:
        """Return a snapshot of the customer profile (compatibility helper)."""
        db = SessionLocal()
        try:
            customer = db.get(Customer, self.customer_id) if self.customer_id else None
            if not customer:
                return {}
            return {
                "crop_type": customer.crop_type,
                "location": customer.location,
                "last_recommended_product": customer.last_recommended_product,
                "pesticide_memory": get_pesticide_memory_for_customer(db, self.customer_id),
            }
        finally:
            db.close()
