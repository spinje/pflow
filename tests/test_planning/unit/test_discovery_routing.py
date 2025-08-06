"""Unit tests for discovery system routing logic.

WHEN TO RUN: Always run these tests - they're fast and use mocks.
These tests verify action strings, routing decisions, and path selection logic.
"""

import logging
from unittest.mock import Mock, patch

import pytest

from pflow.core.exceptions import WorkflowNotFoundError
from pflow.planning.nodes import WorkflowDiscoveryNode


@pytest.fixture
def mock_workflow_manager():
    """Mock workflow manager for testing workflow loading."""
    manager = Mock()
    manager.load.return_value = {
        "name": "test-workflow",
        "description": "A test workflow",
        "ir": {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test-node"}],
            "edges": [],
        },
        "created_at": "2024-01-30T10:00:00Z",
        "updated_at": "2024-01-30T10:00:00Z",
        "version": "1.0.0",
    }
    return manager


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


class TestWorkflowDiscoveryRouting:
    """Tests for WorkflowDiscoveryNode routing decisions."""

    def test_post_routes_found_existing_path_a(self, mock_workflow_manager, mock_llm_response_nested):
        """Test post routes to 'found_existing' for Path A when workflow found."""
        with patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class:
            mock_wm_class.return_value = mock_workflow_manager

            node = WorkflowDiscoveryNode()
            node.wait = 0  # Speed up tests
            shared = {}
            prep_res = {"discovery_context": "test context"}
            exec_res = {
                "found": True,
                "workflow_name": "test-workflow",
                "confidence": 0.95,
                "reasoning": "Perfect match",
            }

            action = node.post(shared, prep_res, exec_res)

            assert action == "found_existing"
            assert shared["discovery_result"] == exec_res
            assert shared["discovery_context"] == "test context"
            assert shared["found_workflow"]["name"] == "test-workflow"
            mock_workflow_manager.load.assert_called_once_with("test-workflow")

    def test_post_routes_not_found_path_b(self, mock_llm_response_nested):
        """Test post routes to 'not_found' for Path B when no workflow found."""
        node = WorkflowDiscoveryNode()
        node.wait = 0  # Speed up tests
        shared = {}
        prep_res = {"discovery_context": "test context"}
        exec_res = {"found": False, "workflow_name": None, "confidence": 0.2, "reasoning": "No match"}

        action = node.post(shared, prep_res, exec_res)

        assert action == "not_found"
        assert shared["discovery_result"] == exec_res
        assert shared["discovery_context"] == "test context"
        assert "found_workflow" not in shared

    def test_post_handles_workflow_not_found_error(self, mock_workflow_manager, caplog):
        """Test post handles case when workflow exists in LLM but not on disk."""
        with patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class:
            mock_workflow_manager.load.side_effect = WorkflowNotFoundError("not-on-disk")
            mock_wm_class.return_value = mock_workflow_manager

            node = WorkflowDiscoveryNode()
            node.wait = 0  # Speed up tests
            shared = {}
            prep_res = {"discovery_context": "test context"}
            exec_res = {"found": True, "workflow_name": "not-on-disk", "confidence": 0.9, "reasoning": "Found it"}

            with caplog.at_level(logging.WARNING):
                action = node.post(shared, prep_res, exec_res)

            assert action == "not_found"  # Falls back to Path B
            assert "not-on-disk" in caplog.text
            assert "not found on disk" in caplog.text
            assert "found_workflow" not in shared

    def test_shared_store_keys_written_correctly_discovery(self, mock_llm_response_nested):
        """Test discovery node writes expected keys to shared store."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(found=False)
            mock_get_model.return_value = mock_model

            shared = {"user_input": "test"}

            # Discovery node adds its keys
            discovery = WorkflowDiscoveryNode()
            discovery.wait = 0  # Speed up tests
            prep1 = discovery.prep(shared)
            exec1 = discovery.exec(prep1)
            discovery.post(shared, prep1, exec1)

            assert "discovery_result" in shared
            assert "discovery_context" in shared
            assert "found_workflow" not in shared  # Not found case

    def test_path_a_flow_complete_match(self, mock_workflow_manager, mock_llm_response_nested):
        """Test complete Path A flow: discovery finds match, loads workflow."""
        with patch("llm.get_model") as mock_get_model:
            # Setup mock model for discovery
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(
                found=True, workflow_name="csv-processor", confidence=0.98
            )
            mock_get_model.return_value = mock_model

            with patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class:
                mock_wm_class.return_value = mock_workflow_manager

                # Run discovery node
                discovery_node = WorkflowDiscoveryNode()
                discovery_node.wait = 0  # Speed up tests
                shared = {"user_input": "process CSV files"}

                prep_res = discovery_node.prep(shared)
                exec_res = discovery_node.exec(prep_res)
                action = discovery_node.post(shared, prep_res, exec_res)

                # Verify Path A routing
                assert action == "found_existing"
                assert shared["found_workflow"]["name"] == "test-workflow"
                assert shared["discovery_result"]["found"] is True
                assert shared["discovery_result"]["workflow_name"] == "csv-processor"
