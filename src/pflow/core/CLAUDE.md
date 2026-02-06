# CLAUDE.md - Core Module Documentation

This file provides guidance for understanding and working with the pflow core module, which contains foundational components for workflow validation, shell integration, error handling, and workflow management.

## Module Overview

The `core` module is responsible for:
- **Workflow Management**: Centralized lifecycle management (save/load/list/delete) with format bridging
- **Workflow Parsing**: Parsing `.pflow.md` markdown files into IR dicts
- **Workflow Validation**: Defining and validating the schema for pflow's Intermediate Representation (IR)
- **Shell Integration**: Handling stdin/stdout operations for CLI pipe syntax support
- **Error Handling**: Providing a structured exception hierarchy for the entire pflow system
- **Metrics & Costs**: Tracking execution performance and LLM usage costs
- **Output Control**: Managing interactive vs non-interactive execution modes
- **Settings Management**: Node filtering and configuration with environment overrides
- **User Experience**: User-friendly error formatting with actionable suggestions
- **Public API**: Exposing core functionality through a clean interface
- **JSON Parsing**: Shared JSON parsing infrastructure (`json_utils.py`) used by the template resolver, node wrapper, and batch node. For how these fit together, see `architecture/core-concepts/data-type-coercion.md`.

## Module Structure

```
src/pflow/core/
├── __init__.py              # Public API exports - aggregates functionality from all modules
├── exceptions.py            # Custom exception hierarchy for structured error handling
├── ir_schema.py             # IR schema definition and validation for workflow IR
├── json_utils.py            # Shared JSON parsing utilities (try_parse_json, parse_json_or_original)
├── llm_config.py            # LLM model configuration
├── markdown_parser.py       # Markdown workflow parser (.pflow.md → IR dict)
├── llm_pricing.py           # Centralized LLM pricing and cost calculations
├── metrics.py               # Lightweight metrics collection for workflow execution
├── output_controller.py     # Central output control for interactive vs non-interactive modes
├── param_coercion.py        # Parameter type coercion (CLI inputs → declared types)
├── security_utils.py        # Sensitive parameter detection and masking
├── settings.py              # Settings management with node filtering
├── shell_integration.py     # Unix pipe and stdin/stdout handling for CLI integration
├── suggestion_utils.py      # "Did you mean" suggestions for user input
├── user_errors.py           # User-friendly error formatting for CLI
├── validation_utils.py      # Shared validation utilities for parameters
├── workflow_data_flow.py    # Data flow and execution order validation
├── workflow_manager.py      # Workflow lifecycle management (.pflow.md with YAML frontmatter)
├── workflow_save_service.py # Shared workflow save operations (CLI/MCP)
├── workflow_status.py       # Tri-state workflow execution status enum
├── workflow_validator.py    # Unified workflow validation orchestrator
└── CLAUDE.md               # This file
```

## Key Components

### 1. exceptions.py - Error Handling Infrastructure

Defines the exception hierarchy used throughout pflow:

**Exception Classes**:
- **`PflowError`**: Base exception for all pflow-specific errors (base class for all others)
- **`WorkflowExistsError`**: Raised when saving a workflow that already exists
- **`WorkflowNotFoundError`**: Raised when loading a workflow that doesn't exist
- **`WorkflowValidationError`**: Raised when workflow validation fails
- **`CriticalPlanningError`**: Raised when a planning node fails critically (used by 5 planning nodes)

**Usage Pattern**:
```python
from pflow.core.exceptions import WorkflowNotFoundError

try:
    workflow = manager.load("missing-workflow")
except WorkflowNotFoundError:
    print("Workflow not found")
```

**Error Handling Philosophy**:
The codebase uses a pragmatic error dict pattern rather than a complex exception hierarchy:
- Validation phase returns error strings (never raises)
- Runtime phase catches exceptions and converts to error dicts
- CLI formats errors based on output mode (text/JSON)

See `.taskmaster/tasks/task_59/research/error-handling-patterns.md` for patterns to use when implementing nested workflows.

### 2. ir_schema.py - Workflow Definition and Validation

The heart of workflow representation in pflow:

**Core Components**:
- **`FLOW_IR_SCHEMA`**: JSON Schema (Draft 7) enforcing IR structure
- **`ValidationError`**: Custom exception with helpful error messages and suggestions
- **`validate_ir()`**: Main validation function supporting dict input

