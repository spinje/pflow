"""Paste-ready cache-block edit text for cross-workflow recommendations.

Consumed by ``stages/cross_workflow.py``'s ``_emit_sub_workflow_cache_findings``
via a single call (``format_grouped_body_block``). The seam exchanges plain
strings and does not depend on diagnostic objects.
"""

from __future__ import annotations

from collections.abc import Iterable

from pflow.core.llm_capabilities import anthropic_models_at_threshold
from pflow.core.llm_config import _DEFAULT_FALLBACK_MODEL

from ..stages.row_builder import _static_excerpt
from ..types import (
    _GroupedConsumerProjection,
    _SubWorkflowCacheCandidate,
    _SubWorkflowCacheGroup,
    _workflow_basename,
)

_PARENT_PROSE_PREVIEW_LIMIT = 40
_MODEL_SWITCH_BAND = 1024


def format_grouped_body_block(
    group: _SubWorkflowCacheGroup,
    projections: tuple[_GroupedConsumerProjection, ...],
    tokens_per_input: dict[str, int | None],
    strictest_model: str,
    strictest_threshold: int,
    case: str,
) -> str:
    """Render the case-specific body embedded in the diagnostic message.

    All threshold comparisons use ``per_call_prefix_tokens`` — the bytes the
    provider's cache marker sees on each call. Cohort totals (per_call × calls)
    drive ``savings_usd`` only; they're irrelevant to whether the cache fires.
    """
    candidates_by_ref = {candidate.child_cache_ref: candidate for candidate in group.candidates}
    parent_label = _workflow_basename(group.candidates[0].parent_workflow) if group.candidates else "parent workflow"
    ref_count = len(group.candidates)
    input_phrase = _count_phrase(ref_count, "value")
    # Per-call prefix size of the LARGEST consumer in the group — used as the
    # representative "what does the provider see per call" number for body text.
    # For multi-consumer groups we still render per-consumer lines below.
    per_call_max = max((p.per_call_prefix_tokens for p in projections), default=0)
    lines: list[str] = []

    if case == "unmeasurable":
        return _format_unmeasurable_grouped_body(
            group=group,
            input_phrase=input_phrase,
            tokens_per_input=tokens_per_input,
        )

    if case == "refactor":
        return _format_refactor_grouped_body(
            group=group,
            input_phrase=input_phrase,
            ref_count=ref_count,
            per_call_max=per_call_max,
            tokens_per_input=tokens_per_input,
        )

    threshold_clause = (
        f"above {strictest_model}'s {strictest_threshold:,}-token cache minimum"
        if per_call_max >= strictest_threshold
        else f"below {strictest_model}'s {strictest_threshold:,}-token cache minimum"
    )
    if len(projections) > 1:
        lines.append(
            f"{input_phrase.capitalize()} {_flow_verb(ref_count)} in from parent {parent_label}, used by "
            f"{_count_phrase(len(projections), 'consumer node')}."
        )
        _append_honest_edit_lines(lines, group, tokens_per_input=tokens_per_input, include_cleanup=False)
        lines.append("Prompt-body templates to remove and per-consumer cache prefix:")
        for projection in projections:
            lines.extend(
                _format_per_consumer_input_lines(
                    projection=projection,
                    candidates_by_input=candidates_by_ref,
                    tokens_per_input=tokens_per_input,
                )
            )
    else:
        lines.append(
            f"{input_phrase.capitalize()} {_flow_verb(ref_count)} in from parent {parent_label}: "
            f"{_format_tokens_phrase(per_call_max)} per call ({threshold_clause})."
        )
        _append_honest_edit_lines(lines, group, tokens_per_input=tokens_per_input)

    if case == "model_switch":
        alternatives = anthropic_models_at_threshold(_MODEL_SWITCH_BAND)
        lines.append(
            f"→ Switch model: replace the `- model:` line in {_workflow_basename(group.child_workflow)} with one of:"
        )
        for model in alternatives:
            suffix = " (recommended — pflow's default)" if f"anthropic/{model}" == _DEFAULT_FALLBACK_MODEL else ""
            lines.append(f"    anthropic/{model}{suffix}")
        lines.append(
            "  These cache at ≥1,024 tokens. `prompt_cache:` declarations transfer unchanged. "
            "Switching providers changes base inference cost — see `pflow guide prompt-caching`."
        )
        lines.append("→ Then: apply steps (1)(2)(3) above.")
        lines.append(
            f"→ Monitor: re-run analyze-cache when per-call content grows past {strictest_threshold:,} tokens "
            "to enable caching at the current model."
        )

    return "\n".join(lines)


