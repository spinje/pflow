"""Targeted tests for batch sub-workflow dry-run planning."""

from __future__ import annotations

from pflow.execution.plan import _aggregate_batch_child_plans, build_plan
from pflow.execution.result import Plan, PlanEntry, PlanSummary, RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.registry import Registry
from pflow.runtime import compile_workflow
from pflow.runtime.cache import MemoizationCache
from tests.shared.markdown_utils import write_workflow_file


def _summary(**overrides) -> PlanSummary:
    base = {
        "total": 0,
        "cached_count": 0,
        "execute_count": 0,
        "cache_boundary": None,
        "execute_by_type": {},
        "estimated_cost_usd": 0.0,
        "nodes_without_history": 0,
    }
    base.update(overrides)
    return PlanSummary(**base)


def _plan_workflow_file(path, params: dict | None = None):
    return WorkflowRunner().plan(str(path), params or {}, RunnerConfig())


def _run_workflow_file(path, params: dict | None = None):
    return WorkflowRunner().run(str(path), params or {}, RunnerConfig())


def test_plan_batch_sub_workflow_populates_outputs_for_downstream_resolution(tmp_path) -> None:
    """Batch sub-workflow planning must populate parent shared outputs for downstream nodes."""
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
                    "params": {"command": "printf ${value}"},
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
                },
                {
                    "id": "post",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": "printf '${fanout.results[0].out}-${fanout.count}'"},
                },
            ],
            "edges": [{"from": "fanout", "to": "post"}],
        },
        parent_path,
    )

    run_result = _run_workflow_file(parent_path, {"items": ["a", "b"]})
    assert run_result.success

    plan = _plan_workflow_file(parent_path, {"items": ["a", "b"]})

    assert [entry.status for entry in plan.entries] == ["sub_workflow", "cached"]
    fanout = plan.entries[0]
    assert fanout.batch_count == 2
    assert fanout.sub_plan is not None
    assert len(fanout.sub_plan.entries) == 1
    child_entry = fanout.sub_plan.entries[0]
    assert child_entry.status == "cached"
    assert child_entry.batch_items_cached == 2
    assert child_entry.batch_items_total == 2


def test_plan_batch_sub_workflow_detects_partial_cache_per_item(tmp_path) -> None:
    """Changing one batch item should produce partial child cache counts."""
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
                    "params": {"command": "printf ${value}"},
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

    run_result = _run_workflow_file(parent_path, {"items": ["a", "b"]})
    assert run_result.success

    plan = _plan_workflow_file(parent_path, {"items": ["a", "c"]})

    fanout = plan.entries[0]
    assert fanout.status == "sub_workflow"
    assert fanout.batch_count == 2
    assert fanout.sub_plan is not None

    child_entry = fanout.sub_plan.entries[0]
    assert child_entry.status == "execute"
    assert child_entry.batch_items_cached == 1
    assert child_entry.batch_items_total == 2
    assert fanout.sub_plan.summary.cached_count == 1
    assert fanout.sub_plan.summary.execute_count == 1


def test_plan_batch_sub_workflow_empty_items_produces_empty_sub_plan(tmp_path) -> None:
    """An empty batch should plan as zero child work instead of failing item resolution."""
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
                    "params": {"command": "printf ${value}"},
                }
            ],
            "edges": [],
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

    plan = _plan_workflow_file(parent_path, {"items": []})

    fanout = plan.entries[0]
    assert fanout.status == "sub_workflow"
    assert fanout.batch_count == 0
    assert fanout.sub_plan is not None
    assert fanout.sub_plan.entries == []
    assert fanout.sub_plan.summary.execute_count == 0


