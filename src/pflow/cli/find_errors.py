"""Shared error handling utilities for `find` commands."""

import logging
import sys

import click

from pflow.core.exceptions import CriticalDiscoveryError

logger = logging.getLogger(__name__)


def validate_discovery_query(query: str, command_name: str) -> str:
    """Validate and sanitize a discovery query."""
    query = query.strip()

    if not query:
        click.echo(f"Error: {command_name} query cannot be empty", err=True)
        sys.exit(1)

    if len(query) > 500:
        click.echo(f"Error: Query too long (max 500 characters, got {len(query)})", err=True)
        click.echo("  Please use a more concise description", err=True)
        sys.exit(1)

    return query


def handle_discovery_error(
    exception: Exception,
    discovery_type: str,
    alternative_commands: list[tuple[str, str]],
) -> None:
    """Handle errors during LLM-powered discovery with user-friendly messages."""
    if isinstance(exception, CriticalDiscoveryError):
        reason_lower = exception.reason.lower()
        if "authentication" in reason_lower or "api key" in reason_lower:
            click.echo(f"Error: LLM-powered {discovery_type} discovery requires API configuration\n", err=True)
            click.echo("Configure Anthropic API key:", err=True)
            click.echo("  export ANTHROPIC_API_KEY=your-key-here", err=True)
            click.echo("  # Get key from: https://console.anthropic.com/\n", err=True)
            click.echo("Alternative discovery methods:", err=True)
            for cmd, desc in alternative_commands:
                click.echo(f"  {cmd:<35} # {desc}", err=True)
        else:
            click.echo(f"Error: {exception.reason}", err=True)
        return

    logger.exception("Unexpected error during %s discovery", discovery_type)
    click.echo(f"Unexpected error: {str(exception).splitlines()[0]}", err=True)
    click.echo("\nThis may be a bug. Please report at: https://github.com/spinje/pflow/issues", err=True)
    click.echo("\nAlternative methods:", err=True)
    for cmd, desc in alternative_commands:
        click.echo(f"  {cmd:<35} # {desc}", err=True)
