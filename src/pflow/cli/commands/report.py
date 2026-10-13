"""Report command — generate readable report from workflow traces."""

from pathlib import Path

import click


def _is_complete_run(path: Path) -> bool:
    """Whether a trace is a FINISHED run: a trailer (one tail read), then a full load that is not
    ``incomplete``. Eager-``meta`` (Task 173) leaves an in-flight or crashed run on disk from t=0, so this is
    what keeps a hollow "incomplete, 0 nodes" file from shadowing the last good run. Raises on any read or
    parse fault (``FileNotFoundError`` included) — the caller decides what each means."""
    from pflow.core.trace_dir import read_trace_trailer_strict
    from pflow.core.trace_io import load_trace_file

    if read_trace_trailer_strict(path) is None:
        return False
    return load_trace_file(path).get("final_status") != "incomplete"


def _latest_complete_trace(ctx: click.Context) -> Path:
    """The newest COMPLETE trace by start time (the one recency rule, ``trace_dir.list_traces``), or exit 1.

    Walks newest-first, lazily — never a read of every file. A trace that vanished since the listing is
    passed over; one that cannot be read or parsed, at either read, is named on stderr with its cause, so
    "latest" never silently means an older run."""
    import json

    from pflow.core.trace_dir import TraceUnreadableError, legacy_note, list_traces

    listing = list_traces()
    note = legacy_note(listing.legacy_count)
    unsearched = f" ({note}; pass a path: `pflow report <path>`)" if note else ""
    if not listing.traces:
        click.echo(f"No trace files found in ~/.pflow/debug/{unsearched}", err=True)
        ctx.exit(1)
    skipped = 0
    for entry in listing.traces:
        try:
            if _is_complete_run(entry.path):
                return entry.path
            continue
        except FileNotFoundError:
            continue
        except TraceUnreadableError as exc:
            reason = str(exc)
        except OSError as exc:
            reason = f"could not read trace {entry.path}: {exc.strerror or exc}"
        except json.JSONDecodeError as exc:
            reason = f"could not parse trace {entry.path}: {exc.msg}"
        skipped += 1
        click.echo(f"Skipped a newer trace — {reason}", err=True)
    if skipped:
        click.echo(
            f"No readable completed trace found in ~/.pflow/debug/ ({skipped} could not be read — named above). "
            f"Fix the file's permissions and retry, or pass a specific trace path.{unsearched}",
            err=True,
        )
    else:
        click.echo(
            "No completed trace found in ~/.pflow/debug/ (only in-flight or interrupted runs). "
            f"Run the workflow to completion, or pass a specific trace path.{unsearched}",
            err=True,
        )
    ctx.exit(1)


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
        pflow report ~/.pflow/debug/workflow-trace-3f2a1b9c-my-wf.0b7e6a52-1c4d-4e8f-9a3b-5d6c7e8f9a0b-20260412-093015-123456.json
        pflow report -o ./report/
    """
    from pflow.cli.error_output import output_error
    from pflow.core.exceptions import ReportGenerationError
    from pflow.core.trace_report import generate_report

    if trace_path is None:
        chosen = _latest_complete_trace(ctx)
        trace_path = str(chosen)
        click.echo(f"Using latest trace: {trace_path}", err=True)

    trace_file = Path(trace_path)
    if not trace_file.exists():
        from pflow.core.trace_dir import AGED_OUT_HINT

        click.echo(f"Trace file not found: {trace_path} (if it was a run's trace, {AGED_OUT_HINT})", err=True)
        ctx.exit(1)

    try:
        report_dir = generate_report(trace_path, output_path or "auto")
    except ReportGenerationError as exc:
        output_error(exception=exc)
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
