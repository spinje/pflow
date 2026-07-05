"""Success output formatter for workflow execution.

This module provides a shared formatter for successful workflow execution results,
ensuring CLI and MCP return identical output structures.
"""

import json
from typing import Any

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.diagnostic_render import format_diagnostic
from pflow.core.workflow.status import WorkflowStatus
from pflow.execution.formatters.batch_errors import (
    _truncate_error_message as _shared_truncate_error_message,
)
from pflow.execution.formatters.batch_errors import (
    compact_batch_error_detail,
    compact_batch_output_value,
)
from pflow.execution.formatters.batch_errors import (
    format_batch_errors_section as _shared_format_batch_errors_section,
)
from pflow.runtime.template_resolver import TemplateResolver


def format_execution_success(
    shared_storage: dict[str, Any],
    workflow_ir: dict[str, Any],
    metrics_collector: Any,
    workflow_metadata: dict[str, Any] | None = None,
    output_key: str | None = None,
    trace_path: str | None = None,
    status: WorkflowStatus | None = None,
    warnings: list[Any] | None = None,
) -> dict[str, Any]:
    """Format successful workflow execution output.

    Args:
        shared_storage: Shared storage dictionary from execution
        workflow_ir: Workflow IR specification
        metrics_collector: MetricsCollector instance with execution metrics
        workflow_metadata: Optional workflow metadata (action, name)
        output_key: Optional specific output key to return
        trace_path: Optional path to execution trace file
        status: Optional tri-state workflow status (SUCCESS/DEGRADED/FAILED)
        warnings: Optional list of warning dictionaries

    Returns:
        Dictionary with formatted execution results matching CLI structure
    """
    # Collect outputs from shared storage
    outputs = _collect_outputs(shared_storage, workflow_ir, output_key)

    # Build base result structure
    result = {
        "success": True,
        "result": outputs,
    }

    # Add tri-state status (if provided, otherwise infer from success)
    if status:
        result["status"] = status.value
    else:
        result["status"] = "success"  # Backward compatibility default

    # Add workflow metadata (default to unsaved if not provided)
    result["workflow"] = workflow_metadata if workflow_metadata else {"action": "unsaved"}

    # Split by severity so INFO advisories (e.g. an empty batch) don't appear
    # under `warnings` — an agent parsing JSON would otherwise read a clean run
    # as warned. `diagnostics` keeps the full severity-tagged list. Mirrors the
    # text renderer's Warnings/Advisories split (CLI/JSON parity).
    all_diagnostics = warnings or []
    warnings_list, advisories_list = partition_surfaced_diagnostics(all_diagnostics)
    result["warnings"] = [d.to_display_dict() for d in warnings_list]
    result["advisories"] = [d.to_display_dict() for d in advisories_list]
    result["diagnostics"] = [d.to_dict() for d in all_diagnostics]

    # Add metrics from collector
    if metrics_collector:
        trace = shared_storage.get("__trace_collector__") if shared_storage else None
        llm_calls = trace.collect_llm_calls() if trace else []
        metrics_summary = metrics_collector.get_summary(llm_calls)

        # Add top-level metrics (CLI structure). When pricing is unavailable
        # for any LLM call (LiteLLM doesn't recognize the model — Ollama,
        # custom endpoints, brand-new releases), surface the tri-state
        # discriminators alongside the bare null cost so JSON consumers can
        # distinguish "no LLM calls" from "LLM calls happened but pricing
        # data missing."
        result["duration_ms"] = metrics_summary.get("duration_ms")
        result["total_cost_usd"] = metrics_summary.get("total_cost_usd")
        _mirror_pricing_tri_state(result, metrics_summary)

        # Extract workflow node count
        workflow_metrics = metrics_summary.get("metrics", {}).get("workflow", {})
        result["nodes_executed"] = int(workflow_metrics.get("nodes_executed", 0))

        # Add detailed metrics structure
        result["metrics"] = metrics_summary.get("metrics", {})

        # Add execution state with per-node details
        if workflow_ir and shared_storage:
            from pflow.execution.execution_state import build_execution_steps

            steps = build_execution_steps(workflow_ir, shared_storage, metrics_summary)
            if steps:
                steps = _compact_batch_error_details(steps)
                # Count nodes by status
                completed_count = sum(1 for s in steps if s["status"] == "completed")
                nodes_total = len(steps)

                execution_dict: dict[str, Any] = {
                    "duration_ms": metrics_summary.get("duration_ms"),
                    "nodes_executed": completed_count,
                    "nodes_total": nodes_total,
                    "steps": steps,
                }

                # --only metadata (from __execution__ state)
                exec_state = shared_storage.get("__execution__", {})
                only_node_val = exec_state.get("only_node")
                if only_node_val:
                    execution_dict["only_node"] = only_node_val
                    not_executed_count = sum(1 for s in steps if s["status"] == "not_executed")
                    execution_dict["nodes_skipped"] = not_executed_count

                # Resume metadata (Task 164 — engine stamps in _prepare_resume).
                # A machine-readable resume marker: without it a resumed run's JSON
                # is byte-identical to a full run's, the exact ambiguity the --only
                # fields exist to prevent. Absent on non-resumed runs.
                resumed_from_val = exec_state.get("resumed_from")
                if resumed_from_val:
                    execution_dict["resumed_from"] = resumed_from_val
                    execution_dict["nodes_restored"] = len(exec_state.get("restored_nodes", []))
                    execution_dict["resume_entry_node"] = exec_state.get("resume_entry_node")

                # Aggregate cache stats
                cache_hit_count = sum(1 for s in steps if s.get("cached"))
                if cache_hit_count > 0:
                    execution_dict["cache_hits"] = cache_hit_count

                result["execution"] = execution_dict

    # Add trace_path if provided (MCP bonus feature)
    if trace_path:
        result["trace_path"] = trace_path

    return result


