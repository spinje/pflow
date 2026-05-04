"""Detailed trace collection for workflow debugging."""

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from pflow.core.diagnostic import Diagnostic

logger = logging.getLogger(__name__)

# Trace format version — breaking change from 1.2.0 (removed shared_before/shared_after)
TRACE_FORMAT_VERSION = "2.1.0"


def format_trace_filename(workflow_path: str | None, workflow_name: str, timestamp: str) -> str:
    """Compose a trace filename whose hash prefix encodes ``workflow_path``.

    Filename schema: ``workflow-trace-{wf_hash}-{safe_name}-{timestamp}.json``
    where ``wf_hash`` is the first 8 hex chars of ``md5(workflow_path or "")``.

    The hash makes ``analyze-cache`` autoload O(matching-traces) instead of
    O(directory-size): the reader globs by the same hash prefix to narrow
    candidates before reading any file's contents. Filename collisions across
    distinct workflows are guarded by a contents-level ``workflow_path``
    re-check at read time.
    """
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "-", workflow_name)[:30]
    safe_name = re.sub(r"-+", "-", safe_name).strip("-")

    wf_hash = hashlib.md5((workflow_path or "").encode("utf-8"), usedforsecurity=False).hexdigest()[:8]

    if safe_name and safe_name != "workflow":
        return f"workflow-trace-{wf_hash}-{safe_name}-{timestamp}.json"
    return f"workflow-trace-{wf_hash}-{timestamp}.json"


@dataclass
class _LLMSummaryAccumulator:
    """Accumulator for ``WorkflowTraceCollector._collect_llm_summary``.

    Lives at module level to keep the recursive collector small (ruff C901).
    Mirrors ``MetricsCollector.calculate_costs`` semantics: when any leaf
    has ``cost_usd: None``, ``total_cost_usd`` becomes ``None`` and we surface
    ``partial_cost_usd`` + ``unavailable_models`` + ``pricing_available: False``.
    """

    total_calls: int = 0
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    priced_cost: float = 0.0
    models: set[str] = field(default_factory=set)
    unavailable_models: set[str] = field(default_factory=set)

    def add_leaf(self, call: dict[str, Any]) -> None:
        self.total_calls += 1
        self.total_tokens += call.get("total_tokens", 0)
        self.total_input_tokens += call.get("input_tokens", 0)
        self.total_output_tokens += call.get("output_tokens", 0)
        cost = call.get("cost_usd")
        if cost is None:
            self.unavailable_models.add(call.get("model") or "unknown")
        else:
            self.priced_cost += cost
        model = call.get("model")
        if model:
            self.models.add(model)

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "total_calls": self.total_calls,
            "total_tokens": self.total_tokens,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "models_used": sorted(self.models),
        }
        if self.unavailable_models:
            result["total_cost_usd"] = None
            result["partial_cost_usd"] = round(self.priced_cost, 6) if self.priced_cost > 0 else None
            result["unavailable_models"] = sorted(self.unavailable_models)
            result["pricing_available"] = False
        else:
            result["total_cost_usd"] = round(self.priced_cost, 6)
            result["pricing_available"] = True
        return result


