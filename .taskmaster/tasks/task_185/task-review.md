# Task 185 Review: Run Lookup Without a Directory Scan — a Bounded Trace Directory and Direct Lookup by Run

## Metadata
- Implemented 2026-10-13 on `feat/task-185-run-lookup`. Plan by a Fable planner (3 Claude plan-battery rounds + 1 codex).
  Built by three Opus implementers: P1+P2; P3+P4+bench; and a fresh completion-gate runner.
- Completion gate: 3 astra (codex) rounds, then 1 direct falsifier. Reports are in `implementation/reviews/`. Every finding's
  disposition is in `implementation/progress-log.md`.
- Base: `origin/main` `18036088`, merged in. PR: see the handback.
- No engine line changed. No trace-format change: `TRACE_FORMAT_VERSION` is unchanged and so are the meta/event/trailer
  lines.
- The design record is **ADR-0018** (`context/adr/0018-185-trace-directory-is-the-index.md`). The nouns **Retention** and
  **Protected trace** are in `context/CONTEXT.md`.

## Read First — the load-bearing block
- **What exists now:**
  - **The filename carries every fact a lookup filters on.** It is
    `workflow-trace-{hash8}-{name}.{execution_id}[.only][.from-{src8}][.{tag}…]-{started}.json`. A Paused Run gets an
    empty `{trace}.paused` sidecar. Each lookup does ONE `os.scandir` and opens only the files in its answer.
  - **Retention bounds the directory.** It uses `runtime.trace_retention_days`, default 14, and runs at `finalize`. It
    removes aged traces except the five Protected kinds.
  - **Settings faults never switch deletion on.**
- **Read these first:**
  - `core/trace_dir.py`: `trace_filename`, `parse_trace_filename`, `list_traces`, `find_trace`, and the strict/lenient
    readers (`read_trace_meta_strict`, `read_trace_trailer_strict`, `read_trace_meta_and_lock_strict`).
  - `runtime/trace_retention.py`: `retention_days`, `prune_traces`, `_Sweep`.
  - `runtime/resume_source.py`: `_find_consuming_attempt`, `answerable_pause`, `_refuse_unreadable`, `list_paused_runs`.
  - `runtime/workflow_trace.py`: `_open_stream`, `finalize`, `_iter_workflow_traces`.
  - `ui/run_tailer.find_workflow_trace`.
