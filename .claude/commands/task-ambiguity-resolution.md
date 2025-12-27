---
description: Identify and resolve task ambiguities before implementation
argument-hint: [task-id]
---

# Task Ambiguity Resolution - Meta-Prompt for AI Agents

This command instructs an AI agent to identify and resolve ambiguities for a pflow task before implementation.

## Inputs

Inputs: $ARGUMENTS

Available inputs:
- `--task_id`: The ID of the task to analyze for ambiguities (required)

> If you receive only a number (e.g., "17"), assume that is the task_id

## Your Task as the Ambiguity Resolution Agent

You are tasked with creating a comprehensive ambiguities resolution document for Task {{task_id}} that identifies, analyzes, and resolves all unclear aspects of the implementation. Your primary source of information should be **your existing context window** - everything you already know from your conversation with the user.

**Your output**: Generate the ambiguities document and save it to `.taskmaster/tasks/task_{{task_id}}/task-{{task_id}}-ambiguities.md`

### 🧠 Your Knowledge Sources

1. **Your existing context window**
   - Task discussions you've had with the user
   - Implementation details you've learned
   - Architectural decisions you're aware of
   - Patterns and anti-patterns you've discovered
   - Any relevant context from your conversation

2. **Parallel subagents** for codebase investigation
   - Deploy to verify assumptions against actual code
   - Gather specific implementation patterns
   - Confirm integration points

### Process

1. **ULTRATHINK about what you know** - What do you already understand about Task {{task_id}}?
2. **Identify ambiguities** from your current knowledge
3. **Deploy parallel subagents** to gather specific codebase information (see Section below)
4. **Merge all knowledge** to create comprehensive ambiguity resolutions
5. **Output complete document** with all ambiguities resolved

## 🔍 Step-by-Step Process

### Step 1: Deep Task Analysis (ULTRATHINK)

Use ultrathink to deeply analyze what you know about the task:
- What is the core purpose of this task?
- What systems/components will it touch?
- What are the explicit requirements?
- What is implied but not stated?
- What could go wrong?
- What decisions will the implementer need to make?
- What do I NOT know that I need to find out?

### Step 2: Context Gathering with Parallel Subagents

**Deploy parallel subagents to gather ALL necessary context:**

```markdown
## Context Gathering Tasks (Deploy in Parallel)

### Group 1: Task Understanding
1. **Task Context Analysis**
   - Task: "Read and analyze all files in .taskmaster/tasks/task_{{task_id}}/starting-context/ and provide a comprehensive summary of the task requirements, specifications, and implementation guidance"
   - Task: "Identify all technical requirements and constraints mentioned in the task documentation"

### Group 2: Codebase Investigation
2. **Current Implementation Analysis**
   - Task: "Analyze how [specific component] currently works in the codebase, including its patterns and interfaces"
   - Task: "Find all existing implementations of [similar feature] and extract common patterns"

3. **Integration Points Discovery**
   - Task: "Identify how [feature] integrates with the registry/compiler/runtime system"
   - Task: "Analyze the shared store usage patterns for [component type]"

### Group 3: Pattern and Convention Analysis
4. **Testing Patterns**
   - Task: "Examine the test structure for [similar component] and identify testing patterns"
   - Task: "Find test utilities and fixtures used for [component type] testing"

5. **Documentation Patterns**
   - Task: "Check how [similar features] are documented in docs/"
   - Task: "Identify the documentation structure for [component type]"
```

> Note: Your prompts to subagents should be VERY SPECIFIC and include as much context as possible. Tell them exactly what to look for and why it matters.

### Step 3: Identify True Ambiguities

For each potential ambiguity:
1. **Is this truly unclear?** Or do I just need to verify my understanding?
2. **Would different interpretations lead to different implementations?**
3. **Is this decision important enough to document?**
4. **Can subagents resolve this by investigating the codebase?**

**Important**: Only create multiple options when there are genuinely different viable approaches. If investigation reveals only one logical solution, make it a clarification note rather than a decision.

Common sources of ambiguities:
1. **Vague requirements**: "Handle errors appropriately" - How specifically?
2. **Missing specifications**: "Store data" - Where? What format?
3. **Integration questions**: "Work with existing system" - What's the interface?
4. **Performance/limits**: "Handle large inputs" - How large? What constraints?
5. **Error handling**: What errors? How to recover?
6. **Backward compatibility**: What must be preserved?

