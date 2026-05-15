# Claude Code Node

**Use for**: Multi-step agentic tasks that require a fully autonomous agent.

**Don't use Claude Code for**: Deterministic data reshaping (use `code`), simple shell commands (use `shell`), API calls (use `http`), or ordinary text analysis that does not need repository tools (use `llm`).

**The test**: Does the task need an autonomous coding agent with access to multiple tools like reading files, editing code, bash etc? YES -> `claude-code`. NO -> use the smaller node that matches the operation.

Use `output_schema` when downstream nodes need structured implementation results. Claude Code schemas must be JSON Schema objects with top-level `type: object`, and `max_turns` must be at least `2` when `output_schema` is set.

Run with `--report` when iterating on prompts. The report shows the rendered prompt, result, tool usage, and cost so you can tighten the task without guessing.

### Node Creation Pattern

`````markdown
### implement-fix

Fix the failing behavior and report the exact files changed.

- type: claude-code
- max_turns: 6
- allowed_tools:
    - Read
    - Edit
    - Bash

```yaml output_schema
type: object
properties:
  summary:
    type: string
  files_changed:
    type: array
    items:
      type: string
  tests_run:
    type: array
    items:
      type: string
  follow_up:
    type: string
required:
  - summary
  - files_changed
  - tests_run
```

```prompt
Fix this issue in the current repository:

${triage.result}

Keep the change focused. Run the smallest relevant tests and include the
commands in tests_run.
```
`````

Downstream nodes can read structured fields directly:

```markdown
- content: ${implement-fix.result.summary}
- content: ${implement-fix.result.files_changed}
```

### Claude Code Rules

- Keep prompts specific: state the bug, success criteria, files or commands already known, and verification expectation.
- Prefer narrow tool access with `allowed_tools` / `disallowed_tools` when the workflow should constrain what the agent can do.
- Use `output_schema` for summaries that downstream nodes will route, save, or format.
- Do not ask Claude Code to emit both prose and machine data in the same result; put all required fields in the schema.
- If the task is only "transform this object into that object", use `code` instead.

### Recovering from schema soft-failures

`claude-code` always returns `default`. Schema soft-failures (model didn't comply, a provider error landed alongside the output, or a templated `output_schema` reference resolved to None) do NOT route through `- on-error:` edges. Branch on `${node._schema_error}` or workflow `DEGRADED` status instead:

```markdown
### review

- type: claude-code
- prompt: "..."
- max_turns: 4
- next: branch-on-schema

```yaml output_schema
type: object
properties:
  summary: { type: string }
required: [summary]
```

### branch-on-schema

- type: code
- inputs:
    schema_error: ${review._schema_error ?? ""}

```python code
schema_error: str
if schema_error:
    next: str = "fallback"
else:
    next: str = "use-result"
```
```
