"""Workflow execution engine.

Replaces Flow._orch() + all 4 wrappers. One class that walks the node graph
and handles all runtime concerns (template resolution, namespacing, caching,
tracing, batch iteration, progress callbacks) directly during traversal.

Key design decisions:
- _execute_single_node returns a tuple (action, last_resolutions, template_errors)
  — NO instance state. This prevents data races in parallel batch.
- Shared store is the single source of runtime data — no initial_params override.
- Template resolution happens EARLY in _execute_node — before cache check.
  The resolved params are used for both cache key computation AND param setting.
"""

import time
from typing import Any, Optional

from pflow.core.exceptions import CompilationError
from pflow.runtime.node_state import (
    FAILURE_CATEGORY_EXCEPTION,
    FAILURE_CATEGORY_HTTP,
    FAILURE_CATEGORY_MCP,
    FAILURE_CATEGORY_NODE_ERROR,
    FAILURE_CATEGORY_ROUTING,
    FAILURE_CATEGORY_SHELL,
    FAILURE_CATEGORY_TEMPLATE,
    get_node_failure,
    mark_node_failed,
)

from .api_warning_detector import detect_api_warning
from .batch_executor import execute_batch
from .instrumentation import (
    apply_memo_hit,
    cache_result,
    call_completion_callback,
    call_start_callback,
    enforce_loop_guard,
    enrich_llm_cost,
    handle_api_warning,
    handle_cached_execution,
    initialize_execution_state,
    invalidate_cache,
    record_trace,
    setup_llm_interception,
    write_memo_cache,
)
from .namespaced_store import NamespacedSharedStore
from .plan_node import plan_node
from .template_resolution import resolve_templates
from .types import CompiledWorkflow, NodeConfig

# Map node class names to failure categories for step 17.5 (error-action
# path). The node type is known at compile time — no data-shape heuristic
# needed. Unlisted types fall back to FAILURE_CATEGORY_NODE_ERROR.
_NODE_TYPE_FAILURE_CATEGORY: dict[str, str] = {
    "ShellNode": FAILURE_CATEGORY_SHELL,
    "HttpNode": FAILURE_CATEGORY_HTTP,
    "MCPNode": FAILURE_CATEGORY_MCP,
}


