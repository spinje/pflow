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
    assert "Execute workflows using the =>" in result.output
    assert "--version" in result.output


def test_version_flag():
    """Test that the version flag outputs the correct version."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == "pflow version 0.0.1"


def test_workflow_arguments():
    """Test that workflow arguments are collected."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["node1", "=>", "node2"])

    assert result.exit_code == 0
    assert "Collected workflow from args: node1 => node2" in result.output


def test_no_arguments():
    """Test that running with no arguments collects empty workflow."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [])

    # With no arguments, it should still run and collect empty workflow
    assert result.exit_code == 0
    assert "Collected workflow from args:" in result.output
