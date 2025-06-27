"""Tests for the pflow CLI."""

import click.testing

from pflow.cli import main


def test_cli_entry_point_imports():
    """Test that the CLI entry point can be imported without errors."""
    # The import at the top of this file already tests this
    # but we make it explicit here
    assert main is not None
    assert callable(main)


def test_cli_help_command():
    """Test that the help command shows expected output."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "pflow - workflow compiler for deterministic CLI commands." in result.output
    assert "Commands:" in result.output
    assert "version" in result.output


def test_version_command():
    """Test that the version command outputs the correct version."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == "pflow version 0.0.1"


def test_invalid_command():
    """Test that invalid commands show appropriate error."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["invalid-command"])

    assert result.exit_code != 0
    assert "Error" in result.output or "No such command" in result.output


def test_no_arguments():
    """Test that running with no arguments shows help."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [])

    # Click groups return exit code 2 when no command is provided
    assert result.exit_code == 2
    assert "Commands:" in result.output
    assert "pflow - workflow compiler for deterministic CLI commands." in result.output
