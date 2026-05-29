"""Regression test for the silent cache-corruption bug in iteration loops.

The canonical iteration pattern — a sub-workflow batched with ``parallel: false``
that reads filesystem state mutated by the previous iteration — was silently
broken under the old cache-by-default behavior. A side-effecting shell node whose
declared inputs don't change between iterations (e.g. ``cat queue.txt``) produced
the same memo cache key every iteration, so iteration 2+ re-served iteration 1's
stdout forever. The queue mutation on disk was invisible to the cache, so items
got reprocessed and the loop reported success the whole time.

After the cache-defaults flip, non-``llm`` nodes do not cache by default, so the
shell node re-executes each iteration and reads the current filesystem state.

Load-bearing assertion: there are NO ``cache: false`` annotations anywhere in
these workflows. The pattern must work correctly with the new defaults out of
the box. If you revert the Phase 1 cache flip, this test fails — iteration 2+
re-processes the stale (full) queue and the log accumulates duplicates.

Note: variable names ``true``/``false``/``null`` are reserved as literal
keywords in templates (see Optional A) — these workflows use ordinary
identifiers, so that limitation does not apply here.
"""

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


def test_sub_workflow_batch_iteration_reads_fresh_filesystem_state(tmp_path):
    """A read-queue → take → write-back loop must process each item exactly once.

    Five items, five sequential iterations, each iteration takes the first item
    off the queue and logs it. With correct (uncached) behavior the log ends
    with five distinct items and the queue drains to empty. With the old cached
    behavior the log fills with duplicates of the first item(s).
    """
    queue_file = tmp_path / "queue.txt"
    log_file = tmp_path / "log.txt"

    # Seed: five distinct items, one per line; empty log.
    queue_file.write_text("A\nB\nC\nD\nE\n", encoding="utf-8")
    log_file.write_text("", encoding="utf-8")

    inner_path = tmp_path / "inner.pflow.md"
    inner_path.write_text(
        f"""\
# Inner Iteration Step

Reads the queue, takes the first item, writes the rest back, and logs the item.

## Inputs

### iteration

The current iteration index (unused by logic; proves per-item input wiring).

- type: integer

## Steps

### read-queue

Read the current queue from disk. Deliberately input-free so its memo cache
key is identical across iterations — this is what the old cache-by-default
behavior would (wrongly) hit, re-serving iteration 1's stdout forever.

- type: shell

```shell command
cat {queue_file}
```

### take-and-write

Take the first item, append it to the log, write the remainder back.

- type: shell
- inputs:
    raw: ${{read-queue.stdout}}
    iteration: ${{iteration}}

```shell command
: "iteration ${{iteration}}"
printf '%s\\n' "${{raw}}" | sed '/^$/d' | head -n 1 >> {log_file}
printf '%s\\n' "${{raw}}" | sed '/^$/d' | tail -n +2 > {queue_file}
```
""",
        encoding="utf-8",
    )

    outer_path = tmp_path / "outer.pflow.md"
    outer_path.write_text(
        f"""\
# Outer Iteration Driver

Runs the inner step five times, sequentially, over the on-disk queue.

## Steps

### iterate

Batch the inner workflow once per index, sequentially.

- type: workflow
- workflow: {inner_path}
- inputs:
    iteration: ${{item}}
- batch:
    items: [1, 2, 3, 4, 5]
    parallel: false
""",
        encoding="utf-8",
    )

    runner = WorkflowRunner()
    # Default RunnerConfig keeps the memo cache ENABLED — this is what exposes
    # the bug under the old defaults. Do NOT disable the cache here.
    result = runner.run(str(outer_path), {}, RunnerConfig())
    assert result.success, f"Iteration workflow failed: {result.errors}"

    log_lines = [line for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    remaining = [line for line in queue_file.read_text(encoding="utf-8").splitlines() if line.strip()]

    # Each of the five items must be processed exactly once — no duplicates.
    assert log_lines == ["A", "B", "C", "D", "E"], (
        f"Expected each item logged exactly once in order; got {log_lines!r}. "
        f"Duplicates indicate the read-queue node was served stale cached output "
        f"instead of re-reading the mutated queue file."
    )
    assert len(set(log_lines)) == 5, f"Items were reprocessed (cache served stale data): {log_lines!r}"

    # The queue must have drained completely.
    assert remaining == [], f"Queue did not drain — expected empty, got {remaining!r}"