**Schema Structure**:
```python
{
    "ir_version": "0.1.0",                    # Required - semantic versioning
    "nodes": [...],                          # Required - at least one node
    "edges": [...],                          # Optional - defines connections
    "start_node": "node-id",                 # Optional - defaults to first node
    "mappings": {...},                       # Optional - proxy mappings
    "inputs": {...},                         # Optional - workflow input declarations
    "outputs": {...},                        # Optional - workflow output declarations
    "template_resolution_mode": "strict"     # Optional - "strict" or "permissive", defaults to settings/strict
}
```

**Node Structure**:
```python
{
    "id": "unique-id",          # Required - unique within flow
    "type": "node-type",        # Required - references registry
    "params": {...}             # Optional - node configuration
}
```

**Input/Output Declarations** (for workflows):
```python
"inputs": {
    "api_key": {
        "type": "string",
        "description": "API authentication key",
        "required": true
    }
}
```

**Validation Features**:
- JSON Schema structural validation (on the IR dict)
- Business logic checks (node reference integrity, duplicate ID detection)
- Helpful error messages with fix suggestions

### 3. markdown_parser.py - Markdown Workflow Parser

Parses `.pflow.md` files into IR dicts. This is the primary entry point for all workflow loading — replaces `json.load()` throughout the codebase.

**Key Components**:
- **`parse_markdown(content: str) -> MarkdownParseResult`**: Main parsing function
- **`MarkdownParseError(ValueError)`**: Parse error with `line` and `suggestion` fields
- **`MarkdownParseResult`**: Dataclass with `ir`, `title`, `description`, `metadata`, `source`

**How it works**: Line-by-line state machine that extracts H1 title/description, `## Inputs`/`## Steps`/`## Outputs` sections, `### entity` headings with `- key: value` YAML params and fenced code blocks. Produces the same IR dict shape that JSON workflows produced. Delegates YAML parsing to `yaml.safe_load()`, Python syntax validation to `ast.parse()`.

**Parser validates at parse time**: missing descriptions, bare code blocks, duplicate params, unclosed fences, YAML syntax errors, invalid node IDs, missing `## Steps` section.

**Integration points**: Used by CLI (`cli/main.py`), WorkflowManager (`load`/`load_ir`), MCP resolver, runtime executor (nested workflows), and workflow save service.

### 4. shell_integration.py - CLI and Unix Pipe Support

Enables pflow to work seamlessly in Unix pipelines:

**Key Classes**:
- **`StdinData`**: Container for different stdin content types
  - `text_data`: UTF-8 text (under memory limit)
  - `binary_data`: Binary content (under memory limit)
  - `temp_path`: Path to temp file (for large content)

**Core Functions**:
- **`detect_stdin()`**: Checks if stdin is piped (not TTY)
- **`stdin_has_data()`**: FIFO-only pipe detection - returns True only for real shell pipes
  - Uses `stat.S_ISFIFO()` to detect real pipes (avoids hanging on sockets/char devices)
  - Claude Code stdin is a character device, not FIFO - returns False (prevents hang)
- **`read_stdin_enhanced()`**: Reads stdin with binary/size handling

**Stdin Routing** (Task 115):
- Stdin is routed to workflow inputs via `"stdin": true` declaration
- Routing happens in CLI (`_route_stdin_to_params()`) before input validation
- CLI parameters override piped stdin
- Only one input per workflow can have `stdin: true`

**Memory Management**:
- Default limit: 10MB (configurable via `PFLOW_STDIN_MEMORY_LIMIT`)
- Automatic temp file creation for large inputs
- Binary detection using null byte sampling in first 8KB

### 4. workflow_manager.py - Workflow Lifecycle Management

Centralizes all workflow operations:

**Key Features**:
- **Markdown Storage**: Saved workflows are `.pflow.md` files with YAML frontmatter for system metadata
- **Atomic Operations**: Thread-safe file operations prevent race conditions
- **Name-Based References**: Workflows referenced by kebab-case names (e.g., "fix-issue")
- **Storage Location**: `~/.pflow/workflows/*.pflow.md`

