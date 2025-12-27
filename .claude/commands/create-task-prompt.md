---
description: Generate implementation prompt for a pflow task
argument-hint: [task-id]
---

# Create Task Implementation Prompt - Meta-Prompt for AI Agents

This command instructs an AI agent to generate a comprehensive implementation prompt for another AI agent who will implement a pflow task.

## Inputs

Inputs: $ARGUMENTS

Available inputs:
- `--task_id`: The ID of the task to create an implementation prompt for (required)

> If you receive only a number (e.g., "21"), assume that is the task_id

## Your Task as the Prompt-Generating Agent

You are tasked with creating a comprehensive implementation prompt for another AI agent who will implement a pflow task. Use your existing context window knowledge.

**Your output**: Generate the prompt and save it to `.taskmaster/tasks/task_{{task_id}}/task-{{task_id}}-implementation-prompt.md`

### 🧠 Your Knowledge Source

**Your existing context window** - everything you already know from your conversation with the user:
- Task discussions you've had with the user
- Implementation details you've learned
- Architectural decisions you're aware of
- Patterns and anti-patterns you've discovered

### Process

1. **Use your existing knowledge** from your context window
2. **Fill the template completely** with your knowledge
3. **Output a comprehensive prompt** ready for immediate use

### 🛑 Decision Points: When to STOP and ASK

**Do NOT proceed with generating the prompt if:**

1. The task_id doesn't match any task you've discussed
2. Critical information is missing from your context
3. You're unsure whether your understanding is correct

**Instead, ask the user:**
- "I'm not certain about [specific aspect]. Could you clarify before I generate the prompt?"
- "Should I deploy subagents to gather more information about [specific aspect] in the codebase?"

### 📝 Quality Checks Before Output

Before generating the prompt, ask yourself:

1. **What do I know from our conversation?** List it mentally
2. **What am I uncertain about?** Mark these clearly
3. **Am I making any assumptions?** Verify or mark them
4. **Is this enough to be useful?** If not, ask for clarification


## Template to Fill

Use this exact structure and replace ALL placeholders with content from your knowledge:

---

# Task {{task_number}}: {{task_title}} - Agent Instructions

## The Problem You're Solving

{{problem_statement}}
<!-- Extract from spec or context files. 2-3 sentences explaining what's broken or missing and why it matters -->

## Your Mission

{{brief_mission_statement}}
<!-- Extract from task spec/description. Should be 1-2 sentences explaining the core objective -->

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first**: This mindset is critical for implementing any task correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Task Overview
**File**: `.taskmaster/tasks/task_{{task_id}}/task_{{task_id}}.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_{{task_id}}/starting-context/`

