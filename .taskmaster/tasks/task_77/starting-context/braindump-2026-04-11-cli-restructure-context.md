# Braindump: Task 77 Context from CLI Restructure Conversation

**Date**: 2026-04-11
**Context**: Multi-turn design discussion that rewrote Tasks 151, 77, and created 152.

This braindump captures tacit knowledge from the conversation that shaped the current Task 77 spec. The task file itself is self-contained — **read it first**. This document fills gaps the task file doesn't cover: the conversation journey, user's priorities, rejected alternatives, and uncertainties.

## Where We Are

Task 77 has been completely rewritten. The original version ("Distribute Agent Instructions to Nodes") proposed attaching guidance to individual node metadata. The new version ("Pflow Guide — Tailored Agent Instructions") centralizes content in a `cli/resources/guide/` directory with topic-scoped `.md` chunks composed at runtime.

Task 77 now depends on Task 151 (CLI restructure, which creates the `pflow guide` stub) and is independent of Task 152 (MCP parity follow-up). The three-task split is intentional and load-bearing — don't try to collapse them.

## User's Mental Model

### Exact phrasing they used (load-bearing)

- **"agent-first"** — every UX decision should be optimized for AI agents as primary users, not humans reading docs cover-to-cover
- **"clean cutover, no fallbacks"** — they're explicit that pflow has zero users, so breaking changes are FREE. No deprecation warnings, no aliases, no migration logic. Don't suggest them.
- **"no users yet"** — repeated. This frames what's in vs out of scope for every decision.
- **"MVP context"** — bias toward simple/direct over speculative future-proofing
- **"feels natural to AI agents"** — their evaluation criterion for names. This drove four separate subagent polls where we asked 5 agents each to suggest names WITHOUT seeing any options.
- **"is this needed?"** — they push back HARD on speculative features. Pre-emptively ask yourself this before adding anything.
- **"Show Before You Code"** — from CLAUDE.md; they treat it as a real gate, not guidance. For Task 77, Phase 1 (draft expected outputs, get approval, then code) is non-negotiable.

### What they emphasized vs. glossed over

**Emphasized:**
- The phase-1 menu / `pflow --help` experience for new agents that know nothing about pflow
- The split between `pflow list` (keyword) and `pflow find` (LLM) as the core mental model — same verbs at both scopes
- Consistency between CLI and MCP tool names (but deferred the MCP work to Task 152)
- Size budget — they asked specifically "will this work with the code since CLI and MCP share a lot?" when I proposed the split. They care about implementation feasibility, not just design elegance.

**Glossed over (could matter):**
- Exact content boundaries between `core.md` and per-topic chunks. I proposed the split in the spec but the user didn't review each decision individually. The implementer has latitude.
- Error messages for unknown topics. I wrote "helpful error listing available topics" but the user didn't approve specific text.
- Whether `cross/*.md` is the right bucket name. "cross-cutting" was my framing, user didn't push back but didn't endorse either.

### How their understanding evolved

Started: "Is the current `pflow instructions usage` + `pflow instructions create` model intuitive for agents?" (open question)

Middle: I proposed `pflow learn` with `--nodes` / `--features` flags. User pushed back that the flag soup felt complex. We landed on positional args (`pflow guide http llm batch`).

Later: User asked why `pflow registry describe llm` and `pflow guide llm` would both exist. This was a crucial pivot — they saw the overlap. I initially wanted guide to teach framework and registry to describe nodes. User pushed back: "shouldn't guide llm include both the interface AND everything else for llm node?" — that's what landed in the spec.

Later still: User asked whether `pflow list` and `pflow mcp list` being inconsistent was confusing. I hadn't noticed the inconsistency. This led to the grouped-by-server summary design for `mcp list` and the decision to kill `mcp search` entirely (redundant with `list <keyword>`).

Final: User wanted to split the work into three tasks to keep each one simple. Task 151 = CLI surface, Task 77 = guide content, Task 152 = MCP parity.

