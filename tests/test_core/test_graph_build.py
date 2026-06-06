"""Structural tests for workflow GraphModel construction."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pflow.core.markdown_parser import parse_markdown
from pflow.core.workflow.graph import (
    AncestorStep,
    BatchSpec,
    Container,
    Edge,
    EdgeKind,
    GraphModel,
    Node,
    NodeId,
    SourceRef,
    build_graph,
)
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult, resolve_sub_workflow

ROOT = Path(__file__).resolve().parents[2]
INPUT_SCOPE = "__inputs__"
OUTPUT_SCOPE = "__outputs__"


def _node(graph: GraphModel, node_id: NodeId) -> Node:
    node = graph.node(node_id)
    assert node is not None
    return node


def _parse(path: str) -> dict[str, Any]:
    return parse_markdown((ROOT / path).read_text(encoding="utf-8")).ir


def _input_id(name: str, *ancestor_path: AncestorStep) -> NodeId:
    return NodeId(name, (*ancestor_path, AncestorStep(INPUT_SCOPE)))


def _output_id(name: str, *ancestor_path: AncestorStep) -> NodeId:
    return NodeId(name, (*ancestor_path, AncestorStep(OUTPUT_SCOPE)))


def test_model_helpers_are_derived_from_edges() -> None:
    a = NodeId("a")
    b = NodeId("b")
    c = NodeId("c")
    graph = GraphModel(
        nodes=[Node(a, "code"), Node(b, "code"), Node(c, "code")],
        edges=[
            Edge(a, b, EdgeKind.BRANCH, label="yes"),
            Edge(a, c, EdgeKind.BRANCH, label="no"),
            Edge(b, c, EdgeKind.END),
        ],
        containers=[],
    )

    assert graph.is_decision(a)
    assert not graph.is_decision(b)
    assert graph.is_terminal(b)
    assert graph.node(c) == Node(c, "code")


def test_build_graph_collapses_duplicate_default_edge_and_preserves_error_edge() -> None:
    graph = build_graph({
        "nodes": [
            {"id": "a", "type": "code"},
            {"id": "b", "type": "code"},
            {"id": "c", "type": "code"},
        ],
        "edges": [
            {"from": "a", "to": "b"},
            {"from": "a", "to": "b", "action": "go"},
            {"from": "a", "to": "c", "action": "error"},
        ],
    })

    assert Edge(NodeId("a"), NodeId("b"), EdgeKind.BRANCH, label="go") in graph.edges
    assert Edge(NodeId("a"), NodeId("c"), EdgeKind.ERROR, label="error") in graph.edges
    assert Edge(NodeId("a"), NodeId("b"), EdgeKind.SEQUENTIAL) not in graph.edges


def test_default_edges_do_not_count_toward_decision_detection() -> None:
    graph = build_graph({
        "nodes": [
            {"id": "a", "type": "code"},
            {"id": "b", "type": "code"},
            {"id": "c", "type": "code"},
        ],
        "edges": [
            {"from": "a", "to": "b", "action": "default"},
            {"from": "a", "to": "c", "action": "go"},
        ],
    })

    assert not graph.is_decision(NodeId("a"))


def test_build_graph_ignores_loop_metadata_without_polarity() -> None:
    graph = build_graph({
        "nodes": [
            {"id": "r", "type": "code", "loop": {"max_iterations": 5}},
        ],
    })

    assert _node(graph, NodeId("r")).loop is None


def test_model_rejects_dangling_edges_and_parent_mismatches() -> None:
    a = NodeId("a")
    missing = NodeId("missing")

    try:
        GraphModel(nodes=[Node(a, "code")], edges=[Edge(a, missing, EdgeKind.SEQUENTIAL)], containers=[])
    except ValueError as exc:
        assert "target" in str(exc)
    else:
        raise AssertionError("GraphModel accepted a dangling edge target")

    try:
        GraphModel(
            nodes=[Node(a, "code", parent="box")],
            edges=[],
            containers=[Container(id="box", kind="workflow", nesting_depth=0, members=[])],
        )
    except ValueError as exc:
        assert "missing from parent" in str(exc)
    else:
        raise AssertionError("GraphModel accepted inconsistent parent/container membership")


def test_model_rejects_duplicate_node_and_container_ids() -> None:
    node_id = NodeId("duplicate")

    try:
        GraphModel(nodes=[Node(node_id, "code"), Node(node_id, "shell")], edges=[], containers=[])
    except ValueError as exc:
        assert "Duplicate graph node id" in str(exc)
    else:
        raise AssertionError("GraphModel accepted duplicate node IDs")

    try:
        GraphModel(
            nodes=[],
            edges=[],
            containers=[
                Container(id="box", kind="workflow", nesting_depth=0),
                Container(id="box", kind="batch", nesting_depth=0),
            ],
        )
    except ValueError as exc:
        assert "Duplicate graph container id" in str(exc)
    else:
        raise AssertionError("GraphModel accepted duplicate container IDs")


def test_nested_subworkflow_outputs_thread_to_sibling_consumer() -> None:
    ir = _parse("examples/nested/deep-research/deep-research.pflow.md")
    graph = build_graph(
        ir,
        resolve_child=resolve_sub_workflow,
        base_path=ROOT / "examples/nested/deep-research",
        max_depth=3,
    )

    score_output = NodeId(
        "score",
        (AncestorStep("analyze-sources", None), AncestorStep("score"), AncestorStep(OUTPUT_SCOPE)),
    )
    compile_node = NodeId("compile", (AncestorStep("analyze-sources", None),))
    assert _node(graph, score_output).kind == "output"
    assert (
        Edge(
            source=score_output,
            target=compile_node,
            kind=EdgeKind.DATA_FLOW,
            output_field="score",
            input_name="scores",
        )
        in graph.edges
    )


def test_root_and_child_nodes_carry_source_file_refs() -> None:
    workflow_path = ROOT / "examples/nested/deep-research/deep-research.pflow.md"
    ir = _parse("examples/nested/deep-research/deep-research.pflow.md")
    graph = build_graph(
        ir,
        resolve_child=resolve_sub_workflow,
        base_path=workflow_path.parent,
        source_file=workflow_path,
        max_depth=2,
    )

    prepare = _node(graph, NodeId("prepare"))
    child = _node(graph, NodeId("extract", (AncestorStep("analyze-sources", None),)))

    assert prepare.source == SourceRef(file=str(workflow_path), line=23)
    assert child.source is not None
    assert child.source.file == str(workflow_path.parent / "analyze-source.pflow.md")
    assert child.source.line is not None


def test_nodes_carry_param_level_source_refs_for_click_to_read() -> None:
    source_file = Path("/private/tmp/workflows/main.pflow.md")
    graph = build_graph(
        {
            "nodes": [
                {
                    "id": "implement",
                    "type": "llm",
                    "_source_line": 10,
                    "_source_lines": {"code": 18},
                    "_source_files": {"prompt": "./prompts/implement.prompt.md"},
                }
            ]
        },
        source_file=source_file,
    )

    implement = _node(graph, NodeId("implement"))

    assert implement.source == SourceRef(file=str(source_file), line=10)
    assert implement.param_sources["code"] == SourceRef(file=str(source_file), line=18)
    assert implement.param_sources["prompt"] == SourceRef(
        file=str((source_file.parent / "prompts/implement.prompt.md").resolve()),
        line=None,
    )


def test_batch_model_carries_literal_items_without_dots_and_expands_all_subworkflows() -> None:
    ir = _parse("examples/nested/deep-research/deep-research.pflow.md")
    graph = build_graph(
        ir,
        resolve_child=resolve_sub_workflow,
        base_path=ROOT / "examples/nested/deep-research",
        max_depth=2,
    )
    reviews = _node(graph, NodeId("reviews"))

    assert reviews.batch == BatchSpec(
        parallel=True,
        dynamic=False,
        as_name="item",
        count=5,
        items=reviews.batch.items if reviews.batch else None,
    )
    assert reviews.batch is not None
    assert len(reviews.batch.items or []) == 5
    assert graph.node(NodeId("__dots")) is None
    for index in range(5):
        assert graph.node(NodeId("critique", (AncestorStep("reviews", index),))) is not None


def test_literal_leaf_batch_items_are_data_not_nodes() -> None:
    graph = build_graph({
        "nodes": [
            {
                "id": "review",
                "type": "llm",
                "batch": {"items": ["correctness", "sources", "logic"], "parallel": True},
            }
        ],
        "edges": [],
    })

    review = _node(graph, NodeId("review"))
    assert review.batch is not None
    assert review.batch.items == ["correctness", "sources", "logic"]
    assert graph.node(NodeId("#1", (AncestorStep("review", 0),))) is None


def test_dynamic_batch_over_workflow_has_one_static_representative() -> None:
    ir = _parse("examples/nested/deep-research/deep-research.pflow.md")
    graph = build_graph(
        ir,
        resolve_child=resolve_sub_workflow,
        base_path=ROOT / "examples/nested/deep-research",
        max_depth=2,
    )

    analyze = _node(graph, NodeId("analyze-sources"))
    assert analyze.batch is not None
    assert analyze.batch.dynamic is True
    assert analyze.batch.items is None
    assert graph.node(NodeId("extract", (AncestorStep("analyze-sources", None),))) is not None


def test_synthetic_input_and_output_with_same_name_have_distinct_identity() -> None:
    graph = build_graph({
        "inputs": {"result": {"type": "string"}},
        "nodes": [{"id": "produce", "type": "code"}],
        "outputs": {"result": {"source": "${produce.result}"}},
    })

    input_node = _node(graph, _input_id("result"))
    output_node = _node(graph, _output_id("result"))

    assert input_node.kind == "input"
    assert output_node.kind == "output"
    assert input_node.id != output_node.id


def test_routes_to_end_builds_synthetic_end_edges_without_changing_decision_or_terminal() -> None:
    validate_fix = _parse("examples/agent-orchestration/plan-to-code/execute-plan/validate-fix/validate-fix.pflow.md")
    graph = build_graph(validate_fix)

    check = NodeId("check-validate")
    end_edges = [edge for edge in graph.edges if edge.source == check and edge.kind == EdgeKind.END]
    assert len(end_edges) == 1
    assert _node(graph, end_edges[0].target).kind == "end"
    assert not graph.is_decision(check)
    assert not graph.is_terminal(check)

    conditional = _parse("examples/core/conditional-branching.pflow.md")
    branch_graph = build_graph(conditional)
    handle_error = NodeId("handle-error")
    assert [edge for edge in branch_graph.edges if edge.source == handle_error and edge.kind == EdgeKind.END]
    assert branch_graph.is_terminal(handle_error)

    manual = build_graph({
        "nodes": [
            {"id": "work", "type": "shell", "_routes_to_end": True},
            {"id": "handler", "type": "shell"},
        ],
        "edges": [{"from": "work", "to": "handler", "action": "error"}],
    })
    assert manual.is_terminal(NodeId("work"))


def test_loop_spec_is_node_metadata_and_loop_condition_and_carry_do_not_create_data_flow_edges() -> None:
    ir = _parse("examples/core/stateful-loop-tournament.pflow.md")
    graph = build_graph(
        ir,
        resolve_child=resolve_sub_workflow,
        base_path=ROOT / "examples/core",
        max_depth=1,
    )
    run_rounds = _node(graph, NodeId("run-rounds"))

    assert run_rounds.loop is not None
    assert run_rounds.loop.polarity == "while"
    assert run_rounds.loop.condition == "${run-rounds.more}"
    assert run_rounds.loop.cap == 10
    assert run_rounds.loop.carry == {"contenders": "${run-rounds.survivors}"}
    assert not any(edge.kind == EdgeKind.DATA_FLOW and edge.input_name == "max_review_rounds" for edge in graph.edges)


def test_loop_max_iterations_template_creates_dependency_edges() -> None:
    graph = build_graph({
        "inputs": {"cap": {"type": "int"}},
        "nodes": [
            {"id": "prepare", "type": "code"},
            {
                "id": "run",
                "type": "code",
                "loop": {
                    "while": "${run.result.more}",
                    "max_iterations": "${cap}",
                    "carry": {"value": "${run.result.value}"},
                },
            },
            {
                "id": "review",
                "type": "code",
                "loop": {"until": "${review.done}", "max_iterations": "${prepare.limit}"},
            },
        ],
    })

    assert (
        Edge(
            source=_input_id("cap"),
            target=NodeId("run"),
            kind=EdgeKind.DATA_FLOW,
            input_name="max_iterations",
        )
        in graph.edges
    )
    assert (
        Edge(
            source=NodeId("prepare"),
            target=NodeId("review"),
            kind=EdgeKind.DATA_FLOW,
            output_field="limit",
            input_name="max_iterations",
        )
        in graph.edges
    )
    assert not any(edge.kind == EdgeKind.DATA_FLOW and edge.source == NodeId("run") for edge in graph.edges)


def test_batch_item_input_edges_cover_dynamic_source_and_literal_item_workflows() -> None:
    ir = _parse("examples/nested/deep-research/deep-research.pflow.md")
    graph = build_graph(
        ir,
        resolve_child=resolve_sub_workflow,
        base_path=ROOT / "examples/nested/deep-research",
        max_depth=2,
    )

    prepare = NodeId("prepare")
    combine = NodeId("combine")
    dynamic_content = _input_id("content", AncestorStep("analyze-sources", None))
    dynamic_focus = _input_id("focus", AncestorStep("analyze-sources", None))
    literal_summary = _input_id("summary", AncestorStep("reviews", 0))

    assert (
        Edge(
            source=prepare,
            target=dynamic_content,
            kind=EdgeKind.DATA_FLOW,
            output_field="result",
            input_name="content",
        )
        in graph.edges
    )
    assert (
        Edge(
            source=prepare,
            target=dynamic_focus,
            kind=EdgeKind.DATA_FLOW,
            output_field="result",
            input_name="focus",
        )
        in graph.edges
    )
    assert (
        Edge(
            source=combine,
            target=literal_summary,
            kind=EdgeKind.DATA_FLOW,
            output_field="result",
            input_name="summary",
        )
        in graph.edges
    )


def test_batch_item_input_edges_honor_custom_alias_for_dynamic_batches() -> None:
    child = {"inputs": {"text": {"type": "string"}}, "nodes": [{"id": "work", "type": "code"}]}

    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return SubWorkflowResult(ir=child, path=Path("/fake/child.pflow.md"), warnings=())

    graph = build_graph(
        {
            "nodes": [
                {"id": "prepare", "type": "code"},
                {
                    "id": "process",
                    "type": "workflow",
                    "params": {"workflow": "child", "inputs": {"text": "${record.text}"}},
                    "batch": {"items": "${prepare.rows}", "as": "record"},
                },
            ],
            "edges": [{"from": "prepare", "to": "process"}],
        },
        resolve_child=resolver,
        max_depth=2,
    )

    assert (
        Edge(
            source=NodeId("prepare"),
            target=_input_id("text", AncestorStep("process", None)),
            kind=EdgeKind.DATA_FLOW,
            output_field="rows",
            input_name="text",
        )
        in graph.edges
    )


def test_literal_batch_item_alias_refs_do_not_resolve_as_sibling_nodes() -> None:
    child = {"inputs": {"text": {"type": "string"}}, "nodes": [{"id": "work", "type": "code"}]}

    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return SubWorkflowResult(ir=child, path=Path("/fake/child.pflow.md"), warnings=())

    graph = build_graph(
        {
            "nodes": [
                {"id": "record", "type": "code"},
                {
                    "id": "reviews",
                    "type": "workflow",
                    "params": {"workflow": "child", "inputs": {"text": "${record.text}"}},
                    "batch": {
                        "items": [{"workflow": "./child.pflow.md", "name": "one"}],
                        "as": "record",
                    },
                },
            ],
        },
        resolve_child=resolver,
        max_depth=2,
    )

    assert (
        Edge(
            source=NodeId("record"),
            target=_input_id("text", AncestorStep("reviews", 0)),
            kind=EdgeKind.DATA_FLOW,
            output_field="text",
            input_name="text",
        )
        not in graph.edges
    )


def test_output_source_coalesce_filters_literals_and_keeps_multiple_real_sources() -> None:
    graph = build_graph({
        "nodes": [
            {"id": "a", "type": "code"},
            {"id": "b", "type": "code"},
        ],
        "outputs": {
            "summary": {"source": "${a.result ?? b.result}"},
            "pr_url": {"source": '${a.url ?? "none"}'},
        },
    })

    summary = _output_id("summary")
    pr_url = _output_id("pr_url")
    assert len([edge for edge in graph.edges if edge.target == summary and edge.kind == EdgeKind.DATA_FLOW]) == 2
    assert len([edge for edge in graph.edges if edge.target == pr_url and edge.kind == EdgeKind.DATA_FLOW]) == 1


def test_unexpanded_reasons_and_inline_cycle_detection() -> None:
    parent = {"nodes": [{"id": "call", "type": "workflow", "params": {"workflow": "child"}}], "edges": []}

    assert _node(build_graph(parent, max_depth=0), NodeId("call")).unexpanded == "depth_limit"
    assert (
        _node(
            build_graph({"nodes": [{"id": "call", "type": "workflow", "params": {"workflow": "${which}"}}]}),
            NodeId("call"),
        ).unexpanded
        == "dynamic_path"
    )

    def unresolved(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return None

    assert _node(build_graph(parent, resolve_child=unresolved), NodeId("call")).unexpanded == "unresolved"

    def empty(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return SubWorkflowResult(ir={"nodes": []}, path=None, warnings=())

    assert _node(build_graph(parent, resolve_child=empty), NodeId("call")).unexpanded == "unresolved"

    recursive_child = {"nodes": [{"id": "recurse", "type": "workflow", "params": {"workflow": "same"}}], "edges": []}

    def inline_cycle(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return SubWorkflowResult(ir=recursive_child, path=None, warnings=())

    cycle_graph = build_graph(parent, resolve_child=inline_cycle, max_depth=10)
    assert _node(cycle_graph, NodeId("recurse", (AncestorStep("call"),))).unexpanded == "cycle"


def test_same_child_path_expands_under_distinct_structural_paths() -> None:
    child = {"nodes": [{"id": "inner", "type": "shell"}], "edges": []}
    shared_path = Path("/fake/child.pflow.md")

    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return SubWorkflowResult(ir=child, path=shared_path, warnings=())

    graph = build_graph(
        {
            "nodes": [
                {"id": "first", "type": "workflow", "params": {"workflow": "child"}},
                {"id": "second", "type": "workflow", "params": {"workflow": "child"}},
            ],
            "edges": [{"from": "first", "to": "second"}],
        },
        resolve_child=resolver,
        max_depth=1,
    )

    assert graph.node(NodeId("inner", (AncestorStep("first"),))) is not None
    assert graph.node(NodeId("inner", (AncestorStep("second"),))) is not None


def test_top_level_input_connects_to_each_distinct_consumer_once() -> None:
    graph = build_graph({
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {"id": "a", "type": "code", "params": {"inputs": {"topic": "${topic}"}}},
            {"id": "b", "type": "code", "params": {"inputs": {"topic": "${topic}", "again": "${topic}"}}},
        ],
        "edges": [{"from": "a", "to": "b"}],
    })

    source = _input_id("topic")
    targets = [edge.target for edge in graph.edges if edge.source == source and edge.kind == EdgeKind.DATA_FLOW]
    assert targets.count(NodeId("a")) == 1
    assert targets.count(NodeId("b")) == 1


def test_shadowed_preserves_expanded_output_sources_and_requires_full_batch_coverage() -> None:
    source = NodeId("source")
    child_output = _output_id("result", AncestorStep("source"))
    target = NodeId("target")
    structural = Edge(source, target, EdgeKind.SEQUENTIAL)
    graph = GraphModel(
        nodes=[
            Node(source, "workflow"),
            Node(child_output, "output"),
            Node(target, "code"),
            Node(NodeId("other"), "code"),
        ],
        edges=[structural, Edge(NodeId("other"), target, EdgeKind.DATA_FLOW)],
        containers=[],
    )
    assert not graph.shadowed(structural)

    prepare = NodeId("prepare")
    subwf = NodeId("subwf")
    top_input = _input_id("my_setting")
    subwf_input = _input_id("config", AncestorStep("subwf"))
    parent_input_graph = GraphModel(
        nodes=[
            Node(prepare, "code"),
            Node(subwf, "workflow"),
            Node(top_input, "input"),
            Node(subwf_input, "input", parent="subwf-inputs"),
        ],
        edges=[
            Edge(prepare, subwf, EdgeKind.SEQUENTIAL),
            Edge(top_input, subwf_input, EdgeKind.DATA_FLOW),
        ],
        containers=[
            Container(id="subwf", kind="workflow", nesting_depth=1, host=subwf),
            Container(
                id="subwf-inputs",
                kind="input_wrapper",
                nesting_depth=1,
                parent="subwf",
                members=[subwf_input],
            ),
        ],
    )
    assert not parent_input_graph.shadowed(Edge(prepare, subwf, EdgeKind.SEQUENTIAL))

    batch = NodeId("batch")
    item0 = _input_id("input", AncestorStep("batch", 0))
    item1 = _input_id("input", AncestorStep("batch", 1))
    upstream = NodeId("upstream")
    batch_edge = Edge(upstream, batch, EdgeKind.SEQUENTIAL)
    batch_graph = GraphModel(
        nodes=[
            Node(batch, "workflow"),
            Node(upstream, "code"),
            Node(item0, "input", parent="item0"),
            Node(item1, "input", parent="item1"),
        ],
        edges=[batch_edge, Edge(upstream, item0, EdgeKind.DATA_FLOW)],
        containers=[
            Container(id="batch-box", kind="batch", nesting_depth=1, host=batch),
            Container(id="item0", kind="workflow", nesting_depth=1, parent="batch-box", members=[item0]),
            Container(id="item1", kind="workflow", nesting_depth=1, parent="batch-box", members=[item1]),
        ],
    )
    assert not batch_graph.shadowed(batch_edge)

    covered = GraphModel(
        nodes=batch_graph.nodes,
        edges=[*batch_graph.edges, Edge(upstream, item1, EdgeKind.DATA_FLOW)],
        containers=batch_graph.containers,
    )
    assert covered.shadowed(batch_edge)


def test_shadowed_suppresses_direct_same_source_data_flow_edges() -> None:
    source = NodeId("source")
    target = NodeId("target")
    structural = Edge(source, target, EdgeKind.SEQUENTIAL)
    graph = GraphModel(
        nodes=[Node(source, "code"), Node(target, "code")],
        edges=[
            structural,
            Edge(source, target, EdgeKind.DATA_FLOW, output_field="result", input_name="value"),
        ],
        containers=[],
    )

    assert graph.shadowed(structural)


def test_graph_model_is_asdict_json_serializable_with_adversarial_values() -> None:
    graph = GraphModel(
        nodes=[
            Node(
                NodeId("batch"),
                "llm",
                batch=BatchSpec(
                    parallel=True,
                    dynamic=False,
                    count=1,
                    items=[{"nested": {"x": [1, True, None]}}],
                ),
                source=SourceRef(file=str(Path("/private/tmp/workflow.pflow.md")), line=7),
            )
        ],
        edges=[],
        containers=[],
    )

    json.dumps(asdict(graph))
