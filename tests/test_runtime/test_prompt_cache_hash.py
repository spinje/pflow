"""Regression tests for Task 159 B3.3 + B3.4: prompt_cache hashing.

The single load-bearing gate for the entire feature:
- Workflows WITHOUT ``prompt_cache:``/``## Cache`` produce byte-identical
  ``compute_config_hash`` results pre- and post-task (DD#19).
- ``prompt_cache: []`` is byte-equivalent to absent.
- ``prompt_cache: [chunk]`` + matching ``## Cache`` block produces a
  DIFFERENT hash from absent (so cache opt-in invalidates stale memo entries
  cleanly).

If the golden-fixture comparison fails, STOP — silent stale-cache hits are
the #1 risk for this whole feature. Don't regenerate the fixture without
human review of the underlying compute_node_config change.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from pflow.core.cache_render import _CHUNK_ABSENT, _ChunkAbsentSentinel
from pflow.core.markdown_parser import parse_markdown
from pflow.registry.registry import Registry
from pflow.runtime.cache import _make_serializable
from pflow.runtime.compilation.compiler import compile_workflow
from pflow.runtime.engine.instrumentation import compute_config_hash, compute_node_config

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_FIXTURE = REPO_ROOT / "tests" / "test_runtime" / "fixtures" / "golden_config_hashes.json"

# Single source of truth: imported from the same module the regen script uses.
# Drift between regen and verify paths is impossible by construction.
from tests.test_runtime.fixtures.baseline_workflows import BASELINE_WORKFLOWS  # noqa: E402

_BASELINE_INPUTS: dict[str, dict[str, Any]] = {wf.rel_path: dict(wf.inputs) for wf in BASELINE_WORKFLOWS if wf.inputs}


def _compute_workflow_hashes(rel_path: str, registry: Registry) -> dict[str, str]:
    """Recompute hashes for a baseline workflow — mirrors the regen script."""
    abs_path = REPO_ROOT / rel_path
    ir = parse_markdown(abs_path.read_text(encoding="utf-8")).ir
    initial = {**_BASELINE_INPUTS.get(rel_path, {}), "_pflow_workflow_file": str(abs_path)}
    compiled = compile_workflow(ir, registry, initial_params=initial)
    out: dict[str, str] = {}
    for node_id, config in compiled.node_configs.items():
        node_config = compute_node_config(
            config.node_type_name,
            config.template_config.static_params if config.template_config else {},
            config.template_config.template_params if config.template_config else {},
            config.batch_config,
        )
        out[node_id] = compute_config_hash(node_config)
    return out


# --- LOAD-BEARING REGRESSION GATE -----------------------------------------


def test_golden_baseline_hashes_match() -> None:
    """The single load-bearing test for DD#19: workflows WITHOUT prompt_cache
    must hash byte-identically pre- and post-Task-159 B3.

    On failure: do NOT regenerate the fixture. Inspect the change. Silent
    regeneration encodes the bug as expected. Regen command (only after
    human review): ``uv run python scripts/generate_config_hash_baseline.py``.
    """
    assert GOLDEN_FIXTURE.exists(), (
        "Golden fixture missing — generate via "
        "`uv run python scripts/generate_config_hash_baseline.py` BEFORE landing B3 patches."
    )
    expected = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
    registry = Registry()
    drift: list[str] = []
    for rel_path, expected_node_hashes in expected.items():
        if rel_path.startswith("_"):  # Skip _meta and _coverage
            continue
        actual = _compute_workflow_hashes(rel_path, registry)
        for node_id, expected_hash in expected_node_hashes.items():
            actual_hash = actual.get(node_id)
            if actual_hash != expected_hash:
                drift.append(
                    f"  - {rel_path} :: {node_id}\n      expected: {expected_hash}\n      actual:   {actual_hash}"
                )
    assert not drift, (
        "compute_config_hash drift detected — silent stale-cache regression class (DD#19).\n"
        "DO NOT regenerate the baseline without human review of the underlying change.\n"
        "Drifted nodes:\n" + "\n".join(drift)
    )


# --- DD#19 byte-identity at NodeConfig level -------------------------------


def test_compute_node_config_skips_prompt_cache_when_none() -> None:
    config = compute_node_config("LLMNode", {"a": 1}, {}, None, prompt_cache_content=None)
    assert "prompt_cache" not in config


def test_compute_node_config_skips_prompt_cache_when_empty_list() -> None:
    """Empty list is byte-equivalent to None — DD#19 three-state edge case."""
    config = compute_node_config("LLMNode", {"a": 1}, {}, None, prompt_cache_content=[])
    assert "prompt_cache" not in config


