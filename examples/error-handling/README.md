# Error Handling Examples

Workflows demonstrating pflow's error handling — `on-error` routing, `??` coalesce, loop recovery, typo hints, and source-line tracking in diagnostics.

> Note: the simple "read file, fall back on failure" pattern lives at `examples/core/error-handling.pflow.md`. This directory covers the less obvious cases — what happens when you reference a failed node's output, when coalesce operands are mixed absent/failed, when you typo a field on a failed node, etc.

## Dual purpose: teaching examples + regression fixtures

These workflows double as regression fixtures for the Task 148 failed-node invariant fix ([GH #208](https://github.com/spinje/pflow/issues/208)). `tests/test_integration/test_failed_node_invariant.py` loads them via `WorkflowRunner` and asserts on the rendered diagnostic text an AI agent would see.

**Don't rename, move, or delete files here without checking `test_failed_node_invariant.py`.** Same rule as `examples/invalid/`.

## Fixtures

| File | Demonstrates |
|---|---|
| `failed-node-direct-reference.pflow.md` | Referencing a failed node's output directly (without `??`) produces a structured error with real failure details (exit_code, command, stderr) and a paste-able coalesce fix using a real peer node name |
| `typo-on-failed-node.pflow.md` | When you typo a field on a failed node (`${primary.stddout}`), the error surfaces BOTH the failure (primary signal) AND the typo correction (secondary hint), and the paste-able fix uses the corrected field |
| `coalesce-mixed-absent-failed.pflow.md` | A coalesce `${never_run.x ?? fails.y}` with one absent operand and one failed operand errors loudly with the "All coalesce operands are unavailable" summary block — it does NOT silently skip (that was the Task 128 bug class) |
| `loop-recovery.pflow.md` | A node fails on visit 1, succeeds on visit 2. The loop guard clears the stale `__failures__` entry, the workflow reports success, and downstream references see the visit-2 data |
| `source-line-multi-output.pflow.md` | Multiple output declarations at different lines — the diagnostic's `At:` line points at the exact failing output, not the last output or the top of the file |
| `source-line-heavy-offsets.pflow.md` | Heavy blank-line padding and prose before the Outputs section — the parser's line tracker handles real-world offsets without off-by-N errors |

## Running them

```bash
# Each one is a runnable workflow — expect a failure (by design) for all
# except loop-recovery.pflow.md:
pflow examples/error-handling/failed-node-direct-reference.pflow.md --no-cache --no-trace
pflow examples/error-handling/typo-on-failed-node.pflow.md --no-cache --no-trace
pflow examples/error-handling/loop-recovery.pflow.md --no-cache --no-trace
```
