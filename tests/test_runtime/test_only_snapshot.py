"""Snapshot ``--only`` semantics (issue #443).

``--only <node>`` runs the target against a frozen snapshot of the most recent
full successful run (restored from the debug trace) instead of re-walking the
graph — so side-effecting upstream nodes never re-fire. These tests pin:

- the headline regression: a side-effecting upstream node is NOT re-executed,
  and the execution summary reports restored nodes as ``not_executed`` (only the
  target ran);
- the loader's source policy (``--only`` traces excluded, ``failed`` rejected,
  ``degraded`` accepted, empty/missing → hard error);
- the seed helper's reserved-key filtering and target exclusion;
- the degraded-snapshot advisory (loud, never silent).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pflow.core.exceptions import OnlySnapshotMissingError
from pflow.core.node import BaseNode
from pflow.execution.execution_state import build_execution_steps
from pflow.execution.result import RunnerConfig, WorkflowStatus
from pflow.execution.runner import WorkflowRunner
from pflow.runtime.engine.engine import WorkflowEngine
from pflow.runtime.engine.types import CompiledWorkflow, LoopConfig, NodeConfig
from pflow.runtime.workflow_trace import (
    format_trace_filename,
    load_full_run_events,
    load_snapshot_or_raise,
    seed_snapshot_into_shared,
)
from tests.shared.markdown_utils import write_workflow_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SpyNode(BaseNode):
    """Records every exec() call in a shared list and writes a namespaced output."""

    def exec(self, prep_res: Any) -> Any:
        self.params.setdefault("_calls", []).append(self.node_id)
        return f"ran-{self.node_id}"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["out"] = exec_res
        # Record the loop-suppression depth active during this run so loop-target
        # tests can prove __loop_active__ (which suppresses the memo read) was raised.
        self.params["_loop_active_in_post"] = shared.get("__loop_active__", 0)
        return "default"


def _config(node_id: str, type_name: str = "SpyNode") -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        node_type_name=type_name,
        template_config=None,
        batch_config=None,
        namespaced=True,
        interface_metadata=None,
    )


def _write_trace(
    debug_dir: Path,
    workflow_path: str,
    *,
    name: str = "wf",
    timestamp: str,
    only_node: str | None = None,
    final_status: str = "success",
    nodes: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    format_version: str = "2.4.0",
    include_only_node_field: bool = True,
) -> Path:
    """Write a synthetic trace JSON the loader can discover, returning its path."""
    debug_dir.mkdir(parents=True, exist_ok=True)
    fname = format_trace_filename(workflow_path, name, timestamp)
    data: dict[str, Any] = {
        "format_version": format_version,
        "workflow_path": workflow_path,
        "final_status": final_status,
        "nodes": nodes if nodes is not None else [{"node_id": "fetch", "node_output": {"stdout": "data"}}],
    }
    if include_only_node_field:
        data["only_node"] = only_node
    if warnings is not None:
        data["warnings"] = warnings
    path = debug_dir / fname
    path.write_text(json.dumps(data))
    return path


# ---------------------------------------------------------------------------
# C1 — headline regression: side-effecting upstream never re-fires
# ---------------------------------------------------------------------------


@pytest.mark.trace_files
def test_only_does_not_refire_side_effecting_upstream(tmp_path: Path) -> None:
    """Full run fires a shell side effect once; --only must NOT re-fire it.

    End-to-end through WorkflowRunner (per tests/CLAUDE.md #20): the sentinel
    file count is the proof the upstream node didn't execute, and the execution
    summary reports it ``not_executed`` while only the target is ``completed``.
    """
    sentinel = tmp_path / "sentinel.txt"
    ir = {
        "nodes": [
            {
                "id": "fetch",
                "type": "shell",
                "params": {"command": f"echo fired >> {sentinel}; printf data"},
            },
            {
                "id": "summarize",
                "type": "shell",
                "params": {"command": "printf 'summary of ${fetch.stdout}'"},
            },
        ],
        "edges": [{"from": "fetch", "to": "summarize"}],
    }
    wf = tmp_path / "wf.pflow.md"
    write_workflow_file(ir, wf)

    # Full run: fires the side effect once and records the snapshot.
    full = WorkflowRunner().run(str(wf), {}, RunnerConfig())
    assert full.success, [d.message for d in full.diagnostics]
    full.trace.save_to_file()
    assert sentinel.read_text().count("fired") == 1

    # --only summarize: fetch is restored, never re-run.
    result = WorkflowRunner().run(str(wf), {}, RunnerConfig(only_node="summarize"))
    assert result.success, [d.message for d in result.diagnostics]
    assert sentinel.read_text().count("fired") == 1, "side-effecting upstream re-fired under --only"
    assert result.shared_after["summarize"]["stdout"] == "summary of data"

    steps = build_execution_steps({"nodes": [{"id": "fetch"}, {"id": "summarize"}]}, result.shared_after, None)
    by_id = {s["node_id"]: s["status"] for s in steps}
    assert by_id == {"fetch": "not_executed", "summarize": "completed"}


def test_only_spy_node_upstream_exec_not_called() -> None:
    """Engine-level: a restored upstream node's exec() is never invoked under --only."""
    upstream = _SpyNode()
    upstream.node_id = "upstream"
    upstream.set_params({"_calls": []})

    target = _SpyNode()
    target.node_id = "target"
    target.set_params({"_calls": []})

    upstream >> target

    workflow = CompiledWorkflow(
        start_node=upstream,
        node_configs={"upstream": _config("upstream"), "target": _config("target")},
    )
    shared: dict[str, Any] = {}
    engine = WorkflowEngine(
        only_node="target",
        snapshot_events=[{"node_id": "upstream", "node_output": {"out": "restored"}}],
    )
    engine.run(workflow, shared)

    # Upstream was restored, never executed; only the target ran.
    assert upstream.params["_calls"] == []
    assert target.params["_calls"] == ["target"]
    assert shared["upstream"] == {"out": "restored"}
    assert shared["__execution__"]["restored_nodes"] == ["upstream"]


# ---------------------------------------------------------------------------
# No usable snapshot → hard error
# ---------------------------------------------------------------------------


def test_no_snapshot_raises(tmp_path: Path) -> None:
    """An --only run with no trace on disk raises OnlySnapshotMissingError."""
    node = _SpyNode()
    node.node_id = "target"
    node.set_params({"_calls": []})
    workflow = CompiledWorkflow(start_node=node, node_configs={"target": _config("target")})
    engine = WorkflowEngine(only_node="target", workflow_path=str(tmp_path / "never-run.pflow.md"))

    with pytest.raises(OnlySnapshotMissingError):
        engine.run(workflow, {})


def test_empty_snapshot_events_raises() -> None:
    """An empty events list must RAISE, not seed an empty store (falsy-check path)."""
    with pytest.raises(OnlySnapshotMissingError):
        load_snapshot_or_raise("ir-hash:abc", "target", snapshot_events=[])


def test_empty_nodes_trace_is_no_match(tmp_path: Path) -> None:
    """A zero-event success trace must not masquerade as a usable snapshot."""
    wf = "ir-hash:emptynodes"
    _write_trace(tmp_path, wf, timestamp="20260101-000000", nodes=[])
    assert load_full_run_events(wf, debug_dir=tmp_path) is None
    with pytest.raises(OnlySnapshotMissingError):
        load_snapshot_or_raise(wf, "target", debug_dir=tmp_path)


def test_falsy_workflow_path_returns_none() -> None:
    """A falsy workflow_path short-circuits to None (degenerate inline case)."""
    assert load_full_run_events(None) is None
    assert load_full_run_events("") is None


# ---------------------------------------------------------------------------
# Loader source policy
# ---------------------------------------------------------------------------


def test_only_node_trace_excluded(tmp_path: Path) -> None:
    """A newer --only trace is skipped in favor of an older full-run trace."""
    wf = "ir-hash:excl"
    # Older full run.
    _write_trace(
        tmp_path,
        wf,
        timestamp="20260101-000000",
        only_node=None,
        nodes=[{"node_id": "fetch", "node_output": {"stdout": "full"}}],
    )
    # Newer --only run — must be excluded as a snapshot source.
    _write_trace(
        tmp_path,
        wf,
        timestamp="20260101-010000",
        only_node="summarize",
        nodes=[{"node_id": "summarize", "node_output": {"stdout": "only"}}],
    )

    loaded = load_full_run_events(wf, debug_dir=tmp_path)
    assert loaded is not None
    nodes, status = loaded
    assert status == "success"
    assert nodes == [{"node_id": "fetch", "node_output": {"stdout": "full"}}]


def test_failed_trace_rejected(tmp_path: Path) -> None:
    """A newer failed run does not shadow an older successful one."""
    wf = "ir-hash:failed"
    _write_trace(tmp_path, wf, timestamp="20260101-000000", final_status="success")
    _write_trace(tmp_path, wf, timestamp="20260101-010000", final_status="failed")

    loaded = load_full_run_events(wf, debug_dir=tmp_path)
    assert loaded is not None
    _nodes, status = loaded
    assert status == "success"


def test_legacy_2_3_0_trace_without_only_node_accepted(tmp_path: Path) -> None:
    """A synthetic 2.3.0 trace (no only_node field) is accepted as a snapshot."""
    wf = "ir-hash:legacy"
    _write_trace(
        tmp_path,
        wf,
        timestamp="20260101-000000",
        format_version="2.3.0",
        include_only_node_field=False,
    )
    loaded = load_full_run_events(wf, debug_dir=tmp_path)
    assert loaded is not None
    _nodes, status = loaded
    assert status == "success"


def test_degraded_trace_with_warning_reports_degraded(tmp_path: Path) -> None:
    """A degraded trace carrying a genuine WARNING surfaces status='degraded'."""
    wf = "ir-hash:degraded-warn"
    _write_trace(
        tmp_path,
        wf,
        timestamp="20260101-000000",
        final_status="degraded",
        warnings=[{"severity": "warning", "source": "runtime", "message": "dropped a failed batch item"}],
    )
    loaded = load_full_run_events(wf, debug_dir=tmp_path)
    assert loaded is not None
    _nodes, status = loaded
    assert status == "degraded"


def test_degraded_trace_with_info_only_reports_success(tmp_path: Path) -> None:
    """A trace marked degraded solely by an INFO advisory loses no data → success."""
    wf = "ir-hash:degraded-info"
    _write_trace(
        tmp_path,
        wf,
        timestamp="20260101-000000",
        final_status="degraded",
        warnings=[{"severity": "info", "source": "runtime", "message": "empty batch ran with no items"}],
    )
    loaded = load_full_run_events(wf, debug_dir=tmp_path)
    assert loaded is not None
    _nodes, status = loaded
    assert status == "success"


# ---------------------------------------------------------------------------
# seed_snapshot_into_shared unit
# ---------------------------------------------------------------------------


def test_seed_filters_reserved_keys_and_excludes_target() -> None:
    """Reserved engine keys are stripped; the target is never seeded; __metrics__ survives."""
    events = [
        {
            "node_id": "upstream",
            "node_output": {
                "stdout": "value",
                "__metrics__": {"tokens": 1},
                "__pflow_stats__": {"duration_ms": 5},
                "__pflow_warnings__": {"x": 1},
            },
        },
        {"node_id": "target", "node_output": {"stdout": "should-not-seed"}},
    ]
    shared: dict[str, Any] = {}
    final = seed_snapshot_into_shared(shared, events, exclude="target")

    assert "target" not in shared, "the --only target must never be seeded"
    assert shared["upstream"] == {"stdout": "value", "__metrics__": {"tokens": 1}}
    # The helper returns the final-events map (keyed by node_id) for restored_nodes.
    assert set(final) == {"upstream", "target"}


def test_seed_uses_last_event_per_node() -> None:
    """Loop recovery records multiple events; the LAST per node_id wins."""
    events = [
        {"node_id": "loop", "node_output": {"stdout": "first"}},
        {"node_id": "loop", "node_output": {"stdout": "final"}},
    ]
    shared: dict[str, Any] = {}
    seed_snapshot_into_shared(shared, events, exclude="other")
    assert shared["loop"] == {"stdout": "final"}


def test_seed_skips_events_without_output() -> None:
    """A node with no captured output is skipped (no empty seed)."""
    events = [{"node_id": "ghost"}]  # no node_output
    shared: dict[str, Any] = {}
    seed_snapshot_into_shared(shared, events, exclude="target")
    assert "ghost" not in shared


# ---------------------------------------------------------------------------
# Degraded-snapshot advisory (loud, flips DEGRADED) — end to end
# ---------------------------------------------------------------------------


@pytest.mark.trace_files
def test_degraded_snapshot_emits_loud_advisory(tmp_path: Path) -> None:
    """Restoring from a genuinely degraded run surfaces a WARNING advisory + DEGRADED."""
    wf = "ir-hash:adv"
    node = _SpyNode()
    node.node_id = "summarize"
    node.set_params({"_calls": []})
    workflow = CompiledWorkflow(start_node=node, node_configs={"summarize": _config("summarize")})

    # The engine's loader defaults to Path.home()/.pflow/debug, which the autouse
    # isolate fixture points at tmp_path. Write a degraded full-run trace there.
    home_debug = Path.home() / ".pflow" / "debug"
    _write_trace(
        home_debug,
        wf,
        timestamp="20260101-000000",
        final_status="degraded",
        nodes=[{"node_id": "fetch", "node_output": {"stdout": "partial"}}],
        warnings=[{"severity": "warning", "source": "runtime", "message": "batch dropped a failed item"}],
    )

    shared: dict[str, Any] = {}
    engine = WorkflowEngine(only_node="summarize", workflow_path=wf)
    engine.run(workflow, shared)

    advisory = shared["__warnings__"].get("__only_snapshot__")
    assert advisory is not None
    assert advisory.id == "only.snapshot-degraded"
    assert "DEGRADED" in advisory.message


# ---------------------------------------------------------------------------
# Engine ↔ planner parity for the --only target (single-entry plan + verdict)
# ---------------------------------------------------------------------------


@pytest.mark.trace_files
def test_planner_cached_verdict_matches_engine_serving_cached(tmp_path: Path) -> None:
    """For a mid-graph cached target, the planner says 'cached' AND the engine serves cached.

    The plan is a single entry (upstream/downstream not costed), the planner's
    verdict is ``cached``, and the engine actually serves the target from the memo
    cache — proven by a side effect that does NOT re-fire on the --only run.
    """
    sentinel = tmp_path / "b_ran.txt"
    ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": "printf a"}},
            {
                "id": "b",
                "type": "shell",
                "cache": True,
                "params": {"command": f"echo ran >> {sentinel}; printf b"},
            },
            {"id": "c", "type": "shell", "params": {"command": "printf c"}},
        ],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
    }
    wf = tmp_path / "cached-parity.pflow.md"
    write_workflow_file(ir, wf)

    full = WorkflowRunner().run(str(wf), {}, RunnerConfig())
    assert full.success, [d.message for d in full.diagnostics]
    full.trace.save_to_file()
    assert sentinel.read_text().count("ran") == 1

    # Planner verdict: single entry, target 'b' is a memo hit → cached.
    plan = WorkflowRunner().plan(str(wf), {}, RunnerConfig(only_node="b"))
    assert [e.node_id for e in plan.entries] == ["b"], "upstream/downstream must not be costed"
    assert plan.entries[0].status == "cached"

    # Engine behavior matches the verdict: b is served from cache, never re-run.
    result = WorkflowRunner().run(str(wf), {}, RunnerConfig(only_node="b"))
    assert result.success
    assert sentinel.read_text().count("ran") == 1, "cached --only target must not re-execute"


