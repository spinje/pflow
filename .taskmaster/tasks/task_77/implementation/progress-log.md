# Task 77: Progress Log

**Task**: Replace the monolithic `cli-agent-instructions.md` (2,225 lines) with `pflow guide`, a topic-scoped content delivery system. Static markdown chunks composed at runtime based on what the agent asked for.

**Key files to read first**:
- `.taskmaster/tasks/task_77/task-77.md` — full spec
- `.taskmaster/tasks/task_77/starting-context/braindump-2026-04-11-cli-restructure-context.md` — tacit knowledge from the design discussion
- `.taskmaster/tasks/task_77/research/pedagogical-framing-ideas.md` — three framing ideas for core.md
- `.taskmaster/tasks/task_77/implementation/implementation-plan.md` — Phase 0 plan (OUTDATED — see deviations below)

**Three phases**: Phase 0 (move content to chunks) → Phase 1 (condense, compose entry.md, draft outputs for approval) → Phase 2 (implement guide composition code + tests)

**Current status**: Phase 2 complete. All three phases done. Guide composition implemented, tests passing, old files deleted.

## Phase 0 — Content Move + Structural Refinements (2026-04-12)

### Context Gathering

Read all source material:
- `src/pflow/cli/resources/cli-agent-instructions.md` (2,225 lines) — read in 500-line chunks with analysis after each
- `src/pflow/cli/resources/cli-basic-usage.md` (191 lines)
- Task 77 spec, braindump, pedagogical framing ideas
- Task 151 review (prerequisite — completed, merged)

Key finding: neither source file is used by any production code. They're inert reference material. Safe to delete after Phase 2.

### Initial Content Move

Detailed implementation plan written and approved: `.taskmaster/tasks/task_77/implementation/implementation-plan.md`

Original plan had 17 chunk files. Three agreed consolidations:
1. Mandatory first step — duplicate in both source files, kept richer version
2. Match score decision trees — three copies, kept most detailed
3. Command cheat sheet — deleted (redundant with `pflow --help`)

Created all 17 chunk files with content moved as-is. Verification: 10 spot-checks passed.

### Structural Refinements (Beyond Original Plan)

Through iterative discussion with the user, we significantly reshaped the guide structure. The guiding principle that emerged: **make the CLI surface self-documenting, guide only teaches what the CLI can't.**

#### Dissolved Chunks

**`cross/mcp-testing.md` → distributed to node chunks**
- The "when to probe" decision tree covered ALL node types — not appropriate for one chunk
- Testing advice is per-node: MCP/HTTP = probe if accessing specific fields, shell = test pipelines, everything else = no probing needed
- MCP-specific content (protocol, meta-discovery, structure discovery) → `nodes/mcp.md`
- HTTP probing one-liner → `nodes/http.md`
- Shell pipeline testing + exit codes → `nodes/shell.md`
- No testing guidance in core.md — user pushed back through several rounds; only MCP/HTTP/shell need probing, and those are node-specific

**`cross/debugging.md` → dissolved entirely**
- Error messages are already agent-optimized (Tasks 143/144/148 built structured diagnostics with fix suggestions)
- Error patterns table (KeyError, 401, ConnectionRefused) is self-explanatory
- `pflow report` is the escalation path for complex debugging only
- Agents should NOT re-run to get reports — every run saves a trace, `pflow report` reads the most recent
- Content collapses to one line in core's dev loop: "Errors include fix suggestions. For complex debugging: `pflow report`"

**`cross/phased-building.md` → dissolved entirely**
- The phased building pattern was a pre-caching workaround
- Phase 1 "write-file to inspect output" → now just `--only fetch --report`
- Phases 2-4 "add nodes incrementally" → caching handles this (re-run, unchanged nodes instant)
- Only useful part was "Iteration is Free" (caching), already in core.md
- The principle "build incrementally" is a one-liner in core's dev loop

