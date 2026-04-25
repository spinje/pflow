# Braindump: Task 158 — Phase A complete (handoff to Phase B-G planning)

**Read first:** `.taskmaster/tasks/task_158/implementation/progress-log.md` §27-§33. Especially §32 (item #6 implementation, with the discriminator-loss + dead-field bug patterns) and §33 (the broader deferred-findings closeout + operational principles). The other surviving doc, `braindump-design-complete.md`, is still mostly accurate for design rationale.

This braindump captures what's in MY head from this session that isn't in the formal docs.

---

## Where Phase A actually is

5301 tests green; sacred plan-drift 32/32; `make check` clean; one architectural grep verifies the seal (`grep -rn 'import litellm\.exceptions' src/pflow/` returns exactly one expected match). Branch `feat/prompt-caching-lite-llm` is mergeable.

But "ready to merge" ≠ "user is done." Two open user-decisions block PR creation: CHANGELOG label (`Unreleased` vs version bump) and Gemini PR #15226 cost-doubling fix re-verification on 1.82.6 (cheap spike, ~$0.001, but never run because we accepted the release-date inference). Both surfaced repeatedly across sessions and never closed.

**ASSUMPTION**: the user wants the next agent to write the Phase B-G plan, not to re-litigate Phase A. Verify before starting design work.

---

## User's mental model — load-bearing principles, in their words

These shaped every meaningful decision this session and the prior ones. Use the user's exact phrasing back to them:

1. **"Simplicity of the FINAL code, not how easy it is to get there."** Asked verbatim at the inflection point for #6. Eliminates the "minimum diff" / "leave it as-is" defenses. If you propose a defensible-but-halfway change, expect this reframe.

2. **"What's the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet?"** The user's operational selector when alternatives are equivalent by LOC. Used to drive #6 to full seal, C8 to explicit tuple, C10 to surfacing-real-data over deleting-dead-code.

3. **"FULLY happy?" / "any loose ends?"** A debugging probe — NOT a procedural check. The user expects that the answer is sometimes "no, actually, here's what I missed." Don't claim done after pass 1. The §32 implementing agent caught two more bugs after each "any loose ends?" prompt; the pattern repeats.

4. **"agents are always writing pflow.md workflows, not 'users'"** (from braindump-design-complete.md, still load-bearing). This means: optimize error messages, JSON output, and structured fields for AI agents reading them programmatically. Stable warning IDs, structured `error_class`, machine-parseable cause fields > prose.

5. **"i dont think we should auto apply caching if that means we have to change prompts that are declared in the workflow. but we can split it up if whts sent is identical"** — THE load-bearing principle for Phase B-G. Pflow renders what was declared; never silently restructures. Splitting bytes into content blocks with `cache_control` metadata is OK because tokens are identical.

6. **"i think relative to cwd is correct here, this is an input to the workflow not a 'workflow asset'"** — the C4 framing. Distinguishes inputs (cwd-relative) from workflow assets (workflow-file-relative, like `code: @./helper.py`). Apply the same lens to any new path-handling decision.

---

## Tacit knowledge that isn't in the docs

### The two-pass shape is structural, not procedural

§32's implementation of #6 went: clean plan → clean impl → "FULLY happy?" probe → caught one bug → "/code-review" → caught two more critical bugs + six smaller → fixed → "any loose ends?" → caught a third (dead `error_class` field). That's normal, not exceptional. **Plan time for at least one critical-review pass after every "implementation done" claim**, even when tests are green. Tests verify what they were written to test; review catches what tests weren't written for.

### The discriminator-loss bug pattern generalizes

§32 documents it for `UnknownModelError(reason="missing_prefix" | "unknown_name")`. The pattern is: **substring-encoded sub-cases get silently discarded across module boundaries when the consumer catches without `as e`.** Anywhere pflow has a typed message-passing seam (Diagnostic objects, template error events, trace events, MCP error responses), this pattern lurks. Worth a `CLAUDE.md` note somewhere if you're touching that code.

### The "what almost broke" insight

The 6-parallel-agent verification round before any code change surfaced FOUR issues the original deferred-findings doc had missed:
- `test_missing_api_key_error` was silently broken since Phase A
- The dead BadRequestError branch had a downstream UX consequence (raw JSON envelope)
- C4's contract was real but the documented mechanism was fictional
- B11's effort estimate was 4-5× too high

This is the methodological lesson: **verify before implementing, even when the source doc is recent and detailed.** The deferred-findings doc was written 2 days before; still drifted. Future Phase B-G plan writing should re-verify against current code, not trust written specs.

### Gated tests rot silently

`test_missing_api_key_error` was broken since Phase A landed. `RUN_LLM_TESTS=1` gating hid it for weeks. **Other gated tests likely have similar latent breakage.** Before merging Phase A, someone should run `RUN_LLM_TESTS=1 uv run pytest tests/test_nodes/test_llm/test_llm_integration.py` against real keys at least once. Same for any other env-var-gated tests in the suite.

### The autouse-mock skip pattern is wider than `/llm/` suggests

The skip pattern in `tests/conftest.py:23-26` matches `/llm/` as a path substring. **It does NOT match `tests/test_nodes/test_llm/test_*.py`** because the substring there is `_llm/`, not `/llm/`. Every unit test under `tests/test_nodes/test_llm/` gets the autouse `mock_llm_client` applied — including `test_llm_integration.py`, which gates real calls via `pytest.mark.skipif(RUN_LLM_TESTS)`, NOT via the conftest skip pattern.

**The simpler workaround for tests needing real-adapter behavior** (which §32 alludes to but doesn't state plainly): patch `pflow.core.llm_client.litellm.completion` instead of `complete`. The autouse mock replaces `complete` itself; `litellm.completion` is one layer down and untouched. All adapter tests in `test_llm_client.py` use this pattern; it works.

### The plan-vs-implementation deviation pattern

My #6 plan was good. The implementing agent deviated in three ways, ALL improvements:
- Added the `reason` attribute pattern (caught a real bug; my plan had LLMNode catch without `as e`)
- Added the `error_class` field surfaced to `shared` (better JSON-mode UX; not in my plan)
- Added the `_api_key_tip` helper with no-keys-detected guidance (better defaults; my plan had bare `tip = ""` for that case)

**Lesson for future plans:** leave room for tactical improvement during implementation. A good plan describes the shape; a great implementation refines the details. Don't over-specify down to the message text.

### `enrich_llm_usage_with_cost` location is unresolved

It lives in `src/pflow/core/llm_client.py` (~10 lines at the bottom). The implementing agent argued for it from "documents the cost contract next to the adapter that establishes it." But it's used by `metrics.py`, `nodes/llm/llm.py`, `instrumentation.py`, `batch_executor.py` — most of those are runtime, not adapter. **A reviewer could reasonably argue it belongs in `metrics.py` or a new `cost_utils.py`.** This was flagged in the deleted Phase A review handoff and never resolved. Worth a quick decision before Phase B-G touches the cost path.

### What §32's "JSONSchemaValidationError NOT caught" really means

§32 says it's deferred because "rare in practice." The actual reason is more nuanced: `parse_structured_response` already converts JSON-decode failures to `LLMCallError` (post-#9). LiteLLM itself raises `JSONSchemaValidationError` only for `response_format` violations that the provider returned but the schema rejected — which is a different layer. **If Phase B-G adds tighter `response_format` validation, this catch may need to be added.** Add it then, with a real failure case as evidence.

### `MockLLMClient` thinking-budget gap

C10 surfaced real `thinking_budget` data via `_extract_thinking_budget(kwargs)` at the adapter layer. **The mock returns `thinking_budget=0` regardless of `reasoning_kwargs`.** Tests verifying thinking-metric flow get inaccurate data. Not blocking; flagged in §32 as deferred. **MIGHT MATTER:** if Phase B-G adds thinking-utilization tests against the mock, they'll silently always show 0% utilization. Either pin via direct `AdapterResponse` construction OR teach the mock to mirror the budget extraction logic.

---

## What's actually load-bearing for Phase B-G plan writing

These are open questions Phase A surfaced but didn't resolve. The Phase B-G plan author needs to address each:

1. **`## Cache` block parsing slots into a state-machine markdown parser, NOT a markdown library.** `core/markdown_parser.py` is line-by-line. Any new top-level section (`## Cache`) needs to integrate with `_Entity`, `yaml_items`, `yaml_item_lines`, `yaml_item_keys` parallel-list structure. **Source-line tracking is load-bearing for template error `At:` rendering — propagate carefully.**

2. **Cache rendering interacts with `prep_res["prompt"]`.** The rendered prompt is a flat string by the time `_call_llm` sees it. Cache rendering needs to split it into content blocks at the adapter layer, not at the LLMNode layer. The adapter is the natural seam (already constructs `messages` list via `_build_messages`). New code path: render cache content blocks → prepend to system message → place `cache_control` markers per provider rules. Adapter knows the provider; LLMNode shouldn't.

3. **Memo cache hash correctness is THE silent-correctness risk.** `compute_node_config` (`runtime/engine/instrumentation.py:140-179`) determines which cached output is served. If `prompt_cache` content prepends to system at runtime but is NOT in the hash, existing entries hit for upgraded workflows and serve outputs produced WITHOUT the prepended content. **Conditional inclusion** (mirroring `batch_config` precedent at the same function) is the only correct approach. **Regression test mandatory:** existing workflows hash identically pre-and-post.

4. **Validation-time data-flow rules for `prompt_cache:` order** live in `core/workflow/data_flow.py::validate_data_flow()`. Schema-level shape rules go in `core/ir_schema.py::FLOW_IR_SCHEMA`. Both are shared by `WorkflowValidator.validate()` AND `runtime/compilation/compile_validation.py`. One implementation covers all entry points — verified pattern from Phase A.

5. **The `_extract_thinking_budget(kwargs)` pattern generalizes.** It's the adapter owning request-side state extraction for response correlation. **Cache_control likely follows the same pattern**: adapter accepts `prompt_cache_items: list[str] | None`, extracts cache content from request kwargs, surfaces cache stats from response usage, all at one seam.

6. **`AdapterResponse.usage` is the single source of truth for everything observable.** Cost (`cost_usd`), reasoning tokens (`thinking_tokens`/`thinking_budget`), cache tokens (`cache_creation_input_tokens`/`cache_read_input_tokens`). Phase B-G's cache work should add cache-related fields here, not invent new return paths.

7. **`error_class` is a public field of LLMNode's error contract.** Documented in `_error_dict`'s docstring. Five paths pin it. **Any new error path in Phase B-G's cache work MUST populate it** — `CacheRenderError`? `CacheReferenceError`? Pick a typed subclass, set `error_class = type(e).__name__`.

---

## Things the user said / did that shaped the work but aren't in the log

- The user explicitly chose Option B for C10 ("surface real thinking-token data") over my recommended Option A (delete dead aggregation). The reasoning: "we should prioritize simplicity of the final code, not how easy it is to get there. Does this make sense?" — even though Option A was less code, Option B was the correct end-state because the dead aggregation was reading a real concept that just lacked a producer.

- The user's `/braindump` skill invocation at the end of this session is a STRONG signal they intend the next session to be a fresh agent. They want this handoff to count.

- The user uses `/loop` and `/schedule` skills regularly per their auto-memory. **CONSIDER:** if the next agent is doing PR-prep style work (CHANGELOG decision, Gemini spike, ultraview launch), the user might `/schedule` a follow-up agent in 2 weeks to verify the merged PR. Don't proactively offer this — let the user surface it.

- The user's pattern across sessions: research → plan → review → implement → code review → fix → manual test. The `/code-review` step is load-bearing — `review-agent-ux` caught the discriminator-loss bug in #6 that the implementer (and I, planning) missed. **Phase B-G plans MUST include a review checkpoint between design and implementation.**

- The user previously paid for `/ultrareview` on past PRs (per auto-memory). They might want to run it on the Phase A PR before merge. Surface this as an option without recommending one way or the other.

---

## What I'd tell myself at the start of this session

1. **Do #6 (the architectural seal) FIRST, not last.** Group A/B/C4/C8/C10 are cleanup; #6 is the load-bearing architectural change. Once the seal is in place, the smaller items flow naturally from a clean adapter contract. Doing them in the other order means the smaller items have to be designed against a leaky abstraction, then re-evaluated when the abstraction tightens.

2. **The 6-parallel-agent verification was the right call but I could have run it earlier.** If you're inheriting work that has a "deferred findings" doc, verify against current code BEFORE writing any plan. Specs drift, even 2-day-old ones.

3. **When the user asks "FULLY happy?" treat it as "look one more time."** Don't answer "yes" reflexively. Run another grep, re-read the test you just wrote, check that the field you added is actually surfaced to the consumer. The implementing agent for #6 caught their dead-field bug only after this prompt; I would have caught my own gaps faster if I'd internalized this earlier.

4. **The plan you write WILL be improved during implementation.** That's good. Don't over-specify message text or exact line counts. Specify the SHAPE — adapter raises typed exception with structured discriminator; LLMNode catches at single boundary; `import litellm.exceptions` leaves nodes/llm/llm.py — and let the implementing agent (you, future self, or another) refine the tactical details.

---

## Open threads — items the next agent should consciously decide on

1. **CHANGELOG version label.** `Unreleased` vs version bump (`v0.13.0`?). Process call. User decides.

2. **Gemini PR #15226 fix re-verification on 1.82.6.** Cheap spike (~$0.001, 1 minute). Convert release-date inference to direct evidence OR explicitly accept inference. If Phase B-G's analyze-cache feature ends up depending on accurate Gemini cost reporting, this becomes load-bearing.

3. **`enrich_llm_usage_with_cost` location.** Stays in `core/llm_client.py` or moves to `metrics.py` / new `cost_utils.py`? Decide before Phase B-G adds cache-cost wiring.

4. **`MockLLMClient` thinking-budget mirroring.** If Phase B-G writes thinking-utilization tests, the mock needs the matching extraction logic. Otherwise tests silently always show 0%.

5. **Real-API smoke test before merge.** Phase A's smoke was minimal (single LLM call, no batch, no nested workflows, no structured output, no attachments). A multi-feature workflow against the lyrics-generator would catch composition bugs unit tests miss. Cheap (~$0.05); high-confidence merge signal. **The user has mentioned the lyrics-generator as the motivating case ~10 times across sessions; verifying Phase A doesn't regress it is implicit.**

6. **The two retained `litellm.exceptions` references** (the `core/llm_client.py:35` import which is the seam, and the `nodes/llm/llm.py:449` informational docstring) — both intentional. Don't try to "clean them up" in a future PR.

---

## Unexplored territory for Phase B-G

**UNEXPLORED:** How does `pflow analyze-cache` surface partial-cost / unpriced data from the new B7 contract? `MetricsCollector.calculate_costs` returns `total_cost_usd: None` + `partial_cost_usd` + `unavailable_models`. The analyze-cache report needs to render this gracefully — design before writing the report formatter.

**UNEXPLORED:** Trace format 2.1.0 (per spec §22). Phase A made trace cost handling tri-state but kept `format_version: 2.0.0`. The Phase B-G plan needs to bump to 2.1.0 and add `cache_key` / `cache_source` / `cache_age_sec` per-event fields. Forward-compat via `startswith("2.")` gate.

**CONSIDER:** The `_extract_thinking_budget` pattern (request-side state extraction at adapter) suggests `_extract_cache_request_state(kwargs)` could mirror it for cache analytics. Adapter already builds the messages list with cache_control markers; could surface "what cache content was sent" as part of `AdapterResponse.usage` for trace correlation. Decide during plan.

**MIGHT MATTER:** Phase B-G is going to add a NEW field to `NodeConfig` (`prompt_cache_items: list[str] | None`). NodeConfig is NOT a frozen dataclass (verified in Phase A research). But it has a hash function (`compute_node_config`). Adding a field requires updating the hash conditional. Mirror `batch_config` precedent.

**MIGHT MATTER:** The `_PROPAGATED_KEYS` list at `workflow_executor.py:118-126` propagates parent shared state to child workflows. If cache data needs to flow parent → child (e.g., parent's cache items referenced in child's `prompt_cache:`), it needs adding here. Phase A added `_trace_collector` to this list; the pattern is established.

---

## Files that matter for Phase B-G planning

**Don't reinvent — read these first:**

- `src/pflow/core/llm_client.py` — the adapter is the cache-rendering integration point. `_build_messages` (line ~288) is where cache content blocks get inserted. `complete()` is where `cache_control` markers go. `_normalize` is where cache stats come from.
- `src/pflow/core/markdown_parser.py` — line-by-line state machine. New `## Cache` section integrates here. Source-line tracking via parallel lists is load-bearing.
- `src/pflow/core/workflow/data_flow.py::validate_data_flow()` — shared validation entry point. `prompt_cache` reference validation goes here.
- `src/pflow/core/ir_schema.py::FLOW_IR_SCHEMA` — schema-level structural rules. Top-level `cache` field + per-node `prompt_cache`/`prewarm` go here. **Both are `additionalProperties: False` — must be added explicitly.**
- `src/pflow/runtime/engine/instrumentation.py::compute_node_config` — memo cache hash. `prompt_cache` content threading goes here, conditionally (mirror `batch_config` precedent at lines 162-169).
- `src/pflow/runtime/workflow_trace.py::_LLMSummaryAccumulator` (added in B7) — accumulator pattern for per-summary aggregation. Reuse or extend for cache stats.
- `src/pflow/nodes/llm/llm.py::_error_dict` and `_api_key_tip` (added in #6) — helper pattern for error dict construction. Reuse for cache-related errors.

**Test infrastructure:**

- `tests/shared/llm_mock.py::MockLLMClient` — mock matches adapter's stable usage shape (post-C10). Cache-structure testing needs full prompt access via `call_history_full` (already added in §28 A.4 for "future Phase B/C tests").
- `tests/conftest.py` — autouse `mock_llm_client` is the only LLM mock. Path-substring skip pattern (`/llm/`) is documented above.

---

## For the next agent

**Start by:** reading `progress-log.md` §27-§33 (the "what was done" section), this braindump (the "what's in my head" section), and `braindump-design-complete.md` (the "why was it designed this way" section). Total ~600 lines. Don't skip — design rationale matters for plan judgment.

**Don't bother with:**
- Re-implementing anything from Phase A
- Re-litigating the typed-exception hierarchy (it's stable)
- Reorganizing the adapter (it's where it should be)
- Bumping LiteLLM (1.82.6 is pinned for the click 8.1.8 reason; track upstream when click 8.3+ becomes available)
- Touching the lyrics-generator workflow files (user's, not ours)
- Re-running the Phase 0 spike scripts (they're under `scratchpads/task-158-spike/`, kept as runnable docs, not committed)

**The user cares most about:**
1. Phase B-G plan reflects Phase A's surfaced-but-not-resolved questions (§33's "what Phase A confirmed for B-G plan writing" + this braindump's "what's actually load-bearing" section)
2. Memo cache hash correctness (the silent-correctness risk — see open threads)
3. The lyrics-generator workflow getting actually cheaper (end-to-end validation, not just unit tests)
4. Existing `cache: bool` workflows continuing to work unchanged (it's per-node memoization opt-out — different layer, different semantics)
5. `test_plan_drift.py` staying green throughout B-G work (sacred parity invariant)

**Watch for:**
- Anyone proposing changes that violate "pflow renders what was declared" (the load-bearing user principle)
- Anyone encoding sub-cases in message text instead of structured attributes (the discriminator-loss pattern)
- Anyone adding `import litellm.exceptions` to `nodes/llm/llm.py` (the seal must stay; only `core/llm_client.py` imports it)
- Tests asserting on prose error messages instead of `error_class` field (the structured contract is the public one)

**When in doubt:**
- About the design: ask. The user prefers 20 turns over a wrong design.
- About library behavior: spike. Don't guess. The Phase 0 spike pattern works — small scripts, real APIs, ~$0.10 total.
- About whether to surface a concern: surface it. Honesty over defensiveness is the user's load-bearing preference.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points (especially: the open user-decisions blocking PR creation, the load-bearing user principles in their exact words, the architectural patterns Phase A established that B-G must extend, and the unresolved `enrich_llm_usage_with_cost` location question), then state you're ready to proceed. Do not start the Phase B-G plan without confirming the user wants you to.
