"""pflow MCP Server.

Exposes pflow's workflow building and execution capabilities as MCP tools
for AI agents to use programmatically.
"""

from .main import run_server

__all__ = ["run_server"]
