# Task 185: Run Lookup Without a Directory Scan — a Bounded Trace Directory and Direct Lookup by Run

## Description

Every pflow surface that needs a Run — `pflow resume list`, `pflow resume <id>`, `pflow report`, `--only`'s snapshot,
`analyze-cache`, and the Viewer's gate callout — finds it by scanning the whole `~/.pflow/debug` directory, reading the head
or tail (or the whole file) of every trace in it. The directory has no retention, so it grows without bound and every lookup
slows with it. Make a run lookup cost what the lookup needs (one directory listing at most, reads only of the files that
match), and keep the directory bounded without breaking the three features that read old traces.

## Status

not started

## Priority

high

## Roadmap

next

> Drafted 2026-10-12 by the main orchestrator (session-16) from two independent searcher passes (native + codex offload)
> over `main` `c4975a12` that converged on every claim below (`scratchpads/session-16/verify/{native,out}-traces.md`,
> gitignored). Line numbers are point-in-time — re-verify at start. D1 DECIDED by the user 2026-10-12 (accepted the
> recommendation); D2 is the planner's within the stated constraints.

## Problem

Observed, by a consumer that films pflow on camera and on the owner's own machine (2026-10-12):

| Measurement | Consumer's machine | Owner's machine |
|---|---|---|
| traces in `~/.pflow/debug` | 28,542 (2.3 GB) | 29,650 (2.4 GB); 20,704 written in October alone |
| `pflow resume list` wall time | 42.8 s / 52.6 s | 24.8 s / 24.3 s (`pflow --version`: 0.68 s) |
| Viewer gate callout "Loading gate…" | ~25 s | not measured |

On camera this put 93 s between a human's Approve click and the next narration line; the consumer's helper now polls the
Viewer's `/api/runs?workflow=` instead of `resume list` to get under a second.

**Why it is one problem.** The trace filename carries `md5(workflow_path)[:8]`, an optional display name, and the start
timestamp — never the `execution_id` (`runtime/workflow_trace.py:66-98`, composer; the id is only on the meta line `:1066`
and the trailer `:1092`). So every lookup by run id, and every "is anything paused" question, is a full-directory walk:

