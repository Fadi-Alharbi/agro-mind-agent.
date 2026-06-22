import pytest
import asyncio
from unittest.mock import patch, MagicMock
from agent.orchestrator import AgroMindAgent

@pytest.fixture
def agent():
    return AgroMindAgent()

def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)

def test_safety_escalation_blocks_llm(agent):
    """
    Test that a message triggering a safety risk immediately returns
    an escalated response without passing to the normal intent nodes.
    """
    mock_risk = MagicMock()
    mock_risk.invoke.return_value = True
    mock_alert = MagicMock()
    mock_alert.invoke.return_value = "🚨 Safety Alert!"
    
    with patch("agent.orchestrator.detect_escalation_risk", mock_risk):
        with patch("agent.orchestrator.create_human_alert", mock_alert):
            result = run_async(agent.run(
                session_id="test-safety",
                user_text="I want to drink the pesticide and die",
            ))
            
            assert result.safety_risk_detected is True
            assert result.escalate_human is True
            assert result.intent == "safety"
            assert result.response_text == "🚨 Safety Alert!"

def test_normal_general_qa(agent):
    """
    Test a normal general QA query routes correctly.
    """
    mock_risk = MagicMock()
    mock_risk.invoke.return_value = False
    mock_classify = MagicMock()
    mock_classify.invoke.return_value = "General"
    mock_profile = MagicMock()
    
    with patch("agent.orchestrator.detect_escalation_risk", mock_risk):
        with patch("agent.orchestrator.classify_intent", mock_classify):
            with patch("agent.orchestrator.update_customer_profile", mock_profile):
                # Mock the LLM invoke inside general_node
                mock_llm_response = MagicMock()
                mock_llm_response.content = "All our products are authentic."
                with patch("agent.orchestrator.ChatOpenAI") as mock_chat:
                    mock_chat.return_value.invoke.return_value = mock_llm_response
                    result = run_async(agent.run(
                        session_id="test-qa",
                        user_text="Is this product authentic?",
                    ))
                    
                    assert result.safety_risk_detected is False
                    assert result.escalate_human is False
                    assert result.intent == "general"
                    assert result.response_text == "All our products are authentic."
