"""Shared error handling utilities for discovery commands.

This module provides centralized error handling for LLM-powered discovery
commands (workflow discover, registry discover) to avoid code duplication
and ensure consistent error messaging.
"""

import logging

import click

logger = logging.getLogger(__name__)


def handle_discovery_error(
    exception: Exception,
    discovery_type: str,
    alternative_commands: list[tuple[str, str]],
) -> None:
    """Handle errors during LLM-powered discovery with user-friendly messages.

    Handles specific exception types with appropriate messaging and logs
    unexpected errors for debugging.

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
    from pflow.core.exceptions import CriticalPlanningError, WorkflowExecutionError

    if isinstance(exception, CriticalPlanningError):
        # Known planning error - handle gracefully
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

    elif isinstance(exception, WorkflowExecutionError):
        # Workflow execution error - show details and log
        logger.error(f"Discovery failed during workflow execution: {exception}", exc_info=True)
        click.echo(f"Error during {discovery_type} discovery: {str(exception).splitlines()[0]}", err=True)
        click.echo("\nAlternative methods:", err=True)
        for cmd, desc in alternative_commands:
            click.echo(f"  {cmd:<35} # {desc}", err=True)

    else:
        # Unexpected error - log for debugging and suggest bug report
        logger.exception(f"Unexpected error during {discovery_type} discovery")
        click.echo(f"Unexpected error: {str(exception).splitlines()[0]}", err=True)
        click.echo("\nThis may be a bug. Please report at: https://github.com/spinje/pflow/issues", err=True)
        click.echo("\nAlternative methods:", err=True)
        for cmd, desc in alternative_commands:
            click.echo(f"  {cmd:<35} # {desc}", err=True)
