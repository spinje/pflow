# Agent Handoff: Task 159 (Prompt Caching)

Operating context for any agent picking up Task 159. This file holds what doesn't fit in `task-159.md` (the contract) or `implementation/progress-log.md` (the journey): user-working-style, methodology that's worked, concrete substrate details, and gotchas.

**Read order:** spec → progress log → this file. Then verify the user wants to proceed before writing code.

---

## Working with this user

### Pushback comes as questions, not assertions

When the user asks a question rather than stating you're wrong, that's a strong signal there's a real issue worth re-examining from scratch — not a request to clarify your last answer. Treat questions as forcing functions.

Representative examples that each caught a real design issue:
- *"doesn't FixAction overlap with the existing 'suggestion'?"* → forced dropping a typed substructure with no programmatic consumer (DD#28).
- *"cant trace be loaded automatically?"* → forced separating MemoizationCache vs JSON trace files (DD#34).
- *"wouldnt blocking pflow run mean loading historical data?"* → forced the three-tier validation/analysis architecture (DD#36).
- *"why couldnt you do [chorus-chooser.winning_chorus] directly?"* → forced dropping `[name]` markers (DD#4).
- *"im not sure why we would need a different ttl?"* → forced block-level TTL only (DD#7).
- *"why is this not supported by litellm? seems weird?"* → forced re-investigating Gemini TTL and finding LiteLLM does support it via seconds notation.

### Other patterns

- **Double-error pattern after correction.** After acknowledging one mistake, the agent tends to make a new mistake in the adjacent decision (e.g., catching the savings-ratio math error, then proposing the warning be a blocking error, then having to retract). Take a beat after a correction before extending the fix.
- **"lets take a step back" / "im not sure"** = stop and explore, not "ship the next draft." User detects premature commitment faster than the agent.
- **Honest reconsideration lands.** "You're right, my framing was wrong because Y" works. Defending under pushback by hand-waving doesn't.
- **20 turns > wrong design.** When in doubt about user preference, ask.
- **User does not make decisions for you.** Always present 2+ options with tradeoffs and a clear recommendation. For low-stakes you're confident on, proceed; for higher stakes, stop and wait.
- **Concise, recommendation-first, math over hand-waving.** When the user's instinct points at a clean rule, work the math first instead of arguing from assumed cases — savings-ratio went from "always >40%" (my assumption-based wrong claim) to "structural property captured by math" (correct) in one turn once I actually computed it.

### Direct quotes that are still load-bearing

These shaped specific DDs and should keep shaping plan-writing:

| Quote | What it locks in |
|---|---|
| *"agents are always writing pflow.md workflows, not 'users'"* | Optimize output for LLM-agent readability. Markdown text > JSON for primary surface; JSON is secondary for tooling. Stable warning IDs matter in BOTH. |
| *"I dont think we should auto apply caching if that means we have to change prompts that are declared in the workflow. but we can split it up if the whts sent is identical"* | DD#2. The single most important principle. pflow never silently restructures messages; bytes-identical splitting is fine. |
| *"we shouldnt optimize automatically for workflow reruns, that should be opt in"* | DD#8. Extended TTL is always opt-in. No assumption of reruns in default behavior. |
| *"the IMPORTANT part is that when llm nodes use them they NEED to be imported in the same order as whats defined in the cache block"* | DD#6. The order invariant came from the user, not the agent. |
| *"prioritize simplicity of the FINAL code, not how easy it is to get there"* | Eliminates "minimum-diff patch" defenses. Pick the cleaner end-state. |
| *"what would the top 10% of codebases similar to this one implement?"* | Operational question for selecting between equivalent-by-LOC alternatives. Answer with **named comparable tools**, then test the analog with: "do they auto-apply or just analyze?" — that test made mypy the right analog (analyzer) and rustc the wrong one (auto-applier) for v1's `analyze-cache`. |
| *"introspect deeply into your context window and make sure we havent missed anything"* | The two-wave research pattern was the user's idea. Use it; they're willing to invest in verification. |

### Inferred user priorities (confirmed across Phase A and §25-§28)

- **Top-10% well-written codebase, not enterprise-framework-like.** Boring, obvious code wins.
- **Allergic to silent behavior.** Visible > invisible, always.
- **Strict validation that errors clearly > lenient parsing that guesses.**
- **Dislikes verbose output, fine with comprehensive output if structured.**
- **Trusts research agents' output but wants claims verified.**
- **Wants the cleanest end-state, not the easiest migration path.**

### What the user cares most about for Task 159 (priority order)

1. Agent-readable syntax (the load-bearing principle).
2. No silent behavior changes.
3. The lyrics-generator actually getting cheaper (end-to-end validation, not just unit tests).
4. Existing `cache: bool` workflows continuing to work unchanged.
5. `test_plan_drift.py` staying green.
6. Cleanest end-state code (not easiest migration path).

---

## Methodology that's worked here

### Framing checks before adding code

- **"What's the delta between this and what already exists?"** Before proposing a new abstraction (typed dataclass, helper module, parameter), state the delta over what's already in the codebase. If the answer is "same thing with a typed name," kill the abstraction. The `FixAction` debate cost a round-trip because this check wasn't applied upfront.
- **"Do they auto-apply or just analyze?"** The test that distinguishes mypy/pylint/shellcheck (analyzers — prose suggestions, no programmatic application) from rustc/ruff/eslint/prettier (auto-appliers — typed fix structures justified). For v1's `analyze-cache`, mypy is the right analog. `pflow cache apply` is a v1b feature; until then, no typed `FixAction`.
- **"Is `source` the analyzer or the renderer?"** Rule found in §27: source = the analyzer (`source="cache_analyzer"`), regardless of which CLI surface emits it. Mirrors the existing `source="planner"` precedent.

### Research pattern that worked

- **Two-wave dispatch.** Wave 1 = unknown unknowns (5 parallel `pflow-codebase-searcher` subagents on broad areas). Wave 2 = specific assumptions surfaced by Wave 1 (4 parallel agents on narrow questions). Each agent gets concrete prompts and reports under 400 words. Used in §17, §26, §27.
- **Per-provider enumeration, never assume uniformity.** Wave 2A originally verified `llm-anthropic` only and missed Gemini's dual-mechanism. External research surfaced it. Recurring trap; Anthropic 4-marker limit, OpenAI auto-cache thresholds, and any future provider need their own per-provider verification.
- **Mockup before syntax lock.** The `pflow analyze-cache` output mockup revealed doability questions (dollar estimates pre-run) before the spec committed.
- **Re-read the actual workflow files** before locking syntax decisions. Pattern A (cross-call reuse) only emerged once lyrics-generator was read — before that, thinking was batch-only. For Phase B-G, lyrics-generator + song-creator + chorus-chooser remain the ground truth.
- **Spike LiteLLM for any cache scenario you're unsure about.** Pattern: minimal Python file calling `complete()` directly with one provider scenario, dropped in `scratchpads/`. ~$0.10/run. Faster than reading docs for behavior questions. Task 158's spike scripts have been cleaned up — no template to point at; write fresh.

### When the user invokes "top 10% codebases similar to this one"

Answer with concrete named comparable tools, not abstract qualities. Apply the auto-apply-vs-analyze test to filter. Examples that worked: mypy (analyzer, right analog), rustc (auto-applier, wrong analog), ruff/prettier/clippy (auto-appliers).

### Patterns to mirror, not invent

- **Typed-exception → diagnostics.** `LLMCallError → to_diagnostics()` from Task 158 is the template for cache-validation errors. Don't invent a new error system.
- **Conditional inclusion in `compute_node_config`.** `if batch_config: config["batch"] = ...` (`runtime/engine/instrumentation.py`) is the precedent for `if prompt_cache_content: config["prompt_cache"] = ...`. The dict key is `"batch"`, NOT `"batch_config"` — copy the precedent verbatim.
- **MD5 + `# noqa: S324`** for content identity hashing (5 sites: `cache.py:85,111,344`, `instrumentation.py:178`, `smart_filter.py:71`, `runner.py:52`). SHA-256 is reserved for security-relevant change detection (2 MCP-config-drift sites). New `prompt_cache_key` follows the MD5 convention.
- **`source="planner"` for analyzer-tier diagnostics** (`execution/plan.py`, six sites) is the precedent for `source="cache_analyzer"`. Used by both CLI and MCP callers; renderers don't inspect `source`. Identity-tuple dedup is the only consumer.
- **`test_mermaid_golden.py`** is the only existing golden-test pattern. Parametrized cases, byte-exact equality, regen command in failure message. NO `--update` mode — pflow has no convention for one. New `test_analyze_cache_golden.py` mirrors this exactly.
- **`MockLLMClient` is the only LLM mock.** If cache-rendering tests need new capabilities, reshape `set_response`. Don't fork.

---

## Concrete substrate (Task 158 leftovers not in the spec)

### LiteLLM version pin and rationale

`litellm==1.82.6` (NOT 1.83.7 as the original Phase 0 spike suggested). Rationale: 1.83.x hard-pins `click==8.1.8` which broke 3 CliRunner tests in pflow. 1.82.6 contains the Gemini double-counting fix (PR #15226, 2025-10-07) per release date. Don't bump unless the click pin is resolved upstream.

### LiteLLM verification spikes (~$0.10 each)

Pattern: minimal Python files calling `complete()` directly with one provider scenario, dropped under `scratchpads/`. Used during Task 158 to verify cache_control composition with thinking + structured output, Gemini double-counting fix, response shape normalization. **Task 158's spike scripts have been cleaned up — no existing template to copy.** When Phase D needs to verify OpenAI `prompt_cache_key` routing or Phase E needs to verify per-TTL pricing, write fresh spike scripts following the same minimal pattern.

### 6 GH follow-ups from Task 158 (#347-#352)

None block Phase B-G work. Three touch areas Phase F will modify — read them before starting Phase F:
- **#350** (cost display) — analyze-cache output cost rendering will overlap.
- **#351** (warning aggregation) — analyze-cache emits multi-warning lists; aggregation rules may converge.
- **#352** (secondary diagnostic context) — cache validation errors emit context payloads; same surface area.

### Lyrics-generator concrete numbers (motivating workflow, do not modify)

Paths under `/Users/andfal/projects/music-generation/workflows/lyrics-generator/` — **explicit user permission required before touching.**
- Total: ~181 LLM calls per run, ~252 across 8 workflow files when sub-workflows enumerated.
- song-creator cache ~11k tokens, referenced ~60 times per run, ~20-min run duration. Net-positive for explicit caching on any provider.
- chorus-chooser: 8 chorus-gens + ~34 scoring calls share a ~1.5k-token rubric prefix.

These ground "is this savings worth the complexity?" questions throughout plan-writing.

---

## Provider-specific gotchas

### Gemini's dual-mechanism (still relevant for v1b)

Gemini has TWO caching modes; the spec collapses them into "cache" but the distinction matters for the `cache.gemini-implicit-vs-explicit` follow-up:

- **Implicit caching** — automatic for Gemini 2.5+, no API surface. Free (no storage cost, no TTL control). Min 1024 tokens (2.5 Flash) / 2048 (2.5 Pro). Fires when prefix is stable across requests.
- **Explicit caching** — via `CachedContents` API (what `cache_control` triggers). 90% read discount BUT charges storage cost by duration. Higher minimum (~4k–32k for 2.5 Pro). Default 60-min TTL when ttl omitted.

**Economic trap.** For small/rare caches, explicit can cost MORE than no caching — storage fee exceeds read savings. Breakeven for Gemini 2.5 Flash ≈ 4 queries/hour per million cached tokens. Below that, implicit-only (just stable prefix, no markers) wins.

**v1 decision.** Accept silent-cost-regression risk for Gemini small caches because default 5-min TTL keeps storage cost window tiny. The 1h-TTL opt-in is the trap; flagged as v1b follow-up `cache.gemini-implicit-vs-explicit` warning.

**Observability gap.** LiteLLM's `cached_tokens` populates for BOTH implicit and explicit hits. Cannot distinguish without GCP billing dashboard. `analyze-cache --from-trace` Gemini output should note this limitation when surfacing cache hits.

**Architectural constraint.** Gemini API allows only 1 cached block per request — `CachedContents` is single-blob. v1's single-breakpoint strategy aligns accidentally. Multi-breakpoint follow-up is **Anthropic-only**; multiple `cache_control` markers on Gemini collapse to the latest (already documented in Breakpoint Limit Handling section of spec).

### Anthropic per-TTL pricing precision (Phase E verification)

Anthropic charges 1.25× (5-min TTL) vs 2× (1-hour TTL) for cache writes. LiteLLM's `completion_cost()` may not distinguish per-TTL — verify in Phase E when 1h TTL becomes selectable. If LiteLLM doesn't distinguish:
- Conservative path: accept the 2× over-estimate.
- Manual path: compute write cost from raw `cache_creation_input_tokens` × per-provider rate, override `cost_usd` for cache-write events.

### OpenAI parallel-batch routing (Phase D spike)

LiteLLM exposes `prompt_cache_key` for OpenAI routing consistency. **Unverified for v1**: in parallel batch fan-out (e.g., chorus-scoring's 34 parallel calls), does setting the same `prompt_cache_key` across all 34 force them to the same server? Or does LiteLLM/OpenAI randomize? If randomized, parallel cache writes still race. Phase D spike with a small batch (4-8 calls) confirms before locking in.

### OpenAI `prompt_cache_retention` — potential v1 gap not addressed in spec

The TTL translation table in the spec marks OpenAI as "ignored" — strictly correct for `cache_control` markers (OpenAI auto-caches without them), but **OpenAI exposes a separate `prompt_cache_retention: "in_memory" | "24h"` parameter** that DOES control cache lifetime. Surfaced during §28 research via the LiteLLM caching docs; not folded into the spec.

The gap: OpenAI's auto-cache default retention is short (~5–10 min per OpenAI's docs). With pflow's `- ttl: 1h` on an OpenAI-target workflow, the current spec sends no OpenAI-specific parameter — the cache may expire before 1h elapses, silently under-delivering on the user's opt-in. This contradicts the "no silent behavior changes" principle.

**Phase C decision needed:** map `- ttl: 1h` → `prompt_cache_retention: "24h"` (closest discrete bucket above 1h)? Or accept as v1 limitation and queue for v1b? **NEEDS VERIFICATION:** confirm OpenAI's actual default-retention number with a Phase C spike (~$0.10 via the standard spike template) before committing to a mapping. If `24h` is the only non-default option, that decision is forced.

---

## Watch-for warnings (specific gotchas during implementation)

1. **Cache entries silently serving stale content** — the #1 risk. Mitigation: memo hash conditional inclusion of rendered `prompt_cache` content. Mandatory regression test: workflows WITHOUT `prompt_cache` produce identical hashes pre/post Task 159. Put this test in early; if it fails, STOP and fix before continuing.

2. **`## Cache` parsed but `prompt_cache:` references that don't resolve** — validation must catch with "Did you mean?" hints via `find_similar_items` from `core/suggestion_utils.py`. Same precedent as existing template-reference validation.

3. **Provider-specific cache behavior differences** — Gemini single-block (multi-marker collapse), OpenAI no-op `cache_control` (auto-cache only), Anthropic 4-marker limit. Tests should cover each provider's actual behavior, not assume uniformity.

4. **Test mock contract drift** — `MockLLMClient` is the only mock now. If cache rendering needs new test capabilities, reshape `set_response` (already supports `cost_usd`, `warnings`). Don't fork the mock.

5. **`test_plan_drift.py` is sacred (32 tests).** Enforces planner ↔ runtime parity. Phase C touches both `plan_node.py` and `instrumentation.py`. Must remain green throughout. If it fails, the planner lies about what will execute, and Task 156's `--dry-run` becomes wrong.

6. **`MockLLMClient.set_response(..., cost_usd=...)`** — cost values drift across LiteLLM pricing updates. For golden-file tests, pin costs explicitly via the mock so goldens stay stable.

---

## Hedged claims to verify during implementation

These were hedged at 70% confidence in earlier braindumps. Plan-writing/implementation should validate before encoding as patches:

- **Diagnostic.id field doesn't break existing tests.** Identity tuple falls back to `id or message` when `id is None` — should preserve legacy diagnostic dedup. **Verify**: run `make test` after the Phase B Diagnostic edit; pay attention to `tests/test_core/test_diagnostic.py` and any diagnostic-equality tests elsewhere.
- ~~**Tier 2 walker LOC.** Spec says ~50 LOC mirroring the mermaid renderer's traversal pattern.~~ **Resolved §30:** verified ~130–240 LOC for skeleton + three analyses + cycle detection + result dataclass. Plan-writer encodes the realistic range.
- ~~**`core/llm_capabilities.py` mirrors `core/llm_providers.py`.**~~ **Resolved §30:** mirror pattern confirmed (frozen dataclass-tuple, dependency-free, `from __future__ import annotations` + `from dataclasses import dataclass`, module-level constant tuple, lookup helpers as plain functions).
- **`pflow save` round-trip preserves `## Cache` sections.** Assumed: save writes original markdown atomically. Not verified. **Test in Phase B**: round-trip a workflow with `## Cache` through save/load and confirm declarations survive byte-for-byte.
- **`WorkflowExecutor._compiled_workflow_cache` interaction with sub-workflow `## Cache`.** Wave 1 research suggested compile cache captures the compiled form (which includes the cache block) so it's fine — but worth a Phase C integration test where a sub-workflow's `## Cache` differs across two invocations within one run.
- **`list | str` shape for inputs/outputs in older workflows.** Some older test workflows declare `inputs:` / `outputs:` as either list or string. Cache renderer might interact oddly with that shape variation when `${var}` resolves to a value whose type depends on the declaration. Worth Phase C edge-case tests in `tests/test_integration/`.

---

## Out-of-scope reminders

These came up repeatedly during design; future agents should NOT propose them as v1 work:

- **ClaudeCodeNode caching.** Out of scope. SDK handles Anthropic prompt caching transparently; cache tokens already populate `llm_usage` (`claude_code.py:865-887`). Separate task if user controls become wanted.
- **Lyrics-generator workflow modifications.** Don't touch `/Users/andfal/projects/music-generation/` without explicit user permission. The user may want to add `## Cache` blocks themselves; ask first.
- **`pflow cache clear` CLI command.** Programmatic API exists; user-facing CLI is a follow-up.
- **Per-item TTL.** Block-level only in v1.
- **Multi-breakpoint placement** beyond v1's single-marker strategy. Anthropic-only follow-up.
- **Direct read of `~/.config/io.datasette.llm/keys.json`.** v1.x deferred; users migrate keys via `pflow settings set-env`.
- **MemoizationCache schema versioning.** No version column today; 24h TTL is the natural flush mechanism. Don't introduce versioning for Task 159.
- **`pflow cache apply`** command (Level 3 — programmatic auto-apply of analyze-cache suggestions). v1 ships analyze + suggest; apply waits for observed adoption.

---

## When in doubt

- **LiteLLM behavior on a specific cache scenario:** write a small spike (minimal Python file calling `complete()` under `scratchpads/`, ~$0.10/run). No existing template — Task 158's were cleaned up.
- **User preference on a design call:** ask. They prefer 20 turns over a wrong design.
- **Whether to add a feature beyond what's in the spec:** default no. Add the minimum to satisfy the spec; defer optimization.
- **Whether to refactor adjacent code:** if it isn't load-bearing for Task 159, don't. Spec scope is the contract.

---

## For the plan-writer specifically

The spec lists Phase B prerequisites but doesn't sub-order them, doesn't characterize the hardest piece of Phase D, and doesn't flag the co-edit gotcha. These bite during plan-writing.

### Phase B internal sub-ordering

Spec says "Phases B–D can land in parallel" — true, but B has internal dependencies:

1. **`Diagnostic.id` field first** (10 LOC, `core/diagnostic.py` per DD#27). Independent foundation; everything cache-namespaced depends on it. Verify `make test` immediately — pay attention to `tests/test_core/test_diagnostic.py` and any diagnostic-equality tests in `tests/test_core/`. The identity-tuple change (`(severity, source, node_id, id or message)`) should preserve legacy dedup, but verify before assuming.
2. **`core/llm_capabilities.py`** (DD#32). Independent foundation; can land in parallel with #1. Mirrors `core/llm_providers.py`'s dataclass-tuple shape (dependency-free constraint).
3. **Parser + IR schema + `data_flow.py` validation.** Interdependent group; land together. Parser extension is the hardest sub-piece — introduces a new structural rule (`- key:` params + tagged code block directly under `## Cache`, today only allowed under `### entities`). Read `markdown_parser.py:271-274,422-447` (the orphan-content error path) before designing the patch.
4. **Memo hash conditional inclusion in `compute_node_config`** — LAST in Phase B, gated by the no-`prompt_cache` hash-stability regression test (DD#19). If that regression test fails, STOP and fix before continuing — silent stale cache is the #1 risk.

C and D can land in parallel after B. E is independent. F gates on B + C + E. G is the wrap.

### Phase D plumbing — option (c) was rejected post §29 verification

The spec's Non-Obvious Integration Points originally recommended option (c) (move auto batch-prefix detection to `batch_executor.py`). §29 verification revealed this is structurally wrong: **`batch_executor.py` does NOT do per-item template resolution.** It only resolves the outer `items_template` via `resolve_batch_items` and delegates per-item prompt resolution to a callback (`engine._execute_single_node`). The static prefix portion of the LLM prompt template is not in batch_executor's scope.

**Recommended replacement: option (a)** (now marked RECOMMENDED in spec). Engine injects the unresolved batch-bearing prompt template under a reserved key in `node.params` before calling `node._run`. LLMNode reads it from `params` during prep(), runs detection (find first `${item.X}` in the unresolved template, resolve non-batch references in the static portion using its existing template-resolver context, identify the static prefix), and appends the marker to the cache-content blocks list it passes to `complete()`. No batch_executor changes required.

The unresolved template lives at `NodeConfig.template_config.template_params["prompt"]` (verified `runtime/engine/types.py:12-46`). The injection happens once per call. The plan should specify the reserved param key (suggestion: `__prompt_cache_unresolved_template__`) and document it as engine-internal.

Read `runtime/engine/batch_executor.py` and the `_execute_single_node` callback in the engine to confirm the engine-injection point before committing the patch shape.

### Co-edit gotcha: category constants need three coordinated entries (not a single dual invariant)

§29 verification corrected an earlier mischaracterization. The comment at `executor_service.py:33-37` is about syncing `_FAILURE_CATEGORY_MAP["llm_failure"]`'s **value string** with the `LLM_FAILURE_CATEGORY` **string constant** in `core/diagnostic.py` — both must be the same literal `"llm_failure"`. Adding a cache failure category requires THREE entries (any one missed is silent until tested):

1. **String constant** in `core/diagnostic.py`: `CACHE_FAILURE_CATEGORY = "cache_failure"`. (Per DD#27.)
2. **Failure-context mapping** in `execution/executor_service.py::_FAILURE_CATEGORY_MAP` (lines 29-44): `"cache_failure": "cache_failure"` — using the string from #1, kept in sync per the lines-33-37 comment. Without this, cache exceptions don't get the `_diagnostic_context` attached.
3. **Renderer title** in `core/diagnostic.py::CATEGORY_TITLES`: e.g. `CATEGORY_TITLES["cache_failure"] = "Cache Failure"`. Without this, the renderer falls back to a generic title (not a hard failure, but degraded UX).

The same three-place pattern applies to `cache_warning` and `cache_advisory` if they're treated as full failure categories. If they only need a renderer title (no failure-context plumbing because they're advisory, not exception-driven), then only #1 and #3 apply for those two. Plan-writer decides per-category whether all three or only the title matters — `cache_failure` is the only one that flows from a typed exception (analogous to `LLMCallError`); `cache_warning` and `cache_advisory` are emitted directly from validators/analyzers without an intermediate exception, so #2 is unnecessary for them.

---

### Pre-plan-writing outcomes (session 2026-04-28, progress log §30)

Operational state going into plan-writing. Spec corrections applied this session live in the spec; the journey lives in progress log §30. Below: only operational context the plan-writer needs that doesn't fit elsewhere.

**Spec corrections applied (cross-ref only):** DD#32 per-version Anthropic thresholds; DD#37 added (OpenAI `prompt_cache_retention`); TTL translation table OpenAI column; Cache Rendering threshold reference; Per-Model Capabilities Table; Tracing and Cost Reporting; Cost Model Reference; OpenAI `prompt_cache_key` (now "emit", with 15 RPM soft-cap); Test Infrastructure llm_capabilities. Read the spec for current values.

**13-phase split (recommended; not locked).** Spec keeps high-level B–G framing. Operational sub-split:

- **B1** — Foundations: `Diagnostic.id` field + `core/llm_capabilities.py`. Independent; parallel.
- **B2** — Markdown parser state-machine extension + IR schema + `data_flow.py` cache validation. Interdependent; land together.
- **B3** — Memo hash conditional inclusion (`if prompt_cache_content: config["prompt_cache"] = ...`). Gated by no-`prompt_cache` hash-stability regression test (DD#19). STOP if the regression test fails.
- **C0** — Gemini explicit `cache_control` verification spike (~$0.10). Phase C blocker only for the Gemini code path; Anthropic and OpenAI can ship in C1 in parallel.
- **C1** — Adapter `complete()` signature widening (`system: str | list[ContentBlock] | None`) + Anthropic cache-rendering path.
- **C2** — Gemini cache-rendering path (gated on C0 spike outcome).
- **C3** — OpenAI cache-rendering path (`prompt_cache_key` MD5 + `prompt_cache_retention` per DD#37).
- **D** — Engine plumbing for unresolved-template injection (option (a), reserved key suggestion `__prompt_cache_unresolved_template__`) + auto-batch-prefix detection in `LLMNode.prep()` + prewarm execution (serialize-first-then-fan-out). Includes Phase D OpenAI `prompt_cache_key` parallel-batch verification spike (~$0.10).
- **E** — Trace 2.1.0: bump constant + extend `_add_llm_data` for `cache_key`, `cache_source`, `cache_age_sec`, `workflow_path`. Plan-level decision: extend `llm_usage` keyset (LLMNode writes) vs parallel dict (`_add_llm_data` merges) — recommendation: extend `llm_usage` keyset (mirrors how `cache_creation_input_tokens` already flows).
- **F1** — `cache_analysis` package skeleton: `warning_catalog.py`, `token_estimation.py`, `cross_workflow.py` walker (Tier 2), `padding_advisor.py`.
- **F2** — Analyzer engine: `analyze.py` + `summarize.py` + text/JSON renderers (`render_text.py`) + golden-file tests (mirror `test_mermaid_golden.py`).
- **F3** — CLI command (`cli/commands/analyze_cache.py`) + MCP parity (`execution_service.analyze_cache` + `@mcp.tool()` registration) + `--dry-run` nudge wiring.
- **G** — Deterministic serialization helper + `pflow guide caching` page + cross-references on `cache: bool` vs `prompt_cache:`.

C and D may parallelize after B3 lands. F gates on B + C + E. G wraps. Each sub-phase is a PR-sized chunk.

**In-phase paid spikes (~$0.30 total budget).** Three remaining; all are Phase-internal blockers, not pre-plan blockers:

| Spike | When | What to verify | If it fails |
|---|---|---|---|
| **C0 — Gemini explicit cache_control** | Phase C entry | Gemini call with explicit `cache_control: {type: ephemeral, ttl: "300s"}` actually fires `cachedContents` (returns `cache_creation_input_tokens > 0` on call 1, `cache_read_input_tokens > 0` on call 2). Distinguish from Gemini's IMPLICIT auto-cache (which fires regardless of markers). | Document Gemini explicit-cache as best-effort; ship anyway with caveat in `analyze-cache` Gemini output. |
| **D — OpenAI `prompt_cache_key` parallel-batch routing** | Phase D | 4–8 parallel calls with same `prompt_cache_key`: do most calls hit cache after the first one writes? (~15 RPM soft cap is documented; verify graceful degradation on small batches.) | Document degraded hit rate; emit `prompt_cache_key` regardless (it never hurts). |
| **E — Anthropic per-TTL pricing precision** | Phase E (only when 1h TTL ships) | Does LiteLLM's `completion_cost()` distinguish 1.25× (5-min) from 2× (1h) cache writes? | Compute write cost from raw `cache_creation_input_tokens` × per-provider rate; override `cost_usd` for cache-write events. |

Spike pattern: minimal Python file under `scratchpads/`, calling `litellm.completion()` directly (or pflow's `complete()` once Phase C signature widening lands), printing usage breakdown. Inject keys via `SettingsManager().load().env`. ~$0.10/run.

**Spike pattern (no template — write fresh):** minimal Python file under `scratchpads/`; inject API keys via `from pflow.core.settings import SettingsManager; for k,v in (SettingsManager().load().env or {}).items(): if v and k not in os.environ: os.environ[k] = v`; call `litellm.completion()` directly (or pflow's `complete()` post-Phase-C); print `response.usage` breakdown. Round 3 of progress log §30 verified the pattern works on a 4-scenario sweep at ~$0.50.

**Code-shape findings the plan-writer needs (not in spec or progress log values):**

- **Markdown parser extension (Phase B2)** is structurally novel — today the parser allows `- key:` params and tagged code blocks ONLY inside `### entities` (`markdown_parser.py:271-274,422-447`). `## Cache`'s shape (section-level params + section-level code block, no entities) is a NEW section mode. Estimated **40–70 LOC** in `markdown_parser.py` + **~10 LOC** in `ir_schema.py`. Plan-writer reads the orphan-content rejection path before designing the patch. Adding `_SectionType.CACHE`, registering in `_KNOWN_SECTIONS`, adding `_SECTION_DISPLAY_NAMES` + `_SECTION_SYNTAX_HINTS`, and extending the H2 transition state at `:310-327` to permit section-level YAML + a single tagged code block.

- **5-place co-edit pattern for typed cache failures.** When introducing a typed exception for cache failures (mirroring `LLMCallError`):
  1. `runtime/node_state.py` — `FAILURE_CATEGORY_*` constant.
  2. `core/diagnostic.py` — `*_CATEGORY = "..."` string constant.
  3. `core/diagnostic.py::CATEGORY_TITLES` — title entry.
  4. `execution/executor_service.py::_FAILURE_CATEGORY_MAP` — value string identical to #2.
  5. Typed-exception subclass with `to_diagnostics()` override (only if the failure flows through an exception path; v1 may emit cache validation directly via `Diagnostic` and skip this).

  For `cache_warning` and `cache_advisory` (validator/analyzer-emitted, no typed exception), only #2 + #3 apply. Plan-writer chooses per-category whether all 5 places or only the title-side 2 places matter.

- **`MockLLMClient.complete()` signature widening.** Today: `system: Optional[str] = None`. For Phase C cache-structure tests asserting on `system: list[ContentBlock]`, widen to `Optional[Union[str, list[dict]]]`. One-line type change; assertions read `mock.call_history_full[-1]["system"]` directly. Plan-writer adds this as a Phase C test-infra prerequisite.

- **`LLMNode` cache rendering split: `prep()` assembles, `_call_llm` passes through.** Today `prep_res["system"]` carries a raw string from `self.params.get("system")` (`llm.py:309`). Phase C: assemble `prep_res["system_blocks"]` (structured) in `prep()` from rendered cache content, then pass to `complete()` via the widened parameter. The `_call_llm` integration point (`llm.py:332-390`) is correct — inside ThreadPoolExecutor timeout AND inside retry loop boundary. `LLMCallError` deterministic errors short-circuit at the boundary; `LLMTransientError` re-raises for retry.

- **Trace 2.1.0 fields land via `_add_llm_data`** (`runtime/workflow_trace.py:202-238`) — single integration site that reads `node_output["llm_usage"]` and writes `event["llm_call"]`. New cache fields (`cache_key`, `cache_source`, `cache_age_sec`, `workflow_path`) flow by extending the `llm_usage` keyset (LLMNode writes them) — mirrors how `cache_creation_input_tokens` already flows. **`format_version` bump is one-line** at `runtime/workflow_trace.py:17`. Note: stale comment at `workflow_trace.py:545` references `_attach_llm_call_to_event` (the old name). Out of scope to fix that comment; flag in Phase E plan if Phase E touches the file.

- **`_synthesize_inline_workflow_id`** lives at `src/pflow/execution/runner.py:36-53` (NOT `runtime/runner.py` — there is no such file). Inline runs produce `"ir-hash:<32-char-md5>"`; trace 2.1.0 `workflow_path` carries this for inline runs, symmetric with `MemoizationCache.workflow_path` scoping.

- **`MemoizationCache.get_with_age` returns epoch, not age.** Signature: `Optional[tuple[action, output, created_at_epoch]]`. For trace 2.1.0 `cache_age_sec`, caller computes `time.time() - created_at` at the integration site (one-line at `_add_llm_data`).

For other open hedged claims see the "Hedged claims to verify during implementation" section above (two entries resolved this session, four still open as Phase-internal verifications).

---

> Read this file fully before code. Then check the spec is still in the state §30 left it, scan the latest progress-log entries for any new sessions, and verify with the user that they want to proceed. Don't start coding without authorization.
