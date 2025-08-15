"""Main CLI entry point for pflow."""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

import click

from pflow.core import StdinData, ValidationError, validate_ir
from pflow.core.exceptions import WorkflowExistsError, WorkflowNotFoundError, WorkflowValidationError
from pflow.core.shell_integration import (
    determine_stdin_mode,
    read_stdin_enhanced,
)
from pflow.core.shell_integration import (
    read_stdin as read_stdin_content,
)
from pflow.core.workflow_manager import WorkflowManager
from pflow.registry import Registry
from pflow.runtime import CompilationError, compile_ir_to_flow


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


def read_workflow_from_file(file_path: str) -> str:
    """Read workflow from file with proper error handling."""
    try:
        return Path(file_path).read_text().strip()
    except FileNotFoundError:
        raise click.ClickException(f"cli: File not found: '{file_path}'. Check the file path and try again.") from None
    except PermissionError:
        raise click.ClickException(
            f"cli: Permission denied reading file: '{file_path}'. Check file permissions."
        ) from None
    except UnicodeDecodeError:
        raise click.ClickException(f"cli: Unable to read file: '{file_path}'. File must be valid UTF-8 text.") from None


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


def _determine_workflow_source(
    file: str | None, workflow: tuple[str, ...], stdin_content: str | None
) -> tuple[str, str]:
    """Determine workflow source based on inputs.

    Returns:
        Tuple of (workflow_content, source)
    """
    if file:
        return read_workflow_from_file(file), "file"
    elif stdin_content and determine_stdin_mode(stdin_content) == "workflow":
        if workflow:
            raise click.ClickException(
                "cli: Cannot use stdin input when command arguments are provided. Use either piped input OR command arguments."
            )
        return stdin_content, "stdin"
    else:
        return " ".join(workflow), "args"


def _determine_stdin_data(
    source: str,
    workflow: tuple[str, ...],
    file: str | None,
    stdin_content: str | None,
    enhanced_stdin: StdinData | None,
) -> str | StdinData | None:
    """Determine stdin data based on workflow source.

    Returns:
        stdin_data (string, StdinData, or None)
    """
    if source == "file":
        # When reading from file, any stdin is data
        return stdin_content or enhanced_stdin

    if source == "stdin":
        # Workflow came from stdin, no separate data
        return None

    if source != "args":
        return None

    # Workflow from args, stdin is data if present
    if stdin_content and determine_stdin_mode(stdin_content) == "data":
        if not workflow:
            raise click.ClickException(
                "cli: Stdin contains data but no workflow specified. Use --file or provide a workflow name/command."
            )
        return stdin_content

    if enhanced_stdin and not workflow and not file:
        raise click.ClickException(
            "cli: Binary/large stdin data received but no workflow specified. Use --file or provide a workflow name."
        )

    return enhanced_stdin


def _are_all_params(workflow_args: tuple[str, ...]) -> bool:
    """Check if all workflow arguments are key=value parameters.

    Args:
        workflow_args: Tuple of command line arguments

    Returns:
        True if all args are parameters, False otherwise
    """
    if not workflow_args:
        return True

    # Parameters must contain '=' but not be CLI operators
    return all("=" in arg and not arg.startswith("--") and arg != "=>" for arg in workflow_args)


