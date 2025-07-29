# Create Task Implementation Prompt - Meta-Prompt for AI Agents

This command instructs an AI agent to generate a comprehensive implementation prompt for another AI agent who will implement a pflow task.

## Inputs

Inputs: $ARGUMENTS

Available inputs:
- `--task_id`: The ID of the task to create an implementation prompt for (required)
- `--read_context`: Whether to read the context files from disk (default: false)

> If you receive only a number (e.g., "21"), assume that is the task_id with read_context=false

## 🚨 CRITICAL: File Reading Rules

**NEVER read files unless `--read_context` is explicitly set to true!**

- If `read_context` is false or not specified → DO NOT read any files
- If `read_context` is true → Read the files in `.taskmaster/tasks/<task_id>/starting-context/`
- No exceptions to this rule

## Your Task as the Prompt-Generating Agent

You are tasked with creating a comprehensive implementation prompt for another AI agent who will implement a pflow task. Your primary source of information should be **your existing context window** - everything you already know from your conversation with the user.

### 🧠 Your Knowledge Sources

1. **Primary Source (ALWAYS)**: Your existing context window
   - Task discussions you've had with the user
   - Implementation details you've learned
   - Architectural decisions you're aware of
   - Patterns and anti-patterns you've discovered
   - Any relevant context from your conversation

2. **Secondary Source (ONLY if read_context=true)**: Files on disk
   - Read to supplement and verify your existing knowledge
   - Fill gaps in your understanding
   - Get precise specifications

### Path 1: DEFAULT Behavior (read_context=false)

**Use your existing knowledge from the conversation to fill the template:**

1. **Draw from your context window** - What do you already know about Task {{task_id}}?
2. **Fill in the template** using your existing knowledge
3. **Be explicit about what you know** vs what the implementing agent needs to verify
4. **NEVER make things up** - If you don't know something, mark it as `{{placeholder_name - TO BE VERIFIED}}`
5. **Output a prompt** that acknowledges both what's known and what needs verification

### Path 2: Enhanced Mode (read_context=true)

**Combine your existing knowledge with file contents:**

1. **Start with what you already know** from your context window
2. **Read the files** in `.taskmaster/tasks/<task_id>/starting-context/`
3. **Merge your knowledge** - Use files to verify, correct, and expand your understanding
4. **Fill the template completely** with the combined knowledge
5. **Output a comprehensive prompt** ready for immediate use

### 🛑 Decision Points: When to STOP and ASK

**Do NOT proceed with generating the prompt if:**

1. You have NO knowledge of the task in your context window AND read_context=false
2. The task_id doesn't match any task you've discussed
3. Critical information is missing that you can't mark as "TO BE VERIFIED"
4. You're unsure whether your understanding is correct

**Instead, ask the user:**
- "I don't have sufficient context about Task {{task_id}} in my current conversation. Should I read the context files (--read_context=true) or can you provide more information? Currently these are the ambiguous parts... go on to describe all the things you are not sure about along with a alternative options and recommendations"
- "I'm not certain about [specific aspect]. Could you clarify before I generate the prompt?"
- "Currently I have to make a lot of assumptions about the current state of the codebase. Should I deploy subagents to gather more information about [specific aspect] in the codebase?"

### 📝 Quality Checks Before Output

Before generating the prompt, ask yourself:

1. **What do I know from our conversation?** List it mentally
2. **What am I uncertain about?** Mark these clearly
3. **Am I making any assumptions?** Verify or mark them
4. **Is this enough to be useful?** If not, ask for clarification

### Example Outputs

**When you KNOW the task well (read_context=false):**
```markdown
# Task 21: Implement Workflow Input Declaration - Agent Instructions

## The Problem You're Solving

Workflows currently cannot declare their expected inputs, making validation impossible and usage unclear. Users get cryptic errors when required parameters are missing. [Based on our discussion about parameter validation issues]

## Your Mission

Implement input declaration for workflows in the IR schema, enabling workflows to specify required and optional parameters with types and defaults. [As we discussed in the context of improving workflow usability]

[... continue with known information, marking uncertain areas ...]
```

**When you have LIMITED knowledge (read_context=false):**
```markdown
# Task 21: {{Verify exact title from context files}} - Agent Instructions

## The Problem You're Solving

{{TO BE VERIFIED - Check the spec for the exact problem statement. From our discussion, this relates to workflow parameter handling}}

## Your Mission

Based on our conversation, this task involves workflow input improvements, but you'll need to verify the exact scope in the context files.

[... template with clear markers for what needs verification ...]
```

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

