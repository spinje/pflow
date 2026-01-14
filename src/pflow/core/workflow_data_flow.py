"""Data flow validation for workflow execution order and dependencies.

This module ensures that workflows have correct execution order and that
all data dependencies are satisfied before nodes execute.
"""

import re
from typing import Any, Optional


class CycleError(Exception):
    """Raised when circular dependency is detected in workflow."""

    pass


def build_execution_order(workflow_ir: dict[str, Any]) -> list[str]:
    """Build the execution order of nodes based on edges using topological sort.

    Args:
        workflow_ir: The workflow IR containing nodes and edges

    Returns:
        List of node IDs in execution order

    Raises:
        CycleError: If circular dependency is detected
    """
    edges = workflow_ir.get("edges", [])
    nodes = {node["id"] for node in workflow_ir.get("nodes", [])}

    # Build adjacency list
    graph: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    in_degree: dict[str, int] = dict.fromkeys(nodes, 0)

    for edge in edges:
        if edge.get("from") and edge.get("to"):
            graph[edge["from"]].append(edge["to"])
            in_degree[edge["to"]] += 1

    # Topological sort using Kahn's algorithm
    queue = [node for node in nodes if in_degree[node] == 0]
    order = []

    while queue:
        node = queue.pop(0)
        order.append(node)
        for neighbor in graph.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # Check for cycles
    if len(order) != len(nodes):
        # Find nodes involved in cycle
        remaining = nodes - set(order)
        raise CycleError(f"Circular dependency detected involving nodes: {', '.join(sorted(remaining))}")

    return order


def _is_bash_syntax(ref: str) -> bool:
    """Check if a template reference is bash-specific syntax, not a pflow template.

    Bash-specific patterns include:
    - Array operations: ${#array[@]}, ${array[@]}, ${array[*]}, ${array[$i]}
    - String manipulation: ${var%%pattern}, ${var##pattern}, ${var/pattern/replacement}
    - Default values: ${var:-default}, ${var:=default}, ${var:?error}, ${var:+value}
    - Substring: ${var:offset:length}
    - Length: ${#var}
    - Case modification: ${var^^}, ${var,,}, ${var^}, ${var,}

    Args:
        ref: The content inside ${...} (e.g., "#array[@]" from "${#array[@]}")

    Returns:
        True if this is bash-specific syntax, False if it could be a pflow template
    """
    # Bash array syntax with brackets
    if "[" in ref or "]" in ref:
        return True

    # Bash string operations (contains special operators)
    bash_operators = ["%%", "##", ":-", ":=", ":?", ":+", "/", "^^", ",,"]
    if any(op in ref for op in bash_operators):
        return True

    # Bash length operator at start
    if ref.startswith("#"):
        return True

    # Bash substring syntax (contains colon but not at start, which would be special operators)
    if ":" in ref and not ref.startswith(":"):
        # Check if it's a substring operation like ${var:2:5}
        # But not parameter expansion like ${var:-default} (already caught above)
        parts = ref.split(":")
        if len(parts) >= 2:
            # If the part after : looks like a number/offset, it's bash substring
            try:
                int(parts[1].strip())
                return True
            except ValueError:
                pass

    return False


def _validate_template_reference(
    ref: str,
    node_id: str,
    param_name: str,
    node_position: int,
    nodes_by_id: dict[str, Any],
    node_positions: dict[str, int],
    declared_inputs: set[str],
) -> Optional[str]:
    """Validate a single template reference.

    Args:
        ref: The template reference (e.g., "node1.output" or "input_param")
        node_id: ID of the node containing the reference
        param_name: Parameter name containing the reference
        node_position: Position of the current node in execution order
        nodes_by_id: Mapping of node IDs to node objects
        node_positions: Mapping of node IDs to execution positions
        declared_inputs: Set of declared input parameters

    Returns:
        Error message if invalid, None if valid
    """
    # Skip validation for bash-specific syntax (but still validate pflow templates)
    if _is_bash_syntax(ref):
        return None

    if "." in ref:  # Node output reference like ${node1.output}
        parts = ref.split(".", 1)
        ref_node_id = parts[0]

        # Check if referenced node exists (also allow batch aliases like "item")
        if ref_node_id not in nodes_by_id and ref_node_id not in declared_inputs:
            return f"Node '{node_id}' references non-existent node '{ref_node_id}' in parameter '{param_name}'"
        # Check if referenced node comes before this node
        elif ref_node_id in node_positions:
            ref_position = node_positions[ref_node_id]
            if ref_position >= node_position:
                return (
                    f"Node '{node_id}' references '{ref_node_id}' which comes "
                    f"after it in execution order (position {ref_position} >= {node_position})"
                )
    else:  # Input parameter reference like ${repo_name}
        if ref not in declared_inputs:
            # Check if it's a typo of an existing input
            close_matches = [inp for inp in declared_inputs if inp.lower() == ref.lower()]
            if close_matches:
                return (
                    f"Node '{node_id}' references undefined input '${{{ref}}}' "
                    f"in parameter '{param_name}' - did you mean '${{{close_matches[0]}}}'?"
                )
            else:
                return f"Node '{node_id}' references undefined input '${{{ref}}}' in parameter '{param_name}'"
    return None


def validate_data_flow(workflow_ir: dict[str, Any]) -> list[str]:
    """Validate that data flows correctly between nodes.

    This function checks:
    - References to non-existent nodes
    - References to nodes that come later in execution order
    - References to undefined input parameters
    - Circular dependencies in the workflow

    Args:
        workflow_ir: The workflow IR to validate

    Returns:
        List of error messages (empty if valid)
    """
    errors: list[str] = []

    nodes_by_id = {node["id"]: node for node in workflow_ir.get("nodes", [])}
    declared_inputs = set(workflow_ir.get("inputs", {}).keys())

    # Extract batch item aliases - these are valid variable references within batch nodes
    # Note: This is a permissive check - we allow batch aliases globally rather than
    # tracking which node each template belongs to. Runtime will catch invalid usage.
    batch_item_aliases: set[str] = set()
    has_batch_nodes = False
    for node in workflow_ir.get("nodes", []):
        batch_config = node.get("batch")
        if batch_config:
            has_batch_nodes = True
            item_alias = batch_config.get("as", "item")
            batch_item_aliases.add(item_alias)

    # Combine declared inputs with batch item aliases for validation
    valid_simple_refs = declared_inputs | batch_item_aliases

    # __index__ is auto-injected in batch contexts (0-based batch item index)
    if has_batch_nodes:
        valid_simple_refs.add("__index__")

    # Build execution order
    try:
        node_order = build_execution_order(workflow_ir)
        node_positions = {node_id: i for i, node_id in enumerate(node_order)}
    except CycleError as e:
        errors.append(f"Data flow error: {e!s}")
        return errors

    # Check each node's parameter references
    for node in workflow_ir.get("nodes", []):
        node_id = node.get("id")
        node_position = node_positions.get(node_id, -1)

        for param_name, param_value in node.get("params", {}).items():
            if isinstance(param_value, str) and "${" in param_value:
                # Find all template variable references
                for match in re.finditer(r"\$\{([^}]+)\}", param_value):
                    ref = match.group(1)
                    error = _validate_template_reference(
                        ref, node_id, param_name, node_position, nodes_by_id, node_positions, valid_simple_refs
                    )
                    if error:
                        errors.append(error)

    return errors
