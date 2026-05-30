Implement GitHub issue #${issue.number}: "${issue.title}".

Work in an ISOLATED git worktree so you do not collide with sibling agents
running on the same checkout:

    git worktree add -b ${issue.branch} ../wt-${issue.branch} ${base_branch}

Do all your work inside that worktree directory. Make the smallest correct
change, run the most relevant tests, and commit.

Set commits_made to the number of commits you actually created on
${issue.branch} (0 if you could not complete the work).
