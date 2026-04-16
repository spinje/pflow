# Fix silent drop of undeclared sub-workflow inputs + IR cache heterogeneous-batch bug

## Context

### The problem

Today, passing an input to a `type: workflow` node that the child sub-workflow has not declared in its `## Inputs` is **silently dropped**. No error, no warning, no log line at any verbosity level. A typo like `lyric:` vs `lyrics:` survives validate, execution, and trace inspection.

Two bugs are coupled:

- **Bug A — silent drop of undeclared inputs.** `WorkflowExecutor` has `RESERVED_PARAMS` as a blocklist-style filter; every non-reserved top-level param is forwarded to the child without checking whether the child declared it. Validator Step 7 (`_validate_unknown_params`) would catch this for any other node type, but workflow nodes bypass the registry (`node_loader.py:42`) so Step 7's `if not known_keys: continue` short-circuit silently skips them.
- **Bug B — IR cache breaks heterogeneous batches.** `WorkflowExecutor._cached_loaded_ir` is a scalar keyed on `self`. In a batch where `${item.workflow}` varies per iteration, item 2 reuses item 1's cached child IR. Sequential reuses the same instance; parallel deep-copies the cache after a single pre-warm using item 0. Verified via repro at `/tmp/pflow-repro-batch/` — item 2 fails with "missing required input a … you provided: b" because it loaded child-a's IR but received child-b's inputs.

### Why the fix is coupled

The original report's heterogeneous-batch use case (song-creator reference workflow: parallel fan-out over N review sub-workflows with different `## Inputs` signatures) is the motivating case for keeping any leniency. Fixing Bug A alone produces a migration target (per-item `inputs: ${item.inputs}`) that provably still doesn't work because Bug B. Both must land together.

### Intended outcome

- **One canonical way** to pass values from parent to child: the `inputs:` dict on workflow nodes. No top-level free-form params. No `workflow_ir` inline-IR escape hatch.
- **Symmetric rule at the parent→child boundary**: every value crossing it must be declared on the child. Missing required + undeclared extra are the same diagnostic infrastructure, opposite directions.
- **Structurally impossible to silently drop**: top-level extras rejected at parse time via schema closure; dict extras rejected at parse time via set-diff against the child's declared inputs.
- **Heterogeneous batches work correctly**: IR cache keyed by resolved workflow path; per-iteration child IR load is correct.
- **`RESERVED_PARAMS` frozenset deletable**: its only job (separating framework keys from open-ended forwarding) disappears when the schema is closed.
- **Forward-compatible** with the planned "replace docstring-Interface" refactor: workflow node declares its schema via a `ALLOWED_PARAMS` class attribute — the most mechanism-agnostic form, trivially derivable/replaceable from any future Pydantic/decorator/`__init_subclass__` shape.

## Design decisions (short rationale)

### D1 — Canonical form: `inputs:` dict only

All parent→child value passing goes through a top-level `- inputs:` dict on the workflow node. No more top-level-as-child-inputs. Rationale: agent-first — one pattern to learn, matches code/llm nodes, eliminates the blocklist-filter mental model, enables closed schema.

### D2 — Closed schema via `ALLOWED_PARAMS` class attribute

`WorkflowExecutor.ALLOWED_PARAMS: ClassVar[frozenset[str]]` enumerates the allowed top-level fields. `_validate_unknown_params` gets a branch for workflow-type nodes that reads this attribute. Not A (register in scanner — requires restructuring file location / circular import risk) and not B (permanent special case method in the validator). D is mechanism-agnostic — future refactor (Pydantic / decorator / `__init_subclass__`) either generates or replaces it.

### D3 — W3: remove `workflow_ir` entirely

Zero public doc mentions; one test authors it in markdown (`test_conditional_branching.py:943-957`). Removal eliminates the XOR path in `_load_workflow`, shrinks `sub_workflow_resolver.resolve_sub_workflow`, and simplifies the closed-schema allowed set. One test converts to a proper file fixture.

### D4 — IR cache keyed by resolved workflow path

Replace scalar `_cached_loaded_ir` with `_loaded_ir_cache: dict[str, (ir, path, source, warnings)]` keyed by the resolved workflow path string. Handles heterogeneous batches correctly. Preserves the compile-once benefit for repeated paths.

### D5 — Defense in depth (parse + runtime)

Matches the existing pattern for missing-required (both `validator._check_required_inputs` at parse time and `WorkflowExecutor._validate_child_params` at runtime). Extras check lives in both the same places.

## Implementation (ordered commits)

### Commit 1 — IR cache keyed by resolved path (Bug B)

