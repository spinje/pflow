"""Input/output boundary rendering — top-level, sub-workflow, and external IO wrappers."""

from typing import Any, Optional

from pflow.core.workflow.mermaid._context import (
    _SOURCE_NODE_FIELD_RE,
    MermaidContext,
    _collect_param_refs,
    _escape_label,
    _refs_input,
    _to_mermaid_id,
)

# ---------------------------------------------------------------------------
# Top-level input nodes
# ---------------------------------------------------------------------------


def _render_inputs(ir: dict[str, Any], ctx: MermaidContext) -> None:
    """Render top-level workflow inputs as a dashed wrapper subgraph.

    Only renders the node declarations.  Edges are generated later by
    ``_connect_top_level_inputs`` after all nodes are rendered and we
    know which sub-workflow inputs exist.
    """
    inputs = ir.get("inputs", {})
    if not inputs:
        return

    wrapper_id = "workflow-inputs"
    wrapper_label = _escape_label("workflow inputs")
    ctx.lines.append(f'    subgraph {wrapper_id} ["{wrapper_label}"]')

    for name, config in inputs.items():
        input_type = config.get("type", "")
        required = config.get("required", False)
        req_str = ", required" if required else ""
        label = _escape_label(f"{name} ({input_type}{req_str})")
        mermaid_id = _to_mermaid_id(f"input_{name}")
        ctx.lines.append(f'        {mermaid_id}[/"{label}"/]:::input')

    ctx.lines.append("    end")
    ctx.lines.append("    style workflow-inputs fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4")


# ---------------------------------------------------------------------------
# Top-level input connections
# ---------------------------------------------------------------------------


def _connect_top_level_inputs(ir: dict[str, Any], ctx: MermaidContext) -> None:
    """Connect top-level inputs to their consuming nodes via param analysis.

    Scans all nodes' params and batch configs for ``${input_name}`` refs.
    When a consuming node has external input wrappers (in ``incoming_map``),
    connects to the matching input node.  Otherwise connects directly.
    """
    inputs = ir.get("inputs", {})
    if not inputs:
        return

    nodes = ir.get("nodes", [])
    connected: set[str] = set()

    for node in nodes:
        node_id = node.get("id", "")
        mermaid_id = _to_mermaid_id(node_id)
        in_dict = ctx.incoming_map.get(mermaid_id, {})

        _connect_input_from_params(node, inputs, in_dict, mermaid_id, connected, ctx)
        _connect_input_from_batch(node, inputs, in_dict, mermaid_id, connected, ctx)


def _connect_input_from_params(
    node: dict[str, Any],
    inputs: dict[str, Any],
    in_dict: dict[str, str],
    mermaid_id: str,
    connected: set[str],
    ctx: MermaidContext,
) -> None:
    """Connect top-level inputs referenced in node params."""
    all_refs = _collect_param_refs(node.get("params", {}))
    for ref_value in all_refs:
        for input_name in inputs:
            if not _refs_input(ref_value, input_name):
                continue
            target = in_dict.get(input_name, mermaid_id)
            source = _to_mermaid_id(f"input_{input_name}")
            edge_key = f"{source}->{target}"
            if edge_key not in connected:
                ctx.lines.append(f"    {source} --> {target}")
                connected.add(edge_key)


def _connect_input_from_batch(
    node: dict[str, Any],
    inputs: dict[str, Any],
    in_dict: dict[str, str],
    mermaid_id: str,
    connected: set[str],
    ctx: MermaidContext,
) -> None:
    """Connect top-level inputs referenced in batch.items."""
    batch = node.get("batch")
    if not batch or not isinstance(batch.get("items"), str):
        return
    items_ref = batch["items"]
    for input_name in inputs:
        if not _refs_input(items_ref, input_name):
            continue
        target = next(iter(in_dict.values())) if in_dict else mermaid_id
        source = _to_mermaid_id(f"input_{input_name}")
        edge_key = f"{source}->{target}"
        if edge_key not in connected:
            ctx.lines.append(f"    {source} --> {target}")
            connected.add(edge_key)


# ---------------------------------------------------------------------------
# Top-level output nodes
# ---------------------------------------------------------------------------


