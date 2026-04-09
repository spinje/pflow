"""Data flow validation for workflow execution order and dependencies.

This module ensures that workflows have correct execution order and that
all data dependencies are satisfied before nodes execute.
"""

import re
from typing import Any, Optional

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.suggestion_utils import find_similar_items
from pflow.runtime.template_resolver import TemplateResolver

# Positive match for pflow variable paths (e.g., "node", "node.field", "node[0].field").
# Uses TemplateResolver._VAR_NAME_PATTERN as the canonical definition of valid pflow
# variable names. This is a private attribute — if the pattern changes there, it must
# change here too.
_PFLOW_VAR_RE = re.compile(rf"^{TemplateResolver._VAR_NAME_PATTERN}$")


class CycleError(Exception):
    """Raised when circular dependency is detected in workflow."""

    def __init__(self, nodes_in_cycle: set[str]) -> None:
        self.nodes_in_cycle = sorted(nodes_in_cycle)
        super().__init__(f"Circular dependency detected involving nodes: {', '.join(self.nodes_in_cycle)}")


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
    node_list = workflow_ir.get("nodes", [])
    nodes = {node["id"] for node in node_list}

    # Node positions for determining edge direction
    node_positions = {node["id"]: i for i, node in enumerate(node_list)}

    # Build adjacency list
    graph: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    in_degree: dict[str, int] = dict.fromkeys(nodes, 0)

    for edge in edges:
        if edge.get("from") and edge.get("to"):
            # Skip edges referencing nodes not in the graph (caught by wiring step later)
            if edge["from"] not in nodes or edge["to"] not in nodes:
                continue

            action = edge.get("action")
            source_pos = node_positions.get(edge["from"], -1)
            target_pos = node_positions.get(edge["to"], -1)

            # Include edge if:
            # - No action (document-order edges — always forward)
            # - Any edge going forward (branch targets, error handlers, skip-ahead)
            # Exclude backward edges (retry loops, error-to-earlier) to avoid cycles.
            if action is None or source_pos < target_pos:
                graph[edge["from"]].append(edge["to"])
                in_degree[edge["to"]] += 1

    # Topological sort using Kahn's algorithm.
    # Use document order (node_positions) as tiebreaker for equal in-degree
    # to give deterministic results and honor the author's intended order
    # for disconnected components (e.g., branch targets with no incoming edges).
    queue = sorted(
        [node for node in nodes if in_degree[node] == 0],
        key=lambda n: node_positions.get(n, 0),
    )
    order = []

    while queue:
        node = queue.pop(0)
        order.append(node)
        new_ready = []
        for neighbor in graph.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                new_ready.append(neighbor)
        # Insert newly ready nodes in document order
        if new_ready:
            new_ready.sort(key=lambda n: node_positions.get(n, 0))
            queue.extend(new_ready)

    # Check for cycles
    if len(order) != len(nodes):
        # Find nodes involved in cycle
        remaining = nodes - set(order)
        raise CycleError(remaining)

    return order


def _check_forward_reference(
    node_id: str,
    param_name: str,
    ref_node_id: str,
    node_position: int,
    node_positions: dict[str, int],
    loop_forward_limits: dict[str, int],
) -> Optional[Diagnostic]:
    """Check if a node reference is a disallowed forward reference.

    Returns error diagnostic if ref_node_id comes after node_id in execution order
    and is not part of a valid loop pattern. Returns None if the reference is valid.
    """
    if ref_node_id not in node_positions:
        return None
    ref_position = node_positions[ref_node_id]
    if ref_position < node_position:
        return None
    # Allow forward references for loop targets — backward edges with actions
    # indicate valid PocketFlow retry/loop patterns.
    max_allowed = loop_forward_limits.get(node_id)
    if max_allowed is not None and ref_position <= max_allowed:
        return None
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Node '{node_id}' references '{ref_node_id}' in parameter '{param_name}', "
            f"but '{ref_node_id}' comes after this node in execution order "
            f"(position {ref_position} >= {node_position})."
        ),
        suggestions=[f"Reorder nodes so '{ref_node_id}' appears before '{node_id}'."],
        context={
            "category": "validation",
            "path": f"nodes[id={node_id}].params.{param_name}",
            "referenced_node": ref_node_id,
        },
    )


