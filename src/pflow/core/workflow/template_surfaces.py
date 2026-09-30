"""Every template-bearing location in a workflow IR, in one enumeration.

The validator's template checks (the Issue pass, reference extraction, the data-flow
root check) each walk ``iter_template_surfaces`` instead of their own copy of "where
templates live", so a new location (Task 100's ``batch.initial``) is one line here and
every check sees it.
"""

from __future__ import annotations

import typing
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from pflow.core.templates import Template, parse

SurfaceKind = typing.Literal["param", "batch_items", "loop", "carry", "output_source", "cache_var", "cache_prose"]


@dataclass(frozen=True, slots=True)
class TemplateSurface:
    """One template-bearing IR location and its raw value."""

    kind: SurfaceKind
    node_id: str | None  # None for workflow-level surfaces (outputs, the cache block)
    # The author's name for the location: a param name, ``batch.items``, ``loop.while``,
    # ``loop.carry.<key>``, an output name, or a chunk name.
    key: str
    value: Any  # the raw IR value; dicts and lists nest

    def templates(self) -> Iterator[tuple[str, Template]]:
        """``(location, parsed text)`` for every string in the value.

        ``location`` extends ``key`` into nested values (``headers.Authorization``,
        ``batch.items[0].platform``). A cache var is stored bare in the IR (``p.x``),
        so it is parsed as the ``${p.x}`` the chunk came from.
        """
        if self.kind == "cache_var":
            yield self.key, parse("${" + self.value + "}")
            return
        yield from ((location, parse(text)) for location, text in _strings(self.key, self.value))

    def path(self, location: str) -> str:
        """The diagnostic path of ``location`` (``nodes[id=X].params.a.b``, ``outputs.o.source``)."""
        match self.kind:
            case "param":
                return f"nodes[id={self.node_id}].params.{location}"
            case "batch_items" | "loop" | "carry":
                return f"nodes[id={self.node_id}].{location}"
            case "output_source":
                return f"outputs.{location}.source"
            case "cache_var":
                return f"cache.items[name={location}].var"
            case "cache_prose":
                return f"cache.items[name={location}].prose_before"


def iter_template_surfaces(workflow_ir: dict[str, Any]) -> Iterator[TemplateSurface]:
    """Every template-bearing location, nodes first (IR order), then outputs, then the cache block."""
    for node in workflow_ir.get("nodes", []):
        yield from iter_node_surfaces(node)
    for name, output in (workflow_ir.get("outputs") or {}).items():
        if isinstance(output, dict) and isinstance(output.get("source"), str):
            yield TemplateSurface("output_source", None, name, output["source"])
    cache = workflow_ir.get("cache")
    items = cache.get("items") if isinstance(cache, dict) else None
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        if isinstance(item.get("var"), str) and item["var"]:
            yield TemplateSurface("cache_var", None, item["name"], item["var"])
        if isinstance(item.get("prose_before"), str):
            yield TemplateSurface("cache_prose", None, item["name"], item["prose_before"])


def iter_node_surfaces(node: dict[str, Any]) -> Iterator[TemplateSurface]:
    """One node's surfaces: its params, ``batch.items``, loop fields, and carry values."""
    node_id = node.get("id")
    params = node.get("params")
    for key, value in (params if isinstance(params, dict) else {}).items():
        yield TemplateSurface("param", node_id, key, value)
    batch = node.get("batch")
    if isinstance(batch, dict) and batch.get("items") is not None:
        yield TemplateSurface("batch_items", node_id, "batch.items", batch["items"])
    loop = node.get("loop")
    if not isinstance(loop, dict):
        return
    for key in ("while", "until", "max_iterations"):
        if isinstance(loop.get(key), str):
            yield TemplateSurface("loop", node_id, f"loop.{key}", loop[key])
    carry = loop.get("carry")
    for key, value in (carry if isinstance(carry, dict) else {}).items():
        yield TemplateSurface("carry", node_id, f"loop.carry.{key}", value)


def _strings(location: str, value: Any) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        if "${" in value:
            yield location, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(f"{location}.{key}", item)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(f"{location}[{index}]", item)
