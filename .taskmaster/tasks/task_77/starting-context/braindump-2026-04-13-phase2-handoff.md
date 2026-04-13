# Braindump: Task 77 Phase 2 Handoff

**Date**: 2026-04-13
**Context**: Multi-turn conversation (very long) that completed Phase 0 + Phase 1 of Task 77. Phase 2 (implementation) is next.

## Where I Am

All content work is done. entry.md is live (renders in `pflow --help` and `pflow guide`). core.md is structurally clean at 773 lines. All node chunks and feature chunks are reviewed. Multiple CLI `--help` texts were improved. The `pflow find` output is self-documenting with confidence-based guidance.

Phase 2 is: implement `compose_guide()`, wire it into the CLI, add reserved names, delete old files, write tests.

## User's Mental Model

This user thinks about EVERYTHING from the agent's perspective. Their constant question is: "what would an agent actually look for?" Every design decision flows from this.

### The principle that drives everything

**"Make the CLI surface self-documenting. The guide only teaches what the CLI can't."**

This emerged mid-conversation and became THE guiding principle. It means:
- How a command works → `--help` (we improved probe, report, settings, mcp describe)
- How to interpret output → embed guidance IN the output itself (we made `pflow find` output include match-score actions)
- When/why to use something → guide content
- Workflow building concepts (templates, step order, inputs) → guide content (CLI can't teach this)

### How the user communicates

- **Pushes back on removal** with "are we covering this elsewhere?" — they want ZERO information loss, just better placement
- **Catches over-removal** — I removed workflow smells, auto-JSON rows, and the API research checklist too aggressively. User caught each one.
- **Resists arbitrary targets** — when I said "condense to 250-300 lines" they said the goal is "does it teach an agent to build a workflow?" not a line count
- **Prefers iterative discussion** — "lets discuss everything at the end" turned into discussing after each section. Don't propose big-bang changes.
- **Asks "what do the top 10% do?"** — wants best practices, cites this explicitly
- **Delegates with clear specs** — "can you assign a pflow code implementer to do this, provide comprehensive and unambiguous instructions." They trust agents but want precise instructions.
- **Thinks about the SYSTEM** — when I suggested a guide chunk for auth, they said "should we have this in settings --help instead?" They see the whole CLI surface, not just the guide.

### Key phrases the user used (load-bearing)

- "agent-first" — every UX decision optimized for AI agents
- "progressive disclosure" — information at the point of need, not upfront
- "outsourcing to --help" — their framing for moving content to CLI help texts
- "we should iterate slowly and deliberately" — process preference
- "is this needed?" — frequent pushback on complexity
- "Most of these instructions was written before caching and --only and report was available" — insight that old content assumes pre-feature capabilities
- "i havent decided yet how I want to handle 'save' part" — STILL OPEN. core.md says "SAVE (Optional)" but not fully committed.

## Key Insights

### Content placement hierarchy (discovered through iteration)

1. **Command output** — best place (agent sees it in context, e.g., find match scores)
2. **`--help`** — next best (agent types `--help` when they need a command)
3. **Node/feature chunks** — loaded when agent picks a specific tool
4. **core.md** — loaded once when building from scratch
5. **entry.md** — the orientation/navigation layer, NOT teaching

Each layer lower should only have content the layers above CAN'T express.

### What entry.md is NOT

Entry.md is NOT a teaching document. It doesn't explain how to build workflows. It's:
- Orientation (what is pflow?)
- Decision (run existing or build new?)
- Navigation (which guide topics exist?)
- Discoverability (run options, --help exists)

Building advice was explicitly excluded. The user caught me trying to put "code for transformation, LLM for interpretation" in entry.md — that's core territory.

### The old instructions were pre-caching

Many patterns in the original 2,225-line file assumed `pflow probe` + manual inspection was the only way to test. Now:
- `--only <node>` tests a node in workflow context (upstream cached)
- `--report` / `pflow report` gives per-node inspection
- Caching makes re-running cheap
- Error messages include fix suggestions (Tasks 143/144/148)

The phased building pattern, debugging process, and "test everything" advice were all obsoleted by these features. We dissolved those chunks entirely.

### "test" means "probe" in the old instructions

The old content says "test" when it means `pflow probe`. Phase 2 should consistently use "probe" for the command, "test" only for the general activity. This inconsistency still exists in some moved content (batch.md, branching.md haven't been condensed).

## Assumptions & Uncertainties

ASSUMPTION: core.md at 773 lines is acceptable. We stopped condensing because the user said quality over line count. But I suspect the reference sections (template patterns ~60 lines, parameter types ~50 lines, multi-stage pipeline ~70 lines) might be better as a separate topic loaded on demand. The user explicitly rejected a core/templates split earlier, so tread carefully.

ASSUMPTION: batch.md (136 lines) and branching.md (145 lines) are fine as-is. The user said they "feel okay" during review but we didn't do a deep editorial pass like we did on core.md. These are raw moved content with minor cleanups (removed headings, added "Use when").

ASSUMPTION: The "SAVE (Optional)" framing in core.md is correct. The user said "i havent decided yet how I want to handle save" and we deferred. It hasn't been explicitly confirmed.

UNCLEAR: Whether `features/sub-workflows.md` should also be loadable as `pflow guide workflow` (the node type name). The topic is `sub-workflows` (from our naming poll), but agents might type `workflow` expecting it. The disambiguation in the task spec says topic names win over saved workflow names. Need to decide: is `workflow` a topic alias for `sub-workflows`?

NEEDS VERIFICATION: The auto-detection mapping for workflow-scoped mode. `type: workflow` in IR → topic `sub-workflows` (not `workflow`). This is a non-obvious mapping that needs careful implementation.

NEEDS VERIFICATION: The exact list of topic names for `RESERVED_WORKFLOW_NAMES`. Current topics: `core`, `http`, `llm`, `code`, `shell`, `file`, `mcp`, `batch`, `branching`, `sub-workflows`. No more `structured`, `nested`, `workflow` (as topics), `mcp-testing`, `debugging`, `phased-building`, `auth`, `external-api`.

## Unexplored Territory

UNEXPLORED: `docs/reference/cli/guide.mdx` — the task spec mentions this for user-facing docs. We haven't touched it. Task 151 may have created a stub.

UNEXPLORED: The `pflow://instructions` MCP resource still exists and serves old content from `mcp_server/resources/instructions/`. Task 152 handles this, but there's a window where MCP agents get different content than CLI agents. We updated `pflow trace report` → `pflow report` in the MCP files, but the broader content divergence remains.

UNEXPLORED: What happens when someone adds a new node type to pflow? The guide system needs a maintenance story — create `nodes/<type>.md`, add to entry.md topic list, add to reserved names. This should be documented somewhere (maybe the CLAUDE.md for the guide package).

CONSIDER: Should `pflow guide` with an unknown topic suggest fuzzy matches? The task spec mentions "helpful error listing available topics" but not fuzzy matching. Given `pflow mcp describe` already has fuzzy matching, this seems consistent.

CONSIDER: The `pflow guide <workflow-ref>` mode parses the workflow IR to auto-detect topics. If the workflow fails to parse, the error should be helpful — suggest using explicit topics instead. Task spec covers this.

MIGHT MATTER: The service orchestration pattern in mcp.md is 40+ lines of full workflow example. It's the only multi-node example in a node chunk (other node chunks show single-node patterns). Feels heavy for a "node guide" — more like a pattern that belongs in core or a separate patterns topic. We didn't discuss this.

MIGHT MATTER: batch.md's "All outputs" paragraph is still very dense (one paragraph explaining results, count, success_count, error_count, errors and their relationships). I flagged this for restructuring as a bullet list but we never did it.

## What I'd Tell Myself

1. **Start with "what does --help already say?" before writing guide content.** I didn't check existing help texts until midway through. Would have saved time.

2. **The user catches over-removal every time.** When removing content, always verify the insight exists elsewhere. Don't assume "this is covered" — grep for it.

3. **Don't propose line targets.** The user's measure is "does it work for agents?" not "is it under N lines?"

4. **The iterative approach is non-negotiable.** Read a section → think → discuss → change. Not "here's my plan for 22 changes, approve?" The user wants to discuss each decision.

5. **When in doubt, ask "should this be in --help?"** The user's instinct is always toward progressive disclosure. If `--help` can teach it, the guide doesn't need to.

## Open Threads

### Phase 2 implementation specifics

The task spec (`.taskmaster/tasks/task_77/task-77.md`) has detailed pseudocode for `compose_guide()`, `resolve_topic()`, `detect_topics_from_ir()`, and `is_workflow_ref()`. Read it — the implementation is well-specified.

Key considerations not in the task spec:
- `cross/` directory is gone. Topic resolution is now: `core.md` (top-level) → `nodes/<topic>.md` → `features/<topic>.md`. No third fallback.
- `structured` is gone as a topic (deleted, content in llm.md). Don't add it to reserved names.
- `nested` and `workflow` are gone as topics. `sub-workflows` is the topic name.
- The `detect_topics_from_ir` mapping: `type: workflow` → topic `sub-workflows`
- `entry-raw-material.md` needs deletion alongside source files

### Things I was about to do before the braindump

- Verify exact `RESERVED_WORKFLOW_NAMES` additions needed
- Check if `docs/reference/cli/guide.mdx` exists and needs updating
- Consider writing a `src/pflow/guide/CLAUDE.md` documenting the guide layout
- Think about whether the guide composition separator (`---`) should include the topic name as a heading

### Production code changes made (beyond guide content)

These files were modified and tests updated — important for the PR:
- `src/pflow/cli/commands/probe.py` — help text rewritten
- `src/pflow/cli/commands/trace.py` — `trace` group → standalone `report` command
- `src/pflow/cli/commands/settings.py` — group help text added
- `src/pflow/cli/commands/mcp.py` — `describe` help text added
- `src/pflow/cli/main.py` — import changed, `"trace"` in removed_commands
- `src/pflow/core/workflow/save_service.py` — `"report"` in reserved names
- `src/pflow/execution/formatters/discovery_formatter.py` — confidence guidance in find output
- MCP instruction files — `pflow trace report` → `pflow report`
- Test files — help text assertions updated, 10→1 content test refactor

## Relevant Files & References

**Read first**:
- `.taskmaster/tasks/task_77/implementation/progress-log.md` — comprehensive record of ALL changes
- `.taskmaster/tasks/task_77/task-77.md` — the spec (Phase 2 pseudocode is in here)

**Guide content** (the deliverables):
- `src/pflow/guide/entry.md` — the live capability map
- `src/pflow/guide/core.md` — 773 lines, the building guide
- `src/pflow/guide/nodes/*.md` — 6 node chunks
- `src/pflow/guide/features/*.md` — 3 feature chunks (batch, branching, sub-workflows)

**Implementation targets** (Phase 2):
- `src/pflow/guide/__init__.py` — add `compose_guide()` here
- `src/pflow/cli/commands/guide.py` — replace stub with real logic
- `src/pflow/core/workflow/save_service.py` — add topic names to reserved set

**To delete in Phase 2**:
- `src/pflow/cli/resources/cli-agent-instructions.md`
- `src/pflow/cli/resources/cli-basic-usage.md`
- `src/pflow/guide/entry-raw-material.md`

## For the Next Agent

**Start by**:
1. Reading the progress log fully: `.taskmaster/tasks/task_77/implementation/progress-log.md`
2. Reading the task spec's Phase 2 section: `.taskmaster/tasks/task_77/task-77.md` (search for "Phase 2")
3. Reading the current `guide/__init__.py` and `commands/guide.py` to understand the stub
4. Running `pflow --help` and `pflow guide` to see the live entry.md

**Don't bother with**:
- Re-reading the old source files (`cli-agent-instructions.md`, `cli-basic-usage.md`) — content is fully migrated
- `entry-raw-material.md` — fully evaluated, all useful content absorbed
- The implementation plan (`implementation-plan.md`) — outdated, progress log is authoritative
- Trying to condense core.md further — the user is satisfied with the current state

**The user cares most about**:
- Implementation quality (clean, simple code — ~50-100 lines for compose_guide)
- Tests that catch real bugs (not coverage padding)
- The guide composition actually working end-to-end
- `make test && make check` clean

**Watch out for**:
- Topic name `sub-workflows` (not `nested`, not `workflow`) — poll result, 5/5 unanimous
- No `cross/` directory anymore — only `nodes/` and `features/` subdirs
- No `structured.md` — deleted, content lives in llm.md only
- The `pflow report` command (was `pflow trace report`) — flattened during this conversation
- Entry.md test coupling — only `test_main_command_help` should assert on content

---

**Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
