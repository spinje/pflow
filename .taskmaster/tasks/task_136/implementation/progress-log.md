# Task 136: Recursive Sub-Workflow Validation — Implementation Progress Log

## Implementation Steps

1. **Change 1:** Add `"inputs"` to `RESERVED_PARAMS` in `workflow_executor.py`
2. **Change 2a:** Fix `_validate_child_params()` required heuristic in `workflow_executor.py`
3. **Change 2b-d:** Fix 3 display bugs (context.py, discovery_formatter.py, mcp.py)
4. **Change 3a:** Add `_seen` parameter to `WorkflowValidator.validate()` signature
5. **Change 3b:** Add step 8 call in `validate()` method
6. **Change 3c:** Implement `_validate_sub_workflows()` static method
7. **Change 4a:** Thread `_pflow_workflow_file` into CLI `_perform_validation()`
8. **Change 4b:** Thread `_pflow_workflow_file` into MCP `validate_workflow()`
9. **Tests:** Write `test_sub_workflow_validation.py` (13 tests) + extend existing tests (3 tests) + E2E CLI test (1 test)
10. **Verification:** `make test` (4542 passed) + `make check` (all clean)

---

## Research Phase — COMPLETED

Deep investigation across multiple parallel research agents. Key findings documented in task-136.md and implementation-plan.md.

### Key findings that shaped the plan

- `_resolve_child_workflow_outputs()` already loads child IRs at validation time but swallows all errors (`except Exception: return None`)
- The "missing description" error is a parser-level check in `markdown_parser.py:1108-1120`, fires inside `parse_markdown()` — purely structural, no runtime values needed
- ~90% of validation errors are Category A (structural, no runtime values needed), ~5% Category B (needs input key names), ~5% Category C (needs actual runtime values)
- Mocking inputs with `generate_dummy_parameters()` enables Category A+B validation but doesn't help with Category C (lenient coercion by design)
- Static key comparison catches the most important Category C error (missing required inputs) without any mocking
- `_pflow_workflow_file` is already in `extracted_params` for execution paths, missing only in `--validate-only` and MCP validate paths
- `inputs` framework key (Task 161) leaks into child workflows — NOT in `RESERVED_PARAMS`
- Conflicting "required" heuristics between `_validate_child_params()` and `prepare_inputs()`
- 3 display bugs with wrong `.get("required")` defaults

### Discovered pre-existing bugs (fixing as part of this task)

1. `inputs` leaking through `_extract_child_inputs()` to child workflows
2. `_validate_child_params()` ignores `required` field, only checks `default` presence
3. `context.py:144-145` uses `.get("required", False)` — wrong default
4. `discovery_formatter.py:162` uses `.get("required")` — returns `None`
5. `cli/commands/mcp.py:612` uses `.get("required")` — returns `None`

---

## Implementation Phase — COMPLETED

### Change 1: RESERVED_PARAMS (workflow_executor.py) ✅

Added `"inputs"` to the `RESERVED_PARAMS` frozenset. Straightforward, no deviations from plan.

### Change 2: Required heuristic harmonization ✅

All 4 files fixed as planned. No deviations.

- `workflow_executor.py:378-380` — added `is_required = input_spec.get("required", True)` check
- `context.py:144-145` — `.get("required", False)` → `.get("required", True)`
- `discovery_formatter.py:162` — `.get("required")` → `.get("required", True)`
- `cli/commands/mcp.py:612` — `.get("required")` → `.get("required", True)`

### Change 3: Recursive sub-workflow validation (validator.py) ✅

**Deviations from plan:**

1. **`normalize_ir()` call required (not in plan).** The markdown parser does NOT emit `ir_version` in its output — consumers must call `normalize_ir()` after parsing. Without it, every file-based child workflow fails structural validation with `'ir_version' is a required property`. This matches the pattern in `cli/workflow_resolution.py:79` and `core/workflow/save_service.py:102`. Caught during test writing.

2. **Refactored into 3 methods instead of 1 (plan had single method).** The plan specified a single `_validate_sub_workflows()` method. Implementation was refactored into:
   - `_validate_sub_workflows()` — orchestrator (iterates nodes, runs input check + recursive validation)
   - `_load_child_workflow()` — dispatches to inline/file/saved-name loading
   - `_load_child_from_file()` — file-specific loading with path resolution

   **Why:** `ruff` C901 complexity check (max 10) rejected the single-method approach at complexity 19. The split also makes each concern independently testable.

