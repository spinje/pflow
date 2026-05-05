"""Closed catalog of warning IDs and the ``make_diagnostic`` helper.

The catalog is the agent-facing contract: each entry pins severity, source,
category, and the message / suggestions / path templates so emitted Diagnostics
have stable shape regardless of which call site builds them. Per Task 159
DD#29, the catalog is closed in v1 — adding new IDs goes through design review.

17 entries: 14 ``cache.*`` from v1 + ``cache.prompt-body-duplicates-cache`` and
``cache.prompt-body-shadows-cache`` (Task 159 follow-up: detect prompt-body /
prompt_cache overlap that silently nullifies declared caching) + ``llm.thinking-
temperature-mismatch`` (Stage 2 follow-up: catch Anthropic temperature=1.0 +
extended thinking constraint at validate-time). The base 14 covers the 9 from
spec § "Stable Warning ID Catalog" + ``cache.discrepancy`` (Round 2, dispatch
over ``root_cause`` enum), ``cache.invalid-on-non-llm`` (Round 3, validator-
reach gap closure for non-LLM nodes), ``cache.prewarm-no-prefix`` (Round 3,
prewarm-without-static-prefix advisory), ``cache.consolidate-to-root-
recommended`` (CP3, sub-paths below threshold that would cross when
consolidated to the parent dict), and ``cache.opaque-prompt`` (Stage-1.5, LLM
nodes whose prompt is a single var-ref to a ``type: code`` node — opaque to
static analysis).

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
    LLM_VALIDATION_CATEGORY,
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

    ``headline_template`` is the short action-led title used by
    ``analyze-cache`` text rendering (Recommended actions + Sub-workflow
    boundaries). Pattern: ``"<category> — <action>"`` (rustc-style: fixed
    title per ID + per-instance specifics). When empty, the renderer falls
    back to ``message`` truncated to first sentence. Catalog-driven so per-id
    headline policy lives in one SSoT — no scattered renderer if/elif logic.
    """

    severity: Severity
    source: str
    category: str
    message_template: str
    required_context_keys: tuple[tuple[str, type], ...]
    suggestions_template: tuple[str, ...]
    path_template: str
    nullable_cost_keys: frozenset[str] = frozenset()
    headline_template: str = ""
    # Routes the rendered "See also: pflow guide X" hint per entry. Defaults
    # to ``("caching",)`` because the catalog is historically cache-scoped;
    # entries pointing elsewhere (e.g. the ``llm.*`` thinking-temperature
    # check) override.
    see_also: tuple[str, ...] = ("caching",)


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


# cache.shared-context-undeclared has two distinct emission contexts that
# warrant different prose (CP5 #1+#5):
#
#   - WORKFLOW scope (node_id=None, no ``child_workflow`` key): the analyzer
#     detected a value used by N≥2 LLM nodes inside this workflow. The fix is
#     to declare the value in this workflow's ## Cache block.
#
#   - BOUNDARY scope (``child_workflow`` set in context): the value flows into
#     one or more sub-workflows via ``type: workflow`` nodes. Stage B.1 collapses
#     per-edge findings into per-(parent_workflow, value_root) groups; the
#     destinations list carries one entry per child workflow. The boundary form
#     is further dispatched on ``destination_count`` to produce SINGLE vs MULTI
#     prose: 1-destination cases name BOTH parent and child as valid declaration
#     sites; multi-destination cases recommend declaring in the parent (one edit
#     covers N destinations).
#
# All templates use ``{savings_clause}`` for the optional parenthetical so
# ``None`` savings produces grammatical output (no "saves savings unavailable/run").
_SHARED_CONTEXT_WORKFLOW_TEMPLATE = "Used by {node_count} LLM nodes. Chunks: {shared_chunks_csv}.{savings_clause}"
_SHARED_CONTEXT_BOUNDARY_TEMPLATE_SINGLE = (
    "`{value_root}` flows to `{child_workflow_basename}` "
    "(used by {child_consumer_count} LLM nodes there). Declare it in either "
    "workflow's ## Cache to share cached bytes across the boundary."
    "{savings_clause}"
)
_SHARED_CONTEXT_BOUNDARY_TEMPLATE_MULTI = (
    "`{value_root}` flows to {destination_count} sub-workflows. "
    "{distribution_clause} Declare in this workflow's ## Cache to cover all "
    "destinations in one edit.{savings_clause}"
)


