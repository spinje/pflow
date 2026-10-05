"""Task 171 — the durable-pause PRODUCER: the engine's gate arm + collector trailer.

The pause is a PROMISE: every ``paused`` stamp emits a token the resume path must
accept. These tests pin both halves of that promise at the producer:

- ``_gate_pausable`` refusals (code-node / terminal escalations stay
  ``failed`` — ``resume_preflight._resolve_between_nodes_entry`` would bounce their
  token, so none is ever issued); an approval always pauses — a loop step's at
  any iteration, which resume continues at (Task 179);
- the nesting guard (a child-workflow gate never pauses the run, even when its
  node id COLLIDES with a top-level id — the reason the arm uses an explicit
  ``nested`` flag + first-seen exception tag instead of any id comparison);
- the trailer contract (``final_status: "paused"`` + ``paused_node_id`` +
  ``gate_request``) and its torn-write degradation to Task 164's incomplete arm.
"""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path
from typing import Any, ClassVar

import pytest

from pflow.core.exceptions import GateNotInteractiveError
from pflow.core.gate import GateResolution
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


class EscalateUntilDecidedNode(Node):
    """Test node shaped like the guide's re-fork recipe: escalates until a decision arrives.

    Interface:
    - Params: decision: any  # The previous iteration's decision (empty on the first)
    - Params: log_path: str  # Appends one line per run, naming the decision it saw
    - Writes: shared["result"]: dict  # The escalation marker, or the applied decision
    - Actions: default
    """

    def prep(self, shared: dict) -> tuple[Any, str]:
        return self.params.get("decision"), str(self.params.get("log_path", ""))

    def exec(self, prep_res: tuple[Any, str]) -> dict:
        decision, log_path = prep_res
        chosen = decision.get("chosen") if isinstance(decision, dict) else None
        if log_path:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(f"decision={chosen or ''}\n")
        if not chosen:
            return {"escalation": {"question": "which way?", "options": [{"label": "left"}, {"label": "right"}]}}
        return {"escalation": None, "applied": chosen}

    def post(self, shared: dict, prep_res: tuple[Any, str], exec_res: dict) -> str:
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
        assert request["iteration"] is None  # not a loop step
        # The escalating node's own success record stands (it DID run).
        assert collector._determine_trace_status() == "paused"

    def test_terminal_escalation_stays_failed(self):
        # No default successor: the answer would have nothing left to run.
        collector = _run_gated(_escalation_ir(successor=False))
        assert collector.gate_outcome == "failed"
        assert collector.pause_request is None

    @pytest.mark.trace_files
    def test_loop_node_escalation_pauses_with_position(self, tmp_path, monkeypatch):
        """Task 179: a loop step's escalation pauses (its continuation — another iteration
        or the exit — is the engine's re-entry decision on resume). Iteration 2's escalation
        pauses with its position; the loader resumes AFTER that iteration (entry 3)."""
        from pflow.runtime.resume_source import load_resume_source

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        answers = iter([GateResolution(approved=True, resolved_via="prompt", chosen="a")])

        def answer_first(request: Any, *, allow_prompt: bool = True) -> GateResolution:
            resolution = next(answers, None)
            if resolution is None:
                raise GateNotInteractiveError(request)
            return resolution

        ir = _escalation_ir(successor=True, loop={"while": "${esc.result.escalation}", "max_iterations": 3})
        collector = WorkflowTraceCollector(
            "gated", workflow_path="gated.pflow.md", is_run_scoped=True, stream_to_disk=True
        )
        with pytest.raises(GateNotInteractiveError):
            WorkflowEngine(trace_collector=collector, workflow_path="gated.pflow.md").run(
                compile_workflow(ir, _registry_with_escalating_node()), {"__gate_resolver__": answer_first}
            )
        path = collector.finalize()
        assert path is not None
        assert collector.gate_outcome == "paused"
        assert collector.pause_request is not None
        assert collector.pause_request["gate_request"]["iteration"] == 2

        source = load_resume_source(
            execution_id=collector.execution_id, debug_dir=path.parent, gate_answer={"chosen": "b", "notes": None}
        )
        assert (source.entry_node_id, source.last_completed_node_id, source.entry_iteration) == (None, "esc", 3)

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


