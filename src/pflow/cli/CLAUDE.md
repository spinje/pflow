# CLAUDE.md - CLI Module Documentation

## Executive Summary

The `src/pflow/cli/` module is the **command-line interface** for pflow, providing both natural language workflow execution and traditional CLI subcommands. It uses a unique wrapper pattern to handle the conflict between catch-all arguments for natural language input and Click's subcommand routing.

**Core Innovation**: Pre-parsing sys.argv to route between workflow execution (`pflow "create a poem"`) and subcommands (`pflow mcp list`) before Click processes arguments.

## Module Architecture

```
Entry Point (main_wrapper.cli_main)
    ↓
Routing Decision (based on first arg)
    ├─→ workflow_command (default)
    ├─→ mcp (MCP server management)
    ├─→ registry (node discovery)
    ├─→ workflow (saved workflow management)
    └─→ settings (configuration)
```

## File Structure

```
src/pflow/cli/
├── __init__.py                 # Module export (cli_main)
├── CLAUDE.md                   # This file (AI agent documentation)
├── main_wrapper.py             # Entry point router
├── main.py                     # Core CLI implementation (2929 lines)
├── cli_output.py              # OutputInterface implementation for Click
├── repair_save_handlers.py    # Workflow repair save logic
├── rerun_display.py           # Display rerun commands
├── mcp.py                     # MCP server management commands
├── registry.py                # Node registry commands
└── commands/
    ├── settings.py            # Settings management
    └── workflow.py            # Saved workflow commands
```

## Public API

- `cli_main` - Main entry point (from `__init__.py`)
- `workflow_command` (aliased as `main`) - Core workflow execution command

## Core Components

### 1. Main Wrapper (`main_wrapper.py`)

**Problem Solved**: Click can't handle both `@click.argument("workflow", nargs=-1)` and subcommands in the same group.

**Solution**: Pre-parse sys.argv to detect known subcommands BEFORE Click processes arguments.

**Routing Logic**:
```python
# Detect first non-option argument
if first_arg == "mcp":     → Route to mcp()
elif first_arg == "registry": → Route to registry()
elif first_arg == "workflow": → Route to workflow()
elif first_arg == "settings": → Route to settings()
else:                      → Route to workflow_command()
```

### 2. Core CLI (`main.py`)

**The heart of pflow CLI** - handles workflow execution, planning, and result display.

#### Main Command Options
```bash
@click.command(context_settings={"allow_interspersed_args": False})
--version              # Show version
--verbose, -v          # Detailed output
--output-key, -o       # Specific shared store key
--output-format        # text (default) or json
--print, -p            # Force non-interactive
--trace                # Save workflow execution trace
--trace-planner        # Save planner trace
--planner-timeout      # Timeout in seconds (default: 60)
--save/--no-save       # Save generated workflow (default: save)
--cache-planner        # Use cached planner results
--no-repair            # Disable auto-repair
--no-update            # Save repairs separately
workflow (nargs=-1)    # Catch-all for natural language or file path
```

#### Execution Flow

1. **Input Resolution** (workflow_command, line 2794+):
   - Version check
   - Context initialization
   - Parameter extraction
   - Workflow resolution (string vs file)

2. **Workflow Resolution** (resolve_workflow, line 209):
   - Try as file path
   - Try as saved workflow name
   - Fall back to natural language

3. **Planning Phase**:
   - Create planner flow
   - Generate workflow IR
   - Handle save prompts

4. **Execution Phase** (execute_json_workflow, line 1376):
   - Setup execution environment
   - Call `execute_workflow()` from execution module
   - Handle results and repairs

#### Key Functions

**Output Handling**:
- `_handle_workflow_output()` - Route output based on format (text/json)
- `_handle_text_output()` - Display text results with auto-detection
- `_handle_json_output()` - Structure JSON response
- `_find_auto_output()` - Smart output detection

**Error Handling**:
- `_handle_compilation_error()` - Compilation failures
- `_handle_workflow_error()` - Execution failures
- `_handle_workflow_exception()` - Unexpected errors

**Workflow Management**:
- `resolve_workflow()` - Load from file/registry/string
- `_auto_save_workflow()` - Save to workflow manager
- `_prompt_workflow_save()` - Interactive save dialog

### 3. CLI Output (`cli_output.py`)

