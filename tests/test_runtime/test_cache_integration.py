"""End-to-end integration tests for workflow iteration cache (memoization).

Tests the full flow: multiple nodes wired together via PocketFlow Flow,
with a MemoizationCache in shared["__memoization_cache__"]. Verifies cache
hits, invalidation on config/input changes, --no-cache flag behavior,
--only early termination, error handling, and TTL expiry.

Unlike test_memoization_integration.py (single-node wrapper tests), these
tests exercise multi-node workflows through the real PocketFlow Flow
orchestration loop.
"""

import sqlite3
import time
from typing import Any

import pytest

from pflow.pocketflow import Flow, Node
from pflow.runtime.cache import MemoizationCache
from pflow.runtime.wrappers.instrumented_wrapper import InstrumentedNodeWrapper
from pflow.runtime.wrappers.namespaced_wrapper import NamespacedNodeWrapper
from pflow.runtime.wrappers.template_wrapper import TemplateAwareNodeWrapper

# ---------------------------------------------------------------------------
# Test nodes
# ---------------------------------------------------------------------------

# Module-level execution log shared across all AppendNode instances within
# a single test.  Cleared automatically by the autouse fixture below;
# tests that do multiple runs clear it manually between runs.
_execution_log: list[str] = []


@pytest.fixture(autouse=True)
def _clear_execution_log():
    """Safety net: reset execution log between tests."""
    _execution_log.clear()
    yield
    _execution_log.clear()


class AppendNode(Node):
    """Appends to a module-level log to track execution order.

    Writes its result into the namespaced shared store under "result".
    """

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return shared

    def exec(self, prep_res: Any) -> str:
        value = self.params.get("value", "default")
        _execution_log.append(value)
        return value

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["result"] = exec_res
        return "default"


class RichOutputNode(Node):
    """Produces a rich output dict with nested structures, various types, and edge cases."""

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return shared

    def exec(self, prep_res: Any) -> dict[str, Any]:
        _execution_log.append("rich-output")
        return {
            "text": "hello world",
            "count": 42,
            "ratio": 3.14,
            "active": True,
            "empty": None,
            "tags": ["a", "b", "c"],
            "nested": {"level1": {"level2": "deep"}},
        }

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        for key, value in exec_res.items():
            shared[key] = value
        return "default"


class ConcatNode(Node):
    """Reads upstream data via resolved template params and concatenates them.

    Expects 'prefix' and 'suffix' params (may be templates).
    Writes "prefix|suffix" to shared["result"].
    """

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return shared

    def exec(self, prep_res: Any) -> str:
        prefix = self.params.get("prefix", "")
        suffix = self.params.get("suffix", "")
        result = f"{prefix}|{suffix}"
        _execution_log.append(f"concat:{result}")
        return result

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["result"] = exec_res
        return "default"


class ErrorNode(Node):
    """Node that always returns the 'error' action."""

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return shared

    def exec(self, prep_res: Any) -> str:
        _execution_log.append("error-exec")
        return "something went wrong"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["error"] = exec_res
        return "error"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_node(
    node_cls: type,
    node_id: str,
    params: dict[str, Any] | None = None,
    initial_params: dict[str, Any] | None = None,
) -> InstrumentedNodeWrapper:
    """Build a fully-wrapped node (template -> namespace -> instrumented).

    Args:
        node_cls: PocketFlow Node subclass to instantiate.
        node_id: Unique identifier for the node (namespace key in shared).
        params: Parameters to set on the node (may contain ${...} templates).
        initial_params: Static parameters seeded into the TemplateAwareNodeWrapper
                        (available for template resolution as top-level keys).

    Returns:
        The outermost InstrumentedNodeWrapper, ready for Flow wiring.
    """
    node = node_cls()
    tw = TemplateAwareNodeWrapper(node, node_id, initial_params=initial_params or {})
    tw.set_params(params or {})
    ns = NamespacedNodeWrapper(tw, node_id)
    iw = InstrumentedNodeWrapper(ns, node_id)
    return iw


