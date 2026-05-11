"""D.2 — Prewarm execution: serialize first item, fan out the rest.

When a parallel batch LLM node has ``prewarm: true``, the executor splits
dispatch: item[0] runs synchronously through the SAME ``process_item``
closure the pool would use, then items[1:] dispatch through the pool. This
trades ~one item's latency for cache-write savings on the remaining N-1
items (which now read at 0.1x cost instead of writing at 1.25-2x cost).

The tests pin the load-bearing invariants:
- Item[0] runs before any item[i>0] (barrier-based ordering).
- Items[1:] cluster temporally (still parallel after item[0]).
- ``fail_fast`` + item[0] failure → items[1:] not dispatched.
- ``continue`` + item[0] failure → items[1:] dispatch anyway.
- N=1 batches skip prewarm split (no fan-out opportunity).
- prewarm=False → full fan-out from the start (today's behavior).
- ``_collect_parallel_results`` accepts ``initial_completed`` /
  ``total`` kwargs so progress accounts for the synchronously-run item[0].
"""

from __future__ import annotations

import threading
import time
from types import MappingProxyType
from typing import Any

import pytest

from pflow.core.cache_render import CacheRenderContext
from pflow.runtime.engine.batch_executor import (
    _collect_parallel_results,
    execute_batch,
)
from pflow.runtime.engine.types import BatchConfig, NodeConfig

# --- Test helpers ----------------------------------------------------------


def _make_node_config(
    *,
    node_id: str = "test_node",
    prewarm: bool = False,
    parallel: bool = True,
    error_handling: str = "continue",
    max_concurrent: int = 10,
) -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        node_type_name="LLMNode",
        template_config=None,
        batch_config=BatchConfig(
            items_template="${data}",
            item_alias="item",
            error_handling=error_handling,
            parallel=parallel,
            max_concurrent=max_concurrent,
            max_retries=1,
            retry_wait=0.0,
        ),
        namespaced=True,
        interface_metadata=None,
        prompt_cache_items=(),
        prewarm=prewarm,
    )


def _install_prewarm_ctx(shared: dict, node_id: str, *, prewarm: bool) -> None:
    """Install a minimal CacheRenderContext that toggles prewarm at the
    batch-executor read site."""
    ctx = CacheRenderContext(
        cache_block=None,
        subset=(),
        prewarm=prewarm,
        unresolved_batch_prompt=None,
        batch_alias=None,
    )
    shared["__pflow_cache_render__"] = MappingProxyType({node_id: ctx})


class _MockLLMNode:
    """Mock LLM node simulating per-item processing for prewarm tests.

    The optional ``execute_hook`` callable is invoked on every ``_run`` —
    barrier-based tests use it to coordinate item[0] and items[1:].

    Per-item state (timestamps, call counts) is written into ``shared``
    (which the batch executor shallow-copies so nested lists/dicts share
    by reference across threads). Storing on ``self`` would lose state to
    the executor's per-thread ``copy.deepcopy(node)`` — the deepcopied
    instance keeps its OWN attribute dict.
    """

    def __init__(self, *, execute_hook: Any = None) -> None:
        self.node_id = "test_node"
        self.execute_hook = execute_hook
        self.params: dict[str, Any] = {}

    def _run(self, shared: dict) -> str:
        idx = shared.get("__index__", 0)
        item = shared.get("item")
        timestamps = shared.get("__test_timestamps__")
        if timestamps is not None:
            timestamps[idx] = time.monotonic()
        call_log = shared.get("__test_call_log__")
        if call_log is not None:
            # GIL-protected list append.
            call_log.append(idx)
        if self.execute_hook is not None:
            self.execute_hook(idx=idx, item=item, shared=shared)
        shared[self.node_id] = {"index": idx, "item": item}
        return "default"


def _execute_single(node, config, item_shared):
    action = node._run(item_shared)
    return (action or "default", {}, [])


# --- Barrier-based ordering test (the load-bearing invariant) -------------


