"""Tests for workflow post-processing and auto-fix functionality."""

import pytest

from src.pflow.planning.nodes import WorkflowGeneratorNode


@pytest.fixture
def workflow_generator_node():
    """Create a WorkflowGeneratorNode instance for testing."""
    return WorkflowGeneratorNode()


class TestRemoveUnusedInputs:
    """Test the automatic removal of unused inputs."""

    def test_removes_single_unused_input(self, workflow_generator_node):
        """Test that a single unused input is removed."""
        workflow = {
            "inputs": {
                "used_input": {"type": "string", "description": "Used"},
                "unused_input": {"type": "string", "description": "Not used"},
            },
            "nodes": [{"id": "node1", "type": "test", "params": {"value": "${used_input}"}}],
        }

        result = workflow_generator_node._remove_unused_inputs(workflow)

        assert "used_input" in result["inputs"]
        assert "unused_input" not in result["inputs"]
        assert len(result["inputs"]) == 1

    def test_removes_multiple_unused_inputs(self, workflow_generator_node):
        """Test that multiple unused inputs are removed."""
        workflow = {
            "inputs": {
                "used": {"type": "string"},
                "unused1": {"type": "string"},
                "unused2": {"type": "string"},
                "unused3": {"type": "string"},
            },
            "nodes": [{"id": "node1", "type": "test", "params": {"data": "${used}"}}],
        }

        result = workflow_generator_node._remove_unused_inputs(workflow)

        assert "used" in result["inputs"]
        assert "unused1" not in result["inputs"]
        assert "unused2" not in result["inputs"]
        assert "unused3" not in result["inputs"]
        assert len(result["inputs"]) == 1

    def test_removes_inputs_key_when_empty(self, workflow_generator_node):
        """Test that the inputs key is removed entirely when all inputs are unused."""
        workflow = {
            "inputs": {"unused1": {"type": "string"}, "unused2": {"type": "string"}},
            "nodes": [{"id": "node1", "type": "test", "params": {"value": "hardcoded"}}],
        }

        result = workflow_generator_node._remove_unused_inputs(workflow)

        assert "inputs" not in result

    def test_handles_nested_template_usage(self, workflow_generator_node):
        """Test that inputs used in nested structures are detected."""
        workflow = {
            "inputs": {"api_key": {"type": "string"}, "unused": {"type": "string"}},
            "nodes": [{"id": "node1", "type": "test", "params": {"headers": {"Authorization": "Bearer ${api_key}"}}}],
        }

        result = workflow_generator_node._remove_unused_inputs(workflow)

        assert "api_key" in result["inputs"]
        assert "unused" not in result["inputs"]

    def test_handles_list_template_usage(self, workflow_generator_node):
        """Test that inputs used in lists are detected."""
        workflow = {
            "inputs": {"item1": {"type": "string"}, "item2": {"type": "string"}, "unused": {"type": "string"}},
            "nodes": [{"id": "node1", "type": "test", "params": {"items": ["${item1}", "${item2}"]}}],
        }

        result = workflow_generator_node._remove_unused_inputs(workflow)

        assert "item1" in result["inputs"]
        assert "item2" in result["inputs"]
        assert "unused" not in result["inputs"]

    def test_distinguishes_inputs_from_node_refs(self, workflow_generator_node):
        """Test that node references are not mistaken for inputs."""
        workflow = {
            "inputs": {"real_input": {"type": "string"}, "unused": {"type": "string"}},
            "nodes": [
                {"id": "node1", "type": "test", "params": {"value": "${real_input}"}},
                {
                    "id": "node2",
                    "type": "test",
                    "params": {"data": "${node1.output}"},  # node reference, not input
                },
            ],
        }

        result = workflow_generator_node._remove_unused_inputs(workflow)

        assert "real_input" in result["inputs"]
        assert "unused" not in result["inputs"]
        # Should not incorrectly add "node1" as an input

    def test_handles_workflow_outputs(self, workflow_generator_node):
        """Test that inputs used in workflow outputs are detected."""
        workflow = {
            "inputs": {"output_input": {"type": "string"}, "unused": {"type": "string"}},
            "nodes": [{"id": "node1", "type": "test", "params": {"value": "test"}}],
            "outputs": {"final": "${output_input}"},
        }

        result = workflow_generator_node._remove_unused_inputs(workflow)

        assert "output_input" in result["inputs"]
        assert "unused" not in result["inputs"]

    def test_handles_no_inputs(self, workflow_generator_node):
        """Test that workflows without inputs are handled gracefully."""
        workflow = {"nodes": [{"id": "node1", "type": "test", "params": {"value": "test"}}]}

        result = workflow_generator_node._remove_unused_inputs(workflow)

        assert "inputs" not in result
        assert result == workflow  # Should be unchanged

    def test_handles_empty_inputs(self, workflow_generator_node):
        """Test that empty inputs dict is handled gracefully."""
        workflow = {"inputs": {}, "nodes": [{"id": "node1", "type": "test", "params": {"value": "test"}}]}

        result = workflow_generator_node._remove_unused_inputs(workflow)

        assert "inputs" not in result


