# Braindump: how this task was born (short, tailored)

task-171.md says WHAT; this says how much to trust it and what was never decided.

## Trust calibration — read this first

**This spec is a carve, not a grilled design.** It was distilled (2026-06-12) from Task 125's
durable phase + session insights, with NO dedicated codebase verification pass — unlike
task-125.md and task-164.md, whose claims carry verified `file:line` refs. Treat every
mechanism claim here as "ASSUMED from the 125 spec"; re-verify against code at start. And by
the time you read this, Task 164's task-review will exist — **read it before this spec's
Implementation Notes**; the substrate's real shape beats my predictions.

## Assertions of mine the user never confirmed

- ASSUMPTION: **"one restore reader, two state sources"** (164 reads a sanitized trace, this
  task reads its own faithful checkpoint file; both feed one seed path). I'm ~85% sure it's
  the right shape; it's my design call, echoed into 164's Dependencies, but no human approved
  it. If 164 implemented restore differently, follow 164.
- ASSUMPTION: the **distinct exit code for "paused, token emitted"** requirement — I invented
  it (agent-UX reasoning: callers must distinguish paused from failed). Plausible, unreviewed.
- UNDECIDED (the user never weighed in): **token security** (sign/encrypt vs trust local fs)
  and the **`pflow resume` CLI surface collision** with 164. Both are flagged in the spec as
  open — they are genuinely open, not rhetorically open. Get user decisions.

## Context that shaped the scope

- The split exists because of the user's one-big-PR-per-task convention; this task must stay
  a THIN trigger over 164's substrate. The spec's "design smell" warning (a parallel
  serialization/walk-entry path growing here) is the failure mode I'd bet on — the session
  that created this task spent a week's effort un-forking exactly that kind of duplication
  (issue #504 / PR #505).
- CONSIDER: **this task is what unlocks gates for the MCP server** (MCP can't prompt; 125
  just fails loudly there). The token needs to surface in `execution_service`'s structured
  result, not only CLI stdout — nobody has designed that surface.

> **Note to next agent**: Read this fully, then 164's task-review, then task-171.md. Confirm
> by summarizing key points before proceeding.
