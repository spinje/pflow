"""Drift-catcher tests for plan vs real execution outcomes."""

from __future__ import annotations

from pathlib import Path

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


def _runner_plan(path: Path, params: dict | None = None):
    return WorkflowRunner().plan(str(path), params or {}, RunnerConfig())


def _runner_run(path: Path, params: dict | None = None):
    return WorkflowRunner().run(str(path), params or {}, RunnerConfig())


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


def test_plan_matches_execution_after_config_edit(tmp_path) -> None:
    """Config edit produces cached prefix and executed suffix that match the plan."""
    log_file = tmp_path / "edit.log"
    old_ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": f"echo a >> {log_file}; printf a"}},
            {"id": "b", "type": "shell", "params": {"command": f"echo b >> {log_file}; printf '${{a.stdout}}-b'"}},
            {"id": "c", "type": "shell", "params": {"command": f"echo c >> {log_file}; printf '${{b.stdout}}-c'"}},
        ],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
    }
    new_ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": f"echo a >> {log_file}; printf a"}},
            {"id": "b", "type": "shell", "params": {"command": f"echo b2 >> {log_file}; printf '${{a.stdout}}-b2'"}},
            {"id": "c", "type": "shell", "params": {"command": f"echo c >> {log_file}; printf '${{b.stdout}}-c'"}},
        ],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
    }
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    compiled_old, _registry_old = _compile(old_ir)
    _run(compiled_old, cache)

    compiled_new, registry_new = _compile(new_ir)
    plan = build_plan(compiled_new, {}, cache, registry_new, workflow_name="edited")
    _run(compiled_new, cache)

    assert [entry.status for entry in plan.entries] == ["cached", "execute", "execute"]
    assert _log_lines(log_file) == ["a", "b", "c", "b2", "c"]


def test_plan_matches_execution_with_conditional_branch(tmp_path) -> None:
    """Cached routing action must follow the same branch in plan and execution."""
    log_file = tmp_path / "branch.log"
    ir = {
        "nodes": [
            {
                "id": "router",
                "type": "code",
                "params": {"code": 'next: str = "fast-path"\nresult: str = "routed"'},
            },
            {
                "id": "fast-path",
                "type": "shell",
                "params": {"command": f"echo fast >> {log_file}; printf fast"},
            },
            {
                "id": "slow-path",
                "type": "shell",
                "params": {"command": f"echo slow >> {log_file}; printf slow"},
            },
        ],
        "edges": [
            {"from": "router", "to": "fast-path", "action": "fast-path"},
            {"from": "router", "to": "slow-path", "action": "slow-path"},
        ],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    _run(compiled, cache)
    first_lines = _log_lines(log_file)
    plan = build_plan(compiled, {}, cache, registry, workflow_name="branch")
    _run(compiled, cache)

    assert [entry.node_id for entry in plan.entries] == ["router", "fast-path"]
    assert all(entry.status == "cached" for entry in plan.entries)
    assert _log_lines(log_file) == first_lines


def test_plan_sub_workflow_partial_cache_matches(tmp_path) -> None:
    """Child cache boundary propagates to the parent plan and parent downstream work."""
    log_file = tmp_path / "sub.log"
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "child-a",
                    "type": "shell",
                    "params": {"command": f"echo child-a >> {log_file}; printf child-a"},
                },
                {
                    "id": "child-b",
                    "type": "shell",
                    "params": {"command": f"echo child-b >> {log_file}; printf '${{child-a.stdout}}-child-b'"},
                },
            ],
            "edges": [{"from": "child-a", "to": "child-b"}],
            "outputs": {"out": {"source": "${child-b.stdout}", "description": "child output"}},
        },
        child_path,
    )
    write_workflow_file(
        {
            "nodes": [
                {"id": "pre", "type": "shell", "params": {"command": f"echo pre >> {log_file}; printf pre"}},
                {
                    "id": "call-child",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {}},
                },
                {
                    "id": "post",
                    "type": "shell",
                    "params": {"command": f"echo post >> {log_file}; printf '${{call-child.out}}-post'"},
                },
            ],
            "edges": [{"from": "pre", "to": "call-child"}, {"from": "call-child", "to": "post"}],
        },
        parent_path,
    )

    first_result = _runner_run(parent_path)
    assert first_result.success

    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "child-a",
                    "type": "shell",
                    "params": {"command": f"echo child-a >> {log_file}; printf child-a"},
                },
                {
                    "id": "child-b",
                    "type": "shell",
                    "params": {"command": f"echo child-b2 >> {log_file}; printf '${{child-a.stdout}}-child-b2'"},
                },
            ],
            "edges": [{"from": "child-a", "to": "child-b"}],
            "outputs": {"out": {"source": "${child-b.stdout}", "description": "child output"}},
        },
        child_path,
    )

    plan = _runner_plan(parent_path)
    second_result = _runner_run(parent_path)
    assert second_result.success

    assert [entry.status for entry in plan.entries] == ["cached", "sub_workflow", "execute"]
    assert plan.entries[2].cause == "downstream"
    assert plan.entries[1].sub_plan is not None
    assert [entry.status for entry in plan.entries[1].sub_plan.entries] == ["cached", "execute"]
    assert _log_lines(log_file) == ["pre", "child-a", "child-b", "post", "child-b2", "post"]


