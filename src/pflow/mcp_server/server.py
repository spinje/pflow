"""FastMCP server instance for pflow.

This module creates the central FastMCP server instance that all tools
register with via decorators. This follows the FastMCP best practice
of having a single server instance that tools import and use.
"""

from mcp.server.fastmcp import FastMCP

# Create the FastMCP server instance with instructions for agents
# All tools and resources will register with this instance via decorators
mcp = FastMCP(
    "pflow",
    instructions="""CRITICAL WORKFLOW - Follow these steps for every workflow request:

1. ALWAYS run workflow_discover first to check if a suitable workflow already exists
2. If 95%+ confidence match found → execute it directly using the `workflow_execute` tool (don't rebuild)
3. If building new workflow → read the `pflow://instructions` resource FIRST before using other tools (this is not optional)
4. The instructions resource contains the complete 10-step development loop and best practices (REQUIRED FOR BUILDING OR MODIFYING WORKFLOWS)

Note: If you are a sandboxed agent:
 - No pflow cli installed (check with `pflow --version` if you are unsure)
 - No shared access to the users system
 use the `pflow://instructions/sandbox` resource instead.

This prevents duplicate workflows and ensures you follow established patterns.""",
)


# Import all tool and resource modules to register them
# This happens at import time via decorators
def register_tools() -> None:
    """Import all tool and resource modules to register them with the server.

    This function is called during server startup to ensure all tools
    and resources are registered before the server starts handling requests.
    """
    # Import tool modules to trigger @mcp.tool() decorators
    # We need to import these modules for their side effects (decorator registration)
    # Explicitly reference them to satisfy linting
    # Import resource modules to trigger @mcp.resource() decorators
    from .resources import instruction_resources
    from .tools import (
        discovery_tools,
        execution_tools,
        registry_tools,
        # settings_tools,  # DISABLED - code kept for future use
        # test_tools,  # DISABLED - development only
        workflow_tools,
    )

    # Explicitly reference the modules to satisfy ruff F401
    _ = (
        discovery_tools,
        execution_tools,
        registry_tools,
        # settings_tools,  # DISABLED
        # test_tools,  # DISABLED
        workflow_tools,
        instruction_resources,
    )


__all__ = ["mcp", "register_tools"]
