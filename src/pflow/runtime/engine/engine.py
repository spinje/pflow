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

from .api_warning_detector import detect_api_warning
from .batch_executor import execute_batch
from .instrumentation import (
    cache_result,
    call_completion_callback,
    call_start_callback,
    check_cache_validity,
    check_memo_cache,
    compute_config_hash,
    compute_node_config,
    enforce_loop_guard,
    enrich_llm_cost,
    handle_api_warning,
    handle_cached_execution,
    initialize_execution_state,
    record_trace,
    setup_llm_interception,
    write_memo_cache,
)
from .namespaced_store import NamespacedSharedStore
from .template_resolution import resolve_templates
from .types import CompiledWorkflow, NodeConfig


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
        # 1. Reset visit counts
        if "__execution__" in shared and "node_visit_counts" in shared["__execution__"]:
            shared["__execution__"]["node_visit_counts"] = {}

        # 2. Walk graph
        curr = workflow.start_node
        last_action = None
        while curr:
            node_id = getattr(curr, "node_id", None)
            if node_id is None or node_id not in workflow.node_configs:
                from pflow.core.exceptions import CompilationError

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
            if not nxt and curr.successors:
                shared.setdefault("__warnings__", {})[node_id] = (
                    f"Node '{node_id}' returned action '{last_action}' "
                    f"but no successor edge matches. Available: {list(curr.successors)}. "
                    f"Execution stopped after this node."
                )
            curr = nxt

        # 3. Populate declared outputs
        is_error = last_action and isinstance(last_action, str) and str(last_action).startswith("error")
        if workflow.outputs and not is_error and not self.only_node:
            from pflow.runtime.output_resolver import populate_declared_outputs

            populate_declared_outputs(shared, {"outputs": workflow.outputs})

        return str(last_action) if last_action else "default"

    def _execute_node(self, node: Any, config: NodeConfig, shared: dict[str, Any]) -> str:  # noqa: C901
        """Execute a single node with all runtime concerns."""
        start_time = time.perf_counter()
        shared_keys_before = set(shared.keys()) if (self.trace or self.metrics) else set()

        # 1. LLM interception
        setup_llm_interception(config.node_id, config.node_type_name, node.params, self.trace)

        # 2. Execution state
        initialize_execution_state(shared)

        # 3. Loop guard
        visit_counts = enforce_loop_guard(config.node_id, shared)

        # 4. Resolve templates EARLY — needed for both cache key and execution
        #    SKIP for batch nodes: templates are resolved per-item in _execute_single_node
        last_resolutions: dict = {}
        template_errors: list = []
        resolved_params: Optional[dict] = None
        if config.template_config and not config.batch_config:
            resolved_params, last_resolutions, template_errors = resolve_templates(
                config.template_config, shared, config.node_id
            )

        # 5. Compute config hash (for both cache checks)
        config_hash = compute_config_hash(
            compute_node_config(
                config.node_type_name,
                config.template_config.static_params if config.template_config else node.params,
                config.template_config.template_params if config.template_config else {},
                config.batch_config,
            )
        )

        # 6. Memoization cache check
        hit, result, cache_key = check_memo_cache(
            config.node_id,
            config.node_type_name,
            config_hash,
            config.batch_config,
            shared,
            visit_counts,
            resolved_params=resolved_params,
        )
        if hit:
            return str(result)

        # 7. In-process cache check
        cached, cached_action = check_cache_validity(config.node_id, config_hash, shared)
        if cached:
            return str(
                handle_cached_execution(
                    config.node_id,
                    shared,
                    cached_action,
                    shared_keys_before,
                    config.node_type_name,
                    node.params,
                    self.trace,
                )
            )

        # 8. Progress callback (node_start)
        call_start_callback(config.node_id, shared)

        batch_trace_items: Optional[list] = None
        child_trace_events: Optional[list] = None

        try:
            # 9. Execute: batch or single
            if config.batch_config:
                action, batch_trace_items = execute_batch(node, config, shared, self._execute_single_node)
            else:
                # Set resolved params on node and execute
                if resolved_params is not None:
                    node.params = resolved_params
                    # Write permissive-mode errors to shared store
                    for err in template_errors:
                        shared.setdefault("__template_errors__", {})[config.node_id] = err

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

            # 11. Cache result
            cache_result(config.node_id, config_hash, action, shared)

            # 12. Memo cache write
            write_memo_cache(config.node_id, shared, cache_key, action)

            # 13. Duration
            duration_ms = (time.perf_counter() - start_time) * 1000

            # 14. Metrics
            if self.metrics:
                self.metrics.record_node_execution(config.node_id, duration_ms)

            # 15. LLM cost
            enrich_llm_cost(config.node_id, shared)

            # 16. Trace
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

            return action

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            if self.metrics:
                self.metrics.record_node_execution(config.node_id, duration_ms)

            enrich_llm_cost(config.node_id, shared)

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
                error=e,
            )

            if "__execution__" in shared:
                shared["__execution__"]["failed_node"] = config.node_id

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
            for err in template_errors:
                shared.setdefault("__template_errors__", {})[config.node_id] = err

        store = NamespacedSharedStore(shared, config.node_id) if config.namespaced else shared
        action = node._run(store)

        return action, last_resolutions, template_errors
