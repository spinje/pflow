# 12 — cache.discrepancy

**Surface**: 04-warning-catalog

**Triggers**: `pflow analyze-cache --from-trace` receives a 2.x trace whose
LLM event has cache telemetry and a memo cache key that differs from the key
the current workflow planner predicts for the same node.

**Expected behavior**: Text output surfaces a `cache.discrepancy` recommended
action in plain English: the analyzer predicted a hit, the trace read 0%, and
the likely root cause is that upstream bytes changed between the prediction
and the traced run. The Notes section must not expose planner internals.

**Mutation contract**: if Task 160 breaks the moved prediction/diagnosis path,
or drops key-mismatch discrepancies while refactoring `predict.py` /
`diagnose.py`, this case fails because the rendered discrepancy action
disappears or changes shape.
