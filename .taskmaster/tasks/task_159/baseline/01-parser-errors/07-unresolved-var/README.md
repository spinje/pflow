# 07 — Unresolved `${var}` in cache

**Surface**: 01-parser-errors

**Triggers**: `## Cache` references `${nonexistent}` which is neither an input
nor an upstream node output.

**Expected behavior**: Reference-resolution error; non-zero exit; error names
the unresolved identifier and (ideally) suggests valid candidates.

**Mutation contract**: if the resolver silently treats unknown refs as empty
string or skips them, `prompt_cache: [nonexistent]` would render as empty
content and the cache_control marker would be placed on nothing — silent
no-op.
