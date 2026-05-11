# Task 159 — Sub-workflow cache rec aggregation (A1)

> **Revision history**: initial draft → revised after 4-agent plan review (review-plan / review-impact-completeness / review-feature-interactions / review-agent-ux). Five Critical findings (C1-C5) verified against ground-truth code reads and addressed below.

## Context

`pflow analyze-cache` on the lyrics-generator workflow emits 26 entries in `## Recommended actions`. 20 of those are `cache.sub-workflow-cache-undeclared` findings; ~14 carry `Note: ~N tokens estimated, below {model}'s {threshold}-token minimum` and `savings unavailable`. A fresh AI agent reading this output is led to believe most boundary inputs are unworkable — when in fact 4-6 of the affected children have cumulative cross-workflow inputs that DO cross the threshold once declared together.

**Two underlying defects produce this flood:**

1. **Per-input threshold gating is wrong.** pflow emits ONE `cache_control` marker on the last cached block per LLM call (DD#11 single-breakpoint strategy at `nodes/llm/llm.py:605-608`). The provider sees a single cache breakpoint covering the **cumulative prefix** — all declared chunks combined. Per-call analyzer code already does this math (`_apply_cross_workflow_projection` at `analyze.py:1873-1897`). The recommendation emission path at `_emit_sub_workflow_cache_findings` (`analyze.py:4589-4668`) gates each input independently via `_below_threshold_clause(tokens, model)` (`analyze.py:4503-4533`), missing the cumulative reality.

2. **First-child-model threshold sampling is order-dependent buggy.** `_project_sub_workflow_cache_savings` (`analyze.py:4445-4500`) uses `threshold_model = first_row.model` at line 4477. Under heterogeneous child consumer models this is dishonest both directions. The existing row-level path at `analyze.py:1598` already does it right: `max(get_min_cache_tokens(model) for model in child_models)`.

**Intended outcome:** one numbered entry per child workflow in `## Recommended actions`, with per-consumer-node cumulative math computed at the analyzer tier. Cleanup-first procedure lifts to a section-header explainer.

## Approach: A1 — analyzer-tier collapse mirroring `cache.prompt-cache-incomplete`

`cache.prompt-cache-incomplete` is the established codebase precedent (`analyze.py:3664-3718` + spec at `warning_catalog.py:279-306`):

- ONE Diagnostic per workflow scope (we mirror: per child workflow)
- Helper pair: `_format_X_block(findings) -> str` (pre-rendered) + `_X_context(findings) -> list[dict]` (JSON-consumer view)
- Catalog `message_template` interpolates the pre-rendered block directly; structured list declared in `required_context_keys` but never referenced in the template
- Pre-emission filter against overlapping advisories
- `nullable_cost_keys=frozenset({"savings_usd"})` in spec

## Locked decisions (made now, no implementation-time ambiguity)

| # | Decision | Rationale |
|---|---|---|
| D1 | **Single pre-rendered `body_block` context key** carries all case-specific prose (cumulative summary + inputs list + threshold context + model-switch alternative). Catalog template is `"... {body_block}"`. NO `inputs_block` / `below_threshold_clause` / `model_switch_block` as separate keys. | Avoids the "declared in required_context_keys but never built" trap (C2). Mirrors `cache.prompt-cache-incomplete`'s pre-rendered approach but consolidates 3 case-specific clauses into 1. |
| D2 | **Headline template has NO savings suffix slot** (matches `cache.prompt-cache-incomplete:305`). Renderer appends savings via existing `_pad_savings` / `_format_action_savings` alignment mechanism unchanged. | C5 fix. The plan's earlier `_headline_savings_suffix` was fictional — no such interpolation exists. |
| D3 | **Use `ctx.trace` (not `ctx.trace_data`) for trace-presence gates**, matching every other analyzer site. | C3 fix. `ctx.trace=None` is reachable when `ctx.trace_data` is populated (TraceTree construction at `context.py:82-86` swallows `ValueError`). Mixing the two is a silent footgun. |
| D4 | **Per-input tokenization model = strictest consumer's model**. Single `_estimate_parent_value_tokens(..., model=strictest_model, ...)` call per input. | The strictest model drives the threshold gate; using its tokenizer for the gating math is internally consistent. Tokenizer differences across providers are small enough that this doesn't materially mis-estimate. |
| D5 | **Coalesce / unmeasurable inputs are NOT group-poisoning**. An input whose `_estimate_parent_value_tokens` returns None is listed in the diagnostic with `tokens_estimated=None`, contributes 0 to cumulative, but doesn't drop the group case from "actionable" to "refactor". The case classification uses only the inputs that resolved. | Per feature-interactions review: one coalesce input shouldn't kill a group of 3 actionable inputs. Honest unmeasurable — surface the boundary, mark the unmeasured input. |
| D6 | **Did-not-execute consumers** (where `row.did_not_execute_in_trace=True` from conditional dispatch) are SKIPPED from the cumulative math but still included structurally in the diagnostic. The case classifier sees only executing consumers. | Mirrors per-call's existing trace-filtering. Conditional unreachables shouldn't promote a group to "actionable" based on math that won't run. |
| D7 | **Four cases** (not three): `actionable` / `model_switch` / `refactor` / `unmeasurable`. `unmeasurable` fires when `strictest_threshold == 0` (zero consumers with resolvable models). | Per review-plan W5: "refactor" is the wrong framing when the real problem is no model resolved. Honest unmeasurable convention. |
| D8 | **`_consolidate_to_root_advisories` parallel first-child-model bug IS in scope.** Same fix shape — replace `first_row.model` sampling with strictest-threshold-across-consumers iteration. Mirrors the `_project_sub_workflow_cache_savings` fix. New Step 16. | The two bugs are structurally identical; fixing them together eliminates the asymmetric documented quirk in CLAUDE.md and lands one coherent strictest-threshold convention across the analyzer. |
| D9 | **Extend `PerCallRow.cross_workflow_inputs` from `tuple[str, ...]` to `tuple[CrossWorkflowInputContribution, ...]`** carrying `(name, tokens_per_call, model)` per input. The emission helper reads tokens directly from the row instead of re-tokenizing via `_estimate_parent_value_tokens`. | Removes the duplication where per-call AND emission both tokenize the same parent value. Single source of truth: tokens computed once during row build, consumed by both render paths. |
| D10 | **Body block uses per-consumer grouping for multi-consumer children**. When a child has 2+ LLM consumers with different consumed-input sets, the body block lists consumers as primary headings with their input bullets nested. Single-consumer children show a flat input list. | Per agent-UX review: the analyzer computes per-consumer projections; flattening loses agent-visible reality. |
| D11 | **"Cumulative" everywhere** (drop "combined" / "combine"). | Per agent-UX review #9; matches analyzer code (`cumulative_tokens`, `total_cumulative_tokens`). |
| D12 | **Headline savings labeled "saves ~$X/run"** (i.e., per workflow run; `observed_call_count` is the run-scoped multiplier in `_estimate_token_savings_usd`). | The math is `0.9 × tokens × calls × rate` where `calls = observed_call_count` per consumer summed across consumers — the result is per workflow run, not per LLM call. |
| D13 | **Case 2 headline reads "savings available with model switch — see body"**, NOT "savings unavailable". Body block carries the projected savings if the agent switches model. | Per agent-UX review #2: "savings unavailable" misleads agents to deprioritize when an action exists. |
| D14 | **Case 3 / Case unmeasurable include a `→ Monitor:` actionable instead of "no action available"**. | Per agent-UX review #3: every entry in `## Recommended actions` must surface SOME action; otherwise it doesn't belong in an actions section. |
| D15 | **Replace "body refs" with `${var} references` everywhere** in agent-facing output and prose. Per-finding bullet header becomes `Template variables to remove:`. Section-header explainer keeps the `${var}` form throughout. CLAUDE.md updated to use `${var} references` consistently. | Per agent-UX review: "body refs" is internal pflow terminology that reads as jargon (HTTP body? email body?). `${var} references` is unambiguous and matches the syntax agents actually edit. |

## Output shape (locked)

### Section header (renderer)

```
## Recommended actions (N, ordered by impact)

  Each item below is a cache-optimization opportunity for this workflow.
  Declared values are sent once and reused at 0.1× input cost.

  For each "Sub-workflow cache undeclared" finding, apply ALL THREE edits
  in the listed child workflow. Doing only some leaves the cache disabled:
    (1) Remove the `${var}` references from each affected node's prompt
        (or replace them with literal text). Leaving them re-sends the
        content uncached, defeating the cache.
    (2) Add the input as a named entry under the child workflow's ## Cache
        section.
    (3) Reference that named entry in `prompt_cache:` on each consumer node.
```

### Case 1 — actionable (cumulative crosses strictest threshold)

```
3. Sub-workflow cache undeclared in review-genre.pflow.md — declare 3 inputs  saves ~$0.02/run
   Three values flow in from parent song-creator.pflow.md, cumulative ~5,837 tokens (above gemini/gemini-2.5-flash's 4,096-token cache minimum).
   Template variables to remove (replace with the cached chunk name in `prompt_cache:`):
     • `creative_direction` ~1,922 tokens — node `review` uses `${creative_direction}`
     • `lyrics`             ~285 tokens   — node `review` uses `${lyrics}`
     • `song_architecture`  ~3,630 tokens — node `review` uses `${song_architecture}`
   → Edit: song-creator/reviews/review-genre.pflow.md
```

### Case 2 — model_switch (cumulative below current threshold, above 1024)

```
7. Sub-workflow cache undeclared in review-ai-tells.pflow.md — model switch unlocks caching  savings available with model switch
   Two values flow in, cumulative ~2,207 tokens — below gemini/gemini-2.5-flash's 4,096-token cache minimum, but above Anthropic Sonnet 4.5's 1,024-token minimum.
   Template variables to remove:
     • `creative_direction` ~1,922 tokens — node `review` uses `${creative_direction}`
     • `lyrics`             ~285 tokens   — node `review` uses `${lyrics}`
   → Switch model: replace the `- model:` line in review-ai-tells.pflow.md with one of:
       anthropic/claude-sonnet-4-5   (recommended — pflow's default)
       anthropic/claude-opus-4-1
       anthropic/claude-sonnet-4
       anthropic/claude-sonnet-3-7
       anthropic/claude-opus-4
     These cache at ≥1,024 tokens. `prompt_cache:` declarations transfer unchanged. Note: switching providers changes base inference cost — see `pflow guide caching`.
   → Then: apply steps (1)(2)(3) above to song-creator/reviews/review-ai-tells.pflow.md.
   → Monitor: re-run analyze-cache when inputs grow past 4,096 tokens to enable caching at current model.
```

### Case 3 — refactor (cumulative below all provider tiers)

```
10. Sub-workflow cache undeclared in review-stranger-summary.pflow.md — single input below all tiers  not yet cacheable
    One value `lyrics` ~474 tokens, below the smallest provider cache minimum (1,024 — Anthropic Sonnet 4.5). No provider tier accepts caching at this size.
    → Monitor: re-run analyze-cache when content grows past 1,024 tokens.
    → Verify: confirm ~474 tokens is the realistic size — if lyrics typically run longer, the estimate may be off.
```

### Case 4 — unmeasurable (no consumer model resolved)

```
11. Sub-workflow cache undeclared in custom-workflow.pflow.md — model not resolved  unmeasurable
    Two values flow in but no consumer node has a resolved model — cannot compute cache threshold.
    → Set settings.default_model or add per-node `- model:` to each consumer node in custom-workflow.pflow.md, then re-run analyze-cache.
```

### Multi-consumer body block (Case 1 with 2+ consumers)

```
1. Sub-workflow cache undeclared in chorus-chooser.pflow.md — declare 3 inputs  saves ~$0.21/run
   Three values flow in from parent song-creator.pflow.md, used by 2 consumer nodes.
   Per-consumer cumulative caching:
     Node `score-choruses` (~10,500 tokens cumulative — above gemini/gemini-2.5-flash's 4,096 minimum):
       • `concept` ~10,500 tokens — uses `${concept.core_idea}`
     Node `select-chorus` (~14,500 tokens cumulative — above 4,096 minimum):
       • `concept`         ~10,500 tokens — uses `${concept.core_idea}`, `${concept.title}`
       • `creative_brief`  ~  400 tokens — uses `${creative_brief}`
       • `architecture`    ~3,630 tokens — uses `${architecture}`
   → Edit: song-creator/chorus-chooser/chorus-chooser.pflow.md
```

## Files to modify

| File | Change |
|---|---|
| `src/pflow/core/cache_analysis/analyze.py` | Replace `_dedupe_sub_workflow_cache_candidates` with `_aggregate_sub_workflow_cache_candidates_by_child`; add public `CrossWorkflowInputContribution` dataclass (D9); change `PerCallRow.cross_workflow_inputs` type (D9); update `_apply_cross_workflow_projection` return shape; add `_SubWorkflowCacheGroup` + `_GroupedConsumerProjection` dataclasses; new helpers `_project_grouped_cache_savings`, `_classify_group_case`, `_format_grouped_body_block`, `_grouped_inputs_context`; rewrite `_emit_sub_workflow_cache_findings`; rewrite `_project_sub_workflow_cache_savings` for strictest threshold; rewrite `_consolidate_to_root_advisories` for strictest threshold (D8); DELETE `_build_cleanup_hint_clause` and `_format_child_node_ids_csv` |
| `src/pflow/core/cache_analysis/warning_catalog.py` | Update `cache.sub-workflow-cache-undeclared` spec: minimal `required_context_keys`, trim `suggestions_template` to 1 line (`"Edit: {child_workflow}"`), update `message_template` to interpolate `{body_block}`, update `headline_template` (NO savings suffix), update `path_template` to drop `{child_input_name}` |
| `src/pflow/core/cache_analysis/render_text.py` | (a) Add section-header procedural explainer using `${var} references` wording (D15); (b) **rewrite `_unavailable_notes_by_row_key`** at lines 1390-1405 to iterate the new structured `inputs: list[dict]` payload (C4 fix); (c) update `_format_cross_workflow_inputs_note` at `:1645-1659` to read the new `CrossWorkflowInputContribution.name` field (D9); (d) eyeball `_pad_savings` / `_format_action_savings` to confirm grouped-diag headline rendering works |
| `src/pflow/core/cache_analysis/render_json.py` | (a) Update `cross_workflow_inputs` projection at `:244` to emit the new structured shape (`name`, `tokens_per_call`, `model`); (b) update docstring at `:269-274` (pre-Stage-0 comment is stale post-grouping) |
| `src/pflow/core/cache_analysis/__init__.py` | Add version-history note documenting the diagnostic shape change for `cache.sub-workflow-cache-undeclared` |
| `src/pflow/core/llm_capabilities.py` | New helper `anthropic_models_at_threshold(threshold: int) -> tuple[str, ...]` (~10 LOC) |
| `src/pflow/core/cache_analysis/CLAUDE.md` | **Rewrite** the cross-boundary recommendation paragraph at line ~150 (the existing text is now incorrect on three counts: strictest threshold, per-consumer cumulative, four-case dispatch). Update the note about `_consolidate_to_root_advisories` parallel bug to reference the follow-up issue. |
| `src/pflow/mcp_server/tools/execution_tools.py` | Update `analyze_cache` docstring with the new diagnostic shape: list which keys agents now read (`inputs[]`, `case`, `savings_usd`), which are removed, where to find Case 1/2/3/unmeasurable examples |

## Reusable helpers (verified signatures)

| Helper | Location | Signature / use |
|---|---|---|
| `_estimate_parent_value_tokens` | `analyze.py:4394` | **Keyword-only**, requires `parent_workflow, parent_value_expr, parent_node_id, child_workflow, child_input_name, model, ctx, cw_result`. Returns `int | None`. |
| `_estimate_token_savings_usd` | `analyze.py:3994` | `(model, tokens, calls) -> float | None`. Computes `0.9 * tokens * calls * rate`. |
| `_input_rate` | `analyze.py:4001` | `(model) -> float | None`. Returns rate or None for unpriced model. |
| `get_min_cache_tokens` | `llm_capabilities.py` (already imported at `analyze.py:55`) | `(model) -> int` provider threshold |
| `_is_static_batch_trace_row` | `analyze.py:1917` | `(*, is_batch, batch_size, observed_call_count, source) -> bool` keyword-only. |
| `_total_observed_invocations` | `analyze.py:1666` | `(*, child_workflow, child_node_ids, call_counts_by_node) -> int` |
| `normalize_model_name` | `llm_providers.py:72-80` | `(bare) -> str` adds `anthropic/` prefix |

## Strictest-threshold correctness fix (in scope, both sites — D8)

Replace first-child-model sampling at TWO sites:

1. **`_project_sub_workflow_cache_savings`** (`analyze.py:4477`): `threshold_model = first_row.model` → per-consumer iteration computing `max(get_min_cache_tokens(row.model) for row in consumer_rows if row.model)`. Pattern source: `analyze.py:1598`.

2. **`_consolidate_to_root_advisories`** (location confirmed during implementation; CLAUDE.md documents the same single-model sampling): same fix shape — replace the first-child-model pick with strictest across all consumers that reference the consolidate-root.

Add mutation-contract tests at BOTH sites, mirroring `test_cross_workflow_projection_uses_strictest_child_model_threshold` (`test_cache_analysis_per_id_emission.py:1812-1884`). CLAUDE.md note rewritten to document the unified strictest-threshold convention.

## Implementation steps (atomic)

### Step 1 — `anthropic_models_at_threshold` helper

**File**: `src/pflow/core/llm_capabilities.py`

Add next to `get_min_cache_tokens`:

```python
def anthropic_models_at_threshold(threshold: int) -> tuple[str, ...]:
    """Anthropic model patterns with min_cache_tokens equal to ``threshold``.

    Empty-pattern wildcard rows (OpenAI, Gemini) excluded — we suggest
    named alternatives only.
    """
    return tuple(
        cap.model_pattern
        for cap in MODEL_CAPABILITIES
        if cap.provider == "anthropic"
        and cap.model_pattern
        and cap.min_cache_tokens == threshold
    )
```

**Tests** (new in `tests/test_core/test_llm_capabilities.py`):
- Returns expected 5-tuple for `threshold=1024` (order from `MODEL_CAPABILITIES`)
- Returns 2-tuple for `threshold=2048`
- Returns `()` for unknown threshold
- Excludes wildcard rows

### Step 2 — Dataclasses + aggregator

**File**: `src/pflow/core/cache_analysis/analyze.py`

Add near `_SubWorkflowCacheCandidate` (around line 4141):

```python
@dataclass(frozen=True)
class _GroupedConsumerProjection:
    """One consumer node's cumulative cache plan within a group."""
    consumer_node_id: str
    model: str  # effective (trace-promoted) model; empty if unresolved
    consumed_inputs: tuple[str, ...]
    cumulative_tokens: int
    threshold: int  # 0 if model unresolved
    savings_usd: float | None
    did_not_execute_in_trace: bool


@dataclass(frozen=True)
class _SubWorkflowCacheGroup:
    """All sub-workflow-cache-undeclared candidates flowing into one child workflow."""
    child_workflow: str
    candidates: tuple[_SubWorkflowCacheCandidate, ...]
```

Replace `_dedupe_sub_workflow_cache_candidates` (`analyze.py:4185-4205`) with `_aggregate_sub_workflow_cache_candidates_by_child` (deterministic ordering preserved via the existing `(parent_node_id, parent_workflow)` lex-smallest tie-break within each input).

### Step 2.5 — Extend `PerCallRow.cross_workflow_inputs` (D9)

**File**: `src/pflow/core/cache_analysis/analyze.py`

Add public dataclass alongside `PerCallRow`:

```python
@dataclass(frozen=True)
class CrossWorkflowInputContribution:
    """One parent-workflow value flowing into a per-call row as a cross-workflow projection."""
    name: str           # parent_value_expr (matches today's tuple[str] semantics)
    tokens_per_call: int | None  # NEW: tokens for this one input, per call (None when unmeasurable)
    model: str          # NEW: the consumer-row's effective model used for tokenization
```

Change `PerCallRow.cross_workflow_inputs: tuple[str, ...]` → `tuple[CrossWorkflowInputContribution, ...]`. Update `_apply_cross_workflow_projection` (`analyze.py:1893-1897`) to return the structured form. Update `_RowCrossWorkflowCandidate` (`analyze.py:1512`) — it already carries `estimated_tokens_per_call`, so the new field just preserves that data on the row.

Update consumers:
- `render_text.py::_format_cross_workflow_inputs_note` (`:1645-1659`): change `inputs: tuple[str, ...]` → `tuple[CrossWorkflowInputContribution, ...]`; render `.name` for the agent-facing CSV. No format change.
- `render_json.py` cross_workflow_inputs projection: emit `[{"name": x.name, "tokens_per_call": x.tokens_per_call, "model": x.model}, ...]`.

Per-call tests for `cross_workflow_inputs` shape need migration (mechanical — assert `.name` instead of string).

### Step 3 — Per-consumer cumulative math (FIX C1, C3, D5, D6, D9)

**File**: `src/pflow/core/cache_analysis/analyze.py`

Read per-input tokens DIRECTLY from `PerCallRow.cross_workflow_inputs` (D9 — no re-tokenization). Use `ctx.trace` not `ctx.trace_data` (C3 fix); honest-unmeasurable on coalesce/None (D5); skip did-not-execute consumers (D6). The `_estimate_parent_value_tokens` keyword-only call (C1 fix) is now ONLY used as a fallback when the row hasn't computed `cross_workflow_inputs` yet (e.g., for child consumers that didn't make it onto a row):

