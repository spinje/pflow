"""Tests for dotted-path --only feature (GH #338).

``--only step-b.child-first`` targets a node inside a sub-workflow:
the engine executes the parent up to ``step-b``, and the child workflow
inside ``step-b`` runs only up to ``child-first``.

Covers:
  1. ``parse_only_path`` pure-function unit tests
  2. Engine validation (node not found, not a sub-workflow)
  3. Engine + WorkflowExecutor integration (child-level targeting)
  4. Planner integration (``build_plan`` with dotted paths)
  5. Cleanup of ``_pflow_child_only_node`` key
"""

from pathlib import Path
from typing import Any

import pytest

from pflow.core.exceptions import CompilationError
from pflow.core.node import BaseNode
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.runtime.engine.engine import WorkflowEngine, parse_only_path
from pflow.runtime.engine.types import CompiledWorkflow, NodeConfig
from tests.shared.markdown_utils import write_workflow_file

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _StubNode(BaseNode):
    """Minimal node that writes its node_id to shared for execution tracking."""

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared.setdefault("_executed", []).append(self.node_id)
        shared["stdout"] = f"output-from-{self.node_id}"
        return "default"


def _make_config(node_id: str, type_name: str = "StubNode") -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        node_type_name=type_name,
        template_config=None,
        batch_config=None,
        namespaced=False,
        interface_metadata=None,
    )


# ---------------------------------------------------------------------------
# 1. parse_only_path unit tests
# ---------------------------------------------------------------------------


class TestParseOnlyPath:
    """Pure-function tests for the path parser."""

    def test_none_returns_none_pair(self) -> None:
        assert parse_only_path(None) == (None, None)

    def test_simple_name_no_dot(self) -> None:
        assert parse_only_path("step-a") == ("step-a", None)

    def test_two_segments(self) -> None:
        assert parse_only_path("step-a.child-first") == ("step-a", "child-first")

    def test_multi_level_preserves_remaining(self) -> None:
        """``a.b.c`` splits as ``('a', 'b.c')`` — remaining is still dotted."""
        assert parse_only_path("a.b.c") == ("a", "b.c")

    def test_empty_string_no_dot(self) -> None:
        """Edge case: empty string has no dot, so it returns as-is."""
        assert parse_only_path("") == ("", None)

    def test_trailing_dot_raises(self) -> None:
        with pytest.raises(CompilationError, match="empty segment"):
            parse_only_path("step-a.")

    def test_leading_dot_raises(self) -> None:
        with pytest.raises(CompilationError, match="empty segment"):
            parse_only_path(".child-first")

    def test_single_dot_raises(self) -> None:
        with pytest.raises(CompilationError, match="empty segment"):
            parse_only_path(".")


# ---------------------------------------------------------------------------
# 2. Engine validation tests
# ---------------------------------------------------------------------------


class TestEngineOnlyValidation:
    """Engine.run() validates --only targets before execution starts."""

    def test_dotted_path_nonexistent_first_segment_raises(self) -> None:
        """Dotted path where the first segment doesn't exist in the workflow."""
        node = _StubNode()
        node.node_id = "step-a"

        workflow = CompiledWorkflow(
            start_node=node,
            node_configs={"step-a": _make_config("step-a")},
        )
        shared: dict[str, Any] = {}
        engine = WorkflowEngine(only_node="nonexistent.child")

        with pytest.raises(CompilationError, match="not found"):
            engine.run(workflow, shared)

    def test_dotted_path_on_non_workflow_node_raises(self) -> None:
        """Dotted path where first segment is a shell node, not a sub-workflow."""
        node = _StubNode()
        node.node_id = "step-a"

        workflow = CompiledWorkflow(
            start_node=node,
            node_configs={"step-a": _make_config("step-a", type_name="ShellNode")},
        )
        shared: dict[str, Any] = {}
        engine = WorkflowEngine(only_node="step-a.child")

        with pytest.raises(CompilationError, match="not a sub-workflow"):
            engine.run(workflow, shared)

    def test_flat_only_still_works_regression(self) -> None:
        """Flat --only (no dots) still stops after the target node."""
        node_a = _StubNode()
        node_a.node_id = "first"

        node_b = _StubNode()
        node_b.node_id = "second"

        node_a >> node_b

        workflow = CompiledWorkflow(
            start_node=node_a,
            node_configs={
                "first": _make_config("first"),
                "second": _make_config("second"),
            },
        )
        shared: dict[str, Any] = {}
        engine = WorkflowEngine(only_node="first")
        engine.run(workflow, shared)

        assert shared["_executed"] == ["first"]
        assert shared["__execution__"]["only_node"] == "first"


# ---------------------------------------------------------------------------
# 3. Engine + WorkflowExecutor integration tests
# ---------------------------------------------------------------------------


def _write_child_workflow(tmp_path: Path) -> Path:
    """Write a 2-step child workflow (child-first -> child-second)."""
    child_ir = {
        "nodes": [
            {"id": "child-first", "type": "shell", "params": {"command": "printf child-one"}},
            {"id": "child-second", "type": "shell", "params": {"command": "printf child-two"}},
        ],
        "edges": [{"from": "child-first", "to": "child-second"}],
    }
    child_path = tmp_path / "child.pflow.md"
    write_workflow_file(child_ir, child_path)
    return child_path


