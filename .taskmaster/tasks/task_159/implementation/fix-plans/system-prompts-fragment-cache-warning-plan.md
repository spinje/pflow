# Add `cache.system-prompts-fragment-cache` analyzer warning

> **Atomic implementation plan for Task 159 PR #378 review-fix #5 (the design-decision finding).**
> Optimized for an AI agent implementing in isolation. No ambiguity. Read end-to-end before starting.

---

## Context: Why This Change Exists

### The problem

In `_build_system_blocks` (`src/pflow/nodes/llm/llm.py:540-609`), pflow places `user_system` BEFORE cache chunks in the system message, then puts the `cache_control` marker on the LAST cache chunk. This means the cached prefix bytes = `user_system + chunk_1 + ... + chunk_N`. **If two LLM nodes share `prompt_cache: [...]` but have non-identical `system:` instructions, the prefix bytes diverge and provider cache hits do NOT fire across them.**

The motivating spec example (`song-creator.pflow.md`) is exactly this pattern: `write-lyrics`, `rewrite-emotional`, `rewrite-craft`, `generate-suno-prompt` each have their own role-specific `system:` but share `prompt_cache: [concept, concept_brief, creative-direction.response, song-architecture.response]`. Today these 4 nodes each create their OWN cache entry — sharing is per-node (cross-invocation) only. The spec's "50-70% per-run reduction" is at the bottom edge of what current behavior delivers; cross-node sharing would push it higher but doesn't fire.

The runtime ordering (system FIRST, cache AFTER) matches Anthropic's documented pattern (short instructions at top, long cacheable context below). It's defensible as a default but assumes uniform `system:` across cache-sharing nodes — a tacit assumption agents have no way to know without reading source.

### The chosen solution: Path A + new analyzer warning

**Path A** (keep current ordering, document the constraint) is the right v1 default — Anthropic-recommended; no LLM-behavior risk.

**New warning** (`cache.system-prompts-fragment-cache`) makes the constraint VISIBLE at `pflow analyze-cache` time, so agents are TOLD when their workflow hits the pattern instead of silently losing savings. Structurally a sibling of the existing `cache.heterogeneous-models-fragment-cache` (different fragmentation cause; same fragmentation pattern).

### Why it matters