```python
def _project_grouped_cache_savings(
    group: _SubWorkflowCacheGroup,
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
    ctx: AnalysisContext,
    cw_result: Any,
) -> tuple[
    int,                                   # total_cumulative_tokens
    int,                                   # strictest_threshold (0 if no resolved consumer)
    float | None,                          # group_total_savings_usd
    tuple[_GroupedConsumerProjection, ...],
    dict[str, int | None],                 # tokens_per_input
    str,                                   # strictest_threshold_model name
]:
    # Step 1: pick strictest model first (drives both tokenizer and threshold gate).
    consumer_rows: list[tuple[str, PerCallRow]] = []
    for candidate in group.candidates:
        for node_id in candidate.child_node_ids:
            row = rows_by_node_path.get((group.child_workflow, node_id))
            if row is None or not row.model:
                continue
            if row.did_not_execute_in_trace:
                continue
            consumer_rows.append((node_id, row))
    if not consumer_rows:
        return 0, 0, None, (), {}, ""
    strictest_threshold = max(get_min_cache_tokens(r.model) for _, r in consumer_rows)
    strictest_model = next(
        r.model for _, r in consumer_rows if get_min_cache_tokens(r.model) == strictest_threshold
    )
    # Step 2: read per-input tokens from PerCallRow.cross_workflow_inputs (D9).
    # Fallback to _estimate_parent_value_tokens for inputs not surfaced via row plumbing
    # (e.g., consumers gated out at per-call row build but still candidate at emission).
    tokens_per_input: dict[str, int | None] = {}
    for c in group.candidates:
        tokens = _lookup_tokens_from_rows(c, consumer_rows)
        if tokens is None:
            tokens = _estimate_parent_value_tokens(
                parent_workflow=c.parent_workflow,
                parent_value_expr=c.parent_value_expr,
                parent_node_id=c.parent_node_id,
                child_workflow=c.child_workflow,
                child_input_name=c.child_input_name,
                model=strictest_model,
                ctx=ctx,
                cw_result=cw_result,
            )
        tokens_per_input[c.child_input_name] = tokens
    # Step 3: per-consumer cumulative; coalesce/None contributes 0, doesn't poison.
    inputs_by_consumer: dict[str, list[str]] = {}
    for c in group.candidates:
        for node_id in c.child_node_ids:
            inputs_by_consumer.setdefault(node_id, []).append(c.child_input_name)
    projections: list[_GroupedConsumerProjection] = []
    total_savings: float | None = 0.0
    for consumer_node_id, input_names in sorted(inputs_by_consumer.items()):
        row = rows_by_node_path.get((group.child_workflow, consumer_node_id))
        if row is None or not row.model or row.did_not_execute_in_trace:
            continue
        is_static_batch = _is_static_batch_trace_row(
            is_batch=row.is_batch,
            batch_size=row.batch_size_estimated,
            observed_call_count=row.observed_call_count,
            source=row.data_source,
        )
        multiplier = 1 if is_static_batch else max(1, row.observed_call_count)
        per_call_sum = sum(
            tokens_per_input[name] for name in input_names
            if tokens_per_input.get(name) is not None
        )
        cumulative = per_call_sum * multiplier
        savings = _estimate_token_savings_usd(row.model, per_call_sum, multiplier)
        if savings is None:
            total_savings = None
        elif total_savings is not None:
            total_savings += savings
        projections.append(_GroupedConsumerProjection(
            consumer_node_id=consumer_node_id,
            model=row.model,
            consumed_inputs=tuple(input_names),
            cumulative_tokens=cumulative,
            threshold=get_min_cache_tokens(row.model),
            savings_usd=savings,
            did_not_execute_in_trace=False,
        ))
    total_cumulative = sum(p.cumulative_tokens for p in projections)
    return total_cumulative, strictest_threshold, total_savings, tuple(projections), tokens_per_input, strictest_model
```

