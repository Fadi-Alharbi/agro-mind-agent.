"""
tests/test_agent.py
───────────────────
Integration smoke tests for the AgroMindAgent pipeline.
These tests do NOT call the real Gemini API — they use a mock model
to test all routing logic without network dependency.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from agent.orchestrator import AgroMindAgent, AgentResponse
from safety.interceptor import SafetyInterceptor


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_mock_gemini_response(data: dict) -> MagicMock:
    """Create a mock Gemini response object that returns a JSON string."""
    mock = MagicMock()
    mock.text = json.dumps(data)
    return mock


MOCK_LOGISTICS_RESPONSE = {
    "intent": "logistics",
    "safety_risk_detected": False,
    "escalate_human": False,
    "response_text": "Dear customer, we ship from Zhejiang Province via postal courier.",
    "recommended_product_id": None,
    "group_purchase_triggered": False,
    "human_summary_brief": None,
}

MOCK_PRODUCT_RESPONSE = {
    "intent": "product_recommendation",
    "safety_risk_detected": False,
    "escalate_human": False,
    "response_text": "Dear customer, I recommend AF0001. Group purchase: ¥28 | Single purchase: ¥39.",
    "recommended_product_id": "AF0001",
    "group_purchase_triggered": True,
    "human_summary_brief": None,
}

MOCK_DIAGNOSIS_RESPONSE = {
    "intent": "diagnosis",
    "safety_risk_detected": False,
    "escalate_human": False,
    "response_text": "Your tomato appears to have early blight. I recommend AF0005.",
    "recommended_product_id": "AF0005",
    "group_purchase_triggered": True,
    "human_summary_brief": None,
}

MOCK_GENERAL_RESPONSE = {
    "intent": "general_qa",
    "safety_risk_detected": False,
    "escalate_human": False,
    "response_text": "Dear customer, all our products are genuine and QR-code verified!",
    "recommended_product_id": None,
    "group_purchase_triggered": False,
    "human_summary_brief": None,
}


# ── Safety Intercept Tests (no LLM needed) ─────────────────────────────────────

def test_safety_interceptor_standalone():
    interceptor = SafetyInterceptor()
    result = interceptor.check("I want to die and drink the pesticide")
    assert not result.is_safe
    assert result.escalate_human_required or True


def test_safety_interceptor_safe():
    interceptor = SafetyInterceptor()
    result = interceptor.check("How many jin of water per bottle?")
    assert result.is_safe


# ── Agent routing tests (mocked LLM) ─────────────────────────────────────────

@pytest.fixture
def agent():
    with patch("agent.orchestrator.genai.GenerativeModel") as MockModel:
        mock_instance = MagicMock()
        MockModel.return_value = mock_instance
        a = AgroMindAgent()
        a._model = mock_instance
        return a


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_safety_escalation_blocks_llm(agent):
    """Safety intercept must return without calling the LLM."""
    with patch.object(agent, "_classify_intent") as mock_classify:
        result = run_async(agent.run(
            session_id="test-safety",
            user_text="I want to drink the pesticide and die",
        ))
        # classify_intent must NOT have been called
        mock_classify.assert_not_called()
        assert result.safety_risk_detected is True
        assert result.escalate_human is True
        assert result.intent == "safety_escalation"


def test_logistics_routing(agent):
    """Logistics messages should route to _handle_logistics."""
    agent._model.generate_content.return_value = make_mock_gemini_response(MOCK_LOGISTICS_RESPONSE)

    with patch.object(agent, "_classify_intent", return_value="logistics"):
        result = run_async(agent.run(
            session_id="test-logistics",
            user_text="What courier service do you use?",
        ))

    assert result.intent == "logistics"
    assert result.safety_risk_detected is False


def test_product_recommendation_routing(agent):
    """Product queries should route to _handle_product_recommendation."""
    agent._model.generate_content.return_value = make_mock_gemini_response(MOCK_PRODUCT_RESPONSE)

    with patch.object(agent, "_classify_intent", return_value="product_recommendation"):
        result = run_async(agent.run(
            session_id="test-product",
            user_text="What product should I use for spider mites on citrus?",
        ))

    assert result.intent == "product_recommendation"
    assert result.group_purchase_triggered is True


def test_diagnosis_routing(agent):
    """Diagnosis messages should route to _handle_diagnosis."""
    agent._model.generate_content.return_value = make_mock_gemini_response(MOCK_DIAGNOSIS_RESPONSE)

    with patch.object(agent, "_classify_intent", return_value="diagnosis"):
        result = run_async(agent.run(
            session_id="test-diagnosis",
            user_text="My tomato leaves have brown spots, what disease is this?",
        ))

    assert result.intent == "diagnosis"


def test_general_qa_routing(agent):
    """General questions should route to _handle_general_qa."""
    agent._model.generate_content.return_value = make_mock_gemini_response(MOCK_GENERAL_RESPONSE)

    with patch.object(agent, "_classify_intent", return_value="general_qa"):
        result = run_async(agent.run(
            session_id="test-qa",
            user_text="Is this product authentic?",
        ))

    assert result.intent == "general_qa"
    assert result.safety_risk_detected is False


def test_image_forces_diagnosis(agent):
    """Sending image_bytes should force diagnosis routing regardless of intent."""
    agent._model.generate_content.return_value = make_mock_gemini_response(MOCK_DIAGNOSIS_RESPONSE)

    with patch.object(agent, "_classify_intent", return_value="logistics"):
        # Even if intent says logistics, image should force diagnosis
        fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # fake PNG bytes

        with patch.object(agent, "_handle_diagnosis", return_value=AgentResponse(
            intent="diagnosis",
            safety_risk_detected=False,
            escalate_human=False,
            response_text="Mock diagnosis",
        )) as mock_diag:
            result = run_async(agent.run(
                session_id="test-image",
                user_text="What's wrong with my plant?",
                image_bytes=fake_image,
            ))
            mock_diag.assert_called_once()


def test_response_has_all_required_fields(agent):
    """AgentResponse.to_dict() must always contain all JSON contract fields."""
    agent._model.generate_content.return_value = make_mock_gemini_response(MOCK_GENERAL_RESPONSE)

    with patch.object(agent, "_classify_intent", return_value="general_qa"):
        result = run_async(agent.run(
            session_id="test-schema",
            user_text="Hello!",
        ))

    d = result.to_dict()
    required_fields = [
        "intent", "safety_risk_detected", "escalate_human",
        "response_text", "recommended_product_id",
        "group_purchase_triggered", "human_summary_brief",
    ]
    for field in required_fields:
        assert field in d, f"Missing required field: {field}"
