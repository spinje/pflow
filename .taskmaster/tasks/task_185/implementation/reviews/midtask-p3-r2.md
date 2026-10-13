# Merged Review Report

## Convergent findings

### 1. Dangling settings symlink silently enables default retention

**Lenses and stated severities:** `review-silent-failures` — **Critical C1**; `review-concurrency-safety` — **Warning W1**. Both independently identified the same defect.

**Location:** [settings.py:214](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/core/settings.py:214)

If `settings.json` links to an external configuration containing `trace_retention_days: 0` and the target becomes unavailable—for example, its volume is unmounted—`open()` raises `FileNotFoundError`. The handler returns defaults with `load_error=None`. Retention consequently selects **14 days**, silently enabling deletion of aged eligible traces despite the configured opt-out, without a settings warning.

A subsequent settings write also bypasses the failed-load guard and can replace the symlink with defaults. Both lenses report that the original `PermissionError` scenario is fixed, while unavailable configuration and genuinely absent configuration remain conflated.

**Requested correction:** After an absence exception, use explicit `lstat` handling to distinguish a missing settings entry from an existing dangling symlink. Unresolved configuration should set `load_error`, disable pruning with a warning, and refuse ordinary saves.

### 2. Pre-unlink revalidation faults are silently reported as protection

**Lenses and stated severities:** `review-concurrency-safety` — **Warning W2**; `review-silent-failures` — **Warning W1**. Both independently identified the same defect.

**Locations:** [trace_retention.py:534](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/trace_retention.py:534), [trace_retention.py:541](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/trace_retention.py:541)

After classification successfully reads an aged unfinished trace, file-descriptor exhaustion or a filesystem permission change can cause the fresh trailer read to raise `TraceUnreadableError`, or the marker `lstat` check to raise `OSError`.

`_still_removable()` returns `False` without recording the fault. `_remove()` reports `"kept"`, and removal bookkeeping increments `protected`; `unreadable` and `skipped` remain unchanged. The trace safely survives, but the fault does not reach the warning condition, so `sweep_after_write()` emits no warning. Both lenses identify this as a sibling of Round 1 W2’s unreported uncertainty.

**Requested correction:** Continue preserving the trace while carrying a distinct fault outcome and the affected path into the warning-producing `SweepReport`.

## Critical

No additional distinct findings. The Critical finding from `review-silent-failures` appears under convergence with its original severity preserved.

## Warnings

No additional distinct findings. All stated warnings appear under convergence.

## Suggestions

Neither lens reported suggestions.

## Verified clean

### `review-concurrency-safety`

- **Round 1 C1:** Newly appeared pause markers and trailers on previously unfinished traces are checked before every unlink attempt, including Windows retries. Markers present before trailer publication are covered by `_unfinished`. The stated Windows residual remains an accepted limitation.
- **Round 1 C2, permission-error scenario:** Direct open failures set `load_error`; retention stops and ordinary saves refuse. The symlink exception is reported above.
- **Round 1 W1:** One module lock protects the shared warning set’s complete check-and-add operation. Logging occurs after releasing the lock; no reverse acquisition path was found.
- **Round 1 W2, workflow-state scenario:** Unknown workflow paths reach `unchecked_workflows` and the sweep warning.
- **Round 1 W3, Viewer scenario:** Disappearance before reading a pinned run produces `run-not-found` and terminates the tailer. The hub replaces terminated tailers for later subscribers.
- Sweep classification state remains invocation-local. Deletion waves retain Attempts when their source is skipped or newly protected. Settings publication uses temporary files and atomic `os.replace`.
- No critical thread-safety or resource-lifecycle findings beyond explicitly accepted limitations. The plan’s “unknown lock → age decides” policy was treated as accepted and not re-reported.

### `review-silent-failures`

- **Round 1 C1:** New pause markers and trailers appearing after unfinished classification prevent deletion. Both unlink attempts re-check; a marker listed before its trailer is covered through `_unfinished`. The stated Windows residual was not re-reported.
- **Round 1 C2, original scenario:** Direct opening removes the `Path.exists()` permission-error fallback. Open/read/validation faults set `load_error`, stop retention, and block ordinary saves.
- **Round 1 W1:** A module-level lock shared across managers protects permission-warning check-and-add.
- **Round 1 W2, original scenario:** Unknown workflow-file states populate `unchecked_workflows` and reach the warning.
- **Round 1 W3:** A vanished pinned trace emits `run-not-found` and terminates. The hub replaces terminated tailers for later subscribers.
- Failed source deletion preserves dependent Attempts. Invalid environment overrides and recognized misplaced retention settings stop pruning visibly.

## Coverage

| Lens | Provider | Reported verification |
|---|---|---|
| `review-concurrency-safety` | `codex` | Source-only review; no tests ran and no files were written. |
| `review-silent-failures` | `codex` | Read-only source tracing over requested revisions, related consumers, and regression-test inspection; no tests executed or files written. Fault injection and native Windows verification remain with the caller. |

**Coverage gaps:** None listed; both supplied lenses produced reviews.