### Step 4 — Four-case classification (D7)

```python
_MODEL_SWITCH_BAND = 1024  # Lowest Anthropic tier.

def _classify_group_case(
    total_cumulative_tokens: int,
    strictest_threshold: int,
    has_resolved_consumer: bool,
) -> str:
    if not has_resolved_consumer:
        return "unmeasurable"
    if total_cumulative_tokens >= strictest_threshold:
        return "actionable"
    if total_cumulative_tokens >= _MODEL_SWITCH_BAND:
        return "model_switch"
    return "refactor"
```

### Step 5 — Body block builder (D1, D10, D14)

Single helper `_format_grouped_body_block(group, projections, tokens_per_input, strictest_model, strictest_threshold, case, cw_result) -> str` that returns the full case-aware pre-rendered body. Per-consumer grouping when `len(projections) > 1`; flat input list when single consumer; case-specific footer:
- Case `actionable`: just the inputs/consumer list
- Case `model_switch`: inputs/consumer list + multi-line model-switch alternative + `→ Then:` + `→ Monitor:`
- Case `refactor`: minimal context + `→ Monitor:` + `→ Verify:`
- Case `unmeasurable`: structural info + `→ Set settings.default_model or add per-node - model:`

Reuse `_per_input_body_refs(candidate, cw_result)` — extract this helper from `_build_cleanup_hint_clause` (`analyze.py:4557-4586`) in this step. The extraction is mandatory (locking the previous ambiguous "if clean extract, do it").

