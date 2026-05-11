# 04 — Steady-state mode (JSON)

**Triggers**: same workflow as `03-steady-state-text`, --format=json.

**Expected**: full JSON shape including `summary`, `per_node_thresholds`,
`per_call`, `warnings`, `recommended_actions`. `format_version: "4.0"` first
key. Empty arrays present (not omitted) per the JSON contract.

**Mutation contract**: lock the full agent-facing JSON shape. Any new
top-level field needs to flow into here without breaking dispatch.
