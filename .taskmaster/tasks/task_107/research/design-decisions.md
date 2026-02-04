# Task 107: Design Decisions & Research Log

> Living document tracking decisions, verified architecture facts, and open questions for the markdown workflow format implementation.

---

## Format Overview

The markdown workflow format uses standard markdown structure with one universal pattern at every level:

```
#     Workflow title + description prose
##    Section (Inputs, Steps, Outputs)
###   Entity (input, node, or output)
        prose text      ← description (inputs/outputs/workflow → `description`, nodes → `purpose`)
        - key: value    ← params (YAML list items, merged into dict)
        ```lang param```← code blocks (content or structured data)
```

Three heading levels maximum. Everything follows the same `### heading` + prose description + `- key: value` params + optional code blocks pattern. No frontmatter in authored files (saved workflows get system metadata frontmatter). No special syntax for different entity types.

### Full Example

`````markdown
# Webpage to Markdown

Convert a webpage to clean markdown with AI-powered image analysis.
Uses Jina Reader for initial conversion and Gemini vision for image descriptions.

## Inputs

### target_url

Webpage URL to convert to markdown. Supports any publicly accessible URL.

- type: string
- required: true

### describe_images

Use vision AI to extract content from images found in the page.

- type: boolean
- default: true

## Steps

### fetch

Fetch markdown via Jina Reader. We use Jina over direct fetching because
it handles SPAs and paywalled content better.

- type: http
- url: https://r.jina.ai/${target_url}

### analyze

Analyze each image with vision AI to extract content.

- type: llm
- model: gemini-3-flash-preview
- images: ${item}

```yaml batch
items: ${extract-images.stdout}
parallel: true
max_concurrent: 40
```

```markdown prompt
Extract the information from this image.

* Diagram/flowchart: mermaid code only
* Chart/graph: data values and labels
* Screenshot: visible text and UI elements
* Decorative: say 'decorative'

Be direct. No commentary.
```

### save-article

Save the article markdown to disk at the computed filename.

- type: write-file
- file_path: ${compute-filename.stdout}
- content: ${fetch.response}

## Outputs

### file_path

Path to the saved markdown file with article content and image analyses.

- source: ${compute-filename.stdout}
`````

---

## Decisions Made

### 1. Markdown-only file format

**Decision**: Markdown replaces JSON as the workflow file format. JSON workflow files are no longer supported as input.

**Reasoning**:
- Zero users means zero backwards compatibility concerns
- No format detection logic needed — one parser, one format
- Error messages can be markdown-specific without conditional formatting
- Agent instructions teach one format only
- The internal dict representation remains for programmatic use (MCP server tools, visualization, export)

**What this does NOT change**: The in-memory dict (IR) that validation, compilation, and execution operate on stays the same. Markdown is just a different way to produce that dict.

### 2. Markdown compiles to internal dict, not to JSON

**Decision**: `parse_markdown(content) -> dict` produces the same dict shape that `json.load()` currently produces. No JSON intermediate step.

**Reasoning**:
- Converting markdown to JSON string then parsing adds unnecessary serialization
- Would re-introduce escaping problems (prompts get `\n` in JSON)
- The compiler, validator, and executor all expect a dict — produce it directly

**Pipeline**:
```
Previously:   workflow.json  →  json.load()       →  dict  →  validate → compile → execute
Now:          workflow.md    →  parse_markdown()   →  dict  →  validate → compile → execute
```

### 3. All existing validation reused unchanged

**Decision**: The markdown parser produces the dict. All 6 existing validation layers run on that dict without modification.

**Verified**: Validation operates on the dict structure (node types, edges, templates, outputs). It does not reference JSON syntax in its core logic. ~10-12 error messages mention "JSON" explicitly (see Architecture Findings below).

### 4. Edges from document order

**Decision**: No explicit edge declarations. Execution order is determined by the order of `###` headings in the `## Steps` section. Top to bottom.

**Reasoning**: pflow is currently linear-only (Tasks 38 and 39 are future work). Document order is the natural way to express sequence in a markdown document. When conditionals/parallel are implemented, explicit edge syntax can be added.

**Example**: If nodes appear as `### fetch`, `### analyze`, `### format`, the parser generates edges: fetch → analyze → format.

### 5. Prose as description (all entities)

**Decision**: Prose is preserved for all entities, but serves different roles:

