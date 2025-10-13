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
    filter_pattern: str | None = Field(
        None, description="Optional search term to filter workflows by name or description"
    ),
) -> str:
    """List saved workflows.

    Returns formatted workflow list showing:
    - Workflow names
    - Descriptions
    - Total count

    Examples:
        # List all workflows (returns complete workflow library)
        filter_pattern=None

        # Filter by pattern (returns only matching workflows)
        filter_pattern="keyword"

    Returns:
        Formatted markdown with workflow list
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
    name: str = Field(..., description="Name of the saved workflow from the library"),
) -> str:
    """Show detailed workflow interface specification.

    Returns workflow interface showing:
    - Workflow name and description
    - Input parameters (required/optional, types, defaults)
    - Output values (with descriptions)
    - Example usage command

    This is essential for understanding how to execute a workflow
    before calling workflow_execute.

    Examples:
        # Get workflow interface (returns inputs, outputs, and usage info)
        name="workflow-name"

    Returns:
        Formatted markdown with complete interface specification

    Raises:
        ValueError: If workflow not found (includes suggestions)
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
