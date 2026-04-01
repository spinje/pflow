# Core Module

Foundational components for workflow parsing, validation, management, shell integration, error handling, metrics, and settings.

> For JSON auto-parsing and type coercion across the system, see `architecture/core-concepts/data-type-coercion.md`.

## Module Structure

```
src/pflow/core/
├── __init__.py              # Public API exports
├── node.py                  # Node lifecycle primitives (BaseNode, Node, wiring operators)
├── exceptions.py            # Exception hierarchy (incl. CompilationError, MaxNodeVisitsError)
├── ir_schema.py             # IR schema definition and validation
├── json_utils.py            # Shared JSON parsing (try_parse_json, parse_json_or_original)
├── llm_config.py            # LLM model resolution, env injection, provider detection
├── markdown_parser.py       # .pflow.md → IR dict parser
├── llm_pricing.py           # LLM pricing and cost calculations
├── metrics.py               # Execution metrics collection
├── output_controller.py     # Interactive vs non-interactive output
├── param_coercion.py        # Type coercion: MCP (dict→JSON str) and CLI (str→declared type)
├── security_utils.py        # Sensitive parameter detection and masking
├── settings.py              # Settings with node filtering and env management
├── shell_integration.py     # Unix pipe and stdin handling
├── suggestion_utils.py      # "Did you mean" fuzzy matching
├── user_errors.py           # User-friendly CLI error formatting
├── validation_utils.py      # Parameter name validation (security-aware)
├── llm_utils.py             # Shared LLM response parsing (parse_structured_response)
├── prompt_utils.py          # Prompt loading and formatting (load_prompt, format_prompt)
├── execution_cache.py       # Two-phase execution cache for registry run
├── trace_report.py          # Execution report generation (--report flag, per-node .md files)
├── file_resolver.py         # External file reference detection and resolution
├── workflow/                # Workflow lifecycle subdirectory (see workflow/CLAUDE.md)
│   ├── __init__.py          # Re-exports public API
│   ├── manager.py           # Workflow lifecycle (save/load/list/delete)
│   ├── save_service.py      # Shared save operations (CLI + MCP)
│   ├── validator.py         # Unified validation orchestrator
│   ├── data_flow.py         # Execution order and dependency validation
│   ├── status.py            # SUCCESS/DEGRADED/FAILED tri-state enum
│   ├── skill_service.py     # Publish workflows as AI agent skills (symlinks)
│   ├── context.py           # Workflow context for discovery (build_workflows_context)
│   ├── discovery.py         # LLM-powered workflow discovery (discover_workflow)
│   └── prompts/
│       └── discovery.md     # Workflow discovery prompt template
└── CLAUDE.md
```

## Key Components — Non-Obvious Details

### exceptions.py

**Exception classes** — canonical home for all pflow exceptions. Hierarchy:
```
PflowError(Exception)                    <- base for all pflow errors
  |- SchemaValidationError               <- IR schema validation (message, path, suggestion)
  |- MarkdownParseError                  <- .pflow.md parse errors (line, suggestion)
  |- CompilationError                    <- IR compilation (phase, node_id, node_type, suggestion)
  |- WorkflowValidationError             <- pre-execution validation (summary, validation_errors, format_for_cli())
  |- WorkflowNotFoundError               <- workflow lookup (workflow_name, similar_names, hint, format_for_cli())
  |- WorkflowExistsError                 <- duplicate workflow save
  |- CriticalDiscoveryError              <- discovery abort (node_name, reason)
  |- UserFriendlyError                   <- user_errors.py (title, explanation, suggestions, format_for_cli())
  |   |- MCPError                        <- user_errors.py
  |   |- OutputResolutionError           <- user_errors.py (failures list)
MaxNodeVisitsError(RuntimeError)         <- intentionally NOT PflowError (loop guard)
```
`except PflowError` catches all pflow-specific exceptions except `MaxNodeVisitsError`. All exception imports should use `from pflow.core.exceptions import ClassName` (canonical path). Re-exports exist in `ir_schema.py` (`SchemaValidationError as ValidationError`) and `markdown_parser.py` (`MarkdownParseError`) for backward compatibility.

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

**Routing syntax**: `- next: node-id` (static routing), `- next: end` (terminal), `- on-error: node-id` (error routing). These are extracted from params into routing metadata during `_build_node_dict()` and used by `_build_edges()` to generate edges with action fields. Python code blocks are AST-scanned for `next: str = "literal"` assignments to generate additional routing edges.

