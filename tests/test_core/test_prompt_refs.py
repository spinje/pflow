"""Unit tests for the prompt-ref classifier."""

from __future__ import annotations

import pytest

from pflow.core.prompt_refs import PromptRef, classify_prompt_refs, first_per_item_position


@pytest.mark.parametrize("prompt", ["", None, 42])
def test_classify_empty_prompt_returns_empty_tuple(prompt: object) -> None:
    assert classify_prompt_refs(prompt, "item", None) == ()  # type: ignore[arg-type]


def test_classify_direct_per_item_ref_position_and_end() -> None:
    assert classify_prompt_refs("prefix ${item.id} suffix", "item", None) == (
        PromptRef(position=7, end=17, raw_expr="item.id", operand_paths=("item.id",), is_per_item=True),
    )


def test_classify_indirected_per_item_ref_via_inputs() -> None:
    """Mutation contract: returning operands unchanged fails this test."""
    refs = classify_prompt_refs("prefix ${item_id} suffix", "item", {"item_id": "${item.id}"})

    assert refs == (PromptRef(position=7, end=17, raw_expr="item_id", operand_paths=("item.id",), is_per_item=True),)


def test_classify_indirected_via_node_output_stays_static() -> None:
    refs = classify_prompt_refs("${shared_x}", "item", {"shared_x": "${some_node.result}"})

    assert refs == (
        PromptRef(position=0, end=11, raw_expr="shared_x", operand_paths=("some_node.result",), is_per_item=False),
    )


def test_classify_coalesce_operands_per_item_when_any_branch_matches() -> None:
    """Mutation contract: changing classifier ``any(...)`` to ``all(...)`` fails."""
    refs = classify_prompt_refs("${a ?? item.x}", "item", None)

    assert refs == (
        PromptRef(position=0, end=14, raw_expr="a ?? item.x", operand_paths=("a", "item.x"), is_per_item=True),
    )


def test_classify_bracket_chain_dealiased() -> None:
    refs = classify_prompt_refs("${X[0].name}", "item", {"X": "${item.list}"})

    assert refs == (
        PromptRef(position=0, end=12, raw_expr="X[0].name", operand_paths=("item.list[0].name",), is_per_item=True),
    )


def test_classify_indirected_coalesce_splits_operand_paths() -> None:
    refs = classify_prompt_refs("${X.name}", "item", {"X": "${item.primary ?? fallback}"})

    assert refs == (
        PromptRef(
            position=0,
            end=9,
            raw_expr="X.name",
            operand_paths=("item.primary.name", "fallback.name"),
            is_per_item=True,
        ),
    )


def test_classify_batch_alias_none_never_per_item() -> None:
    refs = classify_prompt_refs("${item.id}", None, None)

    assert refs == (PromptRef(position=0, end=10, raw_expr="item.id", operand_paths=("item.id",), is_per_item=False),)


def test_classify_empty_batch_alias_never_per_item() -> None:
    refs = classify_prompt_refs("${item.id}", "", None)

    assert refs == (PromptRef(position=0, end=10, raw_expr="item.id", operand_paths=("item.id",), is_per_item=False),)


def test_first_per_item_position_returns_none_when_no_per_item_refs() -> None:
    assert first_per_item_position("static ${other.id}", "item", None) is None


def test_first_per_item_position_returns_first_when_multiple() -> None:
    assert first_per_item_position("static ${item.a} more static ${item.b}", "item", None) == 7


def test_classify_ignores_non_string_inputs_values() -> None:
    refs = classify_prompt_refs("${X} ${Y}", "item", {"X": 42, "Y": "${item.id}"})

    assert refs == (
        PromptRef(position=0, end=4, raw_expr="X", operand_paths=("X",), is_per_item=False),
        PromptRef(position=5, end=9, raw_expr="Y", operand_paths=("item.id",), is_per_item=True),
    )


def test_classify_dict_valued_inputs_pass_through_unchanged() -> None:
    refs = classify_prompt_refs("${X.nested}", "item", {"X": {"nested": "${item.y}"}})

    assert refs == (PromptRef(position=0, end=11, raw_expr="X.nested", operand_paths=("X.nested",), is_per_item=False),)


def test_classify_junk_template_value_passes_through() -> None:
    """Mutation contract: a startswith/endswith parser would wrongly dealias."""
    refs = classify_prompt_refs("${X}", "item", {"X": "${ unknown stuff }"})

    assert refs == (PromptRef(position=0, end=4, raw_expr="X", operand_paths=("X",), is_per_item=False),)
