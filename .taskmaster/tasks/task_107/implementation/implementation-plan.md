# Task 107: Implementation Plan (v2)

> Self-contained plan. The implementing agent needs only this file and `format-specification.md`.
> All contradictions from v1 resolved. All codebase assumptions verified. All ambiguities settled.

---

## Settled Decisions

These were ambiguities or contradictions in the previous plan version. All resolved.

| # | Decision | Resolution |
|---|----------|------------|
| D1 | Parser error type | Custom `MarkdownParseError(ValueError)` with `line` and `suggestion` fields. Existing `except ValueError` catches still work. |
| D2 | Planner gated UX | Show: `"Natural language workflow generation is temporarily unavailable. Provide a workflow file (.pflow.md) or saved workflow name instead. Example: pflow ./my-workflow.pflow.md"` |
| D3 | Unknown param warning location | Layer 8 in `WorkflowValidator.validate()` (not compiler). Benefits `--validate-only` and MCP validation. Validator already accepts optional `registry` parameter. |
| D4 | Save() signature | `save(name, markdown_content, metadata=None)`. No `description` parameter — it's embedded in the markdown content. Save trusts the caller (pre-validated). Zero parsing in save. |
| D5 | Node ID regex | `^[a-z][a-z0-9_-]*$` — starts with lowercase letter, then letters/digits/hyphens/underscores. |
| D6 | Prose joining | Consecutive prose lines joined with `\n`. Groups separated by blank lines/params/code blocks joined with `\n\n`. Final result stripped. |
| D7 | `- ` without key:value | Error after YAML parse: validate each item is a dict. If not: `"Line 15: '- This is just a note' is not a valid parameter. Use * for documentation bullets."` |
| D8 | rich_metadata | Flatten into top-level frontmatter. Update ~6 callers that access `metadata["rich_metadata"]`. |
| D9 | Planner/repair tests | Gate with `pytest.mark.skip(reason="Gated pending markdown format migration (Task 107)")`. |
| D10 | Agent instructions | Update as Phase 5 (collaborative with user). |
| D11 | ir_to_markdown() | Robust test utility in `tests/shared/markdown_utils.py`. Test-only, not production. |
| D12 | MCP content detection | Newline = content, `.pflow.md` suffix = file path, single-line = library name. Dict OK for execute/validate, ERROR for save. |
| D13 | YAML block scalars | Continuation rule (indented lines after `- key:`) naturally captures `|` and `>` block scalars. Test explicitly. |
| D14 | Frontmatter YAML roundtrip | Use `yaml.dump(data, default_flow_style=False, sort_keys=False)`. Accept minor formatting drift on repeated updates. Not a functional issue. |

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

Affected: `WorkflowManager.list_all()`, `load()`, `exists()`, `delete()`, `get_path()` — **8 locations** with hardcoded `.json`.

### G2. MCP resolver returns a 3-tuple, not 2-tuple

`resolve_workflow()` in `mcp_server/utils/resolver.py` returns `(workflow_ir | None, error | None, source: str)`.
The third element `source` is one of: `"direct"`, `"library"`, `"file"`, `"content"`, or `""` on error.
All callers destructure three values. Don't lose it.

### G3. CLI has a secondary `.json` stripping function

`_try_load_workflow_from_registry()` at `cli/main.py:196-204` strips `.json` from identifiers:
```python
if identifier.lower().endswith(".json"):
    name = identifier[:-5]
```
Must update to strip `.pflow.md` instead.

### G4. CLI checks `source == "json_error"`

`_handle_workflow_not_found()` at `cli/main.py:~3466` checks for `source == "json_error"`. Rename to `"parse_error"` and update all producers/consumers.

### G5. CLI stores source path with TWO `.json` checks

`_setup_workflow_execution()` at `cli/main.py:~3384`:
```python
# Check 1: source file path storage
if source == "file" and first_arg.endswith(".json"):
    ctx.obj["source_file_path"] = first_arg

# Check 2: workflow name stripping (lines ~3387-3389)
workflow_name = first_arg.replace(".json", "") if first_arg.endswith(".json") else first_arg
```
Both must update to `.pflow.md`.

### G6. `is_likely_workflow_name()` checks `.json`

At `cli/main.py:~3574`:
```python
text.lower().endswith(".json")
```
Must update to also check `.pflow.md`.

### G7. `format_save_success()` needs the IR dict

Both CLI and MCP call `format_save_success(name, saved_path, workflow_ir, metadata)`. The formatter uses IR to display interface info (inputs/outputs). Save pipeline passes markdown content, but the formatter still needs the parsed IR. Solution: callers parse once, keep both the IR (for formatter) and original content (for save).

### G8. MCP save chain is 6 functions deep

The save flow isn't just the resolver — it's:
```
workflow_save() → ExecutionService.save_workflow() → _load_and_validate_workflow_for_save()
  → resolve_workflow() → load_and_validate_workflow() → save_workflow_with_options()
    → WorkflowManager.save()
```
Every function passes IR dicts and a separate `description` string. ALL need signature changes.

