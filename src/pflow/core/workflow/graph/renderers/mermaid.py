"""Render GraphModel as Mermaid flowchart syntax."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pflow.core.workflow.graph.model import (
    AncestorStep,
    BatchSpec,
    Container,
    Edge,
    EdgeKind,
    GraphModel,
    LoopSpec,
    Node,
    NodeId,
)
from pflow.core.workflow.graph.scope import refs_in

_SHAPE_MAP: dict[str, tuple[str, str, str]] = {
    "llm": ("([", "])", "llm"),
    "shell": ("[[", "]]", "shell"),
    "write-file": ("[(", ")]", "writefile"),
    "code": ("[", "]", "code"),
    "workflow": ("(", ")", "workflow"),
}

_LABEL_KEYS = ("name", "label", "focus", "lens")
_SKIP_KEYS = ("workflow", "prompt", "command", "model")

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

_SUBGRAPH_OPACITIES = [0.07, 0.14, 0.21, 0.28]
_STRUCTURAL_KINDS = {EdgeKind.SEQUENTIAL, EdgeKind.BRANCH, EdgeKind.ERROR}


def render_mermaid(graph: GraphModel, *, direction: str = "LR", descriptions: bool = False) -> str:
    """Render a workflow graph model as Mermaid flowchart source."""
    renderer = _MermaidRenderer(graph=graph, descriptions=descriptions)
    return renderer.render(direction)


@dataclass
class _RenderMaps:
    fork_join: dict[str, list[str]] = field(default_factory=dict)
    outgoing: dict[str, dict[str, str]] = field(default_factory=dict)
    incoming: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class _MermaidRenderer:
    graph: GraphModel
    descriptions: bool
    lines: list[str] = field(default_factory=list)
    rendered_nodes: set[NodeId] = field(default_factory=set)
    maps: _RenderMaps = field(default_factory=_RenderMaps)

    def __post_init__(self) -> None:
        self.nodes_by_id = {node.id: node for node in self.graph.nodes}
        self.containers_by_id = {container.id: container for container in self.graph.containers}
        self.children_by_parent: dict[str | None, list[Container]] = {}
        for container in self.graph.containers:
            self.children_by_parent.setdefault(container.parent, []).append(container)
        self.workflow_by_host = {
            container.host: container
            for container in self.graph.containers
            if container.kind == "workflow" and container.host is not None
        }
        self.batch_by_host = {
            container.host: container
            for container in self.graph.containers
            if container.kind == "batch" and container.host is not None
        }
        self._flat: dict[NodeId, str] = {}
        self._assign_flat_ids()
        self._build_render_maps()

    def render(self, direction: str) -> str:
        self.lines = [f"graph {direction}"]
        self._render_classdefs()
        top_inputs = self._io_container(parent=None, kind="input_wrapper")
        if top_inputs is not None:
            self._render_wrapped_inputs(top_inputs, mode="top", indent="    ")
        self._render_level(ancestor_path=(), parent_container=None, indent="    ", suppress_io=False)
        return "\n".join(self.lines) + "\n"

    def _render_level(
        self,
        *,
        ancestor_path: tuple[AncestorStep, ...],
        parent_container: str | None,
        indent: str,
        suppress_io: bool,
    ) -> None:
        if parent_container is not None and not suppress_io:
            input_container = self._io_container(parent=parent_container, kind="input_wrapper")
            if input_container is not None:
                self._render_internal_inputs(input_container, indent)

        output_container = self._io_container(parent=parent_container, kind="output_wrapper")
        for node in self._level_body_nodes(ancestor_path, parent_container):
            self._render_body_node(node, indent)

        if parent_container is None:
            self._render_data_flow_edges(
                self._top_input_consumer_targets(),
                indent,
                source_kinds={"input"},
                target_kinds_exclude={"output"},
            )

        output_ids: list[str] = []
        if parent_container is None and output_container is not None:
            output_ids = self._render_wrapped_outputs(output_container, mode="top", indent=indent)
        elif not suppress_io and output_container is not None:
            output_ids = self._render_internal_outputs(output_container, indent)

        self._render_end_nodes_and_edges(
            ancestor_path=ancestor_path,
            parent_container=parent_container,
            output_ids=output_ids,
            indent=indent,
            suppress_io=suppress_io,
        )

    def _render_body_node(self, node: Node, indent: str) -> None:
        if node.batch is not None and not node.batch.dynamic:
            self._render_literal_batch(node, indent)
            return

        workflow_container = self.workflow_by_host.get(node.id)
        if workflow_container is not None and node.unexpanded is None:
            self._render_expanded_workflow_node(node, workflow_container, indent)
            return

        self._render_regular_node(node, indent)

    def _render_expanded_workflow_node(self, node: Node, container: Container, indent: str) -> None:
        input_container = self._io_container(parent=container.id, kind="input_wrapper")
        if input_container is not None:
            self._render_wrapped_inputs(input_container, mode="external", indent=indent, host=node)

        mermaid_id = self._node_mermaid_id(node.id)
        subgraph_label = self._subgraph_host_label(node)
        self.lines.append(f'{indent}subgraph {mermaid_id} ["{subgraph_label}"]')
        self.rendered_nodes.add(node.id)
        self._render_level(
            ancestor_path=(*node.id.ancestor_path, AncestorStep(node.id.node_id)),
            parent_container=container.id,
            indent=indent + "    ",
            suppress_io=True,
        )
        self.lines.append(f"{indent}end")
        self.lines.append(f"{indent}{_subgraph_style(mermaid_id, container.nesting_depth)}")

        output_container = self._io_container(parent=container.id, kind="output_wrapper")
        if output_container is not None:
            self._render_wrapped_outputs(output_container, mode="external", indent=indent, host=node)
        if input_container is not None:
            self._render_data_flow_edges(
                set(input_container.members),
                indent,
                exclude_top_level_input_sources=True,
            )

    def _render_literal_batch(self, node: Node, indent: str) -> None:
        batch = node.batch
        if batch is None:
            return

        mermaid_id = self._node_mermaid_id(node.id)
        parallel = "parallel " if batch.parallel else ""
        count = _batch_count(batch)
        subgraph_label = _escape_label(f"{node.id.node_id} ({parallel}x{count})")
        self.lines.append(f'{indent}subgraph {mermaid_id} ["{subgraph_label}"]')
        self.rendered_nodes.add(node.id)

        inner_indent = indent + "    "
        shape_open, shape_close, css_class = _node_shape(node, is_decision=False)
        for index in self._visible_batch_indexes(batch):
            item = (batch.items or [])[index]
            item_container = self._batch_item_container(node.id, index)
            item_label = _get_item_label(item, index)
            item_mermaid_id = self._batch_item_mermaid_id(node.id, index)
            if item_container is not None:
                self._render_batch_item_workflow(item_label, item_mermaid_id, item_container, inner_indent)
                continue
            display_label = _escape_label(f"{item_label} ({_format_node_type(node.kind)})")
            self.lines.append(
                f'{inner_indent}{item_mermaid_id}{shape_open}"{display_label}"{shape_close}:::{css_class}'
            )

        if self._has_hidden_batch_items(batch):
            dots_id = self._batch_dots_mermaid_id(node.id)
            dots_label = f"... x{count}"
            self.lines.append(f'{inner_indent}{dots_id}@{{ shape: procs, label: "{_escape_label(dots_label)}" }}')
            self.lines.append(f"{inner_indent}style {dots_id} {_classdef_to_style(css_class)}")

        self.lines.append(f"{indent}end")
        batch_container = self.batch_by_host.get(node.id)
        depth = batch_container.nesting_depth if batch_container is not None else len(node.id.ancestor_path) + 1
        self.lines.append(f"{indent}{_subgraph_style(mermaid_id, depth)}")

        targets: set[NodeId] = set()
        for index in self._visible_batch_indexes(batch):
            item_container = self._batch_item_container(node.id, index)
            input_container = (
                self._io_container(parent=item_container.id, kind="input_wrapper") if item_container else None
            )
            if input_container is not None:
                targets.update(input_container.members)
        self._render_data_flow_edges(targets, indent, source_kinds_exclude={"input"})

    def _render_batch_item_workflow(
        self, item_label: str, item_mermaid_id: str, container: Container, indent: str
    ) -> None:
        subgraph_label = _escape_label(f"{item_label} (workflow)")
        self.lines.append(f'{indent}subgraph {item_mermaid_id} ["{subgraph_label}"]')
        for member in container.members:
            self.rendered_nodes.add(member)
        member_path = self._container_level_path(container)
        self._render_level(
            ancestor_path=member_path,
            parent_container=container.id,
            indent=indent,
            suppress_io=False,
        )
        self.lines.append(f"{indent}end")
        self.lines.append(f"{indent}{_subgraph_style(item_mermaid_id, container.nesting_depth)}")

    def _render_regular_node(self, node: Node, indent: str) -> None:
        mermaid_id = self._node_mermaid_id(node.id)
        batch_suffix = _dynamic_batch_label(node.batch)
        label = _format_label(node, self.graph.is_decision(node.id), self.descriptions, batch_suffix)
        if batch_suffix:
            self.lines.append(f'{indent}{mermaid_id}@{{ shape: procs, label: "{label}" }}')
            _, _, css_class = _node_shape(node, self.graph.is_decision(node.id))
            self.lines.append(f"{indent}style {mermaid_id} {_classdef_to_style(css_class)}")
        else:
            shape_open, shape_close, css_class = _node_shape(node, self.graph.is_decision(node.id))
            self.lines.append(f'{indent}{mermaid_id}{shape_open}"{label}"{shape_close}:::{css_class}')
        self.rendered_nodes.add(node.id)
        if node.loop is not None:
            self.lines.append(f'{indent}{mermaid_id} -.->|"⟳"| {mermaid_id}')

    def _render_wrapped_inputs(
        self,
        container: Container,
        *,
        mode: str,
        indent: str,
        host: Node | None = None,
    ) -> None:
        if mode == "top":
            wrapper_id = "workflow-inputs"
            wrapper_label = "workflow inputs"
        else:
            if host is None:
                return
            wrapper_id = f"{self._node_mermaid_id(host.id)}-in"
            wrapper_label = f"{host.id.node_id} inputs"

        self.lines.append(f'{indent}subgraph {wrapper_id} ["{_escape_label(wrapper_label)}"]')
        inner_indent = indent + "    "
        for member in container.members:
            node = self.nodes_by_id[member]
            self._render_input_node(node, inner_indent, include_required=mode == "top")
        self.lines.append(f"{indent}end")
        self.lines.append(f"{indent}style {wrapper_id} fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4")
        if mode == "external":
            self._render_input_start_edges(container, indent)

    def _render_internal_inputs(self, container: Container, indent: str) -> None:
        for member in container.members:
            self._render_input_node(self.nodes_by_id[member], indent, include_required=False)
        self._render_input_start_edges(container, indent)

    def _render_input_node(self, node: Node, indent: str, *, include_required: bool) -> None:
        input_type = node.io.data_type if node.io is not None and node.io.data_type else ""
        if include_required:
            required = ", required" if node.io is not None and node.io.required else ""
            label = _escape_label(f"{node.id.node_id} ({input_type}{required})")
        else:
            label = _escape_label(f"{node.id.node_id} ({input_type})" if input_type else node.id.node_id)
        self.lines.append(f'{indent}{self._node_mermaid_id(node.id)}[/"{label}"/]:::input')
        self.rendered_nodes.add(node.id)

    def _render_input_start_edges(self, container: Container, indent: str) -> None:
        start_id = self._start_node_for_inputs(container)
        if start_id is None:
            return
        start_mid = self._node_mermaid_id(start_id)
        for member in container.members:
            self.lines.append(f"{indent}{self._node_mermaid_id(member)} --> {start_mid}")

    def _render_wrapped_outputs(
        self,
        container: Container,
        *,
        mode: str,
        indent: str,
        host: Node | None = None,
    ) -> list[str]:
        if mode == "top":
            wrapper_id = "workflow-outputs"
            wrapper_label = "workflow outputs"
        else:
            if host is None:
                return []
            wrapper_id = f"{self._node_mermaid_id(host.id)}-out"
            wrapper_label = f"{host.id.node_id} outputs"

        self.lines.append(f'{indent}subgraph {wrapper_id} ["{_escape_label(wrapper_label)}"]')
        inner_indent = indent + "    "
        output_ids = [self._render_output_node(self.nodes_by_id[member], inner_indent) for member in container.members]
        self.lines.append(f"{indent}end")
        self.lines.append(f"{indent}style {wrapper_id} fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4")
        self._render_data_flow_edges(set(container.members), indent)
        return output_ids

    def _render_internal_outputs(self, container: Container, indent: str) -> list[str]:
        output_ids = []
        for member in container.members:
            output_ids.append(self._render_output_node(self.nodes_by_id[member], indent))
            self._render_data_flow_edges({member}, indent)
        return output_ids

    def _render_output_node(self, node: Node, indent: str) -> str:
        mermaid_id = self._node_mermaid_id(node.id)
        self.lines.append(f'{indent}{mermaid_id}(["{_escape_label(node.id.node_id)}"]):::output')
        self.rendered_nodes.add(node.id)
        return mermaid_id

    def _render_data_flow_edges(
        self,
        targets: set[NodeId],
        indent: str,
        *,
        source_kinds: set[str] | None = None,
        source_kinds_exclude: set[str] | None = None,
        target_kinds_exclude: set[str] | None = None,
        exclude_top_level_input_sources: bool = False,
    ) -> None:
        if not targets:
            return
        for edge in self.graph.edges:
            if edge.kind != EdgeKind.DATA_FLOW or edge.target not in targets:
                continue
            source = self.nodes_by_id[edge.source]
            target = self.nodes_by_id[edge.target]
            if source_kinds is not None and source.kind not in source_kinds:
                continue
            if source_kinds_exclude is not None and source.kind in source_kinds_exclude:
                continue
            if exclude_top_level_input_sources and source.kind == "input" and source.id.ancestor_path == ():
                continue
            if target_kinds_exclude is not None and target.kind in target_kinds_exclude:
                continue
            if edge.source not in self.rendered_nodes or edge.target not in self.rendered_nodes:
                continue
            self.lines.append(f"{indent}{self._node_mermaid_id(edge.source)} --> {self._node_mermaid_id(edge.target)}")

    def _render_end_nodes_and_edges(
        self,
        *,
        ancestor_path: tuple[AncestorStep, ...],
        parent_container: str | None,
        output_ids: list[str],
        indent: str,
        suppress_io: bool,
    ) -> None:
        body_nodes = self._level_body_nodes(ancestor_path, parent_container)
        end_edges = self._level_end_edges(ancestor_path)
        terminals = self._terminal_end_sink_nodes(body_nodes, output_ids=output_ids, suppress_io=suppress_io)
        if end_edges or terminals:
            self.lines.append(f'{indent}{self._level_prefix(ancestor_path)}pflow_end(("end"))')

        for edge in self._level_structural_edges(ancestor_path):
            if self._edge_shadowed_for_render(edge):
                continue
            arrow = _edge_arrow(edge)
            for source_id, target_id in self._resolve_edge_endpoints(edge):
                self.lines.append(f"{indent}{source_id}{arrow}{target_id}")

        if end_edges or terminals:
            end_id = f"{self._level_prefix(ancestor_path)}pflow_end"
            for source_ids in self._end_sink_source_ids(end_edges, terminals):
                for source_id in source_ids:
                    self.lines.append(f"{indent}{source_id} --> {end_id}")

    def _terminal_end_sink_nodes(
        self, body_nodes: list[Node], *, output_ids: list[str], suppress_io: bool
    ) -> list[Node]:
        if output_ids or suppress_io:
            return []
        if not any(self.graph.is_decision(node.id) for node in body_nodes):
            return []
        return [node for node in body_nodes if self.graph.is_terminal(node.id)]

    def _end_sink_source_ids(self, end_edges: list[Edge], terminals: list[Node]) -> list[list[str]]:
        end_sources: dict[NodeId, list[str]] = {}
        for edge in end_edges:
            end_sources[edge.source] = self._resolve_end_edge_sources(edge)
        for node in sorted(terminals, key=lambda item: item.id.node_id):
            if node.id in end_sources:
                continue
            end_sources[node.id] = self.maps.fork_join.get(
                self._node_mermaid_id(node.id), [self._node_mermaid_id(node.id)]
            )
        return [end_sources[source] for source in sorted(end_sources, key=self._node_mermaid_id)]

    def _edge_shadowed_for_render(self, edge: Edge) -> bool:
        if self._has_direct_data_flow(edge):
            return False
        target = self.nodes_by_id[edge.target]
        if target.batch is None or target.batch.dynamic:
            return self.graph.shadowed(edge)
        source_id = self._node_mermaid_id(edge.source)
        if source_id in self.maps.outgoing:
            return False
        fork_targets = self.maps.fork_join.get(self._node_mermaid_id(edge.target))
        if not fork_targets:
            return self.graph.shadowed(edge)
        covered = self._render_data_flow_batch_targets(edge.target)
        return bool(covered) and all(target_id in covered for target_id in fork_targets)

    def _has_direct_data_flow(self, edge: Edge) -> bool:
        return any(
            candidate.kind == EdgeKind.DATA_FLOW and candidate.source == edge.source and candidate.target == edge.target
            for candidate in self.graph.edges
        )

    def _render_data_flow_batch_targets(self, batch_host: NodeId) -> set[str]:
        covered: set[str] = set()
        for edge in self.graph.edges:
            if edge.kind != EdgeKind.DATA_FLOW:
                continue
            target = edge.target
            if not _is_batch_item_descendant(target, batch_host):
                continue
            item_index = _batch_index_for(target, batch_host)
            if item_index is not None:
                covered.add(self._batch_item_mermaid_id(batch_host, item_index))
        return covered

    def _resolve_edge_endpoints(self, edge: Edge) -> list[tuple[str, str]]:
        source_id = self._node_mermaid_id(edge.source)
        target_id = self._node_mermaid_id(edge.target)
        out_dict = self.maps.outgoing.get(source_id)
        in_dict = self.maps.incoming.get(target_id)

        if out_dict and in_dict:
            pairs = [(out_mid, in_dict[name]) for name, out_mid in out_dict.items() if name in in_dict]
            return pairs or [(source_id, target_id)]
        if out_dict:
            target_ids = self.maps.fork_join.get(target_id, [target_id])
            return [(out_mid, tid) for out_mid in out_dict.values() for tid in target_ids]

        source_ids = self.maps.fork_join.get(source_id, [source_id])
        target_ids = self.maps.fork_join.get(target_id, [target_id])
        result: list[tuple[str, str]] = []
        for fid in source_ids:
            fid_out = self.maps.outgoing.get(fid)
            if fid_out:
                for out_mid in fid_out.values():
                    result.extend((out_mid, tid) for tid in target_ids)
            else:
                result.extend((fid, tid) for tid in target_ids)
        return result

    def _build_render_maps(self) -> None:
        for container in self.graph.containers:
            if container.host is not None and container.kind == "workflow":
                host_id = self._node_mermaid_id(container.host)
                self.maps.incoming[host_id] = self._io_members_by_name(container.id, "input_wrapper")
                outputs = self._io_members_by_name(container.id, "output_wrapper")
                if outputs:
                    self.maps.outgoing[host_id] = outputs

        for node in self.graph.nodes:
            if node.batch is None or node.batch.dynamic:
                continue
            host_id = self._node_mermaid_id(node.id)
            self.maps.fork_join[host_id] = self._batch_render_ids(node)
            for index in self._visible_batch_indexes(node.batch):
                item_container = self._batch_item_container(node.id, index)
                if item_container is None:
                    continue
                item_id = self._batch_item_mermaid_id(node.id, index)
                outputs = self._io_members_by_name(item_container.id, "output_wrapper")
                if outputs:
                    self.maps.outgoing[item_id] = outputs

    def _io_members_by_name(self, parent: str, kind: str) -> dict[str, str]:
        container = self._io_container(parent=parent, kind=kind)
        if container is None:
            return {}
        return {member.node_id: self._node_mermaid_id(member) for member in container.members}

    def _level_body_nodes(self, ancestor_path: tuple[AncestorStep, ...], parent_container: str | None) -> list[Node]:
        if parent_container is not None:
            members = self.containers_by_id[parent_container].members
            return [
                self.nodes_by_id[member]
                for member in members
                if self.nodes_by_id[member].kind not in {"input", "output", "end"}
            ]
        return [
            node
            for node in self.graph.nodes
            if node.id.ancestor_path == ancestor_path
            and node.parent is None
            and node.kind not in {"input", "output", "end"}
        ]

    def _level_structural_edges(self, ancestor_path: tuple[AncestorStep, ...]) -> list[Edge]:
        return [
            edge
            for edge in self.graph.edges
            if edge.kind in _STRUCTURAL_KINDS
            and edge.source.ancestor_path == ancestor_path
            and edge.target.ancestor_path == ancestor_path
        ]

    def _level_end_edges(self, ancestor_path: tuple[AncestorStep, ...]) -> list[Edge]:
        return [
            edge
            for edge in self.graph.edges
            if edge.kind == EdgeKind.END
            and edge.source.ancestor_path == ancestor_path
            and edge.target.ancestor_path == ancestor_path
        ]

    def _resolve_end_edge_sources(self, edge: Edge) -> list[str]:
        if edge.source not in self.rendered_nodes:
            return []
        source_id = self._node_mermaid_id(edge.source)
        return self.maps.fork_join.get(source_id, [source_id])

    def _io_container(self, *, parent: str | None, kind: str) -> Container | None:
        for container in self.children_by_parent.get(parent, []):
            if container.kind == kind:
                return container
        return None

    def _top_input_consumer_targets(self) -> set[NodeId]:
        return {
            edge.target
            for edge in self.graph.edges
            if edge.kind == EdgeKind.DATA_FLOW
            and self.nodes_by_id[edge.source].kind == "input"
            and edge.source.ancestor_path == ()
        }

    def _start_node_for_inputs(self, container: Container) -> NodeId | None:
        raw_start = container.annotations.get("start_node")
        ancestor_path = self._container_level_path(container)
        if isinstance(raw_start, str):
            candidate = NodeId(raw_start, ancestor_path)
            if candidate in self.nodes_by_id:
                return candidate
        parent = container.parent
        if parent is None:
            return None
        body_nodes = self._level_body_nodes(ancestor_path, parent)
        return body_nodes[0].id if body_nodes else None

    def _container_level_path(self, container: Container) -> tuple[AncestorStep, ...]:
        if container.members:
            return container.members[0].ancestor_path
        if container.host is not None:
            return (*container.host.ancestor_path, AncestorStep(container.host.node_id))
        return ()

    def _batch_render_ids(self, node: Node) -> list[str]:
        batch = node.batch
        if batch is None:
            return []
        ids = [self._batch_item_mermaid_id(node.id, index) for index in self._visible_batch_indexes(batch)]
        if self._has_hidden_batch_items(batch):
            ids.append(self._batch_dots_mermaid_id(node.id))
        return ids

    def _visible_batch_indexes(self, batch: BatchSpec) -> range:
        count = _batch_count(batch)
        return range(count if count <= 4 else min(count, 2))

    def _has_hidden_batch_items(self, batch: BatchSpec) -> bool:
        count = _batch_count(batch)
        return count > 4

    def _batch_item_container(self, host: NodeId, index: int) -> Container | None:
        batch_container = self.batch_by_host.get(host)
        if batch_container is None:
            return None
        item_path = (*host.ancestor_path, AncestorStep(host.node_id, index))
        for container in self.children_by_parent.get(batch_container.id, []):
            if container.kind != "workflow" or container.host is not None:
                continue
            if self._container_level_path(container) == item_path:
                return container
        return None

    def _batch_item_mermaid_id(self, host: NodeId, index: int) -> str:
        return f"{self._node_mermaid_id(host)}__{_to_mermaid_id(self._batch_item_label(host, index))}"

    def _batch_dots_mermaid_id(self, host: NodeId) -> str:
        return f"{self._node_mermaid_id(host)}__dots"

    def _batch_item_label(self, host: NodeId, index: int) -> str:
        node = self.nodes_by_id[host]
        items = node.batch.items if node.batch is not None and node.batch.items is not None else []
        item = items[index] if index < len(items) else None
        return _get_item_label(item, index)

    def _subgraph_host_label(self, node: Node) -> str:
        batch_suffix = _dynamic_batch_label(node.batch)
        if batch_suffix:
            label = _escape_label(node.id.node_id) + batch_suffix
        else:
            label = _escape_label(f"{node.id.node_id} ({node.kind})")
        if node.loop is not None:
            label += _loop_label(node.loop, node.id.node_id)
        if self.descriptions and node.purpose:
            label += f"<br/>{_escape_label(_first_sentence(node.purpose))}"
        return label

    def _node_mermaid_id(self, node_id: NodeId) -> str:
        resolved = self._flat.get(node_id)
        return resolved if resolved is not None else self._natural_node_id(node_id)

    def _natural_node_id(self, node_id: NodeId) -> str:
        if node_id.node_id == "__end__":
            return f"{self._level_prefix(node_id.ancestor_path)}__end__"
        node = self.nodes_by_id[node_id]
        display_path = node_id.ancestor_path
        prefix = self._level_prefix(display_path)
        if node.kind == "input":
            return f"input_{node_id.node_id}" if not display_path else f"{prefix}in_{node_id.node_id}"
        if node.kind == "output":
            return f"out_{node_id.node_id}" if not display_path else f"{prefix}out_{node_id.node_id}"
        return f"{prefix}{_to_mermaid_id(node_id.node_id)}"

    def _assign_flat_ids(self) -> None:
        """Assign a unique flat Mermaid id to every node.

        The flat-id scheme (``parent__child``, ``input_x``, ``pflow_end`` …) shares
        one string namespace, so an authored node id can collide with another node's
        derived id or with a synthetic id (the ``pflow_end`` sink, batch ``dots`` /
        item-box ids) that is not a model node. We compute ids shallow-to-deep so an
        ancestor's resolved id (carrying any disambiguating suffix) feeds its
        descendants' prefixes, reserve the synthetic ids up front, and append a
        numeric suffix to genuine collisions. With no collisions this reproduces the
        legacy ids byte-for-byte; suffixes only appear for pathological names.
        """
        used: set[str] = {"pflow_end", "workflow-inputs", "workflow-outputs"}

        def sort_key(node: Node) -> tuple[int, str, int, tuple[tuple[str, int], ...]]:
            path = tuple((s.node_id, -1 if s.batch_index is None else s.batch_index) for s in node.id.ancestor_path)
            # port_rank gives input/output ports that share a name + level a deterministic
            # order (their natural ids differ by in_/out_ prefix, so no suffixing results).
            port_rank = {None: 0, "in": 1, "out": 2}[node.id.port]
            return (len(node.id.ancestor_path), node.id.node_id, port_rank, path)

        # Pre-reserve synthetic ids (sink, wrappers, dots, item boxes) from NATURAL host
        # prefixes before assigning any node, so a shallower node cannot squat on a deeper
        # level's synthetic id — the assignment loop runs shallow-to-deep and would otherwise
        # reserve a deep sink only after a colliding top-level node already took it.
        for node in self.graph.nodes:
            self._reserve_synthetic_ids(node, self._natural_node_id(node.id), used)

        for node in sorted(self.graph.nodes, key=sort_key):
            natural = self._natural_node_id(node.id)
            chosen = natural
            k = 2
            while chosen in used:
                chosen = f"{natural}_{k}"
                k += 1
            self._flat[node.id] = chosen
            used.add(chosen)
            # Re-reserve from the resolved (possibly suffixed) id so a suffixed host's
            # descendants and synthetic ids stay collision-free.
            self._reserve_synthetic_ids(node, chosen, used)

    def _reserve_synthetic_ids(self, node: Node, chosen: str, used: set[str]) -> None:
        if node.id in self.workflow_by_host:
            used.add(f"{chosen}__pflow_end")
            # External IO-wrapper subgraph ids for an expanded sub-workflow node.
            used.add(f"{chosen}-in")
            used.add(f"{chosen}-out")
        if node.batch is not None and not node.batch.dynamic:
            used.add(f"{chosen}__dots")
            for index in self._visible_batch_indexes(node.batch):
                label = _to_mermaid_id(self._batch_item_label(node.id, index))
                used.add(f"{chosen}__{label}")
                used.add(f"{chosen}__{label}__pflow_end")

    def _level_prefix(self, ancestor_path: tuple[AncestorStep, ...]) -> str:
        if not ancestor_path:
            return ""
        last = ancestor_path[-1]
        host = NodeId(last.node_id, ancestor_path[:-1])
        base = self._flat.get(host)
        if base is None:
            return self._natural_level_prefix(ancestor_path)
        if last.batch_index is not None:
            base = f"{base}__{_to_mermaid_id(self._batch_item_label(host, last.batch_index))}"
        return base + "__"

    def _natural_level_prefix(self, ancestor_path: tuple[AncestorStep, ...]) -> str:
        parts: list[str] = []
        path_so_far: tuple[AncestorStep, ...] = ()
        for step in ancestor_path:
            parts.append(_to_mermaid_id(step.node_id))
            if step.batch_index is not None:
                host = NodeId(step.node_id, path_so_far)
                parts.append(_to_mermaid_id(self._batch_item_label(host, step.batch_index)))
            path_so_far = (*path_so_far, step)
        return "__".join(parts) + "__" if parts else ""

    def _render_classdefs(self) -> None:
        for name, style in _CLASSDEF_STYLES.items():
            self.lines.append(f"    classDef {name} {style}")


def _to_mermaid_id(node_id: str) -> str:
    return node_id


def _escape_label(text: str) -> str:
    return text.replace('"', "&quot;").replace("|", "&#124;")


def _node_shape(node: Node, is_decision: bool) -> tuple[str, str, str]:
    if is_decision:
        return ("{", "}", "decision")
    if node.kind.startswith("mcp"):
        return ("{{", "}}", "mcp")
    return _SHAPE_MAP.get(node.kind, ("[", "]", "code"))


def _format_node_type(node_type: str) -> str:
    if node_type.startswith("mcp-"):
        return f"mcp:<br/>{node_type[4:]}"
    return node_type


def _format_label(node: Node, is_decision: bool, descriptions: bool, batch_suffix: str = "") -> str:
    display_type = _format_node_type(node.kind)
    label = _escape_label(f"{node.id.node_id} ({display_type})")
    if node.loop is not None:
        label += _loop_label(node.loop, node.id.node_id)
    if descriptions and node.purpose:
        label += f"<br/>{_escape_label(_first_sentence(node.purpose))}"
    if batch_suffix:
        label += f"<br/>{batch_suffix}"
    return label


def _first_sentence(text: str) -> str:
    # Neutralize template refs first so a description like `${max_iterations}` does not
    # leak ${...} into the label (and truncation never severs a ${ ... } mid-brace).
    clean = re.sub(r"\$\{([^}]*)\}", r"\1", text)
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)
    clean = re.sub(r"\*(.+?)\*", r"\1", clean)
    match = re.match(r"([^.!?]+[.!?])", clean)
    if match:
        return match.group(1)[:80]
    return clean[:80]


def _classdef_to_style(css_class: str) -> str:
    return _CLASSDEF_STYLES.get(css_class, _CLASSDEF_STYLES["code"])


def _subgraph_style(mermaid_id: str, depth: int) -> str:
    opacity = _SUBGRAPH_OPACITIES[min(depth, len(_SUBGRAPH_OPACITIES) - 1)]
    return f"style {mermaid_id} fill:#808080,fill-opacity:{opacity},stroke:#999"


def _batch_count(batch: BatchSpec) -> int:
    return batch.count if batch.count is not None else len(batch.items or [])


def _get_item_label(item: Any, index: int) -> str:
    if not isinstance(item, dict):
        return f"#{index + 1}"
    for key in _LABEL_KEYS:
        val = item.get(key)
        if isinstance(val, str):
            return val
    for key, val in item.items():
        if key in _SKIP_KEYS:
            continue
        if isinstance(val, str) and len(val) <= 30:
            return val
    return f"#{index + 1}"


def _dynamic_batch_label(batch: BatchSpec | None) -> str:
    if batch is None or not batch.dynamic or not batch.source_ref:
        return ""
    refs = refs_in(batch.source_ref)
    source_name = refs[0][0] if refs else "N"
    parallel_prefix = "parallel " if batch.parallel else ""
    return f" ({parallel_prefix}x|{source_name}|)"


def _strip_template(ref: Any) -> str:
    if not isinstance(ref, str):
        return ""
    value = ref.strip()
    if value.startswith("${") and value.endswith("}"):
        return value[2:-1].strip()
    return value


def _loop_label(loop: LoopSpec, node_id: str) -> str:
    cond = _strip_template(loop.condition)
    if cond.startswith(f"{node_id}."):
        cond = cond[len(node_id) + 1 :]
    badge = f"⟳ {loop.polarity} {cond}".rstrip()
    if isinstance(loop.cap, int) and not isinstance(loop.cap, bool):
        badge += f" · ≤ {loop.cap}"
    elif isinstance(loop.cap, str) and loop.cap.strip():
        badge += f" · ≤ {_strip_template(loop.cap)}"
    if loop.carry:
        badge += f" · carry {', '.join(loop.carry)}"
    return f"<br/>{_escape_label(badge)}"


def _edge_arrow(edge: Edge) -> str:
    if edge.kind == EdgeKind.ERROR:
        return " -.->|error| "
    if edge.kind == EdgeKind.BRANCH and edge.label is not None:
        return f" -->|{_escape_label(edge.label)}| "
    return " --> "


def _is_batch_item_descendant(candidate: NodeId, batch_host: NodeId) -> bool:
    return _batch_index_for(candidate, batch_host) is not None


def _batch_index_for(candidate: NodeId, batch_host: NodeId) -> int | None:
    path = candidate.ancestor_path
    if len(path) <= len(batch_host.ancestor_path):
        return None
    if path[: len(batch_host.ancestor_path)] != batch_host.ancestor_path:
        return None
    step = path[len(batch_host.ancestor_path)]
    if step.node_id != batch_host.node_id:
        return None
    return step.batch_index
