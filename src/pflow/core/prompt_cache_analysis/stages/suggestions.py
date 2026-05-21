"""Suggested prompt-cache edits and pricing helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from pflow.core.cache_ttl import parse_cache_ttl
from pflow.core.diagnostic import Diagnostic
from pflow.core.llm_capabilities import get_min_cache_tokens
from pflow.core.prompt_refs import classify_prompt_refs

from ..context import AnalysisContext
from ..token_estimation import _estimate_ref_tokens, estimate_tokens
from ..types import (
    PerCallRow,
    PerNodeThresholdEntry,
    SuggestedBlock,
    SuggestedBlockChunk,
    invocation_count_for,
)
from ..warning_catalog import make_diagnostic
from .row_builder import _node_inputs

_SUGGESTED_BLOCK_ACTIONABLE: str = "actionable"
_SUGGESTED_BLOCK_BELOW_THRESHOLD: str = "below_threshold"
_SUGGESTED_BLOCK_EVIDENCE_INCOMPLETE: str = "evidence_incomplete"
_SUGGESTED_BLOCK_INSUFFICIENT_NODES: str = "insufficient_nodes"
_PARENT_PROSE_PREVIEW_LIMIT = 40
_INDIVIDUAL_FLOOR_USD: Final[float] = 0.005
_CUMULATIVE_FLOOR_USD: Final[float] = 0.05


@dataclass(frozen=True)
class PaddingCandidate:
    """One node's padding-advisory candidate.

    Net-positive math (spec § "Prefix-Padding Advisory") is the analyzer's
    job — by the time a candidate reaches this module, ``savings_usd`` is the
    pre-computed dollar saving of switching from ``current_subset`` to
    ``suggested_subset``.
    """

    node_id: str
    workflow_path: str | None
    current_subset: tuple[str, ...]
    suggested_subset: tuple[str, ...]
    savings_usd: float


def compute_padding_advisories(candidates: list[PaddingCandidate]) -> list[Diagnostic]:
    """Filter by sensitivity floors and emit advisory diagnostics."""
    surviving: list[PaddingCandidate] = [c for c in candidates if c.savings_usd >= _INDIVIDUAL_FLOOR_USD]
    cumulative = sum(c.savings_usd for c in surviving)
    if cumulative < _CUMULATIVE_FLOOR_USD:
        return []

    return [
        make_diagnostic(
            "cache.padding-advisory",
            node_id=c.node_id,
            affected_workflow=c.workflow_path,
            current_subset=list(c.current_subset),
            suggested_subset=list(c.suggested_subset),
            savings_usd=c.savings_usd,
        )
        for c in surviving
    ]


def _batch_aliases(node: dict[str, Any]) -> set[str]:
    batch = node.get("batch")
    if not isinstance(batch, dict):
        return set()
    return {str(batch.get("as", "item"))}


def _compute_prompt_body_cleanup(
    workflow_ir: dict[str, Any],
    chunks: list[SuggestedBlockChunk],
    assignments: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Per-node prompt-body cleanup hint for greenfield SuggestedBlock.

    For each node being assigned cached chunks, lists the inline ``${...}``
    references that would overlap and need to be removed from the prompt
    body so agents following the analyzer's recommendation don't silently
    keep the inline refs and cancel out the cache savings.

    Returns ``{node_id: sorted unique body refs}``. Nodes without overlap
    don't appear in the dict.
    """
    from pflow.core.cache_overlap import compute_overlaps

    nodes_by_id_local = {n["id"]: n for n in workflow_ir.get("nodes", []) if isinstance(n, dict) and n.get("id")}
    chunk_name_set = {chunk.name for chunk in chunks}
    cleanup: dict[str, list[str]] = {}
    for node_id, assigned_chunk_names in assignments.items():
        node = nodes_by_id_local.get(node_id)
        if node is None:
            continue
        prompt_text = node.get("params", {}).get("prompt", "") or ""
        if not isinstance(prompt_text, str):
            continue
        overlaps = compute_overlaps(
            prompt_text=prompt_text,
            prompt_cache=assigned_chunk_names,
            cache_item_names=chunk_name_set,
            batch_aliases=_batch_aliases(node),
        )
        if overlaps:
            cleanup[node_id] = sorted({o.body_ref for o in overlaps})
    return cleanup