**Files to read (in this order):**
{{context_file_list}}
<!-- Use LS tool to list all files in the directory, then format as numbered list -->
<!-- Example:
1. `comprehensive-context.md` - Read this for overall understanding
2. `task-21-spec.md` - The specification (source of truth for requirements)
3. `task-21-handover.md` - Context from previous work
4. `implementation-plan.md` - Technical approach
-->

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`*-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

<!-- The prompt-generating agent should use LS to get the actual filenames and list them explicitly -->

## What You're Building

{{detailed_description}}
<!-- Clear explanation of what the feature/component does -->
<!-- Include concrete example of usage if applicable -->

Example:
```{{language}}
{{usage_example}}
```

## Key Outcomes You Must Achieve

### {{outcome_category_1}}
{{outcome_list_1}}
<!-- List specific deliverables as bullet points -->

### {{outcome_category_2}}
{{outcome_list_2}}

<!-- Add more categories as needed based on task complexity -->

## Implementation Strategy

### Phase 1: {{phase1_name}} ({{time_estimate}})
{{phase1_tasks}}
<!-- Break down into numbered steps -->

### Phase 2: {{phase2_name}} ({{time_estimate}})
{{phase2_tasks}}

### Phase 3: {{phase3_name}} ({{time_estimate}})
{{phase3_tasks}}

### Use Subagents effectively

Use subagents to maximize efficiency and avoid context window limitations.

> Always use @agent-pflow-codebase-searcher to gather information, context, do research and verifying assumptions. This is important!
> Always use the @agent-test-writer-fixer subagent for writing tests, fixing test failures, and debugging test issues.
> Always give subagents small isolated tasks, never more than fixes for one file at a time.
> Always deploy subagents in paralel, never sequentially. This means using ONE function call block to deploy all subagents simultaneously.

Implementation should be done by yourself! Write tests using the @agent-test-writer-fixer subagent AFTER implementation is complete.

## Critical Technical Details

### {{technical_detail_1_title}}
{{technical_detail_1_content}}
<!-- Include code snippets for clarity -->

### {{technical_detail_2_title}}
{{technical_detail_2_content}}

<!-- Add more sections as needed based on task complexity -->

## Critical Warnings from Experience

### {{warning_1_title}}
{{warning_1_content}}
<!-- Specific pitfall with example and solution -->

### {{warning_2_title}}
{{warning_2_content}}

<!-- Extract from context files or generate based on task complexity -->

## Key Decisions Already Made

{{decisions_list}}
<!-- Extract from spec or handover documents -->
<!-- Format as numbered list -->

**📋 Note on Specifications**: If a specification file exists for this task, it is the authoritative source. Follow it precisely - do not deviate from specified behavior, test criteria, or implementation requirements unless you discover a critical issue (in which case, document the deviation clearly or STOP and ask the user for clarification).

## Success Criteria

Your implementation is complete when:

{{success_criteria_checklist}}
<!-- Extract from spec, format as checkbox list with ✅ -->
<!-- Always include: ✅ make test passes, ✅ make check passes -->

## Common Pitfalls to Avoid

{{pitfalls_list}}
<!-- Extract from context or generate based on task complexity -->
<!-- Include project-specific patterns to avoid -->

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent subagents from conflicting.

### Why Planning Matters

1. **Prevents duplicate work and conflicts**: Multiple subagents won't edit the same files
2. **Identifies dependencies**: Discover what needs to be built in what order
3. **Optimizes parallelization**: Know exactly what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Codebase Structure Analysis**
   - Task: "Analyze the structure of src/pflow/nodes/ and identify the pattern for adding new node types"
   - Task: "Find all existing node implementations and extract common patterns"

2. **Integration Points Discovery**
   - Task: "Identify how nodes are registered in the registry system"
   - Task: "Analyze how the compiler handles different node types"

3. **Testing Pattern Analysis**
   - Task: "Examine tests/test_nodes/ structure and testing patterns"
   - Task: "Identify test utilities and fixtures used for node testing"

4. **Documentation Requirements**
   - Task: "Check architecture/reference/node-reference.md structure for adding new nodes"
   - Task: "Find examples of node documentation in the codebase"
```

> Note: Your prompts to the subagents should be very specific and detailed. You should be able to tell the subagent exactly what to do and what to look for while providing as much context as possible to the subagent.

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_{{task_id}}/implementation/implementation-plan.md`

Your plan should include:

1. **Comprehensive task breakdown** - Every file to create/modify
2. **Dependency mapping** - What must be done before what
3. **Subagent task assignments** - Who does what, ensuring no conflicts
4. **Risk identification** - What could go wrong and mitigation strategies
5. **Testing strategy** - How you'll verify each component works

### Subagent Task Scoping Guidelines

**✅ GOOD Subagent Tasks:**
```markdown
- "Write a new test case for foo.py that covers the logged‑out user edge case; avoid mocks."
- "Follow the pattern in HotDogWidget.php to implement a new CalendarWidget that lets users paginate months & years (no extra libraries)."
- "test-writer-fixer: Write unit tests for parameter validation in test_workflow_node_params.py focusing on edge cases and error conditions"
- "test-writer-fixer: Review and improve existing tests to ensure they catch real bugs, not just achieve coverage"
```

**❌ BAD Subagent Tasks:**
```markdown
- "Implement the entire WorkflowNode feature" (too broad)
- "Update all files related to nodes" (multiple agents will conflict)
- "Fix any issues you find" (too vague)
```

**Key Rules:**
- One subagent per file
- Specific, bounded edits when modifying existing files
- Include full context about what the subagent needs to know
- Never assign overlapping file modifications
- Always use test-writer-fixer subagent for test creation, test fixes, and final test review
- Always use subagents to gather information from the codebase or docs
- Parallelise only when subtasks are independent and with explicit bounds
- Subagents are your best weapon against unverified assumptions
- Always define termination criteria for subagents

### Implementation Plan Template

```markdown
# Task {{task_id}} Implementation Plan

## Context Gathered

