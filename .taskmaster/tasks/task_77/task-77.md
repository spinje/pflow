# Task 77: Pflow Guide — Tailored Agent Instructions

## Description

Replace the monolithic `cli-agent-instructions.md` (~2,225 lines) with `pflow guide`, a tailored learning command. Split the content into topic-scoped markdown chunks (core framework + per-node + per-feature) and compose them at runtime based on what the agent asked for. Agents get only the content relevant to their current task, not a 2,400-line manual upfront.

This is the **content delivery** task. The CLI surface (Task 151) provides the `pflow guide [topics...]` command as a stub; this task fills in the content and composition logic.

**Scope is CLI only.** MCP server guide content is handled by the MCP parity follow-up (Task 152).

## Status

done

## Completed

2026-04-14

## Priority

high

## Problem

Today's agent onboarding requires reading `pflow instructions usage` (192 lines) and `pflow instructions create --part 1/2/3` (2,225 lines) before an agent can build a workflow. This is the opposite of progressive disclosure:

1. **Massive upfront context cost.** An agent spends ~2,400 lines of context window on documentation before writing a single line of workflow markdown. Most of that content is irrelevant to any given task — an agent building an HTTP+LLM workflow doesn't need MCP discovery patterns or nested workflow composition.

2. **Textbook, not tutor.** The current format assumes agents want to read a manual cover-to-cover. LLMs work much better with targeted, example-driven guidance at the moment of need.

3. **No filter for intent.** An agent must load all 2,225 lines regardless of whether they're building a simple 2-node pipeline or a complex branching workflow with batch processing.

4. **Content is organized by concern, not topic.** The current file is structured as "Philosophy → Mental Model → Steps 1-10 → Patterns." This makes it hard to extract "just the code node bits" or "just the batch processing bits." The content needs to be re-structured around topics an agent can select from.

5. **Parallel-file drift with MCP.** There are two instruction file sets today (CLI vs MCP), and they already drift. Restructuring is a chance to fix the architecture so content is single-sourced.

The design direction was settled in a multi-turn discussion on 2026-04-10/11. Key decision: `pflow guide [topics...]` with positional args, composing static markdown chunks from a new `cli/resources/guide/` directory.

## Solution

Three-phase implementation. The content work is the hard part; the code is trivial.

### Entry content shared between `pflow --help` and `pflow guide` (no args)

The capability map lives in **one file**: `cli/resources/guide/entry.md`. Both `pflow --help` and `pflow guide` (no args) render the same content from this file. Single source of truth, no drift.

- **`pflow --help`** — the canonical entry point. Shows commands, a brief "what pflow is" header, and the topic/capability list. This is where an agent first learns "pflow can do batch processing / branching / nested workflows."
- **`pflow guide`** (no args) — a fallback for agents that forgot to pass a topic. Identical content to `pflow --help`.

The entry content is specifically designed as a **capability map** that sticks in long-term context. Topic descriptions include **vocabulary triggers** — the user-facing words that should map to each topic — so agents can pattern-match future scope changes without re-reading everything.

### `pflow guide` invocation modes

`pflow guide` accepts two kinds of positional args:

1. **Topic names** — `http`, `llm`, `batch`, `core`, etc. Each loads its chunk from `cli/resources/guide/`.
2. **Workflow references** — file paths (`./my-workflow.pflow.md`) or saved workflow names (`github-pr-analyzer`). For each workflow ref, pflow parses the workflow and auto-detects which topics to load based on its actual contents.

Topics and workflow refs can mix in the same invocation:

```
pflow guide                                        # fallback: same as `pflow --help`
pflow guide core                                   # framework fundamentals (explicit)
pflow guide http llm                               # topic-only, NO core auto-included
pflow guide core http llm                          # core + topics (explicit opt-in)
pflow guide ./my-workflow.pflow.md                 # auto-detect from file
pflow guide github-pr-analyzer                     # auto-detect from saved workflow
pflow guide ./my-workflow.pflow.md mcp-testing     # auto-detect + add extra topic
pflow guide http ./other.pflow.md batch            # topic + workflow + topic (deduplicated)
```

**`core` is an explicit topic, not auto-included.** This prevents re-loading framework fundamentals on every subsequent `pflow guide` call in a long agent session. An agent loads `core` once (typically at the start), then loads additional topics later when scope expands without duplicating the framework content.

This workflow-scoped mode is the killer use case for existing workflows: an agent handed a broken workflow runs `pflow guide ./the-file.pflow.md` and gets exactly the content needed to understand and fix it — no manual analysis of which nodes/features the workflow uses, and no re-loading of framework content already in context.

### Phase 0 — Content audit and split (the critical work)

Walk the current `cli-agent-instructions.md` (2,225 lines) paragraph by paragraph. Tag each section with its target chunk:

- **`entry.md`** — the shared content for `pflow --help` and `pflow guide` (no args). Canonical entry point. Short: ~50–60 lines. Brief description of pflow, command list, topic list with vocabulary triggers.
- **`core.md`** — an explicit topic (not auto-included). Contains framework fundamentals: mental model (step order vs templates), input declaration rules, template reference, save workflow step, common mistakes, workflow structure skeleton. Agent loads this once explicitly via `pflow guide core`.
- **`nodes/<type>.md`** — per-node chunks. Each includes the node's interface (parameters, types, defaults), workflow syntax with concrete example, patterns, and gotchas. Each chunk ends with a breadcrumb: "New to pflow? Run `pflow guide core` for the framework fundamentals."
- **`features/<feature>.md`** — per-feature chunks. Batch, branching, nested workflows, structured LLM output. Same breadcrumb at the end.
- **`cross/<topic>.md`** — cross-cutting concerns that are optional. MCP testing protocol, phase-based building, external API integration pattern, debugging template errors.

The target directory layout:

```
src/pflow/cli/resources/guide/
├── entry.md                   # shared by `pflow --help` and `pflow guide` (no args)
├── core.md                    # explicit topic: framework fundamentals
├── nodes/
│   ├── http.md
│   ├── llm.md
│   ├── code.md
│   ├── shell.md
│   ├── file.md
│   ├── mcp.md
│   └── workflow.md            # nested workflow calls
├── features/
│   ├── batch.md
│   ├── branching.md
│   ├── nested.md
│   └── structured.md          # structured LLM output
└── cross/
    ├── mcp-testing.md
    ├── phased-building.md
    ├── debugging.md
    └── external-api.md
```

**Phase 0 deliverable:** all `.md` files written, with content traced back to the source paragraphs in the original `cli-agent-instructions.md`. Nothing lost, nothing duplicated.

### Phase 1 — Draft expected outputs (Show Before You Code gate)

Before writing any code, produce the expected output of:

- **`entry.md` content** — what `pflow --help` and `pflow guide` (no args) display. This is THE most important draft because it's the capability map agents internalize. It must include vocabulary triggers for every topic.
- `pflow guide core` — framework fundamentals chunk on its own
- `pflow guide http` — just the http chunk (no core)
- `pflow guide core http llm batch` — core + http + llm + batch chunks combined
- `pflow guide mcp` — mcp chunk (which includes pointers to `pflow mcp list/find`)
- `pflow guide code batch branching` — code + batch + branching chunks (no core)
- `pflow guide ./example-workflow.pflow.md` — auto-detected topics for a sample workflow (use an existing example from `examples/` or construct one that exercises http + llm + batch)
- `pflow guide ./mixed.pflow.md mcp-testing` — auto-detected topics plus an explicitly-added cross-cutting topic, demonstrating the merge

Read each composed output end-to-end. Verify:
- Nothing is redundant across chunks
- Composition order is sensible
- Size is within budget (~50–400 lines depending on mode)
- Reading it as an agent, you'd have everything you need to build a workflow using the selected topics
- For workflow-scoped mode: the auto-detected topic set matches what the workflow actually uses

**Special acceptance criterion for `entry.md`:** "Would an agent reading this once remember, months later, that pflow supports batch processing when a user asks to 'run these in parallel'?" The vocabulary triggers must pattern-match realistic user phrasings.

**Phase 1 deliverable:** the draft outputs approved by the user before code starts.

### Phase 2 — Implementation

Once content and composition are validated, the code is ~50–100 lines.

**Shared entry content loader** (used by both `pflow --help` and `pflow guide` no-args):

```python
def render_entry_content() -> str:
    """Canonical entry content. Shared by `pflow --help` and `pflow guide` (no args)."""
    return (GUIDE_DIR / "entry.md").read_text()
```

Task 151 wires this into the root Click command's help so that `pflow --help` displays `entry.md` content. Task 77 fills in the actual `entry.md` file content.

**Main guide loader:**

```python
def guide(args: list[str]) -> str:
    if not args:
        return render_entry_content()  # fallback: identical to `pflow --help`

    topics: list[str] = []
    seen: set[str] = set()

    for arg in args:
        if is_workflow_ref(arg):
            # Parse workflow and extract topics from its IR
            ir = resolve_and_parse_workflow(arg)
            detected = detect_topics_from_ir(ir)
        else:
            detected = [arg]  # literal topic name

        for t in detected:
            if t not in seen:
                topics.append(t)
                seen.add(t)

    parts = []
    for topic in topics:
        path = resolve_topic(topic)
        if path is None:
            raise UnknownTopicError(topic)
        parts.append(path.read_text())
    return "\n\n---\n\n".join(parts)
```

Key change from earlier drafts: **no auto-inclusion of `core.md`**. Agent must pass `core` as an explicit topic if they want it. Topic-only invocations return only the requested topic chunks.

