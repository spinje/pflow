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


def get_input_source(file: str | None, workflow: tuple[str, ...]) -> tuple[str, str, str | StdinData | None]:
    """Determine input source and read workflow input.

    Returns:
        Tuple of (workflow_content, source, stdin_data)
        stdin_data can be a string (backward compat), StdinData object, or None
    """
    if file and workflow:
        raise click.ClickException(
            "cli: Cannot specify both --file and command arguments. Use either --file OR provide a workflow as arguments."
        )

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


def _handle_workflow_output(shared_storage: dict[str, Any], output_key: str | None) -> bool:
    """Handle output from workflow execution.

    Returns True if output was produced, False otherwise.
    """
    if output_key:
        # User specified a key to output
        if output_key in shared_storage:
            return safe_output(shared_storage[output_key])
        else:
            click.echo(f"cli: Warning - output key '{output_key}' not found in shared store", err=True)
            return False
    else:
        # Auto-detect output from common keys
        for key in ["response", "output", "result", "text"]:
            if key in shared_storage:
                return safe_output(shared_storage[key])
        return False


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


def execute_json_workflow(
    ctx: click.Context,
    ir_data: dict[str, Any],
    stdin_data: str | StdinData | None = None,
    output_key: str | None = None,
    execution_params: dict[str, Any] | None = None,
) -> None:
    """Execute a JSON workflow if it's valid.

    Args:
        ctx: Click context
        ir_data: Parsed workflow IR data
        stdin_data: Optional stdin data (string or StdinData) to inject into shared storage
        output_key: Optional key to output from shared storage after execution
        execution_params: Optional parameters from planner for template resolution
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

    # Execute with shared storage
    shared_storage: dict[str, Any] = {}

    # Inject stdin data if present
    _inject_stdin_data(shared_storage, stdin_data, verbose)

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
            output_produced = _handle_workflow_output(shared_storage, output_key)

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

    # Get the workflow tuple from parent context
    parent = ctx.parent
    if not parent or not hasattr(parent, "params"):
        return None

    workflow_args = parent.params.get("workflow", ())
    if not workflow_args:
        return None

    # Parse parameters from workflow arguments
    execution_params = parse_workflow_params(workflow_args)
    if execution_params and ctx.obj.get("verbose"):
        click.echo(f"cli: With parameters: {execution_params}")

    return execution_params


def process_file_workflow(ctx: click.Context, raw_input: str, stdin_data: str | StdinData | None = None) -> None:
    """Process file-based workflow, handling JSON and errors.

    Args:
        ctx: Click context
        raw_input: Raw workflow content
        stdin_data: Optional stdin data to pass to workflow
    """
    try:
        # Try to parse as JSON
        ir_data = json.loads(raw_input)

        # Parse parameters from remaining workflow arguments if using --file
        execution_params = _get_file_execution_params(ctx)

        execute_json_workflow(ctx, ir_data, stdin_data, ctx.obj.get("output_key"), execution_params)

    except json.JSONDecodeError:
        # Not JSON - treat as plain text (for future natural language processing)
        click.echo(f"Collected workflow from file: {raw_input}")

    except ValidationError as e:
        click.echo(f"cli: Invalid workflow - {e.message}", err=True)
        if hasattr(e, "path") and e.path:
            click.echo(f"cli: Error at: {e.path}", err=True)
        if hasattr(e, "suggestion") and e.suggestion:
            click.echo(f"cli: Suggestion: {e.suggestion}", err=True)
        ctx.exit(1)

    except CompilationError as e:
        click.echo(f"cli: Compilation failed - {e}", err=True)
        ctx.exit(1)

    except (click.ClickException, SystemExit):
        # Let Click exceptions and exits propagate normally
        raise
    except Exception as e:
        click.echo(f"cli: Unexpected error - {e}", err=True)
        ctx.exit(1)


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


def _execute_with_planner(
    ctx: click.Context,
    raw_input: str,
    stdin_data: str | StdinData | None,
    output_key: str | None,
    verbose: bool,
    source: str,
) -> None:
    """Execute workflow using the natural language planner.

    Falls back to old behavior if planner is not available.
    """
    try:
        # Import planner (delayed import to avoid circular dependencies)
        from pflow.planning import create_planner_flow

        # Show what we're doing if verbose
        if verbose:
            click.echo("cli: Using natural language planner to process input")

        # Create planner flow
        planner_flow = create_planner_flow()
        shared = {
            "user_input": raw_input,
            "workflow_manager": WorkflowManager(),  # Uses default ~/.pflow/workflows
            "stdin_data": stdin_data if stdin_data else None,
        }

        # Run the planner
        planner_flow.run(shared)

        # Check result
        planner_output = shared.get("planner_output", {})
        if not isinstance(planner_output, dict):
            planner_output = {}
        if planner_output.get("success"):
            # Execute the workflow WITH execution_params for template resolution
            if verbose:
                click.echo("cli: Executing generated/discovered workflow")

            execute_json_workflow(
                ctx,
                planner_output["workflow_ir"],
                stdin_data,
                output_key,
                planner_output.get("execution_params"),  # CRITICAL: Pass params for templates!
            )
        else:
            # Handle planning failure
            error_msg = planner_output.get("error", "Unknown planning error")
            click.echo(f"cli: Planning failed - {error_msg}", err=True)

            # Show missing parameters if that's the issue
            missing_params = planner_output.get("missing_params")
            if missing_params:
                click.echo("cli: Missing required parameters:", err=True)
                for param in missing_params:
                    click.echo(f"  - {param}", err=True)

            ctx.exit(1)

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
            execute_json_workflow(ctx, workflow_ir, stdin_data, output_key, execution_params)
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
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def main(
    ctx: click.Context,
    version: bool,
    verbose: bool,
    file: str | None,
    output_key: str | None,
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

    # Process workflow based on input type
    if source in ("file", "stdin"):
        # Process file or stdin workflows
        process_file_workflow(ctx, raw_input, stdin_data)
    else:
        # Check for direct workflow execution first (before planner)
        if _try_direct_workflow_execution(ctx, workflow, stdin_data, output_key, verbose):
            return

        # If we get here, either not a workflow name or not found - use planner
        _execute_with_planner(ctx, raw_input, stdin_data, output_key, verbose, source)
