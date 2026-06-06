# Task 166: Declarative Stateful Loop Primitive

## Description

Extend pflow's existing `loop:` node modifier with first-class **carried state** so that stateful, condition-driven loops (evaluator-optimizer, tournament, iterative refinement, retry-style) are expressible declaratively, reliably, and visualizably — without today's backward-edge / sibling-counter workarounds. The loop stays a node *modifier* (symmetric with `batch:`), gaining an explicit `carry:` (output→input feedback), `inputs:`-as-seed, and `while:`/`until:` polarity keywords.

## Status

done

## Completed

2026-06-05

## Priority

medium

## Problem

Today `loop:` is a do-while over a node's own typed output (`while:` + `max_iterations`) with **no first-class way to carry state across iterations**. To accumulate state (a shrinking contender list, a running best, a draft + feedback), an author must hand-assemble a backward-edge worker/checker and thread the accumulator across *sibling* nodes — verbose, error-prone, and the resulting graph is hard to read. Concretely:

- The "Tournament" pattern is only partially expressible; evaluator-optimizer and validate-fix-style loops require ceremony.
- Blind review of eight candidate syntaxes found the dominant failure mode is **implicit / invisible output→input coupling**, which silently feeds stale state (loop runs wrong or to `max`).
- A single polarity-ambiguous `while:` keyword causes a **silent "runs once and exits" bug** for the most common case (polling): "poll until done" → an author writes `while: done` → `done` is false on the first check → the loop exits immediately, type-checks, runs, and looks plausible. No static check can catch it.

## Solution

Extend the existing `- loop:` modifier (it stays a modifier on a node — workflow or inline — **not** a new `type: loop`) with:

- **`carry:`** — an explicit map `{ body_input: ${loop-node-id.output} }` declaring which body output feeds which body input on the next iteration. Mirrors the shape of `inputs:` (destination key : `${source}` value), so the direction is unambiguous and un-reversible.
- **`inputs:` as the seed** — the node's existing `inputs:` provides round-1 values; `carry:` overrides the carried keys from round 2 onward. **No separate `seed:` field.**
- **`while:` and `until:`** — two distinct, mutually-exclusive condition keywords, each referencing a body's typed bool output. `while: X` continues while X is truthy; `until: X` continues until X is truthy (i.e. while X is falsy). The keyword carries the polarity so the author never mentally negates.
- **Output/condition references use the existing `${loop-node-id.field}` model** — no new `${body}`/`${acc}`/`${item}` reserved word. The loop node's output already equals the body's latest output (verified substrate).
- **Static validation** closes the silent-mismatch holes (typo'd carry output, carried-input-without-seed, while/until misuse).

## Target Syntax

The converged shape (keywords settled; exact validation messages TBD).

**Stateful loop — tournament (carries a shrinking contender list):**

```markdown
### run-rounds
- type: workflow
- workflow: ./judge-round.pflow.md     # input: contenders ; outputs: survivors, more
- inputs:
    contenders: ${initial_lineup}      # round-1 seed (carry overrides round 2+)
- loop:
    carry:
      contenders: ${run-rounds.survivors}   # next round: input `contenders` <- this node's `survivors` output
    while: ${run-rounds.more}                # continue while the body's `more` output is truthy
    max_iterations: 100
```

**No-state loop — poll (carries nothing):**

```markdown
### wait
- type: workflow
- workflow: ./check-status.pflow.md    # input: job_id ; output: pending
- inputs:
    job_id: ${job_id}                  # constant every round
- loop:
    until: ${wait.pending}             # stop when the body's `pending` output is truthy
    max_iterations: 60
```

Notes on the syntax:
- `${run-rounds.X}` / `${wait.X}` reference the **loop node's own latest output** (= the body's
  latest output — the verified self-reference substrate). No `${body}`/`${acc}`/`${item}` reserved
  word. (`${body}` is a low-stakes open alternative — see Implementation Notes.)
- `carry:` mirrors the shape of `inputs:` (destination key : `${source}` value), so the
  output→input direction is unambiguous and un-reversible.
- A **carried** input (a key in `carry:`) takes its round-1 value from `inputs:`; a **constant**
  input (not in `carry:`) is unchanged every round.
- `while:` vs `until:` — exactly one; the keyword carries the polarity so the author never negates.

## Design Decisions

- **Modifier, not a new node type.** `- loop:` stays on a node, symmetric with `batch:`. A `type: loop` would break batch-symmetry, force every loop body to be a sub-workflow file, and add a node type. (A blind design exercise proposed `type: loop` because the designers had no pflow context; rejected on reconciliation with the verified existing modifier model.)
- **Explicit `carry:` over implicit coupling.** Every reviewed implicit option — self-reference-only + `??`, magic `${acc}`, body-I/O name-matching, bare-name binding — was rejected. The #1 reliability risk across all eight candidates was a silent output→input name mismatch; the carry must be *written down* and statically checked.
- **`inputs:` as seed; no separate `seed:`.** Collapses a field — `carry:` already declares which inputs are carried, so a carried input's `inputs:` value is its round-1 value. Cost: the "round-1-only" nature of that value is implicit (surface it via a validation note). 2 of 3 independent designers chose this collapse.
- **`while:` + `until:` (both keywords).** Polarity-in-the-keyword prevents the silent "poll until done → runs once and exits" bug, which no static check can catch. Highest-value single decision.
- **Reuse `${loop-node-id.field}`; no `${body}`/`${acc}`.** Maximally consistent with pflow's universal `${node.field}`; zero new reserved words; uses the verified self-reference substrate. Tradeoff vs a self-documenting `${body}` alias: chose consistency over one new word.
- **`${item}` is NOT reused.** It is batch's per-iteration *input*, injected *into* the body; a loop needs the per-iteration *output*, referenced in the *parent* config. Opposite role — sharing the name would confuse.
- **Logic stays in the body; conditions are field refs only.** No expression language in `${...}` (verified: none exists; `${x > 0}` is illegal). Computed booleans live in the body and are referenced by name.

