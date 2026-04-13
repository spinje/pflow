# Task 77 Phase 0: Content Move Plan

## Context

Task 77 replaces the monolithic `cli-agent-instructions.md` (2,225 lines) + `cli-basic-usage.md` (191 lines) with topic-scoped markdown chunks under `src/pflow/guide/`. Phase 0 is a **move operation** — content goes to the right chunk as-is. No condensation, no rewriting. Condensation happens per-chunk in Phase 1.

**Prerequisite**: Task 151 (CLI restructure) is merged. The `src/pflow/guide/` package exists with `__init__.py` (contains `render_entry_content()`) and an empty `entry.md`.

**Neither source file is used by production code** — they're inert reference material. Safe to leave in place during Phase 0 as verification reference.

## Target Structure

```
src/pflow/guide/
├── entry.md                  ← raw material from cli-basic-usage.md
├── core.md                   ← framework fundamentals (will be large, ~900 lines as-is)
├── nodes/
│   ├── http.md
│   ├── llm.md
│   ├── code.md
│   ├── shell.md
│   ├── file.md               ← thin (~20 lines, needs Phase 1 expansion)
│   ├── mcp.md
│   └── workflow.md            ← thin (~30 lines, needs Phase 1 expansion)
├── features/
│   ├── batch.md
│   ├── branching.md
│   ├── nested.md
│   └── structured.md         ← thin (~35 lines)
└── cross/
    ├── mcp-testing.md
    ├── phased-building.md
    ├── debugging.md
    └── auth.md
```

No `__init__.py` in subdirectories — these are markdown resource directories, not Python packages.

## Agreed Consolidations (3 only)

1. **Mandatory first step** — appears in both source files. Keep the richer version from cli-agent-instructions.md (lines 42-55) in core.md. Drop cli-basic-usage.md lines 5-27.

