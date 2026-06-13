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
    IOPort,
    Node,
    NodeId,
    SourceRef,
    build_graph,
)
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult, resolve_sub_workflow

ROOT = Path(__file__).resolve().parents[2]


def _node(graph: GraphModel, node_id: NodeId) -> Node:
    node = graph.node(node_id)
    assert node is not None
    return node


def _parse(path: str) -> dict[str, Any]:
    return parse_markdown((ROOT / path).read_text(encoding="utf-8")).ir


def _input_id(name: str, *ancestor_path: AncestorStep) -> NodeId:
    return NodeId(name, ancestor_path, port="in")


def _output_id(name: str, *ancestor_path: AncestorStep) -> NodeId:
    return NodeId(name, ancestor_path, port="out")


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

    score_output = _output_id("score", AncestorStep("analyze-sources", None), AncestorStep("score"))
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


def test_nodes_carry_authored_param_values_for_click_to_read() -> None:
    prompt = "Summarize the report.\n\nFocus on:\n- risks\n- mitigations\n"
    graph = build_graph({
        "nodes": [
            {
                "id": "summarize",
                "type": "llm",
                "params": {"prompt": prompt, "model": "anthropic/claude-sonnet-4-5", "max_tokens": 1024},
            }
        ]
    })

    summarize = _node(graph, NodeId("summarize"))

    # The full multi-line prompt lives inline on the model; the React Flow renderer
    # owns the inline-vs-truncate policy, not build_graph. Scalars round-trip as-is.
    assert summarize.params["prompt"] == prompt
    assert summarize.params["model"] == "anthropic/claude-sonnet-4-5"
    assert summarize.params["max_tokens"] == 1024


def test_node_params_defaults_to_empty_dict_for_non_dict_ir() -> None:
    # Unvalidated IR may carry `params: None`/str/list; build_graph normalizes to {}
    # so downstream readers never hit AttributeError. Mirrors every other raw read here.
    graph = build_graph({
        "nodes": [
            {"id": "missing", "type": "code"},
            {"id": "nulled", "type": "code", "params": None},
            {"id": "listy", "type": "code", "params": ["not", "a", "dict"]},
        ]
    })

    assert _node(graph, NodeId("missing")).params == {}
    assert _node(graph, NodeId("nulled")).params == {}
    assert _node(graph, NodeId("listy")).params == {}


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
    # Disambiguation lives in NodeId.port, NOT a synthetic ancestor step: ancestor_path
    # stays empty (real descents only) so the runtime-trace join key is unaffected.
    assert (input_node.id.port, output_node.id.port) == ("in", "out")
    assert input_node.id.ancestor_path == () and output_node.id.ancestor_path == ()


def test_input_ports_carry_interface_data_and_required_defaults_true() -> None:
    graph = build_graph({
        "inputs": {
            "topic": {"type": "string", "description": "What to research"},
            "limit": {"type": "integer", "required": False, "default": 5},
        },
        "nodes": [{"id": "work", "type": "code"}],
    })

    # Description rides `purpose` (symmetric with outputs); an input that omits
    # `required:` IS required — the ir_schema default every runtime reader applies.
    topic = _node(graph, _input_id("topic"))
    assert topic.purpose == "What to research"
    assert topic.io == IOPort(data_type="string", required=True, default=None)

    limit = _node(graph, _input_id("limit"))
    assert limit.purpose == ""
    assert limit.io == IOPort(data_type="integer", required=False, default=5)
    # Inputs ship no source ref (the parser injects `_source_line` only for
    # outputs/nodes; the inputs schema forbids extra keys).
    assert limit.source is None


def test_routes_to_end_builds_synthetic_end_edges_and_counts_end_as_a_decision_outcome() -> None:
    validate_fix = _parse("examples/agent-orchestration/plan-to-code/execute-plan/validate-fix/validate-fix.pflow.md")
    graph = build_graph(validate_fix)

    check = NodeId("check-validate")
    end_edges = [edge for edge in graph.edges if edge.source == check and edge.kind == EdgeKind.END]
    assert len(end_edges) == 1
    assert _node(graph, end_edges[0].target).kind == "end"
    # A continue-or-stop decider IS a decision: 1 branch label (fix-tests) + the
    # END route = 2 distinct outcomes. (The old rule required >= 2 branch labels,
    # which missed every `if ok: next="end"` loop gate.)
    assert graph.is_decision(check)
    assert not graph.is_terminal(check)

    conditional = _parse("examples/core/conditional-branching.pflow.md")
    branch_graph = build_graph(conditional)
    handle_error = NodeId("handle-error")
    assert [edge for edge in branch_graph.edges if edge.source == handle_error and edge.kind == EdgeKind.END]
    assert branch_graph.is_terminal(handle_error)
    # A static `- next: end` (no branch edges) is single-outcome routing, not a decision.
    assert not branch_graph.is_decision(handle_error)


