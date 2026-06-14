"""
safety/escalation_log.py
────────────────────────
Persists safety escalations to the database.

Kept separate from interceptor.py on purpose: the interceptor stays a pure,
deterministic, DB-unaware scanner. This module is the single place that turns
a detected risk into a durable `escalations` row — so high-risk events are
never lost to a log line that scrolls away (Proposal slide 5/8).
"""

from __future__ import annotations

import logging

from db.engine import SessionLocal
from db.models import Escalation

logger = logging.getLogger("agro_mind")


def record_escalation(
    session_id: str,
    risk_category: str,
    triggered_phrase: str,
    human_summary: str,
) -> None:
    """Write one escalation row. Never raises — a logging failure must not
    block the safety response to a user in crisis."""
    db = SessionLocal()
    try:
        db.add(
            Escalation(
                session_id=session_id,
                risk_category=risk_category,
                triggered_phrase=triggered_phrase[:512],
                human_summary=human_summary,
                resolved=False,
            )
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001 — must stay non-fatal
        logger.error("Failed to persist escalation (non-fatal): %s", exc)
        db.rollback()
    finally:
        db.close()