def _make_shared(
    tmp_path: Any,
    read_enabled: bool = True,
    ttl_seconds: float = 86400.0,
) -> dict[str, Any]:
    """Create a shared store with a MemoizationCache.

    Args:
        tmp_path: pytest tmp_path for the SQLite DB file.
        read_enabled: Whether cache reads are enabled.
        ttl_seconds: TTL for cache entries.

    Returns:
        Shared store dict with __memoization_cache__ set.
    """
    cache = MemoizationCache(
        db_path=tmp_path / "cache.db",
        read_enabled=read_enabled,
        ttl_seconds=ttl_seconds,
    )
    return {"__memoization_cache__": cache}


def _make_shared_with_cache(
    cache: MemoizationCache,
) -> dict[str, Any]:
    """Create a shared store re-using an existing MemoizationCache instance."""
    return {"__memoization_cache__": cache}


def _build_two_node_flow(
    params_1: dict[str, Any] | None = None,
    params_2: dict[str, Any] | None = None,
    initial_params_1: dict[str, Any] | None = None,
    initial_params_2: dict[str, Any] | None = None,
) -> Flow:
    """Build a 2-node linear flow: step-1 >> step-2."""
    node1 = _build_node(AppendNode, "step-1", params=params_1, initial_params=initial_params_1)
    node2 = _build_node(AppendNode, "step-2", params=params_2, initial_params=initial_params_2)
    node1 >> node2
    return Flow(start=node1)


def _build_three_node_flow(
    params_a: dict[str, Any] | None = None,
    params_b: dict[str, Any] | None = None,
    params_c: dict[str, Any] | None = None,
    initial_params: dict[str, Any] | None = None,
) -> Flow:
    """Build a 3-node linear flow: A >> B >> C."""
    node_a = _build_node(AppendNode, "A", params=params_a, initial_params=initial_params)
    node_b = _build_node(AppendNode, "B", params=params_b, initial_params=initial_params)
    node_c = _build_node(AppendNode, "C", params=params_c, initial_params=initial_params)
    node_a >> node_b
    node_b >> node_c
    return Flow(start=node_a)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_full_cache_cycle(tmp_path: Any) -> None:
    """Run 2-node workflow, then re-run with same cache. All nodes should be cached.

    First run: both nodes execute (cache misses).
    Second run: fresh wrapper chain + same cache DB -> both nodes cached.
    Outputs in shared["step-1"] and shared["step-2"] should be identical.
    """
    _execution_log.clear()
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # --- First run: both nodes execute ---
    shared1 = _make_shared_with_cache(cache)
    flow1 = _build_two_node_flow(
        params_1={"value": "hello"},
        params_2={"value": "world"},
    )
    flow1.run(shared1)

    assert _execution_log == ["hello", "world"]
    assert shared1["step-1"]["result"] == "hello"
    assert shared1["step-2"]["result"] == "world"

    # --- Second run: fresh wrapper chain, fresh shared, SAME cache ---
    _execution_log.clear()
    shared2 = _make_shared_with_cache(cache)
    flow2 = _build_two_node_flow(
        params_1={"value": "hello"},
        params_2={"value": "world"},
    )
    flow2.run(shared2)

    # No nodes should have executed — all served from cache
    assert _execution_log == [], "Nodes should not re-execute on cache hit"
    # Outputs restored from cache should be identical
    assert shared2["step-1"]["result"] == "hello"
    assert shared2["step-2"]["result"] == "world"
    # Cache hit tracking
    assert "step-1" in shared2.get("__cache_hits__", [])
    assert "step-2" in shared2.get("__cache_hits__", [])


