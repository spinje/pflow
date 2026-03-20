# CLI Module

Command-line interface for pflow. Uses a pre-parsing wrapper pattern to handle the conflict between Click's subcommand routing and catch-all workflow arguments.

## Architecture

```
Entry Point (main_wrapper.cli_main)
    ↓
Routing Decision (pre-parses sys.argv, first non-option arg)
    ├─→ workflow_command (default — file path, saved name, or natural language)
    ├─→ mcp (MCP server management)
    ├─→ registry (node registry and execution)
    ├─→ workflow (saved workflow management)
    ├─→ skill (publish workflows as AI agent skills)
    ├─→ settings (configuration)
    ├─→ instructions (agent guidance)
    └─→ read-fields (retrieve fields from cached executions)
```

**Why the wrapper exists**: Click can't handle both `@click.argument("workflow", nargs=-1)` and subcommands in the same group. `main_wrapper.py` detects known subcommands BEFORE Click processes arguments.

## File Structure

```
src/pflow/cli/
├── __init__.py              # Exports cli_main
├── main_wrapper.py          # Entry point router (pre-parses sys.argv)
├── main.py                  # Workflow command orchestration (~1570 lines)
├── param_parsing.py         # Parameter parsing (infer_type, parse_workflow_params, format_param_value)
├── workflow_resolution.py   # Workflow file/name resolution (resolve_workflow, is_likely_workflow_name)
├── mcp_sync.py              # MCP auto-discovery at startup (_auto_discover_mcp_servers)
├── workflow_output.py       # Output detection, display, formatting (26 functions)
├── workflow_errors.py       # Error display and formatting (9 functions, imports from workflow_output)
├── cli_output.py            # OutputInterface implementation for Click
├── rerun_display.py         # Rerun command display with secret masking
├── discovery_errors.py      # Shared error handling for LLM discovery
├── logging_config.py        # CLI logging configuration
├── resources/               # CLI resources (agent instruction markdown files)
└── commands/
    ├── __init__.py          # Package marker
    ├── instructions.py      # Agent instruction generation
    ├── mcp.py               # MCP server management commands
    ├── read_fields.py       # Retrieve fields from cached registry run results
    ├── registry.py          # Node registry commands (~586 lines)
    ├── registry_run.py      # Single node execution (pflow registry run)
    ├── settings.py          # Settings management (nodes, env, LLM models, registry)
    ├── skills.py            # Skill publishing commands (save/list/remove)
    └── workflow.py          # Saved workflow commands
```

## Core CLI (main.py)

### Startup Sequence

```
workflow_command()                        (main.py)
    ↓ _setup_signals()                    (main.py)
    ↓ _inject_settings_env_vars()         (main.py) ← injects API keys into os.environ
    ↓ _initialize_context()               (main.py)
    ↓ _auto_discover_mcp_servers()        (mcp_sync.py) ← smart sync (skips if config unchanged)
    ↓ _read_stdin_data()                  (main.py)
    ↓ _try_execute_named_workflow()       (main.py) → resolve_workflow (workflow_resolution.py)
```

The env injection step is critical — it makes API keys stored via `pflow settings set-env` available to the `llm` library and other tools that read `os.environ`. Skipped in test environment.

### Command Flags

```
--version              # Show version
--verbose, -v          # Detailed output (shows shell stderr, error details)
--output-key, -o       # Extract specific shared store key instead of auto-detection
--output-format        # "text" (default) or "json" — json forces non-interactive
--print, -p            # Force non-interactive, clean output for piping
--no-trace             # Disable automatic workflow trace saving
--validate-only        # Validate without executing (exit 0/1), auto-normalizes IR
workflow (nargs=-1)    # Catch-all: file path, saved name, or natural language
```

### Workflow Name Detection

`is_likely_workflow_name()` (in `workflow_resolution.py`) determines whether input is a file path or saved workflow name. Heuristics:
- Has file extension (`.pflow.md`, `.json`, `.md`) or path separators → file path
- Followed by `key=value` args → workflow name with params
- Contains hyphens (kebab-case) → likely workflow name
- Single word without params → not treated as workflow name (prevents false positives)

Also: `pflow run my-workflow` silently strips the `run` prefix (`_preprocess_run_prefix`).

### Workflow Resolution Priority

1. Check if valid file path (`.pflow.md`; `.json` → rejection error directing to markdown)
2. Try loading from WorkflowManager (saved name)
3. Error

### Output Streams

- Progress/warnings → **stderr** (`err=True`)
- Results → **stdout** (safe for piping)

This split is critical: piping `pflow workflow.pflow.md | jq` works because progress noise goes to stderr. `BrokenPipeError` handled via `os._exit(0)` for clean pipe termination.

### Interactive Mode Impact

Interactive detection rules are in `core/CLAUDE.md` (output_controller). CLI-specific impacts:
- Progress display: only in interactive
- Save prompts: auto-save in non-interactive
- Warning messages: suppressed in non-interactive
- Trace file paths: only shown in interactive

### Parameter Handling

