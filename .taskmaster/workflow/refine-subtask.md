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

#### 0.1 Load Task-Level Project Context

**Read the project context created during task decomposition:**
1. Read `.taskmaster/tasks/task_<parentTaskId>/project-context.md`
2. This was created by sub-agents during the main task workflow
3. Contains synthesized project understanding for all subtasks

**The project context provides:**
- Overview of relevant components and how they work
- Key concepts and terminology for this task domain
- Architectural context (where this fits in the system)
- Relevant constraints, conventions, or decisions
- Domain understanding shared by all subtasks

**If project context is missing:**
- This indicates the main task workflow was not followed
- Alert the user that task decomposition should be done first
- The task needs to go through `refine-task.md` workflow

#### 0.2 Note Research References in Subtask Description

**Check if your subtask description contains research references:**
- Subtasks may include paths like `.taskmaster/tasks/task_5/research/pocketflow-patterns.md`
- These are **suggestions from task decomposition**, not mandates
- Research provides options to consider, not instructions to follow

**Critical understanding:**
> Research references are ONE INPUT among many. During refinement, you will:
> - Consider research suggestions alongside other approaches
> - Evaluate multiple implementation options
> - Make reasoned decisions based on current context
> - Escalate critical choices to the user when needed

#### 0.3 Load Historical Knowledge

**For NEW TASKS (first subtask of a task):**

Go to next step 0.4.

**For CONTINUING SUBTASKS (not the first subtask):**

Read sibling subtask reviews from your current task:
1. Navigate to `.taskmaster/tasks/task_<parentTaskId>/`
2. For each completed `subtask_*` folder (with lower number than current):
   - Read `implementation/subtask-review.md`

Example for subtask 3.3:
- `.taskmaster/tasks/task_3/subtask_3.1/implementation/subtask-review.md`
- `.taskmaster/tasks/task_3/subtask_3.2/implementation/subtask-review.md`

**Understand:**
- How the parent task is evolving
- Dependencies between subtasks
- Assumptions already made
- Context from completed siblings

> Note: These files contains Knowledge Synthesis for the subtask and should be read with absolute care. Think hard about these insights and how they can be applied to the current subtask.

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

**Important**: Always use sub-agents to gather information from previous tasks or from files in `.taskmaster/knowledge/`. Never try to access these files yourself since it will pollute your context window with irrelevant information. Using sub-agents means that they can fetch curated information from the knowledge base or the other tasks folders.

### Exit Criteria for Phase 0
- [ ] Project context read and understood
- [ ] Relevant components and concepts clear
- [ ] All previous task reviews read and understood (for new tasks)
- [ ] All relevant sibling reviews processed (for continuing subtasks)
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

#### 1.2 Code Validation & Cookbook Pattern Analysis

**Deploy sub-agents** to analyze the codebase, documentation and identify relevant cookbook patterns.

**Part A: Gather relevant information:**
- Agents search the documentation in `docs/` for relevant files and information

**Part B: Explore and verify against actual codebase:**
- Agents search for relevant source files in `src/pflow/`
- And search documentation in `docs/` for accuracy and cross-references

**Part C: Cookbook Pattern Discovery (only for tasks where PocketFlow can potentially be used):**
- **Sub-agents read** `pocketflow/cookbook/CLAUDE.md` to understand available examples and `pocketflow/__init__.py` to understand core framework
- **Sub-agents search** `pocketflow/docs/` for conceptual understanding that can be applied to the current task
- **Sub-agents search** `pocketflow/cookbook/` for relevant examples
- **Sub-agents identify** 1-3 cookbook examples most relevant to this subtask
- **Sub-agents analyze** the identified examples for:
  - Implementation patterns you can adapt
  - Error handling approaches
  - Code organization conventions
  - Testing strategies
  - And more...

**Document findings:**
- Note discrepancies between docs and code
- Identify missing information
- List assumptions that need validation
- Document which cookbook patterns that can be applied

> **Using sub-agents is mandatory** for gathering this information effectively. This ensures that you are not polluting your own context window with irrelevant information when searching for relevant information.

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

#### 1.4 Implementation Approach Decisions

**Evaluate multiple approaches:**
1. Research-suggested patterns (if referenced in subtask)
2. Patterns from knowledge synthesis
3. Approaches discovered through code validation
4. Standard pflow conventions

**For each approach, consider:**
- Pros and cons
- Fit with current architecture
- Complexity vs. benefit
- Long-term maintainability

**Critical Decision Framework:**
- If decision has **profound architectural impact** → Create decision document
- If decision affects **multiple subtasks** → Escalate to user
- If decision contradicts **established patterns** → Document reasoning
- If **multiple valid approaches** exist → Present options to user

**Document in evaluation.md:**
```markdown
## Implementation Approaches Considered

### Approach 1: Research-suggested pattern from external-patterns.md
- Description: JWT token approach from research
- Pros: Industry standard, well-tested
- Cons: May be overkill for MVP
- Decision: [Selected/Rejected] because...

### Approach 2: Simple session-based auth
- Description: Basic cookie sessions
- Pros: Simple, fits MVP scope
- Cons: Less scalable
- Decision: [Selected/Rejected] because...

### Approach 3: PocketFlow pattern from cookbook
- Description: Using decorator pattern from example X
- Pros: Consistent with framework
- Cons: May need adaptation
- Decision: [Selected/Rejected] because...
```

#### 1.5 Create Refined Specification

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
- **Cookbook patterns to apply**: [List specific examples, e.g., "pocketflow-batch-node for file processing"]

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

#### 1.6 Mark Refinement Complete

Create a marker file to indicate refinement is complete:
```bash
touch .taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/ready-for-implementation
```

Note: We do NOT update task-master during refinement. Task-master is only updated when the entire subtask is complete.

### Exit Criteria for Phase 1
- [ ] All code validated against task requirements
- [ ] Relevant cookbook patterns analyzed and documented (2-3 examples minimum for PocketFlow tasks)
- [ ] All ambiguities identified and resolved
- [ ] User decisions obtained and documented
- [ ] Refined specification created with cookbook patterns listed
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

2. Proceed to read and follow `implement-subtask.md` if instructed to do so or by notifying the user of the next step

   Let the user know that the next step is to run the following slash command:
   ```
   /implement-subtask <subtaskId>
   ```

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
   - ALL subtasks read project context (created during main task workflow)
   - NEW TASKS (first subtask)? Read other tasks' reviews
   - CONTINUING SUBTASKS? Read sibling reviews from current task
   - Project context should always exist - if not, task decomposition was skipped

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