def test_plan_batch_items_cache_matches(tmp_path) -> None:
    """Batch node cache prediction matches a second execution with no extra work."""
    log_file = tmp_path / "batch.log"
    ir = {
        "nodes": [
            {
                "id": "source",
                "type": "code",
                "params": {"code": 'result: list[str] = ["a", "b"]'},
            },
            {
                "id": "batch",
                "type": "shell",
                "params": {"command": f"echo ${{item}} >> {log_file}; printf '${{item}}'"},
                "batch": {"items": "${source.result}"},
            },
        ],
        "edges": [{"from": "source", "to": "batch"}],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    _run(compiled, cache)
    first_lines = _log_lines(log_file)
    plan = build_plan(compiled, {}, cache, registry, workflow_name="batch")
    _run(compiled, cache)

    assert [entry.status for entry in plan.entries] == ["cached", "cached"]
    assert _log_lines(log_file) == first_lines


def test_plan_cache_false_always_executes(tmp_path) -> None:
    """Nodes with cache:false must re-execute regardless of previous runs."""
    log_file = tmp_path / "cache-false.log"
    ir = {
        "nodes": [
            {
                "id": "uncached",
                "type": "shell",
                "cache": False,
                "params": {"command": f"echo uncached >> {log_file}; printf uncached"},
            },
        ],
        "edges": [],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    _run(compiled, cache)
    plan = build_plan(compiled, {}, cache, registry, workflow_name="cache-false")
    _run(compiled, cache)

    assert len(plan.entries) == 1
    assert plan.entries[0].status == "execute"
    assert plan.entries[0].cause == "cache_disabled"
    assert _log_lines(log_file) == ["uncached", "uncached"]


def test_plan_bfs_post_boundary_enumerates_branches(tmp_path) -> None:
    """After the first boundary, planner enumerates all non-error branches."""
    ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": "printf a"}},
            {
                "id": "router",
                "type": "code",
                "params": {"code": 'next: str = "left"\nresult: str = "branch"'},
            },
            {"id": "left", "type": "shell", "params": {"command": "printf left"}},
            {"id": "right", "type": "shell", "params": {"command": "printf right"}},
        ],
        "edges": [
            {"from": "a", "to": "router"},
            {"from": "router", "to": "left", "action": "left"},
            {"from": "router", "to": "right", "action": "right"},
        ],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    plan = build_plan(compiled, {}, cache, registry, workflow_name="bfs")

    assert len(plan.entries) == 4
    assert plan.summary.cost_basis == "upper_bound"
    assert {entry.node_id for entry in plan.entries} == {"a", "router", "left", "right"}


def test_plan_routing_error_on_missing_successor(tmp_path) -> None:
    """Cached action with no matching successor becomes routing_error in the plan."""
    old_ir = {
        "nodes": [
            {
                "id": "router",
                "type": "code",
                "params": {"code": 'next: str = "approve"\nresult: str = "ok"'},
            },
            {"id": "approved", "type": "shell", "params": {"command": "printf approved"}},
        ],
        "edges": [{"from": "router", "to": "approved", "action": "approve"}],
    }
    new_ir = {
        "nodes": [
            {
                "id": "router",
                "type": "code",
                "params": {"code": 'next: str = "approve"\nresult: str = "ok"'},
            },
            {"id": "fallback", "type": "shell", "params": {"command": "printf fallback"}},
        ],
        "edges": [{"from": "router", "to": "fallback"}],
    }
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    compiled_old, _registry_old = _compile(old_ir)
    _run(compiled_old, cache)

    compiled_new, registry_new = _compile(new_ir)
    plan = build_plan(compiled_new, {}, cache, registry_new, workflow_name="routing")
    shared = _run(compiled_new, cache)

    assert any(entry.status == "routing_error" for entry in plan.entries)
    assert shared["__execution__"]["failed_node"] == "router"


def test_plan_cost_nested_rollup(tmp_path) -> None:
    """Nested LLM cost must roll up into parent's _including_nested fields.

    Pins the agent-facing cost-gate contract: an agent reading
    `summary.estimated_cost_usd` sees only top-level LLM cost, while
    `summary.estimated_cost_usd_including_nested` sees the full plan tree.
    A refactor that silently double-counts or drops the nested rollup
    would directly break cost-gating scripts.
    """
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    # Child: a single LLM. Editing its prompt invalidates its own cache key
    # directly, so it becomes the first miss at plan time — exactly the
    # scenario agents hit when iterating on an LLM-heavy workflow.
    def _write_child(prompt_text: str) -> None:
        write_workflow_file(
            {
                "nodes": [
                    {
                        "id": "think",
                        "type": "llm",
                        "params": {"prompt": prompt_text, "model": "gpt-4o-mini"},
                    },
                ],
                "edges": [],
                "outputs": {"out": {"source": "${think.response}", "description": "llm output"}},
            },
            child_path,
        )

    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "call-child",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {}},
                },
            ],
            "edges": [],
        },
        parent_path,
    )

    _write_child("Consider alpha")
    first = _runner_run(parent_path)
    assert first.success

    # Edit the prompt so the LLM's cache key changes; historical cost
    # from the first run stays in the cache under its original key.
    _write_child("Consider beta")
    plan = _runner_plan(parent_path)
    second = _runner_run(parent_path)
    assert second.success

    # Top level: 1 sub-workflow entry, no LLM directly at the parent level.
    assert len(plan.entries) == 1
    assert plan.entries[0].status == "sub_workflow"
    assert plan.summary.estimated_cost_usd == 0.0
    assert plan.summary.nodes_without_history == 0

    # Child plan: the LLM is the first miss → `_miss_entry` attaches its
    # historical cost via `_lookup_last_cost(config, cache)`.
    child_plan = plan.entries[0].sub_plan
    assert child_plan is not None
    llm_entries = [e for e in child_plan.entries if e.node_type == "LLMNode"]
    assert len(llm_entries) == 1
    assert llm_entries[0].status == "execute"
    assert llm_entries[0].cause == "no_cache_match"
    assert llm_entries[0].last_cost_usd is not None
    assert llm_entries[0].last_cost_usd > 0

    # Nested rollup: parent's _including_nested must equal the child's total.
    nested_cost = plan.summary.estimated_cost_usd_including_nested
    assert nested_cost is not None
    assert nested_cost == child_plan.summary.estimated_cost_usd
    assert nested_cost > 0


