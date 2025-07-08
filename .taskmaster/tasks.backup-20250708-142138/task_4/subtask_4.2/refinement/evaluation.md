# Evaluation for Subtask 4.2

## Ambiguities Found

### 1. BaseNode vs Node Inheritance Check - Severity: 2

**Description**: Should we check for inheritance from BaseNode or Node? The registry finds all BaseNode subclasses (including Node subclasses), but which should we validate against?

**Why this matters**: Node provides additional functionality (retry, fallback) that BaseNode doesn't have. Being too restrictive could reject valid nodes.

**Options**:
- [x] **Option A**: Check for BaseNode inheritance (more inclusive)
  - Pros: Accepts all valid nodes, matches registry behavior
  - Cons: None - this is what the registry already does
  - Similar to: Task 5 scanner checks for BaseNode

- [ ] **Option B**: Check for Node inheritance only
  - Pros: Ensures retry capabilities
  - Cons: Would reject valid BaseNode-only nodes
  - Risk: Breaking compatibility with existing nodes

**Recommendation**: Option A - Check for BaseNode inheritance to match registry behavior and allow maximum flexibility.

### 2. Return Type: Class vs Instance - Severity: 1

**Description**: The briefing clearly states to return the class (not instance), but should we validate that the class can be instantiated?

**Why this matters**: A class might be valid but have a broken __init__ method that would fail later.

**Options**:
- [x] **Option A**: Return the class without instantiation test
  - Pros: Follows specification exactly, faster, simpler
  - Cons: Defers instantiation errors to later
  - Similar to: Standard Python import behavior

- [ ] **Option B**: Test instantiation before returning class
  - Pros: Earlier error detection
  - Cons: Could trigger side effects, slower, not requested
  - Risk: Instantiation might require parameters we don't have

**Recommendation**: Option A - Return the class as specified. Instantiation testing belongs in integration tests.

## Conflicts with Existing Code/Decisions

### 1. Import Context Management
- **Current state**: Task 5 scanner uses context manager for sys.path modification
- **Task assumes**: Simple importlib usage without path manipulation
- **Resolution needed**: No - the compiler receives full module paths from registry, no sys.path changes needed

## Implementation Approaches Considered

### Approach 1: Direct importlib pattern from PocketFlow cookbook
- Description: Use importlib.import_module() and getattr() as shown in visualization example
- Pros: Proven pattern, simple, matches PocketFlow conventions
- Cons: None identified
- Decision: **Selected** - This is the standard Python approach

### Approach 2: Try-except with specific error handling
- Description: Catch ImportError and AttributeError separately with rich context
- Pros: Specific error messages, follows Task 5 patterns
- Cons: More verbose than catch-all
- Decision: **Selected** - Better debugging experience

### Approach 3: Pre-validation of registry data
- Description: Check if module/class_name exist in registry before attempting import
- Pros: Could provide earlier error detection
- Cons: Redundant - import will fail anyway if missing
- Decision: **Rejected** - Let import errors happen naturally

## Error Handling Strategy

Based on the briefing and patterns discovered:

1. **Missing from Registry**: Check node_type in registry first
   - Phase: "node_resolution"
   - Include list of available nodes in suggestion

2. **Import Failures**: Catch ImportError specifically
   - Phase: "node_import"
   - Include module path in error details

3. **Class Not Found**: Catch AttributeError when using getattr
   - Phase: "node_import"
   - Include class_name in error details

4. **Invalid Inheritance**: Check with issubclass(cls, BaseNode)
   - Phase: "node_validation"
   - Include actual base classes in error details

## Test Strategy Decisions

Based on patterns from Task 5 and the briefing:

1. **Mock Strategy**: Mock importlib.import_module to avoid real imports
2. **Test Coverage**: All 4 error types plus success case
3. **Integration Test**: Use actual test_node.py for real-world validation
4. **Error Message Quality**: Verify all CompilationError fields are populated correctly

## No User Decisions Required

All ambiguities have been resolved based on:
- Clear guidance in the briefing
- Established patterns from previous tasks
- PocketFlow cookbook examples
- Architectural decisions already made

The implementation path is clear and well-defined.
