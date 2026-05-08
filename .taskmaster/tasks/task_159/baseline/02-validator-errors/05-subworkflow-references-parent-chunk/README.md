# 05 — Sub-workflow's prompt_cache references parent chunk by name (ADV)

**Surface**: 02-validator-errors

**Triggers**: Parent workflow declares `## Cache: [article]`. Sub-workflow at
`sub/child.pflow.md` has an LLM node with `prompt_cache: [article]` but does
NOT declare its own `## Cache`. Per spec DD#12 each workflow declares its own
cache; cross-workflow chunk reference by name is invalid.

**Expected behavior**: Validation rejects when running the parent (recursive
sub-workflow validation). Either an undeclared-name error in the child OR a
missing-`## Cache`-block error.

**Mutation contract**: if validation fails to walk into sub-workflows or
silently treats parent's chunk as visible to children, an author can ship
workflows that *appear* to share cache across boundaries — but at runtime the
child has no `## Cache` to render from. The cache marker is placed on empty
content; cache writes silently miss; debugging takes hours. Spec DD#12 calls
out cross-workflow incidental sharing as byte-level only, never name-level.
