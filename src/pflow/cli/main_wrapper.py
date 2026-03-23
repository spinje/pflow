"""Wrapper to route between workflow and subcommands.

PROBLEM: Click groups with catch-all arguments don't work for subcommands.
When @click.argument("workflow", nargs=-1) is on a @click.group(), it consumes
ALL positional arguments including subcommand names, preventing Click from
recognizing them as subcommands.

SOLUTION: Pre-parse sys.argv to detect known subcommands BEFORE Click processes
arguments. If found, route directly to appropriate command group. Otherwise, run
workflow command.
"""

import sys
from typing import Any


def _route_subcommand(name: str, handler: Any) -> None:
    """Route to a subcommand by stripping its name from sys.argv."""
    original_argv = sys.argv[:]
    try:
        idx = sys.argv.index(name)
        sys.argv = [sys.argv[0], *sys.argv[idx + 1 :]]
        handler()
    finally:
        sys.argv = original_argv


def cli_main() -> None:
    """Main entry point that routes between workflow execution and subcommands."""
    # Configure logging FIRST, before any command execution
    # This ensures all command groups (workflow, registry, mcp, etc.) respect the verbose flag
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    from .logging_config import configure_logging

    configure_logging(verbose)

    # Import here to avoid circular imports
    from .commands.instructions import instructions
    from .commands.mcp import mcp
    from .commands.read_fields import read_fields
    from .commands.registry import registry
    from .commands.settings import settings
    from .commands.skills import skill
    from .commands.trace import trace
    from .commands.workflow import workflow
    from .main import workflow_command

    # Pre-parse to find first non-option argument before Click consumes it
    first_arg = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            first_arg = arg
            break

    # Routing table: subcommand name → handler
    subcommand_routes: dict[str, Any] = {
        "mcp": mcp,
        "registry": registry,
        "workflow": workflow,
        "settings": settings,
        "instructions": instructions,
        "read-fields": read_fields,
        "skill": skill,
        "trace": trace,
    }

    if first_arg in subcommand_routes:
        _route_subcommand(first_arg, subcommand_routes[first_arg])
    else:
        workflow_command()
