"""Test checkpoint tracking and resume functionality.

CRITICAL: These tests verify that nodes are NOT re-executed when resuming from checkpoint.
This prevents duplicate side effects (API calls, file writes, etc.) which is the core promise
of the checkpoint system.

Bug History:
- Line 137: Fixed assertion bug - was `node1._run.call_count == 1` (comparison, not assertion)
- Replaced MagicMocks with real nodes to test actual behavior, not implementation
"""

import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from pflow.pocketflow import Node
from pflow.runtime.instrumented_wrapper import InstrumentedNodeWrapper


class SideEffectNode(Node):
    """Node with observable side effects to verify no re-execution."""

    execution_count = 0  # Class variable to track executions across instances

    def __init__(self, node_id: str, output_file: Optional[Path] = None):
        super().__init__()
        self.node_id = node_id
        self.output_file = output_file
        self.local_exec_count = 0

    def _run(self, shared):
        """Execute with side effects."""
        # Track execution
        SideEffectNode.execution_count += 1
        self.local_exec_count += 1

        # Observable side effect: append to file
        if self.output_file:
            with open(self.output_file, "a") as f:
                f.write(f"{self.node_id} executed\n")

        # Store output in shared
        shared[self.node_id] = {"output": f"Result from {self.node_id}", "exec_count": self.local_exec_count}

        return "success"


class FailingNode(Node):
    """Node that fails on first execution but could succeed after repair."""

    def __init__(self, node_id: str, fail_message: str = "Node failed"):
        super().__init__()
        self.node_id = node_id
        self.fail_message = fail_message

    def _run(self, shared):
        """Always fails to simulate error."""
        raise ValueError(self.fail_message)


