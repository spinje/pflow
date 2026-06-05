"""Tests for memoization cache integration via compile_workflow + WorkflowEngine.

Verifies that the engine correctly checks, restores, and stores results in the
MemoizationCache (SQLite-backed cross-run persistence). The memoization cache
sits between the loop guard and the in-process cache check in the engine's
_execute_node(), and is skipped for revisited nodes (visit_count > 1).

Migrated from compile_ir_to_flow shim to compile_workflow + WorkflowEngine
after the shim was deprecated (Task 135/138).
"""

from typing import Any

import pytest

from pflow.core.diagnostic import Diagnostic, Severity, warning_degrades_status
from pflow.runtime.cache import MemoizationCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_workflow(
    ir: dict[str, Any],
    cache: MemoizationCache,
    initial_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile and run a workflow with the given memoization cache.

    Returns the shared store after execution.
    """
    from pflow.registry import Registry
    from pflow.runtime import compile_workflow
    from pflow.runtime.engine import WorkflowEngine

    registry = Registry()
    workflow = compile_workflow(
        ir_json=ir,
        registry=registry,
        initial_params=initial_params,
    )

    shared: dict[str, Any] = {"__memoization_cache__": cache}
    if initial_params:
        shared.update({k: v for k, v in initial_params.items() if not k.startswith("__")})
    shared.update(workflow.resolved_defaults)

    engine = WorkflowEngine()
    engine.run(workflow, shared)
    return shared


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_memo_cache_miss_then_hit(tmp_path: Any) -> None:
    """First run executes the node; second run (fresh shared, same cache) restores from cache."""
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "my-node", "type": "shell", "cache": True, "params": {"command": "printf '%s' hello"}},
        ],
        "edges": [],
    }

    # --- First run: cache MISS, node must execute ---
    shared1 = _run_workflow(ir, cache)
    assert "my-node" in shared1
    assert shared1["my-node"]["stdout"] == "hello"

    # --- Second run: fresh shared, SAME cache ---
    shared2 = _run_workflow(ir, cache)
    # Output restored from cache
    assert "my-node" in shared2
    assert shared2["my-node"]["stdout"] == "hello"


def test_memo_cache_stores_output(tmp_path: Any) -> None:
    """After execution, the memo cache database contains the node's output."""
    import sqlite3

    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "store-test", "type": "shell", "cache": True, "params": {"command": "printf '%s' cached-value"}},
        ],
        "edges": [],
    }

    _run_workflow(ir, cache)

    # Verify the cache DB has an entry
    conn = sqlite3.connect(str(tmp_path / "cache.db"))
    cursor = conn.execute("SELECT node_id FROM cache_entries")
    rows = cursor.fetchall()
    conn.close()

    node_ids = [r[0] for r in rows]
    assert "store-test" in node_ids, "Node output should be stored in memo cache"


def test_memo_cache_restores_shared(tmp_path: Any) -> None:
    """On cache hit, shared[node_id] is populated with the cached output dict."""
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "restore-node", "type": "shell", "cache": True, "params": {"command": "printf '%s' restore-me"}},
        ],
        "edges": [],
    }

    # Populate cache via first run
    shared1 = _run_workflow(ir, cache)
    original_output = dict(shared1["restore-node"])

    # Second run: fresh shared, same cache
    shared2 = _run_workflow(ir, cache)

    # shared[node_id] should be restored from cache
    assert "restore-node" in shared2
    assert shared2["restore-node"] == original_output


def test_memo_cache_miss_on_different_input(tmp_path: Any) -> None:
    """Changing a resolved template input produces a cache miss and re-execution."""
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "diff-input", "type": "shell", "cache": True, "params": {"command": "printf '%s' '${input_val}'"}},
        ],
        "edges": [],
        "inputs": {"input_val": {"type": "string", "description": "Test input"}},
    }

    # First run with input_val="hello"
    shared1 = _run_workflow(ir, cache, initial_params={"input_val": "hello"})
    assert shared1["diff-input"]["stdout"] == "hello"

    # Second run with input_val="world" (different input)
    shared2 = _run_workflow(ir, cache, initial_params={"input_val": "world"})
    assert shared2["diff-input"]["stdout"] == "world"

    # Outputs should differ (cache miss due to different input)
    assert shared1["diff-input"]["stdout"] != shared2["diff-input"]["stdout"]


def test_no_memo_cache_in_shared(tmp_path: Any) -> None:
    """When __memoization_cache__ is absent, node executes normally without errors."""
    from pflow.registry import Registry
    from pflow.runtime import compile_workflow
    from pflow.runtime.engine import WorkflowEngine

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "no-cache-node", "type": "shell", "cache": True, "params": {"command": "printf '%s' works"}},
        ],
        "edges": [],
    }

    registry = Registry()
    workflow = compile_workflow(ir_json=ir, registry=registry)

    # Shared store WITHOUT __memoization_cache__
    shared: dict[str, Any] = dict(workflow.resolved_defaults)

    engine = WorkflowEngine()
    engine.run(workflow, shared)

    assert shared["no-cache-node"]["stdout"] == "works"


def test_memo_cache_prevents_reexecution(tmp_path: Any) -> None:
    """Verify that cached nodes are NOT re-executed using shell side effects."""
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    tracking_file = tmp_path / "exec_tracking.txt"

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "tracked",
                "type": "shell",
                "cache": True,
                "params": {"command": f"echo 'exec' >> {tracking_file}"},
            },
        ],
        "edges": [],
    }

    # First run: node executes
    _run_workflow(ir, cache)
    assert tracking_file.read_text().count("exec") == 1

    # Second run: node should be cached
    _run_workflow(ir, cache)
    assert tracking_file.read_text().count("exec") == 1, "Node was re-executed on memo cache hit!"


