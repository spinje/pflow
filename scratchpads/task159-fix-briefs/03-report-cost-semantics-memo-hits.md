# Task 159 Fix Brief 03 — Report Cost Semantics for Memo Hits

Status: research handoff, not an implementation plan
Prepared: 2026-05-07
Source verification report: `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`

## Purpose

This brief captures what is known about `--report` per-node pages showing
historical LLM provider costs on memo-hit nodes in a way that reads like
current-run spend.

The next agent's job is to research the current code deeply, reproduce the
issue, and discuss any material display-policy decisions with the user before
implementing. Do not treat this as a mechanical patch list. The right outcome is
a simple final model future agents can understand: every report cost line should
make clear whether it means "paid this run" or "historical source cost".

There are no shipped users of the Task 159 report additions yet. Prefer clear,
correct semantics over preserving misleading current output.

## Finding Covered

Primary:

- Final verification Finding 3: memo-hit reports show historical provider costs
  on cached node pages.

Keep separate from:

- Brief 01 cost semantics in `analyze-cache` projections and savings wording.
- Brief 04 CLI run contract under `--only` and warnings.

This issue is localized to trace/report rendering semantics.

## Plain-Language Problem

pflow has two different "cost" concepts in a memo-hit trace:

- **Paid this run**: if pflow reused a memoized node output, it did not call the
  provider for that node during this run. The current-run LLM cost is known
  zero.
- **Historical source cost**: the memoized output may retain the original
  `llm_usage.cost_usd` from the run that created the memo entry. That number can
  be useful for audit/debug context, but it is not what this run paid.

The final verification report observed that all-memo runs correctly report
`actually_paid_usd: 0.0` in analyzer JSON, and summary/pipeline tables can show
cached nodes as `$0.0000`. But individual cached node report pages still render
the historical provider cost directly under:

```text
Status: success [cached]
Cost: $0.0008
```

To an agent or user, that looks like current-run provider spend. It undermines
trust in reports because different report sections appear to disagree.

A clearer report might show:

```text
Paid this run: $0.0000
Historical source cost: $0.0008
```

or it might hide historical source cost unless clearly labeled. The exact UI is
for the fixing agent and user to decide after reading the code. The invariant is
that historical provider cost must not be presented as current-run cost.

## Current Evidence

From `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`:

- Reproduction used the Anthropic Haiku smoke workflow.
- Memo run command:

```bash
CTX="$(cat scratchpads/stage2-verification/anthropic-haiku/reference.md)"
.venv/bin/pflow scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md --report context="$CTX"
```

- Observed trace:

```text
/Users/andfal/.pflow/debug/workflow-trace-8ba27c20-smoke-with-cache-20260506-230801.json
```

- Analyzer on that trace reported:

```text
actually_paid_usd: 0.0
```

- Individual cached node report pages still displayed historical costs such as
  `$0.0003` / `$0.0008`.

Expected from the report:

- Cached report pages should clearly separate current-run paid cost from
  historical source cost, if historical cost is shown at all.

## Verified Code Facts

These were checked through local code orientation and an explorer subagent.

### Report Generation

- Report generation starts at
  `src/pflow/core/trace_report.py::generate_report(...)`.
- `generate_report()` writes `summary.md` and per-node files.
- Per-node files are built through `_build_node_file(...)`, which calls
  `_format_node_metadata(...)`.

### Where Cost Lines Are Rendered

Per-node report cost lines are generated in at least these places:

- Leaf node pages:
  - `trace_report.py::_format_node_metadata(...)`
  - directly renders `event["llm_call"]["cost_usd"]` as `- Cost: $...`.
  - This is the main Finding 3 path.
- Simple batch item pages:
  - `_build_batch_item_file(...)`
  - directly renders `item["llm_call"]["cost_usd"]`.
- Container summaries and pipeline tables:
  - use `_compute_event_cost(...)` / `_compute_batch_item_cost(...)`.
  - those delegate to `TraceTree.cost_for_event(...)` /
    `TraceTree.cost_for_batch_item(...)`.
  - these paths mostly already use actual-run cost semantics.

### How Cached Events Carry Historical Cost

Runtime memo hits restore the cached node output, including its historical
`llm_usage`, then annotate it with memo metadata:

- `runtime/engine/instrumentation.py::apply_memo_hit(...)`
  - restores cached output.
  - writes `cache_source="memo"`, `cache_key`, and `cache_age_sec` into
    `llm_usage`.
- `runtime/engine/instrumentation.py::handle_cached_execution(...)`
  - records trace event with `cached=True`.
- `runtime/workflow_trace.py::WorkflowTraceCollector.record_node_execution(...)`
  - stores `event["cached"] = True`.
  - preserves `node_output`.
  - `_add_llm_data(...)` copies `node_output["llm_usage"]` into
    `event["llm_call"]`.

Therefore a memo-hit trace event can be shaped like:

```json
{
  "cached": true,
  "llm_call": {
    "cost_usd": 0.0008,
    "cache_source": "memo",
    "cache_key": "...",
    "cache_age_sec": 123
  }
}
```

In this shape, `llm_call.cost_usd` is historical source cost retained from the
memoized output, not current-run paid cost.

### Existing Correct Primitive

`TraceTree` already models this distinction:

- Default cost helpers answer "what did this run pay?"
- Cached LLM events are current-run zero-cost boundaries.
- Historical cost is available only when explicitly asking for cached/historical
  inclusion.

The blur is that some report leaf metadata paths bypass `TraceTree` and read
`llm_call.cost_usd` directly.

