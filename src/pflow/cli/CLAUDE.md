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
        ↓ resolve_workflow (execution/workflow_resolver.py)
        ↓ _validate_and_prepare_workflow_params
            ↓ parse_workflow_params (param_parsing.py)
            ↓ _route_stdin_to_params
        ↓ execute_json_workflow
            ↓ WorkflowRunner().run() (from pflow.execution.runner)
            ├─→ success: _handle_workflow_success → _handle_workflow_output (workflow_output.py)
            └─→ error: output_error() (error_output.py) → JSON or text
```

**Why the wrapper exists**: Click can't handle both `@click.argument("workflow", nargs=-1)` and subcommands in the same group. `main_wrapper.py` detects known subcommands BEFORE Click processes arguments. Adding a new subcommand: add to the `subcommand_routes` dict in `main_wrapper.py` and import the handler.

## File Structure

```
src/pflow/cli/
├── main_wrapper.py          # Entry point: routing table + _route_subcommand helper
├── main.py                  # Workflow execution orchestration (see "main.py" section below)
├── workflow_output.py       # Output detection, display, execution summaries
├── workflow_errors.py       # Text-mode error display for ExecutionResult failures
├── error_output.py            # Unified error output (JSON + text for all error types)
├── workflow_resolution.py   # CLI routing heuristic (is_likely_workflow_name only — resolve_workflow moved to execution/workflow_resolver.py)
├── mcp_sync.py              # MCP auto-discovery at startup
├── param_parsing.py         # infer_type, parse_workflow_params, format_param_value
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
error_output.py            (leaf — imports from workflow_output, workflow_errors, core/, execution/)
    ↑
main.py                    (orchestrator — imports from all modules above)
    ↑
