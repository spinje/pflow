"""Test WorkflowDiscoveryNode optimization that skips LLM when no workflows exist.

WHEN TO RUN:
- After modifying WorkflowDiscoveryNode.exec() optimization logic
- After changing how empty discovery_context is handled
- Part of standard test suite

WHAT IT VALIDATES:
- Node skips LLM call when discovery_context is empty (optimization)
- Node calls LLM when discovery_context is non-empty
- Caching tests work correctly with non-empty context

FIX HISTORY:
- 2025-09-19: Added test for optimization that skips LLM call when no workflows exist
- 2025-09-19: This optimization was added to avoid expensive LLM calls when there are
              no workflows in the system to match against
"""

from unittest.mock import Mock, patch

from pflow.planning.nodes import WorkflowDiscoveryNode


class TestWorkflowDiscoveryOptimization:
    """Test optimization in WorkflowDiscoveryNode that skips LLM for empty context."""

    def test_skips_llm_when_no_workflows_exist(self):
        """Node should skip LLM call when discovery_context is empty."""
        node = WorkflowDiscoveryNode()
        shared = {
            "user_input": "create a test workflow",
            "cache_planner": False,
        }

        with patch("pflow.planning.nodes.build_workflows_context") as mock_build_context:
            # Empty context - no workflows exist in the system
            mock_build_context.return_value = ""

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_get_model.return_value = mock_model

                # Execute the node
                prep_res = node.prep(shared)
                result = node.exec(prep_res)

                # Verify LLM was NOT called (optimization)
                mock_model.prompt.assert_not_called()

                # Verify we get the expected result
                assert result["found"] is False
                assert result["workflow_name"] is None
                assert result["confidence"] == 1.0
                assert "No existing workflows" in result["reasoning"]

    def test_calls_llm_when_workflows_exist(self):
        """Node should call LLM when discovery_context has content."""
        node = WorkflowDiscoveryNode()
        shared = {
            "user_input": "create a test workflow",
            "cache_planner": False,
        }

        with patch("pflow.planning.nodes.build_workflows_context") as mock_build_context:
            # Non-empty context - workflows exist
            mock_build_context.return_value = "workflow-1: Test workflow\nworkflow-2: Another workflow"

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": False,
                                "workflow_name": None,
                                "confidence": 0.8,
                                "reasoning": "No exact match found",
                            }
                        }
                    ]
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                # Execute the node
                prep_res = node.prep(shared)
                result = node.exec(prep_res)

                # Verify LLM WAS called
                mock_model.prompt.assert_called_once()

                # Verify result from LLM response
                assert result["found"] is False
                assert result["confidence"] == 0.8
                assert "No exact match" in result["reasoning"]

    def test_optimization_with_caching_enabled(self):
        """Optimization should work regardless of cache_planner flag."""
        node = WorkflowDiscoveryNode()
        shared = {
            "user_input": "create a test workflow",
            "cache_planner": True,  # Caching enabled
        }

        with patch("pflow.planning.nodes.build_workflows_context") as mock_build_context:
            # Empty context - should still trigger optimization
            mock_build_context.return_value = ""

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_get_model.return_value = mock_model

                # Execute the node
                prep_res = node.prep(shared)
                result = node.exec(prep_res)

                # Verify LLM was NOT called even with caching enabled
                mock_model.prompt.assert_not_called()

                # Verify we get the expected result
                assert result["found"] is False
                assert result["confidence"] == 1.0

    def test_caching_requires_non_empty_context(self):
        """Caching behavior can only be tested with non-empty context.

        This documents why the original caching tests need non-empty context:
        With empty context, the optimization path is taken and LLM is never called,
        so there's nothing to cache.
        """
        node = WorkflowDiscoveryNode()
        shared = {
            "user_input": "create a test workflow",
            "cache_planner": True,
        }

        with patch("pflow.planning.nodes.build_workflows_context") as mock_build_context:
            # Must provide non-empty context to test caching
            mock_build_context.return_value = "workflow-1: Existing workflow"

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": False,
                                "workflow_name": None,
                                "confidence": 0.5,
                                "reasoning": "No match",
                            }
                        }
                    ]
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                # Execute the node
                prep_res = node.prep(shared)
                node.exec(prep_res)

                # Verify LLM was called
                mock_model.prompt.assert_called_once()

                # Verify cache_blocks were passed
                call_args = mock_model.prompt.call_args
                assert call_args.kwargs.get("cache_blocks") is not None
