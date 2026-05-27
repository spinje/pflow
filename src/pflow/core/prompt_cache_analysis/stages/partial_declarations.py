"""Partial prompt-cache declaration diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pflow.core.diagnostic import Diagnostic
from pflow.core.llm_capabilities import get_min_cache_tokens
from pflow.core.prompt_refs import classify_prompt_refs

from ..below_min_tokens_detector import is_below_min_cache
from ..context import AnalysisContext
from ..token_estimation import _estimate_ref_tokens
from ..types import PerCallRow, invocation_count_for
from ..warning_catalog import make_diagnostic
from .row_builder import _node_inputs
from .suggestions import (
    _batch_aliases,
    _cache_items,
    _collect_llm_template_root_references,
    _estimate_token_savings_usd,
    _is_batch_scoped_ref,
    _longest_var_prefix_match,
    _prompt_body_cleanup_for_node,
    _template_root_segment,
)


@dataclass(frozen=True)
class _PartialDeclarationFinding:
    node_id: str
    declared_chunks: tuple[str, ...]
    missing_chunks: tuple[str, ...]
    corrected_prompt_cache: tuple[str, ...]
    prompt_body_cleanup: tuple[str, ...]
    missing_chunks_tokens: int | None
    rep_model: str


def _detect_partial_prompt_cache_declarations(
    workflow_ir: dict[str, Any],
    workflow_path: str | None,
    ctx: AnalysisContext,
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
) -> list[_PartialDeclarationFinding]:
    """Find LLM nodes that reference shared cache chunks they do not declare."""
    items = _cache_items(workflow_ir)
    if not items:
        return []
    name_order = [str(item["name"]) for item in items]
    var_to_name = _cache_item_var_to_name(items)
    if not var_to_name:
        return []

    refs_by_name = _collect_llm_template_root_references(workflow_ir, var_to_name)
    cache_item_names = set(name_order)
    findings: list[_PartialDeclarationFinding] = []
    for node in workflow_ir.get("nodes", []) or []:
        finding = _partial_declaration_finding_for_node(
            node=node,
            name_order=name_order,
            var_to_name=var_to_name,
            refs_by_name=refs_by_name,
            cache_item_names=cache_item_names,
            workflow_path=workflow_path,
            ctx=ctx,
            rows_by_node_path=rows_by_node_path,
        )
        if finding is not None:
            findings.append(finding)
    return findings


def _cache_item_var_to_name(items: list[dict[str, Any]]) -> dict[str, str]:
    var_to_name: dict[str, str] = {}
    for item in items:
        name = item.get("name")
        if not isinstance(name, str):
            continue
        var = item.get("var", name)
        if isinstance(var, str) and var:
            var_to_name[var] = name
    return var_to_name


def _partial_declaration_finding_for_node(
    *,
    node: dict[str, Any],
    name_order: list[str],
    var_to_name: dict[str, str],
    refs_by_name: dict[str, list[str]],
    cache_item_names: set[str],
    workflow_path: str | None,
    ctx: AnalysisContext,
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
) -> _PartialDeclarationFinding | None:
    if not isinstance(node, dict) or node.get("type") != "llm":
        return None
    node_id_raw = node.get("id")
    declared_raw = node.get("prompt_cache")
    prompt = node.get("params", {}).get("prompt", "")
    if not node_id_raw or not isinstance(declared_raw, list) or not isinstance(prompt, str):
        return None
    node_id = str(node_id_raw)
    declared = tuple(str(chunk) for chunk in declared_raw)
    node_refs = _node_referenced_cache_names(node, var_to_name)
    missing = _missing_shared_cache_names(name_order, node_refs, set(declared), refs_by_name)
    if not missing:
        return None

    corrected_set = set(declared) | set(missing)
    corrected = tuple(name for name in name_order if name in corrected_set)
    rep_model = _representative_model_for_node(node_id, workflow_path, rows_by_node_path)
    missing_tokens = _estimate_missing_chunks_tokens(
        missing,
        var_to_name,
        model=rep_model,
        ctx=ctx,
        workflow_path=workflow_path,
    )
    return _PartialDeclarationFinding(
        node_id=node_id,
        declared_chunks=declared,
        missing_chunks=tuple(missing),
        corrected_prompt_cache=corrected,
        prompt_body_cleanup=_prompt_body_cleanup_for_node(node, corrected, cache_item_names),
        missing_chunks_tokens=missing_tokens,
        rep_model=rep_model,
    )


def _node_referenced_cache_names(node: dict[str, Any], var_to_name: dict[str, str]) -> set[str]:
    prompt = node.get("params", {}).get("prompt", "")
    if not isinstance(prompt, str):
        return set()
    node_refs: set[str] = set()
    batch_aliases = _batch_aliases(node)
    node_inputs = _node_inputs(node)
    for ref in classify_prompt_refs(prompt, batch_alias=None, node_inputs=node_inputs):
        for operand in ref.operand_paths:
            if _is_batch_scoped_ref(operand, batch_aliases):
                continue
            matched_var = _longest_var_prefix_match(operand, var_to_name.keys())
            if matched_var is not None:
                node_refs.add(var_to_name[matched_var])
    return node_refs


def _missing_shared_cache_names(
    name_order: list[str],
    node_refs: set[str],
    declared: set[str],
    refs_by_name: dict[str, list[str]],
) -> list[str]:
    missing: list[str] = []
    for name in name_order:
        if name not in node_refs or name in declared:
            continue
        if len(set(refs_by_name.get(name, []))) >= 2:
            missing.append(name)
    return missing


def _estimate_missing_chunks_tokens(
    missing_names: list[str],
    var_to_name: dict[str, str],
    *,
    model: str,
    ctx: AnalysisContext,
    workflow_path: str | None,
) -> int | None:
    """Sum per-call token estimates for missing cache items' values."""
    if not model:
        return None
    name_to_var = {name: var for var, name in var_to_name.items()}
    total = 0
    for name in missing_names:
        var = name_to_var.get(name)
        if var is None:
            return None
        tokens = _estimate_ref_tokens(
            var,
            model=model,
            memo_cache=ctx.memo_cache,
            workflow_path=workflow_path,
            ctx=ctx,
        )
        if tokens is None:
            return None
        total += tokens
    return total


