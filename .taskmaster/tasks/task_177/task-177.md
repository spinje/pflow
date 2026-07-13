# Task 177: Unified `agent` Node (claude | codex) Replacing `claude-code`

## Description

Replace the `claude-code` node with a single `agent` node that runs an agentic coding
backend selected by a `backend` parameter (`claude` or `codex`). This is a clean-slate
rename (no alias), consolidating agentic-coding behind one interface so a second backend
(OpenAI Codex) can be added without duplicating ~1600 lines of node scaffolding. The codex
backend drives the `codex exec` CLI, not the beta Python SDK.

## Status

not started

## Priority

medium

## Problem

pflow has exactly one agentic-coding node, `claude-code` (1674 lines,
`src/pflow/nodes/claude/claude_code.py`), tightly wrapping `claude-agent-sdk`. We want to
offer OpenAI Codex as an alternative agent backend. Two shapes were considered and rejected
before landing on this task:

1. **Codex via the MCP node** (`mcp-codex-codex` / `-reply`). Rejected: the MCP `codex-reply`
   resume is *in-memory, process-local* — it only works within a single workflow run and
   fails (`Session not found`) across separate `pflow` invocations, because pflow spawns one
   MCP server process per run and tears it down at the end (verified:
   `src/pflow/mcp/pool.py`, `src/pflow/execution/runner.py:199/239/665`). The MCP path also
   floods stderr with unparseable `codex/event` notifications. Codex-as-agent does not want
   to be modeled as a stateless tool call.

2. **Two sibling nodes** (`claude-code` + a new `codex` node). Rejected: it duplicates the
   lifecycle / param-validation / schema-retry / token-normalization scaffolding. The two
   backends map nearly 1:1 on the core (prompt, model, cwd, structured output, resume-by-id,
   token usage, streaming), so a shared interface is genuinely deep, not forced. This is the
   legitimate "two adapters = one real seam" moment the codebase's own guidance describes.
   (Note: `sandbox` is NOT identical across backends — claude's is a config *dict*
   (`enabled`/`network`/`excludedCommands`/…, an SDK `SandboxSettings` object), codex's is a
   *string mode* (`read-only`/`workspace-write`/`full-access`). It is a backend-specific param, not
   shared — see the param table below. An earlier draft wrongly called the sandbox vocabulary
   identical.)

## Solution

One registered `AgentNode` (registry name `agent`, auto-derived from the class name via
`camel_to_kebab` in `src/pflow/registry/scanner.py:53-65`) that owns everything shared, plus
a small backend protocol with two adapters:

```
AgentNode  (type: agent)              # owns lifecycle, validation, schema coerce/retry,
  ├─ backend: claude | codex          #   output storage, llm_usage normalization
  │
  AgentBackend (protocol)             # run(prompt, opts) -> AgentResult ; resume(id, prompt)
    ├─ ClaudeBackend  → claude-agent-sdk   (existing claude-code logic, moved behind the seam)
    └─ CodexBackend   → `codex exec` CLI subprocess
  AgentResult → normalized onto the existing shared llm_usage contract (src/pflow/core/llm_usage.py)
```

**Param design: FLAT params + per-backend validation** (user ruling during planning; a param
belonging to the other backend is a blocking validation error naming the active backend):

```markdown
### do-the-thing
- type: agent
- backend: codex                       # claude | codex   (required)
- prompt: Diagnose and fix the CI failure
- model: gpt-5.2-codex                 # backend default if omitted (codex inherits its config default)
- cwd: .
- sandbox: workspace-write             # codex: STRING mode. (claude: a DICT — different shape.)
- output_schema: { ... }               # top-level type:object (required by both backends)
- resume: ${prev.llm_usage.session_id} # thread/session id from a prior agent node
- timeout: 300
- use_api_key: false                  # shared: known first-party key paths require explicit true
- approval_policy: never               # codex-only  (claude-only keys here would be rejected)
- add_dir: [../shared]                 # codex-only

# a backend: claude node instead uses claude-shaped params, e.g.:
#   - backend: claude
#   - sandbox: { enabled: true, network: {...} }   # claude: DICT (unchanged from today)
#   - allowed_tools: ["Bash(git:*)"]               # claude-only
#   - max_thinking_tokens: 8000                    # claude-only
```

