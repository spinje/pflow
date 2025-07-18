# Ambiguities Resolution Evaluation and Process

## Prerequisites Check

Before beginning, ensure you have:
1. Read and understood the task description for Task $ARGUMENTS
2. Reviewed any related documentation in `docs/` that pertains to this task
3. Identified the key components/systems this task will interact with

**If you lack sufficient context about Task $ARGUMENTS, STOP and request:**
- The full task description and details
- Related documentation references
- Dependencies and relationships to other tasks
- The broader system context

## Your Mission

Create a comprehensive ambiguities resolution document for Task $ARGUMENTS that identifies, analyzes, and resolves all unclear aspects of the implementation. This document will guide the implementing agent to make correct decisions without guesswork.

**Dual Purpose**:
1. **For the implementer**: Clear guidance on how to proceed
2. **For the user**: Easy review with clear options that can be changed if needed

**Output Location**: `.taskmaster/tasks/task_$ARGUMENTS/task-$ARGUMENTS-ambiguities.md`

## Step-by-Step Process

### Step 1: Deep Task Analysis (ULTRATHINK)

Use ultrathink to deeply analyze the task:
- What is the core purpose of this task?
- What systems/components will it touch?
- What are the explicit requirements?
- What is implied but not stated?
- What could go wrong?
- What decisions will the implementer need to make?

### Step 2: Codebase Investigation

Before identifying ambiguities, investigate the current state:

```markdown
Examples of what to search for:
- If task mentions "extend X", find and read X
- If task mentions "integrate with Y", understand Y's interface
- If task references patterns/approaches, find existing examples
- Check for similar implementations in the codebase
```

Use these tools in parallel when possible:
- `Grep` for pattern searching
- `Read` for understanding specific files
- `Task` sub-agents for complex searches

**Critical**: Verify every assumption! Don't assume something exists or works a certain way without checking.

### Step 3: Identify Ambiguities

For each ambiguity you identify, ask yourself:
- Is this truly unclear or am I missing context?
- Would different interpretations lead to different implementations?
- Is this decision important enough to document?

**Important**: Only create multiple options when there are genuinely different viable approaches. If something has only one logical solution, make it a brief note or clarification rather than a full decision section. Don't add options just for the sake of having options.

Common sources of ambiguities:
1. **Vague requirements**: "Handle errors appropriately" - How specifically?
2. **Missing specifications**: "Store data" - Where? What format?
3. **Integration questions**: "Work with existing system" - What's the interface?
4. **Performance/limits**: "Handle large inputs" - How large? What constraints?
5. **Error handling**: What errors? How to recover?
6. **Backward compatibility**: What must be preserved?

### Step 4: Document Format

Use this exact format for your ambiguities document:

```markdown
# Task $ARGUMENTS: [Task Title] - Critical Decisions & Ambiguities

## Executive Summary

[Brief description of the task and why these ambiguities matter]

**Key Ambiguities**:
1. [First major ambiguity]
2. [Second major ambiguity]
3. [Continue for all major ambiguities]

## Background Context

[Add a section explaining the system/component this task touches, why it exists,
how it currently works, and why this task is needed. Make the document self-contained.]

## Current Implementation Status

[Document what already exists that's relevant to this task. Include code examples,
file locations, and current behavior. This prevents reimplementing existing features.]

## 1. [First Ambiguity Title] - Decision importance (1-5)

[Describe the ambiguity clearly and why a decision is needed]

### Context:
[Provide detailed context about why this ambiguity exists and what depends on it]

### Options:

- [ ] **Option A: [Descriptive name]**
  - [Description of this approach]
  - **Benefits**: [Why this might be good]
  - **Drawbacks**: [What problems this might cause]
  - **Example**: [If applicable, show what this would look like]

- [x] **Option B: [Descriptive name]** ✓ **SELECTED**
  - [Description of this approach]
  - **Benefits**: [Why this is better]
  - **Drawbacks**: [Honest assessment of limitations]
  - **Example**: [Concrete example if helpful]

- [ ] **Option C: [Descriptive name]**
  - [Description]
  - **Benefits**: [Pros]
  - **Drawbacks**: [Cons]

**Recommendation**: Option B - [Explain WHY this is the best choice given the context]

**Note**: Each option must be genuinely viable. The user can easily change the selection by moving the [x] to a different option. Make sure each option would result in a working implementation, just with different trade-offs.

[Continue for each ambiguity...]
```