def test_is_decision_outcome_matrix() -> None:
    a, b, end = NodeId("a"), NodeId("b"), NodeId("__end__")

    def model(edges: list[Edge]) -> GraphModel:
        return GraphModel(
            nodes=[Node(a, "code"), Node(b, "code"), Node(end, "end")],
            edges=edges,
            containers=[],
        )

    # 1 branch label + an END route -> 2 outcomes -> decision
    assert model([Edge(a, b, EdgeKind.BRANCH, label="go"), Edge(a, end, EdgeKind.END)]).is_decision(a)
    # 1 branch label alone -> single forward outcome -> not a decision
    assert not model([Edge(a, b, EdgeKind.BRANCH, label="go")]).is_decision(a)
    # END route alone (static `- next: end` / every arm -> "end") -> not a decision
    assert not model([Edge(a, end, EdgeKind.END)]).is_decision(a)
    # ERROR edges never count as outcomes
    assert not model([Edge(a, b, EdgeKind.ERROR, label="error"), Edge(a, end, EdgeKind.END)]).is_decision(a)

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


def test_top_level_input_connects_once_per_distinct_ref() -> None:
    # One edge per distinct ${ref}: a node reading the same input in TWO params
    # gets TWO edges with distinct input_names — each param row gets its line
    # (the old pair-dedup kept one edge and orphaned the second row).
    graph = build_graph({
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {"id": "a", "type": "code", "params": {"inputs": {"topic": "${topic}"}}},
            {"id": "b", "type": "code", "params": {"inputs": {"topic": "${topic}", "again": "${topic}"}}},
        ],
        "edges": [{"from": "a", "to": "b"}],
    })

    source = _input_id("topic")
    edges = [edge for edge in graph.edges if edge.source == source and edge.kind == EdgeKind.DATA_FLOW]
    assert [edge.input_name for edge in edges if edge.target == NodeId("a")] == ["topic"]
    assert sorted(edge.input_name or "" for edge in edges if edge.target == NodeId("b")) == ["again", "topic"]


def test_plain_param_sibling_ref_forms_data_flow_edge() -> None:
    # The validator enforces `prompt: "...${gen.response}"` as a real ordering
    # dependency; the model carries it as an edge (one rule: every enforced
    # ${ref} is one DATA_FLOW edge).
    graph = build_graph({
        "nodes": [
            {"id": "gen", "type": "llm", "params": {"prompt": "write a poem"}},
            {"id": "consume", "type": "llm", "params": {"prompt": "Summarize: ${gen.response}"}},
        ],
        "edges": [{"from": "gen", "to": "consume"}],
    })

    assert (
        Edge(
            source=NodeId("gen"),
            target=NodeId("consume"),
            kind=EdgeKind.DATA_FLOW,
            output_field="response",
            input_name="prompt",
        )
        in graph.edges
    )


def test_interpolated_multi_ref_param_forms_one_edge_per_ref() -> None:
    graph = build_graph({
        "nodes": [
            {"id": "a", "type": "llm", "params": {"prompt": "x"}},
            {"id": "b", "type": "llm", "params": {"prompt": "y"}},
            {"id": "joins", "type": "llm", "params": {"prompt": "${a.x} and ${b.y}"}},
        ],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "joins"}],
    })

    incoming = [edge for edge in graph.edges if edge.target == NodeId("joins") and edge.kind == EdgeKind.DATA_FLOW]
    assert sorted((edge.source.node_id, edge.output_field or "", edge.input_name or "") for edge in incoming) == [
        ("a", "x", "prompt"),
        ("b", "y", "prompt"),
    ]


def test_top_level_list_param_ref_forms_edge_with_param_name() -> None:
    graph = build_graph({
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": "ls"}},
            {"id": "b", "type": "code", "params": {"lines": ["echo ${a.stdout}"]}},
        ],
        "edges": [{"from": "a", "to": "b"}],
    })

    assert (
        Edge(
            source=NodeId("a"),
            target=NodeId("b"),
            kind=EdgeKind.DATA_FLOW,
            output_field="stdout",
            input_name="lines",
        )
        in graph.edges
    )