### Codebase Patterns
- [Key patterns discovered from context gathering]

### Integration Points
- [How this feature connects to existing code]

### Dependencies
- [What this implementation depends on]

## Implementation Steps

### Phase 1: Core Infrastructure (Parallel Execution Possible)
1. **Create Package Structure** (Subagent A)
   - Files: src/pflow/nodes/{{feature}}/
   - Context: [What the subagent needs to know]

2. **Add Base Classes** (Subagent B)
   - Files: src/pflow/nodes/{{feature}}/base.py
   - Context: [Specific requirements]

### Phase 2: Implementation (Sequential)
1. **Implement Core Logic**
   - Files: [Specific files]
   - Dependencies: Phase 1 must be complete
   - Key considerations: [Technical details]

### Phase 3: Testing (Parallel Execution Possible)
[Testing tasks broken down by file]

### Phase 4: Integration
[How to integrate with existing system]

### Phase 5: Documentation
[Documentation tasks]

### Phase 6: Final Test Review (use test-writer-fixer)
Deploy test-writer-fixer subagent to review all created tests and ensure they:
- Catch real bugs, not just achieve coverage
- Follow project testing patterns
- Have proper error messages and assertions
- Cover critical edge cases

## Risk Mitigation

| Risk | Mitigation Strategy |
|------|-------------------|
| Circular imports | [Specific approach] |
| Breaking changes | [How to verify] |

## Validation Strategy

- How to verify each component works
- Integration testing approach
- Performance considerations
```

> Use as many Phases and sub tasks as you need to make the plan as detailed and comprehensive as possible.

### When to Revise Your Plan

Your plan is a living document. Update it when:
- Context gathering reveals new requirements
- Implementation hits unexpected obstacles
- Dependencies change
- Better approaches become apparent

Document plan changes in your progress log with rationale.

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_{{task_id}}/implementation/progress-log.md`

```markdown
# Task {{task_id}} Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### Implementation Steps

{{ordered_implementation_steps}}
<!-- Extract from implementation plan or generate based on phases -->
<!-- Format as numbered list with clear actions -->

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to [specific action]...

Result: [What happened]
- ✅ What worked: [Specific detail]
- ❌ What failed: [Specific detail]
- 💡 Insight: [What I learned]

Code that worked:
```{{language}}
# Actual code snippet
```
```

## Handle Discoveries and Deviations

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

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

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
## {{time}} - Testing revealed edge case
{{testing_insight_example}}
```

**Remember**: Quality tests that catch real bugs > many trivial tests

## What NOT to Do

{{what_not_to_do_list}}
<!-- Extract from spec or generate based on common mistakes -->
<!-- Format as bullet points starting with DON'T -->
<!-- Include project-specific anti-patterns -->

## Getting Started

{{getting_started_steps}}
<!-- Provide concrete first steps -->
<!-- Include test command for the specific component -->

## Final Notes

{{final_notes}}
<!-- Task-specific reminders -->
<!-- Emphasize critical aspects -->
<!-- Include any warnings or special considerations -->

## Remember

{{remember_section}}
<!-- Final reinforcement of key concepts -->
<!-- Extract key themes from the task -->

{{motivational_ending}}
<!-- End with encouragement and context about impact -->

---

## How to Extract Information and Fill the Template

Reflect on your conversation and extract:
- Problem descriptions and pain points discussed
- Task objectives and goals mentioned
- Technical decisions and constraints shared
- Implementation strategies considered
- Warnings or pitfalls identified
- Patterns and anti-patterns discovered
- Key outcomes and deliverables
- Success criteria discussed
- What NOT to do (anti-patterns mentioned)

## Example Output

Here's what your generated prompt should look like:

```markdown
# Task 20: Implement WorkflowNode - Agent Instructions

## The Problem You're Solving

Currently, workflows cannot compose other workflows as reusable components. This limits code reuse and forces duplication of common workflow patterns. Users need a way to call workflows from within workflows, similar to how functions call other functions.

## Your Mission

