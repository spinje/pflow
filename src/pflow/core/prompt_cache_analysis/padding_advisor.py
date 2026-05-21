"""Prefix-padding advisor — emits ``cache.padding-advisory`` per spec.

For each LLM node whose ``prompt_cache:`` subset doesn't start at position 1
of the master order, padding upstream chunks unlocks prefix hits at the 0.1×
read rate (cheaper than 1× on the existing items). Apply the spec's
sensitivity floors so advisory drown doesn't fire on micro-savings:

- Skip any individual advisory worth less than ``$0.005``.
- Skip the entire batch when cumulative savings across surviving candidates
  is less than ``$0.05``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from pflow.core.diagnostic import Diagnostic

from .warning_catalog import make_diagnostic

_INDIVIDUAL_FLOOR_USD: Final[float] = 0.005
_CUMULATIVE_FLOOR_USD: Final[float] = 0.05


@dataclass(frozen=True)
class PaddingCandidate:
    """One node's padding-advisory candidate.

    Net-positive math (spec § "Prefix-Padding Advisory") is the analyzer's
    job — by the time a candidate reaches this module, ``savings_usd`` is the
    pre-computed dollar saving of switching from ``current_subset`` to
    ``suggested_subset``.
    """

    node_id: str
    workflow_path: str | None
    current_subset: tuple[str, ...]
    suggested_subset: tuple[str, ...]
    savings_usd: float


def compute_padding_advisories(candidates: list[PaddingCandidate]) -> list[Diagnostic]:
    """Filter by sensitivity floors and emit advisory diagnostics."""
    surviving: list[PaddingCandidate] = [c for c in candidates if c.savings_usd >= _INDIVIDUAL_FLOOR_USD]
    cumulative = sum(c.savings_usd for c in surviving)
    if cumulative < _CUMULATIVE_FLOOR_USD:
        return []

    return [
        make_diagnostic(
            "cache.padding-advisory",
            node_id=c.node_id,
            affected_workflow=c.workflow_path,
            current_subset=list(c.current_subset),
            suggested_subset=list(c.suggested_subset),
            savings_usd=c.savings_usd,
        )
        for c in surviving
    ]


__all__ = ["PaddingCandidate", "compute_padding_advisories"]
