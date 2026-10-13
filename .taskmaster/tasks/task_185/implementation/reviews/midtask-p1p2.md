# Merged Review Report

## Convergent findings

### 1. Consumption rereads bypass typed unreadable-source handling, and tests cover only the initial load

**Convergence:** `review-feature-interactions` and `review-test-fidelity` independently identify the same defect at [resume_source.py:268](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/resume_source.py:268).

**Stated severities:** **Warning** — `review-feature-interactions`; **Critical — false confidence in consumption fault handling** — `review-test-fidelity`.

A zero-work or restored-only attempt reaches `_attempt_consumed_work`, which rereads the raw file to inspect dangling starts and gate verdicts. This read catches only `FileNotFoundError`. If the initial load succeeds but the later read raises `PermissionError` or another non-disappearance `OSError`, the error escapes instead of becoming `ResumeSourceUnreadableError`. `/api/resume` catches only `PflowError`, producing HTTP 500 instead of the intended retryable `source_unreadable` refusal.

The unreadable-attempt test at [test_resume_source.py:1718](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/tests/test_runtime/test_resume_source.py:1718) patches `load_trace_file`, proving only the first read’s handling. The existing disappearance test likewise deletes before the initial load, leaving the subsequent read boundary unprotected.

**Requested remediation and coverage:** Apply the three-outcome handling across the complete consumption read. Let the initial load succeed, then fault the raw read and assert the typed retryable refusal, preferably through `/api/resume` with no child spawned. Pair this with disappearance during the raw read and assert superseded.

### 2. Gate and explicit-report misses omit the required aged-out explanation; miss tests do not protect it

**Convergence:** All three lenses identify the missing `/api/gate` aged-out hint. `review-silent-failures` and `review-test-fidelity` also identify the explicit-report omission.

**Stated severity:** **Warning** — all three lenses.

At [server.py:1577](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/ui/server.py:1577), an unknown run returns “No run … was found” plus any legacy count. `review-feature-interactions` references the same gate miss area at [server.py:1574](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/ui/server.py:1574). At [report.py:91](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/cli/commands/report.py:91), a missing explicit path returns only “Trace file not found.”

For a previously issued token or saved trace path whose file has disappeared, neither surface explains retention as a possible cause. [Plan §1.4:223](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/.taskmaster/tasks/task_185/implementation/implementation-plan.md:223) explicitly requires the aged-out hint for “`/api/gate` 404, `report <path>` not found.” This concerns implemented miss handlers, not the unbuilt retention sweep.

The gate test at [test_ui_interaction_server.py:1216](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/tests/test_cli/test_ui_interaction_server.py:1216) checks 404, the requested ID, and absence of a spurious legacy clause; its legacy counterpart checks the count. Neither asserts the aged-out explanation.

**Requested remediation and coverage:** Include the shared hint on both miss surfaces and assert it in their tests. `review-test-fidelity` additionally requests an assertion through CLI resume preflight: its current cutover test checks only the legacy clause, so dropping the aged-out suggestion during re-raising would pass.

### 3. Shared UI lookup loses legacy-exclusion metadata on misses

**Convergence at the code-area level:** `review-feature-interactions` raises this distinct defect in the UI miss-diagnostic area also covered by the gate findings above. The legacy-metadata defect itself is raised by one lens.

**Stated severity:** **Warning** — `review-feature-interactions`.

References: [run_tailer.py:138](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/ui/run_tailer.py:138), [server.py:1574](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/ui/server.py:1574).

With a valid trace renamed to the legacy grammar, `_cached_listing` retains only `.traces`, discarding `legacy_count`. Pinned lookup consequently returns `None`; the tailer emits a bare `run-not-found`, and node detail returns “No recorded detail…” without explaining that older traces were excluded.

The lens cites the spec requirement: “Every lookup that finds nothing says how many old-grammar traces it did not search.” `/api/gate` preserves this count, but the current gate cutover test does not cover these other UI paths.

**Requested remediation and coverage:** Preserve miss metadata through the shared UI resolver and test the legacy-only case through its callers.

## Critical

No remaining standalone critical findings. The test-fidelity Critical finding is preserved under convergent finding 1.

`review-silent-failures` reported no critical silent wrong results in reviewed paths. `review-feature-interactions` reported no critical unhandled combinations.

## Warnings

### 4. `--only` snapshot misses enumerate the directory twice, outside the tested success branch

**Lens:** `review-feature-interactions`
**Stated severity:** **Warning**
**Reference:** [workflow_trace.py:329](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/workflow_trace.py:329)

