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
from typing import ClassVar, Optional

import click


@dataclass
class DebugContext:
    """Encapsulates all debugging infrastructure for the planner.

    This context object is created by the CLI and passed to the flow,
    providing a clean separation of concerns and dependency injection.
    """

    trace_collector: "TraceCollector"
    progress: "PlannerProgress"


class DebugWrapper:
    """Wraps PocketFlow nodes to capture debugging data.

    This wrapper preserves all node functionality while adding debugging
    capabilities. It delegates all unknown attributes to the wrapped node
    and handles special methods to prevent recursion issues.
    """

    def __init__(self, node, debug_context: DebugContext):
        self._wrapped = node
        self.debug_context = debug_context

        # Defensive check for debug_context type
        if not hasattr(debug_context, "trace_collector") or not hasattr(debug_context, "progress"):
            raise TypeError(f"Expected DebugContext, got {type(debug_context)}: {debug_context}")

        self.trace = debug_context.trace_collector
        self.progress = debug_context.progress
        # CRITICAL: Copy Flow-required attributes
        self.successors = node.successors
        self.params = getattr(node, "params", {})

    def __getattr__(self, name):
        """CRITICAL: Delegate ALL unknown attributes to wrapped node."""
        # Handle special methods to prevent recursion
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return getattr(self._wrapped, name)

    def __copy__(self):
        """CRITICAL: Flow uses copy.copy() on nodes (lines 99, 107 of pocketflow/__init__.py)
        This MUST be implemented or Flow will break when it copies nodes!
        """
        import copy

        # Create new wrapper with copied inner node, but SAME debug context (shared)
        return DebugWrapper(copy.copy(self._wrapped), self.debug_context)

    def __deepcopy__(self, memo):
        """Prevent recursion when deep copying."""
        import copy

        return DebugWrapper(copy.deepcopy(self._wrapped, memo), self.debug_context)

    def __sub__(self, action):
        """Support the - operator for flow connections."""
        # Import here to avoid circular dependency
        from pocketflow import _ConditionalTransition

        # Create a conditional transition with the wrapper as source
        return _ConditionalTransition(self, action)

    def __rshift__(self, other):
        """Support the >> operator for flow connections."""
        # Add other as default successor
        self.successors["default"] = other
        # Return other to allow chaining
        return other

    def set_params(self, params):
        """Flow calls this to set parameters."""
        self.params = params
        if hasattr(self._wrapped, "set_params"):
            self._wrapped.set_params(params)

    def _run(self, shared):
        """Main execution - Flow calls this."""
        node_name = getattr(self._wrapped, "name", self._wrapped.__class__.__name__)
        self.progress.on_node_start(node_name)
        start_time = time.time()

        # Store trace collector in shared for access
        shared["_trace_collector"] = self.trace

        try:
            # Call our own prep/exec/post to intercept LLM calls
            prep_res = self.prep(shared)
            exec_res = self.exec(prep_res)
            result = self.post(shared, prep_res, exec_res)

            duration = time.time() - start_time
            self.progress.on_node_complete(node_name, duration)
            self.trace.record_node_execution(node_name, duration, "success")
            return result
        except Exception as e:
            import traceback

            duration = time.time() - start_time
            # Include full traceback for debugging
            error_msg = f"{e!s}\n{traceback.format_exc()}"
            self.trace.record_node_execution(node_name, duration, "failed", error_msg)
            raise

    def prep(self, shared):
        """Wrap prep phase."""
        start = time.time()
        result = self._wrapped.prep(shared)
        self.trace.record_phase(self._wrapped.__class__.__name__, "prep", time.time() - start)
        return result

    def exec(self, prep_res):
        """Wrap exec phase with LLM interception."""
        start = time.time()
        node_name = self._wrapped.__class__.__name__

        # Set up LLM interception if this node uses LLM
        import llm

        original_get_model = None

        if "model_name" in prep_res:  # Node uses LLM
            # Store current node name in trace collector for LLM interception
            self.trace.current_node = node_name

            # Install interceptor only once (first node that uses LLM)
            if not hasattr(self.trace, "_llm_interceptor_installed"):
                original_get_model = llm.get_model
                trace = self.trace  # Capture trace in closure

                def intercept_get_model(*args, **kwargs):
                    model = original_get_model(*args, **kwargs)
                    original_prompt = model.prompt

                    def intercept_prompt(prompt_text, **prompt_kwargs):
                        prompt_start = time.time()
                        # Use current_node from trace collector
                        current_node = getattr(trace, "current_node", "Unknown")

                        # Record the prompt BEFORE calling
                        trace.record_llm_request(current_node, prompt_text, prompt_kwargs)

                        try:
                            response = original_prompt(prompt_text, **prompt_kwargs)
                            # Record the response AFTER calling
                            trace.record_llm_response(current_node, response, time.time() - prompt_start)
                            return response
                        except Exception as e:
                            trace.record_llm_error(current_node, str(e))
                            raise

                    model.prompt = intercept_prompt
                    return model

                llm.get_model = intercept_get_model
                self.trace._llm_interceptor_installed = True
                self.trace._original_get_model = original_get_model

        try:
            result = self._wrapped.exec(prep_res)
        finally:
            # Clear current node name
            if hasattr(self.trace, "current_node"):
                delattr(self.trace, "current_node")

        self.trace.record_phase(node_name, "exec", time.time() - start)
        return result

    def post(self, shared, prep_res, exec_res):
        """Wrap post phase."""
        start = time.time()
        result = self._wrapped.post(shared, prep_res, exec_res)
        self.trace.record_phase(self._wrapped.__class__.__name__, "post", time.time() - start, {"action": result})
        return result