def test_prewarm_serializes_item_zero_then_fans_out() -> None:
    """Item[0] runs synchronously (does NOT enter the worker barrier);
    items[1:] all wait at a barrier with ``parties=N-1`` and unblock
    together. If item[0] is incorrectly submitted to the pool, it would
    enter the barrier (parties=N-1 is wrong for N) and the test deadlocks
    via the 1.0s timeout."""
    N = 4
    barrier = threading.Barrier(parties=N - 1, timeout=1.0)
    item_zero_completed = threading.Event()

    def hook(*, idx: int, **kwargs: Any) -> None:
        if idx == 0:
            time.sleep(0.05)  # item[0]'s synchronous "cache write"
            item_zero_completed.set()
        else:
            assert item_zero_completed.is_set(), f"item[{idx}] started before item[0] completed"
            barrier.wait()

    node = _MockLLMNode(execute_hook=hook)
    config = _make_node_config(prewarm=True)
    timestamps: dict[int, float] = {}
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "__test_timestamps__": timestamps,
    }
    _install_prewarm_ctx(shared, "test_node", prewarm=True)

    execute_batch(node, config, shared, _execute_single)

    # Item[0]'s timestamp precedes ALL workers' timestamps.
    assert all(timestamps[0] <= timestamps[i] for i in range(1, N))
    # Items[1:] cluster (all unblocked simultaneously when barrier filled).
    worker_ts = [timestamps[i] for i in range(1, N)]
    spread_ms = (max(worker_ts) - min(worker_ts)) * 1000
    assert spread_ms < 200, f"workers should cluster within 200ms, got {spread_ms:.1f}ms"


# --- Error handling: fail_fast + item[0] failure --------------------------


def test_prewarm_fail_fast_stops_after_item_zero_fails() -> None:
    """fail_fast + item[0] errors → items[1:] are NOT dispatched. Match the
    documented behavior at execute_batch:236 — raise AFTER aggregation so
    shared[node_id] retains the partial batch_metadata."""
    N = 5

    def hook(*, idx: int, **kwargs: Any) -> None:
        if idx == 0:
            raise RuntimeError("item[0] cache write failed")

    node = _MockLLMNode(execute_hook=hook)
    config = _make_node_config(prewarm=True, error_handling="fail_fast")
    call_log: list[int] = []
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "__test_call_log__": call_log,
    }
    _install_prewarm_ctx(shared, "test_node", prewarm=True)

    with pytest.raises(RuntimeError, match=r"item.0. cache write failed"):
        execute_batch(node, config, shared, _execute_single)

    # Only item[0] was attempted; items[1:] never dispatched.
    assert call_log == [0]


# --- Error handling: continue + item[0] failure ---------------------------


def test_prewarm_continue_dispatches_remainder_after_item_zero_fails() -> None:
    """error_handling=continue + item[0] errors → items[1:] dispatch anyway.
    They each pay the full cache-write cost (cache wasn't populated by
    item[0]) — documented expectation; runtime emits no warning."""
    N = 4

    def hook(*, idx: int, **kwargs: Any) -> None:
        if idx == 0:
            raise RuntimeError("item[0] write failed; continue")

    node = _MockLLMNode(execute_hook=hook)
    config = _make_node_config(prewarm=True, error_handling="continue")
    call_log: list[int] = []
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "__test_call_log__": call_log,
    }
    _install_prewarm_ctx(shared, "test_node", prewarm=True)

    execute_batch(node, config, shared, _execute_single)

    # item[0] (failed) + items[1:N] (succeeded) all attempted.
    assert sorted(call_log) == list(range(N))


# --- N=1 skip + prewarm=False fall-through --------------------------------


def test_prewarm_n1_skips_split() -> None:
    """N=1 batch with prewarm=True still completes (skipping the split is
    safe — no fan-out opportunity). Item[0] is the only call."""
    node = _MockLLMNode()
    config = _make_node_config(prewarm=True)
    call_log: list[int] = []
    shared: dict = {"data": [{"i": 0}], "__test_call_log__": call_log}
    _install_prewarm_ctx(shared, "test_node", prewarm=True)

    execute_batch(node, config, shared, _execute_single)

    assert call_log == [0]


def test_prewarm_false_full_fanout_no_serialization() -> None:
    """prewarm=False + N=4 → all N items enter a barrier with parties=N
    and unblock together (today's behavior; nothing serialized)."""
    N = 4
    barrier = threading.Barrier(parties=N, timeout=1.0)

    def hook(*, idx: int, **kwargs: Any) -> None:
        barrier.wait()

    node = _MockLLMNode(execute_hook=hook)
    config = _make_node_config(prewarm=False)
    call_log: list[int] = []
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "__test_call_log__": call_log,
    }
    _install_prewarm_ctx(shared, "test_node", prewarm=False)

    execute_batch(node, config, shared, _execute_single)

    assert sorted(call_log) == list(range(N))