@pytest.mark.trace_files
def test_planner_execute_verdict_matches_engine_executing(tmp_path: Path) -> None:
    """For an uncached target, the planner says 'execute' AND the engine executes it.

    A shell target defaults to ``cache: false``, so under --only it always runs
    fresh against the restored upstream — and the planner reports it would
    execute. This is the verdict-vs-behavior parity the drift guard protects.
    """
    sentinel = tmp_path / "target_ran.txt"
    ir = {
        "nodes": [
            {"id": "upstream", "type": "shell", "params": {"command": "printf up"}},
            {
                "id": "target",
                "type": "shell",
                "params": {"command": f"echo ran >> {sentinel}; printf 'got ${{upstream.stdout}}'"},
            },
        ],
        "edges": [{"from": "upstream", "to": "target"}],
    }
    wf = tmp_path / "execute-parity.pflow.md"
    write_workflow_file(ir, wf)

    full = WorkflowRunner().run(str(wf), {}, RunnerConfig())
    assert full.success, [d.message for d in full.diagnostics]
    full.trace.save_to_file()
    before = sentinel.read_text().count("ran")

    # Planner verdict: target would execute.
    plan = WorkflowRunner().plan(str(wf), {}, RunnerConfig(only_node="target"))
    assert [e.node_id for e in plan.entries] == ["target"]
    assert plan.entries[0].status == "execute"

    # Engine behavior matches: the target re-runs against restored upstream.
    result = WorkflowRunner().run(str(wf), {}, RunnerConfig(only_node="target"))
    assert result.success
    assert result.shared_after["target"]["stdout"] == "got up"
    assert sentinel.read_text().count("ran") == before + 1, "uncached --only target must execute"


