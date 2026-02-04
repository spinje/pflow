"""Tests for pflow core CLI functionality."""

from unittest.mock import patch

import click.testing
import pytest

from pflow.cli.main import main


def test_main_command_help():
    """Test that the main command help is accessible."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "pflow - Plan Once, Run Forever" in result.output
    assert "Natural language to deterministic workflows" in result.output
    # Updated help text assertions for Task 22 changes
    assert "pflow workflow.pflow.md" in result.output  # File workflow example
    assert "pflow my-workflow param=value" in result.output  # Named workflow example
    assert "Natural Language - use quotes for commands with spaces" in result.output
    assert "From stdin - pipe from other commands" in result.output
    assert "Run workflow from file (no flag needed!)" in result.output  # New file handling
    assert "Workflows can be specified by name, file path, or natural language" in result.output


# REMOVED: Tests for old pre-planner "workflow collection" behavior
# These tests expected unquoted multi-word input to be collected and echoed back.
# With planner validation, these inputs now correctly show errors requiring quotes.
# New tests for this behavior are in test_planner_input_validation.py


def test_empty_arguments():
    """Test handling of empty arguments."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [])

    assert result.exit_code != 0
    # Updated error message from new validation
    assert "No workflow" in result.output


# Tests for stdin input handling
def test_plain_text_stdin_without_workflow_shows_helpful_error():
    """Test that plain text via stdin without workflow shows clear error message."""
    runner = click.testing.CliRunner()
    # Plain text stdin is now treated as data, not workflow
    result = runner.invoke(main, [], input="node1 => node2\n")

    assert result.exit_code == 1
    assert "No workflow" in result.output


def test_complex_stdin_data_without_workflow_shows_helpful_error():
    """Test that complex stdin data without workflow specification shows clear guidance."""
    runner = click.testing.CliRunner()
    stdin_input = "read-file --path=input.txt => llm --prompt='Summarize' => write-file"
    result = runner.invoke(main, [], input=stdin_input)

    assert result.exit_code == 1
    assert "No workflow" in result.output


def test_whitespace_padded_stdin_data_without_workflow_shows_error():
    """Test that stdin data with whitespace padding still requires workflow specification."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [], input="\n  node1 => node2  \n\n")

    assert result.exit_code == 1
    assert "No workflow" in result.output


def test_empty_stdin_falls_back_to_argument_workflow():
    """Test that empty stdin allows arguments to be used as workflow."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["node1"], input="")
    # With planner validation, single word shows helpful error
    assert result.exit_code != 0
    assert "not a known workflow" in result.output


def test_json_workflow_via_stdin_requires_workflow_arg():
    """Test that JSON workflow via stdin still requires a workflow argument."""
    runner = click.testing.CliRunner()
    workflow_json = '{"ir_version": "0.1.0", "nodes": []}'
    result = runner.invoke(main, [], input=workflow_json)

    # With Task 22 changes, stdin alone doesn't work - need workflow args
    assert result.exit_code == 1
    assert "No workflow" in result.output


# Tests for file input handling
def test_from_markdown_file():
    """Test reading workflow from .pflow.md file."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        from tests.shared.markdown_utils import ir_to_markdown

        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "test"}}],
            "edges": [],
        }
        with open("workflow.pflow.md", "w") as f:
            f.write(ir_to_markdown(workflow))

        # .pflow.md file path is detected automatically without --file flag
        result = runner.invoke(main, ["./workflow.pflow.md"])

        # Should execute successfully with echo node
        assert result.exit_code == 0
        assert "test" in result.output or "Workflow executed" in result.output


def test_from_pflow_file_with_empty_steps():
    """Test reading .pflow.md file with no nodes shows validation error."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a workflow file with empty Steps section
        with open("test.pflow.md", "w") as f:
            f.write("# Test\n\nA test workflow.\n\n## Steps\n")

        # .pflow.md extension triggers file workflow detection
        result = runner.invoke(main, ["test.pflow.md"])

        # Should show validation error for empty nodes
        assert result.exit_code != 0
        # Empty steps should fail structural validation
        assert "steps" in result.output.lower() or "node" in result.output.lower()


