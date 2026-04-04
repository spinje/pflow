"""Test checkpoint tracking and resume functionality.

CRITICAL: These tests verify that nodes are NOT re-executed when resuming from checkpoint.
This prevents duplicate side effects (API calls, file writes, etc.) which is the core promise
of the checkpoint system.

Migrated from wrapper-based tests to standalone instrumentation functions and
compile_workflow + WorkflowEngine tests after the wrappers were replaced by
the engine (Task 135/138).

Bug History:
- Line 137: Fixed assertion bug - was `node1._run.call_count == 1` (comparison, not assertion)
- Replaced MagicMocks with real nodes to test actual behavior, not implementation
"""

from typing import Any
from unittest.mock import patch

from pflow.runtime.engine.instrumentation import (
    cache_result,
    check_cache_validity,
    compute_config_hash,
    compute_node_config,
    enforce_loop_guard,
    handle_cached_execution,
    initialize_execution_state,
)


class TestCheckpointTracking:
    """Test checkpoint tracking with standalone instrumentation functions."""

    def test_checkpoint_structure_initialization(self):
        """Test that checkpoint structure is properly initialized."""
        shared: dict[str, Any] = {}
        initialize_execution_state(shared)

        assert "__execution__" in shared, "Checkpoint structure not initialized"
        checkpoint = shared["__execution__"]
        assert "completed_nodes" in checkpoint
        assert "node_actions" in checkpoint
        assert "failed_node" in checkpoint
        assert checkpoint["completed_nodes"] == []
        assert checkpoint["node_actions"] == {}
        assert checkpoint["failed_node"] is None

    def test_cache_result_records_completion(self):
        """Test that cache_result properly records node completion."""
        shared: dict[str, Any] = {}
        initialize_execution_state(shared)

        cache_result("test_node", "hash123", "success", shared)

        checkpoint = shared["__execution__"]
        assert "test_node" in checkpoint["completed_nodes"]
        assert checkpoint["node_actions"]["test_node"] == "success"
        assert checkpoint["node_hashes"]["test_node"] == "hash123"
        assert checkpoint["failed_node"] is None

    def test_no_reexecution_for_completed_nodes(self):
        """CRITICAL TEST: Verify completed nodes return cached action on second check."""
        shared: dict[str, Any] = {}
        initialize_execution_state(shared)

        # First execution: mark node as completed
        config_hash = compute_config_hash(compute_node_config("TestNode", {"value": "hello"}, {}, None))
        cache_result("api_call_node", config_hash, "success", shared)

        # Second check: should be a cache hit
        cached, cached_action = check_cache_validity("api_call_node", config_hash, shared)

        assert cached is True, "Completed node should be a cache hit"
        assert cached_action == "success", "Cached action should match"

    def test_cache_invalid_on_config_change(self):
        """Test that cache is invalidated when node config changes."""
        shared: dict[str, Any] = {}
        initialize_execution_state(shared)

        # Mark completed with one config
        old_hash = compute_config_hash(compute_node_config("TestNode", {"value": "hello"}, {}, None))
        cache_result("test_node", old_hash, "success", shared)

        # Check with different config
        new_hash = compute_config_hash(compute_node_config("TestNode", {"value": "changed"}, {}, None))
        cached, _cached_action = check_cache_validity("test_node", new_hash, shared)

        assert cached is False, "Should be cache miss when config changes"

    def test_failed_node_tracking(self):
        """Test that failed nodes are properly recorded for repair."""
        shared: dict[str, Any] = {}
        initialize_execution_state(shared)

        # Record an error result
        cache_result("payment_processor", "hash123", "error", shared)

        checkpoint = shared["__execution__"]
        assert checkpoint["failed_node"] == "payment_processor"
        assert "payment_processor" not in checkpoint["completed_nodes"]

    def test_resume_workflow_simulation(self):
        """Integration test: Simulate workflow resume after repair.

        Three nodes: fetch_data, process_data, save_results.
        First two complete successfully. On resume, they should be cache hits.
        Third node completes on the resumed run.
        """
        shared: dict[str, Any] = {}
        initialize_execution_state(shared)

        config_hash_1 = compute_config_hash(compute_node_config("FetchNode", {}, {}, None))
        config_hash_2 = compute_config_hash(compute_node_config("ProcessNode", {}, {}, None))
        config_hash_3 = compute_config_hash(compute_node_config("SaveNode", {}, {}, None))

        # Initial execution - nodes 1 and 2 succeed
        cache_result("fetch_data", config_hash_1, "success", shared)
        cache_result("process_data", config_hash_2, "success", shared)

        # Mark node 3 as failed
        shared["__execution__"]["failed_node"] = "save_results"

        # Verify state before resume
        assert len(shared["__execution__"]["completed_nodes"]) == 2
        assert "fetch_data" in shared["__execution__"]["completed_nodes"]
        assert "process_data" in shared["__execution__"]["completed_nodes"]

        # SIMULATE RESUME: check nodes 1 and 2 are cached
        cached_1, action_1 = check_cache_validity("fetch_data", config_hash_1, shared)
        cached_2, action_2 = check_cache_validity("process_data", config_hash_2, shared)

        assert cached_1 is True, "Node 1 should be cached on resume"
        assert action_1 == "success"
        assert cached_2 is True, "Node 2 should be cached on resume"
        assert action_2 == "success"

        # Node 3 should NOT be cached
        cached_3, _ = check_cache_validity("save_results", config_hash_3, shared)
        assert cached_3 is False, "Failed node should not be cached"

        # After node 3 executes successfully on resume
        cache_result("save_results", config_hash_3, "success", shared)
        assert len(shared["__execution__"]["completed_nodes"]) == 3

    def test_progress_callback_shows_cached_indicator(self):
        """Test that cached nodes trigger 'node_start' and 'node_cached' callbacks."""
        events: list[tuple[str, str]] = []

        def track_progress(node_id: str, event: str, duration: Any, depth: int, **kwargs: Any) -> None:
            events.append((node_id, event))

        config_hash = compute_config_hash(compute_node_config("SideEffectNode", {}, {}, None))

        shared: dict[str, Any] = {
            "__execution__": {
                "completed_nodes": ["test_node"],
                "node_actions": {"test_node": "success"},
                "node_hashes": {"test_node": config_hash},
                "failed_node": None,
                "node_visit_counts": {},
            },
            "__cache_hits__": [],
            "__progress_callback__": track_progress,
        }

        # Simulate cached execution via handle_cached_execution
        handle_cached_execution(
            "test_node",
            shared,
            "success",
            set(shared.keys()),
            "SideEffectNode",
            {},
            None,  # no trace collector
        )

        # The implementation sends both "node_start" and "node_cached" for cached nodes
        assert ("test_node", "node_start") in events
        assert ("test_node", "node_cached") in events
        # But doesn't fire "node_complete" (that would mean re-execution)
        assert ("test_node", "node_complete") not in events

    def test_loop_guard_invalidates_cache_for_revisited_nodes(self):
        """Test that the loop guard invalidates cache for revisited nodes."""
        shared: dict[str, Any] = {}
        initialize_execution_state(shared)

        config_hash = compute_config_hash(compute_node_config("TestNode", {}, {}, None))
        cache_result("retry_node", config_hash, "success", shared)

        # First visit: visit_count=1 (normal)
        enforce_loop_guard("retry_node", shared)
        cached, _ = check_cache_validity("retry_node", config_hash, shared)
        assert cached is True, "First visit should see cache hit"

        # Second visit: visit_count=2, cache should be invalidated
        enforce_loop_guard("retry_node", shared)
        cached, _ = check_cache_validity("retry_node", config_hash, shared)
        assert cached is False, "Revisited node should have invalidated cache"


class TestCheckpointIntegration:
    """Integration tests for checkpoint with real workflow scenarios."""

    def test_repair_and_resume_with_mocked_flow(self):
        """Test that checkpoint tracking works during execution."""

        from pflow.execution.result import ExecutionResult, RunnerConfig
        from pflow.execution.runner import WorkflowRunner

        # Simple test: verify that when repair is disabled, execution doesn't attempt repair
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "node1", "type": "shell", "params": {"command": "printf '%s' 'Step 1'"}},
            ],
        }

        # Create successful execution result
        success_result = ExecutionResult(
            success=True,
            diagnostics=[],
            shared_after={
                "result": "success",
                "__execution__": {"completed_nodes": ["node1"], "node_actions": {"node1": "success"}},
            },
        )

        # Mock _compile_and_execute to return controlled result
        with patch.object(WorkflowRunner, "_compile_and_execute", return_value=success_result) as mock_execute:
            result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

            # Verify execution happened
            assert mock_execute.called

            # Result should be successful
            assert result.success is True
            # Verify checkpoint was created
            assert "node1" in result.shared_after["__execution__"]["completed_nodes"]
