"""Workflow management tools for the MCP server.

These tools provide workflow listing, description, and discovery capabilities.
"""

import asyncio
import logging

from pydantic import Field

from ..server import mcp
from ..services.workflow_service import WorkflowService

logger = logging.getLogger(__name__)


@mcp.tool()
async def workflow_list(
    filter_pattern: str | None = Field(None, description="Optional filter pattern"),
) -> str:
    """List saved workflows in markdown format (CLI parity).

    Returns formatted workflow list showing:
    - Workflow names
    - Descriptions
    - Total count

    Args:
        filter_pattern: Optional pattern to filter workflows

    Returns:
        Formatted markdown string (same as CLI)

    Example:
        filter_pattern="github"
        Returns filtered list of GitHub-related workflows
    """
    logger.debug(f"workflow_list called with filter: {filter_pattern}")

    def _sync_list() -> str:
        """Synchronous list operation."""
        result: str = WorkflowService.list_workflows(filter_pattern)
        return result

    # Run in thread pool
    formatted_list = await asyncio.to_thread(_sync_list)

    logger.info("Listed workflows (formatted markdown)")
    return formatted_list


@mcp.tool()
async def workflow_describe(
    name: str = Field(..., description="Workflow name to describe"),
) -> str:
    """Show detailed workflow interface specification.

    Returns workflow interface showing:
    - Workflow name and description
    - Input parameters (required/optional, types, defaults)
    - Output values (with descriptions)
    - Example usage command

    This is essential for understanding how to execute a workflow
    before calling workflow_execute.

    Args:
        name: Name of the saved workflow

    Returns:
        Formatted markdown string (same as CLI)

    Raises:
        ValueError: If workflow not found (includes suggestions)

    Example:
        name="github-pr-analyzer"
        Returns complete interface specification showing inputs/outputs
    """
    logger.debug(f"workflow_describe called for: {name}")

    def _sync_describe() -> str:
        """Synchronous describe operation."""
        result: str = WorkflowService.describe_workflow(name)
        return result

    try:
        # Run in thread pool
        result = await asyncio.to_thread(_sync_describe)
        logger.info(f"Described workflow: {name}")
        return result
    except ValueError:
        # Workflow not found - error includes suggestions
        logger.warning(f"Workflow not found: {name}")
        raise
