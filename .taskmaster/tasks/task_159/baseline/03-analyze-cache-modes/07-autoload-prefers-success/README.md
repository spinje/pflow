# 07 — auto-load prefers a successful trace over a newer failed one

**Triggers**: two matching 2.x traces seeded in `~/.pflow/debug/` — older
success + newer failed. Auto-load (no `--from-trace`, no `--no-trace-autoload`)
must rank success over newer-failed.

**Expected**:
- The older successful trace is loaded (`trace_path` reflects the success
  filename; `Trace:` header line shows `(success, recorded 2026-05-08 15:32)`).
- A Notes entry names BOTH files: `Skipped newer trace
  workflow-trace-…-163000.json (failed run) in favor of
  workflow-trace-…-153200.json (success). Pass --from-trace <path> to override.`
- Trace-driven cost figures appear (success trace has valid evidence).

**Mutation contract**: revert the success-preference branch in
`_autoload_trace` (`analyze.py`) → the newer failed trace wins → the Notes
entry vanishes → cold-reader test fails to find the "Skipped newer trace"
line.
