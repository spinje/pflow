The project's own validation command is currently FAILING on this branch, and your single job is to
make it pass — by fixing the real cause, not by silencing the check.

This is fix attempt **${round}**.

## See exactly what's failing

Run the validation command yourself and read its output in full:

```
${validate_command}
```

It runs in the repository at `${repo_dir}` (your working directory). It is the project's real
test/lint/type gate — its exit code is the ground truth you must turn green.

## Understand the change before fixing

- The implementation plan (intended behavior): `${plan_path}`
- The progress log (what was built + prior fix attempts): `${progress_log_path}`
- The actual change: `git diff ${base_branch}...HEAD` — the work branch is committed, so a bare
  `git diff` shows nothing; always diff against the base.

## Fix the ROOT CAUSE — this is the important part

A failing test/type/lint check is a signal, not the enemy. For each failure, decide WHY it fails and
fix the underlying cause:

- **A regression in the source** (the common case — the new code broke existing behavior): fix the
  **source**. This is almost always the right move.
- **A test that must change because the plan INTENTIONALLY changed that behavior**: update the test
  to match the intended new behavior — but only when the plan clearly intended it. Bias strongly
  toward "the source is wrong, not the test."

**Never** make a check pass by weakening it, deleting the test, loosening an assertion, adding a
blanket `# type: ignore`, or `xfail`/`skip` to dodge it. That defeats the entire gate. If a failure
is genuinely impossible to fix correctly, say so explicitly in the progress log rather than faking
green.

## Finish

1. Re-run `${validate_command}` and confirm it now passes (or that you fixed everything you can).
2. Commit your fix on the current branch with a clear message.
3. Append a concise, no-fluff entry to the progress log at `${progress_log_path}`: what was failing,
   the root cause, and what you changed. A fresh agent re-checks after you — leave it the context.

The gate re-runs the command deterministically after you finish, so your report is not what counts —
the command's exit code is. Make it green for real.
