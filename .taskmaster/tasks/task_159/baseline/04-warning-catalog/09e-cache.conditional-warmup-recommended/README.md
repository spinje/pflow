# 09e-cache.conditional-warmup-recommended

Mixed-size batch trace. Two provider calls carry
`cache_skipped_reason="below_min"` and two do not, so the analyzer recommends a
conditional warmup route instead of treating the whole batch uniformly.
