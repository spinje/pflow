# Braindump: The Journey to Understanding Shell Pipeline Failures

**Date:** 2026-01-10
**Context:** Deep investigation into shell node silent failures, leading to Task 109 (stderr check) and Task 110 (PIPESTATUS)

## Where I Am

We just finished a thorough investigation of a bug where shell pipelines with `grep` silently succeed when they should fail. The user and I explored multiple solutions, verified assumptions, and decided on a two-phase approach:

1. **Task 109 (immediate)**: Simple stderr check - ~10 lines, fixes 95% of cases
2. **Task 110 (future)**: PIPESTATUS solution - ~100 lines, fixes 100% but more complex

I created Task 110's task file. Task 109 still needs to be created and implemented.

## User's Mental Model

The user thinks about this from an **agent's perspective**. Key quotes and insights:

- "agents don't know what they don't know" - They can't add `ignore_errors=true` if they don't anticipate failure
- "I think we should solve the root cause if possible, not do bandaids" - Values principled solutions
- "lets assume we have implemented the stderr check and make PIPESTATUS a new task" - Pragmatic: fix now, enhance later
- Asked "is there anything else?" multiple times - Wants comprehensive thinking, not narrow fixes

**The user's real priority**: Agents building workflows shouldn't encounter silent failures. When something goes wrong, it should be visible.

## Key Insights

### 1. The Bug Report Was Partially Wrong

The original bug report claimed `grep + stdin` was the trigger. Through testing, I discovered:
- `grep` WITHOUT stdin also has the bug
- It's not stdin-specific at all
- The bug is: ANY command containing `grep` with exit code 1 triggers smart handling

**Lesson**: Always verify bug reports before implementing fixes.

### 2. The Root Cause Chain

```
_is_safe_non_error() checks:
  exit_code == 1 AND "grep" in command
    → Returns True (safe)
      → post() returns "default" (success)
        → Workflow succeeds despite downstream failure
```

The check doesn't distinguish grep's exit 1 (no matches) from sed's exit 1 (error).

### 3. Multiple Patterns Have the Same Bug

Not just grep! All of these are affected:
- `grep`, `rg` (ripgrep), `ag` (silver searcher)
- `which`, `command -v`, `type`
- Potentially: `diff`, `cmp`, `test`

I verified `grep`, `rg`, `which`, `command -v` all have the bug.

### 4. The stderr Heuristic Is Good Enough

Key insight that made stderr check viable:
- Commands that fail almost always write to stderr
- grep "no match" produces NO stderr
- sed/jq/etc errors produce stderr

This distinguishes the cases in 95%+ of real workflows. The 5% edge case (`grep | false`) is rare.

### 5. PIPESTATUS Actually Works

I verified through extensive testing:
- `subprocess.run(..., executable='/bin/bash')` enables PIPESTATUS
- Can capture it by wrapping commands
- Can parse it to identify which pipeline stage failed
- macOS `/bin/sh` is actually bash, so PIPESTATUS works there too

But it adds ~100 lines of complexity vs ~10 for stderr check.

## Assumptions & Uncertainties

**ASSUMPTION**: stderr presence reliably indicates "real error" vs "no results". This is based on the observation that failing commands write error messages. Edge cases like `grep | false` violate this.

**ASSUMPTION**: Agents rarely use silent-failure patterns like `grep | false`. If this assumption is wrong, Task 110 becomes higher priority.

**UNCLEAR**: Should we also add the `diff` and `cmp` commands to smart handling? They have similar exit code semantics (exit 1 = files differ, not error). We discussed this but didn't decide.

**UNCLEAR**: Should `test`/`[` be handled? Exit 1 = condition false. Very common in scripts.

**NEEDS VERIFICATION**: The simple pipe split (`command.split('|')`) for PIPESTATUS won't handle quoted pipes like `echo "a|b" | grep a`. Need smarter parsing.

## Unexplored Territory

**UNEXPLORED**: How does this interact with the stderr visibility fix we implemented earlier in this session? That fix shows stderr warnings for exit 0 cases. The grep bug is exit 1 cases. They're complementary but we didn't verify they work together properly.

**CONSIDER**: Should there be a `--strict` mode that disables ALL smart handling? For agents that want unambiguous success/failure.

**CONSIDER**: The guidance notes idea ("💡 Note: grep exited 1...") - we discussed it but didn't decide on exact format or where it appears (CLI, JSON, both).

**MIGHT MATTER**: Performance impact of PIPESTATUS capture. We wrap every command in a bash script, capture PIPESTATUS, parse it from stdout. For high-frequency shell commands, this could add latency.

**MIGHT MATTER**: What if bash isn't installed? We use `executable='/bin/bash'` but on minimal containers, bash might not exist. Should fall back gracefully.

## What I'd Tell Myself

1. **Start with verification, not assumptions**. The bug report said "stdin + grep" but it was just "grep". Testing early saved time.

2. **The user values root-cause fixes but accepts pragmatic tradeoffs**. Don't over-engineer, but don't dismiss proper solutions either.

3. **Think about the agent experience**. Every design question comes back to: "What will an agent see when this happens?"

4. **The `_is_safe_non_error` function is the key location**. All the smart handling logic lives there (lines 165-230 in shell.py).

5. **There are TWO tasks now**:
   - Task 109: stderr check (NOT YET CREATED - needs to be done)
   - Task 110: PIPESTATUS (created, documented)

## Open Threads

1. **Task 109 needs to be created and implemented**. The user agreed to this approach but we didn't create the task file or write the code.

2. **Guidance notes format**. We discussed showing "💡 Note: grep exited 1..." but didn't finalize where/how.

3. **Other commands to add**. `diff`, `cmp`, `test`, `ag` - should they get smart handling too?

4. **JSON output for agents**. Should the guidance appear in structured JSON format for programmatic consumption?

## Relevant Files & References

**The bug**:
- `scratchpads/shell-grep-stdin-exit-code-bug.md` - Original bug report
- `scratchpads/test-grep-stdin-bug.sh` - Test script (run to verify bug fixed)

**The code**:
- `src/pflow/nodes/shell/shell.py` lines 165-230 - `_is_safe_non_error()` function
- `src/pflow/nodes/shell/shell.py` lines 600-668 - `post()` method that calls it

**Related work from earlier in session**:
- We implemented stderr visibility for exit 0 cases (different fix)
- Files: `src/pflow/execution/execution_state.py`, `src/pflow/cli/main.py`
- Tests: `tests/test_cli/test_shell_stderr_warnings.py`

**Task files**:
- `.taskmaster/tasks/task_110/task-110.md` - PIPESTATUS task (created)
- Task 109 needs to be created

## For the Next Agent

**Start by**: Creating Task 109 for the stderr check fix. The user approved this approach but we ran out of context before creating the task file.

**The implementation is simple**: In `_is_safe_non_error()`, add `and not stderr.strip()` to each pattern check. About 10 lines total.

**Test the fix with**: `bash scratchpads/test-grep-stdin-bug.sh` - should show "BUG FIXED" after implementation.

**The user cares most about**: Agent experience. Silent failures are the enemy. When something goes wrong, it should be visible.

**Don't forget**: There are other patterns beyond grep (rg, which, command -v) that need the same fix.

**Low priority but noted**: Consider adding `diff`, `cmp`, `test` to smart handling. Consider guidance notes. Consider JSON output format.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