def _prompt_body_cleanup_for_node(
    node: dict[str, Any],
    corrected_prompt_cache: tuple[str, ...],
    cache_item_names: set[str],
) -> tuple[str, ...]:
    """Return prompt-body refs that overlap the corrected cache declaration."""
    from pflow.core.cache_overlap import compute_overlaps

    prompt_text = node.get("params", {}).get("prompt", "") or ""
    if not isinstance(prompt_text, str):
        return ()
    overlaps = compute_overlaps(
        prompt_text=prompt_text,
        prompt_cache=list(corrected_prompt_cache),
        cache_item_names=cache_item_names,
        batch_aliases=_batch_aliases(node),
    )
    return tuple(sorted({overlap.body_ref for overlap in overlaps}))


def _starter_prose_for_ref(ref: str) -> str:
    """Auto-generated humble label for a suggested cache chunk.

    Single-segment paths render as ``The X:`` (underscores → spaces).
    Dotted paths render as ``The Y from X:`` (Y = field, X = node).

    The agent should replace these with workflow-domain-specific prose
    before first run; the analyzer can't synthesize semantic descriptions
    because it doesn't know the workflow's domain. The starter form is
    byte-valid as-is so caching works on first run even without editing.
    """
    if "." in ref:
        node, _, tail = ref.partition(".")
        field = tail.replace("_", " ")
        return f"The {field} from {node}:"
    return f"The {ref.replace('_', ' ')}:"


def _populate_suggested_blocks(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    ctx: AnalysisContext,
    notes: list[str],
) -> tuple[list[SuggestedBlock], list[Diagnostic]]:
    """Build greenfield suggested ``## Cache`` blocks + advisory.

    v1 covers greenfield only (per DD#3). When ``## Cache`` is already
    declared, append a note so agents understand why no suggestion was
    produced — silent return would otherwise hide the deferral.

    Per-node cacheable projection used to flow back via this pass; that
    responsibility now lives in ``estimate_cacheable_tokens`` (Tier 2 reads
    candidate subsets directly from the IR walker via
    ``_detect_candidate_subsets``).
    """
    if _skip_suggested_blocks_for_declared_cache(workflow_ir, notes):
        return [], []

    ref_to_nodes, first_seen = _collect_llm_template_references(workflow_ir)
    shared_refs = [(ref, nodes) for ref, nodes in ref_to_nodes.items() if len(nodes) >= 2]
    if not shared_refs:
        return [], []

    # Sort key has 5 dimensions (CP3 #4 fix — sibling clustering):
    #   1. Most-shared root first. Roots like ``concept`` (used by 7 nodes via
    #      various sub-paths) outrank singleton roots regardless of any
    #      individual sub-path's count.
    #   2. Root segment alphabetical — deterministic tie-break BETWEEN roots
    #      with equal popularity. Crucially, this also keeps ALL sub-paths of
    #      the same root contiguous in the output (siblings cluster).
    #   3. Within a root, most-shared sub-path first. ``concept.core_idea``
    #      (used by 7) outranks ``concept.angle`` (used by 4).
    #   4. First-seen-in-prompt-walk-order — preserves narrative order between
    #      otherwise-equivalent refs.
    #   5. Alphabetical — final deterministic tie-break.
    # Pre-fix the sort scattered ``concept.core_idea`` / ``concept.title`` /
    # ``concept.angle`` across positions 1, 2, 5 because they had different
    # share counts and got ranked individually. Lyrics-generator song-creator
    # rendered ``concept.angle`` between ``creative-direction.response`` and
    # ``song-architecture.response`` — broke narrative flow AND made the
    # generated ``prompt_cache:`` lists non-prefix-contiguous for nodes using
    # only some sub-paths.
    root_to_nodes: dict[str, set[str]] = {}
    for ref, nodes in shared_refs:
        root_to_nodes.setdefault(_template_root_segment(ref), set()).update(nodes)
    root_popularity = {root: len(node_set) for root, node_set in root_to_nodes.items()}

    shared_refs.sort(
        key=lambda item: (
            -root_popularity[_template_root_segment(item[0])],
            _template_root_segment(item[0]),
            -len(item[1]),
            first_seen[item[0]],
            item[0],
        )
    )
    chunks, assignments, ref_sizes, affected_nodes = _build_suggested_chunks_and_assignments(
        shared_refs=shared_refs,
        rows_by_node=rows_by_node,
        ctx=ctx,
    )
    total_savings: float | None = 0.0

    memo_cache = ctx.memo_cache
    workflow_path = ctx.workflow_path

    per_node_thresholds, eligible_nodes = _thresholds_for_assignments(
        assignments=assignments,
        rows_by_node=rows_by_node,
        ctx=ctx,
        memo_cache=memo_cache,
        workflow_path=workflow_path,
    )
    actionability_state = _classify_suggested_block_actionability(per_node_thresholds)
    if actionability_state == _SUGGESTED_BLOCK_BELOW_THRESHOLD:
        min_tokens_strictest = max(
            entry["min_tokens"] for entry in per_node_thresholds.values() if entry["min_tokens"] is not None
        )
        target_file = workflow_path or "<root>"
        conditional = make_diagnostic(
            "cache.shared-context-undeclared-conditional",
            node_id=None,
            node_count=len(affected_nodes),
            shared_chunks=[chunk.name for chunk in chunks],
            affected_workflow=target_file,
            min_tokens=min_tokens_strictest,
            affected_nodes=sorted(affected_nodes),
        )
        return [], [conditional]

    if actionability_state != _SUGGESTED_BLOCK_ACTIONABLE:
        note = _note_for_non_actionable_state(actionability_state)
        if note is not None:
            notes.append(note)
        return [], []

    for ref, node_ids in shared_refs:
        chunk_savings = _savings_for_shared_ref(ref, node_ids, rows_by_node, ref_sizes[ref], eligible_nodes)
        if chunk_savings is None:
            total_savings = None
        elif total_savings is not None:
            total_savings += chunk_savings

    target_file = workflow_path or "<root>"
    block = SuggestedBlock(
        target_file=target_file,
        ttl="5m",
        chunks=tuple(chunks),
        per_node_assignments={node_id: assignments[node_id] for node_id in sorted(assignments)},
        estimated_savings_usd=total_savings,
        prompt_body_cleanup=_compute_prompt_body_cleanup(workflow_ir, chunks, assignments),
        per_node_thresholds={node_id: per_node_thresholds[node_id] for node_id in sorted(per_node_thresholds)},
    )
    warning = make_diagnostic(
        "cache.shared-context-undeclared",
        node_id=None,
        node_count=len(affected_nodes),
        shared_chunks=[chunk.name for chunk in chunks],
        affected_workflow=target_file,
        savings_usd=total_savings,
    )
    return [block], [warning]


