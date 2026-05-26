Refine and format these changelog entries as a markdown section
for CHANGELOG.md.

## Input
Version: ${compute-version.result.next_version}
Date: ${compute-version.result.date_iso}

## Draft Entries with Context
Each entry is a markdown section with the draft line, commit info,
PR details with full URL, files changed, and matched task reviews.
Use PR links exactly as shown.
${format-draft-entries.result.entries}

## Documentation Changes (for parameter accuracy)
${join-docs-summary.result}

## Refinement Tasks
1. Merge duplicates → combine PR links
2. Standardize verbs: Allow→Added, Enable→Added, Update→Changed/Improved
3. Sort by: Removed > Changed > Added > Fixed > Improved
4. Use docs diff for accurate parameter names
5. Use task reviews for accurate feature descriptions

## Output Format
## v1.0.0 (2026-01-04)

- Removed X [#10](https://github.com/owner/repo/pull/10) ([Task 42](.taskmaster/tasks/task_42/task-review.md))
- Changed Y [#11](https://github.com/owner/repo/pull/11)
- Added Z [#12](https://github.com/owner/repo/pull/12), [#13](https://github.com/owner/repo/pull/13)
- Added W ([Task 104](.taskmaster/tasks/task_104/task-review.md))
- Fixed V
- Improved U [#14](https://github.com/owner/repo/pull/14)

## Rules
- This is a user-facing changelog — describe what changed for users,
  not how it was implemented. Skip internal details unless they
  directly affect usage.
- Be specific — name the actual thing that changed, not a vague
  summary. Never invent details. If an entry is too vague to
  understand what actually changed, drop it.
- Use version and date exactly as provided
- Each entry as bullet with `- `
- CRITICAL: Use the FULL pr_link URL from context, not just the PR number
- Format: [#N](full_url) where full_url is from context.pr_link
- If entry has a task link (e.g. Task: [N](...)), include it after PR links
- If entry has a task WITHOUT a link (e.g. Task: N), do NOT add a task link
- Entries may have: PR + Task link, PR only, Task link only, or neither — all are valid
- Combine PR links when merging duplicates
- Start with ## - no code fences
- Output ONLY the markdown section
