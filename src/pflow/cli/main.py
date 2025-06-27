"""Main CLI entry point for pflow."""

import click


@click.group()
def main():
    """pflow - workflow compiler for deterministic CLI commands."""
    pass


@main.command()
def version():
    """Show the pflow version."""
    click.echo("pflow version 0.0.1")
