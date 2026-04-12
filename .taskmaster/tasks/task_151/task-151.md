# Task 151: CLI Surface Restructure — Flatten, Rename, Delete

## Description

Flatten the pflow CLI surface from nested command groups (`registry`, `workflow`) into top-level commands, rename verbs for agent-friendly clarity, and delete redundant commands. Clean cutover, no fallbacks or aliases — pflow has no users yet.

**Scope is CLI only.** The MCP server continues to work with its existing tool names during and after this task. A follow-up task (see References) handles MCP server parity — renaming tools, adding new tools, removing deprecated resources. This split is possible because CLI and MCP share services (business logic) but NOT command wrappers: CLI uses Click in `cli/commands/`, MCP uses FastMCP in `mcp_server/tools/`. Changing one layer leaves the other intact.

## Status

not started

## Priority

high

## Problem

The current CLI surface has grown organically and doesn't serve agents well:

1. **Too many nested groups.** `pflow workflow describe`, `pflow registry list`, `pflow registry discover`, `pflow workflow discover` — agents must remember which namespace each command lives under. Workflows are the primary artifact; nesting them under `workflow` adds friction for the common path.

2. **Inconsistent verbs.** `list` and `search` do the same job in different places. `discover` is used for LLM-powered search but is indistinguishable from `search` to an agent reading help text.

3. **Redundant commands.** `registry describe` (for core nodes) overlaps with documentation that belongs next to workflow-building knowledge. `registry run` has a name that implies production use when its actual purpose is exploratory testing. `mcp tools` duplicates what `mcp list` would do in a cleaner namespace.

4. **Monolithic instruction dump.** `pflow instructions usage` + `pflow instructions create --part 1/2/3` gives agents a 2,400-line manual to consume before they can build anything. This is the opposite of progressive disclosure.

Note: the MCP server exposes its own tool names (`workflow_discover`, `registry_run`, `registry_describe` etc.) that will diverge from the new CLI surface after this task lands. That divergence is accepted temporarily — a follow-up task brings MCP into parity. The MCP server remains functional throughout.

The redesign emerged from a multi-turn discussion in April 2026 about what feels natural for AI agents as the primary users of the CLI. Subagent polls (N=5 each) produced unanimous or near-unanimous agreement on key naming decisions.

## Solution

Restructure the CLI into a flat, consistent surface with three naming principles:

1. **`list` is for keyword/instant filtering.** `find` is for LLM-powered semantic search. Same verbs, same meaning across all scopes.
2. **Workflows are top-level.** They're the primary artifact, so workflow operations become top-level commands instead of nested under `workflow`.
3. **`guide` replaces `instructions`** as a tailored, topic-filtered learning command. (Content design is Task 77 — this task only stubs `guide` so the CLI shape is complete.)

Final CLI surface:

```
# Top-level (agent-facing, frequent)
pflow my-workflow param=value      # run workflow (catch-all, already works)
pflow list [keyword...]            # list saved workflows (keyword filter)
pflow find "description"           # LLM-powered workflow search
pflow describe <workflow>          # show workflow interface
pflow history <workflow>           # execution history
pflow save <file> --name <name>    # save to library
pflow guide [topics...]            # learn how to build workflows
pflow probe <node> param=value     # test a single node (replaces registry run)
pflow read-fields <exec> <paths>   # existing, unchanged

# MCP namespace (agent-facing + admin)
pflow mcp list [keyword...]        # list MCP tools (primary artifact for agents)
pflow mcp find "description"       # LLM-powered MCP tool search
pflow mcp describe <tool>          # MCP tool details
pflow mcp servers                  # list configured servers (rename from 'mcp list')
pflow mcp add|remove|sync          # server lifecycle
pflow mcp serve                    # run pflow as MCP server

# Config/maintenance
pflow settings ...                 # config (unchanged)
pflow skill save|list|remove       # AI tool skills (unchanged)
```

## Design Decisions

All decisions below came from subagent polls or direct reasoning during the design discussion.

### Naming

