"""MCP tools for pflow.

This module automatically imports all tool modules to register them
with the FastMCP server instance via decorators.
"""

# Import all tool modules to trigger registration
from . import (
    discovery_tools,
    execution_tools,
    registry_tools,
    workflow_tools,
)

__all__ = [
    "discovery_tools",
    "execution_tools",
    "registry_tools",
    "workflow_tools",
]
