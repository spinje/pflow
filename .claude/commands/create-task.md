# Create Task Overview File - Meta-Prompt for AI Agents

This command instructs an AI agent to generate a task overview file that documents a pflow task's essential information.

## Usage

```
/create-task <task_id>
```

## Inputs

Inputs: $ARGUMENTS

Available inputs:
- `task_id`: The ID of the task to create an overview file for (required)
- `--read_spec`: Whether to read the spec file if it exists (default: false)

> If you receive only a number (e.g., "24"), assume that is the task_id with read_spec=false

## 🚨 CRITICAL: File Reading Rules

**NEVER read files unless `--read_spec` is explicitly set to true!**

- If `read_spec` is false or not specified → DO NOT read any files
- If `read_spec` is true → Read ONLY the spec file in `.taskmaster/tasks/<task_id>/starting-context/*-spec.md`
- No exceptions to this rule

## Your Task as the Task Overview Generator

You are tasked with creating a comprehensive task overview file for a pflow task. Your primary source of information should be **your existing context window** - everything you already know from your conversation with the user about this task.

**Your output**: Generate the task overview and save it to `.taskmaster/tasks/task_{{task_id}}/task-{{task_id}}.md`

### 🧠 Your Knowledge Sources

1. **Primary Source (ALWAYS)**: Your existing context window
   - Task discussions you've had with the user
   - Design decisions and requirements mentioned
   - Dependencies and priorities discussed
   - Testing approaches considered

2. **Secondary Source (ONLY if read_spec=true)**: Specification file
   - Read to extract exact requirements
   - Use for test strategy details
   - Verify your understanding

### Path 1: DEFAULT Behavior (read_spec=false)

**Use your existing knowledge from the conversation:**

1. **Draw from your context window** - What do you already know about Task {{task_id}}?
2. **Check if task directory exists** - Use LS on `.taskmaster/tasks/task_{{task_id}}/` to verify
3. **Fill in the template** using your existing knowledge
4. **Be explicit about uncertainty** - If you're unsure about something, note it
5. **Output the task file** with all sections completed

### Path 2: Enhanced Mode (read_spec=true)

**Combine your existing knowledge with spec file:**

1. **Start with what you already know** from your context window
2. **Find and read the spec file** in `.taskmaster/tasks/{{task_id}}/starting-context/*-spec.md`
3. **Extract precise details** - Requirements, test criteria, dependencies
4. **Merge your knowledge** - Use spec to verify and expand your understanding
5. **Output a comprehensive task file** with verified information

### 🛑 Decision Points: When to STOP and ASK

**Do NOT proceed with generating the task file if:**

1. You have NO knowledge of the task in your context window
2. The task_id doesn't match any task you've discussed
3. Critical information is missing (title, description, or purpose)
4. There is ambiguity of what scope the task has
5. There is contradictions in what the spec file says and what you know from the conversation,
6. There is internal contradictions from the conversation that has not been resolved yet

**Instead, ask the user:**
- "I don't have sufficient context about Task {{task_id}}. Could you provide a brief description of what this task should accomplish?"
- "I'm not certain about the dependencies for this task. Could you clarify what other tasks need to be completed first?"

## Template to Fill

Use this exact structure for the task file:

```markdown
# Task {{task_id}}: {{title}}

## ID
{{task_id}}

## Title
{{title}}
<!-- A clear, concise title that describes what the task accomplishes -->
<!-- Example: "Implement Workflow Input Declaration" -->

## Description
{{description}}
<!-- 2-3 sentences explaining what this task does and why it's needed -->
<!-- Focus on the business value and user-facing impact -->

## Status
{{status}}
<!-- Valid values: "not started", "in progress", "completed", "blocked" -->
<!-- Based on your conversation context -->

## Dependencies
{{dependencies}}
<!-- List task IDs that must be completed before this task -->
<!-- For each dependency, explain WHY it's needed and WHAT integration points exist -->
<!-- Format: "- Task X: Title - Explanation of why this is a dependency" -->
<!-- If none, write "None" -->

## Priority
{{priority}}
<!-- Valid values: "high", "medium", "low" -->
<!-- Based on discussion context or "medium" if unclear -->

## Details
{{details}}
<!-- Comprehensive explanation of the task -->
<!-- Include:
  - What needs to be built/changed
  - Key technical considerations
  - Integration points with existing code
  - Any design decisions already made
-->

## Test Strategy
{{test_strategy}}
<!-- How this feature will be tested -->
<!-- Include:
  - Unit test approach
  - Integration test requirements
  - Key test scenarios to cover
  - Reference to spec test criteria if known
-->
```