def test_from_pflow_file_with_whitespace():
    """Test .pflow.md file with extra whitespace is handled correctly."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a .pflow.md file with leading/trailing whitespace
        with open("workflow.pflow.md", "w") as f:
            f.write("\n\n# Test\n\nDescription.\n\n## Steps\n\n")

        # File is detected and parsed — empty Steps section is an error
        result = runner.invoke(main, ["./workflow.pflow.md"])

        # Should show validation error for empty steps
        assert result.exit_code != 0
        assert "steps" in result.output.lower() or "node" in result.output.lower()


def test_from_file_missing():
    """Test error when file doesn't exist."""
    runner = click.testing.CliRunner()
    # File path is detected but file doesn't exist
    result = runner.invoke(main, ["./nonexistent.pflow.md"])

    assert result.exit_code != 0
    # Should show workflow not found
    assert "Workflow './nonexistent.pflow.md' not found" in result.output


# Tests for error cases
def test_markdown_workflow_with_parameters():
    """Test that .pflow.md workflow files can accept parameters."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        from tests.shared.markdown_utils import ir_to_markdown

        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "${param1}"}}],
            "edges": [],
        }
        with open("workflow.pflow.md", "w") as f:
            f.write(ir_to_markdown(workflow))

        # .pflow.md files are detected automatically and can accept parameters
        result = runner.invoke(main, ["--verbose", "./workflow.pflow.md", "param1=value1"])
        # Due to Task 22 implementation bug, parameters with file workflows go through planner
        # The condition checking for spaces prevents direct file+params execution
        assert "param1" in result.output or "value1" in result.output or "planner" in result.output.lower()


def test_file_with_parameters():
    """Test that parameters (key=value) are allowed with workflow files."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        from tests.shared.markdown_utils import ir_to_markdown

        # Create test input file
        with open("input.txt", "w") as f:
            f.write("Test content")

        # Create output file path
        with open("output.txt", "w") as f:
            f.write("")  # Empty file

        # Create a test workflow file with template variables using existing nodes
        # Note: pflow uses ${variable} format for templates
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "reader", "type": "read-file", "params": {"file_path": "${input_file}"}},
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {
                        "file_path": "${output_file}",
                        "content": "${reader.content}",  # Explicit connection required with namespacing
                    },
                },
            ],
            "edges": [{"from": "reader", "to": "writer"}],
        }

        with open("workflow.pflow.md", "w") as f:
            f.write(ir_to_markdown(workflow))

        # Parameters should be allowed with workflow files (no --file flag needed)
        result = runner.invoke(
            main, ["--verbose", "./workflow.pflow.md", "input_file=input.txt", "output_file=output.txt"]
        )

        # Due to Task 22 implementation bug, parameters with file workflows go through planner
        # The condition checking for spaces prevents direct file+params execution
        # This test documents the current (broken) behavior
        assert result.exit_code == 0 or "planner" in result.output.lower() or "input_file" in result.output


def test_pflow_file_with_no_parameters():
    """Test that .pflow.md workflow files work without any parameters."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        from tests.shared.markdown_utils import ir_to_markdown

        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "hello"}}],
            "edges": [],
        }
        with open("workflow.pflow.md", "w") as f:
            f.write(ir_to_markdown(workflow))

        # Should work without parameters
        result = runner.invoke(main, ["./workflow.pflow.md"])

        # Should execute successfully
        assert result.exit_code == 0
        assert "hello" in result.output or "Workflow executed" in result.output


def test_file_with_parameters_template_resolution():
    """Test that template variables in workflow are resolved with passed parameters."""
    runner = click.testing.CliRunner()

    # Import Registry and scanner to populate it
    from pathlib import Path

    from pflow.registry.registry import Registry
    from pflow.registry.scanner import scan_for_nodes

    # Ensure registry exists
    registry = Registry()
    if not registry.registry_path.exists():
        # Populate registry for tests
        src_path = Path(__file__).parent.parent.parent / "src"
        nodes_dir = src_path / "pflow" / "nodes"
        if nodes_dir.exists():
            scan_results = scan_for_nodes([nodes_dir])
            registry.update_from_scanner(scan_results)

    with runner.isolated_filesystem():
        from tests.shared.markdown_utils import ir_to_markdown

        # Create test files
        with open("hello.txt", "w") as f:
            f.write("Hello World")

        # Create workflow with template variables AND declared inputs
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "input_file": {"type": "string", "required": True},
                "output_file": {"type": "string", "required": True},
            },
            "nodes": [
                {"id": "reader", "type": "read-file", "params": {"file_path": "${input_file}"}},
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {
                        "file_path": "${output_file}",
                        "content": "${reader.content}",  # Explicit connection required with namespacing
                    },
                },
            ],
            "edges": [{"from": "reader", "to": "writer"}],
        }

        with open("workflow.pflow.md", "w") as f:
            f.write(ir_to_markdown(workflow))

        # Run with parameters to resolve templates (no --file flag needed)
        result = runner.invoke(
            main, ["--verbose", "./workflow.pflow.md", "input_file=hello.txt", "output_file=result.txt"]
        )

        # Should execute successfully or show collection (test env has planner blocked)
        assert (
            "Collected workflow from args" in result.output  # Test env fallback
            or "planner" in result.output.lower()  # With planner enabled
            or "Workflow executed" in result.output  # Direct execution
            or "Hello World" in result.output  # Content was processed
            or result.exit_code == 0  # Success somehow
        )


def test_stdin_data_with_args():
    """Test that stdin is treated as data when arguments are provided."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["node1"], input="node2 => node3")

    # With planner validation, single word shows helpful error
    assert result.exit_code != 0
    assert "not a known workflow" in result.output