**File**: `src/pflow/runtime/workflow_executor.py`

- Replace scalar `self._cached_loaded_ir` (line 126) with a dict attribute `_loaded_ir_cache: dict[str, tuple[dict, Path|None, str, list]]`.
- In `prep()` (around line 126-132): resolve the workflow reference first to determine the cache key (resolved path string). Check `self._loaded_ir_cache.get(key)` → reuse on hit; on miss, `_load_workflow` + store.
- Key format: `str(resolved_path)` for file/name-loaded workflows. Once `workflow_ir` is removed (commit 3), there's no inline case to guard.
- Update `_compile_sub_workflow` (line 154-223) cache gate: the `_cached_loaded_ir is not None` check becomes `workflow_path in self._loaded_ir_cache`. The `id()`-based inline branch is deleted along with inline IR.

**New test** (`tests/test_runtime/test_workflow_executor/`):

- `test_ir_cache_keyed_by_path`: direct unit test — prep twice with different paths → different IRs; twice with same path → cached.
- `test_heterogeneous_batch_loads_correct_child_ir`: end-to-end — batch with two items each pointing at a different child, per-item `inputs:` matching each child's signature. Both items succeed (reproduces and then fixes the searcher's `/tmp/pflow-repro-batch/` failure).

### Commit 2 — Migration to `inputs:` form (no behavior change yet)

All existing `.pflow.md` files and test fixtures rewritten to use `- inputs: {...}` instead of top-level child-input params. Still works under the current permissive schema, so tests stay green.

**`.pflow.md` files** (10 nodes across 8 files):

