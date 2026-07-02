"""Engine-side gate machinery (Task 125): approval + escalation seams.

The engine owns WHEN a gate fires and the trace events around it; HOW the human
answers is the installed resolver's job (``__gate_resolver__`` in the shared store
— see ``core/gate.py`` for the resolver contract). This module holds everything
the two ``_execute_node`` hook points need, keeping the engine additions to a few
lines each.

Escalation marker contract (documented in the guide): a node's ``result``, when a
dict, may carry ``escalation``:

    {"escalation": {"question": str, "options": [{"label", "description",
     "tradeoffs"?}], "recommendation"?: str}}

Lenient-but-loud shape ladder (review-hardened — a swallowed escalation is the
silent-bad-decision failure this feature exists to prevent):
- dict without a ``decision`` key      → escalate
- non-empty string                     → escalate, string is the question
- dict WITH ``decision``               → already answered elsewhere; never re-prompt
- empty dict / other truthy shapes     → NO pause + degrading warning
- string ``result`` + ``_schema_error``+ "escalation" substring → degrading warning
  (a schema soft-failure may have swallowed an escalation attempt)

The human's choice is written INTO the marker (``result.escalation.decision``) so
re-exposure of the same result — through a sub-workflow output or a batch item
snapshot — can never re-trigger the prompt (idempotent by construction).
"""

import logging
from typing import Any, Optional, Union

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.exceptions import GateDenied, GateNotInteractiveError, PflowError
from pflow.core.gate import (
    GateRequest,
    GateResolution,
    build_approval_request,
    build_escalation_request,
)

logger = logging.getLogger(__name__)

GATE_RESOLVER_KEY = "__gate_resolver__"
GATE_PROMPT_ALLOWED_KEY = "__gate_prompt_allowed__"

_QUESTION_PREVIEW_CHARS = 120


def resolve_gate(request: GateRequest, shared: dict[str, Any]) -> GateResolution:
    """Resolve one gate via the installed resolver.

    No resolver installed → this run has no human channel → loud, payload-carrying
    error (never hang, never silently approve). ``__gate_prompt_allowed__`` is
    False only inside parallel-batch worker stores (set by the batch executor):
    the resolver may still auto-approve from its flag set there, but must not
    prompt — worker output is buffered and stdin is not shareable across threads.
    """
    resolver = shared.get(GATE_RESOLVER_KEY)
    allow_prompt = bool(shared.get(GATE_PROMPT_ALLOWED_KEY, True))
    if resolver is None:
        raise GateNotInteractiveError(request, parallel_batch=not allow_prompt)
    resolution = resolver(request, allow_prompt=allow_prompt)
    if not isinstance(resolution, GateResolution):
        raise PflowError(
            f"gate resolver returned {type(resolution).__name__} instead of GateResolution "
            f"for gate '{request.node_id}' — broken resolver installation"
        )
    return resolution


def run_approval_gate(config: Any, params: Any, shared: dict[str, Any], trace: Any) -> None:
    """Pre-exec approval gate: pause → resolve → continue or raise ``GateDenied``.

    Sits BEFORE the start callback and the ``node.start`` trace marker, so a
    denied node never appears in the trace and no progress line is open.
    """
    request = build_approval_request(config.node_id, config.node_type_name, params)
    _record_gate(trace, request, phase="pause")
    try:
        resolution = resolve_gate(request, shared)
    except GateNotInteractiveError:
        _record_gate(trace, request, phase="resolution", resolution="non_interactive")
        raise
    if not resolution.approved:
        _record_gate(trace, request, phase="resolution", resolution="denied", resolved_via=resolution.resolved_via)
        raise GateDenied(request)
    _record_gate(trace, request, phase="resolution", resolution="approved", resolved_via=resolution.resolved_via)


