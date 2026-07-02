"""Task 125 — the ``gate`` trace event: disk-only sideband, reader tolerance, trailer channel.

The load-bearing invariants (each shipped as a review-confirmed fix):
- gate lines are DISK-ONLY (never in ``collector.events``) so they can't become a
  node's "final event" and break ``--only`` snapshot seeding;
- the reconstruct reader treats ``gate`` as known-but-ignored, so a gated run's
  trace stays fully readable (``pflow report`` / ``--only`` / analyze-cache);
- the pause event round-trips the exact ``GateRequest`` payload (Task 171's
  serialization test);
- a gate-stopped run's trailer is honest via the collector's ``gate_outcome``
  channel (without it, a denied run's own trace would read "success").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pflow.core.exceptions import GateDenied
from pflow.core.gate import GateResolution
from pflow.core.trace_io import load_trace_file
from pflow.registry import Registry
from pflow.runtime import compile_workflow
from pflow.runtime.engine import WorkflowEngine
from pflow.runtime.workflow_trace import WorkflowTraceCollector, load_full_run_events


def _gated_ir() -> dict[str, Any]:
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": "echo hello"}},
            {"id": "b", "type": "shell", "params": {"command": "echo from-${a.stdout}"}, "approval": "required"},
        ],
        "edges": [{"from": "a", "to": "b"}],
    }


def _approver(request, *, allow_prompt):
    return GateResolution(approved=True, resolved_via="prompt")


def _denier(request, *, allow_prompt):
    return GateResolution(approved=False, resolved_via="prompt")


def _run_streamed(ir: dict[str, Any], resolver, tmp_path: Path) -> tuple[WorkflowTraceCollector, dict[str, Any]]:
    collector = WorkflowTraceCollector(
        "gated", workflow_path=str(tmp_path / "gated.pflow.md"), is_run_scoped=True, stream_to_disk=True
    )
    compiled = compile_workflow(ir, Registry())
    shared: dict[str, Any] = {"__gate_resolver__": resolver}
    engine = WorkflowEngine(trace_collector=collector)
    try:
        engine.run(compiled, shared)
    finally:
        collector.finalize()
    return collector, shared


def _read_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.trace_files
class TestGateTraceEvents:
    def test_approved_run_emits_pause_and_resolution_and_stays_readable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        collector, _ = _run_streamed(_gated_ir(), _approver, tmp_path)
        lines = _read_lines(collector._stream_path)

        gate_lines = [ln for ln in lines if ln["kind"] == "gate"]
        assert [ln["phase"] for ln in gate_lines] == ["pause", "resolution"]
        pause, resolution = gate_lines
        # The pause line IS the serialization test for the payload (Task 171).
        assert pause["request"]["node_id"] == "b"
        assert pause["request"]["kind"] == "action_approval"
        assert pause["request"]["preview"] == {"command": "echo from-hello"}
        assert resolution["resolution"] == "approved"
        assert resolution["resolved_via"] == "prompt"

        # DISK-ONLY: gate lines never enter the in-memory event list.
        assert all("gate" not in (e.get("kind") or "") for e in collector.events)
        assert len(collector.events) == 2  # the two node completions only

        # The reconstruct reader ignores the kind — the trace is NOT corrupt.
        trace = load_trace_file(collector._stream_path)
        assert trace["final_status"] == "success"
        assert {e["node_id"] for e in trace["nodes"]} == {"a", "b"}

    def test_gated_approved_run_is_a_valid_only_snapshot_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        collector, _ = _run_streamed(_gated_ir(), _approver, tmp_path)
        collector.save_to_file()
        events, status = load_full_run_events(collector.workflow_path)
        assert status == "success"
        assert [e["node_id"] for e in events] == ["a", "b"]

    def test_denied_run_trailer_says_denied_and_node_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        collector = WorkflowTraceCollector(
            "gated", workflow_path=str(tmp_path / "gated.pflow.md"), is_run_scoped=True, stream_to_disk=True
        )
        compiled = compile_workflow(_gated_ir(), Registry())
        shared: dict[str, Any] = {"__gate_resolver__": _denier}
        with pytest.raises(GateDenied):
            WorkflowEngine(trace_collector=collector).run(compiled, shared)
        collector.finalize()

        lines = _read_lines(collector._stream_path)
        resolution = next(ln for ln in lines if ln["kind"] == "gate" and ln["phase"] == "resolution")
        assert resolution["resolution"] == "denied"
        # The denied node has NO node.start marker and NO completion event.
        assert not any(ln.get("node_id") == "b" for ln in lines if ln["kind"] in ("node.start", "event"))

        trace = load_trace_file(collector._stream_path)
        assert trace["final_status"] == "denied"
        # A denied trace is deliberately NOT a --only snapshot source (loader allowlist).
        collector.save_to_file()
        assert load_full_run_events(collector.workflow_path) is None

    def test_noninteractive_gate_trailer_says_failed_not_success(self, tmp_path, monkeypatch):
        from pflow.core.exceptions import GateNotInteractiveError

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        collector = WorkflowTraceCollector(
            "gated", workflow_path=str(tmp_path / "gated.pflow.md"), is_run_scoped=True, stream_to_disk=True
        )
        compiled = compile_workflow(_gated_ir(), Registry())
        with pytest.raises(GateNotInteractiveError):
            WorkflowEngine(trace_collector=collector).run(compiled, {})
        collector.finalize()
        trace = load_trace_file(collector._stream_path)
        # Node "a" succeeded and no node failed — without the gate_outcome channel
        # this trailer would read "success" for a run that died at a gate.
        assert trace["final_status"] == "failed"
        resolution = next(
            ln for ln in _read_lines(collector._stream_path) if ln["kind"] == "gate" and ln["phase"] == "resolution"
        )
        assert resolution["resolution"] == "non_interactive"

    def test_nested_child_gate_events_land_in_run_stream(self, tmp_path, monkeypatch):
        """A gate inside a sub-workflow (the harness's primary shape) with a REAL
        run-scoped collector: NEW-path children share the run collector, so the
        child gate's pause/resolution lines must appear in the streamed trace —
        and the trace must stay fully readable."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        child = tmp_path / "child.pflow.md"
        child.write_text(
            "# Child\n\nChild with a gated step.\n\n## Steps\n\n### gated-step\n\n"
            "Do the child action.\n\n- type: shell\n- command: echo child-action\n- approval: required\n"
        )
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "sub", "type": "workflow", "params": {"workflow": str(child)}}],
            "edges": [],
        }
        collector, _ = _run_streamed(ir, _approver, tmp_path)
        gate_lines = [ln for ln in _read_lines(collector._stream_path) if ln["kind"] == "gate"]
        assert [(ln["phase"], ln["node_id"]) for ln in gate_lines] == [
            ("pause", "gated-step"),
            ("resolution", "gated-step"),
        ]
        trace = load_trace_file(collector._stream_path)
        assert trace["final_status"] == "success"

    def test_parallel_batch_child_gate_with_live_collector_never_crashes(self, tmp_path, monkeypatch):
        """Worker-thread safety with a REAL streaming collector: batch-item children
        get buffer collectors (owner=None), so a worker-thread record_gate must be a
        silent no-op — NOT an owner-thread assertion crash. Pins the production
        combination (CLI streaming + parallel batch + pre-approved child gate) that
        the traceless engine tests cannot see."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        child = tmp_path / "child.pflow.md"
        child.write_text(
            "# Child\n\nChild with a gated step.\n\n## Steps\n\n### gated-step\n\n"
            "Do the child action.\n\n- type: shell\n- command: echo child-action\n- approval: required\n"
        )
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "fan",
                    "type": "workflow",
                    "params": {"workflow": str(child)},
                    "batch": {"items": "${items}", "as": "item", "parallel": True},
                }
            ],
            "edges": [],
        }

        def flag_approver(request, *, allow_prompt):
            if request.node_id == "gated-step":
                return GateResolution(approved=True, resolved_via="flag")
            raise AssertionError(f"unexpected gate: {request.node_id}")

        collector = WorkflowTraceCollector(
            "batched", workflow_path=str(tmp_path / "batched.pflow.md"), is_run_scoped=True, stream_to_disk=True
        )
        compiled = compile_workflow(ir, Registry())
        shared: dict[str, Any] = {"items": [1, 2, 3], "__gate_resolver__": flag_approver}
        WorkflowEngine(trace_collector=collector).run(compiled, shared)
        collector.finalize()
        assert shared["fan"]["success_count"] == 3
        trace = load_trace_file(collector._stream_path)
        assert trace["final_status"] == "success"

    def test_escalation_gate_lines_carry_decision(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "agent",
                    "type": "code",
                    "params": {"code": "result: dict = {'escalation': {'question': 'q?'}}"},
                }
            ],
            "edges": [],
        }

        def chooser(request, *, allow_prompt):
            return GateResolution(approved=True, resolved_via="prompt", chosen="a", notes="n")

        collector, shared = _run_streamed(ir, chooser, tmp_path)
        lines = _read_lines(collector._stream_path)
        gate_lines = [ln for ln in lines if ln["kind"] == "gate"]
        assert [ln["phase"] for ln in gate_lines] == ["pause", "resolution"]
        assert gate_lines[0]["gate_kind"] == "decision_escalation"
        assert gate_lines[1]["resolution"] == "choice"
        assert gate_lines[1]["decision"] == {"chosen": "a", "notes": "n"}
        # Ordering: the node's own completion event precedes the gate pause —
        # its honest success record stands untouched.
        kinds_for_agent = [ln["kind"] for ln in lines if ln.get("node_id") == "agent"]
        assert kinds_for_agent.index("event") < kinds_for_agent.index("gate")
        trace = load_trace_file(collector._stream_path)
        assert trace["final_status"] == "success"
