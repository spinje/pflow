# Task 159 Fix Brief 08 — Report Directory Stale Pages

Status: research handoff, not an implementation plan
Prepared: 2026-05-07
Source verification report: `scratchpads/stage2-verification/POST-FIX-CLOSURE-REPORT.md`

## Purpose

This brief captures the report-directory staleness issue found during
post-fix closure verification.

The next agent should treat this as a research task first. Read the current
report-generation code, reproduce or inspect the stale-page behavior, reason
about the right report lifecycle policy with the user, then implement the
smallest final design that leaves the code easy for future agents to reason
about.

Do not optimize for the easiest patch if it leaves ambiguous semantics. The
question is: what should a report directory mean?

## Issue Covered

Post-fix closure Issue 1:

> Failed reports can retain stale per-node pages from older runs.

Severity in closure report: high
Area: report UX / correctness

## Plain-Language Problem

`pflow run --report` writes reports to a stable workflow-named directory such
as:

```text
~/.pflow/reports/song-creator
```

When a later run fails before reaching downstream nodes, pflow writes a fresh
`summary.md` and fresh pages for nodes that executed in the current run. But it
does not remove pages from an older successful run. The directory can therefore
contain:

- a current `summary.md` saying the run failed after 10 nodes, and
- stale pages for nodes 11, 14, etc. from a different older run.

An agent browsing the report directory can mistake those stale pages for
current-run evidence. That is especially dangerous because report pages contain
prompts, cached systems, outputs, costs, and success status.

## Current Evidence

From `scratchpads/stage2-verification/POST-FIX-CLOSURE-REPORT.md`:

```text
new summary:
/Users/andfal/.pflow/reports/song-creator/summary.md
mtime: 2026-05-07 13:19:55

stale pages:
/Users/andfal/.pflow/reports/song-creator/11-format-craft-reviews.md
mtime: 2026-05-05 11:52:44

/Users/andfal/.pflow/reports/song-creator/14-generate-suno-prompt.md
mtime: 2026-05-05 11:52:44
```

The current run failed at `craft-reviews`, but downstream pages from an older
run remained in the same report directory.

Trust boundary:

- The stale-file behavior was verified in the current branch.
- The external `song-creator` workflow timeout itself is not part of this
  brief. This brief is only about report artifact correctness after any failed
  or partial run.

## Reproduction

The closure report used a real paid external workflow run. A future agent
should prefer a cheap synthetic workflow if possible.

General reproduction shape:

1. Run a workflow with `--report` that executes enough nodes to create several
   report pages.
2. Run the same workflow again with `--report` but make it fail or stop earlier
   so fewer node pages are generated.
3. Inspect the report directory and compare:
   - `summary.md` timestamp and node count,
   - stale downstream node page timestamps,
   - page contents contradicting the current summary.

The real evidence path from closure verification:

```text
/Users/andfal/.pflow/debug/workflow-trace-40235f89-song-creator-20260507-131955.json
/Users/andfal/.pflow/reports/song-creator
```

If using this real path, do not rerun provider calls unless the user approves.
The file-system evidence may already be sufficient.

## Most Relevant Code Areas

Start here:

- `src/pflow/core/trace_report.py`
  - `generate_report(...)`
  - `_write_node_files(...)`
  - batch/sub-workflow report directory writing helpers
- `src/pflow/cli/commands/run.py`
  - report generation after workflow execution
  - `--report` / `--report-dir` flow into `generate_report(...)`
- `src/pflow/cli/commands/report.py`
  - standalone `pflow report` command and explicit output path behavior
- `src/pflow/core/CLAUDE.md`
  - trace/report expectations

Current code orientation:

- `generate_report()` computes `report_dir`.
- For auto output, it uses `~/.pflow/reports/{workflow-name}`.
- It calls `report_dir.mkdir(parents=True, exist_ok=True)`.
- It writes `summary.md` and current node files.
- It does not clear old files or use a run-specific subdirectory.

## Relevant Progress-Log Context

Read these sections from
`.taskmaster/tasks/task_159/implementation/implementation-progress-log.md`:

- `Stage 2 follow-up — ## Cached System in --report (trace 2.2.0)`
  - Report became a first-class prompt-cache verification surface.
  - `## Cached System` and provider cache markers are visible in per-node pages.
- `Stage 2 follow-up — Findings #4/#5: per-call cache telemetry surfaces`
  - Report added cache telemetry sections.
  - Reinforces that report pages are agent-facing cache evidence.
- `Stage 2 follow-up — report paid-vs-source cost semantics for memo hits`
  - Recent report UX fix clarified current-run versus source-run cost.
  - This stale-page issue can undo that clarity if old pages remain visible.
- `POST-FIX-CLOSURE-REPORT.md` Issue 1
  - Source of current evidence.

Also read:

- `src/pflow/core/trace_report.py` around `generate_report()`.
- Existing tests in `tests/test_core/test_trace_report.py`.

## Research Questions

Answer these before implementing:

1. What should the default auto report directory represent?
   - The latest run snapshot for a workflow?
   - A historical report collection?
   - A stable pointer to a unique run-specific report?
2. Should explicit `--report-dir` / `pflow report -o` paths be cleared?
   - Clearing arbitrary user-specified directories may be destructive.
   - Auto-managed `~/.pflow/reports/<name>` is safer to manage aggressively.
3. Should report generation be atomic enough to avoid half-written report
   directories if interrupted?
4. Should stale files be removed, or should report paths be unique per trace?
5. How should batch/sub-workflow nested directories be handled?
6. What should happen when report generation fails partway through writing?

## Design Options to Discuss

Option A: auto reports are current-run snapshots.

- Clear the auto-managed report directory before writing current files.
- Likely simplest final semantics for agents: directory equals current trace.
- Need careful policy for explicit output paths.

Option B: use unique report directories per trace/run.

- Avoids deletion and preserves history.
- More path churn; user now needs to know which report directory is current.
- May require updating CLI output and docs.

Option C: remove only known generated files before writing.

- Less destructive than clearing directory.
- More complex and easier to get wrong, especially nested batch/sub-workflow
  directories.

The fixing agent should recommend an option after reading code and tests.

## Desired UX Properties

- A report directory presented by pflow after a run must not contain stale pages
  that look like current-run evidence.
- If a run fails early, downstream pages from prior runs should not be visible
  as ordinary report pages for the current report.
- Agents should be able to trust `summary.md` and per-node pages as one coherent
  artifact.
- Explicit user-controlled output paths should not be destructively cleared
  without a deliberate, documented policy.

## Verification Expectations

Add a regression test that creates stale report files and proves they do not
survive in the current report mode being fixed.

Useful test shapes:

- Generate report once from a trace with nodes A/B/C.
- Generate report again from a trace with only A.
- Assert stale B/C files or directories are absent, or that the second report
  uses a distinct run-specific path depending on the chosen design.
- Include nested directory stale behavior if the chosen fix clears recursively.

Likely test file:

- `tests/test_core/test_trace_report.py`

Manual check:

```bash
pflow <workflow> --report ...
ls -la ~/.pflow/reports/<workflow>
```

In Codex sandbox mode, use `HOME=/private/tmp/pflow-test-home` for tests that
write `~/.pflow`.

## Non-Goals

- Do not fix the external `song-creator` timeout here.
- Do not redesign the whole report renderer.
- Do not start Task 160 structural refactor.
- Do not add a complicated report-history system unless the user chooses that
  policy.

