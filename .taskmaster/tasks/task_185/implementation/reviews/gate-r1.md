# Merged Review Report

Findings retain their originating severity and attribution. Shared-area convergence is distinguished from duplicate-defect convergence; related but distinct findings remain separate.

## Convergent findings

### 1. Viewer legacy-trace disclosure — two lenses

**Lenses:** `review-feature-interactions`, `review-agent-ux`
**Convergence:** Both identify missing legacy-trace disclosure in Viewer discovery. The feature-interactions handoff explicitly names agent-ux and impact-completeness.

- **Suggestion — Viewer discovery drops the cutover disclosure.** `[review-feature-interactions]`
  `src/pflow/ui/run_tailer.py:138` discards `legacy_count`; consequently, `/api/runs` at `src/pflow/ui/server.py:1486` returns an unexplained empty list for an old-trace-only directory, despite the requirement that misses disclose unsearched traces. The lens requested a handoff to `review-impact-completeness` / `review-agent-ux`.

- **Warning — Documentation promises skipped-trace counts that Viewer does not provide.** `[review-agent-ux]`
  `docs/guides/debugging.mdx:111` and `docs/reference/cli/index.mdx:517` say each surface reports how many older traces it skipped. With only older traces, history says “No runs yet for this workflow,” and pinned replay emits only `run-not-found`. `/api/gate` includes the count, but history and replay do not. Surface the disclosure or narrow the documentation; also qualify CLI disclosures as occurring on lookup misses, because successful lookups do not always report skipped traces.

**Related clean assertions retained without adjudication:** `review-impact-completeness` calls the Viewer count omission a documented plan exception. `review-spec-conformance` records a UI deferral, including the pinned-banner/run-inputs exception at progress-log:398. `review-silent-failures` explicitly did not re-report the documented UI legacy-message exception.

### 2. Snapshot and pending-pause lookup helpers — two lenses, distinct findings

**Lenses:** `review-silent-failures` seam A, `review-simplicity`
**Convergence:** Both identify findings in `workflow_trace.py` lookup iteration and `resume_source.py` paused-run listing. These are shared-area findings, not duplicate defects.

- **Critical — An unreadable newest Snapshot silently selects older upstream data.** `[review-silent-failures, seam A, C1]`
  At `src/pflow/runtime/workflow_trace.py:318`, the shortlist uses `read_trace_trailer`, which converts read faults into `None`. Given two successful runs with different upstream outputs, a `PermissionError` reading the newer trace excludes it; the older trace supplies the Snapshot, and `--only` can succeed with stale data. A fault during the subsequent full load is also silently skipped at `workflow_trace.py:149`.

  **Requested change:** Distinguish disappearance from unreadability at both reads and refuse Snapshot lookup with the affected path. Related report shortlisting and analyze-cache iteration also need visible disclosure rather than silently selecting older evidence.

- **Critical — An unreadable pending pause produces a successful “No paused runs.”** `[review-silent-failures, seam A, C2]`
  At `src/pflow/runtime/resume_source.py:1189`, both reads are lenient. A `PermissionError` or other I/O error reading an existing marked pause’s head or trailer skips the row without a counter or diagnostic. With no other pauses, the CLI successfully returns `No paused runs.` or JSON `[]`. `hidden_missing_file` does not account for this case.

  **Requested change:** Use strict reads and either fail visibly or explicitly report unreadable pending candidates.

- **Suggestion — Finish choosing who owns directory enumeration.** `[review-simplicity, finding 2]`
  `_iter_workflow_traces` at `src/pflow/runtime/workflow_trace.py:100` accepts either a directory or entries, but all three production callers supply entries. They therefore pass an ignored directory argument, including literal `None` in cache analysis. Conversely, `list_paused_runs` at `src/pflow/runtime/resume_source.py:1172` accepts an optional listing that no caller supplies.

  **Requested change:** Require entries for the shared iterator and let `list_paused_runs` obtain its own listing. This removes two unused input modes, precedence rules, fallback branches, and ignored arguments. Keep `load_full_run_events(listing=…)`, which has an actual reuse caller.

