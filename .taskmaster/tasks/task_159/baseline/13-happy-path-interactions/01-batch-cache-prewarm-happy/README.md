# 01 — Batch + Cache + Prewarm happy path

**Surface**: 13-happy-path-interactions

**Triggers**: A batch node with `prompt_cache: [context]` AND
`prewarm: true`. The cache prefix is large (long context); batch size 8;
sonnet 4.5 (1024 min, easily cleared).

**Expected**: NO `cache.batch-prewarm-recommended` warning (decision is
already made). NO `cache.prewarm-no-prefix` (there IS a static prefix —
the cached `${context}` chunk). NO `cache.below-min-tokens` (long content
clears 1024). The analyzer should treat this as the optimal shape.

**Why this complements surface 04 cases**: surface 04 cases test
suppression rules (low-savings silent, prewarm:false suppresses, etc.).
This case tests the OPPOSITE — the configured-correctly happy path.
Mutation that breaks the suppression-when-correct logic surfaces here.

**Mutation contract**: if the analyzer starts emitting
`cache.batch-prewarm-recommended` on a workflow that has already declared
`prewarm: true`, this case fails — surfacing a regression in the
"already-optimal" decision logic.
