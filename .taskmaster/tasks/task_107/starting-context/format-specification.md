# Task 107: Markdown Workflow Format — Complete Specification

> Single source of truth for the markdown workflow format design. Contains all 25 design decisions, verified codebase facts, parsing rules, implementation guidance, and design context.
>
> **The format is settled.** Don't redesign it. If you find an edge case, add a parsing rule — don't change the format.
>
> **No implementation has been done.** The next step is implementation planning.

---

## Format Overview

The markdown workflow format uses standard markdown structure with one universal pattern:

```
#     Workflow title + description prose
##    Section (Inputs, Steps, Outputs)
###   Entity (input, node, or output)
        prose text      → description (inputs/outputs → `description`, nodes → `purpose`)
        - key: value    → params (YAML list items, merged into dict)
        ```lang param```→ code blocks (content or structured data)
```

Three heading levels maximum. Everything follows the same `### heading` + prose description + `- key: value` params + optional code blocks pattern. No frontmatter in authored files (saved workflows get system metadata frontmatter). No special syntax for different entity types.

### Short Example

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

## Design Decisions

### 1. Markdown-only file format

**Decision**: Markdown replaces JSON as the workflow file format. JSON workflow files are no longer supported as input. File extension: `.pflow.md`.

**Reasoning**:
- Zero users means zero backwards compatibility concerns
- No format detection logic needed — one parser, one format
- Error messages can be markdown-specific without conditional formatting
- Agent instructions teach one format only
- The internal dict representation remains for programmatic use (MCP server tools, visualization, export)
- `.pflow.md` gives GitHub rendering, IDE markdown support, and is distinguishable from regular markdown via `*.pflow.md` glob

**What this does NOT change**: The in-memory dict (IR) that validation, compilation, and execution operate on stays the same. Markdown is just a different way to produce that dict.

### 2. Markdown compiles to internal dict, not to JSON

**Decision**: `parse_markdown(content) -> MarkdownParseResult` produces the same dict shape that `json.load()` currently produces. No JSON intermediate step.

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

**Verified**: Validation operates on the dict structure (node types, edges, templates, outputs). It does not reference JSON syntax in its core logic. ~10-12 error messages mention "JSON" explicitly (see Architecture Findings).

### 4. Edges from document order

**Decision**: No explicit edge declarations. Execution order is determined by the order of `###` headings in the `## Steps` section. Top to bottom.

**Reasoning**: pflow is currently linear-only (Tasks 38 and 39 are future work). Document order is the natural way to express sequence in a markdown document. When conditionals/parallel are implemented, explicit edge syntax can be added.

**Example**: If nodes appear as `### fetch`, `### analyze`, `### format`, the parser generates edges: fetch → analyze → format.

**Section naming**: "Steps" was chosen over "Workflow" (redundant — the whole file is a workflow), "Nodes" (too technical), and "Pipeline" (too specific). "Steps" is the most natural documentation word — SOPs, runbooks, and tutorials all use "Steps."

### 5. Prose as description (all entities)

**Decision**: Prose is preserved for all entities, serving different roles:

| Context | Prose becomes | IR field | Used at runtime? |
|---------|--------------|----------|-----------------|
| After `#` title (until first `##`) | Workflow description | Outside IR (metadata) | Yes — search, display in `pflow workflow list` |
| After `###` input heading | Input description | `inputs.{name}.description` | Yes — help text, validation messages |
| After `###` output heading | Output description | `outputs.{name}.description` | Yes — interface documentation |
| After `###` node heading | Node description | `purpose` field on node | No — dead code at runtime, but forces documentation |

**Reasoning**: Interface descriptions (workflow, inputs, outputs) are used programmatically — they appear in `pflow workflow describe`, search results, and validation messages. Node prose is saved to the `purpose` field (effectively dead code at runtime) but forces the author to articulate intent. Low overhead to store it, and it may become useful for future display features.

**Note on workflow `description`**: This field lives OUTSIDE the IR dict — it's in the WorkflowManager metadata wrapper. In the markdown format, it comes from the H1 prose (between `#` title and first `##`). When saving workflows, agents no longer need to specify description separately — it's extracted from the markdown content.

This replaces the old JSON `purpose` field with something far more expressive — free-form prose instead of a single constrained line.

**Descriptions are required** for all entities (inputs, outputs, and nodes). A node without a description is a validation error:

```
Node '### analyze' (line 30) is missing a description.

Add a text paragraph between the heading and the parameters:

    ### analyze

    Description of what this node does and why.

    - type: llm
```

### 6. One code block per param-name tag per entity

**Decision**: Each entity can have at most one code block per param-name tag. Two `prompt` blocks under the same heading is a validation error. Different tags are fine (e.g., an LLM node with both `prompt` and `batch` blocks).

### 7. Document structure: sections with headings, no authoring frontmatter

**Decision**: The authored document uses `#` for workflow title, `##` for sections (Inputs, Steps, Outputs), and `###` for all entities. No YAML frontmatter in authored files.

**Reasoning**:
- The section approach matches how documentation is naturally written (like an SOP: inputs, steps, outputs)
- LLMs have seen this document structure billions of times in training data
- The format should look like documentation because "documentation IS the workflow"
- Data flows top-to-bottom: inputs defined first, then used by nodes, then outputs reference node results
- Frontmatter mixes three syntax zones (YAML + markdown + code blocks) — more to learn

