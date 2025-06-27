# Subtask Implementation Workflow

Your goal is to implement the refined specification for subtask `<subtaskId>` while capturing ALL learnings for future tasks. This document covers Phase 2 (Implementation) only.

**PREREQUISITE**: You must have completed the refinement workflow (`refine-subtask.md`) and have a clear, unambiguous specification ready.

## Core Principles

1. **Learn while doing** - Capture discoveries AS THEY HAPPEN
2. **No knowledge lost** - Both successes and failures are valuable
3. **Patterns emerge** - Extract reusable solutions for future tasks
4. **Feedback enriches** - Your learnings make everyone better

## Prerequisites

**Required:**
- Completed refinement with `ready-for-implementation` marker
- Refined specification created
- Clear success criteria defined
- Test strategy identified

**Inputs from Refinement:**
- `.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/refinement/refined-spec.md`
- `.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/refinement/knowledge-synthesis.md`
- `.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/ready-for-implementation`

## Phase 2: Implementation

### Goal
Execute the refined specification systematically while capturing all learnings in real-time for future benefit.

### Activities

#### 2.1 Pre-Implementation Setup

Verify refinement is complete by checking for marker file:
- Check: `.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/ready-for-implementation` exists

Read the refined specification:
- Read: `.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/refinement/refined-spec.md`

Note: Implementation files go in the subtask folder, not a separate implementation folder.

#### 2.2 Create Implementation Plan

Create implementation plan at:
`.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/implementation/plan.md`

Based on refined specification:

```markdown
# Implementation Plan for <subtaskId>

## Objective
[From refined spec]

## Implementation Steps
1. [ ] [First concrete action]
   - File: [Which file to modify]
   - Change: [What to add/modify]
   - Test: [How to verify]

2. [ ] [Second concrete action]
   - File: [...]
   - Change: [...]
   - Test: [...]

## Pattern Applications

### Cookbook Patterns (only potentially applicable to tasks that can leverage pocketflow)
- **[Cookbook Example Name]**: [How you'll adapt it]
  - Specific code/approach: [What you're taking from it]
  - Modifications needed: [How you'll adjust for this task]
  - If Discarded: [Why it was discarded]
- **[Another Example]**: [Its application]

### Previous Task Patterns
- Using [Pattern X] from [Task Y] for [specific part]
- Avoiding [Anti-pattern Z] discovered in [Task W]

## Risk Mitigations
- [Risk]: [Mitigation strategy]
```

#### 2.3 Begin Implementation

Create learning log at:
`.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/implementation/progress-log.md`

Initial content:
```markdown
# Learning Log for <subtaskId>
Started: [Current date/time]

## Cookbook Patterns Being Applied
- [Pattern from example X]: [Status]
- [Pattern from example Y]: [Status]
```

Note: Do NOT update task-master status yet. All progress tracking happens in files.

#### 2.4 Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

File: `.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/implementation/progress-log.md`
```markdown
## [Timestamp] - [What I'm trying]
Attempting to [specific action]...

Result: [What happened]
- ✅ What worked: [Specific detail]
- ❌ What failed: [Specific detail]
- 💡 Insight: [What I learned]

Code that worked:
```python
# Actual code snippet
```
```

Remember: Do NOT update task-master during implementation. Keep all discoveries in your progress-log.md file and update every significant discovery.

#### 2.5 Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Update the plan with new approach
4. Continue with new understanding

Append deviation to progress log:
```markdown
## [Time] - DEVIATION FROM PLAN
- Original plan: [what was planned]
- Why it failed: [specific reason]
- New approach: [what you're trying instead]
- Lesson: [what this teaches us]
```

**When you discover something that affects other tasks:**

Create file at:
`.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/implementation/affects-tasks.md`
```markdown
# Task Impact Analysis

## Discovery
[What you found]

## Affects
- Task X: [How it impacts Task X]
- Task Y: [How it impacts Task Y]

## Action Required
- [ ] Update Task X specification
- [ ] Warn implementer of Task Y about [issue]
```

**When applying cookbook patterns:**

Document pattern application results in your progress log:
```markdown
## [Time] - Applying [Cookbook Example Name] Pattern
- Pattern source: pocketflow/cookbook/[example-name]/
- What I'm adapting: [Specific code/approach]
- Modifications made: [How I adjusted it]
- Result: SUCCESS/PARTIAL/FAILED
- Learning: [What this teaches about the pattern]

Working code:
```[language]
# Code adapted from cookbook
[actual implementation]
```
```

#### 2.6 Test Creation