def final_events_by_node(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Last event per node_id — represents each node's terminal state.

    Single source of truth for the "last event per node_id = final state"
    aggregation rule. Used by WorkflowTraceCollector at write time (status
    determination, failed_node_ids derivation) and by ``trace_report._collect_errors``
    at read time (Errors-section rendering, fallback for legacy traces without
    ``failed_node_ids``). If this rule ever evolves, it evolves here.

    Loop recovery records multiple events for the same node_id; only the most
    recent reflects the node's final outcome.

    Keyed by node_id — batch items (which carry ``index``, not ``node_id``)
    and nested sub-workflow events are intentionally ignored.

    **Assumes ``events`` is in chronological append order** (as produced by
    ``record_node_execution``). The function takes the LAST occurrence of
    each node_id as the final state — callers must not pre-sort or merge
    out-of-order events, or loop-recovery aggregation will silently report
    the wrong final state.
    """
    final: dict[str, dict[str, Any]] = {}
    for event in events:
        nid = event.get("node_id")
        if nid:
            final[nid] = event
    return final


class WorkflowTraceCollector:
    """Collects detailed execution traces for workflow debugging.

    Captures node execution data, template resolutions, per-node outputs,
    and LLM interactions. Saves traces to ~/.pflow/debug/ for analysis.

    Format 2.0.0 changes:
    - Removed shared_before/shared_after (O(n²) full-store snapshots)
    - Added node_params, template_resolutions, node_output per event
    - Tree-structured: batch_items and sub_workflow_events are nested
    - No value truncation (only internal key filtering and binary replacement)
    """

    def __init__(
        self,
        workflow_name: str = "workflow",
        *,
        workflow_path: str | None = None,
    ):
        """Initialize the trace collector.

        Args:
            workflow_name: Name of the workflow being traced (display label;
                used for the trace filename and the saved trace's
                ``workflow_name`` field).
            workflow_path: Canonical path identifier for the workflow (Task
                159 trace 2.1.0). For file-based runs, the resolved file
                path. For inline runs, the synthetic
                ``"ir-hash:<32-char-md5>"`` from
                ``execution/runner._synthesize_inline_workflow_id`` —
                symmetric with how ``MemoizationCache.workflow_path``
                already scopes inline-run rows. Defaults to ``None`` so
                existing test fixtures continue to construct without
                changes; production paths set it from
                ``shared["_pflow_workflow_file"]`` / inline-id synthesis.
                The saved trace JSON always emits ``workflow_path``
                unconditionally (``null`` when not set).
        """
        self.workflow_name = workflow_name
        self.workflow_path = workflow_path
        self.execution_id = str(uuid.uuid4())
        self.start_time = datetime.now()
        self.events: list[dict[str, Any]] = []
        self.llm_prompts: dict[str, str] = {}  # populated by trace_hook fired from the adapter; keyed by node_id
        self.json_output: dict[str, Any] | None = None  # Store final JSON output if generated
        self.execution_warnings: list[dict[str, Any]] | None = None  # Runtime warnings

    def record_node_execution(
        self,
        node_id: str,
        node_type: str,
        duration_ms: float,
        success: bool,
        error: Optional[str] = None,
        node_params: Optional[dict[str, Any]] = None,
        template_resolutions: Optional[dict[str, Any]] = None,
        node_output: Optional[dict[str, Any]] = None,
        mutations: Optional[dict[str, list[str]]] = None,
        batch_items: Optional[list[dict[str, Any]]] = None,
        sub_workflow_events: Optional[list[dict[str, Any]]] = None,
        cached: bool = False,
    ) -> None:
        """Record detailed node execution data.

        Args:
            node_id: Unique identifier for the node
            node_type: Type/class name of the node
            duration_ms: Execution duration in milliseconds
            success: Whether the node executed successfully
            error: Error message if execution failed
            node_params: Original node parameters (before template resolution)
            template_resolutions: Template variables resolved during execution
            node_output: This node's output from the shared store (namespaced)
            mutations: Key-level changes to shared store (added/removed/modified)
            batch_items: Per-item trace events for batch nodes
            sub_workflow_events: Child workflow trace events for nested workflows
            cached: Whether this node used cached results (skipped execution)
        """
        event: dict[str, Any] = {
            "node_id": node_id,
            "node_type": node_type,
            "duration_ms": round(duration_ms, 2),
            "success": success,
            "timestamp": datetime.now().isoformat(),
        }

        if cached:
            event["cached"] = True
        if error:
            event["error"] = error
        if node_params:
            event["node_params"] = self._sanitize_for_json(node_params)
        if template_resolutions:
            event["template_resolutions"] = self._sanitize_for_json(template_resolutions)
        if node_output:
            event["node_output"] = self._sanitize_for_json(node_output)
        if mutations:
            event["mutations"] = mutations
        if batch_items:
            event["batch_items"] = self._sanitize_batch_items(batch_items)
        if sub_workflow_events:
            event["sub_workflow_events"] = sub_workflow_events  # Already sanitized by child collector

        # Add LLM-specific data if present
        self._add_llm_data(event, node_id, node_output or {})

        self.events.append(event)

    def _add_llm_data(
        self,
        event: dict[str, Any],
        node_id: str,
        node_output: dict[str, Any],
    ) -> None:
        """Add LLM usage and response data to the event if present.

        Args:
            event: Event dictionary to update
            node_id: Node ID for prompt lookup
            node_output: This node's output from the shared store
        """
        # Look for llm_usage directly in node_output
        llm_usage = node_output.get("llm_usage") if isinstance(node_output, dict) else None
        if isinstance(llm_usage, dict):
            event["llm_call"] = llm_usage

        # Look for prompt via the trace_hook capture first, then node_output.
        # The LLM adapter calls collector.get_trace_hook(node_id) to get a
        # writer that populates self.llm_prompts[node_id] on before_call.
        # Sub-workflow LLM events end up in their own collector's
        # llm_prompts dict (each engine.run installs its own collector into
        # shared["__trace_collector__"]); the parent's WorkflowExecutor event
        # then aggregates child events via sub_workflow_events.
        # The LLM node does NOT write "prompt" to shared, so the
        # node_output fallback only fires for legacy/external callers.
        prompt = self.llm_prompts.get(node_id)
        if not prompt and isinstance(node_output, dict):
            prompt = node_output.get("prompt")
        if isinstance(prompt, str):
            event["llm_prompt"] = prompt  # No truncation

        # Look for response in node_output
        response = node_output.get("response") if isinstance(node_output, dict) else None
        if isinstance(response, str):
            event["llm_response"] = response  # No truncation

    def collect_llm_calls(self) -> list[dict[str, Any]]:
        """Walk event tree recursively and return flat list of llm_call dicts.

        Collects from top-level events, batch_items, and sub_workflow_events.

        Returns:
            Flat list of llm_call dicts (each containing model, tokens, cost, etc.)
        """
        return self._collect_llm_calls_from_events(self.events)

    def _collect_llm_calls_from_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Recursively collect llm_call dicts from tree-structured events.

        Skips cached events at every tier (top-level, batch_items,
        sub_workflow_events) via
        ``TraceTree.iter_llm_leaves(descend_cached_subtrees=False)``. This is
        more aggressive than the pre-1fabde31 hand-rolled walker, which only
        filtered top-level cached events. The new behavior is correct for
        cost-summary purposes: cached items contributed $0 this run regardless
        of nesting tier.
        """
        from pflow.core.trace_tree import TraceTree

        tree = TraceTree(events=tuple(events), format_version=TRACE_FORMAT_VERSION)
        calls: list[dict[str, Any]] = []
        for leaf in tree.iter_llm_leaves(descend_cached_subtrees=False):
            if leaf.llm_call is None:
                continue
            call = dict(leaf.llm_call)
            call["node_id"] = leaf.event_node_id if leaf.tier == "sub_workflow_descendant" else leaf.owner_node_id
            call["duration_ms"] = leaf.event.get("duration_ms", 0)
            if leaf.tier == "batch_item":
                call["batch_item_index"] = leaf.event.get("index", 0)
            calls.append(call)
        return calls

    def _sanitize_for_json(self, data: Any) -> Any:
        """Make data JSON-serializable. No truncation — just hygiene.

        Filters internal keys (__ prefixed except __metrics__)
        and replaces binary data with a placeholder.

        Args:
            data: Data to sanitize

        Returns:
            Sanitized data suitable for JSON serialization
        """
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                # Skip internal keys
                if isinstance(key, str) and key.startswith("__") and key not in ("__metrics__",):
                    continue
                if key in ("__trace_collector__", "_debug_context", "_batch_trace"):
                    continue
                result[key] = self._sanitize_for_json(value)
            return result
        elif isinstance(data, bytes):
            return f"<binary data: {len(data)} bytes>"
        elif isinstance(data, (list, tuple)):
            return [self._sanitize_for_json(item) for item in data]
        else:
            return data

    def _sanitize_batch_items(self, batch_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sanitize batch item trace data. Items are built by _capture_item_trace
        which doesn't sanitize node_output — we do it here at the collector level."""
        sanitized = []
        for item in batch_items:
            clean_item = dict(item)
            if "node_output" in clean_item:
                clean_item["node_output"] = self._sanitize_for_json(clean_item["node_output"])
            if "template_resolutions" in clean_item:
                clean_item["template_resolutions"] = self._sanitize_for_json(clean_item["template_resolutions"])
            # Recurse into nested events (sub-workflow batch items)
            if "events" in clean_item:
                # Child events from sub-workflow collectors are already sanitized,
                # but events from _capture_item_trace may not be
                clean_item["events"] = [
                    self._sanitize_for_json(e) if isinstance(e, dict) else e for e in clean_item["events"]
                ]
            sanitized.append(clean_item)
        return sanitized

    def set_json_output(self, json_output: dict[str, Any]) -> None:
        """Store the JSON output that was sent to stdout.

        Args:
            json_output: The JSON data that was output to the user
        """
        self.json_output = json_output

    def set_warnings(self, warnings: list[Diagnostic] | list[dict[str, Any]]) -> None:
        """Store warning diagnostics from execution.

        Args:
            warnings: List of warning diagnostics or legacy warning dicts
        """
        if not warnings:
            self.execution_warnings = None
            return
        self.execution_warnings = [
            warning.to_display_dict() if isinstance(warning, Diagnostic) else warning for warning in warnings
        ]

    def mark_last_event_failed(self, node_id: str, *, error: str) -> None:
        """Flip the most recent event for node_id to failed.

        Used by the engine when a node's failure is detected AFTER its trace
        event has been recorded — specifically, routing failures on custom
        non-error actions (GH #250). Without this, the trace event says
        success=True while __failures__[node_id] says the node failed.

        No-op if no event for node_id exists. Today the only caller is
        _handle_no_successor, which runs AFTER step 16 trace recording in
        the engine walk — so the no-op path is unreachable under current
        engine semantics. The guard is defensive for future engine paths
        that might call this before trace recording.

        `category` is intentionally NOT accepted: trace events don't carry
        a category field today; the canonical category lives in
        __failures__[node_id]["category"]. A future migration that upgrades
        `success: bool` → `status: enum` would read category from
        __failures__ at migration time.

        The flipped event retains its original `node_output` from the
        successful execution (captured at step 16 before __failures__
        archival). This is intentional: the node DID produce output, and
        then routing failed. Per-node report files show both the output
        and the failed status — this is semantically correct.
        """
        for event in reversed(self.events):
            if event.get("node_id") == node_id:
                event["success"] = False
                event["error"] = error
                return

    def _determine_trace_status(self, final_events: dict[str, dict[str, Any]] | None = None) -> str:
        """Determine status from per-node final state and warnings.

        Uses last-event-per-node_id (via ``final_events_by_node``) so loop
        recovery that ends in success is reported as success — see GH #240.

        Args:
            final_events: optional pre-computed dict. ``save_to_file`` already
                computes this to derive ``failed_node_ids`` and passes it in
                to avoid a second pass over ``self.events``. Callers that
                don't need the dict elsewhere can omit the argument.

        Returns:
            Status string: "success", "degraded", or "failed"
        """
        if final_events is None:
            final_events = final_events_by_node(self.events)
        if any(not e.get("success", True) for e in final_events.values()):
            return "failed"
        if self.execution_warnings and any(
            self._warning_changes_status(warning) for warning in self.execution_warnings
        ):
            return "degraded"
        return "success"

    @staticmethod
    def _warning_changes_status(warning: dict[str, Any]) -> bool:
        """Return whether a warning should mark the trace as degraded.

        Blacklist (not whitelist) is intentional: unknown sources default to
        degrading, so new source types are fail-closed rather than silently
        ignored.  Only parser and validator warnings are excluded — they
        indicate input quality issues, not runtime degradation.
        """
        return warning.get("source") not in {"parser", "validator"}

    def _collect_llm_summary(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Recursively collect LLM call data from tree-structured events.

        Cached events are filtered at every tier via
        ``TraceTree.iter_llm_leaves(descend_cached_subtrees=False)`` — top-level
        cached events AND cached batch_items / sub_workflow_events are excluded
        from the summary. Pre-1fabde31 the hand-rolled walker only filtered
        top-level cached events; the new behavior is correct because cached
        items paid $0 this run regardless of nesting tier.
        """
        from pflow.core.trace_tree import TraceTree

        agg = _LLMSummaryAccumulator()
        tree = TraceTree(events=tuple(events), format_version=TRACE_FORMAT_VERSION)
        for leaf in tree.iter_llm_leaves(descend_cached_subtrees=False):
            if leaf.llm_call is not None:
                agg.add_leaf(dict(leaf.llm_call))
        return agg.as_dict()

    def save_to_file(self) -> Path:
        """Save trace to JSON file in ~/.pflow/debug/.

        Returns:
            Path to the saved trace file
        """
        # Create directory if it doesn't exist
        trace_dir = Path.home() / ".pflow" / "debug"
        trace_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = format_trace_filename(self.workflow_path, self.workflow_name, timestamp)
        filepath = trace_dir / filename

        # Calculate total duration
        duration_ms = (datetime.now() - self.start_time).total_seconds() * 1000

        # Per-node final state — drives BOTH final_status AND failed_node_ids.
        # Loop recovery: last event per node_id wins (visit 2 success overwrites
        # visit 1 failure) so nodes_failed reflects UNIQUE failed nodes, not
        # total failed invocations. nodes_executed still counts per-visit.
        # Computed once and passed to _determine_trace_status so the events
        # list is walked once per save. See GH #240.
        final_events = final_events_by_node(self.events)
        final_status = self._determine_trace_status(final_events)
        failed_node_ids = sorted(nid for nid, e in final_events.items() if not e.get("success", True))

        # Prepare trace data with format version
        trace_data: dict[str, Any] = {
            "format_version": TRACE_FORMAT_VERSION,
            "execution_id": self.execution_id,
            "workflow_name": self.workflow_name,
            # Task 159 trace 2.1.0: emitted unconditionally. None when the
            # caller didn't set it (test fixtures, legacy harnesses); the
            # production paths (``execution/runner.py``,
            # ``runtime/workflow_executor.py``) always provide a value.
            "workflow_path": self.workflow_path,
            "start_time": self.start_time.isoformat(),
            "end_time": datetime.now().isoformat(),
            "duration_ms": round(duration_ms, 2),
            "final_status": final_status,
            "nodes_executed": len(self.events),
            "nodes_failed": len(failed_node_ids),
            "failed_node_ids": failed_node_ids,
            "nodes": self.events,
        }

        # Add LLM summary by recursively scanning tree-structured events
        llm_summary = self._collect_llm_summary(self.events)
        if llm_summary["total_calls"] > 0:
            trace_data["llm_summary"] = llm_summary

        # Add runtime warnings (e.g., API warnings, batch degradation)
        if self.execution_warnings:
            trace_data["warnings"] = self.execution_warnings

        # Add JSON output if it was generated (e.g., when --output-format json was used)
        if self.json_output is not None:
            trace_data["json_output"] = self.json_output

        # Write to file with proper formatting
        with open(filepath, "w") as f:
            json.dump(trace_data, f, indent=2, default=str)

        return filepath

    def get_trace_hook(self, node_id: str) -> Callable[[dict[str, Any]], None]:
        """Return a callable that the LLM adapter invokes around its API call.

        The new pflow-owned LiteLLM adapter (`pflow.core.llm_client.complete`)
        accepts a `trace_hook` parameter. When a workflow trace is active, the
        LLMNode passes `collector.get_trace_hook(node_id)` to the adapter.
        On `before_call` the hook captures the rendered prompt into
        `self.llm_prompts[node_id]` — same destination the legacy
        ``llm.get_model`` monkey-patch wrote to before Task 158 Phase A.6
        replaced it with this hook. Same downstream consumer
        (`_attach_llm_call_to_event` at line 168 of this file).
        """

        def hook(event: dict[str, Any]) -> None:
            if event.get("event") == "before_call":
                prompt = event.get("prompt")
                if isinstance(prompt, str):
                    self.llm_prompts[node_id] = prompt

        return hook