def get_input_source(file: str | None, workflow: tuple[str, ...]) -> tuple[str, str, str | StdinData | None]:
    """Determine input source and read workflow input.

    Returns:
        Tuple of (workflow_content, source, stdin_data)
        stdin_data can be a string (backward compat), StdinData object, or None
    """
    # Check if all workflow args are parameters (key=value) when both file and workflow are provided
    if file and workflow and not _are_all_params(workflow):
        # Has non-parameter args - this is an error
        raise click.ClickException(
            "cli: Cannot mix --file with workflow commands. You can only pass parameters (key=value) with --file."
        )
    # If we get here with both file and workflow, workflow contains only parameters,
    # which is allowed. The parameters will be extracted later by _get_file_execution_params

    # Read stdin data
    stdin_content, enhanced_stdin = _read_stdin_data()

    # Determine workflow source
    workflow_content, source = _determine_workflow_source(file, workflow, stdin_content)

    # Determine stdin data based on workflow source
    stdin_data = _determine_stdin_data(source, workflow, file, stdin_content, enhanced_stdin)

    return workflow_content, source, stdin_data


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
) -> bool:
    """Handle output from workflow execution.

    Args:
        shared_storage: The shared store after execution
        output_key: User-specified output key (--output-key flag)
        workflow_ir: The workflow IR (to check declared outputs)
        verbose: Whether to show verbose output
        output_format: Output format - "text" or "json"

    Returns:
        True if output was produced, False otherwise.
    """
    if output_format == "json":
        return _handle_json_output(shared_storage, output_key, workflow_ir, verbose)
    else:  # text format (default)
        return _handle_text_output(shared_storage, output_key, workflow_ir, verbose)


def _handle_text_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
) -> bool:
    """Handle text formatted output (current behavior).

    Returns the first matching output as plain text.
    """
    # User-specified key takes priority
    if output_key:
        if output_key in shared_storage:
            return safe_output(shared_storage[output_key])
        click.echo(f"cli: Warning - output key '{output_key}' not found in shared store", err=True)
        return False

    # Check workflow-declared outputs
    if _try_declared_outputs(shared_storage, workflow_ir, verbose):
        return True

    # Fall back to auto-detect from common keys (backward compatibility)
    for key in ["response", "output", "result", "text"]:
        if key in shared_storage:
            return safe_output(shared_storage[key])

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

    # Try each declared output in order
    for output_name in declared_outputs:
        if output_name in shared_storage:
            # Found a declared output! Print it
            value = shared_storage[output_name]

            # Optional: Add context about what we're outputting
            if verbose:
                output_desc = declared_outputs[output_name].get("description", "")
                if output_desc:
                    click.echo(f"cli: Output '{output_name}': {output_desc}", err=True)

            return safe_output(value)

    # If workflow declares outputs but none are in shared store, warn in verbose mode
    if verbose:
        expected = ", ".join(declared_outputs.keys())
        click.echo(f"cli: Warning - workflow declares outputs [{expected}] but none found in shared store", err=True)

    return False


def _handle_json_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
) -> bool:
    """Handle JSON formatted output.

    Returns all declared outputs or specified key as JSON.
    """
    result = _collect_json_outputs(shared_storage, output_key, workflow_ir, verbose)
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
        elif verbose:
            # Still output empty JSON, but warn
            click.echo(f"cli: Warning - output key '{output_key}' not found in shared store", err=True)

    elif workflow_ir and "outputs" in workflow_ir and workflow_ir["outputs"]:
        # Collect ALL declared outputs
        declared = workflow_ir["outputs"]
        found_any = False

        for output_name in declared:
            if output_name in shared_storage:
                result[output_name] = shared_storage[output_name]
                found_any = True

        if not found_any and verbose:
            expected = list(declared.keys())
            click.echo(f"cli: Warning - no declared outputs found {expected}", err=True)

    else:
        # Fallback: Use first matching hardcoded key for consistency
        for key in ["response", "output", "result", "text"]:
            if key in shared_storage:
                result[key] = shared_storage[key]
                break  # Only first for consistency with text format

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


def _prompt_workflow_save(ir_data: dict[str, Any]) -> None:
    """Prompt user to save workflow after execution.

    Args:
        ir_data: The workflow IR data to save
    """
    save_response = click.prompt("\nSave this workflow? (y/n)", type=str, default="n").lower()
    if save_response != "y":
        return

    workflow_manager = WorkflowManager()

    # Loop until successful save or user cancels
    while True:
        # Get workflow name
        workflow_name = click.prompt("Workflow name", type=str)

        # Get optional description
        description = click.prompt("Description (optional)", default="", type=str)

        try:
            # Save the workflow
            saved_path = workflow_manager.save(workflow_name, ir_data, description)
            click.echo(f"\n✅ Workflow saved to: {saved_path}")
            break  # Success, exit loop
        except WorkflowExistsError:
            click.echo(f"\n❌ Error: A workflow named '{workflow_name}' already exists.")
            # Offer to use a different name
            retry = click.prompt("Try with a different name? (y/n)", type=str, default="n").lower()
            if retry != "y":
                break  # User declined to retry, exit loop
            # Continue loop to try again
        except WorkflowValidationError as e:
            click.echo(f"\n❌ Error: Invalid workflow name: {e!s}")
            break  # Invalid name, don't retry
        except Exception as e:
            click.echo(f"\n❌ Error saving workflow: {e!s}")
            break  # Other error, don't retry


