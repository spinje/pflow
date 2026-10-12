# Merged Review Report

## Convergent findings

### 1. Migration can hide and delete an already-issued pending pause

**Severity and attribution:** Critical — `review-plan`, `review-architecture-fit`, `review-concurrency-safety`, `review-feature-interactions`, `review-silent-failures`. Suggestion-level handoff — `review-impact-completeness`.

**Convergence:** All six lenses identify the rename-before-marker publication defect.

[implementation-plan.md:175](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:175) specifies renaming a legacy trace before creating its `.paused` marker, suppressing per-file `OSError`. Protection at [implementation-plan.md:184](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:184) depends on that marker.

An expired, unanswered legacy pause can be renamed successfully and then lose protection if marker creation fails, the process exits, or another sweep observes the interval before publication. The new-format filename prevents subsequent migration passes from repairing it. `resume list` omits the pause, and pruning can delete its trace without a diagnostic. An exhausted-inode failure is one concrete marker-write failure identified.

Current paused status comes from the trailer independently of filenames ([resume_source.py:1145](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/resume_source.py:1145)). The architecture lens connects this to Task 171’s contract: “Pause is a promise. Every `paused` stamp must yield a token the resume path accepts” ([task-review.md:39](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_171/task-review.md:39)). Atomic `os.replace` does not make trace-plus-marker publication atomic.

**Requested corrections:** Define recoverable publication coordinated with pruning and orphan-marker cleanup; leave either a discoverable legacy pause or a fully published new pause. Uncertainty must prevent deletion. Specify interprocess coordination and recovery before pruning, record the invariant in the ADR, and test failure, termination, and concurrent observation between rename and marker creation.

**Related, distinct publication gap:** `review-concurrency-safety` and `review-feature-interactions` also identify the normal finalization path at [implementation-plan.md:128](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:128): trailer publication precedes marker publication, and the writer lock is released before the marker is published. The concurrency lens requests keeping marker publication within the protected writer lifetime. Both raised this within their Critical publication findings.

### 2. Removing consumption evidence can make an answered token answerable again

**Severity and attribution:** Critical — `review-plan`, `review-architecture-fit`, `review-concurrency-safety`, `review-silent-failures`, `review-impact-completeness`.

**Convergence:** Five lenses independently identify the source-to-consuming-attempt dependency.

The pruning policy independently removes expired consumed pauses and consuming attempts, continuing after individual failures ([implementation-plan.md:179–194](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:179), particularly [183](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:183) and [191](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:191)).

Two failure modes were reported:

- **Persistent resurrection:** Source P cannot be deleted—for example, because of a Windows sharing violation—but its denied or failed consuming attempt A is deleted. P then has no surviving consumption evidence, reappears as pending, and can accept another answer. An approved attempt that executed work and subsequently failed can leave already-executed effects vulnerable to repetition.
- **Concurrent-reader resurrection:** A reader loads P; a sweep deletes A; the reader checks consumption, skips the now-unreadable A, and accepts P. Even successful deletion of both files can expose this interval. A directory listing containing A’s filename does not preserve its evidence.

The current loader selects the source before checking consumption ([resume_source.py:908](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/resume_source.py:908), [928–929](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/resume_source.py:928)). `_find_consuming_attempt` returns `None` without readable child evidence ([resume_source.py:265](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/resume_source.py:265)); denial consumes through its recorded verdict ([resume_source.py:226](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/resume_source.py:226)).

Task 171 explicitly guards against a chain forking and “double-firing side effects” ([task-review.md:44](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_171/task-review.md:44)). Attempt self-containment under ADR-0010 does not remove this supersession dependency. The checkpoint’s “Nothing reads the source of an Attempt” rationale does not address the reverse dependency: source eligibility reads the consuming attempt ([show-before-code.md:149](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/show-before-code.md:149)).

**Requested corrections:** Preserve consumption evidence while its source remains addressable. Define dependency-aware deletion, partial-failure recovery, and reader coordination, or durable consumption state with a defined lifetime. An interprocess lock covering resume validation and compound deletion was offered as one possible mechanism. Test source-unlink failure, successful attempt deletion, and readers interleaved with cleanup; `missing_ok`, exception suppression, and two successful sweeps do not establish the invariant.

