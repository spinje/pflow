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
- Access to task-master CLI (external task management tool, not part of pflow)
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

**You should:**
- Deploy and synthesize subagent results
- If task mentions PocketFlow: Read `pocketflow/__init__.py`
- Create a synthesized briefing that includes:
  - Overview of relevant components and how they work
  - Key concepts and terminology for this task domain

**Sub-agents should:**
- Analyze the main task description and requirements
- Read relevant sections from `docs/` for the task domain
- **Document which pflow docs are essential** for this task (to be referenced in decomposition plan)
- If task mentions PocketFlow or use of PocketFlow is implied or potentially applicable:
  - First read `pocketflow/__init__.py` to understand core framework
  - Search relevant `pocketflow/docs` for conceptual understanding
  - **Document which PocketFlow docs are relevant** (for decomposition plan)
  - **CRITICAL**: *Use sub-agents* to explore `pocketflow/cookbook/` for production-ready patterns:
    - Sub-agents read `pocketflow/cookbook/CLAUDE.md` for complete example inventory
    - Sub-agents should identify 1-3 relevant examples based on task requirements
    - Extract implementation patterns that apply to this task
    - **Note which examples to reference** in the decomposition plan
- Create a synthesized briefing that includes:
  - Overview of relevant components and how they work
  - Key concepts and terminology for this task domain
  - Architectural context (where this fits in the system)
  - Relevant constraints, conventions, or decisions
  - Cookbook patterns discovered that will guide implementation
  - Domain understanding needed for intelligent decomposition
  - **List of key documentation references** to include in decomposition plan

**Output**: Create `.taskmaster/tasks/task_<taskId>/project-context.md` based on template (`project-context.md` in `.taskmaster/workflow/templates/`)

**IMPORTANT**: The project context should identify key documentation that will be referenced in the decomposition plan. This includes:
- Essential pflow docs from `docs/` folder
- Relevant PocketFlow documentation (if applicable)
- Cookbook examples that demonstrate needed patterns

Remember: The PocketFlow cookbook examples contain production-ready code that can be adapted directly!

#### 0.3 Review Similar Tasks (Recommended)

**If helpful, look at similar completed tasks:**
- Review completed tasks in `.taskmaster/tasks/` directory
- Read their task-review.md files for technical insights (located in `.taskmaster/tasks/task_<id>/task-review.md` for each task)
- Note any useful patterns or approaches
- If many tasks seem relevant, deploy sub-agents to gather useful information from the `task-review.md` files.

**This is about:**
- Understanding how similar technical challenges were solved
- Learning from architectural decisions
- Avoiding known pitfalls

**Keep it lightweight** - don't create formal synthesis documents. Just gather inspiration if needed.

#### 0.4 Understanding Prior Research (If Available)

**Check for existing research files in the task's research folder:**
```bash
# Look for research files created by previous AI agents
ls .taskmaster/tasks/task_<taskId>/research/
```

> Always read all the available research files. This is mandatory.