### Step 4: Deploy Investigation Subagents

Before documenting ambiguities, thoroughly investigate:

```markdown
## Investigation Tasks for Ambiguity Resolution

### For each identified ambiguity, deploy subagents:

1. **Ambiguity: [Storage format unclear]**
   - Subagent A: "Search for existing storage patterns in similar nodes"
   - Subagent B: "Check how other components handle data persistence"
   - Subagent C: "Look for storage conventions in architecture/core-concepts/shared-store.md"

2. **Ambiguity: [Error handling approach]**
   - Subagent A: "Find error handling patterns in existing nodes"
   - Subagent B: "Check src/pflow/core/exceptions.py for error types"
   - Subagent C: "Analyze how similar features handle failures"
```

## 🛑 Decision Points: When to STOP and ASK

**Do NOT proceed with generating the ambiguities document if:**

1. **No context exists**: You have NO knowledge of the task in your context window
2. **Task mismatch**: The task_id doesn't match any task you've discussed
3. **Critical gaps**: Missing critical information that subagents cannot resolve
4. **Fundamental uncertainty**: Core architectural decisions are completely unclear

**Instead, ask the user:**
```markdown
"I don't have sufficient context about Task {{task_id}} to identify meaningful ambiguities.

Currently unclear:
- [Specific aspect 1]: I need to understand [what and why]
- [Specific aspect 2]: Multiple approaches possible: [option A] vs [option B]

Should I:
1. Deploy subagents to investigate [specific areas]?
2. Or can you provide clarification on [specific questions]?"
```

## 📋 Quality Checks Before Output

Before generating the ambiguities document:

1. **What do I know for certain?** List it mentally
2. **What did subagents discover?** Incorporate findings
3. **What remains genuinely ambiguous?** Only document these
4. **Are my options truly different?** Not just variations
5. **Is this actionable?** Will it help the implementer?

## Document Format

Use this exact format for your ambiguities document:

```markdown
# Task {{task_id}}: [Task Title] - Critical Decisions & Ambiguities

## Executive Summary

[Brief description of the task and why these ambiguities matter]

**Key Ambiguities Identified**:
1. [First major ambiguity - resolved/unresolved]
2. [Second major ambiguity - resolved/unresolved]
3. [Continue for all major ambiguities]

**Information Sources Used**:
- Context window knowledge: [What you knew]
- Subagent investigations: [What was discovered]
- Remaining unknowns: [What couldn't be determined]

## Background Context

[Explain the system/component this task touches, why it exists,
how it currently works, and why this task is needed. Include findings
from subagent investigations.]

## Current Implementation Status

[Document what already exists based on subagent findings. Include
code examples, file locations, and current behavior.]

## Ambiguities and Resolutions

### 1. [First Ambiguity Title] - Decision importance (1-5)

**Status**: ✅ Resolved / ⚠️ Needs User Input

[Describe the ambiguity and why a decision is needed]

**Investigation Results**:
[What subagents discovered about this ambiguity]

#### Context:
[Detailed context about why this ambiguity exists]

#### Options:

- [ ] **Option A: [Descriptive name]**
  - [Description of this approach]
  - **Benefits**: [Why this might be good]
  - **Drawbacks**: [What problems this might cause]
  - **Example**: [Code example if applicable]
  - **Precedent**: [Similar pattern found in codebase]

- [x] **Option B: [Descriptive name]** ✓ **SELECTED**
  - [Description of this approach]
  - **Benefits**: [Why this is better]
  - **Drawbacks**: [Honest assessment]
  - **Example**: [Concrete example]
  - **Precedent**: [Where this pattern is used]

**Recommendation**: Option B - [Explain WHY based on investigation]

**Subagent Findings**:
- [Specific discovery that informed this decision]
- [Pattern found in similar implementations]

[Continue for each ambiguity...]

## Implementation Guidance Based on Resolutions

[Synthesize the resolutions into clear implementation guidance]

## Remaining Uncertainties

[List anything that couldn't be resolved even with investigation]

## Appendix: Investigation Details

### Subagent Reports Summary
[Brief summary of what each subagent group discovered]

### Key Patterns Discovered
[Important patterns found during investigation]

### Files and Components Analyzed
[List of relevant files discovered during investigation]
```

