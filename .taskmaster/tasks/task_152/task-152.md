# Task 152: MCP Server Parity with New CLI Surface

## Description

Bring the pflow MCP server into parity with the new CLI surface introduced by Task 151. Rename MCP tools to match CLI verbs, add new tools that mirror new CLI commands, remove deprecated tools and resources, and update the MCP agent instruction files. Clean cutover, no aliases.

After Task 151 and Task 77 ship, CLI agents have a flat command surface with `guide`, `probe`, `find`, and topic-filtered learning. MCP agents still see the old tool names and a monolithic instruction resource. This task closes that gap.

## Status

not started

## Priority

medium

## Problem

After Task 151 lands, CLI and MCP are out of sync:

1. **MCP tools use old verb names.** The CLI has `pflow find`, `pflow probe`, `pflow describe` — the MCP server still exposes `workflow_discover`, `registry_run`, `workflow_describe`. Agents that use both surfaces must remember two naming schemes.

2. **MCP doesn't expose the new commands.** There's no `guide()` tool for agents to get tailored workflow-building content. There's no `mcp_list()` or `mcp_find()` for MCP tool discovery. The CLI has these; MCP doesn't.

3. **The `pflow://instructions` resource is obsolete.** Task 77 replaces it with topic-based guide content. Task 151 already removes the CLI `instructions` command. The MCP resource still exists and still serves a monolithic ~2,200 line dump.

4. **MCP agent instruction files reference old tool names.** `mcp-agent-instructions.md` and `mcp-sandbox-agent-instructions.md` tell agents to call `workflow_discover` first, list `registry_run` as the node-test command, etc. These files need to be rewritten to reflect the new surface.

5. **No single source of truth for guide content.** If the MCP server simply duplicates Task 77's CLI guide content, any future update has to happen twice. A small parser/transformer can read the CLI guide chunks and produce MCP-flavored versions at runtime.

## Solution

**Phase 1 — Tool rename and addition.**

Rename MCP tool wrappers in `mcp_server/tools/` to match new CLI verbs. Add new tool wrappers for commands that don't exist in MCP yet. Remove deprecated tool wrappers entirely (no aliases). The underlying services in `mcp_server/services/` and the shared core services (`core/`, `execution/`, `registry/`) stay unchanged — only the wrapper layer changes.

**Phase 2 — Resource removal and instruction rewrite.**

Remove the `pflow://instructions` and `pflow://instructions/sandbox` MCP resources. The agent instruction files (`mcp_server/resources/instructions/*.md`) are rewritten to use new tool names and delegate to the `guide()` tool for detailed content instead of being monolithic dumps themselves.

**Phase 3 — Guide content strategy.**

Decide whether MCP guide content is independent of CLI guide content, or auto-generated from it. Two options (both acceptable, decided during implementation):

- **Option A — Parallel files:** MCP has its own `.md` chunks under `mcp_server/resources/guide/` written natively in MCP tool-call style. This matches the current parallel-file pattern and is simple. Drift risk over time.
- **Option B — Auto-transform:** A small parser reads CLI guide content from `cli/resources/guide/*.md`, finds `pflow <command>` invocations in code blocks, and rewrites them to MCP tool call JSON. Single source of truth, no drift. ~50–100 lines of parser code.

Option B is preferred if the parser is simple enough to maintain. Option A is the fallback if the parser becomes a burden.

## Design Decisions

### Full MCP tool mapping

| MCP tool (new) | Replaces | Notes |
|---|---|---|
| `workflow_run` | `workflow_execute` | Rename for consistency with CLI's `run` verb |
| `workflow_list` | existing | Same name, new keyword filter behavior (space-separated AND) |
| `workflow_find` | `workflow_discover` | Rename: LLM-powered semantic search |
| `workflow_describe` | existing | Same name |
| `workflow_history` | NEW | Mirror of `pflow history <workflow>` |
| `workflow_save` | existing | Same name |
| `workflow_validate` | existing | Same name |
| `guide` | NEW | Returns tailored content; same interface as CLI `pflow guide [topics]` |
| `probe` | `registry_run` | Rename: exploratory node testing |
| `read_fields` | existing | Same name |
| `mcp_list` | NEW | Lists MCP tools; grouped-by-server when no args, keyword-filtered with args |
| `mcp_find` | `registry_discover` (MCP-scoped) | LLM-powered semantic search for MCP tools |
| `mcp_describe` | `registry_describe` (MCP-scoped) | MCP tool interface details |