| Context | Prose becomes | IR field | Used at runtime? |
|---------|--------------|----------|-----------------|
| After `#` title (until first `##`) | Workflow description | Outside IR (metadata) | Yes — search, display in `pflow workflow list` |
| After `###` input heading | Input description | `inputs.{name}.description` | Yes — help text, validation messages |
| After `###` output heading | Output description | `outputs.{name}.description` | Yes — interface documentation |
| After `###` node heading | Node description | `purpose` field on node | No — dead code at runtime, but forces documentation |

**Reasoning**: Interface descriptions (workflow, inputs, outputs) are used programmatically — they appear in `pflow workflow describe`, search results, and validation messages. Node prose is saved to the `purpose` field (effectively dead code at runtime) but forces the author to articulate intent. Low overhead to store it, and it may become useful for future display features.

**Note on workflow `description`**: This field lives OUTSIDE the IR dict — it's in the WorkflowManager metadata wrapper. In the markdown format, it comes from the H1 prose (between `#` title and first `##`). When saving workflows, agents no longer need to specify description separately — it's extracted from the markdown content.

**Descriptions are required** for all entities (inputs, outputs, and nodes). This forces the author to articulate intent. A node without a description is a validation error. The error message shows the expected structure:

```
Node '### analyze' (line 30) is missing a description.

Add a text paragraph between the heading and the parameters:

    ### analyze

    Description of what this node does and why.

    - type: llm
```

This replaces the old JSON `purpose` field with something far more expressive — free-form prose instead of a single constrained line.

### 6. One code block per language type per node

**Decision**: Each node can have at most one code block per param-name tag. Two `prompt` blocks under the same heading is a validation error. Different tags are fine (e.g., an LLM node with both `prompt` and `batch` blocks).

### 7. Document structure: sections with headings, no authoring frontmatter

**Decision**: The authored document uses `#` for workflow title, `##` for sections (Inputs, Steps, Outputs), and `###` for all entities. No YAML frontmatter in authored files.

**Reasoning**:
- Frontmatter mixes three syntax zones (YAML + markdown + code blocks)
- The section approach matches how documentation is naturally written (like an SOP: inputs, steps, outputs)
- LLMs have seen this document structure billions of times in training data
- The format should look like documentation because "documentation IS the workflow"
- Data flows top-to-bottom: inputs defined first, then used by nodes, then outputs reference node results

**Structure**:
```
# workflow-name         ← H1: title + description prose
## Inputs               ← H2: reserved section name
  ### input-name        ← H3: input declaration
## Steps                ← H2: reserved section name
  ### node-id           ← H3: workflow node
## Outputs              ← H2: reserved section name
  ### output-name       ← H3: output declaration
```

**Reserved section names**: `Inputs`, `Steps`, `Outputs` (case-insensitive). These are the only `##` headings with special meaning. Unknown `##` sections are silently ignored (treated as documentation — agents can add `## Notes`, `## Design Decisions`, etc.). **Near-miss warning**: `## Input`, `## Output`, `## Step` (missing 's') produce a warning since these are almost certainly typos.

