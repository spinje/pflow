# 05 — Gemini lyrics-generator (live recording)

**Surface**: 10-live-recordings (extension beyond PLAN.md §6.J's 4 cases)

**Triggers**: Full lyrics-generator workflow (25 LLM nodes, 3 dynamic
batch nodes, 17 sub-workflow files, 3-level deep) executed end-to-end
on `gemini/gemini-2.5-flash` with raw-text source input.

**Why this case exists**: PLAN.md §6.J's 4 live-recording cases all
target small smoke workflows (2-4 nodes). Surface 12's lyrics-generator
captures are static analyze-cache only — no real trace. This case
fills the "real trace on the load-bearing real-world workflow" gap
and is the regression oracle for trace-mode rendering at scale.

**Recording prerequisites**:
- `GEMINI_API_KEY` set (from `~/.pflow/settings.json`)
- `pflow settings llm set-default gemini/gemini-2.5-flash`
- Recording uses real HOME (not isolated) so the user's MCP and Gemini
  config is available. The trace is then committed to the repo and the
  case's command.sh uses `--from-trace` against the committed fixture.

**Recording invariants**:
- Source: a 3KB excerpt of `_shared/long-stable-text.txt` (committed
  fixture, deterministic content)
- Workflow generates 4 songs (default concept-judging picks top 4)
- ~80-90 LLM calls, ~$1-3 cost, ~10-30 min wall clock

**Expected behavior** after recording: `pflow analyze-cache --from-trace`
shows:
- `Confidence: high_from_trace (25 of 25 nodes)`
- `actually_paid_usd` populated from real Gemini cost data
- 3-level cross-workflow trace attribution
- Per-call rows with `data_source: "trace"` for executed nodes
- Dynamic review sub-workflow rows attributed to their concrete child
  workflows, not collapsed under the batch parent
- `cache.discrepancy` warnings if any TTLs expired (5-min TTL with
  10-30min wall clock = likely)

**Mutation contract**: this case captures the analyzer's behavior on
a real production-shape trace. If Task 160's refactor regresses
trace-mode rendering on:
- Multi-level nested batches
- Per-batch-item cost rollup
- `actually_paid_usd` from real provider responses
- Cross-workflow boundary attribution

...this case will fail diff. The captured fixture is the closest thing
the baseline has to "what an actual production user sees."

**Cost estimate**: ~$1-3 per recording (gemini-2.5-flash). Re-record
only when LiteLLM's cache-translation behavior changes, trace format
bumps, or the lyrics-generator workflow itself is updated.

**Recording log**: see `.run-log.md` (committed) for the actual
elapsed time, cost, and any anomalies during this recording.

**Fixture minimization**: the committed trace fixture is generated from
the raw live trace with `minimize-trace-fixture.py` in this directory.
The minimizer removes duplicate prompt/system/input echoes while preserving
the analyzer canaries this case needs: 25/25 executed LLM rows, separate
dynamic review workflow attribution, and concrete cross-workflow
`could_cache` projections such as `review-rhyme`.
