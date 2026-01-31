"""Main CLI entry point for pflow."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import sys
import time
import warnings
from pathlib import Path
from typing import Any, NoReturn, cast

import click

from pflow.core import StdinData
from pflow.core.exceptions import WorkflowExistsError, WorkflowValidationError
from pflow.core.output_controller import OutputController
from pflow.core.shell_integration import (
    read_stdin as read_stdin_content,
)
from pflow.core.shell_integration import (
    read_stdin_enhanced,
)
from pflow.core.validation_utils import is_valid_parameter_name
from pflow.core.workflow_manager import WorkflowManager
from pflow.execution import DisplayManager, ExecutionResult
from pflow.runtime.compiler import _display_validation_warnings

# Import MCP CLI commands

logger = logging.getLogger(__name__)


# NOTE: Logging configuration moved to logging_config.py
# It's now configured centrally in main_wrapper.py before any command routing.
# This ensures all command groups (workflow, registry, mcp, etc.) respect the verbose flag.


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
    """Output trace file location message.

    Shown in all modes EXCEPT:
    - -p (print) mode: user explicitly wants only raw output
    - JSON output mode: structured output only

    Trace files are valuable for debugging in non-interactive contexts
    like CI/CD, agents, and scripts.

    Args:
        ctx: Click context
        message: Trace message to display
    """
    output_controller = _get_output_controller(ctx)
    # Suppress in -p (print) or JSON modes - user wants only structured output
    if output_controller.print_flag or output_controller.output_format == "json":
        return
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

            # Extract IR if wrapped
            workflow_ir = data["ir"] if isinstance(data, dict) and "ir" in data else data

            # Auto-normalize: add missing boilerplate fields
            # This reduces friction for agent-generated workflows
            if isinstance(workflow_ir, dict):
                from pflow.core import normalize_ir

                normalize_ir(workflow_ir)

            return workflow_ir, "file"
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


def _handle_workflow_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None = None,
    verbose: bool = False,
    output_format: str = "text",
    metrics_collector: Any | None = None,
    print_flag: bool = False,
    workflow_metadata: dict[str, Any] | None = None,
    workflow_trace: Any | None = None,
    output_controller: Any = None,
    status: Any = None,
    warnings: list[dict[str, Any]] | None = None,
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
        workflow_trace: Optional workflow trace collector for saving JSON output

    Returns:
        True if output was produced, False otherwise.
    """
    if output_format == "json":
        return _handle_json_output(
            shared_storage,
            output_key,
            workflow_ir,
            verbose,
            metrics_collector,
            workflow_metadata,
            workflow_trace,
            status=status,
            warnings=warnings,
        )
    else:  # text format (default)
        return _handle_text_output(
            shared_storage,
            output_key,
            workflow_ir,
            verbose,
            print_flag,
            metrics_collector,
            workflow_metadata,
            output_controller=output_controller,
            status=status,
            warnings=warnings,
        )


def _output_with_header(value: Any, print_flag: bool, output_controller: Any, description: str | None = None) -> None:
    """Output value with appropriate header and stream routing based on execution mode.

    Three execution modes with different output strategies:

    1. --print mode (print_flag=True):
       - Use case: Piping output to other commands
       - Behavior: ONLY raw output to stdout, no header, no summary
       - Example: pflow --print my-workflow | jq

    2. Interactive terminal (is_interactive()=True):
       - Use case: Normal terminal usage with TTY
       - Behavior: Unix convention - header/summary to stderr, data to stdout
       - Rationale: Separates progress info from pipeable data
       - Example: pflow my-workflow (in terminal)

    3. Non-interactive (is_interactive()=False, print_flag=False):
       - Use case: Claude Code, CI/CD, non-TTY environments
       - Behavior: Everything to stderr for correct ordering
       - Rationale: Tools that capture streams separately may show stdout before stderr,
                    causing output to appear before summary. Keeping everything on stderr
                    preserves the intended order: summary → header → output
       - Example: pflow my-workflow (in Claude Code)

    Args:
        value: The output value to display
        print_flag: Whether --print flag is set
        output_controller: OutputController for interactive detection
        description: Optional description from workflow output declaration
    """
    # Build header with optional description
    header = f"\nWorkflow output ({description}):\n" if description else "\nWorkflow output:\n"

    if print_flag:
        # Mode 1: --print - raw output only (no header)
        safe_output(value)
    elif output_controller and output_controller.is_interactive():
        # Mode 2: Interactive - Unix convention
        click.echo(header, err=True)
        safe_output(value)
    else:
        # Mode 3: Non-interactive - everything on stderr
        click.echo(header, err=True)
        if isinstance(value, str):
            click.echo(value, err=True)
        else:
            click.echo(str(value), err=True)


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
    metrics_collector: Any | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    output_controller: Any = None,
    status: Any = None,
    warnings: list[dict[str, Any]] | None = None,
) -> bool:
    """Handle text formatted output with execution summary.

    Shows execution summary first, then workflow output.

    When print_flag (-p) is True, suppresses all warnings.

    Args:
        shared_storage: The shared store after execution
        output_key: User-specified output key (--output-key flag)
        workflow_ir: The workflow IR (to check declared outputs)
        verbose: Whether to show verbose output
        print_flag: Whether -p flag is set (suppress warnings)
        metrics_collector: Optional MetricsCollector for execution metrics
        workflow_metadata: Optional workflow metadata

    Returns:
        True if output was produced, False otherwise.
    """
    # Display execution summary FIRST (if metrics collector provided)
    # Skip summary entirely in --print mode (user wants ONLY raw output)
    if metrics_collector and not print_flag:
        from pflow.execution.formatters.success_formatter import format_execution_success

        formatted = format_execution_success(
            shared_storage=shared_storage,
            workflow_ir=workflow_ir or {},
            metrics_collector=metrics_collector,
            workflow_metadata=workflow_metadata,
            output_key=output_key,
            trace_path=None,  # Text mode doesn't include trace_path
            status=status,
            warnings=warnings,
        )

        _display_execution_summary(formatted, verbose)

    # Now show the actual output
    output_found = False

    # User-specified key takes priority
    if output_key:
        if output_key in shared_storage:
            _output_with_header(shared_storage[output_key], print_flag, output_controller)
            output_found = True
        else:
            # Suppress warnings in -p mode
            if not print_flag:
                click.echo(f"cli: Warning - output key '{output_key}' not found in shared store", err=True)

    # Check workflow-declared outputs
    elif workflow_ir and "outputs" in workflow_ir and workflow_ir["outputs"]:
        if _try_declared_outputs(
            shared_storage, workflow_ir, verbose and not print_flag, print_flag, output_controller
        ):
            output_found = True

    # Fall back to auto-detect from common keys (using unified function)
    else:
        key_found, value = _find_auto_output(shared_storage)
        if key_found:
            _output_with_header(value, print_flag, output_controller)
            output_found = True

    return output_found


def _emit_declared_output(
    shared_storage: dict[str, Any],
    declared_outputs: dict[str, Any],
    verbose: bool,
    print_flag: bool,
    output_controller: Any = None,
) -> bool:
    """Emit the first available declared output and return True.

    This helper reduces complexity in `_try_declared_outputs` by encapsulating
    the loop and verbose description printing.
    """
    for output_name, output_config in declared_outputs.items():
        if output_name in shared_storage:
            value = shared_storage[output_name]

            # Extract description from output config
            description = None
            if isinstance(output_config, dict):
                description = output_config.get("description")

            _output_with_header(value, print_flag, output_controller, description)
            return True
    return False


def _try_declared_outputs(
    shared_storage: dict[str, Any],
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
    print_flag: bool,
    output_controller: Any = None,
) -> bool:
    """Try to output from workflow-declared outputs.

    Args:
        shared_storage: The shared storage dictionary
        workflow_ir: The workflow IR specification
        verbose: Whether to show verbose output
        print_flag: Whether in non-interactive/print mode
        output_controller: OutputController for interactive detection

    Returns:
        True if a declared output was found and printed, False otherwise
    """
    if not (workflow_ir and "outputs" in workflow_ir and workflow_ir["outputs"]):
        return False

    declared_outputs = workflow_ir["outputs"]

    # First attempt: use already-populated outputs (preferred path via compiler wrapper)
    if _emit_declared_output(shared_storage, declared_outputs, verbose, print_flag, output_controller):
        return True

    # Populate on-demand if not present
    _populate_declared_outputs_best_effort(shared_storage, workflow_ir)

    # Second attempt after population
    if _emit_declared_output(shared_storage, declared_outputs, verbose, print_flag, output_controller):
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


def _get_status_indicator(status: str) -> str:
    """Get display indicator for node execution status.

    Args:
        status: Node execution status

    Returns:
        Single character indicator symbol
    """
    indicators = {
        "completed": "✓",
        "failed": "✗",
        "not_executed": "○",
    }
    return indicators.get(status, "?")


def _format_node_timing(duration_ms: int | float) -> str:
    """Format node execution timing for display.

    Args:
        duration_ms: Duration in milliseconds

    Returns:
        Formatted timing string
    """
    return f"({int(duration_ms)}ms)" if duration_ms and duration_ms > 0 else "(<1ms)"


