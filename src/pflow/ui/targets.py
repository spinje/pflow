"""Resolve agent-facing Point addresses against a rendered workflow graph.

Resolution is deliberately server-side: address parsing happens once, while the
browser receives only stable structural references. Positional React Flow ids
never cross the live channel because independent renders may number them
differently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from pflow.core.suggestion_utils import find_similar_items
from pflow.core.workflow.graph.renderers.react_flow import RFGraph, RFNode, RFRef


class RefPayload(TypedDict):
    node_id: str
    ancestor_path: list[dict[str, object]]
    port: str | None


class NodeTarget(TypedDict):
    kind: Literal["node"]
    ref: RefPayload


class EdgeTarget(TypedDict):
    kind: Literal["edge"]
    source: RefPayload
    source_field: str | None
    source_path: list[str]
    target: RefPayload
    input_name: str | None


TargetDescriptor = NodeTarget | EdgeTarget


@dataclass(frozen=True)
class TargetResolution:
    """The complete, structured outcome of resolving one Point address."""

    matched: int
    descriptor: TargetDescriptor | None = None
    address: str | None = None
    qualify: tuple[str, ...] = ()
    suggestions: tuple[str, ...] = ()

    def report(self) -> dict[str, object]:
        """Return the minimal JSON response appropriate for this outcome."""
        if self.matched == 0:
            return {"matched": 0, "suggestions": list(self.suggestions)}
        if self.matched > 1:
            return {"matched": self.matched, "qualify": list(self.qualify)}
        return {"matched": 1, "address": self.address}


@dataclass(frozen=True)
class _Addressable:
    addresses: tuple[str, ...]
    qualified: str
    descriptor: TargetDescriptor


def _ref_payload(ref: RFRef) -> RefPayload:
    return {
        "node_id": ref.node_id,
        "ancestor_path": [
            {"node_id": str(step["node_id"]), "batch_index": step.get("batch_index")} for step in ref.ancestor_path
        ],
        "port": ref.port,
    }


def _format_ref(payload: RefPayload) -> str:
    """The ONE canonical scoped address for a structural ref payload.

    Shared by resolution (the qualify/address strings) AND the CLI Watch display
    (`address_for_ref` below), so an address `user-activity` prints always
    round-trips back through `resolve_target` — one grammar, no second source of
    truth to drift.
    """
    segments: list[str] = []
    for step in payload["ancestor_path"]:
        node_id = str(step["node_id"])
        batch_index = step.get("batch_index")
        segments.append(f"{node_id}[{batch_index}]" if isinstance(batch_index, int) else node_id)
    address = ".".join([*segments, payload["node_id"]])
    port = payload["port"]
    return f"{port}:{address}" if port in {"in", "out"} else address


def _format_target(descriptor: TargetDescriptor) -> str:
    """Canonical address for a well-formed target descriptor."""
    if descriptor["kind"] == "node":
        return _format_ref(descriptor["ref"])
    source = _format_ref(descriptor["source"])
    if descriptor["source_field"]:
        source += f".{descriptor['source_field']}"
    source += "".join(f".{part}" for part in descriptor["source_path"])
    destination = _format_ref(descriptor["target"])
    if descriptor["input_name"]:
        destination += f".{descriptor['input_name']}"
    return f"{source} -> {destination}"


def address_for_ref(payload: object) -> str | None:
    """Tolerant scoped address for a raw ref payload off the wire (CLI Watch).

    Same grammar as `_format_ref`, but validates an untrusted dict first so a
    malformed browser report degrades to ``None`` instead of raising.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("node_id"), str):
        return None
    steps: list[dict[str, object]] = []
    ancestors = payload.get("ancestor_path")
    if isinstance(ancestors, list):
        for step in ancestors:
            if isinstance(step, dict) and isinstance(step.get("node_id"), str):
                steps.append({"node_id": step["node_id"], "batch_index": step.get("batch_index")})
    port = payload.get("port")
    return _format_ref({
        "node_id": payload["node_id"],
        "ancestor_path": steps,
        "port": port if isinstance(port, str) else None,
    })


