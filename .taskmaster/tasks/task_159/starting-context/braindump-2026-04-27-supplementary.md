# Braindump: Task 159 — Supplementary (post-session 2026-04-27)

Most of what happened this session is captured in `../implementation/progress-log.md` §26 (the journey, three principle clarifications, verification pass findings, seven open threads). The spec at `../task-159.md` is contract-ready. The original braindump at `braindump-design-complete.md` has been updated to drop outdated framings.

This file captures only what's *not* in those documents.

---

## Patterns I noticed about the user

**Pushback style**: questions, not assertions. "Doesn't FixAction overlap with suggestions?" "Cant trace be loaded automatically?" "Wouldn't blocking pflow run mean loading historical data?" When the user asks a question rather than telling me I'm wrong, that's a strong signal there's a real issue worth re-examining from scratch — not just clarifying my answer.

**Double-error pattern**: When I corrected one mistake under pushback, I sometimes immediately made a new mistake in the adjacent decision. Example: caught the savings-ratio math error, then proposed making the warning a blocking error — which forced a second pushback. Worth taking a beat after a correction before extending the fix.

## Subtle DD interactions not called out in the spec

**DD#27 (`Diagnostic.id`) × DD#36 (multi-mode emission).** The same cache warning is emitted by both `--dry-run` and `analyze-cache`. For dedup to work consistently, the identity tuple `(severity, source, node_id, id or message)` must match across modes. **Question for plan-writing**: is `source` the analyzer (e.g. `"cache_analysis"`) or the renderer (e.g. `"cli/analyze-cache"` vs `"cli/dry-run"`)? Probably the analyzer — so identical regardless of where rendered. Not specified in the spec.

**DD#26 walker placement (option c) plumbing concern.** Spec recommends moving auto batch-prefix detection from `LLMNode` to `batch_executor.py`. Today `batch_executor` resolves per-item templates but doesn't touch adapter calls. If detection lives there, the *emission* of the `cache_control` marker still has to flow back to the adapter call. Phase D plan needs to think about whether option (c) stays architecturally clean or forces a small refactor where `batch_executor` writes a marker hint into the per-item shared state that `LLMNode` then reads. Not fully thought through.

## Things I should have surfaced but didn't

**Exit-code policy for `pflow analyze-cache` on warnings.** Spec says "exits 0 except on validation errors." But in CI, an agent might want non-zero exit on advisory findings to gate merges. I never asked. CONSIDER: a `--strict` flag that exits non-zero when warnings are present.

**Test-fixture strategy for `analyze-cache` goldenfile tests.** I added `tests/test_cli/test_analyze_cache_golden.py` to the spec without specifying the fixture workflows. Real lyrics-generator copy? Synthetic minimal workflows that exercise each mode (greenfield / steady-state / already-optimal / from-trace)? Probably the latter — golden tests should be self-contained, not depend on user's external repo. Plan-writing decision.

**Aggregate confidence misleads when memo data is sparse.** `medium_from_memo` fires if *at least one* row has memo data. For a 30-node workflow with memo on 2 nodes, calling that "medium" misrepresents fidelity. MIGHT MATTER: aggregate could include a coverage percentage (e.g., `medium_from_memo (3/30 nodes)`). v1b refinement.

## Hedged claims (70% confidence)

- Adding `Diagnostic.id` won't break any existing tests. Identity tuple falls back to `id or message` when `id is None`, so legacy diagnostics keep their dedup. **NEEDS VERIFICATION**: run `make test` after the Phase B Diagnostic edit; pay attention to any diagnostic-equality tests in `tests/test_core/test_diagnostic.py` and equivalents.

- The mermaid renderer's traversal pattern (`core/workflow/mermaid/_render.py:50-130`) is genuinely the closest analog for the Tier 2 walker. The recommendation in the spec assumes ~50 LOC; closer to 150 LOC including detection rules. Still small. Plan-writing should validate.

- `core/llm_capabilities.py` should mirror `core/llm_providers.py`'s structural shape — same dataclass-tuple pattern, same dependency-free constraint. Not stated in the spec but follows the codebase's structural-mirroring convention.

## Things I'd tell myself before next session

When proposing a new abstraction, immediately ask: **"what's the delta between this and what already exists?"** If the answer is "it's the same thing with a typed name," the abstraction probably isn't justified. The FixAction debate cost a round-trip because I didn't apply this check upfront.

When the user invokes "top 10% codebases similar to this one," answer with concrete named comparable tools — and the mental check that breaks the wrong comparison is **"do they auto-apply or just analyze?"** That distinction made mypy the right analog and rustc the wrong one. Reusable test for any "top 10%" question about diagnostic systems.

The user has consistently emphasized: *"prioritize simplicity of FINAL code, not how easy to get there."* For Phase B-G plan-writing, this means biasing toward clean end states even when migration is more work. Don't propose minimum-diff patches; propose the cleanest landing point.

## Process recommendation for the next session

Before Phase B-G plan-writing, **consider running `/ultrareview` on the spec**. It grew substantially this session — DD#26 through DD#36, restructured analyze-cache requirements section, output format mockups folded in, four-level confidence labeling, three-tier validation/analysis architecture. Worth a structured review pass to catch internal inconsistencies before they propagate into plan-level patches.

Code investigation is done — items A through H are verified in progress-log §26. Don't re-verify.

## For the next agent

1. Read `../implementation/progress-log.md` §26 first. The three principle clarifications and the verification pass surprises are load-bearing for understanding the spec's reasoning.
2. The 7 open threads in §26 are the to-do list for plan-writing. Resolve them in the plan; don't add to them.
3. The user's communication style: concise, recommendation-first, math/code over hand-waving. They push back via questions ("isn't X?") not assertions. Treat questions as forcing-functions, not requests for clarification.
4. The user values *honest reconsideration* when challenged. Saying "you're right, my framing was wrong because Y" lands well. Defending a position under pushback by hand-waving doesn't.

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