# ---------------------------------------------------------------------------
# --only target that is itself a loop: / a sub-workflow (high-churn boundaries)
# ---------------------------------------------------------------------------


def test_only_loop_target_runs_one_iteration() -> None:
    """An --only target that is a `loop:` node runs exactly ONE iteration.

    The snapshot path executes the target once inside `loop_runtime_scope`
    (iteration=1, `__loop_active__` raised) and never re-enters — so a loop
    target is tuned for a single pass, not run to completion. Regression guard
    for the ADR's "a loop target runs one iteration" claim.
    """
    upstream = _SpyNode()
    upstream.node_id = "upstream"
    upstream.set_params({"_calls": []})

    loop_target = _SpyNode()
    loop_target.node_id = "loopnode"
    loop_target.set_params({"_calls": []})

    upstream >> loop_target

    loop_cfg = NodeConfig(
        node_id="loopnode",
        node_type_name="SpyNode",
        template_config=None,
        batch_config=None,
        namespaced=True,
        interface_metadata=None,
        loop_config=LoopConfig(while_template="${loopnode.keep}", max_iterations=3),
    )
    workflow = CompiledWorkflow(
        start_node=upstream,
        node_configs={"upstream": _config("upstream"), "loopnode": loop_cfg},
    )
    shared: dict[str, Any] = {}
    engine = WorkflowEngine(
        only_node="loopnode",
        snapshot_events=[{"node_id": "upstream", "node_output": {"out": "restored"}}],
    )
    engine.run(workflow, shared)

    # Exactly one iteration; upstream restored, never executed.
    assert loop_target.params["_calls"] == ["loopnode"]
    assert upstream.params["_calls"] == []
    assert shared["__execution__"]["restored_nodes"] == ["upstream"]
    # The per-iteration marker is cleaned up (clear_iteration_on_exit=True).
    assert "__iteration__" not in shared
    # __loop_active__ was raised during the run → the memo read is suppressed
    # (a loop body re-executes each iteration; it must not memo-hit under --only).
    assert loop_target.params["_loop_active_in_post"] >= 1


