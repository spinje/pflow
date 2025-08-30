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

## Relevant pflow Documentation
[ALWAYS include - Reference key project documentation that guides this task]

### Core Documentation
- `architecture/[filename].md` - [Which sections/concepts apply]
  - Relevance: [How this guides the implementation]
  - Key concepts: [Specific patterns or conventions to follow]
  - Applies to subtasks: [Which subtasks should reference this]

### Architecture/Feature Documentation
- `architecture/architecture/[filename].md` - [Relevant architectural patterns]
  - Critical for: [Which aspects of the task]
  - Must follow: [Specific conventions or constraints]

### Example:
```
- `architecture/features/cli-runtime.md` - Sections on shared store usage
  - Relevance: All subtasks must follow shared store conventions
  - Key concepts: Store initialization, key naming patterns
  - Applies to subtasks: 2, 3, and 4
```

## Relevant PocketFlow Documentation
[Include if this task uses PocketFlow framework]

### Framework Core
- `pocketflow/__init__.py` - [Which classes/patterns are relevant]
- `pocketflow/docs/[topic]/[file].md` - [Specific concepts]
  - Pattern: [What pattern to follow]
  - Usage: [How to apply in this context]

### Example:
```
- `pocketflow/docs/core_abstraction/node.md` - Node lifecycle (prep/exec/post)
  - Pattern: All nodes must follow the three-phase lifecycle
  - Usage: Subtask 2 will implement custom nodes following this pattern
```

## Relevant PocketFlow Examples
[Include if not already mentioned in research files]

### Cookbook Patterns
- `pocketflow/cookbook/[example-name]/` - [What pattern this demonstrates]
  - Adaptation needed: [How to modify for this task]
  - Applies to: [Which subtasks can use this pattern]

### Example:
```
- `pocketflow/cookbook/rag-wiki-simple/` - Simple RAG pattern with caching
  - Adaptation: Replace wiki search with our custom data source
  - Applies to: Subtask 3 for implementing search functionality
```

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
- Each subtask should reference relevant documentation sections
- Include specific file paths and concepts in subtask descriptions

---

**Note**: This file will be passed directly to `task-master expand` as the prompt. Ensure it contains ALL context needed for intelligent subtask generation, including explicit references to project documentation, framework docs, and examples.
