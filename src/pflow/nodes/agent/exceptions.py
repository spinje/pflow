"""Agent-node parameter exceptions."""

from __future__ import annotations

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.exceptions import PflowError


class AgentValidationError(PflowError):
    """A user's ``agent`` node parameter is malformed (wrong type or bad value).

    Raised by the shared param validators (``schema_validation``), ``AgentNode.prep``,
    and both backends when a parameter fails its shape/value check. These fire in
    ``prep()`` — before any model call — so on a normal run they fail fast (``prep``
    runs outside the ``Node`` retry loop and propagates immediately).

    Inherits ``PflowError.retriable = True`` deliberately — do NOT set
    ``retriable = False``. In a batch this class flows through
    ``batch_executor``'s per-item retry loop; a non-retriable exception there is
    re-raised and aborts the ENTIRE batch, which would break ``error_handling:
    continue`` (a single item's bad ``${item.sandbox}``/``${item.prompt}`` must be
    recorded as a per-item error while the other items complete). Retriable keeps
    the pre-#592 ``ValueError``/``TypeError`` behavior exactly: the bad-param item
    is recorded as a per-item error and continue-mode batches survive. The only
    cost — a few no-op prep retries of a doomed item — is the pre-existing status
    quo, not something this focused issue changes.

    Renders as a clean validation diagnostic (no ``Type:`` line). Before issue #592
    these sites raised vanilla ``ValueError``/``TypeError``: a ``ValueError`` landed
    in the diagnostic converter's validation branch (clean) while a ``TypeError``
    fell through to the generic branch and surfaced a ``Type: TypeError`` line —
    an inconsistency this class removes by framing itself.
    """

    def to_diagnostics(self) -> list[Diagnostic]:
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="Validation Error",
                source="validation",
                # ``see_also`` mirrors the static validator's diagnostic
                # (``_agent_param_error`` emits ``["agent"]``) so a runtime-only
                # param error (cwd/prompt/timeout/resume/output_schema/use_api_key/
                # codex config — none pre-checked statically) still points the
                # user at ``pflow guide agent``.
                see_also=["agent"],
                context={"category": "validation"},
            )
        ]