**Alternatives explored**:
1. **YAML frontmatter** for inputs/outputs — rejected because it creates a different syntax zone that's inconsistent with how nodes work.
2. **Flat `##` headings for everything** (no sections) — rejected because the parser can't distinguish inputs from nodes from outputs without heuristics. Implicit detection by field content (`type: string` = input, `type: http` = node, `source: ...` = output) is fragile.
3. **`##` sections without `## Steps` wrapper** — considered, but the explicit sections provide clear boundaries and match natural documentation structure (Parameters → Steps → Results).
4. **Deeper nesting** (`####` for batch items, `#####` for individual items) — this works for cases where items have text content (batch items with long format_rules), but adds heading depth and complexity. Rejected: YAML is the right tool for structured data. Heading hierarchy is for named entities in the workflow, not for data structures.

**How it was arrived at**: The user asked "if the .md document was JUST documentation, how would you expect it to look?" Writing it as natural documentation produced: H1 title, sections for Inputs/Steps/Outputs, sub-headings for individual items.

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

**Reserved section names**: `Inputs`, `Steps`, `Outputs` (case-insensitive — `## inputs`, `## Inputs`, `## INPUTS` all valid; parser normalizes). Unknown `##` sections are silently ignored (agents can add `## Notes`, `## Design Decisions`, etc. as documentation). **Near-miss warning**: `## Input`, `## Output`, `## Step` (missing 's') produce a warning — almost certainly typos.

**Optional sections**: `## Inputs` and `## Outputs` are optional. `## Steps` is required (must have at least one node). `# title` is optional (name comes from filename).

**Maximum depth**: Three heading levels (`#`, `##`, `###`). Hard guarantee. Nothing pushes deeper.

### 8. One universal pattern for all entities

**Decision**: Inputs, nodes, and outputs ALL use the same pattern: `###` heading + prose description + `- key: value` params + optional code blocks.

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

**Why this matters**: One mental model for everything. An LLM doesn't need to remember "inputs use YAML blocks, nodes use list items, outputs use headings." It's the same pattern everywhere.

**How it was arrived at**: We initially proposed different syntax for inputs (YAML code blocks), nodes (`- key: value`), and outputs (nested list items). Each worked in isolation but created inconsistencies when mixed. The user pushed for consistency: "shouldn't inputs follow the same syntax as nodes?" The decisive moment was discovering that outputs can need code blocks too (for complex source templates) — meaning outputs need headings → same pattern as nodes → why not make inputs the same?

**Complex outputs forced this unification**. In JSON, a complex output template is a single escaped string: `"source": "# Release v${version}\n\n## Changelog\n${format.response}\n..."`. In markdown, it's a code block:

Simple output (inline):
```markdown
### file_path

Path to the saved file on disk.

- source: ${compute-filename.stdout}
```

Complex output (code block):
````markdown
### report

Full release report combining changelog and all platform announcements.

```markdown source
# Release v${version}

## Changelog
${format.response}

## Announcements
${draft-slack.response}
```
````

If outputs need code blocks, they need heading sections → they follow the same universal pattern → one mental model for everything.

### 9. Params as YAML list items with merge

**Decision**: `- key: value` lines are parsed as a YAML sequence (list of single-key mappings) and merged into a single dict.

**Reasoning**:
- `- ` prefix gives visual bullet points in editors — distinguishes params from prose
- Parsing as YAML means nesting works naturally when needed
- Merge step (list of single-key dicts → single dict) is trivial
- Agents will instinctively try YAML nesting under `-` items — it should work

**Simple case** (flat params):
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

YAML nesting under a `- ` item works naturally. The indentation is relative to the `-`. 95% of params are flat `- key: value`. Indentation only appears for genuinely nested structures. This avoids the indentation gymnastics that made other approaches feel heavy.

**Why `- ` prefix instead of bare YAML?** We explored bare YAML with blank-line separation from prose. Problems: no visual distinction from prose in editors (`type: http` and a sentence look identical), and the `- ` prefix renders as bullet points in markdown preview — visually distinct and scannable.

**Why not a YAML code block for all properties?** Every node would need a code block even for `type: shell` — unnecessary ceremony. And shell commands, prompts, and Python code need their own language-specific code blocks for proper highlighting. Putting them in YAML (with `|` block scalars) gives wrong highlighting.

**Why parse as YAML instead of simple line splitting?** LLMs will naturally try YAML nesting when they see `- key:` syntax. If we use a simple splitter, nesting silently fails. YAML parser means nesting works correctly.

**When to use inline vs code block**: Simple flat values stay as `- key: value`. When a value is a nested object, array of objects, or multi-line structure, it goes in a YAML code block (e.g., `yaml headers`, `yaml batch`).

### 10. Code block tag pattern: `language param_name`

**Decision**: Code block info string uses `language param_name` format. First word = language for editor highlighting. Last word = param name for parser mapping. If only one word, it serves as both.

**The rule**: Last word is always the param name. Preceding word (if any) is the language hint. The parser ignores the language word.

**How it was arrived at**: Initially we used the param name alone (`batch`, `stdin`, `headers`). Consistent but meant no syntax highlighting for YAML-content blocks in editors. We then adopted the CommonMark info string pattern where the first word is the language — YAML highlighting for config, bash for shell, Python for code, agent's choice for prompts.

**Future simplification**: When `command` is renamed to `shell` and `code` is renamed to `python` in the IR, those blocks simplify to just `shell` and `python`. YAML config blocks will always need the two-word form since `yaml` is a language, not a param.

