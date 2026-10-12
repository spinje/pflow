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