Without this warning:
- Agents authoring multi-role pipelines (the spec's motivating shape) silently lose cross-node cache sharing.
- They have no signal at static analysis time; the savings are simply lower than expected.
- The "spec promises 50-70%, you got 40%" gap is invisible to anyone but a careful user reading their trace.

With this warning:
- `pflow analyze-cache` reports the fragmentation with concrete savings estimate.
- Agent gets WHAT happened (4 nodes, 4 distinct system prompts), WHY it matters (provider cache prefix includes system; cache writes redundantly), and HOW to fix (consolidate role-specific text from `system:` to `prompt:`, OR accept per-node caching).
- Pure analyzer addition; zero runtime behavior change; zero regression risk.

### Intended outcome

- New catalog entry `cache.system-prompts-fragment-cache` (severity warning, priority 10, Tier 1 actionable). Catalog grows from 20 → 21 IDs (still closed list per DD#29).
- New detector `_detect_system_cache_fragmentation` invoked from `analyze()` alongside the model-fragmentation detector.
- Honest-unmeasurable convention: returns None when token estimation or pricing is missing. Defers to model-fragmentation when a system group has heterogeneous models internally.
- `pflow guide caching` documents the constraint and points at the warning.
- Production-shape regression tests (1 emission + 4 suppression mutation guards).

---

## Verified Facts (from pflow-codebase-searcher Phase 1)

The plan rests on these load-bearing facts. Implementing agent should re-verify before changing code.

### 1. `system:` storage in IR

**Canonical path: `node["params"]["system"]`** — same as `prompt`, NOT top-level like `prompt_cache`. Always a string when present (single-line YAML scalar OR ```` ```system ```` fenced block; both flow into `params["system"]`). Source of truth: `markdown_parser.py:97-112` (code-block tag mapping) + `markdown_parser.py:1605-1606` (final IR shape). Verified by 3 production read sites:

- Runtime: `nodes/llm/llm.py:719-720`: `system = self.params.get("system")`
- Trace report: `core/trace_report.py:865-866`: `if "system" in node_params: system = str(node_params["system"])`
- Cache rendering: `nodes/llm/llm.py:769-778, 540-609`: `_build_system_blocks(user_system=...)`

**Detector reads via**: `node.get("params", {}).get("system")`. Mirrors `_collect_llm_template_references`'s pattern at `analyze.py:2202` for `prompt`.

### 2. `system:` is NOT in `FILE_RESOLVABLE_PARAMS`

`core/file_resolver.py:38-46` lists `{command, code, prompt, source, stdin, headers, output_schema}` — `system` is NOT there. Comment at lines 34-37 explicitly says it's a planned-not-done addition. **Implication**: `system: ./prompt.md` reaches the analyzer as the literal string `"./prompt.md"`. Byte-comparison still works correctly — two nodes with `system: ./a.md` and `system: ./b.md` are string-different (warn); both with `system: ./a.md` are string-same (no warn). **The detector does NOT need file resolution to function.**

### 3. Templates allowed in `system:`

Parser does not strip `${...}`. Two nodes with `system: "${a}"` are byte-equal at IR time AND will resolve identically at runtime (assuming same upstream value). Two with `${a}` and `${b}` are byte-different → warn (correct; could resolve to different bytes). **Byte-compare unresolved strings is the right semantics.**

### 4. The sibling detector pattern

`_detect_model_cache_fragmentation` at `analyze.py:2380-2466` is the structural template. Algorithm:

1. Filter rows: `declared_prompt_cache` truthy, `model` truthy, NOT `model_is_heterogeneous`, NOT `did_not_execute_in_trace`.
2. Group rows by fragmentation key (`normalize_model_name(row.model)` for the existing one).
3. Find groups whose chunks overlap with another group's chunks (`_chunks_shared_with_other_group`).
4. Gate on `>= 2` fragmented groups.
5. Compute redundant-write cost via `_compute_model_group_costs` (returns `None` if any group lacks pricing or any chunk has unmeasurable tokens — honest-unmeasurable).
6. Filter to groups whose total tokens clear the model's min-cache threshold.
7. Emit ONE workflow-scoped diagnostic (`node_id=None`) with `model_groups`, `models_csv`, `shared_chunks`, `savings_usd`.

Helpers reusable directly:
- `_chunks_shared_with_other_group` (analyze.py:2483-2490) — generic on group dicts
- `_chunks_shared_across_groups` (analyze.py:2493-2497) — generic
- `_sum_chunk_tokens` (analyze.py:2764-2778) — generic, returns None if any ref unmeasurable
- `_format_model_groups_lines` (analyze.py:2546-2552) — generic

Helpers that need a parallel system-keyed version:
- `_group_prompt_cache_rows_by_model` → `_group_prompt_cache_rows_by_system`
- `_compute_model_group_costs` → `_compute_fragmentation_costs` (parameterized by `representative_model_fn`; honest-unmeasurable returns `None` when the model-resolution callback returns `None` — for the system caller, that callback is `_homogeneous_model_for_system_group`, which returns `None` when a group contains heterogeneous models)

### 5. PerCallRow does NOT carry `system`

`PerCallRow` definition at `analyze.py:88-173`. Has `model`, `declared_prompt_cache`, `workflow_path`, `node_path` etc., but no `system`. The detector either:
- (a) Reads `system` from IR at detect-time via `node_by_id[row.node_path]["params"].get("system")` — **chosen in this plan**; keeps `PerCallRow` lean, mirrors how the model-fragmentation detector reads `node_by_id` for similar context (analyze.py:2410), avoids adding a field that only one consumer needs.
- (b) Adds `system: str | None = None` field to `PerCallRow`. Rejected: a data-model change for one consumer. Add only if a 2nd consumer appears.

### 6. Catalog count today

`mcp_server/tools/execution_tools.py:424-425` says **"20 entries in v1 — 19 ``cache.*`` plus 1 ``llm.*``"**. New ID makes it **21 entries — 20 ``cache.*`` plus 1 ``llm.*``**. Update both the count phrase and add the bullet.

### 7. `pflow guide caching` table format

`src/pflow/guide/features/caching.md:212-235`. Table header `| ID | Severity | Triggered by |`. Row format: `` | `cache.foo` | warning | one-clause description | ``. New row added in catalog ID order.

---

## Architecture Decisions

### Decision 1: Generalize via `_detect_cache_fragmentation_by(key_fn=...)`

**User-selected.** Refactor the existing `_detect_model_cache_fragmentation` to delegate fragmentation detection to a parameterized helper. Both `cache.heterogeneous-models-fragment-cache` and `cache.system-prompts-fragment-cache` emit from the same helper.

**Why this is the top-10% answer here**:

1. **The fragmentation pattern IS structural.** Two callers with parallel ~80-line bodies that differ only in (a) the grouping key and (b) the cost-helper variant is the textbook "extract method" precondition. The shared invariant — "shared chunks across groups whose cache prefix bytes diverge → emit one workflow-scoped warning per cause" — locks structurally instead of by convention.

2. **A 3rd fragmentation cause becomes trivial.** Just register a new key_fn + context_builder + warning_id. No copy-paste; the future contributor can't accidentally drift from the established invariant.

3. **The cost-divergence concern is resolved by parameterizing the representative-model lookup.** Both detectors compute cost as `tokens × write_rate × pricing` per group; they differ only in HOW each group selects ITS representative model for pricing. That's a `representative_model_fn(group) -> str | None` callback — clean parameterization, not conditional branches.

### Decision 1a: `cache.first-call-write-penalty` stays model-specific

The existing `_detect_model_cache_fragmentation` ALSO emits `cache.first-call-write-penalty` (per-group write-penalty when one model has only one cache-declaring call). That's a model-specific concept (not a fragmentation cause); it stays in `_detect_model_cache_fragmentation` after the call to the generalized helper.

Resulting shape:

```python
def _detect_model_cache_fragmentation(*, workflow_ir, rows_by_node, declared_chunks, ctx) -> list[Diagnostic]:
    """Emits cache.heterogeneous-models-fragment-cache AND cache.first-call-write-penalty."""
    diagnostics = _detect_cache_fragmentation_by(
        workflow_ir=workflow_ir, rows_by_node=rows_by_node,
        declared_chunks=declared_chunks, ctx=ctx,
        key_fn=lambda row, node: normalize_model_name(row.model),
        warning_id="cache.heterogeneous-models-fragment-cache",
        representative_model_fn=lambda group: str(group["key"]) if group["key"] else None,
        context_builder_fn=_build_model_fragmentation_context,
    )
    # Existing per-group write-penalty loop (lines 2442-2464); unchanged.
    diagnostics.extend(_emit_first_call_write_penalty(...))
    return diagnostics


def _detect_system_cache_fragmentation(*, workflow_ir, rows_by_node, declared_chunks, ctx) -> list[Diagnostic]:
    """Emits cache.system-prompts-fragment-cache."""
    return _detect_cache_fragmentation_by(
        workflow_ir=workflow_ir, rows_by_node=rows_by_node,
        declared_chunks=declared_chunks, ctx=ctx,
        key_fn=lambda row, node: node.get("params", {}).get("system") or None,
        warning_id="cache.system-prompts-fragment-cache",
        representative_model_fn=_homogeneous_model_in_group,
        context_builder_fn=_build_system_fragmentation_context,
    )
```

### Decision 1b: Refactor scope is bounded — only fragmentation detection moves

The generalize-now refactor touches the FRAGMENTATION DETECTION code only. The `cache.first-call-write-penalty` loop stays in place. The shared helpers already in use (`_chunks_shared_with_other_group`, `_chunks_shared_across_groups`, `_sum_chunk_tokens`, `_extract_cache_ttl`) remain unchanged. The renamed cost helper (`_compute_model_group_costs` → `_compute_fragmentation_costs`) gains one parameter (`representative_model_fn`) and changes its key-stringification slightly (group keyed on `group["key"]` instead of `str(group["model"])`).

### Decision 2: Read `system` from IR at detect-time

Per Verified Fact 5 above. Detector takes `workflow_ir` (already in scope at the call site) and looks up each row's node by `(workflow_path, node_path)`. Single consumer; no data-model change.

### Decision 3: Heterogeneous-model-within-system-group → honest-unmeasurable

When a system group contains rows with multiple distinct models, the savings computation returns `None` for that group (honest-unmeasurable). The diagnostic is suppressed if all groups would be unmeasurable. Rationale:

1. **Cross-cutting fix.** If model also fragments, fixing system alone won't unlock cache sharing — the model namespace splits the cache anyway. Reporting savings would mislead.
2. **Model-fragmentation warning takes precedence.** That warning will fire separately and tell the agent about the model issue. System-fragmentation should fire only when system is the dominant fragmentation cause.
3. **Honest-unmeasurable convention.** Established at `_savings_for_shared_ref`, `_compute_model_group_costs`, `_estimate_ref_tokens`. The new helper mirrors it.

### Decision 4: Workflow-scope (root-only) emission

Mirror `_detect_model_cache_fragmentation`. The detector runs once per `analyze()` invocation against the root workflow IR. Sub-workflows are analyzed separately when the user runs `analyze-cache <sub-workflow>`. Diagnostic is emitted with `node_id=None`, `affected_workflow=ctx.workflow_path`.

### Decision 5: Byte-equal compare on unresolved `system:` string

Two nodes' `system:` values are "different" iff `node_a["params"]["system"] != node_b["params"]["system"]` (Python string equality). Includes None vs non-None as different. Includes templates (`${a}` vs `${b}` are different; `${a}` vs `${a}` are same). No fancy normalization — matches `cache.cross-workflow-prose-mismatch` precedent (also byte-equal).

**`params["system_prompt"]` is intentionally NOT read.** The markdown parser maps two distinct fenced-block tags: ```` ```system ```` → `params["system"]` (consumed by `LLMNode`) and ```` ```system_prompt ```` → `params["system_prompt"]` (consumed by `ClaudeCodeNode`). These are different node types' parameters, not aliases. Per Task 159 DD#21, `ClaudeCodeNode` is **out of scope** for pflow's prompt-cache analysis — it uses `claude_agent_sdk` directly and the SDK manages its own caching. `ClaudeCodeNode` rows never reach this detector (no `prompt_cache:` field on Claude nodes). A future reviewer who notices the parser mapping and wonders if `system_prompt:` should be read here: it shouldn't.

---

## Files to Modify

### Production

| File | Change | Estimated LOC |
|---|---|---|
| `src/pflow/core/cache_analysis/warning_catalog.py` | (a) Add `cache.system-prompts-fragment-cache` `CacheWarningSpec` entry with `node_ids_csv` in `required_context_keys`; (b) add to `RECOMMENDED_ACTION_PRIORITY` (priority 10); (c) update module docstring at line 8 (count phrase + prose enumeration) | +37 |
| `src/pflow/core/cache_analysis/analyze.py` | (a) Add `Callable` to `from collections.abc import Iterable, Mapping` at line 27. (b) Step 2a: extract `_detect_cache_fragmentation_by` + `_compute_fragmentation_costs` (rename from `_compute_model_group_costs`); refactor `_detect_model_cache_fragmentation` to wrap and inline the write-penalty loop. (c) Step 2b: add `_detect_system_cache_fragmentation` + `_system_fragmentation_key` + `_homogeneous_model_for_system_group` + `_build_system_fragmentation_context` + `_system_groups_payload` + `_preview_system` + `_format_system_groups_lines` + `_build_model_fragmentation_context`. (d) Step 2c: wire into `analyze()` at the existing call site. | +130 (~50 refactor / ~80 new) |
| `src/pflow/core/cache_analysis/CLAUDE.md:254` | Update count "20 → 21" AND insert new ID into the prose enumeration of catalog IDs | modified text |
| `src/pflow/mcp_server/tools/execution_tools.py:424-445` | Bump count "20 → 21"; bump cache "19 → 20"; insert bullet for new ID | +1, modified text |
| `src/pflow/guide/features/caching.md:212-235` | Add catalog table row; add ~10-line explainer paragraph below the table about the cross-node-sharing constraint and the warning | +15 |

### Tests

| File | Change | Estimated LOC |
|---|---|---|
| `tests/test_core/test_cache_analysis_per_id_emission.py` | (a) New section header + 1 emission test + 4 suppression mutation guards (concrete bodies, not stubs). (b) Lockstep docstring updates for 2 existing model-fragmentation tests at line 2793 and 2896 (renames/inlines from Step 2a). | +210 |
| `tests/test_core/test_cache_analysis_per_id_coverage.py` | Extend `_kwargs_for` with required context for new ID | +15 |
| `tests/test_core/test_cache_analysis_warnings.py` | (a) Bump `assert len(CACHE_WARNING_CATALOG) == 20` to `21`. (b) Rename the catalog-size test so its name doesn't drift from the assertion. (c) Extend `_minimal_context_kwargs` (parallel helper at line 513-676) with the new ID. (d) Update test docstring narrative if it enumerates IDs by name. | +18 |
| `tests/test_execution/test_runner.py:264` | Lockstep docstring update: rename `_compute_model_group_costs` → `_compute_fragmentation_costs` in the comment | modified text |

**Total**: ~410 LOC (roughly 167 production + 244 tests). Production: 37 LOC catalog + 130 LOC analyze.py refactor & new detector + minor docstring updates at 2 metadata sync sites. Tests: 210 LOC new emission/suppression tests + 15 LOC `_kwargs_for` extension + 18 LOC `_minimal_context_kwargs` extension + count assertion bump + cross-file docstring nudge at `test_runner.py:264`.

---

## Implementation

### Step 1: Catalog entry (warning_catalog.py)

Add after `cache.heterogeneous-models-fragment-cache` in the catalog dict. Mirror its shape:

```python
"cache.system-prompts-fragment-cache": CacheWarningSpec(
    severity=Severity.WARNING,
    source="cache_analyzer",
    category=CACHE_WARNING_CATEGORY,
    message_template=(
        "Workflow declares cached chunks shared across {system_group_count} distinct "
        "`system:` instructions. Provider cache prefixes include `system:` content, "
        "so each unique system creates a separate cache namespace; bytes are written "
        "{system_group_count}x instead of 1x.{savings_clause}\n"
        "{system_groups_lines}"
    ),
    required_context_keys=(
        ("system_group_count", int),
        ("system_groups", list),
        ("system_groups_lines", str),
        ("shared_chunks", list),
        ("affected_workflow", str),
        ("savings_usd", float),
        ("node_ids_csv", str),
    ),
    suggestions_template=(
        "Consolidate role-specific text from `system:` into `prompt:` body, leaving "
        "`system:` uniform across {node_ids_csv} so cross-node cache reads fire, OR",
        "Accept per-node caching as the intended tradeoff: each node still benefits "
        "from cross-invocation reads (e.g. across parallel batch fan-out).",
    ),
    path_template="workflows[path={affected_workflow}]",
    nullable_cost_keys=frozenset({"savings_usd"}),
    headline_template=(
        "Cache fragmented across {system_group_count} `system:` prompts — "
        "declared chunks written {system_group_count}x, never shared cross-node"
    ),
),
```

Add to `RECOMMENDED_ACTION_PRIORITY` (warning_catalog.py:710):

```python
"cache.system-prompts-fragment-cache": 10,  # Tier 1 — actionable; sibling of cache.heterogeneous-models-fragment-cache
```

### Step 2: Detector + generalization (analyze.py)

This step has THREE sub-steps. Implement in order; each is a discrete unit.

#### Step 2a: Extract `_detect_cache_fragmentation_by` from `_detect_model_cache_fragmentation`

Refactor the existing detector to delegate fragmentation detection to a generalized helper. Place the helper IMMEDIATELY ABOVE `_detect_model_cache_fragmentation` (so the wrapper reads the helper as already-defined).

**Import update first.** The helper uses `Callable[...]` types in its signature. The existing import line at `analyze.py:27` is `from collections.abc import Iterable, Mapping` — extend it to `from collections.abc import Callable, Iterable, Mapping`. Without this, the helper signature fails type-check.

```python
def _detect_cache_fragmentation_by(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    declared_chunks: list[str],
    ctx: AnalysisContext,
    key_fn: Callable[[PerCallRow, dict[str, Any]], str | None],
    warning_id: str,
    representative_model_fn: Callable[[dict[str, Any]], str | None],
    context_builder_fn: Callable[[list[dict[str, Any]], dict[str, float]], dict[str, Any]],
) -> list[Diagnostic]:
    """Detect ``## Cache`` chunks shared across nodes whose cache prefix bytes
    diverge by ``key_fn``, and emit ``warning_id``.

    This is the shared engine for fragmentation-class catalog warnings. Today
    it powers two: ``cache.heterogeneous-models-fragment-cache`` (key_fn =
    model) and ``cache.system-prompts-fragment-cache`` (key_fn = system).
    Adding a 3rd fragmentation cause requires only a key_fn, a
    representative_model_fn (for pricing), a context_builder_fn (for the
    diagnostic payload), and registering the new catalog entry.

    Algorithm (mirrors the original ``_detect_model_cache_fragmentation``):
      1. Filter rows: declared_prompt_cache truthy, NOT model_is_heterogeneous,
         NOT did_not_execute_in_trace, IR node resolvable.
      2. Group rows by ``key_fn(row, node)``; each group accumulates rows and
         a set-union of declared chunks.
      3. Find fragmented groups (chunks overlap with another group).
      4. Sort by row count descending, then key string ascending (deterministic
         "largest group wins" for redundant-write attribution).
      5. Compute redundant-write costs per group via
         ``_compute_fragmentation_costs`` (uses representative_model_fn for
         pricing; honest-unmeasurable returns ``None``).
      6. Filter to groups whose total tokens cleared the model min-cache
         threshold; gate on ``>= 2`` remaining.
      7. Emit ONE workflow-scoped diagnostic with shared_chunks, savings_usd,
         and the caller-specific context from context_builder_fn.

    Returns ``[]`` (not raise) on any honest-unmeasurable signal — agents
    receive silence, not a misleading diagnostic.
    """
    if not declared_chunks:
        return []

    node_by_id = {
        str(n.get("id")): n
        for n in workflow_ir.get("nodes", [])
        if isinstance(n, dict) and n.get("id")
    }
    rows_with_keys: list[tuple[PerCallRow, str | None]] = []
    for row in rows_by_node.values():
        if not row.declared_prompt_cache:
            continue
        # Preserve pre-refactor model-fragmentation semantics: rows without a
        # resolved model can't be priced and were filtered at row-collection
        # time in the legacy detector (analyze.py:2400). Keep the filter here
        # so both fragmentation causes get the same row-level invariant.
        if not row.model:
            continue
        if row.model_is_heterogeneous or row.did_not_execute_in_trace:
            continue
        node = node_by_id.get(row.node_path)
        if node is None:
            continue
        rows_with_keys.append((row, key_fn(row, node)))

    if not rows_with_keys:
        return []

    # Group by key. ``None`` and ``""`` collapse into the same bucket via the
    # ``key or ""`` normalization — they represent the same "no-distinguishing-
    # value" semantic at the cache-prefix level.
    groups: dict[str, dict[str, Any]] = {}
    for row, key in rows_with_keys:
        bucket_key = key or ""
        group = groups.setdefault(bucket_key, {"key": key, "rows": [], "chunks": set()})
        group["rows"].append(row)
        group["chunks"].update(str(chunk) for chunk in row.declared_prompt_cache or ())

    fragmented_groups = [
        group
        for group in groups.values()
        if _chunks_shared_with_other_group(group, groups.values())
    ]
    if len(fragmented_groups) < 2:
        return []

    sorted_groups = sorted(
        fragmented_groups,
        key=lambda group: (-len(group["rows"]), str(group["key"] or "")),
    )
    shared_chunks = _chunks_shared_across_groups(sorted_groups)
    costs = _compute_fragmentation_costs(
        sorted_groups,
        shared_chunks,
        ttl=_extract_cache_ttl(workflow_ir.get("cache")),
        ctx=ctx,
        representative_model_fn=representative_model_fn,
    )
    if costs is None:
        return []
    participating_groups = [
        group for group in sorted_groups if str(group["key"] or "") in costs
    ]
    if len(participating_groups) < 2:
        return []

    redundant_groups = participating_groups[1:]
    savings_usd = sum(costs[str(group["key"] or "")] for group in redundant_groups)
    extra_context = context_builder_fn(participating_groups, costs)
    return [
        make_diagnostic(
            warning_id,
            node_id=None,
            shared_chunks=sorted(shared_chunks),
            affected_workflow=ctx.workflow_path,
            savings_usd=savings_usd,
            **extra_context,
        )
    ]


def _compute_fragmentation_costs(
    groups: list[dict[str, Any]],
    shared_chunks: set[str],
    *,
    ttl: str | None,
    ctx: AnalysisContext,
    representative_model_fn: Callable[[dict[str, Any]], str | None],
) -> dict[str, float] | None:
    """Sum each group's redundant cache_creation cost over the SHARED chunks.

    Renamed from ``_compute_model_group_costs``: now parameterized by
    ``representative_model_fn`` so each fragmentation cause picks its own
    pricing model. Honest-unmeasurable: returns ``None`` if any group's
    representative model is missing or unpriced, or any shared chunk has
    no resolvable token estimate.

    Below-threshold groups are silently dropped (caller's ``>= 2``
    participating-groups gate handles the suppression).
    """
    from .cost_estimation import _write_rate_for_ttl, get_model_pricing

    costs: dict[str, float] = {}
    for group in groups:
        model = representative_model_fn(group)
        if model is None:
            return None
        pricing = get_model_pricing(model)
        if pricing is None:
            return None
        group_shared = group["chunks"] & shared_chunks
        total_tokens = _sum_chunk_tokens(
            list(group_shared), model, ctx, ctx.memo_cache, ctx.workflow_path
        )
        if total_tokens is None:
            return None
        if total_tokens < get_min_cache_tokens(model):
            continue
        costs[str(group["key"] or "")] = total_tokens * _write_rate_for_ttl(pricing, ttl, model)
    return costs
```

Then refactor `_detect_model_cache_fragmentation` to wrap the helper. The function now has TWO jobs (fragmentation detection + write-penalty emission); fragmentation goes through the helper, write-penalty stays as-is.

```python
def _detect_model_cache_fragmentation(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    declared_chunks: list[str],
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Emit cache.heterogeneous-models-fragment-cache (fragmentation) AND
    cache.first-call-write-penalty (per-model single-call detection).

    Fragmentation detection delegates to ``_detect_cache_fragmentation_by``;
    write-penalty stays inline because it's a model-specific concept (one
    model with one cache-declaring call → cache_creation cost paid without
    amortization).
    """
    diagnostics = _detect_cache_fragmentation_by(
        workflow_ir=workflow_ir,
        rows_by_node=rows_by_node,
        declared_chunks=declared_chunks,
        ctx=ctx,
        key_fn=lambda row, node: normalize_model_name(row.model),
        warning_id="cache.heterogeneous-models-fragment-cache",
        representative_model_fn=lambda group: str(group["key"]) if group["key"] else None,
        context_builder_fn=_build_model_fragmentation_context,
    )

    # First-call-write-penalty: existing per-group loop, copied verbatim from
    # the pre-refactor _detect_model_cache_fragmentation (analyze.py:2442-2464).
    # The helper above operates on a different group dict shape ({"key", "rows",
    # "chunks"}); the write-penalty loop needs the original {"model", "rows",
    # "chunks"} shape AND its own node_by_id lookup. Build them locally so the
    # generalized helper doesn't have to leak this single-detector concern.
    rows = [
        row for row in rows_by_node.values()
        if row.declared_prompt_cache and row.model
        and not row.model_is_heterogeneous and not row.did_not_execute_in_trace
    ]
    if rows:
        legacy_groups = _group_prompt_cache_rows_by_model(rows)
        node_by_id = {
            str(n.get("id")): n
            for n in workflow_ir.get("nodes", [])
            if isinstance(n, dict) and n.get("id")
        }
        ttl = _extract_cache_ttl(workflow_ir.get("cache"))
        for group in sorted(legacy_groups.values(), key=lambda item: str(item["model"])):
            group_rows = group["rows"]
            if len(group_rows) != 1:
                continue
            row = group_rows[0]
            node = node_by_id.get(row.node_path)
            if isinstance(node, dict) and node.get("prewarm") is True:
                continue
            model = str(group["model"])
            if model.startswith("gemini/"):
                continue
            penalty = _single_call_write_penalty(row, ttl=ttl)
            if penalty is None:
                continue
            diagnostics.append(
                make_diagnostic(
                    "cache.first-call-write-penalty",
                    node_id=row.node_path,
                    model=model,
                    affected_workflow=ctx.workflow_path,
                    savings_usd=penalty,
                )
            )

    return diagnostics


def _build_model_fragmentation_context(
    participating_groups: list[dict[str, Any]],
    costs: dict[str, float],
) -> dict[str, Any]:
    """Build the diagnostic context for cache.heterogeneous-models-fragment-cache.

    Reads directly from the helper's ``{"key", "rows", "chunks"}`` group shape
    via the now-generalized ``_model_groups_payload`` (see Step 2a's
    payload-helper update). No reshape needed — group["key"] IS the
    normalized model string for the model-fragmentation caller.
    """
    model_groups = _model_groups_payload(participating_groups, costs)
    return {
        "model_group_count": len(participating_groups),
        "models_csv": ", ".join(str(group["key"]) for group in participating_groups),
        "model_groups": model_groups,
        "model_groups_lines": _format_model_groups_lines(model_groups),
    }
```

**Payload helper update as part of Step 2a.** `_model_groups_payload` at `analyze.py:2532-2543` reads `str(group["model"])` from each input group. After the refactor, the model context-builder passes the helper's `{"key", "rows", "chunks"}` group shape directly (no reshape). Change the one line inside the loop:

```python
def _model_groups_payload(groups: list[dict[str, Any]], costs: dict[str, float]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for group in groups:
        rows = sorted(group["rows"], key=lambda row: row.node_path)
        model = str(group["key"])  # was: str(group["model"])
        payload.append({
            "model": model,
            "node_paths": [row.node_path for row in rows],
            "node_count": len(rows),
            "cache_creation_cost_usd": costs[model],
        })
    return payload
```

The OUTPUT shape is unchanged — payload entries still have a `"model"` field, so the diagnostic context, JSON renderer, text renderer, and `_format_model_groups_lines` (which reads `entry["model"]` from the OUTPUT payload, not the input groups) all see the same bytes pre- and post-refactor. The only change is the input-side key name: `group["model"]` → `group["key"]`.

This eliminates the reshape that earlier plan revisions threaded through `_build_model_fragmentation_context`. The asymmetry left behind: `_group_prompt_cache_rows_by_model` (still used by the write-penalty loop) produces `{"model", "rows", "chunks"}`, while `_detect_cache_fragmentation_by` (the generalized helper) produces `{"key", "rows", "chunks"}`. They consume into different code paths so the asymmetry is invisible to callers; document it in the docstrings of both functions.

**Helper cleanup as part of Step 2a.** After the refactor, `_model_groups_with_shared_chunks` (`analyze.py:2479-2480`) is orphaned — the new `_detect_cache_fragmentation_by` uses an inline list comprehension calling `_chunks_shared_with_other_group` directly (plan recipe lines 333-335). **Delete `_model_groups_with_shared_chunks`** as part of Step 2a; mypy/ruff won't flag it (module-private function, valid by reference), so leaving it would silently rot. `_group_prompt_cache_rows_by_model` and `_chunks_shared_with_other_group` both stay — the write-penalty loop still needs `_group_prompt_cache_rows_by_model`, and `_chunks_shared_with_other_group` is now called inline by the helper.

**Verify before proceeding to 2b**: run the existing **8** model-fragmentation cluster tests at `tests/test_core/test_cache_analysis_per_id_emission.py`:

1. `test_fragmentation_fires_for_two_exact_models_sharing_chunks` (line 2716)
2. `test_fragmentation_silent_when_single_model` (line 2758)
3. `test_fragmentation_silent_when_no_chunk_overlap` (line 2789)
4. `test_fragmentation_skips_heterogeneous_batch_rows` (line 2826)
5. `test_fragmentation_skips_when_any_group_cost_is_none` (line 2859)
6. `test_fragmentation_skips_when_shared_chunk_tokens_unmeasurable` (line 2891)
7. `test_fragmentation_suppresses_when_only_one_model_group_meets_threshold` (line 2926)
8. `test_fragmentation_and_write_penalty_coemit_when_one_group_has_size_one` (line 3110)

All 8 must pass. If any fail, the refactor introduced a regression — fix before adding system-fragmentation.

**Also: lockstep docstring updates.** Three test docstrings reference symbols that the refactor renames or inlines. Update these in the same step (mechanical text edits, no test logic change):

- `tests/test_execution/test_runner.py:264` — comment mentions `_compute_model_group_costs` → update to `_compute_fragmentation_costs`
- `tests/test_core/test_cache_analysis_per_id_emission.py:2793` — mutation contract docstring references `_model_groups_with_shared_chunks` → update to "the inline `_chunks_shared_with_other_group` filter inside `_detect_cache_fragmentation_by`"
- `tests/test_core/test_cache_analysis_per_id_emission.py:2896` — mutation contract docstring references `_compute_model_group_costs` → update to `_compute_fragmentation_costs`

#### Step 2b: Add `_detect_system_cache_fragmentation` wrapper

Insert immediately after the model-fragmentation function. Thin wrapper around the helper:

```python
def _detect_system_cache_fragmentation(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    declared_chunks: list[str],
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Emit cache.system-prompts-fragment-cache.

    Provider cache prefixes for Anthropic/Gemini include the ``system:``
    content block before the first ``cache_control`` marker. Two LLM nodes
    that share ``prompt_cache:`` chunks but declare distinct ``system:``
    strings produce distinct prefix bytes and cannot share the provider
    cache. This detector groups rows by ``system:`` value and fires when
    chunk overlap exists across distinct system groups.

    Defers to ``cache.heterogeneous-models-fragment-cache`` when a system
    group has heterogeneous internal models — the model namespace already
    splits the cache; fixing system alone wouldn't unlock sharing.
    """
    return _detect_cache_fragmentation_by(
        workflow_ir=workflow_ir,
        rows_by_node=rows_by_node,
        declared_chunks=declared_chunks,
        ctx=ctx,
        key_fn=_system_fragmentation_key,
        warning_id="cache.system-prompts-fragment-cache",
        representative_model_fn=_homogeneous_model_for_system_group,
        context_builder_fn=_build_system_fragmentation_context,
    )


def _system_fragmentation_key(row: PerCallRow, node: dict[str, Any]) -> str | None:
    """Return the row's ``system:`` value (or None for absent/empty)."""
    system_value = node.get("params", {}).get("system")
    if not isinstance(system_value, str) or not system_value:
        return None
    return system_value


def _homogeneous_model_for_system_group(group: dict[str, Any]) -> str | None:
    """Return the single model used by all rows in the group, or None if mixed.

    Honest-unmeasurable: heterogeneous models within a system group means the
    provider cache namespace already splits by model; fixing system alone
    wouldn't unlock sharing. Return None to defer to model-fragmentation.
    """
    models = {row.model for row in group["rows"] if row.model}
    if len(models) != 1:
        return None
    return next(iter(models))


def _build_system_fragmentation_context(
    participating_groups: list[dict[str, Any]],
    costs: dict[str, float],
) -> dict[str, Any]:
    """Build the diagnostic context for cache.system-prompts-fragment-cache."""
    payload = _system_groups_payload(participating_groups, costs)
    node_ids_csv = ", ".join(
        sorted({row.node_path for group in participating_groups for row in group["rows"]})
    )
    return {
        "system_group_count": len(participating_groups),
        "system_groups": payload,
        "system_groups_lines": _format_system_groups_lines(payload),
        "node_ids_csv": node_ids_csv,
    }


def _system_groups_payload(
    groups: list[dict[str, Any]],
    costs: dict[str, float],
) -> list[dict[str, Any]]:
    """JSON-friendly payload for the diagnostic context.

    Each entry: ``{system_preview, node_ids, redundant_write_usd}``. The
    system_preview truncates to ~80 chars for display; full strings are
    available via the row data if needed.
    """
    return [
        {
            "system_preview": _preview_system(group["key"]),
            "node_ids": sorted(row.node_path for row in group["rows"]),
            "redundant_write_usd": costs[str(group["key"] or "")],
        }
        for group in groups
    ]


def _preview_system(system: str | None) -> str:
    if not system:
        return "(no system)"
    text = system.replace("\n", " ⏎ ")
    return text if len(text) <= 80 else text[:77] + "…"


def _format_system_groups_lines(payload: list[dict[str, Any]]) -> str:
    """Render the per-group breakdown for the message_template."""
    return "\n".join(
        f"  - `{entry['system_preview']}` → {len(entry['node_ids'])} node(s): "
        f"{', '.join(entry['node_ids'])}"
        for entry in payload
    )
```

#### Step 2c: Wire detector into `analyze()`

At the existing call site (`analyze.py:633-640`), append a parallel `extend` after the model-fragmentation invocation:

```python
warnings.extend(
    _detect_model_cache_fragmentation(
        workflow_ir=workflow_ir,
        rows_by_node=rows_by_node,
        declared_chunks=declared_chunks,
        ctx=ctx,
    )
)
warnings.extend(
    _detect_system_cache_fragmentation(
        workflow_ir=workflow_ir,
        rows_by_node=rows_by_node,
        declared_chunks=declared_chunks,
        ctx=ctx,
    )
)
```

**Note on `_compute_model_group_costs` rename**: the original helper at `analyze.py:2500-2529` was `_compute_model_group_costs`. After Step 2a it becomes `_compute_fragmentation_costs` (parameterized). Search for all internal references to the old name and update — likely only the one call site inside the (now-extracted) helper. The model-fragmentation tests at `test_cache_analysis_per_id_emission.py:2859, 2891, 2926` reference `analyze_module.get_min_cache_tokens` and pricing helpers via monkeypatch but don't call `_compute_model_group_costs` directly; verify with grep before renaming.

### Step 3: Catalog metadata sync (5 sites)

Adding the 21st catalog entry creates documentation drift in 5 places. Update ALL of them in this step — text-only edits, no logic changes.

**Site 1 — `src/pflow/core/cache_analysis/warning_catalog.py:8` (module docstring)**

The module docstring opens with a prose enumeration of all catalog entries. Update the count phrase AND insert the new ID into the prose:

```
20 entries: 14 ``cache.*`` from v1 + ``cache.prompt-body-duplicates-cache`` and
```

becomes:

```
21 entries: 14 ``cache.*`` from v1 + ``cache.prompt-body-duplicates-cache`` and
```

…and insert into the prose enumeration alongside the other Stage-2 fragmentation additions:

```
…``cache.heterogeneous-models-fragment-cache`` and ``cache.first-call-write-
penalty`` (Stage 2 follow-up: detect exact-model cache namespace fragmentation
and lone cache writes) + ``cache.system-prompts-fragment-cache`` (Task 159
PR #378 review-fix #5: detect cross-node cache fragmentation caused by
divergent ``system:`` strings) + ``cache.sub-workflow-cache-undeclared``…
```

**Site 2 — `src/pflow/core/cache_analysis/CLAUDE.md:254` (catalog enumeration)**

The file enumerates every catalog ID by name. Update the count AND insert the new ID:

```
**Stable warning ID catalog has 20 entries** as of v1: ... + `cache.heterogeneous-models-fragment-cache` + `cache.first-call-write-penalty` + `cache.sub-workflow-cache-undeclared` + `llm.thinking-temperature-mismatch`.
```

becomes:

```
**Stable warning ID catalog has 21 entries** as of v1: ... + `cache.heterogeneous-models-fragment-cache` + `cache.first-call-write-penalty` + `cache.system-prompts-fragment-cache` + `cache.sub-workflow-cache-undeclared` + `llm.thinking-temperature-mismatch`.
```

**Site 3 — `src/pflow/mcp_server/tools/execution_tools.py:424-425` (MCP docstring)**

```
**Closed catalog of warning IDs** that may appear in
``warnings[].id`` (21 entries in v1 — 20 ``cache.*`` plus 1 ``llm.*``):
```

Add bullet (alphabetical-ish; insert after `cache.shared-context-undeclared` block to keep grouping):

```
  - cache.system-prompts-fragment-cache
```

**Site 4 — `tests/test_core/test_cache_analysis_warnings.py` count assertion**

`test_catalog_has_twenty_entries_v1` (line 46-68 area): bump the `assert len(CACHE_WARNING_CATALOG) == 20` to `21`. Also rename the test to `test_catalog_has_twentyone_entries_v1` (or generalize to `test_catalog_size`) — leaving the function name out of sync with the assertion is its own drift class.

The test docstring narrative (which enumerates the IDs) also needs the new ID inserted.

**Site 5 — `pflow guide caching` table (Step 4 below)**

Catalog-table row + cross-node-sharing constraint explainer. Covered in Step 4.

### Step 4: pflow guide (caching.md)

Add table row (alphabetical position, after `cache.sub-workflow-cache-undeclared`):

```markdown
| `cache.system-prompts-fragment-cache` | warning | shared cached chunks declared across nodes with distinct `system:` instructions |
```

Add a small explainer below the table (Path A documentation):

```markdown
### Cross-node cache sharing requires uniform `system:`

Provider cache prefixes (Anthropic, Gemini) include the `system:` content. When
two LLM nodes share `prompt_cache:` chunks but declare different `system:`
instructions, each node creates its own cache namespace — cross-node sharing
does NOT fire. Each node still benefits from cross-invocation cache reads
(e.g. parallel batch fan-out), but the workflow-wide savings are lower than if
`system:` were uniform.

`pflow analyze-cache` surfaces this pattern as
`cache.system-prompts-fragment-cache`. To unlock cross-node sharing, move
role-specific text from `system:` into the `prompt:` body and keep `system:`
uniform across nodes that share cache chunks.
```

### Step 5: Tests (test_cache_analysis_per_id_emission.py)

Insert new section after the heterogeneous-models section (~line 2965). Naming follows the existing `test_fragmentation_*` precedent but qualifies with `system_`. **All five tests have concrete bodies and mutation contracts that point at real recipe symbols** — no stubs.

```python
# ---------------------------------------------------------------------------
# cache.system-prompts-fragment-cache — shared chunks across distinct system: prompts
#
# Detector: ``_detect_system_cache_fragmentation`` in ``analyze.py``.
# Generalized engine: ``_detect_cache_fragmentation_by``.
# Sibling: ``cache.heterogeneous-models-fragment-cache``.
# ---------------------------------------------------------------------------


def test_system_fragmentation_fires_for_two_distinct_system_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two LLM nodes share a cache chunk but declare different ``system:``
    instructions (same model). The analyzer warns because cross-node cache
    sharing requires uniform system content.

    Mutation contract: remove the ``len(fragmented_groups) < 2`` early-return
    in ``_detect_cache_fragmentation_by`` (recipe gate at the
    ``fragmented_groups`` stage). With the gate removed the helper still
    returns ``[]`` because the participating-groups gate at
    ``len(participating_groups) < 2`` also fires — BUT removing BOTH gates
    causes the warning to fire on the single-group degenerate case. This
    test pins the emission path; ``test_system_fragmentation_silent_when_uniform_system``
    pins the suppression path.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "You are a lyricist.", "prompt": "Draft."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "You are an emotional reviewer.", "prompt": "Review."},
            },
        ],
    }
    analysis = analyze(
        workflow_ir, parameters={"context": "stable " * 200}, auto_load_trace=False
    )
    found = [d for d in analysis.warnings if d.id == "cache.system-prompts-fragment-cache"]
    assert found, f"system-fragmentation warning missing: ids={[d.id for d in analysis.warnings]}"
    ctx_ = found[0].context
    assert ctx_ is not None
    assert ctx_["system_group_count"] == 2
    assert ctx_["shared_chunks"] == ["context"]
    assert {entry["system_preview"] for entry in ctx_["system_groups"]} == {
        "You are a lyricist.",
        "You are an emotional reviewer.",
    }
    assert ctx_["node_ids_csv"] == "draft, review"


