"""
memory/customer_memory.py
─────────────────────────
Per-session customer memory stored as JSON files.
The agent reads existing context at the start of each turn and writes
updated context at the end.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Storage directory ──────────────────────────────────────────────────────────
_MEMORY_DIR = Path(os.getenv("MEMORY_DIR", "memory/sessions"))


def _session_path(session_id: str) -> Path:
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return _MEMORY_DIR / f"{session_id}.json"


class CustomerMemory:
    """
    Lightweight per-session memory.  Persists to memory/sessions/<session_id>.json.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._path = _session_path(session_id)
        self._data: dict = self._load()

    # ── Public API ─────────────────────────────────────────────────────────────

    def load(self) -> dict:
        """Return the current memory snapshot."""
        return dict(self._data)

    def update(
        self,
        crop_type: Optional[str] = None,
        location: Optional[str] = None,
        infestation_note: Optional[str] = None,
        last_product_id: Optional[str] = None,
        last_intent: Optional[str] = None,
    ) -> None:
        """Merge new information into the session record and persist."""
        now = datetime.now(timezone.utc).isoformat()

        if crop_type:
            self._data["crop_type"] = crop_type
        if location:
            self._data["location"] = location
        if infestation_note:
            history: list[str] = self._data.setdefault("infestation_history", [])
            entry = f"[{now[:10]}] {infestation_note}"
            if entry not in history:
                history.append(entry)
        if last_product_id:
            self._data["last_recommended_product"] = last_product_id
        if last_intent:
            self._data["last_intent"] = last_intent

        self._data["last_interaction"] = now
        self._data["interaction_count"] = self._data.get("interaction_count", 0) + 1

        self._persist()

    def get_context_string(self) -> str:
        """
        Return a compact context string to inject into the LLM prompt.
        Empty string if no history exists yet.
        """
        if not self._data:
            return ""

        parts: list[str] = ["[Customer Profile]"]
        if self._data.get("crop_type"):
            parts.append(f"- Crop: {self._data['crop_type']}")
        if self._data.get("location"):
            parts.append(f"- Location: {self._data['location']}")
        if self._data.get("last_recommended_product"):
            parts.append(f"- Last recommended product: {self._data['last_recommended_product']}")
        if self._data.get("infestation_history"):
            recent = self._data["infestation_history"][-3:]
            parts.append(f"- Recent issues: {'; '.join(recent)}")
        if self._data.get("interaction_count"):
            parts.append(f"- Interactions this session: {self._data['interaction_count']}")

        return "\n".join(parts) if len(parts) > 1 else ""

    def chat_history(self) -> list[dict]:
        """Return the stored conversation turns (list of {role, text} dicts)."""
        return list(self._data.get("chat_history", []))

    def append_turn(self, role: str, text: str) -> None:
        """Append a conversation turn to history (kept last 20 turns)."""
        history: list[dict] = self._data.setdefault("chat_history", [])
        history.append({"role": role, "text": text, "ts": datetime.now(timezone.utc).isoformat()})
        # Keep memory bounded
        if len(history) > 20:
            self._data["chat_history"] = history[-20:]
        self._persist()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _persist(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass  # Non-fatal if memory can't be written
