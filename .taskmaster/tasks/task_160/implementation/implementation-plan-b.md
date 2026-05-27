# Task 160 — Prompt Cache Analysis Architectural Deepening — Execution Plan

**Branch:** `refactor/cache-analysis-refactor`
**Spec:** `.taskmaster/tasks/task_160/task-160.md`
**Verification gate at every phase:** `.taskmaster/tasks/task_159/baseline/verify.sh`

> **Plan revision history**:
> - **v1** drafted from spec + pre-flight searcher verifications.
> - **v2** after `/code-review` skill ran 4 review agents in parallel (review-plan, review-impact-completeness, review-test-fidelity, review-feature-interactions). 9 confirmed critical findings + 11 confirmed warnings folded in. Most-load-bearing v2 corrections: (a) Phase 4 `resolve_ref_value_in_workflow` outline now mirrors `resolve_ref_value`'s workflow-input branching + parameter fallback; (b) Phase 6 step 4 `_RowCrossWorkflowCandidate` destination is unambiguously `types.py`; (c) Phase 7 preserves the trace+declared `cached_now_tokens_estimated` derivation that v1 silently dropped; (d) Phase 7 strategy revised to incremental per-file rollout (not big-bang sed) because 30-50 of 77 renderer sites need explicit `CacheProjection` instances; (e) Phase 5 explicit ordering constraint for truncated-trace filter; (f) Phase 2 sed replaced with a Python migration script; (g) two missing test migrations added (`test_cache_analysis_analyze.py:830,849` for Phase 4; `test_cache_analysis_per_id_emission.py:5378` for Phase 6); (h) the `_row_has_real_data` wrapper at `rendering/text.py:2307-2310` deletion is now explicit; (i) `_workflow_basename` moves to `types.py` instead of being duplicated; (j) Phase 9 adds a `/code-review` skill checkpoint.

---

## Context

The `pflow.core.prompt_cache_analysis` package shipped a structural decomposition (rename `cache_analysis/` → `prompt_cache_analysis/`, split analyze.py into stages/ and rendering/) in the previous task-160 commit history. That work landed correctly but left six concrete frictions where the implementation has diverged from the package's own stated intent:

1. `analyze.py` is 1,095 LOC; its CLAUDE.md says the orchestrator "should stay small and read as orchestration." The body of `analyze()` is 330 LOC across 17 inline sub-steps.
2. `PerCallRow.__post_init__` carries an 82-LOC legacy bridge that the docstring itself admits is debt. The producer side carries a parallel ~76 LOC of bridge code in `stages/row_builder.py`.
3. `stages/cross_workflow.py` mixes ~270 LOC of `_format_*` rendering helpers into a 1,344-LOC analytical stage. The seam between the two is verified clean (one call, three frozen dataclasses, no `Diagnostic` import on the render side).
4. `AnalysisContext` is workflow-path-locked, forcing `stages/cross_workflow.py` to re-implement 188 LOC of parallel resolution chain with `workflow_path` as a parameter.
5. `cost_estimation.py:__all__` already declares 4 internal helpers public (with underscore prefix). Tests import them across what looks like a "private" boundary that was never private.
6. `_template_resolver()` is byte-identical across 4 files (not 3 as the retrospective claimed); two files named `cross_workflow.py` exist at different package levels; `_cache_items` has a name collision between the walker and a stage.

The package shape is good. This refactor closes the gap between shape and the package's own stated invariants. **Zero behavior change.**

**Verified pre-flight invariants (do not re-litigate during implementation):**

| Concern | Verdict | Evidence |
|---|---|---|
| Cycle inversion for G1.5d move | **Safe** | `stages/cross_workflow.py → stages/row_builder.py` is the existing one-way edge; reverse edge does not exist. The 6 lazy imports inside producer bodies become same-module references after move. Need one new top-level import (`get_default_workflow_model` from `pflow.core.llm_config`) which is external to the analyzer package — no back-edge. **`_RowCrossWorkflowCandidate` itself moves to `types.py` (not `stages/cross_workflow.py`) to break the potential cycle with `stages/row_builder.py` which references it via the `_PerCallRowsResult.cross_workflow_candidates_by_row` field.** |
| `stale_memo_*` threading for G4 | **Safe** | Two existing mirror cluster sites in the package (`stages/cross_workflow.py:417` and `token_estimation.py:611-649`) already mutate `ctx.stale_memo_skipped/uncheckable` with non-root `workflow_path` keys. The sole consumer at `stages/summary.py:342-343` is `len()`. No consumer iterates the sets. NOTE: `token_estimation.py:612-649` is `_memo_output_for_freshness_check` — a memo OUTPUT READER, not a ref-resolver. Different abstraction layer; correctly out of scope. |
| PerCallRow legacy bridge — two-block distinction | **Mixed reachability** | The `__post_init__` has TWO independent blocks: **(A) lines 411-418** derive `cached_now_tokens_estimated` from `cache_creation_input_tokens` + `cache_read_input_tokens` — **this block IS reached in production** whenever trace data exists and MUST be preserved. **(B) lines 419-485** synthesize projection objects from the legacy `cacheable_tokens_estimated` scalar — **this block is unreachable in production** because `_apply_cross_workflow_projection` (row_builder.py:321) only updates the legacy scalar when its sibling `_cross_workflow_projection_components` also produces a projection component; they fire in parallel by construction. Phase 7 deletes block (B) and **preserves block (A) PLUS an additional `cached_now = cacheable_tokens_estimated` derivation for the trace+declared case at lines 458-463** (see Phase 7 step 6). The harness catches any production regression as drift. |

---

## Verification protocol — use at every phase boundary

### One-time pre-flight (Phase 0)

```bash
cd .taskmaster/tasks/task_159/baseline
bash verify.sh 2>&1 | tee /tmp/baseline-pre-refactor.log
# Capture the 7 "drifted cases" listed after "drifted cases:" — these are the known-stale set.
# Expected baseline: 80 passed, 7 drifted (the retrospective documents these as pre-existing
# from feature work PRs #390, #392, #396, #405, #412, #416, #418 — NOT caused by this refactor).
```

Note: the harness has 87 cases total (retrospective said "80 passed, 7 drifted" → 87 total). The README at `baseline/README.md` says "79" — that's stale.

### After every phase commit

```bash
cd .taskmaster/tasks/task_159/baseline
bash verify.sh
```

**Green = exit 1 with the same 7 drifted cases** as `/tmp/baseline-pre-refactor.log`.
**Red = ANY new drifted case** (different case name than the 7), or exit 2 (harness error).

