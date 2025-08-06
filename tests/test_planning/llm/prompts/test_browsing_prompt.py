"""LLM prompt-sensitive tests for browsing node.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.
These tests are PROMPT-SENSITIVE and will break if the browsing prompt changes.
They verify the exact prompt structure and LLM response format.

Run with: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_browsing_prompt.py -v
"""

import logging
import os

import pytest

from pflow.planning.nodes import ComponentBrowsingNode

logger = logging.getLogger(__name__)

# Skip these tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


class TestBrowsingPromptSensitive:
    """Tests that are sensitive to browsing prompt changes."""

    def test_component_browsing_with_real_llm(self):
        """Test ComponentBrowsingNode with actual LLM API call."""
        # Create node and set up shared store
        node = ComponentBrowsingNode()
        shared = {"user_input": "Process CSV files and generate a summary report"}

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
            assert "node_ids" in exec_res
            assert "workflow_names" in exec_res
            assert "reasoning" in exec_res
            assert isinstance(exec_res["node_ids"], list)
            assert isinstance(exec_res["workflow_names"], list)

            # Log the actual selection for debugging
            logger.info(f"Real LLM selected {len(exec_res['node_ids'])} nodes: {exec_res['node_ids']}")
            logger.info(f"Selected {len(exec_res['workflow_names'])} workflows: {exec_res['workflow_names']}")
            logger.info(f"Reasoning: {exec_res['reasoning']}")

            # Run post to verify it always returns "generate"
            action = node.post(shared, prep_res, exec_res)
            assert action == "generate"

            # Verify shared store was updated
            assert "browsed_components" in shared
            assert "registry_metadata" in shared

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise


if __name__ == "__main__":
    # Run with logging to see actual LLM responses
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
