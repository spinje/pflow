# Post-Plan-B Architectural Polish — Candidates 1 + 2 + 3

**Branch:** `refactor/cache-analysis-refactor`
**Verification gate at every phase:** `.taskmaster/tasks/task_159/baseline/verify.sh` — must report the same 7 drifted cases as pre-polish (80 passed, 7 drifted, 0 harness errors).
**Source documents:** `.taskmaster/tasks/task_160/implementation/retrospective-and-future-improvements.md`, `.taskmaster/tasks/task_160/implementation/progress-log-b.md`, the architecture-review HTML at `/var/folders/2f/n1_2xwj17z36v7758t4zx6900000gn/T/architecture-review-20260526-210233.html`.

---

## Context

Task 160 Plan B (9 phases, committed in `99382f1c…a4429734`) closed 6 of the 8 architectural insights from the post-implementation retrospective. The package is in a healthy shape:

| Metric | Before Plan B | After Plan B | Target |
|---|---:|---:|---:|
| `analyze.py` | 1,095 LOC | 539 LOC | ≤350 (close enough; the residual is well-justified orchestration) |
| `stages/cross_workflow.py` | 1,344 LOC | 971 LOC | ≤1,070 ✓ |
| `_template_resolver` duplicates | 4 | 0 ✓ | 0 |
| `cross_workflow.py` filename collision | 2 files | 1 file ✓ | 1 |
| `PerCallRow.__post_init__` bridge | ~158 LOC | ~20 LOC ✓ | minimal |
| Test private-symbol imports | ~75 | **63** | ≤60 (just over) |

Three concrete frictions remain. They are the high-leverage, low-risk polish that closes Plan B's residual gaps:

1. **12 of the 63 remaining private-symbol test imports cluster on three rendering helpers.** Five sites of `_render_summary`, five of `_format_delta_parenthetical`, two of `_format_cost`. The first five want the `## Summary` section as a string; the public `render_text(analysis)` returns the full report and forces the underscore import. The other seven sites unit-test pure leaf formatters that genuinely belong as documented substrate (mirror the `stages/discrepancy/CLAUDE.md` pattern).

2. **A genuine module-init cycle inside the stages package is masked by two function-body lazy imports.** `row_builder._build_per_call_rows_and_warnings` is an 85-LOC multi-stage orchestrator misplaced inside `row_builder.py`. It lazy-imports from `.cross_workflow` and `.warnings` at runtime because those modules already import `_node_inputs` / `_total_observed_invocations` / `_static_excerpt` / `_find_batch_static_tail_after_dynamic` from `row_builder` at module top. Phase 6 of Plan B documented this as a deliberate workaround: *"a larger shared-helper extraction would be a separate structural decision, not a safe Phase 6 side quest."* This is that side quest. Verification confirmed: extracting only `_node_inputs` does **NOT** break the cycle (three sibling helpers ride the same back-edge). The correct fix moves the misplaced orchestrator to where its job lives, not the helpers.

3. **`token_estimation.py` carries ~140 LOC of clean-up debt.** Four public `tokenize_prompt_region*` functions duplicate two private `_with_resolver` implementations line-for-line. `_memo_output_for_freshness_check` mirrors `context._latest_memo_for_freshness_check` with trivial deltas. Both consume `ctx.predicted_cache_keys` and mutate `ctx.stale_memo_*` — the freshness check is logically an `AnalysisContext` method, not a free function.

**Intended outcome:** the package's stage dependency graph becomes a true DAG (no lazy-import workarounds), tests stop reaching across the public/private boundary for section rendering, and `token_estimation.py` shrinks by ~140 LOC without breaking any test-mock surface. Zero behavior change throughout.

---

## Scope — what's in, what's out

**IN scope:**
- **Phase A:** add `section=` keyword to `render_text`. Migrate 5 `_render_summary` test sites.
- **Phase B:** create `src/pflow/core/prompt_cache_analysis/rendering/CLAUDE.md` documenting the pure-formatter helpers as stable test substrate (no code change).
- **Phase C:** move `_build_per_call_rows_and_warnings` + companions to a new `stages/per_call_pipeline.py` module. Hoist the two lazy imports inside it to module top.
- **Phase D:** collapse `tokenize_prompt_region*` × 4 to wrappers over the two `_with_resolver` privates.
- **Phase E:** promote `context._latest_memo_for_freshness_check` to `AnalysisContext.latest_memo_for_node()` method. Delete `token_estimation._memo_output_for_freshness_check`.
- **Phase F:** documentation + final verification.

**OUT of scope (do NOT touch — flagged by the verification searchers as scope creep):**
- The `_latest_value_for_ref` `ctx=None` legacy branch (`token_estimation.py:706-734`). Load-bearing for ~20 test sites; removing it is a separate concern.
- Replacing `_find_llm_event` with `ctx.trace.event_for(...)`. Would require threading `ctx` into `estimate_tokens` — scope creep.
- Splitting `rendering/text.py` into per-section files. Architecture review marked Speculative; defer.
- Splitting `warning_catalog.py`. The deletion test rejects scattering rows; internal tier split is purely editorial.
- The 3 additional private-symbol leaks from `rendering/text.py` (`_cell_calls`, `_BASELINE_LABELS`, `_indent_message`). Covered by Phase B (documented substrate) — no code change.
- Promoting the 5 stage `build_*` helpers to public API. Architecture-review "Worth exploring" candidate; user did not select.

**Naming decisions baked in (do not re-litigate):**
- The new keyword on `render_text` is named `section`, not `mode` or `output_format`. `mode` is already used for "compact vs detailed" presentation in `execution/formatters/`; `output_format` is reserved for the text/json axis. `section` is novel and unambiguous.
- The new module is named `stages/per_call_pipeline.py` (no leading underscore). The package convention is "no underscore-prefixed filenames" (signaled by `__all__` discipline at the package `__init__.py`, not by filename).
- The new method on `AnalysisContext` is named `latest_memo_for_node`, matching the existing `verb_what_for_qualifier` pattern (`cost_usd_for_node`, `trace_event_for`, `parameters_for_workflow`).
- The new doc file is `src/pflow/core/prompt_cache_analysis/rendering/CLAUDE.md`, mirroring `stages/discrepancy/CLAUDE.md`.

---

## Verification protocol — use at every phase boundary

```bash
# 1. The Task 159 baseline harness (the load-bearing oracle):
cd .taskmaster/tasks/task_159/baseline
PATH="$PWD/../../../../.venv/bin:$PATH" bash verify.sh
# Expected: 80 passed, 7 drifted, 0 harness errors.
# Exit 1 with the SAME 7 drifted case names = GREEN.
# ANY new drift case name = REGRESSION.
```

Known-drift set (the 7 cases that have always drifted):
- `03-analyze-cache-modes/07-autoload-prefers-success`
- `03-analyze-cache-modes/08-autoload-failed-only`
- `03-analyze-cache-modes/09-autoload-rejected-names-file`
- `04-warning-catalog/23-cache.batch-prewarm-lower-bound-recommended`
- `04-warning-catalog/23b-cache.batch-prewarm-lower-bound-recommended-text`
- `12-real-world-lyrics-generator/04-guide-auto-detect`
- `15-run-flag-interactions/03-report-with-only`

```bash
# 2. Unit + quality gates (sandbox-safe form per pflow-sandbox-testing guidance):
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 --doctest-modules \
    --ignore=tests/test_nodes/test_llm/test_llm_integration.py -m "not e2e" \
    -k 'not test_dry_run_json_mode_emits_no_stderr and not test_litellm_not_imported_by_cli_main and not test_progress_streams_before_downstream_nodes_complete'
# Expected: pass count ≥ 7106 (Plan B's Phase 7 added one parity-guard test).

HOME=/private/tmp/pflow-test-home .venv/bin/mypy
# Expected: Success: no issues found in 224 source files.

HOME=/private/tmp/pflow-test-home .venv/bin/deptry src
# Expected: no dependency issues.

HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a
# Expected: pass after escalation for sandboxed metadata-file access.
```

```bash
# 3. Package import cheapness (litellm must NOT load eagerly):
uv run python -c "import sys; import pflow.core.prompt_cache_analysis; assert 'litellm' not in sys.modules, 'litellm loaded eagerly — investigate'; print('OK')"
```

```bash
# 4. Private-symbol leak count tracker:
grep -rn "from pflow.core.prompt_cache_analysis.*import _" tests/ --include="*.py" | wc -l
# Starting: 63. After Phase A: should drop to ~58 (remove 5 _render_summary sites).
# Target end-state: ≤ 58.
```

---

## Phase 0 — Pre-flight (read-only, ~5 minutes)

1. **Verify environment prerequisites:**
   ```bash
   test -d .venv && test -x .venv/bin/python || { echo "FAIL: .venv missing"; exit 1; }
   mkdir -p /private/tmp/pflow-test-home
   ls .taskmaster/tasks/task_159/baseline/verify.sh
   ```
   These prerequisites are what `verify.sh` and the sandbox-safe pytest invocation depend on. If any are missing, STOP — the branch is in an unexpected state.

