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
├── main.py                     # Core CLI implementation (3403 lines)
├── cli_output.py              # OutputInterface implementation for Click
├── repair_save_handlers.py    # Workflow repair save logic
├── rerun_display.py           # Display rerun commands
├── discovery_errors.py        # Discovery error handling
├── mcp.py                     # MCP server management commands
├── registry.py                # Node registry commands
├── registry_run.py            # Single node execution (pflow registry execute)
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
--no-trace            # Disable workflow execution trace (enabled by default)
--trace-planner        # Save planner trace
--planner-timeout      # Timeout in seconds (default: 60)
--save/--no-save       # Save generated workflow (default: save)
--cache-planner        # Use cached planner results
--auto-repair            # Enable auto-repair
--no-update            # Save repairs separately
--validate-only        # Validate workflow without executing (NEW in Task 71)
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
- `_handle_json_output()` - Structure JSON response (enhanced in Task 71)
- `_find_auto_output()` - Smart output detection
- `_build_execution_steps()` - Build detailed execution state (NEW in Task 71)

**Error Handling**:
- `_handle_compilation_error()` - Compilation failures
- `_handle_workflow_error()` - Execution failures (enhanced in Task 71)
- `_handle_workflow_exception()` - Unexpected errors
- `_handle_discovery_error()` - Discovery command errors (NEW in Task 71)

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
- `serve` - Run pflow as MCP server (stdio transport)

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
- `describe` - Show node metadata (with MCP tool normalization - NEW in Task 71)
- `search` - Find nodes by keyword
- `scan` - Force registry rescan
- `discover` - LLM-powered node selection (NEW in Task 71)
- `execute` - Execute single node independently (delegates to `registry_run.py`)

**Display Features**:
- Groups nodes by package
- Shows interface metadata
- Filters test nodes by default

**NEW: MCP Tool Normalization** (Task 71):
- `_normalize_node_id()` handles multiple formats:
  - Exact match: `mcp-slack-composio-SLACK_SEND_MESSAGE`
  - Hyphen/underscore conversion: `SLACK-SEND-MESSAGE` → `SLACK_SEND_MESSAGE`
  - Short form matching: `SLACK_SEND_MESSAGE` → `mcp-slack-composio-SLACK_SEND_MESSAGE`
- Ambiguity detection with helpful error messages
- 3-tier matching strategy (lines 709-773)

### 7. Workflow Commands (`commands/workflow.py`)

**Subcommands**:
- `list` - List saved workflows
- `describe` - Show workflow interface
- `show` - Display workflow content
- `delete` - Remove saved workflow
- `discover` - LLM-powered workflow discovery (NEW in Task 71)
- `save` - Save workflow to global library (NEW in Task 71)

**Interface Display**:
- Shows inputs (required/optional)
- Shows outputs
- Provides example usage

**NEW: Workflow Discovery** (Task 71, lines 234-376):
- Uses `WorkflowDiscoveryNode` for intelligent matching
- Returns workflow with metadata, flow, inputs, outputs, confidence
- Anthropic monkey patch installed for LLM calls
- Agent-friendly error handling (auth errors → alternatives)

