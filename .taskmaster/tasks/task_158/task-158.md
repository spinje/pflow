# Task 158: Prompt Caching via LiteLLM + Declarative `## Cache` Block

## Description

Introduce provider-level prompt caching to pflow workflows. Replace Simon Willison's `llm` library with LiteLLM (unified Anthropic/Gemini/OpenAI cache support), add a new `## Cache` top-level section to `.pflow.md` workflows for declarative cross-call context reuse, and ship `pflow analyze-cache` as the agent-facing diagnostic. Estimated input-cost reduction on LLM-heavy workflows: 50–70% per run, 80%+ on reruns within TTL. Motivating case: the `lyrics-generator` pipeline (`/Users/andfal/projects/music-generation/workflows/lyrics-generator/`) with ~181 LLM calls per run, of which a handful of large stable context objects flow through ~15 sequential calls per song path × 4 parallel songs.

## Status

not started

## Priority

high

## Problem

pflow workflows that chain many LLM calls pay for the same context tokens repeatedly:

1. **Intra-batch redundancy.** Batch fan-outs (e.g., `analyze-source` 6 specialists × N sources, `chorus-chooser` 8 chorus-gens + 34 scorings) send the same stable prefix to every call, with only per-item tails differing.
2. **Cross-call redundancy within a pipeline.** In `song-creator`, outputs from `creative-direction`, `song-architecture`, `easter-eggs`, and `concept_brief` flow through 15+ downstream LLM calls — `write-lyrics`, emotional/craft reviews, rewrite stages, suno-prompt generation. Each downstream call re-pastes 8–12k tokens of content it already produced.
3. **No provider-level caching.** Simon Willison's `llm` library — pflow's current LLM abstraction — does not expose Anthropic's system-prompt `cache_control`, Gemini's `cachedContents`, or OpenAI's `prompt_cache_key`. The `llm-anthropic==0.25` plugin's `cache: bool` option is limited to attachments and multi-turn history; it cannot cache system prompts or first-turn user content, which is where most of the value lives. The `llm` library's `Options` are declared `extra="forbid"`, so no kwarg passthrough exists.
4. **Agents cannot reason about cache.** Even if an author wanted to structure prompts for cacheability, there is no feedback loop telling them which calls share prefixes, which prompts have dynamic content high-up (breaking the cache), or how much money is being left on the table.

For the lyrics-generator specifically, back-of-envelope per-run input-cost reduction is 50–70% with a well-declared cache, and 80%+ on reruns within 1h TTL — meaningful money at the scale users iterate at. But this is blocked entirely by the library choice.

## Solution

Three tightly-coupled changes, shipped together because none provides value alone:

**1. Replace `llm` with LiteLLM.** LiteLLM provides a unified `cache_control: {type: ephemeral}` syntax that maps to Anthropic directly, Gemini via translation to `cachedContents`, and is a no-op on OpenAI (which caches automatically at ≥1024 tokens). Ollama and other local-model runtimes remain supported for non-caching use. Pflow's LLM node, tracing, reasoning-option handling, and test infrastructure rewire around LiteLLM. The `llm` library's CLI-based key storage (`llm keys get`) is replaced by environment variables and optional direct read of `~/.config/io.datasette.llm/keys.json` for users migrating from `llm`.

**2. `## Cache` block syntax for declarative cross-call caching.** A new top-level section in `.pflow.md`, alongside `## Inputs` / `## Steps` / `## Outputs`. Contains a `` ```cache `` code block with prose interleaved with `${var}` references — prose above each variable travels into the rendered system message as the cacheable label. Each workflow file (including sub-workflows) declares its own block scoped to its own inputs and step outputs. Individual LLM nodes opt in by listing a subset via a new `- prompt_cache: [name1, name2]` field (where names are the bare template paths, e.g., `concept`, `creative-direction.response`). Order matches the declaration block strictly; violation is a hard error. The existing `- cache: bool` field (per-node memoization opt-out — different cache layer) is untouched. See the **Syntax Specification** in Implementation Notes.

**3. `pflow analyze-cache` command for agent feedback.** Static analysis of a workflow's cache plan: per-node cache ratio, shared context candidates, warnings with concrete fixes, optional prefix-padding advisories, and a `--from-trace` mode that compares predicted cache behavior to actual cache hit/miss data from runtime traces. Output has a human-readable default and a `--format=json` for agent consumption with stable warning IDs. A shared `cache_analysis.summarize()` helper emits a one-line nudge in `pflow run --dry-run` output when actionable opportunities exist.

**Auto batch-prefix caching** runs alongside the declared cache, detecting the stable prefix of a batch prompt (text before the first `${item.X}`) and automatically inserting a `cache_control` marker. Bytes sent to the LLM are identical to what the author wrote. Visible in analyze-cache output; opt-outable per node with `- batch_cache: false`.

## Design Decisions

1. **LiteLLM migration is required, not optional.** The `llm-anthropic==0.25` plugin exposes only a `cache: bool` option that marks `cache_control` on the last attachment or the last content block of the last prior user message. It does not mark system prompts, first-turn user content, or arbitrary breakpoints — and `llm.models.Options` is pinned to `extra="forbid"`, so there is no kwarg passthrough or `extra_body` escape hatch. Caching system prompts and first-turn content is the core Task 158 use case. LiteLLM covers Anthropic + Gemini + OpenAI through one `cache_control` syntax; direct SDKs would require two code paths. Keeping `llm` + monkey-patching is fragile across plugin upgrades. The 5–10 engineer-day replacement cost is unavoidable for this use case.

2. **Explicit `## Cache` declaration, not silent restructuring.** Autodetecting "this value is reused, let me lift it out of the prompt file into a cacheable system prefix" would silently change the message structure the LLM receives. Even though the content bytes would be identical, the message assembly pattern differs (inline prose vs. structured system blocks). pflow's existing philosophy is explicit, visible workflow syntax — caching follows that. The author declares what's cached; pflow renders what was declared.

