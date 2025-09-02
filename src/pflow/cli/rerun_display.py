"""Utilities for displaying rerun commands after workflow execution."""

from __future__ import annotations

import json
import shlex
from typing import Any

import click


def format_param_value(value: Any) -> str:
    """Convert a Python value to its CLI string representation.

    This reverses the logic of infer_type() to produce a string that,
    when parsed by the CLI, will result in the same Python value.

    Args:
        value: The Python value to convert

    Returns:
        The string representation for CLI usage (WITHOUT shell escaping)
    """
    if isinstance(value, bool):
        # Booleans become lowercase strings
        return str(value).lower()

    elif isinstance(value, (int, float)):
        # Numbers convert directly
        return str(value)

    elif isinstance(value, (list, dict)):
        # JSON types need compact serialization
        return json.dumps(value, separators=(",", ":"))

    elif isinstance(value, str):
        # Strings pass through as-is
        return value

    else:
        # Fallback for other types
        return str(value)


def format_rerun_command(workflow_name: str, params: dict[str, Any] | None) -> str:
    """Build a complete rerun command with proper shell escaping.

    Args:
        workflow_name: Name of the saved workflow
        params: Execution parameters (None or empty dict for no params)

    Returns:
        Complete shell command string ready for display
    """
    # Common secret-like parameter names to mask
    SENSITIVE_KEYS = {
        "password",
        "passwd",
        "pwd",
        "token",
        "api_token",
        "access_token",
        "auth_token",
        "api_key",
        "apikey",
        "api-key",
        "secret",
        "client_secret",
        "private_key",
        "ssh_key",
        "secret_key",
    }

    # Start with base command (no "run" prefix per spec)
    command_parts = ["pflow", workflow_name]

    # Add parameters if any
    if params:
        for key, value in params.items():
            # Skip None values
            if value is None:
                continue

            # Check if this is a sensitive parameter
            if key.lower() in SENSITIVE_KEYS:
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
    click.echo(f"  $ pflow workflow describe {workflow_name}")
