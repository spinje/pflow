# CLI Commands

All Click command groups for pflow. Each file defines one subcommand group routed by `main_wrapper.py`.

## File Overview

| File | Subcommands | External deps |
|------|------------|---------------|
| `mcp.py` | add, list, sync, remove, tools, info, serve | `pflow.mcp.*` |
| `registry.py` | list, describe, scan, discover, run | `pflow.registry.*`, `registry_run.py` |
| `registry_run.py` | (called by registry `run`) | `registry.py`, `param_parsing.py` |
| `read_fields.py` | (standalone command) | `pflow.core.execution_cache` |
| `workflow.py` | list, describe, history, discover, save | `pflow.core.workflow.*` |
| `skills.py` | save, list, remove | `pflow.core.workflow.skill_service` |
| `settings.py` | init, show, allow, deny, remove, reset, check, set-env, unset-env, list-env, llm (subgroup), registry (subgroup) | `pflow.core.settings` |
| `visualize.py` | (standalone command) | `pflow.core.workflow.mermaid`, `pflow.execution.*` |
| `instructions.py` | usage, create | Reads from `../resources/` |

## Cross-References Within commands/

`registry.py` and `registry_run.py` have a mutual lazy import dependency (both inside function bodies, no circular import at load time):
- `registry.py` lazily imports `execute_single_node` from `registry_run.py` (inside the `run` command)
- `registry_run.py` lazily imports `normalize_node_id` from `registry.py` (inside `_resolve_node_type`)

No other cross-references exist between command files.

## MCP Commands (mcp.py)

Subcommands: `add`, `list`, `sync`, `remove`, `tools`, `info`, `serve`.

**Smart auto-discovery**: Runs at pflow startup on every command (via `mcp_sync.py`, not this file). Only syncs when config modified or servers changed — uses file mtime and server hash for detection. Saves ~500ms on warm starts.

**Universal MCPNode pattern**: Single `MCPNode` class handles ALL MCP tools. Virtual registry entries point to same node class. Server/tool injected via `__mcp_server__` and `__mcp_tool__` params.

**MCP connection pooling**: Server sessions are kept alive across workflow steps via `MCPConnectionPool` (shared store key `__mcp_pool__`). Pool is created by `runner.py:_initialize_shared_store()` and shut down in `runner.py:_cleanup()`.

**`serve` is fundamentally different** from the management commands — it launches pflow as an MCP server (stdio transport). It's a separate concern co-located here for CLI organization.

## Probe Command (`probe.py` + `_probe_impl.py`)

`pflow probe <node> params...` executes a single node and returns metadata / template paths rather than dumping raw output by default.

**MCP tool normalization** (`normalize_node_id`, 3-tier matching for `describe`/`run`):
1. Exact match: `mcp-slack-composio-SLACK_SEND_MESSAGE`
2. Hyphen/underscore conversion: `SLACK-SEND-MESSAGE` → `SLACK_SEND_MESSAGE`
3. Short form: `SLACK_SEND_MESSAGE` → searches for unique tool with this suffix

Ambiguity detected → shows all matching full IDs with guidance.

**Cross-module dependency**: `describe` uses `build_component_context()` from `pflow.registry.context_builder` to produce detailed node output.

**Shared formatters**: Uses `registry_list_formatter` and `registry_search_formatter` from `pflow.execution.formatters/`.

## Execution Caching Pipeline (registry_run.py + read_fields.py)

```
pflow probe <node> params...
    ↓ executes node
    ↓ ExecutionCache.store(execution_id, outputs)
    ↓ displays results with execution_id

pflow read-fields <execution_id> <field_paths>...
    ↓ ExecutionCache.retrieve(execution_id)
    ↓ TemplateResolver.resolve_value(field_path, outputs)
    ↓ displays specific field values
```

This two-command pipeline allows agents to run a node once, then extract specific fields without re-execution. Output display mode controlled by `settings.registry.output_mode` ("smart"/"structure"/"full").

## Workflow Commands

Top-level commands: `list`, `find`, `describe`, `history`, `save`.