### 3. Retention removal reporting — two lenses, distinct findings

**Lenses:** `review-agent-ux`, `review-simplicity`
**Convergence:** Both identify findings in removal-result reporting and bookkeeping. These are shared-area findings, not duplicate defects.

- **Warning — Retention deletion failures hide actionable diagnostics behind debug logging.** `[review-agent-ux, finding 2]`
  `src/pflow/runtime/trace_retention.py:150` reports:

  > “trace retention could not remove 1 trace(s); the next run retries”

  Persistent permission or filesystem failures do not resolve through retry alone. `_remove()` has the affected path and OS error, but logs them only at debug level.

  **Requested change:** Display a bounded sample of paths and causes, with instructions to correct permissions or filesystem availability.

- **Suggestion — Remove the unused protection tally.** `[review-simplicity, finding 1]`
  `SweepReport` at `src/pflow/runtime/trace_retention.py:61` exposes `protected`, but no production caller or test reads it. `_remove_in_waves` at `trace_retention.py:468` nevertheless maintains `kept`, distinguishes unreadable keeps solely for counting, and returns a third value that `run()` combines with another protection count.

  **Requested change:** Remove the report field and reporting-only bookkeeping while retaining the protection set controlling deletion. This deletes a counter, a reporting-only branch, a tuple element, and the reconciliation calculation.

## Critical

### Retention-looking keys inside `settings.env` bypass the guard

**Lens:** `review-silent-failures`, seam B, C1
**References:** `src/pflow/core/settings.py:179`; `src/pflow/runtime/trace_retention.py:100`; `.taskmaster/tasks/task_185/task-185.md:132`.

`pflow settings set-env PFLOW_TRACE_RETENTION_DAY 0` succeeds and stores the misspelled opt-out under `env`. Environment injection exports that spelling unchanged, retention checks only `PFLOW_TRACE_RETENTION_DAYS`, and `unknown_settings_keys()` skips `env` because it traverses only `BaseModel` sections. Retention consequently applies the default **14 days** and deletes eligible aged traces without a retention warning.

The spec requires a retention-looking key in the wrong place or spelling to disable retention with a warning.

**Requested change:** Check retention-related misspellings in the settings environment dictionary while preserving the valid override and unrelated environment keys.

## Warnings

### UI lookups translate read failures into absence or incorrect run status

**Lens:** `review-silent-failures`, seam A, W1
**References:** `src/pflow/ui/server.py:1586`; `src/pflow/ui/run_tailer.py:233`.

An I/O failure loading an exactly matched paused trace becomes `{}`, followed by HTTP 404: “Run … is not paused at a gate.” If retention removes the file between listing and reading, this branch also bypasses the corrected missing-run/aged-out response.

The shared UI resolver converts directory and metadata read faults into `None`, eventually producing `run-not-found` or missing-detail responses. History additionally caches failed metadata reads against unchanged mtime/size, allowing a transient failure to hide a trace after access recovers.

**Requested change:** Preserve missing, unreadable, and readable-but-not-paused outcomes through the UI boundary; do not cache transient failures as immutable absence.

### The post-consumption existence check bypasses unreadable-source refusal on Python 3.14

**Lens:** `review-silent-failures`, seam A, W2
**Reference:** `src/pflow/runtime/resume_source.py:987`.

`Path.exists()` can return `False` for stat permission/I/O failures on Python 3.14. After the initial source load, such a failure manufactures `FileNotFoundError` and reports that the trace “was removed,” suggesting a rerun. `_refuse_unreadable` cannot intercept the swallowed fault.

**Requested change:** Use an explicit stat/read preserving non-disappearance errors and map those errors to `ResumeSourceUnreadableError`.

### Unreadable consumption checks lack a retention-level regression test