### 11. Flexible prose and param placement

**Decision**: Prose can appear anywhere — before params, after params, between code blocks. All `- key: value` lines are always treated as params regardless of position.

**Reasoning**: Maximum flexibility for documentation. Agents and humans can write prose wherever it makes sense — explaining a param choice, documenting a design decision between code blocks, or adding context before the params. The format should not constrain natural writing patterns.

**Parsing rule**: The parser scans all lines in the `###` entity:
- Lines starting with `- ` (plus indented continuations) → collected as YAML params
- Code block fences → extracted as code blocks
- Everything else → prose (`description` for inputs/outputs, `purpose` for nodes)

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

**For documentation bullet lists**: Use `*` instead of `-` to avoid being parsed as params. All `-` lines outside code blocks are params. All `*` lines are prose.

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

**Risk**: An LLM that doesn't notice the content contains backticks will produce a broken document. Error messages should detect unclosed code blocks and suggest using more backticks.

### 13. Node IDs from headings, must be valid format

**Decision**: The `###` heading text IS the entity ID directly. No normalization. Must be lowercase alphanumeric with hyphens or underscores (no spaces).

**Verified**: Current IR has no explicit ID format validation. Convention in existing examples is `snake_case`. We enforce valid format at the markdown parser level.

### 14. Type stubs / mypy integration is NOT in scope

**Decision**: No `.pyi` stub generation. No mypy integration. The code node validates type annotations at runtime.

### 15. Error messages should be markdown-native

**Decision**: Errors reference markdown structure (headings, code blocks, line numbers), not abstract IR paths.

**Current**: `"'type' is a required property at nodes[0]"`
**Target**: `"Node '### analyze' (line 15) missing required 'type' parameter"`

The parser must track source line numbers and front-load structural validation (see Implementation Guidance for why a source map is NOT needed).

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

**Migration**: WorkflowManager currently stores saved workflows as `~/.pflow/workflows/{name}.json` with a JSON metadata wrapper (`{"description": "...", "ir": {...}, "created_at": "...", ...}`). This changes to `~/.pflow/workflows/{name}.pflow.md` with YAML frontmatter for metadata and the markdown body replacing the `ir` field.

**Note**: The workflow `description` (from H1 prose) replaces the separate `description` field that was in the old JSON metadata wrapper. Agents no longer need to specify description separately when saving — it's extracted from the markdown content. All other metadata maps 1:1 from the old JSON wrapper to frontmatter fields.

**Parser behavior**: If frontmatter exists, extract metadata and pass to WorkflowManager. If not, it's a clean authoring file. The workflow body is identical either way. The parser handles frontmatter stripping naturally — no separate unwrapping logic needed (replacing the current `data["ir"]` unwrapping in JSON loading).

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

**Reasoning**: Duplicate definitions are ambiguous. Fail fast with a clear error.

### 19. Code blocks without info string are errors

**Decision**: Bare code blocks (no language/param tag) are validation errors. The error should suggest the likely tag based on node type.

```
Code block at line 12 has no tag.
For a 'llm' node, did you mean ```prompt or ```markdown prompt?
```

### 20. `ir_version` handled by normalize_ir()

**Decision**: The markdown format has no explicit `ir_version` field. The existing `normalize_ir()` function adds it when missing.

**Verified**: `normalize_ir()` (`ir_schema.py:559-592`) adds exactly 3 things:
1. `ir_version: "0.1.0"` if missing
2. `edges: []` if missing (and no `flow` field)
3. Renames `parameters` → `params` in nodes

The parser SHOULD generate edges from document order (Decision 4), so `edges` will already be present.

### 21. `batch` and `source` map to top-level fields (not params)

**Decision**: The `yaml batch` code block maps to the node-level `batch` field, not `params.batch`. Similarly, `source` code blocks/params in outputs map to the output-level `source` field, not `params.source`. Agents don't need to know about the `params` wrapper — the parser handles routing.

**Verified**: The complete set of top-level node fields (`ir_schema.py:197-212`, `additionalProperties: False`):

| Field | Required | Maps from |
|-------|----------|-----------|
| `id` | Yes | `###` heading text |
| `type` | Yes | `- type:` param (extracted from params, moved to top level) |
| `purpose` | No | All prose within entity (joined with `\n\n`, stripped) |
| `params` | No | All other `- key: value` params + code block content |
| `batch` | No | `yaml batch` code block |

The parser routes: `type` → top-level, prose → `purpose`, `yaml batch` → top-level `batch`, everything else → `params`.

### 22. Description concatenation strategy

**Decision**: All prose text within an entity is concatenated by joining paragraphs with `\n\n` (double newline). Leading and trailing whitespace is stripped.

**Scope**:
- **Workflow**: Prose between `#` title and first `##` heading only → `description` (in metadata, not IR)
- **Inputs and outputs**: All prose within the `###` entity → `description` field in IR
- **Nodes**: All prose within the `###` entity → `purpose` field in IR

The `purpose` field is optional in the IR schema, not used by compiler, runtime, CLI display, MCP server, or validation. It exists only in the planner's IR models (legacy). The description is still **required** by the parser (forces documentation), even though `purpose` is effectively dead code at runtime.

**Example**: Prose before params AND after params:
```markdown
### analyze

Classifies each commit as user-facing or internal.

- type: llm
- model: gpt-4

We chose GPT-4 over cheaper models because accuracy matters
more than cost for commit classification.
```

