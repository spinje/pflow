"""
Debug infrastructure for planner execution visibility.

This module provides debugging capabilities for the Natural Language Planner
without modifying existing node implementations. It wraps nodes to capture
execution data, display progress, and save trace files for debugging.
"""

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, ClassVar, Optional

import click


@dataclass
class DebugContext:
    """Encapsulates all debugging infrastructure for the planner.

    This context object is created by the CLI and passed to the flow,
    providing a clean separation of concerns and dependency injection.
    """

    trace_collector: "TraceCollector"
    progress: "PlannerProgress"
    metrics_collector: Optional[Any] = None  # Optional MetricsCollector for cost tracking


class TimedResponse:
    """Wrapper for LLM Response objects that captures timing when evaluated."""

    def __init__(
        self, wrapped_response: Any, trace: "TraceCollector", current_node: str, shared: Optional[dict[str, Any]] = None
    ):
        self._response = wrapped_response
        self._json_cache: Optional[Any] = None
        self._text_cache: Optional[str] = None
        self._trace = trace
        self._current_node = current_node
        self._shared = shared

    def json(self) -> Any:
        if self._json_cache is None:
            # Time the actual API call
            start = time.perf_counter()
            self._json_cache = self._response.json()
            duration = time.perf_counter() - start
            # Now that response is consumed, capture usage data
            self._capture_usage_and_record(duration, self._json_cache)
        return self._json_cache

    def text(self) -> str:
        if self._text_cache is None:
            # Time the actual API call
            start = time.perf_counter()
            self._text_cache = self._response.text()
            duration = time.perf_counter() - start
            # Now that response is consumed, capture usage data
            # For text responses, we need to try to get JSON for metadata
            try:
                response_data = self._response.json() if hasattr(self._response, "json") else None
            except (json.JSONDecodeError, AttributeError, ValueError):
                # JSONDecodeError: Response isn't valid JSON
                # AttributeError: Response doesn't have expected attributes
                # ValueError: Other JSON parsing issues
                response_data = None
            self._capture_usage_and_record(duration, response_data or self._text_cache)
        return self._text_cache

    def _capture_usage_and_record(self, duration: float, response_data: Any) -> None:
        """Capture usage data after response consumption and record it."""
        # Now that the response has been consumed, usage() should have data
        usage_data = None
        model_name = "unknown"

        # Get usage data - it's now available after consumption
        if hasattr(self._response, "usage"):
            usage_obj = self._response.usage() if callable(self._response.usage) else self._response.usage
            if usage_obj:
                # Handle both dict and object forms
                if isinstance(usage_obj, dict):
                    usage_data = usage_obj
                elif hasattr(usage_obj, "input") and hasattr(usage_obj, "output"):
                    usage_data = {
                        "input_tokens": getattr(usage_obj, "input", 0),
                        "output_tokens": getattr(usage_obj, "output", 0),
                        "total_tokens": getattr(usage_obj, "input", 0) + getattr(usage_obj, "output", 0),
                    }
                    # Check for cache-related fields
                    if hasattr(usage_obj, "details") and usage_obj.details:
                        details = usage_obj.details
                        if hasattr(details, "cache_creation_input_tokens"):
                            usage_data["cache_creation_input_tokens"] = details.cache_creation_input_tokens
                        if hasattr(details, "cache_read_input_tokens"):
                            usage_data["cache_read_input_tokens"] = details.cache_read_input_tokens

        # Get model name from current_llm_call (it was stored when request was made)
        # The model is already in current_llm_call from record_llm_request
        model_name = "unknown"
        if hasattr(self._trace, "current_llm_call") and self._trace.current_llm_call:
            # First try to get from prompt_kwargs where our interceptor put it
            model_name = self._trace.current_llm_call.get("prompt_kwargs", {}).get("model")
            # Fallback to top-level model field if not in prompt_kwargs
            if not model_name:
                model_name = self._trace.current_llm_call.get("model", "unknown")

        # Pass the captured data to record_llm_response
        self._trace.record_llm_response_with_data(
            self._current_node, response_data, duration, usage_data, model_name, self._shared
        )

    def __getattr__(self, name: str) -> Any:
        # Forward other attributes to the wrapped response
        return getattr(self._response, name)


