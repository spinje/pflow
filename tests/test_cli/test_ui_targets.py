"""Pure target-address resolution for ``pflow ui`` Point commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pflow.core.workflow.graph import build_graph, render_react_flow
from pflow.core.workflow.graph.renderers.react_flow import (
    RFEdge,
    RFGraph,
    RFGroup,
    RFNode,
    RFRef,
)
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult
from pflow.ui.targets import address_for_target, resolve_target


def _ref(
    node_id: str,
    *ancestors: tuple[str, int | None],
    port: str | None = None,
) -> RFRef:
    return RFRef(
        node_id=node_id,
        ancestor_path=[{"node_id": host, "batch_index": index} for host, index in ancestors],
        port=port,
    )


def _node(flat_id: str, ref: RFRef, *, group_host: bool = False) -> RFNode:
    return RFNode(
        id=flat_id,
        ref=ref,
        kind="shell",
        purpose="",
        params=[],
        io=None,
        loop=None,
        batch=None,
        parent=None,
        source=None,
        is_decision=False,
        is_terminal=False,
        is_group_host=group_host,
        is_transform=False,
        output_shape=None,
        cached_prefix=None,
        unexpanded=None,
        annotations={},
    )


def _graph(
    nodes: list[RFNode],
    *,
    edges: list[RFEdge] | None = None,
    groups: list[RFGroup] | None = None,
) -> RFGraph:
    return RFGraph(nodes=nodes, edges=edges or [], groups=groups or [])


def _child_resolver(children: dict[str, dict[str, Any]]):
    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        reference = params.get("workflow")
        child = children.get(reference)
        return SubWorkflowResult(child, Path(f"/fake/{reference}.pflow.md"), ()) if child is not None else None

    return resolver


def test_resolves_flat_node_and_container_host_to_structural_ref() -> None:
    host = _node("n0", _ref("research"), group_host=True)
    graph = _graph(
        [host],
        groups=[RFGroup("g0", "workflow", None, "n0", [], 0, {})],
    )

    resolution = resolve_target(graph, "research")

    assert resolution.matched == 1
    assert resolution.address == "research"
    assert resolution.descriptor == {
        "kind": "node",
        "ref": {"node_id": "research", "ancestor_path": [], "port": None},
    }


def test_duplicate_nested_node_reports_round_trippable_qualified_addresses() -> None:
    graph = _graph([
        _node("n0", _ref("gen", ("create", None))),
        _node("n1", _ref("gen", ("remix", None))),
    ])

    resolution = resolve_target(graph, "gen")

    assert resolution.matched == 2
    assert resolution.qualify == ("create.gen", "remix.gen")
    assert all(resolve_target(graph, address).matched == 1 for address in resolution.qualify)


def test_literal_batch_index_is_part_of_qualified_address() -> None:
    graph = _graph([
        _node("n0", _ref("gen", ("fanout", 0))),
        _node("n1", _ref("gen", ("fanout", 1))),
    ])

    resolution = resolve_target(graph, "gen")

    assert resolution.qualify == ("fanout[0].gen", "fanout[1].gen")
    assert all(resolve_target(graph, address).matched == 1 for address in resolution.qualify)


def test_real_nested_render_preserves_scope_qualification() -> None:
    child = {"nodes": [{"id": "gen", "type": "shell"}]}
    model = build_graph(
        {
            "nodes": [
                {"id": "create", "type": "workflow", "params": {"workflow": "child"}},
                {"id": "remix", "type": "workflow", "params": {"workflow": "child"}},
            ]
        },
        resolve_child=_child_resolver({"child": child}),
        max_depth=2,
    )

    resolution = resolve_target(render_react_flow(model), "gen")

    assert resolution.qualify == ("create.gen", "remix.gen")
    assert all(resolve_target(render_react_flow(model), address).matched == 1 for address in resolution.qualify)


def test_real_truncated_batch_exposes_only_rendered_representatives() -> None:
    child = {"nodes": [{"id": "gen", "type": "shell"}]}
    model = build_graph(
        {
            "nodes": [
                {
                    "id": "fanout",
                    "type": "workflow",
                    "params": {"workflow": "child"},
                    "batch": {"items": [{"workflow": "child"} for _ in range(6)]},
                }
            ]
        },
        resolve_child=_child_resolver({"child": child}),
        max_depth=2,
    )

    resolution = resolve_target(render_react_flow(model), "gen")

    assert resolution.qualify == ("fanout[0].gen", "fanout[1].gen")


def test_input_and_output_ports_with_same_name_are_distinct() -> None:
    graph = _graph([
        _node("n0", _ref("data", port="in")),
        _node("n1", _ref("data", port="out")),
    ])

    incoming = resolve_target(graph, "in:data")
    outgoing = resolve_target(graph, "out:data")

    assert incoming.matched == outgoing.matched == 1
    assert incoming.descriptor is not None
    assert outgoing.descriptor is not None
    assert incoming.descriptor["ref"]["port"] == "in"
    assert outgoing.descriptor["ref"]["port"] == "out"


def test_resolves_data_edge_by_original_structural_endpoints() -> None:
    source = _node("n0", _ref("gen"))
    target = _node("n1", _ref("summarize"))
    graph = _graph(
        [source, target],
        edges=[
            RFEdge(
                id="e0",
                source="n0",
                target="n1",
                kind="data_flow",
                label=None,
                output_field="response",
                input_name="prompt",
                shadowed=False,
                output_path=["text"],
            )
        ],
    )

    resolution = resolve_target(graph, "gen.response.text->summarize.prompt")

    assert resolution.matched == 1
    assert resolution.address == "gen.response.text -> summarize.prompt"
    assert resolution.descriptor == {
        "kind": "edge",
        "source": {"node_id": "gen", "ancestor_path": [], "port": None},
        "source_field": "response",
        "source_path": ["text"],
        "target": {"node_id": "summarize", "ancestor_path": [], "port": None},
        "input_name": "prompt",
    }


def test_ambiguous_edge_qualifiers_also_round_trip() -> None:
    nodes = [
        _node("n0", _ref("gen", ("left", None))),
        _node("n1", _ref("sink", ("left", None))),
        _node("n2", _ref("gen", ("right", None))),
        _node("n3", _ref("sink", ("right", None))),
    ]
    graph = _graph(
        nodes,
        edges=[
            RFEdge("e0", "n0", "n1", "data_flow", None, "stdout", "text", False),
            RFEdge("e1", "n2", "n3", "data_flow", None, "stdout", "text", False),
        ],
    )

    resolution = resolve_target(graph, "gen.stdout -> sink.text")

    assert resolution.matched == 2
    assert resolution.qualify == (
        "left.gen.stdout -> left.sink.text",
        "right.gen.stdout -> right.sink.text",
    )
    assert all(resolve_target(graph, address).matched == 1 for address in resolution.qualify)


def test_not_found_uses_fuzzy_node_suggestions() -> None:
    graph = _graph([_node("n0", _ref("fetch-data")), _node("n1", _ref("summarize"))])

    resolution = resolve_target(graph, "fetchdata")

    assert resolution.matched == 0
    assert resolution.suggestions[0] == "fetch-data"


def test_io_port_resolves_by_its_bare_name_without_a_prefix() -> None:
    """An agent points at an input by the name it reads under ``## Inputs`` — the
    `in:`/`out:` prefix is never required when nothing collides."""
    graph = _graph([_node("n0", _ref("source_file", port="in"))])

    resolution = resolve_target(graph, "source_file")

    assert resolution.matched == 1
    assert resolution.descriptor is not None
    assert resolution.descriptor["ref"]["port"] == "in"
    # The canonical address keeps the prefix so the report stays unambiguous,
    # even though the bare name is what the agent typed.
    assert resolution.address == "in:source_file"


def test_same_name_input_and_output_qualify_to_the_prefixed_forms() -> None:
    """The one case the prefix exists for: a bare name that is genuinely two
    elements returns a qualify list that teaches `in:`/`out:` exactly when needed."""
    graph = _graph([
        _node("n0", _ref("data", port="in")),
        _node("n1", _ref("data", port="out")),
    ])

    resolution = resolve_target(graph, "data")

    assert resolution.matched == 2
    assert resolution.qualify == ("in:data", "out:data")
    assert all(resolve_target(graph, address).matched == 1 for address in resolution.qualify)


def test_edge_resolves_when_its_source_is_an_io_port_named_bare() -> None:
    """A connection from a workflow input composes from the input's bare name —
    `source_file -> read_source.file_path` resolves with no prefix."""
    source = _node("n0", _ref("source_file", port="in"))
    target = _node("n1", _ref("read_source"))
    graph = _graph(
        [source, target],
        edges=[RFEdge("e0", "n0", "n1", "data_flow", None, None, "file_path", False)],
    )

    resolution = resolve_target(graph, "source_file -> read_source.file_path")

    assert resolution.matched == 1
    assert resolution.address == "in:source_file -> read_source.file_path"


def test_not_found_input_typo_suggests_input_names_not_unrelated_steps() -> None:
    graph = _graph([_node("n0", _ref("source_file", port="in")), _node("n1", _ref("read_source"))])

    resolution = resolve_target(graph, "source_fil")

    assert resolution.matched == 0
    assert "source_file" in resolution.suggestions


def test_not_found_edge_attempt_suggests_real_connections() -> None:
    source = _node("n0", _ref("gen"))
    target = _node("n1", _ref("summarize"))
    graph = _graph(
        [source, target],
        edges=[RFEdge("e0", "n0", "n1", "data_flow", None, "response", "prompt", False)],
    )

    resolution = resolve_target(graph, "gen.response -> summarize.promt")

    assert resolution.matched == 0
    assert resolution.suggestions[0] == "gen.response -> summarize.prompt"


def test_display_grammar_matches_resolver_and_round_trips() -> None:
    """`address_for_target` (the CLI Watch display formatter) and `resolve_target`
    share ONE grammar — an address `pflow ui user-activity` prints re-points to
    exactly one element. Guards the two-source-of-truth drift the plan warned
    about (the Watch display path used to re-implement the grammar in ui.py)."""
    graph = _graph(
        [
            _node("n0", _ref("gen", ("create", 0))),
            _node("n1", _ref("summarize", ("create", 0))),
            _node("n2", _ref("data", port="in")),
        ],
        edges=[RFEdge("e0", "n0", "n1", "data_flow", None, "result", "prompt", False, output_path=["ok"])],
    )

    for probe in ("gen", "in:data", "gen.result.ok -> summarize.prompt"):
        resolution = resolve_target(graph, probe)
        assert resolution.matched == 1, probe
        assert resolution.descriptor is not None
        # The CLI renders the recorded descriptor via the SAME formatter; it must
        # equal the resolver's canonical address and itself re-point to one element.
        rendered = address_for_target(resolution.descriptor)
        assert rendered == resolution.address
        assert resolve_target(graph, rendered).matched == 1
