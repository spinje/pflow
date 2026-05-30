You are finalizing this cycle's work by opening **pull requests** — do NOT merge
into ${base_branch} directly.

Per-issue results (each item has `branch`, `commits_made`, `verdict`, `summary`,
and `item.number` / `item.title` for the original issue):
${results}

You are on ${base_branch} in the main checkout. For each result:

**verdict "approve" and commits_made > 0:**
- `git push -u origin <branch>`
- `gh pr create --base ${base_branch} --head <branch> --title "<item.title>" --body "Automated implementation of #<item.number>.\n\n<summary>"`
- `gh issue edit <item.number> --remove-label agent-ready`
- record `<branch>` under `prs_opened`.

**verdict "request-changes" (or commits_made == 0):**
- `gh issue edit <item.number> --remove-label agent-ready --add-label agent-needs-human`
- (optional) `gh issue comment <item.number> --body "<review notes>"`
- record `#<item.number>` under `needs_human`.

**Removing the `agent-ready` label is REQUIRED for every issue you touch** —
it takes the issue out of the candidate pool so the next cycle does not
re-attempt it and collide on the now-existing branch. This label removal is what
lets the outer loop converge. Report `prs_opened` and `needs_human`.
