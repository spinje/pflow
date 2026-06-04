# Handoff: Six-pattern stress test → what it says about Task 100

**Date:** 2026-06-03
**Origin:** Ad-hoc question — "which of these six agent-orchestration patterns does pflow
support natively?" — turned into a stress test of pflow's parallel/reduction model.
**Trust boundary:** Conclusions verified against `pflow guide core/branching/batch/sub-workflows`
and the Task 100 spec. The tournament workaround below is reasoned, *not* yet built/run.

## What was tested

Six common multi-agent patterns, mapped onto pflow primitives:

| # | Pattern | Native? | Primitive |
|---|---------|---------|-----------|
| 1 | Classify-And-Act | ✅ Full | classifier node + `- next:` routing |
| 2 | Fanout-And-Synthesize | ✅ Full | `batch parallel:true` → synthesis node |
| 3 | Adversarial Verification | ✅ Full | worker → batch of verifiers |
| 4 | Generate-And-Filter | ✅ Full | batch generate → `code` dedupe + rank |
| 5 | Tournament (bracket) | ⚠️ Partial | static bracket = DAG; dynamic depth = `loop:` + code pairing |
| 6 | Loop Until Done | ✅ Full | `loop:` with `while:` on a typed output |

**5 of 6 map cleanly.** The lone partial (tournament) is the most exotic and least-used —
that reads as validation of pflow's model for agent orchestration, not a hole.

## The finding that matters for Task 100

The tournament friction traces to three boundaries. Two are *intentional* and not gaps:
- No dynamically-growing operation count (keeps runs deterministic) — by design.
- Parallelism only inside `batch`, never across graph paths — by design.

The third is the real one, and it's exactly what Task 100 names:
**reduction/fold over a collection is manual today** (hand-written `code` node).

## Important nuance — Task 100 (linear fold) ≠ what the tournament needs (tree fold)

Reading the Task 100 spec closely: it is a **linear accumulate** —
`acc = f(acc, item)` chained left-to-right via `${accumulator}`, forced sequential,
single scalar output. This cleanly serves the *accumulate* family:
- the image-replacement use case in the spec
- running totals, progressive document edits, sequential state threading

The **tournament is a different shape** — a *tree / per-round* reduction:
take survivors[], pair them `[(0,1),(2,3)…]`, judge each pair **in parallel**, halve the
field, repeat until one remains. That is `loop:` + a `code` pairing node, **not** a linear
`${accumulator}` chain. Linear reduce mode does not directly express it.

**So don't let the tournament pull Task 100's scope toward tree reduction.** They are
adjacent ("the fold family") but distinct. Task 100's value stands on its own (linear
accumulate) and this exercise independently re-confirmed that linear fold is the genuine
gap. Tree reduction has **no observed demand** (no users yet) and the `loop:`+code
workaround covers it — record it as a known model boundary, not a feature.

Likewise, correcting an earlier loose claim from the originating discussion: reduce mode
does **not** meaningfully clean up Generate-And-Filter (#4) either — its dedupe is already
a single `code` node over the full array. Reduce mode's payoff is the linear-accumulate
case specifically.

## Recommendation

- **Keep Task 100 scoped to linear fold** (`mode: "reduce"` + `${accumulator}`) as specced.
  Do not expand it to tree/bracket reduction; do not add a tournament primitive.
- **Signal to watch** that would raise Task 100's priority: users repeatedly reaching for
  the temp-file workaround (spec) or `loop:`+code-pairing to accumulate over a collection.
  That recurring workaround is the observed-demand evidence — tournament is not.

## Pointers

- Spec: `.taskmaster/tasks/task_100/task-100.md`
- Loop primitive (covers tournament's dynamic depth): `pflow guide branching` → Loops
- Batch map mode it extends: `pflow guide batch`; dependency Task 96
