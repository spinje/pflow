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
    query: str = Field(
        ...,
        description="Full, detailed description of what the user wants to accomplish (pass user request as-is or enhance it for clarity)",
    ),
) -> str:
    """Find existing workflows matching a request.

    Run this BEFORE building new workflows to check if a suitable
    workflow already exists. Uses LLM-powered intelligent matching
    to find workflows that match your requirements.

    IMPORTANT: Provide detailed, natural language descriptions similar to how
    an end user would describe their needs. Don't abbreviate or summarize.

    Confidence guidance:
    - 95%+ match: Execute directly, don't rebuild
    - 70-95%: Review workflow, may need minor adjustments (ask user if they want to execute it or modify it)
    - <70%: Build new workflow using registry_discover

    Note: Non-Sandboxed agents can inspect similar workflow in `~/.pflow/workflows/workflow-name.json` (copy json ir object and modify)
    Sandboxed agents will have to begin building the workflow from scratch.

    Examples:
        # Detailed workflow request (pass user's full description)
        query="I need to check our GitHub repository for new pull requests every hour, analyze the changes, generate a summary, and post it to our team's Slack channel"

        # Another detailed request (include context and requirements)
        query="I want to fetch customer data from our REST API, filter out inactive users, format the results into a CSV file, and email it to the marketing team every morning"

    Returns:
        Formatted markdown with workflow details, confidence scores, and reasoning
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
    task: str = Field(
        ...,
        description="Detailed description of the complete workflow or specific capabilities needed (use full user request)",
    ),
) -> str:
    """Find nodes for building workflows using intelligent selection.

    This tool uses LLM-powered analysis to select the best components
    for your task. Returns markdown formatted planning context with complete
    node specifications, interfaces, and everything needed to build a workflow.

    IMPORTANT: Provide detailed descriptions of what needs to be accomplished.
    Describe the full workflow context, not just a single operation.

    Examples:
        # Detailed workflow description (describes full context and requirements)
        task="I need to make an HTTP POST request to an API endpoint with JSON data in the body and custom authentication headers, then parse the response and extract specific fields"

        # Another detailed description (includes data flow and transformations)
        task="I want to read a JSON configuration file, use those settings to query a database, process the results with some filtering logic, and write the output to a CSV file"

    Returns:
        Formatted markdown with selected node specifications and interfaces
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
