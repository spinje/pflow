# Implementation Order - Critical Path

## Goal
Refactor validation without breaking ANY existing tests while adding data flow validation to production.

## Critical Constraint
**Every commit must have all tests passing.** No temporary breakage allowed.

## Step-by-Step Implementation

### Step 1: Add New Module (No Integration)
**Branch**: `feature/add-data-flow-validation`

1. Create `/src/pflow/core/workflow_data_flow.py`
   - Copy `build_execution_order()` from test file
   - Copy `validate_data_flow()` from test file
   - Make it standalone, no dependencies on other pflow modules

2. Create `/tests/test_core/test_workflow_data_flow.py`
   - Test the new module in isolation
   - Ensure 100% coverage

**Verification**:
- Run: `pytest tests/test_core/test_workflow_data_flow.py`
- All existing tests still pass (nothing changed)

### Step 2: Create WorkflowValidator (No Integration)
**Same branch**

1. Create `/src/pflow/core/workflow_validator.py`
   - Implement WorkflowValidator class
   - Use existing validation functions
   - Don't modify any existing code yet

2. Create `/tests/test_core/test_workflow_validator.py`
   - Test WorkflowValidator in isolation
   - Mock Registry if needed

**Verification**:
- Run: `pytest tests/test_core/test_workflow_validator.py`
- All existing tests still pass (nothing changed)

### Step 3: Shadow Mode in ValidatorNode
**Same branch**

1. Modify `ValidatorNode.exec()`:
```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    """Execute validation."""
    workflow = prep_res.get("workflow", {})

    # OLD validation (keep working)
    errors_old = []
    errors_old.extend(self._validate_structure(workflow))
    errors_old.extend(self._validate_templates(workflow, prep_res))
    errors_old.extend(self._validate_node_types(workflow))

    # NEW validation (shadow mode)
    if os.getenv("USE_NEW_VALIDATOR", "false").lower() == "true":
        from pflow.core.workflow_validator import WorkflowValidator
        errors_new = WorkflowValidator.validate(
            workflow,
            extracted_params=prep_res.get("extracted_params", {}),
            registry=self.registry
        )

        # Log differences for debugging
        if set(errors_old) != set(errors_new):
            logger.debug(f"Validation difference: old={errors_old}, new={errors_new}")

        # Use new if enabled
        errors = errors_new
    else:
        errors = errors_old

    return {"errors": errors[:3]}
```

**Verification**:
- Run: `pytest tests/` - All pass with old validator
- Run: `USE_NEW_VALIDATOR=true pytest tests/` - Should also pass

### Step 4: Add Data Flow Tests to ValidatorNode
**Same branch**

1. Add new test cases to ValidatorNode tests:
```python
def test_validator_catches_data_flow_issues():
    """Test that ValidatorNode catches data flow issues when enabled."""
    os.environ["USE_NEW_VALIDATOR"] = "true"
    try:
        validator = ValidatorNode()
        workflow = create_workflow_with_forward_reference()
        prep_res = {"workflow": workflow, "extracted_params": {}}
        result = validator.exec(prep_res)
        assert any("forward" in str(e).lower() for e in result["errors"])
    finally:
        os.environ.pop("USE_NEW_VALIDATOR", None)
```

**Verification**:
- New tests fail with `USE_NEW_VALIDATOR=false` (expected)
- New tests pass with `USE_NEW_VALIDATOR=true` (validates feature works)

### Step 5: Update Test Files to Use WorkflowValidator
**Same branch**

1. Update `test_workflow_generator_prompt.py`:
```python
def validate_workflow(workflow: dict, test_case: WorkflowTestCase) -> tuple[bool, str]:
    """Validate using production WorkflowValidator."""
    # Try new validator if available
    try:
        from pflow.core.workflow_validator import WorkflowValidator
        uses_mock_nodes = "(mock)" in test_case.planning_context

        errors = WorkflowValidator.validate(
            workflow_ir=workflow,
            extracted_params=test_case.discovered_params,
            registry=Registry() if not uses_mock_nodes else None,
            skip_node_types=uses_mock_nodes
        )
    except ImportError:
        # Fall back to old validation
        errors = []
        # ... existing validation code ...

    # Test-specific checks remain
    # ...

    return len(errors) == 0, "; ".join(errors)
```

**Verification**:
- Run: `pytest tests/test_planning/llm/prompts/test_workflow_generator_prompt.py`
- Should pass with same accuracy

### Step 6: Switch to New Validator as Default
**Same branch**

1. Change ValidatorNode to use new validator by default:
```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    """Execute validation using WorkflowValidator."""
    from pflow.core.workflow_validator import WorkflowValidator

    workflow = prep_res.get("workflow", {})
    errors = WorkflowValidator.validate(
        workflow,
        extracted_params=prep_res.get("extracted_params", {}),
        registry=self.registry
    )

    return {"errors": errors[:3]}
```

2. Remove shadow mode code

**Verification**:
- Run: `pytest tests/` - All tests pass
- Run: `make test` - Full test suite passes

### Step 7: Clean Up
**Same branch**

1. Remove old validation methods from ValidatorNode:
   - Remove `_validate_structure()`
   - Remove `_validate_templates()`
   - Remove `_validate_node_types()`

2. Remove `validate_data_flow()` from test file (now using production)

3. Update imports in any affected test files

**Verification**:
- Run: `pytest tests/` - All tests still pass
- Run: `make check` - No lint/type errors

### Step 8: Documentation
**Same branch**

1. Update docstrings
2. Update CLAUDE.md files
3. Add migration notes

### Step 9: Performance Verification
**Before merge**

1. Benchmark validation time:
```python
import time
from pflow.core.workflow_validator import WorkflowValidator

# Load a complex workflow
workflow = load_complex_workflow()

start = time.time()
for _ in range(100):
    errors = WorkflowValidator.validate(workflow)
elapsed = time.time() - start

print(f"Average validation time: {elapsed/100*1000:.2f}ms")
assert elapsed/100 < 0.1  # Less than 100ms
```

## Rollback Points

At each step, we can rollback by:

1. **Step 1-2**: Just delete new files (no integration)
2. **Step 3-4**: Remove environment variable check
3. **Step 5**: Revert test file changes
4. **Step 6**: Switch back to old validator
5. **Step 7+**: Git revert the cleanup commit

## Risk Mitigation

1. **Feature Flag**: Use `USE_NEW_VALIDATOR` environment variable
2. **Shadow Mode**: Run both validators, compare results
3. **Incremental**: Each step is independently testable
4. **No Breaking Changes**: Old code works until we're ready

## Timeline

- **Day 1**: Steps 1-2 (Add new modules)
- **Day 2**: Steps 3-4 (Shadow mode)
- **Day 3**: Steps 5-6 (Switch to new)
- **Day 4**: Steps 7-8 (Cleanup)
- **Day 5**: Step 9 (Performance verification)

## CI/CD Considerations

1. Run tests with both validators in CI:
```yaml
- name: Test with old validator
  run: pytest tests/

- name: Test with new validator
  run: USE_NEW_VALIDATOR=true pytest tests/
```

2. Monitor for any differences in validation results

3. Gradual rollout using feature flag

## Definition of Done

- [ ] All existing tests pass without modification
- [ ] Data flow validation catches issues in production
- [ ] Performance impact < 100ms
- [ ] No code duplication
- [ ] Documentation updated
- [ ] Team review completed