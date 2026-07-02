"""Workflow output handling — detection, display, and formatting."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import click

from pflow.core.diagnostic import Diagnostic
from pflow.core.diagnostic_render import format_diagnostic
from pflow.execution.formatters.output_utils import OutputMode, select_output_mode
from pflow.runtime.template_resolver import TemplateResolver


def safe_output(value: Any) -> bool:
    """Safely output a value to stdout, handling broken pipes.

    Strings pass through verbatim. Structured values (dict, list, tuple,
    bool, int, float, None) are emitted as **strict JSON** so consumers
    can parse them with ``jq`` or ``json.loads`` — the GH #194 routing
    fix means agents now actually receive these on stdout, so the format
    must be parseable.

    - ``allow_nan=False``: rejects NaN/Infinity (jq and most strict
      parsers reject these literals).
    - ``default=str``: non-natively-serializable values (datetime, Path,
      set, dataclass, etc.) are coerced to their ``str()`` form INSIDE
      the JSON document, so the value lands as a JSON string and the
      pipeline keeps working.
    - Last-resort fallback: if even ``default=str`` cannot serialize the
      value (e.g. NaN inside an otherwise valid dict), we emit a stderr
      warning so agents can diagnose, then write ``repr(value)`` to
      stdout so something is visible.

    Returns True if output was successful, False otherwise.
    """
    try:
        if isinstance(value, bytes):
            click.echo("cli: Skipping binary output (use --output-key with text values)", err=True)
            return False
        if isinstance(value, str):
            click.echo(value)
            return True
        try:
            click.echo(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
        except (TypeError, ValueError) as exc:
            click.echo(
                f"cli: Output value of type {type(value).__name__} is not JSON-serializable "
                f"({exc}); emitting repr() so the value is still visible. "
                "Convert it in your workflow before output for parseable results.",
                err=True,
            )
            click.echo(repr(value))
        return True
    except BrokenPipeError:
        os._exit(0)
    except OSError as e:
        if hasattr(e, "errno") and e.errno == 32:  # EPIPE
            os._exit(0)
        raise


def _stream_is_tty(stream_name: str) -> bool:
    """Return whether ``stdout``/``stderr`` is a TTY.

    Prefers ``OutputController``'s captured state (set once at CLI startup) and
    falls back to ``sys.<stream>.isatty()`` when no Click context /
    OutputController is available — so the TTY decision stays consistent for any
    caller of ``_output_with_header`` (including non-CLI entry points that don't
    thread through ``_initialize_context``).
    """
    import sys

    try:
        ctx = click.get_current_context(silent=True)
    except RuntimeError:
        ctx = None
    if ctx is not None and ctx.obj and "output_controller" in ctx.obj:
        return bool(getattr(ctx.obj["output_controller"], f"{stream_name}_tty"))
    stream = getattr(sys, stream_name, None)
    return stream.isatty() if stream is not None else False


def _show_output_header() -> bool:
    """Whether to emit the ``Workflow output:`` label before the data.

    Show it whenever stdout is interactive OR stderr is captured. The label is
    suppressed in exactly one case — stdout redirected to a file/pipe WHILE
    stderr is a terminal (``pflow wf > out.json`` watched in a shell) — where a
    naked label on stderr with the data elsewhere reads as empty output.

    For the agent case (both streams captured, non-TTY) the label IS shown: it
    delimits where the result begins in a merged ``2>&1`` capture. This is the
    Option B refinement of the Task 149 suppression, which only ever needed to
    fire for the human-redirect case.
    """
    return _stream_is_tty("stdout") or not _stream_is_tty("stderr")


def _output_with_header(value: Any, print_flag: bool, description: str | None = None) -> None:
    """Output value with Unix-convention routing.

    - ``--print`` mode: data to stdout, no header.
    - stdout redirected while stderr is a terminal: data to stdout, no header —
      the naked stderr label would look like empty output (see
      ``_show_output_header``).
    - Otherwise (interactive, or both streams captured by an agent): header to
      stderr, data to stdout — the label delimits the result.
    """
    from pflow.execution.formatters.batch_errors import compact_batch_output_value

    value = compact_batch_output_value(value)
    if print_flag or not _show_output_header():
        safe_output(value)
        return

    header = f"\nWorkflow output ({description}):\n" if description else "\nWorkflow output:\n"
    click.echo(header, err=True)
    safe_output(value)


def _handle_text_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
    print_flag: bool = False,
    metrics_collector: Any | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    status: Any = None,
    warnings: list[Any] | None = None,
    trace_path: str | None = None,
) -> None:
    """Handle text formatted output with execution summary.

    Shows execution summary first, then workflow output. When ``print_flag``
    (``-p``) is True, suppresses stderr warnings/advice.

    When no output is produced (``-o`` miss, no declared outputs, no
    auto-detect match), stdout stays empty so pipe consumers receive a clean
    stream. The stderr summary emitted by ``_emit_summary_or_only_indicator``
    already signals success / degraded / failed status, so duplicating it on
    stdout would mean ``pflow ... -o nonexistent | jq .`` crashed on a literal
    English fallback (jq parses ``"Workflow executed successfully"`` as
    invalid JSON). That fallback was the pre-existing wart this branch
    removes as part of the GH #400 fix.

    Args:
        shared_storage: The shared store after execution
        output_key: User-specified output key (--output-key flag)
        workflow_ir: The workflow IR (to check declared outputs)
        verbose: Whether to show verbose output
        print_flag: Whether -p flag is set (suppress warnings)
        metrics_collector: Optional MetricsCollector for execution metrics
        workflow_metadata: Optional workflow metadata
        status: Optional tri-state workflow status
        warnings: Optional list of warning diagnostics
        trace_path: Optional trace file path, rendered in the meta block above
            the data (text-success path only)
    """
    # Display execution summary or --only mode indicator (dispatch in helper)
    _emit_summary_or_only_indicator(
        shared_storage=shared_storage,
        workflow_ir=workflow_ir,
        metrics_collector=metrics_collector,
        workflow_metadata=workflow_metadata,
        output_key=output_key,
        status=status,
        warnings=warnings,
        verbose=verbose,
        print_flag=print_flag,
        trace_path=trace_path,
    )

    # Output precedence lives in the shared classifier (output_utils), so the
    # CLI text path and the JSON/MCP path can never disagree on *which* branch
    # applies. This path renders the chosen branch its own way (streams one
    # value to stdout, emits stderr advisories); the JSON path renders the same
    # decision as a dict — only the precedence is shared.
    mode = select_output_mode(output_key, workflow_ir, shared_storage)

    # User-specified key takes priority. Supports dotted paths (e.g.
    # ``batch-llm.success_count``, ``items[0].title``) by delegating to
    # ``TemplateResolver``, which is the same primitive used by ``${...}``
    # templates inside workflow files and by ``pflow read-fields``.
    if mode is OutputMode.EXPLICIT_KEY:
        assert output_key is not None, "EXPLICIT_KEY ⇒ output_key truthy"  # type narrowing for mypy  # noqa: S101
        if TemplateResolver.variable_exists(output_key, shared_storage):
            value = TemplateResolver.resolve_value(output_key, shared_storage)
            _output_with_header(value, print_flag)
        elif not print_flag:
            hint = _diagnose_path_failure(shared_storage, output_key)
            # Blank line separates this advisory from the summary block above,
            # matching the other output-section advisories (airy layout).
            click.echo("", err=True)
            click.echo(
                f"cli: Warning - output key '{output_key}' not found. {hint}",
                err=True,
            )
        return

    # --only targets are explicit data-routing requests. Declared workflow
    # outputs describe full runs, so they must not shadow the targeted node.
    if mode is OutputMode.ONLY:
        _emit_only_output(shared_storage, print_flag)
        return

    # Check workflow-declared outputs for full runs. Declared outputs that
    # fail to resolve do NOT fall through to auto-detect — the workflow
    # author's declared contract is authoritative; an unresolved declared
    # output is a workflow-author error, not a cue to guess.
    if mode is OutputMode.DECLARED:
        _try_declared_outputs(shared_storage, workflow_ir, verbose and not print_flag, print_flag)
        return

    # Fall back to auto-detect from common keys (using unified function)
    _emit_auto_detected_output(
        shared_storage,
        print_flag,
        "cli: No outputs declared — showing auto-detected key '{key}'. Declare outputs for reliable results.",
    )


def _emit_only_output(shared_storage: dict[str, Any], print_flag: bool) -> bool:
    """Emit target-scoped output for an active ``--only`` run."""
    from pflow.execution.formatters.output_utils import find_only_output

    only_node = shared_storage.get("__execution__", {}).get("only_node")
    if not isinstance(only_node, str) or not only_node:
        return False

    key_found, value = find_only_output(shared_storage, only_node)
    if not key_found:
        if not print_flag:
            # Surface concrete ``-o`` candidates so the agent's suggested next
            # action is actionable — without enumeration the agent must either
            # introspect the trace or guess key names.
            available = _list_routable_keys_for_only_target(shared_storage)
            keys_hint = f" Available keys: {', '.join(available)}." if available else ""
            click.echo(
                f"cli: --only target '{only_node}' produced no output. "
                f"Pass -o <key> to select a specific output.{keys_hint}",
                err=True,
            )
        return False

    # Batch nodes write a {results, count, success_count, error_count, errors,
    # batch_metadata} aggregate to shared[node_id]. Dumping that whole dict
    # consumes tens of KB of agent context; replace with a 2-line summary that
    # surfaces success ratio + the explicit ``-o`` paths to drill in.
    # Detection is shape-only (``"batch_metadata" in value``) — the canonical
    # marker used by execution_state and instrumentation for batch detection.
    # The label uses ``key_found`` (the actual shared-store key holding the
    # aggregate, e.g. ``sub-wf``) rather than ``only_node`` (which may be a
    # dotted target like ``sub-wf.inner``) so the hint ``-o <key>.results``
    # points at a path that actually resolves.
    if isinstance(value, dict) and "batch_metadata" in value:
        _render_batch_compact_summary(key_found, value, print_flag)
        return True

    if not print_flag:
        # Blank line separates this advisory from the summary block above (airy).
        click.echo("", err=True)
        click.echo(
            f"cli: --only active — streaming auto-detected key '{key_found}' from target '{only_node}' to stdout.",
            err=True,
        )
    _output_with_header(value, print_flag)
    return True


def _list_routable_keys_for_only_target(shared_storage: dict[str, Any]) -> list[str]:
    """Return top-level shared-storage keys that ``-o <key>`` can select.

    Used by the ``--only`` no-output error path so the agent sees concrete
    ``-o`` candidates rather than abstract advice. Filters internal keys
    (leading ``_``) since those are never user-routable. The ``-o`` flag
    operates on the whole shared storage, not within a specific namespace —
    so the candidates are top-level node-id keys, not sub-keys of the target.
    Returns ``[]`` if no routable keys exist; caller decides how to render
    absence.
    """
    return sorted(k for k in shared_storage if isinstance(k, str) and not k.startswith("_"))


# Token grammar: dotted name (``[a-zA-Z_][\w-]*``) or bracket index (``[N]``).
# Bare digits are intentionally NOT a name segment — that makes inputs like
# ``batch.results.0.r`` (dot-notation indexing, a documented misuse from #400)
# fail the reconstruction check and fall into the syntax-hint branch, which
# explicitly nudges the agent toward ``<name>[N]`` syntax. Pinned by
# ``test_output_key_miss_with_dot_notation_for_list_index_nudges_to_brackets``.
_PATH_SEGMENT_PATTERN = re.compile(r"[a-zA-Z_][\w-]*|\[\d+\]")


def _diagnose_path_failure(shared_storage: dict[str, Any], key: str) -> str:
    """Walk a failing ``-o`` path; return a hint describing the deepest valid prefix.

    Called when ``TemplateResolver.variable_exists(key, shared_storage)`` has
    returned False. Walks segment-by-segment from the root, keeping track of
    the deepest prefix that resolves, then describes what's there so the
    agent can pick a valid next path.

    The token regex matches either a dotted name segment (``[a-zA-Z_][\\w-]*``)
    or a bracketed index (``[\\d+]``) — the same token classes
    ``TemplateResolver.resolve_value`` accepts. Any other character in ``key``
    is silently ignored by ``re.findall``, which would produce a misleading
    hint about a path the agent didn't type. Defend against that by
    reconstructing the path from matched tokens and bailing out with a
    generic syntax hint when the reconstruction doesn't equal the input.
    """
    segments = _PATH_SEGMENT_PATTERN.findall(key)
    if not segments:
        return _describe_at("", shared_storage)

    reconstructed = ""
    for seg in segments:
        if seg.startswith("["):
            reconstructed += seg
        elif reconstructed:
            reconstructed += "." + seg
        else:
            reconstructed = seg
    if reconstructed != key:
        return (
            f"'{key}' contains characters that aren't valid in a path. "
            f"Use `<name>`, `<name>.<sub>`, or `<name>[N]` syntax."
        )

    valid_prefix = ""
    parent: Any = shared_storage
    for seg in segments:
        if seg.startswith("["):
            trial = valid_prefix + seg
        elif valid_prefix:
            trial = valid_prefix + "." + seg
        else:
            trial = seg
        if TemplateResolver.variable_exists(trial, shared_storage):
            valid_prefix = trial
            parent = TemplateResolver.resolve_value(trial, shared_storage)
        else:
            return _describe_at(valid_prefix, parent)
    return _describe_at(valid_prefix, parent)


def _describe_at(prefix: str, parent: Any) -> str:
    """Describe what's at ``parent`` (the deepest-valid path); used for ``-o`` miss hints."""
    if isinstance(parent, dict):
        keys = sorted(k for k in parent if isinstance(k, str) and not k.startswith("_"))
        if not keys:
            return f"'{prefix}' has no subkeys." if prefix else "No top-level keys available."
        if prefix:
            return f"Available subkeys of '{prefix}': {', '.join(keys)}."
        return f"Available top-level keys: {', '.join(keys)}."
    if isinstance(parent, list):
        n = len(parent)
        if n == 0:
            return f"'{prefix}' is an empty list."
        if n == 1:
            return f"'{prefix}' is a list of length 1. Valid index: 0."
        return f"'{prefix}' is a list of length {n}. Valid indices: 0 to {n - 1}."
    value_repr = _short_repr(parent)
    return (
        f"'{prefix}' is a {_friendly_type(parent)} (value: {value_repr}), "
        f"cannot descend. Drop the trailing segments to read it."
    )


