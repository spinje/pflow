# 02 — report cache telemetry

**Surface**: 15-run-flag-interactions

**Triggers**: `pflow report` renders the committed live Gemini translation
trace, which includes the cache-rendered system block and provider cache
telemetry recorded by pflow.

**Expected behavior**: The report node page contains `## Cached System` before
`## Prompt`, plus a `## Cache telemetry` section with cache write/read counts
and the cache key. The command prints a shortened excerpt of the generated
report so the baseline stays readable while still using the full committed
trace. The wording should describe behavior without exposing memo or analyzer
internals.

**Mutation contract**: if trace recording or report generation drops
`llm_system`, omits cache telemetry, or reorders telemetry before the cached
system/prompt context, the captured markdown drifts.
