# Task 107: Implementation Plan

> Based on codebase verification against spec. All assumptions verified.
> See `scratchpads/task-107/codebase-verification-report.md` for the reasoning trail.
> This plan is self-contained — the implementing agent should not need the verification report.

---

## Gotchas and Traps

> Read these first. Each one will cause a detour if missed.

### G1. `Path.stem` returns wrong name for `.pflow.md`

`Path("my-workflow.pflow.md").stem` returns `"my-workflow.pflow"`, NOT `"my-workflow"`.
Every place that derives a workflow name from a filename needs:
```python
name = file_path.stem
if name.endswith(".pflow"):
    name = name[:-6]
```

Affected: `WorkflowManager.list_all()`, `load()`, `exists()`, `delete()`, `get_path()`.

### G2. MCP resolver returns a 3-tuple, not 2-tuple

`resolve_workflow()` in `mcp_server/utils/resolver.py` returns `(workflow_ir | None, error | None, source: str)`.
The third element `source` is one of: `"direct"`, `"library"`, `"file"`, or `""` on error.
All callers destructure three values. Don't lose it.

### G3. CLI has a secondary `.json` stripping function

`_try_load_workflow_from_registry()` at `cli/main.py:196-204` strips `.json` from identifiers to find saved workflows:
```python
if identifier.lower().endswith(".json"):
    name = identifier[:-5]
    if wm.exists(name):
        return wm.load_ir(name), "saved"
```
Must update this to strip `.pflow.md` instead. Easy to miss because the primary `_is_path_like()` function gets all the attention.

### G4. CLI checks `source == "json_error"`

`_handle_workflow_not_found()` at `cli/main.py:3466` checks for `source == "json_error"` to decide whether the error was already displayed. Rename this sentinel to `"parse_error"` and update all producers/consumers.

### G5. CLI stores source path with `.json` check

`_setup_workflow_execution()` at `cli/main.py:3384`:
```python
if source == "file" and first_arg.endswith(".json"):
    ctx.obj["source_file_path"] = first_arg
```
Must update to `.pflow.md`. Without this, repair save handlers won't know the original file.

### G6. `format_save_success()` still needs the IR dict

Both CLI (`cli/commands/workflow.py:389`) and MCP (`mcp_server/services/execution_service.py:495`) call:
```python
format_save_success(name=name, saved_path=saved_path, workflow_ir=validated_ir, metadata=metadata)
```
The formatter uses the IR dict to display interface info (inputs/outputs). Even though the save pipeline now passes markdown content instead of IR+description, the formatter still needs the parsed IR. Solution: parse the markdown content once to get both the IR (for the formatter) and the original content (for saving).

---

## Phase 0: Preparation

No new features. Just foundation changes that make everything else possible.

### 0.1 Move PyYAML to main dependencies

**File**: `pyproject.toml`

Add `"PyYAML>=6.0.0"` to `[project] dependencies` (currently only in `[dependency-groups] dev`).
Keep `types-PyYAML` in dev dependencies.
Run `uv lock`.

### 0.2 Gate planner and repair (Decision 26)

Simple if-guards. No code deleted.

**Gating points** (each gets an `if` guard + comment):

1. `cli/main.py` - planner call site (~line 3912-3924): Skip `_execute_with_planner()`, show error message instead
2. `cli/main.py` - `--auto-repair` flag: Disable flag, show deprecation message if used
3. `cli/repair_save_handlers.py` - entry point `save_repaired_workflow()`: Early return with warning
4. `cli/commands/workflow.py` - `--generate-metadata` flag: Disable processing
5. `mcp_server/tools/execution_tools.py` - `generate_metadata` parameter: Ignore if True
6. `planning/context_builder.py` - `_load_single_workflow()` (~line 237): Return None with warning

**Pattern**:
```python
# GATED: Planner disabled pending markdown format migration (Task 107).
# Planner prompts assume JSON workflow format. Re-enable after prompt rewrite.
```

### 0.3 Build test utility `ir_to_markdown()`

**File**: `tests/shared/markdown_utils.py`

Function `ir_to_markdown(ir_dict: dict, title: str = "Test Workflow") -> str` that generates minimal valid `.pflow.md` from an IR dict.