**Removed entirely (no aliases):**
- `registry_list` — core nodes handled by `guide`; MCP nodes handled by `mcp_list`
- `registry_discover` — core nodes handled by `guide`; MCP nodes handled by `mcp_find`
- `registry_describe` — core nodes handled by `guide`; MCP nodes handled by `mcp_describe`
- `pflow://instructions` resource — replaced by `guide()` tool
- `pflow://instructions/sandbox` resource — replaced by `guide()` tool with sandbox context flag

### Service layer scoping

Current MCP services (`discovery_service.py`, `registry_service.py`) sometimes span both core and MCP nodes. After this task, the services that back the new MCP-only tools (`mcp_list`, `mcp_find`, `mcp_describe`) should be scoped to return only MCP nodes, not core nodes. Core node information is handled by `guide()` instead.

Specifically:
- `mcp_list` filters the registry to only `type == "mcp"` nodes
- `mcp_find` scopes the LLM search context to MCP-only
- `mcp_describe` returns details for MCP nodes only (errors if given a core node name like `http`)

### `workflow_list` keyword filtering

The existing `workflow_list` MCP tool takes an optional `filter_pattern` string. Update it to:
- Accept a list of keywords (or space-separated string) for AND logic
- Apply the same substring + smart-case + name-and-description matching as CLI `pflow list`

### `guide()` tool signature

Mirrors CLI exactly:

```python
def guide(topics: list[str] | None = None) -> str:
    """Return tailored workflow-building content.

    - No topics: returns phase-1 menu (available topics + example usage)
    - With topics: returns core framework + per-topic sections
    """
```

Topics are the same names as CLI (`http`, `llm`, `code`, `shell`, `file`, `mcp`, `batch`, `branching`, `nested`, `structured`).

### Guide content strategy (Option B preferred)

If going with Option B (auto-transform):

**Parser responsibilities:**
- Walk `.md` files in `cli/resources/guide/`
- Find code blocks that contain `pflow <verb>` invocations
- Parse each invocation into (verb, positional args, key=value args)
- Look up the verb in a command mapping table
- Emit an equivalent MCP tool call representation

**Command mapping table** (subset — full list matches Task 151 parity mapping):

```python
CLI_TO_MCP = {
    "guide": ("guide", parse_guide_args),
    "probe": ("probe", parse_probe_args),
    "find": ("workflow_find", parse_find_args),
    "list": ("workflow_list", parse_list_args),
    "describe": ("workflow_describe", parse_describe_args),
    "history": ("workflow_history", parse_single_arg),
    "save": ("workflow_save", parse_save_args),
    "mcp list": ("mcp_list", parse_list_args),
    "mcp find": ("mcp_find", parse_find_args),
    "mcp describe": ("mcp_describe", parse_single_arg),
    # Catch-all: pflow <workflow-name> param=value → workflow_run
}
```

**Unknown commands stay as CLI text** with a prefix note ("CLI only — MCP agents skip this example"). In CI, unknown commands should be an error; in production, graceful fallback.

**Linter:** a CI step parses every `.md` file in `cli/resources/guide/` and fails if any `pflow <command>` invocation can't be mapped. This catches mapping-table drift when new commands are added.

### MCP agent instruction files

Current `mcp-agent-instructions.md` and `mcp-sandbox-agent-instructions.md` are both ~short files (~200 lines) that describe the high-level MCP agent flow. After this task:

- Reduce each to ~50 lines: just the decision tree (discover → read → act) and a pointer to `guide()` for detailed content.
- Reference only new tool names.
- The monolithic content that used to live in `pflow://instructions` is replaced by `guide()` tool calls with appropriate topics.

### Sandbox vs regular

Sandboxed agents don't have filesystem access, so they can't `cat` `.pflow.md` files or read raw instruction files. The difference matters for:

- **Workflow source viewing:** sandboxed agents get workflow source via `workflow_describe()` (which returns the full content) instead of filesystem reads
- **Guide content:** both variants can use `guide()` equally — it returns a string regardless of context
- **Instructions resource removal:** no functional difference; the `guide()` tool replaces the resource for both

