# Task 107: Codebase Verification Report

> Verified every assumption in `task-107.md` and `format-specification.md` against the actual codebase.
> This document captures contradictions, gaps, and the resulting implementation plan.

---

## Contradictions and Wrong Assumptions

### 1. Context builder function name mismatch

**Spec says**: `_try_load_workflow()` at `context_builder.py:255`
**Actual**: Function is `_load_single_workflow()` at lines 237-275.

**Impact**: Low. The function exists and does what the spec describes. Just a naming error in the spec.

### 2. MCP resolver returns 3-tuple, not 2-tuple

**Spec describes**: `resolve_workflow()` returning `(workflow_ir, error)`
**Actual**: Returns `(workflow_ir | None, error | None, source: str)` where source is `"direct"`, `"library"`, `"file"`, or `""`.

**Impact**: Medium. The third return value must be preserved in the updated implementation.

### 3. Metadata structure: flat frontmatter vs nested `rich_metadata`

**Spec shows frontmatter with flat structure**:
```yaml
execution_count: 8
last_execution_timestamp: "..."
last_execution_success: true
last_execution_params: {...}
```

**Actual current structure**: These fields are nested under `rich_metadata`:
```python
wrapper = {
    "description": "...",
    "ir": {...},
    "created_at": "...",
    "updated_at": "...",
    "version": "1.0.0",
    "rich_metadata": {
        "execution_count": 8,
        "last_execution_timestamp": "...",
        ...
    }
}
```

**Impact**: Medium. Decision needed: flatten `rich_metadata` into frontmatter top-level, or preserve the nesting? Flattening is cleaner for YAML frontmatter and this is a good opportunity to simplify.

**Recommendation**: Flatten. The `rich_metadata` wrapper was an artifact of the JSON format. Frontmatter should be flat:
```yaml
---
created_at: "..."
updated_at: "..."
version: "1.0.0"
execution_count: 8
last_execution_timestamp: "..."
last_execution_success: true
last_execution_params:
  version: "1.0.0"
---
```

### 4. 17 test files write JSON workflows to disk (CRITICAL GAP)

**Spec says**: "~15-20 test files load workflows from .json files on disk (need conversion). Mostly in test_cli/."
**Actual**: 17 test files construct IR dicts in Python, write them as JSON files with `json.dump()`, then invoke the CLI or runtime with those file paths.

**The problem**: If JSON is no longer accepted as input, every one of these tests breaks. They can't write markdown files because there's no IR-to-markdown serializer, and the spec explicitly rules that out of scope.

**Files affected**:
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

**Solution**: Build a minimal test utility `ir_to_markdown(ir_dict) -> str` that generates valid `.pflow.md` content from an IR dict. This is NOT a production serializer - it's a test helper that produces minimal valid markdown. Place it in `tests/shared/markdown_utils.py`.

The utility needs to:
- Generate `# Workflow` title
- Generate `## Inputs` from `ir["inputs"]`
- Generate `## Steps` with `### node-id` for each node
- Generate `## Outputs` from `ir["outputs"]`
- Map `params.command` to `shell command` code blocks
- Map `params.prompt` to `prompt` code blocks
- Map `params.code` to `python code` code blocks
- Map `batch` to `yaml batch` code blocks
- Generate edges from node order
- Add placeholder descriptions ("Step description." for each entity)

### 5. PyYAML must move to main dependencies

**Current**: PyYAML is only in `[dependency-groups] dev`
**Needed**: Must be in `[project] dependencies` for runtime markdown parsing.

**Impact**: Low. Simple `pyproject.toml` change.

### 6. `validate_ir()` accepts strings with `json.loads()`

**Location**: `ir_schema.py:479-481`
```python
if isinstance(data, str):
    data = json.loads(data)
```

**Impact**: Low. This path is rarely used in production. No change needed - the parser produces dicts, not strings.

### 7. Line number references in spec are approximate

Most line numbers in the spec are close but not exact. This is expected given the codebase evolves. The functions exist at approximately the stated locations.

**Impact**: None. Line numbers are for navigation guidance, not precision.

### 8. MCP save tool: `description` is currently required

**Current**: `description: str = Field(...)` (required parameter)
**Spec says**: Remove it (extract from H1 prose).

**Impact**: Low (no users), but needs careful implementation. The MCP tool signature changes and agent instructions would need updating.

### 9. `_wire_nodes()` supports both edge formats