Handles:
- `ir["inputs"]` -> `## Inputs` with `### name` + description + `- key: value` params
- `ir["nodes"]` -> `## Steps` with `### id` + purpose/description + `- type: ...` + params + code blocks
- `ir["outputs"]` -> `## Outputs` with `### name` + description + `- source: ...`
- `params.command` -> `` ```shell command `` code block
- `params.prompt` -> `` ```prompt `` code block
- `params.code` -> `` ```python code `` code block
- `batch` -> `` ```yaml batch `` code block
- Complex `params.stdin` (dict/list) -> `` ```yaml stdin `` code block
- Complex `params.headers` (dict) -> `` ```yaml headers `` code block
- Generates placeholder descriptions for entities that lack them

This utility is test-only infrastructure. Not production code.

**Also create**: `write_workflow_file(ir_dict, path, title="Test Workflow")` helper that writes the markdown to a `.pflow.md` file.

---

## Phase 1: Parser Core

### 1.1 Create `src/pflow/core/markdown_parser.py`

**Return type**:
```python
@dataclass
class MarkdownParseResult:
    ir: dict[str, Any]                    # The workflow IR dict
    title: str | None                     # H1 heading text
    description: str | None               # H1 prose (between # and first ##)
    metadata: dict[str, Any] | None       # Frontmatter (None for authored files)
    source: str                           # Original markdown content
```

**Main function**: `parse_markdown(content: str) -> MarkdownParseResult`

**State machine states**:
1. `START` - looking for frontmatter or H1
2. `FRONTMATTER` - inside `---` delimiters
3. `H1_PROSE` - collecting workflow description
4. `SECTION` - inside a `##` section (Inputs/Steps/Outputs/Unknown)
5. `ENTITY` - inside a `###` entity
6. `CODE_BLOCK` - inside a fenced code block
7. `YAML_CONTINUATION` - collecting indented lines after `- key:`

**Line-by-line processing**:
```
for line_num, line in enumerate(content.splitlines(), 1):
    # Check for code fence boundaries first (highest priority)
    # Then headings (H1, H2, H3)
    # Then `- ` param lines (with continuation tracking)
    # Then prose
```

**Parsing rules** (from spec, verified against codebase):

1. Frontmatter: `---` at line 1 -> extract until closing `---` -> `yaml.safe_load()`
2. H1: `# Title` -> `result.title = "Title"`
3. H1 prose: everything between `#` and first `##` -> `result.description`
4. H2 sections: case-insensitive match for `Inputs`, `Steps`, `Outputs`
   - Unknown sections silently ignored
   - Near-miss warning for `Input`, `Output`, `Step` (missing 's')
5. H3 entities: heading text = entity ID/name
6. Within entity:
   - `- ` lines + indented continuations -> collect as YAML items
   - Code fences -> extract with info string tag
   - Everything else -> prose (description/purpose)
7. Parse collected `- ` lines as YAML sequence -> merge into dict
8. Route params by section type:
   - **Inputs**: all params -> input dict directly (no `params` wrapper). Valid fields: `description`, `required`, `type`, `default`, `stdin`. Schema has `additionalProperties: False`.
   - **Outputs**: all params -> output dict directly (no `params` wrapper). Valid fields: `description`, `type`, `source`. Schema has `additionalProperties: False`.
   - **Nodes**: `type` -> top-level `node["type"]`, prose -> `node["purpose"]`, `yaml batch` code block -> top-level `node["batch"]`, everything else -> `node["params"]`. `params` has `additionalProperties: True`.
