# CLI Module

Command-line interface for pflow. Uses a pre-parsing wrapper pattern to handle the conflict between Click's subcommand routing and catch-all workflow arguments.

## Architecture

```
Entry Point (main_wrapper.cli_main)
    ↓
Routing Decision (pre-parses sys.argv, first non-option arg)
    ├─→ workflow_command (default — file path, saved name, or natural language)
    ├─→ mcp (MCP server management)
    ├─→ registry (node discovery)
    ├─→ workflow (saved workflow management)
    ├─→ settings (configuration)
    └─→ instructions (agent guidance)
```

**Why the wrapper exists**: Click can't handle both `@click.argument("workflow", nargs=-1)` and subcommands in the same group. `main_wrapper.py` detects known subcommands BEFORE Click processes arguments.

## File Structure

```
src/pflow/cli/
├── __init__.py              # Exports cli_main
├── main_wrapper.py          # Entry point router (pre-parses sys.argv)
├── main.py                  # Core workflow execution (~3400 lines)
├── cli_output.py            # OutputInterface implementation for Click
├── repair_save_handlers.py  # ⚠️ GATED (Task 107) — repair save logic
├── rerun_display.py         # Rerun command display with secret masking
├── discovery_errors.py      # Shared error handling for LLM discovery
├── read_fields.py           # Field reading utilities
├── logging_config.py        # CLI logging configuration
├── mcp.py                   # MCP server management commands
├── registry.py              # Node registry commands
├── registry_run.py          # Single node execution (pflow registry execute)
├── skills.py                # Skill management commands
├── instructions.py          # Agent instruction generation
├── resources/               # CLI resources (agent instructions)
└── commands/
    ├── settings.py          # Settings management
    └── workflow.py          # Saved workflow commands
```

## Core CLI (main.py)

### Command Flags

```
--version              # Show version
--verbose, -v          # Detailed output (shows shell stderr, error details)
--output-key, -o       # Extract specific shared store key instead of auto-detection
--output-format        # "text" (default) or "json" — json forces non-interactive
--print, -p            # Force non-interactive, clean output for piping
--no-trace             # Disable automatic workflow trace saving
--trace-planner        # Save planner trace (also saved automatically on failure)
--planner-timeout      # Timeout in seconds (default: 60)
--planner-model        # LLM model for planning (default: auto-detect)
--save/--no-save       # Save generated workflow (default: save) — planner only
--cache-planner        # Use cached planner results
--validate-only        # Validate without executing (exit 0/1), auto-normalizes IR
--auto-repair          # ⚠️ GATED (Task 107)
--no-update            # ⚠️ GATED (Task 107)
workflow (nargs=-1)    # Catch-all: file path, saved name, or natural language
```

### Workflow Resolution Priority

1. Check if valid file path (`.pflow.md`; `.json` → rejection error directing to markdown)
2. Try loading from WorkflowManager (saved name)
3. Natural language → planner (**GATED** — Task 107)

### Execution Flow

```
Load .pflow.md → parse_markdown() → Validation → Execution → Display
```

Output resolution priority: declared outputs → common patterns → last node output → auto-detection from shared store.

### Output Streams

- Progress/warnings → **stderr** (`err=True`)
- Results → **stdout** (safe for piping)

This split is critical: piping `pflow workflow.pflow.md | jq` works because progress noise goes to stderr.

### Interactive Mode Impact

Interactive detection rules are in `core/CLAUDE.md` (output_controller). CLI-specific impacts:
- Progress display: only in interactive
- Save prompts: auto-save in non-interactive
- Warning messages: suppressed in non-interactive
- Trace file paths: only shown in interactive

### Parameter Handling

**Type inference** (`infer_type` function):
- `"true"/"false"` → `True/False` (case-insensitive)
- No decimal/scientific notation → `int`
- Has decimal or `e` → `float`
- Starts with `[` or `{` → parsed as JSON list/dict
- Everything else → `str`

**Internal parameters**: `__` prefixed params are system-internal, filtered from display by `filter_user_params()`. Includes `__verbose__`, `__llm_calls__`, `__planner_cache_chunks__`.

**Sensitive parameter masking**: 15 predefined sensitive keys auto-masked as `<REDACTED>` in rerun display. Shell injection protection via `shlex.quote()`.

### Trace File System

- Workflow: `~/.pflow/debug/workflow-trace-{name}-{YYYYMMDD-HHMMSS}.json` — saved automatically (disable with `--no-trace`)
- Planner: `~/.pflow/debug/planner-trace-{YYYYMMDD-HHMMSS}.json` — saved when `--trace-planner` OR on failure

### Error Display

Error categories with different handlers: `PlannerError`, `UserFriendlyError`, `CompilationError`, generic exceptions.

Shell error details (verbose mode): shows command, stdout, stderr with truncation (200/300/300 chars).

JSON errors include structured execution state: per-node status (completed/failed/not_executed), duration, cached, repaired.

### Context (`ctx.obj`) — Non-Obvious Keys

- `workflow_source`: `"file"`, `"saved"`, or `None` — **gates whether metadata updates happen**
- `workflow_name`: derived from filename (file) or save name (saved), used for traces/display
- Full list of keys readable in `main.py` workflow_command function.

## Component Details

### MCP Commands (mcp.py)

Subcommands: `add`, `list`, `sync`, `remove`, `tools`, `info`, `serve`.

**Smart auto-discovery**: Runs at pflow startup on every command. Only syncs when config modified or servers changed — uses file mtime and server hash for detection. Saves ~500ms on warm starts.