**Branch target validation**: After edge generation, the parser validates that all branch targets (nodes reached via named action edges or `- on-error:` edges) have explicit `- next:` directives. Also validates that non-router nodes don't fall through into branch targets via document order, and that dynamic `next` assignments in code have corresponding `- next:` declarations. Raises `MarkdownParseError` with actionable fix suggestions.

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

### workflow/

See `workflow/CLAUDE.md` for per-file details (storage format, validation pipeline, data flow algorithm, skill publishing, known issues).

### llm_pricing.py

46+ models (Anthropic, OpenAI, Google). 20+ aliases.

**Pricing rules** (Anthropic's model): Cache creation = 2x input rate. Cache reads = 0.1x input rate. Thinking tokens = output rate.

**🐛 Broken aliases**: `"claude-3.5-haiku"` and `"claude-4-opus"` point to non-existent pricing entries.

### llm_config.py

**Two different resolution chains** — easy to call the wrong one:
- `get_model_for_feature("discovery"|"filtering")`: feature setting → `default_model` → auto-detect (Anthropic → Gemini → OpenAI) → hardcoded fallback. **Never returns None.**
- `get_default_workflow_model()`: `default_model` → llm CLI default (`llm models default`) → auto-detect → **None** (caller must handle).

**`inject_settings_env_vars()`**: Called early in CLI/MCP startup. Injects `settings.json` env vars into `os.environ` so `llm` library finds API keys. User's actual environment takes priority (won't override existing vars). Idempotent.

**Test guard**: All LLM detection skipped when `PYTEST_CURRENT_TEST` is set (prevents subprocess hangs from `llm keys get`).

**Module-level caching**: `get_default_llm_model()` caches result after first detection. Call `clear_model_cache()` in tests.

### metrics.py

**Metrics flow**: LLM usage is captured via trace events (WorkflowTraceCollector). Consumers call `trace.collect_llm_calls()` to get a flat list, then `MetricsCollector.get_summary(llm_calls)` aggregates costs.

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
    "nodes": { "allow": ["*"], "deny": ["pflow.nodes.git.*", "pflow.nodes.github.*"] }
  },
  "runtime": { "template_resolution_mode": "strict" },
  "llm": { "default_model": null, "discovery_model": null, "filtering_model": null },
  "env": {
    "OPENAI_API_KEY": "sk-proj-...",
    "ANTHROPIC_API_KEY": "sk-ant-..."
  }
}
```

**`runtime`**: `template_resolution_mode` overridable via `PFLOW_TEMPLATE_RESOLUTION_MODE` env var.

**`llm`**: `default_model` is shared fallback for all features. `discovery_model` and `filtering_model` override it for specific features. See `llm_config.py` for resolution chains.

**Env management**: `set_env`/`get_env`/`unset_env`/`list_env(mask_values=True)`. Plain text storage (industry standard for CLI tools — no keyring/encryption).

**Security**: Atomic save (tempfile + `os.replace()`), chmod 600 on save, permission validation warns on insecure files with secrets.

**Input precedence**: CLI params → settings.env → workflow defaults → error.

**Node filtering**: Allow/deny patterns with fnmatch. Filtering happens at Registry **load time**, not storage time. Test nodes hidden by default, exposed via `PFLOW_INCLUDE_TEST_NODES` env var. **`include_test_nodes` is never persisted** — the env toggle is ephemeral by design. MCP nodes generate multiple match candidates: `mcp-{server}-{tool}` → also tries `{tool}` (hyphenated) and `{server}.{tool}`.

### user_errors.py

Three-part error structure: WHAT went wrong (title) → WHY it failed (explanation) → HOW to fix it (suggestions). Specialized: `MCPError`, `OutputResolutionError` (raised when non-coalesce output sources cannot be resolved after execution, e.g., a declared output references a node that didn't run on the taken branch).

### validation_utils.py

**Forbidden in parameter names**: `$` (template conflict), `|><&;` (shell injection), spaces/tabs (CLI parsing). Allowed: hyphens, dots, numbers at start.

**🚨 Security gaps identified**:
- Template variables NOT validated for dangerous characters
- Node parameters in IR NOT validated
- LLM-extracted parameters NOT validated
- MCP tool parameters NOT validated (external servers could provide dangerous names)

### execution_cache.py

Two-phase execution pattern for AI agents: (1) execute node → return structure-only + `execution_id`, (2) read specific fields → retrieve from `~/.pflow/cache/registry-run/`. TTL: 24h stored but **not enforced** in MVP.

### trace_report.py

Generates navigable markdown report directories from trace files. `generate_report(trace_path, output_path, only_node, total_nodes)` → `~/.pflow/reports/{name}/` with `summary.md` + per-node files (`01-node-id.md`). Batch/sub-workflow nodes get directories with nested files.

**`--only` context**: When `only_node` and `total_nodes` are provided, summary shows `Nodes: N/M (--only 'X', K skipped)` instead of just `Nodes: N`. Only executed nodes get report files (skipped nodes aren't in the trace).

**Pipeline table**: `_format_event_status()` shows `ok [cached]` for cached nodes, `**FAILED**` for errors, and `ok (N/M)` for batch nodes with item counts.

**Per-node files include**: metadata (type, timing, status, LLM model/tokens/cost, error), resolved inputs (`## Command` for shell, `## Prompt` for LLM, `## Code` + `## Inputs` for python), outputs (`## stdout`, `## stderr`, `## Result`, `## Response`), and a catch-all for remaining output keys.

