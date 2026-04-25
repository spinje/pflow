"""Shared error handling utilities for `find` commands."""

import logging
import sys

import click

from pflow.core.exceptions import CriticalDiscoveryError, LLMCallError

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

    # LLM adapter errors propagating from discovery callers (find_workflow,
    # find_components). The exception's own to_diagnostics() override
    # produced the rich Diagnostic — surface its title + message + suggestions
    # directly so agents get the same actionable text the runtime path
    # produces, without duplicating the remediation logic here.
    if isinstance(exception, LLMCallError):
        diagnostic = exception.to_diagnostics()[0]
        title = diagnostic.title or "LLM Call Failed"
        click.echo(f"Error: {title}", err=True)
        click.echo(f"  {diagnostic.message}\n", err=True)
        if diagnostic.suggestions:
            click.echo("Suggestions:", err=True)
            for hint in diagnostic.suggestions:
                click.echo(f"  - {hint}", err=True)
            click.echo("", err=True)
        click.echo("Alternative methods:", err=True)
        for cmd, desc in alternative_commands:
            click.echo(f"  {cmd:<35} # {desc}", err=True)
        return

    logger.exception("Unexpected error during %s discovery", discovery_type)
    click.echo(f"Unexpected error: {str(exception).splitlines()[0]}", err=True)
    click.echo("\nThis may be a bug. Please report at: https://github.com/spinje/pflow/issues", err=True)
    click.echo("\nAlternative methods:", err=True)
    for cmd, desc in alternative_commands:
        click.echo(f"  {cmd:<35} # {desc}", err=True)
