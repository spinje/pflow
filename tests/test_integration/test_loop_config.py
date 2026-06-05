"""End-to-end engine coverage for the `loop:` config block (issue #445, Phase 4/5).

Each test writes a small workflow and runs it through `WorkflowRunner`, asserting
the re-entry behavior: drain-to-empty, single iteration, cap-hit advisory,
`${__iteration__}` exposure + post-loop isolation, loop-then-branch routing, and
the cache-staleness guard (an inner `cache: true` node re-executes each iteration).
"""

from pflow.core.diagnostic import Severity
from pflow.core.workflow.status import WorkflowStatus
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


def _run(tmp_path, body: str, name="wf.pflow.md"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return WorkflowRunner().run(str(p), {}, RunnerConfig())


_DRAIN = """# Drain

Drain a computed list to empty.

## Steps

### counter

Shrinking list — drains by one each iteration.

- type: code
- inputs:
    iteration: ${__iteration__}

```python code
iteration: int
result: list = list(range(max(0, START - iteration)))
```

- loop:
    while: ${counter.result}
    max_iterations: 10
"""


def test_drain_to_empty_stops_on_falsy(tmp_path) -> None:
    r = _run(tmp_path, _DRAIN.replace("START", "3"))
    assert r.success
    sa = r.shared_after
    assert sa["__execution__"]["node_visit_counts"]["counter"] == 3
    assert sa["counter"]["result"] == []
    assert sa["counter"]["loop_stopped"] == "condition"
    assert "__iteration__" not in sa  # cleared on exit


def test_single_iteration_when_immediately_falsy(tmp_path) -> None:
    # START=1 → iteration 1 yields range(0) == [] → stop after one run.
    r = _run(tmp_path, _DRAIN.replace("START", "1"))
    assert r.success
    assert r.shared_after["__execution__"]["node_visit_counts"]["counter"] == 1


def test_iteration_is_one_based_in_body(tmp_path) -> None:
    body = """# Iter

Record the iteration number each pass.

## Steps

### counter

Record the iteration and whether to keep looping.

- type: code
- inputs:
    iteration: ${__iteration__}

```python code
iteration: int
result: dict = {"n": iteration, "more": iteration < 2}
```

- loop:
    while: ${counter.result.more}
    max_iterations: 10
"""
    r = _run(tmp_path, body)
    assert r.success
    # Ran twice (iteration 1 more=True, iteration 2 more=False) — last n == 2.
    assert r.shared_after["counter"]["result"]["n"] == 2
    assert r.shared_after["__execution__"]["node_visit_counts"]["counter"] == 2


_CAP = """# Cap

Never drains; capped, then a post-loop node.

## Steps

### counter

Always truthy.

- type: code
- inputs:
    iteration: ${__iteration__}

```python code
iteration: int
result: int = iteration
```

- next: after
- loop:
    while: ${counter.result}
    max_iterations: 3

### after

Post-loop node.

- type: shell
- command: echo done
"""


def test_cap_hit_is_non_degrading_advisory(tmp_path) -> None:
    r = _run(tmp_path, _CAP)
    assert r.success
    assert r.status == WorkflowStatus.SUCCESS  # INFO advisory does not degrade
    sa = r.shared_after
    assert sa["__execution__"]["node_visit_counts"]["counter"] == 3
    assert sa["counter"]["loop_stopped"] == "max_iterations"
    advisory = sa["__warnings__"]["counter"]
    assert advisory.severity == Severity.INFO
    assert advisory.id == "loop.max-iterations-reached"


def test_cap_hit_advisory_in_result_diagnostics(tmp_path) -> None:
    r = _run(tmp_path, _CAP)
    infos = [d for d in r.diagnostics if d.severity == Severity.INFO]
    assert any(d.id == "loop.max-iterations-reached" for d in infos)


def test_post_loop_node_runs_and_iteration_cleared(tmp_path) -> None:
    r = _run(tmp_path, _CAP)
    sa = r.shared_after
    assert sa["after"]["stdout"].strip() == "done"
    assert "__iteration__" not in sa


def test_cap_hit_respects_lowered_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PFLOW_MAX_NODE_VISITS", "50")
    # Use a default-capped loop (no explicit max_iterations) that never drains;
    # it should stop at the loop's own cap (MAX_NODE_VISITS) without raising.
    import importlib

    from pflow.runtime.engine import instrumentation

    importlib.reload(instrumentation)
    try:
        body = """# Default cap

Never drains; default cap.

## Steps

### counter

Always truthy — relies on the default cap to stop.

- type: code
- inputs:
    iteration: ${__iteration__}

```python code
iteration: int
result: int = 1
```

- loop:
    while: ${counter.result}
"""
        r = _run(tmp_path, body)
        assert r.success
        assert r.shared_after["counter"]["loop_stopped"] == "max_iterations"
        assert r.shared_after["__execution__"]["node_visit_counts"]["counter"] == 50
    finally:
        monkeypatch.delenv("PFLOW_MAX_NODE_VISITS", raising=False)
        importlib.reload(instrumentation)


def test_error_mid_loop_stops_and_fails(tmp_path) -> None:
    body = """# Error loop

Fails on the second iteration.

## Steps

### counter

Fails on the second iteration.

- type: code
- inputs:
    iteration: ${__iteration__}

```python code
iteration: int
if iteration >= 2:
    raise ValueError("boom")
result: int = 1
```

- loop:
    while: ${counter.result}
    max_iterations: 10
"""
    r = _run(tmp_path, body)
    assert not r.success
    # Ran twice (iteration 1 ok, iteration 2 raised), then stopped.
    assert r.shared_after["__execution__"]["node_visit_counts"]["counter"] == 2
    assert "__iteration__" not in r.shared_after  # cleared even on the error path


def test_downstream_node_reads_loop_stopped_marker(tmp_path) -> None:
    """Mirrors the ported orchestrate.pflow.md flagship shape: a `loop:` node
    followed by a `summarize` node that turns `${loop.loop_stopped}` into a
    human status. Guards that the engine-injected marker is a valid downstream
    output reference (registered in extract_node_outputs) and resolves correctly.
    """
    # condition branch (clean drain)
    drain = """# Marker drain

Loop drains, then summarize reads why it stopped.

## Steps

### counter

Shrinking list.

- type: code
- inputs:
    iteration: ${__iteration__}

```python code
iteration: int
result: list = list(range(max(0, 2 - iteration)))
```

- next: summarize
- loop:
    while: ${counter.result}
    max_iterations: 5

### summarize

Report why the loop stopped.

- type: code
- inputs:
    stopped: ${counter.loop_stopped}

```python code
stopped: str
result: str = "drained" if stopped == "condition" else "capped"
```
"""
    r = _run(tmp_path, drain)
    assert r.success, r.errors
    assert r.shared_after["counter"]["loop_stopped"] == "condition"
    assert r.shared_after["summarize"]["result"] == "drained"

    # max_iterations branch (cap hit)
    capped = drain.replace("max(0, 2 - iteration)", "max(1, 9 - iteration)").replace(
        "max_iterations: 5", "max_iterations: 2"
    )
    r2 = _run(tmp_path, capped, name="capped.pflow.md")
    assert r2.success, r2.errors
    assert r2.shared_after["counter"]["loop_stopped"] == "max_iterations"
    assert r2.shared_after["summarize"]["result"] == "capped"


def test_error_action_during_loop_routes_to_on_error(tmp_path) -> None:
    """An error ACTION (not exception) on iteration N skips re-entry and routes to
    the on-error handler — a distinct code path from the exception case."""
    body = """# Error action loop

Loop routes to on-error on the third iteration.

## Steps

### worker

Emit a result; on iteration 3 route to the error handler.

- type: code
- on-error: recover
- inputs:
    iteration: ${__iteration__}

```python code
iteration: int
result: int = 1
if iteration >= 3:
    next: str = "error"
```

- loop:
    while: ${worker.result}
    max_iterations: 10

### recover

Recovery handler.

- type: shell
- next: end
- command: echo recovered
"""
    r = _run(tmp_path, body)
    assert r.success
    assert r.status == WorkflowStatus.DEGRADED  # recovered via on-error
    sa = r.shared_after
    assert sa["__execution__"]["node_visit_counts"]["worker"] == 3
    assert sa["recover"]["stdout"].strip() == "recovered"
    assert "__iteration__" not in sa  # cleared before routing to on-error


def test_carry_loop_error_action_archives_failed_iteration_for_on_error(tmp_path) -> None:
    """A carried loop that routes to on-error must not expose stale carried output.

    The failed iteration is archived in __failures__; the active shared store no
    longer exposes the worker's stale successful output under `worker`.
    """
    body = """# Carry error action loop

Carry state until iteration 2 fails and routes to the handler.

## Steps

### worker

Advance state, then fail on the second iteration.

- type: code
- on-error: recover
- inputs:
    state: 0
    iteration: ${__iteration__}

```python code
state: int
iteration: int
next_state = state + 1
result: dict = {"state": next_state, "more": True}
if iteration >= 2:
    next: str = "error"
```

- loop:
    carry:
      state: ${worker.result.state}
    while: ${worker.result.more}
    max_iterations: 5

### recover

Recovery handler.

- type: shell
- next: end
- command: echo recovered
"""
    r = _run(tmp_path, body)
    assert r.success
    assert r.status == WorkflowStatus.DEGRADED
    sa = r.shared_after
    assert sa["__execution__"]["node_visit_counts"]["worker"] == 2
    assert "worker" in sa["__failures__"]
    assert "worker" not in sa
    assert sa["__failures__"]["worker"]["data"]["result"]["state"] == 2
    assert sa["recover"]["stdout"].strip() == "recovered"


def test_iteration_threaded_into_sub_workflow_inputs(tmp_path) -> None:
    """Flagship pattern: ${__iteration__} is resolved in the parent and passed to a
    looped sub-workflow's inputs each iteration; the child output drives the drain."""
    child = tmp_path / "child.pflow.md"
    child.write_text(
        """# Child

Emit a shrinking list keyed off the iteration handed in by the parent.

## Inputs

### iteration

The 1-based loop iteration from the parent.

- type: integer

## Outputs

### remaining

Items still pending after this iteration.

- type: array
- source: ${shrink.result}

## Steps

### shrink

Shrink the list by the iteration count.

- type: code
- inputs:
    iteration: ${iteration}

```python code
iteration: int
result: list = list(range(max(0, 3 - iteration)))
```
""",
        encoding="utf-8",
    )
    outer = tmp_path / "outer.pflow.md"
    outer.write_text(
        f"""# Outer

Loop the child, threading the iteration count in.

## Steps

### loop-child

Run the child until its remaining list drains.

- type: workflow
- workflow: {child}
- inputs:
    iteration: ${{__iteration__}}
- loop:
    while: ${{loop-child.remaining}}
    max_iterations: 10
""",
        encoding="utf-8",
    )
    r = WorkflowRunner().run(str(outer), {}, RunnerConfig())
    assert r.success, r.errors
    sa = r.shared_after
    assert sa["__execution__"]["node_visit_counts"]["loop-child"] == 3
    assert sa["loop-child"]["remaining"] == []
    assert sa["loop-child"]["loop_stopped"] == "condition"


def test_carry_tournament_threads_previous_survivors_into_next_round(tmp_path) -> None:
    child = tmp_path / "judge-round.pflow.md"
    log_path = tmp_path / "rounds.jsonl"
    child.write_text(
        """# Judge Round

## Inputs

### contenders

Current contenders.

- type: array

### log_path

Round log path.

- type: string

## Outputs

### survivors

Survivors for the next round.

- type: array
- source: ${judge.result.survivors}

### more

Whether another round is needed.

- type: boolean
- source: ${judge.result.more}

## Steps

### judge

Keep every other contender and log the input this round received.

- type: code
- inputs:
    contenders: ${contenders}
    log_path: ${log_path}

```python code
import json

contenders: list
log_path: str
survivors = contenders[::2] if len(contenders) > 1 else contenders
with open(log_path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(contenders) + "\\n")
result: dict = {"survivors": survivors, "more": len(survivors) > 1}
```
""",
        encoding="utf-8",
    )
    outer = tmp_path / "tournament.pflow.md"
    outer.write_text(
        f"""# Tournament

## Steps

### run-rounds

Run elimination rounds.

- type: workflow
- workflow: {child}
- inputs:
    contenders: ["ada", "beck", "cy", "dee"]
    log_path: {log_path}
- loop:
    carry:
      contenders: ${{run-rounds.survivors}}
    while: ${{run-rounds.more}}
    max_iterations: 10
""",
        encoding="utf-8",
    )

    r = WorkflowRunner().run(str(outer), {}, RunnerConfig())
    assert r.success, r.errors
    assert r.shared_after["__execution__"]["node_visit_counts"]["run-rounds"] == 2
    assert r.shared_after["run-rounds"]["survivors"] == ["ada"]

    import json

    rounds = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert rounds == [["ada", "beck", "cy", "dee"], ["ada", "cy"]]


def test_workflow_body_carry_typo_rejected_before_runtime(tmp_path) -> None:
    """Workflow-body carry refs must be checked against declared child outputs.

    This is the primary user-facing shape for stateful loops. It exercises the
    child-workflow output registration path, which is distinct from code-node
    `result` output validation.
    """
    child = tmp_path / "judge-round.pflow.md"
    child.write_text(
        """# Judge Round

## Inputs

### contenders

Current contenders.

- type: array

## Outputs

### survivors

Survivors for the next round.

- type: array
- source: ${judge.result.survivors}

### more

Whether another round is needed.

- type: boolean
- source: ${judge.result.more}

## Steps

### judge

Keep every other contender.

- type: code
- inputs:
    contenders: ${contenders}

```python code
contenders: list
survivors = contenders[::2] if len(contenders) > 1 else contenders
result: dict = {"survivors": survivors, "more": len(survivors) > 1}
```
""",
        encoding="utf-8",
    )
    outer = tmp_path / "bad-carry.pflow.md"
    outer.write_text(
        f"""# Bad Carry

## Steps

### run-rounds

Run elimination rounds.

- type: workflow
- workflow: {child}
- inputs:
    contenders: ["ada", "beck", "cy", "dee"]
- loop:
    carry:
      contenders: ${{run-rounds.surviviors}}
    while: ${{run-rounds.more}}
    max_iterations: 10
""",
        encoding="utf-8",
    )

    r = WorkflowRunner().run(str(outer), {}, RunnerConfig())
    assert not r.success
    assert any("does not declare output 'surviviors'" in err.message for err in r.errors)


def test_until_poll_runs_until_truthy(tmp_path) -> None:
    body = """# Poll

## Steps

### wait

Done on the third check.

- type: code
- inputs:
    iteration: ${__iteration__}

```python code
iteration: int
result: dict = {"done": iteration >= 3}
```

- loop:
    until: ${wait.result.done}
    max_iterations: 5
"""
    r = _run(tmp_path, body)
    assert r.success, r.errors
    assert r.shared_after["__execution__"]["node_visit_counts"]["wait"] == 3
    assert r.shared_after["wait"]["loop_stopped"] == "condition"


def test_until_absent_runtime_source_continues_to_cap(tmp_path) -> None:
    """Absent `until:` source must not silently exit after one iteration."""
    body = """# Missing Until

## Steps

### wait

Never emits result.done.

- type: code

```python code
result: dict = {"still_missing": True}
```

- loop:
    until: ${wait.result.done}
    max_iterations: 3
"""
    r = _run(tmp_path, body)
    assert r.success, r.errors
    assert r.shared_after["__execution__"]["node_visit_counts"]["wait"] == 3
    assert r.shared_after["wait"]["loop_stopped"] == "max_iterations"


def test_validate_fix_carries_draft_and_feedback_pair(tmp_path) -> None:
    body = """# Validate Fix

## Steps

### fix

Carry both the draft and the next feedback.

- type: code
- inputs:
    iteration: ${__iteration__}
    draft: a
    feedback: b

```python code
iteration: int
draft: str
feedback: str
result: dict = {
    "draft": draft + feedback,
    "feedback": "!",
    "more": iteration < 3,
}
```

- loop:
    carry:
      draft: ${fix.result.draft}
      feedback: ${fix.result.feedback}
    while: ${fix.result.more}
    max_iterations: 5
"""
    r = _run(tmp_path, body)
    assert r.success, r.errors
    assert r.shared_after["__execution__"]["node_visit_counts"]["fix"] == 3
    assert r.shared_after["fix"]["result"]["draft"] == "ab!!"


def test_carry_preserves_constant_inputs(tmp_path) -> None:
    body = """# Constant Carry

## Steps

### step

Carry state but keep label constant.

- type: code
- inputs:
    state: 0
    label: fixed

```python code
state: int
label: str
next_state = state + 1
result: dict = {"state": next_state, "label": label, "more": state < 2}
```

- loop:
    carry:
      state: ${step.result.state}
    while: ${step.result.more}
    max_iterations: 5
"""
    r = _run(tmp_path, body)
    assert r.success, r.errors
    assert r.shared_after["step"]["result"]["state"] == 3
    assert r.shared_after["step"]["result"]["label"] == "fixed"


def test_no_carry_loop_leaves_static_inputs_unchanged(tmp_path) -> None:
    body = """# No Carry

## Steps

### step

Loop without carry.

- type: code
- inputs:
    seed: 5
    iteration: ${__iteration__}

```python code
seed: int
iteration: int
result: dict = {"seed": seed, "more": iteration < 2}
```

- loop:
    while: ${step.result.more}
    max_iterations: 5
"""
    r = _run(tmp_path, body)
    assert r.success, r.errors
    assert r.shared_after["__execution__"]["node_visit_counts"]["step"] == 2
    assert r.shared_after["step"]["result"]["seed"] == 5


def test_no_carry_loop_without_inputs_does_not_trip_carry_guard(tmp_path) -> None:
    """A no-carry loop with NO inputs must never enter the carry path.

    This guards the shared `is_carry_iteration` gate's specificity. If the gate
    regressed to fire for any loop on iteration > 1 (dropping its `carry` conjunct),
    this node — which has no `template_config` and no resolved inputs — would raise
    `LoopCarryError` ("no inputs mapping" from the engine guard, or "no template
    configuration" from `carry_effective_config`) on round 2. Running cleanly to the
    cap proves carry stays inert for non-carry loops.
    """
    body = """# No Inputs Loop

## Steps

### step

Always continue; runs to the cap.

- type: code

```python code
result: dict = {"more": True}
```

- loop:
    while: ${step.result.more}
    max_iterations: 2
"""
    r = _run(tmp_path, body)
    assert r.success, r.errors
    assert r.shared_after["__execution__"]["node_visit_counts"]["step"] == 2
    assert r.shared_after["step"]["loop_stopped"] == "max_iterations"


def test_permissive_mode_still_raises_for_unresolved_carry(tmp_path) -> None:
    child = tmp_path / "dynamic-child.pflow.md"
    child.write_text(
        """# Dynamic Child

## Inputs

### state

Carried state.

- type: string

## Outputs

### done

Never done.

- type: boolean
- source: ${emit.result.done}

## Steps

### emit

Emit no carried field.

- type: code

```python code
result: dict = {"done": False}
```
""",
        encoding="utf-8",
    )
    ir = {
        "ir_version": "0.1.0",
        "template_resolution_mode": "permissive",
        "inputs": {"child_path": {"type": "string", "required": False, "default": str(child)}},
        "nodes": [
            {
                "id": "run",
                "type": "workflow",
                "params": {
                    "workflow": "${child_path}",
                    "inputs": {"state": "seed"},
                },
                "loop": {
                    "carry": {"state": "${run.missing}"},
                    "until": "${run.done}",
                    "max_iterations": 3,
                },
            }
        ],
        "edges": [],
    }

    r = WorkflowRunner().run(ir, {}, RunnerConfig())
    assert not r.success
    assert any("carried input 'state' did not resolve" in err.message for err in r.errors)


def test_templated_max_iterations_caps_at_runtime(tmp_path) -> None:
    """`max_iterations: ${cap}` resolves at loop entry and caps the iteration count."""
    body = """# Templated cap

## Inputs

### cap

The iteration cap.

- type: integer

## Steps

### counter

Always truthy — relies on the templated cap to stop.

- type: code
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
    r = WorkflowRunner().run(str(p), {"cap": 2}, RunnerConfig())
    assert r.success
    assert r.shared_after["__execution__"]["node_visit_counts"]["counter"] == 2
    assert r.shared_after["counter"]["loop_stopped"] == "max_iterations"


def test_templated_max_iterations_bad_value_fails_run(tmp_path) -> None:
    """A `${cap}` that resolves to a non-positive-int at runtime fails the run with
    a LoopConditionError rather than silently defaulting or looping forever."""
    body = """# Bad templated cap

## Inputs

### cap

The (invalid) iteration cap.

- type: any

## Steps

### counter

Always truthy; cap resolves to 0 at runtime.

- type: code
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
    p = tmp_path / "badcap.pflow.md"
    p.write_text(body, encoding="utf-8")
    r = WorkflowRunner().run(str(p), {"cap": 0}, RunnerConfig())
    assert not r.success
    assert any("max_iterations" in d.message for d in r.errors)


def test_inner_loop_inside_subworkflow_converges(tmp_path) -> None:
    """An inner loop node inside a sub-workflow whose PARENT does NOT loop — the
    inner loop drains and neither ${__iteration__} nor __loop_active__ leaks.

    True two-level nesting (both levels looping, which exercises the
    __loop_active__ depth counter at depth 2) is covered by
    test_nested_loops_both_converge below."""
    inner = tmp_path / "inner.pflow.md"
    inner.write_text(
        """# Inner

A self-contained loop that drains its own list, exposing the final length.

## Outputs

### remaining

Always 0 once the inner loop drains.

- type: integer
- source: ${tick.result.len}

## Steps

### tick

Inner loop body — drains a computed list.

- type: code
- inputs:
    iteration: ${__iteration__}

```python code
iteration: int
_keep = list(range(max(0, 2 - iteration)))
result: dict = {"keep": _keep, "len": len(_keep)}
```

- loop:
    while: ${tick.result.keep}
    max_iterations: 5
""",
        encoding="utf-8",
    )
    state = tmp_path / "outer_state.txt"
    state.write_text("X\nY\n", encoding="utf-8")
    # Outer loop drives the child until a filesystem queue drains. The child also
    # exposes `pending` (queue length) that the outer loops on.
    outer = tmp_path / "outer.pflow.md"
    outer.write_text(
        f"""# Outer

Outer loop over a child that itself loops.

## Steps

### run-inner

Run the inner (which loops internally), then shrink the outer queue.

- type: workflow
- workflow: {inner}
- next: take

### take

Remove one line from the outer queue and report remaining count.

- type: shell

```shell command
tail -n +2 {state} > {state}.tmp && mv {state}.tmp {state}
wc -l < {state} | tr -d ' '
```
""",
        encoding="utf-8",
    )
    # NOTE: keep the outer simple — the point is the INNER loop runs inside a
    # sub-workflow. Run once and confirm the inner loop converged + no leaks.
    r = WorkflowRunner().run(str(outer), {}, RunnerConfig())
    assert r.success, r.errors
    sa = r.shared_after
    assert sa["run-inner"]["remaining"] == 0  # inner loop drained
    assert "__iteration__" not in sa
    assert "__loop_active__" not in sa


def test_cache_guard_deactivates_after_loop(tmp_path) -> None:
    """The `__loop_active__` memo-read suppression is scoped to the loop subtree:
    a `cache: true` node AFTER the loop must still serve from the memo cache on a
    second run (deactivation side of the guard — the plan's explicit check)."""
    body = """# Deactivation

A loop, then a cached node downstream of it.

## Steps

### counter

Drains a computed list.

- type: code
- inputs:
    iteration: ${__iteration__}

```python code
iteration: int
result: list = list(range(max(0, 2 - iteration)))
```

- next: after
- loop:
    while: ${counter.result}
    max_iterations: 5

### after

Deterministic cached node downstream of the loop.

- type: code
- cache: true

```python code
result: int = 42
```
"""
    p = tmp_path / "deact.pflow.md"
    p.write_text(body, encoding="utf-8")
    runner = WorkflowRunner()
    r1 = runner.run(str(p), {}, RunnerConfig())
    assert r1.success
    # First run populates the memo cache; `after` was not a hit.
    assert "after" not in r1.shared_after.get("__cache_hits__", [])
    # Second run: the loop re-executes (no memo), but `after` — outside the loop
    # subtree, so __loop_active__ is cleared by then — serves from the memo cache.
    r2 = runner.run(str(p), {}, RunnerConfig())
    assert r2.success
    assert "after" in r2.shared_after.get("__cache_hits__", [])


def test_cache_staleness_guard_drains_despite_inner_cache_true(tmp_path) -> None:
    """A looped sub-workflow with an input-free `cache: true` node must re-read
    fresh filesystem state each iteration — without the guard it would serve
    iteration 1's stdout forever and cap-hit instead of draining."""
    state = tmp_path / "state.txt"
    state.write_text("A\nB\nC\n", encoding="utf-8")
    inner = tmp_path / "inner.pflow.md"
    inner.write_text(
        f"""# Inner

Reports remaining lines, then removes the first.

## Outputs

### remaining

Lines remaining in the queue before this take.

- type: integer
- source: ${{count.result}}

## Steps

### read

cache:true; identical inputs each call.

- type: shell
- cache: true

```shell command
wc -l < {state} | tr -d ' '
```

### count

Parse the remaining-line count to an int.

- type: code
- inputs:
    raw: ${{read.stdout}}

```python code
raw: str
result: int = int(raw.strip() or 0)
```

- next: take

### take

Remove the first queue line.

- type: shell

```shell command
tail -n +2 {state} > {state}.tmp && mv {state}.tmp {state}
```
""",
        encoding="utf-8",
    )
    outer = tmp_path / "outer.pflow.md"
    outer.write_text(
        f"""# Outer

Drain via a looped sub-workflow.

## Steps

### loop-take

Run the inner take-step until the queue drains.

- type: workflow
- workflow: {inner}
- loop:
    while: ${{loop-take.remaining}}
    max_iterations: 10
""",
        encoding="utf-8",
    )
    r = WorkflowRunner().run(str(outer), {}, RunnerConfig())  # cache ENABLED
    assert r.success, r.errors
    assert r.shared_after["loop-take"]["remaining"] == 0
    assert r.shared_after["loop-take"]["loop_stopped"] == "condition"
    # Queue fully drained — proves `read` re-executed each iteration.
    assert [ln for ln in state.read_text().splitlines() if ln.strip()] == []
    assert "__loop_active__" not in r.shared_after  # guard cleared after loop


def test_nested_loops_both_converge(tmp_path) -> None:
    """A TRUE two-level loop nest: an outer `loop:` node whose sub-workflow body
    itself contains a `loop:` node. Exercises the __loop_active__ depth counter at
    depth 2, proves the inner loop's exit doesn't clear the outer's suppression,
    that the two ${__iteration__} counters don't collide (mapped isolation), and
    that neither marker leaks."""
    inner = tmp_path / "inner.pflow.md"
    inner.write_text(
        """# Inner

Runs an internal loop, then removes one item from the outer queue file.

## Inputs

### queue_file

Path to the outer queue file (shared filesystem state across outer iterations).

- type: string
- required: true

## Outputs

### pending

Remaining lines in the outer queue after this call.

- type: integer
- source: ${drain.result.remaining}

## Steps

### tick

Inner loop body — drains a computed in-memory list using the iteration counter.

- type: code
- next: drain
- inputs:
    iteration: ${__iteration__}

```python code
iteration: int
_keep = list(range(max(0, 2 - iteration)))
result: dict = {"keep": _keep, "len": len(_keep)}
```

- loop:
    while: ${tick.result.keep}
    max_iterations: 5

### drain

Remove one line from the outer queue file; report the remaining count.

- type: code
- inputs:
    queue_file: ${queue_file}

```python code
import pathlib
queue_file: str
_p = pathlib.Path(queue_file)
_lines = [ln for ln in _p.read_text().splitlines() if ln.strip()]
_rest = _lines[1:]
_p.write_text("\\n".join(_rest) + ("\\n" if _rest else ""))
result: dict = {"remaining": len(_rest)}
```
""",
        encoding="utf-8",
    )
    state = tmp_path / "outer_queue.txt"
    state.write_text("A\nB\nC\n", encoding="utf-8")
    outer = tmp_path / "outer.pflow.md"
    outer.write_text(
        f"""# Outer

Outer loop over a child workflow that itself loops internally.

## Steps

### run-inner

Run the inner workflow (which loops internally + shrinks the queue), repeating
until the outer queue drains.

- type: workflow
- workflow: {inner}
- inputs:
    queue_file: {state}
- loop:
    while: ${{run-inner.pending}}
    max_iterations: 5
""",
        encoding="utf-8",
    )
    r = WorkflowRunner().run(str(outer), {}, RunnerConfig())
    assert r.success, r.errors
    sa = r.shared_after
    # Outer drained on condition (queue empty), not on the cap.
    assert sa["run-inner"]["pending"] == 0
    assert sa["run-inner"]["loop_stopped"] == "condition"
    # All three queue lines removed → the outer actually looped (not single-passed)
    # and the inner re-ran each outer iteration.
    assert [ln for ln in state.read_text().splitlines() if ln.strip()] == []
    # Neither loop marker leaks past the depth-2 nest.
    assert "__iteration__" not in sa
    assert "__loop_active__" not in sa
