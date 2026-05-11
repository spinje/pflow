# Braindump: Task 159 polish plan — for the agent picking up POLISH-PLAN.md

> Companion to `.taskmaster/tasks/task_159/baseline/POLISH-PLAN.md`. Read
> the plan for WHAT to fix; read this for HOW the plan came to be, where
> I was wrong, and what's hard to internalize from the docs alone.
>
> Don't expect this to be comprehensive — it's the residue from one
> long conversation. POLISH-PLAN.md has the structured information.

---

## Where I am

I'm the triage agent that produced POLISH-PLAN.md. I deployed 6 parallel
`pflow-codebase-searcher` investigators against thematic groups of
findings and synthesized their reports into the plan. I have not
written or verified any of the proposed fixes. My contribution is the
classification + complexity estimates + composition advice, NOT the
implementation.

**State of my understanding when this conversation ended:**

- Confident in: which fixes are renderer-only vs data-model edits, what
  the canonical lyrics-generator capture looks like, how the
  investigators were prompted (the pattern is reusable).
- Less confident in: the row.cost_usd batch double-count assumption,
  whether B-1 and B-19 are still real, the exact LOC estimates (most
  are from investigators' grep-based estimates, not implementation).
- Wrong about, then corrected: I removed A-4 from the original audit
  during initial triage; reading post-fix output as a fresh agent,
  A-4 was genuinely confusing. Reactivated. Also originally framed
  N-7 as "analyzer doesn't detect"; investigator showed it DOES
  detect, the gap is impact projection.

---

## User's mental model — exact words

The user is Andreas. He architected Task 159 and has run the
lyrics-generator workflow many times. Strong intuition for cost,
agent UX, and what "good output" feels like. Stated priorities,
verbatim:

- **"the json is not important here, the text output and agent ux and
  correctness is what matters, and actionable and easy to understand
  information"** — repeated multiple times. JSON-shape findings are
  deferrable.
- **"lets just doing the last verification before merge"** — initial
  framing. Signaled he expected this to be lightweight; the volume
  of issues surprised him too.
- **"lets take a step back"** — mid-conversation redirect. Signal
  that I'd been moving too fast and pattern-matching against existing
  categories instead of reading the actual output. Listen for these.
- **"Can you read the .taskmaster/.../expected-stdout.txt yourself
  and ground your recommendations in what you would read as
  incoherent and noisy, inaccurate as a new agent"** — the prompt
  that triggered the highest-yield work in the entire conversation.
  Reading raw output as a fresh agent surfaced N-1 through N-10.
- **"we should also remove any noise from the file, for example if
  we decide something is not important or if its a false positive
  etc"** — distinguishes "deferred" from "noise"; deferred items stay
  documented, noise gets deleted from the source doc.

He also edited POLISH-PLAN.md after I wrote it to add: **"do not read
this document, unless targeting a specific section"** to the header.
That's a signal about expected reading style — agents should treat the
plan as targeted lookup material, not linear reading. Design future
sections accordingly.

**Unstated priorities I read** (verify by behavior, not stated):

- He cares about pre-merge scrutiny but doesn't want analysis paralysis.
- He trusts running real workloads more than reading specs (spent
  $2.31 on a Gemini lyrics-generator run earlier in the project).
- He notices when output is "wrong" even when tests pass. The L-10
  finding ("0 opportunities") came from him reading captured output
  for 1 minute and asking "is there really 0?" That's a more powerful
  audit signal than any auditor.

---

## My triage mistakes (calibration data)

### 1. I removed A-4 as noise; it's real

Reasoning at the time: the audit author had self-downgraded A-4
in-line ("count is correct, the issue is rendered-structure mismatch").
I deleted the entry from BASELINE-AUDIT.md.

After the user redirected me to read the actual output: A-4 ("19
opportunities" with no section showing 19) is genuinely confusing.
Reactivated as part of Cluster E.

**Lesson**: when someone (including the audit author) "downgrades" a
finding, run the actual tool fresh before agreeing. The downgrade
might be wrong.

### 2. I anchored to existing audit categories

Initial response to "what's left to do" was a synthesis of B-section
+ C-section + L-section findings from the audit. The user redirected
me to read the captured output cold. That triggered N-1 through N-10
— 10 new findings, several of which (N-1, N-7) are higher-impact than
half the items I'd been recommending.

**Lesson**: the existing categories ARE sometimes the bug. Read raw
output before classifying.

### 3. I imposed "Tier 1 / Tier 2 / Tier 3" framing

User didn't ask for tiers; concrete impact statements would have been
clearer. I noticed myself reaching for this categorization and the
user's preference patterns suggest it added noise. Use ranked lists
with one-sentence justifications instead.

### 4. I trusted "9 merge-block bugs" count without verification

Audit said "9 code bugs to fix pre-merge." After source verification:
- L-1/L-2/L-12 collapsed to one root cause (per-call model rendering)
- L-9 was a pure dupe of A-1
- N-7 was reframed (detection works; impact projection missing)
- A-4 was wrongly removed by me

Net: closer to 5 distinct merge-block fixes than 9. Source-verifying
before recommending merge-block status would have caught this earlier.

**Lesson**: the audit author's confidence isn't transferable. Verify
each "merge-block" claim against source.

### 5. I missed B-4 in the investigator dispatch

When I deployed 6 parallel investigators, B-4 (3 near-identical batch
notes) wasn't included in any prompt. Realized after all reports came
back. The fix is probably trivial (mirror L-4's collapse pattern, ~10
LOC) but it's currently *assumed* not investigated.

**Lesson**: when grouping findings for delegation, do an explicit
"is every finding assigned" pass.

---

## What worked well (reusable patterns)

### The investigator delegation pattern

The 6 parallel `pflow-codebase-searcher` agents were the highest-yield
single decision in this conversation. ~5-7 minutes wall-clock per
agent, ran simultaneously, produced source-grounded reports with
file:line evidence.

The prompt shape that worked:
1. **Specific finding(s)** with audit-letter labels (B-2, N-8, etc.)
2. **Evidence from the capture**: paste the actual problematic output
3. **What I knew about the code so far**: prior context, file
   suggestions, things to investigate
4. **Investigative question**: "root cause + fix complexity + composition"
5. **Output format**: concise (under N words), file:line for every
   claim, structured per-finding

What I'd add next time:
- Explicit "is every finding assigned" check before launching
- Tell investigators to flag "I would need to verify before
  implementing" load-bearing assumptions (the cost-savings agent did
  this naturally with row.cost_usd; that pattern saved my plan)

### Source verification BEFORE classification

The verification round (after the user pushed back on my initial
"merge-block list") reframed N-7 substantially and confirmed the
others. ~30 minutes of source-reading saved hours of wrong
implementation effort.

**Don't recommend merge-block status without grep evidence.**

---

## Hard-to-find / hard-to-internalize patterns

### The `requires_complete_trace` catalog flag

The L-10/L-11 fix introduced `requires_complete_trace: bool = False`
on `CacheWarningSpec` (`warning_catalog.py`). It's a **new reusable
abstraction**: any future cache warning that should suppress in
truncated-trace mode just sets the flag — no need to touch
`_filter_trace_dependent_warnings`. Easy to miss if you didn't see
the implementation. Use it; don't add another filter path.

### "Honest unmeasurable" is load-bearing

Multiple PRs in this branch enforce: when data is absent, render `?`
or `n/a`, never fabricate. The F-04, A-6 fixes set this precedent.
N-1 and Cluster C MUST follow it (don't compute fake savings; fall
back to None when pricing unknown). The codebase is consistent; new
fixes shouldn't break it.

### The catalog is closed (DD#29)

Adding new catalog IDs needs design review. Extending existing IDs
(additive context fields, populating `savings_usd`, etc.) is cheap.
Cluster C deliberately picks Option A (enrich existing ID) over
Option B (new ID) for this reason. If a future agent reaches for a
new ID, stop and ask first.

### Pitfall #19 culture

Synthetic fixtures hide bugs. The codebase has been bitten 8+ times.
Every regression test must drive `analyze(...)` (or
`WorkflowRunner.run()`) end-to-end with REAL state — memo cache,
NamespacedSharedStore wrap, real trace files. The progress log has
the catalog of instances. Don't write synthetic-dict-fixture tests
for renderer behavior unless they're testing display logic
isolation; if you're testing emission paths, drive the real path.

### Composition order for B-2 + N-8

The investigator caught it; it's in the plan, but the meta-insight
is: when grouping operations exist at multiple axes, ORDER MATTERS.
Source-dedup before boundary grouping. Reverse order silently
defeats N-8 because the `(parent, child, line)` key keeps the 7
different `(child, line)` pairs visible. Test the ordering with a
multi-child fixture.

### The user prefers "working tool" over "working plan"

Multiple times he asked variants of "can you actually verify this in
the tool" rather than "what does the doc say." Spend cycles running
`pflow analyze-cache` on the lyrics-generator before/after each fix.
Don't trust the plan's complexity estimates without spot-checks.

---

## Open verification threads

These are NOT in POLISH-PLAN.md as concrete TODOs because they're
calibration / risk concerns, but they need attention.

### NEEDS VERIFICATION (load-bearing): row.cost_usd batch semantics

For Cluster B (N-1) — the fix subtracts excluded rows' costs from
total paid. If `row.cost_usd` for batch sub-workflow rows includes
children AND `actually_paid` sums all trace leaves (also including
children), simple subtraction is correct. If they're inconsistent,
double-subtraction.

The cost-savings investigator flagged this as the load-bearing risk
and explicitly couldn't verify in the time budget. **Before
implementing N-1**: build a heterogeneous batch fixture, assert
`row.cost_usd == Σ row.children.cost_usd` (or whatever the actual
contract is). One test reveals the answer.

### NEEDS VERIFICATION: B-1 might already be partially fixed

The L-1 fix promoted observed_models into the trace-mode header. But
the static-mode rendering (no trace, no `settings.default_model`)
might still show blank `model=` per-call rows. Verify with:

```bash
pflow analyze-cache --no-trace-autoload <workflow> \
    # ensure no settings.default_model in env
```

If still blank, B-1 is open. If it shows `<unresolved>` or similar,
it was implicitly fixed.

### NEEDS VERIFICATION: B-19 wording may be solved

The B-18 fix changed "no run history" → "memo cache empty (predicted-
key matching needs prior memo cache entries to compare against)". The
B-19 finding (the "no predicted cache_key" message conflicts with
visible cache_key in trace) might be similarly resolved by adjacent
wording changes. Read the current capture's Notes section before
treating it as open work.

