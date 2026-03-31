"""Tests that error results are never served from the memoization cache.

Regression test for a bug where write_memo_cache hardcoded the action as
"default", causing error results to be cached as successes. The fix:
write_memo_cache now takes an action parameter and skips writing when
action == "error".

This test exercises the full WorkflowRunner pipeline with a real shell
node that always fails (exit 1), verifying that a second execution with
the same params and cache does NOT return a cached "success".
"""

from typing import Any

from pflow.execution.result import ExecutionResult, RunnerConfig
from pflow.execution.runner import WorkflowRunner


def test_error_results_not_served_from_cache() -> None:
    """A failing shell node must fail on every run, never served from cache.

    When a node returns the "error" action, write_memo_cache must skip
    the write. If it cached error results as "default" (the old bug),
    the second run would return success=True from cache — a silent
    correctness violation.

    Uses `exit 1` which always fails with a non-zero exit code.
    """
    workflow_ir: dict[str, Any] = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "fail_node", "type": "shell", "params": {"command": "exit 1"}}],
        "edges": [],
    }
    config = RunnerConfig(cache_enabled=True)

    # First execution — must fail
    result1: ExecutionResult = WorkflowRunner().run(workflow_ir, {}, config)
    assert result1.success is False, f"First run should fail, got success with shared: {result1.shared_after}"

    # Second execution — must ALSO fail, NOT served from cache
    result2: ExecutionResult = WorkflowRunner().run(workflow_ir, {}, config)
    assert result2.success is False, (
        "Second run should also fail. If it succeeded, error result was incorrectly cached and served as a success."
    )

    # Verify it was not served from cache (no cache hits for fail_node)
    cache_hits = result2.shared_after.get("__cache_hits__", [])
    assert "fail_node" not in cache_hits, (
        f"fail_node should not appear in cache hits, but found: {cache_hits}. "
        "Error results must never be written to the memoization cache."
    )