## Reproduction Commands

Use sandbox-safe invocation where possible:

```bash
CTX="$(cat scratchpads/stage2-verification/anthropic-haiku/reference.md)"

HOME=/private/tmp/pflow-test-home .venv/bin/pflow \
  scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --report --no-cache context="$CTX"

HOME=/private/tmp/pflow-test-home .venv/bin/pflow \
  scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --report context="$CTX"
```

Then inspect:

```bash
ls -t ~/.pflow/debug/workflow-trace-*smoke-with-cache* | head -1
ls ~/.pflow/reports/smoke-with-cache
```

Check:

- `summary.md` pipeline/table cost for cached nodes.
- individual node pages for `- Status: success [cached]` and `- Cost: ...`.
- analyzer JSON:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --from-trace <memo-trace-path> \
  --format=json \
  context="$CTX"
```

If historical traces under `/Users/andfal/.pflow` are unavailable, fresh
reproduction may spend provider money. For the report-rendering issue, a
synthetic trace fixture may be enough once the current behavior is confirmed.

## Most Relevant Code Areas

Start here, read before editing:

- `src/pflow/core/trace_report.py`
  - `generate_report(...)`
  - `_build_node_file(...)`
  - `_format_node_metadata(...)`
  - `_build_batch_item_file(...)`
  - `_compute_event_cost(...)`
  - `_compute_batch_item_cost(...)`
  - `_format_cost(...)`
- `src/pflow/core/trace_tree.py`
  - cost semantics for cached events.
  - default actual-run cost vs historical include-cached cost.
- `src/pflow/runtime/engine/instrumentation.py`
  - `apply_memo_hit(...)`
  - `handle_cached_execution(...)`
  - how memo metadata is attached.
- `src/pflow/runtime/workflow_trace.py`
  - `WorkflowTraceCollector.record_node_execution(...)`
  - `_add_llm_data(...)`
  - how retained `llm_usage` becomes `event["llm_call"]`.
- `src/pflow/core/cache_analysis/cost_estimation.py`
  - `compute_actually_paid(...)`
  - useful as reference for current-run cost semantics.

## Relevant Progress-Log Context

Read these sections from
`.taskmaster/tasks/task_159/implementation/implementation-progress-log.md`:

- `Stage 2 follow-up — Findings #4/#5: per-call cache telemetry surfaces`
  - Current `--report` and JSON telemetry expectations.
  - Important distinction between raw observed cache splits and projections.
- `Stage 2 follow-up — Finding #17: all-memo trace cost is known zero`
  - The most directly relevant section.
  - Establishes that all-memo traces are known current-run zero cost.
  - Explains why the policy lives in `TraceTree`.
- `Post-segment-3 adversarial CLI verification + 2 bug fixes`
  - Memo-hit `cache_source` labeling bug and fix.
  - Explains why distinguishing memo vs in-process cache source matters.
- `Post-segment-4 follow-up: cost wiring + honest loose-ends audit`
  - Tri-state cost contract and `$0` vs unavailable distinction.

Also read:

- `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`
  - Finding 3.
  - Critical context section distinguishing provider prompt cache and pflow memo
    cache.
- `src/pflow/runtime/CLAUDE.md`
  - trace/report-facing cache fields.
- `src/pflow/runtime/engine/CLAUDE.md`
  - memo cache metadata semantics.

## Tests to Read Before Changing Behavior

- `tests/test_core/test_trace_tree.py`
  - cached events are known zero actual cost.
  - historical cost should require explicit include-cached/historical view.
- `tests/test_runtime/test_workflow_trace.py`
  - trace summaries exclude cached cost.
- `tests/test_runtime/test_trace_format_2_1.py`
  - production memo-hit trace shape and `cache_source="memo"`.
- `tests/test_core/test_trace_report.py`
  - report rendering expectations.
  - cache telemetry report tests.

Expect to add or update tests around:

- cached LLM node page metadata renders current-run paid cost as zero or omits
  current cost line in favor of a clear label.
- historical source cost, if rendered, is explicitly labeled.
- batch item pages follow the same semantics as leaf node pages.
- summary/pipeline table and per-node page no longer appear contradictory.

## Research Questions for the Next Agent

Answer before designing the display:

1. Should cached node pages show both current-run paid cost and historical source
   cost, or only current-run cost?
2. If both are shown, what exact wording is least ambiguous for agents?
3. Should the report use one shared helper for actual-run node cost so leaf,
   batch, and pipeline views cannot drift?
4. Does `llm_call.cost_usd` have a documented meaning in trace JSON when
   `event.cached == true`, or should docs clarify that it is retained historical
   usage?
5. Are there other direct `llm_call.cost_usd` report paths that bypass
   `TraceTree`?
6. Should `cache_source` affect the display wording, or is `event.cached` enough?

## Desired UX Properties

Outcome constraints:

- A cached node page must not imply the provider was paid for that node during
  this run.
- Current-run zero and unavailable remain distinct.
- Historical source cost may be shown only if explicitly labeled.
- Summary/pipeline tables and individual node pages agree semantically.
- Memo cache and provider prompt cache remain distinct in wording.
- The report should be understandable without reading trace internals.

## Non-Goals for This Brief

- Do not solve analyzer negative savings/projection math here.
- Do not redesign trace format unless research proves display-only changes are
  insufficient.
- Do not start Task 160 structural refactor.
- Do not remove useful historical telemetry blindly; the issue is labeling and
  semantic separation, not the existence of retained historical data.