def test_prewarm_no_cache_ctx_full_fanout() -> None:
    """No __pflow_cache_render__ at all (legacy non-cache workflow) → full
    fan-out. Defensive read at the executor must handle the absent key."""
    N = 4
    barrier = threading.Barrier(parties=N, timeout=1.0)

    def hook(*, idx: int, **kwargs: Any) -> None:
        barrier.wait()

    node = _MockLLMNode(execute_hook=hook)
    config = _make_node_config(prewarm=False)  # NodeConfig.prewarm=False too
    call_log: list[int] = []
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "__test_call_log__": call_log,
    }
    # No _install_prewarm_ctx call

    execute_batch(node, config, shared, _execute_single)

    assert sorted(call_log) == list(range(N))


# --- _collect_parallel_results signature widening -------------------------


def test_collect_parallel_results_accepts_initial_completed_and_total() -> None:
    """The widening must keep today's callers source-compatible (defaults),
    AND the new kwargs must flow through to the progress reporting site —
    callback fires with ``batch_current = initial_completed + 1`` and
    ``batch_total = total``. Without that flow-through the prewarm-split
    progress numbers would silently desync (item[0] reported as 1/N from
    synchronous run, item[1] reported as 1/N+1 from pool — off by one)."""
    from concurrent.futures import Future
    from unittest.mock import Mock

    # Construct a single completed future to exercise the signature.
    future: Future = Future()
    future.set_result((0, {"ok": True}, None, 1.0, []))
    future_to_idx = {future: 0}

    items: list[Any] = [{"i": 0}]
    results: list[Any] = [None]
    timings: list[float] = [0.0]
    pending_errors: list[dict] = []
    config = _make_node_config()
    batch_config = config.batch_config
    assert batch_config is not None

    progress_callback = Mock()

    # Calling with initial_completed=1, total=2 simulates "item[0] already
    # ran synchronously; item[1] in the pool". After draining the single
    # future, completed_count = 1 (initial) + 1 (drained) = 2 and total = 2.
    _collect_parallel_results(
        future_to_idx,
        items,
        results,
        timings,
        pending_errors,
        config,
        batch_config,
        callback=progress_callback,
        depth=0,
        initial_completed=1,
        total=2,
    )

    assert results[0] == {"ok": True}
    assert pending_errors == []

    # Verify the callback received the correct progress accounting kwargs.
    # _report_batch_progress signature:
    #   callback(node_id, "batch_progress", duration_ms, depth,
    #            batch_current=..., batch_total=..., batch_success=...)
    progress_calls = [
        call for call in progress_callback.call_args_list if len(call.args) >= 2 and call.args[1] == "batch_progress"
    ]
    assert len(progress_calls) == 1, f"expected one batch_progress call, got {progress_calls}"
    call = progress_calls[0]
    assert call.kwargs["batch_current"] == 2, (
        f"initial_completed kwarg did not flow through: expected batch_current=2 "
        f"(initial=1 + drained=1), got {call.kwargs['batch_current']!r}"
    )
    assert call.kwargs["batch_total"] == 2, (
        f"total kwarg did not flow through: expected batch_total=2, got {call.kwargs['batch_total']!r}"
    )
    assert call.kwargs["batch_success"] is True


def test_collect_parallel_results_defaults_preserve_legacy_callers() -> None:
    """Today's callers pass NO initial_completed / total — defaults must
    keep the legacy ``completed_count = 0`` and ``total = len(future_to_idx)``
    semantics."""
    from concurrent.futures import Future

    future: Future = Future()
    future.set_result((0, {"ok": True}, None, 1.0, []))
    future_to_idx = {future: 0}

    items: list[Any] = [{"i": 0}]
    results: list[Any] = [None]
    timings: list[float] = [0.0]
    pending_errors: list[dict] = []
    config = _make_node_config()
    batch_config = config.batch_config
    assert batch_config is not None

    # Old call shape — no kwargs.
    _collect_parallel_results(
        future_to_idx,
        items,
        results,
        timings,
        pending_errors,
        config,
        batch_config,
        callback=None,
        depth=0,
    )

    assert results[0] == {"ok": True}


# --- Sequential path ignores prewarm --------------------------------------


def test_prewarm_ignored_in_sequential_mode() -> None:
    """Sequential batches don't fan out; prewarm has no effect there.
    All items run in declared order anyway."""
    N = 3
    node = _MockLLMNode()
    config = _make_node_config(prewarm=True, parallel=False)
    call_log: list[int] = []
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "__test_call_log__": call_log,
    }
    _install_prewarm_ctx(shared, "test_node", prewarm=True)

    execute_batch(node, config, shared, _execute_single)

    assert call_log == [0, 1, 2]
