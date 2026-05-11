# 07 — Unused cache chunk

**Surface**: 02-validator-errors

**Triggers**: `## Cache` declares `[article, topic]`. Only one node references
`article` via `prompt_cache:`; `topic` is declared but unused.

**Expected behavior**: `cache.unused-chunk` warning fires (severity warning,
not error — does NOT block run). Identifies the unused chunk by name.

**Mutation contract**: if the warning is dropped, dead-code chunks accumulate
and agents have no signal to clean them up. The warning's `source_line`
context (per the recent `_make_unused_chunk_diagnostic` fix in commit
`f91814be`) is part of the contract — drift here is what the
`review-validation-consistency` agent caught earlier in this branch.
