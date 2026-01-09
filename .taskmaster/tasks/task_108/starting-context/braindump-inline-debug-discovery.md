# Braindump: How We Discovered the Need for Inline Debug Output

**Date:** 2026-01-09
**Context:** Investigation of a false bug report that revealed an observability gap

## Where I Am

This session started with the user asking me to review a bug report (`scratchpads/bug-optional-input-null-string.md`) claiming that optional inputs become the string `"null"` instead of empty string in shell commands.

After thorough investigation with parallel subagents, I discovered **the bug doesn't exist** - the code correctly handles `None` → `""` conversion. The bug report was a misdiagnosis caused by poor visibility into workflow data flow.

This led to a productive discussion about what the agent actually needed: **inline debug output during execution**, which became research input for Task 108.

## User's Mental Model

The user thinks about this in terms of **agent efficiency**:
- Agents waste time guessing at causes when they can't see data flow
- The trace files have all the info, but require manual JSON inspection
- A quick sanity check during execution would prevent false diagnoses
- "Show the shared store + link to trace file" - simple, pragmatic solution

Key phrase from the other agent the user quoted:
> "The problem: There was no error. The workflow 'succeeded' with wrong output. So it's not about error messages - it's about visibility."

The user's proposed solution was deliberately minimal:
- `--debug` flag (not `--verbose` with per-node output)
- Final shared store state (not per-node stdin/stdout)
- Truncated values (token-efficient for AI agents)
- Link to trace file for deeper investigation

## Key Insights

### 1. The False Bug Report Chain of Causation

```
Poor debugging UX
    ↓
Agent couldn't see actual data flow
    ↓
Forced to guess at root cause
    ↓
Guessed wrong (theorized None → "null")
    ↓
Wrote incorrect bug report
    ↓
Wasted investigation time
```

This is the real problem Task 108 needs to solve.

### 2. The Actual Template Resolution Behavior

I verified this with code analysis AND live testing:

| Template Type | Example | None Becomes |
|---------------|---------|--------------|
| Simple | `"${optional}"` | `None` (preserved) |
| Complex | `"text ${optional}"` | `""` (empty string) |

The code at `template_resolver.py:367-368`:
```python
if value is None or value == "":
    return ""
```

Tests confirm this: `test_none_value_resolves_to_empty_string` in `test_node_wrapper_template_validation.py:451-461`.

### 3. Edge Cases I Discovered (Documented but Worth Noting)

When testing the "non-bug", I found these behaviors:

- `"command": "${optional}"` (simple template, None) → Error: "Missing required parameter" (confusing message)
- `"command": "ls ${optional}"` (complex template, None) → Becomes `ls ` → Lists current directory (surprising but not wrong)
- `"${data.field}"` where data=None → Error: "Unresolved variables" (correct, can't traverse None)

These are documented in tests but the error messages could be clearer.

## Assumptions & Uncertainties

**ASSUMPTION:** The user wants `--debug` to be a simple flag, not a full verbose mode. They explicitly chose "show shared store at end" over "show per-node stdin/stdout".

**ASSUMPTION:** Token efficiency is important because the primary consumers are AI agents, not humans.

**UNCLEAR:** Should `--debug` be a standalone mini-feature or part of Task 108? The user said "research input for task 108" which suggests it could be either.

**UNCLEAR:** Should `--debug` also work in MCP context? The current Task 108 scope includes an MCP tool (`get_debug_trace`), but that's post-execution analysis, not inline output.

**NEEDS VERIFICATION:** The truncation threshold for long strings. I suggested 200 chars in the research doc but this wasn't discussed.

## Unexplored Territory

**UNEXPLORED:** What about streaming workflows or long-running nodes? The `--debug` output assumes execution completes. If a node hangs, you'd see nothing.

**CONSIDER:** Should `--debug` show timing per shared store key? e.g., "fetch-data.response (set at 234ms)". Might help identify slow nodes.

**MIGHT MATTER:** The relationship between `--debug` and the existing `--dry-run` flag. Should `--debug --dry-run` show what the shared store *would* look like?

**UNEXPLORED:** Error cases. Current proposal shows shared store on success. On failure, should it show partial state? The trace file has this, but inline visibility might help.

**CONSIDER:** Environment variable alternative to flag? `PFLOW_DEBUG=1` for always-on debugging during development.

## What I'd Tell Myself

1. **Don't trust bug reports without reproduction.** The scratchpad claimed specific behavior that was demonstrably false. A 30-second test would have saved the whole investigation.

2. **The subagents were thorough but found a contradiction.** They correctly identified that the code should produce `""` not `"null"`, but couldn't explain why the bug report claimed otherwise. The answer: the bug report was wrong.

3. **The user pivoted well.** When I showed the bug didn't exist, they immediately asked "what went wrong with the agent's analysis?" - leading to the real insight about observability.

4. **PR #49 is relevant context.** It fixed optional inputs without defaults failing template resolution. The code comments there explain the design decision well.

## Open Threads

1. **The `--debug` flag is not yet a formal task.** It's research input. Someone needs to decide: separate mini-task or part of Task 108?

2. **I deleted the false bug report files** per user request, but the PR #49 scratchpad still exists at `scratchpads/optional-input-resolution/README.md` - that one documents a real (now fixed) bug.

3. **The edge case behaviors I tested** (like `ls ${optional}` becoming `ls `) aren't bugs but could benefit from documentation. I didn't create a doc for this.

## Relevant Files & References

**Research I created:**
- `.taskmaster/tasks/task_108/starting-context/research-inline-debug-flag.md` - The main output of this session

**Code paths for None → "" conversion:**
- `src/pflow/runtime/template_resolver.py:367-368` - The `_convert_to_string()` method
- `src/pflow/runtime/workflow_validator.py:175-186` - Where optional inputs get `None` default

**Tests that verify behavior:**
- `tests/test_runtime/test_node_wrapper_template_validation.py:451-472` - None in templates
- `tests/test_runtime/test_null_defaults.py` - Optional input handling

**PR #49 context:**
- `scratchpads/optional-input-resolution/README.md` - The real bug that was fixed
- Commit `bbebd54` - The merge commit

**Task 108 docs:**
- `.taskmaster/tasks/task_108/task-108.md` - Main task definition
- `.taskmaster/tasks/task_108/starting-context/task-108-spec.md` - Detailed spec

## For the Next Agent

**Start by:** Reading the research file I created (`research-inline-debug-flag.md`). It has the user's proposed solution and design questions.

**Don't bother with:** Re-investigating the "None → null" bug. It doesn't exist. The code is correct.

**The user cares most about:** Token-efficient debugging for AI agents. They want minimal output that gives quick visibility, with trace files as escape hatch for deep dives.

**Key decision needed:** Is `--debug` a small standalone feature or part of Task 108's scope? The user leaned toward "research input for 108" but didn't definitively answer.

**If implementing `--debug`:** Look at `src/pflow/cli/main.py` for where the flag would go, and `src/pflow/execution/display_manager.py` for existing output patterns. The shared store is already available at end of execution - just need to pretty-print it with truncation.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
