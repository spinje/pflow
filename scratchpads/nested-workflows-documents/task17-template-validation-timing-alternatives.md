# Task 17: Template Validation Timing Alternatives

## Context

Template validation ensures that all template variables (e.g., `$issue_number`, `$issue_data.user.login`) in a workflow can be resolved at runtime. This validation is critical for the "Plan Once, Run Forever" philosophy - workflows must be valid and reusable.

Based on codebase analysis, there are two types of validation:
1. **Structure Validation** (`validate_ir()`) - Checks JSON schema compliance, node references, duplicate IDs
2. **Template Validation** (`TemplateValidator.validate_workflow_templates()`) - Checks template variables can be resolved

## Current Implementation

The runtime compiler (`compile_ir_to_flow()`) performs both validations when `validate=True` (default):
```python
# Step 2: Validate structure first
validate_ir(ir_dict)

# Step 3: Validate templates can be resolved
if validate:
    errors = TemplateValidator.validate_workflow_templates(ir_dict, initial_params, registry)
    if errors:
        raise ValueError(error_msg)
```

## Alternative Approaches

### Alternative 1: Planner Validates Everything (Eager Validation)

**Description**: The planner's ValidatorNode performs both structure and template validation immediately after generation.

**Implementation**:
```python
class ValidatorNode(Node):
    def exec(self, prep_res):
        workflow = prep_res["workflow"]
        registry = prep_res["registry"]
        params = prep_res["parameter_values"]

        # 1. Structure validation
        validate_ir(workflow)

        # 2. Template validation
        errors = TemplateValidator.validate_workflow_templates(
            workflow, params, registry
        )

        if errors:
            return {"is_valid": False, "errors": errors}
        return {"is_valid": True}
```

**Pros**:
- Early error detection - invalid workflows never leave the planner
- Immediate feedback for retry logic - can fix template errors during generation
- Single validation point - clear responsibility
- Better user experience - errors caught before approval

**Cons**:
- Requires parameter extraction to happen BEFORE validation (changes flow)
- May validate workflows that user rejects anyway
- Couples planner tightly to runtime validation logic
- Harder to test planner in isolation

---

### Alternative 2: Runtime Validates Everything (Lazy Validation)

**Description**: The planner only does structure validation. Template validation happens exclusively at runtime.

**Implementation**:
```python
# In planner's ValidatorNode
def exec(self, prep_res):
    workflow = prep_res["workflow"]

    # Only structure validation
    validate_ir(workflow)
    return {"is_valid": True}

# At runtime (current implementation)
compile_ir_to_flow(workflow, registry, initial_params, validate=True)
```

**Pros**:
- Clean separation of concerns - planner generates, runtime validates execution readiness
- Simpler planner implementation
- Allows saving workflows with unresolved templates (future use case)
- Runtime has most accurate parameter information

**Cons**:
- Late error detection - user approves workflow that might fail
- No opportunity for planner to fix template errors
- Worse user experience - errors after approval
- May generate many invalid workflows

---

### Alternative 3: Dual Validation (Recommended) ✓

**Description**: Both planner and runtime validate, but with different purposes:
- **Planner**: Validates structure + templates against *expected* parameters
- **Runtime**: Re-validates with *actual* parameters as safety check

**Implementation**:
```python
# In planner's ValidatorNode
def exec(self, prep_res):
    workflow = prep_res["workflow"]
    registry = prep_res["registry"]
    expected_params = prep_res["parameter_values"]  # What planner extracted

    # 1. Always validate structure
    validate_ir(workflow)

    # 2. Validate templates with expected params
    # This catches issues like:
    # - Template variables that no node writes
    # - Invalid paths like $issue_data.missing.field
    errors = TemplateValidator.validate_workflow_templates(
        workflow, expected_params, registry
    )

    if errors:
        return {
            "is_valid": False,
            "errors": errors,
            "error_type": "template_validation"
        }

    return {"is_valid": True}

# At runtime (keep existing validation)
compile_ir_to_flow(workflow, registry, actual_params, validate=True)
```

**Pros**:
- Early detection with retry opportunity
- Safety net at runtime for parameter mismatches
- Clear separation: planner validates "can this work?", runtime validates "will this work now?"
- Supports future use cases (saved workflows with different params)
- Best user experience - errors caught early but verified at execution

**Cons**:
- Validation happens twice (minimal performance impact)
- Slightly more complex than single validation point
- Need to keep validation logic consistent

---

### Alternative 4: Conditional Validation Based on Path

**Description**: Different validation strategies for found vs generated workflows:
- **Path A (Found)**: Skip template validation in planner (already validated when saved)
- **Path B (Generated)**: Full validation in planner

**Implementation**:
```python
# In planner - different validator behavior based on path
def should_validate_templates(shared):
    # Only validate templates for newly generated workflows
    return "generated_workflow" in shared

class ValidatorNode(Node):
    def exec(self, prep_res):
        workflow = prep_res["workflow"]

        # Always validate structure
        validate_ir(workflow)

        # Conditionally validate templates
        if self.should_validate_templates(prep_res["shared"]):
            errors = TemplateValidator.validate_workflow_templates(...)
            # ... handle errors

        return {"is_valid": True}
```

**Pros**:
- Efficient - avoids re-validating known-good workflows
- Respects workflow lifecycle (validated when saved)
- Faster for workflow reuse path

**Cons**:
- Complex conditional logic
- Saved workflows might have become invalid (node changes)
- Different behavior for different paths increases testing complexity
- Breaks single responsibility principle

## Recommendation: Alternative 3 (Dual Validation)

**Rationale**:

1. **Early Detection**: Template errors are caught during planning when they can be fixed through retry logic. This is crucial for the planner's self-correcting behavior.

2. **Safety**: Runtime validation provides a safety net for edge cases (parameter type changes, runtime-only params).

3. **Clean Architecture**: Each component has clear validation responsibility:
   - Planner: "Is this workflow well-formed and likely to work?"
   - Runtime: "Can I execute this workflow right now with these exact parameters?"

4. **Future Proof**: Supports future scenarios like:
   - Saving workflows that need runtime-only parameters
   - Workflows with optional parameters
   - Different parameter sets for same workflow

5. **User Experience**: Users get immediate feedback during planning but with runtime verification for safety.

## Implementation Notes

1. **Error Messages**: Planner should provide user-friendly template error messages that help the LLM fix issues:
   ```python
   "Template variable $api_config has no valid source - no node writes 'api_config'"
   "Invalid template path: $issue_data.missing.field - 'missing' not in issue_data structure"
   ```

2. **Performance**: Template validation is fast (regex parsing + dictionary lookups), so dual validation has minimal impact.

3. **Testing**: Need tests for both validation points:
   - Planner tests: Mock registry and verify retry on template errors
   - Runtime tests: Verify validation still works as safety net

4. **Consistency**: Both validation points use the same `TemplateValidator` class, ensuring consistent behavior.

## Migration Path

1. Update planner's ValidatorNode to include template validation
2. Keep runtime validation unchanged (already implemented)
3. Add tests for planner's template validation behavior
4. Document the dual validation approach in architecture docs