### Step 6 — Structured payload builder

`_grouped_inputs_context(group, projections, tokens_per_input, cw_result) -> list[dict]` mirroring `_node_findings_context` shape (`analyze.py:3780-3794`). Keys per input:
- `child_input_name` (str)
- `parent_value_expr` (str)
- `parent_workflow` (str)
- `parent_node_id` (str)
- `line_in_parent` (int)
- `tokens_estimated` (int | None)
- `consumer_node_ids` (list[str])
- `consumer_node_ids_csv` (str — backtick CSV per existing convention)

### Step 7 — Rewrite `_emit_sub_workflow_cache_findings` (FIX C2)

**File**: `src/pflow/core/cache_analysis/analyze.py:4589-4668`

Consumes `list[_SubWorkflowCacheGroup]`. One diagnostic per group with minimal context — only the keys that exist; **no `model_switch_block` declared but unbuilt (C2 fix)**:

```python
diagnostics.append(make_diagnostic(
    "cache.sub-workflow-cache-undeclared",
    node_id=None,
    affected_workflow=group.child_workflow,
    child_workflow=group.child_workflow,
    child_workflow_basename=Path(group.child_workflow).name,
    affected_input_count=len(group.candidates),
    inputs=_grouped_inputs_context(group, projections, tokens_per_input, cw_result),
    body_block=_format_grouped_body_block(group, projections, tokens_per_input, strictest_model, strictest_threshold, case, cw_result),
    case=case,
    savings_usd=total_savings if case == "actionable" else None,
))
```

