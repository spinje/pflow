"""Dry-run planner parity for the `loop:` config block (issue #445, Phase 6).

The planner walks a loop body ONCE and multiplies its single-pass estimate by
the resolved `max_iterations` upper bound. This test runs the engine N times
(a cap-hit loop where actual iterations == max_iterations) and asserts the
planner predicts the same Nx cost/duration — no existing test exercises repeats.
"""

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner

# Cap-hit loop: `result` is always truthy, so it runs exactly max_iterations
# times. `cache: true` records per-iteration duration history for the planner.
_CAP_LOOP = """# Parity cap loop

Never drains; cap 4.

## Steps

### counter

Always truthy — runs exactly max_iterations times.

- type: code
- cache: true
- inputs:
    iteration: ${__iteration__}

```python code
iteration: int
result: int = 1
```

- loop:
    while: ${counter.result}
    max_iterations: 4
"""


def test_planner_predicts_n_times_engine_iterations(tmp_path) -> None:
    p = tmp_path / "parity.pflow.md"
    p.write_text(_CAP_LOOP, encoding="utf-8")
    runner = WorkflowRunner()

    # 1) Run the engine — records N-iteration duration history.
    result = runner.run(str(p), {}, RunnerConfig())
    assert result.success
    n = result.shared_after["__execution__"]["node_visit_counts"]["counter"]
    assert n == 4  # cap-hit: actual iterations == max_iterations

    # 2) Plan it.
    plan = runner.plan(str(p), {}, RunnerConfig())
    entry = next(e for e in plan.entries if e.node_id == "counter")

    # The loop node is annotated with the resolved upper bound...
    assert entry.loop_iterations == n
    # ...the plan is upper_bound (a loop is never an exact estimate)...
    assert plan.summary.cost_basis == "upper_bound"
    # ...and the summary duration is N x the single-pass estimate.
    assert entry.last_duration_ms is not None
    assert abs(plan.summary.estimated_duration_ms - n * entry.last_duration_ms) < 1e-6


_LOOP_SUBWF_PARENT = """# Loop over a sub-workflow body

Cap-hit loop whose body is a sub-workflow containing a cached inner node.

## Steps

### run-body

The loop body — a whole sub-workflow re-run each iteration.

- type: workflow
- workflow: ./body.pflow.md
- loop:
    while: ${run-body.keep}
    max_iterations: 3
"""

_LOOP_SUBWF_BODY = """# Loop body

One deterministic cached inner node; emits an always-truthy output so the
parent loop hits its cap.

## Steps

### inner

Deterministic and cached — the node whose plan status we assert. At runtime the
loop re-executes it each iteration (memo read suppressed under __loop_active__);
the planner must model the same, not report it cached.

- type: code
- cache: true

```python code
result: int = 1
```

## Outputs

### keep

Always truthy → the parent loop runs to its cap.

- source: ${inner.result}
"""


def test_planner_models_looped_subworkflow_inner_cache_as_execute(tmp_path) -> None:
    """Regression for the loop x sub-workflow x cache cost under-report (#445).

    The engine propagates ``__loop_active__`` into a looped sub-workflow's child
    store (``_PROPAGATED_KEYS``), so inner cached nodes re-execute each
    iteration. The planner must mirror this: ``create_planner_shared`` forwards
    ``loop_active`` so the inner node plans as ``execute``, not ``cached``.
    Without that propagation the planner reports the inner node cached (~$0) and
    under-reports the loop's cost. A cached status here would be the bug.
    """
    (tmp_path / "body.pflow.md").write_text(_LOOP_SUBWF_BODY, encoding="utf-8")
    parent = tmp_path / "parent.pflow.md"
    parent.write_text(_LOOP_SUBWF_PARENT, encoding="utf-8")
    runner = WorkflowRunner()

    # 1) Run — cap-hit (3 iterations); populates the inner node's memo cache.
    result = runner.run(str(parent), {}, RunnerConfig())
    assert result.success

    # 2) Plan — the inner cached node must model as EXECUTE, mirroring the
    #    engine's per-iteration re-execution under the propagated loop flag.
    plan = runner.plan(str(parent), {}, RunnerConfig())
    body_entry = next(e for e in plan.entries if e.node_id == "run-body")
    assert body_entry.sub_plan is not None
    inner = next(e for e in body_entry.sub_plan.entries if e.node_id == "inner")
    assert inner.status == "execute", f"inner node planned as {inner.status!r}, expected 'execute' (loop cache parity)"


def test_planner_uses_template_cap_upper_bound(tmp_path) -> None:
    body = """# Template cap

## Inputs

### cap

The iteration cap.

- type: integer

## Steps

### counter

Always truthy — capped by a templated max_iterations.

- type: code
- cache: true
- inputs:
    iteration: ${__iteration__}
    cap: ${cap}

```python code
iteration: int
cap: int
result: int = 1
```

- loop:
    while: ${counter.result}
    max_iterations: ${cap}
"""
    p = tmp_path / "tmpl.pflow.md"
    p.write_text(body, encoding="utf-8")
    runner = WorkflowRunner()
    plan = runner.plan(str(p), {"cap": 5}, RunnerConfig())
    entry = next(e for e in plan.entries if e.node_id == "counter")
    assert entry.loop_iterations == 5