# Headline templates — short action-led titles for analyze-cache text output.
# Per-id, catalog-driven; the renderer reads these without knowing the IDs.
# Boundary headline dispatches on destination_count (SINGLE vs MULTI) to match
# the message dispatch — single-destination preserves "either side" framing
# (declaring on the child is equally valid); multi-destination recommends the
# parent because that's the single edit unlocking N destinations.
_SHARED_CONTEXT_WORKFLOW_HEADLINE = "Shared context undeclared — declare {shared_chunks_short} in ## Cache"
_SHARED_CONTEXT_BOUNDARY_HEADLINE_SINGLE = (
    "Cross-boundary value undeclared — declare `{value_root}` in "
    "{parent_workflow_basename}'s or {child_workflow_basename}'s ## Cache"
)
_SHARED_CONTEXT_BOUNDARY_HEADLINE_MULTI = (
    "Cross-boundary value undeclared — declare `{value_root}` in "
    "{parent_workflow_basename}'s ## Cache (covers {destination_count} sub-workflows)"
)


def _basename_for_workflow(path: str) -> str:
    """Strip directory components for compact rendering. Non-paths pass through."""
    return path.rsplit("/", 1)[-1] if "/" in path else path


def _compute_distribution_clause(destinations: list[dict[str, Any]]) -> str:
    """Return a fact-dense per-destination breakdown for the multi-destination boundary message.

    Uniform case (all destinations have the same node_count): renders as
    ``"Used by {N} LLM nodes per destination ({csv})."`` so the agent doesn't
    have to mentally parse a sum.

    Non-uniform: renders as ``"Used by {total} LLM nodes ({per-dest breakdown})."``
    Per-agent-ux Finding 2: aggregate alone hides distribution; the agent can't
    tell whether 18 = 6+6+6 or 16+1+1 without the breakdown.
    """
    if not destinations:
        return ""
    counts = [int(d.get("node_count", 0)) for d in destinations]
    basenames = [str(d.get("child_workflow_basename", "")) for d in destinations]
    csv = ", ".join(basenames)
    total = sum(counts)
    # Uniform when all counts equal AND > 0 (zero-count is degenerate; pre-suppression should catch it).
    if counts and all(c == counts[0] for c in counts) and counts[0] > 0:
        noun = "node" if counts[0] == 1 else "nodes"
        return f"Used by {counts[0]} LLM {noun} per destination ({csv})."
    breakdown = ", ".join(f"{name}: {count}" for name, count in zip(basenames, counts, strict=True))
    total_noun = "node" if total == 1 else "nodes"
    return f"Used by {total} LLM {total_noun} ({breakdown})."


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
        # ERRORs render through diagnostic_render.py with title `[id]` next to
        # the title. analyze-cache's recommendations section sees ERRORs too
        # (after A.6 wired validator findings into analyze output) — the
        # headline shows there.
        headline_template="`prompt_cache:` order mismatch on {node_id}",
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
        headline_template="Unused cache chunk — remove `{chunk_name}` from ## Cache",
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
        headline_template="Cache field on non-LLM node — remove {invalid_fields_csv} from {node_id}",
    ),
    # === Analytical tier (emitted by analyze-cache / --dry-run only) ===
    "cache.shared-context-undeclared": CacheWarningSpec(
        severity=Severity.INFO,
        source="cache_analyzer",
        category=CACHE_ADVISORY_CATEGORY,
        # Dispatched on context: workflow scope (default) vs boundary scope
        # (when ``child_workflow`` is present in context). The placeholder here
        # is replaced at make_diagnostic time — see ``_dispatch_shared_context``.
        # Two distinct sentences are needed because workflow-internal sharing
        # and cross-boundary value flow have different remediation paths.
        # Headline is also dispatched (see ``_select_headline_template``).
        message_template=_SHARED_CONTEXT_WORKFLOW_TEMPLATE,
        required_context_keys=(
            ("node_count", int),
            ("shared_chunks", list),
            ("affected_workflow", str),
            ("savings_usd", float),
        ),
        suggestions_template=(
            "Paste the suggested ## Cache block (see 'Suggested ## Cache block' section) into {affected_workflow}.",
            "Per-node `prompt_cache:` assignments are listed in the same section.",
        ),
        path_template="workflows[path={affected_workflow}]",
        nullable_cost_keys=frozenset({"savings_usd"}),
        headline_template=_SHARED_CONTEXT_WORKFLOW_HEADLINE,
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
            "Add `- prewarm: true` to {node_id} to opt in.{savings_clause}",
            "OR add `- prewarm: false` to {node_id} to opt out explicitly (suppresses this warning).",
        ),
        path_template="nodes[id={node_id}]",
        nullable_cost_keys=frozenset({"savings_usd"}),
        headline_template="Batch prewarm not declared — add `- prewarm: true` to {node_id}",
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
        headline_template="Dynamic ref blocks caching on {node_id} — move `${{{dynamic_ref}}}` after stable content",
    ),
    "cache.padding-advisory": CacheWarningSpec(
        severity=Severity.INFO,
        source="cache_analyzer",
        category=CACHE_ADVISORY_CATEGORY,
        message_template=(
            "{node_id}: `prompt_cache:` subset doesn't start at position 1 of the "
            "## Cache declaration. Extending it to {suggested_subset} would let this "
            "node hit cached writes from upstream nodes at 0.1× input cost.{savings_clause}"
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
        headline_template="Padding advisory — extend `prompt_cache:` on {node_id} to hit upstream cache",
    ),
    # When Task 94 (Display Available LLM Models) ships, extend the suggestion
    # below to reference `pflow llm list --min-cache-tokens=<N>` so agents can
    # pivot from "this model can't cache my content" to "here are models that
    # can." See .taskmaster/tasks/task_94/research/cache-threshold-cross-reference-from-task-159.md
    # for design rationale and the bidirectional cross-reference plan.
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
        headline_template="Cache content below provider minimum on {node_id}",
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
        headline_template="Cross-workflow prose mismatch — align `{chunk_name}` in both ## Cache blocks",
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
        headline_template="Cross-workflow rename — `{parent_value_expr}` ↔ `{child_input_name}`",
    ),
    "cache.discrepancy": CacheWarningSpec(
        severity=Severity.INFO,
        source="cache_analyzer",
        category=CACHE_ADVISORY_CATEGORY,
        # ``predicted_label`` distinguishes "hit" (predicted_key == actual_key),
        # "hit (bytes diverged at runtime)" (planner expected a hit; trace's
        # cache_key didn't match), and "miss" (no predicted_key). Bug F fix:
        # the prior template "predicted hit_ratio {predicted_pct}%" implied we
        # MEASURED a hit ratio, but ``predicted_pct`` is binary (100 if planner
        # produced a cache_key, 0 otherwise) — different concept from the
        # actual measured hit ratio. ``predicted_pct`` stays in the context
        # for JSON consumers that read raw values; the rendered message uses
        # the explicit label.
        message_template=(
            "{node_id} in {workflow_path_short} (trace: {trace_path}): predicted {predicted_label}, "
            "actual {actual_pct}% read — root cause: {root_cause_summary}"
        ),
        required_context_keys=(
            ("node_id", str),
            ("trace_path", str),
            ("workflow_path_short", str),
            ("predicted_pct", int),
            ("predicted_label", str),
            ("actual_pct", int),
            ("root_cause", str),
            ("root_cause_summary", str),
        ),
        suggestions_template=(),  # DISPATCHED on root_cause — see CACHE_DISCREPANCY_*
        path_template="nodes[id={node_id}]",
        nullable_cost_keys=frozenset({"cache_age_sec", "predicted_cache_key", "actual_cache_key"}),
        headline_template="Cache hit discrepancy on {node_id} — {root_cause_summary}",
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
        headline_template="Prewarm has no static prefix on {node_id}",
    ),
    "cache.consolidate-to-root-recommended": CacheWarningSpec(
        severity=Severity.INFO,
        source="cache_analyzer",
        category=CACHE_ADVISORY_CATEGORY,
        message_template=(
            "Sub-paths of `{root}` ({sub_paths_csv}) are individually below "
            "{model}'s min-cache threshold ({min_tokens} tokens, max sub-path "
            "~{max_subpath_tokens}); consolidating to `${{{root}}}` (~{root_tokens} "
            "tokens) would cross the threshold and actually cache. Sub-path "
            "markers silently no-op at the provider as declared."
        ),
        required_context_keys=(
            ("root", str),
            ("sub_paths", list),
            ("model", str),
            ("min_tokens", int),
            ("max_subpath_tokens", int),
            ("root_tokens", int),
            ("affected_workflow", str),
        ),
        suggestions_template=(
            "Replace [{sub_paths_csv}] with [{root}] in the ## Cache block and in "
            "every node's `prompt_cache:` list that currently references any of "
            "those sub-paths. Trade-off: each call sends the entire `{root}` "
            "value (~{root_tokens} tokens) instead of just the sub-paths it "
            "references; cache write costs 1.25× input rate, reads cost 0.1×, "
            "so consolidation pays off after the first read.",
        ),
        path_template="workflows[path={affected_workflow}]",
        headline_template="Consolidate sub-paths of `{root}` to root in ## Cache",
    ),
    "cache.opaque-prompt": CacheWarningSpec(
        severity=Severity.INFO,
        source="cache_analyzer",
        category=CACHE_ADVISORY_CATEGORY,
        # Fires when an LLM node's prompt is a single var-ref (e.g. ``${X}``)
        # whose ultimate source is a ``type: code`` node. Static walkers
        # (cache.dynamic-before-static, cache.batch-prewarm-recommended,
        # cache.shared-context-undeclared) read the literal IR template and
        # see only one ref — even when the assembled prompt has substantial
        # cache potential. The fix is structural: refactor to an inline
        # declarative prompt so static walkers can inspect it.
        message_template=(
            "{node_id}: prompt is `${{{var_ref}}}`, assembled by `{upstream_node_id}` "
            "(type: code). Static analysis cannot inspect the assembled prompt's "
            "structure, so cache opportunities (shared prefixes, prewarm) are not "
            "detected. If the assembled prompt has a stable prefix and per-call "
            "dynamic content, refactoring to an inline declarative prompt unlocks "
            "detection."
        ),
        required_context_keys=(
            ("node_id", str),
            ("var_ref", str),
            ("upstream_node_id", str),
        ),
        suggestions_template=(
            "Inline the prompt template on `{node_id}`: replace `${{{var_ref}}}` "
            "with the literal prompt content, with stable bytes BEFORE per-call "
            "dynamic references.",
            "See `pflow guide caching` (Python-assembled prompts section) for the refactor pattern.",
        ),
        path_template="nodes[id={node_id}].prompt",
        headline_template=("Prompt opaque to static analysis on {node_id} — refactor inline for cache detection"),
    ),
    # Validator-tier: prompt body duplicates a cached chunk path-for-path.
    # Net effect of the duplication: cache stores the value at 0.1x rate but
    # the prompt body still sends it at 1.0x every call — savings ~zero. The
    # rendered message lists each ``(chunk → body_ref)`` pair on its own line
    # so multi-overlap nodes show every duplicate at a glance. Consolidated-
    # per-node shape mirrors ``cache.invalid-on-non-llm`` (data_flow.py:702):
    # each node emits ONE diagnostic listing ALL duplicates, not N of them
    # (``Diagnostic.__hash__`` would otherwise collapse repeats and lose
    # detail).
    "cache.prompt-body-duplicates-cache": CacheWarningSpec(
        severity=Severity.ERROR,
        source="validator",
        category=CACHE_FAILURE_CATEGORY,
        message_template=(
            "Node '{node_id}' duplicates cached chunks in the prompt body — the cache "
            "stores these values at 0.1× rate but the body sends them inline at 1.0× "
            "every call:\n{overlap_lines}"
        ),
        required_context_keys=(
            ("node_id", str),
            ("overlapping_pairs", list),
            ("affected_workflow", str),
            ("overlap_lines", str),
        ),
        suggestions_template=(
            "Remove the listed `${{...}}` references from the prompt body — the cached "
            "chunks already supply these values via the system prompt.",
        ),
        path_template="nodes[id={node_id}].params.prompt",
        headline_template="Prompt body duplicates cached chunks on {node_id}",
    ),
    # Validator-tier: prompt body and cache chunk overlap on a sub-path
    # (either direction). Warning rather than error: there are legitimate
    # patterns (e.g. cache the parent dict, use selected sub-paths inline)
    # but the typical case is mistaken duplication. Consolidated per node
    # for the same reason as the duplicates ID.
    "cache.prompt-body-shadows-cache": CacheWarningSpec(
        severity=Severity.WARNING,
        source="validator",
        category=CACHE_WARNING_CATEGORY,
        message_template=(
            "Node '{node_id}' has overlapping cached chunks and prompt-body refs (sub-path overlap):\n{overlap_lines}"
        ),
        required_context_keys=(
            ("node_id", str),
            ("shadowing_pairs", list),
            ("affected_workflow", str),
            ("overlap_lines", str),
        ),
        suggestions_template=(
            "Either narrow the cached chunks to only the sub-paths the body uses, OR "
            "remove the listed `${{...}}` references from the prompt body. Sub-path "
            "overlap can quietly inflate input tokens without firing the cache reliably.",
        ),
        path_template="nodes[id={node_id}].params.prompt",
        headline_template="Prompt body shadows cached chunks on {node_id}",
    ),
    # Validator-tier: Anthropic API requires temperature=1.0 whenever extended
    # thinking is enabled. Workflows that combine ``reasoning_effort`` (which
    # pflow translates to ``thinking: enabled`` for Anthropic models) with a
    # declared ``temperature`` other than 1.0 are guaranteed to fail at runtime
    # with ``BadRequestError: temperature may only be set to 1 when thinking
    # is enabled``. Empirically verified across Opus 4.1/4.5/4.7, Sonnet
    # 4.5/4.6, Haiku 4.5 (uniform behavior — Anthropic treats this as a single
    # API rule across the extended-thinking model family).
    #
    # Why namespaced ``llm.*`` rather than ``cache.*``: this isn't a cache rule;
    # the catalog has historically held cache.* IDs but the dispatch
    # infrastructure (Diagnostic, make_diagnostic, render pipeline) is general.
    # Mixing one ``llm.*`` ID into the existing catalog is preferable to
    # building a parallel catalog for one entry.
    "llm.thinking-temperature-mismatch": CacheWarningSpec(
        severity=Severity.ERROR,
        source="validator",
        category=LLM_VALIDATION_CATEGORY,
        message_template=(
            "Node '{node_id}': temperature {temperature} conflicts with "
            "reasoning_effort '{reasoning_effort}' on model {model} — "
            "Anthropic requires temperature=1.0 when extended thinking is enabled."
        ),
        required_context_keys=(
            ("node_id", str),
            ("model", str),
            ("reasoning_effort", str),
            ("temperature", float),
            ("affected_workflow", str),
        ),
        suggestions_template=(
            "Set `temperature: 1.0` on `{node_id}` (recommended for thinking-enabled calls), OR",
            "Set `reasoning_effort: none` on `{node_id}` to disable thinking and keep your declared temperature.",
        ),
        path_template="nodes[id={node_id}].params.temperature",
        headline_template="Temperature conflicts with reasoning_effort on {node_id}",
        see_also=("llm",),
    ),
}