def test_deep_dict_ref_attaches_to_node_never_a_same_named_child_port() -> None:
    # A depth-2 dict ref keeps its nearest key as input_name but must never
    # claim a child-input port that happens to share that key's name (the
    # `shallow` guard): on a plain node it targets the node; on a workflow
    # step with a child input named `inner` it targets the HOST.
    graph = build_graph({
        "nodes": [
            {"id": "gen", "type": "llm", "params": {"prompt": "x"}},
            {"id": "plain", "type": "code", "params": {"config": {"outer": {"inner": "${gen.response}"}}}},
        ],
        "edges": [{"from": "gen", "to": "plain"}],
    })
    assert (
        Edge(
            source=NodeId("gen"),
            target=NodeId("plain"),
            kind=EdgeKind.DATA_FLOW,
            output_field="response",
            input_name="inner",
        )
        in graph.edges
    )

    child = {"inputs": {"inner": {"type": "string"}}, "nodes": [{"id": "work", "type": "code"}]}

    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return SubWorkflowResult(ir=child, path=Path("/fake/child.pflow.md"), warnings=())

    graph = build_graph(
        {
            "nodes": [
                {"id": "gen", "type": "llm", "params": {"prompt": "x"}},
                {
                    "id": "host",
                    "type": "workflow",
                    "params": {"workflow": "child", "config": {"outer": {"inner": "${gen.response}"}}},
                },
            ],
            "edges": [{"from": "gen", "to": "host"}],
        },
        resolve_child=resolver,
        max_depth=2,
    )
    deep_edges = [
        edge
        for edge in graph.edges
        if edge.source == NodeId("gen") and edge.kind == EdgeKind.DATA_FLOW and edge.input_name == "inner"
    ]
    assert [edge.target for edge in deep_edges] == [NodeId("host")]


def test_dynamic_batch_over_input_with_opaque_bindings_keeps_input_edge() -> None:
    # An expanded dynamic batch over `${docs}` whose bindings are opaque
    # (`inputs: ${item}`) has no other emitter for the input→batch dependency.
    child = {"inputs": {"text": {"type": "string"}}, "nodes": [{"id": "work", "type": "code"}]}

    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return SubWorkflowResult(ir=child, path=Path("/fake/child.pflow.md"), warnings=())

    graph = build_graph(
        {
            "inputs": {"docs": {"type": "array"}},
            "nodes": [
                {
                    "id": "proc",
                    "type": "workflow",
                    "params": {"workflow": "child", "inputs": "${item}"},
                    "batch": {"items": "${docs}"},
                }
            ],
        },
        resolve_child=resolver,
        max_depth=2,
    )

    assert Edge(source=_input_id("docs"), target=NodeId("proc"), kind=EdgeKind.DATA_FLOW) in graph.edges


def test_batch_alias_ref_in_plain_param_forms_no_edge() -> None:
    # `${item.text}` in a plain param of a batched node is the per-item alias —
    # the items-source edge is drawn by the batch arm, never duplicated here.
    graph = build_graph({
        "nodes": [
            {"id": "prep", "type": "code", "params": {"code": "result = {'rows': []}"}},
            {
                "id": "fan",
                "type": "shell",
                "params": {"command": "echo ${item.text}"},
                "batch": {"items": "${prep.rows}"},
            },
        ],
        "edges": [{"from": "prep", "to": "fan"}],
    })

    assert not any(edge.kind == EdgeKind.DATA_FLOW and edge.input_name == "command" for edge in graph.edges)
    # the items-source dependency itself is still there (the batch arm)
    assert any(
        edge.kind == EdgeKind.DATA_FLOW and edge.source == NodeId("prep") and edge.target == NodeId("fan")
        for edge in graph.edges
    )


def test_cache_chunk_consumed_by_two_nodes_forms_edge_per_consumer() -> None:
    # A chunk's ref is FORBIDDEN in the consumer's prompt body, so the cache
    # edge is the only visibility this dependency can have.
    graph = build_graph({
        "cache": {"items": [{"name": "ctx", "var": "extract.response"}]},
        "nodes": [
            {"id": "extract", "type": "llm", "params": {"prompt": "extract"}},
            {"id": "a", "type": "llm", "params": {"prompt": "x"}, "prompt_cache": ["ctx"]},
            {"id": "b", "type": "llm", "params": {"prompt": "y"}, "prompt_cache": ["ctx"]},
        ],
        "edges": [{"from": "extract", "to": "a"}, {"from": "a", "to": "b"}],
    })

    cache_edges = [edge for edge in graph.edges if edge.input_name == "prompt_cache"]
    assert sorted((edge.source.node_id, edge.target.node_id) for edge in cache_edges) == [
        ("extract", "a"),
        ("extract", "b"),
    ]
    assert all(edge.kind == EdgeKind.DATA_FLOW and edge.output_field == "response" for edge in cache_edges)