def test_config_change_invalidation(tmp_path: Any) -> None:
    """Changing a static param on one node invalidates that node's cache.

    Run workflow, change step-2's value param, re-run.
    step-1 should be cached, step-2 should re-execute.
    """
    _execution_log.clear()
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # First run: populate cache
    shared1 = _make_shared_with_cache(cache)
    flow1 = _build_two_node_flow(
        params_1={"value": "alpha"},
        params_2={"value": "beta"},
    )
    flow1.run(shared1)
    assert _execution_log == ["alpha", "beta"]

    # Second run: step-2 has a different value
    _execution_log.clear()
    shared2 = _make_shared_with_cache(cache)
    flow2 = _build_two_node_flow(
        params_1={"value": "alpha"},
        params_2={"value": "gamma"},  # changed
    )
    flow2.run(shared2)

    # step-1 cached, step-2 re-executed
    assert _execution_log == ["gamma"], "Only step-2 should re-execute"
    assert shared2["step-1"]["result"] == "alpha"  # from cache
    assert shared2["step-2"]["result"] == "gamma"  # freshly executed


def test_template_input_change_invalidation(tmp_path: Any) -> None:
    """Changing an initial_param that feeds a template invalidates cache.

    Run with initial_params={"input": "A"}, then re-run with {"input": "B"}.
    Nodes using ${input} should get a cache miss.
    """
    _execution_log.clear()
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # First run with input=A
    shared1 = _make_shared_with_cache(cache)
    flow1 = _build_two_node_flow(
        params_1={"value": "${input_val}"},
        initial_params_1={"input_val": "A"},
        params_2={"value": "fixed"},
    )
    flow1.run(shared1)
    assert _execution_log == ["A", "fixed"]
    assert shared1["step-1"]["result"] == "A"

    # Second run with input=B
    _execution_log.clear()
    shared2 = _make_shared_with_cache(cache)
    flow2 = _build_two_node_flow(
        params_1={"value": "${input_val}"},
        initial_params_1={"input_val": "B"},
        params_2={"value": "fixed"},
    )
    flow2.run(shared2)

    # step-1 re-executes (template input changed), step-2 cached (static param unchanged)
    assert _execution_log == ["B"], "Only step-1 should re-execute for changed template input"
    assert shared2["step-1"]["result"] == "B"
    assert shared2["step-2"]["result"] == "fixed"  # from cache


def test_no_cache_flag(tmp_path: Any) -> None:
    """With read_enabled=False (--no-cache), all nodes execute but cache is written.

    First run with read_enabled=False: all execute, cache written.
    Second run with read_enabled=True: all served from cache.
    """
    _execution_log.clear()
    db_path = tmp_path / "cache.db"

    # First run: no-cache mode (writes to DB but never reads)
    cache_write_only = MemoizationCache(db_path=db_path, read_enabled=False)
    shared1 = _make_shared_with_cache(cache_write_only)
    flow1 = _build_two_node_flow(
        params_1={"value": "one"},
        params_2={"value": "two"},
    )
    flow1.run(shared1)
    assert _execution_log == ["one", "two"]

    # Second run: normal mode (reads enabled), same DB path
    _execution_log.clear()
    cache_read_enabled = MemoizationCache(db_path=db_path, read_enabled=True)
    shared2 = _make_shared_with_cache(cache_read_enabled)
    flow2 = _build_two_node_flow(
        params_1={"value": "one"},
        params_2={"value": "two"},
    )
    flow2.run(shared2)

    assert _execution_log == [], "All nodes should be cached on second run"
    assert shared2["step-1"]["result"] == "one"
    assert shared2["step-2"]["result"] == "two"


