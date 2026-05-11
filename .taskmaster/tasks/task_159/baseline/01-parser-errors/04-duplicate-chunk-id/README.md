# 04 — Duplicate chunk identifier

**Surface**: 01-parser-errors

**Triggers**: `${article}` appears twice as separate chunks in `## Cache`. The
chunk identifier (`article`) collides.

**Expected behavior**: Parse Error; non-zero exit; error message names the
duplicated identifier.

**Mutation contract**: if duplicates are allowed, `prompt_cache: [article]` has
two valid mappings — undefined which prose chunk wins. Silent ambiguity.