### G9. `rich_metadata` callers to update

These callers access `metadata["rich_metadata"]` and must change to top-level access:

| File | Access Pattern | New Pattern |
|------|---------------|-------------|
| `execution/formatters/workflow_describe_formatter.py:56` | `metadata.get("rich_metadata", {})` | Direct field access on metadata |
| `execution/formatters/discovery_formatter.py:102` | `workflow["rich_metadata"]` | Direct field access |
| `execution/formatters/history_formatter.py:23-54` | Reads `execution_count`, `last_execution_timestamp`, etc. | Same fields, different nesting |
| `planning/context_builder.py:451-483` | Reads `description`, `search_keywords`, `capabilities` | Direct field access |
| `cli/main.py:1204-1221` | Constructs `rich_metadata` dict for save | Pass as flat `metadata` |
| `cli/main.py:1273-1286` | Same pattern, second occurrence | Same fix |
| `core/workflow_manager.py:323-334` | `update_metadata()` writes to `rich_metadata` | Write to top-level frontmatter |

---

## Phase 0: Preparation

No new features. Foundation changes that make everything else possible.

### 0.1 Move PyYAML to main dependencies

**File**: `pyproject.toml`

Add `"PyYAML>=6.0.0"` to `[project] dependencies` (currently only in `[dependency-groups] dev`).
Keep `types-PyYAML` in dev dependencies.
Run `uv lock`.

### 0.2 Gate planner and repair (Decision 26)

Simple if-guards. No code deleted.

**Production gating points** (each gets an `if` guard + comment):

1. `cli/main.py` ~line 3922: Skip `_execute_with_planner()`, show error message (D2)
2. `cli/main.py` `--auto-repair` flag (~line 3759): Show deprecation message if used
3. `cli/repair_save_handlers.py:14` `save_repaired_workflow()`: Early return with warning
4. `cli/commands/workflow.py` `--generate-metadata` flag: Disable processing
5. `mcp_server/tools/execution_tools.py` `generate_metadata` parameter: Ignore if True
6. `planning/context_builder.py` `_load_single_workflow()` (~line 237): Return None with warning

**Test gating** (D9):

7. `tests/test_planning/` — all test files: `@pytest.mark.skip(reason="Gated pending markdown format migration (Task 107)")`
8. `tests/test_cli/test_repair_save_handlers.py` — skip
9. `tests/test_cli/test_auto_repair_flag.py` — skip
10. `tests/test_integration/test_context_builder_integration.py` — skip (uses planner context builder)

**Pattern**:
```python
# GATED: Planner disabled pending markdown format migration (Task 107).
# Planner prompts assume JSON workflow format. Re-enable after prompt rewrite.
```

### 0.3 Build test utility `ir_to_markdown()`

**File**: `tests/shared/markdown_utils.py`

Function `ir_to_markdown(ir_dict: dict, title: str = "Test Workflow") -> str` that generates minimal valid `.pflow.md` from an IR dict.

**Serialization rules** (D11):
- `str`, `int`, `float`, `bool` params: inline `- key: value`
- `params.command`: ```` ```shell command ```` code block
- `params.prompt`: ```` ```prompt ```` code block
- `params.code`: ```` ```python code ```` code block
- `batch` dict: ```` ```yaml batch ```` code block
- Complex `params.stdin` (dict/list): ```` ```yaml stdin ```` code block
- Complex `params.headers` (dict): ```` ```yaml headers ```` code block
- Other complex params (dict/list): inline YAML via `yaml.dump(value, default_flow_style=True)`
- Entities without descriptions get placeholder: `"Step description."`
- `ir["inputs"]` → `## Inputs` with `### name` sections
- `ir["nodes"]` → `## Steps` with `### id` sections
- `ir["outputs"]` → `## Outputs` with `### name` sections

**Also create**: `write_workflow_file(ir_dict, path, title="Test Workflow")` helper that writes markdown to a `.pflow.md` file.

This utility is test-only infrastructure. Not production code.

---

## Phase 1: Parser Core

### 1.1 Create `src/pflow/core/markdown_parser.py`

**Exception type** (D1):
```python
class MarkdownParseError(ValueError):
    def __init__(self, message: str, line: int | None = None, suggestion: str | None = None):
        self.line = line
        self.suggestion = suggestion
        super().__init__(message)
```

