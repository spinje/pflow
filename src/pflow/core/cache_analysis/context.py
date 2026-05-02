"""Read-only inputs threaded through the analyzer's helper graph.

Replaces the 5-tuple ``(workflow_ir, parameters, memo_cache, trace_data,
workflow_path, base_path)`` that was passed by-keyword to ~30 call sites in
:mod:`analyze`. Same pattern as ``execution/plan.py::_WalkerState`` — bundle
the invariant inputs, reduce signature noise.

Three load-bearing methods consolidate the policy that was previously
scattered across helpers:

- :meth:`AnalysisContext.trace_event_for` — lookup the top-level trace event
  for a node_id (None when no event found).
- :meth:`AnalysisContext.cost_usd_for_node` — sum the recorded ``cost_usd``
  values from a node's trace event tree (top-level llm_call + batch_items).
  Used by Track A so the analyzer reports the same number the workflow
  actually paid (instead of recomputing from ``tokens x full_rate`` which
  ignores implicit caching like Gemini's).
- :meth:`AnalysisContext.resolve_ref_value` — resolve a template ref to its
  latest known value. Workflow inputs win from ``parameters`` (current
  question wins over historical memo); node outputs come from memo only.

Layer policy: this module imports from :mod:`pflow.runtime.template_resolver`
lazily (inside the resolver method) to keep import cost low — the analyzer
package is import-cheap on purpose.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalysisContext:
    """Immutable inputs threaded through the analyzer's helper graph.

    Parameters reach this object **post type-coercion** (via
    ``coerce_workflow_input`` at the CLI boundary). Raw CLI strings are NOT
    stored here — int-typed inputs are int, string-typed inputs are string.
    """

    workflow_ir: Mapping[str, Any]
    parameters: Mapping[str, Any] = field(default_factory=dict)
    memo_cache: Any | None = None
    trace_data: Mapping[str, Any] | None = None
    workflow_path: str | None = None
    base_path: Path | None = None

    # ------------------------------------------------------------------
    # Trace event lookup
    # ------------------------------------------------------------------

    def trace_event_for(self, node_id: str) -> Mapping[str, Any] | None:
        """Top-level trace event dict for ``node_id``, or None.

        Non-recursive — sub-workflow / batch-item events are accessed via
        dedicated walkers (see :meth:`cost_usd_for_node` recursion). The
        trace JSON's top-level events list is keyed ``"nodes"`` (see
        ``runtime/workflow_trace.WorkflowTraceCollector.save_to_file``).
        """
        if self.trace_data is None:
            return None
        events = self.trace_data.get("nodes")
        if not isinstance(events, list):
            return None
        for event in events:
            if isinstance(event, dict) and event.get("node_id") == node_id:
                return event
        return None

    # ------------------------------------------------------------------
    # Cost extraction (Track A)
    # ------------------------------------------------------------------

    def cost_usd_for_node(self, node_id: str) -> tuple[float | None, str]:
        """Per-node recorded cost from trace (3-state).

        Returns ``(cost, source)``:

        - ``(float, "trace")``: priced; sum of llm_call + batch_items[*].llm_call
          costs. Cached events contribute 0.0 explicitly (this run paid 0
          for that item — NOT excluded as "unavailable").
        - ``(float, "trace_partial")``: at least one leaf had ``cost_usd=None``
          (unpriced model). The float is the priced subset; caller upgrades
          to recompute for unpriced leaves OR surfaces partial.
        - ``(None, "unavailable")``: no event found for this node_id, or
          no trace data loaded at all.

        Recursion: top-level llm_call + batch_items[*].llm_call. Does NOT
        descend into ``sub_workflow_events`` (per-call rows iterate
        ``type:llm`` only; sub-workflow internals are scoped to their own
        analyze-cache invocation).
        """
        event = self.trace_event_for(node_id)
        if event is None:
            return None, "unavailable"

        # Cached events (cache hit — skipped LLM execution) carry NO
        # ``llm_call`` field but still represent a real outcome: this run
        # paid 0 for the LLM call. Treat as ``(0.0, "trace")`` so a
        # fully-cached rerun reports ``current_cost = $0.00 (trace)``
        # instead of falling back to recompute / unavailable. Mirrors the
        # production trace producer at ``workflow_trace.py:312`` which
        # marks cached events explicitly.
        if event.get("cached") and event.get("llm_call") is None and not (event.get("batch_items") or []):
            return 0.0, "trace"

        total, found_any, has_unpriced = _walk_event_for_cost(event)

        if not found_any:
            return None, "unavailable"
        if has_unpriced:
            # Some leaves priced, others unpriced — caller handles the mix.
            return float(total), "trace_partial"
        return float(total), "trace"

    # ------------------------------------------------------------------
    # Template ref resolution (Track B)
    # ------------------------------------------------------------------

    def resolve_ref_value(self, ref: str) -> Any | None:
        """Resolve a single template ref to its latest known value, or None.

        Tier order DEPENDS on whether root is a workflow input or a node:

        - **Root in ``workflow_ir["inputs"]``**: ``parameters`` WINS over
          memo. The agent's --inputs represent their CURRENT question; memo
          from a prior run with different inputs MUST NOT override.
        - **Root is a node id**: memo only. Parameters never reach here
          because node outputs aren't passable as --inputs.

        Empty-value handling: returns ``None`` for empty string, empty dict,
        empty list. Distinct from "we have a real value" — propagates as
        Tier-4 unavailable to avoid false ~0-token projections.
        """
        # Lazy-import keeps this module layer-clean.
        from pflow.runtime.template_resolver import TemplateResolver

        root = TemplateResolver.extract_root_node_id(ref)
        if not root:
            return None

        declared_inputs = self.workflow_ir.get("inputs") if isinstance(self.workflow_ir, Mapping) else None
        if isinstance(declared_inputs, Mapping) and root in declared_inputs:
            value = self._resolve_from_parameters(ref, root)
            if value is not None:
                return value
            # Parameters didn't supply it (or supplied empty) — fall through
            # to memo if any. Memo for a workflow-input root is unusual but
            # not impossible (some adapters seed it).

        # Node-output root (or workflow-input not in parameters): consult memo.
        return self._resolve_from_memo(ref, root)

    def _resolve_from_parameters(self, ref: str, root: str) -> Any | None:
        """Resolve ``ref`` against ``self.parameters`` for a workflow-input root."""
        if root not in self.parameters:
            return None
        from pflow.runtime.template_resolver import TemplateResolver

        # Wrap the input value so TemplateResolver can navigate dotted paths.
        # ``parameters[root]`` is the resolved value (post-coercion); for a
        # bare ``${root}`` ref this returns the value directly. Sub-paths
        # (``${root.field}``) are navigated through the value's dict shape.
        try:
            resolved = TemplateResolver.resolve_template(f"${{{ref}}}", {root: self.parameters[root]})
        except Exception:
            logger.debug("parameters resolve failed for %s", ref, exc_info=True)
            return None
        if isinstance(resolved, str) and resolved == f"${{{ref}}}":
            # Ref didn't resolve (e.g., dotted path missed). Fall through
            # so memo gets a chance.
            return None
        return _normalize_empty(resolved)

    def _resolve_from_memo(self, ref: str, root: str) -> Any | None:
        """Resolve ``ref`` against memo cache for a node-output root."""
        if self.memo_cache is None:
            return None
        from pflow.runtime.template_resolver import TemplateResolver

        try:
            latest = self.memo_cache.get_latest_for_node(root, workflow_path=self.workflow_path)
        except Exception:
            logger.debug("memo_cache.get_latest_for_node failed for %s", ref, exc_info=True)
            return None
        if latest is None:
            return None
        output, _created_at = latest
        if not isinstance(output, dict):
            return None
        try:
            resolved = TemplateResolver.resolve_template(f"${{{ref}}}", {root: output})
        except Exception:
            logger.debug("memo resolve failed for %s", ref, exc_info=True)
            return None
        if isinstance(resolved, str) and resolved == f"${{{ref}}}":
            return None
        return _normalize_empty(resolved)


def _walk_event_for_cost(event: Mapping[str, Any]) -> tuple[float, bool, bool]:
    """Sum ``llm_call.cost_usd`` across the event tree (top-level + batch items).

    Returns ``(total, found_any, has_unpriced)``. ``found_any`` is True if
    at least one priced or unpriced leaf was visited. ``has_unpriced`` is
    True if at least one leaf had ``cost_usd: None`` (unpriced model).
    Cached batch items contribute to ``found_any`` (priced-at-zero) without
    inflating the sum.

    Does NOT recurse into ``sub_workflow_events`` — sub-workflow internals
    are scoped to their own analyze-cache invocation (see GH #365).
    """
    total = 0.0
    found_any = False
    has_unpriced = False

    def _accumulate(call: Any) -> None:
        nonlocal total, found_any, has_unpriced
        if not isinstance(call, dict) or "cost_usd" not in call:
            return
        found_any = True
        cost = call.get("cost_usd")
        if cost is None:
            has_unpriced = True
        else:
            total += float(cost)

    _accumulate(event.get("llm_call"))
    for item in event.get("batch_items") or []:
        if not isinstance(item, dict):
            continue
        if item.get("cached") and item.get("llm_call") is None:
            # Cached batch item — this run paid 0 for it. Count as
            # priced-at-zero so the whole node doesn't degrade to
            # "unavailable" just because one item was cached.
            found_any = True
            continue
        _accumulate(item.get("llm_call"))

    return total, found_any, has_unpriced


def _normalize_empty(value: Any) -> Any | None:
    """Return ``None`` for empty string / empty dict / empty list; else value.

    Empty values would collapse to ~0 tokens through tokenization, falsely
    signaling "we have a real value" when the upstream actually has nothing.
    Returning None pushes the caller to Tier-4 unavailable — honest signal.
    """
    if value is None:
        return None
    if isinstance(value, (str, list, dict, tuple, set)) and not value:
        return None
    return value


__all__ = ["AnalysisContext"]
