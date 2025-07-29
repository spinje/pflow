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

**Your output**: Generate the task overview and save it to `.taskmaster/tasks/task_{{task_id}}/task_{{task_id}}.md`

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
<!-- Format as bullet points: "- Task 18: Template Variable System" -->
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

## Example Output

Here's what your generated task file should look like:

```markdown
# Task 24: Implement Workflow Manager

## ID
24

## Title
Implement Workflow Manager

## Description
Create a centralized service that owns the workflow lifecycle, including save, load, and resolve operations. This will provide a clean API for managing workflows and enable future features like workflow versioning and sharing.

## Status
not started

## Dependencies
- Task 21: Implement Workflow Input Declaration
- Task 20: Implement Nested Workflow Execution

## Priority
high

## Details
The Workflow Manager will be a core service in pflow that centralizes all workflow-related operations. Currently, workflow handling is scattered across different components. This task will:

- Create a `WorkflowManager` class that handles workflow persistence
- Implement save/load operations for workflow JSON files
- Add workflow resolution logic to find workflows by name or path
- Provide a clean API that other components can use
- Set up proper error handling for missing or invalid workflows

Key design decisions:
- Workflows stored as JSON files in a configurable directory
- Simple file-based storage for MVP (no database)
- Workflow names must be unique within their namespace

## Test Strategy
Comprehensive testing will ensure the Workflow Manager is reliable:

- Unit tests for all public methods of WorkflowManager
- Test save/load round-trips with various workflow types
- Test error cases (missing files, invalid JSON, duplicate names)
- Integration tests with the compiler and runtime
- Performance tests for workflow resolution with many workflows
```

## 📁 Output: Where to Save Your Generated Task File

**IMPORTANT**: After generating the task overview, save it to:

`.taskmaster/tasks/task_{{task_id}}/task_{{task_id}}.md`

**Example**: For Task 24, save to:
`.taskmaster/tasks/task_24/task_24.md`

## 🔑 Key Principles to Remember

1. **Context Window First**: Your existing knowledge from the conversation is your PRIMARY source
2. **Never Read Without Permission**: DO NOT read files unless --read_spec=true
3. **Be Honest About Uncertainty**: Note when you're making reasonable assumptions
4. **Consistency Matters**: Follow the template structure exactly
5. **Focus on Clarity**: Write for someone who hasn't been part of your conversation

Remember: This task overview file will guide the implementation, so make it clear, accurate, and comprehensive based on what you know.
