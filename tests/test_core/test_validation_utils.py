"""Tests for validation utilities."""

from pathlib import Path

import pytest

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.exceptions import WorkflowValidationError
from pflow.core.validation_utils import get_parameter_validation_error, is_valid_parameter_name


def test_valid_parameter_names():
    """Test that valid parameter names are accepted."""
    # Traditional Python identifiers
    assert is_valid_parameter_name("my_var")
    assert is_valid_parameter_name("MyVar")
    assert is_valid_parameter_name("_private")
    assert is_valid_parameter_name("var123")

    # Now also valid: hyphens
    assert is_valid_parameter_name("my-var")
    assert is_valid_parameter_name("api-key")
    assert is_valid_parameter_name("user-name")

    # Now also valid: dots
    assert is_valid_parameter_name("file.path")
    assert is_valid_parameter_name("data.field")
    assert is_valid_parameter_name("config.setting.value")

    # Now also valid: numbers at start
    assert is_valid_parameter_name("123start")
    assert is_valid_parameter_name("2fa-token")
    assert is_valid_parameter_name("1st-place")

    # Complex but valid
    assert is_valid_parameter_name("my-complex.param-123")

    # Single/double underscores that are NOT reserved (only __X__ is reserved)
    assert is_valid_parameter_name("_private")
    assert is_valid_parameter_name("__double_leading")
    assert is_valid_parameter_name("trailing__")


def test_invalid_parameter_names():
    """Test that invalid parameter names are rejected."""
    # Empty or whitespace
    assert not is_valid_parameter_name("")
    assert not is_valid_parameter_name("  ")
    assert not is_valid_parameter_name("\t")

    # Spaces and tabs (NEW: these break CLI parsing and template regex)
    assert not is_valid_parameter_name("api key")  # Space in middle
    assert not is_valid_parameter_name("my param")  # Space in middle
    assert not is_valid_parameter_name("tab\there")  # Tab in middle
    assert not is_valid_parameter_name(" leading")  # Leading space (caught by strip)
    assert not is_valid_parameter_name("trailing ")  # Trailing space (caught by strip)

    # Shell special characters
    assert not is_valid_parameter_name("my$var")  # Dollar sign
    assert not is_valid_parameter_name("cmd|pipe")  # Pipe
    assert not is_valid_parameter_name("out>file")  # Redirect
    assert not is_valid_parameter_name("in<file")  # Redirect
    assert not is_valid_parameter_name("cmd&bg")  # Background
    assert not is_valid_parameter_name("cmd;next")  # Command separator
    assert not is_valid_parameter_name("cmd`sub`")  # Backticks

    # Control characters
    assert not is_valid_parameter_name("line\nbreak")
    assert not is_valid_parameter_name("carriage\rreturn")
    assert not is_valid_parameter_name("null\0char")

    # Quotes and backslash
    assert not is_valid_parameter_name('my"var')
    assert not is_valid_parameter_name("my'var")
    assert not is_valid_parameter_name("my\\var")

    # Reserved double-underscore names (bypass NamespacedSharedStore)
    assert not is_valid_parameter_name("__execution__")
    assert not is_valid_parameter_name("__failures__")
    assert not is_valid_parameter_name("__warnings__")
    assert not is_valid_parameter_name("__custom__")


def test_parameter_validation_error_messages():
    """Test that error messages are descriptive."""
    # Empty string
    error = get_parameter_validation_error("", "input")
    assert "cannot be empty" in error

    # Spaces (with helpful suggestion)
    error = get_parameter_validation_error("api key", "input")
    assert "cannot contain spaces" in error
    assert "use hyphens or underscores instead" in error

    # Tabs
    error = get_parameter_validation_error("tab\there", "output")
    assert "cannot contain tabs" in error

    # Dollar sign
    error = get_parameter_validation_error("my$var", "input")
    assert "$" in error
    assert "template syntax" in error

    # Shell characters
    error = get_parameter_validation_error("cmd|pipe", "output")
    assert "shell special characters" in error

    # Control characters
    error = get_parameter_validation_error("line\nbreak", "parameter")
    assert "control characters" in error

    # Quotes
    error = get_parameter_validation_error('"quoted"', "input")
    assert "quotes" in error

    # Reserved dunder names
    error = get_parameter_validation_error("__execution__", "input")
    assert "reserved" in error


