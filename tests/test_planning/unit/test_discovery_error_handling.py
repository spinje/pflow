"""Unit tests for discovery system error handling.

WHEN TO RUN: Always run these tests - they're fast and use mocks.
These tests verify exec_fallback, edge cases, and error recovery.
"""

import logging
from unittest.mock import Mock, patch

import pytest

from pflow.planning.nodes import ComponentBrowsingNode, WorkflowDiscoveryNode


@pytest.fixture
def mock_llm_response_nested():
    """Mock LLM response with CRITICAL nested structure for Anthropic."""

    def create_response(found=False, workflow_name=None, confidence=0.8, node_ids=None, workflow_names=None):
        """Create mock response with correct nested structure."""
        response = Mock()

        if node_ids is not None or workflow_names is not None:
            # ComponentSelection response
            response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "node_ids": node_ids or [],
                            "workflow_names": workflow_names or [],
                            "reasoning": "Test reasoning for component selection",
                        }
                    }
                ]
            }
        else:
            # WorkflowDecision response
            response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "found": found,
                            "workflow_name": workflow_name,
                            "confidence": confidence,
                            "reasoning": "Test reasoning for decision",
                        }
                    }
                ]
            }
        return response

    return create_response


class TestDiscoveryErrorHandling:
    """Tests for error handling in discovery nodes."""

    def test_exec_fallback_handles_llm_failure_discovery(self):
        """Test exec_fallback provides safe defaults on LLM failure for discovery."""
        node = WorkflowDiscoveryNode()
        node.wait = 0  # Speed up tests
        prep_res = {"user_input": "test", "discovery_context": "context"}
        exc = ValueError("LLM API failed")

        result = node.exec_fallback(prep_res, exc)

        assert result["found"] is False
        assert result["workflow_name"] is None
        assert result["confidence"] == 0.0
        assert "LLM API failed" in result["reasoning"]

    def test_exec_fallback_handles_llm_failure_browsing(self):
        """Test exec_fallback provides safe defaults on LLM failure for browsing."""
        node = ComponentBrowsingNode()
        node.wait = 0  # Speed up tests
        prep_res = {"user_input": "test", "discovery_context": "context", "registry_metadata": {}}
        exc = RuntimeError("API timeout")

        result = node.exec_fallback(prep_res, exc)

        assert result["node_ids"] == []
        assert result["workflow_names"] == []
        assert "API timeout" in result["reasoning"]

    def test_discovery_with_empty_user_input(self):
        """Test discovery validates required user_input."""
        node = WorkflowDiscoveryNode()
        node.wait = 0  # Speed up tests

        # Test that missing user_input raises ValueError
        shared = {}  # No user_input key
        with pytest.raises(ValueError, match="Missing required 'user_input'"):
            node.prep(shared)

        # Test with empty string also raises
        shared = {"user_input": ""}
        with pytest.raises(ValueError, match="Missing required 'user_input'"):
            node.prep(shared)

        # Test fallback to params works
        node.params = {"user_input": "test input"}
        node.wait = 0  # Speed up tests
        with patch("pflow.planning.nodes.build_discovery_context") as mock_build:
            mock_build.return_value = "test context"
            prep_res = node.prep({})  # Empty shared but params has it
            assert prep_res["user_input"] == "test input"

    def test_browsing_validates_required_user_input(self):
        """Test browsing validates required user_input."""
        node = ComponentBrowsingNode()
        node.wait = 0  # Speed up tests

        # Test that missing user_input raises ValueError
        shared = {}  # No user_input key
        with (
            pytest.raises(ValueError, match="Missing required 'user_input'"),
            patch("pflow.planning.nodes.Registry") as mock_registry,
        ):
            mock_registry.return_value.load.return_value = {}
            node.prep(shared)

    def test_discovery_handles_malformed_llm_response(self):
        """Test discovery handles malformed LLM responses gracefully."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            response = Mock()
            # Simulate malformed response structure
            response.json.return_value = {"unexpected": "structure"}
            mock_model.prompt.return_value = response
            mock_get_model.return_value = mock_model

            node = WorkflowDiscoveryNode()
            node.wait = 0  # Speed up tests
            prep_res = {
                "user_input": "test",
                "discovery_context": "context",
                "model_name": "anthropic/claude-sonnet-4-0",
                "temperature": 0.0,
            }

            # Should raise ValueError for invalid structure
            with pytest.raises(ValueError, match="Invalid LLM response structure"):
                node.exec(prep_res)

    def test_browsing_handles_registry_load_failure(self, caplog):
        """Test browsing handles registry load failures gracefully."""
        with patch("llm.get_model"), patch("pflow.planning.nodes.Registry") as mock_reg_class:
            mock_registry = Mock()
            mock_registry.load.side_effect = RuntimeError("Registry corrupted")
            mock_reg_class.return_value = mock_registry

            with patch("pflow.planning.nodes.build_discovery_context") as mock_build:
                mock_build.return_value = "minimal context"

                node = ComponentBrowsingNode()
                node.wait = 0  # Speed up tests
                shared = {"user_input": "test"}

                # Should not raise - continues with empty registry
                with caplog.at_level(logging.ERROR):
                    prep_res = node.prep(shared)

                # Verify it logged the error and used empty registry
                assert "Failed to load registry" in caplog.text
                assert "Registry corrupted" in caplog.text
                assert prep_res["registry_metadata"] == {}  # Empty registry used

    def test_discovery_long_user_input_truncation(self, mock_llm_response_nested, caplog):
        """Test discovery handles very long user input with truncation in logs."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(found=False)
            mock_get_model.return_value = mock_model

            node = WorkflowDiscoveryNode()
            node.wait = 0  # Speed up tests
            long_input = "x" * 500  # Very long input
            prep_res = {
                "user_input": long_input,
                "discovery_context": "context",
                "model_name": "anthropic/claude-sonnet-4-0",
                "temperature": 0.0,
            }

            with caplog.at_level(logging.DEBUG):
                node.exec(prep_res)

            # Check that logging truncates to 100 chars
            assert "xxx..." in caplog.text  # Shows truncation
            assert len([r for r in caplog.records if len(r.message) > 150]) == 0

    def test_post_handles_planning_context_error_dict(self, caplog):
        """Test post handles error dict from build_planning_context."""
        with patch("pflow.planning.nodes.build_planning_context") as mock_build:
            # Return error dict structure
            mock_build.return_value = {
                "error": "Some components not found",
                "missing_nodes": ["unknown-node"],
                "missing_workflows": ["missing-workflow"],
            }

            node = ComponentBrowsingNode()
            node.wait = 0  # Speed up tests
            shared = {}
            prep_res = {"registry_metadata": {}}
            exec_res = {
                "node_ids": ["unknown-node"],
                "workflow_names": ["missing-workflow"],
                "reasoning": "Bad selection",
            }

            with caplog.at_level(logging.WARNING):
                action = node.post(shared, prep_res, exec_res)

            assert action == "generate"  # Still routes to generate
            assert shared["planning_context"] == ""  # Empty on error
            assert "Planning context error" in caplog.text

            # Check structured logging extra fields
            warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
            assert len(warning_records) > 0
            assert warning_records[0].phase == "post"
            assert warning_records[0].missing_nodes == ["unknown-node"]
            assert warning_records[0].missing_workflows == ["missing-workflow"]

    def test_browsing_with_empty_selections(self, mock_llm_response_nested):
        """Test browsing handles empty component selections."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(node_ids=[], workflow_names=[])
            mock_get_model.return_value = mock_model

            with patch("pflow.planning.nodes.Registry") as mock_reg_class:
                mock_reg_class.return_value = Mock(load=Mock(return_value={}))

                with patch("pflow.planning.nodes.build_planning_context") as mock_build:
                    mock_build.return_value = "empty context"

                    node = ComponentBrowsingNode()
                    node.wait = 0  # Speed up tests
                    shared = {"user_input": "unclear request"}

                    prep_res = node.prep(shared)
                    exec_res = node.exec(prep_res)
                    action = node.post(shared, prep_res, exec_res)

                    assert action == "generate"  # Still routes to generate
                    assert shared["browsed_components"]["node_ids"] == []
                    assert shared["browsed_components"]["workflow_names"] == []
