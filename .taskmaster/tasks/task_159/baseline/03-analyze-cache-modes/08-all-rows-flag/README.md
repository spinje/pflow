# 08 — `--all-rows` shows every node

**Triggers**: same workflow as `03-steady-state-text` plus `--all-rows`.

**Expected**: per-call cache report includes EVERY LLM node (no
"Hidden: N nodes at ≥80%..." summary line).

**Mutation contract**: locks the `--all-rows` toggle. If the default-hide
heuristic regresses or the flag gets dropped, this case fails.
