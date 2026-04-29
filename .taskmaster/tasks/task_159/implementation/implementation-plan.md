# Task 159 — Phase B–G Implementation Plan

## Context

Task 159 ships prompt caching for pflow workflows: a declarative `## Cache` block, per-node `prompt_cache:` and `prewarm:` fields, auto batch-prefix caching, `pflow analyze-cache` (CLI + MCP), trace format 2.1.0, and a `--dry-run` cache nudge. The motivating workload is `lyrics-generator` (~252 LLM calls per run); the conservative target is ≥40% input-cost reduction first run, ≥70% on within-TTL reruns.

## Architectural backbone — `CacheRenderContext`

**Decision (post-review):** all engine→LLMNode communication for caching flows through a single typed context object delivered via one reserved shared-store key. This collapses what an earlier draft scattered across 6 reserved keys (3 in `shared`, 3 in `node.params`) into one. The pattern mirrors `shared["__trace_collector__"]` exactly: engine sets, leaf node reads in `prep()`, save/restore at `engine.run()` boundary handles sub-workflow nesting.

```python
# src/pflow/runtime/engine/types.py — NEW dataclasses alongside CompiledWorkflow
@dataclass(frozen=True)
class CacheChunkIR:
    """Frozen representation of one cache chunk in the workflow-level ## Cache block."""
    name: str
    var_expr: str
    prose_before: str
    source_line: int

@dataclass(frozen=True)
class CacheBlockIR:
    """Frozen representation of the workflow-level ## Cache block.

    Replaces the earlier dict[str, Any] shape so the value is genuinely immutable
    and safe to share across parallel sub-workflow invocations via the compile-once
    cache (`_compiled_workflow_cache`)."""
    ttl: str | None                           # "5m" | "1h" | None (provider default)
    items: tuple[CacheChunkIR, ...]           # declaration order; immutable tuple
    source_line: int

@dataclass(frozen=True)
class CacheRenderContext:
    """Per-node cache rendering context, built once at engine.run() entry."""
    cache_block: CacheBlockIR | None          # workflow-level ## Cache IR (frozen)
    subset: tuple[str, ...]                   # per-node prompt_cache items, declaration order; () = no opt-in
    prewarm: bool                             # per-node prewarm flag
    unresolved_batch_prompt: str | None       # per-node, batch-only — raw template with ${item.X} intact
    batch_alias: str | None                   # per-node, batch-only — typically "item"
```

**Why `CacheBlockIR` is a frozen dataclass, not a `dict`:** the workflow-level `## Cache` IR is shared across invocations via `_compiled_workflow_cache` (keyed by resolved workflow path). A parallel batch dispatching the same sub-workflow file shares the same compiled `CacheBlockIR` object. If it were a regular `dict`, any consumer mutation (or library code accidentally calling `.setdefault` / `.update`) would corrupt other invocations. Frozen dataclass + `tuple` items eliminates the surface entirely. The `CompiledWorkflow.cache_block: CacheBlockIR | None` field at B3.1 reflects this.

**Delivery channel:** `shared["__pflow_cache_render__"]: dict[node_id, CacheRenderContext]`. Engine builds this at `run()` entry from `CompiledWorkflow` + `NodeConfig` per node. Frozen dataclass + immutable tuple = read-only-shared = parallel-batch-safe by construction.

**Outer-dict read-only invariant.** The outer `dict[node_id, CacheRenderContext]` is constructed once and passed to consumers (`plan_node`, `LLMNode.prep`, `batch_executor`) as read-only. **Wrap with `types.MappingProxyType` at install time** so any consumer mutation raises `TypeError` immediately rather than corrupting parallel-batch state silently. Document the read-only contract in `runtime/CLAUDE.md`'s "Reserved Shared Store Keys" entry: "`__pflow_cache_render__` is read-only across all consumers; never mutate the dict or its `CacheRenderContext` values."

**Save/restore:** mirror `engine.py:181–187` exactly — capture prior value via `.get()`, install always (even when the dict is empty), restore via write-back assignment (NOT `.pop()` — `NamespacedSharedStore` lacks `pop`). Sub-workflow children's engine.run() installs their own dict; parent's value is restored on exit.