**Return type**:
```python
@dataclass
class MarkdownParseResult:
    ir: dict[str, Any]                    # The workflow IR dict
    title: str | None                     # H1 heading text
    description: str | None               # H1 prose (between # and first ##)
    metadata: dict[str, Any] | None       # Frontmatter (None for authored files)
    source: str                           # Original markdown content (for save operations)
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

**Parsing rules** (verified against codebase):

1. Frontmatter: `---` at line 1 → extract until closing `---` → `yaml.safe_load()`
2. H1: `# Title` → `result.title = "Title"`
3. H1 prose: everything between `#` and first `##` → `result.description` (D6: paragraphs joined with `\n\n`)
4. H2 sections: case-insensitive match for `Inputs`, `Steps`, `Outputs`
   - Unknown sections silently ignored
   - Near-miss warning for `Input`, `Output`, `Step` (missing 's')
5. H3 entities: heading text = entity ID/name, validated against regex `^[a-z][a-z0-9_-]*$` (D5)
6. Within entity:
   - `- ` lines + indented continuations → collect as YAML items (includes block scalars `|` and `>` — D13)
   - Code fences → extract with info string tag
   - Everything else → prose (description/purpose)
7. Parse collected `- ` lines as YAML sequence → merge into dict. Validate each item is a dict (D7).
8. Route params by section type:
   - **Inputs**: all params → input dict directly (no `params` wrapper). Valid fields: `description`, `required`, `type`, `default`, `stdin`. Schema: `additionalProperties: False`.
   - **Outputs**: all params → output dict directly (no `params` wrapper). Valid fields: `description`, `type`, `source`. Schema: `additionalProperties: False`.
   - **Nodes**: `type` → top-level, prose → `purpose`, `yaml batch` code block → top-level `batch`, everything else → `params`. `params`: `additionalProperties: True`.
9. Generate edges: `[{"from": nodes[i]["id"], "to": nodes[i+1]["id"]} for i in range(len(nodes) - 1)]`
   - **Edge generation is mandatory**. Empty edges causes non-deterministic ordering.
   - Use `"from"` / `"to"` field names (convention in existing workflows).

**YAML continuation collection rules** (precise definition):
- A `- ` line starts a new YAML item
- Subsequent lines indented more than the `- ` are continuations (covers block scalars `|`, `>`)
- A blank line, another `- ` line, or a non-indented non-blank line terminates the continuation
- Non-contiguous items (separated by prose) are collected independently
- All collected items joined with `\n` and parsed as a single YAML sequence via `yaml.safe_load()`

**Code block tag mapping** (last word = param name, preceding word = language hint):

| Tag | Maps to | Used by |
|-----|---------|---------|
| `shell command` | `params.command` | shell nodes |
| `python code` | `params.code` | code nodes |
| `prompt` | `params.prompt` | llm nodes |
| `markdown prompt` | `params.prompt` | llm nodes |
| `source` | output `source` (top-level) | outputs |
| `markdown source` | output `source` (top-level) | outputs |
| `json source` | output `source` (top-level) | outputs |
| `yaml batch` | top-level `batch` (NOT `params.batch`) | batched nodes |
| `yaml stdin` | `params.stdin` | nodes with stdin |
| `yaml headers` | `params.headers` | http nodes |
| `yaml output_schema` | `params.output_schema` | claude-code nodes |

**Top-level IR fields** (parser produces a subset, `normalize_ir()` adds the rest):
- Parser produces: `nodes`, `edges`, `inputs` (default `{}`), `outputs` (default `{}`)
- `normalize_ir()` adds: `ir_version` ("0.1.0")
- Don't produce: `start_node`, `mappings`, `enable_namespacing`, `template_resolution_mode` (use defaults)
- Top-level schema: `additionalProperties: False` — no extra fields

**Validation at parse time**:
- Missing descriptions (required for all entities)
- Bare code blocks (no info string) → suggest tag based on node type
- Duplicate params (same key inline + code block)
- Unclosed code fences → error with opening line reference
- YAML syntax errors → error with line range
- Non-dict YAML items → error suggesting `*` for bullets (D7)
- Invalid node ID format → error with regex (D5)
- Missing `## Steps` section
- Empty `## Steps` (no `###` entities)
- Near-miss section names (`## Input` vs `## Inputs`)
- One code block per param-name tag per entity
- `ast.parse()` on Python code blocks (with offset line numbers)
- `yaml.safe_load()` on YAML config blocks (e.g., `yaml batch`, `yaml headers`)

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
1. **Complete workflow parsing** — full example from format-specification.md
2. **Section handling** — case-insensitive, optional sections, unknown sections, near-miss warnings
3. **Entity parsing** — IDs, descriptions, params, code blocks, ID validation
4. **YAML param parsing** — flat, nested, non-contiguous, comments, block scalars (`|`, `>`)
5. **Code block parsing** — info strings, nested fences (4+ backticks), content extraction
6. **Param routing** — input flat, output flat, node with params wrapper, `type`/`batch` to top-level
7. **Edge generation** — correct from document order, single node (no edges)
8. **Frontmatter** — parsing, stripping, None for authored files
9. **Prose joining** — paragraphs, mixed with params, stripped whitespace (D6)
10. **Validation errors** — each rule produces `MarkdownParseError` with correct line number
11. **Non-dict YAML items** — `- note` without colon produces clear error (D7)
12. **`ast.parse()`** — Python code block syntax validation with correct line offsets
13. **`yaml.safe_load()`** — YAML config block validation
14. **IR equivalence** — parsed markdown produces same IR as manually constructed dict
15. **Edge cases** — empty sections, minimal workflow (single node), large workflows

