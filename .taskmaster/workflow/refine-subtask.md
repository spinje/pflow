# Subtask Refinement Workflow

Your goal is to transform the subtask with id `<subtaskId>` from a potentially ambiguous description into a crystal-clear implementation specification. This is achieved through systematic knowledge loading and thorough refinement.

**IMPORTANT**: This document covers Phase 0 (Knowledge Loading) and Phase 1 (Refinement) only. Implementation is covered in `implement-subtask.md`.

## Core Principles

1. **Past implementations contain wisdom** - Every previous task has lessons to teach
2. **Ambiguity is a STOP signal** - Never proceed on assumptions
3. **Truth lives in code** - Always validate against actual implementation
4. **Knowledge compounds** - Each refinement makes future ones better

## Prerequisites

**Required:**
- Task ID provided as argument to this workflow (`<subtaskId>`)
- Access to task-master CLI
- Understanding of pflow project structure and goals

**Variables:**
- `<subtaskId>` - The current subtask being refined (e.g., "1.2")
- `<parentTaskId>` - The parent task ID (e.g., "1")

## Phase 0: Knowledge Loading

### Goal
Load ALL relevant knowledge from previous implementations to avoid repeating mistakes and leverage discovered patterns.

### Activities

#### 0.1 Load or Create Task-Level Project Context

**For NEW TASKS (first subtask of a task):**
1. Check if `.taskmaster/tasks/task_<parentTaskId>/project-context.md` exists
2. If it exists, read it (another subtask may have created it)
3. If not, launch sub-agents to create it:

   **Sub-agent Mission:**
   "Analyze the ENTIRE task (not just this subtask) and create a briefing document that provides the project context needed for ALL subtasks of this task. Read all relevant documentation but synthesize it into a focused brief."

   **Sub-agents should:**
   - Analyze the parent task description and all its subtasks
   - Read relevant sections from `docs/` (carefully search through the docs for relevant information)
   - If task mentions PocketFlow or implicitly uses PocketFlow: Read `pocketflow/__init__.py` and relevant `pocketflow/docs/`
   - Create a synthesized briefing that includes:
     - Overview of relevant components and how they work
     - Key concepts and terminology for this task domain
     - Architectural context (where this fits in the system)
     - Relevant constraints, conventions, or decisions
     - Just enough big picture to ground ALL subtasks

   **Sub-agents should NOT:**
   - Include implementation examples (save cookbook for later)
   - Add details about unrelated components
   - Copy large sections verbatim
   - Focus on HOW to implement (that comes later)

   **Output**: Create `.taskmaster/tasks/task_<parentTaskId>/project-context.md` based on the template

**For CONTINUING SUBTASKS (not the first in the task):**
1. Read existing `.taskmaster/tasks/task_<parentTaskId>/project-context.md`
2. If it doesn't exist (rare case where earlier subtask failed), follow the NEW TASKS process above

This briefing document should be 2-4 pages that give the mental model needed for the entire task.

#### 0.2 Load Project-Wide Knowledge

**For a NEW TASK** (first subtask of a task, e.g., subtask 3.1):
Read all task-level reviews from completed tasks:
1. Navigate to `.taskmaster/tasks/`
2. For each `task_*` folder (except your current task):
   - Read `task-review.md` if it exists

Example paths to check for task 3.1:
- `.taskmaster/tasks/task_1/task-review.md`
- `.taskmaster/tasks/task_2/task-review.md`

**Focus on:**
- Patterns that worked well
- Approaches that failed
- Architectural decisions made
- Conventions established

#### 0.3 Load Task-Specific Knowledge

**For a SUBTASK** (not the first in its task, e.g., subtask 3.2 or 3.3):
Read sibling subtask reviews from your current task:
1. Navigate to `.taskmaster/tasks/task_<parentTaskId>/`
2. For each completed `subtask_*` folder (with lower number than current):
   - Read `implementation/review.md`

Example for subtask 3.3:
- `.taskmaster/tasks/task_3/subtask_3.1/implementation/review.md`
- `.taskmaster/tasks/task_3/subtask_3.2/implementation/review.md`

**Understand:**
- How the parent task is evolving
- Dependencies between subtasks
- Assumptions already made
- Context from completed siblings

#### 0.4 Synthesize Patterns
Create knowledge synthesis file at:
`.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/refinement/knowledge-synthesis.md`

```markdown
# Knowledge Synthesis for <subtaskId>

## Relevant Patterns from Previous Tasks
- [Pattern]: [Where it was used] - [Why it's relevant]

## Known Pitfalls to Avoid
- [Pitfall]: [Where it failed] - [How to avoid]

## Established Conventions
- [Convention]: [Where decided] - [Must follow]

## Codebase Evolution Context
- [What changed]: [When] - [Impact on this task]
```

### Exit Criteria for Phase 0
- [ ] Project context briefing created by sub-agents
- [ ] Relevant components and concepts understood
- [ ] All previous task reviews read and understood
- [ ] All relevant subtask reviews (if applicable) processed
- [ ] Knowledge synthesis document created
- [ ] Mental model of codebase evolution established

## Phase 1: Refinement

### Goal
Transform the task description into an unambiguous specification, validated against code reality and informed by accumulated knowledge.

### Activities

#### 1.1 Deep Understanding (Knowledge-Informed)

Read the task details:
```bash
task-master show --id=<subtaskId>
```

Note: This is the primary use of task-master in the refinement phase.

