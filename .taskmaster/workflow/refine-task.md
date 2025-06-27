# Task Refinement & Decomposition Workflow

Your goal is to refine task `<taskId>` and decompose it into well-structured subtasks. This workflow applies epistemic learning principles to task decomposition, ensuring each task benefits from all previous decomposition experiences.

**IMPORTANT**: This document covers main task refinement and subtask generation. For subtask implementation, use `refine-subtask.md` and `implement-subtask.md`.

## Core Principles

1. **Past decompositions contain wisdom** - Learn from what worked and what didn't
2. **Patterns compound** - Each task decomposition makes the next one better
3. **Ambiguity is a STOP signal** - Never guess at task breakdown
4. **Size matters** - Well-sized subtasks are key to success
5. **Dependencies are critical** - Order subtasks for smooth flow

## Prerequisites

**Required:**
- Task ID provided as argument (`<taskId>`)
- Access to task-master CLI
- Understanding of pflow project structure

**Variables:**
- `<taskId>` - The main task being refined (e.g., "5")

## Phase 0: Task Understanding

### Goal
Deeply understand the current task and its project context before attempting decomposition.

### Activities

#### 0.1 Read and Analyze Current Task

**Get the task details:**
```bash
task-master show --id=<taskId>
```

**Understand thoroughly:**
- What is the core objective?
- What are the implementation requirements?
- What is the test strategy?
- Are there any ambiguities or unclear aspects?

**If anything is unclear:**
- Document the ambiguities
- Seek clarification before proceeding
- Never decompose based on assumptions

#### 0.2 Create Project Context

**Launch sub-agents with this mission:**
"Analyze the main task <taskId> and create a comprehensive project context briefing that will be used by ALL subtasks. Read all relevant documentation but synthesize it into a focused brief that provides the domain understanding needed for both decomposition and implementation."

**Sub-agents should:**
- Analyze the main task description and requirements
- Read relevant sections from `docs/` for the task domain
- If task mentions PocketFlow: Read `pocketflow/__init__.py` and relevant docs
- Create a synthesized briefing that includes:
  - Overview of relevant components and how they work
  - Key concepts and terminology for this task domain
  - Architectural context (where this fits in the system)
  - Relevant constraints, conventions, or decisions
  - Domain understanding needed for intelligent decomposition

**Output**: Create `.taskmaster/tasks/task_<taskId>/project-context.md` based on template

#### 0.3 Review Similar Tasks (Optional)

**If helpful, look at similar completed tasks:**
- Check `.taskmaster/reports/task-complexity-report.json` for tasks with similar domain/complexity
- Read their task-review.md files for technical insights
- Note any useful patterns or approaches

**This is NOT about analyzing decomposition quality**, but rather:
- Understanding how similar technical challenges were solved
- Learning from architectural decisions
- Avoiding known pitfalls

**Keep it lightweight** - don't create formal synthesis documents. Just gather inspiration if needed.

### Exit Criteria for Phase 0
- [ ] Current task fully understood with no ambiguities
- [ ] Project context briefing created for the task
- [ ] Domain understanding acquired for intelligent decomposition
- [ ] (Optional) Similar tasks reviewed for inspiration

## Phase 1: Task Refinement

### Goal
Refine the task description if needed based on understanding gained in Phase 0.

### Activities

#### 1.1 Verify Task Readiness

**Check task status:**
- Ensure no existing subtasks (if they exist, abort and notify user)
- Verify implementation details are sufficient
- Confirm test strategy is complete

**Based on Phase 0 understanding:**
- Are the implementation details complete?
- Is the test strategy comprehensive?
- Are success criteria clear?

#### 1.2 Refine Task Description (If Needed)

**Only if updates are required:**
```bash
task-master update-task --id=<taskId> --prompt="[detailed update instructions]"
```

**Common refinements:**
- Add missing implementation details discovered during context creation
- Clarify test requirements
- Add specific success criteria
- Incorporate constraints from project context

#### 1.3 Solution Exploration

**Evaluate different approaches:**
1. List 2-3 viable ways to accomplish the task
2. Consider trade-offs of each approach
3. Use project context to inform decisions

**If multiple valid approaches with significant implications:**
- Create decision document in `scratchpads/task_<taskId>/critical-user-decisions/`
- STOP and wait for user decision
- Document chosen approach rationale

**After decisions are made:**
- Update task description if needed (using task-master update-task)
- Verify updates with task-master show

### Exit Criteria for Phase 1
- [ ] Task fully understood with no ambiguities
- [ ] All technical decisions made or escalated
- [ ] Task description refined if needed
- [ ] Clear mental model of what needs to be built

## Phase 2: Subtask Generation

### Goal
Create well-structured subtasks using patterns from decomposition synthesis.

### Activities

#### 2.1 Determine Decomposition Strategy

**Based on decomposition synthesis and task analysis:**
1. Identify which pattern(s) fit this task
2. Determine optimal number of subtasks
3. Plan subtask ordering for dependencies

**Consider:**
- Complexity score (1-10) from task understanding
- Similar tasks' subtask counts
- Available patterns from synthesis