class _ApproveFirstResolver:
    """Approves the first ``approvals`` gate requests, then behaves like a non-TTY run."""

    def __init__(self, approvals: int) -> None:
        self.remaining = approvals

    def __call__(self, request: Any, *, allow_prompt: bool = True) -> GateResolution:
        if self.remaining > 0:
            self.remaining -= 1
            return GateResolution(approved=True, resolved_via="flag")
        raise GateNotInteractiveError(request)


def _loop_approval_ir() -> dict[str, Any]:
    return {
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


class TestApprovalPausePromise:
    """Task 179: a loop step's approval pauses at EVERY iteration, and resume continues
    at the gated iteration (superseding #615's first-iteration-only rule)."""

    def test_loop_approval_on_first_iteration_pauses(self):
        collector = _run_gated(_loop_approval_ir())
        assert collector.gate_outcome == "paused"
        assert collector.pause_request is not None
        assert collector.pause_request["paused_node_id"] == "tick"
        assert collector.pause_request["gate_request"]["iteration"] == 1

    @pytest.mark.trace_files
    def test_loop_approval_after_first_iteration_pauses_with_position(self, tmp_path, monkeypatch):
        """Iteration 2's approval pauses with its position; the answer runs iteration 2,
        iteration 3 pauses again as a NEW token; a third attempt finishes — iteration 1
        never re-runs and each attempt trace is self-contained (resume-of-a-resume)."""
        from pflow.core.exceptions import ResumeSupersededError
        from pflow.runtime.resume_source import load_resume_source

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        debug_dir = tmp_path / ".pflow" / "debug"
        marker = tmp_path / "effects.txt"
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "prep", "type": "shell", "params": {"command": "echo ready"}},
                {
                    "id": "tick",
                    "type": "code",
                    "params": {
                        "code": (
                            "i: int\nmarker: str\n"
                            "with open(marker, 'a', encoding='utf-8') as fh:\n    fh.write(f'effect {i}\\n')\n"
                            "result: bool = int(i) < 3"
                        ),
                        "inputs": {"i": "${__iteration__}", "marker": str(marker)},
                    },
                    "approval": "required",
                    "loop": {"while": "${tick.result}", "max_iterations": 3},
                },
            ],
            "edges": [{"from": "prep", "to": "tick"}],
        }
        compiled = compile_workflow(ir, _registry_with_escalating_node())

        def attempt(resolver: Any, source: Any = None) -> WorkflowTraceCollector:
            """One attempt — the source run, or a resume whose single-use answer is ``resolver``."""
            collector = WorkflowTraceCollector(
                "gated",
                workflow_path="gated.pflow.md",
                is_run_scoped=True,
                stream_to_disk=True,
                resumed_from=source.execution_id if source is not None else None,
            )
            engine = WorkflowEngine(
                trace_collector=collector,
                workflow_path="gated.pflow.md",
                resume_from=source.entry_node_id if source is not None else None,
                resume_events=source.events if source is not None else None,
                resume_source_id=source.execution_id if source is not None else None,
                resume_iteration=source.entry_iteration if source is not None else 1,
            )
            with contextlib.suppress(GateNotInteractiveError):  # a pausing attempt stops at its gate
                engine.run(compiled, {"__gate_resolver__": resolver})
            assert collector.finalize() is not None
            return collector

        def effects() -> list[str]:
            return marker.read_text(encoding="utf-8").splitlines()

        first = attempt(_ApproveFirstResolver(approvals=1))
        assert first.gate_outcome == "paused"
        assert first.pause_request is not None
        assert first.pause_request["gate_request"]["iteration"] == 2
        assert effects() == ["effect 1"]

        source = load_resume_source(execution_id=first.execution_id, debug_dir=debug_dir, gate_answer={"approve": True})
        assert (source.entry_node_id, source.entry_iteration) == ("tick", 2)
        second = attempt(_ApproveFirstResolver(approvals=1), source)
        assert second.gate_outcome == "paused"
        assert second.pause_request is not None
        assert second.pause_request["gate_request"]["iteration"] == 3
        assert effects() == ["effect 1", "effect 2"]

        source = load_resume_source(
            execution_id=second.execution_id, debug_dir=debug_dir, gate_answer={"approve": True}
        )
        assert (source.entry_node_id, source.entry_iteration) == ("tick", 3)
        third = attempt(_ApproveFirstResolver(approvals=1), source)
        assert third._determine_trace_status() == "success"
        assert effects() == ["effect 1", "effect 2", "effect 3"]
        # Self-contained: tick's seeded iteration 2 re-recorded (restored), then iteration 3 ran.
        ticks = [(e.get("restored", False), e["iteration"]) for e in third.events if e["node_id"] == "tick"]
        assert ticks == [(True, 2), (False, 3)]
        assert [e["node_id"] for e in third.events if e.get("restored")] == ["prep", "tick"]
        with pytest.raises(ResumeSupersededError):
            load_resume_source(execution_id=second.execution_id, debug_dir=debug_dir, gate_answer={"approve": True})


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
            "```shell command\necho child-review\n```\n",
            encoding="utf-8",
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
            "```shell command\necho child-action\n```\n",
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
        "```shell command\necho child-action\n```\n",
        encoding="utf-8",
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