Implement WorkflowNode, a new node type that allows workflows to execute other workflows as sub-components. This is a critical feature that enables workflow composition and reusability in pflow.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first**: This mindset is critical for implementing any task correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Task Overview
**File**: `.taskmaster/tasks/task_20/task_20.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. THIRD: Deep Understanding of WorkflowNode
**File**: `.taskmaster/tasks/task_20/starting_context/workflownode-comprehensive-context.md`

**Purpose**: Complete architectural understanding of how WorkflowNode fits into pflow's execution model, including storage isolation, parameter mapping, and error handling strategies.

**Why read third**: This gives you the conceptual foundation before diving into implementation details.

[... rest of numbered readings ...]

## What You're Building

WorkflowNode is a regular pflow node (inherits from BaseNode) that:
- Loads workflow definitions from JSON files or accepts inline workflow IR
- Compiles and executes these workflows with parameter mapping and storage isolation
- Returns results to the parent workflow

Think of it as enabling this:
```json
{
  "id": "analyze_data",
  "type": "workflow",
  "params": {
    "workflow_ref": "analyzers/sentiment.json",
    "param_mapping": {"text": "$input_text"},
    "output_mapping": {"score": "sentiment_result"}
  }
}
```

## Key Outcomes You Must Achieve

### 1. Core Implementation
- WorkflowNode class in `src/pflow/nodes/workflow/`
- Support for both file references and inline workflows
- Four storage modes: mapped, isolated, scoped, shared
- Proper error handling with context preservation

### 2. Safety Features
- Circular dependency detection
- Depth limiting (default: 10 levels)
- Clear error messages with workflow paths
- Template variable resolution

### 3. Testing & Documentation
- All 26 test criteria from spec passing
- Complete unit and integration tests
- Updated documentation in docs/
- Working examples in examples/

[... continues with all sections filled ...]

## Implementation Strategy

### Phase 1: Core Implementation (2-3 hours)
1. Create the package structure in `src/pflow/nodes/workflow/`
2. Implement WorkflowNode class following the implementation plan
3. Add exception classes to `src/pflow/core/exceptions.py`

### Phase 2: Testing (2-3 hours)
1. Create test structure in `tests/test_nodes/test_workflow/`
2. Implement unit tests (test all 26 test criteria from spec)
3. Implement integration tests

### Phase 3: Documentation (1 hour)
1. Update `architecture/reference/node-reference.md`
2. Create `architecture/features/nested-workflows.md`
3. Add examples in `examples/nested/`

### Use Subagents effectively

Use subagents to maximize efficiency and avoid context window limitations.

> Always use @agent-pflow-codebase-searcher to gather information, context, do research and verifying assumptions. This is important!
> Always use the @agent-test-writer-fixer subagent for writing tests, fixing test failures, and debugging test issues.
> Always give subagents small isolated tasks, never more than fixes for one file at a time.
> Always deploy subagents in paralel, never sequentially. This means using ONE function call block to deploy all subagents simultaneously.

Implementation should be done by yourself! Write tests using the @agent-test-writer-fixer subagent AFTER implementation is complete.

## Critical Technical Details

### Registry Access Pattern
The registry is passed during compilation:
```python
# In your WorkflowNode implementation:
registry = self.params.get("__registry__")  # This is how you get it
compile_ir_to_flow(workflow_ir, registry=registry)  # Pass it along
```

### Reserved Keys
Always use the `_pflow_` prefix for internal keys:
- `_pflow_depth`: Current nesting depth
- `_pflow_stack`: Execution stack for circular detection
- `_pflow_workflow_file`: Current workflow file path

### Storage Modes
Implement all four modes correctly:
- **mapped**: Only explicitly mapped parameters (DEFAULT)
- **isolated**: Completely empty storage
- **scoped**: Filtered view with prefix
- **shared**: Direct reference (dangerous but needed)

### Error Handling
Always preserve context when errors occur:
```python
except Exception as e:
    return {
        "success": False,
        "error": f"Clear error message: {str(e)}",
        "workflow_path": workflow_path
    }
```

## Key Decisions Already Made

1. **WorkflowNode is NOT using Flow-as-Node** - It's an execution wrapper
2. **No workflow registry** - Load files at runtime
3. **No caching** - Keep it simple for MVP
4. **Template resolution uses parent's shared storage** as context
5. **Default storage mode is "mapped"** for safety

## Success Criteria

Your implementation is complete when:

- ✅ All 26 test criteria from the spec pass
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ Documentation is complete and accurate
- ✅ At least one example workflow demonstrates the feature
- ✅ Error messages are clear and actionable
- ✅ No existing functionality is broken

## Common Pitfalls to Avoid

1. **Don't overthink the design** - The implementation plan has working code
2. **Don't add features not in spec** - No caching, no registry, no timeouts
3. **Don't forget error context** - Always wrap errors with workflow path
4. **Don't skip tests** - All 26 test criteria must be covered
5. **Don't modify existing code** unless absolutely necessary

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan following the detailed instructions in the template section above. For WorkflowNode, this means understanding how nodes integrate with the registry, compiler, and execution system before starting implementation.

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_20/implementation/progress-log.md`

