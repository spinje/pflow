# Handoff: Don't extend `is_rename` — investigate its premise first

> **To**: my past-self, at the moment just after I had proposed extending the `is_rename` predicate to handle the nested-path same-tail case (the "bonus finding" — `extract-emotional-lyrics.result.lyrics → lyrics`). The user is about to ask me to focus only on the bonus finding and explain why it matters.
>
> **From**: my current-self, after walking through the full investigation that the user's pushback unlocked.
>
> **Why this exists**: I almost shipped a fix that extended a predicate whose premise I hadn't verified. The user's next two questions ("why does this matter?" then "if we know they point to the same data, why can't we just allow different names?") forced me to actually check whether the rename detector should exist at all. The investigation landed on shape δ (emit but don't render in text). This document is what I wish I'd told myself before proposing the predicate extension.

## TL;DR

**Don't extend `is_rename`.** Before touching the predicate, verify three claims that the catalog asserts but no one had checked:

1. Variable names appear in the bytes the LLM provider sees.
2. The rename detector catches a real cache failure that prose-mismatch doesn't.
3. The rename detector's signal-to-noise is empirically positive.

All three claims are false. The predicate works exactly as intended at the syntactic level — it just detects a thing that doesn't matter for cache fidelity. Extending it makes the false-positive flood larger.

**The right shape is δ**: emit-but-don't-render-in-text. ~30 production LOC, ~250 test LOC, trivially reversible. Smaller blast radius than full deletion (γ), preserves JSON for future consumers, sidesteps the MCP docstring contract change.

## What I almost did wrong

When the user flagged the missing `extract-emotional-lyrics.result.lyrics → lyrics` in `## Sub-workflow boundaries`, my reflex was: "the predicate's tail-only comparison has a gap; extend it." I drafted a 5-LOC predicate change:

```python
@property
def is_rename(self) -> bool:
    if not self.parent_value_expr:
        return False
    tail = _value_tail(self.parent_value_expr)
    if tail != self.child_input_name:
        return True
    return "." in self.parent_value_expr or "[" in self.parent_value_expr
```

The framing was: "fill in a gap in an established predicate." That's how the work would have been justified.

**The mistake**: I extended a predicate without asking what the predicate is for. The predicate is the front-end of a feature (`cache.cross-workflow-rename-detected` warning). The feature exists to flag cases where cache fidelity might fail. Extending the predicate increases the warning's coverage — but only if the warning's coverage is correct in the first place.

The user's question — "if we KNOW it's pointing to the same data, why can't we just allow the different variable names?" — was the prompt to verify the predicate's purpose. That question is the work. Don't skip it.

## The investigation chain (what to ask, in order)

Three parallel searchers settle the question. Run them BEFORE writing any predicate code.

### Searcher 1 — do variable names leak into wire bytes?

Trace end-to-end: parser → `_build_system_blocks` → `_build_user_message_blocks` → `_build_messages` → provider wire format.

**What you'll find**:
- Parser stores `name`, `var_expr`, `prose_before` separately. `prose_before` is `content[last_end : match.start()]` — text up to but not including `${`. (`markdown_parser.py:1693-1745`)
- `_build_system_blocks` emits `{"type": "text", "text": prose + value, "cache_control": {...}(last only)}`. The chunk's `name` is used only as a dict-lookup key, never as text content. (`nodes/llm/llm.py:540-609`, key block-construction at line 597-608)
- `_build_user_message_blocks` substitutes `${var}` with `_deterministic_serialize(value)`. Names disappear at substitution. (`nodes/llm/llm.py:319-461`)
- LiteLLM adapter wraps these as-is. Provider sees `{type, text, cache_control?}` only — no `name`, no `${...}`, no chunk identifier on the wire.
- Tests confirm the inverse: `test_prompt_cache_rendering.py:144-157` locks `text == prose_before + value`.

**Verdict**: variable names do NOT appear in wire bytes for any of Anthropic / Gemini / OpenAI. Two cross-workflow chunks with the same value pass byte-identical content if `prose_before` matches.

**Caveat**: pflow's INTERNAL memo cache hash DOES fold `name` into `config_hash` via `plan_node.py:191`. But `MemoizationCache.get_latest_for_node` is already scoped by `workflow_path` (`runtime/cache.py:305-361`), making the name's role in the hash redundant. So even this caveat doesn't translate to a real-world cross-workflow cache barrier.

### Searcher 2 — does the prose-mismatch detector cover what rename was meant to catch?

Look at `cache.cross-workflow-prose-mismatch` emission and run the scenario matrix.

**What you'll find**:
- Emission at `analyze.py:_cross_workflow_prose_mismatches` (around line 4098-4120), called from `_build_cross_workflow_findings` at `analyze.py:4077-4078`.
- **Critical code**: at `analyze.py:4077`, prose-mismatch emission is gated by `if not is_rename: prose_mismatches.extend(...)`. Locked by `test_cross_workflow_prose_mismatch_suppressed_by_rename_precedence`.
- **The two detectors are mutually exclusive, not redundant.** Rename takes precedence. Prose-mismatch never fires on the same edge as rename.

Coverage matrix (run this scenario-by-scenario):
- **Same prose, different names, both have `## Cache`**: rename fires, prose-mismatch does NOT (suppressed). **Cache would actually fire** because rendered bytes match. Rename is a false positive.
- **Different prose, different names, both have `## Cache` with same chunk name**: rename fires (suppresses prose-mismatch). Cache would fail because of the prose divergence. **But rename's suggestion text doesn't say "fix the prose"**; it says "rename the variable." Misleading.
- **Different prose, SAME names, both have `## Cache`**: rename does not fire; prose-mismatch fires. Cache fails. Prose-mismatch correctly diagnosed.
- **Parent has cache, child doesn't**: rename fires (parent_has_cache gate); `cache.sub-workflow-cache-undeclared` also fires. Prose-mismatch can't fire (intersection empty). Rename adds nothing.
- **Both sides cache different chunk names**: rename fires; prose-mismatch can't fire (intersection empty). Each side caches its own bytes independently. **No actual cache failure.**

**Verdict**: rename never fires on edges where actual cache bytes diverge. The risk it warns about is **anticipatory, not present.** Searcher's exact words: *"There is no concrete byte-level cache failure that `cache.cross-workflow-rename-detected` catches uniquely."*

### Searcher 3 — what's the blast radius of dropping the rename diagnostic?

Survey every consumer of `is_rename` and the rename diagnostic ID. This is the searcher that decides whether full deletion (γ) or text-suppression (δ) is the right shape.

**What you'll find**:
- `is_rename` is consumed only by emission code. Zero downstream-decision uses.
- The rename diagnostic ID surfaces in: emission site, catalog spec, RECOMMENDED_ACTION_PRIORITY (priority 50 — never wins), `_CROSS_WORKFLOW_ALIGNMENT_IDS` frozenset, `count_rendered_findings`, `_render_cross_workflow`, JSON `cross_workflow.rename_detections[]`, MCP docstring, guide table, ~28 tests across 6 test files.
- Catalog count is hardcoded to 22 in `test_cache_analysis_warnings.py:73`. Auto-derived `EXPECTED_CATALOG_COUNT` in catalog itself.
- MCP docstring at `execution_tools.py:487` is the ONLY public contract change for full deletion.

**Empirical evidence (the deciding signal)**: Per the original commit `0c1e46db` ("fix: tier 1 AG/UX issues in pflow analyze-cache (closes #362)"), lyrics-generator originally produced **23 rename warnings, all from batch aliases or non-cache boundaries — zero actionable**. The actionability gate (`parent_has_cache or child_has_cache`) was added in response. Even after that gate, the warning's signal-to-noise hadn't been re-evaluated.

## The pivot (γ vs δ)

After all three searchers return, the choice is between:

**γ — drop entirely**: remove emission, catalog ID, helpers, tests, JSON field, MCP docstring entry, guide row. Catalog 22→21. Public contract change. ~150-200 production LOC + ~750 test LOC. 2-4 days.

**δ — emit but don't render in text**: keep emission, JSON, MCP docstring, catalog count. Strip text rendering only. ~30 production LOC + ~250 test LOC. ~1 day.

**Pick δ.** Reasons:
1. The user-stated priority for this work is text/agent-UX. JSON shape is lower priority. Removing from text addresses the actual problem (noise in agent-facing output) without disturbing the data model.
2. The diagnostic stays emitted in JSON. If a future consumer (auto-fix tool, IDE plugin, code-clarity report) wants the data, it's there. Don't pre-emptively delete infrastructure for speculative future use cases.
3. No external contract churn. MCP docstring, JSON `rename_detections[]`, catalog count all stable.
4. Trivial reversibility. Un-comment the render branch.

But — and this is important — δ is NOT the cleanest answer. γ is technically the most honest. The reason δ wins is **risk and reversibility**, not technical purity. If the team later decides γ is right, going from δ to γ is mechanical.

## Concrete plan for shape δ

**Files**:
- `src/pflow/core/cache_analysis/render_text.py` — strip rename rendering from `_render_cross_workflow`. Delete `_render_renames_for_parent`, `_format_consumer_summary`, possibly `_wrap_csv` (verify with grep). Update intro prose: "name or prose mismatch" → "prose mismatch". Header math drops the `(N, covering M underlying renames)` rollup. ~50 LOC removed.
- `src/pflow/core/cache_analysis/view_helpers.py` — `count_rendered_findings` returns `(rec_count, len(prose_mismatches))`. Delete `group_renames_by_parent` if orphaned. Keep `_CROSS_WORKFLOW_ALIGNMENT_IDS` frozenset as-is (still excluding rename from recommendations is correct). ~30 LOC removed.
- `src/pflow/core/cache_analysis/warning_catalog.py` — update the `cache.cross-workflow-rename-detected` `suggestions_template` to be honest. Proposed: `"Identifier divergence does not affect provider cache fidelity (variable names are stripped before the wire); rename only if it improves code clarity. Cache hits depend on prose-before-${...} text and resolved value bytes, checked separately by cache.cross-workflow-prose-mismatch."`. ~5 LOC.
- `src/pflow/core/cache_analysis/CLAUDE.md` — update line ~92 (rename predicate description) and line ~158 (`_CROSS_WORKFLOW_ALIGNMENT_IDS` description) to clarify text-vs-JSON divergence. ~10 LOC.
- Tests: delete ~5-6 renderer rename tests, migrate ~2 (use prose-mismatch instead), add 3 new contract tests (rename emission still works, text omits renames, dry-run nudge stops counting renames).
- Baselines: regenerate ~3-4 cases (lyrics-generator, the rename-detected catalog case, anything that was rendering renames).

**Tests to add** (these are the new contracts):
- `test_text_sub_workflow_boundaries_omits_rename_diagnostics` — rename diag in `analysis.warnings`, but rendered text does NOT contain its substrings.
- `test_text_sub_workflow_boundaries_section_omitted_when_only_renames_present` — only renames emitted, section header `## Sub-workflow boundaries` does NOT appear.
- `test_dry_run_nudge_excludes_renames_from_actionable_count` — N rename diagnostics + zero prose-mismatches → nudge silent (None).

**Verification**:
- Focused tests: `uv run pytest tests/test_core/test_cache_analysis_renderers.py tests/test_core/test_cache_analysis_summarize.py`
- `make test`, `make check`
- Baseline harness: `verify.sh`. Expect ~3-4 baselines drift, all strict improvements (rename text disappears, sections may collapse to empty when only renames were the boundary content).

## What this fix unlocks (for the next agent — yourself, post-pivot)

After δ ships, the lyrics-generator output will look much cleaner. But you will then notice — or the user will point out — that the `## Sub-workflow boundaries` section now only shows prose-mismatches (which on lyrics-generator is none, so the section vanishes entirely). The recommendations section is still 26 entries. The user will probably ask "is the per-call cache report data different now?"

**Answer in advance**: no. δ was scoped to one section. Per-call uses an entirely separate code path (`_build_per_call_row` + Pass C cross-workflow row plumbing) and is unchanged.

**But this question reveals the next bug**: there's an architectural asymmetry between Per-call and Recommendations.

- **Per-call rendering** uses cumulative-prefix thinking: it scopes to `(child_workflow, child_node_id)`, sums all cross-workflow inputs flowing into that node, projects `could_cache` cumulatively. Pass C added this. Surfaces as `cacheable inputs: a, b, c` with cumulative `could_cache` numbers.
- **Recommendation emission** uses per-input thinking: it scopes to `(child_workflow, child_input_name)` after `_dedupe_sub_workflow_cache_candidates`, runs the threshold check on each individual input via `_below_threshold_clause(tokens, model)` (`analyze.py:4503-4533`).

The asymmetry: lyrics-generator's `review-accuracy` per-call shows `cacheable inputs: creative-direction.response, concept_brief → could_cache: 27,004 (78%)`. Cumulative crosses 4,096. But Recommendation #7 says `creative_direction ~1,922 < 4,096 → savings unavailable`. The same input gets two different stories: per-call says "contributes to cumulative cache", per-rec says "below threshold, won't fire."

The bug: pflow uses single-breakpoint cumulative-prefix rendering (DD#11). When the agent declares ALL the recommended chunks for one child, the cumulative bytes cross threshold and they all fire. The recommendation emission path doesn't know about siblings — each candidate is gated independently.

**Fix shape (Cluster A) for this**:
- **A1** (analyzer-tier aggregator): in `_emit_sub_workflow_cache_findings`, group candidates by `(child_workflow, child_node_ids)`, sum tokens, run threshold check on cumulative. Findings whose cumulative crosses threshold get `savings_usd` populated even if individual tokens are below.
- **A2** (renderer-tier grouping): keep emission per-candidate; renderer groups by child and computes cumulative at display time, dropping the per-input "below threshold" framing when cumulative crosses. JSON consumers still see N separate diagnostics.

A1 is more honest (analyzer's emitted savings is correct cumulatively). A2 is renderer-only, mirrors the Cluster A precedent for cross-workflow renames, and matches how Per-call already handles this. Pick A2 for symmetry with the per-call code path; revisit A1 later if JSON consumers complain.

## Process learnings (don't repeat my mistakes)

1. **When the user pushes back with "but X, why can't we just Y?", that's high-signal.** They saw something I missed. Don't extend a flawed framing; investigate the framing's premises first.

2. **Predicates exist for a reason. Verify the reason before extending.** I treated `is_rename` as an established API to extend; I should have asked "what does this predicate exist for, does that purpose still hold?" The answer was "for a feature whose premise is wrong."

3. **Empirical history matters.** GH #362 already showed the rename detector's signal-to-noise was poor. The actionability gate was a bandage over a deeper issue. I had read that earlier but didn't weight it heavily. **Read the GH-filed issues for the feature before extending the feature.**

4. **Two cache layers, two places "name" matters.** Provider cache: name doesn't matter (stripped at wire). Memo cache: name IS in `config_hash` but already redundant via `workflow_path` scoping. Don't conflate them when reading or writing catalog suggestions.

5. **Suggestion templates can be technically wrong even when emission is correct.** The catalog text `"rename the input ... ensure both ## Cache blocks use the same chunk identifier and identical prose"` was actively misleading agents. Even shape α would have left this misleading text in place. Shape δ fixes it.

6. **Blast-radius analysis is essential before "drop entirely" decisions.** Without searcher 3, I might have proposed γ-full where δ was sufficient. Over-deletion has real costs (public contract changes, test churn, baseline regen). Smaller is usually better when reversibility is high.

7. **Don't plan from a single mental model.** I went into the bonus finding investigation thinking "extend the predicate" — and the user's question forced me to verify the model first. The investigation that followed was much more valuable than the predicate extension would have been.

8. **The Per-call vs Recommendations asymmetry is the next bug.** The user will surface this immediately after δ ships. Be ready to explain it without being defensive about δ — δ is correctly scoped, and the asymmetry is a separate, pre-existing issue (Cluster A territory).

## What to read before starting

- `src/pflow/core/cache_analysis/CLAUDE.md` lines 92, 150, 158 — design intent for the cross-workflow detectors and the `_CROSS_WORKFLOW_ALIGNMENT_IDS` frozenset.
- `src/pflow/core/cache_analysis/cross_workflow.py:67-115` — the `is_rename` predicate and `_value_tail` helper.
- `src/pflow/core/cache_analysis/analyze.py:4046-4120` — the rename-vs-prose-mismatch precedence at line 4077.
- `src/pflow/core/cache_analysis/warning_catalog.py:430-454` — the catalog entry with the misleading suggestion text.
- `src/pflow/nodes/llm/llm.py:540-609` — `_build_system_blocks` to confirm names don't appear in wire bytes.
- `tests/test_core/test_cache_analysis_per_id_emission.py:2150, 2188, 2889` — the rename emission tests and the prose-mismatch precedence test.
- `.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt` — the canonical capture; eyeball it before AND after.

## Verification checkpoints

After implementing δ:
1. Focused renderer/summarize tests pass (~232 tests).
2. Baseline harness 67/67 pass after targeted regen.
3. Lyrics-generator capture: `## Sub-workflow boundaries` section is gone (no prose-mismatches in this fixture). Recommendations section unchanged. Per-call section unchanged.
4. JSON output (`--format json`): `cross_workflow.rename_detections[]` still populated. Confirms emission is intact.
5. MCP smoke: `analyze_cache` returns rename diagnostics in `warnings[]`. Public contract intact.

If any of those fail, the fix isn't δ — figure out which scope leaked before pressing on.

---

**Final note**: the user's two questions ("why does this matter?" then "if we know they point to the same data, why can't we just allow different names?") were the entire investigation. Without them I'd have shipped a 5-LOC predicate extension that made the problem worse. Listen for those follow-up questions; they're the work.