**Codex backend drives the CLI** (`codex exec`), because the SDK is not ready (see Design
Decisions):
- Run: `codex exec [PROMPT] -m <model> -s <sandbox> -C <cwd> --skip-git-repo-check
  --output-schema <schema.json> -o <last-message-file> --json`
- Resume: `codex exec resume <SESSION_ID> [PROMPT]` — **disk-based**, works across separate
  invocations (reads `~/.codex/sessions/**/rollout-*.jsonl`).
- Auth: account-backed `codex login` by default; known stored/environment API-key paths require the
  shared `use_api_key: true` opt-in. Custom profile/provider/proxy config remains caller-owned.
- Parse `--json` JSONL events for the final message + token usage; normalize to `llm_usage`.

## Design Decisions

- **Clean-slate replace, no alias.** `claude-code` is removed entirely; `agent` is the only
  agentic node. Justified by "no external users yet" (root CLAUDE.md). User chose this over
  aliasing `claude-code` → `agent` + `backend: claude`.

- **Codex backend = CLI (`codex exec`), not the `openai-codex` SDK — for v1.** Verified facts
  driving this (see Verification for evidence):
  - The `openai-codex` SDK is a Python client that spawns a `codex` binary and talks JSON-RPC
    to it. It **bundles its own pinned binary** (`openai-codex-cli-bin==0.132.0`) and drives
    that by default.
  - That bundled 0.132.0 binary is stale: it **cannot parse a current `~/.codex/config.toml`**
    ("invalid type: map") and its **model turns 401** ("Missing bearer") — it does not attach
    the ChatGPT subscription token.
  - The SDK *can* be made to work by overriding `CodexConfig(codex_bin=<system codex 0.144.1>)`
    — subscription turns then succeed — **but** that runs the SDK's client protocol against a
    newer server than it pins (unsupported version combo, fragile under drift).
  - The **CLI (`codex exec`) works cleanly today**: subscription auth, native
    `--output-schema`, disk-based `codex exec resume`, stable public command contract, no
    version-matched protocol to maintain.
  - **This is not "mirror claude-code."** claude-code uses the *SDK* pattern
    (`claude-agent-sdk`, which itself drives an installed `claude` binary). The clean long-term
    end state is a *codex SDK* backend that structurally twins claude-code. We choose the CLI
    for v1 *only* because codex's SDK is beta/immature, and the `AgentBackend` seam makes the
    later swap invisible to `type: agent`.

- **The AgentBackend seam makes SDK-vs-CLI reversible.** The backend choice is an internal
  adapter detail, not part of the public `type: agent` interface. Migrating codex from CLI to
  SDK later requires no workflow changes.

- **FLAT params + per-backend validation** (superseded the earlier nested-escape-hatch idea — user
  ruling during planning; the implementation plan is authoritative). All params flat; a param
  belonging to the other backend is a blocking validation error. Shared (valid for both):
  `prompt`, `model`, `cwd`, `output_schema`, `resume`, `timeout`, `system_prompt`, `schema_retries`,
  `use_api_key`. claude-only: `allowed_tools`, `disallowed_tools`, `max_turns`,
  `max_thinking_tokens`.
  codex-only: `approval_policy`, `add_dir`, `profile`, `config`. **`sandbox` is valid for BOTH but
  backend-shaped** (claude: dict `SandboxSettings`; codex: string mode) — each backend validates its
  own shape. See the implementation plan's "Resolved decisions" for the exact frozenset model.

- **Known first-party API-key paths are opt-in for both backends.** `use_api_key` is a shared strict
  boolean and defaults to `false`. False scrubs the named first-party key variables and, for Codex,
  rejects recognized stored API-key auth before a model call; true permits those paths but does not
  require a key or force a paid request. Claude preserves its existing child-environment key
  scrubbing. Codex also verifies account-backed auth with `codex login status` and pins the OpenAI
  provider selector in safe mode. This guard cannot prove that custom profiles/providers/proxies or
  base URLs are unmetered, and it cannot control account-level purchased credits, auto-reload, or
  plan overage policies; documentation must state the concrete guard rather than promise zero spend.

- **Autonomous by default.** claude-code hardcodes `permission_mode: bypassPermissions`;
  `codex exec` is non-interactive by default (does not prompt). Default codex `approval_policy`
  is `never`; exposed as the codex-only `approval_policy` param for callers who want otherwise.

