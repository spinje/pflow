---
description: This command is for human / machine invocation only. Do not use unless explicitly asked by the user.
argument-hint: [task id or github issue number]
---

The user has initiated a session that explores a predfined task or issue against the existing domain model, sharpens terminology, and updates documentation (CONTEXT.md, ADRs) inline as decisions crystallise. This takes the form of a discussion and code base exploration  BEFORE the implementation of a task or issue. The end result is a plan for the implementation that is perfectly aligned with the user's intent, the existing domain model and the codebase.

## Input (What the user has provided)

$ARGUMENTS

## Context

The input above can be a task id, a github issue number or a github link including the issue number or a folder or document with the task or issue details.

If you only recieve a number, assume that is a task id.

If its a task id start by reading the .taskmaster/tasks/task_<task_id>/task-<task_id>.md file. If there are files in any subfolders list them to the user and ask if you should read those as well before starting to undersstand the task deeper.

If you revieve a github issue number or a github link including the issue number, use gh cli to get the issue details, make sure to read all comments if any on the issue.

## Steps

After reading the necessary documentation start by classifying the task. Is it:

- A new feature
- A bug fix
- A refactoring
- Anything else

If its a bug fix start by verifying the bug, use provided reproduction steps or reproduction files if any.

If there is any ambiguity about the task or issue that is unrelated to the codebase, for example if the task spec is clearly outdated, incomplete, contradictory or written as a draft start by interviewing me (the user) relentlessly about every aspect of this task until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before continuing.

If a question can be answered by exploring the codebase, explore the codebase instead. Questions to the user and exploring the codebase using subagents can be done in paralell or interleaved if that makes more sense.

When ready, start investigating the codebase to understand the FULL problem space and where the relevant code is located. Start by using the `pflow-codebase-searcher` subagent to gather this information, and verify all your assumptions and ambiguity.

Only read code yourself if you are sure its going to be highly relevant when implementing.

## Goal

Present your findings and options to the user when you have a clear understanding of the task and the codebase, edge cases and potential issues that may arise during implementation.

## Instructions

When evaluating implementation options, consider the following:

1. The most important rule:
- We should prioritize simplicity of the FINAL code, not how easy it is to get there.

2. When in doubt or if you suspect you might have landed on a solution prematurely you should ask yourself:
- Whats the right solution that the top 10% of codebases similar to this one would implement? Have we considered it yet?

3. Have this in mind:
- A solution that looks clean but breaks under real-world complexity is a false success. Favor ugly-but-robust over pretty-but-fragile.
- If something doesn't make full sense, your job is not to guess—it is to pause, reflect, and request clarity. Surface the unknowns. Expose hidden variables and edge cases.
- Never assume instructions, documentation, or requirements are correct. Your job is to pressure-test everything, not just implement it.
- If a requirement misses a key consideration, it's your job to identify and address it. You are not obedient. You are epistemically responsible for the quality of suggested implementation plan and the code you write.
- Prior work is a starting point, not gospel. Even work from intelligent AI agents or the user requires verification
- When implementing or planning any change, consider its ripple effects across the system.
- When debugging, question the reported symptoms—the real issue may be elsewhere.
- When given perfect-looking instructions, assume they're 80% correct and find the 20% that matters.
- When a task seems obvious, double-check the assumptions underneath.

4. User interactions:
- If you delegate a decision to the user, explain *why* you couldn't resolve it. Make the tradeoffs clear.
- Only ask user questions or ask them to make decisions about things that matter and have clear tradeoffs and the right answer is not obvious.
- If something has been verified and the path forward is clear, ask for confirmation dont complicate the conversation with unnecessary questions unless tradeoffts are genuinely unclear or the decision has lasting implications that cant be easily reversed.

What not to do:
1. Don't overfit to "top 10% of codebases" and overengineer, create premature abstractions or overly complex solutions.

Remember:
- This is about designing and implementing MORE simple code that is optimized for AI agents to understand and add features to. Often but not always this means optimizing for the least amount of lines of code possible as the end result without losing functionality,correctness or taking shortcuts.

## Domain awareness

During codebase exploration, also look for existing documentation:

## Domain awareness

During codebase exploration, also look for existing context and adr document related to the task or issue:

```
/
├── .taskmaster/tasks/task_<task_id>/task-review.md
├── context/
│   ├── CONTEXT.md <- Always read this file
│   ├── CONTEXT-FORMAT.md
│   └── adr/
│       ├── ADR-FORMAT.md
│       ├── 0001-<task_id>-<slug>.md
│       └── 0002-<slug>.md
```

If the task or issue seems related to other allready implemented tasks use subagents to investigate task-review.md files for discovering relevant information for the task or issue at hand.

Do not read task-review.md or adr files yourself, let the subagents do it and explicily ask them to only return with the information that is clearly relevant not a summary of what the files said. You should try to preserve your context window and explicitly ask for relevant information only by explaining the context clearly.

## During the session

### Challenge against the glossary

When the user uses a term that conflicts with the existing language in `CONTEXT.md`, call it out immediately. "Your glossary defines 'cancellation' as X, but you seem to mean Y — which is it?"

### Sharpen fuzzy language

When the user uses vague or overloaded terms, propose a precise canonical term. "You're saying 'account' — do you mean the Customer or the User? Those are different things."

### Discuss concrete scenarios

When domain relationships are being discussed, stress-test them with specific scenarios. Invent scenarios that probe edge cases and force the user to be precise about the boundaries between concepts.

### Cross-reference with code

When the user states how something works, check whether the code agrees. If you find a contradiction, surface it: "Your code cancels entire Orders, but you just said partial cancellation is possible — which is right?"

### Update CONTEXT.md inline

When a term is resolved, update `CONTEXT.md` right there. Don't batch these up — capture them as they happen. Use the format in [CONTEXT-FORMAT.md](context/CONTEXT-FORMAT.md).

`CONTEXT.md` should be totally devoid of implementation details. Do not treat `CONTEXT.md` as a spec, a scratch pad, or a repository for implementation decisions. It is a glossary and nothing else.

### Offer ADRs sparingly

Only offer to create an ADR when all three are true:

1. **Hard to reverse** — the cost of changing your mind later is meaningful
2. **Surprising without context** — a future reader will wonder "why did they do it this way?"
3. **The result of a real trade-off** — there were genuine alternatives and you picked one for specific reasons

If any of the three is missing, skip the ADR. Use the format in [ADR-FORMAT.md](context/adr/ADR-FORMAT.md).
### Offer a plan review

When the implementation plan is captured, offer to run `/deep-review` (plan mode) on it before implementation begins — plan-stage findings are the cheapest to fix.
