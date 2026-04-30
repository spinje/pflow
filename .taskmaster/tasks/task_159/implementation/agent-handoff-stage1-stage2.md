# Handoff: Stage 1 wrap + Stage 2 verification

You're picking this up cold. The cache analyzer's Stage 1 work is essentially
done — Path 1 (file resolution centralized), Tier 1 fixes (4 issues), and
CP5 (agent-UX message clarity pass) all shipped. The output is now genuinely
agent-actionable on the lyrics-generator workflow. Two small UX nits remain
flagged by the user (Concerns A + B below).

Your mandate, in order:

1. **Address the two remaining UX nits** (Concerns A + B). Together
   ~1-2 hours. Surface designs to the user before committing.
2. **Stage 2** — real LLM verification on lyrics-generator. Sub-workflow
   standalone runs first, then full pipeline. Expected ≥40% input-cost
   reduction per spec line 1030.
3. **Architectural decisions** — three open questions documented at the
   end. Not Stage 2 blockers.

> **Detailed account of what each pass changed lives in
> `implementation-progress-log.md`** (Path 1, Tier 1, CP5 entries). This
> doc only carries forward-facing context.

---

## Where the branch is right now

```
git log --oneline -5
[head]    [unstaged] CP5 — agent-UX message clarity (Pass 1+2+3)
[parent]  [unstaged] Tier 1 AG/UX fixes (4 issues) + CP1-4 (issues 8/11/3/4/16/9/7/6+13)
a3044f42  refactor: centralize file resolution at resolve_workflow boundary  ← Path 1
11230abb  task 159: verification-specialist CLI drill — fix bugs A/B/G + E/F/G
b38ae7c5  task 159: post-recommendations 4-agent review fixes
```

**Working tree is unstaged** — the user controls when to commit. CP1-CP5
work has not been broken into separate commits; the user may choose
single-commit or multi-commit.

State:
- 6,000 tests passing, 9 skipped
- `make check` clean (ruff + ruff-format + mypy + deptry)
- `test_plan_drift.py` 34/34 green
- `test_golden_baseline_hashes_match` (DD#19) green
- 13 catalog IDs (added `cache.consolidate-to-root-recommended` in CP3)

GH issues filed during Stage 1 (still open):

- **#361** — Path 2 architectural umbrella (closes #321 + #334 in lockstep
  when complete). Path 1 is the first slice.
- **#362** — Cross-workflow rename signal/noise. **CLOSED in this branch**
  by Tier 1.1 fix.
- **#357 (closed)**, **#358 (open, v1.x — image+prewarm)**, **#359 (open,
  v1.x — LiteLLM stderr noise)**, **#360 (open, v1.x — dynamic batch-size
  cost undercounting)**.

---

## The two open UX nits (your immediate Stage-1 wrap)

User reviewed the CP5 output, found it dramatically improved, and flagged
these two as still imperfect. Both have design questions — surface a
specific shape to the user before coding.

### Concern A — `[cache.shared-context-undeclared]` ID still visibly opaque

After CP5, every Recommended Action AND every Sub-workflow boundary line
shows the bracketed ID. Spec DD#27 makes IDs first-class for machine
filtering, but the user's feedback is that the rendered TEXT shouldn't
require ID-lookup to be readable.

**Three shapes worth pricing:**

1. **Drop brackets from text, keep in JSON.** Users running
   `--format=json` get the granular ID; text consumers see only the
   message. ~10 LOC + test updates.
2. **Replace with human-readable category prefix.** E.g. `[shared context
   undeclared]` instead of `[cache.shared-context-undeclared]`. Reads
   naturally without losing meaning. ~30 LOC (per-id mapping).
3. **Move ID to less prominent position.** Keep at end of bullet as
   `... (id: cache.shared-context-undeclared)` so it's discoverable but
   not the first thing read. ~15 LOC.

I lean (3) — preserves the discoverability without dominating the read.
But this is the user's call.

### Concern B — `cacheable=0 ratio=0%` in per-call report unexplained

