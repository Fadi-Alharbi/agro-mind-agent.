from unittest.mock import MagicMock, patch

import pytest

from agent.orchestrator import AgroMindAgent, _NoopMemory
from agent.tools import classify_intent, recommend_product


@pytest.fixture
def product_agent():
    return AgroMindAgent()


def _tool_mock(return_value):
    mock = MagicMock()
    mock.invoke.return_value = return_value
    return mock


def test_recommend_product_falls_back_to_local_catalog_when_vectorstore_unavailable():
    with patch(
        "agent.tools.retrieve_agronomy_knowledge",
        _tool_mock("Knowledge base unavailable."),
    ):
        result = recommend_product.invoke({
            "diagnosis": "Which product should I use for pests on citrus?",
            "crop": "Which product should I use for pests on citrus?",
        })

    assert "[PRODUCT:" in result
    assert "No suitable product found" not in result


def test_usage_question_with_catalog_product_routes_to_product():
    intent = classify_intent.invoke("how i use it 24% Diphenylhydrazine-Merry Orangery?")

    assert intent == "Product"


def test_usage_question_with_order_id_routes_to_product():
    intent = classify_intent.invoke("how i use it? PDD20260623160355-3-1")

    assert intent == "Product"


@pytest.mark.asyncio
async def test_product_recommendation_attaches_catalog_product_and_hides_tag(product_agent):
    recommend = _tool_mock(
        "This looks like a pest pressure issue. Apply a suitable product as directed. [PRODUCT: AF0001]"
    )

    with patch("agent.orchestrator._session_memory", return_value=_NoopMemory()):
        with patch("agent.orchestrator.detect_escalation_risk", _tool_mock(False)):
            with patch("agent.orchestrator.classify_intent", _tool_mock("Product")):
                with patch("agent.orchestrator.recommend_product", recommend):
                    with patch("agent.orchestrator.update_customer_profile", _tool_mock(None)):
                        with patch("agent.orchestrator._save_treatment_in_background"):
                            result = await product_agent.run(
                                session_id="test-product-recommendation",
                                user_text="Which product should I use for pests on citrus?",
                            )

    assert result.intent == "product"
    assert result.recommended_product_id == "AF0001"
    assert result.group_purchase_triggered is True
    assert len(result.matched_products) == 1
    assert result.matched_products[0]["product_id"] == "AF0001"
    assert "[PRODUCT:" not in result.response_text


@pytest.mark.asyncio
async def test_product_recommendation_accepts_legacy_product_id_marker(product_agent):
    recommend = _tool_mock(
        "Recommended Solution\nProduct ID: AF0001\nUse only according to the product label."
    )

    with patch("agent.orchestrator._session_memory", return_value=_NoopMemory()):
        with patch("agent.orchestrator.detect_escalation_risk", _tool_mock(False)):
            with patch("agent.orchestrator.classify_intent", _tool_mock("Product")):
                with patch("agent.orchestrator.recommend_product", recommend):
                    with patch("agent.orchestrator.update_customer_profile", _tool_mock(None)):
                        with patch("agent.orchestrator._save_treatment_in_background"):
                            result = await product_agent.run(
                                session_id="test-product-legacy-marker",
                                user_text="Recommend product for citrus pest",
                            )

    assert result.recommended_product_id == "AF0001"
    assert result.group_purchase_triggered is True
    assert len(result.matched_products) == 1
    assert "Product ID:" not in result.response_text


@pytest.mark.asyncio
async def test_no_suitable_product_does_not_attach_catalog_product(product_agent):
    recommend = _tool_mock(
        "No suitable product found in our catalog for this specific issue. "
        "General crop rotation and sanitation may help. AF0001 is not a recommendation."
    )

    with patch("agent.orchestrator._session_memory", return_value=_NoopMemory()):
        with patch("agent.orchestrator.detect_escalation_risk", _tool_mock(False)):
            with patch("agent.orchestrator.classify_intent", _tool_mock("Product")):
                with patch("agent.orchestrator.recommend_product", recommend):
                    with patch("agent.orchestrator.update_customer_profile", _tool_mock(None)):
                        with patch("agent.orchestrator._save_treatment_in_background"):
                            result = await product_agent.run(
                                session_id="test-product-no-match",
                                user_text="Recommend product for an unknown crop issue",
                            )

    assert result.recommended_product_id is None
    assert result.group_purchase_triggered is False
    assert result.matched_products == []


@pytest.mark.asyncio
async def test_ambiguous_usage_question_asks_for_product_without_recommending(product_agent):
    recommend = _tool_mock(
        "Based on the catalog match, this issue can be handled with a suitable verified product. [PRODUCT: PN0023]"
    )

    with patch("agent.orchestrator._session_memory", return_value=_NoopMemory()):
        with patch("agent.orchestrator.detect_escalation_risk", _tool_mock(False)):
            with patch("agent.orchestrator.classify_intent", _tool_mock("Product")):
                with patch("agent.orchestrator.get_pesticide_memory", return_value={}):
                    with patch("agent.orchestrator.recommend_product", recommend):
                        with patch("agent.orchestrator.update_customer_profile", _tool_mock(None)):
                            with patch("agent.orchestrator._save_treatment_in_background"):
                                result = await product_agent.run(
                                    session_id="test-product-usage-ambiguous",
                                    user_text="How do I mix the medicine with water?",
                                )

    assert result.intent == "product"
    assert "Which product are you asking about?" in result.response_text
    assert result.recommended_product_id is None
    assert result.group_purchase_triggered is False
    assert result.matched_products == []
    recommend.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_product_usage_by_exact_name_is_catalog_grounded(product_agent):
    with patch("agent.orchestrator._session_memory", return_value=_NoopMemory()):
        with patch("agent.orchestrator.detect_escalation_risk", _tool_mock(False)):
            with patch("agent.orchestrator.classify_intent", _tool_mock("Product")):
                with patch("agent.orchestrator.update_customer_profile", _tool_mock(None)):
                    with patch("agent.orchestrator._save_treatment_in_background"):
                        result = await product_agent.run(
                            session_id="test-product-usage-name",
                            user_text="how i use it 24% Diphenylhydrazine-Merry Orangery?",
                        )

    assert result.intent == "product"
    assert "PN0013" in result.response_text
    assert "15 grams mixed with 40 pounds of water" in result.response_text
    assert "1000-1500 times" in result.response_text
    assert "not approved" not in result.response_text.lower()


@pytest.mark.asyncio
async def test_product_usage_by_order_id_uses_order_product(product_agent):
    order = {
        "id": "PDD20260623160355-3-1",
        "product_id": "PN0013",
    }

    with patch("agent.orchestrator._session_memory", return_value=_NoopMemory()):
        with patch("agent.orchestrator.detect_escalation_risk", _tool_mock(False)):
            with patch("agent.orchestrator.classify_intent", _tool_mock("Product")):
                with patch("agent.orchestrator.get_order", return_value=order):
                    with patch("agent.orchestrator.update_customer_profile", _tool_mock(None)):
                        with patch("agent.orchestrator._save_treatment_in_background"):
                            result = await product_agent.run(
                                session_id="test-product-usage-order",
                                user_text="how i use it? PDD20260623160355-3-1",
                            )

    assert result.intent == "product"
    assert "PN0013" in result.response_text
    assert "15 grams mixed with 40 pounds of water" in result.response_text