**Core Principle**: "Test what matters"

**Focus on quality over quantity**:
- Test public interfaces and critical paths
- Test edge cases where bugs typically hide
- Create integration tests when components interact
- Document only interesting test discoveries in your progress log

**What to test**:
- **Critical paths**: Business logic that must work correctly
- **Public APIs**: Functions/classes exposed to other modules
- **Error handling**: How code behaves with invalid input
- **Integration points**: Where components connect

**What NOT to test**:
- Simple getters/setters
- Configuration loading
- Framework code
- Internal helper functions (unless complex)

**Progress Log - Only document testing insights**:
```markdown
## 14:50 - Testing revealed edge case
While testing authenticate_user(), discovered that empty strings
bypass validation. Added specific check and test case.
This pattern might affect other input validation across the system.
```

**Remember**: Quality tests that catch real bugs > many trivial tests

#### 2.7 Testing and Validation

Execute test strategy from refined spec and run your newly created tests:

- Run tests using appropriate commands (e.g., `make test`, `pytest`, etc.)
- Document test discoveries in your progress log
- Add section "## Test Insights" with findings

#### 2.8 Extract Patterns

As patterns emerge, document them immediately:

Create patterns file at:
`.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/implementation/new-patterns.md`
```markdown
# Patterns Discovered

## Pattern: [Descriptive Name]
**Context**: When you need to [situation]
**Solution**: [Specific approach with code example]
**Why it works**: [Explanation]
**When to use**: [Specific conditions]
**Example**:
```code
[Working code demonstrating pattern]
```
```

#### 2.9 Create Implementation Review

Once functional, create comprehensive review at:
`.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/implementation/subtask-review.md`

```markdown
# Implementation Review for <subtaskId>

## Summary
- Started: [Date/time]
- Completed: [Date/time]
- Deviations from plan: [Count and severity]

## Cookbook Pattern Evaluation
### Patterns Applied
1. **[Cookbook Example Name]** (pocketflow/cookbook/[example]/)
   - Applied for: [What aspect of the task]
   - Success level: [Full/Partial/Failed]
   - Key adaptations: [How you modified it]
   - Would use again: [Yes/No + reasoning]

2. **[Another Example]**
   - [Same structure]

### Cookbook Insights
- Most valuable pattern: [Which one and why]
- Unexpected discovery: [Something learned from examples]
- Gap identified: [What cookbook doesn't cover that would help]

## Test Creation Summary
### Tests Created
- **Total test files**: [Number] new, [Number] modified
- **Total test cases**: [Number] created
- **Coverage achieved**: [X]% of new code
- **Test execution time**: [X] seconds

### Test Breakdown by Feature
1. **[Feature/Function Name]**
   - Test file: `tests/test_[module].py`
   - Test cases: [Number]
   - Coverage: [X]%
   - Key scenarios tested: [List main test scenarios]

2. **[Another Feature]**
   - [Same structure]

### Testing Insights
- Most valuable test: [Which caught important issues]
- Testing challenges: [Any difficulties encountered]
- Future test improvements: [What could be added]

## What Worked Well
1. [Approach/pattern]: [Why it worked]
   - Reusable: Yes/No
   - Code example: [snippet]

## What Didn't Work
1. [Failed approach]: [Why it failed]
   - Root cause: [Deep reason]
   - How to avoid: [Specific guidance]

## Key Learnings
1. **Fundamental Truth**: [Something we now know for certain]
   - Evidence: [How we know]
   - Implications: [What this means for future tasks]

## Patterns Extracted
- [Pattern name]: See new-patterns.md
- Applicable to: [Which future tasks could use this]

## Impact on Other Tasks
- [Task X]: Needs [specific update]
- [Task Y]: Can now use [pattern/approach]

## Documentation Updates Needed
- [ ] Update [doc] to reflect [learning]
- [ ] Add pattern to knowledge base
- [ ] Update architectural decision record

## Advice for Future Implementers
If you're implementing something similar:
1. Start with [specific approach]
2. Watch out for [specific pitfall]
3. Use [pattern] for [situation]
```

#### 2.10 Final Learning Integration

If you discovered truly reusable patterns, pitfalls, or made architectural decisions:

1. **For Patterns**:
   - Read: `.taskmaster/knowledge/patterns.md` (entire file)
   - Check:
      - Does this pattern already exist?
      - Will this pattern be useful for future tasks and help make the project more coherent?
   - If unique: Append your pattern to the end of the file
   - Use the format specified in `.taskmaster/knowledge/CLAUDE.md`

