"""Prompt-cache fragmentation and write-penalty diagnostics."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from pflow.core.diagnostic import Diagnostic
from pflow.core.llm_providers import normalize_model_name

from ..below_min_tokens_detector import is_likely_below_min_cache
from ..context import AnalysisContext
from ..types import PerCallRow
from ..warning_catalog import make_diagnostic
from .suggestions import _extract_cache_ttl, _input_rate, _sum_chunk_tokens


def _detect_cache_fragmentation_by(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    declared_chunks: list[str],
    ctx: AnalysisContext,
    key_fn: Callable[[PerCallRow, dict[str, Any]], str | None],
    warning_id: str,
    representative_model_fn: Callable[[dict[str, Any]], str | None],
    context_builder_fn: Callable[[list[dict[str, Any]], dict[str, float]], dict[str, Any]],
) -> list[Diagnostic]:
    """Emit one workflow-scoped warning for cache-prefix fragmentation.

    This is the shared engine for warnings whose invariant is "shared cache
    chunks are declared across groups that cannot share provider cache prefix
    bytes." Callers supply the grouping key, the representative model used for
    pricing each group, and the warning-specific diagnostic context.
    """
    if not declared_chunks:
        return []

    rows_with_keys = _fragmentation_rows_with_keys(
        workflow_ir=workflow_ir,
        rows_by_node=rows_by_node,
        key_fn=key_fn,
    )
    if not rows_with_keys:
        return []

    groups = _group_rows_by_fragmentation_key(rows_with_keys)
    fragmented_groups = [group for group in groups.values() if _chunks_shared_with_other_group(group, groups.values())]
    if len(fragmented_groups) < 2:
        return []

    sorted_groups = sorted(
        fragmented_groups,
        key=lambda group: (-len(group["rows"]), str(group["key"] or "")),
    )
    shared_chunks = _chunks_shared_across_groups(sorted_groups)
    costs = _compute_fragmentation_costs(
        sorted_groups,
        shared_chunks,
        ttl=_extract_cache_ttl(workflow_ir.get("cache")),
        ctx=ctx,
        representative_model_fn=representative_model_fn,
    )
    if costs is None:
        return []

    participating_groups = [group for group in sorted_groups if str(group["key"] or "") in costs]
    if len(participating_groups) < 2:
        return []

    redundant_groups = participating_groups[1:]
    savings_usd = sum(costs[str(group["key"] or "")] for group in redundant_groups)
    extra_context = context_builder_fn(participating_groups, costs)
    return [
        make_diagnostic(
            warning_id,
            node_id=None,
            shared_chunks=sorted(shared_chunks),
            affected_workflow=ctx.workflow_path,
            savings_usd=savings_usd,
            **extra_context,
        )
    ]


def _fragmentation_rows_with_keys(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    key_fn: Callable[[PerCallRow, dict[str, Any]], str | None],
) -> list[tuple[PerCallRow, str | None]]:
    node_by_id = {str(n.get("id")): n for n in workflow_ir.get("nodes", []) if isinstance(n, dict) and n.get("id")}
    rows_with_keys: list[tuple[PerCallRow, str | None]] = []
    for row in rows_by_node.values():
        if not row.declared_prompt_cache:
            continue
        if not row.model:
            continue
        if row.model_is_heterogeneous or row.did_not_execute_in_trace:
            continue
        node = node_by_id.get(row.node_path)
        if node is None:
            continue
        rows_with_keys.append((row, key_fn(row, node)))
    return rows_with_keys


def _group_rows_by_fragmentation_key(
    rows_with_keys: list[tuple[PerCallRow, str | None]],
) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row, key in rows_with_keys:
        bucket_key = key or ""
        group = groups.setdefault(bucket_key, {"key": key, "rows": [], "chunks": set()})
        group["rows"].append(row)
        group["chunks"].update(str(chunk) for chunk in row.declared_prompt_cache or ())
    return groups


def _detect_model_cache_fragmentation(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    declared_chunks: list[str],
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Emit model-fragmentation and write-penalty diagnostics.

    The fragmentation warning delegates to ``_detect_cache_fragmentation_by``.
    The write-penalty advisory stays here because it is model-specific: one
    exact-model group with one cache-declaring call pays a write premium that
    cannot amortize in the current workflow. Sibling fragmentation detector:
    ``_detect_system_cache_fragmentation``.
    """
    rows = [
        row
        for row in rows_by_node.values()
        if row.declared_prompt_cache
        and row.model
        and not row.model_is_heterogeneous
        and not row.did_not_execute_in_trace
    ]
    node_by_id = {str(n.get("id")): n for n in workflow_ir.get("nodes", []) if isinstance(n, dict) and n.get("id")}
    diagnostics = _detect_cache_fragmentation_by(
        workflow_ir=workflow_ir,
        rows_by_node=rows_by_node,
        declared_chunks=declared_chunks,
        ctx=ctx,
        key_fn=lambda row, node: normalize_model_name(row.model),
        warning_id="cache.heterogeneous-models-fragment-cache",
        representative_model_fn=lambda group: str(group["key"]) if group["key"] else None,
        context_builder_fn=_build_model_fragmentation_context,
    )

    groups = _group_prompt_cache_rows_by_model(rows)
    for group in sorted(groups.values(), key=lambda item: str(item["model"])):
        group_rows = group["rows"]
        if len(group_rows) != 1:
            continue
        row = group_rows[0]
        node = node_by_id.get(row.node_path)
        if isinstance(node, dict) and node.get("prewarm") is True:
            continue
        model = str(group["model"])
        if model.startswith("gemini/"):
            continue
        penalty = _single_call_write_penalty(row, ttl=_extract_cache_ttl(workflow_ir.get("cache")))
        if penalty is None:
            continue
        diagnostics.append(
            make_diagnostic(
                "cache.first-call-write-penalty",
                node_id=row.node_path,
                model=model,
                affected_workflow=ctx.workflow_path,
                savings_usd=penalty,
            )
        )

    return diagnostics


