# Retrospective — Task 160 Cache Analysis Refactor

## Context

This document captures architectural critiques of the Task 160 refactor as it shipped. The refactor passes every functional check (zero-behavior-change verified via Task 159 harness, full test suite green, all quality gates pass), so this is **not** a post-mortem of failure. It is an honest application of the [`/improve-codebase-architecture`](.claude/skills/improve-codebase-architecture) skill's criteria to the result, written for the next agent who picks this package up.

**Read first:**
- `.taskmaster/tasks/task_160/task-160.md` — what we set out to do
- `.taskmaster/tasks/task_160/research/architecture.md` — the dependency analysis
- `.taskmaster/tasks/task_160/implementation/progress-log.md` — what actually happened
- `.claude/skills/improve-codebase-architecture/LANGUAGE.md` — the vocabulary used below

**Vocabulary** (from the skill): Module, Interface, Implementation, Depth, Seam, Adapter, Leverage, Locality. The deletion test. "Interface is the test surface."

## Final shape — by the numbers

```
src/pflow/core/prompt_cache_analysis/
  analyze.py                          1,095 LOC  (target was ≤ 1,100)
  types.py                              890 LOC
  trace_loading.py                      914 LOC
  stages/row_builder.py               1,138 LOC
  stages/cross_workflow.py            1,344 LOC  (largest stage)
  stages/suggestions.py                 813 LOC
  stages/warnings.py                    651 LOC
  stages/summary.py                     595 LOC
  stages/discrepancy/predict.py         573 LOC
  stages/fragmentation.py               389 LOC
  stages/partial_declarations.py        352 LOC
  stages/discrepancy/diagnose.py        185 LOC
  stages/__init__.py                      1 LOC
  stages/discrepancy/__init__.py         10 LOC
  rendering/text.py                   2,423 LOC
  (other rendering files)               866 LOC
  (unchanged infra: context, cost_estimation, token_estimation,
   below_min_tokens_detector, cross_workflow.py walker, warning_catalog)
```

Tests importing private symbols from the package: **51 distinct symbols across 59 import sites.** This is the headline architectural smell to address. See insight #2 below.

---

## Insights ranked by impact

### 1. The 1,100-LOC target on `analyze.py` distorted the design

**What we shipped.** `analyze.py` at 1,095 LOC contains:
- `analyze()` orchestrator (~337 LOC, lines 122-458)
- `_build_per_call_rows_and_warnings` + row assembly helpers (~80 LOC)
- `_build_cross_workflow_candidates_by_row` and related (~200 LOC)
- `_build_parameters_by_workflow` + child input resolution (~150 LOC)
- `_detect_per_node_model_drift`, `_row_model_drift` (~80 LOC)
- `_cache_ttl_by_workflow`, `_extract_declared_chunks`, etc. (~50 LOC)
- `_run_full_validation` (~50 LOC)
- 2 private dataclasses (`_PerCallRowsResult`, `_RowCrossWorkflowCandidate`)

**The problem.** The orchestrator's **interface** should be one fact: "calling `analyze(workflow_ir, ...)` produces a `CacheAnalysis`." The 700 LOC below `analyze()` are not orchestration; they are implementation details of how the orchestrator prepares data and assembles rows. Anyone reading `analyze.py` to understand "how does pflow analyze caching?" has to load all of them.

**What the progress log reveals.** Phase 5 deviations were all driven by hitting the LOC target, not by design:
- Shadow warning enrichment → moved to `warnings.py` (it is orchestration glue, not a warning concern)
- Sub-workflow rollup → moved to `summary.py` (it is row-assembly glue)
- `_extract_cache_ttl` → moved to `suggestions.py` (it is IR parsing, used from multiple stages)
- `_total_observed_invocations` → moved to `row_builder.py` (a cross-workflow concern)
- Several batch-tail helpers → `row_builder.py` (could have been in warnings)