3. **`_seen` set separated from input checking via `ir_cache` + `already_seen` flag (not in plan).** The plan used `_seen` for both cycle detection AND skipping already-validated children. This conflated two concerns: if two parent nodes reference the same child file with different params, the second node's input check was silently skipped. Fixed by:
   - `_load_child_workflow` returns a 5th element: `already_seen: bool`
   - When `already_seen=True`, the cached child_ir is returned from `ir_cache` so the input check still runs, but recursive validation is skipped
   - `ir_cache` is a local dict (not class-level) created in `_validate_sub_workflows`, avoiding cross-call pollution

4. **Lazy imports inside the 3 methods (matches plan intent but different organization).** All imports (`Path`, `is_workflow_file_reference`, `parse_markdown`, `WorkflowManager`, `WorkflowExecutor`, `normalize_ir`, `generate_dummy_parameters`) are lazy (inside method bodies) to avoid circular dependencies. Distributed across the 3 methods based on usage.

### Change 4: _pflow_workflow_file threading ✅

**4a — CLI `_perform_validation()`:** Added `source_file_path: str | None = None` parameter. Used `str | None` instead of `Optional[str]` per ruff UP045 (modern Python style). Removed the `Optional` import that the plan would have required.

**4b — MCP `validate_workflow()`:** Implemented as planned. Note: the variable name `wm_path` (for the WorkflowManager instance used only to get the path) could be clearer, but matches the existing code's pattern of creating fresh instances per-call.

**Pre-existing coverage in execution path:** Verified that `_validate_before_execution()` in the CLI execution path already receives `_pflow_workflow_file` via `enhanced_params` (set at `main.py:184`), so no change was needed there. The plan correctly identified this.

### Existing test update ✅

**`tests/test_cli/test_nested_workflow_cli.py:225`** — Updated assertion in `test_nested_workflow_missing_input_error`. The error message changed from runtime format (`"missing required inputs"`) to validation-time format (`"requires input ... but it is not provided"`). Updated assertion to accept either format for robustness.

---

## Test Phase — COMPLETED

### New test file: `tests/test_core/test_sub_workflow_validation.py` (13 tests)

| # | Test | What it catches |
|---|------|----------------|
| 1 | `test_broken_sub_workflow_caught_at_validation` | Parse errors (missing step description) from child .pflow.md |
| 2 | `test_valid_sub_workflow_passes` | Valid child produces zero errors |
| 3 | `test_nested_sub_workflow_validation` | 3-level nesting error attribution (parent → middle → broken grandchild) |
| 4 | `test_circular_reference_no_infinite_loop` | A → B → A cycle terminates gracefully |
| 5 | `test_missing_required_input_detected` | Child requires `text` + `count`, parent only provides `text` |
| 6 | `test_template_workflow_ref_skipped` | `workflow: ${dynamic_path}` skipped without error |
| 7 | `test_inline_workflow_ir_validated` | Inline `workflow_ir` dict with circular edges caught |
| 8 | `test_saved_workflow_name_validated` | WorkflowManager-saved workflow with forward-reference error |
| 9 | `test_sub_workflow_unknown_node_type_caught` | Child `type: totally-fake-node-type` via real Registry |
| 10 | `test_sub_workflow_data_flow_error_caught` | Child with circular `- next:` routing |
| 11 | `test_required_false_input_not_flagged` | `required: false` omitted by parent is OK |
| 12 | `test_sub_workflow_file_not_found` | Nonexistent .pflow.md file |
| 13 | `test_second_reference_missing_input_still_caught` | Two nodes → same child, second missing input **still** caught |

**Deviation from plan:** Plan specified 11 tests. Implementation has 13:
- Test 12 (`file_not_found`) was added by the test agent — simple but valuable boundary case.
- Test 13 (`second_reference_missing_input_still_caught`) was added after discovering the `_seen` conflation bug during review.

### Extended tests: `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py` (3 tests)

| # | Test | What it catches |
|---|------|----------------|
| 1 | `test_inputs_not_passed_as_child_input` | `"inputs"` excluded from `_extract_child_inputs()` |
| 2 | `test_required_false_no_default_not_rejected` | `required: false` with no default doesn't raise |
| 3 | `test_required_true_no_default_rejected` | `required: true` with no default does raise |

**Deviation from plan:** Plan specified 2 tests. Implementation has 3 — added the positive counterpart (`required: true` rejected) for completeness.

### E2E CLI test: `tests/test_cli/test_nested_workflow_cli.py` (1 test)

| Test | What it catches |
|------|----------------|
| `test_broken_sub_workflow_caught_before_execution` | **The exact reproduction case.** Parent has upstream LLM node → broken sub-workflow. Asserts: non-zero exit, error mentions sub-workflow issue, **zero LLM calls made** (proving error caught at validation time, not runtime). |

