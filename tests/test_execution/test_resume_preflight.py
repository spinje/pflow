"""Task 176 — ``execution/resume_preflight.py``, the click-free resume pre-flight.

Thin by design: the moved refusal gates keep their depth in the CLI battery
(``test_resume_cli.py`` — stale-hash, side-effect quartet, between-nodes suite — now importing
from this module) and the endpoint pins live in ``test_ui_interaction_server.py``. Here: the
side-effect VERDICT matrix (the one piece that changed shape — constructed, not raised) and a
seam smoke that ``preflight_resume`` runs the gates in the CLI's order.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pflow.core.exceptions import ResumeSideEffectConfirmationError, ResumeStaleWorkflowError
from pflow.execution.result import ResolvedWorkflow
from pflow.execution.resume_preflight import (
    _side_effect_refusal,
    preflight_resume,
)
from pflow.runtime.resume_source import ResumeSource


def _source(
    *,
    entry_node_id: str | None = "step2",
    last_completed_node_id: str | None = None,
    paused_node_id: str | None = None,
    content_hash: str | None = None,
) -> ResumeSource:
    return ResumeSource(
        path=Path("trace.json"),
        workflow_path="wf.pflow.md",
        execution_id="exec-1",
        entry_node_id=entry_node_id,
        last_completed_node_id=last_completed_node_id,
        events=[],
        inputs=None,
        content_hash=content_hash,
        paused_node_id=paused_node_id,
    )


def _resolved(nodes: list[dict[str, Any]], edges: list[dict[str, Any]] | None = None) -> ResolvedWorkflow:
    return ResolvedWorkflow(ir={"nodes": nodes, "edges": edges or []}, source="file")


_SHELL_ENTRY = _resolved([{"id": "step2", "type": "shell"}])


class TestSideEffectVerdict:
    """The verdict matrix — None means "spawns/continues dialog-free"; a constructed refusal means
    a prompting caller confirms and every other caller raises it."""

    def test_paused_source_is_none(self) -> None:
        # The entry never ran in the source run — the answer flag is itself the consent.
        source = _source(entry_node_id="step2", paused_node_id="step2")
        assert _side_effect_refusal(_SHELL_ENTRY, source, force=False) is None

    def test_force_is_none(self) -> None:
        assert _side_effect_refusal(_SHELL_ENTRY, _source(), force=True) is None

    def test_idempotent_llm_entry_is_none(self) -> None:
        resolved = _resolved([{"id": "step2", "type": "llm"}])
        assert _side_effect_refusal(resolved, _source(), force=False) is None

    def test_side_effecting_entry_carries_the_refusal_with_registry_type(self) -> None:
        refusal = _side_effect_refusal(_SHELL_ENTRY, _source(), force=False)
        assert isinstance(refusal, ResumeSideEffectConfirmationError)
        assert refusal.node_id == "step2"
        assert refusal.node_type == "shell"  # IR registry vocabulary, never a trace class name
        assert refusal.execution_id == "exec-1"

    def test_entry_removed_from_workflow_is_none(self) -> None:
        # K removed/renamed (hash gate bypassed) — the engine refuses with a K-removed error
        # before any node runs, so no side effect fires; nothing to confirm.
        resolved = _resolved([{"id": "other", "type": "shell"}])
        assert _side_effect_refusal(resolved, _source(), force=False) is None


class TestPreflightOrderSmoke:
    """Seam smokes over `preflight_resume` with the load step patched — the gates' own depth is
    in the moved CLI tests; this pins the order/delegation only."""

    def test_stale_hash_refuses_and_force_skips_gate_and_verdict(self, monkeypatch) -> None:
        from pflow.core.workflow_id import workflow_content_hash
        from pflow.execution import resume_preflight

        resolved = _SHELL_ENTRY
        stale = _source(content_hash="not-the-current-hash")
        monkeypatch.setattr(resume_preflight, "_load_source_and_workflow", lambda t, gate_answer: (stale, resolved))
        with pytest.raises(ResumeStaleWorkflowError):
            preflight_resume("whatever")
        forced = preflight_resume("whatever", force=True)
        assert forced.side_effect_refusal is None  # force also bypasses the verdict
        # An unchanged workflow passes the gate without force.
        fresh = _source(content_hash=workflow_content_hash(resolved.ir))
        monkeypatch.setattr(resume_preflight, "_load_source_and_workflow", lambda t, gate_answer: (fresh, resolved))
        assert preflight_resume("whatever").source is fresh

    def test_between_nodes_entry_is_resolved_for_a_paused_escalation_shape(self, monkeypatch) -> None:
        """entry_node_id=None (the loader's paused-escalation / killed-between-nodes shape) →
        the single default successor is pinned as the entry, and the verdict is computed on it."""
        from pflow.execution import resume_preflight

        resolved = _resolved(
            [{"id": "esc", "type": "llm"}, {"id": "after", "type": "shell"}],
            edges=[{"from": "esc", "to": "after"}],
        )
        source = _source(entry_node_id=None, last_completed_node_id="esc", paused_node_id="esc")
        monkeypatch.setattr(resume_preflight, "_load_source_and_workflow", lambda t, gate_answer: (source, resolved))
        pf = preflight_resume("whatever", force=True)
        assert pf.source.entry_node_id == "after"  # the escalation answer continues at the successor