## Key Insights Not In The Task File

### Why the `guide/` directory architecture was chosen

We explicitly considered and rejected:
- **Attaching guidance to node metadata** (original Task 77 design) — rejected because it's harder to maintain cross-cutting content like batch/branching that applies to any node
- **Template interpolation** (`{{cmd:...}}` placeholders in content) — rejected in favor of plain-CLI-commands parsing approach that the user suggested
- **Dynamic content** (e.g., "you have X MCP servers configured") — explicitly out of scope
- **Auto-generation from node docstrings** — future task, don't do it now

The final architecture (static `.md` files, read-and-concatenate composition) won because: implementer can edit content by opening a file, code stays ~20-50 lines, no template syntax to learn, chunks are self-contained and reviewable.

### Why `describe` won over `show` despite losing the poll 3-5

Subagent poll was 3 for `show`, 2 for `describe`. But one agent flagged a future-collision risk that swayed the decision: **"show" could be needed later for "show me the raw source" or "render the mermaid graph"**, while `describe` unambiguously means "structured interface summary." The user accepted this future-proofing argument even though it went against the plurality.

**Implication for Task 77:** If content ever needs to be rendered as a diagram or raw source dump, `show` is available. Keep this in mind.

### Why we killed `mcp search` but kept `mcp find`

User observed that `list <keyword>` and `search <keyword>` were redundant. The insight: `list` without args means "overview," `list <keyword>` means "filtered." So `mcp search` was unnecessary. But `mcp find "natural language description"` remains because it's an entirely different operation — LLM-powered semantic search, not keyword filtering.

**This matters for guide content:** The `nodes/mcp.md` chunk should teach BOTH `mcp list` (keyword) and `mcp find` (LLM), and explain when to reach for which. It's not obvious from the names alone.

### The grouped-by-server `mcp list` output was the user's idea

When I described `mcp list` with no args returning a flat list, the user said "grouped-by-server summary sounds like a great idea if it is what I think." They were picturing it before I described it. The actual format I proposed (with tool counts, ambient hints, total count) was me drawing out the shape — but the idea of grouping was theirs.

**This matters for guide content:** When explaining `mcp list` in `nodes/mcp.md`, lead with the grouped summary example. It's the most distinctive feature.

### Content is ALREADY separate between CLI and MCP

I discovered this mid-conversation by grepping the code. `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` and `mcp-sandbox-agent-instructions.md` are SEPARATE files from the CLI's `cli-agent-instructions.md`. They reference MCP tool names (`workflow_discover`, `registry_run`), not CLI commands.

**Implication for Task 77:** Task 77 only needs to worry about CLI content. Don't touch the MCP instruction files — they're Task 152's problem. The parallel-file pattern that exists today STAYS until Task 152 decides on Option A (keep parallel) or Option B (parser-based single source).

### The `cli-agent-instructions.md` find-and-replace happens in Task 151

Task 151 does an in-place search-and-replace of OLD CLI command names to NEW ones in `cli-agent-instructions.md` (the full content restructure happens in Task 77). This means **when Task 77 starts the content audit, it reads the file with NEW command names already in place**. Don't be confused if the source material says `pflow find` instead of `pflow workflow discover` — that's correct after Task 151.

**Sequencing matters:** Task 151 must be MERGED (not just in progress) before Task 77 starts, otherwise the content audit will waste time updating stale commands that Task 151 will overwrite.

## The Content Audit Reality Check

Phase 0 of Task 77 is tagging every section of the current 2,225-line `cli-agent-instructions.md` to a target chunk. This is tedious manual work. A few warnings:

### Don't try to automate it

Several sections resist easy categorization. Example: the "Common Agent Mistakes" table mixes node-specific mistakes (missing `- prompt:` on batch LLM), feature-specific mistakes (batch providers), and cross-cutting mistakes (ignoring workflow discovery). A parser can't decide where each row belongs — a human reading and judging each one can.