def _prepare_shared_storage(
    execution_params: dict[str, Any] | None,
    stdin_data: str | StdinData | None,
    verbose: bool,
) -> dict[str, Any]:
    """Prepare shared storage with execution params and stdin data.

    Args:
        execution_params: Optional parameters from planner for template resolution
        stdin_data: Optional stdin data to inject
        verbose: Whether to show verbose output

    Returns:
        Prepared shared storage dictionary
    """
    shared_storage: dict[str, Any] = {}

    # Inject execution parameters from planner (for template resolution)
    if execution_params:
        shared_storage.update(execution_params)
        if verbose:
            click.echo(f"cli: Injected {len(execution_params)} execution parameters into shared storage")

    # Inject stdin data if present (may override execution params)
    _inject_stdin_data(shared_storage, stdin_data, verbose)

    return shared_storage


def execute_json_workflow(
    ctx: click.Context,
    ir_data: dict[str, Any],
    stdin_data: str | StdinData | None = None,
    output_key: str | None = None,
    execution_params: dict[str, Any] | None = None,
    output_format: str = "text",
) -> None:
    """Execute a JSON workflow if it's valid.

    Args:
        ctx: Click context
        ir_data: Parsed workflow IR data
        stdin_data: Optional stdin data (string or StdinData) to inject into shared storage
        output_key: Optional key to output from shared storage after execution
        execution_params: Optional parameters from planner for template resolution
        output_format: Output format - "text" (default) or "json"
    """
    # Check if it's valid JSON with workflow structure
    if not (isinstance(ir_data, dict) and "nodes" in ir_data and "ir_version" in ir_data):
        # Valid JSON but not a workflow - treat as text
        click.echo(f"Collected workflow from {ctx.obj['input_source']}: {ctx.obj['raw_input']}")
        return

    # Load registry (with helpful error if missing)
    registry = Registry()
    if not registry.registry_path.exists():
        click.echo("cli: Error - Node registry not found.", err=True)
        click.echo("cli: Run 'python scripts/populate_registry.py' to populate the registry.", err=True)
        click.echo("cli: Note: This is temporary until 'pflow registry' commands are implemented.", err=True)
        ctx.exit(1)

    # Validate IR
    validate_ir(ir_data)

    # Compile to Flow (with execution_params for template resolution)
    flow = compile_ir_to_flow(ir_data, registry, initial_params=execution_params)

    # Show verbose execution info if requested
    verbose = ctx.obj.get("verbose", False)
    if verbose:
        node_count = len(ir_data.get("nodes", []))
        click.echo(f"cli: Starting workflow execution with {node_count} node(s)")

    # Prepare shared storage with params and stdin
    shared_storage = _prepare_shared_storage(execution_params, stdin_data, verbose)

    try:
        result = flow.run(shared_storage)

        # Check if execution resulted in error
        if result and isinstance(result, str) and result.startswith("error"):
            click.echo("cli: Workflow execution failed - Node returned error action", err=True)
            click.echo("cli: Check node output above for details", err=True)
            ctx.exit(1)
        else:
            if verbose:
                click.echo("cli: Workflow execution completed")

            # Check for output from shared store
            output_produced = _handle_workflow_output(shared_storage, output_key, ir_data, verbose, output_format)

            # Only show success message if we didn't produce output
            if not output_produced:
                click.echo("Workflow executed successfully")

            # Offer to save the workflow (only if not from a file and in interactive mode)
            if ctx.obj.get("input_source") != "file" and sys.stdin.isatty():
                _prompt_workflow_save(ir_data)
    except (click.ClickException, SystemExit):
        # Let Click exceptions and exits propagate normally
        raise
    except Exception as e:
        click.echo(f"cli: Workflow execution failed - {e}", err=True)
        click.echo("cli: This may indicate a bug in the workflow or nodes", err=True)
        ctx.exit(1)
    finally:
        # Clean up temp files if any
        _cleanup_temp_files(stdin_data, verbose)


