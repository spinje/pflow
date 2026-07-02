# CLI Module

Command-line interface for pflow. Uses Click-native routing with a `PflowCLI(click.Group)` subclass that routes unknown commands to a hidden `run` command for workflow execution.

## Architecture

```
Entry Point (main.py:cli_main → cli group)
    ↓
PflowCLI.resolve_command (Click-native routing)
    ├─→ Known command → list, find, describe, history, save, guide, probe, mcp, ...
    └─→ Unknown first arg → hidden `run` command (workflow execution)
            ↓ commands/run.py
            ↓ _setup_workflow_execution, _initialize_context
            ↓ _auto_discover_mcp_servers (mcp_sync.py)
            ↓ _read_stdin_data, _validate_workflow_flags
            ↓ _try_execute_named_workflow
                ↓ is_likely_workflow_name (workflow_resolution.py)
                ↓ resolve_workflow (execution/workflow_resolver.py)
                ↓ _validate_and_prepare_workflow_params
                    ↓ parse_workflow_params (param_parsing.py)
                    ↓ _route_stdin_to_params
                ↓ execute_json_workflow
                    ├─→ dry-run: WorkflowRunner().plan() → plan_formatter
                    ├─→ validate-only: WorkflowRunner().validate()
                    └─→ execute: WorkflowRunner().run() (from pflow.execution.runner)
                            ├─→ success: _handle_workflow_success → _handle_workflow_output (workflow_output.py)
                            └─→ error: output_error() (error_output.py) → JSON or text
```

**How routing works**: `PflowCLI` sets `ignore_unknown_options = True` so that `run`-specific options (`--output-format`, `--no-trace`, etc.) pass through the group parser without error. `resolve_command()` checks if the first arg matches a registered command; if not, it routes everything to the hidden `run` command. This is the standard `click-default-group` pattern, vendored inline (~20 lines).

**Adding a new top-level command**: Create `commands/new_cmd.py`, import in `main.py`, call `cli.add_command(new_cmd)`.

## File Structure

```
src/pflow/cli/
├── __init__.py              # Exports cli_main
├── __main__.py              # python -m pflow.cli support
├── main.py                  # Entry point: PflowCLI group class, command registration
├── workflow_output.py       # Output detection, display, execution summaries
├── workflow_errors.py       # Text-mode error display for ExecutionResult failures
├── error_output.py          # Unified error output (JSON + text for all error types)
├── workflow_resolution.py   # CLI routing heuristic (is_likely_workflow_name only)
├── mcp_sync.py              # MCP auto-discovery at startup
├── param_parsing.py         # infer_type, parse_workflow_params, format_param_value
├── rerun_display.py         # Rerun command display with secret masking
├── find_errors.py           # Shared error handling for LLM-powered find commands
├── logging_config.py        # CLI logging configuration (suppresses 7 third-party libraries)
├── commands/                # One file per command (see commands/CLAUDE.md)
│   ├── run.py               # Workflow execution (largest command file)
│   ├── list.py, find.py, describe.py, history.py, save.py
│   ├── guide.py, probe.py, _probe_impl.py
│   ├── mcp.py, settings.py, skills.py
│   ├── read_fields.py, report.py, mermaid.py, ui.py, analyze_cache.py
│   └── CLAUDE.md
```

## Dependency Graph

```
param_parsing.py           (leaf — stdlib only)
workflow_resolution.py     (leaf — core/ only)
mcp_sync.py                (leaf — mcp/, registry/ only)
workflow_output.py         (leaf — core/, execution/ only)
error_output.py            (leaf — imports from workflow_output, workflow_errors, core/, execution/)
    ↑
commands/run.py            (orchestrator — imports from all modules above)
    ↑
main.py                    (entry point — registers all commands including run)
```

## main.py: Entry Point

Thin entry point: `PflowCLI` class, `cli` group definition with `--verbose`/`--version`, command registration via `cli.add_command()`, and `cli_main()`. Re-exports `main = cli` for backward compat with integration tests that do `from pflow.cli.main import main`.

