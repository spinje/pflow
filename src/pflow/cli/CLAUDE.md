# CLI Module

Command-line interface for pflow. Uses a pre-parsing wrapper pattern because Click can't handle both a catch-all argument and subcommands in the same group.

## Architecture

```
Entry Point (main_wrapper.cli_main)
    ↓
Routing Table (pre-parses sys.argv, first non-option arg)
    ├─→ workflow_command (default — file path, saved name)
    ├─→ mcp, registry, workflow, skill, settings, instructions, read-fields
    ↓
workflow_command (main.py) ← the default path
    ↓ _setup_signals, _inject_settings_env_vars, _initialize_context
    ↓ _auto_discover_mcp_servers (mcp_sync.py)
    ↓ _read_stdin_data, _validate_workflow_flags
    ↓ _try_execute_named_workflow
        ↓ is_likely_workflow_name (workflow_resolution.py)
        ↓ resolve_workflow (workflow_resolution.py)
        ↓ _validate_and_prepare_workflow_params
            ↓ parse_workflow_params (param_parsing.py)
            ↓ _route_stdin_to_params
        ↓ execute_json_workflow
            ↓ _validate_before_execution
            ↓ execute_workflow() (from pflow.execution)
            ↓ _execute_workflow_and_handle_result
                ├─→ _handle_workflow_success → _handle_workflow_output (workflow_output.py)
                └─→ _handle_workflow_error → _display_text_error_details (workflow_errors.py)
```

**Why the wrapper exists**: Click can't handle both `@click.argument("workflow", nargs=-1)` and subcommands in the same group. `main_wrapper.py` detects known subcommands BEFORE Click processes arguments. Adding a new subcommand: add to the `subcommand_routes` dict in `main_wrapper.py` and import the handler.

## File Structure

```
src/pflow/cli/
├── main_wrapper.py          # Entry point: routing table + _route_subcommand helper
├── main.py                  # Workflow execution orchestration (see "main.py" section below)
├── workflow_output.py       # Output detection, display, execution summaries
├── workflow_errors.py       # Error display and JSON error construction
├── workflow_resolution.py   # File/name → IR resolution (resolve_workflow, is_likely_workflow_name)
├── mcp_sync.py              # MCP auto-discovery at startup
├── param_parsing.py         # infer_type, parse_workflow_params, format_param_value
├── cli_output.py            # CliOutput: OutputInterface implementation for Click
├── rerun_display.py         # Rerun command display with secret masking
├── discovery_errors.py      # Shared error handling for LLM discovery commands
├── logging_config.py        # CLI logging configuration
├── commands/                # All command groups (see commands/CLAUDE.md)
│   ├── mcp.py, registry.py, registry_run.py, read_fields.py
│   ├── workflow.py, skills.py, settings.py, instructions.py
│   └── CLAUDE.md
└── resources/               # Agent instruction markdown files
```

## Dependency Graph

```
param_parsing.py           (leaf — stdlib only)
workflow_resolution.py     (leaf — core/ only)
mcp_sync.py                (leaf — mcp/, registry/ only)
workflow_output.py          (leaf — core/, execution/ only)
    ↑
workflow_errors.py          (imports _serialize_json_result, metadata helpers from workflow_output)
    ↑
main.py                    (orchestrator — imports from all 5 modules above)
    ↑
main_wrapper.py            (entry point — imports workflow_command from main.py)
```

## main.py: Orchestration Layer

Contains the Click command definition (`workflow_command`) and everything that coordinates the execution pipeline. The functions here share dependencies on `_echo_trace` (trace display) and `ctx` (Click context), which is why they live together — they form a single orchestration flow from command entry to result display.

**What's here**:
- The Click command and its startup sequence (signals, env injection, context init)
- Execution pipeline: `execute_json_workflow` → prepare → validate → execute → handle result
- Success/error routing: dispatches to `workflow_output` or `workflow_errors`, then handles trace saving and exit codes
- Validation: static workflow validation, validate-only mode
- Stdin routing: detects piped input, routes to workflow inputs marked `stdin: true`
- Named workflow handling: parameter preparation, workflow help display

**If you need to extract more from main.py**: Functions that call `_echo_trace` or `ctx.exit()` can't move to `workflow_output.py` or `workflow_errors.py` without creating circular imports. Those modules import from each other but never back to main.py.

## Output Behavior

### Output Streams

- Progress/warnings → **stderr** (`err=True`)
- Results → **stdout** (safe for piping)

This split is critical: `pflow workflow.pflow.md | jq` works because progress noise goes to stderr. `BrokenPipeError` handled via `os._exit(0)` for clean pipe termination.

### Three Output Modes (`_output_with_header` in workflow_output.py)

| Mode | When | Header | Data | Summary |
|------|------|--------|------|---------|
| `--print` (`-p`) | Explicitly requested | None | stdout | None |
| Interactive | TTY detected | stderr | stdout | stderr |
| Non-interactive | CI/CD, agents, pipes | stderr | stderr | stderr |

Non-interactive sends data to stderr too — this prevents output appearing before summary when tools capture streams separately.