**Lens:** `review-test-fidelity`, W1
**References:** `tests/test_runtime/test_trace_retention.py:606`; `src/pflow/runtime/trace_retention.py:397`.

The existing test faults an attempt’s **removal probe**. Its source is failed, so it never exercises the pending-pause rule’s `ResumeSourceUnreadableError` handler. Resume tests establish that the reader raises, but not how the sweep responds.

The lens identified this missed regression by inspection: changing the handler’s `consumer = None` to a non-`None` value could delete an aged pending pause when there is a dead zero-work attempt, a newer unrelated success, and a **one-shot** attempt-read fault; subsequent removal probes would succeed.

**Requested change:** Add a sweep-level case injecting at `open` during attempt loading/raw rereading. Assert that the pause and marker survive, the warning names the unreadable attempt, and an unrelated removable control disappears. The mutation was assessed by inspection, not executed.

### Hidden pauses cannot be identified or recovered from the message

**Lens:** `review-agent-ux`, finding 1
**Reference:** `src/pflow/cli/commands/resume.py:527`.

The message says:

> “1 paused run is not listed: its workflow file no longer exists.”

Neither text nor JSON identifies the hidden token or missing workflow path. The loader discards those details when incrementing the count, so an agent cannot determine which file to restore.

**Requested change:** Include the token, original workflow path, and recovery instruction, such as restoring the workflow at that path and retrying `pflow resume list`.

### The P5 fixture does not contain the promised 1,000 young failures

**Lens:** `review-spec-conformance`, W1
**References:** `.taskmaster/tasks/task_185/implementation/implementation-plan.md:744`; `.taskmaster/tasks/task_185/implementation/bench/build_bench.py:188`.

The plan requires one identity with **1,000 young failures**. The builder generates ages of **1 through 1,000 hours**. With a 14-day window, **664 are already older than the window**, and the 336-hour boundary can also age out by sweep time. The recorded second-sweep benchmark therefore exercises substantially less retained young history than claimed.

**Requested change:** Keep all 1,000 timestamps safely inside the window and refresh the affected benchmark evidence. The separate P3 cost test constructs its young-history scenario correctly; this finding concerns P5.

### The prefix-collision scenario omits required listing and protection checks

**Lens:** `review-spec-conformance`, W2
**References:** `.taskmaster/tasks/task_185/implementation/implementation-plan.md:491`; `tests/test_runtime/test_resume_source.py:1658`.

The plan requires two sources sharing eight ID characters, one consumed, with the other remaining **“listed, resumable and protected.”** The existing test checks supersession of one source and resumability of the other, but never calls `list_paused_runs` or retention. Retention fixtures deliberately generate distinct ID prefixes and do not supply the missing collision case.

**Requested change:** Add listing and protection assertions using existing workflow files and aged traces, ensuring another protection rule cannot independently explain survival. This is missing scenario coverage, not a claim that implementation currently fails.

### Completion coverage is incomplete

**Lens:** `review-feature-interactions`.

The requested runtime intersections were traced, but the protocol’s full-file reading requirement was not completed across all **94 changed files**. Remaining coverage includes portions of changed tests, documentation, task artifacts, and unchanged bodies of large modified modules. The lens states that this report cannot close the whole-diff completion gate.

## Suggestions

### Remove a direct Pydantic field-constraint test

**Lens:** `review-test-fidelity`
**Reference:** `tests/test_core/test_settings.py:628`.

The test asserts defaults and `ge=0`; retention and CLI tests already cover meaningful outcomes, including refusal to overwrite invalid settings. The lens recommends removing it.

### Remove a private-cache representation assertion

**Lens:** `review-test-fidelity`
**Reference:** `tests/test_cli/test_run_tailer.py:438`.

The private-cache `isinstance(..., tuple)` assertion fixes representation without proving concurrent-reader safety. Remove it while retaining surrounding cache reuse/invalidation checks.

### Make example run IDs agree

**Lens:** `review-agent-ux`
**References:** `docs/reference/cli/index.mdx:258` and `:290`.

