# Braindump: Task 159 — Plan refinement (Rounds 1–4 reviews)

**Sessions**: 2026-04-28 (plan-writing + Round 1 /code-review + consolidation pivot) → 2026-04-29 (Round 2 /code-review + architectural refinements + Round 3 /code-review + Round 4 targeted /code-review + 5 high-value top-10%-pattern additions). Plan is approved, refined four passes deep, and ready for execution. **Implementation has not started.**

> The journey is in `implementation/progress-log.md` §31 (Round 1), §32 (Round 2), §33 (Round 3), §34 (Round 4 + 5 high-value additions). The contract is in `task-159.md`. The HOW is in `implementation/implementation-plan.md`. This braindump only captures what isn't in those docs — **tacit knowledge, hunches, gotchas, and reasoning that lives in my head right now**.

---

## Where I am

Plan v4 is 1813 lines, four review passes deep, architecturally consolidated. The next agent runs three pre-authorized paid spikes (~$0.30 total — Gemini cache_control, OpenAI parallel routing, Anthropic per-TTL pricing) per the agent-handoff, records outcomes as a §35 progress-log entry, consults the new **Spike contingencies** table at the bottom of the plan (just before "Open hedged claims"), updates plan sections per the table if outcomes contradict encoded decisions, then begins B1.1.

