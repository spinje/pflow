"""Report command — generate readable report from workflow traces."""

from pathlib import Path

import click


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
    from pflow.core.trace_report import generate_report

    if trace_path is None:
        # Auto-detect latest trace
        debug_dir = Path.home() / ".pflow" / "debug"
        if not debug_dir.exists():
            click.echo("No trace files found in ~/.pflow/debug/", err=True)
            ctx.exit(1)
        traces = sorted(debug_dir.glob("workflow-trace-*.json"), key=lambda p: p.stat().st_mtime)
        if not traces:
            click.echo("No trace files found in ~/.pflow/debug/", err=True)
            ctx.exit(1)
        trace_path = str(traces[-1])
        click.echo(f"Using latest trace: {trace_path}", err=True)

    trace_file = Path(trace_path)
    if not trace_file.exists():
        click.echo(f"Trace file not found: {trace_path}", err=True)
        ctx.exit(1)

    report_dir = generate_report(trace_path, output_path or "auto")
    if report_dir:
        click.echo(str(report_dir))  # stdout — pipeable for scripting
        click.echo(f"Report generated: {report_dir}", err=True)
    else:
        click.echo(
            "Failed to generate report. The trace may use an older format (requires 2.0.0+).",
            err=True,
        )
        ctx.exit(1)
