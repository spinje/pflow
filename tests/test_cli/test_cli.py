"""Tests for the pflow CLI."""

import click.testing

from pflow.cli.main import main


def test_cli_help_command():
    """Test that the help command shows expected output."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "pflow - Plan Once, Run Forever" in result.output
    assert "Natural language to deterministic workflows" in result.output
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
    """Test that running with no arguments shows error."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [])

    # With no arguments, it should show an error
    assert result.exit_code != 0
    assert "cli: No workflow provided" in result.output
