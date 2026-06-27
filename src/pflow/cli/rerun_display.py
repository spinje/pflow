"""Utilities for displaying rerun commands after workflow execution."""

from __future__ import annotations

import shlex
from typing import Any

import click

from pflow.cli.param_parsing import format_param_value
from pflow.core.security_utils import is_sensitive_parameter


def filter_user_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Filter out internal parameters (those starting with __).

    Args:
        params: Raw execution parameters

    Returns:
        Filtered params with only user-facing parameters, or None if empty
    """
    if not params:
        return None

    # Filter out internal params
    user_params = {k: v for k, v in params.items() if not k.startswith("__")}
    return user_params if user_params else None


def format_rerun_command(workflow_name: str, params: dict[str, Any] | None) -> str:
    """Build a complete rerun command with proper shell escaping.

    Args:
        workflow_name: Name of the saved workflow
        params: Execution parameters (None or empty dict for no params)

    Returns:
        Complete shell command string ready for display
    """
    # Start with base command (no "run" prefix per spec)
    command_parts = ["pflow", workflow_name]

    # Add parameters if any
    if params:
        for key, value in params.items():
            # Skip None values
            if value is None:
                continue

            # Skip internal parameters (those starting with __)
            # These are internal pflow parameters that shouldn't be exposed to users
            if key.startswith("__"):
                continue

            # Check if this is a sensitive parameter (the shared word-aware rule — also catches
            # delimited variants like ``my_api_key`` that the old exact-match missed)
            if is_sensitive_parameter(key):
                # Mask the value
                param_str = f"{key}=<REDACTED>"
            else:
                # Format the value for CLI
                cli_value = format_param_value(value)

                # Apply shell escaping to the value
                escaped_value = shlex.quote(cli_value)

                # Build key=value parameter
                param_str = f"{key}={escaped_value}"

            command_parts.append(param_str)

    return " ".join(command_parts)


def display_rerun_commands(workflow_name: str, params: dict[str, Any] | None) -> None:
    """Display the rerun and describe commands to the user.

    Args:
        workflow_name: Name of the saved workflow
        params: Execution parameters (None or empty dict for no params)
    """
    # Build the rerun command
    rerun_command = format_rerun_command(workflow_name, params)

    # Display with emoji prefixes and proper formatting
    click.echo("\n✨ Run again with:")
    click.echo(f"  $ {rerun_command}")

    click.echo("\n📖 Learn more:")
    click.echo(f"  $ pflow describe {workflow_name}")
