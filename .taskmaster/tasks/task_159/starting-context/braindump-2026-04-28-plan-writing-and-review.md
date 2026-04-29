# Braindump: Task 159 — Plan refinement (Round 1 + Round 2 reviews)

**Sessions**: 2026-04-28 (plan-writing + first /code-review pass + consolidation pivot) → 2026-04-29 (second /code-review pass + architectural refinements). Plan is approved, refined, and ready for execution. **Implementation has not started.**

> The journey is in `implementation/progress-log.md` §31 (round 1) and §32 (round 2). The contract is in `task-159.md`. The HOW is in `implementation/implementation-plan.md`. This braindump only captures what isn't in those docs — **tacit knowledge, hunches, gotchas, and reasoning that lives in my head right now**.

---

## Where I am

Plan v2 is 1290 lines, two review passes deep, architecturally consolidated. The next agent runs three pre-authorized paid spikes (~$0.30 total — Gemini cache_control, OpenAI parallel routing, Anthropic per-TTL pricing) per the agent-handoff, records outcomes as a §33 progress-log entry, then begins B1.1.

The plan has zero spike content inside it (round 2's main course-correction). Spike outcomes either confirm the encoded decisions or trigger a plan update — they're not baked-in fallbacks.

The architectural backbone (`CacheRenderContext` + `__pflow_cache_render__` shared key) survived round-2 review intact. Three structural reinforcements were applied this session: `CacheBlockIR` frozen dataclass replacing `dict[str, Any]`; `MappingProxyType` wrap on the outer dict; restore-from-absent writes `MappingProxyType({})` not `None`; shared `_resolve_chunk_value` helper between `plan_node` and `LLMNode.prep`. Together these eliminate the parallel-batch concurrency surface and the silent-stale-cache risk by construction.

---

## What §32 doesn't capture (the WHYs, not the WHATs)

### Why `MappingProxyType` and not something more sophisticated

Python has no immutable dict in stdlib. Options I considered:

- `frozenset(items())` — wrong shape; consumers do `.get(node_id)`, not `in` checks.
- Custom `FrozenDict` class — over-engineering; the consumer surface is small.
- `MappingProxyType` (stdlib `types.MappingProxyType`) — the right answer. Read-only proxy over an existing dict; raises `TypeError` on mutation; near-zero overhead. Used by Python's `__dict__` semantics for class objects, so it's idiomatic.
- `dataclass(frozen=True)` per-row plus a tuple of rows — nuclear; agents would need a linear scan to look up by node_id.

The `MappingProxyType` choice is conservative — if it ever needs more (e.g. lazy construction, cache-aware reads), wrap with a richer class then. For v1 it's the minimum shape that enforces read-only.

### Why `cache.discrepancy` as 10th catalog entry, not generic Diagnostic

Spec line 944 left this open. Two options:
- 9th entry under `cache_advisory` (filling the slot reserved by DD#29's "10 entries").
- Generic Diagnostic without a stable `id` for the from-trace mode-4 example.

I picked the 10th entry. Reasoning (not fully captured in plan):

1. **Agents read warning IDs as the primary contract.** A trace-discrepancy finding is exactly the kind of thing an agent needs to filter/route on. Without a stable id, agents would have to grep the message string — fragile.
2. **DD#29's "10 entries" was a soft cap, not a hard cap.** The spec text says "Adding new IDs goes through design review." The orchestrator decision IS the design review.
3. **The mode-4 example uses it.** If we're emitting a Diagnostic in trace mode anyway, giving it a stable id costs ~5 LOC. Not having one costs every agent that processes traces.

If you (next agent) disagree: revert is simple — drop the 10th catalog row, leave the analyzer emitting a generic Diagnostic with `id=None` for mode-4 discrepancies. Test changes are localized.

### Why `template_error` (not new `cache_failure` exception) for cache-rendering errors in batch+continue+sub-workflow

The `cache_failure` category constant exists in `core/diagnostic.py` (added in B1.1 for forward-compat). But adding a typed `CacheRenderError` exception now means:
- New exception subclass.
- New `to_diagnostics()` override.
- New `_FAILURE_CATEGORY_MAP` entry (which I deferred to v1.x).
- Test fixtures for the new path.

For ~10 LOC of dead-code removal value. The `template_error` route is consistent with how `${var}` resolution failures already flow today — same builder (`build_template_error_diagnostic`), same diagnostic shape. Agent-facing UX is identical.

When `pflow cache apply` (Level 3 / v1b) ships and we need typed cache failures for programmatic recovery, that's the right time to introduce `CacheRenderError`.

### Why I cared about the `core/CLAUDE.md:103` SSoT comment

The plan's `(severity, source, node_id, id or message)` tuple change is null-safe — when `id is None`, falls back to today's `message`-keyed dedup. So existing tests don't break.

But the SSoT comment in core/CLAUDE.md says: *"Hash identity tuple: (severity, source, node_id, message) — keep it that way."* Future contributors reading that comment will REVERT the change as "drift." We've all seen that PR.

This is a load-bearing comment. Updating it is 2 LOC. Not updating it is a time bomb.

### Why I added the sub-workflow batch concurrency test to B2.3 specifically

The `CacheBlockIR` freeze is meaningless without a test that exercises the parallel-batch path. The original B2.3 hedged-claim test was sequential ("invoke same sub-workflow twice with different parent state"). Sequential runs SHARE the compile cache but never DEMONSTRATE that mutation would be a problem because there's no concurrent reader to corrupt.

A heterogeneous batch with `${item.workflow}` varying per item is the production shape (verified `workflow_executor.py:212–215`). It's the only test that actually exercises "two parallel readers see the same compiled `CacheBlockIR` reference." If this test passes, the freeze guarantee holds. If it fails, the freeze guarantee is broken — and it's better to find that in B2.3 than during lyrics-generator end-to-end at G.

### Why I picked `_resolve_chunk_value` as the shared helper, not just a doc note

The temptation was to write "MUST agree byte-for-byte" in both `plan_node` and `LLMNode.prep` docstrings and trust the implementer. That's a documentation-only enforcement.

The right answer is structural: extract the resolution+serialization into a single function both sites call. Then divergence is impossible by construction — change resolution behavior, both sites change together.

This pattern (extract-shared-helper-from-divergent-call-sites) is the same fix as the `_FAILURE_CATEGORY_MAP` invariant comment at `executor_service.py:33-37` (one literal string, both sites use the same constant). Trust the type system / shared-function structure, not docstring discipline.

### Why I deferred Suggestion 29 (test-file consolidation 19→~12)

Two reasons:
1. **Defer to implementing-agent judgment.** When the agent is actually writing tests, they'll see whether `test_prompt_cache_value_types.py` and `test_batch_cache_prefix.py` benefit from being one file or two. CLAUDE.md says "smaller is better" generally but doesn't prescribe a specific count.
2. **Test consolidation is the polish-layer concern.** It doesn't change correctness. If we ship 19 files and someone later consolidates to 12, fine. If we ship 12 and they grow to 19, also fine. Encoding a target count is bikeshedding.

If you (next agent) want to consolidate, the grouping would be:
- Fold `test_prompt_cache_value_types.py` into `test_batch_cache_prefix.py`.
- Fold `test_cache_serialization.py` into `test_prompt_cache_hash.py`.
- Combine `test_analyze_cache.py` + `test_analyze_cache_from_trace.py` into one parameterized file.

But don't lose tests in the merge — the test count doesn't matter, the assertion count does.

---

## User's load-bearing principles (preserved + extended)

These are the user's exact words that shaped specific decisions. Treat them as forcing functions during implementation.

### From §25-§27 (still load-bearing)

- *"agents are always writing pflow.md workflows, not 'users'"* — output design is for AI-agent readability. Markdown text > JSON for primary surface; JSON is secondary for tooling. Stable warning IDs matter in BOTH. Suggestions list explicit alternatives so agents see all paths that suppress the warning.
- *"I dont think we should auto apply caching if that means we have to change prompts that are declared in the workflow. but we can split it up if the whts sent is identical"* — DD#2. The single most important principle. pflow never silently restructures messages.
- *"the IMPORTANT part is that when llm nodes use them they NEED to be imported in the same order as whats defined in the cache block"* — DD#6. The order invariant came from the user.
- *"prioritize simplicity of the FINAL code, not how easy it is to get there"* — eliminates "minimum-diff patch" defenses. Pick the cleaner end-state.
- *"what would the top 10% of codebases similar to this one implement?"* — operational question for selecting between equivalent-by-LOC alternatives. Apply the auto-apply-vs-analyze test (mypy is right analog for v1, rustc is wrong analog).

### From §31 (consolidation pivot)

- *"yes stop and surface any important decisions with a large potential impact"* — the user wants ambiguity surfaced, not silently resolved.
- *"adapt as complexity arises during planning"* — mid-plan-writing structural changes are OK.
- *"is there any findings in the last round of reviews you havent adressed yet?"* — the user expects honest accounting of what's been deferred. Don't let "phase-internal" become silent skipping.

### From §32 (round-2 corrections — new this session)

- *"all spikes are authorized, no need for separate authorization, also spikes should be done before implementation (plan is executed) not at implementation plan"* — spikes are pre-plan work, not phases. They inform decisions; the plan encodes decisions.
- *"Can you explain what you are doing? it seems you are contaminating the spec with redundant information? if anything is relevant include the actual information in the plan, dont cross reference. this is the HOW to implement, the spike was to inform our decisions?"* — the doc-separation principle. Plan is HOW once decisions are made. Spike protocols, journey, contract live elsewhere. Each doc has its own concern; don't bleed concerns across.
- *"go ahead with A then lets discuss if any suggestions should be included in the plan"* — apply Critical + High-Priority items first, then evaluate Suggestions selectively. Don't bulk-apply polish without thinking about cost.

The interaction pattern that worked: I presented an action plan with my recommendations; user said "go" with directional corrections; I encoded; surfaced decisions I made; user adjusted course twice (mid-stream — once for spike auth gates, once for spike location). **The user reviews mid-stream when something feels off, not at the end.** This is faster than wait-for-full-output review.

---

## Tacit knowledge I'm worried isn't documented anywhere

### The `CacheBlockIR` freeze + `MappingProxyType` are belt-and-suspenders, not redundant

Belt: `CacheBlockIR` frozen dataclass with `tuple` items — values are mutation-proof.
Suspenders: outer `MappingProxyType` wrap — the dict-of-CacheRenderContext is mutation-proof.

Why both? Because the consumer surfaces are different. A consumer might do:
- `cache_ctx = mapping[node_id]` — outer dict access, MappingProxyType protects.
- `cache_ctx.cache_block.items[0].name` — inner dataclass access, frozen protects.
- `cache_ctx.cache_block.items[0].name = "x"` — would corrupt without freeze.
- `mapping["new_node"] = ...` — would corrupt without MappingProxyType.

Both layers are independently violatable. Both need protection. Don't strip one as "redundant."

### The trace_report.py:463 vs :400 line citation issue

Round-2 review found it; my grep verified it. **Line citations drift.** The plan has ~50 of them. Re-verify before patching anything that depends on a specific line. The pattern that works: `grep -n "exact_string"` against the file at patch time. If the line moved, the patch instruction needs updating, not the patch itself.

### `litellm.token_counter` empirical findings — write these into F1's docstring

I verified during this session:
- Known model + valid text → deterministic count (returns 3 for "hello world test" on `claude-sonnet-4-5`).
- **Unknown model → falls back to default tokenizer, returns SOME count (does NOT raise).** This means the `"estimator"` source label fires for unknown models too — agents will get a number, possibly inaccurate.
- Empty text → returns 0 cleanly.
- `text=None` → raises `ValueError`.

The plan F1 says "log via `logger.warning` (not silent — review-silent-failures W2 — a model-name typo deserves visibility beyond a confidence label) and fall through to `heuristic`." This path fires only on `text=None` AND any future LiteLLM regression where unknown models start raising. **For unknown models today, the source label is `"estimator"` (slightly inaccurate), not `"heuristic"`.** The implementing agent should know this when writing the F1 token-estimation tests so they don't assume `"heuristic"` for unknown models.

### `_should_write_cache_metadata(node_type_name)` is a small helper, not a class method

I named it as a module-level helper in `instrumentation.py`. Three call sites use it. Defining it once and importing is cleaner than putting it on `NodeConfig` (which doesn't have node-type semantics) or making each call site re-check. If it grows beyond the LLMNode check (e.g., gating on ClaudeCodeNode in the future), this is the right home.

### F1 catalog table message_template format strings — what I trade off

For each of the 10 IDs, the message_template needs to be:
1. **Agent-parseable** — predictable format an agent can pattern-match.
2. **Human-readable** — a developer reading the rendered diagnostic should immediately see the issue.
3. **Concrete** — `{node_id}` and `{declared!r}` style placeholders, not `{0}` / `{1}` positional.

I leaned heavily on `!r` (Python's `repr()` formatting) for list-typed values like `declared` and `actual` in `cache.order-mismatch` because `repr` produces stable Python-list syntax (`['a', 'b', 'c']`) that round-trips through eval. Strings get the quotes; lists get the brackets. Cheaper than f-string formatting + manual quoting.

If the implementing agent finds the templates verbose, they can shorten — but **don't drop the named placeholders**. Agents will parse `{node_id}` to extract the offending node; positional `{0}` would break that.

### B3 baseline fixture shape coverage is non-negotiable

The `golden_config_hashes.json` fixture must include workflows that exercise EVERY hash-affecting shape, not "≥10 representative workflows." I enumerated 9 shapes in the plan. If even ONE shape is missing (e.g., extended_thinking), the regression gate has a blind spot for that shape — and that's exactly where silent-stale-cache hides.

The implementing agent should generate the fixture, then visually inspect the JSON. Each entry should clearly label which shape it covers. If you generate it and there's no clear "branching workflow" entry, ADD one before committing the fixture.

### `_synthesize_inline_workflow_id` lives at `execution/runner.py:36-53`, NOT `runtime/runner.py`

The handoff already calls this out, but I want to triple-emphasize because trace 2.1.0's `workflow_path` correctness for inline runs depends on this.

For inline runs (e.g., `pflow run --inline workflow-string`), the workflow has no file path. The synthesis function produces `"ir-hash:<32-char-md5>"` from the IR. Trace 2.1.0's top-level `workflow_path` field carries this for inline runs (matching `MemoizationCache.workflow_path` scoping). If the implementing agent looks for this function in `runtime/runner.py`, it doesn't exist. The runner is at `execution/runner.py`.

---

## ASSUMPTION / UNCLEAR / NEEDS VERIFICATION

(Updated from §31 — some resolved, some still open, some new this round.)

### Resolved this session

- ~~`cache.discrepancy` ID — open user decision~~ → resolved as 10th catalog entry under `cache_advisory`.
- ~~Cache rendering errors in batch+continue+sub-workflow error category — open user decision~~ → resolved as `template_error` (defer typed `CacheRenderError` to v1.x).
- ~~Tier 2 walker LOC estimate (~50 vs ~130-240)~~ → resolved §30 (~130-240 LOC realistic).
- ~~`core/llm_capabilities.py` mirror pattern — confirmed.~~ → resolved §30.

### Still open (Phase-internal verifications)

- **B1.1**: `Diagnostic.id` field doesn't break existing tests. Verification: `make test` after the patch. Pay attention to `tests/test_core/test_diagnostic.py` and any diagnostic-equality tests in `tests/test_core/`, `tests/test_runtime/`, `tests/test_execution/`. Identity tuple change is null-safe by construction (`id or message` falls back to today's message-keyed dedup), but verify don't assume.
- **B2.1**: `pflow save` round-trip preserves `## Cache` byte-for-byte. Verification: round-trip test in `test_cache_block_parser.py`. If parser normalizes whitespace inside the cache code block, the round-trip fails — the fix would be to preserve trailing newlines in chunk prose.
- **B2.3**: `WorkflowExecutor._compiled_workflow_cache` interaction with sub-workflow `## Cache`. Verification: parallel-batch heterogeneous-children integration test (`test_subworkflow_cache_concurrency.py`). With `CacheBlockIR` frozen, this should pass — but the test is the only thing that confirms the freeze actually holds under concurrency. If it fails, the fix may require evicting compile-cache entries on a different keying strategy.
- **D.1**: `list | str` shape for older workflow inputs/outputs. Verification: `test_prompt_cache_value_types.py` with list/dict/scalar/None/empty-string/bytes resolved values.

### Newly identified this round

- **NEEDS VERIFICATION**: `litellm.completion_cost()` distinguishes per-TTL Anthropic pricing. Spike 3 verifies this; if it doesn't, the `_normalize` override in `llm_client.py:776-784` is needed. The plan E.1 is written assuming LiteLLM does distinguish — if Spike 3 fails, this is a Phase E plan update.
- **ASSUMPTION**: `LiteLLM` Vertex path correctly translates `cache_control: {"type": "ephemeral", "ttl": "300s"}` to Gemini's `cachedContents` API. Spike 1 Scenario A verifies. If it fails: the C2 patch goes in anyway with the documented info note in `analyze-cache` Gemini output.
- **ASSUMPTION**: Gemini accepts BOTH a system-cache marker AND a user-message-prefix marker in the same request without API error. Spike 1 Scenario B. If Gemini rejects: filter the auto-batch marker on Gemini specifically (D.1 update); flag as v1.x follow-up.
- **UNCLEAR**: how `node_state.get_node_status` behaves under parallel-batch concurrency. The branch-absent check in C1.2 reads node_state during `LLMNode.prep`. If two parallel batch threads check status concurrently while an upstream node's status is transitioning, they could see different chunk sets. Existing pflow node_state should be stable post-execution-of-upstream (upstream completes before downstream batch dispatch), but the test for this in C1.2 is sequential — if parallel-batch behavior matters here, the test needs to be parallel.
- **NEEDS VERIFICATION**: `MockLLMClient.set_response()` accepts `cache_creation_input_tokens` and `cache_read_input_tokens` after the C1.2 test-infra extension. The current `set_response` accepts `cost_usd` (verified §31). The plan extends it; if the extension breaks any existing test that calls `set_response(cost_usd=X)`, surface to user.

---

## Unexplored territory

(Some preserved from §31 + new this round.)

### Preserved from §31

- **MIGHT MATTER**: `CacheRenderContext` is a closed frozen dataclass. If a future feature wants to add a new field, every implementation site needs to handle it. For v1.x extensions, this might bite — consider a tagged-union or optional-field protocol if feature growth happens here.
- **CONSIDER**: the new `## Cache` section uses a NEW structural mode in `markdown_parser.py` (section-level params + section-level code block, no `### entities`). Future markdown sections that want a similar shape (e.g., `## Tools`, `## Resources`) will need to mirror this pattern. Worth noting in `markdown_parser.py`'s docstring after B2.1 lands.
- **UNEXPLORED**: spec line 1075 says lyrics-generator is at `/Users/andfal/projects/music-generation/`. The handoff explicitly forbids modifying it without user permission. End-to-end verification scenario #1 requires running it. **Surface to user before running** — they may want to drive the verification themselves.
- **UNEXPLORED**: `pflow save --skill` (skill publishing path) for workflows with `## Cache`. Plan G.2 doesn't cover; the handoff says skill workflow is being reworked separately. v1 of Task 159 ships without skill-cache integration — confirmed implicitly by orchestrator decision this session.
- **MIGHT MATTER**: `_PROPAGATED_KEYS` in `WorkflowExecutor` does NOT include `__pflow_cache_render__` — each child engine.run installs its own per-workflow cache_render dict. This is correct for sub-workflow scoping (each `.pflow.md` declares its own cache block per DD#12), but the ALWAYS-INSTALL save/restore semantics rely on this not being in `_PROPAGATED_KEYS`. If a future contributor "tidies up" `_PROPAGATED_KEYS` and adds it, parent's cache_render leaks into the child. The plan B3.2 documents this in `runtime/CLAUDE.md` — make sure that doc note actually lands.
- **CONSIDER**: there's a single CLAUDE.md note ("`__` prefixed params are reserved" in `nodes/CLAUDE.md`) that says the convention for engine-internal params is dunder prefix. The consolidation removes ALL `node.params` injection — so `__prompt_cache_items__`, `__prompt_cache_unresolved_template__`, `__prewarm__` are gone. The CLAUDE.md note is not invalidated, but if future features want to inject into `node.params`, they should consider whether the `shared` key approach is preferable.

### New this round

- **MIGHT MATTER**: round-2 review noted that `Diagnostic.to_display_dict()` flattens context into top-level keys. Adding `id` field to Diagnostic creates a new top-level key. If any Diagnostic carries `context = {"id": "..."}` somewhere in the codebase, `setdefault` collision means the new field's `id` wins (or vice versa, depending on the flatten order). Search consumer surfaces (CLI JSON, MCP) for any current `context["id"]` usage before B1.1 lands. If found, rename the context field or skip the flatten for `id`.
- **UNEXPLORED**: `dependency_discovery.discover_dependencies` walks node params for file references. Cache chunks contain `${var}` template refs — should be ignored. The plan B2.1 adds an integration test for this. **But the walker's exact pattern is unverified**: does it walk `node["cache"]["items"]` (the new IR shape)? If yes, it might incorrectly flag chunk `var_expr` strings. Verify during B2.1.
- **CONSIDER**: the F1 SSoT catalog table I filled assumes `dataclasses.replace` semantics for partial overrides. If the implementing agent finds a more idiomatic Python pattern (TypedDict? Pydantic?), feel free to switch — but keep the table values as the SSoT, not move them into per-emitter code.
- **MIGHT MATTER**: `MockLLMClient.complete()` widening (`system: Optional[Union[str, list[dict]]]`) means existing tests passing `system="..."` continue to work. But if any test mocks `complete()` itself (not the method, but a sub-call) and asserts on the system parameter type, those break. Verify with a quick grep for "system=" call sites in test files.
- **MIGHT MATTER**: trace 2.0.0 hardcoded assertions exist in more places than just `test_workflow_trace.py:335`. Round-2 review found three additional sites: `test_runtime/test_trace_integration.py:170`, `test_core/test_trace_report.py:43`, `test_core/test_trace_report.py:1295`. Triage each before E.1 ships.

---

## Open threads (next-step suspicions, not committed work)

1. **Round-2 review didn't cover `pflow guide`** — Phase G.2 introduces a new `caching` topic. The `pflow guide` source code at `src/pflow/guide/topics/` (per CLAUDE.md convention) auto-discovers topic markdown files. But if there's a hardcoded topic list somewhere, the new file won't surface. Worth a 2-minute pflow-codebase-searcher dispatch before G.2 ships.

2. **The `cache_chunks_skipped` channel** I added to C1.2 + E.1 is NEW — it was a Suggestion 21 fix (from review-silent-failures C2). It writes a list to `llm_usage` per call. Trace 2.1.0 surfaces it. Analyze-cache from-trace mode reads it for discrepancy attribution. **But no test asserts the channel works end-to-end yet.** Phase E.1 has tests for `cache_key`/`cache_source`/`cache_age_sec` but `cache_chunks_skipped` is only mentioned in the C1.2 absent-branch test. Worth adding an E.1 test that runs a workflow with `${var}` resolving to ABSENT, captures the trace, and asserts the chunk name appears in `event["llm_call"]["cache_chunks_skipped"]`.

3. **B3 baseline fixture generation script needs to be written.** The plan describes it but doesn't include the code. The implementing agent writes it. **My hunch**: it's ~80 LOC. Loop over a fixed list of workflow paths, compile each, iterate node_configs, call `compute_config_hash(...)` per node, write `{workflow_path: {node_id: hash}}` JSON. The header should include a `# Coverage:` block listing which shapes each workflow covers (per the B3 mandatory-shape list).

4. **F1 catalog table values are based on my judgment, not user review.** I picked the message templates and suggestion strings using mypy/pylint conventions as the analog. The user might prefer different wording. **Worth surfacing the rendered output for one or two warnings (like `cache.batch-prewarm-recommended`) to the user before F1 ships** — same "show before you code" principle from CLAUDE.md.

5. **The `_resolve_chunk_value` shared helper** I introduced in B3.3 is a new abstraction. Plan-wise it's the right call (eliminates render divergence by construction). But the implementing agent might find that the resolution logic in `plan_node` and `LLMNode.prep` actually needs to differ in subtle ways (e.g., one uses `resolved_params`, the other uses `shared` directly). **If they genuinely differ, the shared helper becomes a wrapper that delegates** — still better than two independent implementations, just not a single function body.

6. **`cache.opportunities-available` ID is excluded from the catalog** but it IS emitted at runtime (from `summarize()` for the dry-run nudge). The F1 plan mentions a separate constant `CACHE_OPPORTUNITIES_NUDGE_ID` outside the catalog. Make sure F2's `summarize.py` actually uses this constant and not a string literal — the test should assert constant equality, not string equality.

---

## What I'd tell myself if starting over

- **Triage findings BEFORE encoding.** Round-2 had ~50 raw findings. I encoded ~30 in 2 hours. If I had triaged more aggressively to "what does the user actually care about" first, I'd have done it in 1 hour with the same end-state. The user's priorities (agent UX, no silent behavior, simple final code) should be the filter, not "every finding deserves response."

- **Ask before encoding spike contingencies.** I added 80 lines of spike protocol thinking it was helpful documentation. The user immediately objected. **Lesson: when adding a substantial new section to a doc, briefly state the intent first.** "I'm thinking of adding a Phase 0 section that consolidates the spike protocols. OK?" — would have caught the misframe in one turn.

- **Verify line citations with grep, always.** Round-2 review found `trace_report.py:400` was actually 463. My grep confirmed in 5 seconds. Cheap.

- **Use Python stdlib before reaching for external patterns.** `MappingProxyType` existed in stdlib since 3.3. I almost wrote a `FrozenDict` class. Read stdlib docs first.

- **Don't expand the spec catalog without surfacing to user.** I picked `cache.discrepancy` as the 10th entry. User said "go ahead with A" earlier covered this implicitly, but the explicit confirmation should have happened before the catalog row landed.

- **Doc-separation rules are real.** Plan = HOW. Spec = contract. Progress log = journey. Handoff = operational. Each doc has its concern. When something fits multiple, pick the one closest to the concern. Spike protocols are operational, not implementation. They live in handoff.

---

## For the next agent (you, or future me)

### Start here

1. Read `implementation-plan.md` "Architectural backbone — `CacheRenderContext`" section (~lines 7-87). This is the load-bearing decision. If you find yourself drifting to `node.params` injection or scattered shared keys, STOP — the architectural section explains why those failed.
2. Read the agent-handoff for the three pre-authorized paid spikes. **Run them BEFORE B1.1.** Record outcomes as a §33 progress log entry. ~$0.30 total budget; user has authorized.
3. Read this braindump end-to-end. The "Tacit knowledge I'm worried isn't documented anywhere" section is the highest-value content here.
4. Read progress log §32 for the round-2 journey. It explains why specific architectural decisions look the way they do.
5. Spec is the contract — read sections only when implementing the corresponding phase.

### Single load-bearing gate

**B3's regression test (no-`prompt_cache` workflows produce identical hashes pre/post task).** The pre-merge step is `golden_config_hashes.json` committed against `main` head BEFORE B3.1 patches. **Without the fixture, the gate is a tautology.** If you skip the fixture step, the gate doesn't catch the silent-stale-cache regression — and that's the #1 risk for this entire feature.

### What the user cares most about (priority order)

1. Agent-readable syntax and output (the load-bearing principle).
2. No silent behavior changes — visibility over invisibility.
3. End-to-end behavior on lyrics-generator (real provider, real cost reduction).
4. Existing `cache: bool` workflows continuing unchanged.
5. `test_plan_drift.py` staying green.
6. **Simplicity of the final code, not the easiest path to get there.**
7. **Clean doc separation — concerns belong to specific docs.** (NEW — added §32.)

### When in doubt

- **Surface to user.** They prefer 20 turns over a wrong design. Especially when the answer involves an architectural pivot or a new abstraction.
- **Verify line numbers with grep.** Cite-and-fix-later is fine; cite-without-grep is not.
- **Run the pflow-codebase-searcher** for cross-cutting questions ("does X consumer use Y pattern?"). 5 minutes, saves hours of mid-implementation rework.
- **Don't add spike scripts to the plan** (round-2 lesson). They're informational, not implementation.

### Don't bother with

- Re-running the 8-agent review for v3. The fixes are encoded; remaining review surface is implementation-time review (`/code-review` after each phase merges).
- The `cache.cross-workflow-resolution-failed` ID idea (Suggestion 22). Resolved without a new ID — broken sub-workflow refs re-raise the existing `WorkflowValidationError`; cycles/depth-limit log at info.
- Test-file consolidation (Suggestion 29) — defer to your judgment when actually writing tests.

### The two paid spike outcomes that matter most

- **Spike 1 Scenario A (Gemini explicit cache_control)**: if it fails, C2 ships with documented info note. Doesn't block.
- **Spike 1 Scenario B (Gemini multi-marker)**: if Gemini rejects the request (vs accepts and just collapses to last), D.1 needs to filter the auto-batch marker on Gemini specifically. Surface to user.
- **Spike 3 (Anthropic per-TTL pricing)**: only matters if 1h-TTL is actually used in v1. If LiteLLM doesn't distinguish, the `_normalize` override in `llm_client.py:776-784` is a Phase E follow-up patch.

---

## Relevant files & references

### Plan + context (re-read order)

- `implementation/implementation-plan.md` — the HOW (1290 lines, post round-2).
- `implementation/progress-log.md` — §31 (round 1), §32 (round 2). Journey + insights.
- `task-159.md` — spec / contract.
- `starting-context/agent-handoff.md` — operational style + paid spike protocols.
- This file (`starting-context/braindump-2026-04-28-plan-writing-and-review.md`) — tacit knowledge, hunches, gotchas.

### Code anchors verified during plan refinement

- `src/pflow/core/CLAUDE.md:103` — Diagnostic identity tuple SSoT (must be updated to `(severity, source, node_id, id or message)` in B1.1).
- `src/pflow/core/markdown_parser.py:1393` — `_build_node_dict` start; `cache` extraction at 1432; `prompt_cache` / `prewarm` extraction added in B2.1 next to it.
- `src/pflow/runtime/engine/instrumentation.py:139` — `compute_node_config`; `batch_config` precedent at 162.
- `src/pflow/runtime/engine/instrumentation.py:241/297/480` — `apply_memo_hit`/`write_memo_cache`/`handle_cached_execution` (all 3 need `_should_write_cache_metadata` gate).
- `src/pflow/runtime/workflow_trace.py:17` — `TRACE_FORMAT_VERSION`; `save_to_file` at 463; `_add_llm_data` at 202.
- `src/pflow/core/trace_report.py:463` — `format_version.startswith("2.")` consumer gate (corrected from 400).
- `src/pflow/execution/runner.py:36-53` — `_synthesize_inline_workflow_id` (NOT `runtime/runner.py`).
- `src/pflow/execution/executor_service.py:29` — `_FAILURE_CATEGORY_MAP`; dual-invariant comment at line 37.

### Empirical findings to encode in tests

- `litellm.token_counter` does NOT raise on unknown models — falls back to default tokenizer.
- `litellm.token_counter("model", text=None)` raises `ValueError`.
- `litellm.token_counter("model", text="")` returns 0.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