def _build_suggested_chunks_and_assignments(
    *,
    shared_refs: list[tuple[str, list[str]]],
    rows_by_node: dict[str, PerCallRow],
    ctx: AnalysisContext,
) -> tuple[list[SuggestedBlockChunk], dict[str, list[str]], dict[str, int | None], set[str]]:
    chunks: list[SuggestedBlockChunk] = []
    assignments: dict[str, list[str]] = {}
    ref_sizes: dict[str, int | None] = {}
    affected_nodes: set[str] = set()
    for ref, node_ids in shared_refs:
        first_row = rows_by_node.get(node_ids[0])
        model = first_row.model if first_row else ""
        size_tokens = _estimate_ref_tokens(
            ref,
            model=model,
            memo_cache=ctx.memo_cache,
            workflow_path=ctx.workflow_path,
            ctx=ctx,
        )
        ref_sizes[ref] = size_tokens
        chunks.append(
            SuggestedBlockChunk(
                name=ref,
                var=f"${{{ref}}}",
                size_tokens_est=size_tokens if size_tokens is not None else 0,
                prose_placeholder=_starter_prose_for_ref(ref),
            )
        )
        for node_id in node_ids:
            affected_nodes.add(node_id)
            assignments.setdefault(node_id, []).append(ref)
    return chunks, assignments, ref_sizes, affected_nodes


def _skip_suggested_blocks_for_declared_cache(workflow_ir: dict[str, Any], notes: list[str]) -> bool:
    # The previous "Suggested-blocks: workflow already declares ## Cache;
    # steady-state (partial-block) suggestions deferred to v1.x." Note was
    # internal-jargon roadmap leak ("Suggested-blocks", "partial-block",
    # "v1.x"). Workflows with a declared ## Cache simply don't get block
    # suggestions; that's neutral state, not actionable signal. Silence
    # over noise.
    del notes  # Reserved for future agent-facing signal at this gate.
    return bool(_cache_item_names(workflow_ir))


