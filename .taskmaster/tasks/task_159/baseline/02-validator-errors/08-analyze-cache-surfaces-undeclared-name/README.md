# 08 — analyze-cache surfaces undeclared prompt_cache name (ADV — regression for external review fix at commit `2f4e0d5e`)

**Surface**: 02-validator-errors

**Triggers**: Same workflow shape as `02-prompt-cache-undeclared-name`, but
exercised through `pflow analyze-cache` instead of `pflow run`.

**Expected behavior**: `pflow analyze-cache` surfaces the undeclared-name
error in `blocking_errors` (per the external review fix that taught
`_cache_validator_findings` to filter via path-prefix instead of catalog
membership only). The same workflow that `pflow run` rejects must also be
rejected analytically.

**Mutation contract**: if the catalog-membership filter is reintroduced
(filtering OUT un-IDed validator diagnostics like
`_make_undeclared_chunk_diagnostic`), `analyze-cache` reports "all clear" on
a workflow `pflow run` would reject — the silent-success class of bug the
external review specifically caught. This case is the regression gate for
that fix.
