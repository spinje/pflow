# Task 158 — Design Journey & Progress Log

**Purpose of this document:** Capture the full thinking that shaped Task 158 — reasoning, alternatives considered, pivots, user principles surfaced, and research findings. The task spec (`../task-158.md`) documents the final design. This log documents how we got there and why alternatives were rejected, so a future implementer understands the "why" behind each choice.

**Sessions:** 2026-04-22 → 2026-04-23

---

## 1. Origin — the problem framing

The user opened with: "I want to implement prompt/context caching for workflows. This would need to natively integrate with every part of pflow. Consider that we would have to replace Simon W's llm library, it does not support this. Considering LiteLLM — thoughts?"

Specific workflow driving the request: `lyrics-generator.pflow.md` at `/Users/andfal/projects/music-generation/workflows/lyrics-generator/` — ~181 LLM calls per run, significant redundant input tokens.

Two questions immediately emerged:
1. **Is this the right library choice?** The `llm` library was the incumbent, but unknown whether it could do what we needed.
2. **What's the UX?** Cache points in pflow.md — automatic, manual, or both?

The user explicitly asked for thoughts and tradeoffs, not a decision. That matched their stated preference (from memory): "discuss before implementing" — show design with concrete examples, get approval, THEN implement.

---

## 2. First library exploration — LiteLLM vs alternatives

**Options initially considered:**

| Option | Pros | Cons |
|---|---|---|
| **A. LiteLLM replaces `llm`** | Unified caching across Anthropic/Gemini/OpenAI; one code path | Large refactor; loses `llm` plugin ecosystem; thicker abstraction |
| **B. Direct Anthropic/Gemini SDKs, parallel to `llm`** | First-class caching; minimal disruption; incremental ship | Two code paths; caching only where we add the SDK path |
| **C. Extend `llm-anthropic` plugin to pass `cache_control`** | Smallest change | Upstream-dependent; Gemini needs separate plumbing |

**Initial lean: Option B** (direct SDKs parallel to `llm`). Reasoning at the time: "add SDK path behind a feature flag, keep `llm` as default, ship incrementally." This lean was later reversed — see Section 4.

---

## 3. First workflow read — Pattern A emerges

Read the lyrics-generator workflow file. Identified five redundancy patterns:

- **Pattern A — Sequential context reuse** in `song-creator` subflow: 4 big context blobs (`concept`, `concept_brief`, `creative_direction`, `song_architecture`) flow through ~15 sequential LLM calls per song. Probably 150–250k redundant input tokens per song path.
- **Pattern B — Chorus-chooser internal reuse**: 8 gen calls share 3–6k tokens of static prefix; 34 scoring calls share ~1.5k token rubric.
- **Pattern C — Analyze-source 6×N**: same source, 6 specialist lenses.
- **Pattern D — Concept-chooser 4 lenses + judge**: same brief, 4 lenses.
- **Pattern E — Curate-briefs**: shared instructions across 4 concepts.

Initial savings estimate: 30–50% cost reduction per run, 60–80% on reruns within 5-min TTL.

**Key early insight the user pushed on:** "This isn't just a batch thing — we're reusing the same big context objects continuously in multiple prompts." Pattern A (cross-call reuse) turned out to be the dominant savings opportunity, bigger than intra-batch.

---

## 4. The hard technical constraint that shaped everything

Discovered during the Pattern A discussion:

> **Prompt caching is prefix-based, not substring-based.**

