# 03 — Gemini translation (live recording)

**Surface**: 10-live-recordings (per PLAN.md §6.J)

**Triggers**: Two LLM calls sharing a `## Cache` chunk on
`gemini/gemini-2.5-flash`. First call writes cache; second reads
within the same run.

**Recording prerequisite**: `GEMINI_API_KEY` set in env. Recording is
a one-time operation; subsequent `verify.sh` runs use the committed
trace fixture at `_shared/fixtures/live-gemini-translation.trace.json`.

**Recording command** (run once with API key set):

```bash
cd /Users/andfal/projects/pflow-feat-prompt-caching
export BASELINE_DIR="$(pwd)/.taskmaster/tasks/task_159/baseline"
export BASELINE_CASE_DIR="$BASELINE_DIR/10-live-recordings/03-gemini-translation"
export BASELINE_HOME="$BASELINE_CASE_DIR/.run-home"
rm -rf "$BASELINE_HOME"
mkdir -p "$BASELINE_HOME/.pflow/debug"

HOME="$BASELINE_HOME" uv run pflow run \
  "$BASELINE_CASE_DIR/workflow.pflow.md" \
  context="$(cat $BASELINE_DIR/_shared/long-stable-text.txt)"

# Locate produced trace and copy to fixtures
trace=$(ls -1t $BASELINE_HOME/.pflow/debug/*.json | head -1)
cp "$trace" "$BASELINE_DIR/_shared/fixtures/live-gemini-translation.trace.json"
echo "Recorded trace at: $BASELINE_DIR/_shared/fixtures/live-gemini-translation.trace.json"
```

**Inspection checkpoint** (before running run-case.sh):
- Open the recorded trace JSON
- Verify event 1 has `cache_creation_input_tokens > 0` (or 0 with
  caveat per Gemini telemetry)
- Verify event 2 has `cache_read_input_tokens > 0` — this is the
  load-bearing signal that Gemini's `cachedContents` translation
  actually fired

**Expected behavior** (after recording + harness): `pflow analyze-cache`
on the recorded trace shows:
- `Confidence: high_from_trace (2 of 2 nodes)`
- Per-call `data_source: "trace"`, `src=high` in text rendering
- `Actually paid (trace)` populated
- `Cost on rerun (within TTL)` projected from `cache_read_input_tokens`

**Mutation contract**: if the LiteLLM `cache_control` →
`cachedContents` translation regresses, this case fails because
`cache_read_input_tokens == 0` on call 2 — meaning Gemini's explicit
cache didn't fire. The captured analyze-cache output would lose its
`high_from_trace` confidence label and per-call `src=high` rows.

**Cost estimate**: ~$0.001 per recording (gemini-2.5-flash, ~7500
input tokens × 2 calls + ~400 output tokens). Re-record only when
LiteLLM's cache-translation behavior changes or trace format bumps.
