---
description: Generate post-implementation review document
argument-hint: [task-id]
---

# Create Task Review - Meta-Prompt for Post-Implementation Documentation

This command instructs an AI agent to generate a comprehensive task review document optimized for future AI agent consumption.

## Inputs

Inputs: --task_id=$ARGUMENTS

Available inputs:
- `task_id`: The ID of the completed task to review (required)

---

## 🎯 **Your Mission**: Implementation Archaeology for AI Agents

You are creating a **task review document** in .md format that will be the PRIMARY reference for future AI agents implementing related tasks. This is not a report for humans—it's a **knowledge transfer protocol** for AI systems that need to understand:

1. What was ACTUALLY built (vs. what was planned)
2. HOW it integrates with the existing system
3. WHY certain decisions were made
4. WHAT patterns emerged that should be reused
5. WHERE the dangerous edges are

## 🧠 **Your Edge**: You Have the Implementation Context

Unlike future agents who will only see specs and code, you have:
- The **implementation journey**—what worked, what didn't, what surprised you
- The **user's reactions and course corrections** during development
- The **undocumented assumptions** that proved critical
- The **integration battles** that shaped the final design
- The **test failures** that revealed hidden requirements

This context is GOLD for future implementations. Don't let it vanish.

## 🛑 **Decision Points: When to STOP and ASK**

**Do NOT proceed with the review if:**
1. You didn't implement the task yourself
2. Critical implementation details are missing from your context
3. The task is still in progress or blocked
4. You're unsure about the actual impact on other components

**Instead, ask the user:**
- "I need more context about Task {{task_id}}'s implementation. Was this task completed?"
- "Could you provide details about what was actually built for Task {{task_id}}?"

## 🔁 **Self-Reflection Loop**

Before writing the review, answer these questions:

1. **What did I build that wasn't in the original spec?**
2. **Which components did I touch that I didn't expect to?**
3. **What patterns from this task should become standard?**
4. **What assumptions did the spec make that were wrong?**
5. **Which integration points are now load-bearing?**
6. **What would break if someone naive modified this code?**
7. **What test cases caught real bugs (vs. just coverage)?**
8. **Which parts of my implementation are fragile vs. robust?**
9. **What would I do differently with hindsight?**
10. **What context would make a future agent 10x faster?**

## 🧠 **Think Deep: Make Your Plan**

**ULTRATHINK** before writing. Create a detailed mental map of:
- Every file you touched and why
- Every component that now depends on your changes
- Every pattern you established or broke
- Every test that actually matters
- Every warning future agents need

## 📝 **Template Structure**

Use this EXACT structure for the review (skip sections if necessary):

```markdown
# Task {{task_id}} Review: {{title}}

## Metadata
<!-- Include Implementation Date if available -->
<!-- Include Session ID if available -->
<!-- Include Pull Request URL if available -->

## Executive Summary
<!-- 2-3 sentences: What was built and its impact on the system -->

## Implementation Overview

### What Was Built
<!-- Concrete description of actual implementation -->
<!-- Include deviations from original spec -->

### Implementation Approach
<!-- High-level approach taken and why -->
<!-- Key architectural decisions -->

## Files Modified/Created

### Core Changes
<!-- List with purpose and impact -->
<!-- Format: `path/to/file.py` - What changed and why -->

### Test Files
<!-- Test files created/modified -->
<!-- Which tests are critical vs. nice-to-have -->

## Integration Points & Dependencies

### Incoming Dependencies
<!-- What depends on this task's implementation -->
<!-- Format: Component -> This Task (via what interface) -->

### Outgoing Dependencies
<!-- What this task depends on -->
<!-- Format: This Task -> Component (via what interface) -->

### Shared Store Keys
<!-- Any shared store keys created or consumed -->
<!-- Format: `key_name` - Purpose and data structure -->

## Architectural Decisions & Tradeoffs

### Key Decisions
<!-- Major decisions with reasoning -->
<!-- Format: Decision -> Reasoning -> Alternative considered -->

### Technical Debt Incurred
<!-- Shortcuts taken for MVP -->
<!-- What should be refactored later and why -->

## Testing Implementation

### Test Strategy Applied
<!-- How you actually tested this -->
<!-- Coverage vs. quality tradeoffs -->

### Critical Test Cases
<!-- Tests that catch real issues -->
<!-- Format: test_name - What it validates -->

## Unexpected Discoveries

### Gotchas Encountered
<!-- Surprises during implementation -->
<!-- Hidden requirements or constraints -->

### Edge Cases Found
<!-- Non-obvious scenarios to handle -->

## Patterns Established

### Reusable Patterns
<!-- Patterns other tasks should follow -->
<!-- Include code snippets if helpful -->

### Anti-Patterns to Avoid
<!-- What didn't work and why -->

## Breaking Changes

### API/Interface Changes
<!-- Any changes to existing interfaces -->

### Behavioral Changes
<!-- Changes in system behavior -->

## Future Considerations

### Extension Points
<!-- Where future features should hook in -->

### Scalability Concerns
<!-- What needs attention as system grows -->

## AI Agent Guidance

### Quick Start for Related Tasks
<!-- Specific advice for agents working on related features -->
<!-- Key files to read first -->
<!-- Patterns to follow -->

### Common Pitfalls
<!-- Mistakes to avoid based on your experience -->

### Test-First Recommendations
<!-- Which tests to write/run first when modifying -->

---

*Generated from implementation context of Task {{task_id}}*
```

> Note: If you are not sure about something, leave it out of the review. Skip sections if you have nothing important to say or if you are not sure about the information.
> It is better to have a review that is not complete than a review that is not accurate. It is better to have a review that is short and packed with important information than a review that is long and just rambling.

## ✅ **What to Include**

- **Actual vs. Planned**: Where implementation diverged from spec and why
- **Cross-Component Impact**: Every touchpoint with other modules
- **Pattern Genesis**: New patterns you introduced that should propagate
- **Test Wisdom**: Which tests actually prevent regressions
- **Integration Secrets**: Non-obvious coupling or dependencies
- **Performance Insights**: Bottlenecks or optimizations discovered
- **Error Handling**: How errors propagate through the system
- **Configuration**: Any new settings, env vars, or config files
- **Database/Store Changes**: Schema modifications or new keys
- **API Contract Changes**: Modified interfaces or protocols

## 🚫 **What NOT to Include**

- Generic implementation steps anyone could derive from code
- Boilerplate explanations of obvious code
- Rehashing the original spec requirements
- Generic best practices or platitudes
- Implementation details visible from reading the code
- Personal opinions unrelated to technical decisions

## 📦 **Output Location**

Save your review to:
```
.taskmaster/tasks/task_{{task_id}}/task-review.md
```

> Note: The file location is important. Do not change it.
> If not task_id is provided, save the document to the scratchpad directory.

## 🚀 **MVP Context Reminder**

We're building an MVP with **ZERO users**. This means:
- Breaking changes are acceptable if they improve the system
- Don't over-engineer for scale we don't have
- Document the simple path, not every edge case
- Focus on patterns that will survive v2.0

## 🔑 **Key Principles**

1. **Future Agent First**: Write for AI agents, not humans
2. **Implementation Truth**: Document what IS, not what SHOULD BE
3. **Pattern Propagation**: Highlight reusable patterns explicitly
4. **Integration Focus**: Emphasize connection points
5. **Test Reality**: Only document tests that catch real issues
6. **Discoverable Knowledge**: Use clear headings and searchable terms

Remember: This review is the bridge between your implementation and all future work on the system. Make it count.