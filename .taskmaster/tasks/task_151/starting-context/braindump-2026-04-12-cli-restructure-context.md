# Braindump: Task 151 Implementation Context

**Date**: 2026-04-12
**Context**: Multi-turn design discussion that produced Tasks 151, 77, and 152.

This braindump captures implementation context that isn't in the task file itself. **Read the task file first** (`task-151.md`) — this document fills gaps, not duplicates.

There's a sibling braindump at `.taskmaster/tasks/task_77/starting-context/braindump-2026-04-11-cli-restructure-context.md` that has broader conversation context. Much of it applies here too, especially the user's mental model and design philosophy. **Read that first if you haven't already.** This document focuses specifically on Task 151 implementation concerns.

## User's Working Style (non-obvious)

### Show Before You Code is a HARD gate

The user explicitly wants to see drafted `pflow --help` output BEFORE the Click code is written. This isn't a suggestion — they said it directly in the conversation, and the task file marks it as a requirement. Skipping this gate will waste your time: the user will send you back to draft first.

**Practical approach:** After reading the task file and this braindump, WRITE THE EXPECTED `pflow --help` OUTPUT as a plain text file or in a message to the user. Get approval. THEN start the Click wiring.

The draft can reference the placeholder `entry.md` content (since Task 77 hasn't filled in the real content yet). The point is that the implementer thinks about the help structure before writing code.

### The "no users" mandate is real

The user repeated this multiple times: "we have no users yet," "clean cutover, no fallbacks," "breaking changes are free." Implementer reflex might be to add deprecation warnings, aliases, or fallback routing. **Don't.** The user will reject those suggestions. When you see the old `workflow discover` command, replace it entirely — no "also accept the old name for backwards compatibility."

### Discuss before implementing

CLAUDE.md says this; the user reinforced it in the conversation. For any decision the task file doesn't explicitly cover, STOP and ask. Don't guess. The user prefers to be consulted on 2-3 options with tradeoffs.

Example decisions the task file doesn't cover:
- Exact help text wording
- Test file rename targets (e.g., `test_workflow_discover.py` → ??? — decide a convention and confirm)
- Where `render_entry_content()` lives (helper module? command module? new file?)
- How to handle edge cases in the `is_likely_workflow_name` heuristic for new commands

## Implementation-Specific Tacit Knowledge

### Click help wiring is tricky — three options

Click's `help=` parameter is evaluated at decoration time, not runtime. If you do `@click.command(help=render_entry_content())`, `entry.md` is read at import time — OK for normal cases, but means you can't easily update it without restarting. Three options we discussed:

1. **Set at decoration time** — `help=render_entry_content()` — simple, works, file read at import
2. **Override Click's help formatter** — full control, more code, overkill for this case
3. **Set after decoration** — `workflow_command.help = render_entry_content()` as a module-level statement after the decorator — deferred evaluation, usable

Option 1 is probably fine. The file is small (~50-80 lines), reading it at import time is negligible. If the `entry.md` file doesn't exist yet (Task 77 not merged), `render_entry_content()` falls back to a placeholder string — also cheap.

**Test this specifically:** `pflow --help` must display the `entry.md` content (or placeholder) visibly. Click's default behavior might truncate long help text; verify the full content appears.

### The `render_entry_content()` function is a contract

Task 77 will call this function from the `pflow guide` no-args path. So Task 151 must:
- Create the function in a LOCATION Task 77 can import
- Give it a signature `() -> str` (no args, returns string)
- Make it PUBLIC (not `_render_entry_content`) so it can be imported

Suggested location: `src/pflow/cli/resources/__init__.py` or a new `src/pflow/cli/entry_content.py`. The function should read `src/pflow/cli/resources/guide/entry.md` if it exists, otherwise return a clear placeholder:

```python
def render_entry_content() -> str:
    entry_path = Path(__file__).parent / "resources" / "guide" / "entry.md"
    if entry_path.exists():
        return entry_path.read_text()
    return _placeholder_entry_content()

def _placeholder_entry_content() -> str:
    return """\
pflow - CLI for agent-first workflow execution

(Full help content pending Task 77. Run `pflow --help` after Task 77 merges
for the complete entry content with command list and topic capability map.)

Commands:
  [command list will appear here via Click default rendering]
"""
```

The placeholder exists so Task 151 can ship independently. Task 77 fills in the real `entry.md`, at which point `render_entry_content()` automatically picks it up.

**IMPORTANT:** The placeholder must be functional on its own — running `pflow --help` with just the placeholder should still produce usable output (Click's default command listing + the placeholder header).

### Reserved names mechanism (Task 77 extends this)

Task 151 creates the reserved-names list to prevent workflow saves with colliding names. Task 77 will ADD to this list (all topic names). So make it extensible:

```python
# In core/workflow/manager.py or a new constants module

RESERVED_WORKFLOW_NAMES: frozenset[str] = frozenset({
    # Top-level CLI commands
    "list", "find", "describe", "history", "save", "guide", "probe",
    "mcp", "skill", "settings", "read-fields", "run",
    # Task 77 extension placeholder — topic names will be added here:
    # "core", "http", "llm", "code", "shell", "file", "workflow",
    # "batch", "branching", "nested", "structured",
    # "mcp-testing", "phased-building", "debugging", "external-api",
})
```

Make it a `frozenset` so it's immutable. Task 77 will submit a PR that replaces the set with a larger one — that's fine, no API compatibility issue.

The `WorkflowManager.save()` method checks this set and raises a clear error:

```python
if name in RESERVED_WORKFLOW_NAMES:
    raise WorkflowSaveError(
        f"Cannot save workflow named '{name}': this name is reserved "
        f"for the CLI command. Pick a different name like '{name}-mine'."
    )
```

The error message should NAME the collision type explicitly — agents parsing the error need to know whether it's a command collision or a topic collision (Task 77 will make this more specific).

### The `cli-agent-instructions.md` search-and-replace

Task 151 does an IN-PLACE search-and-replace of old CLI command names in `cli-agent-instructions.md`. This is an interim step — Task 77 later deletes the file entirely and replaces it with chunks.

Why do the in-place update in Task 151: if you DON'T, any user who runs `pflow instructions create` (before it's removed) sees stale command names. Even though the command is being removed, the file might still be served via the MCP resource path until Task 152. The in-place update is a stopgap.

**Exact replacements** (non-exhaustive; grep for all `pflow workflow <verb>` and `pflow registry <verb>` patterns):

| Old | New |
|---|---|
| `pflow workflow discover` | `pflow find` |
| `pflow workflow list` | `pflow list` |
| `pflow workflow describe` | `pflow describe` |
| `pflow workflow history` | `pflow history` |
| `pflow workflow save` | `pflow save` |
| `pflow registry discover` | `pflow mcp find` (context-dependent — see below) |
| `pflow registry list` | `pflow mcp list` OR `pflow guide <topic>` (context-dependent) |
| `pflow registry describe` | `pflow mcp describe` OR `pflow guide <topic>` (context-dependent) |
| `pflow registry run` | `pflow probe` |
| `pflow instructions usage` | `pflow --help` |
| `pflow instructions create` | `pflow guide` |

**Context-dependent replacements need judgment.** `pflow registry list slack` → `pflow mcp list slack` (MCP). `pflow registry list` in the context of "see what nodes exist" → probably `pflow guide` (which shows topics). An agent doing the replacement should read the surrounding paragraph to decide.

### `mcp list` grouped-by-server implementation

The task file describes the grouped summary format. One implementation hint: the current `registry.list()` returns all nodes flat. You need to:
1. Filter to `type == "mcp"` nodes (or whatever the filter mechanism is)
2. Group by server (parse the node name — `mcp-slack-SEND_MESSAGE` has server `slack`)
3. Count per group
4. Generate ambient category hints (implementation flexibility — "whatever reads well")

For the "ambient category hints," you can either:
- Extract the first 5-6 tool names per server and show them truncated
- Pull server-provided categories if MCP metadata has them (check `MCPRegistrar` / `registry/metadata_extractor.py`)
- Use simple noun extraction from tool names ("SEND_MESSAGE" → "messages")

**Pick whatever is simplest that looks readable.** The user said "implementation may vary" and "pick whatever reads well." Don't over-engineer this.

### Routing table conventions (main_wrapper.py)

Current routing table in `main_wrapper.py` is a dict mapping subcommand name → handler function. The key insight: it checks the FIRST non-option arg against known subcommand names. If it's a subcommand, route there. Otherwise fall through to workflow execution.

**New subcommands to add:**
- `list` (top-level)
- `find`
- `describe`
- `history`
- `save`
- `guide`
- `probe`
- (keep existing: `mcp`, `skill`, `settings`, `read-fields`)

**Subcommands to remove:**
- `workflow` (all subcommands flattened)
- `registry` (all subcommands removed or redistributed)
- `instructions` (removed)

**Special case — `pflow run <workflow-name>`:** the current code silently strips the `run` prefix in `_preprocess_run_prefix`. Keep this behavior. `pflow run` is a no-op alias for workflow execution.

**Special case — workflow name collision:** a user might save a workflow with a name that happens to match a subcommand. The routing table must check subcommands FIRST, so `pflow list` always means the list command, never "run a workflow named list." The reserved names check in `save()` prevents this collision from being created in the first place.

### Test mock.patch targets

`src/pflow/cli/CLAUDE.md` documents specific `mock.patch` targets that tests rely on. If you move or rename any of these, tests will break:

```
- pflow.cli.main.WorkflowManager
- pflow.cli.main.execute_json_workflow
- pflow.cli.main.workflow_command
```

Other patch targets may exist — search `tests/` for `mock.patch(".*cli\.` patterns.

**Test file renames:** Not prescribed in the task file. Suggestions:
- `test_workflow_discover.py` → `test_find.py` (since it's no longer nested under workflow)
- `test_workflow_list.py` → `test_list.py`
- `test_workflow_describe.py` → `test_describe.py`
- `test_registry_run.py` → `test_probe.py`
- `test_registry_list.py` → `test_mcp_list.py` (if it's specifically about MCP listing) or split into separate test files
- `test_instructions.py` → `test_guide.py`

Decide on convention early and be consistent.

### Click CliRunner gotcha

`CliRunner().invoke()` returns `False` for `isatty()` always. This affects tests that exercise TTY-specific behavior like batch-progress `\r` rendering. Patch `sys.stderr.isatty()` to `True` in those tests. See `cli/CLAUDE.md` Known Issues section for details.

This is a testing gotcha only; production behavior is fine.

## Things NOT To Do

### Don't touch MCP server code

Task 152 handles MCP parity. Leave `src/pflow/mcp_server/**` completely alone. Even if you see an old tool name that "should" be renamed, it's Task 152's problem. Scoping Task 151 this tightly is what makes it possible to ship independently.

### Don't rename shared service functions

`core/workflow/discovery.py:discover_workflow()` keeps its current name even though the CLI command becomes `find`. MCP still calls the function by its current name. Only the CLI wrapper layer changes.

### Don't add aliases or deprecation

No "also accept `pflow workflow discover` for backwards compat." No "emit a deprecation warning when the old command is used." Clean cutover. If an agent using an old script hits a "command not found" error, that's acceptable — the user has no users yet.

### Don't skip the docs update

`docs/` has ~103 references across 20 files. These are published user-facing docs (Mintlify). The task file lists every file and what to change. Don't treat this as a "doc polish" step — it's a first-class requirement.

### Don't over-engineer `render_entry_content()`

It's a 3-line function that reads a file and returns a string (with a fallback). Don't add caching, don't add template variables, don't add dynamic content injection. KEEP IT SIMPLE.

### Don't try to implement `pflow guide` content composition

That's Task 77. Task 151 only needs `pflow guide` to exist as a command that returns `render_entry_content()` when called without args, and a placeholder when called with topics. Don't write the full composition logic.

## Things That Might Surprise You

### The MCP server has its own separate instruction files

I discovered mid-conversation: `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` and `mcp-sandbox-agent-instructions.md` exist as SEPARATE files from the CLI's `cli-agent-instructions.md`. They reference MCP tool names, not CLI commands. **Don't touch them in Task 151.** They're Task 152's problem.

### The `mcp list` rename changes semantics

Current `pflow mcp list` lists configured SERVERS. New `pflow mcp list` lists TOOLS. Current behavior moves to `pflow mcp servers`. This is a semantic break — anyone who memorized "mcp list shows servers" will be confused. The user acknowledged this tradeoff: tools are what agents care about, servers are setup-time concerns, so tools get the shorter name.

**Be explicit about this in release notes / changelog** when you write them.

### The subagent polls were unanimous for a reason

The conversation ran 4 naming polls (5 agents each, neutral framing):
- `guide` — unanimous 5/5
- `probe` — unanimous 5/5
- `find` (for MCP LLM search) — unanimous 5/5
- `describe` vs `show` (for workflow detail) — 3/5 for `show`, overridden to `describe` due to future collision risk

**Don't re-litigate these.** The user accepted the results. If you think a different name is better, the answer is no — unless you have a specific new reason the polls didn't surface.

### Reserved names need consistency

The reserved names list protects against workflow name collisions. It should include:
- All top-level CLI commands: `list`, `find`, `describe`, `history`, `save`, `guide`, `probe`, `mcp`, `skill`, `settings`, `read-fields`, `run`
- (Task 77 will add all topic names later)

Error message must be clear: "Cannot save workflow named '<name>': this name is reserved for a CLI command. Pick a different name like '<name>-mine'."

If someone has an EXISTING saved workflow with a reserved name (from before this task), it'll still load — the reserved check is only on save. We don't care about cleanup because there are no users yet.

## Open Questions You'll Hit

### UNCLEAR: Which file does `guide.py` live in?

Task 77's content composition lives in `cli/commands/guide.py` probably. But Task 151 creates the stub — where does the stub go? Suggested:
- Create `src/pflow/cli/commands/guide.py` now (Task 151) with stub implementation
- Task 77 replaces the stub content with real composition logic

Alternatively, put the stub in an existing file and move it later. But the "create it in the final location" approach minimizes churn.

### UNCLEAR: How to register `pflow probe` vs keeping it under `mcp`

`probe` is top-level per the design. Current `registry run` is under `registry`. Where does the new `probe` command live?

- **Option A:** New file `src/pflow/cli/commands/probe.py` with a dedicated module
- **Option B:** Move the registry_run.py logic to probe.py with minimal changes
- **Option C:** Combine with other "build helpers" (read-fields, guide, probe) into a single file

My lean: Option B — rename `registry_run.py` → `probe.py`, update the routing, done.

### UNCLEAR: Reserved names list location

Options:
- `src/pflow/core/workflow/manager.py` — near the save logic
- `src/pflow/core/workflow/reserved_names.py` — new file, cleaner
- `src/pflow/cli/constants.py` — new file in CLI module

My lean: new file `src/pflow/core/workflow/reserved_names.py` — shared between CLI validation and MCP validation (if needed later).

### NEEDS VERIFICATION: Docs folder count

I said "~103 references across 20 files" in `docs/`. That count was from grep output mid-conversation. Verify with a fresh grep before you start.

### NEEDS VERIFICATION: Mintlify navigation config

`docs/` uses Mintlify. The navigation might be in `mint.json` or similar. Task 151 lists this as a verification item but I didn't look at the actual config. Check whether the sidebar needs updates.

## What I'd Tell Myself Starting Task 151

1. **Read both braindumps first** — this one AND `task_77/starting-context/braindump-2026-04-11-cli-restructure-context.md`. The Task 77 braindump has broader design context.

2. **Draft `pflow --help` output as text first.** Before writing any Click code. Submit for approval. User will push back if you skip this.

3. **Start with the routing table changes** (`main_wrapper.py`). Get the new command names WORKING (even if they're stubs that print "not implemented"). Then fill in each command.

4. **Do `pflow list`, `pflow find`, `pflow describe` first** — they're ports from existing `workflow <subcommand>` logic. Easy wins.

5. **`pflow guide` stub is the SIMPLEST thing that works.** Return `render_entry_content()` on no args, return a placeholder on any args. Don't implement composition.

6. **`pflow probe` is also a port** — the existing `registry run` logic moves to a new command.

7. **`pflow mcp list` is the biggest NEW surface** — grouped summary + keyword filter. This is where to spend care. Implement the summary logic, then the filter logic separately.

8. **Do the docs update as a SEPARATE pass** after the code works. Easier to be thorough without code-context switching.

9. **Run `make check` and `make test` frequently.** You'll break things. Discover breakages early.

10. **When in doubt, ask the user.** CLAUDE.md says so; the user's working style confirms it. Don't silently make decisions.

## Open Threads (Things I Was Going To Do But Didn't)

- **Didn't verify `pflow visualize` and `pflow trace report` commands** — they should still exist post-restructure. Grep for them in Task 151's scope.
- **Didn't check `pflow --version` routing** — probably unchanged, verify.
- **Didn't look at Task 125** (Human-in-the-Loop Approval Gates) — listed as "Next" with 151 and 77. If it's being worked on in parallel, check for conflicts.
- **Didn't look at Task 142** (Function-Based Code Node Syntax) — mentioned in CLAUDE.md roadmap. Probably no conflict but worth a glance.

## Relevant Files (verified to exist)

- `src/pflow/cli/main.py` — workflow execution orchestration
- `src/pflow/cli/main_wrapper.py` — routing table
- `src/pflow/cli/commands/workflow.py` — current workflow group
- `src/pflow/cli/commands/registry.py` — current registry group (to delete)
- `src/pflow/cli/commands/instructions.py` — current instructions (to delete)
- `src/pflow/cli/commands/mcp.py` — current mcp commands
- `src/pflow/cli/commands/read_fields.py` — existing, unchanged
- `src/pflow/cli/resources/cli-agent-instructions.md` — 2,225 lines, needs in-place search-and-replace
- `src/pflow/cli/resources/cli-basic-usage.md` — 192 lines, same treatment
- `src/pflow/cli/CLAUDE.md` — architecture docs, needs updating
- `src/pflow/cli/commands/CLAUDE.md` — per-command docs, needs updating
- `src/pflow/core/workflow/manager.py` — save logic, needs reserved names check
- `src/pflow/mcp_server/**` — OFF LIMITS for this task
- `docs/**` — ~20 files to update
- `tests/test_cli/**` — rename + update mock.patch targets

## For the Next Agent

**Start by:**
1. Reading `.taskmaster/tasks/task_151/task-151.md` fully
2. Reading THIS braindump fully
3. Reading `.taskmaster/tasks/task_77/starting-context/braindump-2026-04-11-cli-restructure-context.md` for broader design context
4. Drafting expected `pflow --help` output as plain text and getting user approval
5. THEN starting implementation

**Don't bother with:**
- MCP server anything (Task 152)
- Backwards compatibility, aliases, deprecation warnings (no users)
- Re-litigating naming decisions (polls settled these)
- Optimizing `render_entry_content()` (keep it trivial)
- Writing full `pflow guide` content logic (Task 77)

**The user cares most about:**
- Agent-first UX (help text, command intuition, discoverability)
- Simplicity and smallness of implementation
- "No users" mandate (clean cutover)
- Show Before You Code on help text and user-facing surfaces
- Discussing design decisions before implementing

**Watch out for:**
- Click's `help=` being evaluated at decoration time
- Mock.patch targets breaking when you move code
- CliRunner's `isatty()` quirk
- Docs folder having more references than you expect
- Reserved names list needing to be extensible for Task 77

**Use subagents for:**
- Content review / UX feedback on help text drafts
- Mechanical grep-and-replace in docs (one subagent per directory, parallel)
- Running test suites and reporting results
- Looking up existing implementation patterns you might reuse

---

**Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
