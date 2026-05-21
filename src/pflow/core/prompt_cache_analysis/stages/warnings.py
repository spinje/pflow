"""Per-node warning visitors for prompt-cache analysis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pflow.core.diagnostic import Diagnostic
from pflow.core.llm_capabilities import get_min_cache_tokens
from pflow.core.prompt_refs import classify_prompt_refs, first_per_item_position

from .. import cost_estimation
from ..below_min_tokens_detector import (
    BatchPrewarmBelowMinEvidence,
    BelowMinTokensEvidence,
    detect_batch_prewarm_below_min,
    is_below_min_cache,
)
from ..below_min_tokens_detector import (
    detect as detect_below_min_tokens,
)
from ..context import AnalysisContext, template_resolver
from ..token_estimation import (
    tokenize_prompt_region,
    tokenize_prompt_region_for_projection,
    tokenize_prompt_region_lower_bound_for_projection,
)
from ..types import PerCallRow, _safe_pct, invocation_count_for
from ..warning_catalog import make_diagnostic
from .row_builder import (
    _find_batch_static_tail_after_dynamic,
    _node_inputs,
    _static_excerpt,
)
from .suggestions import _estimate_token_savings_usd


def _per_node_warnings(
    node: dict[str, Any],
    row: PerCallRow,
    *,
    declared_chunks: list[str],
    nodes_by_id: dict[str, dict[str, Any]],
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Emit analytical-tier warnings for one LLM node.

    Full-path matching is load-bearing: cache chunk identifiers are
    ``creative-direction.response`` rather than root ids.

    ``nodes_by_id`` is the workflow-wide node lookup (id → node dict). Detectors
    that need to inspect upstream node types (e.g. ``cache.opaque-prompt``)
    consume it; detectors that only inspect the focal node ignore it.
    """
    diagnostics: list[Diagnostic] = []
    node_id = row.node_path

    if row.declared_prompt_cache:
        declared_component = next(
            (
                component
                for component in row.cache_configured.components
                if component.data_source in {"declared_chunks", "trace"}
            ),
            None,
        )
        finding = detect_below_min_tokens(
            BelowMinTokensEvidence(
                node_id=node_id,
                model=row.model,
                declared_prompt_cache=list(row.declared_prompt_cache),
                estimated_tokens=declared_component.tokens_estimated if declared_component else None,
                estimated_data_source=declared_component.data_source if declared_component else "unavailable",
            )
        )
        if finding is not None:
            diagnostics.append(
                make_diagnostic(
                    "cache.below-min-predicted",
                    node_id=finding.node_id,
                    affected_workflow=row.workflow_path,
                    model=finding.model,
                    min_tokens=finding.min_tokens,
                    cacheable_tokens=finding.cacheable_tokens,
                    provider_note=finding.provider_note,
                )
            )

    diagnostics.extend(_batch_prewarm_recommendations(node, row, ctx=ctx))
    diagnostics.extend(_dynamic_before_static_warnings(node, row, declared_chunks=declared_chunks, ctx=ctx))
    diagnostics.extend(_opaque_prompt_warnings(node, row, nodes_by_id=nodes_by_id))

    # Prewarm boundary classification MUST match the runtime gate at
    # ``nodes/llm/llm.py`` so analyzer and runtime agree on what counts as
    # batch-scoped, including refs indirected through ``params.inputs``.
    #
    # Two mutually-exclusive findings fire on the position of the first
    # per-item ref:
    #   * ``cache.prewarm-no-prefix`` — first == 0 (no static bytes before
    #     the per-item ref; nothing to cache).
    #   * ``cache.batch-prewarm-below-min`` — first > 0 but the bytes before
    #     it tokenize below the provider's minimum (auto batch-prefix marker
    #     will silently no-op at the provider). Gated on
    prewarm = node.get("prewarm")
    batch = node.get("batch")
    if prewarm is True and isinstance(batch, dict):
        alias = str(batch.get("as", "item"))
        prompt = node.get("params", {}).get("prompt", "") or ""
        # Per-call _strip_below_min_cache_markers is authoritative for combined channels.
        has_declared_cache = bool(node.get("prompt_cache"))
        if isinstance(prompt, str) and not has_declared_cache:
            node_inputs = _node_inputs(node)
            first = first_per_item_position(prompt, alias, node_inputs)
            if first == 0:
                diagnostics.append(
                    make_diagnostic(
                        "cache.prewarm-no-prefix",
                        node_id=node_id,
                        affected_workflow=row.workflow_path,
                        batch_alias=alias,
                        first_dynamic_position=0,
                    )
                )
            elif first is not None and first > 0:
                # Unresolved refs in the static prefix make below-min unprovable;
                # skip the static-analysis emit but fall through so the trace-driven
                # conditional-warmup detector below can still run.
                prefix_tokens = tokenize_prompt_region_for_projection(prompt[:first], model=row.model, ctx=ctx)
                if prefix_tokens is not None:
                    prewarm_diag = _emit_batch_prewarm_below_min(
                        node_id=node_id,
                        model=row.model,
                        prefix_tokens=prefix_tokens,
                        batch_alias=alias,
                        workflow_path=row.workflow_path,
                    )
                    if prewarm_diag is not None:
                        diagnostics.append(prewarm_diag)

        below_min_count = sum(
            1 for call in row.provider_trace_llm_calls if call.get("prewarm_disabled_reason") == "below_min"
        )
        total_count = len(row.provider_trace_llm_calls)
        if below_min_count >= 1 and below_min_count < total_count and total_count >= 2:
            diagnostics.append(
                make_diagnostic(
                    "cache.conditional-warmup-recommended",
                    node_id=node_id,
                    affected_workflow=row.workflow_path,
                    model=row.model,
                    below_min_count=below_min_count,
                    total_count=total_count,
                    min_tokens=get_min_cache_tokens(row.model),
                )
            )

    return diagnostics


