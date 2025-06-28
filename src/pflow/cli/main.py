"""Main CLI entry point for pflow."""

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
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def run(workflow: tuple[str, ...]) -> None:
    """Run a pflow workflow from command-line arguments."""
    # Join arguments to show collected workflow
    workflow_str = " ".join(workflow)
    click.echo(f"Collected workflow: {workflow_str}")
