"""Renderer-agnostic workflow graph model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


@dataclass(frozen=True)
class AncestorStep:
    """One structural descent from a host node into a child workflow body."""

    node_id: str
    batch_index: int | None = None


@dataclass(frozen=True)
class NodeId:
    """Runtime-aligned node identity.

    Top-level and sub-workflow child nodes keep their authored ``node_id``.
    Nesting is represented by ``ancestor_path``, which is the chain of *real*
    host descents only. Literal batch sub-workflow items use
    ``AncestorStep.batch_index``; dynamic batches use ``None`` because the static
    model has one representative body. Looped nodes remain one static identity;
    a future runtime overlay joins N loop visits to this one node with event
    sequence data, not by changing the static identity.

    ``port`` disambiguates synthetic IO-wrapper nodes, which may share a name
    with each other (an input and output both named ``changelog_file``) or with
    a body node at the same level. It is the role, not an ancestor — keeping it
    off ``ancestor_path`` preserves the real-descents-only invariant. Body nodes
    (the only runtime-trace join targets) always carry ``port=None``, so the
    runtime overlay join is unaffected.
    """

    node_id: str
    ancestor_path: tuple[AncestorStep, ...] = ()
    port: Literal["in", "out"] | None = None


@dataclass(frozen=True)
class LoopSpec:
    polarity: Literal["while", "until"]
    condition: str
    cap: int | str | None
    carry: dict[str, str]


@dataclass(frozen=True)
class BatchSpec:
    parallel: bool
    dynamic: bool
    as_name: str = "item"
    source_ref: str | None = None
    count: int | None = None
    items: list[Any] | None = None


@dataclass(frozen=True)
class IOPort:
    data_type: str | None
    required: bool = False
    # The authored `default:` value verbatim; None when absent (an authored
    # `default: null` is indistinguishable — accepted, it's pathological).
    default: Any = None


@dataclass(frozen=True)
class SourceRef:
    file: str | None
    line: int | None


UnexpandedReason = Literal["depth_limit", "unresolved", "dynamic_path", "cycle"]
NodeKind = str


@dataclass
class Node:
    id: NodeId
    kind: NodeKind
    purpose: str = ""
    parent: str | None = None
    loop: LoopSpec | None = None
    batch: BatchSpec | None = None
    io: IOPort | None = None
    source: SourceRef | None = None
    param_sources: dict[str, SourceRef] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    unexpanded: UnexpandedReason | None = None
    annotations: dict[str, Any] = field(default_factory=dict)


class EdgeKind(str, Enum):
    SEQUENTIAL = "sequential"
    BRANCH = "branch"
    ERROR = "error"
    DATA_FLOW = "data_flow"
    END = "end"


@dataclass(frozen=True)
class Edge:
    source: NodeId
    target: NodeId
    kind: EdgeKind
    label: str | None = None
    output_field: str | None = None
    input_name: str | None = None
    # The ref's sub-path BELOW output_field: ``${gen.result.ok}`` carries
    # ("ok",). ``compare=False`` is LOAD-BEARING, not an optimization: edge
    # dedup is full dataclass equality (build.py `if edge not in self.edges`).
    # In identity, two same-input_name sub-key refs would become two edges and
    # change Mermaid's edge count (goldens break). Out of identity, dedup is
    # byte-identical to before this field; the accepted lossiness (the first
    # ref's path wins in that rare shape) is exactly the documented
    # `input_name` multi-role precedent.
    output_path: tuple[str, ...] = field(default=(), compare=False)


ContainerKind = Literal["workflow", "batch", "input_wrapper", "output_wrapper"]


@dataclass
class Container:
    id: str
    kind: ContainerKind
    nesting_depth: int
    host: NodeId | None = None
    parent: str | None = None
    members: list[NodeId] = field(default_factory=list)
    annotations: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphModel:
    nodes: list[Node]
    edges: list[Edge]
    containers: list[Container]

    def __post_init__(self) -> None:
        # Internal construction invariants (build_graph is the sole constructor). A
        # violation is a builder bug, never user input, so these raise plain ValueError
        # rather than a PflowError subclass — they never reach the user-facing diagnostic
        # pipeline that PflowError exists to feed.
        self._assert_unique_ids()
        self._assert_referential_integrity()
        self._assert_parent_member_consistency()

    def node(self, n: NodeId) -> Node | None:
        for node in self.nodes:
            if node.id == n:
                return node
        return None

    def is_decision(self, n: NodeId) -> bool:
        # A decision has >= 2 distinct routing OUTCOMES: the BRANCH labels plus the
        # reserved "end" route when one exists. A dynamic `next` arm to "end" becomes
        # an END edge, never a BRANCH — so a continue-or-stop decider (1 branch label
        # + an END route, e.g. `if ok: next="end" else: next="fix"`) is a decision.
        # No branch labels at all (a static `- next: end`, or every arm -> "end")
        # means single-outcome routing, not a decision.
        labels = {edge.label for edge in self.edges if edge.source == n and edge.kind == EdgeKind.BRANCH}
        if not labels:
            return False
        if len(labels) >= 2:
            return True
        return any(edge.source == n and edge.kind == EdgeKind.END for edge in self.edges)

    def is_terminal(self, n: NodeId) -> bool:
        # A node is terminal when it has no forward control-flow successor. ERROR and END
        # edges are excluded (an error handler / authored `next: end` route is still a sink).
        # DATA_FLOW edges DO count: a node that feeds data downstream is not a structural
        # sink. The Mermaid end-sink only fires when a level has no declared outputs, where
        # such data-flow out-edges do not arise — do not "simplify" this to exclude
        # DATA_FLOW, or the `handle-error --> pflow_end` parity sink can silently change.
        return not any(edge.source == n and edge.kind not in (EdgeKind.ERROR, EdgeKind.END) for edge in self.edges)

    def shadowed(self, e: Edge) -> bool:
        """Return whether a structural edge is covered by data-flow edges.

        Mirrors the legacy renderer's three-clause suppression rule:
        structural edges are shadowed only when the source has no expanded
        outputs, and data-flow edges from that same source cover either the
        direct target or every expanded batch-item target.
        """
        if e.kind not in (EdgeKind.SEQUENTIAL, EdgeKind.BRANCH, EdgeKind.ERROR):
            return False
        if self._has_expanded_outputs(e.source):
            return False

        data_flow_targets = {
            edge.target for edge in self.edges if edge.kind == EdgeKind.DATA_FLOW and edge.source == e.source
        }
        if e.target in data_flow_targets:
            return True

        expanded_input_members = self._expanded_input_members(e.target)
        if expanded_input_members and any(member in data_flow_targets for member in expanded_input_members):
            return True

        item_members = self._batch_item_members(e.target)
        return bool(item_members) and all(member in data_flow_targets for member in item_members)

    def _assert_unique_ids(self) -> None:
        seen_nodes: set[NodeId] = set()
        for node in self.nodes:
            if node.id in seen_nodes:
                raise ValueError(f"Duplicate graph node id: {node.id}")
            seen_nodes.add(node.id)

        seen_containers: set[str] = set()
        for container in self.containers:
            if container.id in seen_containers:
                raise ValueError(f"Duplicate graph container id: {container.id}")
            seen_containers.add(container.id)

    def _assert_referential_integrity(self) -> None:
        node_ids = {node.id for node in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids:
                raise ValueError(f"Edge source does not resolve to a node: {edge.source}")
            if edge.target not in node_ids:
                raise ValueError(f"Edge target does not resolve to a node: {edge.target}")
        for container in self.containers:
            if container.host is not None and container.host not in node_ids:
                raise ValueError(f"Container host does not resolve to a node: {container.host}")
            for member in container.members:
                if member not in node_ids:
                    raise ValueError(f"Container member does not resolve to a node: {member}")

    def _assert_parent_member_consistency(self) -> None:
        containers_by_id = {container.id: container for container in self.containers}
        for node in self.nodes:
            if node.parent is None:
                continue
            container = containers_by_id.get(node.parent)
            if container is None:
                raise ValueError(f"Node parent does not resolve to a container: {node.parent}")
            if node.id not in container.members:
                raise ValueError(f"Node {node.id} missing from parent container {node.parent}")
        nodes_by_id = {node.id: node for node in self.nodes}
        for container in self.containers:
            for member in container.members:
                node = nodes_by_id[member]
                if node.parent != container.id:
                    raise ValueError(f"Container {container.id} member {member} has parent {node.parent}")

    def _has_expanded_outputs(self, node_id: NodeId) -> bool:
        return any(node.kind == "output" and _is_descendant_of(node.id, node_id) for node in self.nodes)

    def _batch_item_members(self, node_id: NodeId) -> set[NodeId]:
        batch_containers = [
            container for container in self.containers if container.kind == "batch" and container.host == node_id
        ]
        if not batch_containers:
            return set()

        batch_container_ids = {container.id for container in batch_containers}
        item_container_ids = {
            container.id
            for container in self.containers
            if container.kind == "workflow" and container.host is None and container.parent in batch_container_ids
        }
        nodes_by_id = {node.id: node for node in self.nodes}
        covered_members: set[NodeId] = set()
        for container in self.containers:
            if container.id not in item_container_ids:
                continue
            input_members = {member for member in container.members if nodes_by_id[member].kind == "input"}
            covered_members.update(input_members or container.members)
        return covered_members

    def _expanded_input_members(self, node_id: NodeId) -> set[NodeId]:
        workflow_containers = [
            container for container in self.containers if container.kind == "workflow" and container.host == node_id
        ]
        if not workflow_containers:
            return set()
        workflow_container_ids = {container.id for container in workflow_containers}
        input_container_ids = {
            container.id
            for container in self.containers
            if container.kind == "input_wrapper" and container.parent in workflow_container_ids
        }
        return {
            member
            for container in self.containers
            if container.id in input_container_ids
            for member in container.members
        }


def _is_descendant_of(candidate: NodeId, host: NodeId) -> bool:
    if len(candidate.ancestor_path) <= len(host.ancestor_path):
        return False
    if candidate.ancestor_path[: len(host.ancestor_path)] != host.ancestor_path:
        return False
    return candidate.ancestor_path[len(host.ancestor_path)].node_id == host.node_id
