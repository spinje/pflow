"""Tests for Task 159 B3.2: ``build_cache_render_dict`` + engine save/restore.

Covers:
- Unit tests for the ``build_cache_render_dict`` builder against synthetic
  ``CompiledWorkflow`` objects.
- Integration tests for the engine boundary save/restore semantics:
  pre-installed values are restored on exit; restore-from-absent writes
  ``_EMPTY_CACHE_RENDER`` (a frozen empty proxy), never ``None``.
- Sub-workflow isolation: a parent's value is masked during child execution
  and reinstated on exit. Captured via a ``BaseNode.prep`` monkeypatch.
- Read-only invariants: ``MappingProxyType`` rejects mutation; the
  ``CacheRenderContext`` dataclass is frozen.
"""

from __future__ import annotations

import dataclasses
from types import MappingProxyType
from typing import Any

import pytest

from pflow.core.cache_render import CacheBlockIR, CacheChunkIR, CacheRenderContext
from pflow.core.markdown_parser import parse_markdown
from pflow.registry.registry import Registry
from pflow.runtime.compilation.compiler import compile_workflow
from pflow.runtime.engine.engine import (
    _EMPTY_CACHE_RENDER,
    WorkflowEngine,
    build_cache_render_dict,
)
from pflow.runtime.engine.types import BatchConfig, CompiledWorkflow, NodeConfig, TemplateConfig

# --- Builder unit tests ----------------------------------------------------


def _make_node_config(
    node_id: str,
    node_type_name: str,
    *,
    prompt_cache_items: tuple[str, ...] = (),
    prewarm: bool = False,
) -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        node_type_name=node_type_name,
        template_config=None,
        batch_config=None,
        namespaced=True,
        interface_metadata=None,
        prompt_cache_items=prompt_cache_items,
        prewarm=prewarm,
    )


def _make_prewarm_llm_config(prompt: str) -> NodeConfig:
    return NodeConfig(
        node_id="score",
        node_type_name="LLMNode",
        template_config=TemplateConfig(
            template_params={"prompt": prompt},
            static_params={"model": "anthropic/claude-sonnet-4-5"},
            expected_types={},
            resolution_mode="strict",
        ),
        batch_config=BatchConfig(items_template="${items}", item_alias="item"),
        namespaced=True,
        interface_metadata=None,
        prewarm=True,
    )


def _make_workflow(
    configs: dict[str, NodeConfig],
    *,
    cache_block: CacheBlockIR | None = None,
) -> CompiledWorkflow:
    return CompiledWorkflow(
        start_node=None,
        node_configs=configs,
        cache_block=cache_block,
    )


def _simple_block(*chunk_names: str) -> CacheBlockIR:
    return CacheBlockIR(
        ttl=None,
        items=tuple(CacheChunkIR(name=n, var_expr=n, prose_before="", source_line=0) for n in chunk_names),
        source_line=0,
    )


def test_builder_includes_llm_node_with_subset() -> None:
    workflow = _make_workflow(
        {"a": _make_node_config("a", "LLMNode", prompt_cache_items=("concept",))},
    )
    out = build_cache_render_dict(workflow, {})
    assert set(out.keys()) == {"a"}
    assert out["a"].subset == ("concept",)
    assert out["a"].prewarm is False
    assert out["a"].cache_block is None


def test_builder_includes_llm_node_with_prewarm() -> None:
    workflow = _make_workflow(
        {"a": _make_node_config("a", "LLMNode", prewarm=True)},
    )
    out = build_cache_render_dict(workflow, {})
    assert "a" in out
    assert out["a"].prewarm is True


def test_builder_includes_llm_node_when_workflow_has_cache_block() -> None:
    """Even an LLM node with no per-node prompt_cache: gets a context if
    the workflow declares ``## Cache`` — so the renderer can see it."""
    block = _simple_block("concept")
    workflow = _make_workflow(
        {"a": _make_node_config("a", "LLMNode")},
        cache_block=block,
    )
    out = build_cache_render_dict(workflow, {})
    assert "a" in out
    assert out["a"].cache_block is block
    assert out["a"].subset == ()


def test_builder_excludes_non_llm_nodes() -> None:
    workflow = _make_workflow(
        {
            "shell1": _make_node_config("shell1", "ShellNode"),
            "http1": _make_node_config("http1", "HttpNode", prompt_cache_items=("x",)),
            "llm1": _make_node_config("llm1", "LLMNode", prompt_cache_items=("x",)),
        },
        cache_block=_simple_block("x"),
    )
    out = build_cache_render_dict(workflow, {})
    assert set(out.keys()) == {"llm1"}


def test_builder_excludes_llm_without_any_cache_state() -> None:
    """LLM node with empty subset, prewarm=False, no workflow cache_block: skip."""
    workflow = _make_workflow(
        {"a": _make_node_config("a", "LLMNode")},
    )
    assert build_cache_render_dict(workflow, {}) == {}


