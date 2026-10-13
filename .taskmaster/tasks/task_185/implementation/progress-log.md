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
