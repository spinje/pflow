"""Tests for the CLI visualize command.

The visualize command validates a workflow then outputs Mermaid flowchart
syntax to stdout. Errors go to stderr with exit code 1.

Implementation: src/pflow/cli/commands/visualize.py
"""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner, Result

from pflow.cli.commands.visualize import visualize
from tests.shared.markdown_utils import write_workflow_file


def _invoke(args: list[str]) -> Result:
    """Invoke the visualize command via CliRunner."""
    runner = CliRunner()
    return runner.invoke(visualize, args)


class TestVisualizeSimpleWorkflow:
    """Basic visualization of a valid workflow."""

    def test_visualize_simple_workflow(self, tmp_path: Path) -> None:
        """Valid workflow produces Mermaid output with exit code 0."""
        ir = {
            "nodes": [
                {"id": "greet", "type": "shell", "params": {"command": "echo hello"}},
                {"id": "done", "type": "shell", "params": {"command": "echo done"}},
            ],
            "edges": [{"from": "greet", "to": "done"}],
        }
        workflow_path = tmp_path / "simple.pflow.md"
        write_workflow_file(ir, workflow_path)

        result = _invoke([str(workflow_path)])

        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}\noutput: {result.output}"
        assert "graph LR" in result.output
        # Node declarations should appear
        assert "greet" in result.output
        assert "done" in result.output
        # Edge should appear
        assert "-->" in result.output


class TestVisualizeInvalidWorkflow:
    """Visualization of invalid workflows."""

    def test_visualize_invalid_workflow(self, tmp_path: Path) -> None:
        """Workflow with unknown node type exits 1 with error output."""
        ir = {
            "nodes": [
                {"id": "bad", "type": "nonexistent_type_xyz", "params": {}},
            ],
            "edges": [],
        }
        workflow_path = tmp_path / "invalid.pflow.md"
        write_workflow_file(ir, workflow_path)

        result = _invoke([str(workflow_path)])

        assert result.exit_code == 1


class TestVisualizeNonexistentFile:
    """Visualization of a file that does not exist."""

    def test_visualize_nonexistent_file(self) -> None:
        """Invoking with a nonexistent path exits 1."""
        result = _invoke(["nonexistent.pflow.md"])

        assert result.exit_code == 1


class TestVisualizeProducerBugBoundary:
    """Regression guard for issue #237 wrapper deletion.

    After the 3 defensive wrappers in ``WorkflowValidator`` were deleted,
    producer bugs (``AttributeError``/``KeyError`` from same-team code)
    propagate out of ``runner.validate()``. The visualize command must
    convert them to structured diagnostics via ``exception_to_diagnostics``
    — mirroring the existing boundary around ``resolve_workflow`` — not let
    a raw Python traceback escape to the user.
    """

    def test_producer_bug_in_validator_renders_as_diagnostic(self, tmp_path: Path) -> None:
        ir = {
            "nodes": [{"id": "n1", "type": "shell", "params": {"command": "echo hi"}}],
            "edges": [],
        }
        workflow_path = tmp_path / "producer_bug.pflow.md"
        write_workflow_file(ir, workflow_path)

        # Simulate a producer bug: something inside validation raises an
        # AttributeError that no handler converts to a Diagnostic.
        with patch(
            "pflow.execution.runner.WorkflowRunner.validate",
            side_effect=AttributeError("'str' object has no attribute 'get'"),
        ):
            result = _invoke([str(workflow_path)])

        assert result.exit_code == 1
        # Must be a rendered diagnostic, not a raw traceback.
        assert "Traceback" not in result.output
        # The message from exception_to_diagnostics should surface.
        assert "'str' object has no attribute 'get'" in result.output


class TestVisualizeDepthFlag:
    """The --depth flag controls sub-workflow expansion."""

    def test_depth_zero_produces_no_subgraphs(self, tmp_path: Path) -> None:
        """--depth 0 treats workflow nodes as opaque (no subgraph expansion)."""
        child_path = tmp_path / "depth_child.pflow.md"
        write_workflow_file(
            {
                "nodes": [
                    {"id": "inner", "type": "shell", "params": {"command": "echo inner"}},
                ],
                "edges": [],
            },
            child_path,
        )
        ir = {
            "nodes": [
                {"id": "step1", "type": "shell", "params": {"command": "echo hi"}},
                {
                    "id": "sub",
                    "type": "workflow",
                    "params": {"workflow": str(child_path)},
                },
            ],
            "edges": [{"from": "step1", "to": "sub"}],
        }
        workflow_path = tmp_path / "depth.pflow.md"
        write_workflow_file(ir, workflow_path)

        result = _invoke(["--depth", "0", str(workflow_path)])

        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}\noutput: {result.output}"
        assert "graph LR" in result.output
        assert "subgraph" not in result.output


