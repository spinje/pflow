# Feature: batch_iteration_limit

## Objective

Limit batch node iterations via CLI flag for fast workflow iteration.

## Requirements

* CLI must accept `--batch-limit N` option on workflow command
* Default limit is 3 when running local files
* Default limit is 0 (unlimited) when running saved workflows
* Limit applies per batch node independently
* Warning message displays when limit is active
* Workflow trace records batch limit metadata

## Scope

* Does not modify IR schema
* Does not add per-node limit configuration
* Does not apply limit to nested workflows (only top-level batch nodes)
* Does not suppress warning message via flags

## Inputs

* `batch_limit: int` — CLI option value (0 = unlimited, >0 = max items per batch)
* `workflow_source: str` — "file" or "saved" (determines default)
* `items: list[Any]` — resolved batch items from `PflowBatchNode.prep()`

## Outputs

Returns: Modified items list (sliced to limit if applicable)

Side effects:
* Warning printed to stderr when limit active
* Trace metadata includes batch limit information

## Structured Formats

```python
# CLI option
@click.option("--batch-limit", type=int, default=None, help="Limit batch iterations (0=unlimited)")

# Shared store key for runtime access
shared["__batch_limit__"] = 3  # or 0 for unlimited

# Trace metadata structure
{
    "batch_limited": True,
    "batch_limit": 3,
    "items_processed": 3,
    "items_total": 47
}

# Warning output format
"⚠ Batch limited: processing 3 of 47 items\n  Use --batch-limit 0 for full execution"
```

## State/Flow Changes

* `prep()` returns original items → `prep()` returns sliced items when limit active
* CLI parses `--batch-limit` → populates `shared["__batch_limit__"]` before execution
* Trace collector receives batch limit metadata from `PflowBatchNode`

## Constraints

* Limit value must be non-negative integer
* Warning must always be shown when limit is active (not suppressible)
* Warning must include both processed count and total count
* Warning must include instructions for unlimited execution

## Rules

1. CLI option `--batch-limit N` accepts non-negative integer.
2. When `--batch-limit` is not specified and `workflow_source == "file"`, default is 3.
3. When `--batch-limit` is not specified and `workflow_source == "saved"`, default is 0.
4. When `--batch-limit 0` is specified, no limit is applied regardless of source.
5. When `--batch-limit N` (N > 0) is specified, limit is N regardless of source.
6. Limit is applied in `PflowBatchNode.prep()` after items resolution.
7. When limit is active and `len(items) > limit`, slice items to `items[:limit]`.
8. When limit is active and `len(items) <= limit`, process all items without warning.
9. Warning is printed to stderr when items are actually limited.
10. Warning format is: `⚠ Batch limited: processing {limit} of {total} items\n  Use --batch-limit 0 for full execution`.
11. Each batch node in workflow receives same limit value independently.
12. Trace metadata includes `batch_limited`, `batch_limit`, `items_processed`, `items_total`.
13. Limit value is passed to batch nodes via `shared["__batch_limit__"]`.

## Edge Cases

* `--batch-limit 0` with local file → no limit applied, no warning
* `--batch-limit 5` with saved workflow → limit of 5 applied
* Batch with 2 items, limit of 3 → process all 2 items, no warning
* Batch with 50 items, limit of 3 → process 3 items, warning displayed
* Multiple batch nodes (A: 10 items, B: 20 items), limit 3 → A processes 3, B processes 3
* No batch nodes in workflow → limit has no effect, no warning
* Negative value for `--batch-limit` → Click rejects as invalid

## Error Handling

* Negative `--batch-limit` value → Click type validation rejects with error message
* Non-integer `--batch-limit` value → Click type validation rejects with error message

## Non-Functional Criteria

* Warning output latency < 10ms
* No performance impact when limit is 0 (unlimited)

## Examples

```bash
# Local file defaults to limit 3
$ pflow workflow.json
⚠ Batch limited: processing 3 of 47 items
  Use --batch-limit 0 for full execution
[workflow executes with 3 items]

# Explicit unlimited for local file
$ pflow workflow.json --batch-limit 0
[workflow executes with all 47 items, no warning]

# Custom limit
$ pflow workflow.json --batch-limit 10
⚠ Batch limited: processing 10 of 47 items
  Use --batch-limit 0 for full execution
[workflow executes with 10 items]

# Saved workflow defaults to unlimited
$ pflow my-saved-workflow
[workflow executes with all items, no warning]

# Saved workflow with explicit limit
$ pflow my-saved-workflow --batch-limit 5
⚠ Batch limited: processing 5 of 47 items
  Use --batch-limit 0 for full execution
[workflow executes with 5 items]

# Batch smaller than limit
$ pflow workflow.json  # batch has 2 items
[workflow executes with all 2 items, no warning]
```

## Test Criteria

