# Plan: Split `## Recommended actions` into `## Blocking errors` + `## Recommended actions`

## Context

Stage 2 verification of Task 159 surfaced **Finding #6**: when `analyze-cache` reports `2 errors blocking · 2 opportunities (1 warning, 1 info)` in the summary, agents reading the body have no way to tell which entries in `## Recommended actions` are the errors. They're sorted severity-descending but invisible — the agent has to know catalog priorities to reverse-engineer it. This systematically buries blocking errors that must be fixed before `pflow run` works.

A 4-voter unanimous poll (after a clean-prompt re-run that flipped from "inline tag prefix" to structural separation) chose **structural separation** over per-line severity tags. The mental model: errors halt execution, opportunities are optimizations — they're different categories and deserve different sections.

**Outcome**: text + JSON output split errors into their own ranked section, distinct from optimization recommendations. Agents see "must fix" vs "could improve" as separate visual buckets, and the summary count line maps 1:1 to section presence.

We also use this commit to drop two pieces of pre-merge ceremony that the consumer search confirmed have zero programmatic users: the `JSON_FORMAT_VERSION` constant + version-history docstring (renderers' "version policy" with no in-tree gate) and the `_build_recommended_actions` shim in `analyze.py` (zero production callers; only re-imported by 5 tests).

## What changes (before / after)

### Text mode — error UX fixture (`error-ux-tests/order-mismatch.pflow.md`)

**Before** (current rendering, all 4 entries lumped in one section):

```
## Summary
  Cost per run:                unavailable
  2 errors blocking
  2 opportunities (1 warning, 1 info)

## Recommended actions (ordered by impact)

  Each item below is one edit that unlocks LLM-provider caching.
  Declared values are sent once and reused at 0.1× input cost.

  1. `prompt_cache:` order mismatch on test-call               savings unavailable
     test-call
     Node 'test-call' prompt_cache order doesn't match ## Cache declaration
       expected:  [a, b]
       you wrote: [b, a]
       fix:       reorder the `prompt_cache:` field to match ## Cache declaration order
  2. Prompt body duplicates cached chunks on test-call         savings unavailable
     test-call
     ...
  3. Cache content below provider minimum on test-call         savings unavailable
     ...
  4. Single-call cache write penalty on test-call              savings unavailable
     ...
```

**After**:

```
## Summary
  Cost per run:                unavailable
  2 errors blocking
  2 opportunities (1 warning, 1 info)

## Blocking errors (must fix before run)

  Each item below blocks `pflow run`. Fix before retrying.

  1. `prompt_cache:` order mismatch on test-call
     test-call
     Node 'test-call' prompt_cache order doesn't match ## Cache declaration
       expected:  [a, b]
       you wrote: [b, a]
       fix:       reorder the `prompt_cache:` field to match ## Cache declaration order
  2. Prompt body duplicates cached chunks on test-call
     test-call
     ...

## Recommended actions (ordered by impact)

  Each item below is one edit that unlocks LLM-provider caching.
  Declared values are sent once and reused at 0.1× input cost.

  1. Cache content below provider minimum on test-call         savings unavailable
     test-call
     ...
  2. Single-call cache write penalty on test-call              savings unavailable
     test-call
     ...
```

Key shape facts:
- Errors render WITHOUT the savings column (errors block, they don't optimize — column would always be `savings unavailable` and is signal noise).
- Each section has its own rank starting at 1 (local rank, not global slice).
- Empty sections are skipped by the composer (today's pattern at `render_text.py:55-83`).

### JSON mode — the same fixture

**After** (new `blocking_errors[]` array, errors removed from `recommended_actions[]`):

```json
{
  "summary": {
    "blocking_errors": 2,
    "actionable_opportunities": 2,
    "warnings_count": 1,
    "info_count": 1,
    ...
  },
  "blocking_errors": [
    { "rank": 1, "warning_id": "cache.order-mismatch", "node_id": "test-call", "estimated_savings_usd": null, "scope_workflow": "..." },
    { "rank": 2, "warning_id": "cache.prompt-body-duplicates-cache", "node_id": "test-call", "estimated_savings_usd": null, "scope_workflow": "..." }
  ],
  "recommended_actions": [
    { "rank": 1, "warning_id": "cache.below-min-tokens", "node_id": "test-call", "estimated_savings_usd": null, "scope_workflow": "..." },
    { "rank": 2, "warning_id": "cache.first-call-write-penalty", "node_id": "test-call", "estimated_savings_usd": null, "scope_workflow": "..." }
  ],
  "warnings": [ /* unchanged: ALL diagnostics raw, with severity per entry */ ],
  ...
}
```

Empty-array contract (mirrors `cross_workflow.*`): both arrays always present, empty when no findings of that severity.

`format_version` field removed from JSON output entirely — see "Simplifications taken alongside".

## Design

### `view_helpers.py` — two parallel projections sharing one core

Replace the single `build_recommended_actions` with two parallel functions sharing a private helper:

```python
def build_blocking_errors(warnings: list[Diagnostic]) -> list[RecommendedAction]:
    """ERROR severity only, ranked by priority then id (sev_weight degenerate)."""
    eligible = [d for d in warnings
                if d.severity == Severity.ERROR
                and not is_cross_workflow_alignment(d)]
    return _build_actions(eligible)

def build_recommended_actions(warnings: list[Diagnostic]) -> list[RecommendedAction]:
    """WARNING + INFO only, ranked by severity → priority → savings → id."""
    eligible = [d for d in warnings
                if d.severity != Severity.ERROR
                and not is_cross_workflow_alignment(d)]
    return _build_actions(eligible)

def _build_actions(eligible: list[Diagnostic]) -> list[RecommendedAction]:
    """Sort by `_key`, assign rank 1+, project to RecommendedAction."""
    # body identical to today's build_recommended_actions sort+project loop;
    # the existing _key (lines 91-99) is reused unchanged.
```

**Why this shape**: two named entry points, one private core. The existing sort key (`view_helpers.py:91-99`) works unchanged for both — `sev_weight` is degenerate-but-correct in the errors bucket (all entries have `Severity.ERROR`). No new sort logic.

### `render_text.py` — composer + parametric list helper

Add `_render_blocking_errors` between `_render_summary` and `_render_recommended_actions` in the section composer (lines 49-84). Add a shared list-rendering helper that both error and recommendation sections use:

```python
def _render_blocking_errors(analysis: CacheAnalysis) -> str:
    actions = build_blocking_errors(list(analysis.warnings))
    if not actions:
        return ""
    return _render_action_list(
        header="## Blocking errors (must fix before run)",
        intro="Each item below blocks `pflow run`. Fix before retrying.",
        actions=actions,
        show_savings=False,
    )

def _render_recommended_actions(analysis: CacheAnalysis) -> str:
    actions = build_recommended_actions(list(analysis.warnings))
    if not actions:
        return ""
    return _render_action_list(
        header="## Recommended actions (ordered by impact)",
        intro=("Each item below is one edit that unlocks LLM-provider caching.\n"
               "Declared values are sent once and reused at 0.1× input cost."),
        actions=actions,
        show_savings=True,
    )

def _render_action_list(
    *,
    header: str,
    intro: str,
    actions: list[RecommendedAction],
    show_savings: bool,
) -> str:
    """Shared per-action rendering: rank+headline (+savings) / scope / message."""
    # body extracted from today's _render_recommended_actions (lines 478-510),
    # parametric on header/intro/show_savings. Reuses _format_savings_usd,
    # _pad_savings, _short_workflow_label, _indent_message unchanged.
```

Composer update (`render_text.py:53-57`):

```python
lines.append(_render_summary(analysis))

errors = _render_blocking_errors(analysis)   # NEW
if errors:
    lines.append(errors)

actions = _render_recommended_actions(analysis)
if actions:
    lines.append(actions)
```

### `render_json.py` — symmetric arrays + drop `format_version` ceremony

```python
def render_json(analysis: CacheAnalysis) -> dict[str, Any]:
    from .view_helpers import build_blocking_errors, build_recommended_actions

    blocking = build_blocking_errors(list(analysis.warnings))
    actions = build_recommended_actions(list(analysis.warnings))
    return {
        "workflow_path": analysis.workflow_path,
        "analyzed_at": analysis.analyzed_at,
        "estimate_confidence": analysis.estimate_confidence,
        "estimate_confidence_coverage": dict(analysis.estimate_confidence_coverage),
        "trace_path": analysis.trace_path,
        "summary": _summary_to_dict(analysis),
        "blocking_errors": [_action_to_dict(a) for a in blocking],   # NEW array
        "recommended_actions": [_action_to_dict(a) for a in actions],  # now warnings+info only
        "suggested_blocks": [_block_to_dict(b) for b in analysis.suggested_blocks],
        "per_call": [_per_call_to_dict(r) for r in analysis.per_call],
        "cross_workflow": _cross_workflow_to_dict(analysis),
        "warnings": [_warning_to_dict(w) for w in analysis.warnings],
        "notes": list(analysis.notes),
    }
```

Module docstring (lines 1-176) collapses from ~140-line version-history block to a 10-line "current shape" overview. Constants `JSON_FORMAT_VERSION` and `JSON_FORMAT_VERSION_MAJOR` deleted entirely.

### `analyze.py` — drop the shim

Delete `_build_recommended_actions` (lines 3431-3453, ~16 LOC) and its preceding section header. No production callers (verified). Tests are migrated to import `build_recommended_actions` from `view_helpers` directly (5 sites in one file).

## Files to modify

### Production (5 files)

1. **`src/pflow/core/cache_analysis/view_helpers.py`** — add `build_blocking_errors`; rename existing body's eligibility filter; extract `_build_actions` private helper. ~30 LOC net.

2. **`src/pflow/core/cache_analysis/render_text.py`**
   - Add `_render_blocking_errors` (~12 LOC) and `_render_action_list` (~40 LOC)
   - Refactor `_render_recommended_actions` to delegate to `_render_action_list` (~10 LOC after refactor)
   - Add 4 lines in composer (`render_text.py:53-57`)
   - Update module docstring section ordering (lines 3-12) to include "Blocking errors" between summary and recommended actions
   - Net ~+50 LOC

3. **`src/pflow/core/cache_analysis/render_json.py`**
   - Add `blocking_errors[]` to output dict
   - Delete `JSON_FORMAT_VERSION` + `JSON_FORMAT_VERSION_MAJOR` constants (lines 31, 175)
   - Delete the `"format_version": ...` field from output (line 196)
   - Replace ~140-line version-history docstring (lines 32-173) with a ~10-line "current shape" summary
   - Net ~-130 LOC (mostly docstring)

4. **`src/pflow/core/cache_analysis/analyze.py`**
   - Delete `_build_recommended_actions` shim (lines 3431-3453, 16 LOC)

5. **`src/pflow/core/cache_analysis/__init__.py`**
   - Drop `JSON_FORMAT_VERSION` + `JSON_FORMAT_VERSION_MAJOR` from imports + `__all__` (lines 21, 26-27)
   - Trim docstring policy block (lines 10-15)

### Documentation (3 files)

6. **`src/pflow/core/cache_analysis/CLAUDE.md`** — update section ordering note; remove the JSON `format_version` policy paragraph; remove the bullet documenting the `_build_recommended_actions` shim (line 243).

7. **`src/pflow/mcp_server/services/execution_service.py`** — trim docstring lines 382-386 about `JSON_FORMAT_VERSION` consumer rule.

8. **`src/pflow/core/cache_analysis/warning_catalog.py`** — update stale comment at line 1213 to point to `view_helpers.build_recommended_actions`.

### Tests (5 files)

9. **`tests/test_core/test_cache_analysis_renderers.py`**
   - **Update** `test_text_brownfield_error_diagnostic_visible_in_recommended_actions` (lines 1254-1313) → rename + flip assertion to "errors visible in `## Blocking errors` section, not in `## Recommended actions`". Mutation contract: dropping `Severity.ERROR` filter from `build_blocking_errors` keeps errors visible elsewhere → test fails.
   - **Update** `test_text_summary_renders_blocking_errors_categorically` (lines 224-268) — verify still passes; the summary count line is unchanged. Add an assertion that `## Blocking errors` section appears in body when count > 0, mirroring the count.
   - **Add** `test_text_blocking_errors_section_appears_between_summary_and_recommended_actions` — pin section ordering.
   - **Add** `test_text_blocking_errors_section_omitted_when_no_errors` — empty-section gate.
   - **Add** `test_text_blocking_errors_does_not_render_savings_column` — mutation contract for `show_savings=False`.
   - **Add** `test_json_blocking_errors_array_present_and_excludes_warnings` — JSON parity.
   - **Add** `test_json_recommended_actions_excludes_errors_after_split` — JSON contract for the recommended_actions filter.
   - **Remove** `test_format_version_*` tests + imports (lines 4, 15-16, 118-122).
   - Update stale docstring at line 1261 (mentions `_build_recommended_actions`).

10. **`tests/test_core/test_cache_analysis_analyze.py`**
    - **Migrate** 5 tests at lines 1022-1135 from importing `_build_recommended_actions` (analyze.py shim) to `build_recommended_actions` (view_helpers).
    - **Update** `test_recommended_actions_severity_overrides_priority` (lines 1090-1101) → rename + flip contract: errors are FILTERED OUT of `build_recommended_actions`; new test calls `build_blocking_errors` and asserts ERRORs come back ranked by priority.
    - **Add** `test_blocking_errors_filters_out_warnings_and_info`.
    - **Add** `test_blocking_errors_rank_starts_at_one_independent_of_recommended_actions`.

11. **`tests/test_core/test_cache_analysis_per_id_coverage.py`**
    - Remove `test_format_version_consumer_rule_*` test + imports (lines 20, 291, 300-301).

12. **`tests/test_cli/test_analyze_cache.py`**
    - Remove `payload["format_version"]` assertions + import (lines 192, 199-200).
    - **Add** assertion that `payload["blocking_errors"]` is present + has the right shape on a fixture with errors (mirror existing `cache.below-min-tokens` test pattern at line 122-142).

13. **`tests/test_mcp_server/test_analyze_cache_tool.py`**
    - Remove `result["format_version"]` assertions + import across 3 test cases (lines 70, 75, 101, 106, 125, 137).

## Existing functions/utilities reused

- `view_helpers._key` (lines 91-99) — sort key, unchanged. `sev_weight` degenerate-but-correct for errors bucket.
- `view_helpers.is_cross_workflow_alignment` (line 50) — exclusion filter, unchanged. Keeps cross-workflow rename + prose-mismatch in their dedicated section.
- `RecommendedAction` dataclass (`analyze.py:158-195`) — reused for both sections. `estimated_savings_usd: float | None` already nullable.
- `render_text._format_savings_usd` (lines 548-572) — savings rendering, unchanged. Only called when `show_savings=True`.
- `render_text._pad_savings`, `_indent_message`, `_short_workflow_label` — per-action helpers, unchanged.
- `Diagnostic.to_dict()` (`core/diagnostic.py`) — JSON serialization for `warnings[]`, unchanged.
- `AnalysisSummary.blocking_errors / actionable_opportunities / warnings_count / info_count` (lines 310-313) — count fields, unchanged. The summary count line at `_render_summary` (lines 331-338) keeps working.

## Edge cases (covered by tests)

| Case | Behavior |
|---|---|
| 0 errors, N warnings/info | `## Blocking errors` skipped (composer); `## Recommended actions` renders as today |
| N errors, 0 warnings/info | `## Blocking errors` renders; `## Recommended actions` skipped |
| 0 errors, 0 warnings/info | Both sections skipped; rest of report renders as today |
| Cross-workflow alignment IDs (rename, prose-mismatch) | Still filtered by `is_cross_workflow_alignment`; render in "Sub-workflow boundaries" only — never in either new section |
| `cache.shared-context-undeclared` with `child_workflow` (WARNING severity) | Stays in Recommended actions as today |
| All 4 ERROR entries share priority=5 | Tie-break by id alphabetical → deterministic ordering within Blocking errors |
| Diagnostic with no catalog id (defensive) | Existing `headline or message or warning_id` fallback at `_render_recommended_actions:488` reused via shared helper |
| JSON empty arrays | Both `blocking_errors: []` and `recommended_actions: []` always emitted (empty-array contract, mirrors `cross_workflow.*`) |

## Verification

### Unit + integration

```bash
make test       # expect ~+8 new tests, ~5 updated; net should be green
make check      # ruff + ruff-format + mypy + deptry green
```

Per-file expectations:
- `tests/test_core/test_cache_analysis_renderers.py` — 5 new tests, 2 updated, 3 format_version tests removed
- `tests/test_core/test_cache_analysis_analyze.py` — 5 imports migrated, 1 test contract flipped, 2 new tests
- `tests/test_cli/test_analyze_cache.py` — 1 new assertion block, format_version checks removed
- `tests/test_core/test_cache_analysis_per_id_coverage.py` — 1 test removed
- `tests/test_mcp_server/test_analyze_cache_tool.py` — format_version assertions removed

### End-to-end against real fixtures

```bash
# Errors-only fixture: confirm Blocking errors section renders, Recommended actions skipped
uv run pflow analyze-cache scratchpads/stage2-verification/error-ux-tests/order-mismatch.pflow.md
# Expect: ## Summary → ## Blocking errors (2 entries) → ## Recommended actions (2 entries)

# Greenfield with declared cache: confirm Recommended actions renders, Blocking errors skipped
uv run pflow analyze-cache scratchpads/stage2-verification/mixed-model-test/mixed-model.pflow.md
# Expect: ## Summary → ## Recommended actions only

# JSON shape:
uv run pflow analyze-cache scratchpads/stage2-verification/error-ux-tests/order-mismatch.pflow.md --format=json | jq '.blocking_errors, .recommended_actions, has("format_version")'
# Expect: 2 entries in blocking_errors, 2 in recommended_actions, has("format_version") == false
```

### MCP parity

```bash
# In another terminal: uv run pflow mcp-server
# Use any MCP client to call analyze_cache against the order-mismatch fixture.
# Expect: result["blocking_errors"] is the new array; result["recommended_actions"] omits errors;
# result["format_version"] is absent from the dict.
```

### Mutation contracts

Each new firing test should fail with a clear assertion when the production guard is reverted:
- Drop the `severity == Severity.ERROR` filter in `build_blocking_errors` → `test_blocking_errors_filters_out_warnings_and_info` fails.
- Drop the `severity != Severity.ERROR` filter in `build_recommended_actions` → `test_json_recommended_actions_excludes_errors_after_split` fails.
- Set `show_savings=True` in `_render_blocking_errors` call → `test_text_blocking_errors_does_not_render_savings_column` fails.
- Reorder composer to put `_render_blocking_errors` after `_render_recommended_actions` → `test_text_blocking_errors_section_appears_between_summary_and_recommended_actions` fails.

## Out of scope (filed as follow-ups, not in this PR)

1. **Per-call inline ID severity tags** — the per-call report at the bottom currently shows IDs like `below-min-tokens, first-call-write-penalty, order-mismatch` without severity. Bundling into this commit would expand scope significantly. The structural fix at top is the primary win.
2. **Catalog ID brackets on errors** (`[cache.X]` prefix) — Stage-1 final pass dropped them; we keep that decision. Agents who need the catalog id for lookup read JSON `warnings[].id`.
3. **Renaming `CacheAnalysis.warnings`** to a more accurate name (it holds ALL severities, the "warnings" name is historical) — separate refactor; not blocking this UX fix. Worth a follow-up issue.
