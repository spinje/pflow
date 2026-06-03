# Braindump: testability — the observed need (origin: task 163 harness, 2026-06-03)

Delta only. task-121.md is already well-specced (mocks + record/replay + `pflow test`). Read it
first; this adds just what building the task-163 plan-to-code harness taught.

## The need is now OBSERVED, not theorized
- Task 163 (plan-to-code harness) is the first pflow workflow valuable + expensive enough that
  "just run it" is not a viable test loop: a live run ≈ **$5.69, ~31 min, non-deterministic**.
- With no `pflow test`, the only way to regression-guard its control flow was a hand-rolled
  parallel skeleton of `code` stand-ins: `tests/test_integration/test_plan_to_code_harness.py`.
  **That file is the canary for task 121.**

## Drift is THE motivation — bias the design toward record/replay
- The skeleton RE-IMPLEMENTS the routing in a second file, so it can pass green while the real
  `.pflow.md` breaks (tests/CLAUDE.md item 19, "synthetic fixture matching code").
- So for orchestration regression, **record/replay (test the REAL file with agent nodes replayed)
  >> hand-authored mocks** — hand mocks reproduce the same drift. The spec lists both co-equal;
  the harness experience says replay is the higher-leverage one for control-flow guarding. Keep
  hand mocks for unit-style "what if node X returns Y" cases.

## Lean on the trace/cache substrate — don't build a parallel store
- The trace already records every node's resolved inputs + output; caching already substitutes
  recorded outputs for execution. Replay ≈ "expose existing capability," not a new engine.
- **Reconcile with task 133** (trace/cache storage decision record): the spec's proposed
  `my-workflow.pflow-snapshots/` layout likely duplicates 133's per-node storage. Ride on 133.

## Concrete acceptance bar
- `pflow test` is done enough when it can REPLACE `test_plan_to_code_harness.py`: test the REAL
  `execute-plan.pflow.md` + `implement-chunk.pflow.md` routing (loop / early-exit / review cap /
  cost dial) with agent nodes replayed/mocked — no parallel skeleton, no drift.

## Competitive framing (for prioritization)
- Disproportionately load-bearing for pflow: the differentiator IS deterministic/inspectable
  orchestration, so cheap orchestration-testing is the PAYOFF of the bet (vs opaque-agent tools:
  Claude Code/Cursor/Devin), not a DX nicety.
- But it's a TRUST/RETENTION feature, not demo/sales. Critical the moment workflows are expensive/
  important enough that "just run it" fails — the harness already crossed that line. Lightweight
  replay now (riding task 133) > a full mock DSL.
