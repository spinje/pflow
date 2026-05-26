You are classifying one git change for pflow's user-facing changelog.

Audience: a pflow user deciding what changed for THEM in this release — not an engineer auditing the codebase. A later pass polishes wording and merges duplicates, so you do not need perfect prose. Be accurate about two things: the include/skip decision, and what actually changed.

## The test

Would a pflow user notice or care about this when USING pflow? User-facing surfaces: CLI commands/flags/output, workflow file format, node behavior, error and diagnostic messages, performance they would feel, new capabilities. If a user cannot observe it, it is internal.

## How to weigh the evidence, in priority order

1. The commit message and PR title/body are the PRIMARY signal — they state what the author changed. Read them first.
2. The conventional-commit prefix is a strong prior, not a verdict:
   - `feat:`, `fix:`, `perf:` → usually user-facing
   - `docs:`, `test:`, `chore:`, `ci:`, `build:`, `style:`, `refactor:` → usually internal
   Override the prior when the content disagrees — a `chore:` that fixes a user-visible bug is user-facing; a `feat:` that only adds tests is internal.
3. Files changed CORROBORATE scope — use them to catch mislabels, not as the primary gate. Large squash PRs touch many internal files (tests, task specs, skills, docs) alongside the real change. Do NOT skip a `feat:`/`fix:` just because internal files outnumber `src/` files — find the `src/` change that matches the message.

## Include vs skip

Include (user-facing): new CLI commands/flags, new workflow or node capabilities, bug fixes for behavior users could hit, breaking changes (always), noticeable performance gains, dependency bumps ONLY when they change what users get (a security fix or a newly available model).

Skip (internal): refactors with no observable effect, internal renames or module moves, test/CI/tooling, docs-only changes, planning/task files, routine dependency bumps. When genuinely unsure, treat as internal.

## Writing the entry (only when user-facing)

- Name the EXACT component and what changed: "Added a `--dry-run` flag to preview cost" — not "Improved the CLI".
- Use ONLY facts present in the input. Never invent motivations or benefits ("for better performance", "enabling future X") unless stated. Terse input → terse entry.
- If a PR link is present, end the entry with `[#N](link)` using the link verbatim.

## reason

State, in one sentence, the signal you used and why you decided include or skip. Be honest when the call is borderline — a human reads this to audit the cut.

## Examples (these teach the hard calls — apply the principles above)

Large PR, message announces a feature, file list dominated by internal paths:
  Commit: "feat: add --watch flag to re-run on file change (#82)"
  Files: .taskmaster/tasks/task_82/..., tests/test_cli/test_watch.py, docs/cli.mdx, src/pflow/cli/commands/run.py, ... (60+ files)
  → user_facing: true. The message announces a user feature and `src/` implements it; the internal files are the PR's tests/specs/docs, not a reason to skip.

Conventional prefix says chore, but the content is a user-visible fix:
  Commit: "chore: bump provider lib and fix timeout handling on slow APIs"
  → user_facing: true. Override the "chore" prior — the timeout fix is observable.

Conventional prefix says feat, but it only touches tests:
  Commit: "feat: add coverage for batch retry paths"
  Files: tests/test_runtime/test_batch.py
  → user_facing: false. Override the "feat" prior — no `src/` or behavior change.

Refactor in src/ with no observable behavior change:
  Commit: "refactor: split executor into smaller modules"
  Files: src/pflow/runtime/engine/executor.py
  → user_facing: false. Internal reorganization; nothing a user can observe.

Breaking change — a removal, rename, or changed default:
  Commit: "rename --output-key to --output; the old flag is removed (#88)"
  → user_facing: true. Removals/renames/changed-defaults are breaking and always belong in the changelog, even when the diff is small — users must adapt.

Terse message, nothing to embellish:
  Commit: "fix: handle empty response body in http node"
  → user_facing: true, entry "Fixed the http node erroring on an empty response body" — match the message's specificity, add nothing it does not say.

## The change

Is PR merge: ${item.is_merge}
Commit message: ${item.commit_message}
Files changed: ${item.files_changed}
PR Number: ${item.pr_number}
PR Title: ${item.pr_title}
PR Summary: ${item.pr_summary}
PR Link: ${item.pr_link}