```markdown
# Task 20 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### 1. Create Implementation Plan (SECOND!)

Follow the instructions in the "Create Your Implementation Plan FIRST" section above to create a comprehensive plan before any coding.

### 2. Create the package structure
Set up the WorkflowNode package in the correct location

### 3. Implement core functionality
Build the WorkflowNode class with all required methods

### 4. Add error handling
Implement proper error messages and context preservation

### 5. Write comprehensive tests
Cover all test criteria from the specification

### 6. Update documentation
Add to node reference and create feature docs

### 7. Verify everything works
Run full test suite and fix any issues

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

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

## Handle Discoveries and Deviations

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

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

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
While testing extract_metadata(), discovered that nodes with
circular imports crash the scanner. Added import guard pattern.
This affects how we handle all dynamic imports.
```

**Remember**: Quality tests that catch real bugs > many trivial tests

## What NOT to Do

- **DON'T** modify any node implementations
- **DON'T** change the workflow IR structure
- **DON'T** add ANY backward compatibility code
- **DON'T** add features not in spec - No caching, no registry, no timeouts
- **DON'T** skip tests - All test criteria must be covered
- **DON'T** cheat when writing tests - Write tests that actually test the code

## Getting Started

1. Start with Phase 1, Step 1: Create the package structure
2. Follow the implementation plan exactly - the code is tested and ready
3. Run tests frequently: `pytest tests/test_nodes/test_workflow/ -v`
4. Ask questions if anything is unclear

## Final Notes

- The implementation plan has complete, working code - use it!
- Focus on getting the MVP working first
- The spec has all the rules and edge cases clearly defined
- This is a regular node - it doesn't require special treatment by the compiler

## Remember

You're implementing a foundational feature that will unlock workflow composition in pflow. The design in the implementation guide is solid and battle-tested. Trust it, but verify against the epistemic principles. When faced with ambiguity, surface it rather than guessing.

Good luck! This feature will significantly enhance pflow's capabilities by enabling workflow reuse and composition. Think hard!
```

> Note: This is an example of what your generated prompt should look like. The specific details above are from Task 20 and should NOT be copied. Extract the actual content from your context window.

## Critical Reminders for the Prompt-Generating Agent

1. **ALL placeholders must be replaced** - No `{{placeholder}}` should remain in your output
2. **Progress log sections are CRITICAL** - Preserve these sections exactly as shown
3. **Maintain template structure** - Keep all sections in the exact order shown
4. **Include concrete examples** - Add code snippets from your knowledge where relevant
5. **Success criteria must include** - Always add "make test passes" and "make check passes"
6. **Epistemic manifesto is always first** - This must be the first item in the reading list
7. **Extract, don't invent** - Pull content from your knowledge rather than making it up

## What Makes a Good Implementation Prompt

Your generated prompt should:
- Open with the problem to create urgency and context
- Give the implementing agent a clear mission
- Provide all necessary context through the reading list with clear purposes
- Break down work into manageable phases with time estimates
- Warn about specific pitfalls from experience
- Emphasize continuous progress logging
- Include specific technical details from the task
- Provide concrete examples and code snippets
- Explicitly state what NOT to do
- Set clear, measurable success criteria
- End with motivation and impact

## 📁 Output: Where to Save Your Generated Prompt

After thinking extensively and planned the prompt write it to:

`.taskmaster/tasks/task_{{task_id}}/task-{{task_id}}-implementation-prompt.md`


## 🔑 Key Principles to Remember

1. **Use Your Context**: Draw from your existing knowledge from the conversation
2. **Never Invent Information**: Mark unknowns as "TO BE VERIFIED" rather than guessing
3. **Ask When Uncertain**: Better to ask for clarification than generate an unhelpful prompt
4. **Be Explicit**: Clearly distinguish what you KNOW vs what needs verification

Remember: The implementing agent will rely entirely on your generated prompt to complete the task successfully. Make it comprehensive, clear, and actionable.
