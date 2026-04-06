"""Tests for the CLI visualize command.

The visualize command validates a workflow then outputs Mermaid flowchart
syntax to stdout. Errors go to stderr with exit code 1.

Implementation: src/pflow/cli/commands/visualize.py
"""

from pathlib import Path

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


class TestVisualizeDepthFlag:
    """The --depth flag controls sub-workflow expansion."""

    def test_depth_zero_produces_no_subgraphs(self, tmp_path: Path) -> None:
        """--depth 0 treats workflow nodes as opaque (no subgraph expansion)."""
        ir = {
            "nodes": [
                {"id": "step1", "type": "shell", "params": {"command": "echo hi"}},
                {
                    "id": "sub",
                    "type": "workflow",
                    "params": {
                        "workflow_ir": {
                            "nodes": [
                                {
                                    "id": "inner",
                                    "type": "shell",
                                    "params": {"command": "echo inner"},
                                }
                            ],
                            "edges": [],
                        }
                    },
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
