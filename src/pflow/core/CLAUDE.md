# Core Module

Foundational components for workflow parsing, validation, management, shell integration, error handling, metrics, and settings.

> For JSON auto-parsing and type coercion across the system, see `architecture/core-concepts/data-type-coercion.md`.

## Module Structure

```
src/pflow/core/
├── __init__.py              # Public API exports
├── exceptions.py            # Exception hierarchy
├── ir_schema.py             # IR schema definition and validation
├── json_utils.py            # Shared JSON parsing (try_parse_json, parse_json_or_original)
├── llm_config.py            # Default LLM model detection
├── markdown_parser.py       # .pflow.md → IR dict parser
├── llm_pricing.py           # LLM pricing and cost calculations
├── metrics.py               # Execution metrics collection
├── output_controller.py     # Interactive vs non-interactive output
├── param_coercion.py        # CLI input → declared type coercion
├── security_utils.py        # Sensitive parameter detection and masking
├── settings.py              # Settings with node filtering and env management
├── shell_integration.py     # Unix pipe and stdin handling
├── suggestion_utils.py      # "Did you mean" fuzzy matching
├── user_errors.py           # User-friendly CLI error formatting
├── validation_utils.py      # Parameter name validation (security-aware)
├── workflow_data_flow.py    # Execution order and dependency validation
├── workflow_manager.py      # Workflow lifecycle (save/load/list/delete)
├── workflow_save_service.py # Shared save operations (CLI + MCP)
├── workflow_status.py       # SUCCESS/DEGRADED/FAILED tri-state enum
├── workflow_validator.py    # Unified validation orchestrator
├── smart_filter.py          # Smart filtering for registry/workflow search
├── skill_service.py         # Skill discovery and management
├── execution_cache.py       # Execution caching for workflow runs
└── CLAUDE.md
```

## Key Components — Non-Obvious Details

### exceptions.py

**Exception classes**: `PflowError` (base), `WorkflowExistsError`, `WorkflowNotFoundError`, `WorkflowValidationError`, `CriticalPlanningError`.

**Error handling philosophy**: The codebase uses a pragmatic three-layer pattern:
- Validation phase returns error **strings** (never raises)
- Runtime phase catches exceptions and converts to error **dicts**
- CLI formats errors based on output mode (text/JSON)

See `.taskmaster/tasks/task_59/research/error-handling-patterns.md` for patterns used with nested workflows.

### ir_schema.py

**IR schema quick reference** (the shape agents and the compiler work with):
```python
{
    "ir_version": "0.1.0",                    # Required
    "nodes": [...],                            # Required - at least one
    "edges": [...],                            # Optional - node connections
    "start_node": "node-id",                   # Optional - defaults to first node
    "mappings": {...},                         # Optional - proxy mappings
    "inputs": {...},                           # Optional - workflow input declarations
    "outputs": {...},                          # Optional - workflow output declarations
    "template_resolution_mode": "strict"       # Optional - "strict" or "permissive"
}
# Node: {"id": "unique-id", "type": "node-type", "params": {...}}
```

Validates beyond schema structure: catches duplicate IDs, node reference integrity, and provides fix suggestions.

### markdown_parser.py

Line-by-line state machine: extracts H1 title/description, `## Inputs`/`## Steps`/`## Outputs` sections, `### entity` headings with `- key: value` YAML params and fenced code blocks. Produces same IR dict shape as the old JSON format.

Returns `MarkdownParseResult(ir, title, description, metadata, source)`.

**Validates at parse time**: missing descriptions, bare code blocks, duplicate params, unclosed fences, YAML syntax errors, invalid node IDs, missing `## Steps`.

**Integration points**: CLI (`main.py`), WorkflowManager (`load`/`load_ir`), MCP resolver, runtime executor (nested workflows), workflow save service.

### shell_integration.py

**FIFO-only pipe detection**: `stdin_has_data()` uses `stat.S_ISFIFO()` (NOT `select()`). Returns True only for real shell pipes. Claude Code stdin is a character device → returns False, preventing hangs.