**Type inference** (`infer_type` in `param_parsing.py`):
- `"true"/"false"` → `True/False` (case-insensitive)
- No decimal/scientific notation → `int`
- Has decimal or `e` → `float`
- Starts with `[` or `{` → parsed as JSON list/dict
- Everything else → `str`

**Internal parameters**: `__` prefixed params are system-internal, filtered from display by `filter_user_params()`. Includes `__verbose__`, `__llm_calls__`.

**Sensitive parameter masking**: 15 predefined sensitive keys auto-masked as `<REDACTED>` in rerun display. Shell injection protection via `shlex.quote()`.

### Trace File System

- Workflow: `~/.pflow/debug/workflow-trace-{name}-{YYYYMMDD-HHMMSS}.json` — saved automatically (disable with `--no-trace`)

### Error Display

Error categories with different handlers: `UserFriendlyError`, `CompilationError`, generic exceptions.

Shell error details (verbose mode): shows command, stdout, stderr with truncation (200/300/300 chars).

JSON errors include structured execution state: per-node status (completed/failed/not_executed), duration, cached.

### Context (`ctx.obj`) — Non-Obvious Keys

- `workflow_source`: `"file"`, `"saved"`, or `None` — **gates whether metadata updates happen**
- `workflow_name`: derived from filename (file) or save name (saved), used for traces/display
- Full list of keys readable in `main.py` `_initialize_context` function.

## Component Details

### MCP Commands (commands/mcp.py)

Subcommands: `add`, `list`, `sync`, `remove`, `tools`, `info`, `serve`.

**Smart auto-discovery**: Runs at pflow startup on every command. Only syncs when config modified or servers changed — uses file mtime and server hash for detection. Saves ~500ms on warm starts.

**Universal MCPNode pattern**: Single `MCPNode` class handles ALL MCP tools. Virtual registry entries point to same node class. Server/tool injected via `__mcp_server__` and `__mcp_tool__` params.

**MCP connection pooling**: Server sessions are kept alive across workflow steps via `MCPConnectionPool` (shared store key `__mcp_pool__`). Pool is created by `executor_service.py` and shut down in its `finally` block.

### Registry Commands (commands/registry.py)

Subcommands: `list` (with optional filter pattern), `describe`, `scan`, `discover` (LLM-powered), `run`.

Note: there is no separate `search` subcommand — `pflow registry list <pattern>` handles search with relevance-sorted results.

**MCP tool normalization** (3-tier matching for `describe`/`run`):
1. Exact match: `mcp-slack-composio-SLACK_SEND_MESSAGE`
2. Hyphen/underscore conversion: `SLACK-SEND-MESSAGE` → `SLACK_SEND_MESSAGE`
3. Short form: `SLACK_SEND_MESSAGE` → searches for unique tool with this suffix

Ambiguity detected → shows all matching full IDs with guidance.

**Cross-module dependency**: `describe` uses `build_component_context()` from `pflow.registry.context_builder` to produce detailed node output.

### Execution Caching Pipeline (commands/registry_run.py + commands/read_fields.py)

```
pflow registry run <node> params...
    ↓ executes node
    ↓ ExecutionCache.store(execution_id, outputs)
    ↓ displays results with execution_id

pflow read-fields <execution_id> <field_paths>...
    ↓ ExecutionCache.retrieve(execution_id)
    ↓ TemplateResolver.resolve_value(field_path, outputs)
    ↓ displays specific field values
```

This two-command pipeline allows agents to run a node once, then extract specific fields without re-execution. Output display mode controlled by `settings.registry.output_mode` ("smart"/"structure"/"full").

### Workflow Commands (commands/workflow.py)

Subcommands: `list` (with optional filter), `describe`, `history`, `discover` (LLM-powered), `save`.

**Workflow save**:
- Name validation: lowercase, numbers, hyphens only, max 30 chars (shell/URL/git-safe)
- Description extracted from markdown H1 prose (`--description` flag removed)
- `--delete-draft` safety check: only works in `.pflow/workflows/`, resolves symlinks, refuses to delete symlinked files
**Workflow history** (`pflow workflow history <name>`): Shows execution history and last used inputs — useful for finding previously used parameter values.

**Discovery commands use plain functions** — `discover_workflow()` from `core/workflow/discovery` and `discover_components()` from `registry/discovery`. Both return typed dataclasses (`WorkflowMatch`, `ComponentSelection`).

### Skill Commands (commands/skills.py)

Subcommands: `save`, `list`, `remove`.

Skills are **symlinks** from tool-specific directories to saved workflows in `~/.pflow/workflows/`. The saved workflow is the single source of truth.

**Multi-tool targets**: Claude Code (default), Cursor (`--cursor`), Codex (`--codex`), Copilot (`--copilot`). Can combine multiple flags.

**Scope**: `--personal` for personal skills (`~/` dirs) vs project scope (project-relative dirs, default).

**Enrichment**: `save` adds a `## Usage` section to the workflow file (idempotent — replaces existing).

**Broken link detection**: `list` detects and reports broken symlinks with fix/remove guidance.

