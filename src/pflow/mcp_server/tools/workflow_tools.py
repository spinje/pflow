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
        None,
        description="Optional filter pattern. Single keyword or space-separated keywords (AND logic). Searches name and description.",
    ),
) -> str:
    """List saved workflows with name-based filtering.

    ⚠️ For semantic search use `workflow_discover` instead.
    This tool only does keyword matching in name/description.

    Use `workflow_discover` when: Semantic/capability search
      - "Find workflows that analyze pull requests"
      - "Show workflows for data processing"

    Use `workflow_list` when: Filtering by keywords in name
      - "Show workflows with 'data' in the name"
      - "List workflows containing 'slack'"

    Filter behavior:
    - No filter: Returns ALL workflows (may be long)
    - Single keyword: Matches name OR description
    - Multiple keywords: Space-separated AND logic (all must match)
      Example: "data process" matches workflows with both "data" AND "process"

    Examples:
        # List all workflows (no parameters)
        <invoke with no parameters>

        # Filter by single keyword
        filter_pattern="data"      # Shows data-processor, etc.
        filter_pattern="slack"     # Shows slack-notification, etc.

        # Multi-keyword filter (ALL keywords must match)
        filter_pattern="data process"  # Must match BOTH "data" AND "process"
        filter_pattern="slack send"   # Must match BOTH "slack" AND "send"

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

    ⚠️ ESSENTIAL: Call this BEFORE `workflow_execute` to understand required parameters if not already known.
    Executing without checking parameters first will likely fail.

    Returns workflow interface showing:
    - Workflow name and description
    - Input parameters (required/optional, types, defaults)
    - Output values (with descriptions)
    - Example usage command

    Typical usage pattern:
    1. workflow_discover (find workflow)
    2. workflow_describe (understand interface) ← YOU ARE HERE
    3. workflow_execute (run with correct parameters)

    Examples:
        # Check what parameters a workflow needs before execution
        name="data-processor"
        # Returns: inputs, outputs, full description and example usage


    Returns:
        Formatted markdown with complete interface specification
        ```

    Raises:
        ValueError: If workflow not found (includes similar workflow suggestions)
    """
    logger.debug(f"workflow_describe called for: {name}")

    def _sync_describe() -> str:
        """Synchronous describe operation."""
        result: str = WorkflowService.describe_workflow(name)
        return result

    result = await asyncio.to_thread(_sync_describe)
    logger.info(f"Described workflow: {name}")
    return result