1. **Rule 1**: `pflow workflow.json --batch-limit 5` parses limit as 5.
2. **Rule 2**: `pflow workflow.json` without `--batch-limit` sets limit to 3.
3. **Rule 3**: `pflow my-saved-workflow` without `--batch-limit` sets limit to 0.
4. **Rule 4**: `pflow workflow.json --batch-limit 0` sets limit to 0, processes all items.
5. **Rule 5**: `pflow my-saved-workflow --batch-limit 10` sets limit to 10.
6. **Rule 6**: `PflowBatchNode.prep()` checks `shared["__batch_limit__"]` after resolving items.
7. **Rule 7**: Batch with 50 items and limit 3 returns list of length 3 from `prep()`.
8. **Rule 8**: Batch with 2 items and limit 3 returns list of length 2 from `prep()`, no warning.
9. **Rule 9**: Warning is written to stderr, not stdout.
10. **Rule 10**: Warning message contains "processing 3 of 47 items" and "--batch-limit 0".
11. **Rule 11**: Workflow with two batch nodes (10 items each), limit 3 → each processes 3 items.
12. **Rule 12**: Trace file contains `batch_limited: true`, `batch_limit: 3`, `items_processed: 3`, `items_total: 47`.
13. **Rule 13**: `shared["__batch_limit__"]` is set before `compile_ir_to_flow()` is called.
14. **Edge case negative**: `pflow workflow.json --batch-limit -1` exits with error.
15. **Edge case no batch**: Workflow without batch nodes executes normally, no warning.

## Notes (Why)

* **CLI flag over IR parameter**: Keeps workflow definitions pure. Debug/iteration settings stay at runtime, not baked into workflow files that might accidentally ship with limits.
* **Default 3 for files**: Files are the iteration format used by AI agents. Quick feedback (3 items) validates patterns without burning resources.
* **Default 0 for saved**: Saved workflows are "production" - users expect full execution by default.
* **Single `--batch-limit` syntax**: Using 0 for unlimited avoids two separate flags (`--batch-limit` and `--no-batch-limit`).
* **Per-node limit**: Simpler implementation and mental model. Each batch node gets the same limit independently.
* **Always show warning**: Prevents confusion about incomplete results. Users always know when limit is active.

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
|--------|---------------------------|
| 1      | 1                         |
| 2      | 2                         |
| 3      | 3                         |
| 4      | 4                         |
| 5      | 5                         |
| 6      | 6                         |
| 7      | 7                         |
| 8      | 8                         |
| 9      | 9                         |
| 10     | 10                        |
| 11     | 11                        |
| 12     | 12                        |
| 13     | 13                        |

| Edge Case                    | Covered By Test Criteria # |
|-----------------------------|---------------------------|
| Negative value              | 14                        |
| No batch nodes              | 15                        |
| Batch smaller than limit    | 8                         |
| Multiple batch nodes        | 11                        |

## Versioning & Evolution

* **Version:** 1.0.0
* **Changelog:**
  * **1.0.0** — Initial specification for batch iteration limit feature

## Epistemic Appendix

### Assumptions & Unknowns

* **Assumed**: `workflow_source` is reliably set to "file" or "saved" before execution (verified in grep of main.py line 3223)
* **Assumed**: `shared["__batch_limit__"]` key will not conflict with existing workflows (prefix with `__` follows existing convention)
* **Unknown**: Whether nested workflows should inherit parent's batch limit (spec excludes this for simplicity)

### Conflicts & Resolutions

* None observed. Existing batch implementation (`batch_node.py`) does not have any limit mechanism.

### Decision Log / Tradeoffs

* **CLI flag vs IR parameter**: Chose CLI flag. Tradeoff: Less granular control (can't limit specific nodes), but cleaner separation between workflow definition and debug settings.
* **Default 3 vs configurable default**: Chose fixed default of 3. Tradeoff: Less flexibility, but simpler UX and sufficient for iteration use case.
* **Per-node vs global limit**: Chose per-node (each batch node gets same limit independently). Tradeoff: Total iterations could exceed limit × node_count, but simpler mental model.

### Ripple Effects / Impact Map

* **batch_node.py**: Add limit check in `prep()` method
* **main.py**: Add `--batch-limit` option, set default based on source, populate shared store
* **workflow_trace.py**: Extend trace to include batch limit metadata
* **executor_service.py**: May need to pass batch_limit through to compiler/execution

### Residual Risks & Confidence

* **Risk**: Warning message could be noisy for workflows with many batch nodes (each shows warning). Mitigation: Acceptable since this is iteration mode.
* **Risk**: Users might forget limit is active and ship incomplete results. Mitigation: Warning is always shown, cannot be suppressed.
* **Confidence**: High. Feature is self-contained with clear boundaries.

### Epistemic Audit (Checklist Answers)

1. **Assumptions not explicit**: workflow_source reliability, __batch_limit__ key availability
2. **Breakage if wrong**: If workflow_source not set correctly, wrong default applied (minor impact)
3. **Elegance vs robustness**: Chose robustness - explicit warning, simple defaults
4. **Rule↔Test mapping**: All 13 rules have corresponding tests, all edge cases covered
5. **Ripple effects**: 4 files affected (batch_node, main, workflow_trace, executor_service)
6. **Uncertainty**: Low. All integration points verified via code inspection. Confidence: High.