**NEW: Workflow Save** (Task 71, lines 405-442):
- Name validation: lowercase, numbers, hyphens only (max 30 chars)
- Auto-normalization: adds `ir_version`, `edges` if missing
- Optional `--generate-metadata` using `MetadataGenerationNode`
- Optional `--delete-draft` with safety check (only `.pflow/workflows/`)
- Optional `--force` to overwrite existing workflows
- Extracted to helper functions for clarity (lines 132-403)

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
    enable_repair=not auto_repair,
    output=cli_output,  # CliOutput instance
    workflow_manager=workflow_manager,
    # ... other params
)
```

**Shared Formatters**: CLI uses formatters from `execution/formatters/` for output consistency with MCP server
- `registry_run.py`: Uses `node_output_formatter`, `registry_run_formatter`
- `registry.py`: Uses `registry_list_formatter`, `registry_search_formatter`
- `commands/workflow.py`: Uses `workflow_list_formatter`, `workflow_describe_formatter`, `discovery_formatter`, `workflow_save_formatter`
- `main.py`: Uses `success_formatter`, `error_formatter`, `validation_formatter`

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

**Workflow Save Service**: `commands/workflow.py` uses `core/workflow_save_service.py` for workflow save operations
- `validate_workflow_name()` - Name format validation
- `load_and_validate_workflow()` - Load and normalize from file
- `save_workflow_with_options()` - Save with force/overwrite handling
- `generate_workflow_metadata()` - Optional LLM metadata generation
- `delete_draft_safely()` - Security-aware draft deletion

### 3. Context Management

**Click Context (`ctx.obj`) Storage**:
- `verbose`: Verbose output flag
- `output_format`: "text" or "json"
- `print_flag`: Force non-interactive
- `auto_repair`: Enable auto-repair
- `no_update`: Save repairs separately
- `validate_only`: Validate without executing (NEW in Task 71)
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
- **Workflow traces**: Saved automatically (disable with `--no-trace`)
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
pflow ./my-workflow.json --auto-repair
```

### Saved Workflow Execution
```bash
pflow github-analyzer repo=anthropics/pflow
pflow my-saved-workflow  # Trace saved automatically to ~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json
```

### Subcommand Usage
```bash
pflow mcp add ./github.mcp.json
pflow mcp serve                    # Run as MCP server (stdio)
pflow registry list
pflow registry execute node_type param=value
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

## Task 71 Enhancements: Agent-First CLI

### Overview

Task 71 added comprehensive agent enablement features to make pflow CLI AI-agent-friendly. All changes maintain backward compatibility while adding powerful discovery and validation tools.

### New Features

#### 1. Static Validation (`--validate-only` flag)

**Location**: `main.py` lines 2912-2990

**Purpose**: Validate workflow structure without executing, enabling agents to catch errors early.

**Implementation**:
```python
# Flag added to workflow_command
@click.option("--validate-only", is_flag=True)

# Validation logic (lines 2912-2990)
if validate_only:
    # Generate dummy values for declared inputs
    dummy_params = {k: "__validation_placeholder__" for k in ir_data.get("inputs", {})}

    # Full structural validation
    errors = WorkflowValidator.validate(workflow_ir=ir_data, extracted_params=dummy_params)

    # Display results and exit
    if errors: exit(1)
    else: exit(0)
```

**What Gets Validated**:
- ✅ Schema compliance (JSON structure, required fields)
- ✅ Data flow correctness (execution order, no cycles)
- ✅ Template structure (`${node.output}` references)
- ✅ Node types exist in registry
- ❌ Runtime values (that's execution-time)
- ❌ API credentials
- ❌ File existence

**Auto-Normalization** (lines 2931-2935):
- Adds `ir_version: "0.1.0"` if missing
- Adds `edges: []` if no connections
- Reduces friction for agent-generated workflows

#### 2. Workflow Discovery (`pflow workflow discover`)

**Location**: `commands/workflow.py` lines 234-376

**Purpose**: LLM-powered intelligent workflow matching based on natural language description.

**Implementation**:
```python
@workflow.command(name="discover")
def discover_workflows(query: str):
    # Install Anthropic model for LLM calls
    install_anthropic_model()

    # Use WorkflowDiscoveryNode directly
    node = WorkflowDiscoveryNode()
    shared = {"user_input": query, "workflow_manager": WorkflowManager()}
    action = node.run(shared)

    # Display results
    if action == "found_existing":
        _format_discovery_result(result, workflow)
```

**Extracted Helper Functions** (lines 132-232):
- `_handle_discovery_error()` - Agent-friendly error messages
- `_display_workflow_metadata()` - Metadata section
- `_display_workflow_flow()` - Node flow visualization
- `_display_workflow_inputs_outputs()` - I/O specs
- `_format_discovery_result()` - Complete result formatting

**Error Handling**:
- Detects authentication errors → shows alternatives
- No internal jargon or stack traces
- Actionable guidance (export ANTHROPIC_API_KEY, use alternatives)

#### 3. Workflow Save (`pflow workflow save`)

**Location**: `commands/workflow.py` lines 405-442

**Purpose**: Promote draft workflows to global library with metadata generation.

**Implementation**:
```python
@workflow.command(name="save")
def save_workflow(file_path, name, description, delete_draft, force, generate_metadata):
    _validate_workflow_name(name)  # Lines 178-197
    validated_ir = _load_and_normalize_workflow(file_path)  # Lines 200-302
    metadata = _generate_metadata_if_requested(validated_ir, generate_metadata)  # Lines 305-336
    saved_path = _save_with_overwrite_check(...)  # Lines 339-376
    _delete_draft_if_requested(file_path, delete_draft)  # Lines 379-402
