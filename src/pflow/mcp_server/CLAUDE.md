# CLAUDE.md - MCP Server Module

## What This Module Does

Exposes pflow's workflow building and execution capabilities as MCP tools for AI agents. Programmatic access without shell execution, structured responses, agent-optimized defaults.

**Core pattern**: Three-layer stateless architecture (async tools → sync services → core pflow) with CLI parity via shared formatters.

```
┌─────────────────────────────────────────┐
│         MCP Tools (13 enabled)          │  ← FastMCP decorators, async wrappers
│         asyncio.to_thread bridge        │
├─────────────────────────────────────────┤
│      Services Layer (6 services)        │  ← Business logic, stateless pattern
│      Fresh instances per request        │
├─────────────────────────────────────────┤
│   Core pflow (sync components)          │  ← Registry, WorkflowManager, WorkflowRunner
│   Shared formatters (CLI/MCP parity)    │
└─────────────────────────────────────────┘
```

## File Tree

```
src/pflow/mcp_server/
├── __init__.py              - Package exports (run_server)
├── main.py                  - Server startup, env injection, signal handling
├── server.py                - FastMCP instance, server instructions, tool registration
├── tools/
│   ├── __init__.py          - Imports enabled tool modules (triggers decorator registration)
│   ├── discovery_tools.py   - workflow_discover, registry_discover
│   ├── execution_tools.py   - workflow_execute, validate, plan, save, registry_run, read_fields, analyze_cache
│   ├── registry_tools.py    - registry_describe, registry_list
│   └── workflow_tools.py    - workflow_list, workflow_describe
├── resources/
│   ├── __init__.py
│   ├── instruction_resources.py  - 2 MCP resources (regular + sandbox agent instructions)
│   └── instructions/             - Markdown instruction files (shipped with package)
├── services/
│   ├── __init__.py
│   ├── base_service.py      - @ensure_stateless decorator, BaseService class
│   ├── discovery_service.py - LLM-powered workflow/component discovery
│   ├── execution_service.py - Execute, validate, save workflows + test nodes
│   ├── field_service.py     - Read cached fields from previous registry_run executions
│   ├── registry_service.py  - Node describe, list, search
│   └── workflow_service.py  - Workflow list, describe
└── utils/
    ├── __init__.py
    ├── errors.py            - sanitize_parameters() for sensitive data redaction
    └── validation.py        - Parameter security, path validation, dummy params
```

## Entry Points

**main.py** — Server startup sequence:
1. `inject_settings_env_vars()` — Injects API keys from `~/.pflow/settings.json` into environment. **Must happen before any LLM operations.** Skipped during tests (`PYTEST_CURRENT_TEST` check).
2. `register_tools()` — Imports tool/resource modules to trigger `@mcp.tool()` decorator registration.
3. Signal handlers (SIGTERM/SIGINT) for graceful shutdown.
4. `mcp.run("stdio")` — **FastMCP manages its own event loop.** Never wrap in `asyncio.run()`.

**stdout is reserved for MCP protocol messages** — all logging goes to stderr.

**server.py** — `mcp = FastMCP("pflow", instructions="...")`. The `instructions` string is injected into the agent's system prompt by MCP clients. It enforces: (1) always run `workflow_discover` first, (2) 95%+ match → execute directly, (3) building new → read `pflow://instructions` resource first.

Tool/resource registration happens at import time via decorators. `register_tools()` imports the modules to trigger this.

## Tools (13 Enabled)

All tools use async/sync bridge: `await asyncio.to_thread(_sync_operation)` — pflow is sync, MCP is async.

**discovery_tools.py** (2 tools):
- `workflow_discover(query)` — Find workflows via LLM matching. Pass full user request, not abbreviated.
- `registry_discover(task)` — Find nodes via LLM selection. Pass full task description.