**`cross/auth.md` → dissolved into `pflow settings --help`**
- Credential setup guidance (settings set-env, llm keys set, credentials as inputs) moved to `pflow settings --help`
- The critical rule "stored credentials are NOT auto-available — declare as workflow inputs" is in the help text
- `cross/` directory eliminated entirely

#### Merged Chunks

**`nodes/workflow.md` + `features/nested.md` → `features/sub-workflows.md`**
- Both covered the same topic (calling workflows from workflows) from different angles
- Naming poll: 5/5 agents chose `sub-workflows`
- Merged into one coherent chunk with interface details + composition pattern + examples

#### Node-Specific Details Distributed to Node Chunks

The "Node Type Selection" section in core.md had detailed bullets per node type (BSD commands, type annotations, auto-auth, etc.). These moved to their respective node chunks as "Use for" sections:
- Code node details (native objects, multiple inputs, type-annotated) → `nodes/code.md`
- Shell node details (CLI tools, BSD, `$VAR` vs `${VAR}`, sed/awk warning) → `nodes/shell.md`
- LLM node details (costs per execution, output_schema) → `nodes/llm.md`
- MCP naming pattern (`mcp-{server}-{TOOL}`) → `nodes/mcp.md`
- Core keeps just a compact 7-line "Need X? Use Y" table with `pflow guide <node-type>` pointer

#### core.md Structural Edits (1,211 → 964 lines)

**REMOVED** (redundant with CLI output or other sections):
- "Mandatory first step" (→ entry.md — `find` output now self-documents match actions)
- "Step 2: DISCOVER WORKFLOWS" (→ entry.md — execution/discovery, not building)
- Intent signals table (→ entry-raw-material.md — agent behavior, not building)
- Part 4 preamble ("Before building, verify:")
- Template variable quick reference (condensed version of full ref that exists)
- Decision quick reference (condensed version of detailed sections)
- Key success factors (10-point summary of everything already stated)

**MERGED** (duplicate content combined):
- Workflow structure reference into Step 8 BUILD (was duplicated)
- Three extraction/transformation sections into one "Extraction vs Transformation" section
- Two common mistakes sections into one (removed node-specific items already in node chunks)

**SHRUNK**:
- Step 9 TEST → 3-line "RUN & ITERATE" (errors are self-describing)
- Step 10 SAVE → 3-line "SAVE (Optional)" referencing `save --help`
- Node type selection → 7 lines (details distributed to node chunks)

**ADDED**:
- "Common Workflow Shapes" — 4 patterns from pedagogical ideas (Fetch→Transform→Store, Fetch→Decide→Branch, Iterate→Collect→Aggregate, Multi-service coordination)
- "Development Loop" — caching/--only/--no-cache/cache:false/pflow report + "build incrementally"

**MOVED**:
- "Real Request Parsing" → entry-raw-material.md (agent behavior)
- Intent signals table → entry-raw-material.md (agent behavior)

### CLI Improvements

The principle: **`--help` is the authority on how commands work. Guide teaches when and why.**

| Command | What was added |
|---------|---------------|
| `pflow probe --help` | Example output (Execution ID, template paths), pre-filtered explanation, read-fields workflow, http/shell secondary examples |
| `pflow report --help` | What report contains (summary.md, per-node files), when to use it, examples. Previously `pflow trace report` — flattened to top-level command. |
| `pflow settings --help` | Credential setup guide (set-env, llm keys set), critical rule about declaring as inputs |
| `pflow mcp describe --help` | How to interpret results (params with/without defaults, output type "Any" → probe) |

**`pflow trace report` → `pflow report`**: Flattened — `trace` group had only one subcommand. Migration message added for old command.

