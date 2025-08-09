"""End-to-end integration tests for the discovery system with real LLM.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.
These tests verify the full discovery → browsing flow with real LLM calls.

Run with: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration/test_discovery_to_browsing.py -v
"""

import logging
import os

import pytest

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning.nodes import WorkflowDiscoveryNode

logger = logging.getLogger(__name__)

# Skip these tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


class TestDiscoverySystemIntegration:
    """Test the full discovery system flow with real LLM."""

    def test_full_path_a_scenario(self):
        """Test a complete Path A scenario with real LLM."""
        node = WorkflowDiscoveryNode()

        # Create workflow manager and pass it through shared store
        workflow_manager = WorkflowManager()

        # Use a query that's likely to match an existing workflow
        shared = {
            "user_input": "I want to read a file called data.txt",
            "workflow_manager": workflow_manager,  # Pass the same WorkflowManager instance
        }

        try:
            # Run full lifecycle
            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            # Log results
            logger.info(f"Path A test - Action: {action}")
            logger.info(f"Found: {exec_res['found']}, Workflow: {exec_res.get('workflow_name')}")

            # Verify shared store updates
            assert "discovery_result" in shared
            assert "discovery_context" in shared

            if action == "found_existing":
                # If we found a workflow, verify it was loaded
                assert "found_workflow" in shared or exec_res.get("workflow_name") is None

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise


if __name__ == "__main__":
    # Run with logging to see actual LLM responses
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
