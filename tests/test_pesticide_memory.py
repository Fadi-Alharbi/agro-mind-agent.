from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.customer_state as customer_state
import memory.customer_memory as customer_memory_module
from agent.orchestrator import AgroMindAgent, _NoopMemory
from db.engine import Base
from memory.customer_memory import CustomerMemory


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def SessionLocal(monkeypatch):
    factory = _session_factory()
    monkeypatch.setattr(customer_state, "SessionLocal", factory)
    monkeypatch.setattr(customer_memory_module, "SessionLocal", factory)
    return factory


def _tool_mock(return_value):
    mock = MagicMock()
    mock.invoke.return_value = return_value
    return mock


def test_customer_memory_remembers_pesticide_in_active_cart(SessionLocal):
    login = customer_state.login_customer("alice", "alice-password", "cart-session")
    customer_state.add_cart_item(
        login["session_id"],
        None,
        "PN0013",
        quantity=1,
        is_group_buy=False,
    )

    context = CustomerMemory(login["session_id"]).get_context_string()
    pesticide_memory = customer_state.get_pesticide_memory(login["session_id"], None)

    assert "Pesticides in active cart" in context
    assert "Current pesticide reference" in context
    assert "PN0013" in context
    assert pesticide_memory["current"]["state"] == "cart"
    assert pesticide_memory["current"]["product_id"] == "PN0013"


def test_customer_memory_remembers_shipped_pesticide_after_checkout(SessionLocal):
    login = customer_state.login_customer("alice", "alice-password", "ship-session")
    customer_state.add_cart_item(
        login["session_id"],
        None,
        "PN0013",
        quantity=1,
        is_group_buy=False,
    )
    checkout = customer_state.checkout_cart(login["session_id"], None)

    context = CustomerMemory(login["session_id"]).get_context_string()
    pesticide_memory = customer_state.get_pesticide_memory(login["session_id"], None)

    assert checkout["orders"][0]["status"] == "shipped"
    assert "Shipped pesticides" in context
    assert "PN0013" in context
    assert pesticide_memory["current"]["state"] == "shipped"
    assert pesticide_memory["current"]["product_id"] == "PN0013"


@pytest.mark.asyncio
async def test_usage_question_resolves_pesticide_from_cart_memory(SessionLocal):
    login = customer_state.login_customer("alice", "alice-password", "usage-session")
    customer_state.add_cart_item(
        login["session_id"],
        None,
        "PN0013",
        quantity=1,
        is_group_buy=False,
    )

    agent = AgroMindAgent()
    with patch("agent.orchestrator._session_memory", return_value=_NoopMemory()):
        with patch("agent.orchestrator.detect_escalation_risk", _tool_mock(False)):
            with patch("agent.orchestrator.classify_intent", _tool_mock("Product")):
                with patch("agent.orchestrator.update_customer_profile", _tool_mock(None)):
                    with patch("agent.orchestrator._save_treatment_in_background"):
                        result = await agent.run(
                            session_id=login["session_id"],
                            user_text="how do i use it?",
                        )

    assert result.intent == "product"
    assert "PN0013" in result.response_text
    assert "15 grams mixed with 40 pounds of water" in result.response_text
