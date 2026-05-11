# 01 — prompt_cache out of declaration order

**Surface**: 02-validator-errors

**Triggers**: `## Cache` declares `[article, topic]`; node has
`prompt_cache: [topic, article]`. Spec § "Strict Order Validation" requires a
hard error.

**Expected behavior**: `pflow run` exits non-zero BEFORE making any LLM call.
Error carries the `cache.order-mismatch` warning ID, shows expected vs actual
ordering, includes a paste-ready fix hint, and a `pflow guide caching`
cross-reference.

**Mutation contract**: if order checking is removed or weakened, a node's
prompt_cache renders in user-declared order — silent cache prefix divergence
between calls. The `cache.order-mismatch` ID + the `expected: ... you wrote:`
template are the contract for the error message; renderer drift breaks
agent parsers that key on those literal labels.