### Output Auto-Detection (`_find_auto_output` in workflow_output.py)

When no `--output-key` is specified and no outputs are declared in the workflow, auto-detection searches for output in priority order:

**Priority**: response > output > result > text > stdout

Searches namespaced storage first (each node's namespace dict), then direct storage keys. Returns the **last** occurrence of the highest priority key (so in sequential workflows, the final node's output wins).

### JSON/Text Duality

Almost every output and error function has parallel JSON and text code paths. The `--output-format json` flag gates which path executes. JSON mode also suppresses all logging below ERROR level to prevent stdout contamination.

## workflow_output.py

Three responsibilities:

1. **Output routing**: `_handle_workflow_output` → `_handle_text_output` / `_handle_json_output`. Checks user-specified key, then declared outputs, then auto-detection.
2. **Execution summary**: `_display_execution_summary` with per-node timing, cache/batch/stderr tags, LLM cost display, and warnings. Always shown except in `--print` mode.
3. **Shared utilities**: `safe_output` (BrokenPipeError handling), `_serialize_json_result` (JSON serialization), `_create_workflow_metadata`. These are also imported by `workflow_errors.py`.

## workflow_errors.py

Three error categories with different display:

1. **Execution errors** (`_display_text_error_details` → `_display_single_error`): Per-error with node ID, category, message. Special handling for API responses, MCP errors, template errors (shows available fields), shell errors (command/stdout/stderr in verbose mode). Security: sanitizes raw responses via `sanitize_parameters`.
2. **Compilation errors** (`_format_compilation_error_text`, `_handle_compilation_error_json`): UserFriendlyError formatting or generic message with suggestion.
3. **JSON error construction** (`_create_json_error_output`, `_build_json_error_response`): Structured error output with execution state, metrics, and cost.

## Workflow Resolution (workflow_resolution.py)

`resolve_workflow(identifier)` resolves user input to workflow IR:
1. Path detection (`_is_path_like`): file separators or `.pflow.md`/`.json`/`.md` extension
2. File loading (`_try_load_workflow_from_file`): parse markdown, normalize IR. `.json` → rejection with migration message.
3. Registry lookup (`_try_load_workflow_from_registry`): exact name, then strip `.pflow.md` extension and retry.

`is_likely_workflow_name(text, remaining_args)` heuristics:
- Has file extension or path separators → file path
- Followed by `key=value` args → workflow name with params
- Contains hyphens (kebab-case) → likely workflow name
- Single word without params → NOT treated as workflow name (prevents false positives)

Also: `pflow run my-workflow` silently strips the `run` prefix (`_preprocess_run_prefix` in main.py).

Note: The MCP server has its own independent `resolve_workflow` in `mcp_server/utils/resolver.py` with a different signature. They share no code.

## Parameter Handling (param_parsing.py)

**Type inference** (`infer_type`):
- `"true"/"false"` → `True/False` (case-insensitive)
- No decimal/scientific notation → `int`
- Has decimal or `e` → `float`
- Starts with `[` or `{` → parsed as JSON list/dict
- Everything else → `str`

**Reverse conversion** (`format_param_value`): Converts Python values back to CLI strings. Co-located with `infer_type` because they are inverses — `format_param_value(infer_type(s)) == s` for round-trippable values.

**Internal parameters**: `__` prefixed params are system-internal, filtered from display by `filter_user_params()` (in `rerun_display.py`). Includes `__verbose__`, `__llm_calls__`.

**Sensitive parameter masking**: 15 predefined sensitive keys auto-masked as `<REDACTED>` in rerun display. Shell injection protection via `shlex.quote()`.

## MCP Auto-Discovery (mcp_sync.py)

Runs at startup on every `pflow` invocation. Smart skip: checks MCP config file mtime + SHA-256 hash of server list against stored metadata. Only re-syncs when config actually changed.

Note: has its own copy of `_get_output_controller` (duplicated from main.py to avoid circular imports).

## Command Flags

```
--version              # Show version
--verbose, -v          # Detailed output (shows shell stderr, error details)
--output-key, -o       # Extract specific shared store key instead of auto-detection
--output-format        # "text" (default) or "json" — json forces non-interactive
--print, -p            # Force non-interactive, clean output for piping
--no-trace             # Disable automatic workflow trace saving
--validate-only        # Validate without executing (exit 0/1), auto-normalizes IR
workflow (nargs=-1)    # Catch-all: file path, saved name
```

## Context (`ctx.obj`) — Non-Obvious Keys

Most keys are straightforward (`verbose`, `output_format`, `print_flag`, `trace`, `validate_only`). These are the ones that are hard to discover or have surprising behavior:

| Key | Notes |
|-----|-------|
| `output_controller` | `OutputController` instance — created once, reused by `_echo_trace` and output handling |
| `workflow_source` | `"file"`, `"saved"`, or `None` — gates whether WorkflowManager is passed to execution |
| `source_file_path` | Set for file and saved workflows — used for relative path resolution in nested workflows |
| `workflow_metadata` | Action field: `"reused"` (saved) or `"unsaved"` (file) — drives execution summary display |
| `workflow_trace` | `WorkflowTraceCollector` — set during `_prepare_execution_environment`, not at context init |

