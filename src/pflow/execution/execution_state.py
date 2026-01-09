"""Execution state utilities for workflow execution tracking.

This module provides shared utilities for building execution state summaries
from workflow execution data. Used by both success and error response paths
in CLI and MCP interfaces.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_execution_steps(
    workflow_ir: dict[str, Any],
    shared_storage: dict[str, Any],
    metrics_summary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build detailed execution steps array for workflow visualization.

    This function analyzes the workflow IR and execution state to produce
    a detailed array of per-node execution status, timing, and metadata.

    Args:
        workflow_ir: The workflow IR with nodes list
        shared_storage: Shared store after execution containing:
            - __execution__: Execution checkpoint data
            - __cache_hits__: List of nodes that hit cache
            - __modified_nodes__: List of nodes modified by repair
        metrics_summary: Optional metrics summary from collector containing
            node timing data

    Returns:
        List of step dictionaries, each containing:
        - node_id: The node identifier
        - status: "completed", "failed", or "not_executed"
        - duration_ms: Execution time in milliseconds (if available)
        - cached: Boolean indicating cache hit
        - repaired: Boolean indicating node was repaired (if applicable)

        For batch nodes (detected via batch_metadata key in output):
        - is_batch: True
        - batch_total: Total items processed
        - batch_success: Items without errors
        - batch_errors: Items with errors
        - batch_error_details: First 5 error dicts (index, item, error, exception)
        - batch_errors_truncated: Count of additional errors beyond the 5 shown

        For shell nodes with stderr but exit_code=0:
        - has_stderr: True (only when stderr present and exit_code=0)
        - stderr: The stderr content (stripped of leading/trailing whitespace)

    Example:
        >>> steps = build_execution_steps(workflow_ir, shared_storage, metrics)
        >>> steps[0]
        {
            "node_id": "fetch-data",
            "status": "completed",
            "duration_ms": 150,
            "cached": False
        }

        # Batch node example:
        >>> steps[1]
        {
            "node_id": "process-items",
            "status": "completed",
            "duration_ms": 500,
            "cached": False,
            "is_batch": True,
            "batch_total": 10,
            "batch_success": 8,
            "batch_errors": 2,
            "batch_error_details": [{"index": 1, "error": "..."}, ...],
            "batch_errors_truncated": 0
        }
    """
    if not workflow_ir or "nodes" not in workflow_ir:
        return []

    # Get execution state from shared storage
    exec_state = shared_storage.get("__execution__", {})
    completed = exec_state.get("completed_nodes", [])
    failed = exec_state.get("failed_node")
    cache_hits = shared_storage.get("__cache_hits__", [])
    modified_nodes = shared_storage.get("__modified_nodes__", [])

    # Extract node timings from metrics
    node_timings = {}
    if metrics_summary:
        workflow_metrics = metrics_summary.get("metrics", {}).get("workflow", {})
        node_timings = workflow_metrics.get("node_timings", {})

    # Build steps array from workflow IR
    steps = []
    for node in workflow_ir["nodes"]:
        node_id = node["id"]

        # Determine execution status
        # Check completed first - if a node failed then was repaired, it's completed
        if node_id in completed:
            status = "completed"
        elif node_id == failed:
            status = "failed"
        else:
            status = "not_executed"

        # Build step dictionary
        step = {
            "node_id": node_id,
            "status": status,
            "duration_ms": node_timings.get(node_id, 0),  # Default to 0 if not found
            "cached": node_id in cache_hits,
        }

        # Mark repaired nodes
        if node_id in modified_nodes:
            step["repaired"] = True

        # Add batch metadata if this is a batch node
        # Batch nodes write to shared[node_id] with batch_metadata key
        node_output = shared_storage.get(node_id, {})
        if isinstance(node_output, dict) and "batch_metadata" in node_output:
            step["is_batch"] = True
            step["batch_total"] = node_output.get("count", 0)
            step["batch_success"] = node_output.get("success_count", 0)
            step["batch_errors"] = node_output.get("error_count", 0)
            # Include error details for display (capped at 5 for readability)
            errors = node_output.get("errors") or []
            step["batch_error_details"] = errors[:5]
            step["batch_errors_truncated"] = max(0, len(errors) - 5)

        # Detect shell nodes with stderr output but exit_code=0
        # This helps surface hidden errors from shell pipeline failures
        if isinstance(node_output, dict):
            exit_code = node_output.get("exit_code")
            stderr = node_output.get("stderr", "")
            # Only flag completed nodes with exit_code=0 and non-empty stderr
            if status == "completed" and exit_code == 0 and stderr and isinstance(stderr, str) and stderr.strip():
                step["has_stderr"] = True
                step["stderr"] = stderr.strip()

        steps.append(step)

    return steps