**Consumer**: `cli/main.py:_save_trace_and_report()` (CLI `--report` flag), `cli/commands/trace.py` (trace subcommand).

**Binary encoding convention**: `{"__type": "base64", "data": "..."}` — used project-wide for binary data in JSON. Sensitive params auto-masked before caching.

### file_resolver.py

Detects file path references in node params and batch items, reads the files, and substitutes their content into the IR before compilation. Called by `compile_workflow()` and validate-only paths.

**Detection heuristic**: starts with `./` or `../`, or contains `/` with recognized extension (.md, .txt, .py, .sh, .yaml, .yml, .json). Must not contain `${`, newlines, or `://` (URLs excluded).

**YAML-parsed params**: batch, output_schema, headers — file content is `yaml.safe_load()`'d. All other params get raw text content.

**Batch handling**: `node["batch"]` is at the node top level (NOT in params). If it's a string file reference, reads and YAML-parses. If it's a dict with inline items, walks items for file references in their values.

**Provenance**: Records original file paths in `node["_source_files"]` dict for error attribution.

### param_coercion.py

**Two functions for different contexts** — easy to confuse:
- `coerce_to_declared_type(value, expected_type)`: For MCP tools. Converts dict/list → JSON string when declared type is `"str"`.
- `coerce_input_to_declared_type(value, declared_type)`: For CLI inputs. Dispatch table handles all type pairs (str↔int, str↔bool, str↔JSON). **Lenient**: warns on failure instead of erroring — lets downstream validation catch it with full context.

### security_utils.py

19 sensitive parameter names detected (password, token, api_key, secret, etc.). Case-insensitive matching. Used by MCP error sanitization and CLI rerun display.

## Imports — Not Exported (require direct imports)

These modules are NOT in `core/__init__.py` (require direct imports):
- `suggestion_utils` — used by CLI, runtime, formatters, MCP
- `security_utils` — used by MCP errors and CLI display
- `llm_config` — used by CLI startup, compiler, registry/smart_filter, discovery
- `llm_utils` — shared LLM response parsing (used by registry/smart_filter, discovery)
- `prompt_utils` — prompt loading/formatting (used by discovery functions)
- `execution_cache` — used by CLI registry run

The `workflow/` subdirectory has its own `__init__.py` with full re-exports. Import from `pflow.core.workflow.manager`, `pflow.core.workflow.validator`, etc.

## Integration Map

| Consumer | Uses from core | Purpose |
|----------|---------------|---------|
| CLI (`cli/main.py`) | shell_integration, WorkflowManager, OutputController, MetricsCollector, UserFriendlyError | Pipe support, saves, display, metrics, error formatting |
| Compiler (`runtime/compilation/`) | validate_ir, validation_utils, SettingsManager | IR validation, param security, env loading |
| Execution (`execution/`) | WorkflowValidator, OutputController, WorkflowManager | Validation phase, display, metadata updates |
| Registry (`registry/`) | SettingsManager | Node filtering at load time |
| Runtime (`runtime/engine/instrumentation.py`) | MetricsCollector, OutputController | LLM usage capture, progress callbacks |
| MCP Server (`mcp_server/`) | workflow_save_service, suggestion_utils, security_utils | Save ops, suggestions, error sanitization |

## Critical Issues

**🚨 Security**: Parameter validation gaps — template variables, node params, LLM/MCP params not validated for shell special characters.

**🐛 Broken**: Two LLM pricing aliases point to non-existent entries.

## Testing and Examples

Tests in `tests/test_core/` — comprehensive coverage for all components. See `examples/core/` (valid workflows) and `examples/invalid/` (parse error cases) tested by `test_ir_examples.py`.