def _format_node_status_line(step: dict[str, Any]) -> str:
    """Format complete node status line for display.

    For batch nodes, shows item success/failure counts.
    For regular nodes, shows standard status line.

    Args:
        step: Execution step dict with node_id, status, duration_ms, cached,
              and optional batch fields (is_batch, batch_total, batch_success, batch_errors)

    Returns:
        Formatted status line
    """
    node_id = step.get("node_id", "unknown")
    status = step.get("status", "unknown")
    duration_ms = step.get("duration_ms", 0)
    cached = step.get("cached", False)
    repaired = step.get("repaired", False)

    timing = _format_node_timing(duration_ms)

    # Build additional tags
    tags = []
    if cached:
        tags.append("cached")
    if repaired:
        tags.append("repaired")
    # Add smart handling tag for visibility (grep no-match, which not-found, etc.)
    # Tag mapping for smart handling patterns defined in shell.py _is_safe_non_error().
    # When adding new patterns there, ensure reason contains "no matches" or "not found",
    # OR add a new elif branch here. Fallback shows raw reason to avoid silent mystery.
    if step.get("smart_handled"):
        reason = step.get("smart_handled_reason", "")
        if "no matches" in reason:
            tags.append("no matches")
        elif "not found" in reason:
            tags.append("not found")
        elif reason:
            # Unknown pattern - show actual reason so agent knows what happened
            tags.append(reason)
    tag_str = f" [{', '.join(tags)}]" if tags else ""

    # Check if this is a batch node
    if step.get("is_batch"):
        total = step.get("batch_total", 0)
        success = step.get("batch_success", 0)
        errors = step.get("batch_errors", 0)

        if errors > 0:
            # Partial success - warning indicator
            return f"  ⚠ {node_id} {timing} - {success}/{total} items succeeded, {errors} failed{tag_str}"
        else:
            # Full success - checkmark
            return f"  ✓ {node_id} {timing} - {total}/{total} items succeeded{tag_str}"

    # Regular node
    # Use warning indicator if node produced stderr (has_stderr already implies completed)
    if step.get("has_stderr"):
        return f"  ⚠ {node_id} {timing}{tag_str}"

    indicator = _get_status_indicator(status)
    return f"  {indicator} {node_id} {timing}{tag_str}"


def _truncate_error_message(message: str, max_length: int = 200) -> str:
    """Truncate error message to max length with ellipsis."""
    if len(message) <= max_length:
        return message
    return message[: max_length - 3] + "..."


def _display_batch_errors(steps: list[dict[str, Any]]) -> None:
    """Display batch errors section for all batch nodes with failures.

    Args:
        steps: List of execution step dicts
    """
    for step in steps:
        if not step.get("is_batch") or step.get("batch_errors", 0) == 0:
            continue

        node_id = step.get("node_id", "unknown")
        error_details = step.get("batch_error_details", [])
        truncated = step.get("batch_errors_truncated", 0)

        click.echo(f"\nBatch '{node_id}' errors:", err=True)
        for err in error_details:
            idx = err.get("index", "?")
            msg = _truncate_error_message(str(err.get("error", "Unknown error")))
            click.echo(f"  [{idx}] {msg}", err=True)

        if truncated > 0:
            click.echo(f"  ...and {truncated} more errors", err=True)


def _display_stderr_warnings(steps: list[dict[str, Any]]) -> None:
    """Display stderr warnings for shell nodes that succeeded but produced stderr.

    This helps surface hidden errors from shell pipeline failures where
    intermediate commands fail but the overall exit code is 0.

    Args:
        steps: List of execution step dicts (may contain has_stderr and stderr fields)
    """
    stderr_warnings = [
        (step.get("node_id", "unknown"), step.get("stderr", ""))
        for step in steps
        if step.get("has_stderr") and step.get("stderr")
    ]

    if not stderr_warnings:
        return

    click.echo("\n⚠️  Shell stderr (exit code 0):", err=True)
    for node_id, stderr in stderr_warnings:
        # Truncate long stderr to 300 chars
        stderr_preview = stderr[:300]
        if len(stderr) > 300:
            stderr_preview += "..."
        # Indent multiline stderr for readability
        indented = stderr_preview.replace("\n", "\n     ")
        click.echo(f"  • {node_id}: {indented}", err=True)


def _display_workflow_action(workflow_name: str, workflow_action: str) -> None:
    """Display workflow name and action message.

    Args:
        workflow_name: Name of the workflow
        workflow_action: Action type (reused, created, unsaved)
    """
    click.echo("", err=True)
    if workflow_action == "reused":
        click.echo(f"{workflow_name} was executed", err=True)
    elif workflow_action == "created":
        click.echo(f"{workflow_name} was created and executed", err=True)
    # Skip showing workflow line for "unsaved" workflows


def _display_cost_summary(total_cost: float | None, formatted_result: dict[str, Any]) -> None:
    """Display LLM cost and token usage summary.

    Args:
        total_cost: Total cost in USD
        formatted_result: Full formatted result containing metrics
    """
    if total_cost is None or total_cost <= 0:
        return

    # Get token count for context
    metrics = formatted_result.get("metrics", {})
    workflow_metrics = metrics.get("workflow", {})
    total_tokens = workflow_metrics.get("total_tokens", 0)

    if total_tokens > 0:
        click.echo(f"💰 Cost: ${total_cost:.4f} ({total_tokens:,} tokens)", err=True)
    else:
        click.echo(f"💰 Cost: ${total_cost:.4f}", err=True)


def _display_workflow_completion_status(duration_s: float, status: str, has_stderr_warnings: bool) -> None:
    """Display workflow completion status with appropriate indicator.

    Args:
        duration_s: Execution duration in seconds
        status: Workflow status ("success", "degraded", "failed")
        has_stderr_warnings: Whether any shell node produced stderr with exit_code=0
    """
    if status == "degraded":
        click.echo(f"⚠️ Workflow completed with warnings in {duration_s:.3f}s", err=True)
    elif status == "failed":
        click.echo(f"❌ Workflow failed after {duration_s:.3f}s", err=True)
    elif has_stderr_warnings:
        click.echo(f"⚠️ Workflow completed in {duration_s:.3f}s", err=True)
    else:
        click.echo(f"✓ Workflow completed in {duration_s:.3f}s", err=True)


def _display_execution_summary(formatted_result: dict[str, Any], verbose: bool) -> None:
    """Display execution summary with metrics in text mode.

    Always shows:
    - Workflow name and action
    - Total execution time
    - Per-node execution details (timing, cache status)
    - LLM cost and token usage (if > 0)

    Args:
        formatted_result: Formatted result from format_execution_success()
        verbose: Currently unused, kept for compatibility
    """
    duration_ms = formatted_result.get("duration_ms")
    total_cost = formatted_result.get("total_cost_usd")

    # Extract execution details
    execution = formatted_result.get("execution", {})
    steps = execution.get("steps", []) if execution else []

    # Extract workflow metadata
    workflow_metadata = formatted_result.get("workflow", {})
    workflow_name = workflow_metadata.get("name", "workflow")
    workflow_action = workflow_metadata.get("action", "executed")

    # Count nodes
    total_nodes = len(steps)

    # Show workflow name and action (but not for unsaved workflows)
    _display_workflow_action(workflow_name, workflow_action)

    # Show total execution time with status-aware message
    if duration_ms is not None:
        duration_s = duration_ms / 1000.0
        status = formatted_result.get("status", "success")
        has_stderr_warnings = any(step.get("has_stderr") for step in steps)
        _display_workflow_completion_status(duration_s, status, has_stderr_warnings)

    # Show per-node execution details
    if steps:
        click.echo(f"Nodes executed ({total_nodes}):", err=True)
        for step in steps:
            status_line = _format_node_status_line(step)
            click.echo(status_line, err=True)

        # Show batch errors section if any batch nodes had failures
        _display_batch_errors(steps)

        # Show stderr warnings for shell nodes that succeeded but produced stderr
        _display_stderr_warnings(steps)

    # Show cost if > 0
    _display_cost_summary(total_cost, formatted_result)

    # Show warnings if present
    warnings = formatted_result.get("warnings", [])
    if warnings:
        click.echo("", err=True)
        click.echo("⚠️ Warnings:", err=True)
        for warning in warnings:
            node_id = warning.get("node_id", "unknown")
            warning_type = warning.get("type", "warning")
            message = warning.get("message", "No message")

            # Show the full warning message with proper indentation
            click.echo(f"  • {node_id} ({warning_type}):", err=True)
            for line in message.split("\n"):
                if line.strip():  # Skip empty lines
                    click.echo(f"    {line}", err=True)


def _handle_json_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
    metrics_collector: Any | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    workflow_trace: Any | None = None,
    status: Any = None,
    warnings: list[dict[str, Any]] | None = None,
) -> bool:
    """Handle JSON formatted output.

    Returns all declared outputs or specified key as JSON, optionally with metrics.
    """
    # Use shared formatter for consistency with MCP
    from pflow.execution.formatters.success_formatter import format_execution_success

    result = format_execution_success(
        shared_storage=shared_storage,
        workflow_ir=workflow_ir or {},
        metrics_collector=metrics_collector,
        workflow_metadata=workflow_metadata,
        output_key=output_key,
        trace_path=None,  # CLI doesn't include trace_path in output
        status=status,
        warnings=warnings,
    )

    # Save JSON output to trace if available
    if workflow_trace and hasattr(workflow_trace, "set_json_output"):
        workflow_trace.set_json_output(result)

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
    from pflow.core.json_utils import parse_json_or_original

    result = {}

    if output_key:
        # Specific key requested
        if output_key in shared_storage:
            result[output_key] = parse_json_or_original(shared_storage[output_key])
        # In JSON mode, don't output warnings to stderr

    elif workflow_ir and "outputs" in workflow_ir and workflow_ir["outputs"]:
        # Collect ALL declared outputs (JSON mode provides complete data)
        # Text mode only shows the first output for human readability
        declared = workflow_ir["outputs"]

        for output_name in declared:
            if output_name in shared_storage:
                result[output_name] = parse_json_or_original(shared_storage[output_name])
        # In JSON mode, don't output warnings to stderr

    else:
        # Fallback: Use auto-detection (using unified function)
        key_found, value = _find_auto_output(shared_storage)
        if key_found:
            result[key_found] = parse_json_or_original(value)

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

        # Add execution state if available
        if shared_storage and "__execution__" in shared_storage:
            exec_state = shared_storage["__execution__"]
            completed = exec_state.get("completed_nodes", [])
            failed = exec_state.get("failed_node")
            cache_hits = shared_storage.get("__cache_hits__", [])

            # Get node timings if available
            node_timings = {}
            workflow_metrics = metrics_summary.get("metrics", {}).get("workflow", {})
            node_timings = workflow_metrics.get("node_timings", {})

            # Build simplified steps for completed/failed nodes only
            # (we don't have workflow_ir here to know all nodes)
            steps = []
            for node_id in completed:
                steps.append({
                    "node_id": node_id,
                    "status": "completed",
                    "duration_ms": node_timings.get(node_id),
                    "cached": node_id in cache_hits,
                })

            if failed and failed not in completed:
                steps.append({
                    "node_id": failed,
                    "status": "failed",
                    "duration_ms": node_timings.get(failed),
                    "cached": False,
                })

            if steps:
                result["execution"] = {
                    "duration_ms": metrics_summary.get("duration_ms"),
                    "nodes_executed": len(completed),
                    "steps": steps,
                }

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


