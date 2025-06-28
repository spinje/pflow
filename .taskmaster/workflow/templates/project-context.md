# Project Context for Task [X]: [Task Title]

**File Location**: `.taskmaster/tasks/task_[X]/project-context.md`

*Created by sub-agents on: [Date]*
*Purpose: Provide focused project understanding for ALL subtasks of this task*

## Task Domain Overview

[Brief description of what part of the system this task involves, why it exists, and its role in the larger project]

## Relevant Components

### [Component Name]
- **Purpose**: [What this component does]
- **Responsibilities**: [Key functions]
- **Key Files**: [Main files to be aware of]
- **How it works**: [Brief explanation relevant to task]

### [Another Component if applicable]
- **Purpose**: [...]
- **Responsibilities**: [...]
- **Interactions**: [How it relates to other components]

## Core Concepts

### [Concept 1]
- **Definition**: [What this means in the project context]
- **Why it matters for this task**: [Relevance]
- **Key terminology**: [Terms that will appear in code/docs]

### [Concept 2]
- **Definition**: [...]
- **Relationships**: [How it connects to other concepts]

## Architectural Context

### Where This Fits
[Explain how the task's target component(s) fit into the overall architecture]

### Data Flow
[If relevant, describe how data moves through the components involved]

### Dependencies
- **Upstream**: [What this depends on]
- **Downstream**: [What depends on this]

## Constraints and Conventions

### Technical Constraints
- [Constraint 1]: [What it means for this task]
- [Constraint 2]: [Impact on implementation]

### Project Conventions
- **Naming**: [Relevant naming conventions]
- **Patterns**: [Established patterns in this area]
- **Style**: [Code style specific to this component]

### Design Decisions
- [Decision]: [Why it was made and how it affects this task]

## Key Documentation References

### Essential pflow Documentation
- `docs/[filename].md` - [Why this is important for the task]
- `docs/architecture/[filename].md` - [Key architectural patterns]

### PocketFlow Documentation (if applicable)
- `pocketflow/docs/[topic]/[file].md` - [Relevant concepts]
- `pocketflow/cookbook/[example]/` - [Pattern to follow]

*These references should be included in the decomposition plan to guide subtask generation.*

## Key Questions This Context Answers

1. **What am I building/modifying?** [Answer]
2. **How does it fit in the system?** [Answer]
3. **What rules must I follow?** [Answer]
4. **What existing code should I study?** [Answer]

## What This Document Does NOT Cover

- Implementation details (see cookbook examples later)
- Specific code solutions (that's for implementation phase)
- Unrelated components (to preserve focus)
- Historical details not relevant to current task

---

*This briefing was synthesized from project documentation to provide exactly the context needed for this task, without overwhelming detail.*

**Note**: This document is created ONCE at the task level and shared by ALL subtasks. It is created by the first subtask and read by all subsequent subtasks.
