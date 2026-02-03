# Task 107: Implement Markdown Workflow Format

You are implementing Task 107 — replacing JSON with markdown (`.pflow.md`) as the only workflow file format for pflow.

## Required Reading (in order)

Read these files completely before writing any code:

1. `.taskmaster/tasks/task_107/task-107.md` — task overview, scope, verification criteria
2. `.taskmaster/tasks/task_107/starting-context/format-specification.md` — complete format design (27 decisions, parsing rules, code block mapping, integration points). **The format is settled. Don't redesign it.**
3. `.taskmaster/tasks/task_107/implementation/implementation-plan.md` — phased implementation plan with settled decisions, gotchas, file-by-file changes, fork points
4. `.taskmaster/tasks/task_107/implementation/progress-tracking.md` — progress log process (you are the main agent)

## Process

- Follow the implementation plan phase by phase. Do not skip ahead.
- Write your progress log to `.taskmaster/tasks/task_107/implementation/progress-log.md` following the format in the progress-tracking document.
- Write tests as you code (test-as-you-go), not as a separate step.
- At the Phase 2.9 smoke test gate, verify everything works before proceeding to Phase 3.
- At the Phase 3.F fork point, use `pflow fork-session` to parallelize work per the fork plan. Follow the fork invocation process in `progress-tracking.md`.
- Run `make test` and `make check` before considering any phase complete.

## Key Principles

- The markdown parser produces the same IR dict that JSON did. Everything downstream (validation, compilation, execution) is unchanged.
- Save preserves original markdown content. No IR-to-markdown serialization.
- The planner and repair systems are gated (not removed). Simple if-guards with comments.
- Read the Gotchas section (G1-G9) in the implementation plan carefully — each one will cause a detour if missed.

## Start

After reading all four documents, begin with Phase 0. Log your first progress entry before writing code.
