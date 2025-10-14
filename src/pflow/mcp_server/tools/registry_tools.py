"""Registry tools for the MCP server.

These tools provide node discovery, search, and description
capabilities for building workflows.
"""

import asyncio
import logging
from typing import Annotated

from pydantic import Field

from ..server import mcp
from ..services.registry_service import RegistryService

logger = logging.getLogger(__name__)


@mcp.tool()
async def registry_describe(
    nodes: Annotated[list[str], Field(description="List of node type identifiers to describe")],
) -> str:
    """Get detailed specifications for specific nodes.

    Returns comprehensive information for each node:
    - Full description and purpose
    - Required and optional input parameters
    - Output keys available for templates
    - Usage examples

    Examples:
        # Describe a single core node
        nodes=["read-file"]

        # Describe multiple nodes to compare interfaces
        nodes=["http", "shell", "llm"]

        # Describe MCP tool using full ID
        nodes=["mcp-slack-mcp-server-SLACK_SEND_MESSAGE"]

    Returns:
        Formatted text description showing for each node:
        - Input interface (parameters with types, requirements, defaults)
        - Output interface (keys available for templates like ${result.data})
        - Usage examples with typical parameter values
    """
    logger.debug(f"registry_describe called with {len(nodes)} nodes")

    def _sync_describe() -> str:
        """Synchronous describe operation."""
        result: str = RegistryService.describe_nodes(nodes)
        return result

    # Run in thread pool
    result = await asyncio.to_thread(_sync_describe)

    logger.info(f"Described {len(nodes)} nodes")
    return result


@mcp.tool()
async def registry_list(
    filter_pattern: str | None = Field(
        None,
        description="Optional filter pattern. Single keyword or space-separated keywords (AND logic). Examples: 'github' or 'github api'",
    ),
) -> str:
    """List available nodes, optionally filtered by pattern.

    ⚠️ IMPORTANT:
    - WITHOUT filter: Returns 100+ nodes grouped by package (overwhelming)
    - WITH filter: Returns matching nodes sorted by relevance (useful)
    - PREFER registry_discover: For first-time or "what can I use for X?" queries
    - USE registry_list: When you know the node name pattern already

    Examples:
        # List all nodes (no parameters) ⚠️ Avoid this!!
        <invoke with no parameters>

        # Filter by single keyword (returns matching nodes sorted by relevance)
        filter_pattern="llm"      # Finds llm node
        filter_pattern="github"    # Finds github-create-pr, github-list-repos, etc.
        filter_pattern="slack"     # Finds Slack MCP tools

        # Multi-keyword filter (returns nodes matching ALL keywords via AND logic)
        filter_pattern="github api"   # Must match BOTH "github" AND "api"
        filter_pattern="slack send"   # Must match BOTH "slack" AND "send"

    Returns:
        Formatted text listing of nodes:
        - No filter: Grouped by package with counts
        - With filter: Relevance-sorted list with descriptions

        Example output (filtered):
        ```
        Found 3 nodes matching 'github api':
          github-create-pr          Create pull requests via API
          github-create-issue       Create issues via API
          github-get-file           Get file contents using API
        ```
    """
    logger.debug(f"registry_list called with filter: {filter_pattern}")

    def _sync_list() -> str:
        """Synchronous list operation."""
        result: str = RegistryService.list_all_nodes(filter_pattern)
        return result

    # Run in thread pool
    result = await asyncio.to_thread(_sync_list)

    if filter_pattern:
        logger.info(f"registry_list returned filtered results for: {filter_pattern}")
    else:
        logger.info("registry_list returned complete node listing")
    return result
