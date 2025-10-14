"""Error formatting utilities for execution results.

This module provides shared error formatting logic used by both CLI and MCP server
to ensure consistent error handling across interfaces.
"""

import logging
from typing import Any

from pflow.execution.execution_state import build_execution_steps
from pflow.execution.executor_service import ExecutionResult

logger = logging.getLogger(__name__)


def format_execution_errors(
    result: ExecutionResult,
    shared_storage: dict[str, Any] | None = None,
    ir_data: dict[str, Any] | None = None,
    metrics_collector: Any | None = None,
    sanitize: bool = True,
) -> dict[str, Any]:
    """Format execution errors with optional sanitization for API consumption.

    This function extracts error information from ExecutionResult and applies
    sanitization to sensitive fields. Used by both CLI JSON output and MCP server.

    Args:
        result: ExecutionResult from execute_workflow()
        shared_storage: Optional shared store for execution state building
        ir_data: Optional workflow IR for execution state building
        metrics_collector: Optional metrics collector for timing and cost data
        sanitize: Whether to sanitize sensitive fields (default: True)
            - Set True for MCP/API responses
            - Set False for CLI display (sanitization happens at display layer)

    Returns:
        Dictionary with:
        - errors: List of error dicts (all fields from result.errors)
        - checkpoint: Execution checkpoint data
        - execution: Execution state with per-node status (if ir_data provided)
        - metrics: Metrics summary (if metrics_collector provided)

    Example:
        >>> result = execute_workflow(...)
        >>> formatted = format_execution_errors(result)
        >>> formatted["errors"][0]["status_code"]  # 422
        >>> formatted["errors"][0]["raw_response"]  # Sanitized
        >>> formatted["execution"]["steps"]  # Per-node execution state
    """
    # Extract checkpoint from shared store
    checkpoint = result.shared_after.get("__execution__", {})

    # Process each error
    formatted_errors = []
    for error in result.errors:
        # Create copy to avoid modifying original
        formatted_error = error.copy()

        # Apply sanitization if requested
        if sanitize:
            # Lazy import to avoid circular dependencies
            from pflow.mcp_server.utils.errors import sanitize_parameters

            # Sanitize sensitive fields
            if "raw_response" in formatted_error:
                formatted_error["raw_response"] = sanitize_parameters(formatted_error["raw_response"])

            if "response_headers" in formatted_error:
                formatted_error["response_headers"] = sanitize_parameters(formatted_error["response_headers"])

        formatted_errors.append(formatted_error)

    # Build result dictionary
    result_dict: dict[str, Any] = {
        "errors": formatted_errors,
        "checkpoint": checkpoint,
    }

    # Extract metrics summary if collector provided
    metrics_summary = None
    if metrics_collector and shared_storage:
        llm_calls = shared_storage.get("__llm_calls__", [])
        metrics_summary = metrics_collector.get_summary(llm_calls)

    # Add execution state if workflow IR and shared storage provided
    if ir_data and shared_storage:
        steps = build_execution_steps(ir_data, shared_storage, metrics_summary)
        if steps:
            # Count nodes by status
            completed_count = sum(1 for s in steps if s["status"] == "completed")
            nodes_total = len(steps)

            result_dict["execution"] = {
                "duration_ms": metrics_summary.get("duration_ms") if metrics_summary else None,
                "nodes_executed": completed_count,
                "nodes_total": nodes_total,
                "steps": steps,
            }

            # Add repaired flag if any nodes were modified
            modified_nodes = shared_storage.get("__modified_nodes__", [])
            if modified_nodes:
                result_dict["repaired"] = True

    # Add metrics summary if available
    if metrics_summary:
        # Extract workflow node count (not planner nodes)
        workflow_metrics = metrics_summary.get("metrics", {}).get("workflow", {})
        node_count = workflow_metrics.get("nodes_executed", 0)

        result_dict["metrics"] = {
            "duration_ms": metrics_summary.get("duration_ms"),
            "total_cost_usd": metrics_summary.get("total_cost_usd"),
            "nodes_executed": int(node_count),  # Ensure we return an int
            "metrics": metrics_summary.get("metrics", {}),
        }

    return result_dict
