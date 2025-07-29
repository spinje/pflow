# Task 21: Implement Workflow Input Declaration - Agent Instructions

## The Problem You're Solving

Workflows currently cannot declare their expected input parameters in the IR schema, making validation impossible and usage unclear. When users try to execute workflows with missing or incorrect parameters, they get cryptic template resolution errors instead of helpful messages about what inputs the workflow actually needs. This prevents the "Plan Once, Run Forever" philosophy from working effectively.

## Your Mission

Implement input declaration for workflows in the IR schema, enabling workflows to specify required and optional parameters with types, descriptions, and default values. This will provide compile-time validation, better error messages, and make workflows self-documenting.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach

**File:** `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose:** Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first:** This mindset is critical for implementing any task correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Task Overview

**File:** `.taskmaster/tasks/task_21/task_21.md`

**Purpose:** High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second:** This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. THIRD: Read all available files in the starting context directory

**File:** `.taskmaster/tasks/task_21/starting_context/`

**Purpose:** Contains all the files you need to understand the task and implement it.

**Important:** You must read all the files in the starting context directory to understand the task and implement it. (Do not skip any files and carefully think through the implications of each file between each read file)

## What You're Building

You're implementing a mechanism for workflows to declare their expected input parameters directly in the IR schema. This enables workflows to be self-documenting and allows for validation before execution.

**Example:**
```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "issue_number": {
      "description": "GitHub issue number to fix",
      "required": true,
      "type": "string"
    },
    "repo_name": {
      "description": "Repository name (owner/repo format)",
      "required": false,
      "type": "string",
      "default": "pflow/pflow"
    }
  },
  "nodes": [
    {
      "id": "fetch",
      "type": "github-get-issue",
      "params": {
        "issue": "$issue_number",
        "repo": "$repo_name"
      }
    }
  ]
}
```

## Key Outcomes You Must Achieve

### Schema and Validation

- Extend IR schema in `src/pflow/core/ir_schema.py` with `WorkflowInput` model
- Add optional `inputs` field to the workflow IR schema
- Implement Pydantic validation for the new schema components
- Ensure backward compatibility (workflows without inputs still work)

### Compiler Enhancement

- Update `src/pflow/runtime/compiler.py` to extract and validate input declarations
- Validate `initial_params` against declared inputs before template resolution
- Apply default values for missing optional inputs
- Provide clear, helpful error messages that reference input descriptions

### Integration and Testing

- Integrate with existing template validation system
- Create comprehensive test suite covering all scenarios
- Update documentation to reflect new capabilities
- Ensure no breaking changes to existing workflows

## Implementation Strategy

### Phase 1: Schema Extension (1-2 hours)

1. Create `WorkflowInput` model in `src/pflow/core/ir_schema.py`
   - Add fields: `description`, `required`, `type`, `default`
   - Implement proper Pydantic validation
2. Add optional `inputs` field to workflow IR schema
3. Ensure JSON Schema generation includes new fields
4. Write unit tests for schema validation

### Phase 2: Compiler Integration (2-3 hours)

1. Update compiler to extract input declarations during compilation
2. Implement validation of `initial_params` against declared inputs
3. Add logic to apply default values for optional inputs
4. Create detailed error messages that include input descriptions
5. Write comprehensive tests for compiler validation

### Phase 3: Template Validator Enhancement (1-2 hours)

1. Update template validator to use input descriptions in error messages
2. Optionally validate that all template variables have corresponding input declarations
3. Improve error context with parameter information
4. Add tests for enhanced error messages

## Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

**Always use subagents to gather information, context, do research and verifying assumptions. This is important!**
**Always use subagents to work on debugging, testing and writing tests.**

## Critical Technical Details

### Type System Design

The type system should be simple and focused on documentation, not strict enforcement:
```python
ALLOWED_TYPES = ["string", "number", "boolean", "object", "array"]
```
Types are hints for users and documentation - actual validation should be minimal in MVP.

### Backward Compatibility Pattern

Ensure existing workflows continue to work:
```python
# In compiler
inputs_declaration = workflow_ir.get("inputs", {})  # Default to empty
if inputs_declaration:
    # New validation logic
else:
    # Existing behavior unchanged
```

### Error Message Format

Provide helpful, actionable error messages:
```python
# Bad: "Missing parameter"
# Good: "Workflow requires input 'issue_number' (GitHub issue number to fix)"
```

### Default Value Application

Apply defaults early in compilation:
```python
for input_name, input_spec in inputs_declaration.items():
    if input_name not in initial_params and not input_spec.get("required", True):
        initial_params[input_name] = input_spec.get("default")
