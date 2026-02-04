# Task 107: Implement Markdown Workflow Format

You are the **main orchestrating agent** for Task 107 — replacing JSON with markdown (`.pflow.md`) as the only workflow file format for pflow.

## Required Reading (in order)

**Read these files completely before doing anything else:**

1. `.taskmaster/tasks/task_107/task-107.md` — task overview, scope, verification criteria
2. `.taskmaster/tasks/task_107/starting-context/format-specification.md` — complete format design (27 decisions, parsing rules, code block mapping, integration points). **The format is settled. Don't redesign it.**
3. `.taskmaster/tasks/task_107/implementation/implementation-plan.md` — phased plan with settled decisions, gotchas, file-by-file changes, and **fork assignment table**
4. `.taskmaster/tasks/task_107/implementation/progress-tracking.md` — operating model and fork process
5. `.taskmaster/tasks/task_107/implementation/progress-log.md` — to see what's already done and the resumption checkpoint

Read ALL these 5 files. This is unnegotiable. Every file fills a distinct purpose.

## Operating Model

**You do NOT write code directly.** All coding is done by forked agents via `pflow fork-session`. Your role:

1. **Read and understand** — task documents, spec, implementation plan, progress log
2. **Plan fork assignments** — use the fork assignment table in the implementation plan
3. **Launch forks** — via `pflow fork-session` with precise prompts (see prompt template in progress-tracking.md)
4. **Review results** — read fork progress logs, run `make test` and `make check`
5. **Coordinate** — fix trivial integration issues (1-2 lines), update progress log, launch next fork

Never fix or write code as the main agent.

## Process

- Follow the fork assignment table in the implementation plan. Launch forks in the order specified.
- Update your progress log after each fork completes.
- At Phase 2.9 (smoke test gate), verify the full workflow lifecycle works before launching Phase 3 forks.
- Phase 3 forks (F7-F13) can run in parallel — use `run_in_background=true` on the Bash tool calls.
- Run `make test` and `make check` after each fork or batch of forks completes. Never fix test failures or make check issues yourself. Use `pflow fork-session` to fix tests, and use `code-implementer` subagents in parallel to fix linting issues from make check.

## Key Principles

- The markdown parser produces the same IR dict that JSON did. Everything downstream (validation, compilation, execution) is unchanged.
- Save preserves original markdown content. No IR-to-markdown serialization.
- The planner and repair systems are gated (not removed). Simple if-guards with comments.
- Read the Gotchas section (G1-G9) in the implementation plan carefully — each one will cause a detour if missed.

## Start

Read the 5 specified files completely and identify where to resume from. Then stop and suggest what to do next to the user. Do not start implementing.