# Auto-derived count constant — defends against drift across docstrings,
# tests, and MCP schemas. Adding a new ID requires zero count-update edits.
EXPECTED_CATALOG_COUNT: Final[int] = len(CACHE_WARNING_CATALOG)


# ---------------------------------------------------------------------------
# Recommended-actions sort priority
#
# When two warnings share severity AND ``savings_usd`` is unavailable for both
# (the common greenfield case), the natural alphabetical tie-break buries
# actionable findings (``cache.shared-context-undeclared`` — sorts later
# alphabetically) under informational ones (``cache.cross-workflow-rename-
# detected`` — sorts earlier). This dict gives an explicit detection-class
# priority so agents reading the "Recommended actions" section see real
# opportunities first.
#
# Lower number = higher priority (sorts earlier in recommended-actions).
# Co-located with the catalog (this file is the SSoT for catalog metadata)
# so future contributors adding a new ID see the priority table inline.
# Updates go through the same DD#29 review as adding catalog entries.
# Unknown IDs default to ``DEFAULT_RECOMMENDED_ACTION_PRIORITY`` (lowest).
# ---------------------------------------------------------------------------


DEFAULT_RECOMMENDED_ACTION_PRIORITY: Final[int] = 100


RECOMMENDED_ACTION_PRIORITY: dict[str, int] = {
    # Tier 1 — actionable opportunities with concrete suggestions agents can apply.
    "cache.shared-context-undeclared": 10,
    "cache.dynamic-before-static": 10,
    "cache.batch-prewarm-recommended": 10,
    # Tier 2 — discrepancy attribution (only fires with trace; usually high-value).
    "cache.discrepancy": 15,
    # Tier 3 — advisories grounded in current state.
    "cache.padding-advisory": 20,
    # Tier 4 — structural problems (ERROR severity already wins via sev_weight;
    # priority here is belt-and-suspenders for ordering ERRORs among themselves).
    "cache.order-mismatch": 5,
    "cache.invalid-on-non-llm": 5,
    "cache.prompt-body-duplicates-cache": 5,
    "llm.thinking-temperature-mismatch": 5,
    # Sub-path shadow is WARNING but more actionable than cache.unused-chunk —
    # it silently nullifies a cache decision the user explicitly made.
    "cache.prompt-body-shadows-cache": 10,
    # Tier 5 — informational warnings that surface latent issues.
    "cache.unused-chunk": 30,
    "cache.below-min-tokens": 30,
    "cache.prewarm-no-prefix": 30,
    "cache.consolidate-to-root-recommended": 30,
    "cache.opaque-prompt": 30,
    # Tier 6 — cross-workflow alignment (informational; no concrete savings).
    "cache.cross-workflow-prose-mismatch": 50,
    "cache.cross-workflow-rename-detected": 50,
}


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
    """Format ``savings_usd`` for inline message rendering with adaptive
    sub-cent precision. Mirrors ``render_text._format_savings_usd``.

    - ``None`` → ``"savings unavailable"``.
    - ``< $0.0001`` → ``"savings unavailable"`` (below display precision).
    - ``$0.0001 ≤ value < $0.01`` → ``"-$0.0012"`` (4 decimals).
    - ``≥ $0.01`` → ``"-$0.42"`` (2 decimals).
    """
    if savings_usd is None:
        return "savings unavailable"
    try:
        amount = float(savings_usd)
    except (TypeError, ValueError):
        return "savings unavailable"
    if amount < 0.0001:
        return "savings unavailable"
    if amount < 0.01:
        return f"-${amount:.4f}"
    return f"-${amount:.2f}"


