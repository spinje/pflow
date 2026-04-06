"""Edge preprocessing, routing resolution, edge rendering, and data-flow edge generation."""

from typing import Any, Optional

from pflow.core.workflow.mermaid._context import (
    _PARAM_REF_RE,
    _RESERVED_PARAMS,
    MermaidContext,
    _escape_label,
    _to_mermaid_id,
)

# ---------------------------------------------------------------------------
# Edge preprocessing (pure — no ctx)
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


def _find_terminal_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> set[str]:
    """Find nodes with no non-error outgoing edges.

    A node with ``- next: end`` has zero outgoing edges in the IR.
    A node with only an error edge (``on-error``) but ``next: end``
    has no non-error outgoing edges and is terminal for its success path.
    """
    has_non_error_outgoing = {e["from"] for e in edges if e.get("action") != "error"}
    return {n["id"] for n in nodes if n["id"] not in has_non_error_outgoing}


# ---------------------------------------------------------------------------
# Batch source extraction
# ---------------------------------------------------------------------------


def _extract_batch_source(node: dict[str, Any], ctx: MermaidContext) -> Optional[str]:
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
        if str(ref) in ctx.sibling_node_ids:
            return str(ref)
    return None


# ---------------------------------------------------------------------------
# Reference resolution
# ---------------------------------------------------------------------------


def _resolve_ref_source(
    ref_name: str,
    batch_source: Optional[str],
    ctx: MermaidContext,
) -> Optional[str]:
    """Resolve a template ref name to a mermaid source ID."""
    if ref_name == "item":
        if not batch_source:
            return None
        # Skip if source has outputs — name-matched structural edge handles it
        if _to_mermaid_id(ctx.prefix + batch_source) in ctx.has_expanded_outputs:
            return None
        return _to_mermaid_id(ctx.prefix + batch_source)
    if ref_name in ctx.sibling_node_ids:
        mermaid_id = _to_mermaid_id(ctx.prefix + ref_name)
        # If sibling has outputs, route through them instead of subgraph box
        out_dict = ctx.outgoing_routes.get(mermaid_id)
        if out_dict and len(out_dict) == 1:
            return next(iter(out_dict.values()))
        return mermaid_id
    if ref_name in ctx.parent_inputs:
        if not ctx.prefix:
            return None  # Depth 0: handled by _connect_top_level_inputs
        return _to_mermaid_id(f"{ctx.prefix}in_{ref_name}")
    return None


# ---------------------------------------------------------------------------
# Edge endpoint resolution
# ---------------------------------------------------------------------------


def _resolve_edge_endpoints(
    from_id: str,
    to_id: str,
    ctx: MermaidContext,
) -> list[tuple[str, str]]:
    """Resolve edge endpoints through IO name-matching and fork/join maps.

    Returns a list of (from_mermaid_id, to_mermaid_id) pairs to render.
    """
    out_dict = ctx.outgoing_routes.get(from_id)
    in_dict = ctx.incoming_map.get(to_id)

    if out_dict and in_dict:
        # Both sides have IO — name-matched: output→input with same name
        pairs = [(out_mid, in_dict[name]) for name, out_mid in out_dict.items() if name in in_dict]
        return pairs or [(from_id, to_id)]
    if out_dict:
        # Source has outputs, target is regular — fan from outputs
        to_ids = ctx.fork_join_map.get(to_id, [to_id])
        return [(out_mid, tid) for out_mid in out_dict.values() for tid in to_ids]

    # No output map for original source — expand via fork_join_map.
    # After expansion, check if each expanded item has its own outputs
    # (e.g., batch items with internal IO that populated outgoing_routes).
    from_ids = ctx.fork_join_map.get(from_id, [from_id])
    to_ids = ctx.fork_join_map.get(to_id, [to_id])

    result: list[tuple[str, str]] = []
    for fid in from_ids:
        fid_out = ctx.outgoing_routes.get(fid)
        if fid_out:
            # Route through this item's outputs
            for out_mid in fid_out.values():
                result.extend((out_mid, tid) for tid in to_ids)
        else:
            result.extend((fid, tid) for tid in to_ids)
    return result