def _get_file_execution_params(ctx: click.Context) -> dict[str, Any] | None:
    """Get execution parameters from workflow arguments when using --file."""
    if ctx.obj.get("input_source") != "file":
        return None

    # Get the workflow tuple from the context (it's in the same context, not parent)
    workflow_args = ctx.params.get("workflow", ())

    # If not in current context, try parent (for compatibility)
    if not workflow_args and ctx.parent and hasattr(ctx.parent, "params"):
        workflow_args = ctx.parent.params.get("workflow", ())

    if not workflow_args:
        return None

    # Parse parameters from workflow arguments
    execution_params = parse_workflow_params(workflow_args)
    if execution_params and ctx.obj.get("verbose"):
        click.echo(f"cli: With parameters: {execution_params}")

    return execution_params


def _looks_like_json_attempt(content: str) -> bool:
    """Check if content appears to be an attempt at JSON (vs natural language).

    Args:
        content: The content to check

    Returns:
        True if content looks like attempted JSON, False otherwise
    """
    # Strip whitespace
    trimmed = content.strip()

    # Check for JSON-like start characters
    if trimmed.startswith("{") or trimmed.startswith("["):
        return True

    # Check if it contains JSON structure patterns (but not at the start)
    # This catches cases where there might be whitespace or comments before the JSON
    return '"ir_version"' in trimmed or '"nodes"' in trimmed


def _format_json_syntax_error(raw_input: str, error: json.JSONDecodeError, ctx: click.Context) -> None:
    """Format and display a helpful JSON syntax error message.

    Args:
        raw_input: The raw input string that failed to parse
        error: The JSON decode error
        ctx: Click context for exiting
    """
    click.echo("cli: Invalid JSON syntax in file", err=True)
    click.echo(f"cli: Error at line {error.lineno}, column {error.colno}: {error.msg}", err=True)

    # Show the problematic line with a pointer to the error location
    lines = raw_input.split("\n")
    if 0 < error.lineno <= len(lines):
        problem_line = lines[error.lineno - 1]
        # Truncate long lines for display
        if len(problem_line) > 80:
            if error.colno and error.colno <= 80:
                problem_line = problem_line[:80] + "..."
            else:
                # Try to show context around the error
                start = max(0, error.colno - 40) if error.colno else 0
                problem_line = "..." + problem_line[start : start + 77] + "..."

        click.echo(f"cli: Line {error.lineno}: {problem_line}", err=True)

        # Show pointer to error column if available
        if error.colno:
            # Adjust pointer position if line was truncated
            pointer_pos = error.colno - 1
            if len(lines[error.lineno - 1]) > 80 and error.colno > 80:
                pointer_pos = min(40, error.colno - 1)  # Adjusted for truncation
            spaces = " " * (len(f"cli: Line {error.lineno}: ") + pointer_pos)
            click.echo(f"{spaces}^", err=True)

    click.echo("cli: Fix the JSON syntax error and try again.", err=True)
    ctx.exit(1)


def _parse_and_validate_json_workflow(raw_input: str) -> tuple[bool, dict[str, Any] | None]:
    """Try to parse JSON and check if it's a valid workflow structure.

    Args:
        raw_input: The raw input string to parse

    Returns:
        Tuple of (is_valid_json_workflow, parsed_data)
        - (True, data) if valid JSON workflow
        - (False, data) if valid JSON but not a workflow
        - (False, None) if not valid JSON
    """
    try:
        # Try to parse as JSON
        ir_data = json.loads(raw_input)

        # Check if it's actually a workflow JSON
        if isinstance(ir_data, dict) and "nodes" in ir_data and "ir_version" in ir_data:
            return True, ir_data
        else:
            # Valid JSON but not a workflow
            return False, ir_data

    except json.JSONDecodeError:
        # Not valid JSON
        return False, None


