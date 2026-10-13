# 06 twin — the trace 06 seeds IS one auto-load reads

**Triggers**: the same matching trace as `06-no-trace-autoload`, without `--no-trace-autoload`.

**Expected**: the analysis names the seeded trace (`Trace: workflow-trace-<HASH>-smoke-with-cache.seeded-run-<TIMESTAMP>.json`).

**Mutation contract**: without this twin, 06 passes for free whenever the seeded trace is invisible to
auto-load (a wrong hash, a pre-185 name) — it would no longer prove that the flag suppresses a real match.
