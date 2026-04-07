# Task 147: Validator Produces Diagnostics Natively (#219)

## Description

Convert all three validator layers (`WorkflowValidator.validate`, `validate_workflow_templates`, `validate_data_flow`) from producing flat error strings to producing structured `Diagnostic` objects directly. Completes the architectural arc started by Tasks 141, 143, and 144 — extends the "self-describing producers" principle from exceptions to validation checks.

## Status

not started

## Priority

high

## Problem

`WorkflowValidator.validate()` currently returns `tuple[list[str], list[Diagnostic]]` — errors as flat strings, warnings as `Diagnostic` objects. This asymmetry creates four cascading problems:

1. **Structural data is computed and then thrown away.** Every validation helper has the structured data it needs (paths like `nodes[0].params.command`, fuzzy-match suggestions, available options, concrete fixes, node IDs, parameter names) but flattens it into f-string messages. For example, `_validate_unknown_params` calls `find_similar_items()` to compute fuzzy matches, then interpolates them into the error string with `msg += f" Did you mean {suggestions}?"` instead of populating `Diagnostic.suggestions`.

2. **The runner fabricates Diagnostics from those strings.** `runner.py:290-302` wraps each flat error string into a generic `Diagnostic(title="Validation Error", message=error, context={"category": "validation"})` — losing all the structure that the validator originally had. Every validation error gets the identical generic title.

3. **Suggestions are reverse-engineered via pattern matching.** `runner.py:307` calls `generate_validation_suggestions()` (a 40-line function in `validation_utils.py`) that pattern-matches the flattened strings to fabricate INFO-level suggestions. This is the validator throwing away structured data and the runner trying to reconstruct it from text.

4. **A `# type: ignore[arg-type]` papers over the design mismatch.** `WorkflowValidationError.validation_errors` is typed as `list[str | tuple[str, str, str]]` — the tuple form was designed to carry `(message, path, suggestion)` for structured errors, but no caller actually constructs it. `runner.py:393` raises `WorkflowValidationError(validation_errors=errors)  # type: ignore[arg-type]` because errors is `list[str]`, not the typed union.

**The visible symptom**: Compare the `--validate-only` output (bare flat strings, generic ℹ fallback) to runtime errors (rich `Error: Title / message / At: location / → suggestion` format). Validation errors are the visible outlier in the post-Task-144 unified diagnostic system.

