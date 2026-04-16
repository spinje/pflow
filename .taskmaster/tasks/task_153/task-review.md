# Task 153 Review: Reject Undeclared Sub-Workflow Inputs

## Metadata

- **Implementation date**: 2026-04-16
- **Pull request**: https://github.com/spinje/pflow/pull/286
- **Branch**: `fix/silent-drop-undeclared-inputs`
- **Commits**: 5 (`9eedbd1f` core, `2daee665` + `80776a24` + `ec559ca0` review-cycle follow-ups, `a49cd6bf` progress-log update)
- **Tests after**: 4764 passing, 9 skipped; `make check` clean
- **Direct predecessor**: Task 136 (which added parse-time missing-required check in one direction)

## Executive Summary

Closed the parent→child sub-workflow input boundary symmetrically. Every value crossing the boundary now must be declared on the child; extras are rejected at parse time (structured `Diagnostic` with fuzzy suggestions) AND runtime (`ValueError`). Collapsed the dual input-passing mechanism (top-level free-form params + `inputs:` dict) to a single canonical `inputs:` form, deleted `RESERVED_PARAMS` entirely, removed the `workflow_ir` inline-IR escape hatch, and introduced `WorkflowExecutor.ALLOWED_PARAMS` as the forward-compatible seam for the planned schema-declaration refactor. Also fixed a separate IR-cache bug that broke heterogeneous batches (`${item.workflow}` varying per iteration).

## Implementation Overview

### What Was Built

- **`WorkflowExecutor.ALLOWED_PARAMS: ClassVar[frozenset[str]]`** — closed top-level schema declaration consumed by validator Step 7. The workflow node was previously invisible to Step 7 because it bypasses the registry; this attribute gives it a first-class schema without requiring registry relocation.
- **Symmetric input-shape check** — `WorkflowValidator._check_required_inputs` (`validator.py:752-862`) now validates BOTH missing-required AND undeclared-extra directions using set-diff algebra. Runtime counterpart at `WorkflowExecutor._validate_child_params` (`workflow_executor.py:476-534`) mirrors it as defense-in-depth.
- **IR load cache keyed by raw workflow reference** — `WorkflowExecutor._loaded_ir_cache: dict[str, tuple]` at `workflow_executor.py:120-139`. Heterogeneous batches naturally produce different keys per item; homogeneous batches hit the cache from item 2 onward.
- **Non-dict `inputs:` shape diagnostic** — literal non-dict (int, list, string without `${`) rejected at parse time; opaque templates resolving to non-dict caught at runtime via `_extract_child_inputs`.
- **W3 — removed `workflow_ir`** (inline-IR escape hatch) entirely. Resolver, executor XOR logic, template-validation branch, mermaid reserved-params set, and one test all purged.
- **Migration** — 10 `.pflow.md` sites (examples/, repros) + ~44 Python test fixtures converted to `inputs:` dict form.

### Implementation Approach

Option **D** was chosen over three alternatives for schema closure:
- Option A (register workflow node in the scanner) — rejected because `WorkflowExecutor` lives in `runtime/` to avoid a circular import with `compile_workflow`; relocating would touch an architectural boundary for one node type.
- Option B (targeted `_validate_unknown_workflow_params` method) — rejected because it leaves a permanent special case in the validator.
- **Option D (ClassVar frozenset class attribute) — chosen** because it's mechanism-agnostic for the planned schema-declaration refactor (Pydantic / decorator / `__init_subclass__` can all generate or replace it cheaply).

`RESERVED_PARAMS` was **deleted** rather than shrunk. Its existence was a symptom of dual input-passing mechanisms needing a blocklist to separate framework keys from child inputs. Collapsing to `inputs:`-only made the blocklist vestigial.

## Files Modified/Created

### Core source changes

