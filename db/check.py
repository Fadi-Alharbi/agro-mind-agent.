"""
db/check.py
───────────
Health-check / verification script for the Agro-Mind database.

Run any time to confirm the DB is reachable and correctly set up:
    python -m db.check

Checks, in order:
  1. Connection works (and which backend / version)
  2. All expected tables exist
  3. Row counts per table
  4. Sample product rows
"""

from __future__ import annotations

from sqlalchemy import func, inspect, select, text

from db.engine import SessionLocal, _is_mysql, _safe_url, engine, init_db
from db.models import (
    Cart,
    CartItem,
    Customer,
    Diagnosis,
    Escalation,
    FollowUp,
    Message,
    Order,
    Product,
    Refund,
    Session,
)

EXPECTED_TABLES = {
    "customers", "sessions", "messages", "products",
    "orders", "refunds", "escalations", "follow_ups",
    "diagnoses", "carts", "cart_items",
}

MODELS = [
    Customer, Session, Message, Product, Diagnosis, Cart, CartItem,
    Order, Refund, Escalation, FollowUp,
]


def main() -> None:
    print(f"🔌 Connecting to: {_safe_url()}\n")

    # 1. Connection + version
    try:
        with engine.connect() as conn:
            if _is_mysql:
                ver = conn.execute(text("SELECT VERSION()")).scalar()
                print(f"✅ Connected — MySQL {ver}")
            else:
                print("✅ Connected — SQLite")
    except Exception as exc:
        print(f"❌ Connection FAILED: {exc}")
        return

    # 2. Ensure tables + compare against expected set
    init_db()
    found = set(inspect(engine).get_table_names())
    missing = EXPECTED_TABLES - found
    print(f"\n📋 Tables found: {sorted(found & EXPECTED_TABLES)}")
    if missing:
        print(f"❌ MISSING tables: {sorted(missing)}")
    else:
        print(f"✅ All {len(EXPECTED_TABLES)} expected tables present")

    # 3. Row counts
    print("\n📊 Row counts:")
    session = SessionLocal()
    try:
        for model in MODELS:
            n = session.scalar(select(func.count()).select_from(model))
            print(f"   {model.__tablename__:<14} {n}")

        # 4. Sample products
        sample = session.scalars(select(Product).limit(5)).all()
        if sample:
            print("\n🌿 Sample products:")
            for p in sample:
                print(f"   [{p.id}] {p.english_name:<35} group ¥{p.group_price:.0f} / single ¥{p.single_price:.0f}")
        else:
            print("\n⚠️  products table is EMPTY — run:  python -m db.seed")
    finally:
        session.close()

    print("\n✅ Check complete.")


if __name__ == "__main__":
    main()
