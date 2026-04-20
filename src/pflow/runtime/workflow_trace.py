"""Detailed trace collection for workflow debugging."""

import json
import logging
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, ClassVar, Optional

from pflow.core.diagnostic import Diagnostic

logger = logging.getLogger(__name__)

# Trace format version — breaking change from 1.2.0 (removed shared_before/shared_after)
TRACE_FORMAT_VERSION = "2.0.0"


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

    # Class-level attributes for thread-safe LLM interception
    _llm_lock: ClassVar[threading.Lock] = threading.Lock()
    _llm_interception_count: ClassVar[int] = 0
    _original_get_model: ClassVar[Optional[Callable[..., Any]]] = None
    _active_collectors: ClassVar[dict[int, "WorkflowTraceCollector"]] = {}  # thread_id -> collector
    _thread_local: ClassVar[threading.local] = threading.local()  # per-thread current_node

    def __init__(self, workflow_name: str = "workflow"):
        """Initialize the trace collector.

        Args:
            workflow_name: Name of the workflow being traced
        """
        self.workflow_name = workflow_name
        self.execution_id = str(uuid.uuid4())
        self.start_time = datetime.now()
        self.events: list[dict[str, Any]] = []
        self.llm_prompts: dict[str, str] = {}  # Store prompts by node_id
        self._llm_interceptor_installed = False
        self.json_output: dict[str, Any] | None = None  # Store final JSON output if generated
        self.execution_warnings: list[dict[str, Any]] | None = None  # Runtime warnings
        self.enable_llm_interception = True  # Set False for child collectors

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

        # Look for prompt via interception first, then node_output.
        # Note: child collectors (enable_llm_interception=False) won't have intercepted prompts.
        # For those, the prompt is in template_resolutions["prompt"]["resolved"] (not llm_prompt).
        # The LLM node does NOT write "prompt" to shared, so node_output fallback rarely fires.
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

        NOTE: Keep tree traversal in sync with _collect_llm_summary() — same structure.

        Invariant: batch items have EITHER llm_call (leaf items — direct LLM execution)
        OR events (sub-workflow items — containing their own llm_call entries), never both.
        LLM nodes produce llm_call; WorkflowExecutor nodes produce events. If both were
        present, this method would double-count. Verified by construction in _capture_item_trace.

        Args:
            events: List of trace events (may contain nested batch_items/sub_workflow_events)

        Returns:
            Flat list of llm_call dicts
        """
        calls: list[dict[str, Any]] = []

        for event in events:
            if event.get("cached"):
                continue  # Cached nodes incurred no cost this run

            if "llm_call" in event:
                call = dict(event["llm_call"])
                call["node_id"] = event.get("node_id", "unknown")
                call["duration_ms"] = event.get("duration_ms", 0)
                calls.append(call)

            # Recurse into batch items
            for item in event.get("batch_items", []):
                if "llm_call" in item:
                    call = dict(item["llm_call"])
                    call["node_id"] = event.get("node_id", "unknown")
                    call["batch_item_index"] = item.get("index", 0)
                    calls.append(call)
                # Recurse into nested events within batch items (sub-workflow)
                calls.extend(self._collect_llm_calls_from_events(item.get("events", [])))

            # Recurse into sub-workflow events
            sub_events = event.get("sub_workflow_events", [])
            if sub_events:
                calls.extend(self._collect_llm_calls_from_events(sub_events))

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
                if key in ("_trace_collector", "_debug_context", "_batch_trace"):
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

    def _determine_trace_status(self) -> str:
        """Determine status from per-node final state and warnings.

        Uses last-event-per-node_id (via ``final_events_by_node``) so loop
        recovery that ends in success is reported as success — see GH #240.

        Returns:
            Status string: "success", "degraded", or "failed"
        """
        failed = any(not e.get("success", True) for e in final_events_by_node(self.events).values())
        if failed:
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

        NOTE: Keep tree traversal in sync with _collect_llm_calls_from_events() — same structure.
        See that method's docstring for the batch item llm_call/events mutual exclusivity invariant.

        Args:
            events: List of trace events (may contain nested batch_items/sub_workflow_events)

        Returns:
            Summary dict with total_calls, total_tokens, total_input_tokens,
            total_output_tokens, total_cost_usd, models_used
        """
        total_calls = 0
        total_tokens = 0
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0.0
        models: set[str] = set()

        for event in events:
            if event.get("cached"):
                continue  # Cached nodes incurred no cost this run

            if "llm_call" in event:
                total_calls += 1
                total_tokens += event["llm_call"].get("total_tokens", 0)
                total_input_tokens += event["llm_call"].get("input_tokens", 0)
                total_output_tokens += event["llm_call"].get("output_tokens", 0)
                total_cost += event["llm_call"].get("cost_usd", 0) or 0
                model = event["llm_call"].get("model")
                if model:
                    models.add(model)

            # Recurse into batch items
            # Invariant: items have llm_call XOR events, never both (see _collect_llm_calls_from_events)
            for item in event.get("batch_items", []):
                # Leaf item with direct LLM call
                if "llm_call" in item:
                    total_calls += 1
                    total_tokens += item["llm_call"].get("total_tokens", 0)
                    total_input_tokens += item["llm_call"].get("input_tokens", 0)
                    total_output_tokens += item["llm_call"].get("output_tokens", 0)
                    total_cost += item["llm_call"].get("cost_usd", 0) or 0
                    model = item["llm_call"].get("model")
                    if model:
                        models.add(model)
                # Sub-workflow item with nested events
                sub = self._collect_llm_summary(item.get("events", []))
                total_calls += sub.get("total_calls", 0)
                total_tokens += sub.get("total_tokens", 0)
                total_input_tokens += sub.get("total_input_tokens", 0)
                total_output_tokens += sub.get("total_output_tokens", 0)
                total_cost += sub.get("total_cost_usd", 0)
                models.update(sub.get("models_used", []))

            # Recurse into sub-workflow events
            sub_events = event.get("sub_workflow_events", [])
            if sub_events:
                sub = self._collect_llm_summary(sub_events)
                total_calls += sub.get("total_calls", 0)
                total_tokens += sub.get("total_tokens", 0)
                total_input_tokens += sub.get("total_input_tokens", 0)
                total_output_tokens += sub.get("total_output_tokens", 0)
                total_cost += sub.get("total_cost_usd", 0)
                models.update(sub.get("models_used", []))

        return {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_cost_usd": total_cost,
            "models_used": sorted(models),
        }

    def save_to_file(self) -> Path:
        """Save trace to JSON file in ~/.pflow/debug/.

        Returns:
            Path to the saved trace file
        """
        # Create directory if it doesn't exist
        trace_dir = Path.home() / ".pflow" / "debug"
        trace_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp and workflow name
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

        # Sanitize workflow name for filename (keep only alphanumeric and hyphens, limit length)
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "-", self.workflow_name)[:30]
        # Remove multiple consecutive hyphens and strip leading/trailing hyphens
        safe_name = re.sub(r"-+", "-", safe_name).strip("-")

        # Create filename with workflow name if available, otherwise just "workflow"
        if safe_name and safe_name != "workflow":
            filename = f"workflow-trace-{safe_name}-{timestamp}.json"
        else:
            filename = f"workflow-trace-{timestamp}.json"
        filepath = trace_dir / filename

        # Calculate total duration
        duration_ms = (datetime.now() - self.start_time).total_seconds() * 1000

        # Determine final status (tri-state: success/degraded/failed)
        final_status = self._determine_trace_status()

        # Per-node final state — drives nodes_failed and failed_node_ids.
        # Loop recovery: last event per node_id wins (visit 2 success overwrites
        # visit 1 failure) so nodes_failed reflects UNIQUE failed nodes, not
        # total failed invocations. nodes_executed still counts per-visit.
        # See GH #240.
        final_events = final_events_by_node(self.events)
        failed_node_ids = sorted(nid for nid, e in final_events.items() if not e.get("success", True))

        # Prepare trace data with format version
        trace_data: dict[str, Any] = {
            "format_version": TRACE_FORMAT_VERSION,
            "execution_id": self.execution_id,
            "workflow_name": self.workflow_name,
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

    def setup_llm_interception(self, node_id: str) -> None:
        """Thread-safe setup of LLM interception to capture prompts.

        Args:
            node_id: The node that will make LLM calls
        """
        if not self.enable_llm_interception:
            return

        import llm

        # Store current node for prompt capture (thread-local to avoid race in parallel batch)
        WorkflowTraceCollector._thread_local.current_node = node_id

        with WorkflowTraceCollector._llm_lock:
            # Register this collector for the current thread
            thread_id = threading.current_thread().ident
            if thread_id:
                WorkflowTraceCollector._active_collectors[thread_id] = self

            # Only install interceptor if this is the first one
            if WorkflowTraceCollector._llm_interception_count == 0:
                # Save the original function
                WorkflowTraceCollector._original_get_model = llm.get_model

                def intercept_get_model(*args: Any, **kwargs: Any) -> Any:
                    # Get the original function
                    if WorkflowTraceCollector._original_get_model is None:
                        raise RuntimeError("Original get_model not set")
                    model = WorkflowTraceCollector._original_get_model(*args, **kwargs)
                    original_prompt = model.prompt

                    def intercept_prompt(prompt_text: str, **prompt_kwargs: Any) -> Any:
                        # Find the collector for this thread
                        thread_id = threading.current_thread().ident
                        if thread_id and thread_id in WorkflowTraceCollector._active_collectors:
                            collector = WorkflowTraceCollector._active_collectors[thread_id]
                            current_node = getattr(WorkflowTraceCollector._thread_local, "current_node", None)
                            if current_node:
                                collector.llm_prompts[current_node] = prompt_text
                                logger.debug(f"Captured prompt for node {current_node} in thread {thread_id}")

                        # Call original prompt method
                        return original_prompt(prompt_text, **prompt_kwargs)

                    model.prompt = intercept_prompt
                    return model

                llm.get_model = intercept_get_model
                logger.debug("LLM interception installed globally")

            # Increment the reference count
            WorkflowTraceCollector._llm_interception_count += 1
            self._llm_interceptor_installed = True
            logger.debug(f"LLM interception reference count: {WorkflowTraceCollector._llm_interception_count}")

    def cleanup_llm_interception(self) -> None:
        """Thread-safe cleanup of LLM interception."""
        if not self._llm_interceptor_installed:
            return

        with WorkflowTraceCollector._llm_lock:
            # Unregister this collector from the current thread
            thread_id = threading.current_thread().ident
            if thread_id and thread_id in WorkflowTraceCollector._active_collectors:
                del WorkflowTraceCollector._active_collectors[thread_id]
                logger.debug(f"Unregistered collector for thread {thread_id}")

            # Decrement the reference count
            WorkflowTraceCollector._llm_interception_count -= 1
            logger.debug(f"LLM interception reference count: {WorkflowTraceCollector._llm_interception_count}")

            # If this was the last one, restore the original function
            if WorkflowTraceCollector._llm_interception_count == 0:
                import llm

                if WorkflowTraceCollector._original_get_model:
                    llm.get_model = WorkflowTraceCollector._original_get_model
                    WorkflowTraceCollector._original_get_model = None
                    logger.debug("LLM interception removed globally")

            self._llm_interceptor_installed = False