def test_plan_cost_basis_propagates_upper_bound(tmp_path) -> None:
    """Branching inside a child plan must flip the parent's summary.cost_basis.

    Agents treat `cost_basis == "exact"` as trustworthy. If a refactor
    stops propagating `upper_bound` from nested plans to the parent,
    agents would trust an overestimate-risk number as exact.
    """
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    # Child fans out on the first node. A fresh plan hits the router as a
    # miss, BFS enumerates BOTH branches, and the child summary flips to
    # cost_basis="upper_bound". Written as raw markdown because the test
    # needs explicit `- next:` directives on branch targets, which
    # ir_to_markdown doesn't emit.
    child_path.write_text(
        """# Branching Child

## Steps

### router

Pick a branch via the code node's `next` variable.

- type: code

```python code
next: str = "left"
result: str = "routed"
```

### left

Left branch target.

- type: shell
- next: end

```shell command
printf left
```

### right

Right branch target.

- type: shell
- next: end

```shell command
printf right
```
""",
        encoding="utf-8",
    )

    # Parent is strictly linear — its own walk cannot flip cost_basis.
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "call-child",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {}},
                },
            ],
            "edges": [],
        },
        parent_path,
    )

    plan = _runner_plan(parent_path)

    child_plan = plan.entries[0].sub_plan
    assert child_plan is not None
    assert child_plan.summary.cost_basis == "upper_bound"

    # Parent is linear, but its rollup must reflect the child's uncertainty.
    assert plan.summary.cost_basis == "upper_bound"