Purpose: `"Classifies each commit as user-facing or internal.\n\nWe chose GPT-4 over cheaper models because accuracy matters\nmore than cost for commit classification."`

### 23. Error suggestion examples show markdown syntax

**Decision**: All error messages that include "correct format" examples must show markdown syntax, not JSON.

**Current** (JSON, in `ir_schema.py:370-387` `_get_output_suggestion()`):
```
Example:
  "story": {
    "source": "${generate_story.response}"
  }
```

**Target** (markdown):
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

**Decision**: Build a custom state machine parser. No dependency on mistune, markdown-it-py, or any markdown library.

**Reasoning** (validated by 4 independent assessments):
- The format is a DSL using markdown syntax, not a markdown document. Libraries optimize for rich text rendering — we need structured data extraction.
- The hard part (`- ` line collection with YAML continuations) is custom logic regardless.
- Libraries parse `- key: value` as markdown list items, which interferes with our YAML parsing.
- Line number tracking is free with line-by-line scanning, painful with AST reconstruction.
- A library risks **silent failures** (ambiguous indentation parsed into wrong AST structure). A custom parser fails loudly with clear errors.
- ~250-350 lines of focused, testable code. Only dependency: PyYAML (already used).

**Implementation approach**:
- State machine scanning lines: headings, code fences, `- ` params, prose
- Delegate YAML parsing to `yaml.safe_load()`
- Delegate Python syntax checking to `ast.parse()`
- Track line numbers throughout for markdown-native error messages
- Write test cases first (valid workflows, edge cases, error conditions)

**Escape hatch**: If YAML continuation tracking proves too complex, nested params can be restricted to `yaml` code blocks (e.g., `yaml headers` instead of indented `- headers:` with sub-keys).

### Validation & linting scope