**Spec uses**: `{"from": node_a, "to": node_b}`
**Actual**: Supports BOTH `from`/`to` AND `source`/`target` field names.

**Impact**: None. Parser should use `{"from": ..., "to": ...}` consistently, which is what the spec already shows.

### 10. Repair save handlers hardcode `.json` extension

**Location**: `repair_save_handlers.py` creates `.repaired.json` files.
**Impact**: None - repair is being gated (Decision 26).

---

## Gaps Not Addressed in Spec

### Gap 1: `test_json_error_handling.py` becomes obsolete

This test file specifically tests JSON parse error handling. With markdown format, the entire file needs rewriting to test markdown parse errors instead.

### Gap 2: `test_workflow_resolution.py` tests `.json` extension detection

Tests for `_is_path_like()` check `.json` extension. Need new tests for `.pflow.md`.

### Gap 3: Agent instructions (`pflow instructions`) reference JSON

The spec mentions this is out of scope, but `pflow instructions usage` and `pflow instructions create` output JSON workflow examples. These will be confusing with the new format. At minimum, gate the `create` instruction with a note about markdown format.

### Gap 4: `WorkflowManager._create_metadata_wrapper()` returns a dict

The current save pipeline creates a metadata dict wrapper and `json.dump()`s it. The new pipeline needs to:
1. Accept markdown content string (not IR dict)
2. Prepend YAML frontmatter
3. Write as text

This is a complete rewrite of the save path, not just a format change.

### Gap 5: `update_metadata()` currently loads full JSON, updates dict, saves

New approach: read file -> split frontmatter from body -> parse frontmatter YAML -> update fields -> serialize YAML -> reassemble -> write. The spec describes this correctly but it's a non-trivial implementation.

### Gap 6: `list_all()` derives name from `file_path.stem`

With `.pflow.md` extension, `Path("my-workflow.pflow.md").stem` returns `"my-workflow.pflow"`, not `"my-workflow"`. Need to strip `.pflow` suffix too.

### Gap 7: Error messages in `_get_output_suggestion()` show JSON syntax

The spec covers this (Decision 23) but doesn't provide the exact replacement text. Need to write markdown example text.

### Gap 8: `test_example_validation.py` and `test_ir_examples.py`

These test files scan `examples/` for `.json` files. After conversion to `.pflow.md`, they need:
- Updated glob patterns
- Markdown parsing instead of JSON parsing
- Updated hardcoded file paths (7 in `test_ir_examples.py`)

### Gap 9: Invalid examples need markdown equivalents

Current invalid examples test JSON-specific errors. New markdown-specific invalid examples needed:
- `missing-version.json` -> becomes irrelevant (normalize_ir adds it)
- `duplicate-ids.json` -> `duplicate-ids.pflow.md` (same concept, markdown syntax)
- `bad-edge-ref.json` -> `bad-edge-ref.pflow.md` (edges from doc order, so this becomes "references non-existent node in template")
- `wrong-types.json` -> `wrong-types.pflow.md` (adapted for markdown)

Wait - `bad-edge-ref.json` tests edges referencing non-existent nodes. With markdown format, edges are auto-generated from document order, so this test case doesn't apply. Need different invalid cases:
- Missing `## Steps` section
- Node without `- type:` param
- Missing descriptions
- Unclosed code fences
- Bare code blocks (no tag)
- YAML syntax errors in params
- Duplicate params (inline + code block)
- Invalid node ID format

### 11. CLI stores `source_file_path` with `.json` check

**Location**: `cli/main.py:3384`
```python
if source == "file" and first_arg.endswith(".json"):
    ctx.obj["source_file_path"] = first_arg
```

**Impact**: Must update to check `.pflow.md` instead. Used by repair save handlers to determine original file path.

### 12. `_try_load_workflow_from_registry()` strips `.json` suffix

**Location**: `cli/main.py:196-204`
```python
if identifier.lower().endswith(".json"):
    name = identifier[:-5]
    if wm.exists(name):
        return wm.load_ir(name), "saved"
```

**Impact**: Must update to strip `.pflow.md` suffix instead (or in addition).

### 13. `_handle_workflow_not_found()` checks `source == "json_error"`

**Location**: `cli/main.py:3466`
**Impact**: Rename to `"parse_error"` throughout.

### 14. MCP save uses `resolve_workflow()` then passes IR dict to save

**Location**: `mcp_server/services/execution_service.py:421`
```python
workflow_ir, error, source = resolve_workflow(workflow)
# ... then passes workflow_ir to save_workflow_with_options()
```