**Deviation from plan:** Not in the original plan. Added during review as the highest-value integration test — it's the only test that verifies the full CLI pipeline (file resolution → `_pflow_workflow_file` injection → WorkflowValidator step 8 → early exit before execution). Unit tests verify logic; this test verifies plumbing.

---

## Bugs Found During Implementation

### 1. Missing `normalize_ir()` call (caught during test writing)

**Root cause:** `_validate_sub_workflows()` passed child IR from `parse_markdown()` directly to `WorkflowValidator.validate()`. The markdown parser deliberately omits `ir_version` — all consumers must call `normalize_ir()`. Without it, every file-based child failed with `'ir_version' is a required property`.

**Fix:** Added `normalize_ir(child_ir)` after loading and before validation, guarded by `if not already_seen` (normalize only once per child).

### 2. `_seen` set conflating cycle detection with input checking (caught during review)

**Root cause:** When two parent nodes reference the same child file, `_seen` caused the second reference to return `child_ir=None`, skipping the static input check entirely. The second node's missing inputs would only be caught at runtime.

**Fix:** Added `ir_cache` dict and `already_seen` return flag. When a child is already in `_seen`, the cached IR is returned so the input check runs, but recursive validation is skipped.

### 3. YAML parse error in E2E test fixture (caught during test execution)

**Root cause:** The parent workflow markdown had `- prompt: Analyze this: ${query}` — the colon+space inside the value triggers YAML key-value parsing. Not a code bug, just a test authoring issue.

**Fix:** Quoted the value: `- prompt: "Analyze this: ${query}"`.

---

## Final Verification

```
make test  → 4542 passed
make check → all clean (ruff, ruff-format, mypy, deptry)
```

### Files modified (9 source + 3 test)

| File | Change |
|------|--------|
| `src/pflow/runtime/workflow_executor.py` | `"inputs"` in RESERVED_PARAMS; `required` heuristic fix |
| `src/pflow/core/workflow/validator.py` | `_seen` param, step 8 call, 3 new methods (`_validate_sub_workflows`, `_load_child_workflow`, `_load_child_from_file`) |
| `src/pflow/cli/main.py` | `_perform_validation()` accepts `source_file_path`, injects `_pflow_workflow_file` |
| `src/pflow/mcp_server/services/execution_service.py` | `validate_workflow()` injects `_pflow_workflow_file` |
| `src/pflow/core/workflow/context.py` | `required` default fix |
| `src/pflow/execution/formatters/discovery_formatter.py` | `required` default fix |
| `src/pflow/cli/commands/mcp.py` | `required` default fix |
| `tests/test_core/test_sub_workflow_validation.py` | **NEW** — 13 tests |
| `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py` | 3 new tests |
| `tests/test_cli/test_nested_workflow_cli.py` | 1 new E2E test + updated assertion |

---

## Code Review — COMPLETED

Full code review performed against the implementation plan. All 4 changes verified:

- **Change 1 (RESERVED_PARAMS):** `"inputs"` added with clear comment. Single consumer `_extract_child_inputs()` confirmed.
- **Change 2 (required heuristic):** All 4 files fixed. Harmonized to `input_spec.get("required", True)` matching `prepare_inputs()` and IR schema.
- **Change 3 (recursive validation):** 3-method split justified by C901. `ir_cache` + `already_seen` pattern handles duplicate references correctly. `normalize_ir()` call added (not in original plan — required because parser omits `ir_version`). Error prefixing chains cleanly through recursion.
- **Change 4 (`_pflow_workflow_file` threading):** CLI `_perform_validation()` and MCP `validate_workflow()` both inject file path into dummy params. Caller `_handle_validate_only_mode()` confirmed to pass `source_file_path`.

**Issues found:** None.

---

## Manual Testing — COMPLETED

13 manual tests run against real CLI with actual `.pflow.md` files.

### Bug reproduction (the fix)

| # | Test | Result |
|---|------|--------|
| 1 | Original bug: parent + broken sub-workflow (`parent-workflow.pflow.md`) | ✅ Instant failure: `"In sub-workflow './broken-sub-workflow.pflow.md' (step 'process-items'): Entity 'process' is missing a description"`. Zero LLM calls. |
| 2 | Deep nesting: parent → middle → broken grandchild (`deep-parent-workflow.pflow.md`) | ✅ Chained prefix: `"In sub-workflow './middle-workflow.pflow.md' (step 'create-songs'): In sub-workflow './broken-sub-workflow.pflow.md' (step 'broken-review'): ..."` |
| 3 | `--validate-only` on broken parent | ✅ Same error caught in validate-only mode |

### New validation capabilities