def test_input_rooted_cache_chunk_draws_edge_from_input_node() -> None:
    graph = build_graph({
        "inputs": {"article": {"type": "string"}},
        "cache": {"items": [{"name": "doc", "var": "article"}]},
        "nodes": [
            {"id": "summarize", "type": "llm", "params": {"prompt": "go"}, "prompt_cache": ["doc"]},
        ],
    })

    assert (
        Edge(
            source=_input_id("article"),
            target=NodeId("summarize"),
            kind=EdgeKind.DATA_FLOW,
            input_name="prompt_cache",
        )
        in graph.edges
    )


def test_sub_path_cache_chunk_var_keeps_output_path() -> None:
    graph = build_graph({
        "cache": {"items": [{"name": "ok-part", "var": "gen.result.ok"}]},
        "nodes": [
            {"id": "gen", "type": "code", "params": {"code": "result = {'ok': 1}"}},
            {"id": "use", "type": "llm", "params": {"prompt": "x"}, "prompt_cache": ["ok-part"]},
        ],
        "edges": [{"from": "gen", "to": "use"}],
    })

    edge = next(e for e in graph.edges if e.input_name == "prompt_cache")
    assert edge.source == NodeId("gen")
    assert edge.output_field == "result"
    assert edge.output_path == ("ok",)


def test_cache_edges_only_for_listed_chunks() -> None:
    # Subset consumption: edges only for listed chunks; an unconsumed chunk
    # draws nothing; a producer listing its own chunk draws nothing (self-skip).
    graph = build_graph({
        "cache": {
            "items": [
                {"name": "one", "var": "p1.stdout"},
                {"name": "two", "var": "p2.stdout"},
            ]
        },
        "nodes": [
            {"id": "p1", "type": "shell", "params": {"command": "a"}},
            {"id": "p2", "type": "shell", "params": {"command": "b"}, "prompt_cache": ["two"]},
            {"id": "use", "type": "llm", "params": {"prompt": "x"}, "prompt_cache": ["one"]},
        ],
        "edges": [{"from": "p1", "to": "p2"}, {"from": "p2", "to": "use"}],
    })

    cache_edges = [edge for edge in graph.edges if edge.input_name == "prompt_cache"]
    assert [(edge.source.node_id, edge.target.node_id) for edge in cache_edges] == [("p1", "use")]


def test_sub_workflow_cache_resolves_level_locally() -> None:
    # `## Cache` is strictly per-file: a child's chunks resolve against the
    # child's own scope, never the parent's.
    child = {
        "cache": {"items": [{"name": "ctx", "var": "inner-gen.response"}]},
        "nodes": [
            {"id": "inner-gen", "type": "llm", "params": {"prompt": "x"}},
            {"id": "inner-use", "type": "llm", "params": {"prompt": "y"}, "prompt_cache": ["ctx"]},
        ],
        "edges": [{"from": "inner-gen", "to": "inner-use"}],
    }

    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return SubWorkflowResult(ir=child, path=Path("/fake/child.pflow.md"), warnings=())

    graph = build_graph(
        {"nodes": [{"id": "host", "type": "workflow", "params": {"workflow": "child"}}]},
        resolve_child=resolver,
        max_depth=2,
    )

    step = AncestorStep("host")
    assert (
        Edge(
            source=NodeId("inner-gen", (step,)),
            target=NodeId("inner-use", (step,)),
            kind=EdgeKind.DATA_FLOW,
            output_field="response",
            input_name="prompt_cache",
        )
        in graph.edges
    )


