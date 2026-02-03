# Task 107: Markdown Workflow Format — Complete Specification

> Single source of truth for the markdown workflow format design. Contains all 27 design decisions, verified codebase facts, parsing rules, implementation guidance, and design context.
>
> **The format is settled.** Don't redesign it. If you find an edge case, add a parsing rule — don't change the format.
>
> **Deep implementation verification completed.** All ambiguities resolved. Edge generation, save pipeline, MCP integration, planner/repair gating, and all integration points have been verified against the codebase. This document reflects final decisions ready for implementation planning.

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
- `.pflow.md` gives GitHub rendering, IDE markdown support, and is distinguishable from regular markdown via `*.pflow.md` glob

**What this does NOT change**: The in-memory dict (IR) that validation, compilation, and execution operate on stays the same. Markdown is just a different way to produce that dict.

**MCP tools**: MCP tools that accept workflows (`workflow_execute`, `workflow_validate`, `workflow_save`) accept raw `.pflow.md` content strings or file paths — not IR dicts. Agents write markdown, same format everywhere. See Decision 27.

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

**Compiler stays format-agnostic**: `compile_ir_to_flow()` accepts `dict` — no production code passes strings. All file-loading happens at integration points (CLI, MCP, WorkflowManager) before the compiler sees it. The `_parse_ir_input()` string path exists but is unused in production.

### 3. All existing validation reused unchanged

**Decision**: The markdown parser produces the dict. All 6 existing validation layers run on that dict without modification.

**Verified**: Validation operates on the dict structure (node types, edges, templates, outputs). It does not reference JSON syntax in its core logic. ~10-12 error messages mention "JSON" explicitly (see Architecture Findings).

### 4. Edges from document order

**Decision**: No explicit edge declarations. Execution order is determined by the order of `###` headings in the `## Steps` section. Top to bottom.

**Reasoning**: pflow is currently linear-only (Tasks 38 and 39 are future work). Document order is the natural way to express sequence in a markdown document. When conditionals/parallel are implemented, explicit edge syntax can be added.

**Example**: If nodes appear as `### fetch`, `### analyze`, `### format`, the parser generates edges: fetch → analyze → format.

**Verified — all existing workflows are linear chains**: The generate-changelog workflow (17 nodes, 16 edges) was traced edge-by-edge and confirmed to be a single sequential chain with no branches or merges. The edges are listed in non-sequential order in the JSON file, which can create an illusion of a DAG — but it is purely linear. Document order produces identical execution.

**Edge generation is mandatory**: The parser MUST generate edges. An empty edges array causes `build_execution_order()` to assign all nodes `in_degree=0`, producing non-deterministic ordering that breaks data flow validation. Implementation:

```python
edges = [{"from": nodes[i]["id"], "to": nodes[i+1]["id"]} for i in range(len(nodes) - 1)]
```

