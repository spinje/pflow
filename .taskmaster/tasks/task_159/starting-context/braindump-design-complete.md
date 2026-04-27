# Braindump: Task 159 — Caching Design Complete, Migration Done, Phase B–G Pending

**History:** This braindump originally documented "Task 158 design complete, implementation not started." That task split — Phase 0 + Phase A became Task 158 (LiteLLM migration, complete and ready for review), and the actual caching feature became Task 159. Most of the original design content survives because the user's principles and the cache-feature concerns weren't affected by the split. This file is updated for Task 159's current state.

---

## Where We Are

**Task 158 (migration) is complete in this branch.** The pflow-owned LiteLLM adapter (`src/pflow/core/llm_client.py::complete()`), typed exception hierarchy (`LLMCallError` + subclasses with structured discriminators), diagnostic pipeline integration (`category="llm_failure"`, `_diagnostic_context`), tracing seam (`shared["__trace_collector__"]` save/restore), and cost-from-LiteLLM contract are all in place. Performance fixes (lazy import) shipped. Real-API verified end-to-end.

**Task 159 (this task — caching) has NOT started.** No `## Cache` block parsing, no `prompt_cache:` field, no `prewarm:`, no `pflow analyze-cache`. Spec is written and revised through Phase 0 + A insights. Design is complete; implementation plan for Phase B–G has not been written (the user's pattern is: write plan post-migration informed by concrete LiteLLM behavior).

If you pick this up: **verify the user wants the Phase B–G plan written / implementation to start.** Their pattern is research → plan → **plan review** → implement. Migration is at the "ready for PR review" stage; the caching plan is a separate next step they may want to schedule independently.

---

## What's Already In Place (Task 158 Foundations)

These are facts about the current code, not assumptions. Phase B–G plugs into all of these:

- **Adapter**: `src/pflow/core/llm_client.py::complete(*, model, prompt, system, temperature, max_tokens, attachments, schema, reasoning_kwargs, model_options, timeout, trace_hook) -> AdapterResponse`. Single seam for every LLM call. `AdapterResponse.usage` dict has stable keys including `cache_creation_input_tokens` and `cache_read_input_tokens` (already normalized across providers).
- **Cache-control content blocks already work** through the adapter — the spike confirmed `messages=[{"role": "system", "content": [{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}]}]` reaches Anthropic / Gemini / OpenAI cleanly via LiteLLM. **What's missing is the pflow surface to declare and render those blocks** — that's Task 159's whole job.
- **Typed exception hierarchy**: `LLMCallError` (in `core/exceptions.py`) with `UnknownModelError(reason)`, `MissingApiKeyError(kind)`, `InvalidRequestError`, `LLMTransientError`, `LLMResponseParseError`. New cache-validation errors should follow this template — structured attributes, `to_diagnostics()` override, `category` constant.
- **Diagnostic pipeline**: `_FAILURE_CATEGORY_MAP` in `executor_service.py`, `_diagnostic_context` in shared store, `category="llm_failure"` for LLM failures. Cache validation errors might warrant `category="cache_failure"` (their own constant) — same pattern.
- **Trace seam**: `shared["__trace_collector__"]` save/restore around `engine.run`'s graph walk. `LLMNode` reads it; passes `collector.get_trace_hook(node_id)` to the adapter. **No monkey-patch.** Trace format 2.1.0's new cache fields (cache_key, cache_source, cache_age_sec, workflow_path) layer on top via the existing `_attach_llm_call_to_event` codepath.
- **Cost contract**: `AdapterResponse.usage["cost_usd"]` populated from LiteLLM's `_hidden_params["response_cost"]`. `core/llm_pricing.py` deleted; `enrich_llm_usage_with_cost` deleted. New-model-released-but-pricing-missing degrades to `cost_usd: None` + `pricing_available: False` flag.
- **Mock infrastructure**: `MockLLMClient` in `tests/shared/llm_mock.py` returns `AdapterResponse` instances. Has both `call_history` (500-char truncated, default — preserved for backward compat) AND `call_history_full` (untruncated, added during Task 158 in anticipation of cache-structure tests). Use `call_history_full` for asserting on rendered cache content blocks.
- **Autouse fixture**: `mock_llm_client` in `tests/conftest.py` patches `pflow.core.llm_client.complete` plus consumer-module bindings. The legacy `mock_llm_calls` / `MockLLMModel` infrastructure is gone.
- **LiteLLM version pinned**: `litellm==1.82.6` (NOT 1.83.7 as the original Phase 0 spike suggested — 1.83.x hard-pins click 8.1.8 which broke 3 CliRunner tests; 1.82.6 contains the Gemini PR #15226 fix per release date).

---

## User's Mental Model (use their exact words — still completely accurate)

The user is unusually principled for this kind of design discussion. Their load-bearing phrases:

- **"agents are always writing pflow.md workflows, not 'users'"** — this changes the UX calculus. Optimize for LLM-agent readability, not human readability. When the two conflict, pick agent. Agents read **markdown-formatted text** more naturally than JSON — clear headers, prose, sections. JSON (`--format=json`) is a secondary mode for programmatic tooling, NOT the primary agent interface. Stable warning IDs and concrete fix actions matter in BOTH formats.

- **"I dont think we should auto apply caching if that means we have to change prompts that are declared in the workflow. but we can split it up if the whts sent is identical"** — The single most important principle in this whole design. It rejected several things I'd been sliding toward. Memorize it.

- **"we shouldnt optimize automatically for workflow reruns, that should be opt in"** — Don't assume reruns. Extended TTL is always opt-in.

- **"the IMPORTANT part is that when llm nodes use them they NEED to be imported in the same order as whats defined in the cache block"** — This wasn't my idea. It was theirs. Gave us the order invariant. They understand prefix-caching mechanics better than most users would.

- **"why couldnt you do [chorus-chooser.winning_chorus] directly?"** — When they ask this kind of question, they're right. I had been overcomplicating. Take it as a hint that I'm adding ceremony and simplify.

- **"lets take a step back and think hard"** — Slow down, don't ship the next draft, go explore. They'd rather have 20 more turns than a wrong design.

- **"im not sure why we would need a different ttl for different cache entries?"** — Same pattern. When they say "I'm not sure," the answer is usually "you're right, simpler wins."

- **"introspect deeply into your context window and make sure we havent missed anything"** — The research wave phase was their idea, not mine. They're willing to invest in verification. Use it.

- **"how should we handle if subworkflows also declare a cache block? maybe its an edge case thats either easy to solve or something we should defer?"** — Great pattern: they flag edge cases and ask whether to defer. Always answer: easy or defer, explicitly, with reasoning. Don't silently defer.

- **"prioritize simplicity of the FINAL code, not how easy it is to get there"** (added during Phase A code-review iterations) — eliminates "minimum diff" defenses. Pick the cleaner final shape even if it means more migration effort now.

- **"what would the top 10% of codebases similar to this one implement?"** (also Phase A) — operational question for selecting between equivalent-by-LOC alternatives. Surfaces the right architectural answer.

### Unstated user priorities (inferred and confirmed through Phase A)

- pflow remains a top 10% well-written codebase. Not enterprise-framework-like.
- Allergic to silent behavior. Visible > invisible, always.
- Prefers strict validation that errors clearly over lenient parsing that guesses.
- Dislikes verbose output but fine with comprehensive output if it's structured.
- Trusts research agents' output but wants claims verified.
- Will push back on "minimum-diff" framing — wants the cleanest end-state, not the easiest migration.

---

## The #1 Silent Correctness Risk for Phase C

**The memo cache hash MUST include rendered `prompt_cache` content conditionally.** If you forget this, existing cache entries will hit for upgraded workflows and serve outputs produced WITHOUT the prepended cache content. Runtime will re-prepend at call time, causing memo and runtime to silently disagree.

**The regression test for hash stability** (no-`prompt_cache` workflows produce identical hashes pre/post Phase C) is **MANDATORY**. Put it in early. If it fails, STOP.

**Precedent**: `batch_config` in `compute_node_config` at `runtime/engine/instrumentation.py`. Copy that conditional-inclusion pattern exactly. Don't improvise. The function shape:

```python
if prompt_cache_content:  # non-empty list of rendered chunks
    config["prompt_cache"] = prompt_cache_content
```

Nodes that don't opt in keep their existing hash. Nodes that opt in get a distinct hash and fresh entries.

---

## test_plan_drift.py is sacred (32 tests)

`tests/test_execution/test_plan_drift.py` enforces planner ↔ runtime parity. When you touch `plan_node.py` or `instrumentation.py` — both will change for Phase C — this test MUST remain green. Don't weaken it. If it fails, the planner lies about what will execute, and Task 156's `--dry-run` becomes wrong. Verified green throughout Task 158's 15+ commits.

---

## Phase B–G Concerns (still relevant from original braindump)

### Cache field naming collision context

`NodeConfig.cache_enabled` (per-node memo opt-out) and `RunnerConfig.cache_enabled` (global `--no-cache` toggle) already share a name with different meanings. Don't make it worse. The new field is `prompt_cache_items: list[str] | None` (NOT `cache_*` naming). `prewarm: bool` is a separate field. The spec already uses these names.

### Save/load preserves `## Cache` sections — NEEDS VERIFICATION in Phase B

Assumed: `pflow save` writes the original markdown atomically, so `## Cache` sections survive round-trip. Test: write a workflow with `## Cache`, save it, load via `pflow run`, confirm declarations survive.

### Published skills preserve cache declarations — NEEDS VERIFICATION in Phase F or later

`pflow publish` as Claude Code skill (Task 119) — unclear whether the published skill carries the cache declaration. If it doesn't, agents using the skill don't benefit from caching.

### Gemini TTL via LiteLLM — NEEDS VERIFICATION before Phase C ships

Phase 0 spike confirmed `cache_control: {type: ephemeral}` reaches Gemini and triggers explicit caching. But Anthropic's 1h-extended-TTL semantics on Gemini? Google's cache has its own TTL model. Check LiteLLM's provider-specific docs or source before committing to a shared `ttl: 1h` syntax. Likely needs a translation layer or a per-provider TTL strategy.

### OpenAI `prompt_cache_key` with parallel batches — NEEDS VERIFICATION

LiteLLM exposes `prompt_cache_key` for OpenAI routing consistency. In parallel batch calls (chorus-scoring's 34 parallel), does setting the same `prompt_cache_key` across all 34 force them to the same server? Or does LiteLLM randomize? If randomized, parallel cache writes race. Test with a small batch.

### WorkflowExecutor compile cache + sub-workflow `## Cache` blocks

`WorkflowExecutor._compiled_workflow_cache` is keyed by resolved workflow path. If a sub-workflow's `## Cache` changes between invocations within the same run, does the compile cache become stale? Wave 1 research suggested it's fine (compile cache captures the compiled form, which includes the cache block), but worth a test.

### Parallel-batch cache write race (informed prewarm decision)

All N batch calls fire simultaneously, all pay cache-write cost. Pre-warming fixes it. Without prewarm (the `prewarm: false` case in v1), `analyze-cache` should flag this for large N. Resolved per DD#33 / DD#36: savings-ratio-based emission, advisory only — `cache.batch-prewarm-recommended` warning emitted by `analyze-cache` and `--dry-run`, never blocks `pflow run`. (Earlier framing of "hard validation error for large batches" was rejected — expensive analysis doesn't belong in the runtime validation path.)

### `list | str` shape for inputs/outputs in some old workflows — UNVERIFIED

Some older workflows have `inputs:` or `outputs:` declared as either a list or a string. Suspected but never proven: the cache renderer might interact oddly with that shape variation when `${var}` resolves to a value whose type depends on the input/output declaration. Worth checking edge cases in `tests/test_integration/` during Phase B parser work and Phase C rendering work.

## Gemini caching: dual-mechanism gap (still relevant)

**Gemini has TWO caching modes pflow's spec collapses into one:**

- **Implicit caching** — automatic for Gemini 2.5+, no API surface. Free (no storage cost, no TTL control). Minimum 1024 tokens (2.5 Flash) / 2048 (2.5 Pro). Fires when prefix is stable across requests.
- **Explicit caching** — via `CachedContents` API (what LiteLLM's `cache_control` triggers). 90% read discount BUT has storage cost charged by duration. Higher minimum (~4k-32k). Default 60-min TTL.

**Economic trap**: for small/rare caches, explicit can cost MORE than no caching because storage fee exceeds read savings. Breakeven for Gemini 2.5 Flash ≈ 4 queries/hour per million cached tokens. Below that, implicit-only (just keep prefix stable, no markers) wins.

**For lyrics-generator specifically**: song-creator cache is ~11k tokens, referenced ~60 times per run, 20-min duration. Almost certainly net-positive explicit. But a workflow with a 2k cache referenced 3 times would lose money on explicit.

**v1 decision** (per spec discussion): accept the silent-cost-regression risk for Gemini small caches in v1 because default 5-min TTL keeps storage cost window tiny. The 1h-TTL opt-in is what creates the economic trap; that's already opt-in. `analyze-cache` should warn for 1h TTL on Gemini (follow-up enhancement).

**Architectural constraint**: Gemini API allows only 1 cached block per request. v1 single-breakpoint strategy aligns accidentally. Multi-breakpoint follow-up is **Anthropic-only**.

**Observability gap**: `cached_tokens` populates for BOTH implicit and explicit hits. Can't distinguish without GCP billing dashboard. Note this in `analyze-cache --from-trace` Gemini output.

**Per-TTL pricing on Anthropic**: Anthropic charges 1.25× (5-min TTL) vs 2× (1-hour TTL) for cache writes. LiteLLM's `completion_cost()` may not distinguish per-TTL. Verify in Phase E when 1h TTL becomes selectable in `## Cache` blocks. If LiteLLM doesn't distinguish, either accept the 2× over-estimate (conservative) or compute write cost manually for the 5-min TTL case.

**Meta lesson** (still load-bearing for any provider research): when researching provider support during Phase B–G, **always enumerate per-provider mechanisms — don't assume uniformity.** The original Wave 2A research only verified `llm-anthropic`'s cache surface and missed Gemini's dual-mechanism entirely; only external research surfaced it. Similar traps likely exist for OpenAI's auto-cache thresholds, Anthropic's 4-marker limit interactions, and any future provider added to the matrix.

---

## Unexplored Territory (still applies to Phase B–G)

- **Structured output (`output_schema`) with `prompt_cache:`.** Anthropic's caching works with tools and structured output, but the LiteLLM `response_format` + `cache_control` combination needs dedicated test coverage in Phase C. Phase 0 spike verified the composition works on Anthropic Opus; broader provider matrix testing belongs in Phase C.

- **Retries.** LLM node retries via Node class's retry loop (3 attempts). If attempt 1 creates a cache entry and attempt 2 is a retry, attempt 2 hits its own cache — free. But if attempt 1 WRITES the cache (pays 1.25-2×) and attempt 2 has a different resolved `${item.X}`, they're different cache entries. Verify no duplicate writes. Note: Task 158's PATTERN EXCEPTION (BadRequestError → typed exception → no retry) means most deterministic LLM errors don't retry; only transient errors (Timeout / RateLimitError / InternalServerError) do.

- **MCP server exposure of `analyze_cache`.** Wave 1E flagged MCP parity. Spec calls for it. Mirror the `plan_workflow` pattern in `mcp_server/services/execution_service.py` and `mcp_server/tools/execution_tools.py`. Implementer should read the actual files, not trust paraphrases.

- **Workflow-importing-workflow cross-cache hits.** If a parent's `## Cache` references values that the child also caches with the same name — no collision (different scopes) but incidental byte match = cross-workflow cache hit. Documented in spec but worth an integration test in Phase C or F.

- **Tier 2 verification (cross-workflow cache-hit prediction)** — resolved per DD#26: in-by-default for v1. Walker is ~50 LOC mirroring the mermaid renderer's traversal pattern; rename detection (`cache.cross-workflow-rename-detected`) and prose-mismatch warnings (`cache.cross-workflow-prose-mismatch`) ship in v1. Auto-fix suggestions ("which prose canonicalizes?") deferred to v1b — picking the canonical prose has no clearly right answer.

- **`pflow analyze-cache` graceful degradation for unknown models.** Estimates depend on LiteLLM's pricing data. For custom endpoints, brand-new models, self-hosted Ollama, or anything LiteLLM doesn't have pricing for, `completion_cost()` returns `None`. The CLI must degrade gracefully — show "estimates unavailable for this model" not crash and not show $0. Task 158 established the `pricing_available: False` / `partial_cost_usd` / `unavailable_models` tri-state for runtime cost reporting; `analyze-cache` should mirror that shape for its dollar estimates.

---

## Things That Got RESOLVED During Task 158 (no longer concerns)

These were braindump items that worried me at design time. Phase A resolved them:

- ~~LiteLLM extended-thinking support unverified~~ → Verified working with Anthropic Opus 4.5. `thinking_effort` and `thinking_budget` translated correctly via `llm_reasoning_map.py` + adapter. Composes with cache_control + structured output.
- ~~LiteLLM message structure for cache_control unverified~~ → Confirmed the `system: [{text, cache_control}]` structure works on all 3 providers.
- ~~LiteLLM response shape unknown~~ → Normalized in `AdapterResponse`. `LLMNode.post()` simplified to a single dict-read code path.
- ~~LiteLLM logger chatty~~ → `litellm.suppress_debug_info = True` + `logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)` inside `complete()`. Zero stderr noise.
- ~~LiteLLM hidden config files~~ → Audited in clean HOME — none. Env vars only.
- ~~Pricing accuracy~~ → Outcome A: LiteLLM's `completion_cost()` is comprehensive (2,678 entries vs pflow's 41) and per-provider correct. `llm_pricing.py` deleted.
- ~~Gemini double-counting bug~~ → PR #15226 confirmed in 1.82.6 via live spike call.
- ~~Tests using three distinct mock mechanisms~~ → All consolidated to `MockLLMClient` + `mock_llm_client` autouse fixture.
- ~~Exception class-name string matching~~ → Replaced with `isinstance` on typed pflow exceptions; adapter is the single translation seam.
- ~~Provider detection via `model.Options.model_fields`~~ → Replaced with `llm_reasoning_map.py` hardcoded map. Anthropic Opus 4.5 `thinking_effort` precedence preserved.
- ~~LiteLLM dependency footprint~~ → 56 packages, no boto3/google-cloud-*/azure-*. No `[proxy]` extras needed.
- ~~Eager litellm import perf hit~~ → Lazy import inside `complete()`. CLI startup back to 0.3s.

---

## What I'd Tell Myself if Starting Phase B–G Over

1. **Probe LiteLLM's actual cache behavior per provider before designing rendering.** Phase 0 spike covered the basics; cache rendering edges (Gemini single-block, OpenAI auto vs explicit, Anthropic 4-marker limit) need provider-specific verification IN Phase C, not assumption-based design.

2. **Re-read the real workflow files before locking syntax decisions.** Pattern A (cross-call reuse) emerged once I read lyrics-generator the first time; before that, I was thinking purely in terms of batches. For Phase B–G, the lyrics-generator + song-creator + chorus-chooser files are the ground truth — re-read them when sizing analyze-cache output, validating the order invariant against real usage, and choosing prewarm thresholds. Concrete workflow grounds every estimate.

3. **The user kept stripping ceremony.** `[name]` markers, `${var}` references inside `prompt_cache:`, complex per-item TTL — all rejected. Start minimal.

4. **When the user says "lets take a step back" or "i'm not sure" — stop and explore.** They detect premature commitment faster than I do.

5. **Wave research pattern is real.** Use it for Phase B–G plan writing too. Unknown unknowns + known unknowns as two distinct passes, parallel subagents, 4-5 at a time.

6. **The progress log can be long. The spec can be long. It's fine.** Phase A's progress log is 2500+ lines and every section earned its place.

7. **Match the existing typed-exception pattern when adding cache validation errors.** `LLMCallError → to_diagnostics()` is the template. Don't invent a new error system.

---

## Open Threads (for Phase B–G)

- The lyrics-generator workflow itself needs `## Cache` blocks added as part of end-to-end validation. User may want to do this themselves or may ask us to. **Don't touch `/Users/andfal/projects/music-generation/` without explicit permission.**
- ClaudeCodeNode caching is explicitly out of scope. Might come back as a follow-up if Claude Code becomes pflow's preferred LLM node for some use cases.
- The 6 follow-up GH issues from Task 158 (#347-#352) — none block Phase B–G but several touch areas Phase B–G will modify (warning aggregation #351, cost display #350, secondary diagnostic context #352). Read them before starting Phase F.

---

## Relevant Files & References (post-migration)

### Core integration points

- `src/pflow/core/llm_client.py::complete()` — adapter; cache rendering layers in here (likely as a pre-call wrapper that builds the system content blocks).
- `src/pflow/core/llm_reasoning_map.py` — DONE; preserve, don't touch.
- `src/pflow/runtime/engine/instrumentation.py::compute_node_config` — extend with conditional `prompt_cache` inclusion. Mirror the existing `if batch_config:` pattern verbatim.
- `src/pflow/runtime/workflow_trace.py` — trace 2.1.0 cache fields land here. The collector seam itself (`shared["__trace_collector__"]`) is DONE; just add new fields to `_attach_llm_call_to_event`.
- `src/pflow/core/markdown_parser.py` — parser extension. Custom state machine, NOT a markdown library. Add `## Cache` to `_SectionType` and `_KNOWN_SECTIONS` etc.
- `src/pflow/core/ir_schema.py` — extend `FLOW_IR_SCHEMA` with top-level `cache` field AND per-node `prompt_cache` + `prewarm` fields. `additionalProperties: False` at both levels means explicit additions required.
- `src/pflow/core/workflow/data_flow.py::validate_data_flow()` — shared validation site. Cache reference validation (membership, order, batch-scoped reference rejection, unused-chunk warning) goes here.
- `src/pflow/runtime/engine/types.py::NodeConfig` — add `prompt_cache_items: list[str] | None = None` and `prewarm: bool = False`. Dataclass is not frozen; safe to extend.
- `src/pflow/runtime/compilation/compiler.py` — extract the new fields from `node_data` alongside existing `cache`. Single construction site.
- `tests/test_execution/test_plan_drift.py` — do NOT weaken.
- `tests/shared/llm_mock.py` — `MockLLMClient` exists; use `call_history_full` for cache-structure assertions; add `set_response(..., warnings=...)` already supports custom test data.

### Motivating workflow (do not modify without user permission)

- `/Users/andfal/projects/music-generation/workflows/lyrics-generator/lyrics-generator.pflow.md`
- `/Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md`
- `/Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md`

### Key tasks to cross-reference

- **Task 158** — LiteLLM migration (the substrate). Read its progress log §27-§37 for the architectural patterns now in place.
- Task 96 — batch config conditional hash inclusion (the precedent for `prompt_cache` inclusion).
- Task 108 — trace format 2.0.0 (Phase E bumps to 2.1.0).
- Task 152 — MCP parity invariant.
- Task 156 — `--dry-run` + `plan_node()` primitive (must not break; integration point for the dry-run nudge).

### Provider docs

- LiteLLM caching: https://docs.litellm.ai/docs/completion/prompt_caching
- Anthropic cache_control: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- OpenAI prompt caching (automatic): https://openai.com/index/api-prompt-caching/
- Gemini context caching via LiteLLM (translation to `cachedContents`)

---

## For the Next Agent

**Start by:** reading `task-159.md` and the relevant sections of Task 158's `progress-log.md` (§27-§37). Then this braindump. Don't skip to code.

**Before writing any code:** verify the user wants the Phase B–G implementation plan written. Their pattern is research → plan → **review** → implement. The Phase B–G plan does not yet exist (deferred until post-migration so it could be informed by concrete LiteLLM behavior, which we now have). Say: "Task 158 (migration) is ready for review. Before I write the Phase B–G plan for Task 159, do you want to review the spec changes first, or run `/ultrareview` on it?"

**If they green-light planning, the plan should be written informed by:**
- The actual adapter shape now in production
- Phase 0 spike findings (cache_control composition with thinking + structured output)
- Task 158's typed-exception + diagnostic-pipeline patterns
- The Gemini dual-mechanism reality (don't assume uniformity across providers)

**Don't bother with:**
- Rewriting ClaudeCodeNode (out of scope)
- Touching the lyrics-generator workflow files (user's, not ours, without explicit permission)
- Optimizing cache order or padding (advisory only in v1)
- Adding `pflow cache clear` CLI (follow-up)
- Per-item TTL (follow-up)
- Multi-breakpoint placement beyond v1 strategy (follow-up — Anthropic-only)
- Direct read of `~/.config/io.datasette.llm/keys.json` (deferred to v1.x)
- (Tier 2 cross-workflow verification was resolved in-by-default for v1 — see DD#26.)

**The user cares most about:**
1. Agent-readable syntax (they quote this principle)
2. No silent behavior changes (the load-bearing principle from the original design)
3. The lyrics-generator actually getting cheaper (end-to-end validation, not just unit tests)
4. Existing `cache: bool` workflows continuing to work unchanged
5. `test_plan_drift.py` staying green
6. The cleanest end-state code (not the easiest migration path)

**When in doubt about:**
- LiteLLM behavior on a specific cache scenario: write a small spike. The Phase 0 spike scripts under `scratchpads/task-158-spike/` are the template; ~$0.10/run.
- User preference: ask. They prefer 20 turns over a wrong design.
- Whether to add a feature: default no. Add minimum to satisfy spec.

**Watch for:**
- Cache entries silently serving stale content (the #1 risk — memo hash conditional inclusion is the mitigation; mandatory regression test).
- `## Cache` block parsed but `prompt_cache:` references that don't resolve (validation must catch; "Did you mean?" via `find_similar_items`).
- Provider-specific cache behavior differences (Gemini single-block, OpenAI no-op-cache_control, Anthropic 4-marker limit).
- Test mock contract drift — `MockLLMClient` is the only mock; reshape its `set_response` if cache rendering needs new test capabilities, don't fork.

---

> **Note to next agent**: Read this document fully before taking any action. Then read `task-159.md` and Task 158's `progress-log.md` §27-§37. When ready, confirm you've understood by summarizing the key points, then state you're ready to proceed. Do not start coding without user authorization.