In both JSON examples, the ID embedded in `trace_path` differs from `execution_id`, although the producer uses the same ID for both. Align them so agents learn the correct correlation rule.

### Share the duplicate absence helper

**Lens:** `review-simplicity`
**Original classification:** **Minor — take or leave**
**References:** `src/pflow/core/settings.py:153`; `src/pflow/core/trace_dir.py:435`.

The `_no_entry` implementations are identical apart from parameter types. Share the filesystem primitive in a neutral core module, removing a duplicate implementation of the missing-entry versus dangling-symlink distinction.

### Remove the unused strict lock mode

**Lens:** `review-simplicity`
**Original classification:** **Minor — take or leave**
**Reference:** `src/pflow/core/trace_dir.py:378`.

`is_trace_locked` has no production `strict=True` caller. Retention uses `read_trace_meta_and_lock_strict`, which probes through an already-open handle. Remove the standalone flag and exception arm, eliminating an unused public mode and second strict-open error contract.

## Verified clean

These are the lenses’ own assertions, retained independently of findings elsewhere.

### `review-silent-failures` — seam A

- Exact-ID matching and full lineage confirmation prevent prefix collisions from selecting another attempt.
- Marker creation precedes trailer publication; marker-write failure disables streaming before a durable pause is published.
- Prior consumption-reread fixes preserve typed unreadable refusals and treat disappearing attempts conservatively.
- Prior gate/report aged-out hints and resume-preflight suggestion propagation are present.
- Snapshot misses reuse one listing and preserve the legacy count.
- Deleted-workflow pauses are counted; empty Snapshots fail loudly.
- The pinned-trace disappearance fix emits `run-not-found`; the documented UI legacy-message exception was not re-reported.

### `review-silent-failures` — seam B

- Settings permission-error and dangling-symlink fixes stop pruning after failed loads and block ordinary saves.
- Pre-unlink marker/trailer read faults preserve traces and reach warning reporting.
- Newly appeared pause markers and trailers on previously unfinished traces prevent deletion, including before Windows retries.
- Unknown workflow-file states preserve groups and produce warnings.
- Source deletion failures preserve dependent Attempts.
- Strict readers distinguish missing files, unreadable/corrupt files, and unfinished writes.
- Permission-warning deduplication uses a shared lock.
- Finalization publishes pause markers before trailers; sweep failures remain visible warnings.
- No additional Protected-trace deletion path was established within scope. The stated Windows pre-unlink residual was not re-reported.

### `review-concurrency-safety`

- **Concurrent sweeps:** Classification state is invocation-local. Deletion waves at `trace_retention.py:469` remove sources before Attempts, preserve Attempts after failed source deletion, and tolerate repeated unlinks. Prefix counters conservatively retain Attempts when source-ID prefixes collide.
- **Resume racing retention:** Consumption checks at `resume_source.py:255` refuse vanished Attempts or unreadable evidence; the loader subsequently checks source existence and handles disappearance during raw rereads.
- **Live writers and Windows retries:** Held POSIX writer locks protect candidates. Pre-unlink revalidation at `trace_retention.py:495` checks newly published pause markers and previously unfinished trailers before both unlink attempts. Recheck faults preserve files and reach warning accounting.
- **Writer lifecycle:** Marker publication precedes the paused trailer; trailer writing closes the stream in `finally`; repeated finalization does not repeat writes or sweeps. Batch workers use separate buffer collectors.
- **Viewer caches and tailing:** Cache publication at `run_tailer.py:125` uses one lock and immutable listing tuples. Awaited reads serialize offsets; event-state mutation stays on the event loop. Cancelled tailers are replaced with separate instances. Missing pinned traces emit `run-not-found`.
- **Previous fixes:** Settings open/symlink handling, reported workflow-state/revalidation faults, and atomic permission-warning deduplication were verified. The lock at `settings.py:164` covers the full check-and-add; logging occurs after release, with no reverse acquisition found.
- No new scoped concurrency blocker was found. The off-checklist source-prefix collision/concurrent deletion scenario was blocked by conservative deletion ordering.

