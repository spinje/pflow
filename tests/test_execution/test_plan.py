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


def _plan_workflow_file(path, params: dict | None = None, *, only_node: str | None = None):
    return WorkflowRunner().plan(str(path), params or {}, RunnerConfig(only_node=only_node))


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


def test_build_plan_partial_cache_after_config_edit_marks_boundary_and_downstream(tmp_path) -> None:
    """Editing a middle node produces cached prefix + execute boundary + downstream."""
    old_ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": "printf a"}},
            {"id": "b", "type": "shell", "params": {"command": "printf ${a.stdout}-b"}},
            {"id": "c", "type": "shell", "params": {"command": "printf ${b.stdout}-c"}},
        ],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
    }
    new_ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": "printf a"}},
            {"id": "b", "type": "shell", "params": {"command": "printf ${a.stdout}-b2"}},
            {"id": "c", "type": "shell", "params": {"command": "printf ${b.stdout}-c"}},
        ],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
    }
    compiled_old, registry = _compile(old_ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    _run_compiled(compiled_old, cache)

    compiled_new, _registry = _compile(new_ir)
    plan = build_plan(compiled_new, {}, cache, registry, workflow_name="edited")

    assert [entry.status for entry in plan.entries] == ["cached", "execute", "execute"]
    assert [entry.cause for entry in plan.entries] == ["hash_match", "no_cache_match", "downstream"]
    assert plan.summary.cache_boundary == "b"


def test_build_plan_recurses_into_subworkflow(tmp_path) -> None:
    """WorkflowExecutor entries contain a nested sub_plan."""
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "child-step", "type": "shell", "params": {"command": "printf child"}}],
            "edges": [],
        },
        child_path,
    )
    write_workflow_file(
        {
            "nodes": [
                {"id": "call-child", "type": "workflow", "params": {"workflow": str(child_path), "inputs": {}}},
            ],
            "edges": [],
        },
        parent_path,
    )

    plan = _plan_workflow_file(parent_path)

    assert len(plan.entries) == 1
    assert plan.entries[0].status == "sub_workflow"
    assert plan.entries[0].sub_plan is not None
    assert len(plan.entries[0].sub_plan.entries) == 1
    assert plan.summary.execute_count == 1


def test_build_plan_max_depth_guard_emits_diagnostic(tmp_path) -> None:
    """Deep sub-workflow recursion stops with a diagnostic instead of recursing forever."""
    depth = 12
    paths = [tmp_path / f"wf-{index}.pflow.md" for index in range(depth)]
    write_workflow_file(
        {"nodes": [{"id": "final", "type": "shell", "params": {"command": "printf final"}}], "edges": []},
        paths[-1],
    )
    for index in range(depth - 2, -1, -1):
        write_workflow_file(
            {
                "nodes": [
                    {
                        "id": f"call-{index}",
                        "type": "workflow",
                        "params": {"workflow": str(paths[index + 1]), "inputs": {}},
                    }
                ],
                "edges": [],
            },
            paths[index],
        )

    plan = _plan_workflow_file(paths[0])

    assert any("Max sub-workflow depth" in diagnostic.message for diagnostic in plan.diagnostics)


def test_build_plan_circular_subworkflow_emits_diagnostic(tmp_path) -> None:
    """Circular sub-workflow references are surfaced as diagnostics."""
    parent_path = tmp_path / "circular.pflow.md"
    write_workflow_file(
        {
            "nodes": [
                {"id": "self-call", "type": "workflow", "params": {"workflow": str(parent_path), "inputs": {}}},
            ],
            "edges": [],
        },
        parent_path,
    )

    plan = _plan_workflow_file(parent_path)

    assert any("Circular sub-workflow reference" in diagnostic.message for diagnostic in plan.diagnostics)


def test_build_plan_visited_edges_prevents_loop_hang(tmp_path) -> None:
    """A cyclic graph should produce a finite plan."""
    ir = {
        "nodes": [{"id": "loop", "type": "shell", "params": {"command": "printf loop"}}],
        "edges": [{"from": "loop", "to": "loop", "action": "error"}],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    plan = build_plan(compiled, {}, cache, registry, workflow_name="loop")

    assert len(plan.entries) == 1
