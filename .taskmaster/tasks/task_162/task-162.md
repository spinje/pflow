# Task 162: Loop Config — Condition-Terminated Iteration

## Description

A `loop:` config block (sibling to `batch:`) that re-runs a single node until a truthiness
condition over its own output goes falsy, capped by `max_iterations`. It gives pflow a `while`
to complement batch's `for-each`, so agents can express "repeat until the work drains" without
hand-rolling a multi-node loop. Implements GitHub issue #445.

## Status

done

## Completed

2026-05-31

## Priority

medium

## Problem

pflow had no first-class way to express condition-terminated iteration ("repeat until drained,
capped at N"). The two existing options each fall short:

- **`batch`** runs a *fixed* count known up front and cannot stop early — wrong for a loop whose
  length is only discovered by running it.
- **A hand-rolled backward-edge loop** works but carries pure ceremony: because a node can't read
  its own previous output, the author must add a separate counter node *and* a checker node, wire
  a backward edge, and seed the counter. The motivating real workflow
  (`examples/agent-orchestration/parallel-planner-review/orchestrate.pflow.md`) needed **three
  nodes** to say "run this cycle until no issues remain, capped at `max_cycles`" — and its own
  prose apologized for the ceremony.

## Solution

One config block on one node:

```markdown
- loop:
    while: ${node.output}     # typed output (list/number/bool); falsy → stop; do-while
    max_iterations: ${cap}    # int or template; cap-hit = INFO advisory + structured marker
```

`${__iteration__}` (1-based) is exposed to the body. `loop:` and `batch:` are mutually exclusive.
The flagship example collapses from 3 nodes to 2.

The **architecture** (engine re-entry vs. the desugar the issue originally proposed), the rejected
alternatives, and the consequences are recorded in the ADR — not duplicated here.

## Scope

- **In:** the `loop:` block, typed-output truthiness condition, `max_iterations` (literal +
  template), `${__iteration__}`, cap-hit advisory + `loop_stopped` marker, sub-workflow loop
  bodies, the cache-staleness guard, dry-run cost modelling, docs + flagship port.
- **Out (v1):** cross-iteration in-store state threading (filesystem/external state is the
  supported channel); `while:` expression operators (the body emits a boolean instead).

## References

The how, the as-built detail, and the decisions live in dedicated artifacts — read those rather
than expecting them restated here:

- **Issue:** [spinje/pflow#445](https://github.com/spinje/pflow/issues/445) — original proposal + acceptance criteria.
- **Architecture decision:** `context/adr/0001-445-loop-engine-reentry.md` — engine re-entry over
  desugar-to-two-nodes; considered options; consequences (incl. the "not zero new runtime" list).
- **Glossary:** `context/CONTEXT.md` → Iteration — the canonical Loop-vs-Batch distinction.
- **The plan (how, phased):** `implementation/implementation-plan.md` — review-hardened design,
  the validation/runtime touch-list, and the verification matrix.
- **As-built (what shipped):** `implementation/progress-log.md` — per-phase notes, deviations from
  the plan, two review rounds + CLI verification, and the dry-run cost-parity follow-up.
- **Key code:** `src/pflow/runtime/engine/loop_control.py` (new); re-entry seam in
  `runtime/engine/engine.py`; validation in `core/workflow/data_flow.py` +
  `runtime/template_validation/validator.py`; planner parity in `execution/plan.py`.
- **Tests:** `tests/test_integration/test_loop_config.py` (engine matrix),
  `tests/test_execution/test_loop_plan.py` (dry-run parity), `tests/test_core/test_loop_validation.py`.
