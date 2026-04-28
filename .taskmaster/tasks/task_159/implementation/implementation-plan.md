# Task 159 — Phase B–G Implementation Plan

## Context

Task 159 ships prompt caching for pflow workflows: a declarative `## Cache` block, per-node `prompt_cache:` and `prewarm:` fields, auto batch-prefix caching, `pflow analyze-cache` (CLI + MCP), trace format 2.1.0, and a `--dry-run` cache nudge. The motivating workload is `lyrics-generator` (~252 LLM calls per run); the conservative target is ≥40% input-cost reduction first run, ≥70% on within-TTL reruns.

## Architectural backbone — `CacheRenderContext`

**Decision (post-review):** all engine→LLMNode communication for caching flows through a single typed context object delivered via one reserved shared-store key. This collapses what an earlier draft scattered across 6 reserved keys (3 in `shared`, 3 in `node.params`) into one. The pattern mirrors `shared["__trace_collector__"]` exactly: engine sets, leaf node reads in `prep()`, save/restore at `engine.run()` boundary handles sub-workflow nesting.

```python
# src/pflow/runtime/engine/types.py — NEW dataclass alongside CompiledWorkflow
@dataclass(frozen=True)
class CacheRenderContext:
    """Per-node cache rendering context, built once at engine.run() entry."""
    cache_block: dict[str, Any] | None        # workflow-level ## Cache IR
    subset: tuple[str, ...]                   # per-node prompt_cache items, declaration order; () = no opt-in
    prewarm: bool                             # per-node prewarm flag
    unresolved_batch_prompt: str | None       # per-node, batch-only — raw template with ${item.X} intact
    batch_alias: str | None                   # per-node, batch-only — typically "item"
```

**Delivery channel:** `shared["__pflow_cache_render__"]: dict[node_id, CacheRenderContext]`. Engine builds this at `run()` entry from `CompiledWorkflow` + `NodeConfig` per node. Frozen dataclass + immutable tuple = read-only-shared = parallel-batch-safe by construction.

**Save/restore:** mirror `engine.py:181–187` exactly — capture prior value via `.get()`, install always (even when the dict is empty), restore via write-back assignment (NOT `.pop()` — `NamespacedSharedStore` lacks `pop`). Sub-workflow children's engine.run() installs their own dict; parent's value is restored on exit.

**What this replaces from the earlier draft:**
- `shared["__pflow_cache_block__"]` → folded into `CacheRenderContext.cache_block`.
- `node.params["__prompt_cache_items__"]` → folded into `CacheRenderContext.subset`.
- `node.params["__prompt_cache_unresolved_template__"]` → folded into `CacheRenderContext.unresolved_batch_prompt`.
- `node.params["__prewarm__"]` → folded into `CacheRenderContext.prewarm`.
- `shared["__pflow_batch_alias__"]` → folded into `CacheRenderContext.batch_alias`.
- `shared["__pflow_last_cache_meta__"][node_id]` → REMOVED entirely. Cache trace metadata (`cache_key`, `cache_source`, `cache_age_sec`) flows via the existing `llm_usage` channel that `LLMNode.post()` writes to `shared[node_id]` — same path `cache_creation_input_tokens` already takes.

**Why this is the right shape:**
- One read site (`prep()` reads `shared["__pflow_cache_render__"][self.node_id]`), one save/restore (engine.run boundary), one place to extend.
- No `node.params` mutation by the engine — `node.params` stays semantically "user-authored config," consistent with existing precedent.
- Per-node_id keying inside an immutable dict → parallel batch reads the same context per item with zero contention; no shallow-copy concurrency surface to reason about.
- `cache_key` in `llm_usage` per-item preserves batch granularity for `analyze-cache --from-trace` (the parallel-batch trace pipeline already handles this).
- `compute_node_config` doesn't need new dunder-key filtering — no engine-injected dunder keys exist in `node.params` to filter.

**Top-10% precedent:** Temporal SDK `Context`, Prefect `RunContext`, gRPC request context. One typed object, one channel. pflow's existing `__trace_collector__` is the same pattern.

The remainder of this plan reflects this consolidation. Phases B3, C1.2, D, and E describe rendering and consumption against `CacheRenderContext`, not against scattered keys.

Task 158 (LiteLLM migration, typed exceptions, diagnostic pipeline, trace seam, `MockLLMClient.call_history_full`, `MemoizationCache.get_with_age`) shipped. This plan covers Phases B–G and is the HOW: file-level patch ordering and implementation specifics. Read in conjunction with:

1. Spec (contract): `.taskmaster/tasks/task_159/task-159.md` — DDs, requirements, output formats, warning catalog.
2. Progress log (journey): `.taskmaster/tasks/task_159/implementation/progress-log.md` — especially §30 (per-model thresholds, OpenAI retention, the misdiagnosis correction).
3. Handoff (operational): `.taskmaster/tasks/task_159/starting-context/agent-handoff.md` — phase-split, paid spikes, hedged claims, working-style notes.

This plan does NOT duplicate values from those documents — it cross-references them. Threshold numbers live in DD#32; phase split rationale in handoff; warning IDs in spec §"Stable Warning ID Catalog".

## Operating principles