def _format_unmeasurable_grouped_body(
    *,
    group: _SubWorkflowCacheGroup,
    input_phrase: str,
    tokens_per_input: dict[str, int | None],
) -> str:
    lines = [
        f"{input_phrase.capitalize()} flow in but no consumer node has a resolved model — "
        "cannot compute the cache threshold."
    ]
    _append_honest_edit_lines(lines, group, tokens_per_input=tokens_per_input)
    lines.append(
        "→ Set `settings.default_model` or add `- model:` to each consumer node in "
        f"{_workflow_basename(group.child_workflow)}, then re-run analyze-cache."
    )
    return "\n".join(lines)


def _format_refactor_grouped_body(
    *,
    group: _SubWorkflowCacheGroup,
    input_phrase: str,
    ref_count: int,
    per_call_max: int,
    tokens_per_input: dict[str, int | None],
) -> str:
    subject = f"One value `{group.candidates[0].child_cache_ref}`" if ref_count == 1 else input_phrase.capitalize()
    lines = [
        f"{subject} {_format_tokens_phrase(per_call_max)} per call, "
        "below the smallest provider cache minimum (1,024 — Anthropic Sonnet 4.5)."
    ]
    _append_honest_edit_lines(lines, group, tokens_per_input=tokens_per_input)
    lines.append("→ Monitor: re-run analyze-cache when per-call content grows past 1,024 tokens.")
    lines.append(f"→ Verify: confirm {_format_tokens_phrase(per_call_max)} is the realistic per-call size.")
    return "\n".join(lines)


def _append_honest_edit_lines(
    lines: list[str],
    group: _SubWorkflowCacheGroup,
    *,
    tokens_per_input: dict[str, int | None],
    include_cleanup: bool = True,
) -> None:
    if _group_has_subpath_candidates(group):
        lines.append(_subpath_honesty_sentence(group))
    lines.extend(_format_exact_child_cache_edits(group))
    if include_cleanup:
        lines.append("Prompt-body templates to remove:")
        lines.extend(
            _format_single_consumer_input_lines(
                candidates=group.candidates,
                tokens_per_input=tokens_per_input,
            )
        )


def _group_has_subpath_candidates(group: _SubWorkflowCacheGroup) -> bool:
    return any(candidate.child_cache_ref != candidate.child_input_name for candidate in group.candidates)


def _subpath_honesty_sentence(group: _SubWorkflowCacheGroup) -> str:
    roots = tuple(dict.fromkeys(candidate.child_input_name for candidate in group.candidates))
    root_text = ", ".join(f"`{root}`" for root in roots)
    return (
        "Only these listed values are used by prompts. Do not cache full objects like "
        f"{root_text} unless you intentionally want every field in that object sent to the model."
    )


def _format_exact_child_cache_edits(group: _SubWorkflowCacheGroup) -> list[str]:
    lines = ["Edit child workflow:", "  Add or extend ## Cache:"]
    lines.append("    ```cache")
    lines.extend(f"    {line}" for line in _exact_child_cache_block_content(group).split("\n"))
    lines.append("    ```")
    lines.append("  Add prompt_cache entries:")
    for node_id, refs in sorted(group.cache_refs_by_consumer().items()):
        ordered_refs = [
            candidate.child_cache_ref for candidate in group.candidates if candidate.child_cache_ref in refs
        ]
        lines.append(f"    {node_id}: prompt_cache: [{', '.join(ordered_refs)}]")
    return lines


def _exact_child_cache_block_content(group: _SubWorkflowCacheGroup) -> str:
    """Render the paste-ready child ``## Cache`` block content.

    Each chunk emits the var line on its own; when a matching parent chunk
    contributes prose, a 40-char single-line preview of that prose is rendered
    immediately above the var line. Chunks are separated by blank lines to
    mirror the parent's ``## Cache`` visual structure. The single-line preview
    is intentional: it stays scannable for agents and (because
    ``_static_excerpt`` collapses internal whitespace) survives the renderer's
    line-by-line indenting without breaking the cache block layout.
    """
    parts: list[str] = []
    for candidate in group.candidates:
        chunk = ""
        if candidate.parent_prose.strip() and not candidate.parent_prose_origins_differ:
            chunk += _static_excerpt(candidate.parent_prose, limit=_PARENT_PROSE_PREVIEW_LIMIT)
            chunk += "\n\n"
        chunk += f"${{{candidate.child_cache_ref}}}"
        parts.append(chunk)
    return "\n\n".join(parts)


