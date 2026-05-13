# 09 — auto-load rejection names the rejected trace file

**Triggers**: an auto-loaded trace's root LLM events don't match the current
IR's root LLM node IDs (the workflow was edited after the trace was
recorded). The post-row-build gate at `analyze.py:683` fires.

**Expected**:
- `trace_path: null` in JSON (the trace was rejected; greenfield rebuild).
- A Notes entry NAMES the rejected file + its final_status: `Auto-loaded
  trace workflow-trace-…-153200.json (success) did not cover all root LLM
  nodes …. Ignored for workflow-wide cache analysis. Pass --from-trace
  <path> to inspect a specific trace anyway.`
- No `Trace:` header line (no trace ended up loaded).

**Mutation contract**: revert `_format_rejection_note` to the pre-Bug-1
wording → filename + status disappear from the Notes line → cold-reader
test fails to find the filename.
