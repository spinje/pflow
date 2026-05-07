# Task 159 Fix Brief 01 — Cost Semantics and Negative "Savings"

Status: research handoff, not an implementation plan
Prepared: 2026-05-07
Source verification report: `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`
Session addendum: `scratchpads/task159-fix-briefs/01-cost-semantics-session-research-addendum.md`

## Purpose

This brief captures what is currently known about misleading or impossible
cost/savings output in `pflow analyze-cache`, `--dry-run`, and related cache
recommendation surfaces.

The next agent's job is **not** to mechanically apply the smallest patch. This
is a research task that should become implementation only after the agent has
read the relevant code, reproduced the issue, understood the calculation model,
and discussed material design choices with the user.

Prefer simplicity of the final code over ease of patching. Ask: what would the
top 10% of small Python CLI/library codebases do to make this domain model
obvious, honest, and easy for future agents to extend?

There are no external users of `analyze-cache` yet. The analyzer exists only on
this branch. Backwards compatibility for current analyzer JSON fields is not a
constraint. Clear, correct semantics beat compatibility shims.

## Findings Covered

Primary:

- Final verification Finding 2: analyzer emits impossible negative savings
  percentages.
- Final verification Finding 12: dry-run/analyzer actions can render
  negative-signed dollar amounts in savings language.

Related and likely overlapping:

- Finding 4: partial `--only` trace analysis produces misleading savings
  projections and confidence claims.
- Finding 5: below-threshold suggested cache blocks can still appear as
  actionable edits even when provider cache will not fire.

Do not assume these all share one code fix. They are bundled because they share
one user-facing question: **when is a cost delta meaningful enough to call
"savings"?**

## Plain-Language Problem

Prompt caching has asymmetric economics:

- First run can cost more because provider cache writes may have a premium.
- Reruns within TTL should usually cost less because provider cache reads are
  cheaper.
- Small chunks below the provider token minimum do not provider-cache at all.
- Partial `--only` traces are useful evidence for one path, not proof about the
  whole workflow.

The verification report observed analyzer output like:

```text
savings_pct_first_run: -845
savings_pct_rerun: -641
estimated -$0.0036/run
-$0.0016/run
```

Negative deltas are not inherently wrong. A first-run write premium can be a
real cost increase. The bug is that pflow sometimes labels negative deltas as
"savings", emits extreme negative percentages that are not useful agent
guidance, or mixes actual trace cost with hypothetical projections in ways that
make the result mathematically suspect.

The future behavior should let an agent distinguish:

- This saves money on reruns.
- This adds first-run write cost.
- This provider cache will not fire because the content is below threshold.
- This trace is partial, so whole-workflow savings claims are not supported.
- This cannot be computed honestly from available evidence.

## Current Evidence

From `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`:

- Real Anthropic Haiku provider cache worked.
- Fresh Haiku smoke:
  - trace: `/Users/andfal/.pflow/debug/workflow-trace-8ba27c20-smoke-with-cache-20260506-230416.json`
  - cost: `$0.0140`
  - `answer-1` wrote cache, later answers read cache.
- Immediate Haiku rerun:
  - trace: `/Users/andfal/.pflow/debug/workflow-trace-8ba27c20-smoke-with-cache-20260506-230441.json`
  - cost: `$0.0046`
  - all six calls had cache reads.
- Despite the rerun being cheaper, analyzer JSON on the rerun trace produced
  impossible negative percentages such as:
  - `savings_pct_first_run: -845`
  - `savings_pct_rerun: -641`
- A targeted `--only answer-1` trace:
  - trace: `/Users/andfal/.pflow/debug/workflow-trace-8ba27c20-smoke-with-cache-20260506-230837.json`
  - cost: `$0.0008`
  - analyzer treated the workflow as if all six LLM nodes were available and
    produced misleading whole-workflow savings/projection claims.
- Some dry-run/analyzer text rendered negative amounts in phrases that otherwise
  communicate "saves", such as `estimated -$0.0036/run`.

Trust boundary:

- The report is reliable evidence that the UX/math output is wrong or
  misleading.
- It is **not** proof that every underlying arithmetic primitive is wrong.
  The first research step is to separate calculation bugs from naming/rendering
  bugs.

## Reproduction Commands

Use sandbox-safe invocation in Codex:

```bash
CTX="$(cat scratchpads/stage2-verification/anthropic-haiku/reference.md)"

HOME=/private/tmp/pflow-test-home .venv/bin/pflow \
  scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --report --no-cache context="$CTX"

HOME=/private/tmp/pflow-test-home .venv/bin/pflow \
  scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --report --no-cache context="$CTX"
```

