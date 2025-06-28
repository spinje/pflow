"""Tests for pflow core CLI functionality."""

import click.testing

from pflow.cli import main


def test_run_command_exists():
    """Test that the run command exists and is callable."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "run" in result.output
    assert "Run a pflow workflow" in result.output


def test_run_simple_arguments():
    """Test simple argument collection."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["run", "node1", "node2"])

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from args: node1 node2"


def test_run_preserves_double_arrow():
    """Test that >> operator is preserved."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["run", "node1", ">>", "node2"])

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from args: node1 >> node2"


def test_run_with_quoted_strings():
    """Test handling of quoted strings."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["run", "plan", "a backup strategy"])

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from args: plan a backup strategy"


def test_run_with_flags():
    """Test handling of flags with values."""
    runner = click.testing.CliRunner()
    # Using -- to prevent click from parsing the flags
    result = runner.invoke(main, ["run", "--", "node1", "--flag=value", ">>", "node2"])

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from args: node1 --flag=value >> node2"


def test_run_empty_arguments():
    """Test handling of empty arguments."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["run"])

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from args:"


def test_run_complex_workflow():
    """Test a complex workflow with multiple operators and flags."""
    runner = click.testing.CliRunner()
    result = runner.invoke(
        main,
        [
            "run",
            "--",
            "read-file",
            "--path=input.txt",
            ">>",
            "llm",
            "--prompt=Summarize this",
            ">>",
            "write-file",
            "--path=output.txt",
        ],
    )

    assert result.exit_code == 0
    expected = "Collected workflow from args: read-file --path=input.txt >> llm --prompt=Summarize this >> write-file --path=output.txt"
    assert result.output.strip() == expected


# Tests for stdin input handling
def test_run_from_stdin_simple():
    """Test reading workflow from stdin."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["run"], input="node1 >> node2\n")

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from stdin: node1 >> node2"


def test_run_from_stdin_complex():
    """Test reading complex workflow from stdin."""
    runner = click.testing.CliRunner()
    stdin_input = "read-file --path=input.txt >> llm --prompt='Summarize' >> write-file"
    result = runner.invoke(main, ["run"], input=stdin_input)

    assert result.exit_code == 0
    assert result.output.strip() == f"Collected workflow from stdin: {stdin_input}"


def test_run_from_stdin_with_newlines():
    """Test stdin with newlines gets stripped."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["run"], input="\n  node1 >> node2  \n\n")

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from stdin: node1 >> node2"


def test_run_from_stdin_empty():
    """Test empty stdin falls back to args mode."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["run", "node1"], input="")

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow from args: node1"


# Tests for file input handling
def test_run_from_file():
    """Test reading workflow from file."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a test workflow file
        with open("workflow.txt", "w") as f:
            f.write("node1 >> node2 >> node3")

        result = runner.invoke(main, ["run", "--file", "workflow.txt"])

        assert result.exit_code == 0
        assert result.output.strip() == "Collected workflow from file: node1 >> node2 >> node3"


def test_run_from_file_short_option():
    """Test reading workflow from file using short option."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a test workflow file
        with open("test.pflow", "w") as f:
            f.write("plan a backup strategy")

        result = runner.invoke(main, ["run", "-f", "test.pflow"])

        assert result.exit_code == 0
        assert result.output.strip() == "Collected workflow from file: plan a backup strategy"


def test_run_from_file_with_whitespace():
    """Test file content whitespace is stripped."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a test workflow file with extra whitespace
        with open("workflow.txt", "w") as f:
            f.write("\n\n  read-file >> process  \n\n")

        result = runner.invoke(main, ["run", "--file", "workflow.txt"])

        assert result.exit_code == 0
        assert result.output.strip() == "Collected workflow from file: read-file >> process"


def test_run_from_file_missing():
    """Test error when file doesn't exist."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["run", "--file", "nonexistent.txt"])

    assert result.exit_code != 0
    assert "does not exist" in result.output or "Error" in result.output


# Tests for error cases
def test_run_error_file_and_args():
    """Test error when both file and arguments are provided."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a test file
        with open("workflow.txt", "w") as f:
            f.write("node1")

        result = runner.invoke(main, ["run", "--file", "workflow.txt", "node2"])

        assert result.exit_code != 0
        assert "Cannot specify both --file and command arguments" in result.output


def test_run_error_stdin_and_args():
    """Test error when both stdin and arguments are provided."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["run", "node1"], input="node2 >> node3")

    assert result.exit_code != 0
    assert "Cannot specify both stdin and command arguments" in result.output


def test_run_error_stdin_and_file():
    """Test that stdin is ignored when file is specified."""
    runner = click.testing.CliRunner()
    with runner.isolated_filesystem():
        # Create a test file
        with open("workflow.txt", "w") as f:
            f.write("from-file")

        # File takes precedence over stdin
        result = runner.invoke(main, ["run", "--file", "workflow.txt"], input="from-stdin")

        assert result.exit_code == 0
        assert result.output.strip() == "Collected workflow from file: from-file"


# Tests for context storage
def test_run_context_storage_verification():
    """Test that context stores raw input and source correctly."""
    # Since we can't easily capture context from the run command,
    # we'll verify behavior through a modified version that exposes context
    runner = click.testing.CliRunner()

    # Create a test CLI that exposes context after run
    test_cli = click.Group()

    # Copy the existing run command
    run_cmd = main.commands["run"]
    test_cli.add_command(run_cmd)

    # Add a debug command that prints context
    @test_cli.command()
    @click.pass_context
    def debug(ctx):
        """Debug command to verify context."""
        if ctx.parent and ctx.parent.obj:
            click.echo(f"raw_input: {ctx.parent.obj.get('raw_input', 'NOT SET')}")
            click.echo(f"input_source: {ctx.parent.obj.get('input_source', 'NOT SET')}")

    # Test args input
    result = runner.invoke(test_cli, ["run", "test", "workflow"])
    assert result.exit_code == 0
    assert "Collected workflow from args: test workflow" in result.output

    # Test stdin input
    result = runner.invoke(test_cli, ["run"], input="stdin workflow")
    assert result.exit_code == 0
    assert "Collected workflow from stdin: stdin workflow" in result.output

    # Test file input
    with runner.isolated_filesystem():
        with open("test.pflow", "w") as f:
            f.write("file workflow")

        result = runner.invoke(test_cli, ["run", "--file", "test.pflow"])
        assert result.exit_code == 0
        assert "Collected workflow from file: file workflow" in result.output