No separate `guide_sandbox()` tool needed. One `guide()` tool serves both.

## Dependencies

- **Task 151** — CLI Surface Restructure. Must complete before this task. Task 151 provides the new CLI commands that this task mirrors in MCP.
- **Task 77** — Guide content (rewritten). Should complete before this task OR in parallel with it. If Task 77's guide content exists, Option B (auto-transform) is preferred. If not, Option A (parallel files) is the fallback.

## Requirements

### MCP tool renames (in `mcp_server/tools/`)

- `workflow_execute` → `workflow_run` (rename wrapper + update FastMCP registration)
- `workflow_discover` → `workflow_find` (rename)
- `registry_run` → `probe` (rename, move to appropriate tools file)
- `registry_discover` → `mcp_find` (rename AND scope to MCP-only nodes)
- `registry_describe` → `mcp_describe` (rename AND scope to MCP-only nodes)
- `registry_list` → `mcp_list` (rename AND scope to MCP-only; add grouped-by-server output)

### MCP tools added

- `workflow_history(name)` — returns execution history for a workflow
- `guide(topics)` — returns tailored guide content; see Guide content strategy above
- `mcp_list(keywords)` — new signature: optional keyword list, grouped-by-server when empty, keyword-filtered when provided

### MCP tools removed

- `registry_list` (core node listing)
- `registry_discover` (core node LLM search)
- `registry_describe` (core node describe)
- No aliases. Clean cutover.

### MCP resource removal

- `pflow://instructions` removed
- `pflow://instructions/sandbox` removed
- `mcp_server/resources/instruction_resources.py` deleted (or at minimum has both resources unregistered from FastMCP)
- Server instructions string in `mcp_server/server.py` updated to reflect new tool names and point agents at `guide()` for detailed content

### MCP agent instruction files

- `mcp_server/resources/instructions/mcp-agent-instructions.md` rewritten to use new tool names and delegate detailed content to `guide()`
- `mcp_server/resources/instructions/mcp-sandbox-agent-instructions.md` rewritten similarly
- Both files kept under ~50 lines each — high-level flow + decision tree only

### Service layer updates

- `mcp_server/services/discovery_service.py` — scope `discover_components` (or new method) to MCP-only nodes for `mcp_find`
- `mcp_server/services/registry_service.py` — scope filtering methods to MCP-only for `mcp_list` and `mcp_describe`
- `mcp_server/services/workflow_service.py` — add `history` method backing `workflow_history` tool
- **Shared core services unchanged** — `core/workflow/discovery.py:discover_workflow`, `registry/discovery.py:discover_components`, etc. keep their current names and behavior

### Guide content (Option B — auto-transform)

If implementing Option B:

- Create `mcp_server/guide_transformer.py` (or similar):
  - Parses `.md` files from `cli/resources/guide/`
  - Uses regex + `shlex.split` to find `pflow <command>` invocations
  - Looks up commands in `CLI_TO_MCP` mapping table
  - Transforms matched commands to MCP tool call JSON format
  - Unknown commands: leave as CLI text with warning comment
- Create CI linter that runs the parser over all guide `.md` files and fails on unmapped commands
- `guide()` tool implementation:
  - CLI context: return `cli/resources/guide/*.md` content as-is
  - MCP context: pipe through transformer before returning

If implementing Option A (fallback):

- Create parallel `.md` files under `mcp_server/resources/guide/`
- Same topic structure as `cli/resources/guide/` but written with MCP tool calls instead of CLI commands
- `guide()` tool reads from the MCP-side files

### Tests

- MCP tool tests updated to use new tool names
- New tests for `guide()` MCP tool (menu + tailored)
- New tests for `mcp_list()`, `mcp_find()`, `mcp_describe()` with MCP-only scoping
- New test for `workflow_history()` MCP tool
- If Option B: tests for the transformer (mapping every CLI command correctly, graceful fallback on unknown commands)
- If Option B: CI linter test that runs on the real guide content

### Documentation

- `src/pflow/mcp_server/CLAUDE.md` — updated to reflect new tool surface
- `src/pflow/mcp_server/tools/CLAUDE.md` (if exists) — per-tool updates
- `src/pflow/mcp_server/services/CLAUDE.md` — service layer scoping changes
- `docs/integrations/*.mdx` — update MCP-facing integration docs to reference new tool names
- `README.md` — if it mentions MCP tool names, update