**⚠️ IMPORTANT**: Use ONLY these 8 top-level headings (##) exactly as shown:
- `## ID`
- `## Title`
- `## Description`
- `## Status`
- `## Dependencies`
- `## Priority`
- `## Details`
- `## Test Strategy`

Do NOT add additional top-level headings. You MAY add sub-headings (### or ####) within these sections if needed for organization.

## Example Output

Here's what your generated task file should look like:

```markdown
# Task 99: Implement Pizza Topping Validator

## ID
99

## Title
Implement Pizza Topping Validator

## Description
Create a validation service that ensures pizza topping combinations are compatible and within acceptable limits. This will prevent invalid orders and improve customer satisfaction by catching configuration errors early.

## Status
not started

## Dependencies
- Task 87: Implement Ingredient Database - The validator needs access to ingredient properties and compatibility rules stored in the database
- Task 92: Create Pricing Engine - Topping validation must integrate with pricing to enforce maximum topping limits based on pizza size

## Priority
high

## Details
The Pizza Topping Validator will ensure order integrity by validating topping combinations before orders are submitted. Currently, invalid combinations cause kitchen errors and customer complaints. This task will:

- Create a `ToppingValidator` class with rule-based validation logic
- Implement compatibility checking between toppings (e.g., no ice cream on hot pizzas)
- Add quantity limits based on pizza size
- Provide detailed error messages for rejected combinations
- Support custom validation rules for special dietary restrictions

### Key Design Decisions (MVP Approach)
- Simple hardcoded rules in Python (no complex rule engine)
- Validation runs synchronously before order submission
- Failed validations return specific error codes for UI handling
- ...

### Technical Considerations
- Must display validation errors in the UI
- No caching or optimization in v1
- Simple dict-based rule storage
- ...

## Test Strategy
Comprehensive testing will ensure the validator handles all edge cases:

- Unit tests for each validation rule type
- Test known incompatible combinations (documented in test data)
- Test boundary conditions for topping quantities
- Integration tests with the ordering system
- Performance tests with complex multi-topping pizzas
```

> Note: This is just and example output, you should generate the task file based on the template and YOUR knowledge about the task at hand.

## 📁 Output: Where to Save Your Generated Task File

**IMPORTANT**: After generating the task overview, save it to:

`.taskmaster/tasks/task_{{task_id}}/task_{{task_id}}.md`

**Example**: For Task 24, save to:
`.taskmaster/tasks/task_24/task-24.md`

## 🚀 MVP Context - IMPORTANT

**We are building an MVP with ZERO users**. This means:

- **NO backwards compatibility concerns** - We can change anything
- **NO migration code needed** - There's nothing to migrate from
- **No over-engineering** - Build only what's needed for the current requirements
- **Breaking changes are fine** - We can refactor freely as long as we just break functionality that was intended to be broken

When writing task details, always favor:
- Simple, direct solutions over complex abstractions
- Minimal code that solves the immediate problem
- Clear, obvious implementations over clever ones

> With the above in mind, you should always describe the task that you and the user has agreed on, do not change the task in any way unless the user explicitly asks you to. If you feel like you need to change the task, 🛑 STOP and ask the user for input before continuing.

## 🔑 Key Principles to Remember

1. **Context Window First**: Your existing knowledge from the conversation is your PRIMARY source
2. **Never Read Without Permission**: DO NOT read files unless --read_spec=true
3. **Be Honest About Uncertainty**: Note when you're making reasonable assumptions
4. **Consistency Matters**: Follow the template structure exactly
5. **Focus on Clarity**: Write for someone who hasn't been part of your conversation
6. **MVP Mindset**: Always describe the simplest solution that meets requirements

Remember: This task overview file will guide the implementation, so make it clear, accurate, and comprehensive based on what you know.