Interpretation:
- Exit 0 = byte-perfect (won't happen until pre-existing drift is regenerated; out of scope).
- Exit 1 with same drift list = no behavior regression. Proceed.
- Exit 1 with NEW case names = regression. Read the unified diff (printed inline by verify.sh), find the cause, fix before commit.
- Exit 2 = harness error (case crashed). Diagnose immediately — analyzer startup likely broke.

For fast iteration during a single phase, use a single surface:

```bash
bash verify.sh 04-warning-catalog   # ~1-2 minutes
```

### Additional checks after every phase

```bash
make test
make check                          # Run twice if first fails on import ordering — ruff auto-fixes
```

Pass count for `make test` should be identical phase-to-phase (no test deletions in this refactor except dead test removals tied to deleted code).

---

## Phase ordering rationale

Foundation first (low-risk, mechanical, proves the verification protocol). High-volume mechanical second. Structural deepenings third, in order of increasing invasiveness. Test fixture migration last (largest single phase).

| Phase | Goal | Risk | Effort | LOC delta |
|---|---|---|---|---|
| 0 | Pre-flight: capture baseline drift | none | ~10 min | 0 |
| 1 | Cost rename (G5) + template_resolver fold (G6.1) | low | ~1 h | -4 LOC |
| 2 | Walker rename (G6.2) + _cache_items disambig (G6.3) | low-medium | ~2 h | ~0 LOC (rename + ~75 string updates) |
| 3 | Cross-workflow analysis/rendering split (G3) | medium | ~3 h | +/-0 (270 moves out, 80 dataclasses move to types) |
| 4 | AnalysisContext parametric extension (G4) | medium | ~3 h | -158 LOC (collapse mirror cluster) |
| 5 | Orchestrator inline-block extraction (G1.1-G1.4) | low | ~1 h | -80 LOC orchestrator body |
| 6 | Helper relocations + cycle inversion (G1.5-G1.6) | medium | ~3 h | -600 LOC from analyze.py |
| 7 | PerCallRow bridge removal (G2) | medium-high | ~6-8 h | -158 LOC across two files; ~100 test site migration |
| 8 | Documentation (G7 + CLAUDE.md updates) | low | ~1 h | small |
| 9 | Final verification (full Bx pass) | none | ~30 min | 0 |

Total estimate: ~20-22 hours of focused implementation work.

---

## Phase 0 — Pre-flight (read-only, ~10 minutes)

### Steps

1. **Capture the known-drift baseline:**
   ```bash
   cd .taskmaster/tasks/task_159/baseline
   bash verify.sh 2>&1 | tee /tmp/baseline-pre-refactor.log
   ```
   Save the list of 7 drifted case names that appear after `drifted cases:` in the output. These are the **known-drift set**.

2. **Run unit tests for baseline + capture the per-test reference set** (test-fidelity review W3):
   ```bash
   make test 2>&1 | tail -3   # capture "N passed" count
   uv run pytest --collect-only -q 2>&1 | tee /tmp/baseline-collected-tests.log
   # The collected-tests log is the PER-TEST reference for Phase 7 regressions.
   # Pass-count alone catches additions/removals; this catches individual test losses.
   make check
   ```

3. **Record current package metrics for the success criteria:**
   ```bash
   grep -rn "from pflow.core.prompt_cache_analysis.*import _" tests/ --include="*.py" | wc -l
   # Expected: 75 (target: ≥ 60 after Phase 1's cost rename eliminates ~15)

   wc -l src/pflow/core/prompt_cache_analysis/analyze.py
   # Expected: 1095 (target: ≤ 350)

   wc -l src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py
   # Expected: 1344 (target: ≤ 1070)

   grep -rn "def _template_resolver" src/pflow/core/prompt_cache_analysis/
   # Expected: 4 sites (target: 0; replaced by 1 in context.py named `template_resolver`)
   ```

4. **Do NOT commit anything in this phase.** Phase 0 is read-only state capture.

### Gate

The 7 drifted case names are written down; baseline metrics are noted; `make test` passes.

---

## Phase 1 — Foundation cleanups (~1 hour)

Combines G5 (cost API rename) and G6.1 (`_template_resolver` fold). Both are tiny, mechanical, and let us validate the verification protocol on the smallest possible diffs first.

### G5 — Cost API rename

**Files modified:**
- `src/pflow/core/prompt_cache_analysis/cost_estimation.py` (rename internals)
- `src/pflow/core/prompt_cache_analysis/stages/suggestions.py` (3 references)
- `src/pflow/core/prompt_cache_analysis/stages/warnings.py` (1 lazy import)
- `src/pflow/core/prompt_cache_analysis/stages/summary.py` (3 references)
- `src/pflow/core/prompt_cache_analysis/stages/fragmentation.py` (2 references)
- `src/pflow/core/prompt_cache_analysis/stages/partial_declarations.py` (0; transitive)
- `tests/test_core/test_cache_analysis_cost_estimation.py` (~15 import sites)
- `tests/test_core/test_cache_analysis_analyze.py` (~10 import sites)
- `tests/test_core/test_cache_analysis_renderers.py` (~7 import sites)

**Steps:**

1. In `cost_estimation.py`, rename 5 functions (drop underscore prefix):
   - `_aggregate_no_cache_cost` → `aggregate_no_cache_cost`
   - `_aggregate_with_cache_projection` → `aggregate_with_cache_projection`
   - `_row_body_only_cost` → `row_body_only_cost`
   - `_row_first_run_with_cache_cost` → `row_first_run_with_cache_cost`
   - `_pricing_from_dict` → `pricing_from_dict`

2. Update `__all__` in `cost_estimation.py`: list the 4 renamed names without underscore; add `pricing_from_dict` (it wasn't in `__all__` before).

3. Update all internal callers and tests. Use `sed`:
   ```bash
   # production callers (run from repo root)
   grep -rl "_aggregate_no_cache_cost\|_aggregate_with_cache_projection\|_row_body_only_cost\|_row_first_run_with_cache_cost\|_pricing_from_dict" src/pflow/core/prompt_cache_analysis/ tests/ --include="*.py" \
     | xargs sed -i '' \
       -e 's/_aggregate_no_cache_cost/aggregate_no_cache_cost/g' \
       -e 's/_aggregate_with_cache_projection/aggregate_with_cache_projection/g' \
       -e 's/_row_body_only_cost/row_body_only_cost/g' \
       -e 's/_row_first_run_with_cache_cost/row_first_run_with_cache_cost/g' \
       -e 's/_pricing_from_dict/pricing_from_dict/g'
   ```

4. **G5.4 — Hoist stale lazy imports.** The lazy `from ..cost_estimation import ...` inside function bodies at these sites was for an obsolete circular-import concern that no longer applies (verified — `cost_estimation.py` imports from `.types`, never from stages):
   - `stages/suggestions.py:789-793` — `_input_rate` lazy-imports `get_model_pricing`. Hoist to top-level.
   - `stages/warnings.py:572-576` — `_enrich_one_shadow_warning` lazy-imports `row_body_only_cost`, `row_first_run_with_cache_cost`, `get_model_pricing`. Hoist to top-level.
   - `stages/summary.py:138` — `_build_summary` lazy-imports `CostTier`, `compute_actually_paid`, `compute_projections`. The comment at line 136 claims a circular import that does NOT exist (verified). Hoist; delete the stale comment.
   - `stages/summary.py:487` — `_unavailable_models_by_workflow` lazy-imports `get_model_pricing`. Hoist.
   - `stages/summary.py:548` — `_build_sub_workflow_rollup` lazy-imports `compute_projections`. Hoist.
   - `stages/fragmentation.py:300` and `:376` — both lazy-import `_write_rate_for_ttl, get_model_pricing`. Hoist to top-level.

   **Exception — keep lazy:** `cost_estimation.py:187-189` lazy-imports `import_litellm`. Do NOT hoist — `litellm` import is genuinely expensive (~700ms per Task 158 lazy-import policy).

### G6.1 — `_template_resolver()` fold to `context.py`

**Files modified:**
- `src/pflow/core/prompt_cache_analysis/context.py` (+4 LOC)
- `src/pflow/core/prompt_cache_analysis/stages/row_builder.py` (delete lines 51-54)
- `src/pflow/core/prompt_cache_analysis/stages/warnings.py` (delete lines 37-40)
- `src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py` (delete lines 27-30)
- `src/pflow/core/prompt_cache_analysis/stages/discrepancy/predict.py` (delete lines 21-24)

**Steps:**

1. In `context.py`, add a module-level function (after `_PREDICTION_SKIPPED` constant, before the `AnalysisContext` class):
   ```python
   def template_resolver() -> Any:
       """Lazy-imported `TemplateResolver` class for ${var} resolution.

       **DO NOT HOIST** this import to module-top. The `pflow.runtime.template_resolver`
       import transitively loads the runtime stack (~700ms LiteLLM startup per
       Task 158 lazy-import policy). Hoisting would pay that cost on every
       `pflow analyze-cache --dry-run` invocation. The lazy import must live
       inside the function body; module-load of `context.py` must stay cheap.

       See `stages/discrepancy/predict.py` for the parallel policy on
       compile_workflow / plan_node / create_planner_shared lazy imports.
       """
       from pflow.runtime.template_resolver import TemplateResolver
       return TemplateResolver
   ```
   Add `"template_resolver"` to `__all__`.

2. Delete the four byte-identical copies of `_template_resolver()`:
   - `stages/row_builder.py:51-54`
   - `stages/warnings.py:37-40`
   - `stages/cross_workflow.py:27-30`
   - `stages/discrepancy/predict.py:21-24`

3. Update consumers in those four files. The function was always called as `_template_resolver()`; the new form is `template_resolver()`. Add the import line at the top of each file:
   ```python
   from ..context import template_resolver  # in stages/*.py
   from ...context import template_resolver  # in stages/discrepancy/predict.py
   ```
   Replace every `_template_resolver()` call with `template_resolver()` in those four files.

### Phase 1 verification gate

```bash
cd .taskmaster/tasks/task_159/baseline && bash verify.sh
make test
make check                          # may need a second run for import ordering

# G6.1 lazy-import preservation check (feature-int W1):
uv run python -c "
import sys
import pflow.core.prompt_cache_analysis.context
assert 'litellm' not in sys.modules, 'context.py eagerly loaded litellm — template_resolver was likely hoisted'
assert 'pflow.runtime.template_resolver' not in sys.modules, 'context.py eagerly loaded the runtime resolver — template_resolver was likely hoisted'
print('OK: context.py module-load does not transitively load runtime stack')
"

# G6.1 dedup check:
[ "$(grep -rn 'def _template_resolver' src/pflow/core/prompt_cache_analysis/ | wc -l)" -eq 0 ] || { echo "FAIL: _template_resolver duplicates remain"; exit 1; }
```

Expected: same 7 drifted cases as `/tmp/baseline-pre-refactor.log`. Test count unchanged. `grep` for `_template_resolver` returns zero hits in stage files. Module-load assertion passes.

### Note on `_write_rate_for_ttl`

`cost_estimation.py:245` defines `_write_rate_for_ttl` (private, NOT in `__all__`). Lazy-imported by `stages/fragmentation.py:300, 376`. **Intentionally stays private** — it is not in `__all__` and is only consumed by `stages/fragmentation.py`. The G5 rationale ("the export contract has been public the whole time") does NOT apply to symbols that were never exported. Hoist the lazy import to top-level (per G5.4) but do NOT drop the underscore.

### Platform note on `sed`

The `sed -i ''` form is BSD-specific (macOS). On Linux, the syntax is `sed -i`. Use the portable `sed -i.bak ... && find . -name '*.bak' -delete` pattern, OR document explicitly that this plan assumes macOS and the implementing agent must adjust on Linux. The implementing agent should verify their environment before running any `sed` block in this plan.

### Commit message

```
Phase 1: cost API naming + template_resolver fold

G5: 5 cost helpers in cost_estimation.__all__ drop their underscore
prefix to match the export contract. Tests stop importing across
a "private" boundary that was never private.

G5.4: Stale lazy cost_estimation imports inside stage function bodies
hoisted to top-level. The circular-import comment at summary.py:136
referenced a cycle that doesn't exist.

G6.1: _template_resolver() lives once, as a module-level function in
context.py. 4 byte-identical copies deleted (row_builder, warnings,
cross_workflow stage, discrepancy/predict).

Zero behavior change: baseline harness reports same 7 drifted cases
as pre-refactor.
```

---

## Phase 2 — Walker rename + cache_items disambiguation (~2 hours)

### G6.2 — Walker rename `cross_workflow.py` → `sub_workflow_walker.py`

**Files modified (74 in-tree edits total):**
- Source rename: `src/pflow/core/prompt_cache_analysis/cross_workflow.py` → `sub_workflow_walker.py`
- Test rename: `tests/test_core/test_cache_analysis_cross_workflow.py` → `test_cache_analysis_sub_workflow_walker.py`
- 3 src import sites: `trace_loading.py:17`, `analyze.py:53`, `stages/discrepancy/predict.py:15`
- 14 test direct-import sites across 4 files
- 48 `importlib.import_module(...)` string sites (47 in `test_cache_analysis_per_id_emission.py`, 1 in `test_cache_analysis_per_id_coverage.py`)
- 2 `caplog.set_level(..., logger=...)` strings in the test file being renamed
- 5 CLAUDE.md prose lines
- 1 comment line in `src/pflow/core/markdown_parser.py:1625`
- 1 docstring line in `src/pflow/core/prompt_cache_analysis/analyze.py:6`

**Critical risk — disambiguator integrity:** `tests/test_core/test_cache_analysis_per_id_emission.py` contains **8 stage-references that must NOT be touched** (impact-completeness C2 expanded the original 5):
- 5 `cross_stage_module = importlib.import_module("pflow.core.prompt_cache_analysis.stages.cross_workflow")` at lines 137, 1896, 2885, 2982, 3068.
- 2 string-list entries naming the stage module at lines 58, 68 (in `_STAGE_ATTR_MODULES` dict or similar).
- 1 `from pflow.core.prompt_cache_analysis.stages.cross_workflow import ...` at line 5073.

The sed/script pattern below pins the exact walker string (no `.stages.` segment) to prevent accidental collapse.

**Recommended strategy: Python script over sed.** The plan-review reviewer flagged the sed approach as fragile for this volume of changes. Use a Python script that:
1. Iterates over each file in the consumer set.
2. For each occurrence of `"pflow.core.prompt_cache_analysis.cross_workflow"` (exact string, NOT a regex), prints a `BEFORE / AFTER` diff line.
3. Stops if any line contains `stages.cross_workflow` as a substring (defensive).
4. Writes only when every diff has been confirmed by the script's check.

A minimal Python migration script:
```python
#!/usr/bin/env python3
"""Walker rename migration — Phase 2."""
import pathlib, re, sys

CONSUMER_FILES = [
    "src/pflow/core/prompt_cache_analysis/trace_loading.py",
    "src/pflow/core/prompt_cache_analysis/analyze.py",
    "src/pflow/core/prompt_cache_analysis/stages/discrepancy/predict.py",
    "tests/test_core/test_cache_analysis_per_id_emission.py",
    "tests/test_core/test_cache_analysis_per_id_coverage.py",
    "tests/test_core/test_cache_analysis_analyze.py",
    "tests/test_core/test_sub_workflow_resolver.py",
    "tests/test_core/test_cache_analysis_sub_workflow_walker.py",  # post-rename
    "src/pflow/core/markdown_parser.py",
    "src/pflow/core/prompt_cache_analysis/CLAUDE.md",
]

# The exact walker string (no .stages. segment). Pin with negative lookahead.
WALKER_PATTERN = re.compile(r'pflow\.core\.prompt_cache_analysis\.cross_workflow(?!\w)')

for f in CONSUMER_FILES:
    p = pathlib.Path(f)
    if not p.exists():
        print(f"SKIP (not found): {f}")
        continue
    text = p.read_text()
    # Defensive: count stage references; they must be identical before/after.
    stage_count = text.count("pflow.core.prompt_cache_analysis.stages.cross_workflow")
    new_text = WALKER_PATTERN.sub("pflow.core.prompt_cache_analysis.sub_workflow_walker", text)
    new_stage_count = new_text.count("pflow.core.prompt_cache_analysis.stages.cross_workflow")
    assert stage_count == new_stage_count, f"FAIL: stage refs corrupted in {f}: {stage_count} → {new_stage_count}"
    if new_text != text:
        diff_count = sum(1 for a, b in zip(text.split("\n"), new_text.split("\n")) if a != b)
        print(f"OK: {f} — {diff_count} lines changed")
        p.write_text(new_text)

# Also handle the relative imports (manual, 3 sites only — see step 4)
```

**Steps:**

1. **Rename the source file** (use `git mv` to preserve history):
   ```bash
   git mv src/pflow/core/prompt_cache_analysis/cross_workflow.py \
          src/pflow/core/prompt_cache_analysis/sub_workflow_walker.py
   ```

2. **Rename the test file:**
   ```bash
   git mv tests/test_core/test_cache_analysis_cross_workflow.py \
          tests/test_core/test_cache_analysis_sub_workflow_walker.py
   ```

3. **Update full dotted-path imports** (CRITICAL: pin the exact walker string, no `.stages.` segment):
   ```bash
   # Use word-boundary matching so .stages.cross_workflow is NOT matched.
   # The pattern matches "pflow.core.prompt_cache_analysis.cross_workflow" exactly,
   # which is the walker. The stage's path includes ".stages." which won't match.
   grep -rl '"pflow\.core\.prompt_cache_analysis\.cross_workflow"' src/ tests/ --include="*.py" \
     | xargs sed -i '' 's|"pflow\.core\.prompt_cache_analysis\.cross_workflow"|"pflow.core.prompt_cache_analysis.sub_workflow_walker"|g'

   grep -rl 'from pflow\.core\.prompt_cache_analysis\.cross_workflow' src/ tests/ --include="*.py" \
     | xargs sed -i '' 's|from pflow\.core\.prompt_cache_analysis\.cross_workflow|from pflow.core.prompt_cache_analysis.sub_workflow_walker|g'

   grep -rl 'import pflow\.core\.prompt_cache_analysis\.cross_workflow' src/ tests/ --include="*.py" \
     | xargs sed -i '' 's|import pflow\.core\.prompt_cache_analysis\.cross_workflow|import pflow.core.prompt_cache_analysis.sub_workflow_walker|g'
   ```

4. **Update relative imports manually** (only 3 sites, all in `src/`):
   - `src/pflow/core/prompt_cache_analysis/trace_loading.py:17`:
     - Before: `from .cross_workflow import walk_cross_workflow`
     - After: `from .sub_workflow_walker import walk_cross_workflow`
   - `src/pflow/core/prompt_cache_analysis/analyze.py:53`:
     - Before: `from .cross_workflow import CrossWorkflowEdge, walk_cross_workflow`
     - After: `from .sub_workflow_walker import CrossWorkflowEdge, walk_cross_workflow`
     - **Do NOT touch line 54** (`from .stages.cross_workflow import ...`) or lines 871/946 (lazy stage imports).
   - `src/pflow/core/prompt_cache_analysis/stages/discrepancy/predict.py:15`:
     - Before: `from ...cross_workflow import DynamicBatchInfo`
     - After: `from ...sub_workflow_walker import DynamicBatchInfo`

5. **Update caplog logger strings** in the renamed test file:
   - `tests/test_core/test_cache_analysis_sub_workflow_walker.py:142` and `:164`:
     - Before: `caplog.set_level(logging.INFO, logger="pflow.core.prompt_cache_analysis.cross_workflow")`
     - After: `caplog.set_level(logging.INFO, logger="pflow.core.prompt_cache_analysis.sub_workflow_walker")`
   - (The sed in step 3 should catch these because they use the full walker string; verify with grep after.)

6. **Update prose references:**
   - `src/pflow/core/markdown_parser.py:1625`: update comment text from `prompt_cache_analysis/cross_workflow.py` to `prompt_cache_analysis/sub_workflow_walker.py`.
   - `src/pflow/core/prompt_cache_analysis/analyze.py:6`: docstring mentions `cross_workflow` walker. Update to `sub_workflow_walker` walker.
   - `src/pflow/core/prompt_cache_analysis/CLAUDE.md`: lines 49, 76, 78, 109, 254 — update prose; **remove** the "There are two `cross_workflow.py` files by design" note at line 76 (replaced with no analog because there's no longer a collision).

7. **Verify nothing was missed:**
   ```bash
   # Should return zero hits (walker references):
   grep -rn '\bpflow\.core\.prompt_cache_analysis\.cross_workflow\b' src/ tests/ --include="*.py" \
     | grep -v 'stages\.cross_workflow'

   # Should still find 5+ hits (stage references — must NOT have been touched):
   grep -rn 'pflow\.core\.prompt_cache_analysis\.stages\.cross_workflow' tests/ --include="*.py" | wc -l
   ```

### G6.3 — `_cache_items` name collision disambiguation

The walker file (now `sub_workflow_walker.py:417-424`) defines `_cache_items(ir) -> tuple[dict, ...]`. The stage file (`stages/suggestions.py:720-727`) defines `_cache_items(workflow_ir) -> list[dict]`. Same name, different return type.

**Decision:** Rename the walker-side function to `_cache_items_as_tuple` and keep `stages/suggestions.py`'s `_cache_items` as-is. The walker version has only 2 internal callers; the stage version has 4+ callers across the package.

**Files modified:**
- `src/pflow/core/prompt_cache_analysis/sub_workflow_walker.py:205, 342, 417` (3 sites — definition + 2 call sites)

**Steps:**

1. In `sub_workflow_walker.py`, rename the function at line 417 to `_cache_items_as_tuple`.
2. Update both internal callers at lines 205 and 342.
3. The function is private and has no consumers outside this file (verified via grep). No other files need updating.

### Phase 2 verification gate

```bash
# Critical safety checks BEFORE running the harness:
find src/pflow -name "cross_workflow.py"  # Should return ONE path: stages/cross_workflow.py
ls src/pflow/core/prompt_cache_analysis/sub_workflow_walker.py  # Should exist
ls src/pflow/core/prompt_cache_analysis/cross_workflow.py 2>&1  # Should report not-found

# Run the harness:
cd .taskmaster/tasks/task_159/baseline && bash verify.sh
make test
make check
```

Expected: same 7 drifted cases. Test count unchanged.

### Commit message

```
Phase 2: walker rename + cache_items disambiguation

G6.2: Rename package's root walker file cross_workflow.py →
sub_workflow_walker.py. Eliminates file-name collision with the
analytical stage (stages/cross_workflow.py). CLAUDE.md
disambiguation note removed. ~75 in-tree edits across 8 files
(3 src imports, 14 test imports, 48 importlib strings, 2 caplog
strings, 5 CLAUDE.md prose lines, 1 comment, 1 docstring).
Test file renamed to mirror.

G6.3: Walker-side _cache_items renamed to _cache_items_as_tuple.
The package now contains one _cache_items function with one
return type.

Zero behavior change: baseline harness reports same 7 drifted
cases as pre-refactor.
```

---

## Phase 3 — Cross-workflow analysis/rendering split (G3, ~3 hours)

**Files modified:**
- New: `src/pflow/core/prompt_cache_analysis/rendering/cross_workflow_edits.py` (~270 LOC)
- `src/pflow/core/prompt_cache_analysis/types.py` (+80 LOC — three private dataclasses move IN)
- `src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py` (-270 LOC — `_format_*` helpers move OUT; -5 LOC — `cw_result` parameter threading vestige; move 3 dataclasses out)
- `src/pflow/core/prompt_cache_analysis/rendering/__init__.py` (decide whether to re-export `format_grouped_body_block` — likely NO; the analysis side is the only consumer)

### Steps

1. **Move three frozen dataclasses to `types.py`** with their underscore prefix preserved (they are package-internal, not part of the public API):
   - `_SubWorkflowCacheCandidate` from `stages/cross_workflow.py:142-172` → `types.py`
   - `_ChildCacheRefUse` from `stages/cross_workflow.py:175-181` → STAYS in `stages/cross_workflow.py` (purely internal to analysis side; not consumed by rendering)
   - `_GroupedConsumerProjection` from `stages/cross_workflow.py:184-208` → `types.py`
   - `_SubWorkflowCacheGroup` from `stages/cross_workflow.py:211-216` → `types.py`

   Add to `types.py` after the existing dataclasses (e.g., after `CrossWorkflowFindings`). Add a `cache_refs_by_consumer()` method on `_SubWorkflowCacheGroup`:
   ```python
   def cache_refs_by_consumer(self) -> dict[str, list[str]]:
       refs_by_consumer: dict[str, list[str]] = {}
       for candidate in self.candidates:
           for node_id in candidate.child_node_ids:
               refs_by_consumer.setdefault(node_id, []).append(candidate.child_cache_ref)
       return refs_by_consumer
   ```

2. **Delete `_cache_refs_by_consumer` free function** from `stages/cross_workflow.py:744-749`. Replace its two call sites (line 760 in analysis side, line 1087 in rendering side which moves) with `group.cache_refs_by_consumer()`.

3. **Create `rendering/cross_workflow_edits.py`** with this skeleton:
   ```python
   """Paste-ready cache-block edit text for cross-workflow recommendations.

   Consumed by stages/cross_workflow.py's _emit_sub_workflow_cache_findings
   via a single call (format_grouped_body_block). The seam exchanges plain
   strings — this module does not import Diagnostic.
   """
   from __future__ import annotations

   from collections.abc import Iterable
   from typing import Any

   from pflow.core.llm_capabilities import anthropic_models_at_threshold

   from ..types import (
       _GroupedConsumerProjection,
       _SubWorkflowCacheCandidate,
       _SubWorkflowCacheGroup,
   )
   from ..stages.row_builder import _static_excerpt

   _PARENT_PROSE_PREVIEW_LIMIT = 40
   _MODEL_SWITCH_BAND = 1024
   ```

4. **Move the following functions from `stages/cross_workflow.py` to `rendering/cross_workflow_edits.py`** (in this order, preserving call graph):

   | Source line range in `stages/cross_workflow.py` | Function | Visibility in new module |
   |---|---|---|
   | 913-1004 | `_format_grouped_body_block` | rename to `format_grouped_body_block` (public — only function called from outside the module) |
   | 1007-1023 | `_format_unmeasurable_grouped_body` | keep `_` (private to module) |
   | 1026-1043 | `_format_refactor_grouped_body` | keep `_` |
   | 1046-1065 | `_append_honest_edit_lines` | keep `_` |
   | 1068-1069 | `_group_has_subpath_candidates` | keep `_` |
   | 1072-1078 | `_subpath_honesty_sentence` | keep `_` |
   | 1081-1092 | `_format_exact_child_cache_edits` | keep `_` |
   | 1095-1114 | `_exact_child_cache_block_content` | keep `_` |
   | 1117-1118 | `_threshold_relation` | keep `_` |
   | 1121-1131 | `_parent_origin_clause` | keep `_` |
   | 1134-1158 | `_format_per_consumer_input_lines` | keep `_` |
   | 1161-1181 | `_format_single_consumer_input_lines` | keep `_` |
   | 1184-1190 | `_count_phrase` | keep `_` |
   | 1193-1194 | `_flow_verb` | keep `_` |
   | 1197-1198 | `_format_tokens_phrase` | keep `_` |
   | 1201-1202 | `_format_nullable_tokens` | keep `_` |
   | 1205-1209 | `_format_var_refs` | keep `_` |
   | 1212-1214 | `_per_input_var_refs` | keep `_` |

5. **Move `_workflow_basename` from `stages/cross_workflow.py:651-652` to `types.py`** (revised per plan-review W5). The original plan suggested duplication, but `_workflow_basename` is 2 lines and used by 4+ sites in the cross-workflow stage AND by the rendering module after split. Putting it in `types.py` (where the three seam dataclasses already live) avoids the duplication entirely:
   ```python
   # In types.py, near the other seam dataclasses:
   def _workflow_basename(workflow_path: str) -> str:
       return workflow_path.rsplit("/", 1)[-1] if "/" in workflow_path else workflow_path
   ```
   Both `stages/cross_workflow.py` and `rendering/cross_workflow_edits.py` import it via `from ..types import _workflow_basename`. Keep the underscore prefix to signal package-internal scope.

6. **Remove vestigial `cw_result` parameter (G3.4):** the `cw_result` parameter is passed through 7 functions in the rendering chain but is never actually used (verified — `_per_input_var_refs` at line 1212 doesn't read it). Remove `cw_result` from the signatures of:
   - `format_grouped_body_block` (was `_format_grouped_body_block`)
   - `_format_unmeasurable_grouped_body`
   - `_format_refactor_grouped_body`
   - `_append_honest_edit_lines`
   - `_format_per_consumer_input_lines`
   - `_format_single_consumer_input_lines`
   - `_per_input_var_refs`

   Update the sole caller (`_emit_sub_workflow_cache_findings` at line 1291) to stop passing `cw_result`.

7. **In `stages/cross_workflow.py`**:
   - Add top-of-file import: `from ..rendering.cross_workflow_edits import format_grouped_body_block`
   - Update `_emit_sub_workflow_cache_findings` to call `format_grouped_body_block(...)` (no underscore — it's the public seam) and to stop passing `cw_result`.
   - Delete the 18 functions moved out.
   - Delete the `_workflow_basename` function (now duplicated in rendering; the analysis side will keep its own copy too).

8. **Verify the seam:** Open `rendering/cross_workflow_edits.py` and confirm:
   - `Diagnostic` is NOT imported (the docstring promised this).
   - The only function reachable from outside the module is `format_grouped_body_block` (every other function starts with `_`).
   - `cw_result` does not appear anywhere in the file.

### Phase 3 verification gate

```bash
cd .taskmaster/tasks/task_159/baseline && bash verify.sh
make test
make check

# Specific assertions:
wc -l src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py  # Expected: ~1,070
wc -l src/pflow/core/prompt_cache_analysis/rendering/cross_workflow_edits.py  # Expected: ~270
grep -n "Diagnostic" src/pflow/core/prompt_cache_analysis/rendering/cross_workflow_edits.py  # Expected: zero hits
grep -n "cw_result" src/pflow/core/prompt_cache_analysis/rendering/cross_workflow_edits.py  # Expected: zero hits
```

### Commit message

```
Phase 3: split cross-workflow analysis from its rendering

G3.1: New rendering/cross_workflow_edits.py hosts all _format_*
helpers and their pure private utilities (~270 LOC). Single
public function format_grouped_body_block; one caller
(_emit_sub_workflow_cache_findings).

G3.2: Three seam dataclasses (_SubWorkflowCacheCandidate,
_SubWorkflowCacheGroup, _GroupedConsumerProjection) live in
types.py with package-internal naming.

G3.3: _cache_refs_by_consumer becomes a method on
_SubWorkflowCacheGroup. Both analysis and rendering call
group.cache_refs_by_consumer().

G3.4: Vestigial cw_result parameter removed from 7 render-side
functions and from the single emit-side caller.

G3.5: Render module does not import Diagnostic; the seam
exchanges plain strings via make_diagnostic(body_block=...).

stages/cross_workflow.py: 1,344 → ~1,070 LOC.

Zero behavior change: baseline harness reports same 7 drifted
cases as pre-refactor.
```

---

## Phase 4 — AnalysisContext parametric extension (G4, ~3 hours)

**Depends on Phase 1 G6.1** (uses `template_resolver()` helper now in `context.py`).

**Files modified:**
- `src/pflow/core/prompt_cache_analysis/context.py` (+60 LOC — two new methods + parameter threading)
- `src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py` (-158 LOC — six helpers collapse to delegation)
- `tests/test_core/test_cache_analysis_analyze.py` — **2 sites** (lines 830, 849) that currently import `_resolve_value_in_workflow_memo` directly must migrate to `ctx.resolve_ref_value_in_workflow(...)` (impact-completeness C1)

### Steps

1. **Read the existing mirror helpers** in `stages/cross_workflow.py`:
   - `_resolve_value_in_workflow_memo` (lines 399-433)
   - `_resolve_value_in_workflow_parameters` (lines 436-472)
   - `_resolve_value_in_workflow_trace` (lines 507-534)
   - `_trace_node_output_for` (lines 475-504)
   - `_resolve_input_at_workflow_node_invocation` (lines 537-585)
   - `_resolve_child_suffix_in_value` (lines 588-595)

   The first three mirror `AnalysisContext._resolve_from_memo`, `_resolve_from_parameters`, and the trace-output portion of `resolve_ref_value_for_projection`. They take `workflow_path` as a parameter rather than reading `self.workflow_path`.

2. **Add `AnalysisContext.resolve_ref_value_in_workflow(ref, *, workflow_path)`** at `context.py`, after the existing `resolve_ref_value` method (around line 205). The implementation MUST mirror `resolve_ref_value`'s **workflow-input-vs-node-id tier branching** AND the **parameter fallback** found in the existing `_resolve_value_in_workflow_parameters` helper at `stages/cross_workflow.py:436-472` (feature-interactions C2):

   ```python
   def resolve_ref_value_in_workflow(
       self,
       ref: str,
       *,
       workflow_path: str | None,
       irs_by_workflow: Mapping[str, Mapping[str, Any]] | None = None,
   ) -> Any | None:
       """Resolve a template ref against a specific workflow's scope.

       Workflow-path-parametric form of resolve_ref_value. For sub-workflow
       boundary findings where the value lives in a parent workflow (not
       the analyzer's root).

       Tier branching mirrors resolve_ref_value:
       - If `root` is declared as an input on the targeted workflow's IR:
         parameters-for-workflow win over memo (current user inputs beat
         historical memo).
       - If `root` is a node id: memo only.

       Fallback (preserved from stages/cross_workflow.py:461-462):
       If `root` is not present in the workflow-scoped parameters but IS
       present in the analyzer root's parameters (ctx.parameters), fall
       back to root parameters. Necessary when a child workflow inherits
       a parameter without explicit threading (real-world workflows do this).

       Stale-memo accumulators (ctx.stale_memo_skipped, ctx.stale_memo_uncheckable)
       are mutated with keys scoped to the passed workflow_path, not
       ctx.workflow_path. Consumers count entries via len() only — verified
       safe (feature-interactions Q2).

       `irs_by_workflow` is optional. When provided, enables the workflow-input
       branch via the target workflow's `inputs:` declaration. When None
       (most callers), all roots are treated as node-output roots → memo-only.
       Callers that need the workflow-input branch must pass cw_result.irs_by_workflow.
       """
       template_resolver_cls = template_resolver()  # uses Phase 1 G6.1 helper
       root = template_resolver_cls.extract_root_node_id(ref)
       if not root:
           return None

       # Workflow-input-vs-node-id branching (mirrors resolve_ref_value's logic)
       declared_inputs = None
       if irs_by_workflow is not None and workflow_path is not None:
           target_ir = irs_by_workflow.get(workflow_path)
           if isinstance(target_ir, Mapping):
               declared_inputs = target_ir.get("inputs")

       if isinstance(declared_inputs, Mapping) and root in declared_inputs:
           # Tier 0: workflow-scoped parameters win over memo
           value = self._resolve_from_parameters_in_workflow(
               ref, root, workflow_path=workflow_path
           )
           if value is not None:
               return value
           # Fall through to memo if parameters didn't resolve

       # Tier 1 (workflow-scoped memo)
       return self._resolve_from_memo_in_workflow(ref, root, workflow_path=workflow_path)
   ```

   Add private helpers `_resolve_from_parameters_in_workflow` and `_resolve_from_memo_in_workflow` that mirror `_resolve_from_parameters` and `_resolve_from_memo` but take `workflow_path` as a parameter. The parameters helper MUST preserve the fallback:
   ```python
   def _resolve_from_parameters_in_workflow(
       self, ref: str, root: str, *, workflow_path: str | None
   ) -> Any | None:
       """Resolve ref against workflow-scoped parameters with root-params fallback.

       Mirrors stages/cross_workflow.py:436-472. The fallback at lines 461-462
       (if root not in params and root in ctx.parameters: params = ctx.parameters)
       is LOAD-BEARING — real-world workflows inherit parameters without
       explicit threading.
       """
       params = self.parameters_for_workflow(workflow_path)
       if root not in params and root in self.parameters:
           # Fallback to root parameters (preserved from existing mirror)
           params = self.parameters
       if root not in params:
           return None
       template_resolver_cls = template_resolver()
       try:
           resolved = template_resolver_cls.resolve_template(
               f"${{{ref}}}", {root: params[root]}
           )
       except Exception:
           logger.debug("parameters resolve failed for %s in %s", ref, workflow_path, exc_info=True)
           return None
       if isinstance(resolved, str) and resolved == f"${{{ref}}}":
           return None
       return _normalize_empty(resolved)

   def _resolve_from_memo_in_workflow(
       self, ref: str, root: str, *, workflow_path: str | None
   ) -> Any | None:
       """Resolve ref against memo cache scoped to workflow_path.

       Mirrors stages/cross_workflow.py:399-433. Passes workflow_path through
       to _latest_memo_for_freshness_check so stale-memo keys are scoped
       correctly.
       """
       if self.memo_cache is None:
           return None
       try:
           latest = _latest_memo_for_freshness_check(
               self.memo_cache, root, workflow_path=workflow_path, ctx=self
           )
       except Exception:
           logger.debug("memo cache freshness-aware lookup failed for %s", ref, exc_info=True)
           return None
       if latest is None:
           return None
       output, _created_at = latest
       if not isinstance(output, dict):
           return None
       template_resolver_cls = template_resolver()
       try:
           resolved = template_resolver_cls.resolve_template(f"${{{ref}}}", {root: output})
       except Exception:
           logger.debug("memo resolve failed for %s", ref, exc_info=True)
           return None
       if isinstance(resolved, str) and resolved == f"${{{ref}}}":
           return None
       return _normalize_empty(resolved)
   ```

   **Decision on `irs_by_workflow`:** the existing mirror at `stages/cross_workflow.py:436-472` does not consult any workflow's IR — it goes straight to parameters with the fallback. That's why I made `irs_by_workflow` optional. Callers that need the workflow-input branch (currently none — the existing mirror doesn't have it either) can pass it; default behavior matches the existing mirror byte-for-byte. **This preserves zero-behavior-change.**

3. **Add `AnalysisContext.resolve_ref_value_for_projection_in_workflow(ref, *, workflow_path, cw_result)`** with the trace-output extension. The trace-output tier needs `cw_result` for `_edge_child_paths` — accept it as a parameter:
   ```python
   def resolve_ref_value_for_projection_in_workflow(
       self,
       ref: str,
       *,
       workflow_path: str | None,
       cw_result: Any,
   ) -> Any | None:
       value = self.resolve_ref_value_in_workflow(ref, workflow_path=workflow_path)
       if value is not None:
           return value
       # Trace-output tier (mirrors _resolve_value_in_workflow_trace +
       # _trace_node_output_for at stages/cross_workflow.py:475-534)
       # ... [body lifted from those two functions, but parametrized on
       #      workflow_path and using ctx.trace + edge_child_paths]
   ```

4. **In `stages/cross_workflow.py`, replace the six mirror helpers with delegation:**
   - `_resolve_value_in_workflow_memo(ref, *, workflow_path, ctx)` → DELETE (calls `ctx.resolve_ref_value_in_workflow(ref, workflow_path=workflow_path)` at its single call site instead)
   - `_resolve_value_in_workflow_parameters(ref, *, workflow_path, ctx)` → DELETE (same)
   - `_resolve_value_in_workflow_trace(ref, *, workflow_path, ctx, cw_result)` → DELETE (calls `ctx.resolve_ref_value_for_projection_in_workflow(ref, workflow_path=workflow_path, cw_result=cw_result)` instead)
   - `_trace_node_output_for(node_id, *, workflow_path, ctx, cw_result)` → DELETE (folded into AnalysisContext.resolve_ref_value_for_projection_in_workflow)
   - `_resolve_input_at_workflow_node_invocation(...)` → KEEP. This is domain-specific (reads `node_params['inputs'][child_input_name]` from trace events for the input-passthrough case at the parent's workflow-node trace event). It is genuinely cross-workflow stage logic, not generic resolution. Move it to be ~30 LOC after collapse.
   - `_resolve_child_suffix_in_value(value, child_input_name, child_cache_ref)` → KEEP (8 LOC; child-suffix walking is domain-specific to the cross-workflow stage)

5. **Update `_estimate_parent_value_tokens`** (lines 598-648) — the consumer of all 6 mirror helpers. It now calls:
   - `ctx.resolve_ref_value_in_workflow(ref, workflow_path=workflow_path)` (Tier 0+1: parameters + memo, in one call)
   - `ctx.resolve_ref_value_for_projection_in_workflow(ref, workflow_path=workflow_path, cw_result=cw_result)` (Tier 2: trace) — but actually the existing function already separates these tiers, so prefer two distinct calls for clarity OR merge into one. **Decision: keep the existing 4-tier branching in `_estimate_parent_value_tokens` but each branch becomes a 1-line delegation.** The function shrinks from 51 LOC to ~30 LOC.

6. **Threading invariant verification:**
   - `_latest_memo_for_freshness_check` (`context.py:303-332`) currently uses `workflow_path` as a kwarg. The new `_resolve_from_memo_in_workflow` calls it with `workflow_path=workflow_path` (the parameter, not `self.workflow_path`). Mutations to `ctx.stale_memo_skipped` and `ctx.stale_memo_uncheckable` already use the `workflow_path` parameter as a key (verified in the existing implementation at lines 320 and 323) — no change needed.

### Phase 4 verification gate

```bash
cd .taskmaster/tasks/task_159/baseline && bash verify.sh
make test
make check

wc -l src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py  # Expected: ~910 (down from ~1,070 after Phase 3)
wc -l src/pflow/core/prompt_cache_analysis/context.py  # Expected: ~420
grep -n "def _resolve_value_in_workflow_" src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py  # Expected: zero hits
grep -n "def _trace_node_output_for" src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py  # Expected: zero hits

# Test migration verification (impact-completeness C1):
grep -n "_resolve_value_in_workflow_memo" tests/test_core/test_cache_analysis_analyze.py  # Expected: zero hits
# The lines 830 and 849 must now call ctx.resolve_ref_value_in_workflow(...)

# Threading invariant verification (plan-review W7):
# Run a focused test that exercises the parametric memo resolution path
# and verifies stale_memo_skipped accumulators contain keys scoped to the
# PASSED workflow_path, not ctx.workflow_path. Recommend running:
uv run pytest tests/test_core/test_cache_analysis_analyze.py -k "stale_memo or memo_freshness" -v
```

### Commit message

```
Phase 4: parametrize AnalysisContext on workflow_path

G4.1: AnalysisContext.resolve_ref_value_in_workflow(ref, *, workflow_path)
exists. Workflow-path-parametric form of resolve_ref_value.

G4.2: AnalysisContext.resolve_ref_value_for_projection_in_workflow
extends the projection variant similarly.

G4.3: Six mirror helpers in stages/cross_workflow.py
(_resolve_value_in_workflow_memo/parameters/trace, _trace_node_output_for,
plus two domain-specific helpers that survive) collapse to delegation.
~158 LOC removed; the surviving domain-specific helpers
(_resolve_input_at_workflow_node_invocation, _resolve_child_suffix_in_value)
total ~30 LOC.

G4.4: Existing resolve_ref_value and resolve_ref_value_for_projection
methods preserved.

G4-memo: Stale-memo accumulators mutated correctly with passed
workflow_path keys. Threading verified — consumers use len() only.

Zero behavior change: baseline harness reports same 7 drifted
cases as pre-refactor.
```

---

## Phase 5 — Orchestrator inline-block extraction (G1.1-G1.4, ~1 hour)

**File modified:** `src/pflow/core/prompt_cache_analysis/analyze.py` only. No module moves yet.

### Steps

1. **G1.2 — Extract trace-misalignment recovery** (lines 229-272, 44 LOC). Create a new module-private function `_recompute_after_trace_misalignment` that takes the relevant inputs (`per_call_result`, `ctx`, `cw_result`, `lookup_path`, `used_trace_path`, `trace_data`, `notes`, `parameters`, `memo_cache`, `trace_outputs_by_key`, `base_path`, `edge_child_paths`, `predicted_cache_keys`, `prediction_fidelity_notes`) and returns `(new_per_call_result, new_ctx, new_used_trace_path)`. Replace the inline block in `analyze()` with one call.

2. **G1.3 — Add `PerCallRow.has_real_data` property + extract visibility notes:**

   a. In `types.py`, add to `PerCallRow`:
      ```python
      @property
      def has_real_data(self) -> bool:
          """Per-row visibility: True iff this row has substantive signal to display."""
          return (
              self.data_source in {"trace", "memo"}
              or bool(self.declared_prompt_cache)
              or self.model_is_heterogeneous
              or self.cached_now_tokens_estimated is not None
              or self.cache_ready.data_source not in {"not_applicable", "unavailable"}
              or self.cache_opportunity.data_source not in {"not_applicable", "unavailable"}
              or self.cacheable_data_source != "unavailable"
          )
      ```

   b. In `rendering/views.py`, **delete** `per_call_row_has_real_data` (lines 57-76).

   c. In `rendering/text.py`, **explicitly delete the wrapper `_row_has_real_data` at lines 2307-2310** (impact-completeness W5). The wrapper is called from `rendering/text.py:1633`. Replace the call site with `row.has_real_data` directly.

   d. In `analyze.py`, **delete** the import `from .rendering.views import per_call_row_has_real_data` (line 309). Replace the predicate at the call site with `row.has_real_data`.

   e. **Extract visibility notes block** (lines 305-321, 17 LOC) to a new private function `_append_per_call_visibility_notes(per_call_rows, per_call_result, notes)`. **Call this at the SAME pipeline position as the old inline block** — after `_populate_suggested_blocks`, before `_emit_padding_advisories`. Note ordering is observable in `--json` output (feature-interactions W6).

   f. **Stale docstring references** (impact-completeness W4): `tests/test_core/test_cache_analysis_analyze.py:4520` and `tests/test_core/test_cache_analysis_renderers.py:4660` reference `_row_has_real_data` in docstring/comment prose. After deletion, optionally update these docstrings to reference `row.has_real_data` (cosmetic; not a test breakage).

3. **G1.4 — Push summary enrichment into `_build_summary`:**

   **CRITICAL ORDERING CONSTRAINT** (feature-interactions C1): the truncated-trace filter at `analyze.py:378-384` (`if _trace_coverage_for_rows(...)[0] == "truncated": warnings = _filter_trace_dependent_warnings(warnings); suggested_blocks = []`) **MUST continue to run BEFORE `_build_summary`**. `_build_summary` derives counts (`blocking_errors`, `warnings_count`, `info_count`, `actionable_opportunities`) from the (post-filter) `warnings` list. **Do NOT relocate `_filter_trace_dependent_warnings` into `_build_summary`** — that would re-run the filter after summary construction, producing wrong counts. The filter and its `suggested_blocks = []` reset stay in the orchestrator; only the summary enrichment kwargs move.


   a. In `stages/summary.py`, extend `_build_summary`'s signature with 4 new kwargs:
      - `trace_workflow_relationship: str | None = None`
      - `drift_count: int = 0`
      - `sub_workflow_rollup: SubWorkflowRollup | None = None`
      - `suggested_run_command: str | None = None`

   b. Pass these into the `AnalysisSummary(...)` constructor at the end of `_build_summary` (lines 285-344), replacing the corresponding entries. Currently those fields are set via an outer `replace(summary, ...)` in `analyze.py:411-429`.

   c. In `analyze.py`, **delete** the `replace(summary, ...)` block (lines 411-429). Instead pass the 4 values as kwargs to the existing `_build_summary(...)` call at lines 401-410:
      ```python
      summary = _build_summary(
          per_call_rows,
          warnings,
          ttl=_extract_cache_ttl(cache_block),
          ctx=ctx,
          edge_child_paths=edge_child_paths,
          ir_default_model=ir_default_model,
          scope_workflow_paths=scope_workflow_paths,
          trace_index=trace_index,
          trace_workflow_relationship=_derive_trace_workflow_relationship(...),
          drift_count=drift_count,
          sub_workflow_rollup=_build_sub_workflow_rollup(...),
          suggested_run_command=_format_workflow_run_command(...),
      )
      ```

### Phase 5 verification gate

```bash
cd .taskmaster/tasks/task_159/baseline && bash verify.sh
make test
make check

wc -l src/pflow/core/prompt_cache_analysis/analyze.py  # Expected: ~1,015 (down from ~1,095)
grep -n "from .rendering.views" src/pflow/core/prompt_cache_analysis/analyze.py  # Expected: zero hits
grep -rn "def per_call_row_has_real_data" src/pflow/core/prompt_cache_analysis/  # Expected: zero hits
grep -n "def _row_has_real_data" src/pflow/core/prompt_cache_analysis/rendering/text.py  # Expected: zero hits (impact W5)
grep -n "replace(summary" src/pflow/core/prompt_cache_analysis/analyze.py  # Expected: zero hits

# has_real_data parity check (plan-review W6): verify the @property returns
# identical values on legacy-shaped rows BEFORE and AFTER Phase 7 (the bridge
# still synthesizes projections at Phase 5; the property must work both ways).
# This is a smoke test — run one workflow that hits the per-call hidden note
# (e.g. tests/test_core/test_cache_analysis_renderers.py::test_per_call_hidden_when_no_run_data)
uv run pytest tests/test_core/test_cache_analysis_renderers.py::test_per_call_hidden_when_no_run_data -v
```

### Commit message

```
Phase 5: orchestrator inline-block extraction

G1.2: Trace-misalignment recovery (44 LOC inline) extracted to
_recompute_after_trace_misalignment().

G1.3: PerCallRow.has_real_data @property added in types.py. The
free function per_call_row_has_real_data in rendering/views.py
removed; both analyzer and renderer call row.has_real_data
directly. Visibility-notes block (17 LOC inline) extracted to
_append_per_call_visibility_notes().

G1.4: Summary enrichment pushed into _build_summary kwargs. The
outer replace(summary, ...) block (19 LOC) in analyze() is gone;
summary stage owns all summary fields.

analyze.py: 1,095 → ~1,015 LOC.

Zero behavior change: baseline harness reports same 7 drifted
cases as pre-refactor.
```

---

## Phase 6 — Helper relocations + cycle inversion (G1.5-G1.6, ~3 hours)

**Files modified:**
- `src/pflow/core/prompt_cache_analysis/analyze.py` (-600 LOC of helpers, drops to ~250-350 LOC)
- `src/pflow/core/prompt_cache_analysis/sub_workflow_walker.py` (+144 LOC — parameter resolution cluster)
- `src/pflow/core/prompt_cache_analysis/stages/row_builder.py` (+100 LOC — row-assembly orchestration)
- `src/pflow/core/prompt_cache_analysis/trace_loading.py` (+98 LOC — drift detection + call counts)
- `src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py` (+247 LOC — `_RowCrossWorkflowCandidate` + 4 producers)

### Cycle inversion plan (G1.6)

**Verified safe** by the pre-flight check. After moving `_RowCrossWorkflowCandidate` and its 4 producers into `stages/cross_workflow.py`:
- The 6 lazy `from .stages.cross_workflow import ...` blocks inside `analyze.py:871, 946` are no longer needed — those helpers and the producers are now in the same file.
- One new top-level import is needed at the top of `stages/cross_workflow.py`: `from pflow.core.llm_config import get_default_workflow_model` (external to the analyzer package; no back-edge).

### Steps

1. **G1.5a — Move parameter-resolution cluster to `sub_workflow_walker.py`** (144 LOC). The cluster is structural processing of walker output — it belongs with the walker.
   - From `analyze.py`:
     - `_build_parameters_by_workflow` (lines 568-615)
     - `_resolve_child_input_value` (lines 618-649)
     - `_unchecked_parent_memo_roots` (lines 652-670)
     - `_resolve_first_batch_item` (lines 673-704)
     - `_resolve_first_trace_batch_item` (lines 707-719)
   - Add them to `sub_workflow_walker.py` after the existing walker code (after line 447).
   - **Update test imports** (impact-completeness C2 expanded the original count):
     - `tests/test_core/test_cache_analysis_analyze.py:5669, 5704, 5727, 5752` — 4 sites of `_resolve_child_input_value`
     - `tests/test_core/test_cache_analysis_analyze.py:5782, 5818, 6548` — 3 sites of `_build_parameters_by_workflow` (NOT 4 as previously claimed)
     - **`tests/test_core/test_cache_analysis_per_id_emission.py:5378`** — 1 additional site of `_build_parameters_by_workflow` (impact-completeness C2 — was missed in earlier plan revision)
   - Re-point all 8 sites from `pflow.core.prompt_cache_analysis.analyze` to `pflow.core.prompt_cache_analysis.sub_workflow_walker`.

2. **G1.5b — Move row-assembly orchestration to `stages/row_builder.py`** (100 LOC).
   - From `analyze.py`:
     - `_build_per_call_rows_and_warnings` (lines 722-801) — including the `_PerCallRowsResult` dataclass at lines 108-114
     - `_detect_candidate_subsets` (lines 1007-1026)
     - `_extract_declared_chunks` (lines 459-466) — used by both `_build_per_call_rows_and_warnings` and `analyze()`. Keep a copy in both files, or move to types.py. **Decision: move to a helper in `stages/row_builder.py` and have `analyze.py` import it back.** One-way dependency: row_builder is downstream of analyze for this helper.

3. **G1.5c — Move trace integration to `trace_loading.py`** (98 LOC).
   - From `analyze.py`:
     - `_row_model_drift` (lines 469-495)
     - `_detect_per_node_model_drift` (lines 498-541)
     - `_build_call_counts_by_node` (lines 804-817)

4. **G1.5d — Move cross-workflow row-level candidates** (247 LOC). This step has TWO destinations to avoid a cycle (plan-review C3 — earlier wording was contradictory):

   **`_RowCrossWorkflowCandidate` dataclass → `types.py`** (NOT `stages/cross_workflow.py`).
   - The dataclass is referenced by both `_PerCallRowsResult.cross_workflow_candidates_by_row` (which lives in `stages/row_builder.py` after G1.5b) and by the producer functions (which live in `stages/cross_workflow.py` after the rest of G1.5d). If the dataclass lived in `stages/cross_workflow.py`, `stages/row_builder.py` would import from `stages/cross_workflow.py`, AND `stages/cross_workflow.py` already imports from `stages/row_builder.py` (`_node_inputs`, `_static_excerpt`, `_total_observed_invocations`) — that's a cycle.
   - Putting `_RowCrossWorkflowCandidate` in `types.py` (with underscore prefix, package-internal) means both files import the type from `types.py`. No cycle.

   **The 4 producer functions → `stages/cross_workflow.py`**:
   - `_build_cross_workflow_candidates_by_row` (currently at analyze.py:837-859)
   - `_row_cross_workflow_candidates_for_edge` (analyze.py:862-941)
   - `_has_structural_cross_workflow_projection_candidate` (analyze.py:944-971)
   - `_resolved_models_for_child` (analyze.py:974-1004)
   - These four functions reference `_RowCrossWorkflowCandidate` — add `from ..types import _RowCrossWorkflowCandidate` at the top of `stages/cross_workflow.py`.

   **Other lazy-import cleanup**:
   - The 6 helpers `_row_cross_workflow_candidates_for_edge` lazy-imports at line 871 (`_append_child_suffix`, `_cache_ref_is_declared_or_covered`, `_child_cache_ref_consumers`, `_estimate_parent_value_tokens`, `_items_by_name`, `_parent_prose_for_cache_ref`) all live in `stages/cross_workflow.py` already — after the producer move they become same-file references. **Delete the lazy import block at line 871.**
   - The 3 helpers `_has_structural_cross_workflow_projection_candidate` lazy-imports at line 946 (`_cache_ref_is_declared_or_covered`, `_child_cache_ref_consumers`, `_items_by_name`) — same story; delete the lazy import block.

   **Add top-level imports** to `stages/cross_workflow.py`:
   - `from pflow.core.llm_config import get_default_workflow_model` (used by `_resolved_models_for_child`)
   - `from ..types import _RowCrossWorkflowCandidate`

   **Transitive verification**: after the move, run a one-line import check before committing:
   ```bash
   uv run python -c "import pflow.core.prompt_cache_analysis; print('ok')"
   ```
   Catches cycle errors at the moment they would occur, not at `verify.sh` time. If this raises ImportError, the cycle resolution above was incomplete — back out the changes and re-verify the import graph.

5. **G1.5e — `_run_full_validation` (lines 1034-1090)**: stays in `analyze.py`. Single call site; orchestration concern (delegates to the unified validator). 57 LOC kept in the orchestrator.

6. **Update lazy imports**: delete the lazy `from .stages.cross_workflow import ...` blocks inside `_row_cross_workflow_candidates_for_edge` (line 871) and `_has_structural_cross_workflow_projection_candidate` (line 946). Add top-level imports in `stages/cross_workflow.py` after the move.

7. **Update analyze.py imports**: remove imports for moved helpers; add imports back where needed (e.g., `from .sub_workflow_walker import _build_parameters_by_workflow` if `analyze()` still calls it at lines 189, 243). Verify the body of `analyze()` reads as a clean 7-step sequence:
   ```
   analyze()
     1. Build context + resolve trace scope (trace_loading)
     2. Walk sub-workflows (sub_workflow_walker.walk_cross_workflow)
     3. Predict cache keys (stages.discrepancy._attach_predicted_cache_keys)
     4. Build per-call rows (stages.row_builder._build_per_call_rows_and_warnings)
        - includes the trace-misalignment recovery call from Phase 5
     5. Emit stage findings (warnings, suggestions, fragmentation, partial decls, cross-workflow, discrepancy)
     6. Build summary (stages.summary._build_summary with all kwargs)
     7. Return CacheAnalysis
   ```

### Phase 6 verification gate

```bash
cd .taskmaster/tasks/task_159/baseline && bash verify.sh
make test
make check

# Critical: ensure tests that import from analyze.py for the moved helpers
# now import from their new homes (the harness will fail if any test still
# imports e.g. _build_parameters_by_workflow from analyze instead of
# sub_workflow_walker).
grep -rn "from pflow.core.prompt_cache_analysis.analyze import _" tests/ --include="*.py"
# Expected: ZERO hits if all moved helpers are correctly re-pointed.

wc -l src/pflow/core/prompt_cache_analysis/analyze.py  # Expected: ≤ 400 (realistic — plan-review S5)
# The orchestrator body (~250 LOC after Phase 5 extractions), `_run_full_validation`
# (~57 LOC, stays), `_cache_ttl_by_workflow` (~22 LOC, stays unless moved to
# trace_loading.py), `_extract_declared_chunks` (moved to row_builder per W1),
# plus imports (~50 LOC) totals ~380 LOC. Set the gate at 400.
grep -rn "from .stages.cross_workflow import" src/pflow/core/prompt_cache_analysis/analyze.py
# Expected: lazy imports gone — only the top-level import on line ~54 remains

# Transitive import check (cycle safety):
uv run python -c "import pflow.core.prompt_cache_analysis; print('ok')"
# Expected: prints 'ok'. ImportError indicates a cycle the cycle inversion missed.
```

### Commit message

```
Phase 6: orchestrator helper relocations + cycle inversion

G1.5a: Parameter resolution cluster (5 helpers, 144 LOC) moved
from analyze.py to sub_workflow_walker.py. These are structural
processing of walker output and belong with the walker.

G1.5b: Row-assembly orchestration (_build_per_call_rows_and_warnings,
_detect_candidate_subsets, _extract_declared_chunks; ~100 LOC + the
_PerCallRowsResult dataclass) moved to stages/row_builder.py.

G1.5c: Drift detection + call counts (3 helpers, 98 LOC) moved to
trace_loading.py — drift is fundamentally a trace-vs-IR comparison.

G1.5d: Cross-workflow row-level candidates (_RowCrossWorkflowCandidate
+ 4 producers, 247 LOC) moved to stages/cross_workflow.py. The
dataclass _RowCrossWorkflowCandidate lives in types.py to break the
potential cycle with row_builder.

G1.6: Lazy import workarounds for inverted cycles disappear with
their causes. The 6 lazy `from .stages.cross_workflow import ...`
blocks inside helper bodies are gone — those helpers are now
in-file references.

_run_full_validation stays in analyze.py as orchestration glue
(single call site, delegates to the unified validator).

analyze.py: ~1,015 → ~350 LOC.

Zero behavior change: baseline harness reports same 7 drifted
cases as pre-refactor.
```

---

## Phase 7 — PerCallRow bridge removal (G2, ~8-12 hours)

The largest single phase. ~100 test sites migrate before the bridge can be deleted. **Risk-revised by test-fidelity reviewer: 30-50 of the 77 renderer sites need explicit `CacheProjection` instances (not "10-20%"). Use incremental rollout per file, not big-bang sed.**

**Files modified:**
- New: `tests/shared/cache_analysis_fixtures.py` (~80 LOC) — shared `make_per_call_row` helper + parity guard test
- `src/pflow/core/prompt_cache_analysis/types.py` (reduce `__post_init__` body — see step 6 for exact preserved derivations; -70 LOC)
- `src/pflow/core/prompt_cache_analysis/stages/row_builder.py` (delete `_apply_cross_workflow_projection`, `_clamp_legacy_cacheable_projection`; -76 LOC)
- `tests/test_core/test_cache_analysis_renderers.py` (~77 sites migrated — 30-50 require explicit projections, NOT a sed job)
- `tests/test_core/test_cache_analysis_analyze.py` (~14 sites migrated)
- `tests/test_core/test_cache_analysis_cost_estimation.py` (~9 sites migrated)
- **4 per-file factory helpers** delegate to the shared helper (test-fidelity W1 corrected the original "5" — `_make_summary_row` at `cost_estimation.py:3789` does NOT exist; verified file is 1,178 lines):
  - `tests/test_core/test_cache_analysis_renderers.py:1132` — `_row(node_path, ratio)`
  - `tests/test_core/test_cache_analysis_analyze.py:117` — `_row(source)`
  - `tests/test_core/test_cache_analysis_cost_estimation.py:49` — `_row(*, ...)` — NOTE: signature uses `input_tokens`, `cacheable_tokens`, `batch_size` (without `_estimated` suffix). The wrapper needs explicit kwarg translation, NOT `**kwargs` passthrough (test-fidelity W2).
  - `tests/test_core/test_cache_analysis_cost_estimation.py:903` — `_row_with_cost(...)`

### Steps

1. **Create the shared test fixture helper** in `tests/shared/cache_analysis_fixtures.py`:
   ```python
   """Shared PerCallRow construction helpers for cache-analysis tests."""
   from __future__ import annotations

   from typing import Any

   from pflow.core.prompt_cache_analysis.types import (
       CacheProjection,
       CrossWorkflowInputContribution,
       PerCallRow,
       not_applicable_projection,
       unavailable_projection,
   )


   def make_per_call_row(
       *,
       node_path: str = "node",
       model: str = "anthropic/claude-sonnet-4-5",
       is_batch: bool = False,
       batch_size_estimated: int | None = None,
       input_tokens_estimated: int = 100,
       cacheable_tokens_estimated: int | None = None,
       cache_ratio_pct: int | None = None,
       data_source: str = "memo",
       declared_prompt_cache: list[str] | None = None,
       cacheable_data_source: str = "unavailable",
       workflow_path: str | None = None,
       cache_configured: CacheProjection | None = None,
       cache_active: CacheProjection | None = None,
       cache_ready: CacheProjection | None = None,
       cache_opportunity: CacheProjection | None = None,
       cached_now_tokens_estimated: int | None = None,
       **kwargs: Any,
   ) -> PerCallRow:
       """Build a PerCallRow in the projection-object shape.

       Replaces ad-hoc PerCallRow(cacheable_tokens_estimated=...) constructors
       that previously relied on __post_init__ to synthesize projection
       fields from the legacy scalar.

       **WARNING for assertion-on-cell tests**: if your test asserts on
       `cached["ready"]`, `cached["upside"]`, `cached["cached_now"]`,
       or `cached["ratio"]` in `render_text()` output, you MUST pass
       explicit `CacheProjection` instances. The helper's
       `not_applicable_projection()` default causes the renderer to display
       "—" regardless of `cacheable_tokens_estimated`. The bridge previously
       synthesized projections from the legacy scalar; that synthesis is gone.

       Example for a "trace + declared" row that needs the renderer to show
       a real `ready` value:
           make_per_call_row(
               node_path="x", model="anthropic/claude-sonnet-4-5",
               input_tokens_estimated=10000, cacheable_tokens_estimated=7500,
               declared_prompt_cache=["prefix"], cacheable_data_source="trace",
               data_source="trace",
               cache_ready=CacheProjection(
                   tokens_estimated=7500, data_source="trace", ratio_pct=75,
                   confidence="observed", ...),
               cached_now_tokens_estimated=7500,
           )

       The four projection fields default to not_applicable; pass explicit
       CacheProjection instances when tests need specific projection state.
       """
       return PerCallRow(
           node_path=node_path,
           model=model,
           is_batch=is_batch,
           batch_size_estimated=batch_size_estimated,
           input_tokens_estimated=input_tokens_estimated,
           cacheable_tokens_estimated=cacheable_tokens_estimated,
           cache_ratio_pct=cache_ratio_pct,
           data_source=data_source,
           declared_prompt_cache=declared_prompt_cache,
           cacheable_data_source=cacheable_data_source,
           workflow_path=workflow_path,
           cache_configured=cache_configured or not_applicable_projection(),
           cache_active=cache_active or not_applicable_projection(),
           cache_ready=cache_ready or not_applicable_projection(),
           cache_opportunity=cache_opportunity or not_applicable_projection(),
           cached_now_tokens_estimated=cached_now_tokens_estimated,
           **kwargs,
       )
   ```

   **ALSO add a parity guard test** (test-fidelity S1, mirroring Pitfall #19 defense pattern — see `tests/CLAUDE.md`). Place in `tests/test_core/test_cache_analysis_renderers.py` near the existing `TestMakeAnalysisShapeParity`:
   ```python
   class TestMakePerCallRowProductionParity:
       """Helper-vs-production shape parity (Pitfall #19 defense)."""

       def test_helper_shape_matches_production_builder(self):
           # Build a production row via stages/row_builder._build_per_call_row
           # with a representative IR + ctx. Build a helper row via
           # make_per_call_row with equivalent inputs and explicit projections.
           # Assert which fields are populated (data_source string per
           # projection field) match. Drift here = silent helper degradation.
           ...
   ```
   Implementer fills in the body using a minimal IR (one LLM node, no declared cache) and confirms `production_row.cache_ready.data_source == helper_row.cache_ready.data_source`, etc. Without this guard, the helper can drift from production reality without any test signal.

   The helper does NOT auto-synthesize projections from legacy scalars — that's the bridge's behavior being removed. Tests that need specific projection state pass explicit `CacheProjection` instances.

2. **Migrate the 5 per-file `_row()` factory helpers** to delegate to `make_per_call_row`. They become 5-line wrappers:
   - `tests/test_core/test_cache_analysis_analyze.py:117-128` — `_row(source: str)` becomes a thin wrapper around `make_per_call_row(data_source=source, ...)`.
   - `tests/test_core/test_cache_analysis_cost_estimation.py:49-69` — `_row(*, ...)` delegates with explicit kwargs.
   - `tests/test_core/test_cache_analysis_cost_estimation.py:903-927` — `_row_with_cost(...)` delegates.
   - `tests/test_core/test_cache_analysis_cost_estimation.py:3789-3809` — `_make_summary_row(...)` delegates.
   - `tests/test_core/test_cache_analysis_renderers.py:1132-1158` — `_row(node_path, ratio)` delegates.

3. **Migrate inline direct constructions** in `test_cache_analysis_renderers.py` (~77 sites) and `test_cache_analysis_analyze.py` (~14 sites) — anywhere `PerCallRow(node_path=..., cacheable_tokens_estimated=N, ...)` appears directly. Two strategies:
   - **Strategy A (preferred)**: replace `PerCallRow(...)` with `make_per_call_row(...)`. Simple sed-based migration after the helper is named.
   - **Strategy B (where projections matter)**: for tests that depend on the bridge's synthesis behavior (e.g., asserting that `cache_ready` has a populated `data_source`), the test must explicitly construct the right `CacheProjection` and pass it. These are the ~10-20% of test sites that fail loudly after the bridge is deleted.

4. **Migrate `**{**row.__dict__, "override": ...}` spread patterns** to `dataclasses.replace(row, **overrides)`. The spread pattern relies on `__post_init__` to re-synthesize projections from updated legacy scalars; `dataclasses.replace` preserves the projection fields. Existing examples at `test_cache_analysis_renderers.py:1904` and `:4586` already use `dataclasses.replace`.

5. **Incremental rollout — per-file commit cycle** (test-fidelity W4, revised from big-bang approach):

   Migrate ONE test file at a time. The bridge stays in place during steps 1-4 (helper exists, factory helpers delegate, inline sites migrated). After migrating each test file individually:
   - Run `uv run pytest tests/test_core/test_cache_analysis_<file>.py -v`
   - Confirm all tests pass with the bridge STILL IN PLACE (the bridge is forgiving — it synthesizes projections for any test still passing the legacy scalar).
   - Commit (`Phase 7 — migrate test_cache_analysis_<file>.py`).

   Then proceed to step 6 (delete the bridge in one final commit) only AFTER all 3 test files are migrated.

   **Identify at-risk sites BEFORE migration begins** (test-fidelity C1, S2):
   ```bash
   # Find every PerCallRow construction in tests that uses spread-with-dict + override pattern
   # (these are highest-risk because the spread relies on __post_init__ to re-synthesize)
   grep -rn '\*\*{\*\*_row(\|\*\*{\*\*[a-z_]*\.\(_\)\?_dict__' tests/test_core/test_cache_analysis_renderers.py | wc -l
   # Plan-review estimate: ~50 spread sites in test_cache_analysis_renderers.py

   # Find every test that asserts on the rendered ready/upside/cached_now/ratio cells
   # (these are the ones that MUST receive explicit CacheProjection instances)
   grep -rn 'cached\["\(ready\|upside\|cached_now\|ratio\)"\]\s*==' tests/test_core/test_cache_analysis_renderers.py
   # Each match is a candidate for "Strategy B" explicit projection construction.
   ```

   The 30-50 at-risk sites among the 77 inline constructions are the ones touching these renderer cells. Migrate them with explicit `CacheProjection` instances (see the docstring example in step 1). Sites that only assert on the warning IDs, the recommended actions, or model/input columns are safe with `not_applicable_projection()` defaults.

6. **Delete the bridge** in `types.py`. Replace `__post_init__` (lines 403-485) with the **two preserved derivation branches** (test-fidelity W5 — the original plan dropped the line 463 derivation):
   ```python
   def __post_init__(self) -> None:
       """Derive cached_now_tokens_estimated from available evidence.

       The legacy-cacheable-scalar bridge (lines 419-485 of the pre-Phase-7
       __post_init__) has been removed; tests now construct rows in the
       projection-object shape via tests/shared/cache_analysis_fixtures.make_per_call_row.

       Two derivation branches are preserved because they are reached in
       production via stages/row_builder._build_per_call_row:

       Branch A (from pre-refactor lines 411-418): trace cache token splits.
       When `cached_now_tokens_estimated` was not provided and the trace
       reported `cache_creation_input_tokens` or `cache_read_input_tokens`,
       derive cached_now as their sum. Reached on EVERY trace-backed row.

       Branch B (from pre-refactor lines 458-463): trace + declared bridge.
       When `cacheable_data_source == "trace"` AND `declared_prompt_cache` is
       set AND `cached_now_tokens_estimated` is None, fall back to
       `cacheable_tokens_estimated`. This handles the case where the trace
       reported zero cache tokens but the legacy scalar carries the trace
       observation. Reached on declared-cache rows with trace data.

       Without Branch B preserved, tests asserting on `cached["cached_now"]`
       for declared-cache+trace rows would render "—" instead of the
       expected token count.
       """
       # Branch A — trace cache token splits sum
       if self.cached_now_tokens_estimated is None and (
           self.cache_creation_input_tokens is not None
           or self.cache_read_input_tokens is not None
       ):
           object.__setattr__(
               self,
               "cached_now_tokens_estimated",
               int(self.cache_creation_input_tokens or 0) + int(self.cache_read_input_tokens or 0),
           )

       # Branch B — trace + declared cache fallback
       if (
           self.cached_now_tokens_estimated is None
           and self.cacheable_data_source == "trace"
           and self.declared_prompt_cache
           and self.cacheable_tokens_estimated is not None
       ):
           object.__setattr__(
               self,
               "cached_now_tokens_estimated",
               self.cacheable_tokens_estimated,
           )
   ```

7. **Delete `_apply_cross_workflow_projection`** at `stages/row_builder.py:321-366` (46 LOC). Its call site at `stages/row_builder.py:223-230` becomes:
   ```python
   cross_workflow_inputs: tuple[CrossWorkflowInputContribution, ...] = ()
   # _apply_cross_workflow_projection removed (Phase 7): legacy scalar
   # cacheable_tokens_estimated is no longer driven from cross-workflow
   # candidates. cross_workflow_components below (built by
   # _cross_workflow_projection_components) feeds the projection objects.
   ```
   Verify that `cross_workflow_inputs` is populated from `cross_workflow_component_inputs` later in the function (it already is — line 285-286).

8. **Delete `_clamp_legacy_cacheable_projection`** at `stages/row_builder.py:369-398` (30 LOC). Its caller at `stages/row_builder.py:232-240` becomes:
   ```python
   # cacheable_with_clamp and ratio derivation removed (Phase 7).
   # PerCallRow.cacheable_tokens_estimated now receives the raw
   # cacheable_tokens value without legacy clamping; the new
   # projection objects do their own capping via _cap_projection_tokens.
   ```
   The `PerCallRow(...)` construction at line 288 changes:
   - `cacheable_tokens_estimated=cacheable_with_clamp` → `cacheable_tokens_estimated=cacheable_tokens`
   - `cache_ratio_pct=ratio` → `cache_ratio_pct=_safe_pct(cacheable_tokens, input_tokens) if cacheable_tokens else None`

   Or simpler: keep both fields populated identically to today (they're still part of the public contract), just via inline computation rather than via the deleted helper.

### Phase 7 verification gate

```bash
cd .taskmaster/tasks/task_159/baseline && bash verify.sh
make test
make check

wc -l src/pflow/core/prompt_cache_analysis/types.py  # Expected: ~810 (down from ~890 by ~80)
grep -rn "def _apply_cross_workflow_projection" src/  # Expected: zero hits
grep -rn "def _clamp_legacy_cacheable_projection" src/  # Expected: zero hits

# Verify test count is unchanged (no tests dropped):
make test 2>&1 | tail -1   # Compare to Phase 0 baseline (and to /tmp/baseline-collected-tests.log)
diff <(uv run pytest --collect-only -q | sort) <(sort /tmp/baseline-collected-tests.log) | head -20
# Expected: empty diff (no test gained/lost). If any line differs, a test was renamed/added/removed by the migration.

# Verify cacheable_data_source = "cross_workflow_projection" is still emitted by production
# (feature-int W2): after deleting _apply_cross_workflow_projection, the projection-component
# path (`_cross_workflow_projection_components` at row_builder.py:410-453) must still set
# this label. Otherwise PerCallRow.has_real_data silently returns False for cross-workflow
# projection rows and the per-call section hides them.
grep -n '"cross_workflow_projection"' src/pflow/core/prompt_cache_analysis/stages/row_builder.py
# Expected: at least 2 hits (data_source kwarg + at least one comparison/derivation)
```

### Commit message

```
Phase 7: PerCallRow legacy bridge removal

G2.1: Created tests/shared/cache_analysis_fixtures.make_per_call_row
as the canonical PerCallRow constructor for tests. Migrated 5
per-file _row() factory helpers + ~100 inline construction sites
across test_cache_analysis_{renderers,analyze,cost_estimation}.py
to the new shape.

G2.2: PerCallRow.__post_init__ shrinks to ~10 LOC — only the
cached_now_tokens_estimated derivation. The 75-LOC legacy
synthesis from cacheable_tokens_estimated scalar is gone.

G2.3: _apply_cross_workflow_projection (46 LOC) deleted from
stages/row_builder.py. Production rows are constructed only via
_cross_workflow_projection_components.

G2.4: _clamp_legacy_cacheable_projection (30 LOC) deleted. Token
capping lives only in _cap_projection_tokens.

Net: ~158 LOC of bridge code removed across types.py and
stages/row_builder.py. The package's claimed type contract finally
matches its implementation.

Zero behavior change: baseline harness reports same 7 drifted
cases as pre-refactor.
```

---

## Phase 8 — Documentation (G7 + cross-cutting, ~1 hour)

### Steps

1. **Create `src/pflow/core/prompt_cache_analysis/stages/discrepancy/CLAUDE.md`** with a "Test API" section listing the 4 symbols documented as stable test surfaces (G7.1):
   ```markdown
   # Cache-Key Discrepancy Stage

   Predicts memo cache_keys for each LLM node and compares against trace
   evidence. The seam between predict and diagnose is one call returning
   `(workflow_path, node_id) → cache_key | _PREDICTION_SKIPPED`.

   ## Files

   - `predict.py` — cache-key prediction using runtime substrate
     (compile_workflow, plan_node, create_planner_shared). Imports stay lazy
     (Task 160 DD#13) to save ~700ms of LiteLLM startup on dry-run paths.
   - `diagnose.py` — trace discrepancy diagnosis. Emits `cache.discrepancy`
     with `chunk_skipped` / `key_mismatch` root cause attribution.

   ## Test API

   These private (underscore-prefixed) symbols are documented as stable
   test surfaces. Tests may import them directly:

   - `predict._predict_node_cache_key` — explicitly documented at the
     function's docstring as "kept for direct test callers that want a
     single-node prediction without setting up a cw_result /
     AnalysisContext." Production callers should use `_predict_cache_keys`.
   - `predict._format_dynamic_batches_note` — encodes the exact user-facing
     prose for dynamic-batches Notes section. Tests pin exact strings.
   - `predict._format_fidelity_skip_note` — single SSoT for cache fidelity
     skip notes. Tests assert on string shape.
   - `predict._format_skipped_workflows_note` — aggregated per-sub-workflow
     skip notes (Task 159 L-4).

   Other discrepancy internals (`_pad_inputs_for_prediction`,
   `_node_references_any`, `_build_predict_scaffold`,
   `_dummied_cache_chunks`) are surgical branch-logic tests with no
   observable shape via `analyze()` alone. They are implicit-contract test
   surfaces — not promoted to public, but their direct test imports are
   acknowledged as load-bearing.
   ```

2. **Update `src/pflow/core/prompt_cache_analysis/CLAUDE.md`:**
   - Section "Module Structure" → update tree to reflect renames:
     - `cross_workflow.py` → `sub_workflow_walker.py` (the walker)
     - Add `rendering/cross_workflow_edits.py` (new file)
   - **Remove** the section "There are two `cross_workflow.py` files by design" (no longer applies — collision resolved).
   - "Pipeline" section: confirm the 7-step `analyze()` description still matches; update step 4 if needed.
   - "Types And Row Contract" section: update `PerCallRow.__post_init__` description (was "legacy bridge"; now "minimal cached_now derivation").
   - "Where To Add A New Feature" table: update row "Change sub-workflow walking semantics" to point to `sub_workflow_walker.py`.

3. **Update `src/pflow/core/CLAUDE.md`** if it references the package's structure (likely just a pointer; no detail).

4. **Verify all stale references are gone:**
   ```bash
   grep -rn "cache_analysis" --include="CLAUDE.md" .   # Old package name; should NOT appear except in retrospective/historical docs
   grep -rn "two cross_workflow.py" --include="*.md" .   # Should return only retrospective references
   grep -rn "_template_resolver" --include="CLAUDE.md" --include="*.md" .   # Update any docs that mention the duplicate
   ```

### Phase 8 verification gate

```bash
cd .taskmaster/tasks/task_159/baseline && bash verify.sh
make test
make check
```

Documentation phase introduces no code changes; harness expectation is unchanged from Phase 7.

### Commit message

```
Phase 8: documentation updates

G7.1: Created stages/discrepancy/CLAUDE.md with a "Test API"
section documenting _predict_node_cache_key and the three
_format_*_note helpers as stable test surfaces (per their
existing docstrings).

prompt_cache_analysis/CLAUDE.md updated:
- Module structure tree reflects sub_workflow_walker.py rename
  and the new rendering/cross_workflow_edits.py file.
- "Two cross_workflow.py files by design" disambiguation note
  removed (collision resolved).
- PerCallRow contract description updated to reflect bridge removal.
- "Where to add a new feature" table updated.

Zero behavior change.
```

---

## Phase 9 — Final verification + code review (~1 hour)

### Steps

1. **Full harness run:**
   ```bash
   cd .taskmaster/tasks/task_159/baseline && bash verify.sh 2>&1 | tee /tmp/baseline-post-refactor.log
   ```
   Diff the drift list against `/tmp/baseline-pre-refactor.log`. They must contain the same 7 case names.

2. **Full unit/quality gate:**
   ```bash
   make test
   make check
   make test-e2e 2>&1 | tail -5  # If applicable in this branch
   ```

3. **Success criteria verification** (from task spec Verification section):
   ```bash
   # Private-symbol leak count
   grep -rn "from pflow.core.prompt_cache_analysis.*import _" tests/ --include="*.py" | wc -l
   # Expected: ≤ 60 (down from 75 by at least 15, mainly from cost-helper renames)

   # Walker collision gone
   find src/pflow -name "cross_workflow.py"
   # Expected: ONE path (stages/cross_workflow.py only)

   # Template resolver duplication gone
   grep -rn "def _template_resolver" src/pflow/core/prompt_cache_analysis/
   # Expected: ZERO hits

   # Orchestrator size
   wc -l src/pflow/core/prompt_cache_analysis/analyze.py
   # Expected: ≤ 350

   # Cross-workflow stage size
   wc -l src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py
   # Expected: ≤ 1,070

   # Mirror cluster gone
   grep -n "def _resolve_value_in_workflow_" src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py
   # Expected: ZERO hits

   # Walker import resolves
   uv run python -c "from pflow.core.prompt_cache_analysis.sub_workflow_walker import walk_cross_workflow"
   # Expected: succeeds

   # Old walker import fails
   uv run python -c "from pflow.core.prompt_cache_analysis.cross_workflow import walk_cross_workflow" 2>&1 | grep ImportError
   # Expected: ImportError visible

   # Public API stable
   uv run python -c "from pflow.core.prompt_cache_analysis import analyze, render_text, render_json, summarize, summarize_from_analysis, CacheAnalysis, TraceListEntry, JSON_FORMAT_VERSION, list_traces_for_workflow"
   # Expected: succeeds
   ```

4. **No LiteLLM eager-import regression:**
   ```bash
   uv run python -c "import sys; import pflow.core.prompt_cache_analysis; print('litellm' in sys.modules)"
   # Expected: False
   ```

5. **Code review checkpoint** (plan-review S7): invoke the `/code-review` skill over the full diff before declaring the task complete. The 4 most relevant agents to deploy:
   - `review-impact-completeness` — verify every consumer of moved symbols was updated
   - `review-feature-interactions` — verify orchestrator thinning + helper relocation didn't break any stage interaction
   - `review-test-fidelity` — verify the Phase 7 migration didn't degrade test fidelity
   - `review-silent-failures` — verify no operation silently succeeds where it should fail

   Focus areas to call out in the agent prompts:
   - AnalysisContext mirror collapse correctness (Phase 4)
   - PerCallRow projection-shape consistency across the migrated tests (Phase 7)
   - Walker import-path uniformity (Phase 2)
   - `cacheable_data_source = "cross_workflow_projection"` still emitted by production after bridge removal

   Resolve confirmed findings before final commit.

6. **Final commit** (only if any cleanup needed; ideally Phase 8 was the last functional commit):
   ```
   Phase 9: final verification — task 160 complete

   All G1-G7 success criteria met. Task 159 baseline harness reports
   80 passed, 7 drifted — identical to pre-refactor (same 7 case names,
   attributable to PRs #390/#392/#396/#405/#412/#416/#418).

   Package metrics:
   - analyze.py: 1,095 → ~310 LOC
   - stages/cross_workflow.py: 1,344 → ~900 LOC
   - Net package LOC: ~16,300 → ~16,200 (roughly flat; redistribution)
   - _template_resolver duplicates: 4 → 0 (one canonical in context.py)
   - Test private-symbol imports: 75 → ~55
   - Files renamed: 2 (walker + its test)
   - New files: 2 (rendering/cross_workflow_edits.py, stages/discrepancy/CLAUDE.md)
   ```

---

## What NOT to do (preserved invariants)

These are verified non-issues — do not "fix" them during this refactor:

1. **Do not extract `projection_algebra.py` from `types.py`.** The algebra has one consumer path; "one adapter = hypothetical seam" — premature abstraction.

2. **Do not create `_ir_helpers.py`.** The 5 IR helpers (`_node_inputs`, `_batch_aliases`, `_cache_items`, `_cache_item_names`, `_is_batch_scoped_ref`) are heterogeneous and used heavily within their host file. Forced consolidation adds no value.

3. **Do not consolidate `core/cache_overlap.py`'s duplicates of `_batch_aliases` and `_is_batch_scoped_ref`.** They exist by design to keep the one-way `analyzer → data_flow` dependency. Consolidating would create a back-import.

4. **Do not hoist the lazy imports inside `stages/discrepancy/predict.py:468-470`** (compile_workflow, Registry, create_planner_shared, plan_node). They are policy — save ~700ms of LiteLLM startup on dry-run paths.

5. **Do not section-split `rendering/text.py`.** The 2,423-LOC file is cohesive (8 clean section renderers). Physical decomposition is navigability work, not depth work — separate concern, separate task.

6. **Do not promote private discrepancy substrate helpers to public.** They are intentionally a documented test surface (see Phase 8's discrepancy CLAUDE.md). Renaming them adds no value.

7. **Do not change behavior anywhere.** This refactor is structural only. If a test fails with a behavior difference (not an import error), STOP — that's a real regression, not a test fixture migration issue.

8. **Do not add new tests.** Existing tests validate the refactor; new tests would expand scope.

9. **Do not improve code while moving it.** Don't add docstrings, comments, type annotations, or "small cleanups" to functions you're relocating. Pure structural moves keep the diff readable.

10. **Do not regenerate the 7 pre-existing baseline drifts.** The 7 known-drift cases captured in Phase 0 are pre-existing staleness from feature PRs #390/#392/#396/#405/#412/#416/#418. Regenerating them under this refactor would mask whether the refactor itself caused drift. The "same 7 drifted cases as pre-refactor" gate is the contract; do NOT chase exit 0 by regenerating baselines. Baseline hygiene is a separate task (see Open follow-ups #4).

---

## Sub-agent prompt templates

When using subagents for mechanical work in any phase:

### Sed-based bulk replacement (preferred for deterministic substitutions)

```bash
# Always pipe through grep -rl first to limit blast radius:
grep -rl "<old_pattern>" src/ tests/ --include="*.py" \
  | xargs sed -i '' 's|<old_pattern>|<new_pattern>|g'

# Then verify zero hits remain:
grep -rn "<old_pattern>" src/ tests/ --include="*.py"
# Expected: zero
```

### code-implementer subagent (for transformations requiring judgment)

When a transformation needs judgment (e.g., choosing between two strategies for a test migration), use code-implementer with:
- One clear instruction per subagent
- Explicit file paths (always check after `git mv` whether subagent reads/writes to old paths — recreating deleted files is a known trap)
- The instruction "do not change any logic; this is a pure structural refactor"
- The verification command to run after the change

### test-writer-fixer subagent (for the Phase 7 test migration)

For the ~100-site PerCallRow test fixture migration, use test-writer-fixer with batched scope:
- One test file at a time (don't batch across files)
- The full signature of `make_per_call_row`
- The list of legacy-scalar inputs to translate
- The instruction "preserve test behavior — if any assertion changes, the migration is wrong"

---

## Open follow-ups (not in scope; future work)

These were noted during pre-flight verification but are out of scope for this refactor:

1. **`token_estimation.py:611-649` has another `workflow_path`-parametric resolution helper** (`_resolve_value_in_workflow_*`-style). After Phase 4, this could also delegate to `AnalysisContext.resolve_ref_value_in_workflow`, removing another ~40 LOC of mirror code. Defer to a separate task.

2. **Local variable rename in tests**: `cross_module` → `walker_module` (for consistency with the file rename). Cosmetic; non-blocking; defer.

3. **Task 160 spec doc updates** (`.taskmaster/tasks/task_160/` historical documents): the implementation-plan and progress-log reference the walker by old name. Defer — these are historical records, not load-bearing references.

4. **Regenerate the 7 pre-existing baseline drifts**. A clean-up task that takes 30 minutes; defer to a separate baseline-hygiene task. Tracked in retrospective.

5. **Section-split `rendering/text.py`** (navigability gain, not depth). Worth doing when someone next touches text.py.

---

## Critical files referenced in this plan

Production:
- `src/pflow/core/prompt_cache_analysis/__init__.py`
- `src/pflow/core/prompt_cache_analysis/analyze.py`
- `src/pflow/core/prompt_cache_analysis/types.py`
- `src/pflow/core/prompt_cache_analysis/context.py`
- `src/pflow/core/prompt_cache_analysis/cost_estimation.py`
- `src/pflow/core/prompt_cache_analysis/cross_workflow.py` → `sub_workflow_walker.py`
- `src/pflow/core/prompt_cache_analysis/trace_loading.py`
- `src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py`
- `src/pflow/core/prompt_cache_analysis/stages/row_builder.py`
- `src/pflow/core/prompt_cache_analysis/stages/suggestions.py`
- `src/pflow/core/prompt_cache_analysis/stages/warnings.py`
- `src/pflow/core/prompt_cache_analysis/stages/summary.py`
- `src/pflow/core/prompt_cache_analysis/stages/fragmentation.py`
- `src/pflow/core/prompt_cache_analysis/stages/partial_declarations.py`
- `src/pflow/core/prompt_cache_analysis/stages/discrepancy/predict.py`
- `src/pflow/core/prompt_cache_analysis/rendering/views.py`
- `src/pflow/core/prompt_cache_analysis/rendering/text.py`
- `src/pflow/core/markdown_parser.py` (one comment line)

Tests:
- `tests/test_core/test_cache_analysis_renderers.py`
- `tests/test_core/test_cache_analysis_analyze.py`
- `tests/test_core/test_cache_analysis_cost_estimation.py`
- `tests/test_core/test_cache_analysis_per_id_emission.py`
- `tests/test_core/test_cache_analysis_per_id_coverage.py`
- `tests/test_core/test_cache_analysis_cross_workflow.py` → `test_cache_analysis_sub_workflow_walker.py`
- `tests/test_core/test_sub_workflow_resolver.py`
- New: `tests/shared/cache_analysis_fixtures.py`

Documentation:
- `src/pflow/core/prompt_cache_analysis/CLAUDE.md`
- New: `src/pflow/core/prompt_cache_analysis/stages/discrepancy/CLAUDE.md`

Verification harness:
- `.taskmaster/tasks/task_159/baseline/verify.sh`
- `.taskmaster/tasks/task_159/baseline/run-case.sh`
- `.taskmaster/tasks/task_159/baseline/normalize.py`

---

## Final note for the implementing agent

This plan is sized to be completed by a single AI agent over multiple sessions, with each phase a discrete commit that passes the baseline harness independently. If you find an unexpected obstacle:

1. **STOP** at the current phase boundary. Don't push through.
2. **Re-verify the pre-flight invariants** (cycle safety, threading, harness usability) — they were verified at planning time but could have been invalidated by intervening commits.
3. **Read the surrounding code yourself** before delegating to subagents for mechanical work. The refactor skill is explicit: "Read the code yourself before dispatching implementers. One focused task per agent."
4. **Trust the harness over your intuition.** If `bash verify.sh` reports the same 7 drifted cases as pre-refactor, the work is correct regardless of what unit-test output suggests. Conversely, any NEW drift is a real regression.

The single most important property of this refactor: **each phase commit must independently pass the Task 159 baseline harness with no new drift.** That is the contract.
