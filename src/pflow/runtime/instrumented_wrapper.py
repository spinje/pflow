"""Unified wrapper for metrics collection and optional tracing."""

import contextlib
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

        # Initialize LLM calls accumulation list if needed
        if "__llm_calls__" not in shared:
            shared["__llm_calls__"] = []

        # Track if this is a planner node (for cost attribution)
        is_planner = shared.get("__is_planner__", False)

        # Set up LLM interception if needed
        self._setup_llm_interception()

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
            if callable(callback):
                # Never let callback errors break execution
                with contextlib.suppress(Exception):
                    callback(self.node_id, "node_complete", duration_ms, depth)

            return result

        except Exception as e:
            # Still record metrics and trace on failure
            duration_ms = (time.perf_counter() - start_time) * 1000

            if self.metrics:
                self.metrics.record_node_execution(self.node_id, duration_ms, is_planner=is_planner)

            # Record trace with error
            self._record_trace(duration_ms, shared_before, dict(shared), success=False, error=str(e))

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
