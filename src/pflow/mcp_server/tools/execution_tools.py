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

    Built-in behaviors (no flags needed):
    - Text output format (LLMs parse natural language better than JSON)
    - No auto-repair (returns explicit errors for agent handling)
    - Trace saved to ~/.pflow/debug/
    - Auto-normalization (adds ir_version, edges if missing)

    Examples:
        # Execute saved workflow by name
        workflow="my-workflow"
        parameters={"input1": "value1", "input2": 123}

        # Execute workflow from file
        workflow="./workflows/analysis.json"
        parameters={...}

        # Execute inline workflow IR (useful for testing or one-off workflows)
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
    """Validate workflow structure without execution.

    Checks:
    - Schema compliance (JSON structure, required fields)
    - Data flow correctness (execution order, no cycles)
    - Template structure (${node.output} references)
    - Node types exist in registry

    Does NOT check:
    - Runtime values
    - API credentials
    - File existence

    Examples:
        # Validate saved workflow (returns validation errors if any)
        workflow="my-workflow"

        # Validate workflow file
        workflow="./workflow.json"

        # Validate inline workflow IR
        workflow={
            "inputs": {...},
            "nodes": [...],
            "edges": [...],
            "outputs": {...}
        }

    Returns:
        Formatted text with validation results
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
                "  - Path to workflow JSON file: './my-workflow.json'\n"
                '  - Workflow IR object: {"nodes": [...], "edges": [...], "inputs": {...}, "outputs": {...}}'
            )
        ),
    ],
    name: str = Field(..., description="Unique workflow name (format: lowercase-with-hyphens, max 50 chars)"),
    description: str = Field(..., description="One-line summary of what the workflow does"),
    force: bool = Field(False, description="Whether to overwrite existing workflow with same name"),
    generate_metadata: bool = Field(
        False,
        description="Whether to generate AI-powered metadata for better discovery (adds ~10s latency and LLM cost)",
    ),
) -> str:
    """Save workflow to global library for reuse.

    Validates and normalizes the workflow before saving.
    Name must be lowercase letters, numbers, and hyphens only (max 50 chars).

    By default, saving fails if a workflow with the same name exists.
    Use force=true to overwrite existing workflows.

    Set generate_metadata=true to create rich metadata (keywords, capabilities,
    typical use cases) which improves discovery ranking in workflow_discover.
    This uses an LLM call and adds latency but significantly improves discoverability.

    Examples:
        # Save workflow from file (minimal options)
        workflow="./path/to/workflow.json"
        name="my-workflow"
        description="Brief description of what workflow does"
        force=False
        generate_metadata=False

        # Save inline workflow with all options
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
    """Test a node to discover its actual output structure.

    Use this BEFORE building workflows to understand what template variables
    (like ${result.data.items[0].title}) are available from a node.

    Critical for MCP or HTTP nodes where documentation shows "Any" but actual
    output is deeply nested. Returns formatted text with complete structure
    showing all template paths available for workflow building.

    Examples:
        # Test core node (shows output structure with available template paths)
        node_type="node-type"
        parameters={"param1": "value1"}

        # Test MCP node to discover nested output structure
        node_type="mcp-server-name-tool-name"
        parameters={
            "param1": "value1",
            "param2": "value2"
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