- **Invariants that must NOT break:**
  1. **`trace_filename` is the ONLY producer of trace names, and it asserts parse-back.** A name the parser rejects is
     not a trace: it is never listed, never protected and never deleted. If composer and parser drift apart, runs vanish
     from every surface. Fixtures go through `tests/shared/trace_jsonl.py`; never hand-write a current-grammar name.
  2. **The grammar is additive-only. The timestamp stays LAST and the `{name}` segment is always written.**
     - Pre-185 pflow versions sharing `~/.pflow` sort by the trailing timestamp and glob `{hash}-*`.
     - New facts become dot-tags.
     - A deleter KEEPS any trace with an unknown tag or an unknown `{trace}.json.{x}` sidecar (`_unknown_facts`), so a
       later pflow's "keep this" is honoured by older binaries.
  3. **`finalize` writes the `.paused` marker BEFORE the `run.complete` trailer.** A marker fault disables streaming and
     writes no trailer, so the run is non-durable on every surface. Reversing the order makes a durable pause without a
     marker, which `resume list` cannot see and the sweep can delete.
  4. **The sweep reads only through the STRICT readers.** Faults raise `TraceUnreadableError` and the trace is kept and
     counted. The lenient twins return `None` on any fault, and `None` means "delete" in the sweep, so using them there
     loses data.
  5. **An Attempt is consumption evidence: sources are removed before their Attempts (`_remove_in_waves`).** Deleting
     an Attempt while its source stays resurrects an answered token, and answering again repeats the side effect. A
     vanished Attempt counts as consumed.
  6. **An unreadable read is never "absent".** This holds on every lookup:
     - resume refuses with `source_unreadable` (409 from `/api/resume`);
     - `--only` refuses "Snapshot trace unreadable" and never restores an older upstream;
     - `report` names the skipped file;
     - `resume list` says the list is incomplete;
     - a settings path or workflow path that exists but cannot be resolved (a dangling symlink, EACCES) is `unknown`,
       never `absent`.

     The shared helper is `core/path_state.path_state`. Do not use `Path.exists()`/`is_file()`: on 3.14 they swallow
     `PermissionError`.
  7. **`retention_days()` is the ONE resolution order. `pflow settings show` ("Trace retention in effect: …") and a run
     both call it.** The order:
     1. the exact process variable;
     2. a failed settings load gives `None`;
     3. the exact `settings.env` value;
     4. a misspelled `PFLOW_*` variable gives `None`;
     5. a typo'd or misplaced key anywhere in the file or `settings.env` gives `None` (stems `reten`/`retain`, one
        recursive walk through dicts AND lists);
     6. `runtime.trace_retention_days`.

     `None` means prune nothing and warn once. Never add a second reader.
  8. **`SettingsManager.save()` refuses while `load_error` is set.** Otherwise a settings write after a failed load wipes
     the user's file, opt-out included. `init`/`reset` over a dangling link prompt, as they do for an unreadable file.
  9. **`debug_dir()` is evaluated per call, never at import time.** `tests/conftest.py` patches `Path.home` per test.
     `conftest` also exports `PFLOW_TRACE_RETENTION_DAYS=0` in `isolate_pflow_config` AND `set_isolated_home`, so tests
     opt in per test.

## What Was Built (actual vs. planned)
Built as the plan says, with these divergences (each is reasoned in the log):

**Lookups**
- **Resume is fail-closed on all five reads:** by-id load, by-workflow selection, the source re-read, the consumption
  check and its raw re-read.
  - `_iter_workflow_traces(entries, …, unreadable="skip"|"raise")`: resume passes `raise`; `--only` and analyze-cache
    `skip`.
  - The `--only` Snapshot path refuses on an unreadable newest candidate rather than falling back.
  - `_iter_workflow_traces` requires `entries` (callers own the one listing).
- `list_paused_runs()` returns `PausedRunListing` (runs + hidden-because-workflow-gone + unreadable). The CLI renders
  "N paused runs are not listed …" and "No readable paused runs; the list is incomplete". It owns its listing; there is
  no `listing=` parameter.
- **Miss clauses are suggestions, not message text.** These are `AGED_OUT_HINT` and `legacy_note(n)`.
  `OnlySnapshotMissingError(causes=)` carries them, and `_DEFAULT_SUGGESTION` does not repeat them.
- **A by-id hit on an `.only` trace refuses with its real reason.** A failed `--only` run prints no resume hint and has no
  `resume_command` (text/JSON/MCP). Its `execution_id`/`trace_path` stay.

**Retention**
- **The identity read may be ONE young file:** the group's newest name. This is data safety over the plan's
  "aged-only reads", because a disk-full run leaves a young 0-byte newest file.
- **The sweep re-checks the marker and trailer before every unlink** (Windows retry included), to close the
  finalize-vs-sweep race. Re-check faults are reported.

**Settings**
- `extra="allow"` is on EVERY settings model, so unknown keys survive saves and `show` hides them.
- A bool never validates as days (`mode="before"` validator). A quoted number still loads: a whole-file load failure
  drops the user's `env` keys for that run.
- Duplicate JSON keys fail the load (`object_pairs_hook`).
- The permission and failed-load warnings print once per file per process (`_WARNED` + lock).

