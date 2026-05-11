# 07 — JSON error envelope on unknown workflow (ADV)

**Triggers**: `--format=json` on a workflow file that doesn't exist.

**Expected**: stdout contains a parseable JSON envelope:
`{format_version, error: {id, message, suggestion?}}`. Stderr has the human
line in parallel. Pre-fix at commit `60a2eec8` stdout was empty — JSON
consumers got parse-failure.

**Mutation contract**: if the error path stops emitting the JSON envelope to
stdout, agents calling analyze-cache via `--format=json` and JSON-parsing
the result fail with a confusing parser error instead of structured info.
