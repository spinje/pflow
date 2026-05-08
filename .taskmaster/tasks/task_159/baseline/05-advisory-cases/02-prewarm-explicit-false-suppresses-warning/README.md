# 02 — `prewarm: false` suppresses the warning

**Triggers**: Batch with explicit `prewarm: false`, regardless of savings_ratio.

**Expected**: warnings array does NOT contain `cache.batch-prewarm-recommended`. Author has already made the decision; the analyzer respects it.

**Mutation contract**: if the suppression is removed, agents who deliberately opt out get spammed with a warning they already addressed.
