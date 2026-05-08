# 04 — Parallel batch with prompt_cache (no prewarm)

**Surface**: 13-happy-path-interactions

**Triggers**: A parallel batch with `prompt_cache: [context]` but NO
`prewarm:` decision. The savings_ratio depends on prefix size relative to
dynamic content. The agent should see `cache.batch-prewarm-recommended` if
savings_ratio ≥ 5%.

**Why this case**: tests the interaction between batch + cache + parallel
without prewarm. The lyrics-generator's chorus-chooser pattern has shapes
similar to this. If prewarm-recommendation breaks for parallel batches,
the warning silently disappears.

**Mutation contract**: the captured per_call shape, batch attribution, and
emitted warnings are all under test. A change in batch×cache interaction
will visibly shift the output.
