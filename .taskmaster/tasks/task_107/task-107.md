# Task 107: Implement Markdown Workflow Format

## Description

Replace JSON as the workflow file format with markdown. The markdown format compiles to the same in-memory dict (IR) that JSON currently produces — all existing validation, compilation, and execution is reused unchanged. The format uses standard markdown structure (headings, code blocks, bullet-point properties) optimized for LLM authoring, with inline documentation that makes workflows self-explaining.

## Status
not started

## Priority
high

## Problem

JSON workflows have significant friction for the actual users (LLMs):

**Prompt editing is painful:**
```json
"prompt": "Analyze this:\n\n${item.subject}\n\nRules:\n- Be concise\n- No guessing"
```
vs just writing text in a code block.

**Data transformations are cryptic jq one-liners:**
```json
"command": "jq -r 'to_entries | map(\"### Image \" + (.key + 1 | tostring) + \"\\n\" + .value.response) | join(\"\\n\")'"
```
- Can't lint, can't test, errors only at runtime

**Documentation is separate:**
- `workflow.json` + `README.md` = two files that drift apart
- The `purpose` field is one line, no formatting

**Token inefficiency:**
- Escaped newlines (`\n`), quotes everywhere
- ~20-40% more tokens than necessary

## Why This Matters

**LLMs are the users, not humans.** This reframe changes everything:
- "Users need to learn new format" → LLMs already know markdown
- "Novel = scary" → LLMs don't feel fear
- "Maintain ecosystem compatibility" → What ecosystem? We're pre-release

The current JSON format is already unusable by humans (editing a prompt on one escaped line). We're not losing human-friendliness — we're gaining it as a side benefit of optimizing for LLMs.

**Literate workflows — documentation IS code:**
- The workflow file IS the documentation. Not `workflow.json` + separate `README.md`
- Renders beautifully on GitHub
- Self-documenting by default — prose is required, not optional
- Can explain WHY a node exists, not just WHAT it does
- Can include links, examples, blockquotes, formatted lists
- This replaces the one-line `purpose` field with free-form prose

**Python over jq (enabled by Task 104):**
- Most shell nodes existed for jq data transforms — cryptic, unlintable
- Python code blocks are readable, lintable (`ast.parse()`), testable, familiar
- The markdown format's value increases dramatically with lintable Python replacing jq

## Solution

Markdown replaces JSON as the **only** workflow file format. File extension: `.pflow.md`. The internal dict (IR) remains for programmatic use (MCP server, visualization, export). Zero users means zero backwards compatibility concerns.

### Format Structure

Three heading levels, one universal entity pattern:

```
#     Workflow title + description prose
##    Section (Inputs, Steps, Outputs)
###   Entity (input, node, or output)
        prose text      → description
        - key: value    → params (YAML list items, merged into dict)
        ```lang param```→ code blocks (content or structured data)
```

### Complete Example

`````markdown
# Webpage to Markdown

Convert a webpage to clean markdown with AI-powered image analysis.

## Inputs

### target_url

Webpage URL to convert to markdown.

- type: string
- required: true

### describe_images

Use vision AI to extract content from images.

- type: boolean
- default: true

## Steps

### fetch

Fetch markdown via Jina Reader.

- type: http
- url: https://r.jina.ai/${target_url}

### analyze

Analyze each image with vision AI.

- type: llm
- model: gemini-3-flash-preview
- images: ${item}

```yaml batch
items: ${extract-images.stdout}
parallel: true
max_concurrent: 40
```

````markdown prompt
Extract the information from this image.

* Diagram/flowchart: mermaid code only (```mermaid block)
* Chart/graph: data values and labels
* Screenshot: visible text and UI elements
````

### save-article

Save the article markdown to disk.

- type: write-file
- file_path: ${compute-filename.stdout}
- content: ${fetch.response}

## Outputs

### file_path

Path to the saved markdown file.

- source: ${compute-filename.stdout}
`````

## Design Decisions (all resolved)

Full details in `.taskmaster/tasks/task_107/research/design-decisions.md` (25 numbered decisions with reasoning and verification).

### Architecture

1. **Markdown-only** — JSON workflow files no longer supported as input. One parser, one format.
2. **Markdown → dict (IR), not → JSON** — `parse_markdown(content) -> dict` produces the same dict shape that `json.load()` would. No JSON intermediate step.
3. **All existing validation reused** — parser produces the dict, all 6 validation layers run unchanged.
4. **Edges from document order** — linear only (no explicit edge declarations). Order of `###` headings in `## Steps` determines execution sequence.
5. **Name from filename** — `generate-changelog.pflow.md` → name `generate-changelog`. The `#` heading is a display title.

