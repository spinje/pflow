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
        # Get detailed specs for specific nodes (returns parameters, outputs, and examples)
        nodes=["node-type-1", "node-type-2"]

    Returns:
        Formatted text description of each node with complete specifications
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
async def registry_search(
    pattern: str = Field(..., description="Search term to match against node IDs and descriptions (case-insensitive)"),
) -> str:
    """Search for nodes by pattern.

    Use this when you know what type of node you're looking for.
    Searches across node IDs and descriptions.

    Examples:
        # Search for nodes (returns matching nodes in table format)
        pattern="keyword"

    Returns:
        Formatted table with matching nodes
    """
    logger.debug(f"registry_search called with pattern: {pattern}")

    def _sync_search() -> str:
        """Synchronous search operation."""
        result: str = RegistryService.search_nodes(pattern)
        return result

    # Run in thread pool
    result = await asyncio.to_thread(_sync_search)

    logger.info(f"registry_search returned formatted results for: {pattern}")
    return result


@mcp.tool()
async def registry_list() -> str:
    """List all available nodes grouped by package.

    ⚠️ Use this as a LAST RESORT only. Prefer:
    - registry_discover: For complex queries and intelligent node selection
    - registry_search: When you know what type of node you need

    This tool returns ALL nodes which can be overwhelming.
    Only use ONLY when you need to browse the complete catalog.

    Returns:
        All registered nodes grouped by package (Core, MCP, User) with summary counts

    Example:
        Returns complete node catalog - use sparingly
    """
    logger.debug("registry_list called")

    def _sync_list() -> str:
        """Synchronous list operation."""
        result: str = RegistryService.list_all_nodes()
        return result

    # Run in thread pool
    result = await asyncio.to_thread(_sync_list)

    logger.info("registry_list returned formatted node listing")
    return result
