You just finished implementing a segment of the plan and committed your work — it's all in the
conversation above. Before this hands off to an independent review, take ONE more pass over your
own work with fresh eyes.

Ask yourself plainly: **are you FULLY happy with this implementation? Any loose ends?** Look for
the things that are easy to leave behind — a missing edge case, a test you meant to write, a
half-done refactor, an unhandled error path, a name that no longer fits. Prioritize the
simplicity of the FINAL code, not how easy it was to get there. Fix the real gaps you find.

If, on honest reflection, the work was already complete and clean, that is a fine outcome — make
no change and say so. Do not invent busywork.

## Commit everything — leave the working tree clean

Run `git status`. **Any uncommitted change is invisible to the review that follows and is
excluded from the pull request — it will be lost.** Commit your fixes with clear messages so the
working tree is clean. If you fixed anything in this pass, append a brief note to the progress
log at `${progress_log_path}`.

## Report

- `commits_made`: the TOTAL number of commits this segment added — the initial implementation
  PLUS anything you committed in this pass (run `git log` to count if unsure). Set it to 0 ONLY
  if genuinely nothing was implemented or committed (a hard failure).
- `summary`: one paragraph on what the segment delivered.

Your FINAL message must be ONLY the JSON object matching `{commits_made, summary}` — no prose
before or after it.