def address_for_target(descriptor: object) -> str | None:
    """Tolerant address for a raw target descriptor off the wire (CLI Watch)."""
    if not isinstance(descriptor, dict):
        return None
    kind = descriptor.get("kind")
    if kind == "node":
        return address_for_ref(descriptor.get("ref"))
    if kind != "edge":
        return None
    source = address_for_ref(descriptor.get("source"))
    destination = address_for_ref(descriptor.get("target"))
    if source is None or destination is None:
        return None
    field = descriptor.get("source_field")
    if isinstance(field, str):
        source += f".{field}"
    path = descriptor.get("source_path")
    if isinstance(path, list):
        source += "".join(f".{part}" for part in path if isinstance(part, str))
    input_name = descriptor.get("input_name")
    if isinstance(input_name, str):
        destination += f".{input_name}"
    return f"{source} -> {destination}"


def _node_addresses(ref: RFRef) -> tuple[str, str]:
    scoped = _format_ref(_ref_payload(ref))
    bare = f"{ref.port}:{ref.node_id}" if ref.port in {"in", "out"} else ref.node_id
    return bare, scoped


def _with_field(address: str, field: str | None, path: list[str]) -> str:
    suffix = [part for part in (field, *path) if part]
    return ".".join((address, *suffix)) if suffix else address


def _normalize_address(address: str) -> str:
    endpoints = address.split("->")
    if len(endpoints) == 2:
        return f"{endpoints[0].strip()} -> {endpoints[1].strip()}"
    return address.strip()


def _node_elements(graph: RFGraph) -> list[_Addressable]:
    elements = []
    for node in graph.nodes:
        bare, scoped = _node_addresses(node.ref)
        elements.append(
            _Addressable(
                addresses=tuple(dict.fromkeys((bare, scoped))),
                qualified=scoped,
                descriptor={"kind": "node", "ref": _ref_payload(node.ref)},
            )
        )
    return elements


def _edge_elements(graph: RFGraph, nodes_by_id: dict[str, RFNode]) -> list[_Addressable]:
    elements = []
    for edge in graph.edges:
        if edge.kind != "data_flow":
            continue
        source = nodes_by_id.get(edge.source)
        target = nodes_by_id.get(edge.target)
        if source is None or target is None:
            continue

        source_bare, source_scoped = _node_addresses(source.ref)
        target_bare, target_scoped = _node_addresses(target.ref)
        source_addresses = {
            _with_field(source_bare, edge.output_field, edge.output_path),
            _with_field(source_scoped, edge.output_field, edge.output_path),
        }
        target_addresses = {
            _with_field(target_bare, edge.input_name, []),
            _with_field(target_scoped, edge.input_name, []),
        }
        addresses = tuple(
            sorted(
                f"{source_address} -> {target_address}"
                for source_address in source_addresses
                for target_address in target_addresses
            )
        )
        descriptor: EdgeTarget = {
            "kind": "edge",
            "source": _ref_payload(source.ref),
            "source_field": edge.output_field,
            "source_path": list(edge.output_path),
            "target": _ref_payload(target.ref),
            "input_name": edge.input_name,
        }
        elements.append(
            _Addressable(
                addresses=addresses,
                qualified=_format_target(descriptor),
                descriptor=descriptor,
            )
        )
    return elements


def resolve_target(graph: RFGraph, target: str) -> TargetResolution:
    """Resolve ``target`` to exactly one stable node/port/container/edge identity.

    Bare node ids intentionally match every nested occurrence. Ambiguity is an
    actionable result, never guessed: each returned qualified address carries
    the full ancestor path, IO side, and literal-batch index and therefore
    round-trips to one element.
    """
    normalized = _normalize_address(target)
    nodes_by_id = {node.id: node for node in graph.nodes}
    elements = [*_node_elements(graph), *_edge_elements(graph, nodes_by_id)]
    matches = [element for element in elements if normalized in element.addresses]

    if not matches:
        bare_node_ids = sorted({node.ref.node_id for node in graph.nodes if node.ref.port is None})
        suggestions = find_similar_items(normalized, bare_node_ids, method="fuzzy")
        return TargetResolution(matched=0, suggestions=tuple(suggestions))
    if len(matches) > 1:
        return TargetResolution(
            matched=len(matches),
            qualify=tuple(sorted(element.qualified for element in matches)),
        )

    match = matches[0]
    return TargetResolution(
        matched=1,
        descriptor=match.descriptor,
        address=match.qualified,
    )


__all__ = ["TargetDescriptor", "TargetResolution", "address_for_ref", "address_for_target", "resolve_target"]