Then analyze the fresh and rerun traces:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --from-trace <trace-path> \
  --format=json
```

To reproduce the partial-trace variant:

```bash
CTX="$(cat scratchpads/stage2-verification/anthropic-haiku/reference.md)"

HOME=/private/tmp/pflow-test-home .venv/bin/pflow \
  scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --only answer-1 \
  --report \
  --no-cache \
  context="$CTX"

HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --from-trace <only-trace-path> \
  --format=json
```

Historical traces named in the report may exist under `/Users/andfal/.pflow`.
If they are gone, fresh reproduction is acceptable but costs real provider
money. Prefer using checked-in scratchpad traces if sufficient for the specific
assertion being investigated.

Context hygiene for the next agent: do not dump full trace JSON or full
`node_output.system` bodies into the conversation. The Haiku traces contain
large cached system prompts; use targeted `jq`, `rg`, or small Python snippets
for fields like `input_tokens`, `cache_read_input_tokens`, `cost_usd`,
`nodes_executed`, and `llm_summary`. The session addendum has already captured
the useful numbers from those traces.

## Most Relevant Code Areas

Start with these. Read before editing.

- `src/pflow/core/cache_analysis/analyze.py`
  - `AnalysisSummary` dataclass.
  - `_build_summary(...)`.
  - `_safe_pct_or_none(...)`.
  - per-call row construction and `TraceExecutionIndex` handling.
- `src/pflow/core/cache_analysis/cost_estimation.py`
  - `compute_projections(...)`.
  - `compute_actually_paid(...)`.
  - `_aggregate_first_run_savings(...)`.
  - `_aggregate_rerun_savings(...)`.
  - row exclusion rules for heterogeneous and non-executed trace rows.
- `src/pflow/core/cache_analysis/render_text.py`
  - summary rendering.
  - recommended action rendering.
  - savings wording and negative dollar display.
- `src/pflow/core/cache_analysis/render_json.py`
  - JSON summary fields.
  - action fields exposed to agents/MCP.
- `src/pflow/core/cache_analysis/view_helpers.py`
  - `RecommendedAction.estimated_savings_usd` projection and ranking.
- `src/pflow/core/cache_analysis/summarize.py`
  - dry-run nudge text and savings anchor.
- `src/pflow/core/cache_analysis/below_min_tokens_detector.py`
  - threshold signal used by analyzer/runtime below-min warnings.

Important current code suspicion:

- `_build_summary(...)` currently chooses `actually_paid.total_usd` as the
  percentage anchor when present, otherwise `no_cache_hypothetical_usd`.
  This may be invalid when the actual trace already includes provider cache
  reads, pflow memo hits, partial `--only` execution, Gemini implicit cache, or
  a subset of workflow rows. Investigate before changing labels.

## Relevant Progress-Log Context

Read these sections from
`.taskmaster/tasks/task_159/implementation/implementation-progress-log.md`:

- `Post-segment-4 follow-up: cost wiring + honest loose-ends audit`
  - Introduced real cost computation.
  - Defines the tri-state cost contract: priced / partial / unavailable.
  - Explains why `$0` versus unavailable is load-bearing UX.
- `Verification-specialist CLI drill — 4 production bugs fixed`
  - Includes earlier "Cache ratio > 100%" and "`-$0.00/run` violates
    tri-state contract" lessons.
  - Relevant because similar bug class appears to have re-entered.
- `Cost-projection fix: Tracks A + B + C`
  - Explains separation between recorded trace cost and projections.
- `Cost-projection fix follow-up: cached events + missing tests`
  - Relevant for memo-hit and cached event semantics.
- `Stage 2.1 follow-up — Anthropic 1h cost double-charge`
  - Confirms Haiku 1h TTL cost normalization and previous spurious negative
    first-run savings caused by pricing mismatch.
- `Stage 2 follow-up — Findings #11/#12: exact-model fragmentation + lone-write penalty`
  - Introduces first-call write penalty.
  - Important distinction: a first-call penalty is not the same as savings.
- `Stage 2 follow-up — Findings #11/#12: post-review fixes`
  - Contains the "honest-unmeasurable beats approximate-and-overstating"
    principle.
  - Notes embedded currency in catalog message bodies is an anti-pattern.
- `Stage 2 follow-up — Findings #9/#10 + phantom-savings: unified below-min-token detection`
  - Directly relevant to below-threshold phantom savings.
  - Says threshold gating must happen at provider-cache granularity.
- `Stage 2 follow-up — post-implementation review + tightening`
  - Reinforces "honest unmeasurable" for missing provider telemetry.
