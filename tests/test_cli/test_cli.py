"""Tests for the pflow CLI."""

from pathlib import Path

import click.testing
import pytest

from pflow.cli.main import main


def test_cli_help_command():
    """Test that the help command shows expected output."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "Commands:" in result.output
    assert "--version" in result.output


def test_version_flag():
    """Test that the version flag outputs the correct version."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip().startswith("pflow version ")


def test_workflow_arguments():
    """Test that unquoted multi-word arguments show validation error."""
    # Updated for planner validation - unquoted multi-word input now errors
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["node1", "=>", "node2"])

    assert result.exit_code == 1
    assert "Invalid input" in result.output or "must be quoted" in result.output


def test_no_arguments():
    """Test that running with no arguments shows group help."""
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [])

    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_report_command_no_traces(tmp_path: Path, monkeypatch):
    """pflow report with no trace files gives a clear error, not a crash."""
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["report"])

    assert result.exit_code == 1
    assert "No trace files found" in result.output


@pytest.mark.trace_files
def test_report_command_generates_from_trace(tmp_path: Path, monkeypatch):
    """pflow report reads the latest trace and produces a report directory."""
    # Run a workflow first to generate a trace
    workflow = tmp_path / "test.pflow.md"
    workflow.write_text(
        "# Test\n\n## Steps\n\n### hello\n\nSay hello.\n\n- type: shell\n- cache: false\n- command: echo hi\n"
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = click.testing.CliRunner()

    # Generate a trace via workflow execution
    run_result = runner.invoke(main, [str(workflow)])
    assert run_result.exit_code == 0, f"Workflow failed: {run_result.output}"

    # Now run pflow report — should pick up the trace and produce a report
    result = runner.invoke(main, ["report"])
    assert result.exit_code == 0, f"Report failed: {result.output}"
    assert "Report generated" in result.output


@pytest.mark.trace_files
def test_report_flag_generates_report(tmp_path: Path, monkeypatch):
    """Test that --report flag generates an execution report directory."""
    # Create a minimal workflow
    workflow = tmp_path / "test.pflow.md"
    workflow.write_text(
        "# Test\n\n## Steps\n\n### hello\n\nSay hello.\n\n- type: shell\n- cache: false\n- command: echo hi\n"
    )
    report_dir = tmp_path / "report"

    monkeypatch.setenv("HOME", str(tmp_path))
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [str(workflow), "--report-dir", str(report_dir)])

    assert result.exit_code == 0, f"Workflow failed: {result.output}"
    assert report_dir.exists(), "Report directory not created"
    assert (report_dir / "summary.md").exists(), "summary.md not created"
    # Verify the node file exists
    node_files = list(report_dir.glob("*-hello.md"))
    assert len(node_files) == 1, f"Expected 1 node file, got {node_files}"


@pytest.mark.trace_files
def test_report_flag_overrides_no_trace(tmp_path: Path, monkeypatch):
    """Test that --report overrides --no-trace (report requires trace data)."""
    workflow = tmp_path / "test.pflow.md"
    workflow.write_text(
        "# Test\n\n## Steps\n\n### hello\n\nSay hello.\n\n- type: shell\n- cache: false\n- command: echo hi\n"
    )
    report_dir = tmp_path / "report"

    monkeypatch.setenv("HOME", str(tmp_path))
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [str(workflow), "--report-dir", str(report_dir), "--no-trace"])

    assert result.exit_code == 0, f"Workflow failed: {result.output}"
    assert report_dir.exists(), "Report not generated despite --report overriding --no-trace"
    assert (report_dir / "summary.md").exists()