def _execute_json_workflow_from_file(
    ctx: click.Context, ir_data: dict[str, Any], stdin_data: str | StdinData | None
) -> None:
    """Execute a JSON workflow from file input, handling all exceptions.

    Args:
        ctx: Click context
        ir_data: Parsed workflow IR data
        stdin_data: Optional stdin data
    """
    try:
        # Parse parameters from remaining workflow arguments if using --file
        execution_params = _get_file_execution_params(ctx)

        execute_json_workflow(
            ctx,
            ir_data,
            stdin_data,
            ctx.obj.get("output_key"),
            execution_params,
            ctx.obj.get("output_format", "text"),
        )
        return  # Success - exit normally

    except ValidationError as e:
        # Workflow validation failed - show error and exit
        click.echo(f"cli: Invalid workflow - {e.message}", err=True)
        if hasattr(e, "path") and e.path:
            click.echo(f"cli: Error at: {e.path}", err=True)
        if hasattr(e, "suggestion") and e.suggestion:
            click.echo(f"cli: Suggestion: {e.suggestion}", err=True)
        ctx.exit(1)

    except CompilationError as e:
        # Compilation failed - show error and exit
        click.echo(f"cli: Compilation failed - {e}", err=True)
        ctx.exit(1)

    except (click.ClickException, SystemExit):
        # Let Click exceptions and exits propagate normally
        raise

    except Exception as e:
        # Execution error - DO NOT fall back to planner for valid JSON
        click.echo(f"cli: Workflow execution error - {e}", err=True)
        click.echo("cli: This may indicate a bug in the workflow or nodes", err=True)
        ctx.exit(1)


def process_file_workflow(ctx: click.Context, raw_input: str, stdin_data: str | StdinData | None = None) -> None:
    """Process file-based workflow, handling JSON and errors.

    Args:
        ctx: Click context
        raw_input: Raw workflow content
        stdin_data: Optional stdin data to pass to workflow
    """
    # Try to parse as JSON workflow
    is_json_workflow, ir_data = _parse_and_validate_json_workflow(raw_input)

    if is_json_workflow and ir_data:
        # Execute JSON workflow
        _execute_json_workflow_from_file(ctx, ir_data, stdin_data)
    else:
        # Not a valid workflow JSON - determine how to handle it
        if _looks_like_json_attempt(raw_input) and ir_data is None:
            # Looks like JSON but failed to parse - show syntax error
            try:
                json.loads(raw_input)
            except json.JSONDecodeError as e:
                _format_json_syntax_error(raw_input, e, ctx)
                # _format_json_syntax_error calls ctx.exit(1), so we won't reach here

        # If we get here, it's either:
        # 1. Valid JSON but not a workflow (ir_data is not None)
        # 2. Natural language (doesn't look like JSON)
        # In both cases, use the planner

        if ir_data is not None and ctx.obj.get("verbose"):
            # Valid JSON but not a workflow
            click.echo("cli: File contains valid JSON but not a workflow structure, using planner")
        elif ctx.obj.get("verbose"):
            # Not JSON at all
            click.echo("cli: File contains natural language (not JSON), using planner")

        # Use planner for natural language or non-workflow JSON
        # input_source should be set by main function before calling process_file_workflow
        source = ctx.obj.get("input_source", "file")  # Default to "file" as fallback
        _execute_with_planner(
            ctx,
            raw_input,
            stdin_data,
            ctx.obj.get("output_key"),
            ctx.obj.get("verbose"),
            source,
            ctx.obj.get("trace", False),
            ctx.obj.get("planner_timeout", 60),
        )


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