```

**Name Validation Rules** (lines 178-197):
- Lowercase letters, numbers, hyphens only
- Max 30 characters
- Shell-safe, URL-safe, git-branch-compatible

**Auto-Normalization** (lines 291-294):
- Same as `--validate-only` (ir_version, edges)

**Metadata Generation** (lines 305-336):
- Uses `MetadataGenerationNode` for rich metadata
- Generates keywords, capabilities, use cases
- Optional via `--generate-metadata` flag

**Safety Features** (lines 379-402):
- `--delete-draft` only works in `.pflow/workflows/` directory
- `--force` requires explicit confirmation
- Deletes existing before save to avoid conflicts

#### 4. Node Discovery (`pflow registry discover`)

**Location**: `registry.py` lines 646-723

**Purpose**: LLM-powered node selection based on task description.

**Implementation**:
```python
@registry.command(name="discover")
def discover_nodes(query: str):
    # Install Anthropic model
    install_anthropic_model()

    # Create complete context (required by ComponentBrowsingNode)
    shared = {
        "user_input": query,
        "workflow_manager": WorkflowManager(),  # Required for workflow context
        "current_date": datetime.now().strftime("%Y-%m-%d"),
        "cache_planner": False
    }

    # Use ComponentBrowsingNode directly
    node = ComponentBrowsingNode()
    node.run(shared)

    # Display planning_context (already formatted markdown)
    click.echo(shared["planning_context"])
```

**Context Requirements**:
- `workflow_manager` - Required by ComponentBrowsingNode
- `current_date` - Standard planning context
- `cache_planner` - Disabled for CLI

#### 5. Enhanced Node Description (`pflow registry describe`)

**Location**: `registry.py` lines 837-870

**Purpose**: Detailed node specifications with MCP tool normalization.

**MCP Tool Normalization** (lines 709-773):

**3-Tier Matching Strategy**:
1. **Exact match**: `mcp-slack-composio-SLACK_SEND_MESSAGE`
2. **Hyphen/underscore conversion**: `SLACK-SEND-MESSAGE` → `SLACK_SEND_MESSAGE`
3. **Short form matching**: `SLACK_SEND_MESSAGE` → searches for unique tool ending with this

**Example**:
```bash
# All these work:
pflow registry describe mcp-slack-composio-SLACK_SEND_MESSAGE
pflow registry describe SLACK-SEND-MESSAGE  # Normalized
pflow registry describe SLACK_SEND_MESSAGE  # Short form
```

**Ambiguity Handling** (lines 818-833):
- Detects multiple matches
- Shows all matching full IDs
- Suggests using full format or `{server}-{tool}`

**Validation Helper Functions** (lines 776-833):
- `_validate_and_normalize_node_ids()` - Batch validation
- `_handle_node_validation_errors()` - Error display with guidance

#### 6. Enhanced Error Output

**Location**: `main.py` lines 1153-1269

**Purpose**: Show rich error context to help agents debug failures.

**Implementation**:
```python
def _handle_workflow_error(ctx, result, ...):
    if output_format == "json":
        # Include structured errors from ExecutionResult
        error_output["errors"] = result.errors  # Rich error data

        # Add execution state
        error_output["execution"] = {
            "duration_ms": ...,
            "nodes_executed": ...,
            "steps": [...]  # Per-node status, cache, duration
        }
    else:
        # Text mode: Display rich error details
        for error in result.errors:
            click.echo(f"Error at node '{error['node_id']}':")
            click.echo(f"  Category: {error['category']}")

            # Show API response details
            if raw := error.get('raw_response'):
                # Field-level errors

            # Show template suggestions
            if available := error.get('available_fields'):
                # List available fields
