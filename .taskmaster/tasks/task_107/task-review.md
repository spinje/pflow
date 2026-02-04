# Task 107 Review: Implement Markdown Workflow Format

## Metadata

- **Branch**: `feat/markdown-workflow-format`
- **Commits**: 20 on branch
- **Scope**: 265 files changed, +20,230 / -8,077 lines
- **Test state**: 3609 passed, 516 skipped, 0 failed

## Executive Summary

Replaced JSON as the workflow file format with `.pflow.md` markdown. A custom 779-line state machine parser (`markdown_parser.py`) produces the same IR dict that `json.load()` previously produced — all downstream validation, compilation, and execution is unchanged. Save preserves original markdown content (no IR-to-markdown serialization). The planner and repair systems are gated (not removed) since their prompts assume JSON format. This was the largest single task in pflow history, touching every integration point in the system.

## Implementation Overview

### What Was Built

1. **Markdown parser** (`src/pflow/core/markdown_parser.py`, 779 lines) — line-by-line state machine that parses `.pflow.md` files into IR dicts. Handles frontmatter, H1/H2/H3 heading hierarchy, `- key: value` YAML params with continuation/nesting, fenced code blocks (including nested fences), prose extraction, edge generation from document order, and param routing by section type.

2. **Test utility** (`tests/shared/markdown_utils.py`, 207 lines) — `ir_to_markdown()` converts any IR dict to valid `.pflow.md` content. `write_workflow_file()` writes it to disk. Test-only, not production. This was the single most important tool for migrating ~200 JSON-writing test occurrences.

3. **WorkflowManager rewrite** — complete storage format change from `.json` to `.pflow.md` with YAML frontmatter for system metadata. Flat metadata structure (no `rich_metadata` wrapper).

4. **Integration at all 7 entry points** — CLI file loading, CLI save command, WorkflowManager, save service, MCP resolver, MCP save tool chain, runtime nested workflow loading.

5. **Example conversions** — 30+ JSON workflow files converted to `.pflow.md`, 8 new invalid example files, 4 old invalid JSON files deleted.

6. **Test migration** — 25+ test files updated from JSON to markdown (200+ individual occurrences).

7. **Planner/repair gating** — 6 production entry points gated with `if` guards, ~10 test files skipped via `pytest.mark.skip`.

8. **Unknown param warnings** — new validation layer (layer 8 in `WorkflowValidator`) comparing node params against registry interface metadata.

9. **Agent instructions** — `cli-agent-instructions.md` fully rewritten for `.pflow.md` format.

10. **Agent-friendly command output** — `.pflow.md` usage snippets added to `registry describe`, `mcp info`, and other discovery commands.

### Deviations from Original Spec

| Area | Spec said | What happened |
|------|-----------|---------------|
| Parser size | ~300-400 lines | 779 lines (more validation, better errors) |
| `ir_to_markdown` | ~100-150 lines | 207 lines (more code block types handled) |
| Inline batch routing | Only from `yaml batch` code blocks | Also from inline `- batch:` params (discovered during Phase 5 agent instruction review) |
| `rich_metadata` flattening | 6 callers | Also `test_executor_service.py` (13 refs), MCP save tests, workflow save service tests |
| MCP save flow | Update `resolve_workflow()` | Built separate save-specific detection — `resolve_workflow()` discards original content, can't be reused for save |
| Phase 3 approach | All fork-session | Hit context window limit after ~12 forks; switched to test-writer-fixer subagents |
| Nested workflow validation | Not in scope | Found and fixed 2 pre-existing bugs (workflow type allowlist, output_mapping template registration) |

## Files Modified/Created

### Core Changes (new files)

- `src/pflow/core/markdown_parser.py` — the parser. `parse_markdown(content) -> MarkdownParseResult`. State machine with `MarkdownParseError` exception type. **This is the single most important new file in the task.**
- `tests/shared/markdown_utils.py` — `ir_to_markdown()` and `write_workflow_file()`. Test infrastructure only.
- `tests/test_core/test_markdown_parser.py` (1896 lines) — 73 tests across 15 categories.
- `examples/invalid/*.pflow.md` — 8 new invalid examples for parse error testing.

### Core Changes (major modifications)