@pytest.mark.trace_files
def test_answered_loop_escalation_then_failure_resumes_with_the_recorded_decision(tmp_path, monkeypatch):
    """D2b (1), real producer (Task 179): K escalates at iteration 1 (answered at the prompt),
    then fails at iteration 2. The answer folds onto iteration 1's event — the one the
    resume seeds — so the resume neither false-refuses nor loses the decision, and the
    carried decision iteration 2 receives equals an uninterrupted run's."""
    from pflow.runtime.resume_source import load_resume_source

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    log = tmp_path / "decisions.txt"
    flag = tmp_path / "fail"
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "k",
                "type": "code",
                "params": {
                    "code": (
                        "from pathlib import Path\n"
                        "i: int\ndecision: str\n"
                        f"with open({str(log)!r}, 'a', encoding='utf-8') as fh:\n    fh.write(decision + '\\n')\n"
                        f"if i == 2 and Path({str(flag)!r}).exists():\n    raise RuntimeError('injected')\n"
                        "result: dict = {'escalation': {'question': 'pick?'} if i == 1 else None, 'more': i < 2}"
                    ),
                    "inputs": {"i": "${__iteration__}", "decision": "none-yet"},
                },
                "loop": {
                    "carry": {"decision": "${k.result.escalation.decision.chosen}"},
                    "while": "${k.result.more}",
                    "max_iterations": 3,
                },
            }
        ],
        "edges": [],
    }
    compiled = compile_workflow(ir, _registry_with_escalating_node())

    def chooser(request: Any, *, allow_prompt: bool = True) -> GateResolution:
        return GateResolution(approved=True, resolved_via="prompt", chosen="A")

    def run(resolver: Any, source: Any = None) -> WorkflowTraceCollector:
        collector = WorkflowTraceCollector(
            "esc-loop", workflow_path="esc-loop.pflow.md", is_run_scoped=True, stream_to_disk=True
        )
        engine = WorkflowEngine(
            trace_collector=collector,
            workflow_path="esc-loop.pflow.md",
            resume_from=source.entry_node_id if source is not None else None,
            resume_events=source.events if source is not None else None,
            resume_source_id=source.execution_id if source is not None else None,
            resume_iteration=source.entry_iteration if source is not None else 1,
        )
        engine.run(compiled, {"__gate_resolver__": resolver})
        assert collector.finalize() is not None
        return collector

    run(chooser)
    uninterrupted = log.read_text(encoding="utf-8").splitlines()
    assert uninterrupted == ["none-yet", "A"]
    log.unlink()
    for trace in (tmp_path / ".pflow" / "debug").glob("*"):
        trace.unlink()

    flag.write_text("1", encoding="utf-8")
    failed = run(chooser)
    assert failed._determine_trace_status() == "failed"
    flag.unlink()
    source = load_resume_source(execution_id=failed.execution_id, debug_dir=tmp_path / ".pflow" / "debug")
    assert (source.entry_node_id, source.entry_iteration) == ("k", 2)

    def no_prompt(request: Any, *, allow_prompt: bool = True) -> GateResolution:
        raise AssertionError(f"iteration 1's escalation must not be asked again: {request}")

    resumed = run(no_prompt, source)
    assert resumed._determine_trace_status() == "success"
    assert log.read_text(encoding="utf-8").splitlines() == ["none-yet", "A", "A"]
    restored_k = next(e for e in resumed.events if e["node_id"] == "k" and e.get("restored"))
    assert restored_k["node_output"]["result"]["escalation"]["decision"] == {"chosen": "A", "notes": None}


