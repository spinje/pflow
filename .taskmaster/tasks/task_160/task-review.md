# Task 160 Review: Prompt Cache Analysis Architectural Refactor

## Metadata

- **Implementation window**: 2026-05-21 → 2026-05-26 (three work streams; see provenance note).
- **Branch**: `refactor/cache-analysis-refactor` (committed; not yet merged to `main` as of this review).
- **PR URL**: none yet.
- **Provenance / trust boundary**: This review was *not* written by the agent who
  typed the code. It is synthesized from the complete implementation record —
  `implementation/implementation-plan{,-b,-c}.md`, `implementation/progress-log{,-b,-c}.md`,
  `implementation/retrospective-and-future-improvements.md`,
  `starting-context/braindump-2026-05-21-handoff-after-retrospective.md` — plus direct
  verification of the end-state against the live code. Where a claim is from the
  written record rather than re-verified in code, it is still reliable (the logs are
  detailed and cross-consistent), but a future agent modifying load-bearing behavior
  should re-confirm against the harness, not against this prose.

## Post-rebase baseline refresh (2026-05-27)

After the PR was opened, the branch was **rebased onto current `main`** (which had
advanced 14 commits, several touching the same area — the Gemini per-model
prompt-cache threshold fix #432/#433, the `cost_usd`/`ensure_model_priced` fix
#423/#424, a litellm bump). The rebase applied with no conflicts; the two riskiest
semantic merges were verified to survive (main's `llm_capabilities.py` is byte-identical
to `origin/main`; main's `ensure_model_priced(model)` call carried into the *renamed*
`prompt_cache_analysis/cost_estimation.py`). This changes the harness guidance below:

- **Zero new drift vs. main, proven by comparison.** Running the Task 159 harness on
  the rebased branch and on plain `origin/main` and diffing the drift sets: the
  refactor introduces **zero new drift**, and it incidentally *fixes*
  `01-parser-errors/01-empty-cache-block` (drifts on `main`, passes here — the
  pre-existing incidental fix first noted in Plan A's verification). Every other drift
  was *shared* with `main`, i.e. caused by merged feature PRs, not by this work.
- **Stale baselines regenerated → harness now fully green.** The shared drifts were
  stale expected-outputs vs. behavior already merged to `main`: Gemini thresholds
  (#432/#433) → `10-live-recordings/05`; autoload IR-hash filenames →
  `03-analyze-cache-modes/07,08,09`; prewarm wording → `04-warning-catalog/23,23b`;
  guide text → `12-real-world-lyrics-generator/04`. Regenerated via
  `baseline/regenerate.sh <case>`. The harness now reports **`87 passed, 0 drifted, 0
  harness errors`** on this branch.

**Gotcha for future regeneration:** `regenerate.sh` captures whatever the subprocess
writes to stderr, and a `uv`-triggered rebuild leaks `Building pflow-cli` / `Installed
1 package` lines into `expected-stderr.txt` — it contaminated
`03-analyze-cache-modes/07`'s stderr on first regen, and `normalize.py` does not strip
it. Always diff regenerated `expected-stderr.txt` for build noise and revert it (that
file should normally be empty); regenerate with an already-built venv to avoid it.

> This supersedes the "7 known drifts" guidance below, which describes the historical
> *pre-rebase* state. On this branch, GREEN now means **0 drifted**.

## Executive Summary

A 8,570-LOC `analyze.py` monolith (in `core/cache_analysis/`) was decomposed into a
modular package, `core/prompt_cache_analysis/` (~16,200 LOC across 29 source files),
with the orchestrator reduced to a thin pipeline and analysis/rendering split along
earned seams. **Zero user-facing behavior change** — proven byte-for-byte by the
Task 159 regression harness throughout. The refactor shipped in three waves: a
structural decomposition + package rename, then a "deepening" of six earned seams,
then a polish pass on three residual frictions.

## Implementation Overview

### What Was Built

The package today (verify against `prompt_cache_analysis/CLAUDE.md`, which is the
living self-description):

- **Thin orchestrator** — `analyze.py` (~540 LOC) reads as a 7-step pipeline; helpers
  live with the stage that owns them; no stage imports privates from `analyze.py`.
- **Leaf vocabulary** — `types.py` (~930) owns public dataclasses + projection
  algebra + `PerCallRow`; imports nothing analyzer-internal. Types are importable
  *only* from `types.py` (`analyze.__all__ == ["analyze"]`).
- **Stages** — `stages/`: `per_call_pipeline`, `row_builder`, `warnings`,
  `suggestions`, `fragmentation`, `partial_declarations`, `cross_workflow`, `summary`,
  `discrepancy/{predict,diagnose}`. One concern + one entry point each.
- **Rendering** — `rendering/`: `text`, `json`, `views`, `cross_workflow_edits`,
  `summarize`, `traces_list`. Read-only projections of `CacheAnalysis`.
- **Resolution policy home** — `context.py::AnalysisContext` owns ref resolution
  (root + workflow-path-parametric forms) and memo freshness (`latest_memo_for_node`).
- **Disambiguating names** — package renamed `cache_analysis → prompt_cache_analysis`;
  the walker renamed `cross_workflow.py → sub_workflow_walker.py` (no filename
  collision); `template_resolver()` deduplicated to one home (`context.py`).

### Deviations from the original spec (important)

The original `task-160.md` set an `analyze.py ≤ 350 LOC` target. **It landed at ~540
and that was deliberately accepted.** `_run_full_validation`, trace-misalignment
recovery, and per-call visibility-note glue are orchestration with single call sites;
moving them only to satisfy a line count was judged worse than keeping them. The
orchestrator is "thin" in *interface* (one entry point), which is the property that
mattered — not minimal in line count. A private-symbol-test-import target of ≤60 was
likewise treated as soft; it landed at 58.

> The `task-160.md` spec has since been rewritten (2026-05-27) to describe the
> achieved end-state rather than the original aspirational targets. Read that for the
> *what*; read this document for the *how and why*.

## Files: the high-signal map

New files (didn't exist before): `types.py`, `trace_loading.py`, `context.py` usage
expanded, the entire `stages/` and `rendering/` trees, `stages/per_call_pipeline.py`,
`rendering/cross_workflow_edits.py`, `tests/shared/cache_analysis_fixtures.py`, and
two docs (`stages/discrepancy/CLAUDE.md`, `rendering/CLAUDE.md`).

Renamed: `cross_workflow.py → sub_workflow_walker.py` and its test file. Deleted:
`padding_advisor.py` (folded into `stages/suggestions.py`).

External consumers updated (the integration surface — see below): `cli/commands/analyze_cache.py`,
`execution/runner.py`, `mcp_server/services/execution_service.py`,
`runtime/engine/engine.py`, `nodes/llm/llm.py`, `core/workflow/data_flow.py`, plus
`pyproject.toml` (ruff per-file-ignore glob) and several `CLAUDE.md` files.

## The single most important thing a future agent must know: the verification oracle

**The Task 159 baseline harness is the authoritative proof of zero behavior change.
Use it. Trust it over your intuition and over unit tests.**

```bash
cd .taskmaster/tasks/task_159/baseline
PATH="$PWD/../../../../.venv/bin:$PATH" bash verify.sh
```

- **HISTORICAL (pre-rebase) — superseded by the Post-rebase baseline refresh above;
  the branch now runs `87 passed, 0 drifted`.** Before the rebase + baseline refresh,
  GREEN meant exit 1 with exactly these 7 drifted cases (pre-existing staleness from
  feature PRs #390/#392/#396/#405/#412/#416/#418, *not* this refactor):
  - `03-analyze-cache-modes/07-autoload-prefers-success`
  - `03-analyze-cache-modes/08-autoload-failed-only`
  - `03-analyze-cache-modes/09-autoload-rejected-names-file`
  - `04-warning-catalog/23-cache.batch-prewarm-lower-bound-recommended`
  - `04-warning-catalog/23b-cache.batch-prewarm-lower-bound-recommended-text`
  - `12-real-world-lyrics-generator/04-guide-auto-detect`
  - `15-run-flag-interactions/03-report-with-only`
- **RED = any *new* drift case name.** That is a real regression.
- **`0 passed, 87 drifted` is NOT real drift** — it is the signature of a broken
  Homebrew `uv`/`hatchling` environment where every case fails at subprocess startup.
  The first implementing agent misread this as "harness invalid" across six progress-log
  entries and shipped Plan A without authoritative verification. A later agent ran it
  outside the broken environment and proved zero behavior change. **Lesson: when tooling
  looks uniformly broken, discriminate environment failure from tool failure before
  declaring the tool invalid — uniform failure is itself the tell.**

### Sandbox testing reality

`make test` / `uv run` are unreliable in the sandbox (subprocess panics). Use:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py -m "not e2e" \
  -k 'not test_dry_run_json_mode_emits_no_stderr and not test_litellm_not_imported_by_cli_main and not test_progress_streams_before_downstream_nodes_complete'
```
The three excluded `-k` tests are documented sandbox/tooling failures, not product
failures. `mypy`, `deptry src`, and changed-file `pre-commit` work; full
`pre-commit run -a` fails on unrelated hidden `.codex`/`.agents` metadata permissions.

### A baseline fixture trap

`04-warning-catalog/09{b,c,d,e}/trace.json` were **untracked via `.gitignore`** because
the generator bakes an absolute worktree path into `workflow_path` on every
regeneration. `git status` may show them as `D` — that is expected; they regenerate on
the next harness run. `--from-trace` treats `workflow_path` as *informational only*, so
the absolute path has no behavioral effect (only display, which `normalize.py` redacts).
Do not "fix" these by re-tracking them.

## Integration Points & Dependencies

### Outgoing (this package → others), strictly one-way

- `prompt_cache_analysis → core/{prompt_cache,prompt_refs,llm_capabilities,cache_overlap,cache_ttl}.py`.
  **Never reverse this.** `cache_overlap.py` keeps its own copies of `_batch_aliases` /
  `_is_batch_scoped_ref` *by design* to preserve the one-way `analyzer → data_flow`
  edge; consolidating them would create a back-import.
- Discrepancy prediction → runtime substrate (`compile_workflow`, `plan_node`,
  `create_planner_shared`, `TraceTree`) — **all lazy** (see lazy-import policy below).

### Incoming (others → this package), via the stable public surface only

```python
from pflow.core.prompt_cache_analysis import (
    JSON_FORMAT_VERSION, CacheAnalysis, TraceListEntry, analyze,
    list_traces_for_workflow, render_json, render_text, summarize, summarize_from_analysis,
)
```
Consumers: `cli/commands/analyze_cache.py` (also direct `rendering.traces_list`,
`trace_loading.list_traces_for_workflow`), `execution/runner.py`,
`mcp_server/services/execution_service.py`, `runtime/engine/engine.py` (below-min
detector, context, token estimation, warning catalog), `nodes/llm/llm.py`,
`core/workflow/data_flow.py` (`warning_catalog.make_diagnostic`).

### Runtime trace contract (the producer/consumer seam)

The analyzer reads engine-written trace fields: `event["cache_source"]`,
`event["cache_key"]`, `event["cache_age_sec"]`, `trace["workflow_path"]`. Changing
what the engine writes here without updating `trace_loading.py` / `discrepancy` is a
silent break — there is no type checker across this seam.

## Architectural Decisions & Tradeoffs

### Load-bearing decisions (with the cycle traps that forced them)

1. **`_RowCrossWorkflowCandidate` lives in `types.py`, not `stages/cross_workflow.py`.**
   It is referenced by both `row_builder` (via a result-dataclass field) and the
   cross_workflow producers. Putting it in the stage would make
   `row_builder → cross_workflow` while `cross_workflow → row_builder` already exists →
   cycle. The leaf is the cycle-breaker.

2. **`_build_per_call_rows_and_warnings` lives in `stages/per_call_pipeline.py`, not
   `row_builder.py`.** It is the multi-stage seam (rows + warnings + cross-workflow);
   living in `row_builder` forced two function-body lazy imports to mask a real
   `row_builder → cross_workflow/warnings` module-init cycle. The fix moved *the
   orchestrator*, not the shared helpers — extracting only `_node_inputs` does **not**
   break the cycle (three sibling helpers ride the same back-edge). `row_builder.py` now
   has zero function-body sibling imports; the stage graph is a DAG.

3. **`rendering/__init__.py` is lazy.** A normal stage import created
   `analyze → stages.cross_workflow → rendering.cross_workflow_edits → rendering.__init__
   → summarize → analyze`. Lazy package re-exports keep `from ...rendering import
   render_text` source-compatible while letting the stage import the render seam.
   `format_grouped_body_block` is deliberately **not** re-exported from
   `rendering/__init__.py` (the analysis stage is its only consumer; re-exporting would
   make an internal seam look public).

4. **Cost API helpers dropped their underscore prefix** (`aggregate_no_cache_cost`,
   `aggregate_with_cache_projection`, `row_body_only_cost`,
   `row_first_run_with_cache_cost`, `pricing_from_dict`) to match the already-public
   `__all__`. Internal callers import the *module* (`from .. import cost_estimation`)
   not the function, because tests monkeypatch `cost_estimation.get_model_pricing` and
   module-level lookup preserves that seam.

### Lazy-import policy (NON-NEGOTIABLE invariant)

`import pflow.core.prompt_cache_analysis` **must leave `litellm` absent from
`sys.modules`.** `--dry-run` and other LLM-free CLI paths import this package and must
not pay ~700ms of LiteLLM startup. These imports are *policy*, not accident — do not
"tidy" them to module top:
- `context.py::template_resolver()` (lazy `TemplateResolver`).
- `stages/discrepancy/predict.py` (`compile_workflow`, `plan_node`, `create_planner_shared`).
- `diagnose.py` (`TraceTree`); `trace_loading.py` (`MemoizationCache`).
- `cost_estimation.py` (`import litellm`).

Guard test exists; re-run it after any import change:
`assert 'litellm' not in sys.modules` after importing the package.

### Verified non-issues — do NOT "fix" these

- Do not extract `projection_algebra.py` from `types.py` (one consumer path).
- Do not create `_ir_helpers.py` (the 5 IR accessors are heterogeneous, placed with
  their primary consumer).
- Do not consolidate `cache_overlap.py`'s `_batch_aliases`/`_is_batch_scoped_ref`.
- Do not section-split `rendering/text.py` (~2,450 LOC, cohesive — navigability work,
  not depth work).
- Do not promote the documented private test surfaces to public.

## The PerCallRow contract (a sharp edge)

`PerCallRow.__post_init__` is **intentionally minimal**. It derives
`cached_now_tokens_estimated` from (A) trace cache-token splits
(`cache_creation_input_tokens` + `cache_read_input_tokens`) and (B) a trace-backed
declared-cache fallback to `cacheable_tokens_estimated`. **Both branches are reached in
production — preserve them.** The removed legacy block synthesized the four projection
objects from the `cacheable_tokens_estimated` scalar; that path was unreachable in
production and is gone.

Consequence for tests: rows are built via `tests/shared/cache_analysis_fixtures.make_per_call_row`,
whose projection fields default to `not_applicable_projection()`. **If a test asserts on
rendered `ready`/`upside`/`cached_now`/`ratio` cells, it must pass explicit
`CacheProjection` instances** — the defaults render "—". A parity-guard test
(`TestMakePerCallRowProductionParity`-style) asserts the helper's shape matches
production's `_build_per_call_row`; keep it green so the fixture can't silently drift.

## AnalysisContext resolution: the threading invariant

`resolve_ref_value_in_workflow` / `resolve_ref_value_for_projection_in_workflow` /
`latest_memo_for_node` take `workflow_path` as a *parameter*. The memo freshness check
mutates `stale_memo_skipped` / `stale_memo_uncheckable` keyed on
`(workflow_path, node_id)`. **It must key on the *passed* `workflow_path`, never
`self.workflow_path`** — passing the wrong one silently mis-attributes staleness.
Consumers only `len()` these sets, which is why the mis-attribution is silent.

### The Phase-9 production bug (regression-test rationale)

`resolve_ref_value_for_projection_in_workflow` originally failed to thread
`cw_result.irs_by_workflow` into the workflow-scoped resolver. Result: a parent
node-output ref like `${creative.direction}` could be resolved from a colliding
*root analysis parameter* named `creative`. Found by `review-silent-failures` +
`review-feature-interactions`. Fix: pass `irs_by_workflow` so the workflow-input branch
distinguishes a declared input from a node-output root. There is a regression test
proving parent node-output refs ignore colliding root params — do not delete it.

## Testing Implementation

- **The harness is the regression net.** Unit tests + structural greps are supporting
  evidence; the Task 159 harness is proof.
- **Health metric: private-symbol test imports.** Currently 58. Track
  `grep -rn "from pflow.core.prompt_cache_analysis.*import _" tests/ --include="*.py" | wc -l`.
  Growing it re-couples tests to implementation. The retrospective named this the single
  biggest constraint on future refactoring.
- **Documented direct-test surfaces** (rename freely, but update tests in the same
  change; do not promote to public): `stages/discrepancy/CLAUDE.md` lists
  `_predict_node_cache_key`, `_format_dynamic_batches_note`, `_format_fidelity_skip_note`,
  `_format_skipped_workflows_note`. `rendering/CLAUDE.md` lists `_render_summary`,
  `_format_delta_parenthetical`, `_format_cost`, `_cell_calls`, `_indent_message`,
  `_BASELINE_LABELS`. Prefer `render_text(analysis, section="summary")` over importing
  `_render_summary` in new tests.

## Gotchas / silent-failure modes when moving symbols

Symbol relocation in this package has a Task-92-style patch-string silent-failure mode.
When you move a symbol, sweep **all** of these, not just `import` lines:
- `importlib.import_module("...")` string paths (the walker rename touched ~48 sites,
  mostly in `test_cache_analysis_per_id_emission.py`). The string `stages.cross_workflow`
  must NOT be collapsed when renaming the walker `cross_workflow` → use exact-string,
  non-`.stages.` matching.
- `_STAGE_ATTR_MODULES` monkeypatch tuples in the per-id test files — audit whether the
  moved module imports a patched name (`estimate_tokens`, `get_min_cache_tokens`, etc.)
  at module top; if not, no tuple update is needed (this is why `per_call_pipeline`
  needed none).
- `caplog` logger-name strings (`logging.getLogger(__name__)` resolves to the *new*
  module — a moved function's logs appear under the new logger name).
- `sys.modules[...]` keys; `monkeypatch.setattr` target strings.

## Anti-patterns this refactor proved out

- **Rename + restructure in one PR.** Plan A did both (package rename + decomposition)
  in one stream; reviewers had to context-switch between "is the rename complete?" and
  "is the decomposition correct?". For future structural work, split mechanical rename
  from design-heavy restructure into sequential PRs.
- **LOC targets as design constraints.** The original `≤1,100` then `≤350` targets on
  `analyze.py` drove several "where does this belong?" decisions toward "wherever keeps
  the count down" rather than "wherever the concern lives." Depth is an *interface*
  property; size it by responsibility, not line count.

## AI Agent Guidance

### Quick start for related work

1. Read `prompt_cache_analysis/CLAUDE.md` first — it has the module map, the
   two-cache disambiguation table, the runtime trace contract, and a "Where To Add A New
   Feature" table that routes you to the right file.
2. Run the harness before touching anything to capture your baseline drift set.
3. Use the "Where To Add A New Feature" table; respect the one-way dependency to
   `core/` prompt-cache files and the lazy-import policy.

### Common pitfalls

- Hoisting a lazy import → breaks the no-eager-LiteLLM invariant.
- Re-adding projection synthesis to `PerCallRow.__post_init__` → re-introduces the
  removed bridge.
- Resolving a parametric ref with `self.workflow_path` instead of the passed one →
  silent stale-memo mis-attribution.
- Moving a symbol without sweeping `importlib`/`caplog`/monkeypatch strings → tests pass
  while patching nothing (silent).
- Adding a new warning ID to vary wording → warning IDs are a stable contract
  (`warning_catalog.py`); reuse the existing ID for the same condition.

### Test-first when modifying

- Run the Task 159 harness first; then the targeted `tests/test_core/test_cache_analysis_*`
  slice for the area you touch; then the `litellm not in sys.modules` guard; then
  `mypy` + changed-file `pre-commit`.

---

*Synthesized from the Task 160 implementation record (3 plans, 3 progress logs,
retrospective, braindump) and direct end-state code verification.*