The per-call section header explainer addresses `ratio=0%` ("always 0%
pre-cache") but `cacheable=0` has no context. In greenfield mode,
`cacheable_tokens_estimated` is always 0 because no node has declared
`prompt_cache:`. Agents reading the table can't tell whether
`cacheable=0` means "no opportunity" or "we haven't measured it yet" —
neither is right; it means "no declared subset, so cacheable token count
is 0 by construction."

**Three shapes worth pricing:**

1. **Drop the `cacheable` column from greenfield rendering** (always 0,
   so the column is noise). Steady-state mode keeps it. ~15 LOC.
2. **Render `cacheable=—` in greenfield**. Distinguishes "0 by definition"
   from "0 measured." ~10 LOC.
3. **Add column legend below per-call header.** "cacheable = tokens
   covered by declared `prompt_cache:` subsets" — explains what the
   column means without changing values. ~10 LOC.

I lean (1) — the column genuinely has no information in greenfield.
Top-10% codebases (mypy, ruff) hide columns when they're useless rather
than padding with empty values.

### Test strategy for Concerns A + B

Same pattern as CP5: behavioral tests with mutation-test docstrings.
Don't add tests just for coverage — focus on:
- The new rendering produces the new shape
- The OLD rendering would fail an assertion (regression gate)
- JSON output is unaffected (machine-readable contract preserved)

Use `test-writer-fixer` if needed but most renderer assertions are
simple substring checks; inline updates are fine.

### Once both concerns ship

Re-run `pflow analyze-cache` against all 4 lyrics-generator targets +
brownfield smoke. Compare with `scratchpads/lyrics-generator-stage1/POST-CP5-*.txt`.
Save POST-STAGE1-FINAL-*.txt. Confirm with user before Stage 2 spend.

---

## Stage 2: real LLM verification on lyrics-generator

Once Stage 1 is locked, validate the value prop. Spec target: **≥40%
input-cost reduction with `## Cache` declared, ≥70% on rerun within 1h**.

### Cost recalibration

Lyrics-generator CLAUDE.md states: **~$1.80 per run, ~380 seconds**.
Cheaper than spec's $2-5 estimate because the workflow uses Gemini Flash
by default, not Anthropic Sonnet. So 5 full runs ≈ $9.

### Provider caveat that matters

Default model is Gemini (with `gemini/gemini-3.1-pro-preview` explicitly
on `write-lyrics`, `rewrite-emotional`, `rewrite-craft`). The caching
guide notes:

> Gemini telemetry caveat — `cache_creation_input_tokens` is 0/absent
> even when caching is working; verify via `cache_read_input_tokens` on
> subsequent calls.

So **don't verify cache via `cache_creation_input_tokens` alone** on this
workflow. Compare total cost RUN1 vs RUN2 OR read
`cache_read_input_tokens` on the second call.

For cleaner verification, ALSO run a small Anthropic-only fixture in
parallel (the verification-specialist drill pattern). Anthropic has
clean cache reporting.

### Recommended Stage 2 ordering — cheapest to most expensive

**Stage 2.1 — `song-creator` standalone (highest leverage, ~$1)**

```bash
pflow /path/to/lyrics-generator/song-creator/song-creator.pflow.md \
  concept='{"title":"Test","core_idea":"...","angle":"...","genre_family":"folk","narrator_hint":"observer","narrator_type":"natural","reasoning":"..."}' \
  concept_brief='<10k tokens of palette text>'
```

Cost baseline (no `## Cache`): ~$0.50/run. Capture trace.

Then add the suggested `## Cache` block from analyze-cache output.
Run again within 5 min: target ~$0.30 (40% reduction).
Run3 within 1h with `- ttl: 1h`: target ~$0.15 (70% reduction).

This is the cheapest path to value-prop verification — ~$1 total.
Validates the cache rendering layer (Segments 2-3 of Task 159) actually
delivers savings on a real workflow.

**Stage 2.2 — `chorus-chooser` standalone (~$1, prewarm + auto-batch-prefix)**

The `score-choruses` node is the canonical 34-item batch with ~2k-token
static rubric — spec mode-1 prewarm test. **CAVEAT: see "Architectural
concern 2" below — the analyzer can't recommend prewarm here today
because the prompt is `${item.prompt}` (built in Python).** Stage 2.2
still validates that prewarm WORKS at runtime even if the analyzer
can't suggest it; manually add `- prewarm: true` to score-choruses and
measure.

**Stage 2.3 — Full lyrics-generator (~$6, final verification)**

Only after 2.1-2.2 confirm. Run with `## Cache` blocks declared
everywhere recommended, plus prewarm where applicable. Verify ≥40%
overall reduction, ≥70% on rerun.

**Total Stage 2 spend: $8-10.**

### What to capture per Stage 2 run

For each run:

1. Total LLM cost (from trace's per-node cost summary)
2. Per-node `cache_creation_input_tokens` (Anthropic) or
   `cache_read_input_tokens` (Gemini)
3. Trace file for `--from-trace` discrepancy analysis
4. `pflow analyze-cache --from-trace <trace>` output — verify discrepancy
   detection flags any mismatches

Save runs to `scratchpads/stage2-verification/run-N-{baseline|cached|rerun}/`.

### Failure cases to watch for

- **First run 0% savings**: cache rendering didn't fire. Check
  `cache_render` IR populated; verify `__pflow_cache_render__` in shared.
- **Provider response shape mismatch**: LiteLLM might handle Gemini cache
  differently. Compare with Anthropic-only fixture.
- **Cross-workflow byte mismatch**: if song-creator's `## Cache` declares
  prose labels diverging from chorus-chooser's, cross-workflow cache hits
  fail. Use `analyze-cache --from-trace` to detect — exactly the case
  `cache.discrepancy` is for.
- **TTL expiry**: 5-min default may expire between baseline and cached
  run. Use `- ttl: 1h` if iteration is slow.

---

## Architectural concerns (decisions on the table — not Stage 2 blockers)

### Concern 1 — Catalog redesign: rename → discrepancy fold?

The Tier 1 #362 fix made `cache.cross-workflow-rename-detected` fire only
with evidence (`## Cache` declared on at least one side). Once trace data
is available, the SAME concern is detectable as a `cache.discrepancy` with
"cross-workflow byte mismatch" root cause — evidence-based, attributed
to a real cache miss.

Should the catalog drop `cache.cross-workflow-rename-detected` entirely
and fold it into `cache.discrepancy`'s root_cause enum?

- **Pros**: catalog 13 → 12 (DD#29 closed list); fewer ways to express
  the same concern; users see findings only with evidence.
- **Cons**: loses static-only detection (when no trace exists). But
  that's the same case my Tier 1 fix gates on — if no `## Cache`
  declared, suppressed anyway. Static detection is only relevant in a
  narrow state: `## Cache` declared but no trace yet.

Discuss with user. If yes, this is a catalog redesign (DD#29 review).

### Concern 2 — Python-assembled prompts limit detection

`chorus-chooser`'s `score-choruses` node is a 34-item batch with a 2k-token
static rubric (the spec mode-1 prewarm canonical example). **The analyzer
can't detect it** because the prompt is `${item.prompt}` — assembled in
Python by the upstream `build-scoring-items` code node.

This compounds with #362 — the most batch-prewarm-relevant case in the
spec example IS exactly this Python-assembled pattern.

**Three directions:**

1. **Document as a limitation.** Add a Notes-section line: "Prompts
   assembled in Python code nodes are invisible to static analysis. Use
   `pflow analyze-cache --from-trace <path>` after a real run for
   evidence-based prewarm recommendations."
2. **Detect statically.** When `params["prompt"] == "${item.X}"` AND an
   upstream code node produces items with `prompt` field, walk to the
   code node's output. Hard — requires Python AST analysis.
3. **Run-once detection.** After memo data exists, the analyzer reads
   the actual rendered prompt from MemoizationCache. Half-static,
   half-evidence.

Recommend (1) for v1; consider (3) for v1.x. Either way, document.

### Concern 3 — Path 2 architectural cleanup (#361)

Path 2 extends the `ResolvedWorkflow` boundary contract to also pre-compile
sub-workflows (closes #334) and bake output-exposure rules + cycle
detection state (closes #321). One PR closes three issues.

**Estimated scope** (per #361): ~280 LOC + ~10 tests, 1-2 days.

Path 2 is NOT blocking Stage 2. But it's the architecturally correct
end-state. Consider tackling Path 2 BEFORE merging this branch if the
user wants the architectural slice complete.

---

## Tacit knowledge specific to CP5 (the colleague-walking-in stuff)

> Earlier-pass tacit knowledge (Path 1, Tier 1) is in the corresponding
> progress log entries. This section is CP5-specific.

**1. The catalog message-template lens.** When you touch a template, ask:
"does this answer what / why / how-to-fix in plain language?" If any is
missing, the template needs work. CP5 rewrote 3 templates that failed the
test (shared-context-undeclared, padding-advisory message, batch-prewarm
suggestions). The remaining 9 templates passed CP5's audit but re-audit
when you touch them — agent UX expectations evolve.

**2. `child_workflow` in context is the boundary-template trigger.** When
adding new emission sites for `cache.shared-context-undeclared`, decide
whether you're emitting workflow-scope (don't pass `child_workflow`) or
boundary-scope (pass `edge.child_workflow`). The dispatch in
`make_diagnostic` is automatic; the emission site controls which form
fires. Document at the call site.

**3. `savings_clause` vs `savings_str` are NOT interchangeable.** The
former is the parenthetical form (`" (saves $X.XX/run)"` or empty); the
latter is the bare amount (`-$0.45` or `"savings unavailable"`).
Embedding `savings_str` in `(saves {savings_str}/run)` reproduces the
grammar bug we fixed. Use `savings_clause` for any inline parenthetical;
use `savings_str` only when None-fallback to `"savings unavailable"`
text is acceptable in context.

**4. Cross-workflow finding renderers pull from `diag.context` directly.**
The catalog message text is rich for recommendations + JSON, but
duplicates context the section header already provides. Each finding
type has its own renderer (`_format_value_flow_finding`,
`_format_rename_finding`, `_format_prose_mismatch_finding`). New finding
types added later need new renderers — pattern is consistent and
mechanical.

**5. RecommendedAction.message is a NEW field as of CP5.** Existing
tests that constructed RecommendedAction without `message=` still work
(default empty string). But for behavioral tests verifying rendered
output, populate it. The renderer indents the message under the scope
line; long messages wrap.

**6. Stage 1 mostly polish-complete.** Path 2 is genuine architectural
work; Concerns A + B are 1-2 hour polish; Concerns 1-3 are open
decisions. Stage 2 verification is the next major gate. Don't sink
more time into rendering polish without user direction — diminishing
returns territory.

---

## Quick-start commands

```bash
# Verify the branch state
git log --oneline -5
make test                   # expect 6,000 passing, 9 skipped
make check                  # expect all green

# Re-run the canonical analyze-cache smoke test
uv run pflow analyze-cache /path/to/lyrics-generator/song-creator/song-creator.pflow.md --no-trace-autoload

# Compare with the post-CP5 baseline
diff scratchpads/lyrics-generator-stage1/POST-CP5-song-creator.txt <(uv run pflow analyze-cache ...)

# Find Concern A fix sites
grep -n "warning_id" src/pflow/core/cache_analysis/render_text.py

# Find Concern B fix sites
grep -n "cacheable=" src/pflow/core/cache_analysis/render_text.py
```

---

## Final ask

Before committing CP5, the user wants Concerns A + B addressed (or
explicitly deferred with a documented reason). Once those are in,
the user controls commit shape (single CP5 commit vs multiple).

After commit, surface to the user **before**:
- Stage 2 spending
- Touching the catalog (DD#29 design review territory)
- Any architectural decision (Concerns 1-3)

The user explicitly cares about: agent-actionable output on real
workflows. Every UX decision evaluated through that lens.

Good hunting.
