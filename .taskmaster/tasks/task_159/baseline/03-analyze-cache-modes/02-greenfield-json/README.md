# 02 — Greenfield mode (JSON)

**Triggers**: same workflow as `01-greenfield-text`, --format=json.

**Expected**: JSON document with `format_version: "4.0"` as the FIRST key,
`warnings[]` includes `cache.shared-context-undeclared`, `suggested_blocks[]`
populated.

**Mutation contract**: `format_version` first-key invariant is the agent
contract — drift here breaks JSON consumers that assert position. The
re-add at commit `60a2eec8` (after a previous removal) was load-bearing;
this case is the regression gate.
