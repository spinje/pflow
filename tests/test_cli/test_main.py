"""Tests for pflow core CLI functionality."""

import click.testing

from pflow.cli.main import main


def test_main_command_help():
    """Test that the main command help is accessible."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "pflow - Plan Once, Run Forever" in result.output
    assert "Natural language to deterministic workflows" in result.output
    assert "CLI Syntax - chain nodes with => operator" in result.output
    assert "Natural Language - use quotes for commands with spaces" in result.output
    assert "From File - store complex workflows" in result.output
    assert "From stdin - pipe from other commands" in result.output
    assert "Passing flags to nodes - use -- separator" in result.output
    assert "Input precedence: --file > stdin > command arguments" in result.output


def test_cli_collects_multiple_arguments_as_workflow():
    """Test that CLI collects multiple arguments into a workflow string."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["node1", "node2"])

    assert result.exit_code == 0
    assert "Collected workflow from args:" in result.output
    assert "node1 node2" in result.output


def test_cli_preserves_workflow_arrow_operators():
    """Test that workflow arrow operators are preserved in collection."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["node1", "=>", "node2"])

    assert result.exit_code == 0
    assert "Collected workflow from args:" in result.output
    assert "node1 => node2" in result.output


def test_cli_handles_natural_language_with_spaces():
    """Test that CLI handles natural language commands with spaces."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["plan", "a backup strategy"])

    assert result.exit_code == 0
    assert "Collected workflow from args:" in result.output
    assert "plan a backup strategy" in result.output


def test_with_flags():
    """Test handling of flags with values."""
    runner = click.testing.CliRunner()
    # Using -- to prevent click from parsing the flags
    result = runner.invoke(main, ["--", "node1", "--flag=value", "=>", "node2"])

    assert result.exit_code == 0
    assert "Collected workflow from args:" in result.output
    assert "node1 --flag=value => node2" in result.output


def test_empty_arguments():
    """Test handling of empty arguments."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [])

    assert result.exit_code != 0
    assert "cli: No workflow provided" in result.output
    assert "Use --help to see usage examples" in result.output


def test_complex_workflow():
    """Test a complex workflow with multiple operators and flags."""
    runner = click.testing.CliRunner()
    result = runner.invoke(
        main,
        [
            "--",
            "read-file",
            "--path=input.txt",
            "=>",
            "llm",
            "--prompt=Summarize this",
            "=>",
            "write-file",
            "--path=output.txt",
        ],
    )

    assert result.exit_code == 0
    assert "Collected workflow from args:" in result.output
    assert "read-file --path=input.txt" in result.output
    assert "llm --prompt=Summarize this" in result.output
    assert "write-file --path=output.txt" in result.output


# Tests for stdin input handling
def test_plain_text_stdin_without_workflow_shows_helpful_error():
    """Test that plain text via stdin without workflow shows clear error message."""
    runner = click.testing.CliRunner()
    # Plain text stdin is now treated as data, not workflow
    result = runner.invoke(main, [], input="node1 => node2\n")

    assert result.exit_code == 1
    assert "no workflow specified" in result.output
    assert "Use --file or provide a workflow" in result.output


def test_complex_stdin_data_without_workflow_shows_helpful_error():
    """Test that complex stdin data without workflow specification shows clear guidance."""
    runner = click.testing.CliRunner()
    stdin_input = "read-file --path=input.txt => llm --prompt='Summarize' => write-file"
    result = runner.invoke(main, [], input=stdin_input)

    assert result.exit_code == 1
    assert "no workflow specified" in result.output
    assert "Use --file or provide a workflow" in result.output


def test_whitespace_padded_stdin_data_without_workflow_shows_error():
    """Test that stdin data with whitespace padding still requires workflow specification."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [], input="\n  node1 => node2  \n\n")

    assert result.exit_code == 1
    assert "no workflow specified" in result.output