## Implementation Notes

### Service layer refactor for MCP-scoping

The current `registry_service.py` and `discovery_service.py` filter by all node types. For MCP-only scoping, the simplest approach is to add an optional `type_filter` parameter:

```python
def list_nodes(keywords: list[str] | None = None, type_filter: str | None = None) -> ...:
    nodes = registry.list()
    if type_filter:
        nodes = [n for n in nodes if n.type == type_filter]
    # ... existing keyword filtering
```

Then `mcp_list` calls `list_nodes(keywords, type_filter="mcp")`. Minimal change, no duplication.

### Tool wrapper file organization

Current structure:
- `mcp_server/tools/discovery_tools.py` — `workflow_discover`, `registry_discover`
- `mcp_server/tools/workflow_tools.py` — `workflow_list`, `workflow_describe`
- `mcp_server/tools/execution_tools.py` — `workflow_execute`, `workflow_validate`, `workflow_save`, `registry_run`, `read_fields`
- `mcp_server/tools/registry_tools.py` — `registry_describe`, `registry_list`

After this task, consider reorganizing to mirror CLI commands by concern:
- `workflow_tools.py` — `workflow_run`, `workflow_list`, `workflow_find`, `workflow_describe`, `workflow_history`, `workflow_save`, `workflow_validate`
- `mcp_tools.py` — `mcp_list`, `mcp_find`, `mcp_describe`
- `build_tools.py` — `guide`, `probe`, `read_fields`

Or leave the current file organization and just rename the functions. Pick whichever minimizes churn.

### FastMCP registration updates

Each renamed tool needs its FastMCP decorator updated. Old names must be unregistered (not silently kept as aliases). The MCP SDK handles this at registration time, not runtime.

### Parser edge cases (Option B)

Several patterns need graceful handling:

- **Multi-line commands with `\`:** join continuation lines before parsing
- **Inline code in prose (backticks):** transform these too, not just code blocks
- **Pipes (`pflow foo | jq ...`):** the pipe can't be mapped to MCP. Either skip transformation (leave as CLI-only) or strip the pipe portion and transform only the `pflow foo` part with a note
- **Complex shell quoting:** use `shlex.split()` for robust quoted-string handling
- **Workflow-name catch-all:** `pflow my-workflow param=X` has no subcommand. Detect this case (first token not in reserved names) and map to `workflow_run(workflow="my-workflow", parameters={...})`

### Server instructions string

The instructions string in `mcp_server/server.py` is injected into the agent's system prompt by MCP clients. Current content (approx):

```
Use workflow_discover first to check if a workflow exists...
```

Rewrite to use new tool names:

```
Use workflow_find first to check if a workflow exists. If found with high confidence, call workflow_run. Otherwise, call guide() for workflow-building instructions.
```

Keep it short — under 1000 chars ideally. Agents read this on every session.

### Migration order within this task

Recommended sequence:
1. Update `mcp_server/services/` — add type filtering, add history method
2. Create new tool wrappers (`guide`, `mcp_list`, `mcp_find`, `mcp_describe`, `workflow_history`)
3. Rename existing tool wrappers (`workflow_execute` → `workflow_run`, etc.)
4. Remove deprecated tool wrappers and resources
5. Rewrite MCP agent instruction files
6. Update server instructions string
7. Update tests
8. If Option B: implement and test the transformer

### What if Task 77 isn't done yet?

This task technically depends on Task 77 because `guide()` needs content to serve. If Task 77 isn't complete:

- Ship this task with `guide()` returning Task 151's stub message
- Add a note: "MCP guide content requires Task 77"
- Avoid Option B (transformer) until guide content actually exists

Preferred order: Task 151 → Task 77 → Task 152. But if needed, Task 77 and Task 152 can run in parallel.

## Verification

### Unit tests
- Every renamed tool has a test under its new name that passes
- Every removed tool has a test confirming it is NO LONGER exposed (FastMCP client can't find it)
- New tools (`guide`, `mcp_list`, `mcp_find`, `mcp_describe`, `workflow_history`) have tests
- `mcp_list` test confirms MCP-only scoping (core nodes not returned)
- `mcp_find` test confirms MCP-only LLM context
- If Option B: transformer correctly maps every command in the mapping table
- If Option B: transformer leaves unknown commands as CLI text

### Integration tests
- Start MCP server, connect test client, list available tools, confirm set matches new surface exactly
- Call `guide()` with no args — returns menu
- Call `guide(topics=["http", "llm"])` — returns core + http + llm sections
- Call `workflow_run(workflow="test-workflow", parameters={...})` — executes successfully
- Call `probe(node_type="shell", parameters={"command": "echo hi"})` — returns metadata
- Call `workflow_find(description="...")` — returns LLM-ranked matches
- Call `mcp_find(description="...")` — returns MCP-only LLM-ranked matches

### Regression tests
- CLI from Task 151 still works (unchanged by this task)
- Workflow execution via CLI still produces same results
- Shared core services (`core/`, `execution/`, `registry/`) have no behavior changes

### Acceptance
- `make test` passes
- `make check` passes
- MCP server exposes exactly the tools listed in the mapping table — no more, no less
- `pflow://instructions` resource is unregistered (MCP client's resource list doesn't include it)
- MCP agent instruction files use only new tool names
- Server instructions string references new tool names
- If Option B: CI linter runs successfully on all guide content

