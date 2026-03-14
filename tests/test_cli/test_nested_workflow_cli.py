"""CLI end-to-end tests for nested workflow execution.

Validates that workflow-type nodes correctly execute child workflows,
pass inputs, resolve outputs, and handle error cases through the CLI.
"""

import sys
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

CHILD_WORKFLOW = """\
# To Uppercase

## Inputs

### text

The text to convert to uppercase.

- type: string

## Outputs

### result

The uppercased text result.

- source: ${transform.stdout}

## Steps

### transform

Convert text to uppercase using tr.

- type: shell
- command: echo "${text}" | tr '[:lower:]' '[:upper:]'
"""


def _make_parent_workflow(child_ref: str, pass_text: bool = True) -> str:
    """Build parent workflow markdown that calls a child workflow.

    Args:
        child_ref: Path or name of the child workflow file.
        pass_text: Whether to pass the 'text' input to the child.
    """
    text_param = "- text: ${title}\n" if pass_text else ""
    # When not passing text, still use ${title} in the show step so
    # the declared input is not flagged as unused by validation.
    show_cmd = "echo ${process.result}" if pass_text else "echo ${title}"
    return f"""\
# Parent

## Inputs

### title

The title to process.

- type: string

## Steps

### process

Process the title through a child workflow.

- type: workflow
- workflow: {child_ref}
{text_param}
### show

Show the final result.

- type: shell
- command: {show_cmd}
"""


def invoke_cli(args: list[str]) -> Any:
    """Invoke the pflow CLI by manipulating sys.argv (matches test_validate_only pattern).

    CliRunner cannot be used here because the main_wrapper pre-parses sys.argv
    for routing, and nested workflow execution needs real file I/O context.
    """
    from pflow.cli.main_wrapper import cli_main

    original_argv = sys.argv[:]
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    original_stdin = sys.stdin

    stdout_capture = StringIO()
    stderr_capture = StringIO()

    try:
        sys.argv = ["pflow", *args]
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture

        mock_stdin = StringIO("")
        mock_stdin.isatty = lambda: False  # type: ignore[assignment]
        sys.stdin = mock_stdin

        exit_code = 0
        try:
            cli_main()
        except SystemExit as e:
            exit_code = int(e.code) if e.code is not None else 0

        class Result:
            def __init__(self, exit_code: int, output: str, stderr: str) -> None:
                self.exit_code = exit_code
                self.output = output
                self.stderr = stderr

        return Result(exit_code, stdout_capture.getvalue(), stderr_capture.getvalue())

    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        sys.stdin = original_stdin