- **`guide`** replaces `instructions`. Unanimous 5/5 agent poll. Works as both noun and verb, distinct from `help`/`docs`, signals tailored/adaptive output. Phase 1 (`pflow guide`) returns a menu; phase 2 (`pflow guide topic1 topic2`) returns tailored content. Positional args, not flags.

- **`probe`** replaces `registry run`. Unanimous 5/5 agent poll. Signals non-destructive discovery, distinct from production `run`, won't collide with workflow names. `registry run` returns metadata + template paths (not raw data), so "probe" fits the semantics better than "test" or "try."

- **`find`** for LLM-powered semantic search, at both levels (`pflow find` and `pflow mcp find`). Unanimous 5/5 agent poll. The `search` vs `find` distinction in English maps perfectly onto keyword vs semantic: you *search* a known space, you *find* something whose location you don't know.

- **`describe`** (not `show`) for the workflow detail command. 3/5 poll split, but the minority argument was decisive: `show` could collide with a future "show me the raw source" or "render mermaid" command, while `describe` unambiguously means "structured interface summary." Matches `kubectl describe` precedent.

- **`list`** does keyword filtering at both levels. `pflow list github pr` and `pflow mcp list slack send` both use space-separated AND logic. Kills the separate `search` verb that would have been redundant with `list <keyword>`.

- **`mcp list`** now means "list MCP tools" (primary agent concern). Current `mcp list` (which lists servers) moves to **`mcp servers`**. Agents building workflows care about tools; servers are rare setup-time concern, so tools get the shorter name.

### Deletions

- **`registry` group entirely removed.** `registry describe` for core nodes is absorbed by `guide` (per Task 77). `registry discover` is replaced by `guide` for core nodes and `mcp find` for MCP nodes. `registry list` is split: core node listing lives in `guide`'s menu output, MCP node listing lives in `mcp list`. `registry scan` is killed outright (custom user nodes feature is being removed — user confirmed).

- **`mcp tools`** removed. Redundant with `mcp list [server]`.

- **`workflow` group entirely removed.** All subcommands flattened to top-level.

- **`instructions` command removed.** Replaced by `guide` (content delivery is Task 77).

- **`pflow://instructions` MCP resource stays in place for now.** Removal happens in the MCP parity follow-up task, not here. The resource content (`mcp_server/resources/instructions/*.md`) references MCP tool names, not CLI commands, so CLI renames don't affect it.

### Search behavior

`list` supports:
- Substring matching (default, anywhere in name or description)
- Smart-case (case-insensitive unless you explicitly use capitals)
- Multiple positional keywords with AND logic (`mcp list slack send`)
- Search across both name AND description (critical for "search by intent" when tool names are cryptic like `POST_CHAT_MESSAGE`)
- Highlighted matches in output (bold the matched substrings)

Explicitly NOT supported (ship minimal, add if real usage demands it):
- Negation (`!keyword`) — positive filters scale well enough for small result sets
- Regex patterns — overkill
- Glob patterns — no hierarchy to match
- OR logic — complex to spec, rarely needed

### `mcp list` output modes

`mcp list` with no args returns a **grouped-by-server summary** (not every tool). Format:

```
MCP Tools (247 total across 6 servers)

slack (38 tools) — Slack workspace integration
  channels, messages, users, files, reactions...

github (52 tools) — GitHub API
  repos, issues, pulls, actions, releases...
...
```

With a keyword (`mcp list slack`), it shows full tool details (name + description) for matching tools, grouped by server when the match spans servers.

This prevents context overload when hundreds of tools are connected while still allowing drill-down.

### Cross-cutting

- **Clean cutover, no aliases.** No deprecation warnings, no fallback routing. pflow has zero users — breaking changes are free.
- **MCP server is out of scope.** Its tools (`workflow_discover`, `registry_run`, etc.) continue to work unchanged. A follow-up task (see References) brings MCP into parity with the new CLI names.
- **Guide command exists but content is stubbed.** The full content design is Task 77. This task only needs `pflow guide` to exist in the command routing and return *something* (even minimal placeholder content).
- **Shared services are NOT renamed.** Functions like `discover_workflow()` in `core/workflow/discovery.py` keep their current names because MCP still calls them. Only CLI-side wrappers change.

