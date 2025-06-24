# Task Master Development Workflow

This guide outlines the typical process for using Task Master to manage software development projects using the **`task-master` CLI** with the global `task-master` command by providing a user-friendly interface for direct terminal interaction.

The `task-master` CLI is a powerful tool that allows you to manage your tasks and subtasks in a structured way. It is designed to allow for efficient and precise control over updating the `tasks.json` file that holds the task hierarchy and all information about the project's tasks.

## Standard Development Workflow Process

Prefer to use the `task-master` CLI over editing the `tasks.json` file directly. Using the CLI is more efficient and precise and avoids spending unnecessary tokens. It also allows for more precise control over what context you are retrieving, allowing you to avoid context overload. When using sub agents, an effective way is to instruct the sub agent exactly what `task-master` commands to use. For example, if you are using a sub agent to cross-reference a number of tasks, you can instruct the sub agent to use the `task-master show 1,3,5` command to let the sub agent only retrieve the details of the tasks with ids 1, 3, and 5. This makes the sub agent more efficient and precise.

You can also invoke `task-master` commands using parallel tool calling. For maximum efficiency, whenever you need to perform umltiple indedendent operations, invoke all relevant `task-master` commands simultaneously rather than sequentially. This speeds things up immensely when needing to run bulk operations on the tasks.json file.

-   Begin coding sessions with `task-master list` or `task-master next` to determine the next task to work on if not explicitly specified by the user
-   Analyze task complexity with `task-master analyze-complexity --research` before breaking down tasks
-   Review complexity report using `task-master complexity-report`
-   Select tasks based on dependencies (all marked 'done'), priority level, and ID order
-   Clarify tasks by checking task files in tasks/ directory or asking for user input
-   View specific task details using `task-master show <id>` to understand implementation requirements
-   Break down complex tasks using `task-master expand --id=<id> --force --research` with appropriate flags like `--force` (to replace existing subtasks) and `--research`.
-   Clear existing subtasks if needed using `task-master clear-subtasks --id=<id>` before regenerating
-   Implement code following task details, dependencies, and project standards
-   Verify tasks according to test strategies before marking as complete
-   Mark completed tasks with `task-master set-status --id=<id> --status=done`
-   Update dependent tasks when implementation differs from original plan using `task-master update --from=<id> --prompt="..."` or `task-master update-task --id=<id> --prompt="..."`
-   Add new tasks discovered during implementation using `task-master add-task --prompt="..." --research`
-   Add new subtasks as needed using `task-master add-subtask --parent=<id> --title="..."`
-   Append notes or details to subtasks using `task-master update-subtask --id=<subtaskId> --prompt='Add implementation notes here...\nMore details...'`
-   Generate task files with `task-master generate` after updating tasks.json
-   Maintain valid dependency structure with `task-master add-dependency`/`remove-dependency` commands, `task-master validate-dependencies`, and `task-master fix-dependencies` when needed
-   Respect dependency chains and task priorities when selecting work
-   Reorganize tasks as needed using `task-master move --from=<id> --to=<id>` to change task hierarchy or ordering

## Task Complexity Analysis

-   Run `task-master analyze-complexity --research` for comprehensive analysis
-   Review complexity report via `task-master complexity-report` for a formatted, readable version
-   Focus on tasks with highest complexity scores (8-10) for detailed breakdown
-   Use analysis results to determine appropriate subtask allocation
-   Note that reports are automatically used by the expand command

## Task Breakdown Process

-   Use `task-master expand --id=<id>`. It automatically uses the complexity report if found, otherwise generates default number of subtasks
-   Use `--num=<number>` to specify an explicit number of subtasks, overriding defaults or complexity report recommendations
-   Add `--research` flag to leverage Perplexity AI for research-backed expansion
-   Add `--force` flag to clear existing subtasks before generating new ones (default is to append)
-   Use `--prompt="<context>"` to provide additional context when needed
-   Review and adjust generated subtasks as necessary
-   Use `task-master expand --all` to expand multiple pending tasks at once, respecting flags like `--force` and `--research`
-   If subtasks need complete replacement (regardless of the `--force` flag on `expand`), clear them first with `task-master clear-subtasks --id=<id>`

## Implementation Drift Handling