def _classify_suggested_block_actionability(
    per_node_thresholds: Mapping[str, PerNodeThresholdEntry],
) -> str:
    """Classify the suggested-block state for dispatch.

    The caller emits the confident ``cache.shared-context-undeclared`` only for
    actionable blocks, emits a conditional advisory for known-below-threshold
    blocks, and leaves only plain notes for incomplete evidence or too few
    reusable nodes.
    """
    if len(per_node_thresholds) < 2:
        return _SUGGESTED_BLOCK_INSUFFICIENT_NODES
    statuses = [entry["meets_threshold"] for entry in per_node_thresholds.values()]
    if any(status is None for status in statuses):
        return _SUGGESTED_BLOCK_EVIDENCE_INCOMPLETE
    if any(status is False for status in statuses):
        return _SUGGESTED_BLOCK_BELOW_THRESHOLD
    return _SUGGESTED_BLOCK_ACTIONABLE


def _note_for_non_actionable_state(state: str) -> str | None:
    """Plain-English note text for states without a structured advisory."""
    if state == _SUGGESTED_BLOCK_INSUFFICIENT_NODES:
        return (
            "Suggested-blocks: shared refs were found, but fewer than two LLM nodes can "
            "reuse the provider cache; no cache edit will fire at the provider yet."
        )
    if state == _SUGGESTED_BLOCK_EVIDENCE_INCOMPLETE:
        return (
            "Suggested-blocks: shared refs were found, but the analyzer cannot yet tell "
            "whether a cache edit would fire (set settings.default_model or run the "
            "workflow once, then re-run analyze-cache)."
        )
    return None


def _thresholds_for_assignments(
    *,
    assignments: dict[str, list[str]],
    rows_by_node: dict[str, PerCallRow],
    ctx: AnalysisContext,
    memo_cache: Any,
    workflow_path: str | None,
) -> tuple[dict[str, PerNodeThresholdEntry], set[str]]:
    per_node_thresholds: dict[str, PerNodeThresholdEntry] = {}
    eligible_nodes: set[str] = set()
    for node_id, assigned_refs in assignments.items():
        entry = _threshold_entry_for_node(
            node_id=node_id,
            assigned_refs=assigned_refs,
            rows_by_node=rows_by_node,
            ctx=ctx,
            memo_cache=memo_cache,
            workflow_path=workflow_path,
        )
        per_node_thresholds[node_id] = entry
        if entry["meets_threshold"] is True:
            eligible_nodes.add(node_id)
    return per_node_thresholds, eligible_nodes


def _threshold_entry_for_node(
    *,
    node_id: str,
    assigned_refs: list[str],
    rows_by_node: dict[str, PerCallRow],
    ctx: AnalysisContext,
    memo_cache: Any,
    workflow_path: str | None,
) -> PerNodeThresholdEntry:
    node_row = rows_by_node.get(node_id)
    if node_row is None:
        return {
            "model": None,
            "model_state": "unknown",
            "min_tokens": None,
            "total_tokens": None,
            "meets_threshold": None,
        }
    if node_row.model_is_heterogeneous:
        return {
            "model": None,
            "model_state": "heterogeneous",
            "min_tokens": None,
            "total_tokens": None,
            "meets_threshold": None,
        }
    if not node_row.model:
        return {
            "model": None,
            "model_state": "unknown",
            "min_tokens": None,
            "total_tokens": None,
            "meets_threshold": None,
        }

    total = _sum_chunk_tokens(assigned_refs, node_row.model, ctx, memo_cache, workflow_path)
    threshold = get_min_cache_tokens(node_row.model)
    return {
        "model": node_row.model,
        "model_state": "resolved",
        "min_tokens": threshold,
        "total_tokens": total,
        "meets_threshold": (total >= threshold) if total is not None else None,
    }


