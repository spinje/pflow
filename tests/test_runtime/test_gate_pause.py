"""Task 171 — the durable-pause PRODUCER: the engine's gate arm + collector trailer.

The pause is a PROMISE: every ``paused`` stamp emits a token the resume path must
accept. These tests pin both halves of that promise at the producer:

- ``_gate_pausable`` refusals (loop / code-node / terminal escalations stay
  ``failed`` — the CLI's ``_resolve_between_nodes_entry`` would bounce their
  token, so none is ever issued);
- the nesting guard (a child-workflow gate never pauses the run, even when its
  node id COLLIDES with a top-level id — the reason the arm uses an explicit
  ``nested`` flag + first-seen exception tag instead of any id comparison);
- the trailer contract (``final_status: "paused"`` + ``paused_node_id`` +
  ``gate_request``) and its torn-write degradation to Task 164's incomplete arm.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, ClassVar

import pytest

from pflow.core.exceptions import GateNotInteractiveError
from pflow.core.node import Node
from pflow.registry import Registry
from pflow.runtime import compile_workflow
from pflow.runtime.engine import WorkflowEngine
from pflow.runtime.engine.engine import _gate_pausable
from pflow.runtime.workflow_trace import WorkflowTraceCollector


class EscalatingNode(Node):
    """Test node that raises an escalation from a NON-code node type.

    Interface:
    - Params: question: str  # The escalation question
    - Writes: shared["result"]: dict  # Carries the undecided escalation marker
    - Actions: default
    """

    def prep(self, shared: dict) -> str:
        return str(self.params.get("question", "which option?"))

    def exec(self, question: str) -> dict:
        return {"escalation": {"question": question, "options": [{"label": "a"}, {"label": "b"}]}}

    def post(self, shared: dict, prep_res: str, exec_res: dict) -> str:
        shared["result"] = exec_res
        return "default"


def _registry_with_escalating_node() -> Registry:
    registry = Registry(Path(tempfile.mkdtemp()) / "gate_pause_registry.json")
    registry.save({
        "escalating-node": {
            "module": "tests.test_runtime.test_gate_pause",
            "class_name": "EscalatingNode",
            "docstring": EscalatingNode.__doc__ or "",
            "file_path": __file__,
        },
        "shell": {
            "module": "pflow.nodes.shell.shell",
            "class_name": "ShellNode",
            "docstring": "Shell node",
            "file_path": "src/pflow/nodes/shell/shell.py",
        },
        "code": {
            "module": "pflow.nodes.python.python_code",
            "class_name": "PythonCodeNode",
            "docstring": "Python code node",
            "file_path": "src/pflow/nodes/python/python_code.py",
        },
        "workflow": {
            "module": "pflow.runtime.workflow_executor",
            "class_name": "WorkflowExecutor",
            "docstring": "Nested workflow executor",
            "file_path": "src/pflow/runtime/workflow_executor.py",
        },
    })
    return registry


def _run_gated(ir: dict[str, Any], shared: dict[str, Any] | None = None) -> WorkflowTraceCollector:
    """Run ``ir`` with no resolver installed; return the ROOT collector after the gate stop."""
    collector = WorkflowTraceCollector("gated", workflow_path="gated.pflow.md", is_run_scoped=True)
    compiled = compile_workflow(ir, _registry_with_escalating_node())
    with pytest.raises(GateNotInteractiveError):
        WorkflowEngine(trace_collector=collector, workflow_path="gated.pflow.md").run(
            compiled, shared if shared is not None else {}
        )
    return collector


def _escalation_ir(*, successor: bool, loop: dict[str, Any] | None = None) -> dict[str, Any]:
    esc: dict[str, Any] = {"id": "esc", "type": "escalating-node", "params": {"question": "a or b?"}}
    if loop is not None:
        esc["loop"] = loop
    nodes = [esc]
    edges = []
    if successor:
        nodes.append({"id": "after", "type": "shell", "params": {"command": "echo after"}})
        edges.append({"from": "esc", "to": "after"})
    return {"ir_version": "0.1.0", "nodes": nodes, "edges": edges}


class TestEscalationPausePromise:
    """Producer-side halves of the pause-promise parity pin (producer-pauses ⟹ resume-accepts).

    The resume-accepts loader/engine half now lives in
    ``test_paused_escalation_real_trace_choose_answer_roundtrip`` (Phase 2, below);
    the ``--choose`` CLI-flag half lands with the Phase-3 e2e battery.
    """

    def test_mid_graph_escalation_pauses_with_full_gate_request(self):
        collector = _run_gated(_escalation_ir(successor=True))
        assert collector.gate_outcome == "paused"
        assert collector.pause_request is not None
        assert collector.pause_request["paused_node_id"] == "esc"
        request = collector.pause_request["gate_request"]
        assert request["kind"] == "decision_escalation"
        assert request["question"] == "a or b?"
        assert [option["label"] for option in request["options"]] == ["a", "b"]
        # The escalating node's own success record stands (it DID run).
        assert collector._determine_trace_status() == "paused"

    def test_terminal_escalation_stays_failed(self):
        # No default successor: the answer would have nothing left to run.
        collector = _run_gated(_escalation_ir(successor=False))
        assert collector.gate_outcome == "failed"
        assert collector.pause_request is None

    def test_loop_node_escalation_stays_failed(self):
        # Loop re-entry state is engine-ephemeral — the CLI refuses loop successors.
        collector = _run_gated(
            _escalation_ir(successor=True, loop={"while": "${esc.result.escalation}", "max_iterations": 3})
        )
        assert collector.gate_outcome == "failed"
        assert collector.pause_request is None

    def test_code_node_escalation_stays_failed(self):
        # A code node is a dynamic router — the CLI refuses `code` successors.
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "agent", "type": "code", "params": {"code": "result: dict = {'escalation': 'a or b?'}"}},
                {"id": "after", "type": "shell", "params": {"command": "echo after"}},
            ],
            "edges": [{"from": "agent", "to": "after"}],
        }
        collector = _run_gated(ir)
        assert collector.gate_outcome == "failed"
        assert collector.pause_request is None

    def test_end_action_refused_by_gate_pausable(self):
        """The ``action == "end"`` clause, unit-pinned: no non-code node returns a
        literal "end" action alongside an escalation in today's graph shapes, so
        this defensive clause is exercised directly."""

        class _Config:
            loop_config = None
            node_type_name = "EscalatingNode"

        class _Node:
            successors: ClassVar[dict[str, Any]] = {"default": object()}

        class _Request:
            kind = "decision_escalation"

        assert _gate_pausable(_Request(), _Config(), _Node(), "default") is True
        assert _gate_pausable(_Request(), _Config(), _Node(), "end") is False


class TestNestingGuard:
    def test_child_gate_with_id_colliding_parent_host_stays_failed(self, tmp_path):
        """The id-collision pin: a child gate node named IDENTICALLY to its parent
        WorkflowExecutor host must never smuggle the run into ``paused``. The naive
        ``request.node_id == config.node_id`` heuristic passes every OTHER test —
        only this collision catches it (deep-review Critical, plan 1a)."""
        child = tmp_path / "child.pflow.md"
        child.write_text(
            "# Child\n\nChild whose gated step shares the parent host's id.\n\n## Steps\n\n"
            "### review\n\nGated child step.\n\n- type: shell\n- approval: required\n\n"
            "```shell command\necho child-review\n```\n"
        )
        ir = {
            "ir_version": "0.1.0",
            # Parent host id == child gate id == "review".
            "nodes": [{"id": "review", "type": "workflow", "params": {"workflow": str(child)}}],
            "edges": [],
        }
        collector = _run_gated(ir)
        assert collector.gate_outcome == "failed"
        assert collector.pause_request is None

    # NOTE (plan delta, 2026-07-05): the plan's "batch-HOST approval → pauses"
    # scenario is unproducible — `approval:` on a batch step is rejected at
    # compile/validation by check_approval_allowed (Task 125). No test.

    def test_parallel_batch_child_gate_stays_failed(self, tmp_path):
        """A gate inside a parallel batch item (sub-workflow child) keeps today's
        ``failed`` — v1 scope. Both guards exclude it: the child engine is
        ``nested=True``, and the worker raise carries ``parallel_batch=True``."""
        child = tmp_path / "child.pflow.md"
        child.write_text(
            "# Child\n\nChild with a gated step.\n\n## Steps\n\n"
            "### gated-step\n\nGated child action.\n\n- type: shell\n- approval: required\n\n"
            "```shell command\necho child-action\n```\n"
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
        collector = WorkflowTraceCollector("gated", workflow_path="gated.pflow.md", is_run_scoped=True)
        compiled = compile_workflow(ir, _registry_with_escalating_node())
        # Gate exceptions are exempted (retriable=False, re-raised untouched) at
        # the batch retry loop too — the original exception reaches the root.
        with pytest.raises(GateNotInteractiveError) as exc_info:
            WorkflowEngine(trace_collector=collector, workflow_path="gated.pflow.md").run(compiled, {"items": [1, 2]})
        assert exc_info.value.parallel_batch is True
        assert collector.gate_outcome == "failed"
        assert collector.pause_request is None


class TestPausedCollectorContracts:
    def test_has_resumable_step_false_on_paused_collector(self):
        """Pin (plan 1b): `paused` is not `failed`, so the failure resume-hint and
        the JSON `resume_command` stay suppressed via has_resumable_step()."""
        collector = _run_gated(_escalation_ir(successor=True))
        assert collector.gate_outcome == "paused"
        assert collector.has_resumable_step() is False

    def test_first_node_pause_reads_paused_not_failed(self):
        """Status-ladder ORDERING pin: an approval on the workflow's FIRST node
        pauses with ZERO node events, and `_determine_trace_status` has a
        zero-events arm that returns "failed" ("nothing executed = crash").
        The paused check must stay ABOVE that arm — no other test has a
        zero-event paused run, so only this pins the ordering. (Phase 3's
        by-name token selection depends on first-node pauses staying honest.)"""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "gated", "type": "shell", "params": {"command": "echo x"}, "approval": "required"},
            ],
            "edges": [],
        }
        collector = _run_gated(ir)
        assert collector.events == []  # the gate fired before anything ran
        assert collector._determine_trace_status() == "paused"
        assert collector.pause_request is not None
        assert collector.pause_request["paused_node_id"] == "gated"


@pytest.mark.trace_files
def test_failed_child_gate_stop_still_refuses_naming_the_gate(tmp_path, monkeypatch):
    """The pre-171 gate-stop refusal chain (failed trace + zero unrecovered nodes →
    ResumeGateStoppedError naming the gate) survives for the stops that STAY
    ``failed`` — a child-workflow gate. Descends from the Task 164 e2e pin whose
    top-level scenario now pauses instead."""
    from pflow.core.exceptions import ResumeGateStoppedError
    from pflow.core.trace_io import load_trace_file
    from pflow.runtime.resume_source import load_resume_source

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".pflow" / "debug").mkdir(parents=True)

    child = tmp_path / "child.pflow.md"
    child.write_text(
        "# Child\n\nChild with a gated step.\n\n## Steps\n\n"
        "### child-gate\n\nGated child action.\n\n- type: shell\n- approval: required\n\n"
        "```shell command\necho child-action\n```\n"
    )
    wf_path = tmp_path / "parent.pflow.md"
    ir = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "sub", "type": "workflow", "params": {"workflow": str(child)}}],
        "edges": [],
    }
    collector = WorkflowTraceCollector("parent", workflow_path=str(wf_path), is_run_scoped=True, stream_to_disk=True)
    compiled = compile_workflow(ir, Registry())
    with pytest.raises(GateNotInteractiveError):
        WorkflowEngine(trace_collector=collector, workflow_path=str(wf_path)).run(compiled, {})
    path = collector.finalize()
    assert path is not None
    assert load_trace_file(path)["final_status"] == "failed"

    with pytest.raises(ResumeGateStoppedError) as exc:
        load_resume_source(execution_id=collector.execution_id, debug_dir=path.parent)
    assert exc.value.node_id == "child-gate"


@pytest.mark.trace_files
def test_torn_paused_trailer_degrades_to_incomplete_and_resumes(tmp_path, monkeypatch):
    """Crash story (plan 1b): a kill mid-trailer-write leaves a truncated final
    line → the reader tolerates it as a MISSING trailer → status `incomplete` →
    Task 164's interrupted arm still resumes the run (the gate pause line is
    earlier in the file and survives). No fsync/rename machinery."""
    from pflow.core.trace_io import load_trace_file
    from pflow.runtime.resume_source import load_resume_source

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    debug_dir = tmp_path / ".pflow" / "debug"
    debug_dir.mkdir(parents=True)

    wf_path = tmp_path / "gated.pflow.md"
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "prep", "type": "shell", "params": {"command": "echo ready"}},
            {"id": "guarded", "type": "shell", "params": {"command": "echo do-it"}, "approval": "required"},
        ],
        "edges": [{"from": "prep", "to": "guarded"}],
    }
    collector = WorkflowTraceCollector("gated", workflow_path=str(wf_path), is_run_scoped=True, stream_to_disk=True)
    compiled = compile_workflow(ir, Registry())
    with pytest.raises(GateNotInteractiveError):
        WorkflowEngine(trace_collector=collector, workflow_path=str(wf_path)).run(compiled, {})
    path = collector.finalize()
    assert path is not None
    assert load_trace_file(path)["final_status"] == "paused"

    # Tear the trailer: keep the file but truncate the last line mid-JSON.
    lines = path.read_text(encoding="utf-8").splitlines()
    torn = "\n".join([*lines[:-1], lines[-1][: len(lines[-1]) // 2]])
    path.write_text(torn, encoding="utf-8")

    assert load_trace_file(path)["final_status"] == "incomplete"
    source = load_resume_source(execution_id=collector.execution_id, debug_dir=path.parent)
    # 164's incomplete arm: killed between nodes after 'prep' — the CLI resolves
    # the successor from there. The pause degraded gracefully to a plain resume.
    assert source.last_completed_node_id == "prep"


@pytest.mark.trace_files
def test_paused_escalation_real_trace_choose_answer_roundtrip(tmp_path, monkeypatch):
    """The escalation-side pause-promise keystone (Task 171 Phase 2), on a REAL producer
    trace: a mid-graph escalation pauses; the loader with a numeric ``--choose``-shaped
    answer maps it through the option labels the producer actually wrote, folds the
    DECIDED marker into the events, and returns the between-nodes entry; the resumed
    engine run (entry = the successor, exactly what the CLI resolves post-compile)
    restores the escalating step WITHOUT re-executing it, re-records the decided marker
    into the attempt trace (self-containment for resume-of-a-resume), and runs the
    successor. Producer-pauses ⟹ resume-accepts on an unchanged workflow — the
    loader/engine half; the ``--choose`` FLAG itself lands with the Phase-3 CLI."""
    from pflow.runtime.resume_source import load_resume_source

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".pflow" / "debug").mkdir(parents=True)

    ir = _escalation_ir(successor=True)
    registry = _registry_with_escalating_node()
    collector = WorkflowTraceCollector("gated", workflow_path="gated.pflow.md", is_run_scoped=True, stream_to_disk=True)
    with pytest.raises(GateNotInteractiveError):
        WorkflowEngine(trace_collector=collector, workflow_path="gated.pflow.md").run(
            compile_workflow(ir, registry), {}
        )
    path = collector.finalize()
    assert path is not None

    source = load_resume_source(
        execution_id=collector.execution_id, debug_dir=path.parent, gate_answer={"chosen": "2", "notes": None}
    )
    assert (source.entry_node_id, source.last_completed_node_id) == (None, "esc")
    # The numeric answer mapped through the REAL producer-written options ("a", "b").
    folded = next(e for e in source.events if e["node_id"] == "esc")
    assert folded["node_output"]["result"]["escalation"]["decision"] == {"chosen": "b", "notes": None}

    # Resume at the successor — the entry the CLI's between-nodes resolution pins.
    attempt = WorkflowTraceCollector("gated", workflow_path="gated.pflow.md", is_run_scoped=True, stream_to_disk=True)
    shared: dict = {}
    engine = WorkflowEngine(
        trace_collector=attempt,
        resume_from="after",
        resume_events=source.events,
        resume_source_id=source.execution_id,
    )
    engine.run(compile_workflow(ir, registry), shared)
    attempt.finalize()

    execution = shared["__execution__"]
    assert execution["restored_nodes"] == ["esc"]  # restored, never re-executed (never re-paid)
    assert execution["completed_nodes"] == ["after"]
    # The seeded store carries the human's decision where downstream templates read it.
    assert shared["esc"]["result"]["escalation"]["decision"] == {"chosen": "b", "notes": None}
    assert shared["after"]["stdout"].strip() == "after"
    # Self-containment: the attempt trace re-recorded the DECIDED marker, so a
    # resume-of-a-resume (or a later --only) seeds from this attempt alone.
    re_recorded = next(e for e in attempt.events if e["node_id"] == "esc")
    assert re_recorded["restored"] is True
    assert re_recorded["node_output"]["result"]["escalation"]["decision"] == {"chosen": "b", "notes": None}
    assert attempt._determine_trace_status() == "success"


class TestInlinePausePromise:
    """Owner decision 2026-07-05 (option a): an INLINE run's gate never pauses.

    An inline source (dict IR / piped content) records only the synthesized
    ``ir-hash:<md5>`` identity — no file to re-resolve — so resume ALWAYS
    refuses its token. Pause = promise: the producer must not issue one. Making
    inline runs resumable (workflow content in the trace) is the tracked
    follow-up issue; when that lands, these pins flip.
    """

    def test_inline_gated_run_stays_failed_without_a_token(self):
        """Through the REAL runner, so the ir-hash synthesis path is the one exercised."""
        from pflow.core.workflow.status import WorkflowStatus
        from pflow.execution.result import RunnerConfig
        from pflow.execution.runner import WorkflowRunner

        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "guarded", "type": "shell", "params": {"command": "echo x"}, "approval": "required"}],
            "edges": [],
        }
        result = WorkflowRunner().run(ir, {}, RunnerConfig())
        assert result.status is WorkflowStatus.FAILED  # never PAUSED
        assert result.trace.gate_outcome == "failed"
        assert result.trace.pause_request is None

    def test_engine_without_workflow_path_never_pauses(self):
        """A rootless engine (workflow_path=None) has no re-resolvable identity either."""
        collector = WorkflowTraceCollector("gated", workflow_path="gated.pflow.md", is_run_scoped=True)
        compiled = compile_workflow(_escalation_ir(successor=True), _registry_with_escalating_node())
        with pytest.raises(GateNotInteractiveError):
            WorkflowEngine(trace_collector=collector).run(compiled, {})
        assert collector.gate_outcome == "failed"
        assert collector.pause_request is None


class TestOnlyPausePromise:
    """A gate fired under ``--only`` stays ``failed`` — never pauses.

    ``_run_only_snapshot`` shares ``_execute_node`` with the full walk, so a gate
    on the ``--only`` target reaches the pause arm. But the trace stamps
    ``only_node`` and every resume consumer EXCLUDES ``only_node`` traces from
    selection (``_iter_workflow_traces`` / ``_select_resume_trace`` by-exec-id),
    so a token issued here would never resolve — pause = promise, so the producer
    must not issue one. Reachability: a prior answered full run leaves a snapshot;
    a non-TTY ``--only`` re-run of the gate node fires the gate again.
    """

    def _run_only_gate(self):
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "upstream", "type": "shell", "params": {"command": "echo up"}},
                {
                    "id": "gated",
                    "type": "shell",
                    "params": {"command": "echo go"},
                    "approval": "required",
                },
            ],
            "edges": [{"from": "upstream", "to": "gated"}],
        }
        collector = WorkflowTraceCollector("gated", workflow_path="gated.pflow.md", is_run_scoped=True)
        compiled = compile_workflow(ir, _registry_with_escalating_node())
        with pytest.raises(GateNotInteractiveError) as exc_info:
            WorkflowEngine(
                trace_collector=collector,
                workflow_path="gated.pflow.md",
                only_node="gated",
                snapshot_events=[{"node_id": "upstream", "node_output": {"stdout": "up"}}],
            ).run(compiled, {})
        return collector, exc_info.value

    def test_only_gate_stays_failed_without_a_token(self):
        collector, _ = self._run_only_gate()
        assert collector.gate_outcome == "failed"  # never "paused"
        assert collector.pause_request is None
        # only_node is stamped, confirming the trace is a non-resumable --only run.
        assert collector.only_node == "gated"

    def test_only_gate_remediation_names_only_as_the_cause(self):
        """Agent-UX: the failure message must NAME --only, not leave an agent
        staring at the generic 'unsupported position' list that doesn't apply."""
        _, exc = self._run_only_gate()
        suggestions = " ".join(exc.to_diagnostics()[0].suggestions)
        assert "--only" in suggestions