def _compact_batch_error_details(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact_steps: list[dict[str, Any]] = []
    for step in steps:
        step_copy = dict(step)
        details = step_copy.get("batch_error_details")
        if isinstance(details, list):
            step_copy["batch_error_details"] = [
                compact_batch_error_detail(detail) if isinstance(detail, dict) else detail for detail in details
            ]
        compact_steps.append(step_copy)
    return compact_steps


def _mirror_pricing_tri_state(result: dict[str, Any], metrics_summary: dict[str, Any]) -> None:
    """Mirror the pricing tri-state (partial_cost_usd / pricing_available /
    unavailable_models) from metrics_summary to top-level result keys.

    When pricing is unavailable for any LLM call, the bare top-level
    ``total_cost_usd: null`` is ambiguous — agents can't tell "no LLM calls"
    from "calls happened but pricing data missing." Mirroring the
    discriminators alongside makes the cause obvious without drilling into
    ``result["metrics"]["total"]``.
    """
    if metrics_summary.get("pricing_available") is not False:
        return
    result["pricing_available"] = False
    partial_cost = metrics_summary.get("partial_cost_usd")
    if partial_cost is not None:
        result["partial_cost_usd"] = partial_cost
    unavailable = metrics_summary.get("unavailable_models")
    if unavailable:
        result["unavailable_models"] = list(unavailable)
    unnamed_count = metrics_summary.get("unavailable_models_unnamed_count", 0)
    if unnamed_count:
        result["unavailable_models_unnamed_count"] = unnamed_count


def _collect_outputs(
    shared_storage: dict[str, Any],
    workflow_ir: dict[str, Any],
    output_key: str | None = None,
) -> dict[str, Any]:
    """Collect outputs from shared storage for JSON formatting.

    Args:
        shared_storage: Shared storage dictionary
        workflow_ir: Workflow IR specification
        output_key: Optional specific key to output

    Returns:
        Dictionary of outputs to include in result
    """

    from pflow.core.json_utils import parse_json_or_original
    from pflow.execution.formatters.output_utils import (
        OutputMode,
        find_auto_output,
        find_only_output,
        select_output_mode,
    )

    result = {}

    # Output precedence lives in the shared classifier so this JSON/MCP path
    # and the CLI text path can never disagree on *which* branch applies. They
    # render the decision differently — text streams one value, this path
    # collects a dict (all declared outputs) — but the precedence is shared.
    mode = select_output_mode(output_key, workflow_ir, shared_storage)

    if mode is OutputMode.EXPLICIT_KEY:
        # Specific key requested. Supports dotted paths (e.g.
        # ``batch.success_count``, ``items[0].title``) via ``TemplateResolver`` —
        # the same primitive used by CLI text mode and ``${...}`` templates
        # inside workflows. ``variable_exists`` distinguishes "path missing"
        # from "path resolved to None" so a legitimately-None value is
        # preserved in the JSON output.
        assert output_key is not None, "EXPLICIT_KEY ⇒ output_key truthy"  # type narrowing for mypy  # noqa: S101
        if TemplateResolver.variable_exists(output_key, shared_storage):
            resolved: Any = TemplateResolver.resolve_value(output_key, shared_storage)
            result[output_key] = compact_batch_output_value(parse_json_or_original(resolved))

    elif mode is OutputMode.ONLY:
        # --only is target-scoped: declared full-run outputs and unrelated
        # root priority keys must not shadow the requested node/sub-workflow.
        # (Decided before DECLARED by the classifier — no guard needed here.)
        only_node = shared_storage.get("__execution__", {}).get("only_node")
        key_found, value = find_only_output(shared_storage, only_node if isinstance(only_node, str) else None)
        if key_found:
            result[key_found] = compact_batch_output_value(parse_json_or_original(value))

    elif mode is OutputMode.DECLARED:
        # Collect ALL declared outputs (full-run JSON contract; text mode
        # streams just one). --only is already handled above.
        for output_name in workflow_ir["outputs"]:
            if output_name in shared_storage:
                result[output_name] = compact_batch_output_value(parse_json_or_original(shared_storage[output_name]))

    else:  # OutputMode.AUTO
        # Auto-detect output for full runs without declared outputs.
        key_found, value = find_auto_output(shared_storage)
        if key_found:
            result[key_found] = compact_batch_output_value(parse_json_or_original(value))

    return result


def partition_surfaced_diagnostics(
    diagnostics: list[Diagnostic] | None,
) -> tuple[list[Diagnostic], list[Diagnostic]]:
    """Split surfaced diagnostics into ``(warnings, advisories)``.

    Warnings (``WARNING``/``ERROR`` severity) drive the "completed with N
    warnings" header. Advisories (``INFO`` severity) are non-degrading notes —
    e.g. an empty batch (a drained iteration loop or a filter that matched
    nothing) or a cache advisory — rendered under their own heading so a fully
    correct run still reads "✓ Workflow completed". Single source of truth for
    both the CLI text renderer and this MCP/success formatter.
    """
    diags = diagnostics or []
    warnings = [d for d in diags if d.severity is not Severity.INFO]
    advisories = [d for d in diags if d.severity is Severity.INFO]
    return warnings, advisories


def format_success_as_text(  # noqa: C901
    success_dict: dict[str, Any],
    warning_diagnostics: list[Diagnostic] | None = None,
) -> str:
    """Convert success dictionary to human-readable text (matches CLI format exactly).

    Args:
        success_dict: Dictionary from format_execution_success()

    Returns:
        Formatted text string matching CLI output
    """
    lines = []

    # Extract data
    duration_ms = success_dict.get("duration_ms", 0)
    duration_sec = duration_ms / 1000 if duration_ms else 0
    total_cost = success_dict.get("total_cost_usd")
    workflow_metadata = success_dict.get("workflow", {})
    workflow_name = workflow_metadata.get("name", "workflow")
    workflow_action = workflow_metadata.get("action", "executed")
    status = success_dict.get("status", "success")
    # INFO advisories (e.g. an empty batch) must not be counted as warnings:
    # only WARNING/ERROR diagnostics drive the "completed with N warnings"
    # header. Advisories render in their own section below.
    warnings_list, advisories_list = partition_surfaced_diagnostics(warning_diagnostics)
    warning_count = len(warnings_list)

    # Show workflow name and action (MCP text only). The CLI summary
    # deliberately dropped this line as redundant with the completion line
    # below (PR #470); MCP keeps it because agents calling the tool have no
    # command-line context for which workflow ran. Do NOT "restore parity" by
    # re-adding it to the CLI.
    if workflow_action == "reused":
        lines.append(f"{workflow_name} was executed")
    elif workflow_action == "created":
        lines.append(f"{workflow_name} was created and executed")
    # Skip for "unsaved" workflows

    # Success header with tri-state status and optional cache stats
    execution_data = success_dict.get("execution", {})
    cache_hits = execution_data.get("cache_hits", 0)
    completed_count = execution_data.get("nodes_executed", 0)
    steps = execution_data.get("steps", [])
    has_stderr_warnings = any(step.get("has_stderr") for step in steps)
    cache_suffix = ""
    if cache_hits > 0:
        executed_fresh = completed_count - cache_hits
        cache_suffix = f" ({cache_hits} cached, {executed_fresh} executed)"

    if status == "degraded":
        lines.append(f"⚠️ Workflow completed with warnings in {duration_sec:.3f}s{cache_suffix}")
    elif status == "denied":
        # Defensive: denied results normally route through the error path (CLI
        # intercepts DENIED before this formatter; MCP goes via success=False),
        # but a denied run must never render the success ✓ if that ever changes.
        lines.append(f"⊘ Workflow denied at an approval gate after {duration_sec:.3f}s{cache_suffix}")
    elif status == "failed":
        if warning_count:
            lines.append(f"❌ Workflow failed ({warning_count} warnings) after {duration_sec:.3f}s{cache_suffix}")
        else:
            lines.append(f"❌ Workflow failed after {duration_sec:.3f}s{cache_suffix}")
    elif warning_count:
        lines.append(f"⚠️ Workflow completed with {warning_count} warnings in {duration_sec:.3f}s{cache_suffix}")
    elif has_stderr_warnings:
        # Shell node(s) exited 0 but wrote to stderr — upgrade glyph to ⚠️
        # so MCP consumers see the same signal CLI users do. The per-node
        # stderr block is rendered below via format_stderr_warnings().
        lines.append(f"⚠️ Workflow completed in {duration_sec:.3f}s{cache_suffix}")
    else:
        lines.append(f"✓ Workflow completed in {duration_sec:.3f}s{cache_suffix}")

    # Show node execution details (matches CLI lines 646-655)
    _append_execution_steps(lines, execution_data)

    # Shell-stderr warnings (CLI/MCP parity — same `format_stderr_warnings`
    # the CLI summary block calls in `_display_execution_summary`)
    lines.extend(format_stderr_warnings(steps))

    # Show cost (matches CLI `_format_cost_summary_lines`). The "Total LLM calls: N"
    # sibling line below the cost line keeps the call tally visible at all
    # three surfaces (CLI text, success formatter, trace report); call counts
    # are also now interpolated into the priced cost line and per-model in
    # the unpriced phrase (Bundle 7 / F#17 deferred).
    metrics = success_dict.get("metrics", {})
    total_metrics = metrics.get("total", {})
    total_llm_calls = int(total_metrics.get("total_calls", 0) or 0)

    if not total_metrics.get("pricing_available", True):
        from pflow.core.metrics import format_unavailable_models_phrase, unavailable_models_to_counts

        unavailable_counts = unavailable_models_to_counts(total_metrics.get("unavailable_models", []))
        unavailable_unnamed_count = total_metrics.get("unavailable_models_unnamed_count", 0)
        models_phrase = format_unavailable_models_phrase(unavailable_counts, unavailable_unnamed_count)
        partial = total_metrics.get("partial_cost_usd")
        if partial is not None:
            lines.append(f"💰 Cost: ${partial:.4f}+ (partial — pricing unavailable for: {models_phrase})")
        else:
            lines.append(f"⚠️  Cost unavailable — pricing data missing for: {models_phrase}")
        if total_llm_calls > 0:
            lines.append(f"   Total LLM calls: {total_llm_calls}")
    elif total_cost and total_cost > 0:
        # The key is ``tokens_total`` (set by MetricsCollector._build_execution_metrics)
        # — cache-inclusive input + output. Mirrors the CLI cost line.
        workflow_metrics = metrics.get("workflow", {})
        tokens_total = workflow_metrics.get("tokens_total", 0)

        detail_parts: list[str] = []
        if total_llm_calls > 0:
            detail_parts.append(f"{total_llm_calls} call{'s' if total_llm_calls != 1 else ''}")
        if tokens_total > 0:
            detail_parts.append(f"{tokens_total:,} tokens")

        if detail_parts:
            lines.append(f"💰 Cost: ${total_cost:.4f} ({', '.join(detail_parts)})")
        else:
            lines.append(f"💰 Cost: ${total_cost:.4f}")

    # Show warnings and advisories in separate sections (matches CLI format).
    # Warnings are regressions; advisories are non-degrading notes.
    if warnings_list:
        lines.append("")
        lines.append("⚠️ Warnings:")
        for warning in warnings_list:
            lines.append(format_diagnostic(warning))
    # Unreachable today: the only production caller is MCP, which passes
    # WARNING-only diagnostics (see the filter in
    # mcp_server/services/execution_service.py). Kept for symmetry with the CLI
    # renderer (workflow_output.py) and exercised by unit tests — a future
    # caller passing the full diagnostics list exercises it for real.
    if advisories_list:
        lines.append("")
        lines.append("\N{INFORMATION SOURCE}\N{VARIATION SELECTOR-16} Advisories:")
        for advisory in advisories_list:
            lines.append(format_diagnostic(advisory))

    # Show outputs if present (matches CLI "Workflow output:" section)
    result = success_dict.get("result", {})
    if result:
        lines.append("")
        lines.append("Workflow output:")
        lines.append("")
        _append_outputs(lines, result)

    # Run identity + trace location (Task 171) — MCP-only text (the CLI has its
    # own stderr trace line and never calls this renderer). Grep-parseable
    # `key: value` lines so an agent can correlate the run with a later
    # `pflow resume` chain or `pflow report` without a side channel.
    execution_id = success_dict.get("execution_id")
    trace_path = success_dict.get("trace_path")
    if execution_id or trace_path:
        lines.append("")
        if execution_id:
            lines.append(f"execution_id: {execution_id}")
        if trace_path:
            lines.append(f"trace_path: {trace_path}")

    return "\n".join(lines)


def _append_outputs(lines: list[str], result: dict[str, Any]) -> None:
    """Append formatted outputs to lines list (matches CLI behavior).

    CLI outputs the FIRST output's value directly (not key: value format).
    Mirrors ``cli/workflow_output.py::safe_output``: strings pass through
    verbatim, structured values are JSON-encoded so MCP consumers can parse
    them with ``jq`` or ``json.loads``.

    On serialization failure (e.g., NaN/Infinity inside an otherwise-valid
    structure, or a custom class whose ``__str__`` raises inside ``default=str``),
    falls back to ``repr(first_value)`` — **not** ``str(first_value)`` — to match
    CLI ``safe_output``'s fallback. The CLI also emits a stderr diagnostic in
    this case; MCP returns strings so it cannot do that, and the divergence on
    warning emission is accepted as a documented gap (see the Task 149 review).
    """
    if not result:
        return

    first_value = next(iter(result.values()))

    if isinstance(first_value, str):
        lines.append(first_value)
        return

    try:
        lines.append(json.dumps(first_value, ensure_ascii=False, allow_nan=False, default=str))
    except (TypeError, ValueError):
        # CLI safe_output falls back to repr(); match it for parity.
        lines.append(repr(first_value))


def format_only_indicator(only_node: str, nodes_skipped: int) -> str:
    """Format the ``--only`` mode confirmation line.

    Single source of truth for the ``--only`` indicator text. Used by:
    - CLI text summary (``cli/workflow_output.py::_display_execution_summary``)
    - CLI ``-p`` mode emission (``cli/workflow_output.py::_emit_mode_indicators``)
    - MCP text summary (``_append_execution_steps`` below)

    Architecturally, ``--only`` is a **mode signal**, not a summary detail.
    Mode flags (which change what the workflow does) are always announced
    regardless of verbosity flags (which hide details). This matches the
    convention of ``make -k``, ``pytest --maxfail``, ``rsync --dry-run``,
    ``apt-get --simulate``, ``kubectl --dry-run``, etc.

    Wording note (issue #443): ``--only`` is snapshot semantics — only the target
    runs; every other node's output is RESTORED from the prior full run, not
    executed. The line therefore says "Ran only 'X'" + "N other node(s) not
    executed", NOT "Stopped after X" / "skipped" (which implied a walk-and-stop
    that no longer happens and would mislead an agent into thinking upstream ran).

    Two forms:
    - Other nodes were restored, not run: ``Ran only 'X' (--only), N other nodes not executed``
    - Single-node workflow (nothing else to restore): ``Ran only 'X' (--only)``
    The shorter form is the fix for the case where the rendered output
    was previously indistinguishable from a full run (sub-issue 8a in
    Task 149's code review).
    """
    if nodes_skipped > 0:
        noun = "node" if nodes_skipped == 1 else "nodes"
        return f"  ⤷ Ran only '{only_node}' (--only), {nodes_skipped} other {noun} not executed"
    return f"  ⤷ Ran only '{only_node}' (--only)"


def format_resume_indicator(resumed_from: str, entry_node: str | None, nodes_restored: int) -> str:
    """Format the resume mode confirmation line (Task 164).

    Single source of truth at parity with ``format_only_indicator`` — same
    rationale: a resume is a **mode signal**, not a summary detail. Without it
    a resumed run's text output is byte-identical to a full run's, and an
    agent doing iterative debugging cannot tell "everything re-ran" from
    "upstream was restored from the failed attempt". Used by the CLI text
    summary + ``-p`` emission (``cli/workflow_output.py``) and the MCP text
    summary (``_append_execution_steps`` below).

    Wording mirrors the ``--only`` line's semantics: restored upstream steps
    were NOT executed this run — their outputs were seeded from the source
    attempt's trace. The shorter no-restored form (K was the first step) still
    announces the mode.
    """
    at_clause = f" at '{entry_node}'" if entry_node else ""
    if nodes_restored > 0:
        noun = "step" if nodes_restored == 1 else "steps"
        return f"  ⤷ Resumed from {resumed_from}{at_clause} — {nodes_restored} upstream {noun} restored"
    return f"  ⤷ Resumed from {resumed_from}{at_clause}"


def format_stderr_warnings(steps: list[dict[str, Any]]) -> list[str]:
    """Format shell-stderr warning block for nodes that exited 0 with non-empty stderr.

    Single source of truth used by both:
    - CLI ``cli/workflow_output.py::_display_execution_summary`` (as a summary block)
    - MCP ``format_success_as_text`` below (extends the lines list)

    Mirrors the CLI/MCP parity pattern established by ``format_only_indicator`` and
    ``_append_outputs``. Without this helper, MCP text output would silently omit
    shell-stderr warnings for workflows where a shell node wrote to stderr but
    exited 0 — agents calling the MCP ``workflow_execute`` tool would get a
    misleading ``✓ Workflow completed`` summary with no visibility into the
    hidden shell pipeline failures.

    Args:
        steps: List of execution step dicts (may contain ``has_stderr`` and ``stderr`` fields)

    Returns:
        Lines to append to output. Empty list when no step has stderr warnings.
        First line is a blank (to separate from preceding content); second is the
        ``⚠️  Shell stderr (exit code 0):`` header; remaining lines are per-node
        bullets with stderr previews truncated to 300 chars and multiline stderr
        indented for readability.
    """
    stderr_warnings = [
        (step.get("node_id", "unknown"), step.get("stderr", ""))
        for step in steps
        if step.get("has_stderr") and step.get("stderr")
    ]

    if not stderr_warnings:
        return []

    lines = ["", "⚠️  Shell stderr (exit code 0):"]
    for node_id, stderr in stderr_warnings:
        # Truncate long stderr to 300 chars
        stderr_preview = stderr[:300]
        if len(stderr) > 300:
            stderr_preview += "..."
        # Indent multiline stderr for readability
        indented = stderr_preview.replace("\n", "\n     ")
        lines.append(f"  • {node_id}: {indented}")

    return lines


def _append_execution_steps(lines: list[str], execution: dict[str, Any]) -> None:
    """Append supplementary execution details: --only summary line + batch errors."""
    if not execution or "steps" not in execution:
        return

    steps = execution["steps"]
    only_node_val = execution.get("only_node")
    nodes_skipped = execution.get("nodes_skipped", 0)

    # Emit the --only mode confirmation whenever --only is active, even
    # when no downstream nodes were skipped (e.g., --only targeted the
    # last node). Without this, the rendered output is byte-identical to
    # a full run and agents doing iterative debugging cannot disambiguate.
    if only_node_val:
        lines.append(format_only_indicator(only_node_val, nodes_skipped))

    # Resume mode confirmation (Task 164) — same mode-signal doctrine as --only.
    resumed_from = execution.get("resumed_from")
    if resumed_from:
        lines.append(
            format_resume_indicator(
                resumed_from, execution.get("resume_entry_node"), execution.get("nodes_restored", 0)
            )
        )

    batch_error_lines = _format_batch_errors_section(steps)
    if batch_error_lines:
        lines.extend(batch_error_lines)


def _truncate_error_message(message: str, max_length: int = 200) -> str:
    return _shared_truncate_error_message(message, max_length)


def _format_batch_errors_section(steps: list[dict[str, Any]]) -> list[str]:
    return _shared_format_batch_errors_section(steps)
