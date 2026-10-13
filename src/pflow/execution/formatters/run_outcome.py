"""The Run outcome (``context/CONTEXT.md``): how a run ended, built once from its ``ExecutionResult``.

``build_run_outcome`` is the one builder for every status — success, degraded, failed, paused,
denied. CLI JSON emits ``RunOutcome.document`` unchanged; the CLI stderr summary and the MCP text
response render it from the section functions below, so a field is added here once, never per channel.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Final

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.diagnostic_render import format_diagnostic, head_tail_preview
from pflow.core.gate import masked_gate_dict
from pflow.core.security_utils import scrub_secret_values, secret_values
from pflow.core.templates import TemplateResolver
from pflow.core.workflow.status import WorkflowStatus
from pflow.execution.execution_state import build_execution_steps
from pflow.execution.formatters.batch_errors import (
    compact_batch_error_detail,
    compact_batch_output_value,
    format_batch_errors_section,
)
from pflow.execution.gate_prompt import format_bulk_approve_hint, format_gate_lines, format_resume_answer_command
from pflow.execution.result import ExecutionResult

# The CLI's exit codes, all in one place (documented in docs/reference/cli/index.mdx → Exit codes).
# A run that ended maps by its status. EXIT_REJECTED means the run never started — the call or the
# workflow is wrong (fix it, then retry): a FAILED outcome whose engine never started, and every CLI
# refusal raised before a run exists. It is Click's usage-error code, so one code means "wrong call"
# whoever caught it. Interrupts exit 130.
EXIT_CODES: Final[Mapping[WorkflowStatus, int]] = MappingProxyType({
    WorkflowStatus.SUCCESS: 0,
    WorkflowStatus.DEGRADED: 0,
    WorkflowStatus.FAILED: 1,
    WorkflowStatus.DENIED: 3,
    WorkflowStatus.PAUSED: 4,
})
EXIT_REJECTED: Final = 2

_ADVISORIES_HEADING = "\N{INFORMATION SOURCE}\N{VARIATION SELECTOR-16} Advisories:"
_NO_ERROR_DETAILS = "❌ Workflow execution failed — no error details were recorded"
# Advisories MCP shows: definition-quality notes with no other surface. Runtime INFO (an empty
# batch) duplicates data an MCP caller can read, so only the CLI renders it; the document has all.
_MCP_ADVISORY_SOURCES = frozenset({"parser", "validator"})
# A diagnostic's or step's string longer than this window — a step's stdout/stderr, a response body, a
# tool error, at any depth — reaches the document as its head and tail (``_excerpted``): an agent reads
# the document whole, and tools write the cause last. The trace (``trace_path``) keeps every value whole.
DOCUMENT_EXCERPT_HEAD_CHARS: Final = 1_000
DOCUMENT_EXCERPT_TAIL_CHARS: Final = 4_000
# Never cut: a gate's request, which the approver consents to whole (``core/gate.py::masked_preview``).
_UNCUT_KEYS = frozenset({"gate"})


@dataclass(frozen=True)
class RunOutcome:
    """One Run outcome. ``document`` is the agent contract (CLI JSON emits it unchanged).

    ``errors``/``warnings``/``advisories`` are the Diagnostics already serialized into the
    document's lists of the same names — kept because text rendering (``format_diagnostic``)
    takes a ``Diagnostic``, and rebuilding one from its printed dict would be a second serializer.
    """

    document: dict[str, Any]
    status: WorkflowStatus
    errors: list[Diagnostic]
    warnings: list[Diagnostic]
    advisories: list[Diagnostic]
    engine_started: bool
    # The run's secret values (``secret_values``), already scrubbed from everything above — kept so a
    # printer that renders from the run's store instead (CLI text stdout) scrubs with the same set.
    secrets: frozenset[str] = frozenset()
    # The step table before the document's excerpts: a text preview of a step's stderr or of a batch
    # item's child failure is cut from the whole value, so the count it says it omitted is true.
    steps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if self.status is WorkflowStatus.FAILED and not self.engine_started:
            return EXIT_REJECTED
        return EXIT_CODES[self.status]


def build_run_outcome(
    result: ExecutionResult,
    workflow_ir: dict[str, Any],
    *,
    workflow_metadata: dict[str, Any] | None,
    output_key: str | None = None,
) -> RunOutcome:
    """Build the one Run outcome for ``result``, whatever its status.

    ``success`` is derived from the outcome's status — the run completed (exit 0) — so ``success``,
    ``status`` and the exit code can never disagree. Keys the run has no value for are absent, never
    ``null`` (no trace file → no ``execution_id``/``trace_path``; no metrics collector → no
    ``duration_ms``/``metrics``).
    Values whose producer means ``null`` keep it: the ``total_cost_usd`` pricing tri-state, a
    ``?? null`` output, the canonical gate payload's ``question``/``recommendation``/``iteration``.
    The run's secret values are scrubbed from its DATA before anything is built from it — the store,
    the diagnostics, a paused gate's request — so truncation and JSON parsing never see a whole
    secret and no channel that renders the outcome can print one. The document's own fields
    (statuses, node ids, counts) are never scrubbed: a stored value that happens to equal one of
    them must not rewrite the contract.
    """
    secrets = secret_values(getattr(result.trace, "inputs", None) or {})
    result = replace(
        result,
        shared_after=scrub_shared_store(result.shared_after, secrets),
        diagnostics=[_scrub_diagnostic(diagnostic, secrets) for diagnostic in result.diagnostics],
    )
    status = _outcome_status(result)
    trace = result.trace
    errors = [] if status is WorkflowStatus.PAUSED else result.errors
    surfaced = [diagnostic for diagnostic in result.diagnostics if diagnostic.severity is not Severity.ERROR]
    warnings, advisories = partition_surfaced_diagnostics(surfaced)
    printed_errors = [_printed(error) for error in errors]
    metrics_summary = _metrics_summary(result)

    document: dict[str, Any] = {
        "success": status in (WorkflowStatus.SUCCESS, WorkflowStatus.DEGRADED),
        "status": status.value,
        "workflow": workflow_metadata or {"action": "unsaved"},
    }
    # Identity is the trace FILE: an id with no file to resolve against is not run identity.
    if trace is not None and trace.trace_path is not None:
        document["execution_id"] = trace.execution_id
        document["trace_path"] = str(trace.trace_path)
    # Again after collection: an output is JSON-decoded there, which can restore a secret the store held encoded.
    outputs = scrub_secret_values(_outputs(result, status, workflow_ir, output_key), secrets)
    if outputs is not None:
        document["result"] = outputs
    if printed_errors:
        document["error"] = (
            printed_errors[0]["message"]
            if len(printed_errors) == 1
            else f"Workflow execution failed ({len(printed_errors)} errors)"
        )
    document["errors"] = printed_errors
    document["warnings"] = [_printed(diagnostic) for diagnostic in warnings]
    document["advisories"] = [_printed(diagnostic) for diagnostic in advisories]
    document["diagnostics"] = printed_errors + [_printed(diagnostic) for diagnostic in surfaced]
    if metrics_summary is not None:
        document["duration_ms"] = metrics_summary["duration_ms"]
        document["total_cost_usd"] = metrics_summary["total_cost_usd"]
        _mirror_pricing_tri_state(document, metrics_summary)
        document["metrics"] = metrics_summary["metrics"]
    gate = _gate_payload(result, status, secrets)
    execution = _execution_block(workflow_ir, result.shared_after, metrics_summary, gate)
    if execution is not None:
        document["execution"] = {**execution, "steps": _excerpted(execution["steps"])}
    if gate is not None:
        document["gate"] = gate
    resume_command = _resume_command(document, status, trace, gate)
    if resume_command is not None:
        document["resume_command"] = resume_command

    return RunOutcome(
        document=document,
        status=status,
        errors=errors,
        warnings=warnings,
        advisories=advisories,
        engine_started=result.engine_started,
        secrets=secrets,
        steps=execution["steps"] if execution is not None else [],
    )


def _printed(diagnostic: Diagnostic) -> dict[str, Any]:
    """The diagnostic as the document prints it: redacted (``to_output_dict``), long strings excerpted."""
    printed: dict[str, Any] = _excerpted(diagnostic.to_output_dict())
    return printed


def _excerpted(value: Any) -> Any:
    """A copy of ``value`` with every string past the document window cut to its head and tail
    (``_UNCUT_KEYS`` excepted)."""
    if isinstance(value, str):
        return head_tail_preview(value, DOCUMENT_EXCERPT_HEAD_CHARS, DOCUMENT_EXCERPT_TAIL_CHARS)
    if isinstance(value, dict):
        return {key: item if key in _UNCUT_KEYS else _excerpted(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):  # a tuple prints as a JSON array too
        return [_excerpted(item) for item in value]
    return value


# The store's bookkeeping of node ids (routing, cache hits): what output selection and the step table
# match node ids against, never data — scrubbing one that equals a stored value would break the match.
_NODE_ID_RECORDS = frozenset({"__execution__", "__cache_hits__"})


def scrub_shared_store(shared: dict[str, Any], secrets: frozenset[str]) -> dict[str, Any]:
    """A copy of a run's store scrubbed of ``secrets`` — every value but its node-id records; top-level
    keys (node ids, input and output names) stay as they are, so lookups still resolve."""
    if not secrets:
        return shared
    return {
        key: value if key in _NODE_ID_RECORDS else scrub_secret_values(value, secrets) for key, value in shared.items()
    }


def _scrub_diagnostic(diagnostic: Diagnostic, secrets: frozenset[str]) -> Diagnostic:
    """A copy whose text fields — what ``format_diagnostic`` renders — are scrubbed of ``secrets``."""
    if not secrets:
        return diagnostic
    return replace(
        diagnostic,
        message=scrub_secret_values(diagnostic.message, secrets),
        title=scrub_secret_values(diagnostic.title, secrets),
        suggestions=scrub_secret_values(diagnostic.suggestions, secrets),
        context=scrub_secret_values(diagnostic.context, secrets),
    )


def _outcome_status(result: ExecutionResult) -> WorkflowStatus:
    """The status the outcome reports — the result's, except a PAUSED run whose trailer never reached
    disk: no token would resolve, so it ends as FAILED (the gate's remediation ladder stays in its errors).
    """
    if result.status is WorkflowStatus.PAUSED and not result.is_durable_pause:
        return WorkflowStatus.FAILED
    return result.status


def _metrics_summary(result: ExecutionResult) -> dict[str, Any] | None:
    if result.metrics is None:
        return None
    llm_calls = result.trace.collect_llm_calls() if result.trace is not None else []
    summary: dict[str, Any] = result.metrics.get_summary(llm_calls)
    return summary


def _outputs(
    result: ExecutionResult, status: WorkflowStatus, workflow_ir: dict[str, Any], output_key: str | None
) -> dict[str, Any] | None:
    if status in (WorkflowStatus.SUCCESS, WorkflowStatus.DEGRADED):
        return _collect_outputs(result.shared_after, workflow_ir, output_key)
    if status is WorkflowStatus.FAILED:
        return collect_outputs_resolved_before_failure(result, workflow_ir)
    return None


def _execution_block(
    workflow_ir: dict[str, Any],
    shared: dict[str, Any],
    metrics_summary: dict[str, Any] | None,
    gate: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """The step table — ``nodes_executed`` counts steps completed in THIS attempt (restored ≠ executed)."""
    steps = [_compact_step(step) for step in build_execution_steps(workflow_ir, shared, metrics_summary)]
    if not steps:
        return None
    for step in steps:
        if gate is not None and step["node_id"] == gate.get("node_id") and step["status"] == "completed":
            # The gate stopped its step before it ran: the output a looping step carries in from its
            # earlier iterations (or the resumed attempt) is not this step completing.
            step["status"] = "not_executed"
    execution: dict[str, Any] = {}
    if metrics_summary is not None:
        execution["duration_ms"] = metrics_summary["duration_ms"]
    execution["nodes_executed"] = sum(1 for step in steps if step["status"] == "completed")
    execution["nodes_total"] = len(steps)
    execution["steps"] = steps

    exec_state = shared.get("__execution__") or {}
    only_node = exec_state.get("only_node")
    if only_node:
        execution["only_node"] = only_node
        # The target is never one of the "other" nodes, even when a gate stopped it unrun.
        execution["nodes_skipped"] = sum(
            1 for step in steps if step["status"] == "not_executed" and step["node_id"] != only_node
        )
    resumed_from = exec_state.get("resumed_from")
    if resumed_from:
        execution["resumed_from"] = resumed_from
        execution["nodes_restored"] = len(exec_state.get("restored_nodes", []))
        entry_node = exec_state.get("resume_entry_node")
        if entry_node:
            execution["resume_entry_node"] = entry_node
        execution["resume_entry_iteration"] = exec_state.get("resume_entry_iteration", 1)
    cache_hits = sum(1 for step in steps if step.get("cached"))
    if cache_hits:
        execution["cache_hits"] = cache_hits
    return execution


def _compact_step(step: dict[str, Any]) -> dict[str, Any]:
    details = step.get("batch_error_details")
    if not isinstance(details, list):
        return step
    compacted = [compact_batch_error_detail(detail) if isinstance(detail, dict) else detail for detail in details]
    return {**step, "batch_error_details": compacted}


def _gate_payload(result: ExecutionResult, status: WorkflowStatus, secrets: frozenset[str]) -> dict[str, Any] | None:
    """The masked ``GateRequest`` dict of a paused or denied run — one shape for both (``node_id`` inside)."""
    if status is WorkflowStatus.PAUSED and result.trace is not None:  # a durable pause always has its trace
        request = (result.trace.pause_request or {}).get("gate_request")
        if not isinstance(request, dict):
            return None
        # The request comes from the trace, not the scrubbed store: scrub what it shows, not who it is.
        identity = {key: request[key] for key in ("node_id", "node_type", "kind") if key in request}
        return masked_gate_dict({**scrub_secret_values(request, secrets), **identity})
    if status is WorkflowStatus.DENIED:
        for error in result.errors:
            context = error.context or {}
            if context.get("category") == "gate" and isinstance(context.get("gate"), dict):
                gate: dict[str, Any] = context["gate"]  # masked at the producer (_masked_gate_payload)
                return gate
    return None


def _resume_command(
    document: dict[str, Any], status: WorkflowStatus, trace: Any, gate: dict[str, Any] | None
) -> str | None:
    if status is WorkflowStatus.PAUSED and gate is not None:
        return format_resume_answer_command(trace.execution_id, gate)
    # has_resumable_step() is the one resumability suppressor: False means the loader would refuse.
    if status is WorkflowStatus.FAILED and "trace_path" in document and trace.has_resumable_step():
        return f"pflow resume {trace.execution_id}"
    return None


def _mirror_pricing_tri_state(result: dict[str, Any], metrics_summary: dict[str, Any]) -> None:
    """Mirror the pricing tri-state (partial_cost_usd / pricing_available /
    unavailable_models) from metrics_summary to top-level result keys.

    When pricing is unavailable for any LLM call, the bare top-level
    ``total_cost_usd: null`` is ambiguous — agents can't tell "no LLM calls"
    from "calls happened but pricing data missing." Mirroring the
    discriminators alongside makes the cause obvious without drilling into
    ``result["metrics"]["total"]``. ``subscription`` is mirrored for the same
    reason: subscription-billed agent calls also leave the paid total null.
    """
    for key in ("partial_cost_usd", "subscription"):
        if metrics_summary.get(key) is not None:
            result[key] = metrics_summary[key]
    if metrics_summary.get("pricing_available") is not False:
        return
    result["pricing_available"] = False
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
            if not TemplateResolver.reads_declared_input(output_key, shared_storage):
                resolved = parse_json_or_original(resolved)  # a declared input's text is never re-parsed
            result[output_key] = compact_batch_output_value(resolved)

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
        result = collect_declared_outputs(shared_storage, workflow_ir)

    else:  # OutputMode.AUTO
        # Auto-detect output for full runs without declared outputs.
        key_found, value = find_auto_output(shared_storage)
        if key_found:
            # A root hit can be a declared input, whose text is never re-parsed (as for `-o` above).
            from_input = shared_storage.get(key_found) is value and TemplateResolver.reads_declared_input(
                key_found, shared_storage
            )
            result[key_found] = compact_batch_output_value(value if from_input else parse_json_or_original(value))

    return result


def collect_declared_outputs(shared_storage: dict[str, Any], workflow_ir: dict[str, Any]) -> dict[str, Any]:
    """Every declared output present in shared storage, keyed by output name."""
    from pflow.core.json_utils import parse_json_or_original

    return {
        name: compact_batch_output_value(parse_json_or_original(shared_storage[name]))
        for name in workflow_ir.get("outputs", {})
        if name in shared_storage
    }


def collect_outputs_resolved_before_failure(
    result: ExecutionResult, workflow_ir: dict[str, Any]
) -> dict[str, Any] | None:
    """The declared outputs that resolved in a run that failed at output resolution.

    ``populate_declared_outputs`` writes each output it can resolve before raising
    ``OutputResolutionError``, so those values are real. Every other failure stops
    before outputs are populated — a declared name in shared storage is then a node
    or input of the same name, not an output — so this returns ``None``.
    """
    failed: set[str] = set()
    for diagnostic in result.errors:
        context = diagnostic.context or {}
        if context.get("is_output_resolution"):
            failed.update(block["output_name"] for block in context["output_failures"])
    if not failed:
        return None
    resolved = collect_declared_outputs(result.shared_after, workflow_ir)
    return {name: value for name, value in resolved.items() if name not in failed}


def partition_surfaced_diagnostics(
    diagnostics: list[Diagnostic] | None,
) -> tuple[list[Diagnostic], list[Diagnostic]]:
    """Split surfaced diagnostics into ``(warnings, advisories)``.

    Warnings (``WARNING``/``ERROR`` severity) drive the "completed with N
    warnings" header. Advisories (``INFO`` severity) are non-degrading notes —
    e.g. an empty batch (a drained iteration loop or a filter that matched
    nothing) or a cache advisory — rendered under their own heading so a fully
    correct run still reads "✓ Workflow completed".
    """
    diags = diagnostics or []
    warnings = [d for d in diags if d.severity is not Severity.INFO]
    advisories = [d for d in diags if d.severity is Severity.INFO]
    return warnings, advisories


# --- Section functions: each renders one part of an outcome as text lines. The CLI stderr
# summary and the MCP text response compose them; neither assembles a section itself.


def completion_line(outcome: RunOutcome) -> list[str]:
    """The one line that says how the run ended — one arm per status.

    Duration-bearing arms (success, degraded, failed) read ``document["duration_ms"]``: a run
    that ended before its metrics collector existed has none, so it gets no completion line.
    """
    document = outcome.document
    execution = document.get("execution") or {}
    gate_node = (document.get("gate") or {}).get("node_id")
    if outcome.status is WorkflowStatus.PAUSED:
        where = f" at '{gate_node}'" if gate_node else ""
        return [f"⏸ Workflow paused{where} — a human decision is required."]
    if outcome.status is WorkflowStatus.DENIED:
        gate_name = f" '{gate_node}'" if gate_node else ""
        progress = (
            f" Steps completed: {execution['nodes_executed']} of {execution['nodes_total']}." if execution else ""
        )
        return [f"✗ Denied at gate{gate_name}. Workflow stopped cleanly before the step ran.{progress} (exit 3)"]

    duration_ms = document.get("duration_ms")
    if duration_ms is None:
        return []
    took = f"{duration_ms / 1000:.3f}s{_cache_suffix(execution)}"
    warning_count = len(outcome.warnings)
    if outcome.status is WorkflowStatus.FAILED:
        noted = f" ({warning_count} warnings)" if warning_count else ""
        return [f"❌ Workflow failed{noted} after {took}"]
    if outcome.status is WorkflowStatus.DEGRADED:
        return [f"⚠️ Workflow completed with warnings in {took}"]
    if warning_count:
        return [f"⚠️ Workflow completed with {warning_count} warnings in {took}"]
    if any(step.get("has_stderr") for step in execution.get("steps", [])):
        # A shell step exited 0 but wrote stderr: the glyph says "look", the stderr block says what.
        return [f"⚠️ Workflow completed in {took}"]
    return [f"✓ Workflow completed in {took}"]


def _cache_suffix(execution: dict[str, Any]) -> str:
    cache_hits = execution.get("cache_hits", 0)
    if not cache_hits:
        return ""
    return f" ({cache_hits} cached, {execution['nodes_executed'] - cache_hits} executed)"


def mode_lines(document: dict[str, Any]) -> list[str]:
    """The ``--only`` / resume mode confirmations — mode signals that survive ``-p``."""
    execution = document.get("execution") or {}
    lines: list[str] = []
    only_node = execution.get("only_node")
    if only_node:
        target = next((step for step in execution["steps"] if step["node_id"] == only_node), None)
        ran = target is None or target["status"] != "not_executed"
        lines.append(format_only_indicator(only_node, execution.get("nodes_skipped", 0), ran=ran))
    resumed_from = execution.get("resumed_from")
    if resumed_from:
        lines.append(
            format_resume_indicator(
                resumed_from,
                execution.get("resume_entry_node"),
                execution.get("nodes_restored", 0),
                execution.get("resume_entry_iteration", 1),
            )
        )
    return lines


def errors_block(errors: list[Diagnostic], warnings: list[Diagnostic], *, verbose: bool = False) -> list[str]:
    """Every error: one titled diagnostic, or a counted header then each one numbered.

    A failure that recorded no error diagnostic still says it failed — never an empty block.
    """
    if len(errors) == 1:
        return [format_diagnostic(errors[0], verbose=verbose).rstrip("\n")]
    if not errors:
        return [_NO_ERROR_DETAILS]
    noted = f", {len(warnings)} warning{'s' if len(warnings) != 1 else ''}" if warnings else ""
    lines = [f"❌ Workflow execution failed ({len(errors)} errors{noted})"]
    for number, error in enumerate(errors, 1):
        lines += ["", format_diagnostic(error, verbose=verbose, error_number=number).rstrip("\n")]
    return lines


def diagnostic_sections(warnings: list[Diagnostic], advisories: list[Diagnostic]) -> list[str]:
    """The Warnings section, then the Advisories section — a warning degrades the run, an advisory never does."""
    lines: list[str] = []
    if warnings:
        lines += ["⚠️ Warnings:", *(format_diagnostic(warning) for warning in warnings)]
    if advisories:
        lines += [*([""] if lines else []), _ADVISORIES_HEADING, *(format_diagnostic(a) for a in advisories)]
    return lines


def gate_lines(outcome: RunOutcome) -> list[str]:
    """A paused gate's content, unindented. A denial is final, so it renders no gate to answer."""
    gate = outcome.document.get("gate")
    if outcome.status is not WorkflowStatus.PAUSED or gate is None:
        return []
    return format_gate_lines(gate)


def answer_lines(outcome: RunOutcome) -> list[str]:
    """``To answer: <resume_command>`` plus a looping gate's bulk-approval hint — paused runs only."""
    document = outcome.document
    resume_command = document.get("resume_command")
    if outcome.status is not WorkflowStatus.PAUSED or resume_command is None:
        return []
    return [f"To answer: {resume_command}", *_bulk_hint(document)]


def _bulk_hint(document: dict[str, Any]) -> list[str]:
    """A looping approval gate's "approve every remaining iteration" line, else nothing."""
    if "execution_id" not in document or "gate" not in document:
        return []
    hint = format_bulk_approve_hint(document["execution_id"], document["gate"])
    return [hint] if hint else []


def resolved_outputs_note(document: dict[str, Any]) -> list[str]:
    """The declared outputs that resolved before an output-resolution failure (#754)."""
    resolved = document.get("result")
    if document["status"] != WorkflowStatus.FAILED.value or not resolved:
        return []
    try:
        rendered = json.dumps(resolved, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # non-str dict keys; same fallback as the success text's outputs
        rendered = repr(resolved)
    return ["Outputs that resolved before the failure:", rendered]


def identity_lines(document: dict[str, Any]) -> list[str]:
    """Grep-parseable ``key: value`` lines naming the run — present keys only."""
    return [
        f"{key}: {document[key]}"
        for key in ("status", "execution_id", "trace_path", "resume_command")
        if key in document
    ]


def render_cli_stderr(outcome: RunOutcome, *, text_mode: bool, print_flag: bool, verbose: bool) -> list[str]:
    """The CLI's stderr lines for an outcome, by tier (the stdout data is the caller's).

    must-act — errors, a failed run's batch item errors, the resolved-outputs note, a pause's gate
    and answer, the resume hint, the denied line — prints in text mode with or without ``-p``; in
    JSON mode it is in the document instead. The ``⤷`` mode lines print in every mode. summary —
    the completion line, a non-failed run's batch errors, shell stderr, cost, warnings, advisories,
    the trace line — prints unless ``-p``. A pause has no completion line here: its stdout token
    line announces it. Warnings precede the errors so the cause sits last in the stream.
    """
    document = outcome.document
    status = outcome.status
    steps = outcome.steps
    batch_errors = format_batch_errors_section(steps)
    must_act = text_mode
    summary = not print_flag

    completion_shown = must_act if status is WorkflowStatus.DENIED else summary and status is not WorkflowStatus.PAUSED
    blocks: list[tuple[bool, list[str]]] = [
        # The mode lines sit directly under the completion line they qualify, and print alone without it.
        (True, [*(completion_line(outcome) if completion_shown else []), *mode_lines(document)]),
        (must_act if status is WorkflowStatus.FAILED else summary, batch_errors),
        (summary, format_stderr_warnings(steps)),
        (summary, format_cost_summary_lines(document)),
        (summary, diagnostic_sections(outcome.warnings, outcome.advisories)),
        # A denial's one error is the human's no — the denied line says it; it is not rendered as a failure.
        (must_act and status is WorkflowStatus.FAILED, errors_block(outcome.errors, outcome.warnings, verbose=verbose)),
        (must_act, resolved_outputs_note(document)),
        (must_act, [f"   {line}" for line in gate_lines(outcome)]),
        (must_act, answer_lines(outcome)),
        (
            must_act and status is WorkflowStatus.FAILED and "resume_command" in document,
            [f"To resume from the failed step: {document.get('resume_command')}"],
        ),
        (summary and "trace_path" in document, [f"Workflow trace saved: {document.get('trace_path')}"]),
    ]
    lines = _join_blocks([block for shown, block in blocks if shown])
    # The leading blank separates the summary from the progress stream, which -p never prints.
    return lines[1:] if print_flag else lines


def render_mcp_text(outcome: RunOutcome) -> str:
    """The MCP ``workflow_execute`` response for an outcome — one layout for every status.

    MCP has no stdout/stderr split, so every tier renders, the result value included, and the run
    ends with grep-parseable identity lines (``status:`` / ``execution_id:`` / ``trace_path:`` /
    ``resume_command:``). Runtime INFO advisories are left to the document (``_MCP_ADVISORY_SOURCES``).
    """
    document = outcome.document
    steps = outcome.steps
    workflow = document["workflow"]
    # MCP-only: an agent calling the tool has no command line naming the workflow it ran. The CLI
    # summary dropped this line as redundant (PR #470) — do not "restore parity" there.
    named = {
        "reused": [f"{workflow.get('name', 'workflow')} was executed"],
        "created": [f"{workflow.get('name', 'workflow')} was created and executed"],
    }.get(workflow.get("action"), [])
    head = [
        *named,
        *completion_line(outcome),
        *mode_lines(document),
        *format_batch_errors_section(steps),
        *format_stderr_warnings(steps),
        *format_cost_summary_lines(document),
    ]
    advisories = [a for a in outcome.advisories if a.source in _MCP_ADVISORY_SOURCES]
    outputs: list[str] = []
    if outcome.status in (WorkflowStatus.SUCCESS, WorkflowStatus.DEGRADED) and document.get("result"):
        outputs = ["Workflow output:", ""]
        _append_outputs(outputs, document["result"])
    gate = gate_lines(outcome)
    sections = [
        diagnostic_sections(outcome.warnings, advisories),
        errors_block(outcome.errors, outcome.warnings) if outcome.status is WorkflowStatus.FAILED else [],
        resolved_outputs_note(document),
        outputs,
        ["Gate:", *(f"  {line}" for line in gate)] if gate else [],
        [*identity_lines(document), *(_bulk_hint(document) if outcome.status is WorkflowStatus.PAUSED else [])],
    ]
    body = _join_blocks(sections)
    return "\n".join([*head, *body] if head else body[1:])


def _join_blocks(blocks: list[list[str]]) -> list[str]:
    """One blank line before each non-empty block; a block's own leading/trailing blanks are dropped."""
    lines: list[str] = []
    for block in blocks:
        trimmed = list(block)
        while trimmed and not trimmed[0].strip():
            trimmed.pop(0)
        while trimmed and trimmed[-1] == "":
            trimmed.pop()
        if trimmed:
            trimmed[0] = trimmed[0].lstrip("\n")  # a section header with its own separator baked in
            lines += ["", *trimmed]
    return lines


def format_error_text(errors: list[Diagnostic], warnings: list[Diagnostic]) -> str:
    """Errors + warnings text for a failure that has no Run outcome — the ``registry_run`` single-node probe.

    Composed from the same section functions as the run renderers; ``warnings`` may hold INFO
    advisories, which render under their own heading.
    """
    warning_list, advisories = partition_surfaced_diagnostics(warnings)
    lines = errors_block(errors, warning_list)
    sections = diagnostic_sections(warning_list, advisories)
    if sections:
        lines += ["", *sections]
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


def format_cost_summary_lines(document: dict[str, Any]) -> list[str]:
    """Build the LLM cost summary lines shared by the CLI summary and MCP text.

    The first line names the run's cost state, and the three states stay
    distinguishable (see ``MetricsCollector.calculate_costs``):

    - paid: ``💰 Cost: $0.0420 (2 calls, 1,234 tokens)``
    - subscription-billed agent calls: ``💰 Cost: [$paid + ]subscription (N agent
      calls) · API-equivalent[ total]: $X`` — the estimate, labelled, never a
      "pricing missing" warning
    - unpriced API calls: ``⚠️  Cost unavailable — pricing data missing for: …``
      (or the ``$X+ (partial — …)`` form), with any subscription calls on a
      ``   + subscription …`` sibling line

    A ``   Total LLM calls: N`` sibling line follows the subscription and
    unpriced forms whenever LLM calls ran (the priced form carries the count
    inline). Returns ``[]`` when there is no cost to show — a run with no LLM
    calls never sees ``Total LLM calls: 0``.

    Args:
        document: A Run outcome document (``RunOutcome.document``).
    """
    from pflow.core.metrics import (
        format_subscription_phrase,
        format_unavailable_models_phrase,
        unavailable_models_to_counts,
    )

    metrics = document.get("metrics", {})
    total_metrics = metrics.get("total", {})
    total_llm_calls = int(total_metrics.get("total_calls", 0) or 0)
    calls_line = [f"   Total LLM calls: {total_llm_calls}"] if total_llm_calls > 0 else []
    subscription = total_metrics.get("subscription")
    partial = total_metrics.get("partial_cost_usd")

    if not total_metrics.get("pricing_available", True):
        unavailable_counts = unavailable_models_to_counts(total_metrics.get("unavailable_models", []))
        unavailable_unnamed_count = total_metrics.get("unavailable_models_unnamed_count", 0)
        models_phrase = format_unavailable_models_phrase(unavailable_counts, unavailable_unnamed_count)
        if partial is not None:
            lines = [f"💰 Cost: ${partial:.4f}+ (partial — pricing unavailable for: {models_phrase})"]
        else:
            lines = [f"⚠️  Cost unavailable — pricing data missing for: {models_phrase}"]
        if subscription:
            lines.append(f"   + {format_subscription_phrase(subscription)}")
        return lines + calls_line

    if subscription:
        paid_prefix = f"${partial:.4f} + " if partial else ""
        return [f"💰 Cost: {paid_prefix}{format_subscription_phrase(subscription, paid_cost=partial)}", *calls_line]

    total_cost = document.get("total_cost_usd")
    if total_cost is None or total_cost <= 0:
        return []

    # The key is ``tokens_total`` (set by MetricsCollector._build_execution_metrics)
    # — cache-inclusive input + output.
    tokens_total = metrics.get("workflow", {}).get("tokens_total", 0)
    detail_parts: list[str] = []
    if total_llm_calls > 0:
        detail_parts.append(f"{total_llm_calls} call{'s' if total_llm_calls != 1 else ''}")
    if tokens_total > 0:
        detail_parts.append(f"{tokens_total:,} tokens")
    if detail_parts:
        return [f"💰 Cost: ${total_cost:.4f} ({', '.join(detail_parts)})"]
    return [f"💰 Cost: ${total_cost:.4f}"]


def format_only_indicator(only_node: str, nodes_skipped: int, *, ran: bool) -> str:
    """Format the ``--only`` mode confirmation line (composed by ``mode_lines``).

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
    "Ran only" is false when a gate stopped the target before it ran, so that
    case (``ran=False``) says the target was selected and did not run.

    The ``N other node(s)`` clause is dropped when nothing else was restored (a
    single-node workflow) — the shorter form still announces the mode (sub-issue
    8a in Task 149's code review).
    """
    others = ""
    if nodes_skipped > 0:
        noun = "node" if nodes_skipped == 1 else "nodes"
        others = f", {nodes_skipped} other {noun} not executed"
    if ran:
        return f"  ⤷ Ran only '{only_node}' (--only){others}"
    return f"  ⤷ Only '{only_node}' was selected (--only); it did not run{others}"


def format_resume_indicator(
    resumed_from: str, entry_node: str | None, nodes_restored: int, entry_iteration: int = 1
) -> str:
    """Format the resume mode confirmation line (Task 164).

    Single source of truth at parity with ``format_only_indicator`` — same
    rationale: a resume is a **mode signal**, not a summary detail. Without it
    a resumed run's text output is byte-identical to a full run's, and an
    agent doing iterative debugging cannot tell "everything re-ran" from
    "upstream was restored from the failed attempt".

    Wording mirrors the ``--only`` line's semantics: restored upstream steps
    were NOT executed this run — their outputs were seeded from the source
    attempt's trace. The shorter no-restored form (K was the first step) still
    announces the mode. A loop step resumed past its first iteration names the
    iteration it continues at (Task 179): ``at 'k' (iteration 3)``.
    """
    at_clause = f" at '{entry_node}'" if entry_node else ""
    if entry_node and entry_iteration > 1:
        at_clause += f" (iteration {entry_iteration})"
    if nodes_restored > 0:
        noun = "step" if nodes_restored == 1 else "steps"
        return f"  ⤷ Resumed from {resumed_from}{at_clause} — {nodes_restored} upstream {noun} restored"
    return f"  ⤷ Resumed from {resumed_from}{at_clause}"


def format_stderr_warnings(steps: list[dict[str, Any]]) -> list[str]:
    """The shell-stderr block for steps that exited 0 with non-empty stderr.

    Without it a pipeline whose inner command failed (exit 0 overall, the cause on
    stderr) reads as a clean ``✓ Workflow completed`` on both channels.

    Returns ``[]`` when no step has stderr; otherwise a leading blank line, the
    ``⚠️  Shell stderr (exit code 0):`` header, and one bullet per step whose stderr
    preview keeps head and tail (``head_tail_preview``), continuation lines indented.
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
        indented = head_tail_preview(stderr).replace("\n", "\n     ")
        lines.append(f"  • {node_id}: {indented}")

    return lines