This task is named in Task 144's review as known debt:
> `format_validation_failure()` accepts `list[Any]` — should be `list[Diagnostic]` once `WorkflowValidator.validate()` returns Diagnostics (spinje/pflow#219).

## Solution

**Architectural principle**: Extend Task 144's "self-describing producers" pattern from exceptions to validation checks. Validation producers (the deepest functions that detect errors) build `Diagnostic` objects directly. No string intermediate. No wrapper/conversion step in the runner.

**Three-layer model** (the model Tasks 141/143/144 established):

```
Producer                         Data type              Rendering
───────────────                  ─────────              ─────────
Exception class                  Diagnostic             format_diagnostic()
  .to_diagnostics()    ───────►                ───────►   (ONE format)
Validation check                 list[Diagnostic]
  returns directly     ───────►
Runtime event
  emits directly       ───────►
```

**Concrete changes**:

1. **`WorkflowValidator.validate()` returns `list[Diagnostic]`** — single list, not tuple. Severity is a field on `Diagnostic`. All 9 internal `_validate_*` helpers return `list[Diagnostic]`.
2. **`validate_workflow_templates()` returns `list[Diagnostic]`** — same pattern. The 8 template-validation passes (path, type, shell, batch-item, malformed, unused-inputs) all produce Diagnostics directly.
3. **`validate_data_flow()` returns `list[Diagnostic]`** — primitive layer, also called by the compiler.
4. **`WorkflowValidationError.validation_errors: list[Diagnostic]`** — delete the `list[str | tuple]` union, simplify `to_diagnostics()` to a pass-through.
5. **Broaden the renderer's `available_fields` gate** — `_format_template_error_lines` in `diagnostic.py` currently only renders under `category == "template_error"`. Make it unconditional and rename to `_format_available_fields_block`. Single required renderer change.
6. **Rewrite `format_validation_failure()`** — the dominant CLI/MCP text path's formatter currently only renders 3 fields per error. Delegate to `format_diagnostic()` so the new structured fields actually reach users in text mode (without this, the improvement only reaches JSON consumers).
7. **Use `format_child_provenance()` for sub-workflow error propagation** — symmetry with the warnings path established in Task 143. Extend `_add_child_provenance` helper to handle errors as well as warnings.
8. **Fix latent dual-propagation-path dedup bug** — `WorkflowExecutor._propagate_child_parser_warnings:337` uses `node_id=step_id` (always overwrites), while validator path uses `d.node_id or step_id`. Different node_ids → different `Diagnostic.__hash__` → no dedup. One-line alignment fix.
9. **Delete `generate_validation_suggestions()`** in full — pattern-matching function with 1 production caller (runner.py) and 4 dedicated tests (`TestValidationSuggestions` in test_workflow_data_flow.py). Becomes dead code once validator produces structured suggestions.

**Knock-on simplifications**:
- Delete the runner's string-fabrication loop (`runner.py:290-316`)
- Remove the `# type: ignore[arg-type]` (resolved naturally)
- Simplify `WorkflowValidationError.to_diagnostics()` from 30 lines to 8

## Design Decisions

User-approved decisions from discussion:

1. **Single list return, not tuple `(errors, warnings)`** — severity is a field on `Diagnostic`, not a list identity. Matches `ExecutionResult.diagnostics` and `ValidationResult.diagnostics` patterns. Matches rustc/ruff/mypy/ESLint idiom (per Task 144 research). Tests filter by severity inline.
2. **`WorkflowValidationError.validation_errors: list[Diagnostic]`** — delete the tuple/str union entirely. The 2 production callers (`cli/main.py:631`, `runner.py:393`) and 2 test callers (`test_diagnostic.py:151`, `capture_baselines.py:134`) are updated to construct `Diagnostic` directly.
3. **Delete `generate_validation_suggestions()` in full** — its 4 dedicated tests verify pattern-matching edge cases that don't exist after structured suggestions.
4. **Use `format_child_provenance()` helper for sub-workflow error propagation** — same helper warnings already use. Achieves error/warning symmetry Task 143 set up.
5. **All three validator layers converted in one PR** — avoids the "Task 143 took the pragmatic shortcut, Task 144 had to fix it" lesson written into the codebase history.
6. **Keep `WorkflowValidationError(summary=str)` single-string constructor unchanged** — only `validation_errors` field type changes. The 19 single-string call sites in `manager.py` and `save_service.py` continue to work via the empty-list fallback.
7. **Sub-workflow provenance**: keep child's `context["path"]` untouched (it's relative to the child IR), add `context["sub_workflow_step"]` and `context["sub_workflow_path"]` for parent context.
8. **Broaden the renderer gate** for `available_fields` — gating it on `template_error` category was an artifact. The block is generic ("valid parameters", "valid nodes", "valid inputs"). Renaming to `_format_available_fields_block` reflects its actual purpose.

**Why Option D over alternatives** (from discussion):
- **Option A (outer layer only)** rejected — leaves the most valuable case (template errors via `format_enhanced_node_error`) bare. Same pain wrapped in a Diagnostic shell.
- **Option C (phased)** rejected — Task 143 took the pragmatic phased approach and Task 144 had to come back and fix it. The lesson is in the codebase history.
- **Option D (full conversion + single list + cleanup)** chosen — final code is simpler, the runner has fewer bridges, the tuple/str union and `type: ignore` are deletable, the architecture matches what Tasks 141/143/144 established for exceptions.

## Dependencies

- **Task 141** (DONE): Consolidate Exception Hierarchy — established `core/exceptions.py` as a leaf module with module-level imports
- **Task 143** (DONE): Unified Diagnostic System — created `Diagnostic` dataclass, unified ExecutionResult/ValidationResult to single-list
- **Task 144** (DONE): Display Consolidation — established self-describing exceptions via `to_diagnostics()`, one rendering format, and named #219 as known debt

This task is the architectural completion of the 141 → 143 → 144 arc.

