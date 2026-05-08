# 06 — `--no-trace-autoload` opts out even when a matching trace exists

**Triggers**: a matching 2.1.0 trace IS seeded in `~/.pflow/debug/`, but the
flag suppresses auto-load.

**Expected**: confidence `low_no_data` (or `medium_from_memo` if memo cache
fires; in this clean HOME it should be low); `trace_path: null` in JSON; no
trace-driven discrepancies.

**Mutation contract**: if the flag stops opting out, agents who explicitly ask
"don't load my history" silently get history-tainted output — exactly the
opt-out the spec promises (DD#34).