def test_builder_returns_plain_dict_not_proxy() -> None:
    """The builder yields a dict; the engine wraps it in ``MappingProxyType``
    at install time. Keeping the wrap responsibility at the call site means
    the builder is testable without proxy machinery."""
    workflow = _make_workflow(
        {"a": _make_node_config("a", "LLMNode", prompt_cache_items=("x",))},
    )
    out = build_cache_render_dict(workflow, {})
    assert isinstance(out, dict)


def test_builder_disables_prewarm_when_static_prefix_below_min(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pflow.core.cache_analysis.token_estimation.estimate_tokens",
        lambda model, text: (10, "test"),
    )
    workflow = _make_workflow({"score": _make_prewarm_llm_config("short prefix ${item.text}")})
    shared: dict[str, Any] = {"items": [{"text": "a"}, {"text": "b"}], "_pflow_workflow_file": "wf.pflow.md"}

    out = build_cache_render_dict(workflow, shared)

    assert out["score"].prewarm is False
    warning = shared["__warnings__"]["score"]
    assert warning.id == "cache.prewarm-disabled-below-min"
    assert shared["__prewarm_disabled_below_min__"]["score"] == "below_min"


def test_builder_keeps_prewarm_when_static_prefix_clears_min(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pflow.core.cache_analysis.token_estimation.estimate_tokens",
        lambda model, text: (2_000, "test"),
    )
    workflow = _make_workflow({"score": _make_prewarm_llm_config("long prefix ${item.text}")})
    shared: dict[str, Any] = {"items": [{"text": "a"}, {"text": "b"}]}

    out = build_cache_render_dict(workflow, shared)

    assert out["score"].prewarm is True
    assert "__warnings__" not in shared
    assert "__prewarm_disabled_below_min__" not in shared


# --- Integration tests: engine save/restore --------------------------------


_MINIMAL_WORKFLOW = """
# Tiny

## Steps

### hello

Print a greeting.

- type: shell

```shell command
echo hi
```
"""


def _compile_minimal(registry: Registry) -> CompiledWorkflow:
    ir = parse_markdown(_MINIMAL_WORKFLOW).ir
    return compile_workflow(ir, registry)


def test_save_restore_round_trip_preserves_pre_existing_value() -> None:
    """Pre-install a sentinel value; engine.run must restore it on exit."""
    registry = Registry()
    workflow = _compile_minimal(registry)
    sentinel: Any = MappingProxyType({"sentinel": object()})  # type: ignore[var-annotated]
    shared: dict[str, Any] = {"__pflow_cache_render__": sentinel}
    WorkflowEngine().run(workflow, shared)
    assert shared["__pflow_cache_render__"] is sentinel


def test_restore_from_absent_writes_empty_proxy_not_none() -> None:
    """When the parent had no value, restore writes ``_EMPTY_CACHE_RENDER``
    so a future consumer that drops the ``or {}`` defense doesn't hit
    ``None.get(...)``."""
    registry = Registry()
    workflow = _compile_minimal(registry)
    shared: dict[str, Any] = {}  # no pre-existing key
    WorkflowEngine().run(workflow, shared)
    restored = shared["__pflow_cache_render__"]
    assert restored is _EMPTY_CACHE_RENDER
    assert isinstance(restored, MappingProxyType)
    assert dict(restored) == {}
    assert restored is not None  # explicit — the load-bearing invariant


def test_dict_is_installed_during_run() -> None:
    """During execution, ``shared["__pflow_cache_render__"]`` is a Mapping.
    Captured via a ``ShellNode.prep`` monkeypatch — leaf classes override
    ``prep``, so a ``BaseNode.prep`` patch would not fire (CPython MRO finds
    the subclass override first)."""
    from pflow.nodes.shell.shell import ShellNode

    captured: list[Any] = []
    original_prep = ShellNode.prep

    def capturing_prep(self: ShellNode, shared: dict[str, Any]) -> Any:
        captured.append(shared.get("__pflow_cache_render__"))
        return original_prep(self, shared)

    registry = Registry()
    workflow = _compile_minimal(registry)
    ShellNode.prep = capturing_prep  # type: ignore[method-assign]
    try:
        WorkflowEngine().run(workflow, {})
    finally:
        ShellNode.prep = original_prep  # type: ignore[method-assign]

    assert captured, "prep was never invoked"
    for entry in captured:
        assert isinstance(entry, MappingProxyType)


# --- Read-only invariants --------------------------------------------------


def test_outer_dict_is_read_only() -> None:
    """``MappingProxyType`` raises ``TypeError`` on mutation — protects the
    parallel-batch concurrency surface."""
    registry = Registry()
    workflow = _compile_minimal(registry)
    shared: dict[str, Any] = {}
    WorkflowEngine().run(workflow, shared)
    proxy = shared["__pflow_cache_render__"]
    with pytest.raises(TypeError):
        proxy["new_node"] = object()  # type: ignore[index]


