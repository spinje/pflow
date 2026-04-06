"""Generate Mermaid flowchart diagrams from workflow IR."""

import logging
import re
from pathlib import Path
from typing import Any, Callable, Optional

from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shape mapping: node_type -> (open_bracket, close_bracket, css_class)
# ---------------------------------------------------------------------------

_SHAPE_MAP: dict[str, tuple[str, str, str]] = {
    "llm": ("([", "])", "llm"),
    "shell": ("[[", "]]", "shell"),
    "write-file": ("[(", ")]", "writefile"),
    "code": ("[", "]", "code"),
    "workflow": ("(", ")", "workflow"),
}

# Batch item label extraction
_LABEL_KEYS = ("name", "label", "focus", "lens")
_SKIP_KEYS = ("workflow", "prompt", "command", "model")

# Reserved workflow params (not child inputs)
_RESERVED_PARAMS = {"workflow", "workflow_ir", "storage_mode", "type"}


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
    lines: list[str] = [f"graph {direction}"]
    seen: set[str] = set()

    _render_classdefs(lines)
    _render_inputs(ir, lines)
    _render_workflow(ir, lines, resolve_child, base_path, max_depth, 0, "", seen, direction, descriptions)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Edge preprocessing
# ---------------------------------------------------------------------------


def _deduplicate_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove redundant edges.

    When a (from, to) pair has BOTH a document-order edge (no ``action`` key)
    and a named action edge (action is not None/default/error), suppress:
    - The document-order edge (no action key)
    - Any ``action: "default"`` edge for the same pair

    This prevents visual duplication like:
        classify --> fetch-youtube           (document-order)
        classify -->|fetch-youtube| fetch-youtube  (named action)
    """
    # Pairs that have at least one named action edge
    named_pairs: set[tuple[str, str]] = set()
    for edge in edges:
        if "action" in edge and edge["action"] not in ("default", "error"):
            named_pairs.add((edge["from"], edge["to"]))

    result: list[dict[str, Any]] = []
    for edge in edges:
        pair = (edge["from"], edge["to"])
        if pair in named_pairs:
            # Keep only named action edges and error edges for this pair
            if "action" in edge and edge["action"] not in ("default",):
                result.append(edge)
            # Suppress: document-order (no action key) or action="default"
        else:
            result.append(edge)
    return result


def _detect_decision_nodes(edges: list[dict[str, Any]]) -> set[str]:
    """Return node IDs that are decision/routing points.

    A decision node has >=2 outgoing edges with distinct named actions
    (excluding "error" and "default" actions, and excluding document-order
    edges with no action key).
    """
    action_sets: dict[str, set[str]] = {}
    for edge in edges:
        if "action" in edge and edge["action"] not in ("error", "default"):
            from_id = edge["from"]
            if from_id not in action_sets:
                action_sets[from_id] = set()
            action_sets[from_id].add(edge["action"])
    return {node_id for node_id, actions in action_sets.items() if len(actions) >= 2}


# ---------------------------------------------------------------------------
# Node shape and label formatting
# ---------------------------------------------------------------------------


def _get_node_shape(node_type: str, is_decision: bool) -> tuple[str, str, str]:
    """Return (open_bracket, close_bracket, css_class) for a node's Mermaid shape.

    Decision nodes always get diamond shape regardless of type.
    MCP nodes (type starts with "mcp") get hexagon shape.
    """
    if is_decision:
        return ("{", "}", "decision")
    if node_type.startswith("mcp"):
        return ("{{", "}}", "mcp")
    return _SHAPE_MAP.get(node_type, ("[", "]", "code"))


def _format_node_type(node_type: str) -> str:
    """Format node type for display in labels.

    MCP types are long (``mcp-klavis-youtube-get_youtube_video_transcript``).
    Format as ``mcp:<br/>klavis-youtube-get_youtube_video_transcript`` for readability.
    """
    if node_type.startswith("mcp-"):
        return f"mcp:<br/>{node_type[4:]}"
    return node_type


def _format_label(
    node_id: str,
    node_type: str,
    descriptions: bool,
    purpose: str,
    batch_suffix: str = "",
) -> str:
    """Format the full display label for a node.

    The batch suffix (e.g., ``(parallel x|sources|)``) is appended AFTER
    escaping because it contains ``|`` delimiters that must be preserved
    in ``@{ shape: procs }`` labels.
    """
    display_type = _format_node_type(node_type)
    label = f"{node_id} ({display_type})"
    if descriptions and purpose:
        label += f"<br/>{_first_sentence(purpose)}"
    label = _escape_label(label)
    if batch_suffix:
        label += f"<br/>{batch_suffix}"
    return label


def _first_sentence(text: str) -> str:
    """Extract first sentence from a purpose string, stripped of markdown formatting."""
    # Strip bold and italic markdown
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    clean = re.sub(r"\*(.+?)\*", r"\1", clean)
    # Find first sentence
    match = re.match(r"([^.!?]+[.!?])", clean)
    if match:
        return match.group(1)[:80]
    return clean[:80]


# ---------------------------------------------------------------------------
# Style declarations
# ---------------------------------------------------------------------------


_CLASSDEF_STYLES: dict[str, str] = {
    "code": "fill:#D5E8D4,stroke:#82B366,color:#000",
    "llm": "fill:#E8D5F5,stroke:#7B2D8E,color:#000",
    "shell": "fill:#DAE8FC,stroke:#6C8EBF,color:#000",
    "mcp": "fill:#FFE6CC,stroke:#D79B00,color:#000",
    "writefile": "fill:#F8CECC,stroke:#B85450,color:#000",
    "workflow": "fill:#FFF2CC,stroke:#D6B656,color:#000",
    "decision": "fill:#F5F5F5,stroke:#666666,color:#000",
    "input": "fill:#F5F5F5,stroke:#666666,stroke-dasharray:5 5,color:#000",
    "output": "fill:#E8E8E8,stroke:#666666,color:#000",
}


def _classdef_to_style(css_class: str) -> str:
    """Return inline style properties for a classDef name.

    Used for nodes that can't use ``:::classDef`` syntax (e.g., ``@{ shape: procs }``).
    """
    return _CLASSDEF_STYLES.get(css_class, _CLASSDEF_STYLES["code"])


def _render_classdefs(lines: list[str]) -> None:
    """Add classDef color declarations at the top of the graph."""
    for name, style in _CLASSDEF_STYLES.items():
        lines.append(f"    classDef {name} {style}")


# ---------------------------------------------------------------------------
# Input nodes
# ---------------------------------------------------------------------------


def _render_inputs(ir: dict[str, Any], lines: list[str]) -> None:
    """Render top-level workflow inputs as parallelogram nodes.

    Only renders the node declarations.  Edges are generated later by
    ``_connect_top_level_inputs`` after all nodes are rendered and we
    know which sub-workflow inputs exist.
    """
    inputs = ir.get("inputs", {})
    if not inputs:
        return

    for name, config in inputs.items():
        input_type = config.get("type", "")
        required = config.get("required", False)
        req_str = ", required" if required else ""
        label = _escape_label(f"{name} ({input_type}{req_str})")
        mermaid_id = _to_mermaid_id(f"input_{name}")
        lines.append(f'    {mermaid_id}[/"{label}"/]:::input')


def _refs_input(value: str, input_name: str) -> bool:
    """Check if a string value references a top-level input by name."""
    return f"${{{input_name}}}" in value or f"${{{input_name}." in value


def _connect_top_level_inputs(
    ir: dict[str, Any],
    lines: list[str],
    incoming_map: dict[str, dict[str, str]],
) -> None:
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
        in_dict = incoming_map.get(mermaid_id, {})

        _connect_input_from_params(node, inputs, in_dict, mermaid_id, lines, connected)
        _connect_input_from_batch(node, inputs, in_dict, mermaid_id, lines, connected)


def _collect_param_refs(params: dict[str, Any]) -> list[str]:
    """Collect all string values from params, including one level of nested dicts.

    Code nodes store declared inputs at ``params.inputs`` (a nested dict),
    so we recurse one level to find those refs too.
    """
    refs: list[str] = []
    for value in params.values():
        if isinstance(value, str):
            refs.append(value)
        elif isinstance(value, dict):
            refs.extend(v for v in value.values() if isinstance(v, str))
    return refs


def _connect_input_from_params(
    node: dict[str, Any],
    inputs: dict[str, Any],
    in_dict: dict[str, str],
    mermaid_id: str,
    lines: list[str],
    connected: set[str],
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
                lines.append(f"    {source} --> {target}")
                connected.add(edge_key)


def _connect_input_from_batch(
    node: dict[str, Any],
    inputs: dict[str, Any],
    in_dict: dict[str, str],
    mermaid_id: str,
    lines: list[str],
    connected: set[str],
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
            lines.append(f"    {source} --> {target}")
            connected.add(edge_key)


def _render_top_level_outputs(
    ir: dict[str, Any],
    lines: list[str],
    outgoing_map: dict[str, dict[str, str]],
) -> list[str]:
    """Render top-level workflow outputs as a dashed wrapper at the bottom.

    Parses source fields to connect producing nodes to outputs.
    Returns list of output mermaid IDs.
    """
    outputs = ir.get("outputs", {})
    if not outputs:
        return []

    node_ids = {n["id"] for n in ir.get("nodes", [])}

    wrapper_id = "workflow-outputs"
    wrapper_label = _escape_label("outputs")
    lines.append(f'    subgraph {wrapper_id} ["{wrapper_label}"]')

    output_ids: list[str] = []
    out_name_map: dict[str, str] = {}
    for name in outputs:
        out_mid = _to_mermaid_id(f"out_{name}")
        label = _escape_label(name)
        lines.append(f'        {out_mid}(["{label}"]):::output')
        output_ids.append(out_mid)
        out_name_map[name] = out_mid

    lines.append("    end")
    lines.append("    style workflow-outputs fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4")

    # Connect producing nodes to outputs
    for name, config in outputs.items():
        source = config.get("source", "") if isinstance(config, dict) else ""
        _connect_sources_to_output(source, out_name_map[name], node_ids, "", lines, "    ", outgoing_map)

    return output_ids


# ---------------------------------------------------------------------------
# Sub-workflow boundary nodes
# ---------------------------------------------------------------------------


def _render_subworkflow_inputs(ir: dict[str, Any], lines: list[str], indent: str, prefix: str) -> None:
    """Render sub-workflow inputs as parallelogram entry nodes."""
    inputs = ir.get("inputs", {})
    if not inputs:
        return

    start_node = ir.get("start_node") or ir["nodes"][0]["id"]

    for name, config in inputs.items():
        input_type = config.get("type", "")
        label = _escape_label(f"{name} ({input_type})" if input_type else name)
        mermaid_id = _to_mermaid_id(f"{prefix}in_{name}")
        lines.append(f'{indent}{mermaid_id}[/"{label}"/]:::input')

    for name in inputs:
        mermaid_id = _to_mermaid_id(f"{prefix}in_{name}")
        lines.append(f"{indent}{mermaid_id} --> {_to_mermaid_id(prefix + start_node)}")


_SOURCE_NODE_FIELD_RE = re.compile(r"(?:^|[\s{?])([a-zA-Z0-9_-]+)\.([a-zA-Z0-9_-]+)")


def _connect_sources_to_output(
    source: str,
    out_mid: str,
    node_ids: set[str],
    id_prefix: str,
    lines: list[str],
    indent: str,
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
            lines.append(f"{indent}{child_outputs[field]} --> {out_mid}")
        elif len(child_outputs) == 1:
            lines.append(f"{indent}{next(iter(child_outputs.values()))} --> {out_mid}")
        else:
            lines.append(f"{indent}{src_mid} --> {out_mid}")


def _render_subworkflow_outputs(
    ir: dict[str, Any],
    lines: list[str],
    indent: str,
    prefix: str,
    outgoing_map: Optional[dict[str, dict[str, str]]] = None,
) -> list[str]:
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
    _outgoing = outgoing_map or {}
    output_ids: list[str] = []

    for name, config in outputs.items():
        out_mid = _to_mermaid_id(f"{prefix}out_{name}")
        label = _escape_label(name)
        lines.append(f'{indent}{out_mid}(["{label}"]):::output')
        output_ids.append(out_mid)

        source = config.get("source", "") if isinstance(config, dict) else ""
        _connect_sources_to_output(source, out_mid, node_ids, prefix, lines, indent, _outgoing)

    return output_ids


# ---------------------------------------------------------------------------
# Data-flow edges (param template refs → sub-workflow inputs)
# ---------------------------------------------------------------------------

_PARAM_REF_RE = re.compile(r"\$\{([a-zA-Z0-9_-]+)(?:\.|\})")


def _extract_batch_source(node: dict[str, Any], sibling_node_ids: set[str]) -> Optional[str]:
    """Extract the source node ID from a batch items template ref.

    For ``batch: {items: "${zip-results.result}"}``, returns ``"zip-results"``.
    Returns None if batch has no dynamic items or source isn't a sibling node.
    """
    batch = node.get("batch")
    if not batch:
        return None
    items = batch.get("items")
    if not isinstance(items, str):
        return None
    for ref in _PARAM_REF_RE.findall(items):
        if str(ref) in sibling_node_ids:
            return str(ref)
    return None


def _resolve_ref_source(
    ref_name: str,
    prefix: str,
    sibling_node_ids: set[str],
    parent_inputs: dict[str, Any],
    batch_source: Optional[str],
    outgoing_map: dict[str, dict[str, str]],
) -> Optional[str]:
    """Resolve a template ref name to a mermaid source ID."""
    if ref_name == "item":
        if not batch_source:
            return None
        # Skip if source has outputs — name-matched structural edge handles it
        if _to_mermaid_id(prefix + batch_source) in outgoing_map:
            return None
        return _to_mermaid_id(prefix + batch_source)
    if ref_name in sibling_node_ids:
        mermaid_id = _to_mermaid_id(prefix + ref_name)
        # If sibling has outputs, route through them instead of subgraph box
        out_dict = outgoing_map.get(mermaid_id)
        if out_dict and len(out_dict) == 1:
            return next(iter(out_dict.values()))
        return mermaid_id
    if ref_name in parent_inputs:
        return _to_mermaid_id(f"{prefix}in_{ref_name}")
    return None


def _generate_data_flow_edges(
    node: dict[str, Any],
    child_ir: dict[str, Any],
    lines: list[str],
    indent: str,
    prefix: str,
    child_prefix: str,
    parent_inputs: dict[str, Any],
    sibling_node_ids: set[str],
    outgoing_map: dict[str, dict[str, str]],
) -> None:
    """Generate edges from upstream nodes to sub-workflow input nodes.

    Parses template refs in the parent node's ``params`` to find which
    sibling nodes or parent inputs feed each child input.  For example,
    ``creative_direction: ${creative-direction.response}`` generates an
    edge from ``creative-direction`` to the child's ``in_creative_direction``.
    """
    child_inputs = child_ir.get("inputs", {})
    if not child_inputs:
        return

    params = node.get("params", {})
    batch_source = _extract_batch_source(node, sibling_node_ids)

    for param_name, param_value in params.items():
        if param_name in _RESERVED_PARAMS or param_name not in child_inputs:
            continue
        if not isinstance(param_value, str) or "${" not in param_value:
            continue

        target_mid = _to_mermaid_id(f"{child_prefix}in_{param_name}")
        for ref_name in _PARAM_REF_RE.findall(param_value):
            source_mid = _resolve_ref_source(
                ref_name,
                prefix,
                sibling_node_ids,
                parent_inputs,
                batch_source,
                outgoing_map,
            )
            if source_mid:
                lines.append(f"{indent}{source_mid} --> {target_mid}")


# ---------------------------------------------------------------------------
# External IO wrappers (rendered at parent scope, outside subgraphs)
# ---------------------------------------------------------------------------


def _render_external_inputs(
    child_ir: dict[str, Any],
    lines: list[str],
    indent: str,
    node_id: str,
    prefix: str,
) -> None:
    """Render sub-workflow inputs as a dashed wrapper subgraph at parent scope.

    Creates parallelogram input nodes with the same mermaid ID convention
    as internal IO (``{prefix}{node_id}__in_{name}``), then adds
    cross-boundary edges from each input to the child's start node.
    """
    inputs = child_ir.get("inputs", {})
    if not inputs:
        return

    child_prefix = prefix + node_id + "__"
    start_node = child_ir.get("start_node") or child_ir["nodes"][0]["id"]

    # Wrapper subgraph
    wrapper_id = _to_mermaid_id(f"{prefix}{node_id}-in")
    wrapper_label = _escape_label(f"{node_id} inputs")
    lines.append(f'{indent}subgraph {wrapper_id} ["{wrapper_label}"]')
    inner_indent = indent + "    "
    for name, config in inputs.items():
        input_type = config.get("type", "")
        label = _escape_label(f"{name} ({input_type})" if input_type else name)
        mermaid_id = _to_mermaid_id(f"{child_prefix}in_{name}")
        lines.append(f'{inner_indent}{mermaid_id}[/"{label}"/]:::input')
    lines.append(f"{indent}end")
    lines.append(f"{indent}style {wrapper_id} fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4")

    # Cross-boundary edges: input → child's start node
    start_mid = _to_mermaid_id(child_prefix + start_node)
    for name in inputs:
        in_mid = _to_mermaid_id(f"{child_prefix}in_{name}")
        lines.append(f"{indent}{in_mid} --> {start_mid}")


def _render_external_outputs(
    child_ir: dict[str, Any],
    lines: list[str],
    indent: str,
    node_id: str,
    prefix: str,
    outgoing_map: dict[str, dict[str, str]],
    child_outgoing_map: Optional[dict[str, dict[str, str]]] = None,
) -> list[str]:
    """Render sub-workflow outputs as a dashed wrapper subgraph at parent scope.

    Parses each output's ``source`` field to connect internal producing
    nodes to the external output nodes (cross-boundary edges).  Populates
    ``outgoing_map`` for structural edge routing.

    Args:
        child_outgoing_map: The outgoing_map from the child's ``_render_workflow``
            call.  Used to route through nested sub-workflow outputs (e.g.,
            choose-chorus's outputs when rendering create-songs' outputs).

    Returns the list of output mermaid IDs.
    """
    outputs = child_ir.get("outputs", {})
    if not outputs:
        return []

    child_prefix = prefix + node_id + "__"
    mermaid_id = _to_mermaid_id(prefix + node_id)
    node_ids = {n["id"] for n in child_ir.get("nodes", [])}

    # Wrapper subgraph
    wrapper_id = _to_mermaid_id(f"{prefix}{node_id}-out")
    wrapper_label = _escape_label(f"{node_id} outputs")
    lines.append(f'{indent}subgraph {wrapper_id} ["{wrapper_label}"]')
    inner_indent = indent + "    "

    output_ids: list[str] = []
    out_name_map: dict[str, str] = {}
    for name in outputs:
        out_mid = _to_mermaid_id(f"{child_prefix}out_{name}")
        label = _escape_label(name)
        lines.append(f'{inner_indent}{out_mid}(["{label}"]):::output')
        output_ids.append(out_mid)
        out_name_map[name] = out_mid

    lines.append(f"{indent}end")
    lines.append(f"{indent}style {wrapper_id} fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4")

    # Cross-boundary edges: internal producing nodes → external outputs.
    # Check child_outgoing_map first (nested sub-workflow outputs from
    # the child's own _render_workflow), then fall back to parent outgoing_map.
    _child_out = child_outgoing_map or {}
    for name, config in outputs.items():
        source = config.get("source", "") if isinstance(config, dict) else ""
        _connect_sources_to_output(
            source, out_name_map[name], node_ids, child_prefix, lines, indent, _child_out, outgoing_map
        )

    # Populate outgoing_map for structural edge routing
    outgoing_map[mermaid_id] = out_name_map

    return output_ids


# ---------------------------------------------------------------------------
# Terminal end nodes
# ---------------------------------------------------------------------------


def _find_terminal_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> set[str]:
    """Find nodes with no non-error outgoing edges.

    A node with ``- next: end`` has zero outgoing edges in the IR.
    A node with only an error edge (``on-error``) but ``next: end``
    has no non-error outgoing edges and is terminal for its success path.
    """
    has_non_error_outgoing = {e["from"] for e in edges if e.get("action") != "error"}
    return {n["id"] for n in nodes if n["id"] not in has_non_error_outgoing}


# ---------------------------------------------------------------------------
# Batch rendering
# ---------------------------------------------------------------------------


def _get_item_label(item: Any, index: int) -> str:
    """Extract a meaningful short label from a batch item dict."""
    if not isinstance(item, dict):
        return f"#{index + 1}"
    # Try priority keys
    for key in _LABEL_KEYS:
        val = item.get(key)
        if isinstance(val, str):
            return val
    # Fallback: first short string value not in skip keys
    for key, val in item.items():
        if key in _SKIP_KEYS:
            continue
        if isinstance(val, str) and len(val) <= 30:
            return val
    return f"#{index + 1}"


def _render_batch_inline(
    node: dict[str, Any],
    items: list[Any],
    is_parallel: bool,
    lines: list[str],
    indent: str,
    prefix: str,
    node_type: str,
    descriptions: bool,
    fork_join_map: dict[str, list[str]],
    resolve_child: Optional[Callable[[dict[str, Any], Optional[Path]], Optional[SubWorkflowResult]]] = None,
    base_path: Optional[Path] = None,
    max_depth: int = 1,
    current_depth: int = 0,
    seen: Optional[set[str]] = None,
    direction: str = "LR",
    sibling_node_ids: Optional[set[str]] = None,
    data_flow_targets: Optional[set[str]] = None,
    outgoing_map: Optional[dict[str, dict[str, str]]] = None,
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
    mermaid_id = _to_mermaid_id(prefix + node_id)
    if seen is None:
        seen = set()

    render_items = items if len(items) <= 4 else items[:2]
    parallel_str = "parallel " if is_parallel else ""
    subgraph_label = _escape_label(f"{node_id} ({parallel_str}x{len(items)})")

    lines.append(f'{indent}subgraph {mermaid_id} ["{subgraph_label}"]')
    inner_indent = indent + "    "

    collected_ids: list[str] = []
    expanded_items: list[tuple[str, dict[str, Any]]] = []  # (item_label, child_ir)
    shape_open, shape_close, css_class = _get_node_shape(node_type, False)
    can_expand = node_type in _WORKFLOW_TYPES and resolve_child is not None and current_depth < max_depth

    for i, item in enumerate(render_items):
        item_label = _get_item_label(item, i)
        item_mermaid_id = _to_mermaid_id(prefix + node_id + "__" + item_label)

        # Try to expand workflow items as subgraphs
        child_ir: Optional[dict[str, Any]] = None
        if can_expand:
            child_ir = _try_expand_batch_item(
                item,
                item_label,
                item_mermaid_id,
                lines,
                inner_indent,
                prefix + node_id + "__",
                resolve_child,  # type: ignore[arg-type]
                base_path,
                max_depth,
                current_depth,
                seen,
                direction,
                descriptions,
            )
        if child_ir is not None:
            expanded_items.append((item_label, child_ir))
            collected_ids.append(item_mermaid_id)
            # Populate outgoing_map so structural edges route through item's outputs
            child_outputs = child_ir.get("outputs", {})
            if child_outputs and outgoing_map is not None:
                item_prefix = prefix + node_id + "__" + item_label + "__"
                outgoing_map[item_mermaid_id] = {
                    name: _to_mermaid_id(f"{item_prefix}out_{name}") for name in child_outputs
                }
            continue

        display_label = _escape_label(f"{item_label} ({_format_node_type(node_type)})")
        lines.append(f'{inner_indent}{item_mermaid_id}{shape_open}"{display_label}"{shape_close}:::{css_class}')
        collected_ids.append(item_mermaid_id)

    if len(items) > 4:
        dots_id = _to_mermaid_id(prefix + node_id + "__dots")
        dots_label = f"... x{len(items)}"
        lines.append(f'{inner_indent}{dots_id}@{{ shape: procs, label: "{_escape_label(dots_label)}" }}')
        lines.append(f"{inner_indent}style {dots_id} {_classdef_to_style(css_class)}")
        collected_ids.append(dots_id)

    lines.append(f"{indent}end")
    lines.append(f"{indent}{_subgraph_style(mermaid_id, current_depth + 1)}")
    fork_join_map[mermaid_id] = collected_ids

    # Batch item data-flow edges: connect parent params to each item's inputs.
    # Returns set of item IDs that have data-flow coverage — these are added
    # to data_flow_targets so structural edges (through fork_join_map) to them
    # are suppressed (avoiding duplicate connections).
    if expanded_items:
        items_with_df = _generate_batch_item_data_flow(
            node,
            expanded_items,
            lines,
            indent,
            prefix,
            sibling_node_ids or set(),
        )
        if items_with_df and data_flow_targets is not None:
            data_flow_targets.update(items_with_df)


def _generate_batch_item_data_flow(
    node: dict[str, Any],
    expanded_items: list[tuple[str, dict[str, Any]]],
    lines: list[str],
    indent: str,
    prefix: str,
    sibling_node_ids: set[str],
) -> set[str]:
    """Generate data-flow edges from parent params to each expanded batch item's inputs.

    For a batch workflow node like ``emotional-reviews`` with params
    ``lyrics: ${write-lyrics.response}``, generates edges from ``write-lyrics``
    to each item's ``in_lyrics`` node (emotional-architecture, narrative, imagery).

    Skips ``${item.*}`` refs (those come from the batch items themselves).

    Returns set of item mermaid IDs that received data-flow edges (for
    structural edge suppression in the fork/join).
    """
    node_id = node["id"]
    params = node.get("params", {})
    child_prefix_base = prefix + node_id + "__"
    items_with_data_flow: set[str] = set()

    for param_name, param_value in params.items():
        if param_name in _RESERVED_PARAMS:
            continue
        if not isinstance(param_value, str) or "${" not in param_value:
            continue
        if "${item" in param_value:
            continue  # Skip batch item refs

        # Find source node from template ref
        for ref_name in _PARAM_REF_RE.findall(param_value):
            if ref_name not in sibling_node_ids:
                continue
            source_mid = _to_mermaid_id(prefix + ref_name)

            # Generate edge to each expanded item's input (if it has this input)
            for item_label, child_ir in expanded_items:
                child_inputs = child_ir.get("inputs", {})
                if param_name not in child_inputs:
                    continue
                item_mermaid_id = _to_mermaid_id(child_prefix_base + item_label)
                item_prefix = child_prefix_base + item_label + "__"
                target_mid = _to_mermaid_id(f"{item_prefix}in_{param_name}")
                lines.append(f"{indent}{source_mid} --> {target_mid}")
                items_with_data_flow.add(item_mermaid_id)

    return items_with_data_flow


def _try_expand_batch_item(
    item: Any,
    item_label: str,
    item_mermaid_id: str,
    lines: list[str],
    indent: str,
    prefix: str,
    resolve_child: Callable[[dict[str, Any], Optional[Path]], Optional[SubWorkflowResult]],
    base_path: Optional[Path],
    max_depth: int,
    current_depth: int,
    seen: set[str],
    direction: str,
    descriptions: bool,
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
        resolve_child,
        base_path,
        seen,
    )
    if child_result is None:
        return None

    path_key = str(child_result.path) if child_result.path else None
    if path_key:
        seen.add(path_key)

    subgraph_label = _escape_label(f"{item_label} (workflow)")
    lines.append(f'{indent}subgraph {item_mermaid_id} ["{subgraph_label}"]')
    child_base = child_result.path.parent if child_result.path else base_path
    _render_workflow(
        child_result.ir,
        lines,
        resolve_child,
        child_base,
        max_depth,
        current_depth + 1,
        prefix + item_label + "__",
        seen,
        direction,
        descriptions,
    )
    lines.append(f"{indent}end")
    lines.append(f"{indent}{_subgraph_style(item_mermaid_id, current_depth + 1)}")

    if path_key:
        seen.discard(path_key)
    return child_result.ir


# ---------------------------------------------------------------------------
# Core rendering
# ---------------------------------------------------------------------------


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
    descriptions: bool,
    suppress_io: bool = False,
) -> dict[str, dict[str, str]]:
    """Render a single workflow (or sub-workflow) into mermaid lines.

    Args:
        suppress_io: When True, skip rendering internal IO nodes and end nodes.
            Used when the parent renders IO externally via wrapper subgraphs.

    Returns:
        The ``outgoing_map`` built during rendering — maps subgraph mermaid IDs
        to their output node IDs. Needed by the parent to route edges through
        nested sub-workflow outputs.
    """
    nodes = ir.get("nodes", [])
    edges = ir.get("edges", [])
    indent = "    " * (current_depth + 1)

    deduped_edges = _deduplicate_edges(edges)
    decision_nodes = _detect_decision_nodes(edges)
    fork_join_map: dict[str, list[str]] = {}
    outgoing_map: dict[str, dict[str, str]] = {}  # subgraph_id → {name: output_mermaid_id}
    data_flow_targets: set[str] = set()  # subgraph IDs with data-flow edges to inputs
    incoming_map: dict[str, dict[str, str]] = {}  # subgraph_id → {name: input_mermaid_id}
    parent_inputs = ir.get("inputs", {})
    sibling_node_ids = {n.get("id", "") for n in nodes}

    # Sub-workflow boundary: render inputs at top (unless parent handles IO)
    if current_depth > 0 and not suppress_io:
        _render_subworkflow_inputs(ir, lines, indent, prefix)

    for node in nodes:
        _render_node(
            node,
            lines,
            indent,
            prefix,
            decision_nodes,
            fork_join_map,
            outgoing_map,
            incoming_map,
            data_flow_targets,
            resolve_child,
            base_path,
            max_depth,
            current_depth,
            seen,
            direction,
            descriptions,
            parent_inputs,
            sibling_node_ids,
        )

    # Top-level: connect inputs to consuming nodes (now that incoming_map is populated)
    if current_depth == 0:
        _connect_top_level_inputs(ir, lines, incoming_map)

    # Sub-workflow boundary: render outputs (unless parent handles IO)
    if current_depth > 0 and not suppress_io:
        output_ids = _render_subworkflow_outputs(ir, lines, indent, prefix, outgoing_map)
    else:
        output_ids = []

    # Top-level: render workflow outputs at the bottom
    if current_depth == 0:
        output_ids = _render_top_level_outputs(ir, lines, outgoing_map)

    _render_end_nodes_and_edges(
        nodes,
        edges,
        deduped_edges,
        decision_nodes,
        fork_join_map,
        outgoing_map,
        incoming_map,
        data_flow_targets,
        lines,
        indent,
        prefix,
        output_ids,
        suppress_io,
    )

    return outgoing_map


_WORKFLOW_TYPES = {"workflow", "pflow.runtime.workflow_executor"}


def _render_node(
    node: dict[str, Any],
    lines: list[str],
    indent: str,
    prefix: str,
    decision_nodes: set[str],
    fork_join_map: dict[str, list[str]],
    outgoing_map: dict[str, dict[str, str]],
    incoming_map: dict[str, dict[str, str]],
    data_flow_targets: set[str],
    resolve_child: Optional[Callable[[dict[str, Any], Optional[Path]], Optional[SubWorkflowResult]]],
    base_path: Optional[Path],
    max_depth: int,
    current_depth: int,
    seen: set[str],
    direction: str,
    descriptions: bool,
    parent_inputs: dict[str, Any],
    sibling_node_ids: set[str],
) -> None:
    """Render a single node declaration (regular, batch, or sub-workflow)."""
    node_id = node.get("id", "unknown")
    node_type = node.get("type", "unknown")
    mermaid_id = _to_mermaid_id(prefix + node_id)
    purpose = node.get("purpose", "")
    batch = node.get("batch")

    # Batch with inline items: fork/join rendering
    if batch and isinstance(batch.get("items"), list):
        _render_batch_inline(
            node,
            batch["items"],
            batch.get("parallel", False),
            lines,
            indent,
            prefix,
            node_type,
            descriptions,
            fork_join_map,
            resolve_child=resolve_child,
            base_path=base_path,
            max_depth=max_depth,
            current_depth=current_depth,
            seen=seen,
            direction=direction,
            sibling_node_ids=sibling_node_ids,
            data_flow_targets=data_flow_targets,
            outgoing_map=outgoing_map,
        )
        return

    # Compute batch label for dynamic batch
    dynamic_batch_label = _dynamic_batch_label(batch)

    # Sub-workflow expansion
    if node_type in _WORKFLOW_TYPES and resolve_child is not None and current_depth < max_depth:
        child_result = _try_resolve_child(node, resolve_child, base_path, seen)
        if child_result is not None:
            # 1. External input wrapper (BEFORE subgraph)
            _render_external_inputs(child_result.ir, lines, indent, node_id, prefix)

            # 2. Subgraph with suppress_io=True (NO internal IO)
            child_outgoing = _render_subgraph(
                node_id,
                node_type,
                mermaid_id,
                dynamic_batch_label,
                child_result,
                lines,
                indent,
                prefix,
                resolve_child,
                base_path,
                max_depth,
                current_depth,
                seen,
                direction,
                descriptions,
                purpose=purpose,
                suppress_io=True,
            )

            # 3. External output wrapper (AFTER subgraph, replaces _populate_outgoing_map)
            _render_external_outputs(child_result.ir, lines, indent, node_id, prefix, outgoing_map, child_outgoing)

            # 4. Data-flow edges and routing maps (SAME as before)
            child_inputs = child_result.ir.get("inputs", {})
            if child_inputs:
                _generate_data_flow_edges(
                    node,
                    child_result.ir,
                    lines,
                    indent,
                    prefix,
                    prefix + node_id + "__",
                    parent_inputs,
                    sibling_node_ids,
                    outgoing_map,
                )
                data_flow_targets.add(mermaid_id)
                child_prefix = prefix + node_id + "__"
                incoming_map[mermaid_id] = {name: _to_mermaid_id(f"{child_prefix}in_{name}") for name in child_inputs}
            return

    # Regular node declaration
    is_decision = node_id in decision_nodes
    label = _format_label(node_id, node_type, descriptions, purpose, dynamic_batch_label)

    if dynamic_batch_label:
        # Dynamic batch: use procs (stacked rectangles) shape via @{} syntax.
        # Can't combine with :::classDef — use style directive instead.
        lines.append(f'{indent}{mermaid_id}@{{ shape: procs, label: "{label}" }}')
        _, _, css_class = _get_node_shape(node_type, is_decision)
        lines.append(f"{indent}style {mermaid_id} {_classdef_to_style(css_class)}")
    else:
        shape_open, shape_close, css_class = _get_node_shape(node_type, is_decision)
        lines.append(f'{indent}{mermaid_id}{shape_open}"{label}"{shape_close}:::{css_class}')


_SUBGRAPH_OPACITIES = [0.07, 0.14, 0.21, 0.28]


def _subgraph_style(mermaid_id: str, depth: int) -> str:
    """Return a Mermaid style directive for subgraph nesting depth.

    Uses a neutral gray with increasing ``fill-opacity`` so nesting is
    visible on both light and dark themes.
    """
    opacity = _SUBGRAPH_OPACITIES[min(depth, len(_SUBGRAPH_OPACITIES) - 1)]
    return f"style {mermaid_id} fill:#808080,fill-opacity:{opacity},stroke:#999"


def _dynamic_batch_label(batch: Optional[dict[str, Any]]) -> str:
    """Return a batch suffix string like ' (parallel x|sources|)' for dynamic batch.

    Extracts the source variable name from the template ref (first segment
    of ``${ref.field}``), e.g. ``${sources}`` -> ``sources``,
    ``${zip-concepts-with-briefs.result}`` -> ``zip-concepts-with-briefs``.
    """
    if not batch or not isinstance(batch.get("items"), str):
        return ""
    items_ref = batch["items"]
    # Extract first segment from ${ref.field...}
    match = _PARAM_REF_RE.search(items_ref)
    source_name = match.group(1) if match else "N"
    parallel_prefix = "parallel " if batch.get("parallel", False) else ""
    return f" ({parallel_prefix}x|{source_name}|)"


def _render_subgraph(
    node_id: str,
    node_type: str,
    mermaid_id: str,
    dynamic_batch_label: str,
    child_result: SubWorkflowResult,
    lines: list[str],
    indent: str,
    prefix: str,
    resolve_child: Optional[Callable[[dict[str, Any], Optional[Path]], Optional[SubWorkflowResult]]],
    base_path: Optional[Path],
    max_depth: int,
    current_depth: int,
    seen: set[str],
    direction: str,
    descriptions: bool,
    purpose: str = "",
    suppress_io: bool = False,
) -> dict[str, dict[str, str]]:
    """Render a sub-workflow as a mermaid subgraph.

    Returns the child's ``outgoing_map`` so the parent can route edges
    through nested sub-workflow outputs.
    """
    path_key = str(child_result.path) if child_result.path else None
    if path_key:
        seen.add(path_key)

    if dynamic_batch_label:
        subgraph_label = _escape_label(node_id) + dynamic_batch_label
    else:
        subgraph_label = _escape_label(f"{node_id} ({node_type})")
    if descriptions and purpose:
        subgraph_label += f"<br/>{_escape_label(_first_sentence(purpose))}"

    lines.append(f'{indent}subgraph {mermaid_id} ["{subgraph_label}"]')
    child_base = child_result.path.parent if child_result.path else base_path
    child_outgoing = _render_workflow(
        child_result.ir,
        lines,
        resolve_child,
        child_base,
        max_depth,
        current_depth + 1,
        prefix + node_id + "__",
        seen,
        direction,
        descriptions,
        suppress_io=suppress_io,
    )
    lines.append(f"{indent}end")
    lines.append(f"{indent}{_subgraph_style(mermaid_id, current_depth + 1)}")

    if path_key:
        seen.discard(path_key)

    return child_outgoing


def _resolve_edge_endpoints(
    from_id: str,
    to_id: str,
    fork_join_map: dict[str, list[str]],
    outgoing_map: dict[str, dict[str, str]],
    incoming_map: dict[str, dict[str, str]],
) -> list[tuple[str, str]]:
    """Resolve edge endpoints through IO name-matching and fork/join maps.

    Returns a list of (from_mermaid_id, to_mermaid_id) pairs to render.
    """
    out_dict = outgoing_map.get(from_id)
    in_dict = incoming_map.get(to_id)

    if out_dict and in_dict:
        # Both sides have IO — name-matched: output→input with same name
        pairs = [(out_mid, in_dict[name]) for name, out_mid in out_dict.items() if name in in_dict]
        return pairs or [(from_id, to_id)]
    if out_dict:
        # Source has outputs, target is regular — fan from outputs
        to_ids = fork_join_map.get(to_id, [to_id])
        return [(out_mid, tid) for out_mid in out_dict.values() for tid in to_ids]

    # No output map for original source — expand via fork_join_map.
    # After expansion, check if each expanded item has its own outputs
    # (e.g., batch items with internal IO that populated outgoing_map).
    from_ids = fork_join_map.get(from_id, [from_id])
    to_ids = fork_join_map.get(to_id, [to_id])

    result: list[tuple[str, str]] = []
    for fid in from_ids:
        fid_out = outgoing_map.get(fid)
        if fid_out:
            # Route through this item's outputs
            for out_mid in fid_out.values():
                result.extend((out_mid, tid) for tid in to_ids)
        else:
            result.extend((fid, tid) for tid in to_ids)
    return result


def _render_edge(
    edge: dict[str, Any],
    lines: list[str],
    indent: str,
    prefix: str,
    fork_join_map: dict[str, list[str]],
    outgoing_map: Optional[dict[str, dict[str, str]]] = None,
    incoming_map: Optional[dict[str, dict[str, str]]] = None,
    data_flow_targets: Optional[set[str]] = None,
) -> None:
    """Render a single edge with fork/join and IO routing."""
    from_id = _to_mermaid_id(prefix + edge["from"])
    to_id = _to_mermaid_id(prefix + edge["to"])

    # Suppress structural edges to subgraphs with data-flow inputs,
    # UNLESS the source has outputs (output→input name matching handles those)
    _outgoing = outgoing_map or {}
    if data_flow_targets and from_id not in _outgoing:
        # Direct target has data-flow coverage
        if to_id in data_flow_targets:
            return
        # Fork/join target: suppress if ALL expanded items have data-flow coverage
        fork_targets = fork_join_map.get(to_id)
        if fork_targets and all(ft in data_flow_targets for ft in fork_targets):
            return

    action = edge.get("action")

    if action == "error":
        arrow = " -.->|error| "
    elif "action" in edge and action not in (None, "default"):
        arrow = f" -->|{_escape_label(str(action))}| "
    else:
        arrow = " --> "

    pairs = _resolve_edge_endpoints(
        from_id,
        to_id,
        fork_join_map,
        _outgoing,
        incoming_map or {},
    )
    for fid, tid in pairs:
        lines.append(f"{indent}{fid}{arrow}{tid}")


def _render_end_nodes_and_edges(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    deduped_edges: list[dict[str, Any]],
    decision_nodes: set[str],
    fork_join_map: dict[str, list[str]],
    outgoing_map: dict[str, dict[str, str]],
    incoming_map: dict[str, dict[str, str]],
    data_flow_targets: set[str],
    lines: list[str],
    indent: str,
    prefix: str,
    output_ids: Optional[list[str]] = None,
    suppress_io: bool = False,
) -> None:
    """Render end/output nodes (if branching) and all edges with routing.

    When ``output_ids`` exist, source->output edges are already rendered
    by ``_render_subworkflow_outputs``.  When ``suppress_io`` is True,
    the parent handles IO externally — skip end node generation.
    """
    # End node: only for branching workflows without output nodes,
    # and not when parent handles IO externally
    terminals: set[str] = set()
    if decision_nodes and not output_ids and not suppress_io:
        terminals = _find_terminal_nodes(nodes, edges)
        if terminals:
            end_id = _to_mermaid_id(f"{prefix}pflow_end")
            lines.append(f'{indent}{end_id}(("end"))')

    # Edges
    for edge in deduped_edges:
        _render_edge(edge, lines, indent, prefix, fork_join_map, outgoing_map, incoming_map, data_flow_targets)

    # End node edges (only when no outputs — outputs have source-based edges)
    if terminals:
        end_id = _to_mermaid_id(f"{prefix}pflow_end")
        for t in sorted(terminals):
            t_mermaid = _to_mermaid_id(prefix + t)
            t_ids = fork_join_map.get(t_mermaid, [t_mermaid])
            for tid in t_ids:
                lines.append(f"{indent}{tid} --> {end_id}")


# ---------------------------------------------------------------------------
# Sub-workflow resolution (unchanged)
# ---------------------------------------------------------------------------


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
        logger.debug("Failed to resolve sub-workflow for node '%s'", node.get("id", "?"), exc_info=True)
        return None

    if result is None:
        return None

    # Cycle detection: check if this path is already on the recursion stack
    if result.path and str(result.path) in seen:
        return None

    return result


# ---------------------------------------------------------------------------
# ID and label helpers (unchanged)
# ---------------------------------------------------------------------------


def _to_mermaid_id(node_id: str) -> str:
    """Convert a pflow node ID to a valid Mermaid node ID.

    Returns the ID unchanged — hyphens and underscores are both valid
    in Mermaid's bracket syntax (``id["label"]``), so no sanitization
    is needed. Replacing hyphens with underscores would cause ID
    collisions between ``foo-bar`` and ``foo_bar``.
    """
    return node_id


def _escape_label(text: str) -> str:
    """Escape special characters for Mermaid node and edge labels."""
    return text.replace('"', "&quot;").replace("|", "&#124;")