def test_only_flag_stops_after_target(tmp_path: Any) -> None:
    """With --only monkey-patch, flow stops after target node.

    Build 3-node flow (A->B->C). Monkey-patch get_next_node to stop after B.
    A and B should execute, C should not.
    """
    _execution_log.clear()
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    shared = _make_shared_with_cache(cache)
    flow = _build_three_node_flow(
        params_a={"value": "a-val"},
        params_b={"value": "b-val"},
        params_c={"value": "c-val"},
    )

    # Monkey-patch: stop after node B
    target_id = "B"
    original_get_next = flow.get_next_node

    def get_next_with_stop(curr: Any, action: Any) -> Any:
        if getattr(curr, "node_id", None) == target_id:
            return None
        return original_get_next(curr, action)

    flow.get_next_node = get_next_with_stop

    flow.run(shared)

    assert _execution_log == ["a-val", "b-val"], "C should not execute with --only B"
    assert shared["A"]["result"] == "a-val"
    assert shared["B"]["result"] == "b-val"
    assert "C" not in shared, "C should not have been visited"


def test_only_with_cache(tmp_path: Any) -> None:
    """Full run builds cache. --only B run: A and B from cache, C never reached.

    1. Full run: A, B, C all execute, cache populated.
    2. --only B run: A and B served from cache (same config+inputs), C never reached.
    """
    _execution_log.clear()
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # --- Full run: populate cache for all three nodes ---
    shared1 = _make_shared_with_cache(cache)
    flow1 = _build_three_node_flow(
        params_a={"value": "a-val"},
        params_b={"value": "b-val"},
        params_c={"value": "c-val"},
    )
    flow1.run(shared1)
    assert _execution_log == ["a-val", "b-val", "c-val"]

    # --- --only B run: fresh shared, same cache ---
    _execution_log.clear()
    shared2 = _make_shared_with_cache(cache)
    flow2 = _build_three_node_flow(
        params_a={"value": "a-val"},
        params_b={"value": "b-val"},
        params_c={"value": "c-val"},
    )

    # Monkey-patch: stop after B
    target_id = "B"
    original_get_next = flow2.get_next_node

    def get_next_with_stop(curr: Any, action: Any) -> Any:
        if getattr(curr, "node_id", None) == target_id:
            return None
        return original_get_next(curr, action)

    flow2.get_next_node = get_next_with_stop  # type: ignore[assignment]

    flow2.run(shared2)

    # A should be from cache (no execution), B from cache too (same config),
    # C never reached
    assert _execution_log == [], "A and B should both be cached"
    assert shared2["A"]["result"] == "a-val"  # restored from cache
    assert shared2["B"]["result"] == "b-val"  # restored from cache
    assert "C" not in shared2, "C should not have been visited"
    assert "A" in shared2.get("__cache_hits__", [])
    assert "B" in shared2.get("__cache_hits__", [])


def test_key_value_override_cache_interaction(tmp_path: Any) -> None:
    """Cache key varies with template input values.

    Run with input=A (cached). Run with input=B (miss). Run with input=A again (hit).
    """
    _execution_log.clear()
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # Run 1: input_val=A
    shared1 = _make_shared_with_cache(cache)
    flow1 = _build_two_node_flow(
        params_1={"value": "${input_val}"},
        initial_params_1={"input_val": "A"},
        params_2={"value": "static"},
    )
    flow1.run(shared1)
    assert _execution_log == ["A", "static"]

    # Run 2: input_val=B -> cache miss for step-1
    _execution_log.clear()
    shared2 = _make_shared_with_cache(cache)
    flow2 = _build_two_node_flow(
        params_1={"value": "${input_val}"},
        initial_params_1={"input_val": "B"},
        params_2={"value": "static"},
    )
    flow2.run(shared2)
    assert _execution_log == ["B"], "step-1 should re-execute for input_val=B"
    assert shared2["step-1"]["result"] == "B"
    assert shared2["step-2"]["result"] == "static"  # from cache

    # Run 3: input_val=A again -> cache HIT from run 1
    _execution_log.clear()
    shared3 = _make_shared_with_cache(cache)
    flow3 = _build_two_node_flow(
        params_1={"value": "${input_val}"},
        initial_params_1={"input_val": "A"},
        params_2={"value": "static"},
    )
    flow3.run(shared3)
    assert _execution_log == [], "All nodes should hit cache on third run with input_val=A"
    assert shared3["step-1"]["result"] == "A"
    assert shared3["step-2"]["result"] == "static"