def _format_chunks_short(chunks: Any, *, max_inline: int = 2) -> str:
    """Compact headline-friendly chunk list. ``max_inline+1`` items use ``+N more``.

    ``["concept"]`` → ``"`concept`"``
    ``["concept", "concept_brief"]`` → ``"`concept`, `concept_brief`"``
    ``["concept", "concept_brief", "x"]`` → ``"`concept`, `concept_brief` +1 more"``
    """
    if not chunks:
        return ""
    items = [str(c) for c in chunks]
    if len(items) <= max_inline:
        return ", ".join(f"`{c}`" for c in items)
    head = ", ".join(f"`{c}`" for c in items[:max_inline])
    return f"{head} +{len(items) - max_inline} more"


def _format_savings_clause(savings_usd: Any) -> str:
    """Render the parenthetical ``" (saves $X.XX/run)"`` clause, or empty string.

    Used by message templates that want to APPEND a savings hint inline.
    Adaptive sub-cent precision matches ``_format_savings`` /
    ``render_text._format_savings_usd``:

    - ``None`` → ``""`` (silent — keeps surrounding wording grammatical).
    - ``< $0.0001`` → ``""`` (silent — below display precision).
    - ``$0.0001 ≤ value < $0.01`` → ``" (saves $0.0012/run)"`` (4 decimals).
    - ``≥ $0.01`` → ``" (saves $0.42/run)"`` (2 decimals).
    """
    if savings_usd is None:
        return ""
    try:
        amount = float(savings_usd)
    except (TypeError, ValueError):
        return ""
    if amount < 0.0001:
        return ""
    if amount < 0.01:
        return f" (saves ${amount:.4f}/run)"
    return f" (saves ${amount:.2f}/run)"


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
    _ensure_discrepancy_workflow_scope(warning_id, context_kwargs)
    _validate_required(spec, context_kwargs, node_id, warning_id)
    _ensure_workflow_scope(warning_id, node_id, context_kwargs)

    # Format-dict merges node_id (helper kwarg) with all context kwargs so
    # message / suggestions / path templates can reference {node_id}.
    format_dict: dict[str, Any] = {**context_kwargs, "node_id": node_id}

    # Some templates use {savings_str} as a typed alias of savings_usd that
    # gracefully degrades on None. Compute on demand.
    if "savings_usd" in context_kwargs:
        format_dict["savings_str"] = _format_savings(context_kwargs["savings_usd"])
        # ``savings_clause`` is the inline-parenthetical form that templates can
        # append without producing the broken ``"saves savings unavailable/run"``
        # artifact when savings_usd is None/sub-cent. Templates use one or the
        # other depending on whether they want the bare amount (savings_str) or
        # the full parenthetical (savings_clause).
        format_dict["savings_clause"] = _format_savings_clause(context_kwargs["savings_usd"])

    # ``shared_chunks_csv`` is a typed alias of ``shared_chunks`` (list) so
    # message templates can render the discriminator without duplicating the
    # join logic at every emission site. Without this, ``cache.shared-context-
    # undeclared`` rendered three identical lines on lyrics-generator
    # song-creator (one per cross-workflow boundary) — agents couldn't tell
    # which chunk each line was about.
    #
    # ``shared_chunks_short`` is the headline-friendly compact form: keeps the
    # first 2 chunks inline, then ``+N more`` for the rest. Long lists wrap
    # awkwardly in the rank-line header; the full list still appears in the
    # message body via ``shared_chunks_csv``.
    if "shared_chunks" in context_kwargs:
        chunks = context_kwargs["shared_chunks"]
        format_dict["shared_chunks_csv"] = ", ".join(str(c) for c in chunks) if chunks else ""
        format_dict["shared_chunks_short"] = _format_chunks_short(chunks)

    # ``sub_paths_csv`` mirrors ``shared_chunks_csv`` for the consolidate-to-root
    # advisory. Same join-free pattern; same passthrough-to-context fidelity.
    if "sub_paths" in context_kwargs:
        sub_paths = context_kwargs["sub_paths"]
        format_dict["sub_paths_csv"] = ", ".join(str(p) for p in sub_paths) if sub_paths else ""

    # cache.invalid-on-non-llm: provide the lowercase form matching the
    # shipped data_flow.py emitter (lowercase 'this'/'these'). Synced with
    # _make_invalid_on_non_llm_diagnostic at data_flow.py:719 — drift between
    # the two would produce non-byte-equivalent messages for the same finding.
    if "is_or_are" in context_kwargs:
        format_dict["is_or_are_capitalized"] = (
            "this field is" if context_kwargs["is_or_are"] == "is" else "these fields are"
        )

    # cache.shared-context-undeclared: select boundary template when
    # ``child_workflow`` is set in context. Stage B.1 (Task 159) collapses
    # per-edge findings into per-(parent_workflow, value_root) groups; the
    # boundary form is further dispatched on ``destination_count`` (number
    # of sub-workflows the value flows to):
    #
    #   - SINGLE (destination_count == 1): name BOTH parent and child as valid
    #     declaration sites. Declaring on the child is equally valid (and
    #     sometimes preferable when the child is the canonical owner).
    #   - MULTI (destination_count >= 2): recommend declaring in the parent
    #     because that's the single edit unlocking N destinations.
    #
    # Workflow-scope emission (no ``child_workflow`` in context) gets the
    # straight workflow template.
    selected_message_template = spec.message_template
    if warning_id == "cache.shared-context-undeclared" and "child_workflow" in context_kwargs:
        destinations = context_kwargs.get("destinations") or []
        destination_count = int(context_kwargs.get("destination_count", len(destinations) or 1))
        # Parent basename for both branches (used by SINGLE headline + MULTI message).
        parent_workflow = str(context_kwargs.get("affected_workflow", ""))
        format_dict["parent_workflow_basename"] = _basename_for_workflow(parent_workflow)
        if destination_count == 1:
            selected_message_template = _SHARED_CONTEXT_BOUNDARY_TEMPLATE_SINGLE
            # Single destination: pull child basename + consumer count from
            # destinations[0] when present, else fall back to context's
            # child_workflow path. Pre-Stage-B.1 callers (or future per-edge
            # paths) that don't pass destinations still produce sensible output.
            if destinations:
                d0 = destinations[0]
                format_dict["child_workflow_basename"] = str(d0.get("child_workflow_basename", ""))
                format_dict["child_consumer_count"] = int(d0.get("node_count", 0))
            else:
                child_path = str(context_kwargs["child_workflow"])
                format_dict["child_workflow_basename"] = _basename_for_workflow(child_path)
                # Fall back to node_count (the validator-required key) when
                # destinations isn't carried — symmetric with old per-edge form.
                format_dict["child_consumer_count"] = int(context_kwargs.get("node_count", 0))
        else:
            selected_message_template = _SHARED_CONTEXT_BOUNDARY_TEMPLATE_MULTI
            format_dict["destination_count"] = destination_count
            format_dict["child_workflows_csv"] = ", ".join(
                str(d.get("child_workflow_basename", "")) for d in destinations
            )
            format_dict["total_consumer_count"] = int(
                context_kwargs.get("total_consumer_count", context_kwargs.get("node_count", 0))
            )
            format_dict["distribution_clause"] = _compute_distribution_clause(destinations)

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
        message = selected_message_template.format(**format_dict)
        suggestions = [s.format(**format_dict) for s in spec.suggestions_template]
        path = spec.path_template.format(**format_dict)
        context = dict(context_kwargs)
        context["category"] = spec.category
        context["path"] = path

    # Headline rendering is now sourced via ``resolve_headline_for(diag)`` at
    # render time (catalog-as-SSoT). The make_diagnostic path no longer writes
    # ``context["headline"]`` — keeping the catalog as the single source of
    # truth means validator-emitted diagnostics (built via raw Diagnostic(...)
    # in data_flow.py, NOT via this helper) get headlines too. See
    # ``resolve_headline_for`` below for the lookup logic.

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
        see_also=list(spec.see_also),
    )


