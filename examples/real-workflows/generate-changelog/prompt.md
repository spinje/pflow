Generate a changelog from git history since a tag. Outputs CHANGELOG.md, Mintlify format, and a context file for verification.

## Requirements
- Git repo with at least one tag
- GitHub CLI (`gh`) authenticated

## Core Logic

**Streamlined LLM approach:**
1. Classification pass: Classify each commit in parallel (user-facing or internal?)
2. Formatting pass: Mintlify formatter sees all entries, dedupes, groups themes, polishes (markdown is shell-only, no LLM)

**Classification signals:**
- File paths matter: `.taskmaster/`, `tests/`, `docs/`, `.github/` = probably internal
- PR merge commits have richer context than direct commits
- When unclear, default to internal (can verify later)

## Workflow

1. `git log --first-parent` since tag (avoids duplicates from PR branches)
2. Enrich with GitHub PR metadata (title, body, link)
3. Extract file paths per commit
4. Load task-review.md files for referenced tasks (full file, not summary)
5. Get docs diff since tag (for accurate parameter descriptions)
6. **Parallel:** Classify each commit - user-facing or internal?
7. Compute semantic version (breaking=major, features=minor, fixes=patch)
8. Format CHANGELOG.md (shell - simple bullets, no LLM)
9. Format changelog.mdx (LLM - dedupe, group themes, polish, uses docs diff)
10. Save context file with: skipped changes, task reviews, docs diff, draft entries + PR context
11. Output summary with counts

## Outputs

| File | Purpose | Content |
|------|---------|---------|
| CHANGELOG.md | Developers | Technical, with PR links |
| changelog.mdx | Users | Mintlify format, grouped themes, no links |
| releases/v1.0.0-context.md | Verification | Everything the LLM saw + skipped items |

The context file lets you verify nothing was misclassified before committing.