### ASSUMPTION: B-4 collapse is similar to L-4

L-4 was the discrepancy-note collapse; the helper pattern is in
`analyze.py` (look for `_format_skipped_workflows_note` or similar).
B-4 (3 near-identical batch notes) probably uses the same shape.
Investigator wasn't asked. **Verify the helper exists and is reusable
before estimating effort.**

### NEEDS VERIFICATION: pricing per provider for Cluster C

The N-7 fix computes `savings_usd = calls × tokens × cache_read_factor`.
For Anthropic, cache_read_factor = 0.1× input rate (documented). For
Gemini and OpenAI, the factor differs and might not even apply
(OpenAI's `prompt_cache_retention` is structurally different from
Anthropic's `cache_control`). **Read `cost_estimation.py::get_model_pricing`
before implementing.** If a model's cache_read_factor isn't reliable,
fall back to `savings_usd=None` for that row's contribution.

---

## Ambiguities and assumptions

### UNCLEAR: A-4 fix shape

The plan recommends Option (a): split the count line ("2 actionable +
17 boundary findings (19 cache-domain info)"). The audit suggested
Option (b): exclude renames from headline count. Both are defensible.
I picked (a) because it's purely additive and doesn't break JSON
consumers reading `info_count`.

If the user prefers (b) when reviewing the PR, the fix is structurally
larger because it changes the JSON contract. Ask before committing.

### UNCLEAR: N-7 Option A vs Option B

I recommended Option A (enrich existing `cache.sub-workflow-cache-undeclared`
with savings) over Option B (new catalog ID `cache.high-leverage-uncached`).
Option A is smaller and doesn't need DD#29 review. Option B fires for
solo high-call high-token nodes that don't have shared content (which
Option A doesn't catch).

The user might prefer Option B if "the analyzer should recommend
caching ANY high-leverage node" is the desired behavior. This is a
product decision, not a code decision. **Ask before implementing if
unsure.**

### ASSUMPTION: render_text.py is the right place for all renderer fixes

I haven't checked if any renderer logic spilled into `view_helpers.py`
or other files. Most fixes assume `render_text.py` is the locus.
Verify with grep before each PR.

### UNCLEAR: how baselines drift compose across PRs

I estimated each cluster's baseline drift independently. They overlap
heavily (lyrics-generator captures hit by multiple clusters). If you
land all 5 PRs sequentially, the same case is regenerated 3-4 times.
This is fine — but coordinate with anyone else working on this branch
to avoid merge conflicts in `expected-stdout.txt` files.

---

## Unexplored territory

### MIGHT MATTER: Task 160 will mass-drift baselines

Task 160 is the analyzer architectural refactor. It will restructure
section ordering, possibly change column widths, and trigger
mass-drift in `expected-stdout.txt` baselines. Worth investing in a
"shape-only" testing layer (assert structure, not exact strings)
BEFORE Task 160 starts, so the polish PRs don't get re-litigated.

This isn't in POLISH-PLAN.md because it's adjacent work, not Task 159
polish. But if a Task 160 stage starts before the polish PRs land,
expect baseline rebases.

### CONSIDER: JSON_FORMAT_VERSION transition at merge

Currently 4.1 within-branch. The discipline has been "no version
bumps for additive changes within the same minor" because consumers
don't exist yet. Once Task 159 merges, external consumers exist (MCP
clients, agent scripts). Document this transition somewhere — the
within-branch staging discipline ends; future additive changes
should bump 4.1 → 4.2.

### UNEXPLORED: cache: vs prompt_cache: interaction surface

Existing tests cover the orthogonality (DD#5: memo opt-out is
independent from provider prompt cache). Nothing in the polish queue
exercises the interaction surface. If a workflow has both `cache:
false` AND `prompt_cache: [...]`, does the analyzer correctly
recognize that memo is disabled but provider caching is active? Worth
a smoke test.

### UNEXPLORED: MCP `analyze_cache` parity

The fixes are scoped to `pflow analyze-cache` text + JSON output. The
MCP `analyze_cache` tool consumes the same `analyze()` + `render_json()`
path so JSON changes propagate naturally. But the MCP docstring
documents specific fields; if Cluster B adds `excluded_nodes` to
`CostDelta`, the MCP docstring needs updating too. Check
`mcp_server/tools/execution_tools.py` after each PR that changes JSON
shape.

### MIGHT MATTER: error message rendering when no memo cache exists

I noticed but didn't investigate: a fresh agent running their first
workflow then immediately running `pflow analyze-cache` will see
"memo cache empty" + "predicted-key matching unavailable" notes.
First-time UX. The wording is OK after B-18 fix but might still be
off-putting. Verify with a fresh-env smoke test (clear `~/.pflow/`
before invoking).

---

## What I'd tell myself starting over

1. **Read the lyrics-generator capture FIRST**, before any audit
   reading. The audit categories are sometimes the bug.

2. **Run `pflow analyze-cache` on a representative workflow** before
   every classification decision. The user's "is there really 0
   opportunities?" question would have caught L-10 instantly if I'd
   done this.

3. **Don't anchor to "merge-block" framing without verification.** The
   audit's count was off. Source-verify each merge-block claim before
   committing to it.

4. **When the user says "step back" — actually step back.** Don't just
   swap the framing of what you were doing. Reground in primary
   evidence (raw output).

5. **Distinguish "downgrade" from "false positive."** A downgraded
   finding might still fire on real output. Verify before deleting.

6. **Use parallel investigators earlier.** I should have launched the
   6-investigator wave BEFORE attempting any triage, not after.
   Source-grounded fix complexity should drive triage, not the
   reverse.

7. **The user prefers concrete impact statements over tier
   categorizations.** "Saves agents from skimming past 75 lines of
   noise" beats "Tier 1 fix."

---

## For the next agent

**Start by**:

1. Read the lyrics-generator captures (`12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt`
   AND `10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`)
   line by line. Don't skim. The friction points are visible if you
   read as a fresh agent.
2. Read POLISH-PLAN.md targeted at the cluster you're starting with
   (the user's edit confirmed: "do not read this document, unless
   targeting a specific section").
3. Run `make test` and `./.taskmaster/tasks/task_159/baseline/verify.sh`
   to confirm clean starting state before touching anything.
4. Pick Cluster A (cross-workflow grouping) for your first PR. It's
   renderer-only, no test breakage, single biggest visible improvement.

**Don't bother with**:

- Re-doing the audit — POLISH-PLAN.md has the structured findings
- JSON-shape findings unless the user explicitly asks
- The deferred secondary backlog before primary clusters land
- Re-running the lyrics-generator end-to-end ($2.31 per run; the
  trace fixture at `_shared/fixtures/live-gemini-lyrics-generator.trace.json`
  is sufficient)

**The user cares most about**:

- Text output that an AI agent would find actionable and easy to
  understand
- Correctness over cleverness
- Bugs that affect first-time-agent first-contact experience (L-10,
  L-12, A-4)
- Fixing things at the source (N-8) rather than working around them

**Stop and ask Andreas if**:

- A-4 fix shape is unclear (split count vs change `info_count`
  semantics)
- N-7 should be Option A (enrich existing) or Option B (new catalog
  ID)
- Pre-flight verification reveals the row.cost_usd assumption is
  wrong (Cluster B needs a different fix path)
- You find a NEW bug not in the plan that locks bad behavior in
  baselines
- You hit DD#29 territory (new catalog IDs)

**Don't stop for**:

- "Is this finding worth fixing?" — POLISH-PLAN.md classified it
- "How should I structure the fix PR?" — your judgment
- "Should I re-capture this baseline after fix?" — yes, always
- Pure formatting / lint / type errors during implementation

**Calibration from my conversation**:

- I produced ~10 hours of work over the conversation; ~30 min of that
  was the parallel-investigator wave that produced 80% of the
  source-grounded value. Use the same pattern when in doubt.
- The user surfaced the most consequential findings (L-10, L-11,
  L-12, plus the redirect that produced N-1 through N-10) by reading
  output for ~5 minutes total. Treat user observations as
  high-bandwidth signal.
- POLISH-PLAN.md has my best estimates. Treat them as 70% confidence
  estimates. Spot-check before committing time.

---

## Relevant files and pointers

**Authoritative for forward work**:
- `.taskmaster/tasks/task_159/baseline/POLISH-PLAN.md` — the plan
- `.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`
  — canonical real-world capture
- `.taskmaster/tasks/task_159/baseline/12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt`
  — static-mode counterpart

**Historical (don't act on directly)**:
- `.taskmaster/tasks/task_159/baseline/BASELINE-AUDIT.md` — deprecated
  but historically accurate; skim Section F if you want to see what
  was triaged where
- `scratchpads/handoffs/task-159-baseline-audit-triage.md` — the
  handoff from the audit-author agent to me. Useful context for
  understanding how A-4 and other findings evolved.
- `.taskmaster/tasks/task_159/implementation/implementation-progress-log.md`
  — 9,936 lines, only read if you need specific implementation
  history. The recent entries (~9530+) cover the L-batch and bonus
  polish.

**Hot files for fixes** (most clusters touch these):
- `src/pflow/core/cache_analysis/render_text.py`
- `src/pflow/core/cache_analysis/analyze.py`
- `src/pflow/core/cache_analysis/CLAUDE.md` (read before changing
  analyzer)

**Don't touch unless explicitly required**:
- `src/pflow/core/cache_analysis/warning_catalog.py` (closed catalog;
  DD#29 review for new IDs)
- `src/pflow/core/cache_render.py` (rendering hot path; load-bearing
  byte-identity invariants)

---

## Final honest confidence breakdown

| Cluster | My confidence | Why |
|---|---|---|
| A — Cross-workflow grouping | 85% | Investigator confirmed renderer-only, data already groupable |
| B — Cost-savings honesty | 65% | row.cost_usd assumption unverified; reframing is right |
| C — Recommendation impact | 70% | Reframed mid-conversation; pricing per provider unverified |
| D — Header + per-call clarity | 80% | All renderer-only, well-scoped, multiple investigators concur |
| E — Section organization | 65% | A-4 fix shape is opinionated; user might prefer different framing |

If forced to pick the SAFEST first PR: **Cluster A**. Renderer-only,
data already groupable, zero test breakage, single biggest visible
improvement. Ships in 2-3 hours.

If forced to pick the HIGHEST IMPACT first PR: **Cluster A or B**.
B has higher correctness impact (the contradictory headline) but
needs the row.cost_usd verification first.

If you want to delay merge: **don't ship anything**. Task 159 IS
mergeable as-is (per the merge-block batch landing). POLISH-PLAN is
v1.x polish. Don't conflate "should ship eventually" with "blocks
merge."

---

> **Note to next agent**: Read this document fully before taking any
> action. When ready, confirm you've read and understood by
> summarizing the key points, then state you're ready to proceed.