2. **Match score decision trees** — three copies (lines 49-54, 300-311, cli-basic-usage.md 20-24). Both cli-agent-instructions.md versions end up in core.md naturally (they're in sections that both map to core.md). The cli-basic-usage.md copy drops (consolidation #1 already drops that section). Merge within core.md happens during Phase 1 condensation.

3. **Command cheat sheet** (lines 2118-2142) — delete. Redundant with `pflow --help` / `entry.md`.

## Content Mapping: cli-agent-instructions.md

### → core.md

| Lines | Content |
|-------|---------|
| 1-55 | Header, core mission, primary decision rule, quick wins, core philosophy, mandatory first step |
| 66-183 | Step order vs templates (two concepts, 5-step example, data availability table, misunderstandings) |
| 185-253 | What workflows CANNOT do + One workflow or multiple |
| 255-279 | Node type selection (entire block, including per-node details — split later in Phase 1) |
| 283-299 | Step 1: UNDERSTAND (parse requirements, intent signals table) |
| 300-316 | Step 2: DISCOVER WORKFLOWS (most detailed match-score version) |
| 317-328 | Step 3: DISCOVER NODES (general discovery advice only) |
| 467-493 | Steps 6-7: DESIGN + PLAN & CONFIRM |
| 494-551 | Step 8: BUILD (dev format, workflow skeleton, key rules, nesting backticks) |
| 649-711 | Input declaration complete rules (decision tree + examples) |
| 847-863 | `inputs:` works on ANY node type |
| 865-877 | Step 9: TEST (dev loop, trace files) |
| 879-933 | Step 10: SAVE (save command, examples, after-save usage) |
| 935-937 | Part 4 preamble ("Before building, verify:...") |
| 974-1018 | Workflow structure complete reference (overlaps with Step 8 skeleton — both stay) |
| 1020-1063 | Template variable complete reference (resolution order, auto-JSON, escape hatch) |
| 1064-1110 | Anti-pattern (unnecessary extraction) + correct patterns |
| 1112-1127 | Automatic JSON serialization for string-typed params |
| 1129-1173 | Transformation complexity checklist + extraction vs transformation decision rule |
| 1175-1235 | All template patterns (basic, nested, structured objects, yaml blocks) |
| 1271-1322 | Parameter types complete guide |
| 1465-1512 | Pattern: Extract from structured data |
| 1514-1598 | Pattern: Multi-stage data pipeline (full end-to-end example) |
| 1979-2041 | Common mistakes detailed solutions (all 8 items — redistribute per-node items in Phase 1) |
| 2043-2073 | Real request parsing (ambiguity table + clarification template) |
| 2088-2101 | Workflow smells table (general quality, NOT MCP-specific) |
| 2144-2193 | Quick references (template, decisions, naming convention) |
| 2195-2209 | Common agent mistakes table (overlaps with 1979-2041 — merge in Phase 1) |
| 2210-2225 | Key success factors + final reminder |

### → nodes/http.md

| Lines | Content |
|-------|---------|
| 280-282 | Async API optimization (Prefer: wait header) |
| 336-350 | Step 4: External API integration (research + test auth) |
| 713-731 | HTTP node creation pattern (fetch with auth, POST, headers, body) |

### → nodes/llm.md

| Lines | Content |
|-------|---------|
| 785-820 | LLM node creation pattern (structured analysis with output_schema, prompt) |

### → nodes/code.md

| Lines | Content |
|-------|---------|
| 743-783 | Code node creation patterns (filter/reshape + merge/dict output) |
| 839-845 | Code node rules (templates in inputs, type annotations, auto-parsing) |

### → nodes/shell.md

| Lines | Content |
|-------|---------|
| 733-741 | Shell node creation pattern (find command) |
| 1237-1247 | Templates in shell commands (pflow resolves before shell runs) |

### → nodes/file.md

| Lines | Content |
|-------|---------|
| (fragments only) | write-file examples from lines 591, 1595-1597; testing matrix row from line 1337 |

Note: Very thin. Add `<!-- Phase 1: expand to full node interface documentation -->` marker.

### → nodes/mcp.md

| Lines | Content |
|-------|---------|
| 57-65 | Supported service categories |
| 329-335 | Step 3: MCP-specific discovery advice |
| 448-465 | "MCP Output Has NO Standard Structure" warning + examples |
| 822-837 | MCP update service creation pattern |
| 1600-1647 | Pattern: Service orchestration with formatting |
| 2075-2087 | MCP/HTTP reality vs documentation table |
| 2103-2117 | Reality vs documentation summary table |

### → nodes/workflow.md

| Lines | Content |
|-------|---------|
| (fragments only) | Brief mentions from lines 275-278 (node type selection) and 239-246 (compose decision). Main nested content goes to features/nested.md. |

Note: Thin. Add `<!-- Phase 1: expand to full node interface documentation -->` marker.

### → features/batch.md

| Lines | Content |
|-------|---------|
| 1649-1780 | Pattern: Batch processing (entire block — self-contained) |

### → features/branching.md

| Lines | Content |
|-------|---------|
| 1781-1922 | Pattern: Conditional branching (entire block — self-contained) |

### → features/nested.md

| Lines | Content |
|-------|---------|
| 1924-1977 | Pattern: Nested workflow composition (child/parent example, key points) |

### → features/structured.md

| Lines | Content |
|-------|---------|
| 793-808 | output_schema yaml example (extracted from LLM node pattern) |
| 1134-1136 | "Use output_schema — guarantees valid JSON via constrained decoding" |

Note: Thin (~35 lines). May need Phase 1 expansion.

### → cross/mcp-testing.md

| Lines | Content |
|-------|---------|
| 351-430 | Step 5: TEST MCP/HTTP NODES (decision tree, skip-test rules) |
| 431-447 | MCP Testing Protocol (4-step process) |
| 1324-1350 | Precise testing decision matrix |
| 1352-1401 | MCP meta-discovery + structure discovery process |

### → cross/phased-building.md

| Lines | Content |
|-------|---------|
| 554-646 | Phase-based building + "Iteration is free" (caching) |

### → cross/debugging.md

| Lines | Content |
|-------|---------|
| 1249-1269 | Debugging template errors |
| 1403-1463 | Systematic debugging process (3 phases) |

### → cross/auth.md

| Lines | Content |
|-------|---------|
| 938-972 | Authentication setup (settings set-env, llm keys set, credentials as inputs) |

### → DELETE

| Lines | Content | Reason |
|-------|---------|--------|
| 2118-2142 | Command cheat sheet | Redundant with `pflow --help` |

### Metadata / separators (not moved)

Lines 552-553 (horizontal rule), 647-648 (Part 2 comment), 1324 (Part 3 comment) — structural markers, not content.

## Content Mapping: cli-basic-usage.md

### → entry.md (raw material)

| Lines | Content |
|-------|---------|
| 1-4 | Header, purpose |
| 28-32 | Execute directly vs create workflow decision (1-2 nodes vs 3+) |
| 33-65 | Essential commands, execute workflow, output behavior, "never re-run" |
| 91-104 | When to read guide |
| 105-146 | Node commands (probe, mcp find/list/describe, read-fields) |
| 148-190 | Quick decision tree |

### → core.md

| Lines | Content |
|-------|---------|
| 67-89 | Iterating on workflow files (caching, --only, --no-cache, --report, visualize) |

### → DROP (consolidation #1)

| Lines | Content | Reason |
|-------|---------|--------|
| 5-27 | Mandatory first step | Weaker duplicate — richer version in cli-agent-instructions.md lines 42-55 |

## Execution Steps

### Step 1: Create directories

```
mkdir -p src/pflow/guide/nodes
mkdir -p src/pflow/guide/features
mkdir -p src/pflow/guide/cross
```

### Step 2: Create chunk files (bottom-up order)

Work in this order so "remaining for core.md" is unambiguous:

1. **Node chunks** (7 files): http.md, shell.md, code.md, llm.md, mcp.md, file.md, workflow.md
2. **Feature chunks** (4 files): batch.md, branching.md, nested.md, structured.md
3. **Cross-cutting chunks** (4 files): mcp-testing.md, phased-building.md, debugging.md, auth.md
4. **core.md** — all remaining content from cli-agent-instructions.md + caching section from cli-basic-usage.md
5. **entry.md** — raw material from cli-basic-usage.md

For each file: copy the mapped line ranges as-is. No rewriting. Add only:
- A `# Topic Name` heading at the top of each file
- Breadcrumb at the end of nodes/*.md and features/*.md: `---\nNew to pflow? Run \`pflow guide core\` for the framework fundamentals.`

### Step 3: Verify completeness

1. **Spot-check 10 distinctive phrases** — each must appear in exactly one chunk:
   - "Prefer: wait=60" → nodes/http.md
   - "$VAR not ${VAR}" → nodes/shell.md (or core.md if in the node selection block)
   - "Templates go in inputs, NEVER in the python code block" → nodes/code.md
   - "Every MCP server is completely different" → nodes/mcp.md
   - "Same operation × N items" → features/batch.md
   - "Route execution based on data or errors" → features/branching.md
   - "Nesting depth limited to 10 levels" → features/nested.md
   - "Phase 1: Core Data Path" → cross/phased-building.md
   - "Data transformation → code node" → core.md
   - "pflow settings set-env" → cross/auth.md

2. **Grep for orphaned content** — search source files for any paragraph not in any chunk.

### Step 4: Do NOT delete source files

Source files stay as verification reference. Deletion happens after Phase 2 (when guide command is wired up and tests pass).

## Phase 1 (outline — not part of this plan's scope)

- Condense each chunk to target size (core.md from ~900 → ~250-300, nodes ~50-100, features ~60-100, cross ~40-80)
- Compose entry.md as capability map with vocabulary triggers (~50-80 lines)
- Merge duplicate sections within core.md (two workflow skeletons, three common-mistakes sections)
- Decide on "save" messaging (project-local default vs library)
- Draft composed outputs for approval
- Incorporate pedagogical framing ideas (thinking process, workflow shapes, node decision tree)

## Phase 2 (outline)

- Implement `compose_guide()` in `src/pflow/guide/__init__.py` (~50-100 lines)
- Replace stub in `src/pflow/cli/commands/guide.py`
- Add topic names to `RESERVED_WORKFLOW_NAMES` in `src/pflow/core/workflow/save_service.py`
- Delete source files
- Write tests (unit + integration per task spec)
- `make test && make check`

## Critical Files

| File | Role |
|------|------|
| `src/pflow/cli/resources/cli-agent-instructions.md` | Source (2,225 lines) — read only |
| `src/pflow/cli/resources/cli-basic-usage.md` | Source (191 lines) — read only |
| `src/pflow/guide/__init__.py` | Existing loader — unchanged in Phase 0 |
| `src/pflow/guide/entry.md` | Currently empty — gets raw material |
| `src/pflow/guide/nodes/*.md` | 7 new files |
| `src/pflow/guide/features/*.md` | 4 new files |
| `src/pflow/guide/cross/*.md` | 4 new files |
| `src/pflow/guide/core.md` | 1 new file (largest) |