**`pflow find` output self-documenting**: Match score decision tree removed from guide. Output now includes actionable guidance per confidence level:
- ≥95%: "High confidence match. Run it: `pflow <name> param="<type>"`" (with auto-extracted params)
- 80-94%: "Partial match. Show differences, ask: use as-is, modify, or build new?"
- 70-79%: "Weak match. Suggest modifying this workflow to fit."
- <70%: "No match. Build a new workflow. Start with: `pflow guide core`"

### All Production Code Changes

| File | Change |
|------|--------|
| `src/pflow/cli/commands/probe.py` | Help text rewritten with example output and usage guidance |
| `src/pflow/cli/commands/trace.py` | Rewritten: `trace` group → standalone `report` command |
| `src/pflow/cli/commands/settings.py` | Group help text added — credentials, LLM keys, inputs rule |
| `src/pflow/cli/commands/mcp.py` | `describe` help text added — interpreting results |
| `src/pflow/cli/main.py` | Import changed (`trace` → `report_cmd`), `"trace"` added to `_removed_commands` |
| `src/pflow/core/workflow/save_service.py` | `"report"` added to `RESERVED_WORKFLOW_NAMES` |
| `src/pflow/execution/formatters/discovery_formatter.py` | Confidence-based guidance in find output, run hint with auto-extracted params |
| `src/pflow/cli/commands/CLAUDE.md` | `pflow trace report` → `pflow report` |
| `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` | `pflow trace report` → `pflow report` (3 occurrences) |
| `src/pflow/mcp_server/resources/instructions/mcp-sandbox-agent-instructions.md` | `pflow trace report` → `pflow report` (1 occurrence) |
| `tests/test_cli/test_probe.py` | Updated assertion for new help text |
| `tests/test_execution/formatters/test_discovery_formatter.py` | Updated assertions for new find output format |

### Key Decisions Made

1. **No core/templates split** — Agents need both mental model and syntax to build a workflow. One chunk, condensed aggressively.

2. **core.md scope: building only** — Core teaches how to build workflows. Execution/discovery guidance (find workflows, run them, match scores) belongs in entry.md. Agent behavior (handling ambiguity, intent recognition) belongs in entry.md.

3. **`--help` is the authority on command mechanics** — Guide teaches when/why; `--help` teaches what/how. Applied to probe, report, settings, mcp describe.

4. **Self-documenting output over guide documentation** — `pflow find` output now includes actionable guidance per confidence level. Removes need for guide to teach match score interpretation.

5. **Error messages are self-describing** — No error lookup tables. `pflow report` is escalation path for complex cases only.

6. **Caching/--only/--report replace phased building** — The old "build in phases, write to file for inspection" approach is obsolete. New approach: write the workflow, run it, caching makes iteration fast, `--only` isolates nodes, `pflow report` for deep inspection.

7. **Probe for structure discovery, not testing** — "Test" in old instructions meant `pflow probe`. Agents probe MCP/HTTP nodes to discover output structure BEFORE writing the workflow. After writing: just run it (errors are self-describing).

8. **"Save" messaging TBD** — Old instructions: save is mandatory. User's view: workflows are project-local files, save-to-library is optional. Core.md now says "SAVE (Optional)" but Phase 1 should confirm this framing.

9. **`sub-workflows`** — Unanimous 5/5 poll for the merged workflow.md + nested.md chunk name.

### User's Communication Style (for next agent)

- Pushes back on unnecessary complexity — "is this needed?" is a frequent question
- Thinks from the agent's perspective — "what would an agent actually look for?"
- Very aware of current feature capabilities (caching, --only, --report) vs what old instructions assumed
- Prefers `--help` over guide content for command documentation
- Prefers self-documenting output over teaching agents to interpret output
- Values concrete before/after — Show Before You Code is a real gate
- Won't accept speculative features or "might be useful" content
- Wants discussion before implementation on non-obvious decisions

### Editorial Pass on core.md (964 → 780 lines)

Read the full file in 100-200 line chunks, critically assessed each section, then executed 22 specific changes:

