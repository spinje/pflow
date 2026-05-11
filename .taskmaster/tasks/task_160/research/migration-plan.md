# Migration Plan

Phasing recommendation, open decisions, and operational guidance for the implementer. The end-state is fully specified in `end-state-architecture.md`; this doc is about how to *get there safely*.

## Phasing recommendation: five phases, but one PR

### Phase 1 — `types.py` extraction
**Smallest, lowest-risk, highest first-day value.** Lift the 9 dataclasses out of `analyze.py` into a new `types.py`. Update internal imports (analyze, render_text, render_json, summarize, view_helpers, cost_estimation). Delete the lazy-import workaround at `view_helpers.py:84`.

- Source LOC moved: ~294
- Behavior change: zero
- Risk: low — pure mechanical move
- Tests: every test that imports a dataclass updates its import path; no test logic changes

### Phase 2 — `rendering/` subdirectory
Move `render_text.py` → `rendering/text.py`, `render_json.py` → `rendering/json.py`, `view_helpers.py` → `rendering/views.py`, `summarize.py` → `rendering/summarize.py`. Update package `__init__.py` to re-export from new paths. Add `rendering/__init__.py`. Dedupe `_workflow_short_name` (canonical version in `rendering/views.py`).

- Source LOC moved: ~1,663 (sum of the four files)
- Behavior change: zero
- Risk: low — moves + import updates only

### Phase 3 — `stages/` directory (the bulk of the refactor)
Lift the six clusters out of `analyze.py` into stage files. The discrepancy cluster splits into a `discrepancy/` sub-package as it lifts. Fold `padding_advisor.py` into `stages/padding.py`. Collapse the four per-node warning visitors into one walk in `stages/rules.py`. Delete the `_build_recommended_actions` compatibility shim. Resolve the `_iter_llm_events` test-only orphan.

This is the largest phase. Could optionally be split further (per stage), but each stage is a coherent unit and going stage-by-stage gives the implementer 6+ clean checkpoints internally.

- Source LOC moved: ~2,400
- Behavior change: zero (the rules.py collapse is an internal restructure that produces the same diagnostic emissions)
- Risk: medium — mostly mechanical but with the rules.py shape change adding a small thinking-required surface

### Phase 4 — Test consolidation
After phases 1–3, all test imports have been updated mechanically. Phase 4 is the surgical cleanup:
- Migrate the 4–5 highest-call-count local fixture factories (`_make_analysis` 54 calls, `_row` ~56 calls across 3 files, `_write_trace` 20 calls, `_make_diag` 12 calls, `_candidate` 12 calls) into shared fixtures (extend `tests/shared/trace_fixture_builder.py` or add `tests/conftest.py`).
- Drop tests that bind to symbols deleted in phases 1–3 with no public-API replacement, *only* where behavioural coverage exists elsewhere.

Don't try to mandate "every test uses TraceFixtureBuilder" — that's its own task. Consolidate the obvious duplication; leave the rest.

- Risk: low — narrow, value-driven cleanup

### Phase 5 — Documentation
- Add `cache_analysis/CLAUDE.md` (outline in `end-state-architecture.md`).
- Update `core/CLAUDE.md` if needed (verify it mentions the cache_analysis subpackage; may have been updated during task 159).
- Update `tests/CLAUDE.md` if Phase 4 changes test fixture conventions (current refs at lines 127, 329-341).

- Risk: zero

### Phase ordering rationale
Phases 1 and 2 are nearly free wins that a future change in phase 3 doesn't depend on; landing them first reduces phase 3's diff size. Phase 3 carries most of the risk; isolating it is a feature. Phase 4 has to follow phase 3 because the test imports must already be correct. Phase 5 can land any time but has the most signal at the very end.

## Open decision: walker filename collision

Two files would be named `cross_workflow.py` (different directories):