The plan has zero spike content inside the phases (Round 2's course-correction held; Round 4 added a Spike contingencies subsection that maps spike → encoded-decision → if-contradicts-action without baking in fallbacks).

The architectural backbone (`CacheRenderContext` + `__pflow_cache_render__` shared key) survived four review passes intact. Successive structural reinforcements:
- Round 2: `CacheBlockIR` frozen dataclass; `MappingProxyType` outer wrap; restore-from-absent writes proxy({}) not None; shared `_resolve_chunk_value` helper.
- Round 3: `_CHUNK_ABSENT` sentinel for branch-absent symmetry; `cache.invalid-on-non-llm` rule (validator-reach gap); cross-layer co-edits for `cache_chunks_skipped`; engine save/restore simplified to single try/finally; `_EMPTY_CACHE_RENDER` module constant.
- Round 4: `_resolve_static_prefix_for_cache` companion helper (locks byte-identical resolution across ALL three cache paths); `cache.discrepancy` structured `context["root_cause_action"]` payload; JSON `format_version` evolution policy + constants; defensive isinstance guards enumerated; `Diagnostic` identity tuple multi-field-collapse fix (combined diagnostic with `invalid_fields: list[str]`).

Catalog has 12 entries. `EXPECTED_CATALOG_COUNT = len(CACHE_WARNING_CATALOG)` constant defends against count drift across docs/tests.

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

## What §33 / §34 don't capture (Rounds 3 + 4 tacit knowledge)

### Why I picked combined-diagnostic over namespaced-id for V6

`cache.invalid-on-non-llm` on a node with both `prompt_cache:` AND `prewarm:` declared. Three options I considered:

- **(a) ONE diagnostic with `invalid_fields: list[str]`** — picked. Matches mypy/ruff convention (one error per [rule, location] with multiple offenses listed). Identity tuple already handles dedup correctly. Best agent UX (one error → one "remove these N fields" intent).
- **(b) Namespaced ids per field** (`cache.invalid-on-non-llm.prompt_cache`, `cache.invalid-on-non-llm.prewarm`) — rejected. Variable IDs break F1 catalog static enumeration AND F2 per-warning-ID coverage test. More code, worse DX.
- **(c) Same id, different messages** — rejected. With `id` set (truthy), identity tuple `(severity, source, node_id, id or message)` collapses on `id` regardless of message — falls back to (a) or (b) shape; (c) doesn't actually work given pflow's identity tuple.

The Round-4 reviewer found (c) as the bug class; option (a) is the cleanest fix.

### Why I rejected belt-and-suspenders for V5 (schema vs `_validate_cache_block`)

Round-4 reviewer found my Round-3 dedup test was based on a misanalysis: schema-emitted shape errors and `_validate_cache_block`-emitted ones have different messages, no shared `id`, won't dedup via `(severity, source, node_id, id or message)`. Two fix options:
- **(a) Belt-and-suspenders**: keep both. Test asserts TWO diagnostics fire (intentional double-emit).
- **(b) Schema-only for shape**: schema validates `prompt_cache: list[str]`, `prewarm: bool`, `cache.ttl` enum. `_validate_cache_block` does only semantics (cross-refs, ordering, batch-scoped, non-LLM-type rejection) + defensive isinstance skip on the compile path.

Picked (b). Top-10% question (mypy/rustc/ruff): one rule per error condition, never two. Belt-and-suspenders means TWO places to maintain when shape constraints change — exactly the validation-consistency drift the review category exists to catch. Compile-path defense is just `isinstance` guards + `logger.warning`; deeper compile-time error surfaces normally. **This made the V6 fix simpler too** — `_validate_cache_block` doesn't have shape checks competing with semantic checks.

### Why `_resolve_static_prefix_for_cache` is its own helper, not a parameter on `_resolve_chunk_value`

The two paths produce DIFFERENT shapes:
- `_resolve_chunk_value(chunk, shared) -> str | _ChunkAbsentSentinel` — single-var, sentinel-eligible (ABSENT branch returns `_CHUNK_ABSENT`; both call sites filter).
- `_resolve_static_prefix_for_cache(template_str, shared) -> str` — multi-ref, no sentinel (ABSENT leaves the `${var}` literal in the string; matches existing TemplateResolver permissive behavior).

I considered unifying via a `mode` flag. Rejected — the sentinel semantics differ structurally (chunk: skip; static-prefix: leave literal). The shared invariant is `_deterministic_serialize` for substituted values, NOT a unified function body. The two helpers SHARE the deterministic-serialize call, which is what locks byte-identity for the same logical value across all three cache paths (chunk hash, chunk message, static-prefix auto-batch + analyzer prediction).

The bug this prevents: `TemplateResolver.resolve_template("${X}", shared)` for a dict `{"text": "abc"}` returns the dict (simple template preserves type per `runtime/CLAUDE.md`). `_deterministic_serialize` produces `'{"text":"abc"}'`. But `TemplateResolver.resolve_template("prefix ${X} suffix", shared)` is a complex template — substitutes via Python's default `str(value)` → `"prefix {'text': 'abc'} suffix"` (Python repr, NOT canonical JSON). Different bytes, silent cross-mode cache miss.

### Why `cache.discrepancy` structured payload is `dict`-shaped, not a per-cause typed dataclass

Spec line 944 left the `cache.discrepancy` shape open. I considered:
- Per-cause dataclass (`TtlExpiryAction`, `KeyMismatchAction`, ...) — rejected. Adds 5 dataclass definitions for marginal type-safety gain. JSON consumers (MCP, agent) would deserialize as dicts anyway.
- Loose `dict[str, Any]` — picked. Schema documented in `CACHE_DISCREPANCY_ACTION_PAYLOAD_KEYS`. Agents dispatch via `"raw_root_cause" in payload` (unknown-cause discriminator) or specific keys (`"suggested_ttl"`, `"skipped_chunk"`).
- Polymorphic union via JSON `"kind"` field — rejected for v1. Could add later as a non-breaking minor bump (per the new format_version policy).

The `suggested_ttl` field is a STRING (`"1h"`) NOT a duration object. Matches the YAML config; simpler. If future cache TTLs need finer granularity (e.g., minutes), the field can become `{"value": int, "unit": "hour" | "minute"}` via additive minor bump.

### Why I picked `EXPECTED_CATALOG_COUNT = len(CACHE_WARNING_CATALOG)` (computed) not a hardcoded constant

Round 3 left "10/11/12 catalog entries" in 5 prose sites despite Round 3 adding two entries. The drift class is real. Two fix options:
- Hardcode `EXPECTED_CATALOG_COUNT = 12` — rejected. Future entries require updating both the catalog dict AND the constant; if you forget, tests pass for the wrong reason (or fail with a confusing message).
- Compute `EXPECTED_CATALOG_COUNT = len(CACHE_WARNING_CATALOG)` — picked. Tautological to the catalog itself, but locks the count-vs-docstring/tests/MCP-schema alignment. Adding a new entry: zero cascade edits.

The test then asserts `assert len(CACHE_WARNING_CATALOG) == EXPECTED_CATALOG_COUNT` — passes trivially under the constant pattern, but the docstring-contract test asserts the docstring contains EVERY id in `CACHE_WARNING_CATALOG.keys()` (computed at test time). That's where the constant earns its keep.

### Why I skipped the "verification-only pass" before B1.1

After Round 4 + the 5 high-value additions, I considered running a final 30-min self-review that re-greps every Round 4 / 5-additions change against actual code shapes. The user said "yes go ahead, but do 5 agents for round 4" then later "yes" to all 5 high-value items, implying "ship Round 4 / 5-additions, don't gate on yet another pass."

I'd estimate the verification pass would catch 1-2 pseudo-code precision issues in the 5 high-value additions (specifically: the `_resolve_static_prefix_for_cache` regex pattern is referenced as `TEMPLATE_VAR_PATTERN` but the plan doesn't lock the import path; the per-cause structured payload's `"branch_node": None` default is documented but the analyzer code path that would supply it isn't yet). These are minor — implementation-time review catches them.

