"""MCP tools for pflow.

This module automatically imports all tool modules to register them
with the FastMCP server instance via decorators.
"""

# Import all tool modules to trigger registration
# As we add more tool files, import them here
from . import (
    discovery_tools,  # Phase 2: Discovery tools
    execution_tools,  # Phase 3: Execution tools
    registry_tools,  # Phase 4: Registry tools
    # settings_tools,  # Phase 4: Settings tools (DISABLED - code kept for future use)
    test_tools,  # Phase 1: Basic test tool
    workflow_tools,  # Phase 4: Workflow tools
)

# Phase 5 imports (to be added):
# from . import trace_tools

__all__ = [
    "discovery_tools",
    "execution_tools",
    "registry_tools",
    # "settings_tools",  # DISABLED
    "test_tools",
    "workflow_tools",
]
