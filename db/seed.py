"""
db/seed.py
──────────
One-time migration: load the translated product catalog (XLSX) into the
`products` table. Idempotent — re-running updates existing rows in place.

Run:
    python -m db.seed
"""

from __future__ import annotations

import logging

from db.engine import SessionLocal, init_db
from db.models import Product
from rag.catalog_loader import _load_catalog  # reuse the existing XLSX parser

logger = logging.getLogger("agro_mind")


def seed_products() -> int:
    """Upsert every catalog record into the products table. Returns row count."""
    init_db()
    records = _load_catalog()

    if not records:
        print("⚠️  No records parsed from XLSX — check the catalog path.")
        return 0

    session = SessionLocal()
    try:
        for rec in records:
            product = session.get(Product, rec.product_id) or Product(id=rec.product_id)
            product.product_name = rec.product_name
            product.english_name = rec.english_name
            product.product_type = rec.product_type
            product.crops = rec.crops
            product.specification = rec.specification
            product.main_ingredients = rec.main_ingredients
            product.how_to_use = rec.how_to_use
            product.water_ratio = rec.water_ratio
            product.group_price = rec.group_price
            product.single_price = rec.single_price
            product.active = True
            session.merge(product)

        session.commit()
        count = session.query(Product).count()
        print(f"✅ Seeded {count} products into the database.")
        return count
    finally:
        session.close()


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    seed_products()