**Impact**: Critical. The save flow currently loses the original content. With markdown format, save needs the ORIGINAL markdown content, not the IR dict. The MCP save flow needs a separate resolution path that preserves content.

### 15. CLI save command has `--description` as required

**Location**: `cli/commands/workflow.py:350`
```python
@click.option("--description", required=True, ...)
```

**Impact**: Remove this option. Description extracted from H1 prose. This changes the CLI interface.

### 16. `format_save_success()` formatter takes `workflow_ir` param

**Location**: `cli/commands/workflow.py:389` and `mcp_server/services/execution_service.py:495-500`

Both CLI and MCP call `format_save_success(name, saved_path, workflow_ir, metadata)`. The formatter may need updating if it uses IR to display interface info.

---

## Verified Facts (Spec Is Correct)

- normalize_ir() adds ir_version, edges, renames parameters->params: CONFIRMED
- Top-level IR fields with additionalProperties: False: CONFIRMED (9 fields)
- Node schema: id, type required; purpose, params, batch optional; additionalProperties: False: CONFIRMED
- Input schema: description, required, type, default, stdin; additionalProperties: False: CONFIRMED
- Output schema: description, type, source; additionalProperties: False: CONFIRMED
- Batch schema: items required, 7 fields total, additionalProperties: False: CONFIRMED
- params has additionalProperties: True: CONFIRMED
- purpose field unused at runtime: CONFIRMED
- All existing workflows are linear: CONFIRMED (via prior research)
- _wire_nodes() at compiler.py uses >> operator: CONFIRMED
- _get_start_node() uses first node in array: CONFIRMED
- Template validator loads registry interface metadata: CONFIRMED
- 7 validation layers in workflow_validator.py: CONFIRMED
- JSON string anti-pattern validation at layer 7: CONFIRMED
- Atomic file writes in WorkflowManager: CONFIRMED
- Workflow name derived from filename, not stored in file: CONFIRMED
- Planner entry point exists and can be gated: CONFIRMED
- repair is controlled by enable_repair flag: CONFIRMED
- No production code passes strings to _parse_ir_input(): CONFIRMED (only tests)

---

## Implementation Plan

### Phase 0: Preparation (foundation changes, no new code)

**0.1 Move PyYAML to main dependencies**
- Add `"PyYAML>=6.0.0"` to `[project] dependencies` in `pyproject.toml`
- Keep `types-PyYAML` in dev dependencies
- Run `uv lock` to update lockfile

**0.2 Gate planner and repair systems (Decision 26)**
- Gate planner at `cli/main.py` `_execute_with_planner()` call site
- Gate `--auto-repair` flag processing
- Gate repair save handlers
- Gate `--generate-metadata` in CLI and MCP
- Gate context builder `_load_single_workflow()`
- Pattern: `# GATED: [System] disabled pending markdown format migration (Task 107).`
- All code preserved, just guarded with if-statements

**0.3 Build test utility `ir_to_markdown()`**
- Create `tests/shared/markdown_utils.py`
- Function: `ir_to_markdown(ir_dict: dict) -> str`
- Generates minimal valid `.pflow.md` content from IR dict
- Handles: nodes, inputs, outputs, edges (implicit from order), batch, code blocks
- This is critical infrastructure for Phase 3

### Phase 1: Parser Core

**1.1 Create markdown parser module**
- `src/pflow/core/markdown_parser.py`
- `MarkdownParseResult` dataclass (ir, title, description, metadata, source)
- `parse_markdown(content: str) -> MarkdownParseResult`
- Line-by-line state machine
- States: top-level, h1-prose, section (inputs/steps/outputs), entity, code-block, yaml-continuation