**Core Methods**:
- **`save(name, markdown_content, metadata)`**: Prepends YAML frontmatter to markdown content, saves atomically
- **`load(name)`**: Returns flat metadata dict with parsed IR, description, and execution stats
- **`load_ir(name)`**: Returns just the IR dict (for WorkflowExecutor)
- **`list_all()`**: Lists all saved workflows with metadata
- **`exists(name)`**: Checks if workflow exists
- **`delete(name)`**: Removes workflow
- **`get_path(name)`**: Returns absolute file path
- **`update_metadata(name, updates)`**: Updates YAML frontmatter without modifying the markdown body
- **`update_ir(name, new_ir)`**: **⚠️ DEAD CODE** — preserved but unreachable (repair system gated, Task 107)

**Storage Format**: YAML frontmatter + original markdown content:
```markdown
---
created_at: "2026-01-14T15:43:57.425006+00:00"
updated_at: "2026-01-14T22:03:06.823530+00:00"
version: "1.0.0"
execution_count: 5
last_execution_timestamp: "2026-01-14T15:30:00"
last_execution_success: true
last_execution_params:
  repo: "owner/repo"
---

# Fix GitHub Issues

Fixes GitHub issues automatically.

## Steps
...
```

**Note**: Metadata is flat (no `rich_metadata` wrapper). The workflow `name` is derived from the filename (`my-workflow.pflow.md` → `my-workflow`). The `description` is extracted from the H1 prose during `load()`, not stored separately in metadata.

### 5. workflow_validator.py - Unified Validation System

Provides a single source of truth for all workflow validation:

**Key Class**:
- **`WorkflowValidator`**: Orchestrates all validation checks

**Core Method**:
```python
@staticmethod
def validate(
    workflow_ir: dict[str, Any],
    extracted_params: Optional[dict[str, Any]] = None,
    registry: Optional[Registry] = None,
    skip_node_types: bool = False
) -> list[str]
```

**Validation Types**:
1. **Structural validation**: IR schema compliance (via `validate_ir`)
2. **Data flow validation**: Execution order and dependencies (via `workflow_data_flow`)
3. **Template validation**: Variable resolution (via `TemplateValidator`)
4. **Node type validation**: Registry verification

**Critical Design Decision**: This replaces scattered validation logic that existed in multiple places (ValidatorNode, tests) with a unified system. Previously, tests had data flow validation that production lacked!

### 6. workflow_data_flow.py - Execution Order Validation

Ensures workflows will execute correctly at runtime:

**Key Functions**:
- **`build_execution_order(workflow_ir)`**: Creates topological sort of nodes
- **`validate_data_flow(workflow_ir)`**: Validates all data dependencies

