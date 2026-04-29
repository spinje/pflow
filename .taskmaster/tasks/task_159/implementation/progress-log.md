# Task 159 — Design Journey & Progress Log

**Purpose of this document:** Capture the full thinking that shaped the prompt-caching feature — reasoning, alternatives considered, pivots, user principles surfaced, and research findings. The task spec (`../task-159.md`) documents the final design. This log documents how we got there and why alternatives were rejected, so a future implementer understands the "why" behind each choice.

**Sessions:** 2026-04-22 → 2026-04-24.

**Originally Task 158.** The discussion in §1–§25 below was about a single task (then numbered 158) that intended to ship both the LiteLLM migration AND the caching feature. After implementation revealed the migration deserved its own scope, the task split: the migration became Task 158 (its implementation log lives at `../../task_158/implementation/progress-log.md`, sections §26–§38), and the caching feature kept the design narrative here (now Task 159). Section numbering in this log preserves the original chronology — §1–§24 is the design discussion before any implementation; §25 is the pre-implementation refinement session that triggered the split.

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

## What happened next

§25 below documents the session where the user resumed and we refined the spec + decided to split the work into a planned phased implementation (Phase 0 spike → Phase A migration → Phase B–G caching feature). That session triggered the eventual task split: Phase 0 + Phase A became Task 158 (migration), and Phase B–G remains the work for Task 159 (this task).

Implementation history for Phase 0 + Phase A lives in **`../../task_158/implementation/progress-log.md`** (sections §26–§38). The caching feature itself (Phase B–G) has not started — when it does, append entries here continuing from §25.

---

## 25. Session 2026-04-24 — Final caching-design refinement

