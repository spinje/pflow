---
name: code-review
description: "Deploy specialized review agents to find bugs that general code review misses. Handles both plan review (before implementation) and code review (after implementation). Deploys 7-8 focused agents in parallel, each targeting a specific blindspot category."
---

# Code Review — Specialized Multi-Agent Review

You are the orchestrator for pflow's specialized code review system. You deploy review agents, evaluate their findings, and produce a concrete action plan. This replaces the general-purpose code review for pflow — it targets the specific blindspot categories identified from this project's bug history.

## Assess Context

You already know the current state from the conversation. Determine which review type fits:

| Context | Review type | Agents |
|---|---|---|
| You just wrote or finalized an implementation plan | **Plan review** | 8 agents (includes `review-plan`) |
| You just finished a phase, staged changes exist | **Code review** (staged) | 7 agents |
| Implementation is done, PR is ready | **Code review** (full branch) | 7 agents |
| User explicitly asks to review plan/code/staged | Whatever they asked for | 7 or 8 agents |

**Protect your context window.** Do NOT read diffs, plans, or full files yourself. The subagents have expendable context windows — let them do the heavy reading. You only need the task ID and a one-line description to deploy them.

## Deploy Agents

Launch ALL agents in a SINGLE message (parallel execution). Keep prompts minimal — the agents have detailed built-in instructions and know the pflow codebase.

### Plan Review — 8 Agents

| # | subagent_type |
|---|---|
| 1 | `review-plan` |
| 2 | `review-silent-failures` |
| 3 | `review-validation-consistency` |
| 4 | `review-impact-completeness` |
| 5 | `review-feature-interactions` |
| 6 | `review-agent-ux` |
| 7 | `review-test-fidelity` |
| 8 | `review-concurrency-safety` |

Tell each agent to review the plan, where to find it, and what task it's for. Example:
```
Review the implementation plan for task 135 (Execution Core Compile-Once Redesign).
Plan: .taskmaster/tasks/task_135/implementation/plan.md
```

### Code Review — 7 Agents

| # | subagent_type |
|---|---|
| 1 | `review-silent-failures` |
| 2 | `review-validation-consistency` |
| 3 | `review-impact-completeness` |
| 4 | `review-feature-interactions` |
| 5 | `review-agent-ux` |
| 6 | `review-test-fidelity` |
| 7 | `review-concurrency-safety` |

Tell each agent what to review and what task it's for. The agents know git — they'll figure out the right commands. Example:
```
Review staged changes for task 135 (Execution Core Compile-Once Redesign).
```
or:
```
Review all changes on this branch for task 135 (Execution Core Compile-Once Redesign).
```

`review-plan` is NOT included in code reviews — it only reviews plans.

## Evaluate Findings

When all agents return, evaluate their findings rigorously. **Do not blindly trust the reviews.** Review agents can be wrong, miss context, or misunderstand the code.

### Step 1: Inventory

Build a complete inventory of all findings across agents. For each finding, extract:
- **What**: The specific issue raised
- **Where**: File path and location
- **Severity**: Critical / Warning / Suggestion
- **Which agent(s)**: Who found it (multiple agents flagging the same area is a strong signal)

Merge duplicates — multiple agents often flag the same issue from different angles. Keep the version with better evidence.

### Step 2: Verify Critical Findings

For findings classified as Critical or high-confidence Warnings, verify them before accepting:

- If a finding references specific code, deploy a `pflow-codebase-searcher` agent (or a small batch in parallel) to verify the claim against actual code. The review agent may have hallucinated a file path, misread a function, or missed surrounding context.
- Check whether the proposed fix would conflict with existing patterns or break other code.
- Check for context the review agent may have missed — CLAUDE.md files, related tests, git history.

You don't need to verify every Suggestion — focus verification effort on findings that would change the implementation.

### Step 3: Classify Each Finding

Render a verdict for each finding:

| Verdict | Meaning |
|---|---|
| **Confirmed** | Issue is real, proposed fix is sound |
| **Confirmed, different fix** | Issue is real, but the proposed fix is wrong or there's a better approach |
| **Disputed** | Issue doesn't exist, or the reviewer misunderstood the code. State why with evidence. |
| **Needs investigation** | Can't determine without deeper analysis or user input |

### Step 4: Surface Ambiguity

Before presenting the plan, explicitly identify:
- Any findings where you're less than 90% confident in your verdict
- Any fixes that touch code you don't fully understand
- Any architectural decisions that should be made by the user, not by you
- Any findings that contradict each other

**Do not silently resolve ambiguity. Surface it.**

## Present Action Plan

### Output Format

```markdown
## Review Summary

**Mode**: [plan/code]
**Task**: [id — description]
**Agents deployed**: [count]
**Findings**: [N confirmed, N disputed, N needs investigation]

### Action Plan (ordered by priority)

#### 1. [Title] — [Confirmed / Confirmed, different fix]
- **Found by**: [agent name(s)]
- **Issue**: [What's wrong]
- **File(s)**: [Exact paths]
- **Fix**: [Concrete description — specific enough to implement]
- **Risk**: [What could go wrong if we get this fix wrong]
- **Tests**: [What tests need adding/modifying, if any]

#### 2. ...

### Disputed Findings
#### [Title] — Disputed
- **Found by**: [agent]
- **Claimed issue**: [What the review said]
- **Why it's wrong**: [Your reasoning with code evidence]

### Needs Investigation
#### [Title]
- **Found by**: [agent]
- **Issue**: [What was raised]
- **Why it's unclear**: [What you'd need to determine]

### Suggestions
- [Finding] (from: [agent])

### Areas Verified Clean
[Summary of what was checked and found correct]
```

### After Presenting

**If the session involves back-and-forth conversation with the user**: Present the action plan and wait for approval before implementing fixes. The user may want to adjust priorities, dispute findings, or skip items.

**If you are operating autonomously** (no conversational back-and-forth): Proceed with implementing confirmed fixes in priority order. Use your judgment on disputed findings — skip them if uncertain.

## Running Individual Agents

You can also launch a single specialist agent when you suspect a specific type of issue — no need for the full battery every time.
