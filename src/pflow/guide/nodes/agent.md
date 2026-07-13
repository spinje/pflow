# Agent Node

**Use for**: multi-step work that needs an autonomous coding agent to inspect files, edit a repository, run commands, and iterate on results.

**Use a narrower node when it fits**: deterministic data reshaping → `code`, one command → `shell`, one API call → `http`, ordinary text analysis without repository tools → `llm`.

`backend` is required:

- `claude` runs Claude Code.
- `codex` runs the installed `codex exec` CLI.

All parameters are flat. Shared parameters work with either backend: `prompt`, `inputs`, `model`, `cwd`, `output_schema`, `resume`, `timeout`, `system_prompt`, and `schema_retries`. Backend-only parameters are rejected when paired with the other backend.

| Backend | Backend-specific parameters | `sandbox` shape |
|---|---|---|
| `claude` | `allowed_tools`, `disallowed_tools`, `max_turns`, `max_thinking_tokens`, `use_api_key` | dict of Claude sandbox settings |
| `codex` | `approval_policy`, `add_dir`, `profile`, `config` | `read-only`, `workspace-write`, or `full-access` |

When `model` is omitted, Claude uses `claude-sonnet-4-5`; Codex inherits the model from its CLI configuration. Codex defaults to `workspace-write` when `sandbox` is omitted.

## Claude pattern

`````markdown
### implement-fix

Fix the failing behavior and report the exact files changed.

- type: agent
- backend: claude
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
required: [summary, files_changed, tests_run]
```

```prompt
Fix this issue in the current repository:

${triage.result}

Keep the change focused. Run the smallest relevant tests and include the
commands in tests_run.
```
`````

## Codex pattern

`````markdown
### review-fix

Review the current change and return actionable findings.

- type: agent
- backend: codex
- cwd: .
- sandbox: workspace-write
- approval_policy: never
- add_dir:
    - ../shared-fixtures

```yaml output_schema
type: object
properties:
  summary: { type: string }
  findings:
    type: array
    items: { type: string }
required: [summary, findings]
```

```prompt
Review the current worktree for correctness. Fix confirmed issues, run focused
tests, and return the final summary and any remaining findings.
```
`````

`approval_policy` accepts `untrusted`, `on-request`, or `never`. `config` passes TOML-compatible Codex configuration overrides; prefer the dedicated parameters when one exists. The node isolates Codex stdin, so the CLI cannot consume pflow's own input pipe.

## Structured output and schema recovery

`output_schema` uses each backend's native structured-output surface. Both backends require top-level `type: object`. Wrap arrays, primitives, or top-level combinators inside an object property.

When `output_schema` is set, pflow can recover from schema soft-failures in two ways:

1. **Scalar coercion** converts canonical scalar values such as `"false"` → `false` and `"3"` → `3`. Nested objects and arrays are not coerced.
2. **Resume retry** asks the same backend session to emit only an object matching the schema. `schema_retries` defaults to `1`; set it to `0` to disable validation/retry and accept the backend result as-is.

For Claude, `max_turns` must be at least `2` when structured output is enabled. Codex has no `max_turns` parameter.

On exhausted or unavailable schema recovery, the node still returns `default`: `${node.result}` contains raw text, `${node._schema_error}` contains the reason, and the workflow becomes `DEGRADED`. Schema soft-failures do not follow `on-error` edges.

When recovery made corrective calls, `${node.llm_usage}` describes the final call and `llm_usage.retries` records the superseded calls. Reports and trace summaries aggregate usage across them.

## Resume an agent session

Both backends write a resumable identifier to `llm_usage.session_id`. Pass it through `resume` to continue that session, including in a later pflow invocation:

```markdown
### investigate

- type: agent
- backend: codex
- prompt: Inspect the failing tests and identify the root cause. Do not edit yet.

### implement

- type: agent
- backend: codex
- resume: ${investigate.llm_usage.session_id}
- prompt: Implement the fix you proposed and run the focused tests.
```

Schema retries use the same continuation mechanism automatically. If a backend call produces no session ID, pflow keeps the raw result and degrades instead of starting an unrelated fresh session.

## Authentication

### Claude

Install and authenticate Claude Code once:

```bash
npm install -g @anthropic-ai/claude-code
claude auth login
claude auth status
```

By default, `backend: claude` uses your Claude Pro/Max subscription. The node blanks `ANTHROPIC_API_KEY` for the Claude subprocess only, because the CLI otherwise prefers an ambient key and silently switches to Anthropic Console billing. The parent environment is unchanged, so sibling `llm` nodes can still use the stored key.

Set `use_api_key: true` only when you intend to bill `ANTHROPIC_API_KEY` to Anthropic Console:

```markdown
### implement

- type: agent
- backend: claude
- use_api_key: true
- prompt: Refactor this module and run its tests.
```

For non-interactive subscription setup, use `claude setup-token`. If authentication fails in default mode, run `claude auth login`; if `use_api_key: true`, check the key and Console credit instead.

### Codex

Install the CLI and authenticate with your ChatGPT account:

```bash
npm install -g @openai/codex
codex login
```

The backend uses the CLI's existing login and configuration; no OpenAI API key parameter exists on the node. Missing CLI and login errors include these commands in their remediation text.

## Choosing permissions

For Claude, constrain tools with `allowed_tools` / `disallowed_tools` and use a Claude sandbox dict when command isolation is required.

For Codex, choose the narrowest sandbox that can complete the task:

- `read-only` for analysis without file edits.
- `workspace-write` for normal repository work (default).
- `full-access` only when the task must write outside the workspace sandbox.

`add_dir` grants additional writable directories on initial Codex runs. Resume continues the persisted Codex thread; do not assume a resumed turn re-applies initial working-directory or additional-directory flags.

## Result handling

Downstream nodes read free-form text as `${node.result}` or structured fields such as `${node.result.summary}`. Every successful backend call also writes normalized `llm_usage` fields: token counts, duration, turn count, session ID, and model. Claude supplies an API-equivalent `cost_usd`; Codex CLI usage has `cost_usd: null` and additionally reports `reasoning_output_tokens`.

Run with `--report` while tuning prompts. The report shows the rendered prompt, result, tools, retries, token usage, and available cost data.
