# Braindump: Stage 2 verification findings → fix-decision handoff

> Pair this with:
> - `../reports/REPORT.md` (the WHAT — 21 findings catalogued)
> - `../reports/cache-heterogeneous-models-fragment.md` (the user's specific Finding #11 — implementation spec)
>
> This braindump captures the HOW-IT-FELT and WHY-I-MADE-CERTAIN-CALLS. The 21 findings are written down. What's NOT written: the user's priorities, the constraints they put on fixes, the patterns of how they collaborate, and the gotchas I'd be furious to lose.

---

## Where I am

Two long sessions of Stage 2 verification done. All 21 findings catalogued. Spent ~$2.59 of $5 budget. The cache mechanism in Task 159 works end-to-end on real production workflows; spec target hit definitively on Anthropic Haiku (48% fresh / 99% rerun). On Gemini the spec target is muddied by implicit cache.

The next agent's job is to **decide WITH the user which findings to fix and how**, then implement the chosen ones. This is a planning + execution session, not pure execution.

Working tree state: many in-place edits to `/Users/andfal/projects/music-generation/workflows/lyrics-generator/`. See REPORT.md "Reverts before merge" section. **DO NOT revert until you and user agree on the bug-fix scope** — some edits are workarounds for Finding #1 (the `reasoning_effort` translation bug) and should stay until that bug is fixed at the pflow level.

---

## User's mental model — exact words and patterns

### Their priorities (revealed across the session)

1. **"make sure you are evaluating the agent ux of all features of this branch as much as making sure everything works"** — load-bearing. Every test surface gets evaluated for "what does this mean to an agent?" UX. The 21 findings are mostly UX findings, not mechanism failures. The user values UX work as highly as mechanism work.

2. **"we shouldnt do the implement provider-constraint table in pflow"** — explicit constraint on solutions. They don't want maintenance burden of a generic provider-rule table. **This affects how Finding #1 (temp=1+thinking) gets fixed**: the fix path is constrained to "fix it inside pflow's existing translation layer" (the layer that translates `reasoning_effort: low` → Anthropic's `thinking: enabled` should ALSO normalize `temperature: 1`). It's NOT "build a constraint table" or "validate at workflow time."

3. **"the model need to match exactly for prompt caching to work, not just provider"** — important factual correction. They know the cache namespacing is exact-model-scoped. The Finding #11 spec was updated based on this. The next agent must NOT group by provider prefix when implementing the heterogeneous-models warning.

4. **"how we could best show model switching caching gains in the best way possible"** — meta-priority. They want a NEW SURFACE in analyze-cache that helps agents understand model-switch implications. This is the gap that Finding #11 fills. They specifically want this, not just any of the 21 findings.

### How they speak

- **"go ahead" = "execute the plan, don't keep asking"**. After I propose a plan and they say "go ahead", I should NOT re-confirm small steps. Just execute.
- **Polite corrections phrased as questions**: "the default in pflow should be gemini 3 flash?" — that was a CORRECTION, not a question. When the user phrases something as a question, check whether they're correcting me.
- **"can you think of anything you want to verify before wrapping up"** = they want me to surface gaps PROACTIVELY. Don't just stop when the plan is done; look for what's missing.
- **They distinguish error severity carefully**: "is the error we get back from pflow good? would a new agent understand what to do?" — they want me to evaluate AGENT-USABILITY, not just "does it print something."
- **"can you explain what you mean by this"** is a serious request. They want me to explain CLEARLY enough that THEY (and the next agent) can verify the issue independently. Don't gloss.

### Work patterns

- **They run agents in parallel**. While I was deliberating about the prompt overlap issue, they fixed the prompts themselves and started RUN2. The message was "we just updated the prompts! RUN2 running as bm661gbha." Don't fight this; embrace it. **If the user says "we did X", just trust them and verify against current state.**
- **They reference progress log sections by exact heading**. When a fix lands, they update the progress log and ask me to read the new section. The `## Detect prompt-body / prompt_cache overlap (2026-05-04)` and `## Stage 2 follow-up — `## Cached System` in `--report` (trace 2.2.0)` sections were both added MID-SESSION as fixes shipped.
- **Budget discipline is strategic, not stingy**. They started at $1-2, then added $4 when needed for Haiku tests. They're willing to spend money for good evidence. Frame spend as "what does this answer that nothing else can?"
- **They prefer real workflows over synthetic tests**. The lyrics-generator project is THE testbed. Auxiliary mini-workflows (mixed-model, cross-workflow, error UX) are fine for narrow tests, but the load-bearing verification is on real production code.

---

## Critical insights I'd be furious to lose

### 1. Finding #1 isn't "Anthropic's fault" — it's pflow's translation layer

The temp=1+thinking BadRequestError feels at first like an Anthropic API quirk. It's not. It's pflow's responsibility:

- pflow translates `reasoning_effort: low/medium/high` → Anthropic's `thinking: {enabled, budget_tokens: N}`
- This translation happens in `core/llm_client.py` (or thereabouts) — pflow IS the layer that flips thinking on
- Anthropic's API requires `temperature: 1` whenever `thinking: enabled`
- pflow doesn't normalize temperature when it flips thinking on
- Result: pflow sends a request with `thinking: enabled, temperature: 0.3` and Anthropic rejects

**The fix isn't "add a constraint table"** (the user explicitly said no). The fix is: **the same code that emits `thinking: enabled` should also normalize `temperature: 1`** — preferably with a `## Stage 2 follow-up`-style log entry explaining the choice. Optionally emit a one-time WARNING the first time a workflow's declared temperature is over-ridden.

This is a **5-line fix in the right place**. It's high-impact (every Anthropic workflow with non-zero reasoning_effort breaks today) and low-risk.

### 2. The "Auto-load trace from prior provider" issue is more subtle than it looks

Auto-load isn't broken — it's silently authoritative on stale data. The behavior:
- `analyze-cache <workflow.pflow.md>` (no explicit `--from-trace`) auto-loads the most recent matching trace
- The TRACE was recorded with whatever models the workflow had at that moment
- The current IR may have DIFFERENT models declared
- Analyzer mixes the two: trace data (with old models) + IR data (with new models)
- Result: spurious findings like "Cache hit discrepancy on write-lyrics (predicted=0%, actual=100%)" — the discrepancy is because the trace was on Gemini (implicit cache fires) but the current IR is on Haiku (no implicit cache)

The fix needs to be MODEL-CONTEXT-AWARE: at auto-load time, compare `trace.llm_summary.by_model` (what models the trace was recorded with) to current IR's declared models. If they differ:
- EITHER skip auto-load with an info note
- OR auto-load but tag findings with "trace-from-prior-model-context"

This interaction matters more than it seems because the user's testing flow IS model-switching — they may run the same workflow on multiple providers in sequence. Each switch invalidates auto-load.

### 3. Gemini's implicit cache subverts EVERYTHING about explicit-cache testing

This was the single hardest concept to internalize. Gemini Flash has automatic implicit caching that fires on any stable prefix above the threshold, regardless of whether the workflow declares `## Cache`. So:

- `## Cache` declaration on Gemini gives MARGINAL benefit over implicit cache
- `--no-cache` flag (which only disables memo) leaves implicit cache firing
- Cache_key invalidation (changing context) gets new explicit cache_key but Gemini implicit STILL fires on similar content
- "True fresh baseline" on Gemini is essentially impossible

**For spec-target verification, ALWAYS use Anthropic** — no implicit cache, clean numbers. The user understood this implicitly when they suggested switching to Haiku. The next agent: when verifying cache features, default to Anthropic.

### 4. Per-workflow cache_key scoping is tighter than the analyzer suggests

The cross-workflow test had this surprise:
- Parent declares `## Cache` with `${shared_doc}`
- Child also declares `## Cache` with `${shared_doc}` (same content, same model)
- DIFFERENT cache_keys — they don't share

The analyzer's "Cross-boundary value undeclared — declare in either workflow's ## Cache" recommendation IMPLIES cross-workflow sharing is possible. **It isn't on Anthropic** (each workflow gets its own cache namespace). On Gemini, implicit cache picks up the slack so it "works" — but the explicit cache mechanism doesn't share.

This is **working-as-designed** (cache_key includes workflow scope) but the recommendation text is misleading. Worth filing as a docstring fix when the cross-workflow behavior is clarified.

### 5. The user-edited prompts mid-session — KEEP those edits

While I was deliberating about the prompt-body overlap (Finding solved by `cache.prompt-body-duplicates-cache` validator), the user edited the 7 song-creator prompt files themselves to remove the duplicated `${concept.title}`, `${concept_brief}`, etc. references. Those edits unlocked the explicit cache benefit on Anthropic.

**These prompt edits are KEEPERS** — they're real workflow improvements. Do NOT revert them. The model overrides + reasoning_effort: none changes are workarounds (revert when pflow Finding #1 is fixed). The prompt cleanups are improvements (keep forever).

### 6. The score-choruses temp=1 issue is a CASCADING workflow-author trap

Once Finding #1 lands as a pflow fix, the `reasoning_effort: low → none` workarounds I applied across:
- `chorus-chooser/score-choruses` (1 file)
- 9 review sub-workflows (9 files)
- `generate-suno-prompt` (in song-creator.pflow.md)

…can ALL be reverted (set back to `reasoning_effort: low`) and the workflows will work on Anthropic too. Until Finding #1 is fixed, those are required workarounds.

The implication: **don't ship the Finding #1 fix without also testing the lyrics-generator workflows on Anthropic with reasoning_effort restored**. Round-trip verification.

### 7. The `--report` 2.2.0 fix landed mid-session and worked

The user shipped `## Cached System` in --report DURING our verification session (commit landed via the progress log section dated 2026-05-04). I verified the fix end-to-end on the gemini-smoke. Anthropic-format `cache_control: {type: ephemeral, ttl: "1h"}` and Gemini-format `{type: ephemeral, ttl: "300s"}` both render correctly.

**This pattern is likely to recur**. The user lands fixes mid-verification and updates the progress log. **Always re-read the latest progress log section before assuming a known issue still exists.** I missed this once and the user had to point it out ("did you read the new section in the progress log?").

---

## Things I'd 70% bet on but didn't verify

- **MCP server `analyze_cache` tool has the SAME UX gaps** as the CLI version. They share the analyzer code path. But I didn't verify any MCP-specific behavior. **NEEDS VERIFICATION** if you implement a finding-fix that touches the analyzer's per_call output shape.
- **`pflow save` would catch the temp=1+thinking issue** if Finding #1 landed as a pflow-side validator (not just translation fix). Pattern-4 subprocess test would be the regression pin.
- **The cross-workflow cache_key inclusion of workflow scope** is a deliberate design choice, not a bug. The cache_key probably hashes (workflow_path, node_id, chunks) rather than just chunks. If a future "make cache shareable across workflows" feature is wanted, the scope would need to widen — but that's a different conversation.
- **Haiku 4.5's 4096-token cache minimum** (in pflow's `llm_capabilities.py`) might be inaccurate. Anthropic's Sonnet/Opus cache at 1024 tokens; the difference for Haiku is unusual. Worth verifying against Anthropic's actual API behavior. **NEEDS VERIFICATION**.
- **The `total_llm_calls_estimated: 19` field naming** is wrong (it's a node count not call count). Renaming it might break MCP tool consumers. **CONSIDER**: a backwards-compatible aliased field rather than a rename.

---

## Decision dimensions for "which findings to fix"

When the next agent talks with the user about prioritization, here are the axes that matter:

### By impact on real workflows
- **Finding #1 (temp=1+thinking)**: blocks every Anthropic workflow with reasoning_effort. **TOP** priority.
- **Finding #2 (rerun_within_ttl ignores memo)**: makes the analyzer's projection wildly wrong. Agents reading it will under-estimate caching value. HIGH.
- **Finding #11 (heterogeneous-models warning)**: silently fragmenting workflows pay 2-3× the cache cost. The user explicitly wants this. HIGH.
- **Findings #3, #4, #5 (analyzer correlation, --report cache fields, JSON cache fields)**: data already exists, just isn't surfaced. MEDIUM.
- **Finding #9 (cache.below-min-tokens not at validate time)**: small surface fix. LOW-MEDIUM.

### By fix complexity
- **Trivial (5–20 LOC + tests)**: Findings #6, #13, #15, #17, #18 — text/rendering tweaks
- **Small (~50–100 LOC + tests)**: Findings #1, #4, #5, #9, #14, #16
- **Medium (~150 LOC + tests)**: Finding #11 (new catalog entry, detection logic, tests, MCP docstring sync)
- **Larger (might need investigation)**: Findings #3 (correlation bug), #2 (memo modeling)

### By independence (good for parallel agent work)
- **Independent fixes**: #1, #6, #11, #13 can be done in parallel with no dependencies
- **Coupled**: #2 + #20 (memo behavior interactions); #4 + #5 (same field-set in different surfaces); #8 + #10 (auto-load + provider-aware text)

### Per the user's stated preferences
- **Will accept**: catalog-entry-shape fixes (mirror existing patterns)
- **Will reject**: provider-constraint tables, generic rule engines
- **Wants explicitly**: heterogeneous-models warning (#11)
- **Said but didn't elaborate**: rerun_within_ttl modeling (#2) — likely also wants but check
- **Probably defer**: paper-cuts (#17, #20, #21)

---

## What I'd tell myself if starting over

1. **Read the latest progress log sections BEFORE running anything.** The user lands fixes mid-session. I wasted a RUN2 attempt because I didn't know `cache.prompt-body-duplicates-cache` had been added.

2. **Always run `--validate-only` BEFORE the first paid run.** Would have caught the prompt-body overlap (which made my first cache attempt invalid) without spending money.

3. **Default to Anthropic for cache mechanism verification.** Gemini's implicit cache is a confound. The user understood this; I didn't until late.

4. **Don't truncate analyze-cache output with `head -40`.** I missed 7 BLOCKING errors because I cut the output. The summary line "21 opportunities" undersells the severity. Read the full output.

5. **The `## Stage 2 follow-up` pattern in the progress log is load-bearing.** The user uses it to track mid-session fixes. **Always grep for `## Stage 2 follow-up` and `## <feature> follow-up` patterns before assuming a known issue still exists.**

6. **Per-batch-item report file naming is a UX win** that I almost missed. `item-0-gemini-3-flash-preview.md` showing the model in the filename is exactly the kind of thing agents need. Worth highlighting if you build similar features.

7. **Mixed-model fragmentation has TWO classes** — within-batch (heterogeneous batches, already detected) and cross-node (different nodes, different models). The existing detection covers only the first. The user's question was about the SECOND.

---

## Open threads

### Definitely open

- **Finding #1 fix shape**: auto-normalize temperature inside pflow's translation layer (per user constraint of no constraint table). I sketched the approach but didn't implement. **Approach**: when emitting an Anthropic request with `thinking: enabled`, set `temperature = 1` regardless of workflow's declared value. Optionally emit a one-time INFO note "temperature=1 normalized for thinking mode." Test with the lyrics-generator workflows after revert of my workarounds.

- **Cache_creation cost projection accuracy**: my mixed-model test showed analyzer's `no_cache_hypothetical_usd: $0.0119` matched my hand-calc when I used the right Haiku rates ($1.00/M). But the math is sensitive to model rate accuracy in `litellm.utils.get_model_info()`. **NEEDS VERIFICATION**: that the analyzer reads model rates from the same place LiteLLM does. If they diverge, projections will be subtly wrong.

- **score-choruses prewarm: true** opportunity. score-choruses runs 34 batch items with the same scoring rubric. PERFECT for `prewarm: true` — would write cache once, read 33 times. I deliberately skipped this test (prompt is opaque, complicates the test). The user said skip but it's a real value-add for the lyrics-generator project. **CONSIDER** filing as future work in the music-generation repo.

- **Cross-provider cache consolidation guidance**: when Finding #11 lands, we need to also clarify that "consolidate to one model" might not be possible (workflow-author chose models for reasons — quality, cost, latency tradeoffs). The warning should say "consider consolidating; if you can't, accept the fragmentation cost."

### Probably worth flagging

- **The `--no-cache` flag scope** (Finding #13) is misleading enough that someone WILL get tripped by it. A small renaming to `--no-memo` would be a 30-LOC fix but breaks anyone who scripts pflow with `--no-cache`. Worth a deprecation period.

- **The `actually_paid_usd: null` paper-cut** (Finding #17) is documented in the handoff. Doesn't affect agents who read per-call rows but trips quick-glance summaries.

- **The 120s default LLM timeout** (Finding #19) bites both Pro Preview AND Haiku on reasonable workflows. Increase default to 240s OR auto-scale based on prompt size.

---

## Process notes for the next agent

### How to talk with this user about decisions

1. **Present options with concrete tradeoffs**, not abstract ranges.
   - GOOD: "Option A: 50 LOC fix in translation layer (5 hours). Option B: 200 LOC fix as a new validator (12 hours, requires test coverage of 9 catalog scenarios)."
   - BAD: "We could fix this lots of ways depending on scope."

2. **Surface the user's stated constraints up front**. If the user said "no provider-constraint table," repeat it back: "Per your earlier guidance about no provider-constraint table, Option A doesn't add a constraint table; Option B would technically be a constraint registry which I think is out of scope per your guidance."

3. **Cite line numbers and file paths**. "spec line 1030", "warning_catalog.py:142". The user references these and expects me to too.

4. **Distinguish bug fixes from feature additions**. Finding #1 is a BUG FIX (existing behavior is wrong). Finding #11 is a FEATURE ADDITION (new warning). Different decision criteria, different amount of design.

5. **Ask before spending**. The user's budget discipline is strategic. If a fix needs verification on lyrics-generator, ask: "This fix needs a $0.30-0.50 verification run on Anthropic. Approve?" before spending.

### What the user WILL likely want to do first

Best guess: fix Finding #1 first (highest impact, simplest fix, blocks current production workflows). Then likely Finding #11 (the explicit ask). Then triage the rest.

### Files to read FIRST

1. `../reports/REPORT.md` — the comprehensive findings catalogue
2. `../reports/cache-heterogeneous-models-fragment.md` — the implementation spec for Finding #11
3. `../implementation-progress-log.md` — the progress log; especially the latest sections (Stage 2 verification entry + Stage 2.1 follow-up Anthropic 1h cost normalization)
4. THIS document

### Files to read ONLY IF needed

- The actual workflow files in `/Users/andfal/projects/music-generation/workflows/lyrics-generator/` — only if you're implementing Finding #1 and need to round-trip verify.
- The mini test workflows under `scratchpads/stage2-verification/{mixed-model-test, cross-workflow-test, error-ux-tests}/` — only if you're implementing Finding #11 (mixed-model is the canonical test fixture).

---

## Relevant files (don't re-derive)

### Documents
- `../reports/REPORT.md` — 21 findings catalogue
- `../reports/cache-heterogeneous-models-fragment.md` — Finding #11 spec
- `../implementation-progress-log.md` — progress log; line 6797 (prompt-body overlap), line 7004 (## Cached System fix), line 7188 (Anthropic 1h cost normalization), line 7191 (Stage 2 verification entry)

### Code locations referenced (from my exploration)
- `core/llm_client.py` — where pflow translates `reasoning_effort` → Anthropic's `thinking` (Finding #1 fix site)
- `core/llm_capabilities.py:90` — Gemini's 4096-token threshold; Haiku's threshold also seems to be 4096 (verify)
- `core/cache_analysis/analyze.py` — analyzer logic, including `_estimate_row_tokens`, `_build_trace_execution_index`
- `core/cache_analysis/warning_catalog.py` — 16 catalog entries; new entry for Finding #11 goes here
- `core/cache_analysis/render_text.py` — text rendering of recommendations
- `core/cache_analysis/render_json.py` — JSON output schema
- `core/trace_report.py` — `--report` markdown rendering (where Finding #4 fix goes)

### Data/traces
- `scratchpads/stage2-verification/song-creator/RUN-HAIKU-FINAL-trace.json` — clean Anthropic FRESH data (48% savings proof)
- `scratchpads/stage2-verification/song-creator/RUN-HAIKU-RERUN-trace.json` — rerun (99% reduction proof)
- `~/.pflow/debug/workflow-trace-805ed51c-mixed-model-*.json` — Finding #11 fixture data

---

## For the next agent

**Start by**:
1. Reading the REPORT.md fully (~30 min) — understand the 21 findings
2. Reading the cache-heterogeneous-models-fragment.md (~10 min) — Finding #11 spec
3. Reading this braindump fully (~15 min) — the patterns and gotchas
4. Reading `../implementation-progress-log.md` last 500 lines (~10 min) — what's been fixed mid-session
5. Discussing with the user which findings to prioritize. Don't propose all 21; propose 3-5 (the highest-impact and the one the user explicitly asked for).

**The user cares most about**:
- Finding #1 (the temp=1+thinking pflow translation bug) — blocks production
- Finding #11 (the heterogeneous-models warning) — they explicitly asked for this
- Honest reporting on what does and doesn't work
- Cost discipline on any new test runs

**Move forward without asking**:
- Reading any file in this repo or the music-generation repo
- Running `--validate-only` and `analyze-cache` (free)
- Running unit tests
- Adding catalog entries that mirror existing patterns

**Surface to user before**:
- Spending > $0.20 on any single LLM-paid run
- Editing files outside the pflow repo (the lyrics-generator project edits should be coordinated)
- Changing trace format version (would require another minor bump like 2.3.0)
- Renaming JSON fields (breaking change for MCP consumers)

**Don't bother with**:
- Fixing the pre-existing 2 ruff RUF059 errors in `tests/test_core/test_cache_analysis_token_estimation.py` (commit `6640255b1`) — out of scope, mechanical fix
- Re-running the gemini-smoke or anthropic-smoke (verified end-to-end multiple times)
- Trying to get a "clean" Gemini baseline (impossible due to implicit cache)
- The MCP server analyze_cache tool path (delegates to analyzer; same fixes apply)

**The user works in this pattern** (observed):
- Agent proposes plan → user approves with "go ahead" or modifies
- Agent executes in parallel as much as possible
- Results surfaced with concrete data, not abstract claims
- Findings categorized by severity for triage decisions

---

**Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points (especially the 7 critical insights and the user's stated constraints), then state you're ready to proceed.
