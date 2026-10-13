# Merged Review Report

## Convergent findings

### Retention settings and effective policy — two distinct Warnings

**Area convergence:** `review-silent-failures` (seam B) and `review-agent-ux` independently identified conditions where retention remains enabled despite an intended opt-out or a displayed no-deletion policy. These are distinct defects, preserved separately.

#### Warning — A misplaced opt-out inside an array bypasses detection

**Lens:** `review-silent-failures`, seam B · **Provider:** codex
**Location:** [trace_retention.py:150](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/trace_retention.py:150)
**Contract reference:** [ADR-0018:101](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/context/adr/0018-185-trace-directory-is-the-index.md:101)

With no process override, this settings file loads successfully:

```json
{"runtime_settings": [{"trace_retention_days": 0}]}
```

Unknown fields are allowed, but `_mentions_retention()` only descends through dictionaries. The array hides the retention key, so `retention_days()` returns **14 without a warning**, allowing eligible aged traces to be deleted. Ordinary settings writes preserve this ineffective opt-out.

ADR-0018 promises detection “in any unknown settings key at any level.”

**Lens recommendation:** Traverse arrays within unknown values; this input should disable pruning and warn.

**Stated severity rationale:** Warning because it requires an atypical malformed settings layout.

#### Warning — `settings show` can promise no deletion while workflow execution enables retention

**Lens:** `review-agent-ux` · **Provider:** codex
**Location:** [settings.py:112](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/cli/commands/settings.py:112)

With no shell override and these settings:

```json
{
  "runtime": {"trace_retension_days": 0},
  "env": {"PFLOW_TRACE_RETENTION_DAYS": "3"}
}
```

`settings show` prints “Trace retention in effect: none … so it removes no trace.” Its call to `retention_days()` encounters the misspelled setting before reaching the stored override.

Workflow startup instead injects the stored override into the process environment. Retention then returns **3 days** immediately, bypassing the typo check. Eligible traces can therefore be deleted after the agent was told deletion was disabled.

**Lens recommendation:** Make displayed policy and execution use consistent override resolution, including this combination.

The lens explicitly scopes this finding to the new status claim, not the recorded override-precedence decision.

## Critical

No lens reported a new Critical finding.

## Warnings

### The resume guide incorrectly implies failed `--only` runs lack run identity

**Lens:** `review-agent-ux` · **Provider:** codex
**Location:** [resume.md:21](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/guide/features/resume.md:21)
**Supporting reference:** [run_outcome.py:119](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/execution/formatters/run_outcome.py:119)

Immediately after describing JSON run identity and `resume_command`, the guide says:

> “A failed `--only` run offers neither”

However, `run_outcome.py` still emits `execution_id` and `trace_path` when a trace exists. Only the resume command is suppressed. An agent following the guide could overlook the trace path needed to generate a failure report.

**Lens recommendation:** Replace the wording with:

> “A failed `--only` run retains `execution_id` and `trace_path`, but offers no `resume_command`; re-run the step with `--only`.”

## Suggestions

No lens reported Suggestions.

## Verified clean

The assertions below preserve each lens’s scoped conclusions. All reviews were static; no lens executed tests or wrote files.

### `review-silent-failures` — seam A

At `95bb37e6`, no new seam-A silent-failure finding was established, and no inspected round-two fix was shown wrong or incomplete.

- **Report selection:** Trailer and full-load failures disclose the affected path and cause. An unreadable-only result no longer claims all traces are unfinished. Regression coverage includes second-read failure with and without an older candidate.
- **Resume list:** Strict head/trailer failures produce visible disclosures in text and JSON. Otherwise-empty text results explicitly state that the list is incomplete.
- **Snapshot selection:** Persistent I/O and full-load failures refuse with `OnlySnapshotUnreadableError`; genuine disappearance permits fallback. Empty Snapshot results fail loudly.
- **Consumption evidence:** Recovery advice prohibits moving or deleting traces. Consumption-check I/O failures and post-check source-stat failures retain typed refusals.
- **`--only` resume:** Filename-tag and metadata detection both refuse explicitly. Failed `--only` runs suppress the resume command through the shared outcome builder.
- **Gate and Viewer cache:** Gate reads distinguish disappearance from unreadability. Failed Viewer metadata/trailer reads are not cached, allowing recovery without content changes.
- The additional interaction pass found no new quiet fallback introduced by these fixes.

Previously dispositioned Viewer discovery/history/pinned-resolution and cache-analysis limitations remain **deferred, not verified clear**.

### `review-silent-failures` — seam B

Apart from the array input-shape finding, the lens reported that prior scoped fixes hold by static inspection:

- Stored exact overrides resolve directly despite aborted or skipped environment injection.
- Invalid override values prevent pruning and warn.
- Boolean retention values and duplicate JSON keys fail loading; ordinary saves subsequently refuse.
- Quoted `"0"` retains its opt-out meaning and preserves environment settings.
- `init` and `reset` request confirmation for dangling symlinks and unknown path states.
- Warning deduplication does not suppress the retention-level failed-load warning.
- Ordinary writes preserve recognized opt-outs and unknown keys; process overrides are not persisted.
- `settings show` uses the actual retention resolver.

### `review-test-fidelity`

No new fidelity defect or incomplete fix was found in the changed tests. The lens judged their regression protection meaningful, without material added bloat.

