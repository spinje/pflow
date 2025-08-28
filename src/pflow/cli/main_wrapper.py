"""Wrapper to route between workflow and MCP commands.

PROBLEM: Click groups with catch-all arguments don't work for subcommands.
When @click.argument("workflow", nargs=-1) is on a @click.group(), it consumes
ALL positional arguments including subcommand names like "mcp", preventing
Click from recognizing them as subcommands.

SOLUTION: Pre-parse sys.argv to detect "mcp" BEFORE Click processes arguments.
If found, route directly to MCP command group. Otherwise, run workflow command.
This allows both "pflow mcp list" and "pflow 'create a poem'" to work correctly.
"""

import sys


def cli_main() -> None:
    """Main entry point that routes between workflow execution and MCP commands."""
    # Import here to avoid circular imports
    from .main import workflow_command
    from .mcp import mcp

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
    else:
        # Run the workflow command (default behavior)
        workflow_command()