def test_malformed_cache_shapes_emit_nothing() -> None:
    # build_graph assumes pre-validated IR; the validator owns cache.* errors —
    # malformed shapes must not crash and must not draw edges.
    malformed_irs = [
        {"cache": [], "nodes": [{"id": "n", "type": "llm", "params": {}, "prompt_cache": ["x"]}]},
        {"cache": {"items": "nope"}, "nodes": [{"id": "n", "type": "llm", "params": {}, "prompt_cache": ["x"]}]},
        {
            "cache": {"items": [{"name": "x"}]},  # item missing var
            "nodes": [{"id": "n", "type": "llm", "params": {}, "prompt_cache": ["x"]}],
        },
        {
            "cache": {"items": [{"name": "x", "var": "gen.response"}]},
            "nodes": [
                {"id": "gen", "type": "llm", "params": {}},
                {"id": "n", "type": "llm", "params": {}, "prompt_cache": "x"},  # not a list
            ],
        },
    ]
    for ir in malformed_irs:
        graph = build_graph(ir)
        assert not any(edge.input_name == "prompt_cache" for edge in graph.edges)


def test_multi_chunk_cache_example_draws_all_producer_consumer_edges() -> None:
    # Real subject: three shell producers, two LLM consumers listing all three.
    ir = _parse("examples/core/prompt-caching-multi-chunk.pflow.md")
    graph = build_graph(ir)

    cache_edges = [edge for edge in graph.edges if edge.input_name == "prompt_cache"]
    producers = {"system_prompt", "knowledge_ref", "session_context"}
    consumers = {"summarize", "translate"}
    assert {(edge.source.node_id, edge.target.node_id) for edge in cache_edges} == {
        (producer, consumer) for producer in producers for consumer in consumers
    }


def test_cached_prefix_assembles_prose_and_vars_in_declaration_order() -> None:
    # Node.cached_prefix mirrors the runtime's block assembly over the authored
    # template (build_cache_system_blocks: prose_before + value, declaration
    # order, consumed chunks only): the user reads the prompt as the model will.
    ir = _parse("examples/core/prompt-caching-multi-chunk.pflow.md")
    graph = build_graph(ir)

    chunks = {item["name"]: item for item in ir["cache"]["items"]}
    expected = "".join(
        chunks[name]["prose_before"] + "${" + chunks[name]["var"] + "}"
        for name in ("system_prompt", "knowledge_ref", "session_context")
    )
    assert _node(graph, NodeId("summarize")).cached_prefix == expected
    assert _node(graph, NodeId("translate")).cached_prefix == expected
    # producers consume nothing
    assert _node(graph, NodeId("system_prompt")).cached_prefix is None


def test_cached_prefix_includes_only_consumed_chunks() -> None:
    graph = build_graph({
        "cache": {
            "items": [
                {"name": "one", "var": "p1.stdout", "prose_before": "First:\n"},
                {"name": "two", "var": "p2.stdout", "prose_before": "\n\nSecond:\n"},
            ]
        },
        "nodes": [
            {"id": "p1", "type": "shell", "params": {"command": "a"}},
            {"id": "p2", "type": "shell", "params": {"command": "b"}},
            {"id": "use", "type": "llm", "params": {"prompt": "x"}, "prompt_cache": ["two"]},
        ],
        "edges": [{"from": "p1", "to": "p2"}, {"from": "p2", "to": "use"}],
    })

    assert _node(graph, NodeId("use")).cached_prefix == "\n\nSecond:\n${p2.stdout}"


def test_literal_operands_form_no_edges_and_coalesce_forms_two() -> None:
    graph = build_graph({
        "nodes": [
            {"id": "gen", "type": "llm", "params": {"prompt": "x"}},
            {"id": "alt", "type": "llm", "params": {"prompt": "y"}},
            {
                "id": "consume",
                "type": "code",
                "params": {"a": "${5}", "b": '${"x"}', "c": "${true}", "d": "${gen.x ?? alt.y}"},
            },
        ],
        "edges": [{"from": "gen", "to": "alt"}, {"from": "alt", "to": "consume"}],
    })

    incoming = [edge for edge in graph.edges if edge.target == NodeId("consume") and edge.kind == EdgeKind.DATA_FLOW]
    assert all(edge.input_name == "d" for edge in incoming)
    assert sorted((edge.source.node_id, edge.output_field or "") for edge in incoming) == [
        ("alt", "y"),
        ("gen", "x"),
    ]


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


