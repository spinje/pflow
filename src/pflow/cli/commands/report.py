"""Report command — generate readable report from workflow traces."""

from pathlib import Path

import click


def _trace_is_complete(path: Path) -> bool:
    """True if the trace loads as a FINISHED run — not an eager-``meta`` / crash-tail ``incomplete`` file.

    The no-arg ``pflow report`` auto-select uses this to skip in-flight / interrupted traces, which
    eager-``meta`` (Task 173) now leaves on disk from t=0 (before this, a crash left no file). Unreadable
    or legacy single-object traces also report False (they can't be reported anyway)."""
    import json

    from pflow.core.trace_io import load_trace_file

    try:
        return load_trace_file(path).get("final_status") != "incomplete"
    except (json.JSONDecodeError, OSError):
        return False


@click.command("report")
@click.argument("trace_path", required=False, default=None)
@click.option("--output", "-o", "output_path", default=None, help="Output directory")
@click.pass_context
def report_cmd(ctx: click.Context, trace_path: str | None, output_path: str | None) -> None:
    """Generate a readable report from a workflow trace.

    Produces a directory of markdown files — one per node — for
    complex debugging when error messages alone aren't enough.

    \b
    The report includes:
      summary.md   Pipeline overview, errors with fix suggestions, cost
      01-node.md   Per-node: resolved inputs, outputs, timing, errors

    If no trace path given, uses the most recent trace.

    \b
    Examples:
        pflow report
        pflow report ~/.pflow/debug/workflow-trace-my-wf-20260412.json
        pflow report -o ./report/
    """
    from pflow.cli.error_output import output_error
    from pflow.core.exceptions import ReportGenerationError
    from pflow.core.trace_report import generate_report

    if trace_path is None:
        # Auto-detect latest trace
        debug_dir = Path.home() / ".pflow" / "debug"
        if not debug_dir.exists():
            click.echo("No trace files found in ~/.pflow/debug/", err=True)
            ctx.exit(1)
        traces = sorted(debug_dir.glob("workflow-trace-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not traces:
            click.echo("No trace files found in ~/.pflow/debug/", err=True)
            ctx.exit(1)
        # Prefer the newest COMPLETE trace. Eager-`meta` (Task 173) means an in-flight or
        # crash-before-first-completion run now leaves a `meta`-only / `incomplete` file from t=0; picking
        # it would shadow the user's last good run with a hollow "incomplete, 0 nodes" report. Skip
        # incomplete (and unreadable/legacy) candidates, newest-first.
        chosen = next((candidate for candidate in traces if _trace_is_complete(candidate)), None)
        if chosen is None:
            click.echo(
                "No completed trace found in ~/.pflow/debug/ (only in-flight or interrupted runs). "
                "Run the workflow to completion, or pass a specific trace path.",
                err=True,
            )
            ctx.exit(1)
        trace_path = str(chosen)
        click.echo(f"Using latest trace: {trace_path}", err=True)

    trace_file = Path(trace_path)
    if not trace_file.exists():
        click.echo(f"Trace file not found: {trace_path}", err=True)
        ctx.exit(1)

    try:
        report_dir = generate_report(trace_path, output_path or "auto")
    except ReportGenerationError as exc:
        output_error(ctx, exception=exc)
        ctx.exit(1)
    if report_dir:
        click.echo(str(report_dir))  # stdout — pipeable for scripting
        click.echo(f"Report generated: {report_dir}", err=True)
        summary_path = report_dir / "summary.md"
        try:
            summary_text = summary_path.read_text(encoding="utf-8")
        except OSError:
            pass
        else:
            # Trailing newline matches the parallel echo in run.py via
            # _echo_trace — keep the two sites in sync.
            click.echo("", err=True)
            click.echo(summary_text, err=True)
    else:
        click.echo(
            "Failed to generate report. The trace may use an older format (requires 2.0.0+).",
            err=True,
        )
        ctx.exit(1)
