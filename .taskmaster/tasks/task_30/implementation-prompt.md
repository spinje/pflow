# Task 30: Refactor Validation Functions from compiler.py - Agent Instructions

## The Problem You're Solving

The compiler.py module has grown to ~745 lines with mixed concerns, making it hard to test validation logic in isolation. Validation functions are intertwined with compilation logic, and one function (_validate_inputs) secretly mutates data, violating expectations. This refactoring improves code organization and makes the true behavior explicit.

## Your Mission

Extract two validation functions from compiler.py into a new workflow_validator.py module, reducing compiler size by ~110 lines while maintaining exact behavior. Keep mutations visible in the compiler and use honest naming.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first**: This mindset is critical for implementing any task correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Task Overview
**File**: `.taskmaster/tasks/task_30/task-30.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_30/starting-context/`

**Files to read (in this order):**
1. `task-30-spec.md` - The specification (FOLLOW THIS PRECISELY) {{TO BE VERIFIED - check actual filename}}
2. `task-30-handover.md` - Critical insights about why these aren't just validation functions {{TO BE VERIFIED - check actual filename}}

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`*-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

## What You're Building

You're creating a new `workflow_validator.py` module that extracts validation logic from the compiler while being honest about what these functions actually do:

1. **Pure validation**: `validate_ir_structure()` - checks if IR has required structure
2. **Validation + preparation**: `prepare_inputs()` - validates inputs AND returns defaults to apply

Example of the new approach:
```python
# In workflow_validator.py
def prepare_inputs(workflow_ir: dict[str, Any], provided_params: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Returns (errors, defaults_to_apply). Does not mutate provided_params."""
    errors = []
    defaults = {}
    # ... validation and default collection ...
    return errors, defaults

# In compiler.py
errors, defaults = prepare_inputs(ir_dict, initial_params)
if errors:
    raise CompilationError(...)
initial_params.update(defaults)  # Explicit mutation in compiler
```

## Key Outcomes You Must Achieve

### Code Organization
- Create `src/pflow/runtime/workflow_validator.py` with extracted functions
- Reduce compiler.py by 100-120 lines
- Maintain clear separation of concerns

### Behavioral Preservation
- All existing tests must pass without modification
- Preserve exact error messages and logging
- Keep all logger.debug() calls and extra fields identical
- Ensure no breaking changes to existing functionality

### Honest Design
- Rename `_validate_inputs()` to `prepare_inputs()` to reflect dual purpose
- Make mutations explicit in the compiler, not hidden in validators
- Return results from validation functions rather than mutating inputs

## Implementation Strategy

### Phase 1: Create New Module (30 minutes)
1. Create `src/pflow/runtime/workflow_validator.py`
2. Add necessary imports (logging, CompilationError, ValidationError)
3. Set up module structure with proper docstrings

### Phase 2: Extract validate_ir_structure (30 minutes)
1. Copy `_validate_ir_structure()` from compiler.py (lines 99-146)
2. Make it public (remove underscore prefix)
3. Keep all error messages and logging identical
4. Update compiler.py to import and use the new function

### Phase 3: Extract and Refactor prepare_inputs (1 hour)
1. Copy `_validate_inputs()` from compiler.py (lines 470-541)
2. Rename to `prepare_inputs()` to reflect its dual purpose
3. Refactor to return `(errors, defaults)` instead of mutating
4. Collect errors in a list instead of raising immediately
5. Build defaults dict for missing optional inputs
6. Update compiler.py to use new function and apply mutations explicitly

### Phase 4: Testing and Verification (30 minutes)
1. Run full test suite to ensure no regressions
2. Verify line count reduction in compiler.py
3. Check for any import issues or circular dependencies
4. Ensure all logging output remains identical

### Phase 5: Final Cleanup (15 minutes)
1. Remove old functions from compiler.py
2. Update any import statements in test files
3. Add module-level docstring to workflow_validator.py
4. Verify make test and make check pass

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use subagents to work on debugging, testing and writing tests.

## Critical Technical Details

### The Mutation Issue
`_validate_inputs()` currently mutates `initial_params` by adding default values:
```python
initial_params[input_name] = default_value  # Line 527
```
The compiler DEPENDS on this mutation. When extracting, you must:
1. Return the defaults to apply
2. Have the compiler explicitly apply them
3. Make the mutation visible in the compiler

### Why NOT Extracting _validate_outputs
The `_validate_outputs()` function (lines 543-615) stays in compiler because:
- It's really static analysis, not validation (only produces warnings)
- Uses `TemplateValidator._extract_node_outputs()` - cross-module coupling
- Contains workflow-specific logic (lines 581-587)
- Deeply coupled to compilation context
- Never fails compilation - only warns

### Circular Import Risk
`CompilationError` is defined in compiler.py. When importing into workflow_validator.py:
- This creates a potential circular import
- Should work due to import-time evaluation
- If issues arise, consider moving exception classes to a separate module

### Exact Behavior Preservation
Critical to preserve:
- All error message text must remain identical
- Logger extra fields might be parsed by external systems
- The order of validation checks
- Which errors cause immediate failure vs collected errors

## Critical Warnings from Experience

### Hidden Mutations Are Dangerous
The current `_validate_inputs()` violates the principle of least surprise by mutating its inputs. This refactoring makes that behavior explicit and visible at the call site, preventing future confusion.

### Cross-Module Private Method Usage
`_validate_outputs()` calls `TemplateValidator._extract_node_outputs()` - a private method from another module. This is why we're NOT extracting it. Attempting to extract would require fixing this coupling first.

### Test File Imports
Check if any test files directly import these private functions. The assumption is they don't, but verify this to avoid breaking tests.

## Key Decisions Already Made

1. **Extract only 2 of 3 functions** - `_validate_outputs()` stays in compiler
2. **Honest naming** - Use `prepare_inputs()` not `validate_inputs()`
3. **Explicit mutations** - Mutations happen in compiler, not validator
4. **Pure functions where possible** - Return results, don't mutate
5. **Preserve exact behavior** - No functional changes, only reorganization
6. **Keep logging identical** - All debug messages and extra fields unchanged

**📋 Note on Specifications**: If a specification file exists for this task, it is the authoritative source. Follow it precisely - do not deviate from specified behavior, test criteria, or implementation requirements unless you discover a critical issue (in which case, document the deviation clearly or STOP and ask the user for clarification).

## Success Criteria

Your implementation is complete when:

- ✅ All existing tests pass without modification
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ compiler.py reduced by 100-120 lines
- ✅ New workflow_validator.py properly organized
- ✅ Mutations are explicit in compiler, not hidden
- ✅ All error messages and logging remain identical
- ✅ No circular import issues
- ✅ Functions have clear, honest names

## Common Pitfalls to Avoid

- **DON'T extract _validate_outputs()** - It belongs in the compiler
- **DON'T change error messages** - Keep them exactly the same
- **DON'T modify logger extra fields** - External tools may parse them
- **DON'T hide mutations** - Make them explicit in the compiler
- **DON'T skip testing** - Run full test suite after each change
- **DON'T change function behavior** - Only reorganize code
- **DON'T forget to update imports** - Check test files too

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent subagents from conflicting.

### Why Planning Matters

1. **Prevents duplicate work and conflicts**: Multiple subagents won't edit the same files
2. **Identifies dependencies**: Discover what needs to be built in what order
3. **Optimizes parallelization**: Know exactly what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Current Validation Function Analysis**
   - Task: "Analyze _validate_ir_structure, _validate_inputs, and _validate_outputs in src/pflow/runtime/compiler.py. Extract exact line numbers, dependencies, and mutation points"
   - Task: "Find all calls to these validation functions in compiler.py and note the context"

2. **Import and Dependency Analysis**
   - Task: "Check if any test files import _validate_ir_structure or _validate_inputs directly"
   - Task: "Analyze CompilationError usage and potential circular import issues"

3. **Template Validator Integration**
   - Task: "Examine how _validate_outputs uses TemplateValidator._extract_node_outputs"
   - Task: "Document the workflow-specific logic in _validate_outputs"

4. **Testing Impact Analysis**
   - Task: "Find all tests that exercise validation functions"
   - Task: "Identify test assertions that depend on specific error messages"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_30/implementation/implementation-plan.md`

Your plan should include:

1. **Comprehensive task breakdown** - Every file to create/modify
2. **Dependency mapping** - What must be done before what
3. **Subagent task assignments** - Who does what, ensuring no conflicts
4. **Risk identification** - What could go wrong and mitigation strategies
5. **Testing strategy** - How you'll verify each component works

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_30/implementation/progress-log.md`

```markdown
# Task 30 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### Implementation Steps

1. **Create implementation plan** - Comprehensive plan following template
2. **Gather context** - Deploy subagents to understand current code
3. **Create new module** - Set up workflow_validator.py
4. **Extract pure validation** - Move validate_ir_structure
5. **Extract and refactor input validation** - Create prepare_inputs
6. **Update compiler imports** - Modify compiler to use new functions
7. **Run tests** - Verify no regressions
8. **Clean up** - Remove old functions from compiler
9. **Final verification** - Ensure all criteria met

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to [specific action]...

Result: [What happened]
- ✅ What worked: [Specific detail]
- ❌ What failed: [Specific detail]
- 💡 Insight: [What I learned]

Code that worked:
```python
# Actual code snippet
```
```

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Update the plan with new approach
4. Continue with new understanding

Append deviation to progress log:
```markdown
## [Time] - DEVIATION FROM PLAN
- Original plan: [what was planned]
- Why it failed: [specific reason]
- New approach: [what you're trying instead]
- Lesson: [what this teaches us]
```

## Test Creation Guidelines

**Core Principle**: "Test what matters"

**Focus on quality over quantity**:
- Test public interfaces and critical paths
- Test edge cases where bugs typically hide
- Create integration tests when components interact
- Document only interesting test discoveries in your progress log

**What to test**:
- **Critical paths**: Validation logic that must work correctly
- **Public APIs**: The new validate_ir_structure and prepare_inputs functions
- **Error handling**: How functions behave with invalid input
- **Integration points**: How compiler uses the new functions

**What NOT to test**:
- Simple getters/setters
- Configuration loading
- Framework code
- Internal helper functions (unless complex)

**Progress Log - Only document testing insights**:
```markdown
## 10:30 - Testing revealed edge case
While testing prepare_inputs(), discovered that None defaults
behave differently than missing defaults. This affects how we
handle optional parameters.
```

**Remember**: Quality tests that catch real bugs > many trivial tests

## What NOT to Do

- **DON'T** extract `_validate_outputs()` - It's static analysis, not validation
- **DON'T** change any error messages - Keep exact text
- **DON'T** modify logger extra fields - May break log parsing
- **DON'T** hide mutations in validators - Make them explicit
- **DON'T** change function behavior - Only reorganize
- **DON'T** skip running tests - Verify after each change

## Getting Started

1. Read the epistemic manifesto to understand the approach
2. Read the task overview and specifications
3. Create your implementation plan
4. Deploy subagents to gather context
5. Start with creating the new module
6. Extract functions one at a time, testing after each

## Final Notes

- This is a pure refactoring - no functional changes
- The goal is better code organization and honest naming
- Mutations must be visible where they happen
- All existing tests should pass without modification
- The spec has exact line numbers and function details

## Remember

You're improving code quality by separating concerns and making behavior explicit. The current code works but mixes validation with data transformation. Your refactoring will make the codebase more maintainable and the true behavior more obvious. When faced with ambiguity about what the code does, study it carefully and preserve exact behavior.

Good luck! This refactoring will make the compiler cleaner and validation logic easier to test and understand.