def test_build_graph_tolerates_null_params_via_public_api() -> None:
    # build_graph is a public function called directly with hand-built IR; a node may
    # carry `params: None`. The data-flow input path and the literal-batch construction
    # path must both tolerate it without raising AttributeError on `params.get(...)`.
    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return SubWorkflowResult(
            ir={"inputs": {"text": {"type": "string"}}, "nodes": [{"id": "inner", "type": "code"}]},
            path=Path("/fake/child.pflow.md"),
            warnings=(),
        )

    graph = build_graph(
        {
            "nodes": [
                {"id": "a", "type": "code", "params": None},
                {"id": "b", "type": "workflow", "params": None, "batch": {"items": [{"workflow": "./child.pflow.md"}]}},
            ],
            "edges": [{"from": "a", "to": "b"}],
        },
        resolve_child=resolver,
        max_depth=2,
    )

    assert graph.node(NodeId("a")) is not None
    assert graph.node(NodeId("b")) is not None


def _batch_container(graph: GraphModel, host: NodeId) -> Container:
    container = next(c for c in graph.containers if c.kind == "batch" and c.host == host)
    return container


def test_literal_batch_unexpandable_items_record_reason_on_container() -> None:
    # A failed sub-workflow batch item must be distinguishable from a genuine leaf item
    # (the "no information loss" bar): record WHY each item did not expand, mirroring the
    # Node.unexpanded discriminator the regular/dynamic expansion paths set.
    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        if params.get("workflow") == "./good.pflow.md":
            return SubWorkflowResult(
                ir={"nodes": [{"id": "inner", "type": "code"}]}, path=Path("/fake/good.pflow.md"), warnings=()
            )
        return None  # ./missing.pflow.md -> unresolved

    parent = {
        "nodes": [
            {
                "id": "reviews",
                "type": "workflow",
                "params": {},
                "batch": {
                    "items": [
                        {"workflow": "./good.pflow.md"},
                        {"workflow": "./missing.pflow.md"},
                        {"workflow": "${chosen}"},
                        {"name": "genuine-leaf"},
                    ]
                },
            }
        ]
    }

    graph = build_graph(parent, resolve_child=resolver, max_depth=2)
    unexpanded = _batch_container(graph, NodeId("reviews")).annotations.get("unexpanded_items", {})
    assert unexpanded.get(1) == "unresolved"
    assert unexpanded.get(2) == "dynamic_path"
    assert 0 not in unexpanded  # good item expanded
    assert 3 not in unexpanded  # genuine leaf item is not a failed expansion
    json.dumps(unexpanded)  # JSON-able

    # Depth limit on the same items records depth_limit for every sub-workflow item.
    capped = build_graph(parent, resolve_child=resolver, max_depth=0)
    capped_unexpanded = _batch_container(capped, NodeId("reviews")).annotations.get("unexpanded_items", {})
    assert capped_unexpanded.get(0) == "depth_limit"
    assert capped_unexpanded.get(1) == "depth_limit"


def test_literal_batch_item_cycle_records_reason_and_leaves_no_empty_container() -> None:
    # A literal batch item that re-enters a workflow already on the recursion stack must
    # be marked "cycle" WITHOUT leaving an empty workflow container behind (the cycle
    # check now runs before the container is created, matching the other expansion paths).
    rec_ir = {
        "nodes": [
            {"id": "again", "type": "workflow", "params": {}, "batch": {"items": [{"workflow": "./rec.pflow.md"}]}}
        ]
    }

    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return SubWorkflowResult(ir=rec_ir, path=Path("/fake/rec.pflow.md"), warnings=())

    graph = build_graph(
        {
            "nodes": [
                {
                    "id": "reviews",
                    "type": "workflow",
                    "params": {},
                    "batch": {"items": [{"workflow": "./rec.pflow.md"}]},
                }
            ]
        },
        resolve_child=resolver,
        max_depth=10,
    )

    inner_host = NodeId("again", (AncestorStep("reviews", 0),))
    inner_batch = _batch_container(graph, inner_host)
    assert inner_batch.annotations.get("unexpanded_items", {}).get(0) == "cycle"
    # The cycled item left no empty workflow container under the inner batch.
    empty = [
        c
        for c in graph.containers
        if c.kind == "workflow" and c.host is None and c.parent == inner_batch.id and not c.members
    ]
    assert empty == []