-   When implementation differs significantly from planned approach
-   When future tasks need modification due to current implementation choices
-   When new dependencies or requirements emerge
-   Use `task-master update --from=<futureTaskId> --prompt='<explanation>\nUpdate context...' --research` to update multiple future tasks
-   Use `task-master update-task --id=<taskId> --prompt='<explanation>\nUpdate context...' --research` to update a single specific task

## Task Status Management

-   Use `pending` for tasks ready to be worked on
-   Use `done` for completed and verified tasks
-   Use `deferred` for postponed tasks
-   Add custom status values as needed for project-specific workflows

## Task Structure Fields

- **id**: Unique identifier for the task (Example: `1` for top level tasks, `1.1` for subtasks)
- **title**: Brief, descriptive title (Example: "Initialize Repo")
- **description**: Concise summary of what the task involves (Example: "Create a new repository, set up initial structure")
- **status**: Current state of the task (Example: `pending`, `done`, `deferred`)
- **dependencies**: IDs of prerequisite tasks (Example: `[1, 2.1]`)
    - Dependencies are displayed with status indicators (✅ for completed, ⏱️ for pending)
    - This helps quickly identify which prerequisite tasks are blocking work
- **priority**: Importance level (Example: `high`, `medium`, `low`)
- **details**: In-depth implementation instructions
- **testStrategy**: Verification approach (Example: "Deploy and call endpoint to confirm 'Hello World' response")
- **subtasks**: List of smaller, more specific tasks

## Determining the Next Task

- Run `task-master next` to show the next task to work on
- The command identifies tasks with all dependencies satisfied
- Tasks are prioritized by priority level, dependency count, and ID
- The command shows comprehensive task information including:
    - Basic task details and description
    - Implementation details
    - Subtasks (if they exist)
    - Contextual suggested actions
- Recommended before starting any new development work
- Respects your project's dependency structure
- Ensures tasks are completed in the appropriate sequence
- Provides ready-to-use commands for common task actions

## Viewing Specific Task Details

- Run `task-master show <id>` to view a specific task
- Use dot notation for subtasks: `task-master show 1.2` (shows subtask 2 of task 1)
- Displays comprehensive information similar to the next command, but for a specific task
- For parent tasks, shows all subtasks and their current status
- For subtasks, shows parent task information and relationship
- Provides contextual suggested actions appropriate for the specific task
- Useful for examining task details before implementation or checking status

## Managing Task Dependencies

- Use `task-master add-dependency --id=<id> --depends-on=<id>` to add a dependency
- Use `task-master remove-dependency --id=<id> --depends-on=<id>` to remove a dependency
- The system prevents circular dependencies and duplicate dependency entries
- Dependencies are checked for existence before being added or removed
- Task files are automatically regenerated after dependency changes
- Dependencies are visualized with status indicators in task listings and files

## Task Reorganization

- Use `task-master move --from=<id> --to=<id>` to move tasks or subtasks within the hierarchy
- This command supports several use cases:
  - Moving a standalone task to become a subtask (e.g., `--from=5 --to=7`)
  - Moving a subtask to become a standalone task (e.g., `--from=5.2 --to=7`)
  - Moving a subtask to a different parent (e.g., `--from=5.2 --to=7.3`)
  - Reordering subtasks within the same parent (e.g., `--from=5.2 --to=5.4`)
  - Moving a task to a new, non-existent ID position (e.g., `--from=5 --to=25`)
  - Moving multiple tasks at once using comma-separated IDs (e.g., `--from=10,11,12 --to=16,17,18`)
- The system includes validation to prevent data loss:
  - Allows moving to non-existent IDs by creating placeholder tasks
  - Prevents moving to existing task IDs that have content (to avoid overwriting)
  - Validates source tasks exist before attempting to move them
  - Maintains proper parent-child relationships and dependency integrity
- Task files are automatically regenerated after the move operation
- This provides greater flexibility in organizing and refining your task structure as project understanding evolves
- This is especially useful when dealing with potential merge conflicts arising from teams creating tasks on separate branches. Solve these conflicts very easily by moving your tasks and keeping theirs

## Iterative Subtask Implementation

Once a task has been broken down into subtasks using `task-master expand` or similar methods, follow this iterative process for implementation:

1. **Understand the Goal (Preparation):**
   - Use `task-master show <subtaskId>` to thoroughly understand the specific goals and requirements of the subtask

2. **Initial Exploration & Planning (Iteration 1):**
   - This is the first attempt at creating a concrete implementation plan
   - Explore the codebase to identify the precise files, functions, documentation and even specific lines of code that will need modification
   - Determine the intended code changes (diffs) and their locations
   - Gather *all* relevant details from this exploration phase. Evaluate all **potentially relevant** files in the `docs`, `src`, `pocketflow/docs`, `pocketflow/cookbook` directory and ultra think on the problem space and potential solutions
   - If you are not sure about the solution or if there are multiple potential solutions, always ask the user for input
   - Create the detailed plan in a new markdown file in the `.taskmaster/tasks/<taskId>/` file

3. **Log the Plan:**
   - Run `task-master update-subtask --id=<subtaskId> --prompt='<detailed plan>'`
   - Provide the *complete and detailed* findings from the exploration phase in the prompt. Include file paths, line numbers, proposed diffs, reasoning, and any potential challenges identified. Do not omit details. The goal is to create a rich, timestamped log within the subtask's `details`

4. **Verify the Plan:**
   - Run `task-master show <subtaskId>` again to confirm that the detailed implementation plan has been successfully appended to the subtask's details

5. **Begin Implementation:**
   - Set the subtask status using `task-master set-status --id=<subtaskId> --status=in-progress`
   - Start coding based on the logged plan

6. **Refine and Log Progress (Iteration 2+):**
   - As implementation progresses, you will encounter challenges, discover nuances, or confirm successful approaches
   - **Before appending new information**: Briefly review the *existing* details logged in the subtask to ensure the update adds fresh insights and avoids redundancy
   - **Regularly** use `task-master update-subtask --id=<subtaskId> --prompt='<update details>\n- What worked...\n- What didn't work...'` to append new findings
   - **Crucially, log:**
       - What worked ("fundamental truths" discovered)
       - What didn't work and why (to avoid repeating mistakes)
       - Specific code snippets or configurations that were successful
       - Decisions made, especially if confirmed with user input
       - Any deviations from the initial plan and the reasoning
   - The objective is to continuously enrich the subtask's details, creating a log of the implementation journey that helps the AI (and human developers) learn, adapt, and avoid repeating errors

7. **Review (Post-Implementation):**
   - Once the implementation for the subtask is functionally complete, review all code changes and the relevant chat history
   - Identify any new or modified code patterns, conventions, or best practices established during the implementation
   - Create a new subsection to the comprehensive report in the `.taskmaster/tasks/<taskId>/implementation-review.md` file that summarizes the implementation and carefully considers any implications for any other tasks that may be affected/dependent by the changes (You can see dependencies in the `dependencies` field of the task). This is the time to reflect on what you have learned, what initial assumptions you had that were incorrect and what key decisions you and the user made that could potentially impact other tasks and the project as a whole. Also consider if any existing documentation needs to be updated to reflect any key insights you have gained

8. **Mark Task Complete:**
   - After verifying the implementation and updating any necessary rules, mark the subtask as completed: `task-master set-status --id=<subtaskId> --status=done`

9. **Commit Changes (If using Git):**
   - Stage the relevant code changes and any updated/new rule files (`git add .`)
   - Craft a comprehensive Git commit message summarizing the work done for the subtask, including both code implementation and any rule adjustments
   - Execute the commit command directly in the terminal (e.g., `git commit -m 'feat(module): Implement feature X for subtask <subtaskId>\n\n- Details about changes...\n- Updated rule Y for pattern Z'`)
   - Consider if a Changeset is needed according to internal versioning guidelines. If so, run `npm run changeset`, stage the generated file, and amend the commit or create a new one

10. **Proceed to Next Subtask:**
    - Identify the next subtask using `task-master next`

## Code Analysis & Refactoring Techniques

- **Top-Level Function Search**:
    - Useful for understanding module structure or planning refactors
    - Use grep/ripgrep to find exported functions/constants:
      `rg "export (async function|function|const) \w+"` or similar patterns
    - Can help compare functions between files during migrations or identify potential naming conflicts

---

# Taskmaster Command Reference