2. Capture the baseline drift set:
   ```bash
   cd .taskmaster/tasks/task_159/baseline
   PATH="$PWD/../../../../.venv/bin:$PATH" bash verify.sh 2>&1 | tee /tmp/baseline-pre-polish.log
   ```
   Confirm the exact 7 drifted case names listed after `drifted cases:` match the canonical set above. If they do not, STOP — the branch state has shifted since planning.

3. Capture current metrics:
   ```bash
   wc -l src/pflow/core/prompt_cache_analysis/rendering/text.py     # Expected: 2417
   wc -l src/pflow/core/prompt_cache_analysis/stages/row_builder.py # Expected: 1229
   wc -l src/pflow/core/prompt_cache_analysis/token_estimation.py   # Expected: 747
   wc -l src/pflow/core/prompt_cache_analysis/context.py            # Expected: 516

   grep -rn "from pflow.core.prompt_cache_analysis.*import _" tests/ --include="*.py" | wc -l
   # Expected: 63
   ```

4. Verify package import is cheap (item 3 of "Verification protocol" above).

5. **No commits in Phase 0** — read-only state capture.

---

## Phase A — `render_text(section=)` keyword (~1.5 hours)

**Files modified:**
- `src/pflow/core/prompt_cache_analysis/rendering/text.py` (signature change + dispatch)
- `tests/test_core/test_cache_analysis_analyze.py` (5 test sites)

**Pre-verified facts (do not re-litigate):**
- `render_text` lives at `rendering/text.py:89` with signature `def render_text(analysis: CacheAnalysis, *, all_rows: bool = False) -> str`.
- 10 `_render_*` section roots exist. Two take extra args:
  - `_render_other_blocking_errors(analysis, *, cache_blocking_present: bool)` at line 982.
  - `_render_per_call(analysis, *, all_rows: bool)` at line 1529.