**Group callback** handles: `ctx.obj["verbose"]`, `configure_logging(verbose)`, `_setup_signals()`, and showing help when no subcommand is given.

**`render_entry_content()`** from `pflow.guide` is evaluated at import time for Click's `help=` parameter. If `src/pflow/guide/entry.md` has no content, a placeholder is shown.

## commands/run.py: Workflow Execution

All workflow execution logic lives here (moved from the old monolithic `main.py`). This is the hidden default command that handles `pflow <workflow> [params...]`.

**Click settings** (all three are required for correct routing):
- `hidden=True` — doesn't appear in `--help` Commands section
- `add_help_option=False` — `--help` passes through to `_show_workflow_help()` for individual workflows
- `context_settings={"ignore_unknown_options": True, "allow_interspersed_args": True}`

**Reads `verbose` from `ctx.obj`** (set by the group callback). Does NOT have its own `--verbose` flag.

`execute_json_workflow` is the thin CLI shim that dispatches to `WorkflowRunner` (`plan()`, `validate()`, or `run()` depending on flags). Pre-execution setup, validation, resource lifecycle, and error boundary all live in `WorkflowRunner` — don't pull them back into the CLI.

## Output Behavior

### Output Streams

- Progress/warnings → **stderr** (`err=True`)
- Results → **stdout** (safe for piping)

This split is critical: `pflow workflow.pflow.md | jq` works because progress noise goes to stderr. `BrokenPipeError` handled via `os._exit(0)` for clean pipe termination.

### Output routing (`_output_with_header` in workflow_output.py)

Routing is TTY-agnostic: data always goes to stdout, diagnostics always go to stderr. The stderr header (`Workflow output (<desc>):`) is the only TTY-sensitive element — shown when stdout is a TTY **or** stderr is non-TTY, and suppressed ONLY when stdout is redirected to a file/pipe while stderr is a terminal (`pflow wf > out.json` watched in a shell), where a naked label with the value elsewhere reads as "empty output". Agents capturing both streams (e.g. `2>&1`) see the label as a result delimiter. This is the Option B refinement of the Task 149 suppression — see `_show_output_header` in `workflow_output.py`.

| Mode | When | Header | Data | Summary |
|------|------|--------|------|---------|
| `--print` (`-p`) | Explicitly requested | None | stdout | None |
| stdout TTY | Interactive terminal | stderr | stdout | stderr |
| stdout non-TTY, stderr non-TTY | Pipe / CI / agent (`2>&1`, both captured) | stderr | stdout | stderr |
| stdout non-TTY, stderr TTY | Redirect to file while watching terminal (`pflow wf > out`) | None | stdout | stderr |

`--print` suppresses header, summary, and warnings on stderr. Data still goes to stdout.

### Declared vs `--only` Output Contract

Precedence is explicit and load-bearing, and lives in ONE place: `select_output_mode(output_key, workflow_ir, shared) -> OutputMode` in `execution/formatters/output_utils.py`. Both the CLI text path (`_handle_text_output`) and the JSON/MCP path (`success_formatter._collect_outputs`) dispatch on the returned `OutputMode` — they render the chosen branch differently but never re-encode the precedence (which is how they previously drifted). Mirrors `plan.py`'s `Transition` classify-then-dispatch idiom; pinned by `TestSelectOutputMode` in `tests/test_execution/formatters/test_output_utils.py`.

