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


def _node_addresses(ref: RFRef) -> tuple[tuple[str, ...], str]:
    """Every string this element answers to, plus its one canonical address.

    A node answers to its bare name and its scope-qualified name. An IO port
    answers to those *unprefixed natural* forms too (`source_file`, `child.data`
    — the names an agent reads under ``## Inputs``/``## Outputs``), so the prefix
    is never required up front. ``in:``/``out:`` only has to appear when a real
    same-name collision (an input and output both called ``data``) makes the bare
    name ambiguous — at which point it surfaces in the qualify list and teaches
    itself. The canonical (returned second) keeps the prefix so reports and
    qualify entries stay unambiguous.
    """
    scoped = _format_ref(_ref_payload(ref))
    addresses: tuple[str, ...]
    if ref.port in {"in", "out"}:
        unprefixed_scoped = scoped[len(ref.port) + 1 :]  # strip "in:"/"out:"
        addresses = (ref.node_id, unprefixed_scoped, f"{ref.port}:{ref.node_id}", scoped)
    else:
        addresses = (ref.node_id, scoped)
    return tuple(dict.fromkeys(addresses)), scoped


def _with_field(address: str, field: str | None, path: list[str]) -> str:
    suffix = [part for part in (field, *path) if part]
    return ".".join((address, *suffix)) if suffix else address


def _normalize_address(address: str) -> str:
    endpoints = address.split("->")
    if len(endpoints) == 2:
        return f"{endpoints[0].strip()} -> {endpoints[1].strip()}"
    return address.strip()


def _drop_prefix(endpoint: str) -> str:
    for prefix in ("in:", "out:"):
        if endpoint.startswith(prefix):
            return endpoint[len(prefix) :]
    return endpoint


def _drop_side_prefixes(address: str) -> str:
    """``address`` with each endpoint's leading ``in:``/``out:`` removed.

    The bare form an agent reads in the file. ``resolve_target`` only adopts it
    when it still resolves uniquely, so the side-prefix returns in the qualify
    list exactly when an input and output share a name — the one case it exists
    for.
    """
    return " -> ".join(_drop_prefix(endpoint) for endpoint in address.split(" -> "))


def _node_elements(graph: RFGraph) -> list[_Addressable]:
    elements = []
    for node in graph.nodes:
        addresses, qualified = _node_addresses(node.ref)
        elements.append(
            _Addressable(
                addresses=addresses,
                qualified=qualified,
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

        source_addrs, _ = _node_addresses(source.ref)
        target_addrs, _ = _node_addresses(target.ref)
        source_endpoints = {_with_field(addr, edge.output_field, edge.output_path) for addr in source_addrs}
        target_endpoints = {_with_field(addr, edge.input_name, []) for addr in target_addrs}
        # The natural form (both endpoints by their bare names) leads, so it is
        # what `resolve_target` offers as a suggestion when an edge address misses.
        natural = (
            f"{_with_field(source_addrs[0], edge.output_field, edge.output_path)} -> "
            f"{_with_field(target_addrs[0], edge.input_name, [])}"
        )
        all_addresses = {f"{src} -> {tgt}" for src in source_endpoints for tgt in target_endpoints}
        addresses = (natural, *sorted(all_addresses - {natural}))
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
    node_elements = _node_elements(graph)
    edge_elements = _edge_elements(graph, nodes_by_id)
    elements = [*node_elements, *edge_elements]
    matches = [element for element in elements if normalized in element.addresses]

    if not matches:
        # Suggest in the shape of what was typed: an edge attempt (`a -> b`) gets
        # real connections back, anything else gets step/input/output names. The
        # pool is each element's natural (bare) address, so a miss steers to a
        # name an agent can actually type — never a different kind of thing.
        if "->" in normalized:
            pool = sorted({element.addresses[0] for element in edge_elements})
        else:
            pool = sorted({element.addresses[0] for element in node_elements})
        suggestions = find_similar_items(normalized, pool, method="fuzzy")
        return TargetResolution(matched=0, suggestions=tuple(suggestions))
    if len(matches) > 1:
        return TargetResolution(
            matched=len(matches),
            qualify=tuple(sorted(element.qualified for element in matches)),
        )

    match = matches[0]
    # Report the address in the file's own vocabulary: drop the in:/out: side-prefix
    # when the bare form still names exactly one element. The prefix exists only to
    # disambiguate an input/output name collision — and a collision never lands here
    # (it returns a qualify list above), so on a unique match it is notation the agent
    # never typed. It stays in the qualify list, where it earns its place.
    address = match.qualified
    relaxed = _drop_side_prefixes(address)
    if relaxed != address and sum(relaxed in element.addresses for element in elements) == 1:
        address = relaxed
    return TargetResolution(
        matched=1,
        descriptor=match.descriptor,
        address=address,
    )


__all__ = ["TargetDescriptor", "TargetResolution", "address_for_ref", "address_for_target", "resolve_target"]