### 3. A live zero-work attempt can authorize deletion of its still-needed source

**Severity and attribution:** Critical — `review-concurrency-safety`, `review-feature-interactions`, `review-impact-completeness`.

**Convergence:** Three lenses identify the distinction between temporary resume exclusion and durable consumption.

[implementation-plan.md:184](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:184) protects a pause only when `_find_consuming_attempt` returns `None`. That function treats a held writer lock as temporary supersession even before a verdict, started step, or completed work exists ([resume_source.py:252](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/resume_source.py:252), [268](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/resume_source.py:268)).

An expired pending source P can therefore be deleted after attempt A merely opens its trace and holds its lock. If A then dies without consuming work, the existing policy treats A as non-consuming, but P is already gone. `test_dead_zero_work_attempt_does_not_wedge_workflow_resume` establishes the recovery behavior that the proposed retention tests do not exercise.

**Requested corrections:** Distinguish live reservation from durable consumption, using the existing work predicate through a richer shared verdict. Protect the source while the attempt could still exit without consuming it. Test the exact start–sweep–zero-work-crash sequence.

### 4. Migration renames active legacy writers without honoring their locks

**Severity and attribution:** Critical — `review-plan`, `review-concurrency-safety`. Warning-level handoff — `review-architecture-fit`. Warning finding, bundled with retained-path consumers — `review-impact-completeness`. Cross-lens handoffs without a separate severity — `review-feature-interactions`, `review-silent-failures`.

**Convergence:** All six lenses identify this migration/liveness defect or hand it off explicitly.

Migration covers every legacy entry at [implementation-plan.md:172](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:172) and [175](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:175); writer-lock protection appears only later in pruning.

On POSIX, an older agent can keep writing an open legacy trace after `os.replace` moves it. The collector retains its obsolete `_stream_path` ([workflow_trace.py:996](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/workflow_trace.py:996)) and eventually returns a nonexistent path. If the writer later pauses, migration has already observed an incomplete trailer and creates no marker, leaving that pause absent from discovery and protection. Windows rename failure does not establish POSIX safety.

**Requested corrections:** Exclude active writers from migration. Hold the shared advisory lock across inspection and rename rather than probing and releasing it; define conservative behavior for unknown liveness or unavailable locking. Test an old-version writer spanning the upgrade.

### 5. Migration strands already-resolved pinned tailers

**Severity and attribution:** Critical — `review-plan`, bundled with active-writer migration. Warnings — `review-concurrency-safety`, `review-impact-completeness`. Warning-level handoff — `review-architecture-fit`. Cross-lens handoffs without a separate severity — `review-feature-interactions`, `review-silent-failures`.

**Convergence:** All six lenses identify or hand off the retained pinned-path failure. This is distinct from active-writer exclusion.

The plan updates initial pinned lookup ([implementation-plan.md:154](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:154)) but not the ongoing tailer lifecycle. A tailer resolves once and retains the path ([run_tailer.py:424](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/ui/run_tailer.py:424), [444](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/ui/run_tailer.py:444)). After migration renames that file, repeated opens fail and `_read_bytes` silently returns empty bytes indefinitely ([run_tailer.py:564](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/ui/run_tailer.py:564)).

Windows does not protect the intervals between these short-lived opens. The checkpoint itself cites this lifecycle problem when rejecting finalize-time renames ([show-before-code.md:138](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/show-before-code.md:138)).

**Requested corrections:** Define safe retained-path handling; on disappearance, re-resolve the same execution ID while preserving coherent replay state, and explicitly report removal if the run no longer exists. Test migration during pinned replay.

### 6. UI direct lookups omit legacy fallback

**Severity and attribution:** Critical — `review-plan`. Warnings — `review-feature-interactions`, `review-impact-completeness`. Warning-level handoff — `review-architecture-fit`. Cross-lens handoff without a separate severity — `review-silent-failures`.

**Convergence:** Five lenses identify the same compatibility omission.