**execution_tools.py** (7 tools):
- `workflow_execute(workflow, parameters)` — Execute with agent defaults (no repair, silent, traces saved)
- `workflow_validate(workflow)` — Static validation without execution (10 checks including sub-workflow validation)
- `plan_workflow(workflow, parameters)` — Build execution plan JSON without side effects
- `workflow_save(workflow, name, force)` — Save to library (accepts raw markdown or file path)
- `registry_run(node_type, parameters)` — Test node to discover output structure + template paths
- `read_fields(execution_id, field_paths)` — Read specific fields from cached `registry_run` execution
- `analyze_cache(workflow, parameters)` — Static + trace-based cache plan analysis. Returns the same JSON shape as `pflow analyze-cache --format=json`. Auto-loads matching trace from `~/.pflow/debug/` when present.

**registry_tools.py** (2 tools):
- `registry_describe(nodes)` — Detailed specs using `build_component_context()`
- `registry_list(filter_pattern)` — All nodes grouped by package; with filter: relevance-sorted search

**workflow_tools.py** (2 tools):
- `workflow_list(filter_pattern)` — List saved workflows with keyword filtering
- `workflow_describe(name)` — Show workflow interface (inputs/outputs/example usage)

## Resources (2)

- `pflow://instructions` — Complete workflow building guide for agents with **full system access** (CLI, settings.json, traces, library)
- `pflow://instructions/sandbox` — Same guide adapted for **isolated environments** (no CLI, no settings access, no traces, must send markdown content directly)

**Path resolution** (3-tier, checked in order):
1. Package resources: `src/pflow/mcp_server/resources/instructions/{filename}` (production/installed)
2. User home: `~/.pflow/instructions/{filename}` (custom overrides)
3. Dev fallback: `{project_root}/.pflow/instructions/{filename}` (backward compat)

If none found, returns a fallback message with tool reference and troubleshooting steps.

## Services (6)

All inherit from `BaseService`. All methods are `@classmethod` with `@ensure_stateless` decorator. Every request creates fresh instances of Registry, WorkflowManager, etc.

- **BaseService** — `@ensure_stateless` decorator (logs instance creation), `validate_stateless()` checks
- **DiscoveryService** — Wraps `find_workflow()` and `find_components()` plain functions for LLM-powered discovery.
- **ExecutionService** — Execution/validation/planning methods delegate to `WorkflowRunner` from `pflow.execution.runner`. `plan_workflow()` returns the same JSON shape as CLI `--dry-run --output-format json` via `format_plan_json(plan)`. `run_registry_node` builds synthetic single-node IR, resolves `${ENV_VAR}` from env/settings, routes through Runner with `cache_enabled=False`.
- **FieldService** — Reads cached fields from previous `registry_run` via ExecutionCache + TemplateResolver. Supports `result[0].title` path syntax. **Not exported from services/__init__.py** — imported directly in execution_tools.py.
- **RegistryService** — `describe_nodes()` uses `build_component_context()`, `list_all_nodes()` supports filter via Registry.search()
- **WorkflowService** — List/describe with shared formatters, raises ValueError with "did you mean" suggestions

## Utilities

See `utils/CLAUDE.md` for details. Quick reference:

- **validation.py** — `validate_execution_parameters()` (shell-safe names, 1MB limit, code injection detection), `validate_file_path()` (exists but **never called** — design decision: local MCP = trusted), `generate_dummy_parameters()` (re-exported from `core.validation_utils`)
- **errors.py** — Re-exports `sanitize_parameters()` from `core.security_utils` for backward compat. Called by `WorkflowRunner._update_metadata()` for metadata redaction.

## Key Patterns

### Stateless Pattern

Every service method creates fresh instances (WorkflowManager, Registry, MetricsCollector) inside the method body. Never reuse across calls. **Why**: Thread safety without locks, no stale data, no state pollution between requests.

### Async/Sync Bridge

pflow core is synchronous. MCP protocol is async. Every tool wraps its service call in `asyncio.to_thread()` to avoid blocking the event loop. This is the consistent pattern across all 13 tools.

### CLI/MCP Parity