**Removed redundancies**: anti-pattern section (duplicated extraction vs transformation), "No Dynamic Node Creation" (same as "No Loops"), real-world template jumping example (7th repetition), quick wins that were execution guidance, Development Loop bash examples (duplicated bullets), final reminder (3rd time saying "general over specific")

**Trimmed**: auto-JSON parsing table (7→3 rows), template patterns example (removed non-template lines), input declaration examples (5→2), multi-stage pipeline verbose steps, common mistakes (9→3 unique items), workflow smells (8→3 non-redundant items)

**Moved**: `inputs:` on any node to after template reference (better placement), batch prompt wiring mistake to features/batch.md

**Merged**: anti-pattern key insight into extraction vs transformation section ("check if you need to extract at all")

**Fixed**: emojis removed (🎯, ⚠️, 💡), unverified stat removed, typo fixed, save messaging aligned with SAVE (Optional), pre-caching advice updated

### Structural Cleanup (core.md 780 → 769)

- Merged "Step 9: RUN & ITERATE" + "Development Loop" into one "Running and Iterating" section (removed duplicate `pflow report` mention)
- Moved "Saving (Optional)" after iteration section (was wedged between running and dev loop)
- Dropped "Step N:" numbering from all headings → descriptive names (Before You Build, Finding Building Blocks, Building the Workflow, Running and Iterating, Saving)
- Merged thin Steps 1, 6, 7 into single "Before You Build" section (Identify/Design/Plan bullets)
- Removed batch prompt wiring from Common Mistakes (feature-specific, already in batch.md)
- Removed duplicate "Build incrementally" line and last ⚠️ emoji

### Node Chunk Review

Reviewed all 6 node chunks. Changes:
- **code.md**: Removed ⚠️ emoji from rules heading
- **http.md**: Added "Use for" line, removed verbose "Phase 1/Phase 2" API integration process, kept API research checklist as one-liner ("Research first: auth method, endpoints, request format, response structure, rate limits")
- **file.md**: Rewrote — added "Use for", added read-file example (was write-only), removed 1-row testing table and Phase 1 comment
- **mcp.md**: Removed "Reality vs Documentation Summary" table (general workflow advice, not MCP-specific)
- **llm.md**: No changes — already clean
- **shell.md**: No changes — already clean

### Feature Chunk Review

Reviewed all feature chunks. Changes:
- **structured.md**: **Deleted** — duplicate of llm.md content (same output_schema example). Structured output is an LLM node capability, not a standalone feature.
- **batch.md**: Removed ⚠️ emoji, removed redundant "Pattern:" heading, added `**Use when**:` opener with vocabulary triggers
- **branching.md**: Removed redundant "Pattern:" heading, added `**Use when**:` opener with vocabulary triggers
- **sub-workflows.md**: Removed duplicate "Key points" (already in top bullets), changed `**Use for**:` to `**Use when**:` with vocabulary triggers, added "executable both standalone AND as part of a parent" use case

### Additional Node Improvements

- **llm.md**: Added explicit "Don't use LLM for" callout with "The test: deterministic? → code. Not? → LLM."
- **code.md**: Added "Not for extraction — templates handle path traversal" one-liner
- **shell.md**: Added "Don't use shell for data pass-through: jq before LLM is unnecessary"

### entry.md Composed (2026-04-13)

Wrote entry.md from scratch as capability map. NOT a move from raw material — genuinely new content shaped by all discussions. Key design decisions:

- **Flat layout** matching Click's formatting style (section headers with `:`, 2-space indent)
- **No building advice** — entry.md is orientation/navigation only. Building is core's job.
- **"First Action" section** with decision tree: find existing → discover tools → probe/build
- **"Running Workflows"** showing both modes: file path (development) and saved name (library)
- **"Run Options"** — makes hidden run command flags discoverable (--only, --no-cache, --report, -o, --validate-only, --output-format, -p)
- **"Guide Topics"** — capability map with vocabulary triggers for features
- **"When to load the guide"** — building new (core + topics), modifying (auto-detect), errors (read error first)
- **MCP discovery** in the decision tree: "Need an external service? → `pflow mcp list` or `pflow mcp find`"
- **"All commands support `--help`"** — fundamental discoverability principle