**What It Catches**:
- Forward references (node referencing future node's output)
- Circular dependencies
- References to non-existent nodes
- Undefined input parameters

**Critical Addition**: This validation was previously only in tests, not production. This could lead to workflows passing validation but failing at runtime.

**Algorithm**: Uses Kahn's algorithm for topological sort to determine valid execution order.

### 7. llm_pricing.py - Centralized LLM Cost Calculations

Single source of truth for all LLM pricing and cost calculations:

**Key Components**:
- **`MODEL_PRICING`**: Dictionary with pricing for 46+ models (Anthropic, OpenAI, Google)
- **`MODEL_ALIASES`**: 20+ common aliases mapping (e.g., "4o" → "gpt-4o")
- **`calculate_llm_cost()`**: Calculate costs with cache and thinking token support

**Pricing Rules** (Anthropic's model):
- Regular input/output: Standard model rates
- Cache creation: 2x input rate (100% premium)
- Cache reads: 0.1x input rate (90% discount)
- Thinking tokens: Output rate

**Known Issues**:
- **⚠️ 2 Broken Aliases**: `"claude-3.5-haiku"` and `"claude-4-opus"` point to non-existent pricing entries
- Missing models referenced in docs: `claude-opus-4-1-20250805`

**Usage Pattern**:
```python
cost_breakdown = calculate_llm_cost(
    model="anthropic/claude-sonnet-4-0",
    input_tokens=1000,
    output_tokens=500,
    cache_read_tokens=2000
)
# Returns: {"total_cost_usd": 0.001234, ...}
```

### 8. metrics.py - Execution Metrics Collection

Lightweight metrics aggregation for tracking performance and costs:

**Key Class**:
- **`MetricsCollector`**: Tracks planner vs workflow execution phases

**Features**:
- Separate timing for planner and workflow phases
- Per-node execution duration tracking
- LLM token usage and cost aggregation
- Cache efficiency metrics (cache hit rate)
- Thinking token utilization tracking

**Metrics Flow**:
1. LLM calls accumulate in `shared["__llm_calls__"]`
2. MetricsCollector aggregates costs using `calculate_llm_cost()`
3. Summary includes phase breakdown and performance metrics

### 9. output_controller.py - Interactive Mode Management

Controls output behavior based on execution context:

**Key Class**:
- **`OutputController`**: Determines interactive vs non-interactive mode

**5 Rules for Interactive Mode**:
1. If `-p/--print` flag → non-interactive
2. If output format is `json` → non-interactive
3. If stdin is not TTY → non-interactive
4. If stdout is not TTY → non-interactive
5. Only if all pass → interactive

**Progress Indicators**:
- ✓ Success (green), ❌ Error (red), ⚠️ Warning (yellow)
- ↻ Cached (blue, dimmed), [repaired] Modified (cyan)

### 10. workflow_status.py - Tri-State Workflow Status

Defines execution status outcomes for better observability:

**Key Enum**:
- **`WorkflowStatus`**: SUCCESS/DEGRADED/FAILED tri-state status
  - `SUCCESS`: All nodes completed without warnings
  - `DEGRADED`: Completed but with warnings (e.g., unresolved templates in permissive mode)
  - `FAILED`: Workflow failed due to errors

### 11. settings.py - Settings Management & API Key Storage

Manages settings with environment variable override support and secure API key storage:

**Key Classes**:
- **`SettingsManager`**: Manages `~/.pflow/settings.json`
- **`PflowSettings`**: Settings data model with registry and env fields
- **`RuntimeSettings`**: Runtime configuration including `template_resolution_mode` ("strict"/"permissive")

**Features**:
- **Node Filtering**: Allow/deny patterns with fnmatch support
- **Test Node Filtering**: `PFLOW_INCLUDE_TEST_NODES` env var override
- **MCP Pattern Matching**: Aliases for MCP node filtering
- **API Key Management**: Secure storage of API keys and secrets (Task 80)
- **Atomic Operations**: Temp file + os.replace() pattern for crash safety
- **Secure Permissions**: Automatic chmod 600 on save (owner read/write only)
- **Permission Validation**: Warns if file has insecure permissions with secrets

**Settings Structure**:
```json
{
  "version": "1.0.0",
  "registry": {
    "nodes": {
      "allow": ["*"],
      "deny": ["test*", "debug*"]
    }
  },
  "env": {
    "OPENAI_API_KEY": "sk-proj-...",
    "ANTHROPIC_API_KEY": "sk-ant-...",
    "replicate_api_token": "r8_..."
  }
}
```

**Environment Variable Management** (Added in Task 80):
- `set_env(key, value)` - Store API keys and secrets
- `unset_env(key) → bool` - Remove keys (idempotent)
- `get_env(key, default) → Optional[str]` - Retrieve stored values
- `list_env(mask_values=True) → dict` - List keys (masked by default for security)
- `_mask_value(value) → str` [static] - Value masking (first 3 chars + ***)

**Security Implementation**:
```python
# Atomic save with secure permissions
temp_fd, temp_path = tempfile.mkstemp(
    dir=self.settings_path.parent,
    prefix=".settings.",
    suffix=".tmp"
)
try:
    with open(temp_fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, self.settings_path)  # Atomic
    os.chmod(self.settings_path, 0o600)         # Secure permissions
except Exception:
    Path(temp_path).unlink(missing_ok=True)     # Cleanup
    raise
```

**Workflow Integration**: Settings.env values automatically populate workflow inputs via:
1. Compiler loads settings.env (`compiler.py:_validate_workflow()`)
2. Validator uses env values (`workflow_validator.py:prepare_inputs()`)
3. Precedence: CLI params → settings.env → workflow defaults → error

**Usage Pattern**:
```python
# Set API keys (automatically secure with 600 permissions)
manager = SettingsManager()
manager.set_env("OPENAI_API_KEY", "sk-...")
manager.set_env("replicate_api_token", "r8_...")

# Values automatically populate workflow inputs
# No need to pass via --param every time!

# List keys (masked for security)
env_vars = manager.list_env()  # {"OPENAI_API_KEY": "sk-***", ...}

# Show full values (debugging only)
env_vars = manager.list_env(mask_values=False)
```

**Security Properties**:
- File permissions always 600 (owner-only access)
- Atomic operations prevent corruption during crashes
- Value masking reduces accidental exposure
- Permission validation warns on insecure files
- Plain text storage (industry standard for CLI tools)

### 12. user_errors.py - User-Friendly Error Formatting

Provides structured, actionable error messages for CLI users:

**Key Class**:
- **`UserFriendlyError`**: Base class with three-part structure
  1. WHAT went wrong (title)
  2. WHY it failed (explanation)
  3. HOW to fix it (suggestions)

**Specialized Errors**:
- **`MCPError`**: Used in MCP nodes for tool availability issues
- **`PlannerError`**: Used in planning system for planning failures
- **`CompilationError`**: Used in compiler for workflow compilation issues

### 13. validation_utils.py - Parameter Validation Utilities

Security-aware parameter name validation:

**Key Functions**:
- **`is_valid_parameter_name()`**: Validates parameter names for security
- **`get_parameter_validation_error()`**: Descriptive error messages with guidance

**Security Rules** (prevents injection attacks):
- **Forbidden**: `$` (template conflict), `|><&;` (shell injection), spaces/tabs (CLI parsing)
- **Allowed**: Hyphens, dots, numbers at start (e.g., `api-key`, `2fa.token`)

**Current Usage** (3 locations):
- ✅ CLI parameter processing (`cli/main.py:503`)
- ✅ Workflow input validation (`runtime/workflow_validator.py:35`)
- ✅ Workflow output validation (`runtime/compiler.py:515`)

**Security Gaps Identified**:
- **🚨 Template variables NOT validated** - Could contain dangerous characters
- **🚨 Node parameters in IR NOT validated** - Could bypass security
- **🚨 LLM-extracted parameters NOT validated** - Could suggest dangerous names
- **🚨 MCP tool parameters NOT validated** - External servers could provide dangerous names

### 14. workflow_save_service.py - Shared Save Operations

Unified workflow save/load/validation for CLI and MCP server:

**Key Functions**:
- **`validate_workflow_name()`**: Name format validation (lowercase, numbers, hyphens; max 50 chars)
- **`load_and_validate_workflow()`**: Multi-source loading (file/name) with normalization
- **`save_workflow_with_options(name, markdown_content, *, force, metadata)`**: Save with force overwrite handling
- **`generate_workflow_metadata()`**: **⚠️ GATED** — disabled pending markdown format migration (Task 107)
- **`delete_draft_safely()`**: Security-aware deletion (`.pflow/workflows/` only)

**Reserved Names**: Set of 9 (`null`, `undefined`, `none`, `test`, `settings`, `registry`, `workflow`, `mcp`)

**Usage**: CLI (`commands/workflow.py`), MCP server (`services/execution_service.py`)

### 15. suggestion_utils.py - User Input Suggestions

"Did you mean" logic for user-friendly error messages:

**Key Functions**:
- **`find_similar_items()`**: Find matches using substring or fuzzy (difflib) matching
- **`format_did_you_mean()`**: Format suggestions as user message

**Usage**: CLI (`mcp.py`), Runtime (`compiler.py`), Formatters (`registry_run_formatter.py`), MCP (`resolver.py`, `workflow_service.py`)

### 16. security_utils.py - Sensitive Parameter Detection

Security utilities for credential masking:

**Key Items**:
- **`SENSITIVE_KEYS`**: Set of 19 sensitive parameter names (password, token, api_key, secret, etc.)
- **`is_sensitive_parameter()`**: Check if name indicates sensitive data (case-insensitive)
- **`mask_sensitive_value()`**: Mask value if parameter is sensitive

**Usage**: MCP errors (`utils/errors.py`), CLI display (`rerun_display.py`)

### 17. __init__.py - Public API

Aggregates and exposes the module's functionality:

**Note**: The following modules are NOT exported (direct imports required):
- `workflow_save_service` - Used by CLI and MCP server only
- `suggestion_utils` - Used by CLI, runtime, formatters, MCP
- `security_utils` - Used by MCP errors and CLI display

**Exported from exceptions.py**:
- `PflowError` (base class for all pflow errors)

**Exported from ir_schema.py**:
- `FLOW_IR_SCHEMA`
- `ValidationError`
- `validate_ir`

**Exported from llm_pricing.py**:
- `MODEL_PRICING`
- `PRICING_VERSION`
- `calculate_llm_cost`
- `get_model_pricing`

**Exported from shell_integration.py**:
- `StdinData`
- `detect_stdin`
- `detect_binary_content`
- `read_stdin`
- `read_stdin_enhanced`
- `read_stdin_with_limit`
- `stdin_has_data`

**Exported from workflow_data_flow.py**:
- `CycleError`
- `build_execution_order`
- `validate_data_flow`

**Exported from workflow_validator.py**:
- `WorkflowValidator`

## Connection to Examples

The `examples/` directory contains real-world usage of the IR schema, all in `.pflow.md` format:

### Valid Examples (tested by test_ir_examples.py)
- **`examples/core/minimal.pflow.md`** - Demonstrates minimum requirements (single node workflow)
- **`examples/core/simple-pipeline.pflow.md`** - Shows basic edge connections (read → copy → write)
- **`examples/core/template-variables.pflow.md`** - Uses `${variable}` substitution throughout workflow
- **`examples/core/error-handling.pflow.md`** - Action-based routing with error and retry paths
- **`examples/core/proxy-mappings.pflow.md`** - Interface adaptation using mappings section

### Invalid Examples (demonstrate markdown parse errors)
- **`examples/invalid/missing-steps.pflow.md`** - No `## Steps` section
- **`examples/invalid/missing-type.pflow.md`** - Node without `- type:` param
- **`examples/invalid/missing-description.pflow.md`** - Entity without prose description
- **`examples/invalid/unclosed-fence.pflow.md`** - Unclosed code block
- **`examples/invalid/bare-code-block.pflow.md`** - Code block without tag
- **`examples/invalid/duplicate-param.pflow.md`** - Same param inline + code block
- **`examples/invalid/duplicate-ids.pflow.md`** - Two nodes with same heading
- **`examples/invalid/yaml-syntax-error.pflow.md`** - Bad YAML in params

## Common Usage Patterns

### Managing Workflow Lifecycle
```python
from pflow.core import WorkflowManager, WorkflowExistsError

workflow_manager = WorkflowManager()

# Save a workflow (pass original markdown content, not IR dict)
try:
    path = workflow_manager.save("data-pipeline", markdown_content)
    print(f"Saved to: {path}")
except WorkflowExistsError:
    print("Workflow already exists!")

# Load for different purposes
metadata = workflow_manager.load("data-pipeline")  # Flat metadata dict with IR
workflow_ir = workflow_manager.load_ir("data-pipeline")  # Just IR for execution

# List all workflows
for wf in workflow_manager.list_all():
    print(f"{wf['name']}: {wf['description']}")
```

### Validating Workflow IR
```python
from pflow.core import validate_ir, ValidationError

try:
    validated_ir = validate_ir(workflow_dict)
except ValidationError as e:
    print(f"Validation failed: {e}")
    # Error includes path and suggestions
```

### Handling Stdin in CLI
```python
from pflow.core import detect_stdin, read_stdin_enhanced

if detect_stdin():
    stdin_data = read_stdin_enhanced()
    if stdin_data.text_data:
        # Handle text input
    elif stdin_data.binary_data:
        # Handle binary input
    elif stdin_data.temp_path:
        # Handle large file
```

### Error Handling
```python
from pflow.core.exceptions import WorkflowNotFoundError, WorkflowValidationError

try:
    workflow_ir = workflow_manager.load_ir("missing-workflow")
except WorkflowNotFoundError as e:
    print(f"Workflow not found: {e}")

try:
    workflow_manager.save("existing-name", content)
except WorkflowExistsError as e:
    print(f"Already exists: {e}")
```

**Note**: Runtime errors use error dicts, not exceptions. See `.taskmaster/tasks/task_59/research/error-handling-patterns.md` for the error dict pattern.

## Extending the Schema

When adding new features to the IR format:

1. **Update ir_schema.py**:
   - Add new fields to FLOW_IR_SCHEMA
   - Mark new fields as optional for backward compatibility
   - Add validation logic if needed beyond JSON schema

2. **Update Documentation**:
   - Update `architecture/core-concepts/schemas.md` with new fields
   - Add examples showing the new feature
   - Update version compatibility notes

3. **Add Tests**:
   - Add test cases to `tests/test_core/test_ir_schema.py`
   - Create example files demonstrating the feature
   - Test both valid and invalid usage

## Testing

Each component has comprehensive test coverage:
- `tests/test_core/test_exceptions.py` - Exception behavior and formatting
- `tests/test_core/test_ir_schema.py` - Schema validation edge cases
- `tests/test_core/test_markdown_parser.py` - Markdown parser (70 tests, 15 categories)
- `tests/test_core/test_shell_integration.py` - Stdin handling scenarios
- `tests/test_core/test_ir_examples.py` - Real-world example validation
- `tests/test_core/test_workflow_validator.py` - Unified validation system tests
- `tests/test_core/test_workflow_data_flow.py` - Execution order and dependency validation
- `tests/test_core/test_workflow_manager.py` - Concurrent access and atomic operations
- `tests/test_core/test_metrics.py` - Metrics aggregation and cost calculation
- `tests/test_core/test_metrics_thinking_cache.py` - Cache and thinking token metrics
- `tests/test_core/test_settings.py` - Settings management and node filtering
- `tests/test_core/test_output_controller.py` - Interactive mode detection
- `tests/test_core/test_user_errors.py` - User-friendly error formatting
- `tests/test_core/test_validation_utils.py` - Parameter validation
- `tests/test_core/test_workflow_save_service.py` - Workflow save operations
- `tests/test_core/test_suggestion_utils.py` - Suggestion utilities

### Running Tests
```bash
# Run all core module tests
pytest tests/test_core/

# Run specific test file
pytest tests/test_core/test_ir_schema.py -v
```

## Integration Points

The core module is used throughout pflow:
- **CLI** (`cli/main.py`):
  - Uses shell integration for pipe support
  - Uses WorkflowManager for saving workflows after execution
  - Uses OutputController for interactive mode detection
  - Uses MetricsCollector for tracking execution performance
  - Handles UserFriendlyError formatting with `format_for_cli()`
- **Compiler** (`runtime/compiler.py`): Validates IR before compilation
- **Context Builder** (`planning/context_builder.py`): Uses WorkflowManager.list_all() for workflow discovery
- **WorkflowExecutor** (`runtime/workflow_executor.py`): Uses WorkflowManager.load_ir() for name-based workflow loading
- **Registry** (`registry/registry.py`): Uses SettingsManager for node filtering
- **Execution Module** (`execution/`):
  - Uses WorkflowValidator in validation phase
  - Creates CliOutput wrapping OutputController
  - Updates WorkflowManager metadata after execution
- **Planning Nodes** (`planning/nodes.py`):
  - Uses WorkflowValidator for validation
  - Raises CriticalPlanningError for unrecoverable failures
- **InstrumentedNodeWrapper** (`runtime/instrumented_wrapper.py`):
  - Captures LLM usage for MetricsCollector
  - Calls progress callbacks from OutputController
- **Repair Service** (`execution/repair_service.py`): Uses WorkflowValidator to validate repairs
- **Tests** (`tests/test_planning/llm/prompts/`): Now use WorkflowValidator for production-consistent validation
- **Nodes**: Use exceptions for error reporting, MCPError for MCP issues
- **MCP Server** (`mcp_server/`):
  - Uses `workflow_save_service` for workflow save operations
  - Uses `suggestion_utils` for tool/workflow suggestions
  - Uses `security_utils` for error sanitization

## Design Decisions

1. **Stdin Routing**: Stdin data routed to workflow inputs via `stdin: true` declarations
2. **Memory-Aware**: Handles large inputs without exhausting memory (10MB default, temp files for larger)
3. **Helpful Errors**: ValidationError includes paths and fix suggestions; UserFriendlyError follows WHAT-WHY-HOW structure
4. **Clean API**: __init__.py provides single import point for consumers
5. **Type Annotations**: Full type hints for better IDE support
6. **Markdown Storage**: WorkflowManager stores `.pflow.md` files with YAML frontmatter for metadata
7. **Atomic Operations**: WorkflowManager uses `os.link()` for creates, `os.replace()` for updates
8. **Kebab-Case Names**: Workflow names use kebab-case for CLI friendliness (e.g., "fix-issue")
9. **Unified Validation**: WorkflowValidator provides single source of truth for all validation
10. **Data Flow Validation**: Critical addition that ensures workflows will execute correctly at runtime
11. **Centralized Pricing**: Single llm_pricing.py module for all cost calculations with cache token support
12. **Interactive Mode Rules**: 5-rule hierarchy determines output behavior (print flag, json format, TTY detection)
13. **Settings Filtering**: Node visibility controlled at Registry load time, not storage time
14. **Test Node Isolation**: Test nodes hidden by default, exposed only via environment variable
15. **Security-Aware Validation**: Parameter names disallow shell special characters for safety

## Best Practices

1. **Always validate early**: Validate IR as soon as it's loaded or generated using WorkflowValidator
2. **Use helpful error messages**: UserFriendlyError for CLI, include fix suggestions in ValidationError
3. **Test edge cases**: Ensure validation catches all invalid states (missing fields, wrong types, bad references)
4. **Keep examples updated**: Examples serve as both documentation and tests - maintain them carefully
5. **Building MVP**: We do not need to worry about backward compatibility for now, no migrations are needed
6. **Handle stdin modes explicitly**: Stdin is routed to workflow inputs via `stdin: true` declarations
7. **Preserve error context**: Use appropriate exception classes (though note some are underutilized)
8. **Use WorkflowManager for all workflow operations**: Don't implement custom file loading/saving
9. **Test concurrent access**: Always test with real threads when dealing with file operations
10. **Handle load variants**: Use load() for metadata needs, load_ir() for execution needs
11. **Track metrics properly**: Initialize `shared["__llm_calls__"]` list for LLM usage tracking
12. **Use OutputController**: Create once, reuse throughout CLI command execution
13. **Update pricing promptly**: Keep MODEL_PRICING current as providers change rates
14. **Filter at load time**: SettingsManager filters nodes when Registry loads, not when scanning
15. **Validate parameter names**: Use validation_utils for security-aware parameter validation

## Related Documentation

- **Shell Pipes**: `architecture/features/shell-pipes.md` - Unix pipe integration details
- **Schemas**: `architecture/core-concepts/schemas.md` - Conceptual schema overview
- **Examples**: `examples/` - Valid and invalid workflow examples
- **Runtime**: `src/pflow/runtime/compiler.py` - How validation fits execution
- **Task 24 Review**: `.taskmaster/tasks/task_24/task-review.md` - Comprehensive WorkflowManager implementation details
- **Workflow Management**: All workflow lifecycle operations should use WorkflowManager

## Critical Issues and Gaps

### 🚨 Security Vulnerabilities
1. **Parameter Validation Gaps**: Template variables, node parameters, and LLM/MCP parameters not validated for dangerous characters
2. **Shell Injection Risk**: Unvalidated parameters could contain shell special characters

### 🐛 Active Bugs
1. **Broken LLM Aliases**: Two aliases point to non-existent pricing entries

### ⚠️ Gated Code
1. **Repair System**: `update_ir()` in workflow_manager.py is preserved but unreachable (gated by Task 107)

**Note**: Dead exception classes and unused functions were removed in Feb 2026 cleanup. Error handling patterns for nested workflows (Task 59) are documented in `.taskmaster/tasks/task_59/research/error-handling-patterns.md`.

## Key Lessons from Task 24

1. **The Race Condition Discovery**: Initial tests were too shallow. Only when proper concurrent tests were written was a critical race condition discovered in WorkflowManager.save(). This was fixed using atomic file operations with os.link().

2. **Content Preservation is Critical**: Save operations store the original markdown content with YAML frontmatter prepended. The markdown body is never modified by metadata updates. WorkflowManager handles frontmatter read-modify-write transparently.

3. **Test Quality Matters**: Always write real tests with actual threading, file I/O, and error conditions. Mocking too much can hide real bugs.

4. **Data Flow Validation Gap**: Tests had execution order validation that production lacked - workflows could pass validation but fail at runtime with forward references or circular dependencies.

Remember: This module provides the foundation for pflow's reliability and CLI-first design. Changes here affect the entire system, so verify thoroughly against existing tests and usage patterns.
