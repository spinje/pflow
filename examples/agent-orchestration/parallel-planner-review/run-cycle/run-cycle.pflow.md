# Run One Planning Cycle

One full triage → implement → review → open-PRs cycle over the currently-unblocked
issues. Invoked repeatedly by `../orchestrate.pflow.md`; each invocation
re-fetches and re-plans against the live repo, so newly-unblocked work surfaces
over time.

Triage is deliberately minimal — `shell` fetch + ONE `llm` planning call. There
is no per-issue classification pass: priority and dependencies are relational
(they emerge from how the issues relate), so they need the whole-set view that a
single call already has, and a label-gated pool is small enough to fit one
context. Only `implement`, `review`, and `open-prs` are agents.

## Inputs

### base_branch

Branch PRs target, and that new branches are based on.

- type: string
- required: false
- default: main

### max_issues

Cap on how many issues the planner may pick up in a single cycle.

- type: integer
- required: false
- default: 5

## Steps

### find-repo

Resolve the repository root by walking up from wherever pflow was launched
(`git rev-parse --show-toplevel` does the walk). Every agent runs with this as
its `cwd`, so the workflow works launched from any subdirectory of the repo —
not just the root. Fails clearly if launched outside a git repo.

- type: shell

```shell command
git rev-parse --show-toplevel
```

### fetch-issues

Fetch the candidate pool as JSON — label-gated to `agent-ready` so the swarm
only ever touches issues a human opted in. Deterministic; no agent.

- type: shell

```shell command
gh issue list --label agent-ready --json number,title,body,labels --limit 50
```

### plan

The one relational call: read the whole candidate pool and select up to
`${max_issues}` unblocked, highest-impact issues — inferring dependencies and
priority from what the issues are about. `output_schema` guarantees valid JSON
via constrained decoding (an `llm` node, not an agent — no tools needed).

- type: llm
- prompt: ./prompts/plan.prompt.md
- inputs:
    issues: ${fetch-issues.stdout}
    max_issues: ${max_issues}

```yaml output_schema
type: object
properties:
  issues:
    type: array
    items:
      type: object
      properties:
        number: { type: integer }
        title: { type: string }
        branch: { type: string }
        rationale: { type: string }
      required: [number, title, branch, rationale]
required: [issues]
```

### gate

Skip the expensive implement/review/PR work when the planner found nothing
unblocked — a zero-issue cycle costs only fetch + plan.

- type: code
- inputs:
    issues: ${plan.response.issues}

```python code
issues: list
result: int = len(issues)
if issues:
    next: str = "implement-and-review-each"
else:
    next: str = "end"
```

### implement-and-review-each

Fan out across the unblocked issues, one parallel agent pipeline per issue, each
on its own branch/worktree. `error_handling: continue` keeps the pack alive if
one issue fails.

- type: workflow
- workflow: ./implement-and-review-one/implement-and-review-one.pflow.md
- next: open-prs
- inputs:
    issue: ${item}
    base_branch: ${base_branch}
    repo_dir: ${find-repo.stdout}
- batch:
    items: ${plan.response.issues}
    parallel: true
    max_concurrent: 3
    error_handling: continue

### open-prs

Finalize the cycle by opening a PR per approved branch (push + `gh pr create`),
never merging into `${base_branch}` directly. **Critically, it also removes the
`agent-ready` label from every issue it touches** — that is what shrinks the
candidate pool so the next cycle doesn't re-pick a done issue and collide on its
existing branch. Without the relabel the loop would never converge. Approved
issues get a PR; `request-changes` issues are relabeled `agent-needs-human`.

- type: agent
- backend: claude
- prompt: ./prompts/open-prs.prompt.md
- cwd: ${find-repo.stdout}
- max_turns: 30
- timeout: 900
- inputs:
    results: ${implement-and-review-each.results}
    base_branch: ${base_branch}
- allowed_tools:
    - Bash
    - Read

```yaml output_schema
type: object
properties:
  prs_opened: { type: array, items: { type: string } }
  needs_human: { type: array, items: { type: string } }
required: [prs_opened, needs_human]
```

## Outputs

### issues_planned

The issues the planner picked this cycle. The orchestrator loops on this list:
while it is non-empty there is more work, and because `open-prs` removes the
`agent-ready` label, the pool shrinks each cycle until this drains to empty.
Declared `array` so the orchestrator's `loop: while:` source is positively typed.

- type: array
- source: ${plan.response.issues}

### prs_opened

Branches that got a PR this cycle, or `[]` when the cycle ended early with no
work.

- source: ${open-prs.result.prs_opened ?? []}