- `examples/nested/document-processor.pflow.md` (2 nodes)
- `examples/nested/deep-research/deep-research.pflow.md` (2 nodes)
- `examples/nested/deep-research/analyze-source.pflow.md` (1 node)
- `examples/bundling/parent-with-sub.pflow.md` (1 node)
- `scratchpads/undeclared-workflow-input-drop/repro-files/parent-extra.pflow.md` (1 node — keep the `b` field to exercise the extras rejection in commit 4's test)
- `scratchpads/undeclared-workflow-input-drop/repro-files/parent-missing-optional.pflow.md` (1 node)
- `scratchpads/undeclared-workflow-input-drop/repro-files/parent-missing-required.pflow.md` (1 node)
- `scratchpads/undeclared-workflow-input-drop/repro-files/parent-batch-hetero.pflow.md` (1 node, now per-item `inputs:`)

**Python test fixtures** (~5 sites):

- `tests/test_core/test_sub_workflow_validation.py:715`
- `tests/test_cli/test_nested_workflow_cli.py:71, 272, 342, 368`

### Commit 3 — Remove `workflow_ir` (W3)

**Files**:

- `src/pflow/runtime/workflow_executor.py`:
  - Delete XOR guards at `_load_workflow` (lines 434-440, 449-453).
  - Delete inline-source branch at line 463-464 (`workflow_source = "inline"`).
  - Delete `workflow_ir` references from docstring (lines 38, 43).
  - Delete `workflow_ir` from `RESERVED_PARAMS` (will fully disappear in commit 4).
  - Delete inline-IR guard from the cache docstring (lines 120-125).

- `src/pflow/core/workflow/sub_workflow_resolver.py`:
  - Remove the inline-IR code path from `resolve_sub_workflow`. Function now accepts only file path or saved name.
  - Adjust signature and return type as needed.

- `src/pflow/runtime/template_validation/validator.py:547-550`: delete the `params.get("workflow_ir")` branch.

- `src/pflow/core/workflow/mermaid/_context.py:30`: remove `"workflow_ir"` from `_RESERVED_PARAMS`.

- `tests/test_integration/test_conditional_branching.py:943-957`: replace the inline `- workflow_ir:` block with a proper fixture file (e.g. `tests/fixtures/conditional_branching_child.pflow.md`) and a `- workflow: ./fixtures/conditional_branching_child.pflow.md` reference. Keep the test's assertions unchanged.

### Commit 4 — Close the schema (Bug A)

**File**: `src/pflow/runtime/workflow_executor.py`

Add at the top of the class:

```python
ALLOWED_PARAMS: ClassVar[frozenset[str]] = frozenset({
    "workflow",
    "inputs",
    "error_action",
    "storage_mode",
    "max_depth",
})
```

- Delete the `RESERVED_PARAMS` frozenset (lines 54-62).
- Simplify `_extract_child_inputs` (lines 409-422) to:
  ```python
  def _extract_child_inputs(self) -> dict[str, Any]:
      return dict(self.params.get("inputs", {}) or {})
  ```
- In `_validate_child_params` (lines 482-514), after the existing missing-required loop, add:
  ```python
  extras = set(child_params.keys()) - set(declared_inputs.keys())
  if extras:
      raise ValueError(...)  # use structured message matching the validator's Diagnostic
  ```
  Runtime defense-in-depth.

**File**: `src/pflow/core/workflow/validator.py`

- `_validate_unknown_params` (line 562-632): at the `known_keys` computation (line 603), add a branch for workflow-type nodes that reads `WorkflowExecutor.ALLOWED_PARAMS` instead of interface metadata. Reuse the rest of the loop (fuzzy suggestions, Diagnostic construction) unchanged.
  ```python
  workflow_types = {"workflow", "pflow.runtime.workflow_executor"}
  if node_type in workflow_types:
      from pflow.runtime.workflow_executor import WorkflowExecutor
      known_keys = set(WorkflowExecutor.ALLOWED_PARAMS)
  else:
      interface = nodes_metadata.get(node_type, {}).get("interface", {})
      known_keys = WorkflowValidator._extract_known_keys(interface)
  ```
  Leave `framework_keys = frozenset({"inputs"})` (line 583) — `inputs` is already in `ALLOWED_PARAMS` so this is defensive-only.

- `_check_required_inputs` (line 742-785):
  - Remove the `WorkflowExecutor.RESERVED_PARAMS` import and usage (line 749, 757). With top-level params gone, `parent_keys` comes from `inputs_value` (dict) only — post-migration, there's no other source.
  - Keep the opaque-template guard (lines 751-754).
  - After the existing missing-required loop, add the inverse:
    ```python
    declared_names = set(child_inputs.keys())
    extras = parent_keys - declared_names
    for extra in sorted(extras):
        sorted_declared = sorted(declared_names)
        similar = find_similar_items(extra, sorted_declared, max_results=2, method="fuzzy")
        diagnostics.append(Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            title="Validation Error",
            node_id=node_id,
            message=(
                f"Step '{node_id}': sub-workflow '{ref_label}' does not declare input "
                f"'{extra}' (passed via inputs: dict)."
            ),
            suggestions=[f"Did you mean '{similar[0]}'?"] if similar else None,
            context={
                "category": "validation",
                "sub_workflow_path": ref_label,
                "sub_workflow_step": node_id,
                "available_fields": sorted_declared,
                "available_fields_total": len(sorted_declared),
                "available_fields_label": "declared inputs",
                "similar_names": similar or None,
            },
        ))
    ```
  - Rename method to `_check_input_shape` if preferred — optional, cosmetic.

**New tests** (add to `tests/test_core/test_sub_workflow_validation.py` or a new file under `test_core/`):

- `test_workflow_extras_top_level_rejected` — workflow node with `- random_field: value` fails at `--validate-only` with Step 7 fuzzy diagnostic.
- `test_workflow_extras_in_inputs_rejected` — workflow node with `- inputs: {known: x, typo: y}` where child declares only `known` fails at `--validate-only` with the new structured diagnostic.
- `test_workflow_extras_with_template_inputs_deferred` — workflow node with `- inputs: ${item}` skips parse-time extras check (opaque template); runtime catches the mismatch. Matches existing missing-required behavior.

### Commit 5 — Docs

- `src/pflow/guide/features/sub-workflows.md`:
  - State clearly: values are passed to children via `- inputs: {...}`. Every value must correspond to a declared `## Inputs` field on the child. Extras are rejected at parse time.
  - Replace any top-level-params examples.
  - Add a named "Heterogeneous batch over sub-workflows" pattern example showing per-item `inputs: ${item.inputs}` with items supplying per-child dicts.
  - Remove any mention of `workflow_ir` (audit showed zero; double-check).

- `src/pflow/core/workflow/CLAUDE.md`: update step-7 and step-8 descriptions to note workflow node coverage.

- `src/pflow/runtime/CLAUDE.md`:
  - Remove `workflow_ir` mention at line 76.
  - Remove "Compile-once `id()` check — only works for static `workflow_ir`" gotcha (no longer applies).
  - Update `WorkflowExecutor` section (line 73-86): `ALLOWED_PARAMS` replaces `RESERVED_PARAMS` concept; no more "non-reserved params are child inputs."

## Files touched (consolidated)

### Code

- `src/pflow/runtime/workflow_executor.py` — cache dict, `ALLOWED_PARAMS`, delete `RESERVED_PARAMS`, simplify `_extract_child_inputs`, extras check in `_validate_child_params`, delete `workflow_ir` handling.
- `src/pflow/core/workflow/validator.py` — branch in `_validate_unknown_params`, inverse extras loop in `_check_required_inputs`.
- `src/pflow/core/workflow/sub_workflow_resolver.py` — remove inline-IR code path.
- `src/pflow/runtime/template_validation/validator.py` — remove `workflow_ir` branch at 547-550.
- `src/pflow/core/workflow/mermaid/_context.py` — remove `"workflow_ir"` from `_RESERVED_PARAMS` at line 30.

### Migration (.pflow.md)

- `examples/nested/document-processor.pflow.md`
- `examples/nested/deep-research/deep-research.pflow.md`
- `examples/nested/deep-research/analyze-source.pflow.md`
- `examples/bundling/parent-with-sub.pflow.md`
- Four files under `scratchpads/undeclared-workflow-input-drop/repro-files/`

### Migration (Python test fixtures)

- `tests/test_core/test_sub_workflow_validation.py` (line 715)
- `tests/test_cli/test_nested_workflow_cli.py` (lines 71, 272, 342, 368)
- `tests/test_integration/test_conditional_branching.py` (lines 943-957 → fixture file)

### New test files / additions

- `tests/test_runtime/test_workflow_executor/test_ir_cache.py` (or extend existing) — cache-key correctness + heterogeneous-batch e2e.
- `tests/test_core/test_sub_workflow_validation.py` additions — three extras-rejection tests.

### Docs

- `src/pflow/guide/features/sub-workflows.md`
- `src/pflow/core/workflow/CLAUDE.md`
- `src/pflow/runtime/CLAUDE.md`

## Existing functions and utilities reused

- `pflow.core.suggestion_utils.find_similar_items` (`validator.py:579, 611`) — fuzzy "did you mean" suggestions for extras diagnostic.
- `pflow.core.diagnostic.Diagnostic` + `Severity` — structured diagnostic construction (already used throughout the validator).
- `pflow.core.diagnostic.format_child_provenance` (`validator.py:11`) — child diagnostic message formatting.
- `WorkflowValidator._add_child_provenance` (`validator.py:19`) — recursive sub-workflow diagnostic wrapping.
- `pflow.runtime.workflow_executor.WorkflowExecutor.ALLOWED_PARAMS` — new class attribute, read by `validator._validate_unknown_params` and (optionally) by runtime defense.

No new utilities needed. All new diagnostics use existing construction patterns.

## Verification

### Automated

1. `make check` passes (ruff, mypy, pre-commit hooks).
2. `make test` passes (full pytest suite).
3. New regression tests pass:
   - `test_ir_cache_keyed_by_path`
   - `test_heterogeneous_batch_loads_correct_child_ir`
   - `test_workflow_extras_top_level_rejected`
   - `test_workflow_extras_in_inputs_rejected`
   - `test_workflow_extras_with_template_inputs_deferred`

### Manual end-to-end

1. **Bug A reproduces as an error** after fix — `uv run pflow scratchpads/undeclared-workflow-input-drop/repro-files/parent-extra.pflow.md --validate-only` exits non-zero with a structured diagnostic naming `b` and suggesting `a` or showing the child's declared inputs.

2. **Bug B heterogeneous batch succeeds** — `uv run pflow scratchpads/undeclared-workflow-input-drop/repro-files/parent-batch-hetero.pflow.md` (rewritten to per-item `inputs:`) produces both children's outputs correctly, whether `parallel: true` or sequential. Contrast with current-state failure reproduced at `/tmp/pflow-repro-batch/` per Phase 1 searcher.

3. **`workflow_ir` removed end-to-end** — grep for `workflow_ir` across the repo returns only historical references (if any) in scratchpads or progress logs; no production code mentions it.

4. **No regressions on existing examples** — run every `.pflow.md` under `examples/` with `--validate-only`; all pass. Run `uv run pflow examples/nested/document-processor.pflow.md` (migrated form) and confirm output unchanged.

5. **Agent UX smoke test** — intentionally typo a key inside `inputs:` on a migrated example; observe the diagnostic names the child's declared inputs and offers a fuzzy suggestion.

## Out of scope / follow-ups

- **Schema-declaration refactor (new task after this PR)** — replace the docstring-regex `Interface:` mechanism with Pydantic models / decorator / `__init_subclass__`. `ALLOWED_PARAMS` on the workflow node becomes either derivable or replaceable at that point; no migration of workflow-node code required during the refactor.
- **`pflow migrate` command** — not worth it at 10 workflow sites. Future mass migrations can revisit.
- **Interface registration for all runtime-special nodes** — currently only workflow bypasses the registry. If more accumulate, consider extending the scanner or introducing a curated registration list. Out of scope here.