def _representative_model_for_node(
    node_id: str,
    workflow_path: str | None,
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
) -> str:
    row = rows_by_node_path.get((workflow_path, node_id))
    return row.model if row is not None and row.model else ""


def _emit_partial_declaration_findings(
    *,
    cw_result: Any,
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
    ctx: AnalysisContext,
    consolidate_root_diags: list[Diagnostic],
) -> list[Diagnostic]:
    """Emit one grouped ``cache.prompt-cache-incomplete`` diagnostic per workflow."""
    consolidate_roots = _extract_consolidate_roots(consolidate_root_diags)
    diagnostics: list[Diagnostic] = []
    for workflow_path, workflow_ir in getattr(cw_result, "irs_by_workflow", {}).items():
        wf_ctx = AnalysisContext.build(
            workflow_ir=workflow_ir,
            parameters=ctx.parameters_for_workflow(workflow_path),
            memo_cache=ctx.memo_cache,
            trace_data=ctx.trace_data,
            trace_outputs_by_key=ctx.trace_outputs_by_key,
            workflow_path=workflow_path,
            base_path=ctx.base_path,
            parameters_by_workflow=ctx.parameters_by_workflow,
            predicted_cache_keys=ctx.predicted_cache_keys,
            prediction_fidelity_notes=ctx.prediction_fidelity_notes,
            stale_memo_skipped=ctx.stale_memo_skipped,
            stale_memo_uncheckable=ctx.stale_memo_uncheckable,
        )
        findings = _detect_partial_prompt_cache_declarations(
            workflow_ir,
            workflow_path,
            wf_ctx,
            rows_by_node_path,
        )
        findings = [
            finding
            for finding in findings
            if not _finding_chunks_overlap_with_consolidate(finding.missing_chunks, consolidate_roots, workflow_path)
        ]
        if not findings:
            continue
        below_threshold = any(is_below_min_cache(f.rep_model, f.missing_chunks_tokens) for f in findings)
        below_threshold_clause = _below_threshold_clause_for_findings(findings) if below_threshold else ""
        savings_usd = (
            None
            if below_threshold
            else _project_partial_declaration_savings(findings, rows_by_node_path, workflow_path)
        )
        workflow_label = workflow_path or "<inline>"
        diagnostics.append(
            make_diagnostic(
                "cache.prompt-cache-incomplete",
                node_id=None,
                affected_workflow=workflow_label,
                workflow_basename=Path(workflow_label).name if workflow_path else "<inline>",
                affected_node_count=len(findings),
                node_findings=_node_findings_context(findings),
                node_findings_block=_format_node_findings_block(findings),
                below_threshold_clause=below_threshold_clause,
                savings_usd=savings_usd,
            )
        )
    return diagnostics


