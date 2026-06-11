"""Tests for dotted --only paths under snapshot semantics (issue #443).

Snapshot ``--only`` runs a FLAT target against a frozen prior-run snapshot.
Targeting a node INSIDE a sub-workflow (``--only parent.child``) is DEFERRED to
a future name-based "run-anywhere" model, so it is rejected with a clear
"not supported" error rather than re-walking the graph.

Covers:
  1. ``parse_only_path`` pure-function unit tests (still splits dotted paths)
  2. Engine validation: unknown node → "not found"; dotted target → "not supported"
  3. Cross-entry parity: ``WorkflowRunner.run`` and ``.plan`` reject dotted
     identically
  4. Flat --only regression (snapshot-seeded)
"""

from pathlib import Path
from typing import Any

import pytest

from pflow.core.exceptions import CompilationError
from pflow.core.node import BaseNode
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.runtime.engine.engine import WorkflowEngine, parse_only_path, validate_only_target
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
# 1. parse_only_path unit tests (unchanged — the parser still splits dotted)
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

    def test_consecutive_dots_raises(self) -> None:
        """``a..b`` is caught early with the full original path in the error."""
        with pytest.raises(CompilationError, match="a\\.\\.b"):
            parse_only_path("a..b")


# ---------------------------------------------------------------------------
# 1b. validate_only_target unit tests (shared by engine._run_inner and the
#     planner's _build_plan_with_shared — one validation, two entry points)
# ---------------------------------------------------------------------------


class TestValidateOnlyTarget:
    """Direct tests for the shared parse-and-validate function."""

    @staticmethod
    def _workflow() -> CompiledWorkflow:
        node = _StubNode()
        node.node_id = "step-a"
        return CompiledWorkflow(
            start_node=node,
            node_configs={"step-a": _make_config("step-a"), "step-b": _make_config("step-b")},
        )

    def test_none_returns_none_pair_without_validating(self) -> None:
        assert validate_only_target(self._workflow(), None) == (None, None)

    def test_flat_valid_target(self) -> None:
        assert validate_only_target(self._workflow(), "step-a") == ("step-a", None)

    def test_unknown_id_raises_with_sorted_available_nodes(self) -> None:
        with pytest.raises(CompilationError, match="'typo' not found") as exc_info:
            validate_only_target(self._workflow(), "typo")
        assert exc_info.value.details["available_nodes"] == ["step-a", "step-b"]

    def test_dotted_on_real_node_raises_not_supported(self) -> None:
        with pytest.raises(CompilationError, match="not supported"):
            validate_only_target(self._workflow(), "step-a.child")

    def test_membership_first_ordering_for_dotted_typo(self) -> None:
        """``typo.child`` reports 'not found', NOT 'not supported'."""
        with pytest.raises(CompilationError, match="not found"):
            validate_only_target(self._workflow(), "typo.child")

    def test_empty_string_raises(self) -> None:
        """``--only ""`` is a hard error — never a silent full run.

        Pins the unified loud-error semantics (the engine previously fell
        through to a full walk on empty string; the planner raised).
        """
        with pytest.raises(CompilationError, match="'' not found"):
            validate_only_target(self._workflow(), "")


# ---------------------------------------------------------------------------
# 2. Engine validation tests
# ---------------------------------------------------------------------------


class TestEngineOnlyValidation:
    """Engine.run() validates --only targets before execution starts."""

    def test_dotted_path_nonexistent_first_segment_raises(self) -> None:
        """Membership-first ordering: an unknown first segment still says 'not found'."""
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

    def test_dotted_path_rejected_as_not_supported(self) -> None:
        """A dotted path on a REAL node is rejected as 'not supported' (deferred feature)."""
        node = _StubNode()
        node.node_id = "step-a"

        workflow = CompiledWorkflow(
            start_node=node,
            node_configs={"step-a": _make_config("step-a", type_name="ShellNode")},
        )
        shared: dict[str, Any] = {}
        engine = WorkflowEngine(only_node="step-a.child")

        with pytest.raises(CompilationError, match="not supported"):
            engine.run(workflow, shared)

    def test_flat_only_still_works_regression(self) -> None:
        """Flat --only (no dots) runs the target against a seeded snapshot."""
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
        engine = WorkflowEngine(
            only_node="first",
            # Snapshot restores 'second' (downstream); only 'first' executes.
            snapshot_events=[{"node_id": "second", "node_output": {"stdout": "restored"}}],
        )
        engine.run(workflow, shared)

        assert shared["_executed"] == ["first"]
        assert shared["__execution__"]["only_node"] == "first"
        assert shared["__execution__"]["restored_nodes"] == ["second"]


# ---------------------------------------------------------------------------
# 3. Cross-entry dotted rejection parity (run AND plan)
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


class TestDottedOnlyRejected:
    """Dotted --only is rejected identically through run() and plan() (deferred feature)."""

    def test_dotted_only_rejected_via_run(self, tmp_path: Path) -> None:
        """Targeting a node inside a sub-workflow surfaces a 'not supported' error."""
        child_path = _write_child_workflow(tmp_path)
        parent_path = _write_parent_workflow(tmp_path, child_path)

        result = WorkflowRunner().run(str(parent_path), {}, RunnerConfig(only_node="step-b.child-first"))

        assert not result.success
        messages = " ".join(d.message for d in result.diagnostics)
        assert "not supported" in messages
        # No node executed — the workflow was rejected before any side effect.
        assert "step-a" not in result.shared_after
        assert "step-b" not in result.shared_after

    def test_dotted_only_rejected_via_plan(self, tmp_path: Path) -> None:
        """plan() raises the same CompilationError category for a dotted target."""
        child_path = _write_child_workflow(tmp_path)
        parent_path = _write_parent_workflow(tmp_path, child_path)

        with pytest.raises(CompilationError, match="not supported"):
            WorkflowRunner().plan(str(parent_path), {}, RunnerConfig(only_node="step-b.child-first"))

    def test_dotted_only_on_shell_node_rejected_via_plan(self, tmp_path: Path) -> None:
        """A dotted path on a non-sub-workflow node is also rejected (not supported)."""
        child_path = _write_child_workflow(tmp_path)
        parent_path = _write_parent_workflow(tmp_path, child_path)

        with pytest.raises(CompilationError, match="not supported"):
            WorkflowRunner().plan(str(parent_path), {}, RunnerConfig(only_node="step-a.foo"))

    def test_dotted_typo_first_segment_still_not_found_via_plan(self, tmp_path: Path) -> None:
        """Membership-first ordering preserved through plan(): unknown segment → 'not found'."""
        child_path = _write_child_workflow(tmp_path)
        parent_path = _write_parent_workflow(tmp_path, child_path)

        with pytest.raises(CompilationError, match="not found"):
            WorkflowRunner().plan(str(parent_path), {}, RunnerConfig(only_node="nonexistent.child"))
