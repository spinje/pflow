"""Tests for the shared cache-overlap detection module.

Pins the canonicalization rules and overlap kinds the validator and analyzer
both depend on. Drift between the validator's enforcement and the analyzer's
recommendation would put agents in a UX loop (analyze-cache says do X,
validator rejects X).
"""

from __future__ import annotations

import pytest

from pflow.core.cache_overlap import (
    Overlap,
    _canonicalize_path,
    _is_strict_prefix,
    compute_overlaps,
)

# ----------------------------------------------------------------------
# _canonicalize_path
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("concept", ("concept",)),
        ("concept.title", ("concept", "title")),
        ("concept[0]", ("concept", "[0]")),
        ("concept[0].title", ("concept", "[0]", "title")),
        ("concept.items[2].name", ("concept", "items", "[2]", "name")),
        ("a.b.c.d", ("a", "b", "c", "d")),
        ("a[0][1]", ("a", "[0]", "[1]")),
        ("", ()),
    ],
)
def test_canonicalize_path_examples(raw: str, expected: tuple) -> None:
    assert _canonicalize_path(raw) == expected


def test_canonicalize_path_non_string() -> None:
    # Defensive — non-string inputs cannot be paths; return empty tuple.
    assert _canonicalize_path(None) == ()  # type: ignore[arg-type]
    assert _canonicalize_path(123) == ()  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# _is_strict_prefix
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "a, b, expected",
    [
        # Equal — NOT a strict prefix.
        (("concept",), ("concept",), False),
        # Strict prefix.
        (("concept",), ("concept", "title"), True),
        # Superset (b shorter).
        (("concept", "title"), ("concept",), False),
        # Disjoint.
        (("a",), ("b",), False),
        # Empty prefix is NOT a strict prefix (matches the implementation
        # contract — empty paths from canonicalization are skipped upstream).
        ((), ("a",), False),
        # 3-deep prefix.
        (("concept", "items"), ("concept", "items", "[0]", "name"), True),
    ],
)
def test_is_strict_prefix(a: tuple, b: tuple, expected: bool) -> None:
    assert _is_strict_prefix(a, b) == expected


# ----------------------------------------------------------------------
# compute_overlaps — empty / absent inputs
# ----------------------------------------------------------------------


def test_compute_overlaps_empty_prompt_returns_empty() -> None:
    assert (
        compute_overlaps(
            prompt_text="",
            prompt_cache=["concept"],
            cache_item_names={"concept"},
            batch_aliases=set(),
        )
        == []
    )


def test_compute_overlaps_empty_cache_returns_empty() -> None:
    assert (
        compute_overlaps(
            prompt_text="Use ${concept} now.",
            prompt_cache=[],
            cache_item_names={"concept"},
            batch_aliases=set(),
        )
        == []
    )


def test_compute_overlaps_no_body_refs_returns_empty() -> None:
    # Prompt has templates BUT they all fail the var regex (bash syntax).
    assert (
        compute_overlaps(
            prompt_text="Run ${var:-default}",
            prompt_cache=["concept"],
            cache_item_names={"concept"},
            batch_aliases=set(),
        )
        == []
    )


# ----------------------------------------------------------------------
# compute_overlaps — kind detection
# ----------------------------------------------------------------------


def test_compute_overlaps_full_match_emits_duplicate() -> None:
    overlaps = compute_overlaps(
        prompt_text="Concept: ${concept}",
        prompt_cache=["concept"],
        cache_item_names={"concept"},
        batch_aliases=set(),
    )
    assert overlaps == [Overlap(chunk_name="concept", body_ref="concept", kind="duplicate")]


def test_compute_overlaps_subpath_cache_contains_body() -> None:
    overlaps = compute_overlaps(
        prompt_text="Title: ${concept.title}",
        prompt_cache=["concept"],
        cache_item_names={"concept"},
        batch_aliases=set(),
    )
    assert overlaps == [Overlap(chunk_name="concept", body_ref="concept.title", kind="cache_contains_body")]


