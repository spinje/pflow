"""``pflow analyze-cache <workflow> [params...]`` — Tier 2 + Tier 3 analyzer.

Wraps :func:`pflow.core.cache_analysis.analyze` for human / agent consumption.
Output modes per spec § "Output Format — Text" and "Output Format — JSON".

Exit code contract (per F3.1 plan section — 9 conditions):

- ``0``   on successful analysis (any output mode); analytical findings of any
          severity are advisory per DD#36 and do NOT change exit code.
- ``≠ 0`` on workflow path unparseable, validation errors that prevent IR
          construction, missing ``--from-trace`` path, invalid trace JSON, or
          internal analyzer crashes (NEVER silently emit empty JSON for an
          internal failure).
"""

from __future__ import annotations

from pathlib import Path

import click


@click.command("analyze-cache")
@click.argument("workflow")
@click.argument("params", nargs=-1)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format: text (default, human-readable) or json (agent-facing).",
)
@click.option(
    "--from-trace",
    "from_trace",
    type=click.Path(exists=False, dir_okay=False),
    default=None,
    help="Explicit trace file to load for discrepancy mode. Accepts any 2.x trace.",
)
@click.option(
    "--no-trace-autoload",
    is_flag=True,
    default=False,
    help=(
        "Disable auto-loading the most recent matching trace from "
        "~/.pflow/debug/. Note: this flag is named --no-trace-autoload to avoid "
        "colliding with `pflow run --no-trace` (which disables trace SAVING)."
    ),
)
@click.option(
    "--all-rows",
    is_flag=True,
    default=False,
    help=("Show every node in the per-call cache report. Default hides rows with cache ratio ≥80%% and no warnings."),
)
@click.pass_context
def analyze_cache(
    ctx: click.Context,
    workflow: str,
    params: tuple[str, ...],
    output_format: str,
    from_trace: str | None,
    no_trace_autoload: bool,
    all_rows: bool,
) -> None:
    """Analyze a workflow's cache plan; emit recommendations and discrepancies.

    Examples:

        pflow analyze-cache workflow.pflow.md
        pflow analyze-cache workflow.pflow.md --format=json
        pflow analyze-cache workflow.pflow.md --from-trace ~/.pflow/debug/trace.json
        pflow analyze-cache workflow.pflow.md --no-trace-autoload
    """
    # Mutually-exclusive flag gate — Click validation error shape, exit non-zero.
    if from_trace is not None and no_trace_autoload:
        click.echo(
            "Error: --from-trace and --no-trace-autoload are mutually exclusive.",
            err=True,
        )
        ctx.exit(2)
        return

    # Lazy imports — analysis pulls in LiteLLM via token_estimation, no need
    # to pay the import cost on every CLI invocation.
    from pflow.cli.param_parsing import parse_workflow_params
    from pflow.core.cache_analysis import analyze, render_json, render_text
    from pflow.core.diagnostic import exception_to_diagnostics
    from pflow.core.diagnostic_render import format_diagnostic
    from pflow.execution.workflow_resolver import resolve_workflow

    # Resolve the workflow (file path or saved name).
    try:
        resolved = resolve_workflow(workflow)
    except Exception as e:
        for diagnostic in exception_to_diagnostics(e):
            click.echo(format_diagnostic(diagnostic), err=True)
        ctx.exit(1)
        return

    # Parse optional params (per DD#35: inputs are optional; analysis falls back
    # gracefully when input substitution can't fully resolve a prompt).
    try:
        parsed_params = parse_workflow_params(params)
    except Exception as e:
        for diagnostic in exception_to_diagnostics(e):
            click.echo(format_diagnostic(diagnostic), err=True)
        ctx.exit(1)
        return

    # Resolve trace_path argument.
    trace_path = Path(from_trace) if from_trace else None

    base_path = Path(resolved.file_path).parent if resolved.file_path else None
    # Inline workflows pass ``None``; ``analyze()`` derives the canonical
    # ``ir-hash:<md5>`` identifier internally so autoload + memo + cross-workflow
    # lookups correlate with what the trace writer / memo cache used at run
    # time. The displayed ``"<inline>"`` label is computed separately inside
    # ``analyze()`` for the rendered output.
    workflow_path_str = resolved.file_path

    # Run the analyzer. Internal exceptions propagate so the CLI exits non-zero
    # rather than emitting empty-but-valid JSON (per the silent-failures rule
    # in F3.1: NEVER silently emit empty JSON for an internal failure).
    try:
        analysis = analyze(
            resolved.ir,
            parameters=parsed_params,
            workflow_path=workflow_path_str,
            base_path=base_path,
            trace_path=trace_path,
            auto_load_trace=not no_trace_autoload,
        )
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo(
            "Suggestion: check the path. Auto-load reads from ~/.pflow/debug/; "
            "for explicit override pass an existing trace JSON.",
            err=True,
        )
        ctx.exit(1)
        return
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        ctx.exit(1)
        return

    # Successful analysis — render to chosen format.
    if output_format == "json":
        import json

        click.echo(json.dumps(render_json(analysis), indent=2))
    else:
        click.echo(render_text(analysis, all_rows=all_rows))


__all__ = ["analyze_cache"]
