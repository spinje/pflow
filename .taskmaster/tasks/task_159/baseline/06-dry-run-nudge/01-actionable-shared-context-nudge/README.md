# 01 — actionable shared context nudge

**Surface**: 06-dry-run-nudge

**Triggers**: `pflow <workflow> --dry-run` plans a workflow where three LLM
nodes repeat the same long `${article}` value in their prompts, with no
`## Cache` declaration.

**Expected behavior**: The dry-run plan renders normally and ends with a
provider prompt-cache nudge that tells the agent a cache design opportunity is
available and points to `pflow analyze-cache` for the concrete edit.

**Mutation contract**: if dry-run stops running the cache summary, or if the
dry-run nudge count diverges from the analyzer's rendered opportunities, this
case fails through the missing or changed `cache.opportunities-available`
footer.