**1.2 Parser features (in order)**
1. Frontmatter extraction (saved workflows)
2. H1 title and description extraction
3. H2 section splitting (Inputs/Steps/Outputs, case-insensitive)
4. H3 entity splitting within sections
5. `- key: value` YAML param collection with indented continuations
6. Code block extraction with info string parsing (language + param_name)
7. Prose collection (everything that's not params or code blocks)
8. Param routing per section type (inputs flat, outputs flat, nodes with params wrapper)
9. `type` and `batch` extraction to top-level for nodes
10. Edge generation from document order
11. `ast.parse()` on Python code blocks
12. `yaml.safe_load()` on YAML config blocks
13. Line number tracking for all elements

**1.3 Parser validation (markdown-specific)**
- Missing descriptions on entities
- Bare code blocks (no info string tag)
- Duplicate params (inline + code block)
- Unclosed code fences
- YAML syntax errors in params
- Invalid node IDs (spaces, uppercase)
- Missing `## Steps` section
- Empty `## Steps` (no nodes)
- Near-miss section warnings (`## Input` vs `## Inputs`)
- One code block per param-name tag per entity

**1.4 Parser tests**
- Test with complete example workflow from spec
- Test each section type independently
- Test edge cases: nested fences, non-contiguous params, YAML nesting
- Test error messages include line numbers
- Test frontmatter parsing
- Test param routing per section type
- Test `ast.parse()` on Python code blocks
- Test all validation rules

### Phase 2: Integration

**2.1 CLI integration (`cli/main.py`)**
- Update `_is_path_like()` to check `.pflow.md` extension
- Rewrite `_try_load_workflow_from_file()` to use markdown parser
- Replace `_show_json_syntax_error()` with markdown-native error display
- Update `resolve_workflow()` to handle `.pflow.md` files

**2.2 WorkflowManager rewrite (`core/workflow_manager.py`)**
- Change all `.json` references to `.pflow.md`
- Fix `list_all()` glob: `*.pflow.md`
- Fix name derivation: strip `.pflow.md` not just `.json` (handle `stem` returning `name.pflow`)
- Rewrite `save()`: accept markdown content string, prepend YAML frontmatter
- Rewrite `load()`: parse `.pflow.md` with frontmatter, return metadata + IR
- Rewrite `load_ir()`: parse `.pflow.md`, return just IR
- Rewrite `update_metadata()`: split frontmatter/body, update frontmatter YAML, reassemble
- Flatten `rich_metadata` into top-level frontmatter fields
- Remove `_create_metadata_wrapper()` (replaced by frontmatter generation)
- Preserve `update_ir()` but mark as unused (gated repair was its only caller)
- Keep atomic write pattern (temp file + os.replace)

**2.3 Workflow save service (`core/workflow_save_service.py`)**
- Rewrite `_load_from_file()` to use markdown parser
- Update `load_and_validate_workflow()` for markdown content
- Update `save_workflow_with_options()` to pass markdown content to WorkflowManager
- Remove `--description` parameter handling (extracted from content)

**2.4 MCP resolver (`mcp_server/utils/resolver.py`)**
- Update file loading to use markdown parser
- Add raw markdown content detection (starts with `#` or `---`)
- Preserve 3-tuple return value
- Update error messages

**2.5 MCP save tool (`mcp_server/tools/execution_tools.py`)**
- Remove `description` parameter
- Remove `generate_metadata` parameter (gated)
- Accept raw markdown content string or file path
- Update MCP service layer accordingly

**2.6 Runtime workflow executor (`runtime/workflow_executor.py`)**
- Update `_load_workflow_file()` to use markdown parser
- Update error messages

**2.7 Error messages (~10-12 locations)**
- Replace "Invalid JSON" with markdown-specific errors
- Update `_get_output_suggestion()` to show markdown examples
- Remove JSON string anti-pattern validation (layer 7)

**2.8 Unknown param warnings (new validation)**
- During compilation (template validation phase)
- Compare node params against `interface["params"]` keys from registry
- Warn on unknown params with "did you mean?" suggestions
- Hook into existing template validation call site

### Phase 3: Examples and Tests

**3.1 Convert example workflows**
- Convert all 33 `.json` files in `examples/` to `.pflow.md`
- Delete original `.json` files
- Verify each converted workflow produces identical IR
- Special attention: complex workflows (generate-changelog, webpage-to-markdown)

**3.2 Create new invalid examples**
- `examples/invalid/missing-steps.pflow.md` - No `## Steps` section
- `examples/invalid/missing-type.pflow.md` - Node without `- type:` param
- `examples/invalid/missing-description.pflow.md` - Entity without prose
- `examples/invalid/unclosed-fence.pflow.md` - Unclosed code block
- `examples/invalid/bare-code-block.pflow.md` - Code block without tag
- `examples/invalid/duplicate-param.pflow.md` - Param defined inline + code block
- `examples/invalid/yaml-syntax-error.pflow.md` - Bad YAML in params
- `examples/invalid/duplicate-ids.pflow.md` - Two nodes with same heading
- Remove old JSON invalid examples

**3.3 Update test files that load from disk**
- Update all 17 test files to write `.pflow.md` files using `ir_to_markdown()` utility
- Update file extension references
- Update error message assertions (JSON -> markdown)
- Special handling for `test_json_error_handling.py` -> rename/rewrite as `test_parse_error_handling.py`

**3.4 Update example validation tests**
- `test_example_validation.py`: change glob pattern, add markdown parsing
- `test_ir_examples.py`: update 7 hardcoded paths, update parameterized lists

### Phase 4: Polish

**4.1 End-to-end testing**
- Run `make test` - all tests pass
- Run `make check` - lint and type checks pass
- Manual test: `uv run pflow workflow.pflow.md` works
- Manual test: save and load workflows
- Manual test: MCP tools work with markdown content

**4.2 Documentation updates**
- Update `CLAUDE.md` project structure if needed
- Update any in-code comments referencing JSON workflow files
- Add `CLAUDE.md` to `src/pflow/core/` covering the new parser

---

## Risk Assessment

### High Risk
- **Test utility `ir_to_markdown()`**: If this doesn't handle edge cases, 17 test files break. Must be robust.
- **WorkflowManager rewrite**: Complete rewrite of save/load/update cycle. Many callers depend on it.
- **YAML continuation parsing**: Complex state tracking for indented YAML continuations under `- ` items.

### Medium Risk
- **Frontmatter metadata structure change**: Flattening `rich_metadata` changes the data model. All metadata consumers must be updated.
- **MCP resolver content detection**: Distinguishing raw markdown content from workflow names (both are strings).
- **Example conversion accuracy**: 33 workflows must produce identical IR after conversion.

### Low Risk
- **Gating planner/repair**: Simple if-guards with comments.
- **PyYAML dependency move**: Trivial pyproject.toml change.
- **Error message updates**: Find-and-replace style changes.
- **Unknown param warnings**: Additive feature, no existing behavior changed.

---

## Decision Points for User

### Decision 1: Flatten `rich_metadata` into frontmatter? (Importance: 2/5)

**Option A (Recommended)**: Flatten - all metadata fields at top level of frontmatter
- Pro: Cleaner YAML, simpler parsing, no nested wrapper
- Pro: Fresh start (no users with existing metadata)
- Con: Code that reads `rich_metadata` needs updating

**Option B**: Preserve nesting - `rich_metadata:` as a nested YAML key
- Pro: Less code change in metadata consumers
- Con: Unnecessary nesting in frontmatter

**Recommendation and approval by user**: Flatten. Zero users, clean slate.

**Approved by user: Option A**

### Decision 2: `ir_to_markdown()` test utility scope (Importance: 3/5)

**Option A (Recommended)**: Build a robust test utility that handles all node types
- Pro: 17 test files can be updated mechanically
- Pro: Future tests can write markdown easily
- Con: More upfront work (~100-150 lines)

**Option B**: Hand-write markdown strings in each test
- Pro: No utility code to maintain
- Con: Extremely tedious, error-prone, 50+ manual conversions

**Recommendation and approval by user**: Option A. The utility pays for itself immediately.


### Decision 3: MCP content detection heuristic (Importance: 2/5)

When MCP receives a string, how to distinguish "raw markdown content" from "workflow name" from "file path"?

**User insight**: Frontmatter won't be in raw agent content. H1 is optional. File paths end with `.pflow.md`. Names/paths are always single-line.

**Approved approach**: Use newline detection + extension check:

1. **Dict** -> use as IR directly (backward compat for execute/validate)
2. **String with newlines** (`\n` in string) -> raw markdown content -> parse
3. **String ending with `.pflow.md`** (single-line) -> file path -> read and parse
4. **Single-line string** -> try as library name, then try as file path

This is robust because:
- Library names can never contain newlines (validated as lowercase-hyphens-only)
- File paths are always single-line
- Raw markdown content will always have newlines (minimum: heading + section + node)
- `.pflow.md` extension is unambiguous

**Critical save flow implication**: The save operation needs the ORIGINAL markdown content, not just the IR dict. This means `resolve_workflow()` for save needs to return content alongside IR. Or better: the save tool should have its own resolution path that preserves original content.

**Save tool detection for MCP**:
- String with newlines -> raw markdown content (parse to validate, save content with frontmatter)
- String ending with `.pflow.md` -> file path (read file, parse to validate, save file content with frontmatter)
- Dict -> ERROR for save ("Pass markdown content or file path, not IR dict")
- Single-line string (library name) -> not applicable for save (already saved)

**Execute/validate tool detection**: Same as above but dict is OK (just parse to IR).