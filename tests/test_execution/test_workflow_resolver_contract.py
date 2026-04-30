"""Contract tests for ``execution/workflow_resolver.py``.

These tests are the load-bearing structural defense that locks the architectural
contract documented on ``ResolvedWorkflow``: ``ResolvedWorkflow.ir`` is fully
resolved at the boundary, and consumers should never re-resolve.

If a future contributor re-introduces the "consumer applies file resolution"
pattern (which silently broke ``pflow analyze-cache`` on lyrics-generator
before this contract was made explicit), the structural test below fails.

Related architectural threads:

- GH #321 — output population + cycle detection (planner ↔ runtime duplication)
- GH #334 — per-item workflow resolution + compile cache (planner ↔ runtime)
- The third instance (this fix) — file resolution missing from analyzer

All three are symptoms of the same architectural pattern: shared work that
should live at an IR-construction boundary but instead is reimplemented at
every consumer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pflow.core.file_resolver import FILE_RESOLVABLE_PARAMS, is_file_reference
from pflow.execution.workflow_resolver import resolve_workflow


def _walk_resolvable_params(ir: dict) -> list[tuple[str, str, str]]:
    """Yield (node_id, param_key, param_value) for every file-resolvable string param."""
    out: list[tuple[str, str, str]] = []
    for node in ir.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", "?"))
        params = node.get("params", {})
        if not isinstance(params, dict):
            continue
        for key, value in params.items():
            if key in FILE_RESOLVABLE_PARAMS and isinstance(value, str):
                out.append((node_id, key, value))
    return out


def test_resolve_workflow_returns_fully_file_resolved_ir(tmp_path: Path) -> None:
    """``resolve_workflow()`` returns IR with no unresolved ``./*.md`` references.

    REGRESSION GATE — load-bearing. If a future contributor moves file
    resolution back to a consumer (compiler / runner / validator / analyzer /
    a new tool), this test fails because ``ResolvedWorkflow.ir`` would still
    contain literal ``./prompt.md`` strings in ``params`` of LLM nodes.

    The bug this guards against silently broke ``pflow analyze-cache`` on
    real workflows that use the documented external-prompt-file pattern
    (every prompt above ~1000 tokens, by convention).
    """
    # Build a minimal workflow with an external prompt file reference.
    prompt_file = tmp_path / "creative.prompt.md"
    prompt_content = "Write a creative response to: ${user_input}\n\nBe specific."
    prompt_file.write_text(prompt_content)

    workflow_path = tmp_path / "test.pflow.md"
    workflow_path.write_text(
        """# Test Workflow

Tests external prompt file resolution at the boundary.

## Inputs

### user_input

The input to feed the LLM.

- type: string
- required: true

## Steps

### llm-call

Call the LLM with the external prompt file.

- type: llm
- prompt: ./creative.prompt.md
"""
    )

    resolved = resolve_workflow(str(workflow_path))

    # Walk every file-resolvable param. None should look like an unresolved
    # file reference — they should all be inlined content.
    unresolved = []
    for node_id, key, value in _walk_resolvable_params(resolved.ir):
        if is_file_reference(value):
            unresolved.append(f"node={node_id!r} param={key!r} value={value!r}")

    assert not unresolved, (
        "ResolvedWorkflow.ir contains unresolved file references. "
        "resolve_workflow() should have inlined them at the boundary. "
        "If a consumer (compiler, runner, validator, analyzer, etc.) is "
        "calling resolve_file_references() on this IR, that's the bug — "
        "the resolution should happen ONCE at the boundary, not at every "
        "consumer. See execution/workflow_resolver.py module docstring "
        "and GH #321 / #334 for related architectural threads.\n"
        f"Unresolved references: {unresolved}"
    )

    # Positive control — the prompt content should be inlined.
    llm_node = next(n for n in resolved.ir["nodes"] if n["id"] == "llm-call")
    assert prompt_content in llm_node["params"]["prompt"], (
        "External prompt content was not inlined into the resolved IR. "
        "resolve_workflow() should read ./creative.prompt.md and substitute "
        "its content into params['prompt']."
    )


def test_resolve_workflow_skips_resolution_for_inline_dict_input() -> None:
    """Inline dict input has no base directory; resolution is skipped (correctly).

    Inline workflows can't have ``./file.md`` refs because there's no anchor
    for relative paths. ``_check_inline_file_references`` rejects file refs
    pre-resolution for ``source="content"`` and ``source="direct"`` paths.
    Confirms my fix didn't regress that defensive behavior.
    """
    ir = {
        "name": "inline",
        "version": "1.0",
        "inputs": {},
        "outputs": {},
        "nodes": [
            {"id": "echo", "type": "shell", "params": {"command": "echo hi"}},
        ],
        "edges": [],
    }
    resolved = resolve_workflow(ir)
    assert resolved.source == "direct"
    assert resolved.file_path is None
    # No resolution attempt on inline-with-no-file-refs — passes through.
    assert resolved.ir["nodes"][0]["params"]["command"] == "echo hi"


def test_resolve_workflow_rejects_inline_dict_with_file_references() -> None:
    """Defensive — inline workflows with file refs are rejected (no resolution anchor)."""
    ir = {
        "name": "inline-with-bad-ref",
        "version": "1.0",
        "inputs": {},
        "outputs": {},
        "nodes": [
            {"id": "llm", "type": "llm", "params": {"prompt": "./prompt.md"}},
        ],
        "edges": [],
    }
    with pytest.raises(ValueError, match="file references"):
        resolve_workflow(ir)


def test_resolve_workflow_raises_compilation_error_on_missing_file(tmp_path: Path) -> None:
    """Missing ``./file.md`` ref raises ``CompilationError`` at the boundary.

    Mirrors the wrap that the compiler used to do at compile-time.
    Existing exception-handling in runner.py / analyze_cache.py catches this
    via ``CompilationError`` (validate path) or via the broad
    ``except Exception`` (run / analyze paths).
    """
    from pflow.core.exceptions import CompilationError

    workflow_path = tmp_path / "broken.pflow.md"
    workflow_path.write_text(
        """# Broken

Tests CompilationError on missing prompt file.

## Steps

### llm

Calls an LLM with a prompt file that doesn't exist on disk.

- type: llm
- prompt: ./missing.prompt.md
"""
    )

    with pytest.raises(CompilationError, match="file_resolution|missing"):
        resolve_workflow(str(workflow_path))