Full list readable in `_initialize_context` and `_setup_workflow_execution` in main.py.

## Validate-Only Mode

What `--validate-only` checks (and doesn't):
- Checks: schema compliance, data flow, template structure, node types in registry
- Does NOT check: runtime values, API credentials, file existence

**Auto-normalization**: Adds `ir_version: "0.1.0"` if missing, `edges: []` if no connections. Same normalization applied during `workflow save`.

## Stdin Handling

See `core/CLAUDE.md` (shell_integration section) for FIFO detection, StdinData modes, and routing. Key CLI-specific behavior: validation happens AFTER stdin routing, so required inputs can be satisfied by piped data.

## Trace and Signal Handling

- Traces: `~/.pflow/debug/workflow-trace-{name}-{YYYYMMDD-HHMMSS}.json` — saved automatically (disable with `--no-trace`)
- Ctrl+C: exit code 130, no cleanup (relies on finally blocks)
- SIGPIPE: set to SIG_IGN (prevents subprocess SIGPIPE from killing parent process)
- Resource cleanup: `_cleanup_workflow_resources()` handles LLM interception cleanup, temp file deletion. Never raises.

## Shared Formatters

CLI uses formatters from `execution/formatters/` for output consistency with MCP server:
- `main.py`: `success_formatter`, `error_formatter`, `validation_formatter`
- `commands/registry.py`: `registry_list_formatter`, `registry_search_formatter`
- `commands/registry_run.py`: `node_output_formatter`, `registry_run_formatter`
- `commands/workflow.py`: `workflow_list_formatter`, `workflow_describe_formatter`, `discovery_formatter`, `workflow_save_formatter`, `history_formatter`

Note: `commands/mcp.py` still uses inline formatting (not yet migrated to shared formatters).

## Interactive Mode

Interactive detection rules are in `core/CLAUDE.md` (output_controller). CLI-specific impacts:
- Progress display: only in interactive
- Save prompts: auto-save in non-interactive
- Warning messages: suppressed in non-interactive
- Trace file paths: only shown in interactive

## Common Usage

```bash
pflow workflow.pflow.md param1=value1      # File-based execution
pflow github-analyzer repo=spinje/pflow    # Saved workflow
pflow --output-format json workflow.pflow.md  # JSON output
cat data.txt | pflow my-workflow           # Pipe stdin to workflow
pflow --validate-only workflow.pflow.md    # Validate without running

pflow mcp add ./github.mcp.json           # Add MCP server
pflow mcp serve                            # Run as MCP server (stdio)
pflow registry list                        # List nodes
pflow registry run shell command="echo hi" # Run single node
pflow read-fields exec-123-abc result[0].title  # Read cached fields
pflow workflow describe my-workflow        # Show workflow interface
pflow workflow history my-workflow         # Show execution history
pflow skill save my-workflow               # Publish as AI skill
pflow settings set-env ANTHROPIC_API_KEY sk-...  # Store API key
pflow settings llm show                    # Show LLM model config
pflow instructions usage                   # Agent guide
```

## Known Issues

1. **MCP connection cleanup** — handled by `MCPConnectionPool.shutdown()` in `executor_service.py` finally block; `pflow registry run` still creates ephemeral connections
2. **Click testing limitation** — `CliRunner` always returns `False` for `isatty()`, preventing interactive mode testing in unit tests
3. **Registry format inconsistency** — two save methods create format confusion, pattern matching checks multiple fields

## Gotchas

- **Don't combine catch-all args with subcommands** — the wrapper pattern exists because Click can't handle this
- **Use lazy imports** in command files and main.py to avoid circular dependencies
- **Don't mix output streams** — errors→stderr, results→stdout. This makes piping work.
- **Don't assume TTY** — always check interactive mode before showing progress or prompts

## Test Mapping

| Source file | Primary test file(s) |
|------------|---------------------|
| `main.py` | `test_cli.py`, `test_main.py`, `test_parse_error_handling.py`, `test_workflow_output_handling.py`, `test_dual_mode_stdin.py`, `test_enhanced_error_output.py` |
| `workflow_output.py` | `test_shell_stderr_warnings.py`, `test_direct_execution_helpers.py` |
| `workflow_resolution.py` | `test_workflow_resolution.py` |
| `mcp_sync.py` | `test_mcp_auto_discovery.py` |
| `param_parsing.py` | `test_rerun_display.py`, `test_direct_execution_helpers.py` |
| `main_wrapper.py` | `test_registry_cli.py` (routing tests), `test_validate_only.py`, `test_workflow_commands.py` |
| `commands/*` | See `commands/CLAUDE.md` |

**Mock.patch targets in main.py** (referenced by tests, will break if these move):
- `pflow.cli.main.WorkflowManager` — `test_workflow_resolution.py`, `test_nested_workflow_cli.py`
- `pflow.cli.main.execute_json_workflow` — `test_workflow_resolution.py`
- `pflow.cli.main.workflow_command` — `test_registry_cli.py`