- **Gating tests come first.** For each sub-phase the regression set is named; the highest-leverage gate is the no-`prompt_cache` memo-hash equality test (DD#19) — that catches the silent stale-cache bug. STOP if it fails.
- **`test_plan_drift.py` stays green throughout.** Phases B3, C, D, and E touch surfaces it watches.
- **No contract changes here.** If a load-bearing assumption breaks, surface to the user — do not encode a divergence into a patch.
- **Hedged claims become plan-internal verifications.** Each phase that owns a hedged claim has an explicit "verify" step before the patch lands.
- **Three paid spikes (C0, D, E) are Phase-internal, not pre-plan.** They are designed below; their fallback paths are also designed below.

## Cross-cutting reads before any phase

These files were verified during plan-writing. The implementing agent should re-read with the specific patch in hand:

- `src/pflow/core/diagnostic.py` — `Diagnostic` dataclass; `__eq__`/`__hash__` identity tuple at lines 69–92; `CATEGORY_TITLES` at line 192–207.
- `src/pflow/core/llm_providers.py` — frozen-dataclass-tuple template for `llm_capabilities.py`.
- `src/pflow/core/markdown_parser.py` — `_SectionType` enum (line 122), `_KNOWN_SECTIONS`, `_resolve_section` (line 571), entity-only YAML/code-block rule at line 361, orphan-content path at line 273–274, 402–404.
- `src/pflow/core/ir_schema.py` — `FLOW_IR_SCHEMA` at line 143; node `additionalProperties: False` at line 186; top-level `additionalProperties: False` at line 297.
- `src/pflow/core/workflow/data_flow.py` — `validate_data_flow(workflow_ir, check_inputs)` at line 277.
- `src/pflow/core/workflow/validator.py` — 10-step pipeline (cache step is added there per DD#20).
- `src/pflow/core/llm_client.py` — `complete()` at line 169; `_build_messages()` at line 579; `_translate_reasoning_for_litellm` at line 632.
- `src/pflow/runtime/engine/instrumentation.py` — `compute_node_config` (line 139), `handle_cached_execution` (line 480), `write_memo_cache` (line 297).
- `src/pflow/runtime/engine/plan_node.py` — entire file; this is the SSoT for cache-key computation per `engine/CLAUDE.md`.
- `src/pflow/runtime/engine/types.py` — `NodeConfig` (line 36), `TemplateConfig` (line 12).
- `src/pflow/runtime/engine/engine.py` — `_execute_node` (line 317), `_execute_single_node` (line 545), batch dispatch (line 386).
- `src/pflow/nodes/llm/llm.py` — `prep()` at line 231 (where cache content gets assembled), `_call_llm` at line 332 (inside ThreadPoolExecutor + retry boundary), `post()` at line 431.
- `src/pflow/runtime/workflow_trace.py` — `TRACE_FORMAT_VERSION` constant at line 17; `_add_llm_data` at line 202; `save_to_file` at line 463.
- `src/pflow/runtime/cache.py` — `get_with_age` at line 224; `get_latest_for_node` at line 264.
- `src/pflow/execution/runner.py` — `_synthesize_inline_workflow_id` at line 36; `_pflow_workflow_file` injection at line 175.
- `src/pflow/execution/executor_service.py` — `_FAILURE_CATEGORY_MAP` at line 29.
- `src/pflow/core/workflow/sub_workflow_resolver.py` — `resolve_sub_workflow` (the Tier 2 walker primitive).
- `src/pflow/core/workflow/mermaid/_render.py` — `_render_workflow` recursion pattern (lines 94–130) — Tier 2 walker traversal model.
- `src/pflow/execution/plan.py` and `src/pflow/execution/formatters/plan_formatter.py` — dry-run plan flow (`build_plan` → `format_plan_text`/`format_plan_json`); diagnostics list at the bottom of `format_plan_text` (lines 139–142) is where the cache nudge surfaces.
- `src/pflow/mcp_server/services/execution_service.py::plan_workflow` (line 301) and `src/pflow/mcp_server/tools/execution_tools.py::plan_workflow` (line 158) — the precedent the new `analyze_cache` MCP tool mirrors verbatim.
- `tests/shared/llm_mock.py` — `MockLLMClient.complete()` signature at line 189; widen here in C1.
- `tests/test_core/test_mermaid_golden.py` — golden-test pattern for `test_analyze_cache_golden.py`.

---

# Phase B1 — Foundations (parallel-safe)

## Goal

Land the two Phase B prerequisites that nothing else can build on top of: the `Diagnostic.id` field (per DD#27) and the per-model capabilities table (per DD#32). They are independent of each other and of every other Phase B/C/D/E sub-phase except B2 (which uses the new categories and the capabilities lookup).

## B1.1 — `Diagnostic.id` field

### Files

- `src/pflow/core/diagnostic.py`:
  - Add `id: str | None = None` to the `Diagnostic` dataclass (after `see_also`).
  - Update `__eq__` to use `(severity, source, node_id, id or message)`. Same identity tuple update in `__hash__`. Comments at lines 69–80 and 89–92 must be updated to reference `id or message` as the dedup key when present.
  - Update `to_dict()` to emit `"id"` when set; omit when None (mirror existing `title is not None` pattern).
  - **Add three new category constants and `CATEGORY_TITLES` entries** (DD#27 + Files-to-Modify in spec):
    - `CACHE_FAILURE_CATEGORY = "cache_failure"` (typed-exception path; v1 emits via Diagnostic directly, no typed exception).
    - `CACHE_WARNING_CATEGORY = "cache_warning"` — analyzer-emitted; no `_FAILURE_CATEGORY_MAP` entry needed (handoff "5-place co-edit pattern" — only #2 and #3 apply for analytical categories).
    - `CACHE_ADVISORY_CATEGORY = "cache_advisory"` — same.
    - Add corresponding `CATEGORY_TITLES` entries: `"Cache Failure"`, `"Cache Warning"`, `"Cache Advisory"`.

- `src/pflow/execution/executor_service.py`:
  - Add `"cache_failure": "cache_failure"` to `_FAILURE_CATEGORY_MAP` (line 29). The dual-invariant (string constant in `core/diagnostic.py` matches dict-VALUE here) per the comment at line 33–37 must hold.

- `src/pflow/core/diagnostic_render.py`:
  - Extend `_format_warning_or_info_diagnostic` with a category dispatch for `cache_warning` / `cache_advisory` / `cache_failure` that surfaces structured `context` data inline alongside `message`/`suggestions` — mirrors the existing `template_error` precedent (per spec "Diagnostic Extension" subsection). For v1, render: `id` (if present, prefix `[id]`), `message`, `suggestions[]`, then any `context.savings_pct` / `context.savings_usd` / `context.batch_size` / `context.prefix_tokens_estimated` / `context.target_file` lines if present (these are the keys the cache catalog actually emits — see warning-catalog tests in F1).

### Tests

- `tests/test_core/test_diagnostic_id_field.py` (new — Test Infrastructure list):
  - `id=None` (default) preserves legacy identity tuple (dedup matches old behavior).
  - `id="cache.x"` uses `id` in dedup; two diagnostics with same `id` but different `message` collapse.
  - `to_dict()` round-trip with and without `id`.
  - `cache_failure`, `cache_warning`, `cache_advisory` constants exist and appear in `CATEGORY_TITLES`.
  - `_FAILURE_CATEGORY_MAP["cache_failure"] == "cache_failure"`.

### Hedged-claim verification (DD#27 backwards compat)

Before merging B1.1: run `make test`. Pay attention to:
- `tests/test_core/test_diagnostic.py` (existing equality / hash tests).
- Any test under `tests/test_core/`, `tests/test_runtime/`, `tests/test_execution/` that asserts on dedup behavior. The change is null-safe by construction (`id or message` falls back to today's `message`-keyed dedup), but **verify, do not assume**.

If any existing test breaks: STOP. The change is structural and cannot be silently weakened. Surface to the user with the failing test name and a minimal repro.

### Regression invariants

- `tests/test_execution/test_plan_drift.py` (32 tests) stays green — `Diagnostic` is consumed throughout the plan/runtime path.
- All existing CLI/MCP error-output tests stay green.

## B1.2 — `core/llm_capabilities.py`

### Files

- `src/pflow/core/llm_capabilities.py` (NEW, mirrors `llm_providers.py` shape):
  - `from __future__ import annotations` + `from dataclasses import dataclass`.
  - Frozen dataclass `ModelCapability` with fields: `name: str`, `min_cache_tokens: int`, optional `notes: str = ""`.
  - Module-level `MODEL_CAPABILITIES: tuple[ModelCapability, ...]` populated with per-model thresholds per DD#32 (do NOT duplicate the numbers here — read them from spec DD#32 when populating).
  - `get_min_cache_tokens(model: str) -> int` — uses `detect_provider` + a per-model lookup. For unknown Anthropic models or unrecognized providers, return the **conservative fallback floor** stated in DD#32 (the numeric value lives in spec; encode by reference). Lookup matching is by exact model id when prefixed, else by family prefix.
  - No imports from `llm_client`, `runtime/`, or `nodes/` — same dependency-free constraint as `llm_providers.py`.

### Tests

- `tests/test_core/test_llm_capabilities.py` (new):
  - Each model family in DD#32 returns the documented threshold.
  - Bare model names route to the right family via `detect_provider` (e.g., `claude-sonnet-4-5` → 1024).
  - Unknown model returns conservative fallback. Empty string / None handled.
  - The lookup is pure / deterministic / no side effects.

### Regression invariants

`make check` (mypy/ruff) — frozen-dataclass-tuple shape must pass linting like `llm_providers.py` does.

## B1 merge gate

Both B1.1 and B1.2 land independently. Each adds a regression test that ensures the new surface is non-breaking. If either fails its own gating tests, that sub-phase reverts and the other proceeds.

---

# Phase B2 — Markdown parser + IR schema + cache validation

## Goal

Land the `## Cache` block parsing, the IR-schema field additions, and the cache-reference validation logic. These three are interdependent (parser produces IR, schema gates IR, validation reads IR) and ship as one unit per the handoff phase split.

## Pre-implementation verification

Before any patch lands, the implementing agent must read `markdown_parser.py:240–408` (the line-by-line state machine in `parse_markdown`) and confirm three things:
1. `## Cache`'s shape (section-level params + section-level code block, NO `### entities`) is genuinely a new structural rule. Today, when `current_entity is None` and `current_section in _KNOWN_SECTIONS`, both YAML items (line 375) and code blocks (line 273–274 — orphan path) are rejected (orphan-content error if zero entities, warning if entities present). The Cache section must bypass this rule for itself only.
2. The H2 boundary at line 310 already resets `current_entity = None`. The new state must be tracked outside `current_entity` (via a fresh `_CacheSection` collector dataclass).
3. The Phase 4 IR-build loop (line 475–530) is where `ir["cache"]` gets assembled from the collector.

If any of those facts has shifted (e.g. a refactor between plan-write and implementation-time), surface to the user before patching.

## B2.1 — Parser extension

### Files

- `src/pflow/core/markdown_parser.py`:
  - Add `_SectionType.CACHE = auto()` to the enum (line 122).
  - Decision: **do NOT add CACHE to `_KNOWN_SECTIONS`.** The orphan-content rule at line 273–274 / 402–404 must NOT fire for the Cache section's section-level YAML and code block. The CACHE section is its own structural mode.
  - Add `_SECTION_DISPLAY_NAMES[_SectionType.CACHE] = "Cache"` for any error rendering that needs it.
  - Add `_SECTION_SYNTAX_HINTS[_SectionType.CACHE]` with a paste-ready template per the spec's "Syntax Specification" (Implementation Notes) — copy the canonical example shape (`- ttl: 5m`, then a single ` ```cache ` block with prose+`${var}` chunks).
  - Update `_resolve_section` (line 571–593) to recognize `"cache"` (lowercase) and return `(_SectionType.CACHE, False, None)`.
  - **State-machine extension** (the structurally novel part):
    - Add a new collector type `_CacheSection` (similar to `_Entity`) holding `ttl: str | None`, `chunks: list[_CacheChunk]`, `_source_line: int`, plus a helper method to add a chunk parsed from the cache code block content.
    - Add a `_CacheChunk` dataclass with fields `name: str`, `var_expr: str`, `prose_before: str`, `_source_line: int`. The chunk identifier is the stripped template path (`${concept-brief.response}` → `concept-brief.response`).
    - Add a parser-local state variable (alongside `current_entity`) named e.g. `cache_section: _CacheSection | None`.
    - When the H2 transition at line 310 hits a `## Cache` (i.e. `current_section == _SectionType.CACHE`), reset `current_entity = None` AND initialize `cache_section = _CacheSection(...)`. When transitioning OUT of `## Cache` to another section, finalize/persist `cache_section` (via the same `_flush_yaml_item()` pattern — call a new `_flush_cache_section()` helper that runs at H2 transition, EOF, and any boundary).
    - In the per-line dispatch loop, ADD a branch above the entity branch (before line 361) that runs ONLY when `current_section == _SectionType.CACHE` and `current_entity is None`:
      - Code-fence open at section level: if the tag is exactly `cache` (a single tagged code block), enter `in_code_block` mode with `code_fence_pattern` set as today; ELSE error with line number ("Code blocks under `## Cache` must use the `cache` tag — got `<tag>`"). Multiple code blocks under `## Cache` is a syntax error per spec.
      - YAML item at section level (`- key: value`): only `- ttl:` is accepted in v1. Use the existing `_YAML_ITEM_RE` regex; on match, validate the key is `ttl` and the value is `5m` or `1h` (DD#7 + spec section "## Cache Block Parsing"). Other keys → error with hint listing valid keys. Multiple `- ttl:` items → error.
      - Prose lines: ignored at the section level (workflow-level prose under `## Cache` is just commentary, not part of the rendered cache content).
    - Code-fence close at section level: parse via new helper `_parse_cache_code_block(content: str, base_line: int) -> list[_CacheChunk]`. **Algorithm (explicit):**
      ```python
      def _parse_cache_code_block(content, base_line):
          chunks = []
          seen_names = set()
          last_end = 0
          for match in TEMPLATE_EXTRACT_PATTERN.finditer(content):
              prose = content[last_end:match.start()]   # may be empty for ${a}${b}
              var_expr = match.group(1)                  # text inside ${...}
              name = var_expr                            # chunk identifier = stripped template path
              if name in seen_names:
                  raise MarkdownParseError(f"Duplicate chunk identifier '{name}'", line=...)
              seen_names.add(name)
              chunks.append(_CacheChunk(
                  name=name, var_expr=var_expr, prose_before=prose,
                  _source_line=base_line + line_offset(match.start(), content),
              ))
              last_end = match.end()
          # Trailing prose after last ${var} is silently discarded — chunks are
          # "prose-before-${var}" pairs by contract; trailing prose has no var to attach.
          if not chunks:  # empty block OR prose-only — both are errors
              raise MarkdownParseError("Cache block must contain at least one ${var} reference", line=base_line)
          return chunks
      ```
    - **Edge cases handled by this algorithm:**
      - Empty block / prose-only → ERROR.
      - Back-to-back `${a}${b}` → first chunk has prose-before-`a`, second chunk has empty `prose_before`. NOT an error.
      - `${a} foo ${b}` → first chunk's prose ends at `${a}`, second chunk's `prose_before = " foo "`. Each chunk has exactly one `${var}` by construction (algorithm splits at every match).
      - Trailing prose after last `${var}` → silently discarded. Document this in the user-facing syntax spec.
      - Duplicate chunk identifier → ERROR with line number.
    - **Chunk identifier**: equal to the content inside `${...}` verbatim. Examples: `concept`, `chorus-chooser.winning_chorus`, `data[0].field`. **Downstream root-extraction in B2.3 uses `TemplateResolver.extract_root_node_id` (which respects bracket syntax)** — NOT the looser `_PFLOW_VAR_RE` from `data_flow.py:18`, whose bash-syntax skip would let batch-scoped bracket references slip through validation (review-validation-consistency W3).
  - **Phase 4 IR build** (line 475–530): add `ir["cache"] = _build_cache_dict(cache_section)` before the validation/return at line 530, ONLY when `cache_section is not None`. The shape must match the IR schema in B2.2.

### Tests

- `tests/test_core/test_cache_block_parser.py` (new):
  - Parses a valid `## Cache` block with mixed prose + N chunks; chunk count, identifiers, prose-before strings all match.
  - `- ttl: 5m` and `- ttl: 1h` accepted; other values rejected.
  - `- ttl: 5m` declared twice is an error.
  - Two ` ```cache ` blocks in one section is an error.
  - Empty cache block (no `${var}`) is an error.
  - Prose-only block is an error.
  - Duplicate `${concept}` reference is an error.
  - Chunk identifier extraction: `${concept}` → `concept`; `${chorus-chooser.winning_chorus}` → `chorus-chooser.winning_chorus`.
  - `_source_line` populated on the section and on each chunk (used by the validator's `path` field).
  - Round-trip: a valid block → IR → save to disk via the existing save path → reload → IR matches byte-for-byte (covers the `pflow save` round-trip hedged claim — see B2 verification below).

### Hedged-claim verification

The handoff lists "`pflow save` round-trip preserves `## Cache` sections" as still-open. `WorkflowManager.save()` writes raw markdown atomically per `core/workflow/CLAUDE.md`; the markdown body is preserved verbatim. The round-trip test above is the verification step. If it fails, the parser may be normalizing whitespace inside the cache code block or stripping prose; investigate before claiming the round-trip works.

## B2.2 — IR schema (with validation-reach gap closure)

### Files

- `src/pflow/core/ir_schema.py`:
  - Top-level `FLOW_IR_SCHEMA["properties"]["cache"]`: object with `ttl` (enum `["5m", "1h"]`, optional), `items` (array of objects, each with `name: string`, `var: string`, `prose_before: string`, optional `_source_line: integer`). `additionalProperties: False`.
  - Per-node properties (line 156–183): add `prompt_cache: {"type": "array", "items": {"type": "string"}}` and `prewarm: {"type": "boolean"}`. Per-node `additionalProperties: False` at line 186 means both must be added explicitly.
  - The existing `cache: bool` field at line 180–183 remains unchanged.
  - Update `_get_suggestion` only if a new error path is introduced (e.g., misspelled `prompt_cache` → suggest correct field). Otherwise leave alone.

- **Validation-reach gap closure** (review-validation-consistency Critical 1):
  - **The plan's earlier draft assumed `FLOW_IR_SCHEMA` runs at every entry point. It does not.** `WorkflowValidator._validate_structure` (step 1) calls `validate_ir` (full schema). `runtime/compilation/compile_validation.py::_prepare_compilation` calls `validate_ir_structure` from `runtime/compilation/ir_preparation.py:231` (minimal — only checks nodes/edges arrays). A workflow loaded directly via the compiler bypassing the Runner has structural cache shape unchecked.
  - **Fix**: B2.3's `_validate_cache_block` does the structural shape checks (cache block presence, `ttl` enum, `prompt_cache` is a list-of-strings, `prewarm` is a bool) in addition to the reference checks. Both `WorkflowValidator` AND `_prepare_compilation` reach `validate_data_flow`, so the structural checks fire at both entry points. The schema rules in `FLOW_IR_SCHEMA` are belt-AND-suspenders — they fire on the validator path; `_validate_cache_block` is the load-bearing path for both.
  - This means structural cache validation has TWO sources: the JSON schema (validator path only) AND `_validate_cache_block` (both paths). The schema catches the bad shapes earlier (with better diagnostic context: path, enum value, similar_names); `_validate_cache_block` is the safety net for the compile path.
  - Document this in `validate_ir_structure` (with a one-line comment) so a future contributor doesn't mistakenly think `validate_ir` runs there.

### Tests

- Extend `tests/test_core/test_ir_schema.py` (or add adjacent file):
  - Valid IR with `cache` block + per-node `prompt_cache: [a, b]` + `prewarm: true` passes.
  - `prompt_cache` of wrong shape (non-list, list of non-strings) is rejected at the schema level.
  - Per-node `prompt_cahe` (typo) is rejected with `additionalProperties: False`.
  - Top-level `cahe` (typo) is rejected.
  - `cache: false` (existing memo opt-out) and `prompt_cache: [...]` (new) coexist on one node.

## B2.3 — Cache reference validation in `data_flow.py`

### Files

- `src/pflow/core/workflow/data_flow.py`:
  - Add a new function `_validate_cache_block(workflow_ir, diagnostics)` called from inside `validate_data_flow` after the existing per-node template-reference validation loop. Cases (each emits a `Diagnostic` with `source="validator"`, `id="cache.<id>"` per spec catalog):
    - Each `${var}` in `## Cache` chunks resolves to a workflow input or upstream step output (use the same valid_simple_refs / nodes_by_id sets the existing template validator builds — reuse the existing `_validate_template_reference` path). Resolution failure → ERROR (no separate `cache.*` ID; flows through existing template-validation diagnostic machinery).
    - Batch-scoped reference rejection: if a chunk's `${var}` root resolves to a batch alias (any value in `batch_item_aliases`, computed at line 311–318), emit ERROR with a clear message per spec: "References that vary across calls referencing the same chunk are rejected. `${item.X}` and any descendants are batch-scoped and not valid in `## Cache`." (No catalog ID — flows as a generic validation error.)
    - Per-node `prompt_cache: [...]` references that don't appear in `## Cache.items` → ERROR with `find_similar_items`-driven "Did you mean?" suggestions.
    - Per-node `prompt_cache: [a, c, b]` doesn't match `## Cache` declaration order → ERROR with `id="cache.order-mismatch"`. Message must match the format in spec's "Strict Order Validation" section verbatim (declared / you wrote / fix).
    - Unused `## Cache` chunk (declared but no node references it) → WARNING with `id="cache.unused-chunk"`.
  - The function operates purely on the IR — no template resolution, no token counting, no I/O. Stays fast and deterministic per DD#36.

- `src/pflow/core/workflow/validator.py`:
  - The 10-step pipeline already calls `validate_data_flow` (per workflow/CLAUDE.md). No new step is needed — the cache validation is part of step 4 by virtue of living inside `validate_data_flow`. Update the validator's CLAUDE.md to note "step 4 also validates `## Cache` blocks and per-node `prompt_cache`/`prewarm` references via shared `data_flow._validate_cache_block`."
  - Confirm the compile-time path (`runtime/compilation/compile_validation.py::_prepare_compilation`) also reaches `validate_data_flow` — per DD#20 it does. No code change needed there if so; if not, the implementing agent surfaces this.

- **MCP entry point reach** (review-feature-interactions C5 — Task 72 historical pattern):
  - Verify `mcp_server/services/execution_service.py::execute_workflow` (line 195) and `run_registry_node` (line 500) reach the same `validate_data_flow` path before execution. Both go through `WorkflowRunner().run()` (verified by reading execution_service.py — both delegate to `WorkflowRunner`), so they reach `WorkflowValidator.validate()` at `runner.py:336/457`. **Verification step**: add a test in `tests/test_mcp_server/` that invokes `execute_workflow` on a workflow with `cache.order-mismatch` and asserts the same diagnostic structure as the CLI invocation. Catches the regression where MCP path bypasses validation.

### Tests

- `tests/test_core/test_prompt_cache_validation.py` (new):
  - `prompt_cache: [c, b]` when `## Cache` declares `[a, b, c]` → `cache.order-mismatch` ERROR with the exact message format.
  - `prompt_cache: [unknown]` → resolution ERROR with `similar_names` populated.
  - `${item.X}` in cache chunk → batch-scoped rejection ERROR.
  - Unused chunk → `cache.unused-chunk` WARNING.
  - `prompt_cache: []` (empty) and `prompt_cache:` (absent) both treated as "no declared cache" — no ERROR.
  - Sub-workflow with `## Cache` validates independently (each file's cache block is scoped to its own inputs and step outputs per DD#12 — covered by the recursive validator path in `_validate_sub_workflows`).

### Hedged-claim verification

`WorkflowExecutor._compiled_workflow_cache` interaction with sub-workflow `## Cache`: per `runtime/CLAUDE.md` the compile cache is keyed by resolved workflow path and stores the compiled IR (which includes the `cache` field). Two sequential invocations of the same sub-workflow file therefore reuse the same compiled `cache` block — correct. **Verification test**: in `tests/test_runtime/`, add a test where a parent invokes the same sub-workflow twice (or runs a heterogeneous batch where two items share a child path), each time with different parent state. Assert the per-invocation cache content (renderable from each invocation's child shared store) differs while the compiled IR is reused. If the test reveals corruption, surface to the user — the fix may require evicting compile-cache entries on a different keying strategy.

## B2 merge gate

- `tests/test_core/test_cache_block_parser.py`, `tests/test_core/test_prompt_cache_validation.py` pass.
- All existing parser + IR-schema + validator tests pass (`make test` scope).
- `test_plan_drift.py` stays green (validator changes shouldn't affect plan output, but verify).

---

# Phase B3 — Memo hash conditional inclusion via `CacheRenderContext`

## Goal

Wire `prompt_cache` rendered content into the memo cache hash conditionally per DD#19 — opt-in nodes get a fresh hash; opt-out nodes are byte-for-byte identical to today. Highest-risk patch in the entire task; the regression test below is the single most important gate.

## Pre-implementation verification

1. Read `runtime/engine/instrumentation.py:139–170` and `plan_node.py` end-to-end. Confirm the `batch_config` precedent at `compute_node_config:162` (dict key `"batch"`, conditional truthy-include).
2. **Confirm plan_node ordering.** As of plan-write, `plan_node:37–56` runs `compute_config_hash` FIRST (lines 37–44), THEN `resolve_templates` (lines 50–56) — opposite of what cache hashing needs. B3.1 must REORDER `plan_node` so `resolve_templates` runs before `compute_config_hash` (or split the hash into two steps). Verify this ordering before patching; if a refactor between plan-write and implementation has changed it, surface to the user.
3. **Confirm batch-node template resolution gap.** `plan_node:50` only calls `resolve_templates` when `not config.batch_config`. Batch nodes therefore have `resolved_params=None` at hash time. B3.1 must add a separate "render cache content for batch nodes" path because cache chunks reference non-batch values (validated by B2.3) and so can be resolved against `shared` directly, independent of the per-item batch resolution that happens in `_execute_single_node`.
4. **Build the regression baseline FIRST.** Before any B3 patch, run a fixture-generation script that calls `compute_config_hash` for representative workflows and commits the results. The regression gate compares against this baseline — without it, the gate is a tautology.

## Pre-merge step: generate regression-baseline fixture

Add `scripts/generate_config_hash_baseline.py` (NEW — minimal, can be deleted after baseline lands). It loads ≥10 workflows (3–4 from `examples/` representing branching/batch/sub-workflow shapes; all 7 files using `cache: false`; 2–3 fixtures from `tests/test_runtime/`), compiles each, and writes `compute_config_hash` for every node to `tests/test_runtime/fixtures/golden_config_hashes.json`. Run on `main` BEFORE B3 patches. Commit the JSON. The B3 regression test loads it and asserts byte-equality post-task.

## B3.1 — Schema additions to runtime types

### Files

- `src/pflow/runtime/engine/types.py`:
  - Add `CacheRenderContext` dataclass per the "Architectural backbone" section above.
  - Extend `NodeConfig`:
    - `prompt_cache_items: tuple[str, ...] = ()` — the bare names declared on the node. **Tuple, not list**, so the value is hashable and the dataclass stays clean. Empty tuple = no opt-in (DD#19 + spec edge case).
    - `prewarm: bool = False`.
  - Extend `CompiledWorkflow`:
    - `cache_block: dict[str, Any] | None = None` — the workflow-level `## Cache` IR.

- `src/pflow/runtime/compilation/...` (compiler):
  - Find the `NodeConfig` factory (search for `cache_enabled` field assignment — likely `compilation/compiler.py`). Extract `node.get("prompt_cache", [])` → `tuple(...)` into `NodeConfig.prompt_cache_items`. Extract `node.get("prewarm", False)` into `NodeConfig.prewarm`.
  - Find `CompiledWorkflow` assembly site. Extract `workflow_ir.get("cache")` into `CompiledWorkflow.cache_block`.
  - **Verification**: existing `cache: bool` extraction still produces the same `NodeConfig.cache_enabled`. Run all `tests/test_runtime/test_compiler*` tests.

## B3.2 — `CacheRenderContext` build + install at engine boundary

### Files

- `src/pflow/runtime/engine/engine.py`:
  - Add a module-level helper `_build_cache_render_dict(workflow: CompiledWorkflow) -> dict[str, CacheRenderContext]`:
    - Iterate `workflow.node_configs`. For each LLMNode (`config.node_type_name == "LLMNode"`), build a `CacheRenderContext` if any of `(config.prompt_cache_items, config.prewarm, workflow.cache_block)` is set (i.e. at least one cache-related declaration exists for this node or workflow).
    - `cache_block` = `workflow.cache_block`.
    - `subset` = `config.prompt_cache_items`.
    - `prewarm` = `config.prewarm`.
    - `unresolved_batch_prompt` = `config.template_config.template_params.get("prompt")` only when `config.batch_config and config.template_config`; else `None`.
    - `batch_alias` = `config.batch_config.item_alias` when batch; else `None`.
  - In `WorkflowEngine.run()` body (the section currently doing trace-collector save/restore at lines 181–187): add the same shape for `__pflow_cache_render__`:
    ```python
    saved_cache_render = shared.get("__pflow_cache_render__")
    shared["__pflow_cache_render__"] = _build_cache_render_dict(workflow)
    try:
        return self._run_inner(workflow, shared)
    finally:
        shared["__pflow_cache_render__"] = saved_cache_render
    ```
    **Always install (never gated on truthiness).** Sub-workflow children must mask the parent's value even if the child has no cache declarations — otherwise a parent's cache_block leaks into a child without one. Per `engine.py:173–180` documentation: write-back assignment, not `.pop()`, because `shared` may be a `NamespacedSharedStore`.

- `src/pflow/runtime/CLAUDE.md`:
  - Add `__pflow_cache_render__` to the "Reserved Shared Store Keys" canonical reference. Document the value shape (`dict[str, CacheRenderContext]`), the engine-installed-and-restored lifecycle, and the read site (`LLMNode.prep()`).

## B3.3 — Plan_node renders cache content and includes it in the hash

### Files

- `src/pflow/runtime/engine/plan_node.py`:
  - **Reorder**: move template resolution BEFORE config-hash computation. New shape:
    1. If `config.template_config and not config.batch_config`: call `resolve_templates(...)` for non-batch nodes (existing behavior, just moved earlier in the function).
    2. Read `cache_ctx = shared.get("__pflow_cache_render__", {}).get(config.node_id)`.
    3. If `cache_ctx is not None and cache_ctx.subset`: render `prompt_cache_content` via the new helper `_render_cache_for_hash(cache_ctx, resolved_params, shared)`. The helper:
       - Walks `cache_ctx.cache_block["items"]` filtered to `cache_ctx.subset`, in declaration order.
       - For each chunk: resolves `${var}` using `TemplateResolver.extract_root_node_id` + a lookup against `shared` (NOT `resolved_params` alone — for batch nodes, `resolved_params` is `None`; the cache references are validated as non-batch in B2.3 and so resolve from `shared` directly).
       - Returns `[{"name": chunk_name, "prose": prose_before, "value": serialized_value}, ...]` where `serialized_value` uses the deterministic helper (B3 stub: `json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)`; G.1 replaces with the canonical helper).
    4. Pass `prompt_cache_content` to `compute_node_config(...)` (new keyword-only argument; see B3.4).
    5. Compute `config_hash` from the resulting config.
    6. Continue with memo-cache lookup and in-process-cache lookup as today.
  - **Strict-mode template-error path**: if `resolve_templates` raises `ValueError`, the existing early-return at lines 57–68 still fires. The cache content is not rendered (correct — there's nothing to hash for; the `template_exception` branch returns).
  - **Empty subset**: when `cache_ctx is None` OR `cache_ctx.subset` is empty, `prompt_cache_content` is `None` and `compute_node_config`'s conditional include doesn't fire. Hash byte-identical to pre-task. This is the load-bearing DD#19 path.
  - Update plan_node's docstring to document the new ordering and the rendering invariant.

## B3.4 — `compute_node_config` accepts rendered cache content

### Files

- `src/pflow/runtime/engine/instrumentation.py`:
  - Extend `compute_node_config` signature: add `*, prompt_cache_content: list[dict[str, Any]] | None = None` as a **keyword-only** parameter. Keyword-only (after `*`) prevents future callers from accidentally feeding the wrong thing as a 5th positional arg.
  - Add conditional inclusion at the end of the function (after the existing `batch_config` branch):
    ```python
    if prompt_cache_content:
        config["prompt_cache"] = prompt_cache_content
    ```
  - Truthy-list check is load-bearing: empty list `[]` falls through (treated as no opt-in per spec edge case "Empty `prompt_cache` list" + DD#19).

### Tests

- `tests/test_runtime/test_prompt_cache_hash.py` (new — load-bearing gate):
  - **CRITICAL REGRESSION**: load `tests/test_runtime/fixtures/golden_config_hashes.json` (committed in pre-merge step). For each entry, recompute the hash against current code. Assert byte-equality. If any node's hash drifts, FAIL with a clear message naming the workflow + node.
  - Workflow with `prompt_cache: [concept]` produces DIFFERENT hash than the same workflow without the field.
  - Two invocations with `prompt_cache: [concept]` but different resolved `concept` values produce different hashes.
  - Empty `prompt_cache: []` produces the SAME hash as absent.
  - Three-state distinction: (1) no field, (2) `prompt_cache: []`, (3) `prompt_cache: [chunk]`. Assert (1) === (2) at hash AND rendering levels (no `cache_control` markers, no `system_blocks` list — plain string `system`); (3) is distinct from both.
  - Node with `cache: false` AND `prompt_cache: [concept]`: memo cache write skipped (existing `cache_enabled=False` behavior); cache rendering still applies at runtime; in-process cache hash is computed correctly.
  - **Batch-node hash inclusion**: a batch LLM node with `prompt_cache: [concept]` produces a different hash than the same batch node without the field. The batch resolution path renders cache content from `shared` (non-batch refs only), independent of per-item template resolution.

### Regression invariants — STOP IF ANY FAIL

- `tests/test_execution/test_plan_drift.py` (verified at plan-write: 6+ test cases at lines 45–172): planner ↔ runtime parity. The drift test sees the same memo cache state across both code paths; cache rendering produces identical content, hashes match. New ordering (resolve before hash) must not break this.
- All 7 files in `examples/` using `cache: false` execute identically — parameterize over all 7 in a single integration test, not "pick one." Cost is small; coverage gap was large in earlier draft.
- All ~212 existing LLM-related tests pass.

If the regression gate fails: STOP. Silent stale cache is unacceptable.

---

# Phase C0 — Gemini explicit cache_control verification spike (paid)

## Goal

Verify with one paid call (~$0.10) that LiteLLM's Gemini path actually emits `cache_control` markers in a way that fires the explicit-cache mechanism (returns `cache_creation_input_tokens > 0` on call 1, `cache_read_input_tokens > 0` on call 2), distinguishing from Gemini's implicit auto-cache.

This blocks C2 only. C1 (Anthropic) and C3 (OpenAI) can be implemented in parallel.

## Spike script

- `scratchpads/task-159-c0-gemini-cache-spike.py` (new, do NOT run as part of the implementation plan — the implementing agent runs it after authorization):
  - Pattern: minimal Python file calling `litellm.completion` directly with a Gemini Flash model (cheapest), a 1500+ token `cache_control: {type: ephemeral}` system prefix, and a different per-call user message.
  - Inject API keys: `from pflow.core.settings import SettingsManager; for k, v in (SettingsManager().load().env or {}).items(): if v and k not in os.environ: os.environ[k] = v`.
  - Make two sequential calls with the same cached prefix.
  - Print `response.usage.prompt_tokens_details.cached_tokens` (which the adapter normalizes to `cache_read_input_tokens` per `llm_client.py:751–755`) and `response._hidden_params["response_cost"]` for both calls.
  - Pass: call 2 reports `cached_tokens > 0`. Fail: both calls report 0.
  - **Cleanup**: delete the spike script after the C2 patch lands.

## Fallback

If the spike fails (Gemini doesn't honor explicit `cache_control` via LiteLLM): per the handoff spike-table fallback, document Gemini explicit-cache as best-effort. Ship C2 anyway — emit the markers — and add an info note in `analyze-cache` Gemini output: "Gemini cache hits cannot be distinguished from implicit auto-cache via the API response; check the GCP billing dashboard for explicit-cache savings."

---

# Phase C1 — Adapter signature widening + Anthropic cache rendering

## Goal

Extend `complete()` to accept structured `system` content blocks with `cache_control` markers, render an Anthropic-flavored cache prefix when `prompt_cache` is declared on a node, and propagate cache-creation/read token counts into `usage` (already happens for Anthropic per `llm_client.py:749`).

## C1.1 — `complete()` signature

### Files

- `src/pflow/core/llm_client.py`:
  - Widen `system` parameter (line 173) from `str | None` to `str | list[dict[str, Any]] | None`. Update the docstring at line 219 to document both shapes:
    - `str` — plain text system message (today's behavior, unchanged).
    - `list[dict]` — content blocks per the LiteLLM/Anthropic/OpenAI SDK convention. Each block is `{"type": "text", "text": "...", "cache_control": {"type": "ephemeral", "ttl": "1h"}}` (Anthropic) or just `{"type": "text", "text": "..."}` for chunks that are part of a cached prefix but don't bear the marker themselves. The marker must appear on the LAST chunk only (v1 single-breakpoint strategy per DD#11).
  - Inside `_build_messages` (line 579–602): the existing `messages.append({"role": "system", "content": system})` works unchanged for both shapes — LiteLLM accepts either (verified §27 in progress log). No code change required if the type widening is the only delta. The implementing agent verifies with a smoke call (mocked) that a list-of-blocks reaches LiteLLM intact.

- `tests/shared/llm_mock.py`:
  - Widen `MockLLMClient.complete()`'s `system` parameter (line 194) from `Optional[str]` to `Optional[Union[str, list[dict]]]`. The recorded entries in `call_history` and `call_history_full` already store `system` verbatim, so cache-structure tests can inspect `call_history_full[-1]["system"]` directly.

### Tests

Move actual cache-rendering tests to C1.2 — these widening tests are pure type/signature verification:
- Append a test in `tests/test_nodes/test_llm/test_llm_integration.py` (or new `test_llm_adapter_cache_signature.py`) that confirms `complete(system=[{...}], ...)` runs without TypeError. Skipped under no-key path.
- `tests/shared/llm_mock.py` round-trip test: a `system=[{...}]` call records the structured shape in `call_history_full[-1]["system"]`.

## C1.2 — LLMNode → adapter cache rendering (Anthropic)

### Files

- `src/pflow/nodes/llm/llm.py`:
  - In `prep()` (line 231): read `cache_ctx = shared.get("__pflow_cache_render__", {}).get(self.node_id)`. **Do NOT cache `cache_ctx` on `self`** — `LLMNode` is reused across batch items per `nodes/CLAUDE.md` Pitfall #6, so any `self.X = result` would leak across iterations (Task 106 `_resolved` anti-pattern). The context is read fresh from `shared` on every `prep()` call. If `cache_ctx is None or not cache_ctx.subset`: skip cache rendering entirely; `prep_res["system"]` stays a plain string (today's behavior, byte-identical for opt-out nodes).
  - When `cache_ctx` is set with a non-empty subset, build `prep_res["system_blocks"]` (new key — a `list[dict]`):
    1. If the user's `system` param is set (existing `self.params.get("system")`), prepend it as the FIRST content block: `{"type": "text", "text": <user system>}` — NO `cache_control` marker. User-provided system text is not part of the cache prefix.
    2. Walk `cache_ctx.cache_block["items"]` filtered to `cache_ctx.subset`, in declaration order. For each chunk:
       - Resolve `${var}` against `shared` (use `TemplateResolver`; consult `data_flow.py:18` for the var-name pattern).
       - Serialize via the deterministic helper (Phase G stub for now: `json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)`).
       - Produce a content block: `{"type": "text", "text": prose_before + serialized_value}`.
    3. Place a `cache_control` marker on the LAST block (v1 single-breakpoint strategy per DD#11). Per-provider translation (spec "TTL wire-format translation per provider"):
       - **Anthropic**: marker is `{"type": "ephemeral"}` for omitted/`5m` (Anthropic does NOT accept `ttl: "5m"` per progress log §29 — omit `ttl` for the 5-min default); `{"type": "ephemeral", "ttl": "1h"}` for `1h`.
       - **Gemini**: `{"type": "ephemeral"}` for omitted; `{"type": "ephemeral", "ttl": "300s"}` for `5m`; `{"type": "ephemeral", "ttl": "3600s"}` for `1h`.
       - **OpenAI**: cache_control markers are no-op on OpenAI; emit them anyway for consistency, plus the OpenAI-specific knobs in C3.
    4. The TTL value is read from `cache_ctx.cache_block.get("ttl")` (the workflow-level `- ttl:` field). Provider lookup via `detect_provider(model)` from `core/llm_providers.py`.
  - In `_call_llm` (line 332): pass `system=prep_res["system_blocks"]` to `complete()` when `system_blocks` is set; otherwise pass `system=prep_res["system"]` (today's plain-string path). The adapter widening in C1.1 accepts both.
  - **NO min-token threshold check at runtime.** Per DD#36 ("`pflow run` validation: no tokenizer, no historical state"), this expensive check moves to the analytical tier (`pflow analyze-cache` and `pflow run --dry-run`) where `litellm.token_counter` is permitted. The `cache.below-min-tokens` warning fires from F2's `analyze.py`, not from `LLMNode.prep()`. Earlier-draft runtime emission was inconsistent with DD#36.
  - **Cache-rendering template-resolution failure path** (per spec line 189): if a chunk's `${var}` fails to resolve at runtime (e.g. an upstream node failed), use the existing `build_template_error_diagnostic` pattern from `runtime/engine/template_errors.py`. Build the diagnostic with `node_id=self.node_id`, the chunk's `_source_line`, and the failing reference. Return an error-dict from `_call_llm` (mirrors the typed-exception path at `_error_dict_from_exception`) so the Node retry loop short-circuits.
  - **Branch-absent skip** (spec edge case "Cache block references a step output on a branch that didn't execute"): when iterating chunks during rendering, if `${var}` resolves via `node_state.get_node_status` to ABSENT (the upstream node didn't execute), SKIP the chunk silently. Document this behavior in the rendering helper's docstring. The cache prefix is shorter for the affected call but still valid.

### Tests

- `tests/test_nodes/test_llm/test_prompt_cache_rendering.py` (new):
  - Anthropic node with `prompt_cache: [concept]` and a registered cache block: `MockLLMClient.call_history_full[-1]["system"]` is a list with at least one block carrying `cache_control: {"type": "ephemeral"}` on the last cache chunk; the user-provided `system` param (when set) appears as the first chunk WITHOUT a marker.
  - Anthropic with `- ttl: 1h` → marker is EXACTLY `{"type": "ephemeral", "ttl": "1h"}`.
  - Anthropic with `- ttl: 5m` → marker is EXACTLY `{"type": "ephemeral"}` (no `ttl` key). Assert `"ttl" not in marker` AND `len(marker) == 1`. Catches the bug where someone "symmetrically" emits `ttl: "5m"`.
  - No `prompt_cache` → `system` is a plain string (today's behavior).
  - Empty `prompt_cache: []` → `system` is a plain string. Three-state equivalence verified at the rendering level (mirrors B3.4 hash-level test).
  - Cache chunk references an absent branch's output → chunk silently skipped; remaining chunks render correctly; markers placed correctly on the (shortened) chunk list.
  - Cache-rendering template-resolution failure → error-dict returned from `_call_llm`; no retry; structured diagnostic with chunk `_source_line` + the failing reference.
  - `cache: false` AND `prompt_cache: [concept]` on the same node: rendered system_blocks STILL carry `cache_control` markers (cache rendering applies independently of memo cache opt-out). Verifies the two-layer independence per spec "Cache Layer Independence".
  - Structured output (`output_schema`) + `prompt_cache`: the schema's `tools` injection (Anthropic structured output uses tools) does NOT displace cache_control markers from the system blocks.
  - Extended thinking + `prompt_cache`: thinking budget tokens do NOT count against `cache_creation_input_tokens`. The thinking block is in the response, not the request; cache prefix is request-side only.
  - **Parallel-batch ordering**: test that uses 8 parallel batch items finds at least one entry in `call_history_full` with the expected `cache_control` shape, but does NOT assert on `call_history_full[-1]` (last-to-append is non-deterministic across worker threads). Search/filter, never index by position.

### Test infrastructure prerequisite

- Widen `MockLLMClient.complete()`'s `system` parameter from `Optional[str]` to `Optional[Union[str, list[dict]]]` (line 194). The recorded entries in `call_history_full` already store `system` verbatim; cache-structure tests inspect `call_history_full[i]["system"]` directly. Update `tests/shared/llm_mock.py` and add a round-trip test asserting `system=[{...}]` is recorded as a list, not a stringified version.
- Extend `MockLLMClient.set_response(...)` to accept `cache_creation_input_tokens` and `cache_read_input_tokens` keyword args (default 0). They populate the returned `usage` dict so trace tests can simulate cache hits with specific token counts. Without this, downstream cache-correlation tests need ad-hoc monkey-patching.

### Tests

- `tests/test_nodes/test_llm/test_prompt_cache_rendering.py` (new):
  - Anthropic node with `prompt_cache: [concept]` and a registered cache block: `MockLLMClient.call_history_full[-1]["system"]` is a list with at least one block carrying `cache_control: {"type": "ephemeral"}` on the last cache chunk; the user-provided `system` param (when set) appears as the first chunk WITHOUT a marker.
  - Anthropic with `- ttl: 1h` on the cache block → marker is `{"type": "ephemeral", "ttl": "1h"}`.
  - No `prompt_cache` → `system` is a plain string (today's behavior, no list).
  - Empty `prompt_cache: []` → `system` is a plain string.
  - Below-threshold rendered content emits `cache.below-min-tokens` warning to `__warnings__`.
  - Structured output (`output_schema`) + `prompt_cache` co-exist correctly (system blocks unaffected by schema).
  - Extended thinking + `prompt_cache` co-exist correctly (per Anthropic docs; LiteLLM Phase 0 spike findings in Task 158 §27 — cache markers compose with `thinking={"type":"enabled","budget_tokens":...}`).

### Regression invariants

- `tests/test_execution/test_plan_drift.py` stays green.
- All existing LLM tests pass (the type widening is null-safe; default `system: str | None` callers see no shape change in their messages).

---

# Phase C2 — Gemini cache rendering path

## Goal

Same rendering surface as C1 but for Gemini. Triggers `cachedContents` via LiteLLM's translation (verified by C0 spike). Honors Gemini's seconds-suffix TTL format.

## Files

- `src/pflow/nodes/llm/llm.py` (extend the per-provider TTL translation in `prep()`):
  - For Gemini (`detect_provider(model).name == "gemini"`):
    - omitted/default → `cache_control: {"type": "ephemeral"}`.
    - `5m` → `cache_control: {"type": "ephemeral", "ttl": "300s"}`.
    - `1h` → `cache_control: {"type": "ephemeral", "ttl": "3600s"}`.

## Tests

- Extend `tests/test_nodes/test_llm/test_prompt_cache_rendering.py`:
  - Gemini renderings produce the seconds-suffix TTL.
  - Multi-marker collapse note: when batch auto-prefix (Phase D) adds a second marker, only the latter takes effect on Gemini per spec "Breakpoint Limit Handling". v1's 2-marker max degrades correctly because the latter marker's prefix is a superset of the earlier. Add a test asserting both markers are emitted (the adapter doesn't filter them); the Gemini-side collapse is provider behavior, not pflow's responsibility.

## Gating

- C0 spike must have run successfully OR the fallback ("ship anyway with caveat in analyze-cache") is documented.

---

# Phase C3 — OpenAI cache rendering path

## Goal

OpenAI doesn't use `cache_control` (auto-cache only), but it exposes two pflow-relevant knobs: `prompt_cache_key` for sticky routing on parallel batches and `prompt_cache_retention` for the 1h-TTL opt-in (per DD#37). Emit both when applicable.

## Files

- `src/pflow/nodes/llm/llm.py` (in `prep()` per-provider branch):
  - For OpenAI (`detect_provider(model).name == "openai"`):
    - `system_blocks` is rendered the same way (the content matters for OpenAI's auto-cache prefix detection); but no `cache_control` markers are emitted (no-op on OpenAI).
    - When `prompt_cache_items` is non-empty, compute `prompt_cache_key = hashlib.md5(_deterministic_json(rendered_cache_content).encode(), usedforsecurity=False).hexdigest()` (mirrors `compute_config_hash` per progress log §27 finding; MD5 is the project convention with `# noqa: S324`).
    - When the workflow `cache_block.ttl == "1h"`, emit `prompt_cache_retention = "24h"` per DD#37. Both values are passed through `model_options` to LiteLLM, NOT via the typed reasoning channel (model_options is the existing escape hatch for raw provider params at `llm_client.py:235–239`). Note: the adapter's `_validate_model_options` rejects reasoning keys but allows everything else, so this works.

- `src/pflow/core/llm_client.py`:
  - The `model_options` channel already passes through to `litellm.completion(**kwargs)` at line 277–279. No code change.

## Tests

- Extend `tests/test_nodes/test_llm/test_prompt_cache_rendering.py`:
  - OpenAI node with `prompt_cache: [concept]` → `MockLLMClient.call_history_full[-1]["model_options"]` contains `prompt_cache_key` (MD5 hex; deterministic across two calls with identical resolved values).
  - OpenAI node with `cache_block.ttl == "1h"` → `prompt_cache_retention: "24h"` in `model_options`.
  - OpenAI node with no `prompt_cache` → no cache-related kwargs leak into `model_options`.

## Phase D paid-spike preview

The OpenAI `prompt_cache_key` parallel-routing spike lives in Phase D — the test above only verifies the key is emitted; the spike verifies it actually achieves sticky routing under live parallel load.

---

# Phase D — Auto-batch-prefix detection + prewarm execution

## Goal

Two pieces, both flowing through the `CacheRenderContext` channel established in B3 (no new reserved keys):
1. LLMNode performs auto-batch-prefix detection: read `cache_ctx.unresolved_batch_prompt` and `cache_ctx.batch_alias`; find the first `${<alias>.X}` reference; everything before it is the static prefix; insert a second `cache_control` marker at the end of that prefix when `cache_ctx.prewarm` is true.
2. Batch executor's prewarm execution: serialize item[0], wait for cache write, then fan out items[1:]. The executor reads `prewarm` from `cache_ctx`, NOT from `node.params`.

Plus the OpenAI parallel-routing paid spike.

## Pre-implementation verification

1. Confirm B3 has landed and `_build_cache_render_dict` populates `unresolved_batch_prompt` and `batch_alias` correctly for batch LLM nodes.
2. Read `runtime/engine/batch_executor.py` end-to-end. Confirm per-item template resolution lives in the `_execute_single_node` callback, not in `batch_executor` (per progress log §29 — option (c) for detection was rejected for this reason).

## D.1 — LLMNode auto-batch-prefix detection in `prep()`

### Files

- `src/pflow/nodes/llm/llm.py` (in `prep()`, after the cache rendering done in C1.2):
  - `cache_ctx = shared.get("__pflow_cache_render__", {}).get(self.node_id)` — already read for C1.2.
  - **Gating**: per spec DD#9 / "Auto Batch-Prefix Caching", the detection fires when `cache_ctx.prewarm is True` AND the node is a batch (`cache_ctx.unresolved_batch_prompt is not None AND cache_ctx.batch_alias is not None`) — INDEPENDENT of `cache_ctx.subset`. A node with `prewarm: true` and no `prompt_cache:` declaration still gets auto-batch-prefix detection. In that case `prep_res["system_blocks"]` may be empty/absent (no declared cache to render), but the user-message content blocks still receive the auto-marker on the static prefix.
  - When the gate fires:
    - Find the position of the first `${<batch_alias>(\.|\[)` reference in `cache_ctx.unresolved_batch_prompt` (regex: `r"\$\{" + re.escape(cache_ctx.batch_alias) + r"(\.|\[)"`).
    - If no match → no batch-scoped reference; auto-batch-prefix is N/A; skip the rest. (The whole prompt is static; declared cache already covers it OR the user opted into prewarm without intent — runtime emits nothing per DD#36; F2 catches this case.)
    - If `match.start() == 0` → no static portion; skip. F2 emits `cache.prewarm-no-prefix` in the analytical tier when this case is detected with `prewarm: true` declared.
    - Otherwise: the static portion is `unresolved[:match.start()]`. Resolve non-batch templates within it using `TemplateResolver` against the current `shared` store. The resolved string is the auto-batch cache prefix.
  - **Marker insertion** — only when `cache_ctx.prewarm is True`:
    - The auto-batch-prefix is part of the USER message (it's the static portion of the prompt template, before the `${item.X}` substitution). Insert a content block in the user message: `{"type": "text", "text": <resolved static prefix>, "cache_control": {"type": "ephemeral"}}`.
    - Build `prep_res["user_message_blocks"]` (NEW key — analogous to `system_blocks`): a list of content blocks for the user role. Block ordering: the cache-marked static prefix block, then the dynamic suffix (the rest of the prompt template after the cut, resolved per-item by the existing template resolver), then any attachments.
    - When `cache_ctx.prewarm is False or absent`: do NOT insert the auto-marker (per DD#9 / DD#36 — runtime never blocks; the savings-ratio recommendation flows through `analyze-cache` only).
  - **TTL on the auto-marker**: matches the workflow `cache_block.ttl` per the same provider translation table used in C1.2. The auto-marker uses the same TTL as the declared cache.
  - **Multi-marker placement on Anthropic vs Gemini** (per spec "Breakpoint Limit Handling"): with both a system-cache marker (declared) and a user-message-prefix marker (auto-batch), v1 emits both. Anthropic accepts up to 4 cache_control markers; Gemini's `cachedContents` is single-blob and silently drops all but the last marker. The plan does not filter — the adapter sends what's emitted. Document this in the test for C2.
- `src/pflow/core/llm_client.py`:
  - `_build_messages` (line 579): when the caller passes `user_message_blocks` (new optional kwarg), use that as the user `content`. Today the user message is constructed from `prompt` + `attachments`. Mirror the structure: when `user_message_blocks` is passed, the function uses it directly; when absent, current behavior (build from `prompt` + `attachments`).
  - The widening here is type-only (mypy) plus a small dispatch branch. Confirm `_build_messages.system` parameter type also widens to `str | list[dict[str, Any]] | None` (mypy required — C1.1 left this implicit).

### Tests

- `tests/test_nodes/test_llm/test_batch_cache_prefix.py` (new):
  - Batch with `prewarm: true` + `prompt_cache: [concept]`: rendered messages carry BOTH the system-cache marker (from declared cache) AND a user-message-prefix marker. Search/filter `call_history_full` (parallel-batch ordering non-deterministic).
  - The user-message marker's `text` is byte-identical across all batch items (otherwise no cache hit).
  - The marker is on the static-prefix block, NOT on the dynamic suffix block. Assert by inspecting block order.
  - Batch with `prewarm: false`: no user-message marker; only the system-cache marker. All items dispatched in parallel from the start.
  - Batch size N=1: skip auto-batch-prefix entirely (no fan-out opportunity).
  - Static prefix detection finds the correct cut even when a `${non-batch-ref}` appears earlier in the template (the batch alias is the boundary, not the first `${...}`).
  - When `${item.X}` is at position 0 (no static portion), no auto-prefix marker is added — but if `prewarm: true` was declared, emit `cache.prewarm-no-prefix` info diagnostic ONLY from the analytical tier (F2). Runtime emits nothing (per DD#36). Document this in the test as expected.

### Hedged-claim verification (list/dict resolved values)

- `tests/test_integration/test_prompt_cache_value_types.py` (new):
  - `${some-batch.results}` resolves to a list → JSON-serialized via deterministic helper.
  - `${count}` resolves to int → JSON-serialized.
  - `${concept}` resolves to dict → JSON-sorted-keys-serialized.
  - All three produce stable cache_keys across two runs.

## D.2 — Prewarm execution (serialize first, fan out rest)

### Files

- `src/pflow/runtime/engine/batch_executor.py`:
  - At the top of `_execute_parallel`, read `prewarm = shared.get("__pflow_cache_render__", {}).get(config.node_id, None)`. If `prewarm and prewarm.prewarm`: execute item[0] sequentially first via the existing single-item path; wait for completion (which writes the cache); then start the parallel fan-out for items[1:].
  - **No `node.params` mutation, no `__prewarm__` reserved param key.** The batch executor reads `prewarm` from `CacheRenderContext` like every other consumer.
  - Sequential mode (`parallel: false`): ignores prewarm (no fan-out, no opportunity).
  - **Error-handling × prewarm matrix** (review-feature-interactions C2 — must be specified, not punted):
    - `error_handling: fail_fast` AND item[0] fails → raise as today (BatchNode error path); items[1:] never start. Verify the on-error edge handling still fires correctly.
    - `error_handling: continue` AND item[0] fails → fan out items[1:] anyway. The cache_write didn't happen, so items[1:] all pay full write cost — the user opted out of fail_fast and accepted partial savings. Document this as expected behavior in the test.
    - `error_handling: continue` AND item[0] succeeds AND its cache write was below provider min-tokens (silent provider no-op) → items[1:] all pay write cost (no read benefit). The analytical `cache.below-min-tokens` warning catches this at `analyze-cache` time; runtime emits nothing per DD#36. Document this case.

### Tests

Append to `tests/test_nodes/test_llm/test_batch_cache_prefix.py`:
- Prewarm + fail_fast + item[0] fails → raises; items[1:] not dispatched. Verify via call count on `MockLLMClient`.
- Prewarm + continue + item[0] fails → items[1:] dispatched anyway, all marked as cache-write attempts (no reads).
- Prewarm + item[0] succeeds → item[0] completes BEFORE items[1:] start (verify via timing or via `call_history_full` insertion order on a single-threaded mock; for parallel determinism, mock `time.sleep` or use a barrier).

## D.4 — OpenAI parallel-routing paid spike (~$0.10)

### Spike script

- `scratchpads/task-159-d-openai-routing-spike.py` (new, do NOT run as part of the implementation; runs after authorization):
  - Pattern: 4–8 parallel OpenAI calls with the same `prompt_cache_key` and a 1500+ token shared prefix.
  - Inject keys per the C0 pattern.
  - For each call, log `response.usage.prompt_tokens_details.cached_tokens`.
  - Pass: most calls (≥ N-1) report `cached_tokens > 0` after the first one writes.
  - Fail: cache hits are random; suggests no sticky routing or the soft-cap kicked in.
  - Cleanup: delete after the spike outcome is recorded in progress log.

### Fallback

If routing degrades on parallel batches: per the handoff spike-table fallback, document the degraded hit rate in `analyze-cache` OpenAI output and emit `prompt_cache_key` regardless (it never hurts).

## D merge gate

- `test_engine_prompt_cache_plumbing.py`, `test_batch_cache_prefix.py` pass.
- `test_plan_drift.py` stays green.
- Existing batch tests pass (`tests/test_runtime/test_batch*` and `tests/test_runtime/test_compiler*`).

---

# Phase E — Trace format 2.1.0

## Goal

Bump the trace format constant, add per-event `cache_key`/`cache_source`/`cache_age_sec` and top-level `workflow_path`. Cost reporting unchanged (LiteLLM normalization in `llm_client.py:776–784` already handles the cache token counts). Per the handoff spike-table, an Anthropic per-TTL pricing precision spike is gated on whether 1h-TTL ships in v1.

## Pre-implementation verification

Read `runtime/workflow_trace.py:202–238` (`_add_llm_data`) and confirm the LLM-call event payload comes from `node_output.get("llm_usage")`. Cache fields flow by extending the `llm_usage` dict the LLMNode writes (mirroring how `cache_creation_input_tokens` already flows there). The implementing agent confirms the data flow before patching.

## E.1 — Format constant + new fields (route cache metadata through `llm_usage`, NOT a sidecar)

### Files

- `src/pflow/runtime/workflow_trace.py`:
  - Bump `TRACE_FORMAT_VERSION = "2.1.0"` (line 17).
  - Constructor: add `workflow_path: str | None = None` keyword arg to `WorkflowTraceCollector.__init__`. Defaulting to `None` keeps existing test instantiations (~21 sites surveyed by review-impact-completeness) source-compatible — they continue to construct with positional/`workflow_name` kwarg only.
  - In `save_to_file` (line 463), add `trace_data["workflow_path"] = self.workflow_path` (may be `None` for legacy callers; non-None for production paths).
  - In `_add_llm_data` (line 202): no new sidecar dict. The new fields (`cache_key`, `cache_source`, `cache_age_sec`) flow via the existing `llm_usage` keyset — same path `cache_creation_input_tokens` already takes (line 217–218). When `node_output["llm_usage"]` carries those keys, they land on `event["llm_call"]` automatically. **No new code in `_add_llm_data` other than the existing `event["llm_call"] = llm_usage` assignment** — the keyset is extended at the producer side.
  - For 2.0.0 backwards-compat: existing `format_version.startswith("2.")` gate (`trace_report.py:400`) continues to work. Add an info note when `analyze-cache --from-trace` auto-load skips a 2.0.0 trace AND there are matching 2.0.0 traces present — see F3.1 update below.

- `src/pflow/nodes/llm/llm.py`:
  - In `post()` (line 431, where `shared["llm_usage"]` is populated): `usage_dict.get("cache_key")`, `usage_dict.get("cache_source")`, `usage_dict.get("cache_age_sec")` are added to the `llm_usage` dict written to `shared`. For non-cached calls, only `cache_key` is set (the key the entry was written under, available from the engine via `write_memo_cache`). For cached calls, all three are set.
  - **How does LLMNode learn the cache_key, cache_source, cache_age_sec?** They flow through the node-output dict the engine already writes via `apply_memo_hit` (cached path) or via `write_memo_cache` (write path). The engine's existing `usage` propagation is the channel; we extend the propagated keyset.

- `src/pflow/runtime/engine/instrumentation.py`:
  - `apply_memo_hit` (line 241): when restoring `cached_output` to `shared[node_id]`, the cached output already contains the prior run's `llm_usage` (the cache layer round-trips it). On a cache hit, augment it with `cache_source="memo"` and `cache_age_sec=time.time() - created_at` (where `created_at` comes from the new `memo_cache_lookup` return shape — see below).
  - `memo_cache_lookup` (line 181): change return shape to also include `created_at` from the memo cache row. Use `MemoizationCache.get_with_age` instead of `.get` for the lookup. Threads through `check_memo_cache` and `plan_node`.
  - `handle_cached_execution` (line 480): in-process cache hits don't have a `cache_key` (they're in-memory), so `cache_source="in_process"`, `cache_key=None`, `cache_age_sec=None`. Write these into `shared[node_id]["llm_usage"]` if it's an LLM node (gate on `node_type_name == "LLMNode"`).
  - `write_memo_cache` (line 297): on successful write, the cache_key passed in is what the entry will be stored under. Before the write, augment `shared[node_id]["llm_usage"]` with `cache_key=<key>` so the trace event for THIS run records the key the entry was created with. (This is correct: a cache-write event's `cache_key` is the key the writer used; a cache-hit event's `cache_key` is the key that matched.)

- `src/pflow/execution/runner.py`:
  - At line 126 (where `WorkflowTraceCollector` is constructed), pass `workflow_path=resolved.file_path or _synthesize_inline_workflow_id(resolved.ir)` so the trace carries the canonical identifier.

- `src/pflow/runtime/workflow_executor.py` (line 342):
  - The second `WorkflowTraceCollector(...)` instantiation site for child workflows. Pass the resolved child path: `WorkflowTraceCollector(workflow_name=str(workflow_path or "sub-workflow"), workflow_path=str(child_resolved_path))`. The resolved path is already in scope at line ~328 in the surrounding code per review-impact-completeness C1.

- `src/pflow/core/trace_report.py` (optional, per spec): surface `cache_source` and `cache_age_sec` in per-node markdown. If omitted, no regression — just missing detail.

## Tests

- `tests/test_runtime/test_trace_format_2_1.py` (new):
  - A run with `prompt_cache` produces a trace with `format_version: "2.1.0"`, `workflow_path` set (file path for file runs; `ir-hash:<md5>` for inline), and per-event `cache_key`/`cache_source`/`cache_age_sec` on cache-hit events.
  - A 2.1.0 trace is readable by the existing `format_version.startswith("2.")` consumer gate (`trace_report.py:400`) — no consumer-side regression.
  - `cache_age_sec` is correctly computed: write a memo entry, sleep 0.1s, hit it, assert `0.05 <= cache_age_sec <= 5.0`. Two-sided bound catches "epoch returned instead of age" bugs (review-test-fidelity C3).
  - Inline-workflow run produces `workflow_path: "ir-hash:<md5>"` matching `_synthesize_inline_workflow_id` output.
  - **Parallel-batch per-item granularity**: a parallel batch where two items hit different cache_keys (different rendered cache content per item) records BOTH cache_keys in the trace. `event["batch_items"][i]["llm_call"]["cache_key"]` is per-item, distinct per i. (Verifies the routing through `llm_usage` preserves per-item granularity, where the earlier-draft sidecar dict would have lost it.)
  - Sub-workflow run: child trace events carry the child's `workflow_path` (NOT the parent's). Verifies the workflow_executor.py:342 update.

- **Update existing tests** (review-impact-completeness C2/C3):
  - `tests/test_runtime/test_workflow_trace.py:335` and any other tests with literal `format_version: "2.0.0"` assertions: triage each. Tests that assert "trace is 2.0.0 → has these fields" stay (testing legacy compat). Tests that just emit a trace and read its version bump to `"2.1.0"`. Enumerate the affected tests in the merge gate, don't punt to "all existing tests pass."
  - Tests that construct `WorkflowTraceCollector(workflow_name="...")` continue to work (workflow_path defaults to None). No bulk update needed.

## E.2 — Anthropic per-TTL pricing precision paid spike (~$0.10)

This spike is GATED on 1h-TTL actually being selectable in v1. Per spec verification list, all three TTL values must work end-to-end in Phase C/D. The spike here verifies `litellm.completion_cost()` distinguishes 1.25× (5-min) from 2× (1h) cache writes.

### Spike script

- `scratchpads/task-159-e-anthropic-pricing-spike.py` (new, do NOT run as part of plan):
  - Pattern: two Anthropic calls with cache writes — one `5m`, one `1h` — same prefix, same cache size.
  - Compute expected costs from the documented multipliers + the model's per-token rate.
  - Compare against `response._hidden_params["response_cost"]`.

### Fallback

If LiteLLM doesn't distinguish per-TTL: compute write cost from raw `cache_creation_input_tokens × per-provider rate`, override `cost_usd` for cache-write events. The override site is `_normalize` in `llm_client.py:776–784`.

## E merge gate

- `test_trace_format_2_1.py` passes.
- All existing trace tests pass (`tests/test_runtime/test_workflow_trace.py`, `tests/test_core/test_trace_report.py`).

---

# Phase F1 — Cache analysis package skeleton

## Goal

Create `src/pflow/core/cache_analysis/` with the small, independent modules that compose into the analyzer. Each module is self-contained and tested in isolation; F2 wires them together.

## Files

- `src/pflow/core/cache_analysis/__init__.py` — re-exports `analyze`, `summarize`, `CacheAnalysis` dataclass.

- `src/pflow/core/cache_analysis/warning_catalog.py` (new):
  - Closed catalog of `cache.*` warning IDs per spec "Stable Warning ID Catalog" — encode as a single SSoT table with EVERY required attribute per ID. Per-ID contract:

    | Field | What |
    |---|---|
    | `id` | `cache.<name>` |
    | `severity` | `Severity.ERROR` / `WARNING` / `INFO` |
    | `source` | `"validator"` for run-validation IDs (`cache.order-mismatch`, `cache.unused-chunk`); `"cache_analyzer"` for analytical IDs (everything else) |
    | `category_constant` | `cache_failure` / `cache_warning` / `cache_advisory` |
    | `message_template` | Format string with named placeholders (e.g. `"{node_id}: declared {declared!r}, you wrote {actual!r}"`) |
    | `required_context_keys` | Tuple of `(name, type)` pairs the diagnostic MUST carry in `context` |
    | `suggestions_template` | List of suggestion-template strings with named placeholders. MUST include explicit alternatives where applicable (e.g. `cache.batch-prewarm-recommended`'s suggestions list both `prewarm: true` AND `prewarm: false` so the agent knows opt-out also suppresses the warning). |
    | `path_template` | `"nodes[id={node_id}].prompt_cache[{i}]"` shape, where applicable |
    | `nullable_cost_keys` | Set of `context.*_usd` keys that may be `null` under cost-degradation tri-state |

  - Helper: `make_diagnostic(warning_id, *, node_id=None, **context_kwargs) -> Diagnostic` reads the catalog row, formats the message + suggestions from templates, attaches `id=warning_id`, `source` (split per ID per the table above — NOT uniform `"cache_analyzer"`), `context["category"]` from `category_constant`, `see_also=["caching"]`, and `path` from `path_template`.

  - **Source split is load-bearing** (review-agent-ux Critical): structural validator-emitted IDs (`cache.order-mismatch` from B2.3, `cache.unused-chunk` from B2.3) use `source="validator"`. Analytical-emitted IDs use `source="cache_analyzer"`. Diagnostic dedup identity tuple `(severity, source, node_id, id or message)` collapses identical findings within a source but NOT across sources — so the same ID emitted from both surfaces (e.g. `cache.order-mismatch` reaching the analyzer's output via validation pre-check) survives as one entry per surface, which is the desired behavior.

  - **`cache.below-min-tokens` is analytical-only** per spec catalog AND DD#36. It does NOT fire from `LLMNode.prep()` at runtime. The analyzer (F2's `analyze.py`) computes the threshold check and emits this ID. C1.2's earlier-draft runtime emission was wrong; that emission is removed.

  - **`cache.discrepancy`** (used in spec mode-4 from-trace example): NOT in the v1 catalog. Surface to user during plan implementation: is this a 9th catalog entry (DD#29 design review) OR a one-off label that doesn't enter the closed catalog? Recommend: emit as a generic Diagnostic in trace-mode without a stable `id`, OR add as the 9th catalog entry under `cache_advisory`. Plan-writer's preference: add as 9th entry; this needs a one-line user decision.

  - Test in `tests/test_core/test_cache_analysis_warnings.py`: parameterized over every catalog entry. Asserts: (1) `make_diagnostic(id, ...)` produces the expected severity/source/category/message/suggestions; (2) `path` matches the template; (3) `id` is in the diagnostic's `id` field (not buried in context); (4) byte-equality of the canonical message format for at least one example invocation per ID.

- `src/pflow/core/cache_analysis/token_estimation.py` (new):
  - `estimate_tokens(model, text, *, trace=None, memo_cache=None, node_id=None) -> tuple[int, str]` returns `(token_count, source)` where `source` is one of `"trace"` | `"memo"` | `"estimator"` | `"heuristic"` per DD#31. Tier order (highest fidelity first):
    - `trace`: when `trace` (a parsed 2.1.0 trace dict) is provided AND a per-event entry exists for `node_id` carrying `llm_call.input_tokens`, source is `"trace"`. This is the from-trace ground-truth source — only path that gets discrepancy analysis in `--from-trace` mode.
    - `memo`: when no trace data, but `memo_cache` is provided and `get_latest_for_node(node_id, workflow_path=...)` returns a recent entry (within 24h) AND that entry contains `llm_usage.input_tokens`, source is `"memo"`.
    - `estimator`: `litellm.token_counter(model=model, text=text)` lazy-imported (mirrors `llm_client.py`'s lazy import). Successful return → source `"estimator"`.
    - `heuristic`: `len(text) // 4` last-resort fallback.
  - Errors from `token_counter` (unknown model, raises) → log via `logger.warning` (not silent — review-silent-failures W2 — a model-name typo deserves visibility beyond a confidence label) and fall through to `heuristic`.

  - Test in `tests/test_core/test_cache_analysis_token_estimation.py`:
    - When trace data EXISTS AND memo data EXISTS: source is `"trace"` (not `memo`). Catches tier-inversion bugs.
    - When trace ABSENT, memo EXISTS, `token_counter` works: source is `"memo"` (not `estimator`).
    - When all upstream sources fail: source is `"heuristic"` AND result equals `len(text) // 4` exactly.

- `src/pflow/core/cache_analysis/cross_workflow.py` (new ~130–240 LOC per progress log §30 corrected estimate):
  - `walk_cross_workflow(root_ir, base_path, *, max_depth=10) -> list[CrossWorkflowEdge]` — recursive walker using `resolve_sub_workflow` (the primitive at `core/workflow/sub_workflow_resolver.py`).
  - For each `WorkflowExecutor` node, read `node["params"]["workflow"]` and `node["params"]["inputs"]`. Resolve to child IR via the primitive. Recurse on the child IR with depth limit and cycle detection (set of resolved paths) — mirrors mermaid's `_render_workflow` traversal at `_render.py:94–130`.
  - Each `CrossWorkflowEdge` carries `parent_workflow`, `child_workflow`, `parent_value_expr`, `child_input_name`, `line_in_parent`.
  - Three detection rules per spec "Cross-Workflow Walker":
    - **Rename detection** (`cache.cross-workflow-rename-detected`): when a parent edge has `child_input_name != tail_of_parent_value_expr`.
    - **Prose mismatch** (`cache.cross-workflow-prose-mismatch`): when names match across the boundary AND parent and child both declare `## Cache` blocks with the same chunk identifier AND the prose-before-the-`${var}` differs byte-by-byte. Suppressed when a rename was detected for the same chunk (rename takes precedence per spec).
    - **Value-flow opportunity**: parent passes a value into child but neither file's `## Cache` declares it → emits `cache.shared-context-undeclared` scoped to the boundary.
  - Batch sub-workflows: walker uses `WorkflowValidator._enumerate_child_calls` (from `validator.py:807–880`) to enumerate per-batch-item child calls when params reference the batch alias. Heterogeneous batches yield N edges; homogeneous yield 1.

- `src/pflow/core/cache_analysis/padding_advisor.py` (new):
  - `compute_padding_advisories(workflow_ir, per_node_token_estimates) -> list[Diagnostic]` — for each node whose `prompt_cache:` subset doesn't start at position 1 of the master order, compute the net-positive math per spec "Prefix-Padding Advisory". Apply the sensitivity floors ($0.005 per advisory, $0.05 cumulative). Emit `cache.padding-advisory` Diagnostics.

## Tests

- `tests/test_core/test_cache_analysis_warnings.py` (new): each warning ID emits with the right severity, context shape, source.
- `tests/test_core/test_cache_analysis_token_estimation.py` (new): tier order works; trace, memo, estimator, heuristic all reachable; confidence labels match; `litellm.token_counter` exception path falls through to heuristic.
- `tests/test_core/test_cache_analysis_cross_workflow.py` (new): rename detection, prose mismatch, value-flow opportunity, batch sub-workflow enumeration, cycle detection, depth limit.

## Regression invariants

- `test_plan_drift.py` stays green.
- The new package has no imports from `runtime/`, `nodes/`, or `cli/` (mirrors the `core/` discipline). Inputs are IR dicts and `MemoizationCache` instances; outputs are `Diagnostic` objects and dataclasses.

---

# Phase F2 — Analyzer engine

## Goal

Compose the F1 primitives into the full `analyze()` and `summarize()` entry points and the text/JSON renderers. Land golden tests mirroring `test_mermaid_golden.py`.

## Files

- `src/pflow/core/cache_analysis/analyze.py` (new):
  - `analyze(workflow, parameters: dict | None) -> CacheAnalysis` — full plan per spec "Output Format — JSON" / "Output Format — Text". Per DD#35, `parameters` is optional — token estimation falls back when input substitution can't fully resolve a prompt.
  - Auto-load most recent matching 2.1.0 trace per DD#34: scan `~/.pflow/debug/`, parse top-level `workflow_path`, match against the analyzed workflow's resolved path (or `ir-hash:<md5>` for inline). 2.0.0 traces ignored by auto-load (no `workflow_path` field).
  - **2.0.0-skip info note** (review-silent-failures C7): when auto-load finds 2.0.0 traces matching the workflow filename but skips them due to format version, append an info note to `analysis.notes`: `"Found N 2.0.0 traces matching this workflow but skipped (auto-load requires 2.1.0). Use --from-trace <path> to load explicitly."` Without this, agents see `confidence: low_no_data` and don't realize their existing traces are present-but-ignored.
  - Composes: parser → cross-workflow walker → token estimation per node → confidence labeling per DD#34 (4-level per-call, 3-level aggregate, with coverage detail) → padding advisor → recommended-actions ordering (impact descending).
  - Returns a `CacheAnalysis` dataclass with: summary fields, per-call rows, recommended actions, suggested cache blocks (when greenfield), cross-workflow findings, warnings list, notes.

- `src/pflow/core/cache_analysis/summarize.py` (new):
  - `summarize(workflow, parameters) -> Diagnostic | None` — one-line `Severity.INFO` Diagnostic (`id="cache.opportunities-available"`) for the dry-run nudge per spec "—dry-run Cache Nudge". `None` when no actionable opportunities.

- `src/pflow/core/cache_analysis/render_text.py` (new):
  - `render(analysis: CacheAnalysis) -> str` — markdown-formatted text output per spec "Output Format — Text" (the four modes: greenfield, steady-state, already-optimal, from-trace). Section ordering and per-call rendering rules per spec.
  - The cost-degradation contract (partial cost, unavailable models) per spec "Cost-estimate degradation for unknown models" — mirror Task 158's tri-state pattern (`pricing_available: bool`, `partial_cost_usd`, `unavailable_models`).

- `src/pflow/core/cache_analysis/render_json.py` (new):
  - `render_json(analysis: CacheAnalysis) -> dict` — JSON shape per spec "Output Format — JSON". `format_version: "1.0"`. Empty arrays for `cross_workflow.*` (always present in JSON).

## Tests

- `tests/test_core/test_cache_analysis_analyze.py` (new):
  - Each of the four output modes runs cleanly on a synthetic minimal workflow.
  - Confidence labels are correct given the trace/memo/estimator/heuristic mix.
  - Recommended actions are sorted by impact descending.
  - Cost degradation: unknown model produces partial cost output; never `$0.00`.

- `tests/test_cli/test_analyze_cache_golden.py` (new) — mirrors `test_mermaid_golden.py`:
  - Parametrized cases for each of the 4 modes + a 5th for cost-degradation. Synthetic minimal workflows under `tests/test_cli/golden_analyze_cache/`. Byte-exact equality. Failure message embeds the regen command.
  - **Pricing-pin strategy** (review-test-fidelity W1): `MockLLMClient.set_response(..., cost_usd=...)` only pins runtime cost — but the analyzer uses `litellm.completion_cost()` against `litellm.model_cost`, a different code path. Pin BOTH:
    - Runtime side: `MockLLMClient.set_response(cost_usd=...)`.
    - Analyzer side: `monkeypatch.setattr("litellm.completion_cost", lambda *a, **kw: <pinned value>)` in test setup. Without this, golden cost values drift whenever LiteLLM updates `model_cost`, even with the mock pinned.
  - Enumerate explicit golden files: 4 modes × 2 formats (text + JSON) + 1 cost-degradation + 1 from-trace = 10 files. Listed in the test parameterization.
  - Per-call rendering rules tested with explicit byte-equality assertions (review-agent-ux 12):
    - Default-hide-clean: a 23-row workflow hides the top 12 clean rows. Explicit `expected_text` assertion.
    - "Hidden: N nodes at ≥80% projected cache ratio with no warnings (rerun with --all-rows)." — exact text matched.
    - `--all-rows` flag: rows sorted by token volume descending. Explicit ordering test.
    - JSON `format_version: "1.0"` field present and exactly the string `"1.0"` (catches `"1"` int regression).

## Regression invariants

- `test_plan_drift.py` stays green.
- Existing CLI/MCP tests pass.

---

# Phase F3 — CLI command + MCP parity + dry-run nudge

## Goal

Surface F2 to users via three entry points: a new `pflow analyze-cache` CLI command, an `analyze_cache` MCP tool, and the `--dry-run` nudge wired through the existing plan formatter.

## F3.1 — CLI command

### Files

- `src/pflow/cli/commands/analyze_cache.py` (new):
  - Click command `analyze-cache <workflow-path> [inputs...]` with flags `--format=text|json` (default `text`), `--from-trace <path>` (explicit trace override), `--no-trace` (opt out of auto-load), `--all-rows` (per-call rendering rule per spec).
  - Calls `cache_analysis.analyze(workflow, params)`; renders via `render_text` or `render_json`.
  - Exit code: 0 on success; non-zero only on validation errors per spec.
  - Inputs are optional per DD#35.

- `src/pflow/cli/main.py`:
  - Register the new command via the existing command-discovery mechanism. Mirror `pflow visualize` or `pflow describe` registration at `cli/main.py:121–141` (the actual `cli.add_command(...)` registration pattern). Earlier draft referenced `pflow plan` — that command does not exist; `--dry-run` is a flag on `pflow run`, not a top-level command.

### Tests

- `tests/test_cli/test_analyze_cache.py` (new): exit code, all four output modes, per-call rendering rules (default-hide-clean, `--all-rows`), padding-advisory sensitivity floor, missing-pricing degradation.
- `tests/test_cli/test_analyze_cache_from_trace.py` (new): 2.1.0 fields available; 2.0.0 graceful fallback (an info message, no crash).

## F3.2 — MCP parity

### Files

- `src/pflow/mcp_server/services/execution_service.py`:
  - Add `analyze_cache(workflow, parameters) -> dict` mirroring `plan_workflow` (line 301) verbatim. Same exception handling: `WorkflowNotFoundError` (with similar_names hint), `WorkflowValidationError`, `CompilationError`, `MarkdownParseError`, generic.
  - Returns `cache_analysis.render_json(analyze(...))` — the same JSON shape as CLI `--format=json`.

- `src/pflow/mcp_server/tools/execution_tools.py`:
  - Add `@mcp.tool() async def analyze_cache(...)` (line ~178, after `plan_workflow`). Async wrapper per the file's pattern: `result = await asyncio.to_thread(_sync_op)`.
  - Add to `__all__` at line 353.

### Tests

- `tests/test_mcp_server/test_analyze_cache_tool.py` (new): MCP tool returns the same JSON as CLI `--format=json` for the same workflow + parameters. Stateless pattern (fresh service instance per call).

## F3.3 — `--dry-run` cache nudge

### Files

- `src/pflow/execution/plan.py` (or wherever `runner.plan()` builds the `Plan`):
  - After the existing plan construction, call `cache_analysis.summarize(workflow, parameters)` → if it returns a Diagnostic, append to `plan.diagnostics`.
  - Per DD#36, `--dry-run` runs the **full analytical pass** under the hood — `summarize` calls `analyze` internally.
  - Per spec "—dry-run Cache Nudge", the existing plan-formatter loop at `plan_formatter.py:139–142` already renders the diagnostic — no formatter code change needed (the loop iterates `plan.diagnostics` and calls `format_diagnostic`).

### Tests

- `tests/test_execution/test_plan_cache_nudge.py` (new):
  - A workflow with cache opportunities produces a `--dry-run` Plan whose `diagnostics` includes `cache.opportunities-available` with the locked text format from spec.
  - A workflow without opportunities → no nudge (silent).
  - The nudge appears in both text and JSON dry-run output.
  - `summarize.py` builds the message via a single locked format string (in `summarize.py`, not constructed at the call site). Pluralization is explicit: `"{n} design opportunit{y_or_ies}"` where `y_or_ies = "y" if n == 1 else "ies"`. Test both n=1 and n=4.

### Documentation note (Fix 6 — dry-run accuracy)

The dry-run cache-nudge cost prediction is computed against memo'd upstream values (per spec line 722 — `MemoizationCache.get_latest_for_node`). When upstream values change between runs, the predicted cache_keys will differ from the next actual run's cache_keys, and savings estimates may diverge from reality. **This is an inherent property of dry-run prediction, not a Task 159 regression**: today's `--dry-run` cost estimates have the same property. Document in `summarize.py`'s docstring + the F2 `analyze.py` confidence-labeling section: "Predictions assume upstream values match the most recent cached run; agents iterating on upstream nodes should re-run analyze-cache after the upstream change lands."

`test_plan_drift.py` parity is unaffected — verified by reading the test file at plan-time. The drift test compares `build_plan` and `_run` paths given the SAME memo cache state; both render cache content from the same source (memo'd values), produce the same hash. The cross-mode (predicted vs actual) divergence is a different question that the drift test was never designed to catch.

## F merge gate

- All F-phase tests pass.
- `test_plan_drift.py` stays green (the dry-run path is touched).
- CLI/MCP parity tests pass.

---

# Phase G — Deterministic serialization + guide updates

## G.1 — Deterministic serialization helper

### Files

- `src/pflow/core/cache_analysis/serialization.py` (new — or fold into `core/json_utils.py` if a similar helper already exists; the implementing agent verifies):
  - `deterministic_serialize(value) -> str` — JSON with `sort_keys=True`, stable separators `(",", ":")`, `default=str`. Per DD#13 — applied to rendered cache content for hash determinism.
  - Replace the B3 stub usage in `plan_node.py` and `nodes/llm/llm.py` with this helper.

### Tests

- `tests/test_core/test_cache_serialization.py` (new):
  - Dict ordering doesn't change output bytes.
  - List preserves order.
  - Non-JSON-native values (e.g., a `Path`) serialize via `str(value)`.

## G.2 — Agent-facing documentation

### Files

- `src/pflow/guide/` (the `pflow guide` content):
  - Add a new `caching` topic file per spec "Agent-Facing Documentation". Cover the 6 topics (automatic batch auto-prefix, explicit `## Cache` block, when to declare, order invariant, TTL opt-in, relationship to `cache: bool`).
  - Update the `llm` node section to cross-reference the caching guide.
  - The implementing agent identifies the exact file structure by reading `pflow guide` source (likely `src/pflow/guide/topics/`).

- `--no-cache` flag help text (search for the click option in `cli/main.py`):
  - Update help text to make the distinction explicit: "Disables pflow's local memoization layer only. Does NOT disable LLM provider prompt caching." (per spec "Cache Layer Independence")

- `src/pflow/cli/CLAUDE.md` and any other CLAUDE.md that documents `cache: false`: add the `prompt_cache:` cross-reference.

### Tests

- `tests/test_docs/...` — the existing doc-validation suite picks up the new guide page automatically. Add an explicit assertion that `pflow guide` output includes "caching" as a listed topic.

- `tests/test_integration/test_no_cache_flag.py` (new) — `--no-cache` regression test (review-agent-ux 20):
  - Run a workflow with `prompt_cache: [concept]` declared, with `--no-cache` flag set (`cache_enabled=False` on `RunnerConfig`).
  - Assert `MockLLMClient.call_history_full[-1]["system"]` STILL contains `cache_control` markers — `--no-cache` disables only the memo layer per spec "Cache Layer Independence", not LLM provider prompt caching.
  - Assert no memo cache write happened (the existing `cache_enabled=False` behavior).
  - This locks the spec contract that the two cache layers are independent.

## G merge gate

- All G tests pass.
- `make check` (lint, mypy) passes.
- `pflow guide caching` renders correctly when run manually.

---

# End-to-end verification

After all phases land, run the scenario-level verification per spec "Verification — Scenario-Level":

1. **Lyrics-generator end-to-end** (requires explicit user permission per handoff out-of-scope reminders): run once, record cost. Add `## Cache` blocks + `prompt_cache:` references per spec. Run again. Assert ≥40% input-cost reduction. Rerun within 1h. Assert ≥70%.
2. **Sub-workflow isolation**: standalone run of `song-creator` works.
3. **Stranger-summary isolation**: a node with no `prompt_cache:` produces a rendered message with no `cache_control` markers; trace shows `cache_read_input_tokens == 0`.
4. **Cross-workflow cache hit**: parent → child cache propagation when prose labels match.
5. **`cache: false` preserved**: existing memo opt-out still works, byte-for-byte.
6. **Analyze-cache pre-run**: text + JSON output for a greenfield workflow.
7. **Analyze-cache from-trace**: 2.0.0 graceful fallback; 2.1.0 full discrepancies section.
8. **Dry-run nudge**: appears in text + JSON; silent when no opportunities.
9. **MCP parity**: `analyze_cache` MCP tool returns identical JSON to CLI `--format=json`.
10. **Padding advisory**: emits with cost math under the sensitivity floors.

## Provider matrix (per spec)

- Anthropic Sonnet/Opus 4.5/4.6/4.7 — cache_control markers, TTL, cached-token reporting.
- Gemini 2.5/3 — cachedContents via LiteLLM; cache appears in usage metrics.
- OpenAI GPT-5-family — automatic caching fires; `prompt_cache_key` improves hit rate on parallel batches.
- Ollama — non-caching baseline still works; no cache markers leak into requests.

## Regression check

- All ~212 existing LLM-related tests pass.
- All workflows in `examples/` execute identically.
- `pflow guide` output includes the caching section.
- `test_plan_drift.py` parity tests stay green.

---

# Merge order

The handoff phase split is the recommended sequence: B1 → B2 → B3 → C0/C1/C3 (parallel after B3) → C2 (gated on C0) → D (parallel with C after B3) → E → F1 → F2 → F3 → G. C and D may parallelize after B3 lands. F gates on B+C+E. G wraps. Each sub-phase is a PR-sized chunk.

The single hard gate: **B3's regression test (no-`prompt_cache` workflows produce identical hashes pre/post task) must pass before any subsequent phase ships.** This is the silent-stale-cache guard per DD#19.

# Open hedged claims still pending plan-internal verification

These are documented above but listed here for the implementing agent's checklist:

- **B1.1** — `Diagnostic.id` field doesn't break existing tests. Verification: full `make test` after the patch.
- **B2.1** — `pflow save` round-trip preserves `## Cache` byte-for-byte. Verification: round-trip test in `test_cache_block_parser.py`.
- **B2.3** — `WorkflowExecutor._compiled_workflow_cache` interaction with sub-workflow `## Cache`. Verification: integration test where the same sub-workflow is invoked twice with different parent state.
- **D.1** — `list | str` shape for older workflow inputs/outputs. Verification: `test_prompt_cache_value_types.py` with list/dict/scalar resolved values.

If any verification fails, surface to the user before continuing.

# Summary of plan corrections from review

Applied to the plan from the 8-agent code-review pass:

**Architectural consolidation:**
- Replaced 6 scattered reserved keys (3 in `shared`, 3 in `node.params`) with single `CacheRenderContext` typed dataclass + one shared key `__pflow_cache_render__`. Mirrors `__trace_collector__` precedent. Eliminates parallel-batch concurrency surface, dunder-param-injection ordering bugs, and `compute_node_config` filtering concern in one structural change. (Top-10% pattern: Temporal `Context`, Prefect `RunContext`, gRPC request context.)
- Cache trace metadata (`cache_key`, `cache_source`, `cache_age_sec`) now flows via the existing `llm_usage` channel, NOT via `__pflow_last_cache_meta__` sidecar — preserves per-item granularity in parallel batch automatically.

**Critical structural fixes:**
- B3: `plan_node` reordered so `resolve_templates` runs BEFORE `compute_config_hash` (was opposite in current code).
- B3: batch-node `prompt_cache` hash inclusion now explicitly handled — chunks resolve from `shared` directly (validated as non-batch in B2.3).
- B3 regression baseline now generated from `main` BEFORE B3 patches and committed as `golden_config_hashes.json` — earlier draft's "compare both code paths with default None" was a tautology.
- Engine save/restore for `__pflow_cache_render__` always installs (even None/empty) and uses write-back assignment, NOT `.pop()` — `NamespacedSharedStore` lacks `pop`.
- C1.2 min-token threshold check moved from runtime to analytical tier (`analyze-cache` + `--dry-run` only) — earlier draft contradicted DD#36 ("no tokenizer at validation time"). `cache.below-min-tokens` warning now emitted by F2's `analyze.py` only.
- B2.2: validation-reach gap closed — structural cache shape checks live in BOTH the JSON schema (validator path) AND `_validate_cache_block` (compile path) since the compile path uses the minimal `validate_ir_structure`, not full `validate_ir`.
- E.1: workflow_executor.py:342 `WorkflowTraceCollector` instantiation site updated (review missed in earlier draft).
- F1: warning catalog `source` field split — `cache.order-mismatch`/`cache.unused-chunk` use `source="validator"`; analytical IDs use `source="cache_analyzer"`. Catalog SSoT now enumerates per-ID severity, source, category, message template, required context keys, suggestions template, path template, nullable cost keys.
- F3.1: `pflow plan` reference replaced with `pflow visualize` / `pflow describe` (the former does not exist).
- F3.3: dry-run accuracy documentation note added — predictions assume upstream values match memo'd state; cross-run divergence is inherent to dry-run, not a Task 159 regression.

**Algorithm specifications added:**
- B2.1 cache-block-parser algorithm explicit pseudo-code; edge cases (empty, prose-only, back-to-back `${a}${b}`, trailing prose, duplicate identifiers) all covered.
- D.2 auto-batch-prefix marker placement on USER message (not system), with explicit cut-detection algorithm.
- D.2 prewarm × error_handling matrix now enumerated (fail_fast/continue × item[0] success/fail × below-min-tokens) — earlier draft punted to "follow existing tests."

**Test fidelity improvements:**
- Three-state equivalence test (no field / `[]` / non-empty) at BOTH hash and rendering levels.
- Parallel-batch test ordering: search/filter `call_history_full`, never index by position.
- `cache_age_sec` two-sided bound to catch "epoch returned instead of age" bugs.
- Explicit test for Anthropic `ttl: "5m"` rendering as `{"type": "ephemeral"}` with no `ttl` key (asserts `"ttl" not in marker`).
- Cross-workflow walker rename-precedence-suppression test.
- All 7 `cache: false` example workflows parameterized in one test, not "pick one."
- Sub-workflow + cache_block round-trip (different parent state, same compiled IR) verifies compile-once cache doesn't corrupt.
- End-to-end `WorkflowRunner().run()` integration test in `tests/test_integration/test_prompt_cache_end_to_end.py`.
- Test infrastructure prerequisites: widen `MockLLMClient.complete()` system param + extend `set_response` to accept `cache_creation_input_tokens` / `cache_read_input_tokens`.

**Smaller fixes:**
- `_build_messages.system` parameter type widening (mypy block — was implicit in earlier draft).
- `_FAILURE_CATEGORY_MAP["cache_failure"]`: deferred until a typed exception emits it — v1 emits via Diagnostic directly, so the map entry is forward-looking only. Document or remove based on user preference.
- Cache-rendering template-resolution failure: explicit path through `build_template_error_diagnostic` per spec line 189.
- Branch-absent skip during cache rendering: explicit `node_state.get_node_status` check + silent skip.

**Round-2 corrections applied (after re-review of unaddressed findings):**
- F1 token-estimation tier order corrected to `trace → memo → estimator → heuristic` per DD#31 (was missing the `trace` tier).
- D.1 auto-batch-prefix detection now fires on `prewarm: true` ALONE (independent of `prompt_cache:` declaration) per DD#9 / spec.
- B2.3 added MCP entry-point reach verification (Task 72 historical pattern) — explicit test that `execute_workflow` produces same diagnostic structure as CLI.
- G.2 added `--no-cache` regression test asserting `cache_control` markers still present (locks the spec contract that the two cache layers are independent).
- F2 golden test pricing-pin strategy corrected — pin BOTH `MockLLMClient.set_response(cost_usd=...)` AND `monkeypatch.setattr("litellm.completion_cost", ...)` because the analyzer uses a different code path than the runtime.
- F3.1 per-call rendering rules now have explicit byte-equality assertions (default-hide-clean, "Hidden: N nodes" exact text, `--all-rows` ordering, `format_version: "1.0"` string-not-int).
- C1.2 explicitly forbids caching `cache_ctx` on `self` (Task 106 anti-pattern guard).
- F2 added 2.0.0-skip info note when auto-load finds matching traces but skips them — prevents silent confidence-degradation.
- F1 token-estimation `litellm.token_counter` exception path now logs at warning level (review-silent-failures W2) — model-name typos no longer fall through silently to heuristic without visibility.

**Deferred to phase-internal task lists** (noted but not encoded as patches):
- review-validation-consistency 4: `template_validation/` vs `data_flow.py` asymmetry — verify during B2.3 implementation whether cache chunks need template_validation reach too.
- review-impact-completeness 5: `WorkflowExecutor.ALLOWED_PARAMS` — note that `prompt_cache:` / `prewarm:` on a `type: workflow` node is correctly rejected by validator step 8.
- review-impact-completeness 9: `_NEAR_MISS_SECTIONS` typo hint for `## Cahe`.
- review-impact-completeness 15: `dependency_discovery` walker — verify cache `${var}` chunks aren't mistaken for file references during `pflow save` bundling.
- review-plan S5: spike-script cleanup — explicit phase merge gate item.
- review-feature-interactions C3: Gemini multi-marker collapse — add as explicit C0 spike verification step (not just a documented limitation).

**One open user decision still requires call:**
- `cache.discrepancy` (used in spec mode-4 from-trace example): not in v1 catalog. Add as 9th entry (DD#29 design review) OR emit as generic Diagnostic without stable id? Recommend 9th entry under `cache_advisory` — needs one-line user confirmation.

**One open user-architectural question (review-feature-interactions C2):**
- Cache rendering errors in batch + sub-workflow + `error_handling: continue`: which error category fires (`template_error` vs new `cache_failure`)? Plan currently routes through `build_template_error_diagnostic` (i.e., `template_error` category). The four-dimensional error matrix interaction (signaling × categorization × mode × propagation) isn't fully enumerated. Recommended: stay with `template_error` for v1 (consistent with existing template-resolution failure semantics; `cache_failure` is forward-looking only and currently dead code per review-impact-completeness W8). Surface to user before B2.3 lands.