def _extract_consolidate_roots(diagnostics: list[Diagnostic]) -> dict[str | None, set[str]]:
    roots: dict[str | None, set[str]] = {}
    for diag in diagnostics:
        if diag.id != "cache.consolidate-to-root-recommended":
            continue
        ctx = diag.context or {}
        workflow = ctx.get("affected_workflow")
        root = ctx.get("root")
        if isinstance(root, str):
            roots.setdefault(str(workflow) if isinstance(workflow, str) else None, set()).add(root)
    return roots


def _finding_chunks_overlap_with_consolidate(
    missing_chunks: tuple[str, ...],
    consolidate_roots: dict[str | None, set[str]],
    workflow_path: str | None,
) -> bool:
    roots = consolidate_roots.get(workflow_path, set())
    return any(_template_root_segment(chunk) in roots for chunk in missing_chunks)


def _below_threshold_clause_for_findings(findings: list[_PartialDeclarationFinding]) -> str:
    entries: list[str] = []
    for finding in findings:
        tokens = finding.missing_chunks_tokens
        if not is_below_min_cache(finding.rep_model, tokens) or tokens is None:
            continue
        threshold = get_min_cache_tokens(finding.rep_model)
        entries.append(f"{finding.node_id}: ~{tokens:,} tokens below {finding.rep_model}'s {threshold:,}-token minimum")
    if not entries:
        return ""
    return "\nNote: " + "; ".join(entries) + " — caching won't fire until rendered content reaches the minimum."


def _project_partial_declaration_savings(
    findings: list[_PartialDeclarationFinding],
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
    workflow_path: str | None,
) -> float | None:
    total = 0.0
    for finding in findings:
        if finding.missing_chunks_tokens is None:
            return None
        row = rows_by_node_path.get((workflow_path, finding.node_id))
        if row is None or not row.model:
            return None
        # Trace observations win when present; greenfield rows fall back to the
        # row contract multiplier (batch size or 1).
        calls = row.observed_call_count or invocation_count_for(row)
        savings = _estimate_token_savings_usd(row.model, finding.missing_chunks_tokens, calls)
        if savings is None:
            return None
        total += savings
    return total


def _node_findings_context(findings: list[_PartialDeclarationFinding]) -> list[dict[str, Any]]:
    return [
        {
            "node_id": finding.node_id,
            "missing_chunks": list(finding.missing_chunks),
            "missing_chunks_csv": ", ".join(f"`{chunk}`" for chunk in finding.missing_chunks),
            "corrected_prompt_cache": list(finding.corrected_prompt_cache),
            "corrected_prompt_cache_inline": "[" + ", ".join(finding.corrected_prompt_cache) + "]",
            "prompt_body_cleanup": list(finding.prompt_body_cleanup),
            "prompt_body_cleanup_csv": ", ".join(f"${{{ref}}}" for ref in finding.prompt_body_cleanup) or "(none)",
            "rep_model": finding.rep_model,
            "missing_chunks_tokens": finding.missing_chunks_tokens,
        }
        for finding in findings
    ]


def _format_node_findings_block(findings: list[_PartialDeclarationFinding]) -> str:
    lines = ["Affected nodes:"]
    for finding in findings:
        cleanup = ", ".join(f"${{{ref}}}" for ref in finding.prompt_body_cleanup) or "(none)"
        corrected = "[" + ", ".join(finding.corrected_prompt_cache) + "]"
        model = finding.rep_model or "<unresolved>"
        lines.extend([
            f"- `{finding.node_id}` (model: {model}):",
            f"    1. Remove from prompt body: {cleanup}",
            f"    2. Set prompt_cache: {corrected}",
        ])
    return "\n".join(lines)