1. `EXPLICIT_KEY` — `-o/--output-key` wins in text and JSON, even under `--only`.
2. `ONLY` — `--only` runs without `-o` skip workflow-declared outputs and use `find_only_output(shared, only_node)`. Flat targets unwrap common result keys from `shared[target]`. This prevents full-run outputs or unrelated root `result` keys from shadowing the node the user explicitly targeted. (Dotted `--only parent.child` is rejected at the engine layer — issue #443 snapshot semantics; nested targeting is a deferred feature. The dotted branches of `find_only_output` and the compact-summary path are dormant display logic the deferred feature would reuse.) Decided *before* `DECLARED`, so no `not only_node` guard is needed in either renderer.
3. `DECLARED` — full runs without `-o`/`--only` use workflow-declared outputs. Text mode streams one output (`stdout: true`, single output, or first-with-warning); JSON emits all declared outputs.
4. `AUTO` — the floor: auto-detect via `find_auto_output`.

### Output Auto-Detection (`find_auto_output`)

Single unified implementation in `execution/formatters/output_utils.py`, used by both CLI text and JSON/MCP paths:

- **Priority**: `result > response > output > text > data > stdout`
- **Search order**: Root first, then namespaces (root is where declared outputs live)
- **Validity filter**: Skips None and empty/whitespace strings
- **Key filter**: Skips `_` and `__` prefixed keys
- **Last-key fallback**: If no priority key matches, takes the last valid non-internal key

### JSON/Text Duality

Error output is unified: `output_error()` in `error_output.py` handles JSON/text branching for ALL error types. Success output still has parallel paths in `workflow_output.py`. `--output-format` controls stdout format only; stderr verbosity is controlled solely by `-p`.

### Exit Codes

Completed workflows exit `0`, including `WorkflowStatus.DEGRADED` runs with runtime warnings. Failed workflows exit `1`; interrupted workflows exit `130`; a run DENIED at an approval gate exits `3` (Task 125 — a human verdict, not a failure; click owns `2` for usage errors). The denied branch in `_display_execution_result` renders its own output (text prose on stderr, or a JSON document with the `gate` payload on stdout) and never routes through `output_error`/`_emit_failure_tag`. Warning/degraded status remains visible through stderr, JSON, trace, and reports.

## Command Flags

**Group-level** (parsed once by `PflowCLI`, shared via `ctx.obj`):
```
--verbose, -v          # Detailed output (extra error context)
--version              # Show version (Click built-in)
```

**`run` command only** (workflow execution options):
```
--output-key, -o       # Extract specific shared store key instead of auto-detection
--output-format        # "text" (default) or "json" — controls stdout format only
--print, -p            # Minimal output: suppress stderr header/summary/warnings
--no-trace             # Disable automatic workflow trace saving
--cache/--no-cache     # Enable/disable memoization cache reads (default: --cache). Writes always happen.
--only <node>          # Re-run just this node against a snapshot of the most recent full run (upstream restored, not re-executed — no re-fire). Needs a prior full run; dotted/nested targets rejected (issue #443).
--auto-approve <id>    # Pre-approve ONE approval gate by step name (repeatable, per-node only — no blanket form by design, Task 125). Escalations never pre-approve. Flat namespace across the workflow tree: a nested gate matches by name. An id naming no TOP-LEVEL step → informational note (closest match + gated list), never an error — it may be a legitimate nested gate.
--validate-only        # Validate without executing (exit 0/1), auto-normalizes IR
--dry-run              # Build execution plan without side effects
--report               # Generate execution report
--report-dir           # Custom output directory for report (implies --report)
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
| `dry_run` | Boolean from `--dry-run`. Routes `execute_json_workflow()` to `WorkflowRunner.plan()` + `plan_formatter` |
| `total_nodes` | Total node count from IR (set before Runner call). Used by `--report` to show `N/M (--only, K skipped)` |

Full list readable in `_initialize_context` and `_setup_workflow_execution` in `commands/run.py`.

## Workflow Resolution

**Unified resolver**: `execution/workflow_resolver.py:resolve_workflow()` — used by both CLI and MCP. Returns `ResolvedWorkflow(ir, source, file_path)`. Raises `WorkflowNotFoundError` on not-found.

**CLI-only heuristic**: `workflow_resolution.py:is_likely_workflow_name(text, remaining_args)` — determines if a CLI arg is a workflow name vs a typo. Used inside the `run` command, not for routing (routing is handled by `PflowCLI.resolve_command`).

`is_likely_workflow_name` heuristics:
- Has file extension or path separators → file path
- Followed by `key=value` args → workflow name with params
- Contains hyphens (kebab-case) → likely workflow name
- Single word without params → NOT treated as workflow name (prevents false positives)

## Parameter Handling (param_parsing.py)

**Type inference** (`infer_type`):
- `"true"/"false"` → `True/False` (case-insensitive)
- No decimal/scientific notation → `int`
- Has decimal or `e` → `float`
- Starts with `[` or `{` → parsed as JSON list/dict
- Everything else → `str`

**Reverse conversion** (`format_param_value`): Converts Python values back to CLI strings. Co-located with `infer_type` because they are inverses — `format_param_value(infer_type(s)) == s` for round-trippable values.

**Internal parameters**: `__` prefixed params are system-internal, filtered from display by `filter_user_params()` (in `rerun_display.py`). Includes `__verbose__`.

**Sensitive parameter masking**: 19 predefined sensitive keys auto-masked as `<REDACTED>` in rerun display. Shell injection protection via `shlex.quote()`.

## MCP Auto-Discovery (mcp_sync.py)

Runs at startup on every `pflow` invocation. Smart skip: checks MCP config file mtime + SHA-256 hash of server list against stored metadata. Only re-syncs when config actually changed.

Note: has its own copy of `_get_output_controller` (duplicated from `commands/run.py` to avoid circular imports).

## Shared Formatters

CLI uses formatters from `execution/formatters/` for output consistency with MCP server:
- `commands/run.py`: `success_formatter`, `error_formatter`, `validation_formatter`
- `commands/_probe_impl.py`: `node_output_formatter`
- `commands/list.py`, `describe.py`, `find.py`, `save.py`, `history.py`: `workflow_list_formatter`, `workflow_describe_formatter`, `discovery_formatter`, `workflow_save_formatter`, `history_formatter`

Note: `commands/mcp.py` still uses inline formatting (not yet migrated to shared formatters).

## Interactive Mode

`OutputController.is_interactive()` has exactly one caller: `cli/mcp_sync.py` for MCP discovery progress gating. It does NOT gate workflow-execution progress.
- **Progress display**: always streams to stderr via `create_progress_callback()` (TTY and non-TTY alike). Suppressed in `-p` by the callsite gate `progress_enabled = not print_flag` in `commands/run.py`, not by TTY detection. The one TTY-specific branch is `_handle_batch_progress`'s `\r` inline counter.
- **Save prompts**: use `click.confirm(...)` directly.
- **Trace path echo**: `_echo_trace` suppresses the "Workflow trace saved" line in `-p` mode.

## Stdin Handling

See `core/CLAUDE.md` (shell_integration section) for FIFO detection, StdinData modes, and routing. Key CLI-specific behavior: validation happens AFTER stdin routing, so required inputs can be satisfied by piped data.

## Trace, Report, and Signal Handling

- Traces: `~/.pflow/debug/workflow-trace-{wf_hash}-{name}-{YYYYMMDD-HHMMSS-ffffff}.json` — saved automatically (disable with `--no-trace`). The `wf_hash` is an 8-char md5 of the workflow path, used by `pflow analyze-cache` autoload to find traces for a given workflow without scanning the whole directory. The microsecond suffix (`%f`) keeps a same-second full-run + `--only`-run pair from colliding (issue #443) — `--only`'s snapshot reuse depends on the full-run trace surviving.
- Reports: `--report` generates `~/.pflow/reports/{name}/` as a replaced snapshot with `.pflow-report.json`. Explicit `--report-dir` paths are preflighted before execution and must be empty or already marked as pflow report output.
- Ctrl+C: exit code 130, no cleanup (relies on finally blocks)
- SIGPIPE: set to SIG_IGN (prevents subprocess SIGPIPE from killing parent process). Both set in `main.py:_setup_signals()`.
- Resource cleanup: Runner handles LLM interception cleanup in `_cleanup()`. CLI only cleans up temp files (stdin FIFO) in `execute_json_workflow`'s finally block.

## Known Issues

1. **MCP connection cleanup** — handled by `MCPConnectionPool.shutdown()` in `runner.py:_cleanup()`; `pflow probe` still creates ephemeral connections
2. **Click testing limitation** — `CliRunner` always returns `False` for `isatty()`. Batch-progress tests that exercise `\r` rendering need to patch `sys.stderr.isatty()` to `True`.

## Gotchas

- **Use lazy imports** in command files and `commands/run.py` to avoid circular dependencies
- **Don't mix output streams** — errors→stderr, results→stdout. This makes piping work.
- **Don't mix routing and rendering** — stdout/stderr routing is TTY-agnostic; the stderr header in `_output_with_header` and the `\r` batch counter are the only TTY-sensitive writes
- **`ignore_unknown_options=True` is load-bearing, not lax** — it lets `--help` and any unknown dash token reach the `workflow` tuple instead of erroring at parse time; the per-workflow `--help` passthrough depends on it, so don't remove it. `_validate_workflow_flags` (`commands/run.py`) then rejects *every* stray leading-dash token after the workflow with a "use key=value" error (`--help` is the one whitelist; `-h` points to `--help`). This is what stops unknown flags like `--scenario x` from being silently dropped (GH #454). Note: `=`-bearing dash tokens (`--scenario=x`) skip this guard and fail later via the undeclared-input validator instead.

## Test Mapping

| Source file | Primary test file(s) |
|------------|---------------------|
| `main.py` | `test_cli.py`, `test_main.py` |
| `commands/run.py` | `test_workflow_resolution.py`, `test_dual_mode_stdin.py`, `test_parse_error_handling.py`, `test_workflow_output_handling.py`, `test_validate_only.py`, `test_validation_before_execution.py`, `test_dry_run.py` |
| `error_output.py` | `test_unified_error_output.py`, `test_enhanced_error_output.py` |
| `workflow_output.py` | `test_shell_stderr_warnings.py`, `test_direct_execution_helpers.py`, `test_workflow_output_source_simple.py` |
| `workflow_resolution.py` | `test_workflow_resolution.py` |
| `mcp_sync.py` | `test_mcp_auto_discovery.py` |
| `param_parsing.py` | `test_rerun_display.py`, `test_direct_execution_helpers.py` |
| `commands/*` | See `commands/CLAUDE.md` |

**Mock.patch targets in commands/run.py** (referenced by tests, will break if these move):
- `pflow.cli.commands.run.WorkflowManager` — `test_workflow_resolution.py`, `test_nested_workflow_cli.py`
- `pflow.cli.commands.run.execute_json_workflow` — `test_workflow_resolution.py`

## Common Usage

```bash
pflow workflow.pflow.md param1=value1      # File-based execution
pflow github-analyzer repo=spinje/pflow    # Saved workflow
pflow --output-format json workflow.pflow.md  # JSON output
cat data.txt | pflow my-workflow           # Pipe stdin to workflow
pflow --validate-only workflow.pflow.md    # Validate without running

pflow list                                 # List saved workflows
pflow find "something"                     # LLM-powered workflow search
pflow describe my-workflow                 # Show workflow interface
pflow history my-workflow                  # Show execution history
pflow save workflow.pflow.md --name my-wf  # Save to library
pflow guide                                # Agent guide

pflow mcp add ./github.mcp.json           # Add MCP server
pflow mcp list                             # List MCP tools
pflow mcp find "send slack message"        # LLM-powered MCP tool search
pflow mcp describe mcp-github-create-issue # MCP tool details
pflow mcp servers                          # List configured servers
pflow mcp serve                            # Run as MCP server (stdio)

pflow probe shell command="echo hi"        # Test single node
pflow read-fields exec-123-abc result[0].title  # Read cached fields
pflow skill save my-workflow               # Publish as AI skill
pflow settings set-env ANTHROPIC_API_KEY sk-...  # Store API key
pflow settings llm show                    # Show LLM model config
```
