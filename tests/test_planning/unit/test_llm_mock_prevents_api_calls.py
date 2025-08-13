"""Test that the LLM mock prevents actual API calls.

WHEN TO RUN: When validating the mock prevents real API usage
WHAT IT VALIDATES: No real LLM API calls are made in non-llm/ tests
"""

from pflow.planning.nodes import WorkflowDecision, WorkflowDiscoveryNode


class TestLLMMockPreventsAPICalls:
    """Verify the auto-applied mock prevents real LLM API calls."""

    def test_discovery_node_uses_mock_not_real_api(self, mock_llm_responses):
        """Test that discovery node uses the mock instead of real API."""
        # Configure a specific response
        mock_llm_responses.set_response(
            "anthropic/claude-sonnet-4-0",
            WorkflowDecision,
            {
                "found": True,
                "workflow_name": "mock-workflow-xyz-123",  # Unique name that real API wouldn't return
                "confidence": 0.999,
                "reasoning": "This is a mock response - not from real API",
            },
        )

        # Run discovery node
        node = WorkflowDiscoveryNode()
        prep_res = {
            "user_input": "test query",
            "discovery_context": "test context",
            "model_name": "anthropic/claude-sonnet-4-0",
            "temperature": 0.0,
        }

        # Execute - this would call real API without mock
        result = node.exec(prep_res)

        # Verify we got our mock response, not a real API response
        assert result["found"] is True
        assert result["workflow_name"] == "mock-workflow-xyz-123"
        assert result["confidence"] == 0.999
        assert result["reasoning"] == "This is a mock response - not from real API"

        # Verify the mock was called
        assert len(mock_llm_responses.call_history) == 1
        assert mock_llm_responses.call_history[0]["model"] == "anthropic/claude-sonnet-4-0"

    def test_mock_applies_automatically_without_explicit_patch(self, mock_llm_responses):
        """Test that mock is auto-applied without needing explicit @patch."""
        # Don't use any @patch decorator - rely on auto-applied fixture

        # Configure response
        mock_llm_responses.set_response(
            "anthropic/claude-sonnet-4-0",
            WorkflowDecision,
            {"found": False, "workflow_name": None, "confidence": 0.1, "reasoning": "Auto-mock working"},
        )

        # This should use the mock automatically
        node = WorkflowDiscoveryNode()
        result = node.exec({
            "user_input": "test",
            "discovery_context": "context",
            "model_name": "anthropic/claude-sonnet-4-0",
            "temperature": 0.0,
        })

        assert result["reasoning"] == "Auto-mock working"
        assert len(mock_llm_responses.call_history) == 1

    def test_mock_resets_between_tests(self, mock_llm_responses):
        """Test that mock state is clean for each test."""
        # Call history should be empty at start of test
        assert len(mock_llm_responses.call_history) == 0

        # Make a call
        node = WorkflowDiscoveryNode()
        node.exec({
            "user_input": "test",
            "discovery_context": "context",
            "model_name": "anthropic/claude-sonnet-4-0",
            "temperature": 0.0,
        })

        # Should have one call
        assert len(mock_llm_responses.call_history) == 1

        # Next test will start with clean state (tested by running multiple tests)