### Instructions Commands (commands/instructions.py)

- `pflow instructions usage` — basic usage guide (~166 lines)
- `pflow instructions create` — comprehensive workflow creation guide (~1650 lines)
  - `--part 1` Foundation & Mental Model (~550 lines)
  - `--part 2` Building Workflows (~550 lines)
  - `--part 3` Testing & Reference (~550 lines)
  - Without `--part`: shows full content

AI agents should run `pflow instructions usage` when first connecting to pflow.

### Settings Commands (commands/settings.py)

**Node filtering**: `init`, `show`, `allow`, `deny`, `remove`, `check`, `reset`.
Node filtering priority: Test policy → Deny → Allow → Default. See `core/CLAUDE.md` for details.

**Environment variables**: `set-env`, `unset-env`, `list-env`.
Stores API keys in `~/.pflow/settings.json`. Injected into `os.environ` at CLI startup (`_inject_settings_env_vars`), making them available to the `llm` library.

**LLM model settings** (`settings llm` subgroup): `show`, `set-default`, `set-discovery`, `set-filtering`, `unset`.

LLM model resolution chain (genuinely hard to discover):
- `default`: workflow params → `default_model` setting → `llm` CLI default → error
- `discovery`: `discovery_model` → `default_model` → auto-detect → fallback (`anthropic/claude-sonnet-4-5`)
- `filtering`: `filtering_model` → `default_model` → auto-detect → fallback

**Registry settings** (`settings registry` subgroup): `output-mode` (smart/structure/full).

### CLI Output (cli_output.py)

`CliOutput` implements `OutputInterface`, wraps `OutputController`. Delegates interactive detection, creates progress callbacks.

## Shared Formatters

CLI uses formatters from `execution/formatters/` for output consistency with MCP server:
- `main.py`: `success_formatter`, `error_formatter`, `validation_formatter`
- `commands/registry.py`: `registry_list_formatter`, `registry_search_formatter`
- `commands/registry_run.py`: `node_output_formatter`, `registry_run_formatter`
- `commands/workflow.py`: `workflow_list_formatter`, `workflow_describe_formatter`, `discovery_formatter`, `workflow_save_formatter`, `history_formatter`

## Validate-Only Mode

What `--validate-only` checks (and doesn't):
- ✅ Schema compliance, data flow correctness, template structure, node types in registry
- ❌ Runtime values, API credentials, file existence

**Auto-normalization**: Adds `ir_version: "0.1.0"` if missing, `edges: []` if no connections. Reduces friction for agent-generated workflows. Same normalization applied during `workflow save`.

## Stdin Handling

See `core/CLAUDE.md` (shell_integration section) for FIFO detection, StdinData modes, and routing details. Key CLI-specific behavior: validation happens AFTER stdin routing, so required inputs can be satisfied by piped data.

## Signal Handling

- Ctrl+C: exit code 130, no cleanup (relies on finally blocks)
- SIGPIPE: set to default for shell compatibility (prevents broken pipe errors)
- Resource cleanup: `_cleanup_workflow_resources()` handles LLM interception cleanup, temp file deletion. Never raises.

## Common Usage

```bash
# File-based execution
pflow workflow.pflow.md param1=value1

# Saved workflow
pflow github-analyzer repo=spinje/pflow

# Subcommands
pflow mcp add ./github.mcp.json
pflow mcp serve                        # Run as MCP server (stdio)
pflow registry list
pflow registry run shell command="echo hi"
pflow registry run read-file file_path=/tmp/test.txt
pflow read-fields exec-123-abc result[0].title  # Read cached fields
pflow workflow describe my-workflow
pflow workflow history my-workflow      # Show execution history
pflow skill save my-workflow            # Publish as AI skill
pflow skill list                        # List published skills
pflow settings set-env ANTHROPIC_API_KEY sk-... # Store API key
pflow settings llm show                 # Show LLM model config
pflow instructions usage                # Agent guide
```

## Known Issues

1. **MCP connection cleanup** — handled by `MCPConnectionPool.shutdown()` in `executor_service.py` finally block; `pflow registry run` still creates ephemeral connections
2. **Click testing limitation** — `CliRunner` always returns `False` for `isatty()`, preventing interactive mode testing in unit tests
3. **Registry format inconsistency** — two save methods create format confusion, pattern matching checks multiple fields

## Gotchas for Developers

- **Don't combine catch-all args with subcommands** — the wrapper pattern exists because Click can't handle this. Respect it.
- **Don't import execution module in `__init__.py`** — use lazy imports to avoid circular dependencies
- **Don't mix output streams** — errors→stderr, results→stdout. This is what makes piping work.
- **Don't assume TTY** — always check interactive mode before showing progress or prompts
- **`describe` depends on registry/context_builder** — `registry describe` imports `build_component_context` from `pflow.registry.context_builder`.

## Testing

Key mock points: `execute_workflow()`, `click.prompt()`, `WorkflowManager`.

**TTY limitation**: Click's `CliRunner.isatty()` always returns False — can't test interactive mode paths in unit tests.
