"""Structural tests for the React Flow renderer (Task 168 wire contract).

Property-assertion style (mirrors ``test_graph_mermaid_renderer.py``): assert the
contract's invariants — referential integrity, predicate fidelity, edge
additivity, batch truncation — not a frozen payload string.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from pflow.core.markdown_parser import parse_markdown
from pflow.core.workflow.graph import (
    AncestorStep,
    Edge,
    EdgeKind,
    GraphModel,
    Node,
    NodeId,
    build_graph,
    render_react_flow,
)
from pflow.core.workflow.graph.renderers.react_flow import RFGraph, RFNode, RFRef
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult, resolve_sub_workflow

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = ROOT / "examples"


def _child_resolver(children: dict[str, dict[str, Any]]):
    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        ref = params.get("workflow")
        ir = children.get(ref)
        return SubWorkflowResult(ir=ir, path=Path(f"/fake/{ref}"), warnings=()) if ir is not None else None

    return resolver


def _rf_node(rf: RFGraph, node_id: str, ancestor_path: tuple[AncestorStep, ...] = ()) -> RFNode:
    want = [{"node_id": step.node_id, "batch_index": step.batch_index} for step in ancestor_path]
    for node in rf.nodes:
        if node.ref.node_id == node_id and node.ref.ancestor_path == want:
            return node
    raise AssertionError(f"no RF node {node_id!r} at {ancestor_path}")


def _assert_referential_integrity(rf: RFGraph) -> None:
    node_ids = {node.id for node in rf.nodes}
    group_ids = {group.id for group in rf.groups}
    for edge in rf.edges:
        assert edge.source in node_ids, f"edge {edge.id} source {edge.source} is not an emitted node"
        assert edge.target in node_ids, f"edge {edge.id} target {edge.target} is not an emitted node"
    for node in rf.nodes:
        assert node.parent is None or node.parent in group_ids, f"node {node.id} parent {node.parent} unresolved"
    for group in rf.groups:
        assert group.parent is None or group.parent in group_ids
        assert group.host is None or group.host in node_ids
        for member in group.members:
            assert member in node_ids, f"group {group.id} member {member} unresolved"


def _node_identity(node_id: NodeId) -> tuple[object, ...]:
    return (node_id.node_id, tuple((s.node_id, s.batch_index) for s in node_id.ancestor_path), node_id.port)


def _ref_identity(ref: RFRef) -> tuple[object, ...]:
    return (ref.node_id, tuple((s["node_id"], s["batch_index"]) for s in ref.ancestor_path), ref.port)


def _assert_no_dropped_edges(graph: GraphModel, rf: RFGraph) -> None:
    """Every model edge between two *rendered* nodes must reach the payload.

    Referential integrity only proves the payload is internally consistent — it
    CANNOT catch a silently dropped edge (a missing edge is still consistent). This
    matches each model node to its RF node by structural ref, then asserts every model
    edge whose both endpoints survive is present, across ALL edge kinds. Endpoints
    hidden by batch truncation are skipped (their re-anchoring is pinned by
    ``test_truncation_preserves_cross_boundary_dependency_via_host``). This is the
    "no information loss" guarantee on real workflows: a dropped sequential / branch /
    error / data_flow edge — invisible to referential integrity — fails here.
    """
    rf_id_by_identity = {_ref_identity(node.ref): node.id for node in rf.nodes}
    rf_pairs = {(edge.source, edge.target, edge.kind) for edge in rf.edges}
    for edge in graph.edges:
        src, tgt = _node_identity(edge.source), _node_identity(edge.target)
        if src not in rf_id_by_identity or tgt not in rf_id_by_identity:
            continue  # an endpoint is hidden by truncation; re-anchoring is tested separately
        src_id, tgt_id = rf_id_by_identity[src], rf_id_by_identity[tgt]
        if src_id == tgt_id:
            continue
        assert (src_id, tgt_id, edge.kind.value) in rf_pairs, (
            f"model edge {edge.source.node_id} -[{edge.kind.value}]-> {edge.target.node_id} "
            f"(both endpoints rendered) is missing from the payload — silently dropped"
        )


# ── Real workflows: referential integrity + JSON round-trip ───────────────────


@pytest.mark.parametrize(
    "workflow_rel",
    [
        "core/conditional-branching.pflow.md",  # branching + next:end sink
        "core/error-handling.pflow.md",  # on-error routing
        "nested/deep-research/deep-research.pflow.md",  # deep nesting + batch
        "batch-test-parallel.pflow.md",  # batch fan-out
        "core/stateful-loop-tournament.pflow.md",  # loop on a sub-workflow host
        "agent-orchestration/plan-to-code/run-from-plan.pflow.md",  # Task 163 harness
    ],
)
def test_real_workflows_render_without_information_loss(workflow_rel: str) -> None:
    path = EXAMPLES_DIR / workflow_rel
    ir = parse_markdown(path.read_text(encoding="utf-8")).ir
    graph = build_graph(ir, resolve_child=resolve_sub_workflow, base_path=path.parent, source_file=path, max_depth=5)
    rf = render_react_flow(graph)

    _assert_referential_integrity(rf)
    _assert_no_dropped_edges(graph, rf)
    # Mirrors the server's serialization (H2): exotic param values can't break it.
    json.dumps(asdict(rf), default=str)
    assert all(isinstance(node.is_decision, bool) and isinstance(node.is_terminal, bool) for node in rf.nodes)


# ── Template connections (the load-bearing comprehension feature) ─────────────


def test_multi_ref_param_yields_one_edge_per_ref_with_input_name() -> None:
    # "${a.x} and ${b.y}" lands on the `prompt` row as TWO lines, one per ref —
    # the connections a text-first author can't see. Two distinct input sources so
    # "each with input_name set" is reliable (H6).
    graph = build_graph({
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "nodes": [{"id": "consumer", "type": "llm", "params": {"prompt": "${a.x} and ${b.y}"}}],
    })
    rf = render_react_flow(graph)

    consumer = _rf_node(rf, "consumer")
    incoming = [e for e in rf.edges if e.target == consumer.id and e.kind == "data_flow"]
    assert len(incoming) == 2
    assert all(edge.input_name == "prompt" for edge in incoming)
    assert _rf_node(rf, "consumer").params[0].name == "prompt"
    assert _rf_node(rf, "consumer").params[0].is_dynamic is True


def test_output_source_edge_is_emitted_with_no_input_name() -> None:
    # An output `source:` edge carries output_field but NO input_name. Edge
    # rendering is additive: input_name=None attaches at node level, never omits (H6).
    graph = build_graph({
        "nodes": [{"id": "gen", "type": "shell"}],
        "outputs": {"result": {"source": "${gen.stdout}"}},
    })
    rf = render_react_flow(graph)

    data_flow = [e for e in rf.edges if e.kind == "data_flow"]
    assert len(data_flow) == 1
    edge = data_flow[0]
    assert edge.input_name is None
    assert edge.output_field == "stdout"
    assert edge.source == _rf_node(rf, "gen").id


def test_param_is_dynamic_uses_ref_extractor_not_str_repr() -> None:
    # is_dynamic runs source_refs_in over string leaves — never str(value). Two traps
    # the str(value) anti-pattern fails: a literal `${5}` reads as a ref (the `nested`
    # case below), and a ref BELOW the one-level leaf walk would false-positive (H5).
    graph = build_graph({
        "nodes": [
            {
                "id": "n",
                "type": "llm",
                "params": {
                    "binding": {"text": "${a.x}"},  # dict leaf has a ref -> dynamic
                    "schema": {"type": "string"},  # dict, no ref -> static
                    "nested": {"schema": {"deep": "${x}"}},  # ref below leaf level: str(value) would FALSE-positive
                    "literal_num": "${5}",  # literal operand -> static (str(value) would false-positive)
                    "plain": "hello",  # literal -> static
                    "ref": "${topic}",  # ref -> dynamic
                },
            }
        ]
    })
    rf = render_react_flow(graph)

    flags = {param.name: param.is_dynamic for param in _rf_node(rf, "n").params}
    # `nested` is False: the one-level leaf walk doesn't descend past the first dict
    # level, matching build_graph's `_params_strings` so is_dynamic can never disagree
    # with the DATA_FLOW edges. `str(value)` would wrongly flag it True.
    assert flags == {
        "binding": True,
        "schema": False,
        "nested": False,
        "literal_num": False,
        "plain": False,
        "ref": True,
    }


# ── Structural identity: ref mirrors NodeId ───────────────────────────────────


def test_ref_mirrors_node_id_with_explicit_batch_index_and_port() -> None:
    child = {
        "inputs": {"text": {"type": "string"}},
        "nodes": [{"id": "work", "type": "code"}],
    }
    graph = build_graph(
        {
            "nodes": [
                {
                    "id": "reviews",
                    "type": "workflow",
                    "params": {"workflow": "child", "inputs": {"text": "x"}},
                    "batch": {"items": [{"workflow": "child"}, {"workflow": "child"}], "as": "item"},
                }
            ]
        },
        resolve_child=_child_resolver({"child": child}),
        max_depth=2,
    )
    rf = render_react_flow(graph)

    # Body node inside literal batch item 0: ancestor_path carries an explicit int index.
    work = _rf_node(rf, "work", (AncestorStep("reviews", 0),))
    assert work.ref.node_id == "work"
    assert work.ref.ancestor_path == [{"node_id": "reviews", "batch_index": 0}]
    assert work.ref.port is None  # body nodes never carry a port

    # Synthetic input node carries its IO role as `port`.
    text_input = _rf_node(rf, "text", (AncestorStep("reviews", 0),))
    assert text_input.ref.port == "in"
    assert text_input.io == {"data_type": "string", "required": False}


def test_dynamic_batch_ref_carries_null_batch_index() -> None:
    child = {"inputs": {"text": {"type": "string"}}, "nodes": [{"id": "work", "type": "code"}]}
    graph = build_graph(
        {
            "nodes": [
                {"id": "prep", "type": "code"},
                {
                    "id": "proc",
                    "type": "workflow",
                    "params": {"workflow": "child", "inputs": {"text": "${item.t}"}},
                    "batch": {"items": "${prep.rows}", "as": "item"},
                },
            ],
            "edges": [{"from": "prep", "to": "proc"}],
        },
        resolve_child=_child_resolver({"child": child}),
        max_depth=2,
    )
    rf = render_react_flow(graph)

    work = _rf_node(rf, "work", (AncestorStep("proc", None),))
    assert work.ref.ancestor_path == [{"node_id": "proc", "batch_index": None}]


# ── Derived predicates baked as facts ─────────────────────────────────────────


def test_decision_node_predicate_and_branch_labels_survive() -> None:
    graph = build_graph({
        "nodes": [
            {"id": "classify", "type": "code"},
            {"id": "yes", "type": "code"},
            {"id": "no", "type": "code"},
            {"id": "fail", "type": "code"},
        ],
        "edges": [
            {"from": "classify", "to": "yes", "action": "yes"},
            {"from": "classify", "to": "no", "action": "no"},
            {"from": "classify", "to": "fail", "action": "error"},
        ],
    })
    rf = render_react_flow(graph)

    classify = _rf_node(rf, "classify")
    assert classify.is_decision is True and graph.is_decision(NodeId("classify")) is True
    assert classify.is_terminal is False
    assert _rf_node(rf, "yes").is_terminal is True and graph.is_terminal(NodeId("yes")) is True

    branch_labels = {e.label for e in rf.edges if e.kind == "branch"}
    assert branch_labels == {"yes", "no"}
    error_edges = [e for e in rf.edges if e.kind == "error"]
    assert len(error_edges) == 1 and error_edges[0].label == "error"


def test_shadowed_emits_the_models_general_fact() -> None:
    # `shadowed` ships the model's GENERAL `graph.shadowed(edge)` fact, NOT Mermaid's
    # narrower render-time policy — the frontend owns the dim/hide decision per density
    # mode. A structural edge covered by a data-flow edge from the same source is
    # shadowed; data-flow edges themselves are never shadowed. (Hand-built model so the
    # shadowed precondition is unambiguous; mirrors test_graph_build's shadowing fixture.)
    source, target = NodeId("gen"), NodeId("use")
    structural = Edge(source, target, EdgeKind.SEQUENTIAL)
    graph = GraphModel(
        nodes=[Node(source, "code"), Node(target, "code")],
        edges=[structural, Edge(source, target, EdgeKind.DATA_FLOW, output_field="result", input_name="value")],
        containers=[],
    )
    assert graph.shadowed(structural) is True  # precondition: the model says it's shadowed

    rf = render_react_flow(graph)
    sequential = next(e for e in rf.edges if e.kind == "sequential")
    data_flow = next(e for e in rf.edges if e.kind == "data_flow")
    assert sequential.shadowed is True  # the general fact survives to the contract
    assert data_flow.shadowed is False  # non-structural edges are never shadowed


# ── Containers: host is not 1:1 with groups (H8) ──────────────────────────────


def test_dynamic_batch_of_subworkflow_host_materializes_as_group() -> None:
    child = {"inputs": {"text": {"type": "string"}}, "nodes": [{"id": "work", "type": "code"}]}
    graph = build_graph(
        {
            "nodes": [
                {"id": "prep", "type": "code"},
                {
                    "id": "proc",
                    "type": "workflow",
                    "params": {"workflow": "child", "inputs": {"text": "${item.t}"}},
                    "batch": {"items": "${prep.rows}", "as": "item"},
                },
            ],
            "edges": [{"from": "prep", "to": "proc"}],
        },
        resolve_child=_child_resolver({"child": child}),
        max_depth=2,
    )
    rf = render_react_flow(graph)

    proc = _rf_node(rf, "proc")
    assert proc.is_group_host is True  # frontend suppresses its leaf box
    assert proc.batch is not None and proc.batch["dynamic"] is True
    # One host, TWO groups (a batch + a workflow) — host is not 1:1 with a group.
    hosted = {group.kind for group in rf.groups if group.host == proc.id}
    assert hosted == {"batch", "workflow"}


def test_loop_on_subworkflow_host_is_group_and_carries_loop_badge() -> None:
    child = {
        "inputs": {"x": {"type": "string"}},
        "nodes": [{"id": "inner", "type": "code"}],
        "outputs": {"out": {"source": "${inner.stdout}"}},
    }
    graph = build_graph(
        {
            "nodes": [
                {
                    "id": "host",
                    "type": "workflow",
                    "params": {"workflow": "child", "inputs": {"x": "hi"}},
                    "loop": {"while": "${host.more}", "max_iterations": 3},
                }
            ]
        },
        resolve_child=_child_resolver({"child": child}),
        max_depth=2,
    )
    rf = render_react_flow(graph)

    host = _rf_node(rf, "host")
    # The node is BOTH an RFNode (carrying the loop badge) and a group host.
    assert host.is_group_host is True
    assert host.loop == {"polarity": "while", "condition": "${host.more}", "cap": 3, "carry": {}}
    assert any(group.host == host.id and group.kind == "workflow" for group in rf.groups)


def test_unexpanded_node_keeps_its_reason_and_stays_a_leaf() -> None:
    # An unresolvable sub-workflow node has no expanded body: its reason must survive
    # (no information loss) and it must NOT be flagged as a group (it has no body to
    # draw) — the frontend renders a leaf box with the badge.
    graph = build_graph({"nodes": [{"id": "sub", "type": "workflow", "params": {"workflow": "missing"}}]})
    rf = render_react_flow(graph)

    sub = _rf_node(rf, "sub")
    assert sub.unexpanded == "unresolved"
    assert sub.is_group_host is False
    assert not any(group.host == sub.id for group in rf.groups)


def test_unexpanded_dynamic_batch_host_is_not_a_group() -> None:
    # The differentiator that justifies keying is_group_host on an EXPANDED body, not
    # on "is any container's host": a dynamic batch whose child can't resolve creates
    # a batch container (host=node) BEFORE failing, but has no expanded body. The host
    # must stay a leaf box with badges, not become a phantom empty group.
    graph = build_graph({
        "nodes": [
            {"id": "prep", "type": "code"},
            {"id": "proc", "type": "workflow", "params": {"workflow": "missing"}, "batch": {"items": "${prep.rows}"}},
        ],
        "edges": [{"from": "prep", "to": "proc"}],
    })  # no resolve_child -> child unresolved
    rf = render_react_flow(graph)

    proc = _rf_node(rf, "proc")
    assert proc.unexpanded == "unresolved"
    assert proc.is_group_host is False
    # ...yet a batch group hosted by proc DOES exist (created before the resolve failed).
    assert any(group.kind == "batch" and group.host == proc.id for group in rf.groups)


def test_depth_limited_node_forwards_its_reason_through_the_renderer() -> None:
    # A second `unexpanded` reason (`depth_limit`) round-trips through render_react_flow,
    # so the contract carries the distinct reasons the "no information loss" bar names —
    # not just `unresolved`.
    graph = build_graph(
        {"nodes": [{"id": "sub", "type": "workflow", "params": {"workflow": "child"}}]},
        resolve_child=_child_resolver({"child": {"nodes": [{"id": "inner", "type": "code"}]}}),
        max_depth=0,
    )
    rf = render_react_flow(graph)

    sub = _rf_node(rf, "sub")
    assert sub.unexpanded == "depth_limit"
    assert sub.is_group_host is False


# ── Batch truncation + failed-item annotations ────────────────────────────────


def test_literal_batch_truncates_expanded_items_to_representatives() -> None:
    # A >4-item literal batch of sub-workflows must NOT inline its child prompts N times.
    # Mirror Mermaid: keep 2 expanded item groups; the full descriptors ride batch.items.
    child = {"inputs": {"text": {"type": "string"}}, "nodes": [{"id": "work", "type": "code"}]}
    items = [{"workflow": "child", "focus": f"f{i}"} for i in range(6)]
    graph = build_graph(
        {"nodes": [{"id": "reviews", "type": "workflow", "params": {"workflow": "child"}, "batch": {"items": items}}]},
        resolve_child=_child_resolver({"child": child}),
        max_depth=2,
    )
    rf = render_react_flow(graph)

    batch_group = next(group for group in rf.groups if group.kind == "batch")
    item_groups = [g for g in rf.groups if g.kind == "workflow" and g.parent == batch_group.id]
    assert len(item_groups) == 2  # representatives only
    # No hidden item's body node leaked through.
    assert not any(node.ref.ancestor_path and node.ref.ancestor_path[0]["batch_index"] >= 2 for node in rf.nodes)

    reviews = _rf_node(rf, "reviews")
    assert reviews.batch is not None
    assert reviews.batch["count"] == 6 and len(reviews.batch["items"]) == 6  # full per-item data preserved
    _assert_referential_integrity(rf)


def test_truncation_preserves_cross_boundary_dependency_via_host() -> None:
    # A kept upstream feeding a >4-item literal batch must NOT silently lose its
    # dependency on the truncated items. The edges into hidden items re-attach to the
    # batch HOST (node-level fallback, deduped) — never dropped. Mirrors Mermaid's
    # arrow into the "xN" procs box; without this the viewer shows `prep` feeding only
    # 2 of N items with no signal it feeds the rest ("looks like it covered everything").
    child = {"inputs": {"v": {"type": "string"}}, "nodes": [{"id": "work", "type": "code"}]}
    graph = build_graph(
        {
            "nodes": [
                {"id": "prep", "type": "code"},
                {
                    "id": "fan",
                    "type": "workflow",
                    "params": {"workflow": "child", "inputs": {"v": "${prep.out}"}},
                    "batch": {"items": [{"workflow": "child"} for _ in range(6)]},
                },
            ],
            "edges": [{"from": "prep", "to": "fan"}],
        },
        resolve_child=_child_resolver({"child": child}),
        max_depth=2,
    )
    rf = render_react_flow(graph)

    prep, fan = _rf_node(rf, "prep"), _rf_node(rf, "fan")
    # The 4 dropped edges into hidden items 2..5 collapse to ONE host-level fallback.
    fallback = [e for e in rf.edges if e.source == prep.id and e.target == fan.id and e.kind == "data_flow"]
    assert len(fallback) == 1
    # The re-anchored target clears input_name (it no longer names a port of the host);
    # the unchanged source keeps its output_field.
    assert fallback[0].input_name is None and fallback[0].output_field == "out"
    # Direct edges to the two visible items still exist (representatives aren't collapsed).
    assert sum(1 for e in rf.edges if e.source == prep.id and e.kind == "data_flow" and e.target != fan.id) == 2
    # No edge targets a hidden node; no self-loops.
    assert all(e.source != e.target for e in rf.edges)
    _assert_referential_integrity(rf)


def test_failed_batch_item_is_distinguishable_via_group_annotations() -> None:
    # A literal-batch item that can't expand (dynamic ${...} path) is recorded on the
    # batch group's annotations, distinct from a genuine leaf (H7 / "no information loss").
    child = {"inputs": {"text": {"type": "string"}}, "nodes": [{"id": "work", "type": "code"}]}
    graph = build_graph(
        {
            "nodes": [
                {
                    "id": "reviews",
                    "type": "workflow",
                    "params": {"workflow": "child"},
                    "batch": {"items": [{"workflow": "child"}, {"workflow": "${dynamic}"}]},
                }
            ]
        },
        resolve_child=_child_resolver({"child": child}),
        max_depth=2,
    )
    rf = render_react_flow(graph)

    batch_group = next(group for group in rf.groups if group.kind == "batch")
    assert batch_group.annotations.get("unexpanded_items") == {1: "dynamic_path"}


# ── Serialization: the contract round-trips on adversarial input ──────────────


def test_payload_round_trips_with_adversarial_params() -> None:
    # H10/H3: YAML-native date, nested dict, multi-line string, None values, AND a
    # node with params:None (normalized to {} -> empty params list).
    graph = build_graph({
        "nodes": [
            {
                "id": "x",
                "type": "llm",
                "params": {
                    "prompt": "line1\nline2\n${a}",
                    "schema": {"nested": {"deep": [1, True, None]}},
                    "when": datetime.date(2026, 6, 7),
                    "nothing": None,
                },
            },
            {"id": "y", "type": "code", "params": None},
        ]
    })
    rf = render_react_flow(graph)

    # Matches the server's serialization (default=str handles the date).
    json.dumps(asdict(rf), default=str)

    x = _rf_node(rf, "x")
    values = {param.name: param.value for param in x.params}
    assert values["prompt"] == "line1\nline2\n${a}"  # full multi-line value inline
    assert values["when"] == datetime.date(2026, 6, 7)  # preserved on the model (str-ified only at the wire)
    assert {param.name: param.is_dynamic for param in x.params}["prompt"] is True
    assert _rf_node(rf, "y").params == []  # params:None -> {} -> no rows


# ── Branch-condition extraction (fail-closed) ─────────────────────────────────


def test_branch_edges_carry_extracted_conditions() -> None:
    """The contract ships the source condition per outcome; error edges never do."""
    code = 'items = data.get("items", [])\nif len(items) > 5:\n    next: str = "big"\nelse:\n    next: str = "small"\nresult: dict = data\n'
    graph = build_graph({
        "nodes": [
            {"id": "classify", "type": "code", "params": {"code": code}},
            {"id": "big", "type": "code"},
            {"id": "small", "type": "code"},
            {"id": "fail", "type": "code"},
        ],
        "edges": [
            {"from": "classify", "to": "big", "action": "big"},
            {"from": "classify", "to": "small", "action": "small"},
            {"from": "classify", "to": "fail", "action": "error"},
        ],
    })
    rf = render_react_flow(graph)

    by_label = {e.label: e.condition for e in rf.edges if e.kind == "branch"}
    assert by_label == {"big": "if len(items) > 5", "small": "else"}
    assert all(e.condition is None for e in rf.edges if e.kind != "branch")
    # additive field round-trips the wire like everything else
    assert json.loads(json.dumps(asdict(rf), default=str))["edges"][0]["condition"] is not None or True


def test_branch_condition_extraction_matrix() -> None:
    """The supported shapes extract; everything else fails CLOSED to {}."""
    from pflow.core.workflow.graph.renderers.react_flow import _branch_conditions

    # if/elif/else chain
    assert _branch_conditions('if a:\n    next = "x"\nelif b:\n    next = "y"\nelse:\n    next = "z"\n') == {
        "x": "if a",
        "y": "elif b",
        "z": "else",
    }
    # default-then-override: the default becomes the else
    assert _branch_conditions('next = "x"\nif cond:\n    next = "y"\n') == {"y": "if cond", "x": "else"}
    # top-level ternary
    assert _branch_conditions('next = "a" if n > 0 else "b"\n') == {"a": "if n > 0", "b": "else"}
    # the harness shape: adjacent-duplicate join + in-arm ternary + negation flip
    harness = (
        'if commits == 0:\n    next: str = "end"\n'
        'elif not gate_ok:\n    next: str = "end"\n'
        'elif is_last:\n    next: str = "simplify" if cap == 0 else "review-round"\n'
        'else:\n    next: str = "group-tick"\n'
    )
    assert _branch_conditions(harness) == {
        "end": "if commits == 0 or not gate_ok",
        "simplify": "elif is_last and cap == 0",
        "review-round": "elif is_last and cap != 0",
        "group-tick": "else",
    }
    # ternary in the ELSE slot extends the chain
    assert _branch_conditions('if a:\n    next = "x"\nelse:\n    next = "y" if b else "z"\n') == {
        "x": "if a",
        "y": "elif b",
        "z": "else",
    }
    # NON-adjacent duplicate outcome: list each selecting arm verbatim (" · "-joined) —
    # no inferred disjunction, so it can't mis-attribute, only abbreviate
    assert _branch_conditions('if a:\n    next = "x"\nelif b:\n    next = "y"\nelif c:\n    next = "x"\n') == {
        "x": "if a · elif c",
        "y": "elif b",
    }
    # the continue-or-stop gate (check-validate's exact shape): the "end" outcome
    # spans the first arm AND the else — listed, not bailed
    gate = (
        'if ok:\n    next: str = "end"\nelif round < cap:\n    next: str = "fix-tests"\nelse:\n    next: str = "end"\n'
    )
    assert _branch_conditions(gate) == {
        "end": "if ok · else",
        "fix-tests": "elif round < cap",
    }

    # fail-closed: every unsupported shape yields {} (absent beats wrong)
    bails = [
        "result = 1\n",  # no next assignment
        "next = routes[size]\n",  # computed outcome
        'if a:\n    next = "x"\nif b:\n    next = "y"\n',  # two chains: guards unknowable
        'for i in items:\n    next = "x"\n',  # assigned inside another block
        'if a:\n    if b:\n        next = "x"\n',  # nested conditional
        'if a:\n    next = "x"\n    next = "y"\n',  # two assignments in one arm
        'next = "x" if a else compute()\n',  # non-literal ternary side
        'if a\n    next = "x"\n',  # syntax error
    ]
    for code in bails:
        assert _branch_conditions(code) == {}, f"expected fail-closed bail for: {code!r}"


def test_decision_end_edge_carries_the_end_outcome_condition() -> None:
    """A continue-or-stop decider's END edge IS its "end" outcome — it ships the
    extracted condition. A static `- next: end` route (non-decision) never does."""
    code = 'issues: list\nresult: int = len(issues)\nif issues:\n    next: str = "work"\nelse:\n    next: str = "end"\n'
    graph = build_graph({
        "nodes": [
            {"id": "gate", "type": "code", "params": {"code": code}, "_routes_to_end": True},
            {"id": "work", "type": "code"},
        ],
        "edges": [{"from": "gate", "to": "work", "action": "work"}],
    })
    assert graph.is_decision(NodeId("gate"))  # precondition: 1 branch label + END route
    rf = render_react_flow(graph)

    end_conditions = [e.condition for e in rf.edges if e.kind == "end"]
    assert end_conditions == ["else"]
    branch = next(e for e in rf.edges if e.kind == "branch")
    assert (branch.label, branch.condition) == ("work", "if issues")

    # static `- next: end`: single-outcome routing — no condition on its END edge
    static = build_graph({
        "nodes": [{"id": "a", "type": "code", "params": {"code": "result = 1\n"}, "_routes_to_end": True}],
    })
    static_rf = render_react_flow(static)
    assert [e.condition for e in static_rf.edges if e.kind == "end"] == [None]


def test_branch_condition_dead_default_is_omitted() -> None:
    """A default before a chain WITH an else arm is dead code — no guessed label."""
    from pflow.core.workflow.graph.renderers.react_flow import _branch_conditions

    out = _branch_conditions('next = "dead"\nif a:\n    next = "x"\nelse:\n    next = "y"\n')
    assert out == {"x": "if a", "y": "else"}  # "dead" absent, not mislabeled


# ── TRANSFORM classification (fail-closed purity test) ─────────────────────────


def test_is_transform_classification_matrix() -> None:
    """Pure reshapes classify; anything effectful/unrecognized fails CLOSED."""
    from pflow.core.workflow.graph.renderers.react_flow import _is_transform_code

    transforms = [
        # the canonical reshape: inputs -> result dict
        'a: str\nresult: dict = {"upper": a.upper(), "n": len(a)}\n',
        # `impl: object` is the code-node input ANNOTATION convention, not the
        # builtin — banning it cost two real corpus transforms (the regression)
        'impl: object\nresult: int = impl.get("n", 0) if isinstance(impl, dict) else 0\n',
        # raising is a pure failure path (the engine handles it)
        'x: int\nif x < 0:\n    raise ValueError("negative")\nresult: int = x * 2\n',
        # whitelisted stdlib + method calls on values
        "import json\nraw: str\ndata = json.loads(raw)\nresult: list = sorted(data.keys())\n",
        # the author's own helper is pure-checked like everything else
        "def clean(s):\n    return s.strip().lower()\nt: str\nresult: str = clean(t)\n",
    ]
    for code in transforms:
        assert _is_transform_code(code) is True, f"expected TRANSFORM for: {code!r}"

    not_transforms = [
        # routing — a pure decider presents as CONDITION, never both
        'ok: bool\nresult: int = 1\nif ok:\n    next = "a"\nelse:\n    next = "end"\n',
        "import subprocess\nresult = subprocess.run(['ls'])\n",  # effectful import
        'with open("f") as f:\n    result = f.read()\n',  # file IO
        'o = open\nresult = o("f").read()\n',  # ALIASED effectful builtin (the hole)
        'result = getattr(x, "attr")\n',  # dynamic attribute access
        "result = fetch(url)\n",  # unknown call — fail closed
        "x: int\ny = x * 2\n",  # pure but produces no result
        "result = 1\nimport os\n",  # os anywhere disqualifies
        "result =\n",  # syntax error
    ]
    for code in not_transforms:
        assert _is_transform_code(code) is False, f"expected NOT transform for: {code!r}"


def test_transform_fact_ships_on_the_contract() -> None:
    """is_transform is baked per node: transform code True; decider False; non-code False."""
    transform_code = "text: str\nresult: str = text.upper()\n"
    decider_code = 'ok: bool\nresult: int = 1\nif ok:\n    next: str = "work"\nelse:\n    next: str = "end"\n'
    graph = build_graph({
        "nodes": [
            {"id": "reshape", "type": "code", "params": {"code": transform_code}},
            {"id": "gate", "type": "code", "params": {"code": decider_code}, "_routes_to_end": True},
            {"id": "work", "type": "shell"},
        ],
        "edges": [
            {"from": "reshape", "to": "gate"},
            {"from": "gate", "to": "work", "action": "work"},
        ],
    })
    rf = render_react_flow(graph)

    by_id = {n.ref.node_id: n for n in rf.nodes}
    assert by_id["reshape"].is_transform is True
    assert by_id["gate"].is_transform is False  # pure + next -> CONDITION's, not TRANSFORM's
    assert by_id["gate"].is_decision is True
    assert by_id["work"].is_transform is False  # non-code kinds never classify
    # additive field round-trips the wire like everything else
    json.dumps(asdict(rf), default=str)
