"""Core rendering pipeline: generate_mermaid, _render_workflow, _render_node, batch, subgraph."""

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from pflow.core.workflow.mermaid._context import (
    _WORKFLOW_TYPES,
    MermaidConfig,
    MermaidContext,
    _classdef_to_style,
    _dynamic_batch_label,
    _escape_label,
    _first_sentence,
    _format_label,
    _format_node_type,
    _get_item_label,
    _get_node_shape,
    _render_classdefs,
    _subgraph_style,
    _to_mermaid_id,
)
from pflow.core.workflow.mermaid._edges import (
    _deduplicate_edges,
    _detect_decision_nodes,
    _find_terminal_nodes,
    _generate_batch_item_data_flow,
    _generate_data_flow_edges,
    _render_edge,
)
from pflow.core.workflow.mermaid._io import (
    _connect_top_level_inputs,
    _render_external_inputs,
    _render_external_outputs,
    _render_inputs,
    _render_subworkflow_inputs,
    _render_subworkflow_outputs,
    _render_top_level_outputs,
)
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult

logger = logging.getLogger("pflow.core.workflow.mermaid")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_mermaid(
    ir: dict[str, Any],
    *,
    resolve_child: Optional[Callable[[dict[str, Any], Optional[Path]], Optional[SubWorkflowResult]]] = None,
    base_path: Optional[Path] = None,
    max_depth: int = 1,
    direction: str = "LR",
    descriptions: bool = False,
) -> str:
    """Generate a Mermaid flowchart from a workflow IR.

    Args:
        ir: Workflow IR dict (must have ``nodes`` and ``edges`` keys)
        resolve_child: Callback to resolve sub-workflow IRs. Signature matches
            ``resolve_sub_workflow(params, base_path)``. Pass None to skip expansion.
        base_path: Directory for resolving relative sub-workflow paths
        max_depth: Maximum sub-workflow expansion depth. 0 = no expansion.
        direction: Graph direction: "LR" (left-to-right) or "TD" (top-down)
        descriptions: If True, add first sentence of node purpose to labels

    Returns:
        Mermaid flowchart source as a string
    """
    config = MermaidConfig(
        resolve_child=resolve_child,
        max_depth=max_depth,
        direction=direction,
        descriptions=descriptions,
    )
    lines: list[str] = [f"graph {direction}"]
    seen: set[str] = set()
    ctx = MermaidContext(config=config, lines=lines, seen=seen, base_path=base_path)

    _render_classdefs(ctx)
    _render_inputs(ir, ctx)
    _render_workflow(ir, ctx)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Core rendering
# ---------------------------------------------------------------------------


def _render_workflow(ir: dict[str, Any], ctx: MermaidContext) -> dict[str, dict[str, str]]:
    """Render a single workflow (or sub-workflow) into mermaid lines.

    Returns:
        The ``outgoing_routes`` built during rendering — maps subgraph mermaid IDs
        to their output node IDs. Needed by the parent to route edges through
        nested sub-workflow outputs.
    """
    nodes = ir.get("nodes", [])
    edges = ir.get("edges", [])

    deduped_edges = _deduplicate_edges(edges)
    ctx.decision_nodes = _detect_decision_nodes(edges)
    ctx.parent_inputs = ir.get("inputs", {})
    ctx.sibling_node_ids = {n.get("id", "") for n in nodes}

    # Sub-workflow boundary: render inputs at top (unless parent handles IO)
    if ctx.current_depth > 0 and not ctx.suppress_io:
        _render_subworkflow_inputs(ir, ctx)

    for node in nodes:
        _render_node(node, ctx)

    # Top-level: connect inputs to consuming nodes (now that incoming_map is populated)
    if ctx.current_depth == 0:
        _connect_top_level_inputs(ir, ctx)

    # Sub-workflow boundary: render outputs (unless parent handles IO)
    output_ids = _render_subworkflow_outputs(ir, ctx) if ctx.current_depth > 0 and not ctx.suppress_io else []

    # Top-level: render workflow outputs at the bottom
    if ctx.current_depth == 0:
        output_ids = _render_top_level_outputs(ir, ctx)

    _render_end_nodes_and_edges(ir, deduped_edges, output_ids, ctx)

    return ctx.outgoing_routes


