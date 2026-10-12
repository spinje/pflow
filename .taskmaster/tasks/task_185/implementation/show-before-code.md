# Task 185 — Show before code (checkpoint CP-1)

Planner (Fable), 2026-10-12. The user rules on the five questions at the end; nothing below is built yet.
Measurements are from the owner's real `~/.pflow/debug` (30,115 files, 2.58 GB), read-only, 2026-10-12.

## 1. The shape in one paragraph

The directory listing becomes the index. Every fact a lookup filters on is in the filename, so a
lookup is one `os.scandir` (82 ms at 30k entries, measured — parse + sort included) plus reads of
only the files in the answer. Paused-ness, the one fact known only at the end of a run, is a
sidecar marker file that dies with its trace. No second store, no rename of a trace after it is
written, no trace-format change (meta/event/trailer lines and `format_version` 2.10.0 untouched).
Retention is an age bound, applied when pflow writes a trace, that never takes a trace a feature
still reads.

## 2. The filename — before / after

Today (`format_trace_filename`, `runtime/workflow_trace.py:66-98`):

```
workflow-trace-fd2cea36-run-review-lenses-20261012-101500-123456.json
               hash8    name (≤30)        started
```

After — the run id, and the two flags every consumer filters on, join the name:

```
workflow-trace-fd2cea36-run-review-lenses-20261012-101500-123456.9b1c2d3e-4f5a-4b6c-8d7e-0f1a2b3c4d5e.json
                                                                 ^ execution_id (the resume token)
workflow-trace-fd2cea36-run-review-lenses-20261012-110000-000001.c0ffee00-….from-9b1c2d3e.json
                                                                           ^ an Attempt: resumed from 9b1c2d3e…
workflow-trace-fd2cea36-run-review-lenses-20261012-110500-000002.deadbeef-….only.json
                                                                           ^ an --only run (never a Snapshot or Resume source)
workflow-trace-fd2cea36-run-review-lenses-20261012-101500-123456.9b1c2d3e-….json.paused
                                                                           ^ sidecar: this Run is Paused (empty file)
```

Grammar: `workflow-trace-{hash8}[-{name}]-{started}.{execution_id}[.only][.from-{src8}].json`.
The fields after the timestamp are dot-separated, so a legacy name (no dots before `.json`) can never
be mistaken for a new one. The marker is `{trace filename}.paused` — it does not end in `.json`, so
no `workflow-trace-*.json` glob (tests, docs, `jq` recipes) ever picks it up.

What stays: the `workflow-trace-` prefix, the hash prefix (workflow-scoped listings), the display name,
the microsecond start timestamp (the one recency rule, D3). Max length ~140 chars (Windows-safe).

## 3. What each lookup costs after

| Surface | Before (30k dir) | After |
|---|---|---|
| `pflow resume <id>` | list + head-read every file until match | list; the one file |
| `pflow resume list` | list + head+tail of every file (24.8 s measured) + per-paused-row full loads of that workflow | list; markers → P pending rows → head+tail of those P; consumption check = lineage filter on names → full load of 0–2 attempts |
| `--only` Snapshot | list + full loads newest-first | list; non-`.only` traces of that hash newest-first; full load until success/degraded (usually 1) |
| `pflow resume <workflow>` | same | same as Snapshot (first non-dead attempt) |
| `pflow report` (no path) | stat every file + full loads | list; tail-read newest-first until complete (usually 1) |
| `GET /api/gate?run=` | unscoped scan of all N (the ~25 s "Loading gate…") | list; the one file |
| Retention sweep | — | list; delete by age; protected set from names (+ one tail read per workflow that has deletion candidates) |

Predicted on the owner's machine after migration: `resume list` ≈ 0.1 s + 20 pending × ~1 ms.
Per-file reads cost 0.41 ms (measured); the scandir+parse+sort of 30,115 names costs 82 ms.

## 4. `pflow resume list` — output unchanged, only the wait

```
$ /usr/bin/time uv run pflow resume list
TOKEN                                 WORKFLOW         PAUSED AT  GATE      AGE
3f2a1b9c-4f5a-4b6c-8d7e-0f1a2b3c4d5e  release-gate     publish    approval  2h
…
To answer: pflow resume <TOKEN> --approve yes|no
        0.9 real   (was 24.8)          ← the first run after upgrade pays the one-time migration instead (§6)
```

JSON output keeps every field (`path` now shows the new name).

## 5. Retention — the proposal (D1 chose "bounded with a protected set"; defaults are yours)

Settings key: `runtime.trace_retention_days` (integer, default **7**; `0` = keep everything).
Env override: `PFLOW_TRACE_RETENTION_DAYS` (same precedent as `PFLOW_TEMPLATE_RESOLUTION_MODE`).
Set by editing `~/.pflow/settings.json` (no new CLI subcommand — `pflow settings` has no generic
setter today and one key does not earn one).

```json
{ "runtime": { "template_resolution_mode": "strict", "trace_retention_days": 7 } }
```

When: at the end of every run that wrote a trace (CLI, UI-spawned, MCP `workflow_execute`) — inside
`finalize()`, after the trailer is written and the file closed. Never on `report`, `resume list`,
`pflow ui`, `--dry-run`, `--no-trace`. Cost on a converged directory: one listing (~10 ms) + unlinks
of whatever aged out since the last run.

