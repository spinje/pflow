# Task [taskId] Decomposition Plan

**File Location**: `.taskmaster/tasks/task_[taskId]/decomposition-plan.md`

*Created on: [Date]*
*Purpose: Comprehensive prompt for task-master expand command*

## Task Overview
[Provide a clear, concise description of what Task [taskId] aims to accomplish]

## Decomposition Pattern
**Pattern**: [e.g., Foundation-Integration-Polish / Research-Prototype-Production / Data-Logic-Interface]

**Reasoning**: [Explain why this pattern is the best fit for this task]

## Complexity Analysis
- **Complexity Score**: [1-10]
- **Reasoning**: [Why this complexity score]
- **Total Subtasks**: [Number]

## Planned Subtasks

### Subtask 1: [Title]
**Description**: [Detailed description of what this subtask will accomplish]
**Dependencies**: [None | List of task IDs this depends on]
**Estimated Hours**: [2-6]
**Implementation Details**:
- [Specific technical approach]
- [Key files/components to modify or create]
- [Important considerations]

**Test Requirements**:
- [What tests should be written]
- [Key scenarios to cover]

### Subtask 2: [Title]
**Description**: [Detailed description]
**Dependencies**: [[taskId].1]
**Estimated Hours**: [2-6]
**Implementation Details**:
- [Technical approach]
- [Files/components]
- [Considerations]

**Test Requirements**:
- [Test specifications]

[Continue for all planned subtasks...]

## Research References
[Only include if research files exist for this task]

### For Subtask [X]:
- Apply pattern from `.taskmaster/tasks/task_[taskId]/research/[filename].md`
- Specifically: [What pattern/approach to use]
- Adaptation needed: [How to modify for this context]

### For Subtask [Y]:
- Reference: `.taskmaster/tasks/task_[taskId]/research/[filename].md`
- Key insight: [What to take from the research]

## Key Architectural Considerations
- [Any important architectural decisions or constraints]
- [Conventions that must be followed]
- [Integration points with existing code]

## Dependencies Between Subtasks
- [taskId].2 requires [taskId].1 because [reason]
- [taskId].3 and [taskId].4 can be done in parallel after [taskId].2

## Success Criteria
- [ ] [Overall success criterion 1]
- [ ] [Overall success criterion 2]
- [ ] All subtasks have clear implementation paths
- [ ] Test coverage for all new functionality

## Special Instructions for Expansion
[Any specific guidance for the LLM performing the expansion]
- Focus on [specific aspect]
- Ensure [particular requirement]
- Consider [important factor]

---

**Note**: This file will be passed directly to `task-master expand` as the prompt. Ensure it contains ALL context needed for intelligent subtask generation.