**Important:** Several commands involve AI processing. This means the response time will be longer than commands that do not involve AI processing. It also means that the context that you send to the AI will be more important than ever since the task-master AI processing does not have access to the same context as the AI Agent calling it - you (Claude). When you are calling these AI-powered commands, you should always do the heavy lifting and send the most relevant context and detailed instructions to task-master, rather than rely on task-master to figure things out. Task-master is not a general purpose AI agent, it is a tool for managing tasks and subtasks for a software development project. This means that you should always be as specific as possible when calling these commands. Task-master does not know anything about the project other than what you send it in the prompt.

## Quick Command Reference

| Command | Description | Category | AI |
|---------|-------------|----------|-----|
| `list` | List all tasks | Viewing | ❌ |
| `next` | Show next task to work on | Viewing | ❌ |
| `show` | Show specific task details | Viewing | ❌ |
| `add-task` | Add new task | Creation | ✅ |
| `add-subtask` | Add or convert to subtask | Creation | ❌ |
| `update` | Update multiple future tasks | Modification | ✅ |
| `update-task` | Update specific task | Modification | ✅ |
| `update-subtask` | Append notes to subtask | Modification | ✅ |
| `set-status` | Change task status | Modification | ❌ |
| `remove-task` | Delete task | Modification | ❌ |
| `remove-subtask` | Delete or convert subtask | Modification | ❌ |
| `expand` | Break down into subtasks | Organization | ✅ |
| `clear-subtasks` | Remove all subtasks | Organization | ❌ |
| `move` | Reorganize task hierarchy | Organization | ❌ |
| `add-dependency` | Add task dependency | Dependencies | ❌ |
| `remove-dependency` | Remove task dependency | Dependencies | ❌ |
| `validate-dependencies` | Check for issues | Dependencies | ❌ |
| `fix-dependencies` | Auto-fix issues | Dependencies | ❌ |
| `analyze-complexity` | Analyze task complexity | Analysis | ✅ |
| `complexity-report` | View complexity report | Analysis | ❌ |
| `generate` | Generate task markdown files | Files | ❌ |

**Legend:** ✅ = AI-powered (requires API key), ❌ = Local operation

## Common Options

These options are available for most task-master commands:

- `-f, --file <file>` - Path to your `tasks.json` file. If not specified, task-master will auto-detect it by searching up the directory tree for `.taskmaster/tasks/tasks.json`
- `-h, --help` - Show help for any command

## AI-Powered Commands

The following commands use AI and may take up to a minute to complete:
- `add-task` - Create new tasks from descriptions
- `update` - Update multiple tasks with new context
- `update-task` - Update a specific task
- `update-subtask` - Append notes to subtasks
- `expand` - Break down tasks into subtasks
- `analyze-complexity` - Analyze task complexity

When using these commands:
- Ensure you have the appropriate API keys in your `.env` file
- Be as specific as possible in your prompts
- Consider using the `--research` flag for more informed results (requires Perplexity API key)

---

## Task Viewing

### 4. List Tasks (`list`)

**Command:** `task-master list [options]`

**Description:** List your tasks, optionally filtering by status and showing subtasks.

**Options:**
- `-s, --status <status>` - Show only tasks with this status (e.g., `pending`, `done`)
- `--with-subtasks` - Include subtasks indented under their parent tasks
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Example:**
```bash
task-master list --status pending --with-subtasks
```

### 5. Show Next Task (`next`)

**Command:** `task-master next [options]`

**Description:** Show the next available task based on status and completed dependencies.

**Options:**
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Notes:** This command identifies tasks with all dependencies satisfied, prioritized by priority level, dependency count, and ID. Shows comprehensive task information including subtasks and suggested actions.

### 6. Show Task Details (`show`)

**Command:** `task-master show [id] [options]`

**Description:** Display detailed information for a specific task or subtask by its ID.

**Options:**
- `[id]` or `-i, --id <id>` - Task ID (e.g., `15` or `15.2` for subtasks)
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Example:**
```bash
task-master show 15.2
```

---

## Task Creation & Modification

### 7. Add Task (`add-task`)

**Command:** `task-master add-task [options]`

**Description:** Add a new task by describing it; AI will structure it appropriately.