## Dependencies

None hard — builds on the verified existing loop substrate (see research file).

Adjacent (not blocking): the error/resilience-model work (GitHub issue **spinje/pflow#471** — first-class retry/backoff + a "recovered-cleanly" status). Retry-style loops benefit from both, but neither blocks the other.

## Requirements

### Syntax / parsing
- `carry:` parsed as a map `{ body-input-name: ${...} }` inside the `loop:` block.
- A loop node's `inputs:` provides round-1 values; keys present in `carry:` are overridden from round 2 onward.
- `while:` and `until:` both accepted; **exactly one required**; declaring both (or neither) is a blocking error.
- `carry:`/`inputs:` keys are bare (destination = a body input name); values are `${...}` references.

### Execution semantics
- Do-while: the body runs once, then the condition is evaluated.
- Round 1 body inputs = `inputs:` (all keys). Round N>1 = `inputs:` applied, then `carry:` overrides the carried keys with the previous iteration's referenced output.
- `while: X` re-runs while X is truthy; `until: X` re-runs while X is falsy; both stop at `max_iterations`.
- The loop node's post-loop output = the final iteration's body output, consumable downstream as `${loop-node-id.field}`.
- Works on `workflow`-type bodies (carry → child's declared inputs). Inline-node bodies: see Implementation Notes.

### Validation (reuse the diagnostic engine)
- Each `carry:` value must reference a declared output of the body; each `carry:`/`inputs:` key must be a declared input of the body.
- Every `carry:` key must have a value in `inputs:` (a carried input needs a round-1 value) — else a clear diagnostic.
- `while:`/`until:` must reference a declared **bool** output of the body; raw-string condition sources are rejected (already enforced for `while:`).
- A typo'd or non-existent `carry:` output reference is a parse/validate-time error, **not** a silent stale-state run.

### Consistency
- `loop:` remains a node modifier, symmetric with and mutually exclusive with `batch:` (as today).
- No new reserved template variable; references use `${loop-node-id.field}`.

## Implementation Notes

- **Substrate already exists** (verified — see research file): loop re-entry persists `shared[node_id]` across iterations, clears completion/memo per iteration, and the visit guard caps runaway. `${__iteration__}` exists. `while:` already rejects raw-string conditions. So this is *extending* the modifier, not building a loop engine.
- **Core new behavior — carry-override in re-entry:** before re-running the loop node, compute next inputs = `inputs:`, then apply `carry:` overrides (carried keys ← previous-output refs). Lands in the loop re-entry / per-iteration input-resolution path (`engine.py` ~442–490, `loop_control.py`).
- **`until:`** = the negation of the `while:` truthiness check in `loop_control.evaluate_loop_condition`.
- **Schema:** extend `LOOP_CONFIG_SCHEMA` (`src/pflow/core/ir_schema.py` ~141–175) with `carry`, `until`.
- **Validation:** extend loop validation (`data_flow.py:545`; `template_validation/validator.py:207–263`) for carry + until + exactly-one-of, emitting `Diagnostic` objects (detection is separable from rendering — verified).
- **Inline-body case is under-worked.** For a single inline node body (e.g. loop an `llm` without a sub-workflow), the carry must feed the node's own `- inputs:` / template. Clean for sub-workflow bodies; **spec the inline path before implementing, or scope v1 to sub-workflow bodies.**
- **Open micro-decisions (low stakes):** `${loop-node-id}` vs a `${body}` alias for output refs (chose node-id for consistency); whether `max_iterations` is required (visit guard backstops it anyway); `inputs:` vs `initial:` naming for the seed.

## Verification

- **Tournament** (carries a shrinking list, runs a `judge-round` sub-workflow until one remains) is expressible in one loop node + child — no sibling counter, no backward edge.
- **Poll** (no carried state) stays minimal: `inputs:` + `until:`/`while:` + `max_iterations`.
- **Validate-fix-style** loop expressible cleanly.
- A **typo in a `carry:` output reference** fails at validate time with a clear diagnostic (not a silent run).
- **Polarity:** a poll authored with the correct keyword does not exhibit the "runs once and exits" bug; declaring both `while:` and `until:` errors.
- **Carry-override:** round N>1 inputs reflect the previous iteration's output for carried keys; constant inputs are unchanged.
- **Regression:** existing `loop:` workflows (`while` + `max` only) still validate and run.

## References

- Verified codebase findings: `.taskmaster/tasks/task_166/research/codebase-findings.md`
- Exploration history (how the design was reached): `.taskmaster/tasks/task_166/implementation/progress-log.md`
- Adjacent error-model issue: spinje/pflow#471
- Substrate: `src/pflow/runtime/engine/engine.py` (re-entry ~442–490), `runtime/engine/loop_control.py`, `runtime/engine/instrumentation.py`; schema `src/pflow/core/ir_schema.py` (`LOOP_CONFIG_SCHEMA` ~141–175); validation `src/pflow/core/workflow/data_flow.py:545`, `src/pflow/runtime/template_validation/validator.py:207–263`.
