"""The operand classifier: which references the template passes check, and how.

Every reference the passes see comes from ``iter_template_operands``, tagged with
its policy. Pass 5 (paths) and Pass 8 (batch-item fields) field-check
``FIELD_CHECK`` references only; the unused-input check counts all of them;
``ROOT_ONLY`` roots are checked by ``core/workflow/data_flow.py`` (ADR-0006).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pflow.core.templates import Reference
from pflow.core.workflow.template_surfaces import iter_template_surfaces


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

    Carry values, output sources and cache vars have their own passes (one
    diagnostic per mistake); Issues belong to the Issue pass and hold no references.
    """
    for surface in iter_template_surfaces(workflow_ir):
        if surface.kind not in ("param", "batch_items", "loop"):
            continue
        for _, template in surface.templates():
            for expression in template.expressions:
                policy = classify_operand(in_coalesce=len(expression.operands) > 1)
                for operand in expression.operands:
                    if isinstance(operand, Reference):
                        for ref in operand.references:
                            yield TemplateOperand(surface.node_id, ref, policy)
