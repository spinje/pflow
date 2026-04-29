"""Compiler-level tests for Task 159 B3.1: prompt_cache_items + prewarm + cache_block.

Covers:
- Default values when fields are absent (byte-identical to pre-task NodeConfig).
- Well-formed `prompt_cache: [a, b]` lifts to a frozen tuple.
- Well-formed top-level `cache:` block lifts to a frozen ``CacheBlockIR``.
- Frozen invariants: dataclasses.replace works; direct mutation raises.
- Round-6 hardening: 6 malformed shapes raise ``CompilationError(phase="validation")``
  with substrings that distinguish each case.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from pflow.core.cache_render import CacheBlockIR, CacheChunkIR
from pflow.core.exceptions import CompilationError
from pflow.registry.registry import Registry
from pflow.runtime.compilation.compiler import compile_workflow

# Each cache fixture references this single test chunk by name. Using a real
# inputs declaration keeps the validator happy without forcing every test to
# carry a custom cache block.
_TEST_INPUT_NAME = "concept"


def _shell_ir(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Minimal shell-only IR for tests that don't exercise cache fields."""
    node: dict[str, Any] = {"id": "step1", "type": "shell", "params": {"command": "echo hi"}}
    if extra:
        node.update(extra)
    return {"nodes": [node], "edges": []}


def _llm_ir(
    *,
    extra_node_fields: dict[str, Any] | None = None,
    cache: Any = None,
) -> dict[str, Any]:
    """Minimal LLM IR with a declared input. Optional cache block + extra node fields."""
    node: dict[str, Any] = {
        "id": "llm1",
        "type": "llm",
        "params": {"model": "anthropic/claude-3.5-haiku", "prompt": "Tell me about ${concept}"},
    }
    if extra_node_fields:
        node.update(extra_node_fields)
    ir: dict[str, Any] = {
        "nodes": [node],
        "edges": [],
        "inputs": {
            _TEST_INPUT_NAME: {
                "type": "string",
                "required": False,
                "default": "caching",
                "description": "test concept value",
            }
        },
    }
    if cache is not None:
        ir["cache"] = cache
    return ir


def _llm_ir_with_cache_chunk(prompt_cache: list[str]) -> dict[str, Any]:
    """LLM IR with a matching ## Cache block declaring the chunk(s)."""
    items = [{"name": name, "var": name, "prose_before": ""} for name in prompt_cache]
    return _llm_ir(
        extra_node_fields={"prompt_cache": prompt_cache},
        cache={"items": items},
    )


@pytest.fixture
def registry() -> Registry:
    return Registry()


# --- Defaults / happy path -------------------------------------------------


def test_defaults_when_fields_absent(registry: Registry) -> None:
    compiled = compile_workflow(_shell_ir(), registry)
    config = compiled.node_configs["step1"]
    assert config.prompt_cache_items == ()
    assert isinstance(config.prompt_cache_items, tuple)
    assert config.prewarm is False
    assert compiled.cache_block is None


def test_well_formed_prompt_cache_lifts_to_tuple(registry: Registry) -> None:
    compiled = compile_workflow(_llm_ir_with_cache_chunk(["concept"]), registry)
    config = compiled.node_configs["llm1"]
    assert config.prompt_cache_items == ("concept",)
    assert isinstance(config.prompt_cache_items, tuple)


def test_empty_prompt_cache_normalizes_to_empty_tuple(registry: Registry) -> None:
    compiled = compile_workflow(
        _llm_ir(extra_node_fields={"prompt_cache": []}),
        registry,
    )
    assert compiled.node_configs["llm1"].prompt_cache_items == ()


def test_prewarm_true_lifts_to_bool(registry: Registry) -> None:
    compiled = compile_workflow(_llm_ir(extra_node_fields={"prewarm": True}), registry)
    assert compiled.node_configs["llm1"].prewarm is True


def test_prewarm_false_lifts_to_bool(registry: Registry) -> None:
    compiled = compile_workflow(_llm_ir(extra_node_fields={"prewarm": False}), registry)
    assert compiled.node_configs["llm1"].prewarm is False


def test_top_level_cache_block_builds_cache_block_ir(registry: Registry) -> None:
    cache = {
        "ttl": "5m",
        "items": [
            {"name": "concept", "var": "concept", "prose_before": "About the concept:\n", "_source_line": 12},
        ],
        "_source_line": 10,
    }
    compiled = compile_workflow(_llm_ir(cache=cache), registry)
    assert isinstance(compiled.cache_block, CacheBlockIR)
    assert compiled.cache_block.ttl == "5m"
    assert isinstance(compiled.cache_block.items, tuple)
    assert len(compiled.cache_block.items) == 1
    chunk = compiled.cache_block.items[0]
    assert isinstance(chunk, CacheChunkIR)
    assert chunk.name == "concept"
    assert chunk.var_expr == "concept"
    assert chunk.prose_before == "About the concept:\n"
    assert chunk.source_line == 12
    assert compiled.cache_block.source_line == 10