def _write_parent_workflow(tmp_path: Path, child_path: Path) -> Path:
    """Write a 3-step parent: step-a(shell) -> step-b(workflow) -> step-c(shell)."""
    parent_ir = {
        "nodes": [
            {"id": "step-a", "type": "shell", "params": {"command": "printf parent-a"}},
            {
                "id": "step-b",
                "type": "workflow",
                "params": {"workflow": str(child_path)},
            },
            {"id": "step-c", "type": "shell", "params": {"command": "printf parent-c"}},
        ],
        "edges": [
            {"from": "step-a", "to": "step-b"},
            {"from": "step-b", "to": "step-c"},
        ],
    }
    parent_path = tmp_path / "parent.pflow.md"
    write_workflow_file(parent_ir, parent_path)
    return parent_path


class TestDottedOnlyIntegration:
    """Full integration: parent workflow with a sub-workflow, using dotted --only."""

    def test_dotted_only_targets_child_node(self, tmp_path: Path) -> None:
        """``--only step-b.child-first`` executes step-a, step-b (child runs
        only child-first), and stops before step-c."""
        child_path = _write_child_workflow(tmp_path)
        parent_path = _write_parent_workflow(tmp_path, child_path)

        runner = WorkflowRunner()
        config = RunnerConfig(only_node="step-b.child-first")
        result = runner.run(str(parent_path), {}, config)

        shared = result.shared_after

        # step-a executed
        assert "step-a" in shared, "step-a should have executed"

        # step-b executed (sub-workflow node)
        assert "step-b" in shared, "step-b should have executed"

        # Inside child: child-first executed, child-second did NOT
        child_data = shared.get("step-b", {})
        assert "child-first" in child_data, "child-first inside step-b should have executed"
        assert "child-second" not in child_data, "child-second should NOT have executed (dotted --only)"

        # step-c did NOT execute
        assert "step-c" not in shared, "step-c should NOT have executed"

        # The full dotted path is recorded
        assert shared["__execution__"]["only_node"] == "step-b.child-first"

    def test_dotted_only_cleans_up_child_only_key(self, tmp_path: Path) -> None:
        """After engine stops, ``_pflow_child_only_node`` must NOT be in shared."""
        child_path = _write_child_workflow(tmp_path)
        parent_path = _write_parent_workflow(tmp_path, child_path)

        runner = WorkflowRunner()
        config = RunnerConfig(only_node="step-b.child-first")
        result = runner.run(str(parent_path), {}, config)

        assert "_pflow_child_only_node" not in result.shared_after


# ---------------------------------------------------------------------------
# 4. Planner integration tests
# ---------------------------------------------------------------------------


class TestDottedOnlyPlanner:
    """Planner (build_plan) respects dotted --only paths."""

    def test_plan_dotted_only_limits_child_entries_cached_parent(self, tmp_path: Path) -> None:
        """When the parent prefix is cached, ``build_plan(only_node='step-b.child-first')``
        produces a child sub-plan that stops at child-first.

        The planner threads ``child_only`` through the state-machine path
        (FOLLOW transitions for cached nodes).  We prime the cache first
        so step-a is cached and the walker reaches step-b via FOLLOW, not
        BFS downstream.
        """
        child_path = _write_child_workflow(tmp_path)
        parent_path = _write_parent_workflow(tmp_path, child_path)

        # Prime the memo cache so step-a is cached on the next plan
        WorkflowRunner().run(str(parent_path), {}, RunnerConfig())

        plan = WorkflowRunner().plan(str(parent_path), {}, RunnerConfig(only_node="step-b.child-first"))

        # Parent plan should have entries for step-a and step-b only
        parent_ids = [e.node_id for e in plan.entries]
        assert "step-a" in parent_ids
        assert "step-b" in parent_ids
        assert "step-c" not in parent_ids

        # step-b should have a sub_plan
        step_b_entry = next(e for e in plan.entries if e.node_id == "step-b")
        assert step_b_entry.sub_plan is not None

        # Child sub-plan should only include child-first, not child-second
        child_ids = [e.node_id for e in step_b_entry.sub_plan.entries]
        assert "child-first" in child_ids
        assert "child-second" not in child_ids

    def test_plan_dotted_only_bfs_path_limits_child_entries(self, tmp_path: Path) -> None:
        """When upstream is a cache miss, BFS fires — child sub-plan must still
        respect the dotted ``--only`` constraint.

        Uses ``MemoizationCache(read_enabled=False)`` so ALL nodes are misses.
        The first miss triggers BOUNDARY → BFS reaches step-b → must thread
        ``child_only_node`` to the child plan. Without the fix, BFS would show
        the full child workflow (child-first AND child-second).
        """
        child_path = _write_child_workflow(tmp_path)
        parent_path = _write_parent_workflow(tmp_path, child_path)

        plan = WorkflowRunner().plan(
            str(parent_path), {}, RunnerConfig(only_node="step-b.child-first", cache_enabled=False)
        )

        step_b_entry = next((e for e in plan.entries if e.node_id == "step-b"), None)
        assert step_b_entry is not None, "step-b should appear in plan"
        assert step_b_entry.sub_plan is not None, "step-b should have a sub_plan"

        child_ids = [e.node_id for e in step_b_entry.sub_plan.entries]
        assert "child-first" in child_ids
        assert "child-second" not in child_ids, (
            "BFS downstream must thread child_only_node — child-second should be excluded"
        )

    def test_plan_dotted_only_on_shell_node_raises(self, tmp_path: Path) -> None:
        """``build_plan(only_node='step-a.foo')`` where step-a is a shell node
        should raise CompilationError."""
        child_path = _write_child_workflow(tmp_path)
        parent_path = _write_parent_workflow(tmp_path, child_path)

        with pytest.raises(CompilationError, match="not a sub-workflow"):
            WorkflowRunner().plan(str(parent_path), {}, RunnerConfig(only_node="step-a.foo"))