class TestVisualizeDirectionFlag:
    """The --direction flag controls graph orientation."""

    def test_direction_td(self, tmp_path: Path) -> None:
        """--direction TD produces a top-down graph."""
        ir = {
            "nodes": [
                {"id": "step1", "type": "shell", "params": {"command": "echo hi"}},
            ],
            "edges": [],
        }
        workflow_path = tmp_path / "direction.pflow.md"
        write_workflow_file(ir, workflow_path)

        result = _invoke(["--direction", "TD", str(workflow_path)])

        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}\noutput: {result.output}"
        assert "graph TD" in result.output
        assert "graph LR" not in result.output


class TestVisualizeOutputFlag:
    """The -o/--output flag writes mermaid to a file."""

    def test_output_writes_file(self, tmp_path: Path) -> None:
        """--output writes mermaid to the specified file and confirms on stderr."""
        ir = {
            "nodes": [
                {"id": "step1", "type": "shell", "params": {"command": "echo hi"}},
            ],
            "edges": [],
        }
        workflow_path = tmp_path / "wf.pflow.md"
        write_workflow_file(ir, workflow_path)
        output_path = tmp_path / "diagram.mmd"

        result = _invoke([str(workflow_path), "-o", str(output_path)])

        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}\noutput: {result.output}"
        assert output_path.exists()
        content = output_path.read_text()
        assert "graph LR" in content
        assert "step1" in content
        # Mermaid should NOT be on stdout (it went to file)
        assert "graph LR" not in result.output


class TestVisualizeNestedWorkflowExpansion:
    """Nested workflow files are expanded into subgraphs."""

    def test_nested_workflow_expansion(self, tmp_path: Path) -> None:
        """Parent workflow referencing a child file produces a subgraph."""
        # Create child workflow file
        child_ir = {
            "nodes": [
                {"id": "inner-step", "type": "shell", "params": {"command": "echo child"}},
            ],
            "edges": [],
        }
        child_path = tmp_path / "child.pflow.md"
        write_workflow_file(child_ir, child_path, title="Child Workflow")

        # Create parent workflow referencing the child via absolute path
        parent_path = tmp_path / "parent.pflow.md"
        parent_md = (
            "# Parent Workflow\n\n"
            "## Steps\n\n"
            "### call-child\n\n"
            "Run the child workflow.\n\n"
            f"- type: workflow\n"
            f"- workflow: {child_path}\n"
        )
        parent_path.write_text(parent_md)

        result = _invoke([str(parent_path)])

        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}\noutput: {result.output}"
        assert "graph LR" in result.output
        assert "subgraph" in result.output


class TestVisualizeMarkdownOutput:
    """The -o flag with .md extension wraps mermaid in a markdown document."""

    def test_md_output_wraps_with_title_and_description(self, tmp_path: Path) -> None:
        """Output to .md wraps mermaid in a markdown doc with title and description."""
        workflow_path = tmp_path / "wf.pflow.md"
        workflow_path.write_text(
            "# My Cool Workflow\n\nThis workflow does amazing things.\n\n"
            "## Steps\n\n### step1\n\nDoes a thing nicely.\n\n- type: shell\n- command: echo hi\n"
        )
        output_path = tmp_path / "diagram.md"

        result = _invoke([str(workflow_path), "-o", str(output_path)])

        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}\noutput: {result.output}"
        content = output_path.read_text()
        assert content.startswith("# My Cool Workflow\n")
        assert "This workflow does amazing things." in content
        assert "```mermaid\n" in content
        assert "graph LR" in content
        assert content.rstrip().endswith("```")

    def test_mmd_output_is_raw(self, tmp_path: Path) -> None:
        """Output to .mmd stays raw mermaid (no markdown wrapping)."""
        ir = {
            "nodes": [
                {"id": "step1", "type": "shell", "params": {"command": "echo hi"}},
            ],
            "edges": [],
        }
        workflow_path = tmp_path / "wf.pflow.md"
        write_workflow_file(ir, workflow_path)
        output_path = tmp_path / "diagram.mmd"

        result = _invoke([str(workflow_path), "-o", str(output_path)])

        assert result.exit_code == 0
        content = output_path.read_text()
        assert content.startswith("graph LR\n")
        assert "```mermaid" not in content


class TestVisualizeDescriptionsFlag:
    """The --descriptions flag adds node purpose text to labels."""

    def test_descriptions_cli_flag(self, tmp_path: Path) -> None:
        """--descriptions includes node purpose in mermaid labels."""
        # Write a workflow with a purpose (prose between heading and params)
        workflow_path = tmp_path / "desc.pflow.md"
        workflow_md = (
            "# Descriptions Test\n\n"
            "## Steps\n\n"
            "### greet\n\n"
            "This step greets the user warmly. It does other things too.\n\n"
            "- type: shell\n"
            "- command: echo hello\n"
        )
        workflow_path.write_text(workflow_md)

        result = _invoke(["--descriptions", str(workflow_path)])

        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}\noutput: {result.output}"
        assert "<br/>This step greets the user warmly." in result.output