---

## Phase 2: Integration

### 2.1 CLI integration (`cli/main.py`)

**Changes**:

1. `_is_path_like()` (~line 157): Add `.pflow.md` check
   ```python
   identifier.lower().endswith(".json") or identifier.lower().endswith(".pflow.md")
   ```
   Keep `.json` check for graceful error ("JSON workflow format is no longer supported. Use .pflow.md format instead.").

2. `_try_load_workflow_from_file()` (~line 162): Replace JSON loading with markdown parsing
   ```python
   result = parse_markdown(content)
   workflow_ir = result.ir
   normalize_ir(workflow_ir)
   # Store result for save operations
   ctx_or_stash = result  # implementation detail
   return workflow_ir, "file"
   ```
   On `MarkdownParseError`: display error with line numbers, return `(None, "parse_error")`.

3. Replace `_show_json_syntax_error()` (~line 131) with markdown error display using `MarkdownParseError` fields.

4. **[G3]** `_try_load_workflow_from_registry()` (~line 196): Strip `.pflow.md` suffix.
   ```python
   if identifier.lower().endswith(".pflow.md"):
       name = identifier[:-9]  # len(".pflow.md") == 9
   ```

5. **[G4]** `_handle_workflow_not_found()` (~line 3466): Rename `"json_error"` → `"parse_error"`.

6. **[G5]** `_setup_workflow_execution()` (~line 3384): Both `.json` checks → `.pflow.md`.

7. **[G6]** `is_likely_workflow_name()` (~line 3574): Add `.pflow.md` check.

8. Help text updates: Lines ~3674, ~3695, ~3761 — change `workflow.json` → `workflow.pflow.md`.

9. `resolve_workflow()` (~line 207): Update docstring and comments.

### 2.1b CLI save command (`cli/commands/workflow.py`)

1. **Remove `--description`** (`required=True`) option from `save_workflow` command (~line 350). Description is now embedded in markdown.
2. Update `_load_and_normalize_workflow()` (~line 220): read file content as text, parse markdown, validate.
3. Pass original markdown content (not IR dict) to `save_workflow_with_options()`.
4. **[G7]** After parsing, pass the IR to `format_save_success()` for display.
5. Update docstring examples (`.json` → `.pflow.md`).
6. Gate `--generate-metadata` flag (already in Phase 0.2).

### 2.2 WorkflowManager (`core/workflow_manager.py`)

**Complete rewrite of storage format.** All 8 `.json` references become `.pflow.md` (G1).

1. **Name derivation helper**:
   ```python
   def _name_from_path(file_path: Path) -> str:
       name = file_path.stem
       if name.endswith(".pflow"):
           name = name[:-6]
       return name
   ```

2. **`save()` signature** (D4):
   ```python
   def save(self, name: str, markdown_content: str, metadata: dict | None = None) -> str:
   ```
   - Validate workflow name
   - Build frontmatter dict: `created_at`, `updated_at`, `version: "1.0.0"`, plus any `metadata` fields (flat, no `rich_metadata` wrapper)
   - Write: `---\n{yaml.dump(frontmatter)}---\n\n{markdown_content}`
   - Atomic write (temp file + `os.link()`)
   - Return absolute path string
   - **No parsing**. Caller pre-validated.

3. **`load()` returns flat structure** (D8):
   ```python
   {
       "name": name,                         # from filename
       "description": result.description,    # from H1 prose
       "ir": result.ir,                      # parsed IR dict
       "created_at": frontmatter.get("created_at"),
       "updated_at": frontmatter.get("updated_at"),
       "version": frontmatter.get("version"),
       # Flattened — was in rich_metadata:
       "execution_count": frontmatter.get("execution_count", 0),
       "last_execution_timestamp": frontmatter.get("last_execution_timestamp"),
       "last_execution_success": frontmatter.get("last_execution_success"),
       "last_execution_params": frontmatter.get("last_execution_params"),
       "search_keywords": frontmatter.get("search_keywords"),
       "capabilities": frontmatter.get("capabilities"),
       "typical_use_cases": frontmatter.get("typical_use_cases"),
   }
   ```

4. **`load_ir()`**: parse markdown, return `result.ir`

5. **`list_all()`**: glob `*.pflow.md`, use `_name_from_path()` for name derivation

