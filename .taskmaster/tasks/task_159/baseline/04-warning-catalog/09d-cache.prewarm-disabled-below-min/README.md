# 09d-cache.prewarm-disabled-below-min

Trace-backed replay for workflow-entry prewarm disable evidence. The trace
records `prewarm_disabled_reason="below_min"` and a catalog-backed warning so
`analyze-cache --from-trace` exposes `cache.prewarm-disabled-below-min`.