**In scope for Task 107**:
- `ast.parse()` for Python code blocks at parse time — catches syntax errors with markdown line numbers. No template variable issues (code blocks don't contain `${...}`; templates are in `inputs` param).
- `yaml.safe_load()` for YAML config blocks — already part of parsing
- Unknown param warnings — compare against registry interface metadata during compilation
- All markdown-specific validation (Decision 24)

**Out of scope**:
- Full linting (ruff, shellcheck) → Task 118. Potentially bundled with shell node refactor to inject template values as bash variables (instead of inline replacement). Evaluate ruff wrapper generation, `pflow validate --lint` command, ruff as runtime dependency (~26 MB).
- Required param pre-validation → [Issue #76](https://github.com/spinje/pflow/issues/76). Needs `required: bool` added to interface metadata.
- Type stubs / mypy → Decision 14
- Shell node refactor for variable injection → Task 118
- Round-trip conversion (markdown ↔ JSON)
- Multi-file workflows

---

## Code Block Mapping

### Content blocks (text/code)

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
| `yaml batch` | YAML | `batch` config (top-level) | any batched node |
| `yaml stdin` | YAML | `params.stdin` | nodes with complex stdin |
| `yaml headers` | YAML | `params.headers` | http nodes |
| `yaml output_schema` | YAML | `params.output_schema` | claude-code nodes |

The agent chooses the language that best matches the content. The parser only uses the last word (param name). Any `yaml param_name` pattern works for arbitrary complex params.

**Key insight** — how the agent picks the language:
- A prompt with markdown formatting → `markdown prompt`
- A prompt that's plain text → `prompt`
- An output template that's markdown → `markdown source`
- An output template that's JSON → `json source`

---

## Parsing Rules

1. **Check for frontmatter** — if `---` markers at start of file, extract system metadata (saved workflows only). Strip before processing body.

2. **Extract H1** — workflow title from heading. All prose between `#` and first `##` = workflow `description` (stored outside IR, in metadata).

3. **Split by H2** — identify `## Inputs`, `## Steps`, `## Outputs` sections (case-insensitive). Inputs and Outputs optional. Steps required. Unknown sections silently ignored. **Warning** for near-misses: `## Input`, `## Output`, `## Step` (missing 's').

4. **Within each section, split by H3** — each `###` heading is an entity (input, node, or output).

5. **For each entity**:
   a. Heading text = entity ID/name
   b. Extract code blocks (by fence markers, from anywhere in the entity)
   c. Collect `- ` prefixed lines (with indented continuations) from anywhere = YAML params
   d. Parse params as YAML sequence, merge into single dict
   e. Remaining text = prose → joined with `\n\n`, stripped → `description` for inputs/outputs, `purpose` for nodes

6. **Validate descriptions** — all entities (inputs, outputs, nodes) must have prose description text.

7. **Code block validation** — no bare code blocks (suggest tag based on node type). No duplicate param definitions (inline + code block).

8. **Generate edges** from document order of `###` headings in `## Steps`.

9. **Compile to IR dict** in the same shape as current JSON workflows.

10. **Run existing validation** on the dict.

### Parser return type

The parser returns more than just the IR dict. Different callers need different fields:

```python
@dataclass
class MarkdownParseResult:
    ir: dict[str, Any]                    # The workflow IR dict
    title: str | None                     # H1 heading text
    description: str | None               # H1 prose (between # and first ##)
    metadata: dict[str, Any] | None       # Frontmatter (None for authored files)
```

Most callers use `.ir`. WorkflowManager uses all fields (metadata for timestamps/stats, description for display, title for search).

---

## Architecture Findings

### Verified codebase facts

**normalize_ir()** — confirmed at `ir_schema.py:559-592`. Adds `ir_version: "0.1.0"` if missing, `edges: []` if missing (and no `flow` field), renames `parameters` → `params` in nodes. Called from CLI, MCP server, and workflow save service. The markdown parser should produce a dict WITHOUT `ir_version` but WITH `edges` (from document order).

**Top-level node fields** — confirmed at `ir_schema.py:197-212`. Only 5 fields with `additionalProperties: False`: `id`, `type`, `purpose`, `params`, `batch`. Critical: `type` goes top-level (NOT `params`), `batch` goes top-level (NOT `params`), `source` on outputs goes to output dict directly.

**`purpose` field** — optional in IR schema. NOT used by: compiler, runtime, CLI display, MCP server, error messages, or validation. Only the legacy planner references it. Safe to populate from node prose.

**YAML template variables** — PyYAML `safe_load()` treats `${target_url}` as plain string. No special interpretation.

**YAML type coercion** — matches JSON exactly. `int`, `bool`, `float`, `str`, `list` all match. **Gotcha**: unquoted `yes`/`no`/`on`/`off` become booleans. Agents should quote: `- value: "yes"`.

**Unknown params** — `params` has `additionalProperties: True`. Nodes use `.get()` and ignore unknown keys. Documentation bullets accidentally parsed as `- key: value` pass silently. This is why the unknown param warning is in scope.

**Template validation** — `TemplateValidator` runs during `compile_ir_to_flow()` and catches `${nonexistent_node.output}`, `${fetch.nonexistent_field}`, malformed `${unclosed`, and type mismatches — all before execution. No new work needed in the markdown parser for template validation.

**Required params** — each node checks its own in `prep()` (e.g., `if not url: raise ValueError`). No pre-execution check exists. The compiler does NOT validate params against interface metadata. [Issue #76](https://github.com/spinje/pflow/issues/76) tracks adding this.

**Code node validation** — the code node's `prep()` validates `_check_input_annotations()` (every `inputs` key must have a matching type annotation) and `_check_input_types()` (`isinstance()` check). Happens at runtime, not compile time. The markdown parser doesn't need to duplicate this.

**Why code node uses separate `inputs` dict** — template resolution inside code strings would produce JSON-serialized strings, not Python objects. `${fetch.result}` (a list) would become `[{"id": 1}]` as a string literal, breaking `ast.parse()`. The `inputs` dict uses `resolve_nested()` which preserves native Python types, then injects them into the `exec()` namespace.

**Registry interface metadata** — `interface["params"]` gives a list of `{"key": "url", "type": "str", "description": "..."}` dicts. Template validator already loads this during compilation. Unknown param warning can reuse this data. No `required: bool` field exists — required/optional is only in description text.

**Input schema** — has 5 fields with `additionalProperties: False`: `description`, `required` (bool, default true), `type` (enum), `default` (any), `stdin` (bool, default false — for piped stdin data). The `stdin` field must be supported: `- stdin: true`.

**Output schema** — has 3 fields with `additionalProperties: False`: `description`, `type` (enum: string/number/boolean/object/array), `source` (template expression). Outputs can have `- type: string` just like inputs.

**Workflow `description`** — lives OUTSIDE the IR. Top-level IR has NO `description` field (`additionalProperties: False`). It's in the WorkflowManager metadata wrapper. Parser extracts it from H1 prose and exposes via `MarkdownParseResult.description`.

**Unused top-level IR fields** — the full IR has 9 fields. Parser only produces `nodes`, `edges`, `inputs`, `outputs`. The rest use defaults: `ir_version` (added by normalize_ir), `start_node` (always first node), `mappings` (default `{}`), `enable_namespacing` (default `true`), `template_resolution_mode` (default `"strict"`).

**Error system structure** — errors use a three-part structure: `UserFriendlyError` with `title`, `explanation`, `suggestions`; `ValidationError` with `message`, `path`, `suggestion`. Error paths currently use bracket notation (`nodes[0].type`). For markdown, parser-level errors should reference source: `node "### fetch" (line 15)`.

### Integration points (7 JSON parse points)

Every place a workflow file is loaded from disk, needing update to use the markdown parser:

| # | File | Line | Function | Context |
|---|------|------|----------|---------|
| 1 | `src/pflow/cli/main.py` | 172 | `_try_load_workflow_from_file()` | CLI loads workflow from path |
| 2 | `src/pflow/runtime/compiler.py` | 157 | `_parse_ir_input()` | Compiler accepts string input |
| 3 | `src/pflow/core/workflow_manager.py` | 205 | `load()` | Loads saved workflows |
| 4 | `src/pflow/mcp_server/utils/resolver.py` | 61 | `resolve_workflow()` | MCP resolves file paths |
| 5 | `src/pflow/runtime/workflow_executor.py` | 246 | `_load_workflow_from_path()` | Nested workflow loading |
| 6 | `src/pflow/core/workflow_save_service.py` | 176 | `_load_from_file_path()` | Workflow save operations (CLI/MCP) |
| 7 | `src/pflow/planning/context_builder.py` | 255 | `_try_load_workflow()` | Discovery workflow scanning |

Everything downstream operates on dicts. No changes needed to compiler, validator, or executor logic.

### Error messages mentioning JSON (~10-12 places)

| File | Line | Message | Action |
|------|------|---------|--------|
| `cli/main.py` | 133 | "Invalid JSON syntax in {path}" | Replace with markdown parse errors |
| `cli/main.py` | 155 | "Fix the JSON syntax error" | Replace |
| `ir_schema.py` | 481 | "Invalid JSON: {e}" | Replace with YAML/structure errors |
| `ir_schema.py` | 370-387 | `_get_output_suggestion()` shows JSON examples | Update to markdown syntax (Decision 23) |
| `workflow_manager.py` | 214 | "Invalid JSON in workflow" | Update for .pflow.md format |
| `workflow_executor.py` | 248 | "Invalid JSON in workflow file" | Update for nested workflows |
| `workflow_executor.py` | 254 | "Workflow must be a JSON object" | Update |
| `workflow_validator.py` | 497 | "Replace JSON string with object syntax" | Remove (JSON anti-pattern not relevant) |
| `workflow_save_service.py` | 183 | "Invalid JSON in {path}: {e}" | Update for markdown format |
| `mcp_server/utils/resolver.py` | 64 | "Invalid JSON in file: {e}" | Update for markdown format |

Additional MCP config messages (`mcp/manager.py`, `cli/mcp.py`) mention JSON but are about MCP server configs, not workflows — no change needed.

---

## Implementation Guidance

### Source map NOT needed (line numbers and IR validation)

The parser produces an IR dict, then existing validators run on it. Concern: validators produce errors with abstract IR paths like `nodes[0].type` — no markdown line numbers. Do we need a source map to translate these?

**Verified answer: No.** The validation layers fall into two categories:

1. **Structural validation** (jsonschema in `validate_ir()`): Produces `nodes[0].type` style paths. But the **parser can and should catch all of these first** — it knows when a node has no `- type:` param, it controls field routing, and it always produces `id` from headings. If the parser validates structural completeness, jsonschema becomes a safety net that never triggers.

2. **Semantic validation** (template validator, data flow, node types): Already uses **node IDs by name**. E.g., `"Node 'fetch-messages' template ${fetch-messages.msg} references non-existent output 'msg'"`. No abstract paths — user can find `### fetch-messages` easily.

**Conclusion**: The parser IS the line number mechanism. It front-loads structural validation with markdown line numbers. Semantic errors already reference node names. A source map is unnecessary complexity.

**If we're wrong**: Adding a source map later is straightforward — the parser already tracks line numbers.

### The `-` bullet footgun (most important risk)

The format uses `- key: value` for params and `*` for documentation bullets. LLMs default to `-` for markdown bullets. If an LLM writes:

```markdown
- Note: this uses Jina Reader for better quality
- type: http
```

The `Note` line becomes a param. Since unknown params are silently accepted, no error occurs.

**Mitigations**:
1. Clear agent instructions about `*` for bullets
2. Unknown param warning at compile time (in scope) — would flag "unknown param `Note` on http node"
3. The param would have no effect on execution (workflow still works correctly)

**Risk level**: Low severity (workflow works), medium probability (LLMs use `-` by default). The unknown param warning is the key mitigation.

### Parser core complexity: `- ` line collection

The parser must:
1. Track whether it's inside a code fence (don't collect `- ` lines from inside code blocks)
2. Collect `- ` lines AND their indented continuations (for nested YAML like `- headers:` with indented sub-keys)
3. Collect from non-contiguous positions (prose can appear between `- ` lines)
4. Join collected lines and parse as YAML sequence
5. Merge the resulting list of single-key dicts into one dict

The indentation continuation rule: any `- ` line PLUS subsequent lines that are indented more than the `-`, until the next `- ` line or non-indented non-blank line.

### `ast.parse()` for Python code blocks

Python code blocks don't contain `${...}` template variables (those are in the `inputs` param). So `ast.parse()` works directly on the code content with no placeholder tricks. Run at parse time and report errors with markdown line numbers.

### `_is_path_like()` check in CLI

The CLI has `_is_path_like()` that determines if the first argument is a file path vs. a saved workflow name. It currently checks for `.json` extension. Needs to also check for `.pflow.md`.

### Empty sections are valid

`## Inputs` with no `###` headings = no inputs. Same for `## Outputs`. `## Steps` with no `###` headings = error (a workflow needs at least one node).

### Parser strictness

Default should be strict with helpful error messages. Required descriptions, no bare code blocks, duplicate param errors. Ignoring unknown `##` sections (silently, with near-miss warnings) is the exception.

### Edge cases

**`images` param on LLM nodes**: `- images: ${item}` is inline. But complex structures (array with metadata) could use `yaml images` code block. The pattern should work.

**Non-contiguous YAML `- ` lines**: Collecting `- type: llm` and `- model: gpt-4` from scattered lines (with prose between), joining with newlines — YAML parses this correctly as a sequence. Verify with actual parser behavior when items have indented continuations from non-adjacent lines.

### Unexplored territory (not blocking)

**`pflow workflow describe`**: Currently reads JSON. With markdown, could render directly or extract from parsed IR.

**Agent instructions**: `pflow instructions create --part 1/2/3` teaches JSON format. Needs complete rewrite for markdown. Not part of Task 107 but needed before launch.

**MCP server workflow creation**: `run_workflow` MCP tool accepts dicts (no change). MCP tools that accept file paths or create files need the markdown parser/writer.

**Converting examples**: `examples/` directory has JSON workflows needing conversion to `.pflow.md`. Good test cases.

### For the implementing agent

**Don't read** the braindump files in `starting-context/`. They're pre-design exploration, superseded by this document.

**Start with a real workflow, not tests.** Write a complete markdown file, then parse it. The complete example below is a good starting point.

**Build line number tracking from the start.** Every element the parser extracts should carry its source line number. (A source map for IR validation is NOT needed — see above.)

**Test `batch` and `type` routing early.** Verify `yaml batch` → `node["batch"]` not `node["params"]["batch"]`, and `- type: http` → `node["type"]` not `node["params"]["type"]`.

**The 7 JSON parse points are your integration checklist.** Test each independently.

**Unknown param warning is in scope.** During compilation, compare params against `interface["params"]` keys. Flag unknowns with "did you mean?" suggestions.

**Parser must validate structural completeness.** Catch all issues that jsonschema would catch (missing `type`, unknown fields, etc.) with markdown line numbers. Jsonschema validation becomes a safety net that never triggers.

---

## Complete Example

Full webpage-to-markdown workflow converted from JSON (7 nodes, batch processing, multiple outputs):

`````markdown
# Webpage to Markdown

Convert a webpage to clean markdown with AI-powered image analysis.
Uses Jina Reader for initial conversion and Gemini vision for image descriptions.

## Inputs

### target_url

Webpage URL to convert to markdown. Supports any publicly accessible URL.

- type: string
- required: true

### output_file

Output file path. Use 'auto' to generate from URL with date prefix.

- type: string
- default: "auto"

### describe_images

Use vision AI to extract content from images found in the page.

- type: boolean
- default: true

## Steps

### compute-filename

Generate output filename from URL with date prefix, or use provided output_file.

- type: shell

```shell command
if [ '${output_file}' != 'auto' ]; then
  printf '%s' '${output_file}'
else
  name=$(printf '%s' '${target_url}' | sed 's|[?#].*||; s|/$||; s|.*/||; s|\\.[^.]*$||')
  [ -z "$name" ] && name='article'
  printf '%s' "./$(date +%Y-%m-%d)-$name.md"
fi
```

### fetch

Fetch markdown via Jina Reader. We use Jina over direct fetching because
it handles SPAs and paywalled content better.

- type: http
- url: https://r.jina.ai/${target_url}

### extract-images

Extract image URLs from markdown. Returns empty array if describe_images is false.

- type: shell
- stdin: ${fetch.response}

```shell command
case '${describe_images}' in
  *[Ff]alse*) echo '[]' ;;
  *) grep 'Image [0-9]' | grep -o 'https://[^)]*' | \
     jq -Rs 'split("\n") | map(select(. != ""))' ;;