[implementation-plan.md:154–156](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:154) routes pinned overlays/replay, node and input details, and `/api/gate` through filename-ID lookup. Legacy entries have `execution_id=None`; only CLI resume explicitly receives metadata fallback.

Before the first write triggers migration—or when migration skips a file—history remains discoverable through `scan_traces`, but selecting the run cannot resolve its pinned trace and opening its gate returns 404. Current lookups match metadata IDs ([server.py:1566](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/ui/server.py:1566), [run_node.py:98](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/ui/run_node.py:98), [103](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/ui/run_node.py:103), [run_tailer.py:513](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/ui/run_tailer.py:513)).

Migration intentionally does not run on UI startup, contradicting the checkpoint’s “every lookup still finds pre-upgrade traces” promise ([show-before-code.md:120](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/show-before-code.md:120)).

**Requested corrections:** Share exact-ID resolution with legacy fallback across CLI and UI, preserving caller-specific `--only` policies. Test startup, gate retrieval, pinned replay, node details, and run inputs before write-triggered migration.

### 7. A readable success trailer does not establish snapshot or report usability

**Severity and attribution:** Warnings — `review-plan`, `review-feature-interactions`, `review-impact-completeness`.

**Convergence:** Three lenses identify the snapshot eligibility mismatch; `review-plan` and `review-feature-interactions` also identify the corresponding report fallback regression.

The plan uses trailer presence for report selection ([implementation-plan.md:151](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:151)) and hash/tag/trailer status for snapshot protection ([implementation-plan.md:186](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:186)).

Current report selection fully validates the trace ([report.py:18](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/cli/commands/report.py:18)). Snapshot selection additionally requires readable content, matching workflow identity, supported format, and nonempty events ([workflow_trace.py:174–175](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/workflow_trace.py:174), [302](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/workflow_trace.py:302)).

With an older valid trace and a newer trace containing a malformed middle record but an intact success trailer:

- Retention can protect the unreadable newer trace and delete the usable snapshot to which `--only` currently falls back.
- Report selection can stop at the newer invalid trace and lose its existing fallback.

**Requested corrections:** Use tail reads to shortlist candidates, then apply each consumer’s actual eligibility rules before selecting a candidate or discarding alternatives. Add corrupt-newest/valid-older tests for snapshot retention and report selection.

### 8. Snapshot protection groups by hash instead of verified workflow identity

**Severity and attribution:** Warnings — `review-silent-failures`, `review-impact-completeness`.

**Convergence:** Two lenses explicitly identify the hash-collision defect at the same retention selection site. It is distinct from corrupt-body eligibility, although both affect [implementation-plan.md:186](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:186).

Protecting one success/degraded trace per eight-character `workflow_hash` can let a newer success for one workflow displace the only snapshot of another workflow with the same hash. The later `--only` invocation fails after silent deletion. Current lookup verifies the stored workflow path after hash filtering ([workflow_trace.py:181](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/workflow_trace.py:181)).

**Requested correction:** Use the hash only to narrow candidates, then protect representatives by verified workflow identity, preserving the reader’s collision guard.

### 9. Invalid unrelated settings can silently re-enable destructive retention

**Severity and attribution:** Warnings — `review-plan`, `review-silent-failures`. Warning-level handoff — `review-architecture-fit`. Cross-lens handoff without a separate severity — `review-feature-interactions`.

**Convergence:** Four lenses identify the newly destructive consequence of whole-file settings fallback.

The plan defers the existing fallback-to-defaults behavior ([implementation-plan.md:201](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:201)). Settings loading returns all defaults when any setting fails validation ([settings.py:154](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/core/settings.py:154)).

A valid `trace_retention_days: 0` combined with an invalid unrelated setting can therefore activate seven-day deletion. The fallback predates this task; irreversible deletion through that fallback does not.

**Requested corrections:** Address settings-load failure before enabling destructive housekeeping; skip deletion when loading failed and provide a visible diagnostic. Test disabled retention combined with an unrelated invalid setting. Merely forbidding unknown keys does not solve fallback to deletion-enabled defaults.