def _friendly_type(value: Any) -> str:
    """Map Python types to agent-friendly names for error messages."""
    if value is None:
        return "null value"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def _short_repr(value: Any, max_len: int = 60) -> str:
    """Render a short, agent-readable value preview for scalar dead-end messages."""
    rendered = repr(value)
    if len(rendered) > max_len:
        return rendered[: max_len - 1] + "…"
    return rendered


def _render_batch_compact_summary(node_id: str, value: dict[str, Any], print_flag: bool) -> None:
    """Emit a compact summary for ``--only <batch-node>`` instead of the full batch dict.

    Replaces dumping the full ``{results, count, success_count, error_count,
    errors, batch_metadata}`` aggregate, which can run tens of KB on a real
    batch. The summary surfaces success ratio + the explicit ``-o`` paths to
    drill into the parts the agent actually needs.

    The errors hint is appended only when ``error_count > 0`` because batch
    nodes write ``errors: None`` (not ``[]``) when no items failed (see
    ``src/pflow/runtime/engine/batch_executor.py``).

    Under ``-p`` (print mode) the hint line is suppressed — the contract for
    ``-p`` is clean stdout for pipes; the data line stays, the discoverability
    hint would be noise in a pipeline.
    """
    count = value.get("count", 0)
    success_count = value.get("success_count", 0)
    error_count = value.get("error_count", 0)

    if count == 0:
        safe_output(f"batch {node_id}: ran with no items")
        return

    # ``batch_metadata`` is guaranteed dict-or-absent per ``batch_executor.py``
    # contract; the outer ``or {}`` covers absent. ``timing`` is dict-or-None
    # per ``batch_executor.py:823`` (None when ``item_timings`` is empty); the
    # second ``or {}`` covers that real case.
    timing = (value.get("batch_metadata") or {}).get("timing") or {}
    total_ms = timing.get("total_items_ms")
    duration = f" in {total_ms / 1000:.1f}s" if isinstance(total_ms, (int, float)) else ""

    safe_output(f"batch {node_id}: {success_count}/{count} items succeeded{duration}")
    if print_flag:
        return
    hint = f"use `-o {node_id}.results` for full payload"
    if error_count > 0:
        hint += f", `-o {node_id}.errors` for failures"
    # Hint is advisory (drill-deeper guidance), not data — stderr matches the
    # module-wide convention (data → stdout, advice → stderr) used by the
    # ``-o`` miss hint and the ``--only`` no-output advisory.
    click.echo(f"  {hint}", err=True)


