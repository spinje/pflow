---
name: "implement-plan"
description: "This command is for human / machine invocation only. Do not use."
---
Implement an existing implementation plan without shortcuts, keeping the progress log current as you go.

**Resolve inputs from the user's request:**
- Bare task id (`49` / `task_49`) → plan: `.taskmaster/tasks/task_{N}/implementation/implementation-plan.md`
  (if it's an index of per-phase plans, follow it to the scoped phase's file). Context: `task-{N}.md` +
  everything in `starting-context/`. Progress log: `implementation/progress-log.md` (create if missing).
- Explicit paths → use as given; treat extra paths as additional required context.
- Phase scope (`phase 1`, `phases 2-3`) → implement ONLY that scope. If no scope is given, ask before
  implementing the whole plan.

**Before writing any code:**
1. Read every file above in full, and the progress log.
2. Re-verify the plan's load-bearing claims and file:line cites against the current code — plans are
   point-in-time; code is truth. Record real deltas in the progress log.

**While implementing:**
- Don't take shortcuts. Prioritize simplicity of the FINAL code, not how easy it is to get there. When in
  doubt: what would the top 10% of codebases similar to this one implement — has the plan considered it?
- Skipping or altering any plan step requires a clear written rationale in the progress log. Deferring
  something because it's easiest is not a rationale.
- Doing something else is only valid if the plan is unclear, incomplete or contradictory.
- Update the progress log continually as decisions and discoveries happen, not retrospectively.
- Tests ship with the implementation. `make check` must be green before the scope counts as done.

**When the scoped phases are done:** append a dated progress-log entry — key learnings, insights,
deviations from plan with CLEAR reasons (no handwaving) — concise, no fluff. Then STOP and summarize for
review: what was built, what deviated and why, what to verify manually. Do not start the next phase.
Do not commit.
