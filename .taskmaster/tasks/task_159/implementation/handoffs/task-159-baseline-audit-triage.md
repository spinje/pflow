# Braindump: Task 159 baseline audit — triage handoff

> Context-window handoff to the agent who will triage the 48 findings
> in `.taskmaster/tasks/task_159/baseline/BASELINE-AUDIT.md` and
> decide what to fix before merging Task 159.
>
> **Read first**: `BASELINE-AUDIT.md` (the audit itself), then
> `FINDINGS.md` (5 prior findings, mostly resolved). Then this file
> for what isn't written there.

---

## Where I am

I performed the audit specified by `NEXT-AGENT-AUDIT.md`. The prior
agent built 63 baseline cases (now 65 with the 2 live recordings I
added). My job was to read the captured outputs and judge whether
they'd actually help an AI agent debug a workflow.

Initial audit produced 25 findings from reading captured `expected-*.txt`
files alone. Then I:

1. **Live-verified** several findings by running pflow directly →
   surfaced 3 new ones (B-9 blocking-errors-section header, B-10
   guide-topic-position, B-11 workflow-header awkwardness)
2. **Audited `pflow guide caching` content** → 4 findings (B-12
   through B-15), one of which is a doc bug (B-12: incomplete
   model-min-tokens enumeration)
3. **Recorded a Gemini smoke trace** as surface 10 case 03 →
   5 findings (B-16 through B-20)
4. **Recorded the full lyrics-generator end-to-end** ($2.31, 9:40
   wall clock, 253 LLM calls) as surface 10 case 05 → 9 findings
   (L-1 through L-9)
5. **User surfaced 3 more findings in post-recording review** by
   asking obvious questions about the captured baseline → L-10,
   L-11, L-12 (the most consequential of the entire audit)

Final tally: **48 findings**, **9 code bugs to fix pre-merge**.

The audit ran ~6 hours of conversation time including the live runs.

---

## User's mental model — exact words and what they meant

The user (Andreas) is the architect of the prompt-caching feature
and has run the lyrics-generator workflow many times. He has strong
intuition about cost, runtime, and what "good agent UX" means.

### Round 1 — initial framing

> "lets just doing the last verification before merge"

This was the framing: he expected this to be a final-pass check, not
a major dig. The audit found 9 bug-class issues — bigger than he
expected.

### Round 2 — JSON deprioritization

> "the json is not important here, the text output and agent ux and
> correctness is what matters, and actionable and easy to understand
> information"

He emphasized this MULTIPLE times. The Section D findings (JSON
shape) are deferred. **The triage agent should not invest time on
JSON-shape fixes unless they imply a real correctness issue.**

### Round 3 — direct deep-dive on captured output

After I delivered the audit, he asked:
> "model seems to be missing everywhere?"
> "why are we not showing sub workflow opportunities?"
> "is there really 0 opportunities (0 warnings, 0 info) for this
> workflow...?"
> "why is the trace partial, what went wrong?"

These four questions in 60 seconds surfaced L-10, L-11, L-12 — bugs
I had missed in hours of audit. **The user reading the captured
output is a more powerful audit signal than the auditor reading
captured output.** Worth remembering for future audits.

### Round 4 — verification of trim concern

> "this is not because we trimmed the trace right?"

He intuited that my trim might have introduced artifacts. I verified
against the untrimmed 53MB trace — same suppression behavior. He's
right to be skeptical of fixture preparation.

### Stated priorities (verbatim where I have them)

- "Text output, agent UX, and correctness is what matters"
- "Actionable and easy to understand information"
- Cost ceiling for live runs: "$1-3 OK"
- Capture partial traces if runs fail (we never had to)

### Unstated priorities (my read)

- Pre-merge scrutiny is high. He cares about not shipping bugs that
  agents will hit on first contact.
- He trusts running real workloads more than reading specs.
- He's willing to spend ~$3 on live verification when it produces
  signal.
- He notices when the analyzer is doing something wrong even when it
  looks "successful" (the 0 opportunities question).

---

## The most important thing the next agent must understand

**L-10 is the load-bearing finding of this entire audit.**

Static analysis of the lyrics-generator finds **19 opportunities** (2
recommended actions + 17 cross-workflow renames). Trace analysis of
the SAME workflow finds **0 opportunities**. The cross-workflow
findings are static facts derived from the workflow files; they have
nothing to do with trace data. But trace mode hides them via a
single coarse gate: `Workflow-design recommendations suppressed
because the trace is partial`.

**The architectural model is wrong.** The current behavior:
```
findings = trace_findings if has_trace else static_findings  # replacement
```
The correct behavior:
```
findings = static_findings + trace_findings  # superset
```