def _prepare_execution_environment(
    ctx: click.Context,
    ir_data: dict[str, Any],
    output_format: str,
    verbose: bool,
    execution_params: dict[str, Any] | None,
    planner_llm_calls: list[dict[str, Any]] | None,
    planner_cache_chunks: list[dict[str, Any]] | None = None,
) -> tuple[Any, Any, Any, dict[str, Any], bool]:
    """Prepare the execution environment for workflow execution.

    Returns:
        Tuple of (cli_output, display, workflow_trace, enhanced_params, effective_verbose)
    """
    from pflow.cli.cli_output import CliOutput

    # Extract context values
    print_flag = ctx.obj.get("print_flag", False)

    # Determine effective verbose flag for nodes
    # MCP server output should only show when -v is set AND not in print mode or JSON output
    effective_verbose = verbose and not print_flag and output_format != "json"

    # Create output interface
    cli_output = CliOutput(
        output_controller=_get_output_controller(ctx),
        verbose=verbose,
        output_format=output_format,
    )

    # Create display manager
    display = DisplayManager(output=cli_output)

    # Get workflow trace if requested
    workflow_trace = None
    if ctx.obj.get("trace", False):
        from pflow.runtime.workflow_trace import WorkflowTraceCollector

        workflow_trace = WorkflowTraceCollector(ir_data.get("name", "workflow"))
        ctx.obj["workflow_trace"] = workflow_trace

    # Prepare execution params with verbose flag and LLM calls
    enhanced_params = execution_params or {}
    enhanced_params["__verbose__"] = effective_verbose
    if planner_llm_calls:
        enhanced_params["__llm_calls__"] = planner_llm_calls
    if planner_cache_chunks:
        enhanced_params["__planner_cache_chunks__"] = planner_cache_chunks

    return cli_output, display, workflow_trace, enhanced_params, effective_verbose


def _handle_compilation_error(
    ctx: click.Context,
    error: Exception,
    output_format: str,
    verbose: bool,
    workflow_trace: Any | None,
    metrics_collector: Any | None,
) -> None:
    """Handle compilation errors specially.

    Args:
        ctx: Click context
        error: Compilation error
        output_format: Output format (json or text)
        verbose: Verbose flag
        workflow_trace: Optional workflow trace
        metrics_collector: Optional metrics collector
    """
    if output_format == "json":
        _handle_compilation_error_json(ctx, error, metrics_collector)
    else:
        _format_compilation_error_text(error, verbose)

    # Save trace if requested
    if workflow_trace:
        trace_path = workflow_trace.save_to_file()
        if trace_path and verbose and output_format != "json":
            click.echo(f"cli: Trace saved to {trace_path}", err=True)

    ctx.exit(1)


