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
            {
                "id": "b",
                "type": "shell",
                "params": {"command": 'echo from-"$A_STDOUT"', "env": {"A_STDOUT": "${a.stdout}"}},
                "approval": "required",
            },
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
    engine = WorkflowEngine(trace_collector=collector, workflow_path="gated.pflow.md")
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
        assert pause["request"]["preview"] == {"command": 'echo from-"$A_STDOUT"', "env": {"A_STDOUT": "hello"}}
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
            WorkflowEngine(trace_collector=collector, workflow_path="gated.pflow.md").run(compiled, shared)
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

    def test_noninteractive_gate_trailer_says_paused_not_success(self, tmp_path, monkeypatch):
        """Task 171: a top-level non-interactive gate pauses durably — the trailer
        reads ``paused`` (pre-171: ``failed``) and carries the pause record
        (``paused_node_id`` + the full ``gate_request``, round-tripped through
        the trailer). Node "a" succeeded and no node failed — without the
        gate_outcome channel this trailer would read "success"."""
        from pflow.core.exceptions import GateNotInteractiveError

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        collector = WorkflowTraceCollector(
            "gated", workflow_path=str(tmp_path / "gated.pflow.md"), is_run_scoped=True, stream_to_disk=True
        )
        compiled = compile_workflow(_gated_ir(), Registry())
        with pytest.raises(GateNotInteractiveError):
            WorkflowEngine(trace_collector=collector, workflow_path="gated.pflow.md").run(compiled, {})
        collector.finalize()
        trace = load_trace_file(collector._stream_path)
        assert trace["final_status"] == "paused"
        assert trace["paused_node_id"] == "b"
        assert trace["gate_request"]["kind"] == "action_approval"
        assert trace["gate_request"]["preview"] == {"command": 'echo from-"$A_STDOUT"', "env": {"A_STDOUT": "hello"}}
        resolution = next(
            ln for ln in _read_lines(collector._stream_path) if ln["kind"] == "gate" and ln["phase"] == "resolution"
        )
        assert resolution["resolution"] == "non_interactive"
        # A paused run's upstream is PARTIAL (it stopped at the gate) — like a
        # denied trace, it must never seed a --only snapshot. Pins the
        # load_full_run_events ALLOWLIST (success/degraded): a "reject failed"
        # denylist rewrite would silently accept paused partial upstream.
        collector.save_to_file()
        assert load_full_run_events(collector.workflow_path) is None

    def test_resolver_crash_emits_error_resolution_and_trailer_says_failed(self, tmp_path, monkeypatch):
        """A resolver bug still leaves an honest trace: a resolution line
        (``"error"``) is emitted before the exception escapes, and the trailer
        reads ``failed`` via the gate_outcome channel — never ``success``."""
        from pflow.core.exceptions import GateResolverError

        def crasher(request, *, allow_prompt):
            raise RuntimeError("resolver bug")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        collector = WorkflowTraceCollector(
            "gated", workflow_path=str(tmp_path / "gated.pflow.md"), is_run_scoped=True, stream_to_disk=True
        )
        compiled = compile_workflow(_gated_ir(), Registry())
        with pytest.raises(GateResolverError):
            WorkflowEngine(trace_collector=collector, workflow_path="gated.pflow.md").run(
                compiled, {"__gate_resolver__": crasher}
            )
        collector.finalize()
        trace = load_trace_file(collector._stream_path)
        assert trace["final_status"] == "failed"
        resolution = next(
            ln for ln in _read_lines(collector._stream_path) if ln["kind"] == "gate" and ln["phase"] == "resolution"
        )
        assert resolution["resolution"] == "error"

    def _nested_gate_after_sibling_ir(self, tmp_path: Path, name: str) -> dict[str, Any]:
        """A sub-workflow with an EARLIER sibling step (records an event under the
        host) followed by a LATER gated step — the shape that orphans a trace event
        if the host's own completion event is never recorded on a gate stop."""
        child = tmp_path / f"{name}.pflow.md"
        child.write_text(
            "# Child\n\nSibling then a gated step.\n\n## Steps\n\n"
            "### sibling\n\nRuns first, recording an event under the host.\n\n"
            "- type: shell\n- command: echo sibling\n\n"
            "### gated-step\n\nThe gate stops here.\n\n"
            "- type: shell\n- command: echo gated\n- approval: required\n",
            encoding="utf-8",
        )
        return {
            "ir_version": "0.1.0",
            "nodes": [{"id": "sub", "type": "workflow", "params": {"workflow": str(child)}}],
            "edges": [],
        }

    def test_denied_nested_gate_after_sibling_event_does_not_orphan_trace(self, tmp_path, monkeypatch):
        """Code-review fix: a sub-workflow HOST's own trace event must be recorded
        even when a gate stops mid-way through it. Before the fix, ``finalize()``
        itself raised in memory (an orphaned sibling event — parent_id pointing at
        the host's reserved-but-never-written seq), silently swallowed by the
        runner's ``contextlib.suppress``, leaving NO ``run.complete`` trailer — the
        trace read back as ``final_status="incomplete"`` instead of "denied", and
        any direct caller of ``tree()``/``collect_llm_calls()`` would crash outright.
        """
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        collector = WorkflowTraceCollector(
            "nested-denied",
            workflow_path=str(tmp_path / "nested-denied.pflow.md"),
            is_run_scoped=True,
            stream_to_disk=True,
        )
        compiled = compile_workflow(self._nested_gate_after_sibling_ir(tmp_path, "child-denied"), Registry())
        with pytest.raises(GateDenied):
            WorkflowEngine(trace_collector=collector, workflow_path="gated.pflow.md").run(
                compiled, {"__gate_resolver__": _denier}
            )
        collector.finalize()  # must not raise

        lines = _read_lines(collector._stream_path)
        assert any(ln["kind"] == "run.complete" for ln in lines), "finalize() must reach the trailer write"
        trace = load_trace_file(collector._stream_path)
        assert trace["final_status"] == "denied"
        # tree() rebuilt successfully (load_trace_file calls it) — the sibling's
        # event is not an orphan; the whole point of the fix.
        assert collector.tree()

    def test_noninteractive_nested_gate_after_sibling_event_does_not_orphan_trace(self, tmp_path, monkeypatch):
        """Same orphan risk via the non-interactive-fail variant of the same
        gate-exception exemption arm."""
        from pflow.core.exceptions import GateNotInteractiveError

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        collector = WorkflowTraceCollector(
            "nested-noninteractive",
            workflow_path=str(tmp_path / "nested-noninteractive.pflow.md"),
            is_run_scoped=True,
            stream_to_disk=True,
        )
        compiled = compile_workflow(self._nested_gate_after_sibling_ir(tmp_path, "child-noninteractive"), Registry())
        with pytest.raises(GateNotInteractiveError):
            WorkflowEngine(trace_collector=collector, workflow_path="gated.pflow.md").run(compiled, {})
        collector.finalize()  # must not raise

        lines = _read_lines(collector._stream_path)
        assert any(ln["kind"] == "run.complete" for ln in lines)
        trace = load_trace_file(collector._stream_path)
        assert trace["final_status"] == "failed"
        assert collector.tree()

    def test_nested_child_gate_events_land_in_run_stream(self, tmp_path, monkeypatch):
        """A gate inside a sub-workflow (the harness's primary shape) with a REAL
        run-scoped collector: NEW-path children share the run collector, so the
        child gate's pause/resolution lines must appear in the streamed trace —
        and the trace must stay fully readable."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        child = tmp_path / "child.pflow.md"
        child.write_text(
            "# Child\n\nChild with a gated step.\n\n## Steps\n\n### gated-step\n\n"
            "Do the child action.\n\n- type: shell\n- command: echo child-action\n- approval: required\n",
            encoding="utf-8",
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
            "Do the child action.\n\n- type: shell\n- command: echo child-action\n- approval: required\n",
            encoding="utf-8",
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
        WorkflowEngine(trace_collector=collector, workflow_path="gated.pflow.md").run(compiled, shared)
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

        collector, _shared = _run_streamed(ir, chooser, tmp_path)
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


class _ApproveFirst:
    """Approves the first ``approvals`` gates, then answers like a non-TTY run."""

    def __init__(self, approvals: int) -> None:
        self.remaining = approvals

    def __call__(self, request, *, allow_prompt):
        from pflow.core.exceptions import GateNotInteractiveError

        if self.remaining > 0:
            self.remaining -= 1
            return GateResolution(approved=True, resolved_via="flag")
        raise GateNotInteractiveError(request)


def _run_streamed_until_gate_stop(ir: dict[str, Any], shared: dict[str, Any], tmp_path: Path) -> WorkflowTraceCollector:
    """Run ``ir`` on a real streamed collector, expecting a non-interactive gate stop."""
    from pflow.core.exceptions import GateNotInteractiveError

    collector = WorkflowTraceCollector(
        "gated", workflow_path=str(tmp_path / "gated.pflow.md"), is_run_scoped=True, stream_to_disk=True
    )
    compiled = compile_workflow(ir, Registry())
    with pytest.raises(GateNotInteractiveError):
        WorkflowEngine(trace_collector=collector, workflow_path="gated.pflow.md").run(compiled, shared)
    collector.finalize()
    return collector


def _write_child(tmp_path: Path, name: str, output_block: str, code: str) -> Path:
    child = tmp_path / f"{name}.pflow.md"
    child.write_text(
        f"# Child\n\nOne code step whose output the host exposes.\n\n## Outputs\n\n{output_block}\n\n"
        "## Steps\n\n### emit\n\nEmit the output.\n\n- type: code\n\n"
        f"```python code\n{code}\n```\n",
        encoding="utf-8",
    )
    return child


@pytest.mark.trace_files
class TestHostFrameRecordedOnlyForChildGates:
    """#659 (Task 179 D1): the gate arm records a sub-workflow host's event only for a
    gate that came from its CHILD. A gate at the host's own level never reserved a frame
    this visit (7.5) or already consumed it (17.7) — recording there wrote a stale copy.
    The child-gate half is pinned by the two ``…does_not_orphan_trace`` tests above."""

    def test_looping_gated_host_keeps_first_iteration_event(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        child = _write_child(
            tmp_path,
            "loop-child",
            "### more\n\nAlways more.\n\n- type: boolean\n- source: ${emit.result.more}",
            'result: dict = {"more": True}',
        )
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "host",
                    "type": "workflow",
                    "params": {"workflow": str(child)},
                    "approval": "required",
                    "loop": {"while": "${host.more}", "max_iterations": 3},
                }
            ],
            "edges": [],
        }
        # Iteration 1 approved and ran; iteration 2's approval stops the run before exec.
        collector = _run_streamed_until_gate_stop(ir, {"__gate_resolver__": _ApproveFirst(1)}, tmp_path)

        assert [e["node_id"] for e in collector.events if e["node_id"] == "host"] == ["host"]
        lines = _read_lines(collector._stream_path)
        host_lines = [ln for ln in lines if ln["kind"] == "event" and ln["node_id"] == "host"]
        assert len(host_lines) == 1
        host = host_lines[0]
        assert host["iteration"] == 1
        # Iteration 1's real record survives: its child ran under it.
        child_lines = [ln for ln in lines if ln["kind"] == "event" and ln.get("parent_id") == host["id"]]
        assert [ln["node_id"] for ln in child_lines] == ["emit"]
        nodes = load_trace_file(collector._stream_path)["nodes"]
        assert [(n["node_id"], n.get("iteration")) for n in nodes] == [("host", 1)]
        assert [c["node_id"] for c in nodes[0]["sub_workflow_events"]] == ["emit"]

    def test_host_own_escalation_records_host_once(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        child = _write_child(
            tmp_path,
            "escalating-child",
            "### result\n\nAn undecided escalation.\n\n- type: object\n- source: ${emit.result.payload}",
            # Nested one level down so the CHILD step does not escalate itself — only the
            # host's exposed ``result`` carries the marker.
            "result: dict = {'payload': {'escalation': {'question': 'a or b?'}}}",
        )
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "host", "type": "workflow", "params": {"workflow": str(child)}}],
            "edges": [],
        }
        # No resolver: the host's own escalation (17.7, after step 16 recorded it) stops the run.
        collector = _run_streamed_until_gate_stop(ir, {}, tmp_path)

        assert [e["node_id"] for e in collector.events] == ["emit", "host"]
        nodes = load_trace_file(collector._stream_path)["nodes"]
        assert [n["node_id"] for n in nodes] == ["host"]
        assert nodes[0]["node_output"]["result"]["escalation"]["question"] == "a or b?"


@pytest.mark.trace_files
class TestGateIterationRecorded:
    """Task 179: a gate raised by a loop step records the iteration that raised it — on
    the ``GateRequest`` (every pause surface) and on both gate lines (the resolution
    fold's pairing key). A non-loop gate records none."""

    @staticmethod
    def _gate_lines(collector: WorkflowTraceCollector) -> list[dict[str, Any]]:
        return [ln for ln in _read_lines(collector._stream_path) if ln["kind"] == "gate"]

    def test_loop_approval_lines_carry_the_iteration(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "tick",
                    "type": "code",
                    "params": {"code": "i: int\nresult: bool = int(i) < 3", "inputs": {"i": "${__iteration__}"}},
                    "approval": "required",
                    "loop": {"while": "${tick.result}", "max_iterations": 3},
                }
            ],
            "edges": [],
        }
        collector = _run_streamed_until_gate_stop(ir, {"__gate_resolver__": _ApproveFirst(1)}, tmp_path)
        lines = self._gate_lines(collector)
        assert [(ln["phase"], ln.get("resolution"), ln["iteration"]) for ln in lines] == [
            ("pause", None, 1),
            ("resolution", "approved", 1),
            ("pause", None, 2),
            ("resolution", "non_interactive", 2),
        ]
        assert [ln["request"]["iteration"] for ln in lines if ln["phase"] == "pause"] == [1, 2]

    def test_non_loop_approval_lines_carry_no_iteration(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        collector, _ = _run_streamed(_gated_ir(), _approver, tmp_path)
        lines = self._gate_lines(collector)
        assert [ln["phase"] for ln in lines] == ["pause", "resolution"]
        assert all("iteration" not in ln for ln in lines)
        # The payload states it explicitly (JSON-native null), beside its other fields.
        assert lines[0]["request"]["node_id"] == "b"
        assert lines[0]["request"]["iteration"] is None

    def test_loop_escalation_lines_carry_the_iteration(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "agent",
                    "type": "code",
                    "params": {
                        "code": "i: int\nresult: dict = {'escalation': {'question': f'q{i}?'}, 'go': int(i) < 2}",
                        "inputs": {"i": "${__iteration__}"},
                    },
                    "loop": {"while": "${agent.result.go}", "max_iterations": 3},
                }
            ],
            "edges": [],
        }

        def chooser(request, *, allow_prompt):
            return GateResolution(approved=True, resolved_via="prompt", chosen="a")

        collector, _ = _run_streamed(ir, chooser, tmp_path)
        lines = self._gate_lines(collector)
        assert [(ln["phase"], ln["iteration"]) for ln in lines] == [
            ("pause", 1),
            ("resolution", 1),
            ("pause", 2),
            ("resolution", 2),
        ]
        # The iteration that raised each gate, matched to the question it asked.
        assert [(ln["request"]["question"], ln["request"]["iteration"]) for ln in lines if ln["phase"] == "pause"] == [
            ("q1?", 1),
            ("q2?", 2),
        ]
