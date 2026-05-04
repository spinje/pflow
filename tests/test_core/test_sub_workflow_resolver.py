"""Tests for resolve_sub_workflow() — the shared sub-workflow resolver.

Covers all three resolution modes (inline IR, file reference, saved name),
template/empty returns None, and error cases (missing base_path, file not
found, parse error, missing Steps section).
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from pflow.core.exceptions import MarkdownParseError
from pflow.core.workflow.sub_workflow_resolver import resolve_sub_workflow
from tests.shared.markdown_utils import write_workflow_file
from tests.shared.mutation_contract import mutation_contract

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_CHILD_IR = {
    "nodes": [
        {
            "id": "greet",
            "type": "shell",
            "purpose": "Greets the user via shell.",
            "params": {"command": "echo hello"},
        }
    ],
}


def _write_valid_child(path: Path) -> None:
    """Write a minimal valid .pflow.md child workflow to *path*."""
    write_workflow_file(_MINIMAL_CHILD_IR, path, title="Child Workflow")


# ---------------------------------------------------------------------------
# 1. File reference
# ---------------------------------------------------------------------------


def test_file_reference(tmp_path: Path) -> None:
    """When params contain a workflow file path, resolve and parse the file."""
    child_path = tmp_path / "child.pflow.md"
    _write_valid_child(child_path)

    result = resolve_sub_workflow(
        {"workflow": str(child_path)},
        base_path=tmp_path,
    )

    assert result is not None
    assert "nodes" in result.ir
    assert result.ir["nodes"][0]["id"] == "greet"
    assert result.path == child_path.resolve()
    assert isinstance(result.warnings, tuple)


# ---------------------------------------------------------------------------
# 3. Saved workflow name
# ---------------------------------------------------------------------------


def test_saved_name() -> None:
    """When params contain a plain name (no path indicators), resolve via
    WorkflowManager.  We mock WorkflowManager to avoid needing a real
    saved workflow on disk."""
    from pflow.core.workflow.manager import WorkflowManager

    saved_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "step",
                "type": "shell",
                "params": {"command": "echo saved"},
            }
        ],
    }

    with (
        patch.object(WorkflowManager, "load_ir", return_value=saved_ir),
        patch.object(WorkflowManager, "get_path", return_value=None),
    ):
        result = resolve_sub_workflow({"workflow": "my-helper"})

    assert result is not None
    assert result.ir is saved_ir
    assert result.path is None


# ---------------------------------------------------------------------------
# 4. Template reference returns None
# ---------------------------------------------------------------------------


def test_template_reference_returns_none() -> None:
    """Template refs like ${dynamic} cannot be resolved statically."""
    result = resolve_sub_workflow({"workflow": "${dynamic}"})
    assert result is None


# ---------------------------------------------------------------------------
# 5. Empty workflow params returns None
# ---------------------------------------------------------------------------


def test_empty_workflow_returns_none() -> None:
    """When params have neither workflow nor workflow_ir, return None."""
    assert resolve_sub_workflow({}) is None
    assert resolve_sub_workflow({"other_key": "value"}) is None


# ---------------------------------------------------------------------------
# 6. Relative path resolves against base_path
# ---------------------------------------------------------------------------


def test_relative_path_resolves_against_base(tmp_path: Path) -> None:
    """A relative workflow path should resolve against the provided base_path."""
    child_path = tmp_path / "child.pflow.md"
    _write_valid_child(child_path)

    result = resolve_sub_workflow(
        {"workflow": "./child.pflow.md"},
        base_path=tmp_path,
    )

    assert result is not None
    assert result.path == child_path.resolve()
    assert "nodes" in result.ir


# ---------------------------------------------------------------------------
# 7. Relative path without base_path raises ValueError
# ---------------------------------------------------------------------------


def test_relative_path_no_base_raises() -> None:
    """A relative path with no base_path should raise ValueError."""
    with pytest.raises(ValueError, match="Cannot resolve relative"):
        resolve_sub_workflow({"workflow": "./child.pflow.md"}, base_path=None)


# ---------------------------------------------------------------------------
# 8. Non-existent file raises FileNotFoundError
# ---------------------------------------------------------------------------


def test_file_not_found_raises(tmp_path: Path) -> None:
    """An absolute path to a non-existent file should raise FileNotFoundError."""
    missing = tmp_path / "does-not-exist.pflow.md"
    with pytest.raises(FileNotFoundError, match="not found"):
        resolve_sub_workflow({"workflow": str(missing)}, base_path=tmp_path)


# ---------------------------------------------------------------------------
# 9. Parse error propagates as MarkdownParseError
# ---------------------------------------------------------------------------


def test_parse_error_propagates(tmp_path: Path) -> None:
    """Malformed markdown content should raise MarkdownParseError."""
    bad_file = tmp_path / "bad.pflow.md"
    # Unclosed code fence triggers a parse error
    bad_file.write_text(
        "# Bad Workflow\n\nBroken content.\n\n## Steps\n\n### step\n\n"
        "Step description here.\n\n- type: shell\n\n```shell command\necho hello\n",
        encoding="utf-8",
    )

    with pytest.raises(MarkdownParseError):
        resolve_sub_workflow({"workflow": str(bad_file)}, base_path=tmp_path)


# ---------------------------------------------------------------------------
# 10. Missing Steps section raises ValueError
# ---------------------------------------------------------------------------


def test_missing_nodes_section_raises(tmp_path: Path) -> None:
    """A file without ## Steps raises MarkdownParseError from the parser.

    The parser validates structural requirements before the resolver's
    own 'nodes' key check, so the error comes as MarkdownParseError
    with a message about the missing Steps section.
    """
    no_steps = tmp_path / "no-steps.pflow.md"
    no_steps.write_text(
        "# No Steps Workflow\n\nA workflow with no steps section.\n",
        encoding="utf-8",
    )

    with pytest.raises(MarkdownParseError, match="Steps"):
        resolve_sub_workflow({"workflow": str(no_steps)}, base_path=tmp_path)


# ---------------------------------------------------------------------------
# 11. Boundary contract — file resolution at the primitive
# ---------------------------------------------------------------------------
#
# Mirrors ``tests/test_execution/test_workflow_resolver_contract.py`` for
# Path 1 (root workflow boundary). These tests lock the architectural
# extension to the sub-workflow load primitive: child IRs are fully
# file-resolved before being returned, so cross-workflow consumers
# (cache analyzer's value-flow walker, future graph features) operate
# on a single canonical IR shape.
#
# REGRESSION GATE: a child workflow with ``prompt: ./*.prompt.md`` had
# its ``${concept.X}`` references silently invisible to the cross-workflow
# walker before the boundary contract was extended here. Tests that
# construct synthetic inline-prompt children passed; production workflows
# using the documented external-prompt-file pattern lost cross-boundary
# detection. Without these tests, that regression class re-emerges
# silently.


def test_resolve_sub_workflow_returns_fully_file_resolved_ir(tmp_path: Path) -> None:
    """``resolve_sub_workflow().ir`` has no unresolved ``./*.md`` references.

    Load-bearing structural defense for the boundary contract documented in
    ``sub_workflow_resolver.py``'s module docstring. If a future contributor
    moves file resolution back to a consumer (cache analyzer, validator,
    compiler, a new tool), this test fails — the child IR returned by the
    primitive must already be resolved.
    """
    from pflow.core.file_resolver import FILE_RESOLVABLE_PARAMS, is_file_reference

    # External prompt file referenced by the child workflow.
    prompt_file = tmp_path / "child.prompt.md"
    prompt_content = "Process this value: ${shared_value}\n\nBe concise."
    prompt_file.write_text(prompt_content, encoding="utf-8")

    # Child workflow that uses the file reference.
    child = tmp_path / "child.pflow.md"
    child.write_text(
        """# Child Workflow

External-prompt child for boundary-contract testing.

## Inputs

### shared_value

The shared value flowing in from the parent.

- type: string

## Steps

### consume

Calls the LLM with an external prompt file.

- type: llm
- prompt: ./child.prompt.md
""",
        encoding="utf-8",
    )

    result = resolve_sub_workflow({"workflow": str(child)}, base_path=tmp_path)
    assert result is not None

    # Walk every file-resolvable param in the returned child IR. None
    # should still look like a file reference.
    unresolved = []
    for node in result.ir.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", "?"))
        params = node.get("params", {})
        if not isinstance(params, dict):
            continue
        for key, value in params.items():
            if key in FILE_RESOLVABLE_PARAMS and isinstance(value, str) and is_file_reference(value):
                unresolved.append(f"node={node_id!r} param={key!r} value={value!r}")

    assert not unresolved, (
        "SubWorkflowResult.ir contains unresolved file references. "
        "resolve_sub_workflow() should have inlined them at the boundary. "
        "If a consumer (cross-workflow walker, validator, compiler, etc.) "
        "is calling resolve_file_references() on this IR, that's the bug — "
        "the resolution should happen ONCE at the primitive, not at every "
        "consumer. See sub_workflow_resolver.py module docstring.\n"
        f"Unresolved references: {unresolved}"
    )

    # Positive control — the prompt content must be inlined.
    consume = next(n for n in result.ir["nodes"] if n["id"] == "consume")
    assert prompt_content in consume["params"]["prompt"], (
        "External prompt content was not inlined into the child IR. "
        "resolve_sub_workflow() should read ./child.prompt.md and "
        "substitute its content into params['prompt']."
    )


@mutation_contract(
    file="src/pflow/core/workflow/sub_workflow_resolver.py",
    line=163,
    revert="ir = _resolve_file_refs_at_boundary(result.ir, resolved)",
    expected_failure="boundary file resolution skipped — child prompt stays as the file-path string",
)
def test_resolve_sub_workflow_cross_workflow_walker_sees_resolved_prompts(tmp_path: Path) -> None:
    """End-to-end gate: cross-workflow walker via the primitive sees inlined prompts.

    Production-shape regression gate that the existing synthetic-IR walker
    tests can't catch. Pre-fix, the cross-workflow walker stored unresolved
    child IRs in ``irs_by_workflow``; ``_count_llm_nodes_referencing_path``
    saw the file-path string instead of the prompt content; cross-boundary
    findings to file-ref children silently dropped to zero on every
    real-world workflow that follows the documented external-prompt-file
    pattern.

    Mutation contract: revert the boundary call in ``_resolve_from_file``;
    this test fails because the child IR's prompt stays as
    ``"./child.prompt.md"`` (24 chars) instead of the inlined content.
    """
    from pflow.core.cache_analysis.analyze import _count_llm_nodes_referencing_path
    from pflow.core.cache_analysis.cross_workflow import walk_cross_workflow
    from pflow.execution.workflow_resolver import resolve_workflow

    # Child workflow with external prompt that template-references shared_value.
    prompt_file = tmp_path / "child.prompt.md"
    prompt_file.write_text(
        "Process this value carefully: ${shared_value}\n\nBe specific.",
        encoding="utf-8",
    )
    (tmp_path / "child.pflow.md").write_text(
        """# Child

External-prompt child for cross-workflow walker test.

## Inputs

### shared_value

The shared value.

- type: string

## Steps

### consume

LLM that consumes the shared value via an external prompt file.

- type: llm
- prompt: ./child.prompt.md
""",
        encoding="utf-8",
    )

    # Parent that passes shared_value into the child.
    parent_path = tmp_path / "parent.pflow.md"
    parent_path.write_text(
        """# Parent

Tests cross-workflow walker visibility into file-ref child prompts.

## Inputs

### shared_value

The shared value.

- type: string

## Steps

### branch

Invokes the child sub-workflow.

- type: workflow
- workflow: ./child.pflow.md
- inputs:
    shared_value: ${shared_value}
""",
        encoding="utf-8",
    )

    resolved = resolve_workflow(str(parent_path))
    result = walk_cross_workflow(resolved.ir, base_path=tmp_path, root_workflow_path=str(parent_path))

    # The walker has the child IR loaded via resolve_sub_workflow. Its
    # prompts must be FILE-RESOLVED so analyzer queries see template refs.
    assert len(result.edges) == 1
    edge = result.edges[0]
    child_ir = result.irs_by_workflow.get(edge.child_workflow, {})
    consumers = _count_llm_nodes_referencing_path(child_ir, edge.child_input_name)
    assert consumers == 1, (
        "Cross-workflow walker child IR is not file-resolved. "
        "_count_llm_nodes_referencing_path returned 0 because the LLM "
        "node's prompt is still the literal './child.prompt.md' string "
        "instead of the inlined content with its ${shared_value} reference. "
        "This regression silently dropped every cross-boundary finding on "
        "real workflows using the recommended external-prompt-file pattern. "
        "Fix lives at sub_workflow_resolver.py::_resolve_file_refs_at_boundary."
    )