Evaluated entry-raw-material.md against entry.md — all useful content absorbed. Remaining raw material is either covered elsewhere or not pflow-specific:
- Request parsing table → pflow-specific rows moved to core.md "Before You Build" section
- Intent signals table → covered by entry.md's First Action section
- Command examples → covered by entry.md + individual --help
- Decision tree → simplified in entry.md's First Action

### Additional core.md Changes

- Added pflow-specific request parsing to "Before You Build" section (vague user language → pflow concepts: limit inputs, on-error routing, MCP node selection)
- Restored 3 workflow smells that were over-aggressively removed (repetitive nodes, no output formatting, generic names)
- Restored auto-JSON parsing rows for array and boolean types (each demonstrates a distinct type)

### Test Improvements

Refactored help text assertions: 10 tests asserted on `"pflow runs workflows"` content string. Now:
- `test_main_command_help` is the ONE content test (asserts `"Guide Topics"`, `"pflow find"`, etc.)
- Other 9 tests assert on `"Usage:"` (stable Click output) — test BEHAVIOR (this input → help displayed), not CONTENT
- Changing entry.md now breaks 1 test instead of 10

### Current State (Post-Phase 1)

```
src/pflow/guide/
├── entry.md                  (62 — capability map, live in pflow --help)
├── entry-raw-material.md     (188 — fully evaluated, delete in Phase 2)
├── core.md                   (773)
├── nodes/
│   ├── code.md       (68)
│   ├── file.md       (27)
│   ├── http.md       (35)
│   ├── llm.md        (53)
│   ├── mcp.md        (180)
│   └── shell.md      (56)
└── features/
    ├── batch.md          (136)
    ├── branching.md      (145)
    └── sub-workflows.md  (65)
```

Tests: 4,718 passed, `make check` clean.

## Phase 2 — Implementation (2026-04-13)

### Pre-implementation review

Verified all Phase 1 deliverables before starting:
- 11 guide content files reviewed — all well-formed, standalone, with breadcrumbs
- 10 production code changes from Phase 1 reviewed — all correct
- 4,718 tests passing, `make check` clean

Fixed 4 loose ends found during review:
1. Stale `pflow trace report` → `pflow report` in `docs/reference/cli/index.mdx` (2 occurrences)
2. Stale `pflow trace report` → `pflow report` in `docs/guides/debugging.mdx` (2 occurrences)
3. `gpt-5.2` → `gpt-5.4` in `features/batch.md` (example model name)
4. Inconsistent `pflow workflow.pflow.md` → `pflow ./workflow.pflow.md` in `core.md` (2 occurrences, now consistent with entry.md)

### Implementation

**`src/pflow/guide/__init__.py`** — guide composition module (~120 lines new code):
- `GuideError` — clean error class for topic resolution failures
- `compose_guide(args)` — main composition: resolves args to topics, loads chunks, joins with `---` separators
- `list_topics()` — dynamic discovery from filesystem (scans `core.md`, `nodes/*.md`, `features/*.md`)
- `detect_topics_from_ir(ir)` — walks IR nodes/edges to detect relevant topics
- `_resolve_arg(arg)` — disambiguation: file path (has `/` or ends `.pflow.md`) → topic name → saved workflow name → unknown
- `_resolve_topic_path(topic)` — finds markdown file: `core.md` (top-level) → `nodes/<topic>.md` → `features/<topic>.md`
- `_topics_from_workflow_file(path)` — parses workflow, detects topics, handles missing file / parse errors
- `_try_load_saved_workflow(name)` — lazy import of WorkflowManager, returns IR or None
- `_NODE_TYPE_TO_TOPIC` mapping: `read-file`/`write-file` → `file`, `workflow` → `sub-workflows`, `mcp-*` → `mcp`

