"""
db/engine.py
────────────
Database engine + session factory for Agro-Mind.

Reads DATABASE_URL from the environment. Defaults to MySQL but works with
any SQLAlchemy-supported backend — switching to SQLite is a one-line change.

  MySQL    : mysql+pymysql://user:pass@host:3306/agro_mind
  SQLite   : sqlite:///db/agro_mind.db   (dev fallback)
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

logger = logging.getLogger("agro_mind")

# ── Connection URL ──────────────────────────────────────────────────────────────
# If DATABASE_URL is unset we fall back to a local SQLite file so the app still
# boots during development — but production/demo uses the MySQL URL from .env.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///db/agro_mind.db")
_engine_url = make_url(DATABASE_URL)

_is_mysql = DATABASE_URL.startswith("mysql")
_is_sqlite = DATABASE_URL.startswith("sqlite")

# ── Engine ────────────────────────────────────────────────────────────────────
# pool_pre_ping: silently reconnect if the cloud MySQL server dropped an idle
#   connection (common with managed/remote MySQL).
# pool_recycle:  recycle connections older than 1h to dodge server-side timeouts.
_engine_kwargs: dict = {"pool_pre_ping": True, "echo": False}
if _is_mysql:
    _engine_kwargs.update(pool_recycle=3600, pool_size=5, max_overflow=10)
    _engine_kwargs.setdefault("connect_args", {}).update({
        "connect_timeout": 5,
        "read_timeout": 5,
        "write_timeout": 5,
    })
    ssl_mode = _engine_url.query.get("ssl-mode")
    if ssl_mode is not None:
        _engine_url = _engine_url.difference_update_query(["ssl-mode"])
        if ssl_mode.upper() not in {"DISABLED", "PREFERRED"}:
            _engine_kwargs.setdefault("connect_args", {})["ssl"] = {}
elif _is_sqlite:
    # SQLite needs this flag to be used across threads (FastAPI/Streamlit).
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(_engine_url, **_engine_kwargs)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# ── Declarative base ────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """Base class all ORM models inherit from."""


def get_session():
    """
    Context-manager-friendly session.
    Usage:
        with get_session() as s:
            s.add(obj)
            s.commit()
    """
    return SessionLocal()


def init_db() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    from db import models  # noqa: F401 — ensure models are registered on Base

    Base.metadata.create_all(bind=engine)
    _migrate_existing_schema()
    backend = "MySQL" if _is_mysql else ("SQLite" if _is_sqlite else "DB")
    logger.info("🗄️  %s tables ready (%s)", backend, _safe_url())


def _migrate_existing_schema() -> None:
    """Add columns introduced after the first demo schema was created.

    SQLAlchemy's create_all creates missing tables but intentionally does not
    alter existing tables. This keeps local SQLite demos and MySQL deployments
    compatible without bringing in Alembic for the prototype.
    """
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    def has_column(table: str, column: str) -> bool:
        if table not in table_names:
            return False
        return any(col["name"] == column for col in inspector.get_columns(table))

    def add_column(table: str, column: str, ddl_type: str) -> None:
        if table not in table_names or has_column(table, column):
            return
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))

    int_nullable = "INTEGER NULL" if _is_mysql else "INTEGER"
    add_column("orders", "cart_id", int_nullable)
    add_column("orders", "diagnosis_id", int_nullable)
    add_column("orders", "tracking_number", "VARCHAR(128)")
    add_column("orders", "courier", "VARCHAR(128)")
    add_column("orders", "shipped_from", "VARCHAR(255)")
    add_column("orders", "estimated_delivery", "VARCHAR(64)")
    add_column("follow_ups", "diagnosis_id", int_nullable)
    add_column("customers", "password_hash", "VARCHAR(255)")
    add_column("sessions", "is_authenticated", "BOOLEAN DEFAULT 0")
    add_column("sessions", "ended_at", "DATETIME NULL" if _is_mysql else "DATETIME")
    # New treatment columns for daily task tracking
    add_column("treatments", "quantity_per_dose", "VARCHAR(128)")
    add_column("treatments", "daily_tasks", "TEXT")


def _safe_url() -> str:
    """Return the DB URL with the password masked, for safe logging."""
    if "@" in DATABASE_URL and "//" in DATABASE_URL:
        scheme, rest = DATABASE_URL.split("//", 1)
        if "@" in rest:
            creds, host = rest.split("@", 1)
            user = creds.split(":", 1)[0]
            return f"{scheme}//{user}:***@{host}"
    return DATABASE_URL
