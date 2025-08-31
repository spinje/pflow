"""pflow CLI module.

Uses main_wrapper.cli_main as entry point to handle routing between:
- Default workflow execution: pflow "create a poem"
- MCP subcommands: pflow mcp list

This wrapper exists because Click can't handle both a catch-all argument
and subcommands in the same group - the argument consumes everything.
"""

from .main_wrapper import cli_main

__all__ = ["cli_main"]
