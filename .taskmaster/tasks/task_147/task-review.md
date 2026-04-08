# Task 147 Review: Validator Produces Diagnostics Natively

## Metadata

- **Implementation Date**: 2026-04-07
- **Branch**: `fix/workflow-validator-return-type`
- **Commits**: 4
  - `19292cdd` task files and context
  - `d8e7252c` full implementation
  - `0370b951` verification and improvements and fixes
  - `4fe37762` verification and code review fixes
- **GitHub issue**: spinje/pflow#219 (origin); closes #214; files #236, #237, #238, #239 as follow-ups
- **Pull Request**: not yet opened
- **Status**: implementation complete; `make test` 4664 passing; `make check` clean (ruff + ruff-format + mypy + deptry)
- **Prior task reviews required**: `task_141/task-review.md`, `task_143/task-review.md`, `task_144/task-review.md`

## Executive Summary

Task 147 completes the architectural arc started by Tasks 141 (exception hierarchy) → 143 (unified diagnostic type) → 144 (unified rendering). It converts all three validator layers (`WorkflowValidator.validate`, `validate_workflow_templates`, `validate_data_flow`) from returning flat strings or mixed `(errors: list[str], warnings: list[Diagnostic])` tuples into returning a single `list[Diagnostic]` built directly at the producer site. ~45 producer call sites across 6 files now build structured diagnostics natively with full `context["path"]`, `suggestions`, `similar_names`, and `available_fields` populated — ending the runner's string-fabrication loop and the pattern-matching `generate_validation_suggestions()` that reverse-engineered structure from flattened strings. The user-visible result: validation errors now render through the same `format_diagnostic()` path as runtime and compilation errors, with the same rich structure reaching both text and JSON consumers including the MCP server.

## Implementation Overview

### What Was Built

Three-layer producer conversion plus consumer cleanup, renderer extension, exception flattening, and bug fixes found during verification.

**Layer 1 — `src/pflow/core/workflow/data_flow.py`**: 6 producers converted. `CycleError` gained a structured `nodes_in_cycle` attribute (was parsing its own exception message). `_check_forward_reference` and `_validate_template_reference` now return `Optional[Diagnostic]` with `context["path"]` of form `nodes[id={node_id}].params.{param_name}`, fuzzy `similar_names`, and `available_fields`.

**Layer 2 — `src/pflow/runtime/template_validation/`** (4 files): 15 producers in `path_validation.py` (including the 76-line highest-value `_build_enhanced_node_diagnostic` / ex-`format_enhanced_node_error`), 3 in `type_validation.py` (type mismatch + shell single/multi blocked), 2 in `batch_item_validation.py` (BV1 top-level field + BV2 nested field), plus the orchestrator in `validator.py`. The dispatcher was renamed `create_template_error` → `create_template_diagnostic` and `_append_source_file_hint` → `_attach_source_file_hint` (now a `Diagnostic`→`Diagnostic` post-processor via `dataclasses.replace`).

**Layer 3 — `src/pflow/core/workflow/validator.py`**: 9 helpers + orchestrator converted. `SchemaValidationError` exceptions inside `_validate_structure` now route through `e.to_diagnostics()` directly (free win — exception already self-describes). `_format_node_not_found_error` → `_build_node_not_found_diagnostic`, `_format_template_node_error` → `_build_template_node_diagnostic`. `_validate_unknown_params` emits the richest single Diagnostic in the codebase (node_id + path + node_type + available_fields + similar_names + suggestions). `_add_child_provenance` was extended to handle both errors and warnings and uses `setdefault` for nested provenance keys (first-write-wins).

**Exception flattening — `src/pflow/core/exceptions.py`**: `WorkflowValidationError.validation_errors: list[Diagnostic]` (was `list[str | tuple[str, str, str]]`). `to_diagnostics()` simplified from ~30 lines of tuple/str branching to a pass-through. The 19 single-string callers in `manager.py` and `save_service.py` continue to work via the empty-list fallback. `CompilationError` gained an opt-in `wrapped_diagnostics: list[Diagnostic] | None` kwarg; when present, `to_diagnostics()` returns it directly so the compile-time path preserves structure without flattening to a bullet-list message.

**Consumer cleanup**:
- `src/pflow/execution/runner.py:_validate()` — deleted the string-fabrication loop and `generate_validation_suggestions` call, filters by severity, raises `WorkflowValidationError(validation_errors=errors)` without the old `# type: ignore[arg-type]`.
- `src/pflow/execution/formatters/validation_formatter.py` — rewritten to delegate to `format_diagnostic()` per error so the dominant CLI/MCP text path actually renders the new structured fields. **Without this rewrite, 90% of the work would have delivered only 10% of the user-visible value** (plan-review finding).
- `src/pflow/mcp_server/services/execution_service.py` — split the `(ValueError, WorkflowValidationError)` catch union into two branches; `WorkflowValidationError` now renders via `format_validation_failure(e.validation_errors)` so MCP save flow reaches parity with MCP validate flow.
- `src/pflow/core/workflow/save_service.py` — preserves structured diagnostics on `WorkflowValidationError` while keeping a short one-line summary for the exception text.
- `src/pflow/cli/main.py:631` — invalid-parameter-names path constructs a real `Diagnostic` (with `source="validator"`) instead of the old `(message, path, suggestion)` tuple.
- `src/pflow/runtime/compilation/compile_validation.py:_validate_data_flow_at_compile_time` — filters by `Severity.ERROR` before raising, uses `CompilationError(wrapped_diagnostics=errors)` to carry rich structure through the compiler boundary.

**Runtime parser-warning symmetry — `src/pflow/runtime/workflow_executor.py:_propagate_child_parser_warnings`**: aligned with the validator path. Uses `node_id=d.node_id or step_id` (preserves child ID) and `setdefault` for `sub_workflow_step` + conditional `sub_workflow_path`. Fixes a latent dedup asymmetry the plan would otherwise have locked in for errors.

**Renderer — `src/pflow/core/diagnostic.py`**:
- `_format_template_error_lines` → `_format_available_fields_block`, gate broadened from `context["category"] == "template_error"` to unconditional. The same block now serves all producer types.
- New context key `available_fields_label` with `"fields"` fallback. 12 producer sites each set their specific label: `outputs`, `nodes`, `parameters`, `inputs`, `required inputs`, `batch item fields`, `nested fields`, `matching outputs`. Headers now read e.g., "Available outputs (showing 5 of 13):" instead of the misleading "Available fields in node".
- New `source_file` rendering block in `_format_compilation_context_lines`: `Loaded from file: ./prompts/foo.md` — surfaces external file provenance when template producers attach it via `_attach_source_file_hint`.
- Dead code removed: `trace_file_hint` context key and the `available_fields_truncated` hint block were removed entirely (see round 6 of the progress log for rationale).

