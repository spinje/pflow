"""Four-tier token estimation per Task 159 DD#31.

``estimate_tokens`` (input):

1. ``trace``              — from a 2.1.0 JSON trace's per-event ``llm_call.input_tokens``.
                            Only path that gets discrepancy analysis in ``--from-trace`` mode.
2. ``memo``               — from ``MemoizationCache.get_latest_for_node()`` returning a recent
                            entry whose payload includes ``llm_usage.input_tokens``.
3. ``estimator``          — from ``litellm.token_counter(model=, text=)`` on a
                            FULLY RESOLVED prompt (every ``${...}`` substituted).
3a. ``estimator-partial`` — same as ``estimator``, but at least one ``${...}``
                            ref couldn't be resolved (greenfield-no-data).
                            Caller flags this via ``has_unresolved_refs=True``.
4. ``heuristic``          — last-resort ``len(text) // 4`` (only place pflow uses
                            a char-based heuristic — flagged via the source label
                            so agents see the low-fidelity fallback).

``estimate_output_tokens``: ``trace → memo → unavailable``. Output tokens
cannot be predicted ahead of an LLM call.

``estimate_cacheable_tokens``:

1. ``trace``       — from a 2.1.0 trace event's
                     ``cache_creation_input_tokens + cache_read_input_tokens``.
                     Falls through when both fields are 0 (cache declared but
                     didn't fire — sub-threshold etc.).
2. ``memo`` /
   ``parameters``  — sum of resolved chunk token counts (declared OR
                     candidate subsets). All chunks must resolve; partial
                     resolution falls through to Tier 3.
3. ``unavailable`` — None propagation (Option C — honest unmeasurable).
                     Downstream ``cache.below-min-predicted`` naturally
                     suppresses; runtime-tier observed warning still fires
                     after first run.

Lazy-imports LiteLLM (mirrors ``llm_client.py`` lazy-import contract) to keep
the analyzer package import-cheap. Lazy-imports ``TemplateResolver`` inside
template-resolution helpers to keep the layer-policy clean.

``tokenize_prompt_region`` is exact: unresolved template refs make the region
unmeasurable. ``tokenize_prompt_region_lower_bound`` is advisory-only: it
counts resolvable bytes and treats unresolved refs as zero while returning the
refs that need runtime verification.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .context import AnalysisContext

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
    has_unresolved_refs: bool = False,
    ctx: AnalysisContext | None = None,
) -> tuple[int, str]:
    """Return ``(token_count, source)`` per the four-tier strategy.

    ``source ∈ {"trace", "memo", "estimator", "estimator-partial", "heuristic"}``.
    The ``estimator-partial`` source is emitted when the caller resolved the
    prompt template before tokenization but at least one ``${...}`` reference
    couldn't be substituted (greenfield-no-data for some refs). It signals
    "estimator ran on a prompt that's still partially literal" — agents
    treat the count as low-confidence per DD#34's confidence aggregation.

    Confidence aggregation treats ``estimator-partial`` as estimator-tier
    (not heuristic) so STRICT semantics still classify a workflow with
    partial-resolution as ``low_no_data`` only if other rows are heuristic.
    """
    # --- Tier 1: trace --------------------------------------------------------
    if trace is not None and node_id is not None:
        token_count = _from_trace(trace, node_id)
        if token_count is not None:
            return token_count, "trace"

    # --- Tier 2: memo cache ---------------------------------------------------
    # ``ctx`` carries the authoritative memo cache; an explicitly-passed
    # ``memo_cache`` is honored ONLY on the ctx-less legacy/test path. Collapsing
    # to one source here keeps the tier gate and the read consistent and removes
    # the silent-divergence footgun: when ``ctx`` is present it always wins, so a
    # ``memo_cache`` that differs from ``ctx.memo_cache`` can never be silently read.
    effective_memo = ctx.memo_cache if ctx is not None else memo_cache
    if effective_memo is not None and node_id is not None:
        token_count = _from_memo(effective_memo, node_id, workflow_path=workflow_path, ctx=ctx)
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
            return token_count, "estimator-partial" if has_unresolved_refs else "estimator"

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
    ctx: AnalysisContext | None = None,
) -> tuple[int | None, str]:
    """Return ``(cacheable_tokens, source)`` using highest-fidelity available data.

    Sources: ``"trace"``, ``"memo"``, ``"parameters"``, ``"unavailable"``.

    Tier order:

    - Tier 1 (``"trace"``): declared subset + trace event with
      ``cache_creation+cache_read > 0``. Returns the per-call trace value; the
      trace aggregator divides token fields at the producer boundary.
    - Tier 2 (``"memo"`` / ``"parameters"``): all chunks resolve to real
      values via memo or workflow parameters. Returns the per-call chunk sum.
    - Tier 3 (``"unavailable"``): nothing else is honestly measurable.
      Returns ``(None, "unavailable")``.

    Tier 1 fall-through: when declared subset has trace_event with
    ``cache_creation+cache_read == 0`` (cache declared but didn't fire —
    sub-threshold etc.), fall through to Tier 2 to compute "what was
    attempted." If Tier 2 also fails, returns unavailable.

    Honest unmeasurable contract: the function never fabricates token
    counts when chunks can't be resolved. Downstream
    ``cache.below-min-predicted`` warnings naturally suppress (the detector
    requires ``estimated_tokens > 0``). The runtime-tier observed
    warning in ``LLMNode.post()`` catches the real failure case after
    first run when the provider exposes cache telemetry (the runtime
    path gates on ``llm_usage["has_cache_telemetry"]``; providers that
    omit cache fields entirely — custom proxies, brand-new releases — do
    not trigger the observed-tier warning either).
    """
    # Tier 1: trace ground truth — only meaningful for declared cache that fired.
    if declared_subset and trace_event is not None:
        creation = int(trace_event.get("cache_creation_input_tokens") or 0)
        read = int(trace_event.get("cache_read_input_tokens") or 0)
        if creation + read > 0:
            return (creation + read, "trace")
        # Fall through: declared but didn't fire. Tier 2/3 computes
        # "what was attempted" so cache.below-min-predicted fires correctly.

    # Tier 2: memo-resolved chunk tokenization (declared OR candidate).
    # When ``ctx`` is supplied, parameters fallback fires for workflow-input
    # refs (Track B). Without ctx, fall back to memo-only resolution for
    # backward compatibility with legacy direct callers.
    # ``ctx`` is the authoritative source; ``memo_cache`` is honored only on the
    # ctx-less path (see ``estimate_tokens`` for the footgun rationale).
    effective_memo = ctx.memo_cache if ctx is not None else memo_cache
    chunks = declared_subset or candidate_subset
    if chunks and model and (ctx is not None or effective_memo is not None):
        total = _sum_resolved_chunk_tokens(
            chunks,
            model,
            effective_memo,
            workflow_path,
            ctx=ctx,
        )
        if total is not None:
            # When the source is exclusively parameters, label accordingly so
            # agents can see WHICH tier produced the projection. Detection is
            # cheap when ``ctx`` is provided — re-resolve via parameters only.
            label = _classify_resolution_source(chunks, ctx)
            return (total, label)
        # Fall through to Tier 3 (unavailable) — Option C honest unmeasurable.
        # Both declared and candidate subsets share this fall-through.

    # Tier 3: nothing to project — honest unavailable.
    return (None, "unavailable")


def _sum_resolved_chunk_tokens(
    chunks: list[str],
    model: str,
    memo_cache: _MemoCacheLike | None,
    workflow_path: str | None,
    *,
    ctx: AnalysisContext | None = None,
) -> int | None:
    """Sum chunk token counts via parameters (preferred) then memo.

    None if any chunk resolves to no value (Tier 4 unmeasurable propagates).
    """
    total = 0
    for ref in chunks:
        tokens = _estimate_ref_tokens(ref, model=model, memo_cache=memo_cache, workflow_path=workflow_path, ctx=ctx)
        if tokens is None:
            return None
        total += tokens
    return total


def _classify_resolution_source(chunks: list[str], ctx: AnalysisContext | None) -> str:
    """Return ``"parameters"`` when every chunk resolves via parameters; else ``"memo"``.

    Matches the agent-facing tier label set documented in the module
    docstring. Greenfield + ``--inputs`` lights up the parameters tier so
    ``cacheable_data_source`` reads ``"parameters"`` instead of an
    unhelpful generic label.
    """
    if ctx is None:
        return "memo"
    declared_inputs = ctx.workflow_ir.get("inputs") if isinstance(ctx.workflow_ir, dict) else None
    if not isinstance(declared_inputs, dict):
        return "memo"
    # Lazy-import (matches existing pattern in this module).
    from pflow.runtime.template_resolver import TemplateResolver

    all_from_params = True
    for ref in chunks:
        root = TemplateResolver.extract_root_node_id(ref)
        if not root or root not in declared_inputs or root not in ctx.parameters:
            all_from_params = False
            break
    return "parameters" if all_from_params else "memo"


def estimate_output_tokens(
    *,
    trace: dict[str, Any] | None = None,
    memo_cache: _MemoCacheLike | None = None,
    node_id: str | None = None,
    workflow_path: str | None = None,
    ctx: AnalysisContext | None = None,
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

    # ctx wins when present; memo_cache is the ctx-less fallback (see estimate_tokens).
    effective_memo = ctx.memo_cache if ctx is not None else memo_cache
    if effective_memo is not None and node_id is not None:
        token_count = _output_from_memo(effective_memo, node_id, workflow_path=workflow_path, ctx=ctx)
        if token_count is not None:
            return token_count, "memo"

    return None, "unavailable"


def tokenize_prompt_region(
    region: str,
    *,
    model: str,
    ctx: AnalysisContext,
) -> int | None:
    """Tokenize a prompt slice after resolving ``${...}`` refs against ``ctx``.

    This is the cacheable-region sibling of
    ``analyze._resolve_prompt_for_tokenization``. That helper returns partial
    text plus a confidence flag because ``input_tokens_estimated`` is always
    populated by contract. This helper returns ``None`` when a cacheable region
    cannot be fully resolved, so callers render ``?`` / ``unmeasurable`` rather
    than counting the literal ``${...}`` bytes as if they were real prompt text.

    Contract:
    - Empty region returns 0.
    - Regions with no template refs tokenize directly.
    - Fully resolved refs tokenize the resolved bytes.
    - Any unresolved ref after substitution returns None atomically.
    - Single-ref non-string values serialize deterministically before counting.
    """
    return _tokenize_prompt_region_with_resolver(
        region,
        model=model,
        ctx=ctx,
        use_projection_resolver=False,
    )


def tokenize_prompt_region_for_projection(
    region: str,
    *,
    model: str,
    ctx: AnalysisContext,
) -> int | None:
    """Projection variant that can resolve refs from trace node outputs."""
    return _tokenize_prompt_region_with_resolver(
        region,
        model=model,
        ctx=ctx,
        use_projection_resolver=True,
    )


def tokenize_prompt_region_lower_bound(
    region: str,
    *,
    model: str,
    ctx: AnalysisContext,
) -> tuple[int, tuple[str, ...]]:
    """Tokenize a prompt slice as an advisory lower bound.

    Unlike :func:`tokenize_prompt_region`, this helper does not require atomic
    full-template resolution. It resolves what the analyzer can know, strips
    any remaining ``${...}`` placeholders, and returns both the measurable
    token count and the unresolved refs that must be verified against a real
    run before treating the recommendation as confident.

    Contract:
    - Empty region returns ``(0, ())``.
    - Regions with no template refs tokenize directly.
    - Fully resolved refs tokenize the resolved bytes and return no refs.
    - Partial resolution strips unresolved placeholders before tokenization.
    - Resolution exceptions return ``(0, raw_refs)`` conservatively.
    - Single-ref non-string values serialize deterministically before counting.
    """
    return _tokenize_prompt_region_lower_bound_with_resolver(
        region,
        model=model,
        ctx=ctx,
        use_projection_resolver=False,
    )


def tokenize_prompt_region_lower_bound_for_projection(
    region: str,
    *,
    model: str,
    ctx: AnalysisContext,
) -> tuple[int, tuple[str, ...]]:
    """Lower-bound projection variant that can resolve refs from trace outputs."""
    return _tokenize_prompt_region_lower_bound_with_resolver(
        region,
        model=model,
        ctx=ctx,
        use_projection_resolver=True,
    )


def _tokenize_prompt_region_with_resolver(
    region: str,
    *,
    model: str,
    ctx: AnalysisContext,
    use_projection_resolver: bool,
) -> int | None:
    if not region:
        return 0
    if "${" not in region:
        return estimate_tokens(model, region)[0]

    from pflow.core.prompt_cache import deterministic_serialize
    from pflow.runtime.template_resolver import TemplateResolver

    refs = extract_unique_refs(region)
    if not refs:
        return estimate_tokens(model, region)[0]

    shared = build_shared_store_for_refs(refs, ctx, use_projection_resolver=use_projection_resolver)
    try:
        resolved = TemplateResolver.resolve_template(region, shared)
    except (AttributeError, KeyError, TypeError, ValueError):
        logger.debug("tokenize_prompt_region: resolve_template raised", exc_info=True)
        return None

    if not isinstance(resolved, str):
        resolved = deterministic_serialize(resolved)
    if TemplateResolver.TEMPLATE_PATTERN.search(resolved):
        return None
    return estimate_tokens(model, resolved)[0]


def _tokenize_prompt_region_lower_bound_with_resolver(
    region: str,
    *,
    model: str,
    ctx: AnalysisContext,
    use_projection_resolver: bool,
) -> tuple[int, tuple[str, ...]]:
    if not region:
        return 0, ()
    if "${" not in region:
        return estimate_tokens(model, region)[0], ()

    from pflow.core.prompt_cache import deterministic_serialize
    from pflow.runtime.template_resolver import TemplateResolver

    refs = extract_unique_refs(region)
    if not refs:
        return estimate_tokens(model, region)[0], ()

    shared = build_shared_store_for_refs(refs, ctx, use_projection_resolver=use_projection_resolver)
    try:
        resolved = TemplateResolver.resolve_template(region, shared)
    except (AttributeError, KeyError, TypeError, ValueError):
        logger.debug("tokenize_prompt_region_lower_bound: resolve_template raised", exc_info=True)
        return 0, tuple(refs)

    if not isinstance(resolved, str):
        resolved = deterministic_serialize(resolved)

    unresolved = tuple(match.group(1) for match in TemplateResolver.TEMPLATE_PATTERN.finditer(resolved))
    if not unresolved:
        return estimate_tokens(model, resolved)[0], ()

    stripped = TemplateResolver.TEMPLATE_PATTERN.sub("", resolved)
    return estimate_tokens(model, stripped)[0], unresolved


def extract_unique_refs(prompt: str) -> list[str]:
    """Walk ``prompt`` for unique template refs, deduped in encounter order."""
    from pflow.runtime.template_resolver import TemplateResolver

    refs: list[str] = []
    for match in TemplateResolver.TEMPLATE_PATTERN.finditer(prompt):
        for operand in TemplateResolver.split_coalesce_operands(match.group(1)):
            if operand and operand not in refs:
                refs.append(operand)
    return refs


def build_shared_store_for_refs(
    refs: list[str],
    ctx: AnalysisContext,
    *,
    use_projection_resolver: bool = False,
) -> dict[str, Any]:
    """Build a synthetic shared store keyed by root node ids for ``refs``."""
    from pflow.runtime.template_resolver import TemplateResolver

    shared: dict[str, Any] = {}
    for ref in refs:
        root = TemplateResolver.extract_root_node_id(ref)
        if not root or root in shared:
            continue
        # Resolve the root, not the full path. TemplateResolver performs
        # dotted/indexed traversal against the root value, while AnalysisContext
        # preserves the parameters-vs-memo resolution policy.
        resolver = ctx.resolve_ref_value_for_projection if use_projection_resolver else ctx.resolve_ref_value
        value = resolver(root)
        if value is not None:
            shared[root] = value
    return shared


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
    """Return the first top-level ``llm_call`` dict for ``node_id``."""
    from pflow.core.trace_tree import TraceTree

    try:
        event = TraceTree.from_dict(trace).event_for(node_id, requires_llm_call=True)
    except ValueError:
        return None
    llm_call = event.get("llm_call") if event is not None else None
    return llm_call if isinstance(llm_call, dict) else None


def _llm_call_field_from_trace(trace: dict[str, Any], node_id: str, field: str) -> int | None:
    """Read an integer field from the first matching ``llm_call`` event."""
    llm_call = _find_llm_event(trace, node_id)
    if llm_call is None:
        return None
    value = llm_call.get(field)
    return value if isinstance(value, int) else None


def _from_memo(
    memo_cache: _MemoCacheLike,
    node_id: str,
    *,
    workflow_path: str | None,
    ctx: AnalysisContext | None,
) -> int | None:
    """Pull ``llm_usage.input_tokens`` from the latest memoized output."""
    return _llm_usage_field_from_memo(
        memo_cache,
        node_id,
        workflow_path=workflow_path,
        field="input_tokens",
        ctx=ctx,
    )


def _output_from_memo(
    memo_cache: _MemoCacheLike,
    node_id: str,
    *,
    workflow_path: str | None,
    ctx: AnalysisContext | None,
) -> int | None:
    """Pull ``llm_usage.output_tokens`` from the latest memoized output."""
    return _llm_usage_field_from_memo(
        memo_cache,
        node_id,
        workflow_path=workflow_path,
        field="output_tokens",
        ctx=ctx,
    )


def _llm_usage_field_from_memo(
    memo_cache: _MemoCacheLike,
    node_id: str,
    *,
    workflow_path: str | None,
    field: str,
    ctx: AnalysisContext | None,
) -> int | None:
    """Read an integer field from the latest memoized output's ``llm_usage`` dict."""
    if ctx is not None:
        # ctx is authoritative: read via ctx.memo_cache (freshness-checked). The
        # ``memo_cache`` param is consulted only on the ctx-less branch below.
        try:
            latest = ctx.latest_memo_for_node(node_id, workflow_path=workflow_path)
        except Exception:
            logger.debug("memo cache freshness-aware lookup failed for %s", node_id, exc_info=True)
            return None
        output = latest[0] if latest is not None else None
    else:
        # ctx-less fallback: no freshness check possible without ctx.
        # Read the latest memo entry directly with the isinstance-dict guard.
        try:
            result = memo_cache.get_latest_for_node(node_id, workflow_path=workflow_path)
        except Exception:
            logger.debug("memo_cache.get_latest_for_node raised", exc_info=True)
            return None
        output = result[0] if (result is not None and isinstance(result[0], dict)) else None
    if output is None:
        return None
    llm_usage = output.get("llm_usage")
    if not isinstance(llm_usage, dict):
        return None
    value = llm_usage.get(field)
    if isinstance(value, int):
        return value
    return None


