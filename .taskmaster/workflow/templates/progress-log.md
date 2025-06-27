# Learning Log for [Task/Subtask ID]

**File Location**: `.taskmaster/tasks/task_[X]/subtask_[X.Y]/implementation/progress-log.md`

Started: [Date Time]
Plan: implementation-plan.md

---

## [HH:MM] - Starting Implementation

Environment check:
- Working directory: `[pwd output]`
- Git branch: `[branch name]`
- Dependencies verified: ✓
- Test suite passing: ✓

---

## [HH:MM] - Step 1: [Step Name from Plan]

**Attempting**: [What you're trying to do]

```[language]
// Code I'm trying
[actual code]
```

**Result**: [SUCCESS/FAILURE/PARTIAL]

### What Worked ✅
- [Specific thing that worked]
- [Another success]

### What Failed ❌
- Error: `[exact error message]`
- Cause: [Your understanding of why]

### Key Insight 💡
[Important realization about the codebase/pattern/approach]

### Code That Works
```[language]
// This successfully does X
[working code snippet]
```

**Time taken**: [X] minutes (estimated [Y])

---

## [HH:MM] - Deviation from Plan

**Original Plan**: [What step 2 was supposed to be]

**Why It Won't Work**: [Specific reason discovered]

**New Approach**: [What you're trying instead]

```[language]
// New approach code
[code]
```

**Result**: SUCCESS

**Lesson**: [What this teaches about the system]

**Update task-master**: ✓
```bash
task-master update-subtask --id=[X.Y] --prompt="DEVIATION: [summary]"
```

---

## [HH:MM] - Pattern Emerging

While implementing [feature], discovered a reusable pattern:

**Pattern**: [Descriptive name]

```[language]
// The pattern
[code showing the pattern]
```

**Why It's Useful**: [Explanation]

**Other Tasks That Could Use This**: [Task X.Y, Task A.B]

**Documented in**: new-patterns.md ✓

---

## [HH:MM] - Unexpected Discovery

**Found**: [What you discovered]

**Impact**: This means [implication]

**Affects Other Tasks**:
- Task [X.Y]: Will need to [change]
- Task [A.B]: Can now [leverage this]

**Documented in**: affects-tasks.md ✓

---

## [HH:MM] - Testing Insights

**Only document tests that revealed something interesting:**

### Failed Test That Taught Something
```python
def test_[function]_[scenario]():
    # This test failed and revealed [insight]
    result = function(edge_case_input)
    # Expected X but got Y because [reason]
```
**Learning**: [What this failure taught about the system]

### Edge Case Discovery
- Scenario: [What edge case you found]
- Why it matters: [Impact on the system]
- How to handle: [Solution implemented]

### Testing Pattern Emerged
- Pattern: [Reusable testing approach discovered]
- When to use: [Situations where this helps]

---

## [HH:MM] - Performance Observation

Operation: [What you measured]
- Expected: [X]ms
- Actual: [Y]ms
- Reason: [Why different]

**Optimization**: [If applicable, what made it faster]

---

## [HH:MM] - Integration Challenge

**Problem**: [Component X] doesn't work with [Component Y]

**Investigation**:
1. Checked [what you looked at]
2. Found [what you discovered]
3. Root cause: [the real issue]

**Solution**: [How you fixed it]

**Lesson**: Always check [specific thing] when integrating [type of component]

---

## [HH:MM] - Final Testing

### All Tests Run
```bash
$ make test
[output]
```

Result: [PASS/FAIL]

### Manual Verification
- [x] [Test case 1]: Works correctly
- [x] [Test case 2]: Expected behavior
- [ ] [Test case 3]: [Issue found]

---

## [HH:MM] - Implementation Complete

### Summary Stats
- Total time: [X] hours (estimated [Y])
- Deviations from plan: [N]
- New patterns discovered: [N]
- Tasks affected: [N]

### Test Summary
- **Coverage**: [X]% of new code (target was >80%)
- **All tests passing**: ✅ YES / ❌ NO
- **Key testing insight**: [Most important thing learned from testing]

### Key Learnings
1. **Most Important**: [The #1 thing you learned]
2. **Surprised by**: [What you didn't expect]
3. **Will remember**: [What to do next time]

### Updated Documentation
- [ ] Review document created
- [ ] Patterns extracted
- [ ] Tests documented
- [ ] Task-master updated
- [ ] Affected tasks noted

---

**Status**: READY FOR REVIEW
*Proceed to create subtask-review.md*
