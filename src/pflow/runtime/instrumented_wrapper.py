"""Unified wrapper for metrics collection and optional tracing."""

import contextlib
import hashlib
import json
import logging
import time
from typing import Any, Optional, cast

logger = logging.getLogger(__name__)


class InstrumentedNodeWrapper:
    """Wrapper that instruments nodes for metrics and optional tracing.

    This wrapper serves both lightweight metrics collection (always with JSON output)
    and detailed tracing (opt-in with --trace flags). It must be the outermost wrapper
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

    def _capture_llm_usage(
        self, shared: dict[str, Any], shared_before: dict[str, Any] | None, duration_ms: float, is_planner: bool
    ) -> None:
        """Capture and record LLM usage data with defensive validation.

        Args:
            shared: Current shared store
            shared_before: Shared store state before execution
            duration_ms: Execution duration in milliseconds
            is_planner: Whether this is a planner node
        """
        # Validate shared has __llm_calls__ list
        if "__llm_calls__" not in shared:
            logger.warning(f"Node {self.node_id}: __llm_calls__ list not initialized, creating it")
            shared["__llm_calls__"] = []

        if not isinstance(shared["__llm_calls__"], list):
            logger.error(f"Node {self.node_id}: __llm_calls__ is not a list: {type(shared['__llm_calls__']).__name__}")
            return

        # Check both root level (for non-namespaced) and namespaced location
        llm_usage = None

        # First check root level (for nodes without namespacing)
        if "llm_usage" in shared:
            llm_usage = shared["llm_usage"]
        # Then check namespaced location (when namespacing is enabled)
        elif self.node_id in shared and isinstance(shared[self.node_id], dict):
            llm_usage = shared[self.node_id].get("llm_usage")

        if not llm_usage:
            return

        # Validate llm_usage structure before using
        if not isinstance(llm_usage, dict):
            logger.warning(f"Node {self.node_id}: llm_usage is not a dict: {type(llm_usage).__name__}")
            return

        # Create a copy and add metadata - defensive copy in case it's modified elsewhere
        try:
            llm_call_data = llm_usage.copy()
        except Exception:
            logger.exception(f"Node {self.node_id}: Failed to copy llm_usage")
            return

        llm_call_data["node_id"] = self.node_id
        llm_call_data["duration_ms"] = duration_ms
        llm_call_data["is_planner"] = is_planner

        # Intelligently capture the prompt
        llm_prompt = self._find_llm_prompt(shared_before)

        # Add prompt to LLM call data if found
        if llm_prompt:
            llm_call_data["prompt"] = llm_prompt

        # Append to accumulator list with error handling
        try:
            shared["__llm_calls__"].append(llm_call_data)
            logger.debug(f"Node {self.node_id}: Captured LLM usage with {llm_call_data.get('total_tokens', 0)} tokens")
        except Exception:
            logger.exception(f"Node {self.node_id}: Failed to append LLM usage data")

    def _find_llm_prompt(self, shared_before: dict[str, Any] | None) -> str | None:
        """Find the LLM prompt from various sources.

        Args:
            shared_before: Shared store state before execution

        Returns:
            The LLM prompt if found, None otherwise
        """
        llm_prompt = None

        # 1. Check if prompt was in shared_before (non-namespaced)
        if shared_before and "prompt" in shared_before:
            llm_prompt = shared_before["prompt"]

        # 2. Check if prompt was in namespaced shared_before
        if not llm_prompt and shared_before and self.node_id in shared_before:
            ns_data = shared_before[self.node_id]
            if isinstance(ns_data, dict) and "prompt" in ns_data:
                llm_prompt = ns_data["prompt"]

        # 3. Check node params (most likely for workflow nodes)
        if not llm_prompt:
            node_params = self._get_node_params()
            if node_params and "prompt" in node_params:
                llm_prompt = node_params["prompt"]

        return llm_prompt

    def _handle_api_warning(
        self,
        shared: dict[str, Any],
        warning_msg: str,
        start_time: float,
        shared_before: Optional[dict[str, Any]],
        callback: Optional[Any],
        is_planner: bool,
    ) -> str:
        """Handle API warning detection.

        Args:
            shared: The shared store
            warning_msg: Warning message
            start_time: Start time for duration calculation
            shared_before: Shared state before execution
            callback: Progress callback
            is_planner: Whether this is a planner node

        Returns:
            "error" to stop workflow
        """
        logger.debug(f"API warning detected for {self.node_id}: {warning_msg}")

        # Mark as non-repairable to prevent futile repair attempts
        shared["__non_repairable_error__"] = True

        # Store warning for display
        if "__warnings__" not in shared:
            shared["__warnings__"] = {}
        shared["__warnings__"][self.node_id] = warning_msg

        # Record as completed (to prevent re-execution) but return error to stop workflow
        shared["__execution__"]["completed_nodes"].append(self.node_id)
        shared["__execution__"]["node_actions"][self.node_id] = "error"

        # Calculate duration for metrics
        duration_ms = (time.perf_counter() - start_time) * 1000

        # Record metrics if collector present
        if self.metrics:
            self.metrics.record_node_execution(self.node_id, duration_ms, is_planner=is_planner)

        # Call progress callback with warning
        if callable(callback):
            depth = shared.get("_pflow_depth", 0)
            with contextlib.suppress(Exception):
                callback(self.node_id, "node_warning", warning_msg, depth)

        # Record trace
        self._record_trace(duration_ms, shared_before, dict(shared), success=False)

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
            # Don't cache error results - they should be retryable
            logger.debug(f"Node {self.node_id} returned error, not caching")

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

        # Check if node was modified during repair
        is_modified = self.node_id in shared.get("__modified_nodes__", [])

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
                is_modified=is_modified,
                is_error=(result == "error"),
            )

    def _validate_llm_json_output(self, shared_before: dict[str, Any] | None, shared_after: dict[str, Any]) -> None:
        """Validate LLM JSON output and warn about potential issues.

        Args:
            shared_before: Shared store before node execution
            shared_after: Shared store after node execution
        """
        # Only validate if this looks like an LLM node
        if not shared_before:
            return

        # Check if this node had a prompt (indicating it's likely an LLM node)
        prompt = self._find_llm_prompt(shared_before)
        if not prompt:
            return

        # Check if JSON was likely expected based on prompt content
        prompt_lower = prompt.lower()
        expects_json = "json" in prompt_lower

        if not expects_json:
            return

        # Check if response exists and is a string (not parsed JSON)
        response = shared_after.get("response")

        # Also check namespaced response
        if not response and self.node_id in shared_after:
            ns_data = shared_after[self.node_id]
            if isinstance(ns_data, dict):
                response = ns_data.get("response")

        # If response is a string and JSON was expected, likely parsing failed
        if isinstance(response, str) and expects_json:
            # Check if it looks like it should be JSON
            trimmed = response.strip()
            if not (trimmed.startswith("{") or trimmed.startswith("[")):
                # Get model info if available
                model = "unknown"
                if "llm_usage" in shared_after:
                    usage = shared_after["llm_usage"]
                    if isinstance(usage, dict):
                        model = usage.get("model", "unknown")

                logger.warning(
                    f"Node '{self.node_id}' with model '{model}' may have failed to generate valid JSON. "
                    f"Prompt requested JSON but response appears to be plain text. "
                    f"Response starts with: {response[:100]}... "
                    f"Consider using a stronger model like 'gpt-5', 'claude-4-sonnet' or 'gemini-2.5-pro', and adding clearer JSON instructions."
                )

    def _record_trace(
        self,
        duration_ms: float,
        shared_before: dict[str, Any] | None,
        shared_after: dict[str, Any],
        success: bool,
        error: str | None = None,
    ) -> None:
        """Record execution trace if collector is present.

        Args:
            duration_ms: Execution duration in milliseconds
            shared_before: Shared store state before execution
            shared_after: Shared store state after execution
            success: Whether execution succeeded
            error: Error message if execution failed
        """
        if not self.trace:
            return

        # TODO: Capture template resolutions if they were logged
        template_resolutions: dict[str, Any] = {}

        self.trace.record_node_execution(
            node_id=self.node_id,
            node_type=type(self.inner_node).__name__,
            duration_ms=duration_ms,
            shared_before=shared_before,
            shared_after=shared_after,
            success=success,
            error=error,
            template_resolutions=template_resolutions,
        )

    def _compute_node_config(self) -> dict[str, Any]:
        """Compute the configuration dictionary for the node.

        Returns:
            Dictionary containing node type and parameters
        """
        # Get the actual node (might be wrapped multiple times)
        actual_node = self.inner_node
        while hasattr(actual_node, "_inner_node") or hasattr(actual_node, "inner_node"):
            actual_node = actual_node._inner_node if hasattr(actual_node, "_inner_node") else actual_node.inner_node

        # Build configuration dictionary
        node_config = {"type": actual_node.__class__.__name__, "params": {}}

        # Include parameters if present
        if hasattr(actual_node, "params") and actual_node.params:
            # Sort keys for deterministic hashing
            node_config["params"] = dict(sorted(actual_node.params.items()))

        return node_config

    def _compute_config_hash(self, config: dict[str, Any]) -> str:
        """Compute a hash of the node configuration.

        Args:
            config: Node configuration dictionary

        Returns:
            Hexadecimal hash string
        """
        # Create a serializable version of the config
        serializable_config = self._make_serializable(config)

        # Serialize to JSON with sorted keys for deterministic hashing
        config_json = json.dumps(serializable_config, sort_keys=True)
        # MD5 is used here for fast configuration change detection, not for security.
        # This hash is only used to detect if a node's parameters have changed between
        # workflow runs, so cryptographic security is not required. MD5 is chosen for
        # its speed since this check happens frequently during workflow execution.
        return hashlib.md5(config_json.encode()).hexdigest()  # noqa: S324

    def _make_serializable(self, obj: Any) -> Any:
        """Convert an object to a JSON-serializable representation.

        This handles common non-serializable objects like Registry by converting
        them to a deterministic string representation for hashing purposes.

        Args:
            obj: Object to make serializable

        Returns:
            JSON-serializable version of the object
        """
        if isinstance(obj, dict):
            # Recursively process dictionary, excluding non-serializable internal keys
            result = {}
            for key, value in obj.items():
                # Skip internal registry objects and other non-serializable internals
                if isinstance(key, str) and key.startswith("__") and key.endswith("__"):
                    # For internal keys like __registry__, use type name for hash
                    if value is not None:
                        result[key] = f"<{type(value).__name__}>"
                    else:
                        result[key] = "<None>"
                else:
                    result[key] = self._make_serializable(value)
            return result
        elif isinstance(obj, (list, tuple)):
            # Recursively process sequences
            return [self._make_serializable(item) for item in obj]
        elif isinstance(obj, (str, int, float, bool, type(None))):
            # Primitives are already serializable
            return obj
        else:
            # For any other non-serializable object, use its type and id for deterministic hashing
            # This includes Registry objects and any other complex types
            return f"<{type(obj).__module__}.{type(obj).__name__}>"

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
        # Initialize LLM calls accumulation list if needed
        if "__llm_calls__" not in shared:
            shared["__llm_calls__"] = []

        # Initialize checkpoint structure if not present
        if "__execution__" not in shared:
            shared["__execution__"] = {
                "completed_nodes": [],
                "node_actions": {},
                "node_hashes": {},  # Store configuration hashes
                "failed_node": None,
            }
        else:
            # Ensure node_hashes exists in existing checkpoints (backward compatibility)
            if "node_hashes" not in shared["__execution__"]:
                shared["__execution__"]["node_hashes"] = {}

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
        # Mark this node as modified for display
        if "__modified_nodes__" not in shared:
            shared["__modified_nodes__"] = []
        shared["__modified_nodes__"].append(self.node_id)

        # Clear cache entries
        shared["__execution__"]["completed_nodes"].remove(self.node_id)
        shared["__execution__"]["node_actions"].pop(self.node_id, None)
        shared["__execution__"]["node_hashes"].pop(self.node_id, None)

    def _handle_cached_execution(self, shared: dict[str, Any], cached_action: Any) -> Any:
        """Handle cached node execution.

        Args:
            shared: The shared store for inter-node communication
            cached_action: The cached action result

        Returns:
            The cached action result
        """
        # Call progress callback for cached node (same format as normal execution)
        callback = shared.get("__progress_callback__")
        if callable(callback):
            depth = shared.get("_pflow_depth", 0)
            with contextlib.suppress(Exception):
                callback(self.node_id, "node_start", None, depth)  # Show node name first
                callback(self.node_id, "node_cached", None, depth)  # Complete the line

        logger.debug(f"Node {self.node_id} skipped (already completed), returning cached action: {cached_action}")
        return cached_action

    def _run(self, shared: dict[str, Any]) -> Any:
        """Execute the wrapped node with metrics and optional tracing.

        Args:
            shared: The shared store for inter-node communication

        Returns:
            The result from the inner node execution
        """
        # Capture state before execution (for tracing and prompt capture)
        start_time = time.perf_counter()
        shared_before = dict(shared) if (self.trace or self.metrics) else None

        # Track if this is a planner node (for cost attribution)
        is_planner = shared.get("__is_planner__", False)

        # Set up LLM interception if needed
        self._setup_llm_interception()

        # Initialize execution state
        self._initialize_execution_state(shared)

        # Check cache validity
        is_cached, cached_action = self._check_cache_validity(shared)
        if is_cached:
            return self._handle_cached_execution(shared, cached_action)

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
            warning_msg = self._detect_api_warning(shared)
            if warning_msg:
                return self._handle_api_warning(shared, warning_msg, start_time, shared_before, callback, is_planner)

            # Cache successful results
            self._cache_result_if_successful(shared, result)

            # Calculate duration
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Record metrics if collector present
            if self.metrics:
                self.metrics.record_node_execution(self.node_id, duration_ms, is_planner=is_planner)

            # Capture LLM usage if present
            self._capture_llm_usage(shared, shared_before, duration_ms, is_planner)

            # Validate LLM JSON output if applicable
            self._validate_llm_json_output(shared_before, shared)

            # Record trace if collector present
            self._record_trace(duration_ms, shared_before, dict(shared), success=True)

            # Call progress callback for node complete if present
            self._call_completion_callback(shared, callback, result, duration_ms)

            return result

        except Exception as e:
            # Still record metrics and trace on failure
            duration_ms = (time.perf_counter() - start_time) * 1000

            if self.metrics:
                self.metrics.record_node_execution(self.node_id, duration_ms, is_planner=is_planner)

            # Record trace with error
            self._record_trace(duration_ms, shared_before, dict(shared), success=False, error=str(e))

            # Record failure in checkpoint
            shared["__execution__"]["failed_node"] = self.node_id

            # Re-raise the exception
            raise

    def _setup_llm_interception(self) -> None:
        """Set up LLM interception if trace collector is present and node uses LLM."""
        if not self.trace or not hasattr(self.trace, "setup_llm_interception"):
            return

        # Check if this node might use LLM (has prompt in params or is llm type)
        node_params = self._get_node_params()
        if node_params and "prompt" in node_params:
            self.trace.setup_llm_interception(self.node_id)

    def _detect_api_warning(self, shared: dict) -> Optional[str]:
        """
        Detect non-repairable API errors (resource/permission issues).

        Returns None for validation errors to allow repair attempts.

        Strategy:
        1. Check error codes first (most reliable)
        2. Check for validation patterns (let repair handle)
        3. Check for resource patterns (prevent repair)
        4. Default to repairable (loop detection is safety net)
        """
        # Get node output
        if self.node_id not in shared:
            logger.debug(f"Node {self.node_id} not in shared store for API warning check")
            return None

        output = shared.get(self.node_id)
        logger.debug(
            f"Checking {self.node_id} output for API warning. Type: {type(output).__name__}, Keys: {list(output.keys()) if isinstance(output, dict) else 'N/A'}"
        )

        # Handle MCP nested responses
        output = self._unwrap_mcp_response(output)
        if not output:
            return None

        # Extract error information
        error_code = self._extract_error_code(output)
        error_msg = self._extract_error_message(output)

        if not error_msg:
            return None  # No error detected

        # PRIORITY 1: Check error codes (most reliable signal)
        if error_code:
            error_category = self._categorize_by_error_code(error_code)

            if error_category == "validation":
                # Validation error - let repair handle it
                logger.debug(f"Validation error detected (repairable): {error_code} - {error_msg}")
                return None

            elif error_category == "resource":
                # Resource error - prevent repair
                logger.info(f"Resource error detected (non-repairable): {error_code} - {error_msg}")
                return f"API error ({error_code}): {error_msg}"

            # Unknown error code - continue to message analysis

        # PRIORITY 2: Check if it's a validation error (repairable)
        if self._is_validation_error(error_msg):
            logger.debug(f"Validation error detected (repairable): {error_msg}")
            return None  # Let repair handle it

        # PRIORITY 3: Check if it's a resource error (not repairable)
        if self._is_resource_error(error_msg):
            logger.info(f"Resource error detected (non-repairable): {error_msg}")
            return f"API error: {error_msg}"

        # DEFAULT: When in doubt, let repair try
        # Loop detection will prevent infinite attempts
        logger.debug(f"Unknown error type, allowing repair attempt: {error_msg}")
        return None

    def _unwrap_mcp_response(self, output: Any) -> Optional[dict]:
        """Unwrap MCP nested responses to get actual API response."""
        if not isinstance(output, dict):
            return None

        # Try to unwrap MCP JSON string result
        parsed = self._parse_mcp_json_result(output)
        if parsed is not None:
            return parsed

        # Handle MCP dict with nested data
        if output.get("successful") is True and "data" in output:
            data = output["data"]
            # Ensure data is a dict before returning
            if isinstance(data, dict):
                return data
            return None

        # Handle HTTP node with response field
        if "response" in output and "status_code" in output:
            status_code = output.get("status_code", 200)
            # Only check 2xx responses for API errors
            if 200 <= status_code < 300:
                return output.get("response")
            # For 4xx/5xx, HTTP node already handles it
            return None

        return output

    def _parse_mcp_json_result(self, output: dict) -> Optional[dict]:
        """Parse MCP JSON result field if present."""
        if "result" not in output or not isinstance(output["result"], str):
            return None

        try:
            import json

            parsed = json.loads(output["result"])
            if isinstance(parsed, dict):
                # Check for nested data in successful MCP response
                if parsed.get("successful") and "data" in parsed:
                    data = parsed["data"]
                    # Ensure data is a dict before returning
                    if isinstance(data, dict):
                        return data
                    return None
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

        return None

    def _extract_error_code(self, output: dict) -> Optional[str]:
        """Extract error code from various API response formats."""
        # Try different common locations for error codes
        candidates = [
            output.get("error_code"),
            output.get("errorCode"),
            output.get("code"),
            output.get("error", {}).get("code") if isinstance(output.get("error"), dict) else None,
            output.get("statusCode"),
            output.get("status_code"),
        ]

        for code in candidates:
            if code:
                return str(code)
        return None

    def _check_boolean_error_flags(self, output: dict) -> Optional[str]:
        """Check boolean error flags in API response.

        Args:
            output: API response dictionary

        Returns:
            Error message if found, None otherwise
        """
        # Check various boolean error indicators
        if output.get("ok") is False:
            return output.get("error") or "API request failed"

        if output.get("success") is False:
            return output.get("error") or output.get("message") or "API request failed"

        if output.get("successful") is False or output.get("successfull") is False:  # MCP typo
            return output.get("error") or output.get("message") or "API request failed"

        if output.get("succeeded") is False:
            return output.get("error") or output.get("message") or "API request failed"

        if output.get("isError") is True:
            error_info = output.get("error", {})
            if isinstance(error_info, dict):
                return error_info.get("message") or "API request failed"
            return str(error_info) if error_info else "API request failed"

        return None

    def _check_status_field(self, output: dict) -> Optional[str]:
        """Check status field for error indicators.

        Args:
            output: API response dictionary

        Returns:
            Error message if found, None otherwise
        """
        status = str(output.get("status", "")).lower()
        if status in ["error", "failed", "failure"]:
            return output.get("message") or output.get("error") or "API request failed"
        return None

    def _check_graphql_errors(self, output: dict) -> Optional[str]:
        """Check for GraphQL errors in API response.

        Args:
            output: API response dictionary

        Returns:
            Error message if found, None otherwise
        """
        if "errors" in output and output.get("errors"):
            errors = output["errors"]
            if isinstance(errors, list) and len(errors) > 0:
                first_error = errors[0]
                if isinstance(first_error, dict):
                    message = first_error.get("message", "GraphQL error")
                    # Ensure message is a string
                    return str(message)
                else:
                    return str(first_error)
        return None

    def _extract_error_message(self, output: dict) -> Optional[str]:
        """Extract error message from API response.

        Args:
            output: API response dictionary

        Returns:
            Error message if found, None otherwise
        """
        # Check boolean error flags
        error_msg = self._check_boolean_error_flags(output)
        if error_msg:
            return error_msg

        # Check status field
        error_msg = self._check_status_field(output)
        if error_msg:
            return error_msg

        # Check for GraphQL errors
        error_msg = self._check_graphql_errors(output)
        if error_msg:
            return error_msg

        # Check if there's an error field with content
        if output.get("error"):
            return output.get("error")

        return None

    def _categorize_by_error_code(self, code: str) -> str:
        """Categorize error by error code."""
        code_upper = str(code).upper()

        # Validation error codes (REPAIRABLE)
        VALIDATION_CODES = [
            "VALIDATION_ERROR",
            "INVALID_PARAMETER",
            "INVALID_REQUEST",
            "BAD_REQUEST",
            "MALFORMED",
            "TYPE_ERROR",
            "FORMAT_ERROR",
            "MISSING_PARAMETER",
            "MISSING_FIELD",
            "INVALID_FORMAT",
            "SCHEMA_ERROR",
            "INVALID_INPUT",
            "PARAMETER_ERROR",
            "400",  # Bad Request usually means fixable
        ]

        # Resource error codes (NOT REPAIRABLE)
        RESOURCE_CODES = [
            "NOT_FOUND",
            "RESOURCE_NOT_FOUND",
            "CHANNEL_NOT_FOUND",
            "USER_NOT_FOUND",
            "FILE_NOT_FOUND",
            "ITEM_NOT_FOUND",
            "PERMISSION_DENIED",
            "UNAUTHORIZED",
            "FORBIDDEN",
            "RATE_LIMITED",
            "RATE_LIMIT",
            "QUOTA_EXCEEDED",
            "401",  # Unauthorized
            "403",  # Forbidden
            "404",  # Not Found
            "429",  # Rate Limited
        ]

        for vc in VALIDATION_CODES:
            if vc in code_upper:
                return "validation"

        for rc in RESOURCE_CODES:
            if rc in code_upper:
                return "resource"

        return "unknown"

    def _is_validation_error(self, error_msg: str) -> bool:
        """Check if error message indicates a validation/parameter error."""
        if not error_msg:
            return False

        msg_lower = error_msg.lower()

        # Validation error indicators
        VALIDATION_PATTERNS = [
            # Format/type errors
            "should be a",
            "must be a",
            "expected a",
            "expecting",
            "invalid format",
            "wrong format",
            "incorrect format",
            "type mismatch",
            "wrong type",
            "invalid type",
            # Validation errors
            "validation error",
            "validation failed",
            "invalid input",
            "invalid request",
            "invalid parameter",
            "invalid value",
            "invalid data",
            "malformed",
            "badly formed",
            # Missing/required errors
            "missing required",
            "required field",
            "required parameter",
            "must provide",
            "must include",
            "must specify",
            # Structure errors
            "should be valid",
            "must be valid",
            "not a valid",
            "does not match",
            "does not conform",
            "schema error",
            # Specific format errors
            "invalid date",
            "invalid email",
            "invalid url",
            "invalid json",
            "parse error",
            "syntax error",
            # Type-specific errors
            "input should be",
            "parameter should be",
            "value should be",
        ]

        return any(pattern in msg_lower for pattern in VALIDATION_PATTERNS)

    def _is_resource_error(self, error_msg: str) -> bool:
        """Check if error message indicates a resource/permission error."""
        if not error_msg:
            return False

        msg_lower = error_msg.lower()

        # Resource error indicators
        RESOURCE_PATTERNS = [
            # Not found errors
            "not found",
            "not_found",
            "does not exist",
            "doesn't exist",
            "no such",
            "cannot find",
            "could not find",
            "unable to find",
            "404",
            "missing",
            "unavailable",
            # Permission errors
            "permission denied",
            "access denied",
            "unauthorized",
            "forbidden",
            "not authorized",
            "no access",
            "restricted",
            "403",
            "401",
            # Rate limiting
            "rate limit",
            "quota exceeded",
            "too many requests",
            "throttled",
            "429",
            # Authentication
            "authentication failed",
            "invalid token",
            "expired token",
            "invalid api key",
            "bad credentials",
        ]

        # Only return True if we're confident it's a resource error
        # AND it doesn't also look like a validation error
        is_resource = any(pattern in msg_lower for pattern in RESOURCE_PATTERNS)
        is_validation = self._is_validation_error(error_msg)

        # If it looks like both, prefer validation (repairable)
        return is_resource and not is_validation

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
