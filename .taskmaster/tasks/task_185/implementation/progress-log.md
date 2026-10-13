# Task 185 Implementation Progress Log

Spec: `../task-185.md`. Plan: `implementation-plan.md`. Checkpoint: `show-before-code.md`.
Entry format: ORCHESTRATION.md → "Progress-log entry format".

## [2026-10-12 14:40] task-planner (Fable) — planning complete, CP-1 pending
- Did: investigated (3 searchers + direct reads of the writer/readers/UI scanner), measured the owner's real
  `~/.pflow/debug` read-only (30,115 files, 2.58 GB), re-derived D2, wrote the plan and the CP-1 artifact.
- Changed: `implementation-plan.md`, `show-before-code.md`, this log. Spec untouched (CP-1 Q3 is the only
  spec edit pending — applied on ruling).
- Verified: every spec cite at `50f62327` (plan §0); `os.scandir`+parse+sort of 30,115 names = 82 ms;
  head/tail read 0.41 ms/file (so `resume list` = 24.8 s ≈ N head+tail reads — the whole cost); the Problem
  table's "hash-scoped glob still lists all N" (Python 3.13 `glob.py:428-434`); ui/ imports nothing from
  runtime/ today but may (hygiene test only forbids runtime→ui); `PFLOW_EXECUTION_ID` unvalidated;
  `test_workflow_trace.py:500` pins "id NOT in filename" (Task-32 era, reversed deliberately).
  | Assumed: Windows share-mode rename/unlink refusal (standard CRT behaviour; Task 116 log observed it —
  not executable here); the one-time migration ≈ 12 s + 2 s unlinks on the owner's dir (extrapolated from
  3,000-file samples; the bench in P5 measures it on a synthetic 30k dir).
- Deviations/surprises: the spec's protected-set rule "newest Attempt + its source" protects a file nothing
  reads (ADR-0010 lineage rule) → CP-1 Q3 instead of a silent edit. The owner's October rate (~1,700
  runs/day) makes a 14-day window barely a bound → recommendation is 7 days (Q2). Four twin helper pairs
  across runtime/ui exist, not three; the fourth (`_iter_raw_trace_lines` ↔ `run_node._iter_trace_lines`)
  is left out of scope and named in the plan. `docs/reference/configuration.mdx:129-139` documents five
  `PFLOW_TRACE_*` env vars that do not exist in `src/` — folded into P4 since the retention env var lands
  in that section.
- Self-checks: plan-mode battery dispatched via the codex fan-out (`review-plan`, `review-architecture-fit`,
  `review-concurrency-safety`, `review-feature-interactions`, `review-silent-failures`,
  `review-impact-completeness`) → `reviews/plan-review.md`; dispositions appended below when read.
- Next: main orchestrator hands CP-1 (`show-before-code.md` Q1–Q5) to the user; on ruling the task
  orchestrator applies Q2/Q3 to the spec + plan §1.5, then launches P1+P2 (one Opus implementer, effort
  high). **Resume point if this session is lost:** nothing is built; the plan is committed; start at P0.

## [2026-10-12 23:05] task-planner (Fable) — plan self-review (codex fan-out, 6 lenses) dispositioned
- Did: read `reviews/plan-review.md` in full; verified each Critical against code; folded fixes into the
  plan (§1.3, §1.4, §1.5, P2/P3 tests, §4, ADR draft) and the checkpoint (§5, Q3, Q4).
- Dispositions (finding → outcome):
  1. Migration rename-before-marker loses a pending pause — CONFIRMED → marker first, then rename; no
     orphan-marker deletion; the sweep reads the trailer before any deletion and heals a missing marker;
     finalize publishes the marker under the writer lock, before close.
  2. Deleting a consuming attempt resurrects an answered token — CONFIRMED (`_find_consuming_attempt`
     returns `None` without readable attempt evidence, `resume_source.py:265`) → rule 4: an Attempt
     outlives its source; sources removed first, chains unwound in passes; a skipped source keeps its
     attempts. Q3 rewritten accordingly (my "nothing reads the source" claim was the wrong direction).
  3. Live zero-work attempt counted as consumption by the sweep — CONFIRMED (`:268` lock clause) →
     `count_live` flag on the ONE policy; the sweep passes `False`.
  4. Migration renames a trace an old-version writer holds — CONFIRMED (POSIX rename succeeds; stale
     `_stream_path`) → migration skips incomplete legacy traces whose lock is held or unknown.
  5. Pinned tailer stranded by the rename — CONFIRMED (`_read_bytes` → `b""` forever) → retained-path
     rule: re-resolve the same id once, keep the offset; unpinned repoints by id without reset.
  6. UI by-id lookups lack the legacy arm — CONFIRMED → the legacy arm lives in `find_trace` (one home);
     both-generations matrix test across resume/gate/pinned/run-node/run-inputs.
  7. Trailer presence ≠ usability (report, snapshot protection) — CONFIRMED → report keeps the full-load
     check on a tail shortlist; the sweep protects via the snapshot loader's own selector
     (`_select_snapshot`, extracted from `load_full_run_events`).
  8. Snapshot protection grouped by hash — CONFIRMED → grouped by verified `workflow_path` (the sweep
     head-reads every candidate anyway).
  9. Settings fallback-to-defaults re-enables deletion — CONFIRMED (`settings.py:154-165`) →
     `SettingsManager.load_error`; the sweep prunes nothing when set + warns; `extra="forbid"` on
     `RuntimeSettings` so a misspelled key is a load error, not a silent default.
  10. Q3 status — noted; stays a CP-1 ruling. Viewer jump-link reads the source (`RunSelector.tsx:133`):
     degrades to text, acceptable; stated in Q3.
  - Warnings: `_iter_raw_trace_lines` has no `OSError` catch (`:144`) — accepted residual for the
    one-time migration race, documented in §4; multiple listings per public lookup → one listing threaded
    through `load_resume_source` and analyze-cache; scandir-count pin on public functions; persistent
    cleanup failures → `skipped` count + one warning; misspelled opt-out → `extra="forbid"` (above).
  - Suggestions folded: deterministic lifecycle fault tests (P3), both-generations matrix (P5), old
    printed paths invalidated (Q4 text), Task 121 note (ADR consequences).
- Verified: every cited `resume_source.py` line above read at `50f62327`. | Assumed: nothing new.
- Deviations/surprises: the battery's strongest finding (consumption evidence) inverted my Q3 argument —
  the dependency is attempt→source-verdict, not source→attempt data. The plan's complexity grew in the
  sweep (reads the truth before deleting); the lookup side is unchanged.
- Self-checks: no Critical left open; two residual races stated, not hidden. test-reflect: not applicable (plan).
- Next: commit; hand back for CP-1.

## [2026-10-13 00:10] task-planner (Fable) — CP-1 rulings folded (Q1–Q6)
- Did: applied the user's rulings — Q2 default 14 (+reason), Q3 five protected rules, Q4 clean cutover
  (migration phase and every legacy arm deleted; legacy names parsed only for their timestamp so the
  sweep ages them out; never protected, never surfaced), Q5 ADR-0018 + CONTEXT.md nouns written, Q6 the
  tar-backup gate in P5. Spec `## Requirements › Retention` rewritten; D2 ledger row marked decided.
- Changed: `task-185.md`, `implementation-plan.md` (§0, §1.1, §1.2, §1.4, §1.5, P0–P5, §3, §4),
  `show-before-code.md` (§9 rulings), `context/adr/0018-185-trace-directory-is-the-index.md`,
  `context/CONTEXT.md` (Retention, Protected trace).
- Verified: Q4 precondition at `50f62327` — no existing test asserts that a trace written by an older
  pflow is found; every old-grammar name under `tests/` is a fixture (composer-built or hand-written);
  the surfaces that lose pre-upgrade traces are exactly the ruled ones. | Assumed: nothing new.
- Deviations/surprises: with no renames anywhere, the Viewer-tailer retained-path rule folded in the
  first review round is dead — removed (deletion test). Phase bundling unchanged (P3 still carries the
  sweep + settings; nothing emptied).
- Self-checks: review round 1 was codex (6 lenses); the amendment asks for the FULL plan-mode battery
  natively on Claude, iterated to zero confirmed Criticals — rounds logged below.
- Next: commit; Claude battery round 1.

## [2026-10-13 01:30] task-planner (Fable) — Claude plan battery, ROUND 1 (6 lenses, opus/high, native)
- Lenses: review-plan, review-architecture-fit, review-concurrency-safety, review-feature-interactions,
  review-silent-failures, review-impact-completeness. Reported Criticals: 3 (plan C1 sweep cost;
  impact C1 + architecture C1 `extra="forbid"` wipe). **Verified Criticals: 2** (the two distinct ones).