**Key Questions:**
- What does this task REALLY need to accomplish?
- How does previous work affect this task?
- What assumptions are being made?
- Where might ambiguities hide?

#### 1.2 Code Validation
**Explore and verify against actual codebase:**
- Read relevant source files in `src/pflow/`
- Check documentation in `docs/` for accuracy
- If using PocketFlow, study `pocketflow/__init__.py`
- Review examples in `pocketflow/cookbook/` if applicable

**Document findings:**
- Note discrepancies between docs and code
- Identify missing information
- List assumptions that need validation

#### 1.3 Ambiguity Detection and Resolution

Create evaluation file at:
`.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/refinement/evaluation.md`

```markdown
# Evaluation for <subtaskId>

## Ambiguities Found

### 1. [Ambiguity Title] - Severity: [1-5]

**Description**: [What is unclear]

**Why this matters**: [Impact if wrong]

**Options**:
- [ ] **Option A**: [Description]
  - Pros: [...]
  - Cons: [...]
  - Similar to: [Previous task that used this]

- [ ] **Option B**: [Description]
  - Pros: [...]
  - Cons: [...]
  - Risk: [What could go wrong]

**Recommendation**: Option A because [reasoning based on knowledge synthesis]

## Conflicts with Existing Code/Decisions

### 1. [Conflict Title]
- **Current state**: [What exists]
- **Task assumes**: [What the task description implies]
- **Resolution needed**: [User decision required]
```

**Get user decisions on ALL ambiguities before proceeding.**

#### 1.4 Create Refined Specification

Create refined specification at:
`.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/refinement/refined-spec.md`

```markdown
# Refined Specification for <subtaskId>

## Clear Objective
[One sentence describing what success looks like]

## Context from Knowledge Base
- Building on: [Previous patterns being reused]
- Avoiding: [Known pitfalls being sidestepped]
- Following: [Conventions being maintained]

## Technical Specification
### Inputs
- [Specific inputs with types/formats]

### Outputs
- [Specific outputs with types/formats]

### Implementation Constraints
- Must use: [Specific patterns/libraries]
- Must avoid: [Known problematic approaches]
- Must maintain: [Existing conventions]

## Success Criteria
- [ ] [Specific, measurable criterion]
- [ ] [Another criterion]
- [ ] All tests pass
- [ ] No regressions in [specific areas]

## Test Strategy
- Unit tests: [What to test]
- Integration tests: [What to verify]
- Manual verification: [What to check]

## Dependencies
- Requires: [What must exist/be true]
- Impacts: [What this will affect]

## Decisions Made
- [Decision]: [Rationale] (User confirmed on [date])
```

#### 1.5 Mark Refinement Complete

Create a marker file to indicate refinement is complete:
```bash
touch .taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/ready-for-implementation
```

Note: We do NOT update task-master during refinement. Task-master is only updated when the entire subtask is complete.

### Exit Criteria for Phase 1
- [ ] All code validated against task requirements
- [ ] All ambiguities identified and resolved
- [ ] User decisions obtained and documented
- [ ] Refined specification created
- [ ] Success criteria clearly defined
- [ ] Test strategy identified
- [ ] Knowledge from previous tasks incorporated
- [ ] Marker file created for ready-for-implementation

## Handoff to Implementation

Once ALL exit criteria are met:

1. Verify all required files exist:
   - `.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/refinement/knowledge-synthesis.md`
   - `.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/refinement/evaluation.md`
   - `.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/refinement/refined-spec.md`
   - `.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/ready-for-implementation`

2. Proceed to `implement-subtask.md` for Phase 2

## Common Refinement Patterns

### Pattern: Dependency Validation
Always verify that dependencies mentioned in tasks actually exist:
- If task says "use the existing auth system"
- Check files in `src/` for auth-related code
- Read the actual implementation to understand it
- Don't assume based on naming alone

### Pattern: Specification Gaps
If the task says "implement X like Y", always:
1. Find where Y is implemented
2. Understand Y's patterns
3. Explicitly document how X should mirror Y

### Pattern: Test-First Refinement
Before refining implementation details, understand:
- What tests currently exist
- What tests will prove success
- What could break if done wrong

## Anti-Patterns to Avoid

### ❌ Assumption Refinement
"The task probably means X" → Always ask for clarification

### ❌ Documentation Trust
"The docs say X exists" → Always verify in code

### ❌ Isolation Refinement
"This task stands alone" → Always check impact on other tasks

### ❌ Surface Reading
"I understand the task" → Always dig deeper for hidden complexity

## Important Notes for AI Agents

1. **Knowledge Loading Strategy**:
   - First subtask of a task? Read other tasks' `task-review.md` files
   - Later subtask? Read previous subtasks' `review.md` from current task
   - This prevents redundant reading while maintaining context

2. **task-master limitations**:
   - Can only show task details and set status
   - Cannot store or retrieve reviews/patterns/progress
   - Use ONLY for initial task reading and final status update

3. **File-based workflow**:
   - All progress tracking happens in markdown files
   - Create all files in their exact subtask folder
   - Task reviews are created only after ALL subtasks complete

4. **No shell commands needed**:
   - You have Read and Write tools - use them directly
   - Don't search for files - follow the explicit paths provided
   - Create directories as needed when writing files

---

Remember: **Your role is not to follow instructions—it is to ensure they are valid, complete, and aligned with project truth.**
