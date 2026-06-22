"""
rag/catalog_loader.py
─────────────────────
Loads the product catalog from the translated XLSX and provides
keyword-based search functions used by the agent and tools.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import openpyxl

# ── Catalog location ──────────────────────────────────────────────────────────
_CATALOG_PATH = Path(__file__).parent.parent / (
    "tra/1/1.2/ProductCatalog_Translated_EN.xlsx"
)

# ── Pricing table (Group vs Single) for demonstration purposes ───────────────
# In a real PDD integration these would come from the live listing API.
# Prices are illustrative but realistic for the product types.
_PRICE_MAP: dict[str, tuple[float, float]] = {
    "AF0001": (28.0, 39.0), "AF0002": (26.0, 36.0), "AF0003": (24.0, 33.0),
    "AF0004": (22.0, 30.0), "AF0005": (29.0, 40.0), "AF0006": (25.0, 35.0),
    "AF0007": (27.0, 38.0), "AF0008": (23.0, 32.0), "AF0009": (21.0, 29.0),
    "AF0010": (32.0, 45.0), "AF0011": (26.0, 36.0), "AF0012": (24.0, 34.0),
    "AF0013": (18.0, 25.0), "AF0014": (17.0, 24.0), "AF0015": (19.0, 26.0),
    "AF0016": (31.0, 43.0), "AF0017": (28.0, 39.0), "AF0018": (22.0, 31.0),
    "AF0019": (20.0, 28.0), "AF0020": (34.0, 47.0),
}
_DEFAULT_PRICE = (25.0, 35.0)


@dataclass
class ProductRecord:
    product_id: str
    product_name: str
    english_name: str
    product_type: str
    crops: str
    specification: str
    main_ingredients: str
    how_to_use: str
    water_ratio: str           # "How to use (drink with water)" column
    group_price: float = 25.0
    single_price: float = 35.0

    def to_dict(self) -> dict:
        return asdict(self)

    def price_display(self) -> str:
        return f"Group purchase: ¥{self.group_price:.0f} | Single purchase: ¥{self.single_price:.0f}"

    def summary(self) -> str:
        return (
            f"[{self.product_id}] {self.product_name} ({self.product_type})\n"
            f"Crops: {self.crops}\n"
            f"Dosage: {self.water_ratio or self.how_to_use}\n"
            f"Ingredients: {self.main_ingredients}\n"
            f"{self.price_display()}"
        )


# ── Module-level catalog (loaded once at import) ───────────────────────────────
_CATALOG: list[ProductRecord] = []


def _load_catalog() -> list[ProductRecord]:
    """Parse the XLSX and return a list of ProductRecord objects."""
    records: list[ProductRecord] = []
    if not _CATALOG_PATH.exists():
        return records

    wb = openpyxl.load_workbook(str(_CATALOG_PATH), read_only=True, data_only=True)
    ws = wb.active

    for row in ws.iter_rows(min_row=2, values_only=True):
        pid, name, eng_name, ptype, _zh_instr, water_ratio, crops, spec, _src, ingredients, how_to = row

        if not pid:
            continue

        gp, sp = _PRICE_MAP.get(str(pid), _DEFAULT_PRICE)

        records.append(ProductRecord(
            product_id=str(pid).strip(),
            product_name=str(name or "").strip(),
            english_name=str(eng_name or "").strip(),
            product_type=str(ptype or "").strip(),
            crops=str(crops or "").strip(),
            specification=str(spec or "").strip(),
            main_ingredients=str(ingredients or "").strip(),
            how_to_use=str(how_to or "").strip(),
            water_ratio=str(water_ratio or "").strip(),
            group_price=gp,
            single_price=sp,
        ))

    wb.close()
    return records


def get_catalog() -> list[ProductRecord]:
    """Return the module-level catalog, loading it if necessary."""
    global _CATALOG
    if not _CATALOG:
        _CATALOG = _load_catalog()
    return _CATALOG


def search_catalog(
    query: str,
    crop: Optional[str] = None,
    max_results: int = 3,
) -> list[ProductRecord]:
    """
    Keyword search across product name, crops, ingredients, and how-to-use fields.
    Optionally filter by crop name. Returns up to `max_results` records.
    """
    catalog = get_catalog()
    query_tokens = set(re.findall(r"\w+", query.lower()))
    crop_tokens = set(re.findall(r"\w+", crop.lower())) if crop else set()

    scored: list[tuple[int, ProductRecord]] = []

    for rec in catalog:
        searchable = " ".join([
            rec.product_name,
            rec.english_name,
            rec.product_type,
            rec.crops,
            rec.main_ingredients,
            rec.how_to_use,
        ]).lower()

        tokens = set(re.findall(r"\w+", searchable))
        score = len(query_tokens & tokens)

        if crop_tokens:
            crop_score = len(crop_tokens & tokens)
            if crop_score == 0:
                continue          # hard filter: must match crop
            score += crop_score * 2   # boost crop matches

        if score > 0:
            scored.append((score, rec))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:max_results]]


def get_product_by_id(product_id: str) -> Optional[ProductRecord]:
    """Look up a single product by its ID (e.g. 'AF0001')."""
    for rec in get_catalog():
        if rec.product_id.upper() == product_id.upper():
            return rec
    return None


def all_products_summary() -> str:
    """Return a compact text listing of all products (for system prompt injection)."""
    lines = []
    for rec in get_catalog():
        lines.append(
            f"{rec.product_id} | {rec.product_name} | {rec.product_type} | "
            f"Crops: {rec.crops[:80]} | Dosage: {rec.water_ratio}"
        )
    return "\n".join(lines)


# Pre-load at import time
get_catalog()
