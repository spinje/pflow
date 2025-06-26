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

#### 0.1 Load Project-Wide Knowledge
```bash
# Read ALL previous task implementation reviews
task-master show-reviews --all

# Focus on:
# - Patterns that worked well
# - Approaches that failed
# - Architectural decisions made
# - Conventions established
```

#### 0.2 Load Task-Specific Knowledge
```bash
# If working on a subtask, read ALL sibling subtask reviews
task-master show-reviews --task=<parentTaskId>

# Understand:
# - How the parent task is evolving
# - Dependencies between subtasks
# - Assumptions already made
# - Context from completed siblings
```

#### 0.3 Synthesize Patterns
Create `.taskmaster/tasks/task_<parentTaskId>/refinement/knowledge-synthesis.md`:

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
- [ ] All previous task reviews read and understood
- [ ] All relevant subtask reviews (if applicable) processed
- [ ] Knowledge synthesis document created
- [ ] Mental model of codebase evolution established

## Phase 1: Refinement

### Goal
Transform the task description into an unambiguous specification, validated against code reality and informed by accumulated knowledge.

### Activities

#### 1.1 Deep Understanding (Knowledge-Informed)
```bash
# Read the task with full context
task-master show --id=<subtaskId> --with-dependencies
```

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

Create `.taskmaster/tasks/task_<parentTaskId>/refinement/evaluation.md`:

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

Create `.taskmaster/tasks/task_<parentTaskId>/refinement/refined-spec.md`:

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

#### 1.5 Update Task-Master with Refinement

```bash
# Log the complete refinement into task-master
task-master update-subtask --id=<subtaskId> \
  --prompt="REFINEMENT COMPLETE: $(< .taskmaster/tasks/task_<parentTaskId>/refinement/refined-spec.md)"
```

### Exit Criteria for Phase 1
- [ ] All code validated against task requirements
- [ ] All ambiguities identified and resolved
- [ ] User decisions obtained and documented
- [ ] Refined specification created
- [ ] Success criteria clearly defined
- [ ] Test strategy identified
- [ ] Knowledge from previous tasks incorporated
- [ ] Task-master updated with refinement

## Handoff to Implementation

Once ALL exit criteria are met:

1. Verify refinement completeness:
   ```bash
   task-master show --id=<subtaskId>
   # Confirm refined spec is in details
   ```

2. Create handoff marker:
   ```bash
   touch .taskmaster/tasks/task_<parentTaskId>/refinement/ready-for-implementation
   ```

3. Proceed to `implement-subtask.md` for Phase 2

## Common Refinement Patterns

### Pattern: Dependency Validation
Always verify that dependencies mentioned in tasks actually exist:
```bash
# Example: Task says "use the existing auth system"
grep -r "auth" src/
# Verify it exists before assuming
```

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

---

Remember: **Your role is not to follow instructions—it is to ensure they are valid, complete, and aligned with project truth.**