- `cache_analysis/cross_workflow.py` — the WALKER (data primitive, 4 consumers)
- `cache_analysis/stages/cross_workflow.py` — the analytical stage (one consumer of the walker's output)

Python distinguishes by full path, but `find . -name cross_workflow.py` returns 2 hits — mild AI-agent friction.

**Option A**: rename the walker to `cache_analysis/sub_workflow_walker.py` and let the analytical stage keep the natural name. Walker has 4 internal consumers (all in `analyze.py`); rename cost is one search-and-replace.

**Option B**: leave both as `cross_workflow.py`. The dir distinction is enough for Python; readers searching the codebase see two hits and identify which by directory.

**Recommendation**: Option B (leave them). Two files in different directories with the same name is a normal Python pattern. The cognitive cost of the rename outweighs the cognitive cost of two search hits. Implementer's call if they disagree.

## Open decision: phase 3 test compatibility

The 19 private symbols imported across ~36 test sites all need their import paths updated when their target moves. Two ways to do this:

**Option A (recommended)**: surgical updates. Each import site is updated as part of the same commit that moves the symbol. Tests stay green throughout phase 3.

**Option B**: re-export shims in `analyze.py`. Add `from .stages.discrepancy.predict import _predict_cache_keys` etc. at the top of `analyze.py` so tests' existing `from pflow.core.cache_analysis.analyze import _predict_cache_keys` keeps working.

Why option A is better:
- Shims hide the refactor — readers grep `analyze.py` and see imports they have to chase.
- Shims accumulate. Once added "temporarily" they tend to stay.
- The coupling is already known and tracked. Surgical updates are the cleanest path through.

The implementer may choose option B if it materially simplifies an intermediate phase-3 commit, but the final state must be option A — no shims in the merged result.

## Operational notes for the implementer

### Verification approach for "zero behavior change"

1. Before starting: capture reference outputs for at least three workflows (greenfield, with-cache, with-trace). Run `pflow analyze-cache <workflow>` and `pflow analyze-cache <workflow> --json` for each. Save the outputs.
2. After each phase: re-run and diff. The text diff should be empty. The JSON diff should be empty modulo `analyzed_at` timestamps.
3. After phase 3: also re-run `pflow run --dry-run` on a workflow that triggers the cache nudge and confirm the Diagnostic content is identical.

### Discrepancy stage lazy imports — keep them lazy

`stages/discrepancy/predict.py` will lazy-import `compile_workflow`, `Registry`, `create_planner_shared`, `plan_node`. These imports are intentionally lazy because:

- `cache_analysis.__init__` re-exports `summarize`, called on every `pflow run --dry-run`.
- LiteLLM (transitively imported by the runtime modules) costs ~700ms to load.
- Eager runtime imports would slow every dry-run by 700ms.

Don't make these imports eager during the move. The pattern stays.

### `--dry-run` and analyze-cache share the predictor — don't duplicate it

`execution/plan.py::create_planner_shared` and `runtime/engine/plan_node.py::plan_node` are the canonical cache-key predictor. Both `--dry-run` and the discrepancy stage call them. The function `create_planner_shared` was specifically renamed from private (`_create_planner_shared`) in the task 159 PR to make it shareable. Don't fork or reimplement; the substrate is unified.

### Test parameterize and TraceFixtureBuilder are partially adopted

A common assumption ("there's no parametrize and no TraceFixtureBuilder usage") is wrong. Current state:
- Parametrize: 4 uses (`test_cache_analysis_analyze.py` ×1, `test_cache_analysis_per_id_coverage.py` ×1, `test_cache_analysis_warnings.py` ×2)
- TraceFixtureBuilder: 3 sites, all in `test_cache_analysis_analyze.py`

Phase 4 extends adoption; it doesn't introduce.

### Two compatibility decisions made for you

- **Public API stable through `__init__.py`**: production consumers (CLI, runner, MCP, data_flow) keep working unchanged. This is a constraint, not a goal — don't change anything that breaks it.
- **No re-export shims**: as above. Final state has none.

## Out-of-scope follow-ups

These came up during analysis but are explicitly NOT part of this task. Track them as separate tickets:

- **Walker dedup with mermaid renderer.** The cross-workflow walker (`cache_analysis/cross_workflow.py`) and the mermaid renderer (`core/workflow/mermaid/_render.py`) walk the same sub-workflow graph. The task 159 spec (DD#26) notes the cache walker "mirrors the mermaid renderer's traversal pattern." Could extract a single shared `core/workflow/sub_workflow_walker.py`. **Out of scope here.**
- **Trace 2.1.0 typed schema.** The runtime → analyzer contract (`cache_source`, `cache_key`, `cache_age_sec`, `workflow_path`) is currently agreed-upon JSON keys. A `TypedDict` would catch typos at mypy time. **Out of scope; revisit when a bug motivates it.**
- **`AnalyzeOptions` dataclass.** The 7-keyword `analyze()` signature works fine. Replacing with a dataclass is cosmetic. **Out of scope.**
- **Architecture/CLAUDE.md updates.** The architecture index doesn't mention task 159's cache_analysis subpackage. Probably worth a doc update. **Out of scope here; flag for whoever owns the architecture index.**
