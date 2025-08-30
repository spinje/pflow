"""
Utility functions for planner debugging support.

This module provides helper functions for the debugging infrastructure,
including trace file saving, progress message formatting, and LLM interception.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional


def save_trace_to_file(trace_data: dict[str, Any], directory: Optional[Path] = None) -> str:
    """
    Save trace data to a JSON file with timestamp.

    Args:
        trace_data: Dictionary containing trace information
        directory: Directory to save file (default: ~/.pflow/debug)

    Returns:
        str: Full path to saved file

    Raises:
        PermissionError: If directory is not writable
    """
    if directory is None:
        directory = Path.home() / ".pflow" / "debug"

    # Create directory if it doesn't exist
    directory.mkdir(parents=True, exist_ok=True)

    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"planner-trace-{timestamp}.json"
    filepath = directory / filename

    # Save with proper error handling
    try:
        with open(filepath, "w") as f:
            json.dump(trace_data, f, indent=2, default=str)
    except PermissionError as e:
        raise PermissionError(f"Cannot write to {directory}: {e}") from e

    return str(filepath)


def format_progress_message(node_name: str, duration: Optional[float] = None, status: str = "running") -> str:
    """
    Format a progress message with emoji and optional duration.

    Args:
        node_name: Name of the node (e.g., "WorkflowDiscoveryNode")
        duration: Execution time in seconds (None if still running)
        status: One of "running", "complete", "failed"

    Returns:
        str: Formatted message like "🔍 Discovery... ✓ 2.1s"
    """
    # Node to display name mapping
    NODE_DISPLAY = {
        "WorkflowDiscoveryNode": ("🔍", "Discovery"),
        "ComponentBrowsingNode": ("📦", "Browsing"),
        "ParameterDiscoveryNode": ("🔎", "Parameters Discovery"),
        "ParameterMappingNode": ("📝", "Parameters"),
        "ParameterPreparationNode": ("📋", "Preparation"),
        "WorkflowGeneratorNode": ("🤖", "Generating"),
        "ValidatorNode": ("✅", "Validation"),
        "MetadataGenerationNode": ("💾", "Metadata"),
        "ResultPreparationNode": ("📤", "Finalizing"),
    }

    # Get emoji and display name
    emoji, display = NODE_DISPLAY.get(node_name, ("⚙️", node_name))

    # Format based on status
    if status == "running":
        return f"{emoji} {display}..."
    elif status == "complete" and duration is not None:
        return f"{emoji} {display}... ✓ {duration:.1f}s"
    elif status == "failed":
        return f"{emoji} {display}... ✗"
    else:
        return f"{emoji} {display}"


def create_llm_interceptor(
    on_request: Callable[[str, dict[str, Any]], None],
    on_response: Callable[[Any, float], None],
    on_error: Callable[[str], None],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Create a function that intercepts llm.get_model() calls.

    Args:
        on_request: Called with (prompt, kwargs) before LLM call
        on_response: Called with (response, duration) after LLM call
        on_error: Called with error message if LLM fails

    Returns:
        A function that replaces llm.get_model() and intercepts model.prompt()
    """

    def create_wrapper(original_get_model: Callable[..., Any]) -> Callable[..., Any]:
        """Returns a wrapper for llm.get_model"""

        def wrapped_get_model(*args: Any, **kwargs: Any) -> Any:
            # Get the model instance
            model = original_get_model(*args, **kwargs)

            # Save original prompt method
            original_prompt = model.prompt

            # Create intercepted prompt method
            def intercepted_prompt(prompt_text: str, **prompt_kwargs: Any) -> Any:
                import time

                start_time = time.time()

                # Call on_request callback
                on_request(prompt_text, prompt_kwargs)

                try:
                    # Call original prompt
                    response = original_prompt(prompt_text, **prompt_kwargs)

                    # Call on_response callback
                    duration = time.time() - start_time
                    on_response(response, duration)

                    return response

                except Exception as e:
                    # Call on_error callback
                    on_error(str(e))
                    raise

            # Replace prompt method
            model.prompt = intercepted_prompt
            return model

        return wrapped_get_model

    return create_wrapper