def _detect_system_cache_fragmentation(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    declared_chunks: list[str],
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Emit system-prompt cache-prefix fragmentation diagnostics.

    Provider cache prefixes include the rendered ``system:`` content before the
    first cache marker. LLM nodes that share ``prompt_cache:`` chunks but use
    distinct ``system:`` strings therefore create distinct provider cache
    namespaces even when model and chunks match. Sibling fragmentation detector:
    ``_detect_model_cache_fragmentation``.
    """
    return _detect_cache_fragmentation_by(
        workflow_ir=workflow_ir,
        rows_by_node=rows_by_node,
        declared_chunks=declared_chunks,
        ctx=ctx,
        key_fn=_system_fragmentation_key,
        warning_id="cache.system-prompts-fragment-cache",
        representative_model_fn=_homogeneous_model_for_system_group,
        context_builder_fn=_build_system_fragmentation_context,
    )


def _system_fragmentation_key(_row: PerCallRow, node: dict[str, Any]) -> str | None:
    """Return the LLM node's ``system:`` value for cache-prefix grouping."""
    system_value = node.get("params", {}).get("system")
    if not isinstance(system_value, str) or not system_value:
        return None
    return system_value


def _homogeneous_model_for_system_group(group: dict[str, Any]) -> str | None:
    """Return the group's single model, or None when models are mixed."""
    models: set[str] = {str(row.model) for row in group["rows"] if row.model}
    if len(models) != 1:
        return None
    return next(iter(models))


def _build_model_fragmentation_context(
    participating_groups: list[dict[str, Any]],
    costs: dict[str, float],
) -> dict[str, Any]:
    model_groups = _model_groups_payload(participating_groups, costs)
    return {
        "model_group_count": len(participating_groups),
        "models_csv": ", ".join(str(group["key"]) for group in participating_groups),
        "model_groups": model_groups,
        "model_groups_lines": _format_model_groups_lines(model_groups),
    }


def _build_system_fragmentation_context(
    participating_groups: list[dict[str, Any]],
    costs: dict[str, float],
) -> dict[str, Any]:
    payload = _system_groups_payload(participating_groups, costs)
    node_ids_csv = ", ".join(sorted({row.node_path for group in participating_groups for row in group["rows"]}))
    return {
        "system_group_count": len(participating_groups),
        "system_groups": payload,
        "system_groups_lines": _format_system_groups_lines(payload),
        "node_ids_csv": node_ids_csv,
    }


def _group_prompt_cache_rows_by_model(rows: list[PerCallRow]) -> dict[str, dict[str, Any]]:
    """Group rows for the model-specific write-penalty loop.

    This legacy helper emits ``{"model", "rows", "chunks"}``; the generalized
    fragmentation helper emits ``{"key", "rows", "chunks"}``.
    """
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        model = normalize_model_name(row.model)
        group = groups.setdefault(model, {"model": model, "rows": [], "chunks": set()})
        group["rows"].append(row)
        group["chunks"].update(str(chunk) for chunk in row.declared_prompt_cache or ())
    return groups


def _chunks_shared_with_other_group(group: dict[str, Any], all_groups: Iterable[dict[str, Any]]) -> set[str]:
    chunks = set(group["chunks"])
    shared: set[str] = set()
    for other in all_groups:
        if other is group:
            continue
        shared.update(chunks & set(other["chunks"]))
    return shared


def _chunks_shared_across_groups(groups: list[dict[str, Any]]) -> set[str]:
    shared: set[str] = set()
    for group in groups:
        shared.update(_chunks_shared_with_other_group(group, iter(groups)))
    return shared


def _compute_fragmentation_costs(
    groups: list[dict[str, Any]],
    shared_chunks: set[str],
    *,
    ttl: str | None,
    ctx: AnalysisContext,
    representative_model_fn: Callable[[dict[str, Any]], str | None],
) -> dict[str, float] | None:
    """Sum each group's redundant cache_creation cost over the shared chunks.

    Honest-unmeasurable: returns ``None`` if any group lacks pricing OR any
    shared chunk has no resolvable token estimate (memo miss in greenfield).
    Mirrors ``_check_root_for_consolidation``'s "any None → skip" pattern so
    the warning never fabricates dollars when chunk-level data is unavailable.
    """
    from ..cost_estimation import _write_rate_for_ttl, get_model_pricing

    costs: dict[str, float] = {}
    for group in groups:
        model = representative_model_fn(group)
        if model is None:
            return None
        pricing = get_model_pricing(model)
        if pricing is None:
            return None
        group_shared = group["chunks"] & shared_chunks
        total_tokens = _sum_chunk_tokens(list(group_shared), model, ctx, ctx.memo_cache, ctx.workflow_path)
        if total_tokens is None:
            return None
        if is_likely_below_min_cache(model, total_tokens):
            continue
        costs[str(group["key"] or "")] = total_tokens * _write_rate_for_ttl(pricing, ttl, model)
    return costs


def _model_groups_payload(groups: list[dict[str, Any]], costs: dict[str, float]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for group in groups:
        rows = sorted(group["rows"], key=lambda row: row.node_path)
        model = str(group["key"])
        payload.append({
            "model": model,
            "node_paths": [row.node_path for row in rows],
            "node_count": len(rows),
            "cache_creation_cost_usd": costs[model],
        })
    return payload


def _format_model_groups_lines(groups: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for group in groups:
        node_paths = ", ".join(str(path) for path in group["node_paths"])
        noun = "node" if group["node_count"] == 1 else "nodes"
        lines.append(f"  - {group['model']} ({group['node_count']} {noun}): {node_paths}")
    return "\n".join(lines)


def _system_groups_payload(groups: list[dict[str, Any]], costs: dict[str, float]) -> list[dict[str, Any]]:
    return [
        {
            "system_preview": _preview_system(group["key"]),
            "node_ids": sorted(row.node_path for row in group["rows"]),
            "redundant_write_usd": costs[str(group["key"] or "")],
        }
        for group in groups
    ]


def _preview_system(system: str | None) -> str:
    if not system:
        return "(no system)"
    text = system.replace("\n", " ⏎ ")
    return text if len(text) <= 80 else text[:77] + "..."


def _format_system_groups_lines(groups: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for group in groups:
        node_ids = ", ".join(str(node_id) for node_id in group["node_ids"])
        lines.append(f"  - `{group['system_preview']}` -> {len(group['node_ids'])} node(s): {node_ids}")
    return "\n".join(lines)


def _single_call_write_penalty(row: PerCallRow, *, ttl: str | None) -> float | None:
    """Return the savings (write premium - input cost) from removing the cache declaration.

    ``None`` when pricing or token data is unavailable (honest-unmeasurable).
    Positive value = removing the declaration saves money. Mirrors the catalog's
    ``savings_usd`` semantics ("savings from fixing it").
    """
    from ..cost_estimation import _write_rate_for_ttl, get_model_pricing

    tokens = row.cacheable_tokens_estimated
    if tokens is None:
        return None
    if is_likely_below_min_cache(row.model, tokens):
        return None
    pricing = get_model_pricing(row.model)
    if pricing is None:
        return None
    input_rate = _input_rate(row.model)
    if input_rate is None:
        return None
    return tokens * _write_rate_for_ttl(pricing, ttl, row.model) - tokens * input_rate
