# 08 — auto-load discloses when only failed traces exist

**Triggers**: one matching 2.x trace with `final_status=failed`. No
`--from-trace`, no `--no-trace-autoload`. Auto-load has no successful
candidate to prefer; it picks the failed trace + emits a disclosure Notes
line.

**Expected**:
- The failed trace is loaded (`Trace:` header line shows `(failed, recorded
  …)`).
- A Notes entry says `Auto-loaded
  workflow-trace-…-163000.json (failed run); no successful trace exists for
  this workflow. Trace-dependent recommendations may be suppressed. Re-run
  the workflow to record a successful trace, or pass --from-trace <path> to
  use a specific trace.`
- Downstream truncated-trace suppression behaves correctly (some advisories
  filtered).

**Mutation contract**: delete the failed-tier disclosure branch in
`_autoload_trace` → Notes entry vanishes → agent sees the failed-trace
header but has no signal that the trace was the only candidate.
