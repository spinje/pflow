# Task 111: Batch Limit for Workflow Iteration

## Description

Add a `--batch-limit N` CLI parameter that limits batch node iterations during workflow development. Defaults to 3 when running local files, enabling fast iteration without processing entire datasets.

## Status

not started

## Priority

medium

## Problem

When iterating on workflows during development, batch nodes process all items before revealing errors. This wastes time and resources—you don't want to wait for 100+ items to process just to discover a bug at step 3. AI agents building workflows are particularly affected since they iterate frequently with `pflow workflow.json`.

## Solution

A `--batch-limit N` CLI flag that caps batch node iterations:

| Command | Behavior |
|---------|----------|
| `pflow workflow.json` | Batch limit 3 (default for local files) |
| `pflow workflow.json --batch-limit 10` | Custom limit |
| `pflow workflow.json --batch-limit 0` | Full execution (opt-out) |
| `pflow my-saved-workflow` | Full execution (default for saved workflows) |
| `pflow my-saved-workflow --batch-limit 5` | Limited execution |

Output must clearly show when limit is active:
```
Batch limited: processing 3 of 47 items. Use --batch-limit 0 for full execution.
```

## Design Decisions

- **CLI flag, not IR parameter**: Keeps workflow definitions pure. Debug settings stay at runtime, not baked into workflow files.
- **Default limit on local files only**: Running a file path triggers iteration mode (limit 3). Saved workflows run fully by default. This matches actual use—files are for iteration, saved workflows are "production".
- **`--batch-limit 0` for unlimited**: Single syntax instead of separate `--no-batch-limit` flag. 0 means "no limit", not "process nothing".
- **Default value of 3**: Enough to verify the pattern works, fast enough for quick iteration. 1 might miss iteration-related bugs, 5+ starts defeating the purpose.
- **Per-batch-node limit**: Each batch node gets the limit independently. No special handling for nested batches—keeps implementation simple.
- **Always show warning**: When limit is active, always display count of items processed vs total, plus instructions to change the limit. Not suppressible.

## Dependencies

- Task 96: Support Batch Processing in Workflows — Must exist first (already completed)

## Implementation Notes

**Detection of "local file" vs "saved workflow"**:
- Local file: any path that resolves to a file on disk
- Saved workflow: resolved by name through workflow manager
- The distinction already exists in the codebase

**Where limit is applied**:
- Intercept batch data before the batch node loops
- Slice the input list: `items[:limit]` if limit > 0

**Trace indication**:
- Workflow trace should record that the run was limited
- Include: `batch_limited: true`, `batch_limit: 3`, `items_processed: 3`, `items_total: 47`
- Useful for debugging "why did this only process 3 items" after the fact

**Output format**:
```
⚠ Batch limited: processing 3 of 47 items
  Use --batch-limit 0 for full execution
```

## Verification

- Running `pflow workflow.json` with a 50-item batch processes only 3 items
- Running `pflow workflow.json --batch-limit 0` processes all items
- Running `pflow my-saved-workflow` processes all items by default
- Running `pflow my-saved-workflow --batch-limit 5` processes only 5 items
- Warning message displays correct counts (processed vs total)
- Warning includes instructions for changing/removing limit
- Workflow trace includes batch limit metadata when limited
- Multiple batch nodes in same workflow each respect the limit independently
