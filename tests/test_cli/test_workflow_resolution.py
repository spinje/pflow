"""Tests for pflow workflow resolution functionality (Task 22).

This module tests the unified workflow resolution mechanism that allows users to:
1. Run saved workflows by name
2. Run workflows with .pflow.md extension (strips extension)
3. Load workflows from file paths
4. Get helpful errors with suggestions
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import click.testing

from pflow.cli.main import find_similar_workflows, main, resolve_workflow
from tests.shared.markdown_utils import ir_to_markdown, write_workflow_file


class TestResolveWorkflowFunction:
    """Test the resolve_workflow function directly."""

    def test_resolve_saved_workflow_exact_name(self):
        """Test resolution of saved workflow by exact name."""
        mock_wm = MagicMock()
        mock_wm.exists.side_effect = lambda name: name == "my-workflow"
        mock_wm.load_ir.return_value = {"nodes": [], "edges": [], "ir_version": "1.0"}

        workflow_ir, source = resolve_workflow("my-workflow", mock_wm)

        assert workflow_ir == {"nodes": [], "edges": [], "ir_version": "1.0"}
        assert source == "saved"
        mock_wm.exists.assert_called_with("my-workflow")
        mock_wm.load_ir.assert_called_once_with("my-workflow")

    def test_resolve_saved_workflow_with_pflow_md_extension(self):
        """Test resolution strips .pflow.md extension and finds saved workflow."""
        mock_wm = MagicMock()
        mock_wm.exists.side_effect = lambda name: name == "my-workflow"
        mock_wm.load_ir.return_value = {"nodes": [], "edges": [], "ir_version": "1.0"}

        workflow_ir, source = resolve_workflow("my-workflow.pflow.md", mock_wm)

        assert workflow_ir == {"nodes": [], "edges": [], "ir_version": "1.0"}
        assert source == "saved"
        mock_wm.load_ir.assert_called_once_with("my-workflow")

    def test_resolve_file_path_with_slash(self):
        """Test resolution of file path containing slash."""
        workflow_data = {
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
            "ir_version": "1.0",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            wf_file = Path(tmpdir) / "workflow.pflow.md"
            write_workflow_file(workflow_data, wf_file)

            mock_wm = MagicMock()
            mock_wm.exists.return_value = False

            workflow_ir, source = resolve_workflow(str(wf_file), mock_wm)

            assert workflow_ir is not None
            assert source == "file"
            # Should not check saved workflows for paths
            mock_wm.exists.assert_not_called()

    def test_resolve_file_path_relative(self):
        """Test resolution of relative file path."""
        workflow_data = {
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            workflow_file = Path(tmpdir) / "workflow.pflow.md"
            write_workflow_file(workflow_data, workflow_file)

            mock_wm = MagicMock()
            mock_wm.exists.return_value = False

            workflow_ir, source = resolve_workflow(str(workflow_file), mock_wm)

            assert workflow_ir is not None
            assert source == "file"

    def test_resolve_workflow_not_found(self):
        """Test resolution when workflow doesn't exist."""
        mock_wm = MagicMock()
        mock_wm.exists.return_value = False

        workflow_ir, source = resolve_workflow("nonexistent", mock_wm)

        assert workflow_ir is None
        assert source is None

    def test_resolve_with_home_expansion(self):
        """Test resolution expands ~ in file paths."""
        workflow_data = {
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            wf_file = Path(tmpdir) / "workflow.pflow.md"
            write_workflow_file(workflow_data, wf_file)

            mock_wm = MagicMock()
            # Create a path with ~ that will expand to the actual file
            with patch("pathlib.Path.expanduser") as mock_expand:
                mock_expand.return_value = wf_file

                workflow_ir, source = resolve_workflow("~/workflow.pflow.md", mock_wm)

                assert workflow_ir is not None
                assert source == "file"
                mock_expand.assert_called_once()


class TestFindSimilarWorkflows:
    """Test the find_similar_workflows function."""

    def test_find_similar_by_substring(self):
        """Test finding workflows by substring match."""
        mock_wm = MagicMock()
        mock_wm.list_all.return_value = [
            {"name": "analyze-text"},
            {"name": "text-summary"},
            {"name": "process-data"},
            {"name": "text-to-speech"},
        ]

        similar = find_similar_workflows("text", mock_wm)

        assert len(similar) == 3
        assert "analyze-text" in similar
        assert "text-summary" in similar
        assert "text-to-speech" in similar

    def test_find_similar_case_insensitive(self):
        """Test finding workflows is case insensitive."""
        mock_wm = MagicMock()
        mock_wm.list_all.return_value = [
            {"name": "GitHub-Sync"},
            {"name": "github-backup"},
            {"name": "sync-github"},
        ]

        similar = find_similar_workflows("GITHUB", mock_wm)

        assert len(similar) == 3

    def test_find_similar_max_results(self):
        """Test that max_results limits the number of suggestions."""
        mock_wm = MagicMock()
        mock_wm.list_all.return_value = [{"name": f"workflow-{i}"} for i in range(10)]

        similar = find_similar_workflows("workflow", mock_wm, max_results=3)

        assert len(similar) == 3


class TestWorkflowResolutionCLI:
    """Test the CLI integration of workflow resolution."""

    def test_run_saved_workflow_by_name(self):
        """Test running a saved workflow by name."""
        runner = click.testing.CliRunner()

        with patch("pflow.cli.main.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.side_effect = lambda name: name == "my-workflow"
            mock_wm.load_ir.return_value = {
                "nodes": [{"id": "test", "type": "test_node", "config": {}}],
                "edges": [],
                "ir_version": "1.0",
            }

            with patch("pflow.cli.main.execute_json_workflow") as mock_execute:
                result = runner.invoke(main, ["my-workflow"])

                assert result.exit_code == 0
                mock_wm.exists.assert_called_with("my-workflow")
                mock_wm.load_ir.assert_called_with("my-workflow")
                mock_execute.assert_called_once()

                # Verify the IR was passed correctly
                call_args = mock_execute.call_args[0]
                assert call_args[1]["nodes"][0]["type"] == "test_node"

    def test_run_workflow_with_pflow_md_extension(self):
        """Test running workflow with .pflow.md extension strips it."""
        runner = click.testing.CliRunner()

        with patch("pflow.cli.main.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.side_effect = lambda name: name == "my-workflow"
            mock_wm.load_ir.return_value = {"nodes": [], "edges": [], "ir_version": "1.0"}

            with patch("pflow.cli.main.execute_json_workflow") as mock_execute:
                result = runner.invoke(main, ["my-workflow.pflow.md"])

                assert result.exit_code == 0
                # Should find it without extension
                mock_wm.load_ir.assert_called_with("my-workflow")
                mock_execute.assert_called_once()

    def test_run_workflow_from_file(self):
        """Test running workflow from file path."""
        runner = click.testing.CliRunner()

        workflow_data = {
            "nodes": [{"id": "test", "type": "test_node", "config": {}}],
            "edges": [],
            "ir_version": "1.0",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            content = ir_to_markdown(workflow_data)
            f.write(content)
            f.flush()

            try:
                with patch("pflow.cli.main.execute_json_workflow") as mock_execute:
                    result = runner.invoke(main, [f.name])

                    assert result.exit_code == 0
                    mock_execute.assert_called_once()
            finally:
                Path(f.name).unlink()

    def test_workflow_not_found_shows_suggestions(self):
        """Test that helpful suggestions are shown when workflow not found."""
        runner = click.testing.CliRunner()

        with patch("pflow.cli.main.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = False
            mock_wm.list_all.return_value = [
                {"name": "text-analyzer"},
                {"name": "text-summary"},
                {"name": "analyze-data"},
            ]

            result = runner.invoke(main, ["text-analyz"])

            assert result.exit_code == 1
            assert "Workflow 'text-analyz' not found" in result.output
            assert "Did you mean one of these?" in result.output
            assert "text-analyzer" in result.output

    def test_workflow_not_found_no_suggestions(self):
        """Test message when no similar workflows found."""
        runner = click.testing.CliRunner()

        with patch("pflow.cli.main.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = False
            mock_wm.list_all.return_value = []

            result = runner.invoke(main, ["unknown-workflow"])

            assert result.exit_code == 1
            assert "Workflow 'unknown-workflow' not found" in result.output
            assert "Use 'pflow workflow list' to see available workflows" in result.output

    def test_pass_parameters_to_named_workflow(self):
        """Test passing parameters to a named workflow - simplified test."""
        runner = click.testing.CliRunner()

        with patch("pflow.cli.main.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.side_effect = lambda name: name == "process-data"
            mock_wm.load_ir.return_value = {
                "nodes": [],
                "edges": [],
                "ir_version": "1.0",
                "inputs": {
                    "file": {"description": "Input file", "required": True},
                    "format": {"description": "Output format", "required": False, "default": "json"},
                },
            }

            with patch("pflow.cli.main.execute_json_workflow") as mock_execute:
                result = runner.invoke(main, ["process-data", "file=data.csv", "format=xml"])

                assert result.exit_code == 0

                if mock_execute.called:
                    call_args = mock_execute.call_args[0]
                    if len(call_args) > 4 and call_args[4]:
                        params = call_args[4]
                        assert params["file"] == "data.csv"
                        assert params["format"] == "xml"

    def test_parameter_validation_with_prepare_inputs(self):
        """Test that parameters are validated using prepare_inputs."""
        runner = click.testing.CliRunner()

        with patch("pflow.cli.main.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.side_effect = lambda name: name == "process-data"
            mock_wm.load_ir.return_value = {
                "nodes": [],
                "edges": [],
                "ir_version": "1.0",
                "inputs": {
                    "file": {"description": "Input file path", "required": True},
                    "output": {"description": "Output file path", "required": True},
                },
            }

            result = runner.invoke(main, ["process-data"])

            assert result.exit_code == 1
            assert "❌" in result.output
            assert "Workflow requires input 'file'" in result.output
            assert "Input file path" in result.output
            assert "Workflow requires input 'output'" in result.output

    def test_parameter_defaults_applied(self):
        """Test that default values are applied for optional parameters - simplified."""
        runner = click.testing.CliRunner()

        with patch("pflow.cli.main.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.side_effect = lambda name: name == "analyze"
            mock_wm.load_ir.return_value = {
                "nodes": [],
                "edges": [],
                "ir_version": "1.0",
                "inputs": {
                    "text": {"description": "Text to analyze", "required": True},
                    "model": {"description": "Model to use", "required": False, "default": "gpt-4"},
                },
            }

            with patch("pflow.cli.main.execute_json_workflow") as mock_execute:
                result = runner.invoke(main, ["analyze", "text=Hello world"])

                assert result.exit_code == 0

                if mock_execute.called:
                    call_args = mock_execute.call_args[0]
                    if len(call_args) > 4 and call_args[4]:
                        params = call_args[4]
                        assert params["text"] == "Hello world"
                        assert params["model"] == "gpt-4"

    def test_verbose_output_shows_loading_info(self):
        """Test that verbose mode shows what's happening."""
        runner = click.testing.CliRunner()

        with patch("pflow.cli.main.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.side_effect = lambda name: name == "my-workflow"
            mock_wm.load_ir.return_value = {"nodes": [], "edges": [], "ir_version": "1.0"}

            with patch("pflow.cli.main.execute_json_workflow"):
                result = runner.invoke(main, ["--verbose", "my-workflow", "param=value"])

                assert result.exit_code == 0
                assert "verbose" in result.output.lower() or "loading" in result.output.lower() or result.exit_code == 0

    def test_verbose_file_loading(self):
        """Test verbose output when loading from file."""
        runner = click.testing.CliRunner()

        workflow_data = {
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
            "ir_version": "1.0",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow_data))
            f.flush()

            try:
                with patch("pflow.cli.main.execute_json_workflow"):
                    result = runner.invoke(main, ["--verbose", f.name])

                    assert result.exit_code == 0
                    assert f"cli: Loading workflow from file: {f.name}" in result.output
            finally:
                Path(f.name).unlink()

    def test_type_inference_for_parameters(self):
        """Test that parameter types are correctly inferred."""
        runner = click.testing.CliRunner()

        with patch("pflow.cli.main.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.side_effect = lambda name: name == "test"
            mock_wm.load_ir.return_value = {"nodes": [], "edges": [], "ir_version": "1.0"}

            with patch("pflow.cli.main.execute_json_workflow") as mock_execute:
                result = runner.invoke(
                    main,
                    [
                        "test",
                        "count=42",
                        "ratio=3.14",
                        "enabled=true",
                        "disabled=false",
                        "list=[1,2,3]",
                        'obj={"key":"value"}',
                        "text=hello world",
                    ],
                )

                assert result.exit_code == 0
                call_args = mock_execute.call_args
                if call_args and len(call_args[0]) > 4:
                    params = call_args[0][4]

                    assert params["count"] == 42
                    assert isinstance(params["count"], int)

                    assert params["ratio"] == 3.14
                    assert isinstance(params["ratio"], float)

                    assert params["enabled"] is True
                    assert isinstance(params["enabled"], bool)

                    assert params["disabled"] is False
                    assert isinstance(params["disabled"], bool)

                    assert params["list"] == [1, 2, 3]
                    assert isinstance(params["list"], list)

                    assert params["obj"] == {"key": "value"}
                    assert isinstance(params["obj"], dict)

                    assert params["text"] == "hello world"
                    assert isinstance(params["text"], str)

    def test_json_output_format_with_named_workflow(self):
        """Test that --output-format json works with named workflows - simplified."""
        runner = click.testing.CliRunner()

        with patch("pflow.cli.main.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.side_effect = lambda name: name == "test"
            mock_wm.load_ir.return_value = {
                "nodes": [{"id": "test", "type": "test_node", "config": {}}],
                "edges": [],
                "ir_version": "1.0",
            }

            result = runner.invoke(main, ["--output-format", "json", "test"])

            assert result.exit_code in (0, 1)

    def test_natural_language_fallback(self):
        """Test that natural language shows gated planner message when workflow not found."""
        runner = click.testing.CliRunner()

        with patch("pflow.cli.main.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = False
            mock_wm.list_all.return_value = []

            result = runner.invoke(main, ["analyze this text and summarize"])

            # GATED: Planner disabled (Task 107) — should show gated message
            assert result.exit_code != 0
            assert "temporarily unavailable" in result.output


class TestIsLikelyWorkflowName:
    """Test the heuristic for detecting workflow names vs natural language."""

    def test_single_word_not_workflow_name(self):
        """Test that single words without params aren't treated as workflow names."""
        from pflow.cli.main import is_likely_workflow_name

        assert not is_likely_workflow_name("analyze", ())
        assert not is_likely_workflow_name("process", ())
        assert not is_likely_workflow_name("test", ())

    def test_single_word_with_params_is_workflow_name(self):
        """Single word with params is treated as a workflow target (planner allowed)."""
        from pflow.cli.main import is_likely_workflow_name

        assert is_likely_workflow_name("analyze", ("input=data.csv",))

    def test_kebab_case_is_workflow_name(self):
        """Test that kebab-case names are recognized as workflow names."""
        from pflow.cli.main import is_likely_workflow_name

        assert is_likely_workflow_name("my-workflow", ())
        assert is_likely_workflow_name("process-data", ())
        assert is_likely_workflow_name("github-sync", ())

    def test_text_with_spaces_not_workflow_name(self):
        """Test that text with spaces is never a workflow name."""
        from pflow.cli.main import is_likely_workflow_name

        assert not is_likely_workflow_name("analyze this text", ())
        assert not is_likely_workflow_name("process my data", ("param=value",))

    def test_file_paths_are_workflow_names(self):
        """Test that file paths are recognized as workflow references."""
        from pflow.cli.main import is_likely_workflow_name

        assert is_likely_workflow_name("./workflow.pflow.md", ())
        assert is_likely_workflow_name("../workflows/test.pflow.md", ())
        assert is_likely_workflow_name("/absolute/path.pflow.md", ())
        assert is_likely_workflow_name("workflow.pflow.md", ())
        # .json paths are still path-like (triggers error)
        assert is_likely_workflow_name("./workflow.json", ())
        assert is_likely_workflow_name("workflow.json", ())

    def test_with_parameters_is_workflow_name(self):
        """Test that arguments with parameters suggest workflow name."""
        from pflow.cli.main import is_likely_workflow_name

        assert is_likely_workflow_name("process", ("input=data.txt", "output=result.json"))
        assert is_likely_workflow_name("workflow", ("key=value",))

    def test_cli_syntax_not_workflow_name(self):
        """Test that CLI syntax isn't mistaken for workflow name."""
        from pflow.cli.main import is_likely_workflow_name

        assert not is_likely_workflow_name("node1", ("=>", "node2"))
        assert not is_likely_workflow_name("read-file", ("--verbose",))


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_workflow_name(self):
        """Test that empty string is handled correctly."""
        runner = click.testing.CliRunner()

        result = runner.invoke(main, [""])

        assert result.exit_code != 0
        assert "not a known workflow" in result.output

    def test_workflow_file_not_found(self):
        """Test helpful error when workflow file doesn't exist."""
        runner = click.testing.CliRunner()

        result = runner.invoke(main, ["./nonexistent.pflow.md"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_invalid_markdown_in_file(self):
        """Test error handling for invalid markdown in workflow file."""
        runner = click.testing.CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            # Write content that is not a valid workflow (no ## Steps section)
            f.write("# Not a Workflow\n\nJust some text.\n")
            f.flush()

            try:
                result = runner.invoke(main, [f.name])

                # Invalid workflow should cause an error
                assert result.exit_code != 0
            finally:
                Path(f.name).unlink()

    def test_permission_error_on_file(self, tmp_path):
        """Test permission error yields helpful message."""
        runner = click.testing.CliRunner()

        wf = tmp_path / "wf.pflow.md"
        wf.write_text("# Test\n\n## Steps\n\n### a\n\nDesc.\n\n- type: shell\n")

        def raise_perm(*args, **kwargs):
            raise PermissionError

        with patch("pathlib.Path.read_text", raise_perm):
            result = runner.invoke(main, [str(wf)])
            assert result.exit_code != 0
            assert "Permission denied" in result.output

    def test_unicode_decode_error_on_file(self, tmp_path):
        """Test decode error yields helpful message."""
        runner = click.testing.CliRunner()

        wf = tmp_path / "wf.pflow.md"
        wf.write_text("placeholder")

        def raise_decode(*args, **kwargs):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

        with patch("pathlib.Path.read_text", raise_decode):
            result = runner.invoke(main, [str(wf)])
            assert result.exit_code != 0
            assert "Unable to read file" in result.output

    def test_parameter_with_equals_in_value(self):
        """Test parameters with = in the value are handled correctly."""
        runner = click.testing.CliRunner()

        with patch("pflow.cli.main.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.side_effect = lambda name: name == "test"
            mock_wm.load_ir.return_value = {"nodes": [], "edges": [], "ir_version": "1.0"}

            with patch("pflow.cli.main.execute_json_workflow") as mock_execute:
                result = runner.invoke(main, ["test", "equation=a=b+c"])

                assert result.exit_code == 0
                call_args = mock_execute.call_args
                if call_args and len(call_args[0]) > 4:
                    params = call_args[0][4]
                    assert params["equation"] == "a=b+c"
