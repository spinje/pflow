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

    Built-in behaviors:
    - Trace always saved to ~/.pflow/debug/workflow-trace-{name}-{timestamp}.json
    - Returns explicit errors with suggestions for fixing

    Examples:
        # Execute saved workflow by name
        workflow="my-workflow"
        parameters={"input1": "value1", "input2": 123}

        # Execute workflow from file (Should be used by Non-Sandbox Agents)
        workflow="./workflows/my-workflow.json"
        parameters={...}

        # Execute inline workflow IR (Should be used by Sandbox Agents)
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
    """Static validation of workflow structure without execution.

    Checks:
    - Schema compliance (JSON structure, required fields)
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

        # Validate workflow file (Should be used by Non-Sandbox Agents)
        workflow="./workflow.json"

        # Validate inline workflow IR (Should be used by Sandbox Agents)
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
        str | dict[str, Any],
        Field(
            description=(
                "Workflow to save. Can be:\n"
                "  - Path to workflow JSON file: '.pflow/workflows/my-workflow.json'\n"
                '  - Workflow IR object: {"nodes": [...], "edges": [...], "inputs": {...}, "outputs": {...}}'
            )
        ),
    ],
    name: str = Field(..., description="Unique workflow name (format: lowercase-with-hyphens, max 50 chars)"),
    description: str = Field(..., description="One-line summary of what the workflow does"),
    force: bool = Field(False, description="Whether to overwrite existing workflow with same name"),
    generate_metadata: bool = Field(
        False,
        description="Whether to generate AI-powered metadata for better discovery",
    ),
) -> str:
    """Save workflow to global library for reuse.

    Validates and normalizes the workflow before saving.
    Name must be lowercase letters, numbers, and hyphens only (max 50 chars).

    By default, saving fails if a workflow with the same name exists.
    Use force=true to overwrite existing workflows.

    Set generate_metadata=true for better discoverability (uses LLM, adds latency).
    Use when: Reusable workflows
    Skip when: Tests or one-off workflows

    Examples:
        # Save workflow from file (minimal options) (Should be used by Non-Sandbox Agents)
        workflow="./path/to/workflow.json"
        name="my-workflow"
        description="Brief description of what workflow does"
        force=False
        generate_metadata=False

        # Save inline workflow with all options (Should be used by Sandbox Agents)
        workflow={
            "inputs": {...},
            "nodes": [...],
            "edges": [...],
            "outputs": {...}
        }

        name="workflow-name"
        description="Detailed description of what this workflow does"
        force=True
        generate_metadata=True

    Returns:
        Formatted success message with location and execution hint
        "✓ Saved workflow 'name' to library\n  Location: /path/to/workflow.json\n  ✨ Execute with: pflow name param=<value>"
    """
    logger.debug(f"workflow_save called: name={name}, force={force}, generate_metadata={generate_metadata}")

    def _sync_save() -> str:
        """Synchronous save operation."""
        return ExecutionService.save_workflow(workflow, name, description, force, generate_metadata)

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
    """Execute a single node with real data to discover its actual output structure.

    ⚠️ WARNING: This EXECUTES the node with real side effects.

    Safe to test: HTTP GET, read-file, data transforms
    Ask user first: shell, write-file, HTTP POST/PUT/DELETE, MCP tools, git operations

    WHEN TO USE THIS TOOL:
    - AFTER using registry_describe to understand node parameters
    - BEFORE building workflows to discover available template variables
    - Critical for HTTP/MCP nodes where output structure is "Any" in docs (pflow or external)

    This tool always shows the complete flattened output structure with all
    available template paths (like `${result.data.items[0].title}`) for use
    in workflow building.

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


# Export all execution tools
__all__ = [
    "registry_run",
    "workflow_execute",
    "workflow_save",
    "workflow_validate",
]
