# 08 — Prose-only cache block (no `${var}`)

**Surface**: 01-parser-errors

**Triggers**: ```cache``` block contains prose only, no `${var}`. Functionally
overlaps with `01-empty-cache-block` (both end up with zero items) but has
non-empty prose, exercising a distinct parser path.

**Expected behavior**: Parse Error citing the missing `${var}`; non-zero exit.

**Mutation contract**: if accepted, the rendered cache content is static prose
with no value substitution — the cache marker has nothing meaningful to bind
to. Silently broken.
