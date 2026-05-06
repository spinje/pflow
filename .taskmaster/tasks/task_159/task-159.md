# Task 159: Prompt Caching via Declarative `## Cache` Block

## Description

Add provider-level prompt caching to pflow workflows: a new `## Cache` top-level section in `.pflow.md` for declarative cross-call context reuse, a per-node `prompt_cache:` opt-in field, auto batch-prefix caching gated on `prewarm:`, and `pflow analyze-cache` as the agent-facing diagnostic. Cache rendering happens at the existing pflow-owned LiteLLM adapter seam (`src/pflow/core/llm_client.py`) introduced in Task 158. Estimated input-cost reduction on LLM-heavy workflows: 50–70% per run, 80%+ on reruns within TTL. Motivating case: the `lyrics-generator` pipeline (`/Users/andfal/projects/music-generation/workflows/lyrics-generator/`) with ~181 LLM calls per run, of which a handful of large stable context objects flow through ~15 sequential calls per song path × 4 parallel songs.

## Status

not started

## Priority

high

## Prerequisites

**Depends on Task 158 (LiteLLM migration) — must be merged first.** Task 158 replaced Simon Willison's `llm` library with a pflow-owned LiteLLM adapter (`src/pflow/core/llm_client.py`) and built the typed-exception + diagnostic pipeline this task plugs into. That migration was originally Phase 0 + Phase A of this task; it became its own task once the architectural scope crystallized (typed exceptions, diagnostic-driven error pipeline, tracing redesign, performance work — all needed before cache rendering could land cleanly). The cache-rendering work here lives at the adapter seam Task 158 created.

## Problem

pflow workflows that chain many LLM calls pay for the same context tokens repeatedly. The library substrate for caching is now in place (Task 158 — the pflow-owned LiteLLM adapter speaks `cache_control`); what's missing is the workflow-level surface to declare and render those caches:

1. **Intra-batch redundancy.** Batch fan-outs (e.g., `analyze-source` 6 specialists × N sources, `chorus-chooser` 8 chorus-gens + 34 scorings) send the same stable prefix to every call, with only per-item tails differing. The adapter accepts `cache_control` but pflow has no declarative way to say "this prefix should cache."
2. **Cross-call redundancy within a pipeline.** In `song-creator`, outputs from `creative-direction`, `song-architecture`, `easter-eggs`, and `concept_brief` flow through 15+ downstream LLM calls — `write-lyrics`, emotional/craft reviews, rewrite stages, suno-prompt generation. Each downstream call re-pastes 8–12k tokens of content it already produced.
3. **Agents cannot reason about cache.** Even if an author wanted to structure prompts for cacheability, there is no feedback loop telling them which calls share prefixes, which prompts have dynamic content high-up (breaking the cache), or how much money is being left on the table.

For the lyrics-generator specifically, back-of-envelope per-run input-cost reduction is 50–70% with a well-declared cache, and 80%+ on reruns within 1h TTL — meaningful money at the scale users iterate at.

## Solution

Two tightly-coupled changes, shipped together because neither provides value alone:

**1. `## Cache` block syntax for declarative cross-call caching.** A new top-level section in `.pflow.md`, alongside `## Inputs` / `## Steps` / `## Outputs`. Contains a `` ```cache `` code block with prose interleaved with `${var}` references — prose above each variable travels into the rendered system message as the cacheable label. Each workflow file (including sub-workflows) declares its own block scoped to its own inputs and step outputs. Individual LLM nodes opt in by listing a subset via a new `- prompt_cache: [name1, name2]` field (where names are the bare template paths, e.g., `concept`, `creative-direction.response`). Order matches the declaration block strictly; violation is a hard error. The existing `- cache: bool` field (per-node memoization opt-out — different cache layer) is untouched. See the **Syntax Specification** in Implementation Notes.

**2. `pflow analyze-cache` command for agent feedback.** Static analysis of a workflow's cache plan: per-node cache ratio, shared context candidates, warnings with concrete fixes, optional prefix-padding advisories, and a `--from-trace` mode that compares predicted cache behavior to actual cache hit/miss data from runtime traces. Output has a human-readable default and a `--format=json` for agent consumption with stable warning IDs. A shared `cache_analysis.summarize()` helper emits a one-line nudge in `pflow run --dry-run` output when actionable opportunities exist.

**Auto batch-prefix caching** runs alongside the declared cache (gated on `prewarm: true` per Design Decision 9), detecting the stable prefix of a batch prompt (text before the first `${item.X}`) and inserting a `cache_control` marker. Bytes sent to the LLM are identical to what the author wrote. Visible in analyze-cache output.

**Substrate (Task 158, already in place):** the pflow-owned adapter at `src/pflow/core/llm_client.py` accepts `cache_control` content blocks via LiteLLM's unified surface — Anthropic directly, Gemini translated to `cachedContents`, no-op on OpenAI (which caches automatically). The typed exception hierarchy and structured `Diagnostic` pipeline this task emits validation errors into are also in place from Task 158.

## Design Decisions

1. **(Resolved by Task 158 — LiteLLM migration.)** The library substrate decision (LiteLLM via pflow-owned adapter at `src/pflow/core/llm_client.py`) is settled and shipped. Original rationale: the `llm-anthropic==0.25` plugin's `cache: bool` only marked `cache_control` on attachments / last prior user message, not system prompts or first-turn user content; `llm.models.Options` was `extra="forbid"`. LiteLLM's unified `cache_control` syntax (Anthropic native, Gemini→`cachedContents`, no-op on OpenAI) was the chosen substrate. See Task 158 for the full migration story.

2. **Explicit `## Cache` declaration, not silent restructuring.** Autodetecting "this value is reused, let me lift it out of the prompt file into a cacheable system prefix" would silently change the message structure the LLM receives. Even though the content bytes would be identical, the message assembly pattern differs (inline prose vs. structured system blocks). pflow's existing philosophy is explicit, visible workflow syntax — caching follows that. The author declares what's cached; pflow renders what was declared.

3. **Prose-above-variable maps to rendered prefix.** Inside the `` ```cache `` block, prose between `${var}` references travels verbatim into the system message alongside the value. The author writes what the LLM will see; no hidden labels are injected, no framing is rewritten. The block is a faithful render preview.

4. **Per-node references use bare names derived from the template path.** `${concept}` becomes `concept`; `${chorus-chooser.winning_chorus}` becomes `chorus-chooser.winning_chorus` as a bare string identifier. Nodes reference via `- prompt_cache: [concept, concept_brief, chorus-chooser.winning_chorus]`. No `[name]` markers inside the cache block are needed — each chunk has exactly one `${var}`, and stripping `${}` gives the chunk's identifier. Reads as "reference named cache chunks," not "substitute values into this list."

5. **New field named `prompt_cache:`, not `cache:`.** The existing `cache: bool` field is already reserved for per-node **memoization opt-out** (pflow's local cache layer). It is used in 7 example workflows, 14 test files, 5 CLAUDE.md files, the agent guide, and 3 user-doc pages. Overloading it to also mean "LLM provider prompt-cache subset" would create a field with two shapes (bool OR list) and two unrelated meanings. `prompt_cache:` is unambiguous (matches Anthropic/OpenAI/Gemini terminology), keeps the two cache layers visually distinct, has zero backwards-compat impact on existing workflows, and makes agent-authored workflows self-documenting.

6. **Strict order validation — error on wrong order.** Prefix-based caching requires calls that share context to present items in identical order. pflow enforces declaration order rigidly: a node's `prompt_cache:` list out-of-order is a hard error with a clear fix message showing both the declared and the wrong ordering. pflow never silently reorders. The workflow file is the honest source of truth for what the LLM will see.

7. **Block-level TTL, not per-item.** Single `- ttl: 1h` on the `## Cache` section covers all realistic cases. Per-item TTL would add complexity for a marginal optimization that's easier to chase by adjusting workflow structure. Default TTL is the provider default (typically 5 min); extended TTL is opt-in because it costs 2× on writes and only pays off with ≥3 reads.

8. **No auto-optimization for reruns.** Extended TTL (1h) is never auto-applied. Rerun benefits cost money on first-write; that tradeoff is the author's to make, not pflow's.