## Decision Importance Scale

Rate each decision's importance:
- **5**: Architectural decision affecting multiple components
- **4**: Significant implementation choice affecting functionality
- **3**: Important for correctness but limited scope
- **2**: Quality of life or optimization decision
- **1**: Minor detail that won't significantly impact outcome

## Parallel Subagent Best Practices

### Effective Subagent Task Design

**✅ GOOD Subagent Tasks:**
```markdown
- "Analyze all error handling patterns in src/pflow/nodes/ and identify the standard approach for handling validation errors, execution errors, and recovery strategies"
- "Read and summarize the complete specification in .taskmaster/tasks/task_17/starting-context/task-17-spec.md, focusing on requirements, constraints, and success criteria"
- "Search for all uses of the shared store pattern in workflow execution and document how parameters are passed between nodes"
```

**❌ BAD Subagent Tasks:**
```markdown
- "Understand the task" (too vague)
- "Find information about nodes" (too broad)
- "Look for problems" (not specific)
```

### Subagent Deployment Strategy

```markdown
## Phase 1: Broad Understanding (Deploy all in parallel)
- Task A: Read and analyze task specification
- Task B: Investigate current implementation patterns
- Task C: Find similar features in codebase
- Task D: Analyze test patterns

## Phase 2: Targeted Investigation (Based on Phase 1 findings)
- Task E: Deep dive into [specific ambiguity found]
- Task F: Verify [specific pattern discovered]
- Task G: Check [specific integration point]

## Phase 3: Verification (Final checks)
- Task H: Confirm [specific approach] is used consistently
- Task I: Verify no conflicts with [specific component]
```

## Verification Checklist

Before finalizing, verify:
- [ ] Every ambiguity has investigation results from subagents
- [ ] Context sections include discovered information
- [ ] Options are genuinely different (not variations)
- [ ] Examples come from actual codebase discoveries
- [ ] Document synthesizes all available knowledge
- [ ] Technical details are verified by subagents
- [ ] Edge cases were investigated
- [ ] Integration points are confirmed

## Example Opening for Your Document

```markdown
# Task {{task_id}}: [Task Title] - Critical Decisions & Ambiguities

## Executive Summary

Task {{task_id}} aims to [core purpose from your knowledge/investigation]. While the high-level goal is clear, several implementation details require decisions that will significantly impact [what it impacts]. This document resolves these ambiguities based on extensive investigation of the codebase and existing patterns.

**Key Ambiguities Identified**:
1. [Ambiguity 1] - ✅ Resolved through codebase investigation
2. [Ambiguity 2] - ✅ Resolved by finding existing patterns
3. [Ambiguity 3] - ⚠️ Requires user decision between viable options

**Information Sources Used**:
- Context window: Detailed discussion of task requirements and constraints
- 12 parallel subagents: Investigated codebase patterns and conventions
- Remaining unknowns: [Any specific detail] requires user clarification
```

## Critical Reminders

1. **Context window first**: Your conversation knowledge is the PRIMARY source
2. **Parallel investigation**: Deploy multiple subagents to gather information quickly
3. **Verify everything**: Don't assume - have subagents check
4. **Only real ambiguities**: Don't create options where investigation shows only one way
5. **Mark unknowns clearly**: Use `[TO BE VERIFIED]` for gaps in knowledge
6. **Ask when blocked**: Better to ask than guess

## 📁 Output: Where to Save Your Document

After extensive investigation and analysis, write your document to:

`.taskmaster/tasks/task_{{task_id}}/task-{{task_id}}-ambiguities.md`

## Remember

The goal is to eliminate guesswork for the implementing agent by:
1. Using your existing knowledge effectively
2. Deploying subagents to investigate thoroughly
3. Resolving ambiguities through discovery not speculation
4. Providing clear options only where genuinely needed
5. Creating a self-contained guide for confident implementation

Your ambiguities document should demonstrate deep investigation and understanding, not just surface-level questions. Use parallel subagents aggressively to turn uncertainties into verified knowledge.