- **Keep claude-code's structured-output contract for both backends:** native schema (claude
  SDK `output_format: json_schema`; codex `--output-schema`), top-level `type: object`
  constraint, and **soft-fail** on non-conforming output (fall back to raw text in `result`,
  set `_schema_error`, emit `__warnings__[node_id]` → DEGRADED status; do NOT route `on-error`).
  Preserve the scalar-coercion + resume-and-retry loop (`schema_retries`).

- **Preserve the output contract that pflow special-cases key off** (see Requirements →
  Behavioral parity). Both backends must write `shared["result"]` and a `llm_usage` dict that
  includes `num_turns`, `session_id`, and (when retries happen) `retries` — these drive trace
  rendering and are matched by *field presence*, not node-type string.

## Dependencies

None hard. Related planned tasks that reference this node and should be re-scoped to `agent`
after this lands:
- Task 99: Expose pflow Tools to Claude Code Node — explicitly scoped to this node.
- Task 163 harness examples (`examples/agent-orchestration/**`) use `type: claude-code` and
  must migrate.

## Requirements

### Node interface
- Register node type `agent` (auto-derived from `AgentNode`). `claude-code` no longer resolves.
- Required `prompt`; required `backend` ∈ {`claude`, `codex`}.
- Shared params accepted for both backends: `model`, `cwd`, `output_schema`, `resume`, `timeout`,
  `system_prompt`, `schema_retries`, `use_api_key` (strict bool; default `false`).
- `sandbox` is accepted for both backends but is **backend-shaped**: claude expects a config dict
  (`enabled`/`network`/`excludedCommands`/… — unchanged from today's node), codex expects a string
  mode (`read-only`|`workspace-write`|`full-access`). Each backend validates its own shape.
- FLAT params: a key valid only for the *other* backend is a blocking validation error naming the
  active backend and the offending key (no nested `claude:`/`codex:` maps).
- Backend-specific default `model` when omitted (claude: `claude-sonnet-4-5`; codex: a chosen
  default, e.g. `gpt-5.2-codex` — CONFIRM value at implementation time).

### Codex (CLI) backend
- Runs `codex exec` with prompt, `-m/-s/-C`, `--skip-git-repo-check`, and `--output-schema`
  when a schema is set; captures the final message via `-o <file>` and/or `--json`.
- With `use_api_key: false` or omitted, removes ambient `CODEX_API_KEY`/`OPENAI_API_KEY` from a
  child-only environment, runs `codex login status` with that same environment, and proceeds only
  for recognized ChatGPT/account access-token auth. API-key, personal-token, Bedrock, logged-out,
  and unknown status results fail closed before `codex exec`. Safe mode appends
  `model_provider="openai"` after user config/profile selectors. This closes the ordinary alternate
  provider path but does not claim to sandbox an explicitly customized proxy/base URL. It must not
  use `forced_login_method`, which can log the user out when credentials mismatch.
- With `use_api_key: true`, preserves the environment and configured provider without requiring a
  particular auth mode. This is the explicit permission boundary for API-key/provider billing;
  pflow never logs in, stores credentials, or performs a paid probe on the user's behalf.
- If Codex is not installed or account auth is unavailable in safe mode, produce a non-retriable,
  actionable error naming `codex login` / `codex login status`; never expose raw status output.
- `resume: <session_id>` runs `codex exec resume <session_id> <prompt>` and continues the
  prior thread across separate workflow runs.
- Normalizes codex token usage
  (`cached_input_tokens`/`input_tokens`/`output_tokens`/`reasoning_output_tokens`/`total_tokens`)
  onto the shared `llm_usage` contract, and emits `num_turns` + `session_id`.
- Enforces the `timeout` (subprocess-level).

### Claude backend
- Behaviorally identical to today's `claude-code` node (the existing logic, moved behind
  `ClaudeBackend`). No regression in params, structured output, resume, token accounting, or
  auth. `use_api_key: false` continues to scrub `ANTHROPIC_API_KEY` from only the child process;
  true permits the existing API-key behavior.

### Behavioral parity (special-cases the new node must replicate)
- **Validator schema preflight**: rekey the `node_type == "claude-code"` dispatch
  (`validator.py:816`) to `"agent"`; keep the top-level `type: object` schema rule and param
  checks (`_validate_claude_code_params` → rename).