The `resolve_topic` function checks `core.md` (as a top-level file), then `nodes/<topic>.md`, then `features/<topic>.md`, then `cross/<topic>.md`. Unknown topics produce a helpful error: "Unknown topic 'foo'. Available topics: core, http, llm, code, shell, file, mcp, workflow, batch, branching, nested, structured, mcp-testing, phased-building, debugging, external-api. Run `pflow guide` for the full menu."

The `is_workflow_ref` check uses the same heuristic as CLI routing: contains `/`, ends in `.pflow.md`, or resolves to a saved workflow name in `~/.pflow/workflows/`. Topic names take precedence when ambiguous — see "Disambiguation" in Design Decisions.

The `detect_topics_from_ir` function walks the parsed workflow and returns a list of topics based on:

```python
def detect_topics_from_ir(ir: dict) -> list[str]:
    topics: set[str] = set()
    for step in ir.get("steps", []):
        node_type = step.get("type")
        if node_type:
            topics.add(node_type)  # always add node type
        if "batch" in step:
            topics.add("batch")
        if "on-error" in step or "next" in step:
            topics.add("branching")
        if node_type == "workflow":
            topics.add("nested")
        if node_type == "llm" and "output_schema" in step:
            topics.add("structured")
    return sorted(topics)
```

Note: `detect_topics_from_ir` does NOT add `core` to the detected set. If an agent wants core alongside workflow-detected topics, they pass it explicitly: `pflow guide core ./workflow.pflow.md`.

Deduplication happens at the topic level — if the same topic is requested twice (e.g., from an explicit arg and from auto-detection), it's included once.

Replace Task 151's stub implementation in `pflow guide` with the real content loader.

## Design Decisions

### Topic-scoped chunks, not concern-scoped

The current file is organized by concern (philosophy → mental model → steps → patterns). The new structure is organized by topic (http, llm, batch, branching). This matches how agents think when building: "I need to use http and llm nodes with batch processing — give me the content for those three topics."

### What goes in `entry.md` vs `core.md` vs per-topic

**`entry.md` — the capability map (loaded first, sticks in context):**
- 1-2 sentences of what pflow IS
- Agent first-command decision tree ("got a workflow? run `pflow <name>`...")
- Commands list (grouped by concern — running, managing, building, MCP, config)
- Topic list with **vocabulary triggers** for every feature topic
- Pointer to `pflow guide core` for framework fundamentals
- Pointer to `pflow guide ./workflow.pflow.md` for workflow-scoped mode
- Target size: ~50–80 lines