### `review-impact-completeness`

- Production lookup paths use `core.trace_dir`; no remaining production trace glob or duplicate `Path.home() / ".pflow" / "debug"` resolver was found.
- Report, Snapshot, resume, cache analysis, and Viewer discovery use filename start-time ordering. Remaining UI mtime uses invalidate caches.
- Deleted reader/lock twins have no executable references; callers use shared readers.
- Settings serialization handles `extra="allow"`: `show` recursively excludes extras and masks environment values; saves preserve extras; init/reset serialize fresh defaults.
- Task-159 autoload fixtures use the composer, with a positive counterpart proving the no-autoload fixture is discoverable.
- Viewer misses dropping legacy counts are an explicitly documented plan exception.
- No missed production consumer was identified in traced paths and repository-wide searches. Semantic ordering, negative-fixture meaning, and documentation accuracy received separate inspection beyond static checks.

### `review-feature-interactions`

Verified through code and test inspection, **not execution**:

- **Retention × Snapshots:** `.only` exclusion, success/degraded selection, and preservation are covered by `test_the_snapshot_survives_where_the_loader_finds_it`.
- **Retention × resume chains × approval denial:** Attempts outlive undeletable sources; denied attempts retain consumption evidence. Covered by `test_an_attempt_outlives_its_source` and `test_an_attempt_chain_unwinds_root_first`.
- **Marker failures × resume/UI:** Marker-before-trailer ordering and faults prevent non-durable pauses becoming answerable tokens. Covered by `TestTheTraceNameAndThePausedMarker`.
- **CLI × MCP × nested workflows:** Both entry points finalize through the shared collector; nested execution shares the parent collector or uses non-streaming buffers.
- **Viewer × `.only`:** Unpinned discovery excludes partial runs; explicit pinned discovery permits them. Node details share the pinned resolver.
- **Analyze-cache × filename filtering:** Workflow-content verification and caller-owned success/failure selection remain.
- **`--no-trace` × reports:** Report options re-enable tracing; disabled streaming leaves no retention sweep directory.
- **Version coexistence:** Old-writer consumption invisibility and settings-key loss are accepted in ADR-0018 and were not raised as new findings.
- No destructive feature-interaction defect was confirmed in inspected paths. The lens identifies the filename and `.paused` sidecar as the discovery index; retention must preserve selected traces and Attempts proving consumption.

### `review-test-fidelity`

- Read-set pins observe both `builtins.open` and `io.open`, assert exact file sets, and count directory enumerations.
- Ordering pins deliberately oppose start time to mtime and filename order; descending fixture IDs strengthen recency tests.
- Retention tables assert exact survivors, distinguish protection rules, and exercise downstream resume/Snapshot behavior.
- Pre-unlink race tests include removable controls. Inspection supports claimed mutation kills for dropped marker/trailer rechecks and skipped retry rechecks.
- Settings tests verify byte-preserving refusal, recovery, dangling-symlink handling, and unknown-key preservation.
- Task-159’s autoload twin establishes discoverability before testing suppression.
- No reviewed test was found to encode wrong behavior. Mutation claims were spot-checked against code and assertions, without execution.

### `review-agent-ux`

- Settings-save refusal names the file, explains the risk of overwriting it with defaults, and supplies repair/reset options through `UserFriendlyError`.
- Resume read failures retain the trace path and offer retry/permissions guidance.
- Analyze-cache legacy disclosures include the applicable `--from-trace` remedy and survive JSON rendering.
- The shared aged-out hint describes a possibility rather than asserting deletion.
- `--report` / `--report-dir` precedence over `--no-trace` matches execution code.
- No critical message preventing diagnosis was found.

### `review-simplicity`