Never removed, whatever the age (the protected set):
1. a Paused Run whose token is still answerable (marker present, no newer Attempt consumed it — the
   same `_find_consuming_attempt` policy `resume` and `resume list` use);
2. the newest Success/Degraded full run of each Workflow (the `--only` Snapshot; `.only` runs excluded);
3. a trace whose writer still holds the advisory lock (POSIX; on Windows there is no lock and no run
   lives 7 days, so age decides).

4. an Attempt, until the Run it resumed is gone — "this token was already answered" is read from the
   Attempt, so it outlives its source (sources go first, attempts after; a chain unwinds in one sweep).

Removed once older than the window: every other trace — success, failed, denied, incomplete
(crashed), consumed paused — and its marker. Before deleting anything the sweep reads the file's
trailer (the truth; the filename and marker are only the index), so a paused run whose marker is
missing is kept and its marker repaired, and a newer trace with a corrupt body never displaces the
usable snapshot. If `settings.json` cannot be loaded, nothing is pruned and a warning says so —
a typo elsewhere in the file can never switch deletion on.

Why 7 and not 14: the owner's October rate is ~1,700 runs/day (21,168 traces in 12 days), so a
14-day window still holds ~24k files / 1.5 GB; 7 days ≈ 12k files / 750 MB; the protected set keeps
`--only` and pending pauses working regardless of the window, so the window only bounds "resume or
report a run from N days ago".

The directory after the first sweep (owner's machine, predicted): 30,115 → ~12k files (every
October run newer than 7 days) + ~2,500 protected newest-successes of older workflows + the ~20
pending pauses. Nothing a feature reads is gone; `rm` would have taken all of it.

## 6. The one-time migration (first run after upgrade)

Pre-upgrade traces have no run id, flags or marker in their names. The first sweep renames every one
into the new grammar (one head+tail read each: 0.41 ms/file, measured) and writes `.paused` markers
for paused ones, THEN prunes. On the owner's 30k directory that is ~12 s + ~2 s of unlinks, once, at
the end of the first run, announced on stderr:

```
WARNING: updating 30,115 trace files to the current naming (one-time; ~15 s)…
```

Until that sweep has run, every lookup still finds pre-upgrade traces (a legacy arm reads them the old
way), so a token printed before the upgrade stays answerable. After it, no legacy name remains.

## 7. What else changes that you will see

- `--help` for `--no-trace` says `--report`/`--report-dir` re-enable the trace (today only two doc
  lines say so).
- Docs stop advising `rm ~/.pflow/debug/workflow-trace-*.json`; they state the window, the protected
  set, and what deleting a trace breaks (`--only`, `resume`, pending pauses, `report`, analyze-cache).
- The stale filename patterns in `docs/reference/cli/index.mdx`, `debugging.mdx`, `analyze-cache.mdx`,
  `report.py --help` are corrected to the new grammar.
- `/api/runs` `trace_file`, `resume list --output-format json` `path`, `Workflow trace saved:` show
  the new names. No UI visual change (the gate callout just stops waiting).
- The Viewer's two caches stay (they bound the 4 Hz poll); the list they cache is the shared one and
  it sorts by start time, not mtime (D3).

## 8. Questions for the user (rulings needed before building)

**Q1 — Filename grammar (§2).** Accept `…-{started}.{execution_id}[.only][.from-{src8}].json` +
the `.paused` sidecar? Alternative considered and rejected: renaming the trace at finalize to stamp
its status (`….paused.json`) — it would move a file the Viewer is tailing and the printed path, and
needs a Windows rename-retry; the sidecar is one `open(…, "x")`.
*Recommendation: accept.*

**Q2 — Retention default and key (§5).** `runtime.trace_retention_days = 7`, `0` = off, env
`PFLOW_TRACE_RETENTION_DAYS`, no new `pflow settings` subcommand.
*Recommendation: 7. (14 if you want "resume last week's failure" to always work; it costs ~2× disk.)*

**Q3 — The protected set.** The spec protects "the newest Attempt in any resume chain and the trace
it was resumed from". The real dependency runs the other way: nothing restores from an Attempt's
source (ADR-0010 — attempts are self-contained; the Viewer's "resumed from" jump link degrades to plain
text when the source is gone), but the SOURCE's "already answered" verdict is read from its Attempt.
So the rule becomes §5 item 4 — an Attempt outlives its source — and an old failed Attempt is otherwise
no more protected than an old failed Run. The spec line is rewritten to that on ruling.
*Recommendation: accept the four rules in §5.*

**Q4 — The one-time migration (§6).** ~15 s once at the end of the first run after upgrade, with a
stderr line; it renames files, so any trace path printed BEFORE the upgrade stops resolving
(`pflow report <old path>` says "Trace file not found" — the run is still found by its id). A trace an
older pflow is still writing at that moment is left alone (lock probe). Alternative: migrate in bounded
batches of ~3,000 per run (1–2 s each, ~10 runs to converge) at the cost of a batch constant and a
longer window in which lookups use the slower legacy arm.
*Recommendation: one-shot, old printed paths accepted as invalidated.*

**Q5 — ADR.** "A Run is found by its filename: the trace directory listing is the index; paused-ness
is a sidecar that dies with its trace; retention protects exactly what features read" meets the ADR
bar (hard to reverse, surprising without context, a real trade-off against an index/SQLite). The main
orchestrator writes it on ruling; draft text is in `implementation-plan.md` §ADR.
*Recommendation: yes.*
