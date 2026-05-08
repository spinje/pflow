# 02 — Sub-workflow with own `## Cache` (happy path)

**Surface**: 13-happy-path-interactions

**Triggers**: Parent passes `article` to child. Child declares its OWN
`## Cache` block scoped to its own input. Two LLM nodes in the child both
correctly reference `prompt_cache: [article]`.

**Expected**: NO `cache.sub-workflow-cache-undeclared` (child has its own
## Cache). NO `cache.cross-workflow-prose-mismatch` unless the prose
diverges (we don't declare ## Cache in parent here, so cross-workflow
analysis has nothing to compare against). per_call rows for both child
LLM nodes show the cache as declared and used.

**Why this complements surface 04**: surface 04 tests the rejection paths
(child without ## Cache, child with rename); this case tests the
correctly-declared shape that the spec promises is supported by DD#12
("Sub-workflows declare their own `## Cache` block").

**Mutation contract**: if the cross-workflow walker regresses and starts
flagging correctly-declared sub-workflow caches as problematic, this case
fails.