def _pause_loop_escalation_then_resume_after(tmp_path: Path, loop: dict[str, Any]) -> dict[str, Any]:
    """Pause a looping escalation at iteration 1 (no resolver), answer it through the
    loader, resume AFTER it on the engine; return the resumed attempt's shared store."""
    from pflow.runtime.resume_source import load_resume_source

    ir = _escalation_ir(successor=True, loop=loop)
    registry = _registry_with_escalating_node()
    collector = WorkflowTraceCollector("gated", workflow_path="gated.pflow.md", is_run_scoped=True, stream_to_disk=True)
    with pytest.raises(GateNotInteractiveError):
        WorkflowEngine(trace_collector=collector, workflow_path="gated.pflow.md").run(
            compile_workflow(ir, registry), {}
        )
    path = collector.finalize()
    assert path is not None
    assert collector.gate_outcome == "paused"
    source = load_resume_source(
        execution_id=collector.execution_id, debug_dir=path.parent, gate_answer={"chosen": "a", "notes": None}
    )
    assert (source.entry_node_id, source.last_completed_node_id, source.entry_iteration) == (None, "esc", 2)

    shared: dict[str, Any] = {"__gate_resolver__": _ApproveFirstResolver(approvals=0)}
    WorkflowEngine(
        workflow_path="gated.pflow.md",
        resume_after="esc",
        resume_events=source.events,
        resume_source_id=source.execution_id,
        resume_iteration=source.entry_iteration,
    ).run(compile_workflow(ir, registry), shared)
    return shared