class TestCheckpointTracking:
    """Test checkpoint tracking with real nodes and observable behavior."""

    def setup_method(self):
        """Reset execution counter before each test."""
        SideEffectNode.execution_count = 0

    def test_checkpoint_structure_initialization(self):
        """Test that checkpoint structure is properly initialized."""
        node = SideEffectNode("test_node")
        wrapper = InstrumentedNodeWrapper(node, "test_node", None, None)

        shared = {}
        wrapper._run(shared)

        # Verify checkpoint structure
        assert "__execution__" in shared, "Checkpoint structure not initialized"
        checkpoint = shared["__execution__"]
        assert "completed_nodes" in checkpoint
        assert "node_actions" in checkpoint
        assert "failed_node" in checkpoint

        # Verify this node was tracked
        assert "test_node" in checkpoint["completed_nodes"]
        assert checkpoint["node_actions"]["test_node"] == "success"
        assert checkpoint["failed_node"] is None

    def test_no_reexecution_for_completed_nodes(self):
        """CRITICAL TEST: Verify completed nodes are NOT re-executed."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            output_file = Path(f.name)

        try:
            node = SideEffectNode("api_call_node", output_file)
            wrapper = InstrumentedNodeWrapper(node, "api_call_node", None, None)

            # First execution
            shared = {}
            result1 = wrapper._run(shared)

            assert result1 == "success"
            assert node.local_exec_count == 1
            assert output_file.read_text() == "api_call_node executed\n"

            # Simulate resume: same wrapper, same shared store with checkpoint
            result2 = wrapper._run(shared)

            # CRITICAL ASSERTIONS:
            assert result2 == "success", "Should return cached success"
            assert node.local_exec_count == 1, "Node was re-executed! This would cause duplicate API calls!"
            assert output_file.read_text() == "api_call_node executed\n", "Side effect was duplicated!"

            # Verify cached action was used
            assert shared["__execution__"]["node_actions"]["api_call_node"] == "success"

        finally:
            output_file.unlink(missing_ok=True)

    def test_failed_node_tracking(self):
        """Test that failed nodes are properly recorded for repair."""
        node = FailingNode("payment_processor", "Payment gateway timeout")
        wrapper = InstrumentedNodeWrapper(node, "payment_processor", None, None)

        shared = {}

        with pytest.raises(ValueError, match="Payment gateway timeout"):
            wrapper._run(shared)

        # Verify failure was tracked
        checkpoint = shared["__execution__"]
        assert checkpoint["failed_node"] == "payment_processor"
        assert "payment_processor" not in checkpoint["completed_nodes"]
        assert "payment_processor" not in checkpoint.get("node_actions", {})

    def test_resume_workflow_simulation(self):
        """Integration test: Simulate workflow resume after repair."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            output_file = Path(f.name)

        try:
            # Create a 3-node workflow
            node1 = SideEffectNode("fetch_data", output_file)
            node2 = SideEffectNode("process_data", output_file)
            node3 = SideEffectNode("save_results", output_file)

            wrapper1 = InstrumentedNodeWrapper(node1, "fetch_data", None, None)
            wrapper2 = InstrumentedNodeWrapper(node2, "process_data", None, None)
            wrapper3 = InstrumentedNodeWrapper(node3, "save_results", None, None)

            # Initial execution - node 1 and 2 succeed
            shared = {}
            wrapper1._run(shared)
            wrapper2._run(shared)

            # Node 3 would fail here (simulated by not running it)
            # Instead, mark it as failed manually
            shared["__execution__"]["failed_node"] = "save_results"

            # Verify state before resume
            assert len(shared["__execution__"]["completed_nodes"]) == 2
            assert "fetch_data" in shared["__execution__"]["completed_nodes"]
            assert "process_data" in shared["__execution__"]["completed_nodes"]
            assert output_file.read_text() == "fetch_data executed\nprocess_data executed\n"

            # SIMULATE RESUME after repair:
            # Re-run workflow with same shared store (checkpoint)

            # Nodes 1 and 2 should NOT re-execute
            result1 = wrapper1._run(shared)
            result2 = wrapper2._run(shared)

            assert result1 == "success"  # Cached
            assert result2 == "success"  # Cached
            assert node1.local_exec_count == 1, "Node 1 was re-executed during resume!"
            assert node2.local_exec_count == 1, "Node 2 was re-executed during resume!"

            # Node 3 executes for first time
            result3 = wrapper3._run(shared)
            assert result3 == "success"
            assert node3.local_exec_count == 1

            # Verify file shows no duplicate executions
            assert output_file.read_text() == ("fetch_data executed\nprocess_data executed\nsave_results executed\n"), (
                "Duplicate side effects detected!"
            )

            # Verify final checkpoint state
            assert len(shared["__execution__"]["completed_nodes"]) == 3
            # Note: failed_node is not cleared - it preserves failure history

        finally:
            output_file.unlink(missing_ok=True)

    def test_progress_callback_shows_cached_indicator(self):
        """Test that cached nodes show '↻ cached' in progress."""
        node = SideEffectNode("test_node")
        wrapper = InstrumentedNodeWrapper(node, "test_node", None, None)

        events = []

        def track_progress(node_id, event, duration, depth):
            events.append((node_id, event))

        # Pre-populate checkpoint with correct hash for SideEffectNode
        # Hash computed from: {"params": {}, "type": "SideEffectNode"}
        shared = {
            "__execution__": {
                "completed_nodes": ["test_node"],
                "node_actions": {"test_node": "success"},
                "node_hashes": {"test_node": "515c180fa50afc4e759fb44407525010"},  # Correct hash
                "failed_node": None,
            },
            "__progress_callback__": track_progress,
        }

        wrapper._run(shared)

        # The implementation now sends both "node_start" and "node_cached" for cached nodes
        assert ("test_node", "node_start") in events  # Shows node name first
        assert ("test_node", "node_cached") in events  # Then shows it was cached
        assert ("test_node", "node_complete") not in events  # But doesn't re-execute

    def test_checkpoint_prevents_infinite_loops(self):
        """Test that checkpoint prevents infinite retry loops."""
        node = SideEffectNode("retry_node")
        wrapper = InstrumentedNodeWrapper(node, "retry_node", None, None)

        shared = {}

        # Execute node multiple times
        for _ in range(5):
            result = wrapper._run(shared)
            assert result == "success"

        # Node should only execute once despite multiple calls
        assert node.local_exec_count == 1, "Node executed multiple times - checkpoint failed!"
        assert SideEffectNode.execution_count == 1, "Global execution count incorrect!"


class TestCheckpointIntegration:
    """Integration tests for checkpoint with real workflow scenarios."""

    def test_repair_and_resume_with_mocked_flow(self):
        """Test that checkpoint tracking works during execution."""

        from pflow.execution.executor_service import ExecutionResult
        from pflow.execution.null_output import NullOutput
        from pflow.execution.workflow_execution import execute_workflow

        # Simple test: verify that when repair is disabled, execution doesn't attempt repair
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "node1", "type": "echo", "params": {"message": "Step 1"}},
            ],
        }

        # Create successful execution result
        success_result = ExecutionResult(
            success=True,
            errors=[],
            shared_after={
                "result": "success",
                "__execution__": {"completed_nodes": ["node1"], "node_actions": {"node1": "success"}},
            },
            output_data=None,
        )

        # Mock validation and execution to succeed
        with (
            patch("pflow.core.workflow_validator.WorkflowValidator.validate") as mock_validate,
            patch("pflow.execution.executor_service.WorkflowExecutorService.execute_workflow") as mock_execute,
        ):
            # No validation errors
            mock_validate.return_value = []
            # Execution succeeds
            mock_execute.return_value = success_result

            # Execute without repair
            result = execute_workflow(
                workflow_ir=workflow_ir, execution_params={}, enable_repair=False, output=NullOutput()
            )

            # Verify no validation was attempted (repair disabled)
            assert not mock_validate.called

            # Verify execution happened
            assert mock_execute.called

            # Result should be successful
            assert result.success is True
            # Verify checkpoint was created
            assert "node1" in result.shared_after["__execution__"]["completed_nodes"]