esac
```

### analyze

Analyze each image with vision AI to extract content. Uses Gemini's
vision capabilities for cost-effective batch processing.

- type: llm
- model: gemini-3-flash-preview
- images: ${item}

```yaml batch
items: ${extract-images.stdout}
parallel: true
max_concurrent: 40
error_handling: continue
```

````markdown prompt
Extract the information from this image. No analysis or summary - just the content.

- Diagram/flowchart: mermaid code only (```mermaid block)
- Chart/graph: data values and labels
- Screenshot: visible text and UI elements
- Decorative: say 'decorative'

Be direct. No commentary.
````

### format-analyses

Format image analyses as numbered markdown sections for appending to the article.

- type: shell
- stdin: ${analyze.results}

```shell command
jq -r 'to_entries | map("### Image " + (.key + 1 | tostring) + "\n" + .value.response + "\n") | join("\n")'
```

### save-article

Save the article markdown to disk at the computed filename.

- type: write-file
- file_path: ${compute-filename.stdout}
- content: ${fetch.response}

### append-analyses

Append image analysis sections to the saved article file.

- type: shell
- stdin: ${format-analyses.stdout}

```shell command
echo '' >> '${compute-filename.stdout}' && \
echo '---' >> '${compute-filename.stdout}' && \
echo '' >> '${compute-filename.stdout}' && \
echo '## Image Details' >> '${compute-filename.stdout}' && \
echo '' >> '${compute-filename.stdout}' && \
cat >> '${compute-filename.stdout}' && \
echo '${compute-filename.stdout}'
```

