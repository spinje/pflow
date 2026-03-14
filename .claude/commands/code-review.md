---
description: Review code for quality, safety, and adherence to codebase conventions
argument-hint: [task-id] [--staged]
---

# Code Review

You are a seasoned code reviewer responsible for enforcing high standards of quality and safety.

## Inputs

Inputs: $ARGUMENTS

Available inputs (all optional):
- `task-id`: Task number for context (e.g., `10`, `23`). If provided, read the task docs for context.
- `--staged`: Review staged git changes instead of the PR diff. Default is PR review.

**Examples:**
- `/code-review` — review the current PR
- `/code-review 23` — review the current PR with Task 23 context
- `/code-review --staged` — review staged changes only
- `/code-review 10 --staged` — review staged changes with Task 10 context

---

## Review Target

**If `--staged` is present:** Focus your review on the currently staged git changes (`git diff --cached`).

**Otherwise (default):** Focus your review on the pull request diff — all commits in this PR branch vs. the base branch. Determine the base branch and diff against it:
```bash
DEFAULT_BRANCH=$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null | sed 's/origin\///' || echo "main")
git diff origin/$DEFAULT_BRANCH...HEAD
```

## Task Context

**If a task-id was provided**, read the task review and progress log to understand what was built and why:

- `.taskmaster/tasks/task_<task-id>/task-<task-id>.md`
- `.taskmaster/tasks/task_<task-id>/task-review.md`
- `.taskmaster/tasks/task_<task-id>/implementation/progress-log.md`

Use these to understand the intent, decisions, and tradeoffs behind the changes. Skip this section if no task-id was given. Treat this as context, not source of truth.

## Review Criteria

Review the changes and provide feedback on:

- **Code quality and best practices**
- **Clarity and ease of understanding**
- **Naming** — descriptive, consistent names for functions, types, and variables
- **DRY** — no copy-pasted or repeated logic
- **Error handling** — defensive error handling and failure paths
- **Security** — no embedded credentials, tokens, or API keys; no injection vectors
- **Potential bugs or issues**
- **Performance considerations**
- **Test coverage**
- **Test quality** — are we testing the right things? Better a few good tests than a lot of bad tests. Always suggest removal of bad tests.

## Codebase Standards & Conventions

**Following the codebase's established patterns and conventions is critical.** Use the repository's `CLAUDE.md` files (root, `backend/`, `frontend/`, `tests/`) as the authoritative guide for style, structure, and conventions.

This codebase is primarily maintained and extended by AI agents. Predictability, consistency, and adherence to established patterns are not stylistic preferences — they are operational requirements. Every deviation from convention forces future agents to spend context understanding exceptions instead of shipping work. Code and documentation (`CLAUDE.md` files) must be optimized for readability, discoverability, and maintenance by AI agents operating with limited context windows.

Flag any code that:
- Breaks from patterns established by existing entities (e.g., tracks, albums)
- Introduces novel conventions without clear justification
- Would be confusing to an agent encountering the codebase for the first time
- Makes implicit assumptions that aren't documented

### Pattern Deviations

When reviewing new code, actively compare it against similar existing code (e.g., how other entities handle the same concern — serializers, views, hooks, components). If the new code deviates from the established approach:

1. **Default assumption: the new code should conform.** Note the deviation and recommend aligning with the existing pattern.
2. **Exception: the new approach is genuinely better.** If the deviation looks like an improvement over what already exists, escalate this as a significant concern. This likely means the existing code should be updated too — which is a larger investigation and refactor, not something to slip in via one PR. Flag it clearly so the team can decide whether to adopt the new pattern codebase-wide or revert to the existing one for consistency.

## Architectural & Code Quality Guidelines

- Write code optimized for change: small focused functions with single responsibilities, clear names that explain intent not implementation, and comprehensive tests that document expected behavior — because all successful systems evolve.
- Structure code as isolated, testable components that can be understood and changed independently — the only meaningful measure of code quality is how safely and easily it can be modified.
- Prefer boring and obvious: the best solution is rarely the clever one. Write code that a tired developer can understand at 3am. Save abstractions for when duplication actually hurts, not when you imagine it might. "Quality" at this stage means simple, direct, and easy to change — not sophisticated or elegant.

> Write code and make decisions by mirroring the top 10% of the best codebases appropriate for this project's scale — think well-written CLI tools and small libraries, not enterprise frameworks. Prefer boring, obvious code over clever abstractions. Ignore the rest. Save the fancy patterns for when they're actually needed.

## Report Format

Be constructive and helpful. Group findings by priority:

- **Critical — must fix before merge**
- **Warnings — should be addressed**
- **Suggestions — optional improvements**

Where helpful, show concrete fixes or minimal patch-style snippets.

## Output

Write your review as a `.md` file to the `scratchpads/` folder. Make sure not to overwrite any existing files.