def _save_trace_if_needed(trace_collector: Any, trace: bool, success: bool) -> None:
    """Save trace file if needed based on conditions."""
    should_save = trace or not success
    if not should_save:
        return

    trace_file = trace_collector.save_to_file()
    if not success:
        click.echo(f"📝 Debug trace saved: {trace_file}", err=True)
    else:  # trace is True and success is True
        # Use err=True to ensure message is visible even with workflow output
        click.echo(f"📝 Trace saved: {trace_file}", err=True)


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
    import threading

    # Show what we're doing if verbose
    if verbose:
        click.echo("cli: Using natural language planner to process input")
        click.echo("cli: Note: This may take 10-30 seconds for complex requests")

    # Create debugging context (always enabled for progress indicators)
    from pflow.planning.debug import DebugContext, PlannerProgress, TraceCollector

    trace_collector = TraceCollector(raw_input)
    progress = PlannerProgress()
    debug_context = DebugContext(trace_collector=trace_collector, progress=progress)

    # Create planner flow with debugging context
    planner_flow = create_planner_flow(debug_context=debug_context)

    shared = {
        "user_input": raw_input,
        "workflow_manager": WorkflowManager(),  # Uses default ~/.pflow/workflows
        "stdin_data": stdin_data if stdin_data else None,
    }

    # Set up timeout detection (can only detect after completion due to Python limitations)
    timed_out = threading.Event()
    timer = threading.Timer(planner_timeout, lambda: timed_out.set())
    timer.start()

    try:
        # Run the planner (BLOCKING - cannot be interrupted)
        planner_flow.run(shared)

        # Check timeout AFTER completion
        if timed_out.is_set():
            click.echo(f"\n⏰ Operation exceeded {planner_timeout}s timeout", err=True)
            trace_collector.set_final_status("timeout", shared)
            trace_file = trace_collector.save_to_file()
            click.echo(f"📝 Debug trace saved: {trace_file}", err=True)
            ctx.exit(1)

    except Exception as e:
        # Handle execution errors
        trace_collector.set_final_status("error", shared, {"message": str(e)})
        trace_file = trace_collector.save_to_file()
        click.echo(f"❌ Planner failed: {e}", err=True)
        click.echo(f"📝 Debug trace saved: {trace_file}", err=True)
        ctx.exit(1)

    finally:
        timer.cancel()

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

    # Save trace if needed
    _save_trace_if_needed(trace_collector, trace, success)

    # Execute workflow or handle failure
    if success:
        # Execute the workflow WITH execution_params for template resolution
        if verbose:
            click.echo("cli: Executing generated/discovered workflow")

        execute_json_workflow(
            ctx,
            planner_output["workflow_ir"],
            stdin_data,
            output_key,
            planner_output.get("execution_params"),  # CRITICAL: Pass params for templates!
            ctx.obj.get("output_format", "text"),
        )
    else:
        # Handle planning failure
        _handle_planning_failure(ctx, planner_output)


def _handle_planning_failure(ctx: click.Context, planner_output: dict) -> None:
    """Handle planning failure with helpful error messages."""
    error_msg = planner_output.get("error", "Unknown planning error")
    click.echo(f"cli: Planning failed - {error_msg}", err=True)

    # Show missing parameters if that's the issue
    missing_params = planner_output.get("missing_params")
    if missing_params:
        click.echo("cli: Missing required parameters:", err=True)
        for param in missing_params:
            click.echo(f"  - {param}", err=True)

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

    except Exception as e:
        # Other errors in planner execution
        click.echo(f"cli: Planning failed - {e}", err=True)
        ctx.exit(1)


def _try_direct_workflow_execution(
    ctx: click.Context,
    workflow: tuple[str, ...],
    stdin_data: str | StdinData | None,
    output_key: str | None,
    verbose: bool,
) -> bool:
    """Try to execute workflow directly by name if it looks like one.

    Returns True if executed, False if should fall back to planner.
    """
    if not workflow:
        return False

    first_arg = workflow[0]
    remaining_args = workflow[1:] if len(workflow) > 1 else ()

    # Check if likely a workflow name
    if not is_likely_workflow_name(first_arg, remaining_args):
        return False

    wm = WorkflowManager()
    try:
        # Try to load the workflow
        if wm.exists(first_arg):
            # Load workflow IR
            workflow_ir = wm.load_ir(first_arg)

            # Parse parameters from remaining arguments
            execution_params = parse_workflow_params(remaining_args)

            # Show what we're doing if verbose
            if verbose:
                click.echo(f"cli: Loading workflow '{first_arg}' from registry")
                if execution_params:
                    click.echo(f"cli: With parameters: {execution_params}")

            # Execute directly (bypass planner)
            execute_json_workflow(
                ctx, workflow_ir, stdin_data, output_key, execution_params, ctx.obj.get("output_format", "text")
            )
            return True
    except WorkflowNotFoundError:
        # Fall through to planner
        return False
    except Exception as e:
        # Other errors should be reported
        click.echo(f"cli: Error loading workflow '{first_arg}': {e}", err=True)
        ctx.exit(1)

    return False


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


