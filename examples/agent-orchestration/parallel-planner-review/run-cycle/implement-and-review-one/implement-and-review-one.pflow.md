# Implement and Review One Issue

Per-issue body of the orchestration loop: implement one issue on its own branch,
then review the result — but only if the implementer produced commits. Runs as
one item of a parallel batch, so it isolates its work in a dedicated git
worktree to avoid colliding with sibling agents on the shared checkout.

Both agentic steps load their prompts from `./prompts/`.

## Inputs

### issue

The issue to work on: an object with `number`, `title`, and `branch` (the branch
name the planner assigned).

- type: object
- required: true

### base_branch

Branch to base the new work branch on.

- type: string
- required: true

### repo_dir

Absolute path to the repository root (resolved by the parent via
`git rev-parse --show-toplevel`). Both agents run with this as their `cwd`, so
worktree paths are predictable regardless of where pflow was launched.

- type: string
- required: true

## Steps

### implement

Implement the issue in an isolated worktree and commit. Genuinely agentic:
write code, run tests, iterate. Reports `commits_made` so the next step can
decide whether a review is warranted.

- type: agent
- backend: claude
- prompt: ./prompts/implement.prompt.md
- cwd: ${repo_dir}
- max_turns: 80
- timeout: 1800
- inputs:
    issue: ${issue}
    base_branch: ${base_branch}
- allowed_tools:
    - Bash
    - Read
    - Edit
    - Write
    - Glob
    - Grep

```yaml output_schema
type: object
properties:
  branch: { type: string }
  commits_made: { type: integer }
  summary: { type: string }
required: [branch, commits_made, summary]
```

### check-commits

Gate the review: only branches with real commits are worth a reviewer's time.
Literal routing — pflow auto-detects the `review` / `end` targets.

- type: code
- inputs:
    committed: ${implement.result.commits_made}

```python code
committed: int
result: int = committed
if committed > 0:
    next: str = "review"
else:
    next: str = "end"
```

### review

A real review — reads the diff AND the surrounding code (callers, tests,
related modules), which is why it is an agent, not a single LLM call. Adequate
`max_turns` so it is never starved mid-review.

- type: agent
- backend: claude
- prompt: ./prompts/review.prompt.md
- cwd: ${repo_dir}
- max_turns: 12
- timeout: 600
- next: end
- inputs:
    branch: ${implement.result.branch}
    summary: ${implement.result.summary}
    base_branch: ${base_branch}
- allowed_tools:
    - Bash
    - Read
    - Grep

```yaml output_schema
type: object
properties:
  verdict: { type: string, enum: [approve, request-changes] }
  notes: { type: string }
required: [verdict, notes]
```

## Outputs

### branch

The branch this item produced.

- source: ${implement.result.branch}

### commits_made

Commits produced — `0` means nothing to merge.

- source: ${implement.result.commits_made}

### verdict

The review verdict, or `"skipped"` when there were no commits to review. Branch
convergence: `review` only runs on the committed path, so the literal fallback
covers the skipped path.

- source: ${review.result.verdict ?? "skipped"}

### summary

What the implementer changed.

- source: ${implement.result.summary}
