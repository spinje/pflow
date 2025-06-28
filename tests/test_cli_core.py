"""Tests for pflow core CLI functionality."""

import click.testing

from pflow.cli import main


def test_main_command_help():
    """Test that the main command help is accessible."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "pflow - workflow compiler" in result.output
    assert "Execute workflows using the =>" in result.output


def test_simple_arguments():
    """Test simple argument collection."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["node1", "node2"])

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from args: node1 node2"


def test_preserves_arrow_operator():
    """Test that => operator is preserved."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["node1", "=>", "node2"])

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from args: node1 => node2"


def test_with_quoted_strings():
    """Test handling of quoted strings."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["plan", "a backup strategy"])

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from args: plan a backup strategy"


def test_with_flags():
    """Test handling of flags with values."""
    runner = click.testing.CliRunner()
    # Using -- to prevent click from parsing the flags
    result = runner.invoke(main, ["--", "node1", "--flag=value", "=>", "node2"])

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from args: node1 --flag=value => node2"


def test_empty_arguments():
    """Test handling of empty arguments."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [])

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from args:"


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
    expected = "Collected workflow from args: read-file --path=input.txt => llm --prompt=Summarize this => write-file --path=output.txt"
    assert result.output.strip() == expected


# Tests for stdin input handling
def test_from_stdin_simple():
    """Test reading workflow from stdin."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [], input="node1 => node2\n")

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from stdin: node1 => node2"


def test_from_stdin_complex():
    """Test reading complex workflow from stdin."""
    runner = click.testing.CliRunner()
    stdin_input = "read-file --path=input.txt => llm --prompt='Summarize' => write-file"
    result = runner.invoke(main, [], input=stdin_input)

    assert result.exit_code == 0
    assert result.output.strip() == f"Collected workflow from stdin: {stdin_input}"


def test_from_stdin_with_newlines():
    """Test stdin with newlines gets stripped."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [], input="\n  node1 => node2  \n\n")

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from stdin: node1 => node2"


def test_from_stdin_empty():
    """Test empty stdin falls back to args mode."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["node1"], input="")

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from args: node1"


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
        assert result.output.strip() == "Collected workflow from file: node1 => node2 => node3"


def test_from_file_short_option():
    """Test reading workflow from file using short option."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a test workflow file
        with open("test.pflow", "w") as f:
            f.write("plan a backup strategy")

        result = runner.invoke(main, ["-f", "test.pflow"])

        assert result.exit_code == 0
        assert result.output.strip() == "Collected workflow from file: plan a backup strategy"


def test_from_file_with_whitespace():
    """Test file content whitespace is stripped."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a test workflow file with extra whitespace
        with open("workflow.txt", "w") as f:
            f.write("\n\n  read-file => process  \n\n")

        result = runner.invoke(main, ["--file", "workflow.txt"])

        assert result.exit_code == 0
        assert result.output.strip() == "Collected workflow from file: read-file => process"


def test_from_file_missing():
    """Test error when file doesn't exist."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["--file", "nonexistent.txt"])

    assert result.exit_code != 0
    assert "does not exist" in result.output or "Error" in result.output


# Tests for error cases
def test_error_file_and_args():
    """Test error when both file and arguments are provided."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a test file
        with open("workflow.txt", "w") as f:
            f.write("node1")

        result = runner.invoke(main, ["--file", "workflow.txt", "node2"])

        assert result.exit_code != 0
        assert "Cannot specify both --file and command arguments" in result.output


def test_error_stdin_and_args():
    """Test error when both stdin and arguments are provided."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["node1"], input="node2 => node3")

    assert result.exit_code != 0
    assert "Cannot specify both stdin and command arguments" in result.output


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
        assert result.output.strip() == "Collected workflow from file: from-file"


# Tests for context storage
def test_context_storage_verification():
    """Test that context stores raw input and source correctly."""
    # Test through standard CLI invocation and verify output format
    runner = click.testing.CliRunner()

    # Test args input
    result = runner.invoke(main, ["test", "workflow"])
    assert result.exit_code == 0
    assert "Collected workflow from args: test workflow" in result.output

    # Test stdin input
    result = runner.invoke(main, [], input="stdin workflow")
    assert result.exit_code == 0
    assert "Collected workflow from stdin: stdin workflow" in result.output

    # Test file input
    with runner.isolated_filesystem():
        with open("test.pflow", "w") as f:
            f.write("file workflow")

        result = runner.invoke(main, ["--file", "test.pflow"])
        assert result.exit_code == 0
        assert "Collected workflow from file: file workflow" in result.output