**StdinData three modes**:
- `text_data`: UTF-8 text under 10MB
- `binary_data`: Binary content under 10MB (detected via null byte sampling in first 8KB)
- `temp_path`: Auto-created temp file for content over 10MB

Memory limit configurable via `PFLOW_STDIN_MEMORY_LIMIT`.

**Stdin routing**: Stdin routes to workflow input declared with `"stdin": true`. Routing happens in CLI (`_route_stdin_to_params()`) before input validation. CLI params override piped stdin. Only one input per workflow can have `stdin: true`.

### workflow_manager.py

**Storage format**: `.pflow.md` files with YAML frontmatter for system metadata, stored at `~/.pflow/workflows/`:
```markdown
---
created_at: "2026-01-14T15:43:57.425006+00:00"
updated_at: "2026-01-14T22:03:06.823530+00:00"
version: "1.0.0"
execution_count: 5
last_execution_success: true
last_execution_params:
  repo: "owner/repo"
---

# Fix GitHub Issues

Fixes GitHub issues automatically.

## Steps
...
```

**Non-obvious behaviors**:
- Metadata is flat (no `rich_metadata` wrapper)
- Workflow `name` derived from filename (`my-workflow.pflow.md` → `my-workflow`)
- `description` extracted from H1 prose during `load()`, not stored separately in metadata
- `load()` returns flat metadata dict with parsed IR; `load_ir()` returns just the IR dict (for execution)
- Atomic operations: `os.link()` for creates, `os.replace()` for updates (prevents race conditions — discovered in Task 24)
- **⚠️ `update_ir()` is DEAD CODE** — preserved but unreachable (repair system gated, Task 107)

### workflow_validator.py

Unified validation orchestrator. **Key history**: Replaces scattered validation that existed in multiple places. Previously, tests had data flow validation that production lacked — workflows could pass validation but fail at runtime.

Validates: structural (IR schema) → data flow (execution order, dependencies) → templates (variable resolution) → node types (registry).

### workflow_data_flow.py

Uses Kahn's algorithm for topological sort. Catches: forward references, circular dependencies, references to non-existent nodes, undefined input parameters.

**This validation was previously only in tests, not production** — critical addition that ensures workflows execute correctly at runtime.

### llm_pricing.py

46+ models (Anthropic, OpenAI, Google). 20+ aliases.