Trace-presence gate uses `ctx.trace` not `ctx.trace_data` (D3 fix).

### Step 8 — Update catalog spec (FIX C2, C5, D1, D2)

**File**: `src/pflow/core/cache_analysis/warning_catalog.py`

Replace `cache.sub-workflow-cache-undeclared` entry. Minimal required keys per D1:

```python
"cache.sub-workflow-cache-undeclared": CacheWarningSpec(
    severity=Severity.INFO,
    source="cache_analyzer",
    category=CACHE_ADVISORY_CATEGORY,
    message_template=(
        "Workflow `{child_workflow_basename}` receives {affected_input_count} value(s) "
        "from a parent that aren't declared in its `## Cache`.\n\n{body_block}"
    ),
    required_context_keys=(
        ("affected_workflow", str),
        ("child_workflow", str),
        ("child_workflow_basename", str),
        ("affected_input_count", int),
        ("inputs", list),
        ("body_block", str),
        ("case", str),
        ("savings_usd", float),
    ),
    suggestions_template=(
        "Edit: {child_workflow}",
    ),
    path_template="workflows[path={child_workflow}]",
    nullable_cost_keys=frozenset({"savings_usd"}),
    headline_template="Sub-workflow cache undeclared in {child_workflow_basename} — declare {affected_input_count} input(s)",
),
```

NO `_headline_savings_suffix` (C5 fix). NO `model_switch_block` (C2 fix; folded into `body_block`).

### Step 9 — Rewrite `_unavailable_notes_by_row_key` (FIX C4)

**File**: `src/pflow/core/cache_analysis/render_text.py:1390-1405`

Replace the helper to walk the new structured `inputs: list[dict]` payload:

```python
def _unavailable_notes_by_row_key(analysis: CacheAnalysis) -> dict[tuple[str | None, str], list[str]]:
    notes_by_node: dict[tuple[str | None, str], list[str]] = {}
    for diag in analysis.warnings:
        if diag.id != "cache.sub-workflow-cache-undeclared":
            continue
        context = diag.context or {}
        child_workflow = context.get("child_workflow") or context.get("affected_workflow")
        case = context.get("case")
        # Only emit row notes for cases where caching won't fire as-stated.
        if case not in {"model_switch", "refactor"}:
            continue
        if not child_workflow:
            continue
        for input_dict in context.get("inputs", []):
            tokens = input_dict.get("tokens_estimated")
            input_name = input_dict.get("child_input_name", "")
            consumer_ids = input_dict.get("consumer_node_ids", [])
            if not isinstance(tokens, int) or not input_name or not consumer_ids:
                continue
            # Threshold lookup: derive from case (model_switch ≥ 1024) or from
            # a per-input field if you extend the payload — for now, use the
            # case label as the threshold indicator in the note.
            note = f"below cache minimum (case={case}): {input_name} ~{tokens:,}"
            for node_id in consumer_ids:
                notes_by_node.setdefault((str(child_workflow), node_id), []).append(note)
    return notes_by_node
