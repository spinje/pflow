"""LLM prompt-sensitive tests for discovery node.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.
These tests are PROMPT-SENSITIVE and will break if the discovery prompt changes.
They verify the exact prompt structure and LLM response format.

Run with: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_discovery_prompt.py -v
"""

import logging
import os

import pytest

from pflow.planning.nodes import WorkflowDiscoveryNode

logger = logging.getLogger(__name__)

# Skip these tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


class TestDiscoveryPromptSensitive:
    """Tests that are sensitive to discovery prompt changes."""

    def test_workflow_discovery_with_real_llm(self):
        """Test WorkflowDiscoveryNode with actual LLM API call."""
        # Create node and set up shared store
        node = WorkflowDiscoveryNode()

        # Create workflow manager and pass it through shared store
        from pflow.core.workflow_manager import WorkflowManager

        workflow_manager = WorkflowManager()

        shared = {
            "user_input": "I want to read a file and analyze its contents",
            "workflow_manager": workflow_manager,  # Pass the same WorkflowManager instance
        }

        # Run the full lifecycle
        prep_res = node.prep(shared)

        # Verify prep includes model configuration
        assert "model_name" in prep_res
        assert "temperature" in prep_res
        assert prep_res["model_name"] == "anthropic/claude-sonnet-4-0"
        assert prep_res["temperature"] == 0.0

        # Execute with real LLM
        try:
            exec_res = node.exec(prep_res)

            # Verify we got a valid response structure
            assert isinstance(exec_res, dict)
            assert "found" in exec_res
            assert "reasoning" in exec_res
            assert "confidence" in exec_res
            assert isinstance(exec_res["found"], bool)
            assert isinstance(exec_res["confidence"], float)

            # Log the actual decision for debugging
            logger.info(
                f"Real LLM decision: found={exec_res['found']}, "
                f"workflow={exec_res.get('workflow_name')}, "
                f"confidence={exec_res['confidence']}"
            )
            logger.info(f"Reasoning: {exec_res['reasoning']}")

            # Run post to get routing decision
            action = node.post(shared, prep_res, exec_res)
            assert action in ["found_existing", "not_found"]

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_custom_model_configuration(self):
        """Test that custom model configuration via params works."""
        node = WorkflowDiscoveryNode()

        # Configure to use a different model
        node.params = {
            "model": "anthropic/claude-3-haiku-20240307",  # Faster, cheaper model
            "temperature": 0.5,
        }

        # Create workflow manager and pass it through shared store
        from pflow.core.workflow_manager import WorkflowManager

        workflow_manager = WorkflowManager()

        shared = {
            "user_input": "simple test query",
            "workflow_manager": workflow_manager,  # Pass the same WorkflowManager instance
        }
        prep_res = node.prep(shared)

        # Verify custom configuration is used
        assert prep_res["model_name"] == "anthropic/claude-3-haiku-20240307"
        assert prep_res["temperature"] == 0.5

        # Try to execute with custom model
        try:
            exec_res = node.exec(prep_res)

            # Verify response structure
            assert isinstance(exec_res, dict)
            assert "found" in exec_res

            logger.info(f"Custom model response: {exec_res}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            elif "claude-3-haiku" in str(e):
                # Model might not be available, try with default
                logger.warning(f"Haiku model not available: {e}")
                node.params = {}  # Reset to defaults
                prep_res = node.prep(shared)
                exec_res = node.exec(prep_res)
                assert isinstance(exec_res, dict)
            else:
                raise

    def test_error_handling_with_invalid_model(self):
        """Test that exec_fallback is triggered with invalid model."""
        node = WorkflowDiscoveryNode(max_retries=1)  # Single retry to speed up test
        node.params = {"model": "invalid-model-name-xyz"}

        shared = {"user_input": "test"}

        # Use the internal _exec method which handles retries and fallback
        # (In production, this is called by run() or by the Flow)
        prep_res = node.prep(shared)
        exec_res = node._exec(prep_res)  # This will trigger exec_fallback

        # exec_fallback should return a safe default
        assert exec_res["found"] is False
        assert exec_res["confidence"] == 0.0
        assert "error" in exec_res["reasoning"].lower() or "failed" in exec_res["reasoning"].lower()

        # Post should still work with fallback result
        action = node.post(shared, prep_res, exec_res)
        assert action == "not_found"


if __name__ == "__main__":
    # Run with logging to see actual LLM responses
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
