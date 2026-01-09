# Braindump: Shell Stderr Visibility Bug Fix - Overlap with Task 108

**Date:** 2026-01-09
**Context:** Just completed implementation of shell stderr visibility fix, which has significant overlap with Task 108's `--debug` flag

## Where I Am

I just finished implementing a fix for a bug where shell node stderr was hidden when `exit_code=0`. This was a debugging nightmare - pipelines would "succeed" but produce wrong output, and the stderr containing the actual error was invisible.

**What we implemented:**
- `execution_state.py`: Added `has_stderr`/`stderr` detection for shell nodes with exit_code=0
- `main.py`: Added `_display_stderr_warnings()` function, modified status indicators to show ⚠️
- 28 new tests covering CLI, JSON output, and the exact bug scenario

**The fix is complete and working.** This braindump is about how it affects Task 108.

## User's Mental Model

The user thinks about debugging in terms of **immediate visibility**:
- "Quality over quantity" for tests - they want tests that catch real bugs
- They want warnings to be **always visible**, not behind flags
- They verified manually that all scenarios work before considering done
- They explicitly asked about Task 108 overlap before closing out

Key quote from earlier research (from another agent's session):
> "The problem: There was no error. The workflow 'succeeded' with wrong output. So it's not about error messages - it's about visibility."

## Key Insights

### 1. The Stderr Fix and Task 108's `--debug` Are Complementary, Not Overlapping

Initially I thought there was significant overlap. After implementation, I see they solve different problems:

| Aspect | Stderr Fix (Done) | Task 108 `--debug` |
|--------|-------------------|-------------------|
| **Problem solved** | Hidden errors from pipelines | Can't see data flow |
| **Trigger** | Automatic (always on) | Manual flag |
| **Scope** | Only stderr with exit_code=0 | All shared store data |
| **Output location** | In execution summary | After execution summary |
| **Primary user** | Humans debugging failures | Agents understanding data flow |

### 2. Task 108's `--debug` No Longer Needs to Special-Case Stderr

The research doc (`research-inline-debug-flag.md`) mentioned showing stderr in the `--debug` output. Now that stderr warnings are always visible, `--debug` can focus purely on showing the shared store state without needing to highlight stderr specially.

### 3. The `has_stderr` Flag in JSON is Critical for Agents

We added `has_stderr: true` and `stderr: "..."` to the JSON output's `execution.steps[]`. This is important for Task 108 because agents consuming JSON now have a programmatic way to detect stderr issues without parsing text output.

Example JSON output:
```json
{
  "execution": {
    "steps": [{
      "node_id": "pipeline-node",
      "has_stderr": true,
      "stderr": "sed: RE error: repetition-operator operand invalid"
    }]
  }
}
```

## Assumptions & Uncertainties

**ASSUMPTION:** Task 108's `--debug` flag should NOT duplicate the stderr warning display. The shared store dump will include `node.stderr` anyway, so showing it twice would be redundant.

**ASSUMPTION:** The `has_stderr` flag in JSON steps is sufficient for agent detection. Task 108 might not need additional stderr handling.

**UNCLEAR:** Should Task 108's `--debug` output indicate which nodes had stderr warnings? Or just show raw shared store? The warning indicators are already in the normal output, so maybe `--debug` should be purely data dump.

**NEEDS VERIFICATION:** Does the user want Task 108's `--debug` to be purely additive (show shared store AFTER existing output), or should it modify the existing output format?

## Unexplored Territory

**UNEXPLORED:** We didn't discuss whether the JSON output's `status` field should change from `"success"` to `"degraded"` when stderr is present. Currently it stays `"success"`. This might matter for agents making decisions based on status.

**CONSIDER:** The `--debug` flag from Task 108 research shows truncated values (e.g., "2.3kb"). We used 300 char truncation for stderr. Should these be consistent?

**MIGHT MATTER:** The stderr fix only applies to shell nodes. If future nodes produce stderr-like warnings (e.g., deprecation warnings from HTTP nodes), we might need a more generic "node warnings" system. Task 108's design should consider this.

**CONSIDER:** Should `--debug` work in MCP context? The research doc asked this question but didn't answer it. Now that stderr visibility is handled, this is purely about shared store visibility for agents.

## What I'd Tell Myself

1. **Don't try to merge these features.** Stderr visibility (always-on warnings) and `--debug` (opt-in data dump) solve different problems. Keep them separate.

2. **The JSON output is the real interface for agents.** The `has_stderr` flag in `execution.steps[]` is how agents will detect issues. Task 108 should ensure `--debug` mode provides equally structured data.

3. **The user values "always visible" over "opt-in".** They explicitly chose to show stderr warnings without requiring flags. Task 108's `--debug` is opt-in by design, but consider if any of its features should be always-on.

## Open Threads

1. **Update Task 108 spec?** The task spec might mention stderr visibility as a goal. It's now handled separately and should be noted.

2. **Consistency of truncation.** Stderr uses 300 chars, Task 108 research mentioned configurable thresholds. Should standardize.

3. **The `status` field question.** Workflows with stderr show `status: "success"` in JSON. Is this correct? Or should it be `"degraded"` or a new `"success_with_warnings"`?

## Relevant Files & References

**Files I modified (stderr fix):**
- `src/pflow/execution/execution_state.py:129-137` - stderr detection logic
- `src/pflow/cli/main.py:732-758` - `_display_stderr_warnings()` function
- `src/pflow/cli/main.py:797-814` - `_display_workflow_completion_status()` helper
- `tests/test_cli/test_shell_stderr_warnings.py` - 16 tests
- `tests/test_execution/test_execution_state.py` - 12 tests

**Task 108 research (read these first):**
- `.taskmaster/tasks/task_108/starting-context/research-inline-debug-flag.md` - `--debug` flag proposal
- `.taskmaster/tasks/task_108/starting-context/braindump-inline-debug-discovery.md` - How the need was discovered
- `.taskmaster/tasks/task_108/task-108.md` - Main task definition

**Related PR:**
- PR #52 - Surfaces upstream stderr when downstream nodes fail (different scenario, but related)

## For the Next Agent

**Start by:** Reading Task 108's spec and research docs, then compare with what's now implemented for stderr. Note that stderr visibility is DONE - don't re-implement it.

**Don't bother with:** Trying to show stderr in `--debug` output specially. It's already shown in the execution summary. Just include it in the raw shared store dump like any other data.

**The user cares most about:** Immediate visibility without requiring flags. Task 108's `--debug` is opt-in by design, which is fine since it's for deeper debugging. But if you're adding features, consider if they should be always-on.

**Key decision to make:** Should `--debug` show raw shared store data only, or should it include the new `has_stderr` metadata? The metadata is already in JSON output's `execution.steps[]`, so maybe `--debug` just needs to show the raw `shared[node_id]` dict which includes `stderr` naturally.

**Test the overlap:** Run `uv run pflow scratchpads/shell-stderr-visibility-bug/test-cases/stderr-hidden-exit0.json` to see what stderr visibility looks like now. Then design `--debug` to add value beyond this.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