def test_error_node_not_cached(tmp_path: Any) -> None:
    """A node returning 'error' is not stored in cache. Next run re-executes it.

    Flow: step-1 (AppendNode) >> step-err (ErrorNode).
    The error node halts the flow. On re-run, step-1 should be cached
    but step-err should re-execute.
    """
    _execution_log.clear()
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # Build flow: step-1 -> step-err
    node1 = _build_node(AppendNode, "step-1", params={"value": "ok"})
    node_err = _build_node(ErrorNode, "step-err")
    node1 >> node_err

    # First run: step-1 succeeds, step-err returns "error"
    shared1 = _make_shared_with_cache(cache)
    flow1 = Flow(start=node1)
    flow1.run(shared1)

    assert "ok" in _execution_log
    assert "error-exec" in _execution_log
    assert shared1["step-1"]["result"] == "ok"

    # Second run: step-1 from cache, step-err re-executes (errors are not cached)
    _execution_log.clear()
    node1_v2 = _build_node(AppendNode, "step-1", params={"value": "ok"})
    node_err_v2 = _build_node(ErrorNode, "step-err")
    node1_v2 >> node_err_v2

    shared2 = _make_shared_with_cache(cache)
    flow2 = Flow(start=node1_v2)
    flow2.run(shared2)

    # step-1 should be cached (not in _execution_log), step-err should re-execute
    assert "ok" not in _execution_log, "step-1 should be served from cache"
    assert "error-exec" in _execution_log, "step-err should re-execute (errors not cached)"


def test_upstream_cached_downstream_executes(tmp_path: Any) -> None:
    """Upstream node cached, downstream re-executes due to config change.

    Node A is cached (same config). Node B's own config changed, so it
    re-executes. A's output should be available in shared[A] from cache hit
    for downstream template resolution (if needed).
    """
    _execution_log.clear()
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # First run: both execute
    shared1 = _make_shared_with_cache(cache)
    flow1 = _build_two_node_flow(
        params_1={"value": "upstream"},
        params_2={"value": "downstream-v1"},
    )
    flow1.run(shared1)
    assert _execution_log == ["upstream", "downstream-v1"]

    # Second run: step-1 unchanged (cached), step-2 config changed
    _execution_log.clear()
    shared2 = _make_shared_with_cache(cache)
    flow2 = _build_two_node_flow(
        params_1={"value": "upstream"},
        params_2={"value": "downstream-v2"},  # changed
    )
    flow2.run(shared2)

    assert _execution_log == ["downstream-v2"], "Only step-2 should re-execute"
    # Upstream result still available from cache
    assert shared2["step-1"]["result"] == "upstream"
    # Downstream has new result
    assert shared2["step-2"]["result"] == "downstream-v2"


def test_cache_ttl_expiry(tmp_path: Any) -> None:
    """Entries with old timestamps are treated as cache misses.

    Insert entry with old timestamp via direct SQL, then run.
    Node should re-execute because the cached entry is expired.
    """
    _execution_log.clear()
    db_path = tmp_path / "cache.db"
    # Use a short TTL for the test
    cache = MemoizationCache(db_path=db_path, ttl_seconds=3600)

    # First run: populate cache
    shared1 = _make_shared_with_cache(cache)
    flow1 = _build_two_node_flow(
        params_1={"value": "cached-val"},
        params_2={"value": "also-cached"},
    )
    flow1.run(shared1)
    assert _execution_log == ["cached-val", "also-cached"]

    # Backdate ALL cache entries to beyond TTL (2 hours ago, TTL is 1 hour)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE cache_entries SET created_at = ?",
        (time.time() - 7200,),
    )
    conn.commit()
    conn.close()

    # Second run: all entries expired -> cache misses -> re-execute
    _execution_log.clear()
    shared2 = _make_shared_with_cache(cache)
    flow2 = _build_two_node_flow(
        params_1={"value": "cached-val"},
        params_2={"value": "also-cached"},
    )
    flow2.run(shared2)

    assert _execution_log == ["cached-val", "also-cached"], "All nodes should re-execute after TTL expiry"
    assert shared2["step-1"]["result"] == "cached-val"
    assert shared2["step-2"]["result"] == "also-cached"