def test_cache_render_context_is_frozen() -> None:
    """``CacheRenderContext`` mutation raises ``FrozenInstanceError`` — both
    the outer mapping AND the per-node values are mutation-proof."""
    block = _simple_block("x")
    ctx = CacheRenderContext(
        cache_block=block,
        subset=("x",),
        prewarm=False,
        unresolved_batch_prompt=None,
        batch_alias=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.prewarm = True  # type: ignore[misc]
    # ``replace`` works because ``frozen=True`` is the only constraint.
    new = dataclasses.replace(ctx, prewarm=True)
    assert new.prewarm is True
    assert ctx.prewarm is False


# --- Sub-workflow isolation ------------------------------------------------


_PARENT_PFLOW = """
# Parent

## Inputs

### text

Text to pass through.

- type: string
- required: false
- default: hi

## Steps

### sub

Invoke the child workflow.

- type: workflow
- workflow: ./child.pflow.md
- inputs:
    text: ${text}
"""

_CHILD_PFLOW = """
# Child

## Inputs

### text

Text input.

- type: string
- required: true

## Steps

### echo

Echo the input text.

- type: shell

```shell command
echo "${text}"
```
"""


def test_subworkflow_isolation_via_monkeypatch(tmp_path: Any) -> None:
    """Parent installs its own (synthetic) value; the child engine.run must
    mask it during child execution and restore on exit. Captures via a
    ``ShellNode.prep`` monkeypatch on the child's shell node — this works at
    B3.2 because we read ``shared`` directly, not via ``LLMNode.prep``
    (which is C1.2)."""
    from pflow.nodes.shell.shell import ShellNode

    parent_path = tmp_path / "parent.pflow.md"
    parent_path.write_text(_PARENT_PFLOW)
    child_path = tmp_path / "child.pflow.md"
    child_path.write_text(_CHILD_PFLOW)

    captured: list[tuple[str, Any]] = []
    original_prep = ShellNode.prep

    def capturing_prep(self: ShellNode, shared: dict[str, Any]) -> Any:
        node_id = getattr(self, "node_id", "<unknown>")
        captured.append((node_id, shared.get("__pflow_cache_render__")))
        return original_prep(self, shared)

    parent_initial: Any = MappingProxyType({"sentinel-key": object()})  # type: ignore[var-annotated]
    # Seed parent input, the sentinel, and the workflow-file path so the
    # child workflow resolves relative to ``tmp_path`` (not the test cwd).
    shared: dict[str, Any] = {
        "text": "hi",
        "_pflow_workflow_file": str(parent_path),
        "__pflow_cache_render__": parent_initial,
    }

    registry = Registry()
    ir = parse_markdown(_PARENT_PFLOW).ir
    workflow = compile_workflow(
        ir,
        registry,
        initial_params={"_pflow_workflow_file": str(parent_path), "text": "hi"},
    )

    ShellNode.prep = capturing_prep  # type: ignore[method-assign]
    try:
        WorkflowEngine().run(workflow, shared)
    finally:
        ShellNode.prep = original_prep  # type: ignore[method-assign]

    # Parent's pre-installed value is restored after the run completes.
    assert shared["__pflow_cache_render__"] is parent_initial

    # During child execution the child's shell node saw the proxy the child
    # engine built from its OWN compiled workflow — NOT the parent's sentinel.
    # Compare contents against a freshly-built proxy from
    # ``build_cache_render_dict(child_workflow, {})``: the child workflow has no
    # LLM node and no ``## Cache`` block, so the dict must be empty (sparse
    # by design — see build_cache_render_dict's docstring).
    child_ir = parse_markdown(_CHILD_PFLOW).ir
    child_workflow = compile_workflow(
        child_ir,
        registry,
        initial_params={"text": "hi"},
    )
    expected_child_render = build_cache_render_dict(child_workflow, {})
    assert dict(expected_child_render) == {}, (
        "production builder must produce an empty dict for the child shape — test invariant broken if this fails"
    )

    child_captures = [val for nid, val in captured if nid == "echo"]
    assert child_captures, "child shell node prep never captured"
    for child_value in child_captures:
        # Both child and parent install proxies, never None.
        assert isinstance(child_value, MappingProxyType)
        # The child saw a proxy whose CONTENTS match what its own
        # ``build_cache_render_dict`` produces — proves the install path is
        # `MappingProxyType(build_cache_render_dict(child_workflow, {}))` and
        # NOT a leaked parent value.
        assert dict(child_value) == dict(expected_child_render), (
            "child saw a __pflow_cache_render__ that doesn't match its own "
            f"build_cache_render_dict output: got {dict(child_value)!r}"
        )
