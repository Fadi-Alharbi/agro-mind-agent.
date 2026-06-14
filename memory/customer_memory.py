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

from typing import Optional

from sqlalchemy import func, select

from db.engine import SessionLocal
from db.models import Customer, Message, Session as DBSession


class CustomerMemory:
    """Per-session memory persisted to the database."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.customer_id: Optional[int] = None
        self._ensure_session()

    # ── Setup ──────────────────────────────────────────────────────────────────

    def _ensure_session(self) -> None:
        """Create the Session (and its Customer) row if it doesn't exist yet."""
        db = SessionLocal()
        try:
            sess = db.get(DBSession, self.session_id)
            if sess is None:
                customer = Customer()  # anonymous for now (external_id=None)
                db.add(customer)
                db.flush()  # assign customer.id
                sess = DBSession(id=self.session_id, customer_id=customer.id)
                db.add(sess)
                db.commit()
                self.customer_id = customer.id
            else:
                self.customer_id = sess.customer_id
        finally:
            db.close()

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
            recent_issues = db.scalars(
                select(Message.content)
                .where(Message.session_id == self.session_id, Message.intent == "diagnosis")
                .order_by(Message.id.desc())
                .limit(3)
            ).all()
            interaction_count = db.scalar(
                select(func.count(Message.id)).where(Message.session_id == self.session_id)
            )

            parts: list[str] = ["[Customer Profile]"]
            if customer and customer.crop_type:
                parts.append(f"- Crop: {customer.crop_type}")
            if customer and customer.location:
                parts.append(f"- Location: {customer.location}")
            if customer and customer.last_recommended_product:
                parts.append(f"- Last recommended product: {customer.last_recommended_product}")
            if recent_issues:
                parts.append(f"- Recent issues: {'; '.join(i[:120] for i in recent_issues)}")
            if interaction_count:
                parts.append(f"- Interactions this session: {interaction_count}")

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

    def append_turn(self, role: str, text: str) -> None:
        """Append a conversation turn to the message history."""
        db = SessionLocal()
        try:
            db.add(Message(session_id=self.session_id, role=role, content=text))
            db.commit()
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
            }
        finally:
            db.close()