@click.command(context_settings={"allow_interspersed_args": False})
@click.pass_context
@click.option("--version", is_flag=True, help="Show the pflow version")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed execution output")
@click.option("--file", "-f", type=str, help="Read workflow from file")
@click.option("--output-key", "-o", "output_key", help="Shared store key to output to stdout (default: auto-detect)")
@click.option(
    "--output-format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format: text (default) or json",
)
@click.option("--trace", is_flag=True, help="Save debug trace even on success")
@click.option("--planner-timeout", type=int, default=60, help="Timeout for planner execution (seconds)")
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def main(
    ctx: click.Context,
    version: bool,
    verbose: bool,
    file: str | None,
    output_key: str | None,
    output_format: str,
    trace: bool,
    planner_timeout: int,
    workflow: tuple[str, ...],
) -> None:
    """pflow - Plan Once, Run Forever

    Natural language to deterministic workflows.

    \b
    Usage:
      pflow [OPTIONS] [WORKFLOW]...
      pflow --file PATH
      command | pflow

    \b
    Examples:
      # CLI Syntax - chain nodes with => operator
      pflow read-file --path=data.txt => llm --prompt="Summarize"

      # Natural Language - use quotes for commands with spaces
      pflow "read the file data.txt and summarize it"

      # From File - store complex workflows
      pflow --file workflow.txt

      # From stdin - pipe from other commands
      echo "analyze this text" | pflow

      # Passing flags to nodes - use -- separator
      pflow -- read-file --path=data.txt => process --flag

    \b
    Notes:
      - Input precedence: --file > stdin > command arguments
      - Use -- to prevent pflow from parsing node flags
      - Workflows are collected as raw input for the planner
    """
    if version:
        click.echo("pflow version 0.0.1")
        ctx.exit(0)

    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, handle_sigint)

    # Handle broken pipe for shell compatibility
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    # Initialize context object
    if ctx.obj is None:
        ctx.obj = {}

    # Determine input source and read workflow
    raw_input, source, stdin_data = get_input_source(file, workflow)

    # Validate workflow is not empty
    if not raw_input:
        raise click.ClickException("cli: No workflow provided. Use --help to see usage examples.")

    # Validate input length (100KB limit)
    if len(raw_input) > 100 * 1024:
        raise click.ClickException(
            "cli: Workflow input too large (max 100KB). Consider breaking it into smaller workflows."
        )

    # Store in context
    ctx.obj["raw_input"] = raw_input
    ctx.obj["input_source"] = source
    ctx.obj["stdin_data"] = stdin_data
    ctx.obj["verbose"] = verbose
    ctx.obj["output_key"] = output_key
    ctx.obj["output_format"] = output_format
    ctx.obj["trace"] = trace
    ctx.obj["planner_timeout"] = planner_timeout

    # Check for misplaced CLI flags in workflow arguments
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

    # Process workflow based on input type
    if source in ("file", "stdin"):
        # Process file or stdin workflows
        process_file_workflow(ctx, raw_input, stdin_data)
    else:
        # Check for direct workflow execution first (before planner)
        if _try_direct_workflow_execution(ctx, workflow, stdin_data, output_key, verbose):
            return

        # If we get here, either not a workflow name or not found - use planner
        _execute_with_planner(ctx, raw_input, stdin_data, output_key, verbose, source, trace, planner_timeout)