### Format

6. **No authoring frontmatter** — `## Inputs` / `## Steps` / `## Outputs` sections replace YAML frontmatter. Frontmatter is only for system metadata on saved workflows (added by pflow, never by agents).
7. **One universal pattern** — inputs, nodes, and outputs ALL use: `###` heading + prose description + `- key: value` params + optional code blocks.
8. **`- key: value` parsed as YAML** — list items collected from anywhere in an entity, joined, parsed by `yaml.safe_load()`, merged into a dict. Supports YAML nesting for complex values.
9. **Code block tag: `language param_name`** — first word = editor highlighting, last word = parser mapping. E.g., `shell command`, `python code`, `yaml batch`, `markdown prompt`.
10. **Descriptions required** — all entities must have prose description text. Replaces the `purpose` field.
11. **`*` for doc bullets, `-` for params** — all `-` lines are params, `*` lines are prose.
12. **Nested fences** — 4+ backticks for prompts containing triple-backtick examples. Verified with CommonMark spec and Python parsers.

### Parser & Validation

13. **Custom line-by-line parser** — no markdown library. ~250-350 lines of state machine code. Delegates YAML to PyYAML, Python syntax to `ast.parse()`.
14. **`ast.parse()` for Python code blocks** — at parse time with markdown line numbers. YAML config blocks validated by `yaml.safe_load()`. Nothing for shell/prompt.
15. **Unknown param warnings** — compare params against registry interface metadata during compilation. Catches typos and accidental documentation-as-param.
16. **Markdown-native errors** — reference headings, code blocks, line numbers. Not abstract IR paths.

### What's NOT in scope

