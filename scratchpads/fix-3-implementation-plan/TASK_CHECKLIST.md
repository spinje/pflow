# Fix 3: Implementation Task Checklist

## Overview

**Goal**: Implement schema-aware type checking for template variables
**Estimated Time**: 3-5 days
**Status**: Planning Complete ✅

---

## Phase 1: Core Type Logic (2 days)

### Task 1.1: Type Compatibility Matrix (4 hours)

- [ ] Create `src/pflow/runtime/type_checker.py`
- [ ] Implement `TYPE_COMPATIBILITY_MATRIX` dictionary
- [ ] Implement `is_type_compatible(source, target)` function
  - [ ] Handle exact matches
  - [ ] Handle source union types (all must match)
  - [ ] Handle target union types (any must match)
  - [ ] Handle matrix lookups
- [ ] Create `tests/test_runtime/test_type_checker.py`
- [ ] Write unit tests for type compatibility:
  - [ ] `test_exact_match()`
  - [ ] `test_int_to_float()`
  - [ ] `test_str_to_int_incompatible()`
  - [ ] `test_any_compatible()`
  - [ ] `test_union_source_all_must_match()`
  - [ ] `test_union_target_any_must_match()`
- [ ] Run tests: `uv run python -m pytest tests/test_runtime/test_type_checker.py -v`

**Acceptance Criteria**:
- ✅ All compatibility matrix tests pass
- ✅ Union type handling works correctly
- ✅ 100% code coverage for `is_type_compatible()`

---

### Task 1.2: Template Type Inference (6 hours)

- [ ] Implement `infer_template_type(template, workflow_ir, node_outputs)` in `type_checker.py`
  - [ ] Handle workflow inputs
  - [ ] Handle namespaced node outputs
  - [ ] Handle direct output lookups
  - [ ] Handle nested path traversal
- [ ] Implement `_infer_nested_type(path_parts, output_info)` helper
  - [ ] Handle no structure (base type check)
  - [ ] Handle structure traversal
  - [ ] Handle array indices in field names
  - [ ] Handle `any` type traversal
- [ ] Add unit tests:
  - [ ] `test_infer_simple_output()`
  - [ ] `test_infer_nested_field()`
  - [ ] `test_infer_array_access()`
  - [ ] `test_infer_unknown_field()`
  - [ ] `test_infer_with_any_type()`
  - [ ] `test_infer_workflow_input()`
  - [ ] `test_infer_namespaced_output()`
  - [ ] `test_infer_deep_nesting()`
- [ ] Run tests: `uv run python -m pytest tests/test_runtime/test_type_checker.py::test_infer* -v`

**Acceptance Criteria**:
- ✅ Correctly infers types for simple outputs
- ✅ Correctly traverses nested structures
- ✅ Handles array access in paths
- ✅ Returns `None` for unknown paths
- ✅ 90%+ code coverage for inference functions

---

### Task 1.3: Parameter Type Lookup (2 hours)

- [ ] Implement `get_parameter_type(node_type, param_name, registry)` in `type_checker.py`
  - [ ] Get node metadata from registry
  - [ ] Search params for matching key
  - [ ] Return type or None
- [ ] Add unit tests:
  - [ ] `test_get_parameter_type()`
  - [ ] `test_get_parameter_type_not_found()`
  - [ ] `test_get_parameter_type_invalid_node()`
  - [ ] `test_get_parameter_type_any_default()`
- [ ] Run tests: `uv run python -m pytest tests/test_runtime/test_type_checker.py::test_get_parameter* -v`

**Acceptance Criteria**:
- ✅ Correctly retrieves parameter types from registry
- ✅ Returns `None` for missing parameters
- ✅ Handles missing nodes gracefully
- ✅ 100% code coverage for `get_parameter_type()`

---

### Phase 1 Completion

- [ ] Run all Phase 1 tests: `uv run python -m pytest tests/test_runtime/test_type_checker.py -v`
- [ ] Verify 90%+ overall coverage: `uv run python -m pytest tests/test_runtime/test_type_checker.py --cov=src/pflow/runtime/type_checker`
- [ ] Code review: Check for edge cases and error handling
- [ ] Commit: `git commit -m "feat: implement core type checking logic"`

---

## Phase 2: Integration (1 day)