**How execution actually works**: `_wire_nodes()` at `compiler.py:792` iterates edges and calls `source >> target` (PocketFlow's `next()` operator), setting `source.successors["default"] = target`. `Flow._orch()` follows the successor chain: run node → look up `successors["default"]` → next node → repeat until None. `build_execution_order()` is used only for validation (data flow checks), not for execution. Start node = first in the nodes array (from `_get_start_node()`).

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

**Note on workflow `description`**: This field lives OUTSIDE the IR dict — it's in the WorkflowManager metadata (frontmatter in saved files). In the markdown format, it comes from the H1 prose (between `#` title and first `##`). The `--description` flag is removed from both CLI `workflow save` and MCP `workflow_save` — description is always extracted from the markdown content. If no H1 prose exists, description defaults to empty string.

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

**Note on current IR param names**: The IR currently uses `command` for shell nodes and `code` for code nodes. The code block tags `shell command` and `python code` map to `params.command` and `params.code` respectively. If these IR fields are ever renamed to `shell` and `python`, the tags simplify to a single word. YAML config blocks will always need the two-word form since `yaml` is a language, not a param.

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
3. Agent saves: `pflow workflow save ./workflow.pflow.md --name my-workflow` → pflow adds frontmatter and stores it
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

**Save pipeline redesign**: The save operation preserves original markdown content rather than converting an IR dict back to a file format. Flow:

1. **Validate**: parse markdown → IR dict → run all validation (ensures correctness)
2. **Save**: read original markdown content → prepend YAML frontmatter → write to `~/.pflow/workflows/name.pflow.md`

This preserves the author's original formatting, comments, and prose. The parsing/validation step ensures only valid workflows are saved.

**`update_metadata()` with frontmatter**: After execution, `executor_service.py:520` calls `update_metadata()` to track execution stats. New approach: read file → split frontmatter from body → parse frontmatter with `yaml.safe_load()` → update metadata dict → serialize with `yaml.dump()` → reassemble with body → write back. The markdown body is never modified.

**`update_ir()` deprecated**: The only caller was the repair save handler, which is now gated (Decision 26). Method preserved in code but unreachable.

**WorkflowManager method changes**: All methods that hardcode `.json` extension change to `.pflow.md`:
- `save()` — receives markdown content string (not IR dict), prepends frontmatter
- `load()` — parses `.pflow.md` with frontmatter, returns metadata + IR
- `load_ir()` — parses `.pflow.md`, returns just the IR dict
- `delete()`, `exists()`, `get_path()` — use `.pflow.md` extension
- `list_all()` — scans `*.pflow.md` instead of `*.json`

**No migration needed**: Zero users, pre-release. Existing saved `.json` workflows in `~/.pflow/workflows/` become invisible after the change. This is expected behavior.

**Note**: The workflow `description` (from H1 prose) replaces the separate `description` field that was in the old JSON metadata wrapper. The `--description` CLI flag and MCP parameter are removed — description is always extracted from the markdown content. All other metadata maps 1:1 from the old JSON wrapper to frontmatter fields.

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

The parser SHOULD generate edges from document order (Decision 4), so `edges` will already be present. The parser should NOT produce `ir_version` — let `normalize_ir()` add it. Note: `ir_version` is required by the IR schema, but `normalize_ir()` is always called before `validate_ir()` in all integration paths.

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

**Param routing rules by section type** (critical implementation detail):
- **Inputs**: All `- key: value` → input dict fields directly. No `params` wrapper. Fields: `description`, `required`, `type`, `default`, `stdin` (all with `additionalProperties: False`).
- **Outputs**: All `- key: value` → output dict fields directly. No `params` wrapper. Fields: `description`, `type`, `source` (all with `additionalProperties: False`).
- **Nodes**: `type` → top-level `type`, `batch` (from yaml batch code block) → top-level `batch`, prose → `purpose`, everything else → `params` dict.

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
- ~250-350 lines of focused, testable code. Only dependency: PyYAML.

**PyYAML**: Currently in dev dependencies. Must be moved to main dependencies in `pyproject.toml` for production use. PyYAML is the correct choice: we only use `safe_load()` on small fragments, YAML type coercion matches JSON behavior (which is what we want since the IR was designed for JSON), and no need for round-trip or advanced features that heavier libraries like `ruamel.yaml` provide.

**Implementation approach**:
- State machine scanning lines: headings, code fences, `- ` params, prose
- Delegate YAML parsing to `yaml.safe_load()`
- Delegate Python syntax checking to `ast.parse()`
- Track line numbers throughout for markdown-native error messages
- Write test cases first (valid workflows, edge cases, error conditions)

**Escape hatch**: If YAML continuation tracking proves too complex, nested params can be restricted to `yaml` code blocks (e.g., `yaml headers` instead of indented `- headers:` with sub-keys).

### 26. Planner and repair systems gated, not removed

**Decision**: Both the planner and repair systems have prompts written for JSON workflow format. Rather than rewriting prompts or removing code, these are gated at the CLI level with comments explaining why. All code preserved — the decision to upgrade or remove is deferred to a future task.

**Gating approach**: Add `if` guards with clear comments at entry points. No code deleted, no refactoring. Pattern:
```python
# GATED: [System] disabled pending markdown format migration (Task 107).
# [System] prompts assume JSON workflow format. Re-enable after prompt rewrite.
```

**Planner**:
- Gate at `cli/main.py:3922` — the `_execute_with_planner()` call in `workflow_command`
- The planner is invoked automatically when natural language is passed to `pflow`. No separate `pflow plan` subcommand exists
- Keep discovery nodes working (`pflow workflow discover`, `pflow registry discover`) — they don't depend on workflow format
- Keep all planner code in `src/pflow/planning/` intact

**Repair**:
- Gate the `--auto-repair` CLI flag and repair save handlers
- Core in-memory repair logic (`repair_service.py`) preserved but unreachable from CLI
- `repair_save_handlers.py` code preserved, not called
- `WorkflowManager.update_ir()` preserved but its only caller (repair) is gated

**`--generate-metadata` on save**:
- Disabled — uses `MetadataGenerationNode` from `pflow.planning.nodes` which depends on planner prompts assuming JSON
- Flag hidden from CLI and MCP save tool
- Code preserved for re-enabling after prompt rewrite

**Context builder** (integration point #7):
- `planning/context_builder.py:255` `_try_load_workflow()` expects JSON metadata wrapper format
- Gated with same pattern — discovery workflow scanning disabled
- Only affects `pflow workflow discover` when scanning saved workflows

### 27. MCP accepts raw markdown content or file paths

**Decision**: MCP tools that accept workflows (`workflow_execute`, `workflow_validate`, `workflow_save`) accept raw `.pflow.md` content strings or file paths — not IR dicts for workflow creation. One format, one set of instructions for agents.

**`resolve_workflow()` update** (`mcp_server/utils/resolver.py:18-75`):

Resolution order:
1. **String — library name**: Check if exists in WorkflowManager → load `.pflow.md`
2. **String — file path**: Check if file exists → parse with markdown parser
3. **String — raw markdown content**: Detect by content (starts with `#` or `---`) → parse with markdown parser
4. **Dict — IR dict**: Preserved for backwards compatibility during transition, but agents should use markdown strings

This means MCP agents write `.pflow.md` content and pass it directly — same format as files. One set of instructions, one authoring format everywhere.

**MCP `workflow_save` changes**:
- `description` parameter removed (extracted from H1 prose)
- `generate_metadata` parameter disabled (Decision 26)
- Accepts raw markdown content string or file path
- Validates content, then saves with frontmatter

### Validation & linting scope

**In scope for Task 107**:
- `ast.parse()` for Python code blocks at parse time — catches syntax errors with markdown line numbers. No template variable issues (code blocks don't contain `${...}`; templates are in `inputs` param).
- `yaml.safe_load()` for YAML config blocks — already part of parsing
- Unknown param warnings — compare against registry interface metadata during compilation
- All markdown-specific validation (Decision 24)

**Out of scope**:
- Full linting (ruff, shellcheck) → Task 118
- Required param pre-validation → [Issue #76](https://github.com/spinje/pflow/issues/76). Needs `required: bool` added to interface metadata
- Type stubs / mypy → Decision 14
- Shell node refactor for variable injection → Task 118
- IR-to-markdown serialization (not needed — save preserves original content)
- Multi-file workflows
- Planner prompt rewrite for markdown format (Decision 26 — gated for now)
- Repair prompt rewrite for markdown format (Decision 26 — gated for now)
- Agent instruction rewrite (`pflow instructions create`) — needed before launch but not part of this task

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

8. **Generate edges** from document order of `###` headings in `## Steps`. Mandatory — empty edges breaks validation.

9. **Route params by section type** — Inputs/Outputs: all params go directly to entity dict. Nodes: `type` → top-level, `batch` → top-level, prose → `purpose`, everything else → `params`.

10. **Compile to IR dict** in the same shape as current JSON workflows.

11. **Run existing validation** on the dict (after `normalize_ir()` adds `ir_version`).

### Parser return type

The parser returns more than just the IR dict. Different callers need different fields:

```python
@dataclass
class MarkdownParseResult:
    ir: dict[str, Any]                    # The workflow IR dict
    title: str | None                     # H1 heading text
    description: str | None               # H1 prose (between # and first ##)
    metadata: dict[str, Any] | None       # Frontmatter (None for authored files)
    source: str                           # Original markdown content (for save operations)
```

Most callers use `.ir`. WorkflowManager uses all fields (metadata for timestamps/stats, description for display, source for save-with-frontmatter).

---

## Architecture Findings

### Verified codebase facts

**normalize_ir()** — confirmed at `ir_schema.py:559-592`. Adds `ir_version: "0.1.0"` if missing, `edges: []` if missing (and no `flow` field), renames `parameters` → `params` in nodes. Called from CLI, MCP server, and workflow save service. The markdown parser should produce a dict WITHOUT `ir_version` but WITH `edges` (from document order).

**Execution model** — PocketFlow `Flow._orch()` follows `node.successors["default"]` chain. Edges are compiled into successors by `_wire_nodes()` at `compiler.py:792-856`. For each edge: `source >> target` sets `source.successors["default"] = target`. `build_execution_order()` is used only for validation (in `validate_data_flow()`), not execution. Start node = first node in the `nodes` array (from `_get_start_node()` at `compiler.py:859-910`).

**All existing workflows are linear** — generate-changelog (17 nodes, 16 edges) verified as a pure linear chain. Edges listed in non-sequential order in JSON create an illusion of a DAG, but every node has exactly one predecessor and one successor (except start/end). Document order edge generation produces identical execution behavior.

**Top-level node fields** — confirmed at `ir_schema.py:197-212`. Only 5 fields with `additionalProperties: False`: `id`, `type`, `purpose`, `params`, `batch`. Critical: `type` goes top-level (NOT `params`), `batch` goes top-level (NOT `params`), `source` on outputs goes to output dict directly.

**Batch schema fields** — `ir_schema.py:119-179`, `additionalProperties: False`. 7 fields: `items` (required — template string or inline array), `as` (default `"item"`), `error_handling` (enum: `fail_fast`/`continue`), `parallel` (bool), `max_concurrent` (1-100, default 10), `max_retries` (1-10, default 1), `retry_wait` (number, default 0). All valid in `yaml batch` blocks.

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

**Workflow `description`** — lives OUTSIDE the IR. Top-level IR has NO `description` field (`additionalProperties: False`). It's in the WorkflowManager metadata (frontmatter in saved files). Parser extracts it from H1 prose and exposes via `MarkdownParseResult.description`.

**Unused top-level IR fields** — the full IR has 9 fields. Parser only produces `nodes`, `edges`, `inputs`, `outputs`. The rest use defaults: `ir_version` (added by normalize_ir), `start_node` (always first node), `mappings` (default `{}`), `enable_namespacing` (default `true`), `template_resolution_mode` (default `"strict"`).

**Compiler string path** — `_parse_ir_input()` at `compiler.py:144` accepts `str | dict` but NO production code passes strings. All 3 production callers (`executor_service.py:103`, `workflow_executor.py:157`, and tests) pass dicts. The string path is historical — the compiler stays format-agnostic and needs no changes for markdown.

**Save pipeline** — All current save operations lose original file content immediately after parsing (only IR dict flows through). This is being changed: save from file now preserves original markdown content (see Decision 17). `WorkflowManager.save()` currently receives `(name, ir_dict, description)` — signature changes to accept markdown content string instead.

**Error system structure** — errors use a three-part structure: `UserFriendlyError` with `title`, `explanation`, `suggestions`; `ValidationError` with `message`, `path`, `suggestion`. Error paths currently use bracket notation (`nodes[0].type`). For markdown, parser-level errors should reference source: `node "### fetch" (line 15)`.

### Integration points

Every place a workflow file is loaded or saved, needing update to use the markdown parser:

| # | File | Function | What it needs from parser | Notes |
|---|------|----------|---------------------------|-------|
| 1 | `cli/main.py:172` | `_try_load_workflow_from_file()` | `.ir` + raw content for save | Primary CLI entry |
| 2 | `cli/main.py:157` | `_is_path_like()` | N/A | Add `.pflow.md` extension check |
| 3 | `core/workflow_manager.py` | `save()`, `load()`, `load_ir()`, `list_all()`, etc. | All fields | Complete rewrite for `.pflow.md` + frontmatter |
| 4 | `mcp_server/utils/resolver.py:61` | `resolve_workflow()` | `.ir` + raw content detection | Markdown content vs library name vs file path |
| 5 | `runtime/workflow_executor.py:246` | `_load_workflow_from_path()` | `.ir` | Nested workflow loading |
| 6 | `core/workflow_save_service.py:176` | `_load_from_file_path()` | `.ir` + raw content | Save preserves content |
| 7 | `planning/context_builder.py:255` | `_try_load_workflow()` | Gated (Decision 26) | Discovery scanning disabled |

**Note**: `runtime/compiler.py:157` `_parse_ir_input()` was previously listed as an integration point but no production code passes strings to it. No change needed.

**Gating points** (Decision 26):
- `cli/main.py:3922` — planner entry (`_execute_with_planner`)
- `cli/main.py` — `--auto-repair` flag
- `cli/repair_save_handlers.py` — repair file writing
- `cli/commands/workflow.py` + `mcp_server/tools/execution_tools.py` — `--generate-metadata` flag

Everything downstream of integration points operates on dicts. No changes needed to compiler, validator, or executor logic.

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
6. Validate each YAML item is a single-key dict (bare `- value` without key is an error)

**YAML continuation collection rules** (precise definition):
- A `- ` line starts a new YAML item
- Subsequent lines indented more than the `- ` are continuations of that item
- A blank line, another `- ` line, or a non-indented non-blank line terminates the current item's continuation
- Each item (the `- ` line plus its continuations) is collected as a unit
- Non-contiguous items (separated by prose) are collected independently
- All collected items are joined with `\n` and parsed as a single YAML sequence via `yaml.safe_load()`

**Example of non-contiguous collection**:
```markdown
- type: http

We use Jina Reader for better quality.

- url: https://r.jina.ai/${target_url}
```
Collected YAML: `"- type: http\n- url: https://r.jina.ai/${target_url}"` → parsed as `[{"type": "http"}, {"url": "..."}]`

**Example with indented continuation**:
```markdown
- headers:
    Authorization: Bearer ${token}
    Content-Type: application/json

Some prose about why we need auth.

- timeout: 30
```
Item 1: `"- headers:\n    Authorization: Bearer ${token}\n    Content-Type: application/json"`. Item 2: `"- timeout: 30"`. Joined and parsed correctly.

### `ast.parse()` for Python code blocks

Python code blocks don't contain `${...}` template variables (those are in the `inputs` param). So `ast.parse()` works directly on the code content with no placeholder tricks. Run at parse time and report errors with markdown line numbers.

### `_is_path_like()` check in CLI

The CLI has `_is_path_like()` at `cli/main.py:157-159` that determines if the first argument is a file path vs. a saved workflow name. It currently checks for `.json` extension and path separators. Must also check for `.pflow.md`:

```python
identifier.lower().endswith(".json") or identifier.lower().endswith(".pflow.md")
```

Without this, `workflow.pflow.md` (without `./` prefix) would be treated as a saved workflow name lookup, not a file path.

### Empty sections are valid

`## Inputs` with no `###` headings = no inputs. Same for `## Outputs`. `## Steps` with no `###` headings = error (a workflow needs at least one node).

### Parser strictness

Default should be strict with helpful error messages. Required descriptions, no bare code blocks, duplicate param errors. Ignoring unknown `##` sections (silently, with near-miss warnings) is the exception.

### Frontmatter handling for saved workflows

For `update_metadata()` (called after execution):
1. Read file content
2. Find `---` boundaries (first line must be `---`, find closing `---`)
3. Parse frontmatter YAML with `yaml.safe_load()`
4. Update metadata dict fields
5. Serialize frontmatter with `yaml.dump()`
6. Reassemble: `---\n{frontmatter}---\n\n{body}`
7. Write back atomically (temp file + `os.replace()`)

The markdown body is never modified by metadata updates.

### Edge cases

**`images` param on LLM nodes**: `- images: ${item}` is inline. But complex structures (array with metadata) could use `yaml images` code block. The pattern should work.

**Non-contiguous YAML `- ` lines**: See the precise rules above in "Parser core complexity."

**Inline batch items**: The generate-changelog `format-both` node has inline batch items — a literal array of objects in `batch.items`, not a template reference. In markdown, this is a `yaml batch` block with inline YAML array syntax. Must be tested.

**Multi-source stdin**: Nodes like `prepare-context` in generate-changelog have complex stdin objects (`{"filter": "${source1}", "commits": "${source2}"}`). In markdown, use `yaml stdin` code block. Must be tested.

**`pflow workflow describe`**: Currently reads from WorkflowManager which returns parsed IR. With markdown, `load()` parses `.pflow.md` and returns metadata + IR — `describe` should work naturally since it displays interface info (inputs/outputs) from the parsed IR. No special handling needed.

### Invalid example workflows

`examples/invalid/*.json` tests JSON-specific validation errors (bad JSON syntax, missing version). These become irrelevant with markdown. Create new markdown-specific invalid examples:
- Missing descriptions on entities
- Bare code blocks (no tag)
- Unclosed code fences
- YAML syntax errors in params
- Invalid section names (near-miss warnings)
- Duplicate params (inline + code block)
- Invalid node ID format (spaces, uppercase)
- Missing `## Steps` section
- Empty `## Steps` (no nodes)

### Test inventory

- **~15-20 test files** load workflows from `.json` files on disk (need conversion). Mostly in `tests/test_cli/`.
- **~100+ test files** construct IR dicts in code (no change needed).
- **33 example workflows** in `examples/` to convert to `.pflow.md`.
- Most file-loading tests are specifically testing CLI file loading behavior.

### For the implementing agent

**Don't read** the braindump files in `starting-context/`. They're pre-design exploration, superseded by this document.

**Start with a real workflow, not tests.** Write a complete markdown file, then parse it. The complete example below is a good starting point.

**Build line number tracking from the start.** Every element the parser extracts should carry its source line number. (A source map for IR validation is NOT needed — see above.)

**Test `batch` and `type` routing early.** Verify `yaml batch` → `node["batch"]` not `node["params"]["batch"]`, and `- type: http` → `node["type"]` not `node["params"]["type"]`.

**Test param routing per section type.** Inputs and outputs get flat dicts (no `params` wrapper). Nodes get `type`/`batch` extracted to top-level, everything else in `params`.

**The integration points table is your checklist.** Test each independently.

**Unknown param warning is in scope.** During compilation, compare params against `interface["params"]` keys. Flag unknowns with "did you mean?" suggestions.

**Parser must validate structural completeness.** Catch all issues that jsonschema would catch (missing `type`, unknown fields, etc.) with markdown line numbers. Jsonschema validation becomes a safety net that never triggers.

**Gate planner and repair early.** These are simple `if` guards with comments. Do them first so you're not fighting broken planner/repair code while integrating the parser.

---

## Complete Example

Full webpage-to-markdown workflow converted from JSON (7 nodes, batch processing, 1 output):

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
- **Multi-file workflows**: Future work.
- **Cross-node type checking**: `.pyi` stubs and mypy — speculative, not MVP.
- **YAML frontmatter for authoring**: Creates three syntax zones. Section headings provide the same structure with pure markdown. (Frontmatter IS used for system metadata in saved workflows — agents never write it.)
- **Bare YAML params (no `-` prefix)**: No visual distinction from prose. `- ` gives bullet rendering.
- **`- ` as custom parser (not YAML)**: Prevents nesting. Agents will try YAML nesting and it should work.
- **Different syntax for inputs vs outputs vs nodes**: Inconsistency. Complex outputs need code blocks → need headings → same pattern for everything.
- **Batch items as sub-headings (`####`)**: Pushes to 4-5 heading levels. YAML code blocks handle batch config better.
- **`yaml` as code block tag**: Doesn't name a parameter. All tags must name the param they map to.
- **IR-to-markdown serializer for save**: MCP/planner could have needed dict-to-markdown conversion. Rejected — MCP accepts raw markdown strings instead (same format as files), planner gated. Saves always preserve original markdown content.
- **Dual format support (JSON + markdown)**: Considered keeping JSON alongside markdown during transition. Rejected — "markdown-only" is cleaner and avoids format detection complexity. Zero users means no migration burden.
- **Repair/planner prompt rewrite**: Considered updating LLM prompts for markdown. Rejected for now — gated instead (Decision 26). Decision to upgrade or remove made in a future task.

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
- `src/pflow/cli/main.py:157-159` — `_is_path_like()` (needs `.pflow.md` extension check)
- `src/pflow/core/workflow_manager.py` — WorkflowManager (save/load/update_metadata/list_all — complete rewrite for frontmatter)
- `src/pflow/mcp_server/utils/resolver.py:18-75` — `resolve_workflow()` (MCP markdown/file/name resolution)
- `src/pflow/runtime/compiler.py:1058-1075` — template validation call site (where unknown param warning hooks in)
- `src/pflow/runtime/template_validator.py:931-936` — where registry interface metadata is loaded
- `src/pflow/registry/metadata_extractor.py` — how interface metadata is extracted from node docstrings

### Gating points (Decision 26)
- `src/pflow/cli/main.py:3922` — planner entry point (`_execute_with_planner`)
- `src/pflow/cli/main.py` — `--auto-repair` flag
- `src/pflow/cli/repair_save_handlers.py` — repair file writing
- `src/pflow/cli/commands/workflow.py:347-396` — CLI save command (`--description`, `--generate-metadata`)
- `src/pflow/mcp_server/tools/execution_tools.py:150-224` — MCP save tool
- `src/pflow/execution/executor_service.py:520` — `update_metadata()` caller (still active — uses frontmatter)

### Starting context (only if you need background on WHY decisions were made)
- `.taskmaster/tasks/task_107/starting-context/braindump-implementation-context.md`
- `.taskmaster/tasks/task_107/starting-context/braindump-comprehensive-format-exploration.md`

### Architecture
- `architecture/architecture.md` — overall pflow architecture
- `src/pflow/pocketflow/__init__.py` — the underlying framework (~200 lines)
- `architecture/reference/enhanced-interface-format.md` — node interface documentation format

### Example workflows to convert as test cases
- `examples/real-workflows/generate-changelog/workflow.json` — complex (17 nodes, 2 batch, 5 outputs)
- `examples/real-workflows/webpage-to-markdown/workflow.json` — medium complexity (already converted above)