- Full linting (ruff, shellcheck) → Task 118
- Required param pre-validation → [Issue #76](https://github.com/spinje/pflow/issues/76)
- Type stubs / mypy integration → future
- Shell node refactor for variable injection → Task 118
- Round-trip conversion (markdown ↔ JSON)
- Multi-file workflows

## Dependencies

- **Task 104: Python Code Node** — ✅ Completed. Enables lintable `python code` blocks.

## Implementation Scope

### New code

1. **Markdown parser** (`src/pflow/core/markdown_parser.py` or similar)
   - Custom line-by-line state machine
   - Extracts frontmatter (saved workflows), headings, code blocks, `- ` params, prose
   - Tracks line numbers for every element
   - Produces IR dict in same shape as current JSON workflows
   - `ast.parse()` on Python code blocks
   - `yaml.safe_load()` on YAML config blocks

### Modified code (7 JSON parse points)

| # | File | Change |
|---|------|--------|
| 1 | `src/pflow/cli/main.py:172` | Replace `json.loads()` with markdown parser |
| 2 | `src/pflow/runtime/compiler.py:157` | Update `_parse_ir_input()` |
| 3 | `src/pflow/core/workflow_manager.py:205` | Save/load as `.pflow.md` with frontmatter |
| 4 | `src/pflow/mcp_server/utils/resolver.py:61` | Parse markdown files |
| 5 | `src/pflow/runtime/workflow_executor.py:246` | Parse nested workflow files |
| 6 | `src/pflow/core/workflow_save_service.py:176` | Parse markdown in workflow save operations |
| 7 | `src/pflow/planning/context_builder.py:255` | Parse markdown in discovery workflow scanning |

### Error messages (~10-12 JSON references to update)

| File | Current | Target |
|------|---------|--------|
| `cli/main.py:133` | "Invalid JSON syntax" | Markdown parse errors |
| `cli/main.py:155` | "Fix the JSON syntax error" | Markdown-specific guidance |
| `ir_schema.py:481` | "Invalid JSON: {e}" | YAML/structure errors |
| `ir_schema.py:370-387` | `_get_output_suggestion()` JSON examples | Update to markdown syntax |
| `workflow_manager.py:214` | "Invalid JSON in workflow" | Markdown parse errors |
| `workflow_executor.py:248` | "Invalid JSON in workflow file" | Markdown parse errors |
| `workflow_executor.py:254` | "Workflow must be a JSON object" | Update |
| `workflow_validator.py:497` | "Replace JSON string with object syntax" | Remove (JSON anti-pattern not relevant) |
| `workflow_save_service.py:183` | "Invalid JSON in {path}" | Markdown parse errors |
| `mcp_server/utils/resolver.py:64` | "Invalid JSON in file" | Markdown parse errors |

Note: MCP config messages in `mcp/manager.py` and `cli/mcp.py` also mention JSON but are about MCP server configs, not workflows — no change needed.

### Unknown param warnings (new validation)

During compilation (where template validation already happens), compare node params against `interface["params"]` keys from registry metadata. Warn on unknown params with "did you mean?" suggestions.

### Existing examples

Convert JSON workflows in `examples/` to `.pflow.md` format. These serve as both test cases and documentation.

## Code Block Mapping

| Tag pattern | Highlights as | Maps to | Used by |
|---|---|---|---|
| `shell command` | bash | `params.command` | shell nodes |
| `python code` | Python | `params.code` | code nodes |
| `prompt` | plain | `params.prompt` | llm nodes |
| `markdown prompt` | markdown | `params.prompt` | llm nodes |
| `source` | plain | output `source` | outputs |
| `markdown source` | markdown | output `source` | outputs |
| `yaml batch` | YAML | `batch` (top-level) | batched nodes |
| `yaml stdin` | YAML | `params.stdin` | nodes with stdin |
| `yaml headers` | YAML | `params.headers` | http nodes |

Rule: last word = param name, preceding word = language hint. Parser only uses last word.

Exception: `yaml batch` maps to top-level `batch` field, not `params.batch`.

## IR Node Field Mapping (verified)

Top-level node fields (`additionalProperties: False`):

| Field | Required | Maps from |
|-------|----------|-----------|
| `id` | Yes | `###` heading text |
| `type` | Yes | `- type:` param (extracted from params, moved to top level) |
| `purpose` | No | Prose description (joined with `\n\n`, stripped) |
| `params` | No | All other `- key: value` params + code block content |
| `batch` | No | `yaml batch` code block (parsed as YAML dict) |

## Verification

**Parser correctness:**
- Parses complete workflows (convert existing JSON examples, compare IR dicts)
- Handles all entity types (inputs, nodes, outputs)
- Extracts code blocks with correct param mapping
- Handles nested fences (4+ backticks)
- Tracks line numbers accurately
- Rejects invalid workflows with clear, markdown-native errors

**Execution equivalence:**
- Convert existing JSON workflows to markdown
- Parse both → compare resulting IR dicts
- Execute both → compare results

**Validation works:**
- All 6 existing validation layers pass on markdown-produced dicts
- Markdown-specific validation catches: missing descriptions, duplicate params, unknown code block tags, unclosed fences, YAML syntax errors
- Unknown param warnings fire correctly

**Integration:**
- CLI: `pflow run workflow.pflow.md` works
- Saved workflows: `pflow workflow save` stores as `.pflow.md` with frontmatter
- MCP server: resolves and executes markdown workflows
- Nested workflows: markdown files referenced by workflow nodes

**Token efficiency:**
- Measure token count for same workflow in JSON vs markdown
- Expect 20-40% reduction (escaped `\n`, redundant quotes eliminated)

**LLM authoring quality:**
- Have LLMs generate workflows in markdown format
- Compare error rate and quality vs JSON generation
- The format should be what LLMs naturally produce — familiar from READMEs, API docs, SOPs

## Example Workflows for Conversion

These existing JSON workflows should be converted to `.pflow.md` as test cases:
- `examples/real-workflows/generate-changelog/workflow.json` — complex (15 nodes, batch, multiple outputs)
- `examples/real-workflows/webpage-to-markdown/workflow.json` — medium complexity (already shown in markdown in the format spec)

## Research & Design Documents

All design decisions, verified assumptions, and format specification:
- `.taskmaster/tasks/task_107/research/design-decisions.md` — 25 decisions with reasoning and codebase verification
- `.taskmaster/tasks/task_107/research/format-spec-decisions.md` — complete format spec with examples and parsing rules
- `.taskmaster/tasks/task_107/research/braindump-format-design-session.md` — implementation insights and warnings