## Dependencies

- **None.** This task is self-contained. Task 77 (guide content) depends on this, not the other way around.

## Requirements

### CLI routing

- `main_wrapper.py` routing table updated: remove `registry`, `workflow`, `instructions`; add `list`, `find`, `describe`, `history`, `save`, `guide`, `probe` as top-level routes
- Existing catch-all for workflow execution (`pflow my-workflow param=X`) continues to work; new top-level commands take precedence when the first arg matches
- `pflow run` prefix silently stripped (existing behavior, preserved)
- Reserved command names documented so workflow save rejects workflows named `list`, `find`, `describe`, `history`, `save`, `guide`, `probe`, `mcp`, `skill`, `settings`, `read-fields`

### Top-level workflow commands

- `pflow list [keyword...]` — lists saved workflows; multiple keywords AND'd; searches name and description; smart-case
- `pflow find "description"` — LLM-powered semantic search (functionality ported from current `workflow discover`)
- `pflow describe <workflow>` — shows full interface (inputs with types/defaults, outputs, example usage); behavior ported from current `workflow describe`
- `pflow history <workflow>` — ported from current `workflow history`
- `pflow save <file> --name <name>` — ported from current `workflow save`

### New commands

- `pflow guide` (no args) — returns `render_entry_content()` output (same as `pflow --help`); this is the fallback for agents that forgot to pass a topic
- `pflow guide <topic...>` — accepts positional args; returns placeholder acknowledging the topic(s) until Task 77 ships real content composition. Something like: "pflow guide content for topics [<topics>] is not yet implemented. See Task 77. Meanwhile, read `src/pflow/cli/resources/cli-agent-instructions.md` for the legacy monolithic content."
- `pflow probe <node-type> key=value...` — functionality ported from `registry run`; output format unchanged (metadata + template paths, not raw data)
- **Shared `render_entry_content()` helper** — reads from `src/pflow/cli/resources/guide/entry.md` if present; returns a placeholder if the file doesn't exist yet (Task 77 will populate it). This function is wired into both the root Click command's `help=` parameter AND the `pflow guide` no-args path

### MCP namespace

- `pflow mcp list [keyword...]` — new command listing MCP tools; grouped-by-server summary with no args; filtered detail view with keywords; AND logic; smart-case; searches name and description
- `pflow mcp find "description"` — LLM-powered MCP tool search; port LLM logic from current `registry discover` but scope to MCP nodes only
- `pflow mcp describe <tool>` — MCP tool details; port from current `registry describe` but scoped to MCP nodes
- `pflow mcp servers` — list configured servers; functionality from current `mcp list`
- `pflow mcp add|remove|sync|serve` — unchanged
- `pflow mcp tools` removed
- `pflow mcp info` renamed to `pflow mcp describe` (same functionality)

### Deletions (CLI only)

- `pflow registry` command group and all subcommands removed (no aliases)
- `pflow workflow` command group removed (subcommands moved to top-level)
- `pflow instructions` command removed
- `registry scan` removed (user nodes feature is being deprecated independently)

**NOT deleted by this task:**
- `pflow://instructions` and `pflow://instructions/sandbox` MCP resources — stay functional
- MCP tools with old names (`workflow_discover`, `registry_run`, etc.) — stay functional
- Shared service functions — names unchanged, still used by MCP

### Tests

- CLI test files matching old command names renamed to match new names (e.g., `test_workflow_discover.py` → `test_workflow_find.py` or equivalent)
- `mock.patch` targets updated where they reference old CLI command paths (see `src/pflow/cli/CLAUDE.md` for the list of patch targets that will break if moved)
- All existing CLI tests pass under new names
- New tests for the `list` keyword filtering (substring, AND, smart-case, name+description search)
- New test for `mcp list` grouped-by-server summary format
- New test for `pflow guide` stub returning non-empty placeholder
- **MCP server tests remain unchanged** — they test old tool names which still exist

### Help text (FIRST-CLASS requirement, not documentation)

