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
    assert result.output.strip() == "Collected workflow: node1 node2"


def test_run_preserves_double_arrow():
    """Test that >> operator is preserved."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["run", "node1", ">>", "node2"])

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow: node1 >> node2"


def test_run_with_quoted_strings():
    """Test handling of quoted strings."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["run", "plan", "a backup strategy"])

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow: plan a backup strategy"


def test_run_with_flags():
    """Test handling of flags with values."""
    runner = click.testing.CliRunner()
    # Using -- to prevent click from parsing the flags
    result = runner.invoke(main, ["run", "--", "node1", "--flag=value", ">>", "node2"])

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow: node1 --flag=value >> node2"


def test_run_empty_arguments():
    """Test handling of empty arguments."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["run"])

    assert result.exit_code == 0
    assert result.output.strip() == "Collected workflow:"


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
    expected = (
        "Collected workflow: read-file --path=input.txt >> llm --prompt=Summarize this >> write-file --path=output.txt"
    )
    assert result.output.strip() == expected