**Detection logic**:
- Node types map to topics (direct match or via `_NODE_TYPE_TO_TOPIC`)
- `node.get("batch")` at top level → adds `batch` topic
- Edge action != `"default"` → adds `branching` topic (covers `on-error` and code-based routing)
- Uses IR edge format: `{"from": ..., "to": ..., "action": ...}`

**`src/pflow/cli/commands/guide.py`** — stub replaced with real logic:
- No topics → `render_entry_content()` (same as before)
- With topics → `compose_guide()`, catches `GuideError` → stderr + exit 1

**`src/pflow/core/workflow/save_service.py`** — 9 topic names added to `RESERVED_WORKFLOW_NAMES`:
- `core`, `http`, `llm`, `code`, `shell`, `file`, `batch`, `branching`, `sub-workflows`

### Deletions

- `src/pflow/cli/resources/cli-agent-instructions.md` (2,225 lines) — content migrated to guide chunks
- `src/pflow/cli/resources/cli-basic-usage.md` (191 lines) — content migrated to entry.md + core.md
- `src/pflow/guide/entry-raw-material.md` (187 lines) — fully evaluated, all useful content absorbed

### Tests (35 tests in `tests/test_cli/test_guide.py`)

| Category | Count | What they test |
|----------|-------|----------------|
| Entry/fallback | 2 | No-args renders entry.md, content is non-empty |
| list_topics | 3 | Core/nodes/features present, core is first |
| Compose topic mode | 8 | Single/multi topic, order preservation, dedup, no auto-core, separators, unknown topic error |
| Compose workflow-ref mode | 6 | File auto-detection, multi-type detection, mixed args, dedup, missing file error, parse error |
| detect_topics_from_ir | 10 | Each node type mapping, batch, branching (error edge + named action), default-only edges, unknown types, sorted output |
| CLI integration | 3 | Single topic, unknown exits 1, multi-topic |
| Content integrity | 2 | All chunks exist and non-empty, node/feature chunks have breadcrumb |
| Reserved names | 1 | All topic names in RESERVED_WORKFLOW_NAMES |

### Documentation

- `docs/reference/cli/guide.mdx` — updated from Task 151 stub to full documentation (usage, topics, workflow-scoped mode, design notes)

### End-to-end verification

| Check | Result |
|-------|--------|
| `pflow --help` renders entry.md content | OK |
| `pflow guide` (no args) matches `--help` body | OK |
| `pflow guide http` — single topic loads | OK |
| `pflow guide core http batch` — multi-topic with `---` separators | OK |
| `pflow guide nonexistent` — error with topic list, exit 1 | OK |
| `pflow guide ./workflow.pflow.md` — auto-detects code + http from IR | OK |
| `pflow trace report` — migration message shown | OK |
| `pflow probe/report/settings/mcp describe --help` — Phase 1 help text renders | OK |
| Workflow execution (shell node) — core pipeline unaffected | OK |
| 4,750 tests pass, 9 skipped | OK |
| `make check` (ruff + mypy) clean | OK |

### Post-Phase 2 Polish

**Breadcrumbs removed**: "New to pflow? Run `pflow guide core`" removed from all 9 node/feature chunks. entry.md already serves as the navigation layer — the breadcrumb was redundant. Test updated to check headings instead.

**LLM node tips added** (`nodes/llm.md`):
- `--report` for inspecting rendered prompts + responses (ask user about `--report-dir ./report/` for project-local reports)
- `--only <node>` for cheap iteration when tuning prompts in multi-node workflows

### Final State