def test_compute_node_config_includes_prompt_cache_when_non_empty() -> None:
    chunks = [{"name": "concept", "prose": "About: ", "value": "the concept"}]
    config = compute_node_config("LLMNode", {"a": 1}, {}, None, prompt_cache_content=chunks)
    assert config["prompt_cache"] == chunks


def test_hash_three_state_invariant_at_node_level() -> None:
    """absent ≡ [] != [chunk] — DD#19's load-bearing three-state."""
    base = compute_node_config("LLMNode", {"a": 1}, {}, None)
    empty = compute_node_config("LLMNode", {"a": 1}, {}, None, prompt_cache_content=[])
    populated = compute_node_config(
        "LLMNode",
        {"a": 1},
        {},
        None,
        prompt_cache_content=[{"name": "x", "prose": "", "value": "v"}],
    )
    h_base = compute_config_hash(base)
    h_empty = compute_config_hash(empty)
    h_populated = compute_config_hash(populated)
    assert h_base == h_empty, "absent and [] must produce byte-identical hashes (DD#19)"
    assert h_base != h_populated, "non-empty prompt_cache must change the hash"


# --- DD#19 byte-identity end-to-end via compile_workflow -------------------


_WORKFLOW_NO_CACHE = """
# No-Cache Workflow

A small LLM workflow used to verify hash byte-identity at the IR level:
absent vs `prompt_cache: []` produce identical hashes; non-empty differs.

## Inputs

### concept

A concept value.

- type: string
- required: false
- default: caching

## Steps

### gen

Generate a one-liner about the concept.

- type: llm
- model: anthropic/claude-3.5-haiku

```prompt
Tell me a one-liner story.
```
"""


def _compile_with_mutations(ir_dict: dict[str, Any], registry: Registry) -> dict[str, str]:
    """Compile a deep-copied IR (so file-resolution mutations don't bleed)
    and return ``{node_id: config_hash}``.
    """
    workflow = compile_workflow(copy.deepcopy(ir_dict), registry)
    out: dict[str, str] = {}
    for node_id, config in workflow.node_configs.items():
        node_config = compute_node_config(
            config.node_type_name,
            config.template_config.static_params if config.template_config else {},
            config.template_config.template_params if config.template_config else {},
            config.batch_config,
        )
        out[node_id] = compute_config_hash(node_config)
    return out


# --- The end-to-end hash divergence fires through plan_node ----------------
# (A previous "three-state via compile" test asserted that ``compute_node_config``
# without the ``prompt_cache_content`` kwarg ignores cache IR fields — a
# tautology, since the helper never reads cache content unless it's passed in.
# Removed; the production-shape divergence is covered by
# ``test_plan_node_renders_cache_into_hash`` directly below.)


def test_plan_node_renders_cache_into_hash() -> None:
    """When plan_node runs over a workflow with prompt_cache, the rendered
    cache content flows into compute_node_config and changes the hash —
    while a no-cache run of the same node produces the pre-task hash."""
    from pflow.runtime.engine.engine import build_cache_render_dict
    from pflow.runtime.engine.plan_node import plan_node

    ir = parse_markdown(_WORKFLOW_NO_CACHE).ir
    base_workflow = compile_workflow(copy.deepcopy(ir), Registry())
    base_node = base_workflow.start_node
    base_config = base_workflow.node_configs["gen"]

    # State 1: no cache state in shared (workflow.cache_block is None)
    shared_no_cache: dict[str, Any] = {"concept": "x"}
    plan_no_cache = plan_node(base_node, base_config, shared_no_cache)

    # State 2: same workflow but with cache block + subset, rendered through
    # the engine's build_cache_render_dict (skipping engine.run; we want
    # the bare hash impact)
    ir_with_cache = copy.deepcopy(ir)
    ir_with_cache["nodes"][0]["prompt_cache"] = ["concept"]
    ir_with_cache["cache"] = {
        "items": [{"name": "concept", "var": "concept", "prose_before": "About: "}],
    }
    cache_workflow = compile_workflow(ir_with_cache, Registry())
    cache_node = cache_workflow.start_node
    cache_config = cache_workflow.node_configs["gen"]
    shared_with_cache: dict[str, Any] = {
        "concept": "x",
        "__pflow_cache_render__": build_cache_render_dict(cache_workflow),
    }
    plan_with_cache = plan_node(cache_node, cache_config, shared_with_cache)

    assert plan_no_cache.config_hash != plan_with_cache.config_hash, (
        "plan_node must include rendered cache content in the hash when the "
        "node opts in via prompt_cache: [...] — otherwise upgraded workflows "
        "could silently hit stale memo entries (DD#19)."
    )