6. **`update_metadata()`** redesign:
   - Read file content as text
   - Split frontmatter from body (find `---` boundaries)
   - `yaml.safe_load(frontmatter)` → dict
   - Special-case `execution_count` (increment, same as current)
   - Update other fields
   - `yaml.dump(data, default_flow_style=False, sort_keys=False)` (D14)
   - Reassemble: `---\n{frontmatter}---\n\n{body}`
   - Atomic write (temp file + `os.replace()`)
   - Markdown body is NEVER modified

7. **`update_ir()`**: Preserve method but mark as unused (gated repair was only caller). Tests gated (D9).

8. **Remove `_create_metadata_wrapper()`** — replaced by frontmatter generation in save().

### 2.2b Update `rich_metadata` callers (G9)

All callers change from `metadata.get("rich_metadata", {})` to direct field access:

1. `execution/formatters/workflow_describe_formatter.py:56`: `metadata` directly (fields are top-level now)
2. `execution/formatters/discovery_formatter.py:102`: Same
3. `execution/formatters/history_formatter.py:23-54`: Signature may need update if it received `rich_metadata` dict
4. `planning/context_builder.py:451-483`: Direct field access (but context_builder is gated — still update for correctness)
5. `cli/main.py:1204-1221, 1273-1286`: Build flat `metadata` dict instead of `rich_metadata` wrapper
6. `core/workflow_manager.py:323-334`: `update_metadata()` writes to top-level frontmatter

### 2.3 Workflow save service (`core/workflow_save_service.py`)

1. `_load_from_file()` (~line 160): Use markdown parser instead of `json.load()`
2. `load_and_validate_workflow()` (~line 208): Handle markdown content/path
3. **`save_workflow_with_options()` signature change**:
   ```python
   def save_workflow_with_options(
       name: str,
       markdown_content: str,  # Was: workflow_ir + description
       *,
       force: bool = False,
       metadata: Optional[dict[str, Any]] = None,
   ) -> Path:
   ```
   - Passes content + metadata to `WorkflowManager.save()`
   - No separate `description` parameter
4. Remove `description` parameter throughout save chain

### 2.4 MCP resolver (`mcp_server/utils/resolver.py`)

**[G2]** Preserve 3-tuple return: `(workflow_ir | None, error | None, source: str)`.

**String detection for execute/validate** (D12):
1. **Dict** → use as IR directly (source=`"direct"`) — backward compat
2. **String with `\n`** → raw markdown content → parse (source=`"content"`)
3. **String ending `.pflow.md`** (single-line) → file path → read and parse (source=`"file"`)
4. **Single-line string** → try as library name (source=`"library"`), then as file path (source=`"file"`)
5. Not found → suggestions

Update error messages (JSON → markdown).

### 2.5 MCP save tool and service (G8)

**The save flow must preserve original markdown content.** This requires restructuring the entire MCP save chain.

**New MCP save flow**:
```
workflow_save(workflow_str, name, force)           # Tool layer
  → ExecutionService.save_workflow(workflow_str, name, force)  # Service layer
    → detect: content (has \n) or path (ends .pflow.md)
    → read file if path → markdown_content
    → result = parse_markdown(markdown_content)    # validates, extracts IR + description
    → save_workflow_with_options(name, markdown_content, force=force)
      → WorkflowManager.save(name, markdown_content, metadata)
    → return format_save_success(name, path, result.ir, ...)  # IR for display
```

**Changes to `mcp_server/tools/execution_tools.py`**:
1. Remove `description` parameter from tool signature
2. Remove `generate_metadata` parameter (gated in Phase 0.2)
3. Update `Field(description=...)` documentation to mention `.pflow.md`

**Changes to `mcp_server/services/execution_service.py`**:
1. `save_workflow()` — remove `description` and `generate_metadata` params
2. New save-specific detection (NOT using `resolve_workflow()` which discards content):
   - String with `\n` → raw markdown content → parse to validate, save content
   - String ending `.pflow.md` → file path → read file, parse to validate, save content
   - Dict → ERROR ("Pass markdown content or file path, not an IR dict")
   - Single-line non-path string → ERROR ("Already saved — use file path or raw content")
3. `_save_and_format_result()` — receives markdown_content instead of workflow_ir + description
4. Parse once, use IR for `format_save_success()`, use content for saving

### 2.6 Runtime workflow executor (`runtime/workflow_executor.py`)

1. `_load_workflow_file()` (~line 237): use markdown parser instead of `json.load()`
2. Update error messages ("Invalid JSON" → markdown parse errors)
3. Update type check (~line 254): "Workflow must be a JSON object" → appropriate markdown error

### 2.7 Error messages (~10-12 locations)

