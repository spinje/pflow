# Merged Review Report

## Convergent findings

### 1. Report selection can conceal unreadable newer evidence; regression coverage misses the failing read

**Convergence: three lenses independently identify the same report-selection defect and its missing second-read coverage.** The production defect and test-coverage defect remain distinct below, with each lens’s stated severity preserved.

**Production finding — Critical: `review-silent-failures` (seam A); Warning: `review-agent-ux`.**

References: [report.py:20](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/cli/commands/report.py:20), [report.py:49](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/cli/commands/report.py:49).

When the newer completed trace’s trailer reads successfully but its subsequent full read raises `PermissionError`, `EIO`, `EMFILE`, or another `OSError`, `_trace_is_complete()` returns `False`. Selection silently advances to an older trace and prints “Using latest trace:” without identifying the skipped newer run. With no older candidate, it incorrectly describes the directory as containing “only in-flight or interrupted runs.”

The new warning covers only the preceding trailer read. Both lenses note that the regression faults every open, exercising that earlier branch alone. Silent-failures identifies this as an incompletely closed instance of round-one C1.

Requested correction: distinguish disappearance from other full-read failures and disclose the affected path and cause. Agent-UX additionally requests “No readable completed trace found” when unreadable candidates explain the miss.

**Test finding — Critical: `review-test-fidelity`.**

References: [test_cli.py:394](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/tests/test_cli/test_cli.py:394), [report.py:18](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/cli/commands/report.py:18).

The regression faults **every** open of the newer trace and asserts stderr identifies the skipped file. Consequently, it tests only trailer-read failure and passes despite silent fallback after a successful trailer read and failed full-load open.

Requested coverage: parameterize the existing test to fault the newer trace’s second open, retain the older readable control, and require the same path-and-cause disclosure. The lens states that this case would fail against the reviewed code, by inspection.

### 2. Unreadable pause listings: contradictory status and a missing trailer-failure regression

**Convergence: `review-agent-ux` and `review-test-fidelity` flag the same pause-listing area, with distinct defects.** Silent-failures seam A also inspected this area and reports that strict reads and visible disclosures are present; that clean assertion is preserved below.

**Status finding — Warning: `review-agent-ux`.**

Reference: [resume.py:477](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/cli/commands/resume.py:477).

With one marked trace raising `PermissionError` and no readable rows, text output starts:

> No paused runs.
> 1 paused run could not be read and may still be pending: …

The detail makes the failure diagnosable, but the headline asserts a state the lookup could not establish. The lens identifies this as a partial resolution of round one’s unreadable-pause finding.

Requested correction: reserve “No paused runs.” for a complete empty result. For unreadable candidates, use “No readable pending pauses could be listed; the list is incomplete,” followed by existing actionable details.

**Coverage finding — Warning: `review-test-fidelity`.**

References: [test_resume_list_cli.py:317](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/tests/test_cli/test_resume_list_cli.py:317), [resume_source.py:1194](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/resume_source.py:1194).

The regression correctly checks that a readable row survives and an unreadable candidate is disclosed in text and JSON, but its unconditional open fault always stops at the metadata read. Reverting only the trailer call to a lenient reader would leave the test green while allowing a permission failure after successful head reading to hide a pending pause.

Requested coverage: add a trailer-only fault parameter, reset injection for each CLI invocation, and retain readable-row controls and disclosure assertions.

## Critical

### A stored retention opt-out can silently become 14-day retention

**Lens: `review-silent-failures` (seam B).**

References: [trace_retention.py:115](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/trace_retention.py:115), [llm_config.py:245](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/core/llm_config.py:245).

Concrete stored settings:

```json
{"env": {"BAD=KEY": "x", "PFLOW_TRACE_RETENTION_DAYS": "0"}}
```

Both entries can be saved through `settings set-env`. Without a process override, startup injection attempts `BAD=KEY`, raises, catches the exception at debug level, and abandons subsequent entries.

At finalization, `retention_days()` excludes the exact override from suspects but never reads its stored value. It therefore returns **14**, deleting eligible aged traces despite the explicit **0**, without a retention warning.

The recorded empty-value residual crosses the same boundary: injection skips `""` or whitespace, and retention ignores the stored exact key and defaults to 14. An empty process override instead correctly warns and prevents pruning.

Requested correction: when the process override is absent, resolve and validate the exact stored override directly. A valid `0` must survive unrelated injection failures; an invalid stored value must warn and prevent pruning. Fix retention’s dependency on injection without changing general injection semantics.

