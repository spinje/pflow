# Braindump: Task 158 — Design Complete, Implementation Not Started

**Context window situation:** Full design discussion (20+ turns across 2 days) + 9 parallel research subagents worth of codebase evidence. About to hit compaction. Writing down what's in my head that ISN'T in `task-158.md` or `progress-log.md`.

---

## Where I Am

Design is done. Task spec and progress log are both written and reviewed. Nothing is implemented. The user explicitly said they were still discussing — they have not authorized starting implementation.

If you pick this up: **verify the user wants implementation to start** before opening any PR. Their pattern (from auto-memory) is research → plan → **plan review** → implement. We haven't hit plan review yet. They might invoke `/ultrareview` or similar before green-lighting.

---

## User's Mental Model (use their exact words)

The user is unusually principled for this kind of design discussion. Their load-bearing phrases, with my reading of what they meant:

- **"agents are always writing pflow.md workflows, not 'users'"** — this changes the UX calculus. Optimize for LLM-agent readability, not human readability. When the two conflict, pick agent. Note: agents read **markdown-formatted text** more naturally than JSON — clear headers, prose, sections. JSON (`--format=json`) is a secondary mode for programmatic tooling (suppression lists, pipelines wrapping pflow), NOT the primary agent interface. Stable warning IDs and concrete fix actions matter in BOTH formats.

- **"I dont think we should auto apply caching if that means we have to change prompts that are declared in the workflow. but we can split it up if the whts sent is identical"** — The single most important principle in this whole design. It rejected several things I'd been sliding toward. Memorize it.

- **"we shouldnt optimize automatically for workflow reruns, that should be opt in"** — Don't assume reruns. Extended TTL is always opt-in.

- **"the IMPORTANT part is that when llm nodes use them they NEED to be imported in the same order as whats defined in the cache block"** — This wasn't my idea. It was theirs. Gave us the order invariant. They understand prefix-caching mechanics better than most users would.

- **"why couldnt you do [chorus-chooser.winning_chorus] directly?"** — When they ask this kind of question, they're right. I had been overcomplicating. Take it as a hint that I'm adding ceremony and simplify.

- **"lets take a step back and think hard"** — This means: slow down, don't ship the next draft, go explore. They'd rather have 20 more turns than a wrong design.

- **"im not sure why we would need a different ttl for different cache entries?"** — Same pattern. When they say "I'm not sure," the answer is usually "you're right, simpler wins."

- **"introspect deeply into your context window and make sure we havent missed anything"** — The research wave phase was their idea, not mine. They're willing to invest in verification. Use it.

- **"how should we handle if subworkflows also declare a cache block? maybe its an edge case thats either easy to solve or something we should defer?"** — Great pattern: they flag edge cases and ask whether to defer. Always answer: easy or defer, explicitly, with reasoning. Don't silently defer.

### Unstated user priorities I inferred

- They want pflow to remain the top 10% well-written codebase. Not enterprise-framework-like.
- They're allergic to silent behavior. Visible > invisible, always.
- They'd rather write strict validation that errors clearly than lenient parsing that guesses.
- They dislike verbose output but are fine with comprehensive output if it's structured.
- They trust research agents' output but want claims verified (drove Wave 2).

---

## Things that are NOT in the spec/progress log

### LiteLLM friction you should expect

1. **LiteLLM's extended-thinking support is unverified.** pflow uses Anthropic's thinking via `thinking_effort` / `thinking_budget` today. Whether LiteLLM passes these through cleanly or needs wrapping, I don't know. Spike this in Phase A.

2. **LiteLLM's `system: [{text, cache_control}]` structure is how cache_control reaches Anthropic.** I'm ~70% sure this is right from Wave 2A notes but didn't run a real call. The alternative path is `extra_body`. Prove one or the other in a spike before writing the adapter.

3. **LiteLLM's response shape is different from `llm` library's.** Today: `response.text()` (callable) + `response.usage()` (returns object or dict with `.input`/`.output`/`.details`). LiteLLM: `ModelResponse` with `.choices[0].message.content` + `.usage` with `prompt_tokens_details.cached_tokens` + `cache_creation_input_tokens` (Anthropic only). The adapter must normalize into the shape `LLMNode.post` already expects. Don't change LLMNode.post — make the adapter do the shape translation.

4. **LiteLLM has its own logger and debug output.** It's chatty by default. Silence it in the adapter init (`litellm.set_verbose = False` or similar) unless `DEBUG` is set. Check what env vars or module-level config it expects.