- **react_flow renderer**: rekey `node.kind == "claude-code"` (`react_flow.py:282`) to
  `"agent"` so structured output maps to the `result` output port. Rebuild the UI bundle from
  source (do not hand-edit `src/pflow/ui/static/assets/*.js`).
- **Cache-metadata exclusion**: agent stays excluded from trace-2.1.0 memo cache_key/source
  (gate is `LLMNode`-only at `instrumentation.py:300` — auto-excluded; preserve the intent).
- **Agentic trace markers**: keep emitting `num_turns`/`session_id`/`retries` in `llm_usage`
  so `workflow_trace.py:351` and `trace_report.py` render agent calls correctly.
- **LLM-node classification for dry-run/plan**: add `AgentNode` where `ClaudeCodeNode` sat
  (`execution/plan.py:71`, `plan_formatter.py:374`) so cost/duration estimates still apply.
- **Display / catalog / guide / save-allowlist**: update `node_type_display.py:10`,
  `context_builder.py:608`, `guide/__init__.py:40`, `save_service.py:51`.

### Clean-slate migration (no `claude-code` references remain in shipped code/guide/docs/examples)
- All code sites hard-coding `"claude-code"`/`"ClaudeCodeNode"` updated (exhaustive list in the
  migration checklist — see References).
- All example workflows migrated (`examples/nodes/claude-code/**`,
  `examples/agent-orchestration/**` Task 163 harness) to `type: agent` + `backend: claude`.
- Guide content renamed (`src/pflow/guide/nodes/claude-code.md` → `agent.md`; filename drives
  topic name) and cross-references updated.
- User docs (`docs/reference/nodes/claude-code.mdx` → renamed; nav in `docs/docs.json`) updated.
- Tests migrated (`tests/test_nodes/test_claude/**` → `test_agent/**`, plus renderer/trace/
  parser/validator/cli/integration tests listed in the checklist).

## Implementation Notes

- **Registry name is automatic**: `ClaudeCodeNode` → `AgentNode` yields `agent` with no
  explicit `name` attr. But ~15 hard-coded string sites must change by hand (see checklist).
- **Start by extracting the seam**: move the existing claude-code implementation behind a
  `ClaudeBackend` implementing the `AgentBackend` protocol, keeping all tests green, *before*
  adding `CodexBackend`. Extract only the genuinely shared skeleton into `AgentNode`; resist
  pulling backend-specific logic (SDK message types, codex JSONL parsing, auth heuristics,
  token normalization) up — those stay in the adapters.
- **Codex CLI surface** (`codex exec --help`): `-m/--model`, `-s/--sandbox`
  (`read-only`|`workspace-write`|`danger-full-access`), `-C/--cd`, `--add-dir`,
  `--output-schema <FILE>`, `-o/--output-last-message <FILE>`, `--json`, `--skip-git-repo-check`,
  `-c key=value` config overrides. Resume: `codex exec resume [SESSION_ID] [PROMPT]` (or
  `--last`). Note codex's `full-access` maps to the CLI's `danger-full-access`.
- **Token normalization**: codex `TokenUsageBreakdown` has
  `cached_input_tokens`/`input_tokens`/`output_tokens`/`reasoning_output_tokens`/`total_tokens`.
  Map `cached_input_tokens` → cache-read; carry `reasoning_output_tokens` (codex-specific) into
  `llm_usage` without breaking the shared contract used by `LLMNode`.

### Open items to resolve during implementation (do not block the spec)
- **Batch-retry special-casing**: `guide/features/batch.md:208` claims `claude-code` gets
  http-like batch retry behavior. NOT verified in `runtime/engine/batch_executor.py` — confirm
  whether it's type-keyed and whether `agent` should inherit it.
- **UI source**: the compiled bundle references `claude-code`; locate the TS/JS source in
  `src/pflow/ui/` (mirrors the react_flow `kind` logic) and rebuild rather than editing the
  bundle.
- **Codex `--output-schema` object constraint**: confirm codex accepts / requires top-level
  `type: object` schemas (claude does, due to tool-input wrapping). Keep the shared rule unless
  codex diverges.