## Warnings

### Snapshot recovery advice can resurrect an answered approval token

**Lens: `review-feature-interactions`.**

References: [exceptions.py:1404](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/core/exceptions.py:1404), [resume_source.py:253](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/resume_source.py:253), [resume_preflight.py:455](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/execution/resume_preflight.py:455), [trace_retention.py:505](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/trace_retention.py:505).

Snapshot refusal recommends moving an unreadable trace out of `~/.pflow/debug`. The lens supplies this interaction:

1. Paused run **P** is answered by successful Attempt **A**, which performs the approved side effect. Both traces remain within retention.
2. **A** becomes unreadable; `--only` refuses and recommends moving its trace.
3. Following that advice removes the only consumption evidence while leaving **P** and its marker.
4. `_find_consuming_attempt()` subsequently finds no Attempt and returns `None`. `resume list` offers **P** again, and answering it can repeat the side effect.

The vanished-Attempt safeguard does not cover removal before directory listing. Paused sources bypass the separate side-effect confirmation. The lens identifies a contradiction with retention’s source-before-Attempt removal invariant.

Requested correction: recommend restoring readability; any relocation guidance must preserve consumption evidence. Add coverage combining an answered pause, an unreadable successful Attempt, and the recommended recovery action. Existing tests cover unreadability and retention separately.

### The implementation plan still instructs agents to use superseded contracts

**Lens: `review-impact-completeness`.**

Reference: [implementation-plan.md:176](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:176).

| Lines in implementation-plan.md | Stale contract | Requested correction |
|---|---|---|
| 177, 227–228, 300, 613 | `workflow_file_state`, including `trace_dir.workflow_file_state` | Use `core.path_state.path_state`; preserve dangling-symlink → `unknown`. |
| 176, 325–326 | `is_trace_locked(..., strict=True)` | Document the parameterless lock probe and deleter’s `read_trace_meta_and_lock_strict`. |
| 221, 224 | `_iter_workflow_traces(debug_dir, ..., entries=None)` and fallback enumeration | Require entries as the first argument; callers own enumeration. |
| 228, 476–477 | `list_paused_runs(..., listing=None)`; “the CLI lists once and passes it” | The function owns enumeration; CLI consumes its `PausedRunListing`. |
| 244, 611 | `SweepReport.protected`, integer `skipped`/`unreadable`, `unreadable == 1` | Remove `protected`; document diagnostic tuples and count with `len()`. |
| 227–228 | `hidden_missing_file: int` | Document `list[PausedRun]` and new `unreadable` diagnostics. |

The reader table also says “shortlists by a lenient tail read first” at line 222, that skipping unreadable candidates is “right for `--only`” at line 225, and that “`path.exists()` is re-checked” at line 226. The lens states these contradict the round-one fixes.

An agent following the plan could reconstruct removed APIs or reintroduce older-Snapshot fallback and hidden unreadable pauses. Requested correction: update these instructions or mark them superseded with a nearby authoritative replacement. Progress-log dispositions alone leave contradictory guidance.

Mypy cannot check these prose contracts, and the agent-reference meta-test scans `.claude/agents` and `.claude/commands`, not this plan.

## Suggestions

### Delete the redundant protection pass

**Lens: `review-simplicity` — Suggestion, “Minor — take or leave.”**

Reference: [trace_retention.py:267](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/trace_retention.py:267).

`_Sweep.run()` revisits kept groups to add aged paths to `self.protected`. The only assignment of `group.kept = True` is in `_keep_group()`, which already adds those paths immediately, including during late removal probes.

Requested simplification: delete the three-line loop and retain the following candidate filter. The loop is redundant and implies protection requires a later reconciliation step.

### Make the gate diagnostic assertion prove path presence and deduplication

**Lens: `review-test-fidelity`.**

Reference: [test_ui_interaction_server.py:1309](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/tests/test_cli/test_ui_interaction_server.py:1309).

`count(str(target)) <= 1` accepts an omitted path. The injected `PermissionError` also has no filename, so reverting production formatting to interpolate the whole exception would not reproduce duplicate-path output.

Requested improvement: inject an unreadable-case exception containing `str(target)` and assert the path occurs **exactly once**. Preserve the disappearance case’s separate expectation.

## Verified clean