- `src/pflow/runtime/workflow_executor.py` — `ALLOWED_PARAMS` declared (lines 56-62); `RESERVED_PARAMS` deleted; `_extract_child_inputs` collapsed to one line (reads `self.params["inputs"]` only); IR cache keyed by path; `_compile_sub_workflow` cache-key logic simplified to explicit `cacheable` flag; `_validate_child_params` extras loop added; `workflow_ir` user-facing support removed; stale docstrings refreshed.
- `src/pflow/core/workflow/validator.py` — Step 7 workflow-node branch reading `ALLOWED_PARAMS` (`:598-611`); `_check_required_inputs` grown symmetric extras loop with fuzzy suggestions (`:830-860`); non-dict `inputs:` shape diagnostic; `workflow_ir` branch in `_load_child_workflow` removed.
- `src/pflow/core/workflow/sub_workflow_resolver.py` — inline-IR resolution path removed; resolver accepts only file path or saved name.
- `src/pflow/runtime/template_validation/validator.py` — `workflow_ir` output-resolution branch removed.
- `src/pflow/core/workflow/mermaid/_context.py` — `"workflow_ir"` removed from `_RESERVED_PARAMS`.
- `src/pflow/runtime/engine/batch_executor.py` — pre-warm cache uses new `_loaded_ir_cache` / `_compiled_workflow_cache` attribute names.

### Test files

- **New file**: `tests/test_runtime/test_workflow_executor/test_ir_cache.py` — cache-key correctness + end-to-end heterogeneous batch (sequential + parallel). Mutation-resistant (asserts distinct per-child output markers).
- **New class**: `tests/test_core/test_sub_workflow_validation.py::TestUndeclaredExtras` (3 tests) — Bug A parse-time coverage across top-level, inputs-dict, opaque-template-deferred cases.
- **New class**: `tests/test_core/test_sub_workflow_validation.py::TestNonDictInputsShape` (2 tests) — literal non-dict rejection.
- **New tests in** `test_workflow_executor_comprehensive.py` — runtime defense-in-depth (extras + non-dict shape + no-declared-inputs edge case + negative controls).
- **Migrated**: ~44 test sites across runtime-executor, template-validation, integration, CLI trees. Detailed breakdown in `implementation/progress-log.md`.
- **Deleted**: 6 tests that were testing removed XOR / inline-IR behavior. All were tracking removed features, no collateral loss.
- **Test helper pattern**: `_write_child_with_outputs(tmp_path, name, output_keys)` in `test_template_validation/test_validator.py` and `_write_child` helpers in several other test files — raw-string markdown writes that file-back inline child IR fixtures.

### Docs updated

- `src/pflow/guide/features/sub-workflows.md` — `inputs:` as canonical form + heterogeneous-batch named pattern example.
- `src/pflow/runtime/CLAUDE.md`, `src/pflow/core/workflow/CLAUDE.md` — new form, `ALLOWED_PARAMS` mechanism, Step 7/8 coverage notes.

## Integration Points & Dependencies

### Load-bearing integration points

- **`WorkflowExecutor.ALLOWED_PARAMS` ↔ `WorkflowValidator._validate_unknown_params`** (Step 7). The workflow-node branch at `validator.py:598-611` is the workflow-node-specific escape from the Interface-docstring metadata path. **If you rename or remove `ALLOWED_PARAMS`, the workflow node's top-level schema falls open again** and the Step 7 safety net is lost (silent-drop returns).
- **`_loaded_ir_cache: dict[str, tuple]` on the executor instance** ↔ **`batch_executor._pre_warm_compile_cache`**. The pre-warm runs `prep()` on item 0 to populate the cache, then `copy.deepcopy(node)` propagates both caches into parallel worker threads. For heterogeneous batches, each worker cache-misses on its own item's raw ref and loads/compiles independently — this is correct only because the cache is a dict, not a scalar. **Don't revert to a scalar cache attribute.** The docstring at `workflow_executor.py:120-123` and the pre-warm bailout at `batch_executor.py:144-152` both depend on the dict shape.
- **`sub_workflow_resolver.resolve_sub_workflow`** is now the single entry point for child IR loading (file path or saved name only — no inline IR). Consumed by `WorkflowValidator._load_child_workflow`, `WorkflowExecutor._load_workflow`, `template_validation/validator._resolve_child_workflow_outputs`, and the mermaid visualizer. Any future input-loading mechanism should either extend this resolver or route through it.
- **`_check_required_inputs` handles BOTH directions**. Method name is preserved for git-diff-ability but semantically it's "input shape check." If you see this name and assume it only covers missing-required, you'll miss half the logic.

