"""Unit tests for component browsing and selection logic.

WHEN TO RUN: Always run these tests - they're fast and use mocks.
These tests verify component selection, over-inclusive strategies, and browsing behavior.

FOCUS: These tests validate the ComponentBrowsingNode's ability to select
relevant nodes and workflows for new workflow generation (Path B).
The over-inclusive selection strategy is critical to avoid missing components.
"""

from unittest.mock import Mock, patch

import pytest

from pflow.planning.nodes import ComponentBrowsingNode


@pytest.fixture
def mock_registry():
    """Mock registry with test data."""
    registry = Mock()
    registry.load.return_value = {
        "read-file": {
            "module": "pflow.nodes.file.read_file",
            "class_name": "ReadFileNode",
            "interface": {
                "description": "Read content from a file",
                "inputs": [{"key": "file_path", "type": "str"}],
                "outputs": [{"key": "content", "type": "str"}],
            },
        },
        "llm": {
            "module": "pflow.nodes.llm.llm_node",
            "class_name": "LLMNode",
            "interface": {
                "description": "Process text with LLM",
                "inputs": [{"key": "prompt", "type": "str"}],
                "outputs": [{"key": "response", "type": "str"}],
            },
        },
    }
    return registry


@pytest.fixture
def mock_llm_response_nested():
    """Mock LLM response with CRITICAL nested structure for Anthropic."""

    def create_response(found=False, workflow_name=None, confidence=0.8, node_ids=None, workflow_names=None):
        """Create mock response with correct nested structure."""
        import json

        response = Mock()

        if node_ids is not None or workflow_names is not None:
            # ComponentSelection response - return JSON string
            response.text.return_value = json.dumps({
                "node_ids": node_ids or [],
                "workflow_names": workflow_names or [],
                "reasoning": "Test reasoning for component selection",
            })
        else:
            # WorkflowDecision response - return JSON string
            response.text.return_value = json.dumps({
                "found": found,
                "workflow_name": workflow_name,
                "confidence": confidence,
                "reasoning": "Test reasoning for decision",
            })
        return response

    return create_response


class TestComponentBrowsingSelection:
    """Tests for ComponentBrowsingNode selection logic."""

    def test_prep_loads_registry_and_context(self, mock_registry):
        """Test prep phase loads registry metadata and builds context.

        VALIDATES: Registry integration and dual-context building.
        The browsing node needs both node and workflow contexts to make
        informed selection decisions. This tests the preparation phase.
        """
        with (
            patch("pflow.planning.nodes.Registry") as mock_reg_class,
            patch("pflow.planning.nodes.build_nodes_context") as mock_build_nodes,
            patch("pflow.planning.nodes.build_workflows_context") as mock_build_workflows,
        ):
            mock_reg_class.return_value = mock_registry
            mock_build_nodes.return_value = "nodes context"
            mock_build_workflows.return_value = "workflows context"

            node = ComponentBrowsingNode()
            node.wait = 0  # Speed up tests
            shared = {"user_input": "process files"}

            result = node.prep(shared)

            assert result["user_input"] == "process files"
            assert result["nodes_context"] == "nodes context"
            assert result["workflows_context"] == "workflows context"
            assert result["registry_metadata"] == mock_registry.load()
            assert result["model_name"] == "anthropic/claude-sonnet-4-0"  # Default model
            assert result["temperature"] == 0.0  # Default temperature

            mock_build_nodes.assert_called_once_with(node_ids=None, registry_metadata=mock_registry.load())
            mock_build_workflows.assert_called_once_with(workflow_names=None, workflow_manager=None)

    def test_exec_extracts_nested_response_correctly(self, mock_llm_response_nested):
        """CRITICAL TEST: Verify nested response extraction for component selection.

        VALIDATES: ComponentSelection response parsing.
        The LLM returns selected node IDs and workflow names in a nested
        structure that must be correctly extracted for planning context.
        NOTE: Workflows are now cleared from the result until nested workflow
        execution is supported (Task 59).
        """
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(
                node_ids=["read-file", "llm", "write-file"], workflow_names=["data-pipeline", "text-processor"]
            )
            mock_get_model.return_value = mock_model

            node = ComponentBrowsingNode()
            node.wait = 0  # Speed up tests
            prep_res = {
                "user_input": "process CSV and generate report",
                "nodes_context": "test nodes context",
                "workflows_context": "test workflows context",
                "registry_metadata": {},
                "model_name": "anthropic/claude-sonnet-4-0",
                "temperature": 0.0,
            }

            result = node.exec(prep_res)

            # Verify lazy loading of model happens in exec
            mock_get_model.assert_called_once_with("anthropic/claude-sonnet-4-0")

            # Verify nested extraction worked
            assert result["node_ids"] == ["read-file", "llm", "write-file"]
            # Workflows are now cleared to prevent them from being used as nodes
            # until nested workflow execution is supported (Task 59)
            assert result["workflow_names"] == []
            assert result["reasoning"] == "Test reasoning for component selection"

    def test_post_always_routes_to_generate(self):
        """Test post always routes to 'generate' for Path B continuation.

        VALIDATES: Path B flow continuation.
        ComponentBrowsingNode always routes to 'generate' action,
        ensuring Path B continues to workflow generation.
        """
        with patch("pflow.planning.nodes.build_planning_context") as mock_build:
            mock_build.return_value = "detailed planning context"

            node = ComponentBrowsingNode()
            node.wait = 0  # Speed up tests
            shared = {}
            prep_res = {"registry_metadata": {"test": "metadata"}}
            exec_res = {
                "node_ids": ["read-file", "llm"],
                "workflow_names": ["pipeline"],
                "reasoning": "Selected components",
            }

            action = node.post(shared, prep_res, exec_res)

            assert action == "generate"  # Always routes to generate
            assert shared["browsed_components"] == exec_res
            assert shared["registry_metadata"] == {"test": "metadata"}
            assert shared["planning_context"] == "detailed planning context"

    def test_post_builds_planning_context_with_selections(self):
        """Test post correctly calls build_planning_context with selections.

        VALIDATES: Planning context generation for selected components.
        The selected node IDs are passed to build_planning_context, but
        workflow names are now always empty to prevent workflows from being
        used as nodes until nested workflow execution is supported (Task 59).
        """
        with patch("pflow.planning.nodes.build_planning_context") as mock_build:
            mock_build.return_value = "context"

            node = ComponentBrowsingNode()
            node.wait = 0  # Speed up tests
            shared = {}
            prep_res = {"registry_metadata": {"meta": "data"}}
            exec_res = {"node_ids": ["n1", "n2"], "workflow_names": ["w1"], "reasoning": "reason"}

            node.post(shared, prep_res, exec_res)

            # Verify workflow_names are now always passed as empty list
            # to prevent workflows from being used as nodes (Task 59)
            mock_build.assert_called_once_with(
                selected_node_ids=["n1", "n2"],
                selected_workflow_names=[],  # Always empty now
                registry_metadata={"meta": "data"},
                saved_workflows=None,
                workflow_manager=None,
            )
