"""TTY gate resolver — the human side of Task 125 approval gates.

The engine owns WHEN a gate fires (``runtime/engine/gate.py``); this module owns
HOW a human answers. ``build_gate_resolver`` returns the plain callable the
engine invokes via ``__gate_resolver__`` (contract in ``core/gate.py``). click
and OutputController live HERE — never in runtime/.

One builder, every configuration:
- CLI interactive:    ``build_gate_resolver(flags, output_controller)`` — prompts on
  stderr, reads stdin (design anchor: ``terraform apply``).
- MCP / non-TTY:      ``build_gate_resolver(flags, None)`` — honors ``--auto-approve``
  pre-approvals, otherwise raises the payload-carrying ``GateNotInteractiveError``.
- Parallel-batch worker: the SAME resolver called with ``allow_prompt=False``
  (via ``__gate_prompt_allowed__``) — auto-approve still works, prompting never does.

Ctrl-C at a prompt: click raises ``Abort`` (an ``Exception`` subclass the engine
would archive as a node failure) — converted to ``KeyboardInterrupt`` so it rides
the existing clean interrupt path (exit 130, incomplete-but-readable trace).
"""

from collections.abc import Callable
from typing import Any

import click

from pflow.core.exceptions import GateNotInteractiveError
from pflow.core.gate import GATE_KIND_APPROVAL, GateRequest, GateResolution, masked_preview
from pflow.core.output_controller import OutputController

GateResolver = Callable[..., GateResolution]

# Display-only truncation for preview values; the trace event carries the full
# payload (interning handles size — trace_io.intern_event_leaves).
_PREVIEW_VALUE_CHARS = 200


def can_prompt(output_controller: OutputController | None) -> bool:
    """True when a gate prompt can render (stderr) and be answered (stdin).

    Deliberately NOT ``is_interactive()`` — that requires stdout to be a TTY,
    but the prompt never touches stdout: ``pflow wf | jq`` at a real terminal
    must still gate (Decision 14).
    """
    if output_controller is None or output_controller.print_flag:
        return False
    return output_controller.stdin_tty and output_controller.stderr_tty


def build_gate_resolver(
    auto_approve: frozenset[str],
    output_controller: OutputController | None,
) -> GateResolver:
    """Build the ``__gate_resolver__`` callable for this run.

    ``auto_approve`` pre-approves APPROVAL gates by node id (flat namespace
    across the workflow tree — a child gate with a flagged id is approved).
    Escalations never auto-resolve: you cannot pre-answer an unknown question.
    """

    def resolver(request: GateRequest, *, allow_prompt: bool = True) -> GateResolution:
        if request.kind == GATE_KIND_APPROVAL and request.node_id in auto_approve:
            if allow_prompt:
                _echo_auto_approved(request, output_controller)
            return GateResolution(approved=True, resolved_via="flag")
        if allow_prompt and output_controller is not None and can_prompt(output_controller):
            return _prompt(request, output_controller)
        raise GateNotInteractiveError(request, parallel_batch=not allow_prompt)

    return resolver


def _echo_auto_approved(request: GateRequest, output_controller: OutputController | None) -> None:
    """One stderr line so a pre-approved gate is visible, never silent.

    Code-review fix: the CALLER gates this on ``allow_prompt`` — ``allow_prompt=
    False`` means this resolver call is running on a parallel-batch WORKER
    thread (``__gate_prompt_allowed__``), where ``output_controller`` is the
    real, shared one (not buffered, unlike the progress callback). Echoing
    there would call ``prepare_for_prompt()``/``click.echo(err=True)``
    concurrently with the main thread's progress drain — exactly the race the
    per-worker progress buffer exists to prevent (see `engine/CLAUDE.md`
    "Per-worker progress buffer"). Worker output is buffered anyway and the
    flag was already an explicit human pre-approval, so silence there is an
    acceptable trade for correctness.
    """
    if output_controller is None or output_controller.print_flag:
        return
    output_controller.prepare_for_prompt()
    click.echo(
        click.style(f"✓ Gate '{request.node_id}' pre-approved via --auto-approve={request.node_id}", fg="green"),
        err=True,
    )


def _prompt(request: GateRequest, output_controller: OutputController) -> GateResolution:
    output_controller.prepare_for_prompt()
    try:
        if request.kind == GATE_KIND_APPROVAL:
            return _prompt_approval(request)
        return _prompt_escalation(request)
    except click.exceptions.Abort:
        # click's Ctrl-C wrapper is an Exception subclass — re-raise as the real
        # interrupt so the engine's generic arm never archives it as a node failure.
        raise KeyboardInterrupt() from None


def _prompt_approval(request: GateRequest) -> GateResolution:
    click.echo(f"\n⏸  Approval required: {request.node_id} ({request.node_type})\n", err=True)
    for line in _format_preview(request.preview):
        click.echo(f"   {line}", err=True)
    if request.preview:
        click.echo("", err=True)
    approved = click.confirm("   Run this step?", default=False, err=True)
    return GateResolution(approved=approved, resolved_via="prompt")


def _prompt_escalation(request: GateRequest) -> GateResolution:
    click.echo(f"\n⏸  Escalation from {request.node_id}:", err=True)
    if request.question:
        click.echo(f"   {request.question}", err=True)
    click.echo("", err=True)
    labels = _echo_options(request)
    if labels:
        answer = click.prompt(f"   Choose 1-{len(labels)}, or type an answer", err=True)
    else:
        answer = click.prompt("   Type an answer", err=True)
    answer = str(answer).strip()
    if answer.isdigit() and 1 <= int(answer) <= len(labels):
        return GateResolution(approved=True, resolved_via="prompt", chosen=labels[int(answer) - 1])
    return GateResolution(approved=True, resolved_via="prompt", chosen=answer)


def _echo_options(request: GateRequest) -> list[str]:
    """Render numbered options; returns the option labels in display order."""
    labels: list[str] = []
    for i, option in enumerate(request.options, start=1):
        label = str(option.get("label") or f"option {i}")
        labels.append(label)
        rec = " (rec)" if request.recommendation and request.recommendation == label else ""
        detail = " — ".join(str(option[key]) for key in ("description", "tradeoffs") if option.get(key))
        suffix = f" — {detail}" if detail else ""
        click.echo(f"   {i}. {label}{rec}{suffix}", err=True)
    if request.recommendation and request.recommendation not in labels:
        click.echo(f"   Recommendation: {request.recommendation}", err=True)
    if labels:
        click.echo("", err=True)
    return labels


def _format_preview(preview: dict[str, Any]) -> list[str]:
    """Aligned ``key: value`` lines, secret-masked and display-truncated.

    Values are flattened to one line each (newlines escaped) so the block stays
    scannable; the full unmasked payload lives in the gate trace event. Masking
    is the shared ``masked_preview`` (recursive, mask-only); truncation happens
    ONLY here, at the 200-char display budget — never inside the masking step,
    so a long non-secret nested value stays reviewable.
    """
    if not preview:
        return ["(no parameters)"]
    width = max(len(key) for key in preview)
    lines = []
    for key, value in masked_preview(preview).items():
        text = value if isinstance(value, str) else _compact_json(value)
        text = text.replace("\n", "\\n")
        if len(text) > _PREVIEW_VALUE_CHARS:
            text = f"{text[:_PREVIEW_VALUE_CHARS]}… ({len(text)} chars)"
        lines.append(f"{key}:{' ' * (width - len(key) + 2)}{text}")
    return lines


def _compact_json(value: Any) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


__all__ = ["GateResolver", "build_gate_resolver", "can_prompt"]
