"""Tests for memoization cache integration in InstrumentedNodeWrapper._run().

Verifies that the instrumented wrapper correctly checks, restores, and stores
results in the MemoizationCache (SQLite-backed cross-run persistence).
The memoization cache sits between the loop guard and the in-process cache
check in _run(), and is skipped for revisited nodes (visit_count > 1).
"""

from typing import Any

import pytest

from pflow.pocketflow import Node
from pflow.runtime.cache import MemoizationCache
from pflow.runtime.wrappers.instrumented_wrapper import InstrumentedNodeWrapper
from pflow.runtime.wrappers.namespaced_wrapper import NamespacedNodeWrapper
from pflow.runtime.wrappers.template_wrapper import TemplateAwareNodeWrapper

# ---------------------------------------------------------------------------
# Test node that counts executions
# ---------------------------------------------------------------------------


class CountingNode(Node):
    """Node that counts executions for testing.

    Uses a class-level counter so we can observe whether a fresh wrapper
    chain (pointing at a different CountingNode instance) triggers real
    execution or returns a cached result.
    """

    exec_count = 0

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return shared

    def exec(self, prep_res: Any) -> str:
        CountingNode.exec_count += 1
        return f"result-{CountingNode.exec_count}"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["result"] = exec_res
        return "default"


class ErrorReturningNode(Node):
    """Node that always returns the 'error' action string."""

    exec_count = 0

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return shared

    def exec(self, prep_res: Any) -> str:
        ErrorReturningNode.exec_count += 1
        return "something went wrong"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["error"] = exec_res
        return "error"


@pytest.fixture(autouse=True)
def _reset_counters():
    """Reset class-level execution counters between tests."""
    CountingNode.exec_count = 0
    ErrorReturningNode.exec_count = 0
    yield
    CountingNode.exec_count = 0
    ErrorReturningNode.exec_count = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_wrapper_chain(
    node_id: str,
    initial_params: dict[str, Any] | None = None,
    template_params: dict[str, Any] | None = None,
    node: Node | None = None,
) -> InstrumentedNodeWrapper:
    """Build a minimal template -> namespace -> instrumented wrapper chain.

    Args:
        node_id: Identifier for the node (used as namespace key in shared).
        initial_params: Static parameters seeded into the TemplateAwareNodeWrapper.
        template_params: Parameters containing ${...} templates.
        node: Optional node instance; defaults to CountingNode().

    Returns:
        The outermost InstrumentedNodeWrapper ready for _run().
    """
    if node is None:
        node = CountingNode()

    all_params = {}
    if initial_params:
        all_params.update(initial_params)
    if template_params:
        all_params.update(template_params)

    tw = TemplateAwareNodeWrapper(node, node_id, initial_params=initial_params or {})
    tw.set_params(all_params)
    ns = NamespacedNodeWrapper(tw, node_id)
    iw = InstrumentedNodeWrapper(ns, node_id)
    return iw


