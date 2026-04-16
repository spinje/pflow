"""End-to-end integration tests for workflow iteration cache (memoization).

Tests the full flow: multiple nodes wired together via compile_workflow +
WorkflowEngine, with a MemoizationCache in shared["__memoization_cache__"].
Verifies cache hits, invalidation on config/input changes, --no-cache flag
behavior, --only early termination, error handling, and TTL expiry.

Migrated from compile_ir_to_flow shim to compile_workflow + WorkflowEngine
after the shim was deprecated (Task 135/138).

Note: The engine's memo cache hit path (check_memo_cache) does NOT populate
__cache_hits__ -- only the in-process cache hit path (handle_cached_execution)
does. Tests verify caching behavior through output correctness and execution
tracking, not __cache_hits__.
"""

import sqlite3
import time
from pathlib import Path
from typing import Any

from pflow.runtime.cache import MemoizationCache

# ---------------------------------------------------------------------------
# Module-level execution tracking
# ---------------------------------------------------------------------------

# Track node execution via shell side effects (file writes).
# Each test creates a unique tracking file and checks its contents.


def _run_workflow(
    ir: dict[str, Any],
    cache: MemoizationCache,
    initial_params: dict[str, Any] | None = None,
    only_node: str | None = None,
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

    engine = WorkflowEngine(only_node=only_node)
    engine.run(workflow, shared)
    return shared


def _two_shell_ir(msg1: str = "hello", msg2: str = "world") -> dict[str, Any]:
    """Build IR for a 2-node shell workflow: step-1 >> step-2."""
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "step-1", "type": "shell", "params": {"command": f"printf '%s' '{msg1}'"}},
            {"id": "step-2", "type": "shell", "params": {"command": f"printf '%s' '{msg2}'"}},
        ],
        "edges": [{"from": "step-1", "to": "step-2"}],
    }


def _tracking_ir(
    tmp_path: Path,
    node_id: str,
    message: str = "hello",
) -> tuple[dict[str, Any], Path]:
    """Build IR for a shell node that appends to a tracking file.

    Returns (ir_dict, tracking_file_path).
    """
    tracking_file = tmp_path / f"{node_id}_tracking.txt"
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": node_id,
                "type": "shell",
                "params": {"command": f"echo '{message}' >> {tracking_file}"},
            },
        ],
        "edges": [],
    }, tracking_file


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_full_cache_cycle(tmp_path: Any) -> None:
    """Run 2-node workflow, then re-run with same cache. All nodes should be cached.

    First run: both nodes execute (cache misses).
    Second run: fresh shared + same cache DB -> both nodes cached.
    Outputs in shared["step-1"] and shared["step-2"] should be identical.
    """
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # --- First run: both nodes execute ---
    shared1 = _run_workflow(_two_shell_ir("hello", "world"), cache)
    assert shared1["step-1"]["stdout"] == "hello"
    assert shared1["step-2"]["stdout"] == "world"

    # --- Second run: fresh shared, SAME cache ---
    shared2 = _run_workflow(_two_shell_ir("hello", "world"), cache)

    # Outputs restored from cache should be identical
    assert shared2["step-1"]["stdout"] == "hello"
    assert shared2["step-2"]["stdout"] == "world"


def test_cache_prevents_reexecution(tmp_path: Any) -> None:
    """CRITICAL: Verify that cached nodes are NOT re-executed.

    Uses shell nodes that append to a file to detect re-execution.
    """
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    tracking_file = tmp_path / "exec_tracking.txt"

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "tracked",
                "type": "shell",
                "params": {"command": f"echo 'executed' >> {tracking_file}"},
            },
        ],
        "edges": [],
    }

    # First run: node executes, writes to tracking file
    _run_workflow(ir, cache)
    assert tracking_file.read_text().count("executed") == 1

    # Second run: node should be cached, NOT re-executed
    shared2 = _run_workflow(ir, cache)
    assert tracking_file.read_text().count("executed") == 1, "Node was re-executed on second run — cache failed!"

    # Output should still be available from cache
    assert "tracked" in shared2


def test_config_change_invalidation(tmp_path: Any) -> None:
    """Changing a static param on one node invalidates that node's cache.

    Run workflow, change step-2's message param, re-run.
    step-1 should be cached, step-2 should re-execute.
    """
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # First run: populate cache
    shared1 = _run_workflow(_two_shell_ir("alpha", "beta"), cache)
    assert shared1["step-1"]["stdout"] == "alpha"
    assert shared1["step-2"]["stdout"] == "beta"

    # Second run: step-2 has a different message
    shared2 = _run_workflow(_two_shell_ir("alpha", "gamma"), cache)

    # step-1 should be cached (same value), step-2 re-executed with new value
    assert shared2["step-1"]["stdout"] == "alpha"
    assert shared2["step-2"]["stdout"] == "gamma"


