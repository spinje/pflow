# 01 — partial trace analyze-cache

**Surface**: 15-run-flag-interactions

**Triggers**: `pflow analyze-cache --from-trace` receives a production-shaped
failed trace where one LLM node executed, a downstream shell node failed, and a
later static LLM node never ran.

**Expected behavior**: Text output frames the evidence as a truncated executed
subset, labels costs as executed-trace costs, suppresses trace-dependent
optimization recommendations, and shows only executed rows by default.

**Mutation contract**: if truncated traces are treated like complete traces, or
if recommendations leak from unexecuted rows, this case fails through the
header, summary note, or per-call section drift.
