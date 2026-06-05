# Braindump: Task 166 — implementation method & watch-outs

> Tacit residue only. The what/why/target-syntax (`task-166.md`), verified facts
> (`research/codebase-findings.md`), and the journey/principles (`implementation/progress-log.md`)
> are NOT repeated here — read those first. This is the stuff that's only in my head.

## Start here — the sequencing the docs don't spell out

**Step 0: prove the substrate before building anything (~1 hour, de-risks the whole task).**
The research file says the loop self-reference substrate is verified *by code-reading, not by
running it for a non-`while:` param*. So literally write a tiny `.pflow.md` — a `code` node with
`- loop: { while: ${self.<bool>}, max_iterations: 5 }` whose `inputs:` reference its OWN prior
output (`${self.acc ?? 0}`-style) and accumulate — and RUN it on current pflow. If a node's prior
output threads through its own `inputs:` across iterations, the `carry:` override is a thin surface
on proven behavior. If it doesn't, the whole task changes shape. This is the single highest-leverage
hour; everything downstream assumes it passes.

## The real acceptance gate (not just "tests pass")

The actual goal is **a fresh AI agent authors a correct loop on the first try** — that's what the
entire blind-grading exercise was optimizing for. Green unit tests do NOT prove the feature met its
goal. Before merging, reuse the method from the progress log as the gate: hand a fresh
general-purpose agent (no pflow context, only the new guide text) the three cases (tournament /
poll / validate-fix) and measure first-try correctness + which mistakes recur. If agents still trip,
the **syntax** needs adjusting, not the tests.

## Settle the two open micro-decisions the same way — don't bikeshed

`${node-id}` vs `${body}`, and `inputs:` vs `initial:` (both flagged in the spec): resolve by the
blind method, not by argument — give fresh agents both forms and grade authoring reliability. That's
how every contested choice in this design was settled; it's what removed the bikeshedding.

## Implementation watch-outs (sharper than the spec's notes)

- **Carry-resolution ordering is where a silent stale-state bug would hide.** At round N+1's input
  resolution, `shared[loop-node]` must still hold round N's output (it persists — verified) AND
  `carry:` must override `inputs:` for the carried keys. Get the order right: resolve `inputs:`,
  then apply `carry:` overrides, then run. Also confirm the loop-active memo suppression
  (`__loop_active__`, `instrumentation.py:256-276`) doesn't cache carry-resolved inputs and serve
  stale values.
- **`until:` must reuse the existing `while:` validation + runtime path** (typed-bool gate +
  raw-string rejection at `template_validation/validator.py:207-263`, plus `loop_control`), just
  inverted. Do NOT fork a parallel condition pipeline — that's how the two would drift.
- **Don't half-implement inline bodies.** v1 is scoped to sub-workflow bodies on purpose. A
  silently-half-working inline path (carry feeding a node's own `- inputs:`/prompt) is worse than an
  explicit "inline loop bodies not yet supported" error. Decide explicitly; fail loud if unsupported.

## UNEXPLORED / MIGHT MATTER (we did not discuss these)

- **`--only <loop-node>`** runs a single iteration (the loop searcher noted this). Confirm carry
  behaves sanely under it — there's no prior iteration, so nothing should carry. Probably fine; verify.
- **Trace / `pflow report` rendering of carried state.** Loop iterations are currently *derived* by
  counting trace events, not stored. While you're in the engine, consider adding a cheap per-iteration
  trace field for the carried value — pays off for the future React/flow view (Task 155). Not required.
- **`--dry-run` + carry.** The planner walks loop bodies once; confirm carry doesn't make it choke.

## For the next agent

- Do the **Step-0 spike first.** Don't write a line of the feature until the substrate is run-proven.
- The user cares most, in their words, about **simplicity for AI agents** and **"fix the primitive,
  don't flee to code."** When two forms work, pick the one a fresh agent authors correctly first-try
  — not the cleverer one.
- The graders/designers ran on a **smaller model**; the user explicitly said don't treat their output
  as ground truth. Trust the *convergence* and the *polarity finding*; re-derive specifics yourself.
- The error-model work is **issue #471**, independent — keep it out of this task.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm
> you've read and understood by summarizing the key points, then state you're ready to proceed.
