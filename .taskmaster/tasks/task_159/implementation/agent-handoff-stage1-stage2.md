# Handoff: Stage 1 finish + Stage 2 verification

You're picking this up cold. The cache analyzer feature shipped in Task 159
B-G + recommendations-section follow-ups. Then Stage 1 verification on the
lyrics-generator workflow exposed two architectural surfaces (file resolution
at boundary + AG/UX issues in the analyzer's output). This document covers
**everything found**, fixed and not-yet-fixed. Nothing was filed as v1.x —
everything is on the table for you.

Your mandate, in order:

1. **Finish lyrics-generator Stage 1** — make the analyzer's output on the
   canonical real workflow as agent-actionable as v1 should be. 9 issues
   remain (Tier 2 + Tier 3). Listed below.
2. **Stage 2** — real LLM verification on lyrics-generator. Sub-workflow
   standalone runs first, then full pipeline. Expected savings ≥40% per spec
   line 1030.
3. **Architectural decisions** — three open questions are documented at the
   end. They're not blockers for Stage 2 but worth surfacing before merge.

---

## Where the branch is right now

```
git log --oneline -5
a3044f42 refactor: centralize file resolution at resolve_workflow boundary  ← Path 1
[next-commit] tier 1 AG/UX fixes (4 issues)                                 ← THIS PR
11230abb task 159: verification-specialist CLI drill — fix bugs A/B/G + E/F/G
b38ae7c5 task 159: post-recommendations 4-agent review fixes
e456b2a0 test quality fixes
```

State:

- 5,967 tests passing, 9 skipped
- `make check` clean (ruff + ruff-format + mypy + deptry)
- `test_plan_drift.py` 34/34 green
- `test_golden_baseline_hashes_match` (DD#19) green
- Mutation-tested all new contract tests

GH issues filed by this session:

- **#361** — Path 2 architectural umbrella (consumer-applies-X pattern). Closes
  #321 + #334 in lockstep when the boundary contract is complete. Path 1
  (this commit) is the first slice; Path 2 is open.
- **#362** — Cross-workflow rename signal/noise. **CLOSED in this PR** by
  the Tier 1.1 fix. Issue stays open until merge so the GH-link from the
  PR auto-closes it.

No other issues filed. The user explicitly said: "There are no v1.x issues
right now, everything should be up on the table for the next agent." If you
hit something new, document it in this branch's handoff or the progress log;
don't file as a v1.x deferral.

---

## What this PR did

### Path 1 (commit `a3044f42`) — File resolution centralized at `resolve_workflow()`

The bug surfaced when `pflow analyze-cache` returned `tokens=7` for a 3,752-token
prompt: it was tokenizing the literal filename `./write-lyrics.prompt.md`
instead of the file content. Three production sites
(compiler / runner / validator) called `core/file_resolver.py::resolve_file_references`
independently; the analyzer was a fourth consumer that didn't get the call
and silently broke.

Fix: centralize at `resolve_workflow._try_load_from_file` and `_load_library_workflow`
(latter guarded on `path.exists()` for mocked-WorkflowManager test isolation).
Runner's redundant call deleted; compiler's call kept (serves sub-workflow
children loaded by `WorkflowExecutor` — different IR-load boundary).

The contract is locked structurally by `tests/test_execution/test_workflow_resolver_contract.py`.
If a future contributor re-introduces "consumer applies file resolution"
anywhere, that test fails with a diagnostic pointing at the boundary.

### Tier 1 AG/UX fixes (this commit)

Four issues that produce wrong/buried/incomplete findings to agents on real
workflows. All fixed:

| Issue | What was wrong | Fix |
|---|---|---|
| **#362** rename detector flood | 23 false-positive `cache.cross-workflow-rename-detected` warnings on lyrics-generator | Suppress when (a) parent value is batch-alias root or (b) neither side has `## Cache`. Framed as "evidence-basis principle" — predictive warnings only fire when state to compare exists. |
| **#1** sort burying actionable | Alphabetical tie-break put rename-detected (info) ahead of shared-context-undeclared (info) | New `RECOMMENDED_ACTION_PRIORITY` dict in `warning_catalog.py`. Sort key: `(severity, priority, savings, id)`. Tier-1 actionable IDs get priority 10; informational IDs get 50. |
| **#2** workflow-level scope unrendered | Workflow-level findings (node_id=None) rendered without scope info, indistinguishable from per-node | New `RecommendedAction.scope_workflow` field. Renderer outputs "Workflow: <basename>" when set. JSON consumers dispatch on (node_id, scope_workflow) — at most one is non-null. |
| **#10** `(line 0)` placeholder | Cross-workflow output showed `(line 0)` for every boundary — `_source_line` was None on workflow-type nodes | Parser now sets `node["_source_line"] = entity.heading_line` in `_build_node_dict`. Schema updated. Fixed at the data layer (consistent for all consumers). |

**Mutation-tested all four** — reverting any fix makes its specific test fail
with a clear diagnostic.

### Verified output on lyrics-generator (post-Tier 1)

```
$ pflow analyze-cache /path/to/lyrics-generator/song-creator/song-creator.pflow.md --no-trace-autoload
# Cache Analysis: ...

  ~7 LLM calls · 1 models in use
  Confidence: low_no_data

## Summary
  Current cost per run:        unavailable
  ...
  4 opportunities (0 warnings, 4 info)

## Recommended actions (ordered by impact)
  1. [cache.shared-context-undeclared]  savings unavailable
     Workflow: song-creator.pflow.md
  2. [cache.shared-context-undeclared]  savings unavailable
     Node: choose-chorus
  3. [cache.shared-context-undeclared]  savings unavailable
     Node: emotional-reviews
  4. [cache.shared-context-undeclared]  savings unavailable
     Node: craft-reviews
```

Pre-Tier-1: 21 opportunities (17 false-positive renames, 4 actionable buried).
Post-Tier-1: 4 opportunities, all actionable, properly labeled.

This is GOOD but not perfect. See "Stage 1 remaining" below for what's left.

---

## Stage 1 remaining (your immediate work)

### Tier 2 — broken/wrong output, still in v1

**#3 — Sub-paths of dict not collapsed to root**

The suggested `## Cache` block on song-creator emits separate chunks for
`${concept.core_idea}`, `${concept.title}`, `${concept.angle}`:

```
${concept.core_idea}
${concept.title}
${concept.angle}
```

These are all sub-paths of the same `concept` dict. Caching `${concept}` once
serves all three. The analyzer's algorithm walks template references and
treats each unique `${var.path}` as a separate chunk. Doesn't recognize that
`${concept.X}` for various X all share root `concept` and could be one chunk.

**Where**: `core/cache_analysis/analyze.py::_collect_llm_template_references`
(line ~775) — currently keyed by full template path. Needs root-collapse
logic: when `concept`, `concept.X`, `concept.Y` all appear, prefer `concept`
unless the dict's other fields are private.

**Tricky bit**: collapsing too aggressively could over-cache. If a node uses
ONLY `${concept.title}` (a few tokens), promoting to `${concept}` (the whole
dict) sends extra bytes. Decision shape: collapse only when ≥2 sub-paths AND
the union covers most of the dict. Or always collapse to root and accept the
overhead — the dict is the cacheable unit, sub-path access is a syntactic
convenience.

Estimated: ~30-50 LOC + 4-6 tests.

**#4 — Chunk ordering doesn't match natural prompt flow**

```
${concept.core_idea}
${concept.title}
${concept_brief}
${creative-direction.response}
${concept.angle}              ← interrupts the natural flow
${song-architecture.response}
${easter-eggs.response}
```

Looks like first-seen-in-template order with sub-path ordering accident.

**Strict-order rule (DD#6)** means agents MUST list items in `prompt_cache:`
matching `## Cache` declaration order. Wrong order = `cache.order-mismatch`
errors when nodes opt in. Bad order in the suggested block actively misleads.

**Where**: `core/cache_analysis/analyze.py:729` —
`shared_refs.sort(key=lambda item: (-len(item[1]), first_seen[item[0]], item[0]))`.
The `first_seen` dimension uses node index, but doesn't account for ORDER
within a prompt template. Better: track first-occurrence position WITHIN the
prompt of the most-shared node. Or: sort by "natural narrative" — concept
information first, then derived analyses, then context-specific data. The
latter is hard to automate; the former is concrete.

After #3 (sub-path collapse) lands, this becomes simpler: fewer chunks to
order. Suggest doing #3 first.

Estimated: ~15-25 LOC + 2-3 tests.

**#11 — Cross-workflow renames not deduplicated**

After #362, far fewer rename warnings fire. But the ones that DO fire can
still be 2+ per parent-child pair (the song-creator → reviews/* parent
sends `${creative-direction.response}` AND `${song-architecture.response}`,
each becoming a separate warning).

Could collapse to:
```
song-creator → review-emotional-architecture: 2 renames (lyrics → write-lyrics.response, creative_direction → creative-direction.response)
```

**Where**: `core/cache_analysis/analyze.py:_build_cross_workflow_findings` —
the rename emission loop. Group by `(parent_workflow, child_workflow)` and
emit one diagnostic per pair.

**Decision**: each existing per-rename diagnostic carries the full context
in JSON. Grouping at emission collapses JSON consumers' dispatch. Could group
ONLY in text rendering, keeping JSON granular. This preserves machine-
readable surface for agent parsing.

Estimated: ~20-30 LOC + 2 tests.

**#16 — "Recommended actions" + "All warnings" sections duplicate**

Section structure today:
```
## Recommended actions  (warnings sorted by impact)
## Per-call cache report
## All warnings         (warnings sorted differently)
```

Same warnings, two formats. mypy / ruff / clippy print warnings ONCE with a
single sort. Pick one; deprecate the other. Or: keep both but document why
(e.g., "Recommended actions" = top-N filtered, "All warnings" = full list
including suppressed-from-recommendations).

**Decision needed**: which view is the canonical one? The recommended-actions
section is shorter and pre-sorted; the all-warnings section is exhaustive
but redundant. Suggest: keep recommended-actions; drop all-warnings; add
note in agent-facing guide that JSON output has full warnings list for
deeper inspection.

**Where**: `core/cache_analysis/render_text.py` — find the `## All warnings`
section. Test surface: any test asserting on "All warnings" header.

Estimated: ~10-20 LOC removed + tests updated.

### Tier 3 — polish (smaller, lower-priority)

**#6 — Confidence + "Cost: unavailable" redundant signals**

```
Confidence: low_no_data
...
Current cost per run: unavailable
Absolute cost figures need a prior run...
```

Both signal "no data yet." Could unify into ONE clear call-to-action:
"Run the workflow once for full analysis (currently estimating from token
counts only)."

Where: `render_text.py` — `_render_summary` + the confidence-line render.

**#7 — `ratio=0%` alongside "21 opportunities" confusing**

Per-call report shows `ratio=0%` for every node when `## Cache` isn't declared.
"21 opportunities" but every node shows 0%. The relationship isn't surfaced
explicitly. Could add a one-line explainer: "Opportunities are POTENTIAL
savings if `## Cache` were added; ratios reflect CURRENT cache usage."

**#8 — Empty `model=` rendering**

```
song-architecture  model=  tokens=2879
```

`model=` followed by empty space when the workflow uses default model. Should
render `(default)` or `(unknown)`.

Where: `render_text.py::_render_per_call` — the `model=` formatter.

**#9 — `src=heuristic` vs `src=estimator` leaks impl detail**

Per-call report shows `src=` column with internal classification. Agents
shouldn't need to know whether tokens came from char-count fallback vs
litellm.token_counter. Could collapse to "high/low confidence":

- `trace` / `memo` → "high"
- `estimator` → "medium"
- `heuristic` → "low"

**Decision**: changing column header/values may break golden-style tests if
any exist. Check `test_cache_analysis_renderers.py`.

**#13 — Notes section duplicates info from Confidence + Summary**

```
## Notes
- Absolute cost figures need a prior run...
```

Already said via Confidence + Summary. Notes should add NEW context (Gemini
telemetry caveat from spec, Python-assembled-prompt limitation, etc.).

### Stage 1 perfection bar

For Stage 1 to be "perfect," `pflow analyze-cache` on lyrics-generator should:

- Suggested `## Cache` block has root-collapsed chunks in narrative order
  (no `concept.X` separate from `concept`)
- All renames suppressed (post-#362) OR grouped (post-#11)
- One canonical warnings view (no duplication)
- Cosmetic surfaces (model=, src=, Notes, Confidence redundancy) cleaned up

After that, run `pflow analyze-cache --format=json` against the same workflow
and verify the JSON shape — every `warnings[]` entry has populated context,
every `recommended_actions[]` entry has scope, no `null` fields where data
should be.

---

## Stage 2: real LLM verification on lyrics-generator

Once Stage 1 is perfect, validate the value prop. The spec's locked target
is **≥40% input-cost reduction with `## Cache` declared, ≥70% on rerun
within 1h** (line 1030).

### Cost recalibration (don't trust the spec's $2-5 estimate)

The lyrics-generator CLAUDE.md states: **~$1.80 per run, ~380 seconds**.
Cheaper than the spec because the workflow uses Gemini Flash by default
(not Anthropic Sonnet). So 5 full runs is ~$9.

### Provider caveat that matters

The workflow uses Gemini by default (with `gemini/gemini-3.1-pro-preview`
explicitly on `write-lyrics`, `rewrite-emotional`, `rewrite-craft`). The
caching guide flags:

> Gemini telemetry caveat — `cache_creation_input_tokens` is 0/absent even
> when caching is working; verify via `cache_read_input_tokens` on
> subsequent calls.

So **don't verify cache via `cache_creation_input_tokens` alone on this
workflow** — compare total cost RUN1 vs RUN2 OR read `cache_read_input_tokens`
on the second call.

For cleaner verification, ALSO run a small Anthropic-only fixture in parallel
(the same way the verification-specialist drill did). Anthropic has clean
`cache_creation_input_tokens` + `cache_read_input_tokens` reporting.

### Recommended Stage 2 ordering — staged from cheapest to most expensive

**Stage 2.1 — `song-creator` standalone (cheapest, highest leverage)**

```bash
pflow /path/to/lyrics-generator/song-creator/song-creator.pflow.md \
  concept='{"title":"Test","core_idea":"...","angle":"...","genre_family":"folk","narrator_hint":"observer","narrator_type":"natural","reasoning":"..."}' \
  concept_brief='<10k tokens of palette text>'
```

Cost baseline (no `## Cache`): ~$0.50/run. Capture trace.

Then add the suggested `## Cache` block (use the analyzer's output). Run
again within 5 min: ~$0.30 ideally (40% reduction). Run3 within 1h with
`- ttl: 1h`: ~$0.15 (70% reduction).

This is the cheapest path to value-prop verification — ~$1 total. Validates
that Path 1 + Tier 1 + cache rendering layer (Segments 2-3 of Task 159)
actually delivers the savings.

**Stage 2.2 — `chorus-chooser` standalone (prewarm + auto-batch-prefix test)**

```bash
pflow /path/to/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  concept='{"title":"Test","core_idea":"..."}' \
  creative_direction='<text>' \
  architecture='<text>' \
  creative_brief='<text>'
```

The `score-choruses` node is the canonical 34-item batch with ~2k-token
static rubric — the spec mode-1 prewarm test. **CAVEAT: see "#12 Python-
assembled prompts" below — the analyzer can't recommend prewarm here today
because the prompt is `${item.prompt}` (built in Python).** Stage 2 still
validates that prewarm WORKS at runtime even if the analyzer can't suggest
it; you'd manually add `- prewarm: true` to score-choruses and measure.

~$0.30/run × 3 runs = ~$1.

**Stage 2.3 — Full lyrics-generator end-to-end (final verification)**

Only after 2.1-2.2 confirm the value prop. Run with `## Cache` blocks
declared everywhere recommended, plus prewarm where applicable. Verify ≥40%
overall reduction, ≥70% on rerun. ~$1.80/run × 3 runs = ~$6.

**Total estimated Stage 2 spend: $8-10.**

### What to capture per Stage 2 run

For each run:

1. Total LLM cost (from trace's per-node cost summary)
2. Per-node `cache_creation_input_tokens` (Anthropic) or `cache_read_input_tokens` (Gemini)
3. Trace file for `--from-trace` discrepancy analysis (reveals attribution
   gaps the analyzer missed)
4. `pflow analyze-cache --from-trace <trace>` output — does discrepancy
   detection flag mismatches?

Save runs to `scratchpads/stage2-verification/run-N-{baseline|cached|rerun}/`.

### Failure cases to watch for

- **First run 0% savings**: cache rendering didn't fire. Check
  `cache_render` IR is populated; verify `__pflow_cache_render__` in shared.
- **Provider response shape mismatch**: LiteLLM might handle Gemini cache
  differently than expected. Compare with Anthropic-only fixture.
- **Cross-workflow byte mismatch**: if song-creator's `## Cache` declares
  prose labels that diverge from chorus-chooser's, cross-workflow cache hits
  fail. The spec explicitly notes this (DD#26). Use `analyze-cache --from-trace`
  to detect — this is exactly the case `cache.discrepancy` is for.
- **TTL expiry**: 5-min default may expire between baseline and cached run.
  Use `- ttl: 1h` if iteration is slow.

---

## Architectural concerns (decisions on the table)

These are NOT v1.x deferrals — they're decisions you (or the user) need to
make before this branch merges.

### Concern 1 — `cache.cross-workflow-rename-detected` redundancy with `cache.discrepancy`

**Status**: documented; no fix proposed yet.

The Tier 1 #362 fix made the rename warning fire only with evidence (## Cache
declared). But once trace data is available, the SAME concern is detectable
as a `cache.discrepancy` with "cross-workflow byte mismatch" root cause —
evidence-based, attributed to a real cache miss.

This raises: should the catalog drop `cache.cross-workflow-rename-detected`
entirely and fold it into `cache.discrepancy`'s root_cause enum?

**Pros of dropping**: catalog gets smaller (DD#29 closed list of 12 → 11);
fewer ways to express the same concern; users see findings only with evidence.

**Cons**: loses static-only detection (when no trace exists). But that's
the same case my Tier 1 fix gates on — if no `## Cache` declared, suppressed
anyway. So static detection is only relevant in a narrow state: `## Cache`
declared but no trace exists yet.

**Decision shape**: discuss with user. If yes, this is a catalog redesign
(DD#29 review process). If no, document why both warnings exist as a
"static prediction" + "evidence-based attribution" pair.

**Where to look**: `core/cache_analysis/warning_catalog.py` (catalog),
`analyze.py::_build_cross_workflow_findings` (rename emitter),
`warning_catalog.py::_dispatch_discrepancy` (discrepancy attribution
templates — would gain a new root_cause if folded in).

### Concern 2 — Python-assembled prompts limit detection

**Status**: documented; no fix designed.

`chorus-chooser`'s `score-choruses` node is a 34-item batch with a 2k-token
static rubric. Spec mode-1's canonical prewarm test. **The analyzer can't
detect it** because the prompt is `${item.prompt}` — assembled in Python by
the upstream `build-scoring-items` code node:

```python
items.append({
    "prompt": prompt,  # the actual rubric+chorus text
    "chorus_index": i,
    ...
})
```

The static analyzer reads `params["prompt"]` which is just `${item.prompt}`.
It can't see what `build-scoring-items` produces.

This compounds with #362 — the most batch-prewarm-relevant case in the spec
example IS exactly this Python-assembled pattern.

**Three possible directions**:

1. **Document as a limitation**. Add a Notes-section line: "Prompts
   assembled in Python code nodes are invisible to static analysis. Use
   `pflow analyze-cache --from-trace <path>` after a real run for
   evidence-based prewarm recommendations."

2. **Detect the pattern statically**. When `params["prompt"] == "${item.X}"`
   AND there's an upstream code node producing items with `prompt` field,
   walk to the code node's output. Hard — requires AST analysis of Python.

3. **Run-once detection**. After the workflow has run once (memo data
   exists), the analyzer could read the actual rendered prompt from the
   memoization cache. Half-static, half-evidence.

(1) is honest and ships now. (2) is fragile. (3) is bounded design work.

Recommend (1) for v1; consider (3) for v1.x. Either way, document.

**Where to look**: `core/cache_analysis/analyze.py::_dynamic_before_static_warnings`
(currently can't see the prefix), `_emit_padding_advisories` (same),
`_batch_prewarm_recommendations` (same — `prefix_tokens_estimated` from
`${item.X}` is ~3 tokens).

### Concern 3 — Path 2 architectural cleanup (#361)

**Status**: filed as separate issue (#361). Path 1 done, Path 2 open.

Path 2 extends the `ResolvedWorkflow` boundary contract to also pre-compile
sub-workflows (closes #334) and bake output-exposure rules + cycle detection
state (closes #321). One PR closes three issues.

**Estimated scope** (per #361): ~280 LOC + ~10 tests, 1-2 days.

Path 2 is NOT blocking Stage 2 — the analyzer works fine without it. But it's
the architecturally correct end-state. Consider tackling Path 2 BEFORE merging
this branch if the user wants the architectural slice complete.

---

## Tacit knowledge (the colleague-walking-in stuff)

**1. The contract test (`test_workflow_resolver_contract.py`) is structurally
load-bearing.** Don't delete it; don't weaken it. It walks every IR's
`FILE_RESOLVABLE_PARAMS` and asserts no `is_file_reference(value)` matches.
If you add a new file-resolvable param type, update `FILE_RESOLVABLE_PARAMS`
in `core/file_resolver.py` AND the contract test will catch your work
automatically.

**2. The evidence-basis principle (Tier 1 #362) generalizes.** Predictive
warnings about state comparisons should fire only when state to compare
exists. Other warnings I haven't audited might violate this. When you add
new warnings, ask: "is this predicting a future problem? if so, what state
makes the prediction actionable?" If the answer is "imagine the user adds
X later," the warning probably needs gating.

**3. `parent_batch_alias` is on the edge, not derived at emission.** When
you extend `CrossWorkflowEdge` for new fields, follow the same pattern:
compute at walk time, expose as a field. Avoids re-walking the IR at
emission time.

**4. The priority dict in `warning_catalog.py` is the SSoT for ordering.**
Adding a new catalog ID requires adding a priority entry too — otherwise it
falls back to `DEFAULT_RECOMMENDED_ACTION_PRIORITY` (100, lowest). The
priority tiers I established (10/15/20/30/50) leave gaps for future IDs to
slot in without renumbering.

**5. `RecommendedAction.scope_workflow` and `node_id` are mutually exclusive
at most one is set; both can be None for unscoped findings (rare but possible).
JSON consumers should dispatch on the (None/None, set/None, None/set) triple.
Don't add a `scope` enum field — that's overengineering; the existing fields
already encode the choice.

**6. `_source_line` is now consistently populated on nodes via the parser.**
If you write code that reads `_source_line`, expect a populated `int`. Legacy
code that defends with `int(node.get("_source_line") or 0)` still works but
the `or 0` fallback is now defensive-only.

**7. The lyrics-generator workflow uses Gemini Flash by default.** When
running Stage 2 verification, remember the Gemini telemetry caveat — verify
cache via `cache_read_input_tokens` on N+1 calls, not via
`cache_creation_input_tokens` on the first call.

**8. The recommendations-section-handoff.md (existing handoff for the
RECOMMENDATIONS sub-segment work) has tons of valuable context** about how
the analyzer's emission paths work. Read it before touching `analyze.py` for
real changes. It's specifically focused on the recommendations algorithm,
not the broader analyzer.

**9. Mutation testing is the litmus for negative fixtures.** Every Tier 1
test I added has a docstring explaining what removing the production fix
would break. Follow the same pattern when you add tests. The existing
`test_cache_analysis_per_id_emission.py` tests have great examples of
this.

**10. `make check` runs ruff-format which auto-fixes formatting.** If a
test fails after running format, the test's expected text/behavior might
have shifted by a single space. Re-read the test's assertion with that lens.

**11. Don't `git add scratchpads/`.** They're untracked by convention and
contain working notes that don't belong in commits. The user explicitly
flagged this during my session.

**12. The progress log entry for Stage 1 work I appended is the canonical
record.** When you add your work, follow the same shape: "What I implemented
/ Deviations from plan / Tacit knowledge / Open hedged claims / Open user
decisions surfaced." Keeps the history consistent.

---

## Quick-start commands

```bash
# Verify the branch state
git log --oneline -5
make test                   # expect 5,967 passing
make check                  # expect all green

# Re-run the canonical analyze-cache smoke test
uv run pflow analyze-cache /path/to/lyrics-generator/song-creator/song-creator.pflow.md --no-trace-autoload
# Expect: 4 opportunities, all actionable, properly labeled

# Inspect the priority dict (for Tier 2 work)
grep -A 30 "RECOMMENDED_ACTION_PRIORITY" src/pflow/core/cache_analysis/warning_catalog.py

# Find Tier 2 / Tier 3 fix sites quickly
grep -n "_collect_llm_template_references\|shared_refs.sort" src/pflow/core/cache_analysis/analyze.py
grep -n "## All warnings" src/pflow/core/cache_analysis/render_text.py
```

---

## Final ask

Before Stage 2 spend, **show the user a sample of the post-Tier-2/3 output**
on song-creator. Compare side-by-side with the post-Tier-1 output (in this
doc). The user will confirm whether "Stage 1 perfection" has been reached.
Don't burn LLM budget on a known-imperfect analyzer.

Good hunting.