Shared formatters from `execution/formatters/` ensure identical output between CLI and MCP. **Import formatters locally inside methods** (not at module level) to avoid circular dependencies. Pattern: formatters RETURN strings/dicts, never print.

### Security

**What's actually wired up:**
- Parameter name validation via `validate_execution_parameters()` — blocks shell-unsafe chars, 1MB limit, code injection patterns (`__import__`, `eval(`, etc.)
- SENSITIVE_KEYS-based redaction in `sanitize_parameters()` — exists in errors.py but **not called anywhere in services**

**What exists but is never called:**
- `validate_file_path()` — path traversal prevention. Design decision: local MCP server = trusted environment.

## Agent-Optimized Defaults

MCP execution differs from CLI:
- Traces always saved to `~/.pflow/debug/workflow-trace-{timestamp}.json`
- Text output format (LLMs parse text better than nested JSON)
- Auto-normalization of workflow IR (`ir_version`, `edges`)
- Services **raise exceptions** (ValueError, RuntimeError, FileExistsError, and pflow types like WorkflowValidationError / MarkdownParseError) with pre-rendered rich text. The `PflowMCP.call_tool` and `PflowMCP.read_resource` overrides (`server.py`) catch unhandled producer bugs and any self-describing exception (anything with `to_diagnostics()` — includes all `PflowError` subclasses plus `MaxNodeVisitsError`) and convert them to structured `CallToolResult(isError=True)` / rendered resource text via `exception_to_diagnostics()` + `format_diagnostic()`, matching the CLI's outer error boundary. Bare pre-formatted `ValueError` / `TypeError` / `RuntimeError` / `FileExistsError` pass through so their hand-rolled rich text survives unchanged.

## Critical Behaviors

### Discovery-First Workflow

Intended usage flow for agents:
1. `workflow_discover(query)` → Check for existing workflows (avoid rebuilding)
2. `registry_discover(task)` → Find nodes for building (LLM selection)
3. `registry_run(node_type)` → Test node to reveal output structure (critical for MCP/HTTP nodes)
4. `plan_workflow()` → Preview cached vs would-execute nodes and cost before running
5. `workflow_execute()` → Execute built workflow
6. `workflow_save()` → Save to library for reuse

### Workflow Resolution

See `utils/CLAUDE.md` for the 5-step resolution order used by `resolve_workflow()`.

### Validation

`WorkflowValidator.validate()` runs 10 checks: structural (IR schema), stdin inputs, stdout outputs, data flow (order, cycles), template (`${variable}` resolution), node types (registry), output sources, unknown params, node-specific param semantics, and sub-workflow validation (recursive). After the structural check passes, a reserved-literal-name guard also rejects inputs/node IDs named `true`/`false`/`null` (unreachable in templates after literal-operand support). `generate_dummy_parameters()` creates `__validation_placeholder__` values so templates resolve during validation without real API keys.

## Testing

**Location**: `tests/test_mcp_server/`

**Test files**:
- `test_tool_registration.py` — Tool registration verification
- `test_validation_service.py` — Validation logic (8 regression guards)
- `test_registry_run_errors.py` — Error handling patterns
- `test_instruction_resources.py` — Instruction resources (22 tests — regular + sandbox + differences)

**Mock boundaries**: Mock at service layer (service methods return predictable results). Integration tests use real Registry/WorkflowManager with temp files.

## Gotchas

- **Never wrap `mcp.run()` in `asyncio.run()`** — FastMCP manages its own event loop
- **Never skip `asyncio.to_thread()`** — Direct sync calls block the event loop
- **Import formatters locally** inside service methods, not at module level (circular dep risk)
- **stdout is sacred** — only MCP protocol messages; all logging to stderr
- **FieldService not in `__init__.py`** — imported directly where needed in execution_tools.py
- **`sanitize_parameters()` moved to `core/security_utils.py`** — `mcp_server/utils/errors.py` re-exports for backward compat. Called by `WorkflowRunner._update_metadata()` for metadata redaction before saving to disk.
