"""Wrapper to route between workflow and subcommands (MCP, Registry).

PROBLEM: Click groups with catch-all arguments don't work for subcommands.
When @click.argument("workflow", nargs=-1) is on a @click.group(), it consumes
ALL positional arguments including subcommand names like "mcp" or "registry", preventing
Click from recognizing them as subcommands.

SOLUTION: Pre-parse sys.argv to detect known subcommands BEFORE Click processes arguments.
If found, route directly to appropriate command group. Otherwise, run workflow command.
This allows "pflow mcp list", "pflow registry list", and "pflow 'create a poem'" to all work correctly.
"""

import sys


def cli_main() -> None:
    """Main entry point that routes between workflow execution and subcommands."""
    # Import here to avoid circular imports
    from .main import workflow_command
    from .mcp import mcp
    from .registry import registry

    # Pre-parse to find first non-option argument before Click consumes it
    first_arg = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            first_arg = arg
            break

    if first_arg == "mcp":
        # Manually route to MCP group by manipulating sys.argv
        # This bypasses Click's argument parsing which would consume "mcp" as workflow arg
        original_argv = sys.argv[:]
        try:
            # Remove the first 'mcp' from arguments
            mcp_index = sys.argv.index("mcp")
            sys.argv = [sys.argv[0]] + sys.argv[mcp_index + 1 :]
            mcp()
        finally:
            sys.argv = original_argv

    elif first_arg == "registry":
        # Route to Registry group
        original_argv = sys.argv[:]
        try:
            registry_index = sys.argv.index("registry")
            sys.argv = [sys.argv[0]] + sys.argv[registry_index + 1 :]
            registry()
        finally:
            sys.argv = original_argv

    else:
        # Run the workflow command (default behavior)
        workflow_command()