class TestNestedWorkflowCLI:
    """End-to-end CLI tests for nested workflow execution."""

    def test_nested_workflow_e2e(self, tmp_path: Path) -> None:
        """Nested workflow executes child and surfaces its output to parent."""
        child_file = tmp_path / "to-uppercase.pflow.md"
        child_file.write_text(CHILD_WORKFLOW)

        parent_file = tmp_path / "parent.pflow.md"
        parent_file.write_text(_make_parent_workflow(str(child_file)))

        result = invoke_cli([str(parent_file), "title=hello"])

        assert result.exit_code == 0, (
            f"Expected exit code 0, got {result.exit_code}\nstdout: {result.output}\nstderr: {result.stderr}"
        )
        combined = result.output + result.stderr
        assert "HELLO" in combined, (
            f"Expected 'HELLO' in combined output but got:\nstdout: {result.output!r}\nstderr: {result.stderr!r}"
        )

    def test_saved_workflow_with_relative_nested_child(self, tmp_path: Path) -> None:
        """Saved workflow resolves relative child paths from saved dir, not CWD.

        Regression test: when running `pflow my-saved-workflow`, the CLI must
        set _pflow_workflow_file from the saved workflow's path so that
        `workflow: ./child.pflow.md` resolves from ~/.pflow/workflows/, not CWD.
        """
        from pflow.core.workflow_manager import WorkflowManager

        # Create a temporary workflows dir to avoid polluting the real one
        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir()

        wm = WorkflowManager(workflows_dir=workflows_dir)

        # Save child workflow into the workflows dir
        child_file = workflows_dir / "child-upper.pflow.md"
        child_file.write_text(CHILD_WORKFLOW)

        # Save parent workflow that references child with relative path
        parent_content = _make_parent_workflow("./child-upper.pflow.md")
        wm.save("test-saved-nested", parent_content)

        # Patch WorkflowManager to use our tmp workflows dir
        with patch("pflow.core.workflow_manager.WorkflowManager") as mock_wm_class:
            mock_wm_class.return_value = wm

            # Also patch the WorkflowManager used in CLI setup
            with patch("pflow.cli.main.WorkflowManager", return_value=wm):
                result = invoke_cli(["test-saved-nested", "title=saved"])

        assert result.exit_code == 0, (
            f"Saved workflow with relative child failed (exit {result.exit_code})\n"
            f"stdout: {result.output}\nstderr: {result.stderr}"
        )
        combined = result.output + result.stderr
        assert "SAVED" in combined, (
            f"Expected 'SAVED' (uppercased) in output but got:\nstdout: {result.output!r}\nstderr: {result.stderr!r}"
        )

    def test_nested_workflow_validate_only(self, tmp_path: Path) -> None:
        """--validate-only accepts a valid nested workflow without executing it."""
        child_file = tmp_path / "to-uppercase.pflow.md"
        child_file.write_text(CHILD_WORKFLOW)

        parent_file = tmp_path / "parent.pflow.md"
        parent_file.write_text(_make_parent_workflow(str(child_file)))

        result = invoke_cli(["--validate-only", str(parent_file)])

        assert result.exit_code == 0, (
            f"Validation failed unexpectedly\nstdout: {result.output}\nstderr: {result.stderr}"
        )
        combined = result.output + result.stderr
        assert "valid" in combined.lower(), f"Expected 'valid' in output but got:\n{combined}"

    def test_nested_workflow_missing_input_error(self, tmp_path: Path) -> None:
        """Nested workflow reports error when child is missing required inputs."""
        child_file = tmp_path / "to-uppercase.pflow.md"
        child_file.write_text(CHILD_WORKFLOW)

        # Parent does NOT pass the required 'text' input to child
        parent_file = tmp_path / "parent.pflow.md"
        parent_file.write_text(_make_parent_workflow(str(child_file), pass_text=False))

        result = invoke_cli([str(parent_file), "title=hello"])

        assert result.exit_code != 0, (
            f"Expected non-zero exit code for missing input\nstdout: {result.output}\nstderr: {result.stderr}"
        )
        combined = (result.output + result.stderr).lower()
        assert "missing required inputs" in combined, (
            f"Expected 'missing required inputs' in output but got:\n{combined}"
        )

    def test_three_level_nesting_with_relative_paths(self, tmp_path: Path) -> None:
        """3-level nesting (parent → child → grandchild) with relative file paths.

        Tests that _pflow_workflow_file propagates correctly at each level,
        so each workflow resolves relative paths from its own directory.
        """
        # Directory structure:
        #   workflows/parent.pflow.md          → calls ./middle/child.pflow.md
        #   workflows/middle/child.pflow.md    → calls ./inner/grandchild.pflow.md
        #   workflows/middle/inner/grandchild.pflow.md  (leaf, does the actual work)
        root = tmp_path / "workflows"
        middle_dir = root / "middle"
        inner_dir = middle_dir / "inner"
        inner_dir.mkdir(parents=True)

        # Grandchild: the leaf workflow that does actual work
        grandchild = inner_dir / "grandchild.pflow.md"
        grandchild.write_text(CHILD_WORKFLOW)  # reuse: uppercases ${text}

        # Child (middle): calls grandchild with relative path
        child = middle_dir / "child.pflow.md"
        child.write_text("""\
# Middle Workflow

Passes text through to grandchild.

## Inputs

### text

The text to pass through.

- type: string

## Outputs

### result

The processed text from grandchild.

- source: ${process.result}

## Steps

### process

Call the grandchild workflow.

- type: workflow
- workflow: ./inner/grandchild.pflow.md
- text: ${text}
""")

        # Parent: calls child with relative path
        parent = root / "parent.pflow.md"
        parent.write_text("""\
# Top-Level Workflow

Three-level nesting test.

## Inputs

### title

The title to process.

- type: string

## Steps

### process

Call the middle workflow.

- type: workflow
- workflow: ./middle/child.pflow.md
- text: ${title}

### show

Display the result.

- type: shell
- command: echo ${process.result}
""")

        result = invoke_cli([str(parent), "title=deep nesting works"])

        assert result.exit_code == 0, (
            f"3-level nesting failed with exit code {result.exit_code}\n"
            f"stdout: {result.output}\nstderr: {result.stderr}"
        )
        combined = result.output + result.stderr
        assert "DEEP NESTING WORKS" in combined, (
            f"Expected uppercased text from 3-level chain but got:\n"
            f"stdout: {result.output!r}\nstderr: {result.stderr!r}"
        )

    def test_nested_workflow_relative_path(self, tmp_path: Path) -> None:
        """Nested workflow resolves relative child paths from parent directory."""
        # Create subdirectory structure: parent_dir/children/child.pflow.md
        parent_dir = tmp_path / "parent_dir"
        children_dir = parent_dir / "children"
        children_dir.mkdir(parents=True)

        child_file = children_dir / "child.pflow.md"
        child_file.write_text(CHILD_WORKFLOW)

        # Parent uses relative path to child
        parent_file = parent_dir / "parent.pflow.md"
        parent_file.write_text(_make_parent_workflow("./children/child.pflow.md"))

        result = invoke_cli([str(parent_file), "title=hello"])

        assert result.exit_code == 0, (
            f"Expected exit code 0 for relative path, got {result.exit_code}\n"
            f"stdout: {result.output}\nstderr: {result.stderr}"
        )
        combined = result.output + result.stderr
        assert "HELLO" in combined, (
            f"Expected 'HELLO' in combined output but got:\nstdout: {result.output!r}\nstderr: {result.stderr!r}"
        )