- `src/pflow/core/workflow_manager.py` — complete rewrite. `.json` -> `.pflow.md`, metadata wrapper -> frontmatter, `save(name, ir, description)` -> `save(name, markdown_content, metadata)`, `load()` returns flat metadata, `update_metadata()` does frontmatter read-modify-write.
- `src/pflow/cli/main.py` — ~15 integration points: path detection, file loading, error display, registry lookup, save flow, gating, extension error UX, trace filename derivation.
- `src/pflow/cli/commands/workflow.py` — removed `--description` flag, markdown parsing for save, gated `--generate-metadata`.
- `src/pflow/core/workflow_save_service.py` — `save_workflow_with_options(name, markdown_content, *, force, metadata)`.
- `src/pflow/mcp_server/services/execution_service.py` — save flow restructured (6 functions deep, G8). Separate content detection for save path.
- `src/pflow/mcp_server/utils/resolver.py` — markdown content detection (newline = content, `.pflow.md` = path, single-line = name).
- `src/pflow/core/workflow_validator.py` — removed JSON anti-pattern layer (7), added unknown param warning layer (8).
- `src/pflow/cli/resources/cli-agent-instructions.md` — full rewrite for markdown format.

### Test Files (critical ones)

- `tests/test_core/test_markdown_parser.py` — 73 tests. The most important test file. Covers complete workflow parsing, section handling, entity parsing, YAML params (flat, nested, non-contiguous, block scalars), code blocks (nested fences), param routing, edge generation, frontmatter, validation errors, IR equivalence.
- `tests/test_core/test_ir_examples.py` — validates all example `.pflow.md` files parse correctly.
- `tests/test_docs/test_example_validation.py` — validates all examples in `examples/` directory.
- `tests/test_core/test_workflow_validator.py` — includes 2 new tests for nested workflow validation fixes.

## Integration Points & Dependencies

### Critical Integration Point: The Parser

Everything flows through `parse_markdown()`. It's called from:

| Caller | What it uses |
|--------|-------------|
| `cli/main.py:_try_load_workflow_from_file()` | `.ir` + normalize_ir() |
| `workflow_manager.py:load()` | `.ir`, `.title`, `.description`, `.metadata` |
| `workflow_manager.py:load_ir()` | `.ir` |
| `workflow_save_service.py:_load_from_file()` | `.ir` |
| `mcp resolver:resolve_workflow()` | `.ir` |
| `mcp execution_service.py:save_workflow()` | `.ir` (for validation/display) + original content (for save) |
| `runtime/workflow_executor.py:_load_workflow_file()` | `.ir` |

### The Save Pipeline (most complex integration)

The save pipeline has a dual data flow that future agents must understand:

```
Content (original markdown) ──→ WorkflowManager.save() ──→ disk (with frontmatter)
         ↓
   parse_markdown()
         ↓
      IR dict ──→ validation ──→ format_save_success() (display)
```

**Parse once, use twice.** The IR is for validation and display. The original content string is for saving. These are separate data flows that must not be confused.

### Shared Store / IR Contract

The parser produces the exact same IR dict shape as JSON. Top-level fields: `nodes`, `edges`, `inputs`, `outputs`. `normalize_ir()` adds `ir_version`. No new IR fields were added. The contract is unchanged.

### Frontmatter Metadata Structure (flat)

Previously: `{"ir": {...}, "description": "...", "rich_metadata": {"execution_count": 8, ...}}`

Now (YAML frontmatter):
```yaml
---
created_at: "..."
updated_at: "..."
version: "1.0.0"
execution_count: 8
last_execution_timestamp: "..."
last_execution_success: true
last_execution_params: {version: "1.0.0"}
search_keywords: [changelog, git]
capabilities: [generate reports]
---
```

All fields are top-level. No `rich_metadata` nesting. Every caller that accessed `metadata["rich_metadata"]` was updated.

## Architectural Decisions & Tradeoffs

### Key Decisions

**1. Custom parser, no markdown library.** The format is a DSL using markdown syntax, not a markdown document. Libraries parse `- key: value` as list items, interfering with YAML parsing. Line numbers are free with line-by-line scanning. ~779 lines of focused code vs. fighting a library's AST.

**2. Content preservation on save.** No IR-to-markdown serialization. Save stores the original markdown string with frontmatter prepended. This means author formatting, comments, and prose survive save/load cycles. The `ir_to_markdown()` utility exists only in tests.

**3. Gating vs. removing planner/repair.** Code preserved, entry points guarded with `if` statements and comments. Pattern: `# GATED: [System] disabled pending markdown format migration (Task 107).` Tests skipped via `pytestmark = pytest.mark.skip(...)`. All code is intact for future re-enablement.

