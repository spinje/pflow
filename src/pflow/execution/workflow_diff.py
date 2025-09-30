"""Workflow diff utilities for tracking repair modifications."""


def _get_param_changes(original_params: dict, repaired_params: dict) -> list[str]:
    """Identify specific parameter changes between original and repaired nodes.

    Args:
        original_params: Original node parameters
        repaired_params: Repaired node parameters

    Returns:
        List of parameter changes
    """
    changes = []

    # Check for ignore_errors addition
    if "ignore_errors" in repaired_params and "ignore_errors" not in original_params:
        changes.append("ignore_errors added")
    # Check for command changes
    elif "command" in repaired_params and original_params.get("command") != repaired_params.get("command"):
        changes.append("command modified")
    # Check for prompt changes
    elif "prompt" in repaired_params and original_params.get("prompt") != repaired_params.get("prompt"):
        changes.append("prompt modified")
    else:
        # Generic params change
        changes.append("params")

    return changes


def _compare_node(original_node: dict, repaired_node: dict) -> list[str]:
    """Compare a single node between original and repaired versions.

    Args:
        original_node: Original node configuration
        repaired_node: Repaired node configuration

    Returns:
        List of changes found in the node
    """
    changes = []

    # Check params
    if original_node.get("params") != repaired_node.get("params"):
        orig_params = original_node.get("params", {})
        new_params = repaired_node.get("params", {})
        changes.extend(_get_param_changes(orig_params, new_params))

    # Check type
    if original_node.get("type") != repaired_node.get("type"):
        changes.append("type")

    return changes


def _find_added_and_modified_nodes(
    original_nodes: dict[str, dict], repaired_nodes: dict[str, dict]
) -> dict[str, list[str]]:
    """Find nodes that were added or modified in the repaired workflow.

    Args:
        original_nodes: Dictionary of original nodes by ID
        repaired_nodes: Dictionary of repaired nodes by ID

    Returns:
        Dictionary mapping node_id to list of changes
    """
    modifications = {}

    for node_id, repaired_node in repaired_nodes.items():
        if node_id not in original_nodes:
            modifications[node_id] = ["added"]
        else:
            changes = _compare_node(original_nodes[node_id], repaired_node)
            if changes:
                modifications[node_id] = changes

    return modifications


def compute_workflow_diff(original_ir: dict, repaired_ir: dict) -> dict[str, list[str]]:
    """Compare two workflow IRs and return what changed.

    Args:
        original_ir: The original workflow IR
        repaired_ir: The repaired workflow IR

    Returns:
        Dict mapping node_id to list of changed fields
    """
    # Build node dictionaries indexed by ID
    original_nodes = {n["id"]: n for n in original_ir.get("nodes", [])}
    repaired_nodes = {n["id"]: n for n in repaired_ir.get("nodes", [])}

    # Find added and modified nodes
    modifications = _find_added_and_modified_nodes(original_nodes, repaired_nodes)

    # Check for removed nodes
    for node_id in original_nodes:
        if node_id not in repaired_nodes:
            modifications[node_id] = ["removed"]

    return modifications
