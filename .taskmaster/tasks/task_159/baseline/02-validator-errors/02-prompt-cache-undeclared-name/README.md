# 02 — prompt_cache references undeclared chunk

**Surface**: 02-validator-errors

**Triggers**: Node has `prompt_cache: [typo]`; `## Cache` declares only
`[article]`. Reference doesn't resolve.

**Expected behavior**: `pflow run` exits non-zero before any LLM call. The
error names the undeclared identifier and (ideally) suggests near matches via
the `find_similar_items` "Did you mean?" mechanism.

**Mutation contract**: if validation skips this check, the rendered
`prompt_cache` for the node is silently empty (no chunk matches `typo`),
producing a `cache_control` marker with no content — silent provider no-op
billed at cache-write rate.