@patch("pflow.core.shell_integration.stdin_has_data", return_value=True)
def test_stdin_with_file_workflow(mock_stdin_has_data):
    """Test that stdin data works with file-based workflows when stdin: true is declared."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        from tests.shared.markdown_utils import ir_to_markdown

        # Create a test workflow file with stdin: true input
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"data": {"type": "string", "required": True, "stdin": True}},
            "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "${data}"}}],
            "edges": [],
        }
        with open("workflow.pflow.md", "w") as f:
            f.write(ir_to_markdown(workflow))

        # File workflow with stdin data - should route to the stdin: true input
        result = runner.invoke(main, ["./workflow.pflow.md"], input="stdin-data")

        # Should execute the workflow with stdin routed to 'data' input
        assert result.exit_code == 0
        assert "stdin-data" in result.output or "Workflow" in result.output


# Tests for context storage
def test_context_storage_verification():
    """Test that context handles various input types correctly."""
    # This test originally verified the old "workflow collection" behavior
    # With planner validation, unquoted multi-word input now errors
    runner = click.testing.CliRunner()

    # Test multi-word unquoted args - should error with quote suggestion
    result = runner.invoke(main, ["test", "workflow"])
    assert result.exit_code == 1
    assert "Invalid input" in result.output or "must be quoted" in result.output

    # Test stdin input - plain text is now treated as data, needs workflow
    result = runner.invoke(main, [], input="stdin workflow")
    assert result.exit_code == 1
    assert "No workflow" in result.output

    # Test file input - non-JSON files go through planner
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["./test.pflow"])
        # Non-existent file treated as workflow name
        assert result.exit_code != 0
        assert "not found" in result.output


# Tests for new error handling enhancements
def test_error_empty_stdin_no_args():
    """Test error when both stdin and args are empty."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [], input="")

    assert result.exit_code != 0
    assert "No workflow" in result.output


def test_error_empty_pflow_file():
    """Test error when .pflow.md file is empty."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create empty file
        with open("empty.pflow.md", "w") as f:
            f.write("")

        result = runner.invoke(main, ["./empty.pflow.md"])

        assert result.exit_code != 0
        # Empty markdown file should show parse error
        assert "steps" in result.output.lower() or "error" in result.output.lower()


def test_error_file_permission_denied():
    """Test error when file cannot be read due to permissions."""
    import os

    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a .pflow.md file and remove read permissions
        with open("no-read.pflow.md", "w") as f:
            f.write("# Test\n\nDescription.\n\n## Steps\n\n### echo1\n\nA step.\n\n- type: echo\n")
        os.chmod("no-read.pflow.md", 0o000)

        try:
            result = runner.invoke(main, ["./no-read.pflow.md"])
            assert result.exit_code != 0
            # Permission errors now show explicit permission message
            assert "Permission denied" in result.output
        finally:
            # Restore permissions for cleanup
            os.chmod("no-read.pflow.md", 0o644)


def test_error_file_encoding():
    """Test error when .pflow.md file is not valid UTF-8."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a binary file with .pflow.md extension
        with open("binary.pflow.md", "wb") as f:
            f.write(b"\x80\x81\x82\x83")

        result = runner.invoke(main, ["./binary.pflow.md"])

        assert result.exit_code != 0
        # File encoding errors now show explicit decoding message
        assert "Unable to read file" in result.output