def test_template_input_change_invalidation(tmp_path: Any) -> None:
    """Changing a workflow input that feeds a template invalidates cache.

    Run with input_val=A, then re-run with input_val=B.
    Nodes using ${input_val} should get a cache miss.
    """
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "step-1", "type": "shell", "params": {"command": "printf '%s' '${input_val}'"}},
            {"id": "step-2", "type": "shell", "params": {"command": "printf '%s' fixed"}},
        ],
        "edges": [{"from": "step-1", "to": "step-2"}],
        "inputs": {"input_val": {"type": "string", "description": "Test input"}},
    }

    # First run with input_val=A
    shared1 = _run_workflow(ir, cache, initial_params={"input_val": "A"})
    assert shared1["step-1"]["stdout"] == "A"

    # Second run with input_val=B
    shared2 = _run_workflow(ir, cache, initial_params={"input_val": "B"})

    # step-1 re-executes (template input changed), step-2 cached (static param unchanged)
    assert shared2["step-1"]["stdout"] == "B"
    assert shared2["step-2"]["stdout"] == "fixed"


def test_no_cache_flag(tmp_path: Any) -> None:
    """With read_enabled=False (--no-cache), all nodes execute but cache is written.

    First run with read_enabled=False: all execute, cache written.
    Second run with read_enabled=True: all served from cache.
    """
    db_path = tmp_path / "cache.db"
    tracking_file = tmp_path / "exec_tracking.txt"

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "tracked",
                "type": "shell",
                "params": {"command": f"echo 'run' >> {tracking_file}"},
            },
        ],
        "edges": [],
    }

    # First run: no-cache mode (writes to DB but never reads)
    cache_write_only = MemoizationCache(db_path=db_path, read_enabled=False)
    _run_workflow(ir, cache_write_only)
    assert tracking_file.read_text().count("run") == 1

    # Second run: normal mode (reads enabled), same DB path
    cache_read_enabled = MemoizationCache(db_path=db_path, read_enabled=True)
    _run_workflow(ir, cache_read_enabled)

    # Node should NOT have re-executed (cache hit on second run)
    assert tracking_file.read_text().count("run") == 1


def test_only_flag_stops_after_target(tmp_path: Any) -> None:
    """With --only, flow stops after target node.

    Build 3-node flow (A->B->C). Use only_node="B".
    A and B should execute, C should not.
    """
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "A", "type": "shell", "params": {"command": "printf '%s' a-val"}},
            {"id": "B", "type": "shell", "params": {"command": "printf '%s' b-val"}},
            {"id": "C", "type": "shell", "params": {"command": "printf '%s' c-val"}},
        ],
        "edges": [
            {"from": "A", "to": "B"},
            {"from": "B", "to": "C"},
        ],
    }

    shared = _run_workflow(ir, cache, only_node="B")

    assert shared["A"]["stdout"] == "a-val"
    assert shared["B"]["stdout"] == "b-val"
    assert "C" not in shared, "C should not have been visited"


def test_only_with_cache(tmp_path: Any) -> None:
    """Full run builds cache. --only B run: A and B from cache, C never reached."""
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "A", "type": "shell", "params": {"command": "printf '%s' a-val"}},
            {"id": "B", "type": "shell", "params": {"command": "printf '%s' b-val"}},
            {"id": "C", "type": "shell", "params": {"command": "printf '%s' c-val"}},
        ],
        "edges": [
            {"from": "A", "to": "B"},
            {"from": "B", "to": "C"},
        ],
    }

    # --- Full run: populate cache for all three nodes ---
    shared1 = _run_workflow(ir, cache)
    assert shared1["A"]["stdout"] == "a-val"
    assert shared1["B"]["stdout"] == "b-val"
    assert shared1["C"]["stdout"] == "c-val"

    # --- --only B run: fresh shared, same cache ---
    shared2 = _run_workflow(ir, cache, only_node="B")

    assert shared2["A"]["stdout"] == "a-val"  # restored from cache
    assert shared2["B"]["stdout"] == "b-val"  # restored from cache
    assert "C" not in shared2, "C should not have been visited"


def test_key_value_override_cache_interaction(tmp_path: Any) -> None:
    """Cache key varies with template input values.

    Run with input=A (cached). Run with input=B (miss). Run with input=A again (hit).
    """
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "step-1", "type": "shell", "params": {"command": "printf '%s' '${input_val}'"}},
            {"id": "step-2", "type": "shell", "params": {"command": "printf '%s' static"}},
        ],
        "edges": [{"from": "step-1", "to": "step-2"}],
        "inputs": {"input_val": {"type": "string", "description": "Test input"}},
    }

    # Run 1: input_val=A
    shared1 = _run_workflow(ir, cache, initial_params={"input_val": "A"})
    assert shared1["step-1"]["stdout"] == "A"

    # Run 2: input_val=B -> cache miss for step-1
    shared2 = _run_workflow(ir, cache, initial_params={"input_val": "B"})
    assert shared2["step-1"]["stdout"] == "B"
    assert shared2["step-2"]["stdout"] == "static"

    # Run 3: input_val=A again -> cache HIT from run 1
    shared3 = _run_workflow(ir, cache, initial_params={"input_val": "A"})
    assert shared3["step-1"]["stdout"] == "A"
    assert shared3["step-2"]["stdout"] == "static"