def _render_node(node: dict[str, Any], ctx: MermaidContext) -> None:
    """Render a single node declaration (regular, batch, or sub-workflow)."""
    node_id = node.get("id", "unknown")
    node_type = node.get("type", "unknown")
    mermaid_id = _to_mermaid_id(ctx.prefix + node_id)
    purpose = node.get("purpose", "")
    batch = node.get("batch")

    # Batch with inline items: fork/join rendering
    if batch and isinstance(batch.get("items"), list):
        _render_batch_inline(
            node,
            batch["items"],
            batch.get("parallel", False),
            node_type,
            ctx,
        )
        return

    # Compute batch label for dynamic batch
    dynamic_batch_label = _dynamic_batch_label(batch)

    # Sub-workflow expansion
    if (
        node_type in _WORKFLOW_TYPES
        and ctx.config.resolve_child is not None
        and ctx.current_depth < ctx.config.max_depth
    ):
        child_result = _try_resolve_child(node, ctx)
        if child_result is not None:
            # 1. External input wrapper (BEFORE subgraph)
            _render_external_inputs(child_result.ir, node_id, ctx)

            # 2. Subgraph with suppress_io=True (NO internal IO)
            child_outgoing = _render_subgraph(
                node_id,
                node_type,
                mermaid_id,
                dynamic_batch_label,
                child_result,
                ctx,
                purpose=purpose,
                suppress_io=True,
            )

            # 3. External output wrapper (AFTER subgraph, replaces _populate_outgoing_map)
            _render_external_outputs(child_result.ir, node_id, ctx, child_outgoing)

            # 4. Data-flow edges and routing maps
            child_inputs = child_result.ir.get("inputs", {})
            if child_inputs:
                child_prefix = ctx.prefix + node_id + "__"
                has_data_flow = _generate_data_flow_edges(node, child_result.ir, child_prefix, ctx)
                if has_data_flow:
                    ctx.data_flow_targets.add(mermaid_id)
                ctx.incoming_map[mermaid_id] = {
                    name: _to_mermaid_id(f"{child_prefix}in_{name}") for name in child_inputs
                }
            return

    # Regular node declaration
    is_decision = node_id in ctx.decision_nodes
    label = _format_label(node_id, node_type, ctx.config.descriptions, purpose, dynamic_batch_label)

    if dynamic_batch_label:
        # Dynamic batch: use procs (stacked rectangles) shape via @{} syntax.
        # Can't combine with :::classDef — use style directive instead.
        ctx.lines.append(f'{ctx.indent}{mermaid_id}@{{ shape: procs, label: "{label}" }}')
        _, _, css_class = _get_node_shape(node_type, is_decision)
        ctx.lines.append(f"{ctx.indent}style {mermaid_id} {_classdef_to_style(css_class)}")
    else:
        shape_open, shape_close, css_class = _get_node_shape(node_type, is_decision)
        ctx.lines.append(f'{ctx.indent}{mermaid_id}{shape_open}"{label}"{shape_close}:::{css_class}')


# ---------------------------------------------------------------------------
# Batch rendering
# ---------------------------------------------------------------------------


