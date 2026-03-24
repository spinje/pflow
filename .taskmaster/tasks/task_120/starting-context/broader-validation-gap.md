# Note for Task 120 Implementer: Broader Validation Gap

## What Task 120 Solves

Task 120 validates CLI inputs — when a user passes `enabled="maybe"` for a boolean, fail fast at `prepare_inputs()` instead of at the code node.

## What Task 120 Does NOT Solve (But Should Be Aware Of)

There's a broader empty-value problem in runtime data flow that Task 120's implementer should understand, because a natural Phase 2 extension of Task 120 could address it.

### The Problem

In a linear pipeline:

```
Node A (LLM) → writes result: "" (model hiccup, empty response)
Node B (LLM) → template ${A.result} resolves to "" → prompt has blank section → garbage output
```

No error, no warning at runtime. The template resolved successfully — the key exists, the value is just empty. Strict mode only catches MISSING keys, not EMPTY values.

### Why It Matters

An agent building a lyrics pipeline had 11 nodes, sub-workflows, ~$1.58/run. A node silently produced empty output. The pipeline "succeeded" with empty lyrics. The agent only discovered this by manually reading output files.

### What We've Already Done (Task 108 polish, 2026-03-24)

- **Batch items**: `_detect_empty_output_items()` in `batch_node.py` detects batch items that succeeded with empty output → runtime DEGRADED warning
- **Report**: `_check_event_anomaly()` flags empty outputs post-hoc when `--report` is used
- **Code nodes**: Report now shows source code + resolved inputs (agents can see what the code received)

### The Gap That Remains

For **non-batch linear pipelines**, there's no runtime detection of empty output. Adding it to `InstrumentedNodeWrapper` would false-positive on side-effect shell commands (`mkdir`, `cp`) that intentionally produce no stdout.

### How Task 120 Could Extend to Cover This

The natural extension: if Task 120 adds **input** type validation at the CLI boundary, a Phase 2 could add **output** validation at the node boundary:

```markdown
### analyze
- type: llm
- prompt: Analyze ${data}
- outputs:
    response:
      type: string
      required: true      # fail if missing/None
      min_length: 1        # fail if empty string
```

This is opt-in per node, so no false positives. It validates at the RIGHT boundary — after the node executes, before the value propagates downstream.

### Reference

Full analysis: `.taskmaster/tasks/task_108/research/silent-failure-analysis.md`