When a workflow has no reusable snapshot, `load_full_run_events` lists the directory, then `_snapshot_miss_causes` lists it again to obtain the legacy count. This violates the requirement of “at most one directory listing” and doubles enumeration on the cutover failure path.

The snapshot read-set test calls `load_full_run_events` with a successful candidate, so it cannot detect the extra listing through `load_snapshot_or_raise`.

**Requested remediation and coverage:** Carry the original listing’s count into the refusal and cover directory enumeration through the snapshot-miss path.

## Suggestions

No standalone suggestions were reported. Targeted regression coverage is preserved with the corresponding findings. `review-test-fidelity` found no material test bloat in the reviewed additions.

## Verified clean

The following are each lens’s reported assertions, condensed without reconciling them against other findings.

### `review-silent-failures`

- Marker-write `OSError` disables streaming before the trailer. Durability failure is reported without a token; resume-list excludes the trace, and gate lookup rejects it as non-paused.
- Attempt loading distinguishes disappearance from other I/O failures: disappearance counts as consumption; other read faults produce a refusal rather than silently authorizing another answer.
- `.from-` prefix matches receive full lineage and workflow checks.
- Snapshot and resume readers retain the metadata-level `--only` guard; explicit UI pins can inspect `--only` runs.
- CLI miss clauses survive resume-preflight rethrow. Hidden deleted-workflow pauses are counted, including on JSON stderr.
- The shared fixture helper generates descending IDs, with explicit assertions protecting that property. Read-set tests observe both `builtins.open` and `io.open`; inverted timestamps and mtimes distinguish ordering regressions.
- Pinned-banner and `/api/run-inputs` legacy-clause omissions are explicitly recorded plan exceptions and were not findings for this lens.

### `review-feature-interactions`

- **Marker failure × pause durability:** marker `OSError` disables streaming before the trailer, clears the durable path, and releases the handle. The CLI test checks failed output without identity, incomplete resume behavior, an empty paused list, and gate 404.
- **Marker present × trailer failure:** listing still requires a paused trailer; a stranded marker does not publish a pending pause.
- **`--only` × resume/snapshot/UI:** resume and snapshots exclude partial runs, including untagged traces whose metadata records `only_node`. Explicit UI pins resolve them; automatic discovery excludes them.
- **Attempt-prefix collision × consumption:** loaded `resumed_from` confirms the full source ID. The collision test distinguishes sources sharing eight characters.
- **Recency × fixture construction:** descending IDs oppose timestamp order; report/UI tests invert mtime; snapshot tests oppose display-name order. These distinguish the stated incorrect sorts.
- **Read filtering × fixtures:** read-set tests observe both open functions, assert selected results, and include readable legacy files and unrelated current traces. The helper does not make those assertions pass merely by producing undiscoverable filenames.

### `review-test-fidelity`

- The marker-failure test uses a real CLI-produced trace and checks failed output, absent identity, no trailer, incomplete resume semantics, an empty pause list, and gate refusal. The shared helper cannot manufacture that success.
- Ordering fixtures oppose filename and timestamp order; report and discovery also invert mtime. Named assertions distinguish competing ordering rules.
- Read-set tests intercept both `builtins.open` and `io.open`, assert exact file sets, and count directory enumerations.
- Cutover tests establish presence before renaming the same traces. Untagged `--only` tests independently exercise the metadata guard.
- The helper preserves trailer-less fixture construction separately and pins descending generated IDs. No concrete helper-induced free pass was found in reviewed paths.

## Coverage

| Lens | Provider | Review produced |
|---|---|---|
| `review-silent-failures` | codex | Yes |
| `review-feature-interactions` | codex | Yes |
| `review-test-fidelity` | codex | Yes |

**Failed or missing lenses:** None listed in the supplied gaps input.

**Scope and verification limits:**

- All three reviews covered Task 185 P1+P2; P3/P4 were excluded.
- All reviews were static/read-only. No lens executed tests or mutation checks; implementer-reported mutation results remain independently unverified.
- `review-silent-failures` concentrated on changed logic and relevant callers, did not exhaustively review large unchanged test sections, and assessed mutation-survival claims from assertions.
- `review-feature-interactions` inspected trace discovery, resume consumption, `--only` snapshots, cache analysis, CLI diagnostics, and UI history/pinned-run/gate lookup. It identified the filename/`.paused` candidate-selection boundary as carrying identity, lineage, partial-run exclusion, pause durability, and miss metadata.
- `review-test-fidelity` performed a focused diff-and-call-path audit and did not read every unchanged line of the large existing test/server modules.