def test_plan_batch_sub_workflow_non_list_items_surfaces_error(tmp_path) -> None:
    """A batch items template that resolves to a non-list must produce a diagnostic."""
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
                    "params": {"command": "printf ${value}"},
                }
            ],
            "edges": [],
        },
        child_path,
    )
    write_workflow_file(
        {
            "inputs": {"items": {"type": "string"}},
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

    plan = _plan_workflow_file(parent_path, {"items": "not-a-list"})

    assert plan.entries[0].status == "execute"
    assert plan.entries[0].diagnostic is not None
    assert "expected list" in plan.entries[0].diagnostic.message


def test_plan_batch_sub_workflow_unresolvable_items_is_opaque(tmp_path) -> None:
    """Unresolvable batch items should produce an opaque entry instead of a false error."""
    child_path = tmp_path / "child.pflow.md"
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "echo",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": "printf child"},
                }
            ],
            "edges": [],
        },
        child_path,
    )
    ir = {
        "nodes": [
            {
                "id": "fanout",
                "type": "workflow",
                "params": {
                    "workflow": str(child_path),
                    "inputs": {"value": "${item}"},
                },
                "batch": {"items": "${missing.items}"},
            }
        ],
        "edges": [],
    }
    registry = Registry()
    compiled = compile_workflow(ir, registry=registry, initial_params={})
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    plan = build_plan(compiled, {}, cache, registry, workflow_name="opaque-batch")

    assert plan.entries[0].status == "opaque"
    assert plan.entries[0].cause == "dynamic"
    assert plan.summary.opaque_count == 1


def test_aggregate_batch_child_plans_parallel_duration_uses_max() -> None:
    """Parallel batch duration must use max(item), while sequential uses sum(item)."""
    child_plans = [
        Plan(
            workflow="child.pflow.md",
            entries=[PlanEntry(node_id="echo", node_type="ShellNode", status="execute", cause="no_cache_match")],
            summary=_summary(
                total=1,
                execute_count=1,
                execute_by_type={"ShellNode": 1},
                estimated_duration_ms=2000.0,
                total_including_nested=1,
                execute_including_nested=1,
                execute_by_type_including_nested={"ShellNode": 1},
                estimated_duration_ms_including_nested=2000.0,
            ),
        ),
        Plan(
            workflow="child.pflow.md",
            entries=[PlanEntry(node_id="echo", node_type="ShellNode", status="execute", cause="no_cache_match")],
            summary=_summary(
                total=1,
                execute_count=1,
                execute_by_type={"ShellNode": 1},
                estimated_duration_ms=5000.0,
                total_including_nested=1,
                execute_including_nested=1,
                execute_by_type_including_nested={"ShellNode": 1},
                estimated_duration_ms_including_nested=5000.0,
            ),
        ),
    ]

    parallel = _aggregate_batch_child_plans(child_plans, batch_parallel=True)
    sequential = _aggregate_batch_child_plans(child_plans, batch_parallel=False)

    assert parallel.summary.estimated_duration_ms == 5000.0
    assert parallel.summary.estimated_duration_ms_including_nested == 5000.0
    assert sequential.summary.estimated_duration_ms == 7000.0
    assert sequential.summary.estimated_duration_ms_including_nested == 7000.0


def test_aggregate_batch_child_plans_sums_costs_without_average_times_count() -> None:
    """Synthetic batch summary cost must sum per-item costs, not average and multiply."""
    child_plans = [
        Plan(
            workflow="child.pflow.md",
            entries=[
                PlanEntry(
                    node_id="answer",
                    node_type="LLMNode",
                    status="execute",
                    cause="no_cache_match",
                    last_cost_usd=0.10,
                )
            ],
            summary=_summary(
                total=1,
                execute_count=1,
                execute_by_type={"LLMNode": 1},
                estimated_cost_usd=0.10,
                total_including_nested=1,
                execute_including_nested=1,
                execute_by_type_including_nested={"LLMNode": 1},
                estimated_cost_usd_including_nested=0.10,
            ),
        ),
        Plan(
            workflow="child.pflow.md",
            entries=[
                PlanEntry(
                    node_id="answer",
                    node_type="LLMNode",
                    status="execute",
                    cause="no_cache_match",
                    last_cost_usd=0.30,
                )
            ],
            summary=_summary(
                total=1,
                execute_count=1,
                execute_by_type={"LLMNode": 1},
                estimated_cost_usd=0.30,
                total_including_nested=1,
                execute_including_nested=1,
                execute_by_type_including_nested={"LLMNode": 1},
                estimated_cost_usd_including_nested=0.30,
            ),
        ),
    ]

    aggregated = _aggregate_batch_child_plans(child_plans, batch_parallel=False)

    assert aggregated.summary.estimated_cost_usd == 0.40
    assert aggregated.summary.estimated_cost_usd_including_nested == 0.40
    assert aggregated.entries[0].last_cost_usd == 0.20