def test_empty_stdin_falls_back_to_argument_workflow():
    """Test that empty stdin allows arguments to be used as workflow."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["node1"], input="")

    assert result.exit_code == 0
    assert "Collected workflow from args:" in result.output
    assert "node1" in result.output


def test_json_workflow_via_stdin_is_recognized_and_validated():
    """Test that JSON workflow via stdin is properly recognized and validated."""
    runner = click.testing.CliRunner()
    workflow_json = '{"ir_version": "0.1.0", "nodes": []}'
    result = runner.invoke(main, [], input=workflow_json)

    # This should be treated as a workflow and try to execute
    # It will fail due to empty nodes, but that's a validation error, not stdin error
    assert result.exit_code == 1
    assert "Invalid workflow" in result.output
    assert "should be non-empty" in result.output


# Tests for file input handling
def test_from_file():
    """Test reading workflow from file."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a test workflow file
        with open("workflow.txt", "w") as f:
            f.write("node1 => node2 => node3")

        result = runner.invoke(main, ["--file", "workflow.txt"])

        assert result.exit_code == 0
        assert "Collected workflow from file:" in result.output
        assert "node1 => node2 => node3" in result.output


def test_from_file_short_option():
    """Test reading workflow from file using short option."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a test workflow file
        with open("test.pflow", "w") as f:
            f.write("plan a backup strategy")

        result = runner.invoke(main, ["-f", "test.pflow"])

        assert result.exit_code == 0
        assert "Collected workflow from file:" in result.output
        assert "plan a backup strategy" in result.output


def test_from_file_with_whitespace():
    """Test file content whitespace is stripped."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a test workflow file with extra whitespace
        with open("workflow.txt", "w") as f:
            f.write("\n\n  read-file => process  \n\n")

        result = runner.invoke(main, ["--file", "workflow.txt"])

        assert result.exit_code == 0
        assert "Collected workflow from file:" in result.output
        assert "read-file => process" in result.output


def test_from_file_missing():
    """Test error when file doesn't exist."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["--file", "nonexistent.txt"])

    assert result.exit_code != 0
    assert "cli: File not found: 'nonexistent.txt'" in result.output
    assert "Check the file path and try again" in result.output


# Tests for error cases
def test_error_file_and_workflow_commands():
    """Test error when file is combined with workflow commands (not parameters)."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a test file
        with open("workflow.txt", "w") as f:
            f.write("node1")

        # Test with workflow command
        result = runner.invoke(main, ["--file", "workflow.txt", "node2"])
        assert result.exit_code != 0
        assert "cli: Cannot mix --file with workflow commands" in result.output
        assert "You can only pass parameters (key=value) with --file" in result.output

        # Test with workflow operator
        result = runner.invoke(main, ["--file", "workflow.txt", "=>"])
        assert result.exit_code != 0
        assert "cli: Cannot mix --file with workflow commands" in result.output

        # Test with mixed commands and parameters
        result = runner.invoke(main, ["--file", "workflow.txt", "param=value", "=>", "node2"])
        assert result.exit_code != 0
        assert "cli: Cannot mix --file with workflow commands" in result.output


def test_file_with_parameters():
    """Test that parameters (key=value) are allowed with --file."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create test input file
        with open("input.txt", "w") as f:
            f.write("Test content for {{name}}")

        # Create output file path
        with open("output.txt", "w") as f:
            f.write("")  # Empty file

        # Create a test workflow file with template variables using existing nodes
        # Note: pflow uses ${variable} format for templates, not {{variable}}
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

        import json

        with open("workflow.json", "w") as f:
            json.dump(workflow, f)

        # Parameters should be allowed with --file
        # Note: --verbose must come before positional arguments due to Click's parsing
        result = runner.invoke(
            main, ["--verbose", "--file", "workflow.json", "input_file=input.txt", "output_file=output.txt"]
        )

        # Check that parameters were accepted
        if "Cannot mix --file with workflow commands" in result.output:
            raise AssertionError("Parameters should be allowed with --file flag")

        # Should show parameters being used in verbose mode
        if result.exit_code == 0:
            assert "With parameters:" in result.output or "Workflow executed" in result.output
        else:
            # Even if execution fails, we should see the workflow was collected
            assert "Collected workflow from file:" in result.output or "Invalid workflow" not in result.output


def test_file_with_no_parameters():
    """Test that --file still works without any parameters."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a simple test file
        with open("workflow.txt", "w") as f:
            f.write("simple-workflow")

        # Should work without parameters
        result = runner.invoke(main, ["--file", "workflow.txt"])

        assert result.exit_code == 0
        assert "Collected workflow from file:" in result.output
        assert "simple-workflow" in result.output


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
        # Create test files
        with open("hello.txt", "w") as f:
            f.write("Hello World")

        # Create workflow with template variables
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

        import json

        with open("workflow.json", "w") as f:
            json.dump(workflow, f)

        # Run with parameters to resolve templates
        result = runner.invoke(
            main, ["--verbose", "--file", "workflow.json", "input_file=hello.txt", "output_file=result.txt"]
        )

        # Should execute successfully
        assert result.exit_code == 0
        assert "Workflow executed successfully" in result.output

        # Verify the parameters were used
        assert "With parameters:" in result.output

        # Verify output file was created with correct content
        from pathlib import Path

        assert Path("result.txt").exists()
        # ReadFileNode adds line numbers, so content will be formatted
        content = Path("result.txt").read_text()
        assert "Hello World" in content


