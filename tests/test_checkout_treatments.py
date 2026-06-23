from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import db.customer_state as customer_state
from db.engine import Base
from db.models import Treatment


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_recommendation_treatment_without_checkout_is_hidden(monkeypatch):
    SessionLocal = _session_factory()
    monkeypatch.setattr(customer_state, "SessionLocal", SessionLocal)

    login = customer_state.login_customer("alice", "alice-password", "active-session")
    customer_state.add_treatment(
        login["session_id"],
        None,
        start_date="2026-06-23",
        product_id="AF0001",
        duration="5 days",
    )

    assert customer_state.get_active_treatments(login["session_id"], None) == []


def test_checkout_without_consent_does_not_create_treatment(monkeypatch):
    SessionLocal = _session_factory()
    monkeypatch.setattr(customer_state, "SessionLocal", SessionLocal)

    login = customer_state.login_customer("alice", "alice-password", "active-session")
    customer_state.add_cart_item(
        login["session_id"],
        None,
        "AF0001",
        quantity=1,
        is_group_buy=False,
    )
    checkout = customer_state.checkout_cart(login["session_id"], None)
    treatments = customer_state.get_active_treatments(login["session_id"], None)

    assert checkout["orders"][0]["product_id"] == "AF0001"
    assert treatments == []

    db = SessionLocal()
    try:
        persisted = db.scalars(select(Treatment)).all()
        assert persisted == []
    finally:
        db.close()


def test_checkout_with_consent_creates_visible_treatment(monkeypatch):
    SessionLocal = _session_factory()
    monkeypatch.setattr(customer_state, "SessionLocal", SessionLocal)

    login = customer_state.login_customer("alice", "alice-password", "active-session")
    customer_state.add_cart_item(
        login["session_id"],
        None,
        "AF0001",
        quantity=1,
        is_group_buy=False,
    )
    checkout = customer_state.checkout_cart(
        login["session_id"],
        None,
        create_treatment_plan=True,
    )
    treatments = customer_state.get_active_treatments(login["session_id"], None)

    assert checkout["orders"][0]["product_id"] == "AF0001"
    assert len(treatments) == 1
    assert treatments[0]["product_id"] == "AF0001"
    assert treatments[0]["product_name"]
    assert len(treatments[0]["daily_tasks"]) == 5

    db = SessionLocal()
    try:
        persisted = db.scalars(select(Treatment)).all()
        assert len(persisted) == 1
        assert persisted[0].product_id == "AF0001"
    finally:
        db.close()
