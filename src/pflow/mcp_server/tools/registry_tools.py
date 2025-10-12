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
    nodes: Annotated[list[str], Field(description="List of node IDs to describe")],
) -> str:
    """Get detailed specifications for specific nodes.

    Returns formatted text output with:
    - Node description
    - Input parameters
    - Output keys
    - Usage examples

    Args:
        nodes: List of node IDs (e.g., ["read-file", "write-file"])

    Returns:
        Formatted text description of each node

    Example:
        nodes=["read-file"]
        Returns detailed spec with parameters and examples
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
    pattern: str = Field(..., description="Search pattern (case-insensitive)"),
) -> str:
    """Search for nodes by pattern in markdown format (CLI parity).

    Searches in:
    - Node IDs
    - Descriptions

    Args:
        pattern: Search pattern (e.g., "file", "github", "llm")

    Returns:
        Formatted markdown string with search results table (same as CLI)

    Example:
        pattern="file"
        Returns formatted table of file-related nodes
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
    """List all available nodes in markdown format (CLI parity).

    Returns formatted text with:
    - All registered nodes
    - Grouped by package (Core, MCP, User)
    - Summary counts

    Returns:
        Formatted markdown string with nodes grouped by package (same as CLI)

    Example:
        Returns formatted node listing with grouping and summary
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
