# Silent Failure Analysis: Empty Values in Pipeline Data Flow

## Context

During Task 108 Phase 2 and subsequent polish, we investigated a real agent report of "Run 0016 produced entirely empty output and looked successful." This document captures what we found, what we fixed, and what remains.

## The Three Layers of Empty-Value Failures

### Layer 1: Unresolved Templates (SOLVED — strict mode)

When `${node.result.field}` references a key that doesn't exist, strict mode (the default) raises `ValueError` immediately with available keys and fuzzy-match suggestions. Execution stops. The agent doesn't burn time/money on downstream nodes.

**Status**: Fully solved. No action needed.

### Layer 2: Batch Items Succeed with Empty Output (SOLVED — runtime + report warnings)

A batch with `error_handling: continue` processes 10 items. 8 produce good output, 2 get empty LLM responses. Previously: CLI showed "10/10 items succeeded", no signal.

**Fix implemented (2026-03-24)**:
- `_detect_empty_output_items()` in `batch_node.py` detects items that succeeded but all non-meta keys are empty
- Runtime: pushes to `__warnings__` → DEGRADED status → CLI shows "2 item(s) produced empty output (items 3, 7)"
- Report: `_detect_batch_item_anomalies()` surfaces batch item warnings in the top-level `summary.md`
- Both use type-aware checks (LLM empty response, Shell empty stdout with exit 0, Code None result)

**Status**: Solved for batch items. Detection is generic (not semantic) — it flags "empty" but can't know if empty is intentional.

### Layer 3: Linear Pipeline Empty Value Pass-Through (UNSOLVED)

In a non-batch pipeline: Node A writes `shared["result"] = ""`. Node B's template `${A.result}` resolves to `""`. Node B's LLM gets a prompt with blank sections. Node B "succeeds" with garbage output. No warning anywhere at runtime.

**Why we didn't add runtime detection here**: Adding empty-output checks to `InstrumentedNodeWrapper` (which wraps every node) would false-positive on every `mkdir`, `cp`, `mv`, and other side-effect shell commands that intentionally produce no stdout. The false-positive rate in linear pipelines would be unacceptably high.

**Current mitigation**: The trace report's `_check_event_anomaly()` catches empty outputs post-hoc when `--report` is used. But this is after execution, not during.

**Status**: Open gap. See "Possible Solutions" below.

## What the Agent's Report Actually Described

The agent's four complaints, evaluated against current state:

| Claim | Accuracy | Current Status |
|-------|----------|----------------|
| Unresolved template silently passes empty string, burns $1.75 | **False** — strict mode raises immediately | Solved |
| Code node debugging: can't set breakpoints | **True** — inherent trade-off of workflow model | Mitigated by `--report` (now shows code source + inputs) and future iteration cache (Task 106) |
| LLM timeout gives no context | **Mostly false** — message includes model name | Could add prompt token count |
| Empty output looks successful | **Was true, now partially solved** | Batch items: solved (runtime + report). Linear pipelines: report-only |

## Possible Solutions for Layer 3

### Option A: Node Output Declarations (extends Task 120's scope)

Allow nodes to declare output expectations in workflow IR:
```markdown
### analyze
- type: llm
- prompt: Analyze ${data}
- outputs:
    response:
      type: string
      min_length: 10
```

Validation runs after node execution in `InstrumentedNodeWrapper`. If the output doesn't match, emit a warning (not an error — to preserve `error_handling: continue` semantics).

**Pros**: Precise, no false positives, opt-in per node.
**Cons**: New syntax, requires user to declare expectations.

### Option B: Workflow-Level Assertions (Task 121)

Let users write assertions as workflow steps:
```markdown
### check-analysis
- type: assert
- condition: ${analyze.response} != ""
- message: Analysis should not be empty
```

**Pros**: Explicit, testable, composable.
**Cons**: Verbose, requires users to think about what to assert.

### Option C: Heuristic Runtime Detection (NOT recommended)

Add empty-output detection to `InstrumentedNodeWrapper` for non-shell nodes. Skip shell nodes entirely.

**Pros**: Automatic, no user configuration.
**Cons**: Still false-positives on HTTP 204, file-write nodes, etc. Type detection via string matching (`"Shell" in node_type`) is fragile.

### Recommendation

Option A is the cleanest path. It extends the existing IR schema (which already has `inputs` with types) to also validate outputs. This could be a Phase 2 of Task 120 — "strict validation at BOTH boundaries" rather than just the input boundary.

## Verified Code Paths

These are the exact code locations relevant to this analysis. Trust boundary: **Verified** via code read, not assumed.

| Component | File | What it does | Layer |
|-----------|------|-------------|-------|
| Template resolution of empty values | `template_wrapper.py:601-646` | `""` and `None` pass through without warning | Layer 3 |
| `_detect_empty_output_items()` | `batch_node.py:92-123` | Runtime detection for batch items | Layer 2 |
| `_check_event_anomaly()` | `trace_report.py:192-226` | Post-hoc detection for any node (report only) | Layer 3 (partial) |
| `_detect_batch_item_anomalies()` | `trace_report.py:552-571` | Post-hoc detection for batch items | Layer 2 |
| `__warnings__` producers | `batch_node.py:980-986`, `instrumented_wrapper.py:150-152` | Only two writers: batch empty output + API warning detector | Layer 2 |
| `InstrumentedNodeWrapper._run()` | `instrumented_wrapper.py:596-693` | No output inspection at runtime beyond API warnings | Layer 3 gap |

## Code Node Visibility Fix (2026-03-24)

Separately, we fixed a gap where code node inputs and source code were invisible in reports:

- `_format_resolutions()` extracted as shared helper for `_build_node_file` and `_build_batch_item_file`
- Now renders: `## Code` (Python source from `node_params`), `## Inputs` (resolved variables), `## Resolved Parameters` (catch-all for HTTP headers, URLs, etc.)
- This directly addresses the agent's complaint about code node debugging — you can now see what code ran and what data it received without re-running with print statements.
