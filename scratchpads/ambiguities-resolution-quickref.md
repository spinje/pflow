# Ambiguities Resolution Quick Reference

## Quick Checklist for Task $ARGUMENTS

### 1. Prerequisites ✓
- [ ] Have full task description
- [ ] Understand related systems
- [ ] Know dependencies

### 2. Investigation ✓
- [ ] Search codebase for existing implementations
- [ ] Verify all assumptions
- [ ] Read relevant documentation

### 3. For Each Ambiguity ✓
- [ ] Clear title with importance (1-5)
- [ ] Context explaining why it matters
- [ ] 2-4 genuine options with pros/cons
- [ ] Concrete examples where helpful
- [ ] Clear recommendation with reasoning

### 4. Document Structure ✓
```
# Task $ARGUMENTS: [Title] - Critical Decisions & Ambiguities
## Executive Summary
## Background Context
## Current Implementation Status
## 1. [Ambiguity] - Decision importance (X)
   ### Context
   ### Options
   **Recommendation**
```

### 5. Output Location ✓
`.taskmaster/tasks/task_$ARGUMENTS/task-$ARGUMENTS-ambiguities.md`

### 6. Key Reminders ✓
- ULTRATHINK for deep analysis
- Verify before assuming
- Consider the implementer's perspective
- Be honest about trade-offs
- Make it self-contained

### 7. Decision Importance Scale ✓
- 5: Architectural (affects multiple components)
- 4: Significant functionality
- 3: Important but limited scope
- 2: Quality/optimization
- 1: Minor details

### 8. Common Ambiguity Sources ✓
- Vague requirements ("appropriate", "large", "fast")
- Missing specifications (where, what format, how)
- Integration questions (interfaces, protocols)
- Performance boundaries
- Error handling strategies
- Backward compatibility

### 9. Success Criteria ✓
- No guesswork needed for implementation
- All "how exactly?" questions answered
- Context makes decisions clear
- Examples demonstrate intent
- Edge cases considered