| File | Change |
|------|--------|
| `cli/main.py:~131-154` | Replace `_show_json_syntax_error()` with `MarkdownParseError` display |
| `ir_schema.py:~370-387` | `_get_output_suggestion()`: JSON examples → markdown syntax |
| `ir_schema.py:~481` | Keep as-is (`validate_ir()` string path, rarely used, no prod code passes strings) |
| `workflow_manager.py:~213` | `json.JSONDecodeError` catch → `MarkdownParseError` |
| `workflow_executor.py:~248,254` | Markdown parse errors |
| `workflow_validator.py:~435-505` | **Remove** JSON string anti-pattern validation (layer 7) |
| `workflow_save_service.py:~182-183` | Markdown parse errors |
| `resolver.py:~63-64` | Markdown parse errors |
| `repair_save_handlers.py:~67` | `.json` in display message (but gated — low priority) |
| `cli/main.py:~3674,3695,3761` | Help text: `workflow.json` → `workflow.pflow.md` |

### 2.8 Unknown param warnings (D3)

Add as **layer 8** in `WorkflowValidator.validate()` (after existing layer 7 removal):

1. For each node, get `interface["params"]` from registry via `registry.get_nodes_metadata([node_type])`
2. `interface["params"]` is a list of `{"key": "url", "type": "str", "description": "..."}` dicts
3. Extract param key set: `{p["key"] for p in interface["params"]}`
4. Compare node `params` keys against interface param keys
5. Warn on unknown params with "did you mean?" via `find_similar_items()` from `core/suggestion_utils.py`
6. Return warnings (not errors) — unknown params don't break execution

---

## Phase 3: Examples and Tests

### 3.1 Convert example workflows

Convert `.json` workflow files to `.pflow.md` (write manually — these are documentation).
Verify IR equivalence: parse both JSON and markdown versions, compare resulting IR dicts.
Delete original `.json` workflow files after verification.

Priority order:
- `examples/core/` (5 files) — used in parameterized tests
- `examples/real-workflows/` (4 files) — complex, good integration tests
- `examples/advanced/` (3 files)
- `examples/nodes/` (4+ files)
- Other example directories

**Do NOT convert** non-workflow JSON files:
- `examples/mcp-pflow/example-claude-desktop-config.json` — MCP config, not workflow

Delete original `.json` workflow files after conversion.

### 3.2 Create markdown invalid examples

Replace `examples/invalid/` JSON files with markdown equivalents:
- `missing-steps.pflow.md` — No `## Steps` section
- `missing-type.pflow.md` — Node without `- type:` param
- `missing-description.pflow.md` — Entity without prose
- `unclosed-fence.pflow.md` — Unclosed code block
- `bare-code-block.pflow.md` — Code block without tag
- `duplicate-param.pflow.md` — Same param inline + code block
- `duplicate-ids.pflow.md` — Two nodes with same `###` heading
- `yaml-syntax-error.pflow.md` — Bad YAML in params

Old JSON invalid examples (`missing-version.json`, `bad-edge-ref.json`, `duplicate-ids.json`, `wrong-types.json`) are deleted — they tested JSON-specific errors or scenarios that can't occur with markdown (e.g., bad edge refs, since edges are auto-generated).

### 3.3 Update test files

**Complete list of test files writing JSON workflows to disk** (25+ files, 200+ occurrences):

```
# CLI tests
tests/test_cli/test_main.py                          (~20 occurrences)
tests/test_cli/test_workflow_output_handling.py       (~25 occurrences)
tests/test_cli/test_workflow_output_source_simple.py
tests/test_cli/test_workflow_resolution.py
tests/test_cli/test_json_error_handling.py            → rename to test_parse_error_handling.py
tests/test_cli/test_workflow_save_cli.py              (~13 occurrences)
tests/test_cli/test_workflow_save.py                  (~8 occurrences)
tests/test_cli/test_validate_only.py                  (~11 occurrences)
tests/test_cli/test_dual_mode_stdin.py                (~18 occurrences)
tests/test_cli/test_shell_stderr_warnings.py          (~9 occurrences)
tests/test_cli/test_enhanced_error_output.py          (~9 occurrences)

# Integration tests
tests/test_integration/test_sigpipe_regression.py     (~8 occurrences)
tests/test_integration/test_metrics_integration.py    (~10+ occurrences)
tests/test_integration/test_e2e_workflow.py           (~11 occurrences)
tests/test_integration/test_workflow_manager_integration.py
tests/test_integration/test_workflow_outputs_namespaced.py

# Runtime tests
tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py
tests/test_runtime/test_workflow_executor/test_workflow_name.py
tests/test_runtime/test_workflow_executor/test_integration.py
tests/test_runtime/test_nested_template_e2e.py

# Core tests
tests/test_core/test_workflow_manager.py              (~3 occurrences, edge cases)
tests/test_core/test_workflow_manager_update_ir.py    (~9 occurrences, tests dead code — leave or skip)
```

**Gated tests (D9) — skip, don't convert:**
```
tests/test_planning/                                   (all files — planner gated)
tests/test_cli/test_repair_save_handlers.py            (repair gated)
tests/test_cli/test_auto_repair_flag.py                (repair gated)
tests/test_integration/test_context_builder_integration.py (planner context builder gated)
```