## Outputs

### file_path

Path to the saved markdown file with article content and image analyses.

- source: ${compute-filename.stdout}
`````

---

## Ruled Out Alternatives

Don't re-explore these. Each was considered and rejected with reasoning:

- **Python DSL format**: pflow is fundamentally declarative. Python-in-Python for code nodes is absurd.
- **Hybrid approach**: Python authoring with IR storage. Unnecessary complexity.
- **JSON as input format**: No users, no backwards compatibility. One format is simpler.
- **Round-trip conversion**: One-way (markdown to dict) is sufficient.
- **Multi-file workflows**: Future work.
- **Cross-node type checking**: `.pyi` stubs and mypy — speculative, not MVP.
- **YAML frontmatter for authoring**: Creates three syntax zones. Section headings provide the same structure with pure markdown. (Frontmatter IS used for system metadata in saved workflows — agents never write it.)
- **Bare YAML params (no `-` prefix)**: No visual distinction from prose. `- ` gives bullet rendering.
- **`- ` as custom parser (not YAML)**: Prevents nesting. Agents will try YAML nesting and it should work.
- **Different syntax for inputs vs outputs vs nodes**: Inconsistency. Complex outputs need code blocks → need headings → same pattern for everything.
- **Batch items as sub-headings (`####`)**: Pushes to 4-5 heading levels. YAML code blocks handle batch config better.
- **`yaml` as code block tag**: Doesn't name a parameter. All tags must name the param they map to.