**In-scope bug fixes discovered during verification rounds**:
1. **First-write-wins `_add_child_provenance`**: 3-level nesting (parent → middle → grandchild) was overwriting `sub_workflow_step` and `sub_workflow_path` on recursion unwind, leaving structured provenance pointing at the OUTERMOST hop while `node_id` and `context["path"]` pointed at the DEEPEST. Fixed with `setdefault` so the innermost wrapping wins.
2. **Defensive wrappers setting `exception_type`**: Four `except Exception` wrappers in `_validate_structure`, `_validate_data_flow`, `_validate_templates`, `_validate_node_types` were setting `context["exception_type"]`, which renders as "Type: AttributeError" and makes validation errors look like runtime crashes. This directly contradicted the task's own "keys validator producers MUST NEVER set" rule. Fixed by removing the key; the message prefix ("Data flow validation error:" etc.) is sufficient provenance.
3. **`_format_path` malformed paths (closes pflow#214)**: For paths like `[0, "batch"]`, `_format_path` produced `[0]batch` instead of `[0].batch`. The dot-suppression guard `not formatted.endswith("]")` was wrong. One-line fix surfaced during manual reproduction of the batch unresolved-template case.
4. **Stale `src/pflow/core/workflow/CLAUDE.md:120`**: said "Unknown param warnings (warnings, not errors)" but `_validate_unknown_params` actually emits `Severity.ERROR`. Doc drift; updated.

**Post-implementation code-review fixes** (round 5):
1. **MCP `save_workflow` rich error preservation** (above).
2. **Renderer label ambiguity**: the deferred "Available fields in node" header became misleading after gate broadening. Fixed via `available_fields_label` context key + 12 producer updates + 4 pre-existing substring test updates.
3. **Runtime parser-warning context symmetry** (above).
4. **CLI `source="validation"` → `"validator"`**: `Diagnostic.__hash__` includes `source`; the CLI path used a different string than the rest, creating dedup asymmetry. 1-line fix.
5. **Stale `([], [])` mock fixture in `test_workflow_output_handling.py`**.

**Follow-up F2 applied in-scope**: `CompilationError.wrapped_diagnostics` kwarg (described above) — the only follow-up where the task 147 diff itself contained the anti-pattern the task was meant to eliminate (flattening structured validator diagnostics into a bullet-list message string).

**Documentation**: `src/pflow/mcp_server/services/CLAUDE.md:82` example, `src/pflow/core/CLAUDE.md` exception table + validation_utils paragraph + error handling philosophy section, `architecture/reference/template-variables.md` (signature + example), `src/pflow/core/workflow/CLAUDE.md` (P5 fix above). Root `CLAUDE.md` "Recently Completed" list updated to include Task 147.

### Implementation Approach

**Option D from the planning session** (user-approved). The four options considered were:
- **A**: outer layer only, wrap strings at inner boundary — rejected, leaves the highest-value cases bare
- **B**: both layers, keep the tuple return — rejected, adds churn without removing the artificial split
- **C**: phased (A now, B later) — **explicitly rejected because Task 143 took the pragmatic phased approach and Task 144 had to come back and fix it; the lesson is in the project history**
- **D**: full conversion across all three layers, single-list return, delete all the bridges (runner fabrication, `generate_validation_suggestions`, `# type: ignore`, tuple/str union in `WorkflowValidationError`) — chosen

The decisive criterion was the user's framing: **"prioritize simplicity of the final code, not how easy it is to get there."** Once Option D was on the table, the subsequent decisions cascaded deterministically: single list → no more tuple → `validation_errors: list[Diagnostic]` → delete `generate_validation_suggestions` → delete the fabrication loop → delete the `type: ignore`.

**Plan review loop**: before implementation, 4 parallel subagents (`review-plan`, `review-impact-completeness`, `review-feature-interactions`, `review-validation-consistency`) reviewed the plan. They caught 3 genuine critical bugs the planner had missed (`format_validation_failure()` under-rendering, `workflow_executor.py:337` dedup asymmetry, `compile_validation.py` missing severity filter) and 4 phantom concerns that verification disproved. The plan review took ~7 minutes wall clock and saved hours of post-implementation rework.

**Commit-structure deviation**: the plan suggested 5–6 logical commits (renderer, data_flow, template layer, outer validator, consumer cleanup, tests). The implementer collapsed them into one `full implementation` commit plus three verification-round follow-ups (4 total commits on branch). The collapse was justified by transition-state type errors — intermediate states (e.g., data_flow converted but template layer not yet) would have left mypy broken. The plan explicitly permitted this merge.

**Round accounting** (from progress log):
1. Planning session → task spec, plan, braindump
2. Implementation steps 1–5 → producer conversions, consumer cleanup, mechanical test migration
3. Post-fix test hardening (S1–S5) → 5 additional structural assertions
4. Manual verification round 1 → `make test` clean, text + JSON repro
5. Manual verification round 2 (specialist mode) → Bug 1 + Bug 2 + P2 + P5 found and fixed
6. 3-agent code review → 5 in-scope fixes + F2 + issue triage
7. Stale-review evaluation → trace hint removal + 2 doc updates + final state

## Files Modified/Created

### Core Changes (21 production files, ~1070 additions / ~707 deletions)

| File | What Changed |
|---|---|
| `src/pflow/core/diagnostic.py` | Gate broadening (rename `_format_template_error_lines` → `_format_available_fields_block`, unconditional dispatch), new `available_fields_label` key with `"fields"` fallback, `source_file` block added, dead `trace_file_hint` removed |
| `src/pflow/core/exceptions.py` | `WorkflowValidationError.validation_errors: list[Diagnostic]`, `to_diagnostics()` pass-through, `CompilationError.wrapped_diagnostics` kwarg |
| `src/pflow/core/ir_schema.py` | `_format_path` dot-insertion fix (closes pflow#214) |
| `src/pflow/core/validation_utils.py` | **Deleted** `generate_validation_suggestions()` (was 40 lines of pattern-matching reverse-engineering) |
| `src/pflow/core/workflow/data_flow.py` | All 6 producers return Diagnostics; `CycleError.nodes_in_cycle` structured attribute |
| `src/pflow/core/workflow/validator.py` | All 9 helpers + orchestrator return `list[Diagnostic]`; `_add_child_provenance` extended for errors+warnings with `setdefault` first-write-wins; `_build_node_not_found_diagnostic` / `_build_template_node_diagnostic` builders; 4 defensive wrappers no longer set `exception_type` |
| `src/pflow/core/workflow/save_service.py` | Preserves structured diagnostics on `WorkflowValidationError` |
| `src/pflow/runtime/template_validation/path_validation.py` | 15 producers converted; `format_enhanced_node_error` → `_build_enhanced_node_diagnostic`; `_append_source_file_hint` → `_attach_source_file_hint` (now Diagnostic post-processor) |
| `src/pflow/runtime/template_validation/type_validation.py` | 3 producers converted; `_generate_type_fix_suggestion` → `_generate_type_fix_suggestions` returning structured `(suggestions, available_fields)` |
| `src/pflow/runtime/template_validation/batch_item_validation.py` | 2 producers converted (`_build_batch_item_field_diagnostic`, `_build_batch_item_nested_diagnostic`) |
| `src/pflow/runtime/template_validation/validator.py` | Orchestrator returns `list[Diagnostic]`; TV1 (unused inputs) + TV2 (malformed templates) converted |
| `src/pflow/runtime/compilation/compile_validation.py` | Severity filter before raising, uses `CompilationError(wrapped_diagnostics=...)` |
| `src/pflow/runtime/workflow_executor.py` | `_propagate_child_parser_warnings` aligned with validator path (preserves child node_id, `setdefault` for provenance context) |
| `src/pflow/execution/runner.py` | Deleted string-fabrication loop + `generate_validation_suggestions` call + `# type: ignore[arg-type]`; filters by severity |
| `src/pflow/execution/formatters/validation_formatter.py` | Delegates to `format_diagnostic()` per error so unified titled format reaches text mode |
| `src/pflow/execution/executor_service.py` | Dead `trace_file_hint` block and `available_fields_truncated` assignment removed |
| `src/pflow/mcp_server/services/execution_service.py` | Split `(ValueError, WorkflowValidationError)` catch into two branches; MCP save flow now renders via `format_validation_failure` |
| `src/pflow/cli/main.py` | Invalid-parameter-names path constructs inline `Diagnostic` with `source="validator"` |
| `src/pflow/core/CLAUDE.md` | Updated exception usage table, validation_utils paragraph, error handling philosophy section |
| `src/pflow/core/workflow/CLAUDE.md` | Updated step 7 description (warnings→errors) |
| `src/pflow/mcp_server/services/CLAUDE.md` | Updated line 82 example for single-list return |

### Test Files (~57 files, ~981 additions / ~400 deletions)

**Critical structural guard tests added** (these are the ONLY tests that lock in the task's architectural contract — everything else is substring matching):

| Test | File | What It Locks In |
|---|---|---|
| `test_unknown_param_diagnostic_preserves_structure` | `test_core/test_unknown_param_validation.py` | V12 producer: node_id, path, available_fields, similar_names, suggestions |
| `test_json_rich_validation_error_preserves_context_fields` | `test_cli/test_validate_only.py` | JSON output contract end-to-end for agent consumers |
| `test_warning_only_data_flow_does_not_raise` | `test_runtime/test_compiler_basic.py` | `_validate_data_flow_at_compile_time` severity filter (dormant defensive) |
| `test_three_level_nesting_keeps_innermost_sub_workflow_provenance` | `test_core/test_sub_workflow_validation.py` | First-write-wins `_add_child_provenance` for deep nesting |
| 4 × `test_*_wrapper_diagnostic_has_no_exception_type` | `test_core/test_workflow_validator.py::TestDefensiveWrapperDiagnostics` | Defensive wrappers don't set `exception_type` |
| `test_dict_to_int_mismatch` (S1) | `test_runtime/test_template_validation/test_types.py` | TY1 type-mismatch producer structure |
| `test_batch_results_invalid_nested_path_rejected` (S2) | `test_runtime/test_template_validation/test_validator.py` | `_build_enhanced_node_diagnostic` batch case |
| `test_typo_suggestion` (S3) | `test_core/test_workflow_data_flow.py` | data_flow producer fuzzy suggestions |
| `test_path_access_on_declared_input_error` (S4) | `test_runtime/test_template_validation/test_enhanced_errors.py` | Declared-input path producer |
| `test_shell_blocks_dict_list_union` (S5) | `test_runtime/test_template_validation/test_types.py` | TY2 shell producer: 3 fix options + structured context |
| 5 × `test_format_path_*` | `test_core/test_ir_schema_output_suggestions.py::TestFormatPath` | pflow#214 regression guards |
| `test_real_batch_field_path` | Same file | End-to-end triggering of `_format_path` bug |

**Total structural coverage**: 13 tests. **Everything else** (~260 assertions across 19 files) goes through local `_split_validator_diagnostics` / `_split_template_diagnostics` helpers that flatten to rendered strings and verify substring matches against multi-line blocks. **This is documented technical debt (#238)** with a detailed follow-up plan at `.taskmaster/tasks/task_147/implementation/followup-238-test-helper-splits.md`.

## Integration Points & Dependencies

### Incoming Dependencies (what depends on this task)

| Component | Surface | Consumer Behavior |
|---|---|---|
| `execution/runner.py` `WorkflowRunner._validate()` | Calls `WorkflowValidator.validate()`, filters by `Severity.ERROR`, raises `WorkflowValidationError(validation_errors=errors)` | Severity filter is load-bearing; no longer wraps strings |
| `execution/runner.py` `WorkflowRunner.validate()` (validate-only entry) | Same — no fabrication, no pattern matching | Returns `ValidationResult(valid=..., diagnostics=...)` directly |
| `core/workflow/save_service.py::_validate_and_normalize_ir` | Builds `WorkflowValidationError(summary, validation_errors=errors)` | Structured diagnostics preserved for downstream rendering |
| `mcp_server/services/execution_service.py::save_workflow` | Catches `WorkflowValidationError`, renders via `format_validation_failure(e.validation_errors)` | Parity with validate_workflow path |
| `cli/main.py:631` | Constructs `Diagnostic` inline for invalid parameter names | `source="validator"` for dedup consistency |
| `runtime/compilation/compile_validation.py::_validate_data_flow_at_compile_time` | Calls `validate_data_flow`, filters errors, raises `CompilationError(wrapped_diagnostics=errors)` | Rich structure carried through compiler boundary |
| `runtime/workflow_executor.py::_propagate_child_parser_warnings` | Wraps child parser diagnostics using `format_child_provenance` + `setdefault` context | Identical dedup policy as validator path |
| `execution/formatters/validation_formatter.py::format_validation_failure` | Delegates to `format_diagnostic(error, error_number=i)` per error | Produces the same titled-error format as runtime/compilation errors |
| JSON output path (`--output-format json`) | Consumes `Diagnostic.to_dict()` / `to_display_dict()` | New fields (`node_id`, `context.path`, `context.available_fields`, `context.similar_names`) all reach JSON consumers automatically |

### Outgoing Dependencies (what this task depends on)

| Component | Surface | Used For |
|---|---|---|
| `core/diagnostic.py` `Diagnostic`, `Severity`, `format_child_provenance`, `deduplicate_diagnostics` | Data type + helpers | The target type every producer builds |
| `core/suggestion_utils.py` `find_similar_items` | Fuzzy matching | `similar_names` population in producers |
| `runtime/template_validation/utils.py` `find_similar_paths`, `sanitize_for_display`, `MAX_DISPLAYED_FIELDS` | Path matching + security | Template producers |
| `core/exceptions.py` `SchemaValidationError.to_diagnostics()` | Exception → Diagnostic | `_validate_structure` free win (already self-describes) |
| `dataclasses.replace` | Immutable context mutation | `_add_child_provenance`, `_attach_source_file_hint` |

### Shared Store Keys

| Key | Purpose | Touched By |
|---|---|---|
| `__parser_diagnostics__` | Accumulates child parser warnings with parent provenance | `runtime/workflow_executor.py::_propagate_child_parser_warnings` (writes), `execution/runner.py::_extract_runtime_warnings` (reads) |

No new shared store keys created. No changes to existing keys' shapes.

## Architectural Decisions & Tradeoffs

### Key Decisions

| Decision | Reasoning | Alternative Considered |
|---|---|---|
| **Option D** (full 3-layer conversion in one PR) | Task 143's phased approach accrued debt that Task 144 had to fix; repeat that lesson and #220 would have to come back. Final code simplicity > implementation ease. | Option A (outer only), Option B (both layers, keep tuple), Option C (phased) — all rejected |
| **Single-list return** (`list[Diagnostic]`) | Matches rustc/ruff/mypy/ESLint idiom; severity is a field, not a list identity. Once both errors and warnings are `Diagnostic`, the tuple is artificial separation. | Tuple `(errors, warnings)` — rejected as preserving an artifact of the old `list[str]` / `list[Diagnostic]` type split |
| **Delete `generate_validation_suggestions()` in full** | The whole point is to stop pattern-matching reverse-engineering. Its 4 dedicated tests verified edge cases that don't exist once suggestions come from the producer. | Keep as a fallback — rejected, defeats the purpose |
| **Use `format_child_provenance()` for sub-workflow error propagation** | Same helper warnings already use. Achieves error/warning symmetry Task 143 set up. | Separate helper per severity — rejected, reintroduces asymmetry |
| **Producer-supplied `available_fields_label`** (Option A from code-review round) | Producer owns the context; renderer stays dumb. One renderer line + 12 producer sites, each setting the right label (outputs/nodes/parameters/etc.). | Hardcode generic "options" in renderer (loses specificity for PV3); switch on category in renderer (couples renderer to category semantics); separate keys per case (three keys doing one key's job) |
| **First-write-wins for nested provenance** | Simpler than accumulating a chain; keeps structured fields aligned with `node_id` and `context["path"]` (both point at the deepest level). Future feature could add `sub_workflow_chain` if breadcrumbs are needed. | Accumulate chain — rejected as premature; last-write-wins — rejected, broke 3-level nesting test |
| **Remove trace hint entirely** (vs. gate on runtime path) | The hint was speculative value even when technically correct. Users find the actual trace file via the existing `"📊 Workflow trace saved: ..."` message at execution end. Removing simplifies final code AND removes dead `trace_file_hint` context key AND removes now-single-purpose `available_fields_truncated`. | Gate on runtime context; make producers opt-in |
| **`CompilationError.wrapped_diagnostics` kwarg** (F2 follow-up applied in-scope) | The only follow-up where the task 147 diff itself contained the anti-pattern. ~10 lines, keeps existing single-diagnostic contract for all other callers. | Restructure `CompilationError` (too broad); ignore (leaves the smell in task's own code path) |
| **Keep 4 defensive `except Exception` wrappers** | Load-bearing: they catch `TypeError` from `Diagnostic.__post_init__` when a producer passes `suggestions="string"` instead of `suggestions=["string"]`. Not dead code. | Delete as impossible — rejected after plan review |
| **Remove `exception_type` from those wrappers** (verification round) | The key renders as "Type: X" which makes validation errors look like runtime crashes. Message prefix ("Data flow validation error:") is sufficient provenance. | Keep as debug info — rejected, violates the task's own "keys validators MUST NEVER set" rule |

### Architectural Lineage (what this task inherits from 141/143/144)

Task 147 is the final node of a four-task arc. Every meaningful pattern in it has a specific origin, and reading the prior task reviews in isolation leaves gaps that this section exists to fill.

| Pattern / Decision | Origin | Why it mattered for Task 147 |
|---|---|---|
| **`core/exceptions.py` is a leaf module** (safe for module-level imports everywhere) | Task 141 | Enabled the clean `e.to_diagnostics()` dispatch in `_validate_structure` without lazy imports. Without 141, Task 147's producer conversions would each need their own lazy-import dance. |
| **`_pflow_node_id` annotation discriminator** (ValueError → `execution_failure` vs `validation`) | Task 141 | Task 147 inherits this automatically via `exception_to_diagnostics()` for any exception that reaches the validator wrapper. Don't touch it. |
| **"Producers populate `context`"** (the self-describing producer principle) | **Task 143** (for warnings), extended by Task 147 (for errors) | Task 143's spec originally said warning `context` was "always None"; the implementation deviated to `context={"template": "..."}` for agent-actionability. Task 147 extended the same deviation to every validator error site. **This means the pattern did NOT start with Task 147.** If a future agent is looking for the authoritative "why context over typed fields" argument, it's in Task 143's review under `context: dict | None instead of typed fields`. |
| **The Dual-Propagation-Path Problem** (child parser warnings flow through both validation AND runtime; same helper, identical format or dedup fails) | Task 143 (encountered for warnings) | Task 147 hit the **same bug class** for errors at `workflow_executor.py:337` — the plan review caught it as "the plan claims symmetry but only matches `node_id`, not context keys." This is the second time this bug class has surfaced in the arc. **Any future change to child-workflow propagation should read Task 143's "Dual-Propagation-Path Problem" section first** — it's a recurring failure mode, not a one-off. |
| **`Diagnostic.__hash__` excludes `context`** | Task 143 | Two diagnostics with identical core identity but different enrichment must dedup as the same. This is LOAD-BEARING for Task 147's child-workflow symmetry fix — if a future agent adds `context` to the hash to "improve equality," they silently break Task 147's dedup AND Task 143's warning dedup. |
| **`to_diagnostics()` on exception classes** (self-describing exceptions) | Task 144 | **This is NOT a reversal of Task 143's `format_for_cli()` deletion.** Task 143 removed `format_for_cli()` because it returned `str` and coupled exceptions to CLI rendering. Task 144 added `to_diagnostics()` because it returns `list[Diagnostic]` and couples exceptions to the data type only. Different concern, different coupling. A future agent reading only the git log will see "add method, remove method" and may think Task 144 reverted Task 143; it didn't. **Task 144's review has a dedicated section explaining this** — cite it in any commit message that touches exception `to_diagnostics()` methods. |
| **The three-layer model** (Exception typed → Data `Diagnostic` → Rendering one format) | Task 144 | Task 147 extends the producer source from "exception only" to "exception OR validation check OR runtime event," but the three-layer model itself is Task 144's contribution. When explaining the architecture to future agents, cite Task 144's review as authoritative, not Task 147. |
| **"The call site owns the context"** (enrich via `dataclasses.replace()` instead of pushing context into the renderer or dispatcher) | Task 144 | Task 147's `_add_child_provenance` and `_attach_source_file_hint` are direct applications: both use `dataclasses.replace()` to add provenance/source-file context at the enrichment site rather than in the renderer. If you're wondering why the validator doesn't just tell the renderer "this is a sub-workflow error", read Task 144's review section on this. |
| **`_diagnostic_category` class variable pattern** (polymorphic dispatch via field, not method override) | Task 144 (used for `UserFriendlyError` → `MCPError`) | Not used by Task 147, but it's a reusable pattern for exception class hierarchies that differ only in category. Mentioned here so future agents don't re-invent it. |
| **"Delete the bypass, bring the behavior into the unified pipeline"** | Task 144 (deleted `registry_run_formatter.py`) | Task 147 applied the **same playbook** to `format_validation_failure()`: instead of leaving it as a parallel renderer that only rendered 3 fields, the implementation rewrote it to delegate to `format_diagnostic()`. Task 144's review explains the principle: "The irony that sealed the decision: the bypass path provided BETTER guidance than the diagnostic path for simple errors." Task 147's inverse irony: the bypass path provided WORSE guidance than the diagnostic path once producers populated structure. Same lesson either direction — two renderers for the same diagnostic type is drift. |
| **`capture_baselines.py` regression tool** | Task 144 | Task 147 updated the fixture but inherited the tool wholesale. Task 144's review states it caught 3 rendering regressions "that all 4500+ tests missed" because tests check substrings while baselines compare full output. **This is structurally the same insight as the #238 smell**: substring matching is weaker than full-output comparison. Task 144's tool is the direct counter to #238's weakness. |
| **Option D over phased (Option C)** | Implicit rule from Task 143's own debt record | Task 143 explicitly took a pragmatic phased approach and marked `ValidationResult.errors: list[str]` as "Task 144 tracks unification." Task 144 had to come back and fix it. Task 147's plan review called out the same pattern: "Task 143 took the pragmatic shortcut and Task 144 had to fix it. The lesson is in the codebase history." **This is why Option D was chosen and why future refactors of this kind should resist phased approaches for the same reason.** |

**The load-bearing point**: if a future agent is working on any follow-up to this arc, they should read 141 → 143 → 144 → 147 reviews in that order, then the code. Skipping the prior reviews will cause them to re-invent decisions that have already been made and documented, or worse, to "fix" decisions without understanding why they exist.

### Technical Debt Incurred

| Item | Tracked As | Why Deferred |
|---|---|---|
| **19 `_split_*_diagnostics` test helpers flatten errors to rendered strings** — weakens assertion strength: substring matches against multi-line blocks are strictly more permissive than raw `.message` matches; structural fields (`context["path"]`, etc.) are not individually verified by the ~260 affected assertions | pflow#238 + detailed plan at `.taskmaster/tasks/task_147/implementation/followup-238-test-helper-splits.md` | Taking the mechanical shortcut kept the task 147 diff reviewable; the assertion-strength gap is a separate cleanup |
| CLI `pflow workflow save` bypasses `WorkflowValidator.validate()` entirely (only runs `validate_ir` schema check) | pflow#236 | Pre-existing. Task 147's new error filter at `save_service.py:139` is only reachable from MCP save path until this is fixed |
| Batch unresolved template (`batch: ${items}` in validate-only) crashes validators with `AttributeError` — caught by defensive wrappers but produces 3 confusing duplicated errors | pflow#237 | Pre-existing. Defensive wrappers catch it; the real fix is upstream type-checking |
| Sub-workflow + batch + `inputs: ${item}` false-positive validation failure | pflow#239 | Real bug, out of #219 scope, 3-line fix proposed |
| Multi-error text-mode truncation at 5 errors (`errors[:5]` cap in `validation_formatter.py`) | Intentional summary-mode behavior; JSON shows everything | Not debt; explicit design |
| Trace `set_warnings()` excludes `Severity.INFO` | Zero current impact (no producer emits INFO) | Not filing |

## Testing Implementation

### Test Strategy Applied

The test strategy had three distinct phases:

1. **Mechanical migration** (~260 assertions across 19 files). The implementer documented this as an "intentional deviation in mechanics, not in outcome": introduced local `_split_validator_diagnostics` / `_split_template_diagnostics` helpers that preserve the old `(errors, warnings)` tuple ergonomics but flatten errors to `format_diagnostic()` strings. The motivation was diff-size reduction. The cost was assertion-strength reduction — substring matches against multi-line rendered blocks are strictly weaker than matches against raw `.message`. **This is now tracked as pflow#238 with a follow-up plan.**

2. **Structural guards** (8 in closing PR + 5 S-series hardenings = 13 tests total). These are the ONLY tests that lock in the producer's context-field contract. Every rich producer family has at least one structural guard:
   - V6/V8/V9/V11/V12 (outer validator): `test_unknown_param_diagnostic_preserves_structure`, `test_json_rich_validation_error_preserves_context_fields`
   - PV3 (path_validation enhanced_node): S2
   - TY1/TY2 (type validation): S1, S5
   - data_flow: S3
   - Declared-input path: S4
   - Sub-workflow 3-level nesting: `test_three_level_nesting_keeps_innermost_sub_workflow_provenance`
   - Defensive wrappers: 4 × `TestDefensiveWrapperDiagnostics` tests
   - `_format_path` (pflow#214): 5 × `test_format_path_*` + 1 end-to-end
   - Compile-time severity filter: `test_warning_only_data_flow_does_not_raise`

3. **Manual verification**:
   - Round 1 (after implementation): `make test` + `make check` + text/JSON reproduction of a typo workflow
   - Round 2 (specialist try-to-break-it mode): testing plan at `.taskmaster/tasks/task_147/verification/manual-testing-plan.md`, executed against text + JSON + MCP + compile-time paths + 1/2/3-level nesting + sibling sub-workflows + multi-error rendering + batch unresolved template. Found Bug 1, Bug 2, P2, P5 this round.
   - Round 5 (post-code-review): re-verified the 5 in-scope fixes via manual repro.

### Critical Test Cases

The 13 structural guards listed above are the tests that actually prevent regressions. The other ~260 assertions test "rendered text contains substring X" which is strictly weaker than "producer populated field Y correctly." A producer regression where `context["path"]` becomes wrong, `.suggestions` becomes empty, or `.context["available_fields"]` becomes incomplete would NOT be caught by the substring-matching majority. Future agents modifying producers **should rely exclusively on the 13 structural guards for regression safety and treat the substring majority as aspirational.**

**Mutation-test example** recommended for any future structural-contract work: temporarily comment out a context key in a producer, confirm the structural test fails, restore, confirm it passes. If the test doesn't fail when the producer is broken, the assertion is too weak.

## Unexpected Discoveries

### Gotchas Encountered

1. **The issue body had a stale claim**: it said "the `run()` path doesn't have this problem because it raises `WorkflowValidationError` with tuple errors." Reading `runner.py:393` showed `WorkflowValidationError(validation_errors=errors) # type: ignore[arg-type]` where `errors` is `list[str]`. Both paths were equally bare. The correct framing changed the value proposition: fix both together rather than fix validate-only only. **Lesson**: verify every claim in the issue before agreeing with anything.

2. **`format_validation_failure()` was signature-correct but behaviorally incomplete**: it accepted `list[Diagnostic]` (type-correct since Task 144) but only rendered 3 fields (`error.message`, `error.context["path"]`, `error.suggestions[0]`). Title, node_id, available_fields, similar_names, additional suggestions were all silently dropped. **The planner initially missed this and claimed "no changes needed"** — the plan-review found it. Without the rewrite, 90% of the work would have delivered only 10% of the user-visible value. **Lesson**: when a claim is "formatter X already accepts the new type, no changes needed", read X's full body to verify it actually *renders* the new fields, not just accepts them at the boundary.

3. **`workflow_executor.py:337` dedup asymmetry**: the planner claimed "full symmetry with the warnings path via `format_child_provenance()`." Reviewers caught that "uses the same helper" ≠ "uses it the same way": validator path uses `w.node_id or step_id` (preserves child's), runtime path uses `node_id=step_id` (always overwrites). Same logical warning, different `Diagnostic.__hash__`, no dedup. **Lesson**: verify both sides of any symmetry claim, not just the shared helper.

4. **MCP `save_workflow` collapse**: `execution_service.py:358` caught `(ValueError, WorkflowValidationError)` as a single union and raised `ValueError(f"Invalid workflow: {e}")`. `f"{e}"` calls `WorkflowValidationError.__str__()` which is the joined-summary string. **All structured diagnostics died at this boundary** — the MCP save tool produced less rich output than the MCP validate tool despite running the same validator. Pre-task the catch was harmless; post-task it actively destroys new structure. **Lesson**: check exception catch handlers for union-catching + `str(e)` patterns; they flatten structure at the handler boundary.

5. **First-write-wins vs last-write-wins for nested context**: the initial `_add_child_provenance` used overwrite semantics (`new_context["sub_workflow_step"] = step_id`). For 3-level nesting (parent → middle → grandchild), each recursion unwind overwrote the keys, so the OUTERMOST hop won for `sub_workflow_step` but `node_id` and `context["path"]` still pointed at the DEEPEST. **Structured context diverged from location fields.** Fix: `setdefault`. **Lesson**: recursive code needs at least one test that exercises 2+ levels of recursion, or the unwind behavior is unverified.

6. **Defensive wrappers setting `exception_type` violated the task's own guideline**: the progress log explicitly listed `exception_type` under "Keys validator producers MUST NEVER set" because it renders as "Type: AttributeError" and makes validation errors look like unhandled runtime crashes. All four wrappers set it. **The implementer wrote the rule AND violated it in the same task.** Bug would have been invisible to anyone who just read either the guideline OR the wrapper code in isolation. **Lesson**: self-consistency checks catch bugs that single-file review misses.

7. **`_format_path` dot-suppression (pflow#214)**: for `[0, "batch"]`, the function produced `[0]batch` instead of `[0].batch` because the condition `if i > 0 and not formatted.endswith("]")` suppressed the dot when the previous component was an int. Pre-existing bug that surfaced during manual reproduction of the batch-unresolved-template case. One-line fix. **Lesson**: surfacing pre-existing bugs during manual verification is a positive side effect of try-to-break-it mode.

8. **Deferred decisions leak into user-visible output**: the "Available fields in node" renderer header was explicitly deferred in implementation step 3 with the note "matches the plan's explicit instruction to broaden the gate without redesigning the block text." After the gate broadened, the same hardcoded header rendered for node IDs ("Available fields in node (showing 5 of 10): nodeA, nodeB..."), workflow inputs, sub-workflow inputs, batch item fields. **Users saw misleading wording on the most common validator failures.** The deferral had a user-facing cost the moment the gate broadened. **Lesson**: when deferring a decision, check whether the deferral changes user-visible behavior. If it does, don't defer even if the plan says to.

9. **`trace_file_hint` was dead code in plain sight**: it was set by the runtime producer and never read by anything. It survived Task 143 (which authored it) and Task 144 (which touched the rendering pipeline extensively). Context coverage baselines even listed it as "Rendered indirectly via `available_fields_truncated`" — a comment that was wrong. **Lesson**: grep for readers as well as writers when auditing a context key's role.

### Edge Cases Found

- **Defensive wrappers catch `TypeError` from `Diagnostic.__post_init__`**: passing `suggestions="string"` instead of `suggestions=["string"]` raises `TypeError` in `__post_init__`. The 4 defensive wrappers catch this and produce a fallback diagnostic. They're not dead code — they protect against producer-construction mistakes.

- **Warning-severity diagnostics IGNORE context in the renderer**: `_format_warning_or_info_diagnostic` at `diagnostic.py:117` reads only `message`, `node_id`, and `suggestions`. A warning with `context={"path": "X"}` will NOT render the path. Warning producers must embed all info in `message` + `suggestions`. The existing `_warn_inputless_shell_nodes` is the reference pattern.

- **Nested templates in brackets like `${results[${__index__}].field}`** are invisible to the strict `TEMPLATE_PATTERN`; only the permissive `_PERMISSIVE_PATTERN` finds them. Path validation sees them; type validation doesn't. Acceptable because inner variables (typically `__index__`) resolve to primitives.

- **`SchemaValidationError.to_diagnostics()` free win**: `_validate_structure` in `validator.py` now does `return list(e.to_diagnostics())` directly instead of reconstructing the same information. This is the "self-describing exception" principle paying off.

- **Cross-sibling sub-workflow dedup**: `_add_child_provenance` adds parent step_id to `node_id` (via `d.node_id or step_id`) so siblings with identical child diagnostics don't collapse during dedup. Validated by `test_sibling_child_parser_warnings_not_collapsed_by_dedup`.

## Patterns Established

### Reusable Patterns

1. **Self-describing producers** (the load-bearing principle — **originated in Task 143 for warnings**, extended by Task 147 to errors):
   ```python
   # At the detection site — build the target type directly
   return Diagnostic(
       severity=Severity.ERROR,
       source="validator",
       title="Validation Error",
       node_id=node_id,
       message="<concise one-line problem>",
       suggestions=[...],
       context={
           "category": "validation",
           "path": f"nodes[id={node_id}].params.{param_name}",
           "available_fields": sorted(known),
           "available_fields_total": len(known),
           "available_fields_label": "parameters",
           "similar_names": similar or None,
       },
   )
   ```
   No string intermediate. No conversion layer. The renderer handles rendering. **If you want the authoritative "why context over typed fields" argument, see Task 143's review** — it has a dedicated section. Task 147 just extended the pattern; Task 143 established it.

2. **Producer-owned label + generic fallback for ambiguous renderer blocks**: `_format_available_fields_block` reads `context.get("available_fields_label", "fields")`. Each producer sets the specific label. Generic fallback is never technically wrong. This is how you keep renderers dumb while giving specific error messages.

3. **First-write-wins context merging for recursive wrapping**:
   ```python
   existing_context = diagnostic.context or {}
   new_context = dict(existing_context)
   new_context.setdefault("sub_workflow_step", step_id)
   if ref_label:
       new_context.setdefault("sub_workflow_path", ref_label)
   ```
   Use `setdefault`, not direct assignment, anywhere recursive wrapping adds context.

4. **Shared provenance helper + identical policy on both sides**: `format_child_provenance(step_id, message)` is used by both validation-time propagation (`_add_child_provenance` in validator) and runtime-time propagation (`_propagate_child_parser_warnings` in workflow_executor). Both use `node_id=d.node_id or step_id` and `setdefault` for context keys. **Dedup only works if both sides produce identical `Diagnostic.__hash__`** — same message, same node_id, same source, same severity.

5. **Explicit severity filter before truthiness check**:
   ```python
   diagnostics = validate_data_flow(ir)
   errors = [d for d in diagnostics if d.severity == Severity.ERROR]
   if errors:  # NOT `if diagnostics:`
       raise CompilationError(...)
   ```
   Defensive against future warning-severity producers in the same helper.

6. **Exception kwarg for structured-diagnostic passthrough across phase boundaries**:
   ```python
   class CompilationError(PflowError):
       def __init__(self, message, ..., wrapped_diagnostics: list[Diagnostic] | None = None):
           self.wrapped_diagnostics = wrapped_diagnostics

       def to_diagnostics(self) -> list[Diagnostic]:
           if self.wrapped_diagnostics:
               return list(self.wrapped_diagnostics)
           return [Diagnostic(...)]  # fallback
   ```
   Use this pattern whenever an exception wraps a list of already-structured diagnostics and you want them to survive the exception boundary.

7. **Three-layer architecture**: Producer → Data type → Rendering. Each layer has one job. If you find yourself conditionalizing the renderer on producer semantics, you're violating the layering.

8. **Plan-review loop as quality multiplier**: 4-agent parallel review (`review-plan`, `review-impact-completeness`, `review-feature-interactions`, `review-validation-consistency`) before implementation. ~7 minutes wall clock, ~10x ROI. 3 genuine critical bugs caught in Task 147's plan. Repeat this for any non-trivial refactor. (Task 141 used an 8-agent variant of the same loop and caught the `save_service.py:311` miss that the implementation spec's 6-agent research had explicitly claimed didn't exist. Same lesson: the plan-review loop catches things the planner missed, at ~10x ROI.)

9. **"Delete the bypass, bring the behavior into the unified pipeline"** (originated in Task 144 for `registry_run_formatter.py`, repeated by Task 147 for `format_validation_failure()`). When you find a parallel renderer that handles the same data type as an existing unified renderer, the default move is to delete the parallel one and migrate its unique behaviors (titles, suggestions, enrichment) into the unified path. Two renderers for the same type is drift — and Task 144's insight generalizes: "The bypass path provided BETTER guidance than the diagnostic path for simple errors." Bypass paths accumulate improvements because they're local and their authors don't have to touch the whole pipeline. The fix is to pull those improvements INTO the unified path, not leave the bypass. Task 147's `format_validation_failure()` rewrite is the inverse — the unified path had better structure, the bypass was rendering only 3 fields — but the playbook is identical.

### Anti-patterns to Avoid

1. **String intermediate between producer and display** — forces pattern-matching reverse-engineering downstream. (Validators used to do this; the deleted `generate_validation_suggestions()` was the reconstruction attempt.)

2. **Tuple `(errors, warnings)` return when both are the same type with severity as a field** — artificial separation; tests have to unpack; future consumers have to merge. Single list with severity filter is simpler.

3. **Defensive `except Exception` wrappers setting `exception_type`** in a validation context — renders "Type: AttributeError" and misleads users into thinking they hit a runtime crash.

4. **Catching exception unions and stringifying via `str(e)`** — flattens structured data at the handler boundary. If `WorkflowValidationError` has `validation_errors: list[Diagnostic]`, `str(e)` only returns the summary string. Split the catch or render explicitly.

5. **Gating a generic renderer block on a specific category** — prevents reuse. `_format_available_fields_block` was gated on `category == "template_error"` for a year even though the block is generic. Broadening the gate was a 1-line change.

6. **Deferring a design decision that has user-visible consequences** "for later" — the `available_fields_label` deferral caused misleading "Available fields in node" headers the moment the gate broadened. Deferrals that change user-visible output shouldn't be deferred.

7. **Truthiness check on heterogeneous-severity lists** (`if diagnostics:`) — silent bug trap for the first future producer that adds a warning-severity path.

8. **Mechanical test migration via local helpers that flatten to rendered strings** — preserves diff size but weakens assertion strength. See #238.

9. **Trusting that "X uses the same helper as Y"** means "X behaves the same as Y" — verify both call sites, not just the helper definition.

10. **Reading the issue body as ground truth** — the issue body for #219 had a stale claim about `runner.py`. Always re-verify the current code state.

## Breaking Changes

### API/Interface Changes

| Symbol | Before | After |
|---|---|---|
| `WorkflowValidator.validate()` | `tuple[list[str], list[Diagnostic]]` | `list[Diagnostic]` |
| `validate_workflow_templates()` | `tuple[list[str], list[Diagnostic]]` | `list[Diagnostic]` |
| `validate_data_flow()` | `list[str]` | `list[Diagnostic]` |
| All 9 `WorkflowValidator._validate_*` helpers | `list[str]` | `list[Diagnostic]` |
| All template validation sub-pass producers | `list[str]` or similar | `list[Diagnostic]` |
| `WorkflowValidationError.validation_errors` | `list[str | tuple[str, str, str]]` | `list[Diagnostic]` |
| `CycleError.__init__` | `(message: str)` | `(nodes_in_cycle: set[str])`, adds `.nodes_in_cycle` sorted list attribute |
| `CompilationError.__init__` | — | Adds `wrapped_diagnostics: list[Diagnostic] \| None = None` kwarg |
| `CompilationError.to_diagnostics()` | Returns `[single_diagnostic]` | Returns `list(wrapped_diagnostics)` if set, else fallback |
| `core/validation_utils.py::generate_validation_suggestions()` | Existed (~40 lines) | **Deleted** |
| `core/diagnostic.py::_format_template_error_lines` | Gated on `category == "template_error"` | Renamed `_format_available_fields_block`, unconditional dispatch |
| `runtime/template_validation/path_validation.py::format_enhanced_node_error` | Returns `str` | Renamed `_build_enhanced_node_diagnostic`, returns `Diagnostic` |
| `runtime/template_validation/path_validation.py::create_template_error` | Returns `str` | Renamed `create_template_diagnostic`, returns `Diagnostic` |
| `runtime/template_validation/path_validation.py::_append_source_file_hint` | `str → str` | Renamed `_attach_source_file_hint`, `Diagnostic → Diagnostic` via `dataclasses.replace` |
| `core/workflow/validator.py::_format_node_not_found_error` | Returns `str` | Renamed `_build_node_not_found_diagnostic`, returns `Diagnostic` |
| `core/workflow/validator.py::_format_template_node_error` | Returns `str` | Renamed `_build_template_node_diagnostic`, returns `Diagnostic` |
| `Diagnostic` context key `available_fields_label` | Not used by renderer | Read by `_format_available_fields_block` with `"fields"` fallback |
| `Diagnostic` context key `trace_file_hint` | Written by `executor_service.py`, read by nothing | **Removed** (dead code) |
| `Diagnostic` context key `available_fields_truncated` in validation paths | Written but meaningless | Removed from validation-time producers |

### Behavioral Changes

1. **Validation errors render via `format_diagnostic()`**: text mode now shows title / message / `At:` location / `Did you mean` block / `Available X` block / `→ suggestion` — same shape as runtime and compilation errors. Before: bare strings with generic ℹ fallback.

2. **JSON output includes rich structured fields**: `context.path`, `context.available_fields`, `context.similar_names`, `context.node_type`, `context.template`, `node_id`, `title` all reach JSON consumers automatically because `Diagnostic.to_dict()` already serialized them.

3. **MCP `save_workflow` error text**: now multi-line titled format (parity with `validate_workflow`). Was joined-summary string.

4. **Renderer block headers now read "Available {outputs/nodes/parameters/...}"** instead of "Available fields in node". 12 producer sites each set the correct label.

5. **Sub-workflow parser warnings preserve child `node_id` during runtime propagation** (was overwritten with parent step_id). Fixes latent dedup asymmetry with validator path.

6. **Three-level sub-workflow errors have structured provenance fields pointing at the innermost level** (`node_id`, `context["path"]`, `sub_workflow_step`, `sub_workflow_path` all align). Was: provenance fields at outermost, node_id/path at innermost — inconsistent for JSON consumers.

7. **Compile-time data flow errors preserve structure** via `CompilationError.wrapped_diagnostics`. Before: flattened to bullet-list message string.

8. **Validate-only JSON now exposes the full agent-visible contract**: downstream LLM agents parsing `--validate-only --output-format json` see all the structural fields. Locked in by `test_json_rich_validation_error_preserves_context_fields`.

## Future Considerations

### Extension Points

1. **Apply the self-describing producer pattern to `prepare_inputs()`** (`runtime/compilation/ir_preparation.py`). It still produces `list[tuple[str, str, str]]` routed through `SchemaValidationError` — separate code path, out of scope for #219 but a direct candidate for the same treatment. Fixing it would improve compiler input error quality and complete the "no more string intermediates" principle.

2. **`_raise_input_validation_errors` in `compile_validation.py:40-66`** aggregates multiple input errors into a single `SchemaValidationError` with a combined message, losing per-error structure. Same shape as the bug task 147 just fixed in `_validate_data_flow_at_compile_time` — apply the `wrapped_diagnostics` pattern.

3. **Follow-up #238 (test-helper splits)** has a detailed plan ready at `.taskmaster/tasks/task_147/implementation/followup-238-test-helper-splits.md`. Lifts local helpers to `tests/shared/diagnostic_helpers.py` with typed Diagnostic return, sweeps 19 files to use `.message`, promotes 5 high-value files to structural assertions.

4. **Broader runtime path symmetry** with the validator path: this PR touched `_propagate_child_parser_warnings` for the `node_id` + context alignment fix only. Full symmetry (extracting shared logic between `_add_child_provenance` and `_propagate_child_parser_warnings`) is a future cleanup.

5. **`Registry.get_all_node_types()`**: the current unknown-node-type validator (V6) only fuzzy-matches against the queried metadata subset, not the full registry. Broadening fuzzy matching to the full registry would catch more typos but requires a new Registry API. Out of scope for #219; good candidate for a future small task.

6. **`Diagnostic.to_display_dict()` is orphan transitional debt from Task 143**. Task 143's review explicitly marked it as a "transition bridge for text consumers that receive dicts instead of Diagnostics" with the future plan to "eliminate `to_display_dict()` when all display code reads from Diagnostic attributes directly." Task 144 was expected to help; Task 147 inherited it unchanged. It still exists because some JSON output paths expect context keys merged to top level (`error["category"]` etc.) for backward compat. A future cleanup should audit the `to_display_dict()` callers and migrate them to read from `diagnostic.context["X"]` directly. Search for `.to_display_dict()` in the codebase — there are a handful of call sites. This is not urgent but it's a latent code-path divergence: `to_dict()` (structured JSON) and `to_display_dict()` (flat JSON) can drift if a future Diagnostic field is added without updating both.

### Scalability Concerns

- **Diagnostic allocation per validation pass**: worst-case workflow produces ~309 Diagnostics. Validation is not a hot path. Not a concern until benchmarks show CI regressions.
- **`deduplicate_diagnostics` is O(N)** with hash comparison. Fine for validator-sized output.
- **Renderer construction cost** for rich diagnostics (similar_names block, available_fields block, suggestions block) scales linearly with the number of fields. Not a concern at current workflow sizes.

## AI Agent Guidance

### Quick Start for Related Tasks

**If you're converting another producer layer (exception class, validator, runtime event) to return `Diagnostic` directly**, read in this order (~1 hour). Do NOT skip the prior reviews — each was picked because it contains a specific section that preempts a specific failure mode for this kind of refactor.

1. `task-147.md` — the spec (architectural framing)
2. **Task 141's review** (`task_141/task-review.md`) — specifically the **"`core/exceptions.py` is a leaf module" insight**. This is the enabling precondition for the whole arc. Without it, `e.to_diagnostics()` dispatch from validators requires lazy imports. Also read the "Process note" at the end — it documents the 8-agent parallel review that caught the `save_service.py:311` miss; the same loop caught Task 147's 3 critical bugs.
3. **Task 143's review** (`task_143/task-review.md`) — specifically **"The Dual-Propagation-Path Problem"** section under Unexpected Discoveries. Task 143 first hit this for warnings. Task 147 hit the same bug class for errors at `workflow_executor.py:337`. A future propagation change will hit it again unless you know to look for it. Also read **"`context: dict | None` instead of typed fields"** under Key Decisions — this is the origin of the "producers populate `context`" pattern Task 147 extends from warnings to errors.
4. **Task 144's review** (`task_144/task-review.md`) — specifically **"Why `to_diagnostics()` is NOT a reversal of Task 143"**. A future agent reading the diff without this framing will think `to_diagnostics()` contradicts `format_for_cli()`'s deletion and may try to "fix" it. Also read **"The call site owns the context"** section under Architectural Decisions — this is the origin of the `dataclasses.replace()` enrichment pattern Task 147 uses in `_add_child_provenance` and `_attach_source_file_hint`. And **"Why registry_run_formatter was in scope"** — Task 147 applied the same "delete the parallel renderer, bring the behavior INTO the unified pipeline" playbook to `format_validation_failure`.
5. `src/pflow/core/diagnostic.py` — the full data type, renderer, `_format_all_context_blocks`, `_CATEGORY_TITLES`, keys-producers-must-never-set. This is the contract.
6. `src/pflow/core/workflow/validator.py` — one complete producer layer (10 helpers) with the pattern applied end-to-end. Read `_validate_unknown_params` as the canonical rich-diagnostic example.
7. `src/pflow/runtime/template_validation/path_validation.py::_build_enhanced_node_diagnostic` — the highest-value single-producer conversion. Shows path/type/similar_names/suggestions all working together.
8. `.taskmaster/tasks/task_147/implementation/progress-log.md` — skim the "Meta-learnings" and "Plan review findings" sections only (not the full implementation diary).

**If you're extending the renderer**, read:
- `_format_all_context_blocks` dispatcher in `diagnostic.py` (universal — called for every error)
- `_format_available_fields_block` for the producer-label pattern
- `_CATEGORY_TITLES` dict for title fallback via category
- "Keys validator producers MUST NEVER set" section in Task 147's implementation plan (`phase`, `exception_type`, `raw_response`, `mcp_error`, `shell_*`, `line`)

**If you're touching runtime parser-warning propagation**, read:
- `runtime/workflow_executor.py::_propagate_child_parser_warnings`
- `core/workflow/validator.py::_add_child_provenance`
- `core/diagnostic.py::format_child_provenance`
- Both sides must use identical policies: `node_id=d.node_id or step_id`, `setdefault` for context, same message prefix format. If you break the symmetry, dedup silently fails.

**If you're working on the test-helper cleanup (#238)**, the plan is already written:
- `.taskmaster/tasks/task_147/implementation/followup-238-test-helper-splits.md`

### Common Pitfalls

1. **"Formatter X already accepts `list[Diagnostic]`, no changes needed"** — verify by reading the formatter's body, not just its signature. `format_validation_failure()` was type-correct and behaviorally incomplete.

2. **Catching exception unions + `str(e)`** flattens structured data at the handler boundary. If you have `except (ValueError, WorkflowValidationError) as e: raise RuntimeError(str(e))`, you're destroying structure. Split the catch.

3. **`any("X" in e for e in errors)` on a `list[Diagnostic]`** — `e` is a Diagnostic, not a string. Needs `.message`. (This is the #238 smell; don't perpetuate it.)

4. **Recursive context merging with direct assignment** — use `setdefault`. The 3-level nesting bug was exactly this.

5. **Defensive `except Exception` wrappers setting `exception_type`** in a validation context — renders "Type: AttributeError" and makes validation errors look like runtime crashes. Don't populate it.

6. **Gating a generic renderer block on a specific category** — prevents reuse. If the block is generic (available fields, similar names), don't gate it on category.

7. **Truthiness check on heterogeneous-severity lists** (`if diagnostics:`) — filter by severity explicitly or you'll trap future warning producers.

8. **Trusting reviewer findings without verification** — ~30% false-positive rate in both plan-review and code-review rounds of Task 147. Every finding is a hypothesis. Verify via targeted grep or 1-minute repro before filing or fixing.

9. **Asserting structure that depends on implementation details** (e.g., exact order of `available_fields`) — assert on set membership instead of list equality. Locks in the contract without making the test brittle.

10. **Deferring design decisions that have user-visible consequences** — the "Available fields in node" header deferral is the cautionary tale. If your deferral changes rendered output, don't defer.

### Test-First Recommendations

When modifying producers in this codebase:

1. **Write a structural test first**. Construct a workflow that triggers the producer, run it via `python -c "from ... import ...; for d in validate(...): print(d.context)"`, capture the actual shape, then assert on specific context fields.

2. **Mutation-test before declaring done**. Temporarily comment out one context key in the producer, confirm your structural test fails, restore, confirm it passes. If the test doesn't fail when the producer is broken, the assertion is too weak.

3. **Run `make check` early and often**. Mypy is the strongest signal that producer/consumer contract matches. The `# type: ignore[arg-type]` removal in Task 147 was a mypy-verified cleanup.

4. **Manual reproduction in three modes**: text (`pflow broken.pflow.md --validate-only`), JSON (`--output-format json`), MCP (via `workflow_validate` and `workflow_save` tools). Three separate consumers, three separate paths that must all preserve structure. Task 147 found the MCP save flow was collapsing structure only because of this three-mode verification.

5. **For recursion code, write at least one 2+-level-nested test**. One-level passes don't prove unwind behavior. Task 147's 3-level-nesting test caught a bug the one-level tests missed.

6. **Run the 4-agent plan-review loop before non-trivial refactors**. `review-plan`, `review-impact-completeness`, `review-feature-interactions`, `review-validation-consistency`. ~7 minutes, ~10x ROI. Task 147 would have shipped 3 silent regressions without it.

7. **Run `capture_baselines.py before/after/compare` around any rendering change**. Task 144 introduced this tool at `.taskmaster/tasks/task_144/research/capture_baselines.py`; Task 147 inherited it. It compares **full rendered output** for ~21 fixtures across multiple rendering paths. Task 144's review: the tool "caught 3 real regressions in registry bypass paths that all 4500+ tests missed — because the tests check for substrings like 'not found' while the baselines compare full output quality." Substring-matching tests are strictly weaker than full-output comparison, and `make test` will silently pass on a rendering regression that the baseline tool catches. Task 147's verification used this tool; any task that touches `diagnostic.py`, `format_diagnostic()`, or any `_format_*` helper should too.

   ```bash
   uv run python .taskmaster/tasks/task_144/research/capture_baselines.py before
   # ... make changes ...
   uv run python .taskmaster/tasks/task_144/research/capture_baselines.py after
   uv run python .taskmaster/tasks/task_144/research/capture_baselines.py compare
   ```

   **This is also the direct counter to the #238 smell** (19 test helpers flatten errors to rendered strings and substring-match against multi-line blocks — strictly weaker than structural assertions). If you're working on #238's follow-up plan, run the baseline tool in Phase 2 (mechanical sweep) to catch any accidental rendering regression that the substring-matching tests will miss.

---

*Generated from the progress log, implementation plan, braindump, task spec, git history, and a full reading of the 21 production files modified by Task 147. Commit references: `19292cdd`..`4fe37762` on branch `fix/workflow-validator-return-type`.*
