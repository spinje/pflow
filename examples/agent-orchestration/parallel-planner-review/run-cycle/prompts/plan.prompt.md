You are triaging open GitHub issues for an autonomous implementation swarm.

From the issues below, select up to ${max_issues} that are BOTH unblocked and
worth doing now. Priority and dependencies are NOT stated in the issues — infer
them from what each issue is actually about:

- **Dependencies**: if two issues touch the same component/area, or one must
  logically land before another, treat the prerequisite as a blocker. Only pick
  issues whose prerequisites are already done (i.e. not also in this list).
- **Priority**: judge intrinsic severity/impact (security, data loss, crashes,
  broken builds rank above features, which rank above cosmetics) and prefer work
  that unblocks the most downstream issues.
- **Dedup**: if several issues share a root cause, pick one.

For each chosen issue, assign a branch name `agent/<short-slug>-<number>` and a
one-line rationale. Return an empty list if nothing is safely unblocked.

Open issues (JSON):
${issues}