def _validate_template_reference(
    ref: str,
    node_id: str,
    param_name: str,
    node_position: int,
    nodes_by_id: dict[str, Any],
    node_positions: dict[str, int],
    declared_inputs: set[str],
    loop_forward_limits: dict[str, int],
    check_inputs: bool,
) -> Optional[Diagnostic]:
    """Validate a single template reference.

    Args:
        ref: The template reference (e.g., "node1.output" or "input_param")
        node_id: ID of the node containing the reference
        param_name: Parameter name containing the reference
        node_position: Position of the current node in execution order
        nodes_by_id: Mapping of node IDs to node objects
        node_positions: Mapping of node IDs to execution positions
        declared_inputs: All valid simple refs for this node context
            (workflow inputs + batch aliases + node-level params.inputs keys)
        loop_forward_limits: For loop targets, the max position they can reference
        check_inputs: Whether to validate undefined input references

    Returns:
        Error diagnostic if invalid, None if valid
    """
    # Only validate refs that match pflow variable syntax. Non-matching refs
    # are bash syntax (${#count}, ${var:-default}, ${array[@]}), or truncated
    # nested templates (${results[${__index__}) — skip them.
    if not _PFLOW_VAR_RE.match(ref):
        return None

    # Extract root identifier (before first . or [)
    root = TemplateResolver.extract_root_node_id(ref)
    has_path = root != ref

    if has_path:  # Node output reference like ${node1.output} or ${data[0].field}
        ref_node_id = root

        # Check if referenced node exists (also allow batch aliases like "item")
        if ref_node_id not in nodes_by_id and ref_node_id not in declared_inputs:
            if not check_inputs:
                return None  # Could be a runtime param — compiler lacks context
            candidates = sorted(set(nodes_by_id.keys()) | declared_inputs)
            similar = find_similar_items(ref_node_id, candidates, max_results=3, method="fuzzy")
            context: dict[str, Any] = {
                "category": "validation",
                "path": f"nodes[id={node_id}].params.{param_name}",
                "available_fields": sorted(nodes_by_id.keys()),
                "available_fields_total": len(nodes_by_id),
                "available_fields_label": "nodes",
            }
            if similar:
                context["similar_names"] = similar
            return Diagnostic(
                severity=Severity.ERROR,
                source="validator",
                title="Validation Error",
                node_id=node_id,
                message=f"Node '{node_id}' references non-existent node '{ref_node_id}' in parameter '{param_name}'.",
                suggestions=[f"Did you mean '{similar[0]}'?"] if similar else None,
                context=context,
            )
        # Check if referenced node comes before this node
        return _check_forward_reference(
            node_id,
            param_name,
            ref_node_id,
            node_position,
            node_positions,
            loop_forward_limits,
        )

    # Input parameter reference like ${repo_name}
    if not check_inputs:
        return None
    if ref not in declared_inputs:
        close_matches = [inp for inp in declared_inputs if inp.lower() == ref.lower()]
        if close_matches:
            return Diagnostic(
                severity=Severity.ERROR,
                source="validator",
                title="Validation Error",
                node_id=node_id,
                message=f"Node '{node_id}' references undefined input '${{{ref}}}' in parameter '{param_name}'.",
                suggestions=[f"Did you mean '${{{close_matches[0]}}}'?"],
                context={
                    "category": "validation",
                    "path": f"nodes[id={node_id}].params.{param_name}",
                    "template": f"${{{ref}}}",
                    "similar_names": [f"${{{match}}}" for match in close_matches[:3]],
                },
            )
        if not declared_inputs:
            return Diagnostic(
                severity=Severity.ERROR,
                source="validator",
                title="Validation Error",
                node_id=node_id,
                message=(
                    f"Node '{node_id}' references '${{{ref}}}' in parameter '{param_name}' "
                    f"but no inputs are declared in this workflow."
                ),
                suggestions=[
                    f"Declare '{ref}' under '## Inputs' or use a node output reference like ${{node_id.field}}."
                ],
                context={
                    "category": "validation",
                    "path": f"nodes[id={node_id}].params.{param_name}",
                    "template": f"${{{ref}}}",
                },
            )
        sorted_inputs = sorted(declared_inputs)
        return Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            title="Validation Error",
            node_id=node_id,
            message=f"Node '{node_id}' references undefined input '${{{ref}}}' in parameter '{param_name}'.",
            context={
                "category": "validation",
                "path": f"nodes[id={node_id}].params.{param_name}",
                "template": f"${{{ref}}}",
                "available_fields": sorted_inputs,
                "available_fields_total": len(sorted_inputs),
                "available_fields_label": "inputs",
            },
        )
    return None