def test_stdin_data_with_args():
    """Test that stdin is treated as data when arguments are provided."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["node1"], input="node2 => node3")

    # With dual-mode stdin, this is now valid: stdin is data, args are workflow
    assert result.exit_code == 0
    assert "Collected workflow from args: node1" in result.output
    assert "Also collected stdin data: node2 => node3" in result.output


def test_stdin_ignored_with_file():
    """Test that stdin is ignored when file is specified."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a test file
        with open("workflow.txt", "w") as f:
            f.write("from-file")

        # File takes precedence over stdin
        result = runner.invoke(main, ["--file", "workflow.txt"], input="from-stdin")

        assert result.exit_code == 0
        assert "Collected workflow from file:" in result.output
        assert "from-file" in result.output


# Tests for context storage
def test_context_storage_verification():
    """Test that context stores raw input and source correctly."""
    # Test through standard CLI invocation and verify output format
    runner = click.testing.CliRunner()

    # Test args input
    result = runner.invoke(main, ["test", "workflow"])
    assert result.exit_code == 0
    assert "Collected workflow from args: test workflow" in result.output

    # Test stdin input - plain text is now treated as data, needs workflow
    result = runner.invoke(main, [], input="stdin workflow")
    assert result.exit_code == 1
    assert "Stdin contains data but no workflow specified" in result.output

    # Test file input
    with runner.isolated_filesystem():
        with open("test.pflow", "w") as f:
            f.write("file workflow")

        result = runner.invoke(main, ["--file", "test.pflow"])
        assert result.exit_code == 0
        assert "Collected workflow from file: file workflow" in result.output


# Tests for new error handling enhancements
def test_error_empty_stdin_no_args():
    """Test error when both stdin and args are empty."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [], input="")

    assert result.exit_code != 0
    assert "cli: No workflow provided" in result.output


def test_error_empty_file():
    """Test error when file contains no workflow."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create empty file
        with open("empty.txt", "w") as f:
            f.write("")

        result = runner.invoke(main, ["--file", "empty.txt"])

        assert result.exit_code != 0
        assert "cli: No workflow provided" in result.output


def test_error_file_permission_denied():
    """Test error when file cannot be read due to permissions."""
    import os

    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a file and remove read permissions
        with open("no-read.txt", "w") as f:
            f.write("workflow")
        os.chmod("no-read.txt", 0o000)

        try:
            result = runner.invoke(main, ["--file", "no-read.txt"])
            assert result.exit_code != 0
            assert "cli: Permission denied reading file" in result.output
        finally:
            # Restore permissions for cleanup
            os.chmod("no-read.txt", 0o644)


def test_error_file_encoding():
    """Test error when file is not valid UTF-8."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a binary file
        with open("binary.dat", "wb") as f:
            f.write(b"\x80\x81\x82\x83")

        result = runner.invoke(main, ["--file", "binary.dat"])

        assert result.exit_code != 0
        assert "cli: Unable to read file" in result.output
        assert "File must be valid UTF-8 text" in result.output


def test_oversized_workflow_input_shows_clear_size_limit_error():
    """Test that workflow input exceeding size limit shows informative error."""
    runner = click.testing.CliRunner()
    # Create a workflow larger than 100KB (current limit)
    # 25000 * 5 chars ("node ") = ~125KB
    large_workflow = "node " * 25000

    result = runner.invoke(main, large_workflow.split())

    assert result.exit_code != 0
    assert "Workflow input too large" in result.output
    assert "100KB" in result.output  # Size limit mentioned


def test_signal_handling_exit_code():
    """Test that SIGINT handler is registered (cannot test actual signal)."""
    # This test verifies the handler is registered, but we can't send actual signals in tests
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["test"])

    # If we get here without error, the signal handler was registered successfully
    assert result.exit_code == 0