**Options:**
- `-p, --prompt <text>` (required) - Describe the new task to create
- `-d, --dependencies <ids>` - Comma-separated IDs of prerequisite tasks
- `--priority <priority>` - Set priority: `high`, `medium`, or `low` (default: `medium`)
- `-r, --research` - Enable research mode for more informed task creation
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Example:**
```bash
task-master add-task -p "Implement JWT authentication with refresh tokens" -d 3,5 --priority high
```

### 8. Add Subtask (`add-subtask`)

**Command:** `task-master add-subtask [options]`

**Description:** Add a new subtask to a parent task, or convert an existing task into a subtask.

**Options:**
- `-p, --parent <id>` (required) - ID of the parent task
- `-i, --task-id <id>` - Convert existing task to subtask
- `-t, --title <title>` - Title for new subtask (required if not using `--task-id`)
- `-d, --description <text>` - Brief description
- `--details <text>` - Implementation notes
- `--dependencies <ids>` - Prerequisite task/subtask IDs
- `-s, --status <status>` - Initial status (default: `pending`)
- `--skip-generate` - Don't regenerate markdown files

**Example:**
```bash
task-master add-subtask -p 5 -t "Set up database connection" -d "Configure PostgreSQL connection pool"
```

### 9. Update Multiple Tasks (`update`)

**Command:** `task-master update [options]`

**Description:** Update multiple upcoming tasks based on new context or changes.

**Options:**
- `--from <id>` (required) - Starting task ID (updates this and all higher IDs not marked `done`)
- `-p, --prompt <text>` (required) - Explain the change or new context
- `-r, --research` - Enable research mode
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Example:**
```bash
task-master update --from 18 --prompt "Switching to React Query instead of Redux.\nNeed to refactor all data fetching logic."
```

### 10. Update Task (`update-task`)

**Command:** `task-master update-task [options]`

**Description:** Modify a specific task or subtask by its ID.

**Options:**
- `-i, --id <id>` (required) - Task or subtask ID to update
- `-p, --prompt <text>` (required) - Explain the changes or new information
- `-r, --research` - Enable research mode
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Example:**
```bash
task-master update-task -i 15 -p "Use PostgreSQL instead of MySQL.\nUpdate schema to use JSONB for metadata."
```

### 11. Update Subtask (`update-subtask`)

**Command:** `task-master update-subtask [options]`

**Description:** Append timestamped notes to a subtask without overwriting existing content.

**Options:**
- `-i, --id <id>` (required) - Subtask ID
- `-p, --prompt <text>` (required) - Information to append
- `-r, --research` - Enable research mode
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Example:**
```bash
task-master update-subtask -i 15.2 -p "Discovered API requires X-Custom-Header.\nImplemented retry logic with exponential backoff."
```

**Notes:** Review existing details before appending to avoid redundancy. Use for iterative implementation logging.

### 12. Set Task Status (`set-status`)

**Command:** `task-master set-status [options]`

**Description:** Update the status of one or more tasks or subtasks.

**Options:**
- `-i, --id <id>` (required) - Task/subtask ID(s), comma-separated for multiple
- `-s, --status <status>` (required) - New status (e.g., `done`, `pending`, `in-progress`)
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Example:**
```bash
task-master set-status -i 15,15.1,15.2 -s done
```

### 13. Remove Task (`remove-task`)

**Command:** `task-master remove-task [options]`

**Description:** Permanently remove a task or subtask from the tasks list.

**Options:**
- `-i, --id <id>` (required) - Task or subtask ID to remove
- `-y, --yes` - Skip confirmation prompt
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Notes:** Use with caution - this cannot be undone. Consider using status like `cancelled` or `deferred` instead. Automatically cleans up dependency references.

---

## Task Organization

### 14. Expand Task (`expand`)

**Command:** `task-master expand [options]`

**Description:** Break down a complex task into smaller, manageable subtasks using AI.

**Options:**
- `-i, --id <id>` - Task ID to expand
- `--all` - Expand all eligible pending/in-progress tasks
- `-n, --num <number>` - Number of subtasks to create (overrides complexity analysis)
- `-r, --research` - Enable research mode
- `-p, --prompt <text>` - Additional context for expansion
- `--force` - Clear existing subtasks before generating (default: append)
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Example:**
```bash
task-master expand -i 5 -n 8 --research -p "Focus on test coverage and error handling"
```

**Notes:** Automatically uses complexity report recommendations if available and `--num` not specified.