def _make_shared(tmp_path: Any, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a shared store with a MemoizationCache instance.

    Args:
        tmp_path: pytest tmp_path for the SQLite database.
        extra: Additional keys to merge into the shared store.

    Returns:
        Shared store dict with __memoization_cache__ set.
    """
    shared: dict[str, Any] = {
        "__memoization_cache__": MemoizationCache(db_path=tmp_path / "cache.db"),
    }
    if extra:
        shared.update(extra)
    return shared


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_memo_cache_miss_then_hit(tmp_path: Any) -> None:
    """First run executes the node; second run (fresh chain, same cache) skips execution."""

    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # --- First run: cache MISS, node must execute ---
    shared1: dict[str, Any] = {"__memoization_cache__": cache}
    iw1 = _build_wrapper_chain("my-node", initial_params={"input_val": "hello"})
    result1 = iw1._run(shared1)

    assert result1 == "default"
    assert CountingNode.exec_count == 1
    # Namespaced output should exist
    assert "my-node" in shared1
    assert shared1["my-node"]["result"] == "result-1"

    # --- Second run: fresh wrapper chain, fresh shared, SAME cache ---
    shared2: dict[str, Any] = {"__memoization_cache__": cache}
    iw2 = _build_wrapper_chain("my-node", initial_params={"input_val": "hello"})
    result2 = iw2._run(shared2)

    assert result2 == "default"
    # Node should NOT have been executed again
    assert CountingNode.exec_count == 1, "Node was re-executed on cache hit"
    # Output restored from cache
    assert shared2["my-node"]["result"] == "result-1"


def test_memo_cache_stores_output(tmp_path: Any) -> None:
    """After execution, the memo cache contains the node's output."""

    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    shared: dict[str, Any] = {"__memoization_cache__": cache}

    iw = _build_wrapper_chain("store-test", initial_params={"x": "1"})
    iw._run(shared)

    # Compute the same cache key the wrapper would have computed
    # and verify the cache contains our output
    memo_key = iw._compute_memo_cache_key(shared)
    assert memo_key is not None

    cached = cache.get(memo_key)
    assert cached is not None
    action, output = cached
    assert action == "default"
    assert output["result"] == "result-1"


def test_memo_cache_restores_shared(tmp_path: Any) -> None:
    """On cache hit, shared[node_id] is populated with the cached output dict."""

    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # Populate cache via first run
    shared1: dict[str, Any] = {"__memoization_cache__": cache}
    iw1 = _build_wrapper_chain("restore-node", initial_params={"key": "val"})
    iw1._run(shared1)
    original_output = dict(shared1["restore-node"])

    # Second run: fresh shared, same cache
    shared2: dict[str, Any] = {"__memoization_cache__": cache}
    iw2 = _build_wrapper_chain("restore-node", initial_params={"key": "val"})
    iw2._run(shared2)

    # shared[node_id] should be restored from cache
    assert "restore-node" in shared2
    assert shared2["restore-node"] == original_output


def test_memo_cache_miss_on_different_input(tmp_path: Any) -> None:
    """Changing a resolved template input produces a cache miss and re-execution."""

    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # First run with input_val="hello"
    shared1: dict[str, Any] = {"__memoization_cache__": cache}
    iw1 = _build_wrapper_chain("diff-input", initial_params={"input_val": "hello"})
    iw1._run(shared1)
    assert CountingNode.exec_count == 1

    # Second run with input_val="world" (different input)
    shared2: dict[str, Any] = {"__memoization_cache__": cache}
    iw2 = _build_wrapper_chain("diff-input", initial_params={"input_val": "world"})
    iw2._run(shared2)
    assert CountingNode.exec_count == 2, "Node should re-execute for different inputs"

    # Outputs should differ
    assert shared1["diff-input"]["result"] == "result-1"
    assert shared2["diff-input"]["result"] == "result-2"


def test_no_memo_cache_in_shared(tmp_path: Any) -> None:
    """When __memoization_cache__ is absent, node executes normally without errors."""

    # Shared store WITHOUT __memoization_cache__
    shared: dict[str, Any] = {}
    iw = _build_wrapper_chain("no-cache-node", initial_params={"a": "b"})
    result = iw._run(shared)

    assert result == "default"
    assert CountingNode.exec_count == 1
    assert shared["no-cache-node"]["result"] == "result-1"


def test_memo_cache_skipped_for_revisited_nodes(tmp_path: Any) -> None:
    """When visit_count > 1 (looping), memoization is skipped and node re-executes."""

    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # First run: populate the memoization cache
    shared: dict[str, Any] = {"__memoization_cache__": cache}
    iw = _build_wrapper_chain("loop-node", initial_params={"p": "v"})
    iw._run(shared)
    assert CountingNode.exec_count == 1

    # Simulate a loop: _run() is called again on the SAME shared store
    # (visit_count increments to 2, so memoization should be skipped)
    result2 = iw._run(shared)
    assert CountingNode.exec_count == 2, "Memoization should be skipped for revisited nodes"
    assert result2 == "default"


def test_memo_cache_records_execution_state(tmp_path: Any) -> None:
    """On cache hit, __execution__ state is properly populated."""

    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # First run: populate cache
    shared1: dict[str, Any] = {"__memoization_cache__": cache}
    iw1 = _build_wrapper_chain("state-node", initial_params={"k": "v"})
    iw1._run(shared1)

    # Second run: cache hit path
    shared2: dict[str, Any] = {"__memoization_cache__": cache}
    iw2 = _build_wrapper_chain("state-node", initial_params={"k": "v"})
    iw2._run(shared2)

    execution = shared2["__execution__"]
    assert "state-node" in execution["completed_nodes"]
    assert execution["node_actions"]["state-node"] == "default"
    # Node hash should be recorded
    assert "state-node" in execution["node_hashes"]
    # Cache hit tracking
    assert "state-node" in shared2.get("__cache_hits__", [])


def test_memo_cache_no_write_on_error(tmp_path: Any) -> None:
    """When node returns 'error', the result is NOT written to the memo cache."""

    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    shared: dict[str, Any] = {"__memoization_cache__": cache}
    error_node = ErrorReturningNode()
    iw = _build_wrapper_chain("error-node", initial_params={"x": "1"}, node=error_node)
    result = iw._run(shared)

    assert result == "error"
    assert ErrorReturningNode.exec_count == 1

    # Compute the cache key and verify nothing was stored
    memo_key = iw._compute_memo_cache_key(shared)
    if memo_key:
        cached = cache.get(memo_key)
        assert cached is None, "Error results should not be written to memoization cache"
