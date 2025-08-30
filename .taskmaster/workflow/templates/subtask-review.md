# Implementation Review for [Task/Subtask ID]

**File Location**: `.taskmaster/tasks/task_[X]/subtask_[X.Y]/implementation/subtask-review.md`

*Completed: [Date]*

## Summary

- **Started**: [Date/time from progress log]
- **Completed**: [Date/time]
- **Total Duration**: [X hours Y minutes]
- **Plan Accuracy**: [X]% (followed [Y] of [Z] planned steps)
- **Deviations**: [Number] significant, [Number] minor

## What Worked Well

### 1. [Successful Approach/Pattern Name]
**Description**: [What you did]
**Why it worked**: [Specific reason for success]
**Reusable**: ✅ Yes / ❌ No
**Confidence**: [High/Medium/Low]

**Code Example**:
```[language]
// This pattern solved [problem]
[specific code that worked]
```

**When to use again**:
- Situation: [When this pattern applies]
- Benefits: [What it provides]
- Caveats: [Any warnings]

### 2. [Another Success]
[Follow same structure]

## What Didn't Work

### 1. [Failed Approach Name]
**What we tried**: [Specific approach]
**Why it seemed right**: [Initial reasoning]
**Why it failed**: [Root cause analysis]
**Time wasted**: [X minutes]

**Failed code**:
```[language]
// DON'T DO THIS
[code that didn't work]
// Fails because: [reason]
```

**How to avoid**:
- Red flag: [What to watch for]
- Instead do: [Better approach]

### 2. [Another Failure]
[Follow same structure]

## Key Learnings

### 1. **Fundamental Truth**: [Core Discovery]
**Evidence**: [How we know this is true]
**Context**: Discovered while [doing what]

**Implications**:
- For architecture: [Impact]
- For future tasks: [What changes]
- For documentation: [What needs updating]

### 2. **Assumption Corrected**: [What We Thought vs Reality]
**We assumed**: [Original assumption]
**Reality is**: [What's actually true]
**Found out when**: [Specific moment/test]
**This means**: [Implications going forward]

### 3. **Performance Insight**: [Discovery about speed/efficiency]
**Measurement**: [Specific metric]
**Surprise**: [What was unexpected]
**Optimization**: [What made it better]

## Patterns Extracted

### Pattern: [Descriptive Pattern Name]
**File**: `new-patterns.md`
**Summary**: [One-line description]
**Applicable to tasks**: [List of task IDs that could use this]
**Maturity**: [Experimental/Proven/Standard]

## Impact on Other Tasks

### Critical Impacts (Blocks/Changes Required)

#### Task [X.Y]: [Task Name]
**Impact**: BLOCKING - [What must change]
**Reason**: [Why it's affected]
**Recommendation**: [Specific action needed]
**Priority**: HIGH

### Enhancement Opportunities

#### Task [A.B]: [Task Name]
**Impact**: Can now use [pattern/approach]
**Benefit**: [What it gains]
**Priority**: MEDIUM

### Information Only

#### Task [M.N]: [Task Name]
**FYI**: [Relevant discovery]
**No action needed but good to know**

## Documentation Updates Needed

### Must Update (Incorrect/Misleading)
- [ ] `architecture/[file].md` - [What's wrong] → [Correct info]
- [ ] `README.md` - Section [X] implies [wrong thing]

### Should Enhance (Add Learnings)
- [ ] Architecture docs - Add [pattern/decision]
- [ ] Setup guide - Include [discovered requirement]

### Nice to Have
- [ ] Examples - Add [new example showing pattern]

## Advice for Future Implementers

### If you're implementing something similar...

**DO**:
1. Start with [specific approach] because [reason]
2. Use [pattern] for [situation]
3. Test [edge case] early - it reveals [issue]

**DON'T**:
1. Try [approach] - it fails because [reason]
2. Assume [assumption] - reality is [truth]
3. Skip [step] - you'll need it for [reason]

**WATCH OUT FOR**:
- [Specific gotcha]: Shows up as [symptom]
- [Hidden dependency]: Not documented but [component] requires [thing]
- [Performance trap]: [Operation] is O(n²) when [condition]

### Useful Commands/Snippets

```bash
# This helped debug [issue]
[command with explanation]
```

```[language]
// This helper function was invaluable
[reusable code snippet]
```

## Questions for Team

1. **Architecture**: Should we [architectural question]?
2. **Standards**: Is [approach] our preferred pattern for [situation]?
3. **Performance**: Is [X]ms acceptable for [operation]?

## Final Status

### Delivered
- ✅ All success criteria met
- ✅ All tests passing
- ✅ No regressions detected
- ✅ Documentation updated
- ✅ Patterns extracted

### Follow-up Needed
- [ ] Task [X.Y] needs update based on discovery
- [ ] Performance optimization opportunity in [area]
- [ ] Refactor [code] to use new pattern

### Confidence Level
**Overall**: [High/Medium/Low]
**Reasoning**: [Why you have this confidence level]

---

## Appendix: Raw Metrics

```
Test Results:
[paste test output]

Performance Profile:
[paste profiler output]

Code Coverage:
[paste coverage report]
```

---

*This review serves as institutional memory. Future implementers start here.*
