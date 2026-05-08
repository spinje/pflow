# 12-cache.discrepancy — TODO

**Status**: not yet implemented in this baseline.

**Trigger**: requires a recorded trace where the analyzer's predicted memo
config-hash diverges from the actual `event["cache_key"]` written by the
engine. Either (a) trace from a workflow whose IR was edited between runs,
or (b) trace from a workflow with a known prediction-vs-actual gap.

**Implementing agent for surfaces 06+**: extend by recording a workflow run,
editing the IR, recording a second run, then `analyze-cache --from-trace
<second-trace>` to surface the discrepancy.
