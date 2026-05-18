# 02 — optimal workflow silent

**Surface**: 06-dry-run-nudge

**Triggers**: `pflow <workflow> --dry-run` plans a workflow that already has a
cacheable batch LLM node with TWO independent cache mechanisms both above the
provider minimum:

- `## Cache` + `prompt_cache: [context]` — the reference document goes to
  system blocks, cached across calls.
- `prewarm: true` + a long `${rubric}` in the prompt body before the first
  per-item ref — the rubric goes to a user-message stable prefix, cached
  independently by the auto batch-prefix marker.

The two scopes are additive (DD#11): both can fire in one call. Both must
clear the provider minimum (Sonnet 4.5 = 1024) for runtime to emit the
marker, which is why the rubric is substantial — a tiny user-message prefix
would trip `cache.batch-prewarm-below-min` and prove the workflow isn't
actually optimal.

**Expected behavior**: The dry-run plan renders normally and does not emit a
prompt-cache opportunity nudge. An already-optimal workflow should stay quiet.

**Mutation contract**: if the dry-run summary starts emitting noisy
`cache.opportunities-available` diagnostics for workflows with no rendered
cache recommendations, this case fails through stdout drift. Also fails if
the analyzer regresses on the additive-mechanism model and treats
`prompt_cache:` + `prewarm: true` as redundant when both clear the min.
