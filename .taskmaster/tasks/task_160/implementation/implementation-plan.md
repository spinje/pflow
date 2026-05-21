# Plan: Task 160 — Cache Analysis Architectural Refactor

## Context

`src/pflow/core/cache_analysis/analyze.py` is 8,570 LOC with 210 functions and 27 type definitions. Every modification to the cache analysis package requires loading this file. This pure-structural refactor splits it into focused modules with zero behavior change, and renames the package from `cache_analysis` to `prompt_cache_analysis` to disambiguate from pflow's memoization cache.

**Reference documents** (read these first):
- `.taskmaster/tasks/task_160/task-160.md` — complete spec with requirements, design decisions, production consumers, verified non-issues
- `.taskmaster/tasks/task_160/research/architecture.md` — verified cluster structure, import graph, cycle analysis, dataclass inventory, shared utility placement

## Pre-implementation

### Run the task 159 regression harness

Task 159 left a comprehensive regression oracle at `.taskmaster/tasks/task_159/baseline/` with 79 cases and a verification script. Use it instead of manual baseline capture:

```bash
# Verify everything passes BEFORE starting
make test && make check

# Run the task 159 baseline verification harness
cd .taskmaster/tasks/task_159/baseline && bash verify.sh
# Exit 0 = clean. Save this as your pre-refactor reference.
```

### Search pattern checklist

The package rename creates 5 distinct categories of string references. Use ALL 5 patterns at each phase — a simple `grep "from pflow.core.cache_analysis"` misses categories 2-5:

```bash
# 1. Standard imports (from X import Y)
grep -rn "from pflow.core.cache_analysis" src/ tests/ --include="*.py"

# 2. Bare module imports (import X as Y, used by monkeypatch)
grep -rn "import pflow.core.cache_analysis" src/ tests/ --include="*.py"

# 3. importlib.import_module string references (110 sites in 4 test files)
grep -rn 'import_module.*cache_analysis' src/ tests/ --include="*.py"

# 4. sys.modules string keys (26 sites in 2 test files)
grep -rn 'sys\.modules.*cache_analysis' src/ tests/ --include="*.py"

# 5. caplog/monkeypatch/patch target strings
grep -rn '"pflow.core.cache_analysis' src/ tests/ --include="*.py"

# 6. Non-Python references (pyproject.toml, CLAUDE.md, comments)
grep -rn "cache_analysis" pyproject.toml src/ tests/ --include="*.py" --include="*.md" --include="*.toml"
```

## Phase 1: Package rename + types.py extraction

### Step 1.1: Rename the directory

```bash
git mv src/pflow/core/cache_analysis src/pflow/core/prompt_cache_analysis
```

### Step 1.2: Update ALL references across the codebase

Replace `pflow.core.cache_analysis` → `pflow.core.prompt_cache_analysis` using ALL 6 search patterns from the checklist above.

**Production code (6 files):**
- `src/pflow/cli/commands/analyze_cache.py` — **4 import lines** (lines 130, 131, 132, 291). Note: lines 131-132 import from sub-modules (`.analyze` and `.render_traces_list`) — these will change again in Phases 2-3.
- `src/pflow/execution/runner.py` — 1 import line
- `src/pflow/mcp_server/services/execution_service.py` — 1 import line
- `src/pflow/core/workflow/data_flow.py` — 2 import sites
- `src/pflow/nodes/llm/llm.py` — 3 import lines
- `src/pflow/runtime/engine/engine.py` — 4 import lines

**`pyproject.toml` (line ~174):** Update the ruff per-file-ignore glob:
```
"src/pflow/core/cache_analysis/*" → "src/pflow/core/prompt_cache_analysis/*"
```
Missing this breaks `make check` with RUF001/RUF002 violations on `×` characters.

**Internal package imports** — every `.py` file in `prompt_cache_analysis/` with absolute imports.

