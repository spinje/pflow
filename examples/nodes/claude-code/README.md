# Claude Code Node Examples

Examples for the `claude-code` node: an agentic super node that integrates with the Claude Agent SDK for AI-assisted development tasks.

Features:

- Dynamic schema-driven output for structured responses
- Metadata capture (cost, duration, token usage) in `llm_usage`
- Tool use (Read, Write, Edit, Bash, Glob, Grep, LS, WebFetch, WebSearch)
- Dual authentication: API key or Claude Pro/Max CLI

## Examples

### 1. Simple code generation — `claude-code-basic.pflow.md`

```bash
pflow examples/nodes/claude-code/claude-code-basic.pflow.md
```

Demonstrates:

- Basic task execution via the `prompt` parameter
- Accessing generated text via `${node.result}`
- Cost tracking via `${node.llm_usage.cost_usd}`
- Duration and token usage

### 2. Structured code review — `claude-code-schema.pflow.md`

```bash
pflow examples/nodes/claude-code/claude-code-schema.pflow.md file_path=your_script.py
```

Demonstrates:

- `output_schema` for structured outputs
- Field access via `${node.result.field_name}`
- Declared workflow inputs referenced as `${file_path}`
- Multiple output files from a single analysis

### 3. Debugging assistant — `claude-code-debug.pflow.md`

```bash
pflow examples/nodes/claude-code/claude-code-debug.pflow.md error_message="TypeError: ..."
```

Demonstrates:

- Error analysis with structured output
- Optional inputs (`code_context`, `stack_trace`)
- Confidence scoring and prevention tips

### 4. Git workflow integration — `claude-code-git-workflow.pflow.md`

```bash
pflow examples/nodes/claude-code/claude-code-git-workflow.pflow.md
```

Demonstrates:

- Multi-stage analysis pipeline (shell → claude-code → claude-code → write-file)
- Passing upstream node output into the prompt via `${node_id.field}` interpolation
- System prompts for specific personas
- Cost aggregation across multiple calls

## Schema-driven output

When you provide `output_schema`, the result is parsed into a structured dict:

```yaml output_schema
summary:
  type: str
  description: Brief summary
score:
  type: int
  description: Score from 1-10
items:
  type: list
  description: List of items
```

Access fields directly: `${node.result.summary}`, `${node.result.score}`, `${node.result.items}`.

If JSON parsing fails, the raw text is available at `${node.result}` and an error message at `${node._schema_error}`.

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

## Authentication

- **API key**: `export ANTHROPIC_API_KEY=sk-ant-...` — billed to your Anthropic Console account.
- **Claude Pro/Max subscription**: `claude setup-token` (or `claude auth login`) — uses subscription entitlements.

## Parameters

| Parameter             | Default             | Description                                                 |
|-----------------------|---------------------|-------------------------------------------------------------|
| `prompt`              | required            | Prompt to send to Claude                                    |
| `output_schema`       | None                | Schema for structured output (see above)                    |
| `cwd`                 | `os.getcwd()`       | Working directory                                           |
| `model`               | `claude-sonnet-4-5` | Claude model identifier                                     |
| `allowed_tools`       | All tools           | Permitted tool names (e.g., `["Read", "Write"]`)            |
| `disallowed_tools`    | None                | Tool names or patterns to deny (e.g., `["Bash(git:*)"]`)    |
| `max_turns`           | 50                  | Maximum conversation turns                                  |
| `max_thinking_tokens` | 8000                | Maximum tokens for extended reasoning                       |
| `timeout`             | 300                 | Execution timeout in seconds (30–3600)                      |
| `system_prompt`       | None                | System instructions                                         |
| `resume`              | None                | Session ID to resume a previous conversation                |
| `sandbox`             | None                | Sandbox configuration (see node docstring for full schema)  |

## Best practices

- Use `output_schema` whenever you need specific fields — it eliminates regex parsing.
- Set `max_turns` proportional to task complexity: 1 for simple generation, 2–3 for review, 5–10 for multi-step debugging.
- Track `${node.llm_usage.cost_usd}` for budget visibility.
- Interpolate context directly into the `prompt` — there is no `context` parameter.
- Check `${node._schema_error}` after structured calls if downstream logic depends on parsed fields.

## Troubleshooting

- **"Claude not outputting JSON despite schema"** — increase `max_turns` so Claude has room to refine.
- **High cost** — reduce `max_turns`, tighten the prompt, or restrict `allowed_tools`.
- **Timeouts** — break complex tasks into smaller steps or raise `timeout`.
- **Authentication failed** — run `claude doctor` or verify `ANTHROPIC_API_KEY`.

## See also

- [Claude Agent SDK documentation](https://docs.anthropic.com/en/api/claude-agent-sdk)
- `pflow guide` — top-level guide for workflow authoring
