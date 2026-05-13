# 22-cache.batch-prewarm-below-min

Minimal fixture for `cache.batch-prewarm-below-min`. Batch node declares
`prewarm: true` but the static prefix before `${item.X}` is well below
Anthropic Sonnet's 1024-token cache minimum.

**Triggers**: `cache.batch-prewarm-below-min` (WARNING).

**Expected**: the analyzer emits one diagnostic naming the prefix-tokens
estimate, the provider minimum, and the provider note ("cache_control
markers will silently no-op at the provider"). The recommended action's
two suggestions name the two remediation paths: grow the prefix, OR
remove `- prewarm: true`.

**Mutation contract**: revert the emission branch in `_per_node_warnings`
(`analyze.py:_per_node_warnings`) so it only fires `cache.prewarm-no-prefix`
on `first == 0`. The diagnostic disappears and the baseline drifts. Or
restore the inner gate `if not evidence.declared_prompt_cache` to also
cover the prewarm path — same drift.

**Why this case can't be replaced by a unit test**: the renderer's
text/JSON output is the agent-facing contract; this baseline locks the
full rendered string (headline, message, suggestions) byte-for-byte so
wording regressions surface at review time.
