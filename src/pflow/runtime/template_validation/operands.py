"""The operand classifier: which references the template passes check, and how.

Every reference the passes see comes from ``iter_template_operands`` (or, for output
sources, ``iter_output_source_operands``), tagged with its policy. Pass 5 (paths) and
Pass 8 (batch-item fields) field-check ``FIELD_CHECK`` references only; the
unused-input check counts all of them; ``ROOT_ONLY`` roots are checked by
``core/workflow/data_flow.py`` (ADR-0006).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pflow.core.templates import Reference, Template, parse
from pflow.core.workflow.template_surfaces import iter_template_surfaces
from pflow.runtime.output_resolver import normalize_output_source


class OperandPolicy(Enum):
    FIELD_CHECK = "field-check"
    ROOT_ONLY = "root-only"


def classify_operand(*, in_coalesce: bool) -> OperandPolicy:
    """A ``??`` operand may legitimately be missing a field — ``??`` falls through
    on it at runtime (#441) — so only its root is checked; any other reference is
    field-checked. (Literal operands are values, never classified.)"""
    return OperandPolicy.ROOT_ONLY if in_coalesce else OperandPolicy.FIELD_CHECK


@dataclass(frozen=True, slots=True)
class TemplateOperand:
    node_id: str | None
    ref: Reference
    policy: OperandPolicy


def iter_template_operands(workflow_ir: dict[str, Any]) -> Iterator[TemplateOperand]:
    """Every reference in node params, ``batch.items`` and loop fields — a dynamic
    index's inner references included, tagged with their enclosing operand's policy.

    A carry value's own reference and cache vars have their own passes (one
    diagnostic per mistake), but a carry's dynamic-index sources are ordinary
    reads; Issues belong to the Issue pass and hold no references. Output sources
    are ``iter_output_source_operands``'s.
    """
    for surface in iter_template_surfaces(workflow_ir):
        if surface.kind not in ("param", "batch_items", "loop", "carry"):
            continue
        for _, template in surface.templates():
            yield from _operands(surface.node_id, template, index_sources_only=surface.kind == "carry")


def iter_output_source_operands(workflow_ir: dict[str, Any]) -> Iterator[TemplateOperand]:
    """Every reference of every output ``source:``, parsed as the runtime resolves it
    (a bare ``n.x`` reads as ``${n.x}``), tagged like a param's."""
    for surface in iter_template_surfaces(workflow_ir):
        if surface.kind == "output_source":
            yield from _operands(None, parse(normalize_output_source(surface.value)))


def _operands(
    node_id: str | None, template: Template, *, index_sources_only: bool = False
) -> Iterator[TemplateOperand]:
    for expression in template.expressions:
        policy = classify_operand(in_coalesce=len(expression.operands) > 1)
        for operand in expression.operands:
            if isinstance(operand, Reference):
                refs = operand.index_sources if index_sources_only else operand.references
                for ref in refs:
                    yield TemplateOperand(node_id, ref, policy)