# ---------------------------------------------------------------------------
# Data integrity: cached output consumed by downstream template resolution
# ---------------------------------------------------------------------------


def test_cached_output_flows_through_template_resolution(tmp_path: Any) -> None:
    """Cached upstream output must be consumable by downstream via ${upstream.field}.

    This is the core data flow test for the cache feature. A 3-node chain:
      A (RichOutputNode) → B (ConcatNode reads ${A.text} and ${A.count})
                         → C (ConcatNode reads ${B.result})

    Run 1: all execute, cache populated.
    Run 2: all cached. Verify C's output is IDENTICAL to run 1.

    This catches: serialization round-trip corruption, wrong nesting level on
    restore, template resolution failures on cached dict structure.
    """
    _execution_log.clear()
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # --- Run 1: all nodes execute ---
    shared1 = _make_shared_with_cache(cache)
    node_a = _build_node(RichOutputNode, "producer")
    node_b = _build_node(
        ConcatNode,
        "combiner",
        params={"prefix": "${producer.text}", "suffix": "${producer.count}"},
    )
    node_c = _build_node(
        ConcatNode,
        "final",
        params={"prefix": "${combiner.result}", "suffix": "done"},
    )
    node_a >> node_b
    node_b >> node_c
    flow1 = Flow(start=node_a)
    flow1.run(shared1)

    assert "rich-output" in _execution_log
    assert "concat:hello world|42" in _execution_log
    assert "concat:hello world|42|done" in _execution_log

    run1_producer = dict(shared1["producer"])
    run1_combiner = dict(shared1["combiner"])
    run1_final = dict(shared1["final"])

    # --- Run 2: fresh wrappers, fresh shared, SAME cache ---
    _execution_log.clear()
    shared2 = _make_shared_with_cache(cache)
    node_a2 = _build_node(RichOutputNode, "producer")
    node_b2 = _build_node(
        ConcatNode,
        "combiner",
        params={"prefix": "${producer.text}", "suffix": "${producer.count}"},
    )
    node_c2 = _build_node(
        ConcatNode,
        "final",
        params={"prefix": "${combiner.result}", "suffix": "done"},
    )
    node_a2 >> node_b2
    node_b2 >> node_c2
    flow2 = Flow(start=node_a2)
    flow2.run(shared2)

    # No nodes should have executed
    assert _execution_log == [], f"All nodes should be cached, but got: {_execution_log}"

    # Data integrity: cached outputs match original run exactly
    assert shared2["producer"] == run1_producer, "Producer output corrupted by cache round-trip"
    assert shared2["combiner"] == run1_combiner, "Combiner output corrupted by cache round-trip"
    assert shared2["final"] == run1_final, "Final output corrupted by cache round-trip"

    # Verify the rich output survived round-trip with correct types
    p = shared2["producer"]
    assert p["text"] == "hello world" and isinstance(p["text"], str)
    assert p["count"] == 42 and isinstance(p["count"], int)
    assert p["ratio"] == 3.14 and isinstance(p["ratio"], float)
    assert p["active"] is True and isinstance(p["active"], bool)
    assert p["empty"] is None
    assert p["tags"] == ["a", "b", "c"] and isinstance(p["tags"], list)
    assert p["nested"] == {"level1": {"level2": "deep"}}
    assert p["nested"]["level1"]["level2"] == "deep"