@pytest.mark.trace_files
def test_only_subworkflow_target_reruns_whole_child(tmp_path: Path) -> None:
    """An --only target that is a top-level WorkflowExecutor reruns the WHOLE child fresh.

    Running that node fresh is the user's intent; the parent's upstream is
    restored (never re-fired), and the child workflow runs end-to-end against
    that frozen upstream. Regression guard for the ADR's top-level-sub-workflow
    claim, and proof the dormant `_pflow_child_only_node` plumbing can't fire.
    """
    parent_sentinel = tmp_path / "parent_pre.txt"
    child_sentinel = tmp_path / "child_ran.txt"

    child_ir = {
        "inputs": {"text": {"type": "string", "description": "Echoed text"}},
        "outputs": {"result": {"source": "${echo.stdout}", "description": "Echo result"}},
        "nodes": [
            {
                "id": "echo",
                "type": "shell",
                "purpose": "Echo the input and record that the child ran.",
                "params": {"command": f"echo ran >> {child_sentinel}; printf '%s' '${{text}}'"},
            },
        ],
    }
    child_path = tmp_path / "child.pflow.md"
    write_workflow_file(child_ir, child_path)

    parent_ir = {
        "nodes": [
            {
                "id": "pre",
                "type": "shell",
                "purpose": "Side-effecting parent upstream that must NOT re-fire.",
                "params": {"command": f"echo ran >> {parent_sentinel}; printf preval"},
            },
            {
                "id": "sub",
                "type": "workflow",
                "purpose": "Nested sub-workflow target.",
                "params": {"workflow": str(child_path), "inputs": {"text": "${pre.stdout}"}},
            },
            {
                "id": "post",
                "type": "shell",
                "purpose": "Downstream node.",
                "params": {"command": "printf done"},
            },
        ],
        "edges": [{"from": "pre", "to": "sub"}, {"from": "sub", "to": "post"}],
    }
    parent_path = tmp_path / "parent.pflow.md"
    write_workflow_file(parent_ir, parent_path)

    full = WorkflowRunner().run(str(parent_path), {}, RunnerConfig())
    assert full.success, [d.message for d in full.diagnostics]
    full.trace.save_to_file()
    assert parent_sentinel.read_text().count("ran") == 1
    assert child_sentinel.read_text().count("ran") == 1

    # --only sub: parent upstream restored, the whole child reruns fresh.
    result = WorkflowRunner().run(str(parent_path), {}, RunnerConfig(only_node="sub"))
    assert result.success, [d.message for d in result.diagnostics]
    assert parent_sentinel.read_text().count("ran") == 1, "parent upstream must NOT re-fire"
    assert child_sentinel.read_text().count("ran") == 2, "sub-workflow target must rerun the whole child"
    # The child ran against the RESTORED parent output.
    assert result.shared_after["sub"]["result"] == "preval"
    restored = result.shared_after["__execution__"]["restored_nodes"]
    assert "pre" in restored and "post" in restored and "sub" not in restored
    assert "_pflow_child_only_node" not in result.shared_after