If the next agent wants to do the pass: 30 min, focused on the 5 high-value additions only. Worth doing if any pseudo-code feels under-specified during B1.1.

### The "verify against actual code" methodology shift (load-bearing for future rounds)

Round 3 sketched D.2 prewarm pseudo-code from memory of pflow conventions; result was wrong (`process_item` is a 5-tuple-returning closure, not a dict-returning function). Round 4 caught it via Read of `batch_executor.py:540-589`.

The lesson: **for any pseudo-code that depends on a function's signature, return shape, or symbol path, Read the target before encoding.** The 5-minute verification cost prevents hours of mid-implementation rework. Future rounds should follow this discipline by default.

The `/evaluate-review` skill, invoked in Round 4 after the 8-agent review returned, is what made this discipline explicit. The skill's framework (read review → verify findings via subagent + own reads → triage → form judgment → present plan) prevented the Round 3 pattern of encode-then-discover-bug-in-Round-N+1.

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

### From §33 (round-3 — diminishing-returns analysis)

- *"It seems we are not hitting diminishing returns on this. Im trying to undertand why? Or are you under a different impression? lets discuss first"* — the user pushes back on review-cycles when the cost-benefit isn't clear. Forced honest analysis: "are returns flattening?" became a falsifiable question (Critical-finding rate, confirmation rate, restatement rate). Round 3 cleared 7 Critical + 8 High-Priority + verified 87% of reviewer claims — not flattening yet. **Pattern**: when the user asks "why X?", they want analysis with evidence, not reassurance.
- *"go ahead, but do 5 agents for round 4"* — directional correction (5 not 8). User trusts the orchestrator's targeted-review reasoning but adjusts scope. Mid-stream, low-friction.

### From §34 (round-4 — read-the-actual-code)

- *"I want you to read all the relevant code so that you are not making the same mistakes again when writing pseudo or real code."* — load-bearing. Round 3's pseudo-code bugs (`process_item` shape, `node_state.ABSENT`, `TemplateResolutionError`) were all preventable by reading the target functions. The user noticed the pattern and made it an explicit instruction.
- *"Are we prioritizing simplicity of the FINAL code, not how easy it is to get there? Are we aiming for the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet?"* — the load-bearing lens for ALL fix-shape decisions. V5 (single source of truth), V6 (combined diagnostic), the helper unification, the catalog count constant — every Round 4 fix-shape decision was made under this lens explicitly. Future rounds should lead with this question.
- *"This applies to all potential fixes. Use /evaluate-review to understand how to think about this"* — methodology framing. The skill is the right shape for late-round reviews. Use it by default after Round 2.
- *"anything else that is HIGH value that we should consider fixing?"* — the user's openness to additional fixes IF they're high-value. Surfaced 5 items (helper unification, structured payload, format_version policy, defensive guards, spike contingencies). User said "yes all 5." Pattern: end-of-session "anything else?" is a low-cost prompt that surfaces the top-of-stack tacit knowledge.

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

(Updated through Round 4 — some resolved, some still open, some new from Rounds 3 + 4.)

### Resolved across Rounds 1–4