**Test files** — 17 test files with standard imports, PLUS:
- ~110 `importlib.import_module("pflow.core.cache_analysis...")` strings in 4 test files
- ~26 `sys.modules["pflow.core.cache_analysis..."]` keys in 2 test files
- ~4 `caplog` logger name strings (e.g., `logger="pflow.core.cache_analysis.analyze"`)
- ~9 bare `import pflow.core.cache_analysis` + `monkeypatch.setattr` patterns
- 4 patch target strings in `tests/test_runtime/test_prompt_cache_dict.py`

**CLAUDE.md files** — at minimum: `cache_analysis/CLAUDE.md`, `core/CLAUDE.md`, `core/workflow/CLAUDE.md`, `runtime/CLAUDE.md`, `runtime/engine/CLAUDE.md`, `cli/commands/CLAUDE.md`, `tests/CLAUDE.md`. Also update comment/docstring references in ~11 source files (run pattern 6).

**Explicit decisions:**
- `tests/fixtures/cache_analysis/` directory: **keep as-is** (renaming would require updating embedded `workflow_path` in trace JSON plus ~20 path literals in test files — not worth the churn)
- Test file names (`test_cache_analysis_*.py`): **keep as-is** (not imported by anything, renaming confuses git history)

### Step 1.3: Create `types.py`

Create `src/pflow/core/prompt_cache_analysis/types.py`. See `research/architecture.md` → "Dataclass inventory" for the complete list.

Contents (moved verbatim from analyze.py):
- Constants: `_PROJECTION_NOT_APPLICABLE`, `_PROJECTION_UNAVAILABLE`, `_BLOCK_BELOW_PROVIDER_MIN`, `_BLOCK_PREWARM_IMAGES`, `_BLOCK_ABSENT_BRANCH`, `_BLOCK_RUNTIME_STRIPPED`
- 20 public frozen dataclasses + 1 TypedDict (lines 126-972) — full list in architecture.md
- Projection helpers, Cluster A (lines 167-327): `unavailable_projection`, `not_applicable_projection`, `component_tokens`, `_projection_component`, `_cap_projection_tokens`, `aggregate_projection`, `_best_component`, `_aggregate_component_confidence`, `_merge_diagnostic_ids`
- `_safe_pct` (line 6017) — 4-line arithmetic, used by projection helpers
- `invocation_count_for` (lines 8109-8123) — PerCallRow contract, called from 6 clusters + `cost_estimation.py`

**types.py imports:**
```python
from __future__ import annotations
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, TypedDict

if TYPE_CHECKING:
    from .cost_estimation import CostTier
```

### Step 1.4: Update imports throughout the package + shrink analyze.py's `__all__`

Every file that imported dataclasses from `.analyze` now imports from `.types`:
- `analyze.py` — add `from .types import ...` for types it still references internally. **Shrink `analyze.py`'s `__all__`** to only `["analyze"]` — do NOT re-export types from analyze.py (avoid dual-path imports)
- `cost_estimation.py` — `from .analyze import PerCallRow, ProjectionExclusion, invocation_count_for` → `from .types import ...`
- `render_text.py` — `from .analyze import AnalysisSummary, CacheAnalysis, CostDelta, ...` → `from .types import ...`
- `render_json.py` — same pattern
- `view_helpers.py` — the lazy import of `RecommendedAction` (inside `_build_actions()`) becomes a **top-level import** from `.types`
- `summarize.py` — `from .analyze import CacheAnalysis, analyze` → split to `from .types import CacheAnalysis` and `from .analyze import analyze`

Also update test files that import public types directly from `.analyze` (not via `__init__.py`). There are ~51 such import sites across 8 test files importing `PerCallRow`, `AnalysisSummary`, `CostDelta`, `ProjectionExclusion`, `SuggestedBlock`, `SuggestedBlockChunk`, `CrossWorkflowInputContribution`, etc.

### Step 1.5: Update `__init__.py`

