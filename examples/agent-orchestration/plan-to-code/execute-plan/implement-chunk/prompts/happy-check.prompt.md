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

- `commits_made`: the number of commits YOU added for THIS segment — the initial implementation
  PLUS anything you committed in this self-review pass. Count ONLY your own work in this session; do
  NOT count commits that earlier segments/forks already placed on the branch before you started (on
  segment 2+ a naive `git log` count would include those — exclude them). Set it to 0 ONLY if
  genuinely nothing was implemented or committed for this segment (a hard failure the harness
  early-exits on).
- `summary`: one paragraph on what the segment delivered.

Your FINAL message must be ONLY the JSON object matching `{commits_made, summary}` — no prose
before or after it.
