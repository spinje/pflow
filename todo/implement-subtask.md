# Subtask Implementation Workflow

Your goal is to implement the refined specification for subtask `<subtaskId>` while capturing ALL learnings for future tasks. This document covers Phase 2 (Implementation) only.

**PREREQUISITE**: You must have completed the refinement workflow (`refining-subtask.md`) and have a clear, unambiguous specification ready.

## Core Principles

1. **Learn while doing** - Capture discoveries AS THEY HAPPEN
2. **No knowledge lost** - Both successes and failures are valuable
3. **Patterns emerge** - Extract reusable solutions for future tasks
4. **Feedback enriches** - Your learnings make everyone better

## Prerequisites

**Required:**
- Completed refinement with `ready-for-implementation` marker
- Refined specification in task-master
- Clear success criteria defined
- Test strategy identified

**Inputs from Refinement:**
- `.taskmaster/tasks/task_<parentTaskId>/refinement/refined-spec.md`
- `.taskmaster/tasks/task_<parentTaskId>/refinement/knowledge-synthesis.md`
- Task-master entry with refined details

## Phase 2: Implementation

### Goal
Execute the refined specification systematically while capturing all learnings in real-time for future benefit.

### Activities

#### 2.1 Pre-Implementation Setup

```bash
# Verify refinement is complete
test -f .taskmaster/tasks/task_<parentTaskId>/refinement/ready-for-implementation
# Should exist

# Load the refined specification
task-master show --id=<subtaskId>
# Should show REFINEMENT COMPLETE in details
```

Create implementation workspace:
```bash
mkdir -p .taskmaster/tasks/task_<parentTaskId>/implementation
cd .taskmaster/tasks/task_<parentTaskId>/implementation
```

#### 2.2 Create Implementation Plan

Create `plan.md` based on refined specification:

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
- Using [Pattern X] from [Task Y] for [specific part]
- Avoiding [Anti-pattern Z] discovered in [Task W]

## Risk Mitigations
- [Risk]: [Mitigation strategy]
```

#### 2.3 Begin Implementation

```bash
# Mark as in-progress
task-master set-status --id=<subtaskId> --status=in-progress

# Initialize learning log
echo "# Learning Log for <subtaskId>" > progress-log.md
echo "Started: $(date)" >> progress-log.md
```

#### 2.4 Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously update both local log and task-master:

**Local Learning Log** (`progress-log.md`):
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

**Task-Master Updates** (every significant discovery):
```bash
task-master update-subtask --id=<subtaskId> --prompt="
DISCOVERY [$(date)]:
- Tried: [approach]
- Result: [what happened]
- Learning: [key insight]
- Code: [snippet if valuable]
"
```

#### 2.5 Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Update the plan with new approach
4. Continue with new understanding

```bash
# Log the deviation
task-master update-subtask --id=<subtaskId> --prompt="
DEVIATION [$(date)]:
- Original plan: [what was planned]
- Why it failed: [specific reason]
- New approach: [what you're trying instead]
- Lesson: [what this teaches us]
"
```

**When you discover something that affects other tasks:**

Create `affects-tasks.md`:
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

#### 2.6 Testing and Validation

Execute test strategy from refined spec:

```bash
# Run tests continuously during implementation
make test  # or appropriate test command

# Document test discoveries
echo "## Test Insights" >> progress-log.md
echo "- Test X revealed [insight]" >> progress-log.md
```

#### 2.7 Extract Patterns

As patterns emerge, document them immediately:

Create `new-patterns.md`:
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

#### 2.8 Create Implementation Review

Once functional, create comprehensive `review.md`:

```markdown
# Implementation Review for <subtaskId>

## Summary
- Started: [Date/time]
- Completed: [Date/time]
- Deviations from plan: [Count and severity]

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

#### 2.9 Final Learning Integration

```bash
# Push all learnings to task-master
task-master update-subtask --id=<subtaskId> \
  --prompt="IMPLEMENTATION COMPLETE: $(< review.md)"

# Extract patterns to knowledge base
cp new-patterns.md ../../knowledge/patterns/
cp affects-tasks.md ../../impact/

# Mark complete
task-master set-status --id=<subtaskId> --status=done
```

#### 2.10 Git Commit

Create meaningful commit with context:

```bash
git add .
git commit -m "feat: Implement <subtaskId> - [brief description]

Key learnings:
- [Major discovery 1]
- [Major discovery 2]

Patterns documented in .taskmaster/knowledge/patterns/
See .taskmaster/tasks/task_<parentTaskId>/implementation/review.md for details"
```

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
```bash
# Document the issue
echo "REFINEMENT NEEDED: [reason]" > refinement-needed.md

# Update task-master
task-master update-subtask --id=<subtaskId> \
  --prompt="BLOCKED: Refinement needed - [specific issue]"

# Return to refining-subtask.md
```

## Success Metrics

Your implementation is successful when:
- [ ] All success criteria from refined spec are met
- [ ] All tests pass
- [ ] Learnings are captured in real-time
- [ ] Patterns are extracted and documented
- [ ] Review document is comprehensive
- [ ] Task-master contains complete history
- [ ] Future implementers can learn from your work

---

Remember: **Every implementation makes the next one easier. Your learnings are a gift to your future self and teammates.**