# ---------------------------------------------------------------------------
# Placeholder-input validation: every entry point gets the same verdict (#643)
# ---------------------------------------------------------------------------

_CHILD_MD = """# Child

Child workflow.

## Outputs

### result

The result.

- type: string
- source: ${make.stdout}

## Steps

### make

Emit a value.

- type: shell

```shell command
echo hi
```
"""

_PARENT_MD = """# Parent

Parent reads a child output that does not exist.

## Steps

### sub

Call the child.

- type: workflow
- workflow: ./child.pflow.md

### show

Show the child output.

- type: shell

```shell command
echo ${sub.reslt}
```
"""


@pytest.fixture
def parent_with_typo_from_foreign_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A parent reading ``${sub.reslt}`` from a relative child, with cwd elsewhere.

    The cwd holds no ``child.pflow.md``, so any entry point that resolves the
    relative child against cwd instead of the parent's directory cannot see the
    child's outputs and waves the typo through.
    """
    workflow_dir = tmp_path / "wf"
    workflow_dir.mkdir()
    (workflow_dir / "child.pflow.md").write_text(_CHILD_MD, encoding="utf-8")
    parent = workflow_dir / "parent.pflow.md"
    parent.write_text(_PARENT_MD, encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return parent


def _error_messages(diagnostics: list[Diagnostic]) -> list[str]:
    return [d.message for d in diagnostics if d.severity == Severity.ERROR and "reslt" in d.message]


def test_save_and_validate_only_agree_on_relative_child_outputs(parent_with_typo_from_foreign_cwd: Path) -> None:
    """``pflow save`` must reject what ``--validate-only`` rejects, whatever the cwd."""
    from pflow.core.workflow.save_service import save_workflow_with_options
    from pflow.execution.runner import WorkflowRunner

    parent = parent_with_typo_from_foreign_cwd
    validate_only = WorkflowRunner().validate(str(parent), {})
    expected = _error_messages(list(validate_only.diagnostics))
    assert expected, "validate-only should reject the typo'd child output"

    with pytest.raises(WorkflowValidationError) as exc_info:
        save_workflow_with_options("typo-parent", parent.read_text(encoding="utf-8"), source_path=parent)

    assert _error_messages(list(exc_info.value.validation_errors)) == expected


def test_save_and_validate_only_accept_correct_relative_child_output(parent_with_typo_from_foreign_cwd: Path) -> None:
    """Positive control: the corrected ``${sub.result}`` passes both entry points from the same foreign cwd."""
    from pflow.core.workflow.save_service import save_workflow_with_options
    from pflow.execution.runner import WorkflowRunner

    parent = parent_with_typo_from_foreign_cwd
    parent.write_text(_PARENT_MD.replace("${sub.reslt}", "${sub.result}"), encoding="utf-8")

    assert WorkflowRunner().validate(str(parent), {}).valid
    saved_path, _, _ = save_workflow_with_options("good-parent", parent.read_text(encoding="utf-8"), source_path=parent)
    assert saved_path.exists()


def test_analyze_cache_agrees_with_validate_only_on_relative_child_outputs(
    parent_with_typo_from_foreign_cwd: Path,
) -> None:
    """``analyze-cache`` runs the same placeholder validation and reaches the same verdict."""
    from pflow.core.prompt_cache_analysis.analyze import analyze
    from pflow.execution.runner import WorkflowRunner
    from pflow.execution.workflow_resolver import resolve_workflow

    parent = parent_with_typo_from_foreign_cwd
    expected = _error_messages(list(WorkflowRunner().validate(str(parent), {}).diagnostics))
    assert expected

    # Same resolve + analyze() call shape as ``cli/commands/analyze_cache.py``.
    resolved = resolve_workflow(str(parent))
    result = analyze(
        resolved.ir,
        workflow_path=resolved.file_path,
        base_path=parent.parent,
        auto_load_trace=False,
        memo_cache=None,
    )

    assert _error_messages(list(result.warnings)) == expected