- Dispositions (CONFIRMED → folded): sweep re-reads every protected aged trace each run (~5 s/run at the
  owner's shape) → cost model: names-only where possible, ≤1 tail per group, file-exists qualifier on
  rules 1/2/5 (amends ruled rules — flagged), second-sweep benchmark; `extra="forbid"` → dropped, sweep
  reads the raw `runtime` mapping, `load_error` + `save()` refusal; marker-after-trailer contradiction
  and the false "heals it" claim (all six lenses) → marker BEFORE trailer, no healing; unreadable
  candidate treated as "no trailer → delete" / one bad file aborts the sweep → three-outcome reads, per-
  candidate try, group kept on uncertainty, warning-level; raw re-read crash + the ADR residual → post-
  check `path.exists()` and vanished-Attempt-counts-as-consumed (residual closed); rule-4 wording
  inversion → waves defined root-first; `_stream_path.parent` after nulling → directory captured first,
  sweep unconditional; version skew with pre-185 readers → timestamp LAST (amends Q1 field order —
  flagged); rule 1 immortal unanswerable pauses → shared `answerable_pause` predicate (+ file exists);
  Task-159 cases 07/08/09 hand-write old names + case 15/03 sed mask + case 12/04 guide text → P1/P4;
  twins differ on UnicodeDecodeError → union; miss messages after cutover → legacy count clause on
  every surface; mid-task fan-out sweeps the real HOME before the P5 gate → env=0 from P3, gate at P3
  start, tar off /private/tmp (handback item); env override leaking into settings.json → read in the
  sweep, never applied to the settings object; subprocess env fixture → `set_isolated_home` too;
  `trace_dir` in `runtime/` drags the engine into ui → `core/trace_dir.py`; ADR-0007 "delete freely" →
  P4 amendment; grammar additive-only → ADR; orphan markers → collected; disk-full never sweeps → sweep
  after a stream fault too; report shortlist lazy → stated.
- REFUTED / not folded: none refuted outright; "throttle 1-in-N" (plan C1's suggested fix) not adopted —
  the cost model removes the cause instead of hiding it. `web/` banner copy left as is (true wording).
- Changed: `implementation-plan.md` (§0, §1.1–§1.6, P1–P5, §3, §4), ADR-0018 rewritten, CONTEXT.md
  Protected trace qualifier, `show-before-code.md` §10.
- Next: commit; round 2 (same six lenses) on the re-amended plan.

## [2026-10-13 03:10] task-planner (Fable) — Claude plan battery, ROUND 2 (6 lenses, opus/high, native)
- Lenses: the same six (round 1 had verified Criticals in plan + architecture/impact, and the fold
  rewrote §1.1/§1.3/§1.5 — every lens's surface changed). Reported Criticals: 2 (review-plan C1 and
  silent-failures C1 — the same finding). **Verified Criticals: 1**: the "three-outcome fail-closed"
  sweep reads were specified on the lenient twins, which return `None` on any `OSError`
  (`resume_source.py:165,1114`, `run_tailer.py:67,126`) — as written the sweep fails OPEN (EMFILE → "no
  trailer" → a pending pause or the Snapshot deleted) and the planned test mocked the helper, not the
  fault. Folded: strict readers (`read_trace_*_strict` raising `Unreadable`; lenient twins wrap them),
  `is_trace_locked(strict=)`, `workflow_file_state` three-outcome stat, the fault test injected at
  `builtins.open`/`os.stat`.
- Other dispositions (CONFIRMED → folded): legacy arm's `(.+)` swallowed dotted names (short ids,
  non-hex `from`, future tags) → legacy name group dot-free, unrecognised = not a trace, `.from-` accepts
  the id charset, unknown tags parse and are ignored, composer takes a `datetime` and asserts
  parse-back, shared fixture helper converts the 102 short-timestamp sites; nameless traces ARE produced
  (`workflow.pflow.md` → "workflow") → the name segment is always written; version-skew hazard stated
  backwards (an older pflow CAN answer a newer pause; its legacy-named Attempt is invisible → double
  answer) → ADR/P4 corrected, consumption arm over legacy names flagged as the user's call; settings:
  `model_dump` dropped the typo → `extra="allow"` (unknown keys survive, never fail validation) +
  `model_extra` check, no raw second parse (also closes the two-reads race), invalid env → `None`, older
  versions dropping the key documented with the env opt-out; `is_file()` swallows PermissionError on 3.14
  → three-outcome stat, unknown keeps the group; hidden deleted-file pauses counted on `resume list`;
  "vanished Attempt = consumed" cannot be built via `_iter_workflow_traces` → `_find_consuming_attempt`
  iterates its own candidates with three outcomes (loader raises a retryable error on a read fault);
  sweep after a mid-run fault → `_trace_dir` recorded at `_open_stream`; rule numbering → spec order
  (1 pause, 2 Snapshot, 3 newest run, 4 Attempt, 5 writer), spec Solution line + qualifier edited;
  rule-2 walk bounded to aged candidates (over-protect ≤1/group) + agreement test; rule 3 protects the
  source of a newest Attempt; hash-collision circularity → head-read each file about to be removed;
  legacy-count clause data paths (preflight re-raise, `list_paused_runs(listing=)`, `load_snapshot_or_raise`
  miss path, `traces_list.py`); `is_trace_locked` FileNotFound → False; lazy import in `finalize`;
  docs wording vs the file-exists rule; `debugging.mdx:66`; Task-159 case 03/06 rebuilt with 07–09;
  `tests/CLAUDE.md`; `find_workflow_trace` through the cached listing with one scoping rule.
- REFUTED / not folded: none refuted. Not folded: the Viewer `run-not-found` banner and `/api/run-inputs`
  404 legacy clause (`web/` untouched; noted); the three "valid pause" checks (`/api/gate` stays one
  conjunct stricter — documented).
- Changed: `implementation-plan.md` (§1.1–§1.6, P1, P3, P4, P5, §4), `task-185.md` (Solution line,
  rule qualifier), ADR-0018 (grammar, additive rule, fail-closed, settings, version-skew hazard).
- Round 3 selection (per-lens rule): KEEP review-plan and review-silent-failures (verified Critical),
  review-concurrency-safety (W1 important; the consumption iterator was rewritten), review-architecture-fit
  (W1 grammar — the parser was rewritten), review-impact-completeness (its W1 added consumers/data paths);
  RETIRE review-feature-interactions (no Critical; its findings were wording/docs and a renumbering, all
  folded; no new mechanism in its domain); ADD review-test-fidelity (plan mode — two rounds found the
  planned tests mocking the wrong seam and fixtures that would pass for free).
- Next: commit; round 3.

## [2026-10-13 00:55] task-planner (Fable) — ROUND 3 interrupted by a session limit; state + partial fold
- State: worktree clean at `a4534ebd` (round 2 folded). Round 3 had six lenses live (plan, silent-failures,
  concurrency, architecture-fit, impact-completeness, test-fidelity); five died with the limit (no
  report), **architecture-fit delivered**: no Critical; W1 unknown tags/sidecars must KEEP (a deleter
  honours what it does not understand — Task 121's future recordings vs older lanes), W2 ADR-0002:93-94
  still says the timestamp format is free to change (verified), S1 pre-#378 hash-less names are
  unrecognised (claim narrowed; owner's dir has 0), S2 scope the unknown-settings-key rule to
  `*retention*` keys at root + runtime (`extra="allow"` on both models). All four folded (plan §1.1,
  §1.5, P3, P4; ADR-0018). Also noted: main moved to `1df9ceb3` (#857) touching `configuration.mdx`
  and `resume_preflight.py` — the plan's line cites there shift by a few lines; re-grep at P1.
- Q4 confirmation (coordinator's question): the legacy arm is used for exactly two things — (a) the
  sweep parses an old name's timestamp to age it out; (b) `list_traces` COUNTS legacy names so every
  miss message can say "N traces written by an earlier pflow version are not searched" (round-1
  silent-failures W6 + impact W5: every surface otherwise misreports "No trace files found" beside 29k
  files). No lookup ever returns a legacy entry. (b) is an addition beyond the ruling's letter — one
  integer, trivially removable; flagged at handback.
- Resume point: relaunch the five dead lenses on `a4534ebd`+this fold (per-lens rule: all five had
  verified/important findings in round 2 or their surface changed); architecture-fit retired (clean).

## [2026-10-13 01:40] task-planner (Fable) — Claude plan battery, ROUND 3 (relaunched; 6 lenses incl. architecture-fit from the first attempt)
- Lenses and why: review-plan, review-silent-failures (verified Critical in round 2), review-concurrency-safety
  (important W1, consumption iterator rewritten), review-architecture-fit (grammar/parser rewritten),
  review-impact-completeness (new data paths), ADDED review-test-fidelity (two rounds found tests that
  pass for the wrong reason); review-feature-interactions retired (clean, no new mechanism).
- Reported Criticals: 5, all from review-test-fidelity (planned tests). **Verified: 5** — C1 read pins
  on the lister, not the surfaces; C2 dropping `os.utime` removes the only mtime-vs-start discrimination;
  C3 `f"id-{started}"` makes a filename sort pass as a time sort; C4 the cost bound admits a rule-2 walk
  over young files and an in-process cache; C5 rule 3 masks rule 1's `count_live=False` in the fixture.
  All five folded (read-SET pins per public surface, inverted `os.utime` pins, descending deterministic
  ids, opened-set assertions with fresh state, a newer unrelated run beside each rule-1 fixture). The
  other five lenses: 0 Criticals. Their Warnings, all CONFIRMED and folded: `answerable_pause` still
  used `is_file()` (raises on 3.10–3.13, `False` on 3.14) → tri-state via `workflow_file_state`, hidden
  count returned in `PausedRunListing` and rendered; group identity when the newest head is `None`
  (the disk-full file the sweep deliberately follows) → newest PARSEABLE head, else keep group;
  newline-less first line → `None` not `Unreadable`; rule-2 pick head-confirmed (reverse-direction
  collision) and `nodes_executed > 0` (residual closed); `--only` full-loads every newer failed run →
  tail shortlist; settings text contradicted itself (§1.5 vs §1.6 vs ADR) → aligned (root + runtime,
  `*retention*`, case-insensitive) + root test + `settings show` omits extras; new refusal raised as the
  base class → `ResumeSourceUnreadableError` + `_RESUME_REFUSALS` entry; UI reader twins' fate stated,
  oversized pins moved to the strict reader; orphan marker unlink after a positive `lstat`;
  `_attempt_consumed_work` propagates FileNotFound, callers map; rule-3 source search across the whole
  listing; flock non-blocking errors → `None`; `list_traces` error contract; aged-out hint on by-id
  misses; docs: env is per-process, newer pflow ages out older lanes' pauses, `execution_tools.py`
  docstring, `configuration.mdx` cites +1 (#857), Task-159 case 06 + regen of 15/03; dead
  `resumed_from=` param dropped; spec gained the four behaviour lines; §10 of the checkpoint corrected.
- Not folded (stated): the CLI sweeps before printing the outcome (Ctrl-C in the ~2 s first sweep loses
  the printed outcome once; one call site wins); readdir-vs-concurrent-unlink assumption recorded in the
  ADR rather than engineered around for rule 4.
- Stop: round 3 yielded verified Criticals only in the ADDED test-fidelity lens, all folded; per the
  user's rule no fourth round — handed back with that tally.

## [2026-10-13 01:20] task-orchestrator (Opus) — bootstrap
- Did: merged `origin/main` `c357671b` (#833 + #801) into the branch → `9ae17476` (clean, no conflicts); `make install`.
  Read packet, spec, plan, `show-before-code.md` §9–§11, this log, ADR-0018, ORCHESTRATION.md, Task 173's review.
- Changed: plan §P3/§P5 — the backup tar's path is the durable one; the "move it off /private/tmp" handback item is
  satisfied and removed.
- Verified: P5 backup gate (checked early; re-checked at P3 start and P5): `tar -tf /Users/andfal/projects/pflow/
  scratchpads/session-16/backup/pflow-debug-backup-2026-10-12.tar | wc -l` = 30,182 ≥ 29,000 (2.7 GB). #801's
  `workflow_trace.py` edit is inside `_aggregates` (trailer `warnings` scrub) — the plan's `finalize` calls `_aggregates()`
  once and does not touch it; #833/#801's `core/settings.py` edits are the `list-env` mask only (`_mask_value`) — disjoint
  from the plan's `trace_retention_days` / `load_error` / `save()` refusal. | Assumed: the remaining dependency reviews
  (133/164/171/172/180/184) are folded in the plan's §0 — the implementer reads 171/173/184 at P1.
- Rulings carried (main orchestrator, 2026-10-13): CP-1 Q1–Q6 as recorded; the four launch-time items ACCEPTED —
  (1) timestamp last + name always written; (2) rules 1–3 only while the workflow file exists, `resume list` hides AND
  counts such pauses (the count line is mandatory); (3) the cross-version double-answer is documented, not coded;
  (4) the legacy count in miss messages stays. Escalate (never decide): any engine line, any trace-format change,
  anything contradicting ADR-0018 or the rulings. #860 (`/api/gate` serves secrets raw) is NOT built here — leave the
  gate handler so the scrub is one call; comment the exact site on #860 at PR time.
- Deviations/surprises: none vs plan yet.
- Next: launch one Opus `task-phase-implementer` (effort high) on P1+P2 bundled.

## [2026-10-13 01:30] task-orchestrator (Opus) — PARKED on the P1+P2 implementer
- State: one Opus `task-phase-implementer` (effort high) launched on P1+P2 bundled at `72b0cc91`; it does not commit.
- Resume point: on its handback — read its P1/P2 log entries; confirm `make check` + `make test` + `pytest -m trace_files`
  green and `git diff --stat src/pflow/runtime/engine web/` empty; resume it with "fully happy?" then test-reflect
  (directed — read-set/order pins are easy to cheat); commit P1+P2; commission the plan's P1+P2 mid-task review
  (`review-silent-failures`, `review-feature-interactions`, `review-test-fidelity` via the codex fan-out, run by the
  implementer, waited in-turn); then P3 (backup gate re-check first; `PFLOW_TRACE_RETENTION_DAYS=0` from P3 on).

## [2026-10-13 02:10] task-phase-implementer (Opus) — P1 done (trace_dir module, writer, runtime readers)
- Did: built `core/trace_dir.py` (grammar composer/parser, one `list_traces` scandir, `find_trace`, strict+lenient
  meta/trailer readers, `is_trace_locked(strict=)`, `workflow_file_state`, `legacy_note`/`AGED_OUT_HINT`, `recency_key`);
  writer names traces through it + validates forced ids + writes the `.paused` marker before the trailer; every runtime/
  CLI reader moved onto one listing; legacy-count clause on every miss surface; Task-159 fixtures rebuilt.
- Changed: NEW `src/pflow/core/trace_dir.py`; `runtime/workflow_trace.py` (`format_trace_filename`/`_trace_recency_key`
  deleted; `_iter_workflow_traces(entries=)`; `load_full_run_events` tail shortlist; `load_snapshot_or_raise` miss causes;
  `__init__` id validation; `_open_stream`; `finalize` marker; 2 stale MCP comments); `runtime/resume_source.py` (by-id via
  `find_trace`; `_find_consuming_attempt(W, X, *, entries, count_live)` own iterator, 3-outcome reads; `load_resume_source`
  one listing + post-check `exists()`; `is_pause_record`/`answerable_pause`/`PausedRunListing`; twins deleted);
  `core/exceptions.py` (`ResumeSourceUnreadableError`; `OnlySnapshotMissingError(causes=)`); `execution/resume_preflight.py`
  (re-raise keeps the loader's causes); `cli/commands/report.py`, `cli/commands/resume.py` (list: hidden/legacy lines,
  "(workflow file unreadable)" cell); `core/prompt_cache_analysis/trace_loading.py` + `rendering/traces_list.py`;
  `core/CLAUDE.md`, `runtime/CLAUDE.md` owner rows; `tests/test_import_hygiene.py` docstrings+message; Task-159
  `03/06,07,08,09` command.sh (composed names; 06 real hash) + NEW twin `03/06-autoload-fires-without-the-flag`,
  `15/03` UUID mask; regenerated expected for 07/08/09/15-03/06-twin.
- Fixture helpers touched: NEW `tests/shared/trace_jsonl.py::{fixture_started, fixture_execution_id, trace_path_for,
  write_trace_file}` (ids DESCEND with time; refuses a non-current-grammar name); `test_resume_source._write_trace`/
  `_write_incomplete_trace` (+ marker on paused); `test_only_snapshot._write_trace`/`_write_interned_trace`;
  `test_resume_cli._write_incomplete_trace_for`; `test_resume_list_cli._write_paused_trace` (now creates its workflow file
  under HOME + marker); `test_cache_analysis_analyze._write_trace` (+2 inline sites); `test_cache_analysis_trace_listing.
  _trace_name`; `test_cli` report fixtures; `test_workflow_trace` :376/:500 flipped (id in name, reversed deliberately);
  `test_emit_time_trace` (`_collect_candidate_traces(list_traces(...))`).
- New tests: `tests/test_core/test_trace_dir.py` (43), `tests/test_integration/test_run_lookup_reads.py` (6 read-set pins),
  `tests/test_integration/test_pre_185_traces_are_not_searched.py` (presence over renamed copies + paired absence, 6 CLI
  surfaces + JSON stderr), loader tests in `test_resume_source.py` (+8), `test_run_outcome_cli.py::TestTheTraceNameAndThe
  PausedMarker` (4), forced-id test, untagged-`--only` snapshot test, report start-time-vs-mtime pin.
- Read-set pins (17 current + 2 legacy names; every pin also asserts `os.scandir` == 1): resume by id opens 2 (target +
  its dead attempt); resume by workflow 2; `resume list` 3 (2 marked + 1 attempt); `--only` snapshot 4 tail reads, ONE full
  load; `report` 3 (2 unfinished tail-only + the chosen). Mutation-verified (each fails under its mutation): consumption
  prefix filter dropped (3 pins fail), marker filter dropped, snapshot hash filter dropped, tail shortlist dropped,
  report tail pre-check dropped, by-id scan, iterator hash filter dropped. Order pins: whole-filename sort fails
  `test_only_snapshot:438`, `test_resume_source:128`, discover ×2, trace_dir listing, report pin; mtime sort fails the
  report and discover start-time pins. Loader pins mutation-verified: prefix-collision confirm, vanished attempt,
  unreadable attempt, `--only` meta guard by id, hidden count.
- Verified: `make check` green; `make test` 11889 passed (baseline 11817 passed, 0 failed → +72, 0 failed);
  `pytest -m trace_files` 624 passed (baseline 615); full Task-159 `verify.sh` 88/88 PASS (drift only in printed
  filenames, regenerated: 07/08/09 disclosure notes, 15/03 trace lines); `git diff --stat src/pflow/runtime/engine web/
  src/pflow/runtime/workflow_executor.py` empty; trace format/version untouched. Real CLI (isolated HOME): paused run →
  name `workflow-trace-8b631bbb-gate-demo.<uuid>-<ts>.json` + `.paused`; with 6,000 extra traces (3,000 legacy) `resume
  list` 0.61 s wall (≈ python startup), `report` 0.64 s; miss messages printed on all six surfaces (transcript reproduced by
  `scratchpads/task-185/show_miss.py`). | Assumed: Windows (no lock → `None`) untested here — `tests-windows` at P5.
- Deviations/surprises:
  1. `Unreadable` is `TraceUnreadableError(PflowError)` (CLAUDE.md: never vanilla exceptions); `TraceEntry` subclasses
     `ParsedTraceName` and carries `unknown_tags` + `other_sidecars` (P3's "unknown facts keep" needs both from the one
     scandir — built now so P3 adds no second listing).
  2. `_find_consuming_attempt` dropped its `debug_dir` parameter (unused once it iterates `entries`); it raises
     `ResumeSourceUnreadableError` for ANY non-FileNotFound `OSError` regardless of `count_live` — the sweep (P3) catches
     it and protects the source (one flag for liveness only).
  3. Miss clauses go in the refusal's SUGGESTIONS (aged-out hint + legacy note), not its message; the preflight re-raise
     keeps `miss.suggestions[1:]` (index 0 is the loader's generic remedy — pinned by the real-CLI cutover test).
  4. `--only` miss: `OnlySnapshotMissingError` gained `causes=` (appended to the default remedy) instead of reading its
     private `_DEFAULT_SUGGESTION` — **P4 must NOT add the aged-out sentence to `_DEFAULT_SUGGESTION` (it would print
     twice); the docstring edit only.**
  5. `resume list`'s legacy line prints only when there are no rows (plan); the hidden-pause line always when > 0. A
     consumed pause of a deleted workflow is NOT counted as hidden (it is not pending). The "(workflow file unreadable)"
     note is computed by the renderer (`workflow_file_state` per row) so `PausedRun` and the JSON layout stay unchanged.
  6. "Unrecognised dotted name `….x.y.z-{ts}`" from the plan's test list actually PARSES as current (`x` id, unknown tags
     `y`,`z` — the ruled forward-compat rule). Tests use names the current arm truly rejects (a digit-first tag, an empty
     segment, a short hash, a hash-less name, a sidecar).
  7. The post-consumption `path.exists()` re-check is behaviourally redundant today (`_apply_gate_resolutions` always
     re-reads the file and its `FileNotFoundError` gets the same refusal) — kept so the guarantee does not rest on that
     incidental read; its test pins the behaviour, and survives deleting either mechanism alone.
  8. `ResumeSourceUnreadableError` → `/api/resume` refusal `source_unreadable`; `web/src/api/client.ts` has no literal
     union (the refusal machine falls through to the generic arm) — no `web/` edit needed.
  9. A by-id CLI resume needs a uuid-shaped id (`_UUID_RE`); fixtures for CLI by-id paths use uuids.
- Consolidation candidates (logged, not built): `_iter_raw_trace_lines` ↔ `run_node._iter_trace_lines` (4th twin, plan
  §0); `report._trace_is_complete` full-load could become "trailer + version check" once P3's agreement test exists.
- Self-checks: fully happy? — raised and fixed: private `_DEFAULT_SUGGESTION` access (→ `causes=`); `monkeypatch.undo()`
  in two new tests also undid the conftest HOME isolation (made one assertion vacuous) → `monkeypatch.context()`; a report
  pin whose ids sorted WITH time (would pass a whole-name sort) → ids now sort against time; snapshot pin M3 survived the
  first fixture (no newer other-workflow trace) → fixture gained one, now fails. test-reflect: not run yet — awaiting the
  orchestrator's directed pass.
- Next: P2 entry below; then orchestrator's self-checks + mid-task review.

## [2026-10-13 02:15] task-phase-implementer (Opus) — P2 done (UI consumers)
- Did: `ui/run_tailer.py` lists through `trace_dir` (cache keyed `(dir, wf_hash|None)`, value an immutable tuple, order =
  start time; reader twins `_read_meta`/`read_run_trailer`/`_scan_tail_for_terminal`/`is_trace_locked` deleted —
  imported from `trace_dir` into its namespace); NEW `find_workflow_trace(workflow_key, run_id)` (one scoping rule with
  `scan_traces`: md5(key) hash + `_same_path` meta guard) used by `RunTailer._resolve_pinned` and `run_node._resolve_trace`;
  `server.gate` = one `list_traces` + `find_trace` (404 body carries the legacy clause; directory fault → 500 JSON);
  `_RESUME_REFUSALS` += `source_unreadable`.
- Changed: `ui/run_tailer.py`, `ui/run_node.py`, `ui/server.py`, `ui/CLAUDE.md`; tests `test_run_tailer.py` (`_tp`
  composes names with ids; prefer-live tests give the FINISHED run the newer start; new start-time-vs-mtime discover pin;
  rescandir pin on `run_tailer.list_traces` + tuple assert; junk-name test split into a composer-made unreadable file +
  "outside the grammar is never listed/opened"; `a_path.name in opened`; pinned exact+scoped test; the two
  `read_run_trailer` tests and the oversized `read_run_status` test MOVED to `test_trace_dir.py` against the strict/
  lenient readers), `test_ui.py` (`_write_trace(started, …)` composes names), `test_ui_interaction_server.py` (gate helper
  composes + marker; legacy 404 beside current 200; "500 other traces → opens exactly one"; corrupt-trailer gates assert
  "not paused"), `test_run_node.py`.
- #860 site: `src/pflow/ui/server.py::gate`, line 1582 — `trace = load_trace_file(entry.path)`; the scrub is ONE call
  there (`trace = scrub_secret_values(trace, secret_values(trace.get("inputs") or {}))`) before `gate_request` is read.
- Verified: gate read-set pin ("500 other traces → opens exactly one") mutation-verified: re-introducing the unscoped `scan_traces()` lookup in `gate` fails it; real surface on an isolated HOME with
  6,002 traces (3,000 legacy): `/api/gate?run=` 57–76 ms (200), miss 66 ms with "3000 traces written by an earlier pflow
  version are not searched.", `/api/runs?workflow=` 65 ms, bare `/api/runs` 562 ms cold / 84 ms warm; screenshot of the
  pinned paused run (`/tmp/pflow-shots/gate-demo-f4e6ebe0-…-deploy-185-….png`): gate callout rendered with its content
  (shell · deploy, command, Deny/Approve), no "Loading gate…"; server log clean; server killed. `git diff --stat web/` empty.
- Deviations/surprises: the scoped-cache prune still uses the name prefix (`workflow-trace-{hash}-`) rather than an entry
  set — exact for parsed names (the hash is the first field) and cheaper on the 4 Hz poll. `TraceCandidate.mtime` kept
  (shape unchanged) but no longer orders anything. `_check_stopped` now sees a vanished followed file as `False` (gone →
  no writer) → broadcasts `run-stopped` (before: `None` → silent); per plan's `is_trace_locked` contract.
- Tooling postmortem (screenshot-pflow-web-ui): worked — `screenshot.pflow.md` with `run=<token>&node=deploy` captured
  the gate panel first try. Friction: the skill assumes the REAL HOME's MCP registration; running it under an isolated
  HOME (to keep traces out of `~/.pflow/debug`) needed `pflow mcp add` + `mcp sync` into that HOME (~20 s) — idea (S):
  document an isolated-HOME recipe in SKILL.md. Near-miss: none. Observation (not this task): the RUN panel overlaps the
  GATE panel's left edge at default framing (run id truncated "f4…") — pre-existing layout.
- Self-checks: fully happy? — dropped an `__all__` I had added to `run_tailer` (it listed 3 names as the module's
  public API); no other loose ends known. test-reflect: awaiting directed pass.
- Next: orchestrator — "fully happy?" + test-reflect, commit P1+P2, then the mid-task review.

## [2026-10-13 02:40] task-phase-implementer (Opus) — P1+P2 directed test-reflect
- Did: applied `.claude/commands/test-reflect.md` to every P1/P2 test added or rewritten; mutations run for real and judged by
  the counted `N failed`; every mutation restored by writing the saved original back.
- Deleted (duplicates, nothing they alone could catch): `test_trace_dir::test_legacy_note_wording` (both wordings are
  asserted on the real surfaces — gate 404, loader suggestions, the six-surface cutover test);
  `::test_meta_readers_read_the_first_line` (every meta consumer test reads through it);
  `::test_recency_key_ranks_by_start_time_not_by_name` (reverting `trace_loading` to a name sort fails 4 analyze-cache
  tests and 1 listing test — the descending fixture ids make them discriminate).
- Deepened: `test_run_tailer::test_pinned_resolve_is_exact_and_scoped_to_its_workflow` now also spies the meta reads.
  Before, dropping the hash scope survived, because the `_same_path` meta guard still returned `None`; with the spy it
  fails. `test_pre_185_traces_are_not_searched` presence phase now also finds the same data through the loader, by id
  (the failed run) and by workflow (the paused run), before the rename to pre-185 names.
- Added: `test_trace_dir::test_fixture_ids_sort_against_start_time`, which guards the shared helper's DESCENDING ids;
  making the ids ascend fails it, and ascending ids would let every recency pin pass for free.
- Re-confirmed by real mutation: oversized-trailer full re-read dropped → 2 failed (strict-reader pin and the
  `resume list` surface pin); flock non-blocking `OSError` → `True` → 1 failed.
- Kept as is, after audit: the read-set pins (set-equality assertions plus scandir count, each mutation-verified in the
  P1 entry); the loader pins (each mutation-verified); the gate pins (legacy 404 beside a current-name 200; the
  "opens exactly one" pin mutation-verified); the marker and tag CLI tests (exact exit, status, on-disk and every-surface
  assertions); and every absence assertion, each of which has a presence twin in the same medium.
- Verified: `make check` exit 0; `make test` 11887 passed (11889 − 3 deleted + 1 added), 0 failed.
- Self-checks: test-reflect (directed) — 3 deleted, 2 deepened, 1 added; RESOLVED.

## [2026-10-13 03:20] task-phase-implementer (Opus) — P1+P2 mid-task review (`reviews/midtask-p1p2.md`) dispositioned
- Did: read the merged report in full, verified each finding against the code at `580657a1`, fixed 3, skipped 1.
- #1 (consumption re-read escapes as a 500) — CONFIRMED and FIXED as a class. `_attempt_consumed_work`'s raw re-read
  caught only `FileNotFoundError`, so a `PermissionError` escaped. The same gap also existed at the by-workflow
  dead-candidate check, at the by-id source load (where a non-FNF `OSError` was misreported as "no such run"), and at
  the source's post-selection raw re-reads.
  - The fix is ONE mapping, `resume_source._refuse_unreadable(path, execution_id, what)`: FNF passes through to each
    caller's own "gone" rule; any other `OSError` becomes `ResumeSourceUnreadableError`. It is applied to all four reads.
  - In `_find_consuming_attempt` it wraps the load and the re-read together: gone → consumed, `ValueError` → skip,
    other → refuse. The exception's docstring/title are generalized to "the run's trace".
  - Tests, with faults injected at `builtins.open`/`io.open` (never at a helper):
    - `/api/resume` on a REAL denied attempt with its second open faulted → 409 `source_unreadable`, no spawn. Its pair:
      vanished on the re-read → 409 `superseded`.
    - The loader unreadable-attempt test is now parametrized on-load / on-raw-re-read (was patched at `load_trace_file`).
    - Three new loader tests: source by-id load, source raw re-read, by-workflow dead-check.
  - Mutation: disabling the mapping fails 5 loader tests + the 409 test; vanish→skip fails the superseded pair.
- #2 (aged-out hint missing from the `/api/gate` 404 and `report <path>`) — CONFIRMED (plan §1.4 lists both) and FIXED.
  - Both now carry `trace_dir.AGED_OUT_HINT`.
  - Tests: the gate unknown-run test asserts the hint. The cutover test asserts it on `resume <id>` (through the
    preflight re-raise) and on `report <the pre-rename path>` (exit 1, "Trace file not found").
  - Mutation: dropping it from the gate, from report, or from the preflight carry each fails.
- #3 (UI pinned / run-node / run-inputs misses drop the legacy count) — SKIPPED, the plan's recorded `web/` exception
  stands. Verified in `web/src`:
  - the `run-not-found` SSE handler takes no payload (`events.ts` → `runNotFound()`);
  - `ThisRunSection` renders a fixed "Couldn't load run detail." whatever the body;
  - the Run panel's `fetchRunInputs` failure is a silent catch.
  So a server-side clause would land in bodies the browser discards — it buys nothing without a `web/` change. Its
  agent-facing twin (`/api/gate`) carries both clauses. Follow-up candidate: the Viewer's run-not-found banner names
  unsearched pre-185 traces (`web/` + the `run-not-found` payload).
- #4 (`--only` miss enumerates twice) — FIXED, because threading was simpler than the double list.
  - `load_snapshot_or_raise` lists once and passes `listing=` to `load_full_run_events` (new kwarg, mirrors
    `list_paused_runs(listing=)`); the miss reads `listing.legacy_count`. `_snapshot_miss_causes` is deleted.
  - Test: `test_only_snapshot_miss_lists_once_and_names_what_it_did_not_search` (scandir == 1, opens only that
    workflow's trace, clause present). Restoring the second listing fails it.
- Verified: `make check` exit 0; `make test` 11894 passed, 0 failed (11887 + 7); engine/`web/` diff empty.
- Deviations/surprises:
  - #1's class was wider than reported: the by-id source fault said "no run with execution id" for a run that exists.
  - One residual stays as is: `_iter_workflow_traces` still SKIPS a by-workflow candidate whose LOAD faults (its shared
    swallow is right for `--only`/analyze-cache). `resume <workflow>` can therefore pass an unreadable newest run to an
    older one. Noted for the completion gate; fixing it needs a resume-only iterator arm.
- Self-checks: fully happy? — yes for #1/#2/#4. #3 is a deliberate skip with a named follow-up. The residual above is
  stated, not hidden.
- Addendum [2026-10-13 03:45] — residual CLOSED (the 5th member of the unreadable-read class).
  - Shape chosen: one keyword on the shared iterator, `_iter_workflow_traces(..., unreadable="skip"|"raise")`. Resume's
    by-workflow selection passes "raise"; `--only` and analyze-cache keep "skip". In "raise" mode a faulting file's path
    is set on the error. One `_refuse_unreadable` (now accepting `path=None`) wraps the whole selection loop.
  - Rejected: a separate resume iterator, because it would duplicate the contents guards.
  - Folded: those guards now live in `workflow_trace._is_full_run_of`, and `resume_source._is_attempt_of` reuses it (no
    second copy).
  - Test: `test_by_workflow_an_unreadable_newest_run_refuses_never_falls_back_to_an_older_one`. A `PermissionError` at
    the open of the newest run gives `source_unreadable` naming that file. The control, a `FileNotFoundError`, selects
    the older run. Dropping "raise" or the raise arm fails it.
  - `make check` exit 0; `make test` 11895 passed.

## [2026-10-13 04:00] task-phase-implementer (Opus) — P3 handoff (from the P1/P2 implementer)
State at `ce784b91`. Read plan §1.5 + P3 first; below is only what the plan does NOT tell you (`file:line` at `ce784b91`).
**Interfaces P3 consumes — all in `core/trace_dir.py` unless named:**
- `TraceEntry` (:89) extends `ParsedTraceName` (:66). Fields: `workflow_hash`, `started` (str), `execution_id`
  (`None` = legacy), `only`, `resumed_from_prefix`, `unknown_tags: tuple`, `path`, `paused`, `other_sidecars: tuple`
  (suffixes of `{trace}.json.{x}` with x≠paused). `.legacy` and `.started_at` (handles both timestamp widths) are
  properties. For "unknown facts keep", test `unknown_tags or other_sidecars`.
- `list_traces(dir, *, include_legacy=True)` (:205) fills `TraceListing.legacy` (aged by `started_at`; never read) and
  always fills `orphan_markers` (a `.paused` whose base name is absent from the same raw scandir). Plan: unlink only
  after an `os.lstat` → `FileNotFoundError`. FileNotFoundError on the dir → empty listing; any other `OSError`
  propagates, so the sweep must catch it and warn.
- Strict readers: `read_trace_meta_strict` (:277) and `read_trace_trailer_strict` (:317). They raise
  `TraceUnreadableError(PflowError)` (:58, the plan's "Unreadable") and let `FileNotFoundError` propagate. `None`
  means readable but absent: a newline-less first line, or an unfinished trailer. Never use the lenient twins in the
  sweep.
- `is_trace_locked(path, strict=True)` (:359): True = held; False = free OR the file is gone; None = Windows / no flock;
  `TraceUnreadableError` = the open failed. `workflow_file_state(path)` (:392) returns present / absent / unknown.
- `resume_source.answerable_pause(entry, meta, trailer, file_state)` (:1154) returns yes / no / unknown;
  `is_pause_record` (:1135) is its record half. Pass the STRICT meta/trailer.
- `resume_source._find_consuming_attempt(workflow_path, execution_id, *, entries, count_live=True)` (:223).
  - It has NO `debug_dir` parameter (dropped).
  - Returns the consumer's id: a vanished attempt counts as consumed.
  - Raises `ResumeSourceUnreadableError` for ANY non-FNF `OSError` on an attempt (load or raw re-read), whatever
    `count_live`. The sweep passes `count_live=False`, and must catch that error and protect the source.
- `_refuse_unreadable` (:281) is resume's mapping. The sweep has its own policy, so don't reuse it there.
- The `--only` miss: `OnlySnapshotMissingError(causes=)` is already composed at `workflow_trace.load_snapshot_or_raise`
  (the aged-out hint is in). P4 edits the docstring only.
**`finalize` hook:** `_trace_dir` was NOT built. Capture it in `_open_stream` at `workflow_trace.py:1007`
(`trace_dir = debug_dir()`), before `_disable_streaming` can null `_stream_path`. `finalize` is at :1158: the marker
write and early return are at ~:1179–1188, and the `finally: self._close_stream()` is at :1191. Call the sweep after
the `finally` and on the marker-fault early return too. That early `return None` is inside the `try` — restructure so
the sweep runs on both paths.
**Fixtures (`tests/shared/trace_jsonl.py`):**
- `write_trace_file(debug, data, *, name, started)` (:167) composes the producer's name, writes the JSONL, and adds
  `.paused` when `final_status == "paused"`. It ALWAYS writes a `run.complete` trailer.
- For incomplete or 0-byte files, use `trace_path_for` (:142) and write the content yourself.
- `started` accepts "YYYYMMDD-HHMMSS[-ffffff]" or a datetime; a malformed clock string raises in strptime.
- Missing ids get `fixture_execution_id` (DESCENDING with time — keep it; `test_trace_dir` pins it).
- Legacy names: write `workflow-trace-{hash8}-{name}-{ts}.json` by hand.
- Paused fixtures that should be protected or listed need their `workflow_path` to EXIST (create it under HOME).
**Traps that bit P1/P2:**
- `monkeypatch.undo()` also undoes conftest's `Path.home`/HOME isolation, which silently makes later assertions
  vacuous. Use `with monkeypatch.context() as m:`.
- Inject faults at `builtins.open` + `io.open` (`Path.read_text` uses io.open) or at `os.stat`, never at a helper.
- CLI `pflow resume <id>` only takes the by-id arm for uuid-shaped ids (`_UUID_RE`). Fixtures on that path need uuid ids.
- A trace written outside `@pytest.mark.trace_files` is no-op'd at `_open_stream` (conftest). The finalize-hook tests
  need the marker.
- `_DIR_LIST_CACHE` (`ui/run_tailer.py`) is keyed on dir mtime. After a sweep unlinks files the mtime changes, so
  that's fine; but clear it in UI tests that mutate the dir within one second.
- A real mutation run's kill criterion is `N failed`. `scratchpads/task-185/mutate.py FILE OLD NEW -- pytest args`
  restores the file itself.
**Left for P3 deliberately:**
- the `trace_retention.py` module, settings and `conftest` env=0;
- the per-candidate strict head and lock probe on one handle (the plan's cost bound — `is_trace_locked` opens
  separately today, so a shared-handle helper may be worth adding);
- Windows `PermissionError` retry;
- `tests/CLAUDE.md` retention lines.
`count_live` is wired but no caller passes False yet.

## [2026-10-13 04:05] task-orchestrator (Opus) — P1+P2 closed; P3 launched on a fresh implementer
- Did: verified P1+P2 (`make check` green, `make test` 11,889 at my own run; implementer's later runs 11,895), committed
  `580657a1` (P1+P2) and `ce784b91` (mid-task review fixes). Mid-task review: codex fan-out, 3 lenses, all produced
  (`reviews/midtask-p1p2.md`); 0 standalone Criticals; 4 findings → 3 fixed + 1 skipped (dispositions in the 03:20 entry);
  the implementer's own residual (by-workflow resume falling back past an unreadable newest run) closed at my direction
  (03:45) — the "unreadable read as absent" class is now closed on all five resume reads.
- Round 2 of the mid-task review: NOT run — no verified Critical; the fixes' surface (resume read handling) is re-covered
  by the completion gate's silent-failures + test-fidelity lenses on the whole diff. Stated, not silent.
- P3 gate (fail-closed, checked at P3 start): `tar -tf …/scratchpads/session-16/backup/pflow-debug-backup-2026-10-12.tar
  | wc -l` = 30,182 ≥ 29,000 → PASS. From here every non-test `pflow` run from this worktree exports
  `PFLOW_TRACE_RETENTION_DAYS=0` until P5.
- Rotation: the P1/P2 implementer reached ~600k tokens (plan's rotation point ~400k) → P3 goes to a FRESH Opus implementer
  (effort high) whose packet is the plan + this log incl. the 04:00 handoff note. Stated reason: degrading window.
- Follow-up candidate (task-review): the Viewer's pinned `run-not-found` banner / "This run" panel / run-inputs prefill
  discard any server-side miss explanation (`web/` takes no payload) — needs a `web/` change to carry the legacy/aged-out
  clauses.
- Next: P3 handback → verify, "fully happy?", directed test-reflect, commit, mid-task review (concurrency-safety +
  silent-failures on P3's diff).

## [2026-10-13 03:05] task-phase-implementer (Opus, fresh) — P3 done (retention and settings)
- Did: conftest `PFLOW_TRACE_RETENTION_DAYS=0` in `isolate_pflow_config` + `set_isolated_home` FIRST; then NEW
  `runtime/trace_retention.py` (`retention_days` / `sweep_after_write` / `prune_traces`: the five rules, Attempt waves,
  orphan markers after `lstat`, Windows winerror-5/32 retry-once); settings field + `load_error` + `save()` refusal +
  `extra="allow"` on root and `runtime`; `settings show` omits unknown keys; the sweep wired into `finalize` (one call
  site, runs whenever the stream was opened — also after a mid-run fault).
- Changed: NEW `src/pflow/runtime/trace_retention.py`, NEW `tests/test_runtime/test_trace_retention.py` (48 tests,
  module marked `trace_files`); `core/settings.py`; `core/trace_dir.py` (see deviation 5); `runtime/workflow_trace.py`
  (`_trace_dir` captured in `_open_stream`; `finalize` → `_write_trailer` + sweep); `cli/commands/settings.py::show`;
  `tests/conftest.py`; `tests/test_core/test_settings.py` (+6); `tests/test_cli/test_settings_cli.py` (+1);
  `core/CLAUDE.md` settings paragraph; `tests/CLAUDE.md` `isolate_pflow_config` row.
- Verified: baseline `make test` 11895 passed / `pytest -m trace_files` 626 passed → after 11950 passed (+55, 0 failed)
  / 674 passed (+48); `make check` exit 0; `git diff --stat 10bad571 -- src/pflow/runtime/engine web/
  src/pflow/runtime/workflow_executor.py` empty; no trace-format change. **Cost, 2,000-identity fixture** (2,000 idle
  workflows × one aged Snapshot, 50 aged removable, one workflow with 1,000 young failures + an aged Snapshot):
  first sweep 2,078 opens, 0.07–0.14 s; **second sweep 2,003 opens, 0.07–0.11 s** — its opened PATH SET is exactly the
  2,001 aged Snapshots + the busy workflow's newest (young) trace; bound asserted `≤ 3 × groups`. Real surface
  (isolated `HOME` under `scratchpads/task-185/p3home.*`, every `pflow` call with `PFLOW_TRACE_RETENTION_DAYS=0` and
  provider keys unset): a gated run pauses (exit 4), writes trace + `.paused`, and an aged legacy + an aged
  deleted-workflow trace stay (env 0 holds in a real process); `settings show` hides a root `OPENAI_API_KEY` and a
  `runtime.trace_retention_day` typo while printing `"trace_retention_days": 14`; `settings set-env` on a file with
  `trace_retention_days: -5` exits 1 "Settings file not saved … could not be loaded … 'pflow settings reset'", file
  sha1 unchanged. The sweep itself on that real dir via Python (`sweep_after_write`/`prune_traces` — not a `pflow`
  invocation, per the safety rule): typo'd settings → stderr `WARNING: trace retention skipped: … sets
  runtime.trace_retention_day …`, nothing removed; valid file → `removed=2` (legacy + deleted-workflow trace), the
  paused trace + marker kept. | Assumed: the Windows arms (winerror retry simulated on macOS — `tests-windows` at
  P5); the first real-directory sweep (P5, behind the backup gate). No process left running.
- Deviations/surprises:
  1. **Plan contradiction resolved toward data safety — the identity read may be ONE young file.** §1.5 Identity
     grouping (walk back from the group's NEWEST name past `None` heads — "the disk-full run … leaves exactly that as
     the group's newest entry") and the P3 disk-full finalize test contradict the cost test's `opened ∩ young == ∅`.
     With aged-only reads, a run that hit a full disk (a young 0-byte newest name) makes the sweep delete the
     workflow's aged newest real run (rule 3). I followed the identity paragraph: the walk starts at the group's
     newest name, so a group whose newest is young costs exactly one young read; the cost test asserts
     `opened ∩ young == {that newest}` plus the exact path set. Side effect: the hash-collision case where an idle
     path's newest run hid behind the other path's young runs is closed too. ADR-0018's "reads only the aged files it
     is about to judge" needs a P4 touch ("…plus the head of each examined workflow's newest trace").
  2. "No head in the group parses → keep the group" applied to UNREADABLE heads only; a group whose every head is
     `None` (0-byte / newline-less) has nothing protectable and ages out — the plan's own table requires the lone
     0-byte file gone.
  3. Rule 3 also protects the source of the group's newest NAME when it carries `.from-` (not only of the newest
     parsed run) — names only, conservative.
  4. Collisions are judged in one place: the removal probe reads a head naming another workflow → rules 3 + 2 for that
     path, once per sweep (its newest-run walk may read young heads — collision groups only). The plan's extra "keep
     the collider's pick met on the rule-2 walk" call was redundant (its mutation survived) → deleted.
  5. `core/trace_dir.py` edited (outside P3's file list): `read_trace_meta_and_lock_strict` — strict head + flock probe
     through ONE open (the plan's per-candidate cost bound; the 04:00 note's "shared-handle helper"); `_probe_lock` /
     `_meta_from_first_line` now shared with `is_trace_locked` / `read_trace_meta_strict` (no twin; `fcntl` stays here).
  6. `cli/commands/settings.py::show` and `tests/test_cli/test_settings_cli.py` edited — required by §1.5 and the P3
     test list, missing from the P3 Files line.
  7. The save refusal raises the existing `UserFriendlyError` (no `SettingsError` exists — the plan's "nearest
     existing one"); `PflowCLI.invoke` renders it, exit 1.
  8. `SweepReport` gained `unreadable_paths` (the warning names the first three). `prune_traces` treats an
     `OverflowError` window (`999999999` typed as "forever") as nothing-aged instead of warning on every run.
  9. Unreadable granularity is the plan's (group kept on an unreadable identity head, marked trace, trailer before
     the Snapshot pick, or an Attempt / newer-than-pick probe; otherwise only the file). ADR-0018 says "its whole
     Workflow group" unconditionally — P4 reconcile.
  10. **Open, for the orchestrator (importance 2):** retention-key detection covers root + `runtime` extras only (plan
      §1.5; §1.6 freezes the other models). `llm.trace_retention_days` / `registry.…` are silently DROPPED by those
      models' `extra="ignore"` → retention stays ON, contrary to the ruling's "a key in the wrong place switches
      retention off". Closing it = `extra="allow"` on `LLMSettings`/`RegistrySettings`/`NodeFilterSettings` + `show`
      omitting nested extras + one detection walk. Not built (§1.6).
  11. Observed, not fixed: `retention_days()` loads settings once more per finalize, so a user whose settings file is
      0644 with `env` secrets now sees the pre-existing "insecure permissions" warning twice per run.
- Mutations (38 applied, **38 killed**, counted `N failed` over the 3 P3 test files / 188 tests;
  `scratchpads/task-185/p3_mutate_batch.py`, output `p3-mutations.txt`): rule 1 dropped 3; `count_live`→True 2; rule 2
  6; rule 3 8; rule-3 source 1; rule 4 2; rule 5 2; file qualifier rules 2–3 22 / rule 1 1; unknown facts 1;
  `nodes_executed` ignored 1; `.only` not skipped 2; collider via probe 1 / newest run 1 / Snapshot 1; identity
  unreadable fails open 1; walk-unreadable keeps only the file 1; pause unreadable fails open 1; `_note_unreadable`
  not protecting 1; probe-unreadable Attempt 1 / newer-than-pick 1; unknown file state ignored 1; legacy read 1;
  orphan markers kept 1; no Windows retry 1; sweep unguarded 1; invalid env → file 2; `load_error` ignored 1; suspects
  ignored 4 / root suspects 1; finalize never sweeps 6; `_trace_dir` not captured 6; sweep only on a clean trailer 2;
  runtime `extra="ignore"` 4 / root 2; save refusal dropped 3; `load_error` not cleared 1; `show` prints extras 1.
  Also: protect-every-aged-success (over-protection) 4 failed; vanished-attempt-not-consumed is killed by P1's
  `test_an_attempt_that_vanishes_mid_check_counts_as_consuming`.
- Consolidation candidates (logged, not built): (a) `resume_source._find_consuming_attempt` now has three consumers in
  two modules — make it public; (b) "retry once on a Windows sharing violation {5,32}" now exists twice
  (`mcp/manager._replace_config_file`, `trace_retention._unlink`) — two adapters, a real seam for one `core` helper;
  (c) `retention_days` logs its own reason — a `(days, reason)` return if a second caller (e.g. `settings show`
  printing the effective window) appears.
- Self-checks: fully happy? — raised and fixed: the redundant collider call (deleted), the unreadable-trailer hole
  (`_note_unreadable`'s protect was untested), the huge-window overflow, the identity read vs. the disk-full case
  (deviation 1). Remaining, stated: deviation 10 (wrong-section key — the orchestrator's call), deviation 11
  (duplicate warning), ADR sentences for P4 (deviations 1, 9). test-reflect (directed, RESOLVED): deepened
  `test_a_sweep_fault_never_changes_the_run_outcome` (now asserts the run's own trailer; labelled a regression guard —
  the CLI's `_save_trace_file` guard + the `trace_path` property keep the outcome even without `sweep_after_write`'s
  except, confirmed by mutation); deepened the collision rows (A1's newest run ≠ its Snapshot — before, dropping either
  collider rule survived); added `test_an_unreadable_trailer_on_an_older_trace_keeps_that_trace`,
  `test_an_unreadable_newest_trace_keeps_its_whole_group_even_without_a_snapshot`,
  `test_an_unreadable_attempt_or_a_trace_newer_than_the_snapshot_keeps_its_group` (each closed a surviving mutation);
  kept `test_two_interleaved_sweeps…` (the plan's (b); overlaps the vanish test but pins FNF-on-a-stale-listing ≠
  unreadable); deleted none.
- Next: orchestrator — verify, "fully happy?", commit, mid-task review (concurrency-safety + silent-failures on P3's
  diff). P4 reconciles ADR-0018 (deviations 1, 9); ruling needed on deviation 10.
- Addendum [2026-10-13 03:25] — orchestrator rulings on P3 items #1, #3, #4 accepted; fixes A and B done, in that order.
  - **Fix A (deviation 10 closed as a class).**
    - Every settings model now keeps unknown keys (`extra="allow"`): `NodeFilterSettings`, `RegistrySettings` and
      `LLMSettings` join root and `runtime`.
    - One walk, `core/settings.unknown_settings_keys(model) -> [(path, value)]`, covers `model_extra` at every
      level. Retention checks it for a "retention" key, at any depth, including keys nested inside an unknown
      section's value (`runtime_settings: {trace_retention_days: 0}`).
    - `settings show` builds one nested exclude from the same walk, so it omits unknown keys at every level.
    - Pre-check (grep over `src/` for `model_dump`, `model_fields`, `model_extra`, `vars(`, and every
      `settings.llm` / `settings.registry` / `settings.runtime` reader): every consumer reads named attributes
      (`llm_config`, `_probe_impl`, `execution_service`, `compile_validation`, `ui.py`, the `settings` CLI, the
      `should_include_node` filters). The only `model_dump()` calls are `save()` (keeping the unknown keys is the
      point) and `init`/`reset` (defaults, no unknown keys). Nothing iterates fields generically.
    - Tests: wrong-place parametrizations `llm.`, `registry.`, `registry.nodes.` and `inside-an-unknown-section`
      each give `None`, prune nothing, and log exactly one retention warning. Control: unrelated `llm.foo` +
      `registry.nodes.bar` → 14, and it prunes. `show` omits extras in `llm` and `registry.nodes` (presence:
      `tts_voice`, `output_mode`, `deny` still print). The `set_env` round-trip keeps an `llm.` typo.
    - Edited the ADR-0018 sentence (now "every settings model … allows unknown keys") and the `core/CLAUDE.md`
      line.
    - **Plan §1.6 NOT edited.** My standing rules forbid editing the plan; its "beyond `extra="allow"` on
      `PflowSettings` AND `RuntimeSettings`" now needs to read "on every settings model". That edit is yours.
  - **Fix B (deviation 11). The ruling's premise was partly off, so I widened the fix.**
    - A real run under an isolated HOME (retention 0, 0644 settings holding `env` secrets) already printed
      "insecure permissions" **6 times** before this diff; the sweep's extra read made 7 (6 under pytest with
      retention on).
    - Neither `load(validate_permissions=False)` nor reusing loaded settings meets "exactly once"; either only
      takes 7 back to 6.
    - Chosen, minimal: `_validate_permissions` warns once per settings file per process (module set
      `_INSECURE_PERMISSIONS_WARNED`). That closes the class, including the sweep's read, with no new parameter.
    - Trade-off: a long-lived MCP server warns once, not on every load.
    - Real run after the fix: 1 warning.
    - Test `test_a_run_that_sweeps_warns_about_insecure_settings_exactly_once`: a real CLI run with retention
      read from the file (env unset) and 0644 permissions. It asserts the aged trace is gone (the sweep read the
      settings) and exactly one warning (`== 1`, so it also fails if the warning vanishes). Without the dedupe it
      fails 6 == 1.
  - Mutations, all killed:

    | Mutation | Failed |
    |---|---|
    | `extra="ignore"` on NodeFilter / Registry / LLM | 1 / 1 / 2 |
    | walk not recursive | 7 |
    | unknown-section values not searched | 1 |
    | `show` excludes root extras only | 1 |
    | permission warning not de-duplicated | 1 |
    | suspects ignored | 8 |
    | runtime / root `extra="ignore"` | 4 / 3 |

    Two batch entries are obsolete (the per-section code they mutated is gone) and were removed. The
    `registry-extra-ignore` mutation first survived; adding a key directly under `registry` now kills it.
  - Gates: `make check` exit 0. `make test` 11957 passed (+7 over 11950, 0 failed); against the start-of-phase
    baseline that is 11895 → 11957 (+62). `pytest -m trace_files` 681 passed. The engine/`web/`/`workflow_executor`
    diff is empty.

## [2026-10-13 03:19] task-phase-implementer (Opus) — P4 done (docs, help, guide, MCP instructions, ADRs, instruction files)
- Did: worked through every item on the plan's P4 list, reconciled ADR-0018 with what was built, and added the
  `--help` precedence line.
- Changed:
  - **Help and docstrings:** `cli/commands/run.py` (`--no-trace` help); `guide/entry.md` (the `--help` Run Options);
    `core/exceptions.py::OnlySnapshotMissingError` (docstring ONLY — `_DEFAULT_SUGGESTION` untouched);
    `mcp_server/tools/execution_tools.py` (`workflow_execute` docstring).
  - **Docs:** `docs/guides/debugging.mdx` (filename pattern, example name, the "within the retention window"
    sentence, "Disk cleanup" → "Trace retention", the cutover + version-skew Note, the summary row);
    `docs/reference/configuration.mdx` (the field, the env row, the fake `PFLOW_TRACE_*` table replaced by the real
    trace configuration, the `debug/` row → "Caution"); `docs/reference/cli/index.mdx` (`--report`/`--report-dir`
    rows + precedence, two `trace_path` examples, the pattern + retention + older-traces bullets, the report
    example); `docs/reference/cli/analyze-cache.mdx` (example name); `docs/how-it-works/approval-gates.mdx`.
  - **Guide and MCP:** `guide/features/{resume,approval,ui,prompt-caching}.md`; `mcp-agent-instructions.md:853`
    (pattern + retention sentence; the `:2099` `jq` recipe left alone).
  - **ADRs:** ADR-0018 (Deletion bullet: the identity read may be one young file, the unreadable granularity,
    `nodes_executed > 0` — the "zero-event residual" sentence was false and is gone, collisions per path; Settings
    bullet: every model `extra="allow"`, the one recursive walk, the permissions warning once per file per
    process); ADR-0007 / ADR-0002 amendment lines; ADR-0010 `:149-150` corrected in place.
  - **Instruction files:** `.claude/skills/deep-review/SKILL.md` (sensitive paths: `core/trace_dir.py`,
    `runtime/trace_retention.py`); `.claude/agents/review-architecture-fit.md` (door 5: the filename grammar + the
    `.paused` sidecar); `.claude/agents/pflow-codebase-searcher.md` (search row); `make sync-claude-assets` (3
    files); `runtime/CLAUDE.md` (a row + one paragraph); `cli/commands/CLAUDE.md` (report row);
    `architecture/reference/template-variables.md:1749`.
  - **Task-159 baseline:** `run-case.sh` (`PFLOW_TRACE_RETENTION_DAYS=0` in its `env -i`); case
    `12/04-guide-auto-detect` regenerated.
- Verified:
  - `make check` exit 0. `make test` 11957 passed, 0 failed (unchanged — a docs phase). `tests/test_docs` 24
    passed. Task-159 `verify.sh` 88 passed, 0 drifted (run after the regeneration, and again after the
    `entry.md` edit). The regenerated case drifted only by the one pattern line.
  - Isolated HOME, every call with `PFLOW_TRACE_RETENTION_DAYS=0` and provider keys unset:
    - `pflow guide resume` renders the "Runs are kept for a window" bullet;
    - `pflow guide approval` renders the retention + older-version sentence;
    - `pflow guide ui` renders the retention-window run-id sentence;
    - `pflow --help` shows the `--report` / `--no-trace` precedence lines.
  - Assumed: Mintlify renders the new anchor `/guides/debugging#trace-retention` (heading "Trace retention" →
    slug `trace-retention`; not built locally).
- Deviations/surprises:
  1. **The `--help` precedence needed `guide/entry.md`, not only `run.py`.** `pflow --help` renders `entry.md`'s
     Run Options and `run` is a hidden command, so the `run.py` option help is not what an agent sees. The spec's
     "stated in `--help`" required the two `entry.md` lines (`--report` … even with `--no-trace`; `--no-trace` and
     what it costs).
  2. **The Task-159 harness now pins `PFLOW_TRACE_RETENTION_DAYS=0`.** `run-case.sh` builds its env with `env -i`,
     which strips any exported variable. A case that seeds aged fixture traces and then finalizes a run would
     otherwise sweep its own fixtures, depending on the calendar date. This mirrors the conftest change; the
     harness HOME was already isolated, so it is a determinism fix, not a safety one.
  3. ADR amendment lines carry "(Task 185)" and no date. ADR precedent is "Amended <date>"; I followed your
     no-dates instruction.
  4. The cutover text is concentrated, not repeated in full. The whole hazard list (answer pending pauses before
     upgrading; an older pflow can answer a newer pause unseen; an older `settings` write drops the key; set both
     opt-outs and why — the env var is per process and an MCP server launched by a desktop app does not inherit it;
     the newer pflow ages out the older lane's traces; `--only` needs one full run after upgrading) lives in
     `debugging.mdx`'s Note. `cli/index.mdx`, guide `resume`/`approval`/`ui` and the MCP instructions carry the
     short form (not searched / says how many / `pflow report <path>`); guide `resume` also carries "answer
     pending pauses before upgrading" (write discipline: one home).
  5. `architecture/historical/*` still show old patterns — left unchanged as historical records.
  6. `docs/reference/configuration.mdx` still lists `PFLOW_SHELL_STRICT`; it exists in `nodes/shell/shell.py`, so it
     stays.
- Self-checks: fully happy? — yes. Phrases grepped before writing: "retention window", "one recency rule", "listing
  is the index", "delete freely". No restated invariant now has two homes — the runtime paragraph points to
  ADR-0018 and `core/trace_dir.py` instead of restating them. test-reflect: not needed — a docs phase that added no
  tests.
- Next: orchestrator — verify, commit P4; the P3 mid-task review findings come to me afterwards (the review
  artifacts `reviews/midtask-p3.*` are untouched).

## [2026-10-13 03:31] task-phase-implementer (Opus) — P3 mid-task review (`reviews/midtask-p3.md`) dispositioned
- Did: read the merged report in full (2 convergent Criticals, 3 Warnings); verified each against the code at
  `98a09afc`; fixed all five, each with a regression test that fails without its fix.
- Changed: `runtime/trace_retention.py`, `core/settings.py`, `ui/run_tailer.py`, `context/adr/0018-…md`; tests in
  `test_trace_retention.py` (+10), `test_settings.py` (+1), `test_run_tailer.py` (+1).
- Dispositions:
  - **C1 — CONFIRMED, FIXED as a class.** Reachable when a run lasts longer than the window: an aged trace whose
    writer is still live. The sweep judged it from facts taken while it ran — the listing's marker flag, or a
    tail read with no trailer. The writer then finalized (marker, trailer, close), the probe saw the lock free,
    and the trace was unlinked: a pending pause, or the workflow's real newest Snapshot.
    - Fix: `_Sweep._remove` runs `_still_removable` before EVERY unlink attempt, i.e. after the lock was seen
      free, and on the Windows retry too. A `.paused` marker that appeared since the listing (`os.lstat`,
      three outcomes) keeps the trace this sweep. So does a trailer that landed on a trace a classification read
      as unfinished (`_Sweep._trailer` records those). A stale marker flag can therefore no longer orphan a
      marker either.
    - Tests: finalizes-Paused after the listing; finalizes-success after its tail read; a Windows retry after
      the writer finalized; a pause listed between its marker and its trailer (the Windows shape — on POSIX the
      held lock already keeps it, rule 5). Each has a control in which the unchanged unfinished trace IS removed.
      The interleaving is deterministic: a monkeypatched probe or unlink finalizes the trace and releases a real
      `flock`; no sleeps.
    - Mutations, each killed: marker re-check dropped, trailer re-check dropped, `_unfinished` not recorded,
      the pause rule's read not recorded, re-check on the first attempt only.
    - Residual, stated: on Windows (no lock), a writer that closes in the microseconds between the re-check and
      a SUCCESSFUL first unlink can still lose its trace. It needs a run longer than the window that finalizes
      in that instant; there is no atomic check-and-delete short of opening the file exclusively.
  - **C2 — CONFIRMED** (reproduced: Python 3.14, a directory chmod 000 → `Path.exists()` False, `open`
    PermissionError). **FIXED as a class.**
    - `_load_from_file` opens the file directly. `FileNotFoundError` / `NotADirectoryError` → defaults; any
      other fault → `load_error`, so pruning stops and saves are refused. The redundant `exists()` in
      `_validate_permissions` is gone too.
    - Swept for the class: `trace_retention`, `trace_dir` and `settings` have no other `exists()` / `is_file()`
      on a decision path. `settings init` / `reset`'s `exists()` only chooses whether to prompt; they are
      outside this diff and were left as is.
    - Tests: an `os.stat` fault on `settings.json` still honours its `0` (this fails on the old `exists()`
      shape); an `open` fault → nothing pruned, one warning, `set_env` refused, the file byte-identical.
    - Real check (isolated HOME, settings symlinked into a chmod-000 directory): `retention_days()` → `None`,
      with "trace retention skipped … could not be loaded (Permission denied)".
  - **W1 — FIXED.** `_first_insecure_warning` does the check-and-add under one module lock; the warning is
    emitted outside it. Test: two managers in two threads, rendezvousing after the membership answer, give
    exactly one warning. The unlocked version fails it (mutation). The test's first draft rendezvoused BEFORE
    the check and passed unlocked; it was rewritten.
  - **W2 — FIXED.** `SweepReport.unchecked_workflows` lists the paths whose `workflow_file_state` was `unknown`.
    The one warning (`_problems`) now names them: "kept the traces of N workflow(s) whose file could not be
    checked (…)". The existing unknown-state test asserts it through `sweep_after_write`; dropping the warning
    condition fails it.
  - **W3 — CONFIRMED** (narrow: the pin resolves, then a sweep removes the trace before its first read).
    **FIXED backend-only.** `_read_bytes` returns `None` for a vanished file. A pinned tailer whose run was not
    fully read then broadcasts the existing `run-not-found` and stops. `web/`'s handler already clears the
    canvas and shows the missing-run banner, so `web/` is untouched. Test: resolve then remove → exactly
    `[run-not-found]`. Without the fix it broadcasts run-stopped and keeps polling (the test times out and
    fails).
- ADR-0018: one sentence for the re-check after a free lock and before each unlink attempt; a settings file
  that exists but cannot be read is a failed load.
- Verified:
  - `make check` exit 0; `make test` 11968 passed (11957 + 11, 0 failed); `pytest -m trace_files` 690 passed.
  - The full P3 mutation batch was re-run: 44 applied, 44 killed. Two anchors were re-shaped and re-run by hand
    (`load_error` not cleared: 1 failed; dedupe dropped: 2 failed); one anchor is gone (`collider-from-walk`,
    deleted code).
  - `git diff` against the engine / `web/` / `workflow_executor.py`: empty.
- Deviations/surprises:
  - C1's real window is "a run longer than the retention window", so it is rare; it is fixed because a deleted
    pending pause is irreversible.
  - W1's first test draft was theater: it passed without the lock (the rendezvous came before the check). It was
    caught by mutation and rewritten.
  - The W3 fix does not cover the UNPINNED overlay; there, a vanished newest trace is simply re-discovered on the
    next poll.
- Self-checks: fully happy? — yes, with the Windows residual stated. test-reflect: each new test was
  mutation-verified (counts above); the `open`-fault settings test is a regression guard (the pre-fix shape also
  handled that arm), labelled as such; the `os.stat`-fault test is the one that proves C2's fix.
- Next: orchestrator — verify, commit; then the completion gate.

## [2026-10-13 03:50] task-orchestrator (Opus) — P3/P4 committed; P3 review round 2 dispatched; real-dir BEFORE timings
- Did: committed P3 `6966925a`, P4 `98a09afc`, P3 review fixes `7b4495ea`. P3 mid-task review round 1 (codex, concurrency-safety
  + silent-failures, `reviews/midtask-p3.md`): 2 convergent Criticals + 3 Warnings, all verified and fixed by the implementer
  (entry above). Round 2 dispatched on both lenses (both had verified Criticals) → `reviews/midtask-p3-r2.md`. The fan-out
  runs with the MAIN checkout's pre-185 pflow (no sweep code) + `PFLOW_TRACE_RETENTION_DAYS=0` — no sweep can touch the real dir.
- Rulings I made (importance 2, logged): retention-key detection widened to every settings section (one recursive walk) —
  the ruling's intent is "a misplaced opt-out never leaves deletion on"; the identity read may be one young file (data
  safety over the cost test's letter); the duplicate permissions warning deduped once per file per process (pre-existing
  6×, the sweep made 7×).
- BEFORE (pre-185 code = main checkout's `.venv/bin/pflow`, real `~/.pflow/debug`, 31,391 files, `/usr/bin/time -p`):
  `resume list` 14.92 s (first) / 4.15 s (page cache warm); `report` 0.25 s (newest trace complete — early exit);
  `resume 00000000-0000-4000-8000-000000000000 --dry-run` (by-id miss = full by-id scan) 7.29 s. The spec's 24.8 s was a
  colder cache. Running `resume <real paused token> --dry-run` on the real dir was refused by the harness's auto-mode
  classifier (irreversible-action guard) → P5 measures the by-id lookup through the miss path (same scan cost) instead.
- Next: round-2 report → disposition; then P5 (bench + real-dir AFTER behind the backup gate) and the completion gate.

## [2026-10-13 08:22] task-phase-implementer (Opus) — P3 mid-task review round 2 (`reviews/midtask-p3-r2.md`) dispositioned
- Did: read the round-2 report in full; both convergent findings verified against `7b4495ea` and fixed, each with
  a regression test that fails without its fix (mutation-verified, counted `N failed`).
- **#1 — CONFIRMED, FIXED as a class ("unavailable read as absent").**
  - **Settings:** in `_load_from_file`, `open()`'s `FileNotFoundError` / `NotADirectoryError` now means
    defaults only when `os.lstat` also finds no directory entry at the path. A dangling symlink, or anything
    else at the path that cannot be read, sets `load_error`: no pruning, one warning, and saves refused, so the
    link is never overwritten.
  - **Same class at the second decision point:** `trace_dir.workflow_file_state`. A workflow reached through a
    link to an unavailable target (an unmounted volume) was "absent", so its pending pause, Snapshot and newest
    run were removable. It is now `unknown`: the group is kept and the warning names it. `resume list` shows
    such a row with its "(workflow file unreadable)" note instead of hiding it.
  - Tests use real dangling symlinks: settings (control: a genuinely missing file → defaults → prunes, and saves
    a regular file) and a workflow (control: a deleted workflow's pause is removed).
  - Mutations: settings `_no_entry` bypassed → 1 failed; `workflow_file_state` link → absent → 1 failed.
- **#2 — CONFIRMED, FIXED.** A fault in the pre-unlink re-check (the marker `lstat`, or the trailer read) still
  keeps the trace. It is now recorded in `unreadable` with its path, so the one warning fires and names it,
  and it is no longer counted as "protected".
  - Test: parametrized on the two fault points, injected at `os.lstat` and at `builtins.open`/`io.open` only
    during the re-check. Control: an aged unprotected trace is removed by the same sweep.
  - Mutations: either record dropped → 1 failed.
- ADR-0018: the settings sentence ("only no directory entry at the path means no file …") and the workflow-file
  sentence (a link to an unavailable target counts as unknown, and is named).
- Verified: `make check` exit 0; `make test` 11973 passed (11968 + 5, 0 failed); `pytest -m trace_files` 695
  passed.
- Deviations/surprises:
  - Extended #1 to `workflow_file_state` (P1's module) — the same conflation at the deletion decision. The fix
    is one `lstat` fallback.
  - Consolidation candidate: `_no_entry` (no directory entry, not even a dangling link) now exists twice, in
    `core/settings.py` and `core/trace_dir.py` (7 lines each). Neither module is a natural home for the
    other's helper, and `core/` has no filesystem-utility module; it is not built.
- Self-checks: fully happy? — yes. test-reflect: each new test fails under its mutation (above); both controls
  are the presence half of their absence assertions.
- Next: orchestrator — verify, commit; then P5 (synthetic benchmark), not started.