def _collect_llm_template_references(workflow_ir: dict[str, Any]) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Return ``template_ref -> node_ids`` for LLM prompt references."""
    ref_to_nodes: dict[str, list[str]] = {}
    first_seen: dict[str, int] = {}
    for node_idx, node in enumerate(workflow_ir.get("nodes", []) or []):
        if not isinstance(node, dict) or node.get("type") != "llm":
            continue
        prompt = node.get("params", {}).get("prompt", "")
        if not isinstance(prompt, str):
            continue
        batch_aliases = _batch_aliases(node)
        seen_in_node: set[str] = set()
        node_inputs = _node_inputs(node)
        for classified_ref in classify_prompt_refs(prompt, batch_alias=None, node_inputs=node_inputs):
            for ref in classified_ref.operand_paths:
                if _is_batch_scoped_ref(ref, batch_aliases) or ref in seen_in_node:
                    continue
                seen_in_node.add(ref)
                ref_to_nodes.setdefault(ref, []).append(str(node["id"]))
                first_seen.setdefault(ref, node_idx)
    return ref_to_nodes, first_seen


def _collect_llm_template_root_references(
    workflow_ir: dict[str, Any],
    var_to_name: dict[str, str],
) -> dict[str, list[str]]:
    """Return ``cache_item_name -> node_ids`` for LLM prompt references.

    Sibling of ``_collect_llm_template_references``: the existing helper
    preserves literal refs for token pricing; this helper buckets by the cache
    item whose ``var`` is the longest prefix of each operand. Batch-scoped refs
    are filtered to match validator overlap behavior.
    """
    refs_by_name: dict[str, list[str]] = {}
    vars_ = tuple(var_to_name.keys())
    for node in workflow_ir.get("nodes", []) or []:
        if not isinstance(node, dict) or node.get("type") != "llm":
            continue
        node_id = node.get("id")
        prompt = node.get("params", {}).get("prompt", "")
        if not node_id or not isinstance(prompt, str):
            continue
        batch_aliases = _batch_aliases(node)
        seen_names: set[str] = set()
        node_inputs = _node_inputs(node)
        for ref in classify_prompt_refs(prompt, batch_alias=None, node_inputs=node_inputs):
            for operand in ref.operand_paths:
                if _is_batch_scoped_ref(operand, batch_aliases):
                    continue
                matched_var = _longest_var_prefix_match(operand, vars_)
                if matched_var is None:
                    continue
                name = var_to_name[matched_var]
                if name in seen_names:
                    continue
                seen_names.add(name)
                refs_by_name.setdefault(name, []).append(str(node_id))
    return refs_by_name


def _longest_var_prefix_match(operand: str, vars_: Iterable[str]) -> str | None:
    """Return the longest cache var matching ``operand`` by root/sub-path prefix."""
    if not operand:
        return None
    best: str | None = None
    for var in vars_:
        if not isinstance(var, str) or not var:
            continue
        if (operand == var or operand.startswith(f"{var}.") or operand.startswith(f"{var}[")) and (
            best is None or len(var) > len(best)
        ):
            best = var
    return best


def _template_root_segment(ref: str) -> str:
    """Return the first segment of a template path.

    Examples:
        ``concept.core_idea`` → ``concept``
        ``concept`` → ``concept``
        ``items[0].name`` → ``items``
        ``creative-direction.response`` → ``creative-direction``

    Used by:
    - the ``_populate_suggested_blocks`` sort key (CP3 #4 — sibling clustering),
    - the ``_consolidate_to_root_advisories`` detector (CP3 #3 — sub-path
      clusters that fall below the provider's min-cache threshold).
    """
    return ref.split(".", 1)[0].split("[", 1)[0]


def _consolidate_to_root_advisories(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    declared_chunks: list[str],
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Emit ``cache.consolidate-to-root-recommended`` advisories.

    Fires when sub-paths of a parent dict (e.g. ``concept.core_idea``,
    ``concept.title``) are individually below the provider's min-cache token
    threshold AND consolidating to ``${root}`` would cross the threshold.
    The pre-fix sub-path declarations cache_control markers silently no-op
    at the provider; the agent thinks they're caching but they aren't.

    Greenfield path (no ``## Cache`` declared): audits shared template
    references. Only fires when memo data is available — without it,
    ``_estimate_ref_tokens`` falls back to tokenizing the literal
    ``${concept}`` string (~3 tokens), making the threshold check naturally
    suppress the advisory for pure-greenfield workflows. After the first
    run, memo data populates and the advisory becomes meaningful.

    Brownfield path (``## Cache`` declared with sub-path chunks): audits the
    declared chunks directly. The user has explicitly chosen these chunks;
    the advisory tells them why caching isn't actually firing.
    """
    candidates = _collect_consolidate_candidates(workflow_ir, declared_chunks)
    if not candidates:
        return []
    candidate_set = set(candidates)
    by_root = _group_subpaths_by_root(candidates)
    if not by_root:
        return []

    rows = list(rows_by_node.values())
    resolved_models = tuple(row.model for row in rows if row.model)
    representative_model = max(
        resolved_models,
        key=get_min_cache_tokens,
        default="",
    )
    if not representative_model:
        return []
    min_tokens = get_min_cache_tokens(representative_model)

    diagnostics: list[Diagnostic] = []
    for root, sub_paths in sorted(by_root.items()):
        diag = _check_root_for_consolidation(
            root=root,
            sub_paths=sub_paths,
            candidate_set=candidate_set,
            model=representative_model,
            min_tokens=min_tokens,
            ctx=ctx,
        )
        if diag is not None:
            diagnostics.append(diag)
    return diagnostics


def _collect_consolidate_candidates(workflow_ir: dict[str, Any], declared_chunks: list[str]) -> list[str]:
    """Pick the chunk set the consolidate-advisory should examine."""
    if declared_chunks:
        # Brownfield — agent has explicitly declared these chunks.
        return list(set(declared_chunks))
    # Greenfield — shared template references (≥2 LLM nodes).
    ref_to_nodes, _ = _collect_llm_template_references(workflow_ir)
    return [ref for ref, node_ids in ref_to_nodes.items() if len(node_ids) >= 2]


def _group_subpaths_by_root(candidates: list[str]) -> dict[str, list[str]]:
    """Group sub-paths by their root segment.

    Root form chunks (``concept`` itself, where root == ref) are excluded:
    they ARE the root, not candidates for consolidation. Only genuine
    sub-paths (``concept.title``) get grouped.
    """
    by_root: dict[str, list[str]] = {}
    for ref in candidates:
        root = _template_root_segment(ref)
        if root != ref:
            by_root.setdefault(root, []).append(ref)
    return by_root


def _check_root_for_consolidation(
    *,
    root: str,
    sub_paths: list[str],
    candidate_set: set[str],
    model: str,
    min_tokens: int,
    ctx: AnalysisContext,
) -> Diagnostic | None:
    """Run the threshold check for one root group.

    Returns a Diagnostic when consolidation would cross the threshold; None
    when any of the suppression rules fires:
      - <2 sub-paths (no consolidation case)
      - root already declared/used (redundancy, not consolidation)
      - some sub-path already crosses threshold (caching already works)
      - root itself wouldn't cross threshold (cache.below-min-predicted covers it)
    """
    if len(sub_paths) < 2:
        return None
    if root in candidate_set:
        # Root already declared/used directly — sub-paths are a redundancy
        # issue, not a consolidation case. The right fix is "remove the
        # redundant sub-path entries", not "consolidate to root".
        return None
    memo_cache = ctx.memo_cache
    workflow_path = ctx.workflow_path
    sub_path_tokens = [
        _estimate_ref_tokens(sp, model=model, memo_cache=memo_cache, workflow_path=workflow_path, ctx=ctx)
        for sp in sub_paths
    ]
    # Pre-Option-C this advisory relied on ``_estimate_ref_tokens`` returning
    # ~3-5 tokens (literal ``${ref}``) on memo miss — implicit suppression via
    # "small number trickles past threshold". Now ``_estimate_ref_tokens``
    # returns ``None`` on memo miss; explicit check needed. The advisory's
    # whole premise (compare sub-path tokens vs root tokens vs threshold) is
    # only meaningful with real value sizes. Any None → skip.
    if any(t is None for t in sub_path_tokens):
        return None
    max_subpath = max(t for t in sub_path_tokens if t is not None)
    if max_subpath >= min_tokens:
        # At least one sub-path is large enough to cache on its own;
        # cache_control on the largest sub-path already fires.
        return None
    root_tokens = _estimate_ref_tokens(root, model=model, memo_cache=memo_cache, workflow_path=workflow_path, ctx=ctx)
    if root_tokens is None or root_tokens < min_tokens:
        # Either no run data for the root (unmeasurable) or even consolidation
        # wouldn't cross the threshold (``cache.below-min-predicted`` covers
        # the latter case for declared subsets).
        return None
    return make_diagnostic(
        "cache.consolidate-to-root-recommended",
        node_id=None,
        root=root,
        sub_paths=sorted(sub_paths),
        model=model,
        min_tokens=min_tokens,
        max_subpath_tokens=max_subpath,
        root_tokens=root_tokens,
        affected_workflow=workflow_path,
    )


def _emit_padding_advisories(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
) -> list[Diagnostic]:
    """Build and filter ``cache.padding-advisory`` candidates."""
    cache_items = _cache_items(workflow_ir)
    declared_names = [str(item["name"]) for item in cache_items]
    if not declared_names:
        return []
    candidates: list[PaddingCandidate] = []
    for node in workflow_ir.get("nodes", []) or []:
        if not isinstance(node, dict) or node.get("type") != "llm":
            continue
        subset = node.get("prompt_cache")
        if not isinstance(subset, list) or not subset:
            continue
        current_subset = tuple(str(item) for item in subset)
        if current_subset[0] not in declared_names:
            continue
        first_pos = declared_names.index(current_subset[0])
        if first_pos == 0:
            continue
        row = rows_by_node.get(str(node.get("id")))
        if row is None:
            continue
        rate = _input_rate(row.model)
        if rate is None:
            continue
        prefix_tokens = sum(_estimate_chunk_tokens(item, row.model) for item in cache_items[:first_pos])
        call_count = invocation_count_for(row)
        savings_usd = 0.9 * prefix_tokens * call_count * rate
        candidates.append(
            PaddingCandidate(
                node_id=row.node_path,
                workflow_path=row.workflow_path,
                current_subset=current_subset,
                suggested_subset=tuple(declared_names[:first_pos]) + current_subset,
                savings_usd=savings_usd,
            )
        )
    return compute_padding_advisories(candidates)


def _cache_items(workflow_ir: dict[str, Any]) -> list[dict[str, Any]]:
    cache = workflow_ir.get("cache")
    if not isinstance(cache, dict):
        return []
    items = cache.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and isinstance(item.get("name"), str)]


def _cache_item_names(workflow_ir: dict[str, Any]) -> list[str]:
    return [str(item["name"]) for item in _cache_items(workflow_ir)]


def _estimate_chunk_tokens(item: dict[str, Any], model: str) -> int:
    text = f"{item.get('prose_before', '')}\n${{{item.get('var', item.get('name', ''))}}}"
    return estimate_tokens(model, text)[0]


def _sum_chunk_tokens(
    refs: list[str],
    model: str,
    ctx: AnalysisContext,
    memo_cache: Any,
    workflow_path: str | None,
) -> int | None:
    """Sum chunk tokens across refs. Returns None if any ref is unmeasurable."""
    total = 0
    for ref in refs:
        tokens = _estimate_ref_tokens(ref, model=model, memo_cache=memo_cache, workflow_path=workflow_path, ctx=ctx)
        if tokens is None:
            return None
        total += tokens
    return total


def _savings_for_shared_ref(
    ref: str,
    node_ids: list[str],
    rows_by_node: dict[str, PerCallRow],
    tokens: int | None,
    eligible_nodes: set[str],
) -> float | None:
    if tokens is None:
        # No memo data → can't compute savings honestly. Mirror the existing
        # cost tri-state contract: None propagates rather than fabricating 0.
        return None
    eligible_in_order = [node_id for node_id in node_ids if node_id in eligible_nodes]
    if len(eligible_in_order) < 2:
        return 0.0
    total = 0.0
    for node_id in eligible_in_order[1:]:
        row = rows_by_node.get(node_id)
        if row is None:
            return None
        savings = _estimate_token_savings_usd(row.model, tokens, invocation_count_for(row))
        if savings is None:
            return None
        total += savings
    return total


def _estimate_token_savings_usd(model: str, tokens: int, calls: int) -> float | None:
    rate = _input_rate(model)
    if rate is None:
        return None
    return 0.9 * tokens * calls * rate


def _input_rate(model: str) -> float | None:
    from ..cost_estimation import get_model_pricing

    pricing = get_model_pricing(model)
    return pricing.input_rate if pricing is not None else None


def _is_batch_scoped_ref(ref: str, aliases: set[str]) -> bool:
    return any(ref == alias or ref.startswith(f"{alias}.") or ref.startswith(f"{alias}[") for alias in aliases)


def _extract_cache_ttl(cache_block: Any) -> str | None:
    """Read the validated TTL from a ``## Cache`` block."""
    if not isinstance(cache_block, dict):
        return None
    ttl_value = cache_block.get("ttl")
    if ttl_value is None:
        return None
    if not isinstance(ttl_value, str):
        return None
    try:
        parse_cache_ttl(ttl_value)
    except ValueError:
        return None
    return ttl_value
