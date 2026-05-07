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

JSON error envelope (per Task 159 PR #378 review #6): when ``--format=json``
is requested AND an error fires, the CLI emits a structured envelope to
stdout (parseable by the agent) AND a human-readable line to stderr. The
envelope shape is::

    {
        "format_version": "<JSON_FORMAT_VERSION>",
        "error": {
            "id": "analyze-cache.<kind>",
            "message": "<human-readable text>",
            "suggestion": "<optional next-step prose>"
        }
    }

Without this envelope, JSON-consuming agents got an empty stdout + free-form
stderr text and would parse-fail. Text mode is unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
    json_mode = output_format == "json"

    # Mutually-exclusive flag gate — Click validation error shape, exit non-zero.
    if from_trace is not None and no_trace_autoload:
        _emit_error(
            ctx,
            json_mode=json_mode,
            error_id="analyze-cache.flags-mutually-exclusive",
            message="--from-trace and --no-trace-autoload are mutually exclusive.",
            exit_code=2,
        )
        return

    # Lazy imports — analysis pulls in LiteLLM via token_estimation, no need
    # to pay the import cost on every CLI invocation.
    from pflow.cli.param_parsing import parse_workflow_params
    from pflow.core.cache_analysis import analyze, render_json, render_text
    from pflow.execution.workflow_resolver import resolve_workflow

    # Workflow resolution + param parsing — both raise on user error; the
    # helper renders a JSON envelope or text-mode diagnostic stream as
    # appropriate, then exits.
    resolved = _try_or_emit_diagnostic(
        ctx, json_mode, "analyze-cache.workflow-resolution-failed", lambda: resolve_workflow(workflow)
    )
    if resolved is None:
        return
    parsed_params = _try_or_emit_diagnostic(
        ctx, json_mode, "analyze-cache.invalid-parameters", lambda: parse_workflow_params(params)
    )
    if parsed_params is None:
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
        _emit_error(
            ctx,
            json_mode=json_mode,
            error_id="analyze-cache.trace-not-found",
            message=str(e) or "Trace file not found.",
            exit_code=1,
            suggestion=(
                "check the path. Auto-load reads from ~/.pflow/debug/; "
                "for explicit override pass an existing trace JSON."
            ),
        )
        return
    except ValueError as e:
        _emit_error(
            ctx,
            json_mode=json_mode,
            error_id="analyze-cache.invalid-input",
            message=str(e) or "Invalid analyzer input.",
            exit_code=1,
        )
        return

    # Successful analysis — render to chosen format.
    if json_mode:
        import json

        click.echo(json.dumps(render_json(analysis), indent=2))
    else:
        click.echo(render_text(analysis, all_rows=all_rows))


def _try_or_emit_diagnostic(
    ctx: click.Context,
    json_mode: bool,
    error_id: str,
    fn: Any,
) -> Any:
    """Run ``fn()``; on exception, emit a diagnostic stream + exit, return None.

    Consolidates the two parallel try/except blocks that were inline in
    ``analyze_cache``: ``resolve_workflow`` and ``parse_workflow_params`` both
    raise on user error; both convert via ``exception_to_diagnostics`` and emit
    via ``format_diagnostic``. JSON mode wraps the message in the structured
    error envelope; text mode emits each diagnostic line to stderr.

    Returns the function result on success, or ``None`` after emitting +
    exiting on failure (caller must guard with ``if result is None: return``).
    """
    from pflow.core.diagnostic import exception_to_diagnostics
    from pflow.core.diagnostic_render import format_diagnostic

    try:
        return fn()
    except Exception as e:
        diagnostics = list(exception_to_diagnostics(e))
        rendered = "\n".join(format_diagnostic(d) for d in diagnostics)
        if json_mode:
            _emit_error(
                ctx,
                json_mode=True,
                error_id=error_id,
                message=str(e) or e.__class__.__name__,
                exit_code=1,
                stderr_text=rendered,
            )
        else:
            click.echo(rendered, err=True)
            ctx.exit(1)
        return None


def _emit_error(
    ctx: click.Context,
    *,
    json_mode: bool,
    error_id: str,
    message: str,
    exit_code: int,
    suggestion: str | None = None,
    stderr_text: str | None = None,
) -> None:
    """Emit a CLI error and exit, honoring ``--format=json`` if active.

    Text mode: human-readable line(s) to stderr (legacy shape).

    JSON mode: structured envelope on stdout (so the agent's stdout JSON
    parser sees a parseable document) AND a human-readable line on stderr.
    Envelope schema is documented in the module docstring.

    Mutation contract: removing the JSON-mode branch makes
    ``test_analyze_cache_json_error_envelope`` fail with empty stdout.
    """
    if json_mode:
        import json

        from pflow.core.cache_analysis import JSON_FORMAT_VERSION

        envelope: dict[str, Any] = {
            "format_version": JSON_FORMAT_VERSION,
            "error": {"id": error_id, "message": message},
        }
        if suggestion:
            envelope["error"]["suggestion"] = suggestion
        click.echo(json.dumps(envelope, indent=2))
        # Mirror to stderr so humans tailing the same terminal still see context.
        click.echo(stderr_text or f"Error: {message}", err=True)
        if suggestion:
            click.echo(f"Suggestion: {suggestion}", err=True)
    else:
        click.echo(stderr_text or f"Error: {message}", err=True)
        if suggestion:
            click.echo(f"Suggestion: {suggestion}", err=True)
    ctx.exit(exit_code)


__all__ = ["analyze_cache"]