def detect_escalation(shared: dict[str, Any], node_id: str) -> Optional[Union[dict[str, Any], str]]:
    """Return the node's undecided escalation marker, or ``None``.

    Applies the shape ladder above; unusable-but-clearly-intended shapes write a
    degrading warning so a dropped escalation is never silent.
    """
    node_ns = shared.get(node_id)
    if not isinstance(node_ns, dict):
        return None
    result = node_ns.get("result")
    if isinstance(result, str):
        if node_ns.get("_schema_error") and "escalation" in result:
            _warn_escalation(
                shared,
                node_id,
                f"Step '{node_id}' returned a raw string after a schema soft-failure and the text "
                f"mentions 'escalation' — an escalation attempt may have been swallowed; the run did "
                f"NOT pause. Fix the step's output_schema conformance (or raise schema_retries).",
            )
        return None
    if not isinstance(result, dict):
        return None
    marker = result.get("escalation")
    if marker is None or marker is False or marker == "" or marker == 0:
        return None
    if isinstance(marker, dict):
        if "decision" in marker:
            return None  # already answered; re-exposure must not re-prompt
        if not marker:
            _warn_escalation(
                shared,
                node_id,
                f"Step '{node_id}' emitted an EMPTY 'escalation' marker — expected "
                f"{{question, options, recommendation}}; the run did NOT pause.",
            )
            return None
        return marker
    if isinstance(marker, str):
        return marker
    _warn_escalation(
        shared,
        node_id,
        f"Step '{node_id}' emitted 'escalation' with an unusable shape ({type(marker).__name__}) — "
        f"expected {{question, options, recommendation}} or a question string; the run did NOT pause.",
    )
    return None


def run_escalation_gate(config: Any, marker: Union[dict[str, Any], str], shared: dict[str, Any], trace: Any) -> None:
    """Post-exec escalation gate: pause → human chooses → decision written into the marker.

    Runs AFTER the node's own completion trace/callbacks (its success record
    stands untouched) and BEFORE the walk's loop-re-entry check reads the store —
    so ``loop:`` + carry wiring folds ``${step.result.escalation.decision}`` into
    the re-forked agent. There is no deny: the resolver returns a choice.
    """
    request = build_escalation_request(config.node_id, config.node_type_name, marker)
    _record_gate(trace, request, phase="pause")
    try:
        resolution = resolve_gate(request, shared)
    except GateNotInteractiveError:
        _record_gate(trace, request, phase="resolution", resolution="non_interactive")
        raise
    decision = {"chosen": resolution.chosen, "notes": resolution.notes}
    result = shared[config.node_id]["result"]
    if isinstance(marker, str):
        result["escalation"] = {"question": marker, "decision": decision}
    else:
        marker["decision"] = decision
    _record_gate(
        trace,
        request,
        phase="resolution",
        resolution="choice",
        resolved_via=resolution.resolved_via,
        decision=decision,
    )


def scan_batch_escalations(shared: dict[str, Any], node_id: str) -> None:
    """Fail loudly on an UNDECIDED escalation marker in a batch item's result.

    A direct batch host has no per-item gate seam, so a marker here would
    otherwise be silently ignored. Decided markers (answered inside a sequential
    sub-workflow item) are skipped. Failed items are already error-reported by
    the batch machinery — ``results`` holds successes only.
    """
    output = shared.get(node_id)
    if not isinstance(output, dict):
        return
    results = output.get("results")
    if not isinstance(results, list):
        return
    total = output.get("count", len(results))
    for i, item_ns in enumerate(results):
        if not isinstance(item_ns, dict):
            continue
        result = item_ns.get("result")
        if not isinstance(result, dict):
            continue
        marker = result.get("escalation")
        if not marker or (isinstance(marker, dict) and "decision" in marker):
            continue
        question = marker.get("question") if isinstance(marker, dict) else marker
        preview = str(question)[:_QUESTION_PREVIEW_CHARS] if question else "<no question>"
        raise PflowError(
            f"Step '{node_id}' raised an escalation from batch item {i + 1} of {total}: "
            f'"{preview}" — escalations inside a batch are not supported; restructure so '
            f"the escalating step runs outside the batch."
        )


def _record_gate(
    trace: Any,
    request: GateRequest,
    *,
    phase: str,
    resolution: Optional[str] = None,
    resolved_via: Optional[str] = None,
    decision: Optional[dict[str, Any]] = None,
) -> None:
    if trace is None:
        return
    trace.record_gate(
        request.node_id,
        phase=phase,
        gate_kind=request.kind,
        request=request if phase == "pause" else None,
        resolution=resolution,
        resolved_via=resolved_via,
        decision=decision,
    )


def _warn_escalation(shared: dict[str, Any], node_id: str, message: str) -> None:
    logger.warning(message)
    shared.setdefault("__warnings__", {})[node_id] = Diagnostic(
        severity=Severity.WARNING,
        message=message,
        title="Escalation marker dropped",
        node_id=node_id,
        source="runtime",
        context={"category": "gate", "type": "escalation_marker_dropped"},
    )


__all__ = [
    "GATE_PROMPT_ALLOWED_KEY",
    "GATE_RESOLVER_KEY",
    "detect_escalation",
    "resolve_gate",
    "run_approval_gate",
    "run_escalation_gate",
    "scan_batch_escalations",
]