def _build_json_error_response(
    result: Any,
    metrics_collector: Any | None,
    shared_storage: dict[str, Any],
    ir_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build structured JSON error response.

    Args:
        result: ExecutionResult from workflow execution
        metrics_collector: Metrics collector instance
        shared_storage: Shared store with execution data
        ir_data: Optional workflow IR for complete execution state

    Returns:
        Structured error response dict
    """
    error_output: dict[str, Any] = {
        "success": False,
        "status": "failed",  # Add tri-state status for failures
        "error": "Workflow execution failed",
        "is_error": True,
    }

    # Use shared error formatter (SECURITY FIX: adds sanitization)
    if result and hasattr(result, "errors") and result.errors:
        from pflow.execution.formatters.error_formatter import format_execution_errors

        formatted = format_execution_errors(
            result,
            shared_storage=shared_storage,
            ir_data=ir_data,
            metrics_collector=metrics_collector,
            sanitize=True,  # SECURITY FIX: Sanitize sensitive data in JSON output
        )

        # Add formatted errors (sanitized)
        error_output["errors"] = formatted["errors"]
        if formatted["errors"]:
            error_output["failed_node"] = formatted["errors"][0].get("node_id")

        # Add execution state if available
        if formatted.get("execution"):
            error_output["execution"] = formatted["execution"]

        # Add metrics if available
        if formatted.get("metrics"):
            error_output.update(formatted["metrics"])

    return error_output


def _display_api_error_response(raw_response: dict[str, Any]) -> None:
    """Display API error response details.

    Args:
        raw_response: Raw API response dict
    """
    click.echo("\n  API Response:", err=True)

    # GitHub/API errors often have 'errors' array
    if errors_list := raw_response.get("errors"):
        for api_err in errors_list[:3]:
            field = api_err.get("field", "unknown")
            msg = api_err.get("message", api_err.get("code", "error"))
            click.echo(f"    - Field '{field}': {msg}", err=True)
    elif msg := raw_response.get("message"):
        click.echo(f"    {msg}", err=True)

    if doc_url := raw_response.get("documentation_url"):
        click.echo(f"\n  Documentation: {doc_url}", err=True)


def _display_mcp_error_details(mcp_error: dict[str, Any]) -> None:
    """Display MCP tool error details.

    Args:
        mcp_error: MCP error dict
    """
    click.echo("\n  MCP Tool Error:", err=True)

    if details := mcp_error.get("details"):
        click.echo(f"    Field: {details.get('field')}", err=True)
        click.echo(f"    Expected: {details.get('expected')}", err=True)
        click.echo(f"    Received: {details.get('received')}", err=True)
    elif msg := mcp_error.get("message"):
        click.echo(f"    {msg}", err=True)


def _display_single_error(
    error: dict[str, Any],
    error_number: int,
    auto_repair: bool,
    verbose: bool = False,
) -> None:
    """Display a single workflow error with all details.

    Args:
        error: Error dict from ExecutionResult
        error_number: Error number for display (1-indexed)
        auto_repair: Whether auto-repair is enabled
        verbose: Whether to show extended details (command, stdout, etc.)
    """
    if error_number == 1:
        click.echo("❌ Workflow execution failed", err=True)

    node_id = error.get("node_id", "unknown")
    category = error.get("category", "unknown")
    message = error.get("message", "Unknown error")

    click.echo(f"\nError {error_number} at node '{node_id}':", err=True)
    click.echo(f"  Category: {category}", err=True)
    click.echo(f"  Message: {message}", err=True)

    # Show raw API response if available (SECURITY FIX: Sanitize before display)
    if (raw := error.get("raw_response")) and isinstance(raw, dict):
        from pflow.mcp_server.utils.errors import sanitize_parameters

        sanitized_raw = sanitize_parameters(raw)
        _display_api_error_response(sanitized_raw)

    # Show MCP error details (SECURITY FIX: Sanitize before display)
    if (mcp := error.get("mcp_error")) and isinstance(mcp, dict):
        from pflow.mcp_server.utils.errors import sanitize_parameters

        sanitized_mcp = sanitize_parameters(mcp)
        _display_mcp_error_details(sanitized_mcp)

    # Show available fields for template errors
    if category == "template_error" and (available := error.get("available_fields")):
        total = error.get("available_fields_total", len(available))
        click.echo(f"\n  Available fields in node (showing {min(len(available), 5)} of {total}):", err=True)
        for field in available[:5]:
            click.echo(f"    - {field}", err=True)
        if len(available) > 5:
            click.echo(f"    ... and {len(available) - 5} more (in error details)", err=True)

        # Show trace file hint if fields were truncated
        if error.get("available_fields_truncated"):
            click.echo("\n  📁 Complete field list available in trace file", err=True)
            click.echo("     ~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json", err=True)

    # Show shell command details in verbose mode
    if verbose and "shell_command" in error:
        _display_shell_error_details(error)


def _display_shell_error_details(error: dict[str, Any]) -> None:
    """Display shell command details for a failed shell node.

    Args:
        error: Error dict containing shell_command, shell_stdout, shell_stderr
    """
    click.echo("\n  Shell details:", err=True)
    cmd = error.get("shell_command", "")
    # Truncate very long commands
    cmd_display = cmd[:200] + "..." if len(cmd) > 200 else cmd
    click.echo(f"    Command: {cmd_display}", err=True)
    if stdout := error.get("shell_stdout"):
        stdout_preview = stdout[:300] + "..." if len(stdout) > 300 else stdout
        click.echo(f"    Stdout: {stdout_preview}", err=True)
    if stderr := error.get("shell_stderr"):
        stderr_preview = stderr[:300] + "..." if len(stderr) > 300 else stderr
        click.echo(f"    Stderr: {stderr_preview}", err=True)


def _display_text_error_details(
    result: Any,
    auto_repair: bool,
    verbose: bool = False,
) -> None:
    """Display detailed text error output.

    Args:
        result: ExecutionResult with error details
        auto_repair: Whether auto-repair is enabled
        verbose: Whether to show extended details (command, stdout, etc.)
    """
    if not result or not hasattr(result, "errors") or not result.errors:
        # Fallback to generic message
        click.echo("cli: Workflow execution failed - Node returned error action", err=True)
        click.echo("cli: Check node output above for details", err=True)
        return

    for i, error in enumerate(result.errors, 1):
        _display_single_error(error, i, auto_repair, verbose=verbose)


def _handle_workflow_error(
    ctx: click.Context,
    result: Any,  # ExecutionResult
    workflow_trace: Any | None,
    output_format: str,
    metrics_collector: Any | None,
    shared_storage: dict[str, Any],
    verbose: bool,
    auto_repair: bool,
    ir_data: dict[str, Any] | None = None,
) -> None:
    """Handle workflow execution error with rich error context."""
    # Display rich error details
    if output_format == "json":
        # JSON mode: Include structured errors
        error_output = _build_json_error_response(result, metrics_collector, shared_storage, ir_data)
        _serialize_json_result(error_output, verbose)
    else:
        # Text mode: Show detailed rich error context
        _display_text_error_details(result, auto_repair, verbose=verbose)

    # Save trace even on error
    if workflow_trace:
        trace_file = workflow_trace.save_to_file()
        _echo_trace(ctx, f"📊 Workflow trace saved: {trace_file}")

    ctx.exit(1)


def _handle_workflow_success(
    ctx: click.Context,
    result: Any,  # ExecutionResult
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

    # Check for output from shared store (now with metrics)
    # NOTE: We handle output BEFORE saving trace so the JSON output can be included in the trace
    print_flag = ctx.obj.get("print_flag", False)
    workflow_metadata = ctx.obj.get("workflow_metadata")

    # Extract status and warnings from ExecutionResult (Phase 2-5 integration)
    status = getattr(result, "status", None)
    warnings = getattr(result, "warnings", [])

    output_produced = _handle_workflow_output(
        shared_storage,
        output_key,
        ir_data,
        verbose,
        output_format,
        metrics_collector=metrics_collector,
        print_flag=print_flag,
        workflow_metadata=workflow_metadata,
        workflow_trace=workflow_trace,
        output_controller=ctx.obj.get("output_controller"),
        status=status,
        warnings=warnings,
    )

    # Save trace if requested (AFTER handling output so JSON is included)
    if workflow_trace:
        trace_file = workflow_trace.save_to_file()
        _echo_trace(ctx, f"📊 Workflow trace saved: {trace_file}")

    # Only show success message if we didn't produce output
    # Use status from result if available
    if not output_produced:
        status = getattr(result, "status", None)
        if status and hasattr(status, "value"):
            status_str = status.value
            if status_str == "degraded":
                click.echo("⚠️ Workflow completed with warnings")
            elif status_str == "failed":
                click.echo("❌ Workflow execution failed")
            else:
                click.echo("Workflow executed successfully")
        else:
            click.echo("Workflow executed successfully")


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


def _execute_workflow_and_handle_result(
    ctx: click.Context,
    result: ExecutionResult,  # NEW: Accept ExecutionResult
    shared_storage: dict[str, Any],
    workflow_trace: Any | None,
    output_key: str | None,
    ir_data: dict[str, Any],
    output_format: str,
    metrics_collector: Any | None,
    verbose: bool,
    display: DisplayManager,  # NEW: Accept DisplayManager
) -> None:
    """Intermediate function that routes to appropriate handlers.

    This MUST be preserved for compatibility.

    Args:
        ctx: Click context
        result: ExecutionResult from workflow execution
        shared_storage: Shared storage dictionary after execution
        workflow_trace: Optional workflow trace
        output_key: Optional output key
        ir_data: Workflow IR data
        output_format: Output format
        metrics_collector: Optional metrics collector
        verbose: Verbose flag
        display: DisplayManager for output
    """

    # Note: Display output is handled by the handlers below, not here
    # This preserves the existing behavior where output format and
    # interactive mode determine what gets displayed

    # Clean up LLM interception after successful run
    if workflow_trace and hasattr(workflow_trace, "cleanup_llm_interception"):
        workflow_trace.cleanup_llm_interception()

    # Route based on result to display output data
    if result.success:
        _handle_workflow_success(
            ctx=ctx,
            result=result,
            workflow_trace=workflow_trace,
            shared_storage=shared_storage,
            output_key=output_key,
            ir_data=ir_data,
            output_format=output_format,
            metrics_collector=metrics_collector,
            verbose=verbose,
        )
    else:
        _handle_workflow_error(
            ctx=ctx,
            result=result,
            workflow_trace=workflow_trace,
            output_format=output_format,
            metrics_collector=metrics_collector,
            shared_storage=shared_storage,
            verbose=verbose,
            auto_repair=ctx.obj.get("auto_repair", False),
            ir_data=ir_data,
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
    # Only show traceback if verbose mode enabled
    if verbose:
        logger.error(f"Workflow execution failed: {e}", exc_info=True)
    else:
        logger.error(f"Workflow execution failed: {e}")

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
            # Check if this is a registry load error
            error_str = str(e)
            if isinstance(e, RuntimeError) and "registry" in error_str.lower():
                click.echo(f"cli: Error - Failed to load registry: {e}", err=True)
                click.echo("cli: Try 'pflow registry list' to see available nodes.", err=True)
                click.echo("cli: Or 'pflow registry scan <path>' to add custom nodes.", err=True)
            else:
                # Fallback to generic error message
                click.echo(f"cli: Workflow execution failed - {e}", err=True)
                click.echo("cli: This may indicate a bug in the workflow or nodes", err=True)

    # Save trace on error if requested
    if workflow_trace:
        trace_file = workflow_trace.save_to_file()
        _echo_trace(ctx, f"📊 Workflow trace saved: {trace_file}")

    ctx.exit(1)


def _save_repaired_workflow(
    ctx: click.Context,
    repaired_workflow_ir: dict[str, Any],
) -> None:
    """Save repaired workflow based on source type.

    Args:
        ctx: Click context containing workflow_source, workflow_name, etc.
        repaired_workflow_ir: The repaired workflow IR to save
    """
    from .repair_save_handlers import save_repaired_workflow

    save_repaired_workflow(ctx, repaired_workflow_ir)


def _setup_execution_context(
    ctx: click.Context,
    ir_data: dict[str, Any],
    output_format: str,
    metrics_collector: Any | None,
) -> tuple[bool, bool, Any | None]:
    """Setup execution context and return configuration values.

    Args:
        ctx: Click context
        ir_data: Workflow IR data
        output_format: Output format
        metrics_collector: Optional metrics collector

    Returns:
        Tuple of (verbose, auto_repair, metrics_collector)
    """
    verbose = ctx.obj.get("verbose", False)
    auto_repair = ctx.obj.get("auto_repair", False)

    # Set up metrics collector if not provided (for both text and JSON mode)
    if not metrics_collector:
        from pflow.core.metrics import MetricsCollector

        metrics_collector = MetricsCollector()

    # Note: Validation now happens after _prepare_execution_environment()
    # with real enhanced_params, in execute_json_workflow()

    return verbose, auto_repair, metrics_collector


def _perform_validation(
    ir_data: dict[str, Any],
    output_format: str,
) -> tuple[list[str], list[Any]]:
    """Perform static workflow validation.

    Args:
        ir_data: Workflow IR data
        output_format: Output format for error display

    Returns:
        Tuple of (errors, warnings):
        - errors: List of validation errors (empty if valid)
        - warnings: List of ValidationWarning objects

    Raises:
        SystemExit: If validation raises an exception
    """
    from pflow.core.workflow_validator import WorkflowValidator
    from pflow.registry.registry import Registry

    registry = Registry()

    # Generate dummy values for declared inputs to enable structural template validation
    dummy_params = {}
    declared_inputs = ir_data.get("inputs", {})
    for input_name in declared_inputs:
        dummy_params[input_name] = "__validation_placeholder__"

    try:
        errors, warnings = WorkflowValidator.validate(
            workflow_ir=ir_data,
            extracted_params=dummy_params,  # Dummy values enable structural validation
            registry=registry,  # Pass Registry object, not metadata dict
            skip_node_types=False,
        )
    except Exception as e:
        if output_format == "json":
            click.echo(json.dumps({"success": False, "error": f"Validation error: {e}"}))
        else:
            click.echo(f"✗ Validation error: {e}", err=True)
        import sys

        sys.exit(1)

    return (errors, warnings)


def _display_validation_results(
    errors: list[str],
    warnings: list[Any],
    output_format: str,
) -> None:
    """Display validation results and exit.

    Args:
        errors: List of validation errors (empty if valid)
        warnings: List of ValidationWarning objects
        output_format: Output format (text or json)

    Note:
        This function calls sys.exit() and never returns
    """
    import sys

    # Use shared formatter for validation display
    from pflow.execution.formatters.validation_formatter import (
        format_validation_failure,
        format_validation_success,
    )

    if not errors:
        if output_format == "json":
            click.echo(json.dumps({"success": True, "message": "Workflow structure is valid"}))
        else:
            # Use formatter for success display
            success_text = format_validation_success()
            click.echo(success_text)

            # Display warnings if present (complex, CLI-specific)
            if warnings:
                _display_validation_warnings(warnings)
        sys.exit(0)
    else:
        # Display validation errors
        if output_format == "json":
            click.echo(json.dumps({"success": False, "errors": errors}))
        else:
            # Use formatter for error display (auto-generates suggestions)
            error_text = format_validation_failure(errors)
            click.echo(error_text, err=True)
        sys.exit(1)


def _handle_validate_only_mode(
    ctx: click.Context,
    ir_data: dict[str, Any],
    output_format: str,
) -> None:
    """Handle --validate-only flag by performing static validation and exiting.

    Args:
        ctx: Click context
        ir_data: Workflow IR data (will be normalized in-place)
        output_format: Output format (text or json)

    Note:
        This function calls sys.exit() and never returns
    """
    if output_format != "json":
        click.echo("Validating workflow (static validation)...")

    # Note: Normalization already happened in _try_load_workflow_from_file()
    # No need to normalize again here

    # Perform static validation
    errors, warnings = _perform_validation(ir_data, output_format)

    # Display results and exit
    _display_validation_results(errors, warnings, output_format)


def _validate_before_execution(
    ctx: click.Context,
    ir_data: dict[str, Any],
    execution_params: dict[str, Any],
    output_format: str,
    verbose: bool,
) -> None:
    """Validate workflow before execution using full WorkflowValidator.

    This uses real execution params (not dummy) for complete template validation.
    Exits on validation failure.

    Args:
        ctx: Click context
        ir_data: Workflow IR data
        execution_params: Real execution parameters for template validation
        output_format: Output format (text or json)
        verbose: Verbose flag
    """
    from pflow.core.workflow_validator import WorkflowValidator
    from pflow.execution.formatters.validation_formatter import format_validation_failure
    from pflow.registry.registry import Registry

    registry = Registry()

    errors, warnings = WorkflowValidator.validate(
        workflow_ir=ir_data,
        extracted_params=execution_params,  # Real params for full validation
        registry=registry,
        skip_node_types=False,
    )

    if errors:
        if output_format == "json":
            workflow_metadata = ctx.obj.get("workflow_metadata")
            error_output: dict[str, Any] = {
                "success": False,
                "error": "Workflow validation failed",
                "validation_errors": errors,
            }
            if workflow_metadata:
                error_output["metadata"] = workflow_metadata
            # Note: Not including metrics since validation fails before execution starts
            click.echo(json.dumps(error_output, indent=2 if verbose else None))
        else:
            click.echo(format_validation_failure(errors, warnings), err=True)
        ctx.exit(1)

    # Warnings are non-blocking, just display them in verbose mode
    if warnings and output_format != "json" and verbose:
        for warning in warnings:
            click.echo(f"⚠️  {warning}", err=True)


def execute_json_workflow(
    ctx: click.Context,
    ir_data: dict[str, Any],
    stdin_data: str | StdinData | None = None,
    output_key: str | None = None,
    execution_params: dict[str, Any] | None = None,
    planner_llm_calls: list[dict[str, Any]] | None = None,
    output_format: str = "text",
    metrics_collector: Any | None = None,
    planner_cache_chunks: list[dict[str, Any]] | None = None,
) -> None:
    """Thin CLI wrapper for workflow execution.

    All logic delegated to WorkflowExecutorService.
    """
    from pflow.core.workflow_manager import WorkflowManager
    from pflow.execution.workflow_execution import execute_workflow

    # Setup execution context
    verbose, auto_repair, metrics_collector = _setup_execution_context(ctx, ir_data, output_format, metrics_collector)

    # Suppress logging in JSON mode (except CRITICAL) to keep output clean
    if output_format == "json":
        logging.getLogger().setLevel(logging.CRITICAL)

    # Check for validate-only flag
    validate_only = ctx.obj.get("validate_only", False)
    if validate_only:
        _handle_validate_only_mode(ctx, ir_data, output_format)
        # Never reaches here - _handle_validate_only_mode calls ctx.exit()

    # Extract additional context values
    workflow_name = ctx.obj.get("workflow_name")
    original_request = ctx.obj.get("workflow_text")  # From planner

    # Prepare execution environment
    cli_output, display, workflow_trace, enhanced_params, effective_verbose = _prepare_execution_environment(
        ctx, ir_data, output_format, verbose, execution_params, planner_llm_calls, planner_cache_chunks
    )

    # Validate before execution (if not using auto-repair)
    # Auto-repair mode handles validation inside execute_workflow() with repair capability
    if not auto_repair:
        _validate_before_execution(ctx, ir_data, enhanced_params, output_format, verbose)

    # Show execution starting
    node_count = len(ir_data.get("nodes", []))
    if verbose and output_format != "json":
        click.echo(f"cli: Starting workflow execution with {node_count} node(s)")
    display.show_execution_start(node_count)

    # Hide PocketFlow warnings in non-verbose mode
    if not verbose:
        warnings.filterwarnings("ignore", message="Flow ends:*", module="pflow.pocketflow")

    try:
        # Get planner model from context for repair service (with smart default)
        from pflow.core.llm_config import get_default_llm_model

        planner_model = ctx.obj.get("planner_model") or get_default_llm_model()

        # Execute workflow with unified function (includes repair capability)
        result = execute_workflow(
            workflow_ir=ir_data,
            execution_params=enhanced_params,
            enable_repair=auto_repair,  # Repair disabled by default, must opt-in
            resume_state=None,  # Fresh execution
            original_request=original_request,
            output=cli_output,
            workflow_manager=WorkflowManager() if workflow_name else None,
            workflow_name=workflow_name,
            stdin_data=stdin_data,
            output_key=output_key,
            metrics_collector=metrics_collector,
            trace_collector=workflow_trace,
            repair_model=planner_model,  # Use same model as planner
        )

        # Save repaired workflow if applicable
        if result.success and result.repaired_workflow_ir:
            _save_repaired_workflow(ctx, result.repaired_workflow_ir)

        # Handle result
        _execute_workflow_and_handle_result(
            ctx=ctx,
            result=result,
            shared_storage=result.shared_after,
            workflow_trace=workflow_trace,
            output_key=output_key,
            ir_data=ir_data,
            output_format=output_format,
            metrics_collector=metrics_collector,
            verbose=verbose,
            display=display,
        )

    except Exception as e:
        from pflow.runtime.compiler import CompilationError

        # Re-raise Click exceptions (Exit, Abort) - don't handle them
        if isinstance(e, click.exceptions.Exit):
            raise

        # Handle compilation errors specially
        if isinstance(e, CompilationError):
            _handle_compilation_error(ctx, e, output_format, verbose, workflow_trace, metrics_collector)

        # Handle other exceptions
        _handle_workflow_exception(
            ctx,
            e,
            workflow_trace,
            output_format,
            metrics_collector,
            result.shared_after if "result" in locals() else {},
            verbose,
        )

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
    model_name = "anthropic/claude-sonnet-4-5"
    try:
        _ = llm.get_model(model_name)
        # The model loaded successfully - LLM is configured
        # Note: model.key may be None when using environment variables, which is fine
    except Exception as model_error:
        # If we can't get the model, API is likely not configured
        if verbose:
            click.echo(f"cli: LLM model check failed: {model_error}", err=True)
        raise ValueError(f"LLM model {model_name} not available") from model_error


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
    cache_planner: bool,
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
        "cache_planner": cache_planner,  # Enable cross-session caching if flag is set
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
    cache_planner: bool,
) -> None:
    """Execute the planner flow and resulting workflow with optional debugging."""
    # Set up planner execution environment
    metrics_collector, debug_context, trace_collector, shared = _setup_planner_execution(
        ctx, raw_input, stdin_data, verbose, cache_planner
    )

    # Resolve planner model with smart detection and error handling
    planner_model = ctx.obj.get("planner_model")
    if planner_model is None:
        from pflow.core.llm_config import get_default_llm_model, get_llm_setup_help

        planner_model = get_default_llm_model()
        if planner_model is None:
            # No LLM keys configured - error at decision point
            click.echo("Error: Cannot plan workflow without LLM configuration\n", err=True)
            click.echo(get_llm_setup_help(), err=True)
            sys.exit(1)

    # Create planner flow with detected/specified model
    planner_flow = create_planner_flow(debug_context=debug_context, model=planner_model)

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


def _extract_planner_cache_chunks(planner_shared: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Extract cache chunks from planner shared store in priority order."""
    # Priority 1: Most complete context (has retry history)
    if accumulated := planner_shared.get("planner_accumulated_blocks"):
        return cast(list[dict[str, Any]], accumulated)

    # Priority 2: Planning context (has execution plan)
    if extended := planner_shared.get("planner_extended_blocks"):
        return cast(list[dict[str, Any]], extended)

    # Priority 3: Base context (minimal but better than nothing)
    if base := planner_shared.get("planner_base_blocks"):
        return cast(list[dict[str, Any]], base)

    # No planner context available
    return None


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
    # Extract cache chunks for repair context
    planner_cache_chunks = _extract_planner_cache_chunks(planner_shared) if planner_shared else None

    # Store execution params for potential repair save (strip internal params)
    from .rerun_display import filter_user_params

    execution_params = planner_output.get("execution_params")
    ctx.obj["execution_params"] = filter_user_params(execution_params)

    execute_json_workflow(
        ctx,
        planner_output["workflow_ir"],
        stdin_data,
        output_key,
        execution_params,  # CRITICAL: Pass params for templates!
        planner_shared.get("__llm_calls__", []) if planner_shared else None,  # Pass planner LLM calls
        ctx.obj.get("output_format", "text"),
        metrics_collector,
        planner_cache_chunks,  # NEW: Pass cache chunks for repair context
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

    # Handle broken pipe gracefully
    # NOTE: Using SIG_IGN instead of SIG_DFL to prevent subprocess SIGPIPE from killing
    # the parent process. When a subprocess doesn't consume all stdin (e.g., shell command
    # that uses 'echo' instead of reading from pipe), SIG_DFL would terminate Python with
    # exit code 141. SIG_IGN allows subprocess.run() to handle this gracefully.
    # See: https://github.com/spinje/pflow/issues/25
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)


def _check_mcp_sync_needed(config_path: Path, registry: Any, servers: list[str]) -> tuple[bool, str]:
    """Check if MCP sync is needed based on config changes.

    Args:
        config_path: Path to MCP configuration file
        registry: Registry instance for metadata storage
        servers: List of configured server names

    Returns:
        Tuple of (needs_sync, current_hash)
    """
    config_mtime = config_path.stat().st_mtime
    last_sync = registry.get_metadata("mcp_last_sync_time", 0)
    last_sync_hash = registry.get_metadata("mcp_servers_hash", "")

    # Calculate current servers hash using SHA256 for security
    current_servers = sorted(servers)
    current_hash = hashlib.sha256(json.dumps(current_servers).encode()).hexdigest()

    # Skip sync if config hasn't changed AND server list is same
    if config_mtime <= last_sync and current_hash == last_sync_hash:
        logger.debug(
            f"MCP config unchanged since last sync (mtime={config_mtime}, last_sync={last_sync}), skipping discovery"
        )
        return False, current_hash

    return True, current_hash


def _clean_old_mcp_entries(registry: Any) -> None:
    """Remove all existing MCP entries from registry for clean sync.

    Args:
        registry: Registry instance to clean
    """
    all_nodes = registry.list_nodes()
    existing_mcp_count = len([n for n in all_nodes if n.startswith("mcp-")])

    if existing_mcp_count > 0:
        # Load full registry including filtered nodes
        nodes = registry.load(include_filtered=True)
        removed = 0
        for node_name in list(nodes.keys()):
            if node_name.startswith("mcp-"):
                del nodes[node_name]
                removed += 1

        if removed > 0:
            registry.save(nodes)
            logger.debug(f"Removed {removed} old MCP entries for clean sync")


def _discover_and_register_servers(
    servers: list[str], discovery: Any, registrar: Any, show_progress: bool, verbose: bool
) -> tuple[int, list[str]]:
    """Discover tools from MCP servers and register them.

    Args:
        servers: List of server names to discover
        discovery: MCPDiscovery instance
        registrar: MCPRegistrar instance
        show_progress: Whether to show progress messages
        verbose: Whether to show verbose output

    Returns:
        Tuple of (total_tools_discovered, failed_servers)
    """
    total_tools = 0
    failed_servers = []

    for server_name in servers:
        try:
            if show_progress and verbose:
                click.echo(f"Discovering tools from MCP server '{server_name}'...", err=True)

            # Discover tools (pass verbose to control stderr output)
            tools = discovery.discover_tools(server_name, verbose=verbose)

            if tools:
                # Register the discovered tools
                registrar.register_tools(server_name, tools)
                total_tools += len(tools)

                if show_progress and verbose:
                    click.echo(f"  ✓ Discovered {len(tools)} tool(s) from {server_name}", err=True)
        except Exception as e:
            logger.debug(f"Failed to discover tools from {server_name}: {e}")
            failed_servers.append(server_name)
            if show_progress and verbose:
                click.echo(f"  ⚠ Failed to connect to {server_name}", err=True)

    return total_tools, failed_servers


def _auto_discover_mcp_servers(ctx: click.Context, verbose: bool) -> None:
    """Smart auto-discovery that only syncs when MCP config changes.

    Checks config file modification time and server list hash to determine
    if sync is needed. This eliminates unnecessary overhead on every pflow run.
    """
    try:
        from pflow.mcp import MCPDiscovery, MCPRegistrar, MCPServerManager
        from pflow.registry import Registry

        # Check if we should show progress messages
        output_controller = _get_output_controller(ctx)
        show_progress = output_controller.is_interactive()

        # Load MCP server configuration
        manager = MCPServerManager()
        config_path = manager.config_path

        # Check if config exists
        if not config_path.exists():
            # No config, nothing to sync
            return

        servers = manager.list_servers()
        if not servers:
            # No servers configured, nothing to do
            return

        # Check if sync is needed
        registry = Registry()
        needs_sync, current_hash = _check_mcp_sync_needed(config_path, registry, servers)

        if not needs_sync:
            return

        # Config changed or first run - do full sync
        if show_progress and not verbose:
            click.echo("🔄 MCP config changed, syncing servers...", err=True)

        # CRITICAL: Remove ALL existing MCP entries first
        # This handles renames cleanly
        _clean_old_mcp_entries(registry)

        # Now discover and register from all servers
        discovery = MCPDiscovery(manager)
        registrar = MCPRegistrar(registry=registry, manager=manager)

        total_tools, failed_servers = _discover_and_register_servers(
            servers, discovery, registrar, show_progress, verbose
        )

        # Update metadata for next run
        registry.set_metadata("mcp_last_sync_time", time.time())
        registry.set_metadata("mcp_servers_hash", current_hash)

        # Show summary
        if show_progress and total_tools > 0 and not verbose:
            click.echo(
                f"✓ Synced {total_tools} MCP tool(s) from {len(servers) - len(failed_servers)} server(s)", err=True
            )

        if show_progress and failed_servers and verbose:
            click.echo(f"⚠ Failed to connect to {len(failed_servers)} server(s): {', '.join(failed_servers)}", err=True)

    except ImportError as e:
        # MCP modules not available
        logger.debug(f"MCP modules not available: {e}")
    except Exception as e:
        # Log auto-discovery failure at debug level - this is optional functionality
        logger.debug(f"Failed to auto-discover MCP servers: {e}")


def _initialize_context(
    ctx: click.Context,
    verbose: bool,
    output_key: str | None,
    output_format: str,
    print_flag: bool,
    trace_enabled: bool,
    trace_planner: bool,
    planner_timeout: int,
    save: bool,
    cache_planner: bool,
    planner_model: str,
    auto_repair: bool,
    no_update: bool,
    validate_only: bool,
) -> None:
    """Initialize the click context with configuration.

    Args:
        ctx: Click context to initialize
        verbose: Verbose mode flag
        output_key: Optional output key
        output_format: Output format (text/json)
        print_flag: Force non-interactive output flag
        trace_enabled: Trace execution flag (enabled by default)
        trace_planner: Trace planner flag
        planner_timeout: Planner timeout in seconds
        save: Save workflow flag
        cache_planner: Enable cross-session caching for planner
        planner_model: LLM model for planning nodes
        auto_repair: Enable automatic workflow repair on failure
        no_update: Save repairs to separate file instead of updating original
        validate_only: Validate workflow without executing
    """
    if ctx.obj is None:
        ctx.obj = {}

    ctx.obj["verbose"] = verbose
    ctx.obj["output_key"] = output_key
    ctx.obj["output_format"] = output_format
    ctx.obj["print_flag"] = print_flag
    ctx.obj["trace"] = trace_enabled
    ctx.obj["trace_planner"] = trace_planner
    ctx.obj["planner_timeout"] = planner_timeout
    ctx.obj["save"] = save
    ctx.obj["cache_planner"] = cache_planner
    # Use smart default if no model specified (will be resolved when needed)
    ctx.obj["planner_model"] = planner_model  # None triggers auto-detection later
    ctx.obj["auto_repair"] = auto_repair
    ctx.obj["no_update"] = no_update
    ctx.obj["validate_only"] = validate_only

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
        if arg in ("--no-trace", "--verbose", "-v", "--planner-timeout", "--output-key", "-o", "--output-format")
    ]
    if misplaced_flags:
        click.echo("cli: Error - CLI flags must come BEFORE the workflow text", err=True)
        click.echo(f"cli: Found misplaced flags: {', '.join(misplaced_flags)}", err=True)
        click.echo("cli: Correct usage examples:", err=True)
        click.echo('cli:   pflow --verbose "analyze this data"', err=True)
        click.echo('cli:   pflow --no-trace "run without tracing"', err=True)
        click.echo('cli: NOT: pflow "create a story" --no-trace', err=True)
        ctx.exit(1)