3. **Prose-above-variable maps to rendered prefix.** Inside the `` ```cache `` block, prose between `${var}` references travels verbatim into the system message alongside the value. The author writes what the LLM will see; no hidden labels are injected, no framing is rewritten. The block is a faithful render preview.

4. **Per-node references use bare names derived from the template path.** `${concept}` becomes `concept`; `${chorus-chooser.winning_chorus}` becomes `chorus-chooser.winning_chorus` as a bare string identifier. Nodes reference via `- prompt_cache: [concept, concept_brief, chorus-chooser.winning_chorus]`. No `[name]` markers inside the cache block are needed — each chunk has exactly one `${var}`, and stripping `${}` gives the chunk's identifier. Reads as "reference named cache chunks," not "substitute values into this list."

5. **New field named `prompt_cache:`, not `cache:`.** The existing `cache: bool` field is already reserved for per-node **memoization opt-out** (pflow's local cache layer). It is used in 7 example workflows, 14 test files, 5 CLAUDE.md files, the agent guide, and 3 user-doc pages. Overloading it to also mean "LLM provider prompt-cache subset" would create a field with two shapes (bool OR list) and two unrelated meanings. `prompt_cache:` is unambiguous (matches Anthropic/OpenAI/Gemini terminology), keeps the two cache layers visually distinct, has zero backwards-compat impact on existing workflows, and makes agent-authored workflows self-documenting.

6. **Strict order validation — error on wrong order.** Prefix-based caching requires calls that share context to present items in identical order. pflow enforces declaration order rigidly: a node's `prompt_cache:` list out-of-order is a hard error with a clear fix message showing both the declared and the wrong ordering. pflow never silently reorders. The workflow file is the honest source of truth for what the LLM will see.

7. **Block-level TTL, not per-item.** Single `- ttl: 1h` on the `## Cache` section covers all realistic cases. Per-item TTL would add complexity for a marginal optimization that's easier to chase by adjusting workflow structure. Default TTL is the provider default (typically 5 min); extended TTL is opt-in because it costs 2× on writes and only pays off with ≥3 reads.

8. **No auto-optimization for reruns.** Extended TTL (1h) is never auto-applied. Rerun benefits cost money on first-write; that tradeoff is the author's to make, not pflow's.

9. **Auto batch-prefix caching is on by default, but visible.** Within a batched LLM call, detecting the stable prefix before the first `${item.X}` and inserting `cache_control` does not change the bytes sent. It's free money. But it's visible in `pflow analyze-cache` output and opt-outable with `- batch_cache: false`. User decision during discussion: "B" (visible automatic) over fully automatic or fully explicit.

10. **Prefix padding is advisory, never auto-applied.** When a node's `prompt_cache:` subset doesn't start at position 1 of the master order, it doesn't cache-hit upstream writes. Extending the subset to include earlier items can unlock prefix hits at the cost of sending extra content at 0.1× read rate. pflow computes whether padding is net-positive per node and surfaces it as an **optional recommendation** in analyze-cache output. The author decides; pflow never modifies the workflow.

11. **Per-call breakpoint strategy: one `cache_control` marker per distinct subset end, in v1.** Within a call, pflow places one `cache_control` marker at the end of the rendered cache content. The whole subset caches as one entry. Calls with identical subsets cache-hit each other; calls with different subsets get independent cache entries. This uses 1–2 markers per call (with batch auto-prefix adding one more), well within Anthropic's 4-marker limit. Fine-grained multi-breakpoint placement for partial-prefix sharing is deferred to a follow-up if real usage shows demand.

12. **Sub-workflows declare their own `## Cache` block.** Each `.pflow.md` file is self-contained: its cache block references its own inputs and step outputs. This enables sub-workflows to run standalone with caching. Cross-workflow cache hits happen incidentally at the byte level when rendered prefixes match — pflow does not coordinate caching across workflow boundaries. For this incidental hit to fire, parent and child should use identical prose labels for the same logical values.

13. **Deterministic serialization of cached values.** Complex values (dict, list) serialize via sorted-key JSON with stable formatting. Without this, two calls with the "same" concept could produce different cached bytes (dict key ordering) and silently miss cache. One-line fix, prevents a whole class of silent failures.

14. **Tracing redesigned around a pflow-owned seam, not a global monkey-patch.** `runtime/workflow_trace.py:520-574` currently monkey-patches `llm.get_model` as a process-global reference-counted side effect. LiteLLM is a function call (`litellm.completion`), not a module with a function attribute — the current interception pattern doesn't translate. Replace with a pflow-owned adapter (new file `src/pflow/core/llm_client.py`) that wraps `litellm.completion`, exposes a stable internal interface, and lets the trace collector wrap it naturally.

