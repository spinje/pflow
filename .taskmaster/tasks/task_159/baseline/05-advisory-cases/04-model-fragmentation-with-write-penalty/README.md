# 04 — Model fragmentation co-emits with first-call-write-penalty

**Triggers**: 2 nodes share `prompt_cache: [article]` but use different models (sonnet vs haiku) AND each model has only one cache-declaring call. Both `cache.heterogeneous-models-fragment-cache` AND `cache.first-call-write-penalty` are expected to fire.

**Mutation contract**: locks the co-emission contract. If the cohort-key fix at commit `ea5546ac` regresses, savings would be over-counted in exactly the scenario this warning describes.