def _find_stdin_input(workflow_ir: dict[str, Any]) -> str | None:
    """Find the input marked with stdin: true.

    Args:
        workflow_ir: Workflow IR data

    Returns:
        Name of input with stdin: true, or None if no such input exists
    """
    inputs: dict[str, Any] = workflow_ir.get("inputs", {})
    for name, spec in inputs.items():
        if isinstance(spec, dict) and spec.get("stdin") is True:
            return str(name)
    return None


def _extract_stdin_text(stdin_data: str | StdinData | None) -> str | None:
    """Extract text content from stdin data.

    Args:
        stdin_data: Stdin data (string, StdinData, or None)

    Returns:
        Text content if available, None otherwise (for binary/large file/None cases)
    """
    if stdin_data is None:
        return None
    if isinstance(stdin_data, str):
        return stdin_data
    # StdinData object - only extract text_data, not binary or temp file
    if stdin_data.text_data is not None:
        return stdin_data.text_data
    # Binary data or temp file path - do not route
    return None


def _show_stdin_routing_error(ctx: click.Context) -> NoReturn:
    """Display error when stdin cannot be routed to workflow.

    Args:
        ctx: Click context (for exit and output_format)

    Raises:
        SystemExit: Always exits with code 1
    """
    output_format = ctx.obj.get("output_format", "text")
    verbose = ctx.obj.get("verbose", False)

    if output_format == "json":
        workflow_metadata = ctx.obj.get("workflow_metadata")
        error_output: dict[str, Any] = {
            "success": False,
            "error": "Piped input cannot be routed to workflow",
            "validation_errors": [
                'This workflow has no input marked with "stdin": true. '
                'To accept piped data, add "stdin": true to one input declaration.'
            ],
        }
        if workflow_metadata:
            error_output["metadata"] = workflow_metadata
        click.echo(json.dumps(error_output, indent=2 if verbose else None))
    else:
        click.echo("❌ Piped input cannot be routed to workflow", err=True)
        click.echo("", err=True)
        click.echo('   This workflow has no input marked with "stdin": true.', err=True)
        click.echo('   To accept piped data, add "stdin": true to one input declaration.', err=True)
        click.echo("", err=True)
        click.echo("   Example:", err=True)
        click.echo('     "inputs": {', err=True)
        click.echo('       "data": {"type": "string", "required": true, "stdin": true}', err=True)
        click.echo("     }", err=True)
        click.echo("", err=True)
        click.echo('   👉 Add "stdin": true to the input that should receive piped data', err=True)
    ctx.exit(1)


