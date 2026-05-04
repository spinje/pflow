"""Read-only traversal helpers for pflow workflow traces.

Trace JSON has a small tree shape: top-level events, batch items inside an
event, sub-workflow events nested under a parent event. Consumers need
different policies (some skip cached subtrees, some recurse into sub-
workflows, some stay shallow). One primitive — :meth:`TraceTree.walk` —
yields every event in the tree; everything else (LLM-only filter, cost
summation, batch-item cost, total cost) is a thin layer on top.

For one-level reads (immediate children of a single event) direct dict
access is allowed and preferred. The walker primitive is for recursive
traversal across the tree shape; flat per-event work doesn't need it.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

EventTier = Literal["top", "batch_item", "sub_workflow_descendant"]


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

    @property
    def is_cached(self) -> bool:
        return bool(self.event.get("cached"))

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
    """

    events: tuple[Mapping[str, Any], ...]
    format_version: str = ""

    @classmethod
    def from_dict(cls, trace_data: Mapping[str, Any]) -> TraceTree:
        nodes = trace_data.get("nodes")
        if nodes is None:
            events: tuple[Mapping[str, Any], ...] = ()
        elif isinstance(nodes, list):
            events = tuple(event for event in nodes if isinstance(event, Mapping))
        else:
            raise ValueError(f"trace nodes must be a list, got {type(nodes).__name__}")
        return cls(events=events, format_version=str(trace_data.get("format_version", "")))

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
        """
        source = self.events if events is None else events
        for raw_event in source:
            if not isinstance(raw_event, Mapping):
                continue
            if raw_event.get("cached") and not descend_cached_subtrees:
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
                if item.get("cached") and not descend_cached_subtrees:
                    continue
                yield WalkEvent(
                    event=item,
                    owner_node_id=event_node_id,
                    tier="batch_item",
                    workflow_path=workflow_path,
                )
                yield from self.walk(
                    _mapping_events(item.get("events")),
                    descend_sub_workflows=descend_sub_workflows,
                    descend_cached_subtrees=descend_cached_subtrees,
                    edges=edges,
                    owner_node_id=event_node_id,
                    workflow_path=workflow_path,
                    _tier="sub_workflow_descendant",
                )

            if descend_sub_workflows:
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

    def cost_for_event(self, event: Mapping[str, Any]) -> tuple[float | None, str]:
        """Return recorded cost for one event subtree, including child workflows."""
        if event.get("cached") and event.get("llm_call") is None and not (event.get("batch_items") or []):
            return 0.0, "trace"
        return self._sum_leaves(self.iter_llm_leaves((event,)))

    def cost_for_node(self, node_id: str) -> tuple[float | None, str]:
        """Return recorded cost for one top-level node, excluding sub-workflows."""
        event = self.event_for(node_id)
        if event is None:
            return None, "unavailable"
        if event.get("cached") and event.get("llm_call") is None and not (event.get("batch_items") or []):
            return 0.0, "trace"
        return self._sum_leaves(self.iter_llm_leaves((event,), descend_sub_workflows=False))

    def cost_for_batch_item(self, item: Mapping[str, Any]) -> tuple[float | None, str]:
        """Return recorded cost for one batch item dict.

        Batch items differ in shape from real events: they lack ``node_id``
        at the top level and store sub-workflow children under ``events``
        (not ``sub_workflow_events``). Callers like the trace report's
        batch-item summary table pass batch items here directly so the
        shape difference is handled in one place rather than via
        shape-sniffing at every call site.
        """
        if item.get("cached") and item.get("llm_call") is None and not (item.get("batch_items") or []):
            return 0.0, "trace"

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
        return self._sum_leaves(leaf for leaf in leaves if not leaf.is_cached)

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


def _mapping_events(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


__all__ = ["LlmEventLeaf", "TraceTree", "WalkEvent"]
