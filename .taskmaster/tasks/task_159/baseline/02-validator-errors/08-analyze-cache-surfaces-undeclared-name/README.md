# 08 — analyze-cache surfaces undeclared prompt_cache name (ADV — regression for external review fix at commit `2f4e0d5e`)

**Surface**: 02-validator-errors

**Triggers**: Same workflow shape as `02-prompt-cache-undeclared-name`, but
exercised through `pflow analyze-cache` instead of `pflow run`.

**Expected behavior**: `pflow analyze-cache` surfaces the undeclared-name
error in `blocking_errors` because it now runs the same `WorkflowValidator`
pipeline as `pflow run`. The same workflow that `pflow run` rejects must
also be rejected analytically.

**Mutation contract**: if the old cache-only validation adapter is
reintroduced and un-IDed validator diagnostics like
`_make_undeclared_chunk_diagnostic` are filtered out, `analyze-cache` reports
"all clear" on a workflow `pflow run` would reject. This case is the
regression gate for that silent-success class of bug.
