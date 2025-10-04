"""Shared error handling utilities for discovery commands.

This module provides centralized error handling for LLM-powered discovery
commands (workflow discover, registry discover) to avoid code duplication
and ensure consistent error messaging.
"""

import click


def handle_discovery_error(
    exception: Exception,
    discovery_type: str,
    alternative_commands: list[tuple[str, str]],
) -> None:
    """Handle errors during LLM-powered discovery with user-friendly messages.

    Args:
        exception: The exception that occurred during discovery
        discovery_type: Type of discovery ("workflow" or "node") for error messages
        alternative_commands: List of (command, description) tuples for alternatives

    Examples:
        >>> handle_discovery_error(
        ...     CriticalPlanningError("Authentication failed"),
        ...     "workflow",
        ...     [
        ...         ("pflow workflow list", "Show all saved workflows"),
        ...         ("pflow workflow describe <name>", "Get workflow details"),
        ...     ]
        ... )
    """
    from pflow.core.exceptions import CriticalPlanningError

    if isinstance(exception, CriticalPlanningError):
        # Check if this is an authentication/API key error
        reason_lower = exception.reason.lower()
        if "authentication" in reason_lower or "api key" in reason_lower:
            click.echo(
                f"Error: LLM-powered {discovery_type} discovery requires API configuration\n",
                err=True,
            )
            click.echo("Configure Anthropic API key:", err=True)
            click.echo("  export ANTHROPIC_API_KEY=your-key-here", err=True)
            click.echo("  # Get key from: https://console.anthropic.com/\n", err=True)
            click.echo("Alternative discovery methods:", err=True)
            for cmd, desc in alternative_commands:
                click.echo(f"  {cmd:<35} # {desc}", err=True)
        else:
            # Other CriticalPlanningError - use existing reason
            click.echo(f"Error: {exception.reason}", err=True)
    else:
        # Fallback for unexpected errors
        click.echo(f"Error during discovery: {str(exception).splitlines()[0]}", err=True)