**Common research files (organized in `research/` subfolder):**
- `research/pocketflow-patterns.md` - Insights from PocketFlow cookbook examples
- `research/external-patterns.md` - Patterns from similar projects (e.g., Simon Willison's llm)

**Critical Thinking Required:**
> **⚠️ IMPORTANT**: These research files contain recommendations from other AI agents. You must:
> - **Verify all assumptions** - Don't blindly trust prior research
> - **Cross-reference with actual code if possible** - Research may be outdated or incorrect
> - **Question relevance** - Patterns may not apply to current task or need adaptation
> - **Validate against current docs** - Make sure the patterns are applicable to pflow. Project may have evolved since research was done or research may not have considered everything.

**If research files exist:**
1. Read each file critically
2. Extract potentially useful patterns
3. Verify recommendations against:
   - Current task requirements
   - Latest project documentation
   - Actual code in pflow (does this fit?)
   - Actual code in PocketFlow cookbook (only do this if the code seems to be wrong, use sub-agents)
   - Current architectural decisions
4. Document verified insights in project context

**Remember**: Prior research is a starting point, not gospel. Your understanding of the current task and codebase takes precedence over any recommendations in these files. With that said, the reasearch can be an invaluable source of inspiration and ideas to make the best possible task decomposition and implementation.

### Exit Criteria for Phase 0
- [ ] Current task fully understood with no ambiguities
- [ ] Project context briefing created for the task
- [ ] Relevant cookbook patterns identified and documented in project context
- [ ] Domain understanding acquired for intelligent decomposition
- [ ] (Optional) Similar tasks reviewed for inspiration
- [ ] (If available) Prior research files critically reviewed and verified

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
4. Map relevant research insights to specific subtasks

**Consider:**
- Complexity score (1-10) from task understanding
- Similar tasks' subtask counts
- Available patterns from synthesis
- How all available documentation and research files can be used to guide the decomposition

#### 2.2 Create Detailed Expansion Prompt

**Create comprehensive decomposition plan:**
```
.taskmaster/tasks/task_<taskId>/decomposition-plan.md
```

**CRITICAL**: This file will be passed directly to task-master expand as the prompt. It must be self-contained and comprehensive.

**Template Available**: *ALWAYS* Use `.taskmaster/workflow/templates/decomposition-plan.md` as a starting point.

**Follow the template structure** (see `.taskmaster/workflow/templates/decomposition-plan.md`):
- Task overview and decomposition pattern
- Detailed subtask descriptions
- Relevant pflow Documentation section (ALWAYS include)
- Relevant PocketFlow Documentation section (if applicable)
- Relevant PocketFlow Examples section (if not in research)
- Research references (if applicable)
- Key considerations and special instructions

**The file must contain:**
- Complete context about the task
- Detailed descriptions for each subtask
- All dependencies and relationships
- Explicit references to pflow documentation (from `docs/` folder)
- PocketFlow documentation references (if framework can potentially be used)
- Cookbook example references (if applicable and not in research)
- References to research files where applicable
- Test requirements per subtask
- Any special implementation notes

**Remember**: This is the ONLY input the expansion will receive. Documentation references are CRITICAL because they:
- Guide the LLM to generate subtasks that follow project conventions
- Ensure architectural consistency
- Point to specific patterns and examples to follow
- Prevent reinventing existing solutions

> Note: Only include references that is directly relevant to the subtasks. For example, dont automatically reference all the research files for every subtask. Be smart about it and think deeply about what is relevant and what is not.

#### 2.3 Review Decomposition Plan

**Before proceeding, verify your decomposition plan file:**
- Is it comprehensive and self-contained?
- Does it include all context needed for subtask generation?
- Are all subtasks clearly described with dependencies?
- Are research references included where applicable?
- Would an LLM reading ONLY this file understand what to create?

#### 2.4 Generate Subtasks

Run the expansion using your decomposition plan file:
```bash
task-master expand --id=<taskId> --num=<recommendedSubtasks> --prompt="$(< .taskmaster/tasks/task_<taskId>/decomposition-plan.md)"
```

**Note**: The `--prompt` flag passes the entire contents of your decomposition plan file to task-master. This ensures all your planning context is used for intelligent subtask generation. By using the shell command substitution, you can avoid writing out all the content of the decomposition plan file in the prompt.

### Exit Criteria for Phase 2
- [ ] Decomposition strategy documented
- [ ] Comprehensive decomposition plan file created
- [ ] Subtasks generated via task-master expand with file-based prompt
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
   - `.taskmaster/tasks/task_<taskId>/decomposition-plan.md`

2. All subtasks should:
   - Follow `refine-subtask.md` workflow
   - Read the existing project-context.md
   - Build on shared understanding

#### 3.3 Notify the user of the next step

Let the user know that the next step is to run the following slash command:
```
/refine-subtask <taskId>.1
```

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
   - The decomposition plan file is where all intelligence lives
   - Use file-based prompt to pass comprehensive context

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