These are the lenses’ own assertions from static inspection, not additional verification by this merge.

### `review-silent-failures` — seam A

- Persistent Snapshot trailer-read faults reach the full loader; full-load I/O failures propagate as `OnlySnapshotUnreadableError`, preventing silent restoration of older upstream data. Disappearing candidates remain distinguishable.
- Paused-list head and trailer reads are strict; unreadable candidates reach visible text and JSON disclosures, including otherwise empty results.
- Gate directory/read failures produce an error response; disappearance produces the missing-run response. Neither becomes “not paused.”
- Failed Viewer head/trailer reads return before cache insertion; recovery retries without mtime/size changes, closing persistent negative caching.
- Resume’s post-consumption check uses `stat()` inside `_refuse_unreadable`, preserving permission/I/O failures.
- Exact run-ID lookup, full attempt-lineage confirmation, and loud failure for empty Snapshot results remain intact.

**Explicitly deferred, not verified clean:** Viewer discovery/history/pinned resolution and cache-analysis loading can still convert read failures into missing runs, shorter/empty lists, or older evidence. The lens records these as accepted follow-ups under the [10:50 disposition, progress-log.md:1117](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/progress-log.md:1117), without re-raising them as new findings.

### `review-silent-failures` — seam B

- Stored `settings.env` misspellings and process `PFLOW_*RETENTION*` misspellings warn and prevent pruning; exact process overrides retain recorded precedence. Unrelated process retention variables do not disable retention.
- `SweepReport` carries removal paths and causes into bounded visible warnings. Removing its protection tally preserves the protection set and source-before-attempt ordering.
- Failed/deferred source removal keeps dependent attempts.
- `path_state` preserves permission failures and dangling symlinks as unknown. Settings-load failures prevent pruning and ordinary saves.
- Strict-read failures, pending-pause consumption-check failures, and pre-unlink recheck failures preserve traces and reach warnings.
- Finalization publishes pause markers before trailers and invokes retention after stream closure.
- No additional protected-trace deletion path was established.

### `review-agent-ux`

- Snapshot refusal names the `--only` target, trace path, OS cause, reason for refusing older data, and recovery actions through the existing structured diagnostic mechanism.
- Hidden pauses identify tokens and missing workflow paths, give restoration instructions, and retain totals and truncation disclosure for larger lists.
- Retention removal warnings provide bounded path/cause samples and permission guidance.
- Settings and shell-variable warnings name unrecognized inputs, identify the supported setting/variable, and explain that `0` preserves every trace.
- Gate lookup distinguishes vanished from unreadable traces; unreadability names run, path, and cause.
- Documentation qualifies legacy disclosures as lookup-miss behavior, names Viewer exceptions, and correlates JSON `execution_id` with filenames.

### `review-simplicity`

- Round-one removals are complete: `SweepReport.protected` and reporting-only bookkeeping, optional iterator entries, `list_paused_runs(listing=…)`, and unused strict lock mode.
- `path_state` replaces duplicate filesystem checks and centralizes present/absent/unknown handling for settings, resume, and retention.
- `SweepReport` contains consumed results: removal counts and actionable failure details.
- Strict/lenient readers share parsing; retention’s combined head/lock read shares the lock probe.
- Remaining modes have callers: iterator fault handling supports different consumer policies, and `load_full_run_events(listing=…)` avoids another listing.
- Viewer membership/content caches have distinct invalidation needs; pinned consumers share `find_workflow_trace`.
- ADR-0018 records intentionally different environment-typo predicate scopes; consolidation would obscure that policy.

### `review-test-fidelity`

- The consumption-check regression faults only the attempt’s first open. A newer success eliminates alternative protection rules; pause/marker survival, a named warning, and unrelated-control deletion distinguish protection from sweep abortion.
- Prefix-collision coverage checks that an unconsumed pause survives pruning, remains listed, and resumes while the consumed source disappears.
- Snapshot tests cover persistent and second-open faults, typed refusal naming the newer file, and disappearance selecting distinguishable `OLD` output.
- Viewer cache recovery tests cover head/trailer faults and restoration of correct completed status on an unchanged file’s next poll.
- Post-consumption stat coverage reaches the intended check and asserts typed unreadable refusal and path.
- Settings tests distinguish misspellings that preserve aged traces with warnings, unrelated variables that permit deletion, and winning exact overrides.
- Removing the direct Pydantic constraint test preserves stronger behavioral coverage. The retained tuple assertion has an explicit plan requirement; the lens does not re-raise the disputed suggestion.
- The lens reports substantial behavioral confidence without material test bloat, subject to its listed gaps.

