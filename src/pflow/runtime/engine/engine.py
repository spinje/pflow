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
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Optional

from pflow.core.cache_render import CacheRenderContext
from pflow.core.exceptions import CompilationError
from pflow.core.llm_capabilities import get_min_cache_tokens
from pflow.core.validation_utils import VALIDATION_PLACEHOLDER
from pflow.runtime.node_state import (
    FAILURE_CATEGORY_EXCEPTION,
    FAILURE_CATEGORY_HTTP,
    FAILURE_CATEGORY_LLM,
    FAILURE_CATEGORY_MCP,
    FAILURE_CATEGORY_NODE_ERROR,
    FAILURE_CATEGORY_ROUTING,
    FAILURE_CATEGORY_SHELL,
    FAILURE_CATEGORY_TEMPLATE,
    get_node_failure,
    mark_node_failed,
)
from pflow.runtime.template_resolver import TemplateResolver

from .api_warning_detector import detect_api_warning
from .batch_executor import _collect_batch_trace, execute_batch
from .instrumentation import (
    apply_memo_hit,
    cache_result,
    call_completion_callback,
    call_start_callback,
    enforce_loop_guard,
    handle_api_warning,
    handle_cached_execution,
    initialize_execution_state,
    invalidate_cache,
    record_trace,
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
    "LLMNode": FAILURE_CATEGORY_LLM,
}

# Read-only empty mapping used to restore ``__pflow_cache_render__`` after a
# child engine.run completes when the parent had no value installed. Module
# level so deeply-nested sub-workflow restores don't allocate per call.
_EMPTY_CACHE_RENDER: Mapping[str, CacheRenderContext] = MappingProxyType({})


def build_cache_render_dict(
    workflow: CompiledWorkflow,
    shared: dict[str, Any],
) -> dict[str, CacheRenderContext]:
    """Build the per-node ``CacheRenderContext`` map for one engine.run.

    Includes only LLM nodes that have at least one cache-relevant declaration
    (``prompt_cache_items``, ``prewarm``, or a workflow-level ``## Cache``
    block). Sparse by design — non-cache workflows produce an empty dict and
    consumers (`plan_node`, `LLMNode.prep`) read via the canonical
    ``(shared.get(K) or {}).get(node_id)`` defensive pattern.
    """
    cache_block = workflow.cache_block
    out: dict[str, CacheRenderContext] = {}
    for node_id, config in workflow.node_configs.items():
        if config.node_type_name != "LLMNode":
            continue
        if not (config.prompt_cache_items or config.prewarm or cache_block):
            continue
        prewarm = config.prewarm
        if _should_disable_below_min_prewarm(node_id, config, shared):
            prewarm = False
        out[node_id] = _make_cache_render_context(config, cache_block, prewarm=prewarm)
    return out


def _make_cache_render_context(
    config: NodeConfig,
    cache_block: Any,
    *,
    prewarm: bool | None = None,
) -> CacheRenderContext:
    """Build one node's ``CacheRenderContext`` from its ``NodeConfig``.

    ``unresolved_batch_prompt`` and ``batch_alias`` are populated only for
    batch LLM nodes (D.1 auto-prefix detection reads them); non-batch nodes
    get ``None`` for both.
    """
    unresolved = None
    alias = None
    node_inputs = None
    if config.batch_config and config.template_config:
        unresolved = config.template_config.template_params.get("prompt") or config.template_config.static_params.get(
            "prompt"
        )
        alias = config.batch_config.item_alias
        raw_inputs = _node_inputs_from_config(config)
        if isinstance(raw_inputs, Mapping):
            # Snapshot + freeze for parallel-batch safety. CacheRenderContext
            # is shared by batch workers, so the immutability contract is
            # explicit even though template_params is compile-time data.
            node_inputs = MappingProxyType(dict(raw_inputs))
    return CacheRenderContext(
        cache_block=cache_block,
        subset=config.prompt_cache_items,
        prewarm=config.prewarm if prewarm is None else prewarm,
        unresolved_batch_prompt=unresolved,
        batch_alias=alias,
        node_inputs=node_inputs,
    )


