"""Tests for the pflow CLI."""

import json
from pathlib import Path
from typing import Any

import click.testing
import pytest

from pflow.cli.main import main


def _make_trace(nodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "format_version": "2.0.0",
        "execution_id": "test-exec-id",
        "workflow_name": "test-workflow",
        "start_time": "2026-03-23T10:00:00",
        "end_time": "2026-03-23T10:00:05",
        "duration_ms": 5000.0,
        "final_status": "success",
        "nodes_executed": len(nodes) if nodes else 0,
        "nodes_failed": 0,
        "nodes": nodes or [],
    }


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
    assert (report_dir / ".pflow-report.json").exists(), "report marker not created"
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


def test_report_command_refuses_non_empty_unmarked_output_dir(tmp_path: Path, monkeypatch):
    """pflow report -o protects arbitrary non-empty user directories."""
    monkeypatch.setenv("HOME", str(tmp_path))
    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps(_make_trace()))
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    existing = report_dir / "notes.md"
    existing.write_text("keep")

    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["report", str(trace_file), "-o", str(report_dir)])

    assert result.exit_code == 1
    assert "without .pflow-report.json" in result.output
    assert existing.read_text() == "keep"
    assert not (report_dir / "summary.md").exists()


@pytest.mark.trace_files
def test_report_dir_preflight_refuses_before_workflow_execution(tmp_path: Path, monkeypatch):
    """Unsafe --report-dir fails before shell side effects can run."""
    side_effect = tmp_path / "side-effect.txt"
    workflow = tmp_path / "test.pflow.md"
    workflow.write_text(
        "# Test\n\n"
        "## Steps\n\n"
        "### hello\n\n"
        "Say hello.\n\n"
        "- type: shell\n"
        "- cache: false\n"
        f"- command: echo ran > {side_effect}\n"
    )
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    (report_dir / "notes.md").write_text("keep")

    monkeypatch.setenv("HOME", str(tmp_path))
    runner = click.testing.CliRunner()
    result = runner.invoke(main, [str(workflow), "--report-dir", str(report_dir)])

    assert result.exit_code == 1
    assert "without .pflow-report.json" in result.output
    assert not side_effect.exists()


@pytest.mark.trace_files
def test_auto_report_rerun_with_only_removes_downstream_pages(tmp_path: Path, monkeypatch):
    """Default reports remain coherent after a later partial --only run."""
    workflow = tmp_path / "test.pflow.md"
    workflow.write_text(
        "# Test\n\n"
        "## Steps\n\n"
        "### first\n\n"
        "First step.\n\n"
        "- type: shell\n"
        "- cache: false\n"
        "- command: echo first\n\n"
        "### second\n\n"
        "Second step.\n\n"
        "- type: shell\n"
        "- cache: false\n"
        "- command: echo second\n"
    )
    report_dir = tmp_path / ".pflow" / "reports" / "test"

    monkeypatch.setenv("HOME", str(tmp_path))
    runner = click.testing.CliRunner()
    full_result = runner.invoke(main, [str(workflow), "--report"])
    assert full_result.exit_code == 0, f"Workflow failed: {full_result.output}"
    assert (report_dir / "01-first.md").exists()
    assert (report_dir / "02-second.md").exists()

    only_result = runner.invoke(main, [str(workflow), "--report", "--only", "first"])

    assert only_result.exit_code == 0, f"Workflow failed: {only_result.output}"
    assert (report_dir / "01-first.md").exists()
    assert not (report_dir / "02-second.md").exists()
    assert (report_dir / ".pflow-report.json").exists()
    assert "Nodes: 1/2 (--only 'first', 1 skipped)" in (report_dir / "summary.md").read_text()
