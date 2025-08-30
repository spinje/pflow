"""Test the new LLM mock system in isolation.

WHEN TO RUN: When validating the new LLM mock implementation
WHAT IT VALIDATES: The mock correctly simulates LLM behavior for planning nodes
"""

from unittest.mock import patch

from pflow.planning.nodes import ComponentSelection, ParameterDiscovery, WorkflowDecision, WorkflowDiscoveryNode
from tests.shared.llm_mock import create_mock_get_model


class TestLLMMockValidation:
    """Validate the new LLM mock works correctly."""

    def test_mock_returns_configured_response(self):
        """Test that mock returns what we configure."""
        mock_get_model = create_mock_get_model()

        # Configure a specific response
        mock_get_model.set_response(
            "anthropic/claude-3-sonnet-20240229",
            WorkflowDecision,
            {"found": True, "workflow_name": "test-workflow", "confidence": 0.95, "reasoning": "Perfect match"},
        )

        # Get a model and make a call
        model = mock_get_model("anthropic/claude-3-sonnet-20240229")
        response = model.prompt("test prompt", schema=WorkflowDecision)

        # Verify response structure (Anthropic nested format)
        result = response.json()
        assert "content" in result
        assert len(result["content"]) == 1
        assert "input" in result["content"][0]

        # Verify response data
        data = result["content"][0]["input"]
        assert data["found"] is True
        assert data["workflow_name"] == "test-workflow"
        assert data["confidence"] == 0.95

    def test_mock_tracks_call_history(self):
        """Test that mock records calls for verification."""
        mock_get_model = create_mock_get_model()

        # Make some calls
        model1 = mock_get_model("model-1")
        model1.prompt("prompt 1", temperature=0.5)

        model2 = mock_get_model("model-2")
        model2.prompt("prompt 2", schema=WorkflowDecision)

        # Verify call history
        assert len(mock_get_model.call_history) == 2
        assert mock_get_model.call_history[0]["model"] == "model-1"
        assert mock_get_model.call_history[0]["prompt"] == "prompt 1"
        assert mock_get_model.call_history[0]["temperature"] == 0.5
        assert mock_get_model.call_history[1]["model"] == "model-2"
        assert mock_get_model.call_history[1]["schema"] == "WorkflowDecision"

    def test_mock_with_discovery_node_exec(self):
        """Test the mock works with discovery node's exec method."""
        mock_get_model = create_mock_get_model()

        # Configure response for discovery
        mock_get_model.set_response(
            "anthropic/claude-sonnet-4-0",  # Default model used by discovery node
            WorkflowDecision,
            {
                "found": True,
                "workflow_name": "generate-changelog",
                "confidence": 0.92,
                "reasoning": "Exact match for changelog generation",
            },
        )

        with patch("llm.get_model", mock_get_model):
            # Create discovery node and test exec directly
            node = WorkflowDiscoveryNode()

            # Prepare input for exec (bypassing prep)
            prep_res = {
                "user_input": "generate a changelog",
                "discovery_context": "Workflows: generate-changelog, create-report",
                "model_name": "anthropic/claude-sonnet-4-0",
                "temperature": 0.0,
            }

            # Run exec method
            exec_res = node.exec(prep_res)

            # Verify the mock returned the configured response
            assert exec_res["found"] is True
            assert exec_res["workflow_name"] == "generate-changelog"
            assert exec_res["confidence"] == 0.92
            assert exec_res["reasoning"] == "Exact match for changelog generation"

            # Verify LLM was called
            assert len(mock_get_model.call_history) == 1
            assert mock_get_model.call_history[0]["model"] == "anthropic/claude-sonnet-4-0"

    def test_mock_reset_provides_isolation(self):
        """Test that reset() provides clean state between tests."""
        mock_get_model = create_mock_get_model()

        # Configure and use
        mock_get_model.set_response("model", None, {"test": 1})
        model = mock_get_model("model")
        model.prompt("test")

        assert len(mock_get_model.call_history) == 1

        # Reset
        mock_get_model.reset()

        # Verify clean state
        assert len(mock_get_model.call_history) == 0
        assert mock_get_model.get_response("model", None) == {"response": "mock response"}

    def test_mock_handles_text_responses(self):
        """Test mock handles non-schema text responses."""
        mock_get_model = create_mock_get_model()

        # Configure text response
        mock_get_model.set_response("model", None, "Plain text response")

        model = mock_get_model("model")
        response = model.prompt("test")

        # Text responses use .text() method (matching llm library)
        assert response.text() == "Plain text response"
        # Usage is a method that returns an object with input/output properties
        usage = response.usage()
        assert usage.input == 1  # "test" = 1 token

    def test_mock_provides_default_responses(self):
        """Test mock has sensible defaults for each schema."""
        mock_get_model = create_mock_get_model()
        model = mock_get_model("test-model")

        # Test WorkflowDecision default
        response = model.prompt("test", schema=WorkflowDecision)
        data = response.json()["content"][0]["input"]
        assert data["found"] is False
        assert data["confidence"] == 0.3

        # Test other schemas have defaults
        response = model.prompt("test", schema=ComponentSelection)
        data = response.json()["content"][0]["input"]
        assert "node_ids" in data
        assert isinstance(data["node_ids"], list)

        response = model.prompt("test", schema=ParameterDiscovery)
        data = response.json()["content"][0]["input"]
        assert "parameters" in data
        assert isinstance(data["parameters"], dict)