def _render_batch_inline(
    node: dict[str, Any],
    items: list[Any],
    is_parallel: bool,
    node_type: str,
    ctx: MermaidContext,
) -> None:
    """Render a batch node with inline items as fork/join or 2+ellipsis subgraph.

    - <=4 items: show ALL items by name (fork/join pattern)
    - >4 items: show first 2 items + ellipsis node with count

    When the parent node is a workflow type and items have literal ``workflow``
    keys, each item is resolved and expanded as a subgraph.

    After rendering, generates data-flow edges from the parent node's params
    to each expanded item's input nodes (batch item data-flow).

    Populates ``fork_join_map`` so edge rendering can fan-out/fan-in.
    """
    node_id = node["id"]
    mermaid_id = _to_mermaid_id(ctx.prefix + node_id)

    render_items = items if len(items) <= 4 else items[:2]
    parallel_str = "parallel " if is_parallel else ""
    subgraph_label = _escape_label(f"{node_id} ({parallel_str}x{len(items)})")

    ctx.lines.append(f'{ctx.indent}subgraph {mermaid_id} ["{subgraph_label}"]')
    inner_indent = ctx.indent + "    "

    collected_ids: list[str] = []
    expanded_items: list[tuple[str, dict[str, Any]]] = []  # (item_label, child_ir)
    shape_open, shape_close, css_class = _get_node_shape(node_type, False)
    can_expand = (
        node_type in _WORKFLOW_TYPES
        and ctx.config.resolve_child is not None
        and ctx.current_depth < ctx.config.max_depth
    )

    for i, item in enumerate(render_items):
        item_label = _get_item_label(item, i)
        item_mermaid_id = _to_mermaid_id(ctx.prefix + node_id + "__" + item_label)

        # Try to expand workflow items as subgraphs
        child_ir: Optional[dict[str, Any]] = None
        if can_expand:
            child_ir = _try_expand_batch_item(
                item,
                item_label,
                item_mermaid_id,
                ctx.prefix + node_id + "__",
                ctx,
            )
        if child_ir is not None:
            expanded_items.append((item_label, child_ir))
            collected_ids.append(item_mermaid_id)
            # Populate outgoing_routes so structural edges route through item's outputs
            child_outputs = child_ir.get("outputs", {})
            if child_outputs:
                item_prefix = ctx.prefix + node_id + "__" + item_label + "__"
                ctx.outgoing_routes[item_mermaid_id] = {
                    name: _to_mermaid_id(f"{item_prefix}out_{name}") for name in child_outputs
                }
                ctx.has_expanded_outputs.add(item_mermaid_id)
            continue

        display_label = _escape_label(f"{item_label} ({_format_node_type(node_type)})")
        ctx.lines.append(f'{inner_indent}{item_mermaid_id}{shape_open}"{display_label}"{shape_close}:::{css_class}')
        collected_ids.append(item_mermaid_id)

    if len(items) > 4:
        dots_id = _to_mermaid_id(ctx.prefix + node_id + "__dots")
        dots_label = f"... x{len(items)}"
        ctx.lines.append(f'{inner_indent}{dots_id}@{{ shape: procs, label: "{_escape_label(dots_label)}" }}')
        ctx.lines.append(f"{inner_indent}style {dots_id} {_classdef_to_style(css_class)}")
        collected_ids.append(dots_id)

    ctx.lines.append(f"{ctx.indent}end")
    ctx.lines.append(f"{ctx.indent}{_subgraph_style(mermaid_id, ctx.current_depth + 1)}")
    ctx.fork_join_map[mermaid_id] = collected_ids

    # Batch item data-flow edges: connect parent params to each item's inputs.
    # Returns set of item IDs that have data-flow coverage — these are added
    # to data_flow_targets so structural edges (through fork_join_map) to them
    # are suppressed (avoiding duplicate connections).
    if expanded_items:
        items_with_df = _generate_batch_item_data_flow(node, expanded_items, ctx)
        if items_with_df:
            ctx.data_flow_targets.update(items_with_df)


def _try_expand_batch_item(
    item: Any,
    item_label: str,
    item_mermaid_id: str,
    prefix: str,
    ctx: MermaidContext,
) -> Optional[dict[str, Any]]:
    """Try to resolve and expand a batch item's workflow as a subgraph.

    Returns the child IR dict if expanded, None if it should render as opaque.
    """
    if not isinstance(item, dict):
        return None
    workflow_path = item.get("workflow")
    if not isinstance(workflow_path, str) or workflow_path.startswith("${"):
        return None

    child_result = _try_resolve_child(
        {"params": {"workflow": workflow_path}},
        ctx,
    )
    if child_result is None:
        return None

    path_key = str(child_result.path) if child_result.path else None
    if path_key:
        ctx.seen.add(path_key)

    inner_indent = ctx.indent + "    "
    subgraph_label = _escape_label(f"{item_label} (workflow)")
    ctx.lines.append(f'{inner_indent}subgraph {item_mermaid_id} ["{subgraph_label}"]')

    child_base = child_result.path.parent if child_result.path else ctx.base_path
    child_ctx = ctx.child(prefix=prefix + item_label + "__", base_path=child_base)
    _render_workflow(child_result.ir, child_ctx)

    ctx.lines.append(f"{inner_indent}end")
    ctx.lines.append(f"{inner_indent}{_subgraph_style(item_mermaid_id, ctx.current_depth + 1)}")

    if path_key:
        ctx.seen.discard(path_key)
    return child_result.ir


