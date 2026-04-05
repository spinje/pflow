"""Generate Mermaid flowchart diagrams from workflow IR."""

from pathlib import Path
from typing import Any, Callable, Optional

from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult


def generate_mermaid(
    ir: dict[str, Any],
    *,
    resolve_child: Optional[Callable[[dict[str, Any], Optional[Path]], Optional[SubWorkflowResult]]] = None,
    base_path: Optional[Path] = None,
    max_depth: int = 1,
    direction: str = "LR",
) -> str:
    """Generate a Mermaid flowchart from a workflow IR.

    Args:
        ir: Workflow IR dict (must have ``nodes`` and ``edges`` keys)
        resolve_child: Callback to resolve sub-workflow IRs. Signature matches
            ``resolve_sub_workflow(params, base_path)``. Pass None to skip expansion.
        base_path: Directory for resolving relative sub-workflow paths
        max_depth: Maximum sub-workflow expansion depth. 0 = no expansion.
        direction: Graph direction: "LR" (left-to-right) or "TD" (top-down)

    Returns:
        Mermaid flowchart source as a string
    """
    lines: list[str] = [f"graph {direction}"]
    seen: set[str] = set()
    _render_workflow(ir, lines, resolve_child, base_path, max_depth, 0, "", seen, direction)
    return "\n".join(lines) + "\n"


def _render_workflow(
    ir: dict[str, Any],
    lines: list[str],
    resolve_child: Optional[Callable[[dict[str, Any], Optional[Path]], Optional[SubWorkflowResult]]],
    base_path: Optional[Path],
    max_depth: int,
    current_depth: int,
    prefix: str,
    seen: set[str],
    direction: str,
) -> None:
    """Render a single workflow (or sub-workflow) into mermaid lines.

    Args:
        prefix: Node ID prefix for namespacing (e.g., "process_title__")
        seen: Set of resolved paths to prevent cycles
    """
    nodes = ir.get("nodes", [])
    edges = ir.get("edges", [])
    indent = "    " * (current_depth + 1)
    workflow_types = {"workflow", "pflow.runtime.workflow_executor"}

    for node in nodes:
        node_id = node.get("id", "unknown")
        node_type = node.get("type", "unknown")
        mermaid_id = _to_mermaid_id(prefix + node_id)
        label = _escape_label(f"{node_id} ({node_type})")

        # Check if this is a sub-workflow node that should be expanded
        if node_type in workflow_types and resolve_child is not None and current_depth < max_depth:
            child_result = _try_resolve_child(node, resolve_child, base_path, seen)
            if child_result is not None:
                # Track path on recursion stack (prevents A→B→A cycles).
                # Remove after returning so sibling nodes can expand the same child.
                path_key = str(child_result.path) if child_result.path else None
                if path_key:
                    seen.add(path_key)

                # Render as subgraph
                lines.append(f'{indent}subgraph {mermaid_id} ["{label}"]')
                child_base = child_result.path.parent if child_result.path else base_path
                _render_workflow(
                    child_result.ir,
                    lines,
                    resolve_child,
                    child_base,
                    max_depth,
                    current_depth + 1,
                    prefix + node_id + "__",
                    seen,
                    direction,
                )
                lines.append(f"{indent}end")

                if path_key:
                    seen.discard(path_key)
                continue

        # Regular node declaration
        lines.append(f'{indent}{mermaid_id}["{label}"]')

    # Render edges
    for edge in edges:
        from_id = _to_mermaid_id(prefix + edge["from"])
        to_id = _to_mermaid_id(prefix + edge["to"])
        action = edge.get("action")

        if action is None or action == "default":
            # Default/document-order edge: plain arrow
            lines.append(f"{indent}{from_id} --> {to_id}")
        elif action == "error":
            # Error edge: dashed arrow with label
            lines.append(f"{indent}{from_id} -.->|error| {to_id}")
        else:
            # Named action edge: solid arrow with label
            lines.append(f"{indent}{from_id} -->|{_escape_label(action)}| {to_id}")


def _try_resolve_child(
    node: dict[str, Any],
    resolve_child: Callable[[dict[str, Any], Optional[Path]], Optional[SubWorkflowResult]],
    base_path: Optional[Path],
    seen: set[str],
) -> Optional[SubWorkflowResult]:
    """Try to resolve a sub-workflow, returning None on failure.

    Checks the ``seen`` recursion stack for cycles and swallows
    resolution errors (the workflow was already validated — errors
    here are non-fatal for visualization).

    The caller is responsible for adding/removing from ``seen``
    around the recursive render call.
    """
    params = node.get("params", {})
    try:
        result = resolve_child(params, base_path)
    except Exception:
        return None

    if result is None:
        return None

    # Cycle detection: check if this path is already on the recursion stack
    if result.path and str(result.path) in seen:
        return None

    return result


def _to_mermaid_id(node_id: str) -> str:
    """Convert a pflow node ID to a valid Mermaid node ID.

    Returns the ID unchanged — hyphens and underscores are both valid
    in Mermaid's bracket syntax (``id["label"]``), so no sanitization
    is needed. Replacing hyphens with underscores would cause ID
    collisions between ``foo-bar`` and ``foo_bar``.
    """
    return node_id


def _escape_label(text: str) -> str:
    """Escape special characters for Mermaid node labels."""
    return text.replace('"', "&quot;")
