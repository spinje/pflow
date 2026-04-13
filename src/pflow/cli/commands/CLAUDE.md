# CLI Commands

One file per top-level command, registered in `main.py` via `cli.add_command()`.

## File Overview

| File | Command | External deps |
|------|---------|---------------|
| `run.py` | (hidden default — workflow execution) | All CLI modules, `pflow.execution.*` |
| `list.py` | `pflow list [keyword...]` | `pflow.core.workflow.manager` |
| `find.py` | `pflow find "description"` | `pflow.core.workflow.discovery` |
| `describe.py` | `pflow describe <workflow>` | `pflow.core.workflow.manager` |
| `history.py` | `pflow history <workflow>` | `pflow.core.workflow.manager` |
| `save.py` | `pflow save <file> [--name]` | `pflow.core.workflow.save_service` |
| `guide.py` | `pflow guide [topics...]` | `pflow.guide` |
| `probe.py` + `_probe_impl.py` | `pflow probe <node> params...` | `pflow.registry.*`, `pflow.execution.*` |
| `mcp.py` | `pflow mcp` subgroup | `pflow.mcp.*`, `pflow.registry.*` |
| `read_fields.py` | `pflow read-fields <exec> <paths>` | `pflow.core.execution_cache` |
| `skills.py` | `pflow skill save\|list\|remove` | `pflow.core.workflow.skill_service` |
| `settings.py` | `pflow settings ...` | `pflow.core.settings` |
| `report.py` | `pflow report` | `pflow.core.trace_report` |
| `visualize.py` | `pflow visualize` | `pflow.core.workflow.mermaid`, `pflow.execution.*` |

## Cross-References Within commands/

`probe.py` is a thin Click wrapper that delegates to `_probe_impl.py:execute_single_node()`. This split keeps probe logic importable without Click dependencies (MCP server uses it via `execution_service.py`).

`find.py` and `mcp.py` (the `find` subcommand) both use `handle_discovery_error()` from `cli/find_errors.py` for consistent LLM error handling.

No other cross-references exist between command files.

## MCP Commands (mcp.py)

Subcommands: `list`, `find`, `describe`, `servers`, `add`, `sync`, `remove`, `serve`.

- `mcp list [keyword...]` — lists MCP **tools** with grouped-by-server summary (no args) or keyword-filtered detail view. Groups by `mcp_metadata.server` from registry entries.
- `mcp find "description"` — LLM-powered MCP tool search via `find_components()`.
- `mcp describe <tool>` — detailed tool info with parameters, outputs, and `.pflow.md` usage snippet.
- `mcp servers` — lists configured **servers** (transport type, command/URL, timestamps). This was the old `mcp list`.
- `mcp add|remove|sync` — server lifecycle management (unchanged).
- `mcp serve` — launches pflow as an MCP server (stdio transport). Fundamentally different from the management commands.

**Smart auto-discovery**: Runs at pflow startup on every command (via `mcp_sync.py`, not this file). Only syncs when config modified or servers changed.

**MCP tool normalization** (`normalize_node_id` in `registry/node_id.py`, 3-tier matching for `describe`/`probe`):
1. Exact match: `mcp-slack-composio-SLACK_SEND_MESSAGE`
2. Hyphen/underscore conversion: `SLACK-SEND-MESSAGE` → `SLACK_SEND_MESSAGE`
3. Short form: `SLACK_SEND_MESSAGE` → searches for unique tool with this suffix

Ambiguity → shows all matching full IDs with guidance.

## Probe Command (`probe.py` + `_probe_impl.py`)

`pflow probe <node> params...` executes a single node and returns metadata / template paths rather than dumping raw output by default.

**Reads `verbose` from `ctx.obj`** — does NOT have its own `--verbose` flag.

## Execution Caching Pipeline (probe + read_fields)

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

This two-command pipeline allows agents to run a node once, then extract specific fields without re-execution. Output display mode controlled by `settings output-mode` ("smart"/"structure"/"full").

## Workflow Commands

Top-level commands: `list`, `find`, `describe`, `history`, `save`.

**Workflow save** (`save.py`):
- Name validation: lowercase, numbers, hyphens only, max 30 chars (shell/URL/git-safe)
- Description extracted from markdown H1 prose (`--description` flag removed)
- Delegates parse + full validation + save to `save_workflow_with_options()`
- `--delete-draft` safety check: only works in `.pflow/workflows/`, resolves symlinks, refuses to delete symlinked files

**Workflow history** (`history.py`): Shows execution history and last used inputs — useful for finding previously used parameter values.

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

`pflow guide` (no args) renders entry content (same as `pflow --help` body) via `render_entry_content()`.
`pflow guide <topics...>` composes topic-scoped content via `compose_guide()`. Both from `pflow.guide`.

Topics resolve to static `.md` files under `src/pflow/guide/` (nodes, features). Node topics also get dynamic interface data (parameters, outputs) injected from the registry at render time. See `src/pflow/guide/CLAUDE.md` for the content layout.

## Settings Commands (settings.py)

**Node filtering**: `init`, `show`, `allow`, `deny`, `remove`, `check`, `reset`.
Node filtering priority: Test policy → Deny → Allow → Default. See `core/CLAUDE.md` for details.

**Environment variables**: `set-env`, `unset-env`, `list-env`.
Stores API keys in `~/.pflow/settings.json`. Injected into `os.environ` at CLI startup (`_inject_settings_env_vars` in `commands/run.py`).

**LLM model settings** (`settings llm` subgroup): `show`, `set-default`, `set-discovery`, `set-filtering`, `unset`.

LLM model resolution chain (genuinely hard to discover):
- `default`: workflow params → `default_model` setting → `llm` CLI default → error
- `discovery`: `discovery_model` → `default_model` → auto-detect → fallback (`anthropic/claude-sonnet-4-5`)
- `filtering`: `filtering_model` → `default_model` → auto-detect → fallback

**Output mode** (`settings output-mode`): Controls probe output display (smart/structure/full). Flattened from the old `settings registry output-mode`.

## Test Mapping

| Command file | Test file(s) | Key mock.patch targets |
|-------------|-------------|----------------------|
| `run.py` | `test_workflow_resolution.py`, `test_validate_only.py`, `test_workflow_commands.py`, `test_dual_mode_stdin.py` | `pflow.cli.commands.run.WorkflowManager`, `.execute_json_workflow` |
| `list.py` | `test_workflow_commands.py` | `pflow.cli.commands.list.WorkflowManager` |
| `describe.py` | `test_workflow_commands.py` | `pflow.cli.commands.describe.WorkflowManager` |
| `history.py` | `test_workflow_commands.py` | `pflow.cli.commands.history.WorkflowManager` |
| `find.py` | `test_find.py` | `pflow.core.workflow.discovery.find_workflow` |
| `save.py` | `test_workflow_save_cli.py`, `test_workflow_save_security.py` | None |
| `probe.py` | `test_probe.py`, `test_node_id_normalization.py` | None (uses real registry from `isolate_pflow_config`) |
| `mcp.py` | `test_mcp_commands.py`, `test_mcp_add_json.py` | `pflow.cli.commands.mcp.MCPServerManager`, `.MCPRegistrar` |
| `guide.py` | `test_guide.py` | None |
| `read_fields.py` | `test_read_fields.py` | None |
| `skills.py` | `test_skills.py` | `pflow.cli.commands.skills.WorkflowManager`, `.create_skill_symlink`, `.enrich_workflow`, `.find_skill_for_workflow`, `.find_pflow_skills`, `.remove_skill_service` |
| `settings.py` | `test_settings_cli.py` | None |
| `visualize.py` | `test_visualize.py` | None |