5. **LiteLLM might try to read its own config files or env vars beyond the obvious ones.** Test in a clean environment to confirm key resolution is deterministic.

### The #1 silent correctness risk

**The memo cache hash MUST include rendered `prompt_cache` content conditionally.** If you forget this, existing cache entries will hit for upgraded workflows and serve outputs produced WITHOUT the prepended cache content. Runtime will re-prepend at call time, causing memo and runtime to silently disagree.

The regression test for hash stability (no-prompt_cache → identical hash pre/post task) is **MANDATORY**. Put it in early in Phase C. If it fails, STOP.

Precedent: `batch_config` in `compute_node_config` at `runtime/engine/instrumentation.py:140-179`. Copy that exactly. Don't improvise.

### What the user will push back on during implementation

- **Any existing test behavior changing subtly.** Mock shape especially. Wave 1E found tests using three distinct mock mechanisms (shared `MockLLMModel`, inline `patch()` with plain `Mock`, and patch of module-local `llm.get_model`). Don't break any of them.
- **If `pflow settings llm` UX changes.** They're aware that `llm` CLI subprocess is a nicety, not critical. But the help-text audit is real work.
- **If LiteLLM exception messages differ from current friendly errors.** Class-name detection (`UnknownModelError`, `NeedsKeyException`) is in `nodes/llm/llm.py:435-452`. These messages are LOVED by the user's muscle memory. Keep the messages as close as possible.
- **If provider detection gets less robust.** Today: `model.Options.model_fields` introspection. Post-migration: model-name string sniffing. Slight regression in robustness. Wave 1B said the introspection comment at `llm.py:52-54` ("Anthropic Opus 4.5 has thinking_effort, thinking, AND thinking_budget — thinking_effort MUST be checked first") encodes a precedence. The hardcoded map MUST preserve that precedence. Getting it wrong silently degrades Opus 4.5 reasoning.

### Phase A concrete first move (spike before production code)

Before committing to any adapter design, write a 50-line spike:

```python
# spike.py
import litellm

# Mirror what LLMNode builds today
response = litellm.completion(
    model="anthropic/claude-opus-4-5-20251101",
    messages=[
        {"role": "system", "content": [
            {"type": "text", "text": "Long stable preamble..." * 200,
             "cache_control": {"type": "ephemeral"}}
        ]},
        {"role": "user", "content": "Short task"}
    ],
    temperature=0.5,
    max_tokens=1000,
)
print(response)
print(response.usage)
print(getattr(response.usage, "cache_creation_input_tokens", "NOT PRESENT"))
```

Run it. Observe:
1. Does `cache_control` in system content blocks actually reach Anthropic?
2. Does `response.usage.cache_creation_input_tokens` populate?
3. Does a second call hit cache?
4. What's the `response.choices[0].message.content` shape — str or list of blocks?

This one spike (maybe a $0.10 API call) will answer 80% of the Phase A design ambiguity. Don't write production code without it.

### What `cache_enabled` vs `cache` collision inside NodeConfig and RunnerConfig means

Both `NodeConfig` and `RunnerConfig` have `cache_enabled: bool` — same field name, completely different meanings. `NodeConfig.cache_enabled` = per-node opt-out from memo cache. `RunnerConfig.cache_enabled` = global `--no-cache` toggle. They're already a naming collision inside pflow internals. Don't make it worse. When threading `prompt_cache_items` through, use a NEW field name (something like `prompt_cache_items: list[str] | None`). Don't reuse `cache_*` naming.

### Test `test_plan_drift.py` is sacred

`tests/test_execution/test_plan_drift.py` enforces the planner ↔ runtime parity via 30 tests. It catches drift between `plan_node()` and actual execution. When you touch `plan_node.py` or `instrumentation.py` (both change for this task), this test MUST remain green. Do not weaken it. If it fails, the planner lies about what will execute, and Task 156's `--dry-run` becomes wrong.

### The 500-char mock truncation is load-bearing

`tests/shared/llm_mock.py:30` truncates `call_history[i]["prompt"]` to 500 chars. Multiple tests assert against this boundary. Don't remove it. Add a parallel untruncated field (e.g., `call_history_full` or `get_last_prompt_full()`) for cache-structure testing. Default stays truncated.

### ASSUMPTION: Save/load preserves `## Cache` sections