def test_batch_alias_takes_precedence_over_same_named_top_level_input() -> None:
    # `as: data` colliding with a top-level input named `data`: an item binding's
    # `${data.field}` must resolve to the batch source (prep.rows), NOT the input node.
    child = {"inputs": {"text": {"type": "string"}}, "nodes": [{"id": "work", "type": "code"}]}

    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return SubWorkflowResult(ir=child, path=Path("/fake/child.pflow.md"), warnings=())

    graph = build_graph(
        {
            "inputs": {"data": {"type": "array"}},
            "nodes": [
                {"id": "prep", "type": "code"},
                {
                    "id": "process",
                    "type": "workflow",
                    "params": {"workflow": "child", "inputs": {"text": "${data.field}"}},
                    "batch": {"items": "${prep.rows}", "as": "data"},
                },
            ],
            "edges": [{"from": "prep", "to": "process"}],
        },
        resolve_child=resolver,
        max_depth=2,
    )

    target = _input_id("text", AncestorStep("process", None))
    assert (
        Edge(source=NodeId("prep"), target=target, kind=EdgeKind.DATA_FLOW, output_field="rows", input_name="text")
        in graph.edges
    )
    # The same-named top-level input must NOT also draw a (spurious) edge into the child input.
    assert not any(
        edge.target == target and edge.source == _input_id("data") and edge.kind == EdgeKind.DATA_FLOW
        for edge in graph.edges
    )


def test_refs_with_path_in_extracts_full_dotted_tail() -> None:
    """The path-preserving extractor; refs_in stays byte-identical via the shared walk."""
    from pflow.core.workflow.graph.scope import refs_in, refs_with_path_in

    assert refs_with_path_in("${a.b.c.d}") == [("a", "b", ("c", "d"))]
    assert refs_with_path_in("${a.b}") == [("a", "b", ())]
    assert refs_with_path_in("${a}") == [("a", None, ())]
    assert refs_with_path_in("${a.b.c ?? x.y}") == [("a", "b", ("c",)), ("x", "y", ())]
    assert refs_with_path_in('${missing ?? "literal"}') == [("missing", None, ())]
    # Runtime parity: an escaped template resolves to literal `${x}` and a
    # spaced operand never resolves — neither is a ref (the grammar gate).
    assert refs_with_path_in("$${escaped}") == []
    assert refs_with_path_in("${ spaced }") == []
    # the (root, field) view is the same walk truncated — cannot drift
    assert refs_in("${a.b.c.d} and ${e}") == [("a", "b"), ("e", None)]


def test_data_flow_edges_carry_output_path_below_the_resolved_port() -> None:
    """A sub-key ref keeps its sub-path on the edge; wholesale/input refs carry none."""
    child = {
        "inputs": {
            "ok": {"type": "boolean"},
            "deep": {"type": "string"},
            "whole": {"type": "object"},
        },
        "nodes": [{"id": "work", "type": "code"}],
    }

    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return SubWorkflowResult(ir=child, path=Path("/fake/child.pflow.md"), warnings=())

    graph = build_graph(
        {
            "inputs": {"input_x": {"type": "object"}},
            "nodes": [
                {"id": "gen", "type": "code", "params": {"code": "result = compute('${input_x.y}')"}},
                {
                    "id": "check",
                    "type": "workflow",
                    "params": {
                        "workflow": "child",
                        "inputs": {
                            "ok": "${gen.result.ok}",
                            "deep": "${gen.result.a.b}",
                            "whole": "${gen.result}",
                        },
                    },
                },
            ],
            "edges": [{"from": "gen", "to": "check"}],
            "outputs": {
                "summary": {"source": "${gen.result.text}"},
                # An output source reading BELOW a workflow input: resolves to the
                # input node with output_field=None, so the equality guard must
                # keep the tail off (an input node has no "y" port to land on).
                "echoed": {"source": "${input_x.y.z}"},
            },
        },
        resolve_child=resolver,
        max_depth=2,
    )

    def data_edge_into(target: NodeId) -> Edge:
        matches = [e for e in graph.edges if e.target == target and e.kind == EdgeKind.DATA_FLOW]
        assert len(matches) == 1, f"expected one data edge into {target}"
        return matches[0]

    step = AncestorStep("check", None)
    sub_key = data_edge_into(_input_id("ok", step))
    assert (sub_key.output_field, sub_key.output_path) == ("result", ("ok",))
    two_deep = data_edge_into(_input_id("deep", step))
    assert (two_deep.output_field, two_deep.output_path) == ("result", ("a", "b"))
    wholesale = data_edge_into(_input_id("whole", step))
    assert (wholesale.output_field, wholesale.output_path) == ("result", ())
    # site 2 (output source:) carries the tail too
    source_edge = data_edge_into(_output_id("summary"))
    assert (source_edge.output_field, source_edge.output_path) == ("result", ("text",))
    # site 2's equality guard: an input-rooted deep ref resolves with
    # output_field=None, so the tail must NOT attach (mutation-tested gap W1 —
    # without the guard this edge would carry ("z",) toward a port-less node)
    deep_input_edge = data_edge_into(_output_id("echoed"))
    assert (deep_input_edge.output_field, deep_input_edge.output_path) == (None, ())
    # site 3 (workflow input -> consumer) has no output port, hence no sub-path
    input_edge = next(e for e in graph.edges if e.source == _input_id("input_x") and e.kind == EdgeKind.DATA_FLOW)
    assert input_edge.output_path == ()