```python
from .types import CacheAnalysis, TraceListEntry
from .analyze import analyze, list_traces_for_workflow  # list_traces moves in Phase 2
from .render_json import render_json    # moves to .rendering in Phase 3
from .render_text import render_text    # moves to .rendering in Phase 3
from .summarize import summarize, summarize_from_analysis  # moves in Phase 3
```

### Step 1.6: Verify

```bash
make test && make check
```

## Phase 2: trace_loading.py extraction

### Step 2.1: Create `trace_loading.py`

Move from analyze.py (see `research/architecture.md` for full function list):
- Cluster C: `_default_memo_cache` (keep `MemoizationCache` lazy import)
- Cluster D: all 12 trace loading functions
- From Cluster E: `_resolve_current_workflow_model_set`, `_resolve_current_workflow_model_set_for_path`, `_build_trace_list_entry`, `_edge_child_paths`, `_build_trace_execution_index` + helpers, trace aggregation helpers (`_collect_trace_llm_call_lists`, `_aggregate_trace_llm_calls`, etc.)

### Step 2.2: Update `__init__.py` and production consumers

`list_traces_for_workflow` → from `.trace_loading`:
```python
from .trace_loading import list_traces_for_workflow
```

**Update `cli/commands/analyze_cache.py` line 131** — currently imports `list_traces_for_workflow` directly from `.analyze`. Update to `.trace_loading` (or use the package-level import).

### Step 2.3: Verify

```bash
make test && make check
```

## Phase 3: rendering/ subdirectory

### Step 3.1: Create directory and move files

```bash
mkdir -p src/pflow/core/prompt_cache_analysis/rendering
```

- `render_text.py` → `rendering/text.py`
- `render_json.py` → `rendering/json.py`
- `view_helpers.py` → `rendering/views.py`
- `summarize.py` → `rendering/summarize.py`
- `render_traces_list.py` → `rendering/traces_list.py`

### Step 3.2: Create `rendering/__init__.py`

```python
from .json import render_json
from .text import render_text
from .summarize import summarize, summarize_from_analysis
```

Note: `render_traces_list_json`/`render_traces_list_text` are intentionally NOT re-exported here (only one production consumer, which imports directly).

### Step 3.3: Update imports within rendering files

General pattern: `from .X import Y` → `from ..X import Y` for sibling modules.

**Specific traps to watch:**
- `from . import JSON_FORMAT_VERSION` → `from .. import JSON_FORMAT_VERSION` (in `rendering/json.py` and `rendering/traces_list.py`)
- `rendering/summarize.py`: `CacheAnalysis` was already moved to types.py in Phase 1. Import must be `from ..types import CacheAnalysis` (NOT `from ..analyze import CacheAnalysis`)
- `rendering/views.py`: import `RecommendedAction` at **module scope** from `..types`
- `rendering/traces_list.py`: `from .render_text import _format_recorded_timestamp` → `from .text import _format_recorded_timestamp`

### Step 3.4: Update package `__init__.py`

```python
from .rendering import render_json, render_text, summarize, summarize_from_analysis
```

### Step 3.5: Update production and test consumers

**Production:** `cli/commands/analyze_cache.py` line 132 imports from `render_traces_list` → update to `from pflow.core.prompt_cache_analysis.rendering.traces_list import render_traces_list_json, render_traces_list_text`

**Tests:** Update imports in `test_cache_analysis_renderers.py`, `test_cache_analysis_analyze.py`, `test_cache_analysis_summarize.py`, `test_cache_analysis_trace_listing.py`, `test_analyze_cache.py`. Include `importlib.import_module` and `sys.modules` string references.

### Step 3.6: Verify

```bash
make test && make check
```

## Phase 4: Self-contained stage extraction

### Step 4.1: Create `stages/` directory

```bash
mkdir -p src/pflow/core/prompt_cache_analysis/stages/discrepancy
```

**`stages/__init__.py` must be empty** (or docstring-only). The orchestrator imports from specific stage files, NOT through `stages/__init__`. This prevents eager loading of heavy lazy-import modules.

