"""Closed catalog of ``cache.*`` warning IDs and the ``make_diagnostic`` helper.

The catalog is the agent-facing contract: each entry pins severity, source,
category, and the message / suggestions / path templates so emitted Diagnostics
have stable shape regardless of which call site builds them. Per Task 159
DD#29, the catalog is closed in v1 — adding new IDs goes through design review.

12 entries in v1: 9 from spec § "Stable Warning ID Catalog" + ``cache.discrepancy``
(Round 2, dispatch over ``root_cause`` enum), ``cache.invalid-on-non-llm``
(Round 3, validator-reach gap closure for non-LLM nodes), and
``cache.prewarm-no-prefix`` (Round 3, prewarm-without-static-prefix advisory).

The dry-run nudge ID ``cache.opportunities-available`` is reserved separately —
it's emitted by ``summarize()`` not ``analyze()``, so it isn't part of the
catalog (per spec line 307).

Templates note: where a catalog row's text overlaps an emitter shipped in
Phase B (e.g., ``cache.order-mismatch``, ``cache.unused-chunk``,
``cache.invalid-on-non-llm`` already emit from ``data_flow.py``), the
catalog template is kept in sync with the shipped emitter so both paths
produce byte-equivalent Diagnostics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

from pflow.core.diagnostic import (
    CACHE_ADVISORY_CATEGORY,
    CACHE_FAILURE_CATEGORY,
    CACHE_WARNING_CATEGORY,
    Diagnostic,
    Severity,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Spec dataclass — frozen so the module-load catalog cannot drift at runtime.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CacheWarningSpec:
    """One catalog row.

    ``required_context_keys`` is a tuple of ``(key_name, type)`` pairs the
    caller MUST pass to ``make_diagnostic``. ``nullable_cost_keys`` lists
    keys whose value may legitimately be ``None`` (cost degradation).
    Everything else is mandatory and validated at construction.
    """

    severity: Severity
    source: str
    category: str
    message_template: str
    required_context_keys: tuple[tuple[str, type], ...]
    suggestions_template: tuple[str, ...]
    path_template: str
    nullable_cost_keys: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Templates synced with shipped data_flow.py emitters where they overlap.
# ---------------------------------------------------------------------------


# cache.order-mismatch — shipped by data_flow.py:740 (_make_order_mismatch_diagnostic)
# The ``expected:`` line shows the subset reordered to match ## Cache declaration
# order — i.e. the exact replacement the agent should write. (Earlier label was
# ``declared:``; renamed for clarity since the line shows the subset, not the
# full ## Cache block.)
_ORDER_MISMATCH_MESSAGE = (
    "Node '{node_id}' prompt_cache order doesn't match ## Cache declaration\n"
    "  expected:  {declared_str}\n"
    "  you wrote: {actual_str}\n"
    "  fix:       reorder the `prompt_cache:` field to match ## Cache declaration order"
)

# cache.invalid-on-non-llm — shipped by data_flow.py:702 (_make_invalid_on_non_llm_diagnostic)
_INVALID_ON_NON_LLM_MESSAGE = (
    "Node '{node_id}' is type: {node_type} but declares {invalid_fields_csv} — "
    "{is_or_are_capitalized} only valid on type: llm nodes."
)

# cache.unused-chunk — shipped by data_flow.py:892 (_make_unused_chunk_diagnostic)
_UNUSED_CHUNK_MESSAGE = (
    "Cache chunk '{chunk_name}' is declared in ## Cache but no node references it via prompt_cache:."
)


CACHE_WARNING_CATALOG: dict[str, CacheWarningSpec] = {
    # === Run-validation tier (always emitted at pflow run) ===
    "cache.order-mismatch": CacheWarningSpec(
        severity=Severity.ERROR,
        source="validator",
        category=CACHE_FAILURE_CATEGORY,
        message_template=_ORDER_MISMATCH_MESSAGE,
        required_context_keys=(
            ("node_id", str),
            ("declared", list),
            ("actual", list),
            ("declared_str", str),
            ("actual_str", str),
        ),
        suggestions_template=(),  # message itself carries the fix line
        path_template="nodes[id={node_id}].prompt_cache",
    ),
    "cache.unused-chunk": CacheWarningSpec(
        severity=Severity.WARNING,
        source="validator",
        category=CACHE_WARNING_CATEGORY,
        message_template=_UNUSED_CHUNK_MESSAGE,
        required_context_keys=(("chunk_name", str), ("source_line", int)),
        suggestions_template=(
            "Remove '{chunk_name}' from ## Cache, OR reference it from a node's `- prompt_cache: [{chunk_name}]`.",
        ),
        path_template="cache.items[name={chunk_name}]",
    ),
    "cache.invalid-on-non-llm": CacheWarningSpec(
        severity=Severity.ERROR,
        source="validator",
        category=CACHE_FAILURE_CATEGORY,
        message_template=_INVALID_ON_NON_LLM_MESSAGE,
        required_context_keys=(
            ("node_id", str),
            ("node_type", str),
            ("invalid_fields", list),
            ("invalid_fields_csv", str),
            ("is_or_are", str),
            ("plural_s", str),
        ),
        suggestions_template=(
            "Remove the invalid declaration{plural_s} ({invalid_fields_csv}) from {node_id}, "
            "OR move the LLM logic into a type: llm node.",
        ),
        path_template="nodes[id={node_id}]",
    ),
    # === Analytical tier (emitted by analyze-cache / --dry-run only) ===
    "cache.shared-context-undeclared": CacheWarningSpec(
        severity=Severity.INFO,
        source="cache_analyzer",
        category=CACHE_ADVISORY_CATEGORY,
        message_template=(
            "{node_count} LLM nodes share static context that isn't in any ## Cache block (saves {savings_str}/run)"
        ),
        required_context_keys=(
            ("node_count", int),
            ("shared_chunks", list),
            ("affected_workflow", str),
            ("savings_usd", float),
        ),
        suggestions_template=(
            "Paste the suggested ## Cache block (see Suggested ## Cache block section above) into {affected_workflow}.",
            "Per-node prompt_cache: assignments are listed in the same section.",
        ),
        path_template="workflows[path={affected_workflow}]",
        nullable_cost_keys=frozenset({"savings_usd"}),
    ),
    "cache.batch-prewarm-recommended": CacheWarningSpec(
        severity=Severity.WARNING,
        source="cache_analyzer",
        category=CACHE_WARNING_CATEGORY,
        message_template=(
            "{node_id}: {batch_size}-item batch with ~{prefix_tokens_estimated}-token "
            "static prefix has no explicit prewarm decision; prewarming would save "
            "~{savings_pct}% of batch cost"
        ),
        required_context_keys=(
            ("node_id", str),
            ("batch_size", int),
            ("prefix_tokens_estimated", int),
            ("savings_pct", int),
            ("savings_usd", float),
        ),
        suggestions_template=(
            "Add `- prewarm: true` to {node_id} to opt in ({savings_str}/run).",
            "OR add `- prewarm: false` to {node_id} to opt out explicitly (suppresses this warning).",
        ),
        path_template="nodes[id={node_id}]",
        nullable_cost_keys=frozenset({"savings_usd"}),
    ),
    "cache.dynamic-before-static": CacheWarningSpec(
        severity=Severity.WARNING,
        source="cache_analyzer",
        category=CACHE_WARNING_CATEGORY,
        message_template=(
            "{node_id}: dynamic `${{{dynamic_ref}}}` reference at line {dynamic_line} "
            "of the prompt template precedes ~{cacheable_tokens}-token cacheable "
            "content; cache won't fire for {affected_calls} calls per run"
        ),
        required_context_keys=(
            ("node_id", str),
            ("dynamic_ref", str),
            ("dynamic_line", int),
            ("cacheable_tokens", int),
            ("affected_calls", int),
            ("savings_usd", float),
            ("projected_ratio_pct", int),
        ),
        suggestions_template=(
            "Move the cacheable content (everything stable across calls) to BEFORE "
            "`${{{dynamic_ref}}}` in the prompt template.",
            "Projected cache ratio after fix: {projected_ratio_pct}%.",
        ),
        path_template="nodes[id={node_id}].prompt",
        nullable_cost_keys=frozenset({"savings_usd"}),
    ),
    "cache.padding-advisory": CacheWarningSpec(
        severity=Severity.INFO,
        source="cache_analyzer",
        category=CACHE_ADVISORY_CATEGORY,
        message_template=(
            "{node_id}: prompt_cache subset doesn't start at position 1 of ## Cache "
            "declaration order; padding to {suggested_subset} would unlock prefix "
            "hits at 0.1× read rate (saves {savings_str}/run)"
        ),
        required_context_keys=(
            ("node_id", str),
            ("current_subset", list),
            ("suggested_subset", list),
            ("savings_usd", float),
        ),
        suggestions_template=(
            "Extend `prompt_cache:` to `{suggested_subset}` to gain prefix-cache hits from upstream writes.",
        ),
        path_template="nodes[id={node_id}].prompt_cache",
        nullable_cost_keys=frozenset({"savings_usd"}),
    ),
    "cache.below-min-tokens": CacheWarningSpec(
        severity=Severity.WARNING,
        source="cache_analyzer",
        category=CACHE_WARNING_CATEGORY,
        message_template=(
            "{node_id}: declared cache content is ~{cacheable_tokens} tokens, below "
            "{model}'s minimum of {min_tokens}; cache_control markers will silently "
            "no-op at the provider"
        ),
        required_context_keys=(
            ("node_id", str),
            ("model", str),
            ("cacheable_tokens", int),
            ("min_tokens", int),
        ),
        suggestions_template=(
            "Increase cache content above {min_tokens} tokens by adding more chunks "
            "to ## Cache, OR remove `prompt_cache:` from {node_id} since the cache "
            "won't fire anyway.",
        ),
        path_template="nodes[id={node_id}].prompt_cache",
    ),
    "cache.cross-workflow-prose-mismatch": CacheWarningSpec(
        severity=Severity.INFO,
        source="cache_analyzer",
        category=CACHE_ADVISORY_CATEGORY,
        message_template=(
            "{parent_workflow} → {child_workflow}: chunk `{chunk_name}` declared in "
            "both ## Cache blocks with different prose-before-${{var}}; "
            "cross-workflow byte-level cache hit will not fire"
        ),
        required_context_keys=(
            ("parent_workflow", str),
            ("child_workflow", str),
            ("chunk_name", str),
            ("parent_prose", str),
            ("child_prose", str),
        ),
        suggestions_template=(
            "Pick one prose label and use it in both files' ## Cache blocks for chunk `{chunk_name}`.",
        ),
        path_template="workflows[path={parent_workflow}].cache.items[name={chunk_name}]",
    ),
    "cache.cross-workflow-rename-detected": CacheWarningSpec(
        severity=Severity.INFO,
        source="cache_analyzer",
        category=CACHE_ADVISORY_CATEGORY,
        message_template=(
            "{parent_workflow} → {child_workflow}: parent passes `{parent_value_expr}` "
            "as input named `{child_input_name}` (line {line_in_parent}); same "
            "logical value has two names across the boundary"
        ),
        required_context_keys=(
            ("parent_workflow", str),
            ("child_workflow", str),
            ("parent_value_expr", str),
            ("child_input_name", str),
            ("line_in_parent", int),
            ("parent_node_id", str),
        ),
        suggestions_template=(
            "Rename the child input to match the parent's value name, OR rename the "
            "parent value to match the child's input name. Then ensure both "
            "## Cache blocks use the same chunk identifier and identical prose.",
        ),
        path_template=("workflows[path={parent_workflow}].nodes[id={parent_node_id}].inputs[name={child_input_name}]"),
    ),
    "cache.discrepancy": CacheWarningSpec(
        severity=Severity.INFO,
        source="cache_analyzer",
        category=CACHE_ADVISORY_CATEGORY,
        message_template=(
            "{node_id} (path: {trace_path}): predicted hit_ratio {predicted_pct}%, "
            "actual {actual_pct}% — root cause: {root_cause_summary}"
        ),
        required_context_keys=(
            ("node_id", str),
            ("trace_path", str),
            ("predicted_pct", int),
            ("actual_pct", int),
            ("root_cause", str),
            ("root_cause_summary", str),
        ),
        suggestions_template=(),  # DISPATCHED on root_cause — see CACHE_DISCREPANCY_*
        path_template="nodes[id={node_id}]",
        nullable_cost_keys=frozenset({"cache_age_sec", "predicted_cache_key", "actual_cache_key"}),
    ),
    "cache.prewarm-no-prefix": CacheWarningSpec(
        severity=Severity.INFO,
        source="cache_analyzer",
        category=CACHE_ADVISORY_CATEGORY,
        message_template=(
            "{node_id}: prewarm: true declared but the prompt template has no static "
            "prefix before the first ${{<batch_alias>.X}} reference; auto-batch-prefix "
            "caching cannot fire (no shared bytes across items)."
        ),
        required_context_keys=(
            ("node_id", str),
            ("batch_alias", str),
            ("first_dynamic_position", int),
        ),
        suggestions_template=(
            "Move stable content (instructions, schema definitions, persona) BEFORE "
            "the first `${{<batch_alias>.X}}` reference in the prompt template, OR "
            "remove `- prewarm: true` from {node_id} since auto-batch-prefix caching "
            "has nothing to cache.",
        ),
        path_template="nodes[id={node_id}].prompt",
    ),
}


# Auto-derived count constant — defends against drift across docstrings,
# tests, and MCP schemas. Adding a new ID requires zero count-update edits.
EXPECTED_CATALOG_COUNT: Final[int] = len(CACHE_WARNING_CATALOG)


# ---------------------------------------------------------------------------
# cache.discrepancy dispatch — three module-level constants per F1 plan
# ---------------------------------------------------------------------------


CACHE_DISCREPANCY_ACTION_TEMPLATES: dict[str, str] = {
    "ttl_expiry": "Consider `- ttl: 1h` on the {affected_workflow} ## Cache block.",
    "key_mismatch": (
        "Upstream value changed between predicted run and actual run; re-run analyze-cache to refresh the prediction."
    ),
    "parallel_write_race": "Add `- prewarm: true` to the batch node to serialize the first write.",
    "chunk_skipped": (
        "Cache chunk `{skipped_chunk}` was skipped at runtime (branch absent); "
        "declaration is correct but rendered subset is shorter."
    ),
    "unknown": (
        "Cannot attribute discrepancy to root cause '{root_cause}' (not in known "
        "set: ttl_expiry|key_mismatch|parallel_write_race|chunk_skipped); inspect "
        "the trace events for {node_id} manually."
    ),
}


CACHE_DISCREPANCY_REQUIRED_CONTEXT: dict[str, tuple[tuple[str, type], ...]] = {
    "ttl_expiry": (("affected_workflow", str),),
    "key_mismatch": (),
    "parallel_write_race": (),
    "chunk_skipped": (("skipped_chunk", str),),
    "unknown": (),
}


CACHE_DISCREPANCY_ACTION_PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
    "ttl_expiry": ("suggested_ttl", "affected_workflow"),
    "key_mismatch": ("upstream_value_changed",),
    "parallel_write_race": ("recommended_fix",),
    "chunk_skipped": ("skipped_chunk", "branch_node"),
    "unknown": ("raw_root_cause",),
}


# Reserved nudge ID — emitted by summarize() per spec line 307; lives outside
# the catalog because it isn't a finding the analyzer surfaces in `warnings[]`.
CACHE_OPPORTUNITIES_NUDGE_ID: Final[str] = "cache.opportunities-available"


# ---------------------------------------------------------------------------
# make_diagnostic — single helper used by all analyzer-emitted IDs
# ---------------------------------------------------------------------------


def _format_savings(savings_usd: Any) -> str:
    """Format ``savings_usd`` for inline message rendering. ``None`` → 'unavailable'."""
    if savings_usd is None:
        return "savings unavailable"
    return f"-${float(savings_usd):.2f}"


def _validate_required(
    spec: CacheWarningSpec,
    context_kwargs: dict[str, Any],
    node_id: str | None,
    warning_id: str,
) -> None:
    """Raise KeyError for missing required keys. Nullable cost keys may be None.

    ``node_id`` is the helper's separate kwarg (not in ``context_kwargs``); when
    a catalog row lists it as required, it's checked against the helper kwarg.
    """
    for key, _expected_type in spec.required_context_keys:
        if key == "node_id":
            if node_id is None:
                raise KeyError(
                    f"make_diagnostic({warning_id!r}) missing required helper kwarg 'node_id'. "
                    f"Pass via keyword: make_diagnostic('{warning_id}', node_id='...', ...)."
                )
            continue
        if key not in context_kwargs:
            raise KeyError(
                f"make_diagnostic({warning_id!r}) missing required context key '{key}'. "
                f"Required: {[k for k, _ in spec.required_context_keys]}"
            )
        value = context_kwargs[key]
        if value is None and key not in spec.nullable_cost_keys:
            raise KeyError(
                f"make_diagnostic({warning_id!r}) required key '{key}' is None — "
                f"only nullable_cost_keys ({sorted(spec.nullable_cost_keys)}) accept None."
            )


def _dispatch_discrepancy(
    *, format_dict: dict[str, Any], context_kwargs: dict[str, Any]
) -> tuple[list[str], dict[str, Any]]:
    """cache.discrepancy: dispatch on root_cause and build typed payload.

    Returns ``(suggestions, action_payload)``. The caller stores the payload
    on ``context["root_cause_action"]`` so agents reading the JSON output
    dispatch on typed data, not regex-parsed prose.
    """
    root_cause = context_kwargs["root_cause"]
    template = CACHE_DISCREPANCY_ACTION_TEMPLATES.get(root_cause)
    if template is None:
        # Unknown enum — log and fall through to the 'unknown' template so
        # the agent sees the rejected value, not silent degradation.
        logger.warning(
            "cache.discrepancy emitted with unrecognized root_cause %r — using fallback action template",
            root_cause,
        )
        template = CACHE_DISCREPANCY_ACTION_TEMPLATES["unknown"]
        action_payload: dict[str, Any] = {"raw_root_cause": root_cause}
    else:
        # Validate per-cause required keys (KeyError if missing).
        for key, _ in CACHE_DISCREPANCY_REQUIRED_CONTEXT[root_cause]:
            if key not in context_kwargs:
                raise KeyError(
                    f"make_diagnostic('cache.discrepancy', root_cause={root_cause!r}) missing required key '{key}'."
                )
        # Build the typed payload per the schema map.
        if root_cause == "ttl_expiry":
            action_payload = {
                "suggested_ttl": "1h",
                "affected_workflow": context_kwargs["affected_workflow"],
            }
        elif root_cause == "key_mismatch":
            action_payload = {"upstream_value_changed": True}
        elif root_cause == "parallel_write_race":
            action_payload = {"recommended_fix": "prewarm:true"}
        elif root_cause == "chunk_skipped":
            action_payload = {
                "skipped_chunk": context_kwargs["skipped_chunk"],
                # Optional — analyzer may not always identify the branching node.
                "branch_node": context_kwargs.get("branch_node"),
            }
        else:  # safety net — shouldn't fire because we hit the unknown branch above
            action_payload = {"raw_root_cause": root_cause}

    suggestions = [template.format(**format_dict)]
    return suggestions, action_payload


def make_diagnostic(
    warning_id: str,
    *,
    node_id: str | None = None,
    **context_kwargs: Any,
) -> Diagnostic:
    """Build a ``Diagnostic`` from a catalog entry.

    Validates required context keys at construction so catalog-misuse bugs
    surface in tests, not in production renderers. Every key passed in survives
    into ``diag.context`` byte-for-byte (the context-passthrough fidelity
    contract from Round 5) — agents reading the JSON output dispatch on typed
    context fields regardless of whether the human-rendered message references
    them.

    Special case for ``cache.discrepancy``: the helper dispatches on
    ``context_kwargs["root_cause"]`` and assembles the per-cause typed payload
    at ``context["root_cause_action"]``.
    """
    if warning_id not in CACHE_WARNING_CATALOG:
        raise KeyError(f"Unknown cache warning ID: {warning_id!r}. Catalog has {len(CACHE_WARNING_CATALOG)} entries.")
    spec = CACHE_WARNING_CATALOG[warning_id]
    _validate_required(spec, context_kwargs, node_id, warning_id)

    # Format-dict merges node_id (helper kwarg) with all context kwargs so
    # message / suggestions / path templates can reference {node_id}.
    format_dict: dict[str, Any] = {**context_kwargs, "node_id": node_id}

    # Some templates use {savings_str} as a typed alias of savings_usd that
    # gracefully degrades on None. Compute on demand.
    if "savings_usd" in context_kwargs:
        format_dict["savings_str"] = _format_savings(context_kwargs["savings_usd"])

    # cache.invalid-on-non-llm: provide the lowercase form matching the
    # shipped data_flow.py emitter (lowercase 'this'/'these'). Synced with
    # _make_invalid_on_non_llm_diagnostic at data_flow.py:719 — drift between
    # the two would produce non-byte-equivalent messages for the same finding.
    if "is_or_are" in context_kwargs:
        format_dict["is_or_are_capitalized"] = (
            "this field is" if context_kwargs["is_or_are"] == "is" else "these fields are"
        )

    # cache.discrepancy → dispatch; everything else → straight format.
    if warning_id == "cache.discrepancy":
        suggestions, action_payload = _dispatch_discrepancy(format_dict=format_dict, context_kwargs=context_kwargs)
        message = spec.message_template.format(**format_dict)
        path = spec.path_template.format(**format_dict)
        # Build context: passthrough fidelity + category + typed action payload.
        context: dict[str, Any] = dict(context_kwargs)
        context["category"] = spec.category
        context["root_cause_action"] = action_payload
        context["path"] = path
    else:
        message = spec.message_template.format(**format_dict)
        suggestions = [s.format(**format_dict) for s in spec.suggestions_template]
        path = spec.path_template.format(**format_dict)
        context = dict(context_kwargs)
        context["category"] = spec.category
        context["path"] = path

    title = _CATEGORY_TITLE.get(spec.category)

    return Diagnostic(
        severity=spec.severity,
        source=spec.source,
        title=title,
        node_id=node_id,
        id=warning_id,
        message=message,
        suggestions=suggestions if suggestions else None,
        context=context,
        see_also=["caching"],
    )


# Category → title mapping mirrors core.diagnostic.CATEGORY_TITLES.
_CATEGORY_TITLE: Final[dict[str, str]] = {
    CACHE_FAILURE_CATEGORY: "Cache Failure",
    CACHE_WARNING_CATEGORY: "Cache Warning",
    CACHE_ADVISORY_CATEGORY: "Cache Advisory",
}


# ---------------------------------------------------------------------------
# Dry-run nudge — locked text format with explicit pluralization
# ---------------------------------------------------------------------------


def format_dry_run_nudge(
    *,
    opportunity_count: int,
    savings_usd: float | None,
    savings_pct: int | None,
) -> str:
    """Format the spec-locked dry-run nudge text per § "—dry-run Cache Nudge".

    When ``savings_usd`` or ``savings_pct`` is ``None``, drop the dollar figure
    rather than emit a misleading ``-$0.00/run, -0%``. Mirrors the cost
    tri-state rule in ``render_text._format_cost``: ``None`` means
    "unavailable", never "zero".
    """
    word = "opportunity" if opportunity_count == 1 else "opportunities"
    if savings_usd is None:
        return f"Cache: {opportunity_count} design {word} available."
    if savings_pct is None:
        return f"Cache: {opportunity_count} design {word} available (estimated -${savings_usd:.2f}/run)."
    return f"Cache: {opportunity_count} design {word} available (estimated -${savings_usd:.2f}/run, -{savings_pct}%)."


__all__ = [
    "CACHE_DISCREPANCY_ACTION_PAYLOAD_KEYS",
    "CACHE_DISCREPANCY_ACTION_TEMPLATES",
    "CACHE_DISCREPANCY_REQUIRED_CONTEXT",
    "CACHE_OPPORTUNITIES_NUDGE_ID",
    "CACHE_WARNING_CATALOG",
    "EXPECTED_CATALOG_COUNT",
    "CacheWarningSpec",
    "format_dry_run_nudge",
    "make_diagnostic",
]
