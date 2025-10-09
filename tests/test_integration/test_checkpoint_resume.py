"""Integration test for checkpoint-based workflow resume after repair.

This is the CRITICAL test that verifies:
1. Workflow fails at node 3
2. Repair fixes the issue
3. Execution resumes from node 3 (nodes 1-2 show "↻ cached")
4. No duplicate side effects
"""

from typing import Any
from unittest.mock import patch

from pflow.execution.workflow_execution import execute_workflow
from pocketflow import Node


class CountingNode(Node):
    """Node that increments a counter to track executions."""

    # Class variable to track total executions
    total_executions = 0

    @classmethod
    def reset_counts(cls):
        """Reset execution counts for testing."""
        cls.total_executions = 0

    def __init__(self):
        super().__init__()

    def exec(self, prep_res: dict) -> str:
        """Execute and track execution count."""
        # Simply increment the total counter
        CountingNode.total_executions += 1
        return f"executed_{CountingNode.total_executions}"

    def post(self, shared: dict, prep_res: dict, exec_res: str) -> str:
        """Store result and return action."""
        # Store result in shared store (will be namespaced by wrapper)
        shared["result"] = exec_res
        shared["count"] = CountingNode.total_executions

        return "default"


class FailingNode(Node):
    """Node that fails with a template error."""

    def __init__(self):
        super().__init__()

    def exec(self, prep_res: dict) -> None:
        """Simulate template resolution failure."""
        raise ValueError("Template ${node2.missing_field} not found. Available fields: result, count")

    def post(self, shared: dict, prep_res: dict, exec_res: Any) -> str:
        """Never reached due to error."""
        return "error"