2. **For Pitfalls**:
   - Read: `.taskmaster/knowledge/pitfalls.md` (entire file)
   - Check:
      - Is this failure already documented?
      - Is this general knowledge that will help future tasks avoid the same mistake?
   - If unique: Append to the end of the file

3. **For Architectural Decisions**:
   - Read: `.taskmaster/knowledge/decisions.md` (entire file)
   - Check:
      - Does this decision area already exist?
      - Is this an important decision with big consequences and impact on the project?
   - If new: Append to the end of the file

Note: Only add knowledge that will genuinely help future tasks. Quality over quantity.

#### 2.11 Create Task Review (If Last Subtask)

If this is the final subtask of the task:
1. Read all subtask reviews from this task:
   - `.taskmaster/tasks/task_<parentTaskId>/subtask_*/implementation/subtask-review.md`
2. Create task-level summary at:
   - `.taskmaster/tasks/task_<parentTaskId>/task-review.md`
3. Include:
   - Major patterns discovered across all subtasks
   - Key architectural decisions made
   - Important warnings for future tasks
   - Overall task success metrics

#### 2.12 Update Task-Master (FINAL STEP ONLY)

Only after implementation is complete and reviewed:

```bash
task-master set-status --id=<subtaskId> --status=done
```

This is the ONLY time you update task-master during the entire workflow.

#### 2.13 Git Commit

Create meaningful commit with context:

```bash
git add .
git commit -m "feat: Implement <subtaskId> - [brief description]

Key learnings:
- [Major discovery 1]
- [Major discovery 2]

See .taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/implementation/subtask-review.md for details"
```

Do NOT include "Generated with [Claude Code](https://claude.ai/code)" in the commit message.

#### 2.14 Notify the user of the next step

Let the user know that the next step is to run the following slash command:
```
/refine-subtask <nextSubtaskId> (If not last subtask)
# OR
/refine-task <nextTaskId> (If Last Subtask)
```

You can get the next task by running `task-master next`

Example last line to the user: I just finished implementing subtask 1.1, the next step is to run the following slash command: `/refine-subtask 1.2`

## Learning Capture Best Practices

### DO: Capture Immediately
```markdown
## 14:32 - Trying direct approach
[code attempt]
Result: Failed with error X

## 14:35 - Understanding the error
Error caused by [reason]. Need to [solution].

## 14:40 - New approach works!
[working code]
Key insight: [what made it work]
```

### DON'T: Capture After the Fact
```markdown
## End of day summary
Tried various things, eventually got it working.
```

### DO: Specific Code Examples
```python
# This specific pattern solved the async issue:
async def process_with_timeout(data):
    return await asyncio.wait_for(
        process(data),
        timeout=30
    )
```

### DON'T: Vague Descriptions
"Used async/await to fix the timeout problem"

## Feedback Triggers

**Return to Refinement if:**
- [ ] Specification is ambiguous after all
- [ ] Core assumption proves false
- [ ] Dependencies don't exist as expected
- [ ] Success criteria cannot be met as specified

**How to trigger feedback:**

Create file at:
`.taskmaster/tasks/task_<parentTaskId>/subtask_<subtaskId>/refinement-needed.md`

Content:
```markdown
# Refinement Needed

Reason: [specific issue discovered]
Details: [what assumption was wrong]
Needed: [what clarification is required]
```

Then return to `refine-subtask.md` workflow.

## Success Metrics

Your implementation is successful when:
- [ ] All success criteria from refined spec are met
- [ ] Critical functionality has tests
- [ ] All tests pass (both existing and new)
- [ ] Learnings are captured in real-time
- [ ] Patterns are extracted and documented
- [ ] Review document is comprehensive
- [ ] If last subtask: Task review created
- [ ] Future implementers can learn from your work

## Important Notes for AI Agents

1. **File Organization**:
   - All files go in subtask-specific folders
   - Path: `.taskmaster/tasks/task_X/subtask_X.Y/implementation/`
   - Create directories as needed when writing files

2. **Progress Tracking**:
   - NO task-master updates during work
   - ALL progress goes to `progress-log.md`
   - Update task-master ONLY when marking complete

3. **Task Review Creation**:
   - Only create `task-review.md` after ALL subtasks complete
   - This becomes the summary other tasks will read
   - Individual subtask reviews contain the details

4. **Direct File Operations**:
   - Use Read/Write tools directly
   - Don't use shell commands for file operations
   - Follow explicit paths provided

---

Remember: **Every implementation makes the next one easier. Your learnings are a gift to your future self and teammates.**