15. **Reasoning-options handling via hardcoded provider map, not library introspection.** The current `nodes/llm/llm.py:99` introspects `model.Options.model_fields` (Simon's Pydantic options) to decide which reasoning-param name to pass (`thinking_effort` / `reasoning_effort` / `thinking_budget` / etc.). LiteLLM doesn't expose a comparable contract. Replace with an explicit provider-to-option-name mapping inside pflow (`src/pflow/core/llm_reasoning_map.py` or similar). Provider detection continues via model-name sniffing (same as current `smart_filter.py:175-180`).

16. **`llm keys` subprocess replaced by env vars + optional direct read of `~/.config/io.datasette.llm/keys.json`.** LiteLLM uses env vars natively. For users migrating from `llm`-stored keys, pflow optionally reads the legacy keys.json file directly — no subprocess dependency, no `llm` binary requirement. `pflow settings llm` help text is rewritten to point at env vars.

17. **Verification tier strategy: ship Tier 1 (static in-file) + Tier 3 (trace-based) in v1; Tier 2 (cross-workflow prediction) is a planned follow-up.** Tier 1 catches all in-file correctness issues cheaply. Tier 3 is the source-of-truth using actual provider-reported cache data from runtime traces. Tier 2 (predicting cross-workflow cache hits before running) requires cross-file graph analysis and prose-label comparison — valuable but not required for the feature to be useful.

18. **Pre-warming for batches is opt-in, not default.** Firing the first batch call alone and waiting for cache write before fanning out trades ~one call's latency for ~5× cost reduction on the remaining N-1 calls. Default off (latency preservation); opt-in via `- prewarm: true` on the batch node or via `pflow analyze-cache` suggestion when batch size is large.

19. **`prompt_cache` rendered content must be in `compute_node_config`, conditionally.** The memo-cache hash (`runtime/engine/instrumentation.py:140-179`) determines which cached output is served. If `prompt_cache` content prepends to the system message at runtime but is NOT in the hash, existing cache entries hit for upgraded workflows and serve outputs produced WITHOUT the prepended content — a silent correctness bug. Fix: thread the rendered `prompt_cache` content into `compute_node_config` **conditionally** (only when `prompt_cache` is non-empty) so nodes that don't opt in retain their existing hash. Precedent: `batch_config` is added the same conditional way (Task 96).

20. **Cache validation lives in the shared `core/workflow/data_flow.py::validate_data_flow()` module.** pflow has two validation entry points — `WorkflowValidator.validate()` (save-time + pre-execution) and `runtime/compilation/compile_validation.py::_prepare_compilation()` (compile-time) — both of which already call the shared `data_flow.py`. Putting cache reference validation there means both entry points pick it up for free. Schema-level structural rules (cache block shape, required fields) go into `core/ir_schema.py::FLOW_IR_SCHEMA` which both entry points also gate on. No duplicate validator code.

21. **ClaudeCodeNode is out of scope.** `src/pflow/nodes/claude/claude_code.py` uses `claude_agent_sdk` directly (not the `llm` library), and the SDK handles Anthropic prompt caching transparently — cache tokens already appear in `llm_usage` (`claude_code.py:865-887`). Task 158 does not need to touch ClaudeCodeNode. If cache-control user parameters for Claude Code are wanted, that is a separate task.

22. **Trace format bumped to 2.1.0.** The `analyze-cache --from-trace` feature benefits materially from cache metadata that today's format 2.0.0 doesn't carry. New fields: `event["cache_key"]` on cache-hit and cache-write events (for exact SQLite correlation), `event["cache_source"]: "memo" | "in_process"` (distinguishes the two pflow cache layers — distinct from LLM-provider cache), `event["cache_age_sec"]` on cache-hit events (for TTL analysis), `trace["workflow_path"]` at the top level (for cross-trace correlation). `format_version` → `"2.1.0"`. The existing consumer gate `format_version.startswith("2.")` is forward-compatible, so 2.0.0 readers keep working on 2.1.0 files (ignoring the new fields).

23. **Dual-mode mock for LiteLLM response shape.** `tests/shared/llm_mock.py` truncates prompts to 500 chars in `call_history` (`llm_mock.py:30`). Cache-structure testing needs full prompts to verify message block assembly. Extend the mock with an untruncated-prompt mode (or a parallel field); do not remove the truncation for existing tests — several assert against the 500-char invariant.

24. **MCP parity with existing `plan_workflow` pattern.** `pflow analyze-cache` as a CLI command means an equivalent `analyze_cache(workflow, parameters)` method on `mcp_server/services/execution_service.py` and `@mcp.tool()` registration in `mcp_server/tools/execution_tools.py`. Task 152 (MCP parity) is the governing invariant: "every shared formatter has two call sites."

25. **`--dry-run` cache nudge via shared analysis module.** The `cache_analysis` module exposes two entry points: `analyze()` (full plan for `pflow analyze-cache`) and `summarize()` (one-line nudge for `--dry-run` footer). `summarize()` emits a `Severity.INFO` `Diagnostic` that the existing `plan_formatter.py` loop (`plan_formatter.py:139-142`) already renders; no new formatter code is needed. Nudge is silent when the cache is already optimal.

## Dependencies

None. The prerequisites are internal:

- Task 95 introduced the unified `llm` library integration — this task replaces that work with LiteLLM but does not depend on new infrastructure from task 95 beyond what's already merged.
- Task 156 (`--dry-run`) is orthogonal but synergistic — both involve pre-run cost modeling. `pflow analyze-cache` shares the planner's `MemoizationCache.get_latest_for_node()` for size estimates on upstream LLM outputs. No merge-order constraint.
- Task 108 (Smart Trace Debug Output) defined trace format 2.0.0. This task bumps to 2.1.0; `trace_report.py`'s `format_version.startswith("2.")` gate keeps existing consumers compatible.

Related but explicitly out of scope:

- Task 121 (Workflow Testability) — complementary, not blocking.
- Task 133 (Unified Per-Node Storage for Trace and Cache) — may interact with how cache metadata is stored in traces; coordinate during implementation but do not block.
- Task 152 (MCP Server CLI Surface Parity) — defines the parity invariant this task must respect.

## Requirements

### Library Replacement (LiteLLM)

- Replace all `import llm` / `from llm import ...` imports in `src/pflow/` with a pflow-owned adapter (new `src/pflow/core/llm_client.py`) that wraps `litellm.completion`.
- Preserve current LLM-node external behavior for non-cached calls: same parameters accepted (`model`, `temperature`, `max_tokens`, `system`, `prompt`, `images`, `output_schema`, `reasoning_effort`, `reasoning_max_tokens`, `model_options`, `timeout`), same output shape (`response: str|dict`, `error: str`, `llm_usage: dict`).
- Reasoning-options mapping handled by an explicit provider-to-option-name table inside pflow (replaces `model.Options.model_fields` introspection at `nodes/llm/llm.py:99`). Live in new `src/pflow/core/llm_reasoning_map.py`.
- Structured output (`output_schema` → JSON Schema dict OR Pydantic model) preserved; rendered to LiteLLM's structured-output mechanism (`response_format`).
- Image attachments (`images: list[str]`) supported across Anthropic, OpenAI, Gemini (each provider's encoding handled by LiteLLM).
- Ollama and other local-model runtimes remain supported for non-caching use. First-class Ollama; best-effort vLLM / LM Studio / Llamafile.
- Exception handling: detect LiteLLM's equivalent of `UnknownModelError` and `NeedsKeyException` and produce pflow's existing user-facing error messages (currently detected by class-name string matching at `nodes/llm/llm.py:435-452`).
- Key discovery: read env vars (LiteLLM's native path) and optionally `~/.config/io.datasette.llm/keys.json` for users migrating from `llm`. No subprocess shelling to `llm` CLI binary (`core/llm_config.py:40-99, 348-387` replaced).
- `pflow settings llm` CLI subgroup updated (`cli/commands/settings.py:40-41, 451-467`) — help text no longer references Simon's `llm` binary; point users at env vars and `pflow settings llm` itself.

### `## Cache` Block Parsing

- New top-level section `## Cache` recognized by the markdown workflow parser (`core/markdown_parser.py`). Added to `_SectionType` enum, `_KNOWN_SECTIONS`, `_SECTION_DISPLAY_NAMES`, `_SECTION_SYNTAX_HINTS`, `_resolve_section()`.
- Optional `- ttl: <duration>` parameter on the section (`5m` default; `1h` extended; reject other values in v1).
- Contains a tagged `` ```cache `` code block; multiple cache code blocks in one section are a syntax error.
- The `cache` code block content is a sequence of `[prose block][${var} reference]` pairs. Prose between variables, prose before the first variable, and the variable itself are rendered as a single content chunk.
- **Exactly one `${var}` per chunk.** Two or more `${var}` in a chunk is a syntax error (prose should describe its value, not contain further template references).
- Each `${var}` must resolve to a valid workflow input or upstream step output in the containing workflow file (reference resolution, same rules as existing templates).
- `${item.X}` (batch-scoped) or any non-stable reference in a cache block is a syntax error.
- Empty cache block is a syntax error (must have ≥1 variable).
- Prose-only cache block (no variables) is a syntax error.
- Cache chunk identifier = stripped template path. `${concept}` → `concept`; `${chorus-chooser.winning_chorus}` → `chorus-chooser.winning_chorus`. Duplicate identifiers (same `${var}` appearing twice) is a syntax error.
- New top-level IR field `cache` added to `core/ir_schema.py::FLOW_IR_SCHEMA.properties` (top-level `additionalProperties: False` means the schema must be extended). Shape: `{"cache": {"type": "object", "properties": {"ttl": {"enum": ["5m", "1h"]}, "items": {"type": "array", "items": {...}}}}}`.
- `_source_line` metadata injected on cache block + per-chunk for error-rendering (follow same pattern as `markdown_parser.py:1030-1033` for code blocks).

### Per-Node `prompt_cache:` Field

- New node parameter `- prompt_cache: [name1, name2, ...]` accepted on `type: llm` nodes.
- Names are bare strings matching cache chunk identifiers (stripped template paths). Examples: `concept`, `concept_brief`, `creative-direction.response`, `chorus-chooser.winning_chorus`.
- Items must be a subset of the containing workflow's `## Cache` block items (error if referencing an undeclared name).
- Order of items in `prompt_cache:` must match declaration order in `## Cache`. Out-of-order is a hard error with a fix message showing both orderings.
- Absence of the `prompt_cache:` field means "no declared cache" — the node runs with no cross-call caching context (intentional isolation, e.g., `review-stranger-summary` pattern).
- Empty list `- prompt_cache: []` is valid and equivalent to absence.
- Per-node inline cache is NOT supported in v1 — everything cacheable goes in the master `## Cache`.
- IR schema extension at `core/ir_schema.py:152-189` (per-node): add `prompt_cache: {"type": "array", "items": {"type": "string"}}`. Per-node `additionalProperties: False` at line 186 means this must be added.
- Existing `cache: bool` field remains unchanged in schema and semantics. The two fields coexist on the same node.

### Cache Rendering into LLM Calls

- Cache rendering happens inside the pflow-owned adapter (`llm_client.complete(...)`) before it calls `litellm.completion(...)`. The adapter is called from `LLMNode._call_llm` (`nodes/llm/llm.py:271-321`), after kwargs build, before the API call — inside the ThreadPoolExecutor timeout budget.
- For each LLM node with a declared `prompt_cache:` list, pflow renders the cache content as a system-message prefix:
  - One content block per `[prose + ${var}]` chunk, in declaration order filtered to the node's subset.
  - Anthropic/Gemini: a `cache_control: {type: ephemeral}` marker on the final chunk (v1 single-breakpoint strategy). TTL translates to Anthropic's extended cache (via LiteLLM's passthrough of `ttl` when supported).
  - OpenAI: content is the prefix; no markers needed. Optionally emit a `prompt_cache_key` computed from a hash of the rendered cache content (improves routing consistency across parallel batch calls).
- The node's `prompt:` (the task) is rendered as the user message, after the cacheable system prefix.
- If the rendered cache content is below the provider's minimum token threshold (1024 for Anthropic sonnet/opus, 2048 for haiku), pflow issues a validation-time warning but does not fail the call — provider silently no-ops.
- Rendering failures (template resolution error on a cache item) follow the `build_template_error_diagnostic` pattern at `runtime/engine/template_errors.py:320`, returning an error-dict from the adapter to avoid wasted retries.

### Auto Batch-Prefix Caching

- For any `type: llm` node with a `batch:` config, pflow detects the static prefix of the rendered prompt (text before the first `${item.X}` or other batch-scoped reference).
- Detection reads from the unresolved template at `config.template_config.template_params["prompt"]` (the raw `${var}` template), NOT the rendered string.
- If the static prefix exceeds the provider's minimum token threshold, pflow inserts an additional `cache_control` marker at the end of that prefix (Anthropic/Gemini).
- The rendered prompt bytes are identical to what the author wrote — only the content-block structure and `cache_control` metadata differ.
- Opt-out per node via `- batch_cache: false`.
- Combines with declared cache: a batch node can have both a `prompt_cache:` list (reusing workflow-level cache items) AND auto batch-prefix on its prompt — these are distinct cache breakpoints, both marked.

### Strict Order Validation

- A node's `prompt_cache:` list out of declaration order produces a hard error at workflow validation time:

  ```
  ERROR: <node-name> prompt_cache order doesn't match ## Cache declaration
    declared:  [concept, concept_brief, creative-direction.response]
    you wrote: [concept_brief, concept, creative-direction.response]
    fix:       reorder the `prompt_cache:` field to match ## Cache declaration order
  ```

- Error is caught by both `pflow run` validation and `pflow analyze-cache` (via the shared `data_flow.py::validate_data_flow()` call site).
- No auto-reorder. The workflow file is the source of truth.

### Validation Location

- Structural cache-block validation (required fields, types, enum values for `ttl`) lives in the `FLOW_IR_SCHEMA` at `core/ir_schema.py` — automatically runs at every validation entry point.
- Cache reference validation (item names resolve, order matches, subsets valid, `${item.X}` not allowed) lives in `core/workflow/data_flow.py::validate_data_flow()` — already called by both `WorkflowValidator.validate()` (save + pre-execution) and `runtime/compilation/compile_validation.py::_prepare_compilation()` (compile-time). One implementation covers all entry points.
- Diagnostics emitted follow existing pattern (Wave 1C findings): `Diagnostic(severity=ERROR, source="validator", category="validation", path="nodes[id=X].prompt_cache[i]", similar_names=..., available_fields=..., see_also=["caching"])`. Use `find_similar_items` from `core/suggestion_utils.py` for "Did you mean?" hints.
- Schema-level errors and reference-resolution errors both flow through the existing CLI / MCP / JSON diagnostic pipeline (stderr for text, structured for JSON).

### Memo Cache Hash Correctness

- Thread `prompt_cache` rendered content into `compute_node_config()` at `runtime/engine/instrumentation.py:140-179` conditionally:

  ```python
  if prompt_cache_content:  # non-empty list of rendered chunks
      config["prompt_cache"] = prompt_cache_content
  ```

- Follows the `batch_config` precedent at the same function. Nodes that don't opt in keep their existing hash (existing cache entries continue to hit). Nodes that do opt in get a distinct hash and fresh cache entries — no silent stale-result bug.
- `prompt_cache_content` must be the **rendered** content (prose + resolved value), not the declaration (`[name1, name2]`), because two different resolved values under the same name should produce different hashes.
- Update `runtime/engine/CLAUDE.md` to note: "`prompt_cache` content is included conditionally, mirroring `batch_config`. The value is the rendered content chunks."
- Regression test required: existing workflow (no `prompt_cache`) produces identical hash pre- and post-task.

### Breakpoint Limit Handling

- Anthropic: max 4 cache_control markers per request. Pflow's v1 strategy uses 1 per call (the declared-cache end-of-prefix) + up to 1 for batch auto-prefix = 2 max per call. Well within limits.
- OpenAI: markers are effectively no-ops; no limit concern.
- Gemini: LiteLLM handles provider-side limits.
- If future usage demands >2 markers per call (multi-breakpoint for finer-grained sharing), extend the strategy — NOT v1 work.

### `pflow analyze-cache` Command

- New CLI command: `pflow analyze-cache <workflow-path> [inputs...]`. Implementation in new file `src/pflow/cli/commands/analyze_cache.py`.
- Shared analysis module under new package `src/pflow/core/cache_analysis/` exposes two entry points:
  - `analyze(workflow, parameters) -> CacheAnalysis` — full plan with per-node table, shared context candidates, warnings, padding advisories.
  - `summarize(workflow, parameters) -> Diagnostic | None` — one-line `Severity.INFO` nudge for `--dry-run` footer; `None` when cache is already optimal.
- Text output (default) structure:
  - **Summary:** estimated cost delta (first run + rerun), top actionable wins, confidence indicator.
  - **Per-call table:** each LLM node's cache ratio, declared subset, warnings.
  - **Shared context analysis:** detected high-reuse candidates if `## Cache` block is absent or under-utilized; concrete suggested additions as pastable YAML.
  - **Batch pre-warming:** nodes where serializing the first call would save enough to be worth the latency.
  - **Warnings:** severity-tagged, each with stable ID and concrete fix action.
- JSON output (`--format=json`): structured equivalent with `summary`, `warnings`, `shared_context_candidates` arrays. Warning entries have stable `id`, `severity`, `node`, `fix.action`, `fix.description`.
- Confidence indicator: `estimate_confidence: "low_no_trace" | "high_from_trace"` depending on whether a trace is available.
- Size estimates use `MemoizationCache.get_latest_for_node(node_id, workflow_path=...)` (`runtime/cache.py:264-320`) to pull historical output sizes from previous runs. A new helper `MemoizationCache.get_size_for_node(...)` returning `LENGTH(output)` may be added to avoid materializing the full blob; skip this if size is extracted from already-materialized entries.
- `--from-trace [trace-path]` mode: reads an existing trace file (format 2.1.0) and compares predicted cache behavior to actual `cache_creation_input_tokens` / `cache_read_input_tokens` from `event["llm_call"]`. Flags discrepancies with root-cause hints (TTL expiry via `cache_age_sec`, content mismatch via `cache_key` compare, parallel-write race). Falls back gracefully on 2.0.0 traces (omits cache-key-correlated analysis with an info message).
- Exits 0 on successful analysis. Non-zero only on validation errors (unparseable workflow, unresolvable references).

### `--dry-run` Cache Nudge

- `src/pflow/execution/plan.py` (the dry-run planner) calls `cache_analysis.summarize(...)` and attaches its optional `Severity.INFO` `Diagnostic` to the plan's `diagnostics` list.
- `plan_formatter.py` (line 139-142 existing loop) renders the diagnostic automatically. No new formatter code.
- JSON `--format=json` output includes the diagnostic via `Diagnostic.to_dict()` — already serialized by the planner's summary assembly.
- Nudge is silent when no actionable opportunities exist (keeps common-case output unchanged).
- Example nudge text: `Cache: 3 design opportunities available (estimated -$0.78/run). Run 'pflow analyze-cache' for details.`

### MCP Parity

- New MCP tool `analyze_cache(workflow, parameters) -> dict` registered in `src/pflow/mcp_server/tools/execution_tools.py`.
- Service method `ExecutionService.analyze_cache(workflow, parameters)` in `src/pflow/mcp_server/services/execution_service.py` — mirrors the `plan_workflow(...)` pattern (`execution_service.py:301-354`).
- Returns the same JSON shape as `pflow analyze-cache --format=json`.
- Registered in `execution_tools.py:354` tool exports list.
- Structured exception handling consistent with `plan_workflow`: `WorkflowValidationError`, `CompilationError`, `MarkdownParseError`.

### Prefix-Padding Advisory

- For each LLM node whose `prompt_cache:` subset doesn't start at position 1 of the master order, pflow computes whether extending the subset to include earlier items (paying 0.1× read cost on those) would net-save vs. the current state (paying 1× on its own items).
- Surface only when padding is net-positive (with a sensitivity margin — don't suggest $0.001 wins).
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
- New top-level field `trace["workflow_path"]: str | null` — absolute resolved workflow path. Derived from `shared["_pflow_workflow_file"]` at save time.
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
- **Model-specific minimum token thresholds:** the 1024-token minimum is generic but varies by provider/model. Anthropic Sonnet/Opus: 1024; Anthropic Haiku: 2048; Gemini 2.5 Flash: 1024 implicit / ~4k explicit; Gemini 2.5 Pro: 2048 implicit / higher for explicit. Validation should look up the threshold for the node's model via the capabilities table rather than hard-coding 1024.

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

- `tests/shared/llm_mock.py` redesigned around LiteLLM `ModelResponse` shape. Keep backwards-compatible accessors (`.text()`, `.usage()`) where feasible so tests that assert on shared-store outputs (`shared["response"]`, `shared["llm_usage"][...]`) keep working unchanged.
- Add untruncated-prompt mode to the mock: either a second field (e.g., `call_history_full`) or a fixture flag. The 500-char truncation (`llm_mock.py:30`) stays the default to preserve existing test assertions; the untruncated mode is opt-in for cache-structure verification.
- `tests/conftest.py` root fixture (`mock_llm_calls`) updated to patch the pflow-owned adapter (`pflow.core.llm_client.complete` or similar) instead of `llm.get_model`. Preserves the `/llm/` path skip for real-API integration tests.
- ~212 tests across 12 files mechanically updated to the new mock shape. Most should be transparent (they assert on shared-store outputs, not mock internals).
- New tests added:
  - `tests/test_core/test_cache_block_parser.py` — parse valid/invalid `## Cache` blocks.
  - `tests/test_core/test_prompt_cache_validation.py` — reference resolution, order enforcement, subset validity, `${item.X}` rejection.
  - `tests/test_nodes/test_llm/test_prompt_cache_rendering.py` — content-block structure per provider, cache_control markers placed correctly.
  - `tests/test_nodes/test_llm/test_batch_cache_prefix.py` — auto batch-prefix detection + opt-out.
  - `tests/test_cli/test_analyze_cache.py` — CLI output (text + JSON), exit codes.
  - `tests/test_cli/test_analyze_cache_from_trace.py` — trace-based verification.
  - `tests/test_mcp_server/test_analyze_cache_tool.py` — MCP parity.
  - `tests/test_runtime/test_prompt_cache_hash.py` — regression: existing workflows (no prompt_cache) hash identically.
  - `tests/test_runtime/test_trace_format_2_1.py` — new trace fields.

### Out of Scope (v1)

- **ClaudeCodeNode caching** — uses `claude_agent_sdk` directly; SDK handles cache transparently. Separate task if user controls desired.
- **Tier 2 verification** (cross-workflow cache-hit prediction) — planned follow-up; implement after v1 based on observed real-world cross-workflow mismatch patterns.
- **Multi-breakpoint per-call placement** for fine-grained partial-prefix sharing — v1 uses single breakpoint per declared subset.
- **Per-item TTL** — block-level only in v1.
- **Automatic cache-order optimization** — pflow validates order but does not suggest reordering the `## Cache` block itself. Manual only.
- **Per-node inline cache blocks** (non-master) — everything cacheable goes in the master `## Cache`. No inline node-local cache blocks.
- **Gemini explicit cache lifecycle management** beyond what LiteLLM handles transparently.
- **Pre-warming as default** — opt-in via `- prewarm: true` only.
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

**Production source (substantive changes):**

- `src/pflow/nodes/llm/llm.py` (~465 LOC) — rewrite LLM node around pflow-owned adapter. Preserve external behavior. Replace `llm` import with adapter import. Remove `_map_reasoning_options` introspection (lines 35-114); replace with call to the hardcoded map.
- `src/pflow/core/llm_config.py` — replace `llm` CLI subprocess (lines 40-99, 348-387) with env-var detection + optional keys.json read.
- `src/pflow/core/llm_utils.py` — `parse_structured_response` adapts to LiteLLM response shape.
- `src/pflow/core/llm_pricing.py` — verify cache-write (2×) and cache-read (0.1×) multipliers still correct; already implemented at lines 167-171.
- `src/pflow/core/workflow/discovery.py` (line 12, 85) — swap `llm.get_model` call to adapter.
- `src/pflow/registry/discovery.py` (line 13, 88) — same.
- `src/pflow/registry/smart_filter.py` (line 21, 169, 175-180) — same + hardcoded reasoning-options map.
- `src/pflow/runtime/workflow_trace.py` (lines 520-574, 592-599) — redesign tracing around pflow-owned adapter; remove `llm.get_model` monkey-patch.
- `src/pflow/runtime/engine/instrumentation.py` (lines 140-179, 196-197, 423-434, 506-554) — extend `compute_node_config` with conditional `prompt_cache` inclusion; wire `cache_age_sec` and `cache_source` into trace events via `handle_cached_execution`.
- `src/pflow/cli/commands/settings.py` (lines 40-41, 451-467) — update `pflow settings llm` group copy.
- **New files:**
  - `src/pflow/core/llm_client.py` — pflow-owned adapter wrapping `litellm.completion`, attaches tracing, handles cache rendering.
  - `src/pflow/core/llm_reasoning_map.py` — explicit provider-to-option-name mapping.
  - `src/pflow/core/cache_analysis/` package — `analyze()`, `summarize()`, trace-correlation helpers.

**Markdown workflow parser:**

- `src/pflow/core/markdown_parser.py` — extend `_SectionType`, `_KNOWN_SECTIONS`, `_SECTION_DISPLAY_NAMES`, `_SECTION_SYNTAX_HINTS`, `_resolve_section()`. Add `_build_cache_dict(entity)` helper. Integrate into phase 4 at lines 475-530.
- `src/pflow/core/ir_schema.py` — extend `FLOW_IR_SCHEMA` with top-level `cache` section AND per-node `prompt_cache` field. Mind the `additionalProperties: False` at both levels (lines 186, 297).

**Validation:**

- `src/pflow/core/workflow/data_flow.py::validate_data_flow()` — add cache reference validation (item names resolve, order, subset membership). Runs automatically from both `WorkflowValidator` and `compile_validation`.
- `src/pflow/core/workflow/validator.py` — verify the new diagnostics integrate cleanly with existing Step 4 (data flow). If a dedicated Step for cache-specific structural checks is needed, add between current steps 7 and 8.
- `src/pflow/core/exceptions.py` — no new exception types needed; use existing `WorkflowValidationError` (aggregated) and `Diagnostic` (per-error).

**Runtime compilation:**

- `src/pflow/runtime/compilation/compiler.py:358` — extract `prompt_cache` from `node_data` alongside existing `cache`. Thread into `NodeConfig.prompt_cache_items: list[str]` (new field on `runtime/engine/types.py:NodeConfig`).
- `src/pflow/runtime/engine/types.py` — add `prompt_cache_items: list[str] | None = None` to `NodeConfig`.

**Dry-run plan integration:**

- `src/pflow/execution/plan.py` — call `cache_analysis.summarize(...)` and attach nudge Diagnostic to plan's `diagnostics` list. No formatter changes needed (existing loop at `plan_formatter.py:139-142` renders it).

**New CLI command:**

- `src/pflow/cli/commands/analyze_cache.py` — new file. Parses args, invokes shared `cache_analysis.analyze()`, formats text or JSON.
- Register in CLI entry point alongside other commands.

**MCP parity:**

- `src/pflow/mcp_server/services/execution_service.py` — add `analyze_cache(workflow, parameters) -> dict` method. Mirror `plan_workflow` at lines 301-354.
- `src/pflow/mcp_server/tools/execution_tools.py` — add `@mcp.tool() async def analyze_cache(...)`. Mirror `plan_workflow` at lines 157-176. Add to tool exports list at line 354.

**Guide updates:**

- `src/pflow/guide/caching.md` — new top-level guide page.
- `src/pflow/guide/nodes/llm.md` (or equivalent location) — cross-reference caching guide.
- Existing `guide/core.md` mentions of `cache: false` (lines 70, 73, 394) — clarify the distinction from `prompt_cache:`.

**Docs (mintlify):**

- `docs/reference/cli/index.mdx:413-428` — expand cache section to distinguish `cache: false` from `prompt_cache:`.
- New `docs/reference/caching.mdx` or similar — full prompt-caching reference.

**Dependencies:**

- `pyproject.toml` — remove `llm>=0.29`, `llm-anthropic==0.25`, `llm-gemini>=0.30` (lines 28-41). Add `litellm>=X.Y`. Update `DEP002` list (line 184).

**Test infrastructure:**

- `tests/shared/llm_mock.py` — rewrite around adapter shape; keep backwards-compatible accessors; add untruncated-prompt mode.
- `tests/conftest.py:11-35` — update autouse fixture patch target from `llm.get_model` to the adapter.
- ~12 test files with `llm` mock dependencies — mechanically updated patch targets.
- New test files per **Test Infrastructure** section above.

### Implementation Phasing

A single-PR landing is too large. Phases that merge incrementally:

**Phase A.0 (prerequisite spike — do NOT skip):** Before committing to adapter design, run two concrete spikes:

1. **Cache mechanics verification.** Fire `litellm.completion(...)` with `cache_control` markers at Anthropic, Gemini, OpenAI. Verify: (a) `response.usage.cache_creation_input_tokens` / `cache_read_input_tokens` populate as expected, (b) message structure is `system: [{text, cache_control}]` or equivalent, (c) Gemini's single-cached-block architectural limit holds (only last breakpoint honored — confirm silently not silently corrupted), (d) extended thinking (`thinking_budget`, `thinking_effort`) passes through cleanly.

2. **Pricing authority decision.** Compare `litellm.completion_cost(response)` against `core/llm_pricing.py::calculate_llm_cost()` on every model currently in pflow's `MODEL_PRICING` table. Acceptable disagreement threshold: 2% on non-cached calls, 5% on calls with cache tokens. Special attention to Gemini — a Sept 2025 LiteLLM GitHub issue reported cache-token double-counting (~4× inflated costs); closed via PR #15226 on 2025-10-07. Confirm the fix is present in the LiteLLM version being pinned — if pinning an older release, upgrade or add a regression test that would catch the double-count. Based on results, choose:
   - **Outcome A:** LiteLLM accurate + comprehensive → delete `llm_pricing.py`, use `completion_cost()` directly.
   - **Outcome B:** LiteLLM mostly accurate, edge bugs → use LiteLLM as primary, keep thin `llm_pricing.py` as fallback for unknown-model cases.
   - **Outcome C:** Material bugs → import LiteLLM's `model_prices_and_context_window.json` as data, keep pflow's computation code.

   Current spec assumes `llm_pricing.py` stays intact (the conservative default). If the spike shifts the outcome toward A or B, update the "Library Replacement" and "Files to Modify" sections accordingly before Phase A proper.

1. **Phase A: LiteLLM migration, no caching yet.** Replace `llm` with the pflow-owned adapter backed by LiteLLM. Preserve all current behavior. Tests pass. No cache syntax recognized; no cache rendering. Ship standalone; safe-revert. This is the largest phase (~40% of the work).
2. **Phase B: `## Cache` block parsing + per-node `prompt_cache:` field.** Parser recognizes syntax; IR schema updated; validation (membership, order) fires via `data_flow.py`; no rendering yet. Tests for parser + validator correctness.
3. **Phase C: Cache rendering into LLM calls.** Cache block + `prompt_cache:` list produces a rendered system prefix with `cache_control` markers via the adapter. `compute_node_config` updated conditionally. Tracing captures cached-token counts. End-to-end works on a single provider (Anthropic) first, then Gemini, then OpenAI.
4. **Phase D: Auto batch-prefix caching.** Detect and mark stable prefix in batch prompts.
5. **Phase E: Trace format 2.1.0.** Bump version. Add `cache_key`, `cache_source`, `cache_age_sec`, `workflow_path` fields.
6. **Phase F: `pflow analyze-cache` command + MCP parity.** Static analysis (`analyze()`), `--from-trace` mode, JSON output, MCP tool registration, `--dry-run` nudge integration.
7. **Phase G: Deterministic serialization + pre-warming opt-in + guide updates.**

Each phase has its own tests; merges independently. Phase A is prerequisite for all others. Phases B–D can land in parallel after A. Phase E enables richer Phase F. Phase G wraps.

### Non-Obvious Integration Points

- **Memo cache hash conditional inclusion.** The `batch_config` precedent at `runtime/engine/instrumentation.py` is the canonical pattern. Follow it exactly. A regression test asserting pre- and post-task hash equality for no-prompt_cache workflows is mandatory.
- **Tracing is the riskiest rewrite.** Global monkey-patch of `llm.get_model` (`workflow_trace.py:520-574`) is replaced by wrapping the pflow-owned adapter. Validate via drift-catcher test (`tests/test_execution/test_plan_drift.py` — do NOT weaken).
- **Reasoning-options live-introspection removal.** `model.Options.model_fields` introspection at `nodes/llm/llm.py:99` is replaced by a hardcoded map. The comment at lines 52-54 ("Anthropic Opus 4.5 has thinking_effort, thinking, AND thinking_budget, so thinking_effort must be checked first") encodes a precedence — preserve the same ordering in the new map.
- **Pydantic `ValidationError` catch at `nodes/llm/llm.py:298-311`** is flagged as a PATTERN EXCEPTION. Tied to `llm`'s Pydantic-validated options. Remove when no longer applicable under LiteLLM, or redirect to LiteLLM's equivalent deterministic-error detection.
- **Prompt flattening in template resolution.** By the time `LLMNode.prep()` reads `self.params["prompt"]`, it's a fully-resolved flat string. Auto batch-prefix detection must read from the UNRESOLVED template at `config.template_config.template_params["prompt"]`, not the rendered string — the position of `${item.X}` is only identifiable pre-resolution.
- **LLM call integration point.** Cache rendering belongs inside `LLMNode._call_llm` (`nodes/llm/llm.py:271-321`) right before the API call — inside the ThreadPoolExecutor timeout budget, inside the retry loop. Do NOT put rendering in `prep()` or before `pool.submit` (no timeout protection).
- **Sub-workflow compile-once cache.** `WorkflowExecutor._compiled_workflow_cache` (`workflow_executor.py:204-243`) is keyed by resolved workflow path. New fields (e.g., `cache` IR section) shouldn't affect this keying — they're part of the compiled form, which is what's cached. Confirm tests cover the re-compile-with-different-cache-block case.
- **`pflow settings llm` subgroup copy audit.** User-facing strings repeatedly reference Simon's `llm` binary (`cli/commands/settings.py:40-41, 451-467`, `core/llm_config.py:220-237, 433-465`, error messages at `nodes/llm/llm.py:443-452`). Grep for `llm keys`, `llm models`, `llm install` and rewrite.

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

- **Anthropic:** cache write 1.25× (5-min TTL) or 2× (1-hour TTL); cache read 0.1×. Max 4 cache_control markers per request. Min 1024 tokens for sonnet/opus, 2048 for haiku.
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

- Task 95 — Unified LLM Usage via Simon Willison's `llm` Library (this task replaces that infrastructure).
- Task 66 — Structured Output for LLM Node (carries forward to LiteLLM's `response_format`).
- Task 96 — Batch Processing (`batch_config` in hash is the conditional-inclusion precedent).
- Task 104 — Python Code Node (adjacent; unrelated to caching).
- Task 106 — Workflow Iteration Cache (memoization cache introduced here).
- Task 108 — Smart Trace Debug Output (trace format 2.0.0 introduced here; this task bumps to 2.1.0).
- Task 121 — Workflow Testability (complementary verification infrastructure).
- Task 127 — MCP Server Connection Pooling (adjacent; unrelated).
- Task 131 — Batch Error Handling (adds error-handling fields to batch config hash — precedent for subdict additions).
- Task 133 — Unified Per-Node Storage for Trace and Cache (may interact with how cache metadata is persisted).
- Task 136 — Recursive Sub-Workflow Validation at Parse Time (validator recursion pattern).
- Task 143/144 — Unified Diagnostic System (Diagnostic class, severity, context).
- Task 147 — Validator Produces Diagnostics Natively.
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
- **Shift pricing authority to LiteLLM** — if Phase A.0 investigation concludes LiteLLM's `completion_cost()` is trustworthy across providers, replace `core/llm_pricing.py`'s manually-maintained `MODEL_PRICING` table with LiteLLM's data. Eliminates the "new model released → pflow shows $0 cost" maintenance burden. Investigation deferred to Phase A.0; implementation decision flows from that outcome.