---

## Design Context

This section captures the tacit knowledge from the format design sessions — useful for understanding WHY decisions were made, not just WHAT was decided.

### User's mental model

The user's most important reframe: **"If the .md document was JUST documentation, how would you expect it to look?"** This single question shaped the entire format. Every time we got lost in parser mechanics or config-file thinking, coming back to "what would a documentation author write?" gave the answer.

Key phrases in their own words:
- **"Documentation IS code"** — the workflow file IS the documentation
- **"LLMs are the users"** — LLMs generate what they've been trained on. Optimizing for LLMs = optimizing for natural documentation
- **"Faster horse problem"** — people won't know they want markdown until they see it
- **"JSON was HELL for AI agents"** — the escaping, the single-line prompts

Their decision-making style: doesn't accept "good enough." Pushes back until the design feels right. Examples of catching premature convergence:
- When frontmatter was proposed for inputs → "I'm not sure if name and inputs/outputs should be in frontmatter"
- When YAML code blocks were proposed for inputs → "does the prose usually come before or after the - list?"
- When `string = ""` syntax was proposed → "is that natural syntax for you?"
- When settling seemed imminent → "let's take a step back and think about this clearly... this is fundamental"

Their priorities (in order):
1. **Consistency** — one pattern for everything beats multiple optimal-for-each-case patterns
2. **Naturalness** — it should look like documentation LLMs have seen billions of times
3. **LLM generation quality** — minimize errors when generating workflows
4. **Self-documenting** — the format forces good documentation by default
5. **Elegance** — they have taste and care about the design feeling "right"

### Key design principles

**"Documentation as documentation"**: The format should look exactly like natural markdown documentation — heading hierarchy, bullet lists, code blocks. Nothing novel. The less an LLM has to "learn," the fewer errors it makes.

**Content types need appropriate highlighting**: Shell commands need bash highlighting. Python needs Python highlighting. Prompts need readable text. YAML config needs YAML highlighting. Putting everything in one format gives wrong highlighting to most content.

**Data flows top-to-bottom**: Inputs at the top (define before use), nodes in execution order (each can reference above), outputs at the bottom (reference everything above). Mirrors both execution and how LLMs build context when reading.

**Consistency over brevity**: Simple inputs could be one-line list items. Simple outputs could be list items. But then complex outputs need headings. Having two visual weights for the same concept creates inconsistency. One pattern everywhere, even if slightly verbose for simple cases.

### Pivotal design moments

1. **Complex outputs forced the universal pattern.** We had different syntax for inputs (YAML blocks), nodes (headings), and outputs (list items). Then outputs with multi-line source templates needed code blocks → needed headings → followed the same pattern as nodes → why not make inputs the same? This single realization unified the entire format.

2. **YAML `#` comments were a happy accident.** We decided to parse `- ` lines as YAML (not simple line splitting) because agents would try nesting. The bonus: `- model: gpt-4  # chosen for accuracy` works for free. Two documentation mechanisms (inline comments AND prose paragraphs).

3. **Saved workflow frontmatter is NOT authoring frontmatter.** Frontmatter is for SYSTEM METADATA on saved workflows, added programmatically. Agents never write it. Two completely different use cases that happen to use the same syntax.

4. **The `- ` prefix solves parsing ambiguity.** Without it (`type: http` as bare text), you can't distinguish params from prose. With `- type: http`, every param is visually and syntactically distinct. This is why bare YAML was rejected — not because of indentation concerns, but because of prose/param ambiguity.

### Lessons learned

1. **Don't propose YAML frontmatter first.** Start with "what would natural documentation look like?" and let structure emerge.
2. **The consistency insight is the most important one.** Every "special syntax for X" idea created problems when X needed to do something Y could do.
3. **Test against real workflows early.** We didn't until late. Doing it earlier would have revealed the complex-output insight sooner.
4. **The user thinks in terms of what LLMs should generate.** Not parser convenience. Optimizing for parser simplicity at the cost of naturalness got pushed back.

---

## References

### Must-read before implementation
- `src/pflow/core/ir_schema.py` — IR schema definition (this is what the parser produces)
- `src/pflow/cli/main.py:162-193` — `_try_load_workflow_from_file()` (primary CLI integration point)
- `src/pflow/runtime/compiler.py:155-160` — `_parse_ir_input()` (dict/string handling)
- `src/pflow/runtime/compiler.py:1058-1075` — template validation call site (where unknown param warning hooks in)
- `src/pflow/runtime/template_validator.py:931-936` — where registry interface metadata is loaded
- `src/pflow/registry/metadata_extractor.py` — how interface metadata is extracted from node docstrings

### Starting context (only if you need background on WHY decisions were made)
- `.taskmaster/tasks/task_107/starting-context/braindump-implementation-context.md`
- `.taskmaster/tasks/task_107/starting-context/braindump-comprehensive-format-exploration.md`

### Architecture
- `architecture/architecture.md` — overall pflow architecture
- `src/pflow/pocketflow/__init__.py` — the underlying framework (~200 lines)
- `architecture/reference/enhanced-interface-format.md` — node interface documentation format

### Example workflows to convert as test cases
- `examples/real-workflows/generate-changelog/workflow.json` — complex (15 nodes, batch, multiple outputs)
- `examples/real-workflows/webpage-to-markdown/workflow.json` — medium complexity (already converted above)
