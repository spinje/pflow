# 09 — Prompt body duplicates / shadows cache content (ADV)

**Surface**: 01-parser-errors (uses analyze-cache surface)

**Triggers**: Node has `prompt_cache: [article]` AND the prompt body literally
duplicates the same `${article}` reference (and the surrounding prose). The
cache block declares the content as "the article being analyzed:"; the prompt
body repeats that prose verbatim.

**Expected behavior**: `pflow analyze-cache` reports `cache.prompt-body-duplicates-cache`
(and possibly `cache.prompt-body-shadows-cache` depending on detector
specifics). The cached value is sent twice; the warning explains how to remove
the duplication.

**Mutation contract**: if either detector regresses to silence, an author who
naively copy-pastes the cached value into the prompt body pays double the
input tokens forever (cached prefix + duplicated body). Silent waste.
