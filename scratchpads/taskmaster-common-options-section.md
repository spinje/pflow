# Suggested Common Options Section

Add this after the "Taskmaster Tool & Command Reference" introduction:

---

## Common Options

These options are available for most task-master commands:

- `-f, --file <file>` - Path to your `tasks.json` file. If not specified, task-master will auto-detect it by searching up the directory tree for `.taskmaster/tasks/tasks.json`.

- `-h, --help` - Show help for any command

## AI-Powered Commands

The following commands use AI and may take up to a minute to complete:
- `parse-prd` - Parse requirements documents
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

This approach:
1. Eliminates repetition of the file parameter description in every command
2. Groups all AI-related warnings in one place
3. Makes it clear which commands require API keys
4. Provides helpful tips for AI-powered commands