### 3. THIRD: {{primary_context_title}}
**File**: `.taskmaster/tasks/task_{{task_id}}/starting_context/{{primary_context_file}}`

**Purpose**: {{primary_context_purpose}}
<!-- What this document contains and why it's important -->

**Why read third**: {{primary_context_reasoning}}
<!-- Why this needs to be read before other files -->

<!-- Continue numbering for all files in starting-context/ folder -->
<!-- Always include pocketflow/__init__.py for tasks involving pocketflow -->
<!-- Include spec file last if present -->

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

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use subagents to work on debugging, testing and writing tests.

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

## Success Criteria

Your implementation is complete when:

{{success_criteria_checklist}}
<!-- Extract from spec, format as checkbox list with ✅ -->
<!-- Always include: ✅ make test passes, ✅ make check passes -->

## Common Pitfalls to Avoid

{{pitfalls_list}}
<!-- Extract from context or generate based on task complexity -->
<!-- Include project-specific patterns to avoid -->

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

### From Your Context Window (Primary Source):

Reflect on your conversation and extract:
- Problem descriptions and pain points discussed
- Task objectives and goals mentioned
- Technical decisions and constraints shared
- Implementation strategies considered
- Warnings or pitfalls identified
- Patterns and anti-patterns discovered

### From Context Files (Only if read_context=true):

1. **Problem Statement**: Look for sections explaining what's broken, missing, or needs improvement
2. **Task Number and Title**: Usually in the filename or document header
3. **Mission Statement**: First paragraph of spec or "Objective" section
4. **Primary Context File**: Look for comprehensive context documents or main spec files
5. **Key Outcomes**: Look for deliverables, components to build, or specific changes needed
6. **Detailed Description**: "What You're Building" or "Overview" sections
7. **Implementation Phases**: Break down from implementation plans or create logical phases
8. **Technical Details**: Requirements, constraints, or technical considerations sections
9. **Warnings**: Look for "gotchas", "pitfalls", or "lessons learned" sections
10. **Key Decisions**: "Decisions Made" sections or handover documents
11. **What NOT to Do**: Anti-patterns, things to avoid, or explicit "don't" statements
12. **Success Criteria**: "Success Criteria", "Test Requirements", or "Acceptance Criteria" sections
13. **Getting Started Steps**: First concrete actions from implementation plans

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
1. Update `docs/reference/node-reference.md`
2. Create `docs/features/nested-workflows.md`
3. Add examples in `examples/nested/`

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use subagents to work on debugging, testing and writing tests.

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

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_20/implementation/progress-log.md`

```markdown
# Task 20 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### 1. Create the package structure
Set up the WorkflowNode package in the correct location

### 2. Implement core functionality
Build the WorkflowNode class with all required methods

### 3. Add error handling
Implement proper error messages and context preservation

### 4. Write comprehensive tests
Cover all test criteria from the specification

### 5. Update documentation
Add to node reference and create feature docs

### 6. Verify everything works
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

> Note: This is an example of what your generated prompt should look like. The specific details above are from Task 20 and should NOT be copied. Extract the actual content from the task's context files.

## Critical Reminders for the Prompt-Generating Agent

1. **ALL placeholders must be replaced** - No `{{placeholder}}` should remain in your output
2. **Progress log sections are CRITICAL** - Preserve these sections exactly as shown
3. **Read ALL context files (when read_context=true)** - Don't skip any files in the starting-context folder when reading is enabled
4. **Maintain template structure** - Keep all sections in the exact order shown
5. **Include concrete examples** - Add code snippets from your knowledge where relevant
6. **Success criteria must include** - Always add "make test passes" and "make check passes"
7. **Epistemic manifesto is always first** - This must be the first item in the reading list
8. **Extract, don't invent** - Pull content from your knowledge/context files rather than making it up

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

## 🔑 Key Principles to Remember

1. **Context Window First**: Your existing knowledge from the conversation is your PRIMARY source
2. **Never Read Without Permission**: DO NOT read files unless --read_context=true
3. **Never Invent Information**: Mark unknowns as "TO BE VERIFIED" rather than guessing
4. **Ask When Uncertain**: Better to ask for clarification than generate an unhelpful prompt
5. **Be Explicit**: Clearly distinguish what you KNOW vs what needs verification

Remember: The implementing agent will rely entirely on your generated prompt to complete the task successfully. Make it comprehensive, clear, and actionable - using the knowledge you already have.
