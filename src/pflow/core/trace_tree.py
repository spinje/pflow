"""Read-only traversal helpers for pflow workflow traces.

Trace JSON has a small tree shape: top-level events, batch items inside an
event, sub-workflow events nested under a parent event. Consumers need two
recursive views:

- :meth:`TraceTree.walk` yields the structural event tree for inspection,
  attribution, token recovery, and historical/audit views.
- :meth:`TraceTree.iter_actual_cost_events` yields the current-run cost view,
  where cached events are paid-cost boundaries: the cached boundary contributes
  observed zero-cost evidence and historical descendants are not traversed.

Cost helpers are thin layers over those views. Default cost methods answer
"what did this run pay?"; ``include_cached=True`` switches to the historical
audit view and sums retained cached ``llm_call`` costs.

For one-level reads (immediate children of a single event) direct dict
access is allowed and preferred. These traversal views are for recursive
work across the trace tree; flat per-event work doesn't need them.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, overload

EventTier = Literal["top", "batch_item", "sub_workflow_descendant"]


@overload
def normalize_workflow_path_key(path: None) -> None: ...


@overload
def normalize_workflow_path_key(path: str) -> str: ...


def normalize_workflow_path_key(path: str | None) -> str | None:
    """Normalize workflow-path identifiers used as trace/analyzer join keys."""
    if path is None or path.startswith("ir-hash:"):
        return path
    normalized = path.replace("\\", "/")
    if not normalized:
        return normalized
    drive_match = re.match(r"^([A-Za-z]:)(/.*)?$", normalized)
    if drive_match:
        drive = drive_match.group(1)
        tail = drive_match.group(2) or "/"
        return f"{drive}{posixpath.normpath(tail)}"
    return posixpath.normpath(normalized)


def _is_absolute_workflow_path_key(path: str) -> bool:
    return path.startswith("/") or re.match(r"^[A-Za-z]:/", path) is not None


@dataclass(frozen=True)
class WalkEvent:
    """One trace event yielded by :meth:`TraceTree.walk`.

    Carries the event itself plus traversal context: the closest top-level
    or batch parent's id (``owner_node_id``), the tier, and the optional
    workflow_path threaded via ``edges``.
    """

    event: Mapping[str, Any]
    owner_node_id: str
    tier: EventTier
    workflow_path: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "workflow_path", normalize_workflow_path_key(self.workflow_path))

    @property
    def is_cached(self) -> bool:
        return self.event.get("status") == "cached"

    @property
    def has_llm_call(self) -> bool:
        return isinstance(self.event.get("llm_call"), Mapping)

    @property
    def llm_call(self) -> Mapping[str, Any] | None:
        call = self.event.get("llm_call")
        return call if isinstance(call, Mapping) else None

    @property
    def event_node_id(self) -> str:
        return str(self.event.get("node_id", "unknown"))


# Backward-compat alias — earlier API was LLM-leaf specific.
LlmEventLeaf = WalkEvent


@dataclass(frozen=True)
class TraceTree:
    """Read-only view of a workflow trace.

    Format-version validation belongs to callers because CLI/MCP loaders own
    their exit-code contracts. This class validates only the tree shape it
    traverses.

    ``default_edges`` (``{node_id: child_workflow_path}``) is auto-derived from
    the trace itself by reading every event's ``node_output._pflow_child_workflow_paths``.
    :meth:`walk` uses these by default so the common ``tree.walk(workflow_path=root)``
    case correctly attributes ``sub_workflow_events`` to their child workflow.
    Callers that have richer attribution (e.g. the cross-workflow analyzer, which
    also knows IR-static children that didn't execute) pass ``edges=`` to layer
    on top — caller's mapping wins on conflict.
    """

    events: tuple[Mapping[str, Any], ...]
    format_version: str = ""
    default_edges: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, trace_data: Mapping[str, Any]) -> TraceTree:
        nodes = trace_data.get("nodes")
        if nodes is None:
            events: tuple[Mapping[str, Any], ...] = ()
        elif isinstance(nodes, list):
            events = tuple(event for event in nodes if isinstance(event, Mapping))
        else:
            raise ValueError(f"trace nodes must be a list, got {type(nodes).__name__}")
        return cls(
            events=events,
            format_version=str(trace_data.get("format_version", "")),
            default_edges=_collect_default_edges(events),
        )

    def event_for(self, node_id: str, *, requires_llm_call: bool = False) -> Mapping[str, Any] | None:
        """Return a top-level event by node id.

        ``requires_llm_call`` preserves the token-estimation contract for traces
        with multiple events for one node id: skip non-LLM events until an event
        with ``llm_call`` is found.
        """
        for event in self.events:
            if event.get("node_id") != node_id:
                continue
            if requires_llm_call and not isinstance(event.get("llm_call"), Mapping):
                continue
            return event
        return None

    def walk(
        self,
        events: Iterable[Mapping[str, Any]] | None = None,
        *,
        descend_sub_workflows: bool = True,
        descend_cached_subtrees: bool = True,
        edges: Mapping[str, str] | None = None,
        owner_node_id: str | None = None,
        workflow_path: str | None = None,
        _tier: EventTier = "top",
    ) -> Iterator[WalkEvent]:
        """Yield every event in the trace tree.

        Recursion descends into ``batch_items`` (a single level — batch items
        are events themselves), into the sub-workflow events nested under each
        batch item's ``events`` list, and into the parent's
        ``sub_workflow_events`` list. ``event["events"]`` at the top level is
        NOT recursed (vestigial — sole producer is batch items, which are
        reached via ``batch_items`` already).

        Cached-subtree policy: when ``descend_cached_subtrees=False`` cached
        events (top-level or batch-item) are skipped entirely (not yielded,
        not recursed). The runtime producer summaries set this so cached
        parents don't pollute cost aggregation.

        Workflow_path threading: when ``edges`` is provided, descending into
        ``sub_workflow_events`` looks up the parent's id in ``edges`` to find
        the child's workflow_path. Yielded events carry that workflow_path.
        For 2.1 traces (no per-event ``workflow_path`` field), this is the
        only attribution mechanism.

        Default edges: at top-level entry (``events`` is ``None``), the tree's
        ``default_edges`` (auto-derived from ``_pflow_child_workflow_paths``)
        are merged with the caller's ``edges``. The caller's mapping wins on
        conflict so explicit IR-derived attribution stays authoritative.
        """
        if events is None:
            merged: dict[str, str] = dict(self.default_edges)
            if edges:
                merged.update(edges)
            edges = merged
        source = self.events if events is None else events
        for raw_event in source:
            if not isinstance(raw_event, Mapping):
                continue
            if raw_event.get("status") == "cached" and not descend_cached_subtrees:
                continue

            event_node_id = str(raw_event.get("node_id", owner_node_id or "unknown"))
            leaf_owner = owner_node_id or event_node_id
            yield WalkEvent(
                event=raw_event,
                owner_node_id=leaf_owner,
                tier=_tier,
                workflow_path=workflow_path,
            )

            for item in raw_event.get("batch_items") or []:
                if not isinstance(item, Mapping):
                    continue
                if item.get("status") == "cached" and not descend_cached_subtrees:
                    continue
                # Per-item attribution priority for batch_items:
                # 1. ``workflow_path`` — canonical child path recorded after
                #    runtime sub-workflow resolution.
                # 2. ``template_resolutions["workflow"]["resolved"]`` —
                #    older heterogeneous-batch traces only. Normalized when
                #    relative and the parent workflow path is absolute.
                # 3. ``edges.get(event_node_id)`` — analyzer-resolved absolute
                #    child path for HOMOGENEOUS workflow batches (static
                #    ``workflow: ./child.pflow.md`` over ``items: [...]``).
                #    These items have no ``template_resolutions["workflow"]``
                #    because the workflow ref is static, not templated.
                # 4. Inherited ``workflow_path`` — final fallback for
                #    non-workflow batches and unattributed cases.
                item_workflow_path = (
                    _child_workflow_path_from_batch_item(item, parent_workflow_path=workflow_path)
                    or (edges.get(event_node_id) if edges is not None else None)
                    or workflow_path
                )
                yield WalkEvent(
                    event=item,
                    owner_node_id=event_node_id,
                    tier="batch_item",
                    workflow_path=item_workflow_path,
                )
                yield from self.walk(
                    _mapping_events(item.get("events")),
                    descend_sub_workflows=descend_sub_workflows,
                    descend_cached_subtrees=descend_cached_subtrees,
                    edges=edges,
                    owner_node_id=event_node_id,
                    workflow_path=item_workflow_path,
                    _tier="sub_workflow_descendant",
                )

            if descend_sub_workflows:
                # Sub-workflow attribution: ``edges`` (parent_node_id →
                # resolved-absolute child path, derived from the analyzer's
                # cross-workflow walker) is the canonical source. Falls back
                # to inherited ``workflow_path`` when ``edges`` has nothing.
                # Trace metadata's ``node_params.workflow`` is intentionally
                # NOT used here — it stores the raw IR string (often relative,
                # e.g. ``./child.pflow.md``) which would not match the
                # analyzer's resolved-absolute keys.
                child_workflow_path = edges.get(event_node_id) if edges is not None else workflow_path
                yield from self.walk(
                    _mapping_events(raw_event.get("sub_workflow_events")),
                    descend_sub_workflows=True,
                    descend_cached_subtrees=descend_cached_subtrees,
                    edges=edges,
                    owner_node_id=event_node_id,
                    workflow_path=child_workflow_path,
                    _tier="sub_workflow_descendant",
                )

    def iter_llm_leaves(
        self,
        events: Iterable[Mapping[str, Any]] | None = None,
        *,
        descend_sub_workflows: bool = True,
        descend_cached_subtrees: bool = True,
        edges: Mapping[str, str] | None = None,
        owner_node_id: str | None = None,
        workflow_path: str | None = None,
        _tier: EventTier = "top",
    ) -> Iterator[WalkEvent]:
        """Yield only events carrying ``llm_call`` — filter over :meth:`walk`."""
        return (
            we
            for we in self.walk(
                events,
                descend_sub_workflows=descend_sub_workflows,
                descend_cached_subtrees=descend_cached_subtrees,
                edges=edges,
                owner_node_id=owner_node_id,
                workflow_path=workflow_path,
                _tier=_tier,
            )
            if we.has_llm_call
        )

    def iter_actual_cost_events(
        self,
        events: Iterable[Mapping[str, Any]] | None = None,
        *,
        descend_sub_workflows: bool = True,
        edges: Mapping[str, str] | None = None,
        owner_node_id: str | None = None,
        workflow_path: str | None = None,
        _tier: EventTier = "top",
    ) -> Iterator[WalkEvent]:
        """Yield events that contribute evidence to this run's LLM cost.

        Cached LLM events are paid-cost boundaries: yield the cached boundary
        itself as known zero-cost evidence and do not descend into its
        historical children. Cached non-LLM events without LLM descendants do
        not contribute LLM cost evidence. Non-cached events yield their LLM
        calls and recurse normally.

        Default edges: at top-level entry, merges :attr:`default_edges` with
        the caller's ``edges`` (caller wins on conflict). See :meth:`walk`.
        """
        if events is None:
            merged: dict[str, str] = dict(self.default_edges)
            if edges:
                merged.update(edges)
            edges = merged
        source = self.events if events is None else events
        for raw_event in source:
            if not isinstance(raw_event, Mapping):
                continue
            yield from self._iter_actual_cost_event(
                raw_event,
                descend_sub_workflows=descend_sub_workflows,
                edges=edges,
                owner_node_id=owner_node_id,
                workflow_path=workflow_path,
                tier=_tier,
                assume_llm_event=False,
            )

    def cost_for_event(self, event: Mapping[str, Any], *, include_cached: bool = False) -> tuple[float | None, str]:
        """Return recorded cost for one event subtree, including child workflows.

        Cached policy: cached events are paid-cost boundaries. Default mode
        returns what this run paid, so cached LLM subtrees contribute observed
        zero cost and historical descendants are not traversed. Diagnostic
        mode (``include_cached=True``) traverses cached descendants and sums
        retained historical costs.
        """
        if include_cached:
            return self._sum_leaves(self.iter_llm_leaves((event,)))
        return self.sum_actual_cost_events(self.iter_actual_cost_events((event,)))

    def cost_for_node(self, node_id: str, *, include_cached: bool = False) -> tuple[float | None, str]:
        """Return recorded cost for one top-level node, excluding sub-workflows.

        Cached policy: see :meth:`cost_for_event`.
        """
        event = self.event_for(node_id)
        if event is None:
            return None, "unavailable"
        if include_cached:
            return self._sum_leaves(self.iter_llm_leaves((event,), descend_sub_workflows=False))
        return self.sum_actual_cost_events(self.iter_actual_cost_events((event,), descend_sub_workflows=False))

    def cost_for_batch_item(self, item: Mapping[str, Any], *, include_cached: bool = False) -> tuple[float | None, str]:
        """Return recorded cost for one batch item dict.

        Batch items differ in shape from real events: they lack ``node_id``
        at the top level and store sub-workflow children under ``events``
        (not ``sub_workflow_events``). Callers like the trace report's
        batch-item summary table pass batch items here directly so the
        shape difference is handled in one place rather than via
        shape-sniffing at every call site.

        Cached policy: see :meth:`cost_for_event`.
        """
        if include_cached:
            leaves: list[WalkEvent] = []
            if isinstance(item.get("llm_call"), Mapping):
                leaves.append(
                    WalkEvent(
                        event=item,
                        owner_node_id=str(item.get("node_id", item.get("index", "?"))),
                        tier="batch_item",
                    )
                )
            for sub_event in _mapping_events(item.get("events")):
                leaves.extend(we for we in self.walk((sub_event,), _tier="sub_workflow_descendant") if we.has_llm_call)
            return self._sum_leaves(leaves)

        return self.sum_actual_cost_events(
            self._iter_actual_cost_batch_item(
                item,
                owner_node_id=str(item.get("node_id", item.get("index", "?"))),
                workflow_path=None,
                descend_sub_workflows=True,
                edges=None,
                assume_llm_event=True,
            )
        )

    def total_cost(
        self,
        *,
        descend_sub_workflows: bool = True,
        include_cached: bool = False,
        edges: Mapping[str, str] | None = None,
    ) -> tuple[float | None, str]:
        """Return recorded LLM cost across the trace."""
        leaves = self.iter_llm_leaves(
            descend_sub_workflows=descend_sub_workflows,
            edges=edges,
        )
        if include_cached:
            return self._sum_leaves(leaves)
        return self.sum_actual_cost_events(
            self.iter_actual_cost_events(
                descend_sub_workflows=descend_sub_workflows,
                edges=edges,
            )
        )

    def _iter_actual_cost_event(
        self,
        event: Mapping[str, Any],
        *,
        descend_sub_workflows: bool,
        edges: Mapping[str, str] | None,
        owner_node_id: str | None,
        workflow_path: str | None,
        tier: EventTier,
        assume_llm_event: bool,
    ) -> Iterator[WalkEvent]:
        event_node_id = str(event.get("node_id", owner_node_id or "unknown"))
        leaf_owner = owner_node_id or event_node_id
        if event.get("status") == "cached":
            if _has_llm_cost_evidence(
                event,
                assume_llm_event=assume_llm_event,
                descend_sub_workflows=descend_sub_workflows,
            ):
                event_workflow_path = workflow_path
                if descend_sub_workflows and event.get("sub_workflow_events") and edges is not None:
                    event_workflow_path = edges.get(event_node_id, workflow_path)
                yield WalkEvent(event=event, owner_node_id=leaf_owner, tier=tier, workflow_path=event_workflow_path)
            return

        event_is_llm = _is_llm_like_event(event, assume_llm_event=assume_llm_event)
        if isinstance(event.get("llm_call"), Mapping):
            yield WalkEvent(event=event, owner_node_id=leaf_owner, tier=tier, workflow_path=workflow_path)

        for item in event.get("batch_items") or []:
            if not isinstance(item, Mapping):
                continue
            item_workflow_path = (
                _child_workflow_path_from_batch_item(item, parent_workflow_path=workflow_path)
                or (edges.get(event_node_id) if edges is not None else None)
                or workflow_path
            )
            yield from self._iter_actual_cost_batch_item(
                item,
                owner_node_id=event_node_id,
                workflow_path=item_workflow_path,
                descend_sub_workflows=descend_sub_workflows,
                edges=edges,
                assume_llm_event=event_is_llm,
            )

        if descend_sub_workflows:
            child_workflow_path = edges.get(event_node_id) if edges is not None else workflow_path
            for sub_event in _mapping_events(event.get("sub_workflow_events")):
                yield from self._iter_actual_cost_event(
                    sub_event,
                    descend_sub_workflows=True,
                    edges=edges,
                    owner_node_id=event_node_id,
                    workflow_path=child_workflow_path,
                    tier="sub_workflow_descendant",
                    assume_llm_event=False,
                )

    def _iter_actual_cost_batch_item(
        self,
        item: Mapping[str, Any],
        *,
        owner_node_id: str,
        workflow_path: str | None,
        descend_sub_workflows: bool,
        edges: Mapping[str, str] | None,
        assume_llm_event: bool,
    ) -> Iterator[WalkEvent]:
        if item.get("status") == "cached":
            if _has_llm_cost_evidence(
                item,
                assume_llm_event=assume_llm_event,
                descend_sub_workflows=descend_sub_workflows,
                batch_item=True,
            ):
                yield WalkEvent(event=item, owner_node_id=owner_node_id, tier="batch_item", workflow_path=workflow_path)
            return

        if isinstance(item.get("llm_call"), Mapping):
            yield WalkEvent(event=item, owner_node_id=owner_node_id, tier="batch_item", workflow_path=workflow_path)

        if descend_sub_workflows:
            for sub_event in _mapping_events(item.get("events")):
                yield from self._iter_actual_cost_event(
                    sub_event,
                    descend_sub_workflows=True,
                    edges=edges,
                    owner_node_id=owner_node_id,
                    workflow_path=workflow_path,
                    tier="sub_workflow_descendant",
                    assume_llm_event=False,
                )

    @staticmethod
    def sum_actual_cost_events(events: Iterable[WalkEvent]) -> tuple[float | None, str]:
        total = 0.0
        found_any = False
        has_unpriced = False
        for event in events:
            if event.is_cached:
                found_any = True
                continue
            call = event.llm_call
            if call is None or "cost_usd" not in call:
                continue
            found_any = True
            cost = call.get("cost_usd")
            if cost is None:
                has_unpriced = True
            else:
                total += float(cost)
        if not found_any:
            return None, "unavailable"
        if has_unpriced:
            return total, "trace_partial"
        return total, "trace"

    @staticmethod
    def _sum_leaves(leaves: Iterable[WalkEvent]) -> tuple[float | None, str]:
        total = 0.0
        found_any = False
        has_unpriced = False
        for leaf in leaves:
            call = leaf.llm_call
            if call is None or "cost_usd" not in call:
                continue
            found_any = True
            cost = call.get("cost_usd")
            if cost is None:
                has_unpriced = True
            else:
                total += float(cost)
        if not found_any:
            return None, "unavailable"
        if has_unpriced:
            return total, "trace_partial"
        return total, "trace"


def event_cost(event: Mapping[str, Any], *, include_cached: bool = False) -> float | None:
    """Recorded cost for one event subtree, or ``None`` when there's no priced cost.

    The policy-applying wrapper over :meth:`TraceTree.cost_for_event`: it
    collapses that method's ``(cost, source)`` pair to a single ``float | None``
    so every reader (the report, the live-overlay hover chip, the detail panel)
    renders "no cost" identically and can't drift on what it means. ``None`` is
    returned both when no cost data exists anywhere in the subtree
    (``unavailable``) AND when any leaf is unpriced — ``cost_usd: None`` for an
    Ollama/custom-endpoint model (``trace_partial``); the unpriced case
    propagates as ``None`` rather than silently dropping its contribution.
    Returns ``0.0`` only when every leaf is explicitly priced at zero — e.g. a
    cached node, which paid nothing this run (its retained ``llm_call`` cost is
    the SOURCE call's, not this run's).

    For batch items (no top-level ``node_id``; children under ``events``), use
    :func:`batch_item_cost`.
    """
    cost, source = TraceTree(events=(event,), format_version="2.1").cost_for_event(event, include_cached=include_cached)
    return None if source in {"trace_partial", "unavailable"} else cost


def batch_item_cost(item: Mapping[str, Any]) -> float | None:
    """Recorded cost for one batch-item dict, or ``None`` when there's no priced cost.

    The batch-item counterpart of :func:`event_cost` (same ``None`` policy).
    Batch items differ in shape from real events — no top-level ``node_id``,
    sub-workflow children under ``events`` not ``sub_workflow_events`` — so this
    routes through :meth:`TraceTree.cost_for_batch_item`. The empty
    ``events=()`` is deliberate: ``cost_for_batch_item`` walks the ``item``
    passed to it, not ``self.events``.
    """
    cost, source = TraceTree(events=(), format_version="2.1").cost_for_batch_item(item)
    return None if source in {"trace_partial", "unavailable"} else cost


def _mapping_events(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _collect_default_edges(events: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """Derive ``{node_id: child_workflow_path}`` from a trace event tree.

    Reads ``node_output._pflow_child_workflow_paths`` on every event in the
    tree (top-level, batch items, sub-workflow descendants). The runtime
    populates that field for every WorkflowExecutor invocation that succeeds
    in resolving its child workflow path — see ``runtime/workflow_executor.py
    ::_record_child_workflow_path``.

    Used as the default ``edges`` argument for :meth:`TraceTree.walk` so the
    common case (no explicit edges from a cross-workflow analyzer) still
    attributes child events to the correct workflow path. Callers that have
    additional IR-static knowledge layer their own ``edges=`` on top.
    """
    edges: dict[str, str] = {}

    def visit(items: Iterable[Mapping[str, Any]]) -> None:
        for event in items:
            if not isinstance(event, Mapping):
                continue
            node_output = event.get("node_output")
            if isinstance(node_output, Mapping):
                paths = node_output.get("_pflow_child_workflow_paths")
                if isinstance(paths, Mapping):
                    for node_id, path in paths.items():
                        if isinstance(node_id, str) and isinstance(path, str) and path:
                            edges[node_id] = normalize_workflow_path_key(path) or path
            # Recurse into batch items + their nested events
            for item in event.get("batch_items") or []:
                if isinstance(item, Mapping):
                    visit([item])
                    visit(_mapping_events(item.get("events")))
            # Recurse into sub_workflow_events
            visit(_mapping_events(event.get("sub_workflow_events")))

    visit(events)
    return edges


def _is_llm_like_event(event: Mapping[str, Any], *, assume_llm_event: bool) -> bool:
    return assume_llm_event or event.get("node_type") == "LLMNode" or isinstance(event.get("llm_call"), Mapping)


def _has_llm_cost_evidence(
    event: Mapping[str, Any],
    *,
    assume_llm_event: bool,
    descend_sub_workflows: bool,
    batch_item: bool = False,
) -> bool:
    if _is_llm_like_event(event, assume_llm_event=assume_llm_event):
        return True

    parent_is_llm = _is_llm_like_event(event, assume_llm_event=assume_llm_event)
    for item in event.get("batch_items") or []:
        if isinstance(item, Mapping) and _has_llm_cost_evidence(
            item,
            assume_llm_event=parent_is_llm,
            descend_sub_workflows=descend_sub_workflows,
            batch_item=True,
        ):
            return True

    if not descend_sub_workflows:
        return False

    child_events = _mapping_events(event.get("events") if batch_item else event.get("sub_workflow_events"))
    return any(
        _has_llm_cost_evidence(
            child_event,
            assume_llm_event=False,
            descend_sub_workflows=True,
        )
        for child_event in child_events
    )


def _child_workflow_path_from_batch_item(
    event: Mapping[str, Any],
    *,
    parent_workflow_path: str | None,
) -> str | None:
    """Return a canonical-ish child workflow path from a batch item.

    New traces record ``workflow_path`` after ``resolve_sub_workflow`` runs.
    Older heterogeneous workflow-batch traces only have the generic template
    resolution value, which may be relative. Normalize that older value when
    the parent workflow path gives us an absolute directory.
    """
    explicit = event.get("workflow_path")
    if isinstance(explicit, str) and explicit:
        return normalize_workflow_path_key(explicit)

    resolved = _resolved_child_workflow_from_event(event)
    if resolved is None:
        return None
    return _resolve_relative_child_workflow_path(resolved, parent_workflow_path=parent_workflow_path)


def _resolved_child_workflow_from_event(event: Mapping[str, Any]) -> str | None:
    """Extract the template-resolved child workflow reference from an event.

    Source: ``template_resolutions["workflow"]["resolved"]`` — present per
    batch_item when the parent workflow-type node's ``workflow:`` references
    a template (``${item.workflow}`` in heterogeneous batches). This is a
    generic template-resolution value, not necessarily a canonical workflow
    path; older traces may store relative refs here.

    Returns ``None`` for events without this metadata. Note: deliberately
    does NOT fall back to ``node_params["workflow"]`` — that field stores
    the RAW IR string (often relative, e.g. ``./child.pflow.md``) which
    would not match the analyzer's resolved-absolute path keys. The
    ``edges`` fallback in :meth:`TraceTree.walk` provides resolved-absolute
    attribution for static (non-template) sub-workflow refs.
    """
    resolutions = event.get("template_resolutions")
    if isinstance(resolutions, Mapping):
        wf = resolutions.get("workflow")
        if isinstance(wf, Mapping):
            resolved = wf.get("resolved")
            if isinstance(resolved, str) and resolved:
                return resolved
    return None


def _resolve_relative_child_workflow_path(resolved: str, *, parent_workflow_path: str | None) -> str:
    resolved_key = normalize_workflow_path_key(resolved) or resolved
    if _is_absolute_workflow_path_key(resolved_key):
        return resolved_key
    parent_key = normalize_workflow_path_key(parent_workflow_path)
    if not parent_key or not _is_absolute_workflow_path_key(parent_key):
        return resolved_key
    return normalize_workflow_path_key(posixpath.join(posixpath.dirname(parent_key), resolved_key)) or resolved_key


__all__ = [
    "LlmEventLeaf",
    "TraceTree",
    "WalkEvent",
    "batch_item_cost",
    "event_cost",
    "normalize_workflow_path_key",
]