# --- _make_serializable defense (Round 5) ----------------------------------


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(_CHUNK_ABSENT, id="top_level"),
        pytest.param({"key": _CHUNK_ABSENT}, id="inside_dict"),
        pytest.param([_CHUNK_ABSENT], id="inside_list"),
        pytest.param({"a": [_CHUNK_ABSENT]}, id="dict_of_list"),
        pytest.param([{"a": _CHUNK_ABSENT}], id="list_of_dict"),
    ],
)
def test_make_serializable_rejects_chunk_absent(value: Any) -> None:
    """``_make_serializable`` must raise TypeError when ``_CHUNK_ABSENT``
    appears anywhere in the input — directly, in a dict value, in a list
    element, or nested inside any combination. A leak past the symmetric
    ``_resolve_chunk_value`` filter would otherwise serialize to a stable
    type-name string and silently key the memo cache on bytes the LLM never
    actually saw.
    """
    with pytest.raises(TypeError) as excinfo:
        _make_serializable(value)
    # The locked error-message substring lets any future defense-bypass test
    # pin against it without coupling to repr formatting.
    assert "_CHUNK_ABSENT must be filtered before serialization" in str(excinfo.value)


def test_make_serializable_pass_through_for_normal_string() -> None:
    """Positive control — protects against a defense that's too broad."""
    assert _make_serializable("normal_string") == "normal_string"


# --- Branch-absent symmetry (hash side) -----------------------------------


def test_render_cache_for_hash_filters_absent_chunks() -> None:
    """When an upstream node is ABSENT, ``_render_cache_for_hash`` drops the
    chunk from the rendered list — preserving the symmetric subset filter
    invariant that ``LLMNode.prep`` (C1.2) will mirror.

    Without this filter, plan_node would include a stringified ``None`` in
    the hash while LLMNode.prep skipped the chunk entirely — the silent
    stale-cache class for branch-absent upstreams.
    """
    from pflow.runtime.engine.engine import build_cache_render_dict
    from pflow.runtime.engine.plan_node import _render_cache_for_hash

    ir = parse_markdown(_WORKFLOW_NO_CACHE).ir
    ir_with_cache = copy.deepcopy(ir)
    # Add a declared but optional workflow input so the cache chunk
    # reference passes data_flow validation, but the value is NOT seeded in
    # shared at render time → NodeStatus.ABSENT, sentinel returned, filtered.
    ir_with_cache["inputs"]["absent_input"] = {
        "type": "string",
        "required": False,
        "default": None,
        "description": "deliberately absent at render time",
    }
    ir_with_cache["nodes"][0]["prompt_cache"] = ["concept", "absent_input"]
    ir_with_cache["cache"] = {
        "items": [
            {"name": "concept", "var": "concept", "prose_before": "About: "},
            {"name": "absent_input", "var": "absent_input", "prose_before": "Skipped: "},
        ],
    }
    workflow = compile_workflow(ir_with_cache, Registry())
    config = workflow.node_configs["gen"]
    # Note: absent_input is NOT in shared. get_node_status returns ABSENT.
    shared: dict[str, Any] = {
        "concept": "the concept value",
        "__pflow_cache_render__": build_cache_render_dict(workflow),
    }

    rendered = _render_cache_for_hash(config, shared)
    assert rendered is not None
    # absent_node has NodeStatus.ABSENT — the chunk is filtered out.
    rendered_names = [chunk["name"] for chunk in rendered]
    assert rendered_names == ["concept"], f"absent chunk leaked into hash: rendered_names={rendered_names!r}"
    # No leaked sentinel anywhere in the rendered list.
    for chunk in rendered:
        assert not isinstance(chunk["value"], _ChunkAbsentSentinel)


def test_render_cache_for_hash_returns_none_on_no_opt_in() -> None:
    """LLM node with no prompt_cache and no workflow cache_block → None.
    Conditional inclusion in compute_node_config skips this case, byte-
    identical to pre-task."""
    from pflow.runtime.engine.plan_node import _render_cache_for_hash

    ir = parse_markdown(_WORKFLOW_NO_CACHE).ir
    workflow = compile_workflow(ir, Registry())
    config = workflow.node_configs["gen"]
    # Empty cache_render dict — no opt-in, no block.
    assert _render_cache_for_hash(config, {"__pflow_cache_render__": {}}) is None