- **Codex default model** value.
- **SDK backend (future, not this task)**: `openai-codex` becomes a swappable `CodexSdkBackend`
  once its bundled binary is current and does subscription turns out-of-box. Richer objects
  (`TurnResult`, streaming `Notification`s, thread handles) then make codex a structural twin
  of claude-code.

## Verification

Evidence already gathered in the originating session (2026-07-13):
- `codex exec --sandbox read-only "Reply with ONLY the word BANANA."` → `BANANA`, exit 0, on
  ChatGPT subscription auth (no API key present: `~/.codex/auth.json` has
  `OPENAI_API_KEY: null`, ChatGPT OAuth tokens only).
- Codex persists sessions to disk (`~/.codex/sessions/**/rollout-*.jsonl`); `codex exec resume
  <id>` is the disk-based cross-process resume path.
- `codex exec --output-schema <FILE>` exists for structured output.
- MCP-node resume fails across `pflow probe` invocations (`Session not found`) — the reason the
  MCP path was rejected.
- SDK immaturity confirmed: `openai-codex==0.1.0b2` bundles `codex 0.132.0`; default run 401s
  ("Missing bearer") and fails to parse current config.toml; only
  `CodexConfig(codex_bin=<system 0.144.1>)` makes turns succeed (unsupported version combo).

Acceptance scenarios to implement:
- `type: agent` + `backend: claude` reproduces every existing `claude-code` test (moved to
  `test_agent/`), green with no behavior change.
- `type: agent` + `backend: codex` runs a real `codex exec` turn, returns text in `result`,
  and populates `llm_usage` with token fields + `num_turns` + `session_id`.
- Codex structured output: `output_schema` set → `result` is the parsed object; malformed
  output soft-fails to DEGRADED with `_schema_error` (parity with claude backend).
- Codex resume across two separate workflow runs: run A creates a thread and emits
  `session_id`; run B passes `resume: <that id>` and the agent continues the same thread
  (recalls prior context).
- `backend: codex` with omitted/false `use_api_key` and ChatGPT/account-token auth performs
  `codex login status` then runs with API-key variables removed only from the child environment.
- The same safe mode rejects API-key, personal-token, Bedrock, logged-out, and unknown status
  results exactly once and before any `codex exec`; errors are non-retriable and never include the
  CLI's raw/masked credential output.
- `backend: codex` with `use_api_key: true` skips the account-auth guard and preserves the caller's
  environment/provider configuration. No paid API-key end-to-end test is required.
- Cross-backend param validation: a claude-only param (e.g. `max_thinking_tokens`) under
  `backend: codex` (or vice versa) is a blocking validation error naming the active backend.
- Repo-wide: no shipped code/guide/docs/example references `claude-code`; `pflow guide agent`
  works; example workflows validate; `make test` and `make check` green (capture baseline
  first per CLAUDE.md).

## References

- Existing node (becomes `ClaudeBackend`): `src/pflow/nodes/claude/claude_code.py` (1674 lines)
- Shared schema predicates: `src/pflow/nodes/claude/schema_validation.py`
- Structured-output prior art: Task 126 (`.taskmaster/tasks/task_126/`)
- Resume prior art: Task 164 (`.taskmaster/tasks/task_164/`); resume CLI: `tests/test_cli/test_resume_cli.py`
- llm_usage contract: `src/pflow/core/llm_usage.py`
- Validator dispatch: `src/pflow/core/workflow/validator.py:816-991`
- react_flow renderer: `src/pflow/core/workflow/graph/renderers/react_flow.py:280-284`
- Trace markers: `src/pflow/runtime/workflow_trace.py:351`, `src/pflow/core/trace_report.py:345-925`
- Registry name derivation: `src/pflow/registry/scanner.py:53-65`
- MCP-pool lifecycle (why MCP path rejected): `src/pflow/mcp/pool.py`,
  `src/pflow/execution/runner.py:199/239/665`
- Codex CLI: `codex exec --help`, `codex exec resume --help`
- Codex Python SDK (future backend): `openai-codex` (PyPI, beta),
  https://developers.openai.com/codex/sdk , https://github.com/openai/codex/tree/main/sdk/python
- Full migration checklist (exhaustive `claude-code` touchpoints + 8 behavioral special-cases):
  captured in the originating session; regenerate with a repo-wide search for
  `claude-code` / `claude_code` / `ClaudeCodeNode` if needed.