| # | Test | Result |
|---|------|--------|
| 5 | Parent forgets required child input (`text`) | ✅ `"requires input 'text' but it is not provided"` at validation time |
| 6 | Parent omits optional input (`required: false`) | ✅ No error, child executes fine |
| 7 | Child has unknown node type (`magical-unicorn-node`) | ✅ `"Unknown node type: 'magical-unicorn-node'"` with sub-workflow context |
| 8 | Child file doesn't exist (`./does-not-exist.pflow.md`) | ✅ `"sub-workflow file not found"` at validation time |

### Regression checks

| # | Test | Result |
|---|------|--------|
| 4 | Valid parent + valid child batch execution | ✅ 3/3 items succeeded, correct output |
| 9 | Batch + caching (run twice, second should cache) | ✅ Both runs produce correct output |
| 10 | `--validate-only` on valid parent | ✅ `"Workflow is valid"` |
| 11 | `--validate-only` on deep nesting (broken) | ✅ Full chain prefix in error |
| 12 | Existing example workflows (`examples/nested/`, `examples/bundling/`) | ✅ Both pass validation |
| 13 | JSON output format with broken sub-workflow | ✅ Structured JSON with `validation_errors` array containing sub-workflow error |

### Manual test files

Created in `scratchpads/sub-workflow-validation-bug/manual-tests/`:
- `valid-child.pflow.md` — valid child with required + optional inputs
- `valid-parent.pflow.md` — batch parent calling valid child
- `parent-missing-input.pflow.md` — parent omitting required child input
- `parent-optional-omitted.pflow.md` — parent omitting optional child input
- `child-bad-node-type.pflow.md` — child with unknown node type
- `parent-bad-node-type.pflow.md` — parent calling bad-type child
- `parent-nonexistent-child.pflow.md` — parent referencing nonexistent file

---

## External Code Review — COMPLETED

Review by Claude Opus 4.6. 3 warnings, 3 suggestions. No critical issues.

### Findings addressed

**W1 — `ir_cache` not shared across recursion levels (correctness gap):**
When a grandchild was validated during child recursion (level 2), its IR was cached in level 2's local `ir_cache`. If the parent (level 1) later referenced the same grandchild directly with insufficient inputs, the `seen` set said "already validated" but level 1's `ir_cache` didn't have the IR → `child_ir=None` → input check skipped entirely.

**Fix:** Added `_ir_cache` parameter to both `validate()` and `_validate_sub_workflows()`, threaded through recursive calls alongside `_seen`. Now all recursion levels share the same cache. Backward-compatible (optional param with `None` default). Added test `test_cross_nesting_reference_missing_input_caught` covering the exact scenario: parent node A → child → grandchild (validated here), parent node B → grandchild directly with missing input.

**W2 — Redundant `WorkflowManager()` in MCP service:**
`wm_path = WorkflowManager()` at line 390 was a second instantiation when `wm` from line 376 was still in scope. Replaced with `wm.get_path(...)`.

**W3 — Stale validation comment:**
"Run all 4 validation checks" comment replaced with "Run all validation checks (same as CLI)" to avoid going stale again.

### Suggestions not addressed (by design)

- **S1** (simplify path resolution guard) — cosmetic, touches correctness-adjacent code
- **S2** (MCP validate path test) — low risk, 4 lines of straightforward code
- **S3** (NamedTuple for return type) — cosmetic, only 2 call sites in same file

---

## Final Verification

```
make test  → 4543 passed (14 sub-workflow validation tests, +1 from review fixes)
make check → all clean (ruff, ruff-format, mypy, deptry)
```

### Files modified (final, 10 source + 3 test)

| File | Change |
|------|--------|
| `src/pflow/runtime/workflow_executor.py` | `"inputs"` in RESERVED_PARAMS; `required` heuristic fix |
| `src/pflow/core/workflow/validator.py` | `_seen` + `_ir_cache` params, step 8 call, 3 new methods |
| `src/pflow/cli/main.py` | `_perform_validation()` accepts `source_file_path`, injects `_pflow_workflow_file` |
| `src/pflow/mcp_server/services/execution_service.py` | `validate_workflow()` injects `_pflow_workflow_file`; reuse `wm`; fix stale comment |
| `src/pflow/core/workflow/context.py` | `required` default fix |
| `src/pflow/execution/formatters/discovery_formatter.py` | `required` default fix |
| `src/pflow/cli/commands/mcp.py` | `required` default fix |
| `tests/test_core/test_sub_workflow_validation.py` | **NEW** — 14 tests |
| `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py` | 3 new tests |
| `tests/test_cli/test_nested_workflow_cli.py` | 1 new E2E test + updated assertion |
