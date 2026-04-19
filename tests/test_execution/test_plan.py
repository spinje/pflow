"""Integration tests for execution.plan.build_plan()."""

from __future__ import annotations

from pflow.execution.plan import build_plan
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.registry import Registry
from pflow.runtime import WorkflowEngine, compile_workflow
from pflow.runtime.cache import MemoizationCache
from tests.shared.markdown_utils import write_workflow_file


def _compile(ir: dict, params: dict | None = None):
    registry = Registry()
    compiled = compile_workflow(ir, registry=registry, initial_params=params or {})
    return compiled, registry


def _run_compiled(compiled, cache: MemoizationCache, params: dict | None = None) -> None:
    shared = dict(params or {})
    shared.update(compiled.resolved_defaults)
    shared["__memoization_cache__"] = cache
    WorkflowEngine().run(compiled, shared)


def test_build_plan_fresh_workflow_marks_all_execute(tmp_path) -> None:
    """Fresh workflow plans every node as execute/no_cache_match."""
    ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": "printf a"}},
            {"id": "b", "type": "shell", "params": {"command": "printf b"}},
        ],
        "edges": [{"from": "a", "to": "b"}],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    plan = build_plan(compiled, {}, cache, registry, workflow_name="fresh")

    assert [entry.status for entry in plan.entries] == ["execute", "execute"]
    assert plan.entries[0].cause == "no_cache_match"
    assert plan.entries[1].cause == "downstream"


def test_build_plan_fully_cached_workflow_marks_all_cached(tmp_path) -> None:
    """After a run, the same workflow plans as fully cached."""
    ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": "printf a"}},
            {"id": "b", "type": "shell", "params": {"command": "printf b"}},
        ],
        "edges": [{"from": "a", "to": "b"}],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    _run_compiled(compiled, cache)

    plan = build_plan(compiled, {}, cache, registry, workflow_name="cached")

    assert all(entry.status == "cached" for entry in plan.entries)
    assert plan.summary.cache_boundary is None


def test_build_plan_cache_false_node_always_executes(tmp_path) -> None:
    """Nodes with cache: false always show execute/cache_disabled."""
    ir = {
        "nodes": [
            {"id": "a", "type": "shell", "cache": False, "params": {"command": "printf a"}},
        ],
        "edges": [],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    _run_compiled(compiled, cache)

    plan = build_plan(compiled, {}, cache, registry, workflow_name="cache-false")

    assert len(plan.entries) == 1
    assert plan.entries[0].status == "execute"
    assert plan.entries[0].cause == "cache_disabled"


def test_build_plan_marks_dynamic_subworkflow_opaque(tmp_path) -> None:
    """workflow: ${var} renders as opaque instead of template_error."""
    workflow_path = tmp_path / "parent.pflow.md"
    write_workflow_file(
        {
            "inputs": {"child_ref": {"type": "string", "description": "Child workflow ref"}},
            "nodes": [
                {
                    "id": "child",
                    "type": "workflow",
                    "params": {"workflow": "${child_ref}", "inputs": {}},
                }
            ],
            "edges": [],
        },
        workflow_path,
    )

    plan = WorkflowRunner().plan(str(workflow_path), {"child_ref": "./child.pflow.md"}, RunnerConfig())

    assert len(plan.entries) == 1
    assert plan.entries[0].status == "opaque"
    assert plan.entries[0].cause == "dynamic"
