"""Detailed trace collection for workflow debugging."""

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, ClassVar, Optional

logger = logging.getLogger(__name__)

# Configurable truncation limits (can be overridden via environment variables)
# Using debugging-friendly defaults that capture more information
TRACE_PROMPT_MAX_LENGTH = int(os.environ.get("PFLOW_TRACE_PROMPT_MAX", "50000"))  # 50K chars for full prompts
TRACE_RESPONSE_MAX_LENGTH = int(os.environ.get("PFLOW_TRACE_RESPONSE_MAX", "20000"))  # 20K chars for full responses
TRACE_SHARED_STORE_MAX_LENGTH = int(os.environ.get("PFLOW_TRACE_STORE_MAX", "10000"))  # 10K chars for store values
TRACE_DICT_MAX_SIZE = int(os.environ.get("PFLOW_TRACE_DICT_MAX", "50000"))  # 50K chars for complex dicts
TRACE_LLM_CALLS_MAX = int(os.environ.get("PFLOW_TRACE_LLM_CALLS_MAX", "100"))  # Track up to 100 LLM calls

# Trace format version for future compatibility
TRACE_FORMAT_VERSION = "1.1.0"


class WorkflowTraceCollector:
    """Collects detailed execution traces for workflow debugging.

    Captures node execution data, shared store mutations, template resolutions,
    and LLM interactions. Saves traces to ~/.pflow/debug/ for analysis.
    """

    # Class-level attributes for thread-safe LLM interception
    _llm_lock: ClassVar[threading.Lock] = threading.Lock()
    _llm_interception_count: ClassVar[int] = 0
    _original_get_model: ClassVar[Optional[Callable[..., Any]]] = None
    _active_collectors: ClassVar[dict[int, "WorkflowTraceCollector"]] = {}  # thread_id -> collector

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
        self._current_node: Optional[str] = None

    def record_node_execution(
        self,
        node_id: str,
        node_type: str,
        duration_ms: float,
        shared_before: dict[str, Any],
        shared_after: dict[str, Any],
        success: bool,
        error: Optional[str] = None,
        template_resolutions: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record detailed node execution data.

        Args:
            node_id: Unique identifier for the node
            node_type: Type/class name of the node
            duration_ms: Execution duration in milliseconds
            shared_before: Shared store state before execution
            shared_after: Shared store state after execution
            success: Whether the node executed successfully
            error: Error message if execution failed
            template_resolutions: Template variables resolved during execution
        """
        # Build base event
        event = self._build_base_event(node_id, node_type, duration_ms, success, shared_before, shared_after)

        # Add optional fields
        if error:
            event["error"] = error
        if template_resolutions:
            event["template_resolutions"] = template_resolutions

        # Add LLM-specific data if present
        self._add_llm_data(event, node_id, shared_after)

        self.events.append(event)

    def _build_base_event(
        self,
        node_id: str,
        node_type: str,
        duration_ms: float,
        success: bool,
        shared_before: dict[str, Any],
        shared_after: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the base event dictionary with core fields.

        Args:
            node_id: Unique identifier for the node
            node_type: Type/class name of the node
            duration_ms: Execution duration in milliseconds
            success: Whether the node executed successfully
            shared_before: Shared store state before execution
            shared_after: Shared store state after execution

        Returns:
            Base event dictionary
        """
        return {
            "node_id": node_id,
            "node_type": node_type,
            "duration_ms": round(duration_ms, 2),
            "success": success,
            "shared_before": self._filter_shared(shared_before),
            "shared_after": self._filter_shared(shared_after),
            "mutations": self._calculate_mutations(shared_before, shared_after),
            "timestamp": datetime.now().isoformat(),
        }

    def _add_llm_data(
        self,
        event: dict[str, Any],
        node_id: str,
        shared_after: dict[str, Any],
    ) -> None:
        """Add LLM usage and response data to the event if present.

        Args:
            event: Event dictionary to update
            node_id: Node ID for namespaced lookup
            shared_after: Shared store state after execution
        """
        # Extract LLM usage (includes model in the dict)
        llm_usage = self._extract_llm_usage(node_id, shared_after)
        if llm_usage:
            event["llm_call"] = llm_usage

            # Find and add the prompt if available
            prompt = self._find_llm_prompt(node_id, event, shared_after)
            if prompt:
                self._add_truncated_field(event, "llm_prompt", prompt, TRACE_PROMPT_MAX_LENGTH)

        # Extract and add LLM response if available
        response = self._extract_llm_response(node_id, shared_after)
        if response:
            self._add_truncated_field(event, "llm_response", response, TRACE_RESPONSE_MAX_LENGTH)

    def _find_llm_prompt(
        self,
        node_id: str,
        event: dict[str, Any],
        shared_after: dict[str, Any],
    ) -> Optional[str]:
        """Find LLM prompt from various sources.

        Tries multiple locations in order:
        1. Intercepted LLM prompts
        2. __llm_calls__ data in shared_after
        3. shared_before (both root and namespaced)

        Args:
            node_id: Node ID for lookup
            event: Event dictionary containing shared_before
            shared_after: Shared store state after execution

        Returns:
            Prompt string if found, None otherwise
        """
        # Try intercepted prompts first
        prompt = self.llm_prompts.get(node_id)
        if prompt:
            return prompt

        # Try __llm_calls__ data
        prompt = self._find_prompt_in_llm_calls(node_id, shared_after)
        if prompt:
            return prompt

        # Try shared_before
        return self._find_prompt_in_shared_before(node_id, event)

    def _find_prompt_in_llm_calls(self, node_id: str, shared_after: dict[str, Any]) -> Optional[str]:
        """Find prompt in __llm_calls__ data.

        Args:
            node_id: Node ID to match
            shared_after: Shared store state after execution

        Returns:
            Prompt if found, None otherwise
        """
        llm_calls = shared_after.get("__llm_calls__", [])
        for call in llm_calls:
            if call.get("node_id") == node_id and "prompt" in call:
                prompt = call["prompt"]
                return prompt if isinstance(prompt, str) else None
        return None

    def _find_prompt_in_shared_before(self, node_id: str, event: dict[str, Any]) -> Optional[str]:
        """Find prompt in shared_before data.

        Args:
            node_id: Node ID for namespaced lookup
            event: Event dictionary containing shared_before

        Returns:
            Prompt if found, None otherwise
        """
        shared_before = event.get("shared_before", {})

        # Check root level first
        if "prompt" in shared_before:
            prompt = shared_before["prompt"]
            return prompt if isinstance(prompt, str) else None

        # Check namespaced location
        if node_id in shared_before and isinstance(shared_before[node_id], dict):
            prompt = shared_before[node_id].get("prompt")
            return prompt if isinstance(prompt, str) else None

        return None

    def _add_truncated_field(self, event: dict[str, Any], field_name: str, value: str, max_length: int) -> None:
        """Add a field to the event, truncating if necessary.

        Args:
            event: Event dictionary to update
            field_name: Base field name (e.g., "llm_prompt")
            value: Value to add
            max_length: Maximum length before truncation
        """
        if isinstance(value, str) and len(value) > max_length:
            event[f"{field_name}_truncated"] = value[:max_length] + "... [truncated]"
        else:
            event[field_name] = value

    def _extract_llm_usage(self, node_id: str, shared_after: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Extract LLM usage data from shared store.

        Checks both root level (for non-namespaced) and namespaced location.

        Args:
            node_id: Node ID for namespaced lookup
            shared_after: Shared store state after execution

        Returns:
            LLM usage data if found, None otherwise
        """
        if "llm_usage" in shared_after:
            usage = shared_after["llm_usage"]
            if isinstance(usage, dict):
                return usage
        elif node_id in shared_after and isinstance(shared_after[node_id], dict):
            namespaced_usage = shared_after[node_id].get("llm_usage")
            if isinstance(namespaced_usage, dict):
                return namespaced_usage
        return None

    def _extract_llm_response(self, node_id: str, shared_after: dict[str, Any]) -> Optional[str]:
        """Extract LLM response from shared store.

        Checks both root level and namespaced location.

        Args:
            node_id: Node ID for namespaced lookup
            shared_after: Shared store state after execution

        Returns:
            LLM response string if found, None otherwise
        """
        if "response" in shared_after:
            response = shared_after["response"]
            if isinstance(response, str):
                return response
        elif node_id in shared_after and isinstance(shared_after[node_id], dict):
            namespaced_response = shared_after[node_id].get("response")
            if isinstance(namespaced_response, str):
                return namespaced_response
        return None

    def _filter_shared(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Filter sensitive or large data from shared store.

        Args:
            shared: The shared store to filter

        Returns:
            Filtered version suitable for trace files
        """
        filtered: dict[str, Any] = {}

        for key, value in shared.items():
            # Skip system keys except our tracking keys
            if key.startswith("__") and key not in ["__llm_calls__", "__metrics__", "__is_planner__"]:
                continue

            # Skip internal trace/debug keys
            if key in ["_trace_collector", "_debug_context"]:
                continue

            # Handle different value types
            if isinstance(value, str):
                # Truncate large strings
                if len(value) > TRACE_SHARED_STORE_MAX_LENGTH:
                    filtered[key] = value[:TRACE_SHARED_STORE_MAX_LENGTH] + "... [truncated]"
                else:
                    filtered[key] = value
            elif isinstance(value, bytes):
                # Don't include binary data
                filtered[key] = f"<binary data: {len(value)} bytes>"
            elif isinstance(value, list) and key == "__llm_calls__":
                # Include LLM calls but limit size
                filtered[key] = value[:TRACE_LLM_CALLS_MAX] if len(value) > TRACE_LLM_CALLS_MAX else value
            elif isinstance(value, dict):
                # Recursively filter nested dicts (for namespaced data)
                if len(str(value)) > TRACE_DICT_MAX_SIZE:
                    filtered[key] = "<large dict truncated>"
                else:
                    filtered[key] = value
            else:
                # Include other types as-is
                filtered[key] = value

        return filtered

    def _calculate_mutations(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[str]]:
        """Calculate what changed in shared store.

        Args:
            before: Shared store before execution
            after: Shared store after execution

        Returns:
            Dictionary with added, removed, and modified keys
        """
        before_keys = set(before.keys())
        after_keys = set(after.keys())

        added = sorted(after_keys - before_keys)
        removed = sorted(before_keys - after_keys)

        # Check for modified values
        modified = []
        for key in before_keys & after_keys:
            try:
                if before[key] != after[key]:
                    modified.append(key)
            except Exception:
                # Handle unhashable types
                if str(before[key]) != str(after[key]):
                    modified.append(key)

        return {
            "added": added,
            "removed": removed,
            "modified": sorted(modified),
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
        safe_name = re.sub(r"[^a-zA-Z0-9-]", "-", self.workflow_name)[:30]
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

        # Determine final status
        failed_nodes = [e for e in self.events if not e.get("success", True)]
        final_status = "failed" if failed_nodes else "success"

        # Prepare trace data with format version
        trace_data = {
            "format_version": TRACE_FORMAT_VERSION,
            "execution_id": self.execution_id,
            "workflow_name": self.workflow_name,
            "start_time": self.start_time.isoformat(),
            "end_time": datetime.now().isoformat(),
            "duration_ms": round(duration_ms, 2),
            "final_status": final_status,
            "nodes_executed": len(self.events),
            "nodes_failed": len(failed_nodes),
            "nodes": self.events,
        }

        # Add summary of LLM calls if present
        llm_events = [e for e in self.events if "llm_call" in e]
        if llm_events:
            total_tokens = sum(e["llm_call"].get("total_tokens", 0) for e in llm_events)
            trace_data["llm_summary"] = {
                "total_calls": len(llm_events),
                "total_tokens": total_tokens,
                "models_used": list({e["llm_call"].get("model", "unknown") for e in llm_events}),
            }

        # Write to file with proper formatting
        with open(filepath, "w") as f:
            json.dump(trace_data, f, indent=2, default=str)

        return filepath

    def setup_llm_interception(self, node_id: str) -> None:
        """Thread-safe setup of LLM interception to capture prompts.

        Args:
            node_id: The node that will make LLM calls
        """
        import llm

        # Store current node for prompt capture
        self._current_node = node_id

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
                            if collector._current_node:
                                collector.llm_prompts[collector._current_node] = prompt_text
                                logger.debug(
                                    f"Captured prompt for node {collector._current_node} in thread {thread_id}"
                                )

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
