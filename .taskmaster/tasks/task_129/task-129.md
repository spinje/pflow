# Task 129: External File References for Code Block Parameters

## Description

Allow any code-block parameter (prompt, code, command, batch, output_schema, etc.) to reference an external file instead of inline content. The system auto-detects file paths, reads the file, and substitutes the content as if it were inline — before compilation and validation, so template variables inside external files are validated normally.

## Status

not started

## Priority

high

## Problem

Prompt-heavy workflows become painful to work with as they grow. Real-world example: a music-generation pipeline's `song-creator.pflow.md` is 913 lines — 682 lines are prompt content. The problems are:

1. **Navigation**: Finding a specific prompt section means scrolling through hundreds of lines of unrelated content.
2. **Editing ergonomics**: Prompts inside YAML batch blocks require maintaining YAML indentation for 200+ lines. One wrong indent breaks the workflow.
3. **Diff noise**: A one-line prompt change shows as a diff in a massive workflow file. Code review can't isolate prompt changes from structural changes.
4. **Large code blocks**: Same problem applies to Python code nodes (e.g., a 105-line `build-file-list` node).

This is NOT a prompt reuse/DRY problem — pflow's `${var}` template system already handles shared content across prompts. This is purely about file size, navigation, and editing ergonomics.

## Solution

Auto-detect file paths in YAML parameter values. When a param value matches a file-path pattern and the file exists, read the file and substitute its content into the IR before compilation. No new syntax, no `_file` suffix — the same param name is used:

```markdown
### write-lyrics
- type: llm
- prompt: ./prompts/write-lyrics.prompt.md

### build-file-list
- type: code
- code: ./scripts/build-file-list.py

### specialist-reviews
- type: llm
- prompt: ${item.prompt}
- batch: ./config/specialist-reviews.yaml
```

The resolved content goes through the same compilation and validation pipeline as inline content. Template variables (`${var}`) inside external files are validated normally.

## Design Decisions

- **Auto-detection over explicit `_file` suffix**: Using the same param name (`prompt`, not `prompt_file`) is cleaner — zero new param names, zero new concepts for users. Detection uses path patterns + file existence verification. Precedent: `- workflow:` already auto-detects file paths vs. saved workflow names.
- **IR transformation step, not parser or compiler change**: File resolution happens between parsing and compilation as a pure function (`resolve_file_references(ir_dict, base_dir) → modified ir_dict`). This ensures validation sees full file content (including template variables), and the parser and compiler stay unchanged.
- **Compile-time resolution, not runtime**: Resolving at compile time means all errors (file not found, bad template variables) surface before execution starts. In a 58-LLM-call pipeline, discovering a missing file mid-execution wastes time and money.
- **YAML-aware substitution**: Text params (prompt, code, command, source, stdin) get raw file content. YAML params (batch, output_schema, headers) get `yaml.safe_load()` applied to file content. This matches how code blocks already work (the `is_yaml_config` distinction).
- **Inline batch items supported, dynamic items not**: For inline arrays (`items: [{prompt: ./path}, ...]`), file references inside items are resolved at compile time. For template-referenced items (`items: ${upstream.results}`), file references are not supported — items aren't known until runtime. This covers the real-world use case (specialist prompts in song-creator).
- **Mutual exclusivity already handled**: Since we use the same param name, the existing `_check_param_code_block_conflicts()` catches the case where both a YAML param (file reference) and a code block exist for the same param. No new check needed.

## Dependencies

None. This is a self-contained feature.

## Requirements

### Detection Heuristic

- A YAML param value is treated as a file reference if it matches a file-path pattern:
  - Starts with `./` or `../`
  - OR contains `/` AND ends with a recognized extension (`.md`, `.txt`, `.py`, `.sh`, `.yaml`, `.yml`, `.json`)
- If a value matches the pattern, the file MUST exist — missing file is an error, not silent fallback to literal text
- Template variables (`${var}`) in file paths are NOT supported — paths must be static strings
- Values that don't match the pattern are always treated as literal content (no false positives on natural language)

### File Resolution

- Paths resolve relative to the workflow file's directory (same as `- workflow: ./sub.pflow.md` already does)
- Base path comes from `_pflow_workflow_file` in `initial_params`, or from the CLI-known source file path
- Text params (prompt, code, command, source, stdin): file content substituted as raw text
- YAML params (batch, output_schema, headers): file content parsed with `yaml.safe_load()` before substitution
- File resolution walks inline batch item arrays recursively, resolving file references in item values

### IR Transformation

- Implemented as a pure function: `resolve_file_references(ir_dict, base_dir) → modified ir_dict`
- Runs between parsing and compilation: `parse_markdown() → resolve_file_references() → compile_ir_to_flow()`
- After resolution, the IR is indistinguishable from one where content was inline — compiler and validator see no difference