# ---------------------------------------------------------------------------
# Regression test: stale _resolved in loop after memo cache hit
# ---------------------------------------------------------------------------


class LoopCheckerNode(Node):
    """Reads a template param, logs it, and returns 'loop' or 'done'."""

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return shared

    def exec(self, prep_res: Any) -> str:
        counter = self.params.get("current_counter", 0)
        _execution_log.append(f"counter={counter}")
        return str(counter)

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["last_value"] = exec_res
        counter = self.params.get("current_counter", 0)
        if counter >= 2:
            return "done"
        return "loop"


class IncrementNode(Node):
    """Increments shared['counter'] at ROOT level (no namespace wrapper)."""

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return shared

    def exec(self, prep_res: Any) -> str:
        return "incremented"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["counter"] = shared.get("counter", 0) + 1
        return "default"


@pytest.mark.filterwarnings("ignore:Flow ends.*not found:UserWarning")
def test_stale_resolved_regression_in_loop(tmp_path: Any) -> None:
    """Regression test: memo cache hit on visit 1 must not leave stale _resolved.

    Scenario:
    - Node A has template params (reads ${counter} from shared store)
    - Node B increments shared["counter"] at root level
    - A loops back via "loop" action
    - On visit 1, A gets a memo cache hit (from pre-populated cache)
    - On visit 2, memoization is skipped (visit_count > 1)
    - A must resolve templates FRESH (not use stale _resolved from visit 1's
      key computation)

    Without the fix (clearing _resolved after key computation), visit 2 would
    use the resolved params from visit 1 — seeing counter=0 instead of counter=1.
    """
    _execution_log.clear()

    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # --- Pre-populate cache for node A with counter=0 ---
    shared_seed = {"__memoization_cache__": cache, "counter": 0}

    node_seed = LoopCheckerNode()
    tw_seed = TemplateAwareNodeWrapper(node_seed, "check-counter", initial_params={})
    tw_seed.set_params({"current_counter": "${counter}"})
    ns_seed = NamespacedNodeWrapper(tw_seed, "check-counter")
    iw_seed = InstrumentedNodeWrapper(ns_seed, "check-counter")
    iw_seed._run(shared_seed)
    assert _execution_log == ["counter=0"]

    # --- Now build a looping flow: A --loop--> B --> A ---
    _execution_log.clear()

    # Node A: template-wrapped + namespaced + instrumented (full chain)
    node_a = LoopCheckerNode()
    tw_a = TemplateAwareNodeWrapper(node_a, "check-counter", initial_params={})
    tw_a.set_params({"current_counter": "${counter}"})
    ns_a = NamespacedNodeWrapper(tw_a, "check-counter")
    iw_a = InstrumentedNodeWrapper(ns_a, "check-counter")

    # Node B: NOT namespaced — writes counter at root level so A can read it
    node_b = IncrementNode()
    iw_b = InstrumentedNodeWrapper(node_b, "increment")

    # Wire: A --loop--> B --default--> A  (A --done--> end)
    iw_a - "loop" >> iw_b
    iw_b >> iw_a

    flow = Flow(start=iw_a)
    shared = {"__memoization_cache__": cache, "counter": 0}
    flow.run(shared)

    # Visit 1: counter=0, memo cache HIT (seeded above) → cached "loop" action
    # B runs: counter becomes 1
    # Visit 2: counter=1, memoization SKIPPED (visit>1), resolves FRESH → "loop"
    # B runs: counter becomes 2
    # Visit 3: counter=2, resolves FRESH → "done", flow ends

    counter_values = [e.split("=")[1] for e in _execution_log if e.startswith("counter=")]
    assert "1" in counter_values, f"Visit 2 should see counter=1 (fresh resolution), got log: {_execution_log}"
    assert "2" in counter_values, f"Visit 3 should see counter=2 (fresh resolution), got log: {_execution_log}"


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
