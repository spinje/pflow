"""Four-tier token estimation per Task 159 DD#31.

Tier order (highest fidelity first):

1. ``trace``      — from a 2.1.0 JSON trace's per-event ``llm_call.input_tokens``.
                    Only path that gets discrepancy analysis in ``--from-trace`` mode.
2. ``memo``       — from ``MemoizationCache.get_latest_for_node()`` returning a recent
                    entry whose payload includes ``llm_usage.input_tokens``.
3. ``estimator``  — from ``litellm.token_counter(model=, text=)``.
4. ``heuristic``  — last-resort ``len(text) // 4`` (only place pflow uses a
                    char-based heuristic — flagged via the source label so
                    agents see the low-fidelity fallback).

Lazy-imports LiteLLM (mirrors ``llm_client.py`` lazy-import contract) to keep
the analyzer package import-cheap.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ``MemoizationCache.get_latest_for_node`` is the production caller's contract —
# a Protocol keeps this module test-friendly without a hard import.
class _MemoCacheLike(Protocol):
    def get_latest_for_node(
        self, node_id: str, *, workflow_path: str | None = None
    ) -> tuple[dict[str, Any], float] | None: ...


def estimate_tokens(
    model: str | None,
    text: str | None,
    *,
    trace: dict[str, Any] | None = None,
    memo_cache: _MemoCacheLike | None = None,
    node_id: str | None = None,
    workflow_path: str | None = None,
) -> tuple[int, str]:
    """Return ``(token_count, source)`` per the four-tier strategy.

    ``source ∈ {"trace", "memo", "estimator", "heuristic"}``. Confidence
    aggregation upstream uses these labels per DD#34.
    """
    # --- Tier 1: trace --------------------------------------------------------
    if trace is not None and node_id is not None:
        token_count = _from_trace(trace, node_id)
        if token_count is not None:
            return token_count, "trace"

    # --- Tier 2: memo cache ---------------------------------------------------
    if memo_cache is not None and node_id is not None:
        token_count = _from_memo(memo_cache, node_id, workflow_path=workflow_path)
        if token_count is not None:
            return token_count, "memo"

    # --- Tier 3: estimator (litellm.token_counter) ----------------------------
    if text is None:
        # Catches a known regression class — fall through to heuristic with
        # a visible warning so model-name typos don't degrade silently.
        logger.warning(
            "estimate_tokens(model=%r) received text=None — falling back to heuristic.",
            model,
        )
        return _heuristic(text), "heuristic"

    if model:
        try:
            token_count = _from_estimator(model, text)
        except Exception:
            logger.warning(
                "litellm.token_counter raised for model=%r; falling back to heuristic.",
                model,
                exc_info=True,
            )
            return _heuristic(text), "heuristic"
        else:
            return token_count, "estimator"

    # --- Tier 4: heuristic ----------------------------------------------------
    return _heuristic(text), "heuristic"


def estimate_output_tokens(
    *,
    trace: dict[str, Any] | None = None,
    memo_cache: _MemoCacheLike | None = None,
    node_id: str | None = None,
    workflow_path: str | None = None,
) -> tuple[int | None, str]:
    """Return ``(output_token_count | None, source)`` for an LLM call.

    Output tokens cannot be predicted ahead of an LLM call (we don't know how
    long the response will be). So the available tiers are limited to the two
    historical sources:

    - ``trace``       — ``llm_call.output_tokens`` from a 2.1.0 trace event.
    - ``memo``        — ``llm_usage.output_tokens`` from a memoized output.
    - ``unavailable`` — neither source carries the field; cost computations
                        that require output tokens degrade to ``None`` per the
                        cost tri-state contract (see ``cost_estimation.py``).

    Greenfield workflows (never run) always get ``unavailable``. Run the
    workflow once and the memo tier lights up automatically.
    """
    if trace is not None and node_id is not None:
        token_count = _output_from_trace(trace, node_id)
        if token_count is not None:
            return token_count, "trace"

    if memo_cache is not None and node_id is not None:
        token_count = _output_from_memo(memo_cache, node_id, workflow_path=workflow_path)
        if token_count is not None:
            return token_count, "memo"

    return None, "unavailable"


# ---------------------------------------------------------------------------
# Per-tier resolvers
# ---------------------------------------------------------------------------


def _from_trace(trace: dict[str, Any], node_id: str) -> int | None:
    """Pull ``llm_call.input_tokens`` for the given node from a trace's events."""
    return _llm_call_field_from_trace(trace, node_id, "input_tokens")


