"""Main CLI entry point for pflow."""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any, cast

import click

from pflow.core import StdinData, ValidationError, validate_ir
from pflow.core.exceptions import WorkflowExistsError, WorkflowValidationError
from pflow.core.output_controller import OutputController
from pflow.core.shell_integration import (
    read_stdin as read_stdin_content,
)
from pflow.core.shell_integration import (
    read_stdin_enhanced,
)
from pflow.core.workflow_manager import WorkflowManager
from pflow.registry import Registry
from pflow.runtime import compile_ir_to_flow

# Import MCP CLI commands

logger = logging.getLogger(__name__)


def handle_sigint(signum: int, frame: object) -> None:
    """Handle Ctrl+C gracefully."""
    click.echo("\ncli: Interrupted by user", err=True)
    sys.exit(130)  # Standard Unix exit code for SIGINT


def safe_output(value: Any) -> bool:
    """Safely output a value to stdout, handling broken pipes.

    Returns True if output was successful, False otherwise.
    """
    try:
        if isinstance(value, bytes):
            # Skip binary output with warning
            click.echo("cli: Skipping binary output (use --output-key with text values)", err=True)
            return False
        elif isinstance(value, str):
            click.echo(value)
            return True
        else:
            # Convert other types to string
            click.echo(str(value))
            return True
    except BrokenPipeError:
        # Exit cleanly when pipe is closed
        os._exit(0)
    except OSError as e:
        if hasattr(e, "errno") and e.errno == 32:  # EPIPE
            os._exit(0)
        raise


def _get_output_controller(ctx: click.Context) -> OutputController:
    """Get the OutputController from context, creating it if needed.

    Args:
        ctx: Click context

    Returns:
        OutputController instance
    """
    if ctx.obj and "output_controller" in ctx.obj:
        return cast(OutputController, ctx.obj["output_controller"])

    # Fallback: create one if not in context (shouldn't happen normally)
    return OutputController(
        print_flag=ctx.obj.get("print_flag", False) if ctx.obj else False,
        output_format=ctx.obj.get("output_format", "text") if ctx.obj else "text",
    )


def _echo_trace(ctx: click.Context, message: str) -> None:
    """Output trace file location message only in interactive mode.

    Trace messages are informational, not errors, so they should be
    suppressed in non-interactive mode (pipes, -p flag).

    Args:
        ctx: Click context
        message: Trace message to display
    """
    output_controller = _get_output_controller(ctx)
    if output_controller.is_interactive():
        click.echo(message, err=True)


def _echo_info(ctx: click.Context, message: str) -> None:
    """Output informational message only in interactive mode.

    Args:
        ctx: Click context
        message: Info message to display
    """
    output_controller = _get_output_controller(ctx)
    if output_controller.is_interactive():
        click.echo(message, err=True)


def _echo_error(message: str) -> None:
    """Output error message always, even in non-interactive mode.

    Errors are critical and should always be visible.

    Args:
        message: Error message to display
    """
    click.echo(message, err=True)


def _read_stdin_data() -> tuple[str | None, StdinData | None]:
    """Read stdin data, trying text first then enhanced.

    Returns:
        Tuple of (text_content, enhanced_stdin)
    """
    # For backward compatibility, try simple text reading first
    stdin_content = read_stdin_content()

    # Only try enhanced reading if simple reading failed (binary/large data)
    enhanced_stdin = None
    if stdin_content is None:  # Only when actually None, not empty string
        enhanced_stdin = read_stdin_enhanced()

    return stdin_content, enhanced_stdin


def _show_json_syntax_error(path: Path, content: str, error: json.JSONDecodeError) -> None:
    """Show a helpful JSON syntax error message."""
    click.echo(f"❌ Invalid JSON syntax in {path}", err=True)
    click.echo(f"Error at line {error.lineno}, column {error.colno}: {error.msg}", err=True)
    click.echo("", err=True)

    # Show the problematic line with context
    lines = content.splitlines()
    if 0 < error.lineno <= len(lines):
        # Show the line before (if exists) for context
        if error.lineno > 1:
            click.echo(f"Line {error.lineno - 1}: {lines[error.lineno - 2]}", err=True)

        # Show the problematic line
        problematic_line = lines[error.lineno - 1]
        click.echo(f"Line {error.lineno}: {problematic_line}", err=True)

        # Show a pointer to the error position
        if error.colno > 0:
            pointer = " " * (len(f"Line {error.lineno}: ") + error.colno - 1) + "^"
            click.echo(pointer, err=True)

    click.echo("", err=True)
    click.echo("Fix the JSON syntax error and try again.", err=True)


def _is_path_like(identifier: str) -> bool:
    """Heuristic to determine if identifier looks like a file path or .json file."""
    return (os.sep in identifier) or (os.altsep and os.altsep in identifier) or identifier.lower().endswith(".json")


def _try_load_workflow_from_file(path: Path) -> tuple[dict | None, str | None]:
    """Attempt to load a workflow from a file path, with error reporting.

    Returns a tuple of (workflow_ir, source). On handled errors, returns (None, "json_error").
    """
    if not path.exists():
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
            data = json.loads(content)
            if isinstance(data, dict) and "ir" in data:
                return data["ir"], "file"
            return data, "file"
    except json.JSONDecodeError as e:
        _show_json_syntax_error(path, content, e)
        return None, "json_error"
    except PermissionError:
        click.echo(f"cli: Permission denied reading file: '{path}'. Check file permissions.", err=True)
        return None, "json_error"
    except UnicodeDecodeError:
        click.echo(f"cli: Unable to read file: '{path}'. File must be valid UTF-8 text.", err=True)
        return None, "json_error"


def _try_load_workflow_from_registry(identifier: str, wm: WorkflowManager) -> tuple[dict | None, str | None]:
    """Attempt to load a workflow from registry by name, including stripping .json suffix."""
    if wm.exists(identifier):
        return wm.load_ir(identifier), "saved"
    if identifier.lower().endswith(".json"):
        name = identifier[:-5]
        if wm.exists(name):
            return wm.load_ir(name), "saved"
    return None, None


def resolve_workflow(identifier: str, wm: WorkflowManager | None = None) -> tuple[dict | None, str | None]:
    """Resolve workflow from file path or saved name.

    Resolution order:
    1. File paths (contains / or ends with .json)
    2. Exact saved workflow name
    3. Saved workflow without .json extension

    Returns:
        (workflow_ir, source) where source is 'file', 'saved', 'json_error', or None
    """
    if not wm:
        wm = WorkflowManager()

    # 1. File path detection (platform separators) or .json (case-insensitive)
    if _is_path_like(identifier):
        path = Path(identifier).expanduser().resolve()
        ir, source = _try_load_workflow_from_file(path)
        if ir is not None or source == "json_error":
            return ir, source

    # 2/3. Saved workflow (exact name or .json-stripped)
    ir, source = _try_load_workflow_from_registry(identifier, wm)
    if ir is not None:
        return ir, source

    return None, None


def find_similar_workflows(name: str, wm: WorkflowManager, max_results: int = 3) -> list[str]:
    """Find similar workflow names using substring matching."""
    all_names = [w["name"] for w in wm.list_all()]
    # Simple substring matching (existing pattern)
    matches = [n for n in all_names if name.lower() in n.lower()]
    if not matches:
        # Try reverse
        matches = [n for n in all_names if n.lower() in name.lower()]
    return matches[:max_results]


def _log_stdin_injection(stdin_type: str, size_or_path: str | int) -> None:
    """Log stdin injection details."""
    if stdin_type == "text":
        click.echo(f"cli: Injected stdin data ({size_or_path} bytes) into shared storage")
    elif stdin_type == "text_data":
        click.echo(f"cli: Injected text stdin data ({size_or_path} bytes) into shared storage")
    elif stdin_type == "binary":
        click.echo(f"cli: Injected binary stdin data ({size_or_path} bytes) into shared storage")
    elif stdin_type == "temp_file":
        click.echo(f"cli: Injected stdin temp file path: {size_or_path}")


def _inject_stdin_object(shared_storage: dict[str, Any], stdin_data: StdinData, verbose: bool) -> None:
    """Inject StdinData object into shared storage."""
    if stdin_data.is_text and stdin_data.text_data is not None:
        shared_storage["stdin"] = stdin_data.text_data
        if verbose:
            _log_stdin_injection("text_data", len(stdin_data.text_data))
    elif stdin_data.is_binary and stdin_data.binary_data is not None:
        shared_storage["stdin_binary"] = stdin_data.binary_data
        if verbose:
            _log_stdin_injection("binary", len(stdin_data.binary_data))
    elif stdin_data.is_temp_file and stdin_data.temp_path is not None:
        shared_storage["stdin_path"] = stdin_data.temp_path
        if verbose:
            _log_stdin_injection("temp_file", stdin_data.temp_path)


def _inject_stdin_data(shared_storage: dict[str, Any], stdin_data: str | StdinData | None, verbose: bool) -> None:
    """Inject stdin data into shared storage."""
    if stdin_data is None:
        return

    if isinstance(stdin_data, str):
        # Backward compatibility: string data
        shared_storage["stdin"] = stdin_data
        if verbose:
            _log_stdin_injection("text", len(stdin_data))
    elif isinstance(stdin_data, StdinData):
        _inject_stdin_object(shared_storage, stdin_data, verbose)


def _handle_workflow_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None = None,
    verbose: bool = False,
    output_format: str = "text",
    metrics_collector: Any | None = None,
    print_flag: bool = False,
    workflow_metadata: dict[str, Any] | None = None,
) -> bool:
    """Handle output from workflow execution.

    Args:
        shared_storage: The shared store after execution
        output_key: User-specified output key (--output-key flag)
        workflow_ir: The workflow IR (to check declared outputs)
        verbose: Whether to show verbose output
        output_format: Output format - "text" or "json"
        metrics_collector: Optional MetricsCollector for including metrics in JSON output
        print_flag: Whether -p flag is set (suppress warnings)
        workflow_metadata: Optional workflow metadata for JSON output

    Returns:
        True if output was produced, False otherwise.
    """
    if output_format == "json":
        return _handle_json_output(
            shared_storage, output_key, workflow_ir, verbose, metrics_collector, workflow_metadata
        )
    else:  # text format (default)
        return _handle_text_output(shared_storage, output_key, workflow_ir, verbose, print_flag)


