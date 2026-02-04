# Fork: Task 107 — Phase 0.3 + 1.1 + 1.2 — Parser Core

## Entry 1: Create ir_to_markdown test utility

Attempting: Build `tests/shared/markdown_utils.py` with `ir_to_markdown()` and `write_workflow_file()`.

Result:
- ✅ Created `ir_to_markdown(ir_dict, title, description)` with serialization rules from the implementation plan
- ✅ Created `write_workflow_file(ir_dict, path, title, description)` helper
- ✅ Handles all IR patterns: flat params, shell command code blocks, prompt blocks, python code blocks, yaml batch/stdin/headers/output_schema blocks, complex params (dict/list), outputs with inline and code block source
- ✅ `_format_inline_value()` correctly quotes strings containing YAML-special characters (colons, hashes, booleans) to prevent YAML parsing errors
- 💡 Initial version didn't quote strings with colons — caused YAML parse failures when round-tripping template-variables workflow (values like `"Processed on: ${timestamp}"`). Fixed by detecting YAML-special chars and quoting.

Files modified: `tests/shared/markdown_utils.py`
Status: Phase 0.3 complete.

## Entry 2: Create markdown parser

Attempting: Build `src/pflow/core/markdown_parser.py` with `MarkdownParseError`, `MarkdownParseResult`, and `parse_markdown()` state machine.

Result:
- ✅ `MarkdownParseError(ValueError)` with `line` and `suggestion` fields (D1)
- ✅ `MarkdownParseResult` dataclass with `ir`, `title`, `description`, `metadata`, `source` fields
- ✅ State machine parser with phases: frontmatter extraction, line-by-line scanning, structural validation, IR building
- ✅ Frontmatter parsing with `yaml.safe_load()`
- ✅ H1 title and prose extraction (workflow description)
- ✅ H2 section detection: case-insensitive `Inputs`/`Steps`/`Outputs`, unknown sections silently ignored, near-miss warnings for `Input`/`Output`/`Step`
- ✅ H3 entity parsing with ID validation (`^[a-z][a-z0-9_-]*$`)
- ✅ Duplicate entity ID detection within same section
- ✅ YAML param collection: `- key: value` lines with indented continuation tracking
- ✅ Non-contiguous param collection (prose can appear between param lines)
- ✅ YAML block scalars (`|` and `>`) work naturally via continuation rules
- ✅ Code block parsing: backtick and tilde fences, nested fences (4+ backticks)
- ✅ Code block tag mapping: last word = param name, preceding = language hint
- ✅ Edge generation from document order (mandatory)
- ✅ Param routing: inputs/outputs flat (no params wrapper), nodes get type/batch at top-level, everything else in params
- ✅ Validation: missing descriptions, bare code blocks, duplicate params (inline + code block), unclosed fences, YAML syntax errors, non-dict YAML items, invalid IDs, missing Steps section, empty Steps, missing type param, Python syntax errors (ast.parse), YAML config errors
- ✅ Refactored for ruff C901 compliance: extracted `_resolve_section`, `_is_closing_fence`, `_append_code_block`, `_check_param_code_block_conflicts`, `_route_code_blocks_to_node`
- ✅ All `Optional[X]` → `X | None` per project style
- ✅ mypy passes, ruff passes

Files modified: `src/pflow/core/markdown_parser.py`
Status: Phase 1.1 complete.

## Entry 3: Create parser tests

Attempting: Build `tests/test_core/test_markdown_parser.py` with all 15 test categories.

Result:
- ✅ 70 tests across 15 categories:
  1. Complete workflow parsing (2 tests) — full workflow with inputs/steps/outputs, batch + prompt
  2. Section handling (5 tests) — case-insensitive, optional, unknown, near-miss, missing
  3. Entity parsing (6 tests) — ID from heading, hyphens/underscores, invalid uppercase/number/spaces, duplicates
  4. YAML param parsing (6 tests) — flat, nested, non-contiguous, comments, boolean coercion, block scalars
  5. Code block parsing (12 tests) — shell command, prompt, markdown prompt, python code, yaml batch/stdin/headers/output_schema, nested fences, bare block error, duplicate error, output source, json source
  6. Param routing (6 tests) — input flat, output flat, node type top-level, batch top-level, prose to purpose, remaining to params
  7. Edge generation (2 tests) — document order, single node no edges
  8. Frontmatter (4 tests) — parsing, no frontmatter, nested data, invalid YAML
  9. Prose joining (3 tests) — workflow description, before/after params, stripped
  10. Validation errors (5 tests) — missing description, missing type, unclosed fence, empty steps, inline/code block conflict
  11. Non-dict YAML items (1 test) — bare item error
  12. ast.parse() (2 tests) — valid python, invalid syntax
  13. yaml.safe_load() (2 tests) — valid batch, invalid config
  14. IR equivalence round-trips (5 tests) — minimal, pipeline, complex (inputs/batch/outputs), complex stdin dict, inline batch items
  15. Edge cases (9 tests) — single node, no H1, source preserved, tilde fence, no params except type, empty inputs, stdin field, large workflow (10 nodes), json source output
- ✅ Round-trip verified against 4 real-world workflows:
  - `examples/core/minimal.json` — 1 node, no edges
  - `examples/core/template-variables.json` — 5 nodes, 4 edges, values with colons
  - `examples/real-workflows/webpage-to-markdown/workflow.json` — 7 nodes, batch, complex stdin
  - `examples/real-workflows/generate-changelog/workflow.json` — 17 nodes, inline batch items, complex stdin dicts, 5 outputs
- ✅ All 70 tests pass

Files modified: `tests/test_core/test_markdown_parser.py`
Status: Phase 1.2 complete.

## Final Status

All three files created and validated:
- `tests/shared/markdown_utils.py` — ir_to_markdown utility (test-only)
- `src/pflow/core/markdown_parser.py` — markdown parser (~350 lines)
- `tests/test_core/test_markdown_parser.py` — 70 tests across 15 categories

Quality checks on assigned files:
- ✅ 70/70 tests pass
- ✅ ruff: all checks passed
- ✅ mypy: no issues found
- ✅ Round-trip verified against 4 real-world workflow JSON files

Fork F0b complete. Ready for Phase 2 integration forks.
