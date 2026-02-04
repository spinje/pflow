"""Execution tools for the MCP server.

These tools provide workflow execution, validation, saving,
and node testing capabilities.
"""

import asyncio
import logging
from typing import Annotated, Any

from pydantic import Field

from ..server import mcp
from ..services.execution_service import ExecutionService

logger = logging.getLogger(__name__)


@mcp.tool()
async def workflow_execute(
    workflow: Annotated[
        str | dict[str, Any],
        Field(description="Workflow name from library, path to workflow file, or workflow IR object"),
    ],
    parameters: Annotated[
        dict[str, Any] | None,
        Field(description="Input parameters as key-value pairs matching the workflow's declared inputs"),
    ] = None,
) -> str:
    """Execute a workflow with natural language output.

    Input Types:
    1. Workflow name: "my-workflow" (from saved library)
    2. File path: "./workflow.pflow.md" (for agents with filesystem access)
    3. Raw markdown content: "# Title\\n## Steps\\n..." (inline .pflow.md content)
    4. Inline IR: {...} (for sandboxed agents or programmatic building)

    Built-in behaviors:
    - Trace always saved to ~/.pflow/debug/workflow-trace-{name}-{timestamp}.json
    - Returns explicit errors with suggestions for fixing

    Before executing:
    1. Call workflow_describe to understand required parameters
    2. Ensure all required inputs are provided
    3. Validate parameters match expected types

    Examples:
        # Execute saved workflow by name
        workflow="my-workflow"
        parameters={"input1": "value1", "input2": 123}

        # Execute workflow from file
        # ⚠️ Use when you have filesystem access (non-sandbox agents)
        workflow="./workflows/my-workflow.pflow.md"
        parameters={...}

        # Execute inline workflow IR
        # ⚠️ Use in sandboxed environments or when building programmatically
        workflow={
            "inputs": {...},
            "nodes": [...],
            "edges": [...],
            "outputs": {...}
        }
        parameters={...}

    Returns:
        Formatted text with execution results
        Success: "✓ Workflow completed in 0.5s\n\nOutputs:\n  result: ...\n\nNodes executed (3)..."
        Error: "❌ Workflow execution failed\n\nError details:\n  • node-id: error message..."
    """
    logger.debug(f"workflow_execute called: workflow type={type(workflow)}")

    def _sync_execute() -> str:
        """Synchronous execution operation."""
        return ExecutionService.execute_workflow(workflow, parameters)

    # Run in thread pool to avoid blocking
    result = await asyncio.to_thread(_sync_execute)

    # Log based on result content
    if result.startswith("✓"):
        logger.info("Workflow execution successful")
    else:
        logger.warning("Workflow execution failed")

    return result


@mcp.tool()
async def workflow_validate(
    workflow: Annotated[
        str | dict[str, Any],
        Field(description="Workflow name from library, path to workflow file, or workflow IR object"),
    ],
) -> str:
    """STATIC validation of workflow structure WITHOUT execution.

    Checks:
    - Schema compliance (required fields, correct structure)
    - Data flow correctness (execution order, no cycles)
    - Template structure (${node.output} references)
    - Node types exist in registry

    Does NOT check:
    - Runtime values
    - API credentials
    - File existence
    - ANY runtime issues

    Examples:
        # Validate saved workflow (returns validation errors if any)
        workflow="my-workflow"

        # Validate workflow file
        # ⚠️ Use when you have filesystem access
        workflow="./workflow.pflow.md"

        # Validate inline workflow IR
        # ⚠️ Use in sandboxed environments
        workflow={
            "inputs": {...},
            "nodes": [...],
            "edges": [...],
            "outputs": {...}
        }

    Returns:
        Formatted text with validation results and suggestions for fixing
        Success: "✓ Workflow is valid"
        Failure: "✗ Static validation failed:\n  • Error 1\n  • Error 2\n\nSuggestions:\n  • Fix 1"
    """
    logger.debug("workflow_validate called")

    def _sync_validate() -> str:
        """Synchronous validation operation."""
        return ExecutionService.validate_workflow(workflow)

    # Run in thread pool
    result = await asyncio.to_thread(_sync_validate)

    # Log based on result content (string now)
    if result.startswith("✓"):
        logger.info("Workflow validation passed")
    else:
        logger.info("Workflow validation failed")

    return result


