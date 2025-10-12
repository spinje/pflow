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
    workflow: Annotated[str | dict[str, Any], Field(description="Workflow name, file path, or IR dictionary")],
    parameters: Annotated[dict[str, Any] | None, Field(description="Execution parameters for the workflow")] = None,
) -> str:
    """Execute a workflow with natural language output.

    Built-in behaviors (no flags needed):
    - Text output format (LLMs parse natural language better than JSON)
    - No auto-repair (returns explicit errors for agent handling)
    - Trace saved to ~/.pflow/debug/
    - Auto-normalization (adds ir_version, edges if missing)

    Returns formatted text matching CLI output - easy for LLMs to parse.

    Args:
        workflow: Name (from library), path (to file), or IR dict
        parameters: Optional parameters for workflow execution

    Returns:
        Formatted text with execution results (same as CLI)
        Success: "✓ Workflow completed in 0.5s\n\nOutputs:\n  result: ...\n\nNodes executed (3):\n  ✓ node1 (120ms)\n  ✓ node2 (45ms)\n  ✓ node3 (12ms)\n\nCost: $0.0023 | Trace: /Users/user/.pflow/debug/workflow-trace-20251012-143045.json"
        Error: "❌ Workflow execution failed\n\nError details:\n  • node-id: error message\n\nTrace: /Users/user/.pflow/debug/workflow-trace-20251012-143045.json"

    Example:
        workflow="github-pr-analyzer"
        parameters={"repo": "anthropics/pflow", "pr": 123}
        Returns formatted text with outputs or error details (LLM-friendly natural language)
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
    workflow: Annotated[str | dict[str, Any], Field(description="Workflow name, file path, or IR dictionary")],
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

    Args:
        workflow: Name (from library), path (to file), or IR dict

    Returns:
        Formatted text with validation results (same as CLI)
        Success: "✓ Workflow is valid"
        Failure: "✗ Static validation failed:\n  • Error 1\n  • Error 2\n\nSuggestions:\n  • Fix 1"

    Example:
        workflow={"nodes": [...], "edges": [...]}
        Returns formatted validation message with errors and suggestions
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
    workflow_file: str = Field(..., description="Path to workflow JSON file to save"),
    name: str = Field(..., description="Workflow name (lowercase-with-hyphens, max 50 chars)"),
    description: str = Field(..., description="Brief description of what the workflow does"),
    force: bool = Field(False, description="Overwrite existing workflow if it exists"),
    generate_metadata: bool = Field(
        False, description="Generate rich metadata (keywords, capabilities, use cases) using AI for better discovery"
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

    Args:
        workflow_file: Path to workflow JSON file
        name: Unique name for the workflow
        description: What the workflow does
        force: Whether to overwrite existing workflow
        generate_metadata: Whether to generate AI-powered metadata for better discovery

    Returns:
        Formatted success message (text) matching CLI output
        "✓ Saved workflow 'name' to library\n  Location: /path/to/workflow.json\n  ✨ Execute with: pflow name param=<value>"

    Example:
        workflow_file="./draft-workflow.json"
        name="github-pr-analyzer"
        description="Analyzes GitHub PRs and creates summaries"
        force=false
        generate_metadata=true  # Improves discovery ranking

        Returns formatted text with save confirmation and execution hint (LLM-friendly)
    """
    logger.debug(f"workflow_save called: name={name}, force={force}, generate_metadata={generate_metadata}")

    def _sync_save() -> str:
        """Synchronous save operation."""
        # Note: workflow_file is the path, we pass it directly
        return ExecutionService.save_workflow(workflow_file, name, description, force, generate_metadata)

    # Run in thread pool
    result = await asyncio.to_thread(_sync_save)

    logger.info(f"Workflow saved as '{name}' (force={force})")

    return result


@mcp.tool()
async def registry_run(
    node_type: Annotated[str, Field(description="Node type to execute (e.g., 'read-file', 'mcp-github-GET_ISSUE')")],
    parameters: Annotated[dict[str, Any] | None, Field(description="Optional parameters for the node")] = None,
) -> str:
    """Test a node to discover its actual output structure.

    Use this BEFORE building workflows to understand what template variables
    (like ${result.data.items[0].title}) are available from a node.

    Critical for MCP nodes where documentation shows "Any" but actual
    output is deeply nested. Returns formatted text with complete structure
    showing all template paths available for workflow building.

    Args:
        node_type: Type of node to test
        parameters: Optional test parameters

    Returns:
        Formatted text with output structure and template paths (same as CLI)

    Example:
        node_type="mcp-github-GET_ISSUE"
        parameters={"issue": 123}
        Returns text showing all available template paths like ${result.title}
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