### `review-feature-interactions`

- Unreadability × `--only`: shortlisting and full loading address stale upstream data; `test_an_unreadable_newer_snapshot_refuses_never_restores_an_older_run` covers persistent/full-load faults.
- Unreadability × retention: unreadable traces remain protected; persistent refusal is recorded behavior.
- Retention × consumption: source-first deletion, denied Attempts, failed source removal, and chains are covered by `test_an_attempt_outlives_its_source` and `test_an_attempt_chain_unwinds_root_first`.
- Prefix collisions × pending pauses: an unconsumed colliding token remains protected, listed, and resumable.
- Markers × CLI/Viewer: marker failure prevents durable-pause publication; trailer failure after marker creation leaves no listed pause. `TestTheTraceNameAndThePausedMarker` covers these paths.
- `--only` × nested workflows, loops, and degraded batches: tests preserve whole-child execution, one loop iteration, resumed-loop seed boundaries, and degraded-Snapshot advisories.
- CLI/MCP share finalization through the collector; nested collectors create no independent streaming traces or sweeps.
- Report flags re-enable tracing under `--no-trace`; disabled streaming creates no sweep directory.
- ADR-0018 explicitly records old-writer consumption invisibility and settings-key loss; these were not re-raised.
- Viewer documentation was narrowed; remaining Viewer/cache-analysis limitations are explicitly deferred.

### `review-impact-completeness`

- Settings, retention, paused listing, and the CLI workflow cell use `path_state`; tests moved to `test_path_state.py`.
- Snapshot, resume, cache-analysis, and direct iterator tests pass entries to `_iter_workflow_traces`.
- Found callers use reduced `list_paused_runs` and `is_trace_locked` signatures.
- Retention diagnostics/tests consume reshaped `SweepReport`. The benchmark’s `"protected"` field counts its own manifest and is not a stale consumer.
- No obsolete references to the five named shapes were found in current source, tests, user docs, CLAUDE.md files, `.claude` agents/skills, or ADR-0018.
- Older progress logs, prior review reports, and Task 164’s plan are historical references.
- The lenient Viewer metadata spy still targets the lenient pinned resolver; it is not an unused patch binding.
- No unconverted executable consumers were found in the five named migrations.

## Coverage

**Six distinct lenses supplied seven reviews, all from `codex`. Failed-lens gaps input: none.** The reviewers’ own scope limitations remain explicit below.

| Lens / review | Provider | Reported coverage and limitations |
|---|---|---|
| `review-silent-failures`, seam A | codex | Static review scoped to seam A. Viewer discovery/history/pinned resolution and cache-analysis residuals were explicitly deferred. |
| `review-silent-failures`, seam B | codex | Inspected scoped production files, finalization/helpers, and retention/path-state tests. |
| `review-agent-ux` | codex | Inspected all requested message changes and whole-diff docs/guide changes. Did not complete full-file reading of every changed file’s unchanged body, especially large runtime/UI modules, instruction documents, and tests. Does not certify the whole-file completion requirement. |
| `review-simplicity` | codex | Read named shared modules fully and inspected scoped changes/relevant callers. Unchanged portions of `server.py`, `run.py`, `exceptions.py`, `execution_tools.py`, and documentation lacked the full-file pass. Not unrestricted completion-gate sign-off. |
| `review-test-fidelity` | codex | Examined scoped test changes and relevant production paths. Did not exhaustively reread unchanged bodies of every large modified file. Scoped fidelity review, not unqualified full-file clearance. |
| `review-feature-interactions` | codex | Covered trace discovery/retention, `--only`, resume/gates, nested workflows, CLI/MCP, Viewer history/replay, reports, cache analysis, settings, and mixed versions. Reports **97 changed files** on the branch; full-file reading remained incomplete for tests, documents, and task artifacts, especially large cache-analysis, trace-collector/UI tests, and unchanged exception definitions. Explicitly does not close the completion gate. |
| `review-impact-completeness` | codex | Targeted five interface migrations and related contracts. Reports incomplete full-file reading of **34 changed files**; does not certify the entire round-two diff. |

All supplied reviews report read-only/static inspection, with no tests executed and no files written. Feature-interaction combinations were verified through code/test inspection, not execution.