9. Generate edges: `[{"from": nodes[i]["id"], "to": nodes[i+1]["id"]} for i in range(len(nodes) - 1)]`
   - **Edge generation is mandatory**. An empty edges array causes `build_execution_order()` to assign all nodes `in_degree=0`, producing non-deterministic ordering.
   - Edge field format: use `"from"` / `"to"` (the compiler's `_wire_nodes()` also accepts `"source"` / `"target"` but `"from"` / `"to"` is the convention in existing JSON workflows).

**Code block tag mapping** (last word = param name, preceding word = language hint):

| Tag | Maps to | Used by |
|-----|---------|---------|
| `shell command` | `params.command` | shell nodes |
| `python code` | `params.code` | code nodes |
| `prompt` | `params.prompt` | llm nodes |
| `markdown prompt` | `params.prompt` | llm nodes |
| `source` | output `source` | outputs |
| `markdown source` | output `source` | outputs |
| `yaml batch` | top-level `batch` (NOT `params.batch`) | batched nodes |
| `yaml stdin` | `params.stdin` | nodes with stdin |
| `yaml headers` | `params.headers` | http nodes |
| `yaml output_schema` | `params.output_schema` | claude-code nodes |

**Top-level IR fields** (the parser produces a subset, `normalize_ir()` adds the rest):
- Parser produces: `nodes`, `edges`, `inputs` (default `{}`), `outputs` (default `{}`)
- `normalize_ir()` adds: `ir_version` ("0.1.0"), and would add `edges` if missing (but parser always provides them)
- Unused defaults (don't produce): `start_node`, `mappings`, `enable_namespacing`, `template_resolution_mode`
- Top-level schema has `additionalProperties: False` — don't produce any extra fields

**Validation at parse time**:
- Missing descriptions (required for all entities)
- Bare code blocks (no info string) -> suggest tag based on node type
- Duplicate params (same key inline + code block)
- Unclosed code fences -> clear error with opening line reference
- YAML syntax errors -> clear error with line range
- Invalid node ID format (must be lowercase, alphanumeric, hyphens/underscores, no spaces)
- Missing `## Steps` section
- Empty `## Steps` (no `###` entities)
- Near-miss section names (`## Input` vs `## Inputs`)
- One code block per param-name tag per entity
- `ast.parse()` on Python code blocks (with offset line numbers)
- `yaml.safe_load()` on YAML config blocks

**Error format**:
```
Node '### analyze' (line 30) is missing a description.

Add a text paragraph between the heading and the parameters:

    ### analyze

    Description of what this node does and why.

    - type: llm
```

### 1.2 Parser tests (`tests/test_core/test_markdown_parser.py`)

Test categories:
1. **Complete workflow parsing** - full example from spec
2. **Section handling** - case-insensitive, optional sections, unknown sections
3. **Entity parsing** - IDs, descriptions, params, code blocks
4. **YAML param parsing** - flat, nested, non-contiguous, comments
5. **Code block parsing** - info strings, nested fences, content extraction
6. **Param routing** - input flat, output flat, node with params wrapper
7. **Edge generation** - correct from document order
8. **Frontmatter** - parsing, stripping, None for authored files
9. **Validation errors** - each rule produces correct error with line number
10. **Edge cases** - empty sections, minimal workflow, large workflows
11. **`ast.parse()`** - Python code block syntax validation
12. **`yaml.safe_load()`** - YAML config block validation
13. **IR equivalence** - parsed markdown produces same IR as manually constructed dict

---

## Phase 2: Integration

### 2.1 CLI integration (`cli/main.py`)

**Changes**:
1. `_is_path_like()` (line 157): Add `.pflow.md` check
   ```python
   identifier.lower().endswith(".json") or identifier.lower().endswith(".pflow.md")
   ```
   Note: Keep `.json` check temporarily for graceful error if someone passes a JSON file.

2. `_try_load_workflow_from_file()` (line 162): Replace JSON loading with markdown parsing
   ```python
   from pflow.core.markdown_parser import parse_markdown

   result = parse_markdown(content)
   workflow_ir = result.ir
   normalize_ir(workflow_ir)
   return workflow_ir, "file"
   ```
   Also store the original content for save operations (see G5).

3. Replace `_show_json_syntax_error()` (line 131) with markdown error display.

4. Update `resolve_workflow()` (line 207) docstring and comments.

5. **[G3]** Update `_try_load_workflow_from_registry()` (line 196): Currently strips `.json` suffix. Update to strip `.pflow.md` suffix instead.

6. **[G4]** Update `_handle_workflow_not_found()` (line 3466): Rename `"json_error"` sentinel to `"parse_error"`.

7. **[G5]** Update `_setup_workflow_execution()` (line 3384): Change `.json` check to `.pflow.md`.

### 2.1b CLI save command (`cli/commands/workflow.py`)

1. Remove `--description` (`required=True`) option from `save_workflow` command (line 350). Description is now extracted from H1 prose.
2. Update `_load_and_normalize_workflow()` (line 220): read file content as text, parse markdown, validate.
3. Pass original markdown content (not IR dict) to `save_workflow_with_options()`.
4. **[G6]** After parsing, pass the IR to `format_save_success()` for display (the formatter needs it for interface info).
5. Update docstring examples (`.json` -> `.pflow.md`).
6. Gate `--generate-metadata` flag (Decision 26 — already in Phase 0.2).

### 2.2 WorkflowManager (`core/workflow_manager.py`)

**Complete rewrite of storage format**:

1. All `.json` -> `.pflow.md` in path construction (8 locations — see G1).

2. **[G1]** Name derivation fix for double extension:
   ```python
   # "my-workflow.pflow.md" -> stem = "my-workflow.pflow" -> strip ".pflow"
   name = file_path.stem
   if name.endswith(".pflow"):
       name = name[:-6]
   ```
   Affected methods: `list_all()` (line 257), and anywhere `file_path.stem` is used as the workflow name.

3. `save()` signature change:
   ```python
   def save(self, name: str, markdown_content: str, metadata: dict | None = None) -> str:
   ```
   - Parse markdown to validate (raises on error)
   - Extract description from H1 prose
   - Create frontmatter YAML with metadata fields
   - Write: `---\n{frontmatter}---\n\n{markdown_body}`

4. `load()` returns a dict with the same shape as the current JSON wrapper for caller compatibility:
   ```python
   {
       "name": name,                    # from filename (strip .pflow suffix)
       "description": result.description,  # from H1 prose
       "ir": result.ir,                 # parsed IR dict
       "created_at": frontmatter.get("created_at"),
       "updated_at": frontmatter.get("updated_at"),
       "version": frontmatter.get("version"),
       # flattened metadata fields:
       "execution_count": frontmatter.get("execution_count", 0),
       "last_execution_timestamp": frontmatter.get("last_execution_timestamp"),
       "last_execution_success": frontmatter.get("last_execution_success"),
       "last_execution_params": frontmatter.get("last_execution_params"),
       # rich_metadata preserved for callers that check it:
       "rich_metadata": {k: v for k, v in frontmatter.items() if k not in TOP_LEVEL_FIELDS},
   }
   ```

5. `load_ir()`: parse markdown, return `result.ir`

6. `list_all()`: glob `*.pflow.md`, apply G1 name derivation

7. `update_metadata()`:
   - Read file content as text
   - Split frontmatter from body (find `---` boundaries)
   - Parse frontmatter with `yaml.safe_load()`
   - Update fields (special-case `execution_count` increment, same as current code)
   - Serialize with `yaml.dump()`
   - Reassemble: `---\n{frontmatter}---\n\n{body}`
   - Atomic write (temp file + `os.replace()`)
   - The markdown body is NEVER touched by metadata updates.

8. Flatten `rich_metadata` into top-level frontmatter fields. Current `rich_metadata` nesting was an artifact of the JSON wrapper.

### 2.3 Workflow save service (`core/workflow_save_service.py`)

1. `_load_from_file()` (line 160): use markdown parser (reads `.pflow.md`, parses, returns IR)
2. `load_and_validate_workflow()` (line 208): handle markdown content/path
3. `save_workflow_with_options()` (line 254) signature change:
   ```python
   def save_workflow_with_options(
       name: str,
       markdown_content: str,  # Was: workflow_ir + description
       *,
       force: bool = False,
       metadata: Optional[dict[str, Any]] = None,
   ) -> Path:
   ```
   - Parses markdown to validate IR (rejects invalid content)
   - Extracts description from H1 prose via `MarkdownParseResult`
   - Passes content + metadata to `WorkflowManager.save()`
4. Remove separate `description` parameter throughout save chain

### 2.4 MCP resolver (`mcp_server/utils/resolver.py`)

**[G2]** Preserve the 3-tuple return: `(workflow_ir | None, error | None, source: str)`.

**String detection for execute/validate** (newline-based):
1. **Dict** -> use as IR directly (source=`"direct"`) — backward compat
2. **String with `\n`** -> raw markdown content -> parse with markdown parser (source=`"content"`)
3. **String ending `.pflow.md`** (single-line) -> file path -> read and parse (source=`"file"`)
4. **Single-line string** -> try as library name (source=`"library"`), then as file path (source=`"file"`)
5. Not found -> suggestions

Update error messages (JSON -> markdown).

### 2.5 MCP save tool (`mcp_server/tools/execution_tools.py` + services)

**Critical insight**: Save needs ORIGINAL markdown content, not just IR dict. The save tool has its own resolution path separate from execute/validate — it cannot use `resolve_workflow()` which discards original content.

1. Remove `description` parameter from tool signature (extracted from H1 prose)
2. Remove `generate_metadata` parameter (gated in Phase 0.2)
3. **Save-specific string detection** in `ExecutionService.save_workflow()`:
   - String with `\n` -> raw markdown content -> parse to validate, save content with frontmatter
   - String ending `.pflow.md` -> file path -> read file, parse to validate, save file content with frontmatter
   - Dict -> ERROR ("Pass markdown content or file path, not an IR dict")
   - Single-line non-path string -> ERROR ("Workflow already saved — use a file path or raw markdown content")
4. **[G6]** Parse markdown once to get both IR (for `format_save_success()` formatter) and original content (for saving). Don't parse twice.
5. Update `save_workflow_with_options()` call to pass `markdown_content` instead of `workflow_ir + description`.

### 2.6 Runtime workflow executor (`runtime/workflow_executor.py`)

1. `_load_workflow_file()` (line 237): use markdown parser instead of `json.load()`
2. Update error messages ("Invalid JSON" -> markdown parse errors)
3. Update type check (line 254): `"Workflow must be a JSON object"` -> appropriate markdown error

### 2.7 Error messages

Update all ~10 locations identified in spec:
- `cli/main.py:131-154` -> replace `_show_json_syntax_error()` with markdown error display
- `ir_schema.py:370-387` -> `_get_output_suggestion()`: update JSON examples to markdown syntax
- `ir_schema.py:481` -> keep as-is (the `validate_ir()` string path uses `json.loads()` but is rarely triggered in production — no production code passes strings)
- `workflow_manager.py:213` -> `json.JSONDecodeError` catch -> markdown parse errors
- `workflow_executor.py:248,254` -> markdown parse errors
- `workflow_validator.py:435-505` -> remove JSON string anti-pattern validation (layer 7 of 7 validation layers). This detected manually-constructed JSON strings — irrelevant with markdown.
- `workflow_save_service.py:182-183` -> markdown parse errors
- `resolver.py:63-64` -> markdown parse errors

### 2.8 Unknown param warnings

During compilation, after template validation:
1. For each node, get `interface["params"]` from registry metadata via `registry.get_nodes_metadata([node_type])` -> `metadata[node_type]["interface"]["params"]`
2. Each param is a dict with `"key"`, `"type"`, `"description"` fields
3. Compare node `params` keys against interface param keys
4. Warn on unknown params with "did you mean?" suggestions using `find_similar_items()` from `core/suggestion_utils.py`
5. Hook into compiler at template validation call site (`compiler.py` ~line 1058-1075, where `TemplateValidator.validate_workflow_templates()` is called)

---

## Phase 3: Examples and Tests

### 3.1 Convert example workflows

Convert all 33 `.json` files to `.pflow.md`:
- Write markdown versions manually (not using test utility — these are documentation)
- Verify IR equivalence by parsing both and comparing dicts
- Delete original `.json` files

Priority order:
1. `examples/core/` (5 files) — used in parameterized tests
2. `examples/invalid/` (4 files -> replaced with markdown invalid examples)
3. `examples/real-workflows/` (4 files) — complex, good integration tests
4. `examples/advanced/` (3 files)
5. Rest (17 files)

### 3.2 Create markdown invalid examples

Replace JSON invalid examples with markdown equivalents:
- `missing-steps.pflow.md` — No `## Steps` section
- `missing-type.pflow.md` — Node without `- type:` param
- `missing-description.pflow.md` — Entity without prose
- `unclosed-fence.pflow.md` — Unclosed code block
- `bare-code-block.pflow.md` — Code block without tag
- `duplicate-param.pflow.md` — Same param inline + code block
- `duplicate-ids.pflow.md` — Two nodes with same `###` heading

Note: Old JSON invalid examples tested JSON-specific errors:
- `missing-version.json` becomes irrelevant — `normalize_ir()` adds `ir_version` automatically
- `bad-edge-ref.json` tested edges referencing non-existent nodes — with markdown, edges are auto-generated from document order, so this specific scenario can't happen. Template references to non-existent nodes are caught by template validation.
- `duplicate-ids.json` and `wrong-types.json` have markdown equivalents above

### 3.3 Update test files (17 files)

For each test file that writes JSON workflow files to disk:
1. Import `ir_to_markdown` from `tests/shared/markdown_utils`
2. Replace `json.dump(workflow, f)` with writing markdown content
3. Change file extensions from `.json` to `.pflow.md`
4. Update CLI invocations to use `.pflow.md` paths
5. Update error message assertions (JSON -> markdown)

**Full list of affected test files**:
```
tests/test_cli/test_main.py (20+ occurrences)
tests/test_cli/test_workflow_output_handling.py
tests/test_cli/test_workflow_output_source_simple.py
tests/test_cli/test_workflow_resolution.py
tests/test_cli/test_repair_save_handlers.py
tests/test_cli/test_json_error_handling.py
tests/test_cli/test_auto_repair_flag.py
tests/test_integration/test_sigpipe_regression.py (8 occurrences)
tests/test_integration/test_metrics_integration.py (10+ occurrences)
tests/test_integration/test_e2e_workflow.py
tests/test_integration/test_workflow_manager_integration.py
tests/test_integration/test_workflow_outputs_namespaced.py
tests/test_integration/test_context_builder_integration.py
tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py
tests/test_runtime/test_workflow_executor/test_workflow_name.py
tests/test_runtime/test_workflow_executor/test_integration.py
tests/test_runtime/test_nested_template_e2e.py
```

Special cases:
- `test_json_error_handling.py` -> rename to `test_parse_error_handling.py`, rewrite for markdown errors
- `test_workflow_resolution.py` -> add `.pflow.md` extension tests, update `.json` stripping tests

### 3.4 Update example validation tests

- `test_example_validation.py`: change `rglob("*.json")` to `rglob("*.pflow.md")`, update parsing from `json.load()` to markdown parser
- `test_ir_examples.py`: update 7 hardcoded paths (e.g., `"invalid/missing-version.json"` -> new markdown invalid examples), update parameterized test file lists

---

## Phase 4: Polish

### 4.1 Quality checks

- `make test` — all tests pass
- `make check` — lint (ruff) and type check (mypy) pass
- Fix any issues

### 4.2 Manual testing

- `uv run pflow examples/core/minimal.pflow.md` — basic execution
- `uv run pflow workflow save examples/real-workflows/generate-changelog/workflow.pflow.md --name test-workflow` -> saves with frontmatter
- `uv run pflow test-workflow` -> loads from saved, executes
- `uv run pflow workflow list` -> shows saved workflows
- `uv run pflow workflow describe test-workflow` -> shows interface

### 4.3 Documentation

- Add `src/pflow/core/CLAUDE.md` entry for `markdown_parser.py`
- Update any code comments referencing JSON workflow files
- Update `tests/shared/README.md` with `markdown_utils` documentation

---

## Critical Flow: Save Pipeline Redesign

The save pipeline is the most complex integration change. Here's the full picture:

### Current save flow (JSON)

```
CLI:  file_path -> json.load() -> IR dict -> validate -> save(name, ir, description)
MCP:  workflow (dict/name/path) -> resolve_workflow() -> IR dict -> validate -> save(name, ir, description)
```

`WorkflowManager.save()` receives: `(name, ir_dict, description)` -> creates metadata wrapper -> `json.dump(wrapper)`

### New save flow (Markdown)

```
CLI:  file_path -> read content -> parse_markdown() -> validate IR -> save(name, markdown_content)
MCP:  workflow (md string or path) -> read/detect -> parse_markdown() -> validate IR -> save(name, markdown_content)
```

`WorkflowManager.save()` receives: `(name, markdown_content)` -> parse to extract description + validate -> prepend frontmatter -> write text

### Key differences

1. **Content preservation**: Save stores ORIGINAL markdown, not serialized IR. Author's formatting, comments, and prose survive save/load cycles.
2. **Description extraction**: No separate `description` parameter. Extracted from H1 prose by the parser.
3. **No IR-to-file serialization**: We never need to convert IR back to markdown. The original content is always preserved.
4. **Frontmatter is additive**: Prepended to original content on save, stripped on load. Body is never modified.

### Callers that need updating

| Caller | Current call | New call |
|--------|-------------|----------|
| `cli/commands/workflow.py:381` | `_save_with_overwrite_check(name, ir, description, metadata, force)` | `_save_with_overwrite_check(name, markdown_content, metadata, force)` |
| `workflow_save_service.py:296` | `manager.save(name, workflow_ir, description, metadata)` | `manager.save(name, markdown_content, metadata)` |
| `mcp_server/services/execution_service.py:487-493` | `save_workflow_with_options(name, ir, description, force, metadata)` | `save_workflow_with_options(name, markdown_content, force=force, metadata=metadata)` |

### update_metadata() redesign

Current: `load(name)` -> full JSON dict -> update fields -> `json.dump(entire_thing)`

New:
1. Read file content as text
2. Split: find `---` boundaries -> frontmatter YAML + markdown body
3. `yaml.safe_load(frontmatter)` -> update dict fields
4. `yaml.dump(updated_frontmatter)` -> reassemble with body
5. Atomic write

The markdown body is NEVER touched by metadata updates.

### Frontmatter fields (flattened from rich_metadata)

```yaml
---
created_at: "2026-01-14T15:43:57.425006+00:00"
updated_at: "2026-01-14T22:03:06.823530+00:00"
version: "1.0.0"
execution_count: 8
last_execution_timestamp: "2026-01-14T23:03:06.823108"
last_execution_success: true
last_execution_params:
  version: "1.0.0"
keywords:
  - changelog
  - git
capabilities:
  - generate reports
---
```

All fields that were in `rich_metadata` move to top-level frontmatter.

---

## Implementation Order (Critical Path)

```
Phase 0.1 (PyYAML dep)
Phase 0.2 (Gate planner/repair)     } Can be done in parallel
Phase 0.3 (Test utility)            }

Phase 1.1 (Parser core)             } Sequential - parser first
Phase 1.2 (Parser tests)            } then tests

Phase 2.1 (CLI integration)         }
Phase 2.1b (CLI save command)       }
Phase 2.2 (WorkflowManager)         } Sequential - CLI first (primary entry),
Phase 2.3 (Save service)            } then manager, then others
Phase 2.4 (MCP resolver)            }
Phase 2.5 (MCP save tool)           } Can parallel with 2.4
Phase 2.6 (Runtime executor)        } Can parallel with 2.4
Phase 2.7 (Error messages)          } Interleaved with above
Phase 2.8 (Unknown param warnings)  } After all integration done

Phase 3.1 (Convert examples)        }
Phase 3.2 (Invalid examples)        } Can be parallelized
Phase 3.3 (Update test files)       }
Phase 3.4 (Update validation tests) }

Phase 4.1 (make test + make check)
Phase 4.2 (Manual testing)
Phase 4.3 (Documentation)
```

---

## Files Created/Modified Summary

### New files
- `src/pflow/core/markdown_parser.py` (~300-400 lines)
- `tests/test_core/test_markdown_parser.py` (~500-700 lines)
- `tests/shared/markdown_utils.py` (~100-150 lines)
- `examples/invalid/*.pflow.md` (7 new files)

### Modified files (major changes)
- `src/pflow/core/workflow_manager.py` (complete storage format rewrite)
- `src/pflow/core/workflow_save_service.py` (markdown loading, save signature change)
- `src/pflow/cli/main.py` (parser integration, gating, error messages)
- `src/pflow/cli/commands/workflow.py` (remove --description, save flow change)
- `src/pflow/mcp_server/utils/resolver.py` (markdown loading, content detection)
- `src/pflow/mcp_server/tools/execution_tools.py` (parameter changes)
- `src/pflow/mcp_server/services/execution_service.py` (save flow change)
- `src/pflow/runtime/workflow_executor.py` (markdown loading)

### Modified files (minor changes)
- `pyproject.toml` (PyYAML dependency)
- `src/pflow/core/ir_schema.py` (error message examples)
- `src/pflow/core/workflow_validator.py` (remove JSON anti-pattern layer 7)
- `src/pflow/cli/repair_save_handlers.py` (gated)
- `src/pflow/planning/context_builder.py` (gated)
- `src/pflow/runtime/compiler.py` (unknown param warnings)
- `src/pflow/runtime/template_validator.py` (unknown param warnings)

### Converted files
- 33 `.json` -> `.pflow.md` in `examples/`
- 4 old invalid examples deleted, 7 new ones created

### Updated test files
- 17 test files updated to write `.pflow.md` instead of `.json`
- 2 example validation test files updated
- 1 test file renamed (`test_json_error_handling.py` -> `test_parse_error_handling.py`)
