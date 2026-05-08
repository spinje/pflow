# 01-cache.order-mismatch

Master order `[article, topic]`; node has `prompt_cache: [topic, article]`. Triggers `cache.order-mismatch` (error, blocks run/save). Mutation: order check removed → silent prefix divergence.
