# 24-cache.shared-context-undeclared-conditional

Minimal fixture for `cache.shared-context-undeclared-conditional`. Three LLM
nodes share `${article}`, but the CLI value is a smoke-test placeholder below
the provider cache minimum.

**Triggers**: `cache.shared-context-undeclared-conditional` (INFO).

**Expected**: the analyzer emits a conditional recommendation, no suggested
`## Cache` block, and per-call `below provider min` notes.

**Mutation contract**: remove the below-threshold branch in
`analyze.py:_populate_suggested_blocks`. The diagnostic disappears and this
baseline drifts.

