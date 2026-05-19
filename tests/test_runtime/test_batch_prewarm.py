"""D.2 — Synthetic cache warmup for parallel batch LLM nodes.

When a parallel batch LLM node has declared cache chunks (prompt_cache: [...]),
the executor issues a minimal synthetic LLM call (max_tokens=16) to populate
the provider's system-message cache prefix, then fans out ALL items in
parallel. The warmup decision is based on declared cache presence (subset),
NOT the ``prewarm`` flag — ``prewarm`` controls auto-batch-prefix markers
on the user message, which is an independent concern.

The tests pin the load-bearing invariants:
- All N items fan out in parallel (no item-0 serialization).
- ``_execute_synthetic_warmup`` is called when declared cache chunks exist.
- Synthetic warmup failure is non-fatal (batch continues).
- N=1 batches skip warmup (no fan-out benefit).
- No declared cache → no warmup call (regardless of prewarm flag).
- ``_collect_parallel_results`` accepts ``initial_completed`` /
  ``total`` kwargs (signature compatibility).
"""

from __future__ import annotations

import threading
from types import MappingProxyType
from typing import Any
from unittest.mock import patch

from pflow.core.prompt_cache import CacheBlockIR, CacheChunkIR, CacheRenderContext
from pflow.runtime.engine.batch_executor import (
    _collect_parallel_results,
    _execute_synthetic_warmup,
    execute_batch,
)
from pflow.runtime.engine.types import BatchConfig, NodeConfig, TemplateConfig

# --- Test helpers ----------------------------------------------------------


def _make_node_config(
    *,
    node_id: str = "test_node",
    prewarm: bool = False,
    parallel: bool = True,
    error_handling: str = "continue",
    max_concurrent: int = 10,
    template_config: TemplateConfig | None = None,
) -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        node_type_name="LLMNode",
        template_config=template_config,
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


_DUMMY_CACHE_BLOCK = CacheBlockIR(
    ttl="5m",
    items=(CacheChunkIR(name="ctx", var_expr="upstream.result", prose_before="Context:\n\n", source_line=1),),
    source_line=1,
)


def _install_prewarm_ctx(
    shared: dict,
    node_id: str,
    *,
    prewarm: bool,
    with_declared_cache: bool = False,
    with_auto_batch_prefix: bool = False,
) -> None:
    """Install a minimal CacheRenderContext for batch-executor tests.

    ``with_declared_cache=True`` populates ``cache_block`` and ``subset``
    so the declared-cache arm of the warmup gate fires.

    ``with_auto_batch_prefix=True`` populates ``unresolved_batch_prompt``
    and ``batch_alias`` so the auto-batch-prefix arm of the warmup gate
    fires (requires ``prewarm=True`` on the context per the gate logic).
    """
    ctx = CacheRenderContext(
        cache_block=_DUMMY_CACHE_BLOCK if with_declared_cache else None,
        subset=("ctx",) if with_declared_cache else (),
        prewarm=prewarm,
        unresolved_batch_prompt=(
            "You are evaluating against this rubric:\n\nRule 1 ... Rule 100.\n\nScore: ${item.text}"
            if with_auto_batch_prefix
            else None
        ),
        batch_alias="item" if with_auto_batch_prefix else None,
    )
    shared["__pflow_prompt_cache__"] = MappingProxyType({node_id: ctx})


