# 01 — Batch + Cache + Prewarm happy path

**Surface**: 13-happy-path-interactions

**Triggers**: A batch node with `prompt_cache: [context]` AND
`prewarm: true`, where BOTH cache scopes are real and above the provider
minimum:

- `${context}` (long reference doc) lands in system blocks via
  `prompt_cache: [context]`.
- `${rubric}` (long scoring instructions) lands in the prompt body as the
  stable prefix before `${item.text}`, captured by `prewarm: true`'s auto
  batch-prefix marker.

`${context}` and `${rubric}` are distinct variables — `${rubric}` is NOT in
`## Cache`, so there's no shadowing. Per DD#11, the two markers are
additive: provider receives one `cache_control` for the system scope and
one for the user-message scope, two distinct breakpoints. Both clear
sonnet 4.5's 1024 min.

**Expected**: NO `cache.batch-prewarm-recommended` (decision is already
made). NO `cache.prewarm-no-prefix` (there IS a substantial static prefix
in the prompt body). NO `cache.batch-prewarm-below-min` (rubric clears
1024). NO `cache.below-min-predicted` (context clears 1024). The analyzer
should treat this as the optimal shape.

**Why this complements surface 04 cases**: surface 04 cases test
suppression rules (low-savings silent, prewarm:false suppresses, etc.).
This case tests the OPPOSITE — the configured-correctly happy path with
BOTH additive markers above the min. Mutation that breaks the
suppression-when-correct logic surfaces here.

**Mutation contract**: if the analyzer starts emitting
`cache.batch-prewarm-recommended`, `cache.batch-prewarm-below-min`, or
`cache.below-min-predicted` on a workflow that has already declared both
markers correctly with content above the provider min, this case fails —
surfacing a regression in the additive-mechanism model.
