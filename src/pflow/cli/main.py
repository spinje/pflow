"""Main CLI entry point for pflow."""

from __future__ import annotations

import json
import signal
import sys
from pathlib import Path
from typing import Any

import click

from pflow.core import StdinData, ValidationError, validate_ir
from pflow.core.shell_integration import (
    determine_stdin_mode,
    read_stdin_enhanced,
)
from pflow.core.shell_integration import (
    read_stdin as read_stdin_content,
)
from pflow.registry import Registry
from pflow.runtime import CompilationError, compile_ir_to_flow


def handle_sigint(signum: int, frame: object) -> None:
    """Handle Ctrl+C gracefully."""
    click.echo("\ncli: Interrupted by user", err=True)
    sys.exit(130)  # Standard Unix exit code for SIGINT


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


def execute_json_workflow(
    ctx: click.Context, ir_data: dict[str, Any], stdin_data: str | StdinData | None = None
) -> None:
    """Execute a JSON workflow if it's valid.

    Args:
        ctx: Click context
        ir_data: Parsed workflow IR data
        stdin_data: Optional stdin data (string or StdinData) to inject into shared storage
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

    # Compile to Flow
    flow = compile_ir_to_flow(ir_data, registry)

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
            # Simple success message
            click.echo("Workflow executed successfully")
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
        execute_json_workflow(ctx, ir_data, stdin_data)

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


@click.command(context_settings={"allow_interspersed_args": False})
@click.pass_context
@click.option("--version", is_flag=True, help="Show the pflow version")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed execution output")
@click.option("--file", "-f", type=str, help="Read workflow from file")
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def main(ctx: click.Context, version: bool, verbose: bool, file: str | None, workflow: tuple[str, ...]) -> None:
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

    # Process workflow based on input type
    if source in ("file", "stdin"):
        # Process file or stdin workflows
        process_file_workflow(ctx, raw_input, stdin_data)
    else:
        # Temporary output for non-file inputs
        click.echo(f"Collected workflow from {source}: {raw_input}")
        _display_stdin_data(stdin_data)
