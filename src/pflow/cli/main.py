"""Main CLI entry point for pflow."""

import sys
from pathlib import Path

import click


@click.group()
def main() -> None:
    """pflow - workflow compiler for deterministic CLI commands."""
    pass


@main.command()
def version() -> None:
    """Show the pflow version."""
    click.echo("pflow version 0.0.1")


@main.command()
@click.pass_context
@click.option("--file", "-f", type=click.Path(exists=True), help="Read workflow from file")
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def run(ctx: click.Context, file: str | None, workflow: tuple[str, ...]) -> None:
    """Run a pflow workflow from command-line arguments, stdin, or file."""
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