def test_render_cache_for_hash_returns_none_on_empty_subset() -> None:
    """``prompt_cache: []`` is byte-equivalent to absent (DD#19)."""
    from pflow.runtime.engine.engine import build_cache_render_dict
    from pflow.runtime.engine.plan_node import _render_cache_for_hash

    ir = parse_markdown(_WORKFLOW_NO_CACHE).ir
    ir_with_empty = copy.deepcopy(ir)
    ir_with_empty["nodes"][0]["prompt_cache"] = []
    workflow = compile_workflow(ir_with_empty, Registry())
    config = workflow.node_configs["gen"]
    shared: dict[str, Any] = {
        "concept": "x",
        "__pflow_cache_render__": build_cache_render_dict(workflow),
    }
    assert _render_cache_for_hash(config, shared) is None


# --- Pre-dispatch strip vs hash byte-identity (DD#19) ----------------------


def test_pre_dispatch_strip_does_not_mutate_text_bytes() -> None:
    """The runtime pre-dispatch strip removes ``cache_control`` markers
    when rendered content is below the provider minimum, but it must NOT
    mutate the underlying text content of any block. Text bytes are what
    flow into ``compute_node_config(prompt_cache_content=...)`` via the
    hash-side render — preserving them is what makes DD#19 byte-identity
    invariant to whether the strip ultimately fires for any given call.
    """
    from pflow.nodes.llm.llm import _strip_below_min_cache_markers

    def _blocks() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        system = [
            {"type": "text", "text": "system instructions"},
            {"type": "text", "text": "cached chunk one"},
            {"type": "text", "text": "cached chunk two", "cache_control": {"type": "ephemeral"}},
        ]
        user = [
            {"type": "text", "text": "static prefix", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "dynamic suffix"},
        ]
        return system, user

    # Identical input; only the simulated token count differs across runs.
    sys_strip, user_strip = _blocks()
    sys_keep, user_keep = _blocks()

    # Run with token-count BELOW threshold via heuristic on tiny text
    # (each block is ~20 chars → ~5 tokens via len//4 heuristic; well under
    # any provider minimum). Force exception so the heuristic path fires
    # deterministically without depending on litellm.
    import pflow.core.litellm_runtime as litellm_runtime

    class _BoomLitellm:
        def token_counter(self, **_: Any) -> int:
            raise RuntimeError("simulated")

    original_import = litellm_runtime.import_litellm
    try:
        litellm_runtime.import_litellm = lambda: _BoomLitellm()  # type: ignore[assignment]
        result_strip = _strip_below_min_cache_markers(
            system_blocks=sys_strip,
            user_message_blocks=user_strip,
            model="anthropic/claude-sonnet-4-5",  # 1024 min
        )
        # And a no-strip baseline by passing an unknown model with content
        # that has been pre-counted above-threshold via large text payload.
        sys_keep[-1]["text"] = "x" * 32_000  # 8k+ tokens via heuristic
        result_keep = _strip_below_min_cache_markers(
            system_blocks=sys_keep,
            user_message_blocks=user_keep,
            model="anthropic/claude-sonnet-4-5",
        )
    finally:
        litellm_runtime.import_litellm = original_import  # type: ignore[assignment]

    assert result_strip is not None, "strip should have fired on tiny content"
    assert result_keep is None, "strip should not fire on large content"

    # Text bytes are identical for blocks-1 (system instructions), blocks-2
    # (cached chunk one), and user block 2 (dynamic suffix). The cache_control
    # keys differ but the ``text`` values must be byte-identical.
    assert sys_strip[0]["text"] == sys_keep[0]["text"] == "system instructions"
    assert sys_strip[1]["text"] == sys_keep[1]["text"] == "cached chunk one"
    assert sys_strip[2]["text"] == "cached chunk two"  # text preserved
    assert "cache_control" not in sys_strip[2]  # marker stripped
    assert "cache_control" in sys_keep[2]  # marker preserved
    assert user_strip[0]["text"] == "static prefix"  # text preserved
    assert "cache_control" not in user_strip[0]  # marker stripped
    assert user_strip[1]["text"] == user_keep[1]["text"] == "dynamic suffix"
