import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import db.customer_state as customer_state
from db.engine import Base
from db.models import Customer, Message, Session as DBSession


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_switching_users_does_not_reassign_existing_session(monkeypatch):
    SessionLocal = _session_factory()
    monkeypatch.setattr(customer_state, "SessionLocal", SessionLocal)

    alice = customer_state.login_customer("alice", "alice-password", "active-session")
    bob = customer_state.login_customer("bob", "bob-password", alice["session_id"])

    assert alice["session_id"] == "active-session"
    assert bob["session_id"] != alice["session_id"]
    assert bob["session_changed"] is True

    db = SessionLocal()
    try:
        alice_customer = db.scalars(
            select(Customer).where(Customer.external_id == "demo:alice")
        ).one()
        bob_customer = db.scalars(
            select(Customer).where(Customer.external_id == "demo:bob")
        ).one()
        alice_session = db.get(DBSession, alice["session_id"])
        bob_session = db.get(DBSession, bob["session_id"])

        assert alice_session.customer_id == alice_customer.id
        assert bob_session.customer_id == bob_customer.id
        assert alice_session.is_authenticated is True
        assert bob_session.is_authenticated is True
    finally:
        db.close()


def test_new_customer_session_keeps_same_customer(monkeypatch):
    SessionLocal = _session_factory()
    monkeypatch.setattr(customer_state, "SessionLocal", SessionLocal)

    login = customer_state.login_customer("alice", "alice-password", "active-session")
    new_session = customer_state.create_customer_session(login["session_id"])

    assert new_session["session_id"] != login["session_id"]
    assert new_session["id"] == login["id"]
    assert new_session["session_changed"] is True


def test_login_hashes_password_and_rejects_wrong_password(monkeypatch):
    SessionLocal = _session_factory()
    monkeypatch.setattr(customer_state, "SessionLocal", SessionLocal)

    customer_state.login_customer("alice", "alice-password", "active-session")

    db = SessionLocal()
    try:
        alice_customer = db.scalars(
            select(Customer).where(Customer.external_id == "demo:alice")
        ).one()
        assert alice_customer.password_hash
        assert alice_customer.password_hash != "alice-password"
        assert alice_customer.password_hash.startswith("pbkdf2_sha256$")
    finally:
        db.close()

    with pytest.raises(PermissionError, match="Invalid username or password"):
        customer_state.login_customer("alice", "wrong-password", "second-session")


def test_logout_invalidates_session(monkeypatch):
    SessionLocal = _session_factory()
    monkeypatch.setattr(customer_state, "SessionLocal", SessionLocal)

    login = customer_state.login_customer("alice", "alice-password", "active-session")
    logout = customer_state.logout_customer(login["session_id"])

    assert logout["logged_in"] is False
    assert logout["session_id"] != login["session_id"]

    db = SessionLocal()
    try:
        old_session = db.get(DBSession, login["session_id"])
        assert old_session.is_authenticated is False
        assert old_session.ended_at is not None
    finally:
        db.close()

    with pytest.raises(PermissionError, match="Login is required"):
        customer_state.require_authenticated_session(login["session_id"])

    with pytest.raises(PermissionError, match="Login is required"):
        customer_state.create_customer_session(login["session_id"])


def test_resume_session_restores_active_login(monkeypatch):
    SessionLocal = _session_factory()
    monkeypatch.setattr(customer_state, "SessionLocal", SessionLocal)

    login = customer_state.login_customer("alice", "alice-password", "active-session")
    resumed = customer_state.resume_session(login["session_id"])

    # Same identity, same session, and no rotation — the cookie just re-attaches.
    assert resumed["session_id"] == login["session_id"]
    assert resumed["id"] == login["id"]
    assert resumed["username"] == login["username"]
    assert resumed["session_changed"] is False


def test_resume_session_rejects_logged_out_session(monkeypatch):
    SessionLocal = _session_factory()
    monkeypatch.setattr(customer_state, "SessionLocal", SessionLocal)

    login = customer_state.login_customer("alice", "alice-password", "active-session")
    customer_state.logout_customer(login["session_id"])

    # Once logged out, the persisted cookie can no longer restore the session.
    with pytest.raises(PermissionError, match="Session is not active"):
        customer_state.resume_session(login["session_id"])


def test_resume_session_rejects_unknown_or_empty_session(monkeypatch):
    SessionLocal = _session_factory()
    monkeypatch.setattr(customer_state, "SessionLocal", SessionLocal)

    with pytest.raises(PermissionError):
        customer_state.resume_session("does-not-exist")
    with pytest.raises(PermissionError, match="Login is required"):
        customer_state.resume_session("")


def test_chat_history_defaults_to_current_session(monkeypatch):
    SessionLocal = _session_factory()
    monkeypatch.setattr(customer_state, "SessionLocal", SessionLocal)

    login = customer_state.login_customer("alice", "alice-password", "active-session")
    first_session_id = login["session_id"]
    db = SessionLocal()
    try:
        db.add(Message(session_id=first_session_id, role="user", content="first chat question"))
        db.add(Message(session_id=first_session_id, role="assistant", content="first chat answer"))
        db.commit()
    finally:
        db.close()

    second = customer_state.create_customer_session(first_session_id)
    second_session_id = second["session_id"]

    assert customer_state.get_chat_history(second_session_id, None)["messages"] == []

    all_history = customer_state.get_chat_history(
        second_session_id,
        None,
        all_sessions=True,
    )
    assert [m["content"] for m in all_history["messages"]] == [
        "first chat question",
        "first chat answer",
    ]