def test_cache_block_with_omitted_ttl_is_none(registry: Registry) -> None:
    cache = {"items": [{"name": "concept", "var": "concept", "prose_before": ""}]}
    compiled = compile_workflow(_llm_ir(cache=cache), registry)
    assert compiled.cache_block is not None
    assert compiled.cache_block.ttl is None


def test_cache_block_is_frozen(registry: Registry) -> None:
    cache = {"items": [{"name": "concept", "var": "concept", "prose_before": ""}]}
    compiled = compile_workflow(_llm_ir(cache=cache), registry)
    block = compiled.cache_block
    assert block is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        block.ttl = "1h"  # type: ignore[misc]
    chunk = block.items[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        chunk.name = "different"  # type: ignore[misc]
    new_block = dataclasses.replace(block, ttl="1h")
    assert new_block.ttl == "1h"
    assert block.ttl is None  # original unchanged


# --- Round-6 hardening: malformed shapes raise CompilationError -----------


@pytest.mark.parametrize(
    ("bad_value", "expected_substring"),
    [
        (5, "got int: 5"),
        ("concept", "got str: 'concept'"),
        ({"key": "v"}, "got dict:"),
        ({"a", "b"}, "got set:"),
        ([1, 2, 3], "got list:"),
        ([{"a": 1}], "got list:"),
    ],
)
def test_malformed_prompt_cache_raises_compilation_error(
    bad_value: Any,
    expected_substring: str,
    registry: Registry,
) -> None:
    """Each malformed shape is rejected with an identifying message.

    Without the explicit ``isinstance`` precondition, ``tuple("concept")`` would
    silently splat into ``('c', 'o', 'n', 'c', 'e', 'p', 't')`` — the
    silent-stale-cache regression class B3.1 closes.

    The cache-validator's STEP 2 logs+continues for malformed shapes on LLM
    nodes (so ``_validate_cache_block`` does not emit a Diagnostic), letting
    ``_create_node_and_config`` reach the malformed value and raise here.
    """
    with pytest.raises(CompilationError) as excinfo:
        compile_workflow(_llm_ir(extra_node_fields={"prompt_cache": bad_value}), registry)
    assert excinfo.value.phase == "validation"
    assert excinfo.value.node_id == "llm1"
    assert excinfo.value.node_type == "llm"
    assert "prompt_cache" in str(excinfo.value)
    assert expected_substring in str(excinfo.value)


def test_well_formed_prompt_cache_does_not_raise(registry: Registry) -> None:
    """Positive control — protects against an over-broad check that rejects valid input."""
    compile_workflow(_llm_ir_with_cache_chunk(["concept"]), registry)


@pytest.mark.parametrize(
    ("bad_value", "expected_substring"),
    [
        (1, "got int: 1"),
        (0, "got int: 0"),
        ("true", "got str: 'true'"),
        ([], "got list: []"),
    ],
)
def test_malformed_prewarm_raises_compilation_error(
    bad_value: Any,
    expected_substring: str,
    registry: Registry,
) -> None:
    """``isinstance(True, int)`` is True, so a naive ``isinstance(_, int)`` check
    would accept ``prewarm: 1`` — the bool-strict guard prevents that."""
    with pytest.raises(CompilationError) as excinfo:
        compile_workflow(_llm_ir(extra_node_fields={"prewarm": bad_value}), registry)
    assert excinfo.value.phase == "validation"
    assert "prewarm" in str(excinfo.value)
    assert expected_substring in str(excinfo.value)


def test_malformed_cache_block_raises_compilation_error(registry: Registry) -> None:
    """Top-level ``cache:`` of wrong shape (non-dict) raises rather than silently no-op."""
    with pytest.raises(CompilationError) as excinfo:
        compile_workflow(_llm_ir(cache=["not", "a", "dict"]), registry)
    assert excinfo.value.phase == "validation"
    assert "cache" in str(excinfo.value).lower()


# --- Regression: existing memo-cache opt-out (`cache: bool`) still works ---


def test_existing_cache_enabled_still_works(registry: Registry) -> None:
    compiled = compile_workflow(_shell_ir({"cache": False}), registry)
    config = compiled.node_configs["step1"]
    assert config.cache_enabled is False
    # And the new fields stay at default:
    assert config.prompt_cache_items == ()
    assert config.prewarm is False