**4. Flat metadata.** The `rich_metadata` wrapper was unnecessary indirection. Flattening required updating ~10 callers but simplified everything. Future code accesses `metadata["execution_count"]` directly.

**5. `- batch:` inline routing.** Initially only `yaml batch` code blocks routed to top-level `node["batch"]`. After writing agent instructions that showed inline `- batch:` for simple cases, discovered the parser needed a fix. Added `batch` pop from `all_params` in `_build_node_dict()`, same pattern as `type` extraction.

### Technical Debt Incurred

1. **Planner/repair gating** — 516 skipped tests. These systems need prompt rewrites for markdown format before re-enabling. The gating is clean (entry-point guards + test skips) but it's a lot of dormant code.

2. **MCP agent instructions** — `pflow://instructions` and `pflow://instructions/sandbox` resources still contain JSON examples. Any agent using the MCP server's built-in instructions will produce invalid workflows. Noted for a future task.

3. **`architecture/guides/json-workflows.md`** — added deprecation notice but didn't delete. Still referenced from some places.

## Unexpected Discoveries

### Gotchas That Actually Bit Us

**G1: `Path.stem` double extension.** `Path("my-workflow.pflow.md").stem` returns `"my-workflow.pflow"`, not `"my-workflow"`. Required `if name.endswith(".pflow"): name = name[:-6]` everywhere. 8 locations in WorkflowManager alone.

**G5: CLI has TWO `.json` checks in `_setup_workflow_execution()`.** One for source file path storage, one for workflow name stripping. Both needed updating. Easy to miss the second one.

**G8: MCP save chain is 6 functions deep.** `workflow_save()` → `ExecutionService.save_workflow()` → detection → `parse_markdown()` → `save_workflow_with_options()` → `WorkflowManager.save()`. Every function passed `ir_dict` + `description` separately. All signatures changed.

**normalize_ir() bug.** `_try_load_workflow_from_registry()` never called `normalize_ir()`. In JSON mode, the metadata wrapper always included `ir_version`, so it was never triggered. With markdown, the parser correctly omits `ir_version`, exposing the missing call. Latent bug revealed by format change.

**Nested workflow validation bugs (pre-existing).** `WorkflowValidator` rejected `type: workflow` as unknown (handled by compiler, not registry). `TemplateValidator` didn't register `output_mapping` outputs. Both pre-existing, never tested.

**Batch workflows fail through MCP (pre-existing).** MCP path skips template validation, which has a side effect of registering batch context variables (`item`, `__index__`). Filed as GitHub issue #79.

### Edge Cases Worth Knowing

- **Frontmatter on authored files**: Parser handles both with and without frontmatter. `metadata` field is `None` for authored files.
- **Single-node workflows**: Edge generation produces `[]` (correct — no edges needed).
- **Non-contiguous YAML params**: Prose between `- key: value` lines works. Items collected independently, joined, parsed as single YAML sequence.
- **Nested fences**: 4+ backtick outer fence wrapping 3-backtick inner content. Parser tracks fence length.
- **YAML type coercion**: `yes`/`no`/`on`/`off` become booleans. Matches old JSON behavior. Agents should quote string values.

## Patterns Established

### The Parse-Once Pattern

When both IR and original content are needed (save flows):
```python
result = parse_markdown(content)
ir = result.ir
normalize_ir(ir)
# Use ir for validation/display
# Use content (original string) for saving
```

Never parse twice. Never serialize IR back to markdown.

### The Gating Pattern

```python
# GATED: Planner disabled pending markdown format migration (Task 107).
# Planner prompts assume JSON workflow format. Re-enable after prompt rewrite.
if some_condition:
    click.echo("Feature temporarily unavailable...")
    return
```

Tests: `pytestmark = pytest.mark.skip(reason="Gated pending markdown format migration (Task 107)")`

### The `ir_to_markdown()` Test Pattern

For any test that previously wrote JSON to disk:
```python
from tests.shared.markdown_utils import ir_to_markdown, write_workflow_file

# Instead of: json.dump(ir_dict, f)
write_workflow_file(ir_dict, tmp_path / "workflow.pflow.md")

# Or for inline content:
content = ir_to_markdown(ir_dict, title="Test Workflow")
```

### Extension Detection Pattern

```python
if path.endswith(".pflow.md"):    # markdown workflow
elif path.endswith(".json"):       # reject with migration message
elif path.endswith(".md"):         # reject with rename suggestion
```

## Breaking Changes