def test_compute_overlaps_subpath_body_contains_cache() -> None:
    overlaps = compute_overlaps(
        prompt_text="Concept: ${concept}",
        prompt_cache=["concept.title"],
        cache_item_names={"concept.title"},
        batch_aliases=set(),
    )
    assert overlaps == [Overlap(chunk_name="concept.title", body_ref="concept", kind="body_contains_cache")]


def test_compute_overlaps_array_index_pinning() -> None:
    """Array indices canonicalize as their own path segment, so different
    indices don't false-positive."""
    # Same index → duplicate.
    overlaps_same = compute_overlaps(
        prompt_text="${items[0]}",
        prompt_cache=["items[0]"],
        cache_item_names={"items[0]"},
        batch_aliases=set(),
    )
    assert overlaps_same == [Overlap("items[0]", "items[0]", "duplicate")]
    # Different index → no overlap.
    overlaps_diff = compute_overlaps(
        prompt_text="${items[1]}",
        prompt_cache=["items[0]"],
        cache_item_names={"items[0]"},
        batch_aliases=set(),
    )
    assert overlaps_diff == []


# ----------------------------------------------------------------------
# compute_overlaps — filters
# ----------------------------------------------------------------------


def test_compute_overlaps_batch_scoped_skipped() -> None:
    """``${item.X}`` is batch-scoped — never overlap a stable cache chunk."""
    overlaps = compute_overlaps(
        prompt_text="Per-item: ${item.value}",
        prompt_cache=["item"],
        cache_item_names={"item"},
        batch_aliases={"item"},
    )
    assert overlaps == []


def test_compute_overlaps_bash_syntax_filtered() -> None:
    """Bash syntax (``${var:-default}``) fails the pflow var regex; no overlap."""
    overlaps = compute_overlaps(
        prompt_text="${var:-default}",
        prompt_cache=["var"],
        cache_item_names={"var"},
        batch_aliases=set(),
    )
    assert overlaps == []


def test_compute_overlaps_undeclared_chunk_skipped() -> None:
    """A prompt_cache: entry not in cache_item_names is skipped — that's a
    separate diagnostic (cache.undeclared-chunk)."""
    overlaps = compute_overlaps(
        prompt_text="${concept}",
        prompt_cache=["concept"],
        cache_item_names=set(),  # not declared
        batch_aliases=set(),
    )
    assert overlaps == []


# ----------------------------------------------------------------------
# compute_overlaps — coalesce
# ----------------------------------------------------------------------


def test_compute_overlaps_coalesce_two_way() -> None:
    """Both operands of ``${a ?? b}`` are checked independently."""
    overlaps = compute_overlaps(
        prompt_text="Pick: ${concept ?? fallback}",
        prompt_cache=["concept", "fallback"],
        cache_item_names={"concept", "fallback"},
        batch_aliases=set(),
    )
    body_refs = {(o.chunk_name, o.body_ref) for o in overlaps}
    assert body_refs == {("concept", "concept"), ("fallback", "fallback")}
    assert all(o.kind == "duplicate" for o in overlaps)


def test_compute_overlaps_coalesce_three_way() -> None:
    """Each operand of ``${a ?? b ?? c}`` is checked independently."""
    overlaps = compute_overlaps(
        prompt_text="${concept ?? primary_brief ?? fallback_brief}",
        prompt_cache=["concept", "fallback_brief"],
        cache_item_names={"concept", "fallback_brief"},
        batch_aliases=set(),
    )
    pairs = {(o.chunk_name, o.body_ref) for o in overlaps}
    assert pairs == {("concept", "concept"), ("fallback_brief", "fallback_brief")}


# ----------------------------------------------------------------------
# compute_overlaps — multiple chunks per node
# ----------------------------------------------------------------------


def test_compute_overlaps_multiple_chunks_same_prompt() -> None:
    overlaps = compute_overlaps(
        prompt_text="A=${a}, B=${b}, C=${c.field}",
        prompt_cache=["a", "b", "c"],
        cache_item_names={"a", "b", "c"},
        batch_aliases=set(),
    )
    triples = sorted((o.chunk_name, o.body_ref, o.kind) for o in overlaps)
    assert triples == [
        ("a", "a", "duplicate"),
        ("b", "b", "duplicate"),
        ("c", "c.field", "cache_contains_body"),
    ]