### Sections I remember being tricky

From reading the full 2,225 lines earlier in this conversation, these sections will need careful judgment:

1. **"Workflow Smells" table** (around line 2090) — applies cross-node. Could live in `core.md` or `cross/debugging.md`. My lean: `core.md` (always worth seeing).

2. **"Real Request Parsing" table** (around line 2045) — cross-cutting advice about handling ambiguous user requests. `core.md`.

3. **"MCP Output Has NO Standard Structure"** warning — belongs in both `nodes/mcp.md` and `cross/mcp-testing.md` with cross-references. Resist the urge to deduplicate.

4. **The "Extraction vs Transformation: Decision Rule"** (around line 1145) — cross-cutting decision framework. `core.md`.

5. **"Intent signals to recognize" table** (around line 290) — maps user phrases to actions. `core.md`.

6. **"Supported Service Categories"** (around line 58) — lists MCP categories. Probably `nodes/mcp.md`.

7. **Phase-based building for complex workflows** (around line 555) — explicit cross-cutting. `cross/phased-building.md`.

### Sections that might be safe to delete

Not every current paragraph needs to migrate. Task 151 makes some content redundant:

- Bits that explain `pflow workflow discover` output format — `pflow find --help` covers this now
- Bits that explain `registry run` output — `pflow probe --help`
- Bits about when to run `pflow workflow list` — `pflow list --help`

Flag these during Phase 0 as "delete" with reason, don't migrate them to chunks.

### Size budget is aspirational, not enforced

I wrote size budgets in the spec (~100 lines for core, ~50-100 for nodes, etc.) but they're guidelines, not hard limits. If `nodes/llm.md` needs 150 lines because LLM is genuinely more complex, fine. The real target is "agent can build a workflow with the composed output" — that's the acceptance criterion.

## Assumptions and Uncertainties

### ASSUMPTION: Topic resolution order won't have collisions
Spec says resolver checks `nodes/`, then `features/`, then `cross/`. Phase 0 should verify no topic name exists in two directories. If there's a collision (e.g., "workflow" could be a node type AND a nested workflow feature), one directory wins and the other topic gets renamed.

### ASSUMPTION: `cli-basic-usage.md` content fits into `core.md` + `menu.md`
I wrote that these two files get deleted with content migrated to `core.md` and `menu.md`. But I didn't verify that ALL of `cli-basic-usage.md` fits cleanly. Phase 0 should check.

### UNCLEAR: Exact relationship between `pflow --help` and `pflow guide`
Task 151 handles `--help`. Task 77 handles `guide`. But there's overlap — both are entry points for new agents. We said `--help` should be short (1-2 sentences what pflow IS, then command list), while `guide` is the "learn how to build" entry. Still, there will be some content overlap that's OK.

### UNCLEAR: Should `guide` ever return JSON?
We didn't discuss `--output-format json` for `pflow guide`. Probably not worth supporting — guide content is markdown and agents can parse markdown fine. But someone might ask. Default: no, unless someone pushes back.

### NEEDS VERIFICATION: Exact line count of current `cli-agent-instructions.md`
I said 2,225 lines based on reading it earlier. Actual count may differ slightly. Verify before Phase 0 starts.

### NEEDS VERIFICATION: `cross/` directory name
I chose "cross" for cross-cutting topics. User didn't push back but also didn't explicitly approve. If it reads awkwardly in actual paths (`guide/cross/debugging.md`), renaming to `topics/`, `misc/`, or folding into `features/` are alternatives.

## Unexplored Territory

### UNEXPLORED: Content for agents that DON'T use CLI

The task spec is CLI-only. But there's an open question for Task 152: should MCP-side guide content be parallel files (Option A) or parser-transformed from CLI content (Option B)? Task 77 should be written such that Option B is possible — meaning the CLI content uses plain `pflow <command>` syntax in code blocks (not template placeholders), so a parser can find and transform them. This is already how the task is scoped, but worth re-confirming during Phase 0.

