# Refined Specification for [Task/Subtask ID]

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

## Test Strategy

### Unit Tests
- **[Component]**: Test [specific behavior]
  - Happy path: [scenario]
  - Error case: [scenario]
  - Edge case: [scenario]

### Integration Tests
- **[Integration Point]**: Verify [specific interaction]
  - Test case: [description]
  - Expected: [outcome]

### Manual Verification
- [ ] [Specific user flow to test]
- [ ] [Another manual check]

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
path/to/
├── component.js     # [What it does]
├── component.test.js # [Test coverage]
└── types.ts         # [Type definitions]
```

### Key Interfaces
```typescript
interface [Name] {
  // [Purpose]
  property: Type;
  method(): ReturnType;
}
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