# ---------------------------------------------------------------------------
# Subgraph rendering
# ---------------------------------------------------------------------------


def _render_subgraph(
    node_id: str,
    node_type: str,
    mermaid_id: str,
    dynamic_batch_label: str,
    child_result: SubWorkflowResult,
    ctx: MermaidContext,
    purpose: str = "",
    suppress_io: bool = False,
) -> dict[str, dict[str, str]]:
    """Render a sub-workflow as a mermaid subgraph.

    Returns the child's ``outgoing_routes`` so the parent can route edges
    through nested sub-workflow outputs.
    """
    path_key = str(child_result.path) if child_result.path else None
    if path_key:
        ctx.seen.add(path_key)

    if dynamic_batch_label:
        subgraph_label = _escape_label(node_id) + dynamic_batch_label
    else:
        subgraph_label = _escape_label(f"{node_id} ({node_type})")
    if ctx.config.descriptions and purpose:
        subgraph_label += f"<br/>{_escape_label(_first_sentence(purpose))}"

    ctx.lines.append(f'{ctx.indent}subgraph {mermaid_id} ["{subgraph_label}"]')

    child_base = child_result.path.parent if child_result.path else ctx.base_path
    child_ctx = ctx.child(prefix=ctx.prefix + node_id + "__", suppress_io=suppress_io, base_path=child_base)
    child_outgoing = _render_workflow(child_result.ir, child_ctx)

    ctx.lines.append(f"{ctx.indent}end")
    ctx.lines.append(f"{ctx.indent}{_subgraph_style(mermaid_id, ctx.current_depth + 1)}")

    if path_key:
        ctx.seen.discard(path_key)

    return child_outgoing


# ---------------------------------------------------------------------------
# End nodes and edge rendering
# ---------------------------------------------------------------------------


def _render_end_nodes_and_edges(
    ir: dict[str, Any],
    deduped_edges: list[dict[str, Any]],
    output_ids: list[str],
    ctx: MermaidContext,
) -> None:
    """Render end/output nodes (if branching) and all edges with routing.

    When ``output_ids`` exist, source->output edges are already rendered
    by ``_render_subworkflow_outputs``.  When ``suppress_io`` is True,
    the parent handles IO externally — skip end node generation.
    """
    nodes = ir.get("nodes", [])
    edges = ir.get("edges", [])

    # End node: only for branching workflows without output nodes,
    # and not when parent handles IO externally
    terminals: set[str] = set()
    if ctx.decision_nodes and not output_ids and not ctx.suppress_io:
        terminals = _find_terminal_nodes(nodes, edges)
        if terminals:
            end_id = _to_mermaid_id(f"{ctx.prefix}pflow_end")
            ctx.lines.append(f'{ctx.indent}{end_id}(("end"))')

    # Edges
    for edge in deduped_edges:
        _render_edge(edge, ctx)

    # End node edges (only when no outputs — outputs have source-based edges)
    if terminals:
        end_id = _to_mermaid_id(f"{ctx.prefix}pflow_end")
        for t in sorted(terminals):
            t_mermaid = _to_mermaid_id(ctx.prefix + t)
            t_ids = ctx.fork_join_map.get(t_mermaid, [t_mermaid])
            for tid in t_ids:
                ctx.lines.append(f"{ctx.indent}{tid} --> {end_id}")


# ---------------------------------------------------------------------------
# Sub-workflow resolution
# ---------------------------------------------------------------------------


def _try_resolve_child(
    node: dict[str, Any],
    ctx: MermaidContext,
) -> Optional[SubWorkflowResult]:
    """Try to resolve a sub-workflow, returning None on failure.

    Checks the ``seen`` recursion stack for cycles and swallows
    resolution errors (the workflow was already validated — errors
    here are non-fatal for visualization).

    The caller is responsible for adding/removing from ``seen``
    around the recursive render call.
    """
    if ctx.config.resolve_child is None:
        return None
    params = node.get("params", {})
    try:
        result = ctx.config.resolve_child(params, ctx.base_path)
    except Exception:
        logger.debug("Failed to resolve sub-workflow for node '%s'", node.get("id", "?"), exc_info=True)
        return None

    if result is None:
        return None

    # Cycle detection: check if this path is already on the recursion stack
    if result.path and str(result.path) in ctx.seen:
        return None

    return result