- Report fault tests reach trailer reading and full loading, with an older readable control and an empty-result case.
- Pause-list faults reach metadata and trailer reads; counters reset between text/JSON invocations. Assertions distinguish incomplete results from “No paused runs.”
- Gate diagnostics inject an exception containing the filename and require exactly one path occurrence; disappearance requires zero.
- Settings tests distinguish invalid inputs from valid quoted numbers, verify stored/process override precedence, and check trace preservation against deletion controls.
- Dangling-symlink tests verify that declining preserves the link, confirming replaces it, and an absent file requires no confirmation.
- Failed `--only` tests exercise CLI output and by-ID refusal; a failed full-run control proves resume hints remain available.
- Snapshot advice assertions require restoring readability and prohibit the previously hazardous relocation advice.

### `review-agent-ux`

Apart from its two Warnings, the lens identified these actionable message fixes:

- Report lookup discloses failures at either read, naming the trace and cause; empty-result messaging acknowledges unreadability.
- The paused-list headline correctly states that the list is incomplete.
- Snapshot recovery advice preserves traces that may record an answered pause.
- The `--only` resume refusal explains the limitation and provides the appropriate rerun action.
- Retention typo warnings name the rejected setting and its supported spelling.

### `review-feature-interactions`

No new interaction defect or incorrectly completed fix was established in the requested focus areas. No new abstraction boundary was introduced; fixes use the existing run-scoped collector, shared resume loader, and settings-load failure contract.

- **Failed `--only` × CLI/JSON/MCP rendering:** `has_resumable_step()` rejects the run before inspecting nested or batch events. The shared outcome builder omits `resume_command`; both text renderers consume that document. `TestAFailedOnlyRunOffersNoResume` covers CLI text, JSON, and a full-run presence control. Reference: [workflow_trace.py:1643](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/workflow_trace.py:1643).
- **`--only` × Viewer `/api/resume`:** The loader raises `ResumeNotResumableError` for both filename tags and metadata fallback. Viewer preflight maps this to HTTP 409 with `refusal: "not_resumable"` before spawning. References: [resume_source.py:354](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/resume_source.py:354), [server.py:1135](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/ui/server.py:1135). Dedicated endpoint coverage for an `--only` ID was not found; this conclusion is static.
- **`--only` × gates/nested workflows/batch:** The engine prevents an `--only` gate from becoming a durable pause, so the paused-result command branch cannot bypass the failure suppressor. Nested and batch results remain governed by the root collector’s `only_node`. Existing tests cover whole-child execution and degraded batch Snapshots. Reference: [engine.py:1628](/Users/andfal/projects/pflow-worktrees/feat-task-185-run-lookup/src/pflow/runtime/engine/engine.py:1628).
- **MCP `workflow_execute` × resume results:** This entry point exposes no `--only` option and uses `RunnerConfig()` plus the shared outcome builder. Ordinary failures and durable pauses retain existing resume behavior.
- **Settings rejection × environment/LLM/registry:** Duplicate keys and boolean retention values enter the established whole-file failure path; quoted `"0"` remains valid and preserves environment keys. Defaults, omitted stored credentials, LLM fallback, and default registry filters follow the explicitly accepted contract. Saves refuse after failed loading.
- **Settings × long-lived MCP:** Warning deduplication does not cache settings globally. Fresh request consumers and retention create fresh managers; startup environment injection remains process state. The once-per-process warning limitation is explicitly dispositioned. Stored retention overrides are read directly when no process override exists, closing the injection-abort dependency.

**Convergent clean evidence:** Multiple lenses independently reported successful scoped fixes around report-read disclosures, incomplete pause lists, Snapshot recovery advice, failed `--only` resume suppression, and settings rejection/override handling. Their assertions retain the scope limitations below.

## Coverage

Six review outputs were supplied across five distinct lenses; every output used **codex**.

| Lens / scope | Provider | Reported coverage and limitations |
|---|---|---|
| `review-silent-failures`, seam A | codex | Full lookup-module reads, relevant callers, and regression tests. Unchanged portions of large surrounding modules, including `server.py` and `exceptions.py`, did not receive complete full-file review. Deferred Viewer and cache-analysis limitations remain outside clean clearance. |
| `review-silent-failures`, seam B | codex | Three scoped production files and relevant callers/tests. Not whole-branch completion certification. |
| `review-test-fidelity` | codex | Every changed test hunk and relevant production path inspected. Unchanged bodies of larger test/runtime/UI modules were not exhaustively reread. Scoped fidelity clearance only. |
| `review-agent-ux` | codex | Requested message changes, relevant callers, and documentation counterparts. Unchanged bodies of every modified file were not exhaustively read. Not whole-file completion-gate clearance. |
| `review-feature-interactions` | codex | Changed paths and intersections across `--only`, resume, CLI/JSON/MCP outcomes, Viewer preflight, nested workflows, batch, settings, environment injection, LLM configuration, registry filtering, and retention. Full-file reading of every changed file—including large unchanged runtime bodies, tests, and task artifacts—remains incomplete. Dedicated Viewer endpoint coverage for an `--only` ID was not found. |

**Failed-lens coverage gaps:** None listed in the supplied gaps input.

**Execution coverage:** No tests were run by any supplied lens. The reviews do not certify unrestricted whole-diff or whole-file completion-gate coverage.