### Task 2.1: Type Validation Function (4 hours)

- [ ] Open `src/pflow/runtime/template_validator.py`
- [ ] Add imports from `type_checker`:
  ```python
  from pflow.runtime.type_checker import (
      infer_template_type,
      get_parameter_type,
      is_type_compatible
  )
  ```
- [ ] Implement `_validate_template_types()` static method
  - [ ] Iterate through workflow nodes
  - [ ] For each parameter with templates:
    - [ ] Get expected parameter type
    - [ ] Extract templates from parameter value
    - [ ] Infer each template's type
    - [ ] Check compatibility
    - [ ] Generate error if mismatch
  - [ ] Return list of error messages
- [ ] Add helper for error formatting (optional):
  - [ ] `_format_type_mismatch_error()`
  - [ ] Include suggestions for common cases (dict → str)

**Acceptance Criteria**:
- ✅ Function correctly identifies type mismatches
- ✅ Handles templates in string parameters
- ✅ Skips parameters without type constraints
- ✅ Returns clear error messages

---

### Task 2.2: Wire Into Validation Pipeline (2 hours)

- [ ] Modify `validate_workflow_templates()` in `template_validator.py`
- [ ] Add call to `_validate_template_types()` after path validation:
  ```python
  # 6. NEW: Type validation
  type_errors = TemplateValidator._validate_template_types(
      workflow_ir,
      node_outputs,
      registry
  )
  errors.extend(type_errors)
  ```
- [ ] Run existing tests to ensure no regressions:
  - [ ] `uv run python -m pytest tests/test_runtime/test_template_validator.py -v`
- [ ] Verify all existing tests still pass

**Acceptance Criteria**:
- ✅ Type validation integrated into existing pipeline
- ✅ All existing tests pass (no regressions)
- ✅ Type errors appear in validation output

---

### Task 2.3: Integration Tests (2 hours)

- [ ] Create `tests/test_runtime/test_template_validator_types.py`
- [ ] Implement integration tests:
  - [ ] `test_type_mismatch_detected()` - str → int mismatch
  - [ ] `test_dict_to_string_mismatch()` - dict → str (original bug!)
  - [ ] `test_compatible_types_pass()` - int → int OK
  - [ ] `test_int_to_float_compatible()` - int → float OK
  - [ ] `test_union_type_compatibility()` - dict|str → str
  - [ ] `test_any_type_always_compatible()` - any → anything
  - [ ] `test_nested_field_type_checking()` - nested structure types
  - [ ] `test_array_access_type_checking()` - array access types
  - [ ] `test_mcp_node_any_outputs()` - MCP nodes with any
  - [ ] `test_error_message_format()` - verify error formatting
- [ ] Run integration tests: `uv run python -m pytest tests/test_runtime/test_template_validator_types.py -v`

**Acceptance Criteria**:
- ✅ All integration tests pass
- ✅ Type mismatches correctly detected
- ✅ Compatible types pass validation
- ✅ Error messages are clear and helpful

---

### Phase 2 Completion

- [ ] Run all template validator tests: `uv run python -m pytest tests/test_runtime/test_template_validator*.py -v`
- [ ] Verify no regressions in existing validation
- [ ] Code review: Check integration logic
- [ ] Commit: `git commit -m "feat: integrate type checking into template validator"`

---

## Phase 3: Testing & Refinement (1-2 days)

### Task 3.1: Comprehensive Test Suite (1 day)

- [ ] Add edge case tests to `test_type_checker.py`:
  - [ ] Multi-level union types: `dict|str|int`
  - [ ] Complex nested structures (5 levels deep)
  - [ ] Array indices in middle of paths: `items[0].data.field`
  - [ ] Missing structure metadata
  - [ ] Invalid template paths
- [ ] Create end-to-end workflow tests in `tests/test_integration/test_type_checking_workflows.py`:
  - [ ] `test_github_pr_workflow()` - Real GitHub workflow with dict traversal
  - [ ] `test_slack_notification_workflow()` - Real Slack workflow with str params
  - [ ] `test_http_api_chaining()` - Chain multiple HTTP requests
  - [ ] `test_llm_json_workflows()` - LLM with JSON responses
  - [ ] `test_mixed_type_workflow()` - Complex workflow with many types