def _emit_auto_detected_output(
    shared_storage: dict[str, Any],
    print_flag: bool,
    message_template: str | None,
) -> bool:
    """Auto-detect output from shared storage and emit it.

    ``message_template`` (optional) must contain ``{key}`` for the detected
    key name. Returns True if output was emitted.
    """
    from pflow.execution.formatters.output_utils import find_auto_output

    key_found, value = find_auto_output(shared_storage)
    if not key_found:
        return False
    if message_template and not print_flag:
        # Blank line separates this output advisory from the summary block above
        # (airy layout); the header below carries its own leading blank.
        click.echo("", err=True)
        click.echo(message_template.format(key=key_found), err=True)
    _output_with_header(value, print_flag)
    return True


def _emit_declared_output(
    shared_storage: dict[str, Any],
    declared_outputs: dict[str, Any],
    print_flag: bool,
) -> bool:
    """Emit the first available declared output and return True.

    This helper reduces complexity in `_try_declared_outputs` by encapsulating
    the loop and verbose description printing.
    """
    for output_name, output_config in declared_outputs.items():
        if output_name in shared_storage:
            value = shared_storage[output_name]

            # Extract description from output config
            description = None
            if isinstance(output_config, dict):
                description = output_config.get("description")

            _output_with_header(value, print_flag, description)
            return True
    return False