def test_system_fragmentation_silent_when_uniform_system(monkeypatch: pytest.MonkeyPatch) -> None:
    """Identical ``system:`` across nodes → only ONE bucket forms in the
    helper's group-by-key step → no chunk-overlap-across-groups → suppressed
    at the ``len(fragmented_groups) < 2`` gate.

    Mutation contract: change the helper's grouping line ``bucket_key = key
    or ""`` to ``bucket_key = id(row)`` — every row lands in its own bucket,
    fragmentation falsely fires. This test fails when the bucketing logic
    breaks.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "You are a lyricist.", "prompt": "Draft."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "You are a lyricist.", "prompt": "Review."},
            },
        ],
    }
    analysis = analyze(
        workflow_ir, parameters={"context": "stable " * 200}, auto_load_trace=False
    )
    assert "cache.system-prompts-fragment-cache" not in {d.id for d in analysis.warnings}


def test_system_fragmentation_silent_when_no_chunk_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two distinct systems, but no chunk shared across them → no
    fragmentation by definition.

    Mutation contract: remove the ``_chunks_shared_with_other_group`` call
    inside ``_detect_cache_fragmentation_by`` (the inline filter at the
    ``fragmented_groups = [...]`` list comprehension). Without it, every
    group looks fragmented and the warning fires on a workflow with no
    cross-node chunk overlap.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "cache": {
            "items": [
                {"name": "a", "var": "a", "prose_before": "A:\n"},
                {"name": "b", "var": "b", "prose_before": "B:\n"},
            ]
        },
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["a"],
                "params": {"system": "You are a lyricist.", "prompt": "Draft."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["b"],
                "params": {"system": "You are an emotional reviewer.", "prompt": "Review."},
            },
        ],
    }
    analysis = analyze(
        workflow_ir,
        parameters={"a": "stable " * 200, "b": "stable " * 200},
        auto_load_trace=False,
    )
    assert "cache.system-prompts-fragment-cache" not in {d.id for d in analysis.warnings}


def test_system_fragmentation_skips_when_groups_have_heterogeneous_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a system group contains rows with multiple distinct models, defer
    to ``cache.heterogeneous-models-fragment-cache``.

    Three nodes: A and B share ``system: "X"`` but use different models;
    C has ``system: "Y"`` (same model as A). The system-fragmentation
    detector forms two groups (X = {A, B}, Y = {C}). For the X group,
    ``_homogeneous_model_for_system_group`` returns ``None`` (mixed models),
    causing ``_compute_fragmentation_costs`` to return ``None``, causing
    the helper to return ``[]``. Model-fragmentation fires separately
    because A's and B's models differ.

    Mutation contract: change ``_homogeneous_model_for_system_group`` to
    ``return next(iter(models))`` (drop the ``len(models) != 1`` guard).
    With the guard removed, the system-fragmentation warning fires on a
    workflow whose actual fragmentation cause is model namespace splitting.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "node-a",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "X", "prompt": "A."},
            },
            {
                "id": "node-b",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "X", "prompt": "B."},
            },
            {
                "id": "node-c",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "Y", "prompt": "C."},
            },
        ],
    }
    analysis = analyze(
        workflow_ir, parameters={"context": "stable " * 200}, auto_load_trace=False
    )
    ids = {d.id for d in analysis.warnings}
    assert "cache.system-prompts-fragment-cache" not in ids
    assert "cache.heterogeneous-models-fragment-cache" in ids


def test_system_fragmentation_fires_when_one_node_has_no_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One node has ``system: "X"``, the other has no ``system:`` declared.
    They land in separate buckets (the helper's ``bucket_key = key or ""``
    collapses absent/empty into the ``""`` bucket; ``"X"`` lives in its own).
    Two distinct buckets sharing a chunk → warning fires.

    Mutation contract: change ``_system_fragmentation_key`` to return
    ``system_value or ""`` (empty string fallback) instead of returning
    ``None`` for absent. Combined with the helper's ``bucket_key = key or
    ""``, both rows would land in the ``""`` bucket and the warning would
    NOT fire — this test fails on that mutation.

    NOTE: The test name uses ``fires_when`` (not ``silent_when``) — absent
    vs declared system IS fragmentation, because the rendered cache prefix
    bytes differ.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "with-system",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "X", "prompt": "A."},
            },
            {
                "id": "without-system",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "B."},
            },
        ],
    }
    analysis = analyze(
        workflow_ir, parameters={"context": "stable " * 200}, auto_load_trace=False
    )
    assert "cache.system-prompts-fragment-cache" in {d.id for d in analysis.warnings}
```

### Step 6: Coverage tests (TWO parallel helpers — must update both)

There are **two parallel test helpers** that build minimal context for every catalog ID, both parametrized over `sorted(CACHE_WARNING_CATALOG.keys())`. Without an entry in BOTH, parametrize collection raises `KeyError` at test discovery time.

**Helper 1 — `_kwargs_for` in `tests/test_core/test_cache_analysis_per_id_coverage.py`**

Add `"cache.system-prompts-fragment-cache"` entry with all required keys:

```python
"cache.system-prompts-fragment-cache": {
    "system_group_count": 2,
    "system_groups": [
        {"system_preview": "X", "node_ids": ["a"], "redundant_write_usd": 0.001},
        {"system_preview": "Y", "node_ids": ["b"], "redundant_write_usd": 0.002},
    ],
    "system_groups_lines": "  - `X` → 1 node(s): a\n  - `Y` → 1 node(s): b",
    "shared_chunks": ["context"],
    "affected_workflow": "x.pflow.md",
    "savings_usd": 0.001,
    "node_ids_csv": "a, b",
},
```

**Helper 2 — `_minimal_context_kwargs` in `tests/test_core/test_cache_analysis_warnings.py:513-676`**

This is a parallel helper driving `test_every_id_round_trips_through_make_diagnostic` (line 687, parametrized over `sorted(CACHE_WARNING_CATALOG.keys())`). Add the same entry here. The plan author missed this duplicate by name; without the entry, CI fails noisily at parametrize time.

```python
"cache.system-prompts-fragment-cache": {
    "system_group_count": 2,
    "system_groups": [
        {"system_preview": "X", "node_ids": ["a"], "redundant_write_usd": 0.001},
        {"system_preview": "Y", "node_ids": ["b"], "redundant_write_usd": 0.002},
    ],
    "system_groups_lines": "  - `X` → 1 node(s): a\n  - `Y` → 1 node(s): b",
    "shared_chunks": ["context"],
    "affected_workflow": "x.pflow.md",
    "savings_usd": 0.001,
    "node_ids_csv": "a, b",
},
```

**Catalog-size assertion — `tests/test_core/test_cache_analysis_warnings.py`**

The test at line 46-68 (function name like `test_catalog_has_twenty_entries_v1`) asserts `len(CACHE_WARNING_CATALOG) == 20`. Bump to `21`. **Also rename the test** (e.g., to `test_catalog_size_matches_v1_inventory`) so the function name doesn't drift from the assertion. Update the test docstring's narrative enumeration if it lists IDs by name (per Step 3 Site 4).

---

## Verification

### Test commands

After each step:
```bash
# Just the new tests (fastest feedback):
.venv/bin/python -m pytest tests/test_core/test_cache_analysis_per_id_emission.py -k system_fragmentation -v

# Catalog coverage gate:
.venv/bin/python -m pytest tests/test_core/test_cache_analysis_per_id_coverage.py -v

# Catalog count assertion:
.venv/bin/python -m pytest tests/test_core/test_cache_analysis_warnings.py -v
```

After all steps land:
```bash
# Default suite (must pass; ~6,343 tests after 5 new + 0 deletions):
make test

# Static checks:
make check

# DD#19 byte-identity gate (must remain green; this PR doesn't touch hash path):
.venv/bin/python -m pytest tests/test_runtime/test_prompt_cache_hash.py::test_golden_baseline_hashes_match -v

# Plan ↔ engine parity (must remain green; this PR doesn't touch plan_node):
.venv/bin/python -m pytest tests/test_execution/test_plan_drift.py -v
```

### End-to-end smoke against motivating workflow

Run analyze-cache against a 2-node workflow that explicitly demonstrates the warning:

```bash
cat > /tmp/system-fragment-smoke.pflow.md <<'EOF'
# System Fragment Smoke

## Inputs

### context

## Cache

```cache
The shared context:

${context}
```

## Steps

### draft
- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [context]
- system: "You are a lyricist."
- prompt: "Draft."

### review
- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [context]
- system: "You are an emotional reviewer."
- prompt: "Review."
EOF

uv run pflow analyze-cache /tmp/system-fragment-smoke.pflow.md context="$(printf 'stable %.0s' {1..500})"
```

Expected: warning section includes `cache.system-prompts-fragment-cache` with `system_group_count=2`, both system previews shown, redundant-write savings populated.

### Mutation-test verification (manual, optional but high-value)

For each new test, verify the mutation contract by temporarily reverting the production logic and confirming the test fails:

| Test | Mutation site (recipe symbol) | Expected failure |
|---|---|---|
| `test_system_fragmentation_fires_for_two_distinct_system_prompts` | Remove BOTH `len(fragmented_groups) < 2` AND `len(participating_groups) < 2` early-returns in `_detect_cache_fragmentation_by` | Test fails: warning still missing under one-gate removal; under both-gates removal a single-bucket workflow produces a false-positive |
| `test_system_fragmentation_silent_when_uniform_system` | Change `bucket_key = key or ""` in `_detect_cache_fragmentation_by` to `bucket_key = id(row)` | Test fails: every row lands in its own bucket → fragmentation falsely fires |
| `test_system_fragmentation_silent_when_no_chunk_overlap` | Remove the `_chunks_shared_with_other_group(group, groups.values())` predicate from the `fragmented_groups = [...]` list comprehension in `_detect_cache_fragmentation_by` | Test fails: warning fires on non-overlapping chunks |
| `test_system_fragmentation_skips_when_groups_have_heterogeneous_models` | Change `_homogeneous_model_for_system_group` to `return next(iter(models))` (drop the `len(models) != 1` guard) | Test fails: warning fires when model-fragmentation should take over |
| `test_system_fragmentation_fires_when_one_node_has_no_system` | Change `_system_fragmentation_key` to `return system_value or ""` instead of returning `None` for absent | Test fails: both rows land in the `""` bucket and the warning is suppressed |

### Acceptance criteria

The change is complete when:

1. `CACHE_WARNING_CATALOG` has exactly 21 entries; `RECOMMENDED_ACTION_PRIORITY` has matching entry at priority 10.
2. `_detect_system_cache_fragmentation` is invoked from `analyze()` immediately after `_detect_model_cache_fragmentation`.
3. Both detectors carry sibling cross-reference comments.
4. MCP docstring count phrase reads "21 entries in v1 — 20 cache plus 1 llm".
5. `pflow guide caching` table has new row + cross-node-sharing constraint explainer.
6. Five new tests pass; mutation contracts in docstrings.
7. `make test` passes (~6,343 tests).
8. `make check` passes (ruff + ruff-format + mypy + deptry).
9. `test_golden_baseline_hashes_match` and `test_plan_drift.py` remain green (this PR is analyzer-only; runtime is untouched).
10. End-to-end smoke against the 2-node fixture renders the warning correctly.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `node.get("params", {}).get("system")` returns non-string (e.g., dict from a `system_prompt` code-block fenced as YAML) | L | M | Verified: `system` is NOT in `_CODE_BLOCK_TAG_TO_PARAM`'s yaml-config set; always raw string. Guard with `if not isinstance(system_value, str): system_value = None` defensively. |
| Adding the detector adds non-trivial wall-clock time to `analyze()` | VL | L | Detector is O(N²) on number of LLM nodes for chunk-overlap detection but N is typically <30; <1ms in practice. The model-fragmentation sibling has the same complexity and runs cleanly. |
| `_homogeneous_model_for_system_group` (and via it, `_compute_fragmentation_costs`) returns `None` too aggressively, suppressing legitimate warnings | M | M | The "heterogeneous internal models" check is the most likely culprit. Mitigated by Decision 3: we WANT this case to defer to model-fragmentation. `test_system_fragmentation_skips_when_groups_have_heterogeneous_models` locks the intended behavior. |
| Cross-emission with `cache.heterogeneous-models-fragment-cache` produces overwhelming output for workflows with both fragmentation causes | M | L | Both warnings fire. Both are actionable independently. Renderer doesn't dedupe; the agent sees both findings, can fix both. Same precedent as `cache.first-call-write-penalty` co-firing with `cache.heterogeneous-models-fragment-cache`. |
| `system_groups_lines` rendering has formatting drift vs `model_groups_lines` | L | L | Mirror the format string structure; renderer test catches drift. |
| Catalog count update missed at one of the 5 sync sites | M | L | Step 3 enumerates ALL 5: `warning_catalog.py:8` module docstring, `cache_analysis/CLAUDE.md:254` ID enumeration, `mcp_server/tools/execution_tools.py:424` MCP docstring, `tests/test_core/test_cache_analysis_warnings.py` count assertion + narrative, `guide/features/caching.md` table (Step 4). Step 6 separately covers the two parallel `_kwargs_for` / `_minimal_context_kwargs` helpers. |
| Future contributor adds a 3rd fragmentation cause and reinvents the pattern | L | L | Mitigated by Decision 1's generalization: a 3rd cause now requires only a key_fn + representative_model_fn + context_builder_fn + a thin wrapper. The shape is locked structurally by `_detect_cache_fragmentation_by`'s signature; can't accidentally drift. |
| Refactor in Step 2a breaks the 6 existing model-fragmentation tests | M | H | Verify by running the model-fragmentation test section IMMEDIATELY after Step 2a, BEFORE adding new tests. If any of the 6 fail, the refactor introduced a regression — fix before proceeding to 2b. The shared-helper `_compute_fragmentation_costs` has the same signature as the old `_compute_model_group_costs` modulo the new `representative_model_fn` parameter and the group-key stringification (`group["key"]` vs `group["model"]`). Both changes are mechanical — drift would manifest as off-by-one in the cost dict keying. |
| Group-dict shape asymmetry between `_group_prompt_cache_rows_by_model` (`{"model", ...}`) and `_detect_cache_fragmentation_by` (`{"key", ...}`) confuses a future contributor | L | L | The two helpers feed into different code paths (write-penalty loop vs fragmentation detection); they never cross. Mitigated by docstrings on both functions explicitly noting the shape they emit. Verify post-refactor that `_model_groups_payload`'s output shape is byte-equal to pre-refactor (the OUTPUT field is `"model"` in both versions; only the INPUT lookup changed from `group["model"]` to `group["key"]`). |
| `_preview_system` truncation at 80 chars cuts a multi-line system in a confusing way | L | L | Replace `\n` with `⏎` before truncation. Test asserts non-`\n` in payload. |
| Test fixture for "heterogeneous internal models" (test 4) requires careful setup to avoid false-positive emission of model-fragmentation alone | M | M | Use 3 nodes: A and B share system="X" but with different models AND C has system="Y". This produces model-fragmentation (A vs B) AND would-be system-fragmentation (X vs Y) — but the system one defers because group X has heterogeneous models. Assert ONLY model warning fires. |

---

## Top-10% Lens — Considered Alternatives (Rejected)

### Alt 1: Parallel sibling detector, rule-of-three deferral

**Considered, rejected.** Initially proposed as the v1 default (rule of three: don't generalize on 2nd instance). Rejected after evaluating the parameterization shape — the cost-divergence concern resolves cleanly via `representative_model_fn(group)` callback (no conditional branches in the abstraction), and the fragmentation pattern IS structural enough that two parallel implementations would invite drift. User selected the generalize-now path; this plan reflects that.

### Alt 2: Add `system: str | None` field to `PerCallRow`

**Considered, rejected** per Decision 2. Single consumer; data-model change for one detector is overengineering. Read from IR at detect-time mirrors the existing `node_by_id` pattern in `_detect_model_cache_fragmentation`.

### Alt 3: Fire the warning regardless of internal model heterogeneity

**Considered, rejected** per Decision 3. Would mislead agents about achievable savings (fixing system alone wouldn't unlock sharing if model also fragments). Honest-unmeasurable convention is the established pattern.

### Alt 4: Multi-marker strategy (DD#11 evolution) — place separate `cache_control` markers on system AND on cache chunks

**Considered separately, ruled OUT for this scope.** Multi-marker doesn't actually solve the cross-node-different-system problem because marker on chunks would still need the bytes BEFORE it (including system) to match across calls. This is a runtime change; out of analyzer scope. Filed in earlier discussion as a v1.x design topic if needed.

### Alt 5: Swap render order (system AFTER cache chunks; reviewer's original suggestion)

**Considered, rejected as v1 default.** Goes against Anthropic's documented pattern; risks LLM behavior change in unmeasured ways. The new analyzer warning achieves the same agent-actionable outcome without runtime risk. If a future user provides empirical evidence that the swap improves real workflows without LLM-behavior regression, revisit.

---

## What This Plan Does NOT Cover

- Adding `system` to `FILE_RESOLVABLE_PARAMS`. Separate concern. The detector works correctly without it (byte-comparing `./a.md` vs `./b.md` still detects divergence). File-resolution for `system:` is a v1.x enhancement if real workflows demand it.
- Multi-marker strategy. Out of analyzer scope.
- Changing the runtime `_build_system_blocks` order. Path A keeps current behavior.
- Cross-workflow detection (parent + child both declare cache, system differs at the boundary). The current detector is root-only, mirroring `_detect_model_cache_fragmentation`. Cross-workflow generalization is future work.
- Updating the existing `test_user_system_prepended_without_marker` test. It locks runtime ordering; this PR doesn't change runtime. Test stays green.

---

## Sequencing for Implementing Agent

**Implement in this strict order**. Each step has a verification gate.

1. **Step 2a — Refactor only.** Add `Callable` to imports. Extract `_detect_cache_fragmentation_by` + `_compute_fragmentation_costs` (rename from `_compute_model_group_costs`). Refactor `_detect_model_cache_fragmentation` to wrap the helper and inline the full write-penalty loop. Add `_build_model_fragmentation_context`. Apply the lockstep docstring updates listed in Step 2a (3 sites). NO new functionality yet; the existing `cache.heterogeneous-models-fragment-cache` and `cache.first-call-write-penalty` warnings should fire identically to pre-refactor.
   - **Gate**: `pytest tests/test_core/test_cache_analysis_per_id_emission.py -k fragmentation` — all **8** existing model-fragmentation tests pass (see Step 2a for the enumerated list).
   - If any fail: read the failure, fix the regression, do NOT proceed.

2. **Step 1 — Catalog entry.** Add `cache.system-prompts-fragment-cache` to `CACHE_WARNING_CATALOG` (with `node_ids_csv` in `required_context_keys`) and `RECOMMENDED_ACTION_PRIORITY`. Update `warning_catalog.py:8` module docstring (count + prose enumeration).
   - **Gate**: `pytest tests/test_core/test_cache_analysis_warnings.py -v` — the existing `len == 20` test will now fail; bump the literal to 21 AND extend `_minimal_context_kwargs` (Step 6) AND update the test's docstring narrative.

3. **Step 2b — System detector.** Add `_detect_system_cache_fragmentation` + helpers (`_system_fragmentation_key`, `_homogeneous_model_for_system_group`, `_build_system_fragmentation_context`, `_system_groups_payload`, `_preview_system`, `_format_system_groups_lines`).
   - **Gate**: import succeeds; no new tests yet.

4. **Step 2c — Wire detector.** Add the `warnings.extend(_detect_system_cache_fragmentation(...))` call in `analyze()`.
   - **Gate**: `pytest tests/test_core/test_cache_analysis_per_id_emission.py -k fragmentation` — model-fragmentation tests still pass; system-fragmentation tests don't exist yet so no new failures.

5. **Step 6 — Coverage helpers (BOTH).** Extend `_kwargs_for` in `test_cache_analysis_per_id_coverage.py` AND `_minimal_context_kwargs` in `test_cache_analysis_warnings.py:513` with required context for `cache.system-prompts-fragment-cache`.
   - **Gate**: `pytest tests/test_core/test_cache_analysis_per_id_coverage.py tests/test_core/test_cache_analysis_warnings.py -v` — per-id round-trip passes for the new ID in BOTH parametrize iterations.

6. **Step 5 — Production-shape tests.** Add 1 emission + 4 suppression mutation guards to `test_cache_analysis_per_id_emission.py` (concrete bodies, not stubs — see Step 5).
   - **Gate**: `pytest tests/test_core/test_cache_analysis_per_id_emission.py -k system_fragmentation` — all 5 new tests pass.

7. **Step 3 — Catalog metadata sync** + **Step 4 — Guide**. Doc-only updates across the 5 sync sites enumerated in Step 3.
   - **Gate**: `pytest tests/test_mcp_server tests/test_core/test_cache_analysis_warnings.py -v` — confirms no docstring assertions fail.

8. **Final sweep**: `make test` + `make check`. All green.

9. **End-to-end smoke** (Verification section). Manual run against the 2-node fixture; agent confirms warning renders in CLI output.

10. **Mutation-test verification** (optional but high-value). For each new test, apply the mutation listed in the Mutation-test verification table and confirm the test fails. Restore immediately.