# ---------------------------------------------------------------------------
# Edge rendering
# ---------------------------------------------------------------------------


def _render_edge(edge: dict[str, Any], ctx: MermaidContext) -> None:
    """Render a single edge with fork/join and IO routing."""
    from_id = _to_mermaid_id(ctx.prefix + edge["from"])
    to_id = _to_mermaid_id(ctx.prefix + edge["to"])

    # Suppress structural edges to subgraphs with data-flow inputs,
    # UNLESS the source has outputs (output→input name matching handles those)
    if ctx.data_flow_targets and from_id not in ctx.has_expanded_outputs:
        # Direct target has data-flow coverage
        if to_id in ctx.data_flow_targets:
            return
        # Fork/join target: suppress if ALL expanded items have data-flow coverage
        fork_targets = ctx.fork_join_map.get(to_id)
        if fork_targets and all(ft in ctx.data_flow_targets for ft in fork_targets):
            return

    action = edge.get("action")

    if action == "error":
        arrow = " -.->|error| "
    elif "action" in edge and action not in (None, "default"):
        arrow = f" -->|{_escape_label(str(action))}| "
    else:
        arrow = " --> "

    pairs = _resolve_edge_endpoints(from_id, to_id, ctx)
    for fid, tid in pairs:
        ctx.lines.append(f"{ctx.indent}{fid}{arrow}{tid}")


# ---------------------------------------------------------------------------
# Data-flow edge generation
# ---------------------------------------------------------------------------


def _generate_data_flow_edges(
    node: dict[str, Any],
    child_ir: dict[str, Any],
    child_prefix: str,
    ctx: MermaidContext,
) -> bool:
    """Generate edges from upstream nodes to sub-workflow input nodes.

    Parses template refs in the parent node's ``params`` to find which
    sibling nodes or parent inputs feed each child input.  For example,
    ``creative_direction: ${creative-direction.response}`` generates an
    edge from ``creative-direction`` to the child's ``in_creative_direction``.

    Returns True if at least one data-flow edge was generated.
    """
    child_inputs = child_ir.get("inputs", {})
    if not child_inputs:
        return False

    params = node.get("params", {})
    batch_source = _extract_batch_source(node, ctx)
    generated = False

    for param_name, param_value in params.items():
        if param_name in _RESERVED_PARAMS or param_name not in child_inputs:
            continue
        if not isinstance(param_value, str) or "${" not in param_value:
            continue

        target_mid = _to_mermaid_id(f"{child_prefix}in_{param_name}")
        for ref_name in _PARAM_REF_RE.findall(param_value):
            source_mid = _resolve_ref_source(ref_name, batch_source, ctx)
            if source_mid:
                ctx.lines.append(f"{ctx.indent}{source_mid} --> {target_mid}")
                generated = True

    return generated


def _generate_batch_item_data_flow(
    node: dict[str, Any],
    expanded_items: list[tuple[str, dict[str, Any]]],
    ctx: MermaidContext,
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
    child_prefix_base = ctx.prefix + node_id + "__"
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
            if ref_name not in ctx.sibling_node_ids:
                continue
            source_mid = _to_mermaid_id(ctx.prefix + ref_name)

            # Generate edge to each expanded item's input (if it has this input)
            for item_label, child_ir in expanded_items:
                child_inputs = child_ir.get("inputs", {})
                if param_name not in child_inputs:
                    continue
                item_mermaid_id = _to_mermaid_id(child_prefix_base + item_label)
                item_prefix = child_prefix_base + item_label + "__"
                target_mid = _to_mermaid_id(f"{item_prefix}in_{param_name}")
                ctx.lines.append(f"{ctx.indent}{source_mid} --> {target_mid}")
                items_with_data_flow.add(item_mermaid_id)

    return items_with_data_flow
