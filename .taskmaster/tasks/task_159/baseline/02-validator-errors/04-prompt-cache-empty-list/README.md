# 04 — `prompt_cache: []` is valid (intentional opt-out)

**Surface**: 02-validator-errors

**Triggers**: Node has `prompt_cache: []` (empty list). Per spec, this is valid
and equivalent to absence — the intentional `review-stranger-summary`-style
isolation pattern.

**Expected behavior**: Workflow validates successfully. `pflow analyze-cache`
produces a normal report (potentially with `cache.unused-chunk` warning since
nothing references the declared chunk). Exit 0.

**Mutation contract**: if `[]` is mistakenly rejected, an intentional opt-out
breaks. The case captures the as-written workflow being accepted; if Task 160
reverses this, the case fails.