def test_error_node_not_cached(tmp_path: Any) -> None:
    """A node returning 'error' should not be stored in cache.

    On re-run, error node should re-execute.
    """
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    tracking_file = tmp_path / "err_tracking.txt"

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "step-err",
                "type": "shell",
                "params": {"command": f"echo 'fail' >> {tracking_file} && exit 1"},
            },
        ],
        "edges": [],
    }

    # First run: step-err returns "error"
    _run_workflow(ir, cache)
    assert tracking_file.read_text().count("fail") == 1

    # Second run: step-err should re-execute (errors are never cached)
    _run_workflow(ir, cache)
    assert tracking_file.read_text().count("fail") == 2, (
        "Error node should re-execute on second run (errors are not cached)"
    )


def test_upstream_cached_downstream_executes(tmp_path: Any) -> None:
    """Upstream node cached, downstream re-executes due to config change.

    Node A is cached (same config). Node B's own config changed, so it
    re-executes. A's output should be available from cache for downstream.
    """
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # First run: both execute
    shared1 = _run_workflow(_two_shell_ir("upstream", "downstream-v1"), cache)
    assert shared1["step-1"]["stdout"] == "upstream"
    assert shared1["step-2"]["stdout"] == "downstream-v1"

    # Second run: step-1 unchanged (cached), step-2 config changed
    shared2 = _run_workflow(_two_shell_ir("upstream", "downstream-v2"), cache)

    assert shared2["step-1"]["stdout"] == "upstream"  # from cache
    assert shared2["step-2"]["stdout"] == "downstream-v2"  # re-executed


def test_cache_ttl_expiry(tmp_path: Any) -> None:
    """Entries with old timestamps are treated as cache misses.

    Insert entry with old timestamp via direct SQL, then run.
    Node should re-execute because the cached entry is expired.
    """
    db_path = tmp_path / "cache.db"
    cache = MemoizationCache(db_path=db_path, ttl_seconds=3600)
    tracking_file = tmp_path / "ttl_tracking.txt"

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "tracked",
                "type": "shell",
                "params": {"command": f"echo 'run' >> {tracking_file}"},
            },
        ],
        "edges": [],
    }

    # First run: populate cache
    _run_workflow(ir, cache)
    assert tracking_file.read_text().count("run") == 1

    # Backdate ALL cache entries to beyond TTL (2 hours ago, TTL is 1 hour)
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE cache_entries SET created_at = ?", (time.time() - 7200,))
    conn.commit()
    conn.close()

    # Second run: all entries expired -> cache misses -> re-execute
    _run_workflow(ir, cache)
    assert tracking_file.read_text().count("run") == 2, "Node should re-execute after TTL expiry"


# ---------------------------------------------------------------------------
# Data integrity: cached output consumed by downstream template resolution
# ---------------------------------------------------------------------------


def test_cached_output_flows_through_template_resolution(tmp_path: Any) -> None:
    """Cached upstream output must be consumable by downstream via ${upstream.field}.

    Run 1: all execute, cache populated.
    Run 2: all cached. Verify outputs are identical to run 1.
    """
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "producer", "type": "shell", "params": {"command": "printf '%s' 'hello world'"}},
            {"id": "consumer", "type": "shell", "params": {"command": "printf '%s' '${producer.stdout}'"}},
        ],
        "edges": [{"from": "producer", "to": "consumer"}],
    }

    # --- Run 1: all nodes execute ---
    shared1 = _run_workflow(ir, cache)
    assert shared1["producer"]["stdout"] == "hello world"
    assert shared1["consumer"]["stdout"] == "hello world"

    run1_producer = dict(shared1["producer"])
    run1_consumer = dict(shared1["consumer"])

    # --- Run 2: fresh shared, SAME cache ---
    shared2 = _run_workflow(ir, cache)

    # Data integrity: cached outputs match original run exactly
    assert shared2["producer"] == run1_producer, "Producer output corrupted by cache round-trip"
    assert shared2["consumer"] == run1_consumer, "Consumer output corrupted by cache round-trip"


def test_cache_db_init_failure_logs_warning(tmp_path: Any, caplog: Any) -> None:
    """DB init failure logs WARNING (not DEBUG) so agents know caching is unavailable.

    Real bug this catches: If _init_db failure is logged at DEBUG level, agents
    iterating on workflows silently lose caching with no visible indication.
    The WARNING ensures "Memoization cache unavailable" appears in normal output.
    """
    import sqlite3
    from unittest.mock import patch

    caplog.set_level("WARNING", logger="pflow.runtime.cache")
    with patch("sqlite3.connect", side_effect=sqlite3.Error("permission denied")):
        from pflow.runtime.cache import MemoizationCache

        MemoizationCache(db_path=tmp_path / "test.db")
    assert any("Memoization cache unavailable" in r.message for r in caplog.records)
    assert any(r.levelname == "WARNING" for r in caplog.records if "cache unavailable" in r.message)