class TraceCollector:
    """Collects execution trace data for debugging."""

    def __init__(self, user_input: str):
        self.execution_id = str(uuid.uuid4())
        self.start_time = datetime.utcnow()
        self.user_input = user_input
        self.events = []
        self.llm_calls = []
        self.node_executions = []
        self.final_status = "running"
        self.path_taken = None  # Will be "A" or "B"

    def record_node_execution(self, node: str, duration: float, status: str, error: Optional[str] = None):
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

    def record_phase(self, node: str, phase: str, duration: float, extra: Optional[dict] = None):
        """Record execution phase details."""
        self.events.append({
            "timestamp": datetime.utcnow().isoformat(),
            "node": node,
            "phase": phase,
            "duration_ms": int(duration * 1000),
            "extra": extra,
        })

    def record_llm_request(self, node: str, prompt: str, kwargs: dict):
        """Record LLM request before execution."""
        # Store the pending request
        self.current_llm_call = {
            "node": node,
            "timestamp": datetime.utcnow().isoformat(),
            "model": kwargs.get("model", "unknown"),
            "prompt": prompt,
            "prompt_kwargs": {k: v for k, v in kwargs.items() if k != "schema"},
        }

    def record_llm_response(self, node: str, response, duration: float):
        """Record LLM response after execution."""
        if hasattr(self, "current_llm_call"):
            self.current_llm_call["duration_ms"] = int(duration * 1000)

            # Extract response data
            if hasattr(response, "json"):
                try:
                    response_data = response.json()
                    self.current_llm_call["response"] = response_data
                except Exception:
                    self.current_llm_call["response"] = str(response)
            else:
                self.current_llm_call["response"] = str(response)

            # Try to get token counts if available
            if hasattr(response, "usage"):
                # Check if usage is a method or a property
                usage_data = response.usage() if callable(response.usage) else response.usage
                if isinstance(usage_data, dict):
                    self.current_llm_call["tokens"] = {
                        "input": usage_data.get("input_tokens", 0),
                        "output": usage_data.get("output_tokens", 0),
                    }

            self.llm_calls.append(self.current_llm_call)
            delattr(self, "current_llm_call")

    def record_llm_error(self, node: str, error: str):
        """Record LLM error if call fails."""
        if hasattr(self, "current_llm_call"):
            self.current_llm_call["error"] = error
            self.llm_calls.append(self.current_llm_call)
            delattr(self, "current_llm_call")

    def set_final_status(self, status: str, shared_store: Optional[dict] = None, error: Optional[dict] = None):
        """Set final execution status and save important data."""
        self.final_status = status
        if shared_store:
            # Only save important keys, not internal ones
            self.final_shared_store = {
                k: v for k, v in shared_store.items() if not k.startswith("_") and k not in ["workflow_manager"]
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
        filename = f"pflow-trace-{timestamp}.json"
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

    def cleanup_llm_interception(self):
        """Restore original LLM get_model function if it was intercepted."""
        if hasattr(self, "_original_get_model"):
            import llm

            llm.get_model = self._original_get_model
            delattr(self, "_original_get_model")
            if hasattr(self, "_llm_interceptor_installed"):
                delattr(self, "_llm_interceptor_installed")


class PlannerProgress:
    """Displays progress indicators in terminal."""

    # Node name to emoji mapping
    NODE_ICONS: ClassVar[dict[str, str]] = {
        "WorkflowDiscoveryNode": "🔍 Discovery",
        "ComponentBrowsingNode": "📦 Browsing",
        "ParameterDiscoveryNode": "🔎 Parameters Discovery",
        "ParameterMappingNode": "📝 Parameters",
        "ParameterPreparationNode": "📋 Preparation",
        "WorkflowGeneratorNode": "🤖 Generating",
        "ValidatorNode": "✅ Validation",
        "MetadataGenerationNode": "💾 Metadata",
        "ResultPreparationNode": "📤 Finalizing",
    }

    def on_node_start(self, node_name: str):
        """Display node start with emoji and name."""
        display_name = self.NODE_ICONS.get(node_name, node_name)
        click.echo(f"{display_name}...", err=True, nl=False)

    def on_node_complete(self, node_name: str, duration: float):
        """Display node completion with duration."""
        click.echo(f" ✓ {duration:.1f}s", err=True)