I assumed `pflow save` preserves the new `## Cache` section intact — it writes the original markdown atomically. **NEEDS VERIFICATION** in Phase B. Test: write a workflow with `## Cache`, save it, load via `pflow run`, confirm cache declarations survive round-trip.

### ASSUMPTION: Published skills preserve cache declarations

`pflow publish` as Claude Code skill (Task 119) — **UNCLEAR** whether the published skill carries the cache declaration. If it doesn't, agents using the skill don't benefit from caching. **NEEDS VERIFICATION** in Phase F or later.

### NEEDS VERIFICATION: Gemini TTL via LiteLLM

LiteLLM translates `cache_control: {type: ephemeral}` to Google's `cachedContents`. But does it support Anthropic's 1h-extended-TTL semantics on Gemini? Google's cache has its own TTL model. Check LiteLLM's provider-specific docs or source before committing to a shared `ttl: 1h` syntax.

### NEEDS VERIFICATION: OpenAI `prompt_cache_key` with parallel batches

LiteLLM exposes `prompt_cache_key` for OpenAI routing. Wave 2A said it improves consistency. In parallel batch calls (our chorus-scoring, 34 parallel), does setting the same `prompt_cache_key` across all 34 force them to the same server? Or does LiteLLM randomize? If randomized, our parallel cache writes race. Test this with a small batch.

---

## Things I Suspected but Couldn't Prove

- **LiteLLM might have hidden monkey-patching or threading concerns** that collide with pflow's tracing redesign. My gut says no but I didn't verify.
- **The `list | str` shape for `inputs` and `outputs` in some old workflows** might interact oddly with the new cache renderer. Check the edge cases in `tests/test_integration/`.
- **WorkflowExecutor's `_compiled_workflow_cache`** is keyed by resolved workflow path. If a sub-workflow's `## Cache` changes between invocations within the same run, does the compile cache become stale? Wave 1D suggested it's fine (compile cache captures the compiled form, which includes the cache block), but worth a test.
- **The parallel-batch cache write race** — all N calls fire simultaneously, all pay cache-write cost. Pre-warming fixes it. Without pre-warming (default in v1), analyze-cache should flag this for large N. I didn't emphasize this enough in the spec.

---

## What I Was About to Try Next (Had the Conversation Continued)

If the user had said "start implementation":

1. **Day 1**: LiteLLM spike (above). Confirm cache_control path and response shape.
2. **Day 2**: Scaffold `src/pflow/core/llm_client.py` adapter. Preserve LLMNode.post's expected shape. Unit tests with LiteLLM mock.
3. **Day 3-4**: Replace `llm.get_model` call sites (4 production files, 3 shallow + 1 deep). Keep behavior identical.
4. **Day 5-6**: Redesign tracing. Remove monkey-patch. Wrap adapter. Verify `test_plan_drift.py` green.
5. **Day 7**: Rewrite `tests/shared/llm_mock.py` + root fixture. Add untruncated mode.
6. **Day 8-10**: Mechanically fix ~212 tests. Mostly transparent — asserting on shared-store outputs, not mock internals.

That's Phase A only. Phases B–G follow.

I never verified these durations against actual task-156 velocity. The spec's "5-10 engineer-day" estimate is library-migration-only, doesn't include cache features. Realistic Phase A+B+C is probably 2-3 weeks full-time.

## CRITICAL investigation the next agent MUST do — "how thin is pflow's LLM wrapper post-LiteLLM?"

**User explicitly asked for this investigation.** Goes BEFORE committing to adapter design.

