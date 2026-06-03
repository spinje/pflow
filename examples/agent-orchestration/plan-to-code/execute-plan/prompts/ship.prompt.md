You are finalizing a completed, reviewed, and verified implementation by opening a pull
request. The work is committed on the current branch. Do NOT merge into the base branch
directly — open a PR for human review.

You are working in the repository at `${repo_dir}` on the current branch.

## Context for the PR

- The implementation plan: `${plan_path}`
- The progress log — the full implement/review/verify history: `${progress_log_path}`
- The base branch the PR targets: `${base_branch}`

## Your job

1. Confirm the current branch has commits ahead of `${base_branch}` (run `git log` /
   `git status`). If there is nothing to ship, report that and stop.
2. The harness has already pushed the current branch to `origin` (a deterministic step before
   you). Verify it is there — `git status` should show it tracking `origin/<current-branch>` (or
   check `git ls-remote origin`). If it did NOT reach a remote (no `origin` configured, or the
   push was rejected), `gh pr create` will fail in the next step — report that honestly with an
   empty `pr_url` rather than faking success. Do not retry the push yourself.
3. Open a pull request against `${base_branch}` with:
   - a title summarizing the implemented plan,
   - a body that summarizes what was built, drawing on the progress log (implementation
     highlights, what review/verify found and fixed). Keep it informative and concise.
   - Use `gh pr create --base ${base_branch} --head <current-branch> --title "..." --body "..."`.
4. If the review/verify history flagged anything a human should look at before merging, call it
   out explicitly in the PR body under a "⚠️ For the reviewer" heading. (This is the honest
   handoff — surface unresolved concerns rather than burying them.)

Report `pr_url` (the URL of the opened PR, or empty if nothing was shipped) and a one-paragraph
`summary`.