- ~~`cache.discrepancy` ID — open user decision~~ → 10th catalog entry under `cache_advisory` (Round 2).
- ~~Cache rendering errors in batch+continue+sub-workflow error category~~ → `template_error` (defer typed `CacheRenderError` to v1.x; Round 2).
- ~~Tier 2 walker LOC estimate~~ → resolved §30 (~130–240 LOC realistic).
- ~~`core/llm_capabilities.py` mirror pattern~~ → confirmed §30.
- ~~D.1 / D.2 unsafe `shared.get(K, {}).get(...)`~~ → all consumers use `(shared.get(K) or {}).get(...)` (Round 3 caught + Round 4 verified zero remaining).
- ~~F1 `cache.discrepancy` row's unresolvable `{root_cause_action}` placeholder~~ → dispatch map + per-cause required-context map + structured payload schema (Round 3 introduced dispatch; Round 4 added structured payload).
- ~~Validator step 8 reach for `prompt_cache:` on non-LLM nodes (claim: "step 8 catches it")~~ → FALSE; step 8 iterates `node["params"]` only. Fix: `_validate_cache_block` walks top-level node keys + emits `cache.invalid-on-non-llm` (11th catalog entry, Round 3) + V6 combined-diagnostic shape (Round 4).
- ~~Hash-vs-prep render symmetry on ABSENT branches~~ → `_CHUNK_ABSENT` sentinel + filter at both call sites; B3.4 adds branch-absent test + divergence-injection variant (Round 3).
- ~~D.2 prewarm pseudo-code shape (Round 3 treated `process_item` return as dict)~~ → verified 5-tuple destructure; `_collect_parallel_results` extended with `initial_completed`/`total` kwargs (Round 4).
- ~~`node_state.ABSENT` symbol path~~ → actual symbol is `NodeStatus.ABSENT`; corrected in Round 4 pseudo-code.
- ~~`TemplateResolutionError` reference in `_resolve_chunk_value`~~ → does not exist; pflow uses plain `ValueError` (Round 4).
- ~~Strict `workflow_path is not None` assertion in trace constructor~~ → would fire 40+ times in tests; dropped in favor of dedicated production-path integration test (Round 4).
- ~~Schema vs `_validate_cache_block` shape-error dedup test~~ → V5 fix: schema is single source for shape; `_validate_cache_block` does only semantics + defensive `isinstance` skip on compile path (Round 4).
- ~~Multi-field rejection on non-LLM node collapsing on shared `id`~~ → V6 fix: ONE diagnostic per node with `context["invalid_fields"]: list[str]` (Round 4).
- ~~`_resolve_static_prefix_for_cache` byte-divergence (`TemplateResolver.resolve_template`'s default `str()` for embedded refs)~~ → companion helper substitutes via `_deterministic_serialize` per ref (Round 4 high-value fix #1).
- ~~JSON `format_version` evolution policy~~ → `JSON_FORMAT_VERSION_MAJOR` constant + `format_version.startswith("1.")` consumer rule (Round 4 high-value fix #3).
- ~~Catalog count drift across docstring/tests~~ → `EXPECTED_CATALOG_COUNT = len(CACHE_WARNING_CATALOG)` constant; tests iterate `.keys()` rather than hardcode (Round 4).

### Still open (Phase-internal verifications)

- **B1.1**: `Diagnostic.id` field doesn't break existing tests. Verification: `make test` after the patch. Pay attention to `tests/test_core/test_diagnostic.py` and any diagnostic-equality tests in `tests/test_core/`, `tests/test_runtime/`, `tests/test_execution/`. Identity tuple change is null-safe by construction (`id or message` falls back to today's message-keyed dedup), but verify don't assume.
- **B2.1**: `pflow save` round-trip preserves `## Cache` byte-for-byte. Verification: round-trip test in `test_cache_block_parser.py`. If parser normalizes whitespace inside the cache code block, the round-trip fails — the fix would be to preserve trailing newlines in chunk prose.
- **B2.3**: `WorkflowExecutor._compiled_workflow_cache` interaction with sub-workflow `## Cache`. Verification: parallel-batch heterogeneous-children integration test (`test_subworkflow_cache_concurrency.py`). With `CacheBlockIR` frozen, this should pass — but the test is the only thing that confirms the freeze actually holds under concurrency. If it fails, the fix may require evicting compile-cache entries on a different keying strategy.
- **D.1**: `list | str` shape for older workflow inputs/outputs. Verification: `test_prompt_cache_value_types.py` with list/dict/scalar/None/empty-string/bytes resolved values.

### Newly identified across Rounds 2–4 (and still open or spike-gated)

- **NEEDS VERIFICATION** (Spike 3 — Phase E): `litellm.completion_cost()` distinguishes per-TTL Anthropic pricing. If it doesn't, the `_normalize` override in `llm_client.py:776-784` is needed. The plan E.1 is written assuming LiteLLM does distinguish — if Spike 3 fails, this is a Phase E plan update per the new Spike contingencies table.
- **ASSUMPTION** (Spike 1 Scenario A — Phase C entry): LiteLLM Vertex path correctly translates `cache_control: {"type": "ephemeral", "ttl": "300s"}` to Gemini's `cachedContents` API. If it fails: ship C2 with documented info note in `analyze-cache` Gemini output (per Spike contingencies table).
- **ASSUMPTION** (Spike 1 Scenario B — Phase C entry): Gemini accepts BOTH a system-cache marker AND a user-message-prefix marker in the same request without API error. If Gemini rejects: filter auto-batch marker on Gemini specifically (D.1 update per Spike contingencies table); flag as v1.x follow-up.
- **NEEDS VERIFICATION** (Spike 2 — Phase D): OpenAI `prompt_cache_key` parallel-batch routing actually clusters 4–8 parallel calls with same key on one backend. If randomized: document degraded hit rate in G.2 caching guide; emit `prompt_cache_key` regardless.
- **UNCLEAR**: how `node_state.get_node_status` behaves under parallel-batch concurrency for the chunk-absent check. Existing pflow node_state SHOULD be stable post-execution-of-upstream (DAG ordering guarantee per `runtime/CLAUDE.md`), but the test for this in C1.2 is sequential. If parallel-batch behavior matters here, the test needs to be parallel. Round 3's documented LIMITATION ("loop recovery × cache rendering") covers the main edge case; v1 ships with the documented invariant.
- **NEEDS VERIFICATION**: `MockLLMClient.set_response()` accepts `cache_creation_input_tokens` and `cache_read_input_tokens` after the C1.2 test-infra extension. Plan extends the signature; if any existing test breaks, surface.

### Round 4 still-open (post-Round-4 review unverified items)

- **MIGHT MATTER**: `_resolve_static_prefix_for_cache` references `TEMPLATE_VAR_PATTERN` constant. The plan says "import or re-derive at the call site" but doesn't lock the import path. Implementing agent picks: import from `pflow.runtime.template_resolver` (where the regex lives) OR re-derive next to the helper. Either is fine; lock during B3.3 implementation.
- **MIGHT MATTER**: `cache.discrepancy` `branch_node` field in the structured payload is documented as "optional — analyzer may not always identify the branching node." Concrete: the F2 analyzer's chunk-skipped detection logic isn't yet specified to extract `branch_node` — plan says optional but implementing agent might want to lock how it's identified or accept it stays None for v1.
- **CONSIDER**: V5 fix's compile-path defensive skip means a malformed `prompt_cache: 5` reaching the compile path emits `logger.warning` and proceeds; the deeper compile error then surfaces. Test asserts ZERO Diagnostics from `_validate_cache_block` and ONE `logger.warning`. The "deeper compile error" is implicit — the implementing agent needs to verify what error fires (NodeConfig construction? schema-via-different-path? compile-time exception?). Run the test and document the actual deeper error so the test can assert on it explicitly.
- **MIGHT MATTER**: function-scoped MockLLMClient fixtures — the plan locks this for Round-4-introduced tests, but the EXISTING test suite has session-scoped fixtures in places. Implementing agent should audit `tests/shared/llm_mock.py` fixture usage and decide whether to standardize project-wide or leave new-vs-existing scopes split.
- **UNCLEAR**: Round 5 prediction is "1-2 Critical in Round-4-introduced code (the new helpers, the structured payload, the spike contingency table)." If the implementing agent is paranoid and wants to verify, run a Round 5 with the same 5 agents (or just review-plan + review-test-fidelity for the new helpers). Skipping is also fine — implementation-time review (`/code-review` after each phase merges) catches the rest.

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
2. Read the agent-handoff for the three pre-authorized paid spikes. **Run them BEFORE B1.1.** Record outcomes as a §35 progress log entry (§33 = Round 3, §34 = Round 4 + 5 high-value additions; spike outcomes are §35). ~$0.30 total budget; user has authorized.
3. **Read the new "Spike contingencies" subsection at the bottom of the plan** (just before "Open hedged claims"). Maps each spike → encoded plan decision → if-contradicts-action. After §35 lands, update plan sections per the table BEFORE B1.1 patches start.
4. Read this braindump end-to-end. Sections "What §33 / §34 don't capture" and "Tacit knowledge I'm worried isn't documented anywhere" are the highest-value content.
5. Read progress log §31 (Round 1), §32 (Round 2), §33 (Round 3), §34 (Round 4) — chronological. §34 is the most recent and explains the V5/V6 fix-shape decisions + the 5 high-value additions.
6. Spec is the contract — read sections only when implementing the corresponding phase.

### Single load-bearing gate

**B3's regression test (no-`prompt_cache` workflows produce identical hashes pre/post task).** The pre-merge step is `golden_config_hashes.json` committed against `main` head BEFORE B3.1 patches. **Without the fixture, the gate is a tautology.** If you skip the fixture step, the gate doesn't catch the silent-stale-cache regression — and that's the #1 risk for this entire feature.

### What the user cares most about (priority order)

1. Agent-readable syntax and output (the load-bearing principle).
2. No silent behavior changes — visibility over invisibility.
3. End-to-end behavior on lyrics-generator (real provider, real cost reduction).
4. Existing `cache: bool` workflows continuing unchanged.
5. `test_plan_drift.py` staying green.
6. **Simplicity of the final code, not the easiest path to get there.**
7. **Clean doc separation — concerns belong to specific docs.** (Added §32.)
8. **Top-10% codebases similar to this one — what would mypy/rustc/ruff do?** (NEW — surfaced explicitly in §34. Apply this lens to every fix-shape decision. V5 single-source-of-truth + V6 combined-diagnostic both came from this question.)
9. **Read the actual code before writing pseudo-code that depends on its signature.** (NEW — load-bearing instruction in §34. The /evaluate-review skill operationalizes this.)

### When in doubt

- **Surface to user.** They prefer 20 turns over a wrong design. Especially when the answer involves an architectural pivot or a new abstraction.
- **Verify line numbers with grep.** Cite-and-fix-later is fine; cite-without-grep is not.
- **Run the pflow-codebase-searcher** for cross-cutting questions ("does X consumer use Y pattern?"). 5 minutes, saves hours of mid-implementation rework.
- **Don't add spike scripts to the plan** (round-2 lesson). They're informational, not implementation.

### Don't bother with

- Re-running the 8-agent review for v5. Rounds 3 + 4 are done; remaining review surface is implementation-time review (`/code-review` after each phase merges). If paranoid about Round-4-introduced code (the new helpers, structured payload, spike contingency table), run a TARGETED 2-agent review (review-plan + review-test-fidelity) on those sections only — that's the highest-value Round 5 shape.
- The `cache.cross-workflow-resolution-failed` ID idea (Suggestion 22). Resolved without a new ID — broken sub-workflow refs re-raise the existing `WorkflowValidationError`; cycles/depth-limit log at info.
- Test-file consolidation (Suggestion 29) — defer to your judgment when actually writing tests.
- The "verification-only pass" before B1.1 (skipped per user's "yes go ahead with all 5"). 30 min if you want it; not required.
- Adding more entries to the 5 high-value additions list. Round 4 + 5-additions has hit the natural ceiling on plan-stage refinement; further marginal value comes from running the spikes and starting B1.1.

### The two paid spike outcomes that matter most

- **Spike 1 Scenario A (Gemini explicit cache_control)**: if it fails, C2 ships with documented info note. Doesn't block.
- **Spike 1 Scenario B (Gemini multi-marker)**: if Gemini rejects the request (vs accepts and just collapses to last), D.1 needs to filter the auto-batch marker on Gemini specifically. Surface to user.
- **Spike 3 (Anthropic per-TTL pricing)**: only matters if 1h-TTL is actually used in v1. If LiteLLM doesn't distinguish, the `_normalize` override in `llm_client.py:776-784` is a Phase E follow-up patch.

---

## Relevant files & references

### Plan + context (re-read order)

- `implementation/implementation-plan.md` — the HOW (1813 lines, post Round 4 + 5 high-value additions).
- `implementation/progress-log.md` — §31 (Round 1), §32 (Round 2), §33 (Round 3), §34 (Round 4 + 5 high-value additions). Journey + insights.
- `task-159.md` — spec / contract.
- `starting-context/agent-handoff.md` — operational style + paid spike protocols.
- This file (`starting-context/braindump-2026-04-28-plan-writing-and-review.md`) — tacit knowledge, hunches, gotchas.

### Code anchors verified during plan refinement (Rounds 1–4)

- `src/pflow/core/CLAUDE.md:103` — Diagnostic identity tuple SSoT (must be updated to `(severity, source, node_id, id or message)` in B1.1).
- `src/pflow/core/diagnostic.py:69-92` — `Diagnostic.__eq__` and `__hash__`; identity tuple `(severity, source, node_id, message)` documented at line 70-79; `deduplicate_diagnostics` at line 124-132. Verified Round 4.
- `src/pflow/core/markdown_parser.py:1393` — `_build_node_dict` start; `cache` extraction at 1432; `prompt_cache` / `prewarm` extraction added in B2.1 next to it.
- `src/pflow/core/workflow/validator.py:559-638` — `_validate_unknown_params` (step 8); iterates `node["params"]` only at line 600 + 616. Verified Round 4 — does NOT see top-level `prompt_cache`/`prewarm` keys.
- `src/pflow/runtime/engine/batch_executor.py:524-611` — `_execute_parallel`; `process_item` closure at 540-589 returns 5-tuple `(idx, result, error, duration_ms, buffered_events)` at line 589. Verified Round 4.
- `src/pflow/runtime/engine/batch_executor.py:466-522` — `_collect_parallel_results`; destructures the 5-tuple at line 490. Verified Round 4.
- `src/pflow/runtime/engine/batch_executor.py:103-177` — `_pre_warm_compile_cache` (sub-workflow IR compile, NOT D.2 prewarm). Verified Round 4.
- `src/pflow/runtime/engine/instrumentation.py:139` — `compute_node_config`; `batch_config` precedent at 162.
- `src/pflow/runtime/engine/instrumentation.py:241/297/480` — `apply_memo_hit`/`write_memo_cache`/`handle_cached_execution` (all 3 need `_should_write_cache_metadata` gate).
- `src/pflow/runtime/engine/plan_node.py:35-68` — `plan_node()` — `compute_config_hash` runs FIRST (line 37-44), `resolve_templates` SECOND (line 50-56); `template_exception` early-return catches `except ValueError` at line 57. Verified Round 4.
- `src/pflow/runtime/node_state.py:25-59` — `class NodeStatus(Enum)`; `ABSENT/SUCCEEDED/FAILED`; `get_node_status(shared, node_id)` at 48-59. Canonical import: `from pflow.runtime.node_state import NodeStatus, get_node_status`. Verified Round 4.
- `src/pflow/runtime/template_resolver.py:198-212` — `extract_root_node_id(template_path) -> str` (always returns str, never None). Verified Round 4.
- `src/pflow/runtime/compilation/compile_validation.py:120-161` — `_validate_data_flow_at_compile_time` calls `validate_data_flow` at line 122; minimal `validate_ir_structure` at line 155 only checks `nodes`/`edges` arrays. Verified Round 4 (V5 fix relies on this).
- `src/pflow/runtime/workflow_trace.py:17` — `TRACE_FORMAT_VERSION`; `save_to_file` at 463; `_add_llm_data` at 202.
- `src/pflow/core/trace_report.py:463` — `format_version.startswith("2.")` consumer gate (corrected from 400 in Round 2).
- `src/pflow/execution/runner.py:36-53` — `_synthesize_inline_workflow_id` (NOT `runtime/runner.py`).
- `src/pflow/execution/executor_service.py:29` — `_FAILURE_CATEGORY_MAP`; dual-invariant comment at line 37.

### Empirical findings to encode in tests

- `litellm.token_counter` does NOT raise on unknown models — falls back to default tokenizer.
- `litellm.token_counter("model", text=None)` raises `ValueError`.
- `litellm.token_counter("model", text="")` returns 0.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
