"""Drift-catcher tests for plan vs real execution outcomes."""

from __future__ import annotations

from pathlib import Path

from pflow.execution.plan import build_plan
from pflow.registry import Registry
from pflow.runtime import WorkflowEngine, compile_workflow
from pflow.runtime.cache import MemoizationCache


def _compile(ir: dict, params: dict | None = None):
    registry = Registry()
    compiled = compile_workflow(ir, registry=registry, initial_params=params or {})
    return compiled, registry


def _run(compiled, cache: MemoizationCache, params: dict | None = None) -> dict:
    shared = dict(params or {})
    shared.update(compiled.resolved_defaults)
    shared["__memoization_cache__"] = cache
    WorkflowEngine().run(compiled, shared)
    return shared


def _log_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def test_plan_matches_execution_for_fresh_workflow(tmp_path) -> None:
    """Fresh plan predicts execute, and the workflow actually executes."""
    log_file = tmp_path / "exec.log"
    ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": f"echo a >> {log_file}; printf a"}},
            {"id": "b", "type": "shell", "params": {"command": f"echo b >> {log_file}; printf b"}},
        ],
        "edges": [{"from": "a", "to": "b"}],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    plan = build_plan(compiled, {}, cache, registry, workflow_name="fresh")
    _run(compiled, cache)

    assert [entry.status for entry in plan.entries] == ["execute", "execute"]
    assert _log_lines(log_file) == ["a", "b"]


def test_plan_matches_execution_after_first_run(tmp_path) -> None:
    """After a full run, the plan predicts cached and a second run does no work."""
    log_file = tmp_path / "exec.log"
    ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": f"echo a >> {log_file}; printf a"}},
            {"id": "b", "type": "shell", "params": {"command": f"echo b >> {log_file}; printf b"}},
        ],
        "edges": [{"from": "a", "to": "b"}],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    _run(compiled, cache)
    first_lines = _log_lines(log_file)
    plan = build_plan(compiled, {}, cache, registry, workflow_name="cached")
    _run(compiled, cache)

    assert all(entry.status == "cached" for entry in plan.entries)
    assert _log_lines(log_file) == first_lines


def test_plan_cross_node_template_resolution(tmp_path) -> None:
    """Cached upstream outputs must be visible so downstream cache keys match."""
    ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": "printf cached-value"}},
            {"id": "b", "type": "shell", "params": {"command": "printf ${a.stdout}"}},
        ],
        "edges": [{"from": "a", "to": "b"}],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    _run(compiled, cache)
    plan = build_plan(compiled, {}, cache, registry, workflow_name="template")

    assert [entry.status for entry in plan.entries] == ["cached", "cached"]