def _threshold_relation(tokens: int, threshold: int) -> str:
    return "above" if tokens >= threshold else "below"


def _parent_origin_clause(candidate: _SubWorkflowCacheCandidate) -> str | None:
    """Sub-line text naming the parent expression when it differs from the child input name.

    Surfaces parent→child data flow inside the action body for renamed inputs.
    Returns ``None`` for same-name passthroughs (no signal to add) and for
    multi-ref/literal parent values where ``parent_value_expr`` is empty.
    """
    expr = candidate.parent_value_expr
    if not expr or candidate.parent_cache_ref == candidate.child_cache_ref:
        return None
    return f"flows in from parent as `${{{candidate.parent_cache_ref}}}`"


def _format_per_consumer_input_lines(
    *,
    projection: _GroupedConsumerProjection,
    candidates_by_input: dict[str, _SubWorkflowCacheCandidate],
    tokens_per_input: dict[str, int | None],
) -> list[str]:
    """Render input bullets under one consumer-node heading in the multi-consumer case."""
    lines = [
        f"  Node `{projection.consumer_node_id}` "
        f"({_format_tokens_phrase(projection.per_call_prefix_tokens)} per call — "
        f"{_threshold_relation(projection.per_call_prefix_tokens, projection.threshold)} "
        f"{projection.threshold:,}-token minimum):"
    ]
    for input_name in projection.consumed_inputs:
        candidate = candidates_by_input[input_name]
        refs = _per_input_var_refs(candidate).get(projection.consumer_node_id, ())
        lines.append(
            f"    • `{input_name}` {_format_nullable_tokens(tokens_per_input.get(input_name))} — "
            f"uses {_format_var_refs(refs, fallback=input_name)}"
        )
        origin = _parent_origin_clause(candidate)
        if origin is not None:
            lines.append(f"        {origin}")
    return lines


def _format_single_consumer_input_lines(
    *,
    candidates: tuple[_SubWorkflowCacheCandidate, ...],
    tokens_per_input: dict[str, int | None],
) -> list[str]:
    """Render input bullets when the group has a single consumer node."""
    lines: list[str] = []
    for candidate in candidates:
        refs_by_node = _per_input_var_refs(candidate)
        refs = tuple(ref for node_refs in refs_by_node.values() for ref in node_refs)
        consumer_text = ", ".join(f"`{node_id}`" for node_id in candidate.child_node_ids)
        lines.append(
            f"  • `{candidate.child_cache_ref}` "
            f"{_format_nullable_tokens(tokens_per_input.get(candidate.child_cache_ref))} — "
            f"node(s) {consumer_text} use {_format_var_refs(refs, fallback=candidate.child_cache_ref)}"
        )
        origin = _parent_origin_clause(candidate)
        if origin is not None:
            lines.append(f"      {origin}")
    return lines


def _count_phrase(count: int, singular: str) -> str:
    if count == 1:
        return f"1 {singular}"
    if singular == "value":
        words = {2: "Two", 3: "Three", 4: "Four", 5: "Five"}
        return f"{words.get(count, str(count))} values"
    return f"{count} {singular}s"


def _flow_verb(count: int) -> str:
    return "flows" if count == 1 else "flow"


def _format_tokens_phrase(tokens: int) -> str:
    return f"~{tokens:,} tokens"


def _format_nullable_tokens(tokens: int | None) -> str:
    return "unmeasurable" if tokens is None else f"~{tokens:,} tokens"


def _format_var_refs(refs: Iterable[str], *, fallback: str) -> str:
    unique = tuple(dict.fromkeys(refs))
    if not unique:
        unique = (fallback,)
    return ", ".join(f"`${{{ref}}}`" for ref in unique)


def _per_input_var_refs(candidate: _SubWorkflowCacheCandidate) -> dict[str, tuple[str, ...]]:
    """Prompt `${var}` references that must be removed before caching the input."""
    return {node_id: tuple(refs) for node_id, refs in candidate.body_refs_by_node.items()}