### UNEXPLORED: Versioning and staleness
When a node's interface changes (new param, breaking change), the `nodes/<type>.md` chunk needs updating. There's no automation for this. A breaking change to `http` node's `headers` param, for example, would silently go stale in `nodes/http.md` until someone notices. Consider adding a CI check that `nodes/*.md` references match actual node params — but this is a follow-up, not Task 77.

### UNEXPLORED: Guide content testing
I wrote tests that verify the composition logic (concatenates correctly, handles unknown topics). But how do you test that the CONTENT is good? E.g., "running `pflow guide http` actually teaches an agent to use HTTP nodes correctly." This is an agent-UX test that's hard to automate. The task spec mentions a "build a workflow from nothing" manual test, but it's manual.

**MIGHT MATTER:** Consider whether test workflows under `examples/` can serve as "did the guide work?" assertions. If an agent builds `examples/fetch-api.pflow.md` using only `pflow guide http`, that's validation.

### UNEXPLORED: Interaction with `pflow visualize` and `pflow trace report`
These two commands weren't discussed. They should still exist post-restructure. Not touched by Task 77 but worth verifying they don't get accidentally broken.

### CONSIDER: What if an agent asks for a topic that LOOKS LIKE a node but isn't?
Example: `pflow guide rest-api` — `rest-api` isn't a node type but an agent might type it intuitively. Error handling should be forgiving — suggest "did you mean `http`?" with fuzzy matching, or just list all topics. Not in the spec as a requirement; could be a nice UX improvement.

### CONSIDER: Migration announcement
pflow has no users, so this doesn't matter externally. But the internal CLAUDE.md files reference the old command names throughout. Task 151 updates some of them; Task 77 updates `src/pflow/cli/resources/CLAUDE.md`. Between the two tasks, there may be stale references in other CLAUDE.md files (especially nested ones under `src/pflow/core/`, `src/pflow/nodes/`, etc.). Grep after completion to make sure.

## The Polls (context the task file doesn't fully capture)

Four naming polls were done during the conversation:

1. **`guide` vs alternatives** — unanimous 5/5 for `guide`
2. **`probe` vs `try`/`inspect`/etc.** — unanimous 5/5 for `probe`
3. **`find` vs `discover`/`ask`/etc. for MCP LLM search** — unanimous 5/5 for `find`
4. **`describe` vs `show`/`info`/etc.** — split 3/2 for `show`, overridden by the "future collision" argument

**Why poll results matter for Task 77:** If the content in `core.md` or `nodes/*.md` needs to coin new terminology, and you're uncertain, consider a quick subagent poll. The user values this approach and explicitly asked for it during the conversation. Use `general-purpose` subagents with unbiased framing — describe the concept WITHOUT suggesting names.

## What I'd Tell Myself

If I were starting Task 77 fresh:

1. **Read the current `cli-agent-instructions.md` in full first.** Before writing any chunks, know the source material cold. I read it during the conversation and it took real effort — don't skip.

2. **Do the tagging as a spreadsheet or plain list first.** Before creating chunk files, make a flat list: "Lines 1-40 → core.md (mental model)", "Lines 41-85 → nodes/http.md (interface)", etc. Review the mapping before creating files. It's much easier to move sections at the mapping stage than to reshuffle chunks after they're written.

3. **Start with `core.md` and one node (`http` or `code`)**, compose `pflow guide http`, read it end-to-end. If it reads well, the template works — replicate for other nodes. If it reads badly, fix the composition strategy before doing the other chunks.

4. **Get the Phase 1 drafts APPROVED before writing code.** The user is serious about Show Before You Code. Don't skip this gate.

5. **Don't suggest alias/deprecation/fallback mechanisms.** The user will reject them. Clean cutover every time.