def _output_validation_errors(
    ctx: click.Context,
    errors: list[tuple[str, str, str]],
    error_summary: str = "Validation failed",
) -> NoReturn:
    """Output validation errors respecting output_format.

    Args:
        ctx: Click context (for output_format, verbose, workflow_metadata)
        errors: List of (message, path, suggestion) tuples from prepare_inputs()
        error_summary: High-level error description for JSON mode

    Raises:
        SystemExit: Always exits with code 1
    """
    output_format = ctx.obj.get("output_format", "text")
    verbose = ctx.obj.get("verbose", False)

    if output_format == "json":
        workflow_metadata = ctx.obj.get("workflow_metadata")
        # Convert tuple errors to structured format
        validation_errors = []
        for msg, path, suggestion in errors:
            error_entry: dict[str, str] = {"message": msg}
            if path and path != "root":
                error_entry["path"] = path
            if suggestion:
                error_entry["suggestion"] = suggestion
            validation_errors.append(error_entry)

        error_output: dict[str, Any] = {
            "success": False,
            "error": error_summary,
            "validation_errors": validation_errors,
        }
        if workflow_metadata:
            error_output["metadata"] = workflow_metadata
        click.echo(json.dumps(error_output, indent=2 if verbose else None))
    else:
        for msg, path, suggestion in errors:
            click.echo(f"❌ {msg}", err=True)
            if path and path != "root":
                click.echo(f"   At: {path}", err=True)
            if suggestion:
                click.echo(f"   👉 {suggestion}", err=True)
    ctx.exit(1)


