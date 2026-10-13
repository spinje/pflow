# Merged Review Report

## Convergent findings

### Critical — Writer finalization can invalidate protection decisions and cause protected data loss
**Lenses:** `review-concurrency-safety` (C1), `review-silent-failures` (Critical 2)
**References:** [trace_retention.py:350](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/trace_retention.py:350), [trace_retention.py:418](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/trace_retention.py:418)

**Convergence:** Both lenses independently identify the same stale-state deletion race.

Concrete interleaving involving an aged running trace and a newer successful run of the same existing workflow:

1. The sweep lists the running trace before its `.paused` marker exists.
2. The writer finalizes Paused: creates the marker, flushes the trailer, and closes its handle.
3. The sweep skips pending-pause protection because its cached `entry.paused` is false.
4. The removal probe observes the now-free writer lock and deletes the trace.

The token is answerable at deletion time but disappears without warning. The newly created marker remains orphaned because `_remove_trace` also uses the stale `entry.paused` flag.

Both lenses also identify the analogous Snapshot race: the walk observes an incomplete trailer, then deletes the run after it finalizes as the newest success.

**Remedy stated by the lenses:** Establish protection from current finalized state after observing the writer’s lock free. Refresh terminal status and sidecars before deletion, and conservatively retain candidates whose facts changed. Windows retries must also revalidate if the writer closes between unlink attempts. The existing interleaved-sweeps test covers finalized files disappearing, not this transition.

### Critical — Settings lookup faults can silently enable retention on Python 3.14
**Lenses:** `review-concurrency-safety` (C2), `review-silent-failures` (Critical 1)
**References:** [settings.py:197](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/core/settings.py:197), [settings.py:198](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/core/settings.py:198)

**Convergence:** Both lenses independently identify the same settings-fault path and report confirming Python 3.14’s behavior in the installed standard-library source.

`_load_from_file()` clears `load_error`, then calls `Path.exists()` outside its error handler. On supported Python 3.14, `Path.exists()` returns false for filesystem/stat errors, including `PermissionError`.

For example, `settings.json` links to a file containing `trace_retention_days: 0` inside a directory that becomes inaccessible while `.pflow/debug` remains accessible. Loading returns defaults with `load_error=None`; `retention_days()` selects **14**, potentially deleting aged traces despite the opt-out, without a settings-fault warning. The save refusal is also bypassed.

**Remedy stated by the lenses:** Use a direct open with explicit handling that distinguishes genuine absence from other errors. Only genuine absence should select defaults without `load_error`; faults must set `load_error`, disable pruning, and prevent saving defaults.

## Critical

No additional distinct Critical findings. Both lenses’ Critical findings are consolidated above.

## Warnings

### Permission-warning deduplication is not atomic across managers
**Lens:** `review-concurrency-safety` (W1)
**Reference:** [settings.py:472](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/core/settings.py:472)

Concurrent MCP requests execute in worker threads and can construct separate `SettingsManager` instances. Both threads can pass the module-set membership check before either adds the path, causing duplicate warnings. Their instance locks do not protect the shared set.

**Remedy stated by the lens:** Protect check-and-add with one module-level lock and emit the warning outside it.

**Area convergence:** Both lenses raised findings in settings error handling; this warning remains a distinct defect from the convergent settings lookup fault.

### Workflow-file lookup faults silently disable pruning for whole groups
**Lens:** `review-silent-failures` (Warning 1)
**References:** [trace_retention.py:269](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/trace_retention.py:269), [trace_retention.py:127](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/trace_retention.py:127)

A permission or I/O fault checking a workflow produces `"unknown"` and preserves its entire group, but records neither `unreadable` nor `skipped`. The warning condition at line 127 therefore stays false. Persistent permission restrictions can leave retention doing nothing for those workflows indefinitely without explanation.

**Remedy stated by the lens:** Preserve the traces, but count and report workflow paths whose existence could not be checked.

### Retention can make the Viewer misreport a completed run as stopped
**Lens:** `review-silent-failures` (Warning 2)
**Reference:** [run_tailer.py:388](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/ui/run_tailer.py:388)

A pinned Viewer resolves an aged, unprotected successful trace; a sweep deletes it before the first byte read. `_read_bytes()` folds the missing file into empty bytes.

On POSIX, `_check_stopped()` then sees a free/missing lock and no trailer and broadcasts `run-stopped`. On Windows, the unknown lock verdict leaves the empty pinned view polling. Neither reports that retention removed the trace. This existing consumer becomes exposed by P3’s automatic deletion.

**Remedy stated by the lens:** Distinguish disappearance from an unfinished run and surface `run-not-found` with the retention explanation.

## Suggestions

Neither lens reported additional Suggestions beyond the remedies attached to its findings.

## Verified clean

### `review-concurrency-safety`

- Sweep bookkeeping is invocation-local; concurrent sweeps share no mutable classification caches.
- For sources present in the listing, deletion waves retain Attempts when source unlink fails. Repeated unlinks tolerate files already removed by another sweep.
- Strict trace open/read failures preserve candidates; unreadable consumption evidence preserves the paused source.
- Settings writes use temporary files and atomic `os.replace`, preventing partially written JSON from reaching concurrent readers.
- Windows sharing violations retry once, then remain counted skips.
- Viewer reads use scoped handles and tolerate disappearing files without propagating read exceptions.

### `review-silent-failures`

- Strict trace open/read faults preserve affected traces and reach the sweep warning.
- Failed source deletion preserves its Attempts; removal waves retain consumption evidence.
- Observed held POSIX writer locks protect their traces.
- Windows sharing violations retry once, then count skipped deletion and continue.
- Invalid retention overrides, recognized misplaced retention keys, and caught settings-load failures disable pruning.
- Unknown settings keys survive saves and are omitted from `settings show`.
- Sweep exceptions produce warnings without changing the workflow outcome.

## Coverage

| Lens | Provider | Review produced |
|---|---|---|
| `review-concurrency-safety` | codex | Yes |
| `review-silent-failures` | codex | Yes |

**Failed-lens coverage gaps:** None listed.

Both reviews covered Task 185 P3, revision range `10bad571..6966925a`, through read-only source review. P4 was excluded; the concurrency lens explicitly excluded P4 documentation absence.

Neither lens executed tests. The concurrency lens also reported no workflow execution or native Windows checks. The silent-failures lens stated that its findings came from source tracing rather than executed reproductions, leaving deterministic fault/interleaving tests and native Windows verification to the caller.

The concurrency lens concluded that P3 is **not yet safe to enable**, citing writer-finalization races and settings-stat failures that can activate retention despite an opt-out. The silent-failures lens likewise identified these two deletion paths as unsafe while acknowledging substantial conservative handling.
