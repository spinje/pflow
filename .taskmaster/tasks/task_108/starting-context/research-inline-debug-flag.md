# Research: Inline Debug Flag for Execution-Time Visibility

**Date:** 2026-01-09
**Source:** Debugging session investigating false bug report

## The Problem Observed

An agent encountered a workflow that "succeeded" with wrong output:

```
✓ convert-to-array (11ms)
```

The workflow appeared successful, but URLs went in and `/bin/sh` came out. The agent:
1. Couldn't see the data flow from the CLI output
2. Had to dig through JSON trace files with `jq` queries
3. **Guessed** at the root cause (incorrectly)
4. Wrote a bug report for a non-existent bug

**Key insight:** Poor observability led to incorrect diagnosis. The agent theorized a cause rather than observing the actual behavior.

## Proposed Solution: `--debug` Flag

A simple `--debug` flag that shows the final shared store state after execution:

```
$ pflow workflow.json input="hello" --debug

✓ Workflow completed in 1.234s
Nodes executed (3):
  ✓ fetch-data (234ms)
  ✓ transform (45ms)
  ✓ output (12ms)

📦 Shared store:
  input: "hello"
  fetch-data.response: {"status": 200, "data": {"items": [...]}} (truncated, 2.3kb)
  transform.result: ["item1", "item2", "item3"]
  output.stdout: "Processed 3 items"

📊 Full trace: ~/.pflow/debug/workflow-trace-20260109-143521.json
```

### For the original problem:

```
📦 Shared store:
  urls: "https://image1.png\nhttps://image2.png..." (8 lines)
  convert-to-array.stdout: ["/bin/sh"]   ← obviously wrong
```

Immediately visible that URLs went in but `/bin/sh` came out.

## Why This Complements Task 108

| Feature | Purpose | When to use |
|---------|---------|-------------|
| `--debug` flag | Quick inline visibility | During development, understanding data flow |
| `pflow trace debug` | Deep post-execution analysis | Debugging complex failures, understanding what went wrong |

The `--debug` flag is a **quick sanity check** that often prevents needing the deeper analysis.

## Implementation Considerations

1. **Token-efficient** - Truncate long strings (configurable threshold, e.g., 200 chars)
2. **Simple to implement** - Just pretty-print `shared` dict at end of execution
3. **Already have trace path** - Just print it as escape hatch for deeper investigation
4. **Works for success AND failure** - Not just error cases

## Design Questions for Task 108

1. Should `--debug` be a separate mini-feature, or Phase 1 of Task 108?
2. Should the truncation format match `pflow trace debug` output for consistency?
3. Should `--debug` also work in MCP context (return shared store in response)?

## Related Files

- `src/pflow/cli/main.py` - Where `--debug` flag would be added
- `src/pflow/execution/display_manager.py` - Existing output coordination
- `src/pflow/runtime/workflow_trace.py` - Trace data structures

## Original Context

This research came from investigating a false bug report in `scratchpads/bug-optional-input-null-string.md`. The agent reported that optional inputs become string "null", but testing proved the code correctly converts `None` → `""`. The agent's incorrect diagnosis was caused by lack of visibility into actual data flow during execution.