```

**Error Data Extracted** (executor_service.py lines 240-275):
- HTTP nodes: status_code, raw_response, response_headers
- MCP nodes: mcp_error_details, mcp_error
- Template errors: available_fields

**Execution State** (main.py lines 548-697):
- Added `_build_execution_steps()` function
- Per-node: status (completed/failed/not_executed), duration, cached, repaired
- Cache tracking via `__cache_hits__` (instrumented_wrapper.py lines 542-601)

### Integration Pattern: Direct Node Reuse

**Philosophy**: Planning nodes are designed for standalone execution - no extraction needed.

**Pattern**:
```python
# Discovery commands use nodes directly
node = WorkflowDiscoveryNode()  # or ComponentBrowsingNode, MetadataGenerationNode
shared = {"user_input": query, "workflow_manager": WorkflowManager()}
action = node.run(shared)
# Result in shared["discovery_result"], shared["found_workflow"], etc.
```

**Why This Works**:
- Nodes are self-contained with clear inputs/outputs
- No need to extract logic into separate functions
- Reuses existing battle-tested implementations
- Maintains consistency with planning system

### Backward Compatibility

**All changes are additive**:
- New flags are optional
- New commands don't affect existing commands
- JSON output enhancements are additive (old fields preserved)
- Error messages remain for non-agent users

**No Breaking Changes**:
- Existing workflows still work
- Existing parameters unchanged
- Existing output formats preserved

## AI Agent Guidance

### When Working in CLI Module

1. **Respect the Wrapper Pattern**: The main_wrapper exists for a reason - don't try to combine catch-all args with subcommands directly.

2. **Context Management**: Always use `ctx.obj` for passing state between functions.

3. **Output Format Awareness**: Check `output_format` before any display operations.

4. **Error Handling Hierarchy**: Compilation → Execution → Display errors have different handlers.

5. **Interactive vs Non-interactive**: Always check before showing progress or prompts.

6. **Direct Node Reuse** (Task 71): Discovery commands use planning nodes directly - no extraction needed.

### Common Pitfalls to Avoid

1. **Don't Import Execution Directly in __init__**: Use lazy imports to avoid circular dependencies
2. **Don't Show Progress in JSON Mode**: Check output_format first
3. **Don't Assume TTY**: Check interactive mode for progress displays
4. **Don't Mix Output Streams**: Errors to stderr, results to stdout
5. **Don't Forget Parameter Types**: Support type hints in parameters
6. **Don't Extract Node Logic** (Task 71): Use nodes directly, they're designed for standalone execution

### Integration Points to Remember

- **Execution**: Via `execute_workflow()` with CliOutput
- **Planning**: Via PlanningExecutor
- **Registry**: Via Registry.load()
- **Workflow Manager**: Via WorkflowManager for saves
- **Settings**: Via SettingsManager
- **MCP**: Via MCPServerManager and MCPRegistrar
- **Planning Nodes** (Task 71): WorkflowDiscoveryNode, ComponentBrowsingNode, MetadataGenerationNode

### Task 71 Specific Notes

**Anthropic Monkey Patch**:
- Required for discovery commands (WorkflowDiscoveryNode, ComponentBrowsingNode)
- Installed per-command in command groups (bypasses main CLI setup)
- Check for `PYTEST_CURRENT_TEST` to skip during testing

**MCP Tool Normalization**:
- 3-tier matching strategy handles multiple formats
- Ambiguity detection prevents silent failures
- Short form matching requires unique tool names

**Execution State Visibility**:
- Enables intelligent agent repair decisions
- Complete per-node status, timing, cache information
- Additive JSON output (doesn't break existing consumers)

**Helper Function Extraction**:
- Large commands split into focused helper functions
- Improves readability and testability
- Follows single-responsibility principle

This module is the user-facing interface that orchestrates all other pflow components, handling everything from natural language input to structured command execution. Task 71 enhancements make it AI-agent-first while maintaining full backward compatibility.