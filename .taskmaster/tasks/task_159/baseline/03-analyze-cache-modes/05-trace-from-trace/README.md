# 05 — Trace mode via explicit `--from-trace`

**Triggers**: `--from-trace` pointed at a real recorded 2.1.0 trace
(`_shared/fixtures/sample-2.1.0-trace.json`) for the smoke-with-cache workflow.

**Expected**: confidence label `high_from_trace`; per-call `data_source: trace`;
real cache_creation/cache_read tokens visible in the per-call report.

**Mutation contract**: locks trace-mode end-to-end. Drift in trace ingestion,
data_source label, or confidence aggregation breaks here.
