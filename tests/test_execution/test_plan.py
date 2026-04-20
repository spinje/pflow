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


def test_build_plan_surfaces_opaque_count_for_cost_gate_agents(tmp_path) -> None:
    """Opaque sub-workflows increment `opaque_count` so agents can refuse to proceed.

    Without this signal, an agent cost-gating on `estimated_cost_usd_including_nested`
    sees $0 for a workflow whose `workflow: ${var}` sub-tree could cost anything.
    `nodes_without_history` is LLM-specific and doesn't catch this case.

    Mutation: remove the `if entry.status == "opaque": opaque_count += 1`
    branch in `_compute_totals` → this assertion fails (agent has no signal
    that an unplannable region exists).
    """
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

    assert plan.entries[0].status == "opaque"
    assert plan.summary.opaque_count == 1
    # No nested aggregation when there are no sub_plans to merge.
    assert plan.summary.opaque_count_including_nested is None


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


def test_build_plan_circular_subworkflow_emits_error_diagnostic(tmp_path) -> None:
    """Circular sub-workflow references are surfaced as ERROR-severity diagnostics.

    Severity is load-bearing for the CLI exit-code contract: `_display_plan_result`
    exits 1 only on ERROR-severity diagnostics. Cycles, max-depth, resolve
    failures, and bad `inputs:` shapes all reach `_sub_workflow_error_entry` —
    each represents a workflow that would fail at runtime, so the plan must
    signal "don't run this" via exit code.

    Mutation: revert `_sub_workflow_error_entry` to `Severity.WARNING` →
    the severity assertion below fails and `test_dry_run_circular_subworkflow_exits_one`
    starts seeing exit 0.
    """
    from pflow.core.diagnostic import Severity

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

    cycle_diags = [d for d in plan.diagnostics if "Circular sub-workflow reference" in d.message]
    assert cycle_diags, f"Expected cycle diagnostic, got: {[d.message for d in plan.diagnostics]}"
    assert all(d.severity == Severity.ERROR for d in cycle_diags), (
        f"Cycle diagnostics must be ERROR severity for CLI exit-1 contract. "
        f"Got: {[(d.message, d.severity) for d in cycle_diags]}"
    )


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


def test_plan_no_cross_pollution_between_distinct_inline_workflows() -> None:
    """Two distinct inline workflows with overlapping node IDs must not pool cache history.

    Before the L2 fix, both inline workflows wrote cache rows with
    `workflow_path = NULL`. SQL `WHERE workflow_path = NULL` matches zero
    rows, so scoped `get_latest_for_node` calls fell back to unscoped
    lookup — matching every NULL row regardless of source workflow. Two
    workflows sharing a node ID (common idiom: `classify`, `summarize`)
    would pool their histories, giving agents polluted cost/duration
    estimates in `--dry-run`.

    After the fix, each inline run writes with an IR-content synthetic
    `_pflow_workflow_file` (`ir-hash:...`), keeping lookups scoped.

    This test runs BOTH workflows through the real `WorkflowRunner().run()`
    pipeline against the shared isolated cache (via `isolate_pflow_config`),
    so it catches regressions at the synthesis site — removing the
    `_synthesize_inline_workflow_id(...)` call from `_prepare_workflow`
    makes this test fail: scoped lookups match whichever NULL row was
    written last, and the assertions on per-workflow stdout differ.
    """
    ir_a = {
        "nodes": [{"id": "classify", "type": "shell", "params": {"command": "echo A"}}],
        "edges": [],
    }
    ir_b = {
        "nodes": [{"id": "classify", "type": "shell", "params": {"command": "echo B"}}],
        "edges": [],
    }

    # Run both through the full runner pipeline. `isolate_pflow_config`
    # redirects both to the same isolated cache.db.
    result_a = WorkflowRunner().run(ir_a, {}, RunnerConfig())
    result_b = WorkflowRunner().run(ir_b, {}, RunnerConfig())

    assert result_a.success and result_b.success, (
        f"Prereq — both runs must succeed. A={result_a.errors} B={result_b.errors}"
    )

    path_a = result_a.shared_after["_pflow_workflow_file"]
    path_b = result_b.shared_after["_pflow_workflow_file"]
    assert path_a != path_b, (
        "Distinct IRs must produce distinct synthetic paths. Mutation-check: "
        "removing `_synthesize_inline_workflow_id` in _prepare_workflow makes both None."
    )

    # Open a fresh handle to the same cache (isolated via Path.home redirect).
    cache = MemoizationCache()

    entry_a = cache.get_latest_for_node("classify", workflow_path=path_a)
    entry_b = cache.get_latest_for_node("classify", workflow_path=path_b)

    assert entry_a is not None, "Workflow A cache entry missing after execution"
    assert entry_b is not None, "Workflow B cache entry missing after execution"

    output_a, _ = entry_a
    output_b, _ = entry_b

    assert output_a.get("stdout", "").strip() == "A", (
        f"Workflow A's scoped lookup polluted by B: stdout={output_a.get('stdout')!r}"
    )
    assert output_b.get("stdout", "").strip() == "B", (
        f"Workflow B's scoped lookup polluted by A: stdout={output_b.get('stdout')!r}"
    )


def test_extract_cost_rejects_non_finite_floats() -> None:
    """Cost extraction must reject NaN and Inf.

    `json.dumps` emits non-standard `NaN` / `Infinity` literals (invalid per
    RFC 8259), which strict parsers like `jq` reject. Silently propagating
    such values into `summary.estimated_cost_usd` breaks agent cost-gating
    scripts (`jq '.summary.estimated_cost_usd > 1'`).

    Mutation: remove `and math.isfinite(raw)` in `_extract_cost_from_llm_usage`
    → this assertion fails (NaN / Inf leak through as finite floats).
    """
    from pflow.execution.plan import _extract_cost_from_llm_usage

    assert _extract_cost_from_llm_usage({"cost_usd": float("nan")}) is None
    assert _extract_cost_from_llm_usage({"cost_usd": float("inf")}) is None
    assert _extract_cost_from_llm_usage({"cost_usd": float("-inf")}) is None
    # Valid finite floats still pass through.
    assert _extract_cost_from_llm_usage({"cost_usd": 0.05}) == 0.05
    assert _extract_cost_from_llm_usage({"cost_usd": 0}) == 0.0