- ZERO monkeypatches on `_render_summary`, `_format_cost`, or `_format_delta_parenthetical`.
- ONE production caller of `render_text`: `cli/commands/analyze_cache.py:130, 224`. The MCP server uses `render_json`; the dry-run nudge uses `summarize_from_analysis` (a SEPARATE concept that returns a `Diagnostic` — do NOT conflate with `_render_summary`'s `## Summary` section).

### A.1 — Extend `render_text` signature

Edit `src/pflow/core/prompt_cache_analysis/rendering/text.py`. Locate `def render_text(analysis: CacheAnalysis, *, all_rows: bool = False) -> str:` at line 89.

Replace the function (and ONLY the function — the helpers below it are unchanged) with:

```python
from typing import Literal

_RenderSection = Literal["all", "summary"]


def render_text(
    analysis: CacheAnalysis,
    *,
    all_rows: bool = False,
    section: _RenderSection = "all",
) -> str:
    """Render the analyzer result as markdown-formatted text.

    Parameters
    ----------
    analysis:
        The result of :func:`pflow.core.prompt_cache_analysis.analyze`.
    all_rows:
        When True, the per-call section renders every LLM row including
        low-signal ones. Default False keeps the agent-friendly default.
    section:
        Which slice of the full report to render. ``"all"`` (default) emits
        the complete report; ``"summary"`` returns just the ``## Summary``
        section as a string (no header, no footer, no trailing newline).

        Tests asserting on the summary block in isolation should use
        ``section="summary"`` instead of reaching into ``_render_summary``.
        The set of section names is intentionally narrow — extend only when
        a concrete test surface needs another value.
    """
    if section == "summary":
        return _render_summary(analysis)

    lines: list[str] = []
    lines.append(_render_header(analysis))
    lines.append(_render_summary(analysis))

    errors = _render_blocking_errors(analysis)
    if errors:
        lines.append(errors)

    other_errors = _render_other_blocking_errors(analysis, cache_blocking_present=bool(errors))
    if other_errors:
        lines.append(other_errors)

    actions = _render_recommended_actions(analysis)
    if actions:
        lines.append(actions)

    blocks = _render_suggested_blocks(analysis)
    if blocks:
        lines.append(blocks)

    cross = _render_cross_workflow(analysis)
    if cross:
        lines.append(cross)

    per_call = _render_per_call(analysis, all_rows=all_rows)
    if per_call:
        lines.append(per_call)

    drill = _render_sub_workflow_drill_in(analysis)
    if drill:
        lines.append(drill)

    notes = _render_notes(analysis)
    if notes:
        lines.append(notes)

    return "\n\n".join(lines) + "\n"
```

Add `from typing import Literal` to the existing typing imports at the top of `text.py`. `text.py` currently imports only `cast` from `typing`; extend that line to `from typing import Literal, cast`.

`_RenderSection` is module-private (leading underscore) — implementation detail of the kwarg type, not a public taxonomy. The body of the helper sequence is byte-for-byte identical to today's `render_text` body; only the section dispatch is new.

### A.2 — Migrate the 5 `_render_summary` test sites

Files: `tests/test_core/test_cache_analysis_analyze.py` at lines 4304, 4327, 4359, 4438, 4544.

Pattern transformation (apply uniformly to all five):

```python
# Before — each site looks like:
from pflow.core.prompt_cache_analysis.rendering.text import _render_summary
...
rendered = _render_summary(result)
assert "..." in rendered

# After:
from pflow.core.prompt_cache_analysis import render_text
...
rendered = render_text(result, section="summary")
assert "..." in rendered
```

Concrete substring assertions are unaffected — `section="summary"` returns exactly what `_render_summary(result)` returns today (A.1's dispatch is a 1-line early-return).

Consolidate the import (one `from pflow.core.prompt_cache_analysis import render_text` at the top of `test_cache_analysis_analyze.py` rather than per-test). Remove the now-dead `from ... import _render_summary` line.

### A.3 — Sweep for any other `_render_summary` test reference

```bash
grep -rn "_render_summary" tests/ --include="*.py"
```

Expected post-migration hits, ALL of which are docstring/comment-only (do NOT migrate; leave verbatim):
- `tests/test_core/test_cache_analysis_analyze.py:4300` — docstring mentioning `_render_summary` for context.
- `tests/test_core/test_cache_analysis_analyze.py:4651` — docstring inside a `_format_cost` test that mentions `_render_summary`.
- `tests/test_core/test_cache_analysis_renderers.py:901` — mutation-test reference in a comment.

If any hits are import statements or call sites (not docstring/comment text), apply the same transformation as A.2. If only docstring/comment hits remain, the sweep is complete.

### A.4 — Phase A verification gate

```bash
# Same-drift harness:
cd .taskmaster/tasks/task_159/baseline
PATH="$PWD/../../../../.venv/bin:$PATH" bash verify.sh
# Expected: same 7 drifted cases.

# Targeted unit tests:
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_cache_analysis_analyze.py -v -k "summary_message or render_text_emits_suggested or heterogeneous_only_summary"
# Expected: the 5 migrated tests pass.

# Quality gates:
HOME=/private/tmp/pflow-test-home .venv/bin/mypy
HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a

# Private-symbol leak count:
grep -rn "from pflow.core.prompt_cache_analysis.*import _" tests/ --include="*.py" | wc -l
# Expected: 58 (down from 63; -5 sites).
```

### A.5 — Phase A commit message

```
Polish A: render_text(section="summary") public surface

Add a Literal["all", "summary"] `section` keyword to render_text.
Callers needing just the ## Summary section now use
render_text(analysis, section="summary") instead of reaching into
the private _render_summary helper.

5 test sites in test_cache_analysis_analyze.py migrate from
_render_summary direct import to the public form. The remaining
7 sites that import pure leaf formatters (_format_delta_parenthetical,
_format_cost) intentionally stay as direct calls — these are
substrate documented in Phase B.

Private-symbol leak count: 63 → 58.

Zero behavior change: baseline harness reports same 7 drifted cases.
```

---

## Phase B — Document the pure-formatter substrate (~30 minutes)

**Files modified:**
- NEW: `src/pflow/core/prompt_cache_analysis/rendering/CLAUDE.md`
- `src/pflow/core/prompt_cache_analysis/CLAUDE.md` (1-line tree update)

### B.1 — Create `rendering/CLAUDE.md`

Mirror the pattern established at `src/pflow/core/prompt_cache_analysis/stages/discrepancy/CLAUDE.md` — explicit documentation of which private symbols are stable test surfaces.

Exact content to write:

```markdown
# Cache Analysis Rendering

Read-only projections of `CacheAnalysis`. Nothing in this directory
performs analysis — these modules format already-derived state for
downstream consumers (text terminal, JSON, dry-run nudge).

## Files

- `text.py` — markdown-formatted text report. Single public entry point
  `render_text(analysis, *, all_rows=False, section="all")`. The
  `section` keyword exists so tests can assert on one section in
  isolation without crossing the public/private boundary; the set of
  named sections is intentionally narrow.
- `json.py` — JSON projection. `render_json(analysis)`.
- `summarize.py` — one-line dry-run nudge `Diagnostic`. Distinct from
  the `## Summary` markdown section emitted by `text._render_summary`
  (and surfaced via `render_text(..., section="summary")`).
- `cross_workflow_edits.py` — paste-ready cache-block edit text for
  cross-workflow recommendations. Single entry point
  `format_grouped_body_block`.
- `views.py` — blocking-error and recommended-action projections used
  by both `text.py` and `json.py`.
- `traces_list.py` — `--list-traces` output.

## Test API — substrate formatters

These private (underscore-prefixed) symbols in `text.py` are documented
as stable test surfaces. They are pure functions over typed inputs
(`CostDelta`, `PerCallRow`, etc.) with no observable shape via the
public `render_text(analysis)` call alone. Tests may import them
directly; refactors are free to rename them but must update tests
in the same change.

- `_render_summary(analysis: CacheAnalysis) -> str` — markdown summary
  section. Prefer `render_text(analysis, section="summary")` from new
  code; the underscored helper remains as the implementation. Five
  legacy test sites have migrated to the public form.
- `_format_delta_parenthetical(cost_delta: CostDelta, *, local_cache_reuse: bool = False) -> str`
  — pure formatter for `CostDelta` objects. Five direct-test sites in
  `test_cache_analysis_renderers.py` pin exact strings.
- `_format_cost(value: float | None, *, partial: bool, unavailable_models: tuple[str, ...]) -> str`
  — pure formatter for the summary cost cell. Two sites in
  `test_cache_analysis_analyze.py` assert grammar variants (singular vs
  plural unpriced models).
- `_cell_calls(row: PerCallRow, *, static_mode: bool = False) -> str`
  — per-row cell renderer used by the per-call table. One direct-test
  site in `test_cache_analysis_renderers.py`.
- `_indent_message(message: str, *, prefix: str) -> list[str]` — pure
  indentation helper. One direct-test site.
- `_BASELINE_LABELS: dict[str, str]` — producer-to-label parity map.
  Tests assert that every value emitted by `CostDelta.baseline` has a
  label entry; deleting either side without the other breaks rendering.

Other private symbols in `text.py` are implementation details. Do not
test them directly; cover their behavior through `render_text` or one
of the documented surfaces above.
```

### B.2 — Reference the new CLAUDE.md from the package's main CLAUDE.md

Edit `src/pflow/core/prompt_cache_analysis/CLAUDE.md`. Locate the rendering subtree in the Module Structure tree (currently lists `__init__.py`, `json.py`, `text.py`, etc.). Add ONE line as the FIRST entry inside `rendering/`:

```
│   ├── CLAUDE.md            # documented direct-test helper surface
```

Mirrors how `stages/discrepancy/CLAUDE.md` appears in the discrepancy subtree at line 73.

### B.3 — Phase B verification gate

```bash
# Same-drift harness:
cd .taskmaster/tasks/task_159/baseline
PATH="$PWD/../../../../.venv/bin:$PATH" bash verify.sh
# Expected: same 7 drifted cases (no code change — pure docs).

HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a
# Expected: pass.
```

### B.4 — Phase B commit message

```
Polish B: document rendering test substrate

Add rendering/CLAUDE.md modelled on stages/discrepancy/CLAUDE.md.
Lists the six private symbols in rendering/text.py that are
stable direct-test surfaces (_format_delta_parenthetical,
_format_cost, _cell_calls, _indent_message, _BASELINE_LABELS,
_render_summary). Future refactors of the rendering layer keep
these names or update tests in the same change.

Zero code changes.
```

---

## Phase C — Move the cycle-causing orchestrator (~2.5 hours)

**Files modified:**
- NEW: `src/pflow/core/prompt_cache_analysis/stages/per_call_pipeline.py`
- `src/pflow/core/prompt_cache_analysis/stages/row_builder.py` (remove orchestrator + companions; keep row primitive construction)
- `src/pflow/core/prompt_cache_analysis/analyze.py` (re-target import)
- Test files that import the moved symbols (sweep in step C.5)

**Pre-verified facts:**
- `_build_per_call_rows_and_warnings` is at `stages/row_builder.py:757-842` (85 LOC). Its lazy imports at lines 764-768 are the cycle workaround.
- Called from `analyze.py:198` (and the misalignment-recovery path at `analyze.py:422`).
- The function reaches into `cross_workflow` for `_build_cross_workflow_candidates_by_row` and `_has_structural_cross_workflow_projection_candidate`; into `warnings` for `_per_node_warnings`; and into `row_builder` itself for `_build_per_call_row` and `_extract_declared_chunks` and `_detect_candidate_subsets`.
- The 4 "shared helpers" identified in the architecture review (`_node_inputs`, `_total_observed_invocations`, `_static_excerpt`, `_find_batch_static_tail_after_dynamic`) **STAY** in `row_builder.py`. They are row-construction primitives; moving them is unnecessary because the cycle's root is the orchestrator, not the helpers. Verification confirmed: moving only `_node_inputs` does NOT break the cycle.

### C.1 — Identify what moves vs. what stays

**MOVES to `stages/per_call_pipeline.py`:**
1. `_PerCallRowsResult` dataclass (find via `grep -n "class _PerCallRowsResult" src/pflow/core/prompt_cache_analysis/stages/row_builder.py`; capture its current definition verbatim).
2. `_build_per_call_rows_and_warnings` (the orchestrator function, currently `row_builder.py:757-842`).

**STAYS in `row_builder.py` (decision made — do NOT move these):**
- `_build_per_call_row` (single-row builder, ~600 LOC).
- The 4 "shared helpers" (`_node_inputs`, `_total_observed_invocations`, `_static_excerpt`, `_find_batch_static_tail_after_dynamic`).
- **`_extract_declared_chunks`** — verified to have 3 call sites: `analyze.py:150` (top-level analyze flow, NOT the orchestrator), `row_builder.py:786` (inside the orchestrator), and `row_builder.py:1045` (inside `_detect_candidate_subsets`). The first call site is unrelated to the orchestrator move and would force an `analyze.py:150` import change if moved. The second and third callers move together with their hosts. Keeping the symbol in `row_builder.py` lets BOTH `analyze.py` and the new `per_call_pipeline.py` import from `row_builder.py` — one-way, no cycle, no extra import bookkeeping.
- **`_detect_candidate_subsets`** — has one call site inside `_build_per_call_rows_and_warnings` (currently `row_builder.py:787`) AND it CALLS `_extract_declared_chunks` (at `row_builder.py:1045`). The two are tightly coupled. Moving `_detect_candidate_subsets` alone breaks that internal call. Keeping both in `row_builder.py` preserves their coupling and avoids the "must move as a pair" trap. Note: `suggestions.py:172` has a docstring/comment reference to `_detect_candidate_subsets` that the verification grep will surface — this is text, not an import or call site; ignore it.

**LIVES ELSEWHERE (verify before importing in C.2):**
- `_build_call_counts_by_node` — Plan B Phase 6 moved it to `trace_loading.py`. Verify with `grep -rn "def _build_call_counts_by_node" src/pflow/core/prompt_cache_analysis/`. Whatever module owns it, the new `per_call_pipeline.py` imports from there.

**Net effect of this decision:**
- `per_call_pipeline.py` imports `_extract_declared_chunks`, `_detect_candidate_subsets`, `_build_per_call_row` from `row_builder.py` at module top. One-way edge.
- `analyze.py:150` continues to import `_extract_declared_chunks` from `row_builder.py` (no change needed for this symbol).
- Only `_build_per_call_rows_and_warnings` and `_PerCallRowsResult` move — minimal surface area.

### C.2 — Create `stages/per_call_pipeline.py`

The new file owns the orchestrator and its return-shape dataclass only. Read `row_builder.py:757-842` (the orchestrator body) verbatim and capture the `_PerCallRowsResult` dataclass definition. Paste them into the new file with these mechanical changes:

1. Delete the function-body lazy import blocks at `row_builder.py:764-768`:
   ```python
   from .cross_workflow import (
       _build_cross_workflow_candidates_by_row,
       _has_structural_cross_workflow_projection_candidate,
   )
   from .warnings import _per_node_warnings
   ```
2. Add those imports at the top of the new module.
3. Add the other imports the function body needs. Required (verify by reading the function body before writing):
   - `from __future__ import annotations`
   - `from collections.abc import Mapping` (used by `_PerCallRowsResult` field types)
   - `from dataclasses import dataclass, field` (used by `_PerCallRowsResult` itself — DO NOT FORGET; the dataclass requires this import)
   - `from typing import Any`
   - `from pflow.core.diagnostic import Diagnostic`
   - `from ..context import AnalysisContext`
   - `from ..types import PerCallRow, TraceExecutionIndex` (also `_RowCrossWorkflowCandidate` if the dataclass field uses it; verify by reading the current `_PerCallRowsResult` definition)
   - `from ..trace_loading import _build_call_counts_by_node` (verify location per C.1)
   - `from .cross_workflow import _build_cross_workflow_candidates_by_row, _has_structural_cross_workflow_projection_candidate`
   - `from .row_builder import _build_per_call_row, _extract_declared_chunks, _detect_candidate_subsets`
   - `from .warnings import _per_node_warnings`
4. **DO NOT modify function bodies otherwise.** Pure structural relocation.

File skeleton (the implementing agent fills in the imports above and pastes the exact function bodies verbatim):

```python
"""Per-call row pipeline — orchestrates row construction, warning emission,
and cross-workflow attachment for every LLM node reachable from the
analyzer's root workflow.

This module owns the multi-stage seam between row_builder (row primitive
construction), warnings (per-node warning emission), and cross_workflow
(candidate detection). It exists so each stage module can import its
sibling stages at module top without a cycle: the cycle is in
row_builder → cross_workflow / warnings, and the pipeline function is
the cycle source. Moving it out of row_builder breaks the cycle cleanly.

Single public-ish entry point: ``_build_per_call_rows_and_warnings``.
Underscore prefix preserved — production callers are analyze.py only.
"""

from __future__ import annotations

# (the imports listed in step 3 above)


# [_PerCallRowsResult dataclass — paste verbatim from current row_builder.py]


def _build_per_call_rows_and_warnings(
    *,
    ctx: AnalysisContext,
    cw_result: Any,
    trace_index: TraceExecutionIndex,
) -> _PerCallRowsResult:
    """Walk every reachable workflow IR and build LLM rows."""
    # [body — paste verbatim from current row_builder.py:763-842, MINUS
    #  the two function-body `from .cross_workflow import ...` and
    #  `from .warnings import _per_node_warnings` blocks which now live
    #  at module top.]
```

### C.3 — Update `row_builder.py`

Delete the moved symbols from `row_builder.py`:
- `_PerCallRowsResult` dataclass.
- `_build_per_call_rows_and_warnings` function.

Per the C.1 decision, `_extract_declared_chunks` and `_detect_candidate_subsets` STAY in `row_builder.py` — do NOT delete them.

Confirm `row_builder.py` no longer has function-body imports from sibling stages:
```bash
grep -n "^    from \." src/pflow/core/prompt_cache_analysis/stages/row_builder.py
# Expected: zero hits in function bodies (only top-level `from .` imports allowed).
```

Confirm `row_builder.py` does NOT import from `.cross_workflow` or `.warnings` at module top either (it never did at top-level; verify):
```bash
grep -n "^from .cross_workflow\|^from .warnings" src/pflow/core/prompt_cache_analysis/stages/row_builder.py
# Expected: zero hits.
```

### C.4 — Update `analyze.py`

In `src/pflow/core/prompt_cache_analysis/analyze.py`, locate the existing import at line 59:
```python
from .stages.row_builder import _build_per_call_rows_and_warnings, _extract_declared_chunks, _PerCallRowsResult
```

Replace with TWO lines:
```python
from .stages.per_call_pipeline import _build_per_call_rows_and_warnings, _PerCallRowsResult
from .stages.row_builder import _extract_declared_chunks
```

Rationale: per the C.1 decision, `_extract_declared_chunks` stays in `row_builder.py`; only `_build_per_call_rows_and_warnings` and `_PerCallRowsResult` move. The `analyze.py:150` call site of `_extract_declared_chunks` is unchanged.

The two call sites of `_build_per_call_rows_and_warnings` (lines 198 and 422) are unchanged — same function name, just a different import path.

### C.5 — Sweep test imports + monkeypatch fixtures of the moved symbols

The moves in this phase are: `_build_per_call_rows_and_warnings` and `_PerCallRowsResult`. Only references to these two names need re-targeting from `.stages.row_builder` to `.stages.per_call_pipeline`. `_extract_declared_chunks` and `_detect_candidate_subsets` stay in `row_builder.py` (per C.1) — leave their references alone.

**Step 1 — direct imports:**
```bash
grep -rn "from pflow\.core\.prompt_cache_analysis\.stages\.row_builder import" tests/ --include="*.py" | grep -E "_PerCallRowsResult|_build_per_call_rows_and_warnings"
```
For each hit, re-target to `.stages.per_call_pipeline`. If the import line includes other row_builder symbols, split into two import statements (keep the unmoved symbols on the original line).

**Step 2 — `importlib.import_module` dynamic refs:**
```bash
grep -rn "stages\.row_builder" tests/ --include="*.py"
```
Inspect each hit. Of particular concern: `tests/test_core/test_cache_analysis_per_id_emission.py:139` uses `importlib.import_module(...)` followed by `getattr`. Identify which symbol is being fetched. If it's `_build_per_call_rows_and_warnings` or `_PerCallRowsResult`, update the module path to `stages.per_call_pipeline`. If it's any other row_builder symbol, leave it.

**Step 3 — `_STAGE_ATTR_MODULES` monkeypatch tuples (silent-failure risk):**
Three test files maintain a list of stage modules patched by a shared monkeypatch fixture:
- `tests/test_core/test_cache_analysis_analyze.py:42, 49, 61, 68`
- `tests/test_core/test_cache_analysis_per_id_coverage.py:42, 49, 61`
- `tests/test_core/test_cache_analysis_per_id_emission.py:56, 63, 75, 82`

These tuples list module-level names like `estimate_tokens`, `get_min_cache_tokens`, `_estimate_ref_tokens`, `get_default_workflow_model` and patch them on `stages.row_builder`. **Audit the new `per_call_pipeline.py` module to see if it imports any of these names at module top.** If yes, add `pflow.core.prompt_cache_analysis.stages.per_call_pipeline` to the relevant tuples so the monkeypatch patches the new module's binding too. If the new module does NOT import any of these names (likely — the orchestrator calls them through `ctx` or via `_build_per_call_row`), no change needed. The audit step:
```bash
grep -nE "^(from .*import|import) (estimate_tokens|get_min_cache_tokens|_estimate_ref_tokens|get_default_workflow_model)" src/pflow/core/prompt_cache_analysis/stages/per_call_pipeline.py
```
Expected: zero hits (the orchestrator uses these indirectly through callees in other stages, not by direct top-level import). If hits exist, the tuples must be updated.

**Step 4 — `caplog` logger name (silent-failure risk):**
```bash
grep -rn "caplog.at_level.*pflow.core.prompt_cache_analysis.stages.row_builder" tests/ --include="*.py"
```
Expected hit: `tests/test_core/test_cache_analysis_analyze.py:2338`. **Audit what `_build_per_call_rows_and_warnings` actually logs.** If it emits debug logs (via `logger.debug(...)`) AND those logs were the target of the line 2338 caplog assertion, then those logs are now produced under the `stages.per_call_pipeline` logger name (because `logging.getLogger(__name__)` resolves to the new module). The caplog capture will silently see nothing.

To verify what logs the function emits:
```bash
grep -n "logger\." src/pflow/core/prompt_cache_analysis/stages/row_builder.py | sed -n '/757,842/p'
```
Or read lines 757-842 directly. If the function emits debug logs, the caplog at line 2338 needs the logger string updated to `pflow.core.prompt_cache_analysis.stages.per_call_pipeline`. If the function does NOT emit logs directly, no change needed.

This is the classic Task 92-style patch-string silent-failure mode — easy to miss, easy to ship. Do not skip this audit.

### C.6 — Cycle verification

```bash
# Package import must succeed without any lazy hoist:
uv run python -c "import pflow.core.prompt_cache_analysis; print('OK')"

# row_builder.py must have zero function-body imports from sibling stages:
grep -n "^    from \.cross_workflow\|^    from \.warnings" src/pflow/core/prompt_cache_analysis/stages/row_builder.py
# Expected: zero hits.

# The new per_call_pipeline.py must have its imports at module top, not lazy:
grep -n "^    from \." src/pflow/core/prompt_cache_analysis/stages/per_call_pipeline.py
# Expected: zero hits in function bodies.
```

If `uv run python -c "import ..."` raises `ImportError: ... circular import ...`, inspect:
```bash
grep -n "from \.row_builder\|from \.per_call_pipeline" src/pflow/core/prompt_cache_analysis/stages/*.py
```

The expected edges are:
- `per_call_pipeline → row_builder` (for `_build_per_call_row`)
- `per_call_pipeline → cross_workflow`
- `per_call_pipeline → warnings`
- `warnings → row_builder` (for `_find_batch_static_tail_after_dynamic`, etc.)
- `cross_workflow → row_builder` (for `_total_observed_invocations`, etc.)
- `suggestions → row_builder` (for `_node_inputs`)
- `partial_declarations → row_builder` (for `_node_inputs`)

NO `row_builder → cross_workflow`. NO `row_builder → warnings`. That's the DAG.

### C.7 — Phase C verification gate

```bash
# Same-drift harness:
cd .taskmaster/tasks/task_159/baseline
PATH="$PWD/../../../../.venv/bin:$PATH" bash verify.sh
# Expected: same 7 drifted cases.

# Targeted unit tests on the moved orchestrator's behavior:
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_cache_analysis_analyze.py -v -k "per_call or rows_and_warnings or cross_workflow_candidate" -x
# Expected: all pass.

# Full sandbox-safe pytest:
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 --doctest-modules \
    --ignore=tests/test_nodes/test_llm/test_llm_integration.py -m "not e2e" \
    -k 'not test_dry_run_json_mode_emits_no_stderr and not test_litellm_not_imported_by_cli_main and not test_progress_streams_before_downstream_nodes_complete'

HOME=/private/tmp/pflow-test-home .venv/bin/mypy
HOME=/private/tmp/pflow-test-home .venv/bin/deptry src
HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a

# Cycle proof:
uv run python -c "import sys; import pflow.core.prompt_cache_analysis; assert 'litellm' not in sys.modules; print('package imports cheap, no litellm; cycle clean')"

# File-shape verification:
wc -l src/pflow/core/prompt_cache_analysis/stages/per_call_pipeline.py
# Expected: ~120 LOC (orchestrator + dataclass + any helpers moved per C.1).

wc -l src/pflow/core/prompt_cache_analysis/stages/row_builder.py
# Expected: ~1,100 LOC (down from 1,229; ~120 LOC moved out).
```

### C.8 — Phase C commit message

```
Polish C: extract per_call_pipeline.py to break the row_builder cycle

_build_per_call_rows_and_warnings is a multi-stage orchestrator
(row_builder + warnings + cross_workflow). Living inside row_builder.py
forced two function-body lazy imports to mask a real module-init cycle
that Phase 6 of Plan B flagged as "a separate structural decision."

Move the orchestrator + its _PerCallRowsResult dataclass + the
single-caller IR helpers (_extract_declared_chunks if applicable,
_detect_candidate_subsets if applicable) to a new
stages/per_call_pipeline.py. The new module imports row_builder,
cross_workflow, and warnings at module top — no lazy imports needed
because the pipeline IS the multi-stage seam.

After this change:
- stages/row_builder.py has zero intra-stages function-body imports.
- The stage dependency graph is a clean DAG.
- analyze.py imports from per_call_pipeline; row_builder is now
  strictly the row primitive construction module.

Zero behavior change: baseline harness reports same 7 drifted cases.
```

---

## Phase D — Collapse tokenize variants (~1 hour)

**Files modified:**
- `src/pflow/core/prompt_cache_analysis/token_estimation.py` (collapse 4 functions to 4 wrappers)

**Pre-verified facts:**
- 4 public functions duplicate 2 private `_with_resolver` implementations line-for-line, differing only in NOT passing `use_projection_resolver=True`.
- All 4 are in `__all__` (lines 743-746). Stay in `__all__`.
- ZERO test monkeypatches on any of the 4. Symbol stability requirement: keep names at the same module path.
- `build_shared_store_for_refs` defaults `use_projection_resolver=False`, which is why the False case can be the default in the wrapper signatures.

### D.1 — Diff-check before collapse

The publics currently DO NOT delegate to the privates — they have inlined copies of the same body. The diff is expected to show differences; the question is whether those differences are EXACTLY the projection-flag absence (the safe collapse case) or something more (unsafe).

```bash
# Visually confirm equivalence between each public and its private sibling.
sed -n '285,330p' src/pflow/core/prompt_cache_analysis/token_estimation.py > /tmp/public_a.py
sed -n '415,445p' src/pflow/core/prompt_cache_analysis/token_estimation.py > /tmp/private_a.py
diff /tmp/public_a.py /tmp/private_a.py

sed -n '348,397p' src/pflow/core/prompt_cache_analysis/token_estimation.py > /tmp/public_b.py
sed -n '448,482p' src/pflow/core/prompt_cache_analysis/token_estimation.py > /tmp/private_b.py
diff /tmp/public_b.py /tmp/private_b.py
```

**Pass criterion — the diff MUST show ONLY these three differences for the collapse to be safe:**
1. The signature line differs (different function name, and the public lacks the `use_projection_resolver: bool` parameter).
2. Inside the body, the public does NOT thread `use_projection_resolver` into `build_shared_store_for_refs(...)` (the private passes the flag; the public omits it, relying on the default `False`).
3. The docstring may differ in wording (acceptable).

**FAIL criterion — if the diff shows ANY of these, do NOT collapse that variant:**
- Different exception-handling structure (e.g., one catches an exception the other propagates).
- Different return value computation (e.g., one applies a min/max clamp the other doesn't).
- Different early-return conditions.
- A parameter present in one but not the other beyond `use_projection_resolver`.

If a single variant fails the pass criterion, narrow the collapse to the variants that pass; leave the failing public's body unchanged.

### D.2 — Replace the 4 public functions with wrappers

In `src/pflow/core/prompt_cache_analysis/token_estimation.py`:

**Before writing any wrapper: read the current signature (parameter names AND return type annotation) of each public function. Mirror it exactly in the wrapper.** The examples below show one likely shape, but the actual signatures take precedence. The non-lower-bound variants are believed to return `int | None`; the two lower-bound variants are confirmed to return `tuple[int, tuple[str, ...]]`. Verify each before writing.

Replace lines 285-330 (`tokenize_prompt_region`) with (verify current `region:`/`text:` parameter name + return type):
```python
def tokenize_prompt_region(
    region: str,           # or `text:` — match current signature
    *,
    model: str,
    ctx: AnalysisContext,
) -> int | None:           # match current return type annotation
    """Tokenize a literal prompt region for ``model`` against the analyzer context.

    Returns None when the model has no tokenizer registered. Resolves ``${var}``
    refs against ``ctx.parameters`` and ``ctx.memo_cache`` per the standard
    ``resolve_ref_value`` tier order. For the projection variant that consults
    trace outputs as an additional tier, use
    :func:`tokenize_prompt_region_for_projection`.
    """
    return _tokenize_prompt_region_with_resolver(
        region, model=model, ctx=ctx, use_projection_resolver=False
    )
```
(If the current parameter name is `text:`, use `text` in the delegation call — match the public signature.)

Replace lines 333-345 (`tokenize_prompt_region_for_projection`) with:
```python
def tokenize_prompt_region_for_projection(
    region: str,           # or `text:` — match current signature
    *,
    model: str,
    ctx: AnalysisContext,
) -> int | None:           # match current return type annotation
    """Projection variant of :func:`tokenize_prompt_region`.

    Adds the trace-output tier to ref resolution
    (``resolve_ref_value_for_projection``) so cross-workflow recommendations
    using trace evidence get accurate pre-fix token counts.
    """
    return _tokenize_prompt_region_with_resolver(
        region, model=model, ctx=ctx, use_projection_resolver=True
    )
```

Replace lines 348-397 (`tokenize_prompt_region_lower_bound`) with the wrapper. **CRITICAL: this function does NOT return `int | None` — it returns `tuple[int, tuple[str, ...]]` (the engine at `runtime/engine/engine.py:177` unpacks the tuple). The parameter name is `region:`, not `text:`. Read the current signature at line 348 to confirm before writing the wrapper.** Example shape (verify against current signature first):

```python
def tokenize_prompt_region_lower_bound(
    region: str,
    *,
    model: str,
    ctx: AnalysisContext,
) -> tuple[int, tuple[str, ...]]:
    """Conservative lower bound on tokens for a prompt region.

    Used by the runtime engine's pre-flight prewarm check where unresolved
    refs should NOT inflate the count. Unresolved ``${var}`` refs contribute
    zero tokens (not their default fallback values).

    Returns ``(token_count, unresolved_refs)`` — preserve the contract
    documented on the private ``_tokenize_prompt_region_lower_bound_with_resolver``.
    """
    return _tokenize_prompt_region_lower_bound_with_resolver(
        region, model=model, ctx=ctx, use_projection_resolver=False
    )
```

Replace lines 400-412 (`tokenize_prompt_region_lower_bound_for_projection`) with the projection wrapper. Same caveat — verify signature and return type against current code:

```python
def tokenize_prompt_region_lower_bound_for_projection(
    region: str,
    *,
    model: str,
    ctx: AnalysisContext,
) -> tuple[int, tuple[str, ...]]:
    """Projection variant of :func:`tokenize_prompt_region_lower_bound`."""
    return _tokenize_prompt_region_lower_bound_with_resolver(
        region, model=model, ctx=ctx, use_projection_resolver=True
    )
```

**Critical pre-write step for all 4 wrappers:** read the CURRENT function signature and return type for each public function. Mirror them exactly in the wrapper. If the current signature uses `region:` not `text:`, use `region:`. If the return type is a tuple, use the tuple. The wrapper's job is to preserve the exact public API surface; only the body changes from inlined logic to a delegation call.

**Preserve docstring contract bullets.** The existing `tokenize_prompt_region_lower_bound` docstring has a "Contract:" block with specific bullet points (empty/no-refs/fully-resolved/partial/exception/single-ref). Either copy those bullets verbatim into the wrapper docstring, OR move them into the private `_tokenize_prompt_region_lower_bound_with_resolver`'s docstring. They are load-bearing for downstream readers.

**Do NOT modify** `_tokenize_prompt_region_with_resolver` (lines 415-445) or `_tokenize_prompt_region_lower_bound_with_resolver` (lines 448-482). They stay as the implementation. The four public functions still appear in `__all__`.

### D.3 — Phase D verification gate

```bash
# Same-drift harness:
cd .taskmaster/tasks/task_159/baseline
PATH="$PWD/../../../../.venv/bin:$PATH" bash verify.sh
# Expected: same 7 drifted cases. Token counts must be identical — the
# privates already did the work; the wrappers just delegate.

# Targeted token tests:
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_cache_analysis_token_estimation.py -v
# Expected: all pass.

HOME=/private/tmp/pflow-test-home .venv/bin/mypy
HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a

# File shape:
wc -l src/pflow/core/prompt_cache_analysis/token_estimation.py
# Expected: ~640 LOC (down from 747; ~100 LOC eliminated from the 4 wrappers).

# Symbols still importable at the same paths:
uv run python -c "
from pflow.core.prompt_cache_analysis.token_estimation import (
    tokenize_prompt_region,
    tokenize_prompt_region_for_projection,
    tokenize_prompt_region_lower_bound,
    tokenize_prompt_region_lower_bound_for_projection,
)
print('OK: all 4 public tokenize functions importable at same path')
"
```

### D.4 — Phase D commit message

```
Polish D: collapse tokenize_prompt_region variants to wrappers

The four public tokenize_prompt_region* functions duplicated the
bodies of two private _with_resolver helpers line-for-line, differing
only in NOT passing use_projection_resolver=True. The publics now
delegate to the privates with the appropriate flag.

Public symbols stay at the same module path (zero test-mock impact;
verified no monkeypatches on any of them). __all__ unchanged.

token_estimation.py: ~747 → ~640 LOC.

Zero behavior change: baseline harness reports same 7 drifted cases.
```

---

## Phase E — Promote memo freshness to `AnalysisContext` method (~1.5 hours)

**Files modified:**
- `src/pflow/core/prompt_cache_analysis/context.py` (add method; delete module-level helper; update 2 callers)
- `src/pflow/core/prompt_cache_analysis/token_estimation.py` (delete `_memo_output_for_freshness_check`; update its 2 callers)

**Pre-verified facts:**
- `context._latest_memo_for_freshness_check` is at lines 484-513. Module-level function (not a method). Returns `tuple[dict, float] | None`. Called from `context._resolve_from_memo` (line 386) and `context._resolve_from_memo_in_workflow` (line 421).
- `token_estimation._memo_output_for_freshness_check` is at lines 612-649. Returns `dict | None` (strips `created_at`). Called from `token_estimation._llm_usage_field_from_memo` (line 600) and `token_estimation._latest_value_for_ref` ctx=None branch (around line 728).
- Behavior deltas between the two implementations:
  - (1) token_estimation catches `Exception` internally; context catches in callers (both reach `logger.debug` and return None).
  - (2) token_estimation gates on `ctx is not None`; context requires `ctx`.
  - (3) `isinstance(output, dict)` guard placement differs: token_estimation guards every return; context guards only the legacy fallback branch (callers compensate).
  - (4) `stale_memo_*` mutation is IDENTICAL between both.
- The naming pattern on `AnalysisContext` is `verb_what_for_qualifier`: `cost_usd_for_node`, `trace_event_for`, `parameters_for_workflow`. The new method is named `latest_memo_for_node`.
- ZERO test imports of either helper. ZERO test monkeypatches.
- The `_latest_value_for_ref` ctx=None branch is load-bearing for ~20 test sites. **KEEP IT** — just rewire its internal lookup.

### E.1 — Add `AnalysisContext.latest_memo_for_node` method

Edit `src/pflow/core/prompt_cache_analysis/context.py`. Locate `parameters_for_workflow` (currently around line 174-178) and add the new method AFTER it, BEFORE the `Template ref resolution` section comment (currently around line 180):

```python
    # ------------------------------------------------------------------
    # Memo freshness lookup
    # ------------------------------------------------------------------

    def latest_memo_for_node(
        self,
        node_id: str,
        *,
        workflow_path: str | None,
    ) -> tuple[dict[str, Any], float] | None:
        """Return latest memo ``(output, created_at)`` for ``node_id`` or None.

        Encapsulates the Bundle-6 cache-key freshness check that previously
        lived as a free function (``_latest_memo_for_freshness_check``) and
        as a sibling in ``token_estimation.py``. Both call sites now route
        through this method so the freshness machinery
        (``predicted_cache_keys`` lookup, ``stale_memo_skipped`` /
        ``stale_memo_uncheckable`` mutation) has one home.

        Returns None when:
        - No memo cache is attached to this context.
        - The memo cache has no entry for ``node_id`` in this ``workflow_path``.
        - The Bundle-6 cache_key comparison detects staleness (the analyzer
          skipped the row; ``self.stale_memo_skipped`` records the key).
        - The stored output is not a ``dict`` (defensive guard).

        Returns ``(output, created_at)`` when memo data is present and either:
        - The Bundle-6 cache_key matches the prediction.
        - The prediction was intentionally skipped (``_PREDICTION_SKIPPED``),
          in which case ``self.stale_memo_uncheckable`` records the key but
          the memo data is still surfaced (best-effort signal).
        - The cache backend doesn't support ``get_latest_for_node_with_cache_key``
          (legacy memo path), in which case the value is returned without
          freshness checking.

        Output is guaranteed to be a ``dict`` — the guard is at the method
        boundary, so callers don't need to repeat the isinstance check.
        """
        if self.memo_cache is None:
            return None
        if hasattr(self.memo_cache, "get_latest_for_node_with_cache_key"):
            result = self.memo_cache.get_latest_for_node_with_cache_key(
                node_id, workflow_path=workflow_path
            )
            if result is None:
                return None
            output, created_at, memo_cache_key = result
            if not isinstance(output, dict):
                return None
            predicted = self.predicted_cache_keys.get((workflow_path, node_id))
            if predicted is None:
                return output, created_at
            if predicted == _PREDICTION_SKIPPED:
                self.stale_memo_uncheckable.add((workflow_path, node_id))
                return output, created_at
            if memo_cache_key != predicted:
                self.stale_memo_skipped.add((workflow_path, node_id))
                return None
            return output, created_at
        result = self.memo_cache.get_latest_for_node(node_id, workflow_path=workflow_path)
        if result is None:
            return None
        output, created_at = result
        if not isinstance(output, dict):
            return None
        return output, created_at
```

**Critical preserved semantics** (verify by reading the original `_latest_memo_for_freshness_check` at lines 484-513 before writing):
- The `hasattr(memo_cache, "get_latest_for_node_with_cache_key")` discriminator stays.
- The `_PREDICTION_SKIPPED` branch returns the output AND mutates `stale_memo_uncheckable`.
- The cache-key mismatch branch returns None AND mutates `stale_memo_skipped`.
- The legacy `get_latest_for_node` branch returns the dict with no freshness mutation.
- The `isinstance(output, dict)` guard now applies to BOTH branches (the union of guarantees from the two prior implementations — strictly more conservative). The harness will catch any production regression.

### E.2 — Delete the module-level `_latest_memo_for_freshness_check`

In `src/pflow/core/prompt_cache_analysis/context.py`, delete the entire function at lines 484-513.

### E.3 — Update `context.py` callers

In `_resolve_from_memo` (currently around line 379), find the block:
```python
try:
    latest = _latest_memo_for_freshness_check(
        self.memo_cache,
        root,
        workflow_path=self.workflow_path,
        ctx=self,
    )
except Exception:
    logger.debug("memo cache freshness-aware lookup failed for %s", ref, exc_info=True)
    return None
if latest is None:
    return None
output, _created_at = latest
if not isinstance(output, dict):
    return None
```
Replace with:
```python
try:
    latest = self.latest_memo_for_node(root, workflow_path=self.workflow_path)
except Exception:
    logger.debug("memo cache freshness-aware lookup failed for %s", ref, exc_info=True)
    return None
if latest is None:
    return None
output, _created_at = latest
```
The `isinstance(output, dict)` check is now inside `latest_memo_for_node`, so the caller no longer repeats it.

In `_resolve_from_memo_in_workflow` (currently around line 409-442), apply the same transformation. The caller now passes the parametric workflow_path:
```python
try:
    latest = self.latest_memo_for_node(root, workflow_path=workflow_path)
except Exception:
    logger.debug("memo cache freshness-aware lookup failed for %s in %s", ref, workflow_path, exc_info=True)
    return None
if latest is None:
    return None
output, _created_at = latest
```

### E.4 — Delete `token_estimation._memo_output_for_freshness_check`

In `src/pflow/core/prompt_cache_analysis/token_estimation.py`, delete the function at lines 612-649.

### E.5 — Update `token_estimation.py` callers

**Call site 1: `_llm_usage_field_from_memo`** (around line 600). Verified fact: the function signature is `ctx: AnalysisContext | None` (NOT `AnalysisContext`). The `ctx=None` branch is reachable in practice — preserve it.

Current code:
```python
output = _memo_output_for_freshness_check(memo_cache, node_id, workflow_path=workflow_path, ctx=ctx)
```

Replace with (the `ctx=None`-aware primary form):
```python
if ctx is not None:
    latest = ctx.latest_memo_for_node(node_id, workflow_path=workflow_path)
    output = latest[0] if latest is not None else None
else:
    # ctx-less fallback: no freshness check possible without ctx.
    # Read the latest memo entry directly with the isinstance-dict guard.
    result = memo_cache.get_latest_for_node(node_id, workflow_path=workflow_path)
    output = result[0] if (result is not None and isinstance(result[0], dict)) else None
```

This mirrors the rewire applied in E.5 step 2 below. Both call sites of the deleted `_memo_output_for_freshness_check` use the same `if ctx is not None / else` pattern. The `ctx=None` branch reads the memo directly with the isinstance guard but skips the freshness machinery (no `predicted_cache_keys` lookup, no `stale_memo_*` mutation) because no `ctx` means no machinery is reachable.

**Call site 2: `_latest_value_for_ref` ctx=None branch** (around line 728). The surrounding function has a `ctx=None` legacy branch that's load-bearing for ~20 test sites. **DO NOT remove the branch.** Rewire only its memo lookup.

Current code in the `ctx is None` branch:
```python
output = _memo_output_for_freshness_check(memo_cache, root, workflow_path=workflow_path, ctx=None)
```

Replace with (the ctx=None path structurally cannot do a freshness check; just read the latest memo directly):
```python
# ctx=None branch: no freshness check possible without ctx.
# Read the latest memo entry directly; preserve isinstance-dict guard.
result = memo_cache.get_latest_for_node(root, workflow_path=workflow_path)
output = result[0] if (result is not None and isinstance(result[0], dict)) else None
```

The behavior preserved: with `ctx=None`, no freshness check happens, no `stale_memo_*` mutation occurs. This was already true in the prior code; the new form makes it explicit.

### E.6 — Sanity-check `_PREDICTION_SKIPPED` references

After E.4, `_PREDICTION_SKIPPED` is no longer referenced in `token_estimation.py`. Confirm:
```bash
grep -n "_PREDICTION_SKIPPED" src/pflow/core/prompt_cache_analysis/token_estimation.py
```
Expected: zero hits. The current references in `token_estimation.py` are all INSIDE the deleted `_memo_output_for_freshness_check` function (lines 621 lazy import + 634 sentinel comparison), and there is no top-level import to remove — the function-body lazy import goes away with the function. If the grep returns hits, investigate (likely a copy-paste survived); otherwise no cleanup action is needed.

`_PREDICTION_SKIPPED` remains exported from `context.py` (in `__all__`) and consumed by `stages/discrepancy/predict.py`, `stages/discrepancy/diagnose.py`, and 3 test sites — all outside `token_estimation.py`. Do not touch those.

### E.7 — Phase E verification gate

```bash
# Same-drift harness:
cd .taskmaster/tasks/task_159/baseline
PATH="$PWD/../../../../.venv/bin:$PATH" bash verify.sh
# Expected: same 7 drifted cases. Memo freshness machinery byte-identical;
# the only difference is which object owns it.

# Targeted memo/staleness tests:
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_cache_analysis_analyze.py -v -k "memo or stale or freshness or prediction" -x
# Expected: all pass.

# token_estimation tests:
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_cache_analysis_token_estimation.py -v
# Expected: all pass — the ctx=None branch survives intact.

# Full sandbox-safe pytest:
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 --doctest-modules \
    --ignore=tests/test_nodes/test_llm/test_llm_integration.py -m "not e2e" \
    -k 'not test_dry_run_json_mode_emits_no_stderr and not test_litellm_not_imported_by_cli_main and not test_progress_streams_before_downstream_nodes_complete'

HOME=/private/tmp/pflow-test-home .venv/bin/mypy
HOME=/private/tmp/pflow-test-home .venv/bin/deptry src
HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a

# File shape:
wc -l src/pflow/core/prompt_cache_analysis/context.py
# Expected: ~525 LOC (net ~wash — method body equivalent to deleted function).

wc -l src/pflow/core/prompt_cache_analysis/token_estimation.py
# Expected: ~600 LOC (down from ~640 after Phase D; ~40 LOC eliminated).

# Symbol-gone check:
grep -rn "def _memo_output_for_freshness_check\|def _latest_memo_for_freshness_check" src/pflow/core/prompt_cache_analysis/
# Expected: zero hits — both module-level helpers are gone.

# Method-present check:
uv run python -c "
from pflow.core.prompt_cache_analysis.context import AnalysisContext
assert hasattr(AnalysisContext, 'latest_memo_for_node'), 'method missing'
print('OK')
"
```

### E.8 — Phase E commit message

```
Polish E: AnalysisContext.latest_memo_for_node() method

Promote the module-level _latest_memo_for_freshness_check
(context.py) to a method on AnalysisContext. The freshness machinery
(predicted_cache_keys lookup, stale_memo_skipped / stale_memo_uncheckable
mutation) consumes self-state; an instance method is the right shape.

Delete token_estimation._memo_output_for_freshness_check — it was a
mirror with trivial behavioral deltas (different return shape, different
exception-catching location). Its production caller now uses
ctx.latest_memo_for_node(...).

The _latest_value_for_ref ctx=None branch (legacy test compatibility,
~20 test sites depend on it) survives — its memo lookup is rewired to
memo_cache.get_latest_for_node directly, since ctx=None structurally
disables the freshness check.

token_estimation.py: ~640 → ~600 LOC.

Zero behavior change: baseline harness reports same 7 drifted cases.
```

---

## Phase F — Documentation + final verification (~30 minutes)

### F.1 — Update `src/pflow/core/prompt_cache_analysis/CLAUDE.md`

In the Module Structure tree near the top, ADD `per_call_pipeline.py` AND UPDATE the existing `row_builder.py` comment so it reflects the post-move scope. Find the existing `stages/` subtree (currently lists `row_builder.py`, `warnings.py`, `suggestions.py`, etc.) and apply two changes:

```
    ├── row_builder.py          # PerCallRow construction primitives (row + IR helpers; orchestration moved out)
    ├── per_call_pipeline.py    # multi-stage orchestrator: rows + warnings + cross-workflow attachment
```

Place `per_call_pipeline.py` directly under `row_builder.py`. The implementing agent reads the current file to confirm exact indentation/format and matches it.

In the Pipeline section (around lines 103-115), update step 4:

Before:
```
4. Build per-call rows through `stages.row_builder`.
```

After:
```
4. Build per-call rows through `stages.per_call_pipeline._build_per_call_rows_and_warnings`.
```

In the "Where To Add A New Feature" table (around lines 244-262), add a new row immediately after the existing row about per-call row construction (or insert at the matching alphabetical position):

```
| Change per-call pipeline orchestration (row + warning + cross-workflow assembly) | `stages/per_call_pipeline.py` |
```

Keep the existing row about row primitive construction unchanged; the two rows now distinguish the orchestration layer from the row-construction primitives.

### F.2 — Update `context.py` module docstring

Edit `src/pflow/core/prompt_cache_analysis/context.py`. The module docstring (lines 1-25) currently lists three load-bearing methods. Add `latest_memo_for_node` as the fourth. The current text "Three load-bearing methods consolidate the policy..." becomes "Four load-bearing methods consolidate the policy...", and append a fourth bullet:

```
- :meth:`AnalysisContext.latest_memo_for_node` — read the latest memo
  entry for a node, applying Bundle-6 cache-key freshness comparison
  and mutating ``stale_memo_skipped`` / ``stale_memo_uncheckable``
  accumulators when staleness or skip is detected.
```

### F.3 — Final harness + quality run

```bash
cd .taskmaster/tasks/task_159/baseline
PATH="$PWD/../../../../.venv/bin:$PATH" bash verify.sh 2>&1 | tee /tmp/baseline-post-polish.log

# Drift list diff:
diff <(grep -A100 'drifted cases:' /tmp/baseline-pre-polish.log | head -10) \
     <(grep -A100 'drifted cases:' /tmp/baseline-post-polish.log | head -10)
# Expected: empty diff (same 7 case names).

HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 --doctest-modules \
    --ignore=tests/test_nodes/test_llm/test_llm_integration.py -m "not e2e" \
    -k 'not test_dry_run_json_mode_emits_no_stderr and not test_litellm_not_imported_by_cli_main and not test_progress_streams_before_downstream_nodes_complete' 2>&1 | tail -3
# Expected: pass count ≥ 7106.

HOME=/private/tmp/pflow-test-home .venv/bin/mypy
HOME=/private/tmp/pflow-test-home .venv/bin/deptry src
HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a

# Final metrics:
grep -rn "from pflow.core.prompt_cache_analysis.*import _" tests/ --include="*.py" | wc -l
# Expected: ≤ 58.

uv run python -c "import sys; import pflow.core.prompt_cache_analysis; assert 'litellm' not in sys.modules; print('OK')"
```

### F.4 — Final commit message

```
Polish F: docs + final verification

Update prompt_cache_analysis/CLAUDE.md:
- File tree includes stages/per_call_pipeline.py.
- Pipeline step 4 points to per_call_pipeline._build_per_call_rows_and_warnings.
- "Where to add a new feature" table distinguishes pipeline
  orchestration from row primitive construction.

Update context.py module docstring to list the new
AnalysisContext.latest_memo_for_node method alongside the existing
three load-bearing context methods.

Zero behavior change.
```

---

## Edge cases the implementing agent must verify

1. **`_extract_declared_chunks` and `_detect_candidate_subsets` location.** Phase C's C.1 decision is that BOTH stay in `row_builder.py`. Verify their current home before relying on this:
   ```bash
   grep -rn "def _extract_declared_chunks\|def _detect_candidate_subsets" src/pflow/core/prompt_cache_analysis/
   ```
   Both should be defined in `row_builder.py`. `per_call_pipeline.py` imports them from there. Do NOT move them — the C.1 decision is final, even though the architecture-review listed them as candidates. The fix is "minimal surface area": only the orchestrator and its result dataclass move.

2. **`_build_call_counts_by_node` location.** Plan B Phase 6 moved it to `trace_loading.py`. Verify:
   ```bash
   grep -n "def _build_call_counts_by_node" src/pflow/core/prompt_cache_analysis/
   ```
   Whatever module owns it, `per_call_pipeline.py` imports from there.

3. **Test files that reach into the moved orchestrator symbols.** Sweep in Phase C step C.5:
   ```bash
   grep -rn "stages.row_builder import.*_PerCallRowsResult\|stages.row_builder import.*_build_per_call_rows_and_warnings\|stages.row_builder import.*_extract_declared_chunks\|stages.row_builder import.*_detect_candidate_subsets" tests/ --include="*.py"
   ```
   Re-target each hit to `stages.per_call_pipeline` (or split into two import statements if other row_builder symbols are imported on the same line).

4. **`tokenize_prompt_region` diff-check before D.2 collapse.** Run the visual diff command in D.1. If any public function diverges from its private sibling beyond the projection-mode flag (e.g., extra exception handling, a different default), narrow the collapse — keep that public's body as-is.

5. **`_PREDICTION_SKIPPED` import direction.** Phase E may make `token_estimation.py`'s only reference go away. Verify post-E:
   ```bash
   grep -n "_PREDICTION_SKIPPED" src/pflow/core/prompt_cache_analysis/token_estimation.py
   ```
   If zero hits, remove any top-of-file `from .context import _PREDICTION_SKIPPED` lines.

6. **`isinstance(output, dict)` guard semantics.** Phase E moves the guard into `latest_memo_for_node`. Two prior implementations had different placements:
   - `context._latest_memo_for_freshness_check` legacy branch: guarded.
   - `context._latest_memo_for_freshness_check` modern Bundle-6 branch: NOT guarded (callers re-checked).
   - `token_estimation._memo_output_for_freshness_check`: guards every return.
   The new method applies the guard to BOTH branches. This is the union of guarantees — strictly more conservative than either prior implementation. The harness catches any regression.

   **Diagnostic hint if Phase E fails the harness:** the new uniform `isinstance` guard is the prime suspect. If the harness reports new drift after E and the drift involves memo-source rows, temporarily remove the `isinstance(output, dict)` check from the modern Bundle-6 branch (keep it in the legacy branch and at the method exit) and re-run. If the drift disappears, the production code is relying on a non-dict memo output flowing through somewhere; investigate before committing.

   Phase E.3 also includes a small simplification: the callers `_resolve_from_memo` and `_resolve_from_memo_in_workflow` previously re-checked `isinstance(output, dict)` after calling the helper. The new code drops that caller-side check because `latest_memo_for_node` guarantees `dict` output. **Apply the simplification to BOTH callers**, not just `_resolve_from_memo`. The Phase E.3 example code shows only one — extend it.

7. **Sandbox environment.** Per the Plan B progress logs, the sandbox does not run `uv run` or `make test` reliably. Use the documented `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest ...` form throughout. The Task 159 baseline harness needs `PATH="$PWD/../../../../.venv/bin:$PATH"` prefix from the harness directory.

---

## Definition of done

1. **Behavior:** Task 159 baseline harness reports `80 passed, 7 drifted, 0 harness errors` with the same 7 case names as the pre-polish snapshot. ANY new drift name is a failure.

2. **Private-symbol leakage:** `grep -rn "from pflow.core.prompt_cache_analysis.*import _" tests/ --include="*.py" | wc -l` returns ≤ 58 (down from 63).

3. **Cycle elimination:** `row_builder.py` has zero function-body imports from `cross_workflow` / `warnings`. The new `stages/per_call_pipeline.py` has its imports at module top.

4. **`token_estimation.py` LOC reduction:** ≥ 100 LOC removed from wrapper collapse + ≥ 30 LOC from memo helper deletion. Net target: ≤ 600 LOC (down from 747).

5. **Public API stability:** All 4 `tokenize_prompt_region*` functions importable at the same paths; `__all__` membership preserved. `render_text(analysis, all_rows=...)` still works for existing callers; `section=` is additive.

6. **Documentation:** `rendering/CLAUDE.md` exists and lists the 6 stable substrate symbols. `prompt_cache_analysis/CLAUDE.md` references it and distinguishes `per_call_pipeline.py` from `row_builder.py` in the "Where To Add A New Feature" table.

7. **Quality gates pass:** `mypy`, `deptry src`, `pre-commit run -a` all pass.

8. **Litellm import cheapness:** `uv run python -c "import sys; import pflow.core.prompt_cache_analysis; print('litellm' in sys.modules)"` prints `False`.

---

## Critical files referenced

Production:
- `src/pflow/core/prompt_cache_analysis/__init__.py`
- `src/pflow/core/prompt_cache_analysis/analyze.py`
- `src/pflow/core/prompt_cache_analysis/context.py`
- `src/pflow/core/prompt_cache_analysis/token_estimation.py`
- `src/pflow/core/prompt_cache_analysis/stages/row_builder.py`
- NEW: `src/pflow/core/prompt_cache_analysis/stages/per_call_pipeline.py`
- `src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py`
- `src/pflow/core/prompt_cache_analysis/stages/warnings.py`
- `src/pflow/core/prompt_cache_analysis/rendering/text.py`

Tests:
- `tests/test_core/test_cache_analysis_analyze.py` (5 `_render_summary` migrations + sweep for moved-symbol imports)
- `tests/test_core/test_cache_analysis_token_estimation.py` (regression coverage)
- `tests/test_core/test_cache_analysis_renderers.py` (no change — 7 leaf-formatter sites stay as documented substrate)

Documentation:
- `src/pflow/core/prompt_cache_analysis/CLAUDE.md` (Pipeline step 4 + "Where To Add A New Feature" + file tree)
- NEW: `src/pflow/core/prompt_cache_analysis/rendering/CLAUDE.md`

Verification harness:
- `.taskmaster/tasks/task_159/baseline/verify.sh`

---

## Implementing-agent reminders

1. **Each phase commits independently.** Don't squash; each phase boundary must pass the harness on its own.
2. **Read the file before editing it.** Plan B's progress logs explicitly note that file-state assumptions stale between phases — verify `grep`/`wc` outputs before relying on line numbers in this plan.
3. **The harness is the oracle.** If `bash verify.sh` reports the same 7 drifted cases as `/tmp/baseline-pre-polish.log`, the change is correct regardless of unit-test output. New drift = real regression.
4. **No new tests in this refactor.** Existing tests validate. New tests would expand scope. (Phase B documents existing tests' implicit contract — that's documentation, not new tests.)
5. **No behavior changes anywhere.** Pure structural relocation. If a test fails with a behavior difference, STOP — that's a regression, not a fixture migration.
6. **No commits requested by the user yet.** Phase boundaries are commit-ready snapshots; don't push to remote.
7. **Phase order is important.** Recommended sequence: A → B → C → D → E → F.
   - A is independent of all others.
   - **B should COMMIT AFTER A** even though there's no code-level dependency. The new `rendering/CLAUDE.md` claims "Five legacy test sites have migrated to the public form" — that statement is only true after A ships.
   - C is independent of A/B/D/E (touches different files).
   - D before E (no hard dependency, but the LOC and `_PREDICTION_SKIPPED` cleanup steps assume D's file shape).
   - F is documentation; it MUST run last to reflect the post-polish state.