```

## Critical Warnings from Experience

### Input/Output Asymmetry

Based on our discussion, Task 21 only addresses inputs, but workflows also need output declarations for proper composition. Be aware that this creates an incomplete interface - consider adding a TODO comment about future output declaration support.

### Multiple Declaration Locations

Currently, workflow inputs exist in multiple places (metadata vs IR). This implementation moves them into the IR as the source of truth. Be careful not to break existing code that might expect inputs in metadata.

### Template Variable Alignment

Input names **MUST** match the template variable names used in the workflow. For example, if you declare an input named `"issue_number"`, nodes must use `"$issue_number"` to reference it.

## Key Decisions Already Made

1. The `inputs` field is completely optional - existing workflows must continue working unchanged
2. Types are documentation hints, not strict validation in MVP
3. Validation happens at compile time, not runtime
4. Input declarations go in the IR, not metadata (addressing the architectural issue we discovered)
5. Focus on simple types only - no complex schemas or nested validation
6. Error messages must include the input description to be helpful

## Success Criteria

Your implementation is complete when:

- ✅ `WorkflowInput` schema is properly defined with all required fields
- ✅ Workflows can declare inputs with description, required, type, and default
- ✅ Compiler validates `initial_params` against input declarations
- ✅ Missing required inputs produce clear error messages with descriptions
- ✅ Optional inputs use default values when not provided
- ✅ All existing workflows continue to work unchanged (backward compatibility)
- ✅ Template validator integrates with input descriptions for better errors
- ✅ All unit tests pass covering various scenarios
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ Documentation is updated to show the new feature

## Common Pitfalls to Avoid

- **DON'T** break existing workflows - the `inputs` field must be optional
- **DON'T** implement strict type validation - types are hints only in MVP
- **DON'T** forget to handle the case where inputs is an empty object
- **DON'T** mix up metadata inputs (list of strings) with IR inputs (detailed objects)
- **DON'T** create complex validation logic - keep it simple
- **DON'T** forget that input names must be valid Python identifiers
- **DON'T** skip edge case testing (null values, empty defaults, etc.)

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you **MUST** create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent subagents from conflicting.

### Why Planning Matters

1. **Prevents duplicate work and conflicts:** Multiple subagents won't edit the same files
2. **Identifies dependencies:** Discover what needs to be built in what order
3. **Optimizes parallelization:** Know exactly what can be done simultaneously
4. **Surfaces unknowns early:** Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

#### Context Gathering Tasks (Deploy in Parallel)

1. **Schema Analysis**
   - Task: "Analyze `src/pflow/core/ir_schema.py` to understand the current workflow IR schema structure and how to add new fields"
   - Task: "Find examples of optional fields in the IR schema and how backward compatibility is maintained"

2. **Compiler Pattern Analysis**
   - Task: "Examine `src/pflow/runtime/compiler.py` to understand how it currently handles `initial_params` and where to add validation"
   - Task: "Find where compile-time validation happens and how errors are reported"

3. **Template Validator Integration**
   - Task: "Analyze `src/pflow/runtime/template_validator.py` to understand current error message generation"
   - Task: "Identify integration points for enhancing error messages with input descriptions"

4. **Testing Patterns**
   - Task: "Review `tests/test_core/test_ir_schema.py` for schema testing patterns"
   - Task: "Check `tests/test_runtime/test_compiler.py` for compiler validation test patterns"

> **Note:** Your prompts to the subagents should be very specific and detailed. You should be able to tell the subagent exactly what to do and what to look for while providing as much context as possible to the subagent.

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_21/implementation/implementation-plan.md`

Your plan should include:

1. **Comprehensive task breakdown** - Every file to create/modify
2. **Dependency mapping** - What must be done before what
3. **Subagent task assignments** - Who does what, ensuring no conflicts
4. **Risk identification** - What could go wrong and mitigation strategies
5. **Testing strategy** - How you'll verify each component works

### Subagent Task Scoping Guidelines

#### ✅ GOOD Subagent Tasks:
- "Add `WorkflowInput` model to `ir_schema.py` following the pattern of existing models like `NodeModel`"
- "Write unit tests for `WorkflowInput` validation in `test_ir_schema.py` covering required/optional fields"
- "Update compiler's `validate_initial_params` method to check against input declarations"

#### ❌ BAD Subagent Tasks:
- "Implement the entire input declaration feature" (too broad)
- "Update all validation code" (multiple agents will conflict)
- "Fix any issues you find" (too vague)

#### Key Rules:
- One subagent per file
- Specific, bounded edits when modifying existing files
- Include full context about what the subagent needs to know
- Never assign overlapping file modifications
- Always use subagents to fix bugs, test, and write tests
- Always use subagents to gather information from the codebase or docs
- Parallelise only when subtasks are independent and with explicit bounds
- Subagents are your best weapon against unverified assumptions
- Always define termination criteria for subagents

