"""Workflow context builder for discovery.

Builds LLM-optimized context strings from saved workflows for use
in workflow discovery and component browsing.
"""

import logging
from typing import Any

from .manager import WorkflowManager

logger = logging.getLogger(__name__)


def _extract_workflow_description(workflow: dict[str, Any]) -> str:
    """Extract description from workflow metadata.

    Args:
        workflow: Workflow metadata dict

    Returns:
        Description string or empty string
    """
    # Get description from workflow metadata (flat structure, no rich_metadata wrapper)
    if workflow.get("description", "").strip():
        return str(workflow["description"]).strip()
    return ""


def _find_flow_start(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], workflow_ir: dict[str, Any]
) -> str | None:
    """Find the starting node for the workflow flow."""
    # Find nodes with no incoming edges
    has_incoming = {str(edge["to"]) for edge in edges}
    start_nodes: list[str] = [str(node["id"]) for node in nodes if str(node["id"]) not in has_incoming]

    if start_nodes:
        return start_nodes[0]

    # Use explicit start_node or first node
    start_node = workflow_ir.get("start_node")
    if start_node:
        return str(start_node)

    if nodes:
        return str(nodes[0]["id"])
    return None


def _build_linear_flow(start_id: str, node_types: dict[str, str], graph: dict[str, list[str]]) -> list[str]:
    """Build a linear flow from a starting node."""
    flow: list[str] = []
    visited: set[str] = set()
    current: str | None = start_id

    while current and current not in visited and current in node_types:
        visited.add(current)
        flow.append(node_types[current])
        # Follow first outgoing edge
        next_nodes = graph.get(current, [])
        current = next_nodes[0] if next_nodes else None

    return flow


def _build_node_flow(workflow_ir: dict[str, Any]) -> str:
    """Build a readable flow string from workflow nodes and edges.

    Uses node IDs (e.g. "get-commits", "classify-commits") rather than
    types (e.g. "shell", "llm") because IDs are author-chosen names that
    describe what each step does, giving the LLM far better matching signal.

    Args:
        workflow_ir: The workflow IR containing nodes and edges

    Returns:
        A flow string like "get-remote -> classify-commits -> write-changelog"
    """
    nodes = workflow_ir.get("nodes", [])
    edges = workflow_ir.get("edges", [])

    if not nodes:
        return ""

    # Check if nodes have IDs (proper IR format) or are simplified (test format)
    first_node = nodes[0]
    has_ids = "id" in first_node

    if not has_ids:
        # Simplified format without IDs - just list node types
        # This handles test cases that create nodes without IDs
        return " + ".join(node.get("type", "unknown") for node in nodes)

    # Map node ID -> node ID (identity) so _build_linear_flow emits IDs
    node_ids: dict[str, str] = {str(node["id"]): str(node["id"]) for node in nodes}

    if not edges:
        # No edges - just list node IDs
        return " + ".join(str(node["id"]) for node in nodes)

    # Build adjacency list
    graph: dict[str, list[str]] = {str(node["id"]): [] for node in nodes}
    for edge in edges:
        from_id = str(edge["from"])
        to_id = str(edge["to"])
        if from_id in graph:
            graph[from_id].append(to_id)

    # Find starting point and build flow
    start_id = _find_flow_start(nodes, edges, workflow_ir)
    if not start_id:
        return " + ".join(str(node["id"]) for node in nodes)

    flow_parts = _build_linear_flow(start_id, node_ids, graph)

    return " → ".join(flow_parts) if flow_parts else ""


def _build_workflow_entry(idx: int, workflow: dict[str, Any]) -> str:
    """Build a single workflow context entry with metadata.

    Args:
        idx: 1-based index for numbered display
        workflow: Workflow metadata dict from WorkflowManager

    Returns:
        Formatted workflow entry string
    """
    name = workflow["name"]
    description = _extract_workflow_description(workflow)

    entry_parts = []

    if description:
        entry_parts.append(f"**{idx}. `{name}`** - {description}")
    else:
        entry_parts.append(f"**{idx}. `{name}`**")

    # Add workflow inputs grouped by required/optional
    ir = workflow.get("ir", {})
    inputs = ir.get("inputs", {}) if ir else {}
    if inputs:
        required = [n for n, s in inputs.items() if s.get("required", True)]
        optional = [n for n, s in inputs.items() if not s.get("required", True)]
        if required:
            entry_parts.append(f"   **Inputs:** {', '.join(required)}")
        if optional:
            entry_parts.append(f"   **Optional:** {', '.join(optional)}")

    # Add node flow to show what the workflow actually does
    if ir:
        node_flow = _build_node_flow(ir)
        if node_flow:
            entry_parts.append(f"   **Flow:** `{node_flow}`")

    # Metadata fields are at top level (flat structure, no rich_metadata wrapper)
    capabilities = workflow.get("capabilities", [])
    if capabilities:
        entry_parts.append(f"   **Can:** {', '.join(capabilities)}")

    use_cases = workflow.get("typical_use_cases", [])
    if use_cases:
        entry_parts.append(f"   **For:** {', '.join(use_cases)}")

    return "\n".join(entry_parts)


def build_workflows_context(
    workflow_names: list[str] | None = None,
    workflow_manager: WorkflowManager | None = None,
) -> str:
    """Build context containing only workflow information as a numbered list.

    Args:
        workflow_names: List of workflow names to include (None = all workflows)
        workflow_manager: Optional WorkflowManager instance.

    Returns:
        Numbered list of workflows with descriptions
    """
    manager = workflow_manager if workflow_manager else WorkflowManager()
    saved_workflows = manager.list_all()

    if workflow_names is not None:
        filtered_workflows = [w for w in saved_workflows if w["name"] in workflow_names]
    else:
        filtered_workflows = saved_workflows

    sorted_workflows = sorted(filtered_workflows, key=lambda w: w["name"])
    sections = [_build_workflow_entry(idx, wf) for idx, wf in enumerate(sorted_workflows, 1)]

    return "\n\n".join(sections).strip()