class _MockLLMNode:
    """Mock LLM node simulating per-item processing for prewarm tests.

    The optional ``execute_hook`` callable is invoked on every ``_run`` —
    barrier-based tests use it to coordinate thread ordering.

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


# --- All items fan out in parallel (the load-bearing invariant) ----------


def test_prewarm_all_items_fan_out_in_parallel() -> None:
    """All N items enter the pool and run in parallel. A barrier with
    parties=N verifies all items are dispatched concurrently. No declared
    cache is installed, so the synthetic warmup gate does not fire."""
    N = 4
    barrier = threading.Barrier(parties=N, timeout=2.0)

    def hook(*, idx: int, **kwargs: Any) -> None:
        barrier.wait()

    node = _MockLLMNode(execute_hook=hook)
    config = _make_node_config(prewarm=True)
    call_log: list[int] = []
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "__test_call_log__": call_log,
    }
    _install_prewarm_ctx(shared, "test_node", prewarm=True)

    execute_batch(node, config, shared, _execute_single)

    # All N items were dispatched.
    assert sorted(call_log) == list(range(N))


# --- Synthetic warmup is called when declared cache exists ----------------


def test_prewarm_calls_synthetic_warmup() -> None:
    """When declared cache chunks exist and N>1, _execute_synthetic_warmup
    is called before the parallel fan-out."""
    N = 3
    node = _MockLLMNode()
    config = _make_node_config(prewarm=True)
    call_log: list[int] = []
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "__test_call_log__": call_log,
    }
    _install_prewarm_ctx(shared, "test_node", prewarm=True, with_declared_cache=True)

    with patch(
        "pflow.runtime.engine.batch_executor._execute_synthetic_warmup",
        return_value={"model": "test", "input_tokens": 10, "output_tokens": 2, "cost_usd": 0.001},
    ) as mock_warmup:
        execute_batch(node, config, shared, _execute_single)

    mock_warmup.assert_called_once()
    # All items still dispatched after warmup.
    assert sorted(call_log) == list(range(N))


def test_declared_cache_without_prewarm_skips_warmup() -> None:
    """Declared cache chunks alone do NOT trigger warmup. The user must
    also set prewarm: true to opt in to the synthetic warmup call."""
    N = 3
    node = _MockLLMNode()
    config = _make_node_config(prewarm=False)
    call_log: list[int] = []
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "__test_call_log__": call_log,
    }
    _install_prewarm_ctx(shared, "test_node", prewarm=False, with_declared_cache=True)

    with patch(
        "pflow.runtime.engine.batch_executor._execute_synthetic_warmup",
    ) as mock_warmup:
        execute_batch(node, config, shared, _execute_single)

    mock_warmup.assert_not_called()
    assert sorted(call_log) == list(range(N))


def test_prewarm_true_without_buildable_blocks_skips_warmup() -> None:
    """prewarm: true with no declared cache AND no auto-batch-prefix
    (no unresolved_batch_prompt or batch_alias) does NOT trigger warmup.
    There's nothing to warm. The gate checks both arms — declared cache OR
    auto-batch-prefix — and falls through when neither applies."""
    N = 3
    node = _MockLLMNode()
    config = _make_node_config(prewarm=True)
    call_log: list[int] = []
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "__test_call_log__": call_log,
    }
    # _install_prewarm_ctx with with_declared_cache=False sets cache_block=None,
    # subset=(), unresolved_batch_prompt=None, batch_alias=None — neither arm
    # of the warmup gate fires.
    _install_prewarm_ctx(shared, "test_node", prewarm=True, with_declared_cache=False)

    with patch(
        "pflow.runtime.engine.batch_executor._execute_synthetic_warmup",
    ) as mock_warmup:
        execute_batch(node, config, shared, _execute_single)

    mock_warmup.assert_not_called()
    assert sorted(call_log) == list(range(N))


# --- Auto-batch-prefix warmup (declared cache not required) ---------------


def test_warmup_fires_for_auto_batch_prefix_without_declared_cache() -> None:
    """When prewarm: true is set on a batch with a large static prompt prefix
    (auto-batch-prefix) but no declared ## Cache, the warmup STILL fires —
    it warms the user-message cache via the same prefix the batch items will
    send. This was a regression from the initial implementation where the
    gate required declared cache to be present."""
    N = 3
    node = _MockLLMNode()
    config = _make_node_config(prewarm=True)
    call_log: list[int] = []
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "__test_call_log__": call_log,
    }
    # prewarm=True on the ctx (post-pre-flight) + auto-batch-prefix populated.
    # No declared cache → has_declared_cache=False, has_auto_batch_prefix=True.
    _install_prewarm_ctx(
        shared,
        "test_node",
        prewarm=True,
        with_declared_cache=False,
        with_auto_batch_prefix=True,
    )

    with patch(
        "pflow.runtime.engine.batch_executor._execute_synthetic_warmup",
        return_value={"model": "test", "input_tokens": 100, "output_tokens": 2, "cost_usd": 0.001},
    ) as mock_warmup:
        execute_batch(node, config, shared, _execute_single)

    mock_warmup.assert_called_once()
    assert sorted(call_log) == list(range(N))


def test_warmup_fires_when_both_declared_cache_and_auto_batch_prefix_exist() -> None:
    """When BOTH cache mechanisms apply, warmup fires once and the warmup
    function builds both system_blocks AND user_message_blocks internally
    (verified by the _execute_synthetic_warmup unit tests). The gate just
    needs at least one arm true."""
    N = 3
    node = _MockLLMNode()
    config = _make_node_config(prewarm=True)
    call_log: list[int] = []
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "__test_call_log__": call_log,
    }
    _install_prewarm_ctx(
        shared,
        "test_node",
        prewarm=True,
        with_declared_cache=True,
        with_auto_batch_prefix=True,
    )

    with patch(
        "pflow.runtime.engine.batch_executor._execute_synthetic_warmup",
        return_value={"model": "test", "input_tokens": 100, "output_tokens": 2, "cost_usd": 0.001},
    ) as mock_warmup:
        execute_batch(node, config, shared, _execute_single)

    mock_warmup.assert_called_once()
    assert sorted(call_log) == list(range(N))


def test_auto_batch_prefix_warmup_skipped_when_pre_flight_disabled() -> None:
    """The auto-batch-prefix arm requires cache_ctx.prewarm=True (post-pre-flight).
    When the pre-flight check _should_disable_below_min_prewarm has set
    cache_ctx.prewarm=False (user-message prefix below provider minimum), the
    auto-batch-prefix arm of the gate is False. If no declared cache exists
    either, no warmup fires — the user-message marker would no-op at the
    provider, so warming it would be wasted."""
    N = 3
    node = _MockLLMNode()
    config = _make_node_config(prewarm=True)  # user declared prewarm: true
    call_log: list[int] = []
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "__test_call_log__": call_log,
    }
    # cache_ctx.prewarm=False simulates the pre-flight disabling auto-batch-prefix.
    # No declared cache. has_declared_cache=False, has_auto_batch_prefix=False
    # (requires cache_ctx.prewarm=True).
    _install_prewarm_ctx(
        shared,
        "test_node",
        prewarm=False,  # post-pre-flight value on ctx
        with_declared_cache=False,
        with_auto_batch_prefix=True,
    )

    with patch(
        "pflow.runtime.engine.batch_executor._execute_synthetic_warmup",
    ) as mock_warmup:
        execute_batch(node, config, shared, _execute_single)

    mock_warmup.assert_not_called()
    assert sorted(call_log) == list(range(N))


# --- Synthetic warmup failure is non-fatal --------------------------------


def test_prewarm_warmup_failure_does_not_block_batch() -> None:
    """If _execute_synthetic_warmup returns False (failure), all items
    still fan out in parallel."""
    N = 4
    barrier = threading.Barrier(parties=N, timeout=2.0)

    def hook(*, idx: int, **kwargs: Any) -> None:
        barrier.wait()

    node = _MockLLMNode(execute_hook=hook)
    config = _make_node_config(prewarm=True)
    call_log: list[int] = []
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "__test_call_log__": call_log,
    }
    _install_prewarm_ctx(shared, "test_node", prewarm=True, with_declared_cache=True)

    with patch(
        "pflow.runtime.engine.batch_executor._execute_synthetic_warmup",
        return_value=None,
    ):
        execute_batch(node, config, shared, _execute_single)

    assert sorted(call_log) == list(range(N))


# --- N=1 skip + prewarm=False fall-through --------------------------------


def test_prewarm_n1_skips_warmup() -> None:
    """N=1 batch with declared cache still completes (skipping warmup —
    no fan-out benefit). Item[0] is the only call."""
    node = _MockLLMNode()
    config = _make_node_config(prewarm=True)
    call_log: list[int] = []
    shared: dict = {"data": [{"i": 0}], "__test_call_log__": call_log}
    _install_prewarm_ctx(shared, "test_node", prewarm=True, with_declared_cache=True)

    with patch(
        "pflow.runtime.engine.batch_executor._execute_synthetic_warmup",
    ) as mock_warmup:
        execute_batch(node, config, shared, _execute_single)

    # Warmup not called for N=1 (should_warmup is False when len(items) <= 1).
    mock_warmup.assert_not_called()
    assert call_log == [0]


def test_prewarm_false_full_fanout_no_warmup() -> None:
    """prewarm=False + N=4 → all N items enter a barrier with parties=N
    and unblock together. No warmup call."""
    N = 4
    barrier = threading.Barrier(parties=N, timeout=2.0)

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
    """No __pflow_prompt_cache__ at all (legacy non-cache workflow) → full
    fan-out. Defensive read at the executor must handle the absent key."""
    N = 4
    barrier = threading.Barrier(parties=N, timeout=2.0)

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


# --- _execute_synthetic_warmup unit tests ---------------------------------


def test_synthetic_warmup_returns_none_when_no_template_config() -> None:
    """No template_config → cannot resolve model → returns None."""
    config = _make_node_config(prewarm=True)
    ctx = CacheRenderContext(
        cache_block=None,
        subset=(),
        prewarm=True,
        unresolved_batch_prompt=None,
        batch_alias=None,
    )
    assert _execute_synthetic_warmup(config, {}, ctx) is None


def test_synthetic_warmup_returns_none_when_no_model() -> None:
    """template_config exists but no model param → returns None."""
    tc = TemplateConfig(
        template_params={},
        static_params={"system": "You are helpful."},
        expected_types={},
        resolution_mode="strict",
    )
    config = _make_node_config(prewarm=True, template_config=tc)
    ctx = CacheRenderContext(
        cache_block=None,
        subset=(),
        prewarm=True,
        unresolved_batch_prompt=None,
        batch_alias=None,
    )
    assert _execute_synthetic_warmup(config, {}, ctx) is None


def test_synthetic_warmup_returns_none_when_no_system_blocks() -> None:
    """Model resolves but build_cache_system_blocks returns None → None."""
    tc = TemplateConfig(
        template_params={},
        static_params={"model": "anthropic/claude-sonnet-4-5"},
        expected_types={},
        resolution_mode="strict",
    )
    config = _make_node_config(prewarm=True, template_config=tc)
    # cache_block=None + empty subset → build_cache_system_blocks returns (None, [])
    ctx = CacheRenderContext(
        cache_block=None,
        subset=(),
        prewarm=True,
        unresolved_batch_prompt=None,
        batch_alias=None,
    )
    assert _execute_synthetic_warmup(config, {}, ctx) is None


def test_synthetic_warmup_catches_exception_and_returns_none() -> None:
    """If the LLM call raises, warmup catches the exception and returns None."""
    tc = TemplateConfig(
        template_params={},
        static_params={"model": "anthropic/claude-sonnet-4-5"},
        expected_types={},
        resolution_mode="strict",
    )
    config = _make_node_config(prewarm=True, template_config=tc)
    ctx = CacheRenderContext(
        cache_block=None,
        subset=(),
        prewarm=True,
        unresolved_batch_prompt=None,
        batch_alias=None,
    )

    # Patch build_cache_system_blocks to return real blocks, then make complete() raise.
    with (
        patch(
            "pflow.core.prompt_cache.build_cache_system_blocks",
            return_value=([{"type": "text", "text": "system"}], []),
        ),
        patch(
            "pflow.core.llm_client.complete",
            side_effect=RuntimeError("connection failed"),
        ),
    ):
        result = _execute_synthetic_warmup(config, {}, ctx)

    assert result is None


def test_synthetic_warmup_happy_path_calls_complete_correctly() -> None:
    """Happy path: model resolves, system blocks build, complete() is called
    with the expected warmup parameters (max_tokens=16, temperature=0).
    Returns the usage dict from the response."""
    tc = TemplateConfig(
        template_params={},
        static_params={"model": "anthropic/claude-sonnet-4-5", "system": "You are helpful."},
        expected_types={},
        resolution_mode="strict",
    )
    config = _make_node_config(prewarm=True, template_config=tc)
    ctx = CacheRenderContext(
        cache_block=_DUMMY_CACHE_BLOCK,
        subset=("ctx",),
        prewarm=True,
        unresolved_batch_prompt=None,
        batch_alias=None,
    )
    shared: dict[str, Any] = {"upstream": {"result": "large cached content here"}}

    mock_usage = {
        "model": "anthropic/claude-sonnet-4-5",
        "input_tokens": 150,
        "output_tokens": 2,
        "total_tokens": 152,
        "cache_creation_input_tokens": 140,
        "cache_read_input_tokens": 0,
        "cost_usd": 0.0015,
    }

    class _MockResp:
        usage = mock_usage

    with patch("pflow.core.llm_client.complete", return_value=_MockResp()) as mock_complete:
        result = _execute_synthetic_warmup(config, shared, ctx)

    assert result is mock_usage
    mock_complete.assert_called_once()
    call_kwargs = mock_complete.call_args
    assert call_kwargs.kwargs["model"] == "anthropic/claude-sonnet-4-5"
    assert call_kwargs.kwargs["max_tokens"] == 16
    assert call_kwargs.kwargs["temperature"] == 0
    assert call_kwargs.kwargs["prompt"] == "Reply with: OK"
    assert isinstance(call_kwargs.kwargs["system"], list)
    assert len(call_kwargs.kwargs["system"]) >= 1


# --- _collect_parallel_results signature widening -------------------------


def test_collect_parallel_results_accepts_initial_completed_and_total() -> None:
    """The kwargs must flow through to the progress reporting site —
    callback fires with ``batch_current = initial_completed + 1`` and
    ``batch_total = total``."""
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


# --- Warmup cost telemetry tests -------------------------------------------


def test_warmup_cost_in_trace_as_synthetic_batch_item() -> None:
    """When warmup succeeds, a synthetic batch trace item with is_warmup=True
    appears in _batch_trace so cost flows through the existing trace pipeline."""
    N = 3
    node = _MockLLMNode()
    tc = TemplateConfig(
        template_params={},
        static_params={"model": "anthropic/claude-sonnet-4-5", "system": "You are helpful."},
        expected_types={},
        resolution_mode="strict",
    )
    config = _make_node_config(prewarm=True, template_config=tc)
    shared: dict = {
        "data": [{"i": i} for i in range(N)],
        "upstream": {"result": "cached content"},
    }
    _install_prewarm_ctx(shared, "test_node", prewarm=True, with_declared_cache=True)

    mock_usage = {
        "model": "anthropic/claude-sonnet-4-5",
        "input_tokens": 150,
        "output_tokens": 2,
        "total_tokens": 152,
        "cache_creation_input_tokens": 140,
        "cache_read_input_tokens": 0,
        "cost_usd": 0.0015,
    }

    class _MockResp:
        usage = mock_usage

    with patch("pflow.core.llm_client.complete", return_value=_MockResp()):
        execute_batch(node, config, shared, _execute_single)

    # The batch trace should contain N regular items + 1 warmup item
    batch_trace = shared.get("_batch_trace", {}).get("test_node", [])
    warmup_items = [item for item in batch_trace if item.get("llm_call", {}).get("is_warmup")]
    assert len(warmup_items) == 1

    warmup = warmup_items[0]
    assert warmup["index"] == -1
    assert warmup["item"] == "__cache_warmup__"
    assert warmup["success"] is True
    assert warmup["duration_ms"] > 0
    assert warmup["llm_call"]["cost_usd"] == 0.0015
    assert warmup["llm_call"]["is_warmup"] is True
    assert warmup["llm_prompt"] == "Reply with: OK"


def test_warmup_failure_produces_no_synthetic_item() -> None:
    """When warmup returns None (failure), no synthetic item is appended."""
    N = 3
    node = _MockLLMNode()
    config = _make_node_config(prewarm=True)
    shared: dict = {"data": [{"i": i} for i in range(N)]}
    _install_prewarm_ctx(shared, "test_node", prewarm=True, with_declared_cache=True)

    with patch(
        "pflow.runtime.engine.batch_executor._execute_synthetic_warmup",
        return_value=None,
    ):
        execute_batch(node, config, shared, _execute_single)

    batch_trace = shared.get("_batch_trace", {}).get("test_node", [])
    warmup_items = [item for item in batch_trace if item.get("llm_call", {}).get("is_warmup")]
    assert len(warmup_items) == 0


def test_warmup_cost_excluded_from_call_count() -> None:
    """MetricsCollector.get_summary excludes warmup from total_calls but
    includes warmup cost in total_cost_usd."""
    from pflow.core.metrics import MetricsCollector

    collector = MetricsCollector()
    collector.record_workflow_start()
    collector.record_workflow_end()

    llm_calls = [
        {"model": "test-model", "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.005},
        {"model": "test-model", "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.005},
        {"model": "test-model", "input_tokens": 150, "output_tokens": 2, "cost_usd": 0.015, "is_warmup": True},
    ]

    summary = collector.get_summary(llm_calls)
    assert summary["metrics"]["total"]["total_calls"] == 2
    assert summary["metrics"]["total"]["cost_usd"] == 0.025


def test_warmup_with_unpriced_model_excluded_from_unavailable_count() -> None:
    """A warmup call with cost_usd=None and a real model name should NOT
    be counted in unavailable_models or unavailable_models_unnamed_count.
    Regression test for the if/else miscount in metrics.calculate_costs:
    before the fix, an is_warmup call with cost_usd=None + real model would
    fall into the else branch and inflate unavailable_models_unnamed_count."""
    from pflow.core.metrics import MetricsCollector

    collector = MetricsCollector()
    collector.record_workflow_start()
    collector.record_workflow_end()

    llm_calls = [
        # Real call with known model and pricing.
        {"model": "test-model", "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.005},
        # Warmup call with unpriced model (e.g., Ollama, brand-new release).
        {
            "model": "ollama/custom-llama",
            "input_tokens": 150,
            "output_tokens": 2,
            "cost_usd": None,
            "is_warmup": True,
        },
    ]

    summary = collector.get_summary(llm_calls)
    total = summary["metrics"]["total"]

    # Warmup must not inflate the call count.
    assert total["total_calls"] == 1
    # Only the priced call contributes to total cost.
    assert total["cost_usd"] == 0.005

    # KEY INVARIANT: warmup with unpriced model leaves both unavailable
    # counters at zero. Pricing is considered available because the only
    # non-warmup call has a recorded cost.
    assert summary.get("pricing_available", True) is True
    # When pricing is available, calculate_costs does not emit unavailable_*
    # keys at all — assert they're absent (or empty if any consumer ever
    # adds them defensively).
    assert total.get("unavailable_models", []) == []
    assert total.get("unavailable_models_unnamed_count", 0) == 0
    assert summary.get("unavailable_models", []) == []
    assert summary.get("unavailable_models_unnamed_count", 0) == 0
