# Git Worktree Task Creator

Automatically creates git worktrees for development tasks by analyzing
task descriptions with LLM to determine branch types, names, and
worktree paths. Checks repository state, generates appropriate branch
names following conventional patterns (feat/fix/docs/refactor/test),
creates worktrees with cleanup of existing ones, and outputs ready-to-use
development environment commands for Cursor and Claude Code editors.

## Inputs

### task_description

Development task description to create a git worktree for.

- type: string
- required: true

### open_cursor

Whether to open Cursor in the new worktree.

- type: boolean
- required: false
- default: true

### open_claude

Whether to open Claude Code in the new worktree.

- type: boolean
- required: false
- default: true

## Steps

### git_status

Check git repository status to understand current state.

- type: shell

```shell command
git status --short
```

### git_current_branch

Get current git branch name for reference.

- type: shell

```shell command
git branch --show-current
```

### get_directory

Get current directory name for worktree path generation.

- type: shell

```shell command
basename $(pwd)
```

### analyze_task

Analyze task description to determine branch type, name and worktree paths.

- type: llm
- model: gemini-2.5-flash-lite
- temperature: 0.3

````prompt
Analyze the task description and current directory to generate git worktree information.

Task: ${task_description}
Current Directory: ${get_directory.stdout}

Based on the task, determine:
1. Branch type using these rules:
   - If task contains 'implement', 'add', 'create', 'build' → use 'feat'
   - If task contains 'fix', 'bug', 'repair', 'resolve' → use 'fix'
   - If task contains 'document', 'docs', 'readme' → use 'docs'
   - If task contains 'refactor', 'restructure', 'reorganize' → use 'refactor'
   - If task contains 'test', 'testing', 'spec' → use 'test'
   - Default to 'feat' if unclear

2. Branch name (kebab-case, 2-4 words, remove articles):
   - Extract key words from task
   - Convert to lowercase with hyphens
   - Remove 'a', 'an', 'the', 'node' and common words

3. Generate paths and names:
   - Worktree directory: ../[current-dir]-[branch-type]-[branch-name]
   - Full branch name: [branch-type]/[branch-name]

Respond ONLY with this exact format:
BRANCH_TYPE=[branch-type]
BRANCH_NAME=[branch-name]
WORKTREE_PATH=../[current-dir]-[branch-type]-[branch-name]
FULL_BRANCH=[branch-type]/[branch-name]
````

### remove_existing_worktree

Remove any existing worktree at the target location.

- type: shell
- ignore_errors: true

```shell command
WORKTREE_PATH=$(echo '${analyze_task.response}' | grep '^WORKTREE_PATH=' | cut -d'=' -f2) && git worktree remove "$WORKTREE_PATH" 2>/dev/null || true
```

### create_worktree

Create new git worktree with the generated branch.

- type: shell

```shell command
WORKTREE_PATH=$(echo '${analyze_task.response}' | grep '^WORKTREE_PATH=' | cut -d'=' -f2) && FULL_BRANCH=$(echo '${analyze_task.response}' | grep '^FULL_BRANCH=' | cut -d'=' -f2) && git worktree add "$WORKTREE_PATH" -B "$FULL_BRANCH"
```

### output_status

Output worktree creation status.

- type: shell

```shell command
WORKTREE_PATH=$(echo '${analyze_task.response}' | grep '^WORKTREE_PATH=' | cut -d'=' -f2) && echo "Worktree created at $WORKTREE_PATH"
```

### launch_cursor

Launch Cursor in the new worktree directory if requested.

- type: shell
- ignore_errors: true

```shell command
OPEN_CURSOR='${open_cursor}' && echo "DEBUG: open_cursor value is: '$OPEN_CURSOR'" && WORKTREE_PATH=$(echo '${analyze_task.response}' | grep '^WORKTREE_PATH=' | cut -d'=' -f2) && if [ "$OPEN_CURSOR" != 'false' ] && [ "$OPEN_CURSOR" != 'False' ] && [ "$OPEN_CURSOR" != '0' ]; then cursor "$WORKTREE_PATH" && echo 'Cursor launched'; else echo 'Skipping Cursor'; fi
```

### launch_claude

Launch Claude Code in the new worktree with task context if requested.

- type: shell
- ignore_errors: true

```shell command
OPEN_CLAUDE='${open_claude}' && echo "DEBUG: open_claude value is: '$OPEN_CLAUDE'" && WORKTREE_PATH=$(echo '${analyze_task.response}' | grep '^WORKTREE_PATH=' | cut -d'=' -f2) && FULL_BRANCH=$(echo '${analyze_task.response}' | grep '^FULL_BRANCH=' | cut -d'=' -f2) && FULL_WORKTREE_PATH=$(cd "$WORKTREE_PATH" && pwd) && if [ "$OPEN_CLAUDE" != 'false' ] && [ "$OPEN_CLAUDE" != 'False' ] && [ "$OPEN_CLAUDE" != '0' ]; then osascript <<EOF
tell application "Terminal"
    activate
    do script "cd $FULL_WORKTREE_PATH && claude --dangerously-skip-permissions 'You have been assigned to work in a dedicated git worktree for this task. Current worktree: $FULL_WORKTREE_PATH, Branch: $FULL_BRANCH, Original request: ${task_description}. You are now in an isolated git worktree specifically created for this task. All changes you make here are completely separate from the main branch. Please wait for the user to provide specific instructions on how to proceed with: ${task_description}. Do not do anything until the user has provided specific instructions. STOP and WAIT after this message.'"
end tell
EOF
echo 'Claude launched in Terminal'; else echo 'Skipping Claude'; fi
```

## Outputs

### status

Status of worktree creation.

- source: ${output_status.stdout}

### worktree_creation_status

Status output from creating the git worktree.

- source: ${create_worktree.stdout}

### branch_analysis

Analyzed branch information including type, name, and paths.

- source: ${analyze_task.response}