- `scan_traces`, `_SCAN_CACHE`, and `_DIR_LIST_CACHE` remain live through overlay discovery and run history.
- Resume and retention share pause eligibility and consumption policy; `count_live=` expresses a necessary reservation-versus-consumption distinction.
- `unreadable=` represents two real policies: resume refuses an unreadable newer candidate; Snapshot/cache lookup skips it.
- `TraceEntry` fields feed actual lookup or retention rules, including unknown tags and sidecars. Current/legacy separation and orphan markers have concrete consumers.
- Shared fixture writers use the production filename composer; descending fixture IDs provide a meaningful ordering check.
- The integrated design was assessed as mostly cohesive, with remaining complexity concentrated in unused interface modes and reporting bookkeeping.

### `review-spec-conformance`

The lens used the task spec, implementation plan, progress log, and `show-before-code.md` rulings §9–§11. **“Met” means implementation or test presence confirmed by reading, not runtime verification.**

**Core requirement inventory:**

| Requirement and source | Lens’s retained verdict and evidence |
|---|---|
| At most one listing; only answer-related file reads — spec:104 | **Met.** `trace_dir.py:205`; `resume_source.py:951`; `workflow_trace.py:346`; `report.py:24`; `server.py:1569`; `test_run_lookup_reads.py:158`. |
| Lookup below one second on the owner’s machine — spec:106 | **Synthetic evidence recorded; real-directory verification pending.** Progress-log:844 records all five synthetic lookups below one second; subject to W1’s benchmark qualification. |
| Exact identity; no shadowing by another workflow/attempt — spec:108 | **Met.** `trace_dir.py:259`; `resume_source.py:349`; `test_resume_source.py:1625`. |
| Listing and resume consumption verdicts agree — spec:110 | **Met.** Shared `_find_consuming_attempt` at `resume_source.py:223`, called by loader and listing. |
| Gate lookup without unscoped scan — spec:112 | **Met.** `server.py:1569`; one-file read assertion at `test_ui_interaction_server.py:1238`. |
| Default 14 days, zero disables, environment override — spec:116 | **Met.** `settings.py:69`; `trace_retention.py:74,154`. |
| Retention on trace completion; no new subcommand — spec:117 | **Met.** `workflow_trace.py:1162`; no new command registration. |
| Answerable paused runs protected — spec:119 | **Met.** `_apply_pending_pause_rule`; shared predicate at `resume_source.py:1154`. |
| Newest Success/Degraded full run protected — spec:120 | **Met.** `_protect_snapshot`; agreement test at `test_trace_retention.py:359`. |
| Newest run protected regardless of status — spec:121 | **Met.** `_apply_newest_run_rule`; protected-set fixture at `test_trace_retention.py:247`. |
| Workflow-file existence qualifier; inline identities excluded — spec:122 | **Met; amendment recorded and accepted.** `_file_state`; `trace_dir.py:418`; progress-log:228. |
| Attempt survives until resumed Run is gone — spec:124 | **Met.** `_remove_in_waves`, `_source_present`; tests at `test_trace_retention.py:456,479`. |
| Open writer protected by advisory lock — spec:125 | **Met with recorded Windows limitation.** `trace_dir.py:292,400`; removal-candidate lock check; `test_trace_retention.py:676`. |
| No-op with policy off or bound not reached — spec:126 | **Met.** `trace_retention.py:121,154,166`; `test_trace_retention.py:392`. |
| No retention on read-only commands — spec:126 | **Met.** Writer-only hook; CLI/Viewer tests at `test_trace_retention.py:1127,1144`. |
| Removed traces produce “no such run,” not crashes — spec:127 | **Met in reviewed paths.** Trace-first deletion, orphan-marker handling, missing-source refusal, pinned disappearance test at `test_run_tailer.py:723`. |
| Old filenames invisible to discovery — spec:128 | **Met.** Current-only listing; `test_pre_185_traces_are_not_searched.py`; gate tests. |
| Old traces readable by explicit path — spec:129 | **Met.** Explicit `report_cmd` path bypasses discovery; `load_trace_file` unchanged. |
| Legacy traces not protected and age out — spec:129 | **Met subject to unknown-sidecar protection ruling.** Legacy age-only branch; zero-read assertion at `test_trace_retention.py:340`. |
| Misses disclose unsearched old-grammar counts — spec:130 | **Met on implemented surfaces; recorded UI deferral.** `legacy_note`, CLI/analysis/gate handlers; pinned-banner/run-inputs exception at progress-log:398. |
| Hidden pauses counted when workflow file is gone — spec:130 | **Met.** `PausedRunListing`; `resume.py:521`; `test_resume_list_cli.py:250`. |
| Unknown tags/sidecars never removed — spec:131 | **Met.** `_unknown_facts`; `test_trace_retention.py:688`. |
| Failed settings loads not overwritten — spec:132 | **Met; deliberate reset/init recovery retained.** `SettingsManager.save`; failed-load, permission, and dangling-link tests. |
| Misplaced/misspelled retention keys disable retention with warning — spec:132 | **Met; scope widening recorded.** `unknown_settings_keys`; `retention_days`; parametrized tests at `test_trace_retention.py:923`. |
| One debug-directory resolver — spec:136 | **Met.** Sole production spelling at `trace_dir.py:112`; consumers use resolver. |
| One recency rule — spec:136 | **Met.** Filename start-time ordering; inverted-mtime tests at `test_cli.py:360` and `test_run_tailer.py:178`. |
| Flag precedence in help and guide — spec:138 | **Met.** `run.py:1040`; `guide/entry.md:28`; guide rendering recorded in log. |
| Policy/deletion docs and corrected filename examples — spec:141 | **Met.** Both named docs, CLI reference, and `report.py` changed. |
| Three path spellings and empty-path hash — spec:146 | **Met in shared runtime lookup.** `trace_dir.py:115,120`; `test_trace_dir.py:75,152`. |
| Correct MCP persistence claims — spec:149 | **Met.** Collector comments, execution-tool docstring, and ADR-0010 amended. |
| Trace format, report rendering, analysis full loads remain out of scope — Design Decisions | **Met.** No `trace_io`, format-version, or report-renderer changes; analysis keeps its full-load policy. |
| Engine contact explicitly stated — spec:156 | **Met.** Plan states no engine changes; branch diff confirms none. |