def _emit_batch_prewarm_below_min(
    *,
    node_id: str,
    model: str,
    prefix_tokens: int,
    batch_alias: str,
    workflow_path: str | None,
) -> Diagnostic | None:
    """Shared producer for ``cache.batch-prewarm-below-min``.

    Routes three call sites through one helper so the convergence between
    per-call row UX and Recommended-Actions UX stays in lockstep:

    * ``_per_node_warnings``: declared ``prewarm: true`` with a measured
      static prefix below the provider minimum (original site).
    * ``_confident_batch_prewarm_recommendation``: undeclared prewarm where
      the analyzer has a measured prefix that is below min (F#4 — silenced
      previously by an early ``return []``).
    * ``_batch_prewarm_recommendations`` lower-bound branch: undeclared
      prewarm with unresolved refs; even the lower-bound measurable prefix
      is below min (F#4 — same silenced shape).

    Predicate stays ``is_below_min_cache`` via the detector — honest
    unmeasurable for empty/unknown model, matching Bundle 5 Option B scope.
    Returns ``None`` when the detector decides no finding applies (e.g.
    threshold met or unknown model); callers append only when non-None.

    ``workflow_path`` is typed ``str | None`` to mirror ``PerCallRow``'s
    field nullability; the catalog's ``_ensure_workflow_scope`` will reject
    None at construction (raising ``KeyError``), which is the desired
    contract — analyzer rows without a workflow_path shouldn't surface
    workflow-scoped diagnostics.
    """
    finding = detect_batch_prewarm_below_min(
        BatchPrewarmBelowMinEvidence(
            node_id=node_id,
            model=model,
            prefix_tokens=prefix_tokens,
            batch_alias=batch_alias,
        )
    )
    if finding is None:
        return None
    return make_diagnostic(
        "cache.batch-prewarm-below-min",
        node_id=finding.node_id,
        affected_workflow=workflow_path,
        model=finding.model,
        prefix_tokens=finding.prefix_tokens,
        min_tokens=finding.min_tokens,
        batch_alias=finding.batch_alias,
        provider_note=finding.provider_note,
    )