def test_plan_batch_sub_workflow_branching_child_reports_correct_per_node_status(tmp_path) -> None:
    """Branch-local nodes show fully cached when all items traversing them hit cache.

    Regression guard for the batch_items_total fix: using len(entries_for_node)
    instead of batch_count prevents branch-local nodes from appearing as partial
    misses when they were actually cached for every item that took that branch.
    """
    child_path = tmp_path / "child.pflow.md"
    parent_path = tmp_path / "parent.pflow.md"

    child_path.write_text(
        """\
# Branching Child
Routes items to different branches.

## Inputs

### value
The routing value.
- type: string
- required: true

## Steps

### route
Route based on value.
- type: code
- cache: true
- inputs:
    value: ${value}

```python code
value: str

result: str = value
if value == "a":
    next: str = "fast"
else:
    next: str = "slow"
```

### fast
Fast branch target.
- type: shell
- cache: true
- next: end

```shell command
printf 'fast-${value}'
```

### slow
Slow branch target.
- type: shell
- cache: true
- next: end

```shell command
printf 'slow-${value}'
```
""",
        encoding="utf-8",
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

    run_result = _run_workflow_file(parent_path, {"items": ["a", "b"]})
    assert run_result.success

    plan = _plan_workflow_file(parent_path, {"items": ["a", "b"]})

    fanout = plan.entries[0]
    assert fanout.status == "sub_workflow"
    assert fanout.batch_count == 2
    assert fanout.sub_plan is not None

    entries_by_id = {e.node_id: e for e in fanout.sub_plan.entries}
    route_entry = entries_by_id["route"]
    assert route_entry.status == "cached"
    assert route_entry.batch_items_cached == 2
    assert route_entry.batch_items_total == 2

    fast_entry = entries_by_id["fast"]
    assert fast_entry.status == "cached"
    assert fast_entry.batch_items_cached == 1
    assert fast_entry.batch_items_total == 1

    slow_entry = entries_by_id["slow"]
    assert slow_entry.status == "cached"
    assert slow_entry.batch_items_cached == 1
    assert slow_entry.batch_items_total == 1

    assert fanout.sub_plan.summary.execute_count == 0


def test_plan_batch_sub_workflow_non_dict_per_item_inputs_emits_warning(tmp_path) -> None:
    """When one batch item's inputs resolve to non-dict, a WARNING diagnostic surfaces.

    Runtime would raise ValueError; the planner falls back to item[0]'s inputs
    but honestly warns that this item will fail at execution time.
    """
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
                    "params": {"command": "printf ${value}"},
                }
            ],
            "edges": [],
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
                        "inputs": "${item}",
                    },
                    "batch": {"items": "${items}"},
                }
            ],
            "edges": [],
        },
        parent_path,
    )

    plan = _plan_workflow_file(parent_path, {"items": [{"value": "ok"}, "broken-string"]})

    fanout = plan.entries[0]
    assert fanout.status == "sub_workflow"
    assert fanout.sub_plan is not None

    warnings = [d for d in fanout.sub_plan.diagnostics if d.severity.name == "WARNING"]
    assert len(warnings) == 1
    assert "item 1" in warnings[0].message.lower() or "Batch item 1" in warnings[0].message
    assert "str" in warnings[0].message