#### 2.2 Create Detailed Expansion Prompt

**Create scratchpad for planning:**
```
scratchpads/task-<taskId>/task-<taskId>-decomposition-plan.md
```

**Document:**
1. Chosen decomposition pattern and why
2. Planned subtasks with descriptions
3. Dependencies between subtasks
4. Size estimate for each (hours)
5. Detailed expansion prompt

**Expansion prompt should:**
- Reference specific patterns to follow
- Include granular subtask descriptions
- Specify dependencies explicitly
- Mention test requirements per subtask
- Contain ALL the necessary information for an llm to generate the subtasks automatically (all context is needed)

#### 2.3 Update task-complexity-report.json

**Add new entry with extreme care:**
```json
{
    "taskId": <taskId>,
    "taskTitle": "<from task-master show>",
    "complexityScore": <1-10 based on analysis>,
    "recommendedSubtasks": <number based on patterns>,
    "expansionPrompt": "<extremely detailed prompt based on plan>",
    "reasoning": "<why this decomposition, what patterns applied>"
}
```

**Critical**: This is error-prone for AI agents. Double-check JSON syntax!

**Note**: Running `task-master expand` will NOT work if the `task-complexity-report.json` is not updated for the current task.

#### 2.4 Generate Subtasks

Run the expansion:
```bash
task-master expand --id=<taskId> --num=<recommendedSubtasks>
```

### Exit Criteria for Phase 2
- [ ] Decomposition strategy documented
- [ ] task-complexity-report.json updated correctly
- [ ] Subtasks generated via task-master expand
- [ ] All subtasks created successfully

## Phase 3: Subtask Refinement

### Goal
Ensure all subtasks are well-defined and ready for implementation.

### Activities

#### 3.1 Verify All Subtasks

**Check each generated subtask:**
```bash
# Run these in parallel if multiple subtasks
task-master show --id=<taskId>.1
task-master show --id=<taskId>.2
# ... etc
```

**For each subtask verify:**
- Clear objective
- Reasonable scope (2-6 hours)
- Dependencies identified
- Implementation details present

#### 3.2 Refine Subtasks as Needed

**For any subtask needing refinement:**
```bash
task-master update-subtask --id=<taskId>.<subtaskId> --prompt="[specific improvements needed]"
```

**Common refinements:**
- Add missing dependencies
- Clarify ambiguous requirements
- Adjust scope if too large/small
- Add specific test requirements

### Exit Criteria for Phase 3
- [ ] All subtasks verified and refined
- [ ] Each subtask properly scoped
- [ ] Dependencies clearly documented
- [ ] Ready for subtask implementation

## Handoff to Subtask Implementation

Once ALL exit criteria are met:

1. Verify all required files exist:
   - `.taskmaster/tasks/task_<taskId>/project-context.md`
   - `.taskmaster/reports/task-complexity-report.json` (updated)

2. All subtasks should:
   - Follow `refine-subtask.md` workflow
   - Read the existing project-context.md
   - Build on shared understanding

## Common Decomposition Patterns

### Pattern: Foundation-Integration-Polish
Best for: New features requiring infrastructure
```
1. Foundation: Core data models, basic infrastructure
2. Integration: Connect components, basic functionality
3. Polish: Error handling, optimization, documentation
```

### Pattern: Research-Prototype-Production
Best for: Exploratory or uncertain tasks
```
1. Research: Investigate approaches, create POC
2. Prototype: Build working version with shortcuts
3. Production: Harden, test, document
```

### Pattern: Data-Logic-Interface
Best for: Full-stack features
```
1. Data: Models, storage, migrations
2. Logic: Business rules, processing
3. Interface: API/CLI exposure
```

## Anti-Patterns to Avoid

### ❌ The Monolith
Creating 1-2 huge subtasks that are really multiple tasks

### ❌ The Scatter
Creating 10+ tiny subtasks that should be grouped

### ❌ The Chain
Creating long dependency chains where subtask N depends on N-1

### ❌ The Mixup
Mixing different concerns (e.g., infrastructure + features) in one subtask

## Important Notes for AI Agents

1. **Task Understanding First**:
   - Always understand the CURRENT task before looking at patterns
   - Create project context to understand the domain
   - Reviewing similar tasks is optional - for inspiration only
   - Focus on THIS task, not meta-analysis

2. **task-master expand**:
   - This is the ONLY safe way to create subtasks
   - Never try to manipulate tasks.json directly
   - The expansion prompt is where intelligence lives

3. **Pattern References**:
   - Patterns are suggestions, not rules
   - Adapt based on current task needs
   - Don't over-analyze past decompositions

4. **Size Guidance**:
   - 2-6 hours per subtask is ideal
   - Complexity 1-3: Usually 2-3 subtasks
   - Complexity 4-6: Usually 3-5 subtasks
   - Complexity 7-10: Usually 4-7 subtasks

---

Remember: **Your role is not to blindly decompose tasks—it is to deeply understand what needs to be built and break it down logically based on that understanding.**