@pytest.mark.trace_files
class TestResumeAfterLoopStep:
    """Task 179 D3: an answered loop escalation resumes AFTER the iteration that raised it —
    the engine makes the re-entry decision the walk would have made (``should_reenter``)."""

    def test_falsy_condition_exits_to_the_successor_without_rerunning_the_step(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        shared = _pause_loop_escalation_then_resume_after(
            tmp_path, {"until": "${esc.result.escalation.decision}", "max_iterations": 3}
        )
        execution = shared["__execution__"]
        assert execution["completed_nodes"] == ["after"]  # esc did not run again
        assert execution["resume_entry_node"] == "after"
        assert execution["restored_nodes"] == ["esc"]  # its decided output stands
        assert shared["esc"]["loop_stopped"] == "condition"
        assert shared["esc"]["result"]["escalation"]["decision"] == {"chosen": "a", "notes": None}
        assert shared["after"]["stdout"].strip() == "after"

    def test_decision_sees_the_completed_iteration(self, tmp_path, monkeypatch):
        """P2 review (convergent): like the walk, the after-K decision reads the completed
        iteration as ``${__iteration__}`` — absent, ``while: ${__iteration__}`` would read
        falsy and exit early. Here it re-enters: iteration 2 runs and escalates again."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with pytest.raises(GateNotInteractiveError) as exc_info:
            _pause_loop_escalation_then_resume_after(tmp_path, {"while": "${__iteration__}", "max_iterations": 3})
        assert (exc_info.value.request.node_id, exc_info.value.request.iteration) == ("esc", 2)

    def test_condition_still_true_at_the_cap_exits_with_the_cap_advisory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        shared = _pause_loop_escalation_then_resume_after(
            tmp_path, {"while": "${esc.result.escalation}", "max_iterations": 1}
        )
        execution = shared["__execution__"]
        assert execution["completed_nodes"] == ["after"]
        assert execution["resume_entry_node"] == "after"
        assert shared["esc"]["loop_stopped"] == "max_iterations"
        assert shared["__warnings__"]["esc"].id == "loop.max-iterations-reached"


_LOOP = {"while": "${esc.result.escalation}", "max_iterations": 3}
_CODE_ESCALATION = {
    "ir_version": "0.1.0",
    "nodes": [
        {"id": "esc", "type": "code", "params": {"code": "result: dict = {'escalation': 'a or b?'}"}},
        {"id": "after", "type": "shell", "params": {"command": "echo after"}},
    ],
    "edges": [{"from": "esc", "to": "after"}],
}


@pytest.mark.parametrize(
    ("ir", "pauses"),
    [
        (_escalation_ir(successor=True), True),
        (_escalation_ir(successor=True, loop=_LOOP), True),  # Task 179: a loop step pauses too
        (_CODE_ESCALATION, False),  # dynamic router
        (_escalation_ir(successor=False), False),  # final step
        (_escalation_ir(successor=False, loop=_LOOP), False),  # final loop step (ruling (b))
    ],
    ids=["mid-graph", "loop", "code-router", "final-step", "final-loop-step"],
)
def test_escalation_pause_mirrors_the_preflight(ir, pauses):
    """Pause = promise, both directions: the producer pauses an escalation exactly when the
    preflight would accept its between-nodes token (an iteration-1 escalation resumes AFTER
    it at iteration 2). ``action == "end"`` is unit-pinned above (no IR shape produces it)."""
    from pflow.core.exceptions import ResumeNotResumableError
    from pflow.execution.result import ResolvedWorkflow
    from pflow.execution.resume_preflight import _resolve_between_nodes_entry
    from pflow.runtime.resume_source import ResumeSource

    collector = _run_gated(ir)
    assert (collector.gate_outcome == "paused") is pauses

    is_loop = "loop" in ir["nodes"][0]
    source = ResumeSource(
        path=Path("/x/t.json"),
        workflow_path="/x/wf.pflow.md",
        execution_id="e1",
        entry_node_id=None,
        last_completed_node_id="esc",
        events=[],
        inputs=None,
        content_hash=None,
        paused_node_id="esc",
        gate_request={"kind": "decision_escalation"},
        entry_iteration=2 if is_loop else None,
    )
    resolved = ResolvedWorkflow(ir=ir, source="file", file_path="/x/wf.pflow.md")
    if pauses:
        _resolve_between_nodes_entry(resolved, source)
    else:
        with pytest.raises(ResumeNotResumableError):
            _resolve_between_nodes_entry(resolved, source)


@pytest.mark.trace_files
def test_approval_after_a_recovered_failure_resumes_at_the_gated_iteration(tmp_path, monkeypatch):
    """P2 review (feature-interactions C1): K fails at iteration 3, its on-error handler H
    routes back to K, and K's approval pauses at iteration 4. The resume must run the
    iteration the human approved (4, with H's output in the store) — not re-run the
    recovered failure at 3."""
    from pflow.runtime.resume_source import load_resume_source

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "k",
                "type": "code",
                "approval": "required",
                "params": {
                    "code": "i: int\nif int(i) == 3:\n    raise RuntimeError('boom')\nresult: dict = {'more': int(i) < 5}",
                    "inputs": {"i": "${__iteration__}"},
                },
                "loop": {"while": "${k.result.more}", "max_iterations": 5},
            },
            {"id": "h", "type": "shell", "params": {"command": "echo handled"}},
        ],
        # The back edge carries an explicit action (the validator's backward-edge rule).
        "edges": [{"from": "k", "to": "h", "action": "error"}, {"from": "h", "to": "k", "action": "default"}],
    }
    compiled = compile_workflow(ir, _registry_with_escalating_node())

    def run(resolver: Any, source: Any = None) -> WorkflowTraceCollector:
        collector = WorkflowTraceCollector("bk", workflow_path="bk.pflow.md", is_run_scoped=True, stream_to_disk=True)
        engine = WorkflowEngine(
            trace_collector=collector,
            workflow_path="bk.pflow.md",
            resume_from=source.entry_node_id if source is not None else None,
            resume_events=source.events if source is not None else None,
            resume_source_id=source.execution_id if source is not None else None,
            resume_iteration=source.entry_iteration if source is not None else 1,
        )
        with contextlib.suppress(GateNotInteractiveError):
            engine.run(compiled, {"__gate_resolver__": resolver})
        assert collector.finalize() is not None
        return collector

    first = run(_ApproveFirstResolver(approvals=3))
    assert first.pause_request is not None
    assert first.pause_request["gate_request"]["iteration"] == 4
    source = load_resume_source(
        execution_id=first.execution_id, debug_dir=tmp_path / ".pflow" / "debug", gate_answer={"approve": True}
    )
    assert (source.entry_node_id, source.entry_iteration) == ("k", 4)

    resumed = run(_ApproveFirstResolver(approvals=1), source)
    live = [(e["node_id"], e.get("iteration")) for e in resumed.events if not e.get("restored")]
    assert live == [("k", 4)]  # the approved iteration ran; 3 was not re-run
    assert resumed.pause_request is not None
    assert resumed.pause_request["gate_request"]["iteration"] == 5
    assert [e["node_id"] for e in resumed.events if e.get("restored")] == ["h"]  # H's output was in the store