**Purpose**: Implements OutputInterface for Click-based terminal output.

**Key Components**:
- `Colors` class - Terminal color constants
- `styled_text()` - Conditional color styling
- `CliOutput` class - OutputInterface implementation

**Integration with OutputController**:
- Delegates interactive detection
- Creates progress callbacks
- Manages verbose/JSON modes

### 4. Repair Save Handlers (`repair_save_handlers.py`)

**Purpose**: Route repaired workflow saves based on source type.

**Three Save Strategies**:
1. **Saved workflows**: Update via WorkflowManager.update_ir()
2. **File workflows**: Overwrite original (with .backup)
3. **Planner workflows**: Save as `workflow-repaired-TIMESTAMP.json`

**--no-update Flag Effect**:
- Saved: Save to `~/.pflow/workflows/repaired/`
- File: Create `.repaired.json`

### 5. MCP Commands (`mcp.py`)

**Subcommands**:
- `add` - Add servers from config files
- `list` - List configured servers
- `sync` - Synchronize server tools (with smart sync optimization)
- `remove` - Remove server configurations
- `tools` - List registered MCP tools
- `info` - Show tool details

**Smart Auto-Discovery**:
- Runs at pflow startup on every command
- Only syncs when config modified or servers changed
- Uses file mtime and server hash for detection
- Saves ~500ms on warm starts

**Universal MCPNode Pattern**:
- Single `MCPNode` class handles ALL MCP tools
- Virtual registry entries point to same node
- Server/tool injected via `__mcp_server__` and `__mcp_tool__`

**Critical Limitation**: No MCP server process cleanup on exit

### 6. Registry Commands (`registry.py`)

**Subcommands**:
- `list` - List all nodes with grouping
- `describe` - Show node metadata
- `search` - Find nodes by keyword
- `scan` - Force registry rescan

**Display Features**:
- Groups nodes by package
- Shows interface metadata
- Filters test nodes by default

### 7. Workflow Commands (`commands/workflow.py`)

**Subcommands**:
- `list` - List saved workflows
- `describe` - Show workflow interface
- `show` - Display workflow content
- `delete` - Remove saved workflow

**Interface Display**:
- Shows inputs (required/optional)
- Shows outputs
- Provides example usage

### 8. Settings Commands (`commands/settings.py`)

**Subcommands**:
- `init` - Create default settings file
- `show` - Display current settings + env overrides
- `allow` - Add allow pattern for nodes
- `deny` - Add deny pattern for nodes
- `remove` - Remove pattern from lists
- `check` - Test if node would be included
- `reset` - Reset to defaults

**Node Filtering System**:
- Load-time filtering (not storage-time)
- Pattern matching with fnmatch (glob-style)
- Priority: Test policy → Deny → Allow → Default
- Environment override: `PFLOW_INCLUDE_TEST_NODES`

**Settings Location**: `~/.pflow/settings.json`

## Critical Integration Points

### 1. Execution Module Integration

**Via execute_json_workflow()** (line 1376):
```python
from pflow.execution.workflow_execution import execute_workflow

result = execute_workflow(
    workflow_ir=ir_data,
    execution_params=enhanced_params,
    enable_repair=not no_repair,
    output=cli_output,  # CliOutput instance
    workflow_manager=workflow_manager,
    # ... other params
)
```

### 2. Planning Integration

**Via create_planner_flow**:
```python
from pflow.planning import create_planner_flow

planner_flow = create_planner_flow(debug_context=debug_context)
planner_flow.run(shared)  # Populates shared["workflow"]
```

**Planner Cache Chunks**:
- Extracted with priority: accumulated > extended > base
- Passed via `enhanced_params["__planner_cache_chunks__"]`
- Used by repair service for context continuity
- Enables cache reuse reducing LLM costs

### 3. Context Management

**Click Context (`ctx.obj`) Storage** (lines 2286-2299):
- `verbose`: Verbose output flag
- `output_format`: "text" or "json"
- `print_flag`: Force non-interactive
- `no_repair`: Disable auto-repair
- `no_update`: Save repairs separately
- `output_controller`: OutputController instance
- `workflow_source`: "file", "saved", or None
- `workflow_name`: For saved workflows
- `source_file_path`: For file workflows
- `execution_params`: User-provided parameters
- `workflow_metadata`: Metadata for workflow
- `workflow_trace`: Trace collector
- `trace_planner`: Planner trace flag
- `planner_timeout`: Timeout in seconds
- `save`: Save generated workflow flag
- `cache_planner`: Use cached planner

