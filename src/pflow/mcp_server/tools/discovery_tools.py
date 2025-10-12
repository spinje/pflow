"""Discovery tools for the MCP server.

These tools provide intelligent discovery capabilities using
LLM-powered planning nodes for workflow and component selection.
"""

import asyncio
import logging

from pydantic import Field

from ..server import mcp
from ..services.discovery_service import DiscoveryService

logger = logging.getLogger(__name__)


@mcp.tool()
async def workflow_discover(
    query: str = Field(..., description="Natural language description of the desired workflow"),
) -> str:
    """Find existing workflows matching a request.

    Run this BEFORE building new workflows to check if a suitable
    workflow already exists. Uses LLM-powered intelligent matching
    to find workflows that match your requirements.

    Returns formatted markdown with workflow details, confidence scores,
    and reasoning.

    Args:
        query: Task description or workflow requirements

    Returns:
        Markdown formatted string with workflow details (same as CLI)

    Example:
        query="analyze GitHub pull requests and create summary"
        Returns markdown with workflow details and confidence score
    """
    logger.debug(f"workflow_discover called with query: {query}")

    def _sync_discover() -> str:
        """Synchronous discovery operation."""
        result: str = DiscoveryService.discover_workflows(query)
        return result

    # Run in thread pool to avoid blocking
    result = await asyncio.to_thread(_sync_discover)

    logger.debug("workflow_discover returning formatted markdown")
    return result


@mcp.tool()
async def registry_discover(
    task: str = Field(..., description="Description of what needs to be built"),
) -> str:
    """Find nodes for building workflows using intelligent selection.

    This tool uses LLM-powered analysis to select the best components
    for your task. Returns markdown formatted planning context with complete
    node specifications, interfaces, and everything needed to build a workflow.

    Args:
        task: Description of the workflow requirements

    Returns:
        Markdown formatted string with selected components (same as CLI)

    Example:
        task="fetch data from API and transform to CSV"
        Returns markdown with HttpNode and transformation nodes with full specs
    """
    logger.debug(f"registry_discover called with task: {task}")

    def _sync_discover() -> str:
        """Synchronous discovery operation."""
        result: str = DiscoveryService.discover_components(task)
        return result

    # Run in thread pool to avoid blocking
    result = await asyncio.to_thread(_sync_discover)

    logger.debug("registry_discover returning formatted markdown (planning_context)")
    return result


# Export all discovery tools
__all__ = ["registry_discover", "workflow_discover"]
