# Agent Node Package

The `agent` node is pflow's intentional exception to the [simple node philosophy](../features/simple-nodes.md). It delegates repository-scale work to an autonomous coding agent that can inspect files, run tools, modify code, and iterate. A `backend` parameter selects Claude or Codex without changing the workflow's output contract.

## Public interface

| Node | Required inputs | Primary output |
|---|---|---|
| `agent` | `backend` (`claude` or `codex`), `prompt` | `result` (text or parsed structured output) |

Shared parameters are `prompt`, `inputs`, `model`, `cwd`, `output_schema`, `resume`, `timeout`, `system_prompt`, `schema_retries`, and `use_api_key`. Backend-only parameters remain flat:

- Claude: `allowed_tools`, `disallowed_tools`, `max_turns`, `max_thinking_tokens`, and a dict-shaped `sandbox`.
- Codex: `approval_policy`, `add_dir`, `profile`, `config`, and a string `sandbox` mode.

The static validator and runtime backend validation share the parameter sets from `nodes/agent/schema_validation.py`. This is load-bearing: registry metadata must list the union so valid workflows pass unknown-parameter validation, while the backend-aware layer rejects a parameter that belongs to the other backend.

## Architecture

```text
AgentNode
  ├── ClaudeBackend ── Claude Agent SDK ── installed Claude CLI
  └── CodexBackend  ── codex exec subprocess

AgentBackend.run(prompt, options) -> AgentResult
```

`AgentNode` owns the backend-neutral lifecycle:

- shared parameter validation;
- structured-output coercion, continuation retries, and soft-failure storage;
- normalized `result` / `llm_usage` writes;
- trace-visible tool and progress storage;
- PocketFlow retry/fallback integration.

Each backend owns its transport and backend-specific policy:

- option construction and parameter shapes;
- session continuation;
- tool/event parsing;
- token normalization into `AgentResult.metadata`;
- authentication and process error translation.

The boundary matters because the transports are not interchangeable. Claude yields SDK message objects from an asynchronous query. Codex yields typed JSONL events from a synchronous CLI process and writes its final answer to a separate `--output-last-message` file. Moving either transport's parsing into `AgentNode` would couple the shared lifecycle back to one backend.

## Backend behavior

### Claude

`ClaudeBackend` imports `claude_agent_sdk` lazily when `backend: claude` is selected. It uses `ClaudeAgentOptions` with autonomous permission mode, optional tool restrictions, native JSON Schema output, SDK session resume, and the Claude sandbox dict.

Claude defaults to `claude-sonnet-4-5`. It normalizes the SDK's split input/cache fields into pflow's inclusive `input_tokens` contract and carries the SDK's API-equivalent `total_cost_usd` as `cost_usd`.

Authentication defaults to Claude account/subscription mode. The backend blanks `ANTHROPIC_API_KEY` in the child environment unless `use_api_key: true`, preventing that named ambient key from silently switching the CLI to Anthropic Console billing.

### Codex

`CodexBackend` invokes the installed `codex exec` executable with a shell-free argv list, `stdin=DEVNULL`, an execution timeout, and unique temporary files for the final message and optional schema.

By default, the backend copies the parent environment, removes `OPENAI_API_KEY` and `CODEX_API_KEY`, requires a recognized ChatGPT/account access-token result from `codex login status`, and passes that same child environment to `codex exec`. It also appends `model_provider="openai"` after caller overrides. Each possible model call—including a schema-correction resume—gets a fresh preflight. Deterministic status failures are non-retriable and raw status text is never retained in the exception.

`use_api_key: true` is the shared escape hatch: Codex skips the account preflight and preserves key/profile/provider configuration, while Claude stops blanking `ANTHROPIC_API_KEY`. This grants permission; it neither requires a key nor changes credentials. The false-mode boundary covers named first-party key variables, recognized stored Codex API-key auth, and ordinary provider selection—not custom proxies/base URLs, account credits, auto-reload, overage, or administrator policy.

The channels have distinct jobs:

- typed JSONL stdout supplies `thread.started`, `turn.completed` usage, command events, and failure events;
- `--output-last-message` supplies the final text;
- the schema file supplies native structured-output constraints;
- stderr and exit status supply process diagnostics.

Initial and resume argv are built separately. Initial runs accept CLI `--sandbox`, `--cd`, and `--add-dir`. Resume requires `sandbox_mode` as a config override, places `--profile` before the `resume` subcommand, and relies on Codex's on-disk thread store.

Codex omits a model override when the workflow does not declare one, so the CLI configuration remains authoritative. Its CLI usage exposes no per-run USD amount, but an explicitly declared and LiteLLM-priced `model` lets pflow compute an API-equivalent `cost_usd` from cache-aware token usage. Omitted or unpriced models remain `None`; pflow does not inspect private Codex session files to infer the effective model. `reasoning_output_tokens` remains a separate backend-specific usage field.

## Structured output contract

Both backends require a top-level `type: object` JSON Schema. `AgentNode` first applies canonical scalar coercions, then uses the backend's session ID for corrective continuation calls up to `schema_retries`.

If output still does not conform—or no resumable session exists—the node stores raw text in `result`, writes `_schema_error`, emits a structured runtime warning, and returns `default`. This produces a `DEGRADED` workflow instead of error routing. A backend/process failure that exhausts retries still raises through `exec_fallback`, preserving node and batch retry behavior.

`llm_usage` always carries the backend's normalized token fields plus `num_turns` and `session_id` when metadata is available. Corrective calls are stored in `llm_usage.retries`; report/trace aggregation includes them without forcing backend-specific fields onto the other backend.

## Why one node

The lifecycle, schema recovery, result storage, trace markers, and workflow interface are genuinely shared. The two adapters are the real variation point. This keeps a future Codex SDK migration internal: replacing the CLI adapter would not require a new node type or workflow migration.

Use `llm` for ordinary text generation through LiteLLM. Use `agent` only when the task needs repository tools and multi-step autonomous work; its side effects, latency, and session lifecycle make it intentionally non-memoized by default.

## Example

````markdown
### implement

- type: agent
- backend: codex
- cwd: .
- sandbox: workspace-write

```yaml output_schema
type: object
properties:
  summary: { type: string }
  files_changed:
    type: array
    items: { type: string }
required: [summary, files_changed]
```

```prompt
Implement the requested change, run the focused tests, and report the files changed.
```
````

## See also

- [Simple nodes](../features/simple-nodes.md)
- [Enhanced interface format](../reference/enhanced-interface-format.md)
- `src/pflow/nodes/agent/` for the implementation boundary
- `src/pflow/guide/nodes/agent.md` for workflow-authoring guidance