| Reader | What it does per call | Trigger |
|---|---|---|
| `runtime/resume_source.py:1138` `list_paused_runs` | lists all N; head read of every file; tail read (64 KB) of every non-`--only` file; then, per paused row, `_find_consuming_attempt` (`:265`) fully parses every trace of that workflow (`:1036-1040` calls this "accepted v1 inefficiency") | `pflow resume list` |
| `runtime/resume_source.py:304` `_select_resume_trace` by id | lists all N, sorts, head read per file until the id matches | `pflow resume <uuid>`; UI `POST /api/resume` (runs it twice: server preflight + spawned child) |
| `runtime/workflow_trace.py:172` `_iter_workflow_traces` | lists all N (a hash-prefixed glob still enumerates the flat directory — Python 3.13 `glob.py:428-434`), then FULL loads of each matching trace, lazily | `--only` (`engine.py:1041`), `--dry-run --only`, `resume <workflow>`, supersession checks, `analyze-cache` (which loads ALL of a workflow's traces with no early exit, `trace_loading.py:226-233`, incl. the MCP tool) |
| `cli/commands/report.py:57` | `stat()` of every file, then full loads newest-first until a complete trace | `pflow report` with no path |
| `ui/run_tailer.py:277` `scan_traces` | cold: stat + head + tail read of every file; warm: a stat of every file; cache lives per server process, re-lists when the dir mtime changes (every new trace) | the Viewer's tailer (every 0.25 s, workflow-scoped), `/api/runs`, `/api/run-node`, and **`/api/gate` unscoped** (`ui/server.py:1566`: `next(c for c in scan_traces() if …)` — `scan_traces` builds the whole list before `next` can stop) → the "Loading gate…" wait |

Three recency rules disagree (file mtime in the UI and `report`; filename timestamp in resume, `--only`, analyze-cache), and
`Path.home() / ".pflow" / "debug"` is spelled out at 8 sites across 5 modules with no shared resolver
(`workflow_trace.py:299,993`, `resume_source.py:906,1134`, `trace_loading.py:289,338`, `report.py:53`, `run_tailer.py:47`).

**Retention does not exist** — not in `src/`, not a settings key, not a flag (`--no-trace` disables writing, and `--report`
silently overrides it: `run.py:1100-1101`). The user docs say so and tell people to `rm ~/.pflow/debug/workflow-trace-*.json`
(`docs/guides/debugging.mdx:146-151`; `docs/reference/configuration.mdx:223` "Debug traces only, can grow large") — which
silently breaks `--only` (ADR-0002: "clearing the debug dir breaks `--only`") and makes every pending Paused Run
unanswerable, since the resume token IS the trace (ADR-0010). The trace became load-bearing for three features after the
"delete freely" wording was written; nothing re-derived what deletion may touch.

## Solution

- **A run is found, not scanned for.** Lookup by `execution_id`, "newest usable Run of this Workflow", and "all pending Paused
  Runs" each cost at most one directory listing plus reads of the files that match — never a read of every file. The
  mechanism (what the filename carries, whether a small marker/index exists beside the traces, how paused-ness is visible
  without a tail read) is the planner's — see D2.
- **The directory is bounded.** pflow keeps the traces the product still needs and removes the rest on a policy the user
  rules (D1). Removal never takes a trace a feature depends on: a pending Paused Run (its token), the newest success/degraded
  trace per Workflow (the `--only` Snapshot), and the newest Attempt of any resume chain plus what it was resumed from.
- **One resolver, one recency rule.** The debug directory is resolved in one place; "newest" means one thing everywhere.
- **The docs stop advising the destructive `rm`**; `--no-trace` vs `--report` precedence is stated where the flags are.

## Design Decisions

- **DECIDED (user, 2026-10-12) — D1: option (b), bounded retention with the protected set.** Options considered: (a) never delete — only make lookup fast (the directory still grows
  ~2 GB per five months of this owner's use); (b) bounded by age and/or count with the protected set above, applied
  opportunistically when pflow writes a trace (what `git gc --auto`, journald's `SystemMaxUse` and Temporal's retention
  period do for run logs), with a settings key for the bound; (c) a manual `pflow traces prune` command only.
  (b) chosen — the problem is observed on two machines, and (a)/(c) leave the growth to a user who was never told.
  The bound's defaults and the settings key are the planner's proposal at its checkpoint, shown before building.
- **D2 — lookup shape (PLANNER, constrained).** Constraints: no per-file reads to answer "which file is run X" or "what is
  paused"; a second store only if the deletion test demands it (ADR-0007 keeps trace lifecycles self-contained — a marker
  that dies with its trace is fine, a global index that outlives traces is the "global-GC problem" that ADR rejected); the
  trace FORMAT (meta/event/trailer lines, format version) is out of scope unless a field is genuinely missing; a filename
  change is in scope (we have no external users; tests pin it in 9 fixture builders + `test_workflow_trace.py:362-420`).
- **D3 — one debug-dir resolver and one recency rule** replace the 8 copies and the mtime/timestamp split. Not a user
  decision; a constraint.
- **Out of scope:** the trace format itself; `pflow report`'s rendering; `analyze-cache`'s choice to load every trace of a
  workflow (it inherits the faster listing; its full loads stay its own problem — note it to #? at pick-up if it still hurts);
  the Viewer's per-process scan cache beyond what the new lookup makes unnecessary.

## Dependencies

None. Coordinate-with: nothing live touches `resume_source.py`, `workflow_trace.py`, `run_tailer.py` or `report.py` at
drafting time (session-16); the planner re-checks `git log` on those files against the plan's base.

## Requirements

### Lookup
- `pflow resume list`, `pflow resume <execution_id>`, `pflow report` (no path), `--only` snapshot selection, and
  `GET /api/gate` each perform at most one directory listing and read only files that belong to the answer. On a directory
  of 30,000 traces each returns in well under one second (acceptance: < 1 s wall on the owner's machine, measured with
  `/usr/bin/time`, against the 24 s baseline recorded above).
- Lookup by `execution_id` is exact: a newer trace of another workflow or another attempt never shadows it
  (`tests/test_runtime/test_resume_source.py:136-140` stays green).
- A consumed Paused Run (a newer attempt carries `resumed_from` = its id) is not listed, and the list and the resume verdict
  can never disagree (the one-consumption-policy invariant in `list_paused_runs`'s docstring stays true).
- `/api/gate` resolves a paused run without an unscoped scan; the Viewer's gate callout no longer shows "Loading gate…" for
  longer than the trace read itself.

### Retention (shape per D1)
- Never removed: a trace whose Run is Paused and not consumed; the newest success/degraded trace of each Workflow; the newest
  Attempt in any resume chain and the trace it was resumed from; any trace currently open by a writer (advisory lock).
- Removal is a no-op when the policy is off or the bound is not reached; it never runs on a read-only command.
- A removed trace is never referenced by a stale index or marker (a lookup after removal reports "no such run", not a crash).

### Consolidation
- One function resolves the debug directory; the 8 inline spellings are gone. One recency rule; `report`, the UI, resume and
  `--only` agree on "newest".
- `--no-trace` and `--report` precedence is stated in `--help` and the guide.

### Docs
- `docs/guides/debugging.mdx` and `docs/reference/configuration.mdx` describe the policy and what deleting traces breaks;
  the stale filename pattern in `docs/reference/cli/index.mdx:513,528` and `report.py:44` is corrected or removed.

## Implementation Notes

- The filename is the only per-file fact readable without opening it. Today it carries `md5(path)[:8]`, a 30-char display
  name and the start timestamp; the recency key regex is `workflow_trace.py:135`. Whatever the planner adds must survive
  the 3 path-spelling variants `_iter_workflow_traces` tolerates (`:163-171`) and the `None`/empty-path hash `d41d8cd9`.
- MCP `workflow_execute` runs ALSO write traces (`runner.py:224-226`, `execution_service.py:151`); two comments and ADR-0010
  `:149-150` still say the opposite — correct them in passing (write discipline: state the rule, not the incident).
- The Viewer already has two caches (`_SCAN_CACHE`, `_DIR_LIST_CACHE`, `run_tailer.py:208-251`) that a direct lookup may make
  partly redundant — the deletion test applies to them.
- Test blast radius (measured): `pytest -m trace_files` collects 594 of 11,868 tests; 9 test files build fake debug dirs
  with `format_trace_filename`; 8 files / 23 sites glob `workflow-trace-*` to find a produced trace; order/caching pins in
  `test_only_snapshot.py:438`, `test_resume_source.py:128`, `test_cli.py:320`, `test_run_tailer.py:245-391,599`.
- Engine contact: `engine.py:1041` calls `load_snapshot_or_raise`; the reader lives in `workflow_trace.py`, not the engine —
  the plan states whether any engine line changes (serialization + review trigger per ORCHESTRATION).

## Verification

- Build a 30k-file fixture directory (synthetic traces, one paused, one per-workflow newest) and time each lookup; assert the
  bound. Measure on the owner's real directory before and after (the Problem table is the baseline).
- Retention: a fixture with every protected kind; run the policy; assert each protected trace survives and `--only`,
  `resume <token>`, `resume list` still work; assert an unprotected old trace is gone and `report` does not crash.
- Real surface: `pflow resume list` / `resume <id>` / `report` / `pflow ui` gate callout on the owner's directory;
  `screenshot-pflow-web-ui` for the callout timing (no visual change expected).
- `pytest -m trace_files` and the Task-159 baseline (`.taskmaster/tasks/task_159/baseline/verify.sh`) green; `tests-windows`
  green (paths, file locks).

## References

- ADR-0007 (trace/cache separation, "delete freely"), ADR-0010 (resume = trace), ADR-0002 (`--only` snapshot = trace)
- Consumer finding F8: `~/projects/video-generation/projects/pflow-teaser/pflow-findings.md` (append-only, external)
- Verification reports: `scratchpads/session-16/verify/native-traces.md`, `out-traces.md`
- Related open issues: #734 (resume list has no workflow filter / path / start time in JSON — the same reader), #729 (a trace
  abandoned mid-run reads as interrupted), #763 (two concurrent resumes of one token both execute — a lookup/claim seam this
  task's marker, if any, may serve)
