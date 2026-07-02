"""Drift-catcher tests for plan vs real execution outcomes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pflow.execution.formatters.plan_formatter import format_plan_text
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


def _engine_cost(result) -> float:
    """Engine-actual total LLM cost from a real run — the cost-parity oracle.

    Read from the trace's own accumulator (`collect_llm_calls` walks executed
    LLM leaves and excludes cached subtrees), a completely different code path
    from the planner's rollup. That independence is what makes a plan-vs-engine
    comparison a real cross-check rather than a tautology.
    """
    llm_calls = result.trace.collect_llm_calls()
    return result.metrics.get_summary(llm_calls)["total_cost_usd"]


def _plan_cost(plan) -> float:
    """Plan's agent-facing total predicted cost (the cost-gating field).

    Mirrors how an agent gates: prefer `estimated_cost_usd_including_nested`
    (the rollup over sub-workflows) and fall back to the flat
    `estimated_cost_usd` for workflows with no nesting.
    """
    summary = plan.summary
    if summary.estimated_cost_usd_including_nested is not None:
        return summary.estimated_cost_usd_including_nested
    return summary.estimated_cost_usd


def test_plan_matches_execution_for_fresh_workflow(tmp_path) -> None:
    """Fresh plan predicts execute, and the workflow actually executes."""
    log_file = tmp_path / "exec.log"
    ir = {
        "nodes": [
            {"id": "a", "type": "shell", "cache": True, "params": {"command": f"echo a >> {log_file}; printf a"}},
            {"id": "b", "type": "shell", "cache": True, "params": {"command": f"echo b >> {log_file}; printf b"}},
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
            {"id": "a", "type": "shell", "cache": True, "params": {"command": f"echo a >> {log_file}; printf a"}},
            {"id": "b", "type": "shell", "cache": True, "params": {"command": f"echo b >> {log_file}; printf b"}},
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
            {"id": "a", "type": "shell", "cache": True, "params": {"command": "printf cached-value"}},
            {"id": "b", "type": "shell", "cache": True, "params": {"command": "printf ${a.stdout}"}},
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
            {"id": "a", "type": "shell", "cache": True, "params": {"command": f"echo a >> {log_file}; printf a"}},
            {
                "id": "b",
                "type": "shell",
                "cache": True,
                "params": {"command": f"echo b >> {log_file}; printf '${{a.stdout}}-b'"},
            },
            {
                "id": "c",
                "type": "shell",
                "cache": True,
                "params": {"command": f"echo c >> {log_file}; printf '${{b.stdout}}-c'"},
            },
        ],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
    }
    new_ir = {
        "nodes": [
            {"id": "a", "type": "shell", "cache": True, "params": {"command": f"echo a >> {log_file}; printf a"}},
            {
                "id": "b",
                "type": "shell",
                "cache": True,
                "params": {"command": f"echo b2 >> {log_file}; printf '${{a.stdout}}-b2'"},
            },
            {
                "id": "c",
                "type": "shell",
                "cache": True,
                "params": {"command": f"echo c >> {log_file}; printf '${{b.stdout}}-c'"},
            },
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
                "cache": True,
                "params": {"code": 'next: str = "fast-path"\nresult: str = "routed"'},
            },
            {
                "id": "fast-path",
                "type": "shell",
                "cache": True,
                "params": {"command": f"echo fast >> {log_file}; printf fast"},
            },
            {
                "id": "slow-path",
                "type": "shell",
                "cache": True,
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
                    "cache": True,
                    "params": {"command": f"echo child-a >> {log_file}; printf child-a"},
                },
                {
                    "id": "child-b",
                    "type": "shell",
                    "cache": True,
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
                {
                    "id": "pre",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo pre >> {log_file}; printf pre"},
                },
                {
                    "id": "call-child",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {}},
                },
                {
                    "id": "post",
                    "type": "shell",
                    "cache": True,
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
                    "cache": True,
                    "params": {"command": f"echo child-a >> {log_file}; printf child-a"},
                },
                {
                    "id": "child-b",
                    "type": "shell",
                    "cache": True,
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
                "cache": True,
                "params": {"code": 'result: list[str] = ["a", "b"]'},
            },
            {
                "id": "batch",
                "type": "shell",
                "cache": True,
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


def test_plan_batch_sub_workflow_partial_cache_matches_execution(tmp_path) -> None:
    """Batch sub-workflow partial-cache prediction must match the next real run.

    Regression target for task 157's missing dispatch. Without the batch
    WorkflowExecutor planning path, `--dry-run` either reported the whole
    sub-workflow as uncached or failed to resolve `${item}` for the child
    input, while the real execution reused cached items correctly.

    Mutation: remove the `config.batch_config and not downstream` dispatch in
    `_plan_sub_workflow` → this assertion fails because the child sub-plan no
    longer reports `1/2` cache reuse.
    """
    log_file = tmp_path / "batch-sub.log"
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    write_workflow_file(
        {
            "inputs": {"value": {"type": "string"}},
            "nodes": [
                {
                    "id": "echo",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo ${{value}} >> {log_file}; printf '${{value}}'"},
                }
            ],
            "edges": [],
            "outputs": {"out": {"source": "${echo.stdout}", "description": "Echoed value"}},
        },
        child_path,
    )
    write_workflow_file(
        {
            "inputs": {"items": {"type": "array"}},
            "nodes": [
                {
                    "id": "fanout",
                    "type": "workflow",
                    "params": {
                        "workflow": str(child_path),
                        "inputs": {"value": "${item}"},
                    },
                    "batch": {"items": "${items}"},
                }
            ],
            "edges": [],
        },
        parent_path,
    )

    first_result = _runner_run(parent_path, {"items": ["a", "b"]})
    assert first_result.success

    plan = _runner_plan(parent_path, {"items": ["a", "c"]})
    second_result = _runner_run(parent_path, {"items": ["a", "c"]})
    assert second_result.success

    assert [entry.status for entry in plan.entries] == ["sub_workflow"]
    fanout = plan.entries[0]
    assert fanout.sub_plan is not None
    assert len(fanout.sub_plan.entries) == 1
    child_entry = fanout.sub_plan.entries[0]
    assert child_entry.status == "execute"
    assert child_entry.batch_items_cached == 1
    assert child_entry.batch_items_total == 2
    assert _log_lines(log_file) == ["a", "b", "c"]


def test_plan_batch_sub_workflow_preserves_child_approval_flag(tmp_path) -> None:
    """Code-review fix: a gated step inside a batched sub-workflow's child must
    still show `approval: true` in the aggregated dry-run entry.

    `_aggregate_batch_child_plans` builds a FRESH synthetic PlanEntry per
    node-id (collapsing per-item entries into one view) — it must forward
    `approval` from the per-item entries, or the dry-run footer/JSON silently
    omits a gate the engine still pauses on (or fails loudly on, non-
    interactively) at runtime — the resolver's namespace is flat across the
    whole workflow tree, so the child gate fires regardless of batching.

    Mutation: drop the `approval=...` kwarg from the synthetic PlanEntry in
    `_aggregate_batch_child_plans` → this assertion fails (defaults to False).
    """
    child_path = tmp_path / "gated-child.pflow.md"
    parent_path = tmp_path / "gated-parent.pflow.md"

    write_workflow_file(
        {
            "inputs": {"value": {"type": "string"}},
            "nodes": [
                {
                    "id": "gated-echo",
                    "type": "shell",
                    "params": {"command": "printf '${value}'"},
                    "approval": "required",
                }
            ],
            "edges": [],
            "outputs": {"out": {"source": "${gated-echo.stdout}", "description": "Echoed value"}},
        },
        child_path,
    )
    write_workflow_file(
        {
            "inputs": {"items": {"type": "array"}},
            "nodes": [
                {
                    "id": "fanout",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {"value": "${item}"}},
                    "batch": {"items": "${items}"},
                }
            ],
            "edges": [],
        },
        parent_path,
    )

    plan = _runner_plan(parent_path, {"items": ["a", "b"]})
    assert [entry.status for entry in plan.entries] == ["sub_workflow"]
    fanout = plan.entries[0]
    assert fanout.sub_plan is not None
    child_entry = next(e for e in fanout.sub_plan.entries if e.node_id == "gated-echo")
    assert child_entry.approval is True


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
            {"id": "a", "type": "shell", "cache": True, "params": {"command": "printf a"}},
            {
                "id": "router",
                "type": "code",
                "cache": True,
                "params": {"code": 'next: str = "left"\nresult: str = "branch"'},
            },
            {"id": "left", "type": "shell", "cache": True, "params": {"command": "printf left"}},
            {"id": "right", "type": "shell", "cache": True, "params": {"command": "printf right"}},
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
                "cache": True,
                "params": {"code": 'next: str = "approve"\nresult: str = "ok"'},
            },
            {"id": "approved", "type": "shell", "cache": True, "params": {"command": "printf approved"}},
        ],
        "edges": [{"from": "router", "to": "approved", "action": "approve"}],
    }
    new_ir = {
        "nodes": [
            {
                "id": "router",
                "type": "code",
                "cache": True,
                "params": {"code": 'next: str = "approve"\nresult: str = "ok"'},
            },
            {"id": "fallback", "type": "shell", "cache": True, "params": {"command": "printf fallback"}},
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


def test_plan_cost_nested_rollup(tmp_path, mock_llm_client) -> None:
    """Nested LLM cost must roll up into parent's _including_nested fields.

    Pins the agent-facing cost-gate contract: an agent reading
    `summary.estimated_cost_usd` sees only top-level LLM cost, while
    `summary.estimated_cost_usd_including_nested` sees the full plan tree.
    A refactor that silently double-counts or drops the nested rollup
    would directly break cost-gating scripts.

    The mock returns an explicit cost_usd (mirroring how the real adapter
    sets it from LiteLLM's response_cost) so the rollup has a concrete
    number to verify.
    """
    expected_cost = 0.000123
    mock_llm_client.set_response("gpt-4o-mini", None, {"response": "x"}, cost_usd=expected_cost)
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
    # historical cost via `_lookup_last_run_stats(config, cache)`.
    child_plan = plan.entries[0].sub_plan
    assert child_plan is not None
    llm_entries = [e for e in child_plan.entries if e.node_type == "LLMNode"]
    assert len(llm_entries) == 1
    assert llm_entries[0].status == "execute"
    assert llm_entries[0].cause == "no_cache_match"
    assert llm_entries[0].last_cost_usd == expected_cost

    # Nested rollup: parent's _including_nested must equal the child's total.
    nested_cost = plan.summary.estimated_cost_usd_including_nested
    assert nested_cost is not None
    assert nested_cost == child_plan.summary.estimated_cost_usd
    assert nested_cost == expected_cost


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
- cache: true

```python code
next: str = "left"
result: str = "routed"
```

### left

Left branch target.

- type: shell
- cache: true
- next: end

```shell command
printf left
```

### right

Right branch target.

- type: shell
- cache: true
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


def _seed_cache_entry(
    cache: MemoizationCache,
    compiled: Any,
    node_id: str,
    action: str,
    output: dict,
    duration_ms: float | None = None,
    shared_extras: dict | None = None,
) -> None:
    """Write a cache entry for `node_id` keyed exactly as `plan_node` derives it.

    Uses `plan_node` itself to compute the cache key — this is the only way
    to guarantee the seeded key matches what the planner will look up on its
    next call (otherwise resolved_params differ and the lookup misses).

    Pass `shared_extras` for nodes that reference inputs (e.g., batch's
    `items` template needs the array in shared to compute a batch cache key).

    Used by the visit_counts drift test to stage a cyclic-cache state the
    live engine can't produce (infinite loop) but the planner can walk.
    """
    from pflow.runtime.engine.plan_node import plan_node

    # Locate the node object in the compiled graph (breadth-first).
    target = None
    queue = [compiled.start_node]
    seen: set[str] = set()
    while queue:
        n = queue.pop(0)
        nid = getattr(n, "node_id", None)
        if not isinstance(nid, str) or nid in seen:
            continue
        seen.add(nid)
        if nid == node_id:
            target = n
            break
        queue.extend(n.successors.values())
    assert target is not None, f"node {node_id!r} not found in compiled graph"

    config = compiled.node_configs[node_id]
    shared: dict[str, Any] = {
        "__execution__": {"node_visit_counts": {}},
        "__memoization_cache__": cache,
    }
    if shared_extras:
        shared.update(shared_extras)
    planned = plan_node(target, config, shared)
    cache_key = planned.cache_key
    assert cache_key is not None, f"plan_node returned no cache_key for {node_id!r}"

    blob = dict(output)
    if duration_ms is not None:
        blob["__pflow_stats__"] = {"duration_ms": duration_ms}
    cache.put(cache_key, node_id, None, action, blob)


def test_plan_walker_bumps_visit_counts_before_plan_node(monkeypatch, tmp_path) -> None:
    """Walker must bump `node_visit_counts` BEFORE each `plan_node` call.

    Load-bearing invariant from `plan.py`'s module docstring. The walker
    calls the shared `enforce_loop_guard` primitive (same as the engine),
    which bumps visit_counts. Without the pre-bump, a node revisited after
    a cycle would still show `visit_counts[nid] == 1` on the second
    `plan_node` call, so `memo_cache_lookup`'s `visit_counts > 1` gate
    never trips — silent divergence from the engine.

    The observable effect can be masked by the in-process cache when inputs
    don't change between visits, so we pin the contract directly: on the
    walker's second visit to `a`, `plan_node` must see `visit_counts[a] == 2`.

    Mutation: remove the `enforce_loop_guard(node_id, shared)` call in
    `build_plan`'s main loop → the second recorded value stays at 0 and
    this assertion fails. (See also: `test_plan_cached_loop_visit_two_reports_execute`
    which pins the invalidation half of `enforce_loop_guard`.)
    """
    from pflow.execution import plan as plan_module

    ir = {
        "nodes": [
            {"id": "a", "type": "shell", "cache": True, "params": {"command": "echo a"}},
            {"id": "b", "type": "shell", "cache": True, "params": {"command": "echo b"}},
        ],
        "edges": [
            {"from": "a", "to": "b", "action": "go"},
            {"from": "b", "to": "a", "action": "back"},
        ],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    _seed_cache_entry(cache, compiled, "a", "go", {"stdout": "a", "exit_code": 0})
    _seed_cache_entry(cache, compiled, "b", "back", {"stdout": "b", "exit_code": 0})

    recorded: list[tuple[str, int]] = []
    real_plan_node = plan_module.plan_node

    def spy(node, config, shared):
        visit_counts = shared.get("__execution__", {}).get("node_visit_counts", {})
        recorded.append((config.node_id, visit_counts.get(config.node_id, 0)))
        return real_plan_node(node, config, shared)

    monkeypatch.setattr(plan_module, "plan_node", spy)

    build_plan(compiled, {}, cache, registry, workflow_name="cycle")

    # Walker visits: a → b → a (revisit, edge (b,"back") advanced us back).
    # Each call records the visit_counts state plan_node observed.
    assert recorded == [("a", 1), ("b", 1), ("a", 2)]


def test_plan_bfs_downstream_attaches_historical_stats(tmp_path) -> None:
    """BFS-discovered downstream entries must carry historical cost + duration.

    Previously `_make_downstream_entry` built a bare PlanEntry without a
    stats lookup, so a downstream LLM node after a non-LLM miss showed $0
    even when its cost + duration history was in the cache. Agents cost-
    or time-gating against the aggregate saw silent underestimates.

    `_execute_entry` is now the single path every `status="execute"` entry
    flows through — the downstream BFS call site inherits the stats lookup
    by construction. Mutation: revert `_make_downstream_entry` to build a
    raw PlanEntry without `_execute_entry` → this assertion fails.
    """
    ir = {
        "nodes": [
            {"id": "seed", "type": "shell", "cache": True, "params": {"command": "printf seed"}},
            {
                "id": "downstream",
                "type": "shell",
                "cache": True,
                "params": {"command": "printf down"},
            },
        ],
        "edges": [{"from": "seed", "to": "downstream"}],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # Seed only `downstream`'s history — `seed` is the first miss, so the
    # boundary triggers BFS which discovers `downstream`.
    _seed_cache_entry(
        cache,
        compiled,
        "downstream",
        "default",
        {"stdout": "down", "exit_code": 0},
        duration_ms=1234.5,
    )

    plan = build_plan(compiled, {}, cache, registry, workflow_name="bfs-stats")

    by_id = {e.node_id: e for e in plan.entries}
    downstream = by_id["downstream"]
    assert downstream.status == "execute"
    assert downstream.cause == "downstream"
    # Duration from the cache entry's `__pflow_stats__` must reach the
    # downstream entry via `_execute_entry`.
    assert downstream.last_duration_ms == 1234.5
    assert downstream.last_run_age_sec is not None


def test_plan_duration_nested_rollup(tmp_path) -> None:
    """Nested duration must roll up into the parent's `_including_nested`.

    Parallel to `test_plan_cost_nested_rollup`. Parent has no execute nodes
    directly; child has one execute node with a known historical duration.
    Agent time-gating reads `estimated_duration_ms_including_nested`, so
    nested durations must aggregate correctly across the sub-workflow
    boundary. Mutation: remove the `nested_duration += ...` branch in
    `_summarize` → this assertion fails.
    """
    child_path = tmp_path / "child-duration.pflow.md"
    parent_path = tmp_path / "parent-duration.pflow.md"

    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "work",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": "printf work"},
                },
            ],
            "edges": [],
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

    first = _runner_run(parent_path)
    assert first.success

    # Edit child to invalidate the cache → `work` becomes a miss → historical
    # duration from the first run surfaces on the plan entry + summary.
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "work",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": "printf work-edited"},
                },
            ],
            "edges": [],
        },
        child_path,
    )
    plan = _runner_plan(parent_path)

    # Parent level: only a sub_workflow entry — no direct duration.
    assert plan.summary.estimated_duration_ms == 0.0

    child_plan = plan.entries[0].sub_plan
    assert child_plan is not None
    work = next(e for e in child_plan.entries if e.node_id == "work")
    assert work.status == "execute"
    assert work.last_duration_ms is not None
    assert work.last_duration_ms > 0

    # Nested rollup: parent's _including_nested equals the child's aggregate.
    rollup = plan.summary.estimated_duration_ms_including_nested
    assert rollup is not None
    assert rollup == child_plan.summary.estimated_duration_ms
    assert rollup > 0


def test_plan_batch_llm_cost_aggregates_across_results(tmp_path) -> None:
    """Batch LLM cost must sum across `results[i].llm_usage.cost_usd`.

    The batch node's cached blob has no top-level `llm_usage` — cost lives
    per-item inside `results[]`. Before this fix, `_read_stats_from_output`
    only checked the top level and reported batch LLMs as `≈ $?` even when
    every item had cost history. Issue #310's motivating example is a batch
    LLM pipeline — showing `$?` there defeats the feature.

    Mutation: remove the `_extract_batch_cost_from_results` call in
    `_read_stats_from_output` → this assertion fails.
    """
    ir = {
        "inputs": {"items": {"type": "array"}},
        "nodes": [
            {
                "id": "classify",
                "type": "llm",
                "params": {"model": "gpt-4o-mini", "prompt": "Classify: ${item}"},
                "batch": {"items": "${items}", "parallel": False, "max_concurrent": 1},
            },
        ],
        "edges": [],
    }

    # Directly seed the cache with a batch entry shape matching what the
    # engine would write — no real LLM call needed.
    compiled, _registry = _compile(ir, params={"items": ["a", "b", "c"]})
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    batch_output = {
        "results": [
            {"item": "a", "llm_usage": {"cost_usd": 0.0012, "model": "gpt-4o-mini"}, "response": "x"},
            {"item": "b", "llm_usage": {"cost_usd": 0.0034, "model": "gpt-4o-mini"}, "response": "y"},
            {"item": "c", "llm_usage": {"cost_usd": 0.0056, "model": "gpt-4o-mini"}, "response": "z"},
        ],
        "count": 3,
        "success_count": 3,
        "error_count": 0,
        "errors": [],
    }
    _seed_cache_entry(
        cache,
        compiled,
        "classify",
        "default",
        batch_output,
        duration_ms=1500.0,
        shared_extras={"items": ["a", "b", "c"]},
    )

    # Plan with DIFFERENT items — classify becomes a miss, historical cost
    # (summed across results) must surface.
    compiled2, registry2 = _compile(ir, params={"items": ["a", "b", "c", "d"]})
    plan = build_plan(compiled2, {"items": ["a", "b", "c", "d"]}, cache, registry2, workflow_name="batch")

    classify = next(e for e in plan.entries if e.node_id == "classify")
    assert classify.status == "execute"
    assert classify.cause == "no_cache_match"
    # Sum of 0.0012 + 0.0034 + 0.0056 = 0.0102 (allow tiny float tolerance).
    assert classify.last_cost_usd is not None
    assert abs(classify.last_cost_usd - 0.0102) < 1e-9


def test_plan_workflow_path_scoped_lookup_no_pollution(tmp_path) -> None:
    """Historical stats lookup must scope by workflow_path to prevent pollution.

    Before this fix, `get_latest_for_node("classify")` returned the most
    recent entry regardless of which workflow wrote it. Two workflows sharing
    a common node name (like "classify") silently polluted each other's
    cost/duration estimates.

    Mutation: remove the `workflow_path=` filter in `get_latest_for_node`
    (or in `_lookup_last_run_stats`) → this assertion fails because the
    other workflow's duration (the WRONG value) leaks in.
    """
    # Two workflows, both with a node named "classify" but DIFFERENT workflow_path.
    ir_a = {
        "nodes": [{"id": "classify", "type": "shell", "cache": True, "params": {"command": "echo a"}}],
        "edges": [],
    }
    ir_b = {
        "nodes": [{"id": "classify", "type": "shell", "cache": True, "params": {"command": "echo b"}}],
        "edges": [],
    }
    compiled_a, registry_a = _compile(ir_a)
    compiled_b, _registry_b = _compile(ir_b)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # Write each entry with its own workflow_path, different durations.
    # Use the real put() with workflow_path explicitly (bypass the seed helper
    # since it writes with workflow_path=None).
    from pflow.runtime.engine.plan_node import plan_node

    for compiled, workflow_path, output, duration in [
        (
            compiled_a,
            "/fake/workflow_a.pflow.md",
            {"stdout": "a", "exit_code": 0},
            100.0,
        ),
        (
            compiled_b,
            "/fake/workflow_b.pflow.md",
            {"stdout": "b", "exit_code": 0},
            9999.0,  # Very different — if pollution occurs, this leaks into A's lookup.
        ),
    ]:
        target = next(iter(compiled.node_configs.values()))
        planned = plan_node(
            compiled.start_node,
            target,
            {"__execution__": {"node_visit_counts": {}}, "__memoization_cache__": cache},
        )
        blob = dict(output)
        blob["__pflow_stats__"] = {"duration_ms": duration}
        cache.put(planned.cache_key, "classify", workflow_path, "default", blob)

    # Plan workflow A with its own workflow_path. The planner's scoped
    # lookup must NOT leak workflow B's 9999ms duration.
    params_a = {"_pflow_workflow_file": "/fake/workflow_a.pflow.md"}
    # Edit the workflow so A's own entry is a miss — historical stats surface.
    compiled_a_edited, _ = _compile({
        "nodes": [{"id": "classify", "type": "shell", "cache": True, "params": {"command": "echo a-edited"}}],
        "edges": [],
    })
    plan = build_plan(compiled_a_edited, params_a, cache, registry_a, workflow_name="workflow_a.pflow.md")

    classify = next(e for e in plan.entries if e.node_id == "classify")
    assert classify.status == "execute"
    # Should see A's own 100ms duration, NOT B's 9999ms.
    assert classify.last_duration_ms is not None
    assert classify.last_duration_ms == 100.0


def test_plan_sub_workflow_downstream_templates_resolve(tmp_path) -> None:
    """Parent's `shared[sub_workflow_node_id]` must be populated with
    declared child outputs so downstream nodes can template against them.

    Before this fix, `_plan_sub_workflow` returned without populating parent
    shared, so `${analyze.topic}` in downstream nodes failed template
    resolution → plan emitted `cause: "template_error"` entries for any
    parent node that used sub-workflow outputs. This made the planner
    unusable for a core pflow pattern (sub-workflow composition).

    Mutation: remove the `_populate_sub_workflow_outputs(...)` call in
    `_plan_sub_workflow` → this assertion fails (downstream shows
    `template_error` with "Unresolved variables").
    """
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    # Child declares two outputs sourcing from its internal nodes.
    child_path.write_text(
        """# Child

Computes two values.

## Inputs

### seed

Seed text.

- type: string

## Outputs

### topic

Selected topic.

- source: ${pick.stdout}

### body

Computed body.

- source: ${make.stdout}

## Steps

### pick

Pick a topic.

- type: shell
- cache: true

```shell command
printf "topic-from-%s" "${seed}"
```

### make

Make a body.

- type: shell
- cache: true

```shell command
printf "body-from-%s" "${seed}"
```
""",
        encoding="utf-8",
    )
    # Parent uses `${analyze.topic}` and `${analyze.body}` downstream.
    write_workflow_file(
        {
            "inputs": {"input_text": {"type": "string"}},
            "nodes": [
                {
                    "id": "analyze",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {"seed": "${input_text}"}},
                },
                {
                    "id": "combine",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": 'printf "%s|%s" "${analyze.topic}" "${analyze.body}"'},
                },
            ],
            "edges": [{"from": "analyze", "to": "combine"}],
        },
        parent_path,
    )

    # First: real run to populate cache so child outputs are cached.
    first = _runner_run(parent_path, {"input_text": "hello"})
    assert first.success

    # Second: dry-run. Child is fully cached → exact resolution of declared
    # outputs → parent's shared[analyze] has {topic, body} → combine can
    # template-resolve → planner predicts cached (not template_error).
    plan = _runner_plan(parent_path, {"input_text": "hello"})

    combine = next(e for e in plan.entries if e.node_id == "combine")
    assert combine.status == "cached", (
        f"expected combine to be cached (child outputs resolved), got status={combine.status} cause={combine.cause}"
    )
    assert combine.cause == "hash_match"


def test_plan_sub_workflow_plain_format_source_resolves(tmp_path) -> None:
    """Declared-output sources written in plain `node.key` form must resolve.

    pflow accepts three source formats for declared outputs: `${node.key}`,
    `$node.key`, and plain `node.key` (normalized to `${node.key}` by
    `_normalize_source`). Before this fix, the planner called
    `TemplateResolver.resolve_template` directly without normalization, so
    `node.key` and `$node.key` returned the literal string unchanged —
    parent_shared[sub_wf_id][output_name] held a string like `"pick.stdout"`
    instead of the resolved value. Downstream parent nodes then computed
    cache keys against that literal string, causing their plan entries to
    show as `execute` (fresh hash) when the engine would compute the same
    key as runtime and find them cached.

    Mutation: replace `resolve_output_source(source, child_shared)` in
    `_resolve_declared_outputs` with `TemplateResolver.resolve_template(
    source, child_shared)` → the plain-format source returns unchanged as
    a literal string, `combine`'s cache key mismatches the engine's, and
    the plan reports `execute` instead of `cached`.
    """
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    # Note: `- source: pick.stdout` (plain form, no `${}`). Runtime's
    # `populate_declared_outputs` normalizes this via `_normalize_source`.
    child_path.write_text(
        """# Child

Computes one value.

## Inputs

### seed

Seed text.

- type: string

## Outputs

### topic

Selected topic.

- source: pick.stdout

## Steps

### pick

Pick a topic.

- type: shell
- cache: true

```shell command
printf "topic-from-%s" "${seed}"
```
""",
        encoding="utf-8",
    )
    write_workflow_file(
        {
            "inputs": {"input_text": {"type": "string"}},
            "nodes": [
                {
                    "id": "analyze",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {"seed": "${input_text}"}},
                },
                {
                    "id": "combine",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": 'printf "result=%s" "${analyze.topic}"'},
                },
            ],
            "edges": [{"from": "analyze", "to": "combine"}],
        },
        parent_path,
    )

    first = _runner_run(parent_path, {"input_text": "hello"})
    assert first.success

    plan = _runner_plan(parent_path, {"input_text": "hello"})

    combine = next(e for e in plan.entries if e.node_id == "combine")
    assert combine.status == "cached", (
        f"plain-format declared-output source must normalize correctly; "
        f"got combine status={combine.status} cause={combine.cause}"
    )


def test_plan_sub_workflow_undeclared_outputs_fallback(tmp_path) -> None:
    """Sub-workflows without declared `## Outputs` must still expose their
    child node outputs for parent-level template resolution.

    Runtime's `WorkflowExecutor._expose_child_outputs` has a fallback: when
    the child has no declared outputs, it copies all non-internal, non-input
    keys from child_storage to the parent's namespace. This lets parent nodes
    template `${sub_wf_id.child_node_id.field}`.

    Before this fix, the planner's `_populate_sub_workflow_outputs` only
    handled the declared case — the undeclared-fallback path was missing.
    Downstream parent nodes referencing undeclared child outputs failed
    template resolution at plan time, even when runtime would succeed.

    Mutation: remove the `_mirror_child_shared` branch in
    `_populate_sub_workflow_outputs` → downstream becomes `template_error`.
    """
    child_path = tmp_path / "undeclared_child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    # Child with NO `## Outputs` section.
    child_path.write_text(
        """# Undeclared Child

Computes an intermediate value; exposes it via fallback, not via declared outputs.

## Inputs

### seed

Seed text.

- type: string

## Steps

### compute

Do the work.

- type: shell
- cache: true

```shell command
printf "computed-from-%s" "${seed}"
```
""",
        encoding="utf-8",
    )
    # Parent references `${analyze.compute.stdout}` — undeclared child output.
    write_workflow_file(
        {
            "inputs": {"input_text": {"type": "string"}},
            "nodes": [
                {
                    "id": "analyze",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {"seed": "${input_text}"}},
                },
                {
                    "id": "use",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": 'printf "got %s" "${analyze.compute.stdout}"'},
                },
            ],
            "edges": [{"from": "analyze", "to": "use"}],
        },
        parent_path,
    )

    first = _runner_run(parent_path, {"input_text": "hello"})
    assert first.success

    # Plan: child fully cached, declared-outputs fallback should expose
    # child's `compute` key under analyze namespace → parent's `use` can
    # template-resolve `${analyze.compute.stdout}` → cached.
    plan = _runner_plan(parent_path, {"input_text": "hello"})
    use = next(e for e in plan.entries if e.node_id == "use")
    assert use.status == "cached", (
        f"expected use to be cached (undeclared outputs mirrored), got status={use.status} cause={use.cause}"
    )


def test_plan_direct_ir_null_workflow_path_historical_stats(tmp_path) -> None:
    """Direct-IR / content-string runs write NULL `workflow_path`; planner
    must fall back to UNSCOPED lookup when `workflow_path is None`.

    SQL NULL semantics: `WHERE workflow_path = NULL` matches zero rows. If a
    future refactor removes the `if workflow_path is not None:` guard in
    `_lookup_last_run_stats` (thinking "we always have a path now"), all
    direct-IR cache lookups silently return None — agent cost-gating on
    dict-based workflows loses history completely.

    Mutation: change the guard to `if True:` in `_lookup_last_run_stats` →
    the scoped query runs with `workflow_path=None` → matches nothing →
    test fails because `last_duration_ms` is None instead of the seeded value.
    """
    # Build an IR dict (no file path) and compile it — matches a direct-IR run.
    ir = {
        "nodes": [{"id": "work", "type": "shell", "cache": True, "params": {"command": "printf result"}}],
        "edges": [],
    }
    compiled, _registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # Seed a cache entry with NULL workflow_path (matches what the engine
    # writes for direct-IR runs where `_pflow_workflow_file` is never set).
    from pflow.runtime.engine.plan_node import plan_node

    config = compiled.node_configs["work"]
    planned = plan_node(
        compiled.start_node,
        config,
        {"__execution__": {"node_visit_counts": {}}, "__memoization_cache__": cache},
    )
    assert planned.cache_key is not None
    blob = {"stdout": "result", "exit_code": 0, "__pflow_stats__": {"duration_ms": 42.5}}
    cache.put(planned.cache_key, "work", None, "default", blob)  # workflow_path=None

    # Plan the same IR with no `_pflow_workflow_file` in params — _WalkerState.workflow_path
    # will also be None → _lookup_last_run_stats falls back to unscoped lookup.
    # Edit the command so plan sees a miss → _execute_entry attaches historical stats.
    ir_edited = {
        "nodes": [{"id": "work", "type": "shell", "cache": True, "params": {"command": "printf result-edited"}}],
        "edges": [],
    }
    compiled_edited, registry_edited = _compile(ir_edited)
    plan = build_plan(compiled_edited, {}, cache, registry_edited, workflow_name="direct-ir")

    work = next(e for e in plan.entries if e.node_id == "work")
    assert work.status == "execute"
    # NULL-path fallback must surface the historical duration; if the guard
    # is mutated away, this would be None (scoped query with NULL matches 0 rows).
    assert work.last_duration_ms == 42.5


def test_plan_inline_workflow_relative_sub_workflow_resolves_via_cwd(monkeypatch, tmp_path) -> None:
    """Inline (non-file) parent with a relative sub-workflow ref resolves via CWD.

    MCP-inline / dict-input / content-string submissions have no parent file
    path. Runtime's `WorkflowExecutor._load_workflow` reads
    `shared["_pflow_workflow_file"]` (which is the synthetic `"ir-hash:..."`
    identifier after the L2 scoping fix) and derives `base_path` — for the
    ir-hash identifier this gives `Path(".")`, so relative child refs resolve
    against CWD. Planner previously derived base_path from a separate
    `parent_workflow_file` parameter sourced from `resolved.file_path`
    (literally None for inline), so it passed None to `resolve_sub_workflow`
    which raised ValueError on any relative child path.

    Mutation: change the planner's new line to
    `base_path = Path(parent_file).parent if False else None` (forces the
    None branch) → the sub-workflow resolve raises, entry shows
    `cause != "no_cache_match"` with a diagnostic about relative paths.
    """
    monkeypatch.chdir(tmp_path)

    child_path = tmp_path / "child.pflow.md"
    child_path.write_text(
        """# Child

Minimal child workflow.

## Steps

### only

Just echoes.

- type: shell
- cache: true
- command: printf done
""",
        encoding="utf-8",
    )

    parent_ir = {
        "nodes": [
            {
                "id": "run-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md"},
            },
        ],
        "edges": [],
    }

    plan = WorkflowRunner().plan(parent_ir, {}, RunnerConfig())

    run_child = next(e for e in plan.entries if e.node_id == "run-child")
    assert run_child.status == "sub_workflow", (
        f"inline parent's relative sub-workflow ref must resolve via CWD; "
        f"got status={run_child.status} cause={run_child.cause}"
    )
    assert run_child.sub_plan is not None, "child workflow must have been planned"


def test_plan_cached_loop_visit_two_reports_execute(tmp_path) -> None:
    """In an all-cached success-action loop, visit 2 of a node must be execute.

    The engine's `enforce_loop_guard` invalidates `completed_nodes`/
    `node_actions`/`node_hashes` for any revisited node before `plan_node`
    runs, so visit 2 falls through both memo (visit_counts > 1 guard) and
    in-process (node removed from completed_nodes) caches and re-executes.

    Without the invalidation, the planner's in_process_cache_lookup sees
    the visit-1 entries still in `completed_nodes` (populated by
    `apply_memo_hit` on visit 1's cached_memo hit), reports visit 2 as
    `cached_in_process`, and under-reports work.

    Mutation: replace `enforce_loop_guard(node_id, shared)` in the walker
    with `shared["__execution__"]["node_visit_counts"][node_id] += 1`
    (the old manual bump that lacks invalidation) → the third entry's
    status flips to "cached" and this assertion fails.
    """
    ir = {
        "nodes": [
            {"id": "a", "type": "shell", "cache": True, "params": {"command": "echo a"}},
            {"id": "b", "type": "shell", "cache": True, "params": {"command": "echo b"}},
        ],
        "edges": [
            {"from": "a", "to": "b", "action": "go"},
            {"from": "b", "to": "a", "action": "back"},
        ],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    _seed_cache_entry(cache, compiled, "a", "go", {"stdout": "a", "exit_code": 0})
    _seed_cache_entry(cache, compiled, "b", "back", {"stdout": "b", "exit_code": 0})

    plan = build_plan(compiled, {}, cache, registry, workflow_name="loop")

    # Walker trace: a(v1 cached) → b(v1 cached) → a(v2, must be execute).
    # The walker then terminates via visited_edges on (a, "go").
    assert [entry.node_id for entry in plan.entries] == ["a", "b", "a"]
    assert [entry.status for entry in plan.entries] == ["cached", "cached", "execute"]


def test_plan_cache_disabled_node_carries_historical_stats(tmp_path) -> None:
    """A `cache: false` node with prior memo history must surface duration.

    `cache: false` means "don't reuse the cache for hit decisions" — not
    "hide history from the agent". If a prior run (under `cache: true`, or
    before the flag was added) wrote stats to the memo cache for this
    node_id, the planner must look them up — `get_latest_for_node` queries
    by node_id, not by cache_key.

    Guards against `_cache_disabled_entry` bypassing `_execute_entry` and
    losing the stats lookup. This is the exact scenario the feature-interactions
    review flagged: user runs the workflow once to see cost, then marks
    `cache: false`. Without this fix they see `$0` on the dry-run plan.
    """
    ir = {
        "nodes": [
            {
                "id": "uncached",
                "type": "shell",
                "cache": False,
                "params": {"command": "printf uncached"},
            },
        ],
        "edges": [],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # Seed a prior-run entry for this node_id (simulates: user ran the
    # workflow once with cache enabled, then flipped to cache: false).
    cache.put(
        "any-key",
        "uncached",
        None,
        "default",
        {"stdout": "uncached", "exit_code": 0, "__pflow_stats__": {"duration_ms": 77.0}},
    )

    plan = build_plan(compiled, {}, cache, registry, workflow_name="cache-false-stats")

    entry = plan.entries[0]
    assert entry.cause == "cache_disabled"
    assert entry.last_duration_ms == 77.0, (
        "cache_disabled entries must flow through _execute_entry so historical "
        f"duration is attached; got {entry.last_duration_ms}"
    )


def test_plan_bfs_recurses_into_sub_workflow_carrying_child_stats(tmp_path) -> None:
    """Sub-workflows reached via BFS post-boundary must recurse and roll up child stats.

    Motivating scenario: parent workflow has an upstream node, a sub-workflow
    in the middle (with its own LLM/work), and a downstream node. Agent edits
    the upstream node to iterate — the parent's first-miss fires at upstream,
    BFS enumerates downstream. Before this fix, the sub-workflow became a flat
    leaf entry with no `sub_plan` and no rollup of its children's historical
    cost/duration. Agents cost-gating after an upstream edit silently lost
    every nested LLM cost in the summary — exactly the #1 iteration pattern.

    After the fix:
    - Parent plan shows `[execute, sub_workflow, execute]` with causes
      `[no_cache_match, downstream, downstream]`.
    - The `sub_workflow` entry's `sub_plan` exists and contains every child
      node with `cause="downstream"`.
    - Child entries carry `last_duration_ms` populated from the child's
      workflow-path-scoped cache (the `_execute_entry` chokepoint).
    - `estimated_duration_ms_including_nested` on the parent sums the parent
      and child durations.

    Mutation: revert `_make_downstream_entry`'s `WorkflowExecutor` branch to
    fall through to `_execute_entry` → sub_plan becomes None, nested rollup
    drops to zero, these assertions fail.
    """
    log_file = tmp_path / "bfs-sub.log"
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    write_workflow_file(
        {
            "inputs": {"seed": {"type": "string", "description": "upstream value"}},
            "nodes": [
                {
                    "id": "child-work",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo child-work >> {log_file}; printf 'child-${{seed}}'"},
                },
            ],
            "edges": [],
            "outputs": {"out": {"source": "${child-work.stdout}", "description": "child output"}},
        },
        child_path,
    )
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "upstream",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo upstream-v1 >> {log_file}; printf v1"},
                },
                {
                    "id": "middle",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {"seed": "${upstream.stdout}"}},
                },
                {
                    "id": "downstream",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo downstream >> {log_file}; printf end"},
                },
            ],
            "edges": [
                {"from": "upstream", "to": "middle"},
                {"from": "middle", "to": "downstream"},
            ],
        },
        parent_path,
    )

    # First real run populates child's cache entry with duration history.
    first_result = _runner_run(parent_path)
    assert first_result.success

    # Edit upstream to invalidate — parent walker will boundary at upstream,
    # BFS will reach `middle` (the sub-workflow) and MUST recurse.
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "upstream",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo upstream-v2 >> {log_file}; printf v2"},
                },
                {
                    "id": "middle",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {"seed": "${upstream.stdout}"}},
                },
                {
                    "id": "downstream",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo downstream >> {log_file}; printf end"},
                },
            ],
            "edges": [
                {"from": "upstream", "to": "middle"},
                {"from": "middle", "to": "downstream"},
            ],
        },
        parent_path,
    )

    plan = _runner_plan(parent_path)

    assert [e.status for e in plan.entries] == ["execute", "sub_workflow", "execute"]
    assert [e.cause for e in plan.entries] == ["no_cache_match", "downstream", "downstream"]

    sub_plan = plan.entries[1].sub_plan
    assert sub_plan is not None, "BFS must produce a nested sub_plan for the sub-workflow"
    assert [e.status for e in sub_plan.entries] == ["execute"]
    assert [e.cause for e in sub_plan.entries] == ["downstream"]

    child_entry = sub_plan.entries[0]
    assert child_entry.last_duration_ms is not None and child_entry.last_duration_ms > 0, (
        "Child entry must carry duration from child-workflow-scoped cache via "
        f"_execute_entry; got {child_entry.last_duration_ms}"
    )

    # Rollup: nested duration must be present and >= child's duration.
    nested = plan.summary.estimated_duration_ms_including_nested
    assert nested is not None and nested >= child_entry.last_duration_ms, (
        f"estimated_duration_ms_including_nested ({nested}) must include the child's {child_entry.last_duration_ms}ms"
    )


def test_plan_downstream_linear_subworkflow_reports_exact_cost_basis(tmp_path) -> None:
    """Force-downstream recursion on a LINEAR child must keep cost_basis='exact'.

    Before this assertion landed, `_build_plan_with_shared(force_downstream=True)`
    hardcoded `cost_basis="upper_bound"`, which made the summary label promise
    "upper bound across all branches" even for workflows with zero branching.
    Misleading for cost-gating: agents think the estimate is pessimistic when
    actually the topology is exact — it's only the historical number that varies.

    Now the flag follows the BFS `branched` signal. Mutation: re-hardcode
    `cost_basis="upper_bound"` in the `_force_downstream` block → this test
    fails because the linear child produces `exact` but would see `upper_bound`.
    """
    log_file = tmp_path / "linear-sub.log"
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    write_workflow_file(
        {
            "inputs": {"seed": {"type": "string", "description": "upstream value"}},
            "nodes": [
                {
                    "id": "child-a",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo a >> {log_file}; printf 'a-${{seed}}'"},
                },
                {
                    "id": "child-b",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo b >> {log_file}; printf '${{child-a.stdout}}-b'"},
                },
            ],
            "edges": [{"from": "child-a", "to": "child-b"}],
            "outputs": {"out": {"source": "${child-b.stdout}", "description": "out"}},
        },
        child_path,
    )
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "upstream",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo up >> {log_file}; printf up"},
                },
                {
                    "id": "middle",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {"seed": "${upstream.stdout}"}},
                },
            ],
            "edges": [{"from": "upstream", "to": "middle"}],
        },
        parent_path,
    )

    _runner_run(parent_path)

    # Edit upstream so parent's walker enters BFS at `upstream`. BFS reaches
    # `middle` and force-downstream-recurses into the linear child.
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "upstream",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo up2 >> {log_file}; printf up2"},
                },
                {
                    "id": "middle",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {"seed": "${upstream.stdout}"}},
                },
            ],
            "edges": [{"from": "upstream", "to": "middle"}],
        },
        parent_path,
    )

    plan = _runner_plan(parent_path)
    sub_plan = plan.entries[1].sub_plan
    assert sub_plan is not None
    assert sub_plan.summary.cost_basis == "exact", (
        f"linear child in force_downstream mode must report exact basis, got {sub_plan.summary.cost_basis}"
    )


def test_plan_downstream_subworkflow_placeholders_satisfy_required_inputs(tmp_path) -> None:
    """BFS recursion into a sub-workflow with required inputs must compile cleanly.

    Parent's upstream is dirty, so real inputs can't be resolved. The child
    declares required inputs — without placeholder synthesis, `compile_workflow`
    rejects empty/missing values. Mutation: make `_placeholder_child_inputs`
    return `{}` → the child compile fails, the plan's sub_plan is replaced
    with a compile-error entry, and no child entries are produced.
    """
    log_file = tmp_path / "placeholder.log"
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    write_workflow_file(
        {
            "inputs": {
                "seed": {"type": "string", "description": "required seed"},
                "count": {"type": "integer", "description": "required count"},
                "items": {"type": "array", "description": "required list"},
            },
            "nodes": [
                {
                    "id": "consume",
                    "type": "code",
                    "cache": True,
                    "params": {
                        "inputs": {
                            "seed": "${seed}",
                            "count": "${count}",
                            "items": "${items}",
                        },
                        "code": "seed: str\ncount: int\nitems: list\nresult: str = f'{seed}-{count}-{len(items)}'",
                    },
                },
            ],
            "edges": [],
            "outputs": {"result": {"source": "${consume.result}", "description": "out"}},
        },
        child_path,
    )
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "upstream",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo up >> {log_file}; printf up"},
                },
                {
                    "id": "middle",
                    "type": "workflow",
                    "params": {
                        "workflow": str(child_path),
                        "inputs": {
                            "seed": "${upstream.stdout}",
                            "count": 1,
                            "items": ["x"],
                        },
                    },
                },
            ],
            "edges": [{"from": "upstream", "to": "middle"}],
        },
        parent_path,
    )

    # First real run populates child's cache entry.
    first = _runner_run(parent_path)
    assert first.success

    # Invalidate upstream — forces BFS at `middle`.
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "upstream",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo up2 >> {log_file}; printf up2"},
                },
                {
                    "id": "middle",
                    "type": "workflow",
                    "params": {
                        "workflow": str(child_path),
                        "inputs": {
                            "seed": "${upstream.stdout}",
                            "count": 1,
                            "items": ["x"],
                        },
                    },
                },
            ],
            "edges": [{"from": "upstream", "to": "middle"}],
        },
        parent_path,
    )

    plan = _runner_plan(parent_path)

    # The sub-workflow must have recursed into a fully-formed child plan.
    assert plan.entries[1].status == "sub_workflow"
    sub_plan = plan.entries[1].sub_plan
    assert sub_plan is not None, "placeholder inputs must satisfy compile; got no sub_plan"
    assert [e.cause for e in sub_plan.entries] == ["downstream"]
    # No ERROR diagnostics — the compile succeeded with placeholders.
    error_diags = [d for d in plan.diagnostics if getattr(d.severity, "value", "") == "error"]
    assert not error_diags, f"placeholder synthesis must avoid compile errors; got {error_diags}"


def test_plan_summary_execute_by_type_aggregates_across_nested(tmp_path) -> None:
    """`execute_by_type_including_nested` must sum per-level types + child types.

    Parent has 1 shell + 1 workflow. Child has 1 shell. Including nested
    should report {shell: 2, workflow: 1}. Mutation: remove the
    `nested_by_type[t] += count` loop in `_summarize` → child shell
    disappears from the parent summary.
    """
    log_file = tmp_path / "agg.log"
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    write_workflow_file(
        {
            "inputs": {"seed": {"type": "string", "description": "seed"}},
            "nodes": [
                {
                    "id": "child-shell",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo s >> {log_file}; printf '${{seed}}'"},
                },
            ],
            "edges": [],
            "outputs": {"out": {"source": "${child-shell.stdout}", "description": "out"}},
        },
        child_path,
    )
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "parent-shell",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo p >> {log_file}; printf p"},
                },
                {
                    "id": "middle",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {"seed": "${parent-shell.stdout}"}},
                },
            ],
            "edges": [{"from": "parent-shell", "to": "middle"}],
        },
        parent_path,
    )

    # Prime cache so BFS path exercises recursion.
    _runner_run(parent_path)
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "parent-shell",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo p2 >> {log_file}; printf p2"},
                },
                {
                    "id": "middle",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {"seed": "${parent-shell.stdout}"}},
                },
            ],
            "edges": [{"from": "parent-shell", "to": "middle"}],
        },
        parent_path,
    )

    plan = _runner_plan(parent_path)
    nested_types = plan.summary.execute_by_type_including_nested
    assert nested_types is not None
    # 2 shells (parent-shell + child-shell) + 1 WorkflowExecutor frame.
    assert nested_types.get("ShellNode") == 2, f"nested type rollup must include child's shell; got {nested_types}"
    assert nested_types.get("WorkflowExecutor") == 1


def test_plan_downstream_bfs_detects_sub_workflow_cycle(tmp_path) -> None:
    """Cycle detection must survive the BFS → force-downstream → BFS threading.

    `visited_paths` flows through four hops to reach the recursive
    `_plan_sub_workflow` call: `_apply_boundary` → `_bfs_downstream` → `_bfs_walk`
    → `_make_downstream_entry` → `_plan_sub_workflow(cause="downstream")`. If any
    hop drops `visited_paths`, a mutual sub-workflow cycle would silently
    bottom out at `_MAX_SUB_WORKFLOW_DEPTH=10` (producing 10 identical sub_plans)
    instead of surfacing as a proper "Circular sub-workflow reference"
    diagnostic at the second visit.

    Mutation: replace the `_visited_paths` arg in `_plan_sub_workflow`'s
    recursive `_build_plan_with_shared` call with `_visited_paths=[]` → cycle
    detection never fires, max-depth surfaces instead.
    """
    log_file = tmp_path / "cycle.log"
    parent_path = tmp_path / "parent.pflow.md"
    child_a_path = tmp_path / "child-a.pflow.md"

    # child_a references parent in a back-edge — creates a cycle.
    write_workflow_file(
        {
            "inputs": {"seed": {"type": "string", "description": "seed"}},
            "nodes": [
                {
                    "id": "back-to-parent",
                    "type": "workflow",
                    "params": {"workflow": str(parent_path), "inputs": {"seed": "${seed}"}},
                },
            ],
            "edges": [],
            "outputs": {"out": {"source": "${back-to-parent.out}", "description": "out"}},
        },
        child_a_path,
    )
    write_workflow_file(
        {
            "inputs": {"seed": {"type": "string", "description": "seed"}},
            "nodes": [
                {
                    "id": "upstream",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo u >> {log_file}; printf '${{seed}}'"},
                },
                {
                    "id": "call-child",
                    "type": "workflow",
                    "params": {"workflow": str(child_a_path), "inputs": {"seed": "${upstream.stdout}"}},
                },
            ],
            "edges": [{"from": "upstream", "to": "call-child"}],
            "outputs": {"final": {"source": "${call-child.out}", "description": "final"}},
        },
        parent_path,
    )

    # Prime the cache so BFS has a reason to traverse post-boundary. A real run
    # would fail with a cycle error, so seed only the upstream cache entry.
    # Actually: the cycle is only detected by the PLANNER via visited_paths;
    # runtime detects it through `_pflow_stack`. We can't pre-run this workflow
    # to populate cache. Instead, run a stripped-down version first.
    # Simpler: just plan the cyclic workflow cold — visited_paths check runs
    # during the first BFS pass whether or not the cache is populated.

    plan = _runner_plan(parent_path, params={"seed": "x"})

    def _collect_messages(entries):
        for entry in entries:
            if entry.diagnostic is not None:
                yield entry.diagnostic.message
            if entry.sub_plan is not None:
                yield from _collect_messages(entry.sub_plan.entries)

    messages = list(_collect_messages(plan.entries))
    assert any("Circular sub-workflow reference" in m for m in messages), (
        f"visited_paths threading broken — expected cycle diagnostic, got: {messages}"
    )
    assert not any("Max sub-workflow depth" in m for m in messages), (
        f"max-depth fired instead of cycle detection — threading drift: {messages}"
    )


def test_plan_cached_end_action_terminates_cleanly(tmp_path) -> None:
    """Cached action="end" must STOP cleanly, not emit a routing_error entry.

    Guards against a `_classify` check-order regression where the routing_error
    check fires before the "end" sentinel check. Real pflow graphs never have
    "end" as a successors key — it's a runtime termination sentinel — so any
    node cached with action="end" would trip the routing_error branch.
    """
    log_file = tmp_path / "end.log"
    ir = {
        "nodes": [
            {
                "id": "a",
                "type": "shell",
                "cache": True,
                "params": {"command": f"echo a >> {log_file}; printf a"},
            },
            {
                "id": "b",
                "type": "code",
                "cache": True,
                "params": {"code": 'next: str = "end"\nresult: str = "done"'},
            },
        ],
        "edges": [{"from": "a", "to": "b"}],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    _run(compiled, cache)
    plan = build_plan(compiled, {}, cache, registry, workflow_name="end-action")

    statuses = [entry.status for entry in plan.entries]
    causes = [entry.cause for entry in plan.entries]
    assert statuses == ["cached", "cached"]
    assert "routing_error" not in causes


def test_plan_heterogeneous_batch_sub_workflow_per_item_cache(tmp_path) -> None:
    """Batch sub-workflows with per-item workflow paths resolve per-item cache status.

    Regression target for GH #336. Without the heterogeneous batch planning
    path, `workflow: ${item.workflow}` returns opaque — no per-item cache
    checking, no cost/duration, and everything downstream cascades to
    "would execute."

    Mutation: revert _plan_batch_sub_workflow to call _precheck_sub_workflow
    unconditionally → this test fails because the batch entry becomes opaque.
    """
    log_file = tmp_path / "hetero.log"

    child_a = tmp_path / "child-a.pflow.md"
    child_a.write_text(
        f"""\
# Child A

Test child workflow A.

## Inputs

### value

Input value.

- type: string
- required: true

## Steps

### do-a

Echoes the value.

- type: shell
- cache: true
- command: echo a:${{value}} >> {log_file}; printf a:${{value}}

## Outputs

### out

Output from do-a.

- source: ${{do-a.stdout}}
""",
        encoding="utf-8",
    )

    child_b = tmp_path / "child-b.pflow.md"
    child_b.write_text(
        f"""\
# Child B

Test child workflow B.

## Inputs

### value

Input value.

- type: string
- required: true

## Steps

### do-b

Echoes the value.

- type: shell
- cache: true
- command: echo b:${{value}} >> {log_file}; printf b:${{value}}

## Outputs

### out

Output from do-b.

- source: ${{do-b.stdout}}
""",
        encoding="utf-8",
    )

    parent = tmp_path / "parent.pflow.md"
    parent.write_text(
        f"""\
# Heterogeneous Batch Parent

Dispatches to different child workflows per item.

## Steps

### fanout

Runs different child workflows per batch item.

- type: workflow
- workflow: ${{item.workflow}}
- inputs: ${{item.inputs}}

```yaml batch
items:
  - workflow: {child_a}
    inputs:
      value: hello
  - workflow: {child_b}
    inputs:
      value: world
parallel: false
```
""",
        encoding="utf-8",
    )

    first_result = _runner_run(parent)
    assert first_result.success, first_result.diagnostics

    plan = _runner_plan(parent)
    second_result = _runner_run(parent)
    assert second_result.success

    assert len(plan.entries) == 1
    fanout = plan.entries[0]
    assert fanout.status == "sub_workflow"
    assert fanout.batch_count == 2
    assert fanout.sub_plan is not None

    child_entries = fanout.sub_plan.entries
    assert len(child_entries) == 2
    statuses = {e.node_id: e.status for e in child_entries}
    assert statuses.get("do-a") == "cached"
    assert statuses.get("do-b") == "cached"

    # Second run did no extra work
    assert _log_lines(log_file) == ["a:hello", "b:world"]


def test_plan_matches_engine_for_workflow_with_prompt_cache(tmp_path, mock_llm_client) -> None:
    """A workflow with `## Cache` declared: the planner's plan_node must see
    the same `__pflow_prompt_cache__` dict as the engine, otherwise plan and
    runtime hashes diverge — the planner mispredicts ``cached`` vs ``execute``.

    Pre-fix bug (Task 159 B3 review-feature-interactions C1): the planner's
    ``_create_planner_shared`` did not install ``__pflow_prompt_cache__``.
    Engine's ``plan_node`` saw a populated dict via ``WorkflowEngine.run``'s
    save/restore; planner's ``plan_node`` saw ``None``. config_hash diverged
    silently for cache-using workflows.

    Mutation: remove the install at ``_create_planner_shared`` and this
    test fails — planner predicts ``execute`` even though engine actually
    serves the entry from memo cache.
    """
    mock_llm_client.set_response("gpt-4o-mini", None, "ok", cost_usd=0.0)
    ir = {
        "inputs": {
            "concept": {
                "type": "string",
                "required": False,
                "default": "caching",
                "description": "concept to render",
            }
        },
        "nodes": [
            {
                "id": "gen",
                "type": "llm",
                # Prompt body intentionally does NOT reference ${concept} — this
                # plan-vs-engine drift test cares about cache content flowing into
                # the hash, not about prompt body content. Inlining ${concept}
                # would trigger cache.prompt-body-duplicates-cache (Task 159
                # follow-up overlap check) and conflate two checks.
                "params": {"model": "gpt-4o-mini", "prompt": "Tell me a one-liner story."},
                "prompt_cache": ["concept"],
            }
        ],
        "edges": [],
        "cache": {
            "items": [{"name": "concept", "var": "concept", "prose_before": "About: "}],
        },
    }
    compiled, registry = _compile(ir, params={"concept": "caching"})
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # First run populates the memo cache under engine's hash.
    _run(compiled, cache, params={"concept": "caching"})
    import sqlite3

    conn = sqlite3.connect(tmp_path / "cache.db")
    try:
        row = conn.execute(
            "SELECT cache_key FROM cache_entries WHERE node_id = ? ORDER BY created_at DESC LIMIT 1",
            ("gen",),
        ).fetchone()
        engine_cache_key = row[0] if row else None
    finally:
        conn.close()

    # Plan via the planner. Must see the SAME __pflow_prompt_cache__ dict the
    # engine installs — otherwise plan_node's hash diverges and the plan
    # incorrectly predicts "execute".
    plan = build_plan(
        compiled,
        {"concept": "caching"},
        cache,
        registry,
        workflow_name="prompt-cache-parity",
    )
    assert plan.entries, "plan produced no entries"
    gen_entry = next(entry for entry in plan.entries if entry.node_id == "gen")
    assert engine_cache_key is not None, "engine did not populate cache row"
    assert gen_entry.cache_key == engine_cache_key, (
        f"PlanEntry.cache_key drift: planner={gen_entry.cache_key!r} engine={engine_cache_key!r}"
    )
    statuses = [entry.status for entry in plan.entries]
    assert all(s == "cached" for s in statuses), (
        f"planner mispredicted for prompt_cache workflow: statuses={statuses!r}. "
        "Likely cause: _create_planner_shared did not install __pflow_prompt_cache__, "
        "so plan_node's config_hash excludes cache content while engine's includes it."
    )


def test_create_planner_shared_underscore_alias_is_preserved() -> None:
    """Back-compat: ``_create_planner_shared`` alias must resolve and point at
    the canonical ``create_planner_shared`` callable.

    The alias was preserved during Stage A/0/B/C data-model redesign so existing
    in-tree imports don't churn. There are no production callers of the
    underscored name today, so a future cleanup could silently delete the
    alias. This test makes deletion fail loudly.

    Mutation contract: removing
    ``_create_planner_shared = create_planner_shared`` at ``plan.py:503``
    breaks this import.
    """
    from pflow.execution.plan import _create_planner_shared, create_planner_shared

    assert _create_planner_shared is create_planner_shared, (
        "alias drift: _create_planner_shared should be the same callable as create_planner_shared (set at plan.py:503)."
    )


def test_plan_batch_sub_workflow_output_shape_matches_engine(tmp_path) -> None:
    """Engine↔planner BATCH OUTPUT SHAPE parity — the re-fork net for `build_batch_output`.

    The engine (`_aggregate_batch_results`) and the planner
    (`_build_batch_output_shape`) both delegate the batch output contract to
    the shared `build_batch_output`, so this test is identity-by-construction
    today. It exists to catch the historical bug class (#318, #336, #484, the
    Task 162 under-report): one side re-forking the shape — re-inlining the
    dict literal and drifting a key — passes every unit test on the shared
    builder, because those pin the function, not the call sites. This test
    pins the call sites: the shape downstream parent templates resolve
    against at PLAN time must structurally equal what the engine actually
    writes at RUN time.

    Mutation: re-fork either call site (replace the `build_batch_output` call
    with an inline literal and drop/rename any key, or regress `errors` to
    None) → the key-order or value assertions below fail.
    """
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    write_workflow_file(
        {
            "inputs": {"value": {"type": "string"}},
            "nodes": [{"id": "echo", "type": "shell", "cache": True, "params": {"command": "printf ${value}"}}],
            "edges": [],
            "outputs": {"out": {"source": "${echo.stdout}", "description": "Echoed value"}},
        },
        child_path,
    )
    parent_ir = {
        "inputs": {"items": {"type": "array"}},
        "nodes": [
            {
                "id": "fanout",
                "type": "workflow",
                "params": {"workflow": str(child_path), "inputs": {"value": "${item}"}},
                "batch": {"items": "${items}"},
            }
        ],
        "edges": [],
    }
    write_workflow_file(parent_ir, parent_path)
    params = {"items": ["a", "b"]}

    # ENGINE side: real run; the aggregated batch shape lands in shared_after.
    run_result = _runner_run(parent_path, params)
    assert run_result.success
    engine_shape = run_result.shared_after["fanout"]

    # PLANNER side: plan the same workflow against the same (isolated-default)
    # memo cache the runner wrote, exposing the planner's scratch shared.
    from pflow.execution.plan import _build_plan_with_shared

    compiled, registry = _compile(parent_ir, params=params)
    _plan, planner_shared = _build_plan_with_shared(
        compiled,
        params,
        MemoizationCache(),
        registry,
        workflow_name="parent",
        _parent_workflow_file=str(parent_path),
    )
    planner_shape = planner_shared["fanout"]

    # Key sets AND insertion order, both levels — a re-forked literal that
    # drops, renames, or reorders a key fails here.
    assert list(engine_shape) == list(planner_shape)
    assert list(engine_shape["batch_metadata"]) == list(planner_shape["batch_metadata"])

    # Values the planner must predict exactly for a fully-successful batch.
    for key in ("count", "success_count", "error_count", "errors"):
        assert planner_shape[key] == engine_shape[key], f"engine/planner drift on '{key}'"
    for key in ("parallel", "max_concurrent", "max_retries", "retry_wait", "execution_mode"):
        assert planner_shape["batch_metadata"][key] == engine_shape["batch_metadata"][key], (
            f"engine/planner drift on batch_metadata '{key}'"
        )

    # Intentional difference: the engine measured real timings, the planner
    # never executes. The KEY must exist on both sides; only the value differs.
    assert engine_shape["batch_metadata"]["timing"] is not None
    assert planner_shape["batch_metadata"]["timing"] is None

    # Per-item stamping stayed per-side (engine: during execution; planner:
    # at aggregation) — pin that both sides agree on item + original_index,
    # and that the child's declared output is addressable on both sides.
    assert len(engine_shape["results"]) == len(planner_shape["results"]) == 2
    for idx, item in enumerate(params["items"]):
        for side, shape in (("engine", engine_shape), ("planner", planner_shape)):
            result = shape["results"][idx]
            assert result["item"] == item, f"{side} results[{idx}] item mismatch"
            assert result["original_index"] == idx, f"{side} results[{idx}] original_index mismatch"
            assert "out" in result, f"{side} results[{idx}] missing declared child output 'out'"


# ──────────────────────────────────────────────────────────────────────────────
# Cost parity — plan-predicted cost vs engine-actual spend (issue #506)
#
# The drift suite pinned control-flow and output shape but never compared a
# plan's predicted cost to what the engine actually spent. These tests close
# that blind spot: run a workflow for real (mock LLM with a fixed cost_usd),
# capture engine-actual cost from the trace, build the plan for the same
# workflow, and assert under the plan's declared cost_basis:
#   - "exact"       → predicted == engine-actual
#   - "upper_bound" → predicted >= engine-actual  (a bound below actual is the bug)
# ──────────────────────────────────────────────────────────────────────────────


def test_plan_cost_matches_engine_linear_exact(tmp_path, mock_llm_client) -> None:
    """Linear LLM workflow: plan-predicted cost == engine-actual cost (exact).

    Simplest shape, the canonical agent scenario: run once, edit the first
    prompt, then `--dry-run` to estimate the next run's spend. `b` reads
    `${a.response}`, so invalidating `a` cascades to `b` — a full re-execution,
    which is exactly what the plan predicts (a=boundary, b=downstream BFS).

    Mutation: break `_lookup_last_run_stats` / `_read_stats_from_output` so the
    planner reads $0 (or a wrong number) → predicted drifts from engine-actual
    → this assertion fails.
    """
    cost = 0.002
    mock_llm_client.set_response("*", None, {"response": "x"}, cost_usd=cost)
    path = tmp_path / "linear.pflow.md"

    def _write(first_prompt: str) -> None:
        write_workflow_file(
            {
                "nodes": [
                    {"id": "a", "type": "llm", "params": {"prompt": first_prompt, "model": "gpt-4o-mini"}},
                    {
                        "id": "b",
                        "type": "llm",
                        "params": {"prompt": "Summarize: ${a.response}", "model": "gpt-4o-mini"},
                    },
                ],
                "edges": [{"from": "a", "to": "b"}],
            },
            path,
        )

    _write("draft v1")
    run = _runner_run(path)
    assert run.success
    actual = _engine_cost(run)
    assert actual == pytest.approx(2 * cost)

    # Agent edits the first prompt → `a`'s cache key changes (boundary), and the
    # plan enumerates `b` downstream. Both would-execute, both carry historical
    # cost from the first run.
    _write("draft v2")
    plan = _runner_plan(path)

    assert plan.summary.cost_basis == "exact"
    assert _plan_cost(plan) == pytest.approx(actual)


def test_plan_cost_matches_engine_nested_rollup_exact(tmp_path, mock_llm_client) -> None:
    """Nested sub-workflow: predicted `_including_nested` cost == engine-actual.

    `test_plan_cost_nested_rollup` pins the planner's internal rollup arithmetic
    against the seeded cost; this pins the rollup against what the engine
    actually SPENT — the gap issue #506 closes. The Task 162 review named
    nested cost as exactly where the planner under-report hid.

    Mutation: drop the child's contribution from `_summarize`'s nested rollup
    loop → predicted falls below engine-actual → fails.
    """
    cost = 0.0015
    mock_llm_client.set_response("*", None, {"response": "x"}, cost_usd=cost)
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    def _write_child(prompt_text: str) -> None:
        write_workflow_file(
            {
                "nodes": [
                    {"id": "think", "type": "llm", "params": {"prompt": prompt_text, "model": "gpt-4o-mini"}},
                ],
                "edges": [],
                "outputs": {"out": {"source": "${think.response}", "description": "llm output"}},
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

    _write_child("Consider alpha")
    run = _runner_run(parent_path)
    assert run.success
    actual = _engine_cost(run)
    assert actual == pytest.approx(cost)

    # Edit the child's prompt → its LLM is a miss at plan time → the plan
    # predicts execute and rolls the historical cost up to the parent.
    _write_child("Consider beta")
    plan = _runner_plan(parent_path)

    assert plan.summary.cost_basis == "exact"
    assert _plan_cost(plan) == pytest.approx(actual)


def test_plan_cost_loop_subworkflow_cache_not_underreported(tmp_path, mock_llm_client) -> None:
    """Loop x sub-workflow x cache: predicted cost must not under-report re-execution.

    The Task 162 shape. The inner LLM node is `cache: true`, but the engine's
    `__loop_active__` guard forces re-execution every iteration — so a cap-hit
    loop of 3 spends 3x the inner cost. The planner mirrors this via the
    `__loop_active__` seed; without it the inner node plans as `cached` (~$0)
    and the loop's cost is silently under-reported. cost_basis is `upper_bound`
    (a loop is never exact), so the load-bearing contract is predicted >= actual.

    Mutation: drop the `_loop_active` seed in `create_planner_shared` /
    `_plan_sub_workflow` (plan.py ~537 / ~1141) → inner plans as `cached` →
    predicted collapses below engine-actual → fails.
    """
    cost = 0.002
    mock_llm_client.set_response("*", None, {"response": "x"}, cost_usd=cost)

    # `inner` is the cost-bearing cached LLM (the node the bug mis-plans as
    # cached). `gate` is a deterministic code node that emits the loop's truthy
    # signal — an LLM response is a string, and the engine rejects string
    # truthiness for loop conditions, so the condition must read an int.
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "inner",
                    "type": "llm",
                    "cache": True,
                    "params": {"prompt": "Think.", "model": "gpt-4o-mini"},
                },
                {
                    "id": "gate",
                    "type": "code",
                    "cache": True,
                    "params": {"code": "result: int = 1"},
                },
            ],
            "edges": [],
            "outputs": {"keep": {"source": "${gate.result}", "description": "truthy int → loop to cap"}},
        },
        tmp_path / "body.pflow.md",
    )
    parent = tmp_path / "parent.pflow.md"
    parent.write_text(
        """# Loop over a sub-workflow body

Cap-hit loop; the body has a cached inner LLM the engine re-executes each iteration.

## Steps

### run-body

The loop body — a whole sub-workflow re-run each iteration.

- type: workflow
- workflow: ./body.pflow.md
- loop:
    while: ${run-body.keep}
    max_iterations: 3
""",
        encoding="utf-8",
    )

    run = _runner_run(parent)
    assert run.success
    actual = _engine_cost(run)
    # Cap-hit: 3 iterations, the cached inner re-executes each → 3x the inner cost.
    assert actual == pytest.approx(3 * cost)

    plan = _runner_plan(parent)

    assert plan.summary.cost_basis == "upper_bound"
    predicted = _plan_cost(plan)
    assert predicted >= actual, f"predicted {predicted} under-reports engine-actual {actual}"
    # `>=` above is the load-bearing invariant. The `==` below is an incidental
    # tightness check for this cap-hit shape (actual iterations == max_iterations);
    # it would not hold if the planner ever deliberately over-estimated loops.
    assert predicted == pytest.approx(actual)


def test_plan_cost_matches_engine_batch_subworkflow_exact(tmp_path, mock_llm_client) -> None:
    """Pre-boundary batch sub-workflow: predicted cost == engine-actual (Nx per item).

    Guards the correct path: a batch sub-workflow at the start plans one child
    per item, so the rollup must equal the engine's N LLM calls. Regression pin
    that the per-item path keeps matching real spend.

    Mutation: collapse the per-item recursion to a single iteration → predicted
    becomes 1/N → fails.
    """
    cost = 0.0011
    mock_llm_client.set_response("*", None, {"response": "x"}, cost_usd=cost)
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    write_workflow_file(
        {
            "inputs": {"value": {"type": "string"}},
            "nodes": [
                {"id": "think", "type": "llm", "params": {"prompt": "Process ${value}", "model": "gpt-4o-mini"}},
            ],
            "edges": [],
            "outputs": {"out": {"source": "${think.response}", "description": "out"}},
        },
        child_path,
    )
    write_workflow_file(
        {
            "inputs": {"items": {"type": "array"}},
            "nodes": [
                {
                    "id": "fanout",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {"value": "${item}"}},
                    "batch": {"items": "${items}"},
                },
            ],
            "edges": [],
        },
        parent_path,
    )

    run = _runner_run(parent_path, {"items": ["a", "b", "c"]})
    assert run.success
    actual = _engine_cost(run)
    assert actual == pytest.approx(3 * cost)

    # Plan a run over FRESH items so each child is a miss (would execute); the
    # per-item planner must roll up N x the historical per-item cost.
    plan = _runner_plan(parent_path, {"items": ["x", "y", "z"]})

    assert plan.summary.cost_basis == "exact"
    assert _plan_cost(plan) == pytest.approx(actual)


def test_plan_cost_downstream_batch_subworkflow_is_honest(tmp_path, mock_llm_client) -> None:
    """A batch sub-workflow reached downstream is flagged opaque, never 1/N.

    Issue #506 / task 157: post-boundary the batch was planned as a single
    iteration, reporting 1/N of the real cost — a silent underestimate for a
    cost gate. The fix surfaces an honest "unknown" (opaque, counted in
    `summary.opaque_count`) instead of a wrong number.

    Mutation: revert `_plan_sub_workflow` to plan downstream batches as a single
    force-downstream iteration → `fanout` becomes a `sub_workflow` entry with
    ~1/N cost and `opaque_count` drops to 0 → fails.
    """
    cost = 0.0011
    mock_llm_client.set_response("*", None, {"response": "x"}, cost_usd=cost)
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    write_workflow_file(
        {
            "inputs": {"value": {"type": "string"}},
            "nodes": [
                {"id": "think", "type": "llm", "params": {"prompt": "Process ${value}", "model": "gpt-4o-mini"}},
            ],
            "edges": [],
            "outputs": {"out": {"source": "${think.response}", "description": "out"}},
        },
        child_path,
    )

    def _write_parent(upstream_cmd: str) -> None:
        write_workflow_file(
            {
                "inputs": {"items": {"type": "array"}},
                "nodes": [
                    {"id": "upstream", "type": "shell", "cache": True, "params": {"command": upstream_cmd}},
                    {
                        "id": "fanout",
                        "type": "workflow",
                        "params": {"workflow": str(child_path), "inputs": {"value": "${item}"}},
                        "batch": {"items": "${items}"},
                    },
                ],
                "edges": [{"from": "upstream", "to": "fanout"}],
            },
            parent_path,
        )

    _write_parent("printf v1")
    run = _runner_run(parent_path, {"items": ["a", "b", "c"]})
    assert run.success
    # The engine fans out over all 3 items — so a single-iteration plan is 3x low.
    assert _engine_cost(run) == pytest.approx(3 * cost)

    # Edit upstream → the parent boundaries at `upstream`; BFS reaches the batch
    # `fanout` via the downstream path. Items come from a param so they ARE
    # resolvable here (task 157's "rare resolvable" case) — yet the plan must
    # still refuse to emit a single-iteration cost.
    _write_parent("printf v2")
    plan = _runner_plan(parent_path, {"items": ["a", "b", "c"]})

    fanout = next(e for e in plan.entries if e.node_id == "fanout")
    assert fanout.status == "opaque", (
        f"downstream batch must be honest-opaque, not a 1/N estimate; got {fanout.status!r}"
    )
    assert plan.summary.opaque_count >= 1
    # Carries an accurate cause/message, not the generic "dynamic" reason used
    # for templated `workflow: ${var}` paths — an agent inspecting the opaque
    # entry should see the real reason (issue #506 review).
    assert fanout.cause == "downstream_batch"
    assert "batch downstream, item count unreliable" in format_plan_text(plan)


def test_plan_downstream_batch_respects_depth_guard(tmp_path, monkeypatch) -> None:
    """A downstream batch at max nesting depth must error, not emit clean opaque.

    The opaque early-return for downstream batches must still run the shared
    depth guard (`_precheck_sub_workflow`) — parity with the non-batch path and
    with runtime, which both fail loudly at `MAX_DEPTH_DEFAULT`. Without it, an
    over-depth batch silently plans as a successful opaque node. MAX_DEPTH is
    patched to 0 so a top-level downstream batch (depth 0) trips it on a fresh
    plan — no deep nesting needed (Codex review, PR #517).

    Mutation: drop the `_precheck_sub_workflow` call in `_plan_sub_workflow`'s
    downstream-batch branch → fanout returns opaque, the depth diagnostic
    disappears → fails.
    """
    from pflow.runtime.workflow_executor import WorkflowExecutor

    monkeypatch.setattr(WorkflowExecutor, "MAX_DEPTH_DEFAULT", 0)
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"
    write_workflow_file(
        {
            "inputs": {"value": {"type": "string"}},
            "nodes": [{"id": "echo", "type": "shell", "cache": True, "params": {"command": "printf ${value}"}}],
            "edges": [],
            "outputs": {"out": {"source": "${echo.stdout}", "description": "o"}},
        },
        child_path,
    )
    write_workflow_file(
        {
            "inputs": {"items": {"type": "array"}},
            "nodes": [
                {"id": "upstream", "type": "shell", "cache": True, "params": {"command": "printf go"}},
                {
                    "id": "fanout",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {"value": "${item}"}},
                    "batch": {"items": "${items}"},
                },
            ],
            "edges": [{"from": "upstream", "to": "fanout"}],
        },
        parent_path,
    )

    # Fresh plan: `upstream` is a miss → BFS reaches `fanout` downstream at
    # depth 0, which equals the patched MAX_DEPTH → must surface the depth error,
    # not a clean opaque node.
    plan = _runner_plan(parent_path, {"items": ["a", "b"]})

    fanout = next(e for e in plan.entries if e.node_id == "fanout")
    assert fanout.status != "opaque", "downstream batch at max depth must error, not emit clean opaque"
    assert any("Max sub-workflow depth" in d.message for d in plan.diagnostics)


# ---------------------------------------------------------------------------
# Task 125: the approval-gate parity pin — "plan says would-pause ⟺ engine
# pauses". Compared by node-id SET, not count (a gated loop node is ONE plan
# entry but N pause events), across every gate shape the ledger allows: a
# standard node, a gated workflow-type node, a gate INSIDE the child, and a
# gated loop node. Mutation-verified at authoring time: stamping
# `approval=False` in `_annotate_entry` fails the plan side; skipping
# `run_approval_gate` fails the engine side.
# ---------------------------------------------------------------------------


def _gated_shapes_ir(tmp_path: Path) -> dict[str, Any]:
    child_path = tmp_path / "gated-child.pflow.md"
    write_workflow_file(
        {
            "nodes": [
                {"id": "inner-gate", "type": "shell", "params": {"command": "printf inner"}, "approval": "required"},
            ],
            "edges": [],
        },
        child_path,
    )
    loop_code = "i: int\nresult: dict = {'done': i >= 2}"
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "plain", "type": "shell", "params": {"command": "printf plain"}},
            {"id": "gated-shell", "type": "shell", "params": {"command": "printf gated"}, "approval": "required"},
            {
                "id": "gated-sub",
                "type": "workflow",
                "params": {"workflow": str(child_path)},
                "approval": "required",
            },
            {
                "id": "gated-loop",
                "type": "code",
                "params": {"code": loop_code, "inputs": {"i": "${__iteration__}"}},
                "approval": "required",
                "loop": {"until": "${gated-loop.result.done}", "max_iterations": 3},
            },
        ],
        "edges": [
            {"from": "plain", "to": "gated-shell"},
            {"from": "gated-shell", "to": "gated-sub"},
            {"from": "gated-sub", "to": "gated-loop"},
        ],
        "start_node": "plain",
    }


def _flatten_gated_ids(entries: list[Any]) -> set[str]:
    gated: set[str] = set()
    for entry in entries:
        if entry.approval:
            gated.add(entry.node_id)
        if entry.sub_plan is not None:
            gated |= _flatten_gated_ids(entry.sub_plan.entries)
    return gated


@pytest.mark.trace_files
def test_plan_would_pause_matches_engine_gate_pauses(tmp_path, monkeypatch) -> None:
    import json

    from pflow.core.gate import GateResolution
    from pflow.runtime.workflow_trace import WorkflowTraceCollector

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    ir = _gated_shapes_ir(tmp_path)
    registry = Registry()
    cache = MemoizationCache(read_enabled=True)

    # Plan side: gated entries by node-id set, nested sub-plans included.
    compiled = compile_workflow(ir, registry=registry)
    plan = build_plan(compiled, {}, cache, registry, workflow_name="gated-shapes")
    plan_gated = _flatten_gated_ids(plan.entries)

    # Engine side: a REAL run (auto-approving resolver — the test never prompts),
    # gate pause events read from the streamed trace (gate lines are disk-only).
    collector = WorkflowTraceCollector(
        "gated-shapes", workflow_path=str(tmp_path / "gated-shapes.pflow.md"), is_run_scoped=True, stream_to_disk=True
    )
    shared: dict[str, Any] = {
        "__gate_resolver__": lambda request, *, allow_prompt=True: GateResolution(approved=True, resolved_via="flag")
    }
    engine = WorkflowEngine(trace_collector=collector)
    try:
        compiled_for_run = compile_workflow(ir, registry=Registry())
        engine.run(compiled_for_run, shared)
    finally:
        collector.finalize()
    pause_lines = [
        json.loads(line)
        for line in collector._stream_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and '"gate"' in line
    ]
    pauses = [ln for ln in pause_lines if ln.get("kind") == "gate" and ln.get("phase") == "pause"]
    engine_gated = {ln["node_id"] for ln in pauses}

    assert plan_gated == engine_gated == {"gated-shell", "gated-sub", "inner-gate", "gated-loop"}
    # The SET comparison is load-bearing: the gated loop node pauses per
    # iteration (2 real iterations) but is exactly one plan entry.
    loop_pauses = [ln for ln in pauses if ln["node_id"] == "gated-loop"]
    assert len(loop_pauses) == 2, f"expected one pause per loop iteration, got {len(loop_pauses)}"


def test_dry_run_renders_approval_tag_and_footer(tmp_path) -> None:
    ir = _gated_shapes_ir(tmp_path)
    registry = Registry()
    compiled = compile_workflow(ir, registry=registry)
    plan = build_plan(compiled, {}, MemoizationCache(read_enabled=True), registry, workflow_name="gated-shapes")

    text = format_plan_text(plan)
    assert "gated-shell  [shell, approval]" in text
    assert ", approval]" in text.split("gated-sub")[1].splitlines()[0]  # sub-workflow line carries the tag
    assert "pause for approval at run time" in text
    assert "--auto-approve=gated-shell" in text

    from pflow.execution.formatters.plan_formatter import format_plan_json

    document = format_plan_json(plan)
    by_id = {e["node_id"]: e for e in document["plan"]}
    assert by_id["gated-shell"].get("approval") is True
    assert by_id["gated-sub"].get("approval") is True
    assert "approval" not in by_id["plain"]


def test_cached_gated_node_not_stamped_and_engine_skips_gate(tmp_path) -> None:
    """A cache HIT never gates (the engine seam sits after the cache early-return),
    so the plan must not stamp `approval` on a cached entry — else the ⏸ footer and
    JSON `approval` field promise a pause the engine won't make (deep-review find:
    the safe-direction half of the parity invariant, unpinned until now)."""
    from pflow.core.gate import GateResolution

    ir = {
        "nodes": [
            {
                "id": "gated-cached",
                "type": "shell",
                "cache": True,
                "params": {"command": "printf gated"},
                "approval": "required",
            },
        ],
        "edges": [],
    }
    compiled, registry = _compile(ir)
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # Seed: real run through the gate (auto-approving resolver), which memo-caches.
    prompts: list[str] = []

    def approve(request, *, allow_prompt=True):
        prompts.append(request.node_id)
        return GateResolution(approved=True, resolved_via="flag")

    shared: dict[str, Any] = {"__gate_resolver__": approve, "__memoization_cache__": cache}
    WorkflowEngine().run(compiled, shared)
    assert prompts == ["gated-cached"], "seed run must gate once"

    # Plan side: the entry is cached → NOT stamped, absent from the footer/JSON.
    plan = build_plan(compiled, {}, cache, registry, workflow_name="gated-cached")
    (entry,) = plan.entries
    assert entry.status == "cached"
    assert entry.approval is False
    assert "pause for approval" not in format_plan_text(plan)

    # Engine side: the second run cache-hits and never invokes the resolver again.
    shared2: dict[str, Any] = {"__gate_resolver__": approve, "__memoization_cache__": cache}
    WorkflowEngine().run(compiled, shared2)
    assert prompts == ["gated-cached"], "cache hit must not re-gate"