### Provenance Tracking

- When a file reference is resolved, annotate the node with source file information (e.g., `_source_files: {"prompt": "./prompts/foo.md"}`)
- Error messages for template validation failures in external files should reference the source file path, not just the node and param name

### Error Handling

- File not found: clear error with resolved absolute path and base directory shown
- File read error (permissions, encoding): clear error with file path
- Mutual exclusivity: if both YAML param (file reference) and code block exist for same param, error (already handled by existing parser check)
- MCP server: if `_pflow_workflow_file` is not set and file references are detected, clear error explaining file references require a workflow file path

### Scope Boundaries

- **In scope**: All 8 code-block-mapped params (command, code, prompt, source, batch, stdin, headers, output_schema)
- **In scope**: File references inside inline batch item arrays
- **Out of scope**: File references in dynamically-generated batch items (template-referenced `items:`)
- **Out of scope**: Template variables in file paths (`prompt: ./prompts/${var}.md`)
- **Out of scope**: Workflow save/bundling (that's Task 130)

## Implementation Notes

### Integration Point

The new step plugs into the existing pipeline. The CLI currently does:

```python
# cli/main.py or execution pipeline
ir = parse_markdown(content).ir
compiled_flow = compile_ir_to_flow(ir, initial_params)
```

This becomes:

```python
ir = parse_markdown(content).ir
base_dir = Path(initial_params.get("_pflow_workflow_file", "")).parent or Path.cwd()
ir = resolve_file_references(ir, base_dir)  # NEW
compiled_flow = compile_ir_to_flow(ir, initial_params)
```

### Key Files to Modify

- **New file**: `src/pflow/core/file_resolver.py` (or similar) — the IR transformation function
- **CLI pipeline**: Where `parse_markdown` result feeds into `compile_ir_to_flow` — insert the new step
- **MCP execution path**: Same insertion point, with `_pflow_workflow_file` handling
- **Validation pipeline**: May need to pass `_source_files` through for error attribution

### Batch Item Handling

The batch config in the IR is a parsed Python dict. For inline arrays:

```python
node["batch"]["items"] = [
    {"focus": "ai-tells", "prompt": "./prompts/ai-tells.md"},
    {"focus": "cliche", "prompt": "./prompts/cliche.md"},
]
```

The resolution step walks this list, detects `./prompts/ai-tells.md` as a file reference, reads the file, and substitutes:

```python
node["batch"]["items"] = [
    {"focus": "ai-tells", "prompt": "You are a specialist reviewer..."},
    {"focus": "cliche", "prompt": "You are a specialist reviewer..."},
]
```

For template-referenced items (`items: "${upstream.results}"`), the value is a string — items aren't available, so no resolution occurs.

### Existing Pattern: Workflow Reference Detection

The workflow executor already auto-detects file references:

```python
# runtime/workflow_executor.py:181-183
def _is_file_reference(value: str) -> bool:
    return "/" in value or "\\" in value or value.endswith(".pflow.md") or value.startswith(".")
```

The new detection heuristic is similar but slightly stricter (requires recognized extension when only `/` is present, to avoid false positives).

## Verification

- Workflow with `- prompt: ./prompts/foo.md` reads the file and uses its content as the prompt
- Template variables (`${var}`) inside external prompt files are validated and resolved correctly
- File references inside inline batch items are resolved
- Missing file produces clear compile-time error with path details
- Both YAML param file reference and code block for same param produces parse error
- YAML file references (batch, output_schema) are parsed correctly
- Paths resolve relative to workflow file, not working directory
- Nested workflows with file references resolve paths relative to their own location
- Error messages for template failures in external files reference the source file
- MCP server execution with file references works for saved workflows
- Existing workflows with no file references are completely unaffected

## References

- Real-world test case: `~/projects/music-generation/workflows/song-creator.pflow.md` (913 lines, 682 lines of prompts)
- Feature request analysis: `scratchpads/prompt-file-references/README.md`
- Workflow reference detection: `src/pflow/runtime/workflow_executor.py:181-183` (`_is_file_reference`)
- Markdown parser code block handling: `src/pflow/core/markdown_parser.py:87-96` (`_CODE_BLOCK_TAG_TO_PARAM`)
- Parser conflict check: `src/pflow/core/markdown_parser.py:689-702` (`_check_param_code_block_conflicts`)
- Compiler pipeline: `src/pflow/runtime/compilation/compiler.py:601` (`compile_ir_to_flow`)
- Batch wrapper: `src/pflow/runtime/wrappers/batch_node.py`
- Source line tracking: `src/pflow/core/markdown_parser.py` (`_source_lines`), `src/pflow/runtime/compilation/compiler.py:265-269`
