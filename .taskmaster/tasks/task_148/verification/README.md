# Task 148 Verification Corpus

Adversarial verification workflows built during the Post-Completion Verification Pass (2026-04-07) — the first of the six review passes after the initial Task 148 implementation was declared "complete".

**Goal at the time**: *try to break the work, not confirm it*. Every workflow here was designed to probe one dimension of the new failed-node invariant or error-UX rendering path.

## Origin and impact

This corpus found **3 real bugs** that the initial unit-test suite missed. All three were boundary bugs — places where one layer's output became the next layer's input without a consistency check:

1. **BUG #1 (critical)** — `output_resolver._diagnose_unresolved_output` silently skipped ALL unresolved coalesce expressions in output declarations, including when operands had FAILED (not just all-absent). `03_both_fail.pflow.md` and `23_mixed_absent_failed.pflow.md` exposed it: workflow produced empty output instead of erroring loudly. This was exactly the bug class Task 148 was supposed to prevent.

2. **BUG #2 (high)** — `execution_state.py` used the singular `__execution__["failed_node"]` pointer to determine per-node display status. Multi-failure workflows showed only the LAST failed node as "failed"; earlier ones fell through to "not_executed" — a lie in JSON output that AI agents would consume.

3. **BUG #3 (medium)** — `--report` summary for the GH #208 repro showed `"Unknown error"` instead of the actual failure text, violating a Task 148 spec acceptance criterion.

The corpus was later reused as a rendering-baseline reference for every subsequent review pass (fixture-by-fixture diff before and after each refactor, to catch accidental rendering regressions).

## What lives here now

**18 fixtures** that stayed in the corpus but were not promoted to committed regression tests, plus **`inspect_shared.py`** (the verification harness). They're preserved here as a historical record and a ready-made corpus for any future adversarial pass on the Task 148 invariants.

All 18 parse, validate, and run end-to-end under current code. Two fixtures (`17_source_line_block.pflow.md` and `22_routing_error.pflow.md`) were edited during the task-148 rebase pass to match Task 147's parser hardening — see the header comments in those two files for the specific parser contract each one exercises (code-block fence name for 17; dynamic-form `next:` detection for 22).

| File | Scenario |
|---|---|
| `01_python_exception.pflow.md` | Python code node raises; exception path archives to `__failures__` |
| `02_ignore_errors_empty.pflow.md` | `ignore_errors: true` + empty stdout stays succeeded (does not fall through coalesce) |
| `03_both_fail.pflow.md` | Both coalesce operands fail → structured error with "All operands unavailable" summary |
| `05_node_param_both_fail.pflow.md` | Node-param coalesce (not output coalesce) — both operands failed |
| `06_three_way_coalesce.pflow.md` | 3-operand coalesce with middle one absent |
| `07_coalesce_subfield.pflow.md` | Coalesce on a nested field path |
| `10_batch_partial_fail.pflow.md` | Batch with some items failing — batch_metadata / batch_error_details surfacing |
| `11_child_workflow.pflow.md` | Standalone child workflow (used by 12 / 13 / 14) |
| `12_parent_calls_child.pflow.md` | Parent → child sub-workflow boundary |
| `13_child_unrecovered.pflow.md` | Child failure propagates to parent unrecovered |
| `14_parent_handles_child_fail.pflow.md` | Parent has `on-error` for the child sub-workflow step |
| `15_cache_failure.pflow.md` | Cache + failure interaction (stale cache entries on re-run) |
| `17_source_line_block.pflow.md` | Source line tracking for code-block source declarations |
| `19_typo_on_succeeded.pflow.md` | Typo on a SUCCEEDED node → "Did you mean" hint |
| `20_absent_node.pflow.md` | Reference to a node that didn't execute (branch not taken) |
| `21_node_name_typo.pflow.md` | Typo on the node name itself (not the field) |
| `22_routing_error.pflow.md` | Custom non-error action with no matching edge |
| `24_absent_no_coalesce.pflow.md` | Direct reference to absent node without `??` |

## Fixtures that were promoted to committed regression guards

Six workflows from the original 24 were promoted to `examples/error-handling/` with descriptive filenames and committed end-to-end tests in `tests/test_integration/test_failed_node_invariant.py`. They are NOT duplicated here — the committed copies are the source of truth.

| Original scratchpad name | Committed location |
|---|---|
| `04_no_coalesce_failed_ref.pflow.md` | `examples/error-handling/failed-node-direct-reference.pflow.md` |
| `08_typo_on_failed.pflow.md` | `examples/error-handling/typo-on-failed-node.pflow.md` |
| `09_loop_recovery.pflow.md` | `examples/error-handling/loop-recovery.pflow.md` |
| `16_source_line_multi.pflow.md` | `examples/error-handling/source-line-multi-output.pflow.md` |
| `18_source_line_offsets.pflow.md` | `examples/error-handling/source-line-heavy-offsets.pflow.md` |
| `23_mixed_absent_failed.pflow.md` | `examples/error-handling/coalesce-mixed-absent-failed.pflow.md` |

## Using `inspect_shared.py`

The harness runs a workflow via `WorkflowRunner` and dumps the final `shared_after` state — specifically the top-level keys, the `__failures__` dict, and `__execution__`. Useful for verifying the invariant `shared[node_id]` ↔ succeeded, `shared["__failures__"][id]` ↔ failed, neither ↔ didn't run.

```bash
# Run against one of the fixtures here
uv run python .taskmaster/tasks/task_148/verification/inspect_shared.py \
    .taskmaster/tasks/task_148/verification/03_both_fail.pflow.md
```

The harness has no hardcoded paths — pass any `.pflow.md` file as the argument.

## When to re-run this corpus

If you touch any of:
- `src/pflow/runtime/node_state.py` (single-write-site helper contract)
- `src/pflow/runtime/engine/engine.py` (step 17.5 failure archive)
- `src/pflow/runtime/engine/instrumentation.py` (`mark_node_failed` callers)
- `src/pflow/core/diagnostic.py` template error rendering (`_format_template_error_lines`, `_format_all_unavailable_coalesce_summary`, `_format_context_keys_block`)
- `src/pflow/runtime/engine/template_errors.py` (`classify_unresolved_references`, `_classify_one_reference`)
- `src/pflow/runtime/output_resolver.py` (`_diagnose_unresolved_output`, `_is_all_absent_coalesce`, `_record_output_failure`)

...then re-run the relevant fixtures here as a sanity check. The committed tests in `test_failed_node_invariant.py` cover the load-bearing cases automatically, but this corpus catches edges those tests don't reach (batch + sub-workflow interactions, cache + failure races, 3-way coalesce, typo on succeeded).