class TestFixMissingEdges:
    """Test the automatic addition of edges for single-node workflows."""

    def test_adds_edges_for_single_node(self, workflow_generator_node):
        """Test that empty edges are added for single-node workflows."""
        workflow = {
            "nodes": [{"id": "only_node", "type": "test", "params": {"value": "test"}}]
            # Note: no edges key
        }

        result = workflow_generator_node._fix_missing_edges(workflow)

        assert "edges" in result
        assert result["edges"] == []

    def test_does_not_add_edges_for_multi_node(self, workflow_generator_node):
        """Test that edges are NOT added for multi-node workflows."""
        workflow = {
            "nodes": [{"id": "node1", "type": "test"}, {"id": "node2", "type": "test"}]
            # Note: no edges key - this is an error!
        }

        result = workflow_generator_node._fix_missing_edges(workflow)

        assert "edges" not in result  # Should NOT auto-add

    def test_preserves_existing_edges(self, workflow_generator_node):
        """Test that existing edges are preserved."""
        workflow = {
            "nodes": [{"id": "node1", "type": "test"}],
            "edges": [{"from": "node1", "to": "node2"}],  # Even if invalid
        }

        result = workflow_generator_node._fix_missing_edges(workflow)

        assert "edges" in result
        assert result["edges"] == [{"from": "node1", "to": "node2"}]

    def test_handles_empty_workflow(self, workflow_generator_node):
        """Test that empty workflows are handled gracefully."""
        workflow = {}

        result = workflow_generator_node._fix_missing_edges(workflow)

        assert "edges" not in result
        assert result == workflow

    def test_handles_no_nodes(self, workflow_generator_node):
        """Test that workflows without nodes are handled gracefully."""
        workflow = {"nodes": []}

        result = workflow_generator_node._fix_missing_edges(workflow)

        assert "edges" not in result


class TestPostProcessWorkflow:
    """Test the complete post-processing pipeline."""

    def test_complete_post_processing(self, workflow_generator_node):
        """Test that all post-processing steps work together."""
        workflow = {
            "inputs": {"used_input": {"type": "string"}, "unused_input": {"type": "string"}},
            "nodes": [{"id": "only_node", "type": "test", "params": {"value": "${used_input}"}}],
            # Note: no edges, no ir_version
        }

        result = workflow_generator_node._post_process_workflow(workflow)

        # Check all three fixes were applied
        assert result["ir_version"] == "1.0.0"  # Added
        assert "used_input" in result["inputs"]  # Kept
        assert "unused_input" not in result["inputs"]  # Removed
        assert result["edges"] == []  # Added for single node

    def test_handles_empty_workflow(self, workflow_generator_node):
        """Test that empty workflows pass through unchanged."""
        workflow = {}

        result = workflow_generator_node._post_process_workflow(workflow)

        assert result == {}

    def test_handles_none_workflow(self, workflow_generator_node):
        """Test that None workflows are handled gracefully."""
        result = workflow_generator_node._post_process_workflow(None)

        assert result is None

    def test_preserves_other_fields(self, workflow_generator_node):
        """Test that unrelated fields are preserved."""
        workflow = {
            "name": "Test Workflow",
            "description": "A test",
            "metadata": {"author": "test"},
            "nodes": [{"id": "node1", "type": "test"}],
        }

        result = workflow_generator_node._post_process_workflow(workflow)

        assert result["name"] == "Test Workflow"
        assert result["description"] == "A test"
        assert result["metadata"] == {"author": "test"}
        assert result["ir_version"] == "1.0.0"
        assert result["edges"] == []