@pytest.mark.trace_files
def test_real_degraded_batch_snapshot_warns_in_run_and_plan(tmp_path: Path) -> None:
    """End-to-end producer→consumer: a REAL degraded batch drives the loud advisory.

    A `error_handling: continue` batch that drops a failed item produces a real
    WARNING-degraded trace (not a synthetic fixture). Restoring from it under
    --only must: (a) flip the run DEGRADED with the loud advisory, AND (b) surface
    the same `only.snapshot-degraded` WARNING in the dry-run plan — so the
    "preview before you run" surface isn't silent where the real run warns.
    """
    ir = {
        "nodes": [
            {
                "id": "fetch",
                "type": "shell",
                "purpose": "Batch that fails one item; continue drops it and degrades the run.",
                "params": {"command": "test '${item}' != 'FAIL'"},
                "batch": {"items": ["ok1", "ok2", "FAIL"], "error_handling": "continue", "parallel": False},
            },
            {
                "id": "summarize",
                "type": "shell",
                "purpose": "Downstream node restored under --only.",
                "params": {"command": "printf 'count=${fetch.count}'"},
            },
        ],
        "edges": [{"from": "fetch", "to": "summarize"}],
    }
    wf = tmp_path / "degraded-batch.pflow.md"
    write_workflow_file(ir, wf)

    # Full run: one item fails + continue → DEGRADED, real WARNING in the trace.
    full = WorkflowRunner().run(str(wf), {}, RunnerConfig())
    assert full.success  # degraded is still a (warning-carrying) success
    assert full.status == WorkflowStatus.DEGRADED
    full.trace.save_to_file()

    # (a) dry-run plan surfaces the degraded-snapshot advisory (engine/planner parity).
    plan = WorkflowRunner().plan(str(wf), {}, RunnerConfig(only_node="summarize"))
    assert any(d.id == "only.snapshot-degraded" for d in plan.diagnostics), (
        f"dry-run --only must warn on a degraded snapshot; got {[d.id for d in plan.diagnostics]}"
    )

    # (b) the real --only run flips DEGRADED with the loud advisory.
    result = WorkflowRunner().run(str(wf), {}, RunnerConfig(only_node="summarize"))
    assert result.success
    assert result.status == WorkflowStatus.DEGRADED
    assert any(d.id == "only.snapshot-degraded" for d in result.diagnostics)