The root `pflow --help` output is the first thing any new agent sees. It is literally the entry point into the entire system. Both `pflow --help` and `pflow guide` (no args) must be designed for a reader who knows absolutely nothing about pflow.

**Design: shared entry content between `pflow --help` and `pflow guide` (no args).**

Both paths render the same content — `pflow --help` is the canonical entry, `pflow guide` (no args) is a fallback for agents that forgot to pass a topic. Single source of truth, no drift. The content lives in `src/pflow/cli/resources/guide/entry.md` (created by Task 77).

**Task 151 responsibility (this task):**

- Wire `pflow --help` to render the content of `entry.md` in the root Click command's help output
- Wire `pflow guide` (no args) to render the same `entry.md` content
- Create a shared helper function, e.g., `render_entry_content()`, that both paths call
- **If `entry.md` doesn't exist yet** (Task 77 not complete): `render_entry_content()` returns a minimal placeholder like "pflow CLI — see Task 77 for full entry content" and Click's default help shows the commands list. This keeps Task 151 shippable independently.

**Task 77 responsibility (separate task):**

- Fill in the actual content of `entry.md` with vocabulary triggers, topic list, and command descriptions

**Requirements for the entry content (fulfilled by Task 77, but shape agreed here):**

- Opens with a 1-2 sentence description of what pflow IS. Something like: "pflow runs workflows — sequences of nodes (http, shell, llm, code, etc.) that chain together through a shared data store. Workflows are markdown files you can save, reuse, and invoke by name."
- Shows the agent's first-command decision tree: "Got an existing workflow to run? → `pflow <name>`. Want to build a new one? → `pflow guide <topic>`. Looking for something already saved? → `pflow find \"...\"`."
- Commands grouped by concern, not alphabetically. Groups: **Running workflows**, **Finding & managing workflows**, **Building workflows**, **MCP integration**, **Config**.
- Each command gets one short line. Full details via `pflow <command> --help`.
- Includes the **topic list** with vocabulary triggers (this is critical for agent long-term memory — see Task 77's entry.md spec)
- Target size: 50–80 lines
- Reads well for AI agents AND humans — no jargon ("shared store", "IR") in the top-level help

**How Click integrates with `entry.md`:**

Click's root command has a `help=` parameter. Options:
1. Set `help=render_entry_content()` at import time (simplest, but loads file at module import)
2. Override Click's help formatter to inject content dynamically
3. Set `command.help = render_entry_content()` after decoration (deferred load)

Pick whichever is cleanest. The key is that `entry.md` is the canonical source and Click renders its content verbatim.

**Requirements for `pflow guide` (fallback mode, no args):**

- Identical content to `pflow --help` (via the shared `render_entry_content()` function)
- No "menu vs full help" distinction — they're the same thing
- Runs instantly, no LLM call, no network

**Requirements for per-command `--help`:**

- Every new or renamed command has updated help text
- Help text uses concrete examples, not just parameter lists
- `pflow probe --help` explains the metadata-not-data output contract up front (so agents don't expect raw values)
- `pflow find --help` vs `pflow list --help` clearly differentiates LLM-powered semantic search from keyword matching
- `pflow mcp list --help` explains the grouped-by-server summary mode vs keyword-filtered mode

**Show expected help output BEFORE implementing:**

Following the project's "Show Before You Code" principle, the implementer should draft the expected output for `pflow --help` and `pflow guide` (no args) and get approval before writing the Click code. For Task 151, this means drafting the placeholder/fallback content. Task 77 drafts the real `entry.md` content.

This is where the agent-first design is most visible — rework cost here is highest if it lands wrong.

### Documentation

**Internal docs (CLAUDE.md files):**

- `README.md` updated with new commands
- `src/pflow/cli/CLAUDE.md` updated to reflect new architecture
- `src/pflow/cli/commands/CLAUDE.md` updated per-command
- `src/pflow/mcp_server/CLAUDE.md` — **not updated in this task** (MCP tool names unchanged)
- `src/pflow/cli/resources/cli-basic-usage.md` — search-and-replace old CLI command names to new ones (in-place update; full content migration happens in Task 77)
- `src/pflow/cli/resources/cli-agent-instructions.md` — search-and-replace old CLI command names to new ones (in-place update; full content restructure happens in Task 77)

**User-facing docs (`docs/` folder, Mintlify `.mdx`):**

The `docs/` folder is the user-facing documentation site. It currently contains ~103 references to old commands across 20 files. All must be updated to match the new CLI surface. These docs are published and are the second touchpoint (after `--help`) for users learning pflow.

**Files to delete:**
- `docs/reference/cli/workflow.mdx` — subcommands flattened to top-level
- `docs/reference/cli/registry.mdx` — registry group removed entirely

**Files to create:**
- `docs/reference/cli/list.mdx` — top-level `pflow list`
- `docs/reference/cli/find.mdx` — top-level `pflow find`
- `docs/reference/cli/describe.mdx` — top-level `pflow describe`
- `docs/reference/cli/history.mdx` — top-level `pflow history`
- `docs/reference/cli/save.mdx` — top-level `pflow save`
- `docs/reference/cli/guide.mdx` — `pflow guide` (document the command shape; content chunks are Task 77)
- `docs/reference/cli/probe.mdx` — `pflow probe`

**Files to update (old command references):**
- `docs/reference/cli/index.mdx` — command index, update to reflect new structure
- `docs/reference/cli/mcp.mdx` — MCP namespace changes (list → servers, new list/find/describe for tools)
- `docs/reference/cli/skill.mdx` — minor, verify no registry/workflow references
- `docs/reference/cli/settings.mdx` — minor, verify no stale references
- `docs/quickstart.mdx` — 6 occurrences, critical first-touch user path
- `docs/guides/using-pflow.mdx` — 3 occurrences
- `docs/guides/publishing-skills.mdx` — 4 occurrences
- `docs/guides/adding-mcp-servers.mdx` — 2 occurrences
- `docs/guides/debugging.mdx` — verify
- `docs/integrations/overview.mdx` — 1 occurrence
- `docs/integrations/claude-code.mdx` — 1 occurrence
- `docs/integrations/cursor.mdx` — 1 occurrence
- `docs/integrations/windsurf.mdx` — 1 occurrence
- `docs/integrations/claude-desktop.mdx` — verify
- `docs/integrations/vscode.mdx` — verify
- `docs/reference/nodes/mcp.mdx` — 1 occurrence (likely references `registry describe` or `registry list`)
- `docs/reference/nodes/index.mdx` — 4 occurrences
- `docs/reference/configuration.mdx` — 3 occurrences
- `docs/how-it-works/template-variables.mdx` — verify
- `docs/how-it-works/batch-processing.mdx` — verify
- `docs/index.mdx` — 1 occurrence (the landing page)
- `docs/CLAUDE.md` — 1 occurrence, internal guidance for doc writers

**Files to leave unchanged:**
- `docs/changelog.mdx` — 14 occurrences, but these are historical. Old commands appearing in past changelog entries should NOT be rewritten. Add a new changelog entry for this CLI restructure.
- `docs/roadmap.mdx` — 1 occurrence, verify it's not a planned feature using old names

**Navigation / site structure:**
- `mint.json` or equivalent Mintlify config may need updates if the sidebar explicitly lists `workflow.mdx` / `registry.mdx`
- New CLI reference pages need to be added to the navigation

**Validation:**
- After updates, grep the entire `docs/` folder for `pflow registry`, `pflow workflow discover`, `pflow workflow list`, `pflow workflow describe`, `pflow workflow history`, `pflow workflow save`, `pflow instructions` — should return zero occurrences except in `changelog.mdx`
- Any code examples in docs should be runnable under the new CLI (no broken tutorials)
- Verify `docs/quickstart.mdx` walks a new user from zero to running a workflow using only new commands

## Implementation Notes

### Command ordering in `main_wrapper.py`

The routing table must check top-level commands BEFORE falling through to the workflow execution catch-all. Current order already does this for `mcp`, `registry`, etc. Add new routes in the same place.

### Reserved names

`WorkflowManager.save()` should reject attempts to save a workflow with any of the reserved top-level command names. Add the reserved list as a constant in `core/workflow/manager.py` or similar. Error message should be clear: "Cannot save workflow named 'find': this name is reserved for the CLI command. Pick a different name like 'find-github-prs'."

### `mcp list` implementation

The grouped summary view needs:
- Total tool count
- Per-server count
- Per-server description (pulled from MCP server metadata, not the first tool)
- "Ambient category hints" — the current plan was to show abbreviated tool name fragments ("channels, messages, users..."). Implementation may vary: could be the first N tool names truncated, or extracted noun fragments, or server-provided categories. Pick whatever is simplest that looks readable.

The detailed view (with keyword) should highlight matched substrings in the output. ANSI color codes for TTY, plain for pipes/non-TTY.

### `pflow describe` behavior

When run on a workflow with required inputs, `pflow my-workflow` without args already shows the interface automatically (verify this is still the case). `pflow describe` is the explicit way to get the same info without attempting to execute. Keep both paths working.

### `probe` output format

Unchanged from current `registry run`:
- Execution ID line (for `read-fields` correlation)
- Available template paths (filtered to relevant fields)
- Execution time
- Not the raw data — intentional, prevents context overload

### Guide stub

For this task, `pflow guide` can return a single message like:

```
pflow guide is not yet implemented. See Task 77 for the full agent instruction system.
Topics requested: <topics or "none">
```

Or something slightly more useful that points at the current `cli-agent-instructions.md` as a temporary fallback. The important thing is that the command exists, is routed correctly, and has the right argument signature so Task 77 can just fill in content.

### What's NOT in scope

- **Content design for `pflow guide`** → Task 77 (CLI-only content files + composition)
- **MCP server tool renames** → follow-up task (see References)
- **MCP server parity** (new tools like `guide`, `probe`, `mcp_list`, `mcp_find`, `mcp_describe`) → follow-up task
- **Removal of `pflow://instructions` MCP resource** → follow-up task
- **Rewriting `mcp_server/server.py` instructions string** → follow-up task
- **Updating `mcp_server/resources/instructions/*.md`** → follow-up task
- **CLI→MCP command parser/renderer** (for transforming guide examples) → follow-up task (only needed if MCP guide content reuses CLI content)
- **Folder reorganization** beyond what's needed for renames (e.g., don't restructure `cli/commands/` beyond splitting/renaming files that the new command shape requires)
- **Deletion of the custom user nodes feature** — that's a separate task, just remove `registry scan` command

## Verification

### Unit tests
- All existing tests pass under renamed files/targets
- New `list` keyword filtering tests cover: single keyword, multi-keyword AND, smart-case, name-vs-description matches, empty result set, highlighted output
- New `mcp list` tests cover: no-args grouped summary, single-keyword filter, multi-keyword filter, server-name keyword routing
- New `guide` stub test: command exists, accepts positional args, returns non-empty string

### Integration tests
- `pflow my-workflow param=X` still works (catch-all routing)
- `pflow list`, `pflow find`, `pflow describe`, `pflow history`, `pflow save` all execute against a test workflow fixture
- `pflow probe` against a core node (e.g., `shell`) returns metadata + template paths
- `pflow mcp list` against a mock MCP server produces grouped output
- `pflow mcp find` against a mock MCP server returns LLM-routed match

### Regression
- Workflows saved with old CLI can still be loaded and executed (file format is unchanged)
- Traces and reports still generate correctly
- `--validate-only`, `--print`, `--output-format json`, `--only`, `--no-cache` flags still work on top-level workflow execution

### Manual verification
- Run `pflow --help` and confirm the help output matches the approved draft from "Show Before You Code"
- Run `pflow guide` (no args) and confirm phase-1 menu matches the approved draft
- Run `pflow mcp --help` and confirm the MCP namespace is clean
- Run `pflow probe --help`, `pflow find --help`, `pflow list --help`, `pflow mcp list --help` and confirm each has concrete examples and clear semantics
- Save a workflow named `find` and confirm the reserved-name error fires
- Connect to pflow via MCP client and confirm the old MCP tools still work (`workflow_discover`, `registry_run`, etc.) — they are NOT renamed in this task

### Agent UX verification (the hardest to check)
- **The "new agent" test**: open a fresh shell with no prior context. Run `pflow --help`. Can you tell what pflow is and what to do next? If not, the help text needs rework before shipping.
- **The "build a workflow" test**: from `pflow --help` alone, can you reach `pflow guide` and understand that's the next step? The discoverability path should be obvious.

### Acceptance
- `make test` passes
- `make check` passes (lint + type check)
- CLI surface matches the Solution section exactly
- `pflow instructions`, `pflow registry`, `pflow workflow` subcommand groups return "command not found" (no fallback, no alias)
- MCP server still exposes its existing tools with their current names (unchanged)
- MCP clients can still read `pflow://instructions` resources (unchanged)

## References

### Files to modify (non-exhaustive, CLI-only)

- `src/pflow/cli/main_wrapper.py` — routing table
- `src/pflow/cli/main.py` — workflow execution entrypoint (stays as catch-all)
- `src/pflow/cli/commands/workflow.py` — split into top-level command files
- `src/pflow/cli/commands/registry.py` — delete, distribute `probe` to new location
- `src/pflow/cli/commands/instructions.py` — delete
- `src/pflow/cli/commands/mcp.py` — rename `list` → `servers`, add `list`/`find`/`describe`, remove `tools`, rename `info` → `describe`
- `src/pflow/cli/commands/read_fields.py` — unchanged
- `src/pflow/core/workflow/manager.py` — add reserved-names list to `save()`
- `src/pflow/cli/CLAUDE.md` — architecture updates
- `src/pflow/cli/commands/CLAUDE.md` — per-command updates
- `src/pflow/cli/resources/cli-basic-usage.md` — search-and-replace CLI command names
- `src/pflow/cli/resources/cli-agent-instructions.md` — search-and-replace CLI command names
- `tests/test_cli/` — rename + update mock.patch targets

### Files NOT touched by this task

- `src/pflow/mcp_server/**` — all MCP server code stays unchanged
- `src/pflow/core/**`, `src/pflow/execution/**`, `src/pflow/registry/**` — shared services keep current names
- `src/pflow/mcp_server/resources/instructions/*.md` — MCP agent instructions stay unchanged

### Related tasks

- **Task 77**: Guide content design and implementation — depends on this task. CLI-only scope: produce the content chunks (`.md` files under `cli/resources/guide/`), including `entry.md` which is the shared source for `pflow --help` and `pflow guide` (no args). Task 151 wires the `render_entry_content()` function; Task 77 fills in the content file.

- **MCP Parity Follow-up (to be created)**: After Task 151 and Task 77 ship, a follow-up task handles:
  - Renaming all MCP tools to match new CLI verbs (e.g., `workflow_discover` → `workflow_find`, `registry_run` → `probe`)
  - Adding new MCP tools: `guide`, `mcp_list`, `mcp_find`, `mcp_describe`, `workflow_history`
  - Removing old MCP tools: `registry_list`, `registry_discover`, `registry_describe` (for core nodes)
  - Removing `pflow://instructions` and `pflow://instructions/sandbox` resources
  - Rewriting `mcp_server/server.py` instructions string
  - Deciding MCP guide content strategy: separate files, or auto-transform CLI guide content via parser

### Prior art / context

- Design discussion: multi-turn conversation on 2026-04-10 / 2026-04-11
- Subagent polls (5 agents each) confirmed naming choices: `guide` (unanimous), `probe` (unanimous), `find` (unanimous), `describe` vs `show` (3/5 `show`, overridden to `describe` due to future collision risk)
- Current 2,225-line `cli-agent-instructions.md` is the content that Task 77 will restructure into topic chunks
- MCP server has its own instruction files in `mcp_server/resources/instructions/` that are separate from the CLI docs. This parallel-file structure already exists today, which is why the CLI-only restructure in Task 151 doesn't affect MCP functionality.