Every deviation traded conceptual cleanliness for LOC count. The target was the wrong constraint.

**What would have been better.** The orchestrator's rule should be: **`analyze.py` contains `analyze()` and `_default_memo_cache()`. Nothing else.** Everything `analyze()` calls is either:
- A stage (one entry point, called once)
- A trace helper (in `trace_loading.py`)
- A row/projection helper (in `row_builder.py`)
- A parameter helper (somewhere — see insight #4)

Under that rule, `analyze.py` would land around 400-500 LOC. The package gains one or two more files. The orchestrator becomes a sequencing module — its **Depth** comes from the leverage of a single entry point hiding the entire pipeline, not from absorbing helpers to "make analyze.py thin."

**Cost to fix.** Medium. Most extractions are mechanical. The tricky one is `_build_per_call_rows_and_warnings` — it is the integration point between row construction and warning emission. The cleanest move is probably into `stages/row_builder.py` (since it is row assembly).

---

### 2. Tests test private symbols (51 distinct). "Interface is the test surface" fails.

**Quantified.** Running `grep -rn "from pflow.core.prompt_cache_analysis.*import _" tests/` returns **59 import sites of 51 distinct private symbols** across the test suite. That number is HIGHER than the 29 the original spec measured — the decomposition created more private surface for tests to reach into, not less.

**What the skill says.** "Callers and tests cross the same seam. If you want to test *past* the interface, the module is probably the wrong shape." A test that imports `_predict_node_cache_key`, `_aggregate_and_cap_discrepancies`, `_resolve_value_in_workflow_memo`, etc. is testing past the interface. Three possibilities:
1. The tests are too tightly coupled to implementation
2. The modules' interfaces are wider than they declare
3. Both

In practice it is mostly #1, but each test that imports a private helper is a constraint on refactoring that helper. The cheapest way to verify this: try to rename `_predict_node_cache_key` to `_compute_predicted_key` and watch 5-7 tests fail at import time, not at behavioral assertions. That is the constraint we have not earned.

**Why we didn't tackle it.** The original migration plan had "Phase 4: Test consolidation" with a specific list of fixture factories to consolidate (`_make_analysis` 54 calls, `_row` ~56 calls, `_write_trace` 20 calls). The rewritten plan **dropped this phase entirely** under the "no premature abstraction" rationale. In hindsight, this was a misread of the situation — fixture consolidation is not abstraction, it is honest reuse of fixtures that already exist as scattered local copies.

**What would have been better.** Treat test refactoring as a first-class phase, not an "if we have time" deferred item. The phase would have two parts:
1. **Extend shared fixtures.** `tests/shared/trace_fixture_builder.py` exists and is partially adopted (3/12 files originally). Migrating the 4-5 highest-call-count local factories would remove ~500 LOC of test code AND eliminate ~30 private-symbol imports.
2. **Push tests through the public API.** For each private-symbol import, ask: "what behavior is this test asserting? Can the behavior be exercised through `analyze()` + assertions on `CacheAnalysis`?" If yes, rewrite. If no, the function is part of the module's real Interface and should be made public.

**Cost to fix.** High in test-LOC terms (~1-2k lines of test churn), low in conceptual difficulty. The work parallelizes well across test files. A separate task spec for this is worth writing.

---

### 3. `stages/cross_workflow.py` at 1,344 LOC is doing two jobs

**What we shipped.** The file contains the cross-workflow analytical stage (one entry point: `_build_cross_workflow_findings`) AND ~690 LOC of grouped-projection rendering helpers (`_format_grouped_body_block`, `_format_unmeasurable_grouped_body`, `_format_refactor_grouped_body`, `_format_exact_child_cache_edits`, `_format_per_consumer_input_lines`, etc.).

**The problem.** This was the explicit "don't split now" decision (DD#10 in the spec). The reasoning was: the formatting is "tightly coupled to the candidate data structures." But that is **exactly** the kind of coupling the skill says to break. The formatting helpers produce strings that go into `Diagnostic.context` for downstream rendering. They are not analysis — they are renderer-adjacent helpers that live next to their data producers for convenience.

**Apply the deletion test.** If you delete `_format_grouped_body_block`, does complexity scatter or vanish? It scatters — three different `Diagnostic` constructions would need their own format calls. But that complexity is **rendering complexity**, not **analysis complexity**. The deletion test passes only because formatting and analysis got conflated.

**What would have been better.** Two files:
- `stages/cross_workflow.py` (~650 LOC) — `_build_cross_workflow_findings` + candidate detection + value-flow resolution
- `rendering/cross_workflow_edits.py` (~690 LOC) — all `_format_*` helpers that produce paste-ready cache-block edit text

The seam between them is the `_SubWorkflowCacheGroup` dataclass (currently private to the file). It becomes part of `types.py` (or a new `stages/cross_workflow_types.py` to avoid expanding types.py).

**Cost to fix.** Low to medium. The seam is clean (one dataclass crosses it). The risk is the `_format_*` helpers reach into many other private cross-workflow predicates; check the call graph before splitting.

---

### 4. Shared IR helpers split asymmetrically — a tiny module would be cleaner

**What we shipped.** 5 pure-function IR accessors are spread across two files:
- `stages/row_builder.py` owns `_node_inputs` (called from 6 modules)
- `stages/suggestions.py` owns `_batch_aliases`, `_cache_items`, `_cache_item_names`, `_is_batch_scoped_ref` (called from 3-5 modules each)

**Why we did it.** The plan was driven by "minimize new files." The cycle analysis showed both placements work without import cycles. We picked the modules where each helper has its primary consumer.

**The problem.** The split is asymmetric and hard to remember. A reader who wants `_cache_items` looks in `analyze.py` (not there), then `stages/row_builder.py` (not there — but `_node_inputs` is), then finally finds it in `stages/suggestions.py`. The mental model "shared IR helpers live in {primary consumer}" requires knowing which stage is the primary consumer for each helper.

**Apply "one adapter = hypothetical, two = real."** Five pure functions called from 3-6 modules each, with no behavior difference across callers. That is the textbook case for a shared module. We rejected it as "premature abstraction," but the abstraction has already been earned by usage — it just lives in two awkward homes.

**What would have been better.** `src/pflow/core/prompt_cache_analysis/_ir_helpers.py` (~40 LOC):
```python
"""Pure IR accessor utilities shared across stages.

These read raw IR dicts. They do not depend on AnalysisContext or any
analyzer-domain type. Adding here is fine; growing this file beyond
~100 LOC means a stage probably belongs separately.
"""
def _node_inputs(node): ...
def _batch_aliases(node): ...
def _cache_items(workflow_ir): ...
def _cache_item_names(workflow_ir): ...
def _is_batch_scoped_ref(ref, ...): ...
```

The leading underscore in the filename signals "internal to the package," matching `_PREDICTION_RECOVERABLE_EXCEPTIONS` constant style. The deletion test passes strongly: deleting this file scatters 5 functions across 5+ modules.

**Cost to fix.** Trivial. Move 5 functions, update imports in 6 files.

---

### 5. Two `cross_workflow.py` files at different package levels create navigation friction

**What we shipped.** `prompt_cache_analysis/cross_workflow.py` (the walker, 447 LOC) and `prompt_cache_analysis/stages/cross_workflow.py` (the analytical stage, 1,344 LOC). Both files have the same name; only the directory disambiguates.

**Why we did it.** The migration plan offered both options (rename walker vs leave both). We picked "leave both" as the lower-churn option.

**The problem.** `find . -name cross_workflow.py` returns 2 hits. Mental friction for every reader. The CLAUDE.md has to call out "there are two files with the same name" as a navigation note. The actual disambiguating fact (walker vs analytical stage) is invisible in the filename.

**What would have been better.** Rename the walker to `sub_workflow_walker.py` (the option B from the plan). It is more accurate: the walker walks sub-workflows, it is not "cross_workflow analysis" — that name belongs to the analytical stage. The walker has 4 consumers; the rename is mechanical.

**Cost to fix.** Trivial. One file rename, ~6 import updates.

---

### 6. Rename + restructure should have been two PRs

**What we shipped.** One PR (broken into 7 phase commits) that renamed `cache_analysis` → `prompt_cache_analysis` AND restructured `analyze.py` into stages/rendering.

**The problem.** Two qualitatively different kinds of change in one PR:
- **Rename** — mechanical, low-risk, affects every import in the codebase, easy to verify (grep)
- **Restructure** — design-heavy, requires cycle analysis, affects function placement, hard to verify (need harness)

Reviewers (human or AI) have to context-switch between "is the rename complete?" and "is the decomposition correct?" The progress log entries show the implementing agent had to track both concerns simultaneously, leading to conflated cleanup work (e.g., "restored 4 baseline trace.json files the implementing agent had touched during earlier verification runs").

**What would have been better.** Two PRs in sequence:
1. **PR 1 — Rename only.** `cache_analysis` → `prompt_cache_analysis`. Update `pyproject.toml`, all imports (production + tests + `importlib`/`sys.modules`/`caplog` strings), CLAUDE.md references. ~200 file changes, all mechanical. Easy to review.
2. **PR 2 — Restructure.** Within the renamed package, extract `types.py`, `trace_loading.py`, `stages/`, `rendering/`. ~30 file changes, design-heavy. Harness-verified.

**Cost.** Not fixable now (the work is done). But: **for future similar refactors, default to splitting rename and restructure.** It is the same total work spread across two reviewable units.

---

### 7. `_template_resolver()` helper duplicated in 3 stage files

**What we shipped.** Each of `stages/row_builder.py`, `stages/warnings.py`, `stages/cross_workflow.py` has:
```python
def _template_resolver() -> Any:
    from pflow.runtime.template_resolver import TemplateResolver
    return TemplateResolver
```

**Apply "two adapters = real seam."** Three identical 3-line helpers across three files. That is real duplication, not hypothetical.

**Why it is acceptable in this case.** The duplication is 9 lines total and the helper has no logic. The "fix" is to put it somewhere shared, which means either:
- `_ir_helpers.py` (per insight #4) — fine, also picks up the IR accessors
- `__init__.py` private helper — uglier
- A new `_lazy.py` — over-engineering

If insight #4 is acted on, fold `_template_resolver()` into `_ir_helpers.py` (or rename it to `_internal.py`). Otherwise leave it.

**Cost to fix.** Trivial, but only worth doing alongside insight #4.

---

### 8. `analyze.py` keeps several `_*` helpers that exist only to satisfy single-orchestrator-line calls

**What we shipped.** Helpers like `_resolve_first_batch_item` (lines 673-706), `_resolve_first_trace_batch_item` (lines 707-721), `_unchecked_parent_memo_roots` (lines 652-672) are called once from `_build_parameters_by_workflow`. They live in `analyze.py` because their caller stayed in the orchestrator.

**The pattern.** A helper that exists to break up one parent function for readability. Each is small (10-30 LOC). Together they make `analyze.py` look bigger than it is.

**Apply the deletion test.** Inline `_resolve_first_batch_item` into its single caller. Does complexity scatter? No — it stays in one function. The helper exists for paragraph-level readability, not for module-level reuse.

**What this means.** Either:
- Inline them (analyze.py shrinks, single caller becomes longer but no less clear)
- Keep them (analyze.py reads cleanly as "orchestrator + parameter resolution helpers + ...")

Neither is wrong. The current state is fine. Flag for future review: if insight #1 is acted on and parameter resolution moves to its own module, these helpers move with it.

---

## What I would NOT change

These were genuine wins and should be preserved:

1. **`types.py` as a leaf module.** Every module in the package can import from it; it imports from nothing. The cleanest seam in the package.

2. **The discrepancy `predict.py` / `diagnose.py` split.** One cross-boundary call, plain dict contract. Textbook clean.

3. **Empty `stages/__init__.py`.** Prevents eager loading. The `stages/discrepancy/__init__.py` exception (re-exports `_emit_discrepancy_diagnostics` etc.) is justified — discrepancy is a sub-package and needs an internal seam between predict and diagnose.

4. **`padding_advisor.py` folded into `stages/suggestions.py`.** 63 LOC with one consumer. The deletion test for `padding_advisor.py` as a separate module passes only weakly. Folding was correct.

5. **Prompt cache feature files (`prompt_cache.py`, `prompt_refs.py`, `llm_capabilities.py`, `cache_overlap.py`, `cache_ttl.py`) stayed flat in `core/`.** Consumer packages (`nodes/llm`, `runtime/engine`, `prompt_cache_analysis`) all import from them. Wrapping in a parent package would have added nesting depth with no benefit. The user-rejected option ("consolidate into `prompt_caching/analysis/`") was correctly rejected.

6. **The decision to extract `trace_loading.py` from Cluster D+C plus pipeline helpers from Cluster E.** This is the cleanest extraction in the refactor. It absorbs trace I/O + trace indexing + trace aggregation into one coherent module. The naming and scope are right.

7. **The package rename to `prompt_cache_analysis`.** The CLAUDE.md disambiguation section that explains the two-cache-concepts confusion is now load-bearing in fewer places because the package name self-documents.

---

## The meta-lesson

**The plan was strong on *what* to move and *where*. It was weak on *why the orchestrator must stay thin*.**

The deepening criterion the skill teaches is: **interface leverage**. `analyze()` is the most-called function in the package, used by 3 production consumers and ~50 test sites. Every other module ultimately exists to serve that one function. The orchestrator's value comes from being the only thing a caller needs to know.

By absorbing helpers into `analyze.py` to "stay under 1,100 LOC", the refactor diluted that value. A 400-LOC orchestrator that does nothing but sequence stages would have been more **leveraged**: same interface, much smaller surface to learn.

If you pick this up:
- **Read insight #1 first.** Everything else flows from "what does the orchestrator owe its caller?"
- **Then insight #2.** Tests testing privates is the single biggest constraint on future refactoring. Fixing it is medium-cost work with high downstream value.
- **The rest are individually small.** Pick what you have time for; do not feel obligated to do them all.

The package is in a much better state than before the refactor. The improvements above would make it *even* better — they are not corrections of mistakes, they are second-order polishing that the original constraints did not allow.

---

## Quick references for the next agent

- **Verify zero-behavior-change**: `cd .taskmaster/tasks/task_159/baseline && bash verify.sh` — current state is `80 passed, 7 drifted`. The 7 drifts are pre-existing baseline staleness from feature work (commits #390, #392, #396, #405, #412, #416, #418), NOT caused by this refactor.
- **Verify no LiteLLM eager import**: `uv run python -c "import sys; import pflow.core.prompt_cache_analysis; print('litellm' in sys.modules)"` should print `False`.
- **Test private-symbol leak count**: `grep -rn "from pflow.core.prompt_cache_analysis.*import _" tests/ --include="*.py" | wc -l` — currently 59. Track this number as the primary "interface health" metric.
- **Package LOC budget**: total package is 8,950 LOC across 19 production `.py` files. The refactor removed ~380 LOC net from the original 8,570-LOC `analyze.py` (via dedup and the cycle fix).
- **No dual-path imports check**: `uv run python -c "from pflow.core.prompt_cache_analysis.analyze import CacheAnalysis"` should raise `ImportError`.
