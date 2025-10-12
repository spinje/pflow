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

    Example:
        >>> steps = build_execution_steps(workflow_ir, shared_storage, metrics)
        >>> steps[0]
        {
            "node_id": "fetch-data",
            "status": "completed",
            "duration_ms": 150,
            "cached": False
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
            "duration_ms": node_timings.get(node_id),
            "cached": node_id in cache_hits,
        }

        # Mark repaired nodes
        if node_id in modified_nodes:
            step["repaired"] = True

        steps.append(step)

    return steps