**Workflow save**:
- Name validation: lowercase, numbers, hyphens only, max 30 chars (shell/URL/git-safe)
- Description extracted from markdown H1 prose (`--description` flag removed)
- The CLI save command reads raw markdown and delegates parse + full validation + save to `save_workflow_with_options()`
- Validation failures with structured diagnostics are rendered through `format_validation_failure()` for parity with `--validate-only`
- `--delete-draft` safety check: only works in `.pflow/workflows/`, resolves symlinks, refuses to delete symlinked files

**Workflow history** (`pflow history <name>`): Shows execution history and last used inputs — useful for finding previously used parameter values.

**Discovery commands use plain functions** — `find_workflow()` from `core/workflow/discovery` and `find_components()` from `registry/discovery`. Both return typed dataclasses (`WorkflowMatch`, `ComponentSelection`).

**Shared formatters**: Uses `workflow_list_formatter`, `workflow_describe_formatter`, `discovery_formatter`, `workflow_save_formatter`, `history_formatter` from `pflow.execution.formatters/`.

## Skill Commands (skills.py)

Subcommands: `save`, `list`, `remove`.

Skills are **symlinks** from tool-specific directories to saved workflows in `~/.pflow/workflows/`. The saved workflow is the single source of truth.

**Multi-tool targets**: Claude Code (default), Cursor (`--cursor`), Codex (`--codex`), Copilot (`--copilot`). Can combine multiple flags.

**Scope**: `--personal` for personal skills (`~/` dirs) vs project scope (project-relative dirs, default).

**Enrichment**: `save` adds a `## Usage` section to the workflow file (idempotent — replaces existing).

**Broken link detection**: `list` detects and reports broken symlinks with fix/remove guidance.

## Guide Command (`guide.py`)

`pflow guide` renders the shared entry content used by `pflow --help`.
`pflow guide <topics...>` is a placeholder until Task 77 provides composed topic content.

**Resource path**: Uses `Path(__file__).parent.parent / "resources"` to reach `cli/resources/` from `cli/commands/`.

## Settings Commands (settings.py)

**Node filtering**: `init`, `show`, `allow`, `deny`, `remove`, `check`, `reset`.
Node filtering priority: Test policy → Deny → Allow → Default. See `core/CLAUDE.md` for details.

**Environment variables**: `set-env`, `unset-env`, `list-env`.
Stores API keys in `~/.pflow/settings.json`. Injected into `os.environ` at CLI startup (`_inject_settings_env_vars` in `main.py`), making them available to the `llm` library.

**LLM model settings** (`settings llm` subgroup): `show`, `set-default`, `set-discovery`, `set-filtering`, `unset`.

LLM model resolution chain (genuinely hard to discover):
- `default`: workflow params → `default_model` setting → `llm` CLI default → error
- `discovery`: `discovery_model` → `default_model` → auto-detect → fallback (`anthropic/claude-sonnet-4-5`)
- `filtering`: `filtering_model` → `default_model` → auto-detect → fallback

**Registry settings** (`settings registry` subgroup): `output-mode` (smart/structure/full).

## Test Mapping

| Command file | Test file(s) | Mock.patch targets |
|-------------|-------------|-------------------|
| `mcp.py` | `test_mcp_add_json.py` | None |
| `registry.py` | `test_registry_cli.py`, `test_registry_describe.py`, `test_discovery_commands.py` | `pflow.cli.commands.registry.Registry`, `.Path`, `.registry` |
| `registry_run.py` | `test_registry_run.py` | `pflow.cli.commands.registry_run.Registry`, `.import_node_class`, `.inject_special_parameters` |
| `registry.py` (normalization) | `test_registry_normalization.py` | None (direct function import) |
| `read_fields.py` | `test_read_fields.py` | None |
| `workflow.py` | `test_workflow_save_cli.py`, `test_workflow_resolution.py` (partial) | None |
| `skills.py` | `test_skills.py` | `pflow.cli.commands.skills.WorkflowManager`, `.create_skill_symlink`, `.enrich_workflow`, `.find_skill_for_workflow`, `.find_pflow_skills`, `.remove_skill_service` |
| `visualize.py` | `test_visualize.py` | None |
| `settings.py` | (tested via integration) | None |
| `instructions.py` | `test_instructions.py` | None |
