# 06 — Cache content below provider minimum

**Surface**: 02-validator-errors

**Triggers**: `## Cache` declares a chunk that resolves to a tiny string (less
than the provider's minimum cacheable token count — 1024 for sonnet 4.5).

**Expected behavior**: `pflow analyze-cache` emits `cache.below-min-tokens`
warning. Workflow is otherwise valid; exit 0. The warning explains that
markers will silently no-op at the provider — agent-actionable, points at the
fix (consolidate / pad / accept).

**Mutation contract**: if the warning is dropped, an author with a small chunk
ships caching that silently never fires at the provider — exactly the failure
mode this warning was added to surface.
