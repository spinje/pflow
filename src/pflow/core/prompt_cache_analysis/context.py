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
from typing import Any, Final

from pflow.core.trace_tree import TraceTree

logger = logging.getLogger(__name__)

_PREDICTION_SKIPPED: Final[str] = "__PREDICTION_SKIPPED__"
"""Cache-key prediction was attempted but intentionally skipped for this node."""


def template_resolver() -> Any:
    """Lazy-imported ``TemplateResolver`` class for ``${var}`` resolution.

    Do not hoist this import. ``pflow.runtime.template_resolver`` transitively
    loads the runtime stack, so importing it at module load would make the
    analyzer package pay that cost on cheap dry-run and inspection paths.
    """
    from pflow.runtime.template_resolver import TemplateResolver

    return TemplateResolver


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
    trace: TraceTree | None = None
    workflow_path: str | None = None
    base_path: Path | None = None
    parameters_by_workflow: Mapping[str | None, Mapping[str, Any]] = field(default_factory=dict)
    trace_outputs_by_key: Mapping[tuple[str | None, str], Any] = field(default_factory=dict)
    predicted_cache_keys: Mapping[tuple[str | None, str], str] = field(default_factory=dict)
    prediction_fidelity_notes: tuple[str, ...] = ()
    # Documented exception to the frozen-context "read-only inputs" rule:
    # these sets are per-analysis accumulators. Memo token/value tiers mutate
    # them so the final summary can report detected stale and uncheckable memo
    # use without threading mutable counters through every estimator signature.
    stale_memo_skipped: set[tuple[str | None, str]] = field(default_factory=set)
    stale_memo_uncheckable: set[tuple[str | None, str]] = field(default_factory=set)

    @classmethod
    def build(
        cls,
        *,
        workflow_ir: Mapping[str, Any],
        parameters: Mapping[str, Any] | None = None,
        memo_cache: Any | None = None,
        trace_data: Mapping[str, Any] | None = None,
        workflow_path: str | None = None,
        base_path: Path | None = None,
        parameters_by_workflow: Mapping[str | None, Mapping[str, Any]] | None = None,
        trace_outputs_by_key: Mapping[tuple[str | None, str], Any] | None = None,
        predicted_cache_keys: Mapping[tuple[str | None, str], str] | None = None,
        prediction_fidelity_notes: tuple[str, ...] = (),
        stale_memo_skipped: set[tuple[str | None, str]] | None = None,
        stale_memo_uncheckable: set[tuple[str | None, str]] | None = None,
    ) -> AnalysisContext:
        """The single construction path. Compiles trace JSON into ``TraceTree`` once.

        Production and test callers ALL go through ``build()``. The dataclass
        ``__init__`` is technically callable directly but doesn't materialize
        ``trace`` from ``trace_data`` — passing raw trace data directly to the
        constructor produces a context where ``ctx.trace is None`` while
        ``ctx.trace_data`` is populated, which is almost certainly a bug in the
        caller. If a future need arises for low-level construction, harden this
        with a sentinel in ``__post_init__`` rather than relying on convention.
        """
        trace: TraceTree | None = None
        if trace_data is not None:
            try:
                trace = TraceTree.from_dict(trace_data)
            except ValueError:
                logger.debug("TraceTree construction failed; analyzer falls back to no trace", exc_info=True)
                trace = None
        return cls(
            workflow_ir=workflow_ir,
            parameters=parameters or {},
            memo_cache=memo_cache,
            trace_data=trace_data,
            trace=trace,
            workflow_path=workflow_path,
            base_path=base_path,
            parameters_by_workflow=parameters_by_workflow or {},
            trace_outputs_by_key=trace_outputs_by_key or {},
            predicted_cache_keys=predicted_cache_keys or {},
            prediction_fidelity_notes=prediction_fidelity_notes,
            stale_memo_skipped=stale_memo_skipped if stale_memo_skipped is not None else set(),
            stale_memo_uncheckable=stale_memo_uncheckable if stale_memo_uncheckable is not None else set(),
        )

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
        return self.trace.event_for(node_id) if self.trace is not None else None

    # ------------------------------------------------------------------
    # Cost extraction (Track A)
    # ------------------------------------------------------------------

    def cost_usd_for_node(self, node_id: str) -> tuple[float | None, str]:
        """Per-node recorded cost from trace (3-state).

        Returns ``(cost, source)``:

        - ``(float, "trace")``: priced; sum of llm_call + batch_items[*].llm_call
          costs. Cached events return ``(0.0, "trace")`` — this run paid $0
          regardless of any historical ``llm_call.cost_usd`` retained on the
          cached blob (NOT excluded as "unavailable").
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
        if self.trace is None:
            return None, "unavailable"
        return self.trace.cost_for_node(node_id)

    def parameters_for_workflow(self, workflow_path: str | None) -> Mapping[str, Any]:
        """Return parameters scoped to one workflow in a cross-workflow analysis."""
        if workflow_path == self.workflow_path:
            return self.parameters
        return self.parameters_by_workflow.get(workflow_path, {})

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

    def resolve_ref_value_in_workflow(
        self,
        ref: str,
        *,
        workflow_path: str | None,
        irs_by_workflow: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> Any | None:
        """Resolve ``ref`` against a specific workflow's scope.

        Workflow-path-parametric form of :meth:`resolve_ref_value` for
        sub-workflow boundary analysis, where the value may live in a parent
        workflow rather than the analyzer root.

        Default behavior preserves the previous cross-workflow mirror helper:
        try workflow-scoped parameters first, with root-parameter fallback,
        then workflow-scoped memo. When ``irs_by_workflow`` is supplied, the
        parameter tier is limited to refs whose root is declared as an input on
        the targeted workflow, matching :meth:`resolve_ref_value`'s
        workflow-input-vs-node-id branching.
        """
        template_resolver_cls = template_resolver()
        root = template_resolver_cls.extract_root_node_id(ref)
        if not root:
            return None

        should_try_parameters = True
        if irs_by_workflow is not None:
            should_try_parameters = False
            target_ir = irs_by_workflow.get(str(workflow_path)) if workflow_path is not None else None
            if isinstance(target_ir, Mapping):
                declared_inputs = target_ir.get("inputs")
                should_try_parameters = isinstance(declared_inputs, Mapping) and root in declared_inputs

        if should_try_parameters:
            value = self._resolve_from_parameters_in_workflow(ref, root, workflow_path=workflow_path)
            if value is not None:
                return value

        return self._resolve_from_memo_in_workflow(ref, root, workflow_path=workflow_path)

    def resolve_ref_value_for_projection(self, ref: str) -> Any | None:
        """Resolve ``ref`` for analyzer projections using trace outputs as evidence.

        This preserves :meth:`resolve_ref_value` for existing memo/parameter
        estimates while allowing projection-only paths to use values observed
        in the loaded trace. Resolution order is current inputs, memo, then
        workflow-scoped trace ``node_output``.
        """
        value = self.resolve_ref_value(ref)
        if value is not None:
            return value

        from pflow.runtime.template_resolver import TemplateResolver

        root = TemplateResolver.extract_root_node_id(ref)
        if not root:
            return None
        output = self.trace_outputs_by_key.get((self.workflow_path, root))
        if output is None:
            output = self.trace_outputs_by_key.get((None, root))
        if output is None:
            return None
        try:
            resolved = TemplateResolver.resolve_template(f"${{{ref}}}", {root: output})
        except Exception:
            logger.debug("trace-output resolve failed for %s", ref, exc_info=True)
            return None
        if isinstance(resolved, str) and resolved == f"${{{ref}}}":
            return None
        return _normalize_empty(resolved)

    def resolve_ref_value_for_projection_in_workflow(
        self,
        ref: str,
        *,
        workflow_path: str | None,
        cw_result: Any,
    ) -> Any | None:
        """Resolve ``ref`` for projections against a specific workflow's scope.

        Extends :meth:`resolve_ref_value_in_workflow` with the trace-output
        tier used by cross-workflow cache recommendations. Last matching trace
        event wins, mirroring trace recovery semantics elsewhere in the
        analyzer.
        """
        irs_by_workflow = getattr(cw_result, "irs_by_workflow", None)
        if not isinstance(irs_by_workflow, Mapping):
            irs_by_workflow = None
        value = self.resolve_ref_value_in_workflow(
            ref,
            workflow_path=workflow_path,
            irs_by_workflow=irs_by_workflow,
        )
        if value is not None:
            return value

        template_resolver_cls = template_resolver()
        root = template_resolver_cls.extract_root_node_id(ref)
        if not root:
            return None

        output = self._trace_node_output_in_workflow(root, workflow_path=workflow_path, cw_result=cw_result)
        if output is None:
            return None
        try:
            resolved = template_resolver_cls.resolve_template(f"${{{ref}}}", {root: output})
        except Exception:
            logger.debug("trace-output resolve failed for %s in %s", ref, workflow_path, exc_info=True)
            return None
        if isinstance(resolved, str) and resolved == f"${{{ref}}}":
            return None
        return _normalize_empty(resolved)

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

    def _resolve_from_parameters_in_workflow(
        self,
        ref: str,
        root: str,
        *,
        workflow_path: str | None,
    ) -> Any | None:
        """Resolve ``ref`` against workflow-scoped parameters.

        Preserves the cross-workflow fallback where a root missing from the
        workflow-scoped parameter view may still resolve from root parameters.
        """
        params = self.parameters_for_workflow(workflow_path)
        if root not in params and root in self.parameters:
            params = self.parameters
        if root not in params:
            return None
        template_resolver_cls = template_resolver()
        try:
            resolved = template_resolver_cls.resolve_template(f"${{{ref}}}", {root: params[root]})
        except Exception:
            logger.debug("parameters resolve failed for %s in %s", ref, workflow_path, exc_info=True)
            return None
        if isinstance(resolved, str) and resolved == f"${{{ref}}}":
            return None
        return _normalize_empty(resolved)

    def _resolve_from_memo(self, ref: str, root: str) -> Any | None:
        """Resolve ``ref`` against memo cache for a node-output root."""
        if self.memo_cache is None:
            return None
        from pflow.runtime.template_resolver import TemplateResolver

        try:
            latest = _latest_memo_for_freshness_check(
                self.memo_cache,
                root,
                workflow_path=self.workflow_path,
                ctx=self,
            )
        except Exception:
            logger.debug("memo cache freshness-aware lookup failed for %s", ref, exc_info=True)
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

    def _resolve_from_memo_in_workflow(
        self,
        ref: str,
        root: str,
        *,
        workflow_path: str | None,
    ) -> Any | None:
        """Resolve ``ref`` against memo cache scoped to ``workflow_path``."""
        if self.memo_cache is None:
            return None
        template_resolver_cls = template_resolver()
        try:
            latest = _latest_memo_for_freshness_check(
                self.memo_cache,
                root,
                workflow_path=workflow_path,
                ctx=self,
            )
        except Exception:
            logger.debug("memo cache freshness-aware lookup failed for %s in %s", ref, workflow_path, exc_info=True)
            return None
        if latest is None:
            return None
        output, _created_at = latest
        if not isinstance(output, dict):
            return None
        try:
            resolved = template_resolver_cls.resolve_template(f"${{{ref}}}", {root: output})
        except Exception:
            logger.debug("memo resolve failed for %s in %s", ref, workflow_path, exc_info=True)
            return None
        if isinstance(resolved, str) and resolved == f"${{{ref}}}":
            return None
        return _normalize_empty(resolved)

    def _trace_node_output_in_workflow(
        self,
        node_id: str,
        *,
        workflow_path: str | None,
        cw_result: Any,
    ) -> dict[str, Any] | None:
        """Latest trace output for ``(workflow_path, node_id)``."""
        if self.trace is None:
            return None
        from .trace_loading import _edge_child_paths

        output: dict[str, Any] | None = None
        for walk_event in self.trace.walk(edges=_edge_child_paths(cw_result), workflow_path=self.workflow_path):
            if walk_event.workflow_path != workflow_path or walk_event.event.get("node_id") != node_id:
                continue
            event_output = walk_event.event.get("node_output")
            if isinstance(event_output, Mapping):
                output = dict(event_output)
                continue
            llm_response = walk_event.event.get("llm_response")
            if isinstance(llm_response, str):
                output = {"response": llm_response}
        return output


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


def _latest_memo_for_freshness_check(
    memo_cache: Any,
    node_id: str,
    *,
    workflow_path: str | None,
    ctx: AnalysisContext,
) -> tuple[dict[str, Any], float] | None:
    """Return latest memo output unless Bundle 6 cache-key comparison marks it stale."""
    if hasattr(memo_cache, "get_latest_for_node_with_cache_key"):
        result = memo_cache.get_latest_for_node_with_cache_key(node_id, workflow_path=workflow_path)
        if result is None:
            return None
        output, created_at, memo_cache_key = result
        predicted = ctx.predicted_cache_keys.get((workflow_path, node_id))
        if predicted is None:
            return output, created_at
        if predicted == _PREDICTION_SKIPPED:
            ctx.stale_memo_uncheckable.add((workflow_path, node_id))
            return output, created_at
        if memo_cache_key != predicted:
            ctx.stale_memo_skipped.add((workflow_path, node_id))
            return None
        return output, created_at
    result = memo_cache.get_latest_for_node(node_id, workflow_path=workflow_path)
    if result is None:
        return None
    output, created_at = result
    if not isinstance(output, dict):
        return None
    return output, created_at


__all__ = ["_PREDICTION_SKIPPED", "AnalysisContext", "template_resolver"]