9. **Auto batch-prefix caching is gated on `prewarm: true`.** Within a batched LLM call, pflow can detect the stable prefix before the first batch-scoped reference and insert a `cache_control` marker. Without pre-warming, all N calls write the cache simultaneously — no savings, just overhead. So auto-batch-prefix is only applied when `prewarm: true` is explicitly declared (which serializes the first call, then fans out the remaining N-1 in parallel as cache reads). When prewarm savings would be material, `pflow analyze-cache` and `pflow run --dry-run` surface the recommendation as `cache.batch-prewarm-recommended`. **`pflow run` itself does NOT block** on this — analytical findings never gate execution (DD#36). Tiering is by savings ratio (DD#33), NOT by arbitrary size/token thresholds. Declared `## Cache` references whose prefix was written by earlier non-batch nodes still apply to batches at read cost — independent of prewarm.

10. **Prefix padding is advisory, never auto-applied.** When a node's `prompt_cache:` subset doesn't start at position 1 of the master order, it doesn't cache-hit upstream writes. Extending the subset to include earlier items can unlock prefix hits at the cost of sending extra content at 0.1× read rate. pflow computes whether padding is net-positive per node and surfaces it as an **optional recommendation** in analyze-cache output. The author decides; pflow never modifies the workflow.

11. **Per-call breakpoint strategy: one `cache_control` marker per distinct subset end, in v1.** Within a call, pflow places one `cache_control` marker at the end of the rendered cache content. The whole subset caches as one entry. Calls with identical subsets cache-hit each other; calls with different subsets get independent cache entries. This uses 1–2 markers per call (with batch auto-prefix adding one more), well within Anthropic's 4-marker limit. Fine-grained multi-breakpoint placement for partial-prefix sharing is deferred to a follow-up if real usage shows demand.

12. **Sub-workflows declare their own `## Cache` block.** Each `.pflow.md` file is self-contained: its cache block references its own inputs and step outputs. This enables sub-workflows to run standalone with caching. Cross-workflow cache hits happen incidentally at the byte level when rendered prefixes match — pflow does not coordinate caching across workflow boundaries. For this incidental hit to fire, parent and child should use identical prose labels for the same logical values.

13. **Deterministic serialization of cached values.** Complex values (dict, list) serialize via sorted-key JSON with stable formatting. Without this, two calls with the "same" concept could produce different cached bytes (dict key ordering) and silently miss cache. One-line fix, prevents a whole class of silent failures.

14. **(Resolved by Task 158 — tracing redesign.)** The monkey-patch of `llm.get_model` is gone; tracing now flows through `shared["__trace_collector__"]` save/restore around `engine.run`, with the adapter calling `collector.get_trace_hook(node_id)` returned by `WorkflowTraceCollector`. This task does not touch tracing further except for the trace-format 2.1.0 cache-metadata additions (see Trace Format requirements below).

15. **(Resolved by Task 158 — reasoning options map.)** `model.Options.model_fields` introspection replaced by `src/pflow/core/llm_reasoning_map.py` (explicit provider/model → reasoning-kwarg map; Anthropic Opus 4.5 `thinking_effort` precedence preserved).

16. **(Resolved by Task 158 — key discovery.)** Env vars only via `inject_settings_env_vars` and `os.environ`; `llm keys` subprocess deleted. Direct read of legacy `~/.config/io.datasette.llm/keys.json` is a deferred follow-up (not implemented in Task 158; users migrate keys manually via `pflow settings set-env`).

17. **Verification tier strategy: ship Tier 1 (static in-file) + Tier 3 (trace-based) in v1; Tier 2 (cross-workflow prediction) is a planned follow-up.** Tier 1 catches all in-file correctness issues cheaply. Tier 3 is the source-of-truth using actual provider-reported cache data from runtime traces. Tier 2 (predicting cross-workflow cache hits before running) requires cross-file graph analysis and prose-label comparison — valuable but not required for the feature to be useful.

18. **Pre-warming for batches is opt-in via `prewarm: true`.** Semantics: serialize the first call, wait for completion (cache write), then fan out the remaining N-1 calls in parallel at read cost. Trades ~one call's latency for 5–10× cost reduction on the remaining calls. Default off (latency preservation). When prewarm savings would be material, `pflow analyze-cache` and `pflow run --dry-run` emit `cache.batch-prewarm-recommended` (warning severity, advisory only) — never blocks `pflow run` (DD#36). Triggering is savings-ratio based per DD#33, NOT absolute size/token thresholds. Without an explicit `prewarm:` decision and savings-ratio < 5%, pflow skips silently.

19. **`prompt_cache` rendered content must be in `compute_node_config`, conditionally.** The memo-cache hash (`runtime/engine/instrumentation.py:140-179`) determines which cached output is served. If `prompt_cache` content prepends to the system message at runtime but is NOT in the hash, existing cache entries hit for upgraded workflows and serve outputs produced WITHOUT the prepended content — a silent correctness bug. Fix: thread the rendered `prompt_cache` content into `compute_node_config` **conditionally** (only when `prompt_cache` is non-empty) so nodes that don't opt in retain their existing hash. Precedent: `batch_config` is added the same conditional way (Task 96).

20. **Cache validation lives in the shared `core/workflow/data_flow.py::validate_data_flow()` module.** pflow has two validation entry points — `WorkflowValidator.validate()` (save-time + pre-execution) and `runtime/compilation/compile_validation.py::_prepare_compilation()` (compile-time) — both of which already call the shared `data_flow.py`. Putting cache reference validation there means both entry points pick it up for free. Schema-level structural rules (cache block shape, required fields) go into `core/ir_schema.py::FLOW_IR_SCHEMA` which both entry points also gate on. No duplicate validator code.

21. **ClaudeCodeNode is out of scope.** `src/pflow/nodes/claude/claude_code.py` uses `claude_agent_sdk` directly (not the `llm` library), and the SDK handles Anthropic prompt caching transparently — cache tokens already appear in `llm_usage` (`claude_code.py:865-887`). Task 158 does not need to touch ClaudeCodeNode. If cache-control user parameters for Claude Code are wanted, that is a separate task.

22. **Trace format bumped to 2.1.0.** The `analyze-cache --from-trace` feature benefits materially from cache metadata that today's format 2.0.0 doesn't carry. New fields: `event["cache_key"]` on cache-hit and cache-write events (for exact SQLite correlation), `event["cache_source"]: "memo" | "in_process"` (distinguishes the two pflow cache layers — distinct from LLM-provider cache), `event["cache_age_sec"]` on cache-hit events (for TTL analysis), `trace["workflow_path"]` at the top level (for cross-trace correlation). For inline workflow runs, `workflow_path` carries the synthetic `"ir-hash:<md5>"` identifier produced by `_synthesize_inline_workflow_id` (`runner.py:36-53`) — symmetric with how `MemoizationCache.workflow_path` already scopes inline-run rows. `format_version` → `"2.1.0"`. The existing consumer gate `format_version.startswith("2.")` is forward-compatible, so 2.0.0 readers keep working on 2.1.0 files (ignoring the new fields).

23. **Dual-mode mock — fully in place from Task 158.** `MockLLMClient` exposes both `call_history` (truncated to 500 chars, default for legacy tests) and `call_history_full` (untruncated, `tests/shared/llm_mock.py:105`, populated unconditionally on every call). Phase B/C cache-structure tests read `call_history_full`. NO mock-infrastructure work required for Task 159 — this DD is informational only.

24. **MCP parity with existing `plan_workflow` pattern.** `pflow analyze-cache` as a CLI command means an equivalent `analyze_cache(workflow, parameters)` method on `mcp_server/services/execution_service.py` and `@mcp.tool()` registration in `mcp_server/tools/execution_tools.py`. Task 152 (MCP parity) is the governing invariant: "every shared formatter has two call sites."

25. **`--dry-run` cache nudge via shared analysis module.** The `cache_analysis` module exposes two entry points: `analyze()` (full plan for `pflow analyze-cache`) and `summarize()` (one-line nudge for `--dry-run` footer). `summarize()` emits a `Severity.INFO` `Diagnostic` that the existing `plan_formatter.py` loop (`plan_formatter.py:139-142`) already renders; no new formatter code is needed. Nudge is silent when the cache is already optimal.

26. **Tier 2 (cross-workflow analysis) is in-by-default.** The earlier framing ("deferred to v1b follow-up") is overridden after code investigation showed the substrate (sub-workflow resolver, recursive walkers, input-mapping IR shape) is in place. A new ~50 LOC walker in `core/cache_analysis/cross_workflow.py` mirrors the mermaid renderer's traversal pattern (`core/workflow/mermaid/_render.py:50-130`). Per-feature exclusion criterion: a Tier 2 sub-feature is deferred only if (a) it requires structural refactor of existing modules OR (b) the algorithm has no clearly right answer (would risk false-positive warnings). v1 ships rename-detection and prose-mismatch warnings; cross-workflow auto-fix suggestions are deferred under criterion (b) — picking which prose canonicalizes has no obvious right answer.

27. **Stable warning IDs are first-class top-level field on `Diagnostic.id`.** Not nested in `context["warning_id"]`. Top-10% diagnostic systems (mypy, rustc, ruff, eslint, clippy, TypeScript) all use top-level IDs; they're load-bearing for filtering, suppression, and identity-based dedup. Cache analysis is the first user; future categories benefit from the same convention. Identity tuple updates from `(severity, source, node_id, message)` to `(severity, source, node_id, id or message)` — when `id` is present it's the dedup key.

28. **No `FixAction` typed structure in v1.** Existing `suggestions: list[str]` carries prose fix hints; existing `context: dict` carries raw structured data. Pattern follows mypy (analyzer without auto-fix), not rustc / ruff / eslint (which auto-apply). `FixAction` substructure is justified only when programmatic fix application ships — that's deferred to v1b along with `pflow cache apply`. Until then, structure-without-consumer is overengineering. The `description` field of a hypothetical `FixAction` overlaps entirely with `suggestions[0]`; the typed `action` enum and `applicability` classification have no v1 consumer.

29. **Closed warning ID catalog of 13 entries for v1** (started at 10 from spec; +cache.discrepancy from Round 2; +cache.invalid-on-non-llm and cache.prewarm-no-prefix from Round 3; +cache.consolidate-to-root-recommended from CP3 / lyrics-generator Stage 1 verification). Adding new IDs goes through design review. Keeps the agent-facing API stable and prevents ID-namespace drift. Catalog covered in the `Stable Warning ID Catalog` requirements section.

30. **Four-level per-call confidence labeling, three-level aggregate.** Per-call: `trace` (from JSON trace file, richest — only path that gets discrepancy analysis) / `memo` (from `MemoizationCache` prior `llm_usage`) / `estimator` (from `litellm.token_counter()`) / `heuristic` (`len(text) // 4` fallback). Aggregate: `high_from_trace` / `medium_from_memo` / `low_no_data`. Replaces an earlier sloppier scheme that conflated trace files and `MemoizationCache` history under one label — DD#34 separates them properly.

31. **Token estimation tier order.** Greenfield analysis uses `litellm.token_counter(model, text)` — already transitively installed via LiteLLM, model-aware, offline, ±5% accurate. Run history uses `MemoizationCache.get_latest_for_node()` to read prior `llm_usage.input_tokens` from the cached output blob. Character heuristic (`len(text) // 4`) is a last-resort fallback when both fail (unknown model + no history); it's the only place pflow uses a char-based heuristic and is tagged in confidence labeling so agents see when they're getting low-fidelity numbers.

32. **Per-model capabilities table is a new module.** Phase B introduces `core/llm_capabilities.py` with hardcoded per-model min-cache-token thresholds. Anthropic minimums are version-specific (Anthropic prompt-caching docs, April 2026; see progress log §30):
    - Sonnet 4.5, Opus 4.1, Opus 4, Sonnet 4, Sonnet 3.7: **1024**
    - Sonnet 4.6, Haiku 3.5: **2048**
    - Opus 4.7, Opus 4.6, Opus 4.5, Haiku 4.5: **4096**

    Gemini Pro/Flash: 1024 implicit / 4k explicit. OpenAI: 1024 (auto-cache threshold). LiteLLM's `model_cost` dict carries `supports_prompt_caching` but per-model min-token coverage is uneven; v1 hardcodes; v1.x may wrap LiteLLM. Fallback for unknown models: conservative floor 4096 recommended (plan-writer locks exact value).

33. **Prewarm thresholds are savings-ratio-based, not size-or-token-based.** Earlier framing ("size > 10 AND prefix > 2k tokens") used arbitrary proxies. Replaced with a savings-ratio rule: compute `savings_ratio = (N-1) × 1.15 × P / (N × (1.25P + D))` where `P` = static prefix tokens, `D` = dynamic suffix tokens. Ratio captures the structural property "what fraction of this batch is actually cacheable" — naturally scales with prefix-to-total ratio AND batch size N. Two-tier triggering: < 5% silent skip; ≥ 5% emits `cache.batch-prewarm-recommended` (warning severity, advisory only — see DD#36). The single warning carries `context.savings_pct` and `context.savings_usd` so agents reason about magnitude themselves. No absolute dollar floor: small absolute savings compound across reruns, and pflow can't predict run frequency.

34. **Trace data is auto-loaded when available — 2.1.0 traces only.** `pflow analyze-cache` automatically loads the most recent matching 2.1.0 trace from `~/.pflow/debug/` by matching `trace["workflow_path"]` against the analyzed workflow's resolved path (or `ir-hash:<md5>` for inline). 2.0.0 traces lack `workflow_path` and are ignored by auto-load — agents pass `--from-trace <path>` to use a 2.0.0 trace explicitly. `--no-trace` opts out entirely (useful for pre-optimization estimates / before-after comparison). Rationale: filename-based matching has collision risk via the 30-char-truncated-stem sanitizer (`workflow_trace.py:473-486`); requiring the new format for auto-load is cleaner and 2.1.0 traces accumulate fast in practice. Per-call `data_source` labels expand to four values: `trace` (from JSON trace file, richest — only path with discrepancy analysis), `memo` (from `MemoizationCache` prior `llm_usage`), `estimator` (from `litellm.token_counter`), `heuristic` (char count fallback). Aggregate confidence: `high_from_trace` / `medium_from_memo` / `low_no_data`. Replaces the earlier 3-level scheme that conflated trace files and `MemoizationCache` history under one label.

35. **`analyze-cache` inputs are optional.** Workflow inputs from the `## Inputs` section (e.g., `sources='[...]'` for lyrics-generator) are NOT required to run analysis. Most analysis paths (cache-block parsing, Tier 2 walking, shared-context detection) don't depend on input values. Token estimation falls back to lower-fidelity sources (`memo` → `estimator` → `heuristic`) when input substitution can't fully resolve a prompt. Confidence labels reflect the degradation. Required inputs that are absent emit a single info note in the output, not an error.

36. **Three-tier validation/analysis architecture; analytical findings never block `pflow run`.** Three distinct paths with different speed budgets and emission scopes:
   - **`pflow run` validation (always, fast, deterministic).** Structural cache checks only — parser-level, IR reference resolution, declaration-order match, unused-chunk detection. No tokenizer, no historical state, no I/O beyond reading the workflow file. Blocks on structural errors (`cache.order-mismatch`, reference-resolution failures) — those are correctness bugs.
   - **`pflow run --dry-run` (opt-in, can be slow).** Structural checks + full analytical pass: token counting via `litellm.token_counter`, historical state via `MemoizationCache`, savings ratio computation, Tier 2 cross-workflow walking. Emits the one-line `cache.opportunities-available` nudge with real numbers. Doesn't block (no execution to gate).
   - **`pflow analyze-cache` (dedicated, slow OK).** Same analysis as `--dry-run`, full sectioned output (text or JSON), `--from-trace` discrepancy mode.
   Rationale: validation must stay fast and deterministic so `pflow run` doesn't load tokenizers or read historical state. Analytical findings are advisory — agents who care run `analyze-cache` or `--dry-run` first; agents who skip both run unhindered. Aligns with mypy / ruff / pylint pattern (analysis is opt-in). The forcing-function effect of "agent must declare prewarm" relies on agents seeing the warning; if they skip both opt-in paths, default behavior (no prewarm, parallel writes) is documented as legal-but-suboptimal.

37. **OpenAI extended cache retention via `prompt_cache_retention`.** OpenAI's auto-cache exposes `prompt_cache_retention` accepting `"in_memory"` (default; 5–10 min idle, max 1h) or `"24h"` (extended via GPU-local-storage offload). Pflow maps `- ttl:` to this two-bucket vocabulary: omitted/`5m` → no parameter (default `in_memory`); `- ttl: 1h` → `prompt_cache_retention: "24h"`. The 24h overshoot is intentional — `in_memory`'s 5–10 min idle expiry would silently violate the user's `1h` opt-in (per DD#2's "no silent behavior changes" principle). See progress log §30 for verification.

## Dependencies

- **Task 158 (LiteLLM migration) — must be merged first.** Provides the pflow-owned adapter (`src/pflow/core/llm_client.py`), the typed-exception hierarchy (`LLMCallError` and subclasses), the diagnostic pipeline (`_FAILURE_CATEGORY_MAP` + `_diagnostic_context`), the trace-collector seam (`shared["__trace_collector__"]` + adapter `trace_hook`), and the cost-from-LiteLLM contract this task plugs into.
- Task 156 (`--dry-run`) is orthogonal but synergistic — both involve pre-run cost modeling. `pflow analyze-cache` shares the planner's `MemoizationCache.get_latest_for_node()` for size estimates on upstream LLM outputs.
- Task 108 (Smart Trace Debug Output) defined trace format 2.0.0. This task bumps to 2.1.0; the existing `format_version.startswith("2.")` consumer gate keeps 2.0.0 readers compatible.

Related but explicitly out of scope:

- Task 121 (Workflow Testability) — complementary, not blocking.
- Task 133 (Unified Per-Node Storage for Trace and Cache) — may interact with how cache metadata is stored in traces; coordinate during implementation but do not block.
- Task 152 (MCP Server CLI Surface Parity) — defines the parity invariant this task must respect.

## Requirements

> **Library substrate (Task 158, already in place):** the pflow-owned LiteLLM adapter at `src/pflow/core/llm_client.py::complete()` accepts `cache_control` content blocks via LiteLLM's unified syntax. Typed exceptions (`LLMCallError` and subclasses) and the structured `Diagnostic` pipeline this task emits validation errors into are also done. This task builds on top of that surface — see Task 158 spec/progress log for the migration details.

### `## Cache` Block Parsing

- New top-level section `## Cache` recognized by the markdown workflow parser, integrated into the existing section-type machinery alongside `## Inputs` / `## Steps` / `## Outputs`.
- Optional `- ttl: <duration>` parameter on the section (`5m` default; `1h` extended; reject other values in v1).
- Contains a tagged `` ```cache `` code block; multiple cache code blocks in one section are a syntax error.
- The `cache` code block content is a sequence of `[prose block][${var} reference]` pairs. Prose between variables, prose before the first variable, and the variable itself are rendered as a single content chunk.
- **Exactly one `${var}` per chunk.** Two or more `${var}` in a chunk is a syntax error (prose should describe its value, not contain further template references).
- Each `${var}` must resolve to a valid workflow input or upstream step output in the containing workflow file (reference resolution, same rules as existing templates).
- References that vary across calls referencing the same chunk are a syntax error. In practice this means batch-scoped references (`${item.X}` and any descendants) are rejected. Workflow inputs, step outputs (including aggregate batch outputs like `${batch-node.some_field}`), and indexed accesses that resolve to stable values are valid.
- Empty cache block is a syntax error (must have ≥1 variable).
- Prose-only cache block (no variables) is a syntax error.
- Cache chunk identifier = stripped template path. `${concept}` → `concept`; `${chorus-chooser.winning_chorus}` → `chorus-chooser.winning_chorus`. Duplicate identifiers (same `${var}` appearing twice) is a syntax error.
- New top-level IR field `cache` added to the workflow JSON schema (top-level `additionalProperties: False` means the schema must be extended explicitly). Shape: `{"cache": {"type": "object", "properties": {"ttl": {"enum": ["5m", "1h"]}, "items": {"type": "array", "items": {...}}}}}`.
- `_source_line` metadata injected on the cache block and on each chunk for error-rendering, following the existing source-line pattern for tagged code blocks.

### Per-Node `prompt_cache:` Field

- New node parameter `- prompt_cache: [name1, name2, ...]` accepted on `type: llm` nodes.
- Names are bare strings matching cache chunk identifiers (stripped template paths). Examples: `concept`, `concept_brief`, `creative-direction.response`, `chorus-chooser.winning_chorus`.
- Items must be a subset of the containing workflow's `## Cache` block items (error if referencing an undeclared name).
- Order of items in `prompt_cache:` must match declaration order in `## Cache`. Out-of-order is a hard error with a fix message showing both orderings.
- Absence of the `prompt_cache:` field means "no declared cache" — the node runs with no cross-call caching context (intentional isolation, e.g., `review-stranger-summary` pattern).
- Empty list `- prompt_cache: []` is valid and equivalent to absence.
- Per-node inline cache is NOT supported in v1 — everything cacheable goes in the master `## Cache`.
- New per-node `prewarm: bool` field accepted on `type: llm` nodes with a `batch:` config. `true` = serialize-first-then-fan-out with auto-batch-prefix marker; `false` = fan out all N immediately, no auto-batch-prefix; absent = treated as false. When absent and the savings ratio is material (see Auto Batch-Prefix Caching), `pflow analyze-cache` and `pflow run --dry-run` surface `cache.batch-prewarm-recommended` as advisory; `pflow run` itself never blocks on this.
- IR schema extended (per-node): add `prompt_cache: {"type": "array", "items": {"type": "string"}}` and `prewarm: {"type": "boolean"}`. Per-node `additionalProperties: False` means both must be added explicitly.
- Existing `cache: bool` field remains unchanged in schema and semantics. The two fields coexist on the same node.

### Cache Rendering into LLM Calls

- Cache rendering happens inside the pflow-owned adapter before it calls `litellm.completion(...)`. The adapter is called from `LLMNode._call_llm` (lines 332–390 post-Task-158) after kwargs build, before the API call — inside the ThreadPoolExecutor timeout budget and inside the retry loop (transient errors re-raise via `LLMTransientError` and reach the Node retry loop; deterministic errors short-circuit and don't retry).
- **`complete()` signature extension: widen `system: str | None` to `system: str | list[ContentBlock] | None`.** Today's `_build_messages()` (`llm_client.py:579-602`) already accepts scalar-or-list-of-blocks for the **user** message content (when attachments are present); widening `system` mirrors the existing pattern. The line `messages.append({"role": "system", "content": system})` works unchanged for both shapes — LiteLLM accepts either. Mirrors LiteLLM/Anthropic SDK/OpenAI SDK convention. Trivially extensible to future markers (multi-breakpoint, tools). Rejected alternative: a separate `cache_blocks` parameter — invents a parallel channel that has to be reconciled with `system` inside `_build_messages`.
- For each LLM node with a declared `prompt_cache:` list, pflow renders the cache content as a system-message prefix:
  - One content block per `[prose + ${var}]` chunk, in declaration order filtered to the node's subset.
  - Anthropic/Gemini: a `cache_control: {type: ephemeral}` marker on the final chunk (v1 single-breakpoint strategy).
  - OpenAI: content is the prefix; no markers needed. **Emit** `prompt_cache_key = hashlib.md5(_deterministic_json(rendered_cache_content).encode()).hexdigest()` whenever the node has a non-empty `prompt_cache:` subset — mirrors `compute_config_hash` (`runtime/engine/instrumentation.py:173-178`) and the project's MD5-for-content-identity convention (`runtime/cache.py:85,111,344`, `runner.py:52`). Sticky-routes requests sharing the key to the same backend, improving hit rate on parallel batch fan-out (verified — see progress log §30). **Soft cap caveat:** ~15 RPM per backend per prefix; bursts above that overflow to additional machines (graceful degradation — first 15 hit cache, remainder pay write cost). For batches N > 15, expect degraded but non-zero hit rate.
- **TTL wire-format translation per provider.** pflow's workflow-facing TTL is uniform (`- ttl: 5m` or `- ttl: 1h`); providers each have different wire formats and accepted values, so the adapter translates before emission:

  | Workflow `- ttl:` | Anthropic wire | Gemini (Vertex) wire | OpenAI |
  |---|---|---|---|
  | (omitted) | `cache_control: {type: ephemeral}` (5 min provider default) | `cache_control: {type: ephemeral}` (provider default) | no `prompt_cache_retention` (default `in_memory`, 5–10 min idle, max 1h) |
  | `5m` | `cache_control: {type: ephemeral}` (5 min IS the default — Anthropic does NOT accept an explicit `ttl: "5m"`; only `"1h"` is documented as an explicit value) | `cache_control: {type: ephemeral, ttl: "300s"}` | no `prompt_cache_retention` (matches default `in_memory`) |
  | `1h` | `cache_control: {type: ephemeral, ttl: "1h"}` | `cache_control: {type: ephemeral, ttl: "3600s"}` | `prompt_cache_retention: "24h"` (per DD#37) |

  Anthropic's API only documents two states: omit `ttl` for 5-min default, or set `ttl: "1h"` for extended. Gemini's `cachedContents` API requires seconds notation with `"s"` suffix (LiteLLM Vertex docs). OpenAI's `prompt_cache_retention` accepts only `"in_memory"` (default) and `"24h"` (extended); `cache_control` markers themselves are no-op on OpenAI — the retention parameter sits separately on the request body (per DD#37). Translation lives in `src/pflow/core/llm_client.py` alongside the cache-rendering logic — small lookup keyed by `model` provider prefix. Out-of-vocabulary providers omit the TTL field (graceful no-op).
- The node's `prompt:` (the task) is rendered as the user message, after the cacheable system prefix.
- If the rendered cache content is below the provider's minimum token threshold (looked up via `core/llm_capabilities.py::get_min_cache_tokens(model)` — see DD#32 for per-version Anthropic numbers), pflow issues a validation-time warning but does not fail the call — provider silently no-ops.
- Rendering failures (template resolution error on a cache item) follow the existing `build_template_error_diagnostic` pattern, returning an error-dict from the adapter to avoid wasted retries.

### Auto Batch-Prefix Caching

- Auto batch-prefix caching applies ONLY when the batch node has `prewarm: true`. Without prewarm, all N calls would write the cache simultaneously and pay the write cost without any read benefit — pflow does not insert markers in that case.
- When active: pflow detects the static prefix of the rendered prompt (text before the first batch-scoped reference). If the prefix exceeds the provider's minimum token threshold, pflow inserts a `cache_control` marker at the end of that prefix (Anthropic/Gemini).
- Detection resolves all non-batch-scoped template variables first, then locates the first batch-scoped reference in the partially-resolved string. Position-mapping details are an implementation concern.
- The rendered prompt bytes are identical to what the author wrote — only the content-block structure and `cache_control` metadata differ.
- N=1 batches skip auto-batch-prefix (no fan-out, no savings opportunity).
- **Triggering rule (savings-ratio-based, per DD#33):** for batches with size ≥ 2 and static prefix ≥ provider min-cache, compute `savings_ratio = (N-1) × 1.15 × P / (N × (1.25P + D))` where `P` = static prefix tokens, `D` = dynamic suffix tokens. Ratio captures "what fraction of this batch is actually cacheable" — naturally scales with prefix-to-total ratio AND batch size N.
  - `ratio < 5%` → silent skip (no warning, no marker; prefix dominated by dynamic content; not worth pursuing).
  - `ratio ≥ 5%` AND no explicit `prewarm:` decision → emit `cache.batch-prewarm-recommended` (warning severity). `context.savings_pct` carries the ratio; `context.savings_usd` carries the absolute estimate. Agent decides based on intent.
  - When `prewarm:` is already declared (true or false), no warning fires regardless of ratio — decision already made.
- Per DD#36, this warning is emitted only by `pflow analyze-cache` and `pflow run --dry-run`. **Does NOT block `pflow run`.** Computing savings ratio requires `litellm.token_counter` and historical state via `MemoizationCache.get_latest_for_node()`; both are too expensive for runtime validation.
- No absolute dollar floor: small absolute savings compound across reruns; pflow can't predict run frequency. Filtering on absolute would hide high-leverage fixes that compound at scale.
- Combines with declared cache: a batch node can have both `prompt_cache: [...]` (applies regardless of prewarm — those chunks were written by upstream non-batch nodes) AND `prewarm: true` (which adds the auto-batch-prefix marker). Distinct cache breakpoints, both marked.

### Strict Order Validation

- A node's `prompt_cache:` list out of declaration order produces a hard error at workflow validation time:

  ```
  ERROR: <node-name> prompt_cache order doesn't match ## Cache declaration
    expected:  [concept, concept_brief, creative-direction.response]
    you wrote: [concept_brief, concept, creative-direction.response]
    fix:       reorder the `prompt_cache:` field to match ## Cache declaration order
  ```

  The `expected:` line shows the node's selected subset reordered to match the
  containing `## Cache` block — i.e. the exact replacement to write into
  `prompt_cache:`. (Earlier wording was `declared:`; renamed for clarity since
  the line shows the node's subset, not the full `## Cache` declaration.)

- Error is caught by both `pflow run` validation and `pflow analyze-cache` (via the shared `data_flow.py::validate_data_flow()` call site).
- No auto-reorder. The workflow file is the source of truth. No escape hatch in v1; if a real use case emerges for per-node reorder, revisit.

### Validation Location

- Structural cache-block validation (required fields, types, enum values for `ttl`) lives in the `FLOW_IR_SCHEMA` — automatically runs at every validation entry point.
- Cache reference validation (item names resolve, order matches, subsets valid, batch-scoped references rejected) lives in `core/workflow/data_flow.py::validate_data_flow()` — already called by both the workflow validator (save + pre-execution path) and compile-time validation. One implementation covers all entry points.
- Diagnostics emitted follow existing pattern: `Diagnostic(severity=ERROR, source="validator", category="validation", path="nodes[id=X].prompt_cache[i]", similar_names=..., available_fields=..., see_also=["caching"])`. Use `find_similar_items` from `core/suggestion_utils.py` for "Did you mean?" hints.
- **`source` field convention for cache diagnostics**: structural validation errors (run-time path) use `source="validator"` matching existing pflow convention. Analytical findings emitted by `pflow analyze-cache` AND `pflow run --dry-run` (the same warning may surface in both contexts) use `source="cache_analyzer"` regardless of which surface emits them — mirrors the existing precedent where `pflow plan` uses `source="planner"` for both CLI and MCP callers (`execution/plan.py`, six sites). Identity-tuple dedup (`(severity, source, node_id, id or message)` in `core/diagnostic.py:84,92`) collapses identical findings across surfaces. Source = the analyzer, never the renderer.
- Schema-level errors and reference-resolution errors both flow through the existing CLI / MCP / JSON diagnostic pipeline (stderr for text, structured for JSON).
- **Unused cache chunk warning.** If `## Cache` declares a chunk that no node's `prompt_cache:` references, emit a validation warning (not error) suggesting removal or referencing. Helps the author keep the cache block lean and surfaces dead code.

### Memo Cache Hash Correctness

- Thread `prompt_cache` rendered content into `compute_node_config()` conditionally:

  ```python
  if prompt_cache_content:  # non-empty list of rendered chunks
      config["prompt_cache"] = prompt_cache_content
  ```

- Follows the `batch_config` precedent at the same function. Nodes that don't opt in keep their existing hash (existing cache entries continue to hit). Nodes that do opt in get a distinct hash and fresh cache entries — no silent stale-result bug.
- `prompt_cache_content` must be the **rendered** content (prose + resolved value), not the declaration (`[name1, name2]`), because two different resolved values under the same name should produce different hashes.
- Update `runtime/engine/CLAUDE.md` to note: "`prompt_cache` content is included conditionally, mirroring `batch_config`. The value is the rendered content chunks."
- Regression test required: existing workflow (no `prompt_cache`) produces identical hash pre- and post-task.

### Cache Layer Independence (`--no-cache` scope)

- The `--no-cache` flag disables pflow's local **memoization** layer only. It does NOT disable LLM provider prompt caching.
- Rationale: the two layers are conceptually independent. Memoization opts a node out of re-executing when inputs match a prior run (correctness/freshness control). Prompt caching is pure cost reduction at the provider level with no behavioral change. There is no reason to disable prompt caching when debugging memo behavior.
- `pflow analyze-cache` output and trace cached-token reporting remain active under `--no-cache`.
- Documentation (`--no-cache` flag help, guide section) must make this distinction explicit.

### Breakpoint Limit Handling

- Anthropic: max 4 cache_control markers per request. Pflow's v1 strategy uses 1 per call (the declared-cache end-of-prefix) + up to 1 for batch auto-prefix = 2 max per call. Well within limits.
- OpenAI: markers are effectively no-ops; no limit concern.
- Gemini: `CachedContents` is single-blob — multiple `cache_control` markers in one request collapse into the **last** marker's prefix only. v1's 2-marker max degrades correctly because the markers fire in order [end-of-system-cache, end-of-batch-prefix-in-user-message] and the latest is always a superset of the earlier (the batch-prefix marker comes after the system cache content in the rendered request). Both effective cache regions still fall under the surviving marker. Multi-breakpoint placement (Anthropic-only follow-up) does NOT translate to Gemini — see References → Planned Follow-Ups.
- If future usage demands >2 markers per call (multi-breakpoint for finer-grained sharing), extend the strategy — NOT v1 work.

### `pflow analyze-cache` Command

- New CLI command: `pflow analyze-cache <workflow-path> [inputs...]`. Implementation in new file `src/pflow/cli/commands/analyze_cache.py`.
- **Inputs are optional (DD#35).** Workflow inputs from the `## Inputs` section are NOT required to run analysis. Most analysis paths (cache-block parsing, Tier 2 walking, shared-context detection) don't depend on input values. Token estimation falls back to lower-fidelity sources (`memo` → `estimator` → `heuristic`) when input substitution can't fully resolve a prompt. Required-but-absent inputs emit a single info note in the output, not an error.
- **Trace data is auto-loaded (DD#34) — 2.1.0 only.** By default, `pflow analyze-cache` looks for the most recent matching 2.1.0 trace in `~/.pflow/debug/` (matched by `trace["workflow_path"]`) and uses it. 2.0.0 traces are skipped by auto-load. Override with `--from-trace <path>` (explicit file, works on both 2.0.0 and 2.1.0) or opt out with `--no-trace` (pre-optimization estimates / before-after comparison).
- Shared analysis module under new package `src/pflow/core/cache_analysis/` exposes two entry points:
  - `analyze(workflow, parameters) -> CacheAnalysis` — full plan with per-node table, shared context candidates, warnings, padding advisories, cross-workflow alignment findings.
  - `summarize(workflow, parameters) -> Diagnostic | None` — one-line `Severity.INFO` nudge for `--dry-run` footer; `None` when cache is already optimal.
- Output has four modes determined by workflow state and CLI flags. Same data model; section presence varies by content. See **Output Format — Text** and **Output Format — JSON** below.
  - **Greenfield**: workflow has no `## Cache` block declared. Output emphasizes detection and suggested additions.
  - **Steady-state**: workflow has `## Cache` block declared. Output emphasizes per-chunk usage and validation.
  - **Already-optimal**: no actionable opportunities detected. Single-line output.
  - **Trace mode**: a trace file was loaded (auto-discovered or via `--from-trace`). Adds a "Discrepancies" section comparing predicted to actual per-node cache ratios. Each discrepancy carries root-cause attribution (TTL expiry via `cache_age_sec`, content mismatch via `cache_key` compare, parallel-write race). Falls back gracefully on 2.0.0 traces (omits cache-key-correlated analysis with an info message).
- Confidence indicator (aggregate): `low_no_data` / `medium_from_memo` / `high_from_trace`. Per-call `data_source`: `trace` / `memo` / `estimator` / `heuristic`. See **Confidence Labeling Algorithm** subsection.
- **v1 algorithm scope (Level 2 — detect + suggest, plus Tier 2 cross-workflow analysis per DD#26).** The analysis identifies LLM calls that share static context, computes a candidate `## Cache` block + per-node `prompt_cache:` assignments using a most-shared-first ordering heuristic, and emits a copy-pasteable block with blank prose placeholders for the author to fill in. Cross-workflow walker detects rename-across-boundary and prose-mismatch risks between parent and child cache blocks. The author decides whether to apply. Suggestions never modify workflow files.
- **Out of v1 (deferred to v1b follow-up):** full prefix-tree optimization across the whole workflow, cross-workflow auto-fix suggestions (the warnings ship in v1; the suggested-canonicalization fix does not), an explicit `pflow cache apply` command that writes the suggestions to disk after preview. v1b's scope and complexity will be assessed during Phase B-G plan writing once we see the workflow code in detail.
- Size estimates per **Token Estimation Strategy** subsection: trace history first (via `MemoizationCache.get_latest_for_node`), then `litellm.token_counter()`, then character heuristic fallback. Confidence labels reflect which source was used per call.
- **Cost-estimate degradation for unknown models.** When `litellm.completion_cost()` returns `None` for a node's model (custom endpoint, brand-new model not yet in LiteLLM's `model_cost`, self-hosted Ollama, etc.), `analyze-cache` mirrors Task 158's tri-state contract for runtime cost reporting:
  - **JSON output**: `summary.current_cost_per_run_usd` becomes a partial estimate (sum of priced calls only). New sibling fields: `summary.partial_cost_usd: bool` (true when any node has missing pricing), `summary.unavailable_models: list[str]` (model strings missing from LiteLLM pricing). Same fields apply to `optimized_cost_per_run_usd` and `rerun_cost_per_run_usd`. `recommended_actions[].estimated_savings_usd` becomes `null` for nodes with unpriced models; the action still appears (token-savings reasoning is independent of dollar conversion).
  - **Text output**: cost lines render as `~$0.84 (partial — 2 of 23 nodes use unpriced models)` with a footer note: `Unpriced models: ollama/llama3.2:8b, custom-endpoint/foo`. Confidence label is unaffected (it tracks token-source fidelity, not dollar fidelity).
  - **Never crash, never silently show $0.** A workflow with all unpriced models renders cost as `unavailable` rather than `$0.00`, and the SUMMARY explicitly states why.
- Exits 0 on successful analysis. Non-zero only on validation errors (unparseable workflow, unresolvable references). Missing pricing data is NOT a failure — the analysis still has actionable structural recommendations.

### Stable Warning ID Catalog

Closed list for v1. Adding new IDs goes through design review (DD#29). All IDs namespaced under `cache.`:

Catalog organized by emission path (per DD#36 three-tier architecture). "Run validation" entries are structural and always run at `pflow run` time — fast, no tokenizer, no I/O. "Analytical" entries run only at `pflow analyze-cache` or `pflow run --dry-run` — they require token counting, historical state, or graph walking and would slow the runtime path.

**Run validation (always emitted at `pflow run`):**

| ID | Severity | Blocks run? | Triggers when... |
|---|---|---|---|
| `cache.order-mismatch` | `error` | yes | A node's `prompt_cache:` list doesn't match `## Cache` declaration order. |
| `cache.unused-chunk` | `warning` | no | A `## Cache` block declares a chunk that no node's `prompt_cache:` references. |

(Reference-resolution errors — `prompt_cache:` referencing an undeclared chunk, or a `${var}` in `## Cache` that doesn't resolve — flow through the existing diagnostic pipeline; they're errors that block `pflow run`. They're not separate cache-namespaced IDs because they reuse pflow's general validation machinery.)

**Analytical (emitted at `analyze-cache` or `--dry-run` only — never block `pflow run`):**

| ID | Severity | Triggers when... |
|---|---|---|
| `cache.shared-context-undeclared` | `info` | Static analysis finds N≥2 LLM calls sharing a context object that isn't in any `## Cache` block. Suggests adding it. |
| `cache.batch-prewarm-recommended` | `warning` | Prewarm savings_ratio ≥ 5% (per DD#33), no explicit `prewarm:` decision declared. `context.savings_pct` and `context.savings_usd` carry the magnitude — agent decides based on intent. |
| `cache.dynamic-before-static` | `warning` | A node's prompt has a `${var}` reference high up that prevents the rest of the prompt (which IS stable) from caching. Highest-leverage individual fix when it appears. |
| `cache.padding-advisory` | `info` | A node's `prompt_cache:` subset doesn't start at position 1 of the master order; padding would unlock prefix hits at 0.1× read rate, net-positive. |
| `cache.below-min-tokens` | `warning` | Declared cache content for a node is below the provider's minimum token threshold. Markers will silently no-op. |
| `cache.cross-workflow-prose-mismatch` | `info` | Tier 2: parent and child both declare a chunk with the same identifier but different prose-before-the-`${var}`. Cross-workflow byte-level cache hit won't fire. |
| `cache.cross-workflow-rename-detected` | `info` | Tier 2: parent passes a value into a child's input under a different name (e.g. `concept_brief → creative_brief`). Yellow flag for divergent prose between the two cache blocks. |
| `cache.consolidate-to-root-recommended` | `info` | Sub-paths of a parent dict (e.g. `concept.core_idea`, `concept.title`) appear in `## Cache` (brownfield) or in shared template references (greenfield) AND are individually below the provider's min-cache threshold AND consolidating to `${root}` would cross the threshold. Sub-path `cache_control` markers silently no-op at the provider; consolidation makes caching actually fire. (Added in CP3 / lyrics-generator Stage 1 verification — DD#29 design review approved.) |

The `cache.opportunities-available` ID is reserved for the `--dry-run` nudge Diagnostic; it's emitted by `summarize()` rather than `analyze()` and isn't part of the analyze-cache warnings list.

### Output Format — Text

All four modes share section ordering. Sections appear when non-empty, disappear when empty. No "deferred to v1b" placeholders.

**Section ordering:**

1. **Header** — workflow path, scale (concept count, total LLM calls, models in use), confidence label.
2. **Summary** — current cost, optimized cost, rerun cost, opportunity count.
3. **Recommended actions** — numbered, ordered by impact descending, each with stable warning ID, savings, action.
4. **Suggested ## Cache block(s)** — one per target file. Multi-file (greenfield mode usually has multiple targets when sub-workflows exist). Includes paste-ready ## Cache block with `<DESCRIBE...>` prose placeholders, plus per-node `prompt_cache:` assignments.
5. **Cross-workflow alignment (Tier 2)** — only when findings exist. Warnings about rename-across-boundary, prose mismatches, value-flow opportunities.
6. **Per-call cache report** — table of LLM nodes with model, tokens, cacheable, ratio, confidence per call, inline warning markers.
7. **All warnings** — full list with severity, ID, location.
8. **Notes** — per-invocation scoping, mixed-model context, fallback hints (`--from-trace`, `--all-rows`, `--format=json`).

**Per-call rendering rules:**

- Default rendering: only rows with warnings OR rows in the bottom 50% of cache ratios. All-clean rows summarized as `Hidden: N nodes at ≥80% projected cache ratio with no warnings (rerun with --all-rows).`
- `--all-rows` flag shows every node, sorted by token volume descending.
- Default sort: rows with `error` warnings first, then `warning`, then `info`, then by `input_tokens_estimated` descending.
- Batch nodes shown as one row with `(×N)` annotation; per-call ratio reflects a single call.
- Sub-workflow nodes use full path notation: `song-creator.review-narrative` (parent.child), not just `review-narrative`.

**Mode 1 — Greenfield (canonical example, anchored to `lyrics-generator.pflow.md`):**

````
$ pflow analyze-cache workflows/lyrics-generator/lyrics-generator.pflow.md \
    sources='["https://example.com/article"]'

# Cache Analysis: lyrics-generator.pflow.md

  4 concepts · ~252 LLM calls across 8 workflow files · 3 models in use
  Confidence: low_no_data (estimates from litellm.token_counter; no run history, no trace)

## Summary

  Current cost per run:        ~$2.18
  Optimized cost per run:      ~$0.84   (-61%)
  Cost on rerun (within 1h):   ~$0.39   (-82%)

  4 opportunities (1 warning, 3 info)

## Recommended actions (ordered by impact)

  1. [cache.dynamic-before-static]                              -$0.31/run
     chorus-chooser/build-scoring-items: ${chorus_text} appears at line 3
     of the prompt template; the ~1,640-token scoring rubric falls AFTER
     it, so 136 scoring calls per run cache nothing.
     Action: move the "## The Chorus" section to the END of the prompt,
             after the rubric and output format. Projected cache ratio: 87%.

  2. [cache.shared-context-undeclared]                          -$0.78/run
     song-creator.pflow.md: 5 stable contexts (concept, concept_brief,
     creative-direction.response, song-architecture.response,
     easter-eggs.response) flow through 15 sequential LLM calls per song
     path × 4 parallel paths.
     Action: paste the suggested ## Cache block (below) into
             song-creator.pflow.md.

  3. [cache.batch-prewarm-recommended]                          -$0.12/run (89% of batch cost)
     chorus-chooser.score-choruses: 34-item batch with ~2.1k-token static
     prefix has no prewarm decision. Without prewarm, all 34 calls write
     cache simultaneously.
     Action: add `- prewarm: true` (-$0.12/run) or `- prewarm: false`
             (explicit opt-out) to the score-choruses node.

  4. [cache.padding-advisory]                                   -$0.04/run
     song-creator/review-narrative could pad its `prompt_cache:` subset
     to hit upstream cache writes from write-lyrics.
     Action: extend [song-architecture.response] to
             [concept, creative-direction.response, song-architecture.response].

## Suggested ## Cache block — song-creator/song-creator.pflow.md

  Paste between ## Inputs and ## Steps:

  ## Cache

  - ttl: 5m

  ```cache
  <DESCRIBE THE CONCEPT — appears verbatim in cached system prefix>

  ${concept}

  <DESCRIBE THE CONCEPT BRIEF (per-concept material palette)>

  ${concept_brief}

  <DESCRIBE THE CREATIVE DIRECTION DECISIONS>

  ${creative-direction.response}

  <DESCRIBE THE SONG ARCHITECTURE>

  ${song-architecture.response}

  <DESCRIBE THE EASTER EGGS CONTEXT>

  ${easter-eggs.response}

  <DESCRIBE THE WINNING CHORUS — fixed creative constraint>

  ${choose-chorus.winning_chorus}
  ```

  Per-node prompt_cache: assignments:

    write-lyrics:        [concept, concept_brief, creative-direction.response,
                          song-architecture.response, easter-eggs.response,
                          choose-chorus.winning_chorus]
    rewrite-emotional:   [concept, concept_brief, creative-direction.response,
                          song-architecture.response]
    rewrite-craft:       [creative-direction.response, song-architecture.response]
    generate-suno-prompt:[creative-direction.response]

## Cross-workflow alignment (Tier 2)

  ▸ [cache.cross-workflow-rename-detected]
    song-creator → chorus-chooser passes `concept_brief` as input named
    `creative_brief` (line 77 of song-creator.pflow.md). The same logical
    value now has two names across the workflow boundary.

    Risk: when both files declare ## Cache blocks, divergent prose labels
    (likely, given the rename) will produce different bytes for the same
    value. Cross-workflow cache hits won't fire even though the value is
    identical.

    Action: pick one prose label and use it in both files' ## Cache blocks.

  ▸ Verified clean: lyrics-generator → song-creator preserves names.

## Per-call cache report (showing 8 of 23 LLM nodes; all-clean rows hidden)

  node                                       model                              tokens  cacheable  ratio   confidence  notes
  ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  chorus-chooser.score-choruses (×34)        anthropic/claude-sonnet-4-5         1.9k       0.1k     4%   estimator    cache.dynamic-before-static
  chorus-chooser.generate-chorus-options(×8) gemini-3-flash-preview              3.5k       2.6k    74%   estimator    no marker; small batch
  song-creator.write-lyrics                  gemini/gemini-3.1-pro-preview      14.2k      11.8k    83%   estimator
  song-creator.rewrite-emotional             gemini/gemini-3.1-pro-preview      18.1k      15.4k    85%   estimator
  song-creator.rewrite-craft                 gemini/gemini-3.1-pro-preview      19.6k      16.9k    86%   estimator
  song-creator.review-narrative              anthropic/claude-sonnet-4-5        10.5k       3.4k    32%   estimator    cache.padding-advisory
  song-creator.review-stranger-summary       anthropic/claude-sonnet-4-5         3.2k       0.6k    19%   estimator    isolated by design
  curate-briefs (×4)                         anthropic/claude-sonnet-4-5         8.6k       2.5k    29%   estimator

  Hidden: 15 nodes at ≥80% projected cache ratio with no warnings.

## All warnings

  warning  cache.batch-prewarm-recommended     chorus-chooser.score-choruses
  warning  cache.dynamic-before-static         chorus-chooser.build-scoring-items
  info     cache.shared-context-undeclared     song-creator.pflow.md
  info     cache.padding-advisory              song-creator.review-narrative
  info     cache.cross-workflow-rename-detected song-creator → chorus-chooser

## Notes

  · Sub-workflow per-invocation scoping: song-creator runs 4× in parallel
    (one per concept). Each invocation has independent cache entries — no
    cross-path sharing.
  · Mixed-model context: Anthropic and Gemini cache entries are independent.
  · For actuals: pflow analyze-cache --from-trace ~/.pflow/debug/<trace>.json
  · For machine-readable output: --format=json
````

**Mode 2 — Steady-state** (`## Cache` declared): same overall structure; "Suggested ## Cache block" replaced by "Declared cache plan" showing per-chunk usage with active/unused indicators. Per-call table shows actual `cache_creation` / `cache_read` token counts when trace data is available.

**Mode 3 — Already-optimal** (single-line output):

```
# Cache Analysis: workflow.pflow.md
  Confidence: high_from_trace
  Cache plan is optimal — no actionable opportunities detected.
  Run 'pflow analyze-cache --from-trace <trace>.json' to verify against actual provider-reported cache hits.
```

**Mode 4 — `--from-trace`**: same structure as the matching baseline mode, plus a "Discrepancies" section comparing predicted to actual per-node cache ratios. Each discrepancy includes root cause attribution (TTL expiry, parallel-write race, key-mismatch). Per-call table gains a `delta` column. Discrepancy example:

```
▸ [cache.discrepancy] song-creator.review-narrative (path: songs[1])
  Predicted hit_ratio: 72%   Actual: 0%
  Root cause: cache_age_sec = 3,847s (>1h TTL); upstream write expired
              before this read fired.
  Action: consider `- ttl: 1h` on the song-creator ## Cache block.
```

### Output Format — JSON

`--format=json` emits a structured object. `format_version` starts at `"1.0"` (major bump for breaking changes; minor for additive fields). `cross_workflow.*` arrays are always present in JSON; empty arrays mean "no findings" (text mode hides empty sections).

Full schema (anchored to greenfield mode):

```json
{
  "format_version": "1.0",
  "workflow_path": "/abs/path/lyrics-generator.pflow.md",
  "analyzed_at": "2026-04-27T15:42:18Z",
  "estimate_confidence": "low_no_data",
  "trace_path": null,

  "summary": {
    "current_cost_per_run_usd": 2.18,
    "optimized_cost_per_run_usd": 0.84,
    "rerun_cost_per_run_usd": 0.39,
    "savings_pct_first_run": 61,
    "savings_pct_rerun": 82,
    "blocking_errors": 0,
    "actionable_opportunities": 4,
    "warnings_count": 1,
    "info_count": 3,
    "total_llm_nodes_estimated": 19,
    "total_llm_invocations_estimated": 252,
    "dynamic_batch_node_count": 0,
    "total_input_tokens_estimated": 78100,
    "total_cacheable_tokens_estimated": 47300,
    "models_in_use": ["anthropic/claude-sonnet-4-5", "gemini/gemini-3.1-pro-preview", "gemini-3-flash-preview"]
  },

  "recommended_actions": [
    {
      "rank": 1,
      "warning_id": "cache.dynamic-before-static",
      "node_id": "chorus-chooser.build-scoring-items",
      "estimated_savings_usd": 0.31
    }
  ],

  "suggested_blocks": [
    {
      "target_file": "song-creator/song-creator.pflow.md",
      "ttl": "5m",
      "chunks": [
        {"name": "concept", "var": "${concept}", "size_tokens_est": 620, "prose_placeholder": "<DESCRIBE THE CONCEPT...>"}
      ],
      "per_node_assignments": {
        "write-lyrics": ["concept", "concept_brief", "..."]
      },
      "estimated_savings_usd": 0.78
    }
  ],

  "per_call": [
    {
      "node_path": "chorus-chooser.score-choruses",
      "model": "anthropic/claude-sonnet-4-5",
      "is_batch": true,
      "batch_size_estimated": 34,
      "input_tokens_estimated": 1900,
      "cacheable_tokens_estimated": 100,
      "cache_ratio_pct": 4,
      "data_source": "estimator",
      "declared_prompt_cache": null,
      "warnings": ["cache.dynamic-before-static", "cache.batch-prewarm-recommended"]
    }
  ],

  "cross_workflow": {
    "boundaries_analyzed": 8,
    "rename_detections": [
      {
        "warning_id": "cache.cross-workflow-rename-detected",
        "parent_workflow": "song-creator/song-creator.pflow.md",
        "child_workflow": "song-creator/chorus-chooser/chorus-chooser.pflow.md",
        "parent_value": "${concept_brief}",
        "child_input_name": "creative_brief",
        "line_in_parent": 77,
        "risk": "Divergent prose labels likely will break cross-workflow byte-level cache match."
      }
    ],
    "prose_mismatches": [],
    "value_flow_opportunities": []
  },

  "warnings": [
    {
      "id": "cache.batch-prewarm-recommended",
      "severity": "warning",
      "node_id": "chorus-chooser.score-choruses",
      "message": "34-item batch with ~2,100-token static prefix has no explicit prewarm decision; prewarming would save ~89% of batch cost.",
      "suggestions": [
        "Add `- prewarm: true` to opt in (-$0.12/run).",
        "OR add `- prewarm: false` to opt out explicitly."
      ],
      "context": {
        "category": "cache_warning",
        "batch_size": 34,
        "prefix_tokens_estimated": 2100,
        "savings_pct": 89,
        "savings_usd": 0.12
      },
      "see_also": ["caching", "batch"]
    }
  ],

  "notes": [
    "Sub-workflow per-invocation scoping: ...",
    "Mixed-model context: ...",
    "Estimates use litellm.token_counter; run with --from-trace for actuals."
  ]
}
```

JSON shape notes:

- **`per_call[].data_source`**: mirrors per-call confidence labels: `trace` / `estimator` / `heuristic`.
- **`warnings[].context.category`**: uses `cache_failure` / `cache_warning` / `cache_advisory` constants. Phase B adds these to `core/diagnostic.py::CATEGORY_TITLES`.
- **`per_call[].declared_prompt_cache`**: `null` in greenfield; an array of chunk names in steady-state.
- **No `fix.action` typed dispatch.** Per DD#28, structured fix data lives in `warnings[].context` (e.g. `target_file`, `chunks`, `assignments`); prose lives in `warnings[].suggestions`.
- **`recommended_actions`**: pre-sorted dispatch list. Agents iterate in order; consult `warnings[]` by `warning_id` for full context.

### Confidence Labeling Algorithm

Two distinct data sources are sometimes conflated; this section names them apart (DD#34):

- **Trace JSON files** at `~/.pflow/debug/workflow-trace-*.json` — format 2.1.0 carries per-event cache metadata (`cache_creation_input_tokens`, `cache_read_input_tokens`, `cache_age_sec`, `cache_key`). Required for `--from-trace` discrepancy analysis.
- **MemoizationCache** at `~/.pflow/cache.db` (SQLite) — stores prior node outputs including `llm_usage.input_tokens`. Always queryable when a workflow has been run before.

Trace auto-loading: by default, `pflow analyze-cache` looks for the most recent matching **2.1.0** trace in `~/.pflow/debug/` and uses it if found. Matching: parse trace JSON top-level `workflow_path`; compare to the analyzed workflow's resolved path (or `ir-hash:<md5>` for inline). Most-recent-by-mtime among matches wins. 2.0.0 traces are ignored by auto-load (no `workflow_path` field). `--from-trace <path>` is an explicit override (works for both 2.0.0 and 2.1.0). `--no-trace` opts out entirely.

Per-call data source determined by:

1. **Trace JSON file** (auto-loaded or explicit): if a per-event entry exists for the node, source = `trace` (highest fidelity; only path that gets discrepancy analysis in `--from-trace` mode).
2. **MemoizationCache**: query `get_latest_for_node(node_id, workflow_path=...)`. If it returns a recent entry (within 24h) AND that entry contains `llm_usage.input_tokens`: source = `memo`.
3. **`litellm.token_counter`**: try `token_counter(model=node.model, text=resolved_prompt)`. Success → source = `estimator`.
4. **Char heuristic**: `len(resolved_prompt) // 4` when all above fail (unknown model, missing model field, or `token_counter` raises). Source = `heuristic`.

Aggregate confidence:
- All rows `trace` → `high_from_trace`.
- At least some `memo` (or mixed `trace`/`memo`) → `medium_from_memo`.
- All rows `estimator` or `heuristic` → `low_no_data`.

**Coverage detail in aggregate label.** Aggregate alone misleads when memo/trace data is sparse — `medium_from_memo` for "2 of 30 nodes" overstates fidelity. Text mode appends `(<count> of <total> nodes)` when aggregate is `medium_from_memo` or `high_from_trace`. Example: `Confidence: medium_from_memo (3 of 30 nodes have prior run data)`. JSON adds a sibling field `estimate_confidence_coverage: {"trace": <int>, "memo": <int>, "estimator": <int>, "heuristic": <int>, "total": <int>}` so agents can compute their own coverage view.

When aggregate is `low_no_data`, the SUMMARY section explicitly suggests running the workflow once. After a run, `memo` data becomes available automatically (no flag needed); after a run with tracing, `trace` data becomes available.

JSON output's `per_call[].data_source` carries the four-value source label; `estimate_confidence` carries the aggregate; `estimate_confidence_coverage` carries the per-source counts.

### Cross-Workflow Walker (Tier 2)

New module: `src/pflow/core/cache_analysis/cross_workflow.py` (~50 LOC). Mirrors the mermaid renderer's traversal pattern (`core/workflow/mermaid/_render.py:50-130`).

- **Primitive**: `core/workflow/sub_workflow_resolver.py::resolve_sub_workflow` — returns `(ir, path, warnings)` for a sub-workflow reference. Already used by validator, executor, mermaid, and dry-run planner.
- **Walker shape**: recursive walk from root workflow IR. For each `type: workflow` node, read `node["params"]["workflow"]` and `node["params"]["inputs"]`. Resolve to child file via `resolve_sub_workflow`. Recurse on child IR with depth limit and cycle detection (set of resolved paths).
- **Output**: `list[CrossWorkflowEdge]` where each edge carries `{parent_workflow, child_workflow, parent_value_expr, child_input_name, line_in_parent}`.
- **Batch sub-workflows**: walker uses `WorkflowValidator._enumerate_child_calls` (`validator.py:807-880`) to enumerate per-batch-item child calls when params reference the batch alias (`${item.workflow}`). Heterogeneous batches yield N edges; homogeneous yield 1.
- **Detection rules** (rename takes precedence — never double-emit on a renamed chunk):
  - **Rename detection** (`cache.cross-workflow-rename-detected`): when a parent edge has `child_input_name != tail_of_parent_value_expr` (e.g. parent passes `${concept_brief}` to child input named `creative_brief`). Emitted whenever rename occurs, regardless of whether either side has a `## Cache` declaration.
  - **Prose mismatch** (`cache.cross-workflow-prose-mismatch`): emitted ONLY when names are identical across the boundary (no rename) AND parent and child both declare `## Cache` blocks with the same chunk identifier AND the prose-before-the-`${var}` differs byte-by-byte. If a rename was already detected for the same chunk, prose-mismatch is suppressed — the rename warning subsumes it.
  - **Value-flow opportunity**: when parent passes a value into child but neither file's `## Cache` declares it. Surfaces as a `cache.shared-context-undeclared` warning scoped to the boundary.
- **Auto-fix**: out of v1. v1 emits the warning; the canonicalization fix is deferred per DD#26 (no clearly right answer for "which prose wins").

### Token Estimation Strategy

Three-tier strategy (DD#31):

1. **Trace history** (highest fidelity): query `MemoizationCache.get_latest_for_node()` for each LLM node. The cached blob carries `output["llm_usage"]["input_tokens"]` from the prior run. No new SQLite schema; `__pflow_stats__` injection (`runtime/engine/CLAUDE.md:118`) does not need extension.
2. **`litellm.token_counter` estimator** (medium fidelity, ±5%): for nodes without trace history, call `litellm.token_counter(model=node.model, text=resolved_prompt)`. Already transitively installed via LiteLLM. Offline, model-aware. Add lazy-import wrapper at `src/pflow/core/cache_analysis/token_estimation.py` to keep `litellm` lazy-loaded outside the adapter (Task 158 lazy-import contract).
3. **Character heuristic fallback** (low fidelity, ±20%): `len(text) // 4` when both above fail (unknown model, missing model field, or `litellm.token_counter` raises). Only place pflow uses a char-based heuristic; tagged in confidence labeling so agents see they're getting low-fidelity numbers.

### Per-Model Capabilities Table

New module: `src/pflow/core/llm_capabilities.py` introduced in Phase B.

- v1 hardcodes per-model min-cache-token thresholds. Anthropic minimums are version-specific per DD#32; condensed:
  - Anthropic Sonnet 4.5 / Opus 4.1 / Opus 4 / Sonnet 4 / Sonnet 3.7: **1024**
  - Anthropic Sonnet 4.6 / Haiku 3.5: **2048**
  - Anthropic Opus 4.7 / Opus 4.6 / Opus 4.5 / Haiku 4.5: **4096**
  - Gemini 2.5 Flash: 1024 implicit / ~4k explicit
  - Gemini 2.5 Pro: 2048 implicit / higher explicit
  - OpenAI: 1024 (automatic caching threshold)
- LiteLLM's `model_cost` dict has some of this data (`max_input_tokens`, `cache_creation_input_token_cost`, `cache_read_input_token_cost`, `supports_prompt_caching`) but coverage and field names need verification. Wrapping deferred to v1.x if hardcoded data proves stale.
- Used by:
  - `cache.below-min-tokens` warning emission (looks up the threshold for the node's model).
  - Auto batch-prefix detection (skips when prefix is below threshold).
- Lookup: `get_min_cache_tokens(model: str) -> int` returns the threshold. Fallback for unknown models per DD#32 (recommended floor: 4096).

### Diagnostic Extension (Phase B prerequisite)

Required for v1. ~10 LOC change to `core/diagnostic.py`.

- Add `id: str | None = None` field to `Diagnostic` dataclass (DD#27).
- Update identity tuple from `(severity, source, node_id, message)` to `(severity, source, node_id, id or message)`. When `id` is present it's the dedup key; otherwise fall back to `message` (preserves identity for diagnostics not yet migrated).
- `to_dict()` emits `id` when set; omits otherwise.
- Add new category constants: `CACHE_FAILURE_CATEGORY = "cache_failure"`, `CACHE_WARNING_CATEGORY = "cache_warning"`, `CACHE_ADVISORY_CATEGORY = "cache_advisory"` to `CATEGORY_TITLES`.
- No migration needed for existing diagnostics (the `id` field is optional). Future categories adopt the convention as they're touched.
- **Out of scope (per DD#28)**: no `FixAction` typed substructure. `suggestions: list[str]` for prose; `context: dict` for raw structured data. Renderer dispatch for cache-category warnings (so they can render `context` data inline instead of being limited to `message + node_id + suggestions`) is a Phase B add to `core/diagnostic_render.py`'s `_format_warning_or_info_diagnostic` — mirrors the existing `template_error` precedent.

### `--dry-run` Cache Nudge and Cache Rendering

- Per DD#36, `pflow run --dry-run` runs the **full analytical pass** under the hood — same analysis as `pflow analyze-cache`, just rendered as a one-line nudge instead of a full sectioned report. User opted into analysis by passing `--dry-run`, so latency budget is generous (token counting, historical state lookup, Tier 2 walk all permitted).
- The dry-run planner calls `cache_analysis.analyze(...)` to do the work, then `cache_analysis.summarize(...)` to derive a `Severity.INFO` `Diagnostic` from the result. Attached to the plan's `diagnostics` list.
- The existing diagnostic-rendering loop in the plan formatter renders it automatically. No new formatter code.
- JSON `--format=json` output includes the diagnostic via `Diagnostic.to_dict()`.
- Nudge is silent when no actionable opportunities exist.
- Locked nudge text format:
  ```
  ℹ Cache: 4 design opportunities available (estimated -$1.34/run, -61%).
    Run 'pflow analyze-cache' for details.
  ```
- JSON shape (emitted via `Diagnostic.to_dict()` with `id="cache.opportunities-available"`):
  ```json
  {
    "severity": "info",
    "id": "cache.opportunities-available",
    "message": "Cache: 4 design opportunities available (estimated -$1.34/run, -61%).",
    "suggestions": ["Run 'pflow analyze-cache' for details."],
    "context": {
      "category": "cache_advisory",
      "opportunity_count": 4,
      "estimated_savings_usd": 1.34,
      "estimated_savings_pct": 61
    },
    "see_also": ["caching"]
  }
  ```
- **Cache content rendering during dry-run.** The planner does not execute LLM calls, so live cache values are unavailable. For workflows with `## Cache` blocks: cache chunk values resolve from `MemoizationCache.get_latest_for_node()` (the same mechanism Task 156 uses for cost estimates). For chunks with no prior cached data, the planner records "cache content unavailable — estimates low-confidence" and proceeds; this is not an error. Confidence indicator on the dry-run summary degrades accordingly.

### MCP Parity

- New MCP tool `analyze_cache(workflow, parameters) -> dict` registered in `src/pflow/mcp_server/tools/execution_tools.py`.
- Service method `ExecutionService.analyze_cache(workflow, parameters)` in `src/pflow/mcp_server/services/execution_service.py` — mirrors the `plan_workflow(...)` pattern (`execution_service.py:301-354`).
- Returns the same JSON shape as `pflow analyze-cache --format=json`.
- Registered in `execution_tools.py:354` tool exports list.
- Structured exception handling consistent with `plan_workflow`: `WorkflowValidationError`, `CompilationError`, `MarkdownParseError`.

### Prefix-Padding Advisory

- For each LLM node whose `prompt_cache:` subset doesn't start at position 1 of the master order, pflow computes whether extending the subset to include earlier items (paying 0.1× read cost on those) would net-save vs. the current state (paying 1× on its own items).
- Sensitivity floor (prevents advisory drown):
  - Skip individual `cache.padding-advisory` warnings worth less than `$0.005`.
  - Skip when total cumulative padding savings across all advisory candidates is less than `$0.05`.
  - When in doubt, surface — agents prefer over-information to silence.
- Advisory only: output shows the recommendation with cost math; never auto-applies.

### Deterministic Serialization

- Complex values referenced in cache items (dict, list) serialize to JSON with `sort_keys=True` and a stable separator/indent format.
- Applied to the rendered string substituted in place of `${var}` in the cache block.
- Enforce via a single serialization function used by cache-block rendering. Existing non-cache template rendering may use different rules (unchanged).

### Sub-Workflow Cache Blocks

- Every `.pflow.md` file can independently declare its own `## Cache` section.
- When a sub-workflow is called from a parent, the sub-workflow's cache block applies to its own LLM calls only. Parent's cache block does not cascade in.
- Standalone execution of a sub-workflow (via `pflow <sub-workflow-path>`) uses the sub-workflow's own cache block.
- Cross-workflow cache hits happen at the provider byte-match level; pflow does not orchestrate.
- Sub-workflow validation (`WorkflowValidator._validate_sub_workflows` at `validator.py:647-770`) recurses into child workflows — cache validation runs on children automatically via the shared `data_flow.py` validator.

### Trace Format 2.1.0

- Bump `format_version` to `"2.1.0"` in `runtime/workflow_trace.py:save_to_file` (line 487).
- New top-level field `trace["workflow_path"]: str | null` — derived from `shared["_pflow_workflow_file"]` at save time. For file/library runs: absolute resolved workflow path (resolver canonicalizes). For inline runs: synthetic `"ir-hash:<md5>"` identifier from `_synthesize_inline_workflow_id` (`runner.py:36-53`) — same value used by the cache layer's `MemoizationCache.workflow_path` scoping. Never `null` in 2.1.0 traces; `null` is reserved for forward compatibility with future runners that don't set `_pflow_workflow_file`.
- New per-event fields on cache-hit events (when `cached: True`):
  - `event["cache_key"]: str` — the memo cache key that matched (pulled from `plan_node.NodePlan.cache_key`).
  - `event["cache_source"]: "memo" | "in_process"` — distinguishes the two pflow cache layers.
  - `event["cache_age_sec"]: float` — age of the cached entry. Needs `MemoizationCache.get_with_age(...)` wiring into `handle_cached_execution` at `runtime/engine/instrumentation.py:506-554`.
- New per-event field on cache-write events (non-cached successful executions): `event["cache_key"]: str` — the key the entry was written under.
- Forward-compatible: existing consumers gate on `format_version.startswith("2.")` (`trace_report.py:400-455`), so they read 2.1.0 traces while ignoring new fields. No consumer updates required for basic operation.
- `core/trace_report.py` optionally extended to surface `cache_source` and `cache_age_sec` in per-node markdown. If omitted, no regression — just missing detail.
- `pflow analyze-cache --from-trace` uses 2.1.0 fields when present; falls back gracefully (with an info message) on 2.0.0 traces.

### Tracing and Cost Reporting

- The `llm_usage` dict captured in traces already contains `cache_creation_input_tokens` and `cache_read_input_tokens` (`nodes/llm/llm.py:371-387`). No change needed there.
- `core/llm_pricing.py:calculate_llm_cost` already prices cache tokens correctly (2× multiplier for creation, 0.1× for reads — lines 167-171). No change unless we add new provider TTL tiers.
- `pflow report` surfaces per-node cached-token counts via existing trace-rendering machinery.
- **Gemini cost caveat:** LiteLLM had a Gemini cache double-counting bug (filed Sept 2025) that reported ~4× inflated costs. Closed via PR #15226 on 2025-10-07. Confirm the fix is present in the LiteLLM version pinned by this task, and add a regression test that exercises a Gemini cache hit and verifies the reported cost matches hand-calculation from raw tokens. If the fix is present and verified, `response_cost` is safe for Gemini; if not, fall back to computing from raw `cache_creation_input_tokens` / `cache_read_input_tokens` via our own pricing path. Outcome flows from Phase A.0 pricing investigation.
- **Gemini observability gap:** `cached_tokens` in LiteLLM responses populates for BOTH implicit caching (Gemini's free automatic mode) and explicit caching (what our `cache_control` markers trigger). They cannot be distinguished from the API response alone — only via GCP billing dashboard. `pflow analyze-cache --from-trace` should note this limitation in its Gemini output.
- **Model-specific minimum token thresholds:** vary materially by provider/model — Anthropic Opus 4.5+ and Haiku 4.5 require 4096 tokens (much higher than older Sonnet/Opus 1024). Validation looks up the threshold via `core/llm_capabilities.py::get_min_cache_tokens(model)` per DD#32; never hard-coded.

### Agent-Facing Documentation (`pflow guide`)

- New section in `pflow guide caching` covering:
  - **Automatic:** batch auto-prefix; no syntax required; seen via `pflow analyze-cache`.
  - **Explicit:** `## Cache` block + per-node `prompt_cache:` for cross-call reuse.
  - **When to declare `## Cache`:** run `pflow analyze-cache` — it identifies opportunities.
  - **Order invariant:** items must be referenced in declaration order; hard error otherwise.
  - **TTL opt-in:** `- ttl: 1h` on the section for long-running workflows or reruns within an hour.
  - **Relationship to `cache: bool`:** two different cache layers — `cache: false` disables pflow's local memoization; `prompt_cache: [...]` enables LLM provider prompt caching.
- Update `pflow guide llm` node section to cross-reference the caching guide.
- Update `see_also=["caching"]` on relevant validator diagnostics.

### Test Infrastructure

- `tests/shared/llm_mock.py` already redesigned around LiteLLM (Task 158). `MockLLMClient` exposes `call_history` (500-char truncated, default for legacy tests) AND `call_history_full` (untruncated, line 105 — added during Task 158 in anticipation of Task 159 cache-structure tests). Phase B/C cache tests read `call_history_full`; existing tests stay on `call_history`. No further mock-infrastructure work required for Task 159.
- `tests/conftest.py` root fixture (`mock_llm_client`) already patches `pflow.core.llm_client.complete` (Task 158); preserves the `/llm/` path skip for real-API integration tests. No changes for Task 159.
- New tests added:
  - `tests/test_core/test_diagnostic_id_field.py` — Phase B prerequisite: `Diagnostic.id` field, identity tuple update, `to_dict()` emission, category constants.
  - `tests/test_core/test_llm_capabilities.py` — per-model min-cache-token threshold lookup (per-version Anthropic numbers per DD#32); unknown-model fallback.
  - `tests/test_core/test_cache_block_parser.py` — parse valid/invalid `## Cache` blocks.
  - `tests/test_core/test_prompt_cache_validation.py` — reference resolution, order enforcement, subset validity, batch-scoped reference rejection, unused-chunk warning.
  - `tests/test_core/test_cache_analysis_warnings.py` — closed warning ID catalog: each ID emits exactly when expected, with the right severity and `context` payload.
  - `tests/test_core/test_cache_analysis_cross_workflow.py` — Tier 2 walker: rename detection, prose-mismatch, value-flow opportunity, batch sub-workflow enumeration.
  - `tests/test_core/test_cache_analysis_token_estimation.py` — three-tier strategy: trace history, `litellm.token_counter`, char-heuristic fallback. Confidence labels match data source.
  - `tests/test_nodes/test_llm/test_prompt_cache_rendering.py` — content-block structure per provider, cache_control markers placed correctly, structured output + cache composition, extended thinking + cache composition.
  - `tests/test_nodes/test_llm/test_batch_cache_prefix.py` — auto batch-prefix detection gated on prewarm, savings-ratio threshold (DD#33), N=1 skip.
  - `tests/test_cli/test_analyze_cache.py` — CLI output (text + JSON), exit codes, all four output modes (greenfield / steady-state / already-optimal / from-trace), per-call rendering rules (default-hide-clean, `--all-rows`), padding-advisory sensitivity floor.
  - `tests/test_cli/test_analyze_cache_from_trace.py` — trace-based verification: 2.1.0 fields available, 2.0.0 graceful fallback.
  - `tests/test_cli/test_analyze_cache_golden.py` — golden-file tests against the locked text/JSON output formats. Follow the existing `tests/test_core/test_mermaid_golden.py` pattern: parametrized cases, byte-exact equality, regen command embedded in the failure message (no `--update` mode — pflow has no convention for one). Fixtures live under `tests/test_cli/golden_analyze_cache/`. Use **synthetic minimal workflows** (one per mode: greenfield / steady-state / already-optimal / from-trace) — not the lyrics-generator. Lyrics-generator is reserved for hand-driven smoke tests during implementation. Cost values that drift across LiteLLM pricing updates: pin via `MockLLMClient.set_response(cost_usd=...)` to keep goldens stable.
  - `tests/test_mcp_server/test_analyze_cache_tool.py` — MCP parity.
  - `tests/test_runtime/test_prompt_cache_hash.py` — regression: existing workflows (no prompt_cache) hash identically.
  - `tests/test_runtime/test_trace_format_2_1.py` — new trace fields.

### Out of Scope (v1)

- **ClaudeCodeNode caching** — uses `claude_agent_sdk` directly; SDK handles cache transparently. Separate task if user controls desired.
- **`FixAction` typed substructure on `Diagnostic`** (per DD#28) — `suggestions: list[str]` for prose + `context: dict` for structured data covers v1. Reconsider only when `pflow cache apply` ships.
- **Cross-workflow auto-fix suggestions** — Tier 2 ships the warnings (`cache.cross-workflow-prose-mismatch`, `cache.cross-workflow-rename-detected`) per DD#26. The auto-suggested canonicalization fix ("here's the prose to use in both files") is deferred — picking which prose wins has no clearly right answer.
- **Implicit-opportunity n-gram detection** — finding 4k-token blocks shared across workflow files but not declared as cache chunks. v1 catches the explicit case (declared in one file, missed in another). N-gram matching across rendered prompts is a v1b possibility.
- **`pflow cache apply` command** — Level 3 (programmatic auto-apply of suggestions) deferred to v1b based on observed analyze-cache adoption.
- **Multi-breakpoint per-call placement** for fine-grained partial-prefix sharing — v1 uses single breakpoint per declared subset.
- **Per-item TTL** — block-level only in v1.
- **Automatic cache-order optimization** — pflow validates order but does not suggest reordering the `## Cache` block itself. Manual only.
- **Per-node inline cache blocks** (non-master) — everything cacheable goes in the master `## Cache`. No inline node-local cache blocks.
- **Gemini explicit cache lifecycle management** beyond what LiteLLM handles transparently.
- **Pre-warming as default** — opt-in via `- prewarm: true` only. v1 emits `cache.batch-prewarm-recommended` as an advisory warning when savings ratio is material (DD#33); never blocks `pflow run` (DD#36).
- **Per-tier savings projection** (1st / 2nd / 3rd run) — current-vs-rerun two-line is enough; full projection table is overkill.
- **Per-provider cost breakdown** in analyze-cache output — agents don't act on per-provider cost differently from total.
- **Graph visualization in analyze-cache** — text only. Use `pflow visualize` separately for graph rendering.
- **`pflow analyze-cache --diff`** mode comparing two analyses — v1b if real demand emerges.
- **Full prefix-tree optimization across the workflow** — v1 ships Level 2 suggestions (most-shared-first heuristic). Full graph optimization is deferred to v1b; scope and complexity will be assessed during Phase B–G plan writing.
- **MemoizationCache schema versioning or migration** — no version column exists; natural 24h TTL flush is the migration mechanism. Do not introduce schema versioning for this task.

## Implementation Notes

### Syntax Specification

Full example (from `song-creator.pflow.md` as it would look post-task):

````markdown
# Song Creator

...description...

## Inputs

### concept
...

### concept_brief
...

## Cache

Stable context objects reused across song-creator's LLM calls. Items must be
referenced by nodes in declaration order. Prose above each ${value} is
rendered as-is into the cacheable system message. Chunk identifier = the
template path with `${}` stripped.

- ttl: 1h

```cache
The concept we are building this song around — core idea, genre family,
narrator assignment:

${concept}

The per-concept material palette curated from source analyses — metaphor
mappings, kill moments, recognition moments, narrator blind spot:

${concept_brief}

The creative direction decisions — genre, voice/persona, contrast strategy,
audience, tonal register:

${creative-direction.response}

The structural blueprint — section layout, narrative arc, image system,
hook design, musical structure:

${song-architecture.response}

Hidden depth opportunities — double meanings, motif evolution, callbacks
identified by the easter-eggs step:

${easter-eggs.response}

The judge-selected chorus — a fixed creative constraint from write-lyrics
onward:

${chorus-chooser.winning_chorus}
```

## Steps

### creative-direction
- type: llm
- prompt_cache: [concept]
- temperature: 0.9
- prompt: ./creative-direction.prompt.md

### song-architecture
- type: llm
- prompt_cache: [concept, creative-direction.response]
- prompt: ./song-architecture.prompt.md

### write-lyrics
- type: llm
- prompt_cache: [concept, concept_brief, creative-direction.response, song-architecture.response, easter-eggs.response, chorus-chooser.winning_chorus]
- prompt: ./write-lyrics.prompt.md

### review-narrative
- type: llm
- prompt_cache: [song-architecture.response]
- prompt: ../specialist-reviews-narrative.prompt.md

### review-stranger-summary
- type: llm
- prompt: ../specialist-reviews-stranger-summary.prompt.md
# No `prompt_cache:` — intentional isolation for stranger legibility test.

### heavy-compute
- type: shell
- cache: false          # Existing memoization opt-out — unchanged semantics.
- command: date +%s
````

**Key points in the syntax:**

- `prompt_cache:` is a list of bare names. Names match cache chunk identifiers (stripped template paths).
- `cache: false` (existing feature) and `prompt_cache: [...]` (new feature) are independent fields, can coexist on the same node if needed.
- Omitting `prompt_cache:` = no declared LLM-provider caching for that node.
- `- ttl: 1h` on `## Cache` applies to the whole block; no per-item TTL in v1.

### Files to Modify

Detailed file-level modifications and patch ordering live in the implementation plan (`implementation/plan-phase-B-through-G.md`, written after Task 158 merges). High-level touch points by area:

- **Diagnostic extension (Phase B prerequisite)** — `core/diagnostic.py`: add `id` field on `Diagnostic`; add `CACHE_FAILURE_CATEGORY`, `CACHE_WARNING_CATEGORY`, `CACHE_ADVISORY_CATEGORY` constants AND register them in `CATEGORY_TITLES` (renderer falls back to a generic title without the entry — verified pattern at `core/diagnostic.py`). `execution/executor_service.py:_FAILURE_CATEGORY_MAP` (lines 29-44): add `"cache_failure": "cache_failure"` entry alongside the existing `"llm_failure"`. The dict-VALUE string and the `CACHE_FAILURE_CATEGORY` constant in `core/diagnostic.py` must be the same literal `"cache_failure"` — same dual-invariant pattern documented at `executor_service.py:33-37` for `LLM_FAILURE_CATEGORY`. (Note: this dual invariant is between the string-constant and the dict-VALUE, NOT between `_FAILURE_CATEGORY_MAP` and `CATEGORY_TITLES` — `CATEGORY_TITLES` is a separate concern: renderer titles dict that needs its own entry per category, with a friendly title string.) `cache_warning` and `cache_advisory` only need the constant + `CATEGORY_TITLES` entry — they're emitted by validators/analyzers, not through typed exceptions, so they don't need a `_FAILURE_CATEGORY_MAP` entry. `core/diagnostic_render.py`: add category-aware dispatch in `_format_warning_or_info_diagnostic` for cache-category warnings (mirrors `template_error` precedent). Per DD#27 / DD#28.
- **Per-model capabilities** — new module `core/llm_capabilities.py` with `get_min_cache_tokens(model: str) -> int`. v1 hardcoded; v1.x may wrap LiteLLM `model_cost`. Per DD#32.
- **Markdown parser and IR schema** — new `## Cache` section type and code-block handling; new top-level `cache` field and per-node `prompt_cache` + `prewarm` fields with `additionalProperties: False` extensions.
  - **NEW STRUCTURAL RULE**: today's parser allows `- key:` params and tagged code blocks **only inside `### entities`** (`markdown_parser.py:271-274,422-447` — orphan content under `##` is an error). `## Cache`'s shape (inline `- ttl: 5m` plus a single ` ```cache ` block, NO `### entities`) is a NEW shape and requires extending the state machine. Phase B work: add `_SectionType.CACHE`, register in `_KNOWN_SECTIONS`, add `_SECTION_DISPLAY_NAMES` and `_SECTION_SYNTAX_HINTS` entries, add `_resolve_section` branch (`markdown_parser.py:571-593`), and extend the parsing state machine to permit a section-level `- ttl:` param + section-level tagged code block under `## Cache` specifically (other sections retain the entity requirement). Chunk-splitting (one chunk = `[prose-before-${var}][${var}]`) is parser-internal: no new chunk separator syntax — `${var}` references are themselves the separators. The chunk identifier is computed by stripping `${}` from the variable expression.
- **Validation** — cache reference validation lives in shared `data_flow.py::validate_data_flow()` (picked up by both `WorkflowValidator` and `compile_validation`); structural rules in `FLOW_IR_SCHEMA`.
- **Adapter cache rendering** — extend `src/pflow/core/llm_client.py::complete()` to accept rendered cache content blocks and emit them as the system message with `cache_control` markers. The adapter API surface and translation logic for Anthropic/Gemini/OpenAI are already in place from Task 158; this adds the cache-block emission path.
- **LLM node** — pass `prompt_cache_items` from `NodeConfig` into the adapter; render cache chunks (resolve template values) before the call.
- **Runtime compilation and engine** — extract `prompt_cache` and `prewarm` into `NodeConfig`; conditional inclusion in `compute_node_config` memo hash (mirroring `batch_config` precedent); `cache_age_sec` and `cache_source` wired into trace events; pre-warm execution in batch handling.
- **Tracing** — bump trace format to 2.1.0; new fields per the Trace Format requirements. The trace-collector seam itself (Task 158's `shared["__trace_collector__"]` save/restore + adapter `trace_hook`) does not change.
- **New CLI command and analysis package** — `cli/commands/analyze_cache.py`; new package `core/cache_analysis/` exposing:
  - `analyze.py` — full analysis (the `analyze-cache` CLI consumer)
  - `summarize.py` — one-line nudge for `--dry-run`
  - `cross_workflow.py` — Tier 2 walker (per DD#26)
  - `token_estimation.py` — `litellm.token_counter` wrapper with lazy import
  - `padding_advisor.py`
  - `warning_catalog.py` — closed list of `cache.*` warning IDs
  - `render_text.py` — text output renderer (markdown-formatted)
- **MCP service and tool** — `analyze_cache` method on the execution service + `@mcp.tool()` registration mirroring `plan_workflow`.
- **Test infrastructure** — extend `MockLLMClient` to accept and assert on cache content blocks (the `call_history_full` field exists from Task 158 in anticipation); add new test files per the Test Infrastructure section above.
- **Documentation** — new `pflow guide caching` page; mintlify reference updates; clarification of `cache: false` (memo opt-out) vs `prompt_cache:` (LLM-provider caching) everywhere both appear.

### Implementation Phasing

**Phase 0 + Phase A are complete in Task 158** (LiteLLM verification spike + library migration + typed-exception architecture + diagnostic pipeline + tracing redesign + perf fix). This task picks up at Phase B.

**Phase B — `## Cache` block parsing + `prompt_cache:` and `prewarm:` fields.** Markdown parser, IR schema, validation (membership, order, unused chunk warnings) via shared `data_flow.py`. No rendering yet.

**Phase C — Cache rendering into LLM calls.** The adapter renders cached prefix with `cache_control` markers. `compute_node_config` updated conditionally. Tracing captures cached-token counts. End-to-end on Anthropic first, then Gemini, then OpenAI.

**Phase D — Auto batch-prefix + prewarm semantics.** Static-prefix detection in batch prompts; serialize-first-then-fan-out execution. The `cache.batch-prewarm-recommended` advisory emission is part of Phase F (analyze-cache + dry-run), not Phase D — runtime never blocks on prewarm.

**Phase E — Trace format 2.1.0.** New per-event and top-level fields for cache correlation.

**Phase F — `pflow analyze-cache` command + MCP parity + `--dry-run` nudge.** Static analysis (Level 2), `--from-trace` mode, JSON output, MCP tool registration.

**Phase G — Deterministic serialization + guide updates.**

Each phase has its own tests; each merges independently. Phases B–D can land in parallel. Phase E enables richer Phase F. Phase G wraps. The implementation plan covering Phases B–G is written separately once Task 158 merges (informed by concrete post-migration code shape).

### Non-Obvious Integration Points

These are facts the implementation plan must respect; specific file paths and line numbers belong in the plan.

- **Memo cache hash conditional inclusion.** `compute_node_config` (verified at `runtime/engine/instrumentation.py:139-170`) already has 3 conditional inclusions: `if static_params: config["params"] = ...`, `if template_params: config["template_params"] = ...`, and `if batch_config: config["batch"] = {...}` (note: the dict key is `"batch"`, not `"batch_config"`). Robust precedent. `prompt_cache` content follows the same idiom: `if prompt_cache_content: config["prompt_cache"] = prompt_cache_content`. A regression test asserting pre- and post-task hash equality for no-`prompt_cache` workflows is mandatory.
- **`test_plan_drift.py` is sacred.** 32 tests asserting planner ↔ runtime parity. Must remain green when `compute_node_config` is touched.
- **Prompt flattening in template resolution.** By the time `LLMNode.prep()` reads `self.params["prompt"]`, it's a fully-resolved flat string. Auto batch-prefix detection must read from the UNRESOLVED template (the raw `${var}` form), not the rendered string — the position of `${item.X}` is only identifiable pre-resolution.
- **Auto batch-prefix detection placement.** The unresolved template is preserved at `NodeConfig.template_config.template_params["prompt"]` (verified at `runtime/engine/types.py:12-46`). `LLMNode` does NOT currently have access to its own `NodeConfig` — it sees only `shared` and resolved `self.params`. So auto batch-prefix detection cannot live in `LLMNode.prep()` without new plumbing. Three options for Phase D plan-writing:
  - **(a) RECOMMENDED.** Engine injects the unresolved batch-bearing template under a reserved key in `node.params` before calling `node._run`. Minimal new plumbing; LLMNode reads from `params` as it does today, performs detection during prep(), and emits the marker via the cache-content blocks list it passes to `complete()`.
  - (b) Engine passes `NodeConfig` to LLMNode via a reserved `shared` key. Broader access; arguably overscopes.
  - (c) **REJECTED post §29 verification**: spec previously recommended moving detection into `runtime/engine/batch_executor.py`. Codebase verification revealed `batch_executor.py` does NOT do per-item template resolution — it only resolves the outer `items_template` via `resolve_batch_items` and delegates per-item prompt resolution to a callback (`engine._execute_single_node`). The static prefix portion of the LLM prompt is not in batch_executor's scope; option (c) would force batch_executor to gain a new partial-template-resolution responsibility, crossing layer boundaries. Option (a) avoids this entirely.
  Plan-level decision; the spec mandates only that the unresolved template MUST reach LLMNode somehow, and option (a) is the path-of-least-resistance.
- **Adapter integration point.** Cache rendering belongs at the adapter call boundary (the existing `complete()` invocation inside `LLMNode._call_llm`) — inside the ThreadPoolExecutor timeout budget and inside the retry loop. Do NOT put rendering in `prep()` or before `pool.submit` (no timeout protection).
- **Sub-workflow compile-once cache.** `WorkflowExecutor._compiled_workflow_cache` is keyed by resolved workflow path. New IR fields (e.g., the `cache` section) should not affect this keying — they're part of the compiled form, which is what's cached. Tests must cover the re-compile-with-different-cache-block case.
- **Trace seam already in place from Task 158.** `shared["__trace_collector__"]` save/restore + adapter `trace_hook` parameter is the established mechanism. Trace-format-2.1.0 cache-metadata fields (cache_key, cache_source, cache_age_sec, workflow_path) layer on top via the existing `_add_llm_data` method (`runtime/workflow_trace.py:202`) — the single site that reads `llm_usage` and writes per-event LLM metadata. (Note: a stale comment at `workflow_trace.py:545` references this as `_attach_llm_call_to_event`; the actual function name is `_add_llm_data`. Cleanup of that stale reference is out of scope for Task 159 but worth flagging if Phase E touches that file.) No new seams required.
- **Diagnostic pipeline already in place from Task 158.** Cache-validation errors emit via the established `Diagnostic` + `_FAILURE_CATEGORY_MAP` + `_diagnostic_context` pipeline. New failure category (e.g. `"cache_failure"` if needed) follows the same `category` constant + `to_diagnostics()` override pattern that `LLMCallError` uses.

### Edge Cases

- **Empty `prompt_cache` list.** `prompt_cache: []` = no cache. Node proceeds without prefix; no markers; hash matches the no-prompt-cache case (conditional inclusion doesn't fire for empty list).
- **Cache value resolves to empty string or None.** Render as empty; provider may cache an empty block. Warn if the combined block is below provider minimum.
- **Cache block references a step output on a branch that didn't execute.** Validation-time warning (declarations are static; branch execution is dynamic). Runtime rendering skips the missing item gracefully.
- **Batch sub-workflow invocations.** Each invocation has its own cache (different inputs → different rendered bytes). No cross-invocation cache within the batch. Cross-run cache hits via TTL.
- **Retry loops.** A cached call that retries (e.g., timeout) re-sends the same bytes → hits its own cache on retry. Free second-attempt.
- **Existing `cache: false` preserved.** A node with `- cache: false` AND `- prompt_cache: [...]` still opts out of pflow memo caching but still sends `cache_control` markers to the provider. Two independent layers.
- **Parallel batch race on first cache write.** First call writes cache (1.25× or 2× cost); subsequent calls read at 0.1×. Parallel fan-out without pre-warming pays write cost on ALL calls. Analyze-cache flags this when batch size is large; `- prewarm: true` opts into serialize-first-then-fan-out.

### Cost Model Reference

Per provider:

- **Anthropic:** cache write 1.25× (5-min TTL) or 2× (1-hour TTL); cache read 0.1×. Max 4 cache_control markers per request. Per-model minimum cacheable tokens: see DD#32 (1024 / 2048 / 4096 depending on version).
- **OpenAI:** cache write 1× (no surcharge); cache read 0.5× (50% discount). Automatic at ≥1024 tokens. Routing hint via `prompt_cache_key`.
- **Gemini:** via LiteLLM's translation; pricing follows Google's `cachedContents` model. Min 1024 tokens.

Break-even reads: 1-hour extended TTL on Anthropic breaks even at 3 reads. 5-min default breaks even at 1 read.

## Verification

### Requirements-Level

- All requirements in the Library Replacement section verified by an end-to-end test hitting Anthropic, Gemini, OpenAI with real API (gated by `RUN_LLM_TESTS=1`). Extend `tests/test_nodes/test_llm/test_llm_integration.py:has_openai_api_key()` to also gate Anthropic and Gemini tests.
- All requirements in the `## Cache` Block Parsing section verified by parser unit tests — valid and invalid inputs.
- Order validation verified by a test that writes a workflow with out-of-order `prompt_cache:` and asserts the exact error message format.
- Cache rendering verified by a mock provider that captures message structure and asserts content blocks and `cache_control` markers are placed correctly per provider.
- Auto batch-prefix caching verified by a batch workflow that asserts two cache_control markers in rendered messages (one for declared cache, one for batch prefix).
- Memo cache hash stability verified by a regression test: hash of a workflow without `prompt_cache` is identical pre- and post-task.
- Trace format 2.1.0 verified by parsing a 2.1.0 trace and asserting new fields; backwards compat verified by parsing a 2.0.0 trace and confirming no errors.

### Scenario-Level

- **Lyrics-generator end-to-end.** Run the lyrics-generator workflow once, record cost. Add `## Cache` blocks + `prompt_cache:` references per the task spec. Run again, assert input-cost reduction is ≥40% (conservative floor vs. 50–70% estimate). Rerun within 1h, assert ≥70% reduction.
- **Sub-workflow isolation.** Run `song-creator` standalone via `pflow song-creator.pflow.md concept=... concept_brief=...`. Assert caching works without a parent workflow.
- **Stranger-summary isolation.** Assert `review-stranger-summary` (no `prompt_cache:`) produces a rendered message with no `cache_control` markers, and its trace shows `cache_read_input_tokens == 0`.
- **Cross-workflow cache hit.** Run song-creator from parent. Assert review-narrative's LLM call hits the cache populated by song-creator's earlier calls (when labels match).
- **Existing `cache: false` preserved.** Test that a workflow using `- cache: false` on a shell node continues to work exactly as today (memo opt-out). No regression.
- **Analyze-cache pre-run.** Run `pflow analyze-cache lyrics-generator.pflow.md`; assert output contains top-actions section, per-call table, shared-context candidates.
- **Analyze-cache from-trace.** Run workflow, then `pflow analyze-cache --from-trace <trace>`; assert output compares predicted to actual and flags discrepancies. Test with 2.0.0 and 2.1.0 traces (graceful fallback on 2.0.0).
- **Dry-run nudge.** Run `pflow run --dry-run` on a workflow with cache opportunities; assert the one-line nudge appears in both text and JSON output. Silent on workflows without opportunities.
- **MCP parity.** Invoke `analyze_cache` MCP tool; assert JSON response matches CLI `--format=json` output.
- **Padding advisory.** Set up a workflow where one node has a subset that doesn't start at position 1; assert analyze-cache emits a padding recommendation with cost math.

### Provider Matrix

- Anthropic (primary target): Sonnet and Opus 4.5/4.6/4.7. Validate cache_control markers, TTL, cached-token reporting.
- Gemini 2.5 / 3: cachedContents via LiteLLM. Validate cache appears in usage metrics.
- OpenAI GPT-5-family: automatic caching fires; `prompt_cache_key` optionally improves hit rate on parallel batches.
- Ollama: non-caching baseline still works; no cache markers leak into requests.

### Regression

- All ~212 existing LLM-related tests adapted and passing. Most should be transparent (assert on shared-store outputs).
- Existing workflows without `## Cache` blocks execute identically to pre-task behavior.
- No new dependencies beyond LiteLLM (and its transitive deps) added to `pyproject.toml`.
- `pflow guide` output includes the new caching section.
- `test_plan_drift.py` parity tests continue to pass (verify planner ↔ runtime cache-key agreement).
- Workflow examples in `examples/` (7 files using `- cache: false`) execute identically post-task.

## References

### Related Tasks

- **Task 158 — LiteLLM migration (PREREQUISITE).** Provides the adapter, typed exceptions, diagnostic pipeline, trace seam, and cost contract this task plugs into.
- Task 66 — Structured Output for LLM Node (preserved through Task 158's adapter; `response_format` continues to work).
- Task 96 — Batch Processing (`batch_config` in hash is the conditional-inclusion precedent for `prompt_cache`).
- Task 106 — Workflow Iteration Cache (the memoization cache layer; distinct from prompt cache — `cache: bool` opt-out, not `prompt_cache:`).
- Task 108 — Smart Trace Debug Output (trace format 2.0.0 introduced here; this task bumps to 2.1.0).
- Task 121 — Workflow Testability (complementary verification infrastructure).
- Task 131 — Batch Error Handling (precedent for subdict additions to batch config hash).
- Task 133 — Unified Per-Node Storage for Trace and Cache (may interact with how cache metadata is persisted).
- Task 136 — Recursive Sub-Workflow Validation at Parse Time (validator recursion pattern).
- Task 143/144/147 — Unified Diagnostic System (Diagnostic class, severity, structured context — extended further in Task 158).
- Task 148 — Template Error UX Consolidation (`build_template_error_diagnostic` pattern).
- Task 149 — Output Routing (stderr vs stdout contract).
- Task 150 — Wire WorkflowValidator into Save Path.
- Task 152 — MCP Server CLI Surface Parity (governing invariant for `analyze_cache` tool).
- Task 153 — Reject Undeclared Sub-Workflow Inputs (set-algebra validation pattern).
- Task 156 — `--dry-run` flag with cache plan (sibling analysis feature; shares `MemoizationCache.get_latest_for_node`).

### Motivating Workflow

- `/Users/andfal/projects/music-generation/workflows/lyrics-generator/lyrics-generator.pflow.md` — the pipeline that motivated this task. ~181 LLM calls per run; clear Patterns A–E of redundancy.
- `/Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md` — the heaviest sub-workflow; Pattern A (cross-call) concentration, 15+ sequential LLM calls sharing 4–6 context objects.
- `/Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md` — batch-heavy patterns (B/D) with 8 chorus-gens + ~34 scoring calls sharing a large rubric.

### Provider Documentation

- LiteLLM caching: https://docs.litellm.ai/docs/completion/prompt_caching
- LiteLLM local models: https://docs.litellm.ai/docs/providers/ollama
- Anthropic prompt caching: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- OpenAI prompt caching: https://openai.com/index/api-prompt-caching/ , https://developers.openai.com/api/docs/guides/prompt-caching
- Gemini context caching (via LiteLLM's `cachedContents` translation).

### Planned Follow-Ups

- **Tier 2 verification: cross-workflow cache-hit prediction.** Implemented after v1 based on observed mismatch patterns from real-world usage. Should compare prose labels across workflow files when a parent invokes a sub-workflow, warn on divergence that would break byte-level match.
- **Multi-breakpoint per-call placement.** If fine-grained partial-prefix sharing is requested, extend to up to 4 cache_control markers on Anthropic. **Note: Anthropic-only** — Gemini's `CachedContents` API is architecturally single-blob (one immutable cached reference per request); multiple `cache_control` markers on Gemini silently drop all but the last one.
- **Per-provider cache strategy selector — Gemini implicit vs explicit break-even.** Gemini has TWO caching mechanisms: implicit (automatic, free, no storage cost, activates when prefix is stable across requests) and explicit (via `cache_control` markers, 90% read discount BUT charges storage cost by duration). For small or rarely-reused caches, explicit can cost MORE than no caching. Break-even for Gemini 2.5 Flash is roughly 4 queries/hour per million cached tokens. Task 158 v1 always emits explicit markers when `## Cache` is declared. Follow-up: `pflow analyze-cache` computes break-even per node and recommends implicit-only (remove `## Cache` declaration) when explicit is net-negative. May also introduce `- mode: implicit | explicit` on cache blocks.
- **Automatic cache-order optimization suggestion.** `pflow analyze-cache --suggest-order` computes an ordering that maximizes cross-call prefix sharing weighted by item sizes.
- **Per-item TTL.** If real usage shows mixed hot/cold cache items in the same workflow.
- **Pre-warming as default for batch fan-outs above N items.**
- **Automatic padding application.** If advisories are consistently accepted, consider an opt-in "aggressive" mode that auto-pads.
- **Claude Code node caching controls.** If user controls are wanted for `ClaudeCodeNode` (currently SDK-managed).
- **`pflow cache clear` CLI command.** For forced-invalidation scenarios (currently no user-facing CLI exists; programmatic API only).
- **Direct read of `~/.config/io.datasette.llm/keys.json`** — for users migrating from Simon's `llm` library who haven't transferred their stored keys to env vars. Deferred to v1.x; current migration story is manual via `pflow settings set-env`.
- **Per-TTL cache-write pricing** — Anthropic charges 1.25× (5-min) vs 2× (1h) for cache writes; LiteLLM's `completion_cost()` may not distinguish per-TTL. Verify in Phase E when 1h TTL becomes selectable.