**Phase deliverables and verification inventory:**

- **P0:** CP-1 rulings met through rulings §9–§11 and progress-log:228.
- **P1:** Composer/parser, shared readers, writer, runtime/CLI consumers, and fixture conversions present; old helpers removed. Grammar round-trip and pre-185 reader compatibility covered at `test_trace_dir.py:62–152`.
- **P1:** Public read-set pins observe both open functions and `scandir` in `test_run_lookup_reads.py`. Marker failure, trailer failure, `.only`, and `.from-` cases present at `test_run_outcome_cli.py:803`.
- **P1:** Cutover misses, paired presence/absence, and JSON stderr covered in `test_pre_185_traces_are_not_searched.py` and gate tests. Consumed, deleted-workflow, vanished-source, and vanished-Attempt cases present in resume loader/CLI tests.
- **P1:** Prefix-collision listing/resumability/protection obligation is **partial — W2**. Recency, untagged `--only`, newest-complete report, and incomplete-only report cases are present in `test_only_snapshot.py`, `test_cli.py`, and `test_run_tailer.py`.
- **P2:** Pinned exact/scoped resolution, automatic `.only` exclusion, cache isolation, and immutable cache assertions present in `test_run_tailer.py`, using shared `find_workflow_trace`. Gate lookup among 500 traces opens one file at `test_ui_interaction_server.py:1238`.
- **P2:** Isolated-HOME callout, screenshot, and timings recorded at progress-log:337; owner-directory repeat pending.
- **P3:** Every protected kind, collisions both ways, empty newest file, and zero-read legacy cases present at `test_trace_retention.py:247`. Failed source deletion preserves Attempts and chains unwind at `:456,479`.
- **P3:** Fail-closed reads, unrelated removal controls, and unknown workflow state tests present at `test_trace_retention.py:513–676`; unknown facts, Snapshot agreement, and no over-protection at `:359,407,688`.
- **P3:** Second-sweep cost, 2,000 identities, and 1,000 young failures test present at `test_trace_retention.py:804`, with permitted newest-young identity read deviation recorded at progress-log:538.
- **P3:** Real finalization, stream fault, full disk, read-only commands, and sweep exception tests present at `test_trace_retention.py:1041–1158`. Windows retry and deterministic lifecycle interleavings present at `:713,760,778,1219–1294`; native Windows gate pending.
- **P3:** Defaults, invalid environment/file settings, typos, preservation, save refusal, and environment non-persistence covered by retention/settings/CLI settings tests.
- **P4:** Docs, guide, MCP, instruction files, ADR amendments, and baseline fixture updates present. Documentation concentration explained at progress-log:705.
- **P5:** Required 30k fixture’s 1,000-young-failure component is **partial — W1**. Timings and survival of all **505 designated protected paths** recorded at progress-log:844.
- **No unrequested production behavior identified.** Settings-key preservation across sections, permission-warning deduplication, unreadable-source refusals, and pinned disappearance handling have recorded reasons. Recorded departures were treated as decisions rather than re-raised findings.
- No absent or contradicted core requirement was confirmed in the reviewed production changes.