def _route_stdin_to_params(
    ctx: click.Context,
    stdin_data: str | StdinData | None,
    workflow_ir: dict[str, Any],
    params: dict[str, Any],
) -> None:
    """Route stdin content to the appropriate workflow input parameter.

    Args:
        ctx: Click context (for exit on error)
        stdin_data: Stdin data (string, StdinData, or None)
        workflow_ir: Workflow IR data
        params: Parameters dict to modify in place

    Side Effects:
        Modifies params dict if stdin should be routed.
        Calls ctx.exit(1) if stdin is piped but no target input exists.
    """
    stdin_text = _extract_stdin_text(stdin_data)
    if stdin_text is None:
        # Check if stdin was binary/large file (detected but not routable)
        if isinstance(stdin_data, StdinData) and (stdin_data.binary_data or stdin_data.temp_path):
            click.echo("⚠️  Stdin contains binary or large data", err=True)
            click.echo("   Binary/large data is not automatically routed to workflow inputs.", err=True)
            click.echo("   Consider using a file path parameter instead.", err=True)
            click.echo("", err=True)
        return

    # Stdin has text content - try to route it
    target_input = _find_stdin_input(workflow_ir)

    if target_input is None:
        # No stdin: true input - error if stdin is piped
        _show_stdin_routing_error(ctx)

    # Route stdin to target input (unless CLI override exists)
    if target_input not in params:
        params[target_input] = stdin_text


def _load_settings_env() -> dict[str, str]:
    """Load environment variables from settings.

    Returns:
        Dict of environment variables from settings, empty dict on error
    """
    try:
        from pflow.core.settings import SettingsManager

        manager = SettingsManager()
        settings = manager.load()
        return settings.env
    except Exception as e:
        # Non-fatal - continue with empty settings
        logger.warning(f"Failed to load settings.env: {e}")
        return {}


def _validate_and_prepare_workflow_params(
    ctx: click.Context,
    workflow_ir: dict[str, Any],
    remaining_args: tuple[str, ...],
    stdin_data: str | StdinData | None = None,
) -> dict[str, Any]:
    """Validate workflow parameters, route stdin, and apply defaults.

    Args:
        ctx: Click context
        workflow_ir: Workflow IR data
        remaining_args: Command line arguments for parameters
        stdin_data: Optional stdin data (string, StdinData, or None)

    Returns:
        Validated and prepared parameters dictionary

    Raises:
        SystemExit: If validation errors occur (including stdin routing errors)
    """
    # Parse parameters
    params = parse_workflow_params(remaining_args)

    # Validate parameter keys (now more permissive than Python identifiers)
    invalid_keys = [k for k in params if not is_valid_parameter_name(k)]
    if invalid_keys:
        click.echo(f"❌ Invalid parameter name(s): {', '.join(invalid_keys)}", err=True)
        click.echo("   👉 Parameter names cannot contain shell special characters ($, |, >, <, &, ;, etc.)", err=True)
        ctx.exit(1)

    # Route stdin to workflow input marked with stdin: true
    _route_stdin_to_params(ctx, stdin_data, workflow_ir, params)

    # Skip input validation if --validate-only (handled separately with dummy values)
    validate_only = ctx.obj.get("validate_only", False)
    if not validate_only:
        from pflow.runtime.workflow_validator import prepare_inputs

        settings_env = _load_settings_env()
        errors, defaults, env_param_names = prepare_inputs(workflow_ir, params, settings_env=settings_env)
        if errors:
            _output_validation_errors(ctx, errors, "Input validation failed")

        # Apply defaults
        if defaults:
            params.update(defaults)

        # Store env param names as internal param (for consistency with compiler.py)
        if env_param_names:
            params["__env_param_names__"] = list(env_param_names)

    return params


def _show_workflow_help(
    first_arg: str,
    workflow_ir: dict[str, Any],
    source: str | None,
) -> None:
    """Display workflow help information.

    Args:
        first_arg: First workflow argument (name or path)
        workflow_ir: Workflow IR data
        source: Workflow source ("saved", "file", etc.)
    """
    # Use shared formatter (same as workflow describe command)
    from pflow.execution.formatters.workflow_describe_formatter import format_workflow_interface

    # Build metadata structure expected by formatter
    name = os.path.basename(first_arg) if "/" in first_arg else first_arg
    metadata = {"ir": workflow_ir}

    # Add description if present
    if "description" in workflow_ir:
        metadata["description"] = workflow_ir["description"]

    # Display workflow information header
    click.echo(f"\nWorkflow: {name}")
    if source == "saved":
        click.echo("Source: Saved workflow")
    else:
        click.echo(f"Source: {first_arg}")
    click.echo()  # Empty line before formatted output

    # Use formatter for consistent display
    formatted = format_workflow_interface(name, metadata)
    click.echo(formatted)


def _setup_workflow_execution(
    ctx: click.Context,
    first_arg: str,
    source: str | None,
    output_format: str,
) -> Any | None:
    """Setup workflow execution context and metrics.

    Args:
        ctx: Click context
        first_arg: First workflow argument (name or path)
        source: Workflow source ("saved", "file", etc.)
        output_format: Output format

    Returns:
        Metrics collector if JSON output, otherwise None
    """
    # Create metrics collector if needed
    metrics_collector = None
    if output_format == "json":
        from pflow.core.metrics import MetricsCollector

        metrics_collector = MetricsCollector()

    # Set workflow metadata based on source
    # This ensures proper action field in JSON output
    if source == "saved":
        # Workflow from registry - it's being reused
        ctx.obj["workflow_metadata"] = _create_workflow_metadata(first_arg, "reused")
    else:
        # Workflow from file - it's unsaved
        ctx.obj["workflow_metadata"] = _create_workflow_metadata(first_arg, "unsaved")

    # Store workflow source and name for potential repair saving
    ctx.obj["workflow_source"] = source

    if source == "file" and first_arg.endswith(".json"):
        ctx.obj["source_file_path"] = first_arg
    elif source == "saved":
        # Extract clean workflow name (strip any .json extension if present)
        workflow_name = first_arg.replace(".json", "") if first_arg.endswith(".json") else first_arg
        ctx.obj["workflow_name"] = workflow_name

    return metrics_collector


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

    # Check for --help request
    if remaining_args and "--help" in remaining_args:
        _show_workflow_help(first_arg, workflow_ir, source)
        return True

    # Validate and prepare parameters (including stdin routing)
    params = _validate_and_prepare_workflow_params(ctx, workflow_ir, remaining_args, stdin_data)

    # Store execution params for potential repair save (strip internal params)
    from .rerun_display import filter_user_params

    ctx.obj["execution_params"] = filter_user_params(params)

    # Show what we're doing if verbose (but not in JSON mode)
    if verbose and output_format != "json":
        if source == "saved":
            click.echo(f"cli: Loading workflow '{first_arg}' from registry")
        else:
            click.echo(f"cli: Loading workflow from file: {first_arg}")
        if params:
            click.echo(f"cli: With parameters: {params}")

    # Setup workflow execution context
    metrics_collector = _setup_workflow_execution(ctx, first_arg, source, output_format)

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
    cache_planner: bool,
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
            ctx, raw_input, stdin_data, output_key, verbose, create_planner_flow, trace, planner_timeout, cache_planner
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
        # Special case: --help is allowed with workflow names
        if remaining_args and len(remaining_args) > 0 and remaining_args[0] == "--help":
            return True
        # Check if followed by other CLI syntax
        return not (
            remaining_args and ("=>" in remaining_args or any(arg.startswith("--") for arg in remaining_args[:2]))
        )

    # Don't treat single words as workflow names unless they have params
    # This prevents false positives with CLI node names like "node1", "read-file", etc.
    return False