- `Stage 2 follow-up — Finding #17: all-memo trace cost is known zero`
  - Relevant because actual paid zero is real, but historical provider cost may
    still exist for projections.

Also read:

- `scratchpads/stage2-verification/README.md`
  - Handoff trust boundary.
  - Manual things worth testing hard.
  - Anthropic Haiku fixture instructions.
- `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`
  - Findings 2, 4, 5, and 12.
  - Positive results and paid-run decision.
- `src/pflow/core/cache_analysis/CLAUDE.md`
  - Current analyzer architecture and known planned Task 160 refactor.
  - Especially the cost-estimation and trace-contract sections.

## Research Questions for the Next Agent

Answer these before designing a fix:

1. What exact fields are compared to compute:
   - `savings_pct_first_run`
   - `savings_pct_rerun`
   - `aggregate_savings_first_run_usd`
   - `aggregate_savings_rerun_usd`
   - dry-run nudge savings
   - recommended action `estimated_savings_usd`
2. Are the compared values all from the same semantic layer?
   - actual paid trace cost
   - no-cache hypothetical
   - first-run with-cache hypothetical
   - rerun-within-TTL hypothetical
   - pflow memo actual zero
3. Are partial traces marked before aggregate math is trusted?
4. Does `--only` make non-executed rows contribute to projections or counts?
5. Are provider cache token fields counted once?
   - Anthropic/Gemini may differ in whether cache tokens are split from
     `input_tokens`.
6. Does below-threshold provider-cache content contribute to savings anywhere?
7. Are first-run write premiums represented as cost increases rather than
   negative savings?
8. Should some existing fields be removed, renamed, split, or set to `null`
   because no external compatibility exists yet?

## Design Decisions to Bring to the User

The fixing agent should present options and tradeoffs before implementation if
the answer is not obvious from code.

Likely decisions:

- Whether negative first-run deltas should render as:
  - "first-run write premium",
  - signed delta,
  - hidden unless material,
  - or `null` with a reason.
- Whether percentage fields should be bounded, nullable, or replaced by clearer
  delta fields.
- Whether JSON should expose raw signed deltas while text uses user-friendly
  labels.
- Whether partial traces should suppress all workflow-level savings percentages
  or expose them under an explicit "partial trace projection" label.
- Whether below-threshold suggested blocks should be suppressed, downgraded, or
  retained only as "not actionable until expanded" guidance.

## Desired UX Properties

These are outcome constraints, not a patch recipe:

- No text says "saves" for a negative cost delta.
- No JSON field named `savings_*` contains a value that actually means added
  cost unless the field is clearly documented as signed savings/delta.
- The known Haiku rerun smoke should not produce negative rerun savings when
  provider cache reads made the rerun cheaper.
- First-run write premium, if real, is explainable as write premium rather than
  scary impossible savings.
- Partial `--only` traces are visibly partial before any aggregate cost claim.
- Below-threshold cache blocks are not presented as copy-paste actionable edits
  if no provider cache can fire.
- "Unavailable" and "known zero" remain distinct.
- Text, JSON, MCP, and dry-run nudge derive from the same semantic model.

## Test/Verification Expectations

Do not only add unit tests around helper math. Include at least one
production-shaped analyzer invocation or fixture that exercises the CLI/JSON
surface.

Useful test shapes:

- Anthropic Haiku with-cache fresh trace: one write plus several reads.
- Anthropic Haiku rerun trace: all reads.
- `--only answer-1` trace: partial workflow evidence.
- Below-threshold cache declaration: provider cache cannot fire.
- First-call write penalty: exact-model group with only one call.

Likely automated test files:

- `tests/test_core/test_cache_analysis_cost_estimation.py`
- `tests/test_core/test_cache_analysis_analyze.py`
- `tests/test_core/test_cache_analysis_renderers.py`
- `tests/test_core/test_cache_analysis_summarize.py`
- `tests/test_core/test_cache_analysis_per_id_emission.py`
- `tests/test_cli/test_analyze_cache.py`
- `tests/test_execution/test_plan_cache_nudge.py`

Run focused cache sweep before broader gates. In Codex sandbox mode, prefer the
commands from `scratchpads/stage2-verification/README.md` and the
`pflow-sandbox-testing` skill if pytest/uv subprocess behavior gets noisy.

## Non-Goals for This Brief

- Do not start Task 160 structural refactor here. Task 160 requires zero
  behavior change and should wait until Task 159 behavior is trusted.
- Do not preserve broken JSON semantics for compatibility. The analyzer has not
  shipped.
- Do not clamp numbers blindly without understanding whether the underlying
  comparison is valid.
- Do not solve unrelated report/CLI output issues unless they directly share
  the cost semantic model.