### 4. Output Format Handling

**Text Mode** (default):
- Auto-detects output from shared store
- Shows progress in interactive mode
- Displays execution metrics

**JSON Mode** (`--output-format json`):
- No progress output
- Structured response with metadata
- Error details in JSON format

**Print Mode** (`--print`):
- Forces non-interactive
- No progress indicators
- Clean output for piping

### 5. Stdin Handling

**Dual-Mode Reading** (_read_stdin_data, line 125):
1. Simple text reading first (backward compatibility)
2. Enhanced reading only if text fails (binary/large data)

**StdinData Structure**:
- `text_data`: UTF-8 text under 10MB
- `binary_data`: Binary content under 10MB
- `temp_path`: Path to temp file for large content

**Critical Issue**: `populate_shared_store()` in execution module only handles strings, not `StdinData` objects. Binary/large data may be lost in execution path.

**Shared Store Keys**:
- `shared["stdin"]` - Text data (backward compatible)
- `shared["stdin_binary"]` - Binary data
- `shared["stdin_path"]` - Path to temp file

### 6. Parameter Handling

**Type Inference** (infer_type function, line 1547):
- Booleans: `"true"/"false"` → `True/False` (case-insensitive)
- Integers: No decimal/scientific notation → `int`
- Floats: Has decimal or 'e' → `float`
- JSON: Starts with `[` or `{` → Parsed as list/dict
- Default: Everything else → `str`

**Parameter Security** (format_rerun_command, line 62):
- 15 predefined sensitive keys: password, passwd, pwd, token, api_token, access_token, auth_token, api_key, apikey, api-key, secret, client_secret, private_key, ssh_key, secret_key
- Auto-masked as `<REDACTED>` in display
- Shell injection protection via `shlex.quote()`
- Case-insensitive detection of sensitive names

**Internal Parameters**:
- `__` prefixed params are system-internal
- Filtered by `filter_user_params()` for display
- Include: `__verbose__`, `__llm_calls__`, `__planner_cache_chunks__`

## Key Data Flows

### 1. Natural Language Flow
```
User Input → Planning → Workflow IR → Execution → Display
             ↓                         ↓
           Save Prompt              Auto-repair
```

### 2. File/Saved Workflow Flow
```
Load Workflow → Validation → Execution → Display
                              ↓
                          Auto-repair
```

### 3. Output Resolution
```
Shared Store → Auto-detection → Format (text/json) → Display
                ↓
            Declared outputs
                ↓
            Common patterns
                ↓
            Last node output
```

## Critical Behaviors

### 1. Workflow Resolution Priority
1. Check if valid file path
2. Try loading from WorkflowManager
3. Treat as natural language request

### 2. Save Behavior
- **Default**: Prompt to save after planning
- **--no-save**: Skip save prompt
- **Auto-save**: Non-interactive mode

**Metadata Generation**:
- AI-generated by `MetadataGenerationNode`
- Includes: description, search_keywords, capabilities, typical_use_cases
- Execution tracking: count, timestamps, params

### 3. Interactive Detection

**Four Hierarchical Rules** (ALL must pass for interactive mode):
1. `print_flag = False` (no `-p` flag)
2. `output_format != "json"`
3. `stdin.isatty() = True`
4. `stdout.isatty() = True`

**Override Flags**:
- `-p/--print`: Forces non-interactive
- `--output-format json`: Forces non-interactive

**Impact Areas**:
- Progress display (only in interactive)
- Save prompts (auto in non-interactive)
- Warning messages (suppressed in non-interactive)
- Trace file paths (only shown in interactive)

### 4. Error Display Strategy

**_create_json_error_output** (line 639):
- Unified JSON error structure for all error types
- Extracts type, message, details, suggestion
- Includes metrics and workflow metadata
- Always sets `"success": false`

**Error Categories**:
- `PlannerError`: Planning failures
- `UserFriendlyError`: Structured user errors
- `CompilationError`: Workflow compilation issues
- Generic exceptions: Fallback handling

