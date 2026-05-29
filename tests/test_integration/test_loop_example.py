"""Regression guard for the Loops worked example in the branching guide.

This reproduces **Example A** (the self-contained int-counter worker/checker
loop) from ``src/pflow/guide/features/branching.md`` (lines ~152-195) and runs
it end-to-end. It guards that the documented loop actually executes and
terminates — closing the "verify the example itself runs" gap (a guide example
that silently rots to something broken misleads agents who copy it).

Maintenance contract: this is a hand-copied reproduction. If you edit the Loops
example in ``branching.md``, update the workflow string below to match. The test
runs a copy, so it guards the runtime capability the doc claims — it cannot
detect that the doc text itself drifted.

Note: the section also carries a prose note that the worker can be a
``workflow`` node (the loop body becomes a whole sub-workflow). That's a
one-line variation on this same structure, not a separate runnable example, so
there's nothing additional to guard here.

Pattern: mirrors ``tests/test_integration/test_iteration_pattern.py`` — write an
inline ``.pflow.md`` to ``tmp_path`` and run via ``WorkflowRunner``.
"""

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner

# Example A verbatim (branching.md ~152-195), wrapped in a workflow title +
# `## Steps` heading so the step fragment becomes a complete workflow.
LOOP_EXAMPLE_WORKFLOW = """\
# Loop Example (branching guide)

Reproduces the int-counter worker/checker loop from the branching guide's
Loops section, used as an execution regression guard.

## Steps

### worker

Increment the running count. `worker` is a branch target of `checker`'s
loop-back edge, so it needs an explicit `- next:`.

- type: code
- inputs:
    prior: ${checker.result ?? 0}
- next: checker

```python code
prior: int
result: int = prior + 1
```

### checker

Decide whether to loop or finish.

- type: code
- inputs: { count: "${worker.result}" }
- next: worker, done

```python code
count: int
result: int = count
if count >= 3:
    next: str = "done"
else:
    next: str = "worker"
```

### done

Report the final count.

- type: shell
- next: end

```shell command
echo "Looped ${worker.result} times"
```
"""


def test_branching_guide_loop_example_runs_and_terminates(tmp_path):
    """The documented worker/checker loop runs, loops exactly 3 times, exits."""
    workflow_path = tmp_path / "loop-example.pflow.md"
    workflow_path.write_text(LOOP_EXAMPLE_WORKFLOW, encoding="utf-8")

    result = WorkflowRunner().run(str(workflow_path), {}, RunnerConfig())
    assert result.success, f"Loop example failed: {[d.message for d in result.errors]}"

    # The loop must terminate at the documented threshold: worker runs on visits
    # 1→2→3, checker exits when count reaches 3. Pins the loop behavior rather
    # than just "it didn't crash" (same technique as
    # test_conditional_branching.py::test_loop_with_exit_condition).
    visit_counts = result.shared_after["__execution__"]["node_visit_counts"]
    assert visit_counts["worker"] == 3, visit_counts

    # The `done` node reports the final count via stdout.
    assert "Looped 3 times" in result.shared_after["done"]["stdout"]
