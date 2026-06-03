You are implementing part of an implementation plan. Earlier phases (if any) are already
implemented and committed on the current git branch; you are picking up fresh, with only the
written artifacts as context. Read them in full before starting.

## Read these first (do NOT skip)

- The implementation plan: `${plan_path}`
- The complementary spec, if one is provided: `${spec_path}` (may be empty — ignore if so)
- The progress log — what earlier forks did, learned, and decided: `${progress_log_path}`

You are working in the repository at `${repo_dir}` on the current branch. Prior phases'
commits are already here; build on them.

## Your scope (do ONLY this)

${delta}

Implement ONLY the phases named above. Do not start later phases — a fresh agent will pick
those up after you, and your work will be reviewed before it proceeds. Stopping at the right
boundary is part of doing this correctly.

## How to work

- **Prioritize the simplicity of the FINAL code, not how easy it is to get there.** Ugly code
  that you'll "clean up later" is not done.
- **Don't take shortcuts.** If you consider skipping a step the plan calls for, you need a
  clear, written rationale (in your progress-log entry below). "It was easiest to defer" is
  not an acceptable reason.
- Make the change, run the most relevant tests for what you touched, and commit your work
  (one or more focused commits) on the current branch.
- You may dispatch parallel sub-agents for mechanical, clearly-scoped work — but code anything
  that needs deep context of the plan, spec, or prior phases YOURSELF.

## Then record your work

Append a concise, no-fluff entry to the progress log at `${progress_log_path}`. A later
reviewer fork starts fresh and will rely on this entry plus `git diff` to understand what you
did — a thin entry leaves it blind. Include: what you implemented, key decisions/insights, and
any deviations from the plan WITH clear reasons (no hand-waving).

Commit your work on the current branch, then stop.