@mcp.tool()
async def workflow_save(
    workflow: Annotated[
        str,
        Field(
            description=(
                "Workflow to save. Can be:\n"
                "  - Raw .pflow.md content (markdown string with newlines)\n"
                "  - Path to .pflow.md file: './my-workflow.pflow.md'"
            )
        ),
    ],
    name: str = Field(..., description="Unique workflow name (format: lowercase-with-hyphens, max 50 chars)"),
    force: bool = Field(False, description="Whether to overwrite existing workflow with same name"),
) -> str:
    """Save workflow to global library for reuse.

    Purpose: Make workflows reusable by name. Save ONLY workflows you'll execute multiple times.
    Don't save: One-off workflows, tests, experiments.

    Validates the workflow before saving. Description is extracted from the
    markdown content (prose after the # title heading).
    Name must be lowercase letters, numbers, and hyphens only (max 50 chars).

    By default, saving fails if a workflow with the same name exists.
    Use force=true to overwrite existing workflows.

    Examples:
        # Save workflow from file
        # ⚠️ Use when you have filesystem access
        workflow="./path/to/my-workflow.pflow.md"
        name="my-workflow"
        force=False

        # Save raw markdown content
        workflow="# My Workflow\\n\\nDescription.\\n\\n## Steps\\n..."
        name="my-workflow"

    Returns:
        Formatted success message with location and execution hint
        "✓ Saved workflow 'name' to library\n  Location: /path/to/workflow.pflow.md\n  ✨ Execute with: pflow name param=<value>"
    """
    logger.debug(f"workflow_save called: name={name}, force={force}")

    def _sync_save() -> str:
        """Synchronous save operation."""
        return ExecutionService.save_workflow(workflow, name, force)

    # Run in thread pool
    result = await asyncio.to_thread(_sync_save)

    logger.info(f"Workflow saved as '{name}' (force={force})")

    return result


@mcp.tool()
async def registry_run(
    node_type: Annotated[str, Field(description="Node type identifier from the registry")],
    parameters: Annotated[
        dict[str, Any] | None,
        Field(description="Node-specific input parameters as key-value pairs"),
    ] = None,
) -> str:
    """Execute a single node with real data to test/discover its output structure and available template variables.

    ⚠️ WARNING: This EXECUTES the node with real side effects.

    Safe to test: HTTP GET, read-file, data transforms
    Ask user first: shell, write-file, HTTP POST/PUT/DELETE, MCP tools, git operations

    ⚠️ Critical use case: Use when node output structure is "Any" or unknown - common with HTTP and MCP nodes.

    WHEN TO USE:
    - AFTER using registry_describe to understand node parameters
    - BEFORE building workflows to discover available template variables
    - For any HTTP/MCP/external nodes where output structure is unclear

    Shows complete flattened output structure with all available template paths
    (like `${result.data.items[0].title}`) for workflow building.

    Examples:
        # Test HTTP GET (shows response structure for API calls)
        node_type="http"
        parameters={"url": "https://api.github.com/repos/owner/repo",
            "method": "GET",
            "headers": {"X-API-Key": "your_api_key", "X-Custom-Header": "value"}
        }

        # Test HTTP POST with JSON body (shows request/response structure)
        node_type="http"
        parameters={"url": "https://api.example.com/endpoint",
            "method": "POST",
            "body": {"key": "value", "data": [1, 2, 3]},
            "auth_token": "your_bearer_token"
        }

        # Test MCP node to discover nested output structure
        node_type="mcp-slack-mcp-server-SLACK_SEND_MESSAGE"
        parameters={"channel": "The channel id",
            "markdown_text": "Your message here"
        }

    Returns:
        Formatted text with output structure and all available template paths
    """
    logger.debug(f"registry_run called: node_type={node_type}")

    def _sync_run() -> str:
        """Synchronous node execution."""
        return ExecutionService.run_registry_node(node_type, parameters)

    # Run in thread pool
    result = await asyncio.to_thread(_sync_run)

    logger.info(f"Node '{node_type}' execution completed, returning formatted output")
    return result


@mcp.tool()
async def read_fields(
    execution_id: Annotated[
        str, Field(description="Execution ID from previous registry_run call (format: exec-TIMESTAMP-RANDOM)")
    ],
    field_paths: Annotated[
        list[str], Field(description="Field paths to retrieve like ['result[0].title', 'result[0].id']")
    ],
) -> str:
    """Read specific field values from a cached node execution.

    This tool retrieves only the requested fields from a previous registry_run execution,
    enabling efficient data access without re-executing the node.

    WHEN TO USE:
    - AFTER calling registry_run to see structure
    - When you need actual data values (not just structure)
    - To selectively retrieve specific fields without fetching everything

    The execution_id comes from the registry_run output (displayed after execution).
    Field paths use the same syntax shown in registry_run structure output.

    Examples:
        # Single field retrieval
        execution_id="exec-1705234567-a1b2c3d4"
        field_paths=["result[0].title"]

        # Multiple fields at once (more efficient than separate calls)
        execution_id="exec-1705234567-a1b2c3d4"
        field_paths=["result[0].title", "result[0].id", "result[0].state"]

        # Nested field access
        execution_id="exec-1705234567-a1b2c3d4"
        field_paths=["result.data.items[0].author.login"]

    Returns:
        Formatted text showing each field path and its value.
        Fields not found return None.
    """
    logger.debug(f"read_fields called: execution_id={execution_id}, field_count={len(field_paths)}")

    def _sync_read_fields() -> str:
        """Synchronous field reading operation."""
        from ..services.field_service import FieldService

        return FieldService.read_fields(execution_id, field_paths)

    # Run in thread pool
    result = await asyncio.to_thread(_sync_read_fields)

    logger.info(f"Retrieved {len(field_paths)} fields from execution {execution_id}")
    return result


# Export all execution tools
__all__ = [
    "read_fields",
    "registry_run",
    "workflow_execute",
    "workflow_save",
    "workflow_validate",
]
