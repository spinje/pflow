"""Input/output boundary rendering — top-level, sub-workflow, and external IO wrappers."""

from typing import Any, Optional

from pflow.core.workflow.mermaid._context import (
    MermaidContext,
    _escape_label,
    _to_mermaid_id,
)
from pflow.core.workflow.mermaid._scope import Scope

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
    """Connect top-level inputs referenced in node params.

    Walks ``params`` and one level of nested dicts (for the ``params["inputs"]``
    form used by workflow + code nodes).  For each template ref to a declared
    top-level input, emits an edge to the consumer — routed through the
    consumer's input wrapper when the ref lives under a matching child-input
    key (task-146 nearest-consumer heuristic).
    """
    params = node.get("params", {})
    # (child_param_name, ref_value) pairs — child_param_name used for in_dict target routing
    values_to_check: list[tuple[str, str]] = []
    for param_name, param_value in params.items():
        if isinstance(param_value, str):
            values_to_check.append((param_name, param_value))
        elif isinstance(param_value, dict):
            for nested_name, nested_val in param_value.items():
                if isinstance(nested_val, str):
                    values_to_check.append((nested_name, nested_val))

    for child_param_name, ref_value in values_to_check:
        for root, _field in Scope.refs_in(ref_value):
            if root not in inputs:
                continue
            # Route through input wrapper if the child param name matches
            target = in_dict.get(child_param_name, in_dict.get(root, mermaid_id))
            source = _to_mermaid_id(f"input_{root}")
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
    """Connect top-level inputs referenced in ``batch.items``."""
    batch = node.get("batch")
    if not batch or not isinstance(batch.get("items"), str):
        return
    for root, _field in Scope.refs_in(batch["items"]):
        if root not in inputs:
            continue
        target = next(iter(in_dict.values())) if in_dict else mermaid_id
        source = _to_mermaid_id(f"input_{root}")
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

    # Top-level inputs use the ``input_{name}`` convention
    input_ids = {name: _to_mermaid_id(f"input_{name}") for name in ir.get("inputs", {})}

    # Connect producing nodes (and input-root refs) to outputs
    for name, config in outputs.items():
        source = config.get("source", "") if isinstance(config, dict) else ""
        _connect_sources_to_output(source, out_name_map[name], node_ids, "", input_ids, ctx, ctx.outgoing_routes)

    return output_ids


# ---------------------------------------------------------------------------
# Source-to-output connection
# ---------------------------------------------------------------------------


def _connect_sources_to_output(
    source: str,
    out_mid: str,
    node_ids: set[str],
    id_prefix: str,
    input_ids: dict[str, str],
    ctx: MermaidContext,
    *outgoing_maps: dict[str, dict[str, str]],
) -> None:
    """Connect producing sources to an output node by parsing a source expression.

    Each root ref in ``source`` resolves to exactly one of:

    - A declared **input** at this scope → edge from the input parallelogram.
    - A **sibling node**, possibly with a specific output field → edge from
      the node's output (if expanded) or the node box.
    - Unknown → skipped (stale ref — caught elsewhere at validation time).

    Handles coalesce expressions (``${a.x ?? b.y}``) and bare input refs
    (``${data}`` without a field).  Both emit their respective edges.

    Args:
        node_ids: Declared node IDs in the source scope.
        id_prefix: Prepended to source node IDs for mermaid ID construction.
        input_ids: Input name → mermaid ID at this scope (``input_{name}``
            at top level, ``{prefix}in_{name}`` in a sub-workflow).  Refs
            matching an input key emit an edge from the input parallelogram.
        outgoing_maps: Outgoing-routes maps checked in order.  First map with
            a match wins (supports child→parent output cascade).
    """
    for root, field in Scope.source_refs_in(source):
        # Input-root refs (#263 fix): connect from the input parallelogram.
        if root in input_ids:
            ctx.lines.append(f"{ctx.indent}{input_ids[root]} --> {out_mid}")
            continue

        if root not in node_ids:
            continue
        src_mid = _to_mermaid_id(id_prefix + root)
        child_outputs: dict[str, str] = {}
        for omap in outgoing_maps:
            found = omap.get(src_mid)
            if found:
                child_outputs = found
                break
        if field and field in child_outputs:
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
    # Sub-workflow inputs use the ``{prefix}in_{name}`` convention
    input_ids = {name: _to_mermaid_id(f"{ctx.prefix}in_{name}") for name in ir.get("inputs", {})}
    output_ids: list[str] = []

    for name, config in outputs.items():
        out_mid = _to_mermaid_id(f"{ctx.prefix}out_{name}")
        label = _escape_label(name)
        ctx.lines.append(f'{ctx.indent}{out_mid}(["{label}"]):::output')
        output_ids.append(out_mid)

        source = config.get("source", "") if isinstance(config, dict) else ""
        _connect_sources_to_output(source, out_mid, node_ids, ctx.prefix, input_ids, ctx, ctx.outgoing_routes)

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
    # Child-scope inputs use the ``{child_prefix}in_{name}`` convention
    input_ids = {name: _to_mermaid_id(f"{child_prefix}in_{name}") for name in child_ir.get("inputs", {})}
    for name, config in outputs.items():
        source = config.get("source", "") if isinstance(config, dict) else ""
        _connect_sources_to_output(
            source, out_name_map[name], node_ids, child_prefix, input_ids, ctx, _child_out, ctx.outgoing_routes
        )

    # Populate outgoing_routes for structural edge routing
    ctx.outgoing_routes[mermaid_id] = out_name_map
    ctx.has_expanded_outputs.add(mermaid_id)

    return output_ids
