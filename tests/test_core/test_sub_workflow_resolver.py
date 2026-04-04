"""Tests for resolve_sub_workflow() — the shared sub-workflow resolver.

Covers all three resolution modes (inline IR, file reference, saved name),
template/empty returns None, and error cases (missing base_path, file not
found, parse error, missing Steps section).
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from pflow.core.exceptions import MarkdownParseError
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult, resolve_sub_workflow
from tests.shared.markdown_utils import write_workflow_file

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
# 1. Inline IR dict
# ---------------------------------------------------------------------------


def test_inline_ir() -> None:
    """When params contain workflow_ir dict, return it directly with
    path=None and empty warnings tuple."""
    inline_ir = {"nodes": [{"id": "a", "type": "shell", "params": {}}]}
    result = resolve_sub_workflow({"workflow_ir": inline_ir})

    assert isinstance(result, SubWorkflowResult)
    assert result.ir is inline_ir
    assert result.path is None
    assert result.warnings == ()


# ---------------------------------------------------------------------------
# 2. File reference
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
