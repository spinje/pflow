# Implement One Segment

Per-segment body of the harness: a fresh agent implements one segment's phases and commits, then
takes a final fresh-eyes self-review pass over its own work (a resumed follow-up) before handoff.
Segmentation exists ONLY for context-window management — each segment runs in a fresh
`claude-code` process reading `{plan, spec, progress log}` by path, so context never accumulates
across the implementation of a large plan. There is NO external/multi-lens review here: that
happens ONCE over the whole codebase after all segments are implemented (at the `execute-plan`
level).

(Future extension — not built: a foundational segment whose error would compound downstream
could carry a `review_after` flag from breakdown to trigger an early per-segment review. Deferred
until a real plan needs it; today review is whole-codebase, once.)

## Inputs

### plan

Path to the implementation plan (read as REFERENCE; never templated inline — the 10k prompt
cap is post-interpolation).

- type: string
- required: true

### spec

Path to a complementary spec, or "" if none.

- type: string
- required: false
- default: ""

### delta

The phase-scoped instruction for this fork ("phases X done — implement Y, then STOP").

- type: string
- required: true

### progress_log

Path to the shared progress log every fork appends to — the carried-forward state bridge.

- type: string
- required: true

### repo_dir

Absolute repo root. The agent runs with this as its `cwd:`.

- type: string
- required: true

## Steps

### implement

Fresh implement fork: reads {plan, spec, progress log} by path, implements ONLY the scoped
phases, commits its work, and writes a progress-log entry — then ENDS its turn. It carries no
`output_schema`: the consumed `{commits_made, summary}` comes from the `happy-check` follow-up
(the segment's last step), which resumes this same session. The implement fork just implements,
commits, and logs.

- type: claude-code
- prompt: ./prompts/implement.prompt.md
- cwd: ${repo_dir}
- max_turns: 80
- timeout: 1800
- inputs:
    repo_dir: ${repo_dir}
    plan_path: ${plan}
    spec_path: ${spec}
    progress_log_path: ${progress_log}
    delta: ${delta}
- allowed_tools:
    - Bash
    - Read
    - Edit
    - Write
    - Glob
    - Grep
    - Task

### happy-check

Always-on final self-review of the just-implemented segment, run as a follow-up in the SAME
agent session via `resume`. The implement fork ended its turn; this re-prompts it with fresh
eyes on its own work — catch loose ends, COMMIT everything (leave the tree clean, so the review
and PR see all of it), and emit the consumed `{commits_made, summary}`. The `output_schema` +
the "final message = ONLY JSON" instruction live HERE because this is the segment's LAST step,
so its final message is the structured output the parent loop consumes. `commits_made == 0`
means the segment produced nothing — a hard failure the parent loop early-exits on. Resumes
`${implement.llm_usage.session_id}`; if usage is unavailable that resolves empty and this safely
runs as a fresh self-review (degraded, not broken).

- type: claude-code
- prompt: ./prompts/happy-check.prompt.md
- cwd: ${repo_dir}
- resume: ${implement.llm_usage.session_id}
- max_turns: 40
- timeout: 1200
- inputs:
    repo_dir: ${repo_dir}
    progress_log_path: ${progress_log}
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
  commits_made: { type: integer }
  summary: { type: string }
required: [commits_made, summary]
```

### report-commits

Surface a clean integer commit count for the parent loop, guarding the claude-code schema
soft-fail (on non-compliance `result` is a raw string, not a dict → treat as 0 commits = hard
failure, never crash on `.get`). Reads the `happy-check` follow-up's result — the segment's last
step and the producer of the consumed `{commits_made, summary}`.

- type: code
- inputs:
    impl: ${happy-check.result}

```python code
impl: object
result: int = impl.get("commits_made", 0) if isinstance(impl, dict) else 0
```

## Outputs

### commits_made

Commits the implement fork produced — `0` signals a hard failure the parent loop early-exits on.

- source: ${report-commits.result}
