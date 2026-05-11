# 08 — cache.padding-advisory

**Surface**: 04-warning-catalog

**Triggers**: An LLM node starts its `prompt_cache:` subset at a later declared
chunk even though earlier declared chunks are large enough that extending the
subset would clear the advisory savings floor.

**Expected behavior**: Text output recommends extending the node's
`prompt_cache:` list, showing the current subset and suggested padded subset.

**Mutation contract**: if Task 160's padding-stage extraction drops
`cache.padding-advisory`, changes the sensitivity-floor handling, or loses
the suggested subset, this case fails through the recommended action section.
