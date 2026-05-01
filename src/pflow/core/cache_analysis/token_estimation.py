"""Four-tier token estimation per Task 159 DD#31.

``estimate_tokens`` (input):

1. ``trace``      — from a 2.1.0 JSON trace's per-event ``llm_call.input_tokens``.
                    Only path that gets discrepancy analysis in ``--from-trace`` mode.
2. ``memo``       — from ``MemoizationCache.get_latest_for_node()`` returning a recent
                    entry whose payload includes ``llm_usage.input_tokens``.
3. ``estimator``  — from ``litellm.token_counter(model=, text=)``.
4. ``heuristic``  — last-resort ``len(text) // 4`` (only place pflow uses a
                    char-based heuristic — flagged via the source label so
                    agents see the low-fidelity fallback).

``estimate_output_tokens``: ``trace → memo → unavailable``. Output tokens
cannot be predicted ahead of an LLM call.

``estimate_cacheable_tokens``:

1. ``trace``      — from a 2.1.0 trace event's
                    ``cache_creation_input_tokens + cache_read_input_tokens``.
                    Falls through when both fields are 0 (cache declared but
                    didn't fire — sub-threshold etc.).
2. ``memo``       — sum of memo-resolved chunk token counts (declared OR
                    candidate subsets). Partial memo data: declared subsets
                    fall through to Tier 3; candidate-only returns Tier 4.
3. ``estimator``  — heuristic on raw prompt template (declared subset only —
                    preserves ``cache.below-min-tokens`` warning fidelity).
4. ``unavailable`` — None propagation (Option C — honest unmeasurable).

Lazy-imports LiteLLM (mirrors ``llm_client.py`` lazy-import contract) to keep
the analyzer package import-cheap. Lazy-imports ``TemplateResolver`` inside
``_latest_value_for_ref`` to keep the layer-policy clean.
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


def estimate_cacheable_tokens(
    *,
    declared_subset: list[str] | None,
    candidate_subset: list[str] | None,
    trace_event: dict[str, Any] | None,
    memo_cache: _MemoCacheLike | None,
    model: str,
    workflow_path: str | None,
    prompt: str = "",
) -> tuple[int | None, str]:
    """Return ``(cacheable_tokens, source)`` using highest-fidelity available data.

    Sources: ``"trace"``, ``"memo"``, ``"estimator"``, ``"unavailable"``.

    Asymmetric fall-through (load-bearing):

    - For DECLARED subsets: partial memo data → falls through to Tier 3
      (heuristic) to preserve ``cache.below-min-tokens`` warning fidelity.
    - For CANDIDATE-only (greenfield projection): partial memo data →
      returns ``(None, "unavailable")`` (Option C — honest unmeasurable).

    Tier 1 fall-through: when declared subset has trace_event with
    ``cache_creation+cache_read == 0`` (cache declared but didn't fire —
    sub-threshold etc.), fall through to Tier 2/3. Downstream
    ``cache.below-min-tokens`` warning is gated on ``cacheable_data_source !=
    "trace"`` so it fires correctly for the fallthrough cases without
    contradicting trace evidence when cache demonstrably worked.
    """
    # Tier 1: trace ground truth — only meaningful for declared cache that fired.
    if declared_subset and trace_event is not None:
        creation = int(trace_event.get("cache_creation_input_tokens") or 0)
        read = int(trace_event.get("cache_read_input_tokens") or 0)
        if creation + read > 0:
            return (creation + read, "trace")
        # Fall through: declared but didn't fire. Tier 2/3 computes
        # "what was attempted" so cache.below-min-tokens fires correctly.

    # Tier 2: memo-resolved chunk tokenization (declared OR candidate).
    chunks = declared_subset or candidate_subset
    if chunks and memo_cache is not None and model:
        total = _sum_resolved_chunk_tokens(chunks, model, memo_cache, workflow_path)
        if total is not None:
            return (total, "memo")
        # Fall through to Tier 3 for declared (preserves below-min-tokens fidelity).
        # For candidate-only, fall through to Tier 4 (Option C — honest unmeasurable).

    # Tier 3: estimator (declared subset only — heuristic; preserves below-min-tokens).
    if declared_subset:
        return (max(0, len(prompt) * 75 // 400), "estimator")

    # Tier 4: nothing to project — honest unavailable.
    return (None, "unavailable")


def _sum_resolved_chunk_tokens(
    chunks: list[str],
    model: str,
    memo_cache: _MemoCacheLike,
    workflow_path: str | None,
) -> int | None:
    """Sum memo-resolved chunk token counts. None if any chunk has no memo data."""
    total = 0
    for ref in chunks:
        tokens = _estimate_ref_tokens(ref, model=model, memo_cache=memo_cache, workflow_path=workflow_path)
        if tokens is None:
            return None
        total += tokens
    return total


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


def _find_llm_event(trace: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    """Return the first matching ``llm_call`` event dict for the given node_id.

    Non-recursive (top-level events only — sub_workflow_events and
    batch_items[i].events out of scope per existing
    ``_llm_call_field_from_trace`` contract). The trace JSON's top-level
    events list is keyed ``"nodes"`` (see
    ``runtime/workflow_trace.WorkflowTraceCollector.save_to_file``).
    ``analyze.py`` only ever asks for ``type: llm`` IR nodes which always
    appear at top level; the recommendations-section's ``_iter_llm_events``
    walker handles recursive descent for discrepancy detection.

    For batch nodes, trace may have multiple events for one node_id. This
    helper picks first-match (deterministic). Prewarm flows that shift
    chunk membership mid-batch may not be representative — revisit when
    prewarm hits Stage 2.
    """
    events = trace.get("nodes")
    if not isinstance(events, list):
        return None
    for event in events:
        if not isinstance(event, dict) or event.get("node_id") != node_id:
            continue
        llm_call = event.get("llm_call")
        if isinstance(llm_call, dict):
            return llm_call
    return None


def _llm_call_field_from_trace(trace: dict[str, Any], node_id: str, field: str) -> int | None:
    """Read an integer field from the first matching ``llm_call`` event."""
    llm_call = _find_llm_event(trace, node_id)
    if llm_call is None:
        return None
    value = llm_call.get(field)
    return value if isinstance(value, int) else None


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


# ---------------------------------------------------------------------------
# Per-reference value tokenization (Tier 2 primitive for ``estimate_cacheable_tokens``)
# ---------------------------------------------------------------------------


def _estimate_ref_tokens(ref: str, *, model: str, memo_cache: Any, workflow_path: str | None) -> int | None:
    """Tokenize a template reference's resolved value.

    Returns:
        - Real token count when memo cache holds a recent value for the ref's
          root node (high-fidelity).
        - ``None`` when memo is empty / lookup fails (no run data — projection
          unavailable). Callers MUST distinguish ``None`` from a small int.

    The previous fallback (tokenize the literal ``${ref}`` string, ~3-5 tokens)
    was structurally misleading: it produced a tiny number that looked like a
    real estimate but actually represented "we have no data" — agents reading
    ``cacheable=38`` thought the opportunity was small when actually it was
    unmeasured. ``None`` propagation lets the renderer hide misleading rows
    explicitly per Option C (see render_text._render_per_call).
    """
    value = _latest_value_for_ref(ref, memo_cache=memo_cache, workflow_path=workflow_path)
    if value is not None:
        # Lazy-import to avoid heavy ``cache_render`` import at module load.
        from pflow.core.cache_render import deterministic_serialize

        return estimate_tokens(model, deterministic_serialize(value))[0]
    return None


def _latest_value_for_ref(ref: str, *, memo_cache: Any, workflow_path: str | None) -> Any:
    """Resolve ``ref`` to its latest memoized value, or None if unavailable."""
    if memo_cache is None:
        return None
    # Lazy-import keeps token_estimation.py layer-clean (mirrors litellm pattern).
    from pflow.runtime.template_resolver import TemplateResolver

    root = TemplateResolver.extract_root_node_id(ref)
    try:
        latest = memo_cache.get_latest_for_node(root, workflow_path=workflow_path)
    except Exception:
        logger.debug("memo_cache.get_latest_for_node failed while estimating %s", ref, exc_info=True)
        return None
    if latest is None:
        return None
    output, _created_at = latest
    if not isinstance(output, dict):
        return None
    resolved = TemplateResolver.resolve_template(f"${{{ref}}}", {root: output})
    if isinstance(resolved, str) and resolved == f"${{{ref}}}":
        return None
    return resolved


__all__ = ["estimate_cacheable_tokens", "estimate_output_tokens", "estimate_tokens"]
