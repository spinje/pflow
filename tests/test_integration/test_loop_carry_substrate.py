"""Regression coverage for the pre-Task-166 loop self-reference substrate.

These fixtures intentionally use the manual ``${self.output ?? seed}`` pattern,
not the new ``loop.carry`` surface. They prove the existing runtime substrate
still threads a loop node's previous output into its next input.
"""

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


def _run(tmp_path, body: str, name: str = "wf.pflow.md"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return WorkflowRunner().run(str(path), {}, RunnerConfig())


def test_manual_self_reference_threads_prior_output(tmp_path) -> None:
    body = """# Self Reference

## Steps

### tick

Accumulate via this node's own previous output.

- type: code
- inputs:
    prev: ${tick.result.acc ?? 0}
- loop:
    while: ${tick.result.keep_going}
    max_iterations: 5

```python code
prev: int
acc = prev + 1
result: dict = {"acc": acc, "keep_going": acc < 4}
```
"""
    r = _run(tmp_path, body)
    assert r.success, r.errors
    assert r.shared_after["tick"]["result"]["acc"] == 4
    assert r.shared_after["tick"]["loop_stopped"] == "condition"


def test_manual_subworkflow_self_reference_threads_prior_output(tmp_path) -> None:
    child = tmp_path / "child-inc.pflow.md"
    child.write_text(
        """# Child Increment

## Inputs

### n

The current accumulator value.

- type: integer
- required: true

## Outputs

### n_plus

The incremented accumulator.

- type: integer
- source: ${inc.result.n_plus}

### more

Whether to keep looping.

- type: boolean
- source: ${inc.result.more}

## Steps

### inc

Increment and decide whether to continue.

- type: code
- inputs: { n: "${n}" }

```python code
n: int
result: dict = {"n_plus": n + 1, "more": (n + 1) < 3}
```
""",
        encoding="utf-8",
    )
    body = f"""# Subworkflow Carry Substrate

## Steps

### count

Loop the child with manual self-reference carry.

- type: workflow
- workflow: {child}
- inputs:
    n: ${{count.n_plus ?? 0}}
- loop:
    while: ${{count.more}}
    max_iterations: 10
"""
    r = _run(tmp_path, body)
    assert r.success, r.errors
    assert r.shared_after["count"]["n_plus"] == 3
    assert r.shared_after["count"]["loop_stopped"] == "condition"


def test_coalesce_fallback_can_reference_workflow_input_seed(tmp_path) -> None:
    body = """# Coalesce Ref Seed

## Inputs

### seed_val

Round-1 seed provided as a workflow input.

- type: integer
- required: false
- default: 10

## Steps

### tick

Seed round 1 from a referenced workflow input via coalesce fallback.

- type: code
- inputs:
    prev: ${tick.result.acc ?? seed_val}
- loop:
    while: ${tick.result.keep_going}
    max_iterations: 5

```python code
prev: int
acc = prev + 1
result: dict = {"acc": acc, "keep_going": acc < 13}
```
"""
    r = _run(tmp_path, body)
    assert r.success, r.errors
    assert r.shared_after["tick"]["result"]["acc"] == 13
    assert r.shared_after["tick"]["loop_stopped"] == "condition"