The user resumed in worktree `pflow-feat-prompt-caching-lite-llm` to refine the design before implementation. This session surfaced 8 remaining caching-design ambiguities, resolved them, and produced spec revisions that locked in the caching-feature contract. (A parallel outcome from the same session — the phased-implementation decision that ultimately split the original Task 158 into a migration-first sequence — is documented in Task 158's progress log §25, since it shaped the migration sequencing and triggered the task split.)

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

### Spec revisions made this session (caching-flavored)

- Design Decision 9 rewritten to reflect prewarm-gating.
- Design Decision 18 rewritten with prewarm semantics and the large-batch hard-error rule.
- Auto Batch-Prefix Caching requirements section rewritten end-to-end.
- Per-Node fields section gained `prewarm: bool`; lost `batch_cache: false`.
- Cache Block Parsing section: generalized batch-reference rule.
- New Cache Layer Independence section covering `--no-cache` scope.
- `--dry-run` section gained the cache-rendering policy.
- Validation Location section gained the unused-chunk warning.
- analyze-cache Requirements section gained explicit v1a (Level 2) scope and v1b deferral note.
- Out of Scope additions: full prefix-tree optimization (v1b); refined pre-warming default note.
- Test Infrastructure additions: structured output + cache test, extended thinking + cache test, prewarm-gating tests, unused-chunk warning test.

(Migration-related spec revisions from the same session — DD1 estimate removal, Files-to-Modify trim, Non-Obvious-Integration-Points cleanup, Implementation-Phasing split-planning addition — are documented in Task 158's progress log §25.)

### Decisions deferred (intentional)

- Exact thresholds for the large-batch prewarm-required validation error. v1 starts at "size > 10 AND prefix > 2k tokens"; can simplify if a single dimension proves sufficient.

### Open assumption still requiring verification (Phase B–G scope)

- `pflow publish` (Task 119) preserves `## Cache` sections in published skills. Verify in Phase F or earlier.

### Next step

Deside on the final output format of the analyze-cache command then write the implementation plan for the caching feature. Prerequisites are now in place: the design braindump and spec are current, and the LiteLLM substrate (Task 158's adapter, typed exceptions, diagnostic pipeline, tracing seam) has shipped. The plan should be informed by concrete LiteLLM behavior observed during Task 158's implementation — see Task 158's progress log §27 for the Phase 0 spike findings (`cache_control` composition with thinking + structured output, pricing accuracy, etc.) and §38 for end-to-end verification results.

---

## 26. Session 2026-04-27 — Output format synthesis, verification pass, three-tier architecture

This session picked up where §25 left off: design was complete; the analyze-cache output format was the unresolved blocker before plan-writing. The session went deeper than expected — three rounds of user pushback surfaced architectural issues that reshaped DDs and produced the biggest single contribution to the spec since §25 (additions of DD#26-36 and a substantially restructured analyze-cache requirements section).

The spec captures *what was decided*. This entry captures *why* — including the dead ends, the user pushback that caught my drift, and the verification surprises that adjusted plan-writing scope.

### Code investigation, Round 1 — five lookups before mockup synthesis

Goal: don't invent shapes the implementation can't deliver. Five parallel `pflow-codebase-searcher` subagents on:

1. **`Diagnostic` class shape.** Surprise: no stable-ID convention exists. The output mockups (alt-1 and alt-2) had been assuming IDs as a top-level field; the code doesn't have it. This forced a Phase B prerequisite decision (extend `Diagnostic`).
2. **`MemoizationCache` return shape.** Confirmed: stores full output blob (zlib-compressed JSON). Prior `llm_usage.input_tokens` reachable but no metadata-only API. No new SQLite schema needed for v1.
3. **Token estimator.** Surprise: pflow has *zero* token-counting infrastructure. No `tiktoken`, no `len // 4` fallback. Forced choice between (a) adding tiktoken dep, (b) using `litellm.token_counter` (already transitively installed via LiteLLM), (c) inventing a char heuristic. Picked (b) — lowest friction, model-aware, offline.
4. **Sub-workflow graph walk.** Confirmed: `resolve_sub_workflow()` exists as standalone primitive. No existing function returns `parent → list[(child_path, input_mapping)]`; new ~50 LOC walker required, mirroring mermaid renderer's traversal pattern. Tier 2 is feasible.
5. **Per-model capabilities table.** Surprise: doesn't exist. Task 158 created `llm_providers.py` (4 fields, no per-model data). Task 159 must introduce `llm_capabilities.py` from scratch as Phase B work. LiteLLM's `model_cost` dict has *some* of the data but coverage and field names are unverified — wrapping it deferred to v1.x.

These findings shaped DD#27 (Diagnostic id field), DD#31 (token estimation tier), DD#32 (capabilities table as new module).

### Output format synthesis (v3 → folded into spec)

Read existing alt-1 and alt-2 mockups under `research/`.

**alt-1 strengths:** dollar amounts at the top, score-choruses-style mechanical fix detail (file + line + exact text to move + projected post-fix ratio), batch pre-warming as dedicated section with latency/savings tradeoff, sub-workflow per-invocation scoping notes.

**alt-2 strengths:** confidence indicator at top, stable warning IDs introduced as concept (with `cache.<category>` namespace), severity vocabulary aligned with `Diagnostic`, action-ordered "Top opportunities" section, full JSON schema mockup.

**Decision:** alt-2 as skeleton + alt-1's specific details (mechanical-precision warning copy, pre-warming detail, per-invocation scoping note). Add what neither had: Tier 2 cross-workflow alignment section, `--from-trace` mode mockup, already-optimal mode, output for steady-state (workflow already has `## Cache` declared).

Wrote v3 doc as research artifact, then folded contract-level content into the spec when the user clarified that future agents should read only the spec. v3 marked deprecated with header pointing to `task-159.md`.

### Three principle clarifications (user pushback that reshaped DDs)

These are the most important entries in this session. Each one caught me drifting toward overengineering or sloppy thinking.

#### Clarification 1 — `FixAction` overlap with `suggestions` (DD#28)

I had proposed extending `Diagnostic` with a typed `fix: FixAction` substructure carrying `action: str`, `description: str`, `applicability: Literal[...]`, `args: dict`. User pushback:

> "doesn't 'FixAction' seem to have overlap with the existing 'suggestion'? Also do we need this complex structure, lets take a step back and examine what we need and why."

Reconsidered honestly:
- `FixAction.description` IS `suggestions[0]`. Same content, same purpose, just renamed.
- Net delta over `suggestions` is `action: str` (typed enum) + `applicability` + `args`.
- Each needs its own justification.

**The mental-model error I'd made:** lumped "top 10% diagnostic systems" into one bucket. Actually two distinct categories:
- **Auto-applying tools** (rustc, ruff, eslint, prettier): typed fixes are first-class because `--fix` is a primary product. Applicability gates "is this safe to auto-apply." Args carry edit primitives. Need structured fixes because they execute them.
- **Analyzer tools** (mypy, pylint, shellcheck): prose suggestions plus stable IDs. No typed fix machinery, because nothing programmatically applies them.

pflow analyze-cache in v1 is the second category. `pflow cache apply` is deferred to v1b. mypy is the right analog, not rustc.

**Resolution:** drop `FixAction`. Existing `suggestions: list[str]` for prose, existing `context: dict` for structured raw data. Cost: ~10 LOC instead of ~40 LOC. No new dataclass, no new enum.

**Insight to carry forward:** when proposing a structured type, ask "do we have a programmatic consumer?" If no, prose + context dict is enough. Prematurely typed structures cost reader attention without buying anything.

#### Clarification 2 — Trace data conflation (DD#34, four-source labels)

I had labeled per-call confidence as `trace` / `estimator` / `heuristic`, where `trace` meant *either* MemoizationCache prior `llm_usage` OR explicit trace JSON file. User pushback:

> "cant this be loaded automatically if available? when would you not want to use trace when it exists? also when you say trace do you mean the db or where does the data live?"

That last sentence caught a real spec sloppiness. Two distinct data sources I had conflated under one label:

1. **MemoizationCache** at `~/.pflow/cache.db` (SQLite). Stores prior node outputs including `llm_usage.input_tokens`. Always queryable when workflow has been run before.
2. **Trace JSON files** at `~/.pflow/debug/workflow-trace-*.json`. Format 2.1.0 carries per-event cache metadata (`cache_creation_input_tokens`, `cache_age_sec`, `cache_key`). Required for `--from-trace` discrepancy analysis.

These have different fidelities and different code paths. Conflating them masked the auto-load opportunity.

**Resolution:**
- 4-level per-call source labels: `trace` / `memo` / `estimator` / `heuristic`.
- 3-level aggregate: `high_from_trace` / `medium_from_memo` / `low_no_data`.
- Auto-load most recent matching trace from `~/.pflow/debug/` when present. `--from-trace <path>` is explicit override; `--no-trace` opts out.

**Insight to carry forward:** distinguish data sources by *storage location AND fidelity*, not by a generic label. Words like "trace" overload across SQLite + JSON + in-memory state without semantic distinction; pick names that point at the actual artifact.

#### Clarification 3 — Savings ratio as the right threshold (DD#33)

I had proposed absolute dollar floors for prewarm thresholds (`size > 10 AND prefix > 2k tokens`). User pushed:

> "we could probably use % of cost instead, so for example if the costsaving would be more than 20% this would trigger or something"

Initial reaction: % alone won't filter, because for prewarm specifically the savings ratio is always high (Anthropic's 1.25× write vs 0.1× read math gives >40% for any batch ≥2). Replied with "absolute floor is needed."

User pushed harder:

> "shouldnt the improvements be procentual based on cost with and without caching? something going from 0.002 -> 0.001 is a BIG procentual change in cost, and it can compound based on the batchsize and how many times the user intents to run it"

This made me re-examine the math. I had been assuming P >> D (prefix dominates the prompt). When D is significant:

```
savings_ratio = (N-1) × 1.15 × P / (N × (1.25P + D))
```

When P >> D: ratio ≈ (N-1) × 1.15 / (N × 1.25) → high.
When P << D: ratio is small (P / (P+D) dominates). ← this is the case % threshold filters.

So my "always >40%" claim was wrong. Ratio is high *only* when prefix dominates the prompt. When dynamic content dominates, ratio drops below 5%, and a % threshold correctly filters. The user's instinct that "% feels right" was capturing the structural property — what fraction of the batch is actually cacheable — that absolute thresholds miss.

**Resolution:** drop both arbitrary thresholds (`size > 10`, `prefix > 2k`). Single rule: `ratio < 5%` silent skip, `ratio ≥ 5%` emits `cache.batch-prewarm-recommended`. No absolute dollar floor — small absolute savings compound across reruns; pflow can't predict run frequency, so user reads `savings_pct` and `savings_usd` and decides themselves.

**Insight to carry forward:** when a user's instinct points at a clean rule, work the math first instead of arguing from assumed cases. My original "absolute floor" argument was missing the structural property they were pointing at; the math made it visible.

### The biggest architectural reframe — three-tier validation/analysis (DD#36)

After the % threshold landed, I drafted spec edits making `cache.batch-prewarm-recommended` an `error` severity that blocks `pflow run` for batches above 20% savings. User pushback was the most consequential of the session:

> "having cache.batch-prewarm-required error and block pflow run wouldnt that mean we have to load historical data before every run? im not sure this is good... stop and lets dsicuss"

Confirmed: yes. Computing savings ratio at validation time requires:
- Token counts (via `litellm.token_counter` — loads tokenizer files, latency)
- Historical run data (via `MemoizationCache.get_latest_for_node()`)
- Cross-batch-item resolution

That's expensive analysis on every `pflow run`. Validation should be **fast, deterministic, no I/O beyond reading the workflow file**. Forcing tokenizer loading and historical state into the runtime path is wrong.

User then proposed the cleaner architectural distinction:

> "--dry-run could be allowed to be a little slower and read state right?"

Yes — that's the right line to draw. `--dry-run` is the user opting into analysis. Three tiers:

1. **`pflow run` validation** — structural cache checks only (parser, references, order). Fast, deterministic. Blocks on structural errors.
2. **`pflow run --dry-run`** — opt-in, can be slow. Full analytical pass: token counting, historical state, savings ratios, Tier 2 walking. Emits one-line nudge with real numbers. Doesn't block (no execution to gate).
3. **`pflow analyze-cache`** — dedicated command. Same analysis, full sectioned output, `--from-trace` discrepancy mode.

ALL cache analytical findings become advisory. No blocking semantics on `cache.batch-prewarm-*`, `cache.dynamic-before-static`, `cache.padding-advisory`, etc. Only structural errors (`cache.order-mismatch`, reference-resolution failures) block.

This collapsed the two prewarm IDs into one (`cache.batch-prewarm-recommended` with warning severity), simplified the catalog from 10 to 9 entries, and dropped the "forcing function via blocking validation" framing entirely.

**Insight to carry forward:** "forcing function via blocking validation" was a misframe. Standard tooling pattern (mypy, ruff, pylint) is opt-in analysis with prose output — agents who care run the analyzer; agents who skip it run unhindered. The cost of expensive validation paths in the runtime is too high. Keep `pflow run` fast and deterministic.

### Code investigation, Round 2 — verification pass (items A-H)

Eight specific spec assumptions verified in parallel. Most held; three surprises:

**Confirmed (no spec change):**
- B: `MemoizationCache.get_with_age()` already exists at `cache.py:224-262`. Spec had hedged "needs adding" — wrong; it's there. Removed the hedge.
- C: `shared["_pflow_workflow_file"]` exists, reliably set by `runner._prepare_workflow` for every run via `setdefault`. Caveat: inline runs use a synthetic `ir-hash:<md5>` identifier, not a filesystem path.
- E: `LLMNode._call_llm` integration is structurally correct — inside ThreadPoolExecutor timeout AND retry loop (for `LLMTransientError` re-raise path).
- G: `data_flow.py::validate_data_flow()` is genuinely shared. Both validators call into it; `check_inputs=True` (run-time path) vs `False` (compile path). Severity filter differs at the boundary (compiler keeps only ERROR).
- H: `_FAILURE_CATEGORY_MAP` at `executor_service.py:29-44`. Adding `"cache_failure": "cache_failure"` is a one-line dict insertion plus required co-edit to `CATEGORY_TITLES` in `core/diagnostic.py`.

**Surprise 1: `complete()` signature can't accept structured system content today.**
Today's signature: `system: str | None`. Messages built internally via `_build_messages()` with scalar `content: <str>`. Cache feature is the FIRST to need `[{"type":"text","text":"...","cache_control":{"type":"ephemeral"}},...]` system content blocks. Phase C must extend the adapter signature: new `cache_blocks` parameter or widen `system` to `str | list[ContentBlock]`. Plan-level decision; spec now mandates the parameter shape be specified, not which alternative wins.

**Surprise 2: `compute_node_config` uses key `"batch"` not `"batch_config"`.**
The conditional inclusion pattern is: `if batch_config: config["batch"] = {...}`. Spec previously called this `batch_config` everywhere — wrong key name. `prompt_cache` follows the same pattern: `if prompt_cache_content: config["prompt_cache"] = ...`. Pattern is robust — 3 conditional inclusions in same function (`static_params`, `template_params`, `batch_config`).

**Surprise 3 (most consequential): `LLMNode` does NOT have access to its `NodeConfig`.**
Spec assumed auto batch-prefix detection happens in `LLMNode.prep()` reading the unresolved template at `config.template_config.template_params["prompt"]`. That attribute path exists (verified at `runtime/engine/types.py:12-46`), but `LLMNode` only sees `shared` and resolved `self.params` — no handle on its `NodeConfig`. The unresolved template is preserved on `NodeConfig` but never reaches the leaf node.

Three options for Phase D plan-writing:
- (a) Engine injects unresolved batch-bearing template under reserved key in `node.params` before `node._run`. Minimal plumbing.
- (b) Engine passes `NodeConfig` to LLMNode via reserved `shared` key. Broader access, arguably overscopes.
- (c) Detection moves out of LLMNode entirely into `runtime/engine/batch_executor.py` where `template_config.template_params` is already in scope. Recommended — natural home for "what's the static prefix across this batch?"

Spec updated to flag this as a real Phase D plumbing decision, with option (c) recommended absent counter-argument.

**Insight to carry forward:** code-shape verification before plan-writing catches assumption drift cheaply. The "LLMNode reads unresolved template" assumption had been in the spec since §25; would have surfaced as a Phase D blocker if not caught now.

### Other spec changes folded in this session

(Not exhaustive — spec is the source of truth. These are the categories of change.)

- DD#26-36 added (Tier 2 in-by-default, Diagnostic id field, no FixAction, closed warning catalog, four-level confidence, token estimation tier, capabilities table, savings ratio, auto-load trace, optional inputs, three-tier architecture).
- New requirements subsections: Stable Warning ID Catalog, Output Format — Text, Output Format — JSON, Confidence Labeling Algorithm, Cross-Workflow Walker, Token Estimation Strategy, Per-Model Capabilities Table, Diagnostic Extension.
- `pflow analyze-cache` Command requirements section restructured: drop `fix.action` references, update confidence to 4-level, move Tier 2 from "out of v1" to "in v1," reflect auto-load trace and optional inputs.
- `--dry-run` Cache Nudge section: full analytical pass (was: shared module call only).
- `Auto Batch-Prefix Caching` section: savings-ratio rule replaces size/token thresholds.
- `Out of Scope (v1)`: removed Tier 2 verification (now in v1); added FixAction, cross-workflow auto-fix suggestions, n-gram detection, `pflow cache apply`, per-tier projections, per-provider breakdown, graph viz, `--diff` mode.
- `Files to Modify`: added Diagnostic extension, `core/llm_capabilities.py`, `core/cache_analysis/` package with submodules.
- `Test Infrastructure`: added 5 new test files including golden-file outputs for analyze-cache modes.

### What's deliberately NOT in the spec (kept here / in research)

- The journey of how decisions evolved — this entry.
- Rejected alternatives (alt-1 / alt-2 mockups) — preserved in `research/output-draft-alt-1.md` and `output-draft-alt-2.md`.
- v3 synthesis doc — preserved in `research/output-format-v3.md` with deprecation header.
- Code investigation subagent reports — captured in conversation; not in spec.
- The "% threshold math" reasoning that made the user's intuition correct — captured here, not in spec (the spec has the formula and triggers; the reasoning for *why* belongs here).

### Open threads for Phase B-G plan-writing

These are the spec-level decisions deferred to the implementation plan, not decided in this session:

1. **Adapter `complete()` extension shape** (Phase C). New `cache_blocks` parameter vs widening `system` to `str | list[ContentBlock]`. Trade-off: new parameter is more explicit but adds signature surface; widened type is API-cleaner but requires runtime-shape branching inside the adapter. Plan-writing decision.

2. **Auto batch-prefix detection placement** (Phase D). Three options surfaced in verification pass; option (c) — detection in `batch_executor.py` — is recommended. Plan-writing should confirm or counter-argue with concrete reasoning.

3. **Tier 2 prose-mismatch detection algorithm** (Phase F). When child input is renamed (e.g., `concept_brief → creative_brief`), tracing back to parent value via input mapping. Algorithm: walk `node.params.inputs[child_input] → ${parent_expr}`, extract tail of `parent_expr`, compare to chunk identifiers in both files' `## Cache` blocks.

4. **`cache.cross-workflow-prose-mismatch` "which prose wins?" heuristic** (Phase F or v1b). v1 emits the warning without auto-fix; v1b decision based on observed real-world prose-mismatch patterns.

5. **`--from-trace` matching strategy for 2.0.0 traces** (Phase F). 2.1.0 traces carry `workflow_path` (auto-load uses this). 2.0.0 traces don't — for auto-load to work on legacy traces, need a filename heuristic OR skip auto-load for 2.0.0.

6. **Padding-advisory algorithm** (Phase F). v1 surfaces unambiguously net-positive opportunities. Cross-call optimization (full prefix-tree) deferred to v1b.

7. **Diagnostic `id` field migration** (Phase B). New field is optional; existing diagnostics don't need migration. But: should validators emitting cache-related errors (e.g., `cache.order-mismatch`) be required to set `id`, or can they fall back to `(severity, source, node_id, message)` identity tuple? Probably: cache-namespaced emitters always set id; legacy emitters add it as they're touched. Plan-writing should specify the migration policy.

### Where things stand at session end

- Spec at v36 is contract-ready and self-contained. No `output-format-v3.md` references; v3 marked deprecated.
- All decisions documented as DDs (#26-36 added this session).
- Verification pass complete; spec corrections applied for items D, F, A, H.
- 7 open threads identified for Phase B-G plan-writing — none are spec-level ambiguities; all are plan-level patch-ordering and implementation choices.

### Next step

Phase B-G implementation plan writing. Use the spec as the contract; this progress log entry as the journey/insight reference. Plan should:
- Be informed by the verification pass findings (especially the `LLMNode` plumbing gap and the `complete()` signature extension)
- Address the 7 open threads above as concrete patch decisions
- Specify file-level patches in execution order
- Define gating conditions per phase (what must pass before next phase can land)
- Reference Task 158's progress log §27 (Phase 0 spike findings) and §38 (end-to-end verification) for concrete LiteLLM behavior

Before plan-writing begins, optional: `/ultrareview` on the spec to catch issues this session may have introduced.

---

## 27. Session 2026-04-28 — Pre-plan-writing spec consistency pass

User asked for a focused critical-read of the spec before plan-writing began. The session caught a substantive internal contradiction left over from the §26 framing shift (DD#33 + DD#36 invalidating earlier prewarm-validation-error language without all the dependent paragraphs being rewritten), plus seven smaller decisions deferred by §26 as "open threads" that needed resolution before Phase B-G plans could be written.

### Critical contradiction caught and fixed (item 1)

**DD#18 + Per-Node `prewarm:` field description + Out of Scope prewarm bullet + Test Infrastructure + Phase D summary** all still carried "hard validation error demanding an explicit choice" / "v1 starts conservative (e.g. batch size > 10 AND prefix > 2k tokens)" language even though §26's DD#33 (savings-ratio rule, no absolute thresholds) and DD#36 (analytical findings never block `pflow run`) had logically replaced them. Five sites updated this session:

- DD#18 (line 77) rewritten to defer to DD#33 + DD#36; absolute thresholds dropped.
- Per-Node `prewarm:` field description (line 159) drops "validation error" framing.
- Out of Scope prewarm bullet (line 800) drops same.
- Test Infrastructure `test_batch_cache_prefix.py` description retargets to "savings-ratio threshold (DD#33)".
- Phase D summary in Implementation Phasing clarifies advisory emission belongs to Phase F (analyze-cache + dry-run), NOT Phase D.

Lesson: when a load-bearing DD is added late in spec evolution (DD#33, DD#36 in §26), grep for the framing it replaces — every prior paragraph carrying the old framing needs reconciliation, even if the new DD is internally consistent.

### Code investigation, Round 3 — five parallel pflow-codebase-searcher subagents

Five questions, dispatched in parallel:

1. **`MockLLMClient.call_history_full` actually exists?** → YES, at `tests/shared/llm_mock.py:105`, populated unconditionally on every call. Class docstring explicitly notes it was added during Task 158 in anticipation of Phase B/C cache-structure tests. The "Add untruncated-prompt mode to the mock" bullet in Test Infrastructure was stale — removed. DD#23 reframed "fully in place from Task 158."

2. **`Diagnostic.source` field convention?** → `source` is *only* used for dedup identity (`__eq__`/`__hash__` at `core/diagnostic.py:84,92`). Renderers ignore it. Existing analytical-tier precedent: `pflow plan` uses `source="planner"` regardless of CLI vs MCP caller (six sites in `execution/plan.py`). Decision: cache analytical findings use `source="cache_analyzer"` for both `pflow analyze-cache` and `pflow run --dry-run`. Folded into Validation Location section.

3. **`complete()` signature extension shape?** → `_build_messages()` at `llm_client.py:579-602` already does scalar-or-list-of-blocks for the **user** message content (when attachments present). Decision: widen `system: str | None` to `system: str | list[ContentBlock] | None`. Mirrors existing user-side pattern. Mirrors LiteLLM/Anthropic SDK/OpenAI SDK convention. The line `messages.append({"role": "system", "content": system})` works unchanged for both shapes — type hint widens, runtime logic doesn't change. Rejected (a) "new `cache_blocks` parameter" — invents parallel channel that has to merge with `system` inside `_build_messages`, more code, more docs, more edge cases. Folded into Cache Rendering section.

4. **Trace filename pattern + inline-run identifier?** → Filename: `workflow-trace-<safe_name>-<YYYYmmdd-HHMMSS>.json` where `safe_name = re.sub(r"[^a-zA-Z0-9_-]", "-", workflow_name)[:30]` (`workflow_trace.py:473-486`). Inline runs: `_synthesize_inline_workflow_id(ir)` returns `"ir-hash:<32-char-md5>"` (`runner.py:36-53`); already used by `MemoizationCache.workflow_path`. Decision: `trace["workflow_path"]` carries the absolute path for file/library runs and the `"ir-hash:<md5>"` synthetic identifier for inline runs — symmetric with cache layer. Folded into DD#22 + Trace Format section.

5. **Hash function for OpenAI `prompt_cache_key` + parser shape options?** → MD5 is pflow's uniform convention for content identity (5 sites: `cache.py:85,111,344`, `instrumentation.py:178`, `smart_filter.py:71`, `runner.py:52`, all with `# noqa: S324`). SHA-256 is reserved for security-relevant change detection (2 MCP-config-drift sites). Decision: `prompt_cache_key = hashlib.md5(_deterministic_json(rendered_cache_content).encode()).hexdigest()` — mirrors `compute_config_hash`. Folded into Cache Rendering section.

   Parser shape: today the markdown parser allows `- key:` params and tagged code blocks **only inside `### entities`** (`markdown_parser.py:271-274,422-447` — orphan content under `##` is an error). The spec's `## Cache` shape (inline `- ttl: 5m` + a single ` ```cache ` block, NO `### entities`) is a NEW structural rule. Two options surfaced:
   - (A) Entity-based: each chunk gets a `### concept` heading; reuses all existing parser machinery, zero new structural rules — but redundant ceremony (chunk identifier already comes from the template path) and breaks the spec's syntax.
   - (B) Section-level: matches the spec exactly but extends parser to accept `- key:` and code blocks directly under `## Cache`.

   Decision: Option B. Reasons: (1) agent-readability principle — Option A's `### chunk-name` heading is redundant when chunk identifier comes from `${var}` stripping; (2) "simplicity of FINAL code" — Option B is more parser work but the resulting workflow file is simpler; we optimize for the long tail of agents reading workflows, not the one-time parser extension. Folded into Files to Modify markdown parser bullet.

### Decisions deferred to plan-writing

User explicitly accepted these as plan-writing-time decisions, not spec-level:

- **Heterogeneous-batch detection in cross-workflow walker** (`_enumerate_child_calls` contract): plan-writer reads the function and encodes the actual semantics.
- **Tier 2 prose-mismatch algorithm details**: spec specifies the high-level rule (compare prose-before-`${var}` byte-by-byte when names match across boundary) and the rename-precedence rule (prose-mismatch suppressed when rename detected for same chunk). Algorithm-level edge cases (whitespace-only differences, encoding) deferred to Phase F implementation.

### Smaller decisions taken this session

- **Auto-load only matches 2.1.0 traces** (DD#34 update). 2.0.0 traces require explicit `--from-trace`. Filename-based fallback rejected — collision risk via the 30-char-truncated-stem sanitizer; cleaner to require the new format. 2.1.0 traces accumulate fast in practice.
- **Cross-workflow rename precedence** (Cross-Workflow Walker section): rename detection takes precedence over prose-mismatch — never double-emit on a renamed chunk. Prose-mismatch fires only when names are identical AND prose differs.
- **Sparse memo aggregate confidence** (Confidence Labeling Algorithm): aggregate label gains coverage detail. Text mode: `Confidence: medium_from_memo (3 of 30 nodes have prior run data)`. JSON adds `estimate_confidence_coverage: {trace, memo, estimator, heuristic, total}` sibling field.
- **Gemini multi-marker collapse** (Breakpoint Limit Handling): added explicit note. v1's 2-marker max degrades correctly on Gemini because the latest marker's prefix is always a superset of the earlier marker's prefix.
- **Golden test pattern** (Test Infrastructure): follow `test_mermaid_golden.py` — parametrized cases, byte-exact equality, regen command in failure message. Synthetic minimal workflows under `tests/test_cli/golden_analyze_cache/`, NOT lyrics-generator (reserved for smoke tests). Cost values pinned via `MockLLMClient.set_response(cost_usd=...)` for stable goldens across LiteLLM pricing updates.

### Items deferred per user direction

- **Item 11** (`litellm.token_counter` coverage): use as-is, don't pre-validate.
- **Item 13** (Anthropic per-TTL pricing accuracy): re-verify in Phase E only when 1h TTL ships.
- **Item 14, 15** (`pflow save` round-trip preservation, `pflow publish` skill cache preservation): defer; skill workflow will be reworked separately.
- **Item 16** (`--strict` CI gating): skip.

### What's still NOT in the spec

The exact Phase B-G implementation plan. Spec is the contract; plan is the patch ordering and file-level dispatch. Plan-writing begins next. Plan should reference DD#18 (rewritten this session), DD#33, DD#36 as the load-bearing prewarm-semantics triad; DD#34 as the auto-load contract; DD#28 as the rationale for "no `FixAction`"; the new `source="cache_analyzer"` convention; the Option B parser extension scope; the widened `system` parameter shape; and the Gemini collapse note for cache-rendering tests.

### Where things stand at session end

- Spec passes a self-consistency grep — no remaining "validation error" / "hard error" prewarm references.
- All 7 §26 open threads either resolved this session or explicitly deferred to plan-writing with rationale.
- 5 codebase-research findings folded into spec.
- progress-log.md captures the journey here; spec captures the contract.

### Next step

Write the Phase B-G implementation plan. The plan should:
- Open with a phase-by-phase patch ordering, file-by-file
- Define gating conditions per phase
- Reference §27 decisions as load-bearing context
- Re-verify any spec assumption that's still hedged ("approximate," "needs verification," etc.) before encoding it as a patch instruction
- Address the 7 §26 open threads — most are now resolved spec-side; remaining ones are plan-level patch-ordering choices

---

## 28. Session 2026-04-28 (continued) — Last-pass scan of starting-context braindumps

User asked: "anything left in these files we need to decide or investigate?" referring to `starting-context/braindump-2026-04-27-supplementary.md` and `starting-context/braindump-design-complete.md`. Walked both files end-to-end and identified two remaining spec gaps plus several already-deferred or implementation-time items.

### Two spec gaps caught and fixed

#### Gemini TTL — turned a punt into a uniform contract

Original framing in spec: *"TTL translates to Anthropic's extended cache (via LiteLLM's passthrough of `ttl` when supported)"* — silent on Gemini. My first pass through the supplementary braindump recommended a "best-effort, document the limitation" framing. User correctly pushed back: *"why is this not supported by litellm? seems weird? is the default ttl we are setting supported (5m)?"*

Re-investigated via WebFetch on LiteLLM's caching docs and Vertex provider docs. Finding: LiteLLM **does** support Gemini TTL, just with a different wire format than Anthropic. Anthropic accepts human-readable strings (`ttl: "1h"`, `ttl: "5m"` — its native API syntax); Gemini's `cachedContents` requires seconds notation (`ttl: "3600s"`, `ttl: "300s"`). When `cache_control` is sent without a `ttl` field, each provider uses its native default (Anthropic 5 min, Gemini's `cachedContents` default, OpenAI auto).

This means pflow can ship a uniform `- ttl: 5m | 1h` workflow surface that works across providers — the adapter does a tiny per-provider translation table:

| Workflow `- ttl:` | Anthropic wire | Gemini wire | OpenAI |
|---|---|---|---|
| (omitted) | no `ttl` field (5m default) | no `ttl` field (provider default) | ignored |
| `5m` | `ttl: "5m"` | `ttl: "300s"` | ignored |
| `1h` | `ttl: "1h"` | `ttl: "3600s"` | ignored |

Spec edit applied to the Cache Rendering section. The "out of scope" Gemini lifecycle exclusion remains (we don't manage cache deletion, idempotent-create semantics, or storage-cost optimization) — only the TTL emission was punted, and it shouldn't have been.

**Lesson:** when WebFetched docs are scant on a feature, double-check by fetching the provider-specific page. The general LiteLLM caching docs don't surface Anthropic TTL syntax (because it's just "whatever Anthropic accepts"); the Vertex page explicitly documents Gemini's seconds notation. Different docs serve different audiences. User's "seems weird" instinct caught this.

#### Cost-estimate degradation for unknown models — silent gap in analyze-cache contract

`braindump-design-complete.md` flagged: *"Task 158 established the `pricing_available: False` / `partial_cost_usd` / `unavailable_models` tri-state for runtime cost reporting; `analyze-cache` should mirror that shape for its dollar estimates."* The spec was silent — neither the JSON nor the text output specified what happens when `litellm.completion_cost()` returns `None` for a model.

Spec edit applied to the `pflow analyze-cache` Command section: missing pricing → partial cost estimates with `partial_cost_usd: bool` and `unavailable_models: list[str]` in JSON, text shows `~$0.84 (partial — 2 of 23 nodes use unpriced models)` with a footer note listing the unpriced models. Never crash, never show `$0.00` for unpriced models. Not a failure mode (exit 0); structural recommendations are still valuable.

### Items confirmed addressed (no action)

- Walker emission plumbing (option c → adapter marker emission): already flagged in Non-Obvious Integration Points; Phase D plan-writing decision.
- OpenAI `prompt_cache_key` routing behavior: Phase D spike.
- Gemini implicit-vs-explicit break-even warning: Planned Follow-Ups.
- `list | str` shape for older workflow inputs/outputs: Phase C edge-case test territory.
- `pflow save` round-trip / `pflow publish` skill cache preservation: deferred per user direction.
- `litellm.token_counter` coverage: use as-is, don't pre-validate.
- Anthropic per-TTL pricing accuracy via `completion_cost()`: Phase E verify when 1h ships.
- Diagnostic.id field doesn't break existing tests: Phase B verify (`make test`).
- `test_plan_drift.py` stays green: load-bearing invariant.
- Tier 2 walker actual LOC: plan-writing validates against real code.
- `NodeConfig.prompt_cache_items` field name: implicit at line 220 of spec; plan-writing makes it explicit.

### Where things stand at session end (revised)

Spec is now genuinely contract-ready. Two real gaps fixed (TTL translation table; cost-estimate degradation contract). All other items from the starting-context braindumps are either (a) already in spec, (b) deferred per user direction, or (c) plan-writing/implementation-time decisions that don't belong in the spec.

Remaining work before code: write the Phase B-G implementation plan.

---

## 29. Session 2026-04-28 (continued) — Pre-handoff verification round

After consolidating the starting-context braindumps into `agent-handoff.md`, user asked: *"anything you want to verify using parallel pflow searcher subagents before we conclude this session?"* Strong instinct that several claims in the spec/handoff hadn't been directly verified by reading code. Dispatched one verification agent across five claims plus a WebFetch on Anthropic's TTL syntax. Three of five claims came back WRONG, plus the Anthropic WebFetch surfaced one more wrong claim. This is the value of verifying assumptions before plan-writing — these errors would have cost real implementation time.

### Findings and corrections applied

**WRONG #1: Anthropic does not accept `ttl: "5m"` as an explicit value.**
WebFetch on Anthropic's prompt-caching docs (now redirected to platform.claude.com): only two states are documented — omit `ttl` for the 5-min default, or set `ttl: "1h"` for extended. No other values mentioned (no `"30m"`, no `"2h"`, no explicit `"5m"`).

Spec's TTL translation table previously said `cache_control: {type: ephemeral, ttl: "5m"}` for Anthropic on `- ttl: 5m`. **Corrected:** `cache_control: {type: ephemeral}` (omit ttl, use 5-min default). Gemini still uses `"300s"` and `"3600s"` (those ARE its native syntax). OpenAI still ignored. Translation table now reflects each provider's actual accepted-values vocabulary.

**WRONG #2: Phase D option (c) is structurally wrong.**
Spec previously recommended moving auto batch-prefix detection to `runtime/engine/batch_executor.py`. Codebase verification revealed:
- `batch_executor.py` exists at `src/pflow/runtime/engine/batch_executor.py` (813 lines).
- Public entry: `execute_batch(node, config, shared, execute_single_fn)`.
- It only resolves the OUTER `items_template` via `resolve_batch_items` / `TemplateResolver.resolve_template`.
- Per-item template resolution happens in the callback (`engine._execute_single_node`), NOT in batch_executor.
- The static prefix portion of the LLM prompt template is therefore not in batch_executor's scope.

Spec's Non-Obvious Integration Points and agent-handoff's "hardest piece" section both updated to **mark option (c) as REJECTED** and recommend option (a) instead: engine injects the unresolved batch-bearing template under a reserved key in `node.params` before `node._run`; LLMNode does detection during `prep()`. Suggested key name: `__prompt_cache_unresolved_template__`.

**WRONG #3: `_attach_llm_call_to_event` does not exist.**
The function is `_add_llm_data` at `src/pflow/runtime/workflow_trace.py:202`. Reads `node_output["llm_usage"]`, assigns `event["llm_call"] = llm_usage`, attaches `event["llm_prompt"]` and `event["llm_response"]`. Single integration point for trace 2.1.0 cache fields.

Bonus finding: a stale comment in the codebase itself at `workflow_trace.py:545` references the wrong function name. Out of scope for Task 159 to fix that comment, but flagged in the spec's updated trace-seam reference.

**WRONG #4: The `executor_service.py:33-37` comment was mischaracterized as a `_FAILURE_CATEGORY_MAP` ↔ `CATEGORY_TITLES` invariant.**
The actual comment is about syncing `_FAILURE_CATEGORY_MAP["llm_failure"]`'s VALUE string with the `LLM_FAILURE_CATEGORY` string constant in `core/diagnostic.py` — both must be the literal `"llm_failure"`. `CATEGORY_TITLES` is imported but not mentioned in the comment.

Adding cache categories actually requires THREE coordinated entries (not one dual invariant):
1. String constant in `core/diagnostic.py` (e.g., `CACHE_FAILURE_CATEGORY = "cache_failure"`).
2. `_FAILURE_CATEGORY_MAP` entry — only for categories that flow from typed exceptions (`cache_failure`); analyzer-emitted `cache_warning` / `cache_advisory` skip this.
3. `CATEGORY_TITLES` entry for the renderer title.

Spec Files-to-Modify section and agent-handoff "co-edit gotcha" section both updated.

**Wrong-but-harmless: `scratchpads/task-158-spike/` was cleaned up.**
Three references in agent-handoff pointed at this directory as the "spike template." It no longer exists. Updated to describe the spike pattern (minimal Python file calling `complete()` directly under `scratchpads/`, ~$0.10/run) without claiming a specific template path.

### Confirmed claims (no change needed)

- `MockLLMClient.set_response()` accepts `cost_usd` parameter (`tests/shared/llm_mock.py:110-118`). Default `None`. Costs stored in `_costs` dict, surfaced in returned `usage`. agent-handoff's golden-test cost-pinning recommendation is sound.
- Inline-run `"ir-hash:<md5>"` flows from `_synthesize_inline_workflow_id` (`runner.py:36-53`) through `_pflow_workflow_file` to `MemoizationCache.workflow_path` (verified at `runtime/cache.py:154,265-294` and `instrumentation.py:323,327`). Trace 2.1.0's `workflow_path` symmetry with the cache layer is real.
- `batch_executor.py` exists (just not where detection should live).

### Lesson

Verification round caught what felt like solid claims — they were stale or mischaracterized. The handoff document was written with care but couldn't catch its own errors without code. **Recommendation for next session's plan-writer**: re-verify any spec claim about line numbers, function names, or "the comment at X documents Y" before encoding it as a patch instruction. Five of five verifications would have been hours of debug-then-fix during implementation; thirty minutes of verification now saved that.

### Where things stand at session end (final)

- Spec corrections applied: TTL translation table (Anthropic 5m row), Phase D plumbing (option (a) recommended), trace seam function name (`_add_llm_data`), Files-to-Modify Diagnostic-extension co-edit characterization.
- Agent-handoff corrections applied: Phase D plumbing section rewritten, co-edit gotcha rewritten, three spike-script path references replaced.
- Five WRONG claims fixed; four CONFIRMED claims preserved.
- Spec + progress log + handoff are now genuinely consistent with the verified code shape.

Plan-writing is the next step.

---

## 30. Session 2026-04-28 (continued) — Pre-plan-writing verification round + spec corrections

User asked to start plan-writing; this session ran one more round of verification before drafting and surfaced two material corrections to the spec. Pattern continues from §27/§29: verify-don't-trust applies recursively, even to claims left by careful prior sessions.

### Open threads enumerated at session start

The spec's outstanding plan-level decisions (per §26-§29 deferrals):
1. Reserved param key for engine-injected unresolved batch template (Phase D).
2. Tier 2 prose-mismatch detection algorithm (Phase F).
3. OpenAI `prompt_cache_retention` mapping for `- ttl: 1h` (Phase C).
4. OpenAI `prompt_cache_key` parallel-batch routing semantics (Phase D).
5. `pflow save` round-trip for `## Cache` (Phase B test).
6. `WorkflowExecutor._compiled_workflow_cache` ↔ sub-workflow `## Cache` (Phase C test).

Items 1–2 were already plan-level (no spec change needed). Items 3–4 needed verification before plan-writing could lock semantics. Items 5–6 became Phase-internal test gates.

### Round 1 — free docs verification

WebFetch + WebSearch on OpenAI prompt-caching docs, LiteLLM caching docs, and Anthropic prompt-caching docs in parallel. All four open OpenAI/Anthropic questions resolved without paid API calls:

- **OpenAI `prompt_cache_retention`** — accepts only `"in_memory"` (default) or `"24h"`. Two discrete buckets, no continuous TTL. Pflow's `- ttl: 1h` has no exact match; mapping to `"24h"` overshoots but matches the user's intent (the alternative — staying on default `in_memory` — silently expires after 5–10 min idle, violating the `1h` opt-in).
- **OpenAI `prompt_cache_key`** — sticky-routing confirmed: "requests with the same cache key are routed to the same backend." Soft per-prefix limit ~15 RPM per backend; bursts above overflow to additional machines (graceful degradation, not failure).
- **LiteLLM cache_control TTL passthrough** — Anthropic and Gemini wire formats confirmed via Vertex docs (Gemini uses seconds-suffix notation). LiteLLM's general caching doc is silent on per-provider TTL handling, but the provider-specific pages cover it.
- **Anthropic TTL syntax** — only `"1h"` accepted as explicit value; omitted = 5-min default. Spec was already correct here post-§29.

### Round 2 — code-shape verification subagent

One pflow-codebase-searcher subagent dispatched on 10 plan-critical claims to lock the patch instructions before plan-writing. Findings shifted several plan-level expectations:

**Confirmed:** `core/llm_providers.py` mirror pattern works for `core/llm_capabilities.py`. `compute_node_config` shape matches the spec's `batch_config` precedent (dict key `"batch"`, lines 139-170). `resolve_sub_workflow` primitive returns `Optional[SubWorkflowResult]` with `(ir, path, warnings)` shape. `MemoizationCache.get_with_age` exists with `(action, output, created_at_epoch)` return shape.

**Corrections applied (handoff updated):**
- Tier 2 walker LOC estimate bumped from spec's "~50 LOC" to **~130–240 LOC** (skeleton + three analyses + cycle detection + result dataclass). Spec's mermaid-mirror framing held; the LOC was optimistic.
- `_FAILURE_CATEGORY_MAP` co-edit pattern is **5 places, not 3** when introducing a typed exception (handoff said 3): `runtime/node_state.py` `FAILURE_CATEGORY_*` constant + `core/diagnostic.py` constant + `CATEGORY_TITLES` entry + `_FAILURE_CATEGORY_MAP` entry + optional `LLMCallError`-style typed-exception subclass with `to_diagnostics()` override. For Task 159's `cache_warning` and `cache_advisory` (validator-emitted, not exception-driven), only 2 of the 5 places apply.
- `MockLLMClient.complete()`'s `system` parameter is typed `Optional[str]` — needs widening to `Optional[Union[str, list[dict]]]` for Phase C cache-structure tests. Plan-level patch instruction.
- `LLMNode._call_llm` integration confirmed at lines 332-390 inside ThreadPoolExecutor timeout AND retry boundary. Cache rendering assembles in `prep()` (sets `prep_res["system_blocks"]`), passes through to `complete()`. Plan-level patch shape now explicit.
- Trace 2.1.0 `format_version` is one constant (`TRACE_FORMAT_VERSION = "2.0.0"` at `runtime/workflow_trace.py:17`). Cache fields land via `_add_llm_data` (line 202-238) extending the `llm_usage` keyset.

**Most consequential finding — Task 158's §27 cache_control verification:** the subagent confirmed Anthropic + thinking + cache spike DID find `cache_creation_input_tokens=0` for Opus 4.5 with a 1380-token prompt. Two hypotheses: (a) Opus has a higher per-model threshold than Sonnet's documented 1024, OR (b) thinking silently disables cache_control markers on Opus. Required a paid spike to distinguish.

### Round 3 — paid Anthropic spike (3 sub-rounds, ~$0.50 total)

**3.1 Initial test** (Opus 4.5/4.6/4.7 + thinking + cache, Sonnet 4.5 control):
- Sonnet 4.5 + thinking + cache at 1072 cacheable tokens → caches ✓.
- Opus 4.5 + thinking + cache at 1097 tokens → no cache ✗ (Task 158 finding reproduced).
- Opus 4.6 + thinking + cache at 1097 tokens → no cache ✗ (counter to user's hypothesis that 4.6 fixed it).
- Opus 4.7 → API error: `thinking.type.enabled` not supported, requires `thinking.type=adaptive` + `output_config.effort` (out of scope for Task 159; Task 158 follow-up for `llm_reasoning_map.py`).

**3.2 Threshold-vs-thinking distinguish** (Opus 4.5/4.7 with NO thinking + cache):
- Opus 4.5 + cache at 1097 tokens → no cache ✗.
- Opus 4.7 + cache at 1600 tokens → no cache ✗.

This RULED OUT thinking as the cause. Both Opus 4.5 and 4.7 fail to cache without thinking at the same prompt sizes that work on Sonnet — pointing at a higher per-model token threshold.

**3.3 Threshold confirmation** (Opus 4.5/4.7 + 4× prefix size):
- Sonnet 4.5 + cache at 4289 tokens → caches ✓ (control).
- Opus 4.5 + cache at 4289 tokens → caches ✓.
- Opus 4.7 + cache at 6258 tokens → caches ✓.

Threshold theory confirmed. Search for Anthropic's official per-model minimums returned the April 2026 Anthropic docs:

| Model family | Minimum |
|---|---|
| Sonnet 4.5, Opus 4.1, Opus 4, Sonnet 4, Sonnet 3.7 | 1024 |
| Sonnet 4.6, Haiku 3.5 | 2048 |
| Opus 4.7, Opus 4.6, Opus 4.5, Haiku 4.5 | 4096 |

Anthropic docs explicit: "Any requests to cache fewer than this number of tokens will be processed without caching, and no error is returned."

**Task 158's §27 finding was a misdiagnosis.** "Opus 4.5 + thinking + cache fails" was actually "Opus 4.5 prompt below 4096-token threshold silently no-ops." Thinking unrelated. The earlier spike's 1380-token prompt was below Opus's 4096 threshold; the cache_control marker was silently dropped per Anthropic's documented behavior.

### Spec changes applied this session

Sections updated (values in spec; rationale via `see progress log §30` cross-ref):
- **DD#32** (Per-Model Capabilities Table is a new module) — corrected per-version Anthropic thresholds.
- **DD#37 added** (OpenAI extended cache retention via `prompt_cache_retention`) — locks the `- ttl: 1h` → `prompt_cache_retention: "24h"` mapping.
- **TTL translation table** in Cache Rendering section — OpenAI column populated with retention parameter values (was: "ignored").
- **Cache Rendering threshold reference** — now cites DD#32 instead of inline numbers.
- **Per-Model Capabilities Table** section — bullet list updated; fallback recommendation noted.
- **Tracing and Cost Reporting** model-specific minimums bullet — corrected.
- **Cost Model Reference** Anthropic line — corrected.
- **OpenAI `prompt_cache_key`** in Cache Rendering — bumped from "Optionally emit" to "Emit when subset non-empty"; added 15 RPM soft-cap caveat.
- **Test Infrastructure** `test_llm_capabilities.py` description — small tweak.

No new requirements; no contract scope change. Just corrections to numerically-wrong claims and a previously-deferred OpenAI-retention decision now resolved.

### Phase split + in-phase verifications decided

Plan-writing decisions captured in `starting-context/agent-handoff.md` (not in spec — operational, not contract):
- 13-phase sub-split (B1/B2/B3, C0–C3, D, E, F1/F2/F3, G).
- Three in-phase paid spikes (~$0.30 total) deferred from this session: Phase C0 Gemini explicit cache_control verification, Phase D OpenAI `prompt_cache_key` parallel-batch routing under live load, Phase E Anthropic per-TTL pricing precision (only when 1h ships).

### Insights

- **Verify-don't-trust applies recursively.** §29 caught five wrong claims in the spec/handoff that earlier sessions had introduced; this session caught a misdiagnosis that had survived from Task 158 §27 → Task 159 spec → agent-handoff. Each verification round catches errors prior rounds didn't surface — the budget for "one more round" pays off when the surface area is large.
- **Misdiagnosis cost economics.** ~$0.50 spent on the paid spike. If the misdiagnosis had survived into Phase C plan-writing, it would have produced a per-model thinking fallback in `llm_capabilities.py` that solved the wrong problem and missed the actual fix (per-model token thresholds). Time saved: ~hours of rework when the first end-to-end test on Opus would have shown the warning fire on the wrong condition.
- **Public docs over inferred behavior.** The Anthropic April 2026 docs page gave the exact per-model threshold table. The user's instinct that 4.6 was fixed turned out to be wrong (4.6 has the same 4096 minimum as 4.5) — but the docs answered the question definitively, removing speculation.

### Where things stand at session end

- Spec is contract-correct on per-model thresholds and OpenAI retention. No more silent under-warnings on Opus.
- Progress log captures the journey + the misdiagnosis correction.
- Agent-handoff updated with phase-split, in-phase spikes, code-shape findings.
- Spike script preserved at `scratchpads/task-159-opus-thinking-cache-spike.py` for reference (clean up after plan-writing).

### Next step

Plan-writing. The next agent opens spec + this progress log + agent-handoff in that order. Plan target: `.taskmaster/tasks/task_159/implementation/plan-phase-B-through-G.md`. Estimated length 1000–1300 lines covering 13 sub-phases with file-level patch ordering, gating tests per phase, and regression invariants (`test_plan_drift.py` foremost).

---

## 31. Session 2026-04-28 (continued) — Plan-writing + 8-agent review + architectural consolidation

Plan written end-to-end (1132 lines), reviewed via the `/code-review` skill (8 specialized agents in parallel), and substantially restructured around a single architectural decision before approval. Approved plan now lives at `.taskmaster/tasks/task_159/implementation/implementation-plan.md`.

### What this entry covers (and what it doesn't)

- **In the plan**: file-level patch ordering, phase gates, test specifications, the `CacheRenderContext` design.
- **In the §31 braindump** at `starting-context/braindump-2026-04-28-plan-writing-and-review.md`: the journey, exact user phrasings, ASSUMPTIONS/UNCLEAR flags, defensive guards.
- **In this entry**: the pivot itself + why it landed where it did. Don't repeat plan content.

### The pivot

V1 plan draft followed progress log §27 option (a): inject `prompt_cache_items` / `unresolved_batch_template` / `prewarm` into `node.params` via reserved dunder keys at `engine.py:386`, plus `__pflow_cache_block__` / `__pflow_batch_alias__` / `__pflow_last_cache_meta__` in `shared`. Six reserved keys total, scattered across two namespaces.

The 8-agent review surfaced ~40 findings; deduped to 22 critical. Findings 3, 4, 5 (concurrency review) all stemmed from the same root: scattered `node.params` injection doesn't compose with parallel batch's deepcopy + pre-warm `node.params = original_params` reset. I presented the action plan as "8 critical fixes including 3 concurrency races."

User pushback was the load-bearing moment of the session — three operational questions back-to-back:

> *"do you need to investigate more about fix 6 or reserved-key consolidation?"*
> *"whats the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet?"*
> *"Are we prioritizing simplicity of the final code, not how easy it is to get there?"*

These forced the right reframing: **single typed context object, single delivery channel, single save/restore boundary.** Top-10% comparable systems (Temporal SDK `Context`, Prefect `RunContext`, Dagster, gRPC, LangGraph) all do this. pflow's existing `__trace_collector__` precedent does this exactly.

The "option (b)" framing in §27 (pass NodeConfig via reserved key) had been rejected for the wrong reason: "ripples through plan_node callers." That ripple only happens if you change `plan_node`'s signature. If the data lives in `shared` (like trace_collector), no caller ripple.

### Resolution: `CacheRenderContext`

Replaced 6 reserved keys with: one frozen dataclass `CacheRenderContext` (cache_block, subset, prewarm, unresolved_batch_prompt, batch_alias) delivered via `shared["__pflow_cache_render__"]: dict[node_id, CacheRenderContext]`. Engine builds at `run()` entry; save/restore at the engine boundary mirrors `__trace_collector__` exactly (always-install + write-back-not-pop). LLMNode reads in `prep()`. Frozen dataclass + immutable tuple = read-only-shared = parallel-batch-safe by construction.

Cache trace metadata (`cache_key`, `cache_source`, `cache_age_sec`) routes through the existing `llm_usage` channel that `LLMNode.post()` already populates — same path `cache_creation_input_tokens` takes. No sidecar `__pflow_last_cache_meta__` dict. Per-item batch granularity preserved by construction.

Collapses 4 of 5 concurrency-critical findings into one structural decision.

### Other corrections applied during review

Eight non-architectural fixes also landed (full list in plan's "Summary of plan corrections" section). Highlights:
- `plan_node` reordered: `resolve_templates` before `compute_config_hash` (was opposite in current code).
- Batch-node `prompt_cache` hash inclusion now explicit — chunks resolve from `shared` directly (validated as non-batch in B2.3).
- B3 regression baseline must be generated on `main` BEFORE B3 patches and committed as `golden_config_hashes.json`. The earlier "compare new code paths to itself" framing was a tautology.
- Min-token threshold check moved entirely from runtime to analytical tier — DD#36 forbids tokenizer at validation time. Earlier draft contradicted this.
- B2.2: validation-reach gap closed — `FLOW_IR_SCHEMA` only runs through `WorkflowValidator._validate_structure`, not through `_prepare_compilation`. Structural cache-shape checks therefore live in `_validate_cache_block` (which both paths reach) AS WELL AS the schema.
- F1 warning catalog SSoT table specifies per-ID source split (`validator` for structural, `cache_analyzer` for analytical), context-key contract, suggestions templates, nullable cost keys.
- Token estimation tier order corrected to `trace → memo → estimator → heuristic` per DD#31 (earlier draft missed `trace`).
- D.1 auto-batch-prefix gate fires on `prewarm: true` ALONE per spec DD#9 (earlier draft incorrectly required `prompt_cache:` too).

### Verification of Fix 6 (test_plan_drift parity)

review-test-fidelity raised parity as "structurally at risk." Read `tests/test_execution/test_plan_drift.py:45–172` — the test compares `build_plan` and `_run` paths against the SAME memo cache state, not cross-mode (predicted-vs-actual). Both render from same memo'd values; hashes match. The cross-mode divergence (predicted ≠ actual when upstream changes) is an inherent dry-run property, not a Task 159 regression. Folded into F3.3 as a documentation note.

### Two open user decisions

Both flagged in the plan; neither is critical-path enough to block plan approval, but each must be resolved before the affected phase ships:

1. **`cache.discrepancy` ID** (used in spec mode-4 from-trace example) — not in the v1 closed catalog. Add as 9th entry under `cache_advisory` (DD#29 design review) OR emit as generic Diagnostic without stable id? Recommended: 9th entry. Surface before F1.

2. **Cache rendering errors in batch + sub-workflow + `error_handling: continue`** — `template_error` (current plan) or `cache_failure` (currently dead-code per review-impact-completeness W8)? Recommended: stay with `template_error`. Surface before B2.3 / C1.2.

### Where things stand at session end

- Plan approved. 1132 lines, 13 sub-phases, file-level patch ordering, gating tests per phase.
- Plan + braindump are the load-bearing handoff artifacts for the implementing agent.
- Two user decisions documented as open; recommendations included; not critical-path.
- Implementation has not started.

### Insights

- **The user's three operational questions are a cheat code for plan quality.** Top-10% codebases / simplicity of FINAL code / "considered it yet?" — every drift toward "minimum-diff" gets caught. Without the questions I'd have shipped a 6-reserved-key plan with the parallel-batch race intact.
- **Drift toward minimum-diff is a real pull.** Each scattered key was individually defensible ("smallest delta from current code"). The aggregate produced bugs only visible when you stand back. The forcing function is asking what the FINAL code reads like, not the diff.
- **Verify-don't-trust applies to review agents too.** review-test-fidelity C2 was framed as a structural risk; reading the actual test file revealed it as a documentation point. Five-minute file read prevented re-architecting around a non-issue.
- **Spec language vs DD language.** Spec prose says "validation-time warning" for min-token; DD#36 says "no tokenizer at validation time." Plan resolves toward DD#36 (analytical-tier-only). When prose and DD diverge, DD wins — but surface to user, don't silently re-resolve.

### Next step

Implementation. The implementing agent opens (in order):
1. The plan at `implementation/implementation-plan.md` — start with the "Architectural backbone — `CacheRenderContext`" section near the top.
2. The braindump at `starting-context/braindump-2026-04-28-plan-writing-and-review.md` — for journey + ASSUMPTIONS/UNCLEAR flags + the "what I'd tell myself" notes.
3. Spec + this progress log only as the contract reference.

Single load-bearing gate: B3's no-`prompt_cache` hash regression test. STOP if it fails.

---

## 32. Session 2026-04-28 (continued) — Round 2 review + plan refinement

Plan v1 (post-§31 consolidation) ran through a second `/code-review` pass — 8 agents in parallel reviewing structural integrity, silent failures, validation consistency, impact completeness, feature interactions, agent UX, test fidelity, concurrency safety. ~50 raw findings, deduped to ~30, classified into 7 critical / 12 high-priority / 11 polish. This entry captures the journey + the two course-corrections from user pushback that reshaped what got encoded.

### What this entry covers (and what it doesn't)

- **In the plan**: every encoded fix is documented inline, with the round-2 architectural corrections appended to the "Summary of plan corrections from review" section at the bottom.
- **In this entry**: the user pushback that caught me drifting toward bloat, the verification round that confirmed which review findings to encode, and the insights for next round.

### The two course-corrections that mattered most

#### Correction 1 — Don't encode spike protocols inside the plan

I drafted a new "Phase 0 — Pre-implementation paid spikes" section (~80 lines) that included full spike scripts, fallback paths, and "if spike fails do X" branching for all three pre-authorized spikes (Gemini cache_control, OpenAI routing, Anthropic per-TTL pricing). I also added per-spike auth gates ("🔒 PAID SPIKE — REQUIRES EXPLICIT USER AUTHORIZATION").

User pushback was concise and load-bearing:

> *"all spikes are authorized, no need for separate authorization, also spikes should be done before implementation (plan is executed) not at implementation plan"*

> *"Can you explain what you are doing? it seems you are contaminating the spec with redundant information? if anything is relevant include the actual information in the plan, dont cross reference. this is the HOW to implement, the spike was to inform our decisions?"*

The framing error was treating spikes as plan content. They aren't. **Spikes inform decisions BEFORE the plan executes; the plan encodes the decisions.** Every "if spike X fails, do Y" line is contingency planning, which doesn't belong in the HOW. If a spike outcome later contradicts the plan, that's a plan UPDATE event — not a baked-in fallback.

Resolution: stripped the entire Phase 0 section, the obsolete C0 / D.4 / E.2 spike sub-phases (the original plan also had these — they were wrong from the start), and all "Spike outcome consumption" / "Cleanup gate" subsections. Replaced with a single Operating Principle bullet: *"Paid spikes run before plan execution, not inside the plan. The agent-handoff documents three pre-authorized spikes (~$0.30 total) ... Run them, record outcomes in progress log §32+, then update this plan if any outcome contradicts an encoded decision. Spikes do not appear as phases in the plan itself."* Merge order updated to drop C0 from the sequence.

**Insight to carry forward:** when a doc has multiple concerns (spec = contract; progress log = journey; handoff = operational; plan = HOW), the temptation to centralize "how to run spike X" in the plan is real because spikes touch implementation. Resist. Plan is the HOW once decisions are made. Spike protocols live in handoff (or progress log if scripted). The plan only encodes decisions.

#### Correction 2 — Cross-reference is fine for shared concerns; redundancy isn't

User's wording: *"if anything is relevant include the actual information in the plan, don't cross reference."* Mild tension with the earlier braindump-§31 instruction *"Don't repeat values across docs. Cross-reference instead."*

Reconciled: when something is operationally relevant to the HOW (a specific decision, a concrete value, a verbatim message format), include it directly in the plan. Cross-reference is for the journey (progress log §X) or the contract (DD#X) or operational style (handoff). Don't write "see Phase 0 spike outcome" — just say what the implementation does.

Applied this to the F1 catalog SSoT table (Critical #7). Earlier draft had column headers but empty cells with handwaves like "format strings with named placeholders" — implementing agent would have invented them. Refilled with concrete `message_template` / `required_context_keys` / `suggestions_template` / `path_template` / `nullable_cost_keys` for all 10 IDs, including the 10th entry `cache.discrepancy` per orchestrator decision.

### Architectural fixes from review

The post-consolidation `CacheRenderContext` backbone held up under round 2 review — the consolidation pivot from §31 was correct. But three structural gaps surfaced that the architectural-backbone section didn't fully close:

1. **`CompiledWorkflow.cache_block: dict[str, Any]` was mutable.** Plan claimed "immutable dict" at backbone line 38, but Python has no immutable dict. With `_compiled_workflow_cache` sharing the compiled IR across parallel sub-workflow invocations, any consumer mutation (or library `.setdefault` / `.update`) would corrupt other invocations. Fix: introduced `CacheBlockIR` and `CacheChunkIR` frozen dataclasses with `tuple` items. The compiler now constructs the frozen object once and `_compiled_workflow_cache` returns the same reference safely. `dataclasses.FrozenInstanceError` test asserts the freeze.

2. **`None` write-back on save/restore.** The original save/restore mirrored `__trace_collector__` exactly: `saved = shared.get(...); ...; finally: shared[K] = saved`. But trace consumers don't `.get()`-chain on the value. Cache consumers do: `(shared.get("__pflow_cache_render__") or ...).get(node_id)`. When `saved is None` (parent never installed), the restore writes `None` back — and `.get(K, default)` only defaults on key absence, not on `None` value, so `None.get(node_id)` raises `AttributeError`. Fix: write `MappingProxyType({})` on restore-from-absent. Also wrapped install in `MappingProxyType` for read-only enforcement (catches accidental consumer mutation as `TypeError`). Consumer pattern unified to `(shared.get(K) or {}).get(node_id)`.

3. **Hash-vs-prep render divergence.** `plan_node._render_cache_for_hash` and `LLMNode.prep._render_cache_for_messages` independently render cache content from the same `cache_ctx`. The plan asserted they "agree on values" but didn't enforce it. If the two ever diverge — different resolution function, different deterministic-serialization, different upstream-state read — memo cache is keyed on `V` while adapter sends `V'`, producing silent stale-cache hits. Fix: extract a single `_resolve_chunk_value(chunk, shared) -> str` helper that both call sites use. Test asserts byte-equivalence at the chunk-value level.

These three closed the architectural-backbone fully. Other corrections were narrower:
- `markdown_parser._build_node_dict` (line 1432) needs parallel `prompt_cache` / `prewarm` extraction next to existing `cache` extraction (otherwise the per-node IR-schema field check rejects valid workflows because the fields stay in `params`).
- `core/CLAUDE.md:103` SSoT comment must be updated to match the new identity tuple — sub-workflow dedup regression test added to lock the invariant.
- Duplicate `### Tests` block in C1.2 with stale `__warnings__` runtime emission deleted.
- `_FAILURE_CATEGORY_MAP["cache_failure"]` deferred to v1.x — adding the entry without a typed-exception producer creates dead code.

### Verifications run

Before encoding fixes, ran 4 targeted verifications against the code:

1. **`core/CLAUDE.md:103`** — confirmed: literally says *"Hash identity tuple: `(severity, source, node_id, message)` — keep it that way"* with sub-workflow dedup warning. The plan's `(severity, source, node_id, id or message)` is null-safe (preserves message-keyed dedup when `id is None`), but the SSoT comment needs updating to match.
2. **`markdown_parser._build_node_dict`** — confirmed at line 1393, with `cache` extraction at line 1432. Patch site is unambiguous.
3. **Duplicate Tests block** — confirmed: plan had `### Tests` at lines 476, 504, AND 524 with the second C1.2 block (524-533) duplicating + carrying stale `__warnings__` runtime emission.
4. **`trace_report.py:400` line citation** — confirmed wrong: actual line is 463.

Plus an empirical check on `litellm.token_counter`:
- `token_counter("claude-sonnet-4-5", "hello world test")` → 3 (deterministic).
- `token_counter("unknown-model/foo-bar", "hello world test")` → 3 (does NOT raise — falls back to default tokenizer, returns SOME count).
- `token_counter("claude-sonnet-4-5", "")` → 0 (clean).
- `token_counter("claude-sonnet-4-5", None)` → raises `ValueError`.

This shaped the F1 token-estimation tier description: the `"estimator"` source label fires regardless of model recognition (LiteLLM doesn't raise on unknown models — agents get a number, possibly inaccurate). The "exception → fall through to heuristic + log warning" path fires only on `text=None` and any future LiteLLM regression where unknown models start raising.

**Insight to carry forward:** verify-don't-trust applies to review-agent claims as well. Five of the round-2 critical findings cited specific code locations or behaviors. All five verified true; one (trace_report.py line) was off by 63 lines. Five-minute verification pass before encoding the fixes saved encoding the wrong line numbers into patch instructions.

### What's encoded vs what's deferred

**Critical (7 of 7):** all encoded. F1 catalog table has all 10 rows × 8 columns of concrete values.

**High-Priority (12 of 12):** all encoded. Includes B3 baseline-fixture merge gate (explicit), open-user-decision gates (B2.3, F1, F2), cache_chunks_skipped trace channel, sub-workflow batch concurrency test, save-bundle integration test, `WorkflowExecutor.ALLOWED_PARAMS` × schema hint message, three-state at MCP/CLI/JSON.

**Suggestions (10 of 11 encoded):** trace-load exit code contract, memo HIT short-circuits, cross-workflow walker resolution-failure (without new catalog ID), unified `_should_write_cache_metadata` gate, cost-degradation tri-state table, dry-run nudge byte-equality, F2 per-warning-ID coverage, MCP tool docstring contract. Suggestion 29 (test-file consolidation 19→~12) deferred to implementing-agent judgment per CLAUDE.md "quality over quantity, smaller is better."

**Disputed (kept disputed):** Anthropic ordering claim (cache_control accepts on any block; user-system-FIRST ordering is intentional).

**Two open user decisions resolved by orchestrator** with rationale documented:
1. `cache.discrepancy` → 10th catalog entry under `cache_advisory` (fills the slot reserved by spec DD#29; mode-4 from-trace gets a stable ID).
2. Cache rendering errors in batch+continue → route through `template_error` (defers typed `CacheRenderError` to v1.x; consistent with existing template-resolution failure semantics).

### Where things stand at session end

- Plan is 1290 lines, no residual spike phase content, no broken line citations, all key concepts (CacheRenderContext, prompt_cache, cache_block) referenced 130+ times across the HOW.
- Three architectural fixes (`CacheBlockIR` freeze + `MappingProxyType` outer wrap + `_resolve_chunk_value` shared helper) close the parallel-batch and silent-stale-cache surfaces.
- 13 sub-phases preserved (B1.1, B1.2, B2.1-3, B3.1-4, C1, C2, C3, D, E, F1, F2, F3, G). Merge order: B1 → B2 → B3 → C1/C2/C3 (parallel after B3) → D (parallel with C) → E → F1 → F2 → F3 → G. Paid spikes run before B1, outside the plan.
- F1 catalog SSoT is filled — implementing agent reads concrete message templates, not handwaves.

### Insights

- **Spike protocols are operational, not implementation.** Belongs in handoff or progress log, never in the plan. The plan is the HOW once decisions are made; spike outcomes inform decisions, they don't sit alongside the implementation as conditional branches.
- **The "what changes if X" → "always X" shift is the litmus test.** When you find yourself writing "if spike result is A, do Y; if B, do Z," you're not writing a plan — you're writing decision-tree contingencies. Pick the path; if the spike contradicts later, that's a plan update.
- **F1-style SSoT tables MUST be filled, not schema-only.** Empty cells with placeholder descriptions defeat the SSoT purpose. Fill them in the plan; implementing agent encodes verbatim. This was a load-bearing miss in the v1 plan that round-2 review caught; round-2 fix made it concrete.
- **`MappingProxyType` is cheap, frozen dataclasses are cheaper.** Both available in stdlib. When parallel-batch concurrency comes up, default to "make it impossible to mutate at the consumer," not "document the read-only contract and hope." Three structural changes (`CacheBlockIR` freeze + outer `MappingProxyType` wrap + frozen `CacheRenderContext` values) eliminate the entire concurrency surface for this feature.
- **Cross-doc tension is real, not bug.** Spec/plan/log/handoff each have a concern. The user's instruction "include actual information in plan, don't cross reference" is correct for HOW-relevant content; the §31 instruction "don't duplicate values across docs" is correct for things like DD#X numeric values. Reconcile by separating "operational decision the implementer needs to encode" (in plan) from "rationale / journey / contract" (in spec / log / handoff).

### Next step

Implementation begins. The implementing agent opens (in order):
1. The plan at `implementation/implementation-plan.md` — start with "Architectural backbone — `CacheRenderContext`" near the top, then "Operating principles," then "Cross-cutting reads," then phase-by-phase.
2. The agent-handoff at `starting-context/agent-handoff.md` — for paid-spike protocols (run before B1) + working-style notes.
3. This progress log §32 — for the journey of why the architectural fixes look the way they do.

Three paid spikes (~$0.30 total, pre-authorized) run BEFORE B1. Outcomes get recorded as a §33 entry (or appended to §32) before B1.1 patches begin.

Single load-bearing gate (unchanged from §31): B3's no-`prompt_cache` hash regression test. The pre-merge fixture step (`golden_config_hashes.json` committed against `main` head) MUST happen before B3.1 patches land; without it, the regression gate is a tautology.

The implementing agent runs the three pre-authorized paid spikes first, records outcomes as §35, updates plan sections per the Spike contingencies table if needed, then begins B1.1. The single load-bearing gate (B3 baseline fixture) remains unchanged.

## 33. Session 2026-04-29 — Round 3 review + plan refinement

Plan v2 ran through a third `/code-review` pass — 8 agents in parallel reviewing the same blindspot categories as Round 2. The hypothesis going in: "We're paying with each round; verify findings honestly; stop encoding once we hit polish-tier returns." Round 3 surfaced **7 Critical + 8 High-Priority + ~14 Medium** findings, most of which were substantive (not polish, not restatements). The user's epistemic question — "are we hitting diminishing returns?" — drove an explicit analysis: returns are still high because the plan keeps growing, each round operates on a different post-fix codebase, and Round 2's claims of completeness ("all consumers use canonical pattern") turned out false in two sites.

### What this entry covers (and what it doesn't)

- **In the plan**: every encoded fix is documented inline; the "Summary of plan corrections from review" section now has a "Round 3 fixes" subsection at the top.
- **In this entry**: the journey of why we ran a third round, the verifications that confirmed reviewer claims (and the one that disputed them), and the structural-versus-polish judgment calls that shaped what got encoded.

### Round 3 findings — verified against code before encoding

Pattern: the orchestrator triaged 8-agent output → Critical/High-Priority/Medium → verified each Critical against actual code (NOT just trusting reviewer claims) → presented action plan to user → encoded after user approval. Verification was cheap (5 grep + 2 read calls) and caught one Disputed-Critical (review-silent-failures #3 about `validate_data_flow` reach — actually verified at `compile_validation.py:120-122` to be correct as planned). The 87% confirmation rate (7 of 8 Critical confirmed) signals the curve hasn't flattened.

**Critical fixes encoded (7 of 7):**

1. **D.1 line 718 + D.2 line 759 unsafe defensive-read pattern.** Round 2 explicitly claimed "all consumers use the canonical pattern"; grep showed two sites still used `shared.get(K, {}).get(...)` — the exact `None.get(...)` AttributeError trap the architectural backbone documents. Replaced with `(shared.get(K) or {}).get(...)`. The Round 2 summary lied about its own coverage; this is the recurring "trust but verify" pattern caught by each new round.

2. **F1 catalog `cache.discrepancy` row internally unresolvable.** The row Round 2 added had `suggestions_template = ["{root_cause_action}"]` referencing a key NOT in `required_context_keys`. The helper documented in F1 says it raises `KeyError` when required keys are missing; literally applied, every `cache.discrepancy` emission throws. Action sub-templates also referenced `{affected_workflow}` and `{skipped_chunk}` — also missing. Fix: introduced `CACHE_DISCREPANCY_ACTION_TEMPLATES` dispatch map keyed on the `root_cause` enum + `CACHE_DISCREPANCY_REQUIRED_CONTEXT` per-cause additional-key map; helper dispatches and validates per-cause keys; `unknown` enum has its own action template (resolves M13). The Round-2 fix introduced the bug; Round 3 caught it.

3. **B2.2 false claim about validator step 8 reach for non-LLM nodes.** Verified `validator.py:600` — step 8 iterates `node.get("params", {})` only. B2.1 extracts `prompt_cache:` and `prewarm:` to TOP-LEVEL node keys. Step 8 cannot see them. So `prompt_cache: [chunk]` on a `type: shell` node passes both schema (additive) AND step 8 (invisible) and silently no-ops at runtime — exactly the validator-vs-runtime drift the review category exists to catch. Fix: removed B2.2's hint claim; added `cache.invalid-on-non-llm` ERROR in `_validate_cache_block` (B2.3) walking top-level node keys; new 11th catalog entry; parametrized test over all non-LLM types.

4. **Hash-vs-prep ABSENT branch handling: silent-stale-cache class.** B3.3 specified `_resolve_chunk_value` as a shared helper, but only C1.2 specified ABSENT handling (skip the chunk). plan_node.render-for-hash didn't. If hash includes the chunk's stringified `None` while prep skips it entirely, memo cache and adapter diverge → silent stale cache (the #1 risk per DD#19). Fix: shared helper returns `_CHUNK_ABSENT` sentinel; both call sites filter on it BEFORE building output; B3.4 adds explicit ABSENT-case byte-equivalence test + divergence-injection variant (anti-tautology — proves the test would actually catch divergence).

5. **D.2 prewarm execution structurally vague.** "Execute item[0] sequentially first via the existing single-item path" left ambiguous (a) which executor runs item[0] (`process_item` synchronously?), (b) how `results[0]` index alignment works, (c) whether item[0] appears in `future_to_idx`, (d) progress drain semantics. An implementing agent could break the per-index `results` array invariant `_aggregate_batch_results` depends on. Fix: concrete pseudo-code algorithm with all six implementation requirements explicit (sole `process_item` callable, `results[0]` direct write, items[1:] in `future_to_idx`, error-handling matrix locked, progress events drain through same buffer, interaction with existing `_pre_warm_compile_cache`).

6. **`cache_chunks_skipped` lost on `_call_llm` error path.** C1.2 wrote it to `prep_res["__cache_chunks_skipped__"]` and propagated through `LLMNode.post()`. But if `_call_llm` short-circuits via `_error_dict_from_exception` (template-error path, deterministic LLMCallError), `post()` never runs — channel lost. Mode-4 trace then has no skip context for the failure. Fix: cross-layer co-edit at three sites — `LLMNode.post()` (success), `_error_dict_from_exception` (error path), `write_memo_cache` persistence (round-trip). Now every trace event corresponding to a partial render — success, failure, retry-failure, memo HIT — carries the skip list.

7. **Strict `workflow_path is not None` assertion would fire 40+ times in tests.** Verified via grep: 40 `WorkflowTraceCollector(...)` instantiations across `tests/` + `src/` (the plan claimed ~21). The assertion was meant to catch missing production plumbing; cost-benefit was wrong. Fix: dropped the assertion; replaced with dedicated `test_workflow_path_set_in_production_runs` integration test covering file/inline/sub-workflow shapes. The integration test catches the same regression class without breaking 40 unrelated tests.

**High-Priority fixes encoded (8 of 8):**

- `--no-trace` flag-name collision with `pflow run --no-trace` → renamed to `--no-trace-autoload`.
- `storage_mode: shared` × `## Cache` interleaving documented as v1 limitation in `runtime/CLAUDE.md` reserved-key entry (lyrics-generator doesn't use the combination).
- OpenAI `prompt_cache_key` × batch_size > 15 RPM soft cap documented in G.2 caching guide; v1 relies on retries; deferred to v1.x as `cache.openai-batch-clamp` follow-up.
- B3 baseline cannot include post-task fields → in-memory mutation test added in B3.4 (load baseline workflow → mutate IR → recompile → assert hash invariants).
- F3.1 exit code policy locked: ERROR-severity validator findings appear in `warnings[]` with exit 0; only IR-construction failures exit non-zero. `analyze-cache` is advisory per DD#36.
- `cache_chunks_skipped` cross-layer co-edit explicit in E.1 LLMNode.post() patch list.
- D.1 `user_message_blocks` consumer step in `_call_llm`/`complete()`/`_build_messages` made explicit (was built but never read in earlier draft).
- Engine save/restore simplified: dropped outer try/except (dead code; mirrors `__trace_collector__`); hoisted `_EMPTY_CACHE_RENDER = MappingProxyType({})` to module level (eliminates per-restore allocation).

**Mediums encoded (7 of 14):** sub-workflow batch concurrency test mechanism made concrete (M5); `_EMPTY_CACHE_RENDER` hoisted (M6); divergence-injection variant (M7); D.1 must use shared resolution helper (M8); ClaudeCodeNode intentionally excluded from cache-metadata gate with explicit doc (M10); `cache.prewarm-no-prefix` added to F1 catalog as 12th entry (M12); resolved unknown root_cause action template via C2 dispatch (M13); loop recovery × cache rendering documented as engine-sequencing-guaranteed-safe (M14).

**Mediums deferred (7 of 14):** `root_cause_action` fully-structured (M1, partially mitigated by C2 dispatch); `notes[]` typed objects with `kind` enum (M2); JSON `format_version` evolution policy (M3); `per_call[].declared_prompt_cache` four-state encoding test (M4); `cache_chunks_skipped` × memo HIT explicit assertion (M9, folded into H6 doc); per-warning-ID synthetic-workflow contract sub-table (M11). All polish-tier; defer to implementer judgment or v1.x follow-up.

**Disputed (1):** review-silent-failures #3 ("`_validate_cache_block` reach across save/compile path unverified"). Verified `compile_validation.py:120-122`: compile path DOES call `validate_data_flow` via `_validate_data_flow_at_compile_time`. Plan B2.3's belt-AND-suspenders is structurally correct.

### Why Round 3 wasn't diminishing returns (analysis explicitly run with user)

User asked the right question: "It seems we are not hitting diminishing returns on this. I'm trying to understand why?" The analysis surfaced four reasons:

1. **Plan keeps growing.** 1099 lines (v1) → 1290 lines (v2) → 1445 lines (v3). More material = more surface area for next-round review.
2. **Layered visibility.** Round 1 fixed gross architecture. Round 2 hardened concurrency. Round 3 found correctness gaps that only surface once architecture+concurrency are fixed. Each layer needs the previous to be in place.
3. **Each round runs on a different post-fix codebase.** Reviewers see fresh material; their claims of completeness ("all consumers use canonical pattern") haven't been re-verified against the fixes that prompted them.
4. **Round-N fixes can introduce Round-N+1 bugs.** `cache.discrepancy` as 10th catalog entry (Round 2 fix) had unresolvable placeholder (Round 3 finding).

**Counter-evidence:** the Mediums are increasingly polish-tier (typed `notes[]`, format_version evolution, four-state test) — that signal is real but weak relative to 7 Critical + 8 High-Priority confirmed.

**Stop criterion (agreed with user):** when a round's findings shift to mostly-disputed, mostly-polish, mostly-restatements, stop. Round 3 showed none of those signals.

**Next:** targeted Round 4 with 5 agents (review-plan, review-silent-failures, review-validation-consistency, review-impact-completeness, review-test-fidelity) focused on Round-3-introduced code (dispatch map, sentinel pattern, `cache.invalid-on-non-llm`, `cache.prewarm-no-prefix`, in-memory mutation test, simplified save/restore). The other three categories (concurrency, feature-interactions, agent-ux) are predicted to find polish-only at this point.

### Insights to carry forward

- **"All consumers use X pattern" is a load-bearing claim that demands grep verification before encoding.** Round 2 made the claim; Round 3 grep falsified it in two sites. Same trap as "I tested it" without showing the command.
- **Catalog-fix that introduces an unresolvable placeholder is the Round-3 archetype.** Adding the row was the right Round-2 decision; missing the helper-vs-template integration was a load-bearing detail. When the spec sentence is "X is computed per Y," demand a structured dispatch — never a single template with a placeholder named after the dispatch.
- **Verify-don't-trust applies to my own corrections too.** Round 3 CRITICAL #2 was verified by reading the catalog row in the plan; cheap. Round 3 Critical #3 was verified by reading `validator.py:600`; cheaper. Round 3 dispute (silent-failures #3) was verified by reading `compile_validation.py:120-122`; cheapest. Reading > trusting.
- **The escape hatch is implementation.** No amount of plan review substitutes for real code on real workflows. The targeted Round 4 is the last bulk-review investment; if it returns ≤2 Critical + ≤4 High-Priority, we ship to B1.1.

### Where things stand at session end

- Plan is 1445 lines (was 1290 before Round 3). Catalog has 12 entries (was 10 in spec; +`cache.discrepancy` Round 2; +`cache.invalid-on-non-llm` and `cache.prewarm-no-prefix` Round 3).
- Architectural backbone (`CacheRenderContext` + frozen `CacheBlockIR` + `MappingProxyType` + `_resolve_chunk_value` + new `_CHUNK_ABSENT` sentinel) closes the structural concurrency and silent-stale-cache classes by construction.
- Three paid spikes still pending (Gemini cache_control, OpenAI parallel routing, Anthropic per-TTL pricing) — pre-authorized, run before B1.1.
- Round 4 targeted review (5 agents) starts after this commit.

## 34. Session 2026-04-29 (continued) — Round 4 review + read-the-actual-code refinement

Plan v3 (post §33 Round 3) ran through a **targeted Round 4** (5 agents instead of full 8: review-plan, review-silent-failures, review-validation-consistency, review-impact-completeness, review-test-fidelity). The user's epistemic question driving this round: *"are we hitting diminishing returns? Or are we aiming for the right solution that the top 10% of codebases similar to this one would implement?"*

Hypothesis going in: Round 4 would find ≤2 Critical + ≤4 High-Priority (diminishing returns signal). **Empirical result: 6 Critical + 12 High-Priority + ~14 Medium + 1 Disputed.** Returns are still high — but the bug class shifted decisively. Round 4 caught **pseudo-code bugs in Round-3-introduced code** (wrong function signatures, wrong symbol paths, references to non-existent classes, count drift). The architectural backbone is sound; the bugs are at the pseudo-code precision level.

The journey's central lesson: **read the actual code before writing pseudo-code that depends on its signature.** Round 3 sketched fixes from memory and convention; Round 4's grep + Read sweep caught:
- `process_item` returns a 5-tuple `(idx, result, error, duration_ms, buffered_events)` — Round 3 pseudo-code treated it as a dict (would have shipped a malformed `results[0]`).
- `NodeStatus.ABSENT` is the canonical symbol — Round 3 wrote `node_state.ABSENT` (would `AttributeError`).
- `TemplateResolutionError` does NOT exist — Round 3 referenced it in the `_resolve_chunk_value` pseudo-code (would `ImportError`).
- `extract_root_node_id` always returns `str` — Round 3's `if upstream_node is not None` check is dead code.
- Catalog count "10/11/12" drifted across 5 prose sites despite Round 3 adding two entries.
- `Diagnostic.__hash__` identity tuple `(severity, source, node_id, message)` — Round 3's V6 fix proposal "emit one ERROR per offending field" with shared `id` would have collapsed multi-field rejections to ONE diagnostic, hiding offenses.

### V5 + V6 fix-shape decisions (top-10% lens)

User question: *"Are we aiming for the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet?"*

This forced explicit reasoning about each fix shape rather than encoding the first-suggested approach.

**V5 — Schema vs `_validate_cache_block` shape redundancy**: Round 4 reviewer found the Round-3 dedup test was based on a misanalysis (schema-emitted and `_validate_cache_block`-emitted shape errors have different messages, no shared `id`, won't dedup). Two fix options surfaced: (a) belt-and-suspenders (both fire, accept double-emit), (b) single source of truth (schema does shape, `_validate_cache_block` does only semantics + defensive skip on compile path). Top-10% answer: **Option (b)**. Mypy/rustc/ruff each have one rule per error condition. Belt-and-suspenders means TWO places to maintain when shape constraints change — exactly the validation-consistency drift the review category exists to catch. Encoded.

**V6 — Multi-field rejection collapse**: Round-3 said "emit one ERROR per offending field" for `cache.invalid-on-non-llm`. With identity tuple `(severity, source, node_id, id or message)` and shared `id`, two emissions for the same node collapse to one. Top-10% answer: ONE diagnostic per [rule, location] with multiple offenses listed in `context["invalid_fields"]: list[str]`. Identity tuple now handles dedup correctly under this shape.

### The five high-value additions (after user said "encode all 5")

1. **`_resolve_static_prefix_for_cache` companion helper** — locks byte-identical resolution across THREE cache paths (chunk hash, chunk message, static-prefix auto-batch). Prevents the dict→Python-repr-vs-canonical-JSON divergence that would silently break cross-mode cache hits. The Round 3 plan said "use the same deterministic-serialization" but didn't lock the abstraction — D.1 calling `TemplateResolver.resolve_template` directly would substitute via Python's default `str(value)`, NOT canonical JSON. Encoded the helper inline next to `_resolve_chunk_value` with a B3.4 cross-helper byte-identity test.

2. **`cache.discrepancy` structured context payload** — agents reading from-trace mode-4 output had to regex-parse prose action templates to dispatch on root_cause specifics. Top-10% pattern: typed structured data in `context["root_cause_action"]`, prose in `suggestions` for human display. Per-cause payload schema (`CACHE_DISCREPANCY_ACTION_PAYLOAD_KEYS`) added; tests assert both prose AND structured payload per cause.

3. **JSON `format_version` evolution policy** — locked `format_version.startswith("1.")` consumer rule via module-level constants `JSON_FORMAT_VERSION` and `JSON_FORMAT_VERSION_MAJOR`. Mirrors trace 2.x policy at `trace_report.py:463`. Without this, agents pinning `== "1.0"` break silently on the first additive minor bump.

4. **Compile-path `_validate_cache_block` defensive isinstance guards enumerated** — Round 4's V5 fix said "defensive isinstance guards" but didn't enumerate them. Concrete per-shape guards now spec'd: `prompt_cache` must be `list[str]` (with all-elements check); `prewarm` must be `bool` (NOT `int` — `bool` subclasses `int`, so `isinstance(prewarm_val, bool)` rejects `prewarm: 1`); top-level `cache` block defends against malformed dict. Each guard emits `logger.warning` and skips.

5. **Spike contingencies subsection** — three pre-authorized paid spikes run before B1.1; their outcomes either confirm encoded decisions or contradict them. Round 3 left "implicit via progress log §33" for the contradiction case. Round 4 added an explicit table mapping each spike to the encoded decision it tests + the if-outcome-contradicts action. Eliminates "ran the spike, missed the contradicting plan section" regression class.

### Why Round 4 wasn't actually diminishing returns

Returns measured by Critical-finding count: Round 1 ~7, Round 2 ~7, Round 3 ~7, **Round 4 ~6**. By rate alone, no flattening. But the BUG CLASS shifted:

- Round 1 + 2 found ARCHITECTURAL bugs (scattered keys, mutable IR, missing concurrency defenses).
- Round 3 found CORRECTNESS-GAP bugs (validator reach, ABSENT branch symmetry, prewarm vagueness).
- Round 4 found PSEUDO-CODE-PRECISION bugs (wrong signatures, wrong symbols, count drift).

Round 5 prediction: pseudo-code precision in Round-4-introduced code (`_resolve_static_prefix_for_cache` helper, per-cause structured payload schema, spike contingency table). At which point we'd see Round 5 with 1-2 Critical and the curve flattening. The escape hatch is implementation. The architectural backbone (CacheRenderContext + frozen IR + MappingProxyType + sentinel + shared resolution helpers) holds against round 4 review. Remaining bugs are local correctness; they will surface immediately during B1.1 if any slip through.

### Insights to carry forward

- **"Read the target code before writing pseudo-code that depends on its signature."** Round 3 sketched D.2 prewarm without reading `_collect_parallel_results`; the resulting pseudo-code shipped a malformed `results[0]`. Round 4 verified each pseudo-code reference via direct Read. The 5-minute verification cost prevents hours of mid-implementation rework.
- **Top-10% / simplest-final-code is the right lens for fix-shape decisions.** Asking "what would mypy/rustc/ruff do?" eliminated belt-and-suspenders (V5) and id-namespacing (V6) in favor of single-source-of-truth and combined-diagnostic-with-typed-context.
- **Each round operates on a different post-fix codebase.** Round 4 reviewers saw Round 3 patches as fresh material. Round 4's claims of completeness ("all consumers use canonical pattern") need to be re-verified by Round 5 at two specific spots — process self-correcting.
- **Targeted reviews (5 agents) work as well as full battery (8) for late rounds.** Skipping concurrency/feature-interactions/agent-ux for Round 4 cost nothing — those categories were closed by earlier rounds. Targeted is the right shape after architectural backbone stabilizes.
- **`logger.warning` for fallback paths beats silent skip.** Round 4 added warnings to: cache.discrepancy unknown-enum dispatch, _validate_cache_block compile-path malformed shape, F2 auto-load scanner unparseable trace skip. The pattern: silent fallback hides regressions; visible fallback lets agents see degradation in `--verbose` mode.
- **`/evaluate-review` skill changes the methodology.** When the user invoked it after Round 4, the framework forced explicit verification of every reviewer claim via parallel pflow-codebase-searcher subagents PLUS direct Read of the 6+ critical files. The discipline caught two reviewer claims that needed clarification (e.g., "single-threaded mock defeats parallelism" was right; the proposed barrier mechanism was the right shape). The framework is the right shape for late-round reviews where reviewer accuracy matters more than reviewer breadth.

### What's encoded vs what's deferred

**Critical (6 of 6):** all encoded, all verified against actual code shapes.
**High-Priority (12 of 12):** all encoded.
**Medium (8 of 14 encoded):** sub-workflow batch concurrency mechanism, divergence-injection mechanism (per-site monkeypatch), in-memory mutation pattern (compile_workflow direct call), `type: llm` positive control, minimal-valid params per node type, `_CHUNK_ABSENT` `__repr__`/`__str__` raise, function-scoped MockLLMClient fixture, ClaudeCodeNode allowlist-style docstring.
**Medium (6 of 14 deferred):** `notes[]` typed (M2), `per_call[].declared_prompt_cache` four-state test (M4), per-warning-ID synthetic-workflow contract sub-table (M11), test file count consolidation, baseline-fixture script body, null-sort ordering polish.
**Disputed (1):** review-silent-failures #3 (`_validate_cache_block` reach via compile path) — verified `compile_validation.py:120-122` reaches `validate_data_flow`; plan B2.3 belt-AND-suspenders structurally correct.

**High-value additions encoded after user's follow-up question (5 of 5):** see "five high-value additions" section above.

### Where things stand at session end

- Plan is 1813 lines (was 1445 after Round 3, 1290 after Round 2, 1099 after Round 1). Catalog has 12 entries.
- All Round 4 pseudo-code verified against actual code shapes (`batch_executor.py:524-611`, `node_state.py:25-59`, `template_resolver.py:198-212`, `plan_node.py:35-68`, `diagnostic.py:69-92`, `compile_validation.py:120-161`).
- `_resolve_static_prefix_for_cache` companion helper locks byte-identical resolution across all three cache paths.
- `cache.discrepancy` is now agent-actionable via `context["root_cause_action"]` typed payload (no prose parsing required).
- JSON `format_version` consumer rule locked via `JSON_FORMAT_VERSION_MAJOR` constant.
- Spike contingencies table maps each spike to the plan section it can contradict.
- Three paid spikes (Gemini cache_control, OpenAI parallel routing, Anthropic per-TTL pricing) still pending — pre-authorized, run before B1.1.
- B1.1 patches start AFTER spike outcomes recorded in §35 (potentially) AND any plan updates from spike contradictions land.

### Next step

The implementing agent runs the three pre-authorized paid spikes first, records outcomes as **§36** (§35 is now Rounds 5+6 review), updates plan sections per the Spike contingencies table if needed, then begins B1.1. The single load-bearing gate (B3 baseline fixture) remains unchanged.

---

## 35. Session 2026-04-29 (continued) — Rounds 5 + 6 review + diminishing-returns analysis

Two more `/code-review` passes after §34: Round 5 (5 targeted agents — review-plan, review-silent-failures, review-validation-consistency, review-impact-completeness, review-test-fidelity), Round 6 (4 targeted agents — same minus review-plan, since architecture is closed). Plan grew 1813 → 2104 lines (after end-of-Round-6 collapse of redundant history into this progress log entry). All fixes encoded inline in the plan; this entry captures the bug classes, the meta-lessons, and the user-driven decision to STOP at Round 6 in favor of implementation-time review.

### What this entry covers (and what it doesn't)

- **In the plan**: every Round 5 + 6 fix encoded inline at the relevant phase section (`implementation-plan.md`'s top "Plan refinement history" pointer is a 10-line summary referring back here for the *why*).
- **In this entry**: the bug classes each round caught + the meta-lessons reusable across future pflow features + the explicit diminishing-returns analysis the user forced.
- **Not duplicated here**: the fix-by-fix list (lives inline in the plan); architectural decisions (Round 1-2, in §31-§32); pseudo-code precision corrections (Round 4, in §34).

### What Round 5 caught (the layer-placement and defensive-bypass round)

Round 4's prediction was Round 5 would find ≤2 Critical in pseudo-code precision class. Empirical: **7 Critical + 11 High-Priority** — bug class shifted, didn't shrink. The key finding shapes:

1. **Layer-placement violation in shared helper home.** Round 4 placed `_resolve_chunk_value` in `runtime/engine/plan_node.py` (the file where the helper was first sketched). Round 5 verified `nodes/llm/llm.py:13-20` only imports `pflow.core.*` AND F1's `core/cache_analysis/` package explicitly bans `runtime/` imports. The implied home was structurally illegal from two consumers. Fix: new `core/cache_render.py` module with lazy `runtime/template_resolver` imports inside function bodies. **Reusable lesson**: when a shared helper has 3+ consumer paths, verify ALL consumers' import boundaries before placing the helper. Round 4 verified the pseudo-code's symbols against actual code; Round 5 had to verify the consumer paths' import policies.

2. **Defensive bypass via `_make_serializable`.** Round 4 added `_CHUNK_ABSENT.__repr__/__str__` raising `TypeError` as the "fail-loud" defense if a caller forgot to filter the sentinel. Round 5 verified `runtime/cache.py:25-51`'s `_make_serializable` falls through to `f"<{type(obj).__module__}.{type(obj).__name__}>"` — using `type()` directly, NOT `__repr__`/`__str__`. The defense never fires on the actual hash path. **Reusable lesson**: a defense that doesn't fire on the path it's meant to protect is *worse* than no defense — it produces false confidence. Verify defenses fire by reading the consumer code path, not just the producer.

3. **Error-path injection at builder vs caller.** Round 4 said "extend `_error_dict_from_exception` to populate `cache_chunks_skipped` from `prep_res`." Round 5 verified the function signature is `(exc: LLMCallError) -> dict` — no `prep_res` access. The fix was to wrap the result at the *caller* (which has `prep_res` in scope), NOT widen the builder signature (cross-cutting change touching every existing caller). **Reusable lesson**: when a side-channel needs to flow through an error path, identify the call site that has the side-channel data in scope, NOT the helper that constructs the error shape.

4. **Format-string trap in spec compliance.** Spec requires `[concept, concept_brief]` (bare identifiers); Python's `str(['concept', 'concept_brief'])` produces `"['concept', 'concept_brief']"` (single-quoted). Catalog `message_template` using `{declared}` would silently produce wrong format vs spec. Fix: catalog row carries both `{declared_str}` (caller pre-formats bare) AND `context["declared"]` (typed list for agent dispatch). **Reusable lesson**: if a spec example uses non-default formatting, the catalog must explicitly carry the formatted-string variant — Python's default str-coercions are NOT the spec's contract.

5. **Mock with hardcoded zeros.** Round 4 added the `MockLLMClient` extension prose; Round 5 verified `tests/shared/llm_mock.py:258-259` hardcodes `cache_creation_input_tokens: 0` / `cache_read_input_tokens: 0`. The Round-4 prose ("populate the returned `usage` dict") was insufficient — needed the full parallel-dict pattern + resolver chain + `reset()` extension spec'd. **Reusable lesson**: when extending a mock that has a hardcoded production-mirror value, the plan must enumerate the parallel-dict pattern + every method that needs the new keys; bare prose creates ambiguity that the implementing agent resolves by writing ad-hoc monkey-patches per test.

### What Round 6 caught (the factual-errors-in-Round-5-fixes round)

Round 6 prediction: 1-2 Critical in Round-5-introduced material. Empirical: **6 Critical + 3 High-Priority** — same bug-rate as prior rounds, but every finding was a *factual error* in a Round-5 fix. The "fix-N introduces bug-N+1" pattern continued.

1. **`tuple("string")` silent splat.** Round 5's `try/except TypeError` wrap caught non-iterable values but missed iterable-but-wrong-shape (`prompt_cache: "concept"` → `tuple("concept") == ('c','o','n','c','e','p','t')`, no exception). Fix: explicit `isinstance(raw, list)` precondition + parametrized test over 6 malformed shapes. **Reusable lesson**: `try/except TypeError` around a constructor catches one failure mode; for shape validation use `isinstance` + content checks, not type-error fishing.

2. **Off-by-N consumer count.** Round 5 widening table for `apply_memo_hit` enumerated 2 callers; Round 6 grep verification found 3 (`execution/plan.py:862` was missed — the dry-run planner's `_cached_memo_entry` builder). The plan would have shipped a signature-mismatch CI failure. **Reusable lesson**: "all consumers" claims need grep verification *every round*, not just the round they were introduced. Each round operates on a post-fix codebase the prior round didn't see.

3. **Off-by-2 enumeration.** Round 5 inline comment said `_PROPAGATED_KEYS` has 5 entries; actual is 7 (`__parser_diagnostics__` and `__memoization_cache__` were missed). The comment would have been merged with stale enumeration. **Reusable lesson**: prose enumerations of code constants are a regression class — every prose count needs a code-read verification per round.

4. **Spec strict-vs-permissive contradiction.** Round 5 implemented F2 confidence aggregation as permissive (`if any(src == "trace")`). Round 6 read DD#34 line 634 verbatim: *"All rows `trace` → `high_from_trace`"* — strict. Round 5's default contradicted the spec. **Reusable lesson**: when a spec says "All X → Y", verify the implementation uses `all()`, not `any()`. The wording is precise; permissive-by-default is a bias.

5. **Missed 4th wrap site.** Round 5 enumerated 3 error-path wrap sites for `cache_chunks_skipped` injection. Round 6 verified `post()` at `llm.py:511` ALSO calls `_error_dict_from_exception` for `LLMResponseParseError` — missed. **Reusable lesson**: when the pattern is "wrap this builder at every caller," grep for the builder name across the file (not just the obvious sites). One missed call site = one silent-data-loss path at runtime.

6. **Test specification missing.** Round 5 spec'd `MockLLMClient` cache-tokens parallel-dict pattern in 30+ lines of detail but never required a test. Implementation could silently ignore the new args. **Reusable lesson**: every infrastructure extension needs an explicit unit test specification in the plan (not just "the existing mock tests will catch it") — otherwise the implementation can return defaults that pass downstream tests by coincidence.

### The diminishing-returns analysis (the user's question and the honest answer)

User asked at the start of Round 6: *"how come we are never reaching diminishing returns on these reviews? how complex is this feature?"* The right question — forcing function for honest accounting.

**Empirical bug-class evolution across 6 rounds:**

| Round | Critical found | Plan growth | Bug class | Cost-saved-per-fix |
|---|---|---|---|---|
| 1 | ~7 | +33 lines | Architecture (scattered keys → typed context) | ~2 hours |
| 2 | ~7 | +158 lines | Concurrency (frozen IR, MappingProxyType, save/restore None-trap) | ~2 hours |
| 3 | ~7 | +155 lines | Correctness gaps (validator reach, ABSENT symmetry, prewarm vagueness) | ~1 hour |
| 4 | ~6 | +368 lines | Symbol/signature precision (NodeStatus.ABSENT, 5-tuple destructure) | ~1 hour |
| 5 | 7 | +326 lines | Layer placement + defensive bypass + API-shape | ~1 hour |
| 6 | 6 | +193 lines | Factual errors + missed enumerations + spec strictness | ~30 min |

**Returns are NOT flattening by Critical-finding count** — every round found 6-7 Criticals. The dimension that changed:

1. **Bug class shifts each round.** Each round's fixes introduce a new surface that the next round reviews. Round-N reviewers see fresh material; their claims of completeness ("all consumers use canonical pattern") need fresh verification on Round-N+1's post-fix codebase.

2. **Cost-saved-per-fix is dropping.** Architecture bugs save days if caught early. Pseudo-code precision saves hours. Factual errors (off-by-N enumerations, missed callers) save minutes — they'd surface within 30-60 minutes of running the implementation.

3. **Plan-time review reads PROSE; the remaining bug class is verifiable only by reading actual code.** Round 6 caught `apply_memo_hit` 3rd caller via grep — the same grep an implementing agent runs in their first 5 minutes. Round 6 caught `_PROPAGATED_KEYS` count via direct file read — same as the implementing agent. Plan-time review used subagent verification to compensate, but the marginal value is now LOWER than implementation-time review.

**The decision (made jointly with user)**: STOP plan-stage review at Round 6. Switch to implementation-time review (`/code-review` mode against staged code, after each phase merges). The remaining bugs are local correctness — exactly what TDD red-green cycles surface immediately.

**Reusable rule of thumb for future pflow features**: 4 plan-review rounds is a reasonable upper bound for high-complexity features (this task at 13 sub-phases, 2104-line plan, 12-entry catalog is among the largest pflow has attempted). Beyond that, each round costs more than it saves vs running the implementation. The exit criterion: when one round's findings shift to mostly-factual and mostly-verifiable-by-grep, stop.

### Methodology that worked across Rounds 5 + 6 (preserve for future feature reviews)

- **Verify reviewer claims against actual code before encoding fixes.** Round 5 ran 5 parallel verification reads (cache.py, llm.py, batch_executor.py, llm_mock.py, instrumentation.py). Round 6 ran 5 parallel verifications too (apply_memo_hit callers grep, `_PROPAGATED_KEYS` content, DD#34 wording, `format_child_provenance` modification, post() error path). 100% of Round 6 reviewer claims were factually correct — the discipline pays off, but it requires actually doing the verification, not assuming.
- **Targeted reviews (5 → 4 agents) work for late rounds.** Skipping `review-plan` (Round 6) when architecture is closed cost nothing and saved one agent's runtime. Concurrency/feature-interactions/agent-ux were already closed by Round 2-3 — re-running them in Round 5+6 would have been pure overhead.
- **Mark dependent failures as `xfail` with surface-to-user message.** Round 6's V6 sub-workflow dedup test will fail on first run by design (`format_child_provenance` modifies message; identity tuple includes message; dedup breaks). Marking `@pytest.mark.xfail(strict=False)` with explicit reason locks the tripwire intent — without xfail, the implementing agent silently weakens or skips the test.
- **Phase-ordering dependencies between tests are real.** Round 6 caught that several B3.4 tests depend on C1.2 production code (`LLMNode.prep` rendering messages). Solution: skip-then-unmark pattern (`@pytest.mark.skip(reason="ships with C1.2")` at B3.4-merge, removed at C1.2-merge). Tests in the wrong phase fail-loud at merge — wastes implementing-agent time.

### Useful info for future agents (what to load-bear from Rounds 5 + 6)

1. **`core/cache_render.py` is the canonical home** for `_resolve_chunk_value`, `_resolve_static_prefix_for_cache`, `_CHUNK_ABSENT`. Lazy-imports `TemplateResolver` and `NodeStatus` from runtime. Three consumers (`plan_node.py`, `nodes/llm/llm.py`, `core/cache_analysis/analyze.py`) all import from there. Don't move it.
2. **`_make_serializable` defense fires at the rejection branch, NOT via sentinel `__repr__`.** The branch lives in `runtime/cache.py` (Round 5 added). Future agents touching `cache.py` must preserve this branch — without it, leaked sentinels silently produce stable-but-wrong cache hashes.
3. **`cache_chunks_skipped` flows through 4 wrap sites + 1 success path** (in `LLMNode`): `_call_llm` deterministic-error wrapper, `_call_llm` timeout wrapper, `exec_fallback` retry-exhausted wrapper, `post()` JSON-parse-error wrapper, and the success-path `post()` write. Plus persistence via `write_memo_cache` and round-trip via `apply_memo_hit`. If any one is missed, the trace channel silently degrades.
4. **F2 confidence aggregation is STRICT** (matches DD#34 line 634 verbatim — `all(src == "trace")`). If you change it to permissive, surface to user — it changes golden test fixtures.
5. **V6 sub-workflow dedup test fails on first run by design** — it's an `xfail` tripwire. Fix-shape decision is open: either granular dedup tuple (touches `Diagnostic` identity contract) or special-case per-id dedup (more fragile). User picks.
6. **Catalog has 12 entries; never hardcode the integer.** Always read `len(CACHE_WARNING_CATALOG.keys())` or `EXPECTED_CATALOG_COUNT`. Round-2 added 1, Round-3 added 2 — the count drifts.

### What's NOT load-bearing (don't waste time re-reading)

- The fix-by-fix list (already inline in the plan at the relevant phase section).
- The Round-1 / Round-2 / Round-3 architectural backbone arguments (`§31`, `§32`, `§33` — read only if you're considering an architectural change).
- The Round-4 V5/V6 fix-shape rationale (`§34` — read only if extending the catalog or modifying validator-reach behavior).

### Where things stand at session end

- Plan is 2104 lines, refined across 6 review rounds, no unmerged corrections.
- Architectural backbone: `CacheRenderContext` + frozen `CacheBlockIR` + `MappingProxyType` outer wrap + `_CHUNK_ABSENT` sentinel + shared `core/cache_render.py` helpers + 4-site error-path wrapping. All closed.
- 13 sub-phases, 12-entry warning catalog, ~50 enumerated tests. All concrete.
- Two open user decisions documented (F2 strictness; V6 dedup outcome). Both surface during their respective phase, not blocking.
- Three pre-authorized paid spikes (~$0.30) pending — run before B1.1.
- Stop criterion met for plan-stage review: bug class shifted to "verifiable by grep within 30 minutes of implementation." Switch to implementation-time review (`/code-review` after each phase merges).

### Next step

The implementing agent runs the three pre-authorized paid spikes, records outcomes as §36, updates plan sections per the Spike contingencies table if any spike contradicts encoded decisions, then begins B1.1. After each phase merges, run `/code-review` in code-review mode (7 agents, no `review-plan`) against staged changes — that's where the remaining bug class surfaces fastest.

The B3 baseline-fixture-before-B3.1-patches gate is the single load-bearing TDD-shaped catch. STOP if it fails.

## 36. Session 2026-04-29 — Pre-implementation paid spike outcomes

Three pre-authorized paid spikes (~$0.30 budget) executed before B1.1 per the agent-handoff and `starting-context/spike-runner-brief.md`. Each verifies an encoded plan decision; outcomes are recorded against the plan's "Spike contingencies" table at line 2057.

Total cost across all three spikes: **~$0.04** (well under the $0.30 budget — Anthropic's 1h cache-write was the dominant line item at ~$0.018, plus a Spike 1b disambiguator re-run that was needed to resolve telemetry-shape ambiguity).

### Spike 1 — Gemini explicit `cache_control` (`gemini/gemini-2.5-flash`, ~5000-token Lorem-Ipsum prefix)

**Scenario A (cachedContents fires under explicit cache_control):**
- A1 (cold): `cache_read_input_tokens: 4042`, `cached_tokens: 4042`. **No `cache_creation_input_tokens` field surfaces** — that key is entirely absent from LiteLLM's Vertex/Gemini telemetry, replaced by `cache_read_input_tokens` even on the first call.
- A2 (warm, exact byte match): `cache_read_input_tokens: 4042`, `cached_tokens: 4042`.
- **Telemetry shape ambiguity:** A1 showing reads-on-cold is consistent with either (a) LiteLLM's Vertex translation creating `cachedContents` as a side-effect and surfacing only reads (markers DO real work), OR (b) Gemini's implicit auto-cache firing regardless of markers (markers are silently no-op).

**Spike 1b disambiguator** — same prefix length (~5000 tokens), FRESH content (unique salt), NO `cache_control` marker:
- Cold call result: `cached_tokens: null`, `cache_read_input_tokens: null`, `text_tokens: 5258` (full prompt billed as fresh).
- **Conclusion: explicit `cache_control` IS doing real work.** Without the marker, no caching fires. With the marker, cache reads register on the first call. Interpretation (a) confirmed.

**Scenario B (multi-marker request — system + user-prefix):**
- B response: `cache_read_input_tokens: 5664` (covers both prefixes), no exception, no API error.
- Outcome: **CONFIRMS** — Gemini accepts both markers in the same request without error.

**Outcome — Scenario A: AMBIGUOUS leaning CONFIRM (telemetry shape diverges from encoded verification criteria, but disambiguator proves marker is functional).**
**Outcome — Scenario B: CONFIRMS.**

**Plan updates applied:**
- F2 `analyze.py` Gemini-detection branch (per Spike contingencies table for Scenario A): added an info-note documenting that `cache_creation_input_tokens` will be 0/absent on Gemini even when caching is working perfectly, because LiteLLM's Vertex translation surfaces only reads. Verification path is `cache_read_input_tokens` (or `prompt_tokens_details.cached_tokens`) on subsequent calls. C2 emission code unchanged.

**Files written:**
- `scratchpads/task-159-spike-1.py` + `task-159-spike-1-output.txt`
- `scratchpads/task-159-spike-1b.py` + `task-159-spike-1b-output.txt` (disambiguator)

### Spike 2 — OpenAI `prompt_cache_key` parallel-batch routing (`openai/gpt-4o-mini`, ~2000-token prefix, N=6 parallel)

**Protocol:** warm-up call (cached=0), 2-second pause, 6 concurrent calls with same `prompt_cache_key`.

**Results:**
- Warm-up: `prompt_tokens_details.cached_tokens: 0` (cold, as expected).
- Parallel call 0: `cached_tokens: 1024`
- Parallel call 1: `cached_tokens: 1024`
- Parallel call 2: `cached_tokens: 1024`
- Parallel call 3: `cached_tokens: 1024`
- Parallel call 4: `cached_tokens: 1792`
- Parallel call 5: `cached_tokens: 1792`
- **Cache hits: 6/6.** Wall-clock: 1.90s for the parallel batch.

**Outcome: CONFIRMS encoded decision.** OpenAI's sticky routing reliably clusters parallel calls on the same backend after warm-up. The cached-token chunking variation (1024 vs 1792) is OpenAI's documented prefix-granularity behavior — all 6 calls register meaningful cache hits.

**Plan updates applied:** None. C3 + D.2 emission code stands.

**Files written:**
- `scratchpads/task-159-spike-2.py` + `task-159-spike-2-output.txt`

### Spike 3 — Anthropic per-TTL pricing precision via `litellm.completion_cost()` (`anthropic/claude-sonnet-4-5`, ~2000-token prefix)

**Protocol:** Two cache-write calls — first with default 5-min TTL (no `ttl` key), second with `ttl: "1h"` and the `anthropic-beta: extended-cache-ttl-2025-04-11` header.

**Results:**
- 5m write: `cache_creation_input_tokens: 3043`, `ephemeral_5m_input_tokens: 3043`, `ephemeral_1h_input_tokens: 0`. `completion_cost` = **$0.01153725**. Math check: 3043 × $3/M × 1.25 + 6 output × $15/M ≈ $0.01151 ✓ (LiteLLM correctly applies 1.25× multiplier).
- 1h write: `cache_creation_input_tokens: 3060`, `ephemeral_5m_input_tokens: 0`, `ephemeral_1h_input_tokens: 3060`. `completion_cost` = **$0.00009600**. Math check: this is approximately just `4 output × $15/M ≈ $0.00006`. **The entire 1h cache-write cost is missing from LiteLLM's pricing.**
- Ratio (1h / 5m) = **0.0083** — should have been ~1.4–1.7 for "distinguishes per-TTL" or ~1.0 for "treats writes equivalently." 0.0083 means LiteLLM completely fails to price `ephemeral_1h_input_tokens`.

**Outcome: CONTRADICTS encoded decision (more severely than expected).** Plan E.1's trust in `litellm.completion_cost()` is misplaced for 1h-TTL cache writes — those events are silently undercounted by ~100×.

**Plan updates applied:**
- Plan E.1 (line 1444 — Phase E goal paragraph): replaced the "Cost reporting unchanged — LiteLLM normalization in `llm_client.py:776–784` already handles the cache token counts. v1 trusts `litellm.completion_cost()` for per-TTL pricing distinction." sentences with a normalization-override directive: when the response usage carries `ephemeral_1h_input_tokens > 0`, override `cost_usd` by computing the 1h-write cost from raw token counts × per-provider 1h rate (2× base input rate) + non-1h portions priced via LiteLLM. Anchor lives in `llm_client.py:776–784`.
- Spike contingencies table (line 2066): annotated the row to record that the contingency fired (severity: 1h cost ≈ output-only, ratio 0.0083) and link the §36 detail.

**Files written:**
- `scratchpads/task-159-spike-3.py` + `task-159-spike-3-output.txt`

### Cost summary

| Spike | Calls | Approx cost |
|---|---|---|
| Spike 1 (A1, A2, B) | 3 Gemini calls, 2 cached, 1 mostly-cached | ~$0.0006 |
| Spike 1b (disambiguator) | 1 Gemini cold call | ~$0.0004 |
| Spike 2 (warm + 6 parallel) | 7 OpenAI calls, 1 cold + 6 cached | ~$0.002 |
| Spike 3 (5m write + 1h write) | 2 Anthropic calls (both cache writes) | ~$0.030 |
| **Total** | 13 paid calls | **~$0.04** |

### Net effect on plan

- **One critical correctness fix** (E.1 — 1h cost normalization override). Without this, every 1h-TTL cache-write event in production would be silently undercounted, defeating the cost-prediction contract.
- **One observability enhancement** (F2 Gemini info-note). Helps `analyze-cache` users interpret Gemini's reads-only telemetry shape correctly.
- **Two clean confirmations** (Scenario B multi-marker, OpenAI parallel routing).

### Next step

B1.1 implementation can now proceed. The implementing agent reads §36 to confirm spike outcomes; the two plan updates above are already encoded in the plan. No further pre-implementation gating remains.