This affects EVERY workflow agents have run. Run-once is when agents
turn to `analyze-cache` to optimize. Trace mode firing → static
findings hidden → agent thinks workflow is optimal when it has 19
real cache opportunities.

L-11 (the "partial trace" misframing) is the proximate cause:
"partial" classification fires for workflows with conditional
dispatches that didn't run, even though the workflow completed
successfully. That triggers L-10's suppression cascade.

L-12 (per-call model column doesn't read trace's `event.llm_call.model`)
is a separate but related issue — the analyzer has trace data and
isn't using it for per-call rendering.

**Fix priority**: L-11 first (de-conflate "partial" from "failed"),
then L-10 (split static/trace findings in suppression logic), then
L-12 (use trace's model in per-call rendering).

---

## Tacit knowledge

### Things you can only learn by running the lyrics-generator

A static-only audit misses L-10 entirely. I spent hours reading
captured outputs without seeing it. The user spotted it immediately
when I gave him the captured output to look at.

**Lesson**: any audit of an analyzer that has multiple modes (static
vs trace, etc.) MUST exercise all modes on a real workflow, not just
read captures. Synthetic captures don't surface the cross-mode
regressions.

### The captured `expected-stdout.txt` for case 05 LOCKS the bugs

Case `10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`
is now a baseline. It contains:
- `0 opportunities (0 warnings, 0 info)` (locks L-10)
- `Evidence: partial trace (18 of 25 LLM nodes executed)` (locks L-11)
- `model=` empty everywhere (locks L-12)
- `Workflow-design recommendations suppressed` (locks the bad gate)

When Task 160's refactor FIXES these bugs, this case will drift in
verify.sh. **That drift is expected — re-capture the case, don't
revert the fix.** Add a comment to the case README explaining this.

### The trim story (read this if touching the fixture)

Original lyrics-generator trace: 53MB. Mostly duplicated prompt text
across 4 fields per event:
- `event.llm_prompt` (the full prompt sent)
- `event.node_params.prompt` (same content)
- `event.template_resolutions.prompt.resolved` (same content)
- `event.node_output.prompt` (same content)

I trimmed to 12MB by replacing these heavy text fields with `<trimmed
N chars>` markers. **Verified L-10/L-11/L-12 reproduce on both
trimmed and untrimmed traces** — they're real bugs, not trim
artifacts.

**BUT**: my trim caused a small drift in the analyzer's
"executed-nodes" count (untrimmed: 16 of 25; trimmed: 18 of 25).
The non-empty `<trimmed N chars>` markers apparently look like
populated content to whatever heuristic decides "did this node
execute?" The captured baseline shows 18 (the trimmed count). The
truth is 16.

**Untrimmed trace**: at `/Users/andfal/.pflow/debug/workflow-trace-c2f89d56-lyrics-generator-20260508-221119.json`
(53MB, on user's machine only — not committed).

**Better trim** (TODO if regenerating fixture): replace heavy text
with EMPTY strings (`""`) instead of `<trimmed N chars>` markers, so
nothing accidentally looks like populated content.

### Cost estimation reality vs my estimates

- I estimated full lyrics-generator run at $0.08-0.30 with Gemini
- Actual cost: $2.31 (10× my estimate)
- User said "$1-3 OK" — he had better intuition

**Lesson**: when the user gives a cost ceiling, trust their estimate
over mine for unfamiliar workflows.

### A-3 still needs verification

A-3 is `unavailable_reason: "trace_coverage_partial"` firing when
`trace_coverage: "none"`. Could be intentional union-vocabulary or a
real bug. **10-minute task**: read `src/pflow/core/cache_analysis/cost_estimation.py`,
search for `trace_coverage_partial` literal, see if it's the
universal "trace not full" tag or whether it should be one of
several values. If multiple values exist, A-3 is a bug. If only this
value exists, A-3 is a vocabulary wart.

### The "honest unmeasurable" convention precedent

F-04 (resolved earlier this branch) is the model for fixing A-6, L-1,
L-12. The pattern:

1. When a column would show fabricated/heuristic data, return
   `(None, "unavailable")` instead.
2. Render as `?` in text mode, `null` in JSON.
3. Add a tier label (`src=high|medium|low|unavailable`) so agents
   know data quality.

A-6 extends this to `tokens=` for opaque prompts. L-12 extends it to
`model=` when trace evidence exists.

---

## What's already locked in baselines (mutation contracts)

The captured baselines lock specific behaviors. The triage agent
must understand which fixes will cause expected drift:

| Finding | Locked in case | Drift on fix? |
|---|---|---|
| A-1 doubled blocking-error | `02-validator-errors/08`, `12-real-world-lyrics-generator/01`, `10-live-recordings/05` | yes — re-capture all 3 |
| A-2 float precision | All JSON cases | yes — re-capture |
| A-6 tokens= for opaque | `12-real-world-lyrics-generator/01`, `12-...03` | yes |
| B-12 guide content | NOT locked (audit-derived) | no |
| B-17 `progress log §36` | `10-live-recordings/03-gemini-translation/expected-stdout.txt:31` | yes |
| L-1/L-2/L-12 model column | `10-live-recordings/05` | yes |
| L-10 trace suppression | `10-live-recordings/05` | yes — case 05 will show 19+ opportunities after fix |
| L-11 partial framing | `10-live-recordings/05` | yes |

**Strategy for L-10/L-11/L-12 fix**: do them as a coordinated batch.
Re-capture case 05 once. Don't try to fix L-10 incrementally (you'll
re-capture multiple times).

---

## Assumptions & uncertainties

**ASSUMPTION**: The "model varies per batch item" handling on
`generate-chorus-options` is the working code path I want extended
to other rows for L-12. I haven't read the renderer code, just
inferred from the captured output. **Verify before fixing**: read
how `<varies>` rows are populated — specifically how
`observed_models=...` is computed — and extend that pattern.

**ASSUMPTION**: The L-10 fix is a single suppression-gate change in
trace-mode rendering logic. **Verify**: trace `Workflow-design
recommendations suppressed for partial trace evidence` to its
emission site and check what feeds it. Likely in
`render_text.py::_render_recommended_actions` or similar.

**UNCLEAR**: Whether L-1 ("discards observed_models when default_model
not set") and L-12 ("doesn't read event.llm_call.model for per-call
rows") are the same bug or different. I framed them separately in
the audit, then unified to L-12 in late updates. The triage agent
should treat them as ONE underlying issue. Reading the source will
clarify.

**NEEDS VERIFICATION**: A-3 (10 min, see above).

**NEEDS VERIFICATION**: the `expected-stdout.txt` for case 05 (the
trimmed-trace version) reports `18 of 25 LLM nodes executed`. The
untrimmed reports `16 of 25`. Either is fine as a captured baseline,
but the next agent should know the count drifted because of trim,
not because of analyzer behavior change.

---

## Unexplored territory

**UNEXPLORED**: I never ran a workflow end-to-end with `--no-cache`
to verify Task 159's claim that `--no-cache` only disables memo,
not provider caching. Surface 08 from PLAN.md was "TODO" and I
didn't implement. Worth a 10-min smoke before merge.

**UNEXPLORED**: I never tested `--from-trace` against a 2.0.0 trace
(scope-cut early per user's "we don't need to test old traces"
directive). If anyone later regenerates traces from older pflow
versions and wants to analyze, this code path is unverified.

**UNEXPLORED**: Surface 06 (dry-run nudge), 07 (hash invariants),
09 (help and guide text) from PLAN.md remain TODO. The triage agent
can decide if these gate Task 160 or defer.

**MIGHT MATTER**: The 12MB trace fixture is heavy for a baseline
fixture. I asked the user about commit-vs-gitignore-vs-LFS but he
didn't answer (we moved on to L-10 discussion). **Open question for
triage**: how to handle the trace fixture for case 05 long-term.
Options:
1. Commit 12MB raw (works, but bloats repo)
2. gzip → ~3MB; have command.sh decompress at runtime
3. Use git-lfs for `_shared/fixtures/*.json`
4. gitignore + document manual recording (case 05 not auto-runnable)

**MIGHT MATTER**: I never ran the workflow end-to-end on its NORMAL
default model (anthropic/claude-haiku-4-5). The Gemini run produced
the L-* findings but a haiku run might surface different findings
(e.g., haiku-specific cache_creation token reporting differences).
Cost would be similar (~$2-3). Defer unless triage decides it's
needed.

**UNEXPLORED**: The `pflow analyze-cache --all-rows` flag in trace
mode — does it ALSO suppress the 19 static findings? Untested. If
yes, that's another dimension of L-10. If no, that's a workaround
agents can use. Worth 30 seconds to verify.

---

## Things that almost broke

### The MCP node visibility issue

The lyrics-generator workflow uses `mcp-klavis-youtube-...` nodes.
The user has these registered in his real env. The captured baseline
runs in clean env (no MCP config), so the analyzer surfaces "Unknown
node type" as a blocking error.

This means **case 12-01 (lyrics-generator-static) and case 10-05
(lyrics-generator-trace) both contain this MCP error in their
`Blocking errors` section** — visible only to fresh-env testers, not
to users with MCP configured.

This is documented as B-9 in the audit (the misleading section
header). But the underlying tension is: should the analyzer's "must
fix before save and run" framing apply to MCP errors that the agent
hasn't decided to register yet? Probably yes (workflow won't run).
But it's confusing UX.

### The trim broke the round-trip once

I trimmed too aggressively first (strings >200 chars). The diff
showed `review-rhyme.pflow.md` row missing. Backed off to a more
conservative trim (only `llm_prompt`, `llm_response`, `llm_system`,
`template_resolutions`, plus large strings inside `node_params` and
`node_output`). That preserved analyzer compatibility but introduced
the 16→18 count drift.

**If the next agent regenerates the case 05 fixture**: use empty
strings (`""`) instead of `<trimmed N chars>` markers for stripped
content. The analyzer's heuristic for "did this execute?" must be
checking for non-empty content somewhere.

---

## What I'd tell myself if starting over

1. **Run the workflow end-to-end FIRST, before any audit work.** The
   live trace data was the highest-yield input. Static-only audit
   missed L-10 entirely. Hours wasted reading captures.

2. **Trust user observations more.** Andreas surfaced 3 of the most
   consequential findings (L-10, L-11, L-12) by asking obvious
   questions about the captured output. I should have asked him to
   read the captures sooner.

3. **Don't oversell uncertainty as bugs.** A-3 and A-4 were classified
   as bugs in my initial audit. Both turned out to be either intentional
   union-vocabulary (A-3, pending verification) or correct counts with
   misleading rendering (A-4, downgraded to wart). When uncertain,
   classify lower.

4. **JSON findings really are lower priority.** I included Section D
   anyway. The user explicitly said don't bother. Listening would have
   saved 30 min.

5. **The trim approach was fine in concept** but the choice of marker
   strings (`<trimmed N chars>`) was a mistake. Empty strings or `null`
   would have been transparent to the analyzer.

6. **Cost estimates: trust the user.** $0.30 vs $2.31 (10× drift). The
   user said $1-3 was fine; he was right.

---

## Open threads / suspicions

**SUSPICION**: L-10's suppression gate is probably one or two lines in
`render_text.py` (and possibly `render_json.py`). Likely a check like
`if analysis.evidence_scope == "partial": skip recommendations`.
Removing or refining that check is the fix. **Verify**: grep for
`partial trace evidence` or `Workflow-design recommendations suppressed`
to find the emission site.

**SUSPICION**: the per-call model column rendering (L-12) reads from
`per_call[].model` field in the analysis result, which is populated
from the IR-resolved model. The fix is to populate it from
`event.llm_call.model` when trace data is available, falling back to
IR. The `<varies>` code path on `generate-chorus-options` is the model
to extend.

**SUSPICION**: the 117-events-with-no-predicted-cache-key (L-5) might
be related to `--from-trace` not running the cache_key prediction
through the same path as auto-load. Worth investigating but lower
priority.

**SUSPICION**: B-13 (stale `--from-trace` example path in guide) —
agents who copy the literal example string `~/.pflow/debug/trace.json`
will fail and may write bug reports. Quick fix; should batch with
B-12 (model min-tokens enumeration) as a single "pflow guide caching
content fix" PR.

---

## Concrete fix order I'd suggest

1. **Pre-merge fixes (3-5 hours of work total)**:
   - L-11 + L-10 + L-12 batch (the trace-mode regression of evidence) —
     biggest impact, single coordinated fix, single fixture re-capture
   - A-1 (blocking-error duplicate message) — straightforward renderer
     fix, locked in 3 cases
   - A-6 (tokens= for opaque prompts) — extends F-04 fix shape
   - B-17 (`progress log §36` dead-link) — quick prose cleanup
   - B-12 + B-13 batch (guide content fixes) — single doc PR

2. **Verify A-3** (10 min) → either fix or downgrade to wart

3. **Re-capture affected baselines** after fixes:
   - Cases that lock A-1, A-6, L-1, L-10, L-11, L-12 will drift
   - Run `regenerate.sh` for those cases, eyeball the diff, commit

4. **Defer everything else** unless someone surfaces it as blocking.
   The B-section warts and C-section UX issues are real but not
   merge-gating.

5. **Ship Task 159**.

6. **Task 160 starts** with the captured baselines as regression
   oracles for trace-mode behavior.

---

## Relevant files & references

**The audit itself**:
- `.taskmaster/tasks/task_159/baseline/BASELINE-AUDIT.md` (the 48
  findings — read first)
- `.taskmaster/tasks/task_159/baseline/FINDINGS.md` (5 prior findings,
  mostly resolved — F-02 and F-05 still open)
- `.taskmaster/tasks/task_159/baseline/NEXT-AGENT-AUDIT.md` (the
  audit's original mission statement)
- `.taskmaster/tasks/task_159/baseline/PLAN.md` (the construction plan
  the prior agent followed)
- `.taskmaster/tasks/task_159/starting-context/braindump-2026-05-08-baseline-audit-handoff.md`
  (the prior agent's handoff to me)

**Captures that lock bugs**:
- `.taskmaster/tasks/task_159/baseline/02-validator-errors/08-analyze-cache-surfaces-undeclared-name/expected-stdout.txt`
  (locks A-1)
- `.taskmaster/tasks/task_159/baseline/12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt`
  (locks A-1, A-6, B-1 through B-8)
- `.taskmaster/tasks/task_159/baseline/10-live-recordings/03-gemini-translation/expected-stdout.txt`
  (locks B-17)
- `.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`
  (locks A-1, L-1, L-9, L-10, L-11, L-12)

**Trace fixtures**:
- `_shared/fixtures/sample-2.1.0-trace.json` (6KB, smoke trace)
- `_shared/fixtures/live-gemini-translation.trace.json` (129KB, case 03)
- `_shared/fixtures/live-gemini-lyrics-generator.trace.json` (12MB,
  trimmed; case 05)
- `/Users/andfal/.pflow/debug/workflow-trace-c2f89d56-lyrics-generator-20260508-221119.json`
  (53MB, untrimmed; on user's machine only)

**Guide content**:
- `src/pflow/guide/features/caching.md` (249 lines; B-12 through B-15)
- `src/pflow/core/llm_capabilities.py` (the canonical model
  min-tokens table — B-12 should reference this not duplicate)

**Renderer code (likely fix sites for L-section)**:
- `src/pflow/core/cache_analysis/render_text.py` (L-10 suppression
  gate)
- `src/pflow/core/cache_analysis/analyze.py` (L-11 partial
  classification)
- `src/pflow/core/cache_analysis/cost_estimation.py` (A-3
  verification)
- `src/pflow/core/cache_analysis/warning_catalog.py` (catalog SSoT —
  21 IDs as of this commit)

**Run logs and case READMEs**:
- `.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/.run-log.md`
  (the recording I did, with stats)
- `.taskmaster/tasks/task_159/baseline/10-live-recordings/03-gemini-translation/README.md`
  (the smoke case I added)

---

## For the next agent

**Start by**:
1. Read `BASELINE-AUDIT.md` Section F (Triage notes) — it's the
   pre-digested decision matrix.
2. Read this braindump.
3. Verify A-3 (10 min) so it's off the "uncertain" list.
4. Plan the L-10/L-11/L-12 fix as a single coordinated batch — it's
   the biggest finding and the fix touches one suppression gate
   plus per-call rendering.

**Don't bother with**:
- JSON shape findings (Section D) — user explicitly deprioritized.
- Re-running the lyrics-generator end-to-end — case 05 captures it.
  Cost would be another $2.31 with no new info.
- Re-finding A-1 in different cases — it's locked in 3 already.
- Auditing the harness — verify.sh confirms 65/65 pass roundtrip.

**The user cares most about**:
- Text output, agent UX, correctness (his exact words).
- Bugs that affect the fresh-agent first-time experience (L-1, L-12
  fall here).
- The lyrics-generator workflow rendering correctly in trace mode
  (L-10 fall here).

**Stop and ask Andreas if**:
- A-3 producer-code reading is ambiguous (10 min should be
  conclusive though).
- The L-10/L-11/L-12 fix touches the catalog or trace format (per
  Task 159 design protocol, those need design review).
- You want to commit the 12MB trace fixture, gzip it, gitignore +
  manual recording, or use git-lfs. Open question.
- You find a NEW bug not in the audit that's mutation-contract-class
  (locks bad behavior in baselines).

**Don't stop for**:
- "Is this finding worth fixing?" — use Section F.
- "How should I structure the fix PR?" — your judgment.
- "Should I re-capture this baseline after fix?" — yes, always.

**Calibration from my audit**:
- I found 48 issues in ~6 hours including live runs.
- The 3 most important findings (L-10, L-11, L-12) came from the
  user reading the captured output for 1 minute.
- **If your triage takes more than 1 hour, you're overthinking it.**
  Section F is opinionated for a reason.

**Verification you've understood when ready**:

> **Note to next agent**: Read this document fully before taking any
> action. When ready, confirm you've read and understood by
> summarizing the key points, then state you're ready to proceed.
