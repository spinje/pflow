"""Main CLI entry point for pflow."""

import sys
from pathlib import Path

import click


@click.command(context_settings={"allow_interspersed_args": False})
@click.pass_context
@click.option("--version", is_flag=True, help="Show the pflow version")
@click.option("--file", "-f", type=click.Path(exists=True), help="Read workflow from file")
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def main(ctx: click.Context, version: bool, file: str | None, workflow: tuple[str, ...]) -> None:
    """pflow - workflow compiler for deterministic CLI commands.

    Execute workflows using the => operator to chain nodes:

    \b
    Examples:
      pflow read-file --path=input.txt => llm --prompt="Summarize"
      pflow "analyze the Python files and find bugs"
      echo "read-file => process" | pflow
      pflow --file=workflow.txt
    """
    if version:
        click.echo("pflow version 0.0.1")
        ctx.exit(0)
    # Initialize context object
    if ctx.obj is None:
        ctx.obj = {}

    # Determine input source and read workflow
    if file and workflow:
        raise click.ClickException("Cannot specify both --file and command arguments")  # noqa: TRY003

    if file:
        # Read from file
        raw_input = Path(file).read_text().strip()
        source = "file"
    elif not sys.stdin.isatty():
        # Read from stdin
        raw_input = sys.stdin.read().strip()
        if raw_input:  # Only use stdin if it has content
            if workflow:
                raise click.ClickException("Cannot specify both stdin and command arguments")  # noqa: TRY003
            source = "stdin"
        else:
            # Empty stdin, treat as command arguments
            raw_input = " ".join(workflow)
            source = "args"
    else:
        # Use command arguments
        raw_input = " ".join(workflow)
        source = "args"

    # Store in context
    ctx.obj["raw_input"] = raw_input
    ctx.obj["input_source"] = source

    # Temporary output
    click.echo(f"Collected workflow from {source}: {raw_input}")
