# Example: Before and After Improvement

## BEFORE (Current Format):

### 6. Add Task (`add_task`)

*   **CLI Command:** `task-master add-task [options]`
*   **Description:** `Add a new task to Taskmaster by describing it; AI will structure it.`
*   **Key CLI Options:**
    *   `prompt`: `Required. Describe the new task you want Taskmaster to create, e.g., "Implement user authentication using JWT".` (CLI: `-p, --prompt <text>`)
    *   `dependencies`: `Specify the IDs of any Taskmaster tasks that must be completed before this new one can start, e.g., '12,14'.` (CLI: `-d, --dependencies <ids>`)
    *   `priority`: `Set the priority for the new task: 'high', 'medium', or 'low'. Default is 'medium'.` (CLI: `--priority <priority>`)
    *   `research`: `Enable Taskmaster to use the research role for potentially more informed task creation.` (CLI: `-r, --research`)
    *   `file`: `Path to your Taskmaster 'tasks.json' file. Default relies on auto-detection.` (CLI: `-f, --file <file>`)
*   **Usage:** Quickly add newly identified tasks during development.
*   **Important:** This command makes AI calls and can take up to a minute to complete. Please inform users to hang tight while the operation is in progress.

---

## AFTER (Improved Format):

### 6. Add Task (`add-task`)

**Command:** `task-master add-task [options]`

**Description:** Add a new task by describing it; AI will structure it appropriately.

**Options:**
- `-p, --prompt <text>` (required) - Describe the new task to create
- `-d, --dependencies <ids>` - Comma-separated IDs of prerequisite tasks (e.g., `12,14`)
- `--priority <priority>` - Set priority: `high`, `medium`, or `low` (default: `medium`)
- `-r, --research` - Enable research mode for more informed task creation
- `-f, --file <file>` - Path to tasks.json file (see Common Options)

**Example:**
```bash
task-master add-task -p "Implement JWT authentication with refresh tokens" -d 3,5 --priority high
```

**Notes:** Quickly add newly identified tasks during development. This is an AI-powered command.

---

## Key Improvements Demonstrated:

1. ✅ Changed header from `add_task` to `add-task` (matches CLI)
2. ✅ Removed backticks from description
3. ✅ Simplified option descriptions (removed redundant "Taskmaster" mentions)
4. ✅ Cleaner option format without inline CLI syntax duplication
5. ✅ Added practical example
6. ✅ Moved "AI-powered" note to a simpler mention in Notes
7. ✅ Referenced "Common Options" for shared parameters
8. ✅ Used consistent structure (Command, Description, Options, Example, Notes)
