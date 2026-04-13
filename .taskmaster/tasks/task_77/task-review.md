# Task 77 Review: Pflow Guide — Tailored Agent Instructions

## Metadata

- **Implementation Date**: 2026-04-12 / 2026-04-13
- **Scope**: 41 files changed, 3674 insertions, 2508 deletions (net +1166)
- **Final state**: 4,759 tests passing, `make check` clean

## Executive Summary

Replaced the monolithic `cli-agent-instructions.md` (2,225 lines) + `cli-basic-usage.md` (191 lines) with `pflow guide`, a topic-scoped content delivery system. 11 markdown chunks under `src/pflow/guide/` are composed at runtime based on what the agent asks for. Total guide content: 1,585 lines across 11 files (34% reduction). The implementation went significantly beyond the original spec — dissolving 4 planned chunks, flattening the `trace` command, adding dynamic node interface injection from the registry, and making `pflow find` output self-documenting.

## Implementation Overview

### What Was Built

**Guide composition system** (`src/pflow/guide/__init__.py`, ~200 lines):
- `compose_guide(args)` — resolves args to topics, loads markdown chunks, joins with `---` separators
- `detect_topics_from_ir(ir)` — walks workflow IR to auto-detect relevant topics
- `list_topics()` — dynamic discovery from filesystem
- Dynamic node interface injection — Parameters/Outputs appended from registry metadata at render time

**Content files** (11 chunks):
- `entry.md` (62 lines) — capability map with vocabulary triggers, rendered by both `pflow --help` and `pflow guide`
- `core.md` (773 lines) — framework fundamentals (mental model, templates, development loop)
- 6 node chunks (`nodes/*.md`) — per-node interface, patterns, gotchas + dynamic Parameters/Outputs
- 3 feature chunks (`features/*.md`) — batch, branching, sub-workflows

**CLI improvements** (beyond spec):
- `pflow trace report` → `pflow report` (flattened group with one subcommand)
- `pflow find` output now includes confidence-based guidance with runnable commands
- Help text improvements on `probe`, `settings`, `mcp describe`

### What Changed From the Spec

The original spec planned 17 chunk files across 4 directories. The final implementation has 11 files across 3 directories. Key deviations:

| Spec | Actual | Why |
|------|--------|-----|
| `cross/mcp-testing.md` | Dissolved into node chunks | Testing advice is per-node, not cross-cutting |
| `cross/debugging.md` | Dissolved entirely | Error messages are already self-describing (Tasks 143/144/148) |
| `cross/phased-building.md` | Dissolved entirely | Caching + `--only` + `--report` replace phased building |
| `cross/auth.md` | Dissolved into `settings --help` | CLI help is the right place for command usage |
| `features/structured.md` | Deleted | Duplicate of llm.md content (output_schema is an LLM capability) |
| `nodes/workflow.md` + `features/nested.md` | Merged → `features/sub-workflows.md` | Same topic from different angles |
| `core.md` budget: 100-150 lines | 773 lines | Budget was wildly optimistic; content is loaded once |
| No dynamic content | Dynamic interface injection from registry | Replaces `registry describe` for core nodes |
| Save as mandatory Step 10 | Save as optional | User's model: workflows are project-local files |

### Implementation Approach

Three phases executed in sequence:

1. **Phase 0** — Content move. Every paragraph from the 2,225-line source tagged to a target chunk and moved as-is. Three consolidations (duplicate sections, redundant command cheat sheet).

2. **Phase 1** — Content refinement. Iterative discussion with the user shaped the guiding principle: **make the CLI surface self-documenting; guide only teaches what the CLI can't.** This dissolved 4 planned chunks, improved CLI help text, and made `pflow find` output self-documenting.

3. **Phase 2** — Implementation. Guide composition code (~200 lines), tests (44 tests), reserved names, deletions.

## Files Modified/Created

### Core Changes (new)