def _output_from_trace(trace: dict[str, Any], node_id: str) -> int | None:
    """Pull ``llm_call.output_tokens`` for the given node from a trace's events."""
    return _llm_call_field_from_trace(trace, node_id, "output_tokens")


def _llm_call_field_from_trace(trace: dict[str, Any], node_id: str, field: str) -> int | None:
    """Read an integer field from the first matching ``llm_call`` event.

    The trace JSON's top-level events list is keyed ``"nodes"`` (see
    ``runtime/workflow_trace.WorkflowTraceCollector.save_to_file``). Other
    consumers — ``core/trace_report.py`` and the runtime's own LLM-summary
    walker — also read ``trace["nodes"]``. This walker is non-recursive: it
    only finds ``node_id`` events at the top level. ``analyze.py`` only ever
    asks for ``type: llm`` IR nodes which always appear at top level; sub-
    workflow internal nodes (event["sub_workflow_events"]) and per-batch-item
    events (event["batch_items"][i]["events"]) are out of scope for this
    consumer. The recommendations-section plan's ``_iter_llm_events`` walker
    (sub-segment C) handles recursive descent for discrepancy detection.
    """
    events = trace.get("nodes")
    if not isinstance(events, list):
        return None
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("node_id") != node_id:
            continue
        llm_call = event.get("llm_call")
        if not isinstance(llm_call, dict):
            continue
        value = llm_call.get(field)
        if isinstance(value, int):
            return value
    return None


def _from_memo(memo_cache: _MemoCacheLike, node_id: str, *, workflow_path: str | None) -> int | None:
    """Pull ``llm_usage.input_tokens`` from the latest memoized output."""
    return _llm_usage_field_from_memo(memo_cache, node_id, workflow_path=workflow_path, field="input_tokens")


def _output_from_memo(memo_cache: _MemoCacheLike, node_id: str, *, workflow_path: str | None) -> int | None:
    """Pull ``llm_usage.output_tokens`` from the latest memoized output."""
    return _llm_usage_field_from_memo(memo_cache, node_id, workflow_path=workflow_path, field="output_tokens")


def _llm_usage_field_from_memo(
    memo_cache: _MemoCacheLike, node_id: str, *, workflow_path: str | None, field: str
) -> int | None:
    """Read an integer field from the latest memoized output's ``llm_usage`` dict."""
    try:
        result = memo_cache.get_latest_for_node(node_id, workflow_path=workflow_path)
    except Exception:
        logger.debug("memo_cache.get_latest_for_node raised", exc_info=True)
        return None
    if result is None:
        return None
    output, _created_at = result
    if not isinstance(output, dict):
        return None
    llm_usage = output.get("llm_usage")
    if not isinstance(llm_usage, dict):
        return None
    value = llm_usage.get(field)
    if isinstance(value, int):
        return value
    return None


def _from_estimator(model: str, text: str) -> int:
    """Lazy-import LiteLLM and call its model-aware tokenizer."""
    import litellm

    return int(litellm.token_counter(model=model, text=text))


def _heuristic(text: str | None) -> int:
    """Char-count heuristic — last-resort fallback only."""
    if not text:
        return 0
    return len(text) // 4


__all__ = ["estimate_output_tokens", "estimate_tokens"]