**Restore-from-absent semantics.** When the parent never installed a value, `shared.get("__pflow_cache_render__")` returns `None`. The `finally` block must NOT write `None` back — consumers do `(shared.get("__pflow_cache_render__") or {}).get(node_id)` (the canonical defensive pattern), but a future code path that bypasses the engine install could leave a literal `None` value, hitting `None.get(...)` → `AttributeError`. **Choice in plan**: write a module-level `_EMPTY_CACHE_RENDER = MappingProxyType({})` constant on restore-from-absent (always install something dict-shaped). The save/restore block becomes:
```python
saved = shared.get("__pflow_cache_render__")
shared["__pflow_cache_render__"] = MappingProxyType(_build_cache_render_dict(workflow))
try:
    return self._run_inner(workflow, shared)
finally:
    shared["__pflow_cache_render__"] = saved if saved is not None else _EMPTY_CACHE_RENDER
```
Single try/finally mirrors the `__trace_collector__` precedent at `engine.py:181–187` exactly: if `_build_cache_render_dict` raises before the install line, `shared` is unchanged, the exception propagates, no restore needed. This contract is documented in `runtime/CLAUDE.md` alongside the reserved-key entry. The `__trace_collector__` precedent doesn't have the `None`-trap because trace consumers don't `.get()`-chain on the value.

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
- **Paid spikes run before plan execution, not inside the plan.** The agent-handoff documents three pre-authorized spikes (~$0.30 total) that inform decisions about Gemini cache_control, OpenAI parallel routing, and Anthropic per-TTL pricing. Run them, record outcomes in progress log §32+, then update this plan if any outcome contradicts an encoded decision. Spikes do not appear as phases in the plan itself.

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
  - **Why this is safe** (load-bearing): when `id is None` (legacy diagnostics, all today's code paths), `id or message` resolves to `message` — identical to today's `(severity, source, node_id, message)` tuple. New cache-namespaced diagnostics that set `id` use it as the dedup key (two diagnostics differing only in `message` enrichment but sharing `id` collapse correctly).

- `src/pflow/core/CLAUDE.md`:
  - **Update the load-bearing SSoT comment at line 103.** Today the comment reads: `Hash identity tuple: (severity, source, node_id, message) — keep it that way.` Replace with: `Hash identity tuple: (severity, source, node_id, id or message) — keep it that way. When id is None (legacy), falls back to message-keyed dedup, preserving sub-workflow warning dedup. When id is set (cache-namespaced diagnostics), id is the dedup key and message variants collapse.` Without this update, future contributors reading core/CLAUDE.md will revert the change.
  - Update `to_dict()` to emit `"id"` when set; omit when None (mirror existing `title is not None` pattern).
  - **Add three new category constants and `CATEGORY_TITLES` entries** (DD#27 + Files-to-Modify in spec):
    - `CACHE_FAILURE_CATEGORY = "cache_failure"` (typed-exception path; v1 emits via Diagnostic directly, no typed exception).
    - `CACHE_WARNING_CATEGORY = "cache_warning"` — analyzer-emitted; no `_FAILURE_CATEGORY_MAP` entry needed (handoff "5-place co-edit pattern" — only #2 and #3 apply for analytical categories).
    - `CACHE_ADVISORY_CATEGORY = "cache_advisory"` — same.
    - Add corresponding `CATEGORY_TITLES` entries: `"Cache Failure"`, `"Cache Warning"`, `"Cache Advisory"`.

- `src/pflow/execution/executor_service.py`:
  - **DO NOT add `_FAILURE_CATEGORY_MAP["cache_failure"]` in v1.** The map's dual-invariant pattern is for typed-exception-driven failures (mirroring `LLMCallError`). v1 emits all cache validation diagnostics directly via `Diagnostic` (no typed cache exception). Adding the entry now creates dead code that no producer reaches — violates "don't add features beyond what task requires." When/if v1.x introduces a typed `CacheRenderError` exception, that task adds the entry alongside the producer in one PR. For v1, the constant `CACHE_FAILURE_CATEGORY` exists in `core/diagnostic.py` (above) for forward-compatibility on the diagnostic side — but no `_FAILURE_CATEGORY_MAP` entry is required because no exception ever flows through the failure-context-mapping path.

- `src/pflow/core/diagnostic_render.py`:
  - Extend `_format_warning_or_info_diagnostic` with a category dispatch for `cache_warning` / `cache_advisory` / `cache_failure` that surfaces structured `context` data inline alongside `message`/`suggestions` — mirrors the existing `template_error` precedent (per spec "Diagnostic Extension" subsection). For v1, render: `id` (if present, prefix `[id]`), `message`, `suggestions[]`, then any `context.savings_pct` / `context.savings_usd` / `context.batch_size` / `context.prefix_tokens_estimated` / `context.target_file` lines if present (these are the keys the cache catalog actually emits — see warning-catalog tests in F1).

### Tests

- `tests/test_core/test_diagnostic_id_field.py` (new — Test Infrastructure list):
  - `id=None` (default) preserves legacy identity tuple (dedup matches old behavior).
  - `id="cache.x"` uses `id` in dedup; two diagnostics with same `id` but different `message` collapse.
  - `to_dict()` round-trip with and without `id`.
  - `cache_failure`, `cache_warning`, `cache_advisory` constants exist and appear in `CATEGORY_TITLES`.
  - `_FAILURE_CATEGORY_MAP["cache_failure"]` is **NOT present** in v1 (deferred until typed exception emits it). Test asserts the absence: `"cache_failure" not in _FAILURE_CATEGORY_MAP`.
  - **Sub-workflow dedup regression** (load-bearing per `core/CLAUDE.md:103` warning): two `Diagnostic`s constructed with identical `(severity, source, node_id, message)` and `id=None` (one from validation-time path, one from runtime path — common pattern for child-workflow warnings flowing through both paths) MUST hash and compare equal. Use `deduplicate_diagnostics([d1, d2])` and assert `len(...) == 1`. Catches the regression where someone adds `id` to the tuple unconditionally.

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
  - **Add per-node field extraction in `_build_node_dict` (lines 1393–1449).** Today the function extracts `type`, `batch`, and `cache` from `all_params` to top-level node keys (`markdown_parser.py:1411–1432`). Add parallel extraction for `prompt_cache` and `prewarm` AFTER the existing `cache` extraction at line 1432:
    ```python
    # Extract prompt_cache (goes to top-level, not params)
    if "prompt_cache" in all_params:
        node["prompt_cache"] = all_params.pop("prompt_cache")

    # Extract prewarm (goes to top-level, not params)
    if "prewarm" in all_params:
        node["prewarm"] = all_params.pop("prewarm")
    ```
    Without this, `prompt_cache:` and `prewarm:` declared on a node remain inside `node["params"]` and the per-node IR-schema `prompt_cache`/`prewarm` field check (B2.2) at top-level rejects every workflow that uses them. **Verify before patching**: re-read `_build_node_dict` at the line numbers above; confirm `cache` extraction is still at the same site.
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

### Save bundling integration test (`dependency_discovery` walker × cache chunks)

`pflow save` runs `dependency_discovery.discover_dependencies` (see `core/workflow/dependency_discovery.py`) which walks node params for file references and bundles them. Cache chunks contain `${var}` template references — NOT file paths — so the walker should ignore them. Verify with an integration test:

- `tests/test_integration/test_save_with_cache_block.py` (new): a workflow with `## Cache` referencing values + a node with `prompt: ./external.prompt.md` (a real file ref). Save the workflow. Assert: (a) cache block survives byte-for-byte, (b) `external.prompt.md` is bundled correctly, (c) no spurious file-not-found errors from the walker mistaking `${concept-brief.response}` for a file path. If the walker DOES treat cache chunks as file refs, a fix is required in `dependency_discovery` to skip the `cache.items[].var` and `cache.items[].prose_before` fields explicitly. **This test is the verification gate for the deferred phase-internal item "review-impact-completeness 15."**

## B2.2 — IR schema (with validation-reach gap closure)

### Files

- `src/pflow/core/ir_schema.py`:
  - Top-level `FLOW_IR_SCHEMA["properties"]["cache"]`: object with `ttl` (enum `["5m", "1h"]`, optional), `items` (array of objects, each with `name: string`, `var: string`, `prose_before: string`, optional `_source_line: integer`). `additionalProperties: False`.
  - Per-node properties (line 156–183): add `prompt_cache: {"type": "array", "items": {"type": "string"}}` and `prewarm: {"type": "boolean"}`. Per-node `additionalProperties: False` at line 186 means both must be added explicitly.
  - **`prompt_cache:` and `prewarm:` accepted on ALL node types at the schema level (additive properties).** They become semantically meaningful only on `type: llm` nodes — for non-LLM types (`shell`, `http`, `file`, `mcp`, `python`, `claude`, `workflow`), the schema accepts them but `_validate_cache_block` (B2.3) rejects them at runtime with a locked hint message.
  - **CRITICAL — validator step 8 cannot catch this** (corrects an earlier draft claim). Step 8 (`_validate_unknown_params` at `core/workflow/validator.py:559–638`) iterates `params = node.get("params", {})` at line 600 and `for param_key in params` at line 616. It only inspects keys inside `node["params"]`. **B2.1 extracts `prompt_cache:` and `prewarm:` to TOP-LEVEL node keys** (siblings of `type`, `cache`, `batch`), so step 8 never sees them. `WorkflowExecutor.ALLOWED_PARAMS` (verified at `workflow_executor.py:75`) is consulted only as the per-`type` known-key set inside the params loop — irrelevant once the keys are top-level. A `prompt_cache:` declared on a `type: shell` node would otherwise pass schema (additive) AND step 8 (invisible) and silently no-op at runtime. The B2.3 check below closes this gap.
  - The existing `cache: bool` field at line 180–183 remains unchanged.
  - Update `_get_suggestion` only if a new error path is introduced (e.g., misspelled `prompt_cache` → suggest correct field). Otherwise leave alone.

- **Validation-reach decision** (V5 fix per Round 4 — single source of truth for shape):
  - **The plan's earlier draft assumed `FLOW_IR_SCHEMA` runs at every entry point. It does not.** `WorkflowValidator._validate_structure` (step 1) calls `validate_ir` (full schema). `runtime/compilation/compile_validation.py::_prepare_compilation` calls `validate_ir_structure` from `runtime/compilation/ir_preparation.py:231` (minimal — only checks nodes/edges arrays). A workflow loaded directly via the compiler bypassing the Runner has structural cache shape unchecked at the schema layer.
  - **Decision (Round 4)**: schema is the **single source of truth for shape**. `_validate_cache_block` (B2.3) does ONLY semantics — cross-references, ordering, batch-scoped rejection, non-LLM-type rejection. NOT structural shape (ttl enum, prompt_cache list-of-strings, prewarm bool). Top-10% pattern (mypy/ruff/rustc): one rule per error condition, not belt-and-suspenders.
  - **Compile-path defense**: when `_validate_cache_block` runs on the compile path (where minimal `validate_ir_structure` did NOT check shape), defensive `isinstance` guards skip nodes with malformed `prompt_cache` / `prewarm` shape, emitting `logger.warning("cache validation skipped node %s: malformed prompt_cache shape (%s)", node_id, type(value).__name__)` so the degradation is visible in `--verbose` mode. The deeper compile-time error (NodeConfig construction failure on the malformed value) surfaces normally — `_validate_cache_block` does NOT emit a Diagnostic for shape errors; that's the schema's job.
  - **Document in `validate_ir_structure`**: add a one-line comment that this path skips full schema validation and structural shape errors will surface at compile time, NOT validation time. Future contributors should not add ad-hoc shape checks here.
  - **Net effect**: validator path emits ONE schema diagnostic for shape errors (step 1 short-circuits). Compile path either skips silently with logger.warning (graceful) OR fails downstream at NodeConfig construction with a clear error. No double-emission case to test; no dedup required.

### Tests

- Extend `tests/test_core/test_ir_schema.py` (or add adjacent file):
  - Valid IR with `cache` block + per-node `prompt_cache: [a, b]` + `prewarm: true` passes.
  - `prompt_cache` of wrong shape (non-list, list of non-strings) is rejected at the schema level.
  - Per-node `prompt_cahe` (typo) is rejected with `additionalProperties: False`.
  - Top-level `cahe` (typo) is rejected.
  - `cache: false` (existing memo opt-out) and `prompt_cache: [...]` (new) coexist on one node.
  - **`prompt_cache:` on a `type: workflow` node**: schema passes (additive field); `_validate_cache_block` (B2.3) rejects with `id="cache.invalid-on-non-llm"`, severity ERROR, message containing the locked hint string. Test asserts both the catalog ID and the hint string. Parametrize over node types `["shell", "http", "file", "mcp", "python", "claude", "workflow"]` — each must reject. `type: llm` accepts.
  - **Three-state at IR-shape level**: parsing absent vs `prompt_cache: []` vs `prompt_cache: [chunk]` produces three distinct IR shapes (key absent vs `[]` vs non-empty list). Confirms the parser doesn't normalize between them.

## B2.3 — Cache reference validation in `data_flow.py`

### Files

- `src/pflow/core/workflow/data_flow.py`:
  - Add a new function `_validate_cache_block(workflow_ir, diagnostics)` called from inside `validate_data_flow` after the existing per-node template-reference validation loop. Cases (each emits a `Diagnostic` with `source="validator"`, `id="cache.<id>"` per spec catalog):
    - Each `${var}` in `## Cache` chunks resolves to a workflow input or upstream step output (use the same valid_simple_refs / nodes_by_id sets the existing template validator builds — reuse the existing `_validate_template_reference` path). Resolution failure → ERROR (no separate `cache.*` ID; flows through existing template-validation diagnostic machinery).
    - Batch-scoped reference rejection: if a chunk's `${var}` root resolves to a batch alias (any value in `batch_item_aliases`, computed at line 311–318), emit ERROR with a clear message per spec: "References that vary across calls referencing the same chunk are rejected. `${item.X}` and any descendants are batch-scoped and not valid in `## Cache`." (No catalog ID — flows as a generic validation error.)
    - Per-node `prompt_cache: [...]` references that don't appear in `## Cache.items` → ERROR with `find_similar_items`-driven "Did you mean?" suggestions.
    - Per-node `prompt_cache: [a, c, b]` doesn't match `## Cache` declaration order → ERROR with `id="cache.order-mismatch"`. Message must match the format in spec's "Strict Order Validation" section verbatim (declared / you wrote / fix).
    - **Per-node `prompt_cache:` or `prewarm:` declared on a non-LLM node** (any `type` other than `"llm"`) → ONE ERROR per offending node (NOT per offending field — see V6 fix in F1 catalog) with `id="cache.invalid-on-non-llm"`. This is the load-bearing check for the validator-step-8 reach gap (see B2.2). Walk every node in `workflow_ir["nodes"]`; for each non-LLM node, compute `invalid_fields = [k for k in ("prompt_cache", "prewarm") if k in node]`. If non-empty, emit ONE Diagnostic via `make_diagnostic("cache.invalid-on-non-llm", ...)` with `invalid_fields`, `invalid_fields_csv`, `is_or_are`, `plural_s` populated per F1 catalog spec. **Skip nodes with missing/empty `type`** — those are structural errors caught upstream (schema requires `type` per `ir_schema.py:185`); skipping them here avoids rendering "type: " or "type: None" in the cache diagnostic. The new ID `cache.invalid-on-non-llm` is added to the F1 catalog as an 11th entry (severity: ERROR, source: validator, category: cache_failure).
    - **Skip semantic checks on shape-malformed nodes** (V5 defense — Round 4 high-value fix #4 enumerates the guards explicitly so the implementer doesn't have to derive them):
      ```python
      # At the top of the per-node loop in _validate_cache_block, BEFORE any
      # semantic check that assumes well-formed shape:
      prompt_cache_val = node.get("prompt_cache")
      if prompt_cache_val is not None and (
          not isinstance(prompt_cache_val, list)
          or not all(isinstance(item, str) for item in prompt_cache_val)
      ):
          logger.warning(
              "cache validation skipped node %s: malformed prompt_cache shape (%s); "
              "schema-validator path catches this at step 1; compile path catches at NodeConfig construction",
              node["id"],
              type(prompt_cache_val).__name__,
          )
          continue  # to next node — no Diagnostic emitted from _validate_cache_block

      prewarm_val = node.get("prewarm")
      if prewarm_val is not None and not isinstance(prewarm_val, bool):
          logger.warning(
              "cache validation skipped node %s: malformed prewarm shape (%s); "
              "schema-validator path catches this at step 1; compile path catches at NodeConfig construction",
              node["id"],
              type(prewarm_val).__name__,
          )
          continue
      ```
      **Top-level cache block defense (similar)**: when `workflow_ir.get("cache")` is present but malformed (not a dict, missing `items`, `items` not a list of dicts, `ttl` not in `{"5m", "1h"}` or missing), emit `logger.warning` and skip ALL `_validate_cache_block` checks for the run — return early. Schema catches the shape; the helper just defends against running on it. Test asserts: a workflow with `cache: 5` (wrong type) loaded directly via `compile_workflow(ir_dict)` produces ZERO `cache.*` Diagnostics from `_validate_cache_block` and exactly ONE `logger.warning` (verify via `caplog`); the deeper compile failure surfaces normally. **Note**: `bool` is a subclass of `int` in Python; `isinstance(True, int)` is True. Use `isinstance(x, bool)` (NOT `isinstance(x, (int, bool))`) to reject `prewarm: 1` as malformed — the schema will catch the bare-int case.
    - Unused `## Cache` chunk (declared but no node references it) → WARNING with `id="cache.unused-chunk"`.
  - The function operates purely on the IR — no template resolution, no token counting, no I/O. Stays fast and deterministic per DD#36.

- `src/pflow/core/workflow/validator.py`:
  - The 10-step pipeline already calls `validate_data_flow` (per workflow/CLAUDE.md). No new step is needed — the cache validation is part of step 4 by virtue of living inside `validate_data_flow`. Update the validator's CLAUDE.md to note "step 4 also validates `## Cache` blocks and per-node `prompt_cache`/`prewarm` references via shared `data_flow._validate_cache_block`."
  - Confirm the compile-time path (`runtime/compilation/compile_validation.py::_prepare_compilation`) also reaches `validate_data_flow` — per DD#20 it does. No code change needed there if so; if not, the implementing agent surfaces this.

- **MCP entry point reach** (review-feature-interactions C5 — Task 72 historical pattern):
  - Verify `mcp_server/services/execution_service.py::execute_workflow` (line 195) and `run_registry_node` (line 500) reach the same `validate_data_flow` path before execution. Both go through `WorkflowRunner().run()` (verified by reading execution_service.py — both delegate to `WorkflowRunner`), so they reach `WorkflowValidator.validate()` at `runner.py:336/457`. **Verification step**: add a test in `tests/test_mcp_server/` that invokes `execute_workflow` on a workflow with `cache.order-mismatch` and asserts the same diagnostic structure as the CLI invocation. Catches the regression where MCP path bypasses validation.

### Tests

- `tests/test_core/test_prompt_cache_validation.py` (new):
  - `prompt_cache: [c, b]` when `## Cache` declares `[a, b, c]` → `cache.order-mismatch` ERROR with the **exact** message format. Assert byte-equality of the rendered message against spec's "Strict Order Validation" example block (the three lines `declared:`, `you wrote:`, `fix:` with exact indentation/labels). This is the agent-facing contract for order errors.
  - `prompt_cache: [unknown]` → resolution ERROR with `similar_names` populated.
  - **`prompt_cache: [chunk]` on a non-LLM node** → ONE ERROR `cache.invalid-on-non-llm` with `context["invalid_fields"] == ["prompt_cache"]` and message containing the locked hint string. Filter the diagnostics list by `id == "cache.invalid-on-non-llm"` (do NOT assert "any error" — there may be unrelated structural errors on the test fixture; the assertion is "the cache.invalid-on-non-llm diagnostic IS in the list").
  - **Both `prompt_cache: [chunk]` AND `prewarm: true` on a non-LLM node** (V6 combined-diagnostic test): ONE ERROR with `context["invalid_fields"] == ["prompt_cache", "prewarm"]`; message contains both field names CSV-formatted; suggestions list contains "Remove the invalid declarations (prompt_cache, prewarm) from {node_id}, OR move the LLM logic into a type: llm node." `prewarm: true` alone (without `prompt_cache:`) → `context["invalid_fields"] == ["prewarm"]`. **Locks the V6 fix**: emission is one-per-node, not one-per-field.
  - **Parametrize fixture-shape per node type**: each non-LLM type has different required params (`shell` requires `command:`; `http` requires `url:`; `file` requires `path:`+`mode:`; `mcp` requires `__mcp_server__`+`__mcp_tool__`; `python` requires `code:`; `claude` requires `prompt:`; `workflow` requires `workflow:`). Parametrize `[("shell", {"command": "echo X"}), ("http", {"url": "https://x"}), ...]` so each fixture is structurally valid except for the cache-invalidity. Without minimal-valid params, the validator may reject for missing-required BEFORE reaching the cache check, and the test passes for the wrong reason. Filter assertions check `cache.invalid-on-non-llm` is IN the diagnostics list, not "is the only error."
  - **`type: llm` positive control row**: parametrize includes `("llm", {"prompt": "X", "model": "claude-sonnet-4-5"})` and asserts NO `cache.invalid-on-non-llm` diagnostic for `prompt_cache: [chunk]` on it. Without the positive control, the test could pass even if the rule rejects every type.
  - **Missing/empty `type` field**: parametrize includes `(None, {})` (no `type` key) — assert NO `cache.invalid-on-non-llm` diagnostic fires (the rule correctly skips); the structural error from schema-required `type` surfaces separately. Locks the "render `None` in cache message" defense.
  - **Shape-malformed `prompt_cache` (not a list of strings)**: a fixture with `prompt_cache: 5` on a `type: llm` node. The validator path produces ONE schema-emitted diagnostic (step 1, short-circuits steps 2-10). The compile path (bypassing `WorkflowValidator`, calling `compile_workflow(ir_dict)` directly) produces ZERO diagnostics from `_validate_cache_block` (defensive skip with `logger.warning` — verify via `caplog`); the compile fails downstream at NodeConfig construction with a different error. **Locks the V5 fix**: shape errors are schema-only, no double-emit.
  - `${item.X}` in cache chunk → batch-scoped rejection ERROR.
  - Unused chunk → `cache.unused-chunk` WARNING.
  - `prompt_cache: []` (empty) and `prompt_cache:` (absent) both treated as "no declared cache" — no ERROR.
  - Sub-workflow with `## Cache` validates independently (each file's cache block is scoped to its own inputs and step outputs per DD#12 — covered by the recursive validator path in `_validate_sub_workflows`). Run as both top-level workflow AND parent-invoked sub-workflow; assert same diagnostics fire in both.
  - **Save-path validation reach** (review-validation-consistency W2): saving a workflow with `cache.order-mismatch` via `WorkflowManager.save()` raises `WorkflowValidationError` with the catalog id `cache.order-mismatch`. Locks the contract that `pflow save` runs full validation including cache checks (verified `save_service.py:107-156`).
  - **Structural shape via compile path** (review-validation-consistency W3): bypass `WorkflowValidator` and call `compile_workflow` directly with a malformed cache IR (e.g., `cache.items: "string"` — wrong type). Assert `_validate_cache_block` catches it (the compile path uses minimal `validate_ir_structure`, not full schema, so the `_validate_cache_block` shape check is the only line of defense).
  - **(REMOVED in Round 4)**: the prior "Schema vs `_validate_cache_block` redundancy dedup" test was based on a misanalysis. With V5 fix (schema-only for shape; `_validate_cache_block` does only semantics + defensive skip), there is no double-emit case to verify. The "Shape-malformed `prompt_cache`" test above is the replacement — asserts schema fires alone on the validator path, and `_validate_cache_block` defensively skips on the compile path.

### Hedged-claim verification

`WorkflowExecutor._compiled_workflow_cache` interaction with sub-workflow `## Cache`: per `runtime/CLAUDE.md` the compile cache is keyed by resolved workflow path and stores the compiled IR (which includes the `cache` field, now a frozen `CacheBlockIR` per B3.1). Two sequential invocations of the same sub-workflow file therefore reuse the same compiled `cache_block` — correct, and frozen so safe.

**Verification test (parallel + heterogeneous batch — load-bearing for the architectural backbone):** in `tests/test_runtime/test_subworkflow_cache_concurrency.py` (new), add a test that spawns a heterogeneous batch parent (`${item.workflow}` varying — production shape verified by `workflow_executor.py:212–215`) where two batch items dispatch the same sub-workflow file with DIFFERENT parent state per item, in parallel mode.

**Concrete test mechanism** (replaces the vague "instrument by recording build site"):
1. **Capture per-thread `cache_block` identity**: monkeypatch `_build_cache_render_dict` (via `monkeypatch.setattr`) to wrap the original implementation. The wrapper appends `(threading.get_ident(), id(workflow.cache_block))` to a shared `list[tuple[int, int]]` BEFORE returning the dict. `list.append` is atomic in CPython, so concurrent appends are safe without explicit locking. After batch completion, assert: (a) the list has ≥ 2 entries; (b) the thread idents differ (proving the calls came from different worker threads); (c) the `id(cache_block)` values are EQUAL (proving the compile cache returned the same frozen object — frozen-shared-by-reference is correct).
2. **Capture per-invocation rendered content**: monkeypatch `LLMNode.prep`'s `system_blocks` builder (via spy on `_resolve_chunk_value` or by reading `MockLLMClient.call_history_full`). After batch completion, assert each item's rendered content reflects its OWN parent state (different across items), even though both items share the same compiled IR.
3. **Assert frozen invariant**: `CompiledWorkflow.cache_block` returned from `_compiled_workflow_cache` for both items must be the same frozen object. `dataclasses.replace(workflow.cache_block, ttl="1h")` works (returns a NEW instance); direct mutation `workflow.cache_block.ttl = "1h"` raises `FrozenInstanceError`. Both assertions on the captured object.
4. **Parent state preservation across batch**: capture `id(shared["__pflow_cache_render__"])` BEFORE the batch dispatches and AFTER the batch completes. The id may change (restore-from-absent writes `_EMPTY_CACHE_RENDER`), but the value must be a `MappingProxyType` over a dict (not `None`, not a corrupted reference).

Sequential-only verification is insufficient — the whole point of the `CacheBlockIR` freeze (B3.1) is parallel-batch safety. If this test fails, the fix is structural and must be surfaced to the user.

### Open user decision required before B2.3 ships

**Cache rendering errors in batch + sub-workflow + `error_handling: continue`** (review-feature-interactions C2): when a chunk's `${var}` fails to resolve at runtime inside a parallel-batch sub-workflow item with `error_handling: continue`, what error category fires? Two routes:

- **(Recommended, current plan):** route through `template_error` via the existing `build_template_error_diagnostic` pattern. Consistent with existing template-resolution failure semantics; `cache_failure` category is forward-looking (no producer in v1 per High-Priority #11 deferral).
- **Alternative:** introduce typed `CacheRenderError` exception now and emit `cache_failure` category. Pulls `_FAILURE_CATEGORY_MAP["cache_failure"]` back in.

**Resolved (per orchestrator decision):** stay with `template_error`. Document this in C1.2's rendering-failure path. Defer typed `CacheRenderError` to v1.x with the corresponding `_FAILURE_CATEGORY_MAP` entry. If the user prefers the alternative, surface here before B2.3 patches land — it changes B1.1 + B2.3 + C1.2 in three coordinated places.

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

Add `scripts/generate_config_hash_baseline.py` (NEW — minimal, can be deleted after baseline lands). It loads workflows covering ALL the hash-affecting shapes (per review-test-fidelity #1 — without these, the regression gate is incomplete) and writes `compute_config_hash` for every node to `tests/test_runtime/fixtures/golden_config_hashes.json`.

**Mandatory shape coverage** (each shape needs ≥1 representative workflow):
- **Plain LLM node** (no cache, no batch, no special features) — baseline.
- **`cache: false`** — all 7 example workflows using this field, parameterized.
- **Branching** (post-DD#38 `## Outputs` coalesce semantics) — at least one workflow with `next:` routing tables.
- **Batch processing** (Task 96) — both `parallel: true` and `parallel: false` shapes, with `error_handling: fail_fast` and `continue` variants.
- **Sub-workflow nodes** (`type: workflow`) — these aren't LLMNode but live in `node_configs`; verify they're unaffected by the cache filter.
- **Structured output** (`output_schema` injecting `tools`) — Task 66 contract.
- **Attachments** — file/binary attachments on LLM nodes.
- **Retry config** — non-default `max_retries` / `wait_seconds` (these ARE in `compute_node_config`).
- **Reasoning** — an LLM node with `- reasoning_effort:` / `- reasoning_max_tokens:` declared in YAML (these flow through `static_params` into the hash; per Task 158 reasoning translation map). Coverage means YAML-declared, not request-time-injected.

**Baseline cannot include post-task fields.** The pre-merge fixture is generated against `main` HEAD which doesn't parse `prompt_cache:` / `prewarm:` / `## Cache` — those would fail markdown-parser validation today. The baseline therefore captures the BARE shapes (no cache fields). The DD#19 byte-identity invariant — `prompt_cache: []` ≡ absent — is verified POST-patch in B3.4 by:
1. Loading a workflow from the baseline fixture that has NO `prompt_cache:` and recording its hash X (already covered by the baseline-fixture comparison).
2. Mutating the same workflow IN-MEMORY to add `prompt_cache: []` to one node (without changing anything else), recompiling, and asserting the new hash equals X.
3. Mutating a similar workflow to add `prompt_cache: [chunk]` + a sibling `## Cache`, recompiling, and asserting the new hash differs from X.
This three-state test is in B3.4 and runs every CI build (not pre-merge). The baseline gate catches "absent → drifted" regressions; the in-memory mutation test catches "absent → []" drift. Together they close the three-state invariant.

The script enumerates which workflows it loaded and which shape each covers in a `# Coverage:` header in the JSON. Implementing agent verifies this header before committing.

**MERGE GATE — non-negotiable:** B3.1 patches MUST NOT begin until `tests/test_runtime/fixtures/golden_config_hashes.json` is committed against `main` head. Generated post-patch = tautology = silent stale cache risk. Recommended PR sequence:
1. PR #1: `scripts/generate_config_hash_baseline.py` only.
2. Run script on `main`. Commit the resulting fixture (PR #1 also).
3. PR #2 onward: B3.1 → B3.2 → B3.3 → B3.4 patches.

Document this gate in B3 merge-gate section below as the FIRST checkpoint.

## B3.1 — Schema additions to runtime types

### Files

- `src/pflow/runtime/engine/types.py`:
  - Add `CacheRenderContext` dataclass per the "Architectural backbone" section above.
  - Extend `NodeConfig`:
    - `prompt_cache_items: tuple[str, ...] = ()` — the bare names declared on the node. **Tuple, not list**, so the value is hashable and the dataclass stays clean. Empty tuple = no opt-in (DD#19 + spec edge case).
    - `prewarm: bool = False`.
  - Extend `CompiledWorkflow`:
    - `cache_block: CacheBlockIR | None = None` — the workflow-level `## Cache` IR (frozen dataclass per the architectural backbone). NOT `dict[str, Any]`. Mutability would defeat the parallel-batch safety guarantee — see backbone section.

- `src/pflow/runtime/compilation/...` (compiler):
  - Find the `NodeConfig` factory (search for `cache_enabled` field assignment — likely `compilation/compiler.py`). Extract `node.get("prompt_cache", [])` → `tuple(...)` into `NodeConfig.prompt_cache_items`. Extract `node.get("prewarm", False)` into `NodeConfig.prewarm`.
  - Find `CompiledWorkflow` assembly site. Build `CacheBlockIR` from `workflow_ir.get("cache")` if present:
    ```python
    cache_ir = workflow_ir.get("cache")
    if cache_ir is not None:
        cache_block = CacheBlockIR(
            ttl=cache_ir.get("ttl"),
            items=tuple(
                CacheChunkIR(
                    name=item["name"],
                    var_expr=item["var"],
                    prose_before=item["prose_before"],
                    source_line=item.get("_source_line", 0),
                )
                for item in cache_ir.get("items", [])
            ),
            source_line=cache_ir.get("_source_line", 0),
        )
    else:
        cache_block = None
    ```
    Pass to `CompiledWorkflow(... , cache_block=cache_block)`. The conversion happens once at compile time; subsequent reads from the compile cache see the same frozen object.
  - **Verification**: existing `cache: bool` extraction still produces the same `NodeConfig.cache_enabled`. Run all `tests/test_runtime/test_compiler*` tests. Add a test that mutating any field on a returned `CacheBlockIR` raises `dataclasses.FrozenInstanceError`.

## B3.2 — `CacheRenderContext` build + install at engine boundary

### Files

- `src/pflow/runtime/engine/engine.py`:
  - Add a module-level helper `_build_cache_render_dict(workflow: CompiledWorkflow) -> dict[str, CacheRenderContext]`:
    - Iterate `workflow.node_configs`. For each LLMNode (`config.node_type_name == "LLMNode"`), build a `CacheRenderContext` if any of `(config.prompt_cache_items, config.prewarm, workflow.cache_block)` is set (i.e. at least one cache-related declaration exists for this node or workflow).
    - `cache_block` = `workflow.cache_block` (already a frozen `CacheBlockIR | None` from B3.1).
    - `subset` = `config.prompt_cache_items`.
    - `prewarm` = `config.prewarm`.
    - `unresolved_batch_prompt` = `config.template_config.template_params.get("prompt")` only when `config.batch_config and config.template_config`; else `None`.
    - `batch_alias` = `config.batch_config.item_alias` when batch; else `None`.
  - In `WorkflowEngine.run()` body (the section currently doing trace-collector save/restore at lines 181–187): add the same shape for `__pflow_cache_render__`. Mirror `__trace_collector__` exactly — single try/finally; if `_build_cache_render_dict` raises before the install line, `shared` is unchanged and the exception propagates cleanly (no restore needed because nothing was modified). Wrap the install in `MappingProxyType` for read-only enforcement. Restore writes the module-level `_EMPTY_CACHE_RENDER` constant (proxy-wrapped empty dict) when the parent had no value, NOT `None` (per "Restore-from-absent semantics" in the backbone section).

    **`_EMPTY_CACHE_RENDER` placement**: defined as a module-level constant in `src/pflow/runtime/engine/engine.py` next to the `WorkflowEngine` class — the only consumer. NOT in `engine/types.py` (no second consumer to justify it; YAGNI). Tests that need to reference the constant import directly: `from pflow.runtime.engine.engine import _EMPTY_CACHE_RENDER`. The leading underscore signals "module-internal" — production callers never need to import it; the consumer pattern `(shared.get("__pflow_cache_render__") or {}).get(node_id)` works whether the value is `_EMPTY_CACHE_RENDER` or any other empty Mapping.
    ```python
    # Module-level constant — avoids per-restore allocation:
    _EMPTY_CACHE_RENDER: Mapping[str, CacheRenderContext] = MappingProxyType({})

    # Inside WorkflowEngine.run(), mirroring engine.py:181–187 trace-collector pattern:
    saved_cache_render = shared.get("__pflow_cache_render__")
    shared["__pflow_cache_render__"] = MappingProxyType(_build_cache_render_dict(workflow))
    try:
        return self._run_inner(workflow, shared)
    finally:
        shared["__pflow_cache_render__"] = saved_cache_render if saved_cache_render is not None else _EMPTY_CACHE_RENDER
    ```
    **Always install (never gated on truthiness).** Sub-workflow children must mask the parent's value even if the child has no cache declarations — otherwise a parent's cache_block leaks into a child without one. Per `engine.py:173–180` documentation: write-back assignment, not `.pop()`, because `shared` may be a `NamespacedSharedStore`. Hoisting `_EMPTY_CACHE_RENDER` to module level eliminates per-restore allocation in deeply-nested sub-workflow runs.

  - **Consumer pattern (canonical):** all consumers read with the `or {}` defensive pattern:
    ```python
    cache_ctx = (shared.get("__pflow_cache_render__") or {}).get(node_id)
    ```
    The `or {}` defends against any code path where the value is `None` (legacy/test instantiations that bypass `_build_cache_render_dict`). Document this in `runtime/CLAUDE.md`. Consumer sites: `plan_node._render_cache_for_hash` (B3.3), `LLMNode.prep` (C1.2), `batch_executor._execute_parallel` (D.2). Apply this pattern at all three.

- `src/pflow/runtime/CLAUDE.md`:
  - Add `__pflow_cache_render__` to the "Reserved Shared Store Keys" canonical reference. Document:
    - **Value shape**: `MappingProxyType[node_id_str, CacheRenderContext]` (read-only proxy over a dict; consumers see the runtime type as `Mapping`, not `dict`).
    - **Lifecycle**: engine-installed at `WorkflowEngine.run()` entry, save/restore via single try/finally (mirroring `__trace_collector__`), restore-from-absent writes the module-level `_EMPTY_CACHE_RENDER` constant (`MappingProxyType({})`, NOT `None`) so consumers can `.get("...") or {}` safely.
    - **Read sites**: `plan_node._render_cache_for_hash` (B3.3), `LLMNode.prep` (C1.2), `batch_executor._execute_parallel` (D.2). All use `(shared.get("__pflow_cache_render__") or {}).get(node_id)`.
    - **Read-only invariant**: NEVER mutate the proxy or the `CacheRenderContext` values. `MappingProxyType` raises `TypeError` on mutation. The frozen dataclass values are mutation-proof by `dataclass(frozen=True)`.
    - **NOT in `_PROPAGATED_KEYS`**: each `engine.run()` builds its own per-workflow dict; sub-workflow children mask the parent's value via the save/restore semantics. Adding to `_PROPAGATED_KEYS` would leak parent cache_render dicts into children.
    - **`storage_mode: shared` × `## Cache` interaction (LIMITATION)**: a sub-workflow with `storage_mode: shared` writes directly to the parent's root store (per `NamespacedSharedStore.__setitem__` at `namespaced_store.py:51` — `__*__` keys bypass the namespace). Two parallel batch items each running a `storage_mode: shared` sub-workflow that has its own `## Cache` block both invoke `engine.run()`'s save/restore on the same parent root, and the restore order across worker threads is non-deterministic (last-finished worker's restore wins). The result is functionally correct (each child reads its own installed value during execution) but the parent's value AFTER the batch is whichever child restored last. **For v1**: document this as an unsupported combination. The cache_render value is per-workflow scope, NOT meant to leak across `storage_mode: shared` boundaries. If a future need arises, the fix is either (a) make the cache_render save/restore use a worker-local key suffix, or (b) refuse the combination at validation time. Neither is needed for v1's motivating workload (lyrics-generator does not use `storage_mode: shared`).

## B3.3 — Plan_node renders cache content and includes it in the hash

### Files

- `src/pflow/runtime/engine/plan_node.py`:
  - **Reorder**: move template resolution BEFORE config-hash computation. New shape:
    1. If `config.template_config and not config.batch_config`: call `resolve_templates(...)` for non-batch nodes (existing behavior, just moved earlier in the function).
    2. Read `cache_ctx = (shared.get("__pflow_cache_render__") or {}).get(config.node_id)` (canonical defensive pattern per B3.2 — `or {}` handles the legacy/test path where the value may be `None`).
    3. If `cache_ctx is not None and cache_ctx.subset`: render `prompt_cache_content` via the new helper `_render_cache_for_hash(cache_ctx, resolved_params, shared)`. The helper:
       - Walks `cache_ctx.cache_block.items` (frozen tuple of `CacheChunkIR`) filtered to `cache_ctx.subset`, in declaration order.
       - For each chunk: resolves `${var}` using `TemplateResolver.extract_root_node_id` + a lookup against `shared` (NOT `resolved_params` alone — for batch nodes, `resolved_params` is `None`; the cache references are validated as non-batch in B2.3 and so resolve from `shared` directly).
       - Returns `[{"name": chunk_name, "prose": prose_before, "value": serialized_value}, ...]` where `serialized_value` uses the deterministic helper (B3 stub: `json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)`; G.1 replaces with the canonical helper).
    4. Pass `prompt_cache_content` to `compute_node_config(...)` (new keyword-only argument; see B3.4).
    5. Compute `config_hash` from the resulting config.
    6. Continue with memo-cache lookup and in-process-cache lookup as today.
  - **Strict-mode template-error path**: if `resolve_templates` raises `ValueError`, the existing early-return at lines 57–68 still fires. The cache content is not rendered (correct — there's nothing to hash for; the `template_exception` branch returns).
  - **Empty subset**: when `cache_ctx is None` OR `cache_ctx.subset` is empty, `prompt_cache_content` is `None` and `compute_node_config`'s conditional include doesn't fire. Hash byte-identical to pre-task. This is the load-bearing DD#19 path.
  - **Hash-vs-prep render divergence invariant** (load-bearing): the `_render_cache_for_hash` helper called from `plan_node` and the `_render_cache_for_messages` helper called from `LLMNode.prep` (C1.2) MUST produce content that is byte-equivalent at the level of "value bytes substituted in for `${var}`." If the two diverge — e.g., `plan_node` resolves `${concept}` to value `V` at hash time but `LLMNode.prep` resolves it to `V'` at prep time — the memo cache is keyed on `V` but the adapter sends `V'`, producing silent stale-cache hits on the next run with `V` again. **Both helpers MUST use the same resolution function** (`TemplateResolver.resolve_template` against `shared`) and the same deterministic-serialization helper. Refactor: extract a single `_resolve_chunk_value(chunk, shared) -> str | _ChunkAbsentSentinel` helper that both call sites use; never duplicate the resolution logic.
  - **Branch-absent symmetry (CRITICAL — silent-stale-cache class)**: the shared helper handles ABSENT chunks identically for both call sites by returning a sentinel. Without this, plan_node could include a chunk's stringified `None` value in the hash while LLMNode.prep skips the chunk entirely (per C1.2), producing different cache_keys for what is logically the same render — silent stale-cache. Concrete shape (verified against actual code shapes — see footnote below):
    ```python
    from typing import Final
    from pflow.runtime.node_state import NodeStatus, get_node_status
    from pflow.runtime.template_resolver import TemplateResolver

    # Module-level sentinel — distinct from any string a real value could serialize to.
    # __repr__/__str__ raise TypeError so accidental serialization fails LOUD instead of
    # silently injecting a memory-address-flavored string into the hash (defense against
    # caller forgetting to filter — see "Both call sites MUST filter" below).
    class _ChunkAbsentSentinel:
        __slots__ = ()
        def __repr__(self) -> str:
            raise TypeError("_CHUNK_ABSENT must be filtered before serialization — caller forgot to drop ABSENT entries")
        def __str__(self) -> str:
            raise TypeError("_CHUNK_ABSENT must be filtered before serialization — caller forgot to drop ABSENT entries")
    _CHUNK_ABSENT: Final = _ChunkAbsentSentinel()

    def _resolve_chunk_value(chunk: CacheChunkIR, shared: SharedStore) -> str | _ChunkAbsentSentinel:
        # extract_root_node_id always returns str (verified template_resolver.py:212);
        # no None guard needed.
        upstream_node = TemplateResolver.extract_root_node_id(chunk.var_expr)
        if get_node_status(shared, upstream_node) == NodeStatus.ABSENT:
            return _CHUNK_ABSENT
        # TemplateResolver.resolve_template raises ValueError on strict-mode failure
        # (verified plan_node.py:57 catches `except ValueError`). Do NOT catch here —
        # the caller decides how to surface: plan_node returns NodePlan(status="miss",
        # template_exception=exc) per existing line 57-68; LLMNode.prep wraps via
        # build_template_error_diagnostic at the prep boundary.
        resolved = TemplateResolver.resolve_template(chunk.var_expr, shared)
        return _deterministic_serialize(resolved)
    ```
    **Verified against actual code (Round 4)**: `TemplateResolutionError` does NOT exist in pflow — `TemplateResolver.resolve_template` raises plain `ValueError` (with `_pflow_partial_resolutions` and `_pflow_template_diagnostic` annotations attached for downstream rendering). `NodeStatus.ABSENT` is the canonical symbol (NOT `node_state.ABSENT`). `extract_root_node_id` always returns `str`, never `None`. The pseudo-code above reflects these actual signatures.

    **Companion helper for static-prefix resolution (D.1) — locks byte-identical bytes across ALL cache paths** (Round 4 high-value fix #1):
    ```python
    import re

    # The TEMPLATE_VAR_PATTERN regex must match TemplateResolver's internal pattern
    # exactly (per runtime/CLAUDE.md):
    #   r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:(?:\[[\d]+\])?(?:\.[a-zA-Z_][\w-]*(?:\[[\d]+\])?)*)?)\}"
    # Import or re-derive at the call site; do NOT duplicate the literal.

    def _resolve_static_prefix_for_cache(template_str: str, shared: SharedStore) -> str:
        """Resolve every ${var} reference in template_str using the SAME deterministic
        serialization that _resolve_chunk_value uses for chunk values.

        Why this differs from `TemplateResolver.resolve_template(template_str, shared)`:
        TemplateResolver substitutes via Python's default `str(value)` for embedded
        refs in complex templates (per runtime/CLAUDE.md "Type behavior: complex
        templates always string"). For dict/list values, `str(value)` produces
        Python repr (`{'key': 'value'}`), NOT canonical JSON. A chunk's value
        and the same value embedded in a static prefix would then produce
        different bytes — silent cross-mode cache miss.

        This helper substitutes per-ref via _deterministic_serialize so the bytes
        match _resolve_chunk_value byte-for-byte for the same logical value.
        ABSENT upstream → leaves the ref unresolved (matches existing
        TemplateResolver permissive behavior; the static-prefix-with-ABSENT case
        means the auto-batch cache prefix is non-deterministic across runs and
        will not cache; this is fine — the analyst tier surfaces it as
        cache.dynamic-before-static or cache.discrepancy depending on the path).
        Strict-mode failures raise ValueError per TemplateResolver convention.
        """
        def _replace_one(match: re.Match) -> str:
            var_expr = match.group(1)
            upstream_node = TemplateResolver.extract_root_node_id(var_expr)
            if get_node_status(shared, upstream_node) == NodeStatus.ABSENT:
                return match.group(0)  # leave ${var} unresolved; runtime emits the ref literally
            resolved = TemplateResolver.resolve_template(var_expr, shared)
            return _deterministic_serialize(resolved)
        return TEMPLATE_VAR_PATTERN.sub(_replace_one, template_str)
    ```

    **Both helpers MUST share `_deterministic_serialize`** — the load-bearing invariant. `_resolve_chunk_value` and `_resolve_static_prefix_for_cache` are the two call sites; D.1 (static prefix), B3.3 (chunk hash), C1.2 (chunk message), F2 `analyze.py` (predicted cache_key) all route through one or the other. NEVER inline `str(value)` or `json.dumps(value)` at any cache-rendering site — that's the regression class this fix prevents.

    **Test in B3.4** (NEW — locks the cross-helper byte-identity invariant): for the same logical dict value `{"text": "abc"}`:
    - `_resolve_chunk_value(chunk_with_var=${X}, shared={"X": {"text": "abc"}})` → `'{"text":"abc"}'`
    - `_resolve_static_prefix_for_cache(template_str="prefix ${X} suffix", shared={"X": {"text": "abc"}})` → `'prefix {"text":"abc"} suffix'`
    - The substring `'{"text":"abc"}'` must appear byte-for-byte in BOTH outputs. If `TemplateResolver.resolve_template` is accidentally used directly in the static-prefix path, the substring becomes `"{'text': 'abc'}"` (Python repr) — different bytes — and this test catches it.
  - **Both call sites MUST filter the sentinel before building output** — this is the structural invariant:
    - `plan_node._render_cache_for_hash`: walks `cache_ctx.cache_block.items` filtered to `cache_ctx.subset`, calls `_resolve_chunk_value` per chunk, drops `_CHUNK_ABSENT` entries, builds `prompt_cache_content` list from the survivors.
    - `LLMNode.prep` (C1.2): walks the same chunks, calls `_resolve_chunk_value`, drops `_CHUNK_ABSENT` entries (recording skipped names in `prep_res["__cache_chunks_skipped__"]`), builds `system_blocks` from the survivors.
    By filtering on the same sentinel value at both sites, the rendered subsets are identical: `[a, c]` (skipping `b`) on both, with byte-equivalent value bytes for `a` and `c`. Test in B3.4 must include an ABSENT-branch case in the byte-equivalence assertion (see B3.4 tests). Without the sentinel filter, hash-time and prep-time can disagree on subset membership — the exact silent-stale-cache class.
  - **`cache_chunks_skipped` is recorded only at the LLMNode.prep call site** (not at plan_node). plan_node's hash is computed from the post-filter subset; the trace channel is for runtime visibility, which only the message-rendering site emits. The sentinel guarantees the SAME subset filter at both sites.
  - **Loop recovery × cache rendering (KNOWN LIMITATION)**: when a node is part of a loop where an upstream failed, was cleared via `clear_node_failure`, and is being retried, cache rendering during the retry's `LLMNode.prep` reads `node_state.get_node_status(shared, upstream)` AT THE MOMENT OF PREP. If prep runs before the upstream's retry completes (which is normally impossible — engine sequences upstream before downstream — but could occur in pathological loop-guard scenarios), the chunk is treated as ABSENT. The cache_key for that prep reflects the absent-state subset, while the next run (where upstream succeeds without retry) reflects the present-state subset. This produces non-deterministic cache_keys across runs that produce the same final shared state. **For v1**: the engine's normal sequencing guarantees upstream is COMPLETE (success or final-failure) before downstream prep runs, so this case is effectively impossible. Document the invariant in the rendering helper docstring: "Cache rendering reads upstream node state at prep time. The engine's DAG ordering guarantees upstream is in a terminal state (success or final-failure) before this prep fires; if a future engine change relaxes that guarantee, the determinism of cache_keys across runs degrades." No test required for v1 (the precondition holds by engine construction); follow-up if loop-guard semantics change.
  - **Memo HIT short-circuits cache rendering** (review-feature-interactions / Suggestion 21): when `plan_node` computes a hash with `prompt_cache_content` and that hash matches a memo cache entry, the engine takes the cached path via `apply_memo_hit + handle_cached_execution` (`engine.py` step 5–9) and skips node execution entirely. `LLMNode.prep()` never runs on memo hits, so the message-side rendering doesn't fire — no wasted work, and no new opportunity for hash-vs-prep divergence on the cached path. Document this in `_render_cache_for_hash`'s docstring: "On memo HIT, this rendering is the only one that fires (for hash computation); LLMNode.prep is skipped. On memo MISS, plan_node renders for hash, then LLMNode.prep renders for messages — both must agree per the invariant above."
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
  - **In-memory mutation test against baseline** (load-bearing for DD#19 byte-identity): for a representative baseline workflow (NO cache fields), parse to IR dict, then call `compile_workflow(ir_dict, registry)` directly (verified `compilation/compiler.py:460-500` accepts `dict`; bypasses `WorkflowExecutor._compiled_workflow_cache` which is keyed by resolved-path, not IR contents). Capture hash H_absent. Then mutate the IR in-memory:
    ```python
    # Top-level node key (NOT inside node["params"]) — matches B2.1 extraction:
    ir_dict["nodes"][i]["prompt_cache"] = []
    ```
    Recompile via `compile_workflow(ir_dict, registry)` again (same direct call — bypasses `_compiled_workflow_cache`). Capture H_empty. Assert `H_absent == H_empty` byte-for-byte. Then mutate further to add the cache block AND a non-empty subset:
    ```python
    ir_dict["nodes"][i]["prompt_cache"] = ["chunk"]
    ir_dict["cache"] = {  # top-level cache block (sibling of nodes/edges)
        "ttl": "5m",
        "items": [{"name": "chunk", "var": "concept", "prose_before": ""}],
    }
    ```
    Recompile, capture H_subset. Assert `H_subset != H_absent`. The mutation pattern catches the regression that the baseline alone cannot — `[]` ≡ absent — because the baseline can't include post-task fields (main HEAD doesn't parse them). **Mutation contract**: `compile_workflow(ir_dict, registry)` direct call is REQUIRED (do NOT route through `WorkflowExecutor` or `WorkflowRunner` — they consult `_compiled_workflow_cache` which keys by resolved-path; a second call with the same path returns the FIRST compile's cached value, and the mutation never lands). Test docstring should call this out explicitly.
  - Three-state distinction: (1) no field, (2) `prompt_cache: []`, (3) `prompt_cache: [chunk]`. Assert (1) === (2) at hash AND rendering levels (no `cache_control` markers, no `system_blocks` list — plain string `system`); (3) is distinct from both.
  - Node with `cache: false` AND `prompt_cache: [concept]`: memo cache write skipped (existing `cache_enabled=False` behavior); cache rendering still applies at runtime; in-process cache hash is computed correctly.
  - **Batch-node hash inclusion**: a batch LLM node with `prompt_cache: [concept]` produces a different hash than the same batch node without the field. The batch resolution path renders cache content from `shared` (non-batch refs only), independent of per-item template resolution.
  - **Hash-vs-prep render byte-equivalence invariant** (load-bearing per B3.3): for a workflow with `prompt_cache: [a, b]` declared and run end-to-end against `MockLLMClient`, capture (a) the rendered `prompt_cache_content` that `compute_node_config` saw at hash time (instrument by reading the call args), and (b) the rendered `system_blocks` text payload that the mock observed. Assert that for each chunk in the subset, the `value` bytes from (a) match the corresponding block's text bytes from (b) (modulo prose framing). If they ever differ, memo cache and adapter are out of sync — silent stale-cache hit. Catch this in B3, before any phase that depends on the invariant ships.
  - **Branch-absent symmetry test** (CRITICAL — locks the sentinel-filter invariant): the fixture must induce ABSENT via a CONDITIONAL BRANCH that runtime didn't take (NOT via a structurally-missing upstream — that would be caught by validator and never reach prep). Concrete fixture shape:
    ```
    nodes: [router, branch_a (LLM), b_producer (LLM), branch_c (LLM), llm_target (LLM)]
    edges: router action="take_a" → branch_a → branch_c → llm_target
           router action="take_b" → b_producer → branch_c → llm_target
    cache: items=[a, b, c]
    llm_target: prompt_cache=[a, b, c]
    ```
    Run with `router` returning `"take_a"` so `b_producer` never executes. Add a precondition assertion BEFORE the symmetry assertions: `assert get_node_status(shared, "b_producer") == NodeStatus.ABSENT` — pins down WHY `b` was skipped (runtime branch absence, not structural failure). Then capture (a) the `prompt_cache_content` at hash time (instrument `compute_node_config` call args) and (b) the `system_blocks` at prep time (read `MockLLMClient.call_history_full[-1]["system"]`). Assert: (1) BOTH have exactly 2 entries (`a` and `c`), NOT 3; (2) neither has any entry for `b` (no `None`-stringification on either side); (3) `shared["llm_target"]["llm_usage"]["cache_chunks_skipped"] == ["b"]`; (4) the trace 2.1.0 event records `cache_chunks_skipped: ["b"]`; (5) the precondition `get_node_status == ABSENT` (locks the test isn't passing for the wrong reason). Without all five assertions, the sentinel filter regression-class is uncaught.
  - **Divergence-injection variant** (anti-tautology): the byte-equivalence test passes whenever both sites import the same `_resolve_chunk_value` symbol — even if a future contributor inlined the resolution at one site and the duplicates happened to agree. Add a SECOND test variant that monkeypatches the per-site import binding independently:
    ```python
    # Both call sites must import via `from ... import _resolve_chunk_value`
    # (creating a local binding) so monkeypatch can target each site separately:
    monkeypatch.setattr("pflow.runtime.engine.plan_node._resolve_chunk_value",
                        lambda chunk, shared: f"plan-{chunk.var_expr}")
    monkeypatch.setattr("pflow.nodes.llm.llm._resolve_chunk_value",
                        lambda chunk, shared: f"llm-{chunk.var_expr}")
    ```
    Assert the byte-equivalence test FAILS in this variant. This proves the test would actually catch divergence — not just that today's implementation happens to agree. **DO NOT use `inspect.stack()`** — fragile under PyTest's frame manipulation, slow, non-deterministic across Python implementations. **DO NOT use `threading.local`** — engine and worker threads have independent thread-locals; a marker set on the engine thread isn't visible to a parallel-batch worker. The per-site monkeypatch approach works because both call sites import the symbol (not the module) — locking this contract in B3.3 is load-bearing for the divergence-injection test.
  - **Restore-from-absent**: construct a `WorkflowEngine`, call `run()` from a `shared` that lacks `__pflow_cache_render__`, and assert no `AttributeError`/`TypeError` raised. After completion, `shared.get("__pflow_cache_render__")` returns a `MappingProxyType({})` (NOT `None`).
  - **Outer-dict mutation rejected**: assert `shared["__pflow_cache_render__"]["new_node"] = ...` raises `TypeError` (MappingProxyType enforces read-only). Assert `dataclasses.replace(cache_ctx, prewarm=True)` works (frozen dataclasses support `replace`); but direct `cache_ctx.prewarm = True` raises `FrozenInstanceError`. Document why: parallel-batch concurrency surface elimination.
  - **Memo HIT short-circuit invariant** (Suggestion 21): a workflow with `prompt_cache: [concept]` declared, run twice with identical state. **Use a function-scoped `MockLLMClient` fixture** so call-count assertions baseline cleanly per test. First run misses memo, calls `MockLLMClient.complete()` (1 call). Second run hits memo. Assert: (a) `MockLLMClient.complete` was called exactly ONCE total across both runs (this fixture's call count, not session-cumulative); (b) the second run's `shared["llm-node-id"]` matches the first run's byte-for-byte (memo restored the cached output); (c) the second run's `shared["llm-node-id"]["llm_usage"]["cache_source"] == "memo"`. Together (a)+(b)+(c) prove the LLM was not re-called AND the cached output round-tripped correctly — without testing implementation details. **REMOVED**: a previous draft asserted "`LLMNode.prep` was not invoked" via a `prep` spy; that's implementation-detail testing — a future refactor that calls `prep` once on memo hits but skips render-side work would still satisfy the contract but break this assertion. The (a)+(b)+(c) trio is behavior-level and stable across refactors.

### Regression invariants — STOP IF ANY FAIL

- **Pre-merge baseline fixture exists**: `tests/test_runtime/fixtures/golden_config_hashes.json` is committed before B3.1 lands. Without this, the regression gate is a tautology.
- `tests/test_execution/test_plan_drift.py` (verified at plan-write: 6+ test cases at lines 45–172): planner ↔ runtime parity. The drift test sees the same memo cache state across both code paths; cache rendering produces identical content, hashes match. New ordering (resolve before hash) must not break this.
- All 7 files in `examples/` using `cache: false` execute identically — parameterize over all 7 in a single integration test, not "pick one." Cost is small; coverage gap was large in earlier draft.
- All ~212 existing LLM-related tests pass.

If the regression gate fails: STOP. Silent stale cache is unacceptable. **Failure message must include the regen command** (`uv run python scripts/generate_config_hash_baseline.py`) AND the warning "DO NOT regenerate without human review of the change — silent regeneration encodes the bug as expected."

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
  - In `prep()` (line 231): read `cache_ctx = (shared.get("__pflow_cache_render__") or {}).get(self.node_id)` (canonical defensive pattern per B3.2 — `or {}` handles legacy/test paths where the value may be `None`). **Do NOT cache `cache_ctx` on `self`** — `LLMNode` is reused across batch items per `nodes/CLAUDE.md` Pitfall #6, so any `self.X = result` would leak across iterations (Task 106 `_resolved` anti-pattern). The context is read fresh from `shared` on every `prep()` call. If `cache_ctx is None or not cache_ctx.subset`: skip cache rendering entirely; `prep_res["system"]` stays a plain string (today's behavior, byte-identical for opt-out nodes).
  - When `cache_ctx` is set with a non-empty subset, build `prep_res["system_blocks"]` (new key — a `list[dict]`) using the **shared** `_resolve_chunk_value` helper introduced in B3.3 (so hash and prep render byte-identically — the load-bearing invariant from B3.3):
    1. If the user's `system` param is set (existing `self.params.get("system")`), prepend it as the FIRST content block: `{"type": "text", "text": <user system>}` — NO `cache_control` marker. User-provided system text is not part of the cache prefix.
    2. Walk `cache_ctx.cache_block.items` (frozen tuple of `CacheChunkIR`) filtered to `cache_ctx.subset`, in declaration order. For each chunk:
       - Resolve via the shared `_resolve_chunk_value(chunk, shared)` helper (same call site `plan_node._render_cache_for_hash` uses — see B3.3).
       - Produce a content block: `{"type": "text", "text": chunk.prose_before + serialized_value}`.
    3. Place a `cache_control` marker on the LAST block (v1 single-breakpoint strategy per DD#11). Per-provider translation (spec "TTL wire-format translation per provider"):
       - **Anthropic**: marker is `{"type": "ephemeral"}` for omitted/`5m` (Anthropic does NOT accept `ttl: "5m"` per progress log §29 — omit `ttl` for the 5-min default); `{"type": "ephemeral", "ttl": "1h"}` for `1h`.
       - **Gemini**: `{"type": "ephemeral"}` for omitted; `{"type": "ephemeral", "ttl": "300s"}` for `5m`; `{"type": "ephemeral", "ttl": "3600s"}` for `1h`.
       - **OpenAI**: cache_control markers are no-op on OpenAI; emit them anyway for consistency, plus the OpenAI-specific knobs in C3.
    4. The TTL value is read from `cache_ctx.cache_block.ttl` (frozen attribute access on `CacheBlockIR`, NOT `.get(...)` — the field is typed and always present). Provider lookup via `detect_provider(model)` from `core/llm_providers.py`.
  - In `_call_llm` (line 332): pass `system=prep_res["system_blocks"]` to `complete()` when `system_blocks` is set; otherwise pass `system=prep_res["system"]` (today's plain-string path). The adapter widening in C1.1 accepts both.
  - **NO min-token threshold check at runtime.** Per DD#36 ("`pflow run` validation: no tokenizer, no historical state"), this expensive check moves to the analytical tier (`pflow analyze-cache` and `pflow run --dry-run`) where `litellm.token_counter` is permitted. The `cache.below-min-tokens` warning fires from F2's `analyze.py`, not from `LLMNode.prep()`. Earlier-draft runtime emission was inconsistent with DD#36.
  - **Cache-rendering template-resolution failure path** (per spec line 189): if a chunk's `${var}` fails to resolve at runtime (e.g. an upstream node failed), use the existing `build_template_error_diagnostic` pattern from `runtime/engine/template_errors.py`. Build the diagnostic with `node_id=self.node_id`, the chunk's `source_line`, and the failing reference. Return an error-dict from `_call_llm` (mirrors the typed-exception path at `_error_dict_from_exception`) so the Node retry loop short-circuits.
  - **Branch-absent skip with trace visibility** (spec edge case "Cache block references a step output on a branch that didn't execute"): the shared `_resolve_chunk_value` helper (B3.3) returns the `_CHUNK_ABSENT` sentinel when the upstream node's `node_state.get_node_status` is `ABSENT`. The C1.2 rendering loop checks for the sentinel and SKIPS the chunk. **Record the skipped chunk name** in `prep_res["__cache_chunks_skipped__"]: list[str]` (new key) so `LLMNode.post()` can write it to `shared[node_id]["llm_usage"]["cache_chunks_skipped"]`. The trace 2.1.0 channel surfaces this list per-event; `analyze-cache --from-trace` mode reads it to attribute discrepancies in cache_creation/read tokens to runtime branch-skips (vs TTL expiry, key mismatch, parallel-write race). Without this trace channel, agents see cache_key divergence between predicted and actual with no diagnostic explaining why. Document the behavior + trace key in the rendering helper's docstring. **The sentinel filter is the load-bearing invariant** — both `plan_node._render_cache_for_hash` (B3.3) and this `LLMNode.prep` rendering filter on the SAME `_CHUNK_ABSENT` value, so the rendered subset is identical at both sites.
  - **Cross-layer co-edits for `cache_chunks_skipped`** (CRITICAL — the channel must survive every error path):
    1. Extend `LLMNode.post()` (E.1) to copy `prep_res["__cache_chunks_skipped__"]` (default `[]`) into `shared[node_id]["llm_usage"]["cache_chunks_skipped"]`.
    2. Extend the error-output builder (`_error_dict_from_exception` or equivalent in `nodes/llm/llm.py`) to ALSO populate `cache_chunks_skipped` from the same `prep_res` source. **Without this**, when `_call_llm` short-circuits on the cache-rendering template-error path or any deterministic LLMCallError, `post()` does not run and the channel is lost — but the trace event for the failure path still needs the skip context for `analyze-cache --from-trace` discrepancy attribution.
    3. Persist `cache_chunks_skipped` in the `llm_usage` payload that `write_memo_cache` writes to disk. On memo HIT, `apply_memo_hit` round-trips the cached `llm_usage` (including this field) into `shared[node_id]["llm_usage"]` automatically — no special-case code needed beyond the keyset extension.
    The intent: every trace event that could correspond to a partial render — success, deterministic error, retry-failure, memo HIT — carries the skip list. Test in E.1 must cover the error-path case explicitly.

### Tests

- `tests/test_nodes/test_llm/test_prompt_cache_rendering.py` (new):
  - Anthropic node with `prompt_cache: [concept]` and a registered cache block: `MockLLMClient.call_history_full[-1]["system"]` is a list with at least one block carrying `cache_control: {"type": "ephemeral"}` on the last cache chunk; the user-provided `system` param (when set) appears as the first chunk WITHOUT a marker.
  - Anthropic with `- ttl: 1h` → marker is EXACTLY `{"type": "ephemeral", "ttl": "1h"}`.
  - Anthropic with `- ttl: 5m` → marker is EXACTLY `{"type": "ephemeral"}` (no `ttl` key). Assert `"ttl" not in marker` AND `len(marker) == 1`. Catches the bug where someone "symmetrically" emits `ttl: "5m"`.
  - No `prompt_cache` → `system` is a plain string (today's behavior).
  - Empty `prompt_cache: []` → `system` is a plain string. Three-state equivalence verified at the rendering level (mirrors B3.4 hash-level test).
  - Cache chunk references an absent branch's output → chunk silently skipped; remaining chunks render correctly; markers placed correctly on the (shortened) chunk list. **`prep_res["__cache_chunks_skipped__"]` carries the skipped chunk name(s)** and propagates through to `shared[node_id]["llm_usage"]["cache_chunks_skipped"]` so trace mode can attribute discrepancies.
  - **Branch-absent + order-mismatch interaction**: workflow with `prompt_cache: [a, b, c]` declared in correct order matching `## Cache`; runtime branch makes `b` absent so the rendered subset is `[a, c]`. Assert NO `cache.order-mismatch` diagnostic fires (the validator runs on the static IR, not the runtime-rendered subset). The order check is purely declaration-vs-IR, never runtime-vs-IR.
  - Cache-rendering template-resolution failure → error-dict returned from `_call_llm`; no retry; structured diagnostic with chunk `source_line` + the failing reference.
  - `cache: false` AND `prompt_cache: [concept]` on the same node: rendered system_blocks STILL carry `cache_control` markers (cache rendering applies independently of memo cache opt-out). Verifies the two-layer independence per spec "Cache Layer Independence".
  - Structured output (`output_schema`) + `prompt_cache`: the schema's `tools` injection (Anthropic structured output uses tools) does NOT displace cache_control markers from the system blocks.
  - Extended thinking + `prompt_cache`: thinking budget tokens do NOT count against `cache_creation_input_tokens`. The thinking block is in the response, not the request; cache prefix is request-side only.
  - **Parallel-batch ordering**: test that uses 8 parallel batch items finds at least one entry in `call_history_full` with the expected `cache_control` shape, but does NOT assert on `call_history_full[-1]` (last-to-append is non-deterministic across worker threads). Search/filter, never index by position.

### Test infrastructure prerequisite

- Widen `MockLLMClient.complete()`'s `system` parameter from `Optional[str]` to `Optional[Union[str, list[dict]]]` (line 194). The recorded entries in `call_history_full` already store `system` verbatim; cache-structure tests inspect `call_history_full[i]["system"]` directly. Update `tests/shared/llm_mock.py` and add a round-trip test asserting `system=[{...}]` is recorded as a list, not a stringified version.
- Extend `MockLLMClient.set_response(...)` to accept `cache_creation_input_tokens` and `cache_read_input_tokens` keyword args (default 0). They populate the returned `usage` dict so trace tests can simulate cache hits with specific token counts. Without this, downstream cache-correlation tests need ad-hoc monkey-patching.

### Regression invariants

- `tests/test_execution/test_plan_drift.py` stays green.
- All existing LLM tests pass (the type widening is null-safe; default `system: str | None` callers see no shape change in their messages).

---

# Phase C2 — Gemini cache rendering path

## Goal

Same rendering surface as C1 but for Gemini. Triggers `cachedContents` via LiteLLM's translation. Honors Gemini's seconds-suffix TTL format.

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
    - **Batch_size > 15 RPM soft cap (KNOWN LIMITATION — v1 documents, no client-side mitigation)**: OpenAI's `prompt_cache_key` provides sticky routing — same key → same backend instance, ~15 RPM soft cap per instance. A parallel batch with N items > 15 sharing the same `prompt_cache_key` will throttle (some calls 429, others fall through to other instances and miss the cache). v1's policy is "let throttling happen; pflow's existing retry layer handles 429s." Two follow-ups exist: (i) hash-stripe the key (`md5(content + index // 10).hexdigest()` — buckets items into groups of ~10 per instance, partial cache loss at bucket transitions), (ii) auto-clamp `max_concurrent` when OpenAI + non-empty `prompt_cache_items`. Both are deferred to v1.x as `cache.openai-batch-clamp` follow-up. **Document the limitation** in `pflow guide caching` (G.2) under OpenAI section: "For batches >15 parallel items on OpenAI, expect throttle-induced retries. The provider-side cache hit rate degrades gracefully but does not zero out." No catalog warning fires at runtime; F2's analyzer surfaces the case under `cache.batch-prewarm-recommended` when applicable.

- `src/pflow/core/llm_client.py`:
  - The `model_options` channel already passes through to `litellm.completion(**kwargs)` at line 277–279. No code change.

## Tests

- Extend `tests/test_nodes/test_llm/test_prompt_cache_rendering.py`:
  - OpenAI node with `prompt_cache: [concept]` → `MockLLMClient.call_history_full[-1]["model_options"]` contains `prompt_cache_key` (MD5 hex; deterministic across two calls with identical resolved values).
  - OpenAI node with `cache_block.ttl == "1h"` → `prompt_cache_retention: "24h"` in `model_options`.
  - OpenAI node with no `prompt_cache` → no cache-related kwargs leak into `model_options`.

---

# Phase D — Auto-batch-prefix detection + prewarm execution

## Goal

Two pieces, both flowing through the `CacheRenderContext` channel established in B3 (no new reserved keys):
1. LLMNode performs auto-batch-prefix detection: read `cache_ctx.unresolved_batch_prompt` and `cache_ctx.batch_alias`; find the first `${<alias>.X}` reference; everything before it is the static prefix; insert a second `cache_control` marker at the end of that prefix when `cache_ctx.prewarm` is true.
2. Batch executor's prewarm execution: serialize item[0], wait for cache write, then fan out items[1:]. The executor reads `prewarm` from `cache_ctx`, NOT from `node.params`.

## Pre-implementation verification

1. Confirm B3 has landed and `_build_cache_render_dict` populates `unresolved_batch_prompt` and `batch_alias` correctly for batch LLM nodes.
2. Read `runtime/engine/batch_executor.py` end-to-end. Confirm per-item template resolution lives in the `_execute_single_node` callback, not in `batch_executor` (per progress log §29 — option (c) for detection was rejected for this reason).

## D.1 — LLMNode auto-batch-prefix detection in `prep()`

### Files

- `src/pflow/nodes/llm/llm.py` (in `prep()`, after the cache rendering done in C1.2):
  - `cache_ctx = (shared.get("__pflow_cache_render__") or {}).get(self.node_id)` — already read for C1.2 via the canonical defensive pattern (see B3.2). The `or {}` matters: a future code path that writes `None` back into the key (or a test that bypasses the engine install) would otherwise raise `AttributeError` on `None.get(...)` — the exact trap the architectural backbone documents.
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
  - **Static-prefix resolution MUST use `_resolve_static_prefix_for_cache`** (per B3.3 helper definition). D.1's earlier draft said "use `TemplateResolver.resolve_template` directly" — but that substitutes embedded refs via Python's default `str(value)`, NOT via the deterministic helper. A dict value `{"text": "abc"}` would render as `"{'text': 'abc'}"` (Python repr) in the static prefix BUT as `'{"text":"abc"}'` (canonical JSON) in a declared cache chunk — same logical value, different bytes, silent cross-mode cache miss. Replace D.1's resolution call with `_resolve_static_prefix_for_cache(unresolved[:match.start()], shared)`. Both paths now route through the same deterministic-serialize pipeline.
  - **`_call_llm` consumer (CRITICAL — without this, `user_message_blocks` is built and never read)**: in `_call_llm` (line 332), pass `user_message_blocks=prep_res["user_message_blocks"]` to `complete()` when the key is set; otherwise fall back to today's path (no `user_message_blocks` kwarg, `complete()` constructs the user message from `prompt` + `attachments` as before). Mirror the same pattern C1.2 uses for `system_blocks`. The adapter widening below threads the kwarg into `_build_messages`.

- `src/pflow/core/llm_client.py`:
  - Widen `complete()` signature: add optional `user_message_blocks: list[dict[str, Any]] | None = None` keyword arg. When set, `_build_messages` uses it as the user-role `content`; when None, today's behavior (build from `prompt` + `attachments`).
  - `_build_messages` (line 579): when `user_message_blocks` is provided, use it directly as the user `content`. When absent, current behavior. Document both shapes in the docstring.
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
  - At the top of `_execute_parallel`, read `cache_ctx = (shared.get("__pflow_cache_render__") or {}).get(config.node_id)` (canonical defensive read pattern per B3.2). When `cache_ctx is not None and cache_ctx.prewarm` AND `len(items) > 1`, split the dispatch via the algorithm below. When prewarm is False, OR `cache_ctx is None`, OR `len(items) <= 1`, fall through to today's behavior (full parallel fan-out from the start).
  - **No `node.params` mutation, no `__prewarm__` reserved param key.** The batch executor reads `prewarm` from `CacheRenderContext` like every other consumer.
  - Sequential mode (`parallel: false`): ignores prewarm (no fan-out, no opportunity).
  - **Concrete prewarm-split algorithm — verified against actual code shapes** (`batch_executor.py:540-589` `process_item` returns 5-tuple; `:466-522` `_collect_parallel_results` consumes it). Two changes total:

    **Change 1**: Extend `_collect_parallel_results` signature with two backward-compatible kwargs at the end of its parameter list:
    ```python
    def _collect_parallel_results(
        future_to_idx: dict,
        items: list[Any],
        results: list,
        timings: list,
        pending_errors: list,
        config: NodeConfig,
        batch_config: BatchConfig,
        callback: Any,
        depth: int,
        *,
        initial_completed: int = 0,
        total: int | None = None,
    ) -> None:
    ```
    Inside, replace the existing `completed_count = 0` and `total = len(future_to_idx)` (lines 485-486) with `completed_count = initial_completed` and `total = total if total is not None else len(future_to_idx)`. All today's callers pass nothing — defaults preserve current behavior.

    **Change 2**: Refactor `_execute_parallel` body (replaces lines 591-606) to interpose the prewarm-split inside the existing `try`/`finally`:
    ```python
    cache_ctx = (shared.get("__pflow_cache_render__") or {}).get(config.node_id)
    do_prewarm = cache_ctx is not None and cache_ctx.prewarm and len(items) > 1

    pool = ThreadPoolExecutor(max_workers=batch_config.max_concurrent)
    try:
        if do_prewarm:
            # Run item[0] synchronously through the SAME process_item callable
            # the pool would use. process_item returns the 5-tuple
            # (idx, result, error, duration_ms, buffered_events).
            # Destructure and merge using the same logic _collect_parallel_results uses
            # so accounting (results, timings, pending_errors, progress events) stays
            # symmetric with the parallel path.
            idx0, result0, error0, duration_ms0, buffered_events0 = process_item(0, items[0])
            results[idx0] = result0
            timings[idx0] = duration_ms0
            _drain_worker_buffer(callback, buffered_events0)
            _report_batch_progress(callback, config.node_id, duration_ms0, depth, 1, len(items), error0 is None)
            if error0:
                pending_errors.append(error0)
                if batch_config.error_handling == "fail_fast":
                    # fail_fast: skip fan-out entirely; today's fail_fast raises
                    # via execute_batch AFTER aggregation, not here. Just return
                    # the partial state so execute_batch's downstream raise fires.
                    return
            start_idx = 1
        else:
            start_idx = 0

        future_to_idx = {
            pool.submit(process_item, idx, items[idx]): idx
            for idx in range(start_idx, len(items))
        }
        _collect_parallel_results(
            future_to_idx, items, results, timings, pending_errors,
            config, batch_config, callback, depth,
            initial_completed=start_idx, total=len(items),
        )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    ```

    Implementation requirements (verification gates during D.2 implementation):
    1. **`process_item` is the SAME closure** in both paths. The 5-tuple destructure must match `_collect_parallel_results:490` exactly (verified `batch_executor.py:589`). Do NOT introduce a parallel "single-item path."
    2. **`results[idx0]` and `timings[idx0]` are written using `idx0` from the destructure** (always `0`), NOT a hardcoded literal. Mirrors `_collect_parallel_results:491-492`. The `pending_errors.append(error0)` follows `_collect_parallel_results:498-499` exactly.
    3. **Item[0]'s `buffered_events` MUST drain through `_drain_worker_buffer`** before the pool dispatches items[1:] — otherwise item[0]'s child sub-workflow events render AFTER items[1:] start and the agent-facing progress is non-deterministic.
    4. **Item[0] is excluded from `future_to_idx`** (the comprehension starts at `start_idx`). After `_collect_parallel_results` returns, `results` has every index 0..N-1 filled.
    5. **Progress accounting** uses `initial_completed=1, total=len(items)` so progress shows "1/N" (item[0] done, drained earlier) through "N/N" (last future) — NOT "1/N-1" through "N-1/N-1".
    6. **`fail_fast` + item[0] failure**: append error to `pending_errors`, return early. `execute_batch` (line 236) checks `error_handling == "fail_fast" and errors` AFTER `_aggregate_batch_results` and raises if so — preserving the load-bearing ordering documented at `batch_executor.py:234-243` ("raise AFTER aggregation so shared[node_id] has the partial batch_metadata"). The early return WITHOUT raise here is intentional: it lets `execute_batch` follow its existing fail_fast path.
    7. **`continue` + item[0] failure**: fall through to fan-out (don't return early). items[1:] all pay full write cost (cache wasn't populated by item[0]) — documented expectation, no runtime assertion required.
    8. **`continue` + item[0] success below provider min-tokens** (silent provider no-op): items[1:] still all pay write cost. The analytical `cache.below-min-tokens` catches this at `analyze-cache` time per DD#36; runtime emits nothing.
    9. **`_pre_warm_compile_cache`** (`batch_executor.py:103-177`) is a SEPARATE concern (sub-workflow IR compile cache for `WorkflowExecutor` nodes). It runs at `execute_batch:223` BEFORE `_execute_parallel`. The new D.2 prewarm-split happens INSIDE `_execute_parallel` and is concept-orthogonal. Verified via reading `_pre_warm_compile_cache` body — it does NOT execute item[0]; it only loads+compiles the sub-workflow IR.

### Tests

Append to `tests/test_nodes/test_llm/test_batch_cache_prefix.py`. **All tests use a `function`-scoped `MockLLMClient` fixture** so call-count assertions baseline cleanly per test.

- **Prewarm + fail_fast + item[0] fails**: items[1:] not dispatched. Verify via `mock.complete_call_count == 1` (function-scoped baseline). Also assert `pending_errors` length == 1, `results[0]["status"] == "failure"`, `results[1:]` all `None`.
- **Prewarm + continue + item[0] fails**: items[1:] dispatched anyway, all marked as cache-write attempts (no reads). Verify `mock.complete_call_count == N`.
- **Prewarm + item[0] succeeds — barrier-based ordering test** (locks the serialize-then-fan-out invariant deterministically):
  ```python
  barrier = threading.Barrier(parties=N - 1, timeout=5.0)
  call_timestamps: dict[int, float] = {}
  def mocked_complete(prompt, model, system=None, **kwargs):
      idx = int(re.search(r"item-(\d+)", prompt).group(1))  # extract from per-item prompt
      call_timestamps[idx] = time.monotonic()
      if idx == 0:
          # Item[0] runs synchronously; does NOT enter the barrier.
          time.sleep(0.05)
      else:
          # Items[1:] all wait at the barrier — they cannot proceed until N-1
          # of them have arrived. If item[0] is incorrectly submitted to the pool,
          # it would also try to enter the barrier (parties=N-1 is wrong for N) and
          # the test deadlocks (timeout=5.0 fails it).
          barrier.wait()
      return mock_response_for(idx)
  ```
  Assert: (a) all N items complete within timeout (5s); (b) `call_timestamps[0] < call_timestamps[i]` for every `i in range(1, N)` — item[0]'s timestamp precedes all worker timestamps; (c) the workers' timestamps are clustered (within 100ms of each other) since they all unblocked simultaneously when the barrier filled. Catches BOTH "items[0] is submitted to the pool by mistake" (test deadlocks) AND "items[1:] start before item[0] completes" (timestamp ordering fails).
- **Prewarm + N=1**: skip auto-batch entirely (gate at top of `_execute_parallel` requires `len(items) > 1`). Verify `mock.complete_call_count == 1` and no `_drain_worker_buffer` call for item[0] (it wasn't prewarm-split — went through the regular full-fan-out path).
- **No prewarm**: full fan-out from start; item[0] uses the regular barrier (parties=N) without exception.
- **Per-item progress order** (not strict sequencing): assert that EVERY `call_history_full` entry for items[1:] has a `before-event` timestamp ≥ item[0]'s `after-event` timestamp; do NOT assert `call_history_full[0]` is item[0] (worker completion order is non-deterministic).

## D merge gate

- `test_engine_prompt_cache_plumbing.py`, `test_batch_cache_prefix.py` pass.
- `test_plan_drift.py` stays green.
- Existing batch tests pass (`tests/test_runtime/test_batch*` and `tests/test_runtime/test_compiler*`).

---

# Phase E — Trace format 2.1.0

## Goal

Bump the trace format constant, add per-event `cache_key`/`cache_source`/`cache_age_sec` and top-level `workflow_path`. Cost reporting unchanged — LiteLLM normalization in `llm_client.py:776–784` already handles the cache token counts. v1 trusts `litellm.completion_cost()` for per-TTL pricing distinction.

## Pre-implementation verification

Read `runtime/workflow_trace.py:202–238` (`_add_llm_data`) and confirm the LLM-call event payload comes from `node_output.get("llm_usage")`. Cache fields flow by extending the `llm_usage` dict the LLMNode writes (mirroring how `cache_creation_input_tokens` already flows there). The implementing agent confirms the data flow before patching.

## E.1 — Format constant + new fields (route cache metadata through `llm_usage`, NOT a sidecar)

### Files

- `src/pflow/runtime/workflow_trace.py`:
  - Bump `TRACE_FORMAT_VERSION = "2.1.0"` (line 17).
  - Constructor: add `workflow_path: str | None = None` keyword arg to `WorkflowTraceCollector.__init__`. Defaulting to `None` keeps the **40+ existing test instantiations** (verified via `grep -rn "WorkflowTraceCollector(" tests/ src/`) source-compatible — they continue to construct with positional / `workflow_name` kwarg only.
  - In `save_to_file` (line 487 — verify before patching), add `trace_data["workflow_path"] = self.workflow_path` unconditionally. When `workflow_path` is `None`, the saved trace's `workflow_path` field is JSON `null`. **No defensive assertion** — an earlier draft proposed asserting `self.workflow_path is not None` for 2.1.0 traces, which would fire on every test that constructs `WorkflowTraceCollector("test")` and saves the trace (40+ sites). The assertion's value (catch missing production plumbing) is dwarfed by its cost (bulk-update every test, OR feature-gate behind an env var that masks regressions). The plan instead relies on a **dedicated production-path integration test** (described below) to lock the contract.
  - **Production-path integration test** (replaces the dropped assertion): `tests/test_runtime/test_trace_format_2_1.py::test_workflow_path_set_in_production_runs` runs `WorkflowRunner().run()` end-to-end on (a) a file-based workflow, (b) an inline workflow, and (c) a sub-workflow invocation. For each, load the saved trace JSON and assert `trace["workflow_path"] is not None` AND `trace["format_version"] == "2.1.0"`. File-based: assert it equals the resolved file path. Inline: assert it matches `ir-hash:<32-char-hex>` regex. Sub-workflow: assert child trace's `workflow_path` is the child's resolved path (NOT the parent's). This locks the production-plumbing contract without polluting test fixtures.
  - In `_add_llm_data` (line 202): no new sidecar dict. The new fields (`cache_key`, `cache_source`, `cache_age_sec`) flow via the existing `llm_usage` keyset — same path `cache_creation_input_tokens` already takes (line 217–218). When `node_output["llm_usage"]` carries those keys, they land on `event["llm_call"]` automatically. **No new code in `_add_llm_data` other than the existing `event["llm_call"] = llm_usage` assignment** — the keyset is extended at the producer side.
  - For 2.0.0 backwards-compat: existing `format_version.startswith("2.")` gate (`trace_report.py:463` — verify line at patch time) continues to work. Add an info note when `analyze-cache --from-trace` auto-load skips a 2.0.0 trace AND there are matching 2.0.0 traces present — see F3.1 update below.

- `src/pflow/nodes/llm/llm.py`:
  - In `post()` (line 431, where `shared["llm_usage"]` is populated): `usage_dict.get("cache_key")`, `usage_dict.get("cache_source")`, `usage_dict.get("cache_age_sec")` are added to the `llm_usage` dict written to `shared`. For non-cached calls, only `cache_key` is set (the key the entry was written under, available from the engine via `write_memo_cache`). For cached calls, all three are set.
  - **`cache_chunks_skipped` (cross-layer co-edit from C1.2)**: `post()` ALSO copies `prep_res.get("__cache_chunks_skipped__", [])` into `shared[node_id]["llm_usage"]["cache_chunks_skipped"]`. Default empty list. This is the success-path producer for the trace channel.
  - **Error-path producer for `cache_chunks_skipped`**: extend the LLMNode's error-output builder (the path that fires when `_call_llm` returns an error-dict or raises a deterministic LLMCallError before `post()` runs) to ALSO copy `prep_res["__cache_chunks_skipped__"]` into the failure-event's `llm_usage`. Without this, the trace event for the failure carries no skip context, breaking `analyze-cache --from-trace` discrepancy attribution. Locate the error-output construction site (likely `_error_dict_from_exception` in `nodes/llm/llm.py`); add the copy alongside any existing `usage`-propagation.
  - **How does LLMNode learn the cache_key, cache_source, cache_age_sec?** They flow through the node-output dict the engine already writes via `apply_memo_hit` (cached path) or via `write_memo_cache` (write path). The engine's existing `usage` propagation is the channel; we extend the propagated keyset.
  - **Memo HIT round-trip for `cache_chunks_skipped`**: when the engine's `write_memo_cache` persists `shared[node_id]["llm_usage"]` to disk, the `cache_chunks_skipped` field is included automatically (it's in the dict). On a subsequent memo HIT, `apply_memo_hit` restores the full `llm_usage` payload — including the skip list from the original write. No special-case code; the field rides the existing channel.

- `src/pflow/runtime/engine/instrumentation.py`:
  - **All three sites below MUST gate cache-metadata writes on `node_type_name == "LLMNode"`.** Add a small helper `_should_write_cache_metadata(node_type_name) -> bool` that returns `node_type_name == "LLMNode"` and call it at all three sites for symmetry.
  - **ClaudeCodeNode is intentionally excluded from this gate** (design decision per round-3 review). ClaudeCodeNode writes `cache_creation_input_tokens` / `cache_read_input_tokens` to `shared["llm_usage"]` from the Claude SDK's metadata (verified `nodes/claude/claude_code.py:875-889`); those represent provider-side caching done by the SDK. pflow's memo-cache `cache_key` / `cache_source="memo"` / `cache_age_sec` are NOT meaningful for ClaudeCodeNode because:
    1. ClaudeCodeNode's request-shape (Claude Code agent loop) is not amenable to pflow's memo cache — its outputs depend on multi-turn agent behavior, not a single deterministic prompt+params hash.
    2. Mixing `cache_creation_input_tokens` (SDK-side) with `cache_source="memo"` (pflow-side) would mislead agents reading the trace into thinking the SDK cache fired when it was actually the pflow memo cache.
  - Document the exclusion in `_should_write_cache_metadata`'s docstring: `"""Allowlist semantics: returns True only for node types that participate in pflow's memo cache layer with explicit cache_key/cache_source/cache_age_sec semantics. Currently only LLMNode. Adding a new LLM-producing node type that participates requires extending this gate alongside the new node type's post() implementation. ClaudeCodeNode is intentionally NOT in the allowlist: its cache_creation/read_input_tokens come from the Claude SDK and reflect SDK-side caching (a different cache layer); adding pflow's memo cache_key/cache_source to ClaudeCodeNode's llm_usage would conflate two distinct cache layers and mislead agents reading the trace."""` Test in `tests/test_runtime/test_trace_format_2_1.py`: a ClaudeCodeNode that reaches `apply_memo_hit` does NOT get `cache_key` / `cache_source` / `cache_age_sec` added to its `llm_usage` — but its existing `cache_creation_input_tokens` (if any) survives untouched.
  - `apply_memo_hit` (line 241 — verified): when restoring `cached_output` to `shared[node_id]` AND `_should_write_cache_metadata(node_type_name)`, the cached output already contains the prior run's `llm_usage` (the cache layer round-trips it). On a cache hit, augment it with `cache_source="memo"` and `cache_age_sec=time.time() - created_at` (where `created_at` comes from the new `memo_cache_lookup` return shape — see below). Non-LLM nodes skip this entirely.
  - `memo_cache_lookup` (line 181): change return shape to also include `created_at` from the memo cache row. Use `MemoizationCache.get_with_age` (already exists at `cache.py:224`) instead of `.get` for the lookup. Threads through `check_memo_cache` and `plan_node`. The `created_at` value is an epoch (per progress log §30) — caller computes age via `time.time() - created_at`.
  - `handle_cached_execution` (line 480 — verified): in-process cache hits don't have a `cache_key` (they're in-memory), so `cache_source="in_process"`, `cache_key=None`, `cache_age_sec=None`. Write these into `shared[node_id]["llm_usage"]` ONLY when `_should_write_cache_metadata(node_type_name)`.
  - `write_memo_cache` (line 297 — verified): on successful write AND `_should_write_cache_metadata(node_type_name)`, the cache_key passed in is what the entry will be stored under. Before the write, augment `shared[node_id]["llm_usage"]` with `cache_key=<key>` so the trace event for THIS run records the key the entry was created with. (Correct: a cache-write event's `cache_key` is the key the writer used; a cache-hit event's `cache_key` is the key that matched.)

- `src/pflow/execution/runner.py`:
  - At line 126 (where `WorkflowTraceCollector` is constructed), pass `workflow_path=resolved.file_path or _synthesize_inline_workflow_id(resolved.ir)` so the trace carries the canonical identifier.

- `src/pflow/runtime/workflow_executor.py` (line 342):
  - The second `WorkflowTraceCollector(...)` instantiation site for child workflows. Pass the resolved child path: `WorkflowTraceCollector(workflow_name=str(workflow_path or "sub-workflow"), workflow_path=str(child_resolved_path))`. The resolved path is already in scope at line ~328 in the surrounding code per review-impact-completeness C1.

- `src/pflow/core/trace_report.py` (optional, per spec): surface `cache_source` and `cache_age_sec` in per-node markdown. If omitted, no regression — just missing detail.

- **`src/pflow/nodes/llm/llm.py` Interface docstring** (Round 4 impact-completeness — drives registry and template-validation pickup): the LLMNode's `Writes: shared["llm_usage"]: dict` Interface block at line ~157-166 must enumerate the new sub-keys so `registry/metadata_extractor.py::_parse_all_structures` (line 507) extracts them, and `runtime/template_validation/path_validation.py` recognizes `${node.llm_usage.cache_chunks_skipped}` etc. as valid template references at parse time. Add to the existing `llm_usage` block:
  - `cache_key: str | None` — memo cache key the entry was created with (write events) or matched against (hit events).
  - `cache_source: "memo" | "in_process" | None` — which cache layer served this call (None for fresh executions).
  - `cache_age_sec: float | None` — age of the cached entry in seconds (None for fresh executions or in-process hits).
  - `cache_chunks_skipped: list[str]` — chunk names skipped during cache rendering due to ABSENT upstream branches (default empty list).

- **`src/pflow/nodes/llm/README.md`** (line ~233-245 token-usage table): add the same four sub-keys as new rows or a sibling section. Keeps user-facing docs in sync with the registry-extracted Interface metadata.

- **Registry cache invalidation note**: existing pflow installs may have a stale `~/.pflow/registry.json` after upgrading. The registry refresh is implicit on `pflow run` (re-scan if interface signatures changed). For Task 159, the `cache_chunks_skipped` field is additive (existing key + new sub-keys); registry consumers that don't know about the sub-keys still see `llm_usage: dict` and treat unknown sub-keys as opaque. No explicit cache-clear step required.

## Tests

- `tests/test_runtime/test_trace_format_2_1.py` (new):
  - A run with `prompt_cache` produces a trace with `format_version: "2.1.0"`, `workflow_path` set (file path for file runs; `ir-hash:<md5>` for inline), and per-event `cache_key`/`cache_source`/`cache_age_sec` on cache-hit events.
  - A 2.1.0 trace is readable by the existing `format_version.startswith("2.")` consumer gate (`trace_report.py:463`) — no consumer-side regression.
  - `cache_age_sec` is correctly computed: write a memo entry, sleep 0.1s, hit it, assert `0.05 <= cache_age_sec <= 5.0`. Two-sided bound catches "epoch returned instead of age" bugs (review-test-fidelity C3).
  - Inline-workflow run produces `workflow_path: "ir-hash:<md5>"` matching `_synthesize_inline_workflow_id` output.
  - **Parallel-batch per-item granularity**: a parallel batch where two items hit different cache_keys (different rendered cache content per item) records BOTH cache_keys in the trace. `event["batch_items"][i]["llm_call"]["cache_key"]` is per-item, distinct per i. (Verifies the routing through `llm_usage` preserves per-item granularity, where the earlier-draft sidecar dict would have lost it.)
  - Sub-workflow run: child trace events carry the child's `workflow_path` (NOT the parent's). Verifies the workflow_executor.py:342 update.
  - **Non-LLM node cache-metadata gating** (review-silent-failures W5 / Suggestion 24): a workflow with a shell node that goes through `apply_memo_hit` produces a trace where `event["llm_call"]` is absent (correct — shell isn't an LLM call) AND `shared["shell-node-id"]` does NOT contain `cache_key`/`cache_source`/`cache_age_sec` keys. Catches the regression where the gate is missed at one of the three write sites and cache fields contaminate a non-LLM node's output dict.
  - **Tests with literal `"2.0.0"` — explicit triage** (Round 4 impact-completeness):
    - **Bump to `"2.1.0"`**: `tests/test_runtime/test_workflow_trace.py:335` — this test emits a fresh trace and reads its version. Update the literal to `"2.1.0"` after E.1 lands. (Verify line at patch time; tests evolve.)
    - **Keep at `"2.0.0"` (legacy-fixture tests, MUST stay unchanged)**: `tests/test_runtime/test_trace_integration.py:170` (constructs a 2.0.0 trace dict to test the consumer gate at `trace_report.py:463`); `tests/test_core/test_trace_report.py:43` and `:1295` (legacy-fixture tests for backwards-compat consumer behavior). These verify that a stored 2.0.0 trace still renders correctly under the post-task consumer code; bumping them would break the legacy contract.
    - Each updated test gets a one-line comment explaining the version choice (e.g., `# Bumped to 2.1.0 in Task 159 E.1` or `# Keep at 2.0.0 — testing legacy-fixture consumer compat`).
  - Tests that construct `WorkflowTraceCollector(workflow_name="...")` continue to work (workflow_path defaults to None). No bulk update needed.

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
  - Closed catalog of 10 `cache.*` warning IDs per spec DD#29. The catalog is a module-level constant `CACHE_WARNING_CATALOG: dict[str, CacheWarningSpec]` where `CacheWarningSpec` is a frozen dataclass with the fields below. **Each row's values are concrete, not placeholders** — the implementing agent encodes them verbatim. The 10th entry, `cache.discrepancy`, is added per the orchestrator decision (resolves the spec line-944 open question — it fills the 10-entry slot reserved by DD#29).

  | id | severity | source | category | message_template | required_context_keys | suggestions_template | path_template | nullable_cost_keys |
  |---|---|---|---|---|---|---|---|---|
  | `cache.order-mismatch` | `ERROR` | `validator` | `cache_failure` | `"{node_id}: prompt_cache order doesn't match ## Cache declaration\n  declared:  {declared}\n  you wrote: {actual}\n  fix:       reorder the `prompt_cache:` field to match ## Cache declaration order"` | `(("node_id", str), ("declared", list), ("actual", list))` | `[]` (message itself carries the fix) | `"nodes[id={node_id}].prompt_cache"` | `set()` |
  | `cache.unused-chunk` | `WARNING` | `validator` | `cache_warning` | `"## Cache declares chunk {chunk_name!r} but no node references it"` | `(("chunk_name", str), ("source_line", int))` | `["Remove the unused chunk from ## Cache, OR add it to a node's prompt_cache: list."]` | `"cache.items[name={chunk_name}]"` | `set()` |
  | `cache.shared-context-undeclared` | `INFO` | `cache_analyzer` | `cache_advisory` | `"{node_count} LLM nodes share static context that isn't in any ## Cache block (saves ~${savings_usd:.2f}/run)"` | `(("node_count", int), ("shared_chunks", list), ("affected_workflow", str), ("savings_usd", float\|None))` | `["Paste the suggested ## Cache block (see Suggested ## Cache block section above) into {affected_workflow}.", "Per-node prompt_cache: assignments are listed in the same section."]` | `"workflows[path={affected_workflow}]"` | `{"savings_usd"}` |
  | `cache.batch-prewarm-recommended` | `WARNING` | `cache_analyzer` | `cache_warning` | `"{node_id}: {batch_size}-item batch with ~{prefix_tokens_estimated}-token static prefix has no explicit prewarm decision; prewarming would save ~{savings_pct}% of batch cost"` | `(("node_id", str), ("batch_size", int), ("prefix_tokens_estimated", int), ("savings_pct", int), ("savings_usd", float\|None))` | `["Add `- prewarm: true` to {node_id} to opt in (-${savings_usd:.2f}/run).", "OR add `- prewarm: false` to {node_id} to opt out explicitly (suppresses this warning)."]` | `"nodes[id={node_id}]"` | `{"savings_usd"}` |
  | `cache.dynamic-before-static` | `WARNING` | `cache_analyzer` | `cache_warning` | `"{node_id}: dynamic `${{{dynamic_ref}}}` reference at line {dynamic_line} of the prompt template precedes ~{cacheable_tokens}-token cacheable content; cache won't fire for {affected_calls} calls per run"` | `(("node_id", str), ("dynamic_ref", str), ("dynamic_line", int), ("cacheable_tokens", int), ("affected_calls", int), ("savings_usd", float\|None))` | `["Move the cacheable content (everything stable across calls) to BEFORE `${{{dynamic_ref}}}` in the prompt template.", "Projected cache ratio after fix: {projected_ratio_pct}%."]` | `"nodes[id={node_id}].prompt"` | `{"savings_usd"}` |
  | `cache.padding-advisory` | `INFO` | `cache_analyzer` | `cache_advisory` | `"{node_id}: prompt_cache subset doesn't start at position 1 of ## Cache declaration order; padding to {suggested_subset} would unlock prefix hits at 0.1× read rate (saves ~${savings_usd:.4f}/run)"` | `(("node_id", str), ("current_subset", list), ("suggested_subset", list), ("savings_usd", float\|None))` | `["Extend `prompt_cache:` to `{suggested_subset}` to gain prefix-cache hits from upstream writes."]` | `"nodes[id={node_id}].prompt_cache"` | `{"savings_usd"}` |
  | `cache.below-min-tokens` | `WARNING` | `cache_analyzer` | `cache_warning` | `"{node_id}: declared cache content is ~{cacheable_tokens} tokens, below {model}'s minimum of {min_tokens}; cache_control markers will silently no-op at the provider"` | `(("node_id", str), ("model", str), ("cacheable_tokens", int), ("min_tokens", int))` | `["Increase cache content above {min_tokens} tokens by adding more chunks to ## Cache, OR remove `prompt_cache:` from {node_id} since the cache won't fire anyway."]` | `"nodes[id={node_id}].prompt_cache"` | `set()` |
  | `cache.cross-workflow-prose-mismatch` | `INFO` | `cache_analyzer` | `cache_advisory` | `"{parent_workflow} → {child_workflow}: chunk `{chunk_name}` declared in both ## Cache blocks with different prose-before-${{var}}; cross-workflow byte-level cache hit will not fire"` | `(("parent_workflow", str), ("child_workflow", str), ("chunk_name", str), ("parent_prose", str), ("child_prose", str))` | `["Pick one prose label and use it in both files' ## Cache blocks for chunk `{chunk_name}`."]` | `"workflows[path={parent_workflow}].cache.items[name={chunk_name}]"` | `set()` |
  | `cache.cross-workflow-rename-detected` | `INFO` | `cache_analyzer` | `cache_advisory` | `"{parent_workflow} → {child_workflow}: parent passes `{parent_value_expr}` as input named `{child_input_name}` (line {line_in_parent}); same logical value has two names across the boundary"` | `(("parent_workflow", str), ("child_workflow", str), ("parent_value_expr", str), ("child_input_name", str), ("line_in_parent", int))` | `["Rename the child input to match the parent's value name, OR rename the parent value to match the child's input name. Then ensure both ## Cache blocks use the same chunk identifier and identical prose."]` | `"workflows[path={parent_workflow}].nodes[id={parent_node_id}].inputs[name={child_input_name}]"` | `set()` |
  | `cache.discrepancy` | `INFO` | `cache_analyzer` | `cache_advisory` | `"{node_id} (path: {trace_path}): predicted hit_ratio {predicted_pct}%, actual {actual_pct}% — root cause: {root_cause_summary}"` | `(("node_id", str), ("trace_path", str), ("predicted_pct", int), ("actual_pct", int), ("root_cause", str), ("root_cause_summary", str), ("cache_age_sec", float\|None), ("predicted_cache_key", str\|None), ("actual_cache_key", str\|None))` | DISPATCHED — see action-template map below. | `"nodes[id={node_id}]"` | `set()` |
  | `cache.invalid-on-non-llm` | `ERROR` | `validator` | `cache_failure` | `"{node_id}: {invalid_fields_csv} {is_or_are} only valid on type: llm nodes (this node is type: {node_type}). For sub-workflow caching, declare ## Cache and prompt_cache: inside the sub-workflow file."` | `(("node_id", str), ("node_type", str), ("invalid_fields", list), ("invalid_fields_csv", str), ("is_or_are", str))` | `["Remove the invalid declaration{plural_s} ({invalid_fields_csv}) from {node_id}, OR move the LLM logic into a type: llm node and reference it from {node_id}."]` | `"nodes[id={node_id}]"` | `set()` |
  | `cache.prewarm-no-prefix` | `INFO` | `cache_analyzer` | `cache_advisory` | `"{node_id}: prewarm: true declared but the prompt template has no static prefix before the first ${{<batch_alias>.X}} reference; auto-batch-prefix caching cannot fire (no shared bytes across items)."` | `(("node_id", str), ("batch_alias", str), ("first_dynamic_position", int))` | `["Move stable content (instructions, schema definitions, persona) BEFORE the first `${{<batch_alias>.X}}` reference in the prompt template, OR remove `- prewarm: true` from {node_id} since auto-batch-prefix caching has nothing to cache."]` | `"nodes[id={node_id}].prompt"` | `set()` |

  **`cache.discrepancy` action-template dispatch + structured context payload** (CRITICAL — per Round 3 fix to the unresolvable `{root_cause_action}` placeholder, AND Round 4 high-value fix #2 making `cache.discrepancy` agent-actionable without prose parsing). The `make_diagnostic` helper, when called with `warning_id="cache.discrepancy"`, dispatches on `context["root_cause"]` and renders the corresponding action template — AND populates a structured `context["root_cause_action"]` payload so agents reading the trace event can dispatch on typed data, not regex-parsed prose. Three module-level constants live in `warning_catalog.py`:
  ```python
  # Prose templates for human display (rendered into `suggestions`):
  CACHE_DISCREPANCY_ACTION_TEMPLATES: dict[str, str] = {
      "ttl_expiry":          "Consider `- ttl: 1h` on the {affected_workflow} ## Cache block.",
      "key_mismatch":        "Upstream value changed between predicted run and actual run; re-run analyze-cache to refresh the prediction.",
      "parallel_write_race": "Add `- prewarm: true` to the batch node to serialize the first write.",
      "chunk_skipped":       "Cache chunk `{skipped_chunk}` was skipped at runtime (branch absent); declaration is correct but rendered subset is shorter.",
      "unknown":             "Cannot attribute discrepancy to root cause {root_cause!r} (not in known set: ttl_expiry|key_mismatch|parallel_write_race|chunk_skipped); inspect the trace events for {node_id} manually.",
  }

  # Per-cause caller-required context keys (KeyError if any missing):
  CACHE_DISCREPANCY_REQUIRED_CONTEXT: dict[str, tuple[tuple[str, type], ...]] = {
      "ttl_expiry":          (("affected_workflow", str),),
      "key_mismatch":        (),
      "parallel_write_race": (),
      "chunk_skipped":       (("skipped_chunk", str),),
      "unknown":             (),
  }

  # Structured context payload schema — agents dispatch on these typed fields,
  # NOT on regex-parsed action prose. The helper assembles a dict with these
  # fields per root_cause and stores it at context["root_cause_action"].
  # Locks the agent-facing JSON contract: agents see typed data per cause
  # without parsing strings.
  CACHE_DISCREPANCY_ACTION_PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
      "ttl_expiry":          ("suggested_ttl", "affected_workflow"),
      "key_mismatch":        ("upstream_value_changed",),
      "parallel_write_race": ("recommended_fix",),
      "chunk_skipped":       ("skipped_chunk", "branch_node"),
      "unknown":             ("raw_root_cause",),
  }
  ```
  After dispatch, the helper populates `context["root_cause_action"]` from the per-cause payload schema:
  ```python
  # Pseudo-code inside make_diagnostic for cache.discrepancy:
  if root_cause == "ttl_expiry":
      action_payload = {"suggested_ttl": "1h", "affected_workflow": context_kwargs["affected_workflow"]}
  elif root_cause == "key_mismatch":
      action_payload = {"upstream_value_changed": True}
  elif root_cause == "parallel_write_race":
      action_payload = {"recommended_fix": "prewarm:true"}
  elif root_cause == "chunk_skipped":
      action_payload = {
          "skipped_chunk": context_kwargs["skipped_chunk"],
          "branch_node": context_kwargs.get("branch_node"),  # optional — analyzer may not always identify
      }
  else:  # "unknown" or unrecognized
      action_payload = {"raw_root_cause": root_cause}
  context["root_cause_action"] = action_payload
  ```
  Helper logic for `cache.discrepancy`:
  1. Validate the base `required_context_keys` (the 9 in the catalog row). KeyError if any missing — including `root_cause` itself.
  2. Look up `root_cause` in `CACHE_DISCREPANCY_ACTION_TEMPLATES`. If the key is present but the VALUE is not a known enum, fall back to the `"unknown"` row AND emit `logger.warning("cache.discrepancy emitted with unrecognized root_cause %r — using fallback action template", root_cause)` so a future contributor adding a new enum value but forgetting to update the dispatch map doesn't degrade silently.
  3. Validate the per-root_cause additional required keys from `CACHE_DISCREPANCY_REQUIRED_CONTEXT[root_cause]`. KeyError if any missing.
  4. Build the format dict as `{**context_kwargs, "node_id": node_id}` (so `{node_id}` placeholders in the action template resolve correctly — `node_id` is the helper's separate kwarg, not in `context_kwargs`).
  5. Format the action template via `.format(**format_dict)` and assign the result as the single suggestion. Suggestions list is `[formatted_action]`.
  6. The unknown-enum fallback message references `{node_id}` only — and that's now in the format dict. The unknown-row template ALSO substitutes the rejected enum value: change the `"unknown"` row template to `"Cannot attribute discrepancy to root cause {root_cause!r} (not in known set: ttl_expiry|key_mismatch|parallel_write_race|chunk_skipped); inspect the trace events for {node_id} manually."` so the agent sees what enum value was rejected, not just "unknown."

  **`root_cause` enum values for `cache.discrepancy`** (only emitted in `--from-trace` / mode-4): `"ttl_expiry"` | `"key_mismatch"` | `"parallel_write_race"` | `"chunk_skipped"` | `"unknown"`. Encoded as a `Literal` in `CacheWarningSpec`. Note: `context["root_cause"]` MUST preserve the original (possibly-unknown) value even when the action template comes from the `"unknown"` row — agents reading the trace event need the rejected enum for debugging.

  **Catalog count strategy (CRITICAL — avoids drift)**: define `EXPECTED_CATALOG_COUNT: int = len(CACHE_WARNING_CATALOG)` next to the catalog dict in `warning_catalog.py`. ALL count-references — F1 catalog test, F2 per-warning-ID coverage assertion, F3.2 MCP docstring contract test — read this constant rather than hardcoding "12." Tests assert `len(CATALOG) == EXPECTED_CATALOG_COUNT` AND assert that the docstring contains `len(CATALOG)` distinct id strings (computed at test time, not hardcoded). Adding a new ID later requires zero count-update edits across the plan; the constant is auto-derived. Round-3 left "10/11/12" in 5 prose sites — the constant pattern eliminates that entire drift class.

  - `cache.invalid-on-non-llm` — validator-side ERROR closing the validator-reach gap (B2.3, see C3 review fix).
  - `cache.prewarm-no-prefix` — analytical-tier INFO that surfaces when `prewarm: true` is declared but no static prefix exists (D.1 references it; previously not in catalog).
  F2's per-warning-ID synthetic-workflow coverage test (Suggestion 30) must add fixtures for both: (a) a workflow with `prompt_cache: [chunk]` on a `type: shell` node (triggers `cache.invalid-on-non-llm`), (b) a workflow with `prewarm: true` and a prompt template starting with `${item.X}` directly (no static prefix; triggers `cache.prewarm-no-prefix`).

  - **`cache.opportunities-available`** is NOT in the catalog — it's the dry-run nudge ID emitted by `summarize()` per spec line 307. It has its own constant `CACHE_OPPORTUNITIES_NUDGE_ID = "cache.opportunities-available"` next to the catalog. The dry-run nudge format string is locked separately at `summarize.py` (see F2 + F3.3); message format: `"Cache: {n} design opportunit{y_or_ies} available (estimated -${savings_usd:.2f}/run, -{savings_pct}%)."` where `y_or_ies = "y" if n == 1 else "ies"`.

  - Helper: `make_diagnostic(warning_id, *, node_id=None, **context_kwargs) -> Diagnostic` reads the catalog row, formats `message_template` + each `suggestions_template` entry via `.format(**format_dict)` (where `format_dict = {**context_kwargs, "node_id": node_id}`), attaches `id=warning_id`, `source` from the catalog row (NOT uniform — per-ID split), `severity` from the row, `context["category"]` from `category_constant`, `see_also=["caching"]`, and `path` from `.format(**format_dict)` on `path_template`. **Validates** that all `required_context_keys` are present in `context_kwargs` (raises `KeyError` at construction if missing — catches catalog-misuse bugs at test time, not in production). **`node_id` is merged into the format dict** so message/suggestions/path templates can reference `{node_id}` without the caller having to duplicate it in `context_kwargs`.

  - **`cache.invalid-on-non-llm` emission contract** (V6 fix — combined-diagnostic shape per Round 4 review): emit ONE Diagnostic per offending node listing ALL offending fields, NOT one Diagnostic per field. Identity tuple `(severity, source, node_id, id or message)` would collapse per-field emissions on shared `id`, hiding offenses. Caller computes:
    ```python
    invalid_fields = [k for k in ("prompt_cache", "prewarm") if k in node and node["type"] != "llm"]
    if not invalid_fields:
        return  # nothing to emit
    invalid_fields_csv = ", ".join(invalid_fields)
    is_or_are = "is" if len(invalid_fields) == 1 else "are"
    plural_s = "" if len(invalid_fields) == 1 else "s"
    diag = make_diagnostic(
        "cache.invalid-on-non-llm",
        node_id=node["id"],
        node_type=node.get("type", ""),
        invalid_fields=invalid_fields,
        invalid_fields_csv=invalid_fields_csv,
        is_or_are=is_or_are,
        plural_s=plural_s,
    )
    ```
    A node with both `prompt_cache:` and `prewarm:` produces `invalid_fields=["prompt_cache", "prewarm"]`, message reads "X: prompt_cache, prewarm are only valid on type: llm nodes...", suggestions list reads "Remove the invalid declarations (prompt_cache, prewarm) from X, OR..." — agent sees both offenses in one diagnostic. Matches mypy/ruff convention (one error per [rule, location], multiple offenses listed).

  - **Special case for `cache.discrepancy`**: when `warning_id == "cache.discrepancy"`, the helper does NOT format the catalog's `suggestions_template` directly (the catalog cell says "DISPATCHED"). Instead, after validating the 9 base required keys, the helper dispatches on `context_kwargs["root_cause"]`, looks up `CACHE_DISCREPANCY_ACTION_TEMPLATES[root_cause]` (falling back to the `"unknown"` row if the value is not a known enum, with `logger.warning` per step 2 above), validates the per-root_cause additional required keys from `CACHE_DISCREPANCY_REQUIRED_CONTEXT[root_cause]`, formats the chosen template via `.format(**format_dict)`, and assigns `suggestions=[formatted_action]`. This contains the `{root_cause_action}` / `{affected_workflow}` / `{skipped_chunk}` placeholders that the catalog cannot express in a single template.

  - **Source split is load-bearing** (per the table). Identity tuple `(severity, source, node_id, id or message)` collapses identical findings within a source but NOT across sources, so the same ID surviving from both validator and analyzer paths produces one entry per surface (the desired behavior — both surfaces mean different things to the agent).

  - **`cache.below-min-tokens` is analytical-only** per spec catalog AND DD#36. It does NOT fire from `LLMNode.prep()` at runtime. The analyzer (F2's `analyze.py`) computes the threshold check via `core/llm_capabilities.py::get_min_cache_tokens(model)` (B1.2) and emits this ID.

  - Test in `tests/test_core/test_cache_analysis_warnings.py`: parameterized over every catalog entry via `CACHE_WARNING_CATALOG.keys()` (DO NOT hardcode "11" or "12" — count drifts; iterate over the catalog itself). Asserts: (1) `make_diagnostic(id, ...)` produces the expected severity/source/category/message/suggestions; (2) `path` matches the template; (3) `id` is in the diagnostic's `id` field (not buried in context); (4) byte-equality of the canonical message format for at least one example invocation per ID — explicitly tests that `cache.batch-prewarm-recommended`'s suggestions list BOTH `prewarm: true` AND `prewarm: false` (agent must see both paths suppress the warning); (5) `make_diagnostic` raises `KeyError` when a required context key is missing; (6) `nullable_cost_keys` truly are `null`-able — passing `savings_usd=None` produces a Diagnostic without raising or substituting `0.00`. (7) **Catalog-count integrity**: `assert len(CACHE_WARNING_CATALOG) == EXPECTED_CATALOG_COUNT` — fails if a new entry is added without updating the constant. (8) **`cache.invalid-on-non-llm` combined emission** (V6): a fixture node with both `prompt_cache:` and `prewarm:` produces ONE Diagnostic (not two); `context["invalid_fields"] == ["prompt_cache", "prewarm"]`; message contains both field names CSV-formatted; the diagnostic deduplicates correctly when emitted twice for the same node (test calls `deduplicate_diagnostics([d, d])` and asserts `len() == 1`).
  - **`cache.discrepancy` dispatch tests** (new, parametrized table — locks per-cause contract for BOTH prose action AND structured `context["root_cause_action"]` payload — Round 4 high-value fix #2):
    ```python
    @pytest.mark.parametrize("root_cause, extra_kwargs, expected_action_text, expected_payload", [
        ("ttl_expiry",          {"affected_workflow": "x.pflow.md"},
            "Consider `- ttl: 1h` on the x.pflow.md ## Cache block.",
            {"suggested_ttl": "1h", "affected_workflow": "x.pflow.md"}),
        ("key_mismatch",        {},
            "Upstream value changed between predicted run and actual run; re-run analyze-cache to refresh the prediction.",
            {"upstream_value_changed": True}),
        ("parallel_write_race", {},
            "Add `- prewarm: true` to the batch node to serialize the first write.",
            {"recommended_fix": "prewarm:true"}),
        ("chunk_skipped",       {"skipped_chunk": "concept"},
            "Cache chunk `concept` was skipped at runtime (branch absent); declaration is correct but rendered subset is shorter.",
            {"skipped_chunk": "concept", "branch_node": None}),
    ])
    def test_cache_discrepancy_dispatch(root_cause, extra_kwargs, expected_action_text, expected_payload):
        diag = make_diagnostic("cache.discrepancy", node_id="X", trace_path="...", predicted_pct=80, actual_pct=20, root_cause=root_cause, root_cause_summary="...", cache_age_sec=None, predicted_cache_key=None, actual_cache_key=None, **extra_kwargs)
        assert diag.suggestions == [expected_action_text]                  # human-display prose
        assert diag.context["root_cause"] == root_cause                    # original value preserved
        assert diag.context["root_cause_action"] == expected_payload       # agent-facing typed payload
    ```
    Plus four additional tests:
    (a) **Missing per-cause required key**: `make_diagnostic("cache.discrepancy", root_cause="ttl_expiry", ...)` WITHOUT `affected_workflow` raises `KeyError`.
    (b) **Missing base required key**: `make_diagnostic("cache.discrepancy", ...)` WITHOUT `root_cause` raises `KeyError` (this is base-list validation, fires before dispatch).
    (c) **Unknown enum fall-through**: `make_diagnostic("cache.discrepancy", root_cause="future_value", ...)` falls through to the `"unknown"` template WITHOUT raising; `caplog` captures `logger.warning` with the rejected value `"future_value"`; `diag.context["root_cause"] == "future_value"` (preserved); `diag.context["root_cause_action"] == {"raw_root_cause": "future_value"}` (typed fallback payload — agents dispatch on `"raw_root_cause" in action_payload` to detect unknown-cause without regex-parsing prose); rendered message contains the literal string `'future_value'` so the agent sees what was rejected.
    (d) **Optional `branch_node` in chunk_skipped payload**: when caller passes `branch_node="router"` AS a context kwarg, the payload reflects it. When omitted, payload has `branch_node=None`. Locks the optional-key contract.

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
  - **Sub-workflow resolution failure handling** (Suggestion 22 — handled without new catalog ID): when `resolve_sub_workflow(child_ref)` raises (broken file path, missing workflow, cycle at depth limit), the walker does NOT silently drop the edge. Two cases:
    - **Cycle / depth limit hit**: walker stops descending that branch but continues siblings. Logs via `logger.info` (not a Diagnostic — cycles are an analyzer-internal limit, not a user-facing finding) so the agent can see it in `--verbose` mode.
    - **Resolution error (broken ref)**: re-raise the underlying `WorkflowValidationError` / `WorkflowNotFoundError`. These are validation errors that should surface through the existing diagnostic pipeline — the SAME error that would fire if the user tried to run the workflow. Adding a new `cache.*` ID for this would duplicate machinery the validator already provides. The cross-workflow walker is opt-in (only fires when `analyze-cache` runs); if the workflow has broken sub-workflow refs, `pflow run` would already fail with the same diagnostic. No silent-skip — the analyzer either produces findings on a structurally valid workflow OR reports the same validation error the runner would.
  - Three detection rules per spec "Cross-Workflow Walker":
    - **Rename detection** (`cache.cross-workflow-rename-detected`): when a parent edge has `child_input_name != tail_of_parent_value_expr`.
    - **Prose mismatch** (`cache.cross-workflow-prose-mismatch`): when names match across the boundary AND parent and child both declare `## Cache` blocks with the same chunk identifier AND the prose-before-the-`${var}` differs byte-by-byte. Suppressed when a rename was detected for the same chunk (rename takes precedence per spec).
    - **Value-flow opportunity**: parent passes a value into child but neither file's `## Cache` declares it → emits `cache.shared-context-undeclared` scoped to the boundary.
  - Batch sub-workflows: walker uses `WorkflowValidator._enumerate_child_calls` (from `validator.py:807–880`) to enumerate per-batch-item child calls when params reference the batch alias. Heterogeneous batches yield N edges; homogeneous yield 1.

- `src/pflow/core/cache_analysis/padding_advisor.py` (new):
  - `compute_padding_advisories(workflow_ir, per_node_token_estimates) -> list[Diagnostic]` — for each node whose `prompt_cache:` subset doesn't start at position 1 of the master order, compute the net-positive math per spec "Prefix-Padding Advisory". Apply the sensitivity floors ($0.005 per advisory, $0.05 cumulative). Emit `cache.padding-advisory` Diagnostics.

## Tests

- `tests/test_core/test_cache_analysis_warnings.py` (new): each warning ID emits with the right severity, context shape, source.
- `tests/test_core/test_cache_analysis_token_estimation.py` (new): tier order works; trace, memo, estimator, heuristic all reachable; confidence labels match. **`litellm.token_counter` empirical findings** (verified during plan refinement): does NOT raise on unknown models — falls back to a default tokenizer. Test asserts: (a) known model returns deterministic count; (b) unknown model returns SOME count (source still labeled `estimator`, not `heuristic`); (c) `text=None` raises `ValueError` and the wrapper falls through to `heuristic`; (d) `text=""` returns 0. The "exception → fall through to heuristic + log warning" path fires for the `text=None` case and any future LiteLLM regression where unknown models start raising.
- `tests/test_core/test_cache_analysis_cross_workflow.py` (new): rename detection, prose mismatch, value-flow opportunity, batch sub-workflow enumeration, cycle detection (logs at info, doesn't crash), depth limit (logs at info, doesn't crash). **Resolution-error propagation** (Suggestion 22): when a parent has a broken sub-workflow ref, the walker re-raises `WorkflowValidationError` (NOT silently skip, NOT a new `cache.*` ID).

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
  - **2.0.0-skip info note** (review-silent-failures C7): when auto-load finds 2.0.0 traces matching the workflow filename but skips them due to format version, append an info note to `analysis.notes`: `"Found N 2.0.0 traces matching this workflow but skipped (auto-load requires 2.1.0). Use --from-trace <path> to load a specific trace, or --no-trace-autoload to disable auto-loading."` Without this, agents see `confidence: low_no_data` and don't realize their existing traces are present-but-ignored.
  - **Unparseable-trace defense** (Round 4 silent-failure): when scanning `~/.pflow/debug/`, individual trace files may be corrupt JSON, missing required fields, or otherwise unreadable. The scanner MUST NOT silently skip them — log via `logger.debug("Skipping unparseable trace %s: %s", path, exc)` per skipped file (debug, not info — too noisy for normal runs) AND when ≥1 skip fired during this analyze invocation, append an info note to `analysis.notes`: `"Found N unparseable trace files in ~/.pflow/debug/ (run with --verbose for details)."` Mirrors the 2.0.0-skip pattern. Without this, agents whose recent trace files got corrupted see `confidence: low_no_data` with no signal that their traces are present-but-broken.
  - **Predicted cache_key uses shared resolution helper** (Round 4 impact-completeness): when computing `predicted_cache_key` for `cache.discrepancy` analysis, F2's `analyze.py` MUST use the same `_resolve_chunk_value` helper from `runtime/engine/plan_node.py` (or its successor location per B3.3) — NOT inline a parallel resolution path. Inline reimplementation diverges from runtime resolution and produces false discrepancy reports. The analyzer's prediction context uses memo'd upstream values (per DD#34 confidence labeling); the helper's resolution semantics (sentinel-on-ABSENT, deterministic-serialize, ValueError on strict failure) apply identically. Document this in `analyze.py`'s docstring: "Cache_key prediction MUST share `_resolve_chunk_value` with runtime; never inline."
  - Composes: parser → cross-workflow walker → token estimation per node → confidence labeling per DD#34 (4-level per-call, 3-level aggregate, with coverage detail) → padding advisor → recommended-actions ordering (impact descending).
  - Returns a `CacheAnalysis` dataclass with: summary fields, per-call rows, recommended actions, suggested cache blocks (when greenfield), cross-workflow findings, warnings list, notes.

- `src/pflow/core/cache_analysis/summarize.py` (new):
  - `summarize(workflow, parameters) -> Diagnostic | None` — one-line `Severity.INFO` Diagnostic (`id="cache.opportunities-available"`) for the dry-run nudge per spec "—dry-run Cache Nudge". `None` when no actionable opportunities.

- `src/pflow/core/cache_analysis/render_text.py` (new):
  - `render(analysis: CacheAnalysis) -> str` — markdown-formatted text output per spec "Output Format — Text" (the four modes: greenfield, steady-state, already-optimal, from-trace). Section ordering and per-call rendering rules per spec.
  - The cost-degradation contract (partial cost, unavailable models) per spec "Cost-estimate degradation for unknown models" — mirror Task 158's tri-state pattern (`pricing_available: bool`, `partial_cost_usd`, `unavailable_models`).

- `src/pflow/core/cache_analysis/render_json.py` (new):
  - `render_json(analysis: CacheAnalysis) -> dict` — JSON shape per spec "Output Format — JSON". Empty arrays for `cross_workflow.*` (always present in JSON).
  - **JSON format version constants** (Round 4 high-value fix #3 — locks consumer evolution policy):
    ```python
    # In src/pflow/core/cache_analysis/__init__.py (sibling of warning_catalog):
    JSON_FORMAT_VERSION: Final[str] = "1.0"
    JSON_FORMAT_VERSION_MAJOR: Final[str] = "1"  # consumer rule: accept any "1.x", reject "2.x"
    ```
    `render_json` writes `format_version: JSON_FORMAT_VERSION` (NOT a literal `"1.0"` — read from the constant so a future minor bump touches one place).
  - **Consumer rule (locked in F3.2 docstring)**: agents matching `format_version` should use `format_version.startswith("1.")` (NOT `== "1.0"`). Major version bump (`2.x`) signals a breaking change; agents pinned to v1 should refuse to consume. This mirrors the trace 2.x policy at `trace_report.py:463` (`format_version.startswith("2.")`). Without this contract, agents pinning `== "1.0"` break silently on the first additive minor bump — which the analyzer evolution will trigger as `recommended_actions` schema grows.
  - **Test in `tests/test_cli/test_analyze_cache_golden.py`** asserts both: (a) `result["format_version"] == JSON_FORMAT_VERSION` (current literal); (b) `result["format_version"].startswith(JSON_FORMAT_VERSION_MAJOR + ".")` (consumer-rule contract — would still pass on a future "1.1" bump). The dual assertion locks the constant and the policy.

## Tests

- `tests/test_core/test_cache_analysis_analyze.py` (new):
  - Each of the four output modes runs cleanly on a synthetic minimal workflow.
  - Confidence labels are correct given the trace/memo/estimator/heuristic mix.
  - Recommended actions are sorted by impact descending.
  - **Cost-degradation tri-state contract** (Suggestion 26 — explicit per-state JSON shape, locks the contract for agents):

    | Pricing state | `summary.current_cost_per_run_usd` | `summary.partial_cost_usd` | `summary.unavailable_models` | text rendering |
    |---|---|---|---|---|
    | All models priced (normal) | float (e.g. `2.18`) | `false` | `[]` | `~$2.18` |
    | Some models unpriced (partial) | float (sum of priced calls only, e.g. `0.84`) | `true` | `["ollama/llama3.2:8b", ...]` | `~$0.84 (partial — N of M nodes use unpriced models)` with footer `Unpriced models: ollama/llama3.2:8b, ...` |
    | All models unpriced | `null` | `true` | `[<all model strings>]` | `unavailable` (NOT `$0.00`, NOT `null` rendered as text); SUMMARY explicitly states "All node models lack pricing data; structural recommendations are still actionable but cost figures are unavailable." |

    Same contract applies to `optimized_cost_per_run_usd`, `rerun_cost_per_run_usd`, and `recommended_actions[].estimated_savings_usd` (becomes `null` when the action's affected nodes use unpriced models). Confidence label is unaffected by cost degradation — it tracks token-source fidelity, not dollar fidelity.

    Test parametrized over the three states. **Never crashes, never silently shows `$0.00` for unpriced models.**
  - Cost degradation: unknown model produces partial cost output; never `$0.00`. Tested per the table above.

- `tests/test_cli/test_analyze_cache_golden.py` (new) — mirrors `test_mermaid_golden.py`:
  - Parametrized cases for each of the 4 modes + a 5th for cost-degradation + 1 from-trace = 10 files (4 × 2 formats text/JSON + 2 specials). Synthetic minimal workflows under `tests/test_cli/golden_analyze_cache/`. Byte-exact equality. Failure message embeds the regen command.
  - **Pricing-pin strategy** (review-test-fidelity W1): `MockLLMClient.set_response(..., cost_usd=...)` only pins runtime cost — but the analyzer uses `litellm.completion_cost()` against `litellm.model_cost`, a different code path. Pin BOTH:
    - Runtime side: `MockLLMClient.set_response(cost_usd=...)`.
    - Analyzer side: `monkeypatch.setattr("litellm.completion_cost", lambda *a, **kw: <pinned value>)` in test setup. Without this, golden cost values drift whenever LiteLLM updates `model_cost`, even with the mock pinned.
    - **`token_counter` does NOT need pinning.** Verified empirically: `litellm.token_counter(model="claude-sonnet-4-5", text="hello world test")` returns 3 deterministically; on unknown models it falls back to a default tokenizer (returns a count, doesn't raise) — see implementation log; the same input always produces the same count. No third pinning site needed.
  - Per-call rendering rules tested with explicit byte-equality assertions (review-agent-ux 12):
    - Default-hide-clean: a 23-row workflow hides the top 12 clean rows. Explicit `expected_text` assertion.
    - "Hidden: N nodes at ≥80% projected cache ratio with no warnings (rerun with --all-rows)." — exact text matched.
    - `--all-rows` flag: rows sorted by token volume descending. Explicit ordering test.
    - JSON `format_version: "1.0"` field present and exactly the string `"1.0"` (catches `"1"` int regression).
    - JSON empty-array contract (review-agent-ux 5): `cross_workflow.rename_detections`, `cross_workflow.prose_mismatches`, `cross_workflow.value_flow_opportunities` are PRESENT as `[]` (not absent, not `null`) when no findings exist.

- **Per-warning-ID coverage** (Suggestion 30 — `tests/test_core/test_cache_analysis_per_id_emission.py`, new):
  - For every warning ID in the catalog (10 total), exists at least one synthetic minimal workflow under `tests/test_cli/golden_analyze_cache/per_id/{cache_id}/` that triggers exactly that ID.
  - Test asserts: (a) running `analyze-cache` on the synthetic workflow emits the expected ID; (b) the emitted Diagnostic carries every `required_context_keys` key; (c) the rendered text output (golden file) matches byte-for-byte. Catches the case where a catalog ID is in the catalog but no production code path actually emits it (dead-code regression).
  - Coverage assertion at module level: `set(catalog.keys()) == set(scanned synthetic workflow directories)` — fails CI if a new ID is added without a synthetic workflow.

- **2.0.0-skip info note byte-equality** (Suggestion 14): synthetic test where `~/.pflow/debug/` contains 2 traces matching the workflow path, both 2.0.0. Run `analyze-cache` (no `--from-trace`). Assert the `notes` array contains exactly: `"Found 2 2.0.0 traces matching this workflow but skipped (auto-load requires 2.1.0). Use --from-trace <path> to load a specific trace, or --no-trace-autoload to disable auto-loading."` (byte-equality on the format string).

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
  - Click command `analyze-cache <workflow-path> [inputs...]` with flags `--format=text|json` (default `text`), `--from-trace <path>` (explicit trace override), `--no-trace-autoload` (opt out of auto-loading an existing trace), `--all-rows` (per-call rendering rule per spec).
  - **Flag-name rationale**: `--no-trace-autoload` (NOT `--no-trace`) — `pflow run --no-trace` already exists at `cli/commands/run.py:802` with the meaning "disable trace SAVING during execution." Reusing the same word on `analyze-cache` would collide. The longer name disambiguates: `analyze-cache --no-trace-autoload` clearly says "don't auto-load an existing trace for analysis." Document the divergence in F3.1 + the agent-facing guide.
  - Calls `cache_analysis.analyze(workflow, params)`; renders via `render_text` or `render_json`.
  - Inputs are optional per DD#35.
  - **Exit code contract** (Suggestion 20 — locks the agent-facing contract for trace-load failures and other error states):

    | Condition | Exit code | Output |
    |---|---|---|
    | Successful analysis (any output mode) | `0` | Full output (text or JSON). Warnings of ANY severity (including ERROR-severity validator findings like `cache.order-mismatch`, `cache.invalid-on-non-llm`) DO NOT change exit code — analytical findings are advisory per DD#36. The findings appear in the `warnings[]` JSON array (with their severity preserved) and in the text output's "## All warnings" section. |
    | Workflow path unparseable (`MarkdownParseError`) | non-zero | Existing `pflow run` validation diagnostic via stderr. Hard-fail: parser cannot produce IR, so analysis cannot run. |
    | Workflow validation fails — structural failures upstream of `validate_data_flow` (schema errors, malformed IR) — that prevent `compile_workflow` from producing a valid IR | non-zero | Existing diagnostic pipeline via stderr. **Cache validation findings (`cache.order-mismatch`, `cache.invalid-on-non-llm`, `cache.unused-chunk`) do NOT take this path** — they're emitted by `_validate_cache_block` which runs alongside analysis; their presence does not abort the analyzer. Compile/parse errors that prevent IR construction DO take this path. |
    | `--from-trace <path>` where path doesn't exist | non-zero | Validation-error-style diagnostic: `"Trace file not found: <path>"` + suggestion `"Check the path. Auto-load reads from ~/.pflow/debug/; for explicit override pass an existing trace JSON."`. |
    | `--from-trace <path>` where the file exists but isn't valid JSON OR missing `format_version` | non-zero | `"Trace file <path> is not a valid pflow trace (JSON parse error / missing format_version field)."` |
    | `--from-trace <path>` where file is a 2.0.0 trace | `0` | Loads successfully (works on both 2.0.0 and 2.1.0 — see DD#34). Mode-4 output WITHOUT discrepancy analysis (per-call `data_source` falls to `memo` / `estimator` / `heuristic`); a single info note explains the limitation. |
    | Auto-load found a 2.0.0 trace and skipped it | `0` | Info note added to `notes` array (see F2 byte-equality test). Analysis proceeds without trace data. |
    | Conflicting `--from-trace <path>` AND `--no-trace-autoload` | non-zero | Click validation error: `"--from-trace and --no-trace-autoload are mutually exclusive."` |
    | All node models unpriced (cost-degradation tri-state) | `0` | Cost rendering = `unavailable`; structural recommendations still emitted. NOT a failure. |
    | Unexpected analyzer crash (bug, OSError, malformed-trace-bypassing-validation, internal exception) | non-zero | Stack trace via stderr through the existing `pflow run` exception pipeline. NEVER emit empty-but-valid JSON for an internal failure — that's a silent-failure attractor. The CLI command implementation MUST NOT have a top-level `except Exception: pass` or any catch-all that swallows internal errors into a partial result. Test (per Tier 2): monkeypatch `analyze()` to raise `RuntimeError("synthetic")`; assert non-zero exit and no JSON written to stdout. |

    **Policy rationale**: `analyze-cache` is advisory by design (per DD#36 — analytical tier, not a gate). Agents that want to gate on findings should inspect the JSON's `warnings[]` array and filter by `severity == "ERROR"` themselves rather than rely on the exit code. This separation lets agents distinguish "I can't even parse this workflow" (exit non-zero, not actionable for cache analysis) from "the workflow is valid but has cache configuration mistakes" (exit 0, actionable findings in `warnings[]`). The same policy applies to MCP `analyze_cache` — ERROR-severity findings are returned in the JSON, not raised as MCP exceptions; internal analyzer crashes in MCP mode propagate as MCP errors (NOT silent empty results).

- `src/pflow/cli/main.py`:
  - Register the new command via the existing command-discovery mechanism. Mirror `pflow visualize` or `pflow describe` registration at `cli/main.py:121–141` (the actual `cli.add_command(...)` registration pattern). Earlier draft referenced `pflow plan` — that command does not exist; `--dry-run` is a flag on `pflow run`, not a top-level command.

### Tests

- `tests/test_cli/test_analyze_cache.py` (new): exit code (parametrized per the F3.1 contract table — all 9 conditions), all four output modes, per-call rendering rules (default-hide-clean, `--all-rows`), padding-advisory sensitivity floor, missing-pricing degradation.
- `tests/test_cli/test_analyze_cache_from_trace.py` (new): 2.1.0 fields available; 2.0.0 graceful fallback (an info message, no crash); `--from-trace` non-existent path produces non-zero exit with the locked diagnostic message; `--from-trace path` AND `--no-trace-autoload` produces a Click validation error.

## F3.2 — MCP parity

### Files

- `src/pflow/mcp_server/services/execution_service.py`:
  - Add `analyze_cache(workflow, parameters) -> dict` mirroring `plan_workflow` (line 301) verbatim. Same exception handling: `WorkflowNotFoundError` (with similar_names hint), `WorkflowValidationError`, `CompilationError`, `MarkdownParseError`, generic.
  - Returns `cache_analysis.render_json(analyze(...))` — the same JSON shape as CLI `--format=json`.

- `src/pflow/mcp_server/tools/execution_tools.py`:
  - Add `@mcp.tool() async def analyze_cache(...)` (line ~178, after `plan_workflow`). Async wrapper per the file's pattern: `result = await asyncio.to_thread(_sync_op)`.
  - Add to `__all__` at line 353.
  - **Tool docstring contract** (review-agent-ux 12): the docstring is the agent-facing schema. It MUST enumerate:
    - The top-level JSON keys returned: `format_version` (current literal `"1.0"`; consumers should use `format_version.startswith("1.")` — accept any minor `1.x`, reject major `2.x`), `workflow_path`, `analyzed_at`, `estimate_confidence` (one of `low_no_data` / `medium_from_memo` / `high_from_trace`), `trace_path`, `summary`, `recommended_actions`, `suggested_blocks`, `per_call`, `cross_workflow`, `warnings`, `notes`.
    - **Version policy paragraph** (verbatim in docstring): *"`format_version` follows semver-ish: minor bumps (`1.0` → `1.1`) are additive (new fields, new warning IDs) — consumers tolerant via `format_version.startswith('1.')` continue to work. Major bumps (`1.x` → `2.x`) are breaking changes; pinned consumers refuse to consume. Mirrors the trace 2.x consumer policy."*
    - The closed catalog of `cache.*` warning IDs that may appear in `warnings[].id` (the docstring lists every id in `CACHE_WARNING_CATALOG.keys()` verbatim — implementing agent generates the docstring section programmatically from the catalog OR maintains it in sync; either way, the test below verifies sync).
    - The cost-degradation tri-state behavior (per the F2 table — agents must handle `summary.partial_cost_usd: bool` and possible `null` cost fields).
    - The four-value `per_call[].data_source`: `trace` / `memo` / `estimator` / `heuristic`.
  - Test in `test_analyze_cache_tool.py` asserts the docstring contains: (a) the literal string `"format_version"`, (b) **every id in `CACHE_WARNING_CATALOG.keys()`** (iterate at test time — DO NOT hardcode "10 / 11 / 12"; computed from the catalog so adding entries doesn't drift the test), (c) the literal string `"partial_cost_usd"`, (d) the literal string `"data_source"`. Catches docstring-rot regressions AND catalog-count drift.

### Tests

- `tests/test_mcp_server/test_analyze_cache_tool.py` (new):
  - MCP tool returns the same JSON as CLI `--format=json` for the same workflow + parameters. Stateless pattern (fresh service instance per call).
  - **JSON round-trip** (review-test-fidelity 12): `json.loads(json.dumps(mcp_result))` produces a dict equal to `mcp_result`. Catches non-JSON-serializable values (Path objects, sets, etc.) leaking into the response.
  - **Same-diagnostic-as-CLI** for `cache.order-mismatch` (review-feature-interactions C5): MCP `execute_workflow` on a workflow with `cache.order-mismatch` produces the SAME diagnostic structure (id, severity, message, suggestions) as `pflow run` on the same workflow. Locks the validation-reach contract.
  - Docstring contract assertions (per F3.2 docstring requirements above).

## F3.3 — `--dry-run` cache nudge

### Files

- `src/pflow/execution/plan.py` (or wherever `runner.plan()` builds the `Plan`):
  - After the existing plan construction, call `cache_analysis.summarize(workflow, parameters)` → if it returns a Diagnostic, append to `plan.diagnostics`.
  - Per DD#36, `--dry-run` runs the **full analytical pass** under the hood — `summarize` calls `analyze` internally.
  - Per spec "—dry-run Cache Nudge", the existing plan-formatter loop at `plan_formatter.py:139–142` already renders the diagnostic — no formatter code change needed (the loop iterates `plan.diagnostics` and calls `format_diagnostic`).

### Tests

- `tests/test_execution/test_plan_cache_nudge.py` (new):
  - A workflow with cache opportunities produces a `--dry-run` Plan whose `diagnostics` includes `cache.opportunities-available` with the locked text format from spec.
  - A workflow without opportunities → no nudge (silent). Test asserts `not any(d.id == "cache.opportunities-available" for d in plan.diagnostics)` — explicit negative assertion, not just absence of any string match.
  - The nudge appears in both text and JSON dry-run output.
  - `summarize.py` builds the message via a single locked format string (in `summarize.py`, not constructed at the call site). Pluralization is explicit: `"{n} design opportunit{y_or_ies}"` where `y_or_ies = "y" if n == 1 else "ies"`. Test both n=1 and n=4.
  - **Byte-equality on the rendered nudge** (Suggestion 28): the rendered text payload (after `format_diagnostic`) matches exactly:
    ```
    ℹ Cache: 4 design opportunities available (estimated -$1.34/run, -61%).
      Run 'pflow analyze-cache' for details.
    ```
    Including the leading `ℹ` glyph, the period after `%)`, the exact `-$1.34/run` sign convention, and the indented suggestion line. Catches the regression where someone changes pluralization or punctuation. n=1 variant: `Cache: 1 design opportunity available (estimated -$0.10/run, -5%).`
  - **Three-state at MCP/CLI/JSON-trace layer** (High-Priority 19): integration test parametrized over the three `prompt_cache:` states (absent / `[]` / non-empty). For each state, run via:
    1. `WorkflowRunner` directly (CLI path) → assert plan output equality between absent and `[]`; non-empty differs.
    2. MCP `execute_workflow` → assert response JSON equality between absent and `[]`; non-empty differs.
    3. JSON trace 2.1.0 file content → assert `trace["events"][i]["llm_call"]` keyset equality (no `cache_key`, `cache_source`, `cache_age_sec` in absent/`[]`; present in non-empty).
    Locks the three-state invariant at every agent-facing surface, not just hash + rendering.

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

The recommended sequence: B1 → B2 → B3 → C1/C2/C3 (parallel after B3) → D (parallel with C after B3) → E → F1 → F2 → F3 → G. F gates on B+C+E. G wraps. Each sub-phase is a PR-sized chunk. Paid spikes (Gemini cache_control, OpenAI routing, Anthropic per-TTL pricing) run before B1 — they are not phases in this plan.

The single hard gate: **B3's regression test (no-`prompt_cache` workflows produce identical hashes pre/post task) must pass before any subsequent phase ships.** This is the silent-stale-cache guard per DD#19.

# Spike contingencies (consult progress log §33+ before B1.1)

Three pre-authorized paid spikes (~$0.30 total) run BEFORE B1.1 per the agent-handoff. Their outcomes either CONFIRM encoded plan decisions (no plan update) or CONTRADICT them (plan update required before B1.1). This subsection maps each spike to the encoded decision(s) it tests, so the implementing agent can read the §33+ outcome and know exactly which plan section(s) need revision (Round 4 high-value fix #5 — eliminates the "ran the spike, missed the contradicting plan section" class).

| Spike | Encoded plan decision | If outcome contradicts, update |
|---|---|---|
| **Gemini explicit `cache_control` verification** (C0 — Phase C entry) | Plan C2 emits `cache_control: {"type": "ephemeral", "ttl": "300s"\|"3600s"}` for Gemini and trusts LiteLLM's translation to fire `cachedContents`. | If `cache_creation_input_tokens` does NOT increment on call 1 / `cache_read_input_tokens` does NOT increment on call 2: ship C2 anyway with a documented info-note in `analyze-cache` Gemini output (per DD#37 / handoff). Add the info-note text to F2 `analyze.py` Gemini-detection branch. NO change to C2's emission code. |
| **Gemini multi-marker behavior** (C0 Scenario B) | Plan C2 emits BOTH a system-cache marker (declared `prompt_cache:`) AND a user-message-prefix marker (auto-batch from D.1) on Gemini, accepting that Gemini's `cachedContents` collapses to the latest. | If Gemini API REJECTS the request (rather than silently collapsing): D.1 needs to filter the auto-batch marker on Gemini-target workflows. Update D.1 with a Gemini-specific gate `if detect_provider(model).name == "gemini" and prep_res.get("system_blocks"): skip user_message_blocks marker insertion`. Flag as v1.x follow-up `cache.gemini-multi-marker`. |
| **OpenAI `prompt_cache_key` parallel-batch routing** (D — Phase D) | Plan C3 + D.2 emit `prompt_cache_key` as `md5(rendered_cache_content)` and assume OpenAI's sticky routing serializes parallel writes (with documented 15 RPM degradation per Round 4 fix). | If 4-8 parallel calls with same key DON'T cluster on one backend (LiteLLM/OpenAI randomizes): document degraded hit rate; emit `prompt_cache_key` regardless (it never hurts). Update G.2 `pflow guide caching` OpenAI section with the empirical finding. NO change to C3 emission code. |
| **Anthropic per-TTL pricing precision via `litellm.completion_cost`** (E — Phase E entry, only when 1h TTL ships) | Plan E.1 trusts `litellm.completion_cost()` to distinguish 1.25× (5-min TTL) vs 2× (1h TTL) cache writes; cost reporting unchanged. | If LiteLLM does NOT distinguish: add a `_normalize` override in `llm_client.py:776–784` that computes write cost from raw `cache_creation_input_tokens` × per-provider rate and overrides `cost_usd` for cache-write events. This is a Phase E plan update; the override sits next to existing cost normalization. |

If any spike outcome triggers a plan update, document the change in progress log §33+ alongside the spike result, then update the cross-referenced plan section BEFORE B1.1 patches start.

# Open hedged claims still pending plan-internal verification

These are documented above but listed here for the implementing agent's checklist:

- **B1.1** — `Diagnostic.id` field doesn't break existing tests. Verification: full `make test` after the patch.
- **B2.1** — `pflow save` round-trip preserves `## Cache` byte-for-byte. Verification: round-trip test in `test_cache_block_parser.py`.
- **B2.3** — `WorkflowExecutor._compiled_workflow_cache` interaction with sub-workflow `## Cache`. Verification: integration test where the same sub-workflow is invoked twice with different parent state.
- **D.1** — `list | str` shape for older workflow inputs/outputs. Verification: `test_prompt_cache_value_types.py` with list/dict/scalar resolved values.

If any verification fails, surface to the user before continuing.

# Summary of plan corrections from review

Applied to the plan from the code-review passes (Round 1 + Round 2 + Round 3 + Round 4):

**Round 4 fixes (applied this session — Critical + High-Priority + selected Tier-3, after reading actual code to validate every pseudo-code reference)**:

Critical pseudo-code corrections (Round 3 introduced these by writing pseudo-code without reading the target functions):
- `_resolve_chunk_value` pseudo-code referenced `TemplateResolutionError` — verified does NOT exist in pflow. `TemplateResolver.resolve_template` raises plain `ValueError` (with `_pflow_partial_resolutions` + `_pflow_template_diagnostic` annotations). Helper now lets `ValueError` propagate; documented that `plan_node.py:57` already catches `except ValueError` per existing precedent.
- `_resolve_chunk_value` pseudo-code referenced `node_state.ABSENT` — verified actual symbol is `NodeStatus.ABSENT` per `node_state.py:25`. Pseudo-code now imports `from pflow.runtime.node_state import NodeStatus, get_node_status` and compares `== NodeStatus.ABSENT`.
- Pseudo-code had dead `if upstream_node is not None` check — verified `extract_root_node_id` always returns `str` (never `None`) per `template_resolver.py:212`. Dropped the dead check.
- D.2 prewarm pseudo-code treated `process_item`'s return as a dict — verified actual return is 5-tuple `(idx, result, error, duration_ms, buffered_events)` per `batch_executor.py:589`. Rewrote D.2 with correct destructure mirroring `_collect_parallel_results:490-522`. Extended `_collect_parallel_results` signature with `*, initial_completed: int = 0, total: int | None = None` kwargs (backward-compatible) so the prewarm-split can pass `initial_completed=1, total=len(items)` and avoid duplicating per-future processing.

V5 fix (Schema vs `_validate_cache_block` shape redundancy — top-10% pattern: one rule per error condition):
- Decision: schema is single source for shape (`prompt_cache: list[str]`, `prewarm: bool`, `cache.ttl` enum). `_validate_cache_block` does ONLY semantics — cross-references, ordering, batch-scoped rejection, non-LLM-type rejection.
- Compile-path defense: `_validate_cache_block` emits `logger.warning` and skips nodes with malformed `prompt_cache`/`prewarm` shape; deeper compile-time error (NodeConfig construction) surfaces normally; NO Diagnostic for shape errors from `_validate_cache_block`.
- Removed the obsolete "two diagnostics that dedupe" test (was based on the misanalysis); replaced with explicit "shape-malformed `prompt_cache`" test asserting validator path emits ONE schema diagnostic AND compile path skips silently with logger.warning.

V6 fix (Multi-field rejection collapse — top-10% pattern: one diagnostic per [rule, location], multiple offenses listed):
- `cache.invalid-on-non-llm` now emits ONE Diagnostic per offending node with `context["invalid_fields"]: list[str]` listing ALL fields. Message lists fields CSV-formatted. Catalog row updated. Emission contract documented inline. Identity tuple already handles dedup correctly under this shape.
- A node with both `prompt_cache:` AND `prewarm:` now produces ONE error (was: two emissions collapsed via id-dedup, hiding one offense).

Helper dispatch refinements:
- `make_diagnostic` now merges `node_id` into the format dict (`{**context_kwargs, "node_id": node_id}`) before formatting templates — `{node_id}` placeholders in action templates resolve correctly.
- `cache.discrepancy` unknown-enum fallback emits `logger.warning(...)` AND surfaces the rejected enum value in the rendered message (template now includes `{root_cause!r}`). Agents see what was rejected, not just "unknown."
- `context["root_cause"]` preserves the original (possibly-unknown) enum value for downstream debugging.

Catalog count drift defense:
- Defined `EXPECTED_CATALOG_COUNT: int = len(CACHE_WARNING_CATALOG)` constant next to the catalog. ALL count-references read this constant. Tests iterate `CACHE_WARNING_CATALOG.keys()` rather than hardcoding numbers. Adding a new catalog entry requires zero count-update edits across the plan; constant is auto-derived.
- F3.2 MCP docstring contract test asserts every id in `CACHE_WARNING_CATALOG.keys()` appears in the docstring (computed at test time, not hardcoded "10/11/12").

Test mechanism corrections:
- D.2 prewarm test locks `threading.Barrier(parties=N-1, timeout=5.0)` mechanism — item[0] does NOT enter the barrier; items[1:] do. If item[0] is incorrectly submitted to the pool, it deadlocks (timeout fails the test). Replaces the vague "single-threaded mock or mock time.sleep."
- Divergence-injection test uses per-site `monkeypatch.setattr(...)` on import bindings (NOT `inspect.stack` / thread-local — both fragile). Locks the contract that both call sites import via `from ... import _resolve_chunk_value` (creating a local binding).
- B3.4 in-memory mutation test uses `compile_workflow(ir_dict, registry)` direct call to bypass `WorkflowExecutor._compiled_workflow_cache` (keyed by resolved-path; would return stale compile on second call with same path).
- B3.4 ABSENT-case fixture pattern made concrete (router/branch_a/b_producer/branch_c/llm_target) with explicit precondition assertion `get_node_status(shared, "b_producer") == NodeStatus.ABSENT` — locks the test isn't passing for the wrong reason (structural failure vs runtime branch absence).
- B3.4 type:llm positive-control row added to parametrize — locks the rule doesn't reject everything.
- Cache-invalid parametrize uses minimal-valid params per node type (`shell` requires `command:`; `http` requires `url:`; etc.) so the cache check is reachable.
- Memo HIT test drops the `prep`-spy assertion (implementation-detail testing); behavior-level (a)+(b)+(c) trio is sufficient and refactor-stable.
- Function-scoped `MockLLMClient` fixture for call-count baseline.

Tier 2 hardening:
- F3.1 exit code table adds 10th row "unexpected analyzer crash → non-zero exit" + analyzer NEVER emits empty-but-valid JSON for internal failures (silent-failure attractor defense).
- F2 auto-load scanner: `logger.debug` per unparseable trace file + info note in `analysis.notes` when ≥1 skip fired.
- F2 `analyze.py` predicted-cache_key MUST use shared `_resolve_chunk_value` helper (NOT inline) — locks runtime↔analyzer resolution parity for `cache.discrepancy` accuracy.
- LLMNode Interface docstring + `nodes/llm/README.md`: enumerate new `llm_usage` sub-keys (`cache_key`, `cache_source`, `cache_age_sec`, `cache_chunks_skipped`) — drives registry → template_validation pickup so `${node.llm_usage.cache_chunks_skipped}` references are valid at parse time.
- `_EMPTY_CACHE_RENDER` placement: explicit in `engine.py` (where consumed) — NOT in types.py (YAGNI).
- `_validate_cache_block` empty/None `type` handling: skip the cache check when `type` is missing/empty (let deeper structural error surface; no "type: None" rendered to user).
- Tests with literal `"2.0.0"` enumerated explicitly (bump `test_workflow_trace.py:335`; keep `test_trace_integration.py:170`, `test_trace_report.py:43, :1295` for legacy-fixture compat).
- ClaudeCodeNode exclusion docstring rewritten allowlist-style (rationale: SDK-side cache vs pflow memo; future LLM-producing node types must extend the gate).

`_CHUNK_ABSENT` sentinel hardening:
- `__repr__` and `__str__` raise `TypeError` on accidental serialization — defends against the silent-stale-cache class where forgotten-filter callers would inject memory-address-flavored strings into the hash. 4 LOC of defense.

Process improvement (the meta-fix):
- All Round 4 pseudo-code is verified against actual code shapes via direct reads (`batch_executor.py:524-611`, `node_state.py:25-59`, `template_resolver.py:198-212`, `plan_node.py:35-68`, `diagnostic.py:69-92`). Future rounds: read the target function before writing pseudo-code that depends on its signature.

**Round 4 high-value fixes (1-5, applied after the V5/V6/symbol corrections — top-10% / simplest-final-code lens)**:

1. **`_resolve_static_prefix_for_cache` companion helper** locks byte-identical resolution across ALL three cache paths (chunk hash via B3.3, chunk message via C1.2, static-prefix auto-batch via D.1 — and analyzer prediction via F2). Prevents the silent cross-mode cache miss where `${X}` resolving to `{"text": "abc"}` produces `'{"text":"abc"}'` (canonical JSON) in chunk paths but `"{'text': 'abc'}"` (Python repr via `TemplateResolver.resolve_template`'s default `str()`) in static-prefix path. The new helper substitutes via `_deterministic_serialize` per ref. B3.4 cross-helper byte-identity test added.

2. **`cache.discrepancy` structured `context["root_cause_action"]` payload** makes mode-4 from-trace agent-actionable WITHOUT prose parsing. Per-cause typed payload schema (`CACHE_DISCREPANCY_ACTION_PAYLOAD_KEYS`) sits next to the prose template map. Agents dispatch on `context["root_cause_action"]["suggested_ttl"]` etc. instead of regex-extracting from prose. Suggestions list still renders prose for human display. Round 4 dispatch tests extended to assert both prose AND structured payload per cause.

3. **JSON `format_version` evolution policy + constants** (`JSON_FORMAT_VERSION`, `JSON_FORMAT_VERSION_MAJOR`). Locks consumer rule: `format_version.startswith("1.")` (NOT `== "1.0"`). Mirrors trace 2.x policy at `trace_report.py:463`. F3.2 docstring includes the version-policy paragraph verbatim. Test asserts both the literal AND the consumer-rule prefix-match (would still pass on a future "1.1" bump).

4. **Compile-path `_validate_cache_block` defensive isinstance guards enumerated**: explicit per-shape guards for `prompt_cache` (must be `list[str]`), `prewarm` (must be `bool`, NOT `int` since `bool` subclasses `int`), top-level `cache` block (dict with required keys). Each guard emits `logger.warning` and `continue` (per-node) or `return` (top-level cache malformed). Test asserts ZERO Diagnostics from `_validate_cache_block` on shape-malformed input + exactly ONE `logger.warning` per malformed shape.

5. **Spike contingencies subsection** (new section before "Open hedged claims"). Maps each pre-authorized spike to the encoded plan decision it tests. Each row: spike name → encoded decision → if-outcome-contradicts action. Eliminates the "ran the spike in §33+, missed the contradicting plan section" regression class. Documents fallback paths for Gemini explicit cache_control, Gemini multi-marker behavior, OpenAI `prompt_cache_key` parallel routing, Anthropic per-TTL pricing precision.

**Round 3 fixes (previous session — Critical + High-Priority + selected Medium):**

Critical:
- D.1 line 718 + D.2 line 759 used unsafe `shared.get(K, {}).get(...)` pattern, hitting the exact `None.get()` AttributeError trap the architectural backbone documents. Replaced with canonical `(shared.get(K) or {}).get(...)` pattern at both sites.
- F1 catalog `cache.discrepancy` row was internally unresolvable — `suggestions_template = ["{root_cause_action}"]` referenced a key not in `required_context_keys`, would `KeyError` on every emission. Fix: added `CACHE_DISCREPANCY_ACTION_TEMPLATES` dispatch map + `CACHE_DISCREPANCY_REQUIRED_CONTEXT` per-root_cause additional-key map; helper dispatches on `context["root_cause"]` to render the correct action template; unknown enum falls back to `"unknown"` row.
- B2.2 falsely claimed validator step 8 catches `prompt_cache:`/`prewarm:` on non-LLM nodes. Verified at `validator.py:600`: step 8 iterates `node["params"]` only; B2.1 extracts to top-level. Fix: added `cache.invalid-on-non-llm` ERROR-tier rejection inside `_validate_cache_block` (B2.3) walking top-level node keys; added 11th catalog entry. B2.2's hint claim removed; rejection now emitted from cache validation locus.
- Hash-vs-prep ABSENT branch handling: B3.3 only specified happy-path; LLMNode.prep (C1.2) skipped ABSENT chunks but plan_node.render-for-hash didn't. Silent-stale-cache class. Fix: shared `_resolve_chunk_value` helper returns `_CHUNK_ABSENT` sentinel; both call sites filter on it BEFORE building output; B3.4 adds explicit ABSENT-case byte-equivalence test + divergence-injection variant (anti-tautology).
- D.2 prewarm execution was structurally vague ("execute item[0] sequentially first"). Fix: concrete pseudo-code algorithm specifying `process_item` (sole single-item executor), `results[0]` direct write before pool dispatch, `future_to_idx` map for indices ≥ 1, error_handling matrix locked, item[0] excluded from `as_completed`, progress-event drain semantics, `_pre_warm_compile_cache` interaction.
- `cache_chunks_skipped` lost on `_call_llm` error path: `prep_res` carries it but `post()` doesn't run on deterministic LLMCallError or template-error short-circuit. Fix: error-output builder (`_error_dict_from_exception`) ALSO copies `cache_chunks_skipped`; memo HIT round-trip via persisted `llm_usage`; explicit cross-layer co-edit notes in C1.2 + E.1.
- E.1 strict-assert `workflow_path is not None` would fire 40+ times across test instantiations. Fix: dropped the assert; added dedicated production-path integration test (`test_workflow_path_set_in_production_runs`) covering file/inline/sub-workflow shapes.

High-Priority:
- `analyze-cache --no-trace` collided with existing `pflow run --no-trace` (different semantics). Renamed to `--no-trace-autoload`; updated F3.1 exit code table; updated F2 byte-equality info-note string.
- `storage_mode: shared` × `## Cache` parallel batch save/restore non-deterministic interleaving documented as v1 limitation in `runtime/CLAUDE.md` reserved-key entry. Lyrics-generator doesn't use the combination, so v1 documents rather than tests.
- OpenAI `prompt_cache_key` × batch_size > 15 RPM soft cap documented as known limitation; v1 relies on retry layer; deferred to v1.x as `cache.openai-batch-clamp` follow-up. Added to G.2 caching guide note.
- Hash baseline cannot include post-task fields (main HEAD doesn't parse `prompt_cache:`). Fix: clarified that B3 baseline covers bare shapes; B3.4 adds in-memory mutation test (load baseline workflow → mutate IR to add `prompt_cache: []` → recompile → assert hash-equality with absent-baseline; mutate to `[chunk]` → assert hash differs). Closes the DD#19 byte-identity invariant verification gap that the baseline alone cannot.
- F3.1 exit code policy: `analyze-cache` is advisory per DD#36 — ERROR-severity validator findings (`cache.order-mismatch`, `cache.invalid-on-non-llm`) appear in `warnings[]` array with exit 0; only IR-construction failures (parse/schema/structural) exit non-zero. Same policy applies to MCP `analyze_cache`.
- E.1 `LLMNode.post()` patch list explicitly includes `cache_chunks_skipped` cross-layer co-edit (was mentioned in C1.2 but not threaded into E.1).
- D.1 `user_message_blocks` consumer step missing — `_call_llm` not told to thread the kwarg through. Fix: explicit step in D.1 specifying `complete()` signature widening with `user_message_blocks` kwarg + `_build_messages` dispatch branch.
- Engine save/restore simplified: dropped outer try/except (dead code; mirrors `__trace_collector__` precedent). Hoisted `_EMPTY_CACHE_RENDER = MappingProxyType({})` to module level (eliminates per-restore allocation in deeply-nested sub-workflow runs).

Selected Mediums:
- B2.3 sub-workflow batch concurrency test mechanism made concrete: `monkeypatch.setattr` on `_build_cache_render_dict` capturing `(threading.get_ident(), id(workflow.cache_block))` to a thread-safe list; assertions on threadid divergence + cache_block id-equality + frozen-mutation invariant.
- ClaudeCodeNode intentionally excluded from `_should_write_cache_metadata` gate (its `cache_creation/read_input_tokens` come from Claude SDK, not pflow memo); documented in helper docstring; test asserts `cache_key`/`cache_source`/`cache_age_sec` absent on ClaudeCodeNode memo paths.
- `cache.prewarm-no-prefix` added to F1 catalog as 12th entry (was referenced by D.1 but not in catalog). Total catalog: 12 entries (was 10 in spec; round-3 added `cache.invalid-on-non-llm` and `cache.prewarm-no-prefix` alongside `cache.discrepancy` from round-2). F2 per-warning-ID coverage adds fixtures for both new entries.
- Loop recovery × cache rendering documented as known limitation in B3.3; engine sequencing guarantees upstream is terminal before downstream prep runs, so the precondition holds today; document the invariant for future loop-guard refactors.
- `_resolve_chunk_value` shared helper extended to handle ABSENT via sentinel; D.1 static-prefix resolution must use the same helper (or `_resolve_template_for_cache` analog) to guarantee byte-identical resolution between cache-chunk path and auto-batch-prefix path.

**Round 2 architectural fixes (previous session):**
- `CompiledWorkflow.cache_block` is a frozen `CacheBlockIR` dataclass (NOT `dict[str, Any]`) — eliminates compile-cache + parallel-batch mutation hazard. Outer `__pflow_cache_render__` dict wrapped in `MappingProxyType`; values are frozen `CacheRenderContext` dataclasses with `tuple` for `subset` and `CacheBlockIR.items`.
- `__pflow_cache_render__` save/restore writes `MappingProxyType({})` on restore-from-absent (NOT `None`) — fixes the consumer-`.get(...).get(node_id)` AttributeError trap. Outer try/finally added so restore fires even if `_build_cache_render_dict` raises.
- All consumers use the canonical defensive read pattern `(shared.get("__pflow_cache_render__") or {}).get(node_id)`.
- Hash-vs-prep render divergence invariant: `plan_node._render_cache_for_hash` and `LLMNode.prep` `_render_cache_for_messages` MUST share a single `_resolve_chunk_value(chunk, shared)` helper — never duplicate resolution logic. Test asserts byte-equivalence.
- `core/CLAUDE.md:103` SSoT comment updated to reflect the `(severity, source, node_id, id or message)` tuple — sub-workflow dedup regression test added.
- `markdown_parser._build_node_dict` extended to extract `prompt_cache:` and `prewarm:` to top-level (parallel to existing `cache` extraction at line 1432).
- Duplicate `### Tests` block in C1.2 (with stale `__warnings__` runtime emission) deleted.
- F1 catalog SSoT table FILLED — all 10 rows × 8 columns concrete values, including `cache.discrepancy` as the 10th entry per orchestrator decision (resolves spec line 944 open question).
- `cache.opportunities-available` documented as separate non-catalog ID (per spec line 307) — emitted by `summarize()`, not `analyze()`.
- All three `_should_write_cache_metadata(node_type_name)` gate sites in instrumentation.py — `apply_memo_hit`, `handle_cached_execution`, `write_memo_cache` — symmetric LLMNode-only check.
- Memo HIT short-circuits cache rendering: documented in `_render_cache_for_hash`, tested explicitly in B3.4.
- Three-state invariant tested at MCP/CLI/JSON-trace surfaces (not just hash + rendering).
- F3.1 exit code contract: 9 conditions in a parametrized table; `--from-trace path` non-existent / corrupt / 2.0.0-graceful / mutually-exclusive-with-`--no-trace` all locked.
- F3.3 dry-run nudge: byte-equality test on the rendered glyph + format string + indented suggestion line.
- F2 cost-degradation tri-state contract: explicit table with three states (all priced / partial / all unpriced); locks `null` vs `0.00` vs `unavailable` per state.
- F2 per-warning-ID coverage test: every catalog ID has a synthetic minimal workflow that triggers it; CI fails if a new ID lacks a fixture.
- F3.2 MCP tool docstring contract: enumerates JSON shape, all catalog IDs (count derived from `CACHE_WARNING_CATALOG.keys()` at test time), cost-degradation tri-state, four-value `data_source`. Test asserts docstring contains the literal strings.
- Cross-workflow walker resolution-failure handling without new catalog ID: cycles/depth-limit log at info; broken sub-workflow refs re-raise existing `WorkflowValidationError` (no silent-skip).
- `_FAILURE_CATEGORY_MAP["cache_failure"]` entry DEFERRED to v1.x (not added in v1 — no typed exception emits it; dead-code violates "don't add features beyond what task requires").
- Branch-absent silent chunk skip now writes `cache_chunks_skipped: list[str]` to `llm_usage` so trace mode attributes discrepancies (vs TTL expiry, key mismatch, parallel-write race).
- B3 baseline-fixture merge gate: explicit "B3.1 patches MUST NOT begin until `golden_config_hashes.json` is committed against `main` head" + non-tautology PR sequence.
- B3 baseline shape coverage: structured output, attachments, retry config, branching, sub-workflows, batch (parallel + sequential), reasoning — all enumerated.
- `WorkflowExecutor.ALLOWED_PARAMS` × per-node schema: validator step 8 emits an improved hint message ("`prompt_cache:` and `prewarm:` are only valid on `type: llm` nodes") — tested explicitly.
- `pflow save` bundling × `## Cache` integration test: dependency_discovery walker doesn't mistake cache `${var}` chunks for file refs.
- B2.3 sub-workflow batch concurrency test: parallel batch with `WorkflowExecutor` (NOT sequential) — load-bearing for the `CacheBlockIR` freeze guarantee.
- `trace_report.py` line citation corrected from 400 to 463 (verified via grep).
- Paid spikes (Gemini, OpenAI routing, Anthropic per-TTL pricing) moved OUT of the plan entirely — they are pre-implementation work documented in agent-handoff and run before B1; spike outcomes either confirm the encoded decision or trigger a plan update.
- `litellm.token_counter` empirical behavior verified (no raise on unknown models, returns 0 on empty text, raises ValueError on None) — F1 test reflects the true error path.

**Round 1 corrections (preserved from prior session — see progress log §31):**

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
- review-feature-interactions C3: Gemini multi-marker collapse — verified during the pre-plan Gemini spike (recorded in progress log §32+).

**One open user decision still requires call:**
- `cache.discrepancy` (used in spec mode-4 from-trace example): not in v1 catalog. Add as 9th entry (DD#29 design review) OR emit as generic Diagnostic without stable id? Recommend 9th entry under `cache_advisory` — needs one-line user confirmation.

**One open user-architectural question (review-feature-interactions C2):**
- Cache rendering errors in batch + sub-workflow + `error_handling: continue`: which error category fires (`template_error` vs new `cache_failure`)? Plan currently routes through `build_template_error_diagnostic` (i.e., `template_error` category). The four-dimensional error matrix interaction (signaling × categorization × mode × propagation) isn't fully enumerated. Recommended: stay with `template_error` for v1 (consistent with existing template-resolution failure semantics; `cache_failure` is forward-looking only and currently dead code per review-impact-completeness W8). Surface to user before B2.3 lands.