```
src/pflow/guide/
├── __init__.py               (197 — compose_guide, detect_topics_from_ir, list_topics)
├── entry.md                  (62 — capability map, live in pflow --help)
├── core.md                   (773 — framework fundamentals)
├── nodes/
│   ├── code.md       (66)
│   ├── file.md       (25)
│   ├── http.md       (33)
│   ├── llm.md        (55)
│   ├── mcp.md        (178)
│   └── shell.md      (53)
└── features/
    ├── batch.md          (134)
    ├── branching.md      (143)
    └── sub-workflows.md  (63)
```

Total guide content: 1,585 lines across 11 files (down from 2,416 lines in 2 monolithic files — 34% reduction with better discoverability).

Tests: 4,750 passed, `make check` clean.

### Dynamic Node Interface Injection

Node topics (http, llm, code, shell, file) now get Parameters + Outputs sections dynamically appended from registry metadata at render time. This replaces the old `registry describe` functionality — `pflow guide <node>` is the one-stop-shop for node information.

**Implementation** (`src/pflow/guide/__init__.py`):
- `_TOPIC_TO_NODE_TYPES` maps guide topics to registry node type(s). `file` maps to both `read-file` and `write-file`.
- `_get_node_interface(topic)` loads registry metadata and formats Parameters + Outputs sections
- `_format_interface()` renders each param/output as `- \`key: type\` - description`
- Filters out bogus `key: "default"` entries from metadata extractor bug (GH #277)
- For multi-node topics (`file`), each node type gets its own `###` heading
- `mcp` topic skipped — tools are user-specific, content points to `pflow mcp describe`

**Composition order** (5/5 agent poll): static prose first (guidance, tips, patterns), dynamic interface last (parameters, outputs). Separated by `---`.

**5 new tests**: dynamic params present for node topics, file shows both types, feature/mcp topics have no interface.

### CLAUDE.md Updates

- Created `src/pflow/guide/CLAUDE.md` — documents guide layout, topic resolution, dynamic injection, how to add topics
- Updated `src/pflow/cli/commands/CLAUDE.md` — guide section: "placeholder" → actual behavior
- Updated `src/pflow/cli/CLAUDE.md` — `resources/` directory note: files moved to `src/pflow/guide/`

### Known Issue Filed

GH #277: Metadata extractor parses `(optional, default: value)` as separate params. Workaround in guide formatter. Affects `code`, `read-file`, `write-file` node interfaces in registry data.

### Code Review Fixes

Code review (`scratchpads/code-review-staged-20260413-230608.md`) raised 3 warnings + 1 suggestion. Actions taken:

**Fixed — broken saved workflow error path** (`src/pflow/guide/__init__.py`):
`_try_load_saved_workflow` was catching all exceptions and returning None, so a malformed saved workflow reported "Unknown topic" instead of the actual parse error. Now catches only `WorkflowNotFoundError` (returns None for "not found"), raises `GuideError` with the load failure details for everything else. New test: `test_compose_broken_saved_workflow_shows_load_error`.

**Fixed — settings help text** (`src/pflow/cli/commands/settings.py`):
Help text said "stored credentials are NOT auto-available in workflows" — incorrect. Credentials stored via `settings set-env` ARE available as fallbacks for declared workflow inputs (precedence: CLI params > shell env > settings env > workflow defaults). Rewritten to reflect actual behavior.

**Disputed — reserved topic names**: Reviewer argued topic names shouldn't be in `RESERVED_WORKFLOW_NAMES` since they don't conflict with CLI routing. Technically correct (routing goes through Click commands, not topic names), but the reservation is a deliberate defensive measure for `pflow guide` disambiguation (task spec lines 335-337). Topics already win over saved workflow names in code, but reserving them at save time prevents the ambiguity from ever existing. Kept as-is.

### Cleanup

- Removed empty `src/pflow/cli/resources/` directory
- Removed stale `resources/` line from `src/pflow/cli/CLAUDE.md` file structure

### Final State

Tests: 4,756 passed, `make check` clean.
