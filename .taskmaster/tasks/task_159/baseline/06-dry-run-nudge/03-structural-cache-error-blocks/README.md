# 03 — structural cache error blocks

**Surface**: 06-dry-run-nudge

**Triggers**: `pflow <workflow> --dry-run` receives a workflow whose
`prompt_cache:` order does not match the `## Cache` declaration order.

**Expected behavior**: Dry-run exits non-zero with the cache-order diagnostic.
It must not render an execution plan, because the workflow is structurally
invalid and would fail before running.

**Mutation contract**: if dry-run bypasses provider prompt-cache validation or
turns cache structural errors into advisory-only output, this case fails
because a dry-run plan appears instead of the `cache.order-mismatch`
diagnostic.
