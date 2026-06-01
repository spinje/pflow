# Claude Code Node Examples

Examples for the `claude-code` node: an agentic super node that integrates with the Claude Agent SDK for AI-assisted development tasks.

Features:

- Native JSON Schema structured output
- Metadata capture (cost, duration, token usage) in `llm_usage`
- Tool use (Read, Write, Edit, Bash, Glob, Grep, LS, WebFetch, WebSearch)
- Subscription-first auth: Claude Pro/Max by default; opt into API-key billing with `use_api_key: true`

## Examples

### 1. Simple code generation - `claude-code-basic.pflow.md`

```bash
pflow examples/nodes/claude-code/claude-code-basic.pflow.md
```

Demonstrates:

- Basic task execution via the `prompt` parameter
- Accessing generated text via `${node.result}`
- Cost tracking via `${node.llm_usage.cost_usd}`
- Duration and token usage

### 2. Structured code review - `claude-code-schema.pflow.md`

```bash
pflow examples/nodes/claude-code/claude-code-schema.pflow.md file_path=your_script.py
```

Demonstrates:

- `output_schema` for structured outputs
- Field access via `${node.result.field_name}`
- Declared workflow inputs referenced as `${file_path}`
- Multiple output files from a single analysis

### 3. Debugging assistant - `claude-code-debug.pflow.md`

```bash
pflow examples/nodes/claude-code/claude-code-debug.pflow.md error_message="TypeError: ..."
```

Demonstrates:

- Error analysis with structured output
- Optional inputs (`code_context`, `stack_trace`)
- Confidence scoring and prevention tips

### 4. Git workflow integration - `claude-code-git-workflow.pflow.md`

```bash
pflow examples/nodes/claude-code/claude-code-git-workflow.pflow.md
```

Demonstrates:

- Multi-stage analysis pipeline (shell -> claude-code -> claude-code -> write-file)
- Passing upstream node output into the prompt via `${node_id.field}` interpolation
- System prompts for specific personas
- Cost aggregation across multiple calls

## Schema-driven output

When you provide `output_schema`, pflow passes JSON Schema to the Claude Agent SDK's native structured-output mode. The top-level schema must be `type: object`.

```yaml output_schema
type: object
properties:
  summary:
    type: string
    description: Brief summary
  score:
    type: integer
    minimum: 1
    maximum: 10
    description: Score from 1-10
  items:
    type: array
    items:
      type: string
    description: List of items
required: [summary, score, items]
```

Access fields directly: `${node.result.summary}`, `${node.result.score}`, `${node.result.items}`.

If the SDK returns no structured output, the raw text is available at `${node.result}`, an error message is available at `${node._schema_error}`, and `shared["__warnings__"][node_id]` marks the workflow status `DEGRADED`.

The node always returns `default` from `post()` — schema soft-failures DO NOT route through `- on-error:` edges. Wire schema-recovery logic by inspecting `${node._schema_error}` or the workflow `DEGRADED` status, not the error edge.

## Passing context into the prompt

The node has no dedicated `context` parameter. Embed upstream data directly in the prompt using template interpolation:

````markdown
```prompt
Analyze these changes.

Diff:
${git_diff.stdout}

Commits:
${git_log.stdout}
```
````

This works for any template reference: workflow inputs (`${input_name}`), prior node outputs (`${node_id.field}`), and structured results (`${other_node.result.field}`).

## Metadata in `llm_usage`

Every execution captures:

```
${node.llm_usage.model}                         # Model identifier
${node.llm_usage.input_tokens}                  # Non-cached input tokens
${node.llm_usage.output_tokens}                 # Output tokens
${node.llm_usage.total_tokens}                  # Sum of input + output
${node.llm_usage.cache_creation_input_tokens}   # Cache-creation tokens
${node.llm_usage.cache_read_input_tokens}       # Cache-read tokens
${node.llm_usage.cost_usd}                      # Cost in USD
${node.llm_usage.duration_ms}                   # Wall-clock duration
${node.llm_usage.num_turns}                     # Conversation turns used
${node.llm_usage.session_id}                    # Resumable session ID
```

`cost_usd` is the SDK-reported API-equivalent estimated cost. Actual billing depends on auth method; Claude Pro/Max subscription runs may report an API-equivalent cost without a direct per-call charge.

## Authentication

By default this node uses your **Claude Pro/Max subscription** and blanks `ANTHROPIC_API_KEY` for the Claude subprocess, so an ambient key (including one stored via `pflow settings set-env` for the `llm` node) never silently bills your Anthropic Console per token.

- **Subscription (default)**: `claude auth login` (or `claude setup-token` for non-interactive/CI) - no per-token charges. Check with `claude auth status`.
- **API key (opt in)**: set `- use_api_key: true` on the node, with `ANTHROPIC_API_KEY` in the environment (e.g. `pflow settings set-env ANTHROPIC_API_KEY "sk-ant-..."`) - bills your Anthropic Console per token.

## Parameters

| Parameter             | Default             | Description                                                 |
|-----------------------|---------------------|-------------------------------------------------------------|
| `prompt`              | required            | Prompt to send to Claude                                    |
| `output_schema`       | None                | JSON Schema for structured output (see above)               |
| `cwd`                 | `os.getcwd()`       | Working directory                                           |
| `model`               | `claude-sonnet-4-5` | Claude model identifier                                     |
| `allowed_tools`       | All tools           | Permitted tool names (e.g., `["Read", "Write"]`)            |
| `disallowed_tools`    | None                | Tool names or patterns to deny (e.g., `["Bash(git:*)"]`)    |
| `max_turns`           | 50                  | Maximum conversation turns (must be >=2 with schema)        |
| `max_thinking_tokens` | 8000                | Maximum tokens for extended reasoning                       |
| `timeout`             | 300                 | Execution timeout in seconds (30–3600)                      |
| `system_prompt`       | None                | System instructions                                         |
| `resume`              | None                | Session ID to resume a previous conversation                |
| `sandbox`             | None                | Sandbox configuration (see node docstring for full schema)  |
| `use_api_key`         | `false`             | Bill to `ANTHROPIC_API_KEY` (Console); default uses subscription |

## Best practices

- Use `output_schema` whenever you need specific fields; it delegates enforcement to the SDK's native structured-output mode.
- Set `max_turns` proportional to task complexity: 2 for simple structured output, 2-3 for review, 5-10 for multi-step debugging.
- Track `${node.llm_usage.cost_usd}` for budget visibility.
- Interpolate context directly into the `prompt`; there is no `context` parameter.
- Check `${node._schema_error}` or workflow `DEGRADED` status after structured calls if downstream logic depends on parsed fields.

## Troubleshooting

- **"Claude not producing structured output despite schema"** - check that the schema is valid JSON Schema and increase `max_turns` if needed.
- **Top-level array schema rejected** - wrap arrays or primitives inside a top-level object property.
- **High cost** - reduce `max_turns`, tighten the prompt, or restrict `allowed_tools`.
- **Timeouts** - break complex tasks into smaller steps or raise `timeout`.
- **Authentication failed** - by default this node uses your subscription; run `claude auth login` (check with `claude auth status`), or set `- use_api_key: true` to bill `ANTHROPIC_API_KEY` to your Anthropic Console.

## See also

- [Claude Agent SDK documentation](https://docs.anthropic.com/en/api/claude-agent-sdk)
- `pflow guide` - top-level guide for workflow authoring
