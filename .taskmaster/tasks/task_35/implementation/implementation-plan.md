# Task 35 Implementation Plan: Template Syntax Migration

## Overview
Migrate from `$variable` to `${variable}` syntax across the entire pflow codebase. This is an atomic migration with no backward compatibility.

## Phase 1: Core Regex and Logic Updates (Critical Foundation)

### 1.1 Update Core Regex Patterns
- [ ] Update TEMPLATE_PATTERN in `template_resolver.py:24`
  - Old: `r"(?<!\$)\$([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)(?=\s|$|[^\w])"`
  - New: `r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:\.[a-zA-Z_][\w-]*)*)\}"`
- [ ] Update _PERMISSIVE_PATTERN in `template_validator.py:338`
  - Old: `r"\$([a-zA-Z_]\w*(?:\.\w*)*)"`
  - New: `r"\$\{([a-zA-Z_][\w-]*(?:\.[\w-]*)*)\}"`

### 1.2 Update Template Replacement Logic (Triple Braces!)
- [ ] Fix `template_resolver.py:181` - Change `f"${var_name}"` to `f"${{{var_name}}}"`
- [ ] Fix `template_resolver.py:192` - Change `f"${var_name}"` to `f"${{{var_name}}}"`

### 1.3 Update Log Messages
- [ ] Update log message at `template_resolver.py:183`
- [ ] Update log message at `template_resolver.py:194`
- [ ] Update log message at `template_resolver.py:200`

### 1.4 Update Docstring Examples
- [ ] Update examples in `template_resolver.py:137-142`

## Phase 2: Error Messages and Planner Updates (Critical for User Experience)

### 2.1 Update Error Messages in template_validator.py
Lines with error messages that need `${template}` → `${{{template}}}`:
- [ ] Line 218
- [ ] Line 245
- [ ] Line 253
- [ ] Line 259
- [ ] Line 260
- [ ] Line 264
- [ ] Line 283
- [ ] Line 291
- [ ] Line 292
- [ ] Line 296

### 2.2 Update Planning System
- [ ] Update error suggestions in `planning/nodes.py:1123`
- [ ] Update error suggestions in `planning/nodes.py:1125`
- [ ] **CRITICAL**: Update ALL examples in `workflow_generator.md` (12+ examples)
- [ ] Update any template examples in other prompt files

## Phase 3: Test Updates (Ensure Correctness)

### 3.1 Core Test Files
- [ ] Update `tests/test_runtime/test_template_resolver.py`
- [ ] Update `tests/test_runtime/test_template_validator.py`
- [ ] Fix expected "failures" in malformed template tests

### 3.2 Integration and Other Tests
- [ ] Update template usage in integration tests
- [ ] Update test fixtures and data files
- [ ] Search and update all test files with template assertions

## Phase 4: Documentation and Examples (User-Facing)

### 4.1 Documentation Updates
- [ ] Update all markdown files in `docs/` directory
- [ ] Update CLI reference documentation
- [ ] Update README files

### 4.2 Example Updates
- [ ] Update all JSON workflows in `examples/` directory
- [ ] Update any inline examples in source code comments

## Phase 5: Cleanup and Verification

### 5.1 Delete Saved Workflows
- [ ] Delete all files in `~/.pflow/workflows/`

### 5.2 Final Verification
- [ ] Run `make test` - all tests must pass
- [ ] Run `make check` - linting and type checking
- [ ] Test planner with real command: `uv run pflow "create a hello world script"`
- [ ] Verify generated workflow uses `${variable}` syntax
- [ ] Grep for any remaining `$variable` patterns (excluding escapes and prompt templates)

## Critical Reminders

1. **Triple Braces in F-Strings**: `f"${{{var_name}}}"` not `f"${var_name}"`
2. **Two Regex Patterns**: Both resolver AND validator must be updated
3. **Planner Prompt**: workflow_generator.md MUST be updated or planner will generate wrong syntax
4. **Atomic Migration**: No partial updates - everything or nothing
5. **Preserve Recent Fixes**: Don't break the regex lookahead fix or parameter injection

## Files to Update (By Category)

### Core Implementation (2 files)
- `src/pflow/runtime/template_resolver.py`
- `src/pflow/runtime/template_validator.py`

### Planning System (3+ files)
- `src/pflow/planning/nodes.py`
- `src/pflow/planning/prompts/workflow_generator.md`
- Other prompt files with examples

### Tests (50+ files)
- All test files containing template assertions
- Focus on test_runtime directory first

### Documentation (35+ files)
- All markdown documentation
- Example JSON files
- README files

## Success Criteria

✅ All 13 rules from spec implemented exactly
✅ All 14 test criteria pass
✅ No regressions in test suite
✅ Planner generates new syntax
✅ Examples like `data_${timestamp}.json` work
✅ No `$variable` syntax remains (except escapes)

## Risk Mitigation

- **Risk**: Missing occurrences
  - **Mitigation**: Use grep/ripgrep to find all instances

- **Risk**: Breaking recent fixes
  - **Mitigation**: Understand the three bugs fixed, test thoroughly

- **Risk**: Planner generating wrong syntax
  - **Mitigation**: Update workflow_generator.md completely

- **Risk**: Test failures from partial update
  - **Mitigation**: Update all tests in same phase

## Estimated Timeline

- Phase 1: 30 minutes (core changes)
- Phase 2: 30 minutes (errors and planner)
- Phase 3: 60 minutes (tests)
- Phase 4: 60 minutes (docs and examples)
- Phase 5: 15 minutes (cleanup and verify)
- Buffer: 30 minutes for issues

Total: ~3.5 hours

## Next Steps

1. Create progress log at `.taskmaster/tasks/task_35/implementation/progress-log.md`
2. Start with Phase 1 - Core regex updates
3. Test frequently with `pytest tests/test_runtime/test_template* -v`
4. Update progress log after each significant change