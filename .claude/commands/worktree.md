---
description: This command is for human / machine invocation only. Do not use unless explicitly asked by the user.
argument-hint: [task number, issue number, or description]
---
Create an isolated git worktree for parallel pflow work, using `./scripts/worktree`.

!`git branch --show-current`

Build and run the command:
```bash
./scripts/worktree new <branch-name> [base-ref] [--copy <path>]... [--no-open] [--claude|--codex "<task context>"] [--model <name>]
```

**Parameter rules:**
- If `$ARGUMENTS` is empty, ask the user what the worktree is for.
- **Derive `<branch-name>` yourself** — no tool generates it. Always type-prefixed:
  `<type>/task-<N>-<short-kebab-slug>` for taskmaster tasks (resolve the title first with
  `./scripts/tasks <N>`, e.g. `feat/task-94-model-list`); `<type>/issue-<N>-<slug>` for GitHub
  issues (`gh issue view <N>` for the title — an issue number is never a task id);
  `<type>/<kebab-slug>` for ad-hoc work. Type ∈ feat/fix/docs/refactor/perf/test/chore. Slug =
  2–4 words, no articles.
- The script defaults the base to `main` only while the **main checkout** is on `main` (the
  branch shown above is the invoker's; they differ only when run from inside a worktree) —
  otherwise it refuses, so pass `main` explicitly as `[base-ref]` unless the user explicitly
  wants to branch from the current branch. A local `main` behind `origin/main` gets a warning:
  offer to `git pull` first.
- If the user mentions files/folders to carry over (scratchpads, briefs, research notes), add
  `--copy <path>` per item (repeatable; paths relative to repo root, location preserved). This
  matters for gitignored files — a fresh worktree only contains tracked files.
- Cursor opens at the new worktree by default — add `--no-open` only if the user says not to.
  Add `--claude "<context>"` (or `--codex "<context>"` if they ask for Codex) only if they want
  a coding agent launched in the new worktree's Terminal. Context is either the user's own
  description (`"Task 94: display available LLM models"`), or an explicit slash command passed
  through verbatim (`"/start-orchestration 94"`).
- `--model <name>` only alongside `--claude`/`--codex`. **The live tiers are `opus` and `fable`
  only — the Sonnet tier is retired (DECISIONS #24) and the script refuses it.** Claude aliases
  pass through; for Codex, `opus`/`fable` map to `gpt-6-astra`.
- The script refuses to clobber an existing worktree dir — relay that error as-is; a collision
  with a *different* task means the name was too vague. Don't work around refusals.
- Related subcommands when the user asks: `./scripts/worktree rm <branch> [-f]` tears down a
  worktree whose PR has merged (squash-safe check built in; `-f` skips it and keeps the branch);
  `list` shows worktrees with their merge state.

**Examples:**

```bash
# "set up a worktree for task 94"
./scripts/worktree new feat/task-94-model-list

# "worktree for issue 620 and have claude work on it"
./scripts/worktree new fix/issue-620-template-escape --claude 'Issue #620: the $${…} template escape is documented but broken'

# "fix the stale-server bug in a worktree" (run from a feature branch → base explicit)
./scripts/worktree new fix/stale-ui-server main

# "task 94 worktree, bring my scratchpad, don't open cursor, codex on fable"
./scripts/worktree new feat/task-94-model-list --copy scratchpads/task-94 --no-open --codex "Task 94: display available LLM models" --model fable
```

Report the summary block (path, branch, base, what was launched, teardown hint) back to the
user. Only claim Cursor or the agent opened when the script said so.

**Parallel-branch discipline — remind the session working in the new worktree:** run the
collision analysis before any parallel launch (ORCHESTRATION.md), never mutate shared tooling
mid-flight, and **the second branch to merge re-runs its code-mode review on the rebased/merged
diff** — the first merge changed the ground under it.

Teardown is not this command's job: after merge, the main orchestrator runs
`./scripts/worktree rm <branch>` (ORCHESTRATION.md "Worktree & git flow" step 6).
