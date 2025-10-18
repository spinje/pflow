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
    instructions="""🚨 MANDATORY WORKFLOW PROTOCOL 🚨

WHEN TO FOLLOW - Any request where you will create/build a pflow workflow:
• "Create a workflow that does X"
• "Help me build/make a workflow"
• "Automate X with pflow"
• User describes task → you produce .json workflow file

REQUIRED SEQUENCE (no exceptions, no skipping):
1. workflow_discover first → Check if suitable workflow already exists
   → 95%+ confidence match? Execute with `workflow_execute` tool (don't rebuild)
2. If building new → Read `pflow://instructions` resource BEFORE using other tools (NON-OPTIONAL)
   → Contains complete 10-step development loop + best practices
   → ⛔ DO NOT skip to building unless you have read the FULL `pflow://instructions` mcp resource
3. Then use registry_discover, registry_describe, etc.

SANDBOXED ENVIRONMENTS:
If no CLI access (pflow --version fails) or no shared filesystem:
→ Use `pflow://instructions/sandbox` resource instead

PURPOSE: Prevents duplicate workflows, ensures established patterns.""",
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