## Requirements

### Validator signatures

- `WorkflowValidator.validate()` returns `list[Diagnostic]` (single list, not tuple)
- `validate_workflow_templates()` returns `list[Diagnostic]`
- `validate_data_flow()` returns `list[Diagnostic]`
- All 9 internal `WorkflowValidator._validate_*` helpers return `list[Diagnostic]`
- All template-validation submodule producers (`path_validation.py`, `type_validation.py`, `batch_item_validation.py`) return `list[Diagnostic]`

### Producer self-description

- Every validator helper builds `Diagnostic` objects at the source — no string flattening
- Producers populate `context["path"]` with JSON-pointer location (e.g., `nodes[0].params.command`) when known
- Producers populate `context["similar_names"]` with pre-truncated fuzzy matches (max ~5)
- Producers populate `context["available_fields"]` + `context["available_fields_total"]` for "valid options" lists
- Producers use `node_id` field for the affected node when known
- Producers use `category="validation"` for general validation errors, `category="template_error"` for template-class errors
- Helpers like `_format_node_not_found_error` and `_format_template_node_error` return `Diagnostic` directly (renamed to `_build_*_diagnostic`)
- The richest helper, `format_enhanced_node_error` in `path_validation.py`, becomes `_build_enhanced_node_diagnostic` returning a Diagnostic with `available_fields` + `similar_names` + structured suggestions

### Renderer

- `_format_template_error_lines` in `diagnostic.py` renamed to `_format_available_fields_block`
- The `category == "template_error"` gate is removed (block renders unconditionally)
- A new `source_file` block is added to `_format_all_context_blocks` for `_attach_source_file_hint` provenance

### Exception

- `WorkflowValidationError.validation_errors: list[Diagnostic]` (was `list[str | tuple[str, str, str]]`)
- `WorkflowValidationError.to_diagnostics()` becomes a pass-through (no tuple/str branching)
- `WorkflowValidationError(summary=str)` single-string constructor still works (empty-list fallback)

### Consumer cleanup

- `runner.py:_validate()` filters errors via `severity == Severity.ERROR`, raises `WorkflowValidationError(validation_errors=errors)` with no `# type: ignore`
- `runner.py:validate()` (the validate-only entry) deletes the string-fabrication loop and `generate_validation_suggestions` post-processing
- `save_service.py` filters errors and constructs `WorkflowValidationError` with `validation_errors=` populated
- `cli/main.py:631-640` constructs a `Diagnostic` inline instead of a tuple
- `compile_validation.py:115-125` filters errors before the truthiness check (defensive against future warning-severity producers in `data_flow.py`)
- `format_validation_failure()` delegates to `format_diagnostic()` per error so the dominant CLI/MCP text path renders the new structured fields

### Sub-workflow provenance