class WorkflowEngine:
    """Executes a CompiledWorkflow by walking the node graph and handling all runtime concerns."""

    def __init__(
        self,
        metrics_collector: Optional[Any] = None,
        trace_collector: Optional[Any] = None,
        only_node: Optional[str] = None,
    ):
        self.metrics = metrics_collector
        self.trace = trace_collector
        self.only_node = only_node

    def run(self, workflow: CompiledWorkflow, shared: dict[str, Any]) -> str:
        """Execute a compiled workflow. Returns action string."""
        # 0. Validate --only target exists
        if self.only_node and self.only_node not in workflow.node_configs:
            available = sorted(workflow.node_configs.keys())
            raise CompilationError(
                f"Node '{self.only_node}' not found",
                phase="only_node_resolution",
                details={"available_nodes": available},
                suggestion=f"Available nodes: {', '.join(available)}",
            )

        # 1. Reset visit counts
        if "__execution__" in shared and "node_visit_counts" in shared["__execution__"]:
            shared["__execution__"]["node_visit_counts"] = {}

        # 2. Walk graph
        curr = workflow.start_node
        last_action = None
        while curr:
            node_id = getattr(curr, "node_id", None)
            if node_id is None or node_id not in workflow.node_configs:
                raise CompilationError(
                    "Node in graph has no node_id or missing from node_configs",
                    phase="execution",
                    suggestion="This indicates a compiler bug",
                )

            config = workflow.node_configs[node_id]
            last_action = self._execute_node(curr, config, shared)

            # --only: stop after target node
            if self.only_node and node_id == self.only_node:
                if "__execution__" in shared:
                    shared["__execution__"]["only_node"] = self.only_node
                break

            # Follow successor edge
            nxt = curr.successors.get(last_action or "default")
            if not nxt:
                last_action = self._handle_no_successor(last_action, node_id, curr, shared)
                break
            curr = nxt

        # 3. Populate declared outputs
        is_error = last_action and isinstance(last_action, str) and str(last_action).startswith("error")
        if workflow.outputs and not is_error and not self.only_node:
            from pflow.runtime.output_resolver import populate_declared_outputs

            populate_declared_outputs(shared, {"outputs": workflow.outputs})

        return str(last_action) if last_action else "default"

    def _handle_no_successor(
        self, last_action: Optional[str], node_id: str, curr: Any, shared: dict[str, Any]
    ) -> Optional[str]:
        """Handle case where no successor matches the current action.

        Distinguishes intentional termination from routing errors:
        - "end" action or no forward (non-error) edges → clean termination
        - Unmatched action with forward edges present → routing failure

        Returns the (possibly updated) last_action.
        """
        if last_action == "end" or all(k == "error" for k in curr.successors):
            return last_action  # Intentional termination or no forward path

        # Unmatched action — either a node failure with no error handler,
        # or a routing error (code returned action not in declared targets)
        is_node_failure = isinstance(last_action, str) and last_action.startswith("error")
        suggestion = (
            "Add '- on-error: <handler-node>' to handle errors."
            if is_node_failure
            else 'Use next: str = "end" to terminate intentionally.'
        )
        warning_msg = (
            f"Node '{node_id}' returned action '{last_action}' "
            f"but no successor edge matches. Available: {list(curr.successors)}. "
            f"{suggestion}"
        )

        # If step 17.5 already archived this node (action started with "error"),
        # the failure record holds the real failure data and category (e.g.
        # shell_failure with exit_code/stderr/command). Don't overwrite it —
        # just surface the routing hint via __warnings__. Without this guard,
        # mark_node_failed's shared.pop() returns None, replacing rich data
        # with an empty-data routing_error record.
        if get_node_failure(shared, node_id) is not None:
            shared.setdefault("__warnings__", {})[node_id] = warning_msg
            return "error"

        # Non-error action with no matching successor: roll back success
        # bookkeeping added by cache_result and archive as a routing failure.
        invalidate_cache(node_id, shared)
        mark_node_failed(
            shared,
            node_id,
            category=FAILURE_CATEGORY_ROUTING,
            error=warning_msg,
            warning=warning_msg,
        )
        return "error"

    def _execute_node(self, node: Any, config: NodeConfig, shared: dict[str, Any]) -> str:  # noqa: C901
        """Execute a single node with all runtime concerns."""
        start_time = time.perf_counter()
        shared_keys_before = set(shared.keys()) if (self.trace or self.metrics) else set()

        # 1. LLM interception
        setup_llm_interception(config.node_id, config.node_type_name, node.params, self.trace)

        # 2. Execution state
        initialize_execution_state(shared)

        # 3. Loop guard
        enforce_loop_guard(config.node_id, shared)

        # Steps 5-11 are inside try so template errors get recorded in trace
        last_resolutions: dict = {}
        template_errors: list = []
        resolved_params: Optional[dict] = None
        batch_trace_items: Optional[list] = None
        child_trace_events: Optional[list] = None

        try:
            plan = plan_node(node, config, shared)

            if plan.template_exception is not None:
                raise plan.template_exception

            if plan.status in ("cached_memo", "cached_in_process"):
                if plan.status == "cached_memo" and plan.cached_output is not None and plan.cached_action is not None:
                    apply_memo_hit(
                        config.node_id,
                        shared,
                        plan.cached_action,
                        plan.cached_output,
                        plan.config_hash,
                    )
                return str(
                    handle_cached_execution(
                        config.node_id,
                        shared,
                        plan.cached_action,
                        shared_keys_before,
                        config.node_type_name,
                        node.params,
                        self.trace,
                    )
                )

            last_resolutions = plan.last_resolutions
            template_errors = plan.template_errors
            resolved_params = plan.resolved_params
            cache_key = plan.cache_key
            config_hash = plan.config_hash

            if config.node_id in shared["__execution__"]["completed_nodes"]:
                cached_hash = shared["__execution__"]["node_hashes"].get(config.node_id)
                if cached_hash != plan.config_hash:
                    invalidate_cache(config.node_id, shared)

            # 8. Progress callback (node_start)
            call_start_callback(config.node_id, shared)

            # 9. Execute: batch or single
            if config.batch_config:
                action, batch_trace_items = execute_batch(node, config, shared, self._execute_single_node)
            else:
                # Set resolved params on node and execute
                if resolved_params is not None:
                    node.params = resolved_params
                    # Write permissive-mode errors to shared store (last error per node,
                    # matching old TemplateAwareNodeWrapper behavior — multiple errors
                    # per node would require changing the consumer in runner.py)
                    if template_errors:
                        shared.setdefault("__template_errors__", {})[config.node_id] = template_errors[-1]

                store = NamespacedSharedStore(shared, config.node_id) if config.namespaced else shared
                action = node._run(store)

                # Read child trace events from WorkflowExecutor
                if config.node_type_name == "WorkflowExecutor":
                    child_trace_events = getattr(node, "_child_trace_events", None)

            # 10. API warning detection
            warning = detect_api_warning(config.node_id, shared)
            if warning:
                return handle_api_warning(
                    config.node_id,
                    shared,
                    warning,
                    self.metrics,
                    self.trace,
                    start_time,
                    shared_keys_before,
                    config.node_type_name,
                    node.params,
                )

            # 11. Cache result (in-process only — not gated by cache_enabled)
            cache_result(config.node_id, config_hash, action, shared)

            # 12. Duration (computed here so the memo cache write can record it
            # for --dry-run historical estimates — see plan_formatter.py).
            duration_ms = (time.perf_counter() - start_time) * 1000

            # 13. Memo cache write (skip for nodes with cache: false)
            if config.cache_enabled:
                write_memo_cache(config.node_id, shared, cache_key, action, duration_ms=duration_ms)

            # 14. Metrics
            if self.metrics:
                self.metrics.record_node_execution(config.node_id, duration_ms)

            # 15. LLM cost
            enrich_llm_cost(config.node_id, shared)

            # Pre-compute trace error for action="error" happy-path failures
            # (no exception raised, but the trace event should still carry the
            # actual error text so --report and other trace consumers don't
            # fall back to "Unknown error").
            is_error_action = str(action).startswith("error")
            trace_error: Optional[str] = None
            if is_error_action:
                node_data_snapshot = shared.get(config.node_id, {})
                if isinstance(node_data_snapshot, dict):
                    trace_error = node_data_snapshot.get("error")

            # 16. Trace — node returning "error" action is a failure even without exception
            record_trace(
                config.node_id,
                config.node_type_name,
                shared,
                start_time,
                shared_keys_before,
                last_resolutions,
                batch_trace_items,
                child_trace_events,
                node.params,
                self.trace,
                success=not is_error_action,
                error=trace_error,
            )

            # 17. Completion callback
            ignore_errors = node.params.get("ignore_errors", False) if isinstance(node.params, dict) else False
            call_completion_callback(
                config.node_id,
                shared,
                action,
                duration_ms,
                ignore_errors=ignore_errors,
            )

            # Step 17.5: archive failed node data to __failures__.
            # Runs AFTER trace, metrics, and completion callback so they
            # all see the data in shared[node_id]. After this, the node
            # is in __failures__ and consumers must use get_node_output.
            #
            # Category is resolved from the compile-time node type name
            # via _NODE_TYPE_FAILURE_CATEGORY — no data-shape heuristic.
            #
            # When an error successor exists (on-error handler), pass
            # warning= so __warnings__ is populated and _determine_status
            # returns DEGRADED instead of SUCCESS. Without this, recovered
            # workflows silently report SUCCESS (GH #246).
            if str(action).startswith("error"):
                node_data = shared.get(config.node_id, {})
                node_error = node_data.get("error") if isinstance(node_data, dict) else None
                error_handler = node.successors.get("error")
                handler_id = getattr(error_handler, "node_id", None) if error_handler else None
                mark_node_failed(
                    shared,
                    config.node_id,
                    category=_NODE_TYPE_FAILURE_CATEGORY.get(config.node_type_name, FAILURE_CATEGORY_NODE_ERROR),
                    error=node_error,
                    warning=f"Node '{config.node_id}' failed — on-error → '{handler_id}'" if handler_id else None,
                )

            return action

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            if self.metrics:
                self.metrics.record_node_execution(config.node_id, duration_ms)

            enrich_llm_cost(config.node_id, shared)

            # Extract partial resolutions from template errors (attached by resolve_templates)
            error_resolutions = getattr(e, "_pflow_partial_resolutions", None) or last_resolutions

            record_trace(
                config.node_id,
                config.node_type_name,
                shared,
                start_time,
                shared_keys_before,
                error_resolutions,
                batch_trace_items,
                child_trace_events,
                node.params,
                self.trace,
                error=e,
            )

            call_completion_callback(config.node_id, shared, "error", duration_ms, error=e)

            # LAST STEP: archive the failed node's data to __failures__.
            # All trace/metrics/callback have already read shared[node_id].

            # Categorize template-resolution ValueErrors specifically so the
            # formatter can render them as template errors, not generic exceptions.
            is_template_error = isinstance(e, ValueError) and getattr(e, "_pflow_partial_resolutions", None) is not None
            category = FAILURE_CATEGORY_TEMPLATE if is_template_error else FAILURE_CATEGORY_EXCEPTION

            node_data = shared.get(config.node_id, {})
            node_error = node_data.get("error") if isinstance(node_data, dict) else None
            mark_node_failed(
                shared,
                config.node_id,
                category=category,
                error=node_error or str(e),
            )

            if not hasattr(e, "_pflow_node_id"):
                e._pflow_node_id = config.node_id  # type: ignore[attr-defined]

            raise

    def _execute_single_node(self, node: Any, config: NodeConfig, shared: dict[str, Any]) -> tuple[str, dict, list]:
        """Execute a non-batch node: resolve templates, namespace, run.

        Returns (action, last_resolutions, template_errors).
        NO instance state stored — safe for parallel batch.
        """
        last_resolutions: dict = {}
        template_errors: list = []

        if config.template_config:
            merged_params, last_resolutions, template_errors = resolve_templates(
                config.template_config, shared, config.node_id
            )
            node.params = merged_params
            if template_errors:
                shared.setdefault("__template_errors__", {})[config.node_id] = template_errors[-1]

        store = NamespacedSharedStore(shared, config.node_id) if config.namespaced else shared
        action = node._run(store)

        return action, last_resolutions, template_errors