### 15. Clear Subtasks (`clear-subtasks`)

**Command:** `task-master clear-subtasks [options]`

**Description:** Remove all subtasks from one or more parent tasks.

**Options:**
- `-i, --id <ids>` - Parent task ID(s), comma-separated
- `--all` - Clear subtasks from all parent tasks
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Example:**
```bash
task-master clear-subtasks -i 15,16,18
```

### 16. Remove Subtask (`remove-subtask`)

**Command:** `task-master remove-subtask [options]`

**Description:** Remove a subtask from its parent, optionally converting it to a standalone task.

**Options:**
- `-i, --id <id>` (required) - Subtask ID(s), comma-separated
- `-c, --convert` - Convert to top-level task instead of deleting
- `--skip-generate` - Don't regenerate markdown files
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Example:**
```bash
task-master remove-subtask -i 15.2 --convert
```

### 17. Move Task (`move`)

**Command:** `task-master move [options]`

**Description:** Move tasks or subtasks to new positions within the hierarchy.

**Options:**
- `--from <id>` (required) - Source task/subtask ID(s), comma-separated
- `--to <id>` (required) - Destination ID(s), must match number of source IDs
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Examples:**
```bash
# Move task 5 to become subtask 7.1
task-master move --from 5 --to 7.1

# Move multiple tasks
task-master move --from 10,11,12 --to 16,17,18

# Move subtask to different parent
task-master move --from 5.2 --to 7.3
```

**Notes:** Supports moving to non-existent IDs (creates placeholders), prevents overwriting existing tasks, maintains dependencies. Useful for resolving merge conflicts.

---

## Dependency Management

### 18. Add Dependency (`add-dependency`)

**Command:** `task-master add-dependency [options]`

**Description:** Make one task dependent on another.

**Options:**
- `-i, --id <id>` (required) - Task that will have the dependency
- `-d, --depends-on <id>` (required) - Task that must be completed first
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Example:**
```bash
task-master add-dependency -i 8 -d 5
```

### 19. Remove Dependency (`remove-dependency`)

**Command:** `task-master remove-dependency [options]`

**Description:** Remove a dependency relationship between tasks.

**Options:**
- `-i, --id <id>` (required) - Task to remove dependency from
- `-d, --depends-on <id>` (required) - Dependency to remove
- `-f, --file <file>` - Path to tasks.json (see Common Options)

### 20. Validate Dependencies (`validate-dependencies`)

**Command:** `task-master validate-dependencies [options]`

**Description:** Check for dependency issues like circular references or links to non-existent tasks.

**Options:**
- `-f, --file <file>` - Path to tasks.json (see Common Options)

### 21. Fix Dependencies (`fix-dependencies`)

**Command:** `task-master fix-dependencies [options]`

**Description:** Automatically fix dependency issues found by validation.

**Options:**
- `-f, --file <file>` - Path to tasks.json (see Common Options)

---

## Analysis & Reporting

### 22. Analyze Complexity (`analyze-complexity`)

**Command:** `task-master analyze-complexity [options]`

**Description:** Analyze tasks to determine complexity and suggest which need breakdown.

**Options:**
- `-o, --output <file>` - Save report to file (default: `.taskmaster/reports/task-complexity-report.json`)
- `-t, --threshold <number>` - Minimum complexity score (1-10) to recommend expansion
- `-r, --research` - Enable research mode for more accurate analysis
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Notes:** Used before task breakdown to identify which tasks need the most attention.

### 23. View Complexity Report (`complexity-report`)

**Command:** `task-master complexity-report [options]`

**Description:** Display the task complexity analysis report in readable format.

**Options:**
- `-f, --file <file>` - Path to complexity report (default: `.taskmaster/reports/task-complexity-report.json`)

---

## File Management

### 24. Generate Task Files (`generate`)

**Command:** `task-master generate [options]`

**Description:** Create or update individual Markdown files for each task based on tasks.json.

**Options:**
- `-o, --output <directory>` - Directory for task files (default: `tasks` directory)
- `-f, --file <file>` - Path to tasks.json (see Common Options)

**Notes:** Run after making changes to tasks.json to keep individual task files synchronized.

---

*This workflow provides a general guideline. Adapt it based on your specific project needs and user preferences.*