class DebugWrapper:
    """Wraps PocketFlow nodes to capture debugging data.

    This wrapper preserves all node functionality while adding debugging
    capabilities. It delegates all unknown attributes to the wrapped node
    and handles special methods to prevent recursion issues.
    """

    def __init__(self, node: Any, debug_context: DebugContext) -> None:
        self._wrapped = node
        self.debug_context = debug_context

        # Defensive check for debug_context type
        if not hasattr(debug_context, "trace_collector") or not hasattr(debug_context, "progress"):
            raise TypeError(f"Expected DebugContext, got {type(debug_context)}: {debug_context}")

        self.trace = debug_context.trace_collector
        self.progress = debug_context.progress
        self.metrics = debug_context.metrics_collector  # Optional metrics collector
        # CRITICAL: Copy Flow-required attributes
        self.successors = node.successors
        self.params = getattr(node, "params", {})

    def __call__(self, shared: dict[str, Any]) -> Any:
        """CRITICAL: Flow calls this to execute the node."""
        return self._run(shared)

    def __getattr__(self, name: str) -> Any:
        """CRITICAL: Delegate ALL unknown attributes to wrapped node."""
        # Handle special methods to prevent recursion
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return getattr(self._wrapped, name)

    def __copy__(self) -> "DebugWrapper":
        """CRITICAL: Flow uses copy.copy() on nodes (lines 99, 107 of pocketflow/__init__.py)
        This MUST be implemented or Flow will break when it copies nodes!
        """
        import copy

        # Create new wrapper with copied inner node, but SAME debug context (shared)
        return DebugWrapper(copy.copy(self._wrapped), self.debug_context)

    def __deepcopy__(self, memo: dict[int, Any]) -> "DebugWrapper":
        """Prevent recursion when deep copying."""
        import copy

        return DebugWrapper(copy.deepcopy(self._wrapped, memo), self.debug_context)

    def __sub__(self, action: str) -> Any:
        """Support the - operator for flow connections."""
        # Import here to avoid circular dependency
        from pocketflow import _ConditionalTransition

        # Create a conditional transition with the wrapper as source
        return _ConditionalTransition(self, action)

    def __rshift__(self, other: Any) -> Any:
        """Support the >> operator for flow connections."""
        # Add other as default successor
        self.successors["default"] = other
        # Return other to allow chaining
        return other

    def set_params(self, params: dict[str, Any]) -> None:
        """Flow calls this to set parameters."""
        self.params = params
        if hasattr(self._wrapped, "set_params"):
            self._wrapped.set_params(params)

    def _run(self, shared: dict[str, Any]) -> Any:
        """Main execution - Flow calls this."""
        node_name = getattr(self._wrapped, "name", self._wrapped.__class__.__name__)
        self.progress.on_node_start(node_name)
        start_time = time.perf_counter()  # Use perf_counter for consistency

        # Store trace collector in shared for access
        shared["_trace_collector"] = self.trace

        # Mark this as planner execution for metrics
        shared["__is_planner__"] = True

        # Initialize LLM calls list if metrics are being collected
        if self.metrics and "__llm_calls__" not in shared:
            shared["__llm_calls__"] = []

        # Store shared reference for LLM interception
        self._current_shared = shared

        try:
            # Call our own prep/exec/post to intercept LLM calls
            prep_res = self.prep(shared)
            exec_res = self.exec(prep_res)
            result = self.post(shared, prep_res, exec_res)

            duration_seconds = time.perf_counter() - start_time
            duration_ms = duration_seconds * 1000

            # Record metrics if collector present
            if self.metrics:
                self.metrics.record_node_execution(node_name, duration_ms, is_planner=True)

            # Show completion with retry indicator if retries occurred
            if hasattr(self, "had_retries") and self.had_retries:
                click.echo(f" (retried) ✓ {duration_seconds:.1f}s", err=True)
            else:
                self.progress.on_node_complete(node_name, duration_seconds)
            self.trace.record_node_execution(node_name, duration_seconds, "success")
            return result
        except Exception as e:
            import traceback

            duration_seconds = time.perf_counter() - start_time
            duration_ms = duration_seconds * 1000

            # Record metrics even on failure
            if self.metrics:
                self.metrics.record_node_execution(node_name, duration_ms, is_planner=True)

            # Include full traceback for debugging
            error_msg = f"{e!s}\n{traceback.format_exc()}"
            self.trace.record_node_execution(node_name, duration_seconds, "failed", error_msg)
            raise

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Wrap prep phase."""
        # Initialize metrics tracking on first method call
        # Mark this as planner execution for metrics
        shared["__is_planner__"] = True

        # Initialize LLM calls list if metrics are being collected
        if self.metrics and "__llm_calls__" not in shared:
            shared["__llm_calls__"] = []

        # Store shared reference for LLM interception
        self._current_shared = shared

        # Store trace collector in shared for access
        shared["_trace_collector"] = self.trace

        start = time.time()
        result = self._wrapped.prep(shared)
        self.trace.record_phase(self._wrapped.__class__.__name__, "prep", time.time() - start)
        return result  # type: ignore[no-any-return]

    def _create_prompt_interceptor(self, original_prompt: Any, trace: "TraceCollector", model: Any = None) -> Any:
        """Create an interceptor for the LLM prompt method."""
        # Capture wrapper reference for closure
        wrapper = self

        def intercept_prompt(prompt_text: str, **prompt_kwargs: Any) -> Any:
            # Use current_node from trace collector
            current_node = getattr(trace, "current_node", "Unknown")

            # Extract model info before modifying kwargs
            model_id = None
            if model is not None:
                if hasattr(model, "model_id"):
                    model_id = model.model_id
                elif hasattr(model, "model_name"):
                    model_id = model.model_name
                elif hasattr(model, "name"):
                    model_id = model.name
                else:
                    # Model exists but has no identifying attribute
                    model_id = str(type(model).__name__)

            # Add model to kwargs for downstream use
            if model_id:
                prompt_kwargs["model"] = model_id

            # Record the prompt with model info
            trace.record_llm_request(current_node, prompt_text, prompt_kwargs)

            try:
                # Get the response object (lazy - no API call yet)
                response = original_prompt(prompt_text, **prompt_kwargs)
                # Get shared from trace (not wrapper, since wrapper is from first node only)
                shared = getattr(trace, "_current_shared", None)
                # Return the wrapped response
                return TimedResponse(response, trace, current_node, shared)
            except Exception as e:
                trace.record_llm_error(current_node, str(e))
                raise

        return intercept_prompt

    def _create_model_interceptor(self, original_get_model: Any, trace: "TraceCollector") -> Any:
        """Create an interceptor for llm.get_model."""

        def intercept_get_model(*args: Any, **kwargs: Any) -> Any:
            model = original_get_model(*args, **kwargs)
            original_prompt = model.prompt
            # Pass model to interceptor so it can get model_id
            model.prompt = self._create_prompt_interceptor(original_prompt, trace, model)
            return model

        return intercept_get_model

    def _setup_llm_interception(self, node_name: str, shared: Optional[dict[str, Any]] = None) -> None:
        """Set up LLM interception if not already installed."""
        import llm

        # Store current node name in trace collector for LLM interception
        self.trace.current_node = node_name

        # Store shared reference for metrics collection
        if shared:
            self.trace._current_shared = shared

        # Install interceptor only once (first node that uses LLM)
        if not self.trace._llm_interceptor_installed:
            original_get_model = llm.get_model
            trace = self.trace  # Capture trace in closure

            llm.get_model = self._create_model_interceptor(original_get_model, trace)
            self.trace._llm_interceptor_installed = True
            self.trace._original_get_model = original_get_model

    def exec(self, prep_res: dict[str, Any]) -> Any:
        """Wrap exec phase with LLM interception."""
        start = time.time()
        node_name = self._wrapped.__class__.__name__

        # Set up LLM interception if this node uses LLM
        if "model_name" in prep_res:  # Node uses LLM
            self._setup_llm_interception(node_name, self._current_shared)

        try:
            # CRITICAL FIX: Call _exec() to use retry mechanism, not exec() directly
            result = self._wrapped._exec(prep_res)

            # Disable retry detection for now - it's buggy and misleading
            # The issue is complex: nodes might be reused, cur_retry tracking is unreliable
            # Better to not show retry indicators than to show incorrect ones
            self.had_retries = False
        finally:
            # Clear current node name
            if hasattr(self.trace, "current_node"):
                delattr(self.trace, "current_node")

        self.trace.record_phase(node_name, "exec", time.time() - start)
        return result

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: Any) -> Any:
        """Wrap post phase."""
        start = time.time()
        result = self._wrapped.post(shared, prep_res, exec_res)
        self.trace.record_phase(self._wrapped.__class__.__name__, "post", time.time() - start, {"action": result})
        return result


class TraceCollector:
    """Collects execution trace data for debugging."""

    def __init__(self, user_input: str) -> None:
        self.execution_id: str = str(uuid.uuid4())
        self.start_time: datetime = datetime.utcnow()
        self.user_input: str = user_input
        self.events: list[dict[str, Any]] = []
        self.llm_calls: list[dict[str, Any]] = []
        self.node_executions: list[dict[str, Any]] = []
        self.final_status: str = "running"
        self.path_taken: Optional[str] = None  # Will be "A" or "B"
        # Dynamic attributes for LLM interception
        self.current_node: Optional[str] = None
        self._llm_interceptor_installed: bool = False
        self._original_get_model: Optional[Callable[..., Any]] = None
        self._current_shared: Optional[dict[str, Any]] = None  # For storing shared reference during LLM interception

    def record_node_execution(self, node: str, duration: float, status: str, error: Optional[str] = None) -> None:
        """Record node execution with timing and status."""
        self.node_executions.append({
            "node": node,
            "duration_ms": int(duration * 1000),
            "status": status,
            "error": error,
        })

        # Detect path based on nodes executed
        if node == "ComponentBrowsingNode":
            self.path_taken = "B"
        elif node == "ParameterMappingNode" and self.path_taken is None:
            self.path_taken = "A"

    def record_phase(self, node: str, phase: str, duration: float, extra: Optional[dict[str, Any]] = None) -> None:
        """Record execution phase details."""
        self.events.append({
            "timestamp": datetime.utcnow().isoformat(),
            "node": node,
            "phase": phase,
            "duration_ms": int(duration * 1000),
            "extra": extra,
        })

    def record_llm_request(self, node: str, prompt: str, kwargs: dict[str, Any]) -> None:
        """Record LLM request before execution."""
        # Store the pending request
        # Model should be in kwargs from our interceptor
        model_name = kwargs.get("model", "unknown")

        self.current_llm_call = {
            "node": node,
            "timestamp": datetime.utcnow().isoformat(),
            "model": model_name,
            "prompt": prompt,
            "prompt_kwargs": {k: v for k, v in kwargs.items() if k != "schema"},
        }

    def record_llm_response_with_data(
        self,
        node: str,
        response_data: Any,
        duration: float,
        usage_data: Optional[dict[str, Any]],
        model_name: str,
        shared: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record LLM response with pre-extracted data."""
        if hasattr(self, "current_llm_call"):
            # Ensure minimum 1ms for any call (even mocked ones)
            self.current_llm_call["duration_ms"] = max(1, int(duration * 1000))
            self.current_llm_call["response"] = response_data
            self.current_llm_call["model"] = model_name

            # Add token counts if available
            if usage_data:
                self.current_llm_call["tokens"] = {
                    "input": usage_data.get("input_tokens", 0),
                    "output": usage_data.get("output_tokens", 0),
                }

                # Also accumulate in shared store for metrics if available
                if shared and "__llm_calls__" in shared:
                    llm_call_metrics = {
                        "model": model_name,
                        "input_tokens": usage_data.get("input_tokens", 0),
                        "output_tokens": usage_data.get("output_tokens", 0),
                        "total_tokens": usage_data.get(
                            "total_tokens", usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0)
                        ),
                        "node_id": node,
                        "duration_ms": self.current_llm_call["duration_ms"],
                        "is_planner": True,
                    }
                    # Handle cache-related fields if present
                    if "cache_creation_input_tokens" in usage_data:
                        llm_call_metrics["cache_creation_input_tokens"] = usage_data["cache_creation_input_tokens"]
                    if "cache_read_input_tokens" in usage_data:
                        llm_call_metrics["cache_read_input_tokens"] = usage_data["cache_read_input_tokens"]

                    shared["__llm_calls__"].append(llm_call_metrics)

            self.llm_calls.append(self.current_llm_call)
            delattr(self, "current_llm_call")

    def _extract_response_data(self, response: Any) -> Any:
        """Extract response data from LLM response object."""
        if hasattr(response, "json"):
            try:
                return response.json()
            except Exception:
                return str(response)
        return str(response)

    def _extract_usage_data(self, response: Any, current_call: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Extract usage data from LLM response or call metadata."""
        # First try the standard usage attribute/method
        if hasattr(response, "usage"):
            # Check if usage is a method or a property
            usage_result = response.usage() if callable(response.usage) else response.usage
            # Ensure we return dict[str, Any] or None
            if isinstance(usage_result, dict):
                return usage_result
            return None

        # For Claude models, check if usage is in the response JSON
        if "response" in current_call:
            response_json = current_call["response"]
            if isinstance(response_json, dict) and "usage" in response_json:
                usage_data = response_json["usage"]
                # Ensure we return dict[str, Any] or None
                if isinstance(usage_data, dict):
                    return usage_data

        return None

    def _update_metrics_in_shared(
        self, shared: Optional[dict[str, Any]], usage_data: dict[str, Any], node: str, duration_ms: int, model: str
    ) -> None:
        """Update metrics in the shared store if available."""
        if not shared or "__llm_calls__" not in shared:
            return

        llm_call_metrics = {
            "model": model,
            "input_tokens": usage_data.get("input_tokens", 0),
            "output_tokens": usage_data.get("output_tokens", 0),
            "total_tokens": usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
            "node_id": node,
            "duration_ms": duration_ms,
            "is_planner": True,
        }

        # Handle Anthropic-specific fields
        if hasattr(usage_data, "cache_creation_input_tokens"):
            llm_call_metrics["cache_creation_input_tokens"] = usage_data.cache_creation_input_tokens
        if hasattr(usage_data, "cache_read_input_tokens"):
            llm_call_metrics["cache_read_input_tokens"] = usage_data.cache_read_input_tokens

        shared["__llm_calls__"].append(llm_call_metrics)

    def record_llm_response(
        self, node: str, response: Any, duration: float, shared: Optional[dict[str, Any]] = None
    ) -> None:
        """Record LLM response after execution (legacy method, kept for compatibility)."""
        if not hasattr(self, "current_llm_call"):
            return

        # Ensure minimum 1ms for any call (even mocked ones)
        self.current_llm_call["duration_ms"] = max(1, int(duration * 1000))

        # Extract response data
        self.current_llm_call["response"] = self._extract_response_data(response)

        # Try to get token counts if available
        usage_data = self._extract_usage_data(response, self.current_llm_call)

        if usage_data and isinstance(usage_data, dict):
            self.current_llm_call["tokens"] = {
                "input": usage_data.get("input_tokens", 0),
                "output": usage_data.get("output_tokens", 0),
            }

            # Also accumulate in shared store for metrics if available
            self._update_metrics_in_shared(
                shared,
                usage_data,
                node,
                self.current_llm_call["duration_ms"],
                self.current_llm_call.get("model", "unknown"),
            )

        self.llm_calls.append(self.current_llm_call)
        delattr(self, "current_llm_call")

    def record_llm_error(self, node: str, error: str) -> None:
        """Record LLM error if call fails."""
        if hasattr(self, "current_llm_call"):
            self.current_llm_call["error"] = error
            self.llm_calls.append(self.current_llm_call)
            delattr(self, "current_llm_call")

    def set_final_status(
        self, status: str, shared_store: Optional[dict[str, Any]] = None, error: Optional[dict[str, Any]] = None
    ) -> None:
        """Set final execution status and save important data."""
        self.final_status = status
        if shared_store:
            # Only save important keys, not internal ones
            # But keep __llm_calls__ and __is_planner__ as they're needed for metrics
            self.final_shared_store = {
                k: v
                for k, v in shared_store.items()
                if (not k.startswith("_") or k in ["__llm_calls__", "__is_planner__"]) and k not in ["workflow_manager"]
            }
        if error:
            self.error_info = error

    def save_to_file(self) -> str:
        """Save trace to JSON file in ~/.pflow/debug/."""
        # Create directory
        trace_dir = Path.home() / ".pflow" / "debug"
        trace_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"planner-trace-{timestamp}.json"
        filepath = trace_dir / filename

        # Prepare trace data
        trace_data = {
            "execution_id": self.execution_id,
            "timestamp": self.start_time.isoformat(),
            "user_input": self.user_input,
            "status": self.final_status,
            "duration_ms": int((datetime.utcnow() - self.start_time).total_seconds() * 1000),
            "path_taken": self.path_taken,
            "llm_calls": self.llm_calls,
            "node_execution": self.node_executions,
            "events": self.events,
        }

        if hasattr(self, "final_shared_store"):
            trace_data["final_shared_store"] = self.final_shared_store
        if hasattr(self, "error_info"):
            trace_data["error"] = self.error_info

        # Write file
        with open(filepath, "w") as f:
            json.dump(trace_data, f, indent=2, default=str)

        return str(filepath)

    def cleanup_llm_interception(self) -> None:
        """Restore original LLM get_model function if it was intercepted."""
        # The trace IS the TraceCollector, check it directly
        if hasattr(self, "_original_get_model"):
            import llm

            llm.get_model = self._original_get_model  # type: ignore[assignment]
            delattr(self, "_original_get_model")
            if hasattr(self, "_llm_interceptor_installed"):
                delattr(self, "_llm_interceptor_installed")


class PlannerProgress:
    """Displays progress indicators in terminal."""

    # Node name to user-friendly display names
    NODE_ICONS: ClassVar[dict[str, str]] = {
        "WorkflowDiscoveryNode": "workflow-discovery",
        "ComponentBrowsingNode": "component-browsing",
        "ParameterDiscoveryNode": "parameter-discovery",
        "ParameterMappingNode": "parameter-mapping",
        "ParameterPreparationNode": "parameter-preparation",
        "WorkflowGeneratorNode": "generator",
        "ValidatorNode": "✅ Validation",
        "MetadataGenerationNode": "💾 Metadata",
        "ResultPreparationNode": "result-preparation",
    }

    def __init__(self, is_interactive: bool = True):
        """Initialize progress display.

        Args:
            is_interactive: Whether to display progress (True for terminal, False for pipes)
        """
        self.is_interactive = is_interactive

    def on_node_start(self, node_name: str) -> None:
        """Display node start with emoji and name."""
        if not self.is_interactive:
            return
        display_name = self.NODE_ICONS.get(node_name, node_name)
        click.echo(f"{display_name}...", err=True, nl=False)

    def on_node_complete(self, node_name: str, duration: float) -> None:
        """Display node completion with duration."""
        if not self.is_interactive:
            return
        click.echo(f" ✓ {duration:.1f}s", err=True)