**Output Streams**:
- Progress/warnings → stderr (`err=True`)
- Results → stdout (for piping)

### 5. Trace File System

**File Patterns**:
- Workflow: `workflow-trace-{name}-{YYYYMMDD-HHMMSS}.json`
- Planner: `planner-trace-{YYYYMMDD-HHMMSS}.json`

**Save Conditions**:
- **Workflow traces**: Always saved when `--trace` present
- **Planner traces**: Saved when `--trace-planner` OR on failure

**Trace Collectors**:
- `WorkflowTraceCollector`: Node execution, LLM calls, repairs
- `TraceCollector` (planner): Planning nodes, path detection, costs

**Display**: Only shown in interactive mode via `_echo_trace()`

## Common Usage Patterns

### Natural Language Execution
```bash
pflow "download the latest release notes from github"
pflow "analyze this CSV and create a summary" < data.csv
```

### File-based Execution
```bash
pflow workflow.json param1=value1
pflow ./my-workflow.json --no-repair
```

### Saved Workflow Execution
```bash
pflow github-analyzer repo=anthropics/pflow
pflow my-saved-workflow --trace
```

### Subcommand Usage
```bash
pflow mcp add ./github.mcp.json
pflow registry list
pflow workflow describe my-workflow
pflow settings set test_nodes_enabled true
```

## Signal Handling and Cleanup

### Signal Handling (handle_sigint, line 36)
- Handles Ctrl+C with exit code 130
- No cleanup performed (relies on finally blocks)
- SIGPIPE set to default for shell compatibility

### Resource Cleanup (_cleanup_workflow_resources, line 1215)
- LLM interception cleanup
- Temporary file deletion
- Error collection and reporting
- Never raises exceptions

### Critical Gap
**No MCP server process management** - servers may remain running after exit

## Testing Considerations

### Key Mock Points
- `create_planner_flow()` for planning
- `execute_workflow()` for execution
- `click.prompt()` for user interaction
- `WorkflowManager` for saved workflows

### Test Boundaries
- Input parsing before planning
- Planning before execution
- Execution before display
- Display format selection

### TTY Testing Limitation
Click's `CliRunner` always returns `False` for `isatty()`, preventing true interactive testing

## Known Issues and Critical Findings

### 1. Stdin Handling Bug
`populate_shared_store()` in execution module only accepts strings, but CLI creates `StdinData` objects for binary/large data. This causes binary data loss in execution path.

### 2. No MCP Process Management
MCP server processes are not tracked or cleaned up on termination. Servers may remain running after CLI exits.

### 3. Test Node Detection
Hardcoded test node list plus pattern matching. Environment override `PFLOW_INCLUDE_TEST_NODES` has highest priority.

### 4. Registry Format Inconsistency
Two save methods create format confusion. Pattern matching checks multiple fields due to inconsistent metadata.

### 5. Click Testing Limitation
`CliRunner` always returns `False` for `isatty()`, preventing interactive mode testing in unit tests.

## AI Agent Guidance

### When Working in CLI Module

1. **Respect the Wrapper Pattern**: The main_wrapper exists for a reason - don't try to combine catch-all args with subcommands directly.

2. **Context Management**: Always use `ctx.obj` for passing state between functions.

3. **Output Format Awareness**: Check `output_format` before any display operations.

4. **Error Handling Hierarchy**: Compilation → Execution → Display errors have different handlers.

5. **Interactive vs Non-interactive**: Always check before showing progress or prompts.

### Common Pitfalls to Avoid

1. **Don't Import Execution Directly in __init__**: Use lazy imports to avoid circular dependencies
2. **Don't Show Progress in JSON Mode**: Check output_format first
3. **Don't Assume TTY**: Check interactive mode for progress displays
4. **Don't Mix Output Streams**: Errors to stderr, results to stdout
5. **Don't Forget Parameter Types**: Support type hints in parameters

### Integration Points to Remember

- **Execution**: Via `execute_workflow()` with CliOutput
- **Planning**: Via PlanningExecutor
- **Registry**: Via Registry.load()
- **Workflow Manager**: Via WorkflowManager for saves
- **Settings**: Via SettingsManager
- **MCP**: Via MCPServerManager and MCPRegistrar

This module is the user-facing interface that orchestrates all other pflow components, handling everything from natural language input to structured command execution.