def _render_top_level_outputs(ir: dict[str, Any], ctx: MermaidContext) -> list[str]:
    """Render top-level workflow outputs as a dashed wrapper at the bottom.

    Parses source fields to connect producing nodes to outputs.
    Returns list of output mermaid IDs.
    """
    outputs = ir.get("outputs", {})
    if not outputs:
        return []

    node_ids = {n["id"] for n in ir.get("nodes", [])}

    wrapper_id = "workflow-outputs"
    wrapper_label = _escape_label("workflow outputs")
    ctx.lines.append(f'    subgraph {wrapper_id} ["{wrapper_label}"]')

    output_ids: list[str] = []
    out_name_map: dict[str, str] = {}
    for name in outputs:
        out_mid = _to_mermaid_id(f"out_{name}")
        label = _escape_label(name)
        ctx.lines.append(f'        {out_mid}(["{label}"]):::output')
        output_ids.append(out_mid)
        out_name_map[name] = out_mid

    ctx.lines.append("    end")
    ctx.lines.append("    style workflow-outputs fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4")

    # Connect producing nodes to outputs
    for name, config in outputs.items():
        source = config.get("source", "") if isinstance(config, dict) else ""
        _connect_sources_to_output(source, out_name_map[name], node_ids, "", ctx, ctx.outgoing_routes)

    return output_ids


# ---------------------------------------------------------------------------
# Source-to-output connection
# ---------------------------------------------------------------------------


def _connect_sources_to_output(
    source: str,
    out_mid: str,
    node_ids: set[str],
    id_prefix: str,
    ctx: MermaidContext,
    *outgoing_maps: dict[str, dict[str, str]],
) -> None:
    """Connect producing nodes to an output node by parsing a source expression.

    Scans ``source`` for ``${node.field}`` refs and emits edges from each
    producing node (or its output node, if expanded) to ``out_mid``.

    Args:
        id_prefix: Prepended to source node IDs for mermaid ID lookup.
        outgoing_maps: One or more outgoing maps, checked in order.
            First map with a match wins (supports child→parent cascade).
    """
    for src_node, field in _SOURCE_NODE_FIELD_RE.findall(source):
        if src_node not in node_ids:
            continue
        src_mid = _to_mermaid_id(id_prefix + src_node)
        # Find the first outgoing map that has this source
        child_outputs: dict[str, str] = {}
        for omap in outgoing_maps:
            found = omap.get(src_mid)
            if found:
                child_outputs = found
                break
        if field in child_outputs:
            ctx.lines.append(f"{ctx.indent}{child_outputs[field]} --> {out_mid}")
        elif len(child_outputs) == 1:
            ctx.lines.append(f"{ctx.indent}{next(iter(child_outputs.values()))} --> {out_mid}")
        else:
            ctx.lines.append(f"{ctx.indent}{src_mid} --> {out_mid}")


# ---------------------------------------------------------------------------
# Sub-workflow boundary nodes
# ---------------------------------------------------------------------------


def _render_subworkflow_inputs(ir: dict[str, Any], ctx: MermaidContext) -> None:
    """Render sub-workflow inputs as parallelogram entry nodes."""
    inputs = ir.get("inputs", {})
    if not inputs:
        return

    start_node = ir.get("start_node") or ir["nodes"][0]["id"]

    for name, config in inputs.items():
        input_type = config.get("type", "")
        label = _escape_label(f"{name} ({input_type})" if input_type else name)
        mermaid_id = _to_mermaid_id(f"{ctx.prefix}in_{name}")
        ctx.lines.append(f'{ctx.indent}{mermaid_id}[/"{label}"/]:::input')

    for name in inputs:
        mermaid_id = _to_mermaid_id(f"{ctx.prefix}in_{name}")
        ctx.lines.append(f"{ctx.indent}{mermaid_id} --> {_to_mermaid_id(ctx.prefix + start_node)}")


def _render_subworkflow_outputs(ir: dict[str, Any], ctx: MermaidContext) -> list[str]:
    """Render sub-workflow outputs and connect producing nodes to them.

    Parses each output's ``source`` field to find which nodes produce
    the value (e.g. ``${classify.result}`` -> classify, or
    ``${a.stdout ?? b.stdout}`` -> a, b).  When the source node is an
    expanded subgraph with outputs, routes through the matching output.

    Returns the list of output mermaid IDs (for parent edge routing).
    """
    outputs = ir.get("outputs", {})
    if not outputs:
        return []

    node_ids = {n["id"] for n in ir.get("nodes", [])}
    output_ids: list[str] = []

    for name, config in outputs.items():
        out_mid = _to_mermaid_id(f"{ctx.prefix}out_{name}")
        label = _escape_label(name)
        ctx.lines.append(f'{ctx.indent}{out_mid}(["{label}"]):::output')
        output_ids.append(out_mid)

        source = config.get("source", "") if isinstance(config, dict) else ""
        _connect_sources_to_output(source, out_mid, node_ids, ctx.prefix, ctx, ctx.outgoing_routes)

    return output_ids


