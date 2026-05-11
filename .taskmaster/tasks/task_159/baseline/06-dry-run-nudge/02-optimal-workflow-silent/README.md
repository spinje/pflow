# 02 — optimal workflow silent

**Surface**: 06-dry-run-nudge

**Triggers**: `pflow <workflow> --dry-run` plans a workflow that already has a
cacheable batch LLM node with `## Cache`, matching `prompt_cache:`, and
`prewarm: true`.

**Expected behavior**: The dry-run plan renders normally and does not emit a
prompt-cache opportunity nudge. An already-optimal workflow should stay quiet.

**Mutation contract**: if the dry-run summary starts emitting noisy
`cache.opportunities-available` diagnostics for workflows with no rendered
cache recommendations, this case fails through stdout drift.
