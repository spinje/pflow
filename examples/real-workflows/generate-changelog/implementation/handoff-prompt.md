I want to continue working on the generate-changelog workflow.

The workflow is executable documentation — read it directly:

1. `examples/real-workflows/generate-changelog/workflow.pflow.md` — the
   workflow itself. Node descriptions cover what each step does, why,
   and any edge cases. Limitations are in the header.
2. `.claude/skills/release/SKILL.md` — the release process that invokes
   this workflow. Shows how it's used end-to-end.
3. `pflow guide core examples/real-workflows/generate-changelog/workflow.pflow.md`
   — topic-scoped pflow reference tailored to this workflow.

## Operating notes (not in the workflow)

- Every run writes to CHANGELOG.md, docs/changelog.mdx, releases/, and
  posts to Slack. ~$0.07 per full run. **Ask before running.**
- For cheap testing, create a tag near HEAD and use a small range, or
  use `--dry-run` for cost/plan preview without side effects.
- Run from the project directory so output is reviewable — never from
  /tmp or anywhere else that can't be reviewed in place.
- Changelog files accumulate via prepend. Never "clean up" by copying
  from /tmp — you'll lose history.

## Open items

- None currently. When new ones come up, add them here.