def _should_disable_below_min_prewarm(
    node_id: str,
    config: NodeConfig,
    shared: dict[str, Any],
) -> bool:
    if not config.prewarm or config.batch_config is None or config.template_config is None:
        return False

    model_raw = config.template_config.template_params.get("model") or config.template_config.static_params.get("model")
    if model_raw is None:
        return False
    model = _resolve_template_string(model_raw, shared)
    if model is None or model == VALIDATION_PLACEHOLDER:
        return False

    prompt_raw = config.template_config.template_params.get("prompt") or config.template_config.static_params.get(
        "prompt"
    )
    if not isinstance(prompt_raw, str):
        return False

    from pflow.core.cache_analysis.below_min_tokens_detector import is_below_min_cache, provider_note
    from pflow.core.cache_analysis.context import AnalysisContext
    from pflow.core.cache_analysis.token_estimation import tokenize_prompt_region_lower_bound
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic
    from pflow.core.prompt_refs import first_per_item_position

    alias = config.batch_config.item_alias
    first = first_per_item_position(prompt_raw, alias, _node_inputs_from_config(config))
    if first is None or first <= 0:
        return False

    ctx = AnalysisContext.build(
        workflow_ir={},
        parameters=shared,
        memo_cache=shared.get("__memoization_cache__"),
        workflow_path=shared.get("_pflow_workflow_file"),
    )
    prefix_tokens, _unresolved_refs = tokenize_prompt_region_lower_bound(prompt_raw[:first], model=model, ctx=ctx)
    if not is_below_min_cache(model, prefix_tokens):
        return False

    diagnostic = make_diagnostic(
        "cache.prewarm-disabled-below-min",
        node_id=node_id,
        affected_workflow=shared.get("_pflow_workflow_file") or "<unknown>",
        model=model,
        cacheable_tokens=prefix_tokens,
        min_tokens=get_min_cache_tokens(model),
        provider_note=provider_note(model),
        alias=alias,
    )
    shared.setdefault("__warnings__", {})[node_id] = diagnostic
    shared.setdefault("__prewarm_disabled_below_min__", {})[node_id] = "below_min"
    return True


def _node_inputs_from_config(config: NodeConfig) -> Mapping[str, Any] | None:
    template_config = config.template_config
    if template_config is None:
        return None
    raw_inputs = template_config.template_params.get("inputs") or template_config.static_params.get("inputs")
    return raw_inputs if isinstance(raw_inputs, Mapping) else None


def _resolve_template_string(raw: Any, shared: dict[str, Any]) -> str | None:
    if not isinstance(raw, str):
        return str(raw) if raw is not None else None
    try:
        resolved = TemplateResolver.resolve_template(raw, shared)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if not isinstance(resolved, str) or TemplateResolver.TEMPLATE_PATTERN.search(resolved):
        return None
    return resolved


def parse_only_path(only_node: str | None) -> tuple[str | None, str | None]:
    """Split a dotted ``--only`` path into (this_level, child_level).

    ``'a.b.c'`` → ``('a', 'b.c')``.  No dots → ``(value, None)``.
    ``None`` → ``(None, None)``.

    Raises ``CompilationError`` on malformed paths (empty segments from
    leading/trailing dots like ``'.b'``, ``'a.'``, or ``'a..b'``).
    """
    if only_node is None or "." not in only_node:
        return only_node, None
    if ".." in only_node:
        raise CompilationError(
            f"Invalid --only path: '{only_node}' contains an empty segment",
            phase="only_node_resolution",
            suggestion="Use 'parent-node.child-node' format, e.g. '--only my-workflow.target-step'.",
        )
    first, remaining = only_node.split(".", 1)
    if not first or not remaining:
        raise CompilationError(
            f"Invalid --only path: '{only_node}' contains an empty segment",
            phase="only_node_resolution",
            suggestion="Use 'parent-node.child-node' format, e.g. '--only my-workflow.target-step'.",
        )
    return first, remaining


