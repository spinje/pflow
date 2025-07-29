# Task 30: Refactor Validation Functions from compiler.py

## Overview

Extract `_validate_ir_structure()` and `_validate_inputs()` from `src/pflow/runtime/compiler.py` into a new `src/pflow/runtime/workflow_validator.py` module. Keep `_validate_outputs()` in compiler due to its compilation-specific nature. Maintain explicit mutation visibility in compiler.

## Requirements

- R1: Create `workflow_validator.py` containing extracted validation logic
- R2: Reduce compiler.py by ~110 lines
- R3: Preserve exact validation behavior
- R4: Keep input parameter mutations explicit in compiler.py
- R5: Maintain all existing error messages and logging

## Design

### Module Structure
```
src/pflow/runtime/
├── compiler.py          # Orchestration, keeps _validate_outputs()
├── workflow_validator.py # New module with:
│   ├── validate_ir_structure(ir_dict) -> None
│   └── prepare_inputs(workflow_ir, provided_params) -> tuple[list[str], dict[str, Any]]
```

### Function Signatures
```python
# workflow_validator.py
def validate_ir_structure(ir_dict: dict[str, Any]) -> None:
    """Raises CompilationError if structure invalid"""

def prepare_inputs(workflow_ir: dict[str, Any], provided_params: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Returns (errors, defaults_to_apply). Does not mutate provided_params."""
```

## Implementation

1. Create `workflow_validator.py` with imports:
   - `logging`
   - `CompilationError` from compiler
   - `ValidationError` from `pflow.core.ir_schema`

2. Extract `_validate_ir_structure()`:
   - Copy function verbatim
   - Make public (remove underscore)
   - Keep all error messages identical

3. Extract and refactor `_validate_inputs()`:
   - Rename to `prepare_inputs()`
   - Change to return `(errors, defaults)` instead of mutating
   - Collect errors instead of raising immediately
   - Build defaults dict for missing optional inputs

4. Update compiler.py:
   - Import from workflow_validator
   - Replace `_validate_ir_structure(ir_dict)` with `validate_ir_structure(ir_dict)`
   - Replace input validation with:
     ```python
     errors, defaults = prepare_inputs(ir_dict, initial_params)
     if errors:
         raise CompilationError(...)
     initial_params.update(defaults)  # Explicit mutation
     ```

5. Update imports in any test files

## Rules

- RULE-1: `validate_ir_structure()` must raise same `CompilationError` instances
- RULE-2: `prepare_inputs()` must not mutate its input parameters
- RULE-3: All logger.debug() and logger.info() calls must be preserved
- RULE-4: Error message text must remain identical
- RULE-5: `_validate_outputs()` must remain in compiler.py unchanged
- RULE-6: Import order in compiler.py must follow existing pattern

## Test Criteria

- TEST-1: All existing tests pass without modification
- TEST-2: `prepare_inputs()` with required input missing returns errors list
- TEST-3: `prepare_inputs()` with optional input missing returns defaults dict entry
- TEST-4: `validate_ir_structure()` raises on missing 'nodes' key
- TEST-5: `validate_ir_structure()` raises on non-list 'edges' value
- TEST-6: Compiler behavior identical for all test workflows
- TEST-7: Line count reduction in compiler.py is 100-120 lines

## Edge Cases

- Invalid Python identifiers in input names
- None vs missing optional inputs
- Empty defaults ({}) vs no default key
- Workflows with no inputs declared
- Circular imports between compiler and validator

## Performance Notes

- None

## Backwards Compatibility

- Public API unchanged
- Internal function signatures changed but not used externally
- Test suite requires no modifications

## Example Usage

```python
# In compiler.py
from .workflow_validator import validate_ir_structure, prepare_inputs

def compile_ir_to_flow(...):
    # Step 2: Validate structure
    try:
        validate_ir_structure(ir_dict)
    except CompilationError:
        logger.exception("IR validation failed", extra={"phase": "validation"})
        raise

    # Step 3: Validate inputs and apply defaults
    try:
        errors, defaults = prepare_inputs(ir_dict, initial_params)
        if errors:
            raise ValidationError(errors[0])  # Use first error
        initial_params.update(defaults)  # Explicit mutation
    except ValidationError:
        logger.exception("Input validation failed", extra={"phase": "input_validation"})
        raise
```

## Follow-up Work

- Consider renaming `_validate_outputs()` to `_analyze_outputs()` in future PR
- Evaluate extracting node instantiation logic (Task 31)

## Open Questions

- None

## Dependencies

- None

## Epistemic Appendix

### Assumptions & Unknowns
- Assumed no external code imports these private functions directly
- Assumed test files import from compiler.py, not the functions directly

### Conflicts & Resolutions
- None identified

### Decision Log / Tradeoffs
- Chose tuple return over dataclass for `prepare_inputs()` to minimize changes
- Kept CompilationError import in validator despite circular dependency risk - mitigated by import-time evaluation
- Named function `prepare_inputs()` not `validate_inputs()` to reflect dual purpose

### Epistemic Audit
1. **Which assumptions did I make that weren't explicit?** That the logging extra fields are not parsed by external systems
2. **What would break if they're wrong?** Log parsing tools might fail if extra fields change
3. **Did I optimize elegance over robustness?** No, kept verbose but explicit approach
4. **Did every Rule map to at least one Test (and vice versa)?** Yes, each rule has corresponding test
5. **What ripple effects or invariants might this touch?** None beyond module boundaries
6. **What remains uncertain, and how confident am I?** 95% confident - only uncertainty is undiscovered external imports