def _batch_prewarm_recommendations(
    node: dict[str, Any],
    row: PerCallRow,
    *,
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Emit ``cache.batch-prewarm-recommended`` per DD#33.

    ``prewarm: false`` is an explicit opt-out and suppresses this warning; only
    absence of the field means the author has not made a decision.

    When the analyzer can prove the would-be prefix is below the provider
    minimum (measurable or lower-bound), this function instead emits
    ``cache.batch-prewarm-below-min`` so the Recommended-Actions surface
    matches the per-call row's structural blocker (F#4 follow-ups-2).
    """
    batch = node.get("batch")
    if "prewarm" in node or not isinstance(batch, dict):
        return []
    affected_calls = row.batch_size_estimated or row.observed_call_count
    if affected_calls < 2:
        return []
    prompt = node.get("params", {}).get("prompt", "") or ""
    if not isinstance(prompt, str):
        return []

    alias = str(batch.get("as", "item"))
    uses_existing_prefix_evidence = False
    prefix_tokens: int | None = None
    dynamic_tokens: int | None = None
    # Reuse row-level batch-prefix evidence when available. Row token fields
    # are per-call by contract; cohort math happens only at explicit consumers.
    if row.observed_call_count >= 2 and row.cacheable_data_source == "batch_prefix" and row.cacheable_tokens_estimated:
        uses_existing_prefix_evidence = True
        prefix_tokens = row.cacheable_tokens_estimated
        dynamic_tokens = max(0, row.input_tokens_estimated - prefix_tokens)
    else:
        node_inputs = _node_inputs(node)
        first = first_per_item_position(prompt, alias, node_inputs)
        if first is None or first == 0:
            return []
        prefix_tokens = tokenize_prompt_region_for_projection(prompt[:first], model=row.model, ctx=ctx)
        dynamic_tokens = tokenize_prompt_region_for_projection(prompt[first:], model=row.model, ctx=ctx)
    if prefix_tokens is not None and dynamic_tokens is not None:
        return _confident_batch_prewarm_recommendation(
            row=row,
            affected_calls=affected_calls,
            prefix_tokens=prefix_tokens,
            dynamic_tokens=dynamic_tokens,
            alias=alias,
        )

    if prefix_tokens is None and not uses_existing_prefix_evidence:
        measurable_tokens, unresolved_refs = tokenize_prompt_region_lower_bound_for_projection(
            prompt[:first],
            model=row.model,
            ctx=ctx,
        )
        # F#4 (follow-ups-2): below-min on the lower-bound branch must surface
        # at the Recommended-Actions block so the agent sees the structural
        # blocker, not just the per-call row. Same convergence rationale as
        # the confident branch below.
        if is_below_min_cache(row.model, measurable_tokens):
            below_min_diag = _emit_batch_prewarm_below_min(
                node_id=row.node_path,
                model=row.model,
                prefix_tokens=measurable_tokens,
                batch_alias=alias,
                workflow_path=row.workflow_path,
            )
            return [below_min_diag] if below_min_diag is not None else []
        if not unresolved_refs:
            # No refs to verify with --report AND measurable cleared min — but
            # if there were no refs the confident branch above would have
            # taken this case. Defensive: nothing actionable to recommend.
            return []
        return [
            make_diagnostic(
                "cache.batch-prewarm-lower-bound-recommended",
                node_id=row.node_path,
                affected_workflow=row.workflow_path,
                measurable_tokens=measurable_tokens,
                batch_alias=alias,
                unresolved_refs=unresolved_refs,
                savings_lower_bound_usd=_estimate_token_savings_usd(
                    row.model,
                    measurable_tokens,
                    affected_calls - 1,
                ),
                batch_size=affected_calls,
            )
        ]

    return []


def _confident_batch_prewarm_recommendation(
    *,
    row: PerCallRow,
    affected_calls: int,
    prefix_tokens: int,
    dynamic_tokens: int,
    alias: str,
) -> list[Diagnostic]:
    # F#4 (follow-ups-2): converge with the per-call row UX. The row already
    # renders ``add prewarm; below provider min`` via
    # ``_prewarm_opportunity_projection_component`` (blocked_reason=
    # ``below_provider_min``). The Recommended-Actions block must also
    # surface the structural blocker so the agent can act on it without
    # cross-referencing the row table — emit ``cache.batch-prewarm-below-min``
    # in place of the previous silent ``return []``.
    if is_below_min_cache(row.model, prefix_tokens):
        below_min_diag = _emit_batch_prewarm_below_min(
            node_id=row.node_path,
            model=row.model,
            prefix_tokens=prefix_tokens,
            batch_alias=alias,
            workflow_path=row.workflow_path,
        )
        return [below_min_diag] if below_min_diag is not None else []

    savings_ratio = ((affected_calls - 1) * 1.15 * prefix_tokens) / (
        affected_calls * ((1.25 * prefix_tokens) + dynamic_tokens)
    )
    savings_pct = round(100 * savings_ratio)
    if savings_pct < 5:
        return []

    return [
        make_diagnostic(
            "cache.batch-prewarm-recommended",
            node_id=row.node_path,
            affected_workflow=row.workflow_path,
            batch_size=affected_calls,
            prefix_tokens_estimated=prefix_tokens,
            prefix_tokens_cohort_estimated=prefix_tokens * affected_calls,
            savings_pct=savings_pct,
            savings_usd=_estimate_token_savings_usd(row.model, prefix_tokens, affected_calls - 1),
        )
    ]


def _dynamic_before_static_warnings(
    node: dict[str, Any],
    row: PerCallRow,
    *,
    declared_chunks: list[str],
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Detect a dynamic template reference before a large stable suffix."""
    prompt = node.get("params", {}).get("prompt", "") or ""
    if not isinstance(prompt, str):
        return []

    batch = node.get("batch")
    if not row.declared_prompt_cache and isinstance(batch, dict):
        affected_calls = row.batch_size_estimated or row.observed_call_count
        if affected_calls < 2:
            return []
        alias = str(batch.get("as", "item"))
        node_inputs = _node_inputs(node)
        finding = _find_batch_static_tail_after_dynamic(
            prompt=prompt,
            model=row.model,
            batch_alias=alias,
            node_inputs=node_inputs,
            ctx=ctx,
        )
        if finding is None:
            return []
        return [
            make_diagnostic(
                "cache.dynamic-before-static",
                node_id=row.node_path,
                affected_workflow=row.workflow_path,
                dynamic_ref=finding.dynamic_ref,
                dynamic_line=finding.dynamic_line,
                cacheable_tokens=finding.stable_tail_tokens,
                affected_calls=affected_calls,
                savings_usd=_estimate_token_savings_usd(row.model, finding.stable_tail_tokens, affected_calls),
                projected_ratio_pct=(
                    _safe_pct(
                        finding.stable_tail_tokens,
                        finding.stable_tail_tokens + finding.tokens_before_dynamic,
                    )
                    if finding.tokens_before_dynamic is not None
                    else None
                ),
                detection_mode="batch_static_tail",
                min_cache_tokens=get_min_cache_tokens(row.model),
                model=row.model,
                tokens_before_dynamic=finding.tokens_before_dynamic,
                template_refs_after_dynamic=finding.template_refs_after_dynamic,
                static_tail_excerpt=finding.static_tail_excerpt,
            )
        ]

    if not row.declared_prompt_cache or not declared_chunks:
        return []

    declared = set(declared_chunks)
    node_inputs = _node_inputs(node)
    refs = classify_prompt_refs(prompt, batch_alias=None, node_inputs=node_inputs)
    for index, ref in enumerate(refs):
        if any(path in declared for path in ref.operand_paths):
            continue

        cacheable_tokens = tokenize_prompt_region(prompt[ref.end :], model=row.model, ctx=ctx)
        if cacheable_tokens is None:
            continue
        if is_below_min_cache(row.model, cacheable_tokens):
            break

        affected_calls = invocation_count_for(row)
        tokens_before = tokenize_prompt_region(prompt[: ref.position], model=row.model, ctx=ctx)
        return [
            make_diagnostic(
                "cache.dynamic-before-static",
                node_id=row.node_path,
                affected_workflow=row.workflow_path,
                dynamic_ref=ref.raw_expr,
                dynamic_line=1 + prompt[: ref.position].count("\n"),
                cacheable_tokens=cacheable_tokens,
                affected_calls=affected_calls,
                savings_usd=_estimate_token_savings_usd(row.model, cacheable_tokens, affected_calls),
                projected_ratio_pct=(
                    _safe_pct(cacheable_tokens, cacheable_tokens + tokens_before) if tokens_before is not None else None
                ),
                detection_mode="declared_cache",
                min_cache_tokens=get_min_cache_tokens(row.model),
                model=row.model,
                tokens_before_dynamic=tokens_before,
                template_refs_after_dynamic=len(refs) - index - 1,
                static_tail_excerpt=_static_excerpt(prompt[ref.end :]),
            )
        ]
    return []


def _opaque_prompt_warnings(
    node: dict[str, Any],
    row: PerCallRow,
    *,
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    """Detect LLM nodes whose prompt is a single var-ref to a code-node output.

    Static walkers (``cache.dynamic-before-static``, ``cache.batch-prewarm-recommended``,
    ``cache.shared-context-undeclared``) read ``node.params.prompt`` as a literal
    template. When the prompt is just ``${X}`` and X resolves through a
    ``type: code`` node, those walkers see one ref and find nothing — even when
    the assembled prompt has substantial cache potential. This detector points
    the agent at the refactor.

    Two patterns trigger:
      - **Direct**: ``prompt: ${some_code.result.field}``.
      - **Through batch alias**: ``prompt: ${item.X}`` AND
        ``batch.items: ${some_code.result}``.

    Coalesce expressions (``${a ?? b}``) are skipped — they have multiple paths
    and the "opaque" framing doesn't fit cleanly.
    """
    prompt = node.get("params", {}).get("prompt", "")
    if not isinstance(prompt, str):
        return []
    stripped = prompt.strip()
    template_resolver_cls = template_resolver()
    if not template_resolver_cls.is_simple_template(stripped):
        return []

    inner = stripped[2:-1]
    if template_resolver_cls.is_coalesce_expression(inner):
        return []
    root = template_resolver_cls.extract_root_node_id(inner)

    upstream_node = nodes_by_id.get(root)
    if upstream_node is None:
        # Try one level of indirection through the batch alias.
        upstream_node = _resolve_through_batch_alias(node, root, nodes_by_id)

    if upstream_node is None or upstream_node.get("type") != "code":
        return []

    return [
        make_diagnostic(
            "cache.opaque-prompt",
            node_id=row.node_path,
            affected_workflow=row.workflow_path,
            var_ref=inner,
            upstream_node_id=str(upstream_node.get("id", "?")),
        )
    ]


def _resolve_through_batch_alias(
    node: dict[str, Any],
    root: str,
    nodes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """If ``root`` is the node's batch alias, follow ``batch.items`` to its source node."""
    batch = node.get("batch")
    if not isinstance(batch, dict):
        return None
    alias = str(batch.get("as", "item"))
    if root != alias:
        return None
    items_expr = batch.get("items", "")
    if not isinstance(items_expr, str):
        return None
    items_stripped = items_expr.strip()
    template_resolver_cls = template_resolver()
    if not template_resolver_cls.is_simple_template(items_stripped):
        return None
    items_inner = items_stripped[2:-1]
    if template_resolver_cls.is_coalesce_expression(items_inner):
        return None
    items_root = template_resolver_cls.extract_root_node_id(items_inner)
    return nodes_by_id.get(items_root)


def _enrich_shadow_warnings_with_costs(
    *,
    rows: Sequence[PerCallRow],
    warnings: Sequence[Diagnostic],
    output_tokens_by_node: Mapping[tuple[str | None, str], int | None],
    ttl_by_workflow: Mapping[str | None, str | None],
) -> None:
    """Attach body-only vs with-cache per-call costs to shadow warnings.

    The validator owns the structural finding. Analyzer-tier enrichment adds
    cost evidence only when pricing and output tokens are known; otherwise the
    warning remains a pure structural suggestion.
    """
    rows_by_key = {(row.workflow_path, row.node_path): row for row in rows}
    for diag in warnings:
        _enrich_one_shadow_warning(
            diag=diag,
            rows=rows,
            rows_by_key=rows_by_key,
            output_tokens_by_node=output_tokens_by_node,
            ttl_by_workflow=ttl_by_workflow,
        )


def _enrich_one_shadow_warning(
    *,
    diag: Diagnostic,
    rows: Sequence[PerCallRow],
    rows_by_key: Mapping[tuple[str | None, str], PerCallRow],
    output_tokens_by_node: Mapping[tuple[str | None, str], int | None],
    ttl_by_workflow: Mapping[str | None, str | None],
) -> None:
    if diag.id != "cache.prompt-body-shadows-cache" or diag.context is None:
        return
    context = diag.context
    cache_contains_body_pairs = _cache_contains_body_pairs(context.get("shadowing_pairs"))
    node_id = context.get("node_id") or diag.node_id
    if not cache_contains_body_pairs or not isinstance(node_id, str):
        return
    row = _row_for_shadow_warning(
        rows=rows,
        rows_by_key=rows_by_key,
        affected_workflow=context.get("affected_workflow"),
        node_id=node_id,
    )
    if row is None or not row.model:
        return
    pricing = cost_estimation.get_model_pricing(row.model)
    output_tokens = _output_tokens_for_row(row, output_tokens_by_node)
    shadowed_chunks = _shadowed_chunk_names(cache_contains_body_pairs)
    if pricing is None or output_tokens is None or not shadowed_chunks:
        return

    invocation_count = invocation_count_for(row)
    context["body_only_cost_usd_per_call"] = (
        cost_estimation.row_body_only_cost(row, pricing, output_tokens) / invocation_count
    )
    context["with_cache_cost_usd_per_call"] = (
        cost_estimation.row_first_run_with_cache_cost(
            row,
            pricing,
            output_tokens,
            ttl=_ttl_for_row(row, ttl_by_workflow),
        )
        / invocation_count
    )
    context["shadowed_chunk_names"] = shadowed_chunks


def _ttl_for_row(row: PerCallRow, ttl_by_workflow: Mapping[str | None, str | None]) -> str | None:
    return ttl_by_workflow.get(row.workflow_path)


def _output_tokens_for_row(
    row: PerCallRow,
    output_tokens_by_node: Mapping[tuple[str | None, str], int | None],
) -> int | None:
    return output_tokens_by_node.get((row.workflow_path, row.node_path))


def _cache_contains_body_pairs(raw_pairs: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_pairs, list):
        return []
    return [pair for pair in raw_pairs if isinstance(pair, dict) and pair.get("direction") == "cache_contains_body"]


def _row_for_shadow_warning(
    *,
    rows: Sequence[PerCallRow],
    rows_by_key: Mapping[tuple[str | None, str], PerCallRow],
    affected_workflow: Any,
    node_id: str,
) -> PerCallRow | None:
    workflow_path = affected_workflow if isinstance(affected_workflow, str) else None
    row = rows_by_key.get((workflow_path, node_id))
    if row is not None:
        return row
    return next((candidate for candidate in rows if candidate.node_path == node_id), None)


def _shadowed_chunk_names(pairs: Sequence[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        sorted({
            str(pair["chunk_name"])
            for pair in pairs
            if isinstance(pair.get("chunk_name"), str) and pair.get("chunk_name")
        })
    )
