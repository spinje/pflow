# 23b-cache.batch-prewarm-lower-bound-recommended-text

Text-mode sibling for `23-cache.batch-prewarm-lower-bound-recommended`.
Uses the same workflow shape but renders the default human/agent CLI output
instead of JSON.

**Triggers**: `cache.batch-prewarm-lower-bound-recommended` (WARNING).

**Expected**: the text output shows the Recommended actions entry with the
lower-bound headline, "savings at least" wording, unresolved ref list,
`--report` verification guidance, and the wall-clock trade-off.

**Mutation contract**: remove the dedicated `_format_action_savings` branch for
`cache.batch-prewarm-lower-bound-recommended` or remove the verification
suggestion from the catalog. The JSON case may still pass structurally, but
this text baseline drifts.