### Manual verification
- Connect to pflow MCP server from Claude Desktop (or equivalent MCP client)
- Confirm tool list matches the mapping table
- Call `guide()` — confirm menu output is sensible
- Call `guide(topics=["batch"])` — confirm tailored output is sensible
- Ask the client to build a simple workflow — confirm it uses new tool names naturally (the server instructions should guide it)

## References

### Files to modify (non-exhaustive)

**Tool wrappers (rename/add/remove):**
- `src/pflow/mcp_server/tools/discovery_tools.py`
- `src/pflow/mcp_server/tools/workflow_tools.py`
- `src/pflow/mcp_server/tools/execution_tools.py`
- `src/pflow/mcp_server/tools/registry_tools.py`
- Possibly new file: `src/pflow/mcp_server/tools/mcp_tools.py`
- Possibly new file: `src/pflow/mcp_server/tools/build_tools.py` (for `guide`, `probe`, `read_fields`)

**Services:**
- `src/pflow/mcp_server/services/discovery_service.py` — add MCP-scoping
- `src/pflow/mcp_server/services/registry_service.py` — add type filtering
- `src/pflow/mcp_server/services/workflow_service.py` — add `history` method

**Server and resources:**
- `src/pflow/mcp_server/server.py` — update instructions string, unregister removed tools/resources
- `src/pflow/mcp_server/resources/instruction_resources.py` — delete or gut
- `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` — rewrite
- `src/pflow/mcp_server/resources/instructions/mcp-sandbox-agent-instructions.md` — rewrite

**Option B only:**
- New file: `src/pflow/mcp_server/guide_transformer.py`
- New CI check or test: `tests/test_mcp_server/test_guide_transformer.py`

**Tests:**
- `tests/test_mcp_server/` — rename test files to match new tool names, add new tests

**Docs:**
- `src/pflow/mcp_server/CLAUDE.md`
- `src/pflow/mcp_server/tools/CLAUDE.md` (if exists)
- `src/pflow/mcp_server/services/CLAUDE.md` (if exists)
- `docs/integrations/*.mdx` — update MCP tool references

### Related tasks

- **Task 151: CLI Surface Restructure** — prerequisite. Provides new CLI commands this task mirrors.
- **Task 77: Guide Content (rewritten)** — prerequisite or parallel. Provides the guide content that `guide()` serves.

### Prior art / context

- Design discussion: multi-turn conversation on 2026-04-10 / 2026-04-11
- MCP server architecture: `src/pflow/mcp_server/CLAUDE.md` documents the thin-wrapper + services pattern. Changes here are at the wrapper layer.
- Current MCP tools listed in `src/pflow/mcp_server/tools/` — 11 enabled tools across 4 files
- Parallel file pattern: `mcp_server/resources/instructions/*.md` are already separate from `cli/resources/cli-agent-instructions.md`. This task continues that pattern (Option A) or unifies via transformer (Option B).
- Naming decisions from Task 151 subagent polls apply here: `guide`, `probe`, `find`, `describe`, `list`