def _install_anthropic_model_if_needed(verbose: bool) -> None:
    """Install Anthropic model wrapper for planning models unless in tests."""
    import os

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        from pflow.planning.utils.anthropic_llm_model import install_anthropic_model

        install_anthropic_model()
        if verbose:
            click.echo("cli: Using Anthropic SDK for planning models", err=True)


def _inject_settings_env_vars() -> None:
    """Inject API keys from pflow settings into environment.

    This allows API keys stored via 'pflow settings set-env' to be available
    to the llm library and other tools that read from os.environ.

    Called early in CLI startup, before any LLM operations.
    Skipped in test environment to avoid test pollution.
    """
    from pflow.core.llm_config import inject_settings_env_vars

    inject_settings_env_vars()


def _try_execute_named_workflow(
    ctx: click.Context,
    workflow: tuple[str, ...],
    stdin_data: StdinData | str | None,
    output_key: str | None,
    output_format: str,
    verbose: bool,
) -> bool:
    """Try to execute workflow as a named/file workflow.

    Returns True if workflow was handled (either executed or error shown), False otherwise.
    """
    if not workflow:
        return False

    first_arg = workflow[0]
    if not is_likely_workflow_name(first_arg, workflow[1:]):
        return False

    # Resolve once to avoid duplicate calls
    workflow_ir, source = resolve_workflow(first_arg)
    # Try to execute as named workflow
    if _handle_named_workflow(
        ctx, first_arg, workflow[1:], stdin_data, output_key, output_format, verbose, workflow_ir, source
    ):
        return True
    # If not found, handle the error
    _handle_workflow_not_found(ctx, first_arg, source or "unknown")
    return True  # We handled it by showing an error


def _is_valid_natural_language_input(workflow: tuple[str, ...]) -> bool:
    """Determine whether the workflow tuple is suitable for planner execution."""
    if len(workflow) != 1:
        return False

    text = workflow[0]
    if " " not in text:
        return False

    return not _is_path_like(text)


def _handle_invalid_planner_input(ctx: click.Context, workflow: tuple[str, ...]) -> None:
    """Emit user guidance for workflows that cannot be handled by the planner."""
    if not workflow:
        click.echo("❌ No workflow specified.", err=True)
        click.echo("", err=True)
        click.echo("Usage:", err=True)
        click.echo('  pflow "natural language prompt"    # Use quotes for planning', err=True)
        click.echo("  pflow workflow.json                 # Run workflow from file", err=True)
        click.echo("  pflow my-workflow                   # Run saved workflow", err=True)
        click.echo("  pflow workflow list                 # List saved workflows", err=True)
        ctx.exit(1)

    if len(workflow) == 1:
        word = workflow[0]
        click.echo(f"❌ '{word}' is not a known workflow or command.", err=True)
        click.echo("", err=True)
        click.echo("Did you mean:", err=True)
        click.echo(f'  pflow "{word} <rest of prompt>"    # Use quotes for natural language', err=True)
        click.echo("  pflow workflow list                 # List saved workflows", err=True)
        ctx.exit(1)

    joined = " ".join(workflow)
    click.echo(f"❌ Invalid input: {workflow[0]} {workflow[1]} ...", err=True)
    click.echo("", err=True)
    click.echo("Natural language prompts must be quoted:", err=True)
    click.echo(f'  pflow "{joined}"', err=True)
    click.echo("", err=True)
    click.echo("Or use a workflow:", err=True)
    click.echo("  pflow workflow.json", err=True)
    click.echo("  pflow my-workflow param=value", err=True)
    ctx.exit(1)


def _validate_and_join_workflow_input(workflow: tuple[str, ...]) -> str:
    """Join workflow tokens and validate constraints for planner execution.

    Args:
        workflow: Raw workflow arguments tuple

    Returns:
        Joined workflow string

    Raises:
        ClickException: If input is empty or exceeds size limits
    """
    raw_input = " ".join(workflow) if workflow else ""

    if not raw_input:
        raise click.ClickException("cli: No workflow provided. Use --help to see usage examples.")

    # Validate input length (100KB limit)
    if len(raw_input) > 100 * 1024:
        raise click.ClickException(
            "cli: Workflow input too large (max 100KB). Consider breaking it into smaller workflows."
        )

    return raw_input


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
@click.option(
    "--no-trace",
    is_flag=True,
    help="Disable workflow execution trace saving (enabled by default)",
)
@click.option("--trace-planner", is_flag=True, help="Save planner execution trace to file")
@click.option("--planner-timeout", type=int, default=60, help="Timeout for planner execution (seconds)")
@click.option("--save/--no-save", default=True, help="Save generated workflow (default: save)")
@click.option(
    "--cache-planner",
    is_flag=True,
    help="Enable cross-session caching for planner LLM calls (reduces cost for repeated runs)",
)
@click.option(
    "--planner-model",
    default=None,  # Will auto-detect based on available API keys
    help="LLM model for planning (default: auto-detect). Supports Anthropic, OpenAI, Gemini, etc.",
)
@click.option("--auto-repair", is_flag=True, help="Enable automatic workflow repair on failure")
@click.option(
    "--no-update", is_flag=True, help="Save repairs to separate .repaired.json file instead of updating original"
)
@click.option("--validate-only", is_flag=True, help="Validate workflow without executing")
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def workflow_command(
    ctx: click.Context,
    version: bool,
    verbose: bool,
    output_key: str | None,
    output_format: str,
    print_flag: bool,
    no_trace: bool,
    trace_planner: bool,
    planner_timeout: int,
    save: bool,
    cache_planner: bool,
    planner_model: str,
    auto_repair: bool,
    no_update: bool,
    validate_only: bool,
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
      registry      Manage node registry (list, search, add custom nodes)
      workflow      Manage saved workflows (list, describe)
      mcp           Manage MCP server connections
      instructions  AI agents: Start here for usage guide and workflow discovery

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
      - AI agents: Always run 'pflow instructions usage' FIRST for agent-optimized guidance
      - Run 'pflow COMMAND --help' for more information on a command
    """
    # Handle version flag
    if version:
        click.echo("pflow version 0.0.1")
        ctx.exit(0)

    # Setup signal handlers
    _setup_signals()

    # NOTE: Logging already configured in main_wrapper.py before routing
    # No need to configure again here

    # Suppress WARNING logs in JSON mode to prevent stdout contamination
    # Only ERROR and CRITICAL logs will be shown
    original_log_levels = {}
    if output_format == "json":
        # Save and update root logger level
        root_logger = logging.getLogger()
        original_log_levels["root"] = root_logger.level
        root_logger.setLevel(logging.ERROR)

        # Also update pflow logger level (child loggers inherit from this)
        pflow_logger = logging.getLogger("pflow")
        original_log_levels["pflow"] = pflow_logger.level
        pflow_logger.setLevel(logging.ERROR)

    try:
        # Inject API keys from pflow settings into environment
        # This must happen early, before any LLM operations
        _inject_settings_env_vars()

        # Initialize context with configuration
        trace_enabled = not no_trace
        _initialize_context(
            ctx,
            verbose,
            output_key,
            output_format,
            print_flag,
            trace_enabled,
            trace_planner,
            planner_timeout,
            save,
            cache_planner,
            planner_model,
            auto_repair,
            no_update,
            validate_only,
        )

        # Auto-discover and sync MCP servers
        # Only show MCP output if verbose AND not in print mode or JSON output
        print_flag = ctx.obj.get("print_flag", False)
        output_format = ctx.obj.get("output_format", "text")
        effective_verbose = verbose and not print_flag and output_format != "json"
        _auto_discover_mcp_servers(ctx, effective_verbose)

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

        # Try to handle as named/file workflow first
        if _try_execute_named_workflow(ctx, workflow, stdin_data, output_key, output_format, verbose):
            return

        if not _is_valid_natural_language_input(workflow):
            _handle_invalid_planner_input(ctx, workflow)
            return

        # Validate input for natural language processing
        raw_input = _validate_and_join_workflow_input(workflow)

        # Install Anthropic model wrapper ONLY for planner path
        # This provides caching, thinking tokens, and structured output features
        # that the planner requires. File/saved workflows use standard llm library.
        _install_anthropic_model_if_needed(verbose)

        # Multi-word or parameterized input: planner by design
        cache_planner = ctx.obj.get("cache_planner", False)
        _execute_with_planner(
            ctx, raw_input, stdin_data, output_key, verbose, "args", trace_enabled, planner_timeout, cache_planner
        )
    finally:
        # Restore original logging levels if we changed them
        if "root" in original_log_levels:
            logging.getLogger().setLevel(original_log_levels["root"])
        if "pflow" in original_log_levels:
            logging.getLogger("pflow").setLevel(original_log_levels["pflow"])


# Alias for backward compatibility with tests that import main directly
# Tests use: from pflow.cli.main import main
# This avoids breaking existing test infrastructure
main = workflow_command