### Step 5: Special Sections to Include

Based on the task type, consider adding:

#### For UI/Display Tasks:
- "Example Output" sections showing before/after
- "User Experience Considerations"
- "Error Message Examples"

#### For Parser/Data Processing Tasks:
- "Edge Cases and Limitations"
- "Input/Output Examples"
- "Error Recovery Strategies"

#### For Integration Tasks:
- "Integration Points"
- "API/Interface Specifications"
- "Backward Compatibility Requirements"

#### For Performance-Critical Tasks:
- "Performance Constraints"
- "Optimization Boundaries"
- "Scaling Considerations"

### Step 6: Decision Importance Scale

Rate each decision's importance:
- **5**: Architectural decision affecting multiple components
- **4**: Significant implementation choice affecting functionality
- **3**: Important for correctness but limited scope
- **2**: Quality of life or optimization decision
- **1**: Minor detail that won't significantly impact outcome

### Step 7: Practical Examples

Include concrete examples wherever possible:

```markdown
### Example from Task 15:

## 9. Structure Display in Planning Context - Decision importance (3)

How should structures be displayed in the planning context markdown?

### Context:
The planning context will be read ONLY by an LLM (not humans). The LLM needs to understand data structures to generate valid proxy mappings like `"author": "issue_data.user.login"`.

### Options:
[Multiple options with concrete examples showing the actual format]

- [x] **Option E: Combined format (JSON + Paths)** ✓ **SELECTED**
  ```markdown
  Structure (JSON format):
  ```json
  {
    "issue_data": {
      "user": {
        "login": "str"
      }
    }
  }
  ```

  Available paths:
  - issue_data.user.login (str) - GitHub username
  ```

**Recommendation**: Option E - Combined format provides optimal LLM comprehension through redundant representations.
```

### Step 8: Verification Checklist

Before finalizing, verify:
- [ ] Every ambiguity has a clear recommendation
- [ ] Context sections explain WHY the decision matters
- [ ] Options are genuinely different (not variations of the same idea)
- [ ] Examples are concrete and helpful
- [ ] Document is self-contained (reader doesn't need external context)
- [ ] Technical details are accurate (verified in codebase)
- [ ] Edge cases are considered
- [ ] Integration points are clear

### Step 9: Critical Thinking Reminders

Throughout this process:
1. **ULTRATHINK freely** - Don't just identify surface-level ambiguities
2. **Question everything** - If something seems assumed, verify it
3. **Consider the implementer** - What would confuse or block them?
4. **Think about consequences** - How do these decisions cascade?
5. **Be honest about trade-offs** - No option is perfect
6. **Provide clear rationale** - WHY is more important than WHAT

## Example Opening for Your Document

Here's how you might start:

```markdown
# Task $ARGUMENTS: [Task Title] - Critical Decisions & Ambiguities

## Executive Summary

Task $ARGUMENTS aims to [core purpose]. While the high-level goal is clear, several implementation details require decisions that will significantly impact [what it impacts]. This document resolves these ambiguities to ensure consistent, correct implementation.

**Key Ambiguities**:
1. [Ambiguity 1] - How should we [specific question]?
2. [Ambiguity 2] - What approach for [specific challenge]?
3. [etc.]

## Background Context

[Explain the system this task touches, why it matters, current state, etc.]
```

## Final Reminders

1. **This is a thinking document** - Show your reasoning, not just conclusions
2. **Be thorough** - Better to document too much than miss something critical
3. **Stay practical** - Academic perfection < working solution
4. **Consider MVP vs future** - What's needed now vs. nice to have later
5. **Test your recommendations** - Can they actually be implemented?

## Output Verification

Your completed document should:
- Answer every "how" and "what exactly" question about the task
- Provide clear direction without constraining implementation details
- Include enough context for decisions to make sense in isolation
- Guide the implementer to success without ambiguity

Remember: The goal is to eliminate guesswork and ensure the implementing agent can proceed with confidence, making the same decisions you would make with full context.