### API/Interface Changes

| Component | Old | New |
|-----------|-----|-----|
| `WorkflowManager.save()` | `save(name, ir_dict, description)` | `save(name, markdown_content, metadata=None)` |
| `save_workflow_with_options()` | `(name, workflow_ir, *, force, description, metadata)` | `(name, markdown_content, *, force, metadata)` |
| `ExecutionService.save_workflow()` | `(workflow, name, description, ...)` | `(workflow, name, force)` |
| MCP `workflow_save` tool | `description` + `generate_metadata` params | Both removed |
| CLI `workflow save` | `--description` required flag | Removed (extracted from H1 prose) |
| `WorkflowManager.load()` return | `{"ir": ..., "rich_metadata": {...}}` | Flat dict with all fields top-level |

### Behavioral Changes

- `.json` workflow files are rejected with "no longer supported" error
- `.md` files (non `.pflow.md`) are rejected with rename suggestion
- Planner invocation shows "temporarily unavailable" message
- `--auto-repair` flag is silently disabled
- `--generate-metadata` flag is silently disabled
- Trace filenames now include workflow name from filename stem (was always generic)

## Future Considerations

### Extension Points

- **Conditional branching (Task 38)**: The parser generates linear edges from document order. When branching is added, explicit edge syntax can be introduced (e.g., `- next: node-a, node-b` or a dedicated `## Flow` section). The parser's state machine can accommodate new syntax without restructuring.
- **Planner re-enablement**: Prompts in `src/pflow/planning/` need rewriting to produce `.pflow.md` instead of JSON. The gating guards mark exact re-enablement points.
- **IR-to-markdown serialization**: Currently test-only (`ir_to_markdown()`). If the planner or repair system needs to produce markdown, the test utility could be promoted to production — but it generates minimal output, not pretty output.

### What Would Break If Naively Modified

1. **Changing `parse_markdown()` return type** — 7 callers depend on `.ir`, `.metadata`, `.description`, `.source` fields.
2. **Adding fields to IR top-level** — `additionalProperties: False` in schema. Parser must not produce unexpected fields.
3. **Modifying `_build_node_dict()` param routing** — `type` and `batch` go to top-level, everything else to `params`. Getting this wrong silently breaks workflows.
4. **Touching `update_metadata()` frontmatter handling** — Must correctly split `---` boundaries, never modify the markdown body.

## AI Agent Guidance

### Quick Start for Related Tasks

1. **Read `src/pflow/core/markdown_parser.py`** first — understand `parse_markdown()`, `MarkdownParseResult`, `MarkdownParseError`, and the state machine.
2. **Read `tests/shared/markdown_utils.py`** — `ir_to_markdown()` is essential for writing tests that involve workflow files.
3. **Read `src/pflow/core/ir_schema.py`** — the IR schema is what the parser targets. `validate_ir()` and `normalize_ir()` are called on every load path.
4. **The IR dict is the universal interface.** Everything downstream of the parser operates on dicts. If you're adding a feature that doesn't touch file I/O, you don't need to know about markdown at all.

### Common Pitfalls

1. **Forgetting `normalize_ir()`** — the parser does NOT add `ir_version`. Every load path must call `normalize_ir()` before validation. Missing this causes `'ir_version' is a required property` errors.
2. **`Path.stem` on `.pflow.md`** — returns `"name.pflow"`, not `"name"`. Always strip the `.pflow` suffix.
3. **Testing with `json.dump()` instead of `write_workflow_file()`** — the CLI rejects `.json` files. All test workflows must be `.pflow.md`.
4. **Accessing `metadata["rich_metadata"]`** — this wrapper no longer exists. All metadata fields are top-level.
5. **MCP save vs. execute paths** — save needs original content preservation; execute only needs IR. The MCP save path does NOT use `resolve_workflow()` because that function discards content.

### Test-First Recommendations

When modifying parser behavior:
- Run `pytest tests/test_core/test_markdown_parser.py -x` first (73 tests, fast)
- Then `pytest tests/test_core/test_ir_examples.py -x` (validates all example files)
- Then `pytest tests/test_docs/test_example_validation.py -x` (validates examples/ directory)

When modifying save/load:
- Run `pytest tests/test_core/test_workflow_manager.py tests/test_execution/test_executor_service.py -x`
- Then `pytest tests/test_cli/test_workflow_save_cli.py tests/test_cli/test_workflow_save.py -x`

---

*Generated from implementation context of Task 107*