**`core.md` — framework fundamentals (explicit topic, loaded once per session):**
- Philosophy: why step order vs templates matter, why code/shell over LLM for structured data, why general over specific
- Mental model: step order vs templates (with concrete example)
- Input declaration decision tree
- Template variable reference (syntax + resolution order + auto-parsing)
- Save workflow step (including reserved names, when to save, how)
- Workflow structure skeleton (## Inputs / ## Steps / ## Outputs)
- Cross-cutting common mistakes (skipping discovery, hardcoded credentials, wrong tool for task)

**Always in per-node chunks:**
- Interface (parameters, types, defaults)
- Workflow syntax block with a complete minimal example
- Node-specific gotchas (code: templates in inputs, not code block; shell: $VAR vs ${VAR})
- Node-specific patterns (llm: output_schema, code: dict result for multi-field output)
- **Breadcrumb at the end:** "New to pflow? Run `pflow guide core` for the framework fundamentals."

**Always in per-feature chunks:**
- Feature syntax with example
- When to use vs alternatives
- Cross-node applicability notes (e.g., batch works on any node)
- **Breadcrumb at the end:** same as nodes

Rule of thumb: if the knowledge is "pflow can do X" → `entry.md`. If it's "how the framework works in general" → `core.md`. If it depends on WHICH node/feature you're using → topic chunk.

### Vocabulary triggers in entry.md (critical design decision)

The topic list in `entry.md` is not just a list of topic names. Each topic includes **trigger phrases** — the user-facing vocabulary that should pattern-match to that topic. These hooks are what lets an agent, months into a conversation, remember "the user said 'in parallel' → pflow has a topic for that" and run `pflow guide batch`.

Example (illustrative, final content drafted in Phase 1):

```
Topics (for `pflow guide <topic>`):

  Nodes:
    http        HTTP requests to REST APIs
    llm         LLM inference with structured output
    code        Python for data transformation
    shell       Shell commands and CLI tools
    file        File read/write
    mcp         MCP service integrations (Slack, GitHub, Postgres, ...)
    workflow    Nested sub-workflow calls

  Features (when the user says X, load topic Y):
    batch       Same operation on N items, parallel/concurrent
                Triggers: "each", "for every", "in parallel", "N at a time"
    branching   Conditional paths, error handling, data-driven routing
                Triggers: "if X then Y", "handle failures", "retry on error"
    nested      Reusable sub-workflows
                Triggers: "reuse this", "same validation as X"
    structured  Structured LLM output via output_schema
                Triggers: "return JSON", "get structured data from LLM"

  Core / Cross-cutting:
    core             Framework fundamentals (step order, templates, inputs)
    mcp-testing      When to test MCP nodes vs skip
    debugging        Template errors and trace reports
    phased-building  Building complex workflows incrementally
    external-api     Integrating REST APIs without dedicated nodes
```

The Phase 1 draft of `entry.md` must include trigger phrases for every feature topic. Node topics don't need triggers (the node type name is the trigger — "HTTP" → `http`). Cross-cutting topics may or may not need them depending on the topic.

### Composition rules

When combining requested topics:
1. **No auto-prefix.** `core.md` is NOT automatically included. If the agent wants core, they pass it explicitly.
2. Append each requested topic in the order the agent listed them (or in sorted order when auto-detected from a workflow)
3. Separate chunks with `---` (visual separation)
4. Do not deduplicate within chunks — each chunk should be self-contained (duplication between `core.md` and a topic chunk is forbidden; duplication between two topic chunks is allowed if rare)
5. **Topic-level deduplication happens**: if the same topic is requested from multiple sources (explicit arg + auto-detected from a workflow), it appears only once in the output

Why no auto-include of core: prevents re-loading fundamentals on every invocation in a long agent session. Agent loads `core` once explicitly, then loads topic chunks on subsequent calls without duplication.

Why no deduplication within chunks: it adds code complexity and makes chunks no longer readable standalone. Better to keep chunks disjoint at the source level.

### Workflow-scoped auto-detection

When a positional arg is a workflow reference (file path or saved workflow name), pflow parses the workflow IR and extracts topics based on its actual contents:

- **Every unique `type:` in steps** → corresponding `nodes/<type>.md` chunk
- **Any node with `batch:` field** → `features/batch.md`
- **Any node with `on-error:` or `next:` fields** → `features/branching.md`
- **Any `type: workflow` step** → `features/nested.md`
- **Any `type: llm` step with `output_schema` field** → `features/structured.md`

The detection walks the top-level workflow only. It does NOT recurse into nested sub-workflows (that would require resolving every `type: workflow` node's target, adding complexity for marginal value). If an agent needs guide content for a nested workflow, they can pass that workflow's file path explicitly.

**Error handling for workflow refs:**

- **File doesn't exist** — error with a pointer to `pflow list` to see saved workflows and `pflow guide` for the topic menu
- **Workflow fails to parse** — error including the parse error, plus a fallback suggestion: "run `pflow guide <topics>` with explicit topics instead"
- **Workflow parses but has no recognizable nodes** (edge case: empty `## Steps` section) — warn and return just `core.md`

### Disambiguation: topic vs workflow vs file

When an agent runs `pflow guide foo`, is `foo` a topic name or a workflow?

**Resolution order** (highest priority wins):

1. If `foo` contains `/` or ends in `.pflow.md` → treat as file path
2. If `foo` matches a known topic name (checked against the list of chunks in `guide/`) → treat as topic
3. If `foo` matches a saved workflow name in `~/.pflow/workflows/` → treat as saved workflow
4. Otherwise → unknown topic error (with suggestion list)

**Why topics beat workflows:** topic names are a small, finite set controlled by this task (http, llm, code, shell, file, mcp, workflow, batch, branching, nested, structured, plus cross-cutting ones). Workflow names are user-created and could collide. Topic names winning is the expected default for ambiguous cases.

**Better fix: reserved names**. Task 151 already has a reserved-names list that prevents workflow save for names like `list`, `find`, `describe`, `history`, `save`, `guide`, `probe`. Extend this list to include ALL topic names so the ambiguity can never happen. A user trying to save a workflow named `llm` would get: "Cannot save workflow named 'llm': this name is reserved (it's a guide topic). Pick a different name like 'llm-summarizer'."

This extension is a requirement of Task 77, but the reserved-names mechanism itself is a Task 151 artifact — this task just adds entries to the existing list.

### Size budget

- `core.md` target: ~100–150 lines
- Each `nodes/*.md`: ~50–100 lines
- Each `features/*.md`: ~30–60 lines
- Each `cross/*.md`: ~40–80 lines
- Typical invocation (`guide http llm batch`): ~300–400 lines total
- Maximum invocation (`guide http llm code shell file mcp batch branching nested structured`): ~1,200 lines — still roughly half the current monolithic file

If any chunk exceeds these budgets during Phase 0, that's a signal to split it further.

### Menu format

`pflow guide` (no args) returns `menu.md`, which contains:

- 1-sentence explanation of what `guide` is for
- Lists of available topics grouped as: Nodes, Features, Cross-cutting
- Each topic on one line with a brief description
- Example invocations for common combinations
- A pointer to `pflow mcp list/find` for discovering specific MCP tools

Draft of menu.md structure (actual content written in Phase 0/1):

```markdown
# pflow guide

Get tailored workflow-building content. Pass one or more topics to see
just what you need, or run with no args for this menu.

## Nodes
- http       HTTP requests to REST APIs
- llm        LLM inference with structured output support
- code       Python code node for data transformation
- shell      Shell commands and CLI tools
- file       File read/write
- mcp        MCP service integrations
- workflow   Nested workflow calls

## Features
- batch       Same operation × N items (parallel)
- branching   Conditional paths via on-error or code next
- nested      Sub-workflow composition
- structured  Structured LLM output via output_schema

## Cross-cutting
- debugging        Template error recovery and trace reports
- phased-building  Building complex workflows incrementally
- external-api     Integrating REST APIs without dedicated nodes
- mcp-testing      When to test MCP nodes vs skip

## Examples

    pflow guide http llm              # core + http + llm
    pflow guide code batch            # core + code + batch processing
    pflow guide mcp                   # core + mcp patterns

To find specific MCP tools: `pflow mcp list [keyword]` or `pflow mcp find "description"`
```

### Node chunks supersede `registry describe` for core nodes

Task 151 decided that `pflow guide <node>` is the one-stop-shop for node information — interface + syntax + patterns + gotchas. This means `registry describe` is no longer needed for core nodes (Task 151 already removes it). Per-node guide chunks must include the full interface (not just patterns), so an agent that runs `pflow guide http` gets everything.

This also means the node chunks need to stay in sync with node implementations. For now, this is manual — whenever a node's interface changes, update the chunk. A future task could auto-generate the interface portion from node docstrings.

### Cross-cutting topic selection

The four cross-cutting topics (`debugging`, `phased-building`, `external-api`, `mcp-testing`) are optional and only loaded when the agent explicitly asks. They contain content from the current file that doesn't fit cleanly into node or feature chunks but is valuable guidance for specific situations.

Agents rarely need these upfront — they load them when they hit the relevant situation ("I need to integrate a new API" → `pflow guide external-api`).

### Backward compatibility with existing MCP resource

The `pflow://instructions` MCP resource currently serves `cli-agent-instructions.md`. Task 151 leaves this alone (the resource uses `mcp_server/resources/instructions/*.md`, not the CLI file). This task deletes `cli-agent-instructions.md` from CLI resources only after verifying nothing in the CLI path still references it.

The old `cli-basic-usage.md` file is also deleted — its content migrates to `core.md` + `menu.md`.

## Dependencies

- **Task 151** — CLI Surface Restructure. Must complete first. Task 151 provides the `pflow guide` command routing and stub implementation; this task fills in the content and real composition logic.

## Requirements

### Phase 0 — Content split

- Every paragraph of current `cli-agent-instructions.md` is tagged to a target chunk (or marked for deletion if it's now redundant — e.g., content that references CLI commands already covered by `--help`)
- All chunk files exist under `src/pflow/cli/resources/guide/`
- Each `nodes/<type>.md` contains: interface (parameters, types, defaults, description), workflow syntax example, patterns, gotchas
- Each `nodes/<type>.md` ends with the breadcrumb: "New to pflow? Run `pflow guide core` for the framework fundamentals."
- Each `features/<feature>.md` contains: syntax, example, when to use
- Each `features/<feature>.md` ends with the same breadcrumb
- `core.md` contains: philosophy, mental model, input declaration, template reference, save step, common mistakes
- `entry.md` contains: pflow description, command list, topic list with vocabulary triggers, pointers to `pflow guide core` and `pflow guide <workflow>`
- `entry.md` target size: 50–80 lines (it's rendered as `pflow --help` so must stay scannable)
- No content duplication between `core.md` and any topic chunk (duplication across topic chunks is acceptable if rare)
- Every chunk reads standalone — an agent reading just `nodes/llm.md` has enough context to use the LLM node (with the breadcrumb pointing to `core` if framework fundamentals are needed)

### Phase 1 — Draft outputs

- Draft composed output of `pflow guide` (menu), `pflow guide http`, `pflow guide http llm batch`, `pflow guide mcp`, `pflow guide code batch branching` are produced
- Drafts are reviewed with the user and approved BEFORE code is written (Show Before You Code)
- Approved drafts serve as acceptance targets — the implemented command must produce the same output for the same inputs

### Phase 2 — Implementation

- `pflow guide` (no args) returns `entry.md` content (identical to `pflow --help` output)
- `render_entry_content()` shared function used by both `pflow --help` (via Task 151's wiring) and `pflow guide` (no args)
- `pflow guide <topic...>` returns the requested topic chunks joined with `---` separators; **no auto-inclusion of core**
- `pflow guide core` returns the `core.md` chunk alone (framework fundamentals as an explicit topic)
- `pflow guide core http llm` returns core + http + llm chunks
- `pflow guide <workflow-ref>` parses the workflow and auto-loads all topics it uses (core NOT auto-added)
- `pflow guide core <workflow-ref>` explicitly adds core alongside auto-detected topics
- `pflow guide <workflow-ref> <extra-topic...>` combines auto-detection with explicit topics (deduplicated)
- `pflow guide <topic> <workflow-ref> <topic>` — any mix of topics and workflow refs in any order works
- Positional arg disambiguation: file path (has `/` or ends `.pflow.md`) → topic name (in known topic list including `core`) → saved workflow name → unknown topic error
- Topic resolution order: top-level `core.md` → `nodes/<topic>.md` → `features/<topic>.md` → `cross/<topic>.md`
- Topic-level deduplication: if the same topic is requested from multiple sources, it appears once in output
- Unknown topic produces a helpful error listing all available topics (including `core`) and pointing to `pflow guide` for the full entry content
- Workflow file doesn't exist: clear error with pointer to `pflow list`
- Workflow fails to parse: error with parse details and fallback suggestion to use explicit topics
- Topic order in output: explicit topics in the order given; auto-detected topics from a workflow ref come sorted alphabetically in the position of that ref
- `guide` command implementation replaces Task 151's stub
- `render_entry_content()` function is importable by Task 151's CLI help wiring
- Reserved names list (from Task 151) extended to include all topic names (including `core`) so workflows can't be saved with names that collide with topics
- Code size: aim for ~50–100 lines; if it grows beyond ~150 lines, something is wrong

### Deletions

- `src/pflow/cli/resources/cli-agent-instructions.md` — deleted (content migrated to chunks)
- `src/pflow/cli/resources/cli-basic-usage.md` — deleted (content migrated to `entry.md` + `core.md`)
- Any references to these files in CLI code — removed

### Tests

**Entry/fallback tests:**
- Unit test: `guide()` with no args returns `entry.md` content
- Unit test: `render_entry_content()` returns non-empty content matching `entry.md`
- Unit test: `render_entry_content()` output is stable (same input → same output)
- Integration test: `pflow --help` output contains the `entry.md` content (Task 151 wires this; Task 77 provides content)

**Topic-mode tests:**
- Unit test: `guide(["core"])` returns just `core.md` content (no prefix or suffix)
- Unit test: `guide(["http"])` returns just http chunk (no core, no preamble)
- Unit test: `guide(["core", "http", "llm"])` returns core + http + llm in that order
- Unit test: `guide(["http", "llm", "batch"])` returns http + llm + batch (no core)
- Unit test: `guide(["unknown-topic"])` raises `UnknownTopicError` with helpful message listing available topics (including `core`)
- Unit test: topic resolution finds `core.md` (top-level), `nodes/`, `features/`, and `cross/` chunks correctly
- Unit test: topic order in input is preserved in output

**Workflow-ref mode tests:**
- Unit test: `detect_topics_from_ir` correctly identifies node types for each supported node
- Unit test: `detect_topics_from_ir` adds `batch` when any step has `batch:` field
- Unit test: `detect_topics_from_ir` adds `branching` when any step has `on-error:` or `next:`
- Unit test: `detect_topics_from_ir` adds `nested` when any step has `type: workflow`
- Unit test: `detect_topics_from_ir` adds `structured` when any llm step has `output_schema`
- Unit test: `guide(["./fixture.pflow.md"])` returns core + auto-detected topics only
- Unit test: `guide(["./fixture.pflow.md", "mcp-testing"])` merges auto-detected and explicit topics, deduplicated
- Unit test: `guide(["saved-name"])` resolves via WorkflowManager, auto-detects topics
- Unit test: `guide(["./nonexistent.pflow.md"])` raises a clear error pointing to `pflow list`
- Unit test: `guide(["./invalid.pflow.md"])` raises a parse error with fallback suggestion
- Unit test: topic name wins over saved workflow name in disambiguation (if both exist somehow)
- Unit test: file paths are detected by `/` or `.pflow.md` suffix

**Integration tests:**
- CLI end-to-end: `pflow guide http` output contains expected markers from `core.md` and `nodes/http.md`
- CLI end-to-end: `pflow guide ./examples/fetch-api.pflow.md` (or an equivalent fixture) returns content for all nodes that workflow uses
- CLI end-to-end: `pflow guide <saved-workflow-name>` resolves and auto-detects correctly
- CLI end-to-end: `pflow guide` with no args prints the menu

**Content tests:**
- All chunk files exist, are non-empty, and are valid markdown
- Combined `core.md + all chunks` does not exceed ~1,500 lines total (guardrail against bloat)

**Reserved names test:**
- `WorkflowManager.save()` refuses to save a workflow with any topic name (e.g., `llm`, `http`, `batch`, `branching`)
- Error message explains the collision and suggests an alternative name

### Documentation

- `src/pflow/cli/resources/CLAUDE.md` (new, or existing) — documents the guide content layout, composition rules, and how to add a new topic
- `src/pflow/cli/commands/guide.py` (or wherever the implementation lives) — has clear docstring explaining Phase 2 logic
- `docs/reference/cli/guide.mdx` — user-facing guide command reference (Task 151 creates the file; this task fills in the real content based on the final shape)

## Implementation Notes

### Content migration strategy

Reading and tagging 2,225 lines is tedious but mechanical. Suggested approach:

1. Print the file and go through it section by section
2. For each paragraph, decide: core, node-specific (which?), feature-specific (which?), cross-cutting (which?), or delete (redundant with --help or other commands)
3. Build a spreadsheet or simple text log of line-range → target-chunk mapping
4. Once mapping is complete, create the chunk files and copy content
5. Review each chunk for standalone readability
6. Delete the mapping log — the chunks are the result

**Do not try to do this step as code.** It's a content design task, not an implementation task. A human (or agent) reading and judging each section is the right approach.

### Handling content that doesn't fit cleanly

Some content will resist easy categorization. Examples:

- **"Workflow smells" table** — applies cross-node. Could go in `core.md` (always shown) or `cross/debugging.md` (loaded on request). Decide during Phase 0.
- **"Real Request Parsing" clarification template** — cross-cutting advice about handling ambiguity. Probably `core.md`.
- **"MCP Output Has NO Standard Structure"** — belongs in `nodes/mcp.md` or `cross/mcp-testing.md`. Probably both have pointers to each other.

When in doubt, err on the side of fewer places. If a chunk would only be 20 lines, see if it can merge with an adjacent one.

### Chunks are markdown, not code-generated

Keep chunks as plain `.md` files in the repository. Don't introduce template syntax, string interpolation, or dynamic generation. The content should be editable by opening the file and making changes. Simplicity matters more than cleverness.

### When to update content

As pflow evolves (new node types, changed syntax, new features), chunks need updates:

- New node type → add `nodes/<new-type>.md`, update `menu.md` topic list
- New feature → add `features/<new-feature>.md`, update `menu.md`
- Breaking change to a node's interface → update that node's chunk
- New common mistake observed → add to `core.md`

Maintaining chunks is easier than maintaining the monolithic file because edits are scoped. But the chunks can still drift from node implementations — manual review remains the safety net.

### Composition separator

Using `---` (horizontal rule in markdown) as the chunk separator has two benefits:
- Visual separation when rendered (Mintlify or terminal markdown renderers)
- Makes it clear where one chunk ends and another begins
- Trivial to implement (`"\n\n---\n\n".join(parts)`)

Alternative: inject `## <Topic Name>` headings. Decide during Phase 1 based on how the drafts look.

### Order of topic resolution matters

If a topic name exists in both `nodes/` and `features/`, the resolver picks the first match. This matters if there's a name collision — e.g., a `workflow` topic in both (nested workflow node in `nodes/workflow.md` vs workflow-level concept in `features/workflow.md`). Phase 0 should ensure no such collisions exist. If they do, one directory wins and the other topic gets a different name.

### Guide isn't dynamic (content-wise)

The content chunks are 100% static markdown. No interpolation of "you have X MCP servers configured" or "your last workflow had Y errors."

However, the **topic SELECTION** is dynamic when a workflow ref is passed — the set of chunks loaded depends on what the workflow actually contains. This is not "dynamic content" in the templating sense; it's filtered composition. Keep this distinction clear: chunks themselves stay static.

If true dynamic content (e.g., "you have 5 MCP servers, here's which ones") proves valuable later, add it as an enhancement — don't build it now.

### Why auto-detection doesn't recurse into nested workflows

A `type: workflow` step references another workflow by path or saved name. To recursively auto-detect topics, pflow would need to resolve and parse every nested workflow, which:
- Adds complexity (error handling for missing files, infinite recursion guard, etc.)
- Multiplies content (a workflow calling 3 sub-workflows could pull in dozens of chunks)
- Dilutes the "focused on this file" value of the feature

Instead: workflow-scoped guide only detects topics from the TOP-LEVEL workflow. If the workflow calls a sub-workflow, the parent gets `features/nested.md` (because it uses the nested pattern) but not the sub-workflow's node types. An agent wanting guide content for the sub-workflow runs `pflow guide ./sub-workflow.pflow.md` explicitly.

This is the right tradeoff: simpler implementation, more predictable output, and agents can always drill in with additional invocations.

### What's NOT in scope

- **Parser/transformer for MCP output** → Task 152 (MCP parity)
- **MCP-side guide content files** → Task 152
- **Auto-generation of node interface from docstrings** → future task
- **Dynamic content (e.g., "you have X servers configured")** → not now, maybe never
- **Search within guide content** → not now
- **Interactive tutorials** → out of scope
- **Migrations of content to docs/** → `docs/` is user-facing via Mintlify, guide content is agent-facing via CLI. Keep them separate.

## Verification

### Phase 0 verification
- Every section of current `cli-agent-instructions.md` has been accounted for (tagged to a chunk or explicitly deleted with reason)
- All chunk files exist, are non-empty, and are valid markdown
- A reviewer can open any chunk and understand it standalone without reading other chunks
- No chunk exceeds its size budget

### Phase 1 verification
- Draft outputs for `pflow guide`, `pflow guide http`, `pflow guide http llm batch`, `pflow guide mcp`, `pflow guide code batch branching` are produced as static text
- Drafts are approved by the user
- Drafts are sensible end-to-end: no redundancy across chunks, sensible composition order, within size budget

### Phase 2 verification
- All unit tests pass
- Integration test passes
- `make test` passes
- `make check` passes
- Running `pflow guide` produces output matching the approved menu draft
- Running `pflow guide http llm batch` produces output matching the approved draft
- `pflow guide unknown-topic` produces a helpful error

### Regression
- Task 151 CLI commands still work (unchanged by this task)
- No MCP server behavior changes (MCP guide content is Task 152)

### Agent UX verification (the real test)
- **The "build a workflow from nothing" test:** Start with a blank agent context, no prior pflow knowledge. Run `pflow guide`, pick relevant topics, run `pflow guide <those topics>`, then try to build a simple workflow (e.g., "fetch from an API, transform, save to file"). Does it work? Is anything missing?
- **The "modify an existing workflow" test:** Take a non-trivial saved workflow. Pretend it's broken. Run `pflow guide ./that-workflow.pflow.md`. Does the composed output contain everything you'd need to understand and fix the workflow, without loading irrelevant topics?
- **The "specific gotcha lookup" test:** An agent hits a specific error like "templates in code block cause parse errors." Running `pflow guide code` should produce content that addresses this. Verify the gotcha is in the chunk.
- **The "size is right" test:** Measure the token count of `pflow guide http llm batch`. Should be meaningfully smaller than the current 2,225 line dump — target ~30% of the original.
- **The "workflow-scoped is scoped" test:** Build a simple 2-node http+code workflow. `pflow guide ./it.pflow.md` should load only core + http + code (not llm, not batch, not branching). Verify output doesn't contain unrelated content.

### Acceptance
- Chunks under `cli/resources/guide/` are complete, non-empty, and pass content tests
- `pflow guide` and `pflow guide <topics>` produce outputs matching approved drafts
- `cli-agent-instructions.md` and `cli-basic-usage.md` are deleted from CLI resources
- All tests pass
- The content in current instructions file is either:
  - Migrated to a chunk (most content)
  - Explicitly deleted with a reason (content made redundant by Task 151's cleaner help text)

## References

### Files to create

- `src/pflow/cli/resources/guide/entry.md` — shared by `pflow --help` and `pflow guide` (no args)
- `src/pflow/cli/resources/guide/core.md` — explicit topic: framework fundamentals
- `src/pflow/cli/resources/guide/nodes/*.md` (7 files)
- `src/pflow/cli/resources/guide/features/*.md` (4 files)
- `src/pflow/cli/resources/guide/cross/*.md` (4 files)
- `src/pflow/cli/resources/CLAUDE.md` — documents the guide content layout

### Files to modify

- `src/pflow/cli/commands/guide.py` (or wherever Task 151 stubs it) — real implementation replaces stub
- Any `docs/reference/cli/guide.mdx` created by Task 151 — updated with real command shape

### Files to delete

- `src/pflow/cli/resources/cli-agent-instructions.md` — content migrated to chunks
- `src/pflow/cli/resources/cli-basic-usage.md` — content migrated to `core.md` + `menu.md`

### Related tasks

- **Task 151: CLI Surface Restructure** — prerequisite. Provides `pflow guide` command routing and stub.
- **Task 152: MCP Server Parity** — follow-up. Decides whether MCP-side guide content is a parallel file set or auto-transformed from these CLI chunks.

### Prior art / context

- Design discussion: multi-turn conversation on 2026-04-10 / 2026-04-11 — consensus that content delivery should be topic-filtered, not monolithic
- Source content: `src/pflow/cli/resources/cli-agent-instructions.md` (~2,225 lines) is the material to restructure
- Original Task 77 description ("Distribute Agent Instructions to Nodes") aimed at a similar goal with a different architecture (guidance attached to nodes). The new approach centralizes in a `guide/` directory with topic-based selection instead, which is simpler to implement and maintain