def test_memo_cache_records_execution_state(tmp_path: Any) -> None:
    """On cache hit, __execution__ state is properly populated."""
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "state-node", "type": "shell", "cache": True, "params": {"command": "printf '%s' test"}},
        ],
        "edges": [],
    }

    # First run: populate cache
    _run_workflow(ir, cache)

    # Second run: cache hit path
    shared2 = _run_workflow(ir, cache)

    execution = shared2["__execution__"]
    assert "state-node" in execution["completed_nodes"]
    assert execution["node_actions"]["state-node"] == "default"
    assert "state-node" in execution["node_hashes"]


def test_memo_cache_rehydrates_node_warning(tmp_path: Any) -> None:
    """Memo hits must preserve node warnings so degraded status does not become success."""
    from pflow.runtime.engine.instrumentation import apply_memo_hit, write_memo_cache

    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    warning = {
        "kind": "claude_code.schema_not_satisfied",
        "text": "Model did not return structured output matching the schema.",
        "context": {"node_type": "claude-code"},
    }
    shared = {
        "__memoization_cache__": cache,
        "__warnings__": {"review": warning},
        "_pflow_workflow_file": "workflow.pflow.md",
        "review": {"result": "raw text", "_schema_error": warning["text"]},
    }

    write_memo_cache(
        "review",
        shared,
        "cache-key",
        node_type_name="ClaudeCodeNode",
    )
    cached = cache.get("cache-key")
    assert cached is not None
    cached_action, cached_output = cached

    replay_shared: dict[str, Any] = {}
    apply_memo_hit(
        "review",
        replay_shared,
        cached_action,
        cached_output,
        "config-hash",
        node_type_name="ClaudeCodeNode",
    )

    assert replay_shared["review"] == {"result": "raw text", "_schema_error": warning["text"]}
    assert replay_shared["__warnings__"]["review"] == warning


@pytest.mark.parametrize(
    ("severity", "degrades"),
    [(Severity.WARNING, True), (Severity.INFO, False)],
)
def test_memo_cache_round_trips_diagnostic_warning(
    tmp_path: Any,
    severity: Severity,
    degrades: bool,
) -> None:
    """Diagnostic warnings keep severity/message/source through SQLite memo cache."""
    from pflow.runtime.engine.instrumentation import apply_memo_hit, write_memo_cache

    cache = MemoizationCache(db_path=tmp_path / f"{severity.value}.db")
    warning = Diagnostic(
        severity=severity,
        message=f"{severity.value} diagnostic",
        title="Cached Diagnostic",
        suggestions=["Inspect the cached warning."],
        node_id="review",
        source="runtime",
        context={"type": "on_error_recovery", "category": "shell_failure"},
        id=f"test.{severity.value}",
    )
    shared = {
        "__memoization_cache__": cache,
        "__warnings__": {"review": warning},
        "_pflow_workflow_file": "workflow.pflow.md",
        "review": {"result": "raw text"},
    }

    write_memo_cache(
        "review",
        shared,
        "cache-key",
        node_type_name="ShellNode",
    )
    cached = cache.get("cache-key")
    assert cached is not None
    cached_action, cached_output = cached
    assert isinstance(cached_output["__pflow_warnings__"], dict)
    assert cached_output["__pflow_warnings__"]["severity"] == severity.value
    assert cached_output["__pflow_warnings__"]["message"] == warning.message

    replay_shared: dict[str, Any] = {}
    apply_memo_hit(
        "review",
        replay_shared,
        cached_action,
        cached_output,
        "config-hash",
        node_type_name="ShellNode",
    )

    replay_warning = replay_shared["__warnings__"]["review"]
    assert isinstance(replay_warning, Diagnostic)
    assert replay_warning.severity is severity
    assert replay_warning.message == warning.message
    assert replay_warning.source == "runtime"
    assert replay_warning.id == warning.id
    assert warning_degrades_status(replay_warning) is degrades
    assert replay_shared["review"] == {"result": "raw text"}


def test_memo_cache_no_write_on_error(tmp_path: Any) -> None:
    """When node returns 'error', the result is NOT written to the memo cache."""
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    tracking_file = tmp_path / "err_tracking.txt"

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "error-node",
                "type": "shell",
                "cache": True,
                "params": {"command": f"echo 'fail' >> {tracking_file} && exit 1"},
            },
        ],
        "edges": [],
    }

    # First run: node returns "error"
    _run_workflow(ir, cache)
    assert tracking_file.read_text().count("fail") == 1

    # Second run: error result should NOT have been cached
    _run_workflow(ir, cache)
    assert tracking_file.read_text().count("fail") == 2, "Error result should not be cached — node must re-execute"


# ---------------------------------------------------------------------------
# Workflow node memoization skip
# ---------------------------------------------------------------------------


def test_workflow_node_skips_memoization(tmp_path: Any) -> None:
    """WorkflowExecutor nodes should not be memoized — sub-workflow files may change.

    Tests this via the standalone check_memo_cache function with
    node_type_name="WorkflowExecutor".
    """
    from pflow.runtime.engine.instrumentation import check_memo_cache

    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    shared: dict[str, Any] = {"__memoization_cache__": cache}

    # Memoization should be skipped entirely for WorkflowExecutor
    hit, result, cache_key = check_memo_cache(
        node_id="sub-wf",
        node_type_name="WorkflowExecutor",
        config_hash="abc123",
        batch_config=None,
        shared=shared,
        visit_counts={"sub-wf": 1},
    )
    assert hit is False
    assert result is None
    assert cache_key is None, "Workflow nodes should not produce a memo cache key"