Only `stages/discrepancy/__init__.py` needs re-exports (it's a sub-package).

### Step 4.2: Extract `stages/summary.py`

Move from analyze.py:
- Cluster I: `_aggregate_confidence`
- Cluster J: `_format_workflow_run_command`, `_build_summary`, `_trace_coverage_for_rows`, `_evidence_scope_for_trace_coverage`, `_aggregate_projection_confidence`, `_filter_trace_dependent_warnings`, `_cost_delta`, `_unavailable_delta`, `_estimate_total_invocations`, `_unavailable_models_by_workflow`, `_safe_pct_or_none`
- Cluster K: `_maybe_append_gemini_note`, `_GEMINI_TELEMETRY_NOTE`
- `_is_cache_focused` (L5868) — called only from `_build_summary` (L8211). Moves with summary.

### Step 4.3: Extract `stages/discrepancy/predict.py`

Move prediction half of Cluster H (full function list in task spec and architecture.md).

Include `_PREDICTION_RECOVERABLE_EXCEPTIONS` constant (L113-123).

**CRITICAL: Keep ALL lazy imports lazy.** `_build_predict_scaffold` lazy-imports `compile_workflow`, `Registry`, `create_planner_shared`, `plan_node`.

### Step 4.4: Extract `stages/discrepancy/diagnose.py`

Move: `_emit_discrepancy_diagnostics`, `_predicted_key_for_event`, `_attribute_root_cause`, `_aggregate_and_cap_discrepancies`.

**Imports from predict.py:**
- `_predict_cache_keys` (the main cross-boundary call)
- `_PREDICTION_RECOVERABLE_EXCEPTIONS` (used in except handler at L7910)
- `_mark_all_prediction_skipped` (called on prediction failure)

**Keep lazy:** `_emit_discrepancy_diagnostics` has a lazy `from pflow.core.trace_tree import TraceTree` — must stay function-local.

### Step 4.5: Create `stages/discrepancy/__init__.py`

```python
from .predict import _attach_predicted_cache_keys, _format_dynamic_batches_note
from .diagnose import _emit_discrepancy_diagnostics
```

### Step 4.6: Extract `stages/cross_workflow.py`

Move Cluster G (L6023-7336) — all ~55 functions and 4 private dataclasses.

**Phase 4 workaround:** Import `_node_inputs`, `_static_excerpt`, `_estimate_token_savings_usd` from `..analyze` temporarily. Phase 5 moves them to their final homes and updates these imports.

**Keep `TemplateResolver` lazy** — import inside functions that use it, not at module scope.

### Step 4.7: Verify

```bash
make test && make check
```

## Phase 5: Cluster F decomposition

The highest-risk phase. Extract 5 stage files from the 3,072-LOC Cluster F.

### Step 5.1: Extract `stages/row_builder.py`

Move sub-groups F1+F2+F3+F4+F5+F6 from analyze.py.

**Shared IR helper (F8) — only `_node_inputs` goes here:**
- `_node_inputs` (L3890) — 7-line pure dict accessor, called from 6 modules

**Row construction (F1):** `_build_per_call_row`, `_apply_cross_workflow_projection`, `_clamp_legacy_cacheable_projection`
**Cross-wf projection (F2):** `_trace_cache_token_splits`, `_cross_workflow_projection_components`
**Provider utils (F3):** `_node_has_images`, `_runtime_trace_blocker`, `_provider_min_state`, `_projection_source_confidence`
**Batch prefix/tail (F4):** `_estimate_dynamic_tail_opportunity`, `_detect_repeated_row_stable_refs`, `_provider_trace_cached_now`
**Projection builders (F5):** `_declared_projection_component`, `_configured_prewarm_projection_component`, `_candidate_cache_projection_component`, `_prewarm_opportunity_projection_component`, `_dynamic_tail_projection_component`, `_build_cache_projection_components`
**Token estimation (F6):** `_resolve_effective_row_model`, `_estimate_row_tokens`, `_tokenize_declared_cache_chunks`, `_resolve_prompt_for_tokenization`

**Make `TemplateResolver` lazy** — import inside functions, matching `context.py` pattern.

### Step 5.2: Extract `stages/warnings.py`

Move sub-group F7 (per-node warning visitors):
- `_per_node_warnings`, `_emit_batch_prewarm_below_min`, `_batch_prewarm_recommendations`, `_confident_batch_prewarm_recommendation`, `_dynamic_before_static_warnings`, `_find_batch_static_tail_after_dynamic`, `_literal_spans_after_template`, `_static_excerpt`, `_opaque_prompt_warnings`, `_resolve_through_batch_alias`, `_estimate_batch_size`, `_estimate_batch_prefix_cacheable_tokens`, `_prefer_batch_prefix_cacheable_tokens`

Note: `_starter_prose_for_ref` goes to suggestions.py (Step 5.3), NOT here.

**Imports:** `from .row_builder import _node_inputs`, `from .suggestions import _estimate_token_savings_usd`
**Make `TemplateResolver` lazy** in this file too.

### Step 5.3: Extract `stages/suggestions.py`

Move sub-groups F9+F10+F11 + pricing helpers from F12 + padding_advisor.py content.

**Shared IR helpers — these go HERE (not row_builder):**
- `_batch_aliases` (L5442) — primary callers are in suggestions/partial_declarations
- `_cache_items` (L5941) — same
- `_cache_item_names` (L5951) — same
- `_is_batch_scoped_ref` (L5820) — same

**Template refs (F10):** `_collect_llm_template_references`, `_collect_llm_template_root_references`, `_longest_var_prefix_match`, `_template_root_segment`
**Suggested blocks (F9):** `_starter_prose_for_ref`, `_populate_suggested_blocks`, `_build_suggested_chunks_and_assignments`, `_skip_suggested_blocks_for_declared_cache`, `_classify_suggested_block_actionability`, `_note_for_non_actionable_state`, `_thresholds_for_assignments`, `_threshold_entry_for_node`
**Body cleanup (F11):** `_compute_prompt_body_cleanup`, `_prompt_body_cleanup_for_node`
**Consolidation from F12:** `_consolidate_to_root_advisories`, `_collect_consolidate_candidates`, `_group_subpaths_by_root`, `_check_root_for_consolidation`
**Pricing helpers from F12:** `_estimate_chunk_tokens`, `_sum_chunk_tokens`, `_savings_for_shared_ref`, `_estimate_token_savings_usd`, `_input_rate`
**Padding:** fold `padding_advisor.py` content (`PaddingCandidate`, `compute_padding_advisories`) + `_emit_padding_advisories` (L5824)
**Constants:** `_SUGGESTED_BLOCK_ACTIONABLE`, `_SUGGESTED_BLOCK_BELOW_THRESHOLD`, `_SUGGESTED_BLOCK_EVIDENCE_INCOMPLETE`, `_SUGGESTED_BLOCK_INSUFFICIENT_NODES`, `_PARENT_PROSE_PREVIEW_LIMIT`

Delete `padding_advisor.py` after folding.

### Step 5.4: Extract `stages/fragmentation.py`

Move fragmentation detection from F12 — full function list in architecture.md.

### Step 5.5: Extract `stages/partial_declarations.py`

Move sub-group F13 — full function list in architecture.md. Optionally move `_PartialDeclarationFinding` dataclass here from types.py.

### Step 5.6: Update cross-module imports

Now that all stages exist, fix the temporary Phase 4 imports:
- `stages/cross_workflow.py`: `from ..analyze import _node_inputs` → `from .row_builder import _node_inputs`
- `stages/cross_workflow.py`: `from ..analyze import _estimate_token_savings_usd` → `from .suggestions import _estimate_token_savings_usd`
- `stages/cross_workflow.py`: `from ..analyze import _static_excerpt` → `from .warnings import _static_excerpt`

### Step 5.7: `_run_full_validation` stays in analyze.py

`_run_full_validation` (L5882) and `_cache_items`/`_cache_item_names` references within it — called only from orchestrator. `_cache_items`/`_cache_item_names` are now in suggestions.py; the orchestrator imports them from there.

### Step 5.8: Update analyze.py orchestrator imports

```python
from .stages.row_builder import _build_per_call_row, _node_inputs, ...
from .stages.warnings import _per_node_warnings
from .stages.suggestions import _populate_suggested_blocks, _consolidate_to_root_advisories, _emit_padding_advisories, _cache_item_names, _collect_llm_template_references
from .stages.fragmentation import _detect_model_cache_fragmentation, _detect_system_cache_fragmentation
from .stages.partial_declarations import _emit_partial_declaration_findings
from .stages.cross_workflow import _build_cross_workflow_findings
from .stages.summary import _build_summary, _aggregate_confidence, _maybe_append_gemini_note, _trace_coverage_for_rows, _filter_trace_dependent_warnings
from .stages.discrepancy import _emit_discrepancy_diagnostics, _attach_predicted_cache_keys, _format_dynamic_batches_note
```

### Step 5.9: Verify

```bash
make test && make check
```

## Phase 6: Test cleanup + final polish

### Step 6.1: Update ALL remaining test imports

Use ALL 5 search patterns from the checklist. Key categories:

**Private symbols from analyze.py → new locations.** Mapping table (search by function name, not line number):

| Symbol | New module |
|--------|-----------|
| `_resolve_trace_scope` | `trace_loading` |
| `_resolve_value_in_workflow_memo` | `stages.cross_workflow` |
| `_build_parameters_by_workflow` | stays in `analyze` |
| `_resolve_child_input_value` | stays in `analyze` |
| `_estimate_row_tokens` | `stages.row_builder` |
| `_configured_prewarm_projection_component` | `stages.row_builder` |
| `_filter_trace_dependent_warnings` | `stages.summary` |
| `_predict_cache_keys` | `stages.discrepancy.predict` |
| `_format_dynamic_batches_note` | `stages.discrepancy.predict` |
| `_format_fidelity_skip_note` | `stages.discrepancy.predict` |
| `_format_skipped_workflows_note` | `stages.discrepancy.predict` |
| `_predict_node_cache_key` | `stages.discrepancy.predict` |
| `_build_predict_scaffold` | `stages.discrepancy.predict` |
| `_pad_inputs_for_prediction` | `stages.discrepancy.predict` |
| `_dummied_cache_chunks` | `stages.discrepancy.predict` |
| `_node_references_any` | `stages.discrepancy.predict` |
| `_attribute_root_cause` | `stages.discrepancy.diagnose` |
| `_aggregate_and_cap_discrepancies` | `stages.discrepancy.diagnose` |
| `_starter_prose_for_ref` | `stages.suggestions` |
| `_parent_origin_clause` | `stages.cross_workflow` |
| `_SubWorkflowCacheCandidate` | `stages.cross_workflow` |
| `_collect_llm_nodes_referencing_path` | `stages.cross_workflow` |

**Public symbols from analyze.py → types.py.** ~51 import sites across 8 test files. Grep: `grep -rn "from pflow.core.prompt_cache_analysis.analyze import" tests/ | grep -v "import _"` — update each to import from `.types`.

**`importlib.import_module` strings** — ~110 sites. These encode the old module path as strings and must be updated to match the new locations. Most are in `test_cache_analysis_per_id_emission.py` (86), `test_cache_analysis_analyze.py` (19), `test_cache_analysis_per_id_coverage.py` (5).

**`sys.modules` keys** — ~26 sites in `test_cache_analysis_analyze.py` (17) and `test_cache_analysis_renderers.py` (9).

**`caplog` logger names** — 4 sites: `test_cache_analysis_cross_workflow.py` (2), `test_cache_analysis_analyze.py` (1), `test_cache_analysis_token_estimation.py` (1).

**`monkeypatch.setattr` target strings** — `test_prompt_cache_dict.py` (4 sites).

### Step 6.2: Final `__init__.py`

```python
from __future__ import annotations
from typing import Final

from .types import CacheAnalysis, TraceListEntry
from .analyze import analyze
from .trace_loading import list_traces_for_workflow
from .rendering import render_json, render_text, summarize, summarize_from_analysis

JSON_FORMAT_VERSION: Final[str] = "5.0"

__all__ = [
    "JSON_FORMAT_VERSION",
    "CacheAnalysis",
    "TraceListEntry",
    "analyze",
    "list_traces_for_workflow",
    "render_json",
    "render_text",
    "summarize",
    "summarize_from_analysis",
]
```

### Step 6.3: Verify

```bash
make test && make check
```

## Phase 7: Documentation

### Step 7.1: Update `prompt_cache_analysis/CLAUDE.md`

Update the existing CLAUDE.md: new module structure, "Where to add a new feature" table, remove "Refactor planned (task 160)" notices. Document the two `cross_workflow.py` files (walker at package root vs analytical stage in `stages/`).

### Step 7.2: Update other CLAUDE.md files

`core/CLAUDE.md`, `core/workflow/CLAUDE.md`, `runtime/CLAUDE.md`, `runtime/engine/CLAUDE.md`, `cli/commands/CLAUDE.md`, `tests/CLAUDE.md` — update references from `cache_analysis` to `prompt_cache_analysis`.

## Final verification

```bash
# 1. Full test suite
make test && make check

# 2. Task 159 regression harness (the authoritative check)
cd .taskmaster/tasks/task_159/baseline && bash verify.sh

# 3. Import chain sanity — no cycles
python -c "from pflow.core.prompt_cache_analysis import analyze, render_json, render_text, summarize"

# 4. No dual-path imports (types should NOT be importable from analyze)
python -c "
from pflow.core.prompt_cache_analysis.types import CacheAnalysis
try:
    from pflow.core.prompt_cache_analysis.analyze import CacheAnalysis
    raise AssertionError('CacheAnalysis should not be importable from analyze.py')
except ImportError:
    pass
"

# 5. File size verification
wc -l src/pflow/core/prompt_cache_analysis/analyze.py  # ≤ 1,100
find src/pflow/core/prompt_cache_analysis -name "*.py" | wc -l  # ~25
```

## Critical reminders for the implementing agent

1. **Zero behavior change.** Move code verbatim. Don't refactor internals. Any bug discovered is a separate ticket.
2. **Keep lazy imports lazy.** `predict.py` (runtime modules), `diagnose.py` (`TraceTree`), `trace_loading.py` (`MemoizationCache`, `resolve_workflow`). Make `TemplateResolver` lazy in ALL stage files that use it (row_builder, warnings, cross_workflow).
3. **Run `make test && make check` after EVERY phase.** Don't batch.
4. **The one cycle to avoid:** `_detect_candidate_subsets` stays in analyze.py. Moving it to row_builder.py creates `row_builder ↔ suggestions` cycle.
5. **No re-export shims.** `analyze.py`'s `__all__` shrinks to `["analyze"]`. Types are importable from `types.py` only.
6. **`stages/__init__.py` must be empty.** Only `stages/discrepancy/__init__.py` needs re-exports.
7. **Line numbers are approximate.** Function names are exact. Always search by function name.
8. **5-pattern search for references.** Standard imports alone miss 150+ string-based references in tests.
9. **`tests/fixtures/cache_analysis/` stays as-is.** Don't rename the fixtures directory or test file names.
10. **`_batch_aliases`, `_cache_items`, `_cache_item_names` go in suggestions.py** (not row_builder.py). Only `_node_inputs` goes in row_builder.py.
