# Cache-Key Discrepancy Stage

Predicts memo cache keys for LLM nodes and compares them with trace evidence.
The seam between prediction and diagnosis is one map:
`(workflow_path, node_id) -> cache_key | _PREDICTION_SKIPPED`.

## Files

- `predict.py` - cache-key prediction using the runtime planning substrate
  (`compile_workflow`, `plan_node`, `create_planner_shared`). Runtime imports
  stay lazy so dry-run/analyze-cache import paths avoid the LiteLLM startup
  cost until prediction actually runs.
- `diagnose.py` - trace discrepancy attribution. Emits `cache.discrepancy`
  with `chunk_skipped` or `key_mismatch` root-cause context.

## Test API

These underscore-prefixed helpers are stable direct-test surfaces:

- `predict._predict_node_cache_key` - self-contained single-node prediction.
  Production callers use `_predict_cache_keys`; direct tests use this helper
  when they do not want to build a full `cw_result` and `AnalysisContext`.
- `predict._format_dynamic_batches_note` - user-facing note for dynamic
  workflow batches that cannot be statically enumerated.
- `predict._format_fidelity_skip_note` - single wording source for cache
  fidelity skip notes.
- `predict._format_skipped_workflows_note` - aggregated sub-workflow skip note
  formatting.

Other discrepancy internals may still have direct branch tests when their
behavior is not observable through `analyze()` alone. Do not promote those
helpers to production API just because tests import them.