# ---------------------------------------------------------------------------
# External IO wrappers (rendered at parent scope, outside subgraphs)
# ---------------------------------------------------------------------------


def _render_external_inputs(
    child_ir: dict[str, Any],
    node_id: str,
    ctx: MermaidContext,
) -> None:
    """Render sub-workflow inputs as a dashed wrapper subgraph at parent scope.

    Creates parallelogram input nodes with the same mermaid ID convention
    as internal IO (``{prefix}{node_id}__in_{name}``), then adds
    cross-boundary edges from each input to the child's start node.
    """
    inputs = child_ir.get("inputs", {})
    if not inputs:
        return

    child_prefix = ctx.prefix + node_id + "__"
    start_node = child_ir.get("start_node") or child_ir["nodes"][0]["id"]

    # Wrapper subgraph
    wrapper_id = _to_mermaid_id(f"{ctx.prefix}{node_id}-in")
    wrapper_label = _escape_label(f"{node_id} inputs")
    ctx.lines.append(f'{ctx.indent}subgraph {wrapper_id} ["{wrapper_label}"]')
    inner_indent = ctx.indent + "    "
    for name, config in inputs.items():
        input_type = config.get("type", "")
        label = _escape_label(f"{name} ({input_type})" if input_type else name)
        mermaid_id = _to_mermaid_id(f"{child_prefix}in_{name}")
        ctx.lines.append(f'{inner_indent}{mermaid_id}[/"{label}"/]:::input')
    ctx.lines.append(f"{ctx.indent}end")
    ctx.lines.append(f"{ctx.indent}style {wrapper_id} fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4")

    # Cross-boundary edges: input → child's start node
    start_mid = _to_mermaid_id(child_prefix + start_node)
    for name in inputs:
        in_mid = _to_mermaid_id(f"{child_prefix}in_{name}")
        ctx.lines.append(f"{ctx.indent}{in_mid} --> {start_mid}")


def _render_external_outputs(
    child_ir: dict[str, Any],
    node_id: str,
    ctx: MermaidContext,
    child_outgoing_routes: Optional[dict[str, dict[str, str]]] = None,
) -> list[str]:
    """Render sub-workflow outputs as a dashed wrapper subgraph at parent scope.

    Parses each output's ``source`` field to connect internal producing
    nodes to the external output nodes (cross-boundary edges).  Populates
    ``outgoing_routes`` for structural edge routing.

    Args:
        child_outgoing_routes: The outgoing_routes from the child's ``_render_workflow``
            call.  Used to route through nested sub-workflow outputs (e.g.,
            choose-chorus's outputs when rendering create-songs' outputs).

    Returns the list of output mermaid IDs.
    """
    outputs = child_ir.get("outputs", {})
    if not outputs:
        return []

    child_prefix = ctx.prefix + node_id + "__"
    mermaid_id = _to_mermaid_id(ctx.prefix + node_id)
    node_ids = {n["id"] for n in child_ir.get("nodes", [])}

    # Wrapper subgraph
    wrapper_id = _to_mermaid_id(f"{ctx.prefix}{node_id}-out")
    wrapper_label = _escape_label(f"{node_id} outputs")
    ctx.lines.append(f'{ctx.indent}subgraph {wrapper_id} ["{wrapper_label}"]')
    inner_indent = ctx.indent + "    "

    output_ids: list[str] = []
    out_name_map: dict[str, str] = {}
    for name in outputs:
        out_mid = _to_mermaid_id(f"{child_prefix}out_{name}")
        label = _escape_label(name)
        ctx.lines.append(f'{inner_indent}{out_mid}(["{label}"]):::output')
        output_ids.append(out_mid)
        out_name_map[name] = out_mid

    ctx.lines.append(f"{ctx.indent}end")
    ctx.lines.append(f"{ctx.indent}style {wrapper_id} fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4")

    # Cross-boundary edges: internal producing nodes → external outputs.
    # Check child_outgoing_routes first (nested sub-workflow outputs from
    # the child's own _render_workflow), then fall back to parent outgoing_routes.
    _child_out = child_outgoing_routes or {}
    for name, config in outputs.items():
        source = config.get("source", "") if isinstance(config, dict) else ""
        _connect_sources_to_output(
            source, out_name_map[name], node_ids, child_prefix, ctx, _child_out, ctx.outgoing_routes
        )

    # Populate outgoing_routes for structural edge routing
    ctx.outgoing_routes[mermaid_id] = out_name_map
    ctx.has_expanded_outputs.add(mermaid_id)

    return output_ids
