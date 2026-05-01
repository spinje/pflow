# Handoff: Stage 1 wrap + Stage 2 verification

You're picking this up cold. The cache analyzer's Stage 1 work is **complete**:
Path 1 (file resolution centralized), Tier 1 fixes (4 issues), CP5 (agent-UX
message clarity), and the Stage-1 final pass (Concerns A + B + Option C —
drop bracketed IDs, headlines via catalog SSoT, hide per-call rows without
real data). The output is genuinely agent-actionable on lyrics-generator.

Your mandate, in order:

1. **Stage 2** — real LLM verification on lyrics-generator. Sub-workflow
   standalone runs first, then full pipeline. Expected ≥40% input-cost
   reduction per spec line 1030.
2. **Architectural decisions** — three open questions documented at the
   end. Not Stage 2 blockers.

> **Detailed account of what each pass changed lives in
> `implementation-progress-log.md`** (Path 1, Tier 1, CP5, Stage-1 final).
> This doc only carries forward-facing context.

---

## Where the branch is right now

```
git log --oneline -5
fa0b93f7  task 159 stage-1 final: drop bracketed IDs + headlines + Option C row filter
17ed9e73  task 159 CP1-5: lyrics-generator stage 1 — agent-actionable analyze-cache output
0c1e46db  fix: tier 1 AG/UX issues in pflow analyze-cache (closes #362)
a3044f42  refactor: centralize file resolution at resolve_workflow boundary
11230abb  task 159: verification-specialist CLI drill — fix bugs A/B/G + E/F/G
```

**All Stage-1 work committed.** Working tree clean.

State:
- 6,001 tests passing, 9 skipped
- `make check` clean (ruff + ruff-format + mypy + deptry)
- `test_plan_drift.py` 34/34 green
- `test_golden_baseline_hashes_match` (DD#19) green
- 13 catalog IDs, each with a `headline_template` (Stage-1 final pass)
- JSON_FORMAT_VERSION 1.1 (semantic shift on `per_call.cacheable_tokens_estimated`)

GH issues:

- **#361** — Path 2 architectural umbrella (closes #321 + #334 in lockstep
  when complete). Path 1 is the first slice. **Open, not blocking Stage 2**.
- **#362** — Cross-workflow rename signal/noise. **CLOSED** by Tier 1.1 fix.
- **#363** — shared-prose detection (v1.x — complements `${var}` reference
  detection by catching repeated raw text across prompts). **Filed during
  Stage-1 final pass; v1.x.**
- **#357 (closed)**, **#358 (open, v1.x — image+prewarm)**, **#359 (open,
  v1.x — LiteLLM stderr noise)**, **#360 (open, v1.x — dynamic batch-size
  cost undercounting)**.

---

## What shipped in the Stage-1 final pass (commit `fa0b93f7`)

**Concern A — bracketed `[cache.X]` IDs dropped.** Catalog has new
`headline_template` field per ID; rank lines lead with the headline
(`<category> — <action>` pattern). `resolve_headline_for(diag)` is the
SSoT — works for both `make_diagnostic` and direct `Diagnostic(...)`
construction (validator emitters in `data_flow.py` get headlines via
the catalog now). Per-call notes column strips `cache.` prefix.

**Concern B + Option C — greenfield per-call rows hide when no real data.**
`_estimate_ref_tokens` returns `int | None`; `PerCallRow.cacheable_tokens_estimated`
and `cache_ratio_pct` are nullable. New `_row_has_real_data` predicate
filters rows; section hidden entirely when all rows fail; Notes entry
explains the absence. Steady-state and post-run rows show real numbers.

**JSON 1.0 → 1.1**: semantic shift on `per_call.cacheable_tokens_estimated`
documented in module docstring.

Snapshots saved at `scratchpads/lyrics-generator-stage1/POST-STAGE1-FINAL-*.txt`.

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

**6. Stage 1 is complete.** All UX polish shipped in commit `fa0b93f7`
(Concerns A + B + Option C). Stage 2 verification is the next gate.
Don't sink more time into rendering polish without user direction —
diminishing returns territory.

**7. Catalog headlines are SSoT via `resolve_headline_for(diag)`.** When
adding a new catalog ID, populate `headline_template` alongside the
other fields. The renderer reads via the helper — works for diagnostics
constructed outside `make_diagnostic` too. See progress log entry
"Stage-1 final UX pass" for the structural defense.

---

## Quick-start commands

```bash
# Verify the branch state
git log --oneline -5
make test                   # expect 6,001 passing, 9 skipped
make check                  # expect all green

# Re-run the canonical analyze-cache smoke test
uv run pflow analyze-cache /path/to/lyrics-generator/song-creator/song-creator.pflow.md --no-trace-autoload

# Compare with the post-Stage-1-final baseline
diff scratchpads/lyrics-generator-stage1/POST-STAGE1-FINAL-song-creator.txt <(uv run pflow analyze-cache ...)
```

---

## Final ask

Surface to the user **before**:
- Stage 2 spending
- Touching the catalog (DD#29 design review territory)
- Any architectural decision (Concerns 1-3)

The user explicitly cares about: agent-actionable output on real
workflows. Every UX decision evaluated through that lens.

Good hunting.
