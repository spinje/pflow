"""F1.4 — padding advisor: net-positive math + sensitivity floors.

Spec § "Prefix-Padding Advisory":
- Skip individual advisories worth less than $0.005.
- Skip the entire batch when cumulative savings across candidates < $0.05.
- When in doubt, surface — agents prefer over-information to silence.
"""

from __future__ import annotations

from pflow.core.cache_analysis.padding_advisor import (
    PaddingCandidate,
    compute_padding_advisories,
)


def _candidate(
    node_id: str,
    *,
    current_subset: list[str],
    suggested_subset: list[str],
    savings_usd: float,
    workflow_path: str | None = "x.pflow.md",
) -> PaddingCandidate:
    return PaddingCandidate(
        node_id=node_id,
        workflow_path=workflow_path,
        current_subset=tuple(current_subset),
        suggested_subset=tuple(suggested_subset),
        savings_usd=savings_usd,
    )


def test_emits_advisory_for_net_positive_candidate_above_cumulative_floor() -> None:
    """A single advisory worth $0.06 clears both the $0.005 individual floor
    AND the $0.05 cumulative floor."""
    advisories = compute_padding_advisories([
        _candidate(
            "review-narrative",
            current_subset=["song-architecture.response"],
            suggested_subset=["concept", "creative-direction.response", "song-architecture.response"],
            savings_usd=0.06,
        )
    ])
    assert len(advisories) == 1
    assert advisories[0].id == "cache.padding-advisory"
    assert advisories[0].context is not None
    assert advisories[0].context["savings_usd"] == 0.06


def test_skips_single_below_cumulative_floor() -> None:
    """A single $0.04 advisory clears the individual floor but cumulative is
    $0.04 < $0.05 → emit nothing."""
    advisories = compute_padding_advisories([
        _candidate(
            "review-narrative",
            current_subset=["song-architecture.response"],
            suggested_subset=["concept", "song-architecture.response"],
            savings_usd=0.04,
        )
    ])
    assert advisories == []


def test_skips_individual_below_005_floor() -> None:
    advisories = compute_padding_advisories([
        _candidate(
            "X",
            current_subset=["a"],
            suggested_subset=["a", "b"],
            savings_usd=0.001,  # below $0.005 individual floor
        ),
        _candidate(
            "Y",
            current_subset=["a"],
            suggested_subset=["a", "b"],
            savings_usd=0.06,  # well above floor; cumulative survives
        ),
    ])
    # Only Y should emit — X dropped by individual floor.
    assert len(advisories) == 1
    assert advisories[0].node_id == "Y"


def test_skips_all_when_cumulative_below_005_dollar_floor() -> None:
    """All advisories worth < $0.05 cumulative → emit nothing."""
    advisories = compute_padding_advisories([
        _candidate("X", current_subset=["a"], suggested_subset=["a", "b"], savings_usd=0.01),
        _candidate("Y", current_subset=["a"], suggested_subset=["a", "b"], savings_usd=0.02),
        _candidate("Z", current_subset=["a"], suggested_subset=["a", "b"], savings_usd=0.01),
        # Cumulative = $0.04 < $0.05 — skip ALL even though each clears the individual floor.
    ])
    assert advisories == []


def test_emits_when_cumulative_clears_floor() -> None:
    advisories = compute_padding_advisories([
        _candidate("X", current_subset=["a"], suggested_subset=["a", "b"], savings_usd=0.02),
        _candidate("Y", current_subset=["a"], suggested_subset=["a", "b"], savings_usd=0.03),
        _candidate("Z", current_subset=["a"], suggested_subset=["a", "b"], savings_usd=0.01),
        # Cumulative = $0.06 ≥ $0.05.
    ])
    # All three above individual floor → all emit.
    assert len(advisories) == 3


def test_empty_candidate_list_returns_empty() -> None:
    assert compute_padding_advisories([]) == []


def test_advisory_carries_subset_lists_in_context() -> None:
    advisories = compute_padding_advisories([
        _candidate(
            "review",
            current_subset=["song-architecture.response"],
            suggested_subset=["concept", "song-architecture.response"],
            savings_usd=0.06,
        )
    ])
    ctx = advisories[0].context
    assert ctx is not None
    assert ctx["current_subset"] == ["song-architecture.response"]
    assert ctx["suggested_subset"] == ["concept", "song-architecture.response"]