**Optional sections**: `## Inputs` and `## Outputs` are optional (many simple workflows don't need declared interfaces). `## Steps` is required (must have at least one node). `# title` is optional (name comes from filename).

**Maximum depth**: Three heading levels (`#`, `##`, `###`). This is guaranteed — nothing pushes deeper. Complex data goes in code blocks, not deeper headings.

**Section naming**: "Steps" was chosen over "Workflow" (redundant — the whole file is a workflow), "Nodes" (too technical), and "Pipeline" (too specific). "Steps" is the most natural documentation word — SOPs, runbooks, and tutorials all use "Steps."

### 8. One universal pattern for all entities

**Decision**: Inputs, nodes, and outputs ALL use the same pattern: `###` heading + `- key: value` params + optional code blocks.

**Reasoning**: We explored having inputs as YAML blocks, list items, and headings. Having different syntax for different entity types (e.g., YAML block for inputs but heading+params for nodes) creates inconsistency. When complex outputs need code blocks (source templates), they'd need headings — making them look different from simple outputs that used list items. One pattern eliminates this.

**The pattern**:
```markdown
### entity-name

Required prose description.

- key: value
- key: value

Optional additional prose (design rationale, notes, etc.)

```lang param_name
content
```
```

Simple entities have just a description and params. Complex entities add code blocks. Same visual weight everywhere.

### 9. Params as YAML list items with merge

**Decision**: `- key: value` lines are parsed as a YAML sequence (list of single-key mappings) and merged into a single dict.

**Reasoning**:
- `- ` prefix gives visual bullet points in editors — distinguishes params from prose
- Parsing as YAML means nesting works naturally when needed
- Merge step (list of single-key dicts → single dict) is trivial
- Agents will instinctively try YAML nesting under `-` items — it should work

**Simple case** (flat params, no indentation):
```markdown
### fetch
- type: http
- url: https://example.com
- timeout: 30
```
Parsed as: `[{"type": "http"}, {"url": "..."}, {"timeout": 30}]` → merged to `{"type": "http", "url": "...", "timeout": 30}`

**Nested case** (YAML indentation under `-` item):
```markdown
### fetch
- type: http
- headers:
    Authorization: Bearer ${token}
    Content-Type: application/json
```
Parsed as: `[{"type": "http"}, {"headers": {"Authorization": "...", "Content-Type": "..."}}]` → merged to `{"type": "http", "headers": {...}}`

**Rare in practice**: 95% of params are flat `- key: value`. Indentation only appears for genuinely nested structures (complex default values, object params). This avoids the indentation gymnastics that made other approaches feel heavy.

### 10. Code block tag pattern: `language param_name`

**Decision**: Code block info string uses `language param_name` format. First word = language for editor highlighting. Last word = param name for parser mapping. If only one word, it serves as both.

**Reasoning**:
- Different content types need different syntax highlighting (bash for shell, Python for code, YAML for config)
- The param name tells the parser where the content maps to in the IR
- Agents choose the language that matches their content for best highlighting

**Examples**:
```
```shell command          → bash highlighting, maps to params.command
```python code            → Python highlighting, maps to params.code
```yaml batch             → YAML highlighting, maps to batch config
```yaml stdin             → YAML highlighting, maps to params.stdin
```yaml headers           → YAML highlighting, maps to params.headers
```prompt                 → no highlighting, maps to params.prompt
```markdown prompt        → markdown highlighting, maps to params.prompt
```source                 → no highlighting, maps to output source
```markdown source        → markdown highlighting, maps to output source
```json source            → JSON highlighting, maps to output source
```

**The rule**: last word is always the param name. Preceding word (if any) is the language hint for the editor. The parser ignores the language word — it only cares about the param name.

**Future simplification**: When `command` is renamed to `shell` and `code` is renamed to `python` in the IR, those blocks simplify to just `shell` and `python` — tag becomes both language and param name. YAML config blocks will always need the info string since `yaml` is a language, not a param.

### 11. Flexible prose and param placement

**Decision**: Prose can appear anywhere — before params, after params, between code blocks. All `- key: value` lines are always treated as params regardless of position. Prose and code blocks can be freely interleaved.

**Parsing rule**: The parser scans all lines in the `###` entity:
- Lines starting with `- ` (plus indented continuations) → collected as YAML params
- Code block fences → extracted as code blocks
- Everything else → prose (description for inputs/outputs/workflow, `purpose` for nodes)

For inputs/outputs/workflow: all prose (concatenation of all non-param, non-code-block text) becomes the `description` field. For nodes: all prose becomes the `purpose` field.

**YAML `#` comments work naturally**: Since params are parsed as YAML, `# comments` after values are stripped by the YAML parser:

```markdown
### analyze

Classifies each commit as user-facing or internal.

- type: llm
- model: gpt-4  # Best accuracy for classification

We chose GPT-4 over cheaper models because accuracy matters
more than cost for commit classification.

- timeout: 120  # Long timeout for batch processing
- temperature: 0.1
```

**For documentation bullet lists**: Use `*` instead of `-` to avoid being parsed as params. All `-` lines are treated as params. All `*` lines are treated as prose.

**Reasoning**: Maximum flexibility for documentation. Agents and humans can write prose wherever it makes sense — explaining a param choice, documenting a design decision between code blocks, or adding context before the params. The format should not constrain natural writing patterns.

### 12. Nested code fences (verified)

**Decision**: Prompts containing code block examples use 4+ backticks for the outer fence.

**Verified**: Both `mistune` and `markdown-it-py` correctly handle this per CommonMark spec. The closing fence must have at least as many backticks as the opening fence.

`````markdown
````markdown prompt
Here's an example:
```python
print("hello")
```
````
`````

### 13. Node IDs from headings, must be valid format

**Decision**: The `###` heading text IS the entity ID directly. No normalization. Must be lowercase alphanumeric with hyphens or underscores (no spaces).

**Verified**: Current IR has no explicit ID format validation. Convention in existing examples is `snake_case`. We enforce valid format at the markdown parser level.

### 14. Type stubs / mypy integration is NOT in scope

**Decision**: No `.pyi` stub generation. No mypy integration. The code node validates type annotations at runtime.

### 15. Error messages should be markdown-native

**Decision**: Errors reference markdown structure (headings, code blocks, line numbers), not abstract IR paths.

**Current**: `"'type' is a required property at nodes[0]"`
**Target**: `"Node '### analyze' (line 15) missing required 'type' parameter"`

The parser must track source line numbers and propagate them through validation.

### 16. Name from filename

**Decision**: Workflow name is derived from the filename. `generate-changelog.pflow.md` → name `generate-changelog`. The `#` H1 heading is the display title (documentation), not the programmatic name.

**Reasoning**: Avoids redundancy between filename and content. When saved via `pflow workflow save my-name`, the name is the save name. The H1 heading can be a human-friendly title with spaces and formatting.

### 17. Saved workflows use frontmatter for system metadata

**Decision**: When workflows are saved via `pflow workflow save`, pflow adds YAML frontmatter containing system metadata. Agents never write or edit frontmatter — it's managed programmatically.

**Two contexts for the same file format**:

| Context | Location | Frontmatter | Who writes |
|---------|----------|-------------|------------|
| Authoring | `./workflow.pflow.md` | None | Agent |
| Saved | `~/.pflow/workflows/name.pflow.md` | System metadata | pflow CLI |

**The workflow**:
1. Agent writes `./workflow.pflow.md` — clean markdown, no frontmatter
2. Agent iterates: `pflow run ./workflow.pflow.md`
3. Agent saves: `pflow workflow save my-workflow` → pflow adds frontmatter and stores it
4. To modify later: copy to local (strip frontmatter) → iterate → save again

**Saved file example**:
```markdown
---
created_at: "2026-01-14T15:43:57.425006+00:00"
updated_at: "2026-01-14T22:03:06.823530+00:00"
version: "1.0.0"
execution_count: 8
last_execution_timestamp: "2026-01-14T23:03:06.823108"
last_execution_success: true
last_execution_params:
  version: "1.0.0"
  slack_channel: "releases"
---

# Generate Changelog

Creates professional changelogs from git history.

## Inputs
...
```

**Reasoning**: Mirrors the current JSON metadata wrapper, just in a different format. One file per workflow. If future needs require full execution history or query support, migrating to SQLite is straightforward since the metadata is structured and the WorkflowManager is a single abstraction layer.

**Parser behavior**: If frontmatter exists, extract metadata and pass to WorkflowManager. If not, it's a clean authoring file. The workflow body is identical either way.

### 18. Duplicate param is an error

**Decision**: A parameter specified both as an inline `- key: value` AND as a code block is a validation error.

```markdown
### process
- type: shell
- stdin: ${fetch.response}    ← inline

```yaml stdin                  ← code block — ERROR: stdin defined twice
config: ${other.data}
```
```

**Reasoning**: Duplicate definitions are ambiguous. The parser should fail fast with a clear error rather than silently picking one.

### 19. Code blocks without info string are errors

**Decision**: Bare code blocks (no language/param tag) are validation errors. The error should suggest the likely tag based on node type.

```
Code block at line 12 has no tag.
For a 'llm' node, did you mean ```prompt or ```markdown prompt?
```

### 20. `ir_version` handled by normalize_ir()

**Decision**: The markdown format has no explicit `ir_version` field. The existing `normalize_ir()` function (called during workflow loading) adds default boilerplate fields including `ir_version` when they're missing. The parser produces a dict without `ir_version` and lets normalization handle it.

**Verified**: `normalize_ir()` (`ir_schema.py:559-592`) adds exactly 3 things:
1. `ir_version: "0.1.0"` if missing
2. `edges: []` if missing (and no `flow` field)
3. Renames `parameters` → `params` in nodes (backwards compat)

The markdown parser can produce a minimal dict (no `ir_version`, no `edges`) and let `normalize_ir()` fill in defaults. However, the parser SHOULD generate edges from document order (Decision 4), so `edges` will already be present.

### 21. `batch` maps to top-level node field (implementation detail)

**Decision**: The `yaml batch` code block maps to the node-level `batch` field, not `params.batch`. This is the one exception to "code blocks map to params." The parser handles this — agents don't need to know about the `params` wrapper in the IR. Similarly, `source` code blocks in outputs map to the output-level `source` field, not `params.source`.

This is purely an implementation detail. The agent just writes `yaml batch` or `source` and the parser puts it in the right place.

**Verified**: The complete set of top-level node fields is (from `ir_schema.py:197-212`, `additionalProperties: False`):

| Field | Required | Maps from |
|-------|----------|-----------|
| `id` | Yes | `###` heading text |
| `type` | Yes | `- type:` param |
| `purpose` | No | All prose within entity (joined with `\n\n`, stripped) |
| `params` | No | All other `- key: value` params + code block content |
| `batch` | No | `yaml batch` code block |

**Only `batch` is a special case** for the code block mapping. The parser routes: `type` → top-level, prose → `purpose`, `yaml batch` → top-level `batch`, everything else → `params`.

### 22. Description concatenation strategy

**Decision**: All prose text within an entity is concatenated by joining paragraphs with `\n\n` (double newline), preserving paragraph structure. Leading and trailing whitespace is stripped from the final result.

**Scope**:
- **Inputs and outputs**: Concatenated prose becomes the `description` field in the IR (used in help text, validation messages, `pflow workflow describe`)
- **Nodes**: Prose is collected and saved to the `purpose` field. **Verified**: `purpose` is optional in the IR schema, not used by the compiler, runtime, CLI display, MCP server, or validation. It exists only in the planner's IR models (legacy). The description is still **required** by the parser (forces documentation), even though `purpose` is effectively dead code at runtime.
- **Workflow**: Prose after the `#` title becomes the workflow `description` field

**Example**: If prose appears before params AND after a code block:
```markdown
### analyze

Classifies each commit as user-facing or internal.

- type: llm
- model: gpt-4

We chose GPT-4 over cheaper models because accuracy matters
more than cost for commit classification.
```

The description is: `"Classifies each commit as user-facing or internal.\n\nWe chose GPT-4 over cheaper models because accuracy matters\nmore than cost for commit classification."`

### 23. Error suggestion examples show markdown syntax

**Decision**: All error messages that include "correct format" examples must show markdown syntax, not JSON. This applies to suggestion examples in `ir_schema.py` and anywhere else that currently demonstrates the correct way to write a workflow.

**Current** (JSON examples):
```
Example:
  "story": {
    "source": "${generate_story.response}"
  }
```

**Target** (markdown examples):
```
Example:
  ### story

  Description of the output.

  - source: ${generate_story.response}
```

### 24. Remove JSON anti-pattern validation, replace with markdown-specific validation

**Decision**: The JSON string template anti-pattern validation (layer 7, `workflow_validator.py:496-504`) is removed. It detected manually-constructed JSON strings — a problem that doesn't exist in the markdown format.

**Replaced by markdown-specific validation**:
- Code blocks without info string tags
- Unclosed code fences
- YAML syntax errors in `- key: value` params
- Invalid section names (with near-miss warnings for `## Input` vs `## Inputs`)
- Missing required descriptions
- Duplicate params (inline + code block conflict)

### 25. Custom line-by-line parser (no markdown library)

**Decision**: Build a custom state machine parser that scans lines top-to-bottom. No dependency on mistune, markdown-it-py, or any markdown library.

**Reasoning** (validated by 4 independent assessments):
- The format is a DSL using markdown syntax, not a markdown document. Libraries optimize for rich text rendering — we need structured data extraction.
- The hard part (`- ` line collection with YAML continuations) is custom logic regardless. A library doesn't help.
- Libraries parse `- key: value` as markdown list items, which interferes with our YAML parsing.
- Line number tracking is free with line-by-line scanning, painful with AST reconstruction.
- A library risks **silent failures** (ambiguous indentation parsed into wrong AST structure, producing silently wrong workflows). A custom parser fails loudly with clear errors.
- ~250-350 lines of focused, testable code. Only dependency: PyYAML (already used).

**Implementation approach**:
- State machine scanning lines: headings, code fences, `- ` params, prose
- Delegate YAML parsing to `yaml.safe_load()` — collect `- ` line blocks (including indented continuations), hand to PyYAML
- Delegate Python syntax checking to `ast.parse()`
- Track line numbers throughout for markdown-native error messages
- Write test cases first (valid workflows, edge cases, error conditions)

**Escape hatch**: If YAML continuation tracking proves too complex, nested params can be restricted to `yaml` code blocks (e.g., ` ```yaml headers ` instead of indented `- headers:` with sub-keys). But this should not be needed since PyYAML handles the actual nesting.

---

## Architecture Findings (Verified Against Code)

### JSON parse points that need changing

7 places in the codebase where `json.load()`/`json.loads()` is called on workflow files:

| # | File | Line | Context |
|---|------|------|---------|
| 1 | `src/pflow/cli/main.py` | 172 | `_try_load_workflow_from_file()` — CLI loads workflow from path |
| 2 | `src/pflow/runtime/compiler.py` | 157 | `_parse_ir_input()` — compiler accepts string input |
| 3 | `src/pflow/core/workflow_manager.py` | 205 | `load()` — loads saved workflows |
| 4 | `src/pflow/mcp_server/utils/resolver.py` | 61 | `resolve_workflow()` — MCP resolves file paths |
| 5 | `src/pflow/runtime/workflow_executor.py` | 246 | `_load_workflow_from_path()` — nested workflow loading |
| 6 | `src/pflow/core/workflow_save_service.py` | 176 | `_load_from_file_path()` — workflow save operations (CLI/MCP) |
| 7 | `src/pflow/planning/context_builder.py` | 255 | `_try_load_workflow()` — discovery workflow scanning |

Everything downstream of these 7 points operates on dicts. No changes needed to compiler, validator, or executor.

### Error messages mentioning JSON (~10-12 places to update)

| File | Line | Message | Action |
|------|------|---------|--------|
| `cli/main.py` | 133 | "Invalid JSON syntax in {path}" | Replace with markdown parse errors |
| `cli/main.py` | 155 | "Fix the JSON syntax error" | Replace |
| `ir_schema.py` | 481 | "Invalid JSON: {e}" | Replace with YAML/structure errors |
| `ir_schema.py` | 370-387 | `_get_output_suggestion()` shows JSON examples | Update to markdown syntax (Decision 23) |
| `workflow_manager.py` | 214 | "Invalid JSON in workflow" | Update for saved workflow format |
| `workflow_executor.py` | 248 | "Invalid JSON in workflow file" | Update for nested workflows |
| `workflow_executor.py` | 254 | "Workflow must be a JSON object" | Update |
| `workflow_validator.py` | 497 | "Replace JSON string with object syntax" | Remove (JSON anti-pattern not relevant) |
| `workflow_save_service.py` | 183 | "Invalid JSON in {path}: {e}" | Update for markdown format |
| `mcp_server/utils/resolver.py` | 64 | "Invalid JSON in file: {e}" | Update for markdown format |

Additional MCP config messages (`mcp/manager.py`, `cli/mcp.py`) mention JSON but are about MCP server configs, not workflows — no change needed.

### Error system structure

Errors use a three-part structure (WHAT/WHY/HOW):
- `UserFriendlyError` base class with `title`, `explanation`, `suggestions`
- `ValidationError` with `message`, `path`, `suggestion`
- Validation formatter: bullet-pointed error list + auto-generated suggestions
- Error paths use bracket notation: `nodes[0].type`, `edges[1].from`

For markdown, error paths should reference source: `node "### fetch" (line 15)`.

### Saved workflows (WorkflowManager)

**Decided**: Saved workflows become markdown files with YAML frontmatter for system metadata. See Decision 17 above. The WorkflowManager stores `~/.pflow/workflows/{name}.pflow.md` with frontmatter containing timestamps, version, execution stats. The parser strips frontmatter before processing the workflow body.

---

## Code Block Content Types

### Content blocks (text/code — needs appropriate highlighting)

| Tag pattern | Highlights as | Maps to | Used by |
|---|---|---|---|
| `shell command` | bash | `params.command` | shell nodes |
| `python code` | Python | `params.code` | code nodes |
| `prompt` | plain | `params.prompt` | llm nodes |
| `markdown prompt` | markdown | `params.prompt` | llm nodes |
| `source` | plain | output `source` | output declarations |
| `markdown source` | markdown | output `source` | output declarations |
| `json source` | JSON | output `source` | output declarations |

### Config blocks (structured YAML data)

| Tag pattern | Highlights as | Maps to | Used by |
|---|---|---|---|
| `yaml batch` | YAML | `batch` config | any batched node |
| `yaml stdin` | YAML | `params.stdin` | nodes with complex stdin |
| `yaml headers` | YAML | `params.headers` | http nodes |
| `yaml output_schema` | YAML | `params.output_schema` | claude-code nodes |

The agent chooses the language that best matches the content. The parser only uses the last word (param name).

---

## Parsing Algorithm (High Level)

1. **Check for frontmatter** — if `---` markers at start of file, extract system metadata (saved workflows only)
2. **Extract H1** — workflow title from heading, all prose between `#` and first `##` = workflow `description`
3. **Split by H2** — identify `## Inputs`, `## Steps`, `## Outputs` sections (Inputs and Outputs optional)
4. **Within each section, split by H3** — each `###` heading is an entity (input, node, or output)
5. **For each entity**:
   a. Heading text = entity ID/name
   b. Extract code blocks (by fence markers, from anywhere in the entity)
   c. Collect `- ` prefixed lines (with indented continuations) from anywhere = YAML params
   d. Parse params as YAML sequence, merge into single dict
   e. Remaining text = prose → joined with `\n\n`, stripped → `description` for inputs/outputs/workflow, `purpose` for nodes
6. **Validate descriptions** — all entities (inputs, outputs, nodes) must have prose description text
7. **Generate edges** from document order of `###` headings in `## Steps`
8. **Compile to IR dict** in the same shape as current JSON workflows
9. **Run existing validation** on the dict

---

## Open Questions

### 1. File extension

| Extension | Renders on GitHub | Distinguishable | IDE support |
|-----------|-------------------|-----------------|-------------|
| `.md` | Yes | No (mixed with docs) | Full |
| `.pflow.md` | Yes | Yes (glob `*.pflow.md`) | Full |
| `.pflow` | No | Yes | None without config |

**Decided**: `.pflow.md` — gets GitHub rendering, IDE markdown support, and is distinguishable from regular markdown files.

### ~~2. Linting scope~~ → DECIDED

**Decision**: Syntax validation only for Task 107:
- **Python code blocks**: `ast.parse()` at parse time — catches syntax errors with markdown line numbers. No template variable issues (code blocks don't contain `${...}`; templates are in `inputs` param).
- **YAML config blocks**: `yaml.safe_load()` — already doing this for the parser.
- **Shell/prompt blocks**: Nothing at parse time. Errors caught at runtime.

**Future tasks (separate)**:
- **Task 118**: Full linting — ruff + shellcheck, potentially bundled with shell node refactor to inject template values as bash variables (instead of inline replacement). Evaluate ruff wrapper generation, `pflow validate --lint` command, ruff as runtime dependency (~26 MB).
- **[Issue #76](https://github.com/spinje/pflow/issues/76)**: Pre-execution validation for required node parameters — add `required: bool` to interface metadata, validate during compilation.

**In scope for Task 107**: Unknown param warnings — compare params against `interface["params"]` keys during compilation. Catches typos and the `-` bullet footgun. Uses existing infrastructure (template validator already loads registry metadata).

---

## Ruled Out (don't re-explore)

- **Python DSL format**: pflow is fundamentally declarative. Python-in-Python for code nodes is absurd. Markdown handles code blocks naturally.
- **Hybrid approach**: Python authoring with IR storage. Unnecessary complexity.
- **JSON as input format**: No users, no backwards compatibility. One format is simpler.
- **Round-trip conversion**: One-way (markdown to dict) is sufficient.
- **Multi-file workflows**: Future work.
- **Cross-node type checking**: `.pyi` stubs and mypy integration — speculative, not MVP.
- **YAML frontmatter for authoring**: Creates three syntax zones. Section headings provide the same structure with pure markdown. (Frontmatter IS used for system metadata in saved workflows — but agents never write it.)
- **Bare YAML params (no `-` prefix)**: Lacks visual distinction from prose in editors. `- ` gives bullet point rendering.
- **`- ` as custom parser (not YAML)**: Prevents nesting. Agents will try YAML nesting and it should work.
- **Different syntax for inputs vs outputs vs nodes**: Creates inconsistency. When complex outputs need code blocks they'd look different from simple outputs. One pattern for everything.
- **Batch items as sub-headings (`####`)**: Pushes to 4-5 heading levels. YAML code blocks handle batch config better.
- **`yaml` as code block tag**: Doesn't name a parameter. All code block tags must name the param they map to.

---

## Key Design Insights

### "If the .md was JUST documentation, how would you expect it to look?"

This reframe from the user shaped the entire format. The answer: a document with sections (Inputs, Steps, Outputs), sub-headings for each entity, bullet-point properties, and code blocks for code. This is exactly what we built.

### LLMs generate what they've been trained on

The format should look like the markdown documents LLMs have seen billions of times: READMEs, API docs, SOPs, runbooks. Heading hierarchy, bullet lists, code blocks. Nothing novel. The less an LLM has to "learn," the fewer errors it makes.

### Content types need appropriate highlighting

Shell commands need bash highlighting. Python needs Python highlighting. Prompts need to be readable text. YAML config needs YAML highlighting. Putting everything in one format (like all-YAML) gives wrong highlighting to most content. The `language param_name` code block pattern lets each content type get the highlighting it deserves.

### Data flows top-to-bottom

Inputs at the top (define before use), nodes in execution order (each can reference above), outputs at the bottom (reference everything above). This mirrors both the execution model and how LLMs build context when reading sequentially.

### Consistency over brevity

Simple inputs could be one-line list items. Simple outputs could be list items. But then complex outputs (with source templates) need headings. Having two visual weights for the same concept creates inconsistency. One pattern (`###` heading + params + optional code blocks) everywhere, even if slightly verbose for simple cases, eliminates this.

---

## Verified Assumptions (from codebase investigation)

### ✅ `normalize_ir()` adds `ir_version`

Confirmed at `ir_schema.py:559-592`. Adds `ir_version: "0.1.0"`, empty `edges: []`, and normalizes `parameters` → `params`. Called from CLI, MCP server, and workflow save service. The markdown parser can rely on this.

### ✅ `purpose` field is dead code at runtime

The field is optional in the IR schema (`ir_schema.py:200-203`, not in required list). It is NOT used by: compiler, runtime, CLI display (`pflow workflow describe`), MCP server, error messages, or validation. Only the legacy planner references it. Safe to populate from node prose descriptions — it won't break anything and may be useful for future display features.

### ✅ Top-level node fields: only `id`, `type`, `purpose`, `params`, `batch`

Confirmed at `ir_schema.py:197-212` with `additionalProperties: False`. Only `batch` is a special case for the code block mapping. No other hidden top-level fields exist.

### ✅ YAML `${...}` template variables preserved as literal text

PyYAML `safe_load()` treats `${target_url}` as plain string content. No special interpretation, no clashes. Template resolution happens at pflow runtime, not during YAML parsing.

### ✅ YAML type coercion matches JSON exactly

`int`, `bool`, `float`, `str`, `list` types produced by PyYAML match what `json.loads()` produces for the same values. No type mismatch between YAML-parsed params and what the IR expects.

**Gotcha**: YAML converts unquoted `yes`/`no`/`on`/`off` to Python booleans. This is standard YAML behavior but should be documented. Agents should quote these values when they want strings: `- value: "yes"`.

### ⚠️ Unknown params are silently accepted

`params` has `additionalProperties: True` in the schema. Nodes use `.get()` pattern and ignore unknown keys. This means documentation bullets accidentally parsed as `- key: value` params will **NOT cause errors** — they'll silently pass through. The workflow still executes correctly (unknown params have no effect), but the documentation line is consumed as a param instead of being treated as prose.

**Risk assessment**: Low severity (workflow works), but it means the `- ` vs `*` bullet convention is a silent-failure footgun rather than a caught-error footgun. Agent instructions must be very clear about using `*` for documentation bullets. Consider adding a **warning** (not error) for params that don't match known fields for a node type — this would catch most accidental documentation-as-param cases.