Context: pflow currently maintains parallel versions of things LiteLLM already provides:
- `core/llm_pricing.py` MODEL_PRICING table (~40 models, manually maintained, breaks on new model releases)
- Key discovery via `llm` CLI subprocess (LiteLLM uses env vars natively)
- Reasoning-options introspection (replaced in spec with hardcoded map — but LiteLLM may have its own capability detection)
- Response-shape translation (LLMNode.post expects `llm` library's shape)

**Question:** how much of this is still justified once LiteLLM is in? If we keep all of it, we're just wrapping LiteLLM thinly. That might be right (pflow semantics stable despite LiteLLM quirks) or might be unnecessary duplication.

**Concrete spike to run before Phase A commits to adapter shape:**

1. **Check LiteLLM's `response_cost` / `completion_cost()` accuracy** against our `llm_pricing.py` on ALL models currently in our table. Acceptable disagreement: 2%. Any bigger → investigate.
2. **Verify the Gemini cache double-count bug is resolved in the pinned version.** LiteLLM GH issue filed Sept 2025, closed via PR #15226 on 2025-10-07. Confirm the fix is present in whatever LiteLLM version gets pinned. Add a regression test: fire two identical prompts at `gemini/gemini-2.5-flash` with `cache_control`, compare LiteLLM's `response_cost` to hand-calculation from `cache_creation_input_tokens` / `cache_read_input_tokens`. If they agree, trust `response_cost` for Gemini. If not, the fix didn't land in our version.
3. **Check coverage.** LiteLLM's `model_prices_and_context_window.json` has hundreds of models. Ours has ~40. How many models are we missing today because of maintenance lag?
4. **Update latency.** How fast does LiteLLM's pricing DB update after a provider releases a new model? Check git history.
5. **Edge cases:** cache token multipliers (1.25× / 2× Anthropic write, 0.1× read), thinking tokens, structured output, image tokens.

**Three possible outcomes (document this decision explicitly):**

- **Outcome A: LiteLLM accurate and comprehensive.** Delete `llm_pricing.py`. Call `completion_cost()`. Maintenance burden gone.
- **Outcome B: Mostly accurate, edge-case bugs.** Use LiteLLM's `response_cost` as primary, `llm_pricing.py` as fallback for unknown-model case. Keep `llm_pricing.py` narrow.
- **Outcome C: Material bugs we can't trust.** Import LiteLLM's `model_prices_and_context_window.json` as data; run our own computation on top. Shared data source, pflow-owned math.

My guess: **Outcome B**, leaning toward importing data + keeping our math. But run the spike, let the numbers decide.

**If this spike shifts the decision, update the task spec accordingly.** Current spec assumes `llm_pricing.py` stays intact. That assumption is not load-bearing — it was the conservative default pre-investigation.

## Gemini caching has a dual-mechanism gap my research missed

The user surfaced external research I hadn't done. Summary of what's different from my spec:

**Gemini has TWO caching modes pflow's spec collapses into one:**

- **Implicit caching** — automatic for Gemini 2.5+, no API surface. Free (no storage cost, no TTL control). Minimum 1024 tokens (2.5 Flash) / 2048 (2.5 Pro). Fires when prefix is stable across requests.
- **Explicit caching** — via `CachedContents` API (what LiteLLM's `cache_control` triggers). 90% read discount BUT has storage cost charged by duration. Higher minimum (~4k-32k). Default 60-min TTL.

**Economic trap:** for small/rare caches, explicit can cost MORE than no caching because storage fee exceeds read savings. Breakeven for Gemini 2.5 Flash ≈ 4 queries/hour per million cached tokens. Below that, implicit-only (just keep prefix stable, no markers) wins.

**For lyrics-generator specifically:** song-creator cache is ~11k tokens, referenced ~60 times per run, 20-min duration. Almost certainly net-positive explicit. But a workflow with a 2k cache referenced 3 times would lose money on explicit.

**Implications for pflow:**

1. Our spec's "use cache_control markers always" approach on Gemini may be suboptimal for small caches. Users could get SILENTLY WORSE cost vs no declaration.
2. **Phase C spike required:** verify that `cache_control` on Gemini actually triggers explicit caching through LiteLLM, and measure storage cost vs read savings on a representative run.
3. **Observability gap:** `cached_tokens` in the response populates for BOTH implicit and explicit hits. Can't cleanly tell which mechanism fired without GCP billing dashboard.
4. **Architectural constraint:** Gemini allows only 1 cached block per request (it's the Gemini API, not LiteLLM limitation). Our v1 single-breakpoint strategy aligns with this accidentally. Multi-breakpoint follow-up (our planned future work) is Anthropic-only.
5. **LiteLLM cost bug for Gemini** (filed Sept 2025, closed via PR #15226 on 2025-10-07) double-counted cached tokens as 4× inflation. Appears fixed — but verify the fix is in the pinned LiteLLM version and add a regression test. If the pinned version is pre-fix, upgrade or fall back to our own pricing computation for Gemini.
6. **Model-specific minimum tokens:** current spec says 1024 generically. Should be model-aware (1024 Flash, 2048 Pro, 2048 Haiku, etc.).

**Adjust the spec:**
- Add caveat to "Tracing and Cost Reporting" section: "For Gemini specifically, compute cost from raw tokens via `llm_pricing.py`. LiteLLM's `response_cost` has had a documented double-counting bug; verify bug status at LiteLLM version pin time."
- Add new follow-up task: "Gemini implicit/explicit cache strategy selector — break-even analysis per workflow."
- Update "Multi-breakpoint per-call placement" follow-up to note "Anthropic-only; Gemini API is architecturally single-blob."
- Nuance minimum-token requirement to be model-specific.

**Meta lesson:** my Wave 2A research only verified `llm-anthropic`'s cache surface, didn't probe Gemini's dual-mechanism. Next agent: when researching provider support, always enumerate per-provider mechanisms, don't assume uniformity.

---

## Unexplored Territory

**UNEXPLORED:** What happens when a workflow with `## Cache` is executed with `--no-cache`? The flag disables memo cache (pflow layer); does it also disable prompt cache (LLM provider layer)? I'd say NO by default (`--no-cache` is about pflow memoization) but this should be an explicit decision. Worth adding to the spec.

**UNEXPLORED:** How does `pflow --dry-run` render a workflow with `## Cache` blocks? The planner doesn't execute LLM calls, so it can't verify the cache content resolves correctly. Does it attempt to render the cache block? Skip it? Show a placeholder? Need to check dry-run output semantics.

**CONSIDER:** The `pflow analyze-cache` output includes dollar estimates. These depend on `llm_pricing.py`'s MODEL_PRICING table. If a user runs a model that isn't in the table (new release, custom provider), estimates are None. The CLI should degrade gracefully ("estimates unavailable for this model") not crash or show $0.

**MIGHT MATTER:** Structured output (`output_schema`) with prompt caching. Anthropic's caching works with tools and structured output, but LiteLLM's `response_format` path might have edge cases. If a workflow uses BOTH `output_schema` AND `prompt_cache:`, the combined flow needs dedicated test coverage.

**CONSIDER:** Retries. LLM node retries via Node class's retry loop (3 attempts). If attempt 1 creates a cache entry and attempt 2 is a retry, attempt 2 hits its own cache — free. But what if attempt 1 WRITES the cache (pays 1.25-2×) and attempt 2 has a different resolved `${item.X}`? They're different cache entries. Verify no duplicate writes.

**UNEXPLORED:** MCP server exposure of `analyze_cache`. Wave 1E flagged MCP parity. Spec calls for it. But the exact MCP tool registration — where in `mcp_server/tools/execution_tools.py:354` list, what the async signature looks like — needs direct file read. My spec says "mirror the `plan_workflow` pattern" but the implementer should read the actual file, not trust my paraphrase.

**MIGHT MATTER:** LiteLLM dependencies pull in a lot (boto3, google-cloud-*, etc.). `pyproject.toml` size will grow. Ensure no security surprises. Run `uv pip list --tree` after migration and check.

**UNEXPLORED:** What if a user imports a workflow file into another via `- workflow: ./child.pflow.md` and child's `## Cache` references values that the PARENT also caches with the same name? No collision (different scopes) but incidental byte match = cross-workflow cache hit. Documented in spec §12 but worth an integration test.

---

## What I'd Tell Myself if Starting Over

1. **Probe library capabilities before designing around them.** I spent multiple turns on "LiteLLM vs direct SDKs" before checking what `llm-anthropic` could actually do. The Wave 2A `python -c "import llm; ..."` introspection command would have saved 3-4 turns.

2. **Read the real workflow file early.** Pattern A (cross-call reuse) emerged once I read lyrics-generator. Before that, I was thinking purely in terms of batches. The concrete workflow grounded every subsequent estimate.

3. **Resist the urge to add ceremony.** `[name]` markers, `${var}` references — both were unnecessary sophistication. User kept stripping them. Start minimal, add only when a concrete case requires it.

4. **When the user says "I think we need to dive deeper" or "let's take a step back" or "i'm not sure about this" — stop moving forward and explore.** They're faster than me at detecting premature commitment.

5. **Wave pattern is real. Use it.** Unknown unknowns + known unknowns as two distinct passes, parallel subagents, 4-5 at a time. Don't chain sequentially. Don't skip Wave 2 to save time.

6. **The spec can be long and the log can be long and it's fine.** This isn't a document you write for decoration. The research findings that hit the spec (cache field collision, memo hash correctness, LiteLLM verification) prevented real implementation-time pain.

---

## Open Threads

- User hasn't authorized implementation start. Assume not authorized until explicit.
- Plan-review step probably hasn't happened. If the user invokes `/ultrareview` or similar on the task spec, address feedback before Phase A.
- The question of whether `prompt_cache` should exist as a field on `ClaudeCodeNode` (currently explicitly out of scope) might come back. If ClaudeCode becomes pflow's preferred LLM node for some use cases, cache control may matter there too. Flag for user if relevant.
- The lyrics-generator workflow itself needs `## Cache` blocks added as part of end-to-end validation. User may want to do this themselves or may ask us to. Don't touch `/Users/andfal/projects/music-generation/` without explicit permission.
- I drafted 5-10 engineer-days in the spec. Honestly 2-3 weeks is more realistic once Phases D-G are added. If the user asks for an estimate, give them the real number.

---

## Relevant Files & References

### Core integration points (from research)
- `src/pflow/nodes/llm/llm.py:271-321` — `_call_llm`, integration point for cache rendering
- `src/pflow/nodes/llm/llm.py:35-114` — reasoning-options introspection to replace
- `src/pflow/runtime/engine/instrumentation.py:140-179` — `compute_node_config`, hash correctness
- `src/pflow/runtime/workflow_trace.py:520-574` — monkey-patch tracing to redesign
- `src/pflow/core/markdown_parser.py` — parser extension (custom state machine, NOT markdown lib)
- `src/pflow/core/ir_schema.py:143-298` + `:152-189` — jsonschema, `additionalProperties: False`
- `src/pflow/core/workflow/data_flow.py::validate_data_flow()` — shared validation location
- `tests/test_execution/test_plan_drift.py` — do NOT weaken
- `tests/shared/llm_mock.py:30` — 500-char truncation (load-bearing)

### Motivating workflow (do not modify without user permission)
- `/Users/andfal/projects/music-generation/workflows/lyrics-generator/lyrics-generator.pflow.md`
- `/Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md`

### Key tasks to cross-reference during implementation
- Task 95 — `llm` library integration (the thing being replaced)
- Task 96 — batch config conditional hash inclusion (precedent for `prompt_cache`)
- Task 108 — trace format 2.0.0 (now bumping to 2.1.0)
- Task 152 — MCP parity invariant
- Task 156 — `--dry-run` + `plan_node()` primitive (must not break)
- Task 205 (commit `2d40bdf9`) — `cache: bool` added; the field we're NOT colliding with

### Provider docs verified
- LiteLLM caching: https://docs.litellm.ai/docs/completion/prompt_caching
- Anthropic cache_control: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- OpenAI prompt caching (automatic): https://openai.com/index/api-prompt-caching/
- Gemini context caching via LiteLLM (translation to cachedContents)

---

## For the Next Agent

**Start by:** reading `task-158.md` and `progress-log.md` in full. They're 636 and ~460 lines. Read them. Don't skip to code.

**Before writing any code:** verify the user wants implementation to start. Their workflow pattern is research → plan → **review** → implement. We haven't done plan review. Say: "The task spec and progress log are complete. Before I start Phase A (LiteLLM migration), do you want to run `/ultrareview` or similar on the spec first, or is it approved as-is?"

**If they green-light implementation, your first move is a $0.10 LiteLLM spike** (see "Phase A concrete first move" above). Don't skip it.

**Don't bother with:**
- Rewriting ClaudeCodeNode (out of scope)
- Touching the lyrics-generator workflow files (user's, not ours)
- Optimizing cache order or padding (advisory only)
- Adding `pflow cache clear` CLI (follow-up)
- Per-item TTL (follow-up)
- Multi-breakpoint placement beyond v1 strategy (follow-up)

**The user cares most about:**
1. Agent-readable syntax (they quote this)
2. No silent behavior changes (the load-bearing principle)
3. The lyrics-generator actually getting cheaper (end-to-end validation, not just unit tests)
4. Existing `cache: bool` workflows continuing to work unchanged
5. `test_plan_drift.py` staying green

**When in doubt about:**
- Library behavior: run the spike, don't guess
- Message structure: check LiteLLM's actual output on a real call
- User preference: ask. They prefer 20 turns over a wrong design.
- Whether to add a feature: default no. Add minimum to satisfy spec.

**Watch for:**
- Subtle changes to exception-message text users depend on
- Test assertions that pattern-match on the `llm` library response shape
- Cache entries silently serving stale content (the #1 risk)
- Provider detection regression (model-name sniffing instead of introspection)

---

> **Note to next agent**: Read this document fully before taking any action. Then read `task-158.md` and `progress-log.md` in full. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed. Do not start coding without user authorization.