| File | Purpose |
|------|---------|
| `src/pflow/guide/core.md` | Framework fundamentals (step order vs templates, input rules, template reference, development loop) |
| `src/pflow/guide/entry.md` | Capability map — rendered by `pflow --help` and `pflow guide` (no args) |
| `src/pflow/guide/nodes/*.md` (6 files) | Per-node guides: http, llm, code, shell, file, mcp |
| `src/pflow/guide/features/*.md` (3 files) | Per-feature guides: batch, branching, sub-workflows |
| `src/pflow/guide/CLAUDE.md` | Documents guide layout, topic resolution, dynamic injection, how to add topics |

### Core Changes (modified)

| File | What changed |
|------|-------------|
| `src/pflow/guide/__init__.py` | Rewritten: `render_entry_content` preserved, added `compose_guide`, `detect_topics_from_ir`, `list_topics`, dynamic interface injection |
| `src/pflow/cli/commands/guide.py` | Stub replaced with real composition logic |
| `src/pflow/cli/commands/trace.py` | Rewritten: `trace` group → standalone `report` command |
| `src/pflow/cli/main.py` | Import changed (`trace` → `report_cmd`), `"trace"` added to `_removed_commands` |
| `src/pflow/core/workflow/save_service.py` | `"report"` + 9 topic names added to `RESERVED_WORKFLOW_NAMES` |
| `src/pflow/execution/formatters/discovery_formatter.py` | Confidence-based guidance in find output, auto-extracted run hints |
| `src/pflow/cli/commands/probe.py` | Help text rewritten with example output |
| `src/pflow/cli/commands/settings.py` | Group help text added — credentials setup |
| `src/pflow/cli/commands/mcp.py` | `describe` help text added |

### Deleted

| File | Why |
|------|-----|
| `src/pflow/cli/resources/cli-agent-instructions.md` | Content migrated to guide chunks |
| `src/pflow/cli/resources/cli-basic-usage.md` | Content migrated to entry.md + core.md |
| `src/pflow/cli/resources/` (directory) | Empty after deletions |

### Test Files

| File | What it tests |
|------|---------------|
| `tests/test_cli/test_guide.py` (44 tests) | Guide composition, topic resolution, workflow auto-detection, dynamic interface, CLI integration, content integrity, reserved names |
| `tests/test_cli/test_cli.py` (+2 tests) | `pflow report` command — no traces error, end-to-end with real trace |

**Critical tests** (catch real bugs, not coverage):
- `test_compose_from_realistic_workflow_detects_all_topic_types` — full pipeline with realistic .pflow.md, catches IR format drift
- `test_compose_broken_saved_workflow_shows_load_error` — caught the "unknown topic" vs actual load error bug
- `test_topic_names_are_reserved` — structural guard preventing name collisions
- `test_report_command_generates_from_trace` — catches command registration regressions

## Integration Points & Dependencies

### Incoming Dependencies

| Consumer | Interface | Notes |
|----------|-----------|-------|
| `pflow --help` | `render_entry_content()` | `entry.md` content rendered via `PflowCLI.format_help()` override |
| `pflow guide <topics>` | `compose_guide(args)` | Called from `guide_cmd` in `commands/guide.py` |
| Task 152 (MCP parity) | `render_entry_content()` | MCP server may want shared entry content |
| Workflow save | `RESERVED_WORKFLOW_NAMES` | Topic names reserved to prevent disambiguation conflicts |

### Outgoing Dependencies

| This Task | Depends On | Interface |
|-----------|-----------|-----------|
| `compose_guide()` | `markdown_parser.parse_markdown()` | Workflow file parsing for auto-detection |
| `compose_guide()` | `WorkflowManager.load_ir()` | Saved workflow loading for auto-detection |
| `_get_node_interface()` | `Registry.load()` | Dynamic Parameters/Outputs from registry metadata |
| `entry.md` rendering | `PflowCLI.format_help()` override | Task 151's `format_help()` calls `render_entry_content()` |

