"""Tests for cache-related IR schema additions (Task 159 B2.2).

Schema is the SINGLE source of truth for cache-block shape per the V5 fix
(Round 4 plan refinement): top-level ``cache`` is an object with ``ttl`` enum
(``5m`` | ``1h``), ``items`` array of {name, var, prose_before}; per-node
``prompt_cache: list[str]`` and ``prewarm: bool`` are additive properties on
EVERY node type (semantic ``invalid-on-non-llm`` rejection lives in B2.3
data_flow validation, not the schema).
"""

from __future__ import annotations

import pytest

from pflow.core import validate_ir
from pflow.core.exceptions import SchemaValidationError


def _minimal_workflow(extra_nodes: list[dict] | None = None, **top_level) -> dict:
    """Build a minimal valid IR with optional cache + extra nodes."""
    nodes = [{"id": "n", "type": "shell", "params": {"command": "echo hi"}}]
    if extra_nodes:
        nodes.extend(extra_nodes)
    ir: dict = {"ir_version": "0.1.0", "nodes": nodes}
    ir.update(top_level)
    return ir


# ------------------------------------------------------------------------------
# Top-level ``cache`` block shape
# ------------------------------------------------------------------------------


def test_valid_cache_block_with_ttl_passes() -> None:
    ir = _minimal_workflow(
        cache={
            "ttl": "5m",
            "items": [{"name": "concept", "var": "concept", "prose_before": "The concept:"}],
        }
    )
    validate_ir(ir)  # no exception


def test_valid_cache_block_with_1h_ttl_passes() -> None:
    ir = _minimal_workflow(
        cache={
            "ttl": "1h",
            "items": [{"name": "x", "var": "x", "prose_before": ""}],
        }
    )
    validate_ir(ir)


def test_valid_cache_block_without_ttl_passes() -> None:
    """Default-TTL workflows omit ``ttl`` — schema must accept absence."""
    ir = _minimal_workflow(cache={"items": [{"name": "x", "var": "x", "prose_before": ""}]})
    validate_ir(ir)


def test_valid_cache_block_with_source_line_metadata_passes() -> None:
    """Internal ``_source_line`` metadata injected by the parser is allowed."""
    ir = _minimal_workflow(
        cache={
            "ttl": "5m",
            "_source_line": 5,
            "items": [
                {"name": "x", "var": "x", "prose_before": "", "_source_line": 8},
            ],
        }
    )
    validate_ir(ir)


def test_invalid_ttl_value_rejected_at_schema() -> None:
    ir = _minimal_workflow(
        cache={
            "ttl": "30m",  # not in enum
            "items": [{"name": "x", "var": "x", "prose_before": ""}],
        }
    )
    with pytest.raises(SchemaValidationError):
        validate_ir(ir)


def test_cache_items_must_be_array() -> None:
    ir = _minimal_workflow(cache={"ttl": "5m", "items": "not-an-array"})
    with pytest.raises(SchemaValidationError):
        validate_ir(ir)


def test_cache_item_missing_name_rejected() -> None:
    ir = _minimal_workflow(
        cache={"items": [{"var": "x", "prose_before": ""}]}  # no name
    )
    with pytest.raises(SchemaValidationError):
        validate_ir(ir)


def test_cache_item_missing_var_rejected() -> None:
    ir = _minimal_workflow(
        cache={"items": [{"name": "x", "prose_before": ""}]}  # no var
    )
    with pytest.raises(SchemaValidationError):
        validate_ir(ir)


def test_cache_top_level_extra_property_rejected() -> None:
    """Schema's ``additionalProperties: False`` rejects unknown keys on cache."""
    ir = _minimal_workflow(
        cache={
            "ttl": "5m",
            "items": [{"name": "x", "var": "x", "prose_before": ""}],
            "unknown_top_level_field": "value",
        }
    )
    with pytest.raises(SchemaValidationError):
        validate_ir(ir)


def test_cache_item_extra_property_rejected() -> None:
    """Per-item ``additionalProperties: False`` rejects unknown keys on chunks."""
    ir = _minimal_workflow(
        cache={
            "items": [{"name": "x", "var": "x", "prose_before": "", "extra": "junk"}],
        }
    )
    with pytest.raises(SchemaValidationError):
        validate_ir(ir)


def test_top_level_cahe_typo_rejected() -> None:
    """``cahe:`` typo at top-level is rejected by the existing
    ``additionalProperties: False`` invariant — Task 159 just adds ``cache``."""
    ir = _minimal_workflow(cahe={"items": []})
    with pytest.raises(SchemaValidationError):
        validate_ir(ir)


# ------------------------------------------------------------------------------
# Per-node ``prompt_cache`` and ``prewarm`` fields
# ------------------------------------------------------------------------------


def test_prompt_cache_list_of_strings_accepted() -> None:
    ir = _minimal_workflow(
        extra_nodes=[
            {
                "id": "llm-step",
                "type": "llm",
                "params": {"prompt": "do thing", "model": "claude-sonnet-4-5"},
                "prompt_cache": ["concept", "concept_brief"],
            }
        ],
        cache={
            "items": [
                {"name": "concept", "var": "concept", "prose_before": ""},
                {"name": "concept_brief", "var": "concept_brief", "prose_before": ""},
            ],
        },
    )
    validate_ir(ir)


def test_prompt_cache_empty_list_accepted() -> None:
    ir = _minimal_workflow(
        extra_nodes=[
            {
                "id": "llm-step",
                "type": "llm",
                "params": {"prompt": "x", "model": "claude-sonnet-4-5"},
                "prompt_cache": [],
            }
        ]
    )
    validate_ir(ir)


