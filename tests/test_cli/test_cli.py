"""Tests for the pflow CLI."""

from pathlib import Path
from typing import Any

import click.testing
import pytest

from pflow.cli.main import main
from tests.shared.trace_jsonl import write_trace_jsonl


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
    write_trace_jsonl(trace_file, _make_trace())
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


def test_report_command_echoes_summary_to_stderr(tmp_path: Path, monkeypatch):
    """pflow report writes summary.md AND echoes its content to stderr."""
    trace_file = tmp_path / "trace.json"
    write_trace_jsonl(
        trace_file,
        _make_trace(
            nodes=[
                {
                    "node_id": "fetch",
                    "node_type": "ShellNode",
                    "duration_ms": 200.0,
                    "success": True,
                    "timestamp": "2026-03-23T10:00:01",
                }
            ]
        ),
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = click.testing.CliRunner(mix_stderr=False)
    report_dir = tmp_path / "report"
    result = runner.invoke(main, ["report", str(trace_file), "-o", str(report_dir)])

    assert result.exit_code == 0, f"Report failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    # stdout is just the path (pipe-safe)
    assert result.stdout.strip() == str(report_dir)
    # stderr carries the human-readable summary, including the new column header
    assert "Report generated:" in result.stderr
    assert "## Pipeline" in result.stderr
    assert "| # | Node | Type | Status | Time | Tokens | Cost |" in result.stderr
    assert "| 1 | fetch | shell | success |" in result.stderr


def test_report_command_stdout_remains_just_the_path(tmp_path: Path, monkeypatch):
    """Pipe-safety regression guard: stdout MUST stay equal to <report_dir>\\n."""
    trace_file = tmp_path / "trace.json"
    write_trace_jsonl(trace_file, _make_trace())
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = click.testing.CliRunner(mix_stderr=False)
    report_dir = tmp_path / "report"
    result = runner.invoke(main, ["report", str(trace_file), "-o", str(report_dir)])

    assert result.exit_code == 0
    # Exactly one line on stdout: the report directory.
    assert result.stdout == f"{report_dir}\n"


def _write_jsonl_trace(path: Path, lines: list[dict[str, Any]]) -> Path:
    """Write hand-built JSONL trace lines verbatim.

    Unlike `write_trace_jsonl` (which always appends a `run.complete` line), this lets a fixture
    OMIT `run.complete` to produce the genuine `final_status="incomplete"` shape that eager-`meta`
    (Task 173) leaves on disk for an in-flight / crash-before-first-completion run.
    """
    import json

    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return path


# meta + event + run.complete → loads as final_status="success"
_COMPLETE_TRACE_LINES: list[dict[str, Any]] = [
    {
        "kind": "meta",
        "pflow_trace": "jsonl/1",
        "workflow_path": "wf.pflow.md",
        "execution_id": "complete-run",
        "format_version": "2.x",
    },
    {
        "kind": "event",
        "node_id": "a",
        "id": 0,
        "seq": 0,
        "parent_id": None,
        "ancestor_path": [],
        "port": None,
        "status": "success",
    },
    {"kind": "run.complete", "final_status": "success", "nodes_executed": 1, "failed_node_ids": []},
]

# meta + node.start, NO run.complete → loads as final_status="incomplete" (eager-`meta` in-flight run)
_INCOMPLETE_TRACE_LINES: list[dict[str, Any]] = [
    {
        "kind": "meta",
        "pflow_trace": "jsonl/1",
        "workflow_path": "wf.pflow.md",
        "execution_id": "in-flight-run",
        "format_version": "2.x",
    },
    {"kind": "node.start", "node_id": "a", "id": 0, "seq": 0, "parent_id": None},
]


def test_report_autoselect_prefers_newest_complete_over_newer_incomplete(tmp_path: Path, monkeypatch):
    """No-arg `pflow report` skips a NEWER in-flight/incomplete trace for the newest COMPLETE one.

    Task 173 eager-`meta` leaves a `meta`-only `incomplete` file from t=0; the old "newest by mtime"
    auto-select would let it shadow the user's last good run with a hollow 0-node report.
    """
    import os

    from pflow.core.trace_io import load_trace_file

    debug_dir = tmp_path / ".pflow" / "debug"
    debug_dir.mkdir(parents=True)

    complete = _write_jsonl_trace(debug_dir / "workflow-trace-complete.json", _COMPLETE_TRACE_LINES)
    incomplete = _write_jsonl_trace(debug_dir / "workflow-trace-incomplete.json", _INCOMPLETE_TRACE_LINES)

    # Make the INCOMPLETE file strictly newer so a naive mtime sort would pick it.
    os.utime(complete, (1_000_000, 1_000_000))
    os.utime(incomplete, (2_000_000, 2_000_000))

    # Guard against fixture theater: confirm the files actually load as the statuses the test relies on.
    assert load_trace_file(complete).get("final_status") == "success"
    assert load_trace_file(incomplete).get("final_status") == "incomplete"

    monkeypatch.setenv("HOME", str(tmp_path))
    runner = click.testing.CliRunner(mix_stderr=False)
    result = runner.invoke(main, ["report"])

    assert result.exit_code == 0, f"Report failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    # The "Using latest trace:" stderr line names the chosen trace — it must be the COMPLETE one.
    assert "Using latest trace:" in result.stderr
    assert str(complete) in result.stderr
    assert str(incomplete) not in result.stderr


def test_report_autoselect_only_incomplete_errors_clearly(tmp_path: Path, monkeypatch):
    """With only in-flight/incomplete traces, no-arg `pflow report` errors and exits 1 — not a hollow report."""
    from pflow.core.trace_io import load_trace_file

    debug_dir = tmp_path / ".pflow" / "debug"
    debug_dir.mkdir(parents=True)

    incomplete = _write_jsonl_trace(debug_dir / "workflow-trace-incomplete.json", _INCOMPLETE_TRACE_LINES)
    assert load_trace_file(incomplete).get("final_status") == "incomplete"

    monkeypatch.setenv("HOME", str(tmp_path))
    runner = click.testing.CliRunner(mix_stderr=False)
    result = runner.invoke(main, ["report"])

    assert result.exit_code == 1, f"Expected exit 1; stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "No completed trace" in result.stderr
    # It must NOT fall through to generating a report from the incomplete trace.
    assert "Using latest trace:" not in result.stderr


@pytest.mark.trace_files
def test_run_report_flag_echoes_summary_to_stderr(tmp_path: Path, monkeypatch):
    """`pflow <workflow> --report` mirrors the inline stderr echo."""
    workflow = tmp_path / "test.pflow.md"
    workflow.write_text(
        "# Test\n\n## Steps\n\n### hello\n\nSay hello.\n\n- type: shell\n- cache: false\n- command: echo hi\n"
    )
    report_dir = tmp_path / "report"

    monkeypatch.setenv("HOME", str(tmp_path))
    runner = click.testing.CliRunner(mix_stderr=False)
    result = runner.invoke(main, [str(workflow), "--report-dir", str(report_dir)])

    assert result.exit_code == 0, f"Workflow failed: stderr={result.stderr!r}"
    # The "📋 Execution report" line is already part of stderr; the summary
    # table now follows it.
    assert "📋 Execution report" in result.stderr
    assert "## Pipeline" in result.stderr
    assert "| 1 | hello | shell | success |" in result.stderr
    # Pipe-safety guard: stdout must NOT carry the summary even when the workflow
    # also writes its own output (here `hi`). A regression routing _echo_trace
    # to stdout would surface the table here.
    assert "## Pipeline" not in result.stdout
    assert "📋 Execution report" not in result.stdout