def _ensure_discrepancy_workflow_scope(warning_id: str, context_kwargs: dict[str, Any]) -> None:
    """Backfill ``workflow_path_short`` for ``cache.discrepancy`` from ``affected_workflow``.

    The workflow-scope contract (``_ensure_workflow_scope``) guarantees
    ``affected_workflow`` is present whenever ``node_id`` is, and production
    ``cache.discrepancy`` always carries both. The catalog's
    ``required_context_keys`` for ``cache.discrepancy`` includes
    ``workflow_path_short``; this helper derives it from ``affected_workflow``
    so callers don't have to thread two redundant keys.
    """
    if warning_id != "cache.discrepancy" or "workflow_path_short" in context_kwargs:
        return
    affected_workflow = context_kwargs.get("affected_workflow")
    if affected_workflow is None:
        return
    context_kwargs["workflow_path_short"] = _basename_for_workflow(str(affected_workflow))


def _ensure_workflow_scope(warning_id: str, node_id: str | None, context_kwargs: dict[str, Any]) -> None:
    """Workflow-scope contract: any cache.* diagnostic carrying a node_id must
    also carry the workflow_path that node_id is scoped to.

    Same node id can appear in parent and child workflows; without
    ``affected_workflow`` the renderer would key warnings against the wrong
    row. Producers in ``analyze.py`` thread ``ctx.workflow_path`` directly;
    tests must do the same. Top-10% codebases enforce workflow-scope at the
    producer boundary, not in renderer fallbacks.
    """
    if node_id is None:
        return
    affected = context_kwargs.get("affected_workflow")
    if isinstance(affected, str) and affected:
        return
    raise KeyError(
        f"make_diagnostic({warning_id!r}, node_id={node_id!r}) is missing required key 'affected_workflow'. "
        "Pass the workflow_path the node belongs to so the renderer can scope per-row warnings correctly."
    )