- `_add_child_provenance` helper extended to handle both errors and warnings (currently warnings-only)
- `_add_child_provenance` accepts optional `ref_label` parameter and adds `sub_workflow_step` + `sub_workflow_path` to child context
- Sub-workflow error propagation uses `format_child_provenance()` (the same helper warnings already use)
- `WorkflowExecutor._propagate_child_parser_warnings:337` updated to use `node_id=d.node_id or step_id` (matching validator's policy) — fixes latent dedup asymmetry

### Deletions

- `generate_validation_suggestions()` function in `core/validation_utils.py` deleted
- `TestValidationSuggestions` class (4 tests) in `test_workflow_data_flow.py` deleted
- String-fabrication loop in `runner.py:290-316` deleted
- `# type: ignore[arg-type]` at `runner.py:393` deleted
- Tuple/str branches in `WorkflowValidationError.to_diagnostics()` deleted (~22 lines)

### Documentation updates

- `src/pflow/mcp_server/services/CLAUDE.md:82` — example code updated for single-list return
- `src/pflow/core/CLAUDE.md:77` — exception usage table updated (drop tuple form)
- `src/pflow/core/CLAUDE.md` — `validation_utils.py` paragraph updated (remove `generate_validation_suggestions` description)
- `architecture/reference/template-variables.md:439-450` — `validate_workflow_templates` signature docs
- `architecture/reference/template-variables.md:~1598` — example code

### Test rewrites (~309 assertions)

Mechanical rewrites following 7 patterns:
1. **Direct index**: `errors[0]` → `errors[0].message`
2. **Substring in for loop**: `any("foo" in e for e in errors)` → `any("foo" in d.message for d in errors)`
3. **String join**: `"\n".join(errors)` → `"\n".join(d.message for d in errors)`
4. **List filter**: `[e for e in errors if "foo" in e]` → `[d for d in errors if "foo" in d.message]`
5. **Tuple unpack → single list + filter**: `errors, warnings = ...` → `diagnostics = ...; errors = [d for d in diagnostics if d.severity == Severity.ERROR]`
6. **Variable assignment**: `error = errors[0]; assert "foo" in error` → `error = errors[0].message; ...`
7. **Set comprehension**: `set(errors)` → `{d.message for d in errors}`

Plus one semantic rewrite: `test_exception_to_diagnostics_workflow_validation_error_fans_out` in `test_diagnostic.py` is rewritten to verify Diagnostic pass-through instead of tuple fan-out.

## Implementation Notes

### Critical files (must read before implementation)

1. `src/pflow/core/diagnostic.py` — the data type, renderer, `format_child_provenance` helper
2. `src/pflow/core/exceptions.py` — `WorkflowValidationError` class
3. `src/pflow/core/workflow/validator.py` — outer validator orchestrator (the 9-step pipeline being changed)
4. `src/pflow/core/workflow/data_flow.py` — primitive data flow validator
5. `src/pflow/runtime/template_validation/validator.py` — template orchestrator
6. `src/pflow/runtime/template_validation/path_validation.py` — 15 producers including `format_enhanced_node_error` (highest-value conversion)
7. `src/pflow/runtime/template_validation/type_validation.py` — 3 producers (shell command error with 4 fix options)
8. `src/pflow/runtime/template_validation/batch_item_validation.py` — 2 producers
9. `src/pflow/execution/runner.py` — consumer with the fabrication loop to delete
10. Tasks 141/143/144 review files in `.taskmaster/tasks/task_141/task-review.md`, `task_143/task-review.md`, `task_144/task-review.md`

### Reused helpers (do NOT recreate)

| Helper | Location | Purpose |
|---|---|---|
| `Diagnostic`, `Severity` | `core/diagnostic.py` | The type every producer builds |
| `format_child_provenance(step_id, message)` | `core/diagnostic.py:93` | Sub-workflow provenance prefix |
| `find_similar_items(target, candidates, max_results, method="fuzzy")` | `core/suggestion_utils.py` | Fuzzy matching for "did you mean" |
| `sanitize_for_display(value)` | `runtime/template_validation/utils.py` | Strips control chars (template injection prevention) |
| `find_similar_paths(attempted, available_paths)` | `runtime/template_validation/utils.py` | Fuzzy matching over (path, type) tuples |
| `MAX_DISPLAYED_FIELDS` | `runtime/template_validation/utils.py` | Truncation constant |
| `deduplicate_diagnostics(list)` | `core/diagnostic.py:82` | Dedup via `__hash__` |
| `_add_child_provenance(diagnostics, step_id, ref_label=None)` | `core/workflow/validator.py:19` | Extend (don't recreate) |
| `SchemaValidationError.to_diagnostics()` | `core/exceptions.py:165` | Free win — call directly from V1 |

### Renderer context-key dictionary (free wins)

The renderer in `core/diagnostic.py` already consumes these keys — producers that populate them get rich text output for free:

- `path` → `At: nodes[0].params.x` line via `_format_location`
- `node_type` → `Node type: <value>` via `_format_compilation_context_lines`
- `sub_workflow_path` → `Sub-workflow: <path>` line
- `similar_names: list[str]` → `Did you mean one of these?` block (truncate to ~5 yourself; renderer doesn't truncate)
- `available_fields` + `available_fields_total` + `available_fields_truncated` → `Available fields in node (showing N of M):` block (after gate broadening)
- `category="validation"` or `"template_error"` → drives title fallback via `_CATEGORY_TITLES`

Producers must NEVER set: `phase`, `exception_type`, `raw_response`, `mcp_error`, `shell_command`/`shell_stdout`/`shell_stderr`, `line` (these are runtime/exception/parser-only).

### Out of scope (do NOT touch)

- `prepare_inputs()` in `ir_preparation.py` — produces tuples routed through `SchemaValidationError`, separate code path
- `_raise_input_validation_errors()` in `compile_validation.py:40-66` — aggregates input errors into a single `SchemaValidationError`. Fixing this is a separate concern.
- `SchemaValidationError` — already self-describing via Task 141
- `prepare_inputs` test files — they test the orthogonal compiler path
- Existing single-string `WorkflowValidationError(str)` call sites in `manager.py` and `save_service.py` (~13 sites) — they continue to work via the empty-list fallback
- The runtime parser-warning propagation path in `WorkflowExecutor._propagate_child_parser_warnings` is touched ONLY for the `node_id` alignment fix (one line) — broader runtime path symmetry is a separate follow-up

### Plan review findings (verified during plan creation)

- The 4-agent plan review (review-plan, review-impact-completeness, review-feature-interactions, review-validation-consistency) caught:
  - **Critical**: `format_validation_failure()` doesn't delegate to `format_diagnostic()` — without rewriting it, the user-visible improvement reaches only JSON consumers
  - **Critical**: `WorkflowExecutor._propagate_child_parser_warnings:337` `node_id` asymmetry — locks in latent dedup bug if not fixed
  - **Confirmed**: compile_validation.py needs explicit error filter (defensive)
  - **Confirmed**: Plan needs full conversions for V9 and V11 (added)
  - **Confirmed**: 6 documentation files have signature drift
  - **Confirmed**: `_validate_data_flow` defensive wrapper is load-bearing (catches `TypeError` from malformed `Diagnostic.__post_init__`), not dead code

## Verification

### Pre-implementation grep audit

Run these greps before any code changes and save the output as `before-grep.txt`:

```bash
grep -rn "errors,\s*warnings\s*=\s*WorkflowValidator" tests/ src/
grep -rn "errors,\s*_warnings\s*=\s*WorkflowValidator" tests/ src/
grep -rn "errors,\s*_\s*=\s*WorkflowValidator" tests/ src/
grep -rn "errors,\s*warnings\s*=\s*validate_workflow_templates" tests/ src/
grep -rn "errors,\s*_warnings\s*=\s*validate_workflow_templates" tests/ src/
grep -rn "errors\s*=\s*validate_data_flow" tests/ src/
grep -rn "WorkflowValidationError(" src/ tests/
grep -rn "generate_validation_suggestions" src/ tests/
grep -rn "CycleError(" src/ tests/
```

Also capture rendering baseline:
```bash
uv run python .taskmaster/tasks/task_144/research/capture_baselines.py before
```

### Test scenarios

- `make test` passes after each commit (5-6 commits in suggested order)
- `make check` passes (mypy, ruff)
- All ~309 mechanical assertion rewrites pass without semantic changes
- The 1 semantic rewrite (`test_exception_to_diagnostics_workflow_validation_error_passes_through`) verifies Diagnostic pass-through
- Baseline comparison after Commit 1 (renderer change) shows zero drift on existing fixtures
- Baseline comparison after all commits shows additive improvements only (no rendering regressions)
- `tests/test_execution/test_runner.py::test_sibling_child_parser_warnings_not_collapsed_by_dedup` still passes (sub-workflow dedup)
- `tests/test_execution/test_runner.py::test_child_cache_lint_warning_propagates_to_parent_validation` still passes (sub-workflow propagation)

### Manual reproduction (acceptance criterion)

Create a workflow with an unknown node reference and run validate-only:

```bash
cat > /tmp/broken.pflow.md << 'EOF'
# Broken Workflow

This workflow references a non-existent node.

## Steps

### broken
Runs a command using a non-existent upstream node.

- type: shell
- command: echo ${nonexistant.stdout}
EOF

uv run pflow /tmp/broken.pflow.md --validate-only
```

Expected output (text mode, after `format_validation_failure` rewrite):
```
✗ Validation failed (1 error):

Error 1: Validation Error

Node 'broken' references non-existent node 'nonexistant' in parameter 'command'.
  At: node 'broken', nodes[0].params.command

  → Did you mean one of these?

(or similar — full unified format from format_diagnostic())
```

Expected JSON output:
```bash
uv run pflow /tmp/broken.pflow.md --validate-only --output-format json | jq '.diagnostics[0]'
```
```json
{
  "severity": "error",
  "message": "Node 'broken' references non-existent node 'nonexistant' in parameter 'command'.",
  "source": "validator",
  "title": "Validation Error",
  "node_id": "broken",
  "context": {
    "category": "validation",
    "path": "nodes[0].params.command",
    "available_fields": [...],
    "similar_names": [...]
  }
}
```

Acceptance: structured `context.path`, `context.available_fields`, `context.similar_names` fields present in JSON output. Text mode shows the unified `Error N: Title / message / At: / suggestions` format.

### Post-implementation grep verification

```bash
# Should return zero matches:
grep -rn "type: ignore\[arg-type\]" src/pflow/execution/runner.py
grep -rn "generate_validation_suggestions" src/
grep -n "isinstance(error, tuple)" src/pflow/core/exceptions.py
grep -rn "errors,\s*warnings\s*=\s*WorkflowValidator" src/  # production code only

# Should match the same count as before-grep.txt for surviving wraps= patterns:
grep -rn "wraps=WorkflowValidator" tests/
```

### Suggested commit structure

5-6 commits in this order, each leaving the codebase in a passing state:

1. **Renderer gate broadening** (`core/diagnostic.py` only) — isolated, additive, zero impact on existing fixtures
2. **`data_flow.py` + compiler consumer** + tests — bottom-up primitive
3. **Template validation layer** (`runtime/template_validation/*`) + tests — depends on layer 1
4. **`WorkflowValidator` outer layer + `WorkflowValidationError`** + tests — depends on layers 1+2 (the biggest commit)
5. **Consumer cleanup**: runner.py simplification + save_service.py + cli/main.py:631 + delete `generate_validation_suggestions` + capture_baselines.py + `format_validation_failure` rewrite + workflow_executor.py:337 fix + 6 doc files
6. **(Optional)** Add structured assertions to 5 high-value tests

## References

### Plan and research artifacts

- **Implementation plan**: `/Users/andfal/.claude/plans/crispy-dreaming-yao.md` — should be moved to `.taskmaster/tasks/task_147/implementation/plan.md` when implementation begins
- **GitHub issue**: spinje/pflow#219
- **Branch**: `fix/workflow-validator-return-type` (worktree: `/Users/andfal/projects/pflow-fix-workflow-validator-return-type`) — consider renaming to `feat/task-147-validator-diagnostics-natively` when implementation begins

### Prior task reviews (architectural context — read before implementing)

- `.taskmaster/tasks/task_141/task-review.md` — Exception hierarchy consolidation
- `.taskmaster/tasks/task_143/task-review.md` — Unified Diagnostic system, ExecutionResult/ValidationResult migration
- `.taskmaster/tasks/task_144/task-review.md` — Display consolidation, self-describing exceptions, names #219 as known debt

### Critical CLAUDE.md files

- `src/pflow/core/CLAUDE.md` — exception hierarchy table, validation_utils description
- `src/pflow/core/workflow/CLAUDE.md` — 9-step validator pipeline
- `src/pflow/runtime/template_validation/CLAUDE.md` — template validation design decisions, three regex patterns explanation
- `src/pflow/execution/CLAUDE.md` — runner pipeline and result types
- `src/pflow/execution/formatters/CLAUDE.md` — formatter rules ("return, never print")

### Producer enumeration (45 sites across 6 files)

The plan file contains a per-producer conversion specification with full before/after for the most complex helpers (V9, V11, V12, V16, PV3, TY1, TY2, TY3, BV1, BV2). Reference it during implementation rather than re-deriving.

### Renderer baseline tooling

`uv run python .taskmaster/tasks/task_144/research/capture_baselines.py before|after|compare` — Task 144's regression-detection tool. Mandatory to run before/after the renderer change in Commit 1.