### 10. Q3 does not resolve resume dependencies or establish an accepted spec amendment

**Original classification and attribution:** Suggestion-level architecture/spec handoff — `review-concurrency-safety`. Unrated decision/status concern — `review-feature-interactions`. Related open decision — `review-architecture-fit`.

**Convergence:** These lenses identify the same Q3 decision area while preserving distinct concerns.

`review-concurrency-safety` states that CP-1 Q3 remains a proposal and the supplied spec still requires chain protection. `review-feature-interactions` likewise states that the checked-in spec protects the newest attempt and its source. Both distinguish self-contained restored event data from the consumption-evidence and temporary-live-attempt dependencies described above.

Separately, `review-architecture-fit` requests correcting the claim that nothing reads an Attempt’s source: the Viewer’s source-run jump does ([RunSelector.tsx:133](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/web/src/components/RunSelector.tsx:133)). Missing sources already degrade to plain text, so loss of history navigation can be explicitly accepted; it must be distinguished from supersession correctness.

`review-plan` separately verified that Q3’s deviation is disclosed and gated on CP-1; that assertion is retained below.

## Critical

All remaining Critical findings are represented in the convergent entries above, with each lens’s original severity retained.

## Warnings

### Resume reopens a migrated path without catching `OSError`

**Lens:** `review-impact-completeness`.

This is an additional retained-path consumer beyond pinned tailers. Resume loads a trace and subsequently reopens its path to reconstruct gate resolution. `_iter_raw_trace_lines` does **not** catch `OSError` ([resume_source.py:144](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/resume_source.py:144)), contrary to the blanket claim at [implementation-plan.md:455](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:455).

Migration at [implementation-plan.md:175](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:175) can occur between those separate reads.

**Requested correction:** Define stable reads or safe re-resolution across migration, and exercise migration between resume’s separate reads.

### Public lookups can still enumerate the directory multiple times

**Lens:** `review-plan`.

[implementation-plan.md:146–149](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:146) says both `load_resume_source` and the by-ID selector list; only consumption checking receives the outer listing. The unchanged by-workflow selector invokes the iterator’s listing as well. Existing selection and consumption calls are separate ([resume_source.py:908](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/resume_source.py:908), [929](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/resume_source.py:929)).

Analyze-cache’s no-match path likewise adds another `list_traces` after candidate collection. Helper-level open-count tests would miss these public-call-graph costs.

**Requested correction:** Pass one listing through selection, consumption, and no-match disclosure. Count directory enumerations through public lookup functions, including by-workflow and missing-ID cases.

### Persistent cleanup failures are deliberately invisible

**Lens:** `review-silent-failures`.

The sweep promises “NEVER raises (suppress + logger.debug)” ([implementation-plan.md:167](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:167)). Persistent permission failures are swallowed alongside harmless concurrent disappearance ([implementation-plan.md:179–182](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:179)).

Old files can accumulate while runs succeed, without a visible indication that retention is ineffective. `SweepReport` has no skipped/failed counts. The cited writer precedent instead logs a warning in `_disable_streaming` ([workflow_trace.py:1126](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/workflow_trace.py:1126)).

**Requested correction:** Keep housekeeping non-fatal while distinguishing expected disappearance from persistent failure, counting skipped operations, and emitting a concise actionable warning.

### A misspelled retention opt-out silently enables deletion

**Lens:** `review-silent-failures`.

The new field at [implementation-plan.md:198](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:198) enters `RuntimeSettings`, which inherits Pydantic’s unknown-key ignoring behavior ([settings.py:48](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/core/settings.py:48)).

With `{"runtime":{"trace_retention_day":0}}`, the intended opt-out is discarded and the seven-day default deletes traces.

**Requested correction:** Explicitly address unknown retention configuration before enabling destructive sweeping. Adding `extra="forbid"` alone is insufficient while validation errors still fall back to deletion-enabled defaults. The related whole-file fallback defect is recorded separately under convergence.

## Suggestions

### Record publication, recovery, and consumption-evidence lifetimes