def _is_valid_output_value(value: Any) -> bool:
    """Check if a value is valid for output.

    Args:
        value: The value to check

    Returns:
        True if the value is non-None and (not a string or non-empty string)
    """
    return value is not None and (not isinstance(value, str) or value.strip() != "")


def _find_in_namespaces(shared_storage: dict[str, Any], key: str) -> Any:
    """Find the last occurrence of a key in namespaced storage.

    Args:
        shared_storage: The shared storage dictionary
        key: The key to search for

    Returns:
        The last valid value found, or None
    """
    last_value = None

    for storage_key, namespace_dict in shared_storage.items():
        # Skip non-dict values and special keys
        if not isinstance(namespace_dict, dict):
            continue
        if storage_key.startswith("__") or storage_key.startswith("_"):
            continue

        # Check if this namespace contains the key
        if key in namespace_dict:
            value = namespace_dict[key]
            if _is_valid_output_value(value):
                last_value = value

    return last_value


def _find_auto_output(shared_storage: dict[str, Any]) -> tuple[str | None, Any]:
    """Find the auto-detectable output with the highest priority.

    In sequential workflows, returns the last occurrence of the highest priority key.
    Priority order: response > output > result > text > stdout

    Args:
        shared_storage: The shared storage dictionary

    Returns:
        Tuple of (key_found, value) or (None, None) if no output found
    """
    # Common output keys in priority order (highest priority first)
    priority_keys = ["response", "output", "result", "text", "stdout"]

    # For each priority level, find the LAST occurrence
    for priority_key in priority_keys:
        # Check namespaced storage first
        last_value = _find_in_namespaces(shared_storage, priority_key)
        if last_value is not None:
            return priority_key, last_value

        # Check direct storage (legacy/non-namespaced)
        if priority_key in shared_storage:
            value = shared_storage[priority_key]
            # Skip special dictionaries that are actually namespaces
            if not isinstance(value, dict) and _is_valid_output_value(value):
                return priority_key, value
            # Handle the case where it might be a dict but not a namespace
            if isinstance(value, dict) and not any(k in priority_keys for k in value) and _is_valid_output_value(value):
                return priority_key, value

    return None, None


def _handle_text_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
    print_flag: bool = False,
) -> bool:
    """Handle text formatted output (current behavior).

    Returns the first matching output as plain text.
    When print_flag (-p) is True, suppresses all warnings.
    """
    # User-specified key takes priority
    if output_key:
        if output_key in shared_storage:
            return safe_output(shared_storage[output_key])
        # Suppress warnings in -p mode
        if not print_flag:
            click.echo(f"cli: Warning - output key '{output_key}' not found in shared store", err=True)
        return False

    # Check workflow-declared outputs
    if _try_declared_outputs(shared_storage, workflow_ir, verbose and not print_flag):
        return True

    # Fall back to auto-detect from common keys (using unified function)
    key_found, value = _find_auto_output(shared_storage)
    if key_found:
        return safe_output(value)

    return False


def _emit_declared_output(
    shared_storage: dict[str, Any],
    declared_outputs: dict[str, Any],
    verbose: bool,
) -> bool:
    """Emit the first available declared output and return True.

    This helper reduces complexity in `_try_declared_outputs` by encapsulating
    the loop and verbose description printing.
    """
    for output_name, output_config in declared_outputs.items():
        if output_name in shared_storage:
            value = shared_storage[output_name]
            if verbose and isinstance(output_config, dict):
                output_desc = output_config.get("description", "")
                if output_desc:
                    click.echo(f"cli: Output '{output_name}': {output_desc}", err=True)
            return safe_output(value)
    return False


def _try_declared_outputs(
    shared_storage: dict[str, Any],
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
) -> bool:
    """Try to output from workflow-declared outputs.

    Args:
        shared_storage: The shared storage dictionary
        workflow_ir: The workflow IR specification
        verbose: Whether to show verbose output

    Returns:
        True if a declared output was found and printed, False otherwise
    """
    if not (workflow_ir and "outputs" in workflow_ir and workflow_ir["outputs"]):
        return False

    declared_outputs = workflow_ir["outputs"]

    # First attempt: use already-populated outputs (preferred path via compiler wrapper)
    if _emit_declared_output(shared_storage, declared_outputs, verbose):
        return True

    # Populate on-demand if not present
    _populate_declared_outputs_best_effort(shared_storage, workflow_ir)

    # Second attempt after population
    if _emit_declared_output(shared_storage, declared_outputs, verbose):
        return True

    _warn_missing_declared_outputs(declared_outputs, verbose)
    return False


def _populate_declared_outputs_best_effort(shared_storage: dict[str, Any], workflow_ir: dict[str, Any]) -> None:
    """Best-effort population of declared outputs from source expressions."""
    try:
        from pflow.runtime.output_resolver import populate_declared_outputs

        populate_declared_outputs(shared_storage, workflow_ir)
    except Exception:
        # Ignore population failures; fallback behavior will handle printing
        return


def _warn_missing_declared_outputs(declared_outputs: dict[str, Any], verbose: bool) -> None:
    """Warn when declared outputs are present but none were resolved."""
    if not verbose:
        return
    expected = ", ".join(declared_outputs.keys())
    click.echo(
        f"cli: Warning - workflow declares outputs [{expected}] but none could be resolved",
        err=True,
    )


def _handle_json_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
    metrics_collector: Any | None = None,
    workflow_metadata: dict[str, Any] | None = None,
) -> bool:
    """Handle JSON formatted output.

    Returns all declared outputs or specified key as JSON, optionally with metrics.
    """
    outputs = _collect_json_outputs(shared_storage, output_key, workflow_ir, verbose)

    # Build unified JSON structure
    result = {
        "success": True,
        "result": outputs,
    }

    # Always include workflow metadata (default to unsaved if not provided)
    result["workflow"] = workflow_metadata if workflow_metadata else _get_default_workflow_metadata()

    # Add metrics at top level if available (like before)
    if metrics_collector:
        llm_calls = shared_storage.get("__llm_calls__", [])
        metrics_summary = metrics_collector.get_summary(llm_calls)

        # Add top-level metrics (matching old structure)
        result["duration_ms"] = metrics_summary.get("duration_ms")
        result["total_cost_usd"] = metrics_summary.get("total_cost_usd")

        # For nodes_executed, only count workflow nodes (not planner nodes)
        result["nodes_executed"] = _extract_workflow_node_count(metrics_summary)

        # Also include detailed metrics for compatibility
        result["metrics"] = metrics_summary.get("metrics", {})

    return _serialize_json_result(result, verbose)


def _collect_json_outputs(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
) -> dict[str, Any]:
    """Collect outputs for JSON formatting.

    Args:
        shared_storage: The shared storage dictionary
        output_key: Optional specific key to output
        workflow_ir: The workflow IR specification
        verbose: Whether to show verbose output

    Returns:
        Dictionary of outputs to serialize as JSON
    """
    result = {}

    if output_key:
        # Specific key requested
        if output_key in shared_storage:
            result[output_key] = shared_storage[output_key]
        # In JSON mode, don't output warnings to stderr

    elif workflow_ir and "outputs" in workflow_ir and workflow_ir["outputs"]:
        # Collect ALL declared outputs
        declared = workflow_ir["outputs"]

        for output_name in declared:
            if output_name in shared_storage:
                result[output_name] = shared_storage[output_name]
        # In JSON mode, don't output warnings to stderr

    else:
        # Fallback: Use auto-detection (using unified function)
        key_found, value = _find_auto_output(shared_storage)
        if key_found:
            result[key_found] = value

    return result


def _get_default_workflow_metadata() -> dict[str, Any]:
    """Get default workflow metadata when none is provided."""
    return {"action": "unsaved"}


def _create_workflow_metadata(name: str | None, action: str) -> dict[str, Any]:
    """Create workflow metadata with name and action.

    Args:
        name: Workflow name (optional)
        action: Workflow action ("created", "reused", "unsaved")

    Returns:
        Workflow metadata dictionary

    Raises:
        ValueError: If action is not one of the allowed values
    """
    allowed_actions = {"created", "reused", "unsaved"}
    if action not in allowed_actions:
        raise ValueError(f"Invalid workflow action: {action}. Must be one of {allowed_actions}")

    metadata = {"action": action}
    if name:
        metadata["name"] = name
    return metadata


def _extract_workflow_node_count(metrics_summary: dict[str, Any]) -> int:
    """Extract workflow node count from metrics summary.

    Only counts workflow nodes, not planner nodes.
    """
    workflow_metrics = metrics_summary.get("metrics", {}).get("workflow", {})
    node_count = workflow_metrics.get("nodes_executed", 0)
    return int(node_count)  # Ensure we return an int