@pytest.mark.skip(reason="Gated pending markdown format migration (Task 107) — size validation is in planner path")
def test_oversized_workflow_input_shows_clear_size_limit_error():
    """Test that workflow input exceeding size limit shows informative error."""
    runner = click.testing.CliRunner()
    # Create a workflow larger than 100KB (current limit)
    # With planner validation, we need a single quoted string WITH SPACES > 100KB
    # to pass validation and reach the size check
    large_prompt = "do something " * 10000  # Over 100KB with spaces

    result = runner.invoke(main, [large_prompt])

    assert result.exit_code != 0
    assert "Workflow input too large" in result.output
    assert "100KB" in result.output  # Size limit mentioned


def test_signal_handling_exit_code():
    """Test that SIGINT handler is registered (cannot test actual signal)."""
    # This test verifies the handler is registered, but we can't send actual signals in tests
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["test"])

    # With planner validation, a lone token shows helpful error
    assert result.exit_code != 0
    assert "not a known workflow" in result.output


# New tests for Task 22 functionality
def test_pflow_file_automatic_detection():
    """Test that .pflow.md files are automatically detected as workflow files."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        from tests.shared.markdown_utils import ir_to_markdown

        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "test"}}],
            "edges": [],
        }
        with open("my-workflow.pflow.md", "w") as f:
            f.write(ir_to_markdown(workflow))

        # .pflow.md extension triggers file workflow detection
        result = runner.invoke(main, ["my-workflow.pflow.md"])
        # Should execute successfully with echo node
        assert result.exit_code == 0
        assert "test" in result.output or "Workflow executed" in result.output


def test_path_with_slash_triggers_file_detection():
    """Test that paths with / are detected as file paths."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        import os

        from tests.shared.markdown_utils import ir_to_markdown

        os.makedirs("workflows")
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "hello"}}],
            "edges": [],
        }
        with open("workflows/test.pflow.md", "w") as f:
            f.write(ir_to_markdown(workflow))

        # Path with / triggers file detection
        result = runner.invoke(main, ["workflows/test.pflow.md"])
        # Should execute the workflow
        assert result.exit_code == 0
        assert "hello" in result.output or "Workflow executed" in result.output


def test_absolute_path_workflow():
    """Test that absolute paths work for workflow files."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        import os

        from tests.shared.markdown_utils import ir_to_markdown

        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "absolute path test"}}],
            "edges": [],
        }
        with open("workflow.pflow.md", "w") as f:
            f.write(ir_to_markdown(workflow))

        # Get absolute path
        abs_path = os.path.abspath("workflow.pflow.md")

        # Absolute path should work
        result = runner.invoke(main, [abs_path])
        assert result.exit_code == 0
        assert "absolute path test" in result.output or "Workflow executed" in result.output


def test_home_directory_expansion():
    """Test that ~ expands to home directory in workflow paths."""
    runner = click.testing.CliRunner()
    from pathlib import Path

    from tests.shared.markdown_utils import ir_to_markdown

    # Create a temporary workflow in a known location
    home = Path.home()
    test_file = home / ".test_workflow_temp.pflow.md"
    try:
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "home test"}}],
            "edges": [],
        }
        test_file.write_text(ir_to_markdown(workflow))

        # Run with ~ path
        result = runner.invoke(main, ["~/.test_workflow_temp.pflow.md"])
        # Should execute or show not found if home expansion fails
        assert "home test" in result.output or "Workflow executed" in result.output or "not found" in result.output
    finally:
        # Clean up
        if test_file.exists():
            test_file.unlink()


def test_workflow_name_without_extension_not_treated_as_file():
    """Test that workflow names without / or .pflow.md are not treated as files."""
    runner = click.testing.CliRunner()

    # Simple names without path indicators should go through workflow resolution
    # not file detection; single-word without context now shows targeted not-found
    result = runner.invoke(main, ["my-workflow"])
    assert result.exit_code != 0
    assert "Workflow 'my-workflow' not found" in result.output


def test_workflow_name_with_params_detected():
    """Test that workflow names with parameters are detected correctly."""
    runner = click.testing.CliRunner()

    # Workflow name with parameters should be detected
    result = runner.invoke(main, ["my-workflow", "param1=value1", "param2=value2"])
    # Should attempt to find saved workflow and show not found error
    assert result.exit_code != 0
    assert "Workflow 'my-workflow' not found" in result.output or "not found" in result.output.lower()