**P5 on the owner's real directory (user-authorised):** the first sweep took 2.99 s wall, 31,396 → 23,182 files. Every removed file was older than 14 days by its name (checked against the backup tar's name list). One old-grammar pending pause (92 days, `escalate-demo`) went with them, as the clean cutover rules. No current-grammar trace was old enough to exercise rules 1–5 on real data; their evidence is synthetic plus the falsifier.

## Patterns & Anti-Patterns
- **Pattern — the listing is the index.** Answer with names first, then open only the answer, and pin it on the PUBLIC
  surface: `tests/test_integration/test_run_lookup_reads.py` intercepts `builtins.open` and `io.open` (`Path.read_text`
  uses only the latter) and counts `os.scandir`. A count on the lister alone is a tautology.
- **Pattern — three-outcome reads at every destructive or answering seam:**
  - `FileNotFoundError` means gone (each caller maps it: consumed / skip / no such run);
  - any other fault means unreadable (keep, refuse or disclose);
  - `None` means readable with no record.
- **Pattern — faults injected at `open`/`os.stat`/`os.lstat` for ONE path, each with a control** (an unrelated aged trace
  the same sweep DOES remove). A helper mock passes against a sweep that fails open.
- **Rejected:**
  - a global index file (it outlives traces: ADR-0007's GC problem);
  - renaming at finalize (moves a tailed file);
  - migrating old names, and a legacy lookup arm (owner ruling: clean cutover);
  - `extra="forbid"` on settings (a typo would drop API keys);
  - `StrictInt` for days (same reason);
  - "throttle the sweep 1-in-N" (hides cost instead of removing it).

## Gotchas & Non-Obvious Coupling
- **`monkeypatch.undo()` also undoes conftest's HOME isolation.** Later assertions then run against the real home or
  pass vacuously. Use `with monkeypatch.context() as m:`.
- **CLI `pflow resume <x>` only takes the by-id arm for uuid-shaped ids (`execution/resume_preflight._UUID_RE`).** CLI by-id fixtures need uuids.
- **Fixture ids from `fixture_execution_id` DESCEND with time** (pinned in `test_trace_dir.py`). Otherwise a whole-filename
  sort (id before timestamp) passes every recency test.
- **Python 3.14:** `Path.exists()`/`is_file()` return False on `PermissionError`.
- **Startup injection of `settings.env` aborts at the first un-settable key (e.g. `BAD=KEY`).** That is why
  `retention_days()` reads the stored exact override directly.
- **Any `uv run pflow <workflow>` from a 185+ checkout with the real HOME sweeps the real `~/.pflow/debug`.** This
  includes the review fan-out. Export `PFLOW_TRACE_RETENTION_DAYS=0`, or run the fan-out with a pre-185 pflow.
- The Task-159 harness `run-case.sh` uses `env -i`, so it sets `PFLOW_TRACE_RETENTION_DAYS=0` itself. Without it, cases
  that seed old traces delete their own fixtures depending on today's date.
- **Version skew is documented, not coded** (ruled):
  - a pre-185 pflow can answer a post-185 pause, and its old-grammar Attempt is invisible to 185+, so the pause can be
    answered twice;
  - a pre-185 settings write drops `trace_retention_days`;
  - a 185+ pflow ages out an older lane's traces.
- **The Viewer discards server-side miss explanations.** The pinned `run-not-found` banner, the "This run" panel and the
  run-inputs prefill take no payload, so the legacy/aged-out clauses need a `web/` change.

## Integration Points
- **New contracts:**
  - the filename grammar and the `.paused` sidecar (durable, on disk; ADR-0018);
  - `runtime.trace_retention_days` + `PFLOW_TRACE_RETENTION_DAYS`;
  - `SettingsManager.load_error` + the save refusal;
  - `ResumeSourceUnreadableError` (refusal literal `source_unreadable` in `ui/server._RESUME_REFUSALS`);
  - `TraceUnreadableError`;
  - `OnlySnapshotMissingError(causes=)`.
- **Consumers moved onto `trace_dir`:** resume, `--only`, report, analyze-cache (`trace_loading`, `rendering/traces_list`),
  and the Viewer (`scan_traces` cache now keyed `(dir, hash)` with an immutable tuple; `find_workflow_trace` shared by
  the pinned tailer and `run_node`; `server.gate`). `Path.home()/".pflow"/"debug"` now appears only in
  `trace_dir.debug_dir`.
- **#860** (`/api/gate` serves secrets raw) is not built here. The scrub is one call at `ui/server.py::gate`, right after
  `trace = load_trace_file(entry.path)` (≈ line 1587), before `gate_request` is read.
- **Follow-ups:**
  - the Viewer explaining misses (needs `web/`);
  - analyze-cache silently skipping an unreadable trace;
  - the fourth reader twin, `_iter_raw_trace_lines` ↔ `run_node._iter_trace_lines`;
  - making `_find_consuming_attempt` public (three consumers);
  - one shared Windows sharing-violation retry helper (`mcp/manager._replace_config_file`, `trace_retention._Sweep._remove`);
  - the Windows residual: a writer closing between the re-check and the first successful unlink.

## Tests That Matter
- `tests/test_integration/test_run_lookup_reads.py`: the read-set and scandir pins for every public lookup.
  Mutation-verified (each name filter dropped → fails).
- `tests/test_runtime/test_trace_retention.py` (55 tests):
  - `test_a_sweep_keeps_exactly_the_protected_traces` (per-item table of all five rules, real md5 collision);
  - `test_an_attempt_outlives_its_source` / `…_chain_unwinds_root_first`;
  - the `unreadable_*` family (fail-closed, with controls);
  - `test_the_second_sweep_reads_only_what_it_must` (cost: opened-path set);
  - `test_a_trace_that_finalizes_paused_after_the_listing_is_kept` (the race);
  - `test_settings_show_and_a_run_resolve_the_same_window`;
  - the settings-fault family (typos, dangling link, bool, duplicate keys, injection abort).

  44 + 2 mutations were applied across the P3 batch, and all were killed.
- `tests/test_core/test_trace_dir.py`: grammar round-trip, pre-185 reader compatibility (the old recency regex and
  `{hash}-*` glob accept every new name), unrecognised names, the descending-id fixture pin.
- `tests/test_integration/test_pre_185_traces_are_not_searched.py`: cutover. The same traces are found under current names,
  then missed (with the count) on six surfaces after being renamed to the old grammar.
- `test_run_outcome_cli.py::TestTheTraceNameAndThePausedMarker`: marker-write fault → non-durable everywhere.
- `test_only_snapshot.py:438`, `test_resume_source.py:128`, the discover/report start-time-vs-mtime pins: the one
  recency rule.
- Outer net: `.taskmaster/tasks/task_159/baseline/verify.sh` (88/88). The bench is
  `implementation/bench/build_bench.py` (`build` / `check` against the protected manifest).

## Performance (observed)
| | before (pre-185) | after |
|---|---|---|
| owner's real dir, 31,396 files: `resume list` | 16.8 s (spec baseline 24.8 s) | 0.28 s |
| real dir: `resume <uuid>` (by-id miss) | 3.9–7.3 s | 0.26 s |
| real dir: `report` | 0.38 s | 0.28 s (startup floor 0.20 s) |
| real dir: first sweep (one real run) | — | 2.99 s wall, 31,396 → 23,182 files; `--only --dry-run` after: 0.31 s |
| synthetic 30k (half old-grammar): every lookup incl. `--only`, `/api/gate` | — | 0.12–0.47 s |
| first sweep on 30k | — | 2.1–3.6 s (30,000 → ~3.8k–4.5k files), 0 protected missing |
| second sweep | — | 0.27 s; opens flat as history doubles |

---
*Distilled from the implementation context of Task 185. The chronological journey — every ruling, review round, and
disposition — lives in `implementation/progress-log.md`; this review is the durable forward-reference.*
