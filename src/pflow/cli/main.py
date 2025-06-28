"""Main CLI entry point for pflow."""

from __future__ import annotations

import signal
import sys
from pathlib import Path
from typing import Optional

import click


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


@click.command(context_settings={"allow_interspersed_args": False})
@click.pass_context
@click.option("--version", is_flag=True, help="Show the pflow version")
@click.option("--file", "-f", type=str, help="Read workflow from file")
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def main(ctx: click.Context, version: bool, file: Optional[str], workflow: tuple[str, ...]) -> None:  # noqa: UP007
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
    if file and workflow:
        raise click.ClickException(
            "cli: Cannot specify both --file and command arguments. Use either --file OR provide a workflow as arguments."
        )

    if file:
        # Read from file
        raw_input = read_workflow_from_file(file)
        source = "file"
    elif not sys.stdin.isatty():
        # Read from stdin
        raw_input = sys.stdin.read().strip()
        if raw_input:  # Only use stdin if it has content
            if workflow:
                raise click.ClickException(
                    "cli: Cannot use stdin input when command arguments are provided. Use either piped input OR command arguments."
                )
            source = "stdin"
        else:
            # Empty stdin, treat as command arguments
            raw_input = " ".join(workflow)
            source = "args"
    else:
        # Use command arguments
        raw_input = " ".join(workflow)
        source = "args"

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

    # Temporary output
    click.echo(f"Collected workflow from {source}: {raw_input}")
