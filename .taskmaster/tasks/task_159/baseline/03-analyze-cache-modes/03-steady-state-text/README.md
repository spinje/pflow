# 03 — Steady-state mode (text)

**Triggers**: workflow with `## Cache` correctly declared — uses
`examples/core/prompt-caching.pflow.md` directly so the case doubles as the
end-to-end UX baseline for the reference example.

**Expected**: report shows declared cache; emits `cache.below-min-predicted`
because resolved values are tiny in greenfield (no `article=` data).

**Mutation contract**: locks the steady-state UX. Section ordering, label
text, "Notes" suffix all part of the contract.
