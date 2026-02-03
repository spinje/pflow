# Progress Tracking for Implementing Agents

> Standard process for all agents working on implementation tasks.
> Main agents and fork-session subagents follow the same format but write to separate files.

## File Locations

| Agent type | Progress log path |
|------------|------------------|
| Main agent | `.taskmaster/tasks/task_N/implementation/progress-log.md` |
| Fork subagent | `.taskmaster/tasks/task_N/implementation/progress-log-{phase}-{label}.md` |

Fork filenames encode the phase and a short descriptive label: `progress-log-3.1-examples-core.md`, `progress-log-3.3-test-cli-group1.md`, etc.

## Progress Log Format

Create the file at the start of implementation. Append entries as you work — never rewrite previous entries.

### Standard Entry

**Main agent** references the phase/subtask from the implementation plan:

```markdown
## Phase X.Y — Entry N: [what you're working on]

Attempting: [specific action]

Result: [what happened]
- ✅ Worked: [detail]
- ❌ Failed: [detail]
- 💡 Insight: [what I learned]

Files modified: [list of files touched in this entry]
Status: [where you are now, what's left in this phase]
```

**Fork subagent** references the task, phase, and assigned subtask from its fork prompt:

```markdown
# Fork: Task N — Phase X.Y — [assigned subtask description]

## Entry 1: [what you're working on]

Attempting: [specific action]

Result: [what happened]
- ✅ Worked: [detail]
- ❌ Failed: [detail]
- 💡 Insight: [what I learned]

Files modified: [list of files touched in this entry]
Status: [where you are now, what's left in your assignment]
```

The fork's H1 heading states the full assignment context once. Individual entries are numbered sequentially within that assignment.

### Decision Entry

When you choose between approaches, capture the reasoning:

```markdown
## Decision: [title]

- Options: [A, B]
- Chose: [A] because [reason]
- Reversible: [yes/no]
```

### Deviation Entry

When the plan doesn't match reality:

```markdown
## DEVIATION FROM PLAN

- Plan said: [what was planned]
- Reality: [what actually happened]
- New approach: [what you're doing instead]
- Downstream impact: [what changes in later phases/tasks]
```

## Rules

1. **Append only.** Never delete or rewrite previous entries. The log is a chronological record.
2. **Status line is mandatory.** Every entry must end with a Status line. This is the resumption checkpoint — if the context window is exhausted or the session is interrupted, the next agent reads the last Status line to know where to continue.
3. **Files modified is mandatory.** List every file you created or changed in the entry. This is critical for fork coordination — the main agent needs to know which files each fork touched.
4. **No code snippets.** The code is in the files; git diff is the source of truth. If a pattern is worth noting, describe it in one sentence.
5. **Log decisions, not just outcomes.** "I tried X and it worked" is less valuable than "I chose X over Y because Z."
6. **Don't log trivial actions.** One entry per meaningful unit of work (e.g., "implemented YAML continuation parsing"), not per file edit.

## How to Know If You Are a Fork

Your conversation context will contain messages from the main agent — you will see its progress log entries, its code changes, its decisions. This is because you inherited the full session context via `--fork-session`. **This does not make you the main agent.**

**You are a forked subagent if your prompt starts with `[FORKED SESSION]`.** If you see this prefix, you are a fork — follow the fork rules below, write to your own progress log file, and stay within your assigned scope. Do not continue the main agent's work or update its progress log.

## Fork-Session Subagent Rules

When invoked via `pflow fork-session` (identified by the `[FORKED SESSION]` prefix), subagents follow additional rules:

1. **Write to your own progress log file.** Use the fork-specific path from the table above. Never write to the main agent's progress log.
2. **Do NOT run `make test` or `make check`.** Other forks may be modifying the codebase concurrently. Test failures outside your assigned files are expected — do not investigate or fix them.
3. **If tests fail for reasons outside your assigned files, ignore them and proceed.** Document what you observed but do not interfere with other forks' work.
4. **Stay within your file assignment.** Only modify files explicitly listed in your fork prompt. If you discover a file needs changes that isn't in your assignment, document it in your progress log as a note for the main agent.
5. **Report final status clearly.** Your last progress log entry should summarize: files modified, what was completed, what was NOT completed (if anything), and any issues for the main agent to resolve.

## Main Agent Responsibilities After Forks

After all forks complete:

1. Read each fork's progress log
2. Run `make test` and `make check` on the combined result
3. Fix any integration issues between forks' work
4. Document phases done and fixes in the main progress log
5. Continue with the next sequential phase

## Main Agent: How to Invoke Forks

### Command

```bash
pflow fork-session prompt="[your prompt here]"
```

The `fork-session` workflow finds the current Claude Code session, forks it with `--resume --fork-session`, and passes the prompt. The forked agent inherits the full conversation context.

### Running Forks in Parallel

Each `pflow fork-session` invocation blocks until the forked agent completes. To run multiple forks concurrently, launch them as background Bash tasks in a single message:

```
# In a single message, invoke multiple Bash tool calls with run_in_background=true:
Bash(run_in_background=true): pflow fork-session prompt="[fork A prompt]"
Bash(run_in_background=true): pflow fork-session prompt="[fork B prompt]"
Bash(run_in_background=true): pflow fork-session prompt="[fork C prompt]"
```

Each returns a task ID. Use `TaskOutput(task_id, block=false)` to check progress, or `TaskOutput(task_id, block=true)` to wait for completion. The main agent can continue working on other things while forks run.

All forks run concurrently against the same codebase. This is why file-level isolation between forks is critical.

### Prompt Template

Forked agents inherit the full conversation context — they know the task, the spec, the decisions, the code that's been written, and the patterns being used. **Don't re-explain what the fork already knows.** The prompt is about scope and boundaries, not implementation guidance.

Every fork prompt must include:

1. **Phase reference** — which phase/subtask this fork is implementing (the fork already knows the task from context)
2. **Exact file list** — every file the fork is allowed to modify (no overlaps between forks)
3. **Progress log path** — where to write the fork's progress log
4. **Process reference** — point to this document so the fork knows the rules even if the main agent hasn't read it recently
5. **Completion criteria** — what "done" looks like for this fork

Keep it short. The fork has full context — it just needs to know its boundaries and assignment.

Example:

```
pflow fork-session prompt="Implement Phase 3.1 — convert examples/core/ workflows.

Implement ONLY this assignment. Do not work on other phases, fix unrelated issues, or continue previous work.

Files to convert (delete .json originals after):
- examples/core/minimal.json
- examples/core/hello-world.json
- [etc.]

Follow the fork process in .taskmaster/tasks/task_107/implementation/progress-tracking.md
Progress log: .taskmaster/tasks/task_107/implementation/progress-log-3.1-examples-core.md

Done when: all .json workflow files in examples/core/ are converted to .pflow.md and originals deleted."
```

### Cost Expectations

The first fork from a session pays a cold-start cache creation cost (~$0.50). Subsequent forks reuse the cached context and cost ~$0.05 each. Plan fork order accordingly — consider running a lightweight fork first to prime the cache before launching the parallel batch.

### Timeout

The fork-session workflow has a 1-hour timeout (`timeout: 3600`). For large assignments (e.g., converting 10+ test files), consider splitting into smaller forks rather than risking a timeout.
