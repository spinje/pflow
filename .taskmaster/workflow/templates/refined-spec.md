# Refined Specification for [Task/Subtask ID]

**File Location**: `.taskmaster/tasks/task_[X]/subtask_[X.Y]/refinement/refined-spec.md`

*Created: [Date]*
*Refined from evaluation.md with user decisions*

## Clear Objective

[One clear sentence describing what success looks like, e.g., "Users can authenticate via CLI using JWT tokens stored securely in the local filesystem"]

## Context from Knowledge Base

### Building On
- **[Pattern Name]** from Task [X.Y]: [How we're reusing it]
- **[Another Pattern]** from Task [A.B]: [How it applies]

### Avoiding
- **[Known Pitfall]** from Task [X.Y]: [Specific avoidance strategy]
- **[Another Pitfall]**: [How we're preventing it]

### Following Conventions
- **[Convention]**: [How we maintain consistency]
- **[Standard]**: [Specific implementation detail]

## Technical Specification

### Inputs

#### Input 1: [Name]
- **Type**: [Specific type/format]
- **Source**: [Where it comes from]
- **Validation**: [What to check]
- **Example**: `[concrete example]`

#### Input 2: [Name]
- **Type**: [...]
- **Source**: [...]
- **Validation**: [...]

### Outputs

#### Output 1: [Name]
- **Type**: [Specific type/format]
- **Destination**: [Where it goes]
- **Format**: [Specific structure]
- **Example**:
```[format]
[Concrete example of output]
```

### Processing Steps

1. **[Step Name]**
   - Input: [What it receives]
   - Process: [What it does]
   - Output: [What it produces]
   - Error handling: [How errors are handled]

2. **[Next Step]**
   - Input: [...]
   - Process: [...]
   - Output: [...]

### Implementation Constraints

#### Must Use
- **[Library/Pattern]**: [Why and how]
- **[Framework Feature]**: [Specific usage]

#### Must Avoid
- **[Anti-pattern]**: [Why it's problematic]
- **[Deprecated Approach]**: [What to use instead]

#### Must Maintain
- **[Backward Compatibility]**: [What can't break]
- **[Performance Requirement]**: [Specific metric]

## Success Criteria

- [ ] **Functional**: [Specific, measurable outcome]
- [ ] **Performance**: [Measurable metric, e.g., "Completes in <2s"]
- [ ] **Security**: [Specific security requirement met]
- [ ] **User Experience**: [Observable behavior]
- [ ] **Integration**: [Works with existing component X]
- [ ] **Tests**: All unit tests pass with >90% coverage
- [ ] **Documentation**: API docs updated with examples

## Test Requirements & Creation Strategy

**Test Coverage Target**: >80% for all new code

### Tests to Create

#### Unit Tests (REQUIRED)
**File**: `tests/test_[module].py`
- **[Function/Class Name]**:
  - `test_[name]_happy_path`: [What normal operation should do]
  - `test_[name]_with_invalid_input`: [How it handles bad data]
  - `test_[name]_edge_case`: [Boundary condition behavior]
  - `test_[name]_error_propagation`: [How errors are handled]

**File**: `tests/test_[another_module].py`
- **[Another Component]**:
  - [List specific test cases]

#### Integration Tests (When Components Interact)
**File**: `tests/test_integration_[feature].py`
- **Test Case**: [Component A + Component B interaction]
- **Test Case**: [Data flow through system]
- **Test Case**: [Error handling across components]
- **Test Case**: [Real-world usage scenario]

### Test Implementation Guidelines
- **Test what matters**: Focus on public interfaces and critical paths
- **Quality over quantity**: Better to have fewer, meaningful tests than many trivial ones
- **Integration tests are valuable**: Sometimes more important than unit tests
- **Test edge cases**: Where bugs hide (empty inputs, boundaries, errors)
- **Mock sparingly**: Only mock external dependencies, not internal components

### Manual Verification (Post-Implementation)
- [ ] [Specific user flow to test]
- [ ] [Another manual check]
- [ ] All automated tests pass locally

## Dependencies

### Required Before Starting
- [Dependency]: Must exist and be version [X.Y]
- [Service]: Must be running and accessible
- [Configuration]: Must be set to [value]

### Will Impact
- **Task [X.Y]**: [How this change affects it]
- **Component [Name]**: [What needs updating]
- **Documentation**: [What needs revision]

## Decisions Made

### Decision 1: [Title]
- **Options Considered**: [A, B, C]
- **Chosen**: Option [X]
- **Rationale**: [User's reasoning]
- **Date**: [When decided]
- **Decided By**: [User]

### Decision 2: [Title]
- **Context**: [Why decision was needed]
- **Chosen Approach**: [What was decided]
- **Trade-offs Accepted**: [What we're giving up]

## Implementation Notes

### File Structure
```
src/pflow/
├── module.py            # [What it does]
├── __init__.py         # Module exports
└── tests/
    ├── test_module.py  # Unit tests (>80% coverage)
    └── test_integration_[feature].py # Integration tests
```

### Key Interfaces/Classes
```python
class [ClassName]:
    """[Purpose of this class]"""

    def __init__(self, [params]):
        """Initialize with [description]."""
        self.property = [value]

    def method_name(self) -> ReturnType:
        """[What this method does]."""
        pass
```

### Error Handling
- **[Error Type]**: [How to handle]
- **[Another Error]**: [Recovery strategy]

## Risks and Mitigations

### Risk: [Identified Risk]
- **Probability**: [High/Medium/Low]
- **Impact**: [What could go wrong]
- **Mitigation**: [How we prevent/handle it]

## Ready for Implementation Checklist

- [ ] All user decisions are documented
- [ ] Success criteria are specific and measurable
- [ ] Test strategy covers all criteria
- [ ] Dependencies are verified to exist
- [ ] No unresolved ambiguities remain
- [ ] Approach validated against current code
- [ ] Knowledge from previous tasks incorporated

---

**Status**: READY FOR IMPLEMENTATION
*Proceed to implement-subtask.md workflow*