**Lenses:** `review-plan` and `review-silent-failures` — Suggestions; also requested within `review-architecture-fit`’s Critical publication finding.

Record these invariants in the proposed ADR alongside the filename grammar. They determine whether marker-based discovery and protected-set retention remain sound under concurrent agents. The requested invariants are recoverable trace/marker publication and preservation of consumption evidence while its source remains addressable.

### Use deterministic lifecycle fault tests

**Lenses:** `review-concurrency-safety`, `review-silent-failures` — Suggestions; corresponding failure tests also requested by the owning findings.

Replace or supplement “two sweeps finish without error” with deterministic barriers at:

- Rename versus marker publication.
- Source loading versus consumption checking.
- Source deletion versus consuming-attempt deletion.

Include a live zero-work attempt that exits, simulated Windows failure deleting the source, interrupted migration, and readers interleaved with cleanup. Successful concurrent sweeps alone do not exercise these failure states.

### Preserve both filename generations in shared lookup-contract tests

**Lens:** `review-impact-completeness`.

Add a matrix covering CLI resume, UI gate, pinned replay, node details, and run inputs against both filename generations. Converting every fixture to the new grammar would conceal the missed legacy consumers.

### Explicitly decide the cost of invalidating emitted legacy paths

**Lens:** `review-architecture-fit` — Open decision; no severity assigned.

Checkpoint Q4 prices migration’s stall ([show-before-code.md:155](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/show-before-code.md:155)). Renaming also invalidates previously emitted `trace_path` values, including protected traces. Current report handling rejects those paths outright ([report.py:76](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/cli/commands/report.py:76)).

Explicitly accept that cutover or specify compatibility behavior. This is distinct from a running tailer retaining a path.

### Record Task 121’s future recording-lifetime dependency

**Lens:** `review-architecture-fit` — Open decision; no severity assigned.

Task 121 proposes record/replay of `agent` nodes from the trace and identifies a separate snapshot store as duplicate machinery ([task-121.md:25](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_121/task-121.md:25)). A selected recording can age out once a newer successful run replaces its protection.

Because that spec requires rewriting, record how Task 121 will establish durable recordings later; do not introduce an unused pinning interface now.

### Durable-contract inventory

**Lens:** `review-architecture-fit` — Architectural classification, retained without regrading.

| Decision | Contract / inheriting consumers | Original tier and verdict |
|---|---|---|
| Filename identity and legacy renaming | Persisted artifacts and agent-facing paths; Tasks 173/184, report, pinned replay | T4; old-path invalidation remains an open decision |
| `.paused` presence controls discovery and protection | Resume-token persistence; Tasks 171/176 and issued approval tokens | T4; publication is not recoverable |
| Age retention, protected set, persisted settings | Artifact lifetime/settings; resume supersession, `--only`, pending Task 121 | T4 policy / T3 key; consumption evidence can disappear |

## Verified clean

These are the lenses’ reported read-only assertions, condensed without additional verification.

### `review-plan`

- The eight inline debug-directory locations and production filename/glob consumers identified by the plan are present.
- `only_node` is stamped before streaming starts; this change can remain outside the engine.
- MCP workflow execution persists traces through the shared runner.
- Runtime/UI dependency direction permits consolidation.
- Timestamp ordering fixes the documented display-name sorting problem.
- Q3’s spec deviation is explicitly disclosed and gated on CP-1, rather than being an unrecorded scope change.
- Tests accompany implementation phases; real-surface, baseline, and Windows verification are planned.

### `review-architecture-fit`

- The shared listing module passes the deletion test: removing it would redistribute filename, directory, and ordering knowledge across consumers.
- Exact lineage verification after eight-character filtering preserves the resume-policy seam.
- Unchanged JSONL payloads preserve trace-reader and raw-overlay interfaces.
- The retention key and environment override fit existing settings machinery; no inspected pending task requires a different naming shape.
- The planned ADR and coordinated documentation/fixture migration recognize the durable contracts involved.
- The full task-board inspection completed successfully.

### `review-concurrency-safety`