def _from_estimator(model: str, text: str) -> int:
    """Lazy-import LiteLLM and call its model-aware tokenizer.

    Routes through pflow's runtime-policy seam so the deterministic
    offline pricing-map default is applied.
    """
    from pflow.core.litellm_runtime import import_litellm

    litellm = import_litellm()
    return int(litellm.token_counter(model=model, text=text))


def _heuristic(text: str | None) -> int:
    """Char-count heuristic — last-resort fallback only."""
    if not text:
        return 0
    return len(text) // 4


# ---------------------------------------------------------------------------
# Per-reference value tokenization (Tier 2 primitive for ``estimate_cacheable_tokens``)
# ---------------------------------------------------------------------------


def _estimate_ref_tokens(
    ref: str,
    *,
    model: str,
    memo_cache: Any,
    workflow_path: str | None,
    ctx: AnalysisContext | None = None,
) -> int | None:
    """Tokenize a template reference's resolved value.

    When ``ctx`` is supplied, resolution honors the input-vs-node-output
    asymmetry from :class:`AnalysisContext.resolve_ref_value` (parameters
    win for workflow-input refs; memo only for node-output refs). Without
    ``ctx``, falls back to the legacy memo-only path for backward
    compatibility with existing test monkeypatch sites.

    Returns:
        - Real token count when a value is available (parameters or memo).
        - ``None`` when no value resolved — callers MUST distinguish
          ``None`` from a small int (per Option C — honest unmeasurable).
    """
    value = _latest_value_for_ref(ref, memo_cache=memo_cache, workflow_path=workflow_path, ctx=ctx)
    if value is not None:
        # Lazy-import to avoid heavy ``prompt_cache`` import at module load.
        from pflow.core.prompt_cache import deterministic_serialize

        return estimate_tokens(model, deterministic_serialize(value))[0]
    return None