main_wrapper.py            (entry point — imports workflow_command from main.py)
```

## main.py: Orchestration Layer

Contains the Click command definition (`workflow_command`) and everything that coordinates the execution pipeline. The functions here share dependencies on `_echo_trace` (trace display) and `ctx` (Click context), which is why they live together — they form a single orchestration flow from command entry to result display.

**What's here**:
- The Click command and its startup sequence (signals, env injection, context init)
- Execution pipeline: `execute_json_workflow` → `WorkflowRunner().run()` → success/error handling
- Success routing: `_handle_workflow_success` → `workflow_output.py`
- Error routing: `output_error()` from `error_output.py` (unified JSON + text for all error types)
- Validate-only mode: `WorkflowRunner().validate()` → `_display_validation_result()`
- Stdin routing: detects piped input, routes to workflow inputs marked `stdin: true`
- Named workflow handling: parameter preparation, workflow help display

`execute_json_workflow` is intentionally thin (~55 lines) — pre-execution setup, validation, resource lifecycle, and error boundary all live in `WorkflowRunner`. Don't pull them back into the CLI.

**If you need to extract more from main.py**: Functions that call `_echo_trace` or `ctx.exit()` can't move to `workflow_output.py` or `workflow_errors.py` without creating circular imports. Those modules import from each other but never back to main.py. Compilation/execution setup logic lives in `WorkflowRunner` (in `execution/runner.py`), not here — if you're tempted to add a helper that mutates shared store or calls `compile_workflow()`, it probably belongs in the Runner.

## Output Behavior

### Output Streams

- Progress/warnings → **stderr** (`err=True`)
- Results → **stdout** (safe for piping)

This split is critical: `pflow workflow.pflow.md | jq` works because progress noise goes to stderr. `BrokenPipeError` handled via `os._exit(0)` for clean pipe termination.

### Output routing (`_output_with_header` in workflow_output.py)

Single rule: data → stdout, diagnostics → stderr. Always — no TTY checks, no mode branching.

| Mode | When | Header | Data | Summary |
|------|------|--------|------|---------|
| `--print` (`-p`) | Explicitly requested | None | stdout | None |
| Default | Everything else (TTY, non-TTY, agents, CI/CD, pipes) | stderr | stdout | stderr |

`--print` is a minimal-output convenience that suppresses the header, summary, and warnings on stderr. Data still goes to stdout. Use it for clean piping into `jq` or similar tools: `pflow -p foo.pflow.md | jq`. Without `-p`, pipes still work correctly because data is already on stdout.

### Output Auto-Detection (`find_auto_output`)

Single unified implementation in `execution/formatters/output_utils.py`, used by both CLI text and JSON/MCP paths:

- **Priority**: `result > response > output > text > data > stdout`
- **Search order**: Root first, then namespaces (root is where declared outputs live)
- **Validity filter**: Skips None and empty/whitespace strings
- **Key filter**: Skips `_` and `__` prefixed keys
- **Last-key fallback**: If no priority key matches, takes the last valid non-internal key

CLI text mode emits a stderr warning when auto-detection is used (not in `--print` mode).

### JSON/Text Duality

Error output is unified: `output_error()` in `error_output.py` handles JSON/text branching for ALL error types. Success output still has parallel paths in `workflow_output.py`. The `--output-format json` flag gates which path executes. JSON mode suppresses all logging below ERROR level to prevent stdout contamination.

## workflow_output.py

Three responsibilities:

1. **Output routing**: `_handle_workflow_output` → `_handle_text_output` / `_handle_json_output`. Checks user-specified key, then declared outputs (skipped when `--only` active), then auto-detection.
2. **Execution summary**: `_display_execution_summary` emits a one-line completion tag (`✓ Workflow completed in Xs`) plus supplementary diagnostics (batch error details, shell stderr warnings, LLM cost, warning diagnostics) only when present. The previous "Nodes executed (N):" per-node listing was removed because it duplicated the live progress stream that is now always visible (TTY and non-TTY alike). When `--only` is active: the live progress and the completion tag reflect only the executed nodes.
3. **Shared utilities**: `safe_output` (BrokenPipeError handling), `_serialize_json_result` (JSON serialization with custom type handling), `_create_workflow_metadata`.

## workflow_errors.py

Text-mode error display for `ExecutionResult` failures. `_display_text_error_details` → `_display_single_error`: accepts `Diagnostic` objects directly (no dict coercion), renders via `format_diagnostic()`. Context blocks (API responses, MCP errors, template fields, shell command/stdout/stderr) are rendered universally by `_format_all_context_blocks()` in `diagnostic.py`. Compilation errors also flow through this path.

## error_output.py

Unified error output for ALL error types. Single entry point: `output_error()` handles both JSON and text modes for both exceptions and `ExecutionResult` failures. No error path in the CLI should bypass this — adding a new exception type means adding a `to_diagnostics()` override on the exception class, not a new special case here.

- `format_error_json()` — builds unified JSON shape: `{success, status, error, errors, diagnostics, workflow}`
- `display_exception_text()` — text-mode display using `exception_to_diagnostics()` + `format_diagnostic()`. No special cases — all exceptions go through the diagnostic pipeline.
- `output_error()` — THE single error output function (JSON delegates to `_serialize_json_result`, text delegates to `display_exception_text` or `_display_text_error_details`)

## Workflow Resolution

**Unified resolver**: `execution/workflow_resolver.py:resolve_workflow()` — used by both CLI and MCP. Returns `ResolvedWorkflow(ir, source, file_path)`. Raises `WorkflowNotFoundError` on not-found.

**CLI-only heuristic**: `workflow_resolution.py:is_likely_workflow_name(text, remaining_args)` — determines if a CLI arg is a workflow name vs a subcommand. Used for routing, not resolution.

`is_likely_workflow_name` heuristics:
- Has file extension or path separators → file path
- Followed by `key=value` args → workflow name with params
- Contains hyphens (kebab-case) → likely workflow name
- Single word without params → NOT treated as workflow name (prevents false positives)

Also: `pflow run my-workflow` silently strips the `run` prefix (`_preprocess_run_prefix` in main.py).

## Parameter Handling (param_parsing.py)

**Type inference** (`infer_type`):
- `"true"/"false"` → `True/False` (case-insensitive)
- No decimal/scientific notation → `int`
- Has decimal or `e` → `float`
- Starts with `[` or `{` → parsed as JSON list/dict
- Everything else → `str`

**Reverse conversion** (`format_param_value`): Converts Python values back to CLI strings. Co-located with `infer_type` because they are inverses — `format_param_value(infer_type(s)) == s` for round-trippable values.

**Internal parameters**: `__` prefixed params are system-internal, filtered from display by `filter_user_params()` (in `rerun_display.py`). Includes `__verbose__`.

**Sensitive parameter masking**: 15 predefined sensitive keys auto-masked as `<REDACTED>` in rerun display. Shell injection protection via `shlex.quote()`.

## MCP Auto-Discovery (mcp_sync.py)

Runs at startup on every `pflow` invocation. Smart skip: checks MCP config file mtime + SHA-256 hash of server list against stored metadata. Only re-syncs when config actually changed.

Note: has its own copy of `_get_output_controller` (duplicated from main.py to avoid circular imports).

## Command Flags

```
--version              # Show version
--verbose, -v          # Detailed output (extra error context)
--output-key, -o       # Extract specific shared store key instead of auto-detection
--output-format        # "text" (default) or "json" — json forces non-interactive
--print, -p            # Minimal output: suppress stderr header/summary/warnings
--no-trace             # Disable automatic workflow trace saving
--cache/--no-cache     # Enable/disable memoization cache reads (default: --cache). Writes always happen.
--only <node>          # Execute up to and including this node, then stop. Upstream from cache.
--validate-only        # Validate without executing (exit 0/1), auto-normalizes IR
workflow (nargs=-1)    # Catch-all: file path, saved name, key=value params
```

## Context (`ctx.obj`) — Non-Obvious Keys

Most keys are straightforward (`verbose`, `output_format`, `print_flag`, `trace`, `validate_only`). These are the ones that are hard to discover or have surprising behavior:

| Key | Notes |
|-----|-------|
| `output_controller` | `OutputController` instance — created once, reused by `_echo_trace` and output handling |
| `workflow_source` | `"file"`, `"library"`, or `None` — gates whether WorkflowManager is passed to Runner |
| `source_file_path` | Set for file and library workflows — injected as `_pflow_workflow_file` for nested workflow relative path resolution |
| `workflow_metadata` | Action field: `"reused"` (library) or `"unsaved"` (file) — drives execution summary display |
| `cache` | Boolean from `--cache/--no-cache` (default True). Flows to `RunnerConfig.cache_enabled` |
| `only_node` | String from `--only` (default None). Flows to `RunnerConfig.only_node` → `WorkflowEngine(only_node=...)` |
| `total_nodes` | Total node count from IR (set before Runner call). Used by `--report` to show `N/M (--only, K skipped)` |

Full list readable in `_initialize_context` and `_setup_workflow_execution` in main.py.

## Validate-Only Mode

What `--validate-only` checks (and doesn't):
- Checks: schema compliance, data flow, template structure, node types in registry
- Does NOT check: runtime values, API credentials, file existence

**Auto-normalization**: Adds `ir_version: "0.1.0"` if missing, `edges: []` if no connections. Same normalization applied during `workflow save`.

## Stdin Handling

See `core/CLAUDE.md` (shell_integration section) for FIFO detection, StdinData modes, and routing. Key CLI-specific behavior: validation happens AFTER stdin routing, so required inputs can be satisfied by piped data.

## Trace, Report, and Signal Handling

- Traces: `~/.pflow/debug/workflow-trace-{name}-{YYYYMMDD-HHMMSS}.json` — saved automatically (disable with `--no-trace`)
- Reports: `--report` generates `~/.pflow/reports/{name}/` directory of markdown files (one per node + summary). When `--only` is active, passes `only_node` and `total_nodes` to `generate_report()` for context in summary. `_echo_target_node_path` displays pointer to the target node's report file.
- Ctrl+C: exit code 130, no cleanup (relies on finally blocks)
- SIGPIPE: set to SIG_IGN (prevents subprocess SIGPIPE from killing parent process)
- Resource cleanup: Runner handles LLM interception cleanup in `_cleanup()`. CLI only cleans up temp files (stdin FIFO) in `execute_json_workflow`'s finally block.

## Shared Formatters

CLI uses formatters from `execution/formatters/` for output consistency with MCP server:
- `main.py`: `success_formatter`, `error_formatter`, `validation_formatter`
- `commands/registry.py`: `registry_list_formatter`, `registry_search_formatter`
- `commands/registry_run.py`: `node_output_formatter`
- `commands/workflow.py`: `workflow_list_formatter`, `workflow_describe_formatter`, `discovery_formatter`, `workflow_save_formatter`, `history_formatter`

Note: `commands/mcp.py` still uses inline formatting (not yet migrated to shared formatters).

## Interactive Mode

`OutputController.is_interactive()` has exactly one caller: `cli/mcp_sync.py` for MCP discovery progress gating. It does NOT gate workflow-execution progress.
- **Progress display**: always streams to stderr via `create_progress_callback()` (TTY and non-TTY alike). Suppressed in `-p` and `--output-format json` by the callsite gate `progress_enabled = not print_flag and output_format != "json"` in `main.py`, not by TTY detection. The one TTY-specific branch is `_handle_batch_progress`'s `\r` inline counter.
- **Save prompts**: use `click.confirm(...)` directly. There is no `OutputController` method for this.
- **Trace path echo**: `_echo_trace` suppresses the "📊 Workflow trace saved" line in `-p` and JSON mode.

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

1. **MCP connection cleanup** — handled by `MCPConnectionPool.shutdown()` in `runner.py:_cleanup()`; `pflow registry run` still creates ephemeral connections
2. **Click testing limitation** — `CliRunner` always returns `False` for `isatty()`. Batch-progress tests that exercise `\r` rendering need to patch `sys.stderr.isatty()` to `True`.
3. **Registry format inconsistency** — two save methods create format confusion, pattern matching checks multiple fields

## Gotchas

- **Don't combine catch-all args with subcommands** — the wrapper pattern exists because Click can't handle this
- **Use lazy imports** in command files and main.py to avoid circular dependencies
- **Don't mix output streams** — errors→stderr, results→stdout. This makes piping work.
- **Don't mix routing and rendering** — stdout/stderr routing is unified; only TTY-specific cursor rendering (`\r` batch updates) should inspect `isatty()`

## Test Mapping

| Source file | Primary test file(s) |
|------------|---------------------|
| `main.py` | `test_cli.py`, `test_main.py`, `test_parse_error_handling.py`, `test_workflow_output_handling.py`, `test_dual_mode_stdin.py`, `test_enhanced_error_output.py` |
| `error_output.py` | `test_unified_error_output.py` (unified JSON shape, structured field preservation, regressions) |
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
