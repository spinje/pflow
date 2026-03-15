---
description: Evaluate a code review
argument-hint: [review-file-path or paths]
---

# Evaluate Code Review

You are a senior engineer who has received a code review. Your job is to understand every finding, verify it against the actual code, and produce a concrete action plan.

## Inputs

Inputs: $ARGUMENTS

The input should be one or more file paths to review documents (markdown files in `scratchpads/`, PR comments, or any text containing review feedback).

---

## Phase 1: Read and Understand

1. Read every review file provided.
2. For each finding, extract:
   - **What**: The specific issue raised
   - **Where**: File path and location (if mentioned)
   - **Severity**: Critical / Warning / Suggestion (use the reviewer's classification if present)
   - **The reviewer's proposed fix** (if any)

Do not act yet. Just build a complete inventory of findings.

## Phase 2: Gather Evidence (Subagents)

**Do not blindly trust the review.** Reviews can be wrong, outdated, or based on misunderstanding.

Deploy `pflow-codebase-searcher` subagents **in parallel** to gather evidence for the findings. For each finding (or group of related findings), instruct a subagent to:

1. Read the actual code referenced and report what it does
2. Check for context the reviewer may have missed — CLAUDE.md files, related tests, git history, surrounding code
3. Check whether the proposed fix would conflict with existing patterns or break anything

Subagents are your research team. Give them specific questions, not vague instructions. They bring back facts — you make the judgments.

## Phase 3: Form Your Own Judgment

Once subagents return, **read the key files yourself**. You likely implemented this code — but don't rely on memory, especially after context resets.

For each finding, with the subagent evidence in hand:

1. **Read the code** — verify the subagent's report is accurate. Subagents can miss nuance or misinterpret the question.
2. **Evaluate the proposed fix** — would it actually work? Is there a simpler approach? Does it introduce new problems?
3. **Render your verdict** — you've seen the evidence and the code. Decide.

Classify each finding into one of:

- **Confirmed** — the issue is real and the fix is sound
- **Confirmed, different fix** — the issue is real but the proposed fix is wrong or suboptimal
- **Disputed** — the issue doesn't exist, or the reviewer misunderstood the code
- **Needs investigation** — can't determine without deeper analysis or user input

## Phase 4: Prioritize and Plan

Group confirmed findings into an ordered action plan:

### Ordering rules:
1. **Critical fixes first** — correctness bugs, security issues, data loss risks
2. **Dependency order** — if fix B depends on fix A, A comes first
3. **High-value warnings** — things that will cause real problems if left
4. **Low-risk suggestions** — style, naming, minor improvements last

### For each action item, write:

```
### [N] Title
- **Finding**: What the review said
- **Verdict**: Confirmed / Confirmed, different fix / Needs investigation
- **File(s)**: Exact paths and line numbers
- **What to do**: Concrete description of the change (not vague — specific enough to implement)
- **Risk**: What could go wrong if we get this wrong
- **Tests**: What tests need to be added/modified (if any)
```

### For disputed findings, write:

```
### Disputed: Title
- **Finding**: What the review said
- **Why it's wrong**: Your reasoning, with evidence from the code
```

## Phase 5: Surface Ambiguity

Before presenting the plan, explicitly call out:

- Any findings where you're less than 90% confident in your verdict
- Any fixes that touch code you don't fully understand
- Any architectural decisions that should be made by the user, not by you
- Any findings that contradict each other

**Do not silently resolve ambiguity. Surface it.**

## Output

Write the evaluation to `scratchpads/review-evaluation/` as a markdown file. Do not overwrite existing files.

Present a summary to the user with:
1. Total findings: N confirmed, N disputed, N needs investigation
2. The ordered action plan (brief version)
3. Any decisions that need user input before proceeding

**Do not start implementing fixes.** Wait for the user to approve the plan.