Anthropic caches the longest shared prefix. OpenAI caches based on a hash of the initial prefix. If `concept_brief` is embedded *in the middle* of each prompt (as it currently is in lyrics-generator's prompt files), those occurrences won't cache across prompts — only the identical opening text caches.

This implied two routes to capture Pattern A savings:
1. **Convention in prompt files:** shared cacheable content at the top, task-specific at the bottom.
2. **Pflow takes over prompt assembly:** YAML declares what's "context" vs "task"; pflow assembles messages as `[system: cacheable context blocks][user: task]`.

Initial lean: Option 2 (YAML declaration). More powerful, decouples cacheability from prompt-authoring style.

---

## 5. First user pushback — "not just batch" and Option 2 has hidden costs

The user challenged Option 2 with a real concern:

> "using option 2, there is no way to easily write 'headers' or explanations before each context file. Its also less clear reading only the prompt what's included."

Legitimate points. Two problems with Option 2 in its initial form:
1. Loss of inline framing prose ("Given the concept above, note especially that the brief...").
2. Reading the prompt alone doesn't tell you what context is injected.

This pivot was important — it forced us to reconsider whether to auto-apply restructuring at all. Led to the user's critical principle in Section 6.

---

## 6. User principle — the load-bearing decision

After exploring options, the user stated the principle that shaped everything downstream:

> "I don't think we should auto apply caching if that means we have to change prompts that are declared in the workflow. But we can split it up if what's sent is identical."

Plus: "We shouldn't optimize automatically for workflow reruns, that should be opt in."

Derived rules:
1. **Pflow never changes the text the LLM sees** from what the workflow declared.
2. **Cache breakpoints are fine as long as rendered tokens are identical.** Splitting a message into content blocks to attach `cache_control` is not a content change.
3. **Rerun and long-duration optimization (extended TTL) is opt-in.**
4. **Explicit syntax over clever inference.** Matches pflow's existing philosophy.

These principles directly rejected: silent cross-call restructuring, auto-padding, default extended TTL, and autodetect on anything that changes message assembly.

---

## 7. Second pivot — code-block cache syntax (user's idea)

User suggested:

> "Could we write a cache 'block' as a markdown code block in ``` then we could have prose + ${dynamic value} alternating. Every block would have an attached text to it that is above until the dynamic value above."

This was the breakthrough. It threads the needle between Option 1 (prose stays with value) and Option 2 (explicit, pflow-native). The `cache` code block matches pflow's existing tagged-code-block pattern (`shell command`, `python code`, `prompt`, `yaml batch`, `yaml output_schema`).

Initial sketch:

````markdown
```cache
The concept we are building this song around:

${concept}

The material palette curated from source analyses:

${concept_brief}
```
````

Each chunk = prose + `${var}`. Prose travels verbatim into the system message alongside the value. The author writes what the LLM will see; pflow just adds cache_control metadata.

---

## 8. Third pivot — different nodes use different subsets (order invariant)

User noticed:

> "We are not always using a full 4-part 'song-context'. Sometimes it's just 1 or 2 or 3 of these, and maybe + something else or two things more that we want to cache in the same prompt."

Reading the subworkflows confirmed: every LLM node in song-creator uses its own subset. Review-narrative only needs `architecture`; review-stranger-summary needs NOTHING (deliberate isolation); write-lyrics needs all six.

User's key technical insight:

> "The IMPORTANT part is when LLM nodes use them they NEED to be imported in the same order as what's defined in the cache block."

This is the **order invariant**: prefix caching only works if calls that share context present items in identical order. Pflow must validate this strictly. Different subsets → independent cache entries; identical subsets (or prefix-of-subset) → shared cache.

Reflection: this was the right call but came with a subtle consequence — nodes using `[architecture]` alone don't cache-hit nodes using `[concept, architecture]` because the prefix doesn't start the same way. This led directly to the "prefix padding advisory" concept (Section 10).

---

## 9. Fourth pivot — naming convention

Three successive attempts at naming cache chunks:

### Attempt 1: `[name]` markers inside the cache block

I proposed:
````
```cache
[concept] ttl=1h
The concept we are building...

${concept}
```
````

Rationale: explicit, carries per-item flags like `ttl`. Rejected by user: complicates the block, user wanted simpler.

### Attempt 2: Template variable IS the key — `${concept}`

I proposed:
```yaml
- cache: [${concept}, ${concept_brief}, ${creative-direction.response}]
```

Rationale: no new vocabulary. Reuses pflow's existing `${...}` syntax.

User pushback:

> "Using the template variable might be confusing since it's the template variable + the text above it in the cache block?"

Valid critique. `${concept}` elsewhere in pflow means "substitute this value here." In a `cache:` reference, it would mean "include the cache *chunk* (prose + value) identified by this variable." Semantic overload.

### Attempt 3: Bare names with stripped template path

User asked:

> "Why couldn't you do `[chorus-chooser.winning_chorus]` directly?"

This was correct. I was overcomplicating. The rule: strip `${}` from the template, use the remainder as a bare string identifier. `${concept}` → `concept`, `${chorus-chooser.winning_chorus}` → `chorus-chooser.winning_chorus`. No `[name]` markers needed at all. Each cache chunk has exactly one `${var}`, and its name is derived.

Final syntax:
```yaml
- prompt_cache: [concept, concept_brief, creative-direction.response]
```

Reads as "reference these named cache chunks" — which is what we mean.

---

## 10. Prefix padding — concept emerged from order invariant

Consequence of the order invariant: nodes using `[architecture]` alone never cache-hit earlier calls.

User asked for clarification:

> "What do you mean padding?"

I explained: `review-narrative` logically only needs `architecture`. Declared as `[architecture]`, no prefix hit. If padded to `[concept, creative_direction, architecture]`, gets cache reads on `concept` and `creative_direction` at 0.1× (since an earlier node wrote them). The extra items cost 0.1× each; if total cost drops, padding wins.

**Design rule: padding is advisory, never auto-applied.** Pflow computes whether padding is net-positive and surfaces it as an optional recommendation in `pflow analyze-cache` output. The author decides.

This was the user's principle again: no silent workflow modifications.

---

## 11. Batch auto-caching — three-option decision

Three positions emerged for "within a batch, what happens to the stable prefix before `${item.X}`?":

- **A. Fully automatic and invisible** — pflow inserts `cache_control` silently. Bytes identical. No author action.
- **B. Automatic and visible** — same behavior, but `pflow analyze-cache` reports what was auto-detected. Opt-out per node via `- batch_cache: false`.
- **C. Explicit only** — batches get no cache unless author declares something.

User chose **B**. Rationale: free money (same bytes), but visibility maintains pflow's explicit philosophy. An agent reading analyze-cache sees "this batch has 2,400 tokens auto-cached before `${item.X}`" — nothing hidden.

---

## 12. `analyze-cache` command mockup exercise

Before locking in syntax, I proposed mocking up what `pflow analyze-cache` output would look like on the real lyrics-generator. User agreed — "Let's do 1."

Produced a detailed mockup covering:
- Summary with estimated cost delta + top actionable wins
- Per-call cache-ratio table
- Shared-context opportunities with suggested YAML
- Batch pre-warming suggestions
- Warnings with severity (⚠⚠ critical, ⚠ minor)

User reaction: "This would be awesome if we could provide this type of feedback. This looks great. But are you sure it's doable with the information we have?"

Honest answer (captured in response): most of it is doable statically; **dollar figures pre-run are estimates, not certainties** without a trace. Split the verification approach into three tiers:

- **Tier 1 — Static in-file** (easy, part of regular validation)
- **Tier 2 — Cross-workflow prediction** (medium, cross-file graph analysis)
- **Tier 3 — Trace-based verification** (ground truth from actual provider-reported cache data)

Decided to ship Tier 1 + Tier 3 in v1. Tier 2 is a planned follow-up (marked explicitly in the task spec).

---

## 13. Explicit vs autodetect — the deeper question

User pushed on whether caching could be purely automatic:

> "Should we require the workflow to define what should be cached, or should we try to autodetect based on what is possible to cache and would save money?"

My honest split:

- **Intra-call caching (per-prompt, batches, reruns):** fully automatic is clearly better. No reason to require declaration. Pflow has all the info at render time; failure to cache well produces a warning with a concrete fix.
- **Cross-call shared context (Pattern A):** requires lifting content out of prompt files into a structured system prefix. **This silently changes the message structure the LLM receives.** Even though bytes are identical, authors' assumptions about message structure might be violated.

Recommendation: **autodetect + warn for cross-call; autodetect + apply for intra-call.** Pflow detects opportunities, author opts in via `## Cache`. Explicit. Visible. The user agreed.

The mockup's "SHARED CONTEXT (cross-call reuse)" section embodies this: pflow detects, suggests the YAML, never auto-applies.

---

## 14. Sub-workflow handling — "it just works"

User asked:

> "Will any of the music subworkflows need to have their own top caching block declaring what's going to be cached in just that sub workflow? This would be required for subworkflows to be able to run in isolation and also utilize caching, right?"

Correct. Each workflow file (parent OR sub) declares its own `## Cache` scoped to its own inputs and step outputs. Cross-workflow cache hits happen incidentally at the byte level when rendered prefixes match. Pflow doesn't coordinate caching across boundaries — no special scoping logic needed.

Practical consequence documented: for parent→child cross-workflow cache hits to actually fire, parent and child should use identical prose labels for the same logical values. Divergent prose = different bytes = no hit. This is surfaced in the planned Tier 2 verification.

---

## 15. Breakpoint limits — "not a problem with simple strategy"

Anthropic allows max 4 `cache_control` markers per request. Initial concern: will this bite us?

Analysis: **in v1, no.** Simple strategy uses 1 marker per call (end of declared cache content) + up to 1 for batch auto-prefix = 2 per call max. Well within Anthropic's 4.

Deferred as follow-up: multi-breakpoint placement for fine-grained partial-prefix sharing. Would use up to 4 markers to cache intermediate subsets. Not v1 work.

---

## 16. TTL — block-level only

User questioned per-item TTL:

> "I'm not sure why we would need a different TTL for different cache entries?"

Agreed. Single TTL on the cache block covers all realistic cases. Per-item TTL would add complexity for a marginal optimization that's easier to chase by adjusting workflow structure. Default TTL is the provider default (typically 5 min); extended `- ttl: 1h` is opt-in (costs 2× on writes, only pays off with ≥3 reads).

Follow-up category: add per-item TTL later if real-world usage shows mixed hot/cold cache items.

---

## 17. Research methodology — Wave 1 & Wave 2

Before updating the task spec, user asked for deep verification:

> "Introspect deeply into your context window and make sure we haven't missed anything, or if there's any additional ambiguity to discuss. First gather information about what you don't know you don't know, then to gather information about the things you know you don't know."

**Wave 1 (5 parallel searches):** unknown unknowns
- A. Compilation pipeline end-to-end
- B. LLM node + Claude node internals
- C. Validation + diagnostic system
- D. Sub-workflow + batch execution
- E. Test infrastructure + `--dry-run` implementation

**Wave 2 (4 parallel searches):** specific assumptions
- A. `llm-anthropic==0.25` cache_control surface (BLOCKING)
- B. Existing `cache: bool` collision scope
- C. Config hash + cache invalidation semantics
- D. Trace event schema for `--from-trace`

This two-wave pattern worked well. Wave 1 surprises fed Wave 2 verifications.

---

## 18. Research findings that changed the design

### Finding 1 — `cache: bool` collision (Wave 2B)

**Severity: breaking if ignored.** The existing `cache: bool` field is reserved for per-node memoization opt-out — different cache layer (pflow's local cache). In use across:
- 7 example workflows
- 14 test files
- 5 CLAUDE.md files
- Agent guide (`guide/core.md`)
- 3 user doc pages
- Validator hint text

Options evaluated:
- **A. Coexist with rename** — new field `prompt_cache:`. Zero breakage.
- **B. Overload `cache:`** — bool OR list. Confusing for agents.
- **C. Replace** — fully breaking, 15+ file changes.

**Chose A.** `prompt_cache:` matches Anthropic/OpenAI/Gemini terminology, keeps the two cache layers visually distinct, zero backwards-compat impact. Wave 2B agent independently recommended same.

Alternatives considered for new name:
- `cache_context: [...]` — vague
- `uses_cache: [...]` — grammatically odd
- `cache_breakpoints: [...]` — Anthropic-specific jargon
- `prompt_cache: [...]` — **selected**, clearest

### Finding 2 — `llm-anthropic==0.25` is insufficient (Wave 2A)

**Severity: confirms LiteLLM migration is required, not optional.**

Wave 2A verified the plugin's actual cache surface by runtime introspection and source code read:
- Exposes `cache: bool` option that inserts `cache_control` on:
  - Last attachment block (if attachments exist)
  - Last content block of the last prior user message (multi-turn)
- Does NOT cache:
  - System prompts
  - First-turn user content (single-shot)
  - Arbitrary breakpoints
- `llm.models.Options` is `extra="forbid"` — no `cache_control=`, no `extra_body=`, no `messages=` passthrough
- No `options` kwarg on `.prompt()` for raw field injection

For Task 158's core use case (caching system prompts and large context objects across calls), the plugin does nothing useful. LiteLLM migration is confirmed required.

Rejected alternatives:
- Keep `llm` + monkey-patch `build_kwargs` — brittle across upgrades, even with the 0.25 pin
- Subclass the plugin — same brittleness

### Finding 3 — Memo cache hash correctness risk (Wave 2C)

**Severity: silent correctness bug if ignored.**

The memo-cache hash (`compute_node_config`) determines which cached output is served. If `prompt_cache` prepends content to the system message at runtime but is NOT in the hash, existing cache entries hit for upgraded workflows and serve outputs produced WITHOUT the prepended content.

Fix: thread rendered `prompt_cache` content into `compute_node_config` **conditionally** — only when `prompt_cache` is non-empty. Nodes not opting in retain their existing hash; opted-in nodes get a distinct hash and fresh entries.

Precedent: `batch_config` is added conditionally (Task 96). `cache_enabled` (the bool) is NOT in the hash — it gates behavior without changing output identity. `prompt_cache` follows the `batch_config` pattern.

Regression test required: no-prompt_cache workflows produce identical hashes pre- and post-task.

### Finding 4 — Prompt is flat by the time LLMNode sees it (Wave 1B/D)

**Severity: integration-point clarification.**

`merged_params["prompt"]` is fully resolved before `LLMNode.prep()`. No intermediate "template prefix vs dynamic suffix" structure. The `llm` library's `model.prompt(prompt_text, **kwargs)` takes positional text.

Integration point for cache rendering: **inside `LLMNode._call_llm`** (`nodes/llm/llm.py:271-321`) after kwargs build, before API call. Stays within ThreadPoolExecutor timeout budget, inside retry loop.

For auto batch-prefix detection: read from the **unresolved** template at `config.template_config.template_params["prompt"]`. The position of `${item.X}` is only identifiable pre-resolution.

### Finding 5 — ClaudeCodeNode out of scope (Wave 1B)

Uses `claude_agent_sdk` directly. SDK already handles Anthropic prompt caching transparently; cache tokens already populate `llm_usage` via `claude_code.py:865-887`.

Task 158 explicitly scopes to LLMNode only. Saved meaningful scope.

### Finding 6 — Validation is shared via `data_flow.py` (Wave 1A + resolution)

Initial concern: pflow has two validation entry points (`WorkflowValidator.validate()` and `runtime/compilation/compile_validation.py::_prepare_compilation()`). Would cache validation need to be duplicated?

Resolution: no. Both entry points already call the shared `core/workflow/data_flow.py::validate_data_flow()`. Cache reference validation goes there; schema-level rules go into `FLOW_IR_SCHEMA` (also shared). Single implementation covers all entry points.

### Finding 7 — Trace format 2.0.0 has cache tokens but not cache keys (Wave 2D)

`event["llm_call"]["cache_creation_input_tokens"]` and `["cache_read_input_tokens"]` already populate. `cached: True` marker exists for memo hits. What's missing:
- `cache_key` per event — for exact SQLite correlation
- `cache_source` on cache-hit events — distinguishes memo vs in-process
- `cache_age_sec` on cache-hit events — for TTL analysis
- `workflow_path` at top level — for cross-trace correlation

User decision: **bump trace format to 2.1.0.** Existing `format_version.startswith("2.")` gate (`trace_report.py:400`) stays forward-compatible; 2.0.0 consumers continue to work on 2.1.0 files, ignoring the new fields.

### Finding 8 — Mock truncates prompts (Wave 1E)

`tests/shared/llm_mock.py:30` truncates `call_history` prompts to 500 chars. Cache-structure testing (verifying message block assembly) needs full prompts. Resolution: add untruncated-prompt opt-in mode; don't break existing assertions that depend on the truncation.

### Finding 9 — MCP parity required (Wave 1E)

Per Task 152 invariant ("every shared formatter has two call sites"). Shipping `pflow analyze-cache` CLI without MCP tool registration would be a parity gap.

Resolution: add `analyze_cache` service method + MCP tool registration mirroring the `plan_workflow` pattern.

---

## 19. Post-research design updates

After both waves, three decisions needed from the user:

1. Field name: `prompt_cache:` (user agreed)
2. Trace format: 2.0.0 or bump to 2.1.0? User said **bump to 2.1.0**
3. Validation location: ship in both entry points or centralize? User said "seems like implementation detail." Resolved: shared `data_flow.py` — one implementation, both entry points pick it up automatically.

All other recommendations (LiteLLM required, memo-cache hash correctness, ClaudeCodeNode out-of-scope, mock dual-mode, MCP parity, `--dry-run` nudge via `Severity.INFO` Diagnostic) user accepted.

---

## 20. Alternatives considered and rejected

### Library choice
- ❌ **Keep `llm` + monkey-patch `build_kwargs`** — brittle, pin-dependent, only partial coverage (no system prompt caching)
- ❌ **Direct Anthropic SDK only** — leaves Gemini caching unsolved, user needs Gemini in v1
- ❌ **OpenRouter / other proxy** — adds network hop, policy concerns, overkill
- ❌ **Instructor or aisuite** — too young or orthogonal
- ✅ **LiteLLM** — unified syntax, covers all three providers, Ollama first-class for non-caching

### Syntax for cache declaration
- ❌ **Cache markers in prompt files** (`<!-- cache-breakpoint -->`) — fragile, pfile-local, hard to audit
- ❌ **YAML declaration only** (pre-code-block idea) — loses inline framing prose
- ❌ **Automatic message restructuring** — violates "no silent prompt changes" principle
- ❌ **`[name]` markers inside cache block** — unnecessary; template path suffices
- ❌ **`${var}` references in `cache:` list** — semantic overload (substitution vs identifier)
- ❌ **Auto-name from last segment** (`.response` collision) — ambiguous
- ✅ **`## Cache` section with `` ```cache `` code block; bare stripped-template-path names in `prompt_cache:` list**

### Field naming
- ❌ **`cache: bool | list`** — overload, agent-confusing
- ❌ **Replace `cache:` meaning** — 15+ file migrations for zero UX gain
- ❌ **`cache_context: [...]`** — vague, doesn't distinguish from memo layer
- ❌ **`uses_cache: [...]`** — grammatically odd
- ✅ **`prompt_cache: [...]`** — clearest, matches provider terminology

### Cross-call caching application
- ❌ **Silent automatic lifting** — changes message structure; agents can't predict
- ❌ **Fully manual** — misses opportunities agents wouldn't think of
- ✅ **Autodetect + suggest; explicit opt-in** — surfaces opportunities, applies only what author declares

### Batch auto-prefix caching
- ❌ **Fully automatic + invisible** — loses agent visibility
- ❌ **Fully explicit** — unnecessary friction when bytes are identical
- ✅ **Automatic + visible in analyze-cache + opt-outable** (Option B)

### TTL
- ❌ **Default to 1h** — costs 2× write, surprising agents
- ❌ **Per-item TTL** — complexity for marginal gain
- ✅ **Block-level, provider-default unless opted into `1h`**

### Prefix padding
- ❌ **Auto-apply when net-positive** — violates no-silent-workflow-modification principle
- ❌ **Ignore entirely** — leaves money on the table
- ✅ **Advisory only in `analyze-cache` output**

### Pre-warming for batches
- ❌ **Default on** — adds surprise latency
- ❌ **Never** — leaves money on the table for large N
- ✅ **Opt-in via `- prewarm: true`**

### Validation placement
- ❌ **Duplicate in both entry points** — drift risk
- ❌ **Factor out into a new shared module just for cache** — over-engineering
- ✅ **Add to existing shared `core/workflow/data_flow.py::validate_data_flow()`**

### Trace format
- ❌ **Stay at 2.0.0 and recompute cache keys** — brittle, requires exact sanitization matching
- ❌ **Major bump to 3.0.0** — breaks existing consumers
- ✅ **Minor bump to 2.1.0** — forward-compatible via existing `startswith("2.")` gate

---

## 21. Open questions the research didn't fully resolve

These are explicitly deferred as implementation-time decisions or follow-up tasks:

### Deferred to implementation
- **How to handle `prompt_cache` references to outputs from branches that didn't execute.** Task spec says "validation-time warning; runtime cache rendering skips the missing item (or errors — decision point during impl)."
- **Gemini TTL translation via LiteLLM.** LiteLLM's Gemini path supports cache_control but its TTL mapping to `cachedContents` needs verification against a real call.
- **Exact shape of `llm_reasoning_map.py`.** Task 158 requires replacing `model.Options.model_fields` introspection with a hardcoded map. The map's internal structure (dict-of-dicts, enum, class hierarchy) is open.
- **OpenAI `prompt_cache_key` generation.** Task spec says "optionally emit a `prompt_cache_key` computed from a hash of the rendered cache content." Hash function choice (md5, sha1, sha256) is open.

### Planned follow-up tasks
- **Tier 2 verification: cross-workflow cache-hit prediction.** Compare prose labels across workflow files when a parent invokes a sub-workflow; warn on divergence.
- **Multi-breakpoint per-call placement.** Up to 4 markers on Anthropic for finer-grained partial-prefix sharing.
- **Automatic cache-order optimization.** `pflow analyze-cache --suggest-order` computes an ordering that maximizes cross-call prefix sharing weighted by item sizes.
- **Per-item TTL.** If real usage shows mixed hot/cold items.
- **Pre-warming as default for batch fan-outs above N items.**
- **Automatic padding application.** If advisories are consistently accepted.
- **Claude Code node caching controls.** If user controls are wanted.
- **`pflow cache clear` CLI command.** No user-facing CLI exists today; programmatic API only.
- **MemoizationCache schema version / migration.** Deferred; 24h TTL is the natural flush mechanism.

---

## 22. Key principles that emerged and crystallized

These principles, surfaced during the discussion, should guide any implementation decision that arises during Phase A–G work:

1. **Pflow never changes the text the LLM sees from what the workflow declared.** Splitting bytes into blocks with cache_control metadata is permitted because the tokens are identical.
2. **Explicit syntax over clever inference.** Matches pflow's existing philosophy — workflow files are the honest source of truth.
3. **No silent workflow modifications.** Advisory recommendations, yes; auto-rewrite, no.
4. **Rerun and long-duration optimization is opt-in.** Default behavior never assumes reruns within TTL.
5. **The memo cache hash MUST match runtime behavior.** Any field that affects the rendered message MUST be in the hash (conditionally, to preserve existing entries).
6. **Validation is shared across entry points via existing modules.** No duplicate validator logic.
7. **Agent-facing output must have stable warning IDs, concrete fix actions, and structured JSON.**
8. **Trace format is forward-compatible by convention.** Minor version bumps, preserve the `startswith("2.")` gate.

---

## 23. Session conduct notes

Aspects of this session worth remembering for similar future design work:

### What worked
- **Reading the real workflow early.** Made savings estimates concrete instead of hand-wavy.
- **User's principled pushback.** Every time the user pushed back ("not just batch," "confusing naming," "why different TTL?"), it led to a better design. Slow iteration beat fast first-draft.
- **Two-wave research before spec update.** Wave 1 surfaced unknown unknowns (cache field collision, dual validation entry points) that would have bitten implementation. Wave 2 verified blocking assumptions (llm-anthropic surface).
- **Parallel subagent searches.** 5 Wave 1 + 4 Wave 2 agents in parallel compressed hours of exploration into minutes.
- **Mockup before syntax lock.** The `pflow analyze-cache` output mockup revealed doability questions (dollar estimates pre-run) before we committed to an interface.

### What to avoid next time
- **Writing generic YAML syntax before checking pflow's actual format.** Wasted a round of discussion on YAML when pflow is markdown-first with tagged code blocks. Fixed by running `pflow guide`.
- **Over-engineering field names.** `[name]` markers were a classic overthink; bare stripped paths work fine. User correctly challenged.
- **Initial "Option B" (direct SDKs) framing.** Reversed after Wave 2A confirmed LiteLLM is required. Could have been avoided by probing llm-anthropic surface earlier.

---

## 24. Timeline / phase summary

| Phase | Duration (turns) | Outcome |
|---|---|---|
| Origin framing + library options | ~2 | Initial lean: direct SDK (later reversed) |
| Workflow read + Pattern A identification | ~1 | Savings estimate grounded in reality |
| Caching model evolution | ~3 | Two-mechanism split (intra-call auto + cross-call explicit) |
| Cache syntax iteration | ~3 | Code-block ``` cache `` with prose + `${var}` |
| Order invariant + subsetting | ~1 | `prompt_cache:` list, strict order, one implementation |
| Naming pivots | ~2 | Bare stripped template paths, no markers |
| User principle clarification | ~1 | "No silent prompt changes" — locked |
| analyze-cache mockup | ~1 | Tier 1 + Tier 3 for v1, Tier 2 follow-up |
| Initial task spec draft | ~1 | First version, ~453 lines |
| Deep research (Wave 1 + Wave 2) | ~2 | Nine findings, three changed the design |
| Spec revision | ~1 | Final version, 636 lines |

---

## Next step

Implementation starts with **Phase A: LiteLLM migration, no caching yet.** This is the largest phase (~40% of work) and is prerequisite for all others. Safe-revert if problems surface. See `../task-158.md` → "Implementation Phasing" for the full phase map.

When Phase A begins, append a dated entry below capturing:
- Branch name
- Initial scope probe (what files touched first)
- Any surprises not predicted by the research
- Test pass/fail state at merge

---

## 25. Session 2026-04-24 — pre-implementation refinement

Resumed in worktree `pflow-feat-prompt-caching-lite-llm` on branch `feat/prompt-caching-lite-llm`. Re-read the spec, progress log, and braindump in full. No implementation yet. Goal of this session: surface remaining ambiguity in the design, decide on resolutions, refine the spec, and commit to a phased planning approach.

### Ambiguities surfaced and resolved

The previous spec was internally consistent but had unaddressed gaps. Each was raised, discussed, and decided this session:

1. **`--no-cache` flag scope.** Decision: disables pflow's memo layer only; LLM provider prompt caching is untouched. The two layers are conceptually independent. Rationale: prompt caching is pure cost reduction with no behavioral change; there is no debug scenario where disabling it helps. Documented in spec under new "Cache Layer Independence" subsection.

2. **Gemini explicit-cache cost regression risk.** Surfaced in the braindump: Gemini explicit caching can cost MORE than no caching for small/rarely-reused caches because of storage fees. Decision: with default 5-min TTL, the storage cost window is small enough that the risk is negligible. The 1h-TTL opt-in is what could create the economic trap, and that's already opt-in. Defer Gemini break-even warning to v1b follow-up; do not block v1.

3. **Tier 2 cross-workflow verification.** Decision: re-evaluate complexity during Phase B–G plan writing. If the mechanical part (parse parent + child cache blocks, compare prose-before-each-var) is cheap and the data-flow tracing for "same logical value across boundary" is also cheap, include in v1; else defer.

4. **Auto-batch-prefix caching default.** **Significant design shift.** The previous spec had auto-batch-prefix ON by default with `batch_cache: false` opt-out. New realization: without pre-warming, all N parallel calls write the cache simultaneously — no read benefit, just overhead. Decision:
   - Auto-batch-prefix is GATED on `prewarm: true`. Without prewarm, no marker is inserted.
   - `batch_cache: false` field removed (subsumed by `prewarm` choice).
   - For large batches (v1 threshold: size > 10 AND detected prefix > 2k tokens), pflow emits a hard validation error demanding an explicit prewarm choice — silent skipping at this scale would represent a meaningful cost regression.
   - N=1 batches always skip auto-batch-prefix (no fan-out, no opportunity).
   - Declared `## Cache` references whose prefix was written by upstream non-batch nodes still apply at read cost — independent of prewarm.
   - `prewarm` semantics: serialize the first call, wait for cache write, then fan out N-1 in parallel as cache reads.

5. **Dry-run cache rendering policy.** Decision: planner uses `MemoizationCache.get_latest_for_node()` — same source Task 156's dry-run uses for cost estimates. For chunks without prior cached data, record "cache content unavailable — estimates low-confidence". Not an error.

6. **Unused cache chunk handling.** Decision: validation warning (not error) when `## Cache` declares a chunk no node references. Surfaces dead code; suggests removal or referencing.

7. **Algorithm depth for analyze-cache suggestions.** Decision for v1: Level 2 — detect shared context, suggest pastable `## Cache` block + per-node `prompt_cache:` assignments using a most-shared-first ordering heuristic. Author manually applies. Level 3 (explicit `cache apply` command writing changes to disk after preview) and full prefix-tree optimization with cross-workflow alignment are deferred to v1b. v1b scope assessed during Phase B–G plan writing once code is concrete.

8. **Cache block reference rule generalization.** Previous spec rejected `${item.X}` specifically. New phrasing: "references that vary across calls referencing the same chunk are rejected". Aggregate batch outputs (`${batch-node.some_field}`) and indexed accesses that resolve to stable values are valid.

### Spec revisions made this session

- Design Decision 9 rewritten to reflect prewarm-gating.
- Design Decision 18 rewritten with prewarm semantics and the large-batch hard-error rule.
- Removed "5–10 engineer-day" estimate from Design Decision 1 (estimates with AI implementation are too unreliable to anchor on).
- Auto Batch-Prefix Caching requirements section rewritten end-to-end.
- Per-Node fields section gained `prewarm: bool`; lost `batch_cache: false`.
- Cache Block Parsing section: generalized batch-reference rule.
- New Cache Layer Independence section covering `--no-cache` scope.
- `--dry-run` section gained the cache-rendering policy.
- Validation Location section gained the unused-chunk warning.
- analyze-cache Requirements section gained explicit v1a (Level 2) scope and v1b deferral note.
- Implementation Phasing section: split planning itself into "plan Phase 0+A first, then plan B–G after Phase A lands". Added Phase 0 spike scope detail (extended thinking + cache, structured output + cache, transitive dep audit, pricing investigation).
- Files to Modify section trimmed heavily — high-level pointers only; detailed file-level work moved to forthcoming implementation plan.
- Non-Obvious Integration Points section: kept the facts, removed specific file:line numbers (those belong in plan).
- Out of Scope additions: full prefix-tree optimization (v1b); refined pre-warming default note.
- Test Infrastructure additions: structured output + cache test, extended thinking + cache test, prewarm-gating tests, unused-chunk warning test.

### Phased planning commitment

Decided we cannot write a credible plan for Phases B–G without first verifying LiteLLM works for pflow's use case. Sequence:

1. Spec revision (this session — done).
2. Write `implementation/plan-phase-0-and-A.md`. Covers the spike (Phase 0) and the LiteLLM migration (Phase A). Not B–G.
3. Plan review.
4. Execute Phase 0 spike.
5. Execute Phase A migration. All tests green before merge (test fixes are part of the phase, not deferred). `test_plan_drift.py` is sacred.
6. After Phase A lands, write `implementation/plan-phase-B-through-G.md` informed by concrete LiteLLM behavior.
7. Plan review.
8. Execute B–G in order.

### Decisions deferred (intentional)

- Phase 0 rollback criterion (what to do if LiteLLM has a dealbreaker — direct SDKs? Stay on `llm`?). Not decided this session because the spike is cheap; we'll cross that bridge if the spike fails.
- Exact thresholds for the large-batch prewarm-required error. v1 starts at "size > 10 AND prefix > 2k tokens"; can simplify if a single dimension proves sufficient.

### Open assumptions still requiring verification

(Most of these flow into Phase 0 spike scope.)

- LiteLLM passes `cache_control` cleanly to all three providers.
- LiteLLM `completion_cost()` is accurate enough to replace `llm_pricing.py` (best case) or merit primary-with-fallback (medium case). Outcome chooses spec direction for pricing module fate.
- Gemini double-counting fix (LiteLLM PR #15226, 2025-10-07) is present in the version we pin.
- Extended thinking parameters compose with `cache_control` and with `response_format`.
- `pflow publish` (Task 119) preserves `## Cache` sections in published skills (verify in Phase F or earlier).

### Next step

Write `implementation/plan-phase-0-and-A.md`. The spec is now in a state to inform that plan without needing further revisions for the LiteLLM migration scope. (Phases B–G may surface more spec refinement once we see concrete code.)
