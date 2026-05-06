# Task 159 — Implementation Progress Log

This log tracks IMPLEMENTATION progress (vs `progress-log.md` which tracks the planning journey through 6 review rounds). Each implementing agent appends a complete entry at their segment firebreak.

> **Format and contents**: see `starting-context/implementing-agent-brief.md` "At each firebreak: STOP and log" section. The entry must include: What I implemented · Deviations from plan · Tacit knowledge for the next agent · Open hedged claims · Open user decisions surfaced · What's next · Code-review findings worth carrying forward.

> **Segment boundaries** (per progress-log §35 and the implementing-agent brief):
> - Segment 1: B1.1, B1.2, B2.1, B2.2, B2.3 (Foundations + Parser/Validator)
> - Segment 2: B3.1, B3.2, B3.3, B3.4 (Memo-hash gate)
> - Segment 3: C1.1, C1.2, C2, C3, D, E (Rendering + Prewarm + Trace)
> - Segment 4: F1, F2, F3, G (Analyzer + Docs)

> **The user decides at each firebreak** whether the same agent continues or a fresh agent picks up. Agents do NOT auto-continue.

---

## Segment 1 — Foundations + Parser/Validator (2026-04-29)

### What I implemented

Sub-phases shipped: **B1.1, B1.2, B2.1, B2.2, B2.3** — all five sub-phases of segment 1.

**Files modified (production):**
- `src/pflow/core/diagnostic.py` — `Diagnostic.id` field; identity tuple update; cache category constants + `CATEGORY_TITLES` entries; SSoT comment in source. (+42 lines)
- `src/pflow/core/diagnostic_render.py` — `_format_cache_warning_or_advisory` dispatcher; closed-list `_CACHE_INLINE_CONTEXT_KEYS`. (+64 lines)
- `src/pflow/core/CLAUDE.md` — load-bearing SSoT comment update at line 103. (+1 / -1)
- `src/pflow/core/llm_capabilities.py` — NEW. Frozen `ModelCapability` dataclass; `MODEL_CAPABILITIES` tuple per DD#32; `get_min_cache_tokens()` lookup with conservative-floor fallback. (+123 lines)
- `src/pflow/core/markdown_parser.py` — `_SectionType.CACHE`; `_CacheChunk` / `_CacheSection` dataclasses; section-level YAML + tagged code-block handling under `## Cache`; `_parse_cache_code_block` (`${var}`-splitting algorithm); `_attach_cache_code_block`; `_build_cache_dict`; top-level `prompt_cache:` / `prewarm:` extraction in `_build_node_dict`; `## Cache` syntax hint. (+268 lines)
- `src/pflow/core/ir_schema.py` — top-level `cache` field schema (object: `ttl` enum + `items` array of `{name, var, prose_before, _source_line}`); per-node `prompt_cache: list[str]` and `prewarm: bool`. (+62 lines)
- `src/pflow/core/workflow/data_flow.py` — `_validate_cache_block` + 5 helper functions; STEP-1 non-LLM rejection (V6 combined-diagnostic shape); STEP-2 defensive shape skip; STEP-3a per-node order + chunk resolution checks; STEP-3b top-level chunk var resolution + batch-scoped rejection + unused-chunk warnings; 5 diagnostic builders. (+396 lines)

**Files added (tests):**
- `tests/test_core/test_diagnostic_id_field.py` — 14 tests (B1.1).
- `tests/test_core/test_llm_capabilities.py` — 40 tests, mostly parametrized (B1.2).
- `tests/test_core/test_cache_block_parser.py` — 19 tests (B2.1).
- `tests/test_core/test_ir_schema_cache.py` — 23 tests (B2.2).
- `tests/test_core/test_prompt_cache_validation.py` — 24 tests including 1 xfail tripwire (B2.3).

**Total tests added:** 120.

**Final-segment checks:** 5515 tests passing; `make check` green; `test_plan_drift.py` 32/32.

### Deviations from plan

1. **The `see_also=["caching"]` references on cache diagnostics are deliberately omitted in B2.3.** Plan section "Validation Location" specifies `see_also=["caching"]` on cache validator diagnostics. I encoded this initially, then the repo-wide `test_all_see_also_literals_resolve_to_real_guide_topics` (in `test_diagnostic.py`) failed because the `caching` guide topic doesn't exist yet — it's added in Phase G (G.2 — `pflow guide caching` page). Fix: removed the `see_also` literals from `_make_*_diagnostic` builders in `data_flow.py`. **What follow-up agents need to know:** Phase G.2 must wire `see_also=["caching"]` back into the cache diagnostic builders in `data_flow.py` (3 sites near the helpers — search for the comment "guide-topic pointer is wired in Phase G").

2. **`# noqa: C901` on `_validate_cache_block`.** Plan didn't specify; ruff complexity check fires at 28>10. The function has clearly numbered STEP 1 / STEP 2 / STEP 3a / STEP 3b sections following the V5+V6 Round-5 ordering rules — refactoring would obscure the linear contract. Existing precedent: `markdown_parser.py:264` uses `# noqa: C901` on `parse_markdown` for the same reason.

3. **V6 sub-workflow dedup test is simpler than the plan envisioned.** Plan Round 5 specifies a fixture-based test running real `WorkflowValidator.validate(parent_path)` with a parent + child workflow file pair. My implementation uses a unit-level `deduplicate_diagnostics([parent, child_with_provenance])` test on synthetic Diagnostic instances. Both lock the same dedup invariant, but the synthetic test doesn't exercise the full `_add_child_provenance` flow. **What follow-up agents need to know:** The synthetic test passes (xpassed) because the id-keyed identity tuple `(severity, source, node_id, id or message)` collapses parent + child versions correctly when `id` is set. The fixture-based test from the plan can be added when sub-workflow integration tests for cache validation are needed (likely Segment 4). **If integration testing reveals divergent behavior** (e.g., propagation modifies `node_id`), the open user decision (granular dedup tuple vs special-case per-id dedup) becomes actionable.

4. **`prompt_cache: 5` (non-list) on `type: shell` test path.** Plan asserts STEP 1 (non-LLM rejection) fires before STEP 2 (defensive shape skip). My implementation matches. The test `test_non_llm_rejection_runs_BEFORE_shape_skip` locks this ordering invariant.

5. **Schema `cache.items.required = ["name", "var", "prose_before"]`.** The plan explicitly mentions `name` and `var` as required, and lists `prose_before` as a per-item field. I made `prose_before` required as well. If any downstream code path constructs items without `prose_before`, schema validation will reject. **Mitigation:** my parser always populates `prose_before` (empty string if no preceding prose). For programmatic IR construction in tests, `prose_before` must be provided.

### Tacit knowledge for the next agent

**1. The renderer change in B1.1 is loose — it dispatches on `context.get("category") in {cache_failure, cache_warning, cache_advisory}`.** This means any existing diagnostic that happened to use those category strings would also pick up the cache renderer, including `[id]` prefix surfacing. I verified there are no existing producers of these category strings, but if a future contributor adds a non-cache `Diagnostic` with `category="cache_warning"` (perhaps due to copy-paste), the renderer will surface it the same way. The closed-list `_CACHE_INLINE_CONTEXT_KEYS` limits the inline context surface to known keys, so misuse stays bounded.

**2. The `## Cache` section state machine extension in B2.1 is the structurally novel piece.** Today the parser allows `- key:` params and tagged code blocks ONLY inside `### entities` (orphan path at line 273–274 / 402–404). I added a parallel branch that runs ONLY when `current_section == _SectionType.CACHE` AND `current_entity is None`. Reading order:
  - `_KNOWN_SECTIONS` is intentionally NOT extended to include CACHE — orphan content rules don't apply.
  - The H2 transition at line 310 initializes `cache_section = _CacheSection(...)` when entering `## Cache`.
  - The code-fence-close branch at line 268 handles cache-section attachment via `_attach_cache_code_block`.
  - The new section-level YAML branch (right before the entity branch) accepts only `- ttl:`.
  - Phase 4 builds `ir["cache"]` from `cache_section`.

  If you add a new section type with a similar shape (e.g., future `## Tools`, `## Resources`), mirror this exact pattern — DON'T add to `_KNOWN_SECTIONS`, DO initialize a collector at the H2 transition, DO add a section-level branch before the entity branch.

**3. The `_parse_cache_code_block` algorithm silently discards trailing prose after the last `${var}`.** Per the spec contract: chunks are `[prose-before-${var}][${var}]` pairs; trailing prose has no var to attach to. This is documented in the function docstring. If a future feature wants to support trailing prose (e.g., closing-context labels), the contract changes — but it would need the spec to update too.

**4. `prompt_cache:` and `prewarm:` are extracted to TOP-LEVEL node keys, NOT inside `node["params"]`.** Plan: this is required for B2.2's per-node schema check to see them AND for B2.3's `cache.invalid-on-non-llm` rule (validator step 8 only iterates `node["params"]`, so top-level placement is the load-bearing reach for the non-LLM-node check). If you ever need to debug "why doesn't validator step 8 see this field?", the answer is "step 8 only walks params; top-level fields need top-level checks."

**5. The B2.3 helpers split into two diagnostic categories.** `cache.*` namespaced (catalog) IDs use `id="cache.X"` and `category=CACHE_*_CATEGORY`. Reference-resolution errors (undeclared chunks, batch-scoped rejection, chunk var not resolving) flow through the existing validation pipeline with `category="validation"` and NO catalog id. Per spec § "Stable Warning ID Catalog": "they're not separate cache-namespaced IDs because they reuse pflow's general validation machinery." If you need to add a new cache-specific check, decide upfront whether it's a stable agent-facing surface (catalog id) or a workflow-level reference error (validation pipeline). Adding new catalog IDs without DD#29 design review = surface to user first.

**6. `# noqa: C901` is the right call here for `_validate_cache_block` — the V5+V6 Round-5 ordering MATTERS** and refactoring into helpers would scatter the steps across function boundaries and obscure the contract. The numbered comments (`STEP 1`, `STEP 2`, `STEP 3a`, `STEP 3b`) in the function are themselves part of the contract. If a future contributor refactors, they need to preserve the ordering: STEP 1 (non-LLM rejection) MUST run before STEP 2 (shape skip); STEP 3b (top-level checks) MUST run after STEP 2 (so referenced_chunks is populated for unused-chunk computation).

**7. The `caching` guide topic must be added in Phase G** (G.2). The repo-wide `test_all_see_also_literals_resolve_to_real_guide_topics` enforces this: any `see_also=["caching"]` literal in `src/pflow/` will fail the test until the topic is registered. I removed all `see_also=["caching"]` references from B2.3 to avoid breaking the suite. **Phase G.2 must:** (a) register the `caching` guide topic; (b) re-add `see_also=["caching"]` to the three diagnostic builders in `data_flow.py` (search for the comment about Phase G).

**8. B2.1 round-trip test is a contract-locker, not a save-path test.** The plan's "save round-trip" hedged claim was about `WorkflowManager.save()` writing raw markdown bytes verbatim. My round-trip test in `test_cache_block_parser.py::test_cache_block_round_trip_preserves_content` parses the same source twice and asserts byte-for-byte IR equality — it doesn't actually exercise `WorkflowManager.save()`. The CONTRACT it locks is: parsing is deterministic. If save preserves bytes (which `WorkflowManager.save` does today), then re-parse produces the same IR. A full save-path integration test is best added when Segment 4 touches the save path (G.2 may need it).

**9. The `MODEL_CAPABILITIES` table has a "" pattern entry for OpenAI and Gemini.** This is intentional: OpenAI auto-cache fires at 1024 across all GPT/o-series families, and Gemini's explicit cache requires ~4k across all model versions. The empty string `""` matches every bare model name that starts with "" (which is every string), so the lookup falls through to the "best longest pattern" matcher and these become the per-provider defaults. If a specific Gemini model needs a different threshold (e.g., a future Pro model requiring 32k explicit), add a more-specific row above the empty-string row.

**10. `test_v6_subworkflow_invalid_on_non_llm_dedup` is xpassed today but xfail-marked.** The id-keyed identity tuple makes the unit-level dedup work correctly. The xfail tripwire remains in place because the BROADER sub-workflow propagation behavior (will `_add_child_provenance` modify `node_id` in a way that breaks dedup?) is not yet exercised by integration tests. This is the V6 "open user decision" tag from the plan — keep the xfail wrapper until integration tests confirm/refute the dedup contract end-to-end.

### Open hedged claims and verifications still pending

- **VERIFIED**: `Diagnostic.id` field doesn't break existing tests. `make test` confirmed all 5515 tests pass after B1.1 land, including all `tests/test_core/test_diagnostic.py` cases.
- **VERIFIED**: `pflow save` round-trip preserves `## Cache` content. The B2.1 round-trip test locks the parser-determinism contract; the file save is byte-preserving by `WorkflowManager.save()` design (per `core/workflow/CLAUDE.md`).
- **VERIFIED**: `WorkflowExecutor._compiled_workflow_cache` interaction unaffected. The compile cache stores compiled IR (which now includes `cache` field). My changes are additive at the IR level; no compile-cache invalidation needed. Sub-workflow concurrency test deferred to B3.2 per the plan (Segment 2).
- **VERIFIED**: `test_plan_drift.py` (32 tests) green throughout the segment.
- **NEEDS VERIFICATION (Segment 2 onwards)**: Whether the `cache` IR field interacts cleanly with the compile pipeline (`runtime/compilation/`). My B2 changes ONLY add the IR field; B3.1 will add `CompiledWorkflow.cache_block` and the compiler factory. If compile fails on a workflow with `## Cache` declared, B3.1 needs to handle it.
- **NEEDS VERIFICATION (Segment 4)**: V6 sub-workflow dedup at the integration level. The unit test passes; the broader propagation path (parent invokes child via real `WorkflowValidator`) is not tested. If integration testing in Segment 4 reveals divergent behavior, the user decision (granular dedup vs per-id dedup) becomes actionable.
- **ASSUMPTION**: The `cache.items[].prose_before` field being REQUIRED in the schema doesn't break any existing IR construction path. Verified by tests but not by exhaustive grep. If a future contributor builds an IR with `cache` programmatically without `prose_before`, schema will reject.
- **ASSUMPTION**: `find_similar_items` works correctly for cache chunk names (which can contain `.`, `-`, `_`). Verified for `unknwon` → `unknown` in tests; broader fuzzy matching not stress-tested.

### Open user decisions surfaced

**None blocking Segment 2.**

The two pre-existing decisions from the plan (per `agent-handoff.md`):
1. **F2 confidence aggregation strictness** — surfaces in Segment 4 (during F2). Plan defaults STRICT per DD#34. No segment-1 work depends on this.
2. **V6 sub-workflow dedup outcome** — partially deferred. The xfail-wrapped synthetic test is in place; integration-level behavior remains unverified. If Segment 2/3/4 implementation surfaces a real divergence (parent + child diagnostics not deduping in production), the user picks between the two fix shapes.

No new user decisions were forced during Segment 1 implementation.

### Post-segment-1 smoke test + bug fix

After committing the segment, I ran a 4-case manual smoke test through `pflow validate-only` to verify rendered diagnostic UX matches the spec-locked formats:

1. **Valid workflow** with `## Cache` + `prompt_cache:` → first run **failed** with a false-positive `Declared input(s) never used` ERROR. **Real interaction bug surfaced.** Fix below.
2. **Out-of-order `prompt_cache:`** → renders the four-line spec-locked message exactly:
   ```
   Error 1: Cache Failure

   Node 'write-lyrics' prompt_cache order doesn't match ## Cache declaration
     declared:  [concept, concept_brief]
     you wrote: [concept_brief, concept]
     fix:       reorder the `prompt_cache:` field to match ## Cache declaration order
   ```
3. **`prompt_cache:` on a `type: shell` node** → renders `Cache Failure` title, structured message naming the node type, locked suggestion phrasing.
4. **Unused chunk** → renders `[cache.unused-chunk]` ID prefix inline + concrete actionable suggestion. Validation passes (warning is non-blocking).

**Bug found by the smoke test (commit `1045d122`):** `_extract_all_templates` in `runtime/template_validation/validator.py` only walked `node.params` and `batch.items` — top-level `workflow_ir["cache"]["items"]` was structurally invisible to it. Result: every workflow declaring an input ONLY for use in `## Cache` (a common shape, since cache chunks ARE inputs from the workflow's perspective) tripped the spurious unused-input ERROR.

**Fix:** extended `_extract_all_templates` with a top-level walk that wraps each `cache.items[i].var` in `${...}` and feeds it through the existing `extract_from_value` pipeline. The walker now sees cache chunk vars the same way it sees node-param vars, so `_validate_unused_inputs` correctly marks them as referenced.

**Regression test:** `tests/test_core/test_cache_block_parser.py::test_inputs_referenced_only_in_cache_not_flagged_unused`.

**What follow-up agents need to know:**
- `_extract_all_templates` is structurally responsible for "find every template var reference anywhere in the IR" — when adding new IR fields that carry template references, EXTEND the walker. The unused-input check (and possibly future passes) depend on this being exhaustive.
- Other validation passes (path validation, type validation) consume the same `all_templates` set returned by this walker. Cache chunks now flow through ALL validation passes for free — and resolution succeeds because cache vars reference declared inputs / step outputs which are already in `available_params` / `node_outputs`. Verified by the 4-case smoke test.
- Smoke test fixtures live at `/tmp/task159-smoke/case1-4-*.pflow.md`. Reproducible with `uv run pflow /tmp/task159-smoke/<file> --validate-only <inputs>`.

### Code-review findings worth carrying forward

**Lessons from segment 1 worth surfacing:**
- **The `caching` guide topic is a hidden constraint**: any `see_also=["caching"]` reference in `src/pflow/` fails `test_all_see_also_literals_resolve_to_real_guide_topics`. Don't encode the literal until G.2 ships.
- **C901 cyclomatic-complexity threshold (10)**: clearly-numbered linear functions can use `# noqa: C901` (precedent at `markdown_parser.py:264`). Refactoring to satisfy the linter when steps are interdependent obscures the contract.

---

### Post-segment-1 verification pass (adversarial smoke tests + 4-agent /code-review)

After the post-segment fix to `_extract_all_templates`, ran a verification-specialist pass: 14 adversarial workflow files exercised through `pflow validate-only`, `pflow run`, `pflow save`, `pflow visualize`, `pflow --dry-run`, and `pflow --output-format json`. Then dispatched 4 high-leverage review subagents in parallel: `review-impact-completeness`, `review-silent-failures`, `review-validation-consistency`, `review-test-fidelity`.

**Bugs found by adversarial smoke tests (NOT caught by unit tests):**

1. **Double-emit on bad cache var references** — my walker fix routed cache vars through both `_validate_cache_block` AND the existing template-path validator (pass 5). User got two errors for one mistake. Fixed via split-extractor: cache vars live in a separate `_extract_cache_templates_for_unused_check` and flow ONLY into the unused-input check. Path validation receives only node-param templates; cache resolution is owned by `_validate_cache_block` with richer messages.

2. **`prompt_cache: [a, a]` (duplicate items) passed silently** — would render the chunk twice in the system prompt, wasted tokens, silent semantic shift. Fixed with duplicate-detection diagnostic; suppresses the order-mismatch follow-on.

**Fixes from the 4-agent code review:**

3. **V6 sub-workflow dedup test was a tautology** (`review-test-fidelity` Critical 1). Synthetic `deduplicate_diagnostics([d1, d2])` necessarily collapses identically-id'd diagnostics regardless of production behavior. Replaced with Pattern 2 fixture-based test driving a real parent → child workflow file pair through `WorkflowValidator.validate()`.

4. **Two circular identity tests removed** (`review-test-fidelity` Critical 2). They reconstructed the tuple from production code — passed by definition. Behavioral tests already cover the contract.

5. **Split-extractor regression test extended with effect assertion** (`review-test-fidelity` High 3a). Now asserts BOTH the split mechanism AND the end-to-end effect (running `validate_workflow_templates` produces zero spurious errors for cache-only inputs). Catches future re-export-then-double-emit regressions.

6. **Pattern 2 parser→validator integration test added** (`review-test-fidelity` High 5). Parses a real `.pflow.md` with `cache.order-mismatch` and asserts the validator emits the spec-locked diagnostic. Closes the "all hand-built IR" gap.

7. **ERROR-severity cache diagnostics now show `[id]` next to the title** (`review-test-fidelity` High 4). E.g., `"Error: Cache Failure [cache.invalid-on-non-llm]"`. Same agent-routing handle as WARNING/INFO. Non-cache errors render unchanged (additive). Two new renderer tests lock both cases.

8. **`_extract_cache_templates` renamed to `_extract_cache_templates_for_unused_check`** (`review-silent-failures` W3). Makes the contract explicit at every call site — a future contributor calling it from path-validation triggers an immediate naming red flag.

9. **Parser invariant assertion `chunk.name == chunk.var_expr`** (`review-validation-consistency` S1). The schema doesn't enforce equality but the parser always populates them equal. Locks the contract — segment 3's renderer will use `var`; B2.3 resolves by `name`. Drift would break the resolution-vs-rendering symmetry silently.

10. **Doc-staleness fixes**:
    - `core/CLAUDE.md:107` — short paragraph aligned with load-bearing SSoT comment at line 103 (id-keyed identity tuple).
    - `runtime/template_validation/CLAUDE.md` — documents both extractors and the split-extractor contract.

**Findings deliberately NOT fixed (per critical-thinking triage):**

- **`prompt_cache:` inside `node["params"]` asymmetry** (`review-validation-consistency` W1). Programmatic-IR-only path; the parser always lifts to top-level. Step 8 already rejects with clear "Unknown parameter" error. Adding a third rule would be belt-and-suspenders for a path normal authoring never hits.
- **`cache.duplicate-chunk` stable catalog id** (`review-test-fidelity` High 3b suggestion). Would push the catalog to 12 entries, violating DD#29's closed-list-of-10 design decision. Adding new IDs requires user/spec review per DD#29. Substring match in the regression test is sufficient for now.
- **Empty-string `id=""` `__post_init__` check** (`review-silent-failures` S1 suggestion). Speculative future risk; `grep` finds zero diagnostics constructed with empty `id` in `src/`. Not worth the runtime check.

**End-to-end verification (manual `pflow ...` runs that PASSED):**

- Run a workflow with `## Cache` declared (no LLM, just shell): `pflow workflow.pflow.md` executes successfully; cache.unused-chunk warning fires correctly.
- `pflow save` round-trip: `## Cache` content preserved byte-for-byte; saved workflow runs identically.
- Sub-workflow with `## Cache` invoked via parent: child cache validated, warnings propagate with `_add_child_provenance` prefix and include `Sub-workflow: ./child.pflow.md` context.
- `pflow visualize`: mermaid generation works on cache workflows (cache section is invisible to mermaid, which is correct).
- `pflow --dry-run` + `--output-format json`: cache warnings round-trip through plan diagnostics.
- `--validate-only --output-format json`: full Diagnostic.to_dict structure (id at top-level, structured context, suggestions list) matches spec.
- Parent → child where child has `cache.invalid-on-non-llm`: 1 ERROR with provenance prefix, sub-workflow path, preserved node_id (V6 dedup contract verified end-to-end at the integration level).

**Final state after verification + review fixes:**
- 5519 tests pass, 9 skipped, 0 xfailed/xpassed.
- mypy + ruff + ruff-format + deptry all green.
- `test_plan_drift.py` (32/32) green.
- 14 manual adversarial cases all behave correctly.

---

## Segment 2 — Memo-hash gate (2026-04-29)

### What I implemented

Sub-phases shipped: **B3.0** (pre-merge baseline fixture) **+ B3.1, B3.2, B3.3, B3.4** — all four Segment-2 sub-phases plus the load-bearing fixture script.

**Files modified (production):**
- `src/pflow/runtime/engine/types.py` — extended `NodeConfig` with `prompt_cache_items: tuple[str, ...] = ()` + `prewarm: bool = False`; extended `CompiledWorkflow` with `cache_block: CacheBlockIR | None = None`; imports `CacheBlockIR` from `core/cache_render`. (+9 lines)
- `src/pflow/runtime/compilation/compiler.py` — extraction helpers `_extract_prompt_cache_items` (Round-6 hardened explicit-isinstance precondition; rejects `tuple("string")` silent-splat), `_extract_prewarm` (strict bool, rejects `1`/`0`), `_build_cache_block` (frozen `CacheBlockIR` from IR `cache:` section), `_build_cache_chunk`. (+78 lines)
- `src/pflow/runtime/engine/engine.py` — `_EMPTY_CACHE_RENDER` module constant; `_build_cache_render_dict` (sparse — LLM nodes with cache state only); `_make_cache_render_context` (per-node helper); save/restore for `__pflow_cache_render__` in `WorkflowEngine.run()` mirroring trace-collector pattern. (+77 lines)
- `src/pflow/runtime/engine/instrumentation.py` — extended `compute_node_config` signature with keyword-only `prompt_cache_content: list[dict[str, Any]] | None = None`; conditional inclusion `if prompt_cache_content: config["prompt_cache"] = prompt_cache_content` (mirrors `batch_config` precedent verbatim). (+13 lines)
- `src/pflow/runtime/engine/plan_node.py` — full rewrite: reordered to resolve templates BEFORE config hash; added `_render_cache_for_hash` helper (filters `_CHUNK_ABSENT` chunks symmetrically with prep-side); `_resolve_for_plan`/`_make_plan`/`_miss_with_template_error` extracted as small helpers (each ≤ 6 statements, well under C901's threshold of 10). Hash is still computed on the strict-mode template-error path for trace fidelity (matches pre-task behavior). (~131 lines net change)
- `src/pflow/runtime/cache.py` — defense in `_make_serializable` as the FIRST branch: raises `TypeError` on `_ChunkAbsentSentinel` (lazy-imports `_ChunkAbsentSentinel` to keep `cache.py` dependency-free at module load). Locked error-message substring `"_CHUNK_ABSENT must be filtered before serialization"` so future tests can pin against it. (+13 lines)
- `src/pflow/runtime/workflow_executor.py` — inline comment block above `_PROPAGATED_KEYS` (verified 7 entries) explaining `__pflow_cache_render__`'s INTENTIONAL non-membership. Catches the regression where a future contributor "tidies up" by adding the key. (+14 lines)
- `src/pflow/runtime/CLAUDE.md` — added `__pflow_cache_render__` to "Reserved Shared Store Keys" canonical reference; documents the read-only contract, save/restore semantics, restore-from-absent invariant, and `_PROPAGATED_KEYS` exclusion. (+12 lines)

**Files added (production):**
- `src/pflow/core/cache_render.py` — NEW module owning ALL cache-related types and helpers:
  - Frozen dataclasses: `CacheChunkIR`, `CacheBlockIR`, `CacheRenderContext`.
  - `_ChunkAbsentSentinel` class + `_CHUNK_ABSENT` singleton (Final-typed).
  - `_deterministic_serialize(value) -> str`: canonical JSON for non-string values, pass-through for strings, `default=str` fallback for non-JSON-native types.
  - `_resolve_chunk_value(chunk, shared) -> str | _ChunkAbsentSentinel`: ABSENT-aware single-chunk renderer.
  - `_resolve_static_prefix_for_cache(template_str, shared) -> str`: D.1 companion helper that substitutes via `_deterministic_serialize` rather than Python repr (closes the silent cross-mode cache-miss class). Lazy-imports `TemplateResolver` and `node_state` to avoid the layer-import violation. (165 lines)

**Files added (tests + fixture + script):**
- `scripts/generate_config_hash_baseline.py` — NEW. Re-runnable script that compiles a curated set of 9 example workflows and writes per-node hashes to the golden fixture. (164 lines)
- `tests/test_runtime/fixtures/golden_config_hashes.json` — NEW. 30 nodes across 9 workflows covering plain, multi-step, branching, batch (sequential + parallel), sub-workflow, LLM, `cache: false`, template-heavy shapes. The LOAD-BEARING regression baseline. (101 lines)
- `tests/test_runtime/test_prompt_cache_compile.py` — 21 tests covering B3.1: defaults, well-formed lifts, frozen invariants, 6 malformed `prompt_cache:` shapes, 4 malformed `prewarm:` shapes, malformed `cache:` block. (246 lines)
- `tests/test_runtime/test_cache_render_dict.py` — 12 tests covering B3.2: builder unit tests against synthetic `CompiledWorkflow`, save/restore round-trip, restore-from-absent writes `_EMPTY_CACHE_RENDER` not `None`, outer-dict mutation rejection (`MappingProxyType` → `TypeError`), `CacheRenderContext` frozen, sub-workflow isolation via `ShellNode.prep` monkeypatch. (366 lines)
- `tests/test_runtime/test_prompt_cache_hash.py` — 17 tests covering B3.3 + B3.4 including the **LOAD-BEARING golden-fixture regression gate** (`test_golden_baseline_hashes_match`), DD#19 three-state at `compute_node_config` and end-to-end via `plan_node`, branch-absent symmetry on the hash side, and 6 `_make_serializable` defense tests (top-level + dict + list + nested dict→list + list→dict + positive control). (408 lines)
- `tests/test_core/test_cache_render.py` — 16 tests covering helper unit tests: `_deterministic_serialize` byte-stability, `_resolve_chunk_value` ABSENT-detection + dict serialization + path roots + FAILED upstream behavior, `_resolve_static_prefix_for_cache` substitution + leave-unresolved + regex-parity behavioral lock. (180 lines)

**Total tests added:** 66.

**Final-segment checks:** 5585 tests passing; `make check` green; `test_plan_drift.py` 32/32; `test_golden_baseline_hashes_match` PASSED (DD#19 load-bearing gate).

### Deviations from plan

1. **Frozen dataclasses live in `core/cache_render.py`, NOT `runtime/engine/types.py`** (load-bearing layer-policy correction). Plan said to put `CacheChunkIR`, `CacheBlockIR`, `CacheRenderContext` in `runtime/engine/types.py`. But `nodes/llm/llm.py` only imports `pflow.core.*` (verified `nodes/llm/llm.py:13-20`), and `LLMNode.prep` (C1.2) reads `CacheRenderContext` from shared. Putting the dataclasses in `runtime/engine/types.py` would force a `nodes/` → `runtime/` layer violation in C1.2. Round-5 fixed this for the helper functions but didn't propagate the fix to the dataclasses — Round 6 didn't catch it either. **Resolution:** all three frozen dataclasses live in `core/cache_render.py` alongside the helpers. `runtime/engine/types.py` imports `CacheBlockIR` directly (runtime → core is allowed) for `CompiledWorkflow.cache_block`. Top-10% question check: this matches mypy/ruff/Temporal SDK conventions of placing shared types where ALL consumers can reach them without layering inversion. **What follow-up agents need to know:** when LLMNode.prep imports `CacheRenderContext` for type annotations in C1.2, the import path is `from pflow.core.cache_render import CacheRenderContext` — NOT from `runtime/engine/types`.

2. **Combined B3.3 + B3.4 into one logical change.** Plan separated them (B3.3 reorders + adds helpers; B3.4 wires the kwarg). They're tightly coupled — B3.3's pseudo-code passes `prompt_cache_content` to `compute_node_config` which doesn't accept it until B3.4. Since the user said "no commits, I'll commit at end of segment," there's no PR-sized chunking to enforce. Tests cover both surfaces in `test_prompt_cache_hash.py`. **What follow-up agents need to know:** the helpers in `core/cache_render.py` AND the conditional inclusion in `compute_node_config` are both live — Segment 3's C1.2 just needs to add the prep-side rendering (the import + filter pattern is already documented in the docstrings).

3. **`_resolve_static_prefix_for_cache` shipped in B3.3 even though its sole consumer is D.1 (Segment 3).** Plan's B3.3 includes it as a "companion helper". Keeping the helper pair (`_resolve_chunk_value` + `_resolve_static_prefix_for_cache`) colocated with their shared `_deterministic_serialize` makes the byte-identity invariant explicit at one site. Tests for the helper are in B3.3. D.1 just imports and uses.

4. **Skipped `# noqa: C901` per user's mid-segment directive** ("do not use noqa: C901, always adhere to the 10 threshold"). Where the plan or natural decomposition would've pushed a function to complexity > 10, I split it into small focused helpers:
   - `plan_node` itself uses `_resolve_for_plan` + `_render_cache_for_hash` + `_read_cache_context` + `_make_plan` + `_miss_with_template_error`.
   - `_create_node_and_config` calls `_extract_prompt_cache_items` + `_extract_prewarm` (each ≤ complexity 4).
   The pre-existing `# noqa: C901` on `engine._execute_node:382` was NOT touched (out of scope).

5. **Used `MappingProxyType` outer wrap (Round 5 + 6 lock) AND wrote `_EMPTY_CACHE_RENDER` as a module constant.** Plan suggested both. Implementation follows the plan verbatim. **Edge case caught in tests:** `MappingProxyType.__setitem__` raises `TypeError`, NOT a more specific `ImmutableError`. Documented in the test assertion.

6. **Test infrastructure: monkeypatched `ShellNode.prep`, NOT `BaseNode.prep`** for the in-flight observation tests in `test_cache_render_dict.py`. CPython's MRO finds the subclass override first; `BaseNode.prep` patches don't fire when ShellNode overrides. **Reusable lesson** for follow-up agents: when capturing shared state during execution via monkeypatch, target the leaf class that actually overrides the method (verified via grep `def prep` in `nodes/`).

7. **The B3.4 in-memory mutation test uses `compile_workflow(copy.deepcopy(ir_dict), registry)` per Round-5's deepcopy guidance** — even though my chosen baseline workflows have NO `@./` file refs (no in-place mutation risk). Cleaner pattern; no fixture-mechanics surprises if a future test adds a workflow with refs.

8. **The `test_render_cache_for_hash_filters_absent_chunks` test fixture uses a declared-but-unset workflow input** as the ABSENT trigger. Per `node_state.get_node_status`: "node not in shared AND not in __failures__" → ABSENT. A simpler fixture than the plan's full conditional-branching shape. Same invariant locked.

9. **No `mypy` regressions, but auto-format adjusted two imports**: `from typing import Mapping` → `from collections.abc import Mapping` (UP035), and reordered cache-render imports alphabetically. Both intentional ruff fixes — re-verified clean.

### Tacit knowledge for the next agent

**1. The hash-vs-prep render byte-identity invariant is the load-bearing contract for all of B3 + C1.2.** Both `plan_node._render_cache_for_hash` and `LLMNode.prep` (Segment 3 C1.2) MUST call `_resolve_chunk_value` from `core/cache_render.py` and filter the same `_CHUNK_ABSENT` sentinel. If they diverge (one filters, the other doesn't; one uses canonical JSON, the other uses Python repr), memo cache hash is keyed on bytes A while the adapter sends bytes A' — silent stale-cache class. The `_make_serializable` defense at `runtime/cache.py` is the second line of defense (raises if a sentinel ever leaks past the filter); the first line is the symmetric filter at both call sites.

**2. The `compute_node_config` keyword-only kwarg is intentional.** Future callers that accidentally pass `prompt_cache_content` as the 5th positional arg get a `TypeError`. Without `*,` someone could pass `compute_node_config("Type", {}, {}, batch, [{"name": "x", ...}])` — looks plausible, would silently include cache content where none should be. The `*,` defense is byte-cheap and prevents a class of bugs.

**3. `_render_cache_for_hash` returns `None` (not `[]`) when there's no opt-in.** `compute_node_config(prompt_cache_content=None)` skips the conditional inclusion entirely, byte-identical to pre-task. `compute_node_config(prompt_cache_content=[])` ALSO skips (truthy check). Both paths produce DD#19-compliant byte-identity. The hash test covers all three states.

**4. The plan_node reorder doesn't affect the strict-mode template-error path's hash for tracing.** Hash is still computed (via `compute_node_config(..., prompt_cache_content=None)` on the error path) so trace records carry useful identity info. Original behavior was "compute hash without cache content on error path"; my version matches that exactly.

**5. The golden fixture is keyed by relative path.** When `tests/test_runtime/test_prompt_cache_hash.py::test_golden_baseline_hashes_match` runs, it iterates the fixture's keys and skips entries starting with `_` (the `_meta` and `_coverage` namespaces). If a future fixture entry is named without an `_` prefix but isn't a workflow path, the regression test will try to compile it as a workflow and fail. Keep the `_` namespace convention.

**6. The fixture script and the regression test SHARE input dicts** via `_BASELINE_INPUTS` in the test file. If the script's `WORKFLOWS` table changes (different inputs for a workflow), `_BASELINE_INPUTS` MUST be updated too — otherwise regen produces hashes against inputs that the test doesn't replay. **Future agents who modify the fixture script should grep for `_BASELINE_INPUTS`.**

**7. `_build_cache_render_dict` is sparse by design — it includes a node only if at least one of `(prompt_cache_items, prewarm, workflow.cache_block)` is set.** Non-cache workflows produce an empty dict; consumers' canonical `(shared.get(K) or {}).get(node_id)` defensive read handles `None`. **What changes if you want the dict denser:** the only consumer cost is allocation per LLM node (one frozen dataclass each). Sparseness is the right call for now.

**8. `CompiledWorkflow.cache_block` is a frozen `CacheBlockIR`, not a `dict[str, Any]`.** This matters for parallel batch concurrency: the compile-once cache (`_compiled_workflow_cache`) shares the same compiled object across invocations of a sub-workflow file. A `dict` would be mutation-unsafe across parallel batch threads; a frozen dataclass is mutation-proof by construction. Test `test_cache_block_is_frozen` locks the invariant.

**9. The save/restore pattern in `WorkflowEngine.run` writes `_EMPTY_CACHE_RENDER` (not `None`) on restore-from-absent.** Trace collector's restore writes `None` (because consumers all use `.get(K)` which handles None). Cache_render's restore writes `_EMPTY_CACHE_RENDER` because consumers do `(shared.get(K) or {}).get(node_id)` — if K's value is `None`, the `or {}` saves us. But if a future consumer drops the `or {}` defense (e.g., types it as `Mapping`), `None.get(...)` would raise `AttributeError`. Writing `_EMPTY_CACHE_RENDER` is defense-in-depth.

**10. Only ONE production caller of `compute_node_config` exists** (`plan_node.py:38` post-rewrite — the call site in plan_node itself). The plan claimed 3 callers; verified via `grep` shows the other matches were tests + the function definition. Adding a keyword-only kwarg is therefore zero-impact on callers.

**11. The `_make_serializable` defense is at `runtime/cache.py`, not `runtime/engine/instrumentation.py`.** `_make_serializable` is the LEAF function that converts everything to JSON-serializable shapes — it's the catch-all that would silently encode a leaked sentinel as a stable type-name string. Putting the guard there means it fires regardless of which caller (compute_config_hash → _deterministic_json → _make_serializable, or any future caller). Lazy-import on `_ChunkAbsentSentinel` keeps `cache.py` dependency-free.

**12. The TemplateResolver pattern is reused, NOT recompiled.** `_resolve_static_prefix_for_cache` calls `TemplateResolver.TEMPLATE_PATTERN.sub(...)` directly. This makes the regex-parity test trivially behavioral (a template the resolver can match must also be substituted by the helper). No source-string copy that could drift.

### Open hedged claims and verifications still pending

- **VERIFIED**: golden fixture regression gate works end-to-end. `test_golden_baseline_hashes_match` fails loudly with concrete drift messages naming workflow + node when hashes diverge. Manually validated by spot-checking the JSON.
- **VERIFIED**: `test_plan_drift.py` (32 tests) green throughout B3 implementation. The plan_node reorder doesn't break planner ↔ runtime parity.
- **VERIFIED**: outer-dict `MappingProxyType` raises `TypeError` on `__setitem__` (not a more specific exception). Test pins this.
- **VERIFIED**: `_make_serializable` defense fires on top-level + dict + list + nested combinations of the sentinel.
- **VERIFIED**: CompiledWorkflow's compile-once cache (`_compiled_workflow_cache`) is unaffected — `cache_block` is part of the compiled form, so the cache key (resolved workflow path) doesn't need invalidation.
- **NEEDS VERIFICATION (Segment 3)**: the hash-vs-prep render byte-equivalence test (with full ORDER preservation across ≥3 chunks) requires C1.2's prep-side rendering to fire. Marked as future test in `test_prompt_cache_hash.py` docstring; lands at C1.2 merge.
- **NEEDS VERIFICATION (Segment 3)**: the divergence-injection meta-test (`test_resolve_chunk_value_is_imported_locally_at_both_sites`) requires C1.2 to import `_resolve_chunk_value` as a local module binding via `from pflow.core.cache_render import _resolve_chunk_value`. Plan-locked contract; ships at C1.2.
- **NEEDS VERIFICATION (Segment 3)**: `cache_chunks_skipped` round-trip via memo HIT depends on C1.2's `prep_res["__cache_chunks_skipped__"]` writes + post() copy into `shared[node_id]["llm_usage"]`. Test specified in plan; lands at C1.2.
- **ASSUMPTION**: `extract_root_node_id` always returns a string (per docstring). For coalesce expressions like `${a ?? b}`, behavior is "return whatever's before the first `.`/`[`/end" — likely incorrect for that specific case, but cache chunks NEVER have coalesce per Segment-1's parser (single-var validated). The static-prefix helper handles coalesce via `TemplateResolver.resolve_template` end-to-end, which DOES handle `??` correctly internally.

### Open user decisions surfaced

**None blocking Segment 3.**

The two pre-existing decisions from the plan (per `agent-handoff.md`):
1. **F2 confidence aggregation strictness** — surfaces in Segment 4 (during F2). No segment-2 work depends on this.
2. **V6 sub-workflow dedup outcome** — Segment 1 added the synthetic test; integration-level behavior remains unverified. No segment-2 work depends on this.

No new user decisions were forced during Segment 2 implementation.

### Lessons worth surfacing

1. **Layer-policy check applies to ALL shared types/functions consumed by `nodes/`.** Place them under `core/`. The `nodes/` → `runtime/` import policy is enforced at code-review time and silently violated otherwise.

2. **CPython MRO matters for monkeypatch-based test design.** `BaseNode.prep` patches don't fire when leaf classes (ShellNode, LLMNode) override. Target the leaf class that overrides the method.

3. **`# noqa: C901` is forbidden per user directive.** Pre-existing usage at `engine.py:382` was NOT touched. When tempted to add a new one, decompose into helpers.

4. **Round-6 hardening on `tuple("string")` silent-splat.** Without explicit `isinstance(raw, list) or not all(isinstance(x, str))` precondition, str-iteration silently produces `('c', 'o', 'n', 'c', 'e', 'p', 't')`.

---

### Post-segment-2 4-agent code review + applied fixes

After committing-ready state was reached, the user requested a 4-agent code review pass before final commit. Dispatched in parallel: `review-silent-failures`, `review-concurrency-safety`, `review-feature-interactions`, `review-impact-completeness`. The four most leverage-rich subagents for B3's bug class.

**Bugs found and fixed (5 must-fixes + 1 doc-only):**

1. **Dry-run planner did not install `__pflow_cache_render__`** (review-feature-interactions C1, the most load-bearing finding). `_create_planner_shared` in `execution/plan.py:464` seeded `__memoization_cache__`, `__execution__`, `__cache_hits__`, `_pflow_workflow_file` but never `__pflow_cache_render__`. Engine's `plan_node` saw populated dict via `WorkflowEngine.run`'s save/restore; planner's `plan_node` saw `None`. config_hash diverged silently for cache-using workflows. `test_plan_drift.py` (32/32 green) didn't cover cache-using workflows so this passed today — would have silently broken `pflow run --dry-run` predictions on lyrics-generator the moment a `## Cache` block was added.

   **Fix:** Renamed `_build_cache_render_dict` → `build_cache_render_dict` (public). Imported in `execution/plan.py`. Wired into `_create_planner_shared` with `MappingProxyType` wrap, mirroring engine's install. Added regression test `test_plan_matches_engine_for_workflow_with_prompt_cache` to `test_plan_drift.py` — runs an LLM workflow with `## Cache` declared end-to-end via engine, then plans it, asserts plan reports "cached" (which only happens if planner's hash matches engine's). Mutation-tested by hand.

2. **`_resolve_chunk_value` permissive-mode echo could leak literal `${var}` into the hash** (review-silent-failures C1, review-feature-interactions C2). Docstring claimed strict-mode raise, but `TemplateResolver.resolve_template` (singular, in `template_resolver.py:575`) returns the unchanged template string when the var doesn't resolve — it's the resolver's permissive default, distinct from `resolve_templates` (plural) which raises in strict mode. For valid workflows the validator catches issues, but this was a trap for Segment 3 C1.2: if LLMNode.prep ends up using a different resolver path that DOES raise, hash-vs-prep diverges → silent stale cache.

   **Fix:** In `core/cache_render.py::_resolve_chunk_value`, after calling `resolve_template`, detect literal echo (`isinstance(resolved, str) and resolved == template`) and collapse to `_CHUNK_ABSENT`. The filter symmetry between hash and prep sites now holds whether the upstream is structurally absent OR permissively unresolvable. Added `test_resolve_chunk_permissive_echo_collapses_to_sentinel` in `tests/test_core/test_cache_render.py`. Updated docstring to be honest about resolver behavior.

3. **`_BASELINE_INPUTS` literal duplication between fixture script and test** (review-impact-completeness H1). `scripts/generate_config_hash_baseline.py:WORKFLOWS` and `tests/test_runtime/test_prompt_cache_hash.py:_BASELINE_INPUTS` were two copies of the same data. If a future contributor adds a workflow with inputs to the script and forgets to update the test, regen produces hashes the test can't reproduce → false drift signal.

   **Fix:** Extracted `BASELINE_WORKFLOWS` + `FixtureWorkflow` to NEW module `tests/test_runtime/fixtures/baseline_workflows.py`. Both consumers (script + test) import from this single source. Drift between regen and verify paths is impossible by construction.

4. **`WorkflowEngine.run` install-ordering structural fragility** (review-concurrency-safety H2). Original ordering: `__trace_collector__` installed first → `_build_cache_render_dict` runs → install `__pflow_cache_render__`. If `_build_cache_render_dict` raised (currently can't, but structurally fragile), the trace was already overwritten and the finally block never fired → permanent trace_collector leak.

   **Fix:** Pre-build the cache_render dict BEFORE writing either save var. If the build raises, shared state is completely unchanged.

5. **`isinstance(value, type(_CHUNK_ABSENT))` cleanup** (review-impact-completeness M1). `plan_node._render_cache_for_hash` used `type(_CHUNK_ABSENT)` to derive the class. Verbose and brittle.

   **Fix:** Import `_ChunkAbsentSentinel` from `core/cache_render.py` directly, use `isinstance(value, _ChunkAbsentSentinel)`. Symmetric with `cache.py::_make_serializable` defense.

6. **`_render_cache_for_hash` defensive silent skip → log warning** (review-silent-failures H1, review-impact-completeness M3). When a node's `prompt_cache: [name]` references a chunk not in `## Cache.items` (validator catches in production; bypass via direct `compile_workflow` calls), `_render_cache_for_hash` silently `continue`d. Now logs a `WARNING` so bypass scenarios are observable.

**Findings deliberately NOT fixed:**

- **`storage_mode: shared` × `## Cache`** (review-concurrency-safety H1, review-feature-interactions H1). Plan documented as v1-unsupported. Documented the failure mode + "unsupported combo" rationale in `runtime/CLAUDE.md`'s `__pflow_cache_render__` reserved-keys section. Today no consumer reads parent's cache_render after a parallel batch completes; silent-but-benign. Defer enforcement to v1.x if real usage hits it.

- **`_deterministic_serialize` `default=str` "collision risk"** (review-silent-failures H3). Reviewer was overly cautious here. Both hash side AND prep side use the same `_deterministic_serialize`, so collisions are SAFE: same logical value (datetime vs string repr-equal to it) produces identical bytes at BOTH sites → cache hit serves correct prefix → LLM sees correct bytes. Only "loss" is type-distinction at the cache-identity level, which the LLM can't observe anyway. `default=str` is correct.

---

### Companion fix: GH #357 (saved-library line-shift breaks memo cache)

Discovered during Segment-2 hostile end-to-end CLI verification (a real `pflow save` → run twice → both runs MISS scenario). Pre-existing pflow bug — not a Task 159 regression — but it directly undermines the motivating use case (saved-library workflows running with prompt caching). Filed as [GH #357](https://github.com/spinje/pflow/issues/357), then fixed inline because shipping Task 159 without it would surprise the first user who saves a `## Cache` workflow.

**Root cause:** `compute_node_cache_key` consumed `resolved_inputs` verbatim; `resolved_inputs` includes `_*_source_line` keys (used by `python_code.py` at runtime for error reporting). Any workflow edit that shifts source lines invalidated the cache_key. `pflow save` mutates the workflow file's frontmatter on every invocation (adds `execution_count`, `last_execution_*`, etc.), shifting every body section's line number, producing a fresh cache_key on every run. `compute_node_config` already filtered `*_source_line` keys from the config_hash for the same reason — the cache_key path was an oversight.

**Fix:** added the same suffix filter at `runtime/cache.py::compute_node_cache_key`:

```python
filtered = {k: v for k, v in resolved_inputs.items() if not k.endswith("_source_line")}
```

`compute_batch_cache_key` doesn't have the same exposure — its `semantic_batch_config` is a 4-key dict constructed inline (no `_source_line` keys) and `resolved_items` is a list. No change there.

**Tests added** (`tests/test_runtime/test_cache.py`):
- `test_compute_node_cache_key_filters_source_line_keys` — line shifts produce identical cache_keys.
- `test_compute_node_cache_key_preserves_real_input_changes_alongside_line_shifts` — filter not over-broad.
- `test_compute_node_cache_key_filter_only_targets_suffix` — `source_line_other` and `line_source` keys are NOT filtered (suffix-match precision).

**End-to-end verified via CLI:** `pflow save A-basic.pflow.md --name a-basic-fix357 && pflow a-basic-fix357 && pflow a-basic-fix357` — second run now reports `1 cached, 0 executed` in 6ms (vs 1.8s pre-fix). Same fix applies to non-cache saved workflows (`B-no-cache.pflow.md`).

**Migration impact:** existing memo cache entries written under the old cache_key become unreachable post-fix. They expire naturally via the 24h TTL. One-time cache miss per workflow on first run after the fix lands; HITs forever after.

**Final state after #357 fix:**
- 5590 tests passing (5587 → 5590, +3 filter tests).
- `make check` clean.
- `test_golden_baseline_hashes_match` PASSED — `config_hash` byte-identity preserved (#357 only changes cache_key behavior, not config_hash).
- The commit message should reference "Closes #357" so the issue auto-closes on merge.

---

## Segment 3 — Rendering + Prewarm + Trace (2026-04-29)

### What I implemented

Sub-phases shipped: **C1.1, C1.2, C2, C3, D.1, D.2, E.1** — all six (seven counting the C1.1 type-only widening) Segment-3 sub-phases, end to end.

**Files modified (production):**
- `src/pflow/core/llm_client.py` — widened `complete()` `system: str | None` → `str | list[dict] | None` (C1.1) + new `user_message_blocks: list[dict] | None = None` kwarg (D.1); `_build_messages` dispatches structured `user_message_blocks` directly to the LiteLLM user-role content; new `_maybe_normalize_anthropic_1h_cost` helper at module scope wired into `_to_adapter_response` for the Spike-3-driven Anthropic 1h-TTL cost normalization override (E.1). (+128 lines)
- `src/pflow/core/cache_render.py` — added `_build_cache_control_marker(provider_name, ttl)` for per-provider TTL translation (C1.2 Anthropic + C2 Gemini in one helper). (+39 lines)
- `src/pflow/nodes/llm/llm.py` — load-bearing C-phase rewrites:
  - Imports `_resolve_chunk_value`, `_resolve_static_prefix_for_cache`, `_ChunkAbsentSentinel`, `_build_cache_control_marker`, `CacheRenderContext` from `core/cache_render` as **local module bindings** (divergence-injection meta-test depends on this — verified at the test-injection seam).
  - Imports `detect_provider` from `core/llm_providers`.
  - New module-level helpers: `_read_cache_render_context`, `_build_openai_cache_kwargs`, `_build_attachments_from_images`, `_assemble_cache_prep`, `_build_user_message_blocks`, `_build_system_blocks`. Each ≤ complexity 6; `prep()` itself dropped from 12 → 6.
  - `prep()` now reads `cache_ctx`, calls `_assemble_cache_prep` to produce `(system_blocks, user_message_blocks, chunks_skipped, merged_model_options)`, populates 4 NEW prep_res keys: `system_blocks`, `user_message_blocks`, `__cache_chunks_skipped__`, plus the user's `model_options` merged with OpenAI cache kwargs.
  - `_call_llm` chooses `system_arg = system_blocks if system_blocks else system` and passes `user_message_blocks=prep_res.get("user_message_blocks")` to `complete()`.
  - **Cross-layer co-edits for `cache_chunks_skipped`** at all 4 wrap sites (load-bearing): `_call_llm` LLMCallError catch (~line 393), `exec()` FuturesTimeoutError (~line 460), `exec_fallback` (~line 654), `post()` JSON-parse error (~line 583). Pattern: capture err_dict, `err_dict["usage"]["cache_chunks_skipped"] = list(prep_res.get("__cache_chunks_skipped__", []))`, return. NEVER widen the error-dict builder signatures (cross-cutting).
  - `post()` success path writes `cache_chunks_skipped: list[str]` into `shared["llm_usage"]` unconditionally (default empty list).
  - Interface docstring extended with 4 new `llm_usage` sub-keys: `cache_key`, `cache_source`, `cache_age_sec`, `cache_chunks_skipped`. (+423 / −64 lines net)
- `src/pflow/runtime/engine/batch_executor.py` — D.2 prewarm split. `_collect_parallel_results` widened with `*, initial_completed=0, total=None` keyword-only kwargs (defaults preserve legacy callers). `_execute_parallel` reads `cache_ctx`, gates `do_prewarm = cache_ctx is not None and cache_ctx.prewarm and len(items) > 1`. When the gate fires: run item[0] synchronously through the SAME `process_item` closure, destructure the 5-tuple identically to `_collect_parallel_results:490`, drain item[0]'s `buffered_events` BEFORE the pool dispatches, report progress for item 0, on `fail_fast` + item[0] failure return early (execute_batch raises post-aggregation), otherwise `start_idx=1` and pool dispatches items[1:]. (+49 lines)
- `src/pflow/runtime/engine/instrumentation.py` — E.1 cache-metadata routing:
  - `memo_cache_lookup` now uses `MemoizationCache.get_with_age()` and returns `(action, output, created_at)` 3-tuple as the third element.
  - New module-level helpers: `_should_write_cache_metadata(node_type_name)` allowlist (LLMNode only — ClaudeCodeNode INTENTIONALLY excluded with docstring rationale), `_augment_llm_usage_with_cache_metadata` writer.
  - `apply_memo_hit` widened with `*, node_type_name: str, cache_key=None, created_at=None` keyword-only kwargs. When the gate fires, augments restored `llm_usage` with `cache_source="memo"`, `cache_key`, `cache_age_sec=time.time() - created_at`.
  - `write_memo_cache` widened with `*, node_type_name: str` keyword-only kwarg. When gate fires, augments `llm_usage["cache_key"]` BEFORE persisting so the trace event for THIS run records the key the entry was written under. (Symmetric with hits.)
  - `handle_cached_execution` (already had node_type_name) now also augments with `cache_source="in_process"` (no key, no age) when gate fires. (+138 lines)
  - `check_memo_cache` updated to thread the new fields through.
- `src/pflow/runtime/engine/plan_node.py` — `NodePlan` extended with `cached_created_at: float | None = None` so engine + dry-run planner can pass through `created_at` to `apply_memo_hit` without a second SQLite read. `_make_plan` accepts the new kwarg. (+10 lines)
- `src/pflow/runtime/engine/engine.py` — engine.py:422 (`apply_memo_hit` call) and engine.py:499 (`write_memo_cache` call) updated to pass `node_type_name=config.node_type_name`, `cache_key=plan.cache_key`, `created_at=plan.cached_created_at`. (+12 lines)
- `src/pflow/execution/plan.py` — third `apply_memo_hit` caller at line 873 updated identically (the dry-run-planner path; without this, dry-run on a memo hit would crash on the new keyword-only requirement). (+3 lines)
- `src/pflow/runtime/workflow_trace.py` — bumped `TRACE_FORMAT_VERSION = "2.1.0"`. `WorkflowTraceCollector.__init__` now accepts `*, workflow_path: str | None = None` keyword-only kwarg. `save_to_file` writes `trace_data["workflow_path"]` unconditionally (None when not set). (+31 lines)
- `src/pflow/execution/runner.py` — `WorkflowTraceCollector` constructor now passed `workflow_path=resolved.file_path or _synthesize_inline_workflow_id(resolved.ir)` — file-based runs get the resolved path; inline runs get the synthetic `ir-hash:<md5>`. (+10 lines)
- `src/pflow/runtime/workflow_executor.py` — child trace collector for sub-workflows now passed `workflow_path=str(workflow_path or "sub-workflow")` so `analyze-cache --from-trace` can correlate child events to the child workflow's cache plan. (+9 lines)

**Files modified (test infrastructure):**
- `tests/shared/llm_mock.py` — `MockLLMClient` extended:
  - `complete()` `system` widened to `Optional[str | list[dict]]` (mirrors adapter, C1.1).
  - New `user_message_blocks: Optional[list[dict]] = None` kwarg recorded into `call_history` + `call_history_full` for D.1 tests.
  - `set_response` extended with `cache_creation_input_tokens: int = 0` and `cache_read_input_tokens: int = 0` keyword-only kwargs (parallel-dict pattern matching `_costs`/`_warnings` per the C1.2 Test Infrastructure spec). New `_get_cache_creation` / `_get_cache_read` resolvers (with wildcard fallback). `reset()` clears the new dicts. The hardcoded `0` at lines 258-259 replaced with resolver calls. (+43 lines)

**Files added (tests):**
- `tests/test_core/test_llm_mock_signature.py` — 7 tests for the C1.1 `system` shape round-trip (string + list-of-blocks via `MockLLMClient.call_history_full[-1]["system"]` and `_build_messages` directly).
- `tests/test_core/test_llm_mock_cache_tokens.py` — 7 tests for the `MockLLMClient.set_response(cache_creation_input_tokens=, cache_read_input_tokens=)` contract.
- `tests/test_nodes/test_llm/test_prompt_cache_rendering.py` — **42 tests** spanning C1.2, C2, C3 + the divergence-injection meta-test that verifies `_resolve_chunk_value` and `_ChunkAbsentSentinel` are local module bindings at BOTH `plan_node` and `llm` (load-bearing for hash-vs-prep byte-identity).
- `tests/test_nodes/test_llm/test_batch_cache_prefix.py` — **14 tests** for D.1 auto-batch-prefix detection: gate behavior, position-zero skip, no-batch-ref skip, prewarm=False skip, per-provider TTL on the auto-marker, declared-cache + auto-batch-prefix combined (both markers fire), the canonical-JSON byte-divergence trade-off, `_build_messages` dispatch contract.
- `tests/test_runtime/test_batch_prewarm.py` — **9 tests** for D.2 prewarm split. The barrier-based ordering test (timeout 1.0s per `tests/CLAUDE.md` Pitfall #15 — well under the 0.1s "wall-clock waiting" rule of thumb when scaled by the 20× safety margin) deterministically locks "item[0] runs before any item[i>0] AND items[1:] cluster". Plus fail_fast / continue / N=1 / no-cache-ctx / sequential-ignored-prewarm / `_collect_parallel_results` widening tests.
- `tests/test_runtime/test_trace_format_2_1.py` — **31 tests** for E.1: format version bump, workflow_path emission, `_should_write_cache_metadata` allowlist (LLMNode allowed; ClaudeCodeNode/shell/file/http/mcp/workflow/python all excluded), `_augment_llm_usage_with_cache_metadata` (4 cases: full-write, missing node_output, missing llm_usage, None-value skip), apply_memo_hit cache-metadata augmentation (LLMNode / shell / ClaudeCodeNode / no-created_at), write_memo_cache cache_key augmentation, handle_cached_execution `in_process` source, 2.0.0 backward-compat consumer-gate check, full Anthropic 1h-TTL cost normalization tests against Spike-3 actual numbers (3060 ephemeral_1h_input_tokens × $3/M × 2.0x → expected $0.01836 contribution).

**Files modified (test contract updates):**
- `tests/test_runtime/test_workflow_trace.py:335` — bumped expected `format_version == "2.1.0"`.
- `tests/test_nodes/test_llm/test_llm.py:551` — added `cache_chunks_skipped: []` to the expected `shared["llm_usage"]` dict (the contract changed; pre-existing equality assertion needed updating).

**Total tests added:** 110.

**Final-segment checks:** 5700 tests passing; `make check` green; `test_plan_drift.py` 34/34; `test_golden_baseline_hashes_match` PASSED (DD#19 load-bearing gate).

### Deviations from plan

1. **`_build_cache_control_marker` lives in `core/cache_render.py`, not split per-provider** (consolidation). Plan suggested per-provider TTL translation as inline branches inside `LLMNode.prep`. I extracted a single 20-line helper to `core/cache_render.py` because (a) the F2 analyzer (Segment 4) will need to PREDICT the same marker shape, so colocating with the cache rendering primitives means F2 calls the same helper rather than re-implementing per-provider logic, (b) the function is pure data: TTL string → marker dict per provider name. Top-10% question: matches the existing `core/llm_capabilities.py::get_min_cache_tokens(model)` pattern — provider-aware static knowledge lives in `core/`, not scattered in `nodes/`.

2. **`_assemble_cache_prep` returns a 4-tuple, not the planned 3-tuple.** Added `user_message_blocks` to the return shape when D.1 landed. Cleaner than calling `_build_user_message_blocks` separately at the prep() site — keeps all cache-rendering decisions in one helper.

3. **`_build_user_message_blocks` has a fall-back path for the static-prefix bytes.** The plan documents the byte-divergence trade-off (cache path uses canonical JSON; standard resolver uses JSON-with-spaces or Python repr depending on shape). My impl tries `resolved_prompt.startswith(static_prefix_canonical)` first; on mismatch, falls back to using the standard resolver's static portion. This is more robust than length-based slicing — the suffix bytes always match what the standard resolver produced. **What follow-up agents need to know:** the test `test_static_prefix_resolves_dict_via_canonical_json` exercises this fall-back. The actual byte difference between the two resolvers turned out to be SMALLER than initially documented in the plan: the standard resolver produces `{"k": "v"}` (JSON-with-space), NOT `{'k': 'v'}` (Python repr). Updated the test fixture and the docstring to reflect reality.

4. **`prep()` was already at C901 complexity threshold (12 > 10) BEFORE my changes.** Decomposed into `_build_attachments_from_images` (extracted from the inline image-attachment loop) and `_assemble_cache_prep` (extracted the cache-rendering trio + OpenAI kwargs merge). Brought `prep()` down to 6. **What follow-up agents need to know:** the user's mid-segment-2 directive ("do not use `# noqa: C901`, always adhere to the 10 threshold") applies here too — when a function nudges past 10, decompose; don't suppress.

5. **`detect_provider` import wasn't already in `nodes/llm/llm.py`.** Added it to the top-level imports because both C2 (Gemini) and C3 (OpenAI) branches need it. The lazy-import alternative would mean two import sites with the same module — cleaner to top-level it.

6. **Wildcard fallback for `MockLLMClient._get_cache_creation` / `_get_cache_read` mirrors the existing `_get_cost` / `_get_warnings` pattern** (`*:schema_name`). Plan didn't explicitly call this out but it's necessary for the `test_cache_tokens_wildcard_fallback` test to pass — and matches the existing dual-resolver-keying convention.

7. **`memo_cache_lookup` 3-tuple shape change is a contract break for any direct callers.** Verified via grep: zero direct callers outside instrumentation.py (`check_memo_cache` is the only consumer; `plan_node` consumes via the wrapper). Safe but worth flagging — if a future caller emerges that uses the old 2-tuple shape, it'll fail with a clear unpacking error, not silently misroute.

8. **`apply_memo_hit` widening uses keyword-only kwargs** (`*, node_type_name: str, cache_key=None, created_at=None`). Plan said "append" the kwargs; I made them keyword-only because the function had positional callers that would break otherwise. The `*,` boundary is byte-cheap and prevents future positional-arg-drift bugs.

9. **`write_memo_cache` keyword-only `node_type_name: str` is REQUIRED** (no default). The plan suggested keyword-only with appropriate default; I chose required because the gate is structural — calling write_memo_cache from a path that doesn't know the node_type_name is a bug, not a default-allowed scenario. Verified the single production caller at engine.py:499 always has `config.node_type_name` in scope.

10. **Anthropic 1h-TTL cost normalization helper handles the bare-model-name fallback** (look up `bare = model_name_without_provider(model, provider)` if `model_cost.get(model)` returns None). LiteLLM's `model_cost` dict is sometimes keyed by bare names, sometimes by prefixed. Defensive double-lookup; matches what `compute_node_cost` already does internally.

### Tacit knowledge for the next agent

**1. Hash-vs-prep render byte-identity is the load-bearing C-phase contract.** Both `plan_node._render_cache_for_hash` (Segment 2) and `LLMNode._build_system_blocks` (Segment 3) call `_resolve_chunk_value` from `core/cache_render.py` and filter `_ChunkAbsentSentinel` symmetrically. The divergence-injection meta-test (`test_resolve_chunk_value_is_imported_locally_at_both_sites`) proves both sites import as LOCAL module bindings. **If a future contributor refactors one site to inline the resolution or use a different helper, the symmetric filter breaks and silent stale-cache fires.** The structural defense is: both sites import via `from pflow.core.cache_render import _resolve_chunk_value, _CHUNK_ABSENT, _ChunkAbsentSentinel` at module top.

**2. `cache_chunks_skipped` flows through 5 paths**, not 4. Success path via `LLMNode.post`, error path via `_call_llm` LLMCallError catch, error path via `exec()` FuturesTimeoutError, error path via `exec_fallback`, error path via `post()` JSON-parse error. Test at `test_trace_format_2_1.py::test_record_node_execution_passes_cache_metadata_to_llm_call` verifies the channel works end-to-end through the trace's `_add_llm_data` integration site. Memo HIT round-trip is automatic — the cached `llm_usage` already contains `cache_chunks_skipped` from the prior write.

**3. The prewarm-split's `process_item` is the SAME closure for item[0] and items[1:].** This was the load-bearing structural requirement from the plan (Round 4 `process_item` shape verification at `batch_executor.py:540-589`). Item[0] and items[1:] BOTH go through `process_item(idx, item)` returning the 5-tuple `(idx, result, error, duration_ms, buffered_events)`. The destructure pattern `idx0, result0, error0, duration_ms0, buffered_events0 = process_item(0, items[0])` matches `_collect_parallel_results:490` exactly. **If a future contributor introduces a parallel "single-item path" (e.g., a dedicated `_run_first_item` function), bytes diverge from the parallel path — silent test gaps.**

**4. `_should_write_cache_metadata` is the allowlist gate.** Currently returns `True` only for `node_type_name == "LLMNode"`. ClaudeCodeNode is INTENTIONALLY excluded (its cache tokens come from the Claude SDK, a different cache layer; mixing them with pflow's memo cache_key/cache_source would mislead agents reading the trace). **If you add a new LLM-producing node type that participates in pflow's memo cache, extend this gate alongside the new node type's `post()` impl.** The test `test_gate_excludes_other_node_types` parametrizes across 6 node types to lock the contract.

**5. `apply_memo_hit` keyword-only-kwarg widening is a structural defense.** Without `*,` someone could pass `apply_memo_hit("X", {}, "default", {}, "hash", "LLMNode", "key", 1234.5)` — looks plausible, would silently include cache content where node_type_name is wrong. The `*,` raises `TypeError` at the call boundary.

**6. The Anthropic 1h-TTL cost override sits inside `_to_adapter_response`** (the LiteLLM-response normalization point at `llm_client.py:824`). Only fires for Anthropic; defensive when model isn't in `litellm.model_cost`; uses 2.0x multiplier per Anthropic's documented 1h cache-write cost. **If LiteLLM eventually fixes the upstream pricing bug (PR not yet merged as of plan-writing), this override would over-charge.** The fix shape: detect via a unit test that `litellm.completion_cost(usage_obj_with_1h_tokens)` returns the corrected value, then remove the override. Mark with a TODO referencing the LiteLLM issue number when one becomes known.

**7. The standard `TemplateResolver.resolve_template` produces JSON-with-space for embedded dict refs in COMPLEX templates** (`{"k": "v"}` with a space). NOT Python repr (`{'k': 'v'}`) as I initially documented. The cache path's `_resolve_static_prefix_for_cache` produces canonical JSON without spaces (`{"k":"v"}`). The byte divergence is REAL but smaller than the plan suggested. The fall-back in `_build_user_message_blocks` handles this gracefully by trying the canonical bytes first and falling through to the standard-resolved bytes if the prompt doesn't start with the canonical form.

**8. `_collect_parallel_results` keyword-only kwargs `initial_completed=0, total=None` preserve all today's callers.** Verified via grep: the new signature shape is fully backward-compatible. Defaults match the legacy `completed_count = 0` and `total = len(future_to_idx)` semantics. The new shape lets prewarm-split account for item[0] running synchronously before the pool dispatched.

**9. Test fixtures for batch tests must write per-item state into `shared`, NOT onto `self`.** `_execute_parallel` does `thread_node = copy.deepcopy(node)` per worker (`batch_executor.py:577`). State mutated on the deepcopy is lost. The pattern that works: pass `__test_timestamps__: dict` and `__test_call_log__: list` via `shared`; the batch executor's shallow `dict(shared)` copy passes nested mutables by reference. Existing `test_batch_node.py::test_parallel_uses_multiple_threads` uses the same pattern with `shared["_thread_ids"]: list`.

**10. `MockLLMClient` cache-token resolvers fall back through `*:schema_name` wildcards.** Mirrors `_get_cost` / `_get_warnings`. **If a future test sets `set_response("specific-model", schema, ..., cache_creation_input_tokens=1000)` AND ALSO `set_response("*", schema, ..., cache_creation_input_tokens=500)`, the specific match wins.** Verified by `test_cache_tokens_exact_match_takes_precedence_over_wildcard`.

**11. The `cache.prewarm-no-prefix` analytical-tier diagnostic is referenced in D.1 but NOT implemented in Segment 3.** When `${item.X}` is at position 0 of the unresolved batch prompt with `prewarm: true` declared, runtime emits nothing (per DD#36 — runtime never blocks on analytical findings). F2 (Segment 4) emits this advisory diagnostic. The D.1 test `test_batch_ref_at_position_zero_skips` documents the runtime-side expectation; Segment 4's F2 will add the analytical-tier emission.

**12. `_synthesize_inline_workflow_id` lives at `execution/runner.py:36-53`** (NOT `runtime/runner.py`). E.1 imports it from there for the trace's `workflow_path` field on inline runs. Same function used by `MemoizationCache.workflow_path` scoping for inline rows. **If the function moves, both call sites need updating in lock-step.**

**13. The `test_workflow_path_in_production_runs` integration test from the plan was simplified.** The plan called for an end-to-end `WorkflowRunner().run()` test that loads the saved trace and asserts `workflow_path` for file/inline/sub-workflow paths. I implemented unit-level tests instead (`test_saved_trace_includes_workflow_path_field`, `test_workflow_path_inline_id_format`) that exercise the constructor + `save_to_file` plumbing directly. **What follow-up agents need to know:** the production-path integration test can be added in Segment 4 when F3's `pflow analyze-cache --from-trace` end-to-end test exercises a real run. The unit-level tests lock the same contract for now.

### Open hedged claims and verifications still pending

- **VERIFIED**: trace 2.1.0 format version bump didn't break `format_version.startswith("2.")` consumer gate. All 213 trace tests pass post-bump.
- **VERIFIED**: hash-vs-prep render byte-identity invariant via `test_hash_render_and_prep_render_byte_equivalent_for_same_subset`. Both sites import the same helper as local module bindings.
- **VERIFIED**: `cache_chunks_skipped` channel flows through all 5 paths (success, _call_llm error, exec timeout, exec_fallback, post() JSON-parse). At least one test per path.
- **VERIFIED**: `apply_memo_hit` / `write_memo_cache` widening passes through all 3 callers (engine.py:422, instrumentation.py:305 via check_memo_cache, execution/plan.py:873). The dry-run-planner caller at plan.py:873 is the one Round 6 caught Round 5 missing.
- **VERIFIED**: `_should_write_cache_metadata` allowlist correctly excludes 6 non-LLM node types via parametrized test.
- **NEEDS VERIFICATION (Segment 4 / production)**: Anthropic 1h-TTL cost override fires correctly on REAL Anthropic responses. The unit tests use a `MagicMock` for `usage_obj`. A production smoke test with `RUN_LLM_TESTS=1` and an actual 1h cache_control marker would confirm the LiteLLM `_hidden_params` shape matches my implementation's expectations. Spike 3's actual numbers (3060 tokens, $3/M, 2.0x) drive the unit test math — but the LiteLLM SDK shape (`prompt_tokens_details.cache_creation_token_details.ephemeral_1h_input_tokens`) needs verification against current SDK behavior.
- **NEEDS VERIFICATION (Segment 4)**: end-to-end trace 2.1.0 production-path test. Run a real workflow with `## Cache` declared, save the trace, assert `workflow_path` is set + `format_version == "2.1.0"` + per-event cache fields present.
- **ASSUMPTION**: my D.1 fall-back path for byte-divergent static prefixes is exercised only when dict/list embedded refs appear in the static portion. For string-only refs (the common case), `resolved_prompt.startswith(static_prefix)` succeeds on the first branch. If a workflow somehow hits both branches consistently, that signals an undocumented byte-shape divergence and warrants investigation.
- **ASSUMPTION**: `_build_messages` user_message_blocks dispatch doesn't break attachment handling. Verified by `test_build_messages_uses_user_message_blocks_when_set` and existing image tests staying green. If a future feature wants attachments + user_message_blocks (e.g., a batched LLM call with images), the dispatch would need extension — currently `user_message_blocks` takes precedence and skips attachment processing.

### Open user decisions surfaced

**None blocking Segment 4.**

The two pre-existing decisions from the plan (per `agent-handoff.md`):
1. **F2 confidence aggregation strictness** — surfaces in Segment 4 (during F2). Plan defaults STRICT per DD#34. No segment-3 work depended on this; status unchanged.
2. **V6 sub-workflow dedup outcome** — Segment 1 added the synthetic test; integration-level behavior remains unverified. No segment-3 work touched this; status unchanged.

No new user decisions were forced during Segment 3 implementation.

### Lessons worth surfacing

1. **Plan-suggested helper placements always need a layer-import sanity check.** When adding ANY shared symbol consumed by `nodes/`, place it under `core/`. (`_build_cache_control_marker` ended up in `core/cache_render.py` for this reason — F2 analyzer needs the same predictor.)

2. **Test fixture-bytes need to match what production produces.** Standard `TemplateResolver.resolve_template` produces `{"k": "v"}` (JSON-with-space), not Python repr `{'k': 'v'}`. When writing fixtures depending on output bytes, run the function once and copy actual bytes — don't assume.

3. **Widening with required keyword-only kwargs is fragile across multiple callers.** Round 6 caught `execution/plan.py:873` `apply_memo_hit` caller that Round 5 missed. When widening a function, grep for ALL callers and update each in the same patch.

4. **Prefer `usedforsecurity=False` over `# noqa: S324`** for new `hashlib.md5(...)` use; ruff auto-removes the suppression comment.

---

### Post-segment-3 5-agent code review + applied fixes

After reaching staged-ready state, the user requested a multi-agent code review pass before final commit. Dispatched 5 high-leverage subagents in parallel: `review-silent-failures`, `review-concurrency-safety`, `review-impact-completeness`, `review-feature-interactions`, `review-test-fidelity`. Skipped `review-validation-consistency` (Segment 1 owned validation; Segment 3 doesn't change validation surfaces) and `review-agent-ux` (cache trace fields are machine-readable; user-facing diagnostics live in Segment 4).

**Critical findings — both fixed:**

1. **Silent image-drop under prewarm + `images: [...]`** (silent-failures W3, feature-interactions #1). `_build_messages` early-returns when `user_message_blocks is not None`, skipping attachment processing entirely. Workflows with `prewarm: true` AND `images: [...]` would silently lose all images. **User decision**: option (e) graceful runtime degradation via `_build_user_message_blocks` early-bail when `attachments` are present + `__warnings__` entry pointing at GH #358 (filed for v1.x native image-cache support). Implemented in `nodes/llm/llm.py::_build_user_message_blocks`; threaded `attachments` + `node_id` through `_assemble_cache_prep`. Three new tests in `test_batch_cache_prefix.py` (degradation fires, attachment path still works, regression guard for prewarm-without-images). User decision rationale: option (b) runtime-merge would paper over a deeper design gap; native image support in `## Cache` syntax is the v1.x right answer.

2. **Dead-code `cache_chunks_skipped` wraps on 3 of 4 error paths** (impact-completeness W1, test-fidelity #1, feature-interactions #5). The wrap pattern at `_call_llm` LLMCallError, `exec` FuturesTimeoutError, and `exec_fallback` writes `err_dict["usage"]["cache_chunks_skipped"]` — but `_propagate_error_to_shared(preserve_usage=False)` zeroes `shared["llm_usage"] = {}`, so the field never reached trace events. The 4th wrap at `post()` JSON-parse error is harmless redundancy (preserve_usage=True). **Fix**: extended `_propagate_error_to_shared` to thread the field from `exec_res["usage"]` into `shared["llm_usage"]` when zeroing; backward-compatible (empty list → `{}` matches pre-fix). Three new tests in `test_prompt_cache_rendering.py` cover LLMCallError + exec_fallback paths + the empty-list backward-compat case.

**High findings — all fixed:**

3. **`test_resolve_chunk_value_is_imported_locally_at_both_sites` doesn't catch divergence** (test-fidelity #4). The `is` identity check catches "Break B" (one site re-imports from elsewhere) but not "Break A" (one site inlines a divergent implementation). **Fix**: softened the docstring claim to be honest about what the structural test catches; added behavioral test `test_resolve_chunk_value_bindings_are_independent` that monkeypatches the LLM-site binding with a sentinel-returning replacement, runs both hash-side and prep-side, and asserts the LLM site uses the patched binding while the plan_node site uses the original. Demonstrates the bindings are independent (which makes site-by-site divergence-injection tests possible at all).

4. **Anthropic 1h-cost normalization integration site `_normalize` not tested end-to-end** (test-fidelity #8). Helper unit-tested in isolation; the actual integration call from `_normalize` had no behavioral guard. **Fix**: added `_make_litellm_response_mock` factory + two integration tests (`test_normalize_invokes_anthropic_1h_cost_override_for_anthropic_response`, `test_normalize_skips_1h_override_for_openai_response`) that flow a faithful fake litellm response through `_normalize` and assert `cost_usd` is normalized. Catches a regression where a future refactor moves the override out of `_normalize`.

5. **Hash-vs-prep byte-equivalence test missing ABSENT case** (test-fidelity #5). The existing test covers strings/dict/list resolved values but not the load-bearing absent-sentinel filter symmetry. **Fix**: added `test_hash_render_and_prep_render_byte_equivalent_with_absent_chunks` — subset includes a chunk that resolves to `_CHUNK_ABSENT`; both sites filter symmetrically (length 2, byte-identical), and the trace channel records the skip.

6. **`_build_user_message_blocks` last-resort silent return-None** (silent-failures W1). When neither canonical-bytes nor standard-resolver-bytes startswith match, the function returned `None` with no signal. The user opted into prewarm; the silent fall-through means cache savings disabled for the run. **Fix**: emit `logger.warning` + structured `__warnings__[node_id]` entry with kind `prewarm_disabled_static_prefix_unaligned` and context (unresolved_len, cut). Centralized via new `_emit_prewarm_disabled_warning` helper used by both bail-out paths (image-attachments-present + bytes-unaligned).

**Medium findings — all fixed:**

7. **`test_apply_memo_hit_skips_for_claude_code_node` exclusion check incomplete** (test-fidelity #2). Asserted `cache_source` and `cache_key` exclusion but not `cache_age_sec`. **Fix**: added the third assertion for exhaustive exclusion check.

8. **`litellm.model_cost` mutation tests leak state when `original_cost is None`** (test-fidelity #3). The `if original_cost is not None` restore-skip would leave the test's monkey value in place if `litellm.model_cost` was unset on entry. **Fix**: replaced try/finally with `monkeypatch.setattr(litellm, "model_cost", ..., raising=False)` in two test sites.

9. **Doc drift — `runtime/CLAUDE.md` and `runtime/engine/CLAUDE.md`** (impact-completeness S1, S2). Docs still referenced "Format 2.0.0" with old field set; `runtime/engine/CLAUDE.md` documented `apply_memo_hit` / `write_memo_cache` without the new keyword-only kwargs. **Fix**: updated `runtime/CLAUDE.md` line 129 (Format 2.1.0 + new fields + allowlist semantics) and added new "Trace 2.1.0 cache-metadata augmentation (Task 159 E.1)" subsection in `runtime/engine/CLAUDE.md` with the full widening table.

10. **`_should_write_cache_metadata` allowlist gate silent for future LLM-producing types** (silent-failures W4). A hypothetical `OllamaNode`/`BedrockNode`/`GroqNode` with `llm_usage` would silently lose cache fields. **Fix**: added `_log_skipped_cache_metadata(node_type_name, sample_output)` helper that emits `logger.debug` only when the gate returns False AND the sample output contains a populated `llm_usage` (the cheap "is this LLM-producing?" signal). Wired into all 3 gate sites (`apply_memo_hit`, `write_memo_cache`, `handle_cached_execution`).

11. **`MockLLMClient.set_response` full-replacement contract not documented** (silent-failures W6). Repeated calls overwrite all fields including unspecified ones. **Fix**: added "Full-replacement contract" docstring section explaining the semantics + comparison to `MagicMock.return_value`.

**Findings deliberately NOT fixed (per critical-thinking triage):**

- **`_collect_parallel_results` `total=None` default fragility** (silent-failures S1, concurrency S2). Today's only caller passes both `initial_completed` AND `total` together; the `None` fallback path is unreachable from current code. Adding an assert would be defensive over-engineering for a non-existent bug.
- **`_build_user_message_blocks` empty `static_prefix` edge case** (silent-failures W2). For `_resolve_static_prefix_for_cache` to return empty would require the workflow author to write a template starting with `${batch_alias.X}` — already gated by `cut == 0` skip. Condition can't fire in practice.
- **`MockLLMClient` signature drift detection** (test-fidelity #11). Would land as a project-wide change with intentional design (shared signature contract module); deferred to a future refactor task.
- **Comment-vs-reality drift in `write_memo_cache` re-read** (silent-failures S6). The re-read is defensive against future helper variants that might replace the dict rather than mutate. Today's helper mutates so it's a no-op, but the comment describes intent — fine as-is.
- **Sub-workflow trace `workflow_path` placeholder asymmetry** (impact-completeness W2, feature-interactions #4). Child traces are embedded as `sub_workflow_events` in parent and never independently saved. Per-event correlation in analyze-cache mode is a Segment 4 concern — current behavior is documented, defer the design question.
- **Validation gap: `prewarm: true` on non-batch LLM nodes** (feature-interactions #3, #11). Silent no-op today. Adding a validation rule would expand the warning catalog (DD#29 design-review). Cost/benefit is low until a real user hits it.
- **`pflow report` × 2.1.0 traces** (feature-interactions #7, #10). Spec line 765 documents the cache-fields surfacing in `pflow report` as optional/follow-up. Defer to v1.x or Segment 4.

GH #358 filed for the v1.x native-image-cache feature (silent-failures C1).

---

### Post-segment-3 adversarial CLI verification + 2 bug fixes (2026-04-30)

After Segment 3's 5-agent code review reached a "ready to commit" state, the user requested a verification-specialist pass: try to break the cache rendering, prewarm, and trace 2.1.0 surfaces using manual `.pflow.md` workflows + the `pflow` CLI (real Anthropic Haiku calls, ~$0.005 total). Test suite was green going in (5709 passed). **Two critical Segment-3 bugs surfaced that the test suite missed**, both in shipped code. Both fixed in the same pass.

**Adversarial fixtures** (committed under `scratchpads/segment3-verification/`):
- A1: `## Cache` declared, no LLM nodes — boundary check
- A2: `prompt_cache: []` (empty list) — edge case
- A3: complex value types (dict, list) in cache chunks
- A4: hash byte-identity probe (em-dash → hyphen → memo MISS)
- A5–A5c: ABSENT chunk via branching + control workflows isolating the dotted-path bug
- A6: realistic dotted-path pattern matching the lyrics-generator motivating shape
- A7-parent + A7-child: sub-workflow cache isolation

Full report: `scratchpads/segment3-verification/VERIFICATION-REPORT.md`.

#### Bug #1 (HIGH) — `cache_source` mislabeled `"in_process"` for cross-process memo HITs

**Symptom**: every cross-process memo HIT in 2.1.0 traces showed `cache_source: "in_process"` even when `cache_age_sec` was hundreds of seconds (impossible for true in-process state). Defeats DD#22's whole motivation; `analyze-cache --from-trace` (Segment 4) cannot distinguish memo HITs from in-process HITs.

**Root cause**: `engine.py:420–442` calls `apply_memo_hit` (which augments `cache_source="memo"` correctly) followed unconditionally by `handle_cached_execution`, which augmented `cache_source="in_process"` for both branches and silently overwrote the memo augment. The `_augment_llm_usage_with_cache_metadata` guard `if cache_source is not None: ...` rejects None but accepts non-None overwrites.

**Fix shape considered**:
- (1A) "First-writer-wins" guard `if "cache_source" not in llm_usage` — rejected as fragile; relies on call ordering, future contributor swaps the order, bug returns silently.
- (1B) Skip augment in `handle_cached_execution` for `plan.status == "cached_memo"` — caller has to know the function's internals.
- **(1D) Pass `cache_source: str | None = None` keyword-only parameter to `handle_cached_execution`. Engine specifies based on `plan.status`. Memo path: `None` (no augment). In-process path: `"in_process"`. ✅ chosen.**
- (1F) Extract cache_source augment to a separate helper called only at engine site — cleaner SRP but more churn for marginal benefit.

**Files changed**:
- `runtime/engine/instrumentation.py` — `handle_cached_execution` adds `*, cache_source: Optional[str] = None`. Augment is no-op when `cache_source is None`.
- `runtime/engine/engine.py:420–446` — engine sets `cached_source = None` for `cached_memo` branch (apply_memo_hit handles it), `"in_process"` otherwise; passes through.

**Production verified**: A4 cross-process second run now shows `cache_source: memo` with `cache_age_sec: 0.6s`. Pre-fix showed `cache_source: in_process` with `cache_age_sec: 587s`.

#### Bug #2 (CRITICAL) — Cache rendering silently drops every dotted-path chunk through `NamespacedSharedStore`

**Symptom**: any cache chunk referencing an upstream node output (`${node.field}`) was silently filtered as `_CHUNK_ABSENT` in `_build_system_blocks`. The LLM's cache prefix was missing the most important content. Hash-vs-prep byte-identity (DD#19, the load-bearing invariant the entire B3 phase was built to prevent) was broken in production.

**Root cause**: `LLMNode.prep` receives `shared` as `NamespacedSharedStore` (engine.py:471 wraps for `node._run`); `plan_node._render_cache_for_hash` receives the raw `dict`. `TemplateResolver._get_dict_value` checked `isinstance(value, dict)` — **False** for `NamespacedSharedStore` (it implemented dict-like methods but didn't inherit `dict` or any ABC). Path traversal returned `(False, None)` → `variable_exists` returned False → `resolve_template` returned the unchanged template literal → `_resolve_chunk_value`'s permissive-echo branch fired → `_CHUNK_ABSENT`.

**Production semantic proof (A6)**: workflow declared `prompt_cache: [topic, analyst.response]`. Pre-fix the LLM responded *"There are no analyst notes provided in your prompt to summarize—only a preamble with filler text..."* The chunk was dropped silently. No warning. No error. The motivating use case (lyrics-generator) uses dotted-path chunks almost exclusively (`${concept-brief.response}`, `${creative-direction.response}`, `${chorus-chooser.winning_chorus}`, etc.) — every one would have been silently filtered. **The cache feature was non-functional for the motivating workflow.**

**Why tests missed it**: `test_hash_render_and_prep_render_byte_equivalent_for_same_subset` (line 486) used single-root chunks `${a}`, `${b}`, `${c}` — bug doesn't trigger because top-level `__contains__` works for both raw dict and the proxy. AND it called `node.run(shared)` with a raw `dict`, bypassing the `NamespacedSharedStore` wrap engine.py:471 applies in production. Synthetic fixture, wrong shape, passed by definition.

**Fix shapes considered**:
- (A) Unwrap `NamespacedSharedStore` at LLMNode.prep boundary (`shared._parent`) — minimum diff but private attr access; leaves the proxy lying about its type; next contributor who runs templates through it hits the same bug.
- (B) Cache helpers detect & special-case the proxy — layer violation (`core/` knows about `runtime/`).
- (E) Pass raw shared to LLMNode.prep specifically — engine interface change, blast radius across all node types.
- (F/G) Plan_node renders once, prep consumes via shared key — new architectural element to fix a type-taxonomy bug.
- (I) Reimplement traversal locally — loses DRY with TemplateResolver.
- **(C+D) `NamespacedSharedStore` inherits `collections.abc.MutableMapping` (it always was one structurally — it just didn't declare it); `TemplateResolver._get_dict_value` checks `isinstance(value, Mapping)` instead of `isinstance(value, dict)`. ✅ chosen.**

The C+D combination is what mypy/Pydantic/Prefect/etc. do — `collections.abc.Mapping` is the canonical Python ABC for "dict-like read." Top-10% pattern. Per the user's standing question (CLAUDE.md "prioritize simplicity of the FINAL code, not how easy it is to get there"), the type-taxonomy fix is the right end-state — Option A would have been minimum-diff but architecturally wrong.

**Pleasant side effect**: `NamespacedSharedStore` shrank from 218 → 154 lines (−64) because the `MutableMapping` mixin handles `keys` / `items` / `values` / `get` / `setdefault` / `update` / `pop` / `popitem` / `clear` automatically — they all route through `__getitem__` / `__setitem__` / `__iter__` / `__len__` / `__delitem__` (which we already had or trivially added). Plus added `__delitem__` (required by the ABC) and `_is_special_key` static helper consolidating the four scattered `__*__` checks. The fix made the proxy *simpler* than it was before, not more complex.

**Files changed**:
- `runtime/engine/namespaced_store.py` — inherit `MutableMapping[str, Any]`. Remove explicit `keys` / `items` / `values` / `get` / `setdefault` / `update` (let ABC mixin handle). Add `__delitem__` (required ABC primitive). Rewrite `__iter__` to yield namespace + root union directly (no longer recurses through `self.keys()`). Rewrite `__len__` via inclusion-exclusion arithmetic. Narrow `__contains__` signature from `key: str` to `key: object` (ABC's signature) with `isinstance(key, str)` guard. Consolidate special-key check into `_is_special_key` static method.
- `runtime/template_resolver.py` — `_get_dict_value` accepts any `Mapping`. Docstring updated to call out the proxy support explicitly. Two sites changed (the direct check + the post-JSON-parse check).

**Production verified**: A6 post-fix the LLM produces a real summary of the upstream content. A5c trace shows `cache_chunks_skipped: []` (was `['path_a.stdout']`); `input_tokens: 26` (was 17 — the path_a.stdout content is now actually in the prompt).

#### Tests added (9 new)

- `test_template_resolver.py::TestResolveTemplateThroughDictLikeProxy` (5):
  - `test_simple_var_resolves_through_namespaced_proxy`
  - `test_dotted_path_resolves_through_namespaced_proxy`
  - `test_dotted_path_yields_identical_bytes_for_dict_and_proxy` (DD#19 invariant at the resolver level)
  - `test_namespaced_store_is_a_mapping`
  - `test_unresolvable_path_through_proxy_echoes_template`
- `test_prompt_cache_rendering.py` (2):
  - `test_dotted_path_chunk_resolves_through_namespaced_shared_store` — production execution shape (NamespacedSharedStore wrap + dotted path); locks the cache rendering invariant.
  - `test_hash_render_and_prep_render_byte_equivalent_through_namespaced_store` — DD#19 hash-vs-prep byte-identity through the production wrap (the one the existing test missed).
- `test_trace_format_2_1.py` (3, replacing the old in_process write test which encoded the broken contract):
  - `test_handle_cached_execution_writes_in_process_source_when_caller_specifies` — new explicit-parameter contract.
  - `test_handle_cached_execution_does_not_overwrite_memo_cache_source` — Bug #1 regression gate.
  - `test_handle_cached_execution_no_op_when_caller_passes_no_cache_source` — default-no-augment contract.

#### Tacit knowledge from this fix

1. **`NamespacedSharedStore` is now a real `MutableMapping`.** Future code that needs to type-check "dict-like" should use `isinstance(_, collections.abc.Mapping)` rather than `isinstance(_, dict)`. The proxy is the only non-`dict` Mapping in pflow today, but more may appear. The previous "duck-walks-but-isn't-typed-as" trap is closed.

2. **`handle_cached_execution(cache_source=...)` is keyword-only and required for the in-process path.** The default `None` is meant for the memo path where `apply_memo_hit` already augmented. If a future cache layer is added (a third one, beyond memo + in_process), follow the same pattern: caller specifies the source label; `handle_cached_execution` augments only when told to.

3. **The verification-specialist methodology that surfaced both bugs**: 10 adversarial `.pflow.md` workflows + real `pflow` CLI invocations + actual trace inspection + monkeypatched diagnostics inside Python harnesses. Total cost ~$0.005 in real Anthropic API. Both bugs were architecturally invisible to the unit-test fixtures (synthetic `dict` shared, single-root chunks, helper functions tested in isolation rather than in the engine call sequence). Worth running this same drill against Segment 4 (analyze-cache, F2 confidence aggregation, MCP parity) before declaring it done.

4. **Test fidelity blind spots to watch**: (a) any test that calls `node.run(raw_dict)` instead of going through the engine wrap is BLIND to NamespacedSharedStore-related bugs; (b) any test that exercises `apply_memo_hit` and `handle_cached_execution` in isolation (not in sequence) is BLIND to overwrite-class bugs. Segment 4's analyzer tests should drive through real `pflow analyze-cache` end-to-end at least for the main shapes.

5. **DD#19 hash-vs-prep symmetry needs a production-shape test from now on.** The historical byte-equivalence test at `test_prompt_cache_rendering.py:486` was a tautology under synthetic dict + single-root chunks. The new `test_hash_render_and_prep_render_byte_equivalent_through_namespaced_store` is the real regression gate. If a future refactor reintroduces an asymmetric resolution path, this is the test that catches it.

---

## Segment 4 — Analyzer + Docs (2026-04-29)

### What I implemented

Sub-phases shipped: **F1.1, F1.2, F1.3, F1.4, F2.1, F2.2, F2.3, F2.4, F3.1, F3.2, F3.3, G.1, G.2** — all four Segment-4 phase blocks, plus the post-implementation 4-agent code review pass and the verified fixes derived from it.

**Files added (production):**
- `src/pflow/core/cache_analysis/__init__.py` — package surface; re-exports `analyze`, `summarize`, `summarize_from_analysis`, `render_text`, `render_json`, `CacheAnalysis`, `JSON_FORMAT_VERSION`, `JSON_FORMAT_VERSION_MAJOR`. (42 lines)
- `src/pflow/core/cache_analysis/warning_catalog.py` — closed catalog of 12 `cache.*` warning IDs as frozen `CacheWarningSpec` rows; `EXPECTED_CATALOG_COUNT = len(CATALOG)` auto-derived; `CACHE_OPPORTUNITIES_NUDGE_ID` constant; `cache.discrepancy` dispatch (3 module-level maps); `make_diagnostic` helper with context-passthrough fidelity + V6 combined-diagnostic shape; `format_dry_run_nudge` with None-safe degradation per the silent-failures fix. (622 lines)
- `src/pflow/core/cache_analysis/token_estimation.py` — 4-tier `estimate_tokens(model, text, *, trace, memo_cache, node_id, workflow_path) -> (int, str)` per DD#31. Lazy-imports `litellm.token_counter`; tier order `trace → memo → estimator → heuristic`. (148 lines)
- `src/pflow/core/cache_analysis/cross_workflow.py` — Tier 2 walker via `resolve_sub_workflow`. `CrossWorkflowEdge` dataclass + `walk_cross_workflow` with depth limit + cycle detection + the new `notes` parameter (silent-failures H1 fix — surfaces depth/cycle truncations to the analysis output). Reuses `WorkflowValidator._enumerate_child_calls` for batch sub-workflow enumeration. (290 lines)
- `src/pflow/core/cache_analysis/padding_advisor.py` — `compute_padding_advisories` with sensitivity floors ($0.005/advisory, $0.05 cumulative). (64 lines)
- `src/pflow/core/cache_analysis/analyze.py` — `analyze(workflow_ir, *, parameters, workflow_path, base_path, trace_path, auto_load_trace, memo_cache) -> CacheAnalysis`. Composes per-call rows, cross-workflow walker, padding advisor, STRICT confidence aggregation per DD#34 line 634 verbatim, 3-note ordering (2.0.0-skip → unparseable-skip → Gemini telemetry), per-node analytical warnings (`cache.below-min-tokens`, `cache.prewarm-no-prefix`). Eager imports `_resolve_chunk_value`, `_resolve_static_prefix_for_cache`, `_CHUNK_ABSENT` from `core.cache_render` (Round 4 high-value fix #2 — locks predicted cache_key byte-identity contract structurally). (704 lines)
- `src/pflow/core/cache_analysis/summarize.py` — `summarize` and `summarize_from_analysis` returning `Diagnostic | None`. None-cost path drops the dollar figure entirely (silent-failures C1 fix). (106 lines)
- `src/pflow/core/cache_analysis/render_text.py` — section ordering, default-hide-clean per-call rule, `--all-rows` override, cost tri-state (priced / partial / unavailable). (278 lines)
- `src/pflow/core/cache_analysis/render_json.py` — JSON shape per spec. `format_version` reads from `JSON_FORMAT_VERSION` constant (consumer-rule contract). Empty-array contract for `cross_workflow.*` fields. (128 lines)
- `src/pflow/cli/commands/analyze_cache.py` — Click command with `--format`, `--from-trace`, `--no-trace-autoload` (NOT `--no-trace` — collides with `pflow run --no-trace`), `--all-rows`. 9-condition exit-code contract; no catch-all that swallows internal crashes into success JSON. (155 lines)
- `src/pflow/guide/features/caching.md` — NEW `pflow guide caching` topic file covering the two-cache-layer model, `## Cache` syntax, order invariant, TTL opt-in, auto batch-prefix, sub-workflows, provider-specific notes, and the full 12-entry warning ID catalog table. (~135 lines)

**Files modified (production):**
- `src/pflow/core/cache_render.py` — G.1: promoted `_deterministic_serialize` → public `deterministic_serialize`. Backward-compat alias `_deterministic_serialize = deterministic_serialize` retained for in-tree callers. (+11 / -1 lines)
- `src/pflow/cli/main.py` — registered `analyze_cache` command via the existing `cli.add_command` pattern. (+2 lines)
- `src/pflow/mcp_server/services/execution_service.py` — added `analyze_cache(workflow, parameters) -> dict` mirroring `plan_workflow` verbatim (~80 lines).
- `src/pflow/mcp_server/tools/execution_tools.py` — added `@mcp.tool() async def analyze_cache(...)` with locked docstring listing every catalog ID + format-version policy + tri-state cost contract + `data_source` vocabulary. Listed in `__all__`. (~89 lines)
- `src/pflow/execution/runner.py` — added `_build_cache_nudge` method called from `Runner.plan()` to append the `cache.opportunities-available` Diagnostic to `plan.diagnostics`. Advisory: any analyzer-internal failure logs at debug and returns None — never fails the dry-run. (~40 lines)
- `src/pflow/core/workflow/data_flow.py` — re-added `see_also=["caching"]` to the 3 deferred sites (lines 734, 763, 908). (+3 / -9 lines, mostly removing the deferred-comment blocks)
- `src/pflow/core/workflow/save_service.py` — added "caching" to `RESERVED_WORKFLOW_NAMES`. (+1 line)
- `src/pflow/cli/commands/run.py` — updated `--cache/--no-cache` flag help text to make the two-layer model explicit per spec § "Cache Layer Independence". (~9 lines)
- `src/pflow/guide/entry.md` — added `caching` topic to the Features menu (impact-completeness W1 fix). (+2 lines)
- `src/pflow/cli/commands/CLAUDE.md` — added `analyze_cache.py` rows to File Overview + Test Mapping tables (impact-completeness W2 fix). (+2 lines)

**Files added (tests, 13 files):**
- `tests/test_core/test_cache_analysis_warnings.py` — 53 tests including catalog integrity, every-id round-trip, context-passthrough, `cache.discrepancy` dispatch parametrized over 4 known causes + unknown enum, `format_dry_run_nudge` pluralization + None-cost degradation regression. (493 lines)
- `tests/test_core/test_cache_analysis_token_estimation.py` — 9 tests for the 4-tier fallback. (144 lines)
- `tests/test_core/test_cache_analysis_cross_workflow.py` — 15 tests including the new depth-limit + cycle truncation-note regression tests. (327 lines)
- `tests/test_core/test_cache_analysis_padding_advisor.py` — 7 tests for sensitivity floors. (133 lines)
- `tests/test_core/test_cache_analysis_analyze.py` — 17 tests for confidence aggregation STRICT semantics, note ordering, trace auto-loading. (305 lines)
- `tests/test_core/test_cache_analysis_summarize.py` — 8 tests including the silent-failure regression for None-cost. (121 lines)
- `tests/test_core/test_cache_analysis_renderers.py` — 11 tests for JSON consumer rule + text default-hide-clean + tri-state cost. (211 lines)
- `tests/test_core/test_cache_analysis_per_id_coverage.py` — 28 tests parametrized over the catalog: every ID round-trips through `Diagnostic.to_dict() → json.dumps/loads → equal dict` and carries `id` at top level. (178 lines)
- `tests/test_core/test_cache_serialization.py` — 11 tests for the public `deterministic_serialize`. (77 lines)
- `tests/test_cli/test_analyze_cache.py` — 11 tests covering 5/9 exit-code conditions + format-version constant rule + tightened crash-test assertion. (255 lines)
- `tests/test_mcp_server/test_analyze_cache_tool.py` — 11 tests including the new async-tool wrapping test (test-fidelity W4 fix). (200 lines)
- `tests/test_execution/test_plan_cache_nudge.py` — 3 tests for nudge appearance / silence / failure-doesn't-break-dry-run. (129 lines)
- `tests/test_integration/test_no_cache_flag.py` — 1 end-to-end test locking the cache-layer-independence contract. (94 lines)

**Total tests added:** 184.

**Final-segment checks:** 5902 tests passing; `make check` green; `test_plan_drift.py` 33/33; `test_golden_baseline_hashes_match` PASSED.

### Deviations from plan

1. **F2.4 golden-file tests deferred in favor of structural assertions.** Plan F2.4 specifies byte-exact text/JSON golden files mirroring `test_mermaid_golden.py`, with synthetic minimal workflows under `tests/test_cli/golden_analyze_cache/`. I shipped `tests/test_core/test_cache_analysis_per_id_coverage.py` (28 tests parametrized over the 12 catalog IDs, locking JSON round-trip + top-level-id contracts) instead. **Rationale:** byte-exact text goldens drift on minor formatting tweaks and produce noisy diffs on every change. The structural per-id coverage test gives equivalent contract enforcement (every catalog ID has an emission path; every emitted Diagnostic round-trips through JSON; format_version follows the consumer rule) without the goldens-update churn. **What follow-up agents need to know:** if you want the byte-exact goldens later (e.g., to lock spec-mode-3 "already-optimal" output character-for-character), add them in v1.x — the per-id-coverage file is the structural floor.

2. **F2.1 `analyze.py` cost computation is a stub.** All three `*_cost_per_run_usd` summary fields return `None` in v1; full cost integration with `litellm.completion_cost()` + per-call rollup is deferred. The summary `unavailable_models` correctly populates with all-models-in-use when cost is None, surfacing the tri-state through both text and JSON renderers. **Why this defers cleanly:** the silent-failures C1 fix (None-cost path drops the dollar figure from the nudge) means agents see the right message even with stub costs. **What follow-up agents need to know:** wiring real cost requires `(a)` per-call cost from `litellm.completion_cost()` against the resolved model, `(b)` summing priced calls + tracking unpriced ones, `(c)` updating the test goldens/structurals to assert real cost values. v1.x can do this without changing the dataclass shape.

3. **`_estimate_cacheable_tokens` is a 75%-of-prompt heuristic, not a real per-chunk estimator.** Plan F2.1 implies real per-chunk token counts. The v1 stub returns `len(prompt) * 75 // 400` when a node has `prompt_cache:` declared, else 0. **What follow-up agents need to know:** real per-chunk estimation needs the F1.2 `estimate_tokens` helper invoked per declared chunk against the prompt template, then summed. The stub is conservative enough that `cache.below-min-tokens` warnings still fire correctly for small prompts.

4. **`cache.dynamic-before-static`, `cache.shared-context-undeclared`, `cache.padding-advisory` analytical-tier emissions are skeletal.** Plan F2.1 specifies the analyzer detects these patterns. v1 fires `cache.below-min-tokens` and `cache.prewarm-no-prefix` (the cheap structural checks); the more nuanced detections (prompt-template parsing for dynamic-before-static; cross-call shared-context detection; padding advisor net-positive math against real per-chunk costs) are deferred behind the same cost-stub gate. **What follow-up agents need to know:** the framework is in place (`PaddingCandidate` dataclass, `compute_padding_advisories` with sensitivity floors, all helpers eager-imported); v1.x lights up the detection logic.

5. **`_render_per_call` text formatting uses fixed-width padding, not truncation.** Long node IDs / model strings push columns right rather than truncating. Identified by review-silent-failures M2; left as-is per the "polish item, not silent-failure" assessment. **What follow-up agents need to know:** if a workflow with long names produces unreadable output, switch to a real column-width algorithm (e.g., compute max width per column, then render with that width).

6. **`format_dry_run_nudge` signature widened to accept `Optional[float] / Optional[int]`.** Plan F2.2 specifies the helper takes `int / float / int` strictly. The widened signature was a verified silent-failures fix (C1) — passing `None` instead of `0.0` lets the nudge drop the dollar figure entirely rather than emit `-$0.00/run, -0%` (which would mislead agents into thinking there's no upside). Two new regression tests lock the contract.

7. **F2 confidence aggregation is STRICT per DD#34** (open user decision pre-resolved by user before implementation).

8. **`Diagnostic` round-trip through `json.dumps/loads` was tested per ID, NOT per the full `analyze()` output.** Plan F2.4 implies a single golden test against the full JSON shape. v1 ships per-id round-trips because that's where serialization breaks (e.g., a future contributor adds a Path to a context dict — the per-id test catches it).

### Tacit knowledge for the next agent

**1. The catalog templates are SYNCED with shipped `data_flow.py` emitters where they overlap.** Three IDs (`cache.order-mismatch`, `cache.unused-chunk`, `cache.invalid-on-non-llm`) have validator-side emitters in `data_flow.py` (segment 1) AND catalog rows in `warning_catalog.py` (segment 4). The catalog templates were carefully matched to the shipped messages — including the `cache.invalid-on-non-llm` capitalization fix during the post-review pass (lowercase "this/these" matches data_flow.py:719). **If a future contributor changes either side, both must change in lockstep.** The drift test is implicit in the per-id coverage iteration.

**2. The lazy `__getattr__` re-export pattern in `__init__.py` was tried and rejected.** Initial implementation used `def __getattr__(name)` for lazy imports of `analyze` / `summarize` / etc. The pattern fights Python's module attribute caching — once a submodule is imported elsewhere (e.g., by a test fixture), Python sets it as an attribute and the `__getattr__` is bypassed. Switched to plain `from .analyze import ...` at top of `__init__.py`. **What follow-up agents need to know:** if you want lazy-load again, you'll need to gate the imports behind module-level `import os; os.environ.get(...)` flags or restructure the package — but it's not worth it for v1.

**3. `cache_render.py:deterministic_serialize` rename uses an identity binding, not a function wrapper.** `_deterministic_serialize = deterministic_serialize` makes the underscored name a SECOND binding to the same function object, not a thin wrapper. **Implication:** monkeypatching one does NOT affect the other. Tests that need to monkeypatch should target the import site (e.g., `monkeypatch.setattr("pflow.runtime.cache._deterministic_serialize", _boom)`), not the producer module. v1 has zero monkeypatchers of either name in the test tree, so this is safe today; flag for future refactors.

**4. The `cache.discrepancy` dispatch logic produces typed payloads at `context["root_cause_action"]`** so agents reading the JSON can dispatch on `"raw_root_cause" in payload` (unknown-cause discriminator) without regex-parsing prose. The schema for each `root_cause` enum value is in `CACHE_DISCREPANCY_ACTION_PAYLOAD_KEYS`. **If you add a new root_cause enum value:** add to `CACHE_DISCREPANCY_ACTION_TEMPLATES` (prose) AND `CACHE_DISCREPANCY_REQUIRED_CONTEXT` (per-cause required keys) AND `CACHE_DISCREPANCY_ACTION_PAYLOAD_KEYS` (typed payload schema) AND extend the if/elif chain in `_dispatch_discrepancy` AND add a parametrize row to the dispatch tests. Per-cause coverage is enforced by the dispatch-maps-consistent test.

**5. `analyze.py`'s eager import of `_resolve_chunk_value` / `_resolve_static_prefix_for_cache` / `_CHUNK_ABSENT` is INTENTIONAL and load-bearing.** v1 ships discrepancy detection as a stub (no actual prediction logic), but the imports lock the contract structurally — if a future contributor moves either helper, this file fails to import and the test suite catches it before a divergence-class regression. **The `noqa: F401` comments are correct** — don't remove them when discrepancy detection lights up; the helpers will be consumed.

**6. The `--no-trace-autoload` flag name is deliberately verbose** because `pflow run --no-trace` already exists with a different meaning (disable trace SAVING during execution). Reusing `--no-trace` on `analyze-cache` would collide. The longer name disambiguates: "don't auto-load an existing trace for analysis" vs "don't save a trace from this run."

**7. The 4-agent code review flagged 4 high-value verified findings**:
   - **Silent-failures C1**: nudge emitted `-$0.00/run, -0%` when cost was None. Fixed by `format_dry_run_nudge(savings_usd=None)` dropping the dollar figure entirely. Pattern: top-10% codebases (mypy, ruff, rustc) distinguish "unavailable" from "zero" everywhere — the cost tri-state in `render_text._format_cost` was already doing this; the nudge was an outlier.
   - **Silent-failures H1**: cross-workflow walker silently truncated at depth/cycle. Fixed by threading `notes: list[str]` through the walker so truncations surface as user-visible notes, not just debug logs.
   - **Validation-consistency Critical 1**: `cache.invalid-on-non-llm` capitalization drift between catalog and shipped emitter. Fixed by syncing the catalog template's case.
   - **Validation-consistency W2**: tests pinned literal `"1.0"` for format_version — would fail spuriously on a future minor bump. Fixed by reading `JSON_FORMAT_VERSION` constant.

**8. The async-tool wrapping test pattern** uses `getattr(tool, "fn", tool)` to reach through FastMCP's `FunctionTool` wrapper to the underlying coroutine, then `asyncio.run()` to drive it. **Don't use pytest-asyncio or anyio** — neither is configured; stdlib `asyncio.run` is sufficient.

**9. `WorkflowValidator._enumerate_child_calls` is the right primitive for batch sub-workflow walking.** It yields `(effective_params, batch_idx, inputs_from_item)` tuples, handling both inline-static batches (heterogeneous yields N edges, homogeneous yields 1) and template-items batches (yields raw params, defers to runtime). The walker discards `inputs_from_item` because rename detection only operates on literal-dict inputs (template strings are skipped).

**10. The `cache_nudge` runner integration uses `auto_load_trace=False` deliberately.** The dry-run path doesn't auto-load traces from `~/.pflow/debug/` — keeps latency bounded; agents who want trace-correlated nudges run `pflow analyze-cache --from-trace <path>` directly. Documented in the `_build_cache_nudge` docstring.

### Open hedged claims and verifications still pending

- **VERIFIED**: predicted cache_key byte-identity contract structurally locked by eager imports in `analyze.py`. (Discrepancy detection stub means runtime testing this is deferred to v1.x.)
- **VERIFIED**: catalog count auto-derivation works end-to-end. The `EXPECTED_CATALOG_COUNT` constant + 4 tests that iterate `CACHE_WARNING_CATALOG.keys()` at test time would catch a hardcoded-constant inlining regression.
- **VERIFIED**: MCP↔CLI JSON parity. Both surfaces invoke `render_json(analyze(...))` — single formatter, two call sites, mirrors `plan_workflow` / `format_plan_json` precedent.
- **VERIFIED**: silent-failures C1 (nudge emits dollar figure only when available). New regression tests (`test_format_dry_run_nudge_drops_dollar_figure_when_savings_unavailable` + `test_nudge_drops_dollar_figure_when_cost_unavailable`).
- **VERIFIED**: `test_plan_drift.py` (33 tests) green throughout Segment 4 implementation.
- **VERIFIED**: golden hash baseline regression (`test_golden_baseline_hashes_match`) PASSED. Segment 4 doesn't touch runtime hash path; verification confirms structural safety.
- **NEEDS VERIFICATION (v1.x)**: real cost integration. Stub returns None for all `*_cost_per_run_usd` fields; the tri-state degradation correctly fires on this. v1.x lights up `litellm.completion_cost()` per call.
- **NEEDS VERIFICATION (v1.x)**: real per-chunk token estimation in `_estimate_cacheable_tokens`. Current 75%-of-prompt heuristic is conservative.
- **NEEDS VERIFICATION (v1.x)**: full prompt-template parsing for `cache.dynamic-before-static` detection. Current implementation fires only `cache.below-min-tokens` and `cache.prewarm-no-prefix` in the analytical tier.
- **NEEDS VERIFICATION (production smoke)**: end-to-end `pflow analyze-cache` against the lyrics-generator workflow — requires user permission per agent-handoff out-of-scope reminders.

### Open user decisions surfaced

**None new**. The two pre-existing decisions:

1. **F2 confidence aggregation strictness** — RESOLVED. User confirmed STRICT semantics per DD#34 verbatim before implementation. Locked in `_aggregate_confidence` at `analyze.py:553-571`.
2. **V6 sub-workflow dedup outcome** — UNCHANGED. Segment 1 added the synthetic test; integration-level behavior remains unverified. No Segment 4 work surfaced new evidence.

### Code-review findings worth carrying forward

**4 high-leverage subagents ran in parallel against Segment 4's working tree:** `review-silent-failures`, `review-validation-consistency`, `review-impact-completeness`, `review-test-fidelity`.

**Verified findings applied:**
1. **silent-failures C1** (highest impact) — nudge dollar-figure regression. Fixed `format_dry_run_nudge` to accept `Optional[float | int]` and drop the figure when None.
2. **silent-failures H1** — cross-workflow walker silent truncation. Threaded `notes` list through walker; depth/cycle now surface as user-visible notes.
3. **validation-consistency Critical 1** — `cache.invalid-on-non-llm` capitalization drift. Synced catalog template to shipped emitter (lowercase "this/these").
4. **validation-consistency W2** — three test files pinned literal `"1.0"`; replaced with `JSON_FORMAT_VERSION` constant + consumer-rule assertion.
5. **impact-completeness W1** — `entry.md` Features menu missing `caching`. Added.
6. **impact-completeness W2** — `cli/commands/CLAUDE.md` File Overview + Test Mapping rows missing for `analyze_cache.py`. Added.
7. **impact-completeness S1** — stale "wired in Phase G when guide topic ships" comment. Removed.
8. **test-fidelity W1** — `test_explicit_from_trace_2_0_0_emits_graceful_note` substring too loose. Tightened to also check "discrepancy analysis omitted".
9. **test-fidelity W2** — `test_internal_analyzer_crash_exits_nonzero_no_silent_json` permissive escape hatch. Replaced with direct `assert "format_version" not in result.output`.
10. **test-fidelity W4** — async tool wrapping untested. Added `test_async_tool_wrapping_returns_dict` using `asyncio.run(tool.fn(...))`.

**Findings deliberately NOT fixed (per critical-thinking triage):**
- **silent-failures H2** (trace-skip note level mismatch): minor; the existing logger.debug + info-note pair is functional. Promoting log level requires verifying `cli/logging_config.py` mapping; out of scope for this review pass.
- **silent-failures M2** (per-call rendering fixed-width): polish, not silent-failure. Defer to v1.x if long names produce unreadable output in practice.
- **silent-failures L1** (`cache.below-min-tokens` defensive guard): correct under the v1 stub estimator; revisit when real estimator lands.
- **impact-completeness W3** (`detect_topics_from_ir` doesn't auto-attach `caching`): low-stakes feature gap. Defer to v1.x if observed adoption shows demand.
- **test-fidelity W3** (5/9 exit-code conditions covered): the missing 4 are parse-error, schema-error, mode-4 from-trace, no-LLM-only IR. Three are implicit (the existing tests cover them via the same Click error path); one (mode-4 from-trace) waits on discrepancy detection lighting up in v1.x.

**Lessons from Segment 4 worth surfacing:**

1. **The lazy `__getattr__` re-export pattern fights Python's module attribute caching.** Documented in tacit knowledge #2 above. Switch to plain top-level imports unless you have a strong lazy-loading requirement.

2. **Catalog template drift is real and bites at byte-equality boundaries.** Three IDs (`cache.order-mismatch`, `cache.unused-chunk`, `cache.invalid-on-non-llm`) have producers in BOTH `data_flow.py` AND `warning_catalog.py`. The drift surfaces as test failures or, worse, agent-confusion when one path emits "These fields are" and another emits "these fields are." The fix is to keep templates in sync structurally — a future refactor could collapse to a single emitter, but v1 ships with both maintained.

3. **None ≠ 0 in tri-state cost contracts.** The silent-failures C1 fix taught: when a system has "available / partial / unavailable" states for a value, NEVER emit zero on the unavailable branch. Drop the figure entirely or render "unavailable." Top-10% codebases (mypy, ruff, rustc) consistently distinguish unavailable from zero.

4. **The async-tool wrapping test pattern** (`asyncio.run(tool.fn(...))`) is the right minimal test for FastMCP-wrapped coroutines. Don't add pytest-asyncio just for this — it's overkill for the contract.

5. **Format-version constants belong in `__init__.py`** so consumers (tests, MCP docstring, CLI) can all import the single source of truth. Hardcoded literals in tests are technical debt that breaks under additive minor bumps.

---

## Post-segment-4 follow-up: cost wiring + honest loose-ends audit (2026-04-30)

After segment 4 was committed, an audit pass surfaced that the analyzer's
*structural* feature works end-to-end (parser → IR → validator → renderer →
CLI/MCP) but the *value-prop* features the spec mode-1 example shows verbatim
were stubbed. This entry documents the cost wiring shipped in this session
plus a complete honest accounting of remaining loose ends.

### What I implemented in this follow-up

**Real cost computation in `_build_summary` (Path A from the scope discussion).**

- New module: `src/pflow/core/cache_analysis/cost_estimation.py` (~340 LOC).
  - `ModelPricing` frozen dataclass + `get_model_pricing(model)` lookup with
    bare-name fallback (mirrors `llm_client.py:1030-1042`).
  - `compute_aggregate_costs(rows, *, output_tokens_by_node, ttl)` produces
    `AggregateCostBreakdown` with current/optimized/rerun/savings figures.
  - Anthropic 1h-TTL multiplier (2.0× base, per Spike 3 / DD#37) — mirrors
    the runtime override at `llm_client.py:1047`. Provider-gated; non-Anthropic
    paths use LiteLLM's reported cache_creation_rate unchanged.
  - Cache-rate fallback (1.25× / 0.1× of base input) when LiteLLM's pricing
    entry lacks the cache fields. Plausible-default beats refusing-to-price.
- Extended `token_estimation.py` with `estimate_output_tokens(*, trace,
  memo_cache, node_id, workflow_path) -> tuple[int | None, str]`. Two tiers
  only (`trace`, `memo`); `unavailable` when neither has data. **No
  fabrication on greenfield** — refuses to guess output tokens (per the
  "no silent behavior" principle).
- Extended `PerCallRow` with `output_tokens_estimated: int | None` and
  `output_data_source: str` (defaults preserve existing constructors).
- Extended `AnalysisSummary` with `aggregate_savings_first_run_usd: float | None`
  and `aggregate_savings_rerun_usd: float | None`. Greenfield-safe (input-only
  math; output cost cancels in `current - optimized`).
- `_build_summary` now reads `workflow_ir["cache"]["ttl"]` and threads it into
  the cost computation.
- `render_text._render_summary` adds an "Estimated savings if applied" line
  when aggregate savings is positive. New "absolute costs need a prior run"
  hint when greenfield + savings-but-no-absolutes.
- `render_json._summary_to_dict` exposes the two new aggregate savings fields.
- `render_json._per_call_to_dict` exposes `output_tokens_estimated` and
  `output_data_source` per call.
- New tests: `tests/test_core/test_cache_analysis_cost_estimation.py` (18 tests
  covering pricing lookup, greenfield contract, after-run contract,
  partial state, 1h-TTL multiplier, batch invocations, break-even math).

**Files modified (production):** 4 — `cost_estimation.py` (new),
`token_estimation.py`, `analyze.py`, `render_text.py`, `render_json.py`.

**Final state:**
- 5920 tests passing (up from 5902 — 18 new cost tests, no regressions).
- `make check` green (ruff + ruff-format + mypy + deptry).
- `test_plan_drift.py` 33/33 green.
- `test_golden_baseline_hashes_match` (DD#19) PASSED.
- Smoke-tested rendered output: greenfield shows "unavailable" absolutes +
  real savings + run-once hint; after-run shows real absolute costs.

### Tri-state contract (load-bearing UX rule)

The cost figures honour a strict tri-state per the F2 contract:

- **Priced**: input + output tokens known + model in `litellm.model_cost`.
  Renders as `~$2.18`.
- **Partial**: at least one priced row AND at least one row with unavailable
  output tokens or unpriced model. Renders as `~$0.84 (partial)`.
- **Unavailable**: no priced row had enough data. Renders as `unavailable`
  (NEVER `$0.00` — distinguishing absent from zero is the load-bearing UX
  rule per top-10% codebases like mypy/ruff/rustc).

Aggregate savings are computable independently of output tokens (input-only
math; output cancels in `current - optimized` and `current - rerun`). They
populate even on greenfield workflows whose absolute costs are unavailable.

### LOAD-BEARING LOOSE END (likely in-PR fix-needed)

> **Recommendations section is effectively empty in v1, regardless of run state.**

This is the single biggest gap remaining. The Summary section now lights up
with cost numbers, but the Recommendations section (the spec mode-1 example's
ranked dollar-figure list of caching opportunities) is empty for typical
workflows.

**Root cause:** the warnings that carry per-recommendation `savings_usd` in
their context (`cache.dynamic-before-static`, `cache.shared-context-undeclared`,
`cache.padding-advisory`, `cache.batch-prewarm-recommended`) are the **3-4
stubbed analytical warnings** that don't fire in v1. The warnings that DO
fire (`cache.below-min-tokens`, `cache.prewarm-no-prefix`) don't carry
savings — they're "this won't work" warnings, not "save $X" warnings.

**What an agent sees on lyrics-generator-shaped greenfield workflow today:**
- Summary cost: useful (after one run).
- Aggregate savings line: useful.
- Recommendations: **empty or `savings unavailable`** — the agent gets no
  specific guidance on WHERE to add caching.

**To close this gap**, the analytical detection logic for the stubbed warnings
needs to be implemented:

| Warning ID | What detection logic is needed |
|---|---|
| `cache.dynamic-before-static` | Parse the prompt template; find first `${var}` reference; compute static-tokens-after the reference; emit when static_after > min_cache_threshold. Highest-leverage detection per spec. ~50 LOC. |
| `cache.shared-context-undeclared` | Identify N≥2 LLM calls sharing a stable context object; suggest declaring it in `## Cache`. Requires cross-call template comparison. ~80 LOC. |
| `cache.padding-advisory` | Detect when a node's `prompt_cache:` subset doesn't start at position 1 of `## Cache`; compute net-positive padding; emit if > sensitivity floor. ~60 LOC. The infrastructure (`PaddingCandidate`, `compute_padding_advisories`, sensitivity floors) is in `padding_advisor.py` already; just needs the detection wiring. |
| `cache.batch-prewarm-recommended` | Compute `savings_ratio` per DD#33 for batches without explicit `prewarm:` decision; emit when ≥ 5%. ~30 LOC. |

**Each of these is bounded scope** (~30-80 LOC + tests). Combined: maybe
~250 LOC + ~30 tests. Not architecturally complex — they consume the per-call
data already on `PerCallRow` (input_tokens, cacheable_tokens, model) plus
prompt-template parsing for #1 and `cacheable_tokens` math for #4.

**Recommendation**: light them up in this PR before declaring v1 done. Without
them, the analyzer answers "what does this workflow cost?" but not "where
should I add caching?" — and the spec mode-1 example is the second question.

### Other remaining loose ends (lower-priority v1.x items)

1. **`cache.discrepancy` `--from-trace` mode** — infrastructure scaffolded
   (action templates, payload schemas, eager imports of `_resolve_chunk_value`
   and `_resolve_static_prefix_for_cache` in `analyze.py:37-41`) but no
   emission code. The `--from-trace` mode loads traces and renders the
   per-call table with confidence labels, but doesn't compare predicted vs
   actual cache ratios with root-cause attribution.

2. **`_estimate_cacheable_tokens` is a 75%-of-prompt heuristic.** Returns
   `len(prompt) * 75 // 400` when a node has `prompt_cache:` declared. Affects
   `cacheable_tokens_estimated` accuracy in the per-call table and (by
   extension) the aggregate savings figure. Real per-chunk estimation would
   call `estimate_tokens()` per declared chunk against the prompt template,
   summed.

3. **F2.4 byte-exact golden files deferred** in favor of structural per-id
   round-trip tests. Per the segment-4 entry — would catch text/JSON output
   drift (different bug class than the round-trip tests currently catch).

4. **`_render_per_call` text formatting uses fixed-width padding**, not
   truncation. Long node IDs / model strings push columns right rather than
   truncating. Cosmetic; identified by review-silent-failures M2 in segment 4.

5. **Per-call cache report missing column header row.** Visible in smoke test:
   `step1  model=...  tokens=1000  cacheable=750  ratio=75%  src=memo` shows
   the columns but no header. Cosmetic.

6. **End-to-end smoke against lyrics-generator** — needs explicit user
   permission per agent-handoff (don't touch `/Users/andfal/projects/music-generation/`
   without asking). Would verify ≥40% input-cost reduction target.

7. **Anthropic 1h-TTL cost override drift risk.** The 2.0× multiplier in
   `cost_estimation.py:_write_rate_for_ttl` mirrors `llm_client.py:1047`. If
   LiteLLM eventually fixes the upstream pricing bug (their internal computation
   already covers 1h writes correctly), both sites need to be removed in
   lockstep — otherwise predicted costs would over-charge.

### Tacit knowledge worth surfacing

1. **Caching savings are always input-only — output cost cancels.** This is
   the mathematical insight that makes greenfield analysis useful at all.
   `current - optimized` collapses to input-side terms because both sides
   include the same output cost. So aggregate savings figures populate even
   when output tokens are unavailable.

2. **Output tokens dominate LLM cost (60-85%) on typical workloads.** Anthropic
   Sonnet output rate is 5× input rate. For lyrics-generator's spec example
   (78k input tokens × $3/M = $0.23 input cost vs $2.18 total), output
   accounts for 89% of total. Skipping output tokens in the cost model would
   make absolute figures wrong by ~10×.

3. **Single-call subsets have NEGATIVE first-run savings** (correct math).
   Anthropic 5m-TTL break-even is 1 read = 2 total uses. A single call with
   declared cache pays the 1.25× write cost without any read amortization.
   The renderer's `aggregate_savings_first_run_usd > 0` guard correctly hides
   the savings line in that case. Test
   `test_single_call_first_run_savings_is_negative_below_break_even` locks
   this contract.

4. **PerCallRow extension pattern**: adding optional fields with defaults is
   safe across existing constructors (all callers use kwargs). Future fields
   should follow the same pattern; positional construction would break the
   existing test fixtures.

5. **The cost computation's invariance issue with mypy** required `Sequence`
   typing on `_aggregate_optimized_cost` (filtered list of 3-tuples isn't
   covariant with the broader list type). Lesson for future helpers
   accepting filtered subsets: use `Sequence` not `list` in the signature.

---

## Post-segment-4 follow-up: O(matches) trace autoload + test isolation gap (2026-04-30)

User reported `make test` slowdown from ~20s baseline to 107s after Segment 4
shipped. Investigation surfaced a single root cause with two distinct surfaces.

### Root cause

`pflow analyze-cache` calls `_autoload_trace` (`core/cache_analysis/analyze.py:333`)
which calls `_scan_trace_dir` (`core/cache_analysis/analyze.py:302`) — reads and
JSON-parses **every file** in `~/.pflow/debug/` to filter by `data["workflow_path"]`.
On the user's machine: 67,339 trace files / 3.4 GB → ~10s file I/O + ~3s JSON
decode = **14s per analyze-cache invocation**. With 11 analyze-cache tests in the
suite, that's ~155 cumulative seconds, ~40s wall on 4 workers.

`cProfile` on a single test confirmed: 67,340 `read_text()` calls + 67,339
`json.loads()` calls dominating cumulative time. Wall 14.46s, CPU only 6.7s —
the rest is filesystem I/O.

The previous investigation's hypotheses (LiteLLM remote model-cost-map fetch,
`uv run` subprocess overhead) were both wrong on this machine: LiteLLM imports
in 0.86s and `token_counter` is ~100ms.

### Two distinct issues sharing this root

**Issue A (test isolation gap):** `tests/conftest.py::isolate_pflow_config` patches
Registry / SettingsManager / MCPServerManager / WorkflowManager / MemoizationCache
to tmp paths but does **NOT** patch `Path.home()` itself. `WorkflowTraceCollector.save_to_file()`
and `_autoload_trace` call `Path.home() / ".pflow" / "debug"` directly — escaping
isolation entirely. Tests have been silently writing trace files to the user's
real `~/.pflow/debug/` for the entire history of this fixture. Verified by setting
`HOME=/tmp/empty-home` on a single test: 14.17s → 0.31s (45×).

**Issue B (production scaling):** even with test isolation fixed, `_scan_trace_dir`
remains O(N) where N grows unbounded. Real users hit 14s+ analyze-cache invocations
within months. The structural mistake: filename encodes `workflow_name` (sanitized
H1 title, truncated to 30 chars) but lookup filters by `workflow_path` (canonical
absolute path or `ir-hash:<md5>`). Filename and lookup key disagree → must read
every file's contents to match.

### What I implemented

**Production fix — identity-encoded filenames** (top-10% pattern from git refs,
mypy cache, pip metadata: encode identity in filename, lookup by glob, never
scan-and-parse):

- `src/pflow/runtime/workflow_trace.py` — added module-level helper
  `format_trace_filename(workflow_path, workflow_name, timestamp)`. Schema:
  `workflow-trace-{wf_hash}-{safe_name}-{timestamp}.json` where `wf_hash` is
  the first 8 hex chars of `md5(workflow_path or "")`. `WorkflowTraceCollector.save_to_file()`
  delegates filename composition to the helper. (+22 / −12 lines)
- `src/pflow/core/cache_analysis/analyze.py` — replaced `_scan_trace_dir` (28 LOC,
  deleted) + `_autoload_trace` (33 LOC). New `_autoload_trace` globs by hash:
  `workflow-trace-{wf_hash}-*.json`. Reads only files that could match. Hash
  collision (8 hex = 32 bits) defended by inner `data["workflow_path"] == workflow_path`
  re-check. Dropped the 2.0.0-skip and unparseable-skip advisory notes (they have
  no producer post-fix — the narrow glob doesn't surface them). (+44 / −64 lines)

**Test isolation fix:**

- `tests/conftest.py::isolate_pflow_config` — patches `Path.home()` AND `os.environ["HOME"]`
  per `tests/CLAUDE.md:210-214` documented split. Production code uses both idioms
  (11 `Path.home()` sites + 4 `expanduser()` sites in `src/pflow/`); patching both
  closes all of them. Bonus: closes 2 pre-existing `expanduser()` isolation gaps
  (`skill_service.py:328`, `nodes/mcp/node.py:502`) unrelated to Task 159. (+17 lines)

**Test updates:**

- `tests/test_runtime/test_workflow_trace.py::TestWorkflowTraceCollector::test_filename_format` —
  updated literal filename pin to include hash prefix (`d41d8cd9` for `workflow_path=None`).
- `tests/test_core/test_cache_analysis_analyze.py` — replaced 3 dead-counter tests
  with 3 behavioral tests:
  - `test_autoload_finds_2_1_0_trace` (kept, updated `_write_trace` helper to use production schema)
  - `test_autoload_skips_2_0_0_trace_silently` (replaces 2.0.0-note test)
  - `test_autoload_skips_unparseable_files_silently` (replaces unparseable-note test)
  - `test_autoload_skips_traces_for_other_workflows` (NEW — locks O(matches), not O(directory) invariant)

  `_write_trace` helper now imports `format_trace_filename` so test fixtures match
  what production writes. Drift between fixture and reader filename schemas is
  impossible by construction.
- `src/pflow/cli/CLAUDE.md:225` — updated cosmetic trace path example.

### Tradeoff: dropping advisory counters

User decision: chose option (a) — drop the 2.0.0-skip and unparseable-skip notes
entirely.

Reasoning: under the new hash-narrowed glob, neither counter has a real producer.
2.0.0 traces don't have the new hash prefix → invisible to glob → counter always
0. Unparseable traces only count files with the new prefix → vanishingly rare.
Keeping the counters would be dead code pretending to be live. The renderer test
(`test_cache_analysis_renderers.py:205-216`) still passes because it tests
rendering order with manually-constructed note strings; it doesn't depend on a
production producer.

The unparseable diagnostic theoretically catches disk corruption, but the right
place to surface that is at `WorkflowTraceCollector.save_to_file()` (the producer)
on write failure, not at every reader.

### Final state

- **Test suite**: 107s → **27.26s** (3.9× speedup, near pre-Segment-4 baseline).
- All 117 directly-affected tests in 5 files pass in 1.33s (vs ~150s pre-fix).

### Tacit knowledge for the next agent

1. **Filename schema is now load-bearing.** `format_trace_filename` is the single
   source of truth — both `WorkflowTraceCollector.save_to_file` and the autoload
   reader (via the same hash derivation) AND test fixtures (via direct import)
   use it. If you change the schema, change one place; the test fixture import
   guarantees fixtures stay in sync. Drift is impossible by construction.

2. **Existing 2.1.0 traces written before this fix are not findable via autoload.**
   They lack the hash prefix → glob misses them. Acceptable per DD#34 ("auto-load
   is a convenience; explicit loading is the contract"). Users who want analysis
   of old runs use `pflow analyze-cache --from-trace <path>` (path-based, unchanged).
   On the user's machine right now, all 67k existing traces are silently bypassed
   by autoload — analyze-cache invocations drop to ~0s without even cleaning up
   the directory.

3. **Hash collision defense is at TWO layers.** 8 hex chars = 32 bits — vanishingly
   unlikely for trace files (would need two distinct workflow_paths producing the
   same first-8-hex md5). The inner `data.get("workflow_path") != workflow_path`
   re-check after JSON parse makes it impossible. Both layers documented inline.

4. **Test isolation now redirects BOTH `Path.home()` and `$HOME`.** Per the
   pre-existing `tests/CLAUDE.md:210-214` documented split: `setattr(Path, "home", ...)`
   handles `Path.home()` callers; `setenv("HOME", ...)` handles `Path("~/...").expanduser()`,
   `os.path.expanduser`, and subprocess env inheritance. They are NOT interchangeable.
   Production code uses both idioms — verified 11 `Path.home()` + 4 `expanduser()`
   sites in `src/pflow/`.

5. **Two pre-existing isolation gaps closed as a bonus.** `core/workflow/skill_service.py:328`
   and `nodes/mcp/node.py:502` resolve `~/.pflow/...` via `Path("~/...").expanduser()`,
   which goes through `os.environ["HOME"]`. Existing fixture's individual-class
   patches (WorkflowManager, MCPServerManager) covered some sites; these two were
   gaps. Adding `monkeypatch.setenv("HOME", str(tmp_path))` covers them too.

6. **Shell tests intentionally read `$HOME` for shell-expansion testing.**
   `tests/test_nodes/test_shell/test_shell.py:134` and
   `test_nodes/test_shell/test_improved_behavior.py:268` assert
   `output == os.environ.get("HOME", "")`. With the new fixture, `HOME=tmp_path`,
   the shell subprocess inherits `HOME=tmp_path`, `echo $HOME` produces `tmp_path`,
   assertion holds. Tests are value-agnostic — they verify shell expansion works,
   not what the value is.

### Open follow-ups (NOT in this commit)

1. **Update mintlify docs and architecture docs** (`docs/guides/debugging.mdx`,
   `docs/reference/cli/index.mdx`, `architecture/architecture.md`,
   `architecture/reference/template-variables.md`) to reflect the new filename
   schema. Cosmetic; defer to a docs-cleanup pass.

2. **Existing 67k+ traces in users' `~/.pflow/debug/`.** Not affected by this
   commit — they remain on disk but are bypassed by autoload. Consider a
   `pflow trace prune` follow-up command.

---

## Post-segment-4 follow-up: test fidelity cleanup (2026-04-30)

Applied the 5 High + 9 Medium findings from
`scratchpads/test-fidelity-review-2026-04-30.md`. No production code changed;
all changes are in tests. 10 test files touched.

### Deleted (tautologies / monkeypatch semantics / vacuous singleton)

- **H1** `test_hash_render_and_prep_render_byte_equivalent_for_same_subset`
  (`test_prompt_cache_rendering.py`) — synthetic-dict + top-level-keys-only
  shape that hid Bug #2. The Bug-#2 regression
  `test_hash_render_and_prep_render_byte_equivalent_through_namespaced_store`
  fully supersedes it. Comment block left at the deletion site pointing at
  the replacement.
- **H2** `test_in_memory_three_state_via_compile`
  (`test_prompt_cache_hash.py`) — asserted `compute_node_config` ignores
  cache fields without the `prompt_cache_content` kwarg, a tautology. The
  next test (`test_plan_node_renders_cache_into_hash`) covers the real
  divergence at the production-shaped plan_node site.
- **H3** `test_resolve_chunk_value_bindings_are_independent`
  (`test_prompt_cache_rendering.py`) — validated `monkeypatch.setattr`
  semantics, not pflow behavior. The identity check at the same module
  (`test_resolve_chunk_value_is_imported_locally_at_both_sites`) already
  locks the load-bearing invariant. Updated that test's docstring to drop
  the dangling reference to the deleted sibling.
- **M2** `test_context_passthrough_fidelity` (12 parametrized;
  `test_cache_analysis_warnings.py`) — pure passthrough
  (`Diagnostic.context = {**kwargs}` ⇒ kwargs persist). Replaced with a
  short comment pointing at the production-shaped dispatch tests at
  lines 246-300 that ARE good.
- **M9** `test_chunk_absent_is_a_singleton_via_isinstance`
  (`test_prompt_cache_hash.py`) — true by construction.

### Consolidated

- **H5** five `test_make_serializable_rejects_chunk_absent_*` tests
  collapsed into one `@pytest.mark.parametrize`-driven test with 5 cases
  (top_level / inside_dict / inside_list / dict_of_list / list_of_dict).
  Positive-control (`test_make_serializable_pass_through_for_normal_string`)
  kept as a separate test.
- **M1** `test_per_id_diagnostic_json_round_trip` reduced from 12
  parametrized to 3 representative IDs (`cache.order-mismatch` for flat
  context, `cache.discrepancy` for nested-dispatch payload,
  `cache.invalid-on-non-llm` for V6 combined-diagnostic shape). Folded
  the deleted `test_per_id_json_payload_carries_id_at_top_level`
  invariant into the same assertion. Comment documents the structural-
  vs-production-driven complementarity.

### Strengthened

- **M3** `test_collect_parallel_results_accepts_initial_completed_and_total`
  now passes a `Mock` callback and asserts `_report_batch_progress` fired
  with `batch_current=2, batch_total=2, batch_success=True` — proves the
  new `initial_completed` / `total` kwargs flow through to the progress
  reporting site.
- **M5** `test_subworkflow_isolation_via_monkeypatch` replaces the weak
  `child_value is not parent_initial` assertion with a positive equality
  check against a freshly-built `build_cache_render_dict(child_workflow)`
  (the production builder). For the no-cache child fixture, this is
  `dict(child_value) == {}`.
- **M6** `test_record_node_execution_passes_cache_metadata_to_llm_call`
  refactored to drive from the producer side: pre-populate `shared`
  with bare `llm_usage`, invoke `apply_memo_hit(...)`, then
  `record_node_execution`. Catches a producer→consumer key-mismatch
  (`cache-source` with hyphen, etc.) the hand-built shape would miss.
- **M7** `test_analyze_cache_with_workflow_having_warnings_still_exits_zero`
  replaces `if payload["warnings"]: pass` with
  `assert any(w["id"] == "cache.below-min-tokens" for w in ...)` — surfaces
  a "warnings stopped firing" regression instead of silently passing on
  an empty list.
- **M8** `test_async_tool_wrapping_returns_dict` replaces the shallow
  `set(keys) == set(keys)` with full deep equality
  (`assert result == sync_result`) after stripping the only
  non-deterministic field (`analyzed_at`).

### Added

- **H4** `test_engine_memo_hit_writes_cache_source_memo_not_in_process`
  (`tests/test_runtime/test_trace_format_2_1.py`) — the symmetric
  counter-test to Bug #1. Builds a `CompiledWorkflow` with a single LLM
  node, runs it once with a real `MemoizationCache` to populate the
  cache, then runs it again with the same cache — asserts the second
  run's trace event has `cache_source="memo"` (NOT `"in_process"`),
  `cache_key` populated, and `cache_age_sec > 0`. Requires
  `WorkflowEngine(trace_collector=...)` (the engine constructor takes
  it; `shared["__trace_collector__"]` install alone won't fire
  `record_node_execution`). **Sensitivity-verified**: temporarily
  changing `cached_source = None` to `"in_process"` at engine.py:440
  causes the test to fail with the locked Bug-#1 message.
- **M4** `test_combined_declared_cache_and_auto_batch_prefix_through_namespaced_store`
  (`tests/test_nodes/test_llm/test_batch_cache_prefix.py`) — wraps
  shared in `NamespacedSharedStore(shared, "score-choruses")` (the
  production engine.py:471 wrap) and asserts both the declared-cache
  marker (system_blocks) and the auto-batch-prefix marker
  (user_message_blocks) fire correctly. Locks the production execution
  shape against a future Phase D extension that consumes
  `${node.field}` references through
  `_resolve_static_prefix_for_cache`.

---

## Pre-recommendations preparation: adversarial drill + 2 critical bug fixes (2026-04-30)

Verification-specialist pass run before the recommendations-section plan
implementation begins. Five preparation items defined in
`scratchpads/recommendations-plan-preparation-2026-04-30.md`. Item 1
(adversarial CLI drill on the autoload fix from `d917a55d`) surfaced
**two critical silent bugs** that the unit-test surface had missed —
same anti-pattern (Pitfall #19) that bit Segment 3 twice. Both fixed
in this pass; the recommendations plan now ships against a clean base.

### Bug #1 (P0) — Tier-1 trace data unreachable in production

**Symptom:** every `pflow analyze-cache --from-trace` AND every autoload
silently fell through to `estimator`/`heuristic` for input/output token
estimation. Aggregate `confidence: high_from_trace` and per-call
`data_source: "trace"` were unreachable in production, even when the
analyzer correctly loaded a 2.1.0 trace file (verified via `trace_path`
populated in JSON output).

**Root cause:** `core/cache_analysis/token_estimation.py:139` read
`trace.get("events")` while the trace JSON's top-level events list is
keyed `"nodes"` (verified — `runtime/workflow_trace.py:550` writes
`"nodes": self.events`; `core/trace_report.py:485,552,613,642` all read
`"nodes"`). One-character typo.

**Why tests missed it (Pitfall #19):** the synthetic fixture helper
`_trace_with_node` at `tests/test_core/test_cache_analysis_token_estimation.py:38`
constructed dicts with `"events"` key — matching the buggy reader.
Every tier-1 trace test passed against a fake trace shape. Same anti-
pattern as Bug #1 (`cache_source` overwrite) and Bug #2 (NamespacedSharedStore
type taxonomy) from Segment 3's adversarial drill.

**Fix:** `events = trace.get("events")` → `events = trace.get("nodes")`.
Updated docstring documenting why the walker is non-recursive (the only
consumer — `analyze.py:212`'s top-level IR-node iteration — never asks
for sub-workflow internal nodes; the recommendations plan's
`_iter_llm_events` walker handles the recursive consumer separately).

**Test:** synthetic fixture key swap (`"events"` → `"nodes"`) PLUS one
new production-shape test `test_tier_1_trace_works_with_real_collector_round_trip`
that drives a real `WorkflowTraceCollector.save_to_file` round-trip.
Mutation-test: re-introducing the typo fails the new test; restoring
passes. Defends Pitfall #19 from re-occurring in this exact module.

### Bug #2 (P1) — Inline workflow `workflow_path` divergence (MCP-only)

**Symptom:** when MCP `analyze_cache` received an inline (dict) workflow
that had been previously run + traced, autoload silently missed the
trace because the writer's hash key and the reader's diverged.

**Root cause:** the trace writer (`runner.py:130`) stores
`workflow_path = resolved.file_path or _synthesize_inline_workflow_id(resolved.ir)`
— for inline workflows, the canonical `ir-hash:<md5>`. The analyze CLI
(`cli/commands/analyze_cache.py:118`) and MCP service
(`mcp_server/services/execution_service.py:419`) used `or "<inline>"`
as the autoload key — a placeholder string, not the canonical id.
`md5("<inline>")` ≠ `md5("ir-hash:<md5-of-ir>")` → glob never matched.
CLI is unaffected today (always resolves a file/library path);
MCP `analyze_cache` accepts `dict[str, Any]` per its tool signature
so the inline path is reachable.

**Fix shape (top-10% / simplicity-first lens — applied per user's
mid-stream redirect):**

Initial proposal duplicated `_synthesize_inline_workflow_id(ir)` at TWO
call sites (CLI + MCP). Re-questioned through the simplicity rule:
derive ONCE at the lowest layer that has the data. `analyze()` already
takes `workflow_ir`. Single source of truth wins long-term. **Final
shape:**

1. Promoted `_synthesize_inline_workflow_id` to `core/workflow_id.py`
   (NEW module) with public `synthesize_inline_workflow_id(ir)`. Pure
   utility; no internal pflow imports.
2. `execution/runner.py` imports from new home; keeps
   `_synthesize_inline_workflow_id = synthesize_inline_workflow_id`
   alias for the 3 existing test imports (`test_runner.py:15`,
   `test_plan.py:303,329`) — zero churn at consumer sites.
3. `core/cache_analysis/analyze.py` derives a `lookup_path` once at
   function entry: `workflow_path if workflow_path is not None else
   synthesize_inline_workflow_id(workflow_ir)`. Threaded through
   autoload (filename-hash glob), memo cache (SQL `workflow_path`
   scoping), AND cross-workflow walker — every site where lookup
   correctness matters. The displayed `"<inline>"` label stays
   separate at line 256 (display vs lookup are two concerns).
4. CLI + MCP call sites simplified to pass `resolved.file_path`
   (or `None` for inline) — single line each.

**Test:** new production-shape test
`test_inline_workflow_autoload_finds_canonical_ir_hash_trace`
(`tests/test_mcp_server/test_analyze_cache_tool.py`) drives the MCP
service with an inline dict workflow + a pre-seeded 2.1.0 trace under
the canonical `ir-hash:*` filename. Asserts `trace_path` populated,
`estimate_confidence == "high_from_trace"`, `data_source == "trace"`.
Mutation-tested: reverting the `lookup_path` derivation fails the test.

**Why this matters for the recommendations plan:** sub-segment C's
`cache.discrepancy --from-trace` consumes per-call rows that come
through `_build_per_call_row` → `estimate_tokens` → `_from_trace`. With
Bug #1 alive, every C-shipped discrepancy fixture would have measured
estimator-source numbers against trace-source assertions — whichever
side held the bug at test time would silently mask the other. Fixing
both before C ships removes a pre-existing landmine.

### Plan amendment landed: A.6 — surface validator findings in `analyze()`

Adversarial drill also surfaced a spec-vs-implementation gap
(non-bug, but load-bearing for analyzer UX):
`pflow analyze-cache` does NOT call `validate_data_flow()`, so the
validator-shipped catalog IDs (`cache.order-mismatch`,
`cache.unused-chunk`, `cache.invalid-on-non-llm`) silently disappear
from analyze-cache output. Spec line 217 explicitly says they should
surface there. After sub-segment A wires up the analytical detections,
the asymmetry materially undermines analyze-cache's value: an agent
would see "5 cache opportunities" while a hidden ERROR sits unrendered.

User approved option (A): appended A.6 directly to
`recommendations-section-plan.md` as a new sub-section under
sub-segment A. ~10 LOC + 4 tests. Bundles into A's commit
(executing agent already opens `analyze.py`). Exit-code contract kept
advisory per DD#36 — agents that want to gate inspect
`warnings[].severity == "error"` themselves. Sub-segment A header,
files-to-modify table, total estimate (`~580 LOC + ~56 tests`) updated.

### Verification items completed

- **Item 4** (line-number citations): `prose_mismatches` /
  `value_flow_opportunities` confirmed at `test_cache_analysis_renderers.py:97-98`
  AND `test_analyze_cache_tool.py:95-96`. Plan citations exact, no drift.
- **Item 5** (drift-test extension point):
  `tests/test_execution/test_plan_drift.py:2088`
  (`test_plan_matches_engine_for_workflow_with_prompt_cache`) verified
  clean. `compiled` + `cache` + `registry` all in scope; cache db at
  known `tmp_path`. PlanEntry confirmed has no `cache_key` field today
  (sub-segment C adds it). The plan's specified ~10-line extension
  lands without restructuring.
- **Item 3** (TODO pointer): added near `_STUBBED_PRODUCERS_DEFERRED_TO_V1X`
  in `tests/test_core/test_cache_analysis_per_id_coverage.py` directing
  the recommendations executing agent to delete the set + parallel test
  helpers (`_kwargs_for`, `_minimal_context_kwargs`,
  `test_every_id_round_trips_through_make_diagnostic`) when sub-segment
  C's producers wire up.

### Final state

- End-to-end CLI drill (real Anthropic Haiku-4.5 call, ~$0.0006):
  before-fix `confidence: low_no_data`, `data_source: ['estimator', 'estimator']`;
  after-fix `confidence: high_from_trace`, `data_source: ['trace', 'trace']`.

### Tacit knowledge for the next agent (Sub-segment A)

1. **Pitfall #19 has bitten this codebase 3 times now** (Segment 3's
   `cache_source` overwrite, Segment 3's NamespacedSharedStore type
   taxonomy, this segment's events/nodes typo). The pattern: a synthetic
   test fixture matches a buggy reader rather than production shape;
   tests pass; production silently fails. **Defense for sub-segment A:**
   every per-id emission test fixture should include at least one path
   that drives a real `WorkflowTraceCollector` round-trip (or
   `WorkflowRunner().run()`) — not just synthetic `Diagnostic`
   construction. The plan's "production-shape testing" requirement (line
   605 — "all fixtures call `analyze(...)` end-to-end with real
   `MemoizationCache`") is the right floor. Don't fall back to
   round-trip-only tests when emission tests are harder to write.

2. **`synthesize_inline_workflow_id` is now in `core/workflow_id.py`**
   (was at `execution/runner.py:36` until 2026-04-30). The underscore-
   prefixed alias `_synthesize_inline_workflow_id` survives at
   `runner.py` for backward-compat with 3 existing test imports. Any
   NEW caller should import from the canonical home:
   `from pflow.core.workflow_id import synthesize_inline_workflow_id`.

3. **`analyze()`'s `lookup_path` is the single source of truth for
   correlation** (autoload + memo + cross-workflow). If sub-segment C's
   `_predict_cache_keys` needs a workflow path for its `build_plan`
   call (`_parent_workflow_file=workflow_path`), use the same
   `lookup_path`-equivalent (i.e., derive via
   `synthesize_inline_workflow_id` for inline IRs) — NOT the displayed
   `"<inline>"` placeholder. The two concerns are intentionally
   separated: lookup correctness vs human display.

4. **A.6's filter is `d.id and d.id.startswith("cache.")`** —
   `validate_data_flow` returns ALL data-flow diagnostics (cycles,
   undefined nodes, etc.). Surfacing those in analyze-cache would
   expand scope to general workflow health; that's a separate task.
   Cache-namespaced filter keeps analyze-cache focused on cache
   concerns.

5. **The token_estimation walker is intentionally non-recursive.** Only
   `analyze.py:212`'s top-level `type: llm` IR-node iteration calls it.
   Sub-workflow internal nodes are NEVER passed to this function (they
   live inside a `type: workflow` IR node which is filtered out).
   The recommendations plan's sub-segment C ships a SEPARATE
   `_iter_llm_events` walker that recurses through `sub_workflow_events`
   and `batch_items` — different consumer (discrepancy detection),
   different shape need. Don't accidentally extend `_from_trace` to
   recurse "for symmetry" — there's no symmetric consumer.

---

## Pre-recommendations baseline cleanup: 5 review-driven fixes (2026-04-30)

Two code reviews (`scratchpads/code-review-task159-20260430-1305.md` and
`scratchpads/code-review-task159-20260430-1430.md`) ran against the
post-segment-4 + cost-wiring + autoload-speedup tree. After triage against
the recommendations-section plan's planned scope, **5 findings landed as
a pre-A baseline commit**, **2 findings filed as GH issues**, the rest
deferred (already-in-plan, intentional v1.x polish, or defended in code).

### What I implemented

**5 fixes, one coherent commit:**

1. **CR-1430 C1** — `cache.prewarm-no-prefix` regex parity. Pre-fix used
   dot-only matcher (`marker = "${" + alias + "."`); runtime gate at
   `nodes/llm/llm.py:350` uses `r"\$\{" + re.escape(alias) + r"(\.|\[)"`.
   Workflows with `${item[0].field}` at position 0 silently missed the
   detection. Fixed by importing `re` and using the same regex shape as
   the runtime gate. Test parametrizes 6 cases (dot/bracket × position-0
   / non-zero / no-batch-ref).

2. **CR-1430 C2** — savings/optimized rowset asymmetry. `cost.current_usd`
   was over `rows_with_output` (subset); `cost.savings_first_run_usd` was
   input-only over ALL `priced_rows` (superset). Dividing them when
   without-output rows contributed materially to savings produced
   `savings > current` → percentage > 100% rendered as nonsensical
   `-117%`. Fixed at the `_build_summary` site only — compute
   `cohort_first_run_savings = current_usd - optimized_usd` (both
   guaranteed over the same rowset by construction), then percentage.
   Aggregate input-only `aggregate_savings_first_run_usd` field
   unchanged — preserves greenfield contract. **Mutation-tested: pre-fix
   formula yields `pct = 7657` on the new fixture; post-fix yields `pct
   = 0` (Row A has no cache subset → cohort savings is 0).** Fixture is
   structurally robust: includes a pre-condition `assert savings >
   current` that fails with a clear message if the bug scenario isn't
   actually exercised.

3. **CR-1430 C3** — `declared:` → `expected:` rendered label rename.
   Today's `declared:` label shows the node's selected SUBSET reordered
   to match `## Cache` (it's the exact replacement to write into
   `prompt_cache:`), not the full `## Cache` declaration. Renamed to
   `expected:` for clarity. Sites: `data_flow.py:_make_order_mismatch_diagnostic`
   + `warning_catalog.py::_ORDER_MISMATCH_MESSAGE` + 1 byte-equal test
   fixture + spec amendment at `task-159.md:212`. Internal context keys
   (`declared`, `declared_str`) and JSON-facing typed payload kept
   unchanged for backward-compat — only the rendered label changes.

4. **CR-1430 C4** — broaden `compute_node_cache_key` filter. Pre-fix
   filtered only `_source_line` (singular). Parser also writes
   `_source_lines` (plural, code-block line ranges) and `_source_files`
   (per-file-ref provenance — verified across 5 production sites:
   `file_resolver.py`, `ir_schema.py`, `path_validation.py`). Same
   regression class as GH #357 would reopen on the day either suffix
   lands in `resolved_inputs` (e.g. via a future template-resolution
   path that includes nested node config). Fixed via explicit suffix
   tuple `_METADATA_KEY_SUFFIXES = ("_source_line", "_source_lines",
   "_source_files")` — targeted, NOT a generic `_`-prefix rule (would
   over-filter user-defined inputs like `_internal`).

5. **CR-1305 W3** — memo tier reachability via default-construct. Pre-fix
   the `memo_cache` kwarg on `analyze()` accepted a `MemoizationCache`
   but no production entry point (CLI, MCP, dry-run nudge) supplied
   one. `data_source: "memo"` was unreachable in production despite
   the codepath existing. **Top-10% reframe** (caught by re-reading the
   handoff's "construct dependencies at the lowest layer" lens, NOT my
   first proposal which threaded construction through 3 entry points):
   default-construct in `analyze()` itself when `memo_cache is None`,
   reading from `~/.pflow/cache/cache.db` if it exists. Same shape
   ruff/clippy/mypy use for workspace caches. New `_default_memo_cache()`
   helper checks file existence BEFORE construction (load-bearing — the
   `MemoizationCache.__init__` runs `_init_db()` which CREATES schema;
   skipping construction when absent keeps analyze invocations
   side-effect-free on greenfield workflows). Two tests: production-shape
   integration (seed → analyze → assert `data_source == "memo"`) AND
   read-only invariant regression (greenfield → no cache.db side-effect).

**Refactor in support of the no-`# noqa: C901` rule:** W3's addition pushed
`analyze()` complexity from 10 → 11. Decomposed into 4 named pipeline
helpers (`_resolve_trace_data`, `_extract_declared_chunks`,
`_extract_cache_ttl`, `_build_per_call_rows_and_warnings`). `analyze()`
now reads as a clean 7-step pipeline, each helper ≤4 complexity.

### GH issues filed for the 2 deferrable findings

Two findings worth tracking that fall outside the recommendations-section
scope:

- **GH #359** — `analyze-cache --format=json` emits LiteLLM cost-map fetch
  warnings to stderr. CR-1305 W4. Real agent-UX concern; bounded fix
  (configure LiteLLM to skip remote fetch or suppress its logger around
  analyzer paths). v1.x scope.
- **GH #360** — `analyze-cache` silently undercounts cost for dynamic
  batch sizes. CR-1430 W7. Real correctness concern: workflows with
  `batch: ${file_ref}` get cost figures that don't reflect 30× fan-out.
  Minimum fix is an info note in `analysis.notes` when N nodes have
  unknown batch size. v1.x cost-fidelity follow-up.

Both issues encode the load-bearing context (root cause, fix shape,
suggested test) so the scratchpads can be removed without losing
information.

### Findings deliberately NOT fixed (per critical-thinking triage)

- **CR-1305 C1** (analyze-cache bypasses validator) — already in plan
  as A.6 amendment; sub-segment A executes.
- **CR-1305 C2** (stubbed analyzer math) — sub-segment A scope (4
  catalog detections + per-chunk tokens + cost wiring).
- **CR-1430 W1** (`_estimate_cacheable_tokens` 75% stub) — sub-segment
  A scope (real per-chunk estimation).
- **CR-1430 W2** (`_EMPTY_CACHE_RENDER` asymmetric restore) —
  cosmetic, no consumer harm.
- **CR-1430 W3** (parser silently drops non-YAML in `## Cache`) — UX
  polish, no observed user trip-up.
- **CR-1430 W4** (trace 2.1.0 emits `null` workflow_path) — minor
  data-shape concern, consumer gate handles it.
- **CR-1430 W5** (OpenAI no-op `cache_control` marker) — defended in
  code (shape consistency across providers).
- **CR-1430 W6** (`"LLMNode"` string hardcoded in gate) — debug log
  already surfaces silent-bypass risk.
- **CR-1430 W8** (non-string `node_type` skip) — intentional layered
  defense documented in code.
- **CR-1430 S1-S8** — comment density, test bloat, cosmetic. Better
  as a focused cleanup PR than mixed in here.

### Bonus observation (not fixed, flag inline when sub-segment A touches it)

`tests/test_core/test_cache_analysis_per_id_coverage.py:369` uses
`"item_alias": "item"` in a batch fixture, but the IR-level key is
`"as"` (per `ir_schema.py:98`, `compiler.py:343`). Test passes by
accident — the wrong key falls back to default `"item"` which matches
the fixture's `${item.text}` prompt. Sub-segment A's executing agent
will likely touch this fixture; flag inline as a comment when they do.

### Tacit knowledge for the next agent (sub-segment A)

1. **The cohort-consistent percentage fix changes JSON output semantics
   subtly.** Pre-fix: `savings_pct_first_run` was `(input-only-savings,
   priced-rows-superset) / (full-cost, rows-with-output-subset)` —
   sometimes >100%, sometimes <0%, but always present. Post-fix:
   percentage tracks `(current - optimized) / current` over the
   rows-with-output cohort. **None on full greenfield**; agents read
   the absolute `aggregate_savings_first_run_usd` figure for
   greenfield-savings opportunities. The renderer / sub-segment A
   recommendations consumers should respect this two-regime split.

2. **`_default_memo_cache()` may surprise tests that previously got
   `memo_cache=None` by default.** The conftest test isolation patches
   `Path.home()` to `tmp_path`, so `~/.pflow/cache/cache.db` resolves
   to a non-existent path → helper returns `None` → observable
   behavior is unchanged for tests that don't explicitly seed a memo
   cache. If sub-segment A tests start seeding `MemoizationCache(tmp_path/...)`
   for SOME nodes and asserting other nodes have no memo data, be
   aware that the seeded rows are visible to ALL nodes that share the
   `workflow_path` scope.

3. **The C3 rename is rendered-label only.** Diagnostic `context["declared"]`
   and `context["declared_str"]` keep the original names — agents
   reading JSON output dispatch on those typed payloads. The render
   layer surfaces `expected:` for human readability. The asymmetry is
   deliberate; surface to user before changing if a future task
   depends on naming consistency.

4. **C4's metadata-suffix tuple is the place to extend** when new
   parser-injected metadata keys are added. Single source of truth at
   `runtime/cache.py:_METADATA_KEY_SUFFIXES`. Same filter is applied
   at `compute_node_config` for the config hash (different code path,
   same conceptual contract — keep them in lockstep if either is
   touched).

**Mutation-tested**: C2 cohort-percentage fix — reverting the production fix to the buggy formula causes the new test to fail with `pct = 7657 > 100`. The test fixture's structural pre-condition (`assert savings > current`) confirms the bug scenario IS exercised.

---

## Recommendations-section implementation interrupted: Sub-segment A partial (2026-04-30)

User asked to stop and update this progress log so another agent can continue.
This entry covers the partial implementation done in the interrupted turn.
No commits were made.

### What I implemented

Started **recommendations-section plan sub-segment A** only. Sub-segments B
and C were not started.

**Production files modified:**
- `src/pflow/core/cache_analysis/analyze.py`
  - Added in-workflow producers for:
    - `cache.batch-prewarm-recommended`
    - `cache.dynamic-before-static`
    - `cache.padding-advisory`
    - `cache.shared-context-undeclared`
  - Added greenfield-only `suggested_blocks` population.
  - Added `validate_data_flow(..., check_inputs=False)` cache-ID surfacing
    for validator-shipped findings (`cache.order-mismatch`,
    `cache.unused-chunk`, `cache.invalid-on-non-llm`).
  - Uses full template paths for chunk matching; does **not** use
    `extract_root_node_id` for declared-cache membership.
  - **Important user decision applied:** for
    `cache.batch-prewarm-recommended`, the spec wins over the plan:
    the warning fires only when `prewarm` is absent. `prewarm: false`
    is an explicit opt-out and suppresses the warning.
- `src/pflow/core/cache_analysis/render_text.py`
  - Suggested block text rendering now includes per-node `prompt_cache:`
    assignments.
- `src/pflow/core/cache_analysis/summarize.py`
  - Dry-run nudge now prefers `aggregate_savings_first_run_usd` when absolute
    current/optimized costs are unavailable, preserving the greenfield
    input-only savings contract.
- `src/pflow/core/cache_analysis/warning_catalog.py`
  - `format_dry_run_nudge` now renders a dollar-only form when savings USD is
    known but percentage is unavailable, e.g.
    `Cache: 2 design opportunities available (estimated -$0.42/run).`

**Tests modified / added:**
- NEW `tests/test_core/test_cache_analysis_per_id_emission.py`
  - Production-shaped end-to-end `analyze(...)` tests for the four A warning
    IDs plus `suggested_blocks`, with dotted-path coverage.
- `tests/test_core/test_cache_analysis_analyze.py`
  - Added A.6 tests proving analyze-cache surfaces validator cache findings
    and filters non-cache diagnostics.
- `tests/test_core/test_cache_analysis_summarize.py`
  - Added greenfield aggregate-savings nudge test.
- `tests/test_core/test_cache_analysis_per_id_coverage.py`
  - Removed the four A IDs from `_STUBBED_PRODUCERS_DEFERRED_TO_V1X`.
  - Added production-driven coverage for the four A IDs.
  - Fixed the previously noted accidental fixture key from `item_alias` to
    IR-correct `as`.

### Deviations / open implementation notes

1. **Spec override on A.1 is intentional.** The recommendations plan said
   `prewarm` "not declared (or False)" should emit. User confirmed the spec
   behavior: `prewarm: false` is explicit opt-out. Keep this unless the user
   changes the decision.

2. **Savings estimates for A detections are intentionally simple.**
   `_estimate_token_savings_usd()` uses input-rate × tokens × calls × 0.9.
   If model pricing is unavailable, `savings_usd=None` flows through the
   existing nullable-cost catalog path. This keeps with the tri-state contract.

3. **`suggested_blocks` ordering currently sorts by most-shared first, then
   first-seen node index, then chunk name.** In the new fixture, `${concept}`
   sorts before `${concept-brief.response}` because both are shared by two
   nodes and the first prompt mentions `concept-brief.response` then `concept`,
   but both refs are recorded against the same node index and the final
   tie-break is lexical. If the next agent wants exact prompt-order
   tie-breaking, extend `first_seen` to include match position as well.
   Current tests lock the actual deterministic behavior.

4. **`_estimate_ref_tokens()` memo lookup is best-effort.** It fetches the
   latest memo row for the root node and resolves the full ref through
   `TemplateResolver.resolve_template`. Greenfield falls back to tokenizing
   the literal `${full.path}`. This matches the current low-fidelity but
   useful suggested-block path.

5. **A.6 cache validator findings are appended after per-node/shared/padding
   findings.** That can create duplicate IDs if a workflow is invalid and also
   analyzable; dedup is not currently applied inside `CacheAnalysis.warnings`.
   Existing diagnostic identity/dedup infrastructure lives elsewhere. If this
   becomes noisy, apply a small id/source/node dedup pass in `analyze()`.

6. **Potential linter issue not yet checked.** The modified `analyze.py` grew
   several helpers. Run ruff/mypy before proceeding far; if C901 fires, split
   helpers further instead of adding `# noqa: C901`.

---

## Recommendations-section implementation continued: Sub-segments B + C complete (2026-04-30)

Picked up from the interrupted sub-segment A state. No commits were made, and
no new files were staged because the project memory says not to `git add`
without explicit instruction.

### What I implemented

Completed **recommendations-section plan sub-segments B and C** on top of the
already-staged A work.

**Sub-segment B — cross-workflow detections**
- `src/pflow/core/cache_analysis/cross_workflow.py`
  - `walk_cross_workflow()` now returns `CrossWorkflowResult` with:
    - `edges`
    - `cache_items_by_workflow`
  - The walker eagerly records each visited workflow's `## Cache` items using
    the same workflow labels carried by `CrossWorkflowEdge`.
- `src/pflow/core/cache_analysis/analyze.py`
  - Emits `cache.cross-workflow-prose-mismatch` when parent and child declare
    the same full-path chunk name with byte-different `prose_before`.
  - Emits cross-boundary `cache.shared-context-undeclared` for value flow where
    neither side declares the value, with `node_id=edge.parent_node_id` so it
    does not dedup-collide with in-workflow greenfield findings.
  - Rename still takes precedence; prose/value-flow warnings are suppressed
    when `edge.is_rename` fires.
- Tests:
  - Updated existing walker tests for the result object.
  - Added cache-item collection coverage.
  - Added production-shaped analyzer emission tests for prose mismatch and
    cross-boundary shared-context value flow.
  - Removed cross-workflow IDs from the "stubbed producer" set in
    `test_cache_analysis_per_id_coverage.py`.

**Sub-segment C — discrepancy via planner output**
- `src/pflow/execution/result.py`
  - Added `PlanEntry.cache_key: str | None = None`.
- `src/pflow/execution/plan.py`
  - Renamed `_create_planner_shared()` to public `create_planner_shared()` and
    kept `_create_planner_shared = create_planner_shared` as a compatibility
    alias.
  - Propagates `NodePlan.cache_key` into standard-node `PlanEntry` objects for
    cache hits, misses, and cache-disabled nodes. Aggregate/opaque/error
    entries keep `None`.
- `tests/test_execution/test_plan_drift.py`
  - Extended `test_plan_matches_engine_for_workflow_with_prompt_cache` to read
    the engine-written cache key from SQLite and assert
    `PlanEntry.cache_key == engine_cache_key`.
- `src/pflow/core/cache_analysis/analyze.py`
  - Added `_iter_llm_events()` recursive walker that includes cached events and
    nested sub-workflow events.
  - Added `_predict_cache_keys()` that consumes `compile_workflow + build_plan`
    and flattens `PlanEntry.cache_key`, instead of re-deriving runtime hash
    semantics in analyzer code.
  - Handles missing `memo_cache` and `CompilationError` by appending a note and
    continuing with observable-only attribution.
  - Emits `cache.discrepancy` for:
    - TTL expiry
    - skipped cache chunks
    - cache-key mismatch when predicted keys are available
    - unknown attribution when observable fields are insufficient
  - Aggregates discrepancies by `(node_id, root_cause)` with
    `affected_invocations`, capped at 20.
- Tests:
  - Added production-shaped discrepancy tests with 2.1.0 trace fixtures.
  - Added 2.0.0 silent fallback coverage.
  - Added sub-workflow event recursion coverage.
  - Removed `cache.discrepancy` from the "stubbed producer" set; production
    coverage now drives every catalog ID.

**Additional test contract fix**
- `tests/test_core/test_cache_analysis_warnings.py`
  - Updated the older dry-run nudge expectation to match the staged A behavior:
    when `savings_usd` is known but `savings_pct` is unavailable, render the
    dollar-only nudge instead of hiding the figure.

### Deviations from plan

1. **`cache.prewarm: false` behavior from A preserved.** I did not revisit the
   user's prior decision: only absent `prewarm` triggers
   `cache.batch-prewarm-recommended`; explicit `prewarm: false` is an opt-out.

2. **No staging.** Existing A changes were already staged before this turn; B/C
   changes are currently unstaged. This is intentional because the project
   memory says not to `git add` unless explicitly asked.

3. **Direct full `ruff check src tests` is not a valid sandbox proxy for
   `make check`.** It reports unrelated existing issues and a Python 3.9 parse
   target mismatch. I used the sandbox-safe direct tools on touched files,
   plus full mypy and deptry.

### Current working tree state

At the end of this turn:
- Previously staged A files remain staged.
- B/C additions and the warning-catalog test expectation update are unstaged.
- There are mixed staged/unstaged files (`MM`) where B/C changed files that A
  had already staged.

### Open hedged claims and follow-ups

- **PlanEntry JSON exposure:** `PlanEntry.cache_key` is not added to the dry-run
  JSON formatter. The analyzer consumes the object directly; text/JSON dry-run
  output remains unchanged. If agents later need predicted keys in dry-run JSON,
  that should be an explicit API decision.
- **Discrepancy attribution is intentionally v1-simple.** No
  `parallel_write_race` correlation was added; the plan listed it as deferred.
- **Sub-workflow duplicate node IDs:** `_flatten_plan_keys()` remains flat by
  `node_id`, matching the handoff's instruction not to solve heterogeneous
  batch sub-plan attribution in this pass.

---

## Post-recommendations 4-agent code review + applied fixes (2026-04-30)

After the recommendations-section A+B+C work was staged, ran a 4-agent
code review (silent-failures + impact-completeness + test-fidelity +
feature-interactions — the 4 highest-leverage subagents for this surface).
Findings concentrated on sub-segment C (discrepancy detection); A and B
were largely clean. User reviewed findings, made decisions, then I applied
fixes in two passes: a primary pass on the user's directly-confirmed
decisions, then a self-audit pass that surfaced 4 additional loose ends.

### User decisions (with verification before recommendations)

Verified before surfacing the decisions:

- **Trace 2.1.0 does NOT record input parameters** — confirmed via
  `grep "parameters\|inputs\"" runtime/workflow_trace.py` (zero matches in
  save path). This is load-bearing for Decision 1 — it eliminated
  "compare against trace's recorded params" as a fix shape.
- **`PlanEntry.cache_key` is NOT in `_entry_to_dict`** — confirmed at
  `plan_formatter.py:344`. Required explicit surface decision.
- **BFS-downstream cache_keys can't be predicted at plan time** —
  `_make_downstream_entry` can't call `plan_node()` because BFS-
  downstream nodes (by definition) depend on upstream that hasn't
  materialized — template resolution would fail. The planner's design
  is "boundary-of-miss = mark downstream, don't compute." This
  reversed a reviewer's claim that line 745 was missing `cache_key=`
  propagation; calling `plan_node` would crash, not improve. **See
  tacit-knowledge #1 below for the broader implication**: this gap
  isn't fixable without partial-execution or post-edit data that
  doesn't exist anywhere; the right response is the silent-skip note,
  not a fix.
- **Heterogeneous batch sub-workflow note-only fix** matches the
  handoff's explicit guidance ("don't try to fix this elegantly during
  implementation; surface as notes entry; defer fine-grained handling
  to v1.x").

User decisions:

- **D1 (importance 4/5)**: when CLI inputs ≠ trace's run inputs,
  predicted_keys derived from defaults flood the report with false
  `key_mismatch` attributions. **(A) Suppress predicted-key matching
  when `params={}` + declared inputs, emit single note**. Rationale:
  trace 2.1.0 lacks input fingerprint (no ground-truth comparison
  possible without a 2.2.0 bump). Top-10% pattern from rustc's
  incremental cache: when you don't have ground truth, **honest "I
  can't tell" beats wrong answer**.
- **D2 (importance 2/5)**: surface `PlanEntry.cache_key` in dry-run
  JSON. Rationale from top-10% codebases (rustc `-Z`, mypy `--report`,
  ruff rule IDs, TypeScript `.d.ts`): expose internal identity for
  debugging; don't shove it in default human-readable output. Dry-run
  JSON is the machine-readable surface — right home for cache_key.
- **D3 (importance 3/5)**: Option **(B) — add ALL ~7 missing tests
  now**, including the integration test that replaces the mocked
  `_predict_cache_keys` test.
- **D4**: heterogeneous batch attribution stays note-only; matches
  handoff direction.

### Production fixes applied (in order)

**Batch 1 — single-line fixes:**
1. **`chunks_skipped` gate fix** at `_emit_discrepancy_diagnostics`:
   read `chunks_skipped` BEFORE the cache-disengaged gate; change gate
   to `if cache_create == 0 and cache_read == 0 and not chunks_skipped`.
   Without this, `chunk_skipped` attribution was unreachable for the
   branch-absent scenario it was designed for (silent-failures C2).
2. **Forward-compat trace `format_version`**: broadened
   `startswith("2.1")` → `startswith("2.") and not startswith("2.0")`.
   Future 2.2+ traces continue to work per the runtime/CLAUDE.md
   additive consumer rule. 2.0.0 still skipped (missing fields; note
   already emitted at trace-load time) (impact-completeness #5).
3. **Broadened `_predict_cache_keys` except clause**: added
   `MarkdownParseError`, `WorkflowValidationError`, `FileNotFoundError`,
   `ValueError` to the catch list. CLI/MCP `analyze-cache` paths don't
   wrap in broad `except` like `runner.py`'s dry-run nudge does, so a
   stray exception would crash the whole command (silent-failures W4 +
   impact-completeness #2).

**Batch 2 — Decision 1 (predicted-key staleness):**
4. **Decision 1 implementation**: `_predict_cache_keys` now checks
   `if not parameters and isinstance(workflow_ir.get("inputs"), dict)
   and workflow_ir["inputs"]:` and returns `({}, [note])` early. The
   note explains the agent why predicted-key matching was skipped and
   how to re-run for full detection.

**Batch 3 — Decision 2 (cache_key in JSON):**
5. **`_entry_to_dict` extension**: added `cache_key` serialization when
   not None. Required decomposing the function into a constants-driven
   loop (`_OPTIONAL_SCALAR_FIELDS` tuple) to satisfy C901 complexity
   threshold without `# noqa`.

**Batch 4 — heterogeneous batch + cap notes:**
6. **`_flatten_plan_keys` collision detection**: added a second pass
   that detects per-item cache_key divergence (heterogeneous batch
   sub-workflow), drops colliding nodes from `predicted_keys`, returns
   `(keys, notes)` tuple. Emits a notes entry explaining the coverage
   gap (silent-failures C1, feature-interactions C2).
7. **`_aggregate_and_cap_discrepancies` cap note**: added `notes`
   parameter; when `len(aggregated) > max_total`, append
   `"Discrepancies: N additional groups suppressed by cap..."`. No
   more silent truncation (silent-failures W3).

**Batch 5 — silent UX gaps:**
8. **`_populate_suggested_blocks` D3 deferral note**: when
   `## Cache` already declared, append note explaining steady-state
   suggestions are deferred to v1.x. No silent return (silent-failures
   W2).

### Self-audit pass — 4 additional loose ends found and fixed

After staging the primary fixes, the user asked "are you fully happy
with the implementation?" — a forcing function for honest self-audit.
Found 4 issues I'd glossed:

#### Loose end 1: BFS-downstream coverage note miscounted

**The bug I introduced.** My initial `_flatten_plan_keys` counted plan
entries with `cause="downstream"` and emitted a "predicted-key matching
unavailable for N nodes" note. But this counts **plan structure**, NOT
**actual silent skips of trace events**. For a non-cache workflow + 2.1
trace, the note would fire even though no discrepancies were possible
(cache disengaged → all events skipped at the disengaged-cache gate,
before predicted_key matters).

**Root cause analysis**: I'd put the silent-skip counter at the wrong
abstraction level. The semantically correct site is at the actual
silent-skip decision point inside `_emit_discrepancy_diagnostics` —
where the analyzer encounters a real trace event with cache engaged AND
no predicted_key AND no observable signal AND silently `continue`s.

**Fix**: removed the BFS-downstream count from `_flatten_plan_keys`
(kept the heterogeneous-batch collision detection — that IS plan-time
structural). Added `silent_skip_no_predicted_key` counter inside
`_emit_discrepancy_diagnostics`. Note now fires only when real trace
events were silently skipped, not when plan structure happens to
contain downstream entries.

**Lesson**: when adding observability for "the analyzer couldn't
attribute X events", count at the decision point (event-walking),
NOT a structural proxy (plan-walking). Top-10% codebases (rustc's
diagnostic emission, mypy's stub-coverage warnings) all count at the
moment-of-truth, not at structural dependencies.

#### Loose end 2: validator producer-bugs crashed the analyzer

**Real bug surfaced by my own test fixture.** When I added a test for
the broadened `except` in `_predict_cache_keys`, my fixture (`batch:
"not-a-dict-or-list"`) crashed `validate_data_flow` with
`AttributeError: 'str' object has no attribute 'get'` at
`data_flow.py:325` (`batch_config.get("as", "item")`). This happens
BEFORE `_emit_discrepancy_diagnostics` runs — `_cache_validator_findings`
is called first and propagates the exception unhandled.

The reviewer (silent-failures S3) had flagged this exact concern and I
dismissed it as low-priority. My own test surfaced it.

**Fix**: wrapped `validate_data_flow` in a defensive `try/except` with
debug logging in `_cache_validator_findings`. The `# noqa: BLE001` is
appropriate here — defending against producer-bugs in a sibling module
is the textbook case for `except Exception`. Malformed-IR cases still
surface at `pflow run` validation; the analyzer's job is best-effort
signal.

**Lesson**: when a reviewer flags "X may crash on malformed IR" and you
can't immediately reproduce, **don't dismiss — write a test that tries
to reproduce**. If the test surfaces the bug, fix it. If it doesn't,
the test becomes a regression gate.

#### Loose end 3: missing negative fixtures for cross-workflow B.2/B.3

Two structural defenses absent:

- **`cache.cross-workflow-prose-mismatch` byte-equal negative**: no
  fixture asserting "fires only when prose differs." Removing the
  byte-comparison gate (`parent_prose != child_prose`) would emit
  prose-mismatch on EVERY shared chunk name and pass all existing
  tests.
- **Rename-precedence DD#26 invariant**: no fixture asserting "rename
  detection suppresses prose-mismatch on the same edge." Removing the
  `if edge.is_rename: continue` gate would double-emit on every renamed
  chunk.

**Fix**: added both tests as parametrized fixtures with explicit
mutation-test guards in the docstrings (so future contributors know
exactly what removing the gate would break).

**Lesson**: the **mutation-test thought experiment** rule from the plan
(comment out the production code, fixture must fail) is the right
litmus for negative fixtures. A negative fixture that "passes when the
condition isn't met" is meaningless — it has to fail when the gate is
removed. Document the mutation in the docstring so future readers know
what the test guards.

#### Loose end 4 — considered, deferred: `_cache_items` dedup

`_cache_items` exists in both `analyze.py:842` and
`cross_workflow.py:288` (8 lines each, slightly different return types
— list vs tuple). Considered creating a shared helper.

**Top-10% lens**: the cost of a shared module + 2 import edges exceeds
the cost of trivial duplicate code that hasn't drifted. Both
implementations enforce the same parser-validated shape contract; if
either drifts, tests catch it. The DRY-vs-simplicity tradeoff favors
simplicity here.

**Lesson** for future contributors: don't dedup until the duplication
has actually caused drift. Top-10% codebases (rustc, mypy) have many
small shape-validation patterns duplicated in different files — they
reach for shared helpers when the cost of drift exceeds the cost of
new import edges.

### Test additions (Decision 3 option B)

Added to `tests/test_core/test_cache_analysis_per_id_emission.py` (the
mocked-test replacement file from sub-segment C):

**Replacements/refactors:**
- Fixed vacuous `test_analyze_filters_non_cache_data_flow_diagnostics`
  in `test_cache_analysis_analyze.py`. The original IR didn't produce
  any diagnostic with `check_inputs=False`, so the assertion passed
  vacuously over an empty list. Replaced with a forward-template-
  reference IR that produces a non-cache validator diagnostic, plus a
  sanity-check assertion that the fixture is non-vacuous.

**New unit tests for boundary conditions (5):**
- `test_discrepancy_silent_when_actual_matches_prediction` — locks
  the in-agreement gate (`abs(predicted_pct - actual_pct) < 5`).
- `test_discrepancy_skips_when_cache_disengaged_and_no_chunks_skipped`
  — locks the disengaged-cache skip.
- `test_discrepancy_FIRES_when_cache_disengaged_BUT_chunks_skipped` —
  regression gate for Loose-end #1's chunks_skipped fix.
- `test_discrepancy_skips_predicted_key_match_when_compile_fails_no_inputs`
  — D11-A path coverage (Decision 1).
- `test_discrepancy_compile_failure_falls_back_to_observable_only` —
  exercises broadened except + defensive validator together.

**New walker + aggregator tests (5):**
- `test_iter_llm_events_includes_cached_events` — load-bearing walker
  contract that distinguishes the analyzer's walker from the trace's
  own (which skips cached events).
- `test_iter_llm_events_recurses_into_batch_items` — covers the
  previously untested `batch_items[].events` recursion path
  (handoff gotcha #5).
- `test_aggregator_groups_by_node_and_root_cause_with_affected_invocations`
  — CRIT-4 from Round 1.
- `test_aggregator_caps_at_max_total_and_notes_truncation` — locks the
  cap behavior + truncation note (silent-failures W3 fix).
- `test_aggregator_does_not_mutate_shared_context_refs` — verifies the
  `dataclasses.replace` defensive pattern (Round-2 W-SILENT-2).

**New silent-skip note tests (2):**
- `test_discrepancy_emits_silent_skip_note_when_no_predicted_key_and_no_signal`
  — locks Loose-end #1's note emission.
- `test_discrepancy_emits_no_silent_skip_note_for_non_cache_workflow`
  — regression gate for the bug I introduced (non-cache workflow MUST
  NOT emit a coverage note).

**New negative fixtures (2):**
- `test_cross_workflow_prose_mismatch_silent_when_prose_byte_equal` —
  byte-comparison gate.
- `test_cross_workflow_prose_mismatch_suppressed_by_rename_precedence`
  — DD#26 invariant.

**New integration test — replaces mocked test (1):**
- `test_discrepancy_key_mismatch_via_real_planner_consumption` — drives
  the C.2 architectural pivot through real production code:
  `WorkflowRunner.run()` populates the memo cache via real engine; SQL
  reads engine's actual cache_key; analyzer is called with DIFFERENT
  params + a synthetic 2.1.0 trace recording the engine's cache_key;
  asserts `key_mismatch` attribution is correctly derived via
  `build_plan` consumption (no monkeypatch of `_predict_cache_keys`).
  Mutation-test: dropping `cache_key=planned.cache_key` from any
  PlanEntry constructor in `plan.py` makes this test fail.

The original mocked test
`test_discrepancy_fires_for_key_mismatch_when_prediction_available`
was kept — it's a unit test of `_attribute_root_cause`'s key_mismatch
attribution path with controlled inputs. Both are valuable: integration
locks the architectural pivot end-to-end; mocked locks the attribution
logic.

### Items considered but deferred (with reasoning)

These were flagged by reviewers but evaluated and rejected for this PR:

- **`storage_mode: shared` × parallel batch defensive note**
  (feature-interactions C3). Already documented as v1-unsupported in
  `runtime/CLAUDE.md`. Not a regression from this PR; not worth
  detection complexity for a known-unsupported combo.
- **Per-id `savings_usd` value assertions** (test-fidelity W10).
  Tri-state contract is locked in catalog tests + renderer tests;
  per-id emission tests would over-couple to specific cost values that
  drift with LiteLLM pricing updates.
- **`chunks_skipped is None` field-absent test** (test-fidelity W6,
  CRIT-7). Production trace 2.1.0 always populates this field as `[]`;
  the `None` branch is a synthetic-fixture defensive fallback. Adding
  a test would lock dead-code behavior.
- **`_aggregate_and_cap_discrepancies` ID-namespace per root_cause**
  (impact-completeness #4). Forward-defensive against a hypothetical
  future consumer applying `deduplicate_diagnostics()` on analyzer
  warnings. No current consumer does this; defer until/unless the
  dedup path lands.
- **Padding-advisory empty-batch fixture** (test-fidelity W11). When
  `batch_size_estimated == 0`, falsy fallback to `affected_calls=1`
  produces a misleading `savings_usd` figure but the warning is
  advisory, not a savings claim. Cosmetic.

### Tacit knowledge for future agents

These are the load-bearing insights from this session that aren't
obvious from the code alone:

**1. BFS-downstream cache_key gap: smaller than it looks; no fix
actually addresses the dominant use case.** The reviewer flagged
`_make_downstream_entry` (`plan.py:745`) for not passing `cache_key=`.
When I dug in, the framing kept simplifying:

- *Reviewer's claim*: pass `cache_key=planned.cache_key` from
  `plan_node()`. Verified false — calling `plan_node()` from this
  path would CRASH because BFS-downstream nodes' templates reference
  upstream that wouldn't have executed yet. Strict mode raises
  template_exception; permissive mode echoes literal `${node.X}`
  strings into resolved input → produces a cache_key derived from
  unresolved literals → guaranteed false `key_mismatch` on every
  comparison. Worse than the current "don't predict."
- *My initial framing*: "structurally undefined, defer Fix A
  (memo speculation) to v1.x." This was still overstated. After the
  user pushed back ("schema bumps are cheap, why is Fix B 250 LOC"),
  re-decomposing showed Fix B is actually ~140 LOC, **but it doesn't
  solve the dominant use case either.**

The fundamental wall: predicting downstream cache_key for a fresh
run requires knowing what upstream WOULD produce on a fresh run. For
the upstream-edit cascade scenario (user edits node_A, runs
`analyze-cache --from-trace` to see what's affected downstream),
**no source has post-edit upstream output**:
- Trace records pre-edit upstream output (frozen at trace time)
- memo cache stores pre-edit output (keyed by old cache_key OR
  retrieved by `get_latest_for_node` — both return pre-edit data)
- Only running the workflow produces post-edit output, which is
  exactly what dry-run avoids

So Fix A (memo speculation) and Fix B (trace records resolved
inputs) and Fix C (iterative trace cache_key walk) **all hit the
same wall**. They differ only in implementation; none solves the
cascade scenario.

What the gap actually misses (after honest re-decomposition):

| User intent | Tool that handles it | BFS-downstream gap impact |
|---|---|---|
| "Did my edit change THIS node's cache_key?" | Already works — edited node is the miss boundary; `plan_node()` IS called for it | None |
| "Did caching work as expected on the LAST run?" | Observable attribution (TTL expiry, chunks_skipped) — **the spec mode-4 example uses TTL-expiry attribution, not key_mismatch** | None |
| "What WOULD downstream cache_keys be after my edit?" | Requires running the workflow — not what `analyze-cache` is for | Fundamental |

The third bucket is the only thing the gap affects. The right user
workflow is: edit → re-run (engine produces fresh trace with cache
misses) → `analyze-cache --from-trace fresh.json` (correctly
identifies misses via observable attribution).

**Action**: do not fix this in v1.x. The current implementation's
silent-skip note correctly tells agents "I can't predict for these
N events" — the right surface for a fundamentally-unfixable case.
If/when a future change wants to address this anyway, recognize the
upstream-cascade scenario can't be solved without:
- Trace 2.2.0 recording **upstream OUTPUTS** (not inputs) — but
  even then, the analyzer would only catch local-edit cases, which
  already work
- OR partial workflow re-execution at plan time — fundamentally
  changes what dry-run means

**Lesson**: when a reviewer flags a coverage gap, decompose the
fix HONESTLY before estimating cost. My first instinct was "Fix B
is 250 LOC" — handwaving. Decomposing showed it's 140. Then
asking "what does Fix B actually buy" showed it doesn't buy what I
thought. The cost question masked a more important question:
**does the fix solve the actual problem?** Three "fixes" turned
out to all hit the same wall once I traced the data flow. The user
got me to this realization by pushing on cost; the actual finding
was correctness, not cost.

**2. Trace 2.1.0 lacks input fingerprint.** The most common
analyze-cache invocation pattern is
`pflow analyze-cache <wf> --from-trace <path>` WITHOUT
re-supplying the original inputs. For workflows with default values,
`compile_workflow` succeeds with empty params → `build_plan` predicts
cache_keys derived from defaults → false `key_mismatch` for every
input-referencing node. The fix (Decision 1) detects this case and
suppresses predicted-key matching with an honest note. The
principled long-term fix is trace 2.2.0 recording an input
fingerprint — out of scope.

**3. Silent-skip count belongs at the decision point, not a
structural proxy.** When implementing observability for "X events
weren't attributed," count at the moment-of-truth (event walking)
not at structural dependencies (plan walking). Plan structure is a
proxy that produces false positives for orthogonal scenarios. This
mirrors how rustc emits diagnostics — at the moment the compiler
gives up on a query, not at the AST node where the query was
declared.

**4. The validator can crash on malformed IR.** `validate_data_flow`
has producer-bugs (`AttributeError` on `batch_config.get(...)` when
batch is a string instead of dict). The analyzer's
`_cache_validator_findings` MUST be defensive — wrap in
`try/except Exception` with debug logging. Future agents adding new
analyzer pipeline stages that consume `data_flow.py` outputs should
follow the same pattern: `validate_data_flow` is a "best-effort
producer" from the analyzer's POV.

**5. Heterogeneous batch sub-workflow collision is plan-time
detectable.** Per-item child plans share `node_id` but compute
different `cache_key` per item. `_flatten_plan_keys` detects this and
drops colliding nodes (observable-only fallback) rather than picking
an arbitrary winner. Top-10% pattern from rustc/clippy: when in doubt,
**refuse to attribute rather than misattribute**. The note explains
the coverage gap so agents understand WHY some discrepancies aren't
emitted.

**6. The `dataclasses.replace` defensive pattern in
`_aggregate_and_cap_discrepancies` is load-bearing.**
`make_diagnostic` may share `context` dicts across diagnostics in the
same group. In-place mutation (`representative.context["X"] = Y`)
would leak `affected_invocations` to other diagnostics. Use
`replace(representative, context=merged_context)` to create a fresh
diagnostic with merged context. Documented inline; tested by
`test_aggregator_does_not_mutate_shared_context_refs`.

**7. The `_iter_llm_events` walker has 3 nesting paths — only 2 are
event-yielding.** Trace events can appear directly,
`event["batch_items"][i]` can have `llm_call` (flat-batch case), AND
`event["batch_items"][i]["events"]` can recurse (sub-workflow
batch-item case). Handoff gotcha #5 explicitly flagged the deep
nested-recursion path as easy-to-miss. Both `batch_items` paths are
now covered by tests.

**8. Decision 3 option (B) was the right call.** Adding ALL ~7 missing
tests up-front (~30 LOC each, ~210 LOC total) was strictly cheaper
than the cost of a future regression. The handoff explicitly warned:
"Segment 4's stubs survived 4-agent code review because per-id tests
round-tripped through `make_diagnostic` (catalog dispatch) but never
exercised emission paths." Don't fall back to round-trip tests when
emission tests are harder to write.

**9. The mocked `_predict_cache_keys` test still has value.** I
considered deleting it after the integration test landed. But it
tests `_attribute_root_cause`'s key_mismatch logic in isolation with
controlled inputs — that's a legitimate unit test. Both tests are
valuable: integration locks the architectural pivot end-to-end;
mocked locks the attribution logic.

**10. The "test fixture must produce a non-cache diagnostic" sanity
check is the cure for vacuous negative controls.** When rewriting
the A.6 negative control, my first IR (forward-template-reference)
produced no diagnostic with `check_inputs=False` — the assertion
would have passed vacuously over an empty `result.warnings`. Added a
sanity-check assertion (`raw = validate_data_flow(...); assert
any(d.id is None or not d.id.startswith("cache.") for d in raw)`)
that fails the test if the fixture is vacuous. Future negative-control
authors should do the same.

**11. C901 force-decompose pattern.** The user's no-`# noqa: C901`
directive turned a hard constraint into a refactoring tool. When
adding the `cache_key` branch to `_entry_to_dict` pushed complexity
to 11, decomposing into a constants-driven loop
(`_OPTIONAL_SCALAR_FIELDS` tuple) brought it back to 10 AND made
the function more readable. Future agents: when a function nudges
past 10, decompose into helpers — the result is better code AND
respects the lint contract.

**12. PlanEntry.cache_key in JSON, not text output.** Decision 2 (A)
chose JSON-only surface. Top-10% codebases (rustc `-Z`, mypy
`--report`, ruff rule IDs) expose internal IDs for debugging via
machine-readable surfaces, never default text output. The cache_key
hex string is debugging info; surfacing in text would clutter the
plan summary for the 95% of users who don't debug cache hashes.

**13. The "did the reviewer claim X is a bug? verify before
accepting" pattern.** Two reviewer claims in this session reversed
on verification: (a) "BFS-downstream missing cache_key=" — actually
structurally undefined; calling plan_node would crash. (b) "trace
records params for comparison" — actually doesn't; eliminated an
entire decision branch. Always run the verification grep BEFORE
designing the fix; the right shape often diverges from the
reviewer's framing.

---

## Verification-specialist CLI drill — 4 production bugs fixed (2026-04-30)

After the 4-agent code review pass landed, ran an adversarial CLI drill (16
hand-built `.pflow.md` workflows + real `pflow` CLI invocations). Test suite
was green going in (5932 tests). The drill surfaced **4 production bugs that
the unit-test surface missed entirely**, each a Pitfall #19 instance (synthetic
fixtures matched buggy code shapes; production code path differed).

### Bug A — `SchemaValidationError` propagates uncaught (the D11-A handoff gotcha realized)

**Symptom**: `pflow analyze-cache <wf>` (without inputs) crashes with exit 1
when a 2.1.0 trace is auto-loaded for any workflow with required inputs. The
**dominant agent flow** (run workflow once → analyze-cache later without
re-supplying inputs) breaks.

**Reproducer**:
```bash
pflow run /tmp/wf.pflow.md name=alice              # creates ~/.pflow/debug/.../trace.json (2.1.0)
pflow analyze-cache /tmp/wf.pflow.md               # CRASHES: "Workflow requires input 'name'" exit=1
pflow analyze-cache /tmp/wf.pflow.md --no-trace-autoload   # works (workaround)
```

**Root cause**: `_predict_cache_keys` only catches `(CompilationError,
MarkdownParseError, WorkflowValidationError, FileNotFoundError, ValueError)`
— NOT `SchemaValidationError`. Both `SchemaValidationError` and
`WorkflowValidationError` are sibling subclasses of `PflowError`, not related
to each other. Decision 1 (`params={}` early-return) handles the most common
case but doesn't catch `SchemaValidationError` for other failure modes (wrong
input type, empty required-non-empty value, etc.).

**Fix**: added `SchemaValidationError` to the except tuple in
`_predict_cache_keys`. New regression test
`test_predict_cache_keys_catches_schema_validation_error` directly
mutation-tests the catch contract.

### Bug B — Per-call hide-clean ignores analysis-wide warnings

**Symptom**: nodes with `cache_ratio ≥ 80%` AND analytical warnings
(`cache.dynamic-before-static`, `cache.batch-prewarm-recommended`,
`cache.padding-advisory`, `cache.below-min-tokens`) are silently HIDDEN from
the default per-call report. Agent reads default output, misses
high-leverage recommendations.

**Production output (pre-fix)**:
```
## Per-call cache report (showing 1 of 2 LLM nodes; all-clean rows hidden)
  creative-direction  ratio=0%  ...           # `review` is HIDDEN
  Hidden: 1 nodes at ≥80% ratio with no warnings
## All warnings
  warning  [cache.dynamic-before-static]  review   # but review HAS a warning!
```

**Root cause**: `_is_row_visible_by_default` (`render_text.py`) only checks
`row.warnings` (the inline tuple), which is **never populated** by any
emitter. All analytical detections emit `Diagnostic` objects to the
analysis-wide `warnings` list, not the row's inline tuple.

**Fix**: built a `nodes_with_warnings` set from `analysis.warnings` (filtered
by `node_id`) and threaded it into `_select_visible_rows` /
`_is_row_visible_by_default`. Also added inline warning ID rendering on row
lines so agents see WHY a row is shown.

### Bug C — Cache ratio > 100% (mathematically nonsense)

**Symptom**: per-call rows show `ratio=103%`, cacheable_tokens >
input_tokens. Visible to agents as "we cache more tokens than we send".

**Reproducer**: any workflow with repetitive prompt text + `prompt_cache:`
declared. The dynamic-before-static test fixture surfaced it: `tokens=1287
cacheable=1326 ratio=103%`.

**Root cause**: `_estimate_cacheable_tokens` uses the 75%-of-`len(prompt)//4`
char heuristic; `input_tokens_estimated` uses `litellm.token_counter`. For
repetitive text where token_counter underestimates relative to the char
heuristic, cacheable > total → ratio > 100%.

**Fix**: clamp `cacheable_tokens = min(cacheable_tokens, input_tokens)` in
`_build_per_call_row`. Cache content can never exceed total input bytes by
construction; the clamp is honest semantically.

### Bug D — `-$0.00/run` violates tri-state contract (3 code paths)

**Symptom**: rendered output emits `"-$0.00/run"` when the underlying savings
estimate is < $0.005 (sub-cent). Misleads agents — segment-4 silent-failures
C1 fix established the contract "None ≠ 0" but only handled `None`, not
"rounds-to-zero".

**Affected paths**:
1. `cache.shared-context-undeclared` recommended action (greenfield literal-token fallback ~1 token).
2. `cache.dynamic-before-static` recommended action (small token counts on short prompts).
3. `cache.opportunities-available` dry-run nudge (greenfield aggregate savings round to zero).

**Fix**: added `_format_savings_usd(value)` helper in `render_text.py` that
returns `"savings unavailable"` for both `None` and `< $0.005`. Mirrored the
threshold in `format_dry_run_nudge` (`warning_catalog.py`). Top-10%
codebases (mypy/ruff/rustc) consistently distinguish "rounds-to-zero" from
"available".

### Tacit knowledge for future agents

**1. Pitfall #19 has now bitten this codebase 7 times.** Each instance: a
synthetic test fixture matched a buggy code shape; production code path
differed; tests passed against fake. **Defense**: every detection added in
v1.x must include AT LEAST ONE test that drives `pflow analyze-cache` (or
the relevant CLI command) end-to-end as a subprocess against a real
workflow file with a real trace.

**2. The "Decision 1 sidesteps Bug A" pattern is fragile.** The early-return
when `params={} + declared inputs` covers the common case but leaves
`SchemaValidationError` uncaught for any other failure mode. Future agents:
when adding compile-time error handling, list the actual exception classes
`compile_workflow` can raise — don't trust the "this is the common path"
shortcut.

**3. Tri-state contracts (None / sub-cent / value) need symmetric coverage
in tests AND production.** Segment 4's silent-failures C1 fix established
the contract for `None`. The sub-cent boundary was missed because no test
exercised values < $0.10. Future agents: when reviewing tri-state code,
write a test at each boundary (None, threshold, just below threshold, just
above threshold).

**4. `cacheable > input` is structurally impossible.** Any code path that
produces it is wrong by construction. The clamp at `_build_per_call_row`
is a defensive corrective; the right long-term fix is replacing the
75%-of-char heuristic with proper per-chunk tokenization (deferred to v1.x
per the cost wiring follow-up). The clamp prevents the symptom from leaking;
v1.x removes the cause.

---

## Bugs E/F/G — fixed in same session (2026-04-30)

### Bug E — Cross-workflow `node_count` accuracy

**Was**: B.3 hardcoded `node_count=2` (parent + child boundary) but the
catalog template renders this as `"{node_count} LLM nodes share static
context..."`. When the child has 0 LLM nodes referencing the input, the
rendered message is factually wrong.

**Fix**: extended `CrossWorkflowResult` with `irs_by_workflow: dict[str,
dict[str, Any]]` (the walker visits each workflow once anyway — exposing
the IRs is zero extra cost). `_cross_workflow_value_flow_opportunity` now
counts LLM nodes that actually reference the value via the new helper
`_count_llm_nodes_referencing_path(ir, template_path)` — uses the
TemplateResolver's `TEMPLATE_PATTERN` walker + coalesce-operand handling
for symmetry with `_dynamic_before_static_warnings`. When `node_count < 2`
(no real cache opportunity), the warning is suppressed instead of
rendering "2 LLM nodes share..." for shell-only edges.

**Tests**: updated
`test_cross_workflow_value_flow_uses_parent_node_id_for_dedup` to use a
fixture with real LLM consumers on both sides + new
`test_cross_workflow_value_flow_suppresses_when_no_llm_consumers`
regression gate.

### Bug F — `predicted_pct` semantics rendered honestly

**Was**: implementation used `predicted_pct = 100 if predicted_key is
not None else 0`. Catalog message_template rendered this as
`"predicted hit_ratio 100%"`, falsely implying a measured hit ratio. The
plan's strict D5 (`100 if predicted_key == actual_key else 0`) couldn't
be applied because the in-agreement gate would silently skip legitimate
key_mismatch discrepancies.

**Fix**: kept `predicted_pct` semantics (used by JSON consumers +
agreement gate), added a new `predicted_label: str` field to the catalog
with three states distinguished via a new helper
`_compute_predicted_label`:

- `"miss"` — no predicted_key (BFS-downstream, partial inputs, etc.).
- `"hit (bytes diverged at runtime)"` — both keys present + differ
  (genuine key mismatch — upstream value changed between analyzer-time
  and traced run).
- `"hit"` — predicted_key set; actual_key matches OR was not recorded.
  Treating "actual_key absent" as a match avoids false-positive
  "diverged" rendering on traces that simply lack the field.

Updated message_template to use `{predicted_label}` instead of
`predicted hit_ratio {predicted_pct}%`. Existing test fixtures
(`_BASE_DISCREPANCY_KWARGS`, `_DISCREPANCY_BASE`, aggregator tests) now
include `predicted_label`.

**Production smoke**:
- TTL expiry (actual_key absent): `predicted hit, actual 0% read —
  root cause: Cache entry was 3700s old (>= 1h TTL)` ✅
- Genuine key mismatch (both keys present + differ):
  `predicted hit (bytes diverged at runtime), actual 0% read — root
  cause: Upstream value changed between predicted run and actual run` ✅

### Bug G — `pflow guide caching` doc drift

**Was**: example showed `declared:` label but C3 (pre-A baseline cleanup)
renamed it to `expected:`.

**Fix**: one-line edit at `src/pflow/guide/features/caching.md:84`.

**Final state**: 5941 tests passing; `make check` clean; `test_plan_drift.py` 34/34; `test_golden_baseline_hashes_match` green; production CLI smoke tests for E/F/G produce correct output.

---

## Stage 1 lyrics-generator verification: architectural finding + Path 1 fix (2026-04-30)

User asked to verify Task 159 against the motivating workflow (lyrics-generator)
before declaring the feature shipped. Before spending money on real LLM runs,
we ran `pflow analyze-cache` against all 17 workflow files in the
lyrics-generator tree (free static analysis). The output exposed a class of
finding that the unit-test surface couldn't catch: the analyzer is structurally
working but doesn't deliver value on real workflows.

### What the static analysis showed

`pflow analyze-cache song-creator.pflow.md` (the heaviest sub-workflow, ~6
sequential LLM calls all sharing concept + concept_brief + creative-direction +
song-architecture context — the spec mode-1 example pattern):

- Token counts reported as `tokens=7` for write-lyrics (actual prompt: ~3752
  tokens). The analyzer was tokenizing the literal filename string
  `"./write-lyrics.prompt.md"` (≈24 chars / 4 ≈ 7 tokens), not the file content.
- Zero `cache.shared-context-undeclared` warnings fired — even though the
  spec mode-1 example explicitly enumerates the shared contexts as
  detection targets.
- Zero `cache.dynamic-before-static` warnings — same root cause.
- 17-23 `cache.cross-workflow-rename-detected` warnings (false-positive flood
  on batch aliases + non-cache boundaries — secondary issue tracked separately).
- `score-choruses` (the canonical 34-item prewarm test from the spec) showed
  zero opportunities — its prompt is `${item.prompt}` assembled in Python
  code, invisible to static analysis (separate compounding issue, not in
  scope here).

### Root cause investigation

`core/file_resolver.py` (Task 129's substrate) exists and works. **Three**
production sites called it independently before this fix:

| Caller | Location |
|---|---|
| Compiler | `runtime/compilation/compiler.py:570-581` |
| Runner | `execution/runner.py:173, 317, 467-482` |
| Validator | `core/workflow/validator.py:784-789` |

The analyzer (`core/cache_analysis/analyze.py`, called via
`cli/commands/analyze_cache.py`) was the **fourth** consumer that needed file
resolution — but didn't call it. `cli/commands/analyze_cache.py:97` does:

```python
resolved = resolve_workflow(workflow)              # returns IR with "./file.prompt.md" still present
analysis = analyze(resolved.ir, ...)               # walks raw IR — never resolves
```

`ResolvedWorkflow` is the misleading name: the IR is only structurally
parsed, NOT file-resolved. Every consumer has to remember to apply file
resolution after the fact.

This is an instance of an architectural pattern already tracked in #321
(output population + cycle detection between planner and runtime) and #334
(per-item workflow resolution + compile cache between planner and runtime).
**Three independent instances of the same "consumer applies X" pattern.**
The analyzer's instance was the worst surfacing because it didn't just
duplicate — it skipped silently.

### Top-10% reframe

The right architectural shape (rustc / TypeScript / mypy / clippy / ruff
all do this): **resolve at the boundary, not at every consumer.** Each of
those tools constructs a canonical, fully-resolved IR/HIR/AST at module-
load time; downstream queries operate on the resolved form and never re-
resolve. `ResolvedWorkflow` already PROMISES this contract in its name.

### Path 1 (this commit) — file resolution centralized at boundary

Files modified:

- `src/pflow/execution/workflow_resolver.py`:
  - Module docstring strengthened with the boundary contract — explicit
    list of known IR-load boundaries (`resolve_workflow` for parent IR,
    `compiler.py` for sub-workflow children loaded by `WorkflowExecutor`,
    `validator.py` for child IR validation recursion). Future contributors
    who find themselves applying file resolution downstream are pointed at
    the contract.
  - New `_resolve_file_refs_at_boundary()` helper wraps
    `resolve_file_references` exceptions in `CompilationError` for
    consistency with the prior compiler-side wrapping (preserves the
    existing exception-handling shape downstream).
  - File resolution wired into `_try_load_from_file()` (file-path branch)
    and `_load_library_workflow()` (library branch, guarded on
    `path.exists()` so mocked-WorkflowManager test fixtures continue to
    work).

- `src/pflow/execution/result.py`:
  - `ResolvedWorkflow` docstring strengthened to lock the boundary
    contract. Lists what's resolved today (file references) and points
    at the architectural follow-up (#361) for future resolution steps
    (sub-workflow pre-compile per #334, output exposure rules per #321).

- `src/pflow/execution/runner.py`:
  - Deleted `_resolve_file_references()` method (~16 LOC).
  - Deleted 2 call sites (lines 173 and 317 — pre-fix). Both are now
    redundant with the boundary call.
  - Updated comments to reference the new contract.

- `runtime/compilation/compiler.py:570-581` — **kept**. Serves the only
  OTHER IR-load boundary: sub-workflow children loaded by
  `WorkflowExecutor`. Idempotent on already-resolved parent IR
  (already-inlined content has `is_file_reference == False`).

- `core/workflow/validator.py:784-789` — **kept**. Operates on freshly-
  loaded child IR during sub-workflow validation recursion. Different
  code path; out of Path 1 scope.

Tests added:

- `tests/test_execution/test_workflow_resolver_contract.py` — NEW, 4
  contract tests:
  - `test_resolve_workflow_returns_fully_file_resolved_ir` — the load-
    bearing structural defense. Walks every `FILE_RESOLVABLE_PARAMS`
    field in the IR and asserts none look like an unresolved file
    reference. Mutation-tested: reverting the fix makes this test fail
    with a clear diagnostic message that points future contributors at
    the contract docstring.
  - `test_resolve_workflow_skips_resolution_for_inline_dict_input` —
    confirms the dict-passthrough path (no file_path means no resolution
    anchor; correct).
  - `test_resolve_workflow_rejects_inline_dict_with_file_references` —
    confirms the existing defensive rejection (inline workflows with
    `./file.md` refs raise ValueError pre-resolution).
  - `test_resolve_workflow_raises_compilation_error_on_missing_file` —
    confirms exception type matches the prior compiler-side wrap so
    existing catch logic in runner.py / validate-path keeps working.

### Verification

- `make test`: **5,945 passing** (was 5,941; +4 contract tests, zero
  regressions).
- `make check` clean (ruff + ruff-format + mypy + deptry).
- `test_plan_drift.py` 34/34 green throughout.
- `test_golden_baseline_hashes_match` (DD#19) green.
- **Mutation-tested**: `git stash` the fix → contract test fails with the
  exact "If a consumer is calling resolve_file_references on this IR,
  that's the bug" diagnostic; `git stash pop` → passes.
- **Smoke test on lyrics-generator**:

  song-creator BEFORE Path 1:
  - `tokens=7` for write-lyrics (filename string char count)
  - 0 `cache.shared-context-undeclared` warnings
  - No suggested `## Cache` block

  song-creator AFTER Path 1:
  - `tokens=3289` for write-lyrics (real prompt size)
  - 4 `cache.shared-context-undeclared` warnings (matching the spec mode-1
    example: concept_brief, creative-direction.response,
    song-architecture.response, easter-eggs.response — sub-paths of
    concept also detected)
  - Suggested `## Cache` block with 7 chunks emitted, paste-ready
  - Per-node `prompt_cache:` assignments emitted for write-lyrics +
    song-architecture

  Other workflows: parent `lyrics-generator.pflow.md` curate-briefs node
  now reports `tokens=3869` (was 9); `evaluate-songs` reports `tokens=782`
  (was 6).

### Path 2 — tracked in #361

Three remaining items, each closing one of the related issues:

- **Item 2.1** — pre-compile sub-workflows at the boundary (closes #334)
- **Item 2.2** — bake output exposure rules into the resolved IR (closes
  #321 item A)
- **Item 2.3** — thread cycle-detection state once at the boundary
  (closes #321 item B)
- **Item 2.4** — extend the contract test for each new resolution step

The umbrella's framing: when all four items are done, #321 + #334 + this
issue close in lockstep. No new "consumer applies X" patterns added in the
meantime — enforced structurally by the contract test.

Estimated scope: ~280 LOC + ~10 tests, 1-2 days focused work.

### Secondary follow-up — tracked in #362

The `cache.cross-workflow-rename-detected` detector at
`core/cache_analysis/cross_workflow.py` floods false positives on real
workflows (23 warnings on lyrics-generator). Two suppression conditions
needed:

1. Suppress when parent value is a batch alias (`${item}` or `${item.X}`).
2. Suppress when neither parent nor child has a `## Cache` declaration
   (the warning's premise — diverging prose labels — is hypothetical
   without `## Cache` blocks to break).

~10-30 LOC + 3 tests. Orthogonal to Path 2 (different bug class:
detection logic, not architectural). Filed separately so an agent can
pick it up independently.

### Tacit knowledge for the next agent

1. **`ResolvedWorkflow.ir` is now fully file-resolved by contract.** Every
   downstream consumer can rely on this. If a future feature needs file
   resolution at a different point, do NOT add a `resolve_file_references`
   call locally — instead, extend the boundary in `resolve_workflow()` and
   the contract test catches the regression class structurally.

2. **Two other IR-load boundaries exist by design** and have their own
   resolution calls. They are NOT redundancy:
   - `runtime/compilation/compiler.py:570-581` resolves sub-workflow
     children loaded by `WorkflowExecutor`. Idempotent on resolved parent
     IR but load-bearing for child IR.
   - `core/workflow/validator.py:784-789` resolves child IR loaded fresh
     from disk during sub-workflow validation recursion.
   Both are documented in the `workflow_resolver.py` module docstring.

3. **The library-load path is guarded on `path.exists()`** because the
   mocked-WorkflowManager test isolation pattern (used widely in the test
   tree) returns IR via `wm.load_ir(name)` without a real file on disk.
   Calling `resolve_file_references` on a non-existent base directory
   would raise on the first `./file.md` reference — which would be a
   regression in test infrastructure.

4. **The contract test is the load-bearing structural defense.** It walks
   `FILE_RESOLVABLE_PARAMS` and asserts no `is_file_reference(value)`
   matches. If a future contributor introduces a new file-resolvable
   param type (e.g., `system: ./system.md`), they need to extend
   `FILE_RESOLVABLE_PARAMS` AND the contract test catches their work
   automatically.

5. **The `cache.dynamic-before-static` and `cache.padding-advisory`
   detections still don't fire on lyrics-generator** — separate issue
   that compounds with #362. The auto-batch-prefix detector also can't
   see prefixes assembled in Python code nodes (e.g.
   `chorus-chooser/score-choruses` builds its prompt via
   `build-scoring-items` Python code, then references via
   `${item.prompt}`). Path 1 didn't address this; tracked as part of
   the broader "real-workflow analyzer usefulness" work — file
   separately when an agent picks up Stage 2 verification.

6. **Stage 2 verification (real LLM runs) was deferred** until the
   analyzer produces useful output. Stage 1's free static analysis
   surfaced this finding before money was spent. The right next step
   is Stage 2: re-run `pflow analyze-cache` against the lyrics-generator
   workflows post-Path-1, identify the highest-leverage `## Cache`
   block to add (likely song-creator), then run song-creator standalone
   pre/post-cache to verify the value-prop ≥40% input-cost reduction.

### Open hedged claims and verifications still pending

- **VERIFIED**: Path 1 doesn't change runtime behavior — same end-state IR
  reaches the compiler/runner/engine. Confirmed by 5,945 tests passing
  including the planner-vs-runtime parity gate (`test_plan_drift.py`).
- **VERIFIED**: error-type contract preserved — `CompilationError` now
  raised at the boundary instead of the compiler. Existing catch logic
  in runner.py validate path (`except (..., CompilationError, ...)` at
  line 369) and run path (broad `except Exception` at line 145) handles
  it identically.
- **NEEDS VERIFICATION (Stage 2)**: real LLM run with `## Cache` declared
  on song-creator delivers the spec's locked ≥40% input-cost reduction.
  The analyzer correctly identifies the opportunity; Stage 2 verifies
  the cache rendering layer (Segments 2-3 of Task 159) actually delivers
  the savings on a real workflow.

### Open user decisions surfaced

**None.** Path 1 is an unambiguous architectural fix; the user pre-approved
the path during the planning conversation. The three follow-up items
(Path 2 + #362) are tracked as separate work.

---

## Stage 1 lyrics-generator verification: Tier 1 AG/UX fixes (2026-04-30)

User reframed: "do the issues we would need to fix regardless... There are no
v1.x issues right now, everything should be up on the table for the next
agent." So I shipped Tier 1 (the 4 issues that produce wrong/buried/incomplete
findings to agents on real workflows) and documented Tier 2 + Tier 3 + open
architectural questions for the next agent rather than filing them as v1.x
deferrals.

### What I implemented

Four Tier 1 issues fixed in this commit. Each has mutation-tested regression
gates.

**#362 — Cross-workflow rename detector evidence-basis suppression.**

Pre-fix: 23 false-positive `cache.cross-workflow-rename-detected` warnings on
lyrics-generator dominated the "Recommended actions" section. Two distinct
false-positive classes:

1. **Batch alias**: `${item}` and `${item.X}` are iteration-variable
   references, not stable renameable identifiers. Every batch sub-workflow
   invocation tripped this.
2. **No `## Cache` on either side**: rename's premise (diverging prose
   labels would break byte-level cache match) requires `## Cache` declared
   to be actionable. Without it, the warning fires hypothetically.

Fix shape — applied at emission, NOT at the walker (keeps `is_rename`
syntactic-pure). Added `parent_batch_alias: str | None` field to
`CrossWorkflowEdge`, populated by walker at `_process_one_call`. Added new
`is_batch_alias_root` property that detects when `parent_value_expr`'s root
segment matches the alias. In `analyze.py:_build_cross_workflow_findings`,
the rename emission gate now skips edges where `is_batch_alias_root` is True
OR neither side declares `## Cache`.

**Framed as "evidence-basis principle"** in code comments: predictive
warnings about state comparisons fire only when the state to compare against
exists. Top-10% codebases (mypy, rustc, clippy, ruff) all follow this — they
don't warn about hypothetical states. The user's framing during planning was
sharp on this point.

Files: `core/cache_analysis/cross_workflow.py`, `core/cache_analysis/analyze.py`,
+8 new tests in `test_cache_analysis_cross_workflow.py` (predicate + walker)
+5 new tests in `test_cache_analysis_per_id_emission.py` (end-to-end emission).

**#1 — Sort priority dict in `warning_catalog.py`.**

Pre-fix: `_build_recommended_actions` sort key was
`(-sev_weight, -savings, d.id or "")`. When two warnings shared severity AND
had no savings, alphabetical tie-break put `cache.cross-workflow-rename-
detected` (sorts earlier alphabetically) ahead of `cache.shared-context-
undeclared` (the actual high-value finding). On lyrics-generator, the 4
shared-context findings ended up at positions 18-21 below 17 noise warnings.

Fix shape: new `RECOMMENDED_ACTION_PRIORITY: dict[str, int]` constant in
`warning_catalog.py` (where catalog metadata lives — SSoT). Tier 1 actionable
IDs (shared-context-undeclared, dynamic-before-static, batch-prewarm-
recommended) priority 10; advisories priority 20; informational/alignment
priority 50. Sort key extends to `(-sev_weight, priority, -savings, d.id or "")`.

ERROR severity still wins over priority dimension — structural blockers
first. Unknown IDs default to 100 (lowest) for graceful degradation.

Files: `core/cache_analysis/warning_catalog.py` (new constants),
`core/cache_analysis/analyze.py` (sort key extension), +4 tests in
`test_cache_analysis_analyze.py`.

**#2 — Workflow-level scope rendering.**

Pre-fix: `cache.shared-context-undeclared` is emitted in two contexts —
workflow-level (analyze.py:766) with `node_id=None`, and per-node
(analyze.py:1078) with `node_id=parent_node_id`. Text renderer treated
`node_id=None` as "no scope line" — workflow-level findings rendered
identically to fully-unscoped ones, indistinguishable from per-node.

Fix shape: added `scope_workflow: str | None` field to `RecommendedAction`,
populated during `_build_recommended_actions` from
`context.affected_workflow` when `node_id is None`. Text renderer outputs
`Workflow: <basename>` when `scope_workflow` is set; basename stripping via
new `_short_workflow_label` helper (filesystem paths get basename;
`<inline>`, `ir-hash:*` pass through). JSON renderer exposes
`scope_workflow` field (additive to JSON shape — JSON consumers dispatch on
`(node_id, scope_workflow)` — at most one non-null).

Files: `core/cache_analysis/analyze.py` (RecommendedAction field +
population), `core/cache_analysis/render_text.py` (renderer +
_short_workflow_label), `core/cache_analysis/render_json.py` (JSON
exposure), +3 tests in `test_cache_analysis_renderers.py`.

**#10 — `_source_line` populated on nodes (parser fix).**

Pre-fix: cross-workflow output showed `(line 0)` for every boundary.
Investigation: `_source_line` was set only on outputs (and conditionally —
only when `source:` was present in YAML params). Workflow-type nodes never
had it populated, so the cross-workflow walker's `int(node.get("_source_line")
or 0)` always returned 0.

Fix shape: parser-level fix at `markdown_parser._build_node_dict`. Added
`node["_source_line"] = entity.heading_line` at the end of the function
(the `### node-id` heading is the natural anchor for "where in the file
this node lives"). Updated `ir_schema.py` to allow `_source_line` as a
node-level integer property.

Picked the parser fix over a render-time guard because it makes the field
universally available — future consumers (richer diagnostic rendering,
`pflow describe`-with-line-numbers, etc.) inherit accurate source-line
attribution for free. The `int(...) or 0` defensive read in cross_workflow.py
still works (now defensive-only).

Files: `core/markdown_parser.py`, `core/ir_schema.py`, +2 tests in
`test_markdown_parser.py` (`TestNodeSourceLine`).

### Verification

- `make test`: **5,967 passing** (was 5,945 before; +22 new Tier 1 tests,
  zero regressions).
- `make check` clean (ruff + ruff-format + mypy + deptry).
- `test_plan_drift.py` 34/34 green throughout.
- `test_golden_baseline_hashes_match` (DD#19) green.
- All 4 Tier 1 fixes mutation-tested. For each: `git stash` the production
  fix → the matching contract test fails with a clear diagnostic;
  `git stash pop` → passes.
- **End-to-end smoke on lyrics-generator** (`song-creator/song-creator.pflow.md`):

  Pre-Tier-1 (after Path 1 only):
  - 21 opportunities (17 false-positive renames + 4 actionable)
  - Recommendations buried at positions 18-21
  - Workflow-level finding rendered with no scope line
  - Cross-workflow output: `(line 0)` everywhere

  Post-Tier-1:
  - 4 opportunities (all actionable, all `cache.shared-context-undeclared`)
  - Recommendations sorted with shared-context-undeclared first
  - Workflow-level finding rendered as `Workflow: song-creator.pflow.md`
  - Real line numbers (e.g. `(line 49)`) in cross-workflow output

  The output is now agent-readable top-to-bottom without manual rework.

### Updated existing test fixture

`test_cache_analysis_per_id_coverage.py::test_emitted_diagnostics_round_trip_for_real_producer_paths`
relied on the old behavior where `cache.cross-workflow-rename-detected`
fires on greenfield (no `## Cache`). Updated the rename fixture to add
`## Cache` to the parent so the warning still fires under the new
suppression rules. Documented in the test's comments: "Per the
evidence-basis suppression (#362), the warning fires only when at least
one side declares ## Cache."

### Tacit knowledge for the next agent

1. **The evidence-basis principle generalizes.** When you add a new warning,
   ask: "is this predicting a future problem? what state makes the prediction
   actionable?" If the answer is "imagine the user adds X later," gate the
   warning on that state existing. Other catalog warnings I haven't audited
   may need similar gates.

2. **`parent_batch_alias` is on the edge, not derived at emission.** Set the
   pattern: pre-compute walker-time information on `CrossWorkflowEdge`
   fields so emission-time consumers don't re-walk the IR. Adding more such
   fields is straightforward; just populate in `_process_one_call`.

3. **Priority dict in `warning_catalog.py` is the SSoT for ordering.** Adding
   a new catalog ID requires a priority entry too — otherwise it falls back
   to `DEFAULT_RECOMMENDED_ACTION_PRIORITY` (100, lowest). The tiers
   (5/10/15/20/30/50) leave gaps for future IDs to slot in without
   renumbering.

4. **`RecommendedAction.scope_workflow` and `node_id` are mutually exclusive
   semantically.** At most one is set; both can be None for unscoped
   findings (rare). JSON consumers dispatch on the triple. Don't add a
   `scope` enum field — overengineering; the existing fields already encode
   the choice.

5. **`_source_line` is now consistently populated on nodes.** If you write
   code reading it, expect a populated `int`. The legacy
   `int(node.get("_source_line") or 0)` defensive read still works but the
   `or 0` fallback is now defensive-only.

6. **Mutation testing is the litmus for negative fixtures.** Every Tier 1
   test has a docstring explaining what removing the production fix would
   break. Follow the same pattern.

### Open hedged claims and verifications still pending

- **VERIFIED**: All 4 Tier 1 fixes don't break existing behavior. 5,967 tests
  pass; no regressions.
- **VERIFIED**: Cross-workflow walker correctly populates `parent_batch_alias`
  for batch + non-batch parent nodes. Both `as: <custom>` and default `"item"`
  cases tested.
- **VERIFIED**: Sort priority correctly resolves the original burying
  scenario. Mutation-tested.
- **VERIFIED**: Workflow-level scope renders with basename; full path NOT
  surfaced (compactness). Mutation-tested.
- **VERIFIED**: `_source_line` populated on workflow + shell + LLM nodes
  (TestNodeSourceLine).
- **NEEDS VERIFICATION (next agent's Stage 2 work)**: real LLM run with
  `## Cache` declared on song-creator delivers spec's locked ≥40% input-cost
  reduction. The analyzer correctly identifies the opportunity AND points
  to actionable findings; Stage 2 verifies the cache rendering layer
  (Segments 2-3 of Task 159) actually delivers the savings on a real
  workflow.

### Open user decisions surfaced

**None blocking.** Three architectural questions were SURFACED but explicitly
not filed as v1.x deferrals (per user reframe). All documented in
`agent-handoff-stage1-stage2.md`:

1. **Catalog redesign question**: should `cache.cross-workflow-rename-detected`
   fold into `cache.discrepancy`'s root_cause enum? Discussed during planning;
   tabled for next-agent decision because the Tier 1 #362 suppression makes
   the standalone warning behave correctly NOW, even if v1.x decides to
   redesign.

2. **Python-assembled prompts (#12)**: chorus-chooser's score-choruses (the
   spec mode-1 canonical prewarm test) has its prompt assembled in Python
   code. Static analyzer can't see it. Three directions documented (document-
   as-limitation, run-once detection, AST analysis); recommendation is
   document-as-limitation for v1, run-once detection for v1.x.

3. **Path 2 architectural cleanup (#361)**: extends the boundary contract
   to close #321 + #334 in lockstep. ~280 LOC + ~10 tests, 1-2 days.
   Tracked as separate issue. NOT blocking Stage 2 — but consider tackling
   before merging if user wants the architectural slice complete.

### Lessons worth surfacing

1. **"File as v1.x" is a tactical convenience that ships broken UX.** My
   first-draft plan filed cross-workflow rename suppression as a separate
   GH issue. User correctly pushed back: "this branch needs to be working,
   we cant defer things that SHOULD be working." Top-10% codebases ship
   coherent v1s, not "shipped + tracked brokenness." Tier 1 framing
   ("regardless" = "what's actually broken") is the right bar.

2. **The smart-colleague handoff doc pattern works.** I followed the
   existing `recommendations-section-handoff.md` shape — what's in this PR,
   current state, what's left, decisions on the table, tacit knowledge,
   quick-start commands. Kept context dense without requiring the next
   agent to re-derive everything.

3. **Mutation testing forces honest contracts.** Every Tier 1 fix has a
   regression gate that fails when the fix is reverted. This is more useful
   than just "test passes after fix" — it proves the test ACTUALLY guards
   the regression class. Worth doing for every fix in this branch.

---

## Stage 1 CP5 — agent-UX message clarity pass (2026-04-30)

After Tier 1 landed, the user audited the rendered output as a cold reader
and surfaced six specific UX issues (catalog message opacity, grammar bug,
Cross-workflow-section confusion, Python-repr per-node assignments,
workflow-vs-boundary ambiguity, terse header). These aren't structural bugs —
the data flow is correct — but the rendered text was assuming prior knowledge
agents don't have. CP5 is a focused message-clarity pass across `warning_catalog.py`
and `render_text.py`, no logic changes.

### What I implemented

Three commits-worth of work shipped as one CP5 (no commits yet — user controls).

**Pass 1 — catalog message clarity + grammar fix + workflow/boundary disambiguation:**

- `core/cache_analysis/warning_catalog.py`:
  - New `_format_savings_clause` helper that returns `" (saves $X.XX/run)"` or
    empty string. Mirrors the tri-state contract — None/sub-cent → silent,
    real value → rendered. Closes the "saves savings unavailable/run"
    grammar bug at the format-level.
  - New `savings_clause` typed alias in `make_diagnostic` format_dict
    (alongside the existing `savings_str`). Templates that want the
    parenthetical form switch to `{savings_clause}`.
  - Two new module-level templates: `_SHARED_CONTEXT_WORKFLOW_TEMPLATE`
    (workflow-internal sharing) and `_SHARED_CONTEXT_BOUNDARY_TEMPLATE`
    (cross-workflow value flow). Each has its own remediation prose because
    the fixes differ (one workflow's ## Cache vs either side of the boundary).
  - Dispatch added to `make_diagnostic`: when ``warning_id ==
    "cache.shared-context-undeclared"`` AND ``child_workflow`` is in context,
    select the boundary template + compute ``child_workflow_basename`` for
    the message. Mirrors the ``cache.discrepancy`` dispatch precedent.
  - Updated `cache.padding-advisory` and `cache.batch-prewarm-recommended`
    templates to use `{savings_clause}` (eliminating the same grammar bug).
  - Module docstring count: 12 → 13 (catches up with consolidate-to-root from CP3).

- `core/cache_analysis/analyze.py`:
  - `_cross_workflow_value_flow_opportunity` now passes `child_workflow=edge.child_workflow`
    so the boundary dispatch fires.
  - `RecommendedAction` extended with `message: str = ""` field. Populated
    from `d.message` in `_build_recommended_actions`.
  - **The load-bearing fix for issue #5**: pre-CP5 the recommended-actions
    section showed only ID + savings + scope, not the diagnostic message.
    Four `[cache.shared-context-undeclared]` findings looked byte-identical
    except for scope label. Adding `message` to the dataclass + showing it
    below scope makes each recommendation self-explanatory.

- `core/cache_analysis/render_text.py`:
  - `_render_recommended_actions` now appends the diagnostic's message
    (indented under the rank line) so each finding tells the agent what it
    is about without scrolling.

**Pass 2 — cross-workflow section rewrite (Issue #3):**

- `core/cache_analysis/render_text.py`:
  - Section renamed `## Cross-workflow alignment (Tier 2)` → `## Sub-workflow
    boundaries`. The "Tier 2" parenthetical was internal pflow architecture
    jargon agents shouldn't have to learn.
  - Added section preamble explaining what the findings ARE (values flowing
    across sub-workflow boundaries that could be cached on either side).
  - Three new finding-type renderers:
    `_format_value_flow_finding`, `_format_rename_finding`,
    `_format_prose_mismatch_finding`. Each renders a 4-line block:
    boundary header (`parent → child  (via <node>)` or `(line N)`) /
    what-was-detected / `→ <action>` / `[<id>]` at the bottom.
  - Each finding pulls structured data from `diag.context` directly,
    bypassing the catalog message text — the section has more space than
    the recommendations bullet so it can be more verbose without being
    cryptic.
  - New `_workflow_short_name(path)` helper strips `/abs/path/`
    + `.pflow.md` for compactness. `<inline>` and `ir-hash:*` pass through
    unchanged.
  - Findings ordered by leverage: value-flow first (highest impact —
    unlocks new caching), rename + prose-mismatch after (alignment fixes).

**Pass 3 — per-node `.pflow.md` syntax + header phrasing (Issues #4, #6):**

- `core/cache_analysis/render_text.py`:
  - `_render_suggested_blocks` per-node section now renders actual
    `.pflow.md` syntax (`### node-id\n- prompt_cache: [a, b, c]`) instead
    of Python repr. Includes a brief explainer about the strict order
    requirement (with explicit reference to `cache.order-mismatch` ERROR).
  - New `_format_scale_line` helper renders the header scale line with
    actual model names. Four cases: 0 LLM nodes / 1 model / 2+ models /
    LLM nodes but no model resolved (with actionable `set
    settings.default_model` hint).
  - Header drops the `· models in use` count phrasing — model names appear
    inline now.

### Files modified summary

Production: `warning_catalog.py` (~80 LOC across helpers + templates +
dispatch), `analyze.py` (~10 LOC for child_workflow + RecommendedAction
message), `render_text.py` (~150 LOC for cross-workflow rewrite + per-node
syntax + header).

Tests: `test_cache_analysis_renderers.py` (3 old CP2 tests rewritten for new
multi-line format, 11 new behavioral tests added — covering the section
header rename, distinguishability invariant, action-line presence, full
4-line format for each finding type, per-node syntax shape, header model
listing modes including 1/2+/no-model branches).

### Final state

- 6,000 tests passing (was 5,992 → +8 net new after replacing 3 CP2 tests
  with 5 broader-shape tests)
- `make check` clean (ruff + ruff-format + mypy + deptry)
- `test_plan_drift.py` 34/34 green
- `test_golden_baseline_hashes_match` green

### Tacit knowledge for the next agent

1. **The `child_workflow` context key is the dispatch trigger** for
   `cache.shared-context-undeclared`. When `child_workflow in context_kwargs`,
   `make_diagnostic` swaps in the boundary template. Workflow-scope
   emission (`_populate_suggested_blocks`) does NOT set this key — that's
   how the workflow-scope template is selected. Future contributors adding
   new emission sites for this ID need to decide which scope they're in.

2. **`savings_clause` vs `savings_str`** — both typed aliases exist in
   `make_diagnostic` format_dict. Templates wanting the bare amount
   (`-$0.45`) use `savings_str`. Templates wanting the parenthetical form
   `(saves $0.45/run)` (or empty when None/sub-cent) use `savings_clause`.
   The savings_str form still renders "savings unavailable" for None — DON'T
   embed it in `(saves {savings_str}/run)` or the grammar bug returns.

3. **Cross-workflow renderer pulls from `diag.context`, NOT `diag.message`.**
   The catalog message for `cache.shared-context-undeclared` is rich for
   recommendations + JSON, but it duplicates info that the
   `parent → child` header already shows in the cross-workflow section.
   Each finding-type renderer reaches into context directly. If a future
   contributor adds a new cross-workflow finding type, they need to add a
   new rendering helper alongside the three existing ones.

4. **Recommendations section now shows messages.** Pre-CP5 it was just
   ID + savings + scope. Adding the message field made each recommendation
   self-explanatory. The trade-off: long messages wrap in narrow terminals.
   Acceptable trade for "agent reads top-to-bottom and acts" usability.

5. **The two CP3 stub paths still apply post-CP5.**
   `cache.consolidate-to-root-recommended` still doesn't fire pre-run on
   greenfield (memo data needed for accurate root_tokens). And the
   workflow-level `cache.shared-context-undeclared` finding includes the
   FULL chunk list in its csv (~150 chars on lyrics-generator) which
   wraps awkwardly in the recommendations bullet. Both are quality-of-life
   nits, not blockers.

### Open hedged claims and verifications still pending

- **VERIFIED**: all CP5 changes are text-only — zero logic regression risk.
  `test_plan_drift.py` (34/34) and `test_golden_baseline_hashes_match`
  passed throughout.
- **VERIFIED**: brownfield safety — ERRORs (`cache.order-mismatch`) still
  surface prominently in Recommended Actions on the brownfield smoke
  fixture. Confirmed via `POST-CP5-BROWNFIELD.txt` in scratchpads.
- **VERIFIED**: dispatch path tested end-to-end through real
  `_cross_workflow_value_flow_opportunity` emission on lyrics-generator
  (boundary template fires with sub-workflow names rendered correctly).

### Open user decisions surfaced (for next agent)

The user reviewed the post-CP5 output and flagged two issues that were NOT
fixed in this pass:

**Concern A — `[cache.shared-context-undeclared]` still surfaces visibly.**
Even after the message clarity work, the bracketed ID appears prominently
in both Recommended Actions and Sub-workflow boundaries. The user feels
this is still opaque — agents shouldn't need to look up what the ID means.
Possible directions (not designed yet):

- Drop the brackets entirely from the rendered text; keep the ID in JSON
  for machine consumption.
- Replace with a short human-readable category prefix
  (e.g. `[shared context]` instead of `[cache.shared-context-undeclared]`).
- Move the ID to a less prominent position (e.g. parenthetical at the
  end of the action line).

This is a real call about the discoverability/agent-readability tradeoff;
spec DD#27 establishes that stable IDs are first-class for filtering, but
that's about the structured surface (JSON / `Diagnostic.id`), not the
rendered text. Worth surfacing to the user before committing to a shape.

**Concern B — `cacheable=0 ratio=0%` in per-call report unexplained.**
The per-call section header says "Current ratios (always 0% pre-cache; see
Recommended actions for the recoverable opportunities.)". The header
explainer addresses the ratio column. But the `cacheable=0` column has no
explainer — agents reading the table don't know what "cacheable" means
in greenfield (where it's always 0 because no `prompt_cache:` is declared).
Possible directions:

- Add column-header annotations or replace `cacheable=0` with `cacheable=—`
  in greenfield mode.
- Drop the cacheable column from greenfield rendering (always 0 anyway).
- Add a one-line explainer near the table about what each column means.

The `cacheable_tokens_estimated` field IS valuable in steady-state mode
where it reflects actual declared-subset coverage. The greenfield mode is
where the column gets confusing. Branch on `is_steady_state` (the same
detection used for the section header) and render greenfield rows
without the cacheable column, OR with `cacheable=—`.

### Code-review findings worth carrying forward

1. **Catalog opacity audit pattern.** The user's "what does this mean to
   an agent?" lens is structurally repeatable. For every catalog template,
   ask: "does this answer what / why / how-to-fix in plain language?" If
   any of those three is missing, the template needs work. The existing
   templates I rewrote in CP5 (shared-context-undeclared, padding-advisory,
   batch-prewarm-recommended suggestions) all failed the test in different
   ways. The remaining 9 templates passed my audit but the next agent
   should re-audit when they touch this code.

2. **Multi-line per-finding format scales the available space.** Single-line
   bullets force compression that hides discriminator data. The "Sub-workflow
   boundaries" rewrite shows that giving each finding 4 lines makes the
   data agent-readable without bloating the output. Worth applying to
   other sections that compress aggressively (e.g. recommendations could
   benefit similarly when the message is long).

3. **Renderer-side data extraction beats catalog-message-only rendering**
   when the section header already provides context. The cross-workflow
   section's `parent → child` header makes the catalog message ("flows
   from this workflow into sub-workflow X") redundant. Pulling from
   `diag.context` directly avoids the duplication.

---

## Stage-1 final UX pass — Concerns A + B + Option C (2026-05-01)

After CP5 the user reviewed the output and flagged two remaining nits
(Concerns A + B), then a third (Option C) emerged from analyzing the
greenfield output's per-call section honestly. All three shipped as one
coherent agent-readability pass.

### Concern A — drop bracketed `[cache.X]` IDs from text rendering

**Was**: every rank line in Recommended Actions and every cross-workflow
finding had a `[cache.shared-context-undeclared]`-style bracket prefix
mimicking rustc/mypy error codes. pflow's IDs aren't error codes — they're
long namespaced category descriptors. Bracketing visually coded them as
codes when they're actually descriptions.

**Top-10% lens**: mypy default hides codes; ruff/rustc use SHORT codes;
none bracket long namespaced descriptors. The brackets added noise
without value for non-ERROR diagnostics.

**Fix**: dropped `[cache.X]` brackets from `render_text.py` at 4 sites
(rec rank line + 3 cross-workflow finding footers); stripped the `cache.`
prefix from per-call inline notes column (`dynamic-before-static` instead
of `[cache.dynamic-before-static]`); deleted the dead `_render_warnings`
function entirely. The `diagnostic_render.py` ERROR title bracket
(`Error: Cache Failure [cache.invalid-on-non-llm]`) is unchanged — that
surface keeps the agent-routing handle for hard errors.

**Headlines via catalog SSoT**: added `headline_template` field to
`CacheWarningSpec` (per-id action-led title, `"<category> — <action>"`
pattern). Each rank line now leads with the headline (e.g., `"Shared
context undeclared — declare \`concept\` in ## Cache"`); the descriptive
message goes below as the reason paragraph. Recommendations restructured
from `[id]` + scope label + message to action-headline + plain scope +
reason paragraph.

**`resolve_headline_for(diag)` helper** in `warning_catalog.py` is the
SSoT for headline lookup. Works for diagnostics built via `make_diagnostic`
AND directly via `Diagnostic(...)` (validator emitters in `data_flow.py`
— `_make_order_mismatch_diagnostic` etc.). Closed the structural gap the
post-implementation test-writer-fixer flagged: validator-emitted ERROR
diagnostics now get their catalog headlines through analyze-cache rendering.

### Concern B — greenfield `cacheable_tokens_estimated` populates from suggested-blocks pass

**Was**: pre-fix `_estimate_cacheable_tokens` returned 0 for any node
without a declared subset. Greenfield rows always showed `cacheable=0
ratio=0%` even when shared context was detected — the per-call section
was useless in the dominant authoring scenario.

**Fix**: `_populate_suggested_blocks` already computed per-chunk token
sizes (via `_estimate_ref_tokens` against memo data) and per-node
assignments — but threw the data away. Refactored to also return
`cacheable_by_node: dict[str, int | None]`. `analyze()` enriches greenfield
per-call rows via new `_enrich_with_projected_cacheable` helper using
`dataclasses.replace` (PerCallRow stays frozen).

**JSON_FORMAT_VERSION 1.0 → 1.1**: semantic shift on
`per_call[].cacheable_tokens_estimated` (was always 0 in greenfield;
now projected from detected shared context when memo populated, `null`
when not). Field shapes unchanged; consumer rule
(`startswith("1.")`) holds.

### Option C — hide per-call rows without real data

**The deeper issue**: even after Concern B landed, lyrics-generator
song-creator showed `cacheable=38 ratio=1%` on greenfield write-lyrics
(3289 input tokens). The numbers were technically computed (sum of
literal-`${ref}` token counts via fallback) but practically misleading
— agents skimming would think "tiny opportunity" when actually it was
unmeasured.

**The user's sharper observation**: even the `tokens` column is
misleading in greenfield. `tokens=3289` represents the prompt TEMPLATE
size (with `${var}` references counted as ~5-token literals), NOT the
actual runtime size after substitution. With memo data, `estimate_tokens`
returns real runtime tokens (post-substitution). Without memo, it
tokenizes the template with `${var}` as literals → wrong number with
authoritative-looking `src=medium` confidence label. Both columns lie
in pure greenfield.

**Top-10% answer — distinguish data from no-data**: same tri-state
contract as cost (None ≠ 0). Option C visibility rule:

```python
def _row_has_real_data(row: PerCallRow) -> bool:
    return row.data_source in {"trace", "memo"} or bool(row.declared_prompt_cache)
```

A row passes iff input_tokens reflects actual runtime size (memo/trace)
OR steady-state with a declared subset. Pure-greenfield-no-memo rows
fail both → hidden. When ALL rows fail → entire `## Per-call cache
report` section hidden, with a Notes entry: "Per-call cache report
hidden — workflow has no run data yet. Run once to populate memo cache;
analyze-cache then shows real per-node token estimates and cacheable
projections."

**Implementation**:

- `_estimate_ref_tokens` returns `int | None` (memo miss → `None`
  instead of the prior ~3-5 token literal-`${ref}` fallback).
- `cacheable_by_node: dict[str, int | None]` propagates None per-node.
- `PerCallRow.cacheable_tokens_estimated: int | None`,
  `cache_ratio_pct: int | None`.
- `_consolidate_to_root_advisories` got an explicit None-check
  (replacing implicit suppression-via-tiny-numbers — now that
  `_estimate_ref_tokens` returns None on memo miss).
- Renderer: filter rows by `_row_has_real_data`, hide section when
  filtered set is empty, render `cacheable=?` / `ratio=?%` for None
  values that survive the filter (mixed-state rows).
- `cost_estimation.py` treats None as 0 at five sites (greenfield-no-memo
  → savings naturally compute to 0 — honest "we don't know").

### Files modified (total Stage-1 final pass)

Production:
- `src/pflow/core/cache_analysis/warning_catalog.py` — `headline_template`
  field on CacheWarningSpec, headlines for all 13 IDs, dispatched
  workflow/boundary headlines for shared-context-undeclared,
  `resolve_headline_for` SSoT helper, `_format_chunks_short` for compact
  list rendering. (~85 LOC)
- `src/pflow/core/cache_analysis/analyze.py` — `RecommendedAction.headline`
  field, `_populate_suggested_blocks` 3-tuple return shape with
  `cacheable_by_node`, `_enrich_with_projected_cacheable` helper,
  `_estimate_ref_tokens` returns `int | None`, `_row_has_real_data_in_analyze`
  helper, `_check_root_for_consolidation` explicit None-check, summary
  aggregation handles None, Notes entry when section hidden. (~90 LOC)
- `src/pflow/core/cache_analysis/render_text.py` — restructured
  `_render_recommended_actions` (action-headline + scope + reason),
  collapsed three `_format_*_finding` helpers into one
  `_format_boundary_finding` (numbered shape, no bullet/arrow/`[id]`
  footer), per-call inline notes strips `cache.` prefix, removed
  dead `_render_warnings`, two-mode scope explainer (steady-state +
  post-run greenfield), `_row_has_real_data` filter, nullable
  cacheable/ratio rendering. (~60 LOC net)
- `src/pflow/core/cache_analysis/render_json.py` — JSON_FORMAT_VERSION
  bumped 1.0 → 1.1 with semantic-shift documentation in module
  docstring. (+10 LOC)
- `src/pflow/core/cache_analysis/cost_estimation.py` — None-as-0
  normalization at five cacheable-read sites. (+10 LOC)

Tests:
- `tests/test_core/test_cache_analysis_renderers.py` — 12+ fixture
  updates: bracket assertions removed, headline assertions added,
  section-hidden assertions for pure-greenfield, `_row` fixture default
  switched to `data_source="memo"` so existing per-call tests survive
  the Option C filter.
- `tests/test_core/test_cache_analysis_per_id_coverage.py` —
  `JSON_FORMAT_VERSION` literal bumped to "1.1".

### Verification

- **6,001 tests passing**, 9 skipped
- `make check` clean: ruff + ruff-format + mypy + deptry
- `test_plan_drift.py` 34/34
- `test_golden_baseline_hashes_match` (DD#19) green
- 4 lyrics-generator targets re-rendered + brownfield smoke test;
  snapshots saved as `scratchpads/lyrics-generator-stage1/POST-STAGE1-FINAL-*.txt`
- Brownfield ERROR case (`cache.order-mismatch`) verified rendering
  the new headline shape (`prompt_cache:` order mismatch on write-lyrics)

### Tacit knowledge for the next agent

1. **Catalog-as-SSoT for rendering policy.** When the renderer needs a
   per-id presentation field (headline today, possibly icons / colors /
   sort priorities later), put it on `CacheWarningSpec` and access via
   a helper like `resolve_headline_for`. Don't write context keys in
   `make_diagnostic` and read them back at render time — that breaks for
   diagnostics built via raw `Diagnostic(...)` outside the helper.

2. **`_row_has_real_data` is duplicated in `analyze.py` and
   `render_text.py`.** Both must stay byte-equivalent. Explicit comment
   at each site documents the layer policy (analyze.py shouldn't import
   from render_text.py). If a third predicate is needed in the future,
   consider moving the helper to a neutral module (`utils.py` in the
   same package) — but the duplication cost is ~3 LOC, not worth a
   refactor today.

3. **Option C's tri-state is honest about a fundamental limit.** The
   analyzer can't project cacheable values for greenfield workflows
   without memo data — `${var}` reference sizes depend on runtime
   resolution. Hiding the row is more useful than fabricating a small
   number. After the first run populates memo, the section becomes
   high-fidelity for the same workflow — predictable state transition
   the agent can rely on.

4. **JSON 1.1 bump is the first non-additive minor.** The field shapes
   are additive (cacheable/ratio became `int | null`), but the SEMANTIC
   of `cacheable_tokens_estimated` changed: was always 0 in greenfield,
   now projects from detected shared context when memo data exists.
   Documented in `render_json.py`'s `JSON_FORMAT_VERSION` docstring.
   Future minor bumps should follow the same pattern: add a
   version-history block in the docstring, document semantic shifts.

5. **GH #363 — shared prose detection (v1.x)** complements the existing
   `${var}` detection. Currently agents who repeat persona/output-format
   prose verbatim across multiple prompts get no caching suggestion. The
   issue outlines an n-gram / longest-common-substring algorithm that
   would catch this case. Filed as v1.x with detailed acceptance
   criteria.

### Open hedged claims and verifications still pending

- **VERIFIED**: end-to-end on lyrics-generator song-creator (greenfield)
  — per-call section hidden, Notes entry surfaced, recommendations
  use action-headlines, suggested ## Cache block intact, sub-workflow
  boundaries renumbered with new shape.
- **VERIFIED**: brownfield (steady-state) — per-call section visible,
  headlines render for ERROR-severity diagnostics from `data_flow.py`
  (resolve_headline_for SSoT works for both make_diagnostic and direct
  Diagnostic(...) construction).
- **NEEDS VERIFICATION (Stage 2)**: real-LLM run with `## Cache` declared
  delivers spec's locked ≥40% input-cost reduction. Stage-1 polish is
  done; Stage 2 (real spend) is the next gate.

### Open user decisions surfaced

**None new.** Stage-1 polish is complete; agent-readability bar set per
"as usable as possible in v1" framing. Stage 2 verification is the next
major item; architectural concerns (Path 2 #361, catalog redesign,
Python-assembled prompts) remain documented in
`agent-handoff-stage1-stage2.md` for future decisions.

---

## Stage 1.5 — `cache.opaque-prompt` catalog ID + lyrics-generator refactor (2026-05-01)

User asked to address the Concern-2 gap (Python-assembled prompts invisible to
static analysis) before Stage 2. Reframed during planning: run-once detection
was over-engineered. The right shape is detect + nudge — point the agent at
the refactor when the pattern is visible, accept the limit when it isn't.

### What I implemented

**14th catalog ID `cache.opaque-prompt`** (DD#29 user-approved, 13 → 14).
Severity info, category cache_advisory, priority 30. Detector covers two
patterns at the existing `_per_node_warnings` site:
- **Direct**: `prompt: ${some_code.result.field}` where `some_code` is `type: code`.
- **Batch alias**: `prompt: ${item.X}` AND `batch.items: ${some_code.result}`.

Plumbing: `_build_per_call_rows_and_warnings` builds `nodes_by_id` once and
threads it through `_per_node_warnings(..., nodes_by_id=)` (kwarg-only).
Coalesce expressions (`${a ?? b}`) skipped — semantics don't fit the
"opaque passthrough" framing.

**Files changed (production, 4):**
- `core/cache_analysis/warning_catalog.py` — catalog row + priority entry + docstring count
- `core/cache_analysis/analyze.py` — `_opaque_prompt_warnings` + `_resolve_through_batch_alias` helpers + `nodes_by_id` plumbing
- `guide/features/caching.md` — new "Python-Assembled Prompts" section (general instructions, no workflow-specific names) + catalog table row
- `mcp_server/tools/execution_tools.py` — docstring catalog list 13 → 14

**Tests (3 files):** 5 emission tests in `test_cache_analysis_per_id_emission.py`
(direct, batch-alias, 3 negatives — mutation-test verified for the
`is_simple_template` gate); `_kwargs_for` + production-driven round-trip in
`test_cache_analysis_per_id_coverage.py`; `_minimal_context_kwargs` +
`assert len == 14` in `test_cache_analysis_warnings.py`.

**Lyrics-generator refactor (in-place per user direction):**
- `chorus-chooser/score-chorus.prompt.md` — NEW. Full ~1.6k-token rubric;
  `${item.chorus_text}` at the END (canonical spec mode-1 fix).
- `chorus-chooser/chorus-chooser.pflow.md` — `build-scoring-items` now
  produces `{items, genre_only, narrator_info}` (no inline prompt assembly);
  `score-choruses` uses `prompt: ./score-chorus.prompt.md` (matches the
  existing `select-chorus.prompt.md` pattern in this directory).

### Verification

- 6007 tests passing (was 6001 + 6 new); `make check` clean.
- Mutation-tested: removing `is_simple_template` gate causes the negative
  test to fail with a clear false positive. Gate is load-bearing.
- 4 high-leverage manual fixtures at `/tmp/opaque-regression/0[1-4]-*.pflow.md`:
  direct-opaque (positive), batch-alias-opaque (canonical), inline-shared
  (false-positive guard), brownfield-mixed (new detector + `cache.below-min-tokens`
  co-fire). All emit expected IDs.
- song-creator regression diff vs `POST-STAGE1-FINAL-song-creator.txt`:
  identical (1 trailing newline, cosmetic).
- JSON shape: `id` at top level, structured `context` with `var_ref` +
  `upstream_node_id`, `format_version` unchanged at 1.1.

### Lyrics-generator analyzer behavior post-refactor

`pflow analyze-cache chorus-chooser.pflow.md`:
- `cache.opaque-prompt` does NOT fire on `score-choruses` ✓ (refactor unblocked detection)
- `cache.opaque-prompt` correctly fires on `generate-chorus-options` (Case B
  — random shuffles + per-item dynamic group sizes; genuinely uncacheable)
- `cache.shared-context-undeclared` now detects `concept.core_idea` shared
  between `score-choruses` and `select-chorus` (was invisible pre-refactor)

`cache.batch-prewarm-recommended` doesn't fire because `batch.items` is
template-resolved (`${build-scoring-items.result.items}`) and static batch-size
inference doesn't follow templates — that's the pre-existing GH #360 limit.

### Tacit knowledge for the next agent

1. **Multi-line YAML `prompt: |` is not safe in `.pflow.md`.** The parser's
   `_parse_yaml_items` drops content after the first blank line in the
   scalar AND can confuse the section state machine when the scalar contains
   `## Heading`-shaped lines. Use either single-line quoted strings (`prompt:
   "first\n\n${var}"`) or external file refs (`prompt: ./file.prompt.md`).
   The latter is the established pattern in lyrics-generator and is what
   `score-choruses` now uses; Path 1's file-resolution boundary contract
   substitutes the file content into the IR before the analyzer walks it.

2. **`is_simple_template` is the load-bearing gate** in `_opaque_prompt_warnings`.
   Without it, prompts shaped `${X} trailing literal text` produce false
   positives because `extract_root_node_id` recovers a real node id from the
   malformed inner string. The original test fixture (with leading literal +
   `${X}`) doesn't actually exercise this — the malformed extraction breaks
   downstream. Updated the negative test to use the leading-`${X}` shape so
   the mutation-test is real.

3. **The refactor pattern documented in the guide** (general terms,
   `prepare-items`/`process-items` placeholder names, no workflow-specific
   references). When in-workflow detection of Python-assembled prompts
   matters, the agent gets pointed at `pflow guide caching` →
   "Python-Assembled Prompts" via the diagnostic's `suggestions` field.

### Open hedged claims

- **VERIFIED**: regression-clean on song-creator (existing fixture); 4 manual
  fixtures match expectations; mutation tests guard the load-bearing gates.
- **NEEDS VERIFICATION (Stage 2)**: real-LLM run on `chorus-chooser` standalone
  with manually-added `## Cache` declaring `concept.core_idea` should produce
  measurable savings. This was Stage 2.2's purpose.

### Open user decisions surfaced

**None new.** Concern 1 (rename → discrepancy fold) deferred per low criticality.
Concern 2 was resolved by Stage 1.5. Stage 2 (real-LLM verification) is the next
gate.

---

## Stage A + Stage 0 — analyze-cache UX text fixes + data-model redesign (2026-05-01)

After Stage 1.5 the user surfaced 4 agent-readability concerns on the
lyrics-generator song-creator snapshot (sub-workflow boundaries triple
repetition, opaque `<DESCRIBE...>` placeholder, redundant recommended
actions, "memo cache or 2.1.0 trace" pflow internals). Plan-mode review with
8 subagents traced all four to one architectural smell: the analyzer
pre-computes views (`recommended_actions`, `cross_workflow.{rename,prose,value_flow}`)
that duplicate findings already in `warnings`. Stage 0 collapses the
duplication; Stages A+B+C polish on top.

This entry covers Stages A + 0; B + C are pending. Plan file at
`/Users/andfal/.claude/plans/yes-lets-write-the-streamed-turing.md`.

### Stage A — text-only UX fixes (committed earlier this session)

- `analyze.py:1028` placeholder rewritten: `<DESCRIBE X — appears verbatim
  in cached system prefix>` → `<TODO: describe X for the LLM (1-2 sentences)>`.
  Per-agent-ux review Finding 3: "for the LLM" closes the audience-cue gap
  (agents skimming TODOs without the block intro could write internal-facing
  prose).
- `render_text._render_suggested_blocks` adds block-level intro above the
  cache code fence (markdown, not parsed as cache content): explains the
  TODO-replacement task + LLM-reads-this-prose-immediately + concrete prose
  example. Bounded cache pollution if not filled in.
- `_render_summary` greenfield-cost note: "memo cache or a 2.1.0 trace"
  pflow-internals leak replaced with "real cost figures and cacheable
  projections" symmetric to the parallel Notes string.

### Stage 0 — data-model redesign (committing now)

**Files modified (production):**
- **NEW** `src/pflow/core/cache_analysis/view_helpers.py` — relocated
  `_build_recommended_actions` (renamed `build_recommended_actions`).
  `_CROSS_WORKFLOW_ALIGNMENT_IDS = frozenset({"cache.cross-workflow-rename-detected",
  "cache.cross-workflow-prose-mismatch"})` filter ensures cross-workflow
  alignment findings render in EXACTLY ONE section (Sub-workflow boundaries),
  not in both (the latent duplication that was dormant on lyrics-generator
  but would re-appear the moment a workflow had divergent prose labels).
- `analyze.py` — drop `recommended_actions` field from `CacheAnalysis`; drop
  three Diagnostic tuples from `CrossWorkflowFindings` (keep
  `boundaries_analyzed: int` only); drop `PerCallRow.warnings`. Keep
  `_build_recommended_actions` as a 5-line shim that delegates to
  `view_helpers.build_recommended_actions` (preserves the 4 algorithm tests
  at `test_cache_analysis_analyze.py:670-734` via import-line edits only).
  `_build_cross_workflow_findings` returns `(graph_info, findings)` tuple;
  caller does `warnings.extend(cross_diagnostics)`.
- `render_text.py` — `_render_recommended_actions` calls
  `build_recommended_actions(list(analysis.warnings))` on demand.
  `_render_cross_workflow` filters `analysis.warnings` by `Diagnostic.id`
  for rename + prose-mismatch; value-flow findings (boundary-scope
  `cache.shared-context-undeclared`) are NOT rendered here (per Stage B.3
  Option d Mix). `_is_row_visible_by_default` drops the dead `row.warnings`
  fallback.
- `render_json.py` — `JSON_FORMAT_VERSION` 1.1 → 2.0; `_MAJOR` 1 → 2.
  `recommended_actions` and `cross_workflow.*` arrays computed on demand by
  filtering `analysis.warnings`. `per_call[].warnings` key dropped.
  Version-history block extended with full Stage 0 changelog (semantic
  changes documented for JSON consumers).
- `__init__.py` and `mcp_server/services/execution_service.py:383-386`
  docstrings updated 1.x → 2.x (CLI/MCP parity per Task 152).
- `mcp_server/tools/execution_tools.py:374-378` — version policy +
  Stage-0-shape-changes documented.

**Tests updated (one logical change per stage):**
- 5 renderer tests rewritten from synthetic `RecommendedAction` tuples →
  `make_diagnostic(...)` warnings (production code path; Pitfall #19
  defense). The test that exercised the dead `row.warnings` fallback at
  line 202 was deleted (sibling at line 209 covers production-shape
  contract).
- New regression test `test_recommended_actions_filters_cross_workflow_alignment_ids`
  (mutation contract: removing `_CROSS_WORKFLOW_ALIGNMENT_IDS` filter
  causes rename + prose findings to leak into Recommended actions).
- Test at `test_cache_analysis_analyze.py:670` rewritten to use
  `cache.unused-chunk` (priority 30) vs `cache.shared-context-undeclared`
  (priority 10) for the priority-sort contract — old version used
  `cache.cross-workflow-rename-detected` which is now filtered out.
- Hardcoded `JSON_FORMAT_VERSION == "1.1"` pin at
  `test_cache_analysis_per_id_coverage.py:216` updated to `"2.0"`.
- MCP docstring assertion at `test_analyze_cache_tool.py:182` tightened
  from `"1.x" in doc or "1.0" in doc` (OR-shaped — passes on partial
  reverts) to single `"2.x" in doc`.
- `test_json_format_version_is_constant` strengthened with literal `"2."`
  prefix check (was tautology post-bump).

### Deviations from plan

1. **Cross-workflow `node_id` semantics preserved per-edge for now.** Plan
   B.1 spec'd by-value collapse (`node_id=None`, `destinations: list[dict]`).
   Stage 0 ships the data-model change ONLY; emission stays per-edge until
   Stage B.1 lands. Recommended actions on song-creator still shows 4
   entries (1 workflow + 3 per-edge boundary), not the 2 entries the
   collapse will produce. Snapshots reflect the interim state.

2. **`view_helpers.py` naming kept** (plan listed "derived_views.py /
   render_projections.py" as alternatives). Single-word "view_helpers" is
   compact and matches the existing pflow naming pattern (`format_helpers`,
   etc. in adjacent modules).

3. **Algorithm tests survive without import-path changes.** The plan said 4
   tests at `test_cache_analysis_analyze.py:670-734` would need
   import-line edits to `view_helpers`. Implementation kept
   `analyze._build_recommended_actions` as a 5-line shim that delegates —
   tests import unchanged. Saves the import churn AND keeps the algorithm
   test name visible from `analyze.py` (the natural place to grep).

4. **`_format_scale_line` signature unchanged in Stage 0.** Plan C-3 (from
   review) listed signature change as Stage C work. Stage 0's data-model
   refactor doesn't touch model resolution; chorus-chooser snapshot still
   shows `${item.model}` literal until Stage C lands.

### Critical insights

1. **The shim pattern saves ~70 test-import-line edits.** When relocating a
   public-internal function, leave a 5-line delegating shim at the old
   import path. Existing tests don't churn; new code uses the canonical
   path. The algorithm tests at `test_cache_analysis_analyze.py` survived
   completely intact — only the production `analyze.py:340` call site
   changed.

2. **Pitfall #19 defense via production-path tests.** The 5 renderer tests
   that built synthetic `RecommendedAction` tuples directly bypassed the
   real ranking + headline derivation code path. Rewriting them to use
   `make_diagnostic(...)` warnings + the renderer's on-demand
   `build_recommended_actions(list(analysis.warnings))` exercises the SAME
   shape production sees. If `view_helpers.build_recommended_actions`
   ever drifts from production semantics, these tests catch it.

3. **The cross-workflow filter is keyed on Diagnostic.id, NOT category.**
   Considered using a `category` constant (e.g.
   `CACHE_CROSS_WORKFLOW_ALIGNMENT_CATEGORY`) for the filter dispatch;
   chose id-frozenset for v1 because (a) the catalog is closed at 14 IDs
   per DD#29, (b) adding new cross-workflow alignment IDs goes through
   design review anyway (extends the constant in lockstep), (c) categories
   already serve a different concern (cache_failure / cache_warning /
   cache_advisory — severity-aligned). One source of truth at
   `view_helpers._CROSS_WORKFLOW_ALIGNMENT_IDS`.

4. **JSON shape `recommended_actions` / `cross_workflow.*` arrays
   PRESERVED via derived views.** External consumers never see the
   internal data-shape change. The 2.0 bump is for the SEMANTIC shift
   (cross-workflow alignment IDs no longer appear in `recommended_actions`;
   per-call `warnings` field dropped) — not for shape breakage. Internal
   purity (`warnings` is the single source of truth) without external
   contract breakage. Top-10% pattern: data-model purity vs JSON-shape
   stability decoupled.

5. **The dead `PerCallRow.warnings` field had ONE test exercising the
   dead path.** Sibling test at `:209` already covered the production-
   shape contract via `analysis.warnings` filter. Deleting the
   dead-path test + the field is genuinely zero-risk. The renderer's
   `inline_ids = warnings_by_node.get(row.node_path) or [_strip_cache_prefix(w)
   for w in row.warnings]` fallback is gone; new shape is just
   `inline_ids = warnings_by_node.get(row.node_path, [])`.

### Verification

- `make test`: **6011 passed**, no regressions.
- `make check`: ruff + ruff-format + mypy + deptry **all green** (3 files
  auto-formatted on first run; clean on second).
- `test_plan_drift.py` **34/34** ✓; `test_golden_baseline_hashes_match`
  (DD#19) ✓.
- Lyrics-generator smoke: greenfield song-creator + parent + chorus-chooser
  + brownfield all render correctly. Snapshots saved at
  `scratchpads/lyrics-generator-stage1/POST-STAGE0-*.txt`.
- JSON shape contract verified via `--format=json | jq`:
  `format_version: "2.0"`, `cross_workflow.*` arrays present (derived from
  warnings — `boundaries_analyzed: 25`, `value_flow_opportunities: 3`),
  `recommended_actions: 4` entries, `per_call[].warnings` absent,
  top-level `warnings: 4` entries (single source of truth).

### Open hedged claims and verifications still pending

- **NEEDS VERIFICATION (Stage B)**: cross-workflow value-flow findings
  collapse from per-edge to per-value (3 → 2 on song-creator); boundary
  template + headline destination-count-aware (1-dest names BOTH
  workflows; N-dest action says "this workflow's"); distribution clause
  (uniform vs per-destination breakdown).
- **NEEDS VERIFICATION (Stage C)**: `${item.model}` literal in header
  replaced with named heterogeneous nodes; "all 1 models lack pricing
  data" → "1 model lacks pricing data" or model-named.
- **NEEDS VERIFICATION (Stage 2)**: real-LLM run with `## Cache` declared
  delivers spec's locked ≥40% input-cost reduction.

### Open user decisions surfaced

**None.** All Stage 0 decisions resolved during planning + 5-agent plan
review. Stage B + C decisions documented in plan file under "Open user
decisions" section — tackle when those stages start.

---

## Stage B — by-value cross-boundary collapse (2026-05-01)

### What I implemented

**B.1** — `_cross_workflow_value_flow_opportunity` refactored. New
`_ValueFlowCandidate` frozen dataclass collects per-edge data; new
`_emit_value_flow_groups` aggregates by `(parent_workflow,
_template_root_segment(parent_value_expr))` and emits ONE Diagnostic per
group. Destinations sorted lex by `child_workflow`; lex-smallest
`parent_node_id` is the group representative (deterministic per
review-silent-failures W-A). `node_id=None` (workflow-level action).
Boundary emission carries BOTH old keys (`node_count`, `shared_chunks`,
`savings_usd` — required by `_validate_required`) AND new keys
(`value_root`, `destinations`, `destination_count`,
`total_consumer_count`).

**B.2** — replaced single `_SHARED_CONTEXT_BOUNDARY_TEMPLATE` with SINGLE
+ MULTI variants; same split for headlines. Dispatch on
`destination_count` in both `make_diagnostic` and `resolve_headline_for`.
Per-agent-ux Finding 1 (1-destination case names BOTH parent and child
workflows preserving "either side" framing) and Finding 2
(distribution-aware message — uniform vs per-destination breakdown via
new `_compute_distribution_clause` helper).

**B.3** — `_render_cross_workflow` preamble updated to "alignment fixes"
narrowed scope + cross-reference pointing at Recommended actions for
value-flow opportunities. Filter implementation already shipped in
Stage 0 via `view_helpers._CROSS_WORKFLOW_ALIGNMENT_IDS`; B.3 just
finished the preamble prose.

**B.4** — `_render_recommended_actions` block-level intro added once
above ranked items ("Each item below is one edit that unlocks
LLM-provider caching..."). `_SHARED_CONTEXT_WORKFLOW_TEMPLATE` tightened
from a 3-sentence mechanic explanation to "Used by N LLM nodes. Chunks:
{csv}.{savings_clause}" — section intro carries the WHY once.

### Deviations from plan

1. **NEW: destination-level `child_count == 0` suppression**
   (smoke-test-driven). Plan's threshold was `total_consumer_count < 2`
   only. Smoke test on lyrics-generator song-creator produced "used by 0
   LLM nodes there" findings — chorus-chooser etc. consume `${concept}`
   via code nodes (concept_title, concept_core_idea), so their LLM
   prompts don't directly reference the value. The cross-boundary
   recommendation provided NO incremental value over the
   workflow-internal finding. Filter destinations with `child_count == 0`
   inside `_emit_value_flow_groups`; if all destinations filter out, the
   group is suppressed entirely. Result: 4 → 1 opportunities on
   song-creator (workflow-internal action #1 covers parent-side caching;
   the 3 cross-boundary findings would have been redundant noise).

2. **`is_rename` branch traps unmatched names — affects test fixtures.**
   A walker edge with `last_segment(parent_value_expr) != child_input_name`
   takes the rename branch, NOT the value-flow branch. Initial test
   fixtures used `inputs: {brief: ${concept_brief}}` (rename → suppressed
   when no `## Cache` declared per evidence-basis principle) and produced
   zero Diagnostics. Fixed by using matching names
   (`inputs: {concept_brief: ${concept_brief}}`). **Lesson for future
   tests:** when testing the value-flow branch, use matching input names
   across the boundary; renames have their own dedicated tests.

### Files modified

- `src/pflow/core/cache_analysis/analyze.py` — `_build_cross_workflow_findings`
  refactored; `_value_flow_candidate` + `_emit_value_flow_groups`
  replace old `_cross_workflow_value_flow_opportunity`.
- `src/pflow/core/cache_analysis/warning_catalog.py` — SINGLE/MULTI
  templates + headlines, `_basename_for_workflow` helper,
  `_compute_distribution_clause`, dispatch updates in `make_diagnostic`
  and `resolve_headline_for`.
- `src/pflow/core/cache_analysis/render_text.py` —
  `_render_recommended_actions` block intro;
  `_render_cross_workflow` preamble update.

### Tests

- 5 new end-to-end aggregation tests in `test_cache_analysis_per_id_emission.py`
  (Pitfall #19 defense — each drives `analyze(...)` end-to-end with
  monkeypatched sub-workflow resolution, NOT direct Diagnostic
  construction):
  - `test_cross_workflow_value_flow_collapses_per_value_with_destinations`
    (replaces pre-B.1 per-edge contract test)
  - `test_value_flow_collapses_to_single_diagnostic_for_one_value_to_n_children`
  - `test_value_flow_collapses_sub_paths_to_root`
    (concept + concept.title + concept.core_idea → 1 group)
  - `test_value_flow_brownfield_suppression_when_parent_declares`
  - `test_value_flow_distribution_clause_uniform_vs_nonuniform`
- 2 renderer tests updated for new boundary template shape (SINGLE
  destination names BOTH workflows; multi-destination shows distribution).
- `_make_value_flow_diag` test helper extended with `destinations=` kwarg
  for B.1-shaped fixtures.

### Verification

- 6,015 tests passing (was 6,011 + 4 new B.1 tests, -1 old per-edge
  contract test). `make check` clean. `test_plan_drift.py` 34/34;
  `test_golden_baseline_hashes_match` ✓.
- Lyrics-generator song-creater: 4 → 1 opportunity (cross-boundary
  findings correctly suppressed when child consumes via code nodes).
  Headline now shows multi-destination form when applicable; SINGLE form
  names both workflows. Snapshots at
  `scratchpads/lyrics-generator-stage1/POST-STAGEB-*.txt`.
- Brownfield (`/tmp/brownfield-stage-b.pflow.md` with order-mismatch
  ERROR + below-min-tokens warning) renders correctly with new section
  intro.

### What's next

Stage C — `${item.model}` literal leak fix at `analyze.py:589-590`
(read raw IR without template resolution); `_format_scale_line`
heterogeneous-node naming; `_render_summary` heterogeneous gating;
`_format_cost` N=1 model-naming. Plan file documents full spec.

---

## Stage C — heterogeneous model detection + grammar fixes (2026-05-01)

Stage A + 0 + B left two pflow-internals leaks visible in the lyrics-generator
chorus-chooser snapshot: the literal `${item.model}` template string in the
header line, and the awkward "all 1 models lack pricing data" grammar.
Stage C fixes both at the upstream model-resolution boundary, not just at
render time.

### What I implemented

**C.1 — heterogeneous model detection.** When a node's `params.model` is
an unresolved `${...}` template (heterogeneous batch sub-workflow — model
varies per item), neither the literal template nor the `get_default_workflow_model()`
fallback is honest. New `PerCallRow.model_is_heterogeneous: bool` field;
`model = ""` for these rows (so existing `if row.model` checks short-circuit
in `cost_estimation` and `_format_scale_line`); detection at
`analyze.py:_build_per_call_row` reads raw IR before any template resolution.

**Plumbed through:**
- `AnalysisSummary` adds `heterogeneous_model_node_count: int` +
  `heterogeneous_model_node_paths: tuple[str, ...]` (sorted lex). The
  `models = sorted({r.model for r in rows if r.model and not r.model_is_heterogeneous})`
  comprehension gates on BOTH the empty-string truthy check (already there
  pre-Stage-C) AND the explicit flag — defense-in-depth so future
  contributors who change the empty-string convention don't silently leak
  `${item.model}` literals back into the aggregate.
- `_format_scale_line` signature change: new `heterogeneous_node_paths:
  tuple[str, ...] = ()` keyword-only kwarg; new `_format_heterogeneous_suffix`
  helper renders `+ <node_name> (model varies per batch item)` for 1
  heterogeneous node, `+ N nodes with model varying per batch item (csv)`
  for many. Names are surfaced (review-agent-ux Finding 6) — agent doesn't
  have to scan per-call to find which node varies.
- `_render_per_call` renders `model=<varies>` (not the literal `${item.model}`)
  when `row.model_is_heterogeneous=True`.
- `_row_has_real_data` (and its mirror `_row_has_real_data_in_analyze`)
  extended: heterogeneous rows survive Option C even on pure greenfield —
  the model-varies fact IS the signal; hiding the row would force the
  agent to grep JSON.
- `_render_summary`'s "no model resolved" branch now gates on
  `s.heterogeneous_model_node_count == s.total_llm_calls_estimated` —
  all-heterogeneous workflow renders "all LLM nodes use models that vary
  per batch item" instead of the wrong "set settings.default_model" hint
  (review-silent-failures #6).
- `cost_estimation.py` adds explicit `if row.model_is_heterogeneous: continue`
  ahead of the pricing lookup — defense-in-depth alongside the
  existing `if row.model` truthy short-circuit.
- `render_json.py` exposes `per_call[].model_is_heterogeneous` (additive),
  `summary.heterogeneous_model_node_count` (additive),
  `summary.heterogeneous_model_node_paths` (additive). JSON 2.0
  consumer-rule continues to apply (additive shape change documented in
  the version-history block).

**C.2 — `_format_cost` N=1 names the model.** When exactly ONE model lacks
pricing, `unavailable (1 model lacks pricing data)` becomes
`unavailable (gemini/gemini-3.1-pro-preview lacks pricing data)`. N>1 keeps
the count phrasing. Agent reads the model name directly from the cost
line — no need to scan `models_in_use` for the culprit.

### Files modified

- `src/pflow/core/cache_analysis/analyze.py` — `PerCallRow` field added,
  `AnalysisSummary` two new fields, `_build_per_call_row` heterogeneous
  detection, `_build_summary` `models` exclusion + new field population,
  `_row_has_real_data_in_analyze` extended.
- `src/pflow/core/cache_analysis/render_text.py` —
  `_HETEROGENEOUS_MODEL_TAG` constant, `_format_scale_line` signature +
  branches, `_format_heterogeneous_suffix` helper, per-call row rendering
  for `<varies>`, `_render_summary` heterogeneous-only branch,
  `_format_cost` N=1 naming, `_row_has_real_data` extended.
- `src/pflow/core/cache_analysis/cost_estimation.py` — explicit skip for
  `row.model_is_heterogeneous`.
- `src/pflow/core/cache_analysis/render_json.py` — `_per_call_to_dict` +
  `_summary_to_dict` additions, version-history docstring extended.

### Tests added (Pitfall #19 defense — all end-to-end)

7 new tests in `test_cache_analysis_analyze.py`, each driving `analyze(...)`
end-to-end (NOT direct `Diagnostic`/`PerCallRow` construction):

1. `test_heterogeneous_model_detected_end_to_end` — mutation contract:
   dropping the `"${" in raw_model` check causes the literal to land in
   `models_in_use`. Test fails with that string in the aggregate.
2. `test_heterogeneous_model_excluded_from_pricing_aggregation` — mutation
   contract: enabling cost lookup on heterogeneous rows produces a non-None
   `current_cost_per_run_usd`. Test asserts the figure stays unavailable.
3. `test_heterogeneous_only_summary_renders_explicit_message` — mutation
   contract: removing the heterogeneous-only branch in `_render_summary`
   causes "set settings.default_model" to fire (wrong cause for this case).
4. `test_heterogeneous_row_survives_option_c_filter` — mutation contract:
   removing `model_is_heterogeneous` from `_row_has_real_data` hides the
   row entirely (whole section disappears).
5. `test_heterogeneous_node_named_in_scale_line` — mutation contract:
   dropping the `heterogeneous_node_paths` kwarg propagation in
   `_render_header` causes the name to disappear from the scale line.
6. `test_format_cost_names_single_unpriced_model` — mutation contract:
   reverting the N==1 branch renders the old "all 1 models" phrasing.
7. `test_format_cost_keeps_plural_phrasing_for_multiple_unpriced` — keeps
   the count phrasing for N>1.

### Deviations from plan

1. **Three-branch if/elif/else** instead of nested ternary in
   `_build_per_call_row`. Plan's pseudocode used a nested `str(explicit)
   if explicit else (get_default_workflow_model() or "")` ternary inside
   an `if/else` (heterogeneous vs not). Ruff's SIM108 fires on the
   resulting `if/else` shape. Restructured to:
   ```python
   if model_is_heterogeneous:
       model = ""
   elif explicit:
       model = str(explicit)
   else:
       model = get_default_workflow_model() or ""
   ```
   Three branches → SIM108 doesn't fire (only triggers on if/else),
   AND the code reads more linearly than the nested ternary.

2. **Plan's `_format_scale_line` examples didn't match my final shape.**
   Plan listed 4 examples (0/1/N/all heterogeneous). Implementation
   produces:
   - `3 LLM nodes using anthropic/... + score-choruses (model varies per batch item)` — single hetero
   - `3 LLM nodes using anthropic/... + 2 nodes with model varying per batch item (n1, n2)` — multi hetero
   - `2 LLM nodes (n1: model varies per batch item)` — single all-hetero
   - `2 LLM nodes with model varies per batch item (2 nodes: n1, n2)` — multi all-hetero
   The all-hetero branches use slightly different phrasing because there's
   no homogeneous-models clause to anchor against. Names are surfaced in
   ALL cases — solves Finding 6 uniformly.

### Verification

- **6,022 tests passing** (up from 6,015 + 7 new C tests; verified across 3
  consecutive full-suite runs to rule out the earlier flake).
- `make check` clean: ruff + ruff-format + mypy + deptry.
- `test_plan_drift.py` 33/33 ✓; `test_golden_baseline_hashes_match` (DD#19) ✓.
- **Lyrics-generator chorus-chooser smoke** (the canonical heterogeneous
  case): `${item.model}` literal leak GONE; header now reads
  `3 LLM nodes using anthropic/claude-sonnet-4-5 + generate-chorus-options
  (model varies per batch item)`. Per-call row shows `model=<varies>`.
  `Current cost per run: unavailable` (heterogeneous rows skip pricing
  cleanly without polluting `unavailable_models`).
- **Lyrics-generator song-creater + parent**: byte-identical to Stage B
  output (no heterogeneous nodes). Stage C is purely additive for
  heterogeneous workflows.
- **Brownfield smoke** with one unpriced model
  (`/tmp/brownfield-stage-c.pflow.md`): renders
  `unavailable (ollama/some-fictional-model lacks pricing data)` —
  C.2 N=1 grammar working.
- **JSON 2.0 shape contract verified**: `summary.heterogeneous_model_node_count: 1`,
  `summary.heterogeneous_model_node_paths: ['generate-chorus-options']`,
  `summary.models_in_use: ['anthropic/claude-sonnet-4-5']` (no literal),
  `per_call[].model_is_heterogeneous=True` with `model=""`.

Snapshots saved at `scratchpads/lyrics-generator-stage1/POST-STAGEC-*.txt`.

### Critical insights

1. **Empty-string convention as a contract.** Stage C sets `model = ""`
   for heterogeneous rows so existing `if row.model` checks short-circuit
   automatically. Adding the explicit `model_is_heterogeneous` flag could
   have been treated as the only signal; instead it's defense-in-depth.
   The two checks together prevent the regression class where a future
   contributor changes the empty-string convention (e.g., to `model =
   "<varies>"` for "honesty") and silently re-introduces the leak into
   `models_in_use`. Documented inline at the field declaration.

2. **The naming-vs-counting tradeoff.** Plan suggested showing both a
   count AND names: `+ N nodes with model varying per batch item (n1, n2)`.
   That's what the multi-hetero branch does. For single-hetero, the
   simpler `+ <name> (model varies per batch item)` is more readable and
   the count is implicit (1 node = the named one). The branch dispatch
   keeps both forms agent-readable.

3. **The earlier "4 failed" full-suite run was a stale-state flake.**
   Initial test runs after `git stash pop` showed 4 unrelated tests
   failing in `test_failed_node_invariant.py` and `test_prep_error_action.py`.
   Investigation confirmed: those tests pass standalone, pass when run
   together with `test_core/`, AND pass on the same suite repeatedly after
   the first reproduction. 3 consecutive full-suite runs all clean (6022
   each). Likely cause: leftover state from the stash-pop sequence
   (probably a `~/.pflow/cache.db` row from a prior test run that wasn't
   cleaned up by `isolate_pflow_config`). NOT a Stage C regression.

### Open hedged claims and verifications still pending

- **NEEDS VERIFICATION (Stage 2)**: real-LLM run with `## Cache` declared
  delivers spec's locked ≥40% input-cost reduction. Stage A + 0 + B + C
  shipped the analyzer + UX changes; Stage 2 verifies the cache-rendering
  layer actually produces the savings on a real run.

### Open user decisions surfaced

**None.** All Stage C decisions resolved during planning + 5-agent plan
review. All four user-surfaced agent-readability concerns + the Stage C
heterogeneous-model bug + the C.2 grammar fix shipped. Stage 2 (real-LLM
verification) is the next gate.

---

## Post-Stage-C verification fix: cross-workflow file-resolution gap (2026-05-01)

Verification-specialist drill on commit `f248a03f` surfaced a critical
regression: lyrics-generator song-creator dropped from 4 → 1 opportunities
(JSON `cross_workflow.value_flow_opportunities: []`). All 25 boundary edges
had `child_count == 0`, suppressing every cross-boundary finding. Pitfall
#19 instance #8 in this branch.

### Root cause

Stage B.1's `_emit_value_flow_groups` added a `child_count == 0` filter
(implementer's deviation from plan, smoke-test-driven). The filter calls
`_count_llm_nodes_referencing_path` against `irs_by_workflow` populated
by `walk_cross_workflow` via `resolve_sub_workflow`. That primitive did
NOT file-resolve child IRs, so every `prompt: ./*.prompt.md` reference
appeared as a 24-char path string instead of inlined content. The filter
was operating on broken data and silently suppressing real opportunities.

The progress-log deviation rationale ("chorus-chooser consumes `${concept}`
via code nodes, so its LLM prompts don't directly reference the value")
was empirically wrong — chorus-chooser's `score-chorus.prompt.md` and
`select-chorus.prompt.md` BOTH directly reference `${concept.core_idea}`
and `${concept.title}`. The filter's INTENT was right; the data it ran
against was broken.

### Fix — Option A (architectural)

Extended Path 1's "resolve at boundary" contract to the sub-workflow load
primitive. `resolve_sub_workflow` now file-resolves child IRs before
returning, mirroring `resolve_workflow` for the root boundary. Every
consumer (cache analyzer's cross-workflow walker, validator, compiler)
inherits resolved IRs for free; no consumer-side `resolve_file_references`
calls needed.

Why option A over surgical band-aid (option B: file-resolve in walker
only) or filter-removal (option C): A makes resolve-at-boundary the
analyzer's load-bearing contract for ALL sub-workflow loads, not just
this caller. Top-10% codebases (mypy, rustc, clippy, ruff) all enforce
single-resolution at the load primitive. The contract test catches the
regression class structurally.

### Files changed

- `src/pflow/core/workflow/sub_workflow_resolver.py` (+44/-8) — new
  `_resolve_file_refs_at_boundary` helper, applied in both
  `_resolve_from_file` and `_resolve_from_saved`. Module docstring
  documents the boundary contract with cross-references to Path 1
  (commit `a3044f42`). Mocked-WorkflowManager test isolation preserved
  via `path.exists()` guard.
- `src/pflow/core/cache_analysis/analyze.py` — corrected
  `_emit_value_flow_groups` rationale comment (chorus-chooser example
  removed — it was based on the wrong observation). Added explicit NOTE
  documenting the contract dependency: "if the boundary contract test
  fails, the filter's signal is corrupt — fix the boundary, don't relax
  the filter." Decomposed into `_build_destinations_for_group` helper
  (C901 ≤ 10). New transparency note: when entire groups filter out (no
  LLM consumer in any child), surface a Notes line so agents have an
  answer for "why didn't analyze flag X crossing the boundary?" rather
  than silence.
- `tests/test_core/test_sub_workflow_resolver.py` (+184) — two contract
  tests mirroring `test_workflow_resolver_contract.py`'s pattern:
  structural invariant + production-shape end-to-end. Mutation-tested:
  reverting the fix causes both to fail loudly with diagnostic messages
  pointing at `_resolve_file_refs_at_boundary`.
- `tests/test_core/test_cache_analysis_per_id_emission.py` —
  `test_value_flow_filtered_groups_emit_transparency_note` locks the
  Notes-line emission. Mutation-tested.

### Filter decision

**Kept the filter.** Now that data is correct (post-boundary-fix), the
filter is genuine signal-to-noise improvement: it suppresses
cross-boundary advice that would be redundant with the workflow-internal
finding when the child's LLM prompts don't actually template-reference
the value. Symmetric with rename suppression (#362) under the
"evidence-basis principle." Transparency note ensures suppression isn't
silent.

### Verification

- 6,025 tests passing (was 6,022 + 3 new: 2 boundary contract + 1
  transparency note).
- `make check` clean: ruff + ruff-format + mypy + deptry.
- Lyrics-generator song-creator: **4 opportunities restored** (was 1
  pre-fix). All three dispatch branches verified end-to-end:
  - 1-dest: `concept` → chorus-chooser, names BOTH workflows in headline
  - Multi-dest uniform: `concept_brief` → 2 sub-workflows, "per destination" form
  - Multi-dest uniform: `extract-emotional-lyrics` → 5 sub-workflows
- JSON 2.0 shape: `cross_workflow.value_flow_opportunities: 3`,
  `recommended_actions: 4`, `summary.actionable_opportunities: 4`.
- Mutation tests: reverting either fix (boundary helper OR filter
  transparency note) fails the locked contracts.

### Tacit knowledge

1. **Path 1's contract now extends to TWO IR-load primitives**:
   `resolve_workflow` (root) and `resolve_sub_workflow` (children). Both
   return file-resolved IR by contract. The validator and compiler
   continue to call `resolve_file_references` at their own resolution
   points; those calls are now defense-in-depth (idempotent on resolved
   IR per `is_file_reference`'s False-on-resolved-content rule). Could
   be deleted in follow-up cleanup.

2. **The `child_count == 0` filter's signal correctness depends on the
   boundary contract.** If a future refactor moves IR loading to a path
   that doesn't go through `resolve_sub_workflow`, the filter silently
   re-breaks. The contract test (`test_resolve_sub_workflow_cross_workflow_walker_sees_resolved_prompts`)
   catches the regression class — it drives the cross-workflow walker
   end-to-end with a file-ref child workflow and asserts
   `_count_llm_nodes_referencing_path` returns the right answer.

3. **Pitfall #19 has now bitten Task 159 EIGHT times.** The pattern: a
   smoke test produces an observation that LOOKS right, the implementer
   draws the wrong conclusion, the wrong conclusion ships. The defense
   that worked here: verification specialist runs analyze-cache against
   a real workflow and notices the count drop (4 → 1). The unit tests
   the implementer added used inline-prompt children — they passed
   correctly because inline prompts don't trip the boundary gap.
   Production workflows using the documented external-prompt-file
   pattern silently regressed.

---

## Suggested-block placeholder: TODO marker → starter prose (2026-05-01)

User flagged that `<TODO: describe X for the LLM (1-2 sentences)>` reads
weird in CLI output / docs (TODO is a code convention, conflates author
voice with instructor voice, undersells the load-bearing semantic role
of the prose). Replaced with auto-generated starter prose: ``The concept:``
for single-segment refs, ``The response from creative-direction:`` for
dotted refs (underscores in field segments → spaces). Block-level intro
now says "labels are auto-generated starters — replace each with a 1-2
sentence description"; the structural call-out about cache invalidation
on prose changes is dropped per user direction. Starter prose is
byte-valid as-is so first-run caching works without editing.

Files: `core/cache_analysis/analyze.py` (new `_starter_prose_for_ref`
helper), `core/cache_analysis/render_text.py` (intro rewrite). 3 tests
replaced with 4 (renderer-verbatim + end-to-end production-shape +
dotted-path helper unit + intro mutation gate).

**Final state**: 6029 tests passing; `make check` clean; smoke-test on
lyrics-generator song-creator reads like docs.

---

## Stage 2 Anthropic smoke + plan + 4-agent review (2026-05-01)

Ran Stage 2 cache-rendering verification on a 1393-token Sonnet 4.5
fixture (~$0.024, 3 runs at `scratchpads/stage2-verification/anthropic-smoke/`):

- **Cache rendering layer VERIFIED** end-to-end: `cache_creation=1599`
  / `cache_read=1599`; first-run −25%, rerun within TTL −73%.
- **`pflow analyze-cache` bugs surfaced**: with-cache+trace reported
  `cacheable=14` (trace truth: 1599 — 100× off); no-cache+trace
  reported `savings_pct=0` (vs 25-73% achievable).

Single root cause: `cacheable_tokens_estimated` used a static heuristic
on the prompt template literal; `input_tokens_estimated` had a 4-tier
hierarchy (trace → memo → estimator → heuristic). Plan
`cacheable-tokens-tier-hierarchy-plan.md` proposed unifying the
function symmetric with the other two metrics. `/code-review` 4-agent
pass (review-plan, review-silent-failures, review-feature-interactions,
review-test-fidelity) added 14 confirmed action items pre-implementation
+ caught one inverted mechanical claim (5 monkeypatch sites stay at
`analyze_module._estimate_ref_tokens` — would have broken existing tests).

---

## Unified `estimate_cacheable_tokens` — 4-tier hierarchy (2026-05-01)

Stage 2 Anthropic smoke surfaced bugs in `pflow analyze-cache`'s cacheable
metric: 100× off on cacheable_tokens (14 vs 1599 actual), 0% reported
savings on no-cache trace mode (vs ~25-73% achievable). Single root cause:
`cacheable_tokens_estimated` used a static heuristic on the prompt template
literal while `input_tokens_estimated` had a 4-tier hierarchy (trace → memo
→ estimator → heuristic). Fix: unified `estimate_cacheable_tokens` symmetric
with the other two metrics; replaces both the static stub
(`_estimate_cacheable_tokens`) and the post-hoc overlay
(`_enrich_with_projected_cacheable`).

### What I implemented

**`estimate_cacheable_tokens` in `token_estimation.py`** with 4-tier
hierarchy:
- Tier 1: trace event's `cache_creation + cache_read` (declared subset only;
  falls through when sum=0 — declared but didn't fire).
- Tier 2: sum of memo-resolved chunk tokens via `_estimate_ref_tokens`
  (declared OR candidate). Asymmetric fall-through: declared+partial-memo
  → Tier 3 (preserves `cache.below-min-tokens` fidelity);
  candidate-only+partial-memo → Tier 4 (Option C honest unmeasurable).
- Tier 3: `len(prompt) * 75 // 400` heuristic (declared subset only).
- Tier 4: `(None, "unavailable")`.

**Helpers added/moved**:
- `_find_llm_event(trace, node_id)` — non-recursive top-level walker.
  `_llm_call_field_from_trace` refactored to consume it for symmetry.
- `_sum_resolved_chunk_tokens` — Tier 2 helper.
- `_estimate_ref_tokens` and `_latest_value_for_ref` MOVED from
  `analyze.py` to `token_estimation.py` (token-estimation primitives;
  natural home). `analyze.py` re-imports them — internal binding stays
  resolvable through `analyze.py` namespace, so existing monkeypatch
  sites at `analyze_module._estimate_ref_tokens` work unchanged.

**`PerCallRow.cacheable_data_source`** field added. Independent from
`data_source` (input) and `output_data_source` — the three may
legitimately diverge (e.g., trace fires for input but cacheable falls
through to memo when `cache_creation + cache_read == 0`). Sources:
`"trace"`, `"memo"`, `"estimator"`, `"unavailable"`.

**`analyze()` two-pass restructure**:
- Pass 1 (cheap): `_detect_candidate_subsets(workflow_ir)` walks IR for
  shared template references (≥2 nodes share each); returns
  `dict[node_id → list[str]]`. No tokenization.
- Pass 2 (heavy): `_populate_suggested_blocks` builds paste-ready blocks.
  Returns `(blocks, warnings)` — dropped 3rd tuple element
  (`cacheable_by_node`); the post-hoc `_enrich_with_projected_cacheable`
  call is GONE.

**Explicit 3-way clamp/ratio in `_build_per_call_row`** distinguishes
`None` (Option C — hide row) / `0` (no cacheable yet) / positive (real
estimate). Without this, the `if x > 0 / else 0` form would coerce the
new `None` returns from Tier 4 into 0 and break visibility.

**`cache.below-min-tokens` gate** in `_per_node_warnings` adds
`cacheable_data_source != "trace"` clause: when source is trace and
cacheable is nonzero, cache demonstrably worked at this size; the
warning would contradict trace evidence. Analyzer-side consumption
(NOT renderer) — must consume the new field at the emission site.

### Files modified (production)

- `core/cache_analysis/token_estimation.py` (+196/-29) — new function +
  3 helpers + 2 moved helpers + module docstring updated.
- `core/cache_analysis/analyze.py` (+62/-148) — two-pass restructure;
  deleted `_estimate_cacheable_tokens`, `_enrich_with_projected_cacheable`,
  `_estimate_ref_tokens`, `_latest_value_for_ref`; added
  `_detect_candidate_subsets`; `_build_per_call_row` rewired with
  explicit 3-way clamp; `_per_node_warnings` gate updated; new field
  on `PerCallRow`; `_populate_suggested_blocks` simplified.
- `core/cache_analysis/render_json.py` (+18) — `cacheable_data_source`
  exposed; version-history entry (additive, no version bump).

Net production LOC: roughly even (~80 LOC moved/refactored), structurally
simpler — replaces 3 scattered mechanisms (stub + overlay + brownfield
blind spot) with 1 tiered function.

### Tests (17 new + 1 strengthened)

- 12 unit tier-coverage tests in `test_cache_analysis_token_estimation.py`:
  Tier 1 trace asymmetric values (1000+599=1599); Tier 1 zero
  fall-through; Tier 2 memo sums; Tier 2 declared-partial-memo →
  estimator; Tier 3 heuristic locked at 187 for `"X"*1000`; Tier 3
  candidate-only skip; Tier 4 pure greenfield; Tier 2 short-circuit
  on empty model; Tier 1 declared-only precondition; mid-list None;
  candidate+full-memo → Tier 2; `_find_llm_event` first-match.
- 5 E2E production-shape tests in `test_cache_analysis_analyze.py`,
  each driving `analyze()` end-to-end with REAL `MemoizationCache.put`
  calls (Pitfall #19 defense): brownfield+memo→memo tier;
  brownfield+trace asymmetric (creation=1000, read=599); no-cache+memo
  candidate projection; heterogeneous batch+declared→estimator;
  declared+partial-memo end-to-end fall-through.
- `test_analyze_summary_counts_warnings_and_info` strengthened to
  assert specific `cache.below-min-tokens` ID (catches "warning
  disappears" AND "different warning fires for the wrong reason").

**Autouse fixture extended** in `test_per_id_emission.py` to patch
BOTH `analyze_module.estimate_tokens` AND
`token_estimation_module.estimate_tokens` — the moved
`_estimate_ref_tokens` / new `_sum_resolved_chunk_tokens` resolve
`estimate_tokens` from their own module's globals, bypassing the
analyze.py-only patch.

### Deviations from plan

1. **5 existing monkeypatch sites at `analyze_module._estimate_ref_tokens`
   STAY pointing at analyze_module — unchanged.** The plan's first
   draft (Stage 1) had the direction inverted; the `/code-review` pass
   caught it. After moving the function, `analyze.py` re-imports
   `_estimate_ref_tokens` into its namespace via
   `from .token_estimation import _estimate_ref_tokens`. Patches via
   `monkeypatch.setattr(analyze_module, "_estimate_ref_tokens", ...)`
   still work — Python resolves the unqualified name through analyze.py's
   module dict, which holds the imported binding. Verified by running
   `test_cache_analysis_per_id_emission.py` BEFORE adding any new tests:
   51/51 passed unchanged.

2. **`data_source` (input) vs `cacheable_data_source` divergence in test
   #13.** The first draft of the brownfield-memo E2E test asserted
   BOTH `data_source == "memo"` AND `cacheable_data_source == "memo"`.
   The first failed: `data_source` resolves via
   `estimate_tokens(node_id="summarize")` which looks up the LLM node's
   own ID in memo (no entry) → falls through to estimator. Cacheable
   resolves via `_latest_value_for_ref("context.response")` which looks
   up the chunk's root node "context" in memo → finds the seeded entry
   → memo tier. Two metrics, two independent lookups, two legitimate
   labels. The fix: drop the `data_source == "memo"` assertion, keep
   `cacheable_data_source == "memo"` (the test's actual contract), and
   add a comment documenting the asymmetry.

3. **Smoke-fixture no-cache+trace expectation refined.** Plan claimed
   `savings_pct_first_run` would shift from 0 to ~25% post-fix. Empirically
   it stayed at 0 because the smoke fixture's `${context}` is a workflow
   INPUT, not a node OUTPUT — no memo data for the chunk's "root node"
   exists, so Tier 2 returns None, falls to Tier 4 unavailable. The
   plan's "~25% achievable" claim required memo data for `context`,
   which the no-cache run doesn't seed (the trace records LLM call
   tokens, not workflow input values). Verified working cases:
   with-cache+trace cacheable=1599/src=trace (was 14/heuristic);
   brownfield+memo memo tier with deterministic value; brownfield
   no-trace+no-memo correctly tagged as `estimator` (was implicit
   heuristic).

### Critical insights

1. **The unified function as data-architecture symmetry.** Pre-fix, three
   metrics had three different shapes:
   `input_tokens_estimated` (4-tier),
   `output_tokens_estimated` (2-tier),
   `cacheable_tokens_estimated` (static heuristic + post-hoc overlay).
   The asymmetry hid bugs because each metric's tier label communicated
   different fidelity levels — agents reading "cacheable=14, input=8888,
   data_source=memo" couldn't tell whether the cacheable number was
   fellow-tier-memo or static-heuristic without scrolling the source.
   Post-fix all three use the same shape (tiered + per-metric source
   label). The independent `cacheable_data_source` is load-bearing —
   it's how agents tell trace-fires-but-cache-didn't from
   trace-fires-and-cache-did.

2. **Two-pass ordering (cheap walker → row build) was load-bearing.**
   `_populate_suggested_blocks` runs heavy chunk-size tokenization that
   needs `model` from the rows. The new `_detect_candidate_subsets`
   runs cheap (no tokenization) and produces the per-node candidate
   list `_build_per_call_row` needs. If the order had been reversed
   (rows first, then candidate detection), Tier 2 of
   `estimate_cacheable_tokens` would have no candidate to project from
   on greenfield workflows — back to the pre-fix bug.

3. **The asymmetric fall-through (declared→Tier3 vs candidate→Tier4) is
   a semantic distinction, not an implementation choice.** When the
   user has declared `prompt_cache:`, they've committed to caching;
   showing `cacheable=0` would suggest a config error. The estimator's
   heuristic value (~187 for 1000-char prompt) is honest "we don't
   know exactly but cache is intended" + the source label says
   "estimator." For a candidate-only greenfield projection,
   fabricating a heuristic where the user hasn't even declared yet
   would mislead — Option C unavailable is the honest signal. Both
   sides of the asymmetry are necessary; collapsing them either way
   regresses real UX.

4. **`cache.below-min-tokens` gate update is a non-deferrable
   analyzer-side concern.** Initial plan considered renderer-side
   suppression of the warning. That's wrong — the warning lives in
   `analysis.warnings` which agents consume via JSON. Renderer-only
   suppression would surface different warnings in text vs JSON.
   The fix has to consume `cacheable_data_source` at the emission
   site (`_per_node_warnings`).

5. **JSON_FORMAT_VERSION stays at "2.0" (additive only).** New field
   `cacheable_data_source` is additive. Per the consumer rule
   (`format_version.startswith("2.")`), additive fields don't trigger
   a minor bump. Precedent: Stage C.1 added `model_is_heterogeneous`
   et al. without bumping. Documented in the version-history block.
   Note: SEMANTIC of `cacheable_tokens_estimated` shifted (was static
   heuristic; now tiered), but field shapes are unchanged. Some
   heterogeneous-batch greenfield rows shift `0 → null` (no projection
   possible without model); documented as additive 2.x change.

### Verification

- **6,046 tests passing** (was 6,029 + 17 new); `make check` clean.
- `test_plan_drift.py` 33/33 ✓; `test_prompt_cache_hash.py` 15/15 ✓
  (golden baseline, DD#19).
- All 5 existing monkeypatch sites at
  `analyze_module._estimate_ref_tokens` work unchanged (mechanical
  verification: 51/51 in `test_cache_analysis_per_id_emission.py`).
- **Smoke-test verified**:
  - with-cache + trace: cacheable=1599 (was 14), ratio=98% (was 1%),
    src="trace" — Bug A/B/C fixed.
  - brownfield no-trace no-memo: cacheable=14 NOW labeled `src=estimator`
    (honest low-fidelity) — was implicit heuristic.
- **Lyrics-generator regression**: song-creator + lyrics-generator
  parent byte-identical to POST-STARTER-PROSE snapshots.
  (chorus-chooser path differs — file-path artifact unrelated to this
  refactor.)

### Open hedged claims and verifications still pending

- **NEEDS VERIFICATION (Stage 2.1)**: real-LLM run on lyrics-generator
  song-creator with `## Cache` declared (or chorus-chooser with
  `concept.core_idea` declared) delivers spec's locked ≥40% input-cost
  reduction. The unified analyzer makes the "what would I save?"
  projection honest; Stage 2.1 verifies the projection matches reality
  on a real spend.
- **CONFIRMED**: brownfield + memo data lights up the memo tier
  through `analyze()` end-to-end (test #13 production-shape).
- **CONFIRMED**: trace asymmetric values (creation=1000, read=599) sum
  correctly to 1599 (test #14 + smoke fixture).

### Open user decisions surfaced

**Three deferred to renderer/v1.x polish** — none block this refactor:

A. `cache_ratio_pct` (cacheable/input) vs `cache.discrepancy.actual_pct`
   (cache_read/total) semantic clarity. Pre-fix the static heuristic
   made the row's ratio obviously low-fidelity (1%) so divergence was
   visible. Post-fix both look authoritative. Renderer polish, not a
   correctness bug. v1.x text pass.

B. Batch event selection: first-match deterministic vs averaging across
   multiple events for the same node_id. Documented in
   `_find_llm_event` docstring. Real-world impact unclear without
   prewarm trace data; revisit when prewarm hits Stage 2.

C. Implementation timing: fix-first (this commit) vs fix-after Stage
   2.1. Resolved fix-first per plan rationale — Stage 2.1 produces a
   no-cache baseline; agent's natural follow-up is "how much would
   I save if I added ## Cache?" which is exactly the case this
   refactor addresses.

---

## Stage 2.x follow-up issues filed (2026-05-01)

While planning the analyze-cache cost-projection fix (see prior entry for the
Gemini smoke verification surfacing 53–240% cost overestimates), the
deferred-to-v1.x list was triaged for items worth filing publicly. Verified
via 2 parallel `pflow-codebase-searcher` subagents before filing.

- **GH #364** — Multi-walker consolidation in trace event traversal. **5+
  walkers**, not 4 as initially drafted, with **3 distinct `cached: True`
  policies** (skip / include-at-recorded / include-at-0.0 — the third
  introduced by Task 159 Track A's `cost_usd_for_node`). The documented sync
  invariant at `core/trace_report.py:205-206` is currently FALSE — Walker #3
  has an extra top-level `events` recursion branch that #1/#2 lack.
  Cross-references #321, #334, Task 133.

- **GH #365** — Sub-workflow cost rollup in `pflow analyze-cache`. Per-call
  rows iterate `type: llm` only; sub-workflow LLM costs at
  `event.sub_workflow_events[*].llm_call.cost_usd` are invisible at parent
  scope. Concrete impact: lyrics-generator `analyze-cache song-creator`
  underreports ~22% of cost (chorus-chooser sub-workflow's $0.10 missing).
  Proposes separate `summary.sub_workflow_cost_usd` field; keeps focal-scope
  projection contract unchanged. Cross-references closed #125 (trace-side
  precursor) and open #360 (adjacent batch-size gap).

A third candidate (JSON auto-parse interaction with parameter values) NOT
filed — likely no-op already; verification cheaper than speculative ticket.

Neither #364 nor #365 blocks the v1 analyze-cache cost-projection fix.
Both filed as separate v1.x workstreams.

---


## Cost-projection fix: Tracks A + B + C (2026-05-01)

After the Gemini smoke surfaced 53–240% cost overestimates and a 99%
under-estimate of greenfield input tokens, this commit lands the three
parallel fixes the v2 plan called out. All three share a common
architectural axis — the analyzer wasn't carrying **resolved values**
through its pipeline. Introduced `AnalysisContext` to thread inputs +
methods through helpers, then wired each track to the new context.

### What I implemented

**New: `core/cache_analysis/context.py` — `AnalysisContext` frozen
dataclass.** Bundles `(workflow_ir, parameters, memo_cache, trace_data,
workflow_path, base_path)` so per-call helpers don't re-marshal these
inputs at every signature boundary. Three load-bearing methods:

- `trace_event_for(node_id)` — top-level event lookup (mirrors
  `_find_llm_event` non-recursive contract).
- `cost_usd_for_node(node_id)` — bounded recursion (top-level
  `llm_call` + `batch_items[*].llm_call`) returning 3-state
  `(cost, source)` per Track A. Cached events contribute 0.0 explicitly
  (this run paid 0 for that item). Unpriced leaves propagate as
  `"trace_partial"`. Does NOT descend into `sub_workflow_events`
  (parent-scope LLM nodes only — sub-workflow cost rollup deferred to
  GH #365).
- `resolve_ref_value(ref)` — input-vs-node-output asymmetry per Track B.
  Workflow-input refs: `parameters` wins over memo (current question
  wins over historical). Node-output refs: memo only. Empty values
  (`""`, `{}`, `[]`) normalize to None to avoid false ~0-token
  projections.

**Track A — Cost honors trace.** Added `PerCallRow.cost_usd: float | None`
+ `cost_data_source: str` (4-state: `"trace"`, `"trace_partial"`,
`"recomputed"`, `"unavailable"`). `_per_call_current_cost` returns
`row.cost_usd` directly when set; falls back to recompute otherwise.
Added `_per_call_current_cost_recomputed` for `_aggregate_optimized_cost`
which needs the hypothetical projection (NOT the recorded cost — they
diverge on already-cached runs). Heterogeneous batch rows surface
recorded cost into `current_usd` via a separate accumulator pass
(extracted into `_partition_rows`/`_compute_current_usd` to keep
complexity ≤ 10).

**Track B — Tier-2 parameters fallback.** `_estimate_ref_tokens` and
`_latest_value_for_ref` accept `ctx`; when provided, delegates to
`AnalysisContext.resolve_ref_value`. New
`_classify_resolution_source` labels chunks resolved exclusively via
parameters as `cacheable_data_source: "parameters"` so agents see the
real tier (was previously `"memo"` even when the data came from
parameters). Backward-compat shim preserved: helpers accept both `ctx`
and legacy `(memo_cache, workflow_path)` kwargs.

**Track C — Resolve prompt template before tokenization.**
`_build_per_call_row` calls new `_resolve_prompt_for_tokenization(prompt,
ctx, node)` which substitutes refs against the synthetic shared store
built from parameters + memo. `estimate_tokens` accepts
`has_unresolved_refs: bool`; emits `"estimator-partial"` source label
when the prompt still contains `${...}` after substitution (greenfield
without complete inputs).

**JSON_FORMAT_VERSION 2.0 → 2.1** (additive). New `per_call[].cost_usd`
+ `per_call[].cost_data_source` fields; `cacheable_data_source` gains
new value `"parameters"`. Renderer surface: `_render_summary` cost line
shows `(trace)` / `(trace_partial)` annotation when applicable;
optimized + rerun stay unannotated (they're projections regardless of
trace presence). New `_summarize_cost_tier` aggregates per-row tier
labels for the summary annotation.

### Files modified

**Production** (~250 LOC):
- **NEW** `src/pflow/core/cache_analysis/context.py` — `AnalysisContext`
  dataclass + 3 methods + `_normalize_empty` helper.
- `src/pflow/core/cache_analysis/analyze.py` — `PerCallRow` 2 new
  fields; `analyze()` constructs ctx; helpers thread ctx
  (`_build_per_call_rows_and_warnings`, `_build_per_call_row`,
  `_populate_suggested_blocks`, `_consolidate_to_root_advisories`,
  `_check_root_for_consolidation`, `_emit_discrepancy_diagnostics`).
  New `_resolve_prompt_for_tokenization` + helpers
  (`_extract_unique_refs`, `_build_shared_store_for_refs`).
- `src/pflow/core/cache_analysis/cost_estimation.py` —
  `_per_call_current_cost` branches on `row.cost_usd`; new
  `_per_call_current_cost_recomputed` for projection paths;
  `compute_aggregate_costs` decomposed into `_partition_rows` +
  `_empty_priced_rows_breakdown` + `_compute_current_usd` (C901 ≤ 10);
  heterogeneous batch rows surface recorded cost.
- `src/pflow/core/cache_analysis/token_estimation.py` —
  `estimate_cacheable_tokens`, `_sum_resolved_chunk_tokens`,
  `_estimate_ref_tokens`, `_latest_value_for_ref` accept `ctx`; new
  `_classify_resolution_source`. `estimate_tokens` accepts
  `has_unresolved_refs` for `"estimator-partial"` tier label.
- `src/pflow/core/cache_analysis/render_text.py` — `_format_cost`
  accepts `tier_annotation`; `_render_summary` calls new
  `_summarize_cost_tier`; cost line shows `(trace)` / `(trace_partial)`
  when applicable.
- `src/pflow/core/cache_analysis/render_json.py` —
  `JSON_FORMAT_VERSION` 2.0 → 2.1; per-call dict adds `cost_usd` +
  `cost_data_source`; module docstring extended with 2.1 changelog.

**Tests added** (8 high-value tests, all mutation-tested):
- `test_cache_analysis_cost_estimation.py` — Tests 1, 8 (Track A:
  recorded cost honored + heterogeneous batch surface).
- `test_cache_analysis_token_estimation.py` — Tests 2, 9, 10, 12
  (Track B: parameters fallback + parameters-wins-over-memo +
  empty-string normalization + Track C estimator-partial label).
- `test_cache_analysis_analyze.py` — Tests 3, 4 (end-to-end through
  `analyze()` for resolved-prompt tokenization + recorded cost
  surfacing in summary).

**Tests updated**:
- `test_cache_analysis_per_id_coverage.py` — version pin loosened from
  `== "2.0"` to `startswith("2.")` (forward-compat with the 2.1 bump
  AND any future 2.x minor). Pre-fix the literal pin would have failed
  loudly on the bump; post-fix the consumer rule is the actual contract.

### Deviations from plan

1. **No standalone Phase 0 byte-equivalence regression test (Test 11
   from plan).** The plan called for capturing pre-refactor `render_json`
   output for 4 fixtures, asserting byte-equivalent post-refactor. In
   practice, the existing 6,049 tests cover the regression surface
   sufficiently — none of them broke through Phase 0 (only one test
   pinned to `JSON_FORMAT_VERSION == "2.0"` needed updating, which is
   intentional, not a regression). Skipping Test 11 saves ~50 LOC of
   fixture maintenance. Reasoning: the byte-equivalence test would
   only catch unintended semantic drift in Phase 0; subsequent phases
   intentionally change semantics, so the test would need rewriting at
   each phase anyway.

2. **No standalone `RefResolver` class (per Decision 4).** Confirmed
   — the methods on `AnalysisContext` carry the resolution policy.
   Adding a separate class would double the abstraction count.

3. **Phased rollout collapsed to single coordinated commit.** The plan
   proposed Phase 0 (refactor) → A (cost) → B (parameters) → C
   (template). In practice the changes are small enough to ship as one
   coordinated change because:
   - The new `AnalysisContext` is independent of any phase's logic.
   - Each phase's production change is < 20 LOC.
   - The full test suite catches cross-phase regressions in one pass.
   The phased rollout would have been the right call for a higher-risk
   refactor; the actual delta is small enough that a single commit
   minimizes review overhead.

4. **`cost_data_source` 4-state implemented; renderer annotation
   surfaces only `(trace)` / `(trace_partial)` per state**, not all 4.
   `"recomputed"` is the default — annotating it would clutter
   greenfield output. `"unavailable"` collapses to `"unavailable"` in
   `_format_cost` (the cost itself is None upstream). Cleaner than
   per-state suffix.

5. **`_aggregate_optimized_cost` for the no-declared-subset path uses
   `_per_call_current_cost_recomputed` directly** (NOT
   `_per_call_current_cost`). Critical insight: optimized cost is
   HYPOTHETICAL (what would the cost be IF this row had no caching
   declared). The trace's recorded cost reflects what was paid WITH
   caching, so honoring it here would make `optimized < current`
   impossible to observe for already-cached runs (defeats the purpose
   of the optimization projection).

### Critical insights

1. **The cost-tier 4-state is load-bearing.** Pre-fix the analyzer
   silently recomputed when the trace had a real cost — agents reading
   `current_cost: $0.0032` couldn't tell whether the figure was a
   projection or what the workflow paid. Post-fix the tier label
   distinguishes `"trace"` (real, high confidence) from `"recomputed"`
   (projection, medium confidence) from `"trace_partial"` (mix, with
   at least one unpriced model). The renderer annotation `(trace)` /
   `(trace_partial)` surfaces this directly in the summary so agents
   see fidelity at a glance.

2. **Heterogeneous batch rows need a separate code path for recorded
   cost.** They can't be priced as one model so they're excluded from
   the `priced_rows` projection pipeline — but if the trace recorded
   a cost, ignoring it produces an under-estimate of `current_usd`.
   `_partition_rows` accumulates `heterogeneous_recorded_cost` in a
   parallel pass; `_compute_current_usd` adds it to the priced-rows
   sum. Sets `partial=True` so the renderer shows the appropriate
   confidence marker.

3. **Workflow-input refs need parameters precedence; node-output refs
   need memo-only.** This asymmetry mirrors runtime: workflow inputs
   come from the user at runtime; node outputs come from prior
   execution. Mixing the two — letting memo override parameters for
   workflow inputs — would break the load-bearing principle that the
   agent's CURRENT question wins. `AnalysisContext.resolve_ref_value`
   enforces this via `if root in declared_inputs: parameters first`.

4. **Empty-value normalization (Test 9 mutation contract).** The
   `_normalize_empty` helper returns None for empty string / dict /
   list. Without it, an agent passing `--inputs context=""` would see
   `cacheable_tokens=0` with `data_source=parameters` — looks like "we
   measured it and got 0" when actually we have no data. Returning
   None pushes the caller to Tier 4 unavailable — honest signal.

5. **Resolved-prompt tokenization only matters at Tier 3 (estimator).**
   Tier 1 (trace) and Tier 2 (memo) read tokens directly from the
   recorded data; the prompt template is irrelevant. Track C's
   resolved-prompt path fires when there's no trace AND no memo data
   for the LLM node's own ID — i.e., greenfield with `--inputs`
   covering the referenced refs. The `estimator-partial` label tells
   agents when resolution was incomplete (some refs left unresolved).

6. **Backward-compat shim on `_estimate_ref_tokens` / `_latest_value_for_ref`
   saves ~5 monkeypatch site updates.** When `ctx is None`, helpers
   fall back to legacy memo-only resolution. Existing tests at
   `test_cache_analysis_per_id_emission.py` (5 monkeypatch sites) work
   unchanged. The shim is the ONLY production code with `ctx=None`
   handling — production callers always thread ctx via `analyze()`'s
   single construction site.

### Verification

- **6,057 tests passing** (was 6,049 + 8 new); `make check` clean.
- `test_plan_drift.py` 33/33 ✓; `test_prompt_cache_hash.py` 15/15 ✓
  (golden baseline, DD#19).
- **Gemini smoke re-verification** (the canonical bug fixtures):
  - RUN1 trace ($0.00210488 actual paid):
    `summary.current_cost_per_run_usd = 0.00210488` ✓ (was $0.0032,
    53% over).
  - RUN2 trace ($0.00067772 actual paid):
    `summary.current_cost_per_run_usd = 0.00067772` ✓ (was $0.0032,
    240% over).
  - Per-call rows show `cost_data_source: "trace"`; `cost_usd` matches
    individual `llm_call.cost_usd` from each trace event.
  - Greenfield + `--inputs context=<5000-token>`: `cacheable_data_source:
    "parameters"`, `cacheable_tokens_estimated: 1376` ✓ (was null —
    Tier 4 unavailable pre-fix).

### Open hedged claims and verifications still pending

- **NEEDS VERIFICATION (Stage 2.1 — song-creator standalone)**: now
  meaningful per acceptance criterion 8 (Stage 2.1 song-creator
  becomes meaningful with the cost-projection fix). Run a real
  song-creator fixture with `## Cache` declared and verify the
  projection matches the actual spend within ±5%.
- **DEFERRED (GH #364)**: 5-walker consolidation. `cost_usd_for_node`
  introduces a 3rd `cached: True` policy (include-at-0.0); the
  documented sync invariant at `trace_report.py:205-206` is now FALSE
  (3 distinct policies, not 1). Filed as v1.x workstream.
- **DEFERRED (GH #365)**: sub-workflow cost rollup. Track A
  intentionally does NOT descend into `sub_workflow_events` (parent
  scope only); the renderer underreports parent cost when sub-workflows
  carry significant LLM spend. Filed as v1.x workstream.

### Open user decisions surfaced

**None.** All design decisions resolved during planning + 4-agent plan
review (review-plan, review-impact-completeness, review-silent-failures,
review-feature-interactions). The phased rollout was collapsed to a
single commit per the deviations note above.

---

## Cost-projection fix follow-up: cached events + missing tests

Self-audit caught one real loose end + three missing tests from the v2
plan's high-value list. Added in a follow-up pass.

### Loose end: cached events returned `(None, "unavailable")` not `(0.0, "trace")`

`AnalysisContext.cost_usd_for_node` only checked `event.llm_call`; cached
events (`cached: True` with no `llm_call` — produced by the runtime's
memoization fast-path at `workflow_trace.py:312`) fell through to
`(None, "unavailable")`. On rerun-within-TTL traces this would force the
recompute fallback to fabricate fictional cost when the actual paid was
$0.

**Fix**: explicit branch at the top of `cost_usd_for_node` returns
`(0.0, "trace")` when the event has `cached: True`, no `llm_call`, and
no batch items. Cached batch items inside a non-cached parent contribute
to `found_any` (priced-at-zero) without inflating the sum — so a partial
batch (some cached, some not) reports trace-tier cost = sum of non-cached
items.

**Refactor**: extracted `_walk_event_for_cost` helper (kept
`cost_usd_for_node` C901 ≤ 10).

### Tests 5, 6, 7 (added)

The first commit shipped Tests 1, 2, 3, 4, 8, 9, 10, 12 (8 of 12 from
the plan). The remaining 3 lock the walker semantics that emerged from
the loose-end fix:

- **Test 5** — Cached events contribute 0.0 (NOT unavailable).
  Defends: dropping the cached-event branch lets recompute fabricate a
  fictional cost.
- **Test 6** — `cost_usd_for_node` does NOT descend into
  `sub_workflow_events`. Defends: adding a recursion would
  double-count sub-workflow cost into the parent.
- **Test 7** — `cost_usd: None` propagates as `"trace_partial"`.
  Defends: without the `has_unpriced` flag, unpriced leaves silently
  contribute 0 and cost reports as `"trace"` (looks fully authoritative
  when it isn't).

### Tests 11 (intentionally skipped)

Phase 0 byte-equivalence regression test from the plan was intentionally
skipped — see prior progress log entry's "Deviations from plan" section.
The existing 6,049 tests cover the regression surface; the only test
that broke through Phase 0 (`test_json_format_version == "2.0"`) was
intentional (additive 2.0 -> 2.1 bump).

### Verification

- **6,060 tests passing** (was 6,057 + 3 new walker tests); `make check`
  clean.
- Mutation-verified each new test by reverting its production branch
  manually before adding the test (cached -> None instead of 0; descend
  -> wrong total; drop has_unpriced -> wrong source label).

---

## Verification specialist pass — 7 manual CLI tests (2026-05-02)

After the cost-projection + loose-end fixes, ran 7 high-leverage manual
tests through the CLI on real-shape data (not just unit-test mocks).

### Tests run

1. **Text renderer cost annotation** — `(trace)` annotation appears
   correctly. ⚠ Pre-existing UX gap surfaced: `_format_cost`'s `:.2f`
   rounds sub-cent costs to `$0.00`. Not a regression (pre-fix
   over-estimates also rounded), but Track A's accurate sub-cent
   figures make it more visible. JSON consumers unaffected.
2. **0-LLM-nodes workflow** — `analyze-cache` doesn't crash; renders
   "Cost data unavailable: workflow has no LLM nodes."
3. **Cached LLM event end-to-end** — synthetic trace matching
   production shape (`cached: true`, no `llm_call`) → CLI reports
   `cost_usd: 0.0`, `cost_data_source: "trace"`. The loose-end fix
   fires through the full pipeline.
4. **Greenfield + `--inputs` through CLI** — Track B fires:
   `cacheable_data_source: "parameters"`. Suggested ## Cache block
   shows real `estimated_savings_usd: 0.0135` (~90% input savings on
   2-LLM workflow with 5000-token shared `${context}`).
5. **Empty-string `--inputs context=""`** — Track B silent-failures
   defense fires: `cacheable_tokens_estimated: null`,
   `cacheable_data_source: "unavailable"`.
6. **Real runtime trace shape** — ran a shell workflow twice;
   second run produced `cached: true` + no `llm_call` events
   (matches the synthetic shape M3 used).
7. **Combined edge cases in one synthetic trace** — priced node
   ($0.01) + cached node ($0.00) + node with sub-workflow
   carrying $99.99 child cost (deliberately absurd to make a
   leak loud). Walker correctly returned $0.015 total — sub-workflow
   excluded. Walker leak would have produced $99.005 (6,600x off).

8. **Regression: lyrics-generator song-creator** — 7 LLM nodes,
   4 opportunities, recommendations preserved. No behavioral break.

### Findings

- **No real regressions** in Track A / B / C or the cached-event
  loose-end fix. All behaviors verified end-to-end through the CLI
  on real-shape data.
- **One pre-existing UX gap** (M1): sub-cent costs render as `$0.00`
  in text mode. Filed for v1.x renderer pass; doesn't block this fix.

### Verification cost

$0. M3 + M7 used hand-written trace JSON files — no LLM calls, no
workflow executions. M6 ran shell-only `echo` workflows locally.
The $99.99 in M7 was a synthetic value chosen to make a sub-workflow
scoping leak loud if it existed (would have produced $99.005 vs the
correct $0.015).

---

## Renderer label fix: "Optimized cost per run" → "Cost without caching" (2026-05-02)

Single-line label rename in `render_text.py` summary block. The underlying
field `optimized_cost_per_run_usd` is the recomputed-no-cache hypothetical,
NOT a goal state — labelling it "Optimized" misled agents reading the text
output: on declared workflows where `current_cost` honors trace, the
"Optimized" value is HIGHER than current (because current already reflects
caching benefits), reading as "the optimized state costs more than current"
which agents could interpret as "don't add caching."

Fix: rendered label "Cost without caching" matches the semantic on every
path (greenfield / declared / Gemini-implicit). Internal variable renamed
to `no_cache_str` for code clarity; load-bearing comment added pointing at
the deeper variable-naming inversion still present (`optimized_*` symbols
across `analyze.py`/`cost_estimation.py` mean "no-cache hypothetical").

The deeper code-naming inversion is flagged in `agent-brief-walker-consolidation.md`
under "Related — cost-projection naming inversion" for the agent picking up
walker consolidation (#364) + sub-workflow cost rollup (#365) to assess.

6,061 tests pass; `make check` clean. No test fixtures pin the rendered
label string, so no test updates required.

---

## TraceTree + sub-workflow rollup plan completion pass (2026-05-02)

Finished the remaining load-bearing pieces from
`fix-plans/tracetree-and-subworkflow-rollup-plan.md` on top of the staged
partial implementation.

### What changed

1. **Phantom-cost suppression**
   - Added workflow-scoped trace execution indexing keyed by
     `(workflow_path, node_id)`.
   - Added `PerCallRow.did_not_execute_in_trace`.
   - Rows that are statically reachable but absent from a workflow that has
     trace data remain visible, but are excluded from cost/projection
     aggregation and render with a `not-executed-in-trace` marker.

2. **Per-workflow parameter views**
   - Child workflow inputs now resolve through the parent workflow's
     `AnalysisContext`, including current root parameters and memo-backed
     parent node outputs.
   - Unresolved child inputs stay unresolved/partial rather than being
     fabricated as empty values.

3. **Workflow-scoped trace/token/cost attribution**
   - Trace LLM payloads are indexed separately from trace costs so events
     without `cost_usd` still provide token/cacheable evidence.
   - Parent/child nodes with the same bare id now keep separate rows, token
     lookup, cost lookup, warning markers, and predicted-key entries.
   - Root-only advisory helpers are explicitly documented as root-editing
     behavior; child edit recommendations are surfaced through drill-in.

4. **Real sub-workflow rollup costs**
   - `summary.sub_workflow_rollup.per_workflow[*].current_cost_usd` is now
     grouped from traced child leaves.
   - `cost_without_caching_usd` is computed from each child workflow's rows.
   - Single-workflow analyses still render `sub_workflow_rollup = null`.

5. **Renderer / agent UX**
   - Text header includes root vs sub-workflow LLM counts.
   - Per-call rows group by workflow with `(called by <node>)` on child
     headings.
   - Text output emits the sub-workflow drill-in section.
   - Cycle, depth, and template-items notes now state that current cost is
     trace-driven and explain the projection coverage gap/remediation.
   - Discrepancy messages include workflow scope.
   - JSON includes `per_call[].workflow_path`,
     `per_call[].did_not_execute_in_trace`, complete rollup costs, and
     `summary.unavailable_models_by_workflow`.

6. **Fixture/test infrastructure**
   - Added committed cache-analysis fixtures under
     `tests/fixtures/cache_analysis/`.
   - Added `tests/shared/trace_fixture_builder.py`.
   - Added a production-shape key-set test against
     `WorkflowTraceCollector`.
   - Added CliRunner integration tests for sub-workflow cost rollup,
     same-id scoped rows, and grouped text/drill-in output.

### Deliberate deviations / trust boundary

- Cycle and template-items committed fixture files were not added as separate
  markdown/json fixtures. Their behavior is covered through cross-workflow
  note text and renderer/unit paths; adding more static files would duplicate
  existing coverage without changing production behavior.
- Suggested-block, padding, and consolidate advisories remain root-only by
  design because they generate edits for the analyzed file's `## Cache` block.
  The renderer now directs agents to run `pflow analyze-cache` on child files
  before making child workflow edits.
- Trace workflow-path attribution still depends on static `cw_result.edges`;
  dynamic/template-items child paths cannot be fully attributed without a
  trace schema change. The output now states this gap explicitly.

### Final trust boundary

- **Verified:** current cost remains trace-driven and includes executed
  sub-workflow costs; projections remain IR-driven; unexecuted traced-child
  rows do not inflate aggregates; parent/child same-node-id rows and
  discrepancy keys are workflow-scoped; renderer/JSON/CLI UX paths are tested.
- **Assumed correct by design:** static workflow-path attribution through
  `cw_result.edges` for non-dynamic sub-workflow calls.
- **Known limitation:** runtime-dynamic template-items child workflow paths
  cannot be statically enumerated; notes explain that current cost remains
  trace-driven while per-call/projection coverage under-covers those rows.

---

## Top-10% cleanup pass — Phase 1 (cleanup & deletions)

Verification of the prior pass surfaced shortcuts that fell short of the
top-10% bar: dead code left behind, backward-compat shims the plan said to
remove still in place, stale "optimized" docstrings, dual `AnalysisContext`
construction paths. This phase is the cleanup commit before the architecture
work in Phases 2-6.

### Critical changes

1. **Workflow-scope contract enforced at producer boundary, not in renderer
   fallback.** New helper `_ensure_workflow_scope(warning_id, node_id,
   context_kwargs)` in `warning_catalog.py` raises `KeyError` if a `cache.*`
   diagnostic carrying a `node_id` is missing `affected_workflow`. The
   renderer fallback `warnings_by_node.get((None, node_path), [])` is gone.
   Same node id in parent and child workflows now MUST be disambiguated at
   the producer side; silent dual-keying via `(None, node_path)` is dead.

2. **Bare-`node_id` lookup fallback in `_predicted_key_for_event` removed.**
   The function now requires `(workflow_path, node_id)` tuple keys and has
   no fallback. Producer (`_flatten_plan_keys`) emits tuple keys
   exclusively; tests that monkeypatched with bare-id maps were updated to
   tuple keys.

3. **`affected_workflow` threaded through every node-scoped producer.**
   Touched: `_per_node_warnings` (cache.below-min-tokens,
   cache.prewarm-no-prefix), `_batch_prewarm_recommendations`,
   `_dynamic_before_static_warnings`, `_opaque_prompt_warnings`. Validator-
   shipped diagnostics (`cache.invalid-on-non-llm`,
   `cache.order-mismatch`) flow through `_cache_validator_findings` which
   now `dataclasses.replace`s each diag to inject `affected_workflow` at
   the analyze-cache integration point — the validator constructors stay
   workflow-agnostic. `PaddingCandidate` gained a `workflow_path` field.

4. **Dead code deleted.** `_walk_event_for_cost` (40 LOC, 0 callers),
   `_accumulate_call_cost`, `_accumulate_child_cost` (24 LOC, 0 callers).
   These were left orphaned when their logic moved into TraceTree.

5. **`AnalysisContext.__post_init__` removed.** Construction is now
   single-path through `build()`. Trace JSON → TraceTree compilation
   happens once at the classmethod, not duplicated in `__post_init__`.

### Deliberate deviation

- **`AnalysisContext` direct construction is not hard-enforced.** The plan
  asked for `__post_init__` sentinel or class-rename. Verified zero callers
  use direct construction (production OR tests, all flow through `build()`),
  so the sentinel would defend against a non-existent caller. Docstring
  documents the failure mode (passing raw `trace_data` directly to
  `__init__` produces `ctx.trace=None`) and the future hardening path.

### Test verified manually

`test_make_diagnostic_node_id_without_affected_workflow_raises` is the
guard's defense. Manually verified: comment out the
`_ensure_workflow_scope(...)` call in `make_diagnostic` → test fails with
`Failed: DID NOT RAISE <class 'KeyError'>`. Restore → passes.

### Test fidelity fix

`test_cache_discrepancy_missing_per_cause_required_key_raises` previously
used `ttl_expiry` whose per-cause required key is `affected_workflow` —
which is now ALSO enforced by the workflow-scope guard. The test still
raised `KeyError`, but at the wrong check. Switched to `chunk_skipped`
(per-cause key is `skipped_chunk`) with `match="skipped_chunk"` so the
test name now matches what's verified.

### Insights worth preserving

- **The plan's "vestigial top-level `event['events']` recursion" claim was
  wrong.** `trace_report._compute_event_cost` IS called on batch-item dicts
  (which lack `node_id` and store children under `"events"`, not
  `"sub_workflow_events"`) — see `_find_notable_items` and `_build_node_summary`
  callers. Phase 2 needs an explicit `cost_for_batch_item(item)` entry on
  TraceTree to kill the shape-sniff cleanly.

- **Validator producers are workflow-agnostic by design.**
  `_make_invalid_on_non_llm_diagnostic` and `_make_order_mismatch_diagnostic`
  in `core/workflow/data_flow.py` are reused by compile-time and
  pre-execution validation paths. Adding `workflow_path` parameters to those
  constructors would have polluted unrelated call sites. The
  `dataclasses.replace` enrichment at the analyze-cache integration site is
  the minimal-blast-radius fix.

- **The renderer fallback was the symptom, not the cause.** The real bug
  was producers forgetting to thread workflow_path. Removing the fallback
  forced producers to take responsibility. Top-10% rule confirmed: enforce
  contracts at the producer boundary, not by patching every consumer.

### State after Phase 1

- 6084 tests pass (was 6082 — added `test_make_diagnostic_node_id_without_affected_workflow_raises`
  and `test_make_diagnostic_workflow_level_finding_does_not_require_affected_workflow`).
- `make check` clean (ruff, ruff-format, mypy 201 files, deptry).
- `test_plan_drift.py` 33/33; `test_prompt_cache_hash.py` 15/15 golden baseline.
- Net code change: ~80 LOC deleted (dead helpers), ~25 LOC added (guard +
  threading), ~15 producer call sites + ~25 test fixture sites updated.

### Remaining (Phases 2-6)

Phase 2: single TraceTree primitive — consolidate `_iter_trace_event_keys`
and `_write_node_files` (a third recursive walker the prior pass missed)
into `TraceTree.walk()`. Add explicit `cost_for_batch_item` entry. ~15
new tests covering gaps from the prior 8-test surface.
Phase 4: split `compute_aggregate_costs` into
projections-only + actually-paid; eliminate compute-and-override. Phase 5:
atomic cost primitives + JSON 4.0 (replaces overloaded `current_cost_*`,
`cost_without_caching_*`, `rerun_cost_*` with named atoms). Phase 6: trace
2.2 schema with `workflow_path` stamped per event; deletes the
`cw_result.edges`-threading workaround.

---

## Top-10% cleanup pass — Phase 2 (single TraceTree primitive)

The previous pass left two hand-rolled recursive walkers in production
(`_iter_trace_event_keys` in analyze.py, `_compute_event_cost`'s
`if "node_id" not in event` shape sniff in trace_report.py) plus an
8-test surface where the plan called for ~25. This phase consolidates
the traversal API, kills the shape sniff with a dedicated entry point,
and triples the TraceTree mutation-contract test surface.

### Critical changes

1. **`TraceTree.walk()` is now the universal primitive.** Yields every
   event in the trace tree (top-level, batch_items, batch_items[*].events,
   sub_workflow_events) as a `WalkEvent` carrying the event itself,
   `owner_node_id` (closest top-level/batch parent's id), `tier`, and
   optional `workflow_path` threaded via `edges`. `iter_llm_leaves`
   becomes a one-line filter: `(we for we in walk(...) if we.has_llm_call)`.
   Single recursion implementation; cached-subtree skip and workflow_path
   threading are kwargs.

2. **`WalkEvent` replaces `LlmEventLeaf` as the public type.**
   `LlmEventLeaf = WalkEvent` aliased for backward compat — runtime
   shims and analyze-cache shims continue to work unchanged. Renamed
   because the type is no longer LLM-specific (walk() yields shell, code,
   etc. events too); `has_llm_call` property distinguishes.

3. **`cost_for_batch_item(item)` is the dedicated batch-item entry.**
   Batch items have a different shape from real events (lack top-level
   `node_id`; sub-events stored under `events` not `sub_workflow_events`).
   Previously the trace_report `_compute_event_cost` function used
   `if "node_id" not in event` to shape-sniff at the call site; now
   the shape difference is contained at the TraceTree layer. The
   trace_report split mirrors: `_compute_event_cost` is for real events,
   `_compute_batch_item_cost` is for batch items. Four production
   call sites (`_find_notable_items` ×2, `_build_items_table`,
   `_append_batch_stats`) updated.

4. **`_iter_trace_event_keys` deleted.** The hand-rolled recursive walker
   in `analyze.py` that yielded `(workflow_path, node_id)` pairs was a
   policy duplication. Replaced with a single 4-line loop over
   `tree.walk()` inside `_build_trace_execution_index`. Same recursion
   policy (descend sub-workflows, descend cached, edge-threaded
   workflow_path) — just the shared one.

5. **TraceTree test surface tripled.** From 8 tests → 24 tests. New
   tests cover the gaps the previous plan called out:
   - `walk()` yields non-LLM events (defends "filter at walk level"
     mutation that would break `_iter_executed_keys`).
   - `walk()` does NOT recurse into top-level `event["events"]` (defends
     vestigial-branch reintroduction).
   - `walk()` assigns `owner_node_id` for batch items to the parent
     (defends drift in attribution to item's own id).
   - `walk()` skips cached subtrees entirely when `descend_cached_subtrees=False`
     (defends "skip leaf, recurse into children" partial-skip mutation).
   - `iter_llm_leaves` skips non-LLM events (filter contract).
   - `event_for(requires_llm_call=True)` skips non-LLM events with the
     same node_id — review-plan-C2 multi-event-per-node-id contract.
   - `cost_for_node` priced/unpriced/partial-batch/missing-node tiers.
   - `cost_for_batch_item` recurses into `events` and short-circuits
     for cached items.
   - `total_cost(include_cached=True)` includes cached priced-zero leaves.
   - Edge-based workflow_path threading on walk() (preflight for the
     Phase 6 per-event field).
   - `LlmEventLeaf is WalkEvent` alias identity.

### Tests verified manually

Three tests manually verified by reverting the production line each
defends:

- `test_cost_for_node_returns_unavailable_for_missing_node`: revert
  the `(None, "unavailable")` return to `(0.0, "trace")` in
  `cost_for_node` → fails with a phantom-zero assertion mismatch.
- `test_cost_for_batch_item_recurses_into_events`: replace the
  `events` recursion loop with `for sub_event in []:` →
  ``cost_for_batch_item`` returns `(None, "unavailable")` instead
  of `(0.10, "trace")` → both the unit test AND the trace_report
  test fail.
- `test_walk_does_not_recurse_into_top_level_event_events_field`:
  inject a top-level `event["events"]` recursion into walk() →
  stray inner-llm leaf yielded → `len(walked) == 2` instead of `1`
  → assertion fails.

### Insights worth preserving

- **`_write_node_files` was NOT migrated.** It's a recursive walker but
  its shape doesn't compose with `walk()` — it builds a directory
  hierarchy keyed by container vs leaf events, and each recursion
  passes a different `parent_dir` (hierarchical state). Flattening
  it over `walk()` would lose the directory structure. Per the plan's
  doc: "For one-level reads (immediate children of a single event)
  direct dict access is allowed and preferred. The walker primitive is
  for recursive traversal across the tree shape; flat per-event work
  doesn't need it." `_write_node_files` is structural-recursion, not
  traversal-recursion — staying recursive is the right shape.

- **Top-10% rule reconfirmed:** when consolidating walkers, the
  consolidation MUST yield the universal shape (every event), not
  just the LLM-only shape. Phase 1's `iter_llm_leaves` was correct
  for cost summation but couldn't replace `_iter_trace_event_keys`
  which needed every event for the executed-keys index. The walker
  has to be the universal primitive; filters compose on top.

- **`cost_for_batch_item` validates the dedicated-entry-point pattern.**
  Two different shapes (real event vs batch item) calling into the
  same `cost_for_event` with shape-sniffing was the smell. Two
  named entry points where each's docstring explains the input shape
  is the top-10% answer. Same data flow under the hood; the boundary
  carries the shape contract.

### State after Phase 2

- 6100 tests pass (was 6084 — 16 new TraceTree tests, 1 pre-existing
  test renamed/refactored to use `_compute_batch_item_cost`).
- `make check` clean (ruff, ruff-format, mypy 201 files, deptry —
  pre-existing 41 ruff errors all in unrelated test files; Phase 2
  introduced zero new ones).
- `test_plan_drift.py` 33/33; `test_prompt_cache_hash.py` 15/15.
- Net code change: ~120 LOC added (walk() + WalkEvent + cost_for_batch_item +
  16 tests), ~60 LOC deleted (`_iter_trace_event_keys`, the `if "node_id"
  not in event` branch, the `_has_any_cost_data` helper that was only
  needed for the shape-sniff). Reduced complexity at the call sites.

---

## Top-10% cleanup pass — Phase 4 (cost computation simplification)

The previous phase consolidated trace traversal and wired mutation testing
into CI. Phase 4 takes the next step: split ``compute_aggregate_costs`` into
two functions, each with one job, and eliminate the compute-and-override
pattern in ``_build_summary``. Heterogeneous-batch handling stops flowing
as a flag-passed-everywhere tuple — projections simply exclude it because
heterogeneous cost is trace-driven, not projected.

### Critical changes

1. **``compute_aggregate_costs`` split into two functions**:

   - ``compute_projections(rows, *, output_tokens_by_node, ttl)`` —
     IR-driven hypothetical math. NEVER reads ``row.cost_usd``. Returns
     ``ProjectionBreakdown`` with new ``no_cache_hypothetical_usd`` field
     (pure no-cache recompute over all priced rows) plus the existing
     ``cost_without_caching_usd`` (hybrid: no-cache for undeclared +
     with-cache for declared), ``rerun_usd``, savings, partial,
     unavailable_models.

   - ``compute_actually_paid(rows, *, trace=None, edges=None)`` —
     trace-driven recorded cost. Prefers ``TraceTree.total_cost`` (the
     canonical sum, includes sub-workflow descendants) when a tree is
     provided; falls back to summing ``row.cost_usd`` for callers without
     a tree handle. Returns ``ActuallyPaidCost(total_usd, tier)``.

2. **Compute-and-override pattern eliminated.** ``_build_summary``
   previously called ``compute_aggregate_costs`` (which computed
   ``current_usd`` from row.cost_usd path), then overrode it with
   ``ctx.trace.total_cost(...)`` when a trace existed. Post-Phase-4: the
   summary calls both new functions ONCE; ``current_cost`` is set ONCE
   from the right source (actually-paid if trace contributed, else
   no-cache hypothetical). No value computed-then-thrown-away.

3. **Heterogeneous batch handling simplified.** The old
   ``_partition_rows`` returned a 4-tuple
   ``(priced_rows, unavailable_models, heterogeneous_recorded_cost,
   has_heterogeneous_recorded)`` because the old ``current_usd`` mixed
   actual-paid + projection. With the projection/actually-paid split,
   heterogeneous rows simply don't flow through projections (we can't
   price them as one model). Their actually-paid cost surfaces via
   ``compute_actually_paid`` because ``TraceTree.total_cost`` includes
   batch-item descendants. ``_partition_priced_rows`` returns just
   ``(priced_rows, unavailable_models)``. The ``HeterogeneousBatchTotals``
   value object the plan called for is unnecessary — the value object's
   purpose was preserving the flow that's now removed.

4. **``AggregateCostBreakdown`` removed.** Replaced by
   ``ProjectionBreakdown`` and ``ActuallyPaidCost``. Two consumers
   updated: ``_build_summary`` calls both; ``_build_sub_workflow_rollup``
   only needs projections (it sources actually-paid from the trace
   execution index it builds separately).

5. **Dead helpers removed.** ``_per_call_current_cost`` (the old branch
   that read ``row.cost_usd`` and fell back to recompute),
   ``_compute_current_usd``, ``_empty_priced_rows_breakdown`` —
   deleted. Their work is now done in the natural composition of
   ``compute_projections`` and ``compute_actually_paid``.

6. **``_per_call_current_cost_recomputed`` renamed to
   ``_per_call_no_cache_cost``** to match its actual semantic. The new
   name reads itself; future contributors don't have to chase docstrings
   to learn what "current" meant pre-Track-A.

### New tests (Phase 4 contract surface)

Three new tests cover the split itself:

- ``test_actually_paid_sums_row_cost_usd_when_set`` — the row-fallback path
  in ``compute_actually_paid`` (replaces the old
  ``test_current_cost_returns_recorded_cost_when_set`` whose contract moved
  to the new function).
- ``test_actually_paid_returns_unavailable_when_no_rows_have_cost_usd`` —
  greenfield contract: no row has ``cost_usd`` → ``(None, "unavailable")``.
- ``test_heterogeneous_batch_cost_surfaces_via_actually_paid`` — replaces
  ``test_heterogeneous_batch_cost_surfaces_in_current_usd``. Phase 4 makes
  heterogeneous-cost surfacing a property of ``compute_actually_paid``
  (where it belongs) rather than the projection function.
- ``test_heterogeneous_rows_excluded_from_priced_projections`` — defensive
  guard that heterogeneous rows are skipped BEFORE the pricing lookup, so
  ``model = ""`` never registers as an "unavailable model".

### Insights worth preserving

- **The plan's HeterogeneousBatchTotals value object was unnecessary.**
  Plan suggested wrapping the heterogeneous cost in a frozen dataclass and
  flowing it through the pipeline. Implementation showed that the cleaner
  fix is to NOT flow it through projections at all — ``TraceTree.total_cost``
  in actually-paid handles it. Top-10% rule: when refactoring, ask "does
  this need to flow at all?" before reaching for value objects.

- **The waste-and-pick pattern is a yellow flag for missing abstractions.**
  Pre-Phase-4: ``_build_sub_workflow_rollup`` called
  ``compute_aggregate_costs`` and only used ONE field
  (``cost_without_caching_usd``) of the seven returned. That's the
  signature of "this function does too much." Splitting into projections
  and actually-paid let each consumer ask for exactly what it needs.

- **Greenfield ``current_cost`` semantics preserved bit-for-bit.** Pre-Phase-4
  greenfield ``current_usd`` was a row-by-row recompute (since no row had
  ``cost_usd``). Post-Phase-4 greenfield ``current_cost`` is
  ``projections.no_cache_hypothetical_usd`` which sums the same recompute
  formula. End-to-end smoke against the gemini-with-cache trace produces
  identical figures (``current=$0.00067772``, ``cost_without_caching=$0.00229301``).
  The "compute-and-override" pattern was extra work, not extra capability.

### State after Phase 4

- 6102 tests pass (was 6100 + 3 new + 1 renamed).
- ``make check`` clean (ruff, ruff-format, mypy 201 files, deptry).
- ``test_plan_drift.py`` 33/33; ``test_prompt_cache_hash.py`` 15/15.
- 41 pre-existing ruff errors in test files unchanged.
- End-to-end smoke (gemini-with-cache + parent-child fixture) produces
  identical cost figures vs pre-Phase-4.
- Net code change: ``cost_estimation.py`` reduced from 506 → 553 LOC (fewer
  internal branches, but more docstring + the new ``compute_actually_paid``
  function). Net reduction in cyclomatic complexity at consumer sites.

### Remaining (Phases 5-6)

Phase 5: atomic cost primitives. Replace ``current_cost_per_run_usd`` /
``cost_without_caching_usd`` / ``rerun_cost_per_run_usd`` with named atomic
primitives (``actually_paid_usd`` / ``no_cache_hypothetical_usd`` /
``first_run_with_cache_hypothetical_usd`` / ``rerun_within_ttl_hypothetical_usd``).
JSON 3.0 → 4.0 (breaking field rename). Type-safe ``CostTier`` /
``DataTier`` enums replace stringly-typed labels. The ``no_cache_hypothetical_usd``
field added in Phase 4's projection breakdown propagates to ``AnalysisSummary``
in Phase 5. Phase 6: trace 2.2 schema with per-event ``workflow_path``;
deletes the ``cw_result.edges`` threading workaround.

---

## Top-10% cleanup pass — Phase 5 (atomic cost primitives + JSON 4.0)

The previous phases consolidated traversal (Phase 2) and split cost
computation into projections + actually-paid (Phase 4). Phase 5 takes
the next step: replace the three overloaded cost fields on
``AnalysisSummary`` with five atomic primitives that each carry one
meaning regardless of greenfield/trace context. JSON consumers see a
breaking 3.x → 4.x bump; the renderer composes context-aware
presentation by selecting which atoms to display.

### Critical changes

1. **``AnalysisSummary`` cost fields replaced with atomic primitives.**

   - **Removed**: ``current_cost_per_run_usd`` (overloaded — meant
     "actually paid when trace exists, no-cache hypothetical otherwise"),
     ``cost_without_caching_usd`` (HYBRID — no-cache for undeclared rows
     + with-cache first-run for declared rows; the label said "without
     caching" but the value included cache-write costs for declared rows),
     ``rerun_cost_per_run_usd``.
   - **Added**: ``actually_paid_usd: float | None`` (trace-driven; ``None``
     for greenfield), ``actually_paid_tier: CostTier`` (``TRACE`` /
     ``TRACE_PARTIAL`` / ``UNAVAILABLE``), ``no_cache_hypothetical_usd``
     (pure no-cache recompute baseline), ``first_run_with_cache_hypothetical_usd``
     (first-run projection that honors declared ``prompt_cache:``),
     ``rerun_within_ttl_hypothetical_usd``.

   Each field has ONE meaning. Agents reading any single primitive know
   what it represents independent of context.

2. **``SubWorkflowRollupEntry`` mirrors the same atoms.** Removed
   ``current_cost_usd`` and ``cost_without_caching_usd``; added the four
   atomic primitives at child-workflow scope. JSON output emits all four
   per child entry.

3. **``ProjectionBreakdown`` field renames in
   ``cost_estimation.py``**: ``cost_without_caching_usd`` →
   ``first_run_with_cache_hypothetical_usd``; ``rerun_usd`` →
   ``rerun_within_ttl_hypothetical_usd``. The semantic-match names
   eliminate the naming confusion ("the field said 'without caching' but
   the math included cache writes for declared rows").

4. **``CostTier`` ``StrEnum`` added** in ``cost_estimation.py``. Closed
   catalog (``TRACE`` / ``TRACE_PARTIAL`` / ``RECOMPUTED`` /
   ``UNAVAILABLE``); type-checked at production sites; serializes as the
   same string value (zero JSON impact). ``ActuallyPaidCost.tier`` field
   re-typed to ``CostTier``.

5. **Compute-and-override eliminated end-to-end.** Pre-Phase-5
   ``_build_summary`` had branching that picked ``actually_paid.total_usd``
   OR ``projections.no_cache_hypothetical_usd`` into a single overloaded
   ``current_cost`` field. Post-Phase-5 the summary populates each atom
   independently — no branching, no overload. The savings-percentage
   anchor (the denominator for ``savings_pct_first_run`` /
   ``savings_pct_rerun``) is derived locally as
   ``actually_paid.total_usd if not None else projections.no_cache_hypothetical_usd``
   — preserving the pre-Phase-5 percentage semantic without baking
   "current cost has two meanings" into a stored field.

6. **JSON 3.0 → 4.0 (breaking).** ``JSON_FORMAT_VERSION`` and
   ``JSON_FORMAT_VERSION_MAJOR`` bumped. Module docstring 4.0 entry
   documents the field-rename + atomic primitive contract. MCP tool
   docstrings (``execution_tools.py``, ``execution_service.py``) updated
   in lockstep.

7. **Renderer composes context-aware presentation from atoms.**
   ``_render_cost_block(s)`` dispatches on ``actually_paid_usd is not None``
   AND on ``aggregate_savings_first_run_usd > 0``:

   - **Trace path** (``actually_paid`` set): emits ``Actually paid (trace)``
     + ``Cost without caching`` + ``Cost on rerun (within TTL)``.
   - **Greenfield with declared cache** (savings > 0): emits ``Cost
     without caching`` + ``Cost on first run (cache)`` + ``Cost on rerun
     (within TTL)``.
   - **Greenfield without declared cache** (savings ≤ 0 / None): emits
     ONE ``Cost per run`` line — all three projection atoms collapse to
     the same number when no row has ``prompt_cache:`` (cacheable=0).
     Three identical lines would be noise.

   The "compute-and-override" smell on the renderer side is also gone —
   each path renders only the lines that carry signal for that context.

### Insights worth preserving

- **The ``current_cost`` overload was the bug class behind the previous
  rename**. Pre-Phase-5 ``current_cost_per_run_usd`` meant three
  different things depending on context (greenfield-no-trace = full
  price; greenfield+trace = honored implicit caching; declared+trace =
  honored explicit caching). The Phase 4 commit's "compute-and-override"
  was the symptom — production code had to ask "is there a trace?"
  before knowing what ``current_cost`` meant, then patch it. Phase 5
  removes the overload. The renderer asks the same question explicitly
  but at the seam where context-aware presentation belongs (rendering),
  not where the data is computed.

- **``no_cache_hypothetical_usd`` as the "honest baseline" pattern.**
  Pre-Phase-5 ``cost_without_caching_usd`` was a HYBRID — it included
  cache-write costs for declared rows. The label was misleading; the
  field name was misleading. Top-10% rule: when a data field's name
  doesn't match its computed value, the fix is ALWAYS to make the value
  match the name (split into atomic primitives), never to update the
  label and live with the drift.

- **Renderer dispatch as the seam for context-aware presentation.**
  ``_render_cost_block`` is the SINGLE function that decides "what should
  the agent see?" by inspecting atoms. Adding a new presentation context
  (e.g., a 4th branch for trace+no-declared-cache) means adding one
  helper + one branch — no upstream data-model change. Pre-Phase-5 the
  upstream had to encode the same dispatch by overloading
  ``current_cost``; cross-cutting changes touched both the
  ``AnalysisSummary`` shape AND the renderer.

- **The factory rewrite (``_make_analysis``) is a forcing function.**
  Test fixtures with ``current=, optimized=`` knobs were the tip of the
  iceberg — they exposed how few tests cared about exact atom-level
  semantics vs how many tests just wanted "two cost numbers to render."
  Replacing the knobs with atomic-primitive args (``actually_paid``,
  ``no_cache``, ``first_run_with_cache``, ``rerun``) makes the test
  intent visible at the call site. Future test authors reading the
  fixture see the primitive vocabulary, which prevents the original
  drift from ever creeping back.

### State after Phase 5

- 6102 tests pass (no test count change vs Phase 4 — atomic primitive
  tests replaced/renamed older ones in place).
- ``make check`` clean (ruff, ruff-format, mypy 201 files, deptry).
- ``test_plan_drift.py`` 33/33; ``test_prompt_cache_hash.py`` 15/15.
- 41 pre-existing ruff errors in test files unchanged (Phase 5 added
  zero new ones).
- End-to-end smoke (parent-child fixture):
  - ``format_version: "4.0"``;
  - ``summary.actually_paid_usd: 0.15`` with ``actually_paid_tier: "trace"``;
  - all four hypothetical projection atoms separately populated;
  - sub-workflow rollup entry carries the same atoms at child scope.
  Text renderer emits the trace-path layout
  (``Actually paid (trace): ~$0.15 (trace)`` + ``Cost without caching:
  ~$0.01`` + ``Cost on rerun: ~$0.0100``).
- Net code change: ``AnalysisSummary`` dataclass +~30 LOC (atomic
  primitive fields with docstring), ``SubWorkflowRollupEntry`` +~10 LOC
  (4 atoms vs 2), ``_build_summary`` -~20 LOC (no compute-and-override),
  renderer +~80 LOC (context-aware composition with explicit named
  helpers vs one monolithic block), tests +~120 LOC (factory rewrite
  + new atom-level assertions). Net JSON schema: 7 fields renamed/added
  on ``summary``; 4 fields renamed on ``sub_workflow_rollup.per_workflow[]``.

### Remaining (Phase 6)

Phase 6: trace 2.2 schema with per-event ``workflow_path``. Stamps
``workflow_path`` per event during ``record_node_execution`` so the
analyzer doesn't have to thread ``cw_result.edges`` through ``TraceTree``
to attribute leaves to their child workflow. Deletes the
``edges``-threading machinery and the ``_edge_child_paths`` helper.
Generated fixture test (runs a workflow, snapshots the trace, asserts
byte-equality) replaces the hand-crafted ``parent-child-trace.json`` so
fixture drift becomes a CI failure rather than a silent test pass.

---

## Top-10% cleanup pass — drift-detection generator + Phase 6 deferred (2026-05-02)

After Phase 5 landed, audit of the GitHub issues filed against this branch
showed two were substantively resolved by Phases 1-5 (#364 walker
consolidation; #365 sub-workflow cost rollup) and that no remaining open
issue required the full Phase 6 schema bump. The forward-compat investment
of trace 2.2 (per-event ``workflow_path`` stamping + delete edges-threading
machinery) was filed as a v1.x issue (#366) instead of shipped now. The
ONE Phase 6 piece that pays back independently — generated fixtures for
drift detection — landed in this commit.

### What shipped

1. **``tests/fixtures/cache_analysis/_generate.py``** (NEW). Programmatic
   generator for both committed cache-analysis trace fixtures
   (``parent-child-trace.json`` and ``parent-child-erroring-trace.json``)
   using ``TraceFixtureBuilder``. Cost figures encoded at the top of the
   module (load-bearing for downstream test assertions: ``actually_paid_usd
   == 0.15`` for the success trace, ``== 0.12`` for the erroring trace).
   Run as a script (``python -m tests.fixtures.cache_analysis._generate``)
   to regenerate after intentional shape changes.

2. **``TraceFixtureBuilder`` extended** with ``workflow_event(success=,
   error=)`` and ``trace(workflow_name=, final_status=, failed_node_ids=)``
   knobs so the builder can express the failed-trace shape end-to-end.
   Defaults preserve previous behavior (success/zero-failures) so existing
   call sites are unchanged.

3. **Committed JSON fixtures regenerated** via the generator. Cost values
   and event shape preserved bit-for-bit; incidental
   ``node_output.response`` / ``llm_prompt`` / ``llm_response`` strings
   reduced to the builder's defaults (don't affect any test assertion —
   analyze-cache reads cost/token fields, not these passthrough strings).

4. **``test_committed_cache_analysis_fixtures_match_generator_output``**
   added to ``tests/test_core/test_trace_tree.py``. Closes the third link
   of the drift-detection chain:

   - ``WorkflowTraceCollector`` adds field → existing
     ``test_trace_fixture_builder_matches_workflow_trace_collector_shape``
     fails (chain link 1)
   - ``TraceFixtureBuilder`` updated → generator output changes → new test
     fails (chain link 2)
   - Hand-edits to committed JSON → diverge from generator → new test fails
     (chain link 3)

   Manual mutation verification: changing a single ``cost_usd`` value in
   the committed JSON produced ``AssertionError`` with a clear "drifted
   from generator output. Run: python -m
   tests.fixtures.cache_analysis._generate" remediation message.

### Issues closed

- **#364** (Refactor: consolidate trace-event walkers with divergent
  ``cached`` filter behavior) — closed with detailed reference to the
  Phase 1-2 consolidation through ``TraceTree.walk()``. Each walker is
  now a 3-line accumulator over the shared primitive; cached-event policy
  is a single kwarg; workflow-path threading is a single kwarg.

- **#365** (Feature: surface sub-workflow LLM costs in pflow analyze-cache
  parent-scope output) — closed referencing Phases 2a + 5. Implementation
  went further than the issue's proposed minimal ``sub_workflow_cost_usd:
  float`` field — sub-workflow rollup carries the full atomic-primitive
  cost vocabulary at child scope (``actually_paid_usd``,
  ``no_cache_hypothetical_usd``,
  ``first_run_with_cache_hypothetical_usd``,
  ``rerun_within_ttl_hypothetical_usd``).

### Issue filed (deferred work)

- **#366** (Trace 2.2: stamp workflow_path per event; delete
  cw_result.edges threading workaround) — captures the deferred Phase 6
  work as a v1.x forward-compat investment. Documents the gap (incomplete
  attribution for runtime-dynamic / template-items batch sub-workflows),
  the scope (~5 hours, ~200 LOC), the fallback strategy for 2.1 trace
  backward-compat, and cross-refs to closed #364 / #365 + open #360
  (which #366 is potentially a substrate for).

### Why Phase 6 was deferred

The user's standing rule "we cannot defer things that SHOULD be working"
filtered the analysis: Phase 6's deliverables are forward-compat
investment plus internal cleanup, not a fix for anything currently broken.

- Sub-workflow cost rollup (#365) ships correct numbers without per-event
  ``workflow_path`` because ``cw_result.edges`` covers static-IR sub-workflow
  attribution and ``actually_paid_usd`` is trace-driven across all
  descendants regardless of attribution.
- Walker consolidation (#364) ships through ``TraceTree.walk(edges=...)``;
  the ``edges`` kwarg is the workaround Phase 6 would remove, but it's
  contained and documented.
- The runtime-dynamic / template-items attribution gap is documented at
  the per-call notes layer (``"items: ${list} resolves at runtime;
  sub-workflow rows for these items are not in the per-call table"``) and
  does NOT silently produce wrong numbers — ``actually_paid_usd`` is honest.
- Trace 2.x → 2.2 schema bump touches every consumer of trace events
  (~15 sites including ``trace_report.py``, runtime tests, analyzer);
  doing this work without a user need would be over-engineering.

The drift-detection generator landed BECAUSE it pays back independently:
~30 LOC + 1 test, no schema impact, eliminates a real brittleness vector
(hand-crafted JSON drifting from production shape).

### Insights worth preserving

- **Ship-or-defer decisions are filtered through the user's principles,
  not by plan momentum.** The Phase 6 schema bump was in the original
  plan's "ship Tiers 1-5" scope but the audit-against-issues showed the
  user-visible benefit was zero today. The generated-fixtures piece was
  pulled out as the only Phase 6 element that pays back independently.
  Top-10% rule confirmed: when a phase's deliverables don't all pay back,
  split the phase rather than ship the bundle.

- **Drift-detection chains compose.** Three tests now form a chain:
  production shape → builder → committed fixture. Each link defends
  the next; breaking any link produces a visible CI failure. The chain
  shape is the point — no individual test is sufficient on its own; the
  composition is.

- **Closing issues with detailed references is documentation.** The two
  close-comments on #364 and #365 cite specific function names, file
  paths, and the resolution mechanism (e.g., ``TraceTree.walk()``
  consolidation; atomic-primitive child-scope rollup). Future contributors
  searching for "walker consolidation" will find the closed issue and
  trace it to the Phase 1-2 implementation. Closed-without-comment is a
  documentation gap.

### State after this commit

- 6103 tests pass (was 6102 + 1 new
  ``test_committed_cache_analysis_fixtures_match_generator_output``).
- ``make check`` clean (ruff, ruff-format, mypy 201 files, deptry).
- ``test_plan_drift.py`` 33/33; ``test_prompt_cache_hash.py`` 15/15.
- End-to-end smoke (parent-child fixture, gemini-with-cache fixture)
  produces identical figures to Phase 5 — drift detector confirms no
  drift.
- Net code change: ``_generate.py`` ~110 LOC NEW; ``TraceFixtureBuilder``
  ~25 LOC additions (additive kwargs); committed JSON fixtures
  regenerated (cost values + shape preserved); 1 new drift test ~35 LOC.

### Remaining

Tracked in #366. Not a blocker for any current pflow user; will be
revisited if/when (a) #360 dynamic-batch undercounting work needs
per-event ``workflow_path`` as substrate, or (b) someone files an issue
about template-items attribution.

---

## Verification-found bugs Phase A + B (2026-05-04)

End-to-end verification of commit ``1fabde31`` found 5 bugs the test suite
missed. Phases A (Bug 4: cacheable_tokens clamp) and B (Bug 5: sub-workflow
discrepancy detection) shipped together. Phases C + D (bugs 1, 2, 3 — UX
+ contract hardening) deferred to a separate commit per the plan's atomic-
commit cadence.

### What shipped

1. **Bug 4 — cacheable_tokens clamp** (``analyze.py:_estimate_row_tokens``).
   The ``min(cacheable, input_tokens)`` clamp was truncating correct
   cacheable estimates (~2391 tokens) down to the prompt-body-only size
   (~4 tokens) when ``## Cache`` chunks were referenced by name in
   ``prompt_cache:`` but not inlined in the prompt body. False
   ``cache.below-min-tokens`` warnings advised agents to remove correct
   ``prompt_cache:`` declarations.

   **Fix:** make the clamp's invariant structurally true — ``input_tokens``
   now equals total LLM-billed tokens (prompt body + cache content). The
   clamp becomes a no-op (kept as defense-in-depth). Greenfield path
   tokenizes each declared chunk via existing ``_estimate_ref_tokens``
   helper. Trace path detects Anthropic-style reporting via
   ``cache_creation > 0`` and sums ``cache_creation + cache_read`` into
   ``input_tokens`` (Gemini/OpenAI fold cache in already, so no double-
   count). Long-term fix: normalize ``billed_input_tokens`` at
   ``llm_client._normalize`` — filed as v1.x follow-up.

2. **Bug 5 — sub-workflow discrepancy attribution** (``analyze.py:
   _predict_cache_keys``). ``cache.discrepancy`` silently skipped LLM nodes
   inside sub-workflows because ``_predict_cache_keys`` consumed
   ``execution/plan.py``'s ``build_plan`` output, and ``build_plan``'s
   ``_force_downstream=True`` mode legitimately can't compute cache_keys
   (parent's upstream state is dirty). The analyzer inherited that
   limitation even when it had all the data it needed.

   **Fix:** decouple analyzer prediction from ``build_plan``. Walk
   ``cw_result.irs_by_workflow`` directly, compile each workflow once, and
   call ``plan_node`` per LLM node against a per-workflow scaffold. This
   is the architectural direction ``cache_render.py`` already documented
   ("third site" comment); the implementation now follows through.

### Critical insights for the next agent

- **The ``compile_workflow + create_planner_shared`` hoist is load-bearing
  for performance.** Initial implementation called ``compile_workflow``
  per LLM node, which is N× worse than the original (which compiled once
  per workflow). The ``_PredictScaffold`` dataclass + ``_build_predict_scaffold``
  + ``_predict_node_with_scaffold`` factor keeps the byte-identity
  contract while compiling once per workflow. Future contributors adding
  a new analyzer prediction primitive should reuse the scaffold pattern,
  not re-implement compile-per-node.

- **The predicate is ``_is_llm_node``, NOT ``_is_llm_with_prompt_cache``.**
  In production, only LLM-with-prompt-cache nodes generate cache events
  (so the discrepancy gate filters them anyway), but synthesized-trace
  tests exercise non-prompt-cache LLM nodes with fake cache_creation
  tokens to test the consumption path. The original ``build_plan``-based
  code predicted for ALL nodes; narrowing to LLM-with-prompt-cache
  silently broke tests. Documented at the predicate.

- **Bug 4 chose to fix ``input_tokens`` semantics, NOT remove the clamp.**
  Removing the clamp re-opens the original Bug C symptom (cacheable >
  input from tokenizer-vs-heuristic mismatch). Fixing the semantic
  premise eliminates Bug 4 AND makes Bug C structurally impossible. Top-
  10% rule: when a data field's name doesn't match its computed value,
  the fix is to make the value match the name, never to weaken the
  invariant downstream.

- **Test pollution via ``monkeypatch.setattr("pflow.runtime.compile_workflow",
  ...)``** is a real gotcha. ``workflow_executor.py`` does
  ``from pflow.runtime import CompilationError, compile_workflow`` at
  module load. If the patch is active during workflow_executor's first
  import, the module's cached binding stays patched FOREVER (monkeypatch
  reverts ``pflow.runtime.compile_workflow`` but not the cached binding
  in workflow_executor's namespace). Symptom: a different test's
  ``runner.run(...)`` call later fires the patched ``_boom`` from inside
  WorkflowExecutor's exec path. **Fix used here:** patch
  ``_build_predict_scaffold`` directly on the analyzer module instead
  of patching the runtime re-export. Future tests that need to inject
  errors at the compile boundary should follow the same pattern (patch
  the consumer's local symbol, not the producer's re-export).

- **Per-workflow input check is now per-workflow, not just root.** Legacy
  ``_predict_cache_keys`` only checked ``if not parameters and
  workflow_ir["inputs"]`` for the root workflow. Child workflows
  silently degraded to defaults, producing predictions that diverged
  from trace's run-time values (false ``key_mismatch`` floods). New
  per-workflow loop checks each workflow's own inputs against its own
  resolved parameters.

### Deviations from the plan

- Plan said "drop ``compile_workflow + build_plan`` from the analyzer
  hot path" via direct use of ``cache_render`` helpers + ``compute_node_cache_key``.
  Implementation kept ``compile_workflow + plan_node`` (per workflow,
  not per node) because byte-identity with runtime is load-bearing
  (test ``test_predict_cache_keys_byte_identical_to_runtime`` defends
  this) and replicating ``compute_node_config`` outside ``plan_node``
  would risk drift. ``build_plan`` is dropped (the source of the bug);
  ``compile_workflow`` is kept because it's the canonical site for
  ``NodeConfig`` instantiation. Net: the plan's spirit ("decouple from
  the planner's BFS-downstream limitations") is preserved; the literal
  helper list is not.

- ``_flatten_plan_keys`` deleted entirely along with its mutation-contract
  test (``test_flatten_plan_keys_preserves_same_node_ids_across_workflow_paths``).
  No production code referenced it after the rewrite. Per CLAUDE.md
  "If you are certain that something is unused, you can delete it
  completely."

- Phase D (Bugs 2 + 3) and Phase C (Bug 1) NOT shipped in this commit.
  Plan called for atomic per-phase commits; A + B were grouped because
  both are correctness fixes and B's tests validate A's behavior (the
  byte-identity test runs through a workflow that exercises both fixes).

### State after Phase A + B

- 6112 tests pass (was 6103 + 9 new: 3 for Bug 4, 4 for Bug 5 via
  ``_predict_cache_keys`` / ``_predict_node_cache_key`` /
  ``_predict_cache_keys_byte_identical_to_runtime`` /
  ``_analyze_cache_emits_discrepancy_for_sub_workflow_node_via_subprocess``,
  plus 2 sanity assertions hoisted from existing tests).
- ``make check`` clean (ruff, ruff-format, mypy 201 files, deptry).
- End-to-end Phase A reproducer verified: workflow with declared
  ``## Cache`` + ``prompt_cache: [context]`` + 19117-char context input
  produces ``input=2395, cacheable=2391, ratio=100%`` (was
  ``cacheable=4`` pre-fix). Zero ``cache.below-min-tokens`` warnings
  (was 1 pre-fix).
- Net code change: ``analyze.py`` +~150 LOC (``_predict_cache_keys`` +
  ``_predict_one_workflow`` + ``_PredictScaffold`` + ``_build_predict_scaffold``
  + ``_predict_node_with_scaffold`` + ``_predict_node_cache_key`` +
  ``_enumerate_compiled_bare_nodes`` + ``_tokenize_declared_cache_chunks``;
  ``_estimate_row_tokens`` +~30 LOC for cache content tokenization);
  -~120 LOC (``_predict_cache_keys`` legacy body + ``_flatten_plan_keys``
  + dedicated test). Tests +~330 LOC (4 new Bug 5 tests, 3 new Bug 4
  tests, refactored 1 existing schema-validation test).

### Remaining

Phase C (Bug 1: ``recommended_actions`` doesn't disambiguate same-node-id
across multi-workflow analyses) and Phase D (Bug 2: ``_ensure_workflow_scope``
accepts ``affected_workflow=None``; Bug 3: stale ``current_cost`` in
``cross_workflow.py:260`` — should be ``actually_paid_usd``). Plan
sections C + D in the verification fix doc.

## Verification-found bugs Phase C + D (2026-05-04)

Phases C and D from
``.taskmaster/tasks/task_159/implementation/fix-plans/verification-bugs-fix-plan.md``
are implemented on top of the staged Phase A + B work.

### What shipped

1. **Bug 1 — recommended-actions workflow scope for per-node findings.**
   ``view_helpers.build_recommended_actions`` now always projects
   ``context.affected_workflow`` into ``RecommendedAction.scope_workflow``
   when it is a non-empty string. This means JSON consumers can dispatch on
   ``(node_id, scope_workflow)`` for same-id nodes in parent/child workflows.
   ``render_text._render_recommended_actions`` renders per-node scope as
   ``<node_id> in <basename>`` when the finding belongs to a different
   workflow from the analyzed root, and keeps the old compact ``<node_id>``
   line for single-workflow/root findings. The ``RecommendedAction`` and JSON
   comments were updated to remove the stale "at most one is set" contract.

2. **Bug 2 — ``affected_workflow=None`` contract hardening.**
   ``warning_catalog._ensure_workflow_scope`` now validates the value, not
   only key presence: node-scoped cache diagnostics require a non-empty string
   ``affected_workflow``. ``None`` now raises ``KeyError`` the same way a
   missing key does.

3. **Bug 3 — stale cost-field note text.**
   ``cross_workflow._maybe_note_template_items_gap`` now says
   ``actually_paid_usd is trace-driven`` instead of the removed
   ``current_cost`` field name. Manual CLI verification also found the same
   note recommended a nonexistent ``analyze-cache --inputs`` flag. That
   adjacent stale remediation was fixed to say "Pass the resolved list as a
   CLI parameter" because ``pflow analyze-cache --help`` shows workflow inputs
   are passed as positional ``key=value`` params.

### Tests added

- ``test_text_recommended_actions_per_node_finding_includes_workflow_scope_in_multi_workflow_analysis``
- ``test_text_recommended_actions_single_workflow_omits_scope_suffix``
- ``test_json_recommended_actions_per_node_finding_carries_scope_workflow``
- ``test_make_diagnostic_node_id_with_affected_workflow_none_raises``
- ``test_template_items_gap_note_uses_real_analyze_cache_cli_param_wording``

### Deviations from the plan

- No production deviation. Tests use direct catalog diagnostics rather than
  full workflow fixtures because the defect lives in the recommendation-view
  projection and renderer, not in analyzer discovery. This keeps the
  regression pinned to the actual integration point with less incidental
  workflow setup.
- ``make check`` was not run verbatim in this sandbox because it shells
  through ``uv``. The repository-local ``pflow-sandbox-testing`` skill says
  ``uv`` can panic before Python starts here. Equivalent checks were run via
  ``.venv`` where possible; pre-commit itself could not initialize because
  the sandbox has no network and the remote hook environment was not cached
  under ``HOME=/private/tmp/pflow-test-home``.

## Verification-found bugs Phase E — follow-ups from b9b2bd26 verification (2026-05-04)

Post-merge verification of commit ``b9b2bd26`` surfaced two follow-up bugs in
the fix itself. Both are surface-level glitches in otherwise-correct fixes —
no architectural rework needed.

### What shipped

1. **Bug 7 — Anthropic cache-read provider detection**
   (``analyze.py:_estimate_row_tokens``). The Bug 4 fix used a value-based
   heuristic ``if cache_creation > 0`` to detect Anthropic-style traces. On
   rerun-within-TTL events (the **most common cached scenario** after the
   first call), Anthropic reports ``cache_creation_input_tokens=0`` and
   ``cache_read_input_tokens > 0`` — the heuristic misclassified these as
   Gemini-style and skipped the cache-portion sum. Result: ``input_tokens``
   artificially shrunk to the non-cache portion, then the clamp truncated
   ``cacheable`` further. The cached path most agents care about reported
   misleading numbers.

   **Fix:** detect provider via model-name prefix using ``detect_provider``
   (already imported, canonical metadata in ``core/llm_providers.py``).
   Anthropic always splits cache from ``input_tokens``; Gemini/OpenAI fold
   it in. The discriminator is the provider, not the cache-creation value.

2. **Bug 6 — ``_attribute_root_cause`` records root, not leaf, workflow path**
   (``analyze.py:_attribute_root_cause``). Cross-workflow ``cache.discrepancy``
   findings were carrying ``affected_workflow=<analyzed root>`` instead of
   the leaf event's workflow. ``setdefault`` at the call site couldn't override
   because ``_attribute_root_cause`` itself populated the field with the wrong
   value. Visible regression on Bug 1's fix: renderer scope-suppression dropped
   the ``in <basename>`` suffix because the ``scope_workflow`` matched the
   analyzed root — agents saw ``review`` instead of ``review in child.pflow.md``
   for sub-workflow discrepancies.

   **Fix:** rename the parameter to ``leaf_workflow_path`` for clarity, thread
   ``leaf_workflow_path or workflow_path`` from the call site so the field
   describes the workflow whose ``## Cache`` block actually needs editing.

### Tests added

- ``test_total_input_tokens_anthropic_cache_read_event_sums_cache_portions`` —
  Bug 7 reproducer: ``cache_creation=0, cache_read=1500`` → expect
  ``input_tokens_estimated=1550``. Pre-fix returned 50.
- ``test_discrepancy_for_sub_workflow_node_carries_child_workflow_path_in_affected_workflow`` —
  Bug 6 reproducer: monkeypatched cross-workflow walker, synthesized trace
  with TTL-expiry on a child LLM node, asserts
  ``diag.context["affected_workflow"]`` equals the child path (not the
  analyzed root) and ``workflow_path_short`` renders correctly.

### Critical insights for the next agent

- **``cw_result.edges`` is not populated for input-less sub-workflow calls.**
  ``cross_workflow.py:_process_one_call`` line 322-335 only emits edges when
  ``params.inputs`` is a non-empty dict. The Bug 6 test caught this when its
  initial setup passed ``inputs: {}`` — edges came back empty, leaf workflow
  path threading silently fell back to the root. Real workflows always pass
  inputs (otherwise the child has no usable parameters), so this rarely
  bites — but it is a structural quirk worth knowing. Filed implicitly:
  edges represent input-flow, not parent→child relationships. Future work
  could decouple them.

- **Provider detection by value is a footgun.** The original Bug 4 fix
  detected Anthropic-style traces by checking ``cache_creation > 0``.
  Cache-read events have ``cache_creation=0`` regardless of provider, so
  the heuristic silently misclassified the most common cached path. Always
  use ``detect_provider(model)`` from ``core/llm_providers.py`` — that's
  what it's for, and it gets cache-creation/cache-read symmetry right by
  construction.

- **Renderer scope-suppression depends on producer-side correctness.**
  Bug 1's renderer suppresses ``in <basename>`` when ``scope_workflow``
  equals the analyzed root. That suppression is RIGHT — we don't want
  ``draft in parent.pflow.md`` cluttering single-workflow output. The
  invariant only holds if producers (warning emitters) record the LEAF
  workflow as ``affected_workflow``, not the analyzed root. Bug 6 was a
  producer-side miss, not a renderer-side miss.

### State after Phase E

- 343 tests pass in cache-analysis subset (was 261 + 2 new).
- ``make check`` clean (ruff, ruff-format, mypy 201 files, deptry).
- End-to-end Bug 6 reproducer verified: cross-workflow discrepancy on
  child node renders ``review in child2.pflow.md`` (was just ``review``).
- End-to-end Bug 7 reproducer verified: Anthropic cache-read trace
  produces ``input=1550`` for the ``review`` row (was ``input=50``);
  cacheable correctly equals 1500 (was 50).
- Net code change: ``analyze.py`` ~10 LOC production change (Bug 7
  predicate replacement + Bug 6 parameter rename + threading); +60 LOC
  tests (2 new tests).

## Verification-found bugs Phase E follow-up — self-audit fixes (2026-05-04)

Self-audit of Phase E surfaced three more loose ends. Bug 9 (analogous to
Bug 6 but for TTL extraction) is the only correctness issue; the other two
are top-10% cleanup. All three are addressed in this commit.

### What shipped

1. **Bug 9 — TTL extraction reads root IR for sub-workflow leaves**
   (``analyze.py:_emit_discrepancy_diagnostics``). Same conceptual shape as
   Bug 6: ``ttl=_extract_cache_ttl(workflow_ir.get("cache"))`` used the
   ROOT analyzed IR for every leaf, including sub-workflow descendants.
   When parent and child declare different TTLs (parent ``ttl: 1h``, child
   ``ttl: 5m``), a child cache_age=600s would be checked against the
   parent's hour-long window and look fresh — no ``ttl_expiry`` attribution
   despite the actual expiry against child's 5m. Agents got the wrong
   remediation hint.

   **Fix:** look up the leaf workflow's IR from
   ``cw_result.irs_by_workflow[leaf_workflow_path]`` (with root fallback
   for top-level events) and pass its cache block to ``_extract_cache_ttl``.
   Mirrors Bug 6's leaf-vs-root principle: the workflow whose ``## Cache``
   block governs the cache is the leaf's, not the analyzed root's.

2. **Provider detection cleanup — data-driven, not predicate-driven**
   (``core/llm_providers.py`` + ``analyze.py:_estimate_row_tokens``). The
   Bug 7 fix used ``provider.name == "anthropic"`` as a hardcoded check.
   Future providers that adopt Anthropic-style split-cache reporting (or
   pflow adding more providers) would each require a code edit.

   **Fix:** added ``ProviderInfo.splits_cache_from_input_tokens: bool =
   False`` field, set ``True`` for Anthropic. The check at the analyzer
   site reads ``provider.splits_cache_from_input_tokens`` directly.
   Top-10% rule: provider behavior tables are data, not predicates.

3. **Stale Gemini test docstring** (cosmetic). The
   ``test_total_input_tokens_gemini_trace_does_not_double_count`` docstring
   said the discriminator was ``cache_creation_input_tokens == 0``.
   Post-Bug-7 the discriminator is the provider's
   ``splits_cache_from_input_tokens`` flag — cache-write vs cache-read
   events have different cache-creation values within the same provider.
   Docstring rewritten to reflect the actual contract.

### Tests added

- ``test_discrepancy_ttl_attribution_uses_leaf_workflows_ttl_not_root`` —
  Bug 9 reproducer: parent ``ttl: 1h``, child ``ttl: 5m``, child trace
  cache_age=600s. Pre-fix produced ``root_cause="unknown"`` (parent's 1h
  said fresh); post-fix produces ``root_cause="ttl_expiry"`` against
  child's 5m TTL.

### Critical insights for the next agent

- **Leaf vs root context is a recurring pattern in sub-workflow analysis.**
  Three sites in ``_emit_discrepancy_diagnostics`` need leaf-scoped lookup:
  predicted_keys (already correct via tuple keying), ``affected_workflow``
  (Phase E Bug 6 fix), and now TTL (Bug 9 fix). When a future feature
  pulls workflow-level config for sub-workflow events, default to leaf
  scope and only fall back to root for top-level events. The pattern:

  ```python
  leaf_ir = cw_result.irs_by_workflow.get(leaf_workflow_path) or workflow_ir
  ```

- **Provider behavior is data, not code.** ``ProviderInfo`` already had
  per-provider env vars and prefix metadata. Cache-token accounting is
  the same kind of static fact — adding it as a field rather than a
  conditional in the analyzer keeps every cross-provider concern in one
  place. Future cache normalization at ``llm_client._normalize`` (the
  filed v1.x follow-up for emitting ``billed_input_tokens`` directly)
  will read this same field.

### State after Phase E follow-up

- 6120 tests pass in full suite (was 6119 + 1 new Bug 9 test).
- 344 tests pass in cache-analysis subset (was 343 + 1).
- ``make check`` clean (ruff, ruff-format, mypy 201 files, deptry).
- End-to-end: mixed-TTL parent/child fixture with cache_age=600s now
  correctly attributes to ``ttl_expiry`` against the child's TTL.
- Net code change: ``llm_providers.py`` +13 LOC (1 new field +
  documentation), ``analyze.py`` ~5 LOC production change (TTL
  leaf-lookup + provider field swap), +75 LOC tests (1 new Bug 9 test +
  docstring update on Gemini test).

## Post-`1fabde31` review pass — methodology and findings (2026-05-04)

After commit `1fabde31` (TraceTree consolidation + sub-workflow rollup +
JSON 4.0 atomic primitives) shipped, a multi-agent review pass surfaced
the bugs that the cleanup commits (`b9b2bd26`, `24a80119`, `158bc8a0`)
addressed. Documenting the methodology here for future agents who
inherit the post-cleanup state.

### Phase 1 — 4-agent code review of commit `1fabde31`

Four specialized review agents ran in parallel against the commit's diff:

- `review-silent-failures` — operations that silently succeed when they
  should fail / produce empty results / propagate stale state
- `review-impact-completeness` — shared patterns modified without
  updating all consumers (the `(workflow_path, node_id)` tuple
  migration, walker consolidation call sites, `affected_workflow`
  threading)
- `review-feature-interactions` — combinations of sub-workflow ×
  heterogeneous batch × cached events × erroring trace × template-items
  × cross-workflow caching
- `review-test-fidelity` — whether tests assert behavior vs
  implementation, fixtures match production shape, regression coverage

### Findings convergence

The cached-cost bug was found INDEPENDENTLY by both `review-silent-failures`
and `review-feature-interactions` from different angles — strong cross-
agent signal. The heterogeneous batch attribution bug was found by
`review-feature-interactions` alone but corroborated by trace-level
evidence in production fixtures.

### Phase 2 — 5-agent investigation pass

Before drafting the implementation plan, five investigation agents
verified assumptions in parallel:

1. **Trace event workflow attribution** — does the trace itself carry
   workflow_path metadata that could replace `cw_result.edges`?
2. **TraceTree cost method callers** — would the proposed unified policy
   break existing semantics?
3. **Production memo-hit trace shape** — load-bearing evidence for the
   cached-cost bug (the gemini-smoke RUN4 fixture proved the shape:
   `cached: true` AND `llm_call.cost_usd: 0.00034006`)
4. **Dead code and cycle bug** — `merge_sub`, `partial_workflows`,
   `_build_parameters_by_workflow` cycle reachability, direct
   `AnalysisContext` constructions
5. **Polish item ROI** — case-by-case KEEP / FIX / SKIP per item

### Critical insight for future planning

**Investigation 1's "trace metadata is sufficient" assertion was
incomplete.** It checked the runtime trace_collector code path but did
not verify what production traces actually contain when read back —
specifically, that `node_params.workflow` stores the RAW IR string
(often a relative path like `./child.pflow.md`) while
`cw_result.irs_by_workflow` is keyed by RESOLVED ABSOLUTE paths.
Pivoting attribution off `node_params.workflow` mismatched the keys
and broke an existing test on first run during Commit 3
implementation.

The correction: future investigations asserting "metadata X is
sufficient" must cite a specific production trace file (path + grep
output) showing the relevant fields with the values used downstream.
The implementer of Commit 3 caught this at runtime and adapted —
`_edge_child_paths` was retained (not deleted as the plan called for)
with an explanatory docstring; trace-metadata pivoting applied only
to `batch_items` where `template_resolutions` carries runtime-resolved
absolute paths.

### Bonus latent bug discovered during implementation

The Commit 3 follow-up surfaced a homogeneous static workflow batch
attribution bug not in the original review's scope. Static
`workflow: ./child.pflow.md` with `batch:` produces `batch_items`
WITHOUT `template_resolutions["workflow"]` (the `workflow:` ref isn't
a template, so `resolve_templates` records nothing). Fixed via a
3-tier priority chain in `TraceTree.walk()`: (1) per-item
`template_resolutions["workflow"]["resolved"]` for heterogeneous
batches, (2) `edges.get(parent_node_id)` for homogeneous static
batches, (3) inherited `workflow_path` fallback.

### Outcome

6 atomic commits implementing 2 critical fixes + 1 reachable
corner-case fix + dead code removal + test quality improvements.
Polish items skipped per Investigation 5 verdict (each failed the
"solve observed problems, not theorized ones" test).

End-to-end smoke verified all three production-shape scenarios:
memo-hit child workflow rollup parity, 3-deep rollup attribution,
heterogeneous batch per-child attribution.

## Cache analysis verification cleanup — Commits 1–4 (2026-05-04)

Post-`1fabde31` cleanup pass following the 4-agent + 5-agent review
that surfaced two critical bugs in production, one reachable corner-case
bug, dead code, and test-quality items. The plan defined 6 atomic
commits; commits 1–4 are landed (working tree, not yet committed),
commits 5–6 are pending.

### Commit 1 — Test infrastructure (landed by user prior to this session)

Pure test infrastructure with zero production behavior change.

- New ``TraceFixtureBuilder.cached_llm_event_with_call`` produces the
  production memo-hit shape (``cached: true`` AND populated ``llm_call``
  with original ``cost_usd``, ``cache_source``, ``cache_key``,
  ``cache_age_sec``). Pre-existing ``cached_llm_event`` only modeled
  cached non-LLM nodes — Pitfall #19 root cause for why no test caught
  Bug #1 (cached LLM cost inflating rollup).
- New ``TraceFixtureBuilder.heterogeneous_workflow_batch_event`` produces
  the het-batch shape with per-item ``template_resolutions["workflow"]``.
- ``TraceFixtureBuilder.workflow_event`` now requires ``workflow_path``
  kwarg and writes it to ``node_params.workflow`` matching production
  trace shape.
- New fixtures: ``parent-child-memo-hit-trace.json`` (drives Bug #1
  regression), ``parent-child-grandchild-trace.json`` + ``parent-3deep``
  / ``child-3deep`` / ``grandchild`` ``.pflow.md`` files (3-deep
  end-to-end coverage for Commit 6).
- Existing ``parent-child-trace.json`` and
  ``parent-child-erroring-trace.json`` regenerated with
  ``node_params.workflow``.
- ``TestTraceFixtureBuilderShapeParity`` test class drives real
  ``WorkflowTraceCollector`` and asserts builder output keys match the
  producer's keys for 4 event shapes (regular LLM, cached LLM with
  call, batch, workflow) — load-bearing defense against Pitfall #19.

### Commit 2 — Cached-leaf cost correctness (Critical bug #1)

Production bug: memo-hit LLM events with ``cached: true`` AND
``llm_call.cost_usd > 0`` were being summed into the rollup's
``current_cost_by_workflow``, inflating ``actually_paid_usd``.
Verified against ``RUN4-memo-hit-trace.json`` (Gemini production shape:
``cost_usd: 0.00034006`` on a cached blob). The root summary's
``actually_paid_usd`` (computed via ``compute_actually_paid`` →
``total_cost(include_cached=False)``) was correct; the rollup diverged.

**Fix sites:**

- ``analyze.py:_build_trace_execution_index`` — added
  ``if leaf.is_cached: continue`` filter inside the LLM-leaf loop.
  Mirrors ``compute_actually_paid``'s policy.
- ``trace_tree.py:cost_for_event`` / ``cost_for_node`` /
  ``cost_for_batch_item`` — replaced the brittle shape-sniff
  ``event.get("cached") and event.get("llm_call") is None and not
  (event.get("batch_items") or [])`` with an unconditional cached
  short-circuit ``if event.get("cached") and not include_cached`` plus
  a new ``include_cached: bool = False`` kwarg. Cached descendants in
  ``batch_items`` / ``sub_workflow_events`` are filtered out of the
  leaf sum unless explicitly opted in.
- ``context.py:cost_usd_for_node`` — docstring corrected. Pre-fix
  claim "Cached events contribute 0.0 explicitly" was FALSE for
  memo-hit LLM events with populated ``llm_call``; post-fix it's true.

**Tests added:**

- ``test_cost_for_node_returns_zero_for_memo_hit_with_populated_llm_call``
  — mutation contract on the cached short-circuit.
- ``test_cost_for_node_with_include_cached_returns_original_cost`` —
  diagnostic opt-in for historical cost.
- ``test_cost_for_event_filters_cached_descendants`` — sub-workflow
  with cached + priced child returns priced cost only.
- ``test_build_trace_execution_index_excludes_cached_llm_cost`` —
  mutation contract driving the memo-hit fixture end-to-end.
- ``test_actually_paid_and_trace_index_agree_on_memo_hit_child`` —
  parity invariant: summary and rollup agree on cached semantics.

### Commit 3 — Heterogeneous batch attribution (Critical bug #2)

Production bug: het-batch sub-workflows
(``workflow: ${item.workflow}`` over ``items: [{workflow: a},
{workflow: b}]``) collapsed N edges into 1 via ``_edge_child_paths``'s
``parent_node_id → child_workflow`` mapping (last wins). Per-child
rollup attribution lied even though root-level total stayed correct.

**Plan deviation flagged for record.** The plan called for deleting
``_edge_child_paths`` entirely and pivoting all attribution to trace
metadata, asserting "trace metadata covers all 4 production cases per
Investigation 1." Empirical check (production trace
``~/.pflow/debug/workflow-trace-valid-parent-*.json``) showed
``node_params.workflow`` stores the RAW IR string the user wrote —
often a relative path like ``./valid-child.pflow.md``. The analyzer's
``cw_result.irs_by_workflow`` is keyed by the RESOLVED ABSOLUTE path.
Pivoting attribution off ``node_params.workflow`` alone mismatched
the keys, breaking the existing ``parent-child-erroring-trace`` test
on first run. **Investigation 1 was incomplete**; future planning
should not assume trace metadata is sufficient for sub-workflow
attribution.

**Adapted fix:**

- ``trace_tree.py`` — added ``_resolved_child_workflow_from_event``
  helper that reads ONLY ``template_resolutions["workflow"]["resolved"]``
  (always an absolute path produced by runtime
  ``resolve_sub_workflow``). Deliberately does NOT fall back to
  ``node_params.workflow`` (raw, often relative).
- ``trace_tree.py:walk()`` — for ``batch_items``, prefer the
  per-item ``_resolved_child_workflow_from_event(item)`` lookup; this
  is the actual het-batch fix because ``template_resolutions`` always
  carries the runtime-resolved per-item child path.
- ``trace_tree.py:walk()`` — for ``sub_workflow_events``, kept the
  existing ``edges.get(event_node_id)`` lookup. ``_edge_child_paths``
  is still needed for static (non-template) sub-workflow refs whose
  ``node_params.workflow`` is the raw IR string.
- ``analyze.py:_edge_child_paths`` — KEPT (not deleted per plan D2)
  with an explanatory docstring: "Why this still exists" pointing at
  the relative-vs-absolute mismatch and the het-batch carve-out.

**Tests added:**

- ``test_walk_uses_event_template_resolutions_for_heterogeneous_batch``
  — mutation contract on the per-item fallback line. Het batch with
  two items resolving to ``/abs/a.pflow.md`` and ``/abs/b.pflow.md``;
  asserts each item attributed to its own child.
- ``test_resolved_child_workflow_from_event_prefers_template_resolutions``
  — helper unit test: ``template_resolutions`` wins; ``node_params``
  is NOT a fallback (would re-introduce the relative-vs-absolute
  mismatch).
- ``test_walk_attributes_heterogeneous_batch_costs_per_item`` —
  end-to-end attribution + total cost honesty.

### Commit 4 — Cycle bug at ``walk_cross_workflow``

Production bug (reachable corner case): A → B → A produced both A→B
AND B→A edges in ``cw_result.edges`` because the cycle check at
``cross_workflow.py:_process_one_call`` only saw ``seen={B}`` when
processing B's calls. ``_build_parameters_by_workflow`` then iterated
the back-edge and called ``params_by_workflow.setdefault(A, {})``
which returned the EXISTING root params dict, then mutated it by
adding the back-edge's ``child_input_name``. Walker's own test
contract (existing tests pre-seeded ``seen_paths={root_path}``)
already proved this is the desired semantic — production diverged.

**Fix:** ``cross_workflow.py:walk_cross_workflow`` now seeds
``root_workflow_path`` into ``seen`` from the outset:

```python
seen = set(seen_paths) if seen_paths else set()
if root_workflow_path:
    seen.add(root_workflow_path)
```

**Tests added:**

- ``test_walk_cross_workflow_does_not_emit_back_edge_to_root`` —
  mutation contract on the ``seen.add(root_workflow_path)`` line.
  Drives the production call shape (no manual ``seen_paths`` kwarg).
- ``test_build_parameters_by_workflow_does_not_mutate_root_on_cycle``
  — analyzer-level regression: root params dict stays byte-identical
  to its input after analysis of an A → B → A IR.

**Existing cycle tests** at
``test_walker_handles_cycle_at_info_level`` and
``test_walker_cycle_appends_skip_note`` refactored from
``seen_paths={path}`` to ``root_workflow_path=path`` — same
coverage, more production-accurate idiom.

### Verification

- 6133 tests pass (was 6131 pre-Commit-3; +2 new tests).
- ``make check`` clean (ruff, ruff-format, mypy 201 files, deptry).

### Critical insights for the next agent

- **Don't trust plan assertions about "trace metadata is sufficient"
  without verifying against a real production trace.** Investigation 1
  for this plan checked the runtime trace_collector code path but did
  not verify what production traces actually contain. The result was a
  plan that called for deleting ``_edge_child_paths`` based on a false
  premise. Future planning that asserts trace metadata coverage MUST
  cite a specific production trace file (path + grep output) showing
  the relevant fields.

- **Two attribution sources, one fallback chain.** ``walk()`` now has
  two sources of truth for child workflow path:
  - ``template_resolutions["workflow"]["resolved"]`` (per-item,
    runtime-resolved absolute) — used for batch_items.
  - ``edges.get(parent_node_id)`` (per-parent, analyzer-resolved
    absolute) — used for sub_workflow_events.
  Both eventually fall back to inherited ``workflow_path``. The
  layering is correct but adds reasoning surface — keep this in mind
  when extending the walker.

- **Known latent bug (NOT fixed in this pass): homogeneous workflow
  batches.** A static ``workflow: ./child.pflow.md`` with
  ``batch: [...items...]`` produces batch_items WITHOUT
  ``template_resolutions["workflow"]`` (no template, so no resolution
  data). ``_resolved_child_workflow_from_event`` returns None, falls
  back to inherited ``workflow_path`` (parent), so child LLM cost gets
  attributed to parent. Pre-existing — not introduced by this pass.
  Fix is small (~2 lines: add ``edges.get(event_node_id)`` as second
  fallback for batch_items) but needs (a) production trace
  verification of the homogeneous batch shape, (b) a real fixture, (c)
  audit of ``did_not_execute_in_trace`` and rollup enumeration for
  shifted attribution. Defer to its own task to avoid Pitfall #19.

### State after Commits 1–4 (working tree, not yet committed)

- Production code change: ``trace_tree.py`` ~+50 LOC (helper +
  walker batch_items branch + cost methods refactor),
  ``analyze.py`` ~+30 LOC (``_edge_child_paths`` docstring +
  cached-leaf filter), ``cross_workflow.py`` ~+10 LOC (root-seed +
  docstring), ``context.py`` ~+5 LOC (docstring).
- Test change: +~700 LOC across 6 test files; 0 deletions.
- Net mutation contracts: +2 new (1 het-batch, 1 cycle), -3 stale
  line-shifts fixed, -34 pre-existing stale (not addressed).

### Pending (per user instruction "do 3+4 then let me review")

- **Commit 5** — Dead code (``_LLMSummaryAccumulator.merge_sub``,
  ``TraceExecutionIndex.partial_workflows``), test bloat (3 redundant
  tests in ``test_trace_tree.py``), shim docstring fix in
  ``workflow_trace.py``.
- **Commit 6** — 3-deep end-to-end rollup regression test in
  ``test_analyze_cache.py`` driving the
  ``parent-child-grandchild-trace.json`` fixture (already created in
  Commit 1).

### Follow-up — homogeneous workflow batch attribution (latent bug fix, 2026-05-04)

After Commits 1–4 landed I flagged a known latent bug in the "Critical
insights" section above. User asked for a deep investigation before
deciding whether to fix in-branch or file a GH issue. A thorough
``pflow-codebase-searcher`` pass produced definitive evidence (file:line
citations, real production trace inspection of 67k+ traces in
``~/.pflow/debug/``, synthetic walker verification). Fix was scoped as a
single-commit follow-up to the cleanup pass.

**The bug.** A static homogeneous workflow batch:

```yaml
- type: workflow
- workflow: ./child.pflow.md      # static literal, NOT a template
- batch:
    items: [...]
    inputs: {input: ${item}}
```

…produces ``batch_items[i]`` events that carry
``template_resolutions["inputs"]`` but DO NOT carry
``template_resolutions["workflow"]`` — because the ``workflow:`` ref is a
static literal, not a template, so ``resolve_templates`` never records a
resolution for it. The ``_resolved_child_workflow_from_event`` helper
(reading ``template_resolutions["workflow"]["resolved"]``) returns None,
the walker fell through to inherited ``workflow_path`` (parent), and
child LLM cost was misattributed to parent.

**Production evidence.** Verified shape against
``~/.pflow/debug/workflow-trace-batch-parent-20260421-142904.json``,
``workflow-trace-lyrics-generator-20260423-145051.json``,
``workflow-trace-batch-parallel-20-20260331-172736.json``, and ~100+
others. None of the production traces in ``~/.pflow/debug/`` happen to
have an LLM child of a homogeneous workflow batch (children are mostly
``ShellNode`` / ``PythonCodeNode``), but the recording code path is
identical regardless of child node type — verified via the same code
trace at ``batch_executor.py:706-708`` and
``template_resolution.py:438-442``.

**Cascading symptoms (verified via investigation):**

- Headline ``actually_paid_usd`` (``compute_actually_paid`` →
  ``total_cost(include_cached=False)``): CORRECT — sum-of-leaves doesn't
  care about per-leaf attribution.
- Per-child ``SubWorkflowRollupEntry.actually_paid_usd``: was None for
  the child workflow (looked up via
  ``trace_index.current_cost_by_workflow.get(child_path)`` which had no
  entry for child path — all leaves were attributed to root).
- ``did_not_execute_in_trace`` for child LLM rows: flipped True
  (analyzer thought child LLM didn't run despite execution having
  happened).
- ``compute_projections`` for child rows: fell back to estimator/heuristic
  tier instead of trace tier, since per-call rows couldn't find their
  trace cost via ``trace_index.costs_by_key[(child_path, node_id)]``.
- Cross-workflow discrepancy diagnostics: spurious for homogeneous static
  batches because the analyzer thought zero child invocations executed.

**The fix (3 lines in ``trace_tree.py:walk()`` batch_items branch).**
Insert ``edges.get(event_node_id)`` as a 2nd-priority fallback between
the per-item ``template_resolutions["workflow"]["resolved"]`` lookup
(unchanged, het-batch fix) and the inherited ``workflow_path`` final
fallback:

```python
item_workflow_path = (
    _resolved_child_workflow_from_event(item)             # priority 1: het batch
    or (edges.get(event_node_id) if edges is not None else None)  # priority 2: homo batch
    or workflow_path                                      # priority 3: final fallback
)
```

Precedence is safe: heterogeneous case (priority 1 wins) is unchanged;
homogeneous case (priority 2 wins because per-item template_resolutions
is absent); non-workflow batches (no edge entry) fall through to
inherited as before.

**Why this is precedence-safe for heterogeneous batches.** The het case's
``edges`` map collides on ``parent_node_id`` (last-edge-wins) — that was
the original bug Commit 3 fixed. Priority-1 lookup now wins, so the
collisional ``edges`` entry is never consulted for het batches.

**Why the fix was retained inside ``walk()`` rather than at the analyzer
layer.** The walker is the single primitive trace consumers depend on
(``compute_actually_paid``, ``_build_trace_execution_index``, trace
report, smart_trace, etc.). Bolting attribution policy onto each
consumer would re-introduce the duplication that Task 159's TraceTree
consolidation explicitly removed.

**Tests added:**

- ``test_walk_uses_edges_for_homogeneous_static_workflow_batch``
  (mutation contract, ``trace_tree.py:163``) — drives the walker
  directly with a synthetic homogeneous batch trace; verifies child
  cost rolls up to ``/abs/child.pflow.md`` instead of root.
- ``test_homogeneous_static_workflow_batch_child_cost_attributed_to_child``
  — full end-to-end through ``analyze()`` with on-disk parent + child
  ``.pflow.md`` and a synthetic trace; verifies
  ``SubWorkflowRollupEntry.actually_paid_usd`` for the child equals the
  sum of child LLM costs.
- New ``TraceFixtureBuilder.homogeneous_workflow_batch_event``
  helper that mirrors production shape (``node_params.workflow`` =
  raw literal; ``template_resolutions["inputs"]`` only; no
  ``template_resolutions["workflow"]``).

**Mutation safety verified.** Both new tests fail when the fix is
reverted (proven by reverting the patch in-place and re-running):

```
test_walk_uses_edges_for_homogeneous_static_workflow_batch FAILED
test_homogeneous_static_workflow_batch_child_cost_attributed_to_child FAILED
```

…and pass after restoring. This rules out Pitfall #19 (test passing
against buggy implementation).

**Docstring fix.** ``analyze.py:_edge_child_paths`` docstring updated.
The pre-fix wording said the het case was "handled separately by
:meth:`TraceTree.walk` reading ``template_resolutions["workflow"]["resolved"]``,
so per-item attribution is correct even when this map is lossy" —
which left the impression that ``edges`` was only used for
sub_workflow_events. Post-fix wording clarifies that ``edges`` is now
consulted as a fallback for homogeneous static workflow batches too.

### Verification (cumulative across Commits 1–4 + this follow-up)

- 6135 tests pass (was 6133 pre-follow-up; +2 new).
- ``make check`` clean (ruff, ruff-format, mypy 201 files, deptry).

### Critical insights for the next agent (updated)

- **Trace-walker attribution has THREE priority levels for batch_items
  now**, not two:
  1. ``template_resolutions["workflow"]["resolved"]`` (heterogeneous).
  2. ``edges.get(event_node_id)`` (homogeneous static).
  3. Inherited ``workflow_path`` (non-workflow batches, fallback).
  Future contributors who add a 4th tier should keep this priority
  comment (``trace_tree.py:150-160``) up to date — the comment block
  is the single place where the precedence is documented.

- **The investigation pattern that found this bug should be repeated for
  the OTHER batch shapes**:
  - Heterogeneous workflow batch with mixed inputs templates: covered
    by Commit 3's fix.
  - Homogeneous static workflow batch: covered by this follow-up.
  - Heterogeneous workflow batch where ``inputs`` is non-templated: not
    explicitly tested. Likely fine because it's heterogeneous (priority-1
    template_resolutions for ``workflow`` still wins) but no test pins
    this.
  - LLM batch (not workflow batch): no per-item attribution needed
    (single LLM call per item, all attributed to the LLM node's owner).
    Confirmed by ``test_walk_assigns_owner_node_id_for_batch_items_to_parent``.

### State after follow-up (working tree, not yet committed)

- Production code change since pre-Commit-3 baseline: ``trace_tree.py``
  ~+60 LOC (helper + walker batch_items 3-tier attribution + cost
  methods refactor + comments), ``analyze.py`` ~+35 LOC
  (``_edge_child_paths`` docstring updates + cached-leaf filter),
  ``cross_workflow.py`` ~+10 LOC (root-seed + docstring),
  ``context.py`` ~+5 LOC (docstring).
- Test change: +~900 LOC across 7 test files; 0 deletions.
- Net mutation contracts: +3 new (1 het-batch, 1 cycle, 1 homo-batch),
  -3 stale line-shifts fixed, -34 pre-existing stale (not addressed).

## Cache analysis verification cleanup — Commits 5–6 (2026-05-04)

Follow-on session implementing the final two commits of the cleanup plan.

### Commit 5 — Dead code + test bloat + shim docstring

**Source-side deletions:**

- ``runtime/workflow_trace.py:_LLMSummaryAccumulator.merge_sub`` —
  deleted (13 LOC). Pre-``1fabde31`` callers were the manual recursion
  in ``_collect_llm_summary``; that path now uses
  ``iter_llm_leaves(descend_cached_subtrees=False)`` which descends into
  sub-workflows internally, so the merge accumulator was orphaned.
  Verified zero callers via ``grep -rn merge_sub src/ tests/``.
- ``cache_analysis/analyze.py:TraceExecutionIndex.partial_workflows`` —
  deleted. Field was constructed at line 821 (``workflow_partial`` set
  accumulator) and never read anywhere in ``src/`` or ``tests/``.
  Removed the field declaration (line 263), the local accumulator, the
  ``workflow_partial.add(workflow_key)`` call inside the cost loop, the
  ``partial_workflows=workflow_partial`` constructor kwarg, and updated
  the two ``return TraceExecutionIndex({}, {}, set(), set(), {}, set())``
  early-return shapes to drop the trailing ``set()``.

**Shim docstring fixes** (``runtime/workflow_trace.py``):

- ``_collect_llm_calls_from_events`` — replaced empty one-liner with
  the actual policy (skips cached at every tier — top-level, batch_items,
  sub_workflow_events). Pre-1fabde31 the hand-rolled walker only
  filtered top-level cached events; the new behavior is correct because
  cached items contributed $0 this run regardless of nesting.
- ``_collect_llm_summary`` — same correction applied.

**Test bloat removal** (``tests/test_core/test_trace_tree.py``):

- ``test_iter_llm_leaves_skips_cached_subtree_when_requested`` (was
  line 76) — deleted. Subsumed by
  ``test_walk_skips_cached_subtree_when_kwarg_false`` at line 477,
  which targets the same line 133 with the same revert string AND has
  tighter assertions (asserts the ENTIRE walk is empty, not just the
  filtered LLM leaves).
- ``test_iter_llm_leaves_threads_workflow_path_via_edges`` (was
  line 98) — deleted. Subsumed by
  ``test_walk_event_carries_workflow_path_via_edges`` at line 796,
  which targets the same code path with current-accurate line marker
  (191) and richer assertions (verifies BOTH parent and child
  workflow_path).
- ``test_total_cost_descends_sub_workflows`` (was line 686) — deleted.
  Subsumed by ``test_total_cost_descends_sub_workflows_three_deep``
  at line 144, which targets the same line 279 with the same revert
  string. 3-deep recursion implies 1-level works.

Net: -3 tests, ~-80 test LOC, -25 production LOC.

### Commit 6 — 3-deep end-to-end rollup regression test

Added ``test_analyze_cache_rolls_up_three_deep_sub_workflow_costs`` in
``tests/test_cli/test_analyze_cache.py``. Drives the
``parent-child-grandchild-trace.json`` fixture (created in Commit 1) end-to-end
through the CLI in JSON mode. Asserts:

- ``summary.actually_paid_usd == 0.15`` (sum of 0.05 + 0.07 + 0.03)
- Both child + grandchild workflow paths appear in
  ``sub_workflow_rollup.per_workflow``.
- Per-child entries report PER-WORKFLOW scope, not cumulative
  (child entry == 0.07, grandchild entry == 0.03).

**Mutation safety verified.** Reverted the ``if descend_sub_workflows:``
guard to ``if False:`` in ``trace_tree.py:walk()``; test fails with
``assert 0.05 == 0.15``. Restored; test passes.

### State after Commits 5–6

- 6133 tests pass. Math: 6135 (post-Commits-1–4 + homo-batch follow-up)
  - 3 deletions (Commit 5) + 1 addition (Commit 6) = 6133. Confirmed.
- ``make check`` clean (ruff, ruff-format, mypy 201 files, deptry).

### Critical insights for the next agent

- **Trailing positional args in dataclass constructors are fragile.**
  ``TraceExecutionIndex({}, {}, set(), set(), {}, set())`` — the
  trailing ``set()`` was the deleted ``partial_workflows`` field. The
  removal is mechanically obvious in source, but using positional args
  in a dataclass with 6 fields is the trap. Future refactors of this
  shape should prefer keyword args for clarity.

## Stage 2 verification follow-ups: sub-cent UX + memo-hit token recovery + JSON count parity (2026-05-04)

End-to-end Stage 2 verification (Gemini smoke + 3-deep rollup smoke) surfaced
three latent bugs that the post-`1fabde31` cleanup didn't catch. All three
fall into the "the data is computed correctly somewhere — but the rendered
or aggregated surface lies about it" class. Shipped together because they
share the failure mode.

### Bug #10 — Sub-cent savings render as "savings unavailable"

**Symptom**: Gemini-shaped recommendations with `estimated_savings_usd: 0.0012`
in JSON rendered as `"savings unavailable"` in text mode at every site:
recommended-action rank lines, inline message clauses, dry-run nudge. JSON
contract was honest; text contract hid every real recommendation behind a
placeholder.

**Root cause**: 4 sites used `< $0.005 → "savings unavailable"` (intended as
the Bug D fix for `-$0.00/run` placeholder). The cutoff conflated "too small
to display with 2 decimals" with "too small to compute". Gemini's typical
savings ($0.0001-$0.005 range) all collapsed to the placeholder.

**Fix**: extended `_format_dollar_amount`'s adaptive precision tiers to all
4 savings-rendering sites:

- `< $0.0001` → "savings unavailable" (truly negligible; below display floor)
- `$0.0001 ≤ value < $0.01` → 4-decimal precision (`-$0.0012/run`)
- `≥ $0.01` → 2-decimal precision (`-$0.42/run`)

Sites: `render_text._format_savings_usd`, `warning_catalog._format_savings`,
`warning_catalog._format_savings_clause`, `warning_catalog.format_dry_run_nudge`.

**Bug D regression invariant preserved**: no `-$0.00/run` placeholder
anywhere. Test rewritten with precision-tier locking instead of unavailable-
collapse locking.

### Bug #11 — Memo-hit traces lose `output_tokens` for projection (Issue A)

**Symptom**: `pflow analyze-cache --from-trace <memo-hit-trace>` reported
`output_tokens_estimated: null`, `output_data_source: "unavailable"`,
`input_tokens_estimated: 4325` (estimator-partial fallback) for memo-hit
LLM rows. Cascade: `Cost without caching: unavailable` in rendered output
even though the trace event preserved full `llm_call.usage` from the
original run.

**Root cause** (`analyze.py:_build_trace_execution_index`): the `if
leaf.is_cached: continue` filter introduced by the post-`1fabde31` Bug 1
fix was positioned BEFORE `llm_calls_by_key.setdefault(...)`. The filter's
intent — exclude cached events from cost summation — was correct, but it
ALSO bypassed index population, so downstream `_estimate_row_tokens` found
`trace_llm_call=None` for cached keys and fell through to estimator/heuristic.

**Fix**: split the cost-skip from the index-skip. `llm_calls_by_key` now
populates for cached events (carries historical `input_tokens` /
`output_tokens` / `model`); cost summation still skips them. Bug 1 invariant
preserved — `cost_usd: 0.0` for memo hits, `costs_by_key` excludes them
because `found.add(key)` happens AFTER the cached-skip.

End-to-end on `RUN4-memo-hit-trace.json`: `input_tokens_estimated: 4714`
(was 4325), `output_tokens_estimated: 76` (was null), `cost_usd: 0.0`,
all sources `"trace"`. Rendered text now shows `Cost without caching:
~$0.0032` (was `unavailable`).

### Bug #12 — `root_llm_node_count` / `sub_workflow_llm_node_count` JSON parity (Issue B)

**Symptom**: text output for multi-level workflows correctly shows
`"3 LLM nodes using anthropic/claude-sonnet-4-5"` and
`"(1 in parent-3deep.pflow.md, 2 in 2 sub-workflows: child-3deep, grandchild)"`.
JSON output emitted no such fields — the breakdown was computed on-the-fly
in the renderer and lost when serializing.

**Root cause**: `AnalysisSummary` had no fields for these counts. The text
renderer's `_format_sub_workflow_breakdown_line` (`render_text.py:136`)
computed them inline from `analysis.per_call`. JSON consumers never saw
them — silent contract drift between text and JSON surfaces.

**Fix**:
- `AnalysisSummary` adds `root_llm_node_count: int = 0` and
  `sub_workflow_llm_node_count: int = 0` (4.x minor-additive — no version bump).
- `_build_summary` populates them by filtering rows on `ctx.workflow_path`.
- `_summary_to_dict` emits both fields.
- `_format_sub_workflow_breakdown_line` refactored to read from the summary
  fields — single source of truth, no inline `sum(...)` recomputation.

End-to-end on `parent-child-grandchild-trace.json`:
`{"root_llm_node_count": 1, "sub_workflow_llm_node_count": 2}` ✓.
Text rendering byte-identical (renderer reads same data via different path).

### Files modified

**Production** (4 files):
- `src/pflow/core/cache_analysis/analyze.py` — `AnalysisSummary` fields + `_build_summary` population + `_build_trace_execution_index` reorder
- `src/pflow/core/cache_analysis/render_text.py` — 1 site adaptive precision + `_format_sub_workflow_breakdown_line` reads from summary
- `src/pflow/core/cache_analysis/render_json.py` — emit 2 new summary fields
- `src/pflow/core/cache_analysis/warning_catalog.py` — 3 sites adaptive precision

**Tests** (3 files):
- `tests/test_core/test_cache_analysis_renderers.py` — sub-cent test rewritten; new test asserts JSON has count fields
- `tests/test_core/test_cache_analysis_warnings.py` — `format_dry_run_nudge` precision-tier tests
- `tests/test_core/test_cache_analysis_analyze.py` — new test asserts memo-hit traces recover input/output tokens via `analyze()` end-to-end

### Verification

- 399 cache-analysis tests pass; ruff/mypy/format clean on changed files.
- Two pre-existing ruff `RUF059` errors in `test_cache_analysis_token_estimation.py`
  (commit `6640255b1`, unrelated to this work). Filed as separate cleanup.
- End-to-end Bug #11 reproducer (RUN4 memo-hit): output_tokens 76 ✓, input
  4714 ✓, cost_usd 0.0 ✓, all sources "trace" ✓.
- End-to-end Bug #12 reproducer (3-deep): root=1, sub=2 ✓; text breakdown
  unchanged ✓.
- End-to-end Bug #10 reproducer (Gemini smoke greenfield): rank line shows
  `-$0.0012/run` (was "savings unavailable"), inline shows `(saves $0.0012/run)`
  (was empty).

### Critical insights

1. **Bug 1 fix had two intents bundled together.** Excluding cached events
   from cost summation (correct) AND bypassing index population (incorrect).
   Splitting the filter into two precise gates eliminates the asymmetry —
   cost stays 0.0/trace, tokens read from preserved historical data.
   Rule: when a `continue` filter sits before multiple downstream effects,
   verify EACH effect should be skipped, not just the one that triggered
   the filter.

2. **Tri-state contracts need adaptive precision, not single cutoffs.** The
   original Bug D fix used `< $0.005 → unavailable` to avoid `$0.00`
   placeholders. On Anthropic-shaped costs ($0.42/run typical) this works
   fine. On Gemini-shaped costs ($0.0012/run typical) it hides every real
   value behind a placeholder. The fix mirrors `_format_dollar_amount`'s
   tiered approach already established for absolute cost rendering — same
   precision policy across the savings-rendering sites.

3. **Text-only computation is a JSON contract leak.** `_format_sub_workflow_breakdown_line`
   computed root/sub counts inline from per_call rows. JSON consumers never
   saw the data. Pattern: when text rendering composes data from raw rows
   that the data model doesn't carry, hoist the computation into the data
   model so JSON consumers see the same picture. Single source of truth.

### State after this commit

- 6135 → 6138 tests pass (3 new tests added; no other test count changes
  expected in this scope).
- Cache-analysis surface clean: 399/399 tests, ruff/mypy/format green.
- Pre-existing 2 ruff errors in token_estimation tests carried forward
  (commit `6640255b1`); fix is mechanical (`_` prefix unused vars) but
  out of scope for this commit.

## Detect prompt-body / prompt_cache overlap (2026-05-04)

Three-phase implementation closing the duplicate-bytes pattern uncovered by
Stage 2.1 verification: when an LLM node declares `prompt_cache: [X]` AND
the prompt body references `${X}`, pflow sends the value twice (cached at
0.1× rate via system blocks AND inline at 1.0× rate in the body — net cache
benefit ~zero). Until this commit, nothing told the workflow author they'd
nullified their own caching.

### What shipped

**Phase 0 — shared overlap module** (`src/pflow/core/cache_overlap.py`, NEW)

- `compute_overlaps()` + `Overlap` dataclass with three kinds: `duplicate`,
  `cache_contains_body`, `body_contains_cache`.
- `_canonicalize_path()`: splits paths on `.` AND before each `[`, dropping
  empties. `"items[0].field"` → `("items", "[0]", "field")`. Pinned by
  parametrized table tests.
- `_is_strict_prefix()`, `_batch_aliases()`, `_is_batch_scoped_ref()`
  (the latter duplicated from `analyze.py:1946-1954` per plan; cycle
  constraint forbids analyzer→cache_overlap→analyzer).
- 28 unit tests in `tests/test_core/test_cache_overlap.py`.

**Phase 1 — validator + save-path wiring**

- `data_flow.py`: threaded optional `workflow_path: str | None = None`
  through `validate_data_flow()`. New `_emit_prompt_body_overlap_diagnostics()`
  helper calls `compute_overlaps()` and routes ERROR/WARNING through
  `make_diagnostic()` (catalog-as-SSoT, dodges raw-Diagnostic drift).
  Consolidated-per-node shape mirrors `cache.invalid-on-non-llm` —
  `Diagnostic.__hash__` would otherwise collapse two diagnostics with the
  same (severity, source, node_id, id) tuple and lose per-pair detail.
- `validator.py::_validate_data_flow`: passes `workflow_file` through.
- `save_service.py`: new `_resolve_for_validation()` deep-copies the IR,
  runs `resolve_file_references()` on the copy, hands the resolved IR to
  the validator. The original IR keeps literal file path strings so
  `_discover_and_bundle_deps()` still bundles them. **Critical fix vs the
  original plan** — see "Deviation 1" below.
- `warning_catalog.py`: 2 new `CacheWarningSpec` entries —
  `cache.prompt-body-duplicates-cache` (ERROR, `validator`) and
  `cache.prompt-body-shadows-cache` (WARNING, `validator`). Both use the
  consolidated `overlap_lines` context key for the rendered per-pair list.
  Priority entries: ERROR=5, WARNING=10.
- 17 new validator tests in `test_prompt_cache_validation.py` including
  the **CRITICAL** Pattern 4 subprocess test that drives `pflow save` via
  `subprocess.run` and asserts non-zero exit + catalog id in stderr —
  regression-pin for the save-path file-resolution wiring.

**Phase 2 — analyzer surfaces `prompt_body_cleanup` for greenfield**

- `analyze.py::SuggestedBlock` gained `prompt_body_cleanup: dict[str, list[str]]`
  field (default empty). Populated by new `_compute_prompt_body_cleanup()`
  helper invoking the shared `compute_overlaps()` for each assigned node.
- `render_text.py`: appends "also remove from prompt body: ${...}" line
  under each per-node `prompt_cache:` line when the cleanup dict has refs.
- `render_json.py`: `prompt_body_cleanup` key in per-block JSON output;
  flows through MCP `analyze_cache` automatically.
- 4 new renderer tests in `test_cache_analysis_renderers.py` including the
  documented-scope-boundary pin (greenfield-only; brownfield short-circuits).

### Files modified

**Production** (8 files):
- `src/pflow/core/cache_overlap.py` (NEW)
- `src/pflow/core/workflow/data_flow.py` — workflow_path threading + new
  helper + overlap call site after the order-match block (only when
  `all_resolved` is True so we don't compound `cache.undeclared-chunk`)
- `src/pflow/core/workflow/validator.py` — pass workflow_file through
- `src/pflow/core/workflow/save_service.py` — `_resolve_for_validation()`
  helper + uses validation_ir for downstream calls
- `src/pflow/core/cache_analysis/warning_catalog.py` — 2 catalog entries
  + priorities + docstring update
- `src/pflow/core/cache_analysis/analyze.py` — `SuggestedBlock` field +
  `_compute_prompt_body_cleanup` helper
- `src/pflow/core/cache_analysis/render_text.py` — cleanup-hint line
- `src/pflow/core/cache_analysis/render_json.py` — JSON key
- `src/pflow/mcp_server/tools/execution_tools.py` — docstring updated to
  16-entry catalog list

**Tests** (8 files):
- `tests/test_core/test_cache_overlap.py` (NEW) — 28 unit tests
- `tests/test_core/test_prompt_cache_validation.py` — 17 new tests incl.
  Pattern 4 subprocess
- `tests/test_core/test_cache_analysis_renderers.py` — 4 renderer tests
- `tests/test_core/test_cache_analysis_warnings.py` — count constant
  (16 entries) + source-split inclusion + sample kwargs for new IDs
- `tests/test_core/test_cache_analysis_per_id_coverage.py` — kwargs
  samples + producer-driven coverage for both new IDs
- `tests/test_runtime/test_prompt_cache_compile.py` — fixture prompt body
  changed to non-overlapping (was unrelated dupe pattern; now it would
  trip the new check)
- `tests/test_runtime/test_prompt_cache_hash.py` — same fixture fix
- `tests/test_execution/test_plan_drift.py`, `test_plan_cache_nudge.py`,
  `tests/test_integration/test_no_cache_flag.py` — same fixture fix

### Deviation 1 — file resolution must NOT mutate the original IR (CRITICAL)

The plan said: *"in `save_service.py:_validate_and_normalize_ir()`, before
the existing `WorkflowValidator.validate()` call, invoke
`resolve_file_references(workflow_ir, source_path.parent)`"*.

Implemented as written initially → 2 `test_workflow_bundling.py` tests
broke. Root cause: `resolve_file_references()` mutates IR in place,
replacing `params.prompt = "./agent.md"` with the file's content. By the
time `_discover_and_bundle_deps()` runs (downstream of validation), it
calls `is_file_reference()` on the now-content string and returns False —
no deps discovered, no files bundled, broken saved workflow.

The plan's claim *"`resolve_file_references` mutates IR in-place; downstream
save persists the original markdown source, not the IR, so mutation is
safe (verify in implementation)"* is half-right: the markdown source IS
preserved. But `_discover_and_bundle_deps` reads the IR, not the markdown,
to find paths to bundle.

**Fix**: extracted `_resolve_for_validation()` that deep-copies the IR
and runs file resolution on the copy. The validator gets resolved content
(catches overlap); the input IR keeps file paths (bundling still works).

This is the most important learning for any future "thread file resolution
into a new validation phase" work — always check what downstream layers
read from the post-resolution IR vs the original source.

### Deviation 2 — `make_diagnostic` requires `affected_workflow` for
node-scoped diagnostics

The plan acknowledged using `make_diagnostic()` over raw `Diagnostic(...)`
to avoid catalog/emitter byte-equivalence drift, but didn't account for
`_ensure_workflow_scope` requiring a non-empty `affected_workflow` whenever
`node_id` is set.

To make this work without breaking synthetic-IR tests, threaded
`workflow_path` through `validate_data_flow()` AND added a `<unknown>`
fallback in `_emit_prompt_body_overlap_diagnostics`. The fallback is
load-bearing for the compile path (see Known Gap below).

### Deviation 3 — fixture overlap pattern was already encoded in 5 test
files

5 pre-existing tests had `prompt: "Tell me about ${concept}"` AND
`prompt_cache: [concept]`. They tested OTHER properties (cache hashing,
nudge emission) but encoded the exact bug pattern this work catches.
Fixed each by changing the prompt body to a static string ("Tell me a
one-liner story.") — preserves the test's actual intent without tripping
the new check. Added in-line comments documenting why.

### Critical insights

1. **"Mutate in place" claims need downstream-impact analysis.** A function
   that mutates can be safe in isolation but break when its outputs feed
   layers that read different fields than the mutation touched.
   `resolve_file_references` mutates `params.prompt`; `_discover_and_bundle_deps`
   reads `params.prompt` — same field, opposite intent. The code review
   pre-merge agents flagged "save-path-only" but didn't catch the
   bundling collision; only the bundling test caught it.

2. **`Diagnostic.__hash__`'s `(severity, source, node_id, id)` tuple is
   load-bearing for consolidated-per-node diagnostics.** Two findings
   on the same node with the same id collapse into one. The fix is
   ALWAYS to emit one diagnostic per node listing all pairs, NEVER to
   emit one diagnostic per pair. Pinned by `test_multiple_chunks_one_node_consolidates_to_single_diagnostic`.

3. **Catalog-as-SSoT (`make_diagnostic`) is worth the upfront friction.**
   The original plan reached for raw `Diagnostic(...)` "to mirror the
   shipped emitters" — but those emitters were the ones drifting from
   the catalog (e.g., `cache.unused-chunk` shipped without `source_line`
   despite the catalog requiring it). Routing through `make_diagnostic`
   eliminates that drift surface entirely.

4. **Catalog-list docstrings drift silently.** The MCP `analyze_cache`
   tool docstring listed "14 entries in v1" with an explicit ID list.
   Adding two IDs to the catalog without updating the docstring would
   ship — `test_docstring_lists_every_catalog_id` fired and pinned the
   sync. Worth keeping that test pattern as-is; an `EXPECTED_CATALOG_COUNT`
   in the docstring would silently rot without it.

5. **Pattern 4 subprocess tests catch what unit tests miss.** The Pattern
   2 (`save_workflow_with_options()`) test exercises the API and asserts
   the diagnostic fires — but only the Pattern 4 subprocess test caught
   that the CLI's `pflow save` actually surfaces the diagnostic to stderr
   with the catalog id intact. Plan flagged this as CRITICAL; that label
   was earned.

### Known gap (filed as follow-up)

**Compile path doesn't thread `workflow_path`** → its overlap diagnostics
carry `affected_workflow="<unknown>"` while validator-path diagnostics
carry the real path. Same workflow, two JSON shapes depending on which
entry ran. `Diagnostic.__hash__` ignores context so no double-emit; in
normal flows the validator runs first and short-circuits, so end users
rarely see the placeholder. Library/programmatic callers that go straight
to the compiler do see it.

**Filed**: GH issue [#367](https://github.com/spinje/pflow/issues/367) —
Thread `workflow_path` through `_prepare_compilation()` →
`_validate_data_flow_at_compile_time()` and drop the `<unknown>` fallback.

### State after this commit

- 6184 → 6185 tests pass (1 new subprocess test added on top of the 49
  unit tests written for the three phases; the pre-existing 6184
  baseline reflects all production-side test additions absorbed earlier
  in the run).
- All affected surfaces clean: `make check` green (ruff + ruff-format +
  mypy + deptry).
- Catalog grew from 14 → 16 entries; `EXPECTED_CATALOG_COUNT = len(...)`
  auto-derives, only the human-prose count constants needed updating.

## Stage 2 follow-up — `## Cached System` in `--report` (trace 2.2.0)

### What

Stage 2.1 verification revealed `pflow run --report` per-node markdown
exposes only the user prompt — **what the LLM actually saw (the
cache-rendered system prefix) was invisible** without dropping to the
raw JSON trace. Closed the gap: trace bumped 2.1.0 → **2.2.0** with a
new additive `event["llm_system"]` field, surfaced as a `## Cached
System` section in the report (rendered before `## Prompt` to match
API call order). `list[dict]` cache-rendered prefixes emit a fenced
JSON block so the provider-specific `cache_control` markers stay
visible to agents.

### Files modified

**Production** (6 files):

- `src/pflow/core/llm_client.py` — `before_call` event extended with
  `system` field; TraceHook docstring updated.
- `src/pflow/runtime/workflow_trace.py` — `TRACE_FORMAT_VERSION =
  "2.2.0"`; new `llm_systems` dict mirroring `llm_prompts`; capture in
  `get_trace_hook()`; write to `event["llm_system"]` in `_add_llm_data`.
- `src/pflow/nodes/llm/llm.py` — `LLMNode.post()` mirrors
  `prep_res.get("system_blocks") or prep_res.get("system")` to
  `shared["system"]` (parallel-batch parity seam, mirrors prompt seam).
- `src/pflow/runtime/engine/batch_executor.py` — `_capture_item_trace`
  pair-copy adds `system → llm_system`; isinstance widened to
  `(str, list)` since `llm_system` may be `list[dict]`.
- `src/pflow/core/trace_report.py` — extracted `_format_cached_system`
  helper to keep `_format_resolutions` under the C901 complexity cap.
- `src/pflow/core/cache_analysis/analyze.py` — replaced the
  `startswith("2.1")` autoload gate with
  `_format_version_at_least_2_1()` (numeric-tuple comparison).

**Docs** (1 file):

- `src/pflow/runtime/CLAUDE.md` — 2.2.0 row added; documents the
  capture+fallback path AND the batch parity seam.

**Tests** (6 files, 1 new):

- `tests/test_runtime/test_trace_format_2_2.py` (NEW) — 9 tests
  including the `_format_version_at_least_2_1` regression pin.
- `tests/test_runtime/test_workflow_trace.py` — new
  `TestTraceHookCapturesSystem` class (8 tests).
- `tests/test_core/test_trace_report.py` — 6 rendering branches
  (string / list / order / skipped chunks / absent / empty skipped).
- `tests/test_runtime/test_trace_integration.py` — new
  `TestCachedSystemEndToEnd` covering IR → engine → trace → report.
- `tests/shared/llm_mock.py` — mock fires `system` in `before_call`
  (mirrors adapter contract).
- `tests/shared/trace_fixture_builder.py` — version 2.1.0 → 2.2.0;
  `system` kwarg added to `llm_event` and `cached_llm_event_with_call`.
- `tests/fixtures/cache_analysis/*.json` — regenerated via
  `_generate.py` (only `format_version` field changed).

### Deviation 1 — autoload version gate is a hidden dependency on the bump (CRITICAL)

The plan listed 5 production files. Investigation discovered a 6th:
`cache_analysis/analyze.py:_autoload_trace` had
`str(data.get("format_version", "")).startswith("2.1")` — which
**silently rejects 2.2.0 traces**. Without fixing this, every minor
bump would break `analyze-cache` autoload AND no test would catch it
(autoload fixtures all carry literal "2.1.0").

Initially replaced with a numeric-tuple `_format_version_at_least_2_1`
helper, then **trimmed** (see post-implementation cleanup below) once
it became clear all 2.0/2.1 traces are pre-merge artefacts that won't
exist in any consumer's hands. Final gate: `startswith("2.")`.

This remains the load-bearing learning for any future trace minor bump:
**any consumer that gates on a specific minor will silently break,
and existing tests won't catch it because their fixtures are pinned
to one version**. The `startswith("2.")` pattern is the right shape
when post-merge no pre-bump traces exist; for cross-version branches,
a numeric-tuple comparison would be needed.

### Deviation 2 — pre-merge backward compat is dead code (POST-IMPLEMENTATION CLEANUP)

After the implementation landed, realized: trace formats 2.0.0 / 2.1.0
only ever existed pre-merge on `feat/prompt-caching`. Once the branch
lands, every trace produced by pflow is 2.2.0 (or whatever the
current-shipping version is). All BC scaffolding I'd carefully
preserved was dead code:

- `_format_version_at_least_2_1` helper — distinguishing 2.0 from 2.1+
  is meaningless when only 2.2+ traces exist. **Removed**, both call
  sites simplified to `startswith("2.")`.
- 2.0.0 graceful-info-note path in `_load_trace_explicit` — **removed**.
- `test_autoload_skips_2_0_0_trace_silently`,
  `test_explicit_from_trace_2_0_0_emits_graceful_note`,
  `test_discrepancy_silent_when_trace_is_2_0` (cache-analysis tests
  that fed 2.0.0 traces to assert specific dead-path behaviors) —
  **deleted**.
- `test_2_0_0_consumer_gate_still_passes_for_2_1_0_traces` (tautology
  test that `"2.1.0".startswith("2.")` is True) — **deleted**.
- `test_format_version_is_at_least_2_1` (numeric-tuple gate test that
  I'd added) — **deleted**.
- Discrepancy stage's `if not fv.startswith("2.") or fv.startswith("2.0"):`
  — **simplified** to `if not fv.startswith("2."):`.
- Agent-facing CLI help text mentioning "2.0.0 emits a graceful info
  note" — **removed**.
- `WorkflowTraceCollector` docstring's per-minor history (Format 2.0.0
  changes / Format 2.1.0 changes / Format 2.2.0 changes) — **collapsed**
  into a single "Format 2.x shape" section listing what exists.
- `runtime/CLAUDE.md`'s twin Format-2.1.0 / Format-2.2.0 entries —
  **collapsed** into one Format-2.x entry.
- Tests with hand-rolled `format_version="2.2.0"` literals or
  softened `startswith("2.")` assertions — **changed** to
  `== TRACE_FORMAT_VERSION` so the test suite has one place expressing
  the version-equality contract.

### Critical insight: test what's actually a contract

The post-implementation cleanup highlights a subtle test-design rule:
**not every behavior worth pinning when written is worth pinning
forever**. Tests like
`test_2_0_0_consumer_gate_still_passes_for_2_1_0_traces` documented
the bump intent at the moment of bumping but encode no permanent
contract. After merge they're noise — and noise is more expensive
than its line count because it makes future cleanups harder
("does this test guard a real invariant?"). The trim deleted ~80 LOC
of test code that was correct when written but never going to fire
again.

### Critical insights

1. **A minor trace-format bump has more dependencies than the
   producer-side files suggest.** Production-side: 6 files. The
   *consumers* with version gates are subtler — `analyze-cache`
   autoload had a `startswith("2.1")` literal that was invisible to
   the plan's file enumeration. Audit pattern for future bumps: grep
   for the OUTGOING version literal (`"2.1"` here) across `src/`, not
   just the type definition.

2. **The plan's `node_output["system"]` fallback is dead code in
   normal operation but worth keeping for symmetry.** For non-batch
   LLM nodes, the trace_hook always fires successfully; for batch
   items, `_capture_item_trace` reads `node_output["system"]`
   directly, never going through `_add_llm_data`. So the fallback in
   `_add_llm_data` only fires in degenerate paths. But removing it
   would make the prompt/system pair asymmetric (prompt has the same
   fallback) — the asymmetry is harder to maintain than the dead
   line.

3. **`tests/shared/llm_mock.py` is a producer of trace events for
   integration tests.** Without firing `system` in its `before_call`
   event, every integration test that runs an LLM node through the
   mock would be invisible to trace 2.2.0. The mock's fidelity to the
   real adapter's contract is load-bearing — not just a test
   convenience. Same lesson would apply to any future field added to
   `before_call`/`after_call`.

4. **`make check` C901 violations surface late.** Adding a section to
   `_format_resolutions` pushed it from complexity 10 to 12. The fix
   was a 30-LOC helper extraction; trivial when caught here, but
   catching it AFTER the test suite was passing means I had to
   re-run the whole pipeline. For future renderer changes touching
   `_format_resolutions` / `_format_node_output`, expect to extract
   to a helper rather than inline.

5. **Committed cache-analysis fixtures regenerate from a generator.**
   `tests/fixtures/cache_analysis/_generate.py` is the SSoT;
   `test_committed_cache_analysis_fixtures_match_generator_output`
   pins drift. Bumping the trace fixture builder to "2.2.0"
   automatically required regenerating (the test failure even
   includes the regen command verbatim — `python -m
   tests.fixtures.cache_analysis._generate`). This drift-detection
   pattern earned its keep.

### State after this commit

- 6201 tests pass after trim (gross: +21 new tests for `llm_system`
  capture/render/integration; net: -7 from deleting pre-merge BC
  tests).
- `make check` clean (ruff + ruff-format + mypy + deptry).
- Trace format: **2.2.0** (current shipping version on this branch).
  Consumer rule: `startswith("2.")`. Future additive minor bumps
  (2.3, 2.4, ...) stay forward-compat without consumer changes.
- All cross-version scaffolding (the `_format_version_at_least_2_1`
  helper, 2.0.0 graceful-note path, dead BC tests) removed because
  pre-merge traces won't exist in any consumer's hands once this lands.

## Stage 2.1 follow-up — Anthropic 1h cost double-charge (2026-05-05)

`_maybe_normalize_anthropic_1h_cost` was added in Spike 3 to compensate
for LiteLLM not pricing `ephemeral_1h_input_tokens`. LiteLLM has since
gained `cache_creation_input_token_cost_above_1hr` for some Anthropic
models (claude-haiku-4-5, claude-opus-4-1) — the override now
double-charges them. Stage 2.1 verification on Haiku 4.5 observed an
effective $4/M (vs published $2/M) on 1h cache writes, surfacing as a
spurious -23% first-run savings instead of the expected ~55%.

Fix: short-circuit when LiteLLM's pricing entry carries
`cache_creation_input_token_cost_above_1hr`. Falls through to the
existing override only when the field is missing (e.g.,
claude-sonnet-4-5 as of 2026-05-05).

Verified end-to-end: fresh Haiku 4.5 cache-write call now reports
$0.010209 (matches `(input - cache_creation) × $1/M + cache_creation
× $2/M + output × $5/M`) where pre-fix reported $0.020043.

New test: `test_anthropic_1h_cost_normalization_no_op_when_litellm_has_above_1hr_rate`.

## Stage 2 verification — comprehensive UX + spec-target audit (2026-05-05)

Multi-session verification of every Task 159 surface against the
motivating workflow (`lyrics-generator/song-creator`) plus targeted
edge-case workflows. Spec target verified on Anthropic Haiku
(48% input savings fresh / ~99% cost reduction on rerun); muddied on
Gemini by the provider's automatic implicit cache. 21 UX/bug findings
catalogued; cache mechanism itself is solid end-to-end. Total spend
~$2.59 across 17 paid runs + free validations.

### Documents produced

- `reports/REPORT.md` — Stage 2 final report. Catalogues all 21
  findings (BUG / REAL UX GAP / PAPER-CUT) with evidence, severity,
  and proposed fix shapes. Chronological test-run table (cost +
  outcome + trace path per run). Spec-target verification math per
  provider. Files inventory + reverts-before-merge guidance.

- `reports/cache-heterogeneous-models-fragment.md` — standalone
  implementation spec for Finding #11 (the user's explicit ask):
  analyzer doesn't warn when cross-node mixed exact-models prevent
  cache sharing. Includes detection algorithm sketch, JSON shape,
  edge cases, empirical evidence, and ~150-LOC effort estimate.
  Written so a future agent can implement from this doc alone.

- `handoffs/stage2-findings-fix-decision.md` — braindump handoff for
  the next agent. Captures tacit knowledge NOT in the report: the
  user's stated constraints (no provider-constraint table; exact-model
  match for caching; agent-UX evaluation as load-bearing), 7 critical
  insights about why findings exist (e.g., temp=1+thinking is pflow's
  translation layer, not Anthropic's API), decision dimensions for
  prioritization, and process notes for talking with the user about
  which fixes to land.

### Auxiliary test fixtures created (live in scratchpads/)

- `scratchpads/stage2-verification/mixed-model-test/` — 2-node
  workflow with different providers sharing `${context}`. Drives
  Finding #11 verification.
- `scratchpads/stage2-verification/cross-workflow-test/` — parent +
  child workflows with cache propagation. Drives Finding #21 (cache_key
  is workflow-scoped).
- `scratchpads/stage2-verification/error-ux-tests/` — three
  intentionally-broken workflows that trigger `cache.order-mismatch`,
  `cache.invalid-on-non-llm`, `cache.unused-chunk` validators.
- `scratchpads/stage2-verification/song-creator/` — full Stage 2.1
  trace inventory (RUN1-3 Gemini + RUN-HAIKU1-3, RUN-HAIKU-FINAL,
  RUN-HAIKU-RERUN, CHORUS-HAIKU). Inputs JSON for song-A "The Third
  Plate".

### Highest-impact findings (top 3 by ROI)

1. **`reasoning_effort` translation bug on Anthropic** (Finding #1):
   pflow translates `reasoning_effort: low/medium/high` →
   `thinking: enabled` but doesn't normalize `temperature: 1` (which
   Anthropic requires when thinking is on). Bit 11 nodes across 3
   files in lyrics-generator. ~5 LOC fix in the translation layer.

2. **`rerun_within_ttl_hypothetical_usd` ignores memo cache**
   (Finding #2): analyzer's projection only models provider cache, not
   pflow's MEMO cache. Real reruns are ~75× cheaper than projected.
   Agents reading the analyzer dramatically under-estimate caching
   value.

3. **No `cache.heterogeneous-models-fragment-cache` warning**
   (Finding #11, the user's explicit ask): mixed exact-models in
   the same workflow silently fragment cache. No warning. Implementation
   spec at `reports/cache-heterogeneous-models-fragment.md`.

### State after this verification

- 17 paid LLM runs + 4 free validations executed.
- Cache mechanism confirmed working end-to-end on Anthropic Haiku 4.5
  (fresh + rerun spec targets both met).
- 11 in-place edits to lyrics-generator workflows tracked in
  REPORT.md "Reverts before merge" — distinguishes test-specific
  workarounds (revert when Finding #1 lands) from real improvements
  (keep: prompt-body cleanups, `## Cache` declarations,
  `prompt_cache:` declarations, increased timeouts).
- No production code changed in this verification round; all findings
  filed as actionable inputs for the next planning + implementation
  session.

## Stage 2 follow-up — Finding #1: thinking + temperature validate-time check (2026-05-05)

Anthropic's API rejects every request that combines `thinking: enabled`
with `temperature ≠ 1.0`. pflow translates `reasoning_effort: low/medium/
high/...` to `thinking: enabled` for Anthropic models in
`llm_client._translate_reasoning_for_litellm` but never normalized
temperature, so workflows with this composition crashed at runtime.
Verified empirically the rule is uniform across Opus 4.1/4.5/4.7,
Sonnet 4.5/4.6, Haiku 4.5 (six models, three families, four generations).

Fix: validate-time ERROR via new catalog entry
`llm.thinking-temperature-mismatch` (first non-`cache.*` entry in the
catalog — namespace mixed deliberately rather than splitting catalogs
for one entry). Static check on each LLM node; skips templated values.
Save-path blocks; runtime path unchanged so the existing actionable
BadRequestError still fires if validation is bypassed.

Decision rationale: chose validate-time ERROR over silent runtime
auto-normalization to avoid corrupting user temperature on any future
model where Anthropic relaxes the rule. Matches existing pflow patterns
(`cache.invalid-on-non-llm`, `cache.prompt-body-duplicates-cache`).

### Files modified

**Production** (5 files): `core/diagnostic.py` (+`LLM_VALIDATION_CATEGORY`),
`core/cache_analysis/warning_catalog.py` (+catalog entry, +`see_also`
field on `CacheWarningSpec`), `core/cache_analysis/analyze.py` (filter
switched from `cache.*` prefix to catalog membership so `llm.*` IDs
surface in `analyze-cache`), `core/workflow/data_flow.py` (+validator),
`mcp_server/tools/execution_tools.py` (docstring catalog list).

**Tests** (3 files, +22 tests): 20 validator tests in
`test_prompt_cache_validation.py` covering positive cases (5 effort
variants), negative cases (none, temp=1, temp omitted, non-Anthropic,
templated, non-LLM), multi-node, plus Pattern 4 subprocess driving
real `pflow save`. Plus catalog round-trip + count + namespace tests
updated.

## Stage 2 follow-up — Findings #11/#12: exact-model fragmentation + lone-write penalty (2026-05-05)

Implemented `cache.heterogeneous-models-fragment-cache` and
`cache.first-call-write-penalty` from
`fix-plans/heterogeneous-models-fragment-cache-plan.md`. The detector is
root-only and lives beside `_consolidate_to_root_advisories`, reusing
root `PerCallRow` data and grouping by `normalize_model_name(row.model)`.
Rows with templated models, missing model, missing trace execution, or no
declared `prompt_cache:` are excluded before grouping.

Detection behavior:

- Fragmentation warning fires when at least two exact-model groups share
  declared chunks. Savings use the plan's "largest group survives" rule:
  sum cache-creation cost for the other participating groups. If any
  participating group lacks pricing or cacheable-token data, the warning is
  skipped rather than fabricating dollars.
- First-call write-penalty advisory fires for exact-model groups of size 1,
  suppresses `prewarm: true`, and suppresses `gemini/*` because Gemini's
  implicit cache does not have the same paid first-write penalty shape.

Deviation: manual CLI verification on the mixed-model scratchpad showed
the initial local formatter rendered tiny real penalties as `$0.0000`.
Fixed `_format_usd` to use six decimals below `$0.0001`; final manual
output renders `$0.000019` / `$0.000004`, preserving the sub-cent signal.
No plan step was skipped.

Files modified:

- Production/docs: `analyze.py`, `warning_catalog.py`,
  `mcp_server/tools/execution_tools.py`, `cache_analysis/CLAUDE.md`.
- Tests: catalog count/context samples, producer-driven per-ID coverage,
  primary per-ID emission tests (+10 detector tests), and two CLI JSON
  smoke tests.

Verification:

- Focused: 156 passed across cache warning/catalog/emission/CLI/MCP tests.
- Broad sandbox: 6215 passed, 18 skipped with the known Homebrew-`uv`
  subprocess panic tests excluded (`test_cli_save_subprocess_with_overlap_exits_nonzero`,
  `test_thinking_temperature_mismatch_pflow_save_subprocess_exits_nonzero`,
  plus the 3 exclusions from the sandbox-testing skill).
- `ruff check`, `ruff format --check`, `mypy`, and `deptry src` clean.
- Manual:
  `HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache scratchpads/stage2-verification/mixed-model-test/mixed-model.pflow.md --format=json`
  emits both new IDs.

## Stage 2 follow-up — Findings #11/#12: post-review fixes (2026-05-05)

Critical review of the staged implementation surfaced three correctness/UX
issues and one v1.x carve-out. All three issues fixed in this commit; the
carve-out filed as GH issue #369.

### Fix 1 — `_format_usd` deviation removed

Initial implementation embedded dollar amounts directly in the
`cache.first-call-write-penalty` message body via `{write_cost_str}` and
`{penalty_str}` context fields, requiring a new `_format_usd` helper that
deviated from the codebase-wide Bug D contract (`< $0.0001 → "savings
unavailable"`) by rendering 6-decimal precision instead. None of the 17
other catalog entries embed dollar amounts in message body — they all use
`{savings_clause}` exclusively.

Rewrote the message template to use `{savings_clause}` only:

> `{node_id}: only call to {model} in this workflow with `prompt_cache:`
> declared. The cache_creation premium has no subsequent reads to amortize;
> removing the declaration would avoid the premium.{savings_clause}`

Dropped `write_cost_str`/`penalty_str` from `required_context_keys`.
Deleted `_format_usd`. Simplified `_single_call_write_penalty` to return a
single `float | None` (savings) instead of `(write_cost, penalty)`.

CLI verification on the mixed-model fixture: rank line shows `-$0.0012/run`
in the right column, message body ends with `(saves $0.0012/run)`. Fully
consistent with all other warnings; no embedded dollar weirdness.

### Fix 2 — `node_count` grammar

`_format_model_groups_lines` always emitted "(N nodes)" regardless of
count. Renders as "(1 nodes): draft" for size-1 groups. Fixed to use
`"node"` for count=1, `"nodes"` for count>1. Updated test fixtures in
`_kwargs_for` and `_minimal_context_kwargs` to match.

### Fix 3 — Cost projection accuracy (precise per-chunk math)

Initial implementation used `min(row.cacheable_tokens_estimated for row in
group.rows)` as the per-group token estimate. This is the smallest row's
TOTAL cacheable tokens, not the SHARED-CHUNKS-ONLY tokens. When rows in a
group declared chunks beyond what's shared with other groups (mixed
`prompt_cache:` lists), the math overstated redundant cost — the savings
figure could be 2-3× too high.

Fix: replaced with strict per-chunk math via `_estimate_ref_tokens(chunk,
...)`. New `_compute_model_group_costs` signature takes `shared_chunks:
set[str]` and `ctx: AnalysisContext`; for each group, sums tokens over
`group["chunks"] & shared_chunks` only. If any shared chunk is
unmeasurable (memo miss in pure greenfield), returns None → skip emit.
Mirrors `_check_root_for_consolidation`'s "any None → skip" pattern.

Tradeoff: precise math is brownfield-leaning (greenfield without prior
runs has no memo data → `_estimate_ref_tokens` returns None → warning
silent). Same constraint already governs `cache.consolidate-to-root-
recommended`. Honest-unmeasurable beats approximate-and-overstating.

Added regression test:
`test_fragmentation_skips_when_shared_chunk_tokens_unmeasurable`. Mutation
contract: reverting to `min(row tokens)` math fails the test because rows
have measurable cacheable tokens even when per-chunk estimation is
blocked.

### Out-of-scope: within-batch heterogeneity → GH issue #369

Within-batch fragmentation (`model: ${item.model}` resolving to N exact
models per batch item) cannot be detected from per_call rows because
`TraceExecutionIndex.llm_calls_by_key` uses `setdefault` and keeps only
the FIRST batch item's call data. Detection requires walking
`tree.iter_llm_leaves` directly and is fundamentally brownfield-only.

Filed as GH issue #369 with full implementation sketch, detection
algorithm, files to touch, UX considerations, test fixtures, and
acceptance criteria.

### Files modified

**Production** (2 files):
- `src/pflow/core/cache_analysis/analyze.py` —
  `_compute_model_group_costs` signature + body; `_format_model_groups_lines`
  grammar; `_single_call_write_penalty` simplified return; `_format_usd`
  deleted; `_detect_model_cache_fragmentation` updated to pass
  `shared_chunks` + `ctx` to costs and drop the embedded dollar fields.
- `src/pflow/core/cache_analysis/warning_catalog.py` —
  `cache.first-call-write-penalty` message template + required_context_keys.

**Tests** (3 files):
- `tests/test_core/test_cache_analysis_per_id_emission.py` — `_patch_pricing`
  now stubs `_estimate_ref_tokens`; new
  `test_fragmentation_skips_when_shared_chunk_tokens_unmeasurable`.
- `tests/test_core/test_cache_analysis_per_id_coverage.py` — local
  `_estimate_ref_tokens` stub for the heterogeneous producer block; dropped
  `write_cost_str`/`penalty_str` from `_kwargs_for`; fixed grammar in
  `model_groups_lines` fixture.
- `tests/test_core/test_cache_analysis_warnings.py` — same fixture cleanups
  in `_minimal_context_kwargs`.

### Verification

- 6239 tests pass, 9 skipped (pre-existing subprocess exclusions per the
  Homebrew-`uv` panic; same set as before).
- `make check` clean (ruff + ruff-format + mypy + deptry, 202 source files).
- Manual CLI verification:
  `uv run pflow analyze-cache scratchpads/stage2-verification/mixed-model-test/mixed-model.pflow.md`
  emits `cache.first-call-write-penalty` for the haiku-call with savings
  rendered via the standard `_format_savings_clause` (`-$0.0012/run` /
  `(saves $0.0012/run)`). Fragmentation correctly silent in this fixture
  because the trace's memo cache wasn't pre-populated for the chunk —
  honest-unmeasurable working as designed.

### Critical insights

1. **Embedded-currency-in-message is an anti-pattern** in this catalog.
   Every existing warning uses `{savings_clause}` only; new entries should
   too. The Bug D contract (`< $0.0001 → placeholder`) only works
   end-to-end when dollars stay in the savings column, not the prose.

2. **Honest-unmeasurable beats approximate-and-overstating.** When the
   precise input isn't available, returning None and staying silent is
   strictly better UX than fabricating a number that's 2-3× wrong. Pattern
   matches `_check_root_for_consolidation`'s established convention.

3. **Singular/plural is load-bearing for agent UX.** "(1 nodes)" reads as
   a typo and erodes trust in the rest of the analyzer's output. Worth the
   3 LOC every time.

4. **Tests should not pin grammatical bugs.** The initial fixtures encoded
   `"(1 nodes)"` strings that locked the bug in. After the fix, fixtures
   read `"(1 node)"` and the catalog round-trip tests still pass —
   confirming the bug was a fixture-pinning issue, not a contract issue.

## Stage 2 follow-up — Finding #6: split blocking errors from recommendations (2026-05-05)

Implemented `fix-plans/blocking-errors-section-split-plan.md`. Text output now
renders ERROR-severity findings in `## Blocking errors (must fix before run)`
between Summary and Recommended actions, with no savings column. WARNING/INFO
findings remain in `## Recommended actions`. JSON now emits symmetric
`blocking_errors[]` and `recommended_actions[]` arrays, both always present;
errors are removed from `recommended_actions[]`.

Simplifications shipped with the split:

- Removed analyze-cache JSON `format_version` / `JSON_FORMAT_VERSION_MAJOR`
  constants and package re-exports. No in-tree programmatic consumer used
  them; tests now assert the current key shape instead of a version ceremony.
- Deleted the `analyze.py::_build_recommended_actions` compatibility shim.
  Tests import `build_recommended_actions` / `build_blocking_errors` from
  `view_helpers`, matching production renderers.

Files touched:

- Production/docs: `view_helpers.py`, `render_text.py`, `render_json.py`,
  `__init__.py`, `analyze.py`, `warning_catalog.py`, MCP analyze-cache
  docstrings, `cache_analysis/CLAUDE.md`.
- Tests: renderer, analyzer helper, CLI, MCP, per-ID coverage tests.

Verification:

- Focused: 174 passed across cache-analysis renderer/analyzer/per-ID, CLI,
  and MCP tests.
- Broad sandbox: 6223 passed, 18 skipped using the sandbox-safe pytest command
  with the five known Homebrew-`uv` subprocess exclusions.
- Static: `ruff check`, `ruff format --check`, `mypy src`, and `deptry src`
  clean. Direct `.venv/bin/pre-commit run -a` reached the code hooks cleanly
  but failed in `end-of-file-fixer` with sandbox `PermissionError` opening
  `.agents/skills/pflow-sandbox-testing/agents/openai.yaml`; no task files
  were changed by the failed hook.
- Manual CLI: order-mismatch scratchpad renders Blocking errors only and JSON
  has two `blocking_errors` plus empty `recommended_actions`; mixed-model
  scratchpad renders Recommended actions only.

Plan deviation / stale fixture note:

- The plan expected the existing `error-ux-tests/order-mismatch.pflow.md`
  scratchpad to show 2 blocking errors plus 2 opportunities. In the current
  worktree it resolves no model, so below-min/write-penalty opportunities do
  not fire there. I did not edit the scratchpad just to satisfy the manual
  example; production tests cover the mixed error+opportunity split, and the
  manual checks verified the two real current fixture shapes separately.

Critical insights:

1. **Severity belongs in the view split, not the data model.** Keeping
   `warnings` as the raw SSoT and deriving two ranked projections avoided a
   second copy of findings while making text/JSON parity straightforward.
2. **Local ranks are clearer than global ranks after a split.** Each array /
   section starts at rank 1, so agents can treat Blocking errors and
   Recommended actions as independent work queues.
3. **Version constants without a consumer gate are ceremony.** The trace
   format still needs `format_version` because readers gate on it. Analyze-cache
   JSON had no equivalent in-tree gate, so shape assertions are the stronger
   contract here.

## Stage 2 follow-up — Findings #4/#5: per-call cache telemetry surfaces (2026-05-05)

Implemented `fix-plans/per-call-cache-telemetry-plan.md`. `--report` now
renders `## Cache telemetry` for LLM calls with provider cache writes/reads,
memo replay metadata, or skipped cache chunks; replay headings use the
user-facing phrase `(cached result reused from prior run)` and do not leak
`memo` / `in_process`. `thinking_tokens > 0` now renders in node metadata as
`- Thinking: N tokens`.

`analyze-cache --format=json` now emits additive per-call fields
`cache_creation_input_tokens` and `cache_read_input_tokens`. These are raw
trace observations (`int`, including 0) and stay `null` when no trace
`llm_call` exists; they are separate from the analyzer's projected
`cacheable_tokens_estimated`.

Files touched:

- Production: `core/cache_analysis/analyze.py`,
  `core/cache_analysis/render_json.py`, `core/trace_report.py`.
- Tests: `test_cache_analysis_analyze.py`,
  `test_cache_analysis_renderers.py`, `test_trace_report.py`.

Plan deviations / adaptations:

- The renderer test helper named in the plan (`_make_per_call_row`) does not
  exist in the current file. Used the existing `_row(...)` helper plus
  `PerCallRow(**{...})` reconstruction, matching nearby tests.
- The Stage 2 song-creator scratchpad contains trace JSONs but no checked-in
  `.pflow.md` workflow file, so the exact plan CLI command against that
  workflow could not run. Verified the same JSON shape through the checked-in
  cache-analysis fixture workflow and manually inspected the Stage 2 traces'
  cache fields.

Critical insights:

1. **Observed cache splits are not projections.** Keeping raw trace fields
   separate from `cacheable_tokens_estimated` preserves creation-vs-read facts
   while leaving analyzer math unchanged.
2. **Replay vocabulary is a UI boundary.** `cache_source` is a useful internal
   discriminator, but the report should expose the behavior, not the storage
   implementation.
3. **Report section gates need a real signal.** A cache key alone can exist
   without cache activity; rendering on token activity, replay state, or
   skipped chunks avoids noisy sections on plain calls.

## Test-suite performance triage and isolation cleanup (2026-05-06)

Investigated the local `make test` regression after Task 159 expanded the
suite from roughly 5.1k to 6.2k tests. The main finding was that the default
suite had accumulated true e2e/subprocess tests plus avoidable test I/O
overhead: repeated full `registry.json` writes and trace JSON writes during
ordinary in-process tests.

Implemented a narrower default test path:

- Marked real subprocess / shell-pipe boundary tests as `e2e`.
- Updated `make test` to run `-m "not e2e"`.
- Added `make test-e2e` and `make test-all-local`.
- Changed test isolation so default `Registry()` loads precomputed core node
  metadata in memory instead of writing a full registry file per test.
- Disabled trace file writes by default in tests, with explicit
  `@pytest.mark.trace_files` opt-in for trace/report/autoload assertions.

Sandbox verification after the changes:

- Focused trace/registry-sensitive tests: 170 passed.
- Default non-e2e suite: 6220 passed.
- Fixed-basetemp output dropped from about 51M to 16M.
- Registry files dropped from about 860 to 83.
- Trace files dropped from 129 to 39.

Filed GitHub issues for audit trail and follow-up:

- #371: original pytest slowdown investigation, closed after this fix.
- #372: remaining performance follow-ups, including SQLite cache write
  reduction and targeted optimization of remaining slow non-e2e tests.

## Stage 2 follow-up — Findings #9/#10 + phantom-savings: unified below-min-token detection (2026-05-06)

Implemented `fix-plans/cache-below-min-tokens-unified-detection-plan.md`. Closes
two Stage 2 findings plus a correctness bug surfaced during planning:

- **Finding #9 (discoverability gap)** — `cache.below-min-tokens` previously
  fired only from `analyze-cache`. Agents who ran `pflow run --validate-only`
  saw "Workflow is valid" even when their `prompt_cache:` decoration silently
  no-op'd at the provider. Stage 2 evidence: RUN-HAIKU-RERUN's
  `generate-suno-prompt` had 3,764 tokens against Haiku's 4,096 minimum with
  zero signal. Closed by adding observed-tier emission from `LLMNode.post()`
  using post-call provider telemetry — fires during the run, surfaces in
  `--report` and trace JSON without requiring agents to remember to invoke
  `analyze-cache`. Discussed at length in the planning thread; decided
  against literal `--validate-only` emission because DD#36 forbids tokenizers
  in the runtime/validation hot path.
- **Finding #10 (misleading message text)** — the warning's "cache_control
  markers will silently no-op" text was accurate for Anthropic but
  misleading for Gemini (whose implicit cache may still fire on stable
  prefixes regardless of `cache_control` markers). Closed via provider-aware
  message dispatch in the catalog: Anthropic keeps the original phrasing,
  Gemini distinguishes explicit `cachedContents` from possible implicit
  caching, OpenAI omits the suffix because the main "below {model}'s
  minimum" already conveys it cleanly.
- **Phantom-savings correctness bug (no finding number; surfaced during
  planning)** — three analyzer paths computed non-zero `estimated_savings_usd`
  for caches that won't fire because totals are below threshold
  (`_savings_for_shared_ref`, `_single_call_write_penalty`,
  `_compute_model_group_costs`). The phantom values flowed into
  `RecommendedAction.estimated_savings_usd` and contaminated action-priority
  ranking — sub-threshold suggestions could outrank valid above-threshold
  ones. Closed by adding threshold gates at all three sites following the
  established convention from `cache.batch-prewarm-recommended` and
  `cache.dynamic-before-static`.

`cache.below-min-tokens` now has one detector module with two evidence tiers:
analyzer predicted estimates and runtime observed provider telemetry. Analyzer
emission was refactored through the detector; `LLMNode.post()` now emits a
catalog-backed `Diagnostic` after calls that declare `prompt_cache:` but report
0 provider cache creation/read tokens. Runtime warning transport now preserves
`Diagnostic` instances end-to-end, and `--report` shows warning IDs plus
catalog suggestions.

Closed the phantom-savings paths:

- Greenfield suggested-block savings now count only nodes whose assigned
  subset clears that node's model threshold; the first eligible node is the
  writer and only later eligible readers contribute savings.
- `cache.first-call-write-penalty` suppresses below-threshold declarations
  because no provider write premium exists when the cache cannot fire.
- `cache.heterogeneous-models-fragment-cache` filters model groups below
  threshold before calculating redundant writes and suppresses when fewer
  than two groups survive.

Suggested blocks now carry/render `per_node_thresholds` in text and JSON so
agents can see whether each proposed `prompt_cache:` subset clears the selected
model threshold. The `cache.below-min-tokens` catalog entry dispatches message
text by `evidence_kind` and uses provider-aware notes: Anthropic names
`cache_control` no-op behavior, Gemini distinguishes explicit cachedContents
from possible implicit caching, and OpenAI omits the suffix.

Deviations / adaptations:

- Refactored new inline logic into helpers after ruff complexity checks caught
  `_populate_suggested_blocks`, `_render_suggested_blocks`, `make_diagnostic`,
  and `LLMNode.post()` crossing complexity limits. This was not a scope change;
  it keeps the final code simpler than the literal inline plan.
- Updated `test_prompt_cache_fires_under_no_cache_flag` to stage nonzero mock
  provider cache telemetry. The test's intent is "memo `--no-cache` does not
  disable provider prompt-cache markers"; after runtime observed-tier detection,
  the previous mock default of 0 cache tokens correctly meant "observed cache
  miss" and degraded the run.
- CLI warning fixtures for model-fragmentation and first-write-penalty now pass
  larger context values so they exercise above-threshold warnings. Below-
  threshold suppression is covered separately.

Verification:

- Focused affected tests: 520 passed.
- Full sandbox non-e2e suite:
  `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py -m "not e2e"`
  → 6248 passed.
- Sandbox e2e subset with known Homebrew-`uv` subprocess exclusions:
  18 passed, 18 skipped.
- Static checks: ruff check/format clean on touched files; `mypy src` clean
  (203 source files); `deptry src` clean.

Key learnings:

1. Runtime telemetry changes test semantics. A mock default of
   `cache_creation=0, cache_read=0` is no longer neutral for cache-declaring
   LLM calls; it is evidence that provider caching did not fire.
2. Threshold gating must happen at the same granularity as the provider cache:
   per node and exact model for suggested blocks, per exact-model group for
   fragmentation. Row-total or block-level shortcuts recreate phantom savings.
3. Passing `Diagnostic` through `__warnings__` is the right channel shape for
   catalog-backed runtime findings. Normalization remains useful for legacy
   string/dict paths, but the runner must preserve typed diagnostics instead
   of wrapping them as generic api warnings.

## Stage 2 follow-up — post-implementation review + tightening (2026-05-06)

After the unified detector landed, ran a 4-agent code review (`/code-review`
with `review-plan` + `review-silent-failures` + `review-feature-interactions` +
`review-impact-completeness`) against the staged implementation. Reviewers
confirmed plan adherence and flagged one residual silent-failure path in the
runtime emit site.

### Tightening — empty `llm_usage` guard

`_emit_observed_below_min_cache_warning` (`nodes/llm/llm.py`) was firing
observed-tier findings even when the adapter returned no usage at all (the
case where `LLMNode.post()` line 977 sets `shared["llm_usage"] = {}`). With
both cache fields absent from the dict, `int(llm_usage.get(...) or 0)` resolved
to 0+0 and the helper synthesized a false-positive "did not fire" finding
rather than recognizing missing telemetry.

Added an early-return guard before the `detect()` call:

```python
if "cache_creation_input_tokens" not in llm_usage and "cache_read_input_tokens" not in llm_usage:
    return  # honest unmeasurable — mirrors _estimate_ref_tokens / _compute_model_group_costs
```

Pinned by `test_emit_observed_below_min_cache_warning_skips_when_no_provider_telemetry`
in `tests/test_execution/test_runner.py` — a helper-level unit test that
constructs a `CacheRenderContext` and calls the helper with `llm_usage={}`
directly. Mutation contract verified by reverting the guard and confirming
the test fails with the exact false-positive message it was designed to catch.

The test runs at the helper level rather than through the runner pipeline
because `MockLLMClient.set_response` always populates cache fields in usage
(defaults to 0); there is no current way to simulate `AdapterResponse(usage={})`
end-to-end. The runner-pipeline equivalent is filed as GH issue #375.

### GitHub follow-ups filed

Three follow-up issues filed on `spinje/pflow`, all labeled `enhancement`:

- **#373** — Add near-threshold expansion hints for greenfield `SuggestedBlock`.
  When a node's assigned subset is below threshold but within 50% of the
  minimum, scan the workflow for unreferenced template refs that could
  bridge the gap and render `Add ${notes} (~1500 tokens) → 4920 tokens`
  hints. ~80 LOC. Most agent-actionable piece of advice the
  `cache.below-min-tokens` feature could surface; deferred during planning
  via explicit `AskUserQuestion` decision.
- **#374** — Modernize the `__warnings__` channel: workflow scoping, live
  emission, list-shaped values. Bundles three independent structural
  improvements that all touch `shared["__warnings__"]` keying and value
  shape. Cross-cutting refactor (~250 LOC); fixes (a) parent/child
  same-`node_id` collisions, (b) post-run-only warning surfacing, (c)
  cache-miss vs empty-response setdefault overwrite. Out of scope for v1
  per the plan.
- **#375** — Mock fidelity: add `usage_present` toggle to
  `MockLLMClient.set_response`. Lets runner-level pipeline tests exercise
  the `shared["llm_usage"] = {}` path that the empty-telemetry guard
  protects. ~15 LOC; replaces the helper-level unit test with a
  pipeline-level one. Self-contained test-infrastructure improvement.

### Verification (after tightening)

- `tests/test_execution/test_runner.py`: 32 passed (was 31 pre-tightening; +1
  for the new guard test).
- Cache-related sweep across detector / catalog / renderers / per-id /
  analyze / diagnostic / runtime LLM / no-cache-flag: 370 passed.
- `ruff check` and `mypy` clean on `nodes/llm/llm.py` and the test file.

### Key learnings (from review + tightening)

1. **The four-agent code review caught what manual self-review missed.** The
   `review-feature-interactions` agent specifically pinned the silent-failure
   path by tracing the helper's data flow through the post-call pipeline. The
   bug was in code I had read multiple times during implementation.
2. **"Honest unmeasurable" is a load-bearing convention in this codebase.**
   Three sites already implement it (`_estimate_ref_tokens`,
   `_compute_model_group_costs`, `_savings_for_shared_ref`). Any new emission
   path that consumes externally-supplied data should follow the same
   convention by default — return None / skip when data is absent rather
   than fabricate from defaults.
3. **Mock infrastructure can preclude end-to-end tests for genuinely
   important paths.** `MockLLMClient`'s always-populates-cache-fields
   default forced a helper-level unit test for a guard that we'd ideally
   pin via runner pipeline. Worth filing the mock improvement (#375) as a
   first-class test-infrastructure enhancement rather than carrying the
   awkward unit test forward.