**Pricing rules** (Anthropic's model): Cache creation = 2x input rate. Cache reads = 0.1x input rate. Thinking tokens = output rate.

**🐛 Broken aliases**: `"claude-3.5-haiku"` and `"claude-4-opus"` point to non-existent pricing entries.

### metrics.py

**Metrics flow**: LLM calls accumulate in `shared["__llm_calls__"]` → `MetricsCollector` aggregates costs using `calculate_llm_cost()`. Initialize `shared["__llm_calls__"]` as empty list for tracking to work.

### output_controller.py

**5 rules for interactive mode** (ALL must pass):
1. No `-p/--print` flag
2. Output format is not `json`
3. stdin is TTY
4. stdout is TTY
5. Only if all pass → interactive

**Progress indicators**: ✓ success (green), ❌ error (red), ⚠️ warning (yellow), ↻ cached (blue/dimmed), [repaired] modified (cyan).

### settings.py

**Settings location**: `~/.pflow/settings.json`

**Structure**:
```json
{
  "version": "1.0.0",
  "registry": {
    "nodes": { "allow": ["*"], "deny": ["test*", "debug*"] }
  },
  "env": {
    "OPENAI_API_KEY": "sk-proj-...",
    "ANTHROPIC_API_KEY": "sk-ant-..."
  }
}
```

**Env management**: `set_env`/`get_env`/`unset_env`/`list_env(mask_values=True)`. Plain text storage (industry standard for CLI tools — no keyring/encryption).

**Security**: Atomic save (tempfile + `os.replace()`), chmod 600 on save, permission validation warns on insecure files with secrets.

**Input precedence**: CLI params → settings.env → workflow defaults → error.

**Node filtering**: Allow/deny patterns with fnmatch. Filtering happens at Registry **load time**, not storage time. Test nodes hidden by default, exposed via `PFLOW_INCLUDE_TEST_NODES` env var.

### user_errors.py

Three-part error structure: WHAT went wrong (title) → WHY it failed (explanation) → HOW to fix it (suggestions). Specialized: `MCPError`, `PlannerError`, `CompilationError`.

### validation_utils.py

**Forbidden in parameter names**: `$` (template conflict), `|><&;` (shell injection), spaces/tabs (CLI parsing). Allowed: hyphens, dots, numbers at start.

**🚨 Security gaps identified**:
- Template variables NOT validated for dangerous characters
- Node parameters in IR NOT validated
- LLM-extracted parameters NOT validated
- MCP tool parameters NOT validated (external servers could provide dangerous names)

### workflow_save_service.py

**Reserved workflow names**: `null`, `undefined`, `none`, `test`, `settings`, `registry`, `workflow`, `mcp`.

**⚠️ `generate_workflow_metadata()` is GATED** — disabled pending markdown format migration (Task 107).

### security_utils.py

19 sensitive parameter names detected (password, token, api_key, secret, etc.). Case-insensitive matching. Used by MCP error sanitization and CLI rerun display.

### workflow_status.py

Tri-state: `SUCCESS` (all nodes clean), `DEGRADED` (completed with warnings, e.g., unresolved templates in permissive mode), `FAILED` (errors).

## Imports — Not Exported (require direct imports)

These modules are NOT in `__init__.py`:
- `workflow_save_service` — used by CLI and MCP server
- `suggestion_utils` — used by CLI, runtime, formatters, MCP
- `security_utils` — used by MCP errors and CLI display

## Integration Map

| Consumer | Uses from core | Purpose |
|----------|---------------|---------|
| CLI (`cli/main.py`) | shell_integration, WorkflowManager, OutputController, MetricsCollector, UserFriendlyError | Pipe support, saves, display, metrics, error formatting |
| Compiler (`runtime/compiler.py`) | validate_ir, validation_utils, SettingsManager | IR validation, param security, env loading |
| Execution (`execution/`) | WorkflowValidator, OutputController, WorkflowManager | Validation phase, display, metadata updates |
| Planning (`planning/`) | WorkflowValidator, WorkflowManager, CriticalPlanningError | Validation, workflow discovery, error handling |
| Registry (`registry/`) | SettingsManager | Node filtering at load time |
| Runtime (`runtime/instrumented_wrapper.py`) | MetricsCollector, OutputController | LLM usage capture, progress callbacks |
| MCP Server (`mcp_server/`) | workflow_save_service, suggestion_utils, security_utils | Save ops, suggestions, error sanitization |

## Critical Issues

**🚨 Security**: Parameter validation gaps — template variables, node params, LLM/MCP params not validated for shell special characters.

**🐛 Broken**: Two LLM pricing aliases point to non-existent entries.

**⚠️ Gated**: `generate_workflow_metadata()` in workflow_save_service, `update_ir()` in workflow_manager — both gated pending Task 107.

## Key Lessons

**Race condition (Task 24)**: Initial tests were too shallow. Only proper concurrent tests discovered a critical race condition in `WorkflowManager.save()`. Fixed with atomic `os.link()`. Lesson: always test with real threads for file I/O.

**Content preservation**: Save operations store original markdown with YAML frontmatter prepended. The markdown body is never modified by metadata updates.

**Data flow validation gap**: Tests had execution order validation that production lacked — workflows passed validation but failed at runtime. Now unified in `WorkflowValidator`.

See `.taskmaster/tasks/task_24/task-review.md` for detailed WorkflowManager implementation review.

## Testing and Examples

Tests in `tests/test_core/` — comprehensive coverage for all components. See `examples/core/` (valid workflows) and `examples/invalid/` (parse error cases) tested by `test_ir_examples.py`.
