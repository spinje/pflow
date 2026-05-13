# 23-cache.batch-prewarm-lower-bound-recommended

Minimal fixture for `cache.batch-prewarm-lower-bound-recommended`. Batch node
has no explicit `prewarm` decision. The prompt prefix before `${item.X}` has a
large measurable literal section above Anthropic Sonnet's 1024-token minimum,
plus an unresolved optional upstream ref that prevents confident exact
measurement.

**Triggers**: `cache.batch-prewarm-lower-bound-recommended` (WARNING).

**Expected**: the analyzer emits one lower-bound prewarm advisory with "at
least" savings wording, lists `context.detail` as unresolved, and tells the
agent to verify with `--report` before adding `prewarm: true`.

**Mutation contract**: restore the old exact-or-nothing
`prefix_tokens is None -> return []` gate in
`analyze.py:_batch_prewarm_recommendations`. The diagnostic disappears and the
baseline drifts.

**Why this case can't be replaced by a unit test**: the renderer's text/JSON
output is the agent-facing contract; this baseline locks the full JSON action
shape, including the lower-bound savings field and verification wording.
