# Task 159 Fix Brief 10 — Scoped Unexecuted Node Summary

Status: research handoff, not an implementation plan
Prepared: 2026-05-07
Source verification report: `scratchpads/stage2-verification/POST-FIX-CLOSURE-REPORT.md`

## Purpose

This brief captures a remaining analyzer JSON scope issue for partial
multi-workflow traces.

The next agent should verify the current JSON shape, decide whether the
summary-level field should change shape or gain a scoped companion field, and
implement the simplest final contract. There are no external analyzer users
yet, so preserving an ambiguous field for compatibility is not required.

## Issue Covered

Post-fix closure Issue 3:

> `trace_unexecuted_llm_nodes` is ambiguous for multi-workflow traces.

Severity in closure report: low-medium
Area: analyzer JSON / multi-workflow context

## Plain-Language Problem

For partial traces, the analyzer summarizes which static LLM nodes did not
execute. In a multi-workflow analysis, different child workflows can have LLM
nodes with the same `id`, such as repeated `review` nodes.

The current summary field lists only bare node IDs:

```json
[
  "generate-suno-prompt",
  "review",
  "review",
  "review",
  "review",
  "review",
  "review",
  "review",
  "review",
  "review",
  "rewrite-craft"
]
```

Detailed `per_call` rows include workflow paths, so the analyzer internally
knows the scope. But the summary field loses that scope. A JSON consumer or
agent looking only at summary cannot tell which child workflow each `review`
belongs to.

## Current Evidence

From `scratchpads/stage2-verification/POST-FIX-CLOSURE-REPORT.md`:

- Failed `song-creator` trace analysis correctly entered partial evidence mode.
- `summary.trace_unexecuted_llm_nodes` contained repeated bare `review` values.
- Repeated `review` entries came from different child review workflows.
- `per_call` rows had workflow paths, but summary did not.

Trace from closure verification:

```text
/Users/andfal/.pflow/debug/workflow-trace-40235f89-song-creator-20260507-131955.json
```

Trust boundary:

- This is not as severe as stale report pages or cohort-mismatched cost deltas.
- It is still an agent-facing JSON contract problem and should be fixed if
  low-churn.

## Reproduction

Using the closure trace if available:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md \
  --from-trace /Users/andfal/.pflow/debug/workflow-trace-40235f89-song-creator-20260507-131955.json \
  --format=json
```

Inspect:

```text
summary.trace_coverage
summary.evidence_scope
summary.trace_unexecuted_llm_nodes
per_call[].workflow_path
per_call[].node_path
per_call[].did_not_execute_in_trace
```

If the external trace is unavailable, use a synthetic parent + two child
workflows where both children contain an LLM node with the same ID and the
trace executes only the parent or one child.

## Most Relevant Code Areas

Start here:

- `src/pflow/core/cache_analysis/analyze.py`
  - `AnalysisSummary.trace_unexecuted_llm_nodes`
  - `_build_summary(...)`
  - `_trace_coverage_for_rows(...)`
  - `PerCallRow.workflow_path`
  - `PerCallRow.node_path`
- `src/pflow/core/cache_analysis/render_json.py`
  - summary serialization for trace coverage fields
- `src/pflow/core/cache_analysis/render_text.py`
  - text rendering of partial evidence and hidden rows
- `tests/test_core/test_cache_analysis_analyze.py`
- `tests/test_core/test_cache_analysis_renderers.py`

Current code orientation:

- `_trace_coverage_for_rows(...)` currently builds:

```python
tuple(sorted(row.node_path for row in rows if row.did_not_execute_in_trace))
```

- That loses `row.workflow_path`.
- The data needed for disambiguation already exists on `PerCallRow`.

## Relevant Progress-Log Context

Read these sections from
`.taskmaster/tasks/task_159/implementation/implementation-progress-log.md`:

- `Stage 2 follow-up — partial trace evidence scope + dynamic batch model truth`
  - Introduced partial trace evidence scope and unexecuted row handling.
- `Stage 2 status check — Findings #3, #14, #16`
  - Notes sub-workflow cost attribution is keyed by `(workflow_path, node_id)`.
  - Reinforces that bare node ID is insufficient in multi-workflow contexts.
- `Stage 2 follow-up — Finding #21: child-scoped sub-workflow cache recommendations`
  - Parent and child cache declarations are distinct; workflow scope matters.
- `Stage 2 follow-up — Recommendation actionability, scope, and syntax`
  - Recently fixed `<unknown>` and workflow scoping for analyzer findings.
- `POST-FIX-CLOSURE-REPORT.md` Issue 3
  - Source of current evidence.

Also read:

- `src/pflow/core/cache_analysis/CLAUDE.md`
  - cross-workflow and renderer contract sections.

## Research Questions

Answer these before implementing:

1. Is `trace_unexecuted_llm_nodes` used anywhere internally, or is it purely
   JSON/text output?
2. Should the field be replaced with scoped objects, for example:

```json
[
  {"workflow_path": ".../review-rhyme.pflow.md", "node_id": "review"}
]
```

3. Should the field instead use string paths like:

```text
review-rhyme.pflow.md:review
```

4. Should text output also show scoped names, or is JSON enough?
5. Since there are no external analyzer users, is it cleaner to rename the field
   to reflect the new shape rather than preserve a misleading name?
6. Should sorting be by workflow path then node ID to keep deterministic output?

## Design Options to Discuss

Option A: replace `trace_unexecuted_llm_nodes` with scoped objects.

- Most machine-readable.
- Cleanest JSON contract.
- Requires updating tests and renderers.

Option B: keep old field and add `trace_unexecuted_llm_rows`.

- Lower risk if internal tests assume the old field.
- But adds duplicate concepts and may preserve the ambiguity.

Option C: use scoped string labels.

- Simpler output shape.
- Less structured for agents than objects.

Because there are no external analyzer users yet, prefer the simplest final
contract, not compatibility ceremony.

## Desired UX Properties

- Summary-level partial-trace JSON is self-contained enough for an agent to
  identify which workflow and node did not execute.
- Duplicate node IDs across child workflows are not ambiguous.
- Text and JSON do not regress the recent partial-evidence improvements.
- `per_call` remains the detailed source of truth, but summary should not force
  consumers to join just to disambiguate repeated IDs.

## Verification Expectations

Add a regression test with duplicate node IDs across workflows.

Assertions should cover:

- partial trace coverage is detected;
- unexecuted summary entries include workflow scope;
- repeated bare IDs are not the only available summary signal;
- JSON output is deterministic.

Likely test files:

- `tests/test_core/test_cache_analysis_analyze.py`
- `tests/test_core/test_cache_analysis_renderers.py`

Manual check against the closure trace if available:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md \
  --from-trace /Users/andfal/.pflow/debug/workflow-trace-40235f89-song-creator-20260507-131955.json \
  --format=json
```

## Non-Goals

- Do not fix the external `song-creator` timeout here.
- Do not alter the partial-trace suppression policy unless research shows it is
  directly coupled.
- Do not start Task 160 structural refactor.
- Do not preserve ambiguous JSON for compatibility; analyzer JSON has not
  shipped.