**Universal MCPNode pattern**: Single `MCPNode` class handles ALL MCP tools. Virtual registry entries point to same node class. Server/tool injected via `__mcp_server__` and `__mcp_tool__` params.

**🐛 No MCP server process cleanup on exit** — servers may remain running after CLI exits.

### Registry Commands (registry.py)

Subcommands: `list`, `describe`, `search`, `scan`, `discover` (LLM-powered), `execute`.

**MCP tool normalization** (3-tier matching for `describe`/`execute`):
1. Exact match: `mcp-slack-composio-SLACK_SEND_MESSAGE`
2. Hyphen/underscore conversion: `SLACK-SEND-MESSAGE` → `SLACK_SEND_MESSAGE`
3. Short form: `SLACK_SEND_MESSAGE` → searches for unique tool with this suffix

Ambiguity detected → shows all matching full IDs with guidance.

### Workflow Commands (commands/workflow.py)

Subcommands: `list`, `describe`, `show`, `delete`, `discover` (LLM-powered), `save`.

**Workflow save**:
- Name validation: lowercase, numbers, hyphens only, max 30 chars (shell/URL/git-safe)
- Description extracted from markdown H1 prose (`--description` flag removed)
- `--delete-draft` safety check: only works in `.pflow/workflows/` directory
- `--generate-metadata` **GATED** (Task 107)

**Discovery commands use planning nodes directly** — `WorkflowDiscoveryNode`, `ComponentBrowsingNode`. No logic extraction needed. Nodes are self-contained with clear inputs/outputs.

**Discovery context requirements**: `ComponentBrowsingNode` requires `workflow_manager`, `current_date`, and `cache_planner` in the shared store. `WorkflowDiscoveryNode` requires `user_input` and `workflow_manager`.

### Instructions Commands (instructions.py)

- `pflow instructions usage` — basic usage guide (~100 lines)
- `pflow instructions create` — comprehensive workflow creation guide (~1600 lines)

AI agents should run `pflow instructions usage` when first connecting to pflow.

### Settings Commands (commands/settings.py)

Subcommands: `init`, `show`, `allow`, `deny`, `remove`, `check`, `reset`.

Node filtering priority: Test policy → Deny → Allow → Default. See `core/CLAUDE.md` for details.

### Repair Save Handlers (repair_save_handlers.py)

**⚠️ GATED** (Task 107): All entry points return early with warning. Code preserved for re-enabling.

Three save strategies (when re-enabled): saved workflows (update via WorkflowManager), file workflows (overwrite with .backup), planner workflows (save as repaired file).

### CLI Output (cli_output.py)

`CliOutput` implements `OutputInterface`, wraps `OutputController`. Delegates interactive detection, creates progress callbacks.

## Shared Formatters

CLI uses formatters from `execution/formatters/` for output consistency with MCP server:
- `main.py`: `success_formatter`, `error_formatter`, `validation_formatter`
- `registry.py`: `registry_list_formatter`, `registry_search_formatter`
- `registry_run.py`: `node_output_formatter`, `registry_run_formatter`
- `commands/workflow.py`: `workflow_list_formatter`, `workflow_describe_formatter`, `discovery_formatter`, `workflow_save_formatter`

## Validate-Only Mode

What `--validate-only` checks (and doesn't):
- ✅ Schema compliance, data flow correctness, template structure, node types in registry
- ❌ Runtime values, API credentials, file existence

**Auto-normalization**: Adds `ir_version: "0.1.0"` if missing, `edges: []` if no connections. Reduces friction for agent-generated workflows. Same normalization applied during `workflow save`.

## Stdin Handling

See `core/CLAUDE.md` (shell_integration section) for FIFO detection, StdinData modes, and routing details. Key CLI-specific behavior: validation happens AFTER stdin routing, so required inputs can be satisfied by piped data.

## Planner Cache Flow

```
PlanningNode → shared["planner_extended_blocks"]
    ↓
CLI extracts with priority: accumulated > extended > base
    ↓
enhanced_params["__planner_cache_chunks__"]
    ↓
RepairService uses as cache_blocks for LLM context continuity
```

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
pflow registry execute shell command="echo hi"
pflow workflow describe my-workflow
pflow instructions usage               # Agent guide
```

## Known Issues

1. **No MCP server process cleanup** — servers may remain running after CLI exit
2. **Click testing limitation** — `CliRunner` always returns `False` for `isatty()`, preventing interactive mode testing in unit tests
3. **Registry format inconsistency** — two save methods create format confusion, pattern matching checks multiple fields

## Gotchas for Developers

- **Don't combine catch-all args with subcommands** — the wrapper pattern exists because Click can't handle this. Respect it.
- **Don't import execution module in `__init__.py`** — use lazy imports to avoid circular dependencies
- **Don't mix output streams** — errors→stderr, results→stdout. This is what makes piping work.
- **Don't assume TTY** — always check interactive mode before showing progress or prompts
- **Anthropic monkey patch** — required for discovery commands, installed per-command (bypasses main CLI setup). Check for `PYTEST_CURRENT_TEST` to skip during testing.
- **Direct node reuse** — discovery commands use planning nodes (`WorkflowDiscoveryNode`, `ComponentBrowsingNode`) directly. Don't extract their logic into separate functions.

## Testing

Key mock points: `create_planner_flow()`, `execute_workflow()`, `click.prompt()`, `WorkflowManager`.

**TTY limitation**: Click's `CliRunner.isatty()` always returns False — can't test interactive mode paths in unit tests.
