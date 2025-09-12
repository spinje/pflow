---
description: Start a bug fix
argument-hint: [issue-id or description of issue]
---

You are an expert debugger tasked with fixing a bug in the codebase. You will either be given a github issue or a description of an issue and you will need to fix the issue.

## Context
- Issue: "$ARGUMENTS"
- Gather recent changes: run `git status`, `git log -10`.
- Reproduce locally (tests/app) and capture stack traces if available.

## Instructions
- If the issue is a github issue, you will need to first read the github issue as the context for the bug fix using the gh cli.
- If the issue is not a github issue, you will first need to create a github issue with the description of the issue.

## Subagent usage
- You should be using @agent-pflow-codebase-searcher subagents to gather basic information about the codebase but you should not rely on them for the root cause of the issue.
- If you need to use more than one subagent, you should deploy them in parallel using ONE function call block to deploy all subagents simultaneously.
- The subagents should not debug the issue, use them to understand WHERE to look closer yourself rather than relying on them to do the task for you.

## Task
1. Use subagents to gather information about the codebase to understand how reproduce the issue.
2. Reproduce and record the failure & environment.
3. Gain more understanding of the issue by using subagents to gather information about the codebase and investigating the most promising leads yourself.
4. Isolate the fault (file/lines); explain the root cause.
5. Implement the smallest safe fix; preserve public behavior.
6. Add/adjust tests that would have caught this.
7. Run tests & linters; summarize results.
8. Draft a concise commit message and PR description.

## Operating rules
- Work via hypotheses → experiments → evidence.
- Prefer minimal, reversible edits; keep diffs small and testable.
- Explain trade-offs and unknowns explicitly.
- Always make sure you have found the root cause of the issue before fixing it.

## Procedure
1) Collect: reproduce the issue; capture logs/stack; record env & steps.
2) Isolate: bisect recent changes; add temporary logging; narrow to file/region.
3) Diagnose: state the root cause and why it wasn't caught.
4) Fix: implement the smallest safe change; update contracts/types as needed.
5) Validate: run unit/integration tests; add a regression test.
6) Clean up: remove diagnostic code; update `.taskmaster/bugfix/bugfix-log.md` file.
7) Instruct the user how to test the fix.

## Deliverables
- Root cause explanation (1–3 sentences)
- Minimal diff/patch
- Test summary and results
- Preventive recommendation (assertions, checks, monitors)
- Write everything to the `bugfix-log.md` file as your last step.

## Notes
- Do not commit or create a PR, just fix the issue and wait for the user to review and test. Make it easy for the user to test the fix by writing concise and clear instructions as your last user message.