**For each non-gated test file:**
1. Import `ir_to_markdown` from `tests/shared/markdown_utils`
2. Replace `json.dump(workflow, f)` / `write_text(json.dumps(...))` with writing markdown
3. Change file extensions from `.json` to `.pflow.md`
4. Update CLI invocations to use `.pflow.md` paths
5. Update error message assertions (JSON → markdown)

**Special cases:**
- `test_json_error_handling.py` → rename to `test_parse_error_handling.py`, rewrite for markdown errors
- `test_workflow_resolution.py` → add `.pflow.md` extension tests, update `.json` stripping tests
- `test_workflow_manager.py` → edge case tests (invalid content, corruption) need markdown equivalents
- `test_workflow_manager_update_ir.py` → tests dead code. Leave tests but they test a gated method.

### 3.4 Update example validation tests

- `test_example_validation.py`: change `rglob("*.json")` to `rglob("*.pflow.md")`, exclude non-workflow JSON (MCP configs), update parsing to use markdown parser
- `test_ir_examples.py`: update ~11 hardcoded paths to new `.pflow.md` files and new invalid examples

---

## Phase 4: Polish

### 4.1 Quality checks

- `make test` — all tests pass
- `make check` — lint (ruff) and type check (mypy) pass
- Fix any issues

### 4.2 Manual testing

- `uv run pflow examples/core/minimal.pflow.md` — basic execution
- `uv run pflow workflow save examples/core/minimal.pflow.md --name test-workflow` → saves with frontmatter
- `uv run pflow test-workflow` → loads from saved, executes
- `uv run pflow workflow list` → shows saved workflows
- `uv run pflow workflow describe test-workflow` → shows interface info
- Test error case: pass a `.json` file → graceful error message

### 4.3 Documentation

- Add `src/pflow/core/CLAUDE.md` entry for `markdown_parser.py`
- Update `tests/shared/README.md` with `markdown_utils` documentation
- Update code comments referencing JSON workflow files

---

## Phase 5: Agent Instructions (collaborative with user)

Update `src/pflow/cli/resources/cli-agent-instructions.md` (~13 references to JSON):
- All `workflow.json` examples → `.pflow.md`
- All JSON workflow syntax examples → markdown format examples
- Update save command examples (remove `--description`)
- **This phase is done collaboratively with the user**, not autonomously

Also update `src/pflow/cli/resources/cli-basic-usage.md` if it references JSON workflow files.

---

## Save Pipeline: Complete Flow

### Current flow (JSON)
```
CLI:  file_path → json.load() → IR dict → validate → save(name, ir, description)
MCP:  workflow → resolve_workflow() → IR dict → validate → save(name, ir, description)
```

### New flow (Markdown)
```
CLI:  file_path → read content → parse_markdown() → validate IR → save(name, content, metadata)
MCP:  workflow_str → detect type → read if path → parse_markdown() → validate → save(name, content, metadata)
```

### Key principles
1. **Content preservation**: Save stores ORIGINAL markdown. Author's formatting survives save/load.
2. **No description parameter**: Embedded in markdown content. load() extracts via parsing.
3. **No IR-to-markdown serialization**: Never convert IR back to markdown. Original content preserved.
4. **Frontmatter is additive**: Prepended on save, stripped on load. Body never modified.
5. **Parse once**: Callers parse markdown once, get both IR (for validation/display) and content (for save).

### Frontmatter fields (flat — D8)

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
search_keywords:
  - changelog
  - git
capabilities:
  - generate reports
---
```

---

## Implementation Order (Critical Path)

```
Phase 0.1 (PyYAML dep)              }
Phase 0.2 (Gate planner/repair)     } Can be done in parallel
Phase 0.3 (Test utility)            }

Phase 1.1 (Parser core)             } Sequential — parser first
Phase 1.2 (Parser tests)            } then tests

Phase 2.1 (CLI integration)         }
Phase 2.1b (CLI save command)       }
Phase 2.2 (WorkflowManager)         } Sequential — CLI first (primary entry),
Phase 2.2b (rich_metadata callers)  } then manager, then others
Phase 2.3 (Save service)            }
Phase 2.4 (MCP resolver)            }
Phase 2.5 (MCP save tool+service)   } Can parallel with 2.4
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

Phase 5 (Agent instructions — collaborative with user)
```

---

## Risk Assessment

### High Risk
- **MCP save flow restructuring (G8)**: 6 functions deep, all need signature changes. Dual data flow (IR for display, content for save).
- **Test migration scope**: 200+ disk-write occurrences across 25+ files. `ir_to_markdown()` must handle ALL IR patterns used in tests.
- **WorkflowManager rewrite**: Complete rewrite of save/load/update cycle. Many callers depend on return structure.

### Medium Risk
- **YAML continuation parsing**: Block scalars, flow sequences, nested dicts under `- ` lines. Must handle correctly or error clearly.
- **Frontmatter management**: `update_metadata()` must correctly split/merge without corrupting markdown body. Edge case: authored file (no frontmatter) being updated after first execution.
- **rich_metadata flattening (G9)**: 6 callers to update. All use safe `.get()` patterns, but verify each.

### Low Risk
- **Gating planner/repair**: Simple if-guards.
- **PyYAML dependency move**: Trivial pyproject.toml change.
- **Error message updates**: Find-and-replace style.
- **Unknown param warnings**: Additive, no existing behavior changed.

---

## Verified Codebase Facts

These have been verified against the actual codebase and can be trusted:

- `normalize_ir()` adds `ir_version: "0.1.0"`, `edges: []` if missing, renames `parameters` → `params`
- Top-level IR: 9 fields, `additionalProperties: False`
- Node schema: `id` + `type` required; `purpose`, `params`, `batch` optional; `additionalProperties: False`
- Input schema: `description`, `required`, `type`, `default`, `stdin`; `additionalProperties: False`
- Output schema: `description`, `type`, `source`; `additionalProperties: False`
- Batch schema: `items` required, 7 fields total, `additionalProperties: False`
- `params` has `additionalProperties: True` (unknown params silently accepted — hence the warning feature)
- `purpose` field is optional, unused at runtime (only legacy planner references it)
- All existing workflows are linear chains (verified via generate-changelog: 17 nodes, 16 edges, pure linear)
- `_wire_nodes()` accepts both `from`/`to` and `source`/`target` field names
- `_get_start_node()` uses first node in the `nodes` array
- Template validator loads interface metadata via `registry.get_nodes_metadata()`
- `interface["params"]` is a list of `{"key": ..., "type": ..., "description": ...}` dicts
- 7 validation layers in `WorkflowValidator`; layer 7 is JSON string anti-pattern (to be removed)
- `WorkflowValidator.validate()` accepts optional `registry: Optional[Registry] = None`
- `find_similar_items()` exists in `suggestion_utils.py` with substring/fuzzy matching
- Workflow name derived from filename (not stored in file content)
- No production code passes strings to `_parse_ir_input()` in compiler (only tests)
- `validate_ir()` accepts strings via `json.loads()` but this path is unused in production
- Context builder function is `_load_single_workflow()` (not `_try_load_workflow()` as spec says)
- MCP resolver returns 3-tuple: `(ir | None, error | None, source: str)`
- WorkflowManager has 8 locations with hardcoded `.json`
- `repair_save_handlers.py` creates `.repaired.json` files (gated, no change needed)

---

## Files Created/Modified Summary

### New files
- `src/pflow/core/markdown_parser.py` (~300-400 lines)
- `tests/test_core/test_markdown_parser.py` (~500-700 lines)
- `tests/shared/markdown_utils.py` (~100-150 lines)
- `examples/invalid/*.pflow.md` (8 new files)

### Modified files (major changes)
- `src/pflow/core/workflow_manager.py` — complete storage format rewrite
- `src/pflow/core/workflow_save_service.py` — markdown loading, save signature change
- `src/pflow/cli/main.py` — parser integration, gating, error messages, multiple `.json` refs
- `src/pflow/cli/commands/workflow.py` — remove `--description`, save flow change
- `src/pflow/mcp_server/utils/resolver.py` — markdown loading, content detection
- `src/pflow/mcp_server/tools/execution_tools.py` — parameter changes, documentation
- `src/pflow/mcp_server/services/execution_service.py` — save flow restructure (G8)
- `src/pflow/runtime/workflow_executor.py` — markdown loading

### Modified files (minor changes)
- `pyproject.toml` — PyYAML dependency
- `src/pflow/core/ir_schema.py` — error message examples
- `src/pflow/core/workflow_validator.py` — remove layer 7, add layer 8 (unknown param warnings)
- `src/pflow/cli/repair_save_handlers.py` — gated
- `src/pflow/planning/context_builder.py` — gated
- `src/pflow/execution/formatters/workflow_describe_formatter.py` — flat metadata access (G9)
- `src/pflow/execution/formatters/discovery_formatter.py` — flat metadata access (G9)
- `src/pflow/execution/formatters/history_formatter.py` — flat metadata access (G9)
- `src/pflow/cli/main.py:1204-1286` — flat metadata construction (G9)

### Converted files
- ~30 `.json` → `.pflow.md` in `examples/` (excluding non-workflow JSON like MCP configs)
- 4 old invalid examples deleted, 8 new ones created

### Updated test files
- 25+ test files updated to write `.pflow.md` instead of `.json`
- 2 example validation test files updated
- 1 test file renamed (`test_json_error_handling.py` → `test_parse_error_handling.py`)
- ~6 test files gated (planner/repair tests)

### Agent instructions (Phase 5)
- `src/pflow/cli/resources/cli-agent-instructions.md` — ~13 JSON references updated
- `src/pflow/cli/resources/cli-basic-usage.md` — if applicable