## Architectural Decisions & Tradeoffs

### Key Decisions

1. **`--help` is the authority on command mechanics; guide teaches when/why**
   - *Reasoning*: Guide content about "how to run `pflow probe`" drifts from actual behavior. Help text is the source of truth. Guide teaches when to probe vs skip, not how to invoke the command.
   - *Impact*: Dissolved 4 planned cross-cutting chunks. Improved help text on probe, settings, mcp describe.

2. **Self-documenting output over guide documentation**
   - *Reasoning*: `pflow find` output now includes confidence-based guidance ("High confidence match. Run it: ..."). Removes need for guide to teach match score interpretation.
   - *Impact*: Match score decision tree removed from guide. Discovery formatter gained `_format_confidence_guidance()` and `_build_run_hint()`.

3. **Dynamic node interface injection from registry**
   - *Reasoning*: Node parameters change with implementations. Static docs drift. Reading from registry keeps interface docs in sync automatically.
   - *Impact*: `pflow guide <node>` is now the one-stop-shop for node information, replacing the old `registry describe`. `_TOPIC_TO_NODE_TYPES` mapping controls which topics get dynamic interfaces.

4. **`core` is explicit, NOT auto-included**
   - *Reasoning*: Agents load `core` once at session start, then load topic chunks as scope expands. Auto-including core on every call wastes context window.
   - *Impact*: `pflow guide http` returns ONLY http content. `pflow guide core http` returns both.

5. **Topic resolution: file path → topic name → saved workflow name**
   - *Reasoning*: Topic names are a small, finite set. Workflow names are user-created and could collide. Topics winning is the safe default. File paths detected by `/` or `.pflow.md` suffix to avoid ambiguity.
   - *Impact*: Topic names added to `RESERVED_WORKFLOW_NAMES` to prevent the collision from ever existing.

### Technical Debt Incurred

1. **`_get_node_interface` bare `except Exception: return None`** — silently drops dynamic interface when registry unavailable. Acceptable degradation (static content is still useful) but a `logger.debug` would help troubleshooting.