def _latest_value_for_ref(
    ref: str,
    *,
    memo_cache: Any,
    workflow_path: str | None,
    ctx: AnalysisContext | None = None,
) -> Any:
    """Resolve ``ref`` to its latest known value, or None if unavailable.

    When ``ctx`` is provided, delegates to :meth:`AnalysisContext.resolve_ref_value`
    (parameters fallback + empty-value handling). Without ctx, uses the
    legacy memo-only resolution.
    """
    if ctx is not None:
        # ctx is authoritative (parameters + freshness-checked memo via
        # ctx.memo_cache). The ``memo_cache`` param is used only when ctx is None.
        return ctx.resolve_ref_value(ref)

    if memo_cache is None:
        return None
    # Lazy-import keeps token_estimation.py layer-clean (mirrors litellm pattern).
    from pflow.runtime.template_resolver import TemplateResolver

    root = TemplateResolver.extract_root_node_id(ref)
    # ctx=None branch: no freshness check possible without ctx.
    # Read the latest memo entry directly; preserve isinstance-dict guard.
    try:
        result = memo_cache.get_latest_for_node(root, workflow_path=workflow_path)
    except Exception:
        logger.debug("memo_cache.get_latest_for_node raised", exc_info=True)
        return None
    output = result[0] if (result is not None and isinstance(result[0], dict)) else None
    if output is None:
        return None
    resolved = TemplateResolver.resolve_template(f"${{{ref}}}", {root: output})
    if isinstance(resolved, str) and resolved == f"${{{ref}}}":
        return None
    return resolved


__all__ = [
    "build_shared_store_for_refs",
    "estimate_cacheable_tokens",
    "estimate_output_tokens",
    "estimate_tokens",
    "extract_unique_refs",
    "tokenize_prompt_region",
    "tokenize_prompt_region_for_projection",
    "tokenize_prompt_region_lower_bound",
    "tokenize_prompt_region_lower_bound_for_projection",
]
