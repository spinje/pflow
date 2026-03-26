"""Unified wrapper for metrics collection and optional tracing."""

import contextlib
import hashlib
import logging
import os
import time
from typing import Any, Optional, cast

from pflow.core.exceptions import MaxNodeVisitsError
from pflow.core.llm_pricing import enrich_llm_usage_with_cost

from .api_warning_detector import detect_api_warning

try:
    MAX_NODE_VISITS = int(os.environ.get("PFLOW_MAX_NODE_VISITS", "100"))
except ValueError:
    MAX_NODE_VISITS = 100

logger = logging.getLogger(__name__)


class InstrumentedNodeWrapper:
    """Wrapper that instruments nodes for metrics and optional tracing.

    This wrapper serves both lightweight metrics collection (always with JSON output)
    and detailed tracing (enabled by default; disable via --no-trace). It must be the outermost wrapper
    to capture all operations including namespace and template resolution.
    """

    def __init__(
        self,
        inner_node: Any,
        node_id: str,
        metrics_collector: Optional[Any] = None,
        trace_collector: Optional[Any] = None,
    ):
        """Initialize the instrumented wrapper.

        Args:
            inner_node: The node being wrapped (may be another wrapper)
            node_id: Unique identifier for this node
            metrics_collector: Optional MetricsCollector instance
            trace_collector: Optional WorkflowTraceCollector instance
        """
        self.inner_node = inner_node
        self.node_id = node_id
        self.metrics = metrics_collector
        self.trace = trace_collector

        # Copy Flow-required attributes from inner node
        if hasattr(inner_node, "successors"):
            self.successors = inner_node.successors
        if hasattr(inner_node, "params"):
            self.params = inner_node.params

    def _get_node_params(self) -> Optional[dict[str, Any]]:
        """Get params from the innermost node by traversing the wrapper chain.

        Returns:
            The params dict from the actual node, or None if not found
        """
        current = self.inner_node

        # Traverse down the wrapper chain to find the actual node with params
        while current:
            # Check for params on current level - make sure it's a dict with actual content
            if (
                hasattr(current, "params")
                and current.params is not None
                and isinstance(current.params, dict)
                and current.params
            ):
                return cast(dict[str, Any], current.params)

            # Check if this is another wrapper and continue traversing
            if hasattr(current, "inner_node"):
                current = current.inner_node
            elif hasattr(current, "_inner_node"):
                current = current._inner_node
            elif hasattr(current, "_wrapped"):
                current = current._wrapped
            else:
                break

        return None

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attributes to inner node.

        This follows the exact pattern from existing wrappers to prevent
        pickle/copy infinite recursion while delegating everything else.
        """
        # Prevent infinite recursion during copy operations
        if name in ("__setstate__", "__getstate__", "__getnewargs__", "__getnewargs_ex__"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        # Get inner_node without triggering __getattr__ again
        inner = object.__getattribute__(self, "inner_node")
        return getattr(inner, name)

    def __rshift__(self, action_str: str) -> Any:
        """Delegate >> operator for flow connections."""
        return self.inner_node >> action_str

    def __sub__(self, action_str: str) -> Any:
        """Delegate - operator for flow connections."""
        return self.inner_node - action_str

    def _enrich_llm_cost(self, shared: dict[str, Any]) -> None:
        """Enrich llm_usage with cost_usd before trace records it.

        Checks both root level (non-namespaced) and namespaced location.

        Args:
            shared: Current shared store
        """
        llm_usage = None
        if "llm_usage" in shared:
            llm_usage = shared["llm_usage"]
        elif self.node_id in shared and isinstance(shared[self.node_id], dict):
            llm_usage = shared[self.node_id].get("llm_usage")
        if isinstance(llm_usage, dict):
            enrich_llm_usage_with_cost(llm_usage)

    def _handle_api_warning(
        self,
        shared: dict[str, Any],
        warning_msg: str,
        start_time: float,
        shared_keys_before: Optional[set[str]],
        callback: Optional[Any],
    ) -> str:
        """Handle API warning detection.

        Args:
            shared: The shared store
            warning_msg: Warning message
            start_time: Start time for duration calculation
            shared_keys_before: Keys in shared store before execution
            callback: Progress callback

        Returns:
            "error" to stop workflow
        """
        logger.debug(f"API warning detected for {self.node_id}: {warning_msg}")

        # Store warning for display
        if "__warnings__" not in shared:
            shared["__warnings__"] = {}
        shared["__warnings__"][self.node_id] = warning_msg

        # Record as completed (to prevent re-execution) but return error to stop workflow
        shared["__execution__"]["completed_nodes"].append(self.node_id)
        shared["__execution__"]["node_actions"][self.node_id] = "error"
        shared["__execution__"]["failed_node"] = self.node_id

        # Calculate duration for metrics
        duration_ms = (time.perf_counter() - start_time) * 1000

        # Record metrics if collector present
        if self.metrics:
            self.metrics.record_node_execution(self.node_id, duration_ms)

        # Call progress callback with warning
        if callable(callback):
            depth = shared.get("_pflow_depth", 0)
            with contextlib.suppress(Exception):
                callback(self.node_id, "node_warning", warning_msg, depth)

        # Record trace with warning message as error context
        self._record_trace(duration_ms, shared, shared_keys_before, success=False, error=warning_msg)

        logger.info(f"Node {self.node_id} detected API warning: {warning_msg}")
        return "error"  # Stop workflow but checkpoint is saved

    def _cache_result_if_successful(self, shared: dict[str, Any], result: Any) -> None:
        """Cache node result if successful.

        Args:
            shared: The shared store
            result: Node execution result
        """
        if result != "error":
            # Compute and store configuration hash
            node_config = self._compute_node_config()
            node_hash = self._compute_config_hash(node_config)

            shared["__execution__"]["completed_nodes"].append(self.node_id)
            shared["__execution__"]["node_actions"][self.node_id] = result
            shared["__execution__"]["node_hashes"][self.node_id] = node_hash

            logger.debug(f"Node {self.node_id} cached with hash {node_hash[:8]}...")
        else:
            # Don't cache error results
            logger.debug(f"Node {self.node_id} returned error, not caching")
            # Record the failed node for execution state
            shared["__execution__"]["failed_node"] = self.node_id

    def _call_completion_callback(
        self,
        shared: dict[str, Any],
        callback: Optional[Any],
        result: Any,
        duration_ms: float,
    ) -> None:
        """Call completion callback if present.

        Args:
            shared: The shared store
            callback: Progress callback function
            result: Node execution result
            duration_ms: Execution duration in milliseconds
        """
        if not callable(callback):
            return

        depth = shared.get("_pflow_depth", 0)

        # Get exit code if available (for shell nodes)
        exit_code = shared.get(self.node_id, {}).get("exit_code")
        error_msg = None
        ignore_errors = False

        if result == "error":
            # Fatal error case - workflow will stop
            error_msg = f"Command failed with exit code {exit_code}" if exit_code else "Failed"
        elif exit_code and exit_code != 0:
            # Warning case - command failed but continuing with ignore_errors
            ignore_errors = self._get_node_param("ignore_errors", False)
            if ignore_errors:
                error_msg = f"Command failed with exit code {exit_code}"

        # Detect if this is a batch node by checking for batch_metadata in output
        node_output = shared.get(self.node_id, {})
        is_batch = isinstance(node_output, dict) and "batch_metadata" in node_output
        batch_total = None
        batch_success_count = None
        if is_batch:
            batch_total = node_output.get("count", 0)
            batch_success_count = node_output.get("success_count", 0)

        # Never let callback errors break execution
        with contextlib.suppress(Exception):
            # Always use node_complete event to keep error on same line
            callback(
                self.node_id,
                "node_complete",
                duration_ms,
                depth,
                error_message=error_msg,
                ignore_errors=ignore_errors,
                is_error=(result == "error"),
                is_batch=is_batch,
                batch_total=batch_total,
                batch_success_count=batch_success_count,
            )

    def _find_template_wrapper(self) -> Any:
        """Traverse wrapper chain to find TemplateAwareNodeWrapper.

        Returns:
            The template wrapper if found, None otherwise
        """
        current = self.inner_node
        while current:
            # Check by attribute presence (avoids import)
            if hasattr(current, "last_resolutions"):
                return current
            if hasattr(current, "inner_node"):
                current = current.inner_node
            elif hasattr(current, "_inner_node"):
                current = current._inner_node
            elif hasattr(current, "_wrapped"):
                current = current._wrapped
            else:
                break
        return None

    def _find_batch_or_workflow_node(self) -> tuple[str | None, Any]:
        """Traverse wrapper chain to find PflowBatchNode or WorkflowExecutor.

        Returns:
            Tuple of (type_name, node) or (None, None)
        """
        current = self.inner_node
        while current:
            cls_name = type(current).__name__
            if cls_name == "PflowBatchNode":
                return ("batch", current)
            if cls_name == "WorkflowExecutor":
                return ("workflow", current)
            if hasattr(current, "inner_node"):
                current = current.inner_node
            elif hasattr(current, "_inner_node"):
                current = current._inner_node
            elif hasattr(current, "_wrapped"):
                current = current._wrapped
            else:
                break
        return (None, None)

    def _record_trace(
        self,
        duration_ms: float,
        shared: dict[str, Any],
        shared_keys_before: set[str] | None,
        success: bool,
        error: str | None = None,
        cached: bool = False,
    ) -> None:
        """Record execution trace if collector is present.

        Args:
            duration_ms: Execution duration in milliseconds
            shared: Current shared store (after execution)
            shared_keys_before: Keys in shared store before execution
            success: Whether execution succeeded
            error: Error message if execution failed
            cached: Whether this node used cached results
        """
        if not self.trace:
            return

        actual_node_class = self._get_actual_node_class()

        # Get template resolutions from wrapper chain
        template_wrapper = self._find_template_wrapper()
        template_resolutions = template_wrapper.last_resolutions if template_wrapper else {}

        # Get node params (original, before resolution)
        node_params = self._get_node_params() or {}

        # Get node output (just this node's namespace, not full store)
        node_output = shared.get(self.node_id)
        if isinstance(node_output, dict):
            node_output = dict(node_output)  # shallow copy
        elif node_output is not None:
            node_output = {"value": node_output}
        else:
            node_output = {}

        # Compute mutations from key sets (filter system/internal keys)
        shared_keys_after = set(shared.keys())
        added = shared_keys_after - shared_keys_before if shared_keys_before is not None else set()
        removed = shared_keys_before - shared_keys_after if shared_keys_before is not None else set()
        mutations = {
            "added": sorted(
                k
                for k in added
                if not k.startswith("__")
                and not k.startswith("_pflow")
                and not k.startswith("_trace")
                and not k.startswith("_batch")
            ),
            "removed": sorted(
                k
                for k in removed
                if not k.startswith("__")
                and not k.startswith("_pflow")
                and not k.startswith("_trace")
                and not k.startswith("_batch")
            ),
            "modified": [],  # Can't detect value changes without full snapshot — acceptable tradeoff
        }

        # Check for nested trace data (batch items, sub-workflow events)
        batch_or_wf_type, batch_or_wf_node = self._find_batch_or_workflow_node()
        batch_items = None
        sub_workflow_events = None
        if batch_or_wf_type == "batch" and hasattr(batch_or_wf_node, "_trace_items"):
            batch_items = batch_or_wf_node._trace_items
        elif batch_or_wf_type == "workflow" and hasattr(batch_or_wf_node, "_child_trace_events"):
            sub_workflow_events = batch_or_wf_node._child_trace_events

        self.trace.record_node_execution(
            node_id=self.node_id,
            node_type=actual_node_class.__name__,
            duration_ms=duration_ms,
            success=success,
            error=error,
            node_params=node_params,
            template_resolutions=template_resolutions,
            node_output=node_output,
            mutations=mutations,
            batch_items=batch_items,
            sub_workflow_events=sub_workflow_events,
            cached=cached,
        )

    def _compute_node_config(self) -> dict[str, Any]:
        """Compute the configuration dictionary for the node.

        Includes all semantically relevant configuration: node type, static params,
        template params (raw templates), batch semantic config. Excludes noise like
        _source_line metadata keys injected by the markdown parser.

        Returns:
            Dictionary containing node type and parameters
        """
        # Get the actual node class using our helper method
        actual_node_class = self._get_actual_node_class()

        # Build configuration dictionary
        node_config: dict[str, Any] = {"type": actual_node_class.__name__, "params": {}}

        # Get the actual node instance to access params
        actual_node = self.inner_node
        while (
            hasattr(actual_node, "_inner_node")
            or hasattr(actual_node, "inner_node")
            or hasattr(actual_node, "_wrapped")
        ):
            if hasattr(actual_node, "_inner_node"):
                actual_node = actual_node._inner_node
            elif hasattr(actual_node, "inner_node"):
                actual_node = actual_node.inner_node
            elif hasattr(actual_node, "_wrapped"):
                actual_node = actual_node._wrapped
            else:
                break

        # Include parameters if present
        if hasattr(actual_node, "params") and actual_node.params:
            # Sort keys for deterministic hashing
            node_config["params"] = dict(sorted(actual_node.params.items()))

        # Include template params from TemplateAwareNodeWrapper (raw templates, not resolved)
        template_wrapper = self._find_template_wrapper()
        if template_wrapper and hasattr(template_wrapper, "template_params") and template_wrapper.template_params:
            node_config["template_params"] = dict(sorted(template_wrapper.template_params.items()))

        # Include semantic batch config (affects results)
        node_type, batch_node = self._find_batch_or_workflow_node()
        if node_type == "batch" and batch_node:
            node_config["batch"] = {
                "items_template": getattr(batch_node, "items_template", None),
                "item_alias": getattr(batch_node, "item_alias", "item"),
                "error_handling": getattr(batch_node, "error_handling", "fail_fast"),
                "max_retries": getattr(batch_node, "max_retries", 1),
            }

        # Filter out _source_line noise from params (injected by markdown parser,
        # changes when lines move but doesn't affect node behavior)
        if node_config.get("params"):
            node_config["params"] = {k: v for k, v in node_config["params"].items() if not k.endswith("_source_line")}

        return node_config

    def _compute_config_hash(self, config: dict[str, Any]) -> str:
        """Compute a hash of the node configuration.

        Args:
            config: Node configuration dictionary

        Returns:
            Hexadecimal hash string
        """
        from pflow.runtime.cache import _deterministic_json

        config_json = _deterministic_json(config)
        # MD5 is used here for fast configuration change detection, not for security.
        # This hash is only used to detect if a node's parameters have changed between
        # workflow runs, so cryptographic security is not required. MD5 is chosen for
        # its speed since this check happens frequently during workflow execution.
        return hashlib.md5(config_json.encode()).hexdigest()  # noqa: S324

    def _get_node_param(self, param_name: str, default: Any = None) -> Any:
        """Get a parameter from the node configuration.

        Args:
            param_name: Name of the parameter to retrieve
            default: Default value if parameter not found

        Returns:
            Parameter value or default
        """
        # Try to get params from the innermost node
        params = self._get_node_params()
        if params:
            return params.get(param_name, default)
        return default

    def _initialize_execution_state(self, shared: dict[str, Any]) -> None:
        """Initialize execution state and checkpoint structure.

        Args:
            shared: The shared store for inter-node communication
        """
        # Initialize checkpoint structure if not present
        if "__execution__" not in shared:
            shared["__execution__"] = {
                "completed_nodes": [],
                "node_actions": {},
                "node_hashes": {},  # Store configuration hashes
                "failed_node": None,
                "node_visit_counts": {},
            }
        else:
            # Ensure node_hashes exists in existing checkpoints (backward compatibility)
            if "node_hashes" not in shared["__execution__"]:
                shared["__execution__"]["node_hashes"] = {}
            if "node_visit_counts" not in shared["__execution__"]:
                shared["__execution__"]["node_visit_counts"] = {}

        # Initialize cache hits tracking for JSON output
        if "__cache_hits__" not in shared:
            shared["__cache_hits__"] = []

    def _check_cache_validity(self, shared: dict[str, Any]) -> tuple[bool, Optional[Any]]:
        """Check if node is cached and if cache is valid.

        Args:
            shared: The shared store for inter-node communication

        Returns:
            Tuple of (is_cached_and_valid, cached_action)
        """
        if self.node_id not in shared["__execution__"]["completed_nodes"]:
            return False, None

        # Validate cache using configuration hash
        node_config = self._compute_node_config()
        current_hash = self._compute_config_hash(node_config)
        cached_hash = shared["__execution__"]["node_hashes"].get(self.node_id)

        if current_hash == cached_hash:
            # Cache is valid - use it
            cached_action = shared["__execution__"]["node_actions"].get(self.node_id, "default")
            return True, cached_action
        else:
            # Cache is invalid - node configuration changed
            logger.info(f"Node {self.node_id} configuration changed, invalidating cache")
            self._invalidate_cache(shared)
            return False, None

    def _invalidate_cache(self, shared: dict[str, Any]) -> None:
        """Invalidate cached node data.

        Args:
            shared: The shared store for inter-node communication
        """
        # Clear cache entries
        shared["__execution__"]["completed_nodes"].remove(self.node_id)
        shared["__execution__"]["node_actions"].pop(self.node_id, None)
        shared["__execution__"]["node_hashes"].pop(self.node_id, None)

    def _handle_cached_execution(
        self, shared: dict[str, Any], cached_action: Any, shared_keys_before: set[str] | None
    ) -> Any:
        """Handle cached node execution.

        Args:
            shared: The shared store for inter-node communication
            cached_action: The cached action result
            shared_keys_before: Keys in shared store before execution (for trace)

        Returns:
            The cached action result
        """
        # Record cache hit for JSON output
        if "__cache_hits__" not in shared:
            shared["__cache_hits__"] = []
        shared["__cache_hits__"].append(self.node_id)

        # Record trace event for cached node (so reports show it)
        self._record_trace(0.0, shared, shared_keys_before, success=(cached_action != "error"), cached=True)

        # Call progress callback for cached node (same format as normal execution)
        callback = shared.get("__progress_callback__")
        if callable(callback):
            depth = shared.get("_pflow_depth", 0)
            with contextlib.suppress(Exception):
                callback(self.node_id, "node_start", None, depth)  # Show node name first
                callback(self.node_id, "node_cached", None, depth)  # Complete the line

        logger.debug(f"Node {self.node_id} skipped (already completed), returning cached action: {cached_action}")
        return cached_action

    def _enforce_loop_guard(self, shared: dict[str, Any]) -> dict[str, int]:
        """Enforce loop guard and invalidate in-process cache for revisited nodes.

        Returns the visit_counts dict for use by memoization checks.
        """
        visit_counts: dict[str, int] = shared["__execution__"]["node_visit_counts"]
        visit_counts[self.node_id] = visit_counts.get(self.node_id, 0) + 1
        if visit_counts[self.node_id] > MAX_NODE_VISITS:
            raise MaxNodeVisitsError(self.node_id, visit_counts[self.node_id], MAX_NODE_VISITS)

        # Invalidate cache for revisited nodes — cache is for workflow resume,
        # not loops. Without this, looping nodes return the first iteration's
        # cached action forever and never re-evaluate exit conditions.
        if visit_counts[self.node_id] > 1:
            completed = shared["__execution__"]["completed_nodes"]
            if self.node_id in completed:
                completed.remove(self.node_id)
                shared["__execution__"]["node_actions"].pop(self.node_id, None)
                shared["__execution__"]["node_hashes"].pop(self.node_id, None)

        return visit_counts

    def _write_memo_cache(self, shared: dict[str, Any], result: str, memo_cache_key: Optional[str]) -> None:
        """Write node output to memoization cache after successful execution."""
        if not memo_cache_key or result == "error":
            return
        memo_cache = shared.get("__memoization_cache__")
        if not memo_cache:
            return
        node_output = shared.get(self.node_id)
        if node_output is not None:
            workflow_path = shared.get("_pflow_workflow_file")
            # Non-dict branch is dead code: NamespacedNodeWrapper guarantees shared[node_id] is always a dict.
            # Kept as defensive fallback — if the invariant ever changes, prefer wrapping over crashing.
            output_dict = dict(node_output) if isinstance(node_output, dict) else {"value": node_output}
            memo_cache.put(memo_cache_key, self.node_id, workflow_path, result, output_dict)

    def _check_memo_cache(
        self,
        shared: dict[str, Any],
        visit_counts: dict[str, int],
        shared_keys_before: Optional[set[str]],
    ) -> tuple[bool, Any, Optional[str]]:
        """Check the memoization cache for a cached result.

        Returns:
            Tuple of (hit, result, cache_key):
            - hit=True, result=action_result, cache_key=None on cache hit
            - hit=False, result=None, cache_key=str on cache miss (key for later write)
            - hit=False, result=None, cache_key=None when memoization is skipped
        """
        memo_cache = shared.get("__memoization_cache__")
        if not memo_cache or visit_counts.get(self.node_id, 0) > 1:
            return False, None, None

        # Skip memoization for workflow nodes — sub-workflow files may have changed
        # since the cache was populated. Inner nodes are individually cached via the
        # propagated __memoization_cache__, so this doesn't lose caching benefits.
        # String check (not isinstance) to avoid circular import: wrappers → workflow_executor.
        # Same pattern as _find_batch_or_workflow_node().
        if self._get_actual_node_class().__name__ == "WorkflowExecutor":
            return False, None, None

        cache_key = self._compute_memo_cache_key(shared)
        if not cache_key:
            return False, None, None

        cached = memo_cache.get(cache_key)
        if cached is None:
            return False, None, cache_key

        cached_action, cached_output = cached
        # Restore output for downstream template resolution
        shared[self.node_id] = cached_output
        # Record in in-process execution state (for checkpoint consistency)
        node_config = self._compute_node_config()
        node_hash = self._compute_config_hash(node_config)
        shared["__execution__"]["completed_nodes"].append(self.node_id)
        shared["__execution__"]["node_actions"][self.node_id] = cached_action
        shared["__execution__"]["node_hashes"][self.node_id] = node_hash
        result = self._handle_cached_execution(shared, cached_action, shared_keys_before)
        return True, result, None

    def _is_batch_node(self) -> bool:
        """Check if this wrapper chain contains a batch node."""
        node_type, _ = self._find_batch_or_workflow_node()
        return node_type == "batch"

    def _compute_memo_cache_key(self, shared: dict[str, Any]) -> Optional[str]:
        """Compute memoization cache key for the current node.

        For non-batch nodes: hash(config + resolved_inputs)
        For batch nodes: hash(config + semantic_batch_config + resolved_items)

        Returns None if the key cannot be computed (e.g., batch items can't be resolved).
        """
        from pflow.runtime.cache import compute_node_cache_key

        config_hash = self._compute_config_hash(self._compute_node_config())

        if self._is_batch_node():
            return self._compute_batch_memo_key(config_hash, shared)

        # Non-batch: use resolved template inputs
        template_wrapper = self._find_template_wrapper()
        if template_wrapper:
            try:
                merged_params = template_wrapper.resolve_templates(shared)
                return compute_node_cache_key(config_hash, merged_params)
            except Exception:
                # Template resolution failed — can't compute cache key, skip memoization
                logger.debug("Failed to resolve templates for memo cache key", exc_info=True)
                return None
        else:
            return compute_node_cache_key(config_hash)

    def _compute_batch_memo_key(self, config_hash: str, shared: dict[str, Any]) -> Optional[str]:
        """Compute cache key for a batch node.

        Returns None if items can't be resolved.
        """
        from pflow.runtime.cache import compute_batch_cache_key

        node_type, batch_node = self._find_batch_or_workflow_node()
        if node_type != "batch" or not batch_node:
            return None

        items_template = getattr(batch_node, "items_template", None)
        if items_template is None:
            return None

        try:
            from .batch_node import resolve_batch_items

            resolved_items = resolve_batch_items(items_template, shared)
            if not isinstance(resolved_items, list):
                return None
        except Exception:
            logger.debug("Failed to resolve batch items for memo cache key", exc_info=True)
            return None

        semantic_config = {
            "items_template": items_template,
            "item_alias": getattr(batch_node, "item_alias", "item"),
            "error_handling": getattr(batch_node, "error_handling", "fail_fast"),
            "max_retries": getattr(batch_node, "max_retries", 1),
        }

        return compute_batch_cache_key(config_hash, semantic_config, resolved_items)

    def _run(self, shared: dict[str, Any]) -> Any:
        """Execute the wrapped node with metrics and optional tracing.

        Args:
            shared: The shared store for inter-node communication

        Returns:
            The result from the inner node execution
        """
        # Capture state before execution (for tracing)
        start_time = time.perf_counter()
        shared_keys_before = set(shared.keys()) if (self.trace or self.metrics) else None

        # Set up LLM interception if needed
        self._setup_llm_interception()

        # Initialize execution state
        self._initialize_execution_state(shared)

        # Loop guard + cache invalidation for revisited nodes
        visit_counts = self._enforce_loop_guard(shared)

        # Memoization cache check (cross-run persistence via SQLite)
        memo_hit, memo_result, memo_cache_key = self._check_memo_cache(shared, visit_counts, shared_keys_before)
        if memo_hit:
            return memo_result

        # Check in-process cache validity (for workflow resume within same run)
        is_cached, cached_action = self._check_cache_validity(shared)
        if is_cached:
            return self._handle_cached_execution(shared, cached_action, shared_keys_before)

        # Call progress callback for node start if present
        callback = shared.get("__progress_callback__")
        if callable(callback):
            depth = shared.get("_pflow_depth", 0)
            # Never let callback errors break execution
            with contextlib.suppress(Exception):
                callback(self.node_id, "node_start", None, depth)

        try:
            # Execute the inner node
            result = self.inner_node._run(shared)

            # Check for API warning patterns (execution succeeded but returned error data)
            warning_msg = detect_api_warning(self.node_id, shared)
            if warning_msg:
                return self._handle_api_warning(shared, warning_msg, start_time, shared_keys_before, callback)

            # Cache successful results (in-process)
            self._cache_result_if_successful(shared, result)

            # Store in memoization cache after successful execution
            self._write_memo_cache(shared, result, memo_cache_key)

            # Calculate duration
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Record metrics if collector present
            if self.metrics:
                self.metrics.record_node_execution(self.node_id, duration_ms)

            # Enrich LLM usage with cost before trace records it
            self._enrich_llm_cost(shared)

            # Record trace if collector present
            # Node returning "error" action is a failure, regardless of API warning detection
            trace_success = result != "error"
            self._record_trace(duration_ms, shared, shared_keys_before, success=trace_success)

            # Call progress callback for node complete if present
            self._call_completion_callback(shared, callback, result, duration_ms)

            return result

        except Exception as e:
            # Still record metrics and trace on failure
            duration_ms = (time.perf_counter() - start_time) * 1000

            if self.metrics:
                self.metrics.record_node_execution(self.node_id, duration_ms)

            # Enrich LLM usage with cost before trace records it
            self._enrich_llm_cost(shared)

            # Record trace with error
            self._record_trace(duration_ms, shared, shared_keys_before, success=False, error=str(e))

            # Record failure in checkpoint
            shared["__execution__"]["failed_node"] = self.node_id

            # Re-raise the exception
            raise

    def _get_actual_node_class(self) -> type:
        """Get the actual node class by traversing the wrapper chain.

        Returns:
            The class of the actual node (not a wrapper)
        """
        current = self.inner_node

        # Traverse down the wrapper chain to find the actual node
        while current:
            # Check if this is another wrapper and continue traversing
            if hasattr(current, "inner_node"):
                current = current.inner_node
            elif hasattr(current, "_inner_node"):
                current = current._inner_node
            elif hasattr(current, "_wrapped"):
                current = current._wrapped
            else:
                # Found the actual node
                return type(current)

        # Fallback to inner_node's type if we can't traverse
        return type(self.inner_node)

    def _setup_llm_interception(self) -> None:
        """Set up LLM interception if trace collector is present and node uses LLM."""
        if not self.trace or not hasattr(self.trace, "setup_llm_interception"):
            return

        # Check if this node might use LLM in various ways:
        # 1. Has prompt in params (some nodes)
        # 2. Is an llm-type node (node type contains 'llm')
        # 3. Has model configuration (likely uses LLM)
        node_params = self._get_node_params()

        # Check node type for 'llm' indicator - get the actual node class, not wrapper
        actual_node_class = self._get_actual_node_class()
        node_type = actual_node_class.__name__.lower()
        is_llm_node = "llm" in node_type

        # Check if params suggest LLM usage
        has_prompt_param = node_params and "prompt" in node_params
        has_model_param = node_params and "model" in node_params

        if is_llm_node or has_prompt_param or has_model_param:
            logger.debug(f"Setting up LLM interception for node {self.node_id} (type: {node_type})")
            self.trace.setup_llm_interception(self.node_id)

    def set_params(self, params: dict[str, Any]) -> None:
        """Set parameters on the wrapped node.

        Args:
            params: Parameters to set
        """
        if hasattr(self.inner_node, "set_params"):
            self.inner_node.set_params(params)
        else:
            # Store params if inner node doesn't have set_params
            self.params = params

    def __copy__(self) -> "InstrumentedNodeWrapper":
        """Support shallow copy for Flow operations."""
        import copy

        new_wrapper = type(self)(copy.copy(self.inner_node), self.node_id, self.metrics, self.trace)
        if hasattr(self, "successors"):
            new_wrapper.successors = self.successors.copy()
        if hasattr(self, "params"):
            new_wrapper.params = self.params.copy() if isinstance(self.params, dict) else self.params
        return new_wrapper

    def __deepcopy__(self, memo: dict[int, Any]) -> "InstrumentedNodeWrapper":
        """Support deep copy for Flow operations."""
        import copy

        new_wrapper = type(self)(
            copy.deepcopy(self.inner_node, memo),
            self.node_id,
            self.metrics,  # Don't deep copy collectors
            self.trace,  # Don't deep copy collectors
        )
        if hasattr(self, "successors"):
            new_wrapper.successors = copy.deepcopy(self.successors, memo)
        if hasattr(self, "params"):
            new_wrapper.params = copy.deepcopy(self.params, memo)
        return new_wrapper
