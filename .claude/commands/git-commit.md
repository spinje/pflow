# Git Commit Slash Command

## Usage
`/git-commit [message]`

## Description
This command helps you create well-structured git commits with descriptive messages and submit them to the repository.

## Workflow

### 1. Analyze Changes and Propose a Plan
Your first step is to get a clear picture of the repository's state.
- **Check Status:** Run `git status` to see all staged and unstaged files.
- **Optionally review each file:** Use `git diff` to understand what changed in each file. This step is *only necessary* if you're not sure what the changes are — i.e., they weren't added by you in the current session.
- **Group Changes:** Analyze the changes and identify single, logical units of work. **IMPORTANT**: Unrelated changes should ALWAYS be in separate commits, even if they're in the same file.
- **Identify unrelated changes:** Look for changes that serve different purposes (e.g., documentation updates vs. code refactoring vs. new features).
- **Analyze order of changes:** Analyze what the most logical order of commiting the changes is.
- **Plan for Multiple Commits:** If you identify multiple logical changes, you must **propose a plan to the users chat window** for how you will split the work into a series of separate commits. Wait for approval before proceeding.

### 2. Prepare the Staging Area for the Commit

For each logical commit (either the only one, or the current step in your approved plan), precisely prepare the staging area.
- **Test Pre-commit Hooks First:** Run `.venv/bin/python -m pre_commit run --all-files` on the files you plan to commit. This often makes automatic changes (formatting, trailing whitespace, etc.), so run it BEFORE staging to avoid having to re-stage files.
  ```bash
  # Run on specific files you plan to commit
  .venv/bin/python -m pre_commit run --files file1.py file2.md
  # Or run on all modified files if committing everything
  .venv/bin/python -m pre_commit run --all-files
  ```
- **Stage Necessary Files:** Use `git add <file>` for any changes that belong in this specific commit (including any fixes made by pre-commit hooks).
- **Unstage Unrelated Files:** If files are staged that do *not* belong in this logical commit, unstage them.

```bash
# Unstage a specific file
git reset path/to/unrelated_file.txt

# Or unstage all currently staged files to start fresh
git reset
```

### 3. Write a Descriptive Commit Message

- See detailed instructions below.

### 4. Submit the Commit

- Create the commit with your descriptive message.
- If pre-commit hooks fail during the commit:
  - Check if the hooks made any automatic fixes
  - If fixes were made, you'll need to stage them with `git add` and commit again
  - If hooks fail without fixes, address the issues before committing
- Never use --no-verify flag to bypass pre-commit hooks unless explicitly asked by the user.

### 5. Repeat if Necessary
If you are executing a multi-commit plan, return to Step 2 and proceed with the next logical commit until all changes are committed.

## Instructions

### Write a Descriptive Commit Message
A good commit message should:
- Use the imperative mood ("Add feature" not "Added feature")
- Start with a verb (add, fix, update, remove, refactor, etc.)
- Be concise but descriptive (50 characters or less for the first line)
- Explain what the change does, not how it does it
- Use present tense

#### Examples of Good Commit Messages:
- `Add user authentication system`
- `Fix dropdown menu positioning issue`
- `Update API endpoint for user profiles`
- `Remove deprecated helper methods`
- `Refactor database connection logic`

#### Examples of Bad Commit Messages:
- `stuff`
- `fixed it`
- `changes`
- `updates and fixes`

### Command Behavior
- If no message is provided, you'll be prompted to write one
- The command will show you what files are being committed
- It will verify the commit was successful
- It can optionally push the changes to the remote repository

### Best Practices
- Commit often with small, focused changes.
- Each commit should represent a single logical change.
- Test your changes before committing.
- Use meaningful commit messages that help other developers understand the change.
- Keep commits atomic – if you need to revert, you can revert the entire feature/fix.
- Handle multiple logical changes: If multiple files are staged or unstaged, your job (CLAUDE) is to analyze the changes, split them into logical pieces that fit together, and propose committing them separately. This ensures the repository history remains clean, organized, and easy to follow.

### Handling multiple logical changes
- If there are multiple logical changes, you should split them into multiple commits.
- Propose a plan of how you will split the changes into multiple commits to the user before doing it (in the chat window)

### Common Examples of Unrelated Changes to Separate
- **Documentation updates** (README, CLAUDE.md, command docs) should be separate from code changes
- **Configuration changes** (package.json, pyproject.toml, settings) should be separate from feature implementation
- **Refactoring** should be separate from bug fixes or new features
- **Test additions** can be with the feature they test, but test refactoring should be separate
- **Different features or fixes** even if they touch the same files, should be in separate commits
- **Auto-formatting changes** should ideally be in their own commit if they affect many files

### Red Flags That Indicate Multiple Commits Are Needed
- Files from completely different parts of the codebase are changed
- The commit message would need "and" to describe all changes
- Some changes are not mentioned in the commit message because they're unrelated
- Different types of changes (docs vs code vs config)
- Changes that could be reverted independently