# Category → title mapping mirrors core.diagnostic.CATEGORY_TITLES.
_CATEGORY_TITLE: Final[dict[str, str]] = {
    CACHE_FAILURE_CATEGORY: "Cache Failure",
    CACHE_WARNING_CATEGORY: "Cache Warning",
    CACHE_ADVISORY_CATEGORY: "Cache Advisory",
    LLM_VALIDATION_CATEGORY: "LLM Configuration",
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

    Tri-state savings contract with adaptive sub-cent precision (mirrors
    ``render_text._format_savings_usd`` /
    ``warning_catalog._format_savings``):

    - ``None`` → drop the dollar figure entirely (genuinely unknown).
    - ``< $0.0001`` → drop the dollar figure entirely (below display
      precision; rendering ``-$0.0000/run`` would imply "we computed it,
      it's zero" when it's too small to surface).
    - ``$0.0001 ≤ value < $0.01`` → render with 4 decimals
      (``-$0.0012/run`` — Gemini-shaped sub-cent visibility).
    - ``≥ $0.01`` → render with 2 decimals (``-$0.42/run``).
    """
    word = "opportunity" if opportunity_count == 1 else "opportunities"
    if savings_usd is None or savings_usd < 0.0001:
        return f"Cache: {opportunity_count} design {word} available."
    amount_str = f"-${savings_usd:.4f}/run" if savings_usd < 0.01 else f"-${savings_usd:.2f}/run"
    if savings_pct is None:
        return f"Cache: {opportunity_count} design {word} available (estimated {amount_str})."
    return f"Cache: {opportunity_count} design {word} available (estimated {amount_str}, -{savings_pct}%)."


# ---------------------------------------------------------------------------
# Headline resolution — catalog-as-SSoT for analyze-cache rendering.
# ---------------------------------------------------------------------------


def resolve_headline_for(diag: Diagnostic) -> str:
    """Format the catalog's ``headline_template`` for a Diagnostic.

    Returns an empty string when the diagnostic has no headline (non-cache
    diagnostic, catalog row without a headline_template, or a formatting
    error). Catalog-as-SSoT: this works regardless of HOW the Diagnostic was
    constructed — both ``make_diagnostic`` (cache_analyzer-emitted) and raw
    ``Diagnostic(...)`` (validator-emitted in ``data_flow.py``) get headlines.

    Dispatches the boundary headline for ``cache.shared-context-undeclared``
    when ``context["child_workflow"]`` is present (mirrors the message
    dispatch in ``make_diagnostic``).

    Used by ``analyze.py:_build_recommended_actions`` for the rank line and
    by ``render_text.py:_format_boundary_finding`` for the cross-workflow
    findings. Both consumers in the same package layer.
    """
    if not diag.id or diag.id not in CACHE_WARNING_CATALOG:
        return ""
    spec = CACHE_WARNING_CATALOG[diag.id]
    if not spec.headline_template:
        return ""
    ctx = dict(diag.context or {})
    if diag.node_id is not None:
        ctx.setdefault("node_id", diag.node_id)

    template = spec.headline_template
    if diag.id == "cache.shared-context-undeclared" and "child_workflow" in ctx:
        # Mirror the message dispatch in ``make_diagnostic``: boundary headline
        # is dispatched on destination_count. SINGLE names both workflows;
        # MULTI commits to the parent + advertises the destination count.
        destinations = ctx.get("destinations") or []
        destination_count = int(ctx.get("destination_count", len(destinations) or 1))
        parent_workflow = str(ctx.get("affected_workflow", ""))
        ctx["parent_workflow_basename"] = _basename_for_workflow(parent_workflow)
        if destination_count == 1:
            template = _SHARED_CONTEXT_BOUNDARY_HEADLINE_SINGLE
            if destinations:
                ctx["child_workflow_basename"] = str(destinations[0].get("child_workflow_basename", ""))
            else:
                child_path = str(ctx["child_workflow"])
                ctx["child_workflow_basename"] = _basename_for_workflow(child_path)
        else:
            template = _SHARED_CONTEXT_BOUNDARY_HEADLINE_MULTI
            ctx["destination_count"] = destination_count

    # Mirror make_diagnostic's typed-alias derivations so headline templates
    # can use the same placeholders. ``shared_chunks_short`` only matters for
    # cache.shared-context-undeclared; cheap unconditional derivation.
    if "shared_chunks" in ctx:
        ctx.setdefault("shared_chunks_short", _format_chunks_short(ctx["shared_chunks"]))

    try:
        return template.format(**ctx)
    except (KeyError, IndexError) as exc:
        # Defense-in-depth: catalog drift could leave a template referencing
        # a placeholder the diagnostic doesn't carry. Log + return empty so
        # the renderer falls back to message-led shape rather than raising
        # in the rendering hot path.
        logger.debug("Headline template formatting failed for %s: %s", diag.id, exc)
        return ""


__all__ = [
    "CACHE_DISCREPANCY_ACTION_PAYLOAD_KEYS",
    "CACHE_DISCREPANCY_ACTION_TEMPLATES",
    "CACHE_DISCREPANCY_REQUIRED_CONTEXT",
    "CACHE_OPPORTUNITIES_NUDGE_ID",
    "CACHE_WARNING_CATALOG",
    "DEFAULT_RECOMMENDED_ACTION_PRIORITY",
    "EXPECTED_CATALOG_COUNT",
    "RECOMMENDED_ACTION_PRIORITY",
    "CacheWarningSpec",
    "format_dry_run_nudge",
    "make_diagnostic",
    "resolve_headline_for",
]
