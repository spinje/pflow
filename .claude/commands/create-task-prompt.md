# Create Task Implementation Prompt - Meta-Prompt for AI Agents

This command instructs an AI agent to generate a comprehensive implementation prompt for another AI agent who will implement a pflow task.

## Usage

```
/create-task-prompt <task_id>
```

## Your Task as the Prompt-Generating Agent

You are tasked with creating a comprehensive implementation prompt for another AI agent who will implement a pflow task. You will:

1. **Read ALL files** in `.taskmaster/tasks/<task_id>/starting-context/`
2. **Extract key information** from these files to understand the task completely
3. **Fill in the template below** by replacing ALL `{{placeholders}}` with specific content from the context files
4. **Output a complete prompt** that another agent can use to implement the task successfully

## Template to Fill

Use this exact structure and replace ALL placeholders with content extracted from the context files:

---

# Task {{task_number}}: {{task_title}} - Agent Instructions

## Your Mission

{{brief_mission_statement}}
<!-- Extract from task spec/description. Should be 1-2 sentences explaining the core objective -->

## Required Reading (Read in This Order)

1. **FIRST**: `.taskmaster/workflow/epistemic-manifesto.md` - The manifesto that guides your thinking. Your mindset while working on this task.
2. **SECOND**: `.taskmaster/tasks/task_{{task_id}}/starting_context/{{primary_context_file}}` - {{context_description}}
<!-- List all files from starting-context/ folder in priority order -->
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

## Key Decisions Already Made

{{decisions_list}}
<!-- Extract from spec or handover documents -->
<!-- Format as numbered list -->

## Success Criteria

Your implementation is complete when:

{{success_criteria_list}}
<!-- Extract from spec, format as checkbox list -->
<!-- Always include: make test passes, make check passes -->

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

## Getting Started

{{getting_started_steps}}
<!-- Provide concrete first steps -->
<!-- Include test command for the specific component -->

## Final Notes

{{final_notes}}
<!-- Task-specific reminders -->
<!-- Emphasize critical aspects -->
<!-- Include any warnings or special considerations -->

---

## How to Extract Information and Fill the Template

When reading the context files, look for:

1. **Task Number and Title**: Usually in the filename or document header
2. **Mission Statement**: First paragraph of spec or "Objective" section
3. **Primary Context File**: Look for comprehensive context documents or main spec files
4. **Detailed Description**: "What You're Building" or "Overview" sections
5. **Implementation Phases**: Break down from implementation plans or create logical phases
6. **Technical Details**: Requirements, constraints, or technical considerations sections
7. **Key Decisions**: "Decisions Made" sections or handover documents
8. **Success Criteria**: "Success Criteria" or "Test Requirements" sections
9. **Getting Started Steps**: First concrete actions from implementation plans

## Example Output

Here's an example of what your generated prompt should look like:

```markdown
# Task 20: Implement WorkflowNode - Agent Instructions

## Your Mission

Implement WorkflowNode, a new node type that allows workflows to execute other workflows as sub-components. This is a critical feature that enables workflow composition and reusability in pflow.

## Required Reading (Read in This Order)

1. **FIRST**: `.taskmaster/workflow/epistemic-manifesto.md` - The manifesto that guides your thinking. Your mindset while working on this task.
2. **SECOND**: `.taskmaster/tasks/task_20/starting_context/workflownode-comprehensive-context.md` - Deep understanding of how WorkflowNode fits into pflow
3. **THIRD**: `.taskmaster/tasks/task_20/starting_context/20_handover.md` - Additional context about the investigation phase
4. **FOURTH**: `pocketflow/__init__.py` - The pocketflow framework (yes this is all the code, less than 200 lines of code)
5. **FIFTH**: `.taskmaster/tasks/task_20/starting_context/20_spec.md` - The complete specification with all requirements, rules, and test criteria
6. **SIXTH**: `.taskmaster/tasks/task_20/starting_context/workflownode-implementation-plan.md` - Step-by-step implementation guide with complete code

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

1. ✅ All 26 test criteria from the spec pass
2. ✅ `make test` passes with no regressions
3. ✅ `make check` passes (linting, type checking)
4. ✅ Documentation is complete
5. ✅ At least one example workflow demonstrates the feature

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

### 1. Start with understanding
Read the MetadataExtractor tests to see all format variations

### 2. Implement scanner changes
Add dependency injection and interface parsing

### 3. Update validator
Full path traversal replacing heuristics

### 4. Simplify context builder
Remove parsing, use stored data

### 5. Run full test suite
Ensure nothing breaks

### 6. Clean up
Remove all old heuristic code

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

Good luck! This feature will significantly enhance pflow's capabilities. Think hard and critically, this is hard task!

```

> Note: This is an example of what your generated prompt should look like. It is not a template that you should use. You should use the template to create a prompt that is tailored to the task at hand.
> Ignore all the specific details in the example above. Remember it is just an example.

## Critical Reminders for the Prompt-Generating Agent

1. **ALL placeholders must be replaced** - No `{{placeholder}}` should remain in your output
2. **Progress log sections are CRITICAL** - Preserve these sections exactly as shown
3. **Read ALL context files** - Don't skip any files in the starting-context folder
4. **Maintain template structure** - Keep all sections in the exact order shown
5. **Include concrete examples** - Add code snippets from context files where relevant
6. **Success criteria must include** - Always add "make test passes" and "make check passes"
7. **Epistemic manifesto is always first** - This must be the first item in the reading list

## What Makes a Good Implementation Prompt

Your generated prompt should:
- Give the implementing agent a clear mission
- Provide all necessary context through the reading list
- Break down work into manageable phases
- Emphasize continuous progress logging
- Include specific technical details from the task
- Provide concrete examples and code snippets
- Set clear success criteria
- Warn about common pitfalls

Remember: The implementing agent will rely entirely on your generated prompt to complete the task successfully. Make it comprehensive, clear, and actionable.
