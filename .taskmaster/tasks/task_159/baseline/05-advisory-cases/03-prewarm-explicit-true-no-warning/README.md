# 03 — `prewarm: true` no warning, marker active

**Triggers**: Batch with explicit `prewarm: true` and adequate static prefix.

**Expected**: NO `cache.batch-prewarm-recommended` (decision made). The cache_control marker is inserted at runtime (verify via trace if available; this case captures only the analyzer's view).

**Mutation contract**: if the suppression breaks, agents who already set `prewarm: true` get a redundant warning telling them to do the thing they already did.