def test_batch_alias_ref_never_carries_an_output_path() -> None:
    """The explicit alias guard: `${data.rows.x}` under `as: data` over
    `items: ${prep.rows}` has first segment "rows" == the batch source's
    output_field — the equality rule ALONE would attach ("x",) to an edge whose
    source is prep, describing the wrong node. The alias guard keeps it ()."""
    child = {"inputs": {"text": {"type": "string"}}, "nodes": [{"id": "work", "type": "code"}]}

    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return SubWorkflowResult(ir=child, path=Path("/fake/child.pflow.md"), warnings=())

    graph = build_graph(
        {
            "nodes": [
                {"id": "prep", "type": "code"},
                {
                    "id": "process",
                    "type": "workflow",
                    "params": {"workflow": "child", "inputs": {"text": "${data.rows.x}"}},
                    "batch": {"items": "${prep.rows}", "as": "data"},
                },
            ],
            "edges": [{"from": "prep", "to": "process"}],
        },
        resolve_child=resolver,
        max_depth=2,
    )

    target = _input_id("text", AncestorStep("process", None))
    edge = next(e for e in graph.edges if e.target == target and e.source == NodeId("prep"))
    assert edge.output_field == "rows"
    assert edge.output_path == ()


def test_two_subkey_refs_in_one_binding_dedupe_to_one_edge_first_path_wins() -> None:
    """``Edge.output_path`` is ``compare=False`` — LOAD-BEARING, mutation-checked.

    Edge dedup is full dataclass equality, so two sub-key refs of the SAME field
    inside ONE binding (``"${gen.result.ok} ${gen.result.no}"``) must collapse to
    ONE DATA_FLOW edge whose ``output_path`` is the FIRST ref's ``("ok",)`` — the
    same documented lossiness as ``input_name``'s multi-role case. Removing
    ``compare=False`` puts the paths into identity: this test then sees TWO edges
    and fails (verified by mutation) — exactly the "cleanup" regression that
    would silently change Mermaid's edge count on multi-sub-key workflows.
    """
    child = {"inputs": {"ok": {"type": "string"}}, "nodes": [{"id": "work", "type": "code"}]}

    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        return SubWorkflowResult(ir=child, path=Path("/fake/child.pflow.md"), warnings=())

    graph = build_graph(
        {
            "nodes": [
                {"id": "gen", "type": "code", "params": {"code": 'result = {"ok": 1, "no": 2}'}},
                {
                    "id": "check",
                    "type": "workflow",
                    "params": {"workflow": "child", "inputs": {"ok": "${gen.result.ok} ${gen.result.no}"}},
                },
            ],
            "edges": [{"from": "gen", "to": "check"}],
        },
        resolve_child=resolver,
        max_depth=2,
    )

    target = _input_id("ok", AncestorStep("check", None))
    edges = [e for e in graph.edges if e.target == target and e.kind == EdgeKind.DATA_FLOW]
    assert len(edges) == 1
    assert (edges[0].output_field, edges[0].output_path) == ("result", ("ok",))


def test_leaf_dynamic_batch_records_sibling_items_source_data_flow() -> None:
    # A leaf (non-workflow) batch over a sibling-produced items source must carry the
    # prep->host dependency in the model — workflow batches already do; leaf batches
    # used to drop it (only top-level-input sources were resolved).
    graph = build_graph({
        "nodes": [
            {"id": "prep", "type": "code"},
            {
                "id": "summarize",
                "type": "shell",
                "params": {"command": "echo ${item}"},
                "batch": {"items": "${prep.rows}"},
            },
        ],
        "edges": [{"from": "prep", "to": "summarize"}],
    })

    assert (
        Edge(source=NodeId("prep"), target=NodeId("summarize"), kind=EdgeKind.DATA_FLOW, output_field="rows")
        in graph.edges
    )
