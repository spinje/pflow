"""Human-decision gate payloads (Task 125).

``GateRequest`` is the seam (ADR-0009): the SAME payload feeds the TTY prompt, the
``gate`` trace event, the non-interactive error diagnostic, and (Task 171) durable
persistence. It is JSON-native by construction — building one coerces every leaf
through a JSON round-trip so no consumer ever needs a ``default=str`` rescue.

Resolution is a plain callable, not a strategy object. The contract:

    resolver(request: GateRequest, *, allow_prompt: bool) -> GateResolution

The resolver lives in the shared store under ``__gate_resolver__`` (installed by the
CLI / MCP layer, propagated to sub-workflow engines like ``__progress_callback__``).
``allow_prompt=False`` means the call site cannot host an interactive prompt (a
parallel-batch worker) — the resolver may still auto-approve from its flag set, but
must raise ``GateNotInteractiveError(..., parallel_batch=True)`` instead of prompting.
"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

from pflow.core.security_utils import is_sensitive_parameter

GATE_KIND_APPROVAL: Literal["action_approval"] = "action_approval"
GATE_KIND_ESCALATION: Literal["decision_escalation"] = "decision_escalation"


def json_safe(value: Any) -> Any:
    """Coerce ``value`` to JSON-native types (non-native leaves become ``str()``)."""
    return json.loads(json.dumps(value, default=str))


@dataclass(frozen=True)
class GateRequest:
    """One human decision: what is being asked, with everything needed to decide.

    Self-contained by contract — a remote human (web UI, Task 176) must be able to
    decide from this payload alone.
    """

    node_id: str
    node_type: str
    kind: Literal["action_approval", "decision_escalation"]
    # Approval: the node's resolved params — what is ABOUT to happen.
    preview: dict[str, Any] = field(default_factory=dict)
    # Escalation: the decision the agent raised. All optional — render leniently.
    question: Optional[str] = None
    options: tuple[dict[str, Any], ...] = ()
    recommendation: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["options"] = list(self.options)
        return data


@dataclass(frozen=True)
class GateResolution:
    """The human's (or flag's) answer to a GateRequest."""

    approved: bool
    resolved_via: Literal["prompt", "flag"]
    # Escalation only: the chosen option label (or free text), plus any extra notes.
    chosen: Optional[str] = None
    notes: Optional[str] = None


def build_approval_request(node_id: str, node_type: str, params: Any) -> GateRequest:
    """Approval payload from the node's (resolved) params.

    ``_``-prefixed keys are parser/engine bookkeeping (``_source_line``, ...), not
    part of the action — filtered here like every other display surface
    (node_output_formatter / trace_report convention).
    """
    if not isinstance(params, dict):
        return GateRequest(node_id=node_id, node_type=node_type, kind=GATE_KIND_APPROVAL)
    preview = {key: json_safe(value) for key, value in params.items() if not key.startswith("_")}
    return GateRequest(node_id=node_id, node_type=node_type, kind=GATE_KIND_APPROVAL, preview=preview)


def build_escalation_request(node_id: str, node_type: str, marker: Any) -> GateRequest:
    """Escalation payload from a node's ``result.escalation`` marker.

    Lenient by design: a string marker becomes the question; dict fields that are
    missing or oddly shaped render as absent — never crash at the pause point.
    """
    if isinstance(marker, str):
        return GateRequest(node_id=node_id, node_type=node_type, kind=GATE_KIND_ESCALATION, question=marker)
    question = marker.get("question")
    raw_options = marker.get("options")
    options = tuple(json_safe(o) for o in raw_options if isinstance(o, dict)) if isinstance(raw_options, list) else ()
    recommendation = marker.get("recommendation")
    return GateRequest(
        node_id=node_id,
        node_type=node_type,
        kind=GATE_KIND_ESCALATION,
        question=str(question) if question is not None else None,
        options=options,
        recommendation=str(recommendation) if recommendation is not None else None,
    )


def masked_preview(preview: dict[str, Any]) -> dict[str, Any]:
    """Preview with secret-NAMED values redacted (recursively) — never truncated.

    THE masking policy for every gate render surface (TTY prompt, error
    diagnostics); the trace's gate event stays unmasked, consistent with the
    trace's ``template_resolutions``. Masking only — length truncation belongs
    to each renderer (the TTY prompt's 200-char step): routing values through
    ``sanitize_parameters`` here cut long non-secret nested values (an http
    ``json:`` body, a sub-workflow ``inputs:`` field) to ~20 chars, blinding
    the approver to what they were approving (PR #554 review warning).
    """

    def mask(key: Optional[str], value: Any) -> Any:
        if key is not None and is_sensitive_parameter(key):
            return "<REDACTED>"
        if isinstance(value, dict):
            return {k: mask(str(k), v) for k, v in value.items()}
        if isinstance(value, list):
            return [mask(None, item) for item in value]
        return value

    return {key: mask(key, value) for key, value in preview.items()}