class TestCheckpointResume:
    """Test checkpoint-based resume after repair."""

    def setup_method(self):
        """Reset node execution counts before each test."""
        CountingNode.reset_counts()

    def test_resume_without_re_execution(self):
        """THE CRITICAL TEST: Verify nodes are not re-executed after repair.

        This test verifies the core innovation of Task 68:
        1. Nodes that succeeded are NOT re-executed
        2. Checkpoint data preserves exact state
        3. Resume continues from failure point
        """
        # Create a workflow that will fail at node3
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "node1", "type": "counting", "params": {}},
                {"id": "node2", "type": "counting", "params": {}},
                {"id": "node3", "type": "failing", "params": {}},  # Will fail here
                {"id": "node4", "type": "counting", "params": {}},
            ],
            "edges": [
                {"from": "node1", "to": "node2"},
                {"from": "node2", "to": "node3"},
                {"from": "node3", "to": "node4"},
            ],
        }

        # Fixed workflow (repair would produce this)
        fixed_workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "node1", "type": "counting", "params": {}},
                {"id": "node2", "type": "counting", "params": {}},
                {"id": "node3", "type": "counting", "params": {}},  # Fixed: now counting
                {"id": "node4", "type": "counting", "params": {}},
            ],
            "edges": [
                {"from": "node1", "to": "node2"},
                {"from": "node2", "to": "node3"},
                {"from": "node3", "to": "node4"},
            ],
        }

        # Mock registry to provide our test nodes
        with patch("pflow.registry.Registry"):

            def get_node_class(node_type, registry):
                # Registry argument is required but not used in test
                if node_type == "counting":
                    return CountingNode
                elif node_type == "failing":
                    return FailingNode
                raise ValueError(f"Unknown node type: {node_type}")

            # Mock the registry to return our test nodes and repair service to return fixed workflow
            with (
                patch("pflow.runtime.compiler.import_node_class", side_effect=get_node_class),
                patch("pflow.execution.workflow_execution.repair_workflow_with_validation") as mock_repair,
            ):
                mock_repair.return_value = (True, fixed_workflow_ir, [])

                # Execute workflow with repair enabled
                result = execute_workflow(
                    workflow_ir=workflow_ir,
                    execution_params={},
                    enable_repair=True,
                    original_request="Test workflow",
                )

                # Verify repair was called
                mock_repair.assert_called_once()

                # CRITICAL ASSERTIONS:

                # 1. Workflow should succeed after repair
                assert result.success is True

                # 2. Check total execution counts
                # First execution: node1, node2 succeed, node3 fails
                # Second execution (after repair): node1, node2 SKIPPED, node3, node4 succeed
                # Total: 4 nodes executed (2 in first run, 2 in second run)
                assert CountingNode.total_executions == 4, (
                    f"Expected 4 total executions, got {CountingNode.total_executions}."
                )

                # 4. Checkpoint data should be preserved in shared store
                assert "__execution__" in result.shared_after
                checkpoint = result.shared_after["__execution__"]

                # All nodes should be marked as completed
                assert set(checkpoint["completed_nodes"]) == {"node1", "node2", "node3", "node4"}

                # Checkpoint should have node_hashes field (new in refactor)
                assert "node_hashes" in checkpoint

                # 5. Original execution results should be preserved
                # Nodes store their results in namespaced sections
                assert "node1" in result.shared_after
                assert "result" in result.shared_after["node1"]
                assert "node2" in result.shared_after
                assert "result" in result.shared_after["node2"]
                # Check that node3 and node4 also executed (after repair)
                assert "node3" in result.shared_after
                assert "result" in result.shared_after["node3"]
                assert "node4" in result.shared_after
                assert "result" in result.shared_after["node4"]

    def test_resume_with_checkpoint_display(self):
        """Test that cached nodes show proper progress indicators."""
        # Track progress callbacks
        progress_events = []

        def mock_progress_callback(node_id: str, event: str, duration: Any, depth: int, **kwargs):
            # Accept any additional kwargs to handle different callback signatures
            progress_events.append((node_id, event))

        # Simulate checkpoint data from previous execution
        checkpoint_data = {
            "__execution__": {
                "completed_nodes": ["node1", "node2"],
                "node_actions": {"node1": "default", "node2": "default"},
                "node_hashes": {
                    # We'll mock the hash computation to return these values
                    "node1": "hash1",
                    "node2": "hash2",
                },
                "failed_node": "node3",
            },
            "__progress_callback__": mock_progress_callback,
            "node1": {"data": "result1"},
            "node2": {"data": "result2"},
        }

        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "node1", "type": "counting", "params": {}},
                {"id": "node2", "type": "counting", "params": {}},
                {"id": "node3", "type": "counting", "params": {}},
            ],
            "edges": [
                {"from": "node1", "to": "node2"},
                {"from": "node2", "to": "node3"},
            ],
        }

        with patch("pflow.registry.Registry"):

            def get_node_class(node_type, registry):
                return CountingNode

            with patch("pflow.runtime.compiler.import_node_class", side_effect=get_node_class):
                # Mock the hash computation to match our checkpoint
                def mock_compute_hash(self, config):
                    # Return hash that matches our checkpoint
                    if self.node_id == "node1":
                        return "hash1"
                    elif self.node_id == "node2":
                        return "hash2"
                    else:
                        return "hash3"

                with patch(
                    "pflow.runtime.instrumented_wrapper.InstrumentedNodeWrapper._compute_config_hash", mock_compute_hash
                ):
                    # Execute with resume state
                    _ = execute_workflow(
                        workflow_ir=workflow_ir,
                        execution_params={},
                        enable_repair=False,  # No repair needed, just resume
                        resume_state=checkpoint_data,
                    )

                # Check that cached events were fired for completed nodes
                cached_events = [(nid, evt) for nid, evt in progress_events if evt == "node_cached"]

                # Should have cached events for node1 and node2
                assert ("node1", "node_cached") in cached_events
                assert ("node2", "node_cached") in cached_events

                # node3 should have normal execution events
                assert ("node3", "node_start") in progress_events
                assert ("node3", "node_complete") in progress_events

    def test_no_repair_when_disabled(self):
        """Test that repair is skipped when disabled."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "node1", "type": "failing", "params": {}},
            ],
            "edges": [],  # Required even if empty
        }

        with patch("pflow.registry.Registry"):

            def get_node_class(node_type, registry):
                # Registry argument is required but not used in test
                if node_type == "failing":
                    return FailingNode
                return CountingNode

            with (
                patch("pflow.runtime.compiler.import_node_class", side_effect=get_node_class),
                patch("pflow.execution.workflow_execution.repair_workflow_with_validation") as mock_repair,
            ):
                # Execute with repair disabled
                result = execute_workflow(
                    workflow_ir=workflow_ir,
                    execution_params={},
                    enable_repair=False,  # Disabled
                )

                # Should fail without attempting repair
                assert result.success is False
                mock_repair.assert_not_called()

    def test_repair_failure_returns_original_error(self):
        """Test that repair failure returns the original error."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "node1", "type": "failing", "params": {}},
            ],
            "edges": [],  # Required even if empty
        }

        with patch("pflow.registry.Registry"):

            def get_node_class(node_type, registry):
                # Registry argument is required but not used in test
                if node_type == "failing":
                    return FailingNode
                return CountingNode

            with (
                patch("pflow.runtime.compiler.import_node_class", side_effect=get_node_class),
                # Mock validation to pass so we get to runtime errors
                patch("pflow.core.workflow_validator.WorkflowValidator.validate", return_value=([], [])),
                patch("pflow.execution.workflow_execution.repair_workflow_with_validation") as mock_repair,
            ):
                # Repair fails (returns success, repaired_ir, errors)
                mock_repair.return_value = (False, None, [])

                result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=True)

                # Should return original failure
                assert result.success is False
                assert len(result.errors) > 0
                # The error should be about the template since the FailingNode raises a template error
                assert "Template" in result.errors[0]["message"]
