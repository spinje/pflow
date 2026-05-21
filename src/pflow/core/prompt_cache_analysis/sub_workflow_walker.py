"""Tier 2 — cross-workflow walker.

Recursive walk from the root workflow IR through every ``type: workflow`` node.
For each parent-child edge yields a :class:`CrossWorkflowEdge` carrying the
parent value expression, the child input name it lands on, and the source line
in the parent file. Detection rules — rename / prose-mismatch / value-flow —
consume these edges in :mod:`analyze`.

Mirrors the mermaid renderer's traversal pattern (depth limit + cycle-detection
``seen`` set, ``resolve_sub_workflow`` as the resolver primitive). The walker
re-raises sub-workflow resolution errors rather than swallowing them: the
analyzer fires only on already-validated workflows; broken refs surface
through the existing diagnostic pipeline (Suggestion 22 — handled without a
new ``cache.*`` ID).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult, resolve_sub_workflow

from .context import AnalysisContext, _normalize_empty
from .token_estimation import (
    build_shared_store_for_refs as _build_shared_store_for_refs,
)
from .token_estimation import (
    extract_unique_refs as _extract_unique_refs,
)

logger = logging.getLogger(__name__)


ResolverCallback = Callable[[dict[str, Any], Path | None], SubWorkflowResult | None]


# ---------------------------------------------------------------------------
# CrossWorkflowEdge — one row per parent-input → child-input mapping
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossWorkflowEdge:
    """One value-flow edge across a workflow boundary.

    ``parent_value_expr`` is the inside of the ``${...}`` reference in the
    parent's input mapping (e.g. ``"concept_brief"`` or
    ``"chorus-chooser.winning_chorus"``); ``None`` when the parent passes a
    literal value (no template). ``child_input_name`` is the key of the child's
    declared inputs dict. Rename detection compares the LAST segment of
    ``parent_value_expr`` (after splitting on ``.``) to ``child_input_name``.

    ``parent_batch_alias`` is the iteration-variable name when the parent
    workflow-type node has a ``batch:`` config (e.g. ``"item"`` by default,
    or whatever the ``as:`` field overrides it to). ``None`` for non-batch
    parent nodes. Used downstream to suppress the rename warning when the
    parent value is a batch alias root (``${item}`` / ``${item.X}``) — that
    is iteration-variable substitution, not a logical rename.
    """

    parent_workflow: str
    child_workflow: str
    parent_value_expr: str | None
    child_input_name: str
    line_in_parent: int
    parent_node_id: str
    parent_batch_alias: str | None = None
    parent_input_value: Any = None

    @property
    def is_rename(self) -> bool:
        """True iff the parent's value-tail differs from the child's input name.

        Syntactic predicate only — answers "are the names different?" without
        regard to whether the difference matters for caching. The decision to
        EMIT a ``cache.cross-workflow-rename-detected`` warning is made
        downstream in :mod:`analyze`, gated on actionability (see the
        evidence-basis principle: predictive warnings about state comparisons
        should fire only when the state to compare against actually exists).

        Suppressed when there's no template (literal value) — there's no
        rename to detect because the parent isn't passing a named value.
        """
        if not self.parent_value_expr:
            return False
        return _value_tail(self.parent_value_expr) != self.child_input_name

    @property
    def is_batch_alias_root(self) -> bool:
        """True iff ``parent_value_expr``'s root segment is the parent's batch alias.

        ``${item}`` and ``${item.X}`` (assuming default alias) are
        iteration-variable references, not stable renameable identifiers.
        Every batch-sub-workflow invocation produces such an edge by design;
        emitting a rename warning for every one floods the report with
        non-actionable noise. This predicate identifies that case.
        """
        if not self.parent_value_expr or not self.parent_batch_alias:
            return False
        # Strip dotted-path / bracket-index to isolate the root identifier.
        root = self.parent_value_expr.split(".", 1)[0].split("[", 1)[0]
        return root == self.parent_batch_alias


def _value_tail(expr: str) -> str:
    """Return the rightmost identifier segment of a template path.

    Examples:
        ``concept`` → ``concept``
        ``chorus-chooser.winning_chorus`` → ``winning_chorus``
        ``data[0].field`` → ``field``
    """
    # Strip everything before the last '.' if any.
    tail = expr.rsplit(".", 1)[-1]
    # Strip trailing bracket index (e.g. ``items[0]`` → ``items``).
    bracket_idx = tail.find("[")
    if bracket_idx != -1:
        tail = tail[:bracket_idx]
    return tail


@dataclass(frozen=True)
class DynamicBatchInfo:
    """One template-items batch encountered during the walk.

    A workflow-type node with ``batch.items: "${...}"`` (runtime template
    rather than an inline static list) can't have its per-item children
    enumerated statically. The walker records each such occurrence as a
    typed entry; the analyzer formats them into ONE aggregated Note after
    the walk completes (B-4) — keeping the walker as a data primitive and
    the user-facing prose in the rendering layer.
    """

    node_id: str
    parent_workflow: str
    items_expression: str


@dataclass(frozen=True)
class CrossWorkflowResult:
    """Cross-workflow walk output.

    ``cache_items_by_workflow`` and ``irs_by_workflow`` are keyed by the same
    labels carried on :class:`CrossWorkflowEdge` (``parent_workflow`` /
    ``child_workflow``). ``irs_by_workflow`` exposes each visited workflow's
    full IR so consumers can count LLM nodes that reference a given value
    (Bug E fix — B.3 cross-workflow value-flow needs an accurate ``node_count``).

    ``dynamic_batches`` carries every template-items batch encountered during
    the walk so the analyzer can emit ONE aggregated Note instead of N
    near-identical paragraphs (B-4).
    """

    edges: tuple[CrossWorkflowEdge, ...]
    cache_items_by_workflow: dict[str, tuple[dict[str, Any], ...]]
    irs_by_workflow: dict[str, dict[str, Any]]
    dynamic_batches: tuple[DynamicBatchInfo, ...] = ()


# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------


_DEFAULT_MAX_DEPTH = 10


def walk_cross_workflow(
    root_ir: dict[str, Any],
    *,
    base_path: Path | None,
    resolve_child: ResolverCallback | None = None,
    root_workflow_path: str | None = None,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    seen_paths: set[str] | None = None,
    notes: list[str] | None = None,
) -> CrossWorkflowResult:
    """Walk the parent-child sub-workflow graph and return every edge.

    Parameters mirror the mermaid renderer's traversal API for consistency.
    ``resolve_child`` defaults to :func:`resolve_sub_workflow` from the shared
    primitive; tests inject a stub.

    ``seen_paths`` lets tests pre-seed cycles (e.g., simulate "the root path is
    X" so a child whose grandchild references X registers a cycle); production
    callers leave it as ``None``.

    ``notes`` is an optional list the walker appends to when it stops descending
    a branch — at ``max_depth`` or on a cycle. The analyzer surfaces these
    notes through ``CacheAnalysis.notes`` so agents see "deeper boundaries not
    analyzed" / "cycle skipped" rather than silently truncated results.

    Cycle handling: the root workflow path is seeded into ``seen`` from the
    outset so cycles back to the root (A → B → A) are detected at the
    cycle-check in :func:`_process_one_call` and the back-edge is suppressed.
    Without this seed the back-edge enters ``cw_result.edges`` and downstream
    consumers like :func:`_build_parameters_by_workflow`
    mutate the root parameter dict.
    """
    resolver = resolve_child or resolve_sub_workflow
    seen = set(seen_paths) if seen_paths else set()
    if root_workflow_path:
        seen.add(root_workflow_path)
    edges: list[CrossWorkflowEdge] = []
    cache_items_by_workflow: dict[str, tuple[dict[str, Any], ...]] = {}
    irs_by_workflow: dict[str, dict[str, Any]] = {}
    dynamic_batches: list[DynamicBatchInfo] = []
    parent_label = root_workflow_path or "<root>"
    cache_items_by_workflow[parent_label] = _cache_items_as_tuple(root_ir)
    irs_by_workflow[parent_label] = root_ir
    _walk_one_level(
        ir=root_ir,
        parent_label=parent_label,
        base_path=base_path,
        resolver=resolver,
        edges=edges,
        seen=seen,
        depth=0,
        max_depth=max_depth,
        notes=notes,
        cache_items_by_workflow=cache_items_by_workflow,
        irs_by_workflow=irs_by_workflow,
        dynamic_batches=dynamic_batches,
    )
    return CrossWorkflowResult(
        edges=tuple(edges),
        cache_items_by_workflow=cache_items_by_workflow,
        irs_by_workflow=irs_by_workflow,
        dynamic_batches=tuple(dynamic_batches),
    )


def _walk_one_level(
    *,
    ir: dict[str, Any],
    parent_label: str,
    base_path: Path | None,
    resolver: ResolverCallback,
    edges: list[CrossWorkflowEdge],
    seen: set[str],
    depth: int,
    max_depth: int,
    notes: list[str] | None,
    cache_items_by_workflow: dict[str, tuple[dict[str, Any], ...]],
    irs_by_workflow: dict[str, dict[str, Any]],
    dynamic_batches: list[DynamicBatchInfo],
) -> None:
    """Visit every ``type: workflow`` node in ``ir`` and recurse."""
    if depth >= max_depth:
        message = (
            f"Cross-workflow walker reached max_depth={max_depth} at {parent_label} — deeper boundaries not analyzed. "
            "Cost rollup is trace-driven and still reflects actual execution; IR-driven projections under-cover "
            "deeper boundaries. Increase max_depth in the analyzer call to extend projection coverage."
        )
        logger.info(message)
        if notes is not None and message not in notes:
            notes.append(message)
        return

    for node in ir.get("nodes", []):
        if not isinstance(node, dict) or node.get("type") != "workflow":
            continue
        _maybe_record_dynamic_batch(node, parent_label, dynamic_batches)
        params = node.get("params") or {}
        if not isinstance(params, dict):
            continue
        # Build the per-call enumeration (1 for non-batch, N for inline-static
        # batch with per-item refs).
        for effective_params, _batch_idx, _from_item in _enumerate_calls(node, params):
            _process_one_call(
                node=node,
                params=effective_params,
                parent_label=parent_label,
                base_path=base_path,
                resolver=resolver,
                edges=edges,
                seen=seen,
                depth=depth,
                max_depth=max_depth,
                notes=notes,
                cache_items_by_workflow=cache_items_by_workflow,
                irs_by_workflow=irs_by_workflow,
                dynamic_batches=dynamic_batches,
            )


def _maybe_record_dynamic_batch(
    node: dict[str, Any], parent_label: str, dynamic_batches: list[DynamicBatchInfo]
) -> None:
    """Record one entry per template-items workflow batch encountered.

    The walker is a data primitive (per ``prompt_cache_analysis/CLAUDE.md``); it
    collects facts and the analyzer formats user-facing prose. Recording
    typed entries here lets the analyzer emit ONE aggregated Note across all
    runtime batches in the workflow tree — replacing the per-batch prose
    paragraphs that flooded ``## Notes`` (B-4).
    """
    batch = node.get("batch")
    if not isinstance(batch, dict) or isinstance(batch.get("items"), list):
        return
    items = batch.get("items")
    if not isinstance(items, str) or "${" not in items:
        return
    node_id = str(node.get("id", "?"))
    entry = DynamicBatchInfo(node_id=node_id, parent_workflow=parent_label, items_expression=items)
    if entry not in dynamic_batches:
        dynamic_batches.append(entry)


def _enumerate_calls(node: dict[str, Any], params: dict[str, Any]) -> Any:
    """Iterate over ``(effective_params, batch_idx, inputs_from_item)`` tuples.

    Wraps :meth:`WorkflowValidator._enumerate_child_calls` so heterogeneous
    inline-static batches yield N calls and homogeneous ones yield 1.
    Lazy-imported to avoid a circular dependency on ``core.workflow.validator``.
    """
    from pflow.core.workflow.validator import WorkflowValidator

    yield from WorkflowValidator._enumerate_child_calls(node)


def _process_one_call(
    *,
    node: dict[str, Any],
    params: dict[str, Any],
    parent_label: str,
    base_path: Path | None,
    resolver: ResolverCallback,
    edges: list[CrossWorkflowEdge],
    seen: set[str],
    depth: int,
    max_depth: int,
    notes: list[str] | None,
    cache_items_by_workflow: dict[str, tuple[dict[str, Any], ...]],
    irs_by_workflow: dict[str, dict[str, Any]],
    dynamic_batches: list[DynamicBatchInfo],
) -> None:
    """Resolve one child call and emit edges + recurse."""
    result = resolver(params, base_path)
    if result is None:
        return

    # Cycle detection — re-entry of a path already on the recursion stack.
    child_path_str = str(result.path) if result.path else None
    child_label = child_path_str or "<inline>"
    cache_items_by_workflow[child_label] = _cache_items_as_tuple(result.ir)
    irs_by_workflow[child_label] = result.ir
    if child_path_str and child_path_str in seen:
        message = (
            f"Cross-workflow walker detected cycle: {child_path_str} "
            f"already on recursion stack from {parent_label} — cycle skipped. "
            "Cost rollup is trace-driven, so actual recursive executions are still summed; "
            "only static IR enumeration was truncated."
        )
        logger.info(message)
        if notes is not None and message not in notes:
            notes.append(message)
        return

    inputs = params.get("inputs")
    line_in_parent = int(node.get("_source_line") or 0)
    node_id = str(node.get("id", ""))
    parent_batch_alias = _node_batch_alias(node)

    if isinstance(inputs, dict):
        for input_name, value_expr in inputs.items():
            edges.append(
                CrossWorkflowEdge(
                    parent_workflow=parent_label,
                    child_workflow=child_label,
                    parent_value_expr=_extract_template_inner(value_expr),
                    child_input_name=str(input_name),
                    line_in_parent=line_in_parent,
                    parent_node_id=node_id,
                    parent_batch_alias=parent_batch_alias,
                    parent_input_value=value_expr,
                )
            )

    if not result.ir.get("nodes"):
        return

    # Recurse — push onto seen, walk, pop. Each parent-child edge gets its own
    # base_path scoped to the child's directory, mirroring mermaid.
    child_base = result.path.parent if result.path else base_path
    if child_path_str:
        seen.add(child_path_str)
    try:
        _walk_one_level(
            ir=result.ir,
            parent_label=child_path_str or parent_label,
            base_path=child_base,
            resolver=resolver,
            edges=edges,
            seen=seen,
            depth=depth + 1,
            max_depth=max_depth,
            notes=notes,
            cache_items_by_workflow=cache_items_by_workflow,
            irs_by_workflow=irs_by_workflow,
            dynamic_batches=dynamic_batches,
        )
    finally:
        if child_path_str:
            seen.discard(child_path_str)


def _node_batch_alias(node: dict[str, Any]) -> str | None:
    """Return the iteration-variable alias for a workflow-type batch node.

    Defaults to ``"item"`` when the node has ``batch:`` config without an
    explicit ``as:`` override; otherwise the configured value. Returns
    ``None`` for non-batch nodes (no iteration variable to detect).
    """
    batch = node.get("batch")
    if not isinstance(batch, dict):
        return None
    return str(batch.get("as", "item"))


def _cache_items_as_tuple(ir: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    cache = ir.get("cache")
    if not isinstance(cache, dict):
        return ()
    items = cache.get("items")
    if not isinstance(items, list):
        return ()
    return tuple(item for item in items if isinstance(item, dict) and isinstance(item.get("name"), str))


def _extract_template_inner(value: Any) -> str | None:
    """Return the inside of ``${...}`` for a single-template input value.

    Returns None for literal values (no template) or non-string types so the
    rename rule treats them as "no logical value name" rather than triggering
    on garbage. Multi-ref strings (``"prefix ${a} mid ${b}"``) also return None
    — rename detection only operates on bare-template inputs.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not (stripped.startswith("${") and stripped.endswith("}")):
        return None
    inner = stripped[2:-1].strip()
    # Reject multi-ref by checking for any unmatched ${ inside the inner.
    if "${" in inner or "}" in inner:
        return None
    return inner or None


def _build_parameters_by_workflow(
    cw_result: Any,
    root_parameters: dict[str, Any],
    root_workflow_path: str,
    *,
    memo_cache: Any | None,
    trace_data: Mapping[str, Any] | None,
    base_path: Path | None,
    trace_outputs_by_key: Mapping[tuple[str | None, str], Any] | None = None,
    stale_memo_uncheckable: set[tuple[str | None, str]] | None = None,
) -> dict[str | None, dict[str, Any]]:
    """Build workflow-scoped parameter views from cross-workflow input edges."""
    params_by_workflow: dict[str | None, dict[str, Any]] = {root_workflow_path: dict(root_parameters)}
    irs_by_workflow = getattr(cw_result, "irs_by_workflow", {}) or {}
    remaining = list(getattr(cw_result, "edges", ()) or ())
    made_progress = True
    while remaining and made_progress:
        made_progress = False
        next_remaining = []
        for edge in remaining:
            parent_workflow = str(getattr(edge, "parent_workflow", root_workflow_path))
            if parent_workflow not in params_by_workflow:
                next_remaining.append(edge)
                continue
            child_workflow = getattr(edge, "child_workflow", None)
            child_input_name = getattr(edge, "child_input_name", None)
            if child_workflow is None or child_input_name is None:
                continue
            parent_ctx = AnalysisContext.build(
                workflow_ir=irs_by_workflow.get(parent_workflow, {}),
                parameters=params_by_workflow[parent_workflow],
                memo_cache=memo_cache,
                trace_data=trace_data,
                trace_outputs_by_key=trace_outputs_by_key or {},
                workflow_path=parent_workflow,
                base_path=base_path,
                parameters_by_workflow=params_by_workflow,
            )
            resolved = _resolve_child_input_value(edge, parent_ctx)
            if resolved is None:
                continue
            if stale_memo_uncheckable is not None:
                stale_memo_uncheckable.update(_unchecked_parent_memo_roots(edge, parent_ctx))
            child_params = params_by_workflow.setdefault(str(child_workflow), {})
            child_params[str(child_input_name)] = resolved
            made_progress = True
        remaining = next_remaining
    return params_by_workflow


def _resolve_child_input_value(edge: CrossWorkflowEdge, parent_ctx: AnalysisContext) -> Any | None:
    """Resolve a child workflow input value from the parent's analysis context.

    Batch sub-workflow calls can pass values rooted on the parent batch alias
    (for example ``${item}`` or ``${item.field}``). Static analysis cannot know
    every runtime item, so this uses ``items[0]`` as a deterministic exemplar
    when the parent's ``batch.items`` expression is resolvable, falling back to
    trace-recorded batch items when the trace is the only available evidence.
    """
    value = edge.parent_input_value
    if not isinstance(value, str):
        return _normalize_empty(value)
    refs = _extract_unique_refs(value)
    if not refs:
        return _normalize_empty(value)
    shared = _build_shared_store_for_refs(refs, parent_ctx)
    if edge.is_batch_alias_root:
        first_item = _resolve_first_batch_item(edge, parent_ctx)
        if first_item is None:
            return None
        if edge.parent_batch_alias is not None:
            shared[edge.parent_batch_alias] = first_item
    from pflow.runtime.template_resolver import TemplateResolver

    try:
        resolved = TemplateResolver.resolve_template(value, shared)
    except Exception:
        logger.debug("failed to resolve child workflow input value", exc_info=True)
        return None
    if isinstance(resolved, str) and TemplateResolver.TEMPLATE_PATTERN.search(resolved):
        return None
    return _normalize_empty(resolved)


def _unchecked_parent_memo_roots(
    edge: CrossWorkflowEdge,
    parent_ctx: AnalysisContext,
) -> set[tuple[str | None, str]]:
    """Node-output roots used to seed child params before prediction can verify memo."""
    value = edge.parent_input_value
    if not isinstance(value, str) or parent_ctx.memo_cache is None:
        return set()
    declared_inputs = parent_ctx.workflow_ir.get("inputs") if isinstance(parent_ctx.workflow_ir, Mapping) else None
    input_names = set(declared_inputs) if isinstance(declared_inputs, Mapping) else set()
    tainted: set[tuple[str | None, str]] = set()
    from pflow.runtime.template_resolver import TemplateResolver

    for ref in _extract_unique_refs(value):
        root = TemplateResolver.extract_root_node_id(ref)
        if not root or root in input_names or root == edge.parent_batch_alias:
            continue
        tainted.add((parent_ctx.workflow_path, root))
    return tainted


def _resolve_first_batch_item(edge: CrossWorkflowEdge, parent_ctx: AnalysisContext) -> Any | None:
    """Resolve the parent batch's ``items:`` expression and return its first item."""
    nodes_by_id = {
        str(n["id"]): n for n in parent_ctx.workflow_ir.get("nodes", []) if isinstance(n, dict) and "id" in n
    }
    parent_node = nodes_by_id.get(edge.parent_node_id)
    if parent_node is None:
        return None
    batch = parent_node.get("batch")
    if not isinstance(batch, dict):
        return None
    items_expr = batch.get("items")
    if isinstance(items_expr, list):
        return _normalize_empty(items_expr[0]) if items_expr else None
    if not isinstance(items_expr, str):
        return None
    from pflow.runtime.template_resolver import TemplateResolver

    try:
        resolved = TemplateResolver.resolve_template(
            items_expr,
            _build_shared_store_for_refs(_extract_unique_refs(items_expr), parent_ctx),
        )
    except Exception:
        logger.debug("failed to resolve batch items expression", exc_info=True)
        return None
    if isinstance(resolved, list) and resolved:
        return _normalize_empty(resolved[0])
    trace_item = _resolve_first_trace_batch_item(edge, parent_ctx)
    if trace_item is not None:
        return trace_item
    return None


def _resolve_first_trace_batch_item(edge: CrossWorkflowEdge, parent_ctx: AnalysisContext) -> Any | None:
    """Return the first recorded runtime batch item for ``edge.parent_node_id``."""
    event = parent_ctx.trace_event_for(edge.parent_node_id)
    if not isinstance(event, Mapping):
        return None
    batch_items = event.get("batch_items")
    if not isinstance(batch_items, list):
        return None
    item_events = [item for item in batch_items if isinstance(item, Mapping)]
    if not item_events:
        return None
    first = min(item_events, key=lambda item: int(item.get("index") or 0))
    return _normalize_empty(first.get("item"))


__all__ = [
    "CrossWorkflowEdge",
    "CrossWorkflowResult",
    "DynamicBatchInfo",
    "walk_cross_workflow",
]