### Implementation Plan Template

```markdown
# Task 21 Implementation Plan

## Context Gathered

### Current Schema Structure
- [How IR schema is organized]
- [Pattern for optional fields]
- [Backward compatibility approach]

### Compiler Validation Pattern
- [Where validation happens]
- [How errors are reported]
- [Initial params handling]

### Integration Points
- [Template validator integration]
- [Registry implications]

## Implementation Steps

### Phase 1: Schema Extension
1. **Create WorkflowInput Model** (Subagent A)
   - File: src/pflow/core/ir_schema.py
   - Context: [Specific requirements for the model]
   - Dependencies: None

2. **Add inputs field to IR** (Subagent B)
   - File: src/pflow/core/ir_schema.py
   - Context: [How to add optional field]
   - Dependencies: WorkflowInput model must exist

### Phase 2: Compiler Integration
[Detailed breakdown]

### Phase 3: Testing
[Test file assignments]

## Risk Mitigation

| Risk | Mitigation Strategy |
|------|-------------------|
| Breaking existing workflows | Ensure inputs field is optional with proper defaults |
| Type validation complexity | Keep types as hints only, no strict validation |

## Validation Strategy

- Unit tests for schema validation
- Integration tests for compiler behavior
- Manual testing with example workflows
```

Use as many Phases and sub tasks as you need to make the plan as detailed and comprehensive as possible.

### When to Revise Your Plan

Your plan is a living document. Update it when:
- Context gathering reveals new requirements
- Implementation hits unexpected obstacles
- Dependencies change
- Better approaches become apparent

Document plan changes in your progress log with rationale.

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_21/implementation/progress-log.md`

```markdown
# Task 21 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

Update this file AS YOU WORK - every discovery, every bug, every insight!

### Implementation Steps

1. Create comprehensive implementation plan with context gathering
2. Implement `WorkflowInput` model in `ir_schema.py`
3. Add `inputs` field to workflow IR schema
4. Update JSON Schema generation
5. Implement compiler validation logic
6. Add default value application
7. Enhance error messages with descriptions
8. Integrate with template validator
9. Write comprehensive unit tests
10. Write integration tests
11. Update documentation
12. Verify backward compatibility

## Real-Time Learning Capture

AS YOU IMPLEMENT, continuously append to your progress log:

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

### Handle Discoveries and Deviations

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

### Core Principle: "Test what matters"

Focus on quality over quantity:
- Test public interfaces and critical paths
- Test edge cases where bugs typically hide
- Create integration tests when components interact
- Document only interesting test discoveries in your progress log

### What to test:
- **Critical paths:** Input validation logic in compiler
- **Public APIs:** `WorkflowInput` model validation
- **Error handling:** Missing required inputs, type mismatches
- **Integration points:** Compiler + template validator interaction

### What NOT to test:
- Simple getters/setters
- Configuration loading
- Framework code
- Internal helper functions (unless complex)

### Progress Log - Only document testing insights:
```markdown
## 14:50 - Testing revealed edge case
Discovered that default values must match declared types.
Added validation to ensure defaults are type-compatible.
```

> **Remember:** Quality tests that catch real bugs > many trivial tests

## What NOT to Do

- **DON'T** implement output declarations (that's a separate task/decision)
- **DON'T** break backward compatibility - existing workflows must work
- **DON'T** implement strict type enforcement - types are hints only
- **DON'T** forget to test empty inputs object `{}`
- **DON'T** mix up metadata inputs with IR inputs
- **DON'T** skip validation of input names (must be valid identifiers)
- **DON'T** forget to handle null/undefined gracefully

## Getting Started

1. Read the epistemic manifesto to understand the approach
2. Create your progress log file
3. Deploy subagents for context gathering
4. Create comprehensive implementation plan
5. Start with Phase 1: Schema extension
6. Run tests frequently: `pytest tests/test_core/test_ir_schema.py -v`

## Final Notes

- This implementation addresses only inputs, not outputs (be aware of the asymmetry)
- The architectural issue of multiple input locations is resolved by using IR as source of truth
- Keep the implementation simple - this is MVP, not a full type system
- Focus on user experience - clear error messages are more important than complex validation

## Remember

You're implementing a foundational feature that makes workflows self-documenting and validates parameters before execution fails with cryptic errors. This directly supports the "Plan Once, Run Forever" philosophy by making workflows easier to understand and use correctly.

The implementation should be simple, backward compatible, and focused on improving the user experience. When in doubt, choose clarity over cleverness.

Good luck! This feature will significantly improve workflow usability and make pflow more approachable for new users.