- [ ] Run full test suite: `uv run python -m pytest tests/ -v`
- [ ] Check coverage: `uv run python -m pytest tests/test_runtime/test_type_checker.py tests/test_runtime/test_template_validator_types.py --cov=src/pflow/runtime`

**Acceptance Criteria**:
- ✅ 85%+ overall test coverage
- ✅ All edge cases handled
- ✅ End-to-end workflows validate correctly
- ✅ No test failures

---

### Task 3.2: Real-World Validation (0.5 days)

- [ ] Test against example workflows (if they exist):
  - [ ] `uv run pflow validate examples/github-pr-analyzer.json` (if exists)
  - [ ] `uv run pflow validate examples/slack-notification.json` (if exists)
  - [ ] Create minimal test workflows if examples don't exist
- [ ] Verify no false positives on valid workflows
- [ ] Document any edge cases found
- [ ] Fix any issues discovered

**Acceptance Criteria**:
- ✅ Zero false positives on valid workflows
- ✅ Known type issues correctly detected
- ✅ All example workflows validate

---

### Task 3.3: Error Message Refinement (0.5 days)

- [ ] Review error message quality
- [ ] Add context-specific suggestions:
  - [ ] Dict → str: suggest field access or JSON serialization
  - [ ] Int → str: note automatic conversion
  - [ ] List → str: suggest joining or serialization
- [ ] Implement `_suggest_dict_fields()` helper (optional):
  - [ ] Parse structure to find available fields
  - [ ] Suggest top 3 string fields
- [ ] Update tests to verify improved messages
- [ ] Manual testing of error output

**Acceptance Criteria**:
- ✅ Error messages are clear and actionable
- ✅ Suggestions help users fix issues
- ✅ Error format is consistent

---

### Task 3.4: Performance Validation (2 hours)

- [ ] Create performance benchmark test
- [ ] Test with large workflow (50 nodes, 200 templates)
- [ ] Measure validation overhead:
  - [ ] `test_type_checking_performance()`
  - [ ] Assert <100ms overhead
- [ ] Profile if needed:
  - [ ] `uv run python -m cProfile -o profile.stats tests/test_runtime/test_template_validator_types.py`
  - [ ] Analyze with `snakeviz profile.stats`
- [ ] Optimize if necessary (cache lookups, early termination)

**Acceptance Criteria**:
- ✅ Type checking adds <100ms overhead
- ✅ Scales to 50+ node workflows
- ✅ No memory leaks

---

### Phase 3 Completion

- [ ] Run full test suite: `uv run python -m pytest tests/ -v`
- [ ] Run linter: `uv run ruff check src/pflow/runtime/type_checker.py`
- [ ] Run type checker: `uv run mypy src/pflow/runtime/type_checker.py`
- [ ] Code review: Final review of all changes
- [ ] Commit: `git commit -m "feat: add comprehensive type checking tests and refinements"`

---

## Final Steps

### Documentation

- [ ] Update `architecture/` docs if needed
- [ ] Add type checking examples to docs
- [ ] Document type compatibility rules
- [ ] Update CHANGELOG

### Code Quality

- [ ] Run full linter: `uv run ruff check src/`
- [ ] Run full type checker: `uv run mypy src/`
- [ ] Run full test suite: `uv run python -m pytest tests/`
- [ ] Verify coverage: `uv run python -m pytest tests/ --cov=src/pflow --cov-report=html`

### Review & Merge

- [ ] Self-review all changes
- [ ] Create pull request (if using PRs)
- [ ] Address review feedback
- [ ] Merge to main
- [ ] Tag release (if applicable)

---

## Success Checklist

### Functional
- [ ] Type mismatches detected at compile-time
- [ ] Compatible types pass validation
- [ ] Union types handled correctly
- [ ] Nested structures supported
- [ ] MCP `any` outputs handled gracefully
- [ ] Clear, actionable error messages

### Quality
- [ ] 85%+ test coverage
- [ ] Zero regressions in existing tests
- [ ] <100ms performance overhead
- [ ] No false positives on valid workflows

### Process
- [ ] All tests pass
- [ ] Linter passes
- [ ] Type checker passes
- [ ] Documentation updated
- [ ] Changes committed

---

**Status**: Ready to begin Phase 1! 🚀

**Next Action**: Create `src/pflow/runtime/type_checker.py` and start Task 1.1