def validate_data_flow(
    workflow_ir: dict[str, Any],
    check_inputs: bool = True,
) -> list[Diagnostic]:
    """Validate that data flows correctly between nodes.

    This function checks:
    - Circular dependencies in the workflow (always)
    - Forward references to nodes that come later in execution order (always)
    - References to non-existent nodes (always when check_inputs=True;
      skips ambiguous refs when False — they could be runtime params)
    - References to undefined input parameters (only when check_inputs=True)

    The check_inputs parameter controls semantic checks that depend on knowing
    all available variable sources. The compiler passes False because it has
    initial_params that legitimately contain variables not declared in IR inputs.
    The pre-execution WorkflowValidator passes True (default) because it runs
    after all variable sources are known.

    Args:
        workflow_ir: The workflow IR to validate
        check_inputs: Whether to validate undefined input references

    Returns:
        List of validation diagnostics (empty if valid)
    """
    diagnostics: list[Diagnostic] = []

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
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                source="validator",
                title="Validation Error",
                message=f"Circular dependency detected involving nodes: {', '.join(e.nodes_in_cycle)}",
                suggestions=["Remove or reorder edges to break the cycle."],
                context={
                    "category": "validation",
                    "cycle_nodes": e.nodes_in_cycle,
                },
            )
        )
        return diagnostics

    # Compute loop forward limits: for each backward edge B→A (with action),
    # node A can reference nodes up to B's position (valid in subsequent iterations).
    loop_forward_limits: dict[str, int] = {}
    for edge in workflow_ir.get("edges", []):
        if edge.get("from") and edge.get("to"):
            action = edge.get("action")
            source_pos = node_positions.get(edge["from"], -1)
            target_pos = node_positions.get(edge["to"], -1)
            if action is not None and source_pos >= target_pos:
                target = edge["to"]
                loop_forward_limits[target] = max(loop_forward_limits.get(target, 0), source_pos)

    # Check each node's parameter references
    for node in workflow_ir.get("nodes", []):
        node_id = node.get("id")
        node_position = node_positions.get(node_id, -1)
        _validate_node_params(
            node,
            node_id,
            node_position,
            nodes_by_id,
            node_positions,
            valid_simple_refs,
            loop_forward_limits,
            check_inputs,
            diagnostics,
        )

    return diagnostics


def _check_param_value(
    param_name: str,
    value: Any,
    node_id: str,
    node_position: int,
    nodes_by_id: dict[str, Any],
    node_positions: dict[str, int],
    valid_simple_refs: set[str],
    loop_forward_limits: dict[str, int],
    check_inputs: bool,
    errors: list[Diagnostic],
) -> None:
    """Recursively validate template references in a parameter value."""
    if isinstance(value, str) and "${" in value:
        for match in TemplateResolver.TEMPLATE_EXTRACT_PATTERN.finditer(value):
            for operand in TemplateResolver.split_coalesce_operands(match.group(1)):
                error = _validate_template_reference(
                    operand,
                    node_id,
                    param_name,
                    node_position,
                    nodes_by_id,
                    node_positions,
                    valid_simple_refs,
                    loop_forward_limits,
                    check_inputs,
                )
                if error:
                    errors.append(error)
    elif isinstance(value, dict):
        # Thread the dict key into param_name so diagnostics for nested values
        # report the deepest path (e.g. ``headers.Authorization`` instead of
        # just ``headers``).
        for key, val in value.items():
            _check_param_value(
                f"{param_name}.{key}",
                val,
                node_id,
                node_position,
                nodes_by_id,
                node_positions,
                valid_simple_refs,
                loop_forward_limits,
                check_inputs,
                errors,
            )
    elif isinstance(value, list):
        # Thread the list index into param_name so diagnostics for list items
        # report the deepest path (e.g. ``commands[1]`` instead of just
        # ``commands``).
        for index, item in enumerate(value):
            _check_param_value(
                f"{param_name}[{index}]",
                item,
                node_id,
                node_position,
                nodes_by_id,
                node_positions,
                valid_simple_refs,
                loop_forward_limits,
                check_inputs,
                errors,
            )


def _validate_node_params(
    node: dict[str, Any],
    node_id: str,
    node_position: int,
    nodes_by_id: dict[str, Any],
    node_positions: dict[str, int],
    valid_simple_refs: set[str],
    loop_forward_limits: dict[str, int],
    check_inputs: bool,
    errors: list[Diagnostic],
) -> None:
    """Validate template references in a single node's parameters."""
    # If node has 'inputs' mapping, its keys are valid template references
    # for other params in the same node (inputs-as-context pattern)
    node_refs = valid_simple_refs
    inputs_param = node.get("params", {}).get("inputs")
    if isinstance(inputs_param, dict):
        node_refs = valid_simple_refs | set(inputs_param.keys())

    for param_name, param_value in node.get("params", {}).items():
        _check_param_value(
            param_name,
            param_value,
            node_id,
            node_position,
            nodes_by_id,
            node_positions,
            node_refs,
            loop_forward_limits,
            check_inputs,
            errors,
        )