```

Decision lock: per-row notes show `(case=model_switch)` or `(case=refactor)` rather than an absolute threshold number. The threshold number lives in the `## Recommended actions` body block. Avoid duplicating the same threshold value in two places.

### Step 10 — Section-header procedural explainer

**File**: `src/pflow/core/cache_analysis/render_text.py`

In `_render_recommended_actions` (around `render_text.py:760-793`), append the procedural explainer block (per output shape above) when any sub-workflow-cache-undeclared finding is present in `actions`.

### Step 11 — Delete dead helpers

Delete `_build_cleanup_hint_clause` (`analyze.py:4557-4586` — replaced by Step 5's body block builder + extracted `_per_input_var_refs`) and `_format_child_node_ids_csv` (`analyze.py:4536-4550` — replaced by inline `, `.join in `_grouped_inputs_context`). Grep-verify no other callers.

### Step 16 — Fix `_consolidate_to_root_advisories` strictest threshold (D8)

**File**: `src/pflow/core/cache_analysis/analyze.py`

Locate `_consolidate_to_root_advisories` (around line 2917+ per CLAUDE.md). Replace its first-child-model sampling with strictest-across-consumers iteration matching the fix pattern from `_project_sub_workflow_cache_savings`. The helper's downstream behavior is identical for homogeneous-models workflows; only the heterogeneous case changes from order-dependent buggy to honest strictest.

Add a mutation-contract test fixture with two consumer models at different thresholds; assert the consolidate advisory uses max-threshold not first-child-model. Mirrors the pattern from `test_cache_analysis_per_id_emission.py:1812-1884`.

Update CLAUDE.md to document the unified strictest-threshold convention across both `_project_sub_workflow_cache_savings` and `_consolidate_to_root_advisories` (the existing note saying "mirrors the existing single-model sampling in `_consolidate_to_root_advisories`" becomes incorrect — rewrite as "strictest across consumer models, mirroring `_row_cross_workflow_candidate_for_edge` at `analyze.py:1598`").

### Step 12 — CLAUDE.md update (rewrite, not augment)

Rewrite the paragraph at line ~150 (cross-boundary recommendations). New content covers:
- Per-consumer cumulative threshold reasoning
- Strictest threshold across consumer models (NOT first-child)
- Four-case dispatch (actionable / model_switch / refactor / unmeasurable)
- One Diagnostic per child workflow (mirroring `cache.prompt-cache-incomplete`)
- The follow-up note: `_consolidate_to_root_advisories` still uses first-child-model sampling — filed as issue #X (D8)

### Step 13 — render_json docstring update

Update the pre-Stage-0 comment at `render_json.py:269-274` — it claims "the duplicated-pre-computed-view smell is gone" but the shape has changed (one record per child vs. one per parent-input).

### Step 14 — __init__.py version-history note

Append a note describing the diagnostic shape change for `cache.sub-workflow-cache-undeclared`. No JSON_FORMAT_VERSION bump (user-stated convention).

### Step 15 — MCP docstring update

Update `mcp_server/tools/execution_tools.py` `analyze_cache` docstring for the new shape: list new keys (`inputs[]`, `case`, `body_block`), removed keys, brief description of the four cases.

## Tests

### Critical: delete (not migrate) obsolete tests

- `test_make_diagnostic_sub_workflow_cache_undeclared_pluralizes_node_phrase` (`test_cache_analysis_warnings.py:218`) — relies on `node_count` context key and `nodes_phrase` auto-derivation. After collapse `node_count` is gone, replaced by `affected_input_count`. **Delete** (no longer testing a relevant invariant).

### Migrate (mechanical, mirror prompt-cache-incomplete shape)

~17 tests in `tests/test_core/test_cache_analysis_per_id_emission.py` (the sub-workflow-cache-undeclared section). Pattern source: prompt-cache-incomplete tests at `test_cache_analysis_per_id_emission.py:4880-5129`.

### Rebuild

`tests/test_core/test_cache_analysis_per_id_coverage.py:61-78` — the `_kwargs_for` fixture entry for `cache.sub-workflow-cache-undeclared` needs full rebuild to match the new `required_context_keys`. Mirror `prompt-cache-incomplete`'s entry at the same file (similar pattern).

### Eyeball / fix-as-needed

- `test_cache_analysis_analyze.py:3049` and adjacent recommended-actions ordering tests — may flip when grouped savings sum differently. Re-run and update assertions to match new shape.
- `test_cache_analysis_renderers.py` — search for `sub-workflow-cache-undeclared` string matches; update substring assertions for the new rendered body.

### Add (~13 new — counts grew with scope expansion)

1. **`test_emits_one_diag_per_child_workflow`** — N candidates collapse to 1 diag with `affected_input_count == N`.
2. **`test_case_actionable_when_cumulative_crosses_threshold`** — 3 sub-threshold inputs cumulative crosses → `case == "actionable"`, `savings_usd > 0`. **Mutation contract**: revert to per-input gating → test fails.
3. **`test_case_model_switch_below_current_above_1024`** — `case == "model_switch"`, body block contains `claude-sonnet-4-5`.
4. **`test_case_refactor_below_all_tiers`** — `case == "refactor"`, body block contains `Monitor:` guidance.
5. **`test_case_unmeasurable_no_resolved_consumer`** — all consumer models empty → `case == "unmeasurable"`, body suggests setting default_model.
6. **`test_strictest_consumer_threshold`** — child with two consumer models (1024 + 4096), content sized to satisfy 1024 but not 4096 → savings None, case `model_switch`. Mirrors mutation contract from `analyze.py:1812`.
7. **`test_static_batch_consumer_no_double_multiply`** — static-batch consumer row, `multiplier=1` not `observed_call_count`.
8. **`test_did_not_execute_consumer_skipped`** — consumer with `did_not_execute_in_trace=True` excluded from cumulative; group still emits with remaining consumers.
9. **`test_coalesce_input_does_not_poison_group`** — one input `${a ?? b}` returns None tokens; case stays `actionable` if other inputs cross threshold; input rendered with `tokens_estimated=None`.
10. **`test_per_consumer_grouping_when_multiple_consumers`** — child with 2 consumers consuming different input subsets; body block lists each consumer with its inputs nested. **Mutation contract**: flatten to single per-child cumulative → test fails because per-consumer cumulatives differ.
11. **`test_inputs_dict_has_documented_keys`** — `set(diag.context["inputs"][0])` equals exact 8-key set (mirrors `test_partial_prompt_cache_node_findings_dict_has_documented_keys` at `test_cache_analysis_per_id_emission.py:5039`).
12. **`test_unavailable_notes_by_row_key_reads_inputs_structure`** — verify Step 9's rewrite: synthesize a Case 2 diag, assert `_unavailable_notes_by_row_key` returns notes keyed by `(child_workflow, consumer_node_id)`.
13. **`test_consolidate_to_root_uses_strictest_consumer_threshold`** (D8) — heterogeneous consumer models, content size satisfies low threshold but not high; assert `_consolidate_to_root_advisories` gate uses max-threshold. **Mutation contract**: revert to first-child-model — test fails.
14. **`test_per_call_row_cross_workflow_inputs_carries_tokens`** (D9) — populate cross_workflow_inputs on a PerCallRow; assert each entry is `CrossWorkflowInputContribution(name, tokens_per_call, model)`. **Mutation contract**: revert to `tuple[str, ...]` — test fails on attribute access.
15. **`test_grouped_emission_reads_tokens_from_row_not_re_estimate`** (D9) — when `PerCallRow.cross_workflow_inputs` has populated tokens, the new emission does NOT call `_estimate_parent_value_tokens` for those inputs. Mock the function and assert call_count.

### Golden text fixtures

Pin the user-design Case 1/2/3/unmeasurable output samples as substring assertions in `test_cache_analysis_renderers.py`. These are the spec — drift here is regression.

## Baselines

**Enumerate before regenerating**:

```bash
grep -l "Sub-workflow cache" .taskmaster/tasks/task_159/baseline/**/expected-stdout.txt
```

Expected drift on at least:
- `10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`
- `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt`
- `12-real-world-lyrics-generator/02-analyze-cache-json/expected-stdout.txt`
- `12-real-world-lyrics-generator/03-analyze-cache-song-creator-text/expected-stdout.txt`
- `04-warning-catalog/05-cache.sub-workflow-cache-undeclared/expected-stdout.txt`
- `04-warning-catalog/05b-cache.sub-workflow-cache-undeclared-subpath/expected-stdout.txt`
- Plus anything else the grep surfaces

Manual smoke expectation pinned:
- lyrics-generator `## Recommended actions` count drops 26 → roughly 10-12
- review-genre, review-rhyme, review-imagery, review-narrative show `case=actionable` with positive savings
- review-ai-tells, review-cliche show `case=model_switch`
- review-stranger-summary shows `case=refactor`
- `_unavailable_notes_by_row_key` per-call table notes still populate for Case 2/3 groups (NOT silent empty)

## Verification

```bash
# After each step that changes code
.venv/bin/python -m pytest tests/test_core/test_cache_analysis_per_id_emission.py tests/test_core/test_cache_analysis_per_id_coverage.py tests/test_core/test_cache_analysis_warnings.py tests/test_core/test_cache_analysis_renderers.py tests/test_core/test_cache_analysis_analyze.py -x --tb=short

# Quality
make check

# Baseline harness (after regen)
.taskmaster/tasks/task_159/baseline/verify.sh

# Full default suite
make test

# Manual smoke
uv run pflow analyze-cache .taskmaster/tasks/task_159/baseline/_shared/workflows/lyrics-generator/lyrics-generator.pflow.md --from-trace .taskmaster/tasks/task_159/baseline/_shared/fixtures/live-gemini-lyrics-generator.trace.json
```

**Code-review checkpoint suggested after Step 7** — that step lands the cross-cutting integration (case dispatch, body block assembly, predicate choice, `_per_input_body_refs` extraction). Past task patterns show cross-cutting integrations are where unit-test-passing plans break in real workflows. A `/code-review` checkpoint before Steps 8-15 catches this cheaply.

## Risk + reversibility

- **Reversible**: yes — all changes are within `cache_analysis/` package + the catalog spec + MCP docstring. JSON shape is additive within the pre-merge window.
- **Largest risk surface**: Step 9 (`_unavailable_notes_by_row_key` rewrite). If wrong, the per-call table silently empties below-threshold notes for Case 2/3 groups — exactly the user-visible signal we're not allowed to lose.
- **Second risk**: test #5 (per-consumer grouping) requires `consumer_projections` data the diagnostic context doesn't carry today. The new `inputs[]` payload + `body_block` covers per-consumer rendering; the test asserts on the rendered body, not on a context key the catalog wouldn't accept.
- **Watch**: Step 4 — make sure `case` values are exact (`"actionable"`, `"model_switch"`, `"refactor"`, `"unmeasurable"`). Tests and renderer match on these strings.

## Total scope estimate (revised after scope expansion)

- Production code: ~+250 LOC net (analyzer +300 with new helpers, dataclasses, PerCallRow extension, and parallel consolidate-to-root fix; catalog +20; renderer -50 for cleanup-first removal +50 for explainer and rewrites; capabilities +10)
- Test code: ~+300 LOC (15 new + ~17 migrations + per-call cross_workflow_inputs migration + 1 delete + 1 rebuild)
- Baselines: ~6-8 cases regenerate
- Effort: 2-2.5 days focused work (added scope: D8 parallel fix + D9 PerCallRow extension)