- Existing owner-thread assertions and worker-buffer routing keep streamed writes on the owning thread; the plan introduces no engine or batch-sharing change.
- UI caches use `_SCAN_CACHE_LOCK`; frozen `TraceEntry` values introduce no mutable per-entry state, and existing cache lock sections do not span filesystem I/O.
- `.only` filtering plus the content-level legacy guard preserves snapshot isolation.
- Exact `resumed_from` verification after prefix filtering prevents collisions from establishing consumption.
- Searches corroborated the eight debug-directory resolver sites and enumerated production filename/glob consumers; no additional production discovery loop surfaced.

### `review-feature-interactions`

- `--only` is stamped before streaming; runtime exclusion and explicit UI-pin allowance remain distinct in the plan.
- Attempts re-record restored nested/loop/branch events and remain self-contained under ADR-0010; filename changes need no engine or trace-format change.
- CLI and MCP share the run-scoped collector, and MCP finalizes through `WorkflowRunner`; the proposed retention hook reaches both.
- `load_trace_file` already rejects legacy single-object content; legacy filename compatibility does not require restoring that reader.
- Searches found the eight debug-directory spellings and enumerated production filename/glob consumers, with no additional production discovery consumer.
- The plan preserves the runtime iterator’s three hash spellings.
- No additional optional feature-parity changes were proposed; legacy UI fallback was classified as required behavior.

### `review-silent-failures`

- The eight inline debug-directory locations and principal production filename/glob consumers match the inventory.
- `_iter_workflow_traces` retains workflow-path verification, format checks, legacy `only_node` exclusion, and consumer-owned status selection.
- `.from-` filtering is followed by exact `resumed_from` verification.
- The shared trailer reader retains its oversized-trailer fallback.
- `/api/gate` retains full loading for interned payloads.
- Ordinary-finalization marker-write failure explicitly clears durable trace identity and has a planned non-durable-pause assertion.

### `review-impact-completeness`

- All eight production debug-directory spellings and current production glob sites are mapped.
- Analyze-cache’s separate ordering and disclosure comparisons are covered.
- CLI/MCP finalization, UI listing caches, and caller-specific `--only` behavior are covered.
- Shared metadata/trailer/lock helpers preserve runtime/UI dependency direction.
- Settings, environment override, fixture builders, relevant guides, and filename documentation are covered.
- Principal cited code locations match checkout `50f62327`.

## Coverage

| Lens | Provider | Review produced | Reported overall assessment |
|---|---|---|---|
| `review-plan` | codex | Yes | Not ready for implementation; publication, consumption-preserving deletion, and legacy UI compatibility need correction before P1–P3 |
| `review-architecture-fit` | codex | Yes | Lookup seam fits the codebase; persistence policy needs revision before implementation |
| `review-concurrency-safety` | codex | Yes | Not yet concurrency-safe for concurrent agents; coordination and recovery rules are missing |
| `review-feature-interactions` | codex | Yes | Lookup consolidation is sound; plan is not ready to implement unchanged |
| `review-silent-failures` | codex | Yes | Consolidation direction is sound; migration and retention lifecycle guarantees need revision |
| `review-impact-completeness` | codex | Yes | Discovery-site map is substantially complete; lifecycle consumer map is incomplete |

**Failed or missing lenses:** None. The supplied coverage-gap list is empty.

**Reported review limits:**

- All six reviews were read-only against `50f62327`; no tests were run, no files were changed, and `uv.lock` was excluded.
- `review-plan` checked core production paths and cited regression pins, but did not independently audit every ancillary documentation/fixture reference or external issue claim.
- `review-architecture-fit` states that its handoffs do not substitute for other lenses’ complete checks.
- `review-concurrency-safety` limited roadmap assessment to supplied artifacts and relevant ADR context.
- `review-feature-interactions` ran neither tests nor benchmarks.
- `review-silent-failures` leaves performance, Windows behavior, and exhaustive roadmap compatibility unverified by execution.
- `review-impact-completeness` leaves performance measurements and broader roadmap suitability unverified. Its static checks and the proposed happy-path fixture conversions do not establish legacy lookup parity, retained-path behavior, or preservation of consumption evidence.
