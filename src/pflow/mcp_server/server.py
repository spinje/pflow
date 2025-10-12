"""FastMCP server instance for pflow.

This module creates the central FastMCP server instance that all tools
register with via decorators. This follows the FastMCP best practice
of having a single server instance that tools import and use.
"""

from mcp.server.fastmcp import FastMCP

# Create the FastMCP server instance
# All tools will register with this instance via decorators
mcp = FastMCP("pflow")


# Import all tool modules to register them
# This happens at import time via decorators
def register_tools() -> None:
    """Import all tool modules to register them with the server.

    This function is called during server startup to ensure all tools
    are registered before the server starts handling requests.
    """
    # Import tool modules to trigger @mcp.tool() decorators
    # We need to import these modules for their side effects (decorator registration)
    # Explicitly reference them to satisfy linting
    from .tools import (
        discovery_tools,
        execution_tools,
        registry_tools,
        settings_tools,
        test_tools,
        workflow_tools,
    )

    # Explicitly reference the modules to satisfy ruff F401
    _ = (
        discovery_tools,
        execution_tools,
        registry_tools,
        settings_tools,
        test_tools,
        workflow_tools,
    )


__all__ = ["mcp", "register_tools"]