### Incoming dependencies (who depends on this task)

- Future schema-declaration refactor task — `ALLOWED_PARAMS` is the seam that refactor will generalize/replace. The refactor's job is (a) pick a mechanism (Pydantic model / decorator / `__init_subclass__`), (b) migrate every node type onto it, (c) delete the docstring-Interface regex pipeline.
- GH #283 (mermaid fix) — will need to descend into `inputs:` dicts to restore data-flow edge fidelity. Uses the new canonical shape as input.
- GH #284 (error_action + prep-time errors) — touches `_validate_child_params` raise path; any fix must not regress the extras/missing-required coverage.
- GH #285 (diagnostic label) — one-line fix in `validator.py:825`.

### Outgoing dependencies (what this task depends on)

- **Task 136** — added `_check_required_inputs` at `validator.py:752` (missing-required direction only) + `RESERVED_PARAMS` frozenset + `_validate_child_params` runtime check. Task 153 completed the asymmetry and deleted `RESERVED_PARAMS`.
- **"Task 161"** (referenced in Task 136 docs; task file doesn't exist but the mechanism does) — made `inputs:` a reserved framework key passed through `_extract_child_inputs`. Task 153 made it the canonical form.
- **Step 7 (`_validate_unknown_params`)** — existing closed-schema pattern for every other node type. Task 153 plugged the workflow node into it.

## Architectural Decisions & Tradeoffs

### Key decisions

| Decision | Why | Rejected alternative |
|---|---|---|
| `ALLOWED_PARAMS` class attribute | Mechanism-agnostic for the planned schema-declaration refactor. Any future form (Pydantic / decorator / hook) generates or replaces a frozenset cheaply. | Register workflow node in the scanner (A) — required file relocation + circular-import fight for one node type. Targeted validator method (B) — permanent special case forever. |
| Delete `RESERVED_PARAMS` entirely | Its existence was a symptom of dual input-passing mechanisms needing a blocklist. With one mechanism, no blocklist is needed. Simpler final state. | Shrink the frozenset. Leaves the blocklist pattern alive as a smell. |
| Defense in depth: parse + runtime | Matches existing missing-required pattern. Protects programmatic callers that bypass `WorkflowValidator` (MCP server, tests constructing executors directly). Runtime also catches opaque-template cases parse-time can't see. | Parse-time only. Leaves a real silent-drop vector for programmatic callers. |
| Wording divergence between parse-time Diagnostic and runtime ValueError | Matches existing missing-required divergence. Aligning only extras would be a local inconsistency. Unification belongs in a dedicated runtime-errors-→-Diagnostics sweep. | Align wording. Premature — one inconsistency doesn't justify an unrelated refactor. |
| Remove `workflow_ir` entirely (W3) | Zero public doc mentions, one test authored it in markdown, works against every property pflow tries to enable. | Keep undocumented. Leaves a second mechanism for the same job as a hidden footgun. |
| Fold non-dict `inputs:` diagnostic INTO this PR | Same surface as Bug A; small fix; caught by the same review. Splitting would be fake scope discipline. | Defer to follow-up. Creates two review cycles for one cluster of findings. |
| NOT fold `framework_keys = frozenset({"inputs"})` cleanup into this PR | Depends on the future schema-declaration refactor's shape. Fixing it now risks double-work. Counter-example to the fold-in rule. | Fold in anyway. |

### Technical debt acknowledged

- **`"<inline>"` sentinel in `prep_res["workflow_path"]`** — post-W3 means "saved name with no on-disk file" (edge case), not "inline IR". Misleading name. Rename cascades into `exec()`, `post()`, trace recording, compile cache's cacheable-check. Medium-sized follow-up.
- **Runtime errors use vanilla `ValueError`** — CLAUDE.md says to use `PflowError` subclasses. Pre-existing pattern; task 153 extended it by one site (the extras raise). Unification is a dedicated task.
- **`framework_keys = frozenset({"inputs"})` at `validator.py:583`** — defensive-but-doing-no-work. Every node that uses `inputs:` declares it in its Interface. Fold into schema-declaration refactor.
- **Docstring-`Interface:` regex parsing** — the Step 7 metadata source. Known tech debt; `ALLOWED_PARAMS` is the first migrant away from it.

## Testing Implementation

### Tests that catch real bugs (not just coverage)

- `test_ir_cache.py::test_heterogeneous_batch_loads_correct_child_ir` + `test_heterogeneous_batch_parallel` — run two different children end-to-end through `WorkflowEngine`, assert distinct stdout markers (`a_is_ALPHA` vs `b_is_BETA`). Sequential AND parallel. Mutation-resistant: any revert to scalar `_cached_loaded_ir` fails immediately.
- `test_ir_cache.py::test_ir_cache_miss_on_different_ref` — `is not` identity check on cached IR dicts. Catches any broken cache-key semantics.
- `TestUndeclaredExtras::test_workflow_extras_in_inputs_rejected` — asserts structured `context` shape (`available_fields`, `similar_names`) + fuzzy suggestion content. Catches diagnostic shape regressions beyond message text.
- `test_inputs_non_dict_raises_shape_error` + `test_inputs_none_treated_as_no_inputs` — positive/negative control pair locks in the defense-in-depth contract.
- `test_no_declared_inputs_still_rejects_extras_at_runtime` + `test_no_declared_inputs_and_empty_inputs_dict_succeeds` — positive/negative control pair for the last silent-drop edge case (child with no `## Inputs` + programmatic caller).
- `test_file_workflow_execution` (post-review-cycle) — asserts `shared["sub"]["test"]["test_output"] == "Processed: Hello from file"` through auto-expose, catching silent-drop of `inputs:` delivery (previously only asserted `result == "default"`).

### Tests migrated from silent-pass to actually-testing

- 33 sites across `test_workflow_executor/` that constructed `{"workflow_ir": ir}` dicts for test convenience.
- 7 sites in `tests/test_runtime/test_template_validation/` — same `workflow_ir` dict shape, different directory; missed by initial audit.
- 3 sites in `tests/test_integration/test_unused_inputs.py` bypassing Step 7 via omitted `registry=` kwarg.
- 1 site (`test_file_workflow_execution`) bypassing `WorkflowValidator` entirely.
- 8 sites using `simple_workflow_ir` fixture (no declared inputs) + passing inputs — needed input declarations after the last edge-case fix.

## Unexpected Discoveries

### Scope surprises (two waves)

**First wave — Commit 3 (`workflow_ir` removal)**: searcher's Phase-1 audit missed 33 test sites that constructed Python dicts with `"workflow_ir"` as a key. The searcher grep'd for "places that author `- workflow_ir:` in markdown" (1 site). It did not grep for dict-construction patterns in test code.

**Second wave — post-commit review cycle**: 11 more silently-passing test sites across 3 distinct failure modes:
1. Same-pattern-different-directory (7 in template-validation tests).
2. Optional-kwarg bypasses validation step (3 in test_unused_inputs.py omitting `registry=`).
3. Bypasses validator entirely via `compile_workflow` direct call (1 in test_integration.py).

### Meta-lesson from these two waves

When removing a feature or tightening a validator, audit **three** test shapes, not just one:
1. **Authoring shape** — markdown fixtures referencing the feature.
2. **Dict-construction shape** — Python dicts with the string key, across **ALL** test directories.
3. **Bypass-path shape** — tests that skip the validator via optional-param omission, direct `compile_workflow` calls, or other mechanisms that silently disable the check.

Mutation testing ($X → BOGUS) catches all three classes structural grep alone can miss.

### One silent-drop edge case survived until the /evaluate-review pass

Even after two review cycles and 4 specialist agents' review, the final `/evaluate-review` subagent caught a genuine silent-drop: `_validate_child_params` early-returned when `declared_inputs` was empty, so programmatic callers + child-with-no-inputs = silent success. Parse-time caught it (`set() - set() = set()`, all parent keys become extras). Runtime didn't. The test `test_no_declared_inputs_skips_validation` literally encoded the bug as the feature. Fix: remove the early return + flip the test.

## Patterns Established

### Reusable patterns future tasks should follow

**1. `ALLOWED_PARAMS` class attribute for top-level schema declaration.**

```python
class MyNode(BaseNode):
    ALLOWED_PARAMS: ClassVar[frozenset[str]] = frozenset({
        "required_field",
        "optional_field",
        "framework_knob",
    })
```

Any new node type should declare this alongside its docstring Interface. Step 7 reads it when available; the legacy Interface-metadata path handles nodes that don't.

**2. Set-diff algebra for parent-child boundary checks.**

```python
# Missing-required
for name, spec in declared.items():
    if is_required(spec) and name not in provided:
        emit(MissingRequired(name))

# Undeclared extras (inverse direction, same primitive)
extras = set(provided) - set(declared)
for extra in sorted(extras):
    emit(UndeclaredExtra(extra, similar=fuzzy(extra, declared)))
```

Both directions use the same set-diff. Use for any validated key-pair boundary.

**3. Defense-in-depth: parse-time structured Diagnostic + runtime ValueError.**

Any check that matters to users should fire at both tiers:
- **Parse-time**: accumulate `Diagnostic` objects (all violations surface at once; fuzzy suggestions via `find_similar_items`).
- **Runtime**: raise `ValueError` on first violation (matches existing missing-required pattern). Protects programmatic callers.

**4. Positive + negative control test pairs for defense-in-depth contracts.**

```python
def test_X_rejected_at_runtime(self):
    # positive: violation raises
    with pytest.raises(ValueError, match=...): node.prep({})

def test_X_not_raised_when_valid(self):
    # negative: no false positive when contract is satisfied
    node.prep({})
```

Without the negative control, a "defense-in-depth" claim is unverifiable — a future refactor could delete the check as "dead code" without test signal.

**5. Cache-by-logical-key, not by instance.**

Per-executor-instance scalar caches (`self._cached_X`) break in batch contexts where the same instance serves multiple items. Use a dict keyed by the logical identity (resolved path, raw reference string, etc.). Instance-deepcopy in parallel workers then does the right thing — each worker cache-misses on its own item's key.

### Anti-patterns to avoid

**1. Early-return on empty input structures.**

```python
# DON'T
if not declared_inputs:
    return  # Silent: any provided keys become extras, invisibly.
```

Let the set-diff algebra handle the empty-vs-populated cases naturally. The loop over an empty dict is a natural no-op; the set-diff against an empty set correctly flags all provided keys.

**2. Blocklist-style filtering as dual-mechanism band-aid.**

If you find yourself writing `RESERVED_KEYS = {...}` to separate "framework stuff" from "user stuff" in a free-form param dict, you probably have two mechanisms that should be one. Close the schema instead.

**3. Test-helper APIs with optional kwargs that silently disable validation.**

`split_validator_diagnostics(workflow_ir, registry=None)` silently skips Step 7. Tests omitting `registry=` diverged from production. Pattern: validator helpers should make "skip step X" explicit or impossible, not silently disable on missing parameters.

**4. Tests that assert only "execution succeeded".**

`assert result == "default"` passes whether or not the behavior-under-test actually occurred. Task-59 lesson, rediscovered here. Every test claiming to validate X should have an assertion that mechanically depends on X happening.

## Breaking Changes

MVP (no external users per CLAUDE.md), so these are documentation-only for future-agent awareness:

### Removed user-facing features

- **`workflow_ir:` inline-IR parameter on workflow nodes** — fully removed. Any workflow that previously used `- workflow_ir: {inline_dict}` must convert to a file reference + `- workflow: ./child.pflow.md`.
- **Top-level free-form params as child inputs** — the `- key: value` form at the top level of a workflow node is no longer valid for child inputs. Must nest inside `- inputs: {...}`. Top-level fields are now exactly `{workflow, inputs, error_action, storage_mode, max_depth}`.

### Behavior changes

- **Extras in `inputs:` dict** — silently dropped → parse-time + runtime `ERROR`.
- **Unknown top-level fields on workflow nodes** — silently ignored → parse-time `ERROR` (Step 7 with fuzzy suggestion).
- **Non-dict `inputs:`** — silently returned `{}` → parse-time `ERROR` (literals) or runtime `ValueError` (templates resolving to wrong shape).
- **Heterogeneous batch with `${item.workflow}`** — previously failed on item 2+ with "missing required input" because IR cache reused item 1's child → now works correctly (cache keyed by resolved path).

### New behavior

- **`WorkflowExecutor.ALLOWED_PARAMS`** is now a contract. Adding a new framework knob to workflow nodes requires adding the key to this frozenset AND updating docstring Parameters section. Skipping either → Step 7 rejects workflows using the new knob.

## Future Considerations

### Extension points

- **Adding a new framework knob to workflow nodes**: add the key to `ALLOWED_PARAMS` at `workflow_executor.py:56-62`, update docstring "Parameters" section, handle the key in `prep()`/`post()`/executor logic, add test.
- **Adding a new node type with closed schema**: declare `ALLOWED_PARAMS: ClassVar[frozenset[str]]` on the class. If the node lives in `src/pflow/nodes/` (discoverable by the scanner), it will ALSO get the Interface-metadata path automatically; ALLOWED_PARAMS takes precedence when both are present (the validator prefers class-attribute over metadata).
- **Tightening validator beyond parent-child boundary**: follow the set-diff algebra pattern + defense-in-depth structure. Emit structured `Diagnostic` at parse time; raise `ValueError` at runtime.

### Scalability / performance concerns

- Heterogeneous parallel batches compile O(unique_children) workflows instead of O(1). For a batch of 4 different children, 4 compilations happen. This is correct behavior (documented) but means parallel compile budget scales with heterogeneity — worth noting for agents relying on "compile once, reuse many" claims.
- `_loaded_ir_cache` is per-executor-instance. Deep copies into parallel workers duplicate the cache state. For very large child IRs this could be memory-expensive; not optimized here because child IRs are small in practice.

### Filed follow-ups (tracked GH issues)

- **GH #283** — Mermaid visualizer descends only into top-level string params; doesn't traverse `inputs:` dicts. Goldens coarsened. Fix: descend into nested dict values in `_edges.py:239-252` using the existing `_collect_param_refs` helper pattern.
- **GH #284** — `error_action: continue` doesn't catch prep-time validation errors (input-shape raises bypass `error_action` which only handles child's `"error"` action).
- **GH #285** — Diagnostic label "Available required inputs" lists optional inputs too. One-line relabel fix at `validator.py:825`.
- **Future schema-declaration refactor task** (not yet filed) — replace docstring-Interface regex with Pydantic models / decorator / `__init_subclass__`. `ALLOWED_PARAMS` is the seam that refactor will generalize across every node type and then delete the legacy path.

## AI Agent Guidance

### Quick start for related tasks

**If you're adding a field to workflow nodes** → update `WorkflowExecutor.ALLOWED_PARAMS` (`workflow_executor.py:56-62`) AND the docstring Parameters block (`:36-45`). Step 7 reads `ALLOWED_PARAMS` at validation time; forgetting it means Step 7 rejects workflows using the new field as "unknown parameter."

**If you're touching parent→child input validation** → `_check_required_inputs` in `validator.py:752-862` handles BOTH directions (missing-required AND extras). Parse-time. Runtime counterpart: `WorkflowExecutor._validate_child_params` in `workflow_executor.py:476-534`. Keep them symmetric.

**If you're touching the IR cache** → `_loaded_ir_cache: dict[str, tuple]` keyed by raw workflow ref (`self.params["workflow"]`), populated in `prep()` at `workflow_executor.py:120-139`. Paired compile cache `_compiled_workflow_cache: dict[str, ...]` keyed by resolved workflow path, populated in `_compile_sub_workflow` at `:161-221`. Parallel batch pre-warm at `batch_executor.py:104-166` depends on both being dicts (not scalars) and on the post-prep-deepcopy propagation.

**If you're removing a feature** → grep the raw string key across **ALL** test directories, not just the subsystem's tests. Audit test-helper APIs for optional kwargs that silently disable validation. Use mutation testing (replace expected token with `BOGUS`) to verify tests actually exercise their claims.

**If you're writing a new node type** → declare `ALLOWED_PARAMS` alongside the docstring Interface. New node types should inherit the forward-compat path even though the schema-declaration refactor hasn't landed yet.

### Key files to read first (in order)

1. `.taskmaster/tasks/task_153/task-153.md` — spec with design decisions and rejected alternatives.
2. `src/pflow/runtime/workflow_executor.py` — `ALLOWED_PARAMS`, `_validate_child_params`, `_extract_child_inputs`, IR cache.
3. `src/pflow/core/workflow/validator.py:752-862` — `_check_required_inputs` (both directions).
4. `src/pflow/core/workflow/validator.py:562-643` — Step 7 (`_validate_unknown_params`) with workflow-node branch.
5. `.taskmaster/tasks/task_153/implementation/progress-log.md` — retrospective with scope surprises, design choices, and meta-lessons.

### Common pitfalls

1. **Reintroducing the early return in `_validate_child_params`**. The inline comment explicitly warns. A naive "optimize by skipping when nothing to check" reverts the silent-drop fix.
2. **Assuming `_check_required_inputs` only checks required**. Method name is semantically misleading — it checks BOTH directions. Renaming would be git-diff-hostile but the comment block above documents this.
3. **Making `_loaded_ir_cache` a scalar again** to "simplify." Heterogeneous batches break immediately, but tests may still pass if you only run homogeneous-batch tests.
4. **Adding a workflow-node field without updating `ALLOWED_PARAMS`**. Step 7 rejects the field as "unknown parameter." The fuzzy suggestion usually makes this self-diagnosing but it's a real gotcha.
5. **Assuming `inputs: null` / missing `inputs:` means error**. Both mean "no inputs provided." Only non-None non-dict values are shape errors.

### Test-first recommendations when modifying

- **Modifying `_validate_child_params`** → run `test_no_declared_inputs_still_rejects_extras_at_runtime` + `test_no_declared_inputs_and_empty_inputs_dict_succeeds` + `test_undeclared_extras_in_inputs_dict_rejected_at_runtime` + `test_runtime_extras_not_raised_when_all_keys_declared`. All four must pass; each guards a distinct behavioral dimension.
- **Modifying the IR cache** → run `test_ir_cache.py` in full. `test_heterogeneous_batch_loads_correct_child_ir` (sequential) and `test_heterogeneous_batch_parallel` are the mutation-resistant guards.
- **Modifying `ALLOWED_PARAMS`** → run `TestUndeclaredExtras::test_workflow_extras_top_level_rejected`. Verifies Step 7 fires and surfaces the updated allowed-set in `available_fields`.
- **Modifying `_extract_child_inputs`** → run `test_inputs_dict_values_forwarded_as_child_inputs` + `test_inputs_non_dict_raises_shape_error` + `test_inputs_none_treated_as_no_inputs`. The three together lock in the "returns dict, raises on non-dict, empty on None" contract.

---

*Generated from implementation context of Task 153. For the implementation journey and scope-surprise archaeology, see `implementation/progress-log.md`. For design decisions and rejected alternatives, see `task-153.md`.*