def _create_json_error_output(
    exception: Exception,
    metrics_collector: Any | None = None,
    shared_storage: dict[str, Any] | None = None,
    workflow_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create unified JSON error structure.

    Args:
        exception: The exception that occurred
        metrics_collector: Optional metrics collector
        shared_storage: Optional shared storage for LLM calls
        workflow_metadata: Optional workflow metadata

    Returns:
        Dictionary with unified error structure
    """
    from pflow.core.user_errors import UserFriendlyError
    from pflow.planning.error_handler import PlannerError

    # Determine error type
    suggestion: str | None
    if isinstance(exception, PlannerError):
        error_type = "PlannerError"
        message = exception.message
        details = str(exception)
        suggestion = exception.user_action
    elif isinstance(exception, UserFriendlyError):
        error_type = exception.__class__.__name__
        # Extract components from UserFriendlyError
        message = exception.title
        details = exception.explanation
        # Join suggestions list into a single string
        suggestion = " ".join(exception.suggestions) if exception.suggestions else None
    else:
        error_type = exception.__class__.__name__
        message = str(exception)
        details = None
        suggestion = None

    # Build error structure
    error_dict: dict[str, Any] = {
        "type": error_type,
        "message": message,
    }

    # Add optional error fields
    if details:
        error_dict["details"] = details
    if suggestion:
        error_dict["suggestion"] = suggestion

    result = {
        "success": False,
        "error": error_dict,
    }

    # Add workflow metadata if available
    result["workflow"] = workflow_metadata if workflow_metadata else _get_default_workflow_metadata()

    # Add metrics if available
    if metrics_collector:
        metrics_collector.record_workflow_end()
        llm_calls = shared_storage.get("__llm_calls__", []) if shared_storage else []
        metrics_summary = metrics_collector.get_summary(llm_calls)

        # Add top-level metrics (matching success structure)
        result["duration_ms"] = metrics_summary.get("duration_ms")
        result["total_cost_usd"] = metrics_summary.get("total_cost_usd")

        # For nodes_executed, only count workflow nodes
        result["nodes_executed"] = _extract_workflow_node_count(metrics_summary)

        # Include detailed metrics
        result["metrics"] = metrics_summary.get("metrics", {})

    return result


def _serialize_json_result(result: dict[str, Any], verbose: bool) -> bool:
    """Serialize result dictionary to JSON and output it.

    Args:
        result: Dictionary to serialize
        verbose: Whether to show verbose output

    Returns:
        True if output was successful, False otherwise
    """
    try:
        # Handle special types
        def json_serializer(obj: Any) -> Any:
            """Custom JSON serializer for non-standard types."""
            if isinstance(obj, bytes):
                return {"_type": "binary", "size": len(obj), "note": "Binary data not included in JSON output"}
            return str(obj)

        output = json.dumps(result, indent=2, ensure_ascii=False, default=json_serializer)
        return safe_output(output)
    except (TypeError, ValueError) as e:
        if verbose:
            click.echo(f"cli: Warning - JSON encoding error: {e}", err=True)
        # Fallback to error message
        error_output = json.dumps({"error": "JSON encoding failed", "message": str(e)})
        return safe_output(error_output)


def _cleanup_temp_files(stdin_data: str | StdinData | None, verbose: bool) -> None:
    """Clean up temporary files if any."""
    if isinstance(stdin_data, StdinData) and stdin_data.is_temp_file and stdin_data.temp_path is not None:
        try:
            import os

            os.unlink(stdin_data.temp_path)
            if verbose:
                click.echo(f"cli: Cleaned up temp file: {stdin_data.temp_path}")
        except OSError:
            # Log warning but don't fail
            if verbose:
                click.echo(f"cli: Warning - could not clean up temp file: {stdin_data.temp_path}", err=True)


def _auto_save_workflow(ir_data: dict[str, Any], metadata: dict[str, Any] | None = None) -> tuple[bool, str | None]:
    """Automatically save workflow without prompting (for non-interactive mode).

    Args:
        ir_data: The workflow IR data to save
        metadata: Optional metadata with suggested_name and description from planner

    Returns:
        Tuple of (was_saved, workflow_name) where was_saved indicates if the workflow
        was successfully saved and workflow_name is the name if saved.
    """
    workflow_manager = WorkflowManager()

    # Extract or generate workflow name
    default_name = metadata.get("suggested_name", "") if metadata else ""
    if not default_name:
        # Generate a timestamp-based name if no suggestion
        from datetime import datetime

        default_name = f"workflow_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Use the AI-generated description if available
    description = metadata.get("description", "") if metadata else ""

    # Extract rich metadata if available
    rich_metadata = None
    if metadata:
        rich_metadata = {
            "search_keywords": metadata.get("search_keywords", []),
            "capabilities": metadata.get("capabilities", []),
            "typical_use_cases": metadata.get("typical_use_cases", []),
        }
        # Filter out empty lists
        rich_metadata = {k: v for k, v in rich_metadata.items() if v}
        if not rich_metadata:
            rich_metadata = None

    # Try to save with the generated name
    workflow_name = default_name
    counter = 1
    while True:
        try:
            workflow_manager.save(workflow_name, ir_data, description, metadata=rich_metadata)
            return (True, workflow_name)
        except WorkflowExistsError:
            # If name exists, append a counter
            workflow_name = f"{default_name}_{counter}"
            counter += 1
            if counter > 100:  # Safety limit
                return (False, None)
        except Exception:
            # Other errors, don't save
            return (False, None)


def _prompt_workflow_save(
    ir_data: dict[str, Any], metadata: dict[str, Any] | None = None, default_save: bool = False
) -> tuple[bool, str | None]:
    """Prompt user to save workflow after execution.

    Args:
        ir_data: The workflow IR data to save
        metadata: Optional metadata with suggested_name and description from planner
        default_save: Whether the default prompt response should be "yes"

    Returns:
        Tuple of (was_saved, workflow_name) where was_saved indicates if the workflow
        was successfully saved and workflow_name is the name if saved.
    """
    default_response = "y" if default_save else "n"
    save_response = click.prompt("\nSave this workflow? (y/n)", type=str, default=default_response).lower()
    if save_response != "y":
        return (False, None)

    workflow_manager = WorkflowManager()

    # Extract defaults from metadata if available
    default_name = metadata.get("suggested_name", "") if metadata else ""
    default_description = metadata.get("description", "") if metadata else ""

    # Loop until successful save or user cancels
    while True:
        # Get workflow name with intelligent default
        if default_name:
            workflow_name = click.prompt("Workflow name", default=default_name, type=str)
        else:
            workflow_name = click.prompt("Workflow name", type=str)

        # Use the AI-generated description automatically (don't prompt)
        # This reduces friction and the AI descriptions are high quality
        description = default_description

        try:
            # Extract rich metadata if available (excluding suggested_name and description)
            rich_metadata = None
            if metadata:
                rich_metadata = {
                    "search_keywords": metadata.get("search_keywords", []),
                    "capabilities": metadata.get("capabilities", []),
                    "typical_use_cases": metadata.get("typical_use_cases", []),
                }
                # Filter out empty lists
                rich_metadata = {k: v for k, v in rich_metadata.items() if v}
                if not rich_metadata:
                    rich_metadata = None

            # Save the workflow with metadata passed directly (not embedded in IR)
            workflow_manager.save(workflow_name, ir_data, description, metadata=rich_metadata)
            click.echo(f"\n✅ Workflow saved as '{workflow_name}'")
            return (True, workflow_name)  # Success, return saved status
        except WorkflowExistsError:
            click.echo(f"\n❌ Error: A workflow named '{workflow_name}' already exists.")
            # Offer to use a different name
            retry = click.prompt("Try with a different name? (y/n)", type=str, default="n").lower()
            if retry != "y":
                return (False, None)  # User declined to retry
            # Continue loop to try again
        except WorkflowValidationError as e:
            click.echo(f"\n❌ Error: Invalid workflow name: {e!s}")
            return (False, None)  # Invalid name, don't retry
        except Exception as e:
            click.echo(f"\n❌ Error saving workflow: {e!s}")
            return (False, None)  # Other error, don't retry


def _prepare_shared_storage(
    execution_params: dict[str, Any] | None,
    planner_llm_calls: list[dict[str, Any]] | None,
    stdin_data: str | StdinData | None,
    verbose: bool,
    output_controller: OutputController | None = None,
) -> dict[str, Any]:
    """Prepare shared storage with execution params and stdin data.

    Args:
        execution_params: Optional parameters from planner for template resolution
        planner_llm_calls: Optional LLM calls from planner for metrics
        stdin_data: Optional stdin data to inject
        verbose: Whether to show verbose output
        output_controller: Optional OutputController for progress callbacks

    Returns:
        Prepared shared storage dictionary
    """
    shared_storage: dict[str, Any] = {}

    # Preserve LLM calls from planner if provided
    if planner_llm_calls:
        shared_storage["__llm_calls__"] = planner_llm_calls

    # Inject execution parameters from planner (for template resolution)
    if execution_params:
        shared_storage.update(execution_params)
        if verbose:
            click.echo(f"cli: Injected {len(execution_params)} execution parameters into shared storage")

    # Inject stdin data if present (may override execution params)
    _inject_stdin_data(shared_storage, stdin_data, verbose)

    # Add verbose flag for nodes to check
    shared_storage["__verbose__"] = verbose

    # Add output controller callback if provided
    if output_controller:
        callback = output_controller.create_progress_callback()
        if callback:
            shared_storage["__progress_callback__"] = callback

    return shared_storage


def _validate_workflow_structure(ir_data: dict[str, Any], ctx: click.Context) -> bool:
    """Validate the workflow structure.

    Returns:
        True if valid workflow, False if not a workflow.
    """
    # Return the condition directly (fixes SIM103)
    return isinstance(ir_data, dict) and "nodes" in ir_data and "ir_version" in ir_data


def _ensure_registry_loaded(ctx: click.Context) -> Registry:
    """Load registry with helpful error if missing.

    Returns:
        Loaded Registry instance.
    """
    registry = Registry()
    try:
        # This will auto-discover core nodes if registry doesn't exist
        registry.load()
    except Exception as e:
        output_format = ctx.obj.get("output_format", "text")
        verbose = ctx.obj.get("verbose", False)

        if output_format == "json":
            workflow_metadata = ctx.obj.get("workflow_metadata")
            error_output = _create_json_error_output(
                e,
                None,  # No metrics collector
                None,  # No shared storage
                workflow_metadata,
            )
            _serialize_json_result(error_output, verbose)
        else:
            click.echo(f"cli: Error - Failed to load registry: {e}", err=True)
            click.echo("cli: Try 'pflow registry list' to see available nodes.", err=True)
            click.echo("cli: Or 'pflow registry scan <path>' to add custom nodes.", err=True)
        ctx.exit(1)
    return registry


def _setup_workflow_collectors(
    ctx: click.Context,
    ir_data: dict[str, Any],
    output_format: str,
    metrics_collector: Any | None,
) -> tuple[Any | None, Any | None]:
    """Set up metrics and trace collectors.

    Returns:
        Tuple of (metrics_collector, workflow_trace).
    """
    workflow_trace = None

    # Only create new metrics collector if not provided and JSON output is requested
    if output_format == "json" and not metrics_collector:
        from pflow.core.metrics import MetricsCollector

        metrics_collector = MetricsCollector()

    if metrics_collector:
        metrics_collector.record_workflow_start()

    if ctx.obj.get("trace", False):
        from pflow.runtime.workflow_trace import WorkflowTraceCollector

        workflow_trace = WorkflowTraceCollector(ir_data.get("name", "workflow"))

    return metrics_collector, workflow_trace


def _compile_workflow(
    ir_data: dict[str, Any],
    registry: Registry,
    execution_params: dict[str, Any] | None,
    metrics_collector: Any | None,
    workflow_trace: Any | None,
) -> Any:
    """Compile IR to Flow with parameters and collectors."""
    return compile_ir_to_flow(
        ir_data,
        registry,
        initial_params=execution_params,
        metrics_collector=metrics_collector,
        trace_collector=workflow_trace,
    )


def _handle_workflow_error(
    ctx: click.Context,
    workflow_trace: Any | None,
    output_format: str,
    metrics_collector: Any | None,
    shared_storage: dict[str, Any],
    verbose: bool,
) -> None:
    """Handle workflow execution error."""
    # Only show error messages if not in JSON mode
    if output_format != "json":
        click.echo("cli: Workflow execution failed - Node returned error action", err=True)
        click.echo("cli: Check node output above for details", err=True)

    # Save trace even on error
    if workflow_trace:
        trace_file = workflow_trace.save_to_file()
        _echo_trace(ctx, f"📊 Workflow trace saved: {trace_file}")

    # Include metrics in error JSON if applicable
    if output_format == "json" and metrics_collector:
        llm_calls = shared_storage.get("__llm_calls__", [])
        metrics_summary = metrics_collector.get_summary(llm_calls)
        error_output = {"error": "Workflow execution failed", "is_error": True, **metrics_summary}
        _serialize_json_result(error_output, verbose)

    ctx.exit(1)


def _handle_workflow_success(
    ctx: click.Context,
    workflow_trace: Any | None,
    shared_storage: dict[str, Any],
    output_key: str | None,
    ir_data: dict[str, Any],
    output_format: str,
    metrics_collector: Any | None,
    verbose: bool,
) -> None:
    """Handle successful workflow execution."""
    if verbose and output_format != "json":
        click.echo("cli: Workflow execution completed")

    # Save trace if requested
    if workflow_trace:
        trace_file = workflow_trace.save_to_file()
        _echo_trace(ctx, f"📊 Workflow trace saved: {trace_file}")

    # Check for output from shared store (now with metrics)
    print_flag = ctx.obj.get("print_flag", False)
    workflow_metadata = ctx.obj.get("workflow_metadata")
    output_produced = _handle_workflow_output(
        shared_storage,
        output_key,
        ir_data,
        verbose,
        output_format,
        metrics_collector=metrics_collector,
        print_flag=print_flag,
        workflow_metadata=workflow_metadata,
    )

    # Only show success message if we didn't produce output
    if not output_produced:
        click.echo("Workflow executed successfully")


def _validate_and_load_registry(ctx: click.Context, ir_data: dict[str, Any]) -> Registry:
    """Validate workflow structure and load registry.

    Args:
        ctx: Click context
        ir_data: Workflow IR data

    Returns:
        Loaded Registry instance

    Raises:
        SystemExit: If validation fails
    """
    output_format = ctx.obj.get("output_format", "text")
    verbose = ctx.obj.get("verbose", False)

    # Check if it's valid JSON with workflow structure
    if not _validate_workflow_structure(ir_data, ctx):
        error_msg = "Invalid workflow - missing required fields (ir_version, nodes)"
        if output_format == "json":
            # Create a simple exception for the error
            error = ValueError(error_msg)
            workflow_metadata = ctx.obj.get("workflow_metadata")
            error_output = _create_json_error_output(
                error,
                None,  # No metrics collector
                None,  # No shared storage
                workflow_metadata,
            )
            _serialize_json_result(error_output, verbose)
        else:
            click.echo(f"cli: {error_msg}", err=True)
        ctx.exit(1)

    # Load registry and validate IR
    registry = _ensure_registry_loaded(ctx)
    try:
        validate_ir(ir_data)
    except ValidationError as e:
        if output_format == "json":
            workflow_metadata = ctx.obj.get("workflow_metadata")
            error_output = _create_json_error_output(
                e,
                None,  # No metrics collector
                None,  # No shared storage
                workflow_metadata,
            )
            _serialize_json_result(error_output, verbose)
        else:
            click.echo(f"cli: Invalid workflow - {e}", err=True)
        ctx.exit(1)

    return registry


def _format_compilation_error_text(e: Exception, verbose: bool) -> None:
    """Format and display compilation error in text mode.

    Args:
        e: The exception to format
        verbose: Whether to show verbose output
    """
    from pflow.core.user_errors import UserFriendlyError
    from pflow.runtime.compiler import CompilationError as CompilerCompilationError

    if isinstance(e, UserFriendlyError):
        # Use the formatted user-friendly error
        error_message = e.format_for_cli(verbose=verbose)
        click.echo(error_message, err=True)
    elif isinstance(e, CompilerCompilationError):
        # Handle old-style CompilationError with suggestion field
        # Keep as "Planning failed" for consistency with existing tests and UX
        click.echo(f"❌ Planning failed: {e}", err=True)
        if hasattr(e, "suggestion") and e.suggestion:
            click.echo(f"\n{e.suggestion}", err=True)
        if verbose:
            click.echo(f"\ncli: Error details: {e}", err=True)
    else:
        # Fallback for other exceptions
        click.echo(f"❌ Planning failed: {e}", err=True)
        if verbose:
            click.echo(f"cli: Error details: {e}", err=True)


def _handle_compilation_error_json(
    ctx: click.Context,
    e: Exception,
    metrics_collector: Any | None,
) -> None:
    """Handle compilation error in JSON output mode.

    Args:
        ctx: Click context
        e: The exception to handle
        metrics_collector: Optional metrics collector
    """
    verbose = ctx.obj.get("verbose", False)
    workflow_metadata = ctx.obj.get("workflow_metadata")
    error_output = _create_json_error_output(
        e,
        metrics_collector,
        None,  # No shared_storage at compilation time
        workflow_metadata,
    )
    _serialize_json_result(error_output, verbose)


def _compile_workflow_with_error_handling(
    ctx: click.Context,
    ir_data: dict[str, Any],
    registry: Registry,
    execution_params: dict[str, Any] | None,
    metrics_collector: Any | None,
    workflow_trace: Any | None,
) -> Any:
    """Compile workflow with error handling.

    Args:
        ctx: Click context
        ir_data: Workflow IR data
        registry: Loaded registry
        execution_params: Optional execution parameters
        metrics_collector: Optional metrics collector
        workflow_trace: Optional workflow trace

    Returns:
        Compiled Flow object

    Raises:
        SystemExit: If compilation fails
    """
    try:
        flow = _compile_workflow(ir_data, registry, execution_params, metrics_collector, workflow_trace)
        return flow
    except Exception as e:
        verbose = ctx.obj.get("verbose", False)
        output_format = ctx.obj.get("output_format", "text")

        # Handle error based on output format
        if output_format == "json":
            _handle_compilation_error_json(ctx, e, metrics_collector)
        else:
            _format_compilation_error_text(e, verbose)

        # Save trace if requested
        if workflow_trace:
            trace_path = workflow_trace.save_to_file()
            # Combine conditions to avoid nested if
            if trace_path and verbose and output_format != "json":
                click.echo(f"cli: Trace saved to {trace_path}", err=True)
        ctx.exit(1)


def _execute_workflow_and_handle_result(
    ctx: click.Context,
    flow: Any,
    shared_storage: dict[str, Any],
    metrics_collector: Any | None,
    workflow_trace: Any | None,
    output_key: str | None,
    ir_data: dict[str, Any],
    output_format: str,
    verbose: bool,
) -> None:
    """Execute workflow and handle the result.

    Args:
        ctx: Click context
        flow: Compiled Flow object
        shared_storage: Shared storage dictionary
        metrics_collector: Optional metrics collector
        workflow_trace: Optional workflow trace
        output_key: Optional output key
        ir_data: Workflow IR data
        output_format: Output format
        verbose: Verbose flag
    """
    result = flow.run(shared_storage)

    # Record workflow end if metrics are being collected
    if metrics_collector:
        metrics_collector.record_workflow_end()

    # Clean up LLM interception after successful run
    if workflow_trace and hasattr(workflow_trace, "cleanup_llm_interception"):
        workflow_trace.cleanup_llm_interception()

    # Route to appropriate handler based on result
    if result and isinstance(result, str) and result.startswith("error"):
        _handle_workflow_error(ctx, workflow_trace, output_format, metrics_collector, shared_storage, verbose)
    else:
        _handle_workflow_success(
            ctx, workflow_trace, shared_storage, output_key, ir_data, output_format, metrics_collector, verbose
        )


def _cleanup_workflow_resources(
    workflow_trace: Any | None,
    stdin_data: str | StdinData | None,
    verbose: bool,
) -> None:
    """Clean up workflow resources with robust error handling.

    Args:
        workflow_trace: Optional workflow trace collector
        stdin_data: Optional stdin data that may have temp files
        verbose: Whether to show verbose output
    """
    cleanup_errors = []

    # Ensure LLM interception is cleaned up
    if workflow_trace:
        try:
            if hasattr(workflow_trace, "cleanup_llm_interception"):
                workflow_trace.cleanup_llm_interception()
                if verbose:
                    logger.debug("LLM interception cleaned up successfully")
            else:
                logger.warning(
                    f"WorkflowTrace object missing cleanup_llm_interception method: {type(workflow_trace).__name__}"
                )
        except Exception as e:
            cleanup_errors.append(f"LLM cleanup failed: {e}")
            logger.error(f"Failed to cleanup LLM interception: {e}", exc_info=True)

    # Clean up temp files
    try:
        _cleanup_temp_files(stdin_data, verbose)
        if verbose and stdin_data:
            logger.debug("Temporary files cleaned up successfully")
    except Exception as e:
        cleanup_errors.append(f"Temp file cleanup failed: {e}")
        logger.error(f"Failed to cleanup temp files: {e}", exc_info=True)

    # Report any cleanup failures to user in verbose mode
    if cleanup_errors and verbose:
        click.echo("⚠️  Some cleanup operations failed:", err=True)
        for error in cleanup_errors:
            click.echo(f"   - {error}", err=True)


def _handle_workflow_exception(
    ctx: click.Context,
    e: Exception,
    workflow_trace: Any | None,
    output_format: str,
    metrics_collector: Any | None,
    shared_storage: dict[str, Any],
    verbose: bool,
) -> None:
    """Handle exceptions during workflow execution with proper cleanup.

    Args:
        ctx: Click context
        e: The exception that occurred
        workflow_trace: Optional workflow trace collector
        output_format: Output format - "text" or "json"
        metrics_collector: Optional metrics collector
        shared_storage: Shared storage dictionary
        verbose: Whether to show verbose output
    """
    logger.error(f"Workflow execution failed: {e}", exc_info=verbose)

    # Clean up LLM interception on error - robust handling
    if workflow_trace:
        try:
            if hasattr(workflow_trace, "cleanup_llm_interception"):
                workflow_trace.cleanup_llm_interception()
                logger.debug("LLM interception cleaned up after error")
            else:
                logger.warning("WorkflowTrace missing cleanup method during exception handling")
        except Exception as cleanup_error:
            logger.error(f"Failed to cleanup during exception: {cleanup_error}", exc_info=True)

    # Check if this is a user-friendly error
    from pflow.core.user_errors import UserFriendlyError

    # In JSON mode, output error as JSON
    if output_format == "json":
        # Get workflow metadata from context if available
        workflow_metadata = ctx.obj.get("workflow_metadata")
        error_output = _create_json_error_output(e, metrics_collector, shared_storage, workflow_metadata)
        _serialize_json_result(error_output, verbose)
    else:
        # Format error based on type
        if isinstance(e, UserFriendlyError):
            # Use the formatted user-friendly error
            error_message = e.format_for_cli(verbose=verbose)
            click.echo(error_message, err=True)
        else:
            # Fallback to generic error message
            click.echo(f"cli: Workflow execution failed - {e}", err=True)
            click.echo("cli: This may indicate a bug in the workflow or nodes", err=True)

    # Save trace on error if requested
    if workflow_trace:
        trace_file = workflow_trace.save_to_file()
        _echo_trace(ctx, f"📊 Workflow trace saved: {trace_file}")

    ctx.exit(1)


def execute_json_workflow(
    ctx: click.Context,
    ir_data: dict[str, Any],
    stdin_data: str | StdinData | None = None,
    output_key: str | None = None,
    execution_params: dict[str, Any] | None = None,
    planner_llm_calls: list[dict[str, Any]] | None = None,
    output_format: str = "text",
    metrics_collector: Any | None = None,
) -> None:
    """Execute a JSON workflow if it's valid.

    Args:
        ctx: Click context
        ir_data: Parsed workflow IR data
        stdin_data: Optional stdin data (string or StdinData) to inject into shared storage
        output_key: Optional key to output from shared storage after execution
        execution_params: Optional parameters from planner for template resolution
        planner_llm_calls: Optional LLM calls from planner for metrics attribution
        output_format: Output format - "text" (default) or "json"
        metrics_collector: Optional existing MetricsCollector to use (from planner)
    """
    # Validate workflow and load registry
    registry = _validate_and_load_registry(ctx, ir_data)

    # Set up collectors
    metrics_collector, workflow_trace = _setup_workflow_collectors(ctx, ir_data, output_format, metrics_collector)

    # Compile workflow with error handling
    flow = _compile_workflow_with_error_handling(
        ctx, ir_data, registry, execution_params, metrics_collector, workflow_trace
    )

    # Show verbose execution info if requested
    verbose = ctx.obj.get("verbose", False)
    if verbose and ctx.obj.get("output_format", "text") != "json":
        node_count = len(ir_data.get("nodes", []))
        click.echo(f"cli: Starting workflow execution with {node_count} node(s)")

    # Get output controller for interactive vs non-interactive mode
    output_controller = _get_output_controller(ctx)

    # Show workflow execution header if interactive
    if output_controller.is_interactive():
        node_count = len(ir_data.get("nodes", []))
        callback = output_controller.create_progress_callback()
        if callback:
            callback(str(node_count), "workflow_start", None, 0)

    # Prepare shared storage with params and stdin
    shared_storage = _prepare_shared_storage(
        execution_params, planner_llm_calls, stdin_data, verbose, output_controller
    )

    try:
        # Execute workflow and handle result
        _execute_workflow_and_handle_result(
            ctx, flow, shared_storage, metrics_collector, workflow_trace, output_key, ir_data, output_format, verbose
        )
    except (click.ClickException, SystemExit):
        # Let Click exceptions and exits propagate normally
        raise
    except Exception as e:
        _handle_workflow_exception(ctx, e, workflow_trace, output_format, metrics_collector, shared_storage, verbose)
    finally:
        _cleanup_workflow_resources(workflow_trace, stdin_data, verbose)


def _display_stdin_data(stdin_data: str | StdinData | None) -> None:
    """Display stdin data information."""
    if not stdin_data:
        return

    if isinstance(stdin_data, str):
        display_data = stdin_data[:50] + "..." if len(stdin_data) > 50 else stdin_data
        click.echo(f"Also collected stdin data: {display_data}")
    elif isinstance(stdin_data, StdinData):
        if stdin_data.is_text and stdin_data.text_data is not None:
            display_data = stdin_data.text_data[:50] + "..." if len(stdin_data.text_data) > 50 else stdin_data.text_data
            click.echo(f"Also collected stdin data: {display_data}")
        elif stdin_data.is_binary and stdin_data.binary_data is not None:
            click.echo(f"Also collected binary stdin data: {len(stdin_data.binary_data)} bytes")
        elif stdin_data.is_temp_file and stdin_data.temp_path is not None:
            click.echo(f"Also collected stdin data (temp file): {stdin_data.temp_path}")


def infer_type(value: str) -> Any:
    """Infer type from string value.

    Supports:
    - Booleans: 'true', 'false' (case-insensitive)
    - Numbers: integers and floats
    - JSON: arrays and objects starting with '[' or '{'
    - Strings: everything else (default)

    Args:
        value: String value to infer type from

    Returns:
        Inferred Python value with appropriate type
    """
    # Boolean detection
    if value.lower() in ("true", "false"):
        return value.lower() == "true"

    # Number detection
    try:
        # Try integer first (more restrictive)
        if "." not in value and "e" not in value.lower():
            return int(value)
        # Then try float
        return float(value)
    except ValueError:
        pass

    # JSON detection for arrays and objects
    if value.startswith(("[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass

    # Default to string
    return value


def parse_workflow_params(args: tuple[str, ...]) -> dict[str, Any]:
    """Parse key=value parameters from command arguments.

    Args:
        args: Tuple of command line arguments

    Returns:
        Dictionary of parsed parameters with inferred types
    """
    params = {}
    for arg in args:
        # Only process arguments with '='
        if "=" in arg:
            key, value = arg.split("=", 1)
            # Use type inference for the value
            params[key] = infer_type(value)
    return params


def _check_llm_configuration(verbose: bool) -> None:
    """Check if LLM is properly configured.

    Raises:
        ImportError: If llm module is not available
        ValueError: If LLM model is not configured properly
    """
    import llm

    # Quick check to see if API key is configured
    # We don't actually call the API here, just check configuration
    model_name = "anthropic/claude-sonnet-4-0"
    try:
        _ = llm.get_model(model_name)
        # The model loaded successfully - LLM is configured
        # Note: model.key may be None when using environment variables, which is fine
    except Exception as model_error:
        # If we can't get the model, API is likely not configured
        if verbose:
            click.echo(f"cli: LLM model check failed: {model_error}", err=True)
        raise ValueError(f"LLM model {model_name} not available") from model_error


def _handle_llm_configuration_error(
    ctx: click.Context,
    llm_error: Exception,
    verbose: bool,
) -> None:
    """Handle LLM configuration errors with helpful messages."""
    click.echo("cli: Natural language planner requires LLM configuration", err=True)
    click.echo("cli: To use the planner, configure the Anthropic API:", err=True)
    click.echo("cli:   1. Run: llm keys set anthropic", err=True)
    click.echo("cli:   2. Enter your API key from https://console.anthropic.com/", err=True)
    if verbose:
        click.echo(f"cli: Error details: {llm_error}", err=True)
    ctx.exit(1)


def _save_trace_if_needed(trace_collector: Any, trace_planner: bool, success: bool, ctx: click.Context) -> None:
    """Save trace file if needed based on conditions."""
    should_save = trace_planner or not success
    if not should_save:
        return

    trace_file = trace_collector.save_to_file()

    if not success:
        _echo_trace(ctx, f"📝 Debug trace saved: {trace_file}")
    else:  # trace_planner is True and success is True
        _echo_trace(ctx, f"📝 Planner trace saved: {trace_file}")


def _create_debug_context(raw_input: str, ctx: click.Context, metrics_collector: Any | None = None) -> tuple[Any, Any]:
    """Create debugging context for planner execution.

    Args:
        raw_input: The natural language input
        ctx: Click context containing configuration
        metrics_collector: Optional MetricsCollector for cost tracking

    Returns:
        Tuple of (debug_context, trace_collector)
    """
    from pflow.planning.debug import DebugContext, PlannerProgress, TraceCollector

    # Get output controller to determine interactive mode
    output_controller = _get_output_controller(ctx)

    trace_collector = TraceCollector(raw_input)
    progress = PlannerProgress(is_interactive=output_controller.is_interactive())
    debug_context = DebugContext(
        trace_collector=trace_collector, progress=progress, metrics_collector=metrics_collector
    )
    return debug_context, trace_collector


def _show_timeout_help(planner_timeout: int) -> None:
    """Display helpful message for timeout errors."""
    click.echo(f"\n⏰ Operation exceeded {planner_timeout}s timeout", err=True)
    click.echo("", err=True)
    click.echo("💡 This is likely due to AI service overload causing slow responses", err=True)
    click.echo("   Try one of these solutions:", err=True)
    click.echo("   • Wait a few minutes and try again", err=True)
    click.echo('   • Increase timeout: pflow --planner-timeout 120 "your request"', err=True)
    click.echo("   • Check service status at status.anthropic.com", err=True)


def _handle_timeout_completion(
    ctx: click.Context, shared: dict, trace_collector: Any, planner_timeout: int, verbose: bool
) -> None:
    """Handle timeout cases after planner completion."""
    planner_output = shared.get("planner_output", {})

    if isinstance(planner_output, dict) and planner_output.get("success"):
        # Workflow succeeded despite timeout
        if verbose:
            click.echo(f"\n⚠️  Operation took longer than {planner_timeout}s but completed successfully", err=True)
            click.echo("💡 Consider increasing --planner-timeout if this happens often", err=True)
        trace_collector.set_final_status("success", shared)
    elif isinstance(planner_output, dict) and planner_output.get("error_details"):
        # Flow completed but with API errors
        _handle_planning_failure(ctx, planner_output)
    else:
        # True timeout - show help
        _show_timeout_help(planner_timeout)
        trace_collector.set_final_status("timeout", shared)
        trace_file = trace_collector.save_to_file()
        _echo_trace(ctx, f"📝 Debug trace saved: {trace_file}")
        ctx.exit(1)


def _setup_planner_execution(
    ctx: click.Context,
    raw_input: str,
    stdin_data: str | StdinData | None,
    verbose: bool,
) -> tuple[Any | None, Any, Any, dict[str, Any]]:
    """Set up planner execution environment.

    Returns:
        Tuple of (metrics_collector, debug_context, trace_collector, shared_state)
    """
    # Show what we're doing if verbose
    if verbose:
        click.echo("cli: Using natural language planner to process input")
        click.echo("cli: Note: This may take 10-30 seconds for complex requests")

    # Create metrics collector if JSON output is requested
    metrics_collector = None
    if ctx.obj.get("output_format") == "json":
        from pflow.core.metrics import MetricsCollector

        metrics_collector = MetricsCollector()
        metrics_collector.record_planner_start()

    # Create debugging context with optional metrics
    debug_context, trace_collector = _create_debug_context(raw_input, ctx, metrics_collector)

    # Initialize shared state
    shared = {
        "user_input": raw_input,
        "workflow_manager": WorkflowManager(),  # Uses default ~/.pflow/workflows
        "stdin_data": stdin_data if stdin_data else None,
    }

    # Initialize LLM calls list when metrics collection is enabled
    if metrics_collector:
        shared["__llm_calls__"] = []

    return metrics_collector, debug_context, trace_collector, shared


def _run_planner_with_timeout(
    ctx: click.Context,
    planner_flow: Any,
    shared: dict[str, Any],
    trace_collector: Any,
    planner_timeout: int,
    verbose: bool,
) -> None:
    """Run the planner flow with timeout handling.

    Raises exceptions if planner fails.
    """
    import threading

    # Set up timeout detection (can only detect after completion due to Python limitations)
    timed_out = threading.Event()
    timer = threading.Timer(planner_timeout, lambda: timed_out.set())
    timer.start()

    try:
        # Run the planner (BLOCKING - cannot be interrupted)
        planner_flow.run(shared)

        # Check timeout AFTER completion
        if timed_out.is_set():
            _handle_timeout_completion(ctx, shared, trace_collector, planner_timeout, verbose)

    except SystemExit:
        # Don't catch intentional exits (from timeout handler, etc.)
        raise
    except Exception as e:
        # Import here to avoid circular dependency
        from pflow.core.exceptions import CriticalPlanningError

        # Handle critical planning failures with clear user messaging
        if isinstance(e, CriticalPlanningError):
            trace_collector.set_final_status("critical_failure", shared, {"message": str(e)})
            trace_file = trace_collector.save_to_file()
            click.echo(f"❌ Planning aborted: {e.reason}", err=True)
            if verbose and e.original_error:
                click.echo(f"   Original error: {e.original_error}", err=True)
            # Only show trace messages in interactive mode
            _echo_trace(ctx, f"📝 Debug trace saved: {trace_file}")
        else:
            # Handle other execution errors
            trace_collector.set_final_status("error", shared, {"message": str(e)})
            trace_file = trace_collector.save_to_file()
            click.echo(f"❌ Planner failed: {e}", err=True)
            _echo_trace(ctx, f"📝 Debug trace saved: {trace_file}")
        ctx.exit(1)

    finally:
        timer.cancel()


def _process_planner_result(
    ctx: click.Context,
    shared: dict[str, Any],
    trace_collector: Any,
    metrics_collector: Any | None,
    stdin_data: str | StdinData | None,
    output_key: str | None,
    verbose: bool,
) -> None:
    """Process planner result and execute workflow or handle failure."""
    # Check result
    planner_output = shared.get("planner_output", {})
    if not isinstance(planner_output, dict):
        planner_output = {}

    # Clean up LLM interception BEFORE workflow execution
    trace_collector.cleanup_llm_interception()

    # Set final status in trace
    success = planner_output.get("success", False)
    if success:
        trace_collector.set_final_status("success", shared)
    else:
        trace_collector.set_final_status("failed", shared, planner_output.get("error"))

    # Save trace if needed (using trace_planner flag for planner traces)
    trace_planner = ctx.obj.get("trace_planner", False)
    _save_trace_if_needed(trace_collector, trace_planner, success, ctx)

    # Record planner end if metrics are being collected
    if metrics_collector:
        metrics_collector.record_planner_end()

    # Execute workflow or handle failure
    if success:
        _execute_successful_workflow(ctx, planner_output, stdin_data, output_key, verbose, metrics_collector, shared)
    else:
        _handle_planning_failure(ctx, planner_output)


def _execute_planner_and_workflow(
    ctx: click.Context,
    raw_input: str,
    stdin_data: str | StdinData | None,
    output_key: str | None,
    verbose: bool,
    create_planner_flow: Any,
    trace: bool,
    planner_timeout: int,
) -> None:
    """Execute the planner flow and resulting workflow with optional debugging."""
    # Set up planner execution environment
    metrics_collector, debug_context, trace_collector, shared = _setup_planner_execution(
        ctx, raw_input, stdin_data, verbose
    )

    # Create planner flow with debugging context
    planner_flow = create_planner_flow(debug_context=debug_context)

    # Run planner with timeout handling
    _run_planner_with_timeout(ctx, planner_flow, shared, trace_collector, planner_timeout, verbose)

    # Process result and execute workflow
    _process_planner_result(ctx, shared, trace_collector, metrics_collector, stdin_data, output_key, verbose)


def _determine_workflow_metadata(
    ctx: click.Context,
    planner_output: dict,
    output_controller: Any,
) -> tuple[bool, str | None]:
    """Determine workflow metadata and handle pre-execution saving.

    Args:
        ctx: Click context
        planner_output: Planner output dictionary
        output_controller: Output controller for interactive checks

    Returns:
        Tuple of (was_saved, saved_name) for new workflows
    """
    workflow_source = planner_output.get("workflow_source")
    save_flag = ctx.obj.get("save", True)  # Default to True

    if workflow_source and workflow_source.get("found"):
        # Existing workflow was reused
        workflow_name = workflow_source.get("workflow_name", "unknown")
        ctx.obj["workflow_metadata"] = _create_workflow_metadata(workflow_name, "reused")
        return False, None

    if not save_flag:
        # save_flag is False, don't save at all
        ctx.obj["workflow_metadata"] = _get_default_workflow_metadata()
        return False, None

    # New workflow with save_flag=True
    if output_controller.should_show_prompts():
        # Interactive mode: will prompt after execution
        ctx.obj["workflow_metadata"] = None  # Will be set after execution
        return False, None

    # Non-interactive mode: auto-save NOW before execution
    was_saved, saved_name = _auto_save_workflow(
        planner_output["workflow_ir"], metadata=planner_output.get("workflow_metadata")
    )
    workflow_metadata = (
        _create_workflow_metadata(saved_name, "created")
        if was_saved and saved_name
        else _get_default_workflow_metadata()
    )
    ctx.obj["workflow_metadata"] = workflow_metadata
    return was_saved, saved_name


def _handle_post_execution_display(
    ctx: click.Context,
    planner_output: dict,
    output_controller: Any,
    save_flag: bool,
) -> None:
    """Handle post-execution display and prompts.

    Args:
        ctx: Click context
        planner_output: Planner output dictionary
        output_controller: Output controller for interactive checks
        save_flag: Whether saving is enabled
    """
    from .rerun_display import display_rerun_commands

    workflow_source = planner_output.get("workflow_source")

    if workflow_source and workflow_source.get("found"):
        # Handle reused workflow display
        if not output_controller.should_show_prompts():
            return

        workflow_name = workflow_source.get("workflow_name", "unknown")
        click.echo(f"\n✅ Reused existing workflow: '{workflow_name}'")

        execution_params = planner_output.get("execution_params")
        if execution_params is not None and workflow_name != "unknown":
            display_rerun_commands(workflow_name, execution_params)

    elif save_flag and output_controller.should_show_prompts():
        # Interactive mode: prompt for save after execution
        was_saved, saved_name = _prompt_workflow_save(
            planner_output["workflow_ir"],
            metadata=planner_output.get("workflow_metadata"),
            default_save=True,  # Default to "yes" when --save is set
        )

        # Update workflow metadata based on save result
        workflow_metadata = (
            _create_workflow_metadata(saved_name, "created")
            if was_saved and saved_name
            else _get_default_workflow_metadata()
        )
        ctx.obj["workflow_metadata"] = workflow_metadata

        # Display rerun command if saved
        if was_saved and saved_name:
            execution_params = planner_output.get("execution_params")
            if execution_params is not None:
                display_rerun_commands(saved_name, execution_params)


def _execute_successful_workflow(
    ctx: click.Context,
    planner_output: dict,
    stdin_data: str | StdinData | None,
    output_key: str | None,
    verbose: bool,
    metrics_collector: Any | None = None,
    planner_shared: dict[str, Any] | None = None,
) -> None:
    """Execute the successfully planned workflow."""
    if verbose:
        click.echo("cli: Executing generated/discovered workflow")

    # Pre-determine workflow metadata and handle saving BEFORE execution
    output_controller = _get_output_controller(ctx)
    _determine_workflow_metadata(ctx, planner_output, output_controller)

    # Execute the workflow
    execute_json_workflow(
        ctx,
        planner_output["workflow_ir"],
        stdin_data,
        output_key,
        planner_output.get("execution_params"),  # CRITICAL: Pass params for templates!
        planner_shared.get("__llm_calls__", []) if planner_shared else None,  # Pass planner LLM calls
        ctx.obj.get("output_format", "text"),
        metrics_collector,
    )

    # Handle post-execution actions (prompts and display for interactive mode)
    save_flag = ctx.obj.get("save", True)
    _handle_post_execution_display(ctx, planner_output, output_controller, save_flag)


def _handle_planning_failure(ctx: click.Context, planner_output: dict) -> None:
    """Handle planning failure with intelligent error messages and user guidance."""
    verbose = ctx.obj.get("verbose", False)

    # Check for structured error details from our new error classification
    error_details = planner_output.get("error_details")
    if error_details:
        # We have rich error information from PlannerError
        from pflow.planning.error_handler import ErrorCategory, PlannerError

        # Reconstruct PlannerError if we have a dict
        if isinstance(error_details, dict):
            planner_error = PlannerError(
                category=ErrorCategory(error_details.get("category", "unknown")),
                message=error_details.get("message", "Unknown error"),
                user_action=error_details.get("user_action", "Please retry"),
                technical_details=error_details.get("technical_details"),
                retry_suggestion=error_details.get("retry_suggestion", False),
            )
        else:
            planner_error = error_details

        # Display the formatted error
        click.echo(planner_error.format_for_cli(verbose), err=True)
    else:
        # Fallback to old error handling for backward compatibility
        error_msg = planner_output.get("error", "Unknown planning error")
        click.echo(f"❌ Planning failed: {error_msg}", err=True)

        # Show missing parameters if that's the issue
        missing_params = planner_output.get("missing_params")
        if missing_params:
            click.echo("👉 Missing required parameters:", err=True)
            for param in missing_params:
                click.echo(f"   - {param}", err=True)
            click.echo("👉 Provide these parameters in your request", err=True)

    ctx.exit(1)


def _setup_signals() -> None:
    """Setup signal handlers for the application."""
    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, handle_sigint)

    # Handle broken pipe for shell compatibility
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def _check_mcp_setup(ctx: click.Context) -> None:
    """Check if MCP tools need to be synced and inform user.

    This provides proactive guidance to users who have MCP servers configured
    but haven't synced the tools yet.
    """
    # Only check if this looks like a command that might use MCP
    # Skip check if in non-interactive mode to avoid clutter
    output_controller = _get_output_controller(ctx)
    if not output_controller.is_interactive():
        return

    # Only check if workflow text contains keywords suggesting MCP usage
    workflow_text = ctx.obj.get("workflow_text", "")
    mcp_keywords = ["slack", "github", "mcp", "message", "issue", "channel"]

    # Check if any keyword is in the workflow text (case-insensitive)
    if workflow_text and any(keyword in workflow_text.lower() for keyword in mcp_keywords):
        try:
            from pflow.registry import Registry

            registry = Registry()
            all_nodes = registry.list_nodes()
            mcp_count = len([n for n in all_nodes if n.startswith("mcp-")])

            # If no MCP tools are registered, check if servers are configured
            if mcp_count == 0:
                try:
                    from pflow.mcp import MCPServerManager

                    manager = MCPServerManager()
                    servers = manager.list_servers()

                    if servers:
                        # User has configured servers but hasn't synced
                        click.echo(
                            "💡 Tip: You have MCP servers configured but no tools synced.\n"
                            "   This workflow might need MCP tools. Run: pflow mcp sync --all\n",
                            err=True,
                        )
                except Exception as e:
                    # Log MCP check failure at debug level - this is optional functionality
                    logger.debug(f"Failed to check MCP server status: {e}")
        except Exception as e:
            # Log registry check failure at debug level - this is optional functionality
            logger.debug(f"Failed to check registry for MCP nodes: {e}")


def _initialize_context(
    ctx: click.Context,
    verbose: bool,
    output_key: str | None,
    output_format: str,
    print_flag: bool,
    trace: bool,
    trace_planner: bool,
    planner_timeout: int,
    save: bool,
) -> None:
    """Initialize the click context with configuration.

    Args:
        ctx: Click context to initialize
        verbose: Verbose mode flag
        output_key: Optional output key
        output_format: Output format (text/json)
        print_flag: Force non-interactive output flag
        trace: Trace execution flag
        trace_planner: Trace planner flag
        planner_timeout: Planner timeout in seconds
        save: Save workflow flag
    """
    if ctx.obj is None:
        ctx.obj = {}

    ctx.obj["verbose"] = verbose
    ctx.obj["output_key"] = output_key
    ctx.obj["output_format"] = output_format
    ctx.obj["print_flag"] = print_flag
    ctx.obj["trace"] = trace
    ctx.obj["trace_planner"] = trace_planner
    ctx.obj["planner_timeout"] = planner_timeout
    ctx.obj["save"] = save

    # Create OutputController once and store it for reuse
    ctx.obj["output_controller"] = OutputController(
        print_flag=print_flag,
        output_format=output_format,
    )


def _preprocess_run_prefix(ctx: click.Context, workflow: tuple[str, ...]) -> tuple[str, ...]:
    """Handle a leading 'run' token for UX compatibility.

    Returns the possibly modified workflow tuple. Exits on 'run' alone.
    """
    if workflow and workflow[0] == "run":
        if len(workflow) == 1:
            click.echo("cli: Need to specify what to run.", err=True)
            click.echo("cli: Usage: pflow <workflow-name>", err=True)
            click.echo("cli: List workflows: pflow workflow list", err=True)
            ctx.exit(1)
        return tuple(workflow[1:])
    return workflow


def _validate_workflow_flags(workflow: tuple[str, ...], ctx: click.Context) -> None:
    """Validate that CLI flags are not misplaced in workflow arguments.

    Args:
        workflow: Workflow arguments tuple
        ctx: Click context

    Raises:
        SystemExit: If misplaced flags are found
    """
    misplaced_flags = [
        arg
        for arg in workflow
        if arg in ("--trace", "--verbose", "-v", "--planner-timeout", "--output-key", "-o", "--output-format")
    ]
    if misplaced_flags:
        click.echo("cli: Error - CLI flags must come BEFORE the workflow text", err=True)
        click.echo(f"cli: Found misplaced flags: {', '.join(misplaced_flags)}", err=True)
        click.echo("cli: Correct usage examples:", err=True)
        click.echo('cli:   pflow --trace "create a story about llamas"', err=True)
        click.echo('cli:   pflow --verbose --trace "analyze this data"', err=True)
        click.echo('cli: NOT: pflow "create a story" --trace', err=True)
        ctx.exit(1)


def _validate_and_prepare_workflow_params(
    ctx: click.Context, workflow_ir: dict[str, Any], remaining_args: tuple[str, ...]
) -> dict[str, Any]:
    """Validate workflow parameters and apply defaults.

    Args:
        ctx: Click context
        workflow_ir: Workflow IR data
        remaining_args: Command line arguments for parameters

    Returns:
        Validated and prepared parameters dictionary

    Raises:
        SystemExit: If validation errors occur
    """
    # Parse parameters
    params = parse_workflow_params(remaining_args)

    # Validate parameter keys are valid identifiers
    invalid_keys = [k for k in params if not k.isidentifier()]
    if invalid_keys:
        click.echo(f"❌ Invalid parameter name(s): {', '.join(invalid_keys)}", err=True)
        click.echo("   👉 Parameter names must be valid Python identifiers", err=True)
        ctx.exit(1)

    # Import prepare_inputs from the right module
    from pflow.runtime.workflow_validator import prepare_inputs

    # Validate with prepare_inputs
    errors, defaults = prepare_inputs(workflow_ir, params)
    if errors:
        # Show user-friendly errors
        for msg, path, suggestion in errors:
            click.echo(f"❌ {msg}", err=True)
            if path and path != "root":
                click.echo(f"   At: {path}", err=True)
            if suggestion:
                click.echo(f"   👉 {suggestion}", err=True)
        ctx.exit(1)

    # Apply defaults
    if defaults:
        params.update(defaults)

    return params


def _handle_named_workflow(
    ctx: click.Context,
    first_arg: str,
    remaining_args: tuple[str, ...],
    stdin_data: str | StdinData | None,
    output_key: str | None,
    output_format: str,
    verbose: bool,
    workflow_ir: dict[str, Any] | None = None,
    source: str | None = None,
) -> bool:
    """Handle execution of a named or file-based workflow.

    Args:
        ctx: Click context
        first_arg: First workflow argument (name or path)
        remaining_args: Remaining workflow arguments
        stdin_data: Optional stdin data
        output_key: Optional output key
        output_format: Output format
        verbose: Verbose mode flag

    Returns:
        True if workflow was executed, False otherwise
    """
    if workflow_ir is None:
        workflow_ir, source = resolve_workflow(first_arg)
    if not workflow_ir:
        return False

    # Validate and prepare parameters
    params = _validate_and_prepare_workflow_params(ctx, workflow_ir, remaining_args)

    # Show what we're doing if verbose (but not in JSON mode)
    if verbose and output_format != "json":
        if source == "saved":
            click.echo(f"cli: Loading workflow '{first_arg}' from registry")
        else:
            click.echo(f"cli: Loading workflow from file: {first_arg}")
        if params:
            click.echo(f"cli: With parameters: {params}")

    # Create metrics collector if needed
    metrics_collector = None
    if output_format == "json":
        from pflow.core.metrics import MetricsCollector

        metrics_collector = MetricsCollector()

    # Execute workflow
    execute_json_workflow(ctx, workflow_ir, stdin_data, output_key, params, None, output_format, metrics_collector)
    return True


def _handle_workflow_not_found(ctx: click.Context, workflow_name: str, source: str | None) -> None:
    """Handle workflow not found error with helpful suggestions.

    Args:
        ctx: Click context
        workflow_name: Name of the workflow that wasn't found
        source: Source type from resolve_workflow

    Raises:
        SystemExit: Always exits with error
    """
    # Check if it was a JSON error (already displayed)
    if source == "json_error":
        ctx.exit(1)

    # Workflow not found - show helpful error
    wm = WorkflowManager()
    similar = find_similar_workflows(workflow_name, wm)
    click.echo(f"❌ Workflow '{workflow_name}' not found.", err=True)

    if similar:
        click.echo("\nDid you mean one of these?", err=True)
        for name in similar:
            click.echo(f"  - {name}", err=True)
    else:
        click.echo("\nUse 'pflow workflow list' to see available workflows.", err=True)
        click.echo('Or use quotes for natural language: pflow "your request"', err=True)

    ctx.exit(1)


def _execute_with_planner(
    ctx: click.Context,
    raw_input: str,
    stdin_data: str | StdinData | None,
    output_key: str | None,
    verbose: bool,
    source: str,
    trace: bool,
    planner_timeout: int,
) -> None:
    """Execute workflow using the natural language planner.

    Falls back to old behavior if planner is not available.
    """
    try:
        # Try to import planner first - this will raise ImportError if not available
        from pflow.planning import create_planner_flow

        # Check if LLM is configured before attempting to use planner
        try:
            _check_llm_configuration(verbose)
        except (ImportError, ValueError) as llm_error:
            # LLM not configured - fall back to old behavior
            if verbose:
                click.echo(f"cli: LLM not configured, falling back to simple echo: {llm_error}", err=True)
            click.echo(f"Collected workflow from {source}: {raw_input}")
            _display_stdin_data(stdin_data)
            return

        # Execute planner and workflow
        _execute_planner_and_workflow(
            ctx, raw_input, stdin_data, output_key, verbose, create_planner_flow, trace, planner_timeout
        )

    except ImportError:
        # Planner not available (likely in test environment or not fully installed)
        # Fall back to old behavior for compatibility
        click.echo(f"Collected workflow from {source}: {raw_input}")
        _display_stdin_data(stdin_data)

    except SystemExit:
        # Don't catch intentional exits (from timeout handler, etc.)
        raise
    except Exception as e:
        # Other errors in planner execution
        # Avoid duplicating the message printed by compilation handler
        click.echo(f"❌ Planning failed: {e}", err=True)
        ctx.exit(1)


def _single_word_hint(word: str) -> str | None:
    """Return a helpful hint for obvious single-word commands.

    Returns a message string if a targeted hint is available, otherwise None.
    """
    lower = word.lower()
    if lower == "workflows":
        return "Did you mean: pflow workflow list"
    if lower in {"list", "ls"}:
        return "Did you mean: pflow workflow list"
    if lower in {"help", "-h", "--help"}:
        return "For help: pflow --help"
    return None


def is_likely_workflow_name(text: str, remaining_args: tuple[str, ...]) -> bool:
    """Determine if text is likely a workflow name vs natural language.

    Uses heuristics to guess if the input is a workflow name that should
    be loaded directly, rather than sent to the planner.

    Args:
        text: The first argument from command line
        remaining_args: Any remaining arguments

    Returns:
        True if likely a workflow name, False otherwise
    """
    # Empty string is never a workflow name
    if not text:
        return False

    # Text with spaces is never a workflow name (even with params)
    # Workflow names are single words or kebab-case
    if " " in text:
        return False

    # NEW: Detect file paths (platform separators) and .json (case-insensitive)
    if os.sep in text or (os.altsep and os.altsep in text) or text.lower().endswith(".json"):
        return True

    # If there are parameter-like arguments following (key=value), likely a workflow name
    # But check that it's not CLI syntax (=> or --)
    if remaining_args and any("=" in arg for arg in remaining_args) and "=>" not in remaining_args:
        return True

    # Single kebab-case word is likely a workflow name
    # But exclude if followed by CLI operators or flags
    if "-" in text and not text.startswith("--"):
        # Check if followed by CLI syntax
        return not (
            remaining_args and ("=>" in remaining_args or any(arg.startswith("--") for arg in remaining_args[:2]))
        )

    # Don't treat single words as workflow names unless they have params
    # This prevents false positives with CLI node names like "node1", "read-file", etc.
    return False


# NOTE: This MUST be @click.command, not @click.group with catch-all argument.
# Click groups consume ALL positional args when using @click.argument("workflow", nargs=-1),
# preventing subcommands from being recognized. The wrapper (main_wrapper.py) handles routing.
@click.command(context_settings={"allow_interspersed_args": False})
@click.pass_context
@click.option("--version", is_flag=True, help="Show the pflow version")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed execution output")
@click.option("--output-key", "-o", "output_key", help="Shared store key to output to stdout (default: auto-detect)")
@click.option(
    "--output-format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format: text (default) or json",
)
@click.option("-p", "--print", "print_flag", is_flag=True, help="Force non-interactive output (print mode)")
@click.option("--trace", is_flag=True, help="Save workflow execution trace to file")
@click.option("--trace-planner", is_flag=True, help="Save planner execution trace to file")
@click.option("--planner-timeout", type=int, default=60, help="Timeout for planner execution (seconds)")
@click.option("--save/--no-save", default=True, help="Save generated workflow (default: save)")
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def workflow_command(
    ctx: click.Context,
    version: bool,
    verbose: bool,
    output_key: str | None,
    output_format: str,
    print_flag: bool,
    trace: bool,
    trace_planner: bool,
    planner_timeout: int,
    save: bool,
    workflow: tuple[str, ...],
) -> None:
    """pflow - Plan Once, Run Forever

    Natural language to deterministic workflows.

    \b
    Usage:
      pflow [OPTIONS] [WORKFLOW]...
      pflow workflow.json
      pflow my-workflow param=value
      command | pflow

    \b
    Commands:
      registry    Manage node registry (list, search, add custom nodes)
      workflow    Manage saved workflows (list, describe)
      mcp         Manage MCP server connections

    \b
    Examples:
      # Run saved workflow by name
      pflow my-workflow input=data.txt

      # Run workflow from file (no flag needed!)
      pflow ./workflow.json
      pflow ~/workflows/analysis.json

      # Natural Language - use quotes for commands with spaces
      pflow "read the file data.txt and summarize it"

      # Workflow Commands - manage saved workflows
      pflow workflow list                         # List saved workflows
      pflow workflow describe my-workflow         # Show workflow interface

      # Registry Commands - explore available nodes
      pflow registry list                         # List all nodes
      pflow registry search github                # Find GitHub nodes

      # From stdin - pipe from other commands
      echo "analyze this text" | pflow

    \b
    Notes:
      - Workflows can be specified by name, file path, or natural language
      - Use key=value syntax to pass parameters to workflows
      - Run 'pflow COMMAND --help' for more information on a command
    """
    # Handle version flag
    if version:
        click.echo("pflow version 0.0.1")
        ctx.exit(0)

    # Setup signal handlers
    _setup_signals()

    # Initialize context with configuration
    _initialize_context(
        ctx, verbose, output_key, output_format, print_flag, trace, trace_planner, planner_timeout, save
    )

    # Handle stdin data
    stdin_content, enhanced_stdin = _read_stdin_data()
    stdin_data = enhanced_stdin if enhanced_stdin else stdin_content

    # Validate CLI flags are not misplaced
    _validate_workflow_flags(workflow, ctx)

    # Preprocess: transparently handle `run` prefix
    workflow = _preprocess_run_prefix(ctx, workflow)

    # Store workflow text in context for MCP check
    raw_input = " ".join(workflow) if workflow else ""
    ctx.obj["workflow_text"] = raw_input

    # Check MCP setup and provide guidance if needed
    # Temporarily disabled for debugging
    # _check_mcp_setup(ctx)

    # Try to handle as named/file workflow first
    if workflow:
        first_arg = workflow[0]
        if is_likely_workflow_name(first_arg, workflow[1:]):
            # Resolve once to avoid duplicate calls
            workflow_ir, source = resolve_workflow(first_arg)
            # Try to execute as named workflow
            if _handle_named_workflow(
                ctx, first_arg, workflow[1:], stdin_data, output_key, output_format, verbose, workflow_ir, source
            ):
                return
            # If not found, handle the error
            _handle_workflow_not_found(ctx, first_arg, source or "unknown")

    # Natural language fallback
    raw_input = " ".join(workflow) if workflow else ""
    if not raw_input:
        raise click.ClickException("cli: No workflow provided. Use --help to see usage examples.")

    # Validate input length (100KB limit)
    if len(raw_input) > 100 * 1024:
        raise click.ClickException(
            "cli: Workflow input too large (max 100KB). Consider breaking it into smaller workflows."
        )

    # Single-token guardrails: block accidental planner for generic words
    if workflow and len(workflow) == 1 and (" " not in workflow[0]):
        word = workflow[0]
        # If it's a saved workflow, execute it directly
        ir, source = resolve_workflow(word)
        if ir is not None and _handle_named_workflow(
            ctx, word, (), stdin_data, output_key, output_format, verbose, ir, source
        ):
            return
        # Otherwise show targeted hints, or not-found guidance
        hint = _single_word_hint(word)
        if hint:
            click.echo(hint, err=True)
            ctx.exit(1)
        _handle_workflow_not_found(ctx, word, None)
        return

    # Multi-word or parameterized input: planner by design
    _execute_with_planner(ctx, raw_input, stdin_data, output_key, verbose, "args", trace, planner_timeout)


# Alias for backward compatibility with tests that import main directly
# Tests use: from pflow.cli.main import main
# This avoids breaking existing test infrastructure
main = workflow_command