6. **When you hit a design decision that wasn't covered, ask.** The user prefers discussion over silent guessing. But present 2-3 options with tradeoffs (per CLAUDE.md: "Never make decisions silently").

## Open Threads (things I didn't do)

- **Task 125** (Human-in-the-Loop Approval Gates) is listed as "Next" alongside 151 and 77 in the updated CLAUDE.md roadmap. I didn't look at it. Check whether it affects guide content — if approval gates are a new feature, `features/approval.md` might need to exist. Probably scoped for a later task.

- **The `pflow://instructions` MCP resource** — still exists after Task 151 (by design). Task 152 removes it. If Task 77 happens BEFORE Task 152, the MCP resource content will reference the deleted `cli-agent-instructions.md` file. Task 152 will fix this, but there's a brief window where MCP agents could get a broken resource. **Mitigation:** either ensure Task 152 ships close to Task 77, OR have Task 77 leave a stub file at `cli-agent-instructions.md` pointing to `pflow guide`.

- **`cli/resources/CLAUDE.md`** — I specified this file should be created/updated as part of Task 77 to document the guide layout. I didn't check if it currently exists. Verify.

## For the Next Agent

**Start by:**
1. Reading `.taskmaster/tasks/task_77/task-77.md` fully
2. Reading THIS braindump fully
3. Verifying Task 151 status — **Task 77 requires Task 151 to be merged first**
4. Reading `src/pflow/cli/resources/cli-agent-instructions.md` in full to internalize the source material

**Don't bother with:**
- Writing any implementation code until Phase 0 (content audit) and Phase 1 (draft outputs approval) are done
- MCP-side anything (that's Task 152)
- Template interpolation or dynamic content (explicitly out of scope)
- Trying to unify the CLI and MCP instruction files (deferred to Task 152)
- Performance optimization — content loading happens once, it's fine

**The user cares most about:**
- Simplicity and smallness of the implementation code
- Quality of the composed output (does it teach an agent to build workflows?)
- No speculative features or complexity
- Show Before You Code — draft outputs approved before implementation

**Watch out for:**
- Scope creep into MCP territory (defer to Task 152)
- Trying to make Phase 0 automated (it's manual judgment work)
- Size budget obsession — the real acceptance is "does an agent learn to build workflows from this?", not line counts
- Assuming content decisions are settled — some aren't (see UNCLEAR/ASSUMPTION markers above)

**Use subagents for:**
- Content review of draft chunks (pflow-codebase-searcher or general-purpose) — have them read a chunk standalone and assess "could an agent build a workflow with only this information?"
- Naming decisions if new terminology emerges (neutral-framing poll, 5 agents, aggregate results)
- Never skip these when you're uncertain — the user expects subagent use when it adds value

## Relevant Files

**Source material to split:**
- `src/pflow/cli/resources/cli-agent-instructions.md` (~2,225 lines — THE main source)
- `src/pflow/cli/resources/cli-basic-usage.md` (~192 lines — short usage guide, migrates to `core.md` + `menu.md`)

**Task 151 output (must exist before Task 77 starts):**
- `src/pflow/cli/commands/guide.py` (or wherever the stub lives) — to be filled in with real composition
- `src/pflow/cli/resources/cli-agent-instructions.md` (updated in-place with new CLI command names by Task 151)
- Task 151's new CLI commands (`pflow list`, `pflow find`, `pflow describe`, `pflow probe`, `pflow mcp list`, `pflow mcp find`, etc.)

**Related tasks:**
- `.taskmaster/tasks/task_151/task-151.md` (CLI restructure, prerequisite)
- `.taskmaster/tasks/task_152/task-152.md` (MCP parity, follow-up)

**Architecture references:**
- `src/pflow/cli/CLAUDE.md` — CLI architecture (updated by Task 151)
- `src/pflow/nodes/CLAUDE.md` — node implementation patterns (helpful for content accuracy)

---

**Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