## Coverage

### Lenses that ran

| Lens | Provider | Review delivered |
|---|---|---|
| `review-silent-failures` | codex | Separate seam A and seam B reports |
| `review-concurrency-safety` | codex | Completion-gate review |
| `review-impact-completeness` | codex | Consumer/consolidation review |
| `review-feature-interactions` | codex | Runtime-intersection review |
| `review-test-fidelity` | codex | Test review |
| `review-agent-ux` | codex | Messages and documentation review |
| `review-simplicity` | codex | Integrated-design review |
| `review-spec-conformance` | codex | Requirement and plan inventory |

**Failed-lens gaps:** None supplied (`[]`). Eight distinct lenses delivered nine reports.

### Explicit coverage limitations

- **All reports were read-only/static reviews.** No lens ran tests or wrote files. Test inspection and recorded execution evidence are not execution by these reviewers.
- **Silent failures, seam A:** Retention/settings implementation and unrelated portions of large UI/collector modules were outside scope.
- **Silent failures, seam B:** Source-only verification; no additional Protected-trace deletion path established within scope. The stated Windows pre-unlink residual was not re-reported.
- **Concurrency safety:** Native Windows behavior remains unexecuted. Documented limitations for unavailable writer locks and simultaneous resumes remain unchanged.
- **Impact completeness:** Did not finish full-file reading for every changed test and task artifact; explicitly not a complete whole-diff completion-gate sign-off.
- **Feature interactions:** Did not finish full-file reading across all 94 changed files; gaps include tests, documentation, task artifacts, and unchanged bodies of large modified modules. Completion gate remains open.
- **Test fidelity:** Scoped diffs and relevant production paths were read, but unchanged bodies in every large modified test file were not exhaustively reread. Tests and mutations were not executed; no unqualified full-file sign-off.
- **Spec conformance:** Reviewed substantive branch diff, governing documents, new lookup/retention modules, new tests, and relevant existing code, but not every unchanged portion of large changed server, exception, CLI, cache-analysis, and test modules. This falls short of the full-file-read protocol and prevents exhaustive completion-gate clearance.

### Pending obligations recorded by the lenses

These were explicitly classified as **pending obligations, not findings**:

- Real-directory P5 run and owner-directory verification.
- `make test-all-local`.
- Final Task-159 run.
- `tests-windows` / native Windows gate.
- Completion falsifier after the reading lenses, as caller-owned execution under plan §3.

The execution obligations were deferred by the caller, with sequencing recorded in the progress log.
