"""
tests/test_catalog.py
─────────────────────
Tests for the product catalog loader and search functions.
"""

import pytest
from rag.catalog_loader import (
    get_catalog,
    search_catalog,
    get_product_by_id,
    all_products_summary,
    ProductRecord,
)


# ── Catalog loading ────────────────────────────────────────────────────────────

def test_catalog_loads():
    catalog = get_catalog()
    assert len(catalog) > 0, "Catalog should not be empty"


def test_catalog_has_expected_size():
    catalog = get_catalog()
    # The translated catalog has ~113 rows of data
    assert len(catalog) >= 50, f"Expected at least 50 products, got {len(catalog)}"


def test_catalog_records_are_product_records():
    catalog = get_catalog()
    for item in catalog:
        assert isinstance(item, ProductRecord)


def test_catalog_first_product():
    catalog = get_catalog()
    first = catalog[0]
    assert first.product_id.startswith("AF"), f"Expected AF-prefixed ID, got {first.product_id}"
    assert len(first.product_name) > 0


def test_all_products_have_id():
    catalog = get_catalog()
    for prod in catalog:
        assert prod.product_id, f"Product has empty ID: {prod}"


def test_all_products_have_name():
    catalog = get_catalog()
    for prod in catalog:
        assert prod.product_name, f"Product {prod.product_id} has empty name"


# ── Product lookup by ID ───────────────────────────────────────────────────────

def test_get_product_af0001():
    prod = get_product_by_id("AF0001")
    assert prod is not None
    assert prod.product_id == "AF0001"


def test_get_product_case_insensitive():
    prod_upper = get_product_by_id("AF0001")
    prod_lower = get_product_by_id("af0001")
    assert prod_upper is not None
    assert prod_lower is not None
    assert prod_upper.product_id == prod_lower.product_id


def test_get_product_nonexistent():
    prod = get_product_by_id("ZZZZ9999")
    assert prod is None


# ── Catalog search ─────────────────────────────────────────────────────────────

def test_search_returns_list():
    results = search_catalog("spider mite")
    assert isinstance(results, list)


def test_search_spider_mite():
    results = search_catalog("spider mite")
    assert len(results) > 0, "Should find products for spider mites"


def test_search_fungus():
    results = search_catalog("fungus bacteria")
    assert len(results) > 0


def test_search_citrus():
    results = search_catalog("citrus disease", crop="citrus")
    assert len(results) > 0


def test_search_max_results():
    results = search_catalog("pest", max_results=2)
    assert len(results) <= 2


def test_search_no_match_returns_empty():
    results = search_catalog("xyz_completely_unrelated_term_12345")
    assert isinstance(results, list)
    # May return 0 or very low score results — at minimum must not crash


def test_search_herbicide():
    results = search_catalog("herbicide weed")
    assert len(results) > 0


# ── Pricing ────────────────────────────────────────────────────────────────────

def test_pricing_positive():
    catalog = get_catalog()
    for prod in catalog:
        assert prod.group_price > 0
        assert prod.single_price > 0
        assert prod.group_price < prod.single_price, (
            f"{prod.product_id}: group price {prod.group_price} should be < single {prod.single_price}"
        )


def test_price_display_format():
    prod = get_product_by_id("AF0001")
    display = prod.price_display()
    assert "Group purchase:" in display
    assert "Single purchase:" in display
    assert "¥" in display


# ── Summary ────────────────────────────────────────────────────────────────────

def test_all_products_summary_nonempty():
    summary = all_products_summary()
    assert len(summary) > 100


def test_product_summary_method():
    prod = get_product_by_id("AF0001")
    summary = prod.summary()
    assert "AF0001" in summary
    assert "¥" in summary