def _select_stdout_target(declared_outputs: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Choose which declared outputs to stream to stdout in text mode.

    Pure selector — returns ``(target, dropped)`` and never writes to stderr.
    The caller decides whether to emit the multi-output warning (see
    ``_warn_multi_output_ambiguity``).

    Precedence:
    - Any output marked ``stdout: true`` → return only that output, no drops.
      Validator guarantees at most one marker, so this always yields a
      single-entry dict.
    - Exactly one declared output → return it (implicit, unambiguous case).
    - Multiple declared outputs with no marker → return the first, with the
      remaining names as ``dropped``.

    Schema (``additionalProperties: false`` on outputs) guarantees dict
    values by the time we run, so no defensive type checks.
    """
    marked = {name: config for name, config in declared_outputs.items() if config.get("stdout") is True}
    if marked:
        return marked, []
    if len(declared_outputs) <= 1:
        return declared_outputs, []

    names = list(declared_outputs.keys())
    first_name = names[0]
    return {first_name: declared_outputs[first_name]}, names[1:]


def _warn_multi_output_ambiguity(chosen: str, dropped: list[str]) -> None:
    """Emit the stderr warning when multiple declared outputs have no ``stdout: true``.

    Sibling of ``_warn_missing_declared_outputs``. Named so the selector stays
    pure; caller gates on ``print_flag``.
    """
    total = 1 + len(dropped)
    names = ", ".join([chosen, *dropped])
    # Blank line separates this advisory from the summary block above (airy).
    click.echo("", err=True)
    click.echo(
        f"cli: Workflow declares {total} outputs ({names}). "
        f"Streaming '{chosen}' to stdout. Mark one output with `- stdout: true`, "
        "pass `-o <name>`, or use `--output-format json` to emit all.",
        err=True,
    )


def _try_declared_outputs(
    shared_storage: dict[str, Any],
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
    print_flag: bool,
) -> bool:
    """Try to output from workflow-declared outputs.

    Args:
        shared_storage: The shared storage dictionary
        workflow_ir: The workflow IR specification
        verbose: Whether to show verbose output
        print_flag: Whether in non-interactive/print mode
    Returns:
        True if a declared output was found and printed, False otherwise
    """
    if not (workflow_ir and "outputs" in workflow_ir and workflow_ir["outputs"]):
        return False

    declared_outputs = workflow_ir["outputs"]
    target, dropped = _select_stdout_target(declared_outputs)
    if dropped and not print_flag:
        _warn_multi_output_ambiguity(next(iter(target)), dropped)

    # First attempt: use already-populated outputs (preferred path via compiler wrapper)
    if _emit_declared_output(shared_storage, target, print_flag):
        return True

    # Populate on-demand if not present
    _populate_declared_outputs_best_effort(shared_storage, workflow_ir)

    # Second attempt after population
    if _emit_declared_output(shared_storage, target, print_flag):
        return True

    _warn_missing_declared_outputs(target, verbose)
    return False


def _populate_declared_outputs_best_effort(shared_storage: dict[str, Any], workflow_ir: dict[str, Any]) -> None:
    """Best-effort population of declared outputs from source expressions.

    Redundant with ``engine._populate_outputs`` for normal CLI runs (engine
    populates first), but kept as a safety net for callers that bypass the
    engine path. The second call is idempotent — resolvable outputs already
    in ``shared_storage`` are overwritten with the same values.
    """
    from pflow.core.user_errors import OutputResolutionError
    from pflow.runtime.output_resolver import populate_declared_outputs

    try:
        populate_declared_outputs(shared_storage, workflow_ir)
    except OutputResolutionError as e:
        only_node = shared_storage.get("__execution__", {}).get("only_node")
        if not only_node:
            from pflow.core.diagnostic import exception_to_diagnostics

            for d in exception_to_diagnostics(e):
                click.echo(format_diagnostic(d), err=True)
    except Exception:  # noqa: S110
        pass  # Best-effort: non-diagnostic errors silently ignored


def _warn_missing_declared_outputs(declared_outputs: dict[str, Any], verbose: bool) -> None:
    """Warn when declared outputs are present but none were resolved."""
    if not verbose:
        return
    expected = ", ".join(declared_outputs.keys())
    click.echo(
        f"cli: Warning - workflow declares outputs [{expected}] but none could be resolved",
        err=True,
    )


def _truncate_error_message(message: str, max_length: int = 200) -> str:
    """Truncate error message to max length with ellipsis."""
    from pflow.execution.formatters.batch_errors import _truncate_error_message as shared_truncate_error_message

    return shared_truncate_error_message(message, max_length)


def _as_block(lines: list[str]) -> list[str]:
    """Normalize a formatter's output into a clean block.

    Drops leading/trailing blank lines and a newline baked into the first line,
    so ``_echo_summary_blocks`` is the single owner of inter-block spacing.
    ``format_stderr_warnings`` leads with a ``""`` element;
    ``format_batch_errors_section`` bakes a ``\\n`` into its first line — this
    flattens both to bare content.
    """
    block = list(lines)
    while block and block[0] == "":
        block.pop(0)
    while block and block[-1] == "":
        block.pop()
    if block:
        block[0] = block[0].lstrip("\n")
    return block


def _echo_summary_blocks(blocks: list[list[str]]) -> None:
    """Echo summary blocks to stderr with one blank line before each (airy).

    The leading blank before the first block separates the summary from the
    progress stream above it (replacing the old per-action blank line). Empty
    blocks are skipped so absent sections leave no dangling separators.
    """
    for block in blocks:
        if not block:
            continue
        click.echo("", err=True)
        for line in block:
            click.echo(line, err=True)


def _format_cost_summary_lines(total_cost: float | None, formatted_result: dict[str, Any]) -> list[str]:
    """Build the LLM cost / token usage summary lines.

    Returns ``💰 Cost: ...`` (priced) or ``⚠️  Cost unavailable — ...``
    (unpriced) as the first line, followed by a ``   Total LLM calls: N``
    sibling line (3-space indent) whenever the run actually made any LLM
    calls. The sibling line is intentionally suppressed when no LLM calls
    happened so workflows that never touch an LLM don't see ``Total LLM
    calls: 0`` (mirrors the "honest unmeasurable" precedent in
    ``format_dry_run_nudge``). Returns ``[]`` when there is no cost to show.

    Args:
        total_cost: Total cost in USD
        formatted_result: Full formatted result containing metrics
    """
    metrics = formatted_result.get("metrics", {})
    total_metrics = metrics.get("total", {})
    total_llm_calls = int(total_metrics.get("total_calls", 0) or 0)

    # Warn about models with unavailable pricing
    if not total_metrics.get("pricing_available", True):
        from pflow.core.metrics import format_unavailable_models_phrase, unavailable_models_to_counts

        unavailable_counts = unavailable_models_to_counts(total_metrics.get("unavailable_models", []))
        unavailable_unnamed_count = total_metrics.get("unavailable_models_unnamed_count", 0)
        models_phrase = format_unavailable_models_phrase(unavailable_counts, unavailable_unnamed_count)
        partial = total_metrics.get("partial_cost_usd")
        if partial is not None:
            lines = [f"💰 Cost: ${partial:.4f}+ (partial — pricing unavailable for: {models_phrase})"]
        else:
            lines = [f"⚠️  Cost unavailable — pricing data missing for: {models_phrase}"]
        if total_llm_calls > 0:
            lines.append(f"   Total LLM calls: {total_llm_calls}")
        return lines

    if total_cost is None or total_cost <= 0:
        return []

    # Get token count for context. The key is ``tokens_total`` (set by
    # MetricsCollector._build_execution_metrics) — cache-inclusive input + output.
    workflow_metrics = metrics.get("workflow", {})
    tokens_total = workflow_metrics.get("tokens_total", 0)

    detail_parts: list[str] = []
    if total_llm_calls > 0:
        detail_parts.append(f"{total_llm_calls} call{'s' if total_llm_calls != 1 else ''}")
    if tokens_total > 0:
        detail_parts.append(f"{tokens_total:,} tokens")

    if detail_parts:
        return [f"💰 Cost: ${total_cost:.4f} ({', '.join(detail_parts)})"]
    return [f"💰 Cost: ${total_cost:.4f}"]


def _format_workflow_completion_status(
    duration_s: float,
    status: str,
    has_stderr_warnings: bool,
    cache_hits: int = 0,
    nodes_executed: int = 0,
    warning_count: int = 0,
) -> str:
    """Build the workflow completion status line with the appropriate indicator.

    Args:
        duration_s: Execution duration in seconds
        status: Workflow status ("success", "degraded", "failed", "denied")
        has_stderr_warnings: Whether any shell node produced stderr with exit_code=0
        cache_hits: Number of nodes served from cache (0 = no cache stats shown)
        nodes_executed: Total completed nodes (used to compute fresh executions)
        warning_count: Number of diagnostics warnings surfaced in the summary
    """
    cache_suffix = ""
    if cache_hits > 0:
        executed_fresh = nodes_executed - cache_hits
        cache_suffix = f" ({cache_hits} cached, {executed_fresh} executed)"

    if status == "degraded":
        return f"⚠️ Workflow completed with warnings in {duration_s:.3f}s{cache_suffix}"
    if status == "denied":
        # Task 125: explicit arm — the success fallthrough below must never
        # render a human's "no" as ✓. (The denied CLI path has its own display;
        # this guards any other caller passing the status through.)
        return f"✗ Workflow denied at gate after {duration_s:.3f}s{cache_suffix}"
    if status == "failed":
        if warning_count:
            return f"❌ Workflow failed ({warning_count} warnings) after {duration_s:.3f}s{cache_suffix}"
        return f"❌ Workflow failed after {duration_s:.3f}s{cache_suffix}"
    if warning_count:
        return f"⚠️ Workflow completed with {warning_count} warnings in {duration_s:.3f}s{cache_suffix}"
    if has_stderr_warnings:
        return f"⚠️ Workflow completed in {duration_s:.3f}s{cache_suffix}"
    return f"✓ Workflow completed in {duration_s:.3f}s{cache_suffix}"


def _emit_summary_or_only_indicator(
    *,
    shared_storage: dict[str, Any],
    workflow_ir: dict[str, Any] | None,
    metrics_collector: Any | None,
    workflow_metadata: dict[str, Any] | None,
    output_key: str | None,
    status: Any,
    warnings: list[Any] | None,
    verbose: bool,
    print_flag: bool,
    trace_path: str | None = None,
) -> None:
    """Dispatch between full summary, --only-only emission, or nothing.

    The full summary (completion tag + batch errors + cost + trace path +
    warnings + --only line) is suppressed in ``-p`` mode because the user
    explicitly asked for minimal stderr. The ``--only`` mode confirmation is a
    mode signal (not a suppressible detail) and is emitted even in ``-p`` mode
    when ``--only`` is active. Verbosity flags hide details; mode flags survive
    verbosity. Matches the convention of ``make -k``, ``pytest --maxfail``,
    ``rsync --dry-run``, ``apt-get --simulate``, ``kubectl --dry-run``, etc.

    ``trace_path``, when given, rides into the summary so the "Workflow trace
    saved" line renders in the meta block above the data (text mode). JSON and
    failure paths leave it ``None`` and echo the trace line from ``run.py``.

    No-op when there's no metrics collector OR when neither path applies.
    """
    if not metrics_collector:
        return

    only_node = shared_storage.get("__execution__", {}).get("only_node") if shared_storage else None
    if print_flag and not only_node:
        return  # -p mode without --only: nothing to emit

    from pflow.execution.formatters.success_formatter import format_execution_success

    formatted = format_execution_success(
        shared_storage=shared_storage,
        workflow_ir=workflow_ir or {},
        metrics_collector=metrics_collector,
        workflow_metadata=workflow_metadata,
        output_key=output_key,
        trace_path=trace_path,
        status=status,
        warnings=warnings,
    )

    if print_flag:
        # -p + --only: emit just the mode confirmation, nothing else
        _emit_only_indicator(formatted)
        return

    # Default mode: full summary (which already includes the --only line
    # internally via the shared format_only_indicator helper)
    warning_diags = [w for w in (warnings or []) if isinstance(w, Diagnostic)]
    _display_execution_summary(formatted, verbose, warning_diagnostics=warning_diags or None)


def _only_indicator_line(formatted_result: dict[str, Any]) -> str | None:
    """Build the ``--only`` mode confirmation line, or ``None`` if not active.

    Shared by ``_emit_only_indicator`` (the ``-p`` path) and the default
    summary block so the indicator text has one source — see
    ``format_only_indicator`` in ``success_formatter.py``.
    """
    from pflow.execution.formatters.success_formatter import format_only_indicator

    execution = formatted_result.get("execution", {})
    only_node = execution.get("only_node")
    if not only_node:
        return None
    return format_only_indicator(only_node, execution.get("nodes_skipped", 0))


def _emit_only_indicator(formatted_result: dict[str, Any]) -> None:
    """Emit the ``--only`` mode confirmation line to stderr (``-p`` path).

    Why this exists: ``--only`` is a mode signal, not a summary detail.
    Without this emission, ``pflow -p foo --only target`` produces zero
    bytes on stderr, leaving agents unable to disambiguate constrained
    runs from full runs. Verbosity flags hide details; mode flags
    survive verbosity (matches ``make -k``, ``pytest --maxfail``,
    ``rsync --dry-run``, ``apt-get --simulate``, ``kubectl --dry-run``,
    etc.).
    """
    line = _only_indicator_line(formatted_result)
    if line:
        click.echo(line, err=True)


def _display_execution_summary(
    formatted_result: dict[str, Any],
    verbose: bool,
    warning_diagnostics: list[Diagnostic] | None = None,
) -> None:
    """Display the execution summary as airy blocks (one blank line between).

    Order: completion · --only · batch errors · shell-stderr · cost · warnings ·
    advisories · trace path. The trace path is read from
    ``formatted_result["trace_path"]`` (populated only on the text-success path)
    so the "Workflow trace saved" line lands in the meta block above the data,
    de-emoji'd. Sections are collected first and emitted with a single blank
    line before each present one — absent sections leave no dangling separators.
    """
    from pflow.execution.formatters.batch_errors import format_batch_errors_section
    from pflow.execution.formatters.success_formatter import (
        format_stderr_warnings,
        partition_surfaced_diagnostics,
    )

    # INFO advisories (e.g. an empty batch) are not warnings: only WARNING/ERROR
    # diagnostics drive the "completed with N warnings" header. Advisories get
    # their own section so a fully correct run still reads "✓ Workflow completed".
    warnings_list, advisories_list = partition_surfaced_diagnostics(warning_diagnostics)

    duration_ms = formatted_result.get("duration_ms")
    total_cost = formatted_result.get("total_cost_usd")
    execution = formatted_result.get("execution", {})
    steps = execution.get("steps", []) if execution else []

    blocks: list[list[str]] = []

    if duration_ms is not None:
        warning_count = len(warnings_list)
        blocks.append([
            _format_workflow_completion_status(
                duration_ms / 1000.0,
                formatted_result.get("status", "success"),
                any(step.get("has_stderr") for step in steps),
                cache_hits=execution.get("cache_hits", 0),
                nodes_executed=execution.get("nodes_executed", 0),
                warning_count=warning_count,
            )
        ])

    # --only mode confirmation: always emit when --only is active, even when no
    # downstream nodes were skipped (e.g. --only targeted the last node).
    only_line = _only_indicator_line(formatted_result)
    if only_line:
        blocks.append([only_line])

    if steps:
        blocks.append(_as_block(format_batch_errors_section(steps)))
        blocks.append(_as_block(format_stderr_warnings(steps)))

    blocks.append(_format_cost_summary_lines(total_cost, formatted_result))

    if warnings_list:
        blocks.append(["⚠️ Warnings:", *(format_diagnostic(w) for w in warnings_list)])
    if advisories_list:
        blocks.append([
            "\N{INFORMATION SOURCE}\N{VARIATION SELECTOR-16} Advisories:",
            *(format_diagnostic(a) for a in advisories_list),
        ])

    trace_path = formatted_result.get("trace_path")
    if trace_path:
        blocks.append([f"Workflow trace saved: {trace_path}"])

    _echo_summary_blocks(blocks)


def _handle_json_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
    print_flag: bool = False,
    metrics_collector: Any | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    workflow_trace: Any | None = None,
    status: Any = None,
    warnings: list[Any] | None = None,
) -> None:
    """Handle JSON formatted output.

    Emits all declared outputs (or the specified key) as JSON, optionally with
    metrics. Execution summary still flows to stderr — ``--output-format``
    controls stdout format only; ``-p`` controls stderr verbosity.
    """
    # Use shared formatter for consistency with MCP
    from pflow.execution.formatters.success_formatter import format_execution_success

    result = format_execution_success(
        shared_storage=shared_storage,
        workflow_ir=workflow_ir or {},
        metrics_collector=metrics_collector,
        workflow_metadata=workflow_metadata,
        output_key=output_key,
        trace_path=None,  # CLI doesn't include trace_path in output
        status=status,
        warnings=warnings,
    )

    # Save JSON output to trace if available
    if workflow_trace and hasattr(workflow_trace, "set_json_output"):
        workflow_trace.set_json_output(result)

    # Emit execution summary to stderr (same as text mode)
    _emit_summary_or_only_indicator(
        shared_storage=shared_storage,
        workflow_ir=workflow_ir,
        metrics_collector=metrics_collector,
        workflow_metadata=workflow_metadata,
        output_key=output_key,
        status=status,
        warnings=warnings,
        verbose=verbose,
        print_flag=print_flag,
    )

    _serialize_json_result(result, verbose)


def _create_workflow_metadata(name: str | None, action: str) -> dict[str, Any]:
    """Create workflow metadata with name and action.

    Args:
        name: Workflow name (optional)
        action: Workflow action ("created", "reused", "unsaved")

    Returns:
        Workflow metadata dictionary

    Raises:
        ValueError: If action is not one of the allowed values
    """
    allowed_actions = {"created", "reused", "unsaved"}
    if action not in allowed_actions:
        raise ValueError(f"Invalid workflow action: {action}. Must be one of {allowed_actions}")

    metadata = {"action": action}
    if name:
        metadata["name"] = name
    return metadata


def _serialize_json_result(result: dict[str, Any], verbose: bool) -> bool:
    """Serialize result dictionary to JSON and output it.

    Args:
        result: Dictionary to serialize
        verbose: Whether to show verbose output

    Returns:
        True if output was successful, False otherwise
    """
    try:
        # Handle special types
        def json_serializer(obj: Any) -> Any:
            """Custom JSON serializer for non-standard types."""
            if isinstance(obj, bytes):
                return {"_type": "binary", "size": len(obj), "note": "Binary data not included in JSON output"}
            return str(obj)

        output = json.dumps(result, indent=2, ensure_ascii=False, default=json_serializer)
        return safe_output(output)
    except (TypeError, ValueError) as e:
        if verbose:
            click.echo(f"cli: Warning - JSON encoding error: {e}", err=True)
        # Fallback to error message
        error_output = json.dumps({"error": "JSON encoding failed", "message": str(e)})
        return safe_output(error_output)


def _handle_workflow_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None = None,
    verbose: bool = False,
    output_format: str = "text",
    metrics_collector: Any | None = None,
    print_flag: bool = False,
    workflow_metadata: dict[str, Any] | None = None,
    workflow_trace: Any | None = None,
    status: Any = None,
    warnings: list[Any] | None = None,
    trace_path: str | None = None,
) -> None:
    """Handle output from workflow execution.

    Dispatches to ``_handle_json_output`` or ``_handle_text_output`` based on
    ``output_format``. Stream contract: data → stdout, summary/advice → stderr.

    Args:
        shared_storage: The shared store after execution
        output_key: User-specified output key (--output-key flag)
        workflow_ir: The workflow IR (to check declared outputs)
        verbose: Whether to show verbose output
        output_format: Output format - "text" or "json"
        metrics_collector: Optional MetricsCollector for including metrics in JSON output
        print_flag: Whether -p flag is set (suppress warnings)
        workflow_metadata: Optional workflow metadata for JSON output
        workflow_trace: Optional workflow trace collector for saving JSON output
        status: Optional tri-state workflow status
        warnings: Optional list of warning diagnostics
        trace_path: Optional trace file path. In text mode it renders in the
            meta block above the data; JSON leaves it ``None`` (the trace line
            is echoed from ``run.py`` after the JSON payload).
    """
    if output_format == "json":
        _handle_json_output(
            shared_storage,
            output_key,
            workflow_ir,
            verbose,
            print_flag=print_flag,
            metrics_collector=metrics_collector,
            workflow_metadata=workflow_metadata,
            workflow_trace=workflow_trace,
            status=status,
            warnings=warnings,
        )
        return

    _handle_text_output(
        shared_storage,
        output_key,
        workflow_ir,
        verbose,
        print_flag,
        metrics_collector,
        workflow_metadata,
        status=status,
        warnings=warnings,
        trace_path=trace_path,
    )