def is_clean_termination(action: Optional[str], successors: dict[str, Any]) -> bool:
    """Whether the graph walk should clean-terminate after a node returns `action`.

    Shared predicate between the runtime engine (`_handle_no_successor` —
    called when no successor matches the action) and the dry-run planner's
    `_classify`. Centralized here so termination semantics can't drift.

    Two cases count as clean termination:
    - `action == "end"` — the intentional-termination sentinel a node can
      return to stop the walk without a routing error.
    - All successor edges are on-error handlers (`all(k == "error" ...)`)
      — no forward path exists; falling off the end is clean.

    Returns `True` for clean termination, `False` when the missing-successor
    condition should surface as a routing error.
    """
    return action == "end" or all(k == "error" for k in successors)


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

    def _validate_only_target(self, workflow: CompiledWorkflow, this_only: str, child_only: str | None) -> None:
        """Validate ``--only`` target: must exist, dotted paths must target a sub-workflow."""
        if this_only not in workflow.node_configs:
            available = sorted(workflow.node_configs.keys())
            raise CompilationError(
                f"Node '{this_only}' not found",
                phase="only_node_resolution",
                details={"available_nodes": available},
                suggestion=f"Available nodes: {', '.join(available)}",
            )
        if child_only:
            target_config = workflow.node_configs[this_only]
            if target_config.node_type_name != "WorkflowExecutor":
                raise CompilationError(
                    f"Node '{this_only}' is not a sub-workflow",
                    phase="only_node_resolution",
                    details={"node_type": target_config.node_type_name},
                    suggestion=f"Cannot use dotted path '{self.only_node}' — "
                    f"'{this_only}' is a {target_config.node_type_name}, not a sub-workflow.",
                )

    def _run_node_with_child_only(
        self, node: Any, config: NodeConfig, shared: dict[str, Any], child_only: str | None
    ) -> str:
        """Execute a node, injecting ``_pflow_child_only_node`` for sub-workflow targeting.

        The key is written before and cleaned up after execution (including on
        exception) so it never leaks into ``shared_after``.
        """
        if child_only:
            shared["_pflow_child_only_node"] = child_only
        try:
            return self._execute_node(node, config, shared)
        finally:
            if child_only:
                shared.pop("_pflow_child_only_node", None)

    def run(self, workflow: CompiledWorkflow, shared: dict[str, Any]) -> str:
        """Execute a compiled workflow. Returns action string.

        Installs ``self.trace`` into ``shared["__trace_collector__"]`` and a
        per-workflow ``CacheRenderContext`` map into
        ``shared["__pflow_cache_render__"]`` for the duration of the run.
        The save/restore pattern correctly handles nested sub-workflow runs
        (parent's values reinstated after a child engine.run completes) for
        both ``mapped`` and ``shared`` storage modes.
        """
        # Install this engine's trace collector so LLMNode.prep() can find
        # it. Save+restore handles nested sub-workflow runs (parent's
        # collector reinstated after a child engine.run completes) for both
        # storage_mode=mapped and storage_mode=shared.
        #
        # Write-back form (not .pop()) because shared may be a
        # NamespacedSharedStore (sub-workflow path) which doesn't implement
        # pop. All consumers of __trace_collector__ use .get() (verified by
        # grep — runner.py, success_formatter.py, error_formatter.py,
        # cli/error_output.py, workflow_executor.py), so writing None back
        # when the key was originally absent is indistinguishable from
        # absence to every reader.
        # Task 159 B3.2: install per-workflow CacheRenderContext map. Always
        # install (even when the dict is empty) so child engine.run masks the
        # parent's value during sub-workflow execution. MappingProxyType
        # enforces read-only at the call sites; consumers use the
        # ``(shared.get(K) or {}).get(node_id)`` defensive pattern. On
        # restore-from-absent, write the module-level _EMPTY_CACHE_RENDER
        # constant rather than ``None`` so a future consumer that drops the
        # ``or {}`` defense hits a Mapping, not None.get(...).
        #
        # Build BEFORE installing anything so an exception during
        # ``build_cache_render_dict`` leaves shared completely unchanged —
        # otherwise a build-time exception would leak the trace install
        # (saved_trace overwritten, finally never fires).
        saved_trace = shared.get("__trace_collector__")
        saved_cache_render = shared.get("__pflow_cache_render__")
        new_cache_render = MappingProxyType(build_cache_render_dict(workflow, shared))
        if self.trace is not None:
            shared["__trace_collector__"] = self.trace
        shared["__pflow_cache_render__"] = new_cache_render
        try:
            return self._run_inner(workflow, shared)
        finally:
            shared["__trace_collector__"] = saved_trace
            shared["__pflow_cache_render__"] = (
                saved_cache_render if saved_cache_render is not None else _EMPTY_CACHE_RENDER
            )

    def _run_inner(self, workflow: CompiledWorkflow, shared: dict[str, Any]) -> str:
        """Run body — split out so run() can wrap with save/restore cleanly."""
        this_only, child_only = parse_only_path(self.only_node)

        # 0. Validate --only target
        if this_only:
            self._validate_only_target(workflow, this_only, child_only)

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
            is_only_target = this_only is not None and node_id == this_only

            last_action = self._run_node_with_child_only(curr, config, shared, child_only if is_only_target else None)

            # --only: stop after target node
            # (__execution__["only_node"] was already written by _execute_node
            # step 2 for this same node)
            if is_only_target:
                break

            # Follow successor edge
            nxt = curr.successors.get(last_action or "default")
            if not nxt:
                last_action = self._handle_no_successor(last_action, node_id, curr, shared)
                break
            curr = nxt

        # 3. Populate declared outputs
        self._populate_outputs(workflow, shared, last_action)

        return str(last_action) if last_action else "default"

    def _populate_outputs(self, workflow: CompiledWorkflow, shared: dict[str, Any], last_action: Optional[str]) -> None:
        """Resolve declared workflow outputs into the shared store.

        Under ``--only``, outputs whose source templates cannot resolve (because
        the source node was skipped) are skipped without error — the resolver
        writes each successful resolution to ``shared`` during iteration before
        raising ``OutputResolutionError`` for failures, so resolvable outputs
        are still populated. Non-``--only`` runs re-raise so the user sees the
        full error.
        """
        is_error = last_action and isinstance(last_action, str) and str(last_action).startswith("error")
        if not workflow.outputs or is_error:
            return

        from pflow.core.user_errors import OutputResolutionError
        from pflow.runtime.output_resolver import populate_declared_outputs

        try:
            populate_declared_outputs(shared, {"outputs": workflow.outputs})
        except OutputResolutionError:
            if not self.only_node:
                raise

    def _handle_no_successor(
        self, last_action: Optional[str], node_id: str, curr: Any, shared: dict[str, Any]
    ) -> Optional[str]:
        """Handle case where no successor matches the current action.

        Distinguishes intentional termination from routing errors:
        - "end" action or no forward (non-error) edges → clean termination
        - Unmatched action with forward edges present → routing failure

        Returns the (possibly updated) last_action.
        """
        if is_clean_termination(last_action, curr.successors):
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
        # The trace event was recorded at step 16 with success=True (because
        # is_error_action was False for this custom action). Flip it so trace
        # and __failures__ agree — see GH #250. Note: the mutation only sets
        # success=False + error text; the failure category (FAILURE_CATEGORY_ROUTING)
        # lives on the __failures__ record set by mark_node_failed above, not on
        # the trace event itself (events don't carry a category field).
        if self.trace is not None:
            self.trace.mark_last_event_failed(node_id, error=warning_msg)
        return "error"

    def _execute_node(self, node: Any, config: NodeConfig, shared: dict[str, Any]) -> str:  # noqa: C901
        """Execute a single node with all runtime concerns."""
        start_time = time.perf_counter()
        shared_keys_before = set(shared.keys()) if (self.trace or self.metrics) else set()

        # (Step 1 — LLM trace registration — removed in Task 158 Phase A
        # post-cleanup. The trace collector is now installed by `run()`
        # into ``shared["__trace_collector__"]`` and resolved by
        # ``LLMNode.prep()`` directly. Lifecycle step numbers below
        # preserved for cross-reference with engine/CLAUDE.md.)

        # 2. Execution state
        initialize_execution_state(shared)
        if self.only_node:
            shared["__execution__"]["only_node"] = self.only_node

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
                # Task 159 E.1: ``cache_source`` is keyword-driven by plan status.
                # - ``cached_memo``: ``apply_memo_hit`` already augments
                #   ``llm_usage`` with ``cache_source="memo"`` plus the matching
                #   key + age. Pass ``cache_source=None`` so
                #   ``handle_cached_execution`` does NOT overwrite that augment.
                # - ``cached_in_process``: nothing has augmented yet; pass
                #   ``"in_process"`` so the trace correctly tags the intra-run
                #   loop-revisit hit. DD#22 distinguishes the two layers.
                if plan.status == "cached_memo" and plan.cached_output is not None and plan.cached_action is not None:
                    apply_memo_hit(
                        config.node_id,
                        shared,
                        plan.cached_action,
                        plan.cached_output,
                        plan.config_hash,
                        node_type_name=config.node_type_name,
                        cache_key=plan.cache_key,
                        created_at=plan.cached_created_at,
                    )
                    cached_source: Optional[str] = None
                else:
                    cached_source = "in_process"
                return str(
                    handle_cached_execution(
                        config.node_id,
                        shared,
                        plan.cached_action,
                        shared_keys_before,
                        config.node_type_name,
                        node.params,
                        self.trace,
                        cache_source=cached_source,
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
                action = execute_batch(node, config, shared, self._execute_single_node)
                # NOTE: per-item batch trace events stay in ``shared["_batch_trace"]``
                # until the single drain right before ``record_trace`` below. Draining
                # here would lose the items if any later step (write_memo_cache,
                # detect_api_warning, metrics) raised — the except handler's drain
                # would then pop an already-empty buffer. Symmetry with the except
                # path is the whole point of Bundle 8's shared-store recovery channel.
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
                # Drain the per-item buffer even though ``handle_api_warning``
                # discards batch items today (pre-existing, see W2 in PR #405
                # review). The drain prevents the accumulator from leaking into
                # shared state for the rest of the workflow run.
                if config.batch_config:
                    _collect_batch_trace(shared, config.node_id)
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
                write_memo_cache(
                    config.node_id,
                    shared,
                    cache_key,
                    action,
                    duration_ms=duration_ms,
                    node_type_name=config.node_type_name,
                )

            # 14. Metrics
            if self.metrics:
                self.metrics.record_node_execution(config.node_id, duration_ms)

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

            # 16. Trace — node returning "error" action is a failure even without exception.
            # Single drain site for batch trace events: collects from the shared
            # store accumulator just before record_trace consumes them. The
            # except handler below has a symmetric drain so completed-before-
            # failure events survive into the trace identically.
            if config.batch_config:
                batch_trace_items = _collect_batch_trace(shared, config.node_id)
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

            # Extract partial resolutions from template errors (attached by resolve_templates)
            error_resolutions = getattr(e, "_pflow_partial_resolutions", None) or last_resolutions

            # Drain per-item trace events on the failure path too. When
            # execute_batch raises (fail_fast all-failed), items that completed
            # before the failing item still appear in shared["_batch_trace"].
            # Without this drain, completed nested LLM work would silently vanish
            # from the trace, and analyze-cache would report `[unexecuted]` for
            # nodes that actually ran.
            batch_trace_items = _collect_batch_trace(shared, config.node_id) if config.batch_config else None

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