def test_prompt_cache_non_list_rejected() -> None:
    ir = _minimal_workflow(
        extra_nodes=[
            {
                "id": "llm-step",
                "type": "llm",
                "params": {"prompt": "x", "model": "claude-sonnet-4-5"},
                "prompt_cache": "concept",  # string, not list
            }
        ]
    )
    with pytest.raises(SchemaValidationError):
        validate_ir(ir)


def test_prompt_cache_list_of_non_strings_rejected() -> None:
    ir = _minimal_workflow(
        extra_nodes=[
            {
                "id": "llm-step",
                "type": "llm",
                "params": {"prompt": "x", "model": "claude-sonnet-4-5"},
                "prompt_cache": [1, 2, 3],  # ints, not strings
            }
        ]
    )
    with pytest.raises(SchemaValidationError):
        validate_ir(ir)


def test_prewarm_boolean_accepted() -> None:
    ir = _minimal_workflow(
        extra_nodes=[
            {
                "id": "llm-step",
                "type": "llm",
                "params": {"prompt": "x", "model": "claude-sonnet-4-5"},
                "prewarm": True,
            }
        ]
    )
    validate_ir(ir)


def test_prewarm_non_bool_rejected() -> None:
    """Schema rejects ``prewarm: 1`` (bare int) — even though Python's
    ``isinstance(True, int)`` is True, JSON-schema ``boolean`` type matches
    only ``True``/``False``, not ``1``/``0``."""
    ir = _minimal_workflow(
        extra_nodes=[
            {
                "id": "llm-step",
                "type": "llm",
                "params": {"prompt": "x", "model": "claude-sonnet-4-5"},
                "prewarm": 1,
            }
        ]
    )
    with pytest.raises(SchemaValidationError):
        validate_ir(ir)


def test_prompt_cahe_typo_rejected_via_additional_properties() -> None:
    """Per-node ``additionalProperties: False`` rejects ``prompt_cahe`` (typo)."""
    ir = _minimal_workflow(
        extra_nodes=[
            {
                "id": "llm-step",
                "type": "llm",
                "params": {"prompt": "x", "model": "claude-sonnet-4-5"},
                "prompt_cahe": ["concept"],
            }
        ]
    )
    with pytest.raises(SchemaValidationError):
        validate_ir(ir)


def test_cache_bool_and_prompt_cache_coexist_on_same_node() -> None:
    """Existing ``cache: false`` (memo opt-out) and ``prompt_cache:`` (LLM provider
    cache) are independent fields and may coexist on a single node — DD#5."""
    ir = _minimal_workflow(
        extra_nodes=[
            {
                "id": "llm-step",
                "type": "llm",
                "params": {"prompt": "x", "model": "claude-sonnet-4-5"},
                "cache": False,
                "prompt_cache": ["concept"],
            }
        ],
        cache={"items": [{"name": "concept", "var": "concept", "prose_before": ""}]},
    )
    validate_ir(ir)


# ------------------------------------------------------------------------------
# Three-state IR shape: absent vs ``[]`` vs non-empty
# ------------------------------------------------------------------------------


def test_three_state_for_prompt_cache_field() -> None:
    """Parser/schema preserve three distinct states for the ``prompt_cache`` field
    — absent, empty list, non-empty list. These map to different runtime shapes
    and the schema must accept all three (B2.3 enforces semantic equivalence
    between absent and ``[]``)."""
    # Absent
    ir1 = _minimal_workflow(
        extra_nodes=[{"id": "x", "type": "llm", "params": {"prompt": "x", "model": "claude-sonnet-4-5"}}]
    )
    # Empty list
    ir2 = _minimal_workflow(
        extra_nodes=[
            {
                "id": "x",
                "type": "llm",
                "params": {"prompt": "x", "model": "claude-sonnet-4-5"},
                "prompt_cache": [],
            }
        ]
    )
    # Non-empty
    ir3 = _minimal_workflow(
        extra_nodes=[
            {
                "id": "x",
                "type": "llm",
                "params": {"prompt": "x", "model": "claude-sonnet-4-5"},
                "prompt_cache": ["concept"],
            }
        ],
        cache={"items": [{"name": "concept", "var": "concept", "prose_before": ""}]},
    )
    validate_ir(ir1)
    validate_ir(ir2)
    validate_ir(ir3)


# ------------------------------------------------------------------------------
# prompt_cache and prewarm are accepted on every node type at the schema level.
# Semantic ``cache.invalid-on-non-llm`` rejection is in B2.3, not the schema.
# ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "node_type, params",
    [
        ("shell", {"command": "echo x"}),
        ("http", {"url": "https://x"}),
        ("llm", {"prompt": "x", "model": "claude-sonnet-4-5"}),
    ],
)
def test_prompt_cache_accepted_at_schema_level_on_all_node_types(node_type, params) -> None:
    """Schema is single-source-of-truth for shape; semantic rejection on
    non-LLM types is in data_flow B2.3, not here. Without this contract, the
    schema would emit a different error than B2.3, double-emitting on the
    save path.
    """
    ir = _minimal_workflow(
        extra_nodes=[
            {
                "id": "x",
                "type": node_type,
                "params": params,
                "prompt_cache": ["something"],
            }
        ]
    )
    # Schema layer accepts; B2.3 may reject semantically — that's a separate test.
    validate_ir(ir)