2. **`_format_param_line` workaround for metadata extractor bug** (GH #277) — filters out `key: "default"` artifacts and fixes truncated descriptions. Should be fixed at the source in `registry/metadata_extractor.py`.

3. **MCP discovery formatter embeds CLI commands** — `_format_confidence_guidance()` includes `pflow describe`, `cat ~/.pflow/workflows/...`. MCP agents without CLI access can't use these. Task 152 should address this.

## Patterns Established

### Reusable Patterns

**1. Static prose + dynamic interface for node topics**
```python
# In compose_guide:
content = path.read_text(encoding="utf-8").rstrip()
interface = _get_node_interface(topic)
if interface:
    content = content + "\n\n---\n\n" + interface
```
Static `.md` files teach when/why/patterns. Dynamic section from registry provides current parameters/outputs. Separated by `---`.

**2. Filesystem-based topic discovery**
```python
def list_topics() -> list[str]:
    topics = []
    if (GUIDE_DIR / "core.md").exists():
        topics.append("core")
    for subdir in ("nodes", "features"):
        for f in sorted((GUIDE_DIR / subdir).glob("*.md")):
            topics.append(f.stem)
    return topics
```
Adding a new topic = create a `.md` file. No registration needed. `list_topics()` scans automatically.

**3. Adding a new guide topic (checklist)**
1. Create `nodes/<type>.md` or `features/<name>.md`
2. If node topic: add mapping to `_TOPIC_TO_NODE_TYPES` in `__init__.py`
3. Add topic name to `RESERVED_WORKFLOW_NAMES` in `save_service.py`
4. Update `entry.md` topic list

**4. Migration messages for removed commands**
```python
_removed_commands: ClassVar[dict[str, str]] = {
    "trace": "Replaced by: pflow report",
}
```
In `PflowCLI`, `MCPGroup`, or `SettingsGroup`. Prevents "Invalid input" confusion when agents use old command names.

### Anti-Patterns to Avoid

1. **Don't put command mechanics in guide content** — "how to invoke `pflow probe`" belongs in `pflow probe --help`, not in a guide chunk. Guide teaches when/why to use it.

2. **Don't auto-include `core`** — The composition system intentionally requires explicit `core` to prevent re-loading framework fundamentals on every guide call.

3. **Don't duplicate content between `entry.md` and `core.md`** — Entry is orientation/navigation. Core is building knowledge. They have different audiences (new agent vs building agent).

## Breaking Changes

### CLI Surface

| Old | New | Type |
|-----|-----|------|
| `pflow trace report [trace] [-o dir]` | `pflow report [trace] [-o dir]` | Flattened (migration message) |
| `pflow guide` (no args) | Same | Now renders `entry.md` content instead of placeholder |
| `pflow guide <topic>` | Same | Was "coming soon" stub, now returns real content |

### Files Deleted

| Old | Replacement |
|-----|-------------|
| `src/pflow/cli/resources/cli-agent-instructions.md` | `src/pflow/guide/*.md` (11 files) |
| `src/pflow/cli/resources/cli-basic-usage.md` | `src/pflow/guide/entry.md` + `core.md` |

## Future Considerations

### Extension Points

1. **New node type** → create `nodes/<type>.md`, add to `_TOPIC_TO_NODE_TYPES`, add to `RESERVED_WORKFLOW_NAMES`, update `entry.md` topic list
2. **New feature** → create `features/<name>.md`, add to `RESERVED_WORKFLOW_NAMES`, update `entry.md` with vocabulary triggers
3. **MCP-side guide** (Task 152) → `render_entry_content()` is importable from `pflow.guide`. The guide content is CLI-only but the composition system could serve MCP by transforming CLI commands to MCP tool names.

### Fragility Warnings

1. **`entry.md` IS `pflow --help`** — editing `entry.md` changes the CLI help output. Always verify `pflow --help` after editing.
2. **`_TOPIC_TO_NODE_TYPES`** controls dynamic injection — forgetting to add a mapping means the topic shows static prose only (no Parameters/Outputs).
3. **IR format changes break auto-detection** — `detect_topics_from_ir` reads `node["batch"]` at top level and `edge["action"]`. If the parser changes where these live, the realistic workflow test catches it.

## AI Agent Guidance

### Quick Start for Related Tasks

1. Read `src/pflow/guide/CLAUDE.md` — documents layout, topic resolution, dynamic injection, how to add topics
2. Read `src/pflow/guide/__init__.py` — all composition logic
3. Run `pflow guide http` to see composed output (static prose + dynamic interface)
4. Run `pflow --help` to see entry.md rendered

### Common Pitfalls

1. **Don't create `__init__.py` in `nodes/` or `features/`** — these are markdown resource directories, not Python packages
2. **Don't forget `RESERVED_WORKFLOW_NAMES`** when adding topics — `test_topic_names_are_reserved` will catch this
3. **Don't put the guide package at `cli/resources/guide/`** — the spec said this, but Task 151 put it at `src/pflow/guide/` (top-level package) so both CLI and MCP can import `render_entry_content()`
4. **Don't mock.patch `pflow.guide.compose_guide`** in CLI tests — use CliRunner with real content. The guide system is fast (file reads only) and tests with real content catch content regressions.

### Test-First Recommendations

When modifying guide content or composition:
1. `pytest tests/test_cli/test_guide.py -q` — all guide tests (fast, <1s)
2. `pflow --help` — verify entry.md renders correctly
3. `pflow guide http` — verify dynamic interface injection works
4. `pflow guide nonexistent` — verify error handling

---

*Generated from implementation context of Task 77*
