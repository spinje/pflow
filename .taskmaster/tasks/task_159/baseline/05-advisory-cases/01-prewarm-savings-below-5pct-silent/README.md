# 01 — Prewarm savings below 5% — silent skip (ADV)

**Triggers**: Batch where savings_ratio < 5% (mostly dynamic content). Per DD#33, ratio < 5% is a SILENT skip — no `cache.batch-prewarm-recommended` warning emitted.

**Expected**: warnings array does NOT contain `cache.batch-prewarm-recommended`.

**Mutation contract**: if the threshold check is removed or the floor lowered to 0%, this case starts emitting the warning — agents would get noisy advice on workflows where prewarm has no real benefit.
