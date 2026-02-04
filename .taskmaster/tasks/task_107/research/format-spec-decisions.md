# Task 107: Format Specification Decisions

> This document captures all design decisions made during the format stress-testing phase. It resolves the open questions from `design-decisions.md` and establishes the complete format specification through iterative exploration against real workflows.
>
> **Read `design-decisions.md` first** for foundational decisions (markdown-only, dict compilation, validation reuse, etc.). This document builds on those.

---

## Document Structure: Three Sections, Three Heading Levels

**Decision**: The markdown workflow format uses a fixed three-level heading structure with no authoring frontmatter.

```
#     Workflow title + prose description
##    Section (Inputs, Steps, Outputs)
###   Entity (input declaration, node, output declaration)
```

**Maximum depth is `###`.** This is a hard guarantee. No `####` or deeper.

**Reasoning**: We explored many alternatives:

1. **YAML frontmatter** for inputs/outputs — rejected because it creates a different syntax zone (YAML between `---` markers) that's inconsistent with how nodes work. Three syntax zones in one file (YAML frontmatter + markdown + code blocks) is more to learn.

2. **Flat `##` headings for everything** (no sections) — rejected because the parser can't distinguish inputs from nodes from outputs without heuristics. Implicit detection by field content (`type: string` = input, `type: http` = node, `source: ...` = output) is fragile.

3. **`##` sections without `## Steps` wrapper** — considered, but the explicit sections provide clear boundaries and match natural documentation structure (Parameters → Steps → Results).

4. **Deeper nesting** (`####` for batch items, `#####` for individual items) — rejected. Complex nested data goes in YAML code blocks, not deeper headings. This keeps the heading structure simple and predictable.

**How it was arrived at**: The user asked "if the .md document was JUST documentation, how would you expect it to look?" Writing it as natural documentation produced: H1 title, sections for Inputs/Steps/Outputs, sub-headings for individual items. The format follows documentation conventions because that's what LLMs are most trained on.

---

## Edges from Document Order

**Decision**: Execution order is determined by the order of `###` node headings within `## Steps`. No explicit `edges:` declaration. "Steps" was chosen over "Workflow" (redundant), "Nodes" (too technical), and "Pipeline" (too specific) — it's the most natural documentation word.

```markdown
## Steps

### fetch        ← runs first
### analyze      ← runs second
### format       ← runs third
```

Parser generates: `fetch → analyze → format`.

**Reasoning**: pflow is currently linear-only. The document order IS the execution order. When Task 38 (conditionals) or Task 39 (parallel) are implemented, explicit edge syntax can be added. Until then, there's nothing to declare.

---

## Workflow Name

**Decision**: The workflow's programmatic name is inferred from the filename. The `# heading` is a human-readable title for documentation purposes.

- File `generate-changelog.pflow.md` → name `generate-changelog`
- `# Generate Changelog` is the display title (can have spaces, any text)
- When saved via `pflow workflow save my-name`, the save name is used

---

## Universal Entity Pattern

**Decision**: Every `###` entity (input, node, output) uses the same pattern:

```markdown
### entity-name

Required prose description.

- key: value
- key: value

Optional additional prose (design rationale, notes, etc.)

```language param_name
content
```
```

1. `###` heading = the entity's name/ID
2. Prose = description (required for all entities — see below)
3. `- key: value` lines = properties (parsed as YAML, collected from anywhere in the entity)
4. Code blocks = content mapped to specific parameters
5. Additional prose = documentation (can appear anywhere — before params, after params, between code blocks)

**Descriptions are required**: Every `###` entity must have prose description text. For inputs and outputs, this becomes the `description` field in the IR (used in help text, validation messages, `pflow workflow describe`). For nodes, all prose is saved to the `purpose` field (effectively dead code at runtime, but forces the author to articulate intent and may be useful for future display).

**Prose placement is flexible**: Prose and code blocks can be freely interleaved. The parser collects all `- ` lines as params regardless of position, extracts code blocks by fence markers, and treats everything else as prose. YAML `#` comments on param lines also work (stripped by YAML parser). For documentation bullet lists, use `*` instead of `-`.

**Param conflict rule**: A parameter specified both inline (`- key: value`) and as a code block is a validation error.

This pattern is identical for inputs, nodes, and outputs. The only difference is which properties and code blocks are valid for each type.

**Why this matters**: One mental model for everything. An LLM doesn't need to remember "inputs use YAML blocks, nodes use list items, outputs use headings." It's the same pattern everywhere.

**How it was arrived at**: We initially proposed different syntax for inputs (YAML code blocks), nodes (`- key: value`), and outputs (nested list items). Each approach worked in isolation but created inconsistencies when mixed. The user pushed for consistency, asking "shouldn't inputs follow the same syntax as nodes?" Exploring this led to the realization that the heading + params + code blocks pattern works universally. The decisive moment was when we discovered that outputs can need code blocks too (for complex source templates) — meaning outputs need headings, which means the same pattern applies everywhere.

---

## Properties Use `- key: value` (Parsed as YAML)

**Decision**: Properties under a `###` heading use markdown list syntax (`- key: value`). These are parsed as YAML (a sequence of single-key mappings) and merged into a single dict.

Simple flat properties:
```markdown
### fetch
- type: http
- url: https://api.example.com
- timeout: 30
```

Parsed as YAML: `[{"type": "http"}, {"url": "..."}, {"timeout": 30}]`
Merged to: `{"type": "http", "url": "...", "timeout": 30}`

Nested properties (when needed):
```markdown
### config-input
- type: object
- default:
    max_retries: 3
    timeout: 30
```

YAML nesting under a `- ` item works naturally. The indentation is relative to the `-`.

**Why `- ` prefix instead of bare YAML?**

We explored bare YAML (no `-` prefix) with blank-line separation from prose. Problems:
- No visual distinction from prose in editors. `type: http` and a sentence of prose look identical — no syntax highlighting, no bullets.
- The `- ` prefix renders as bullet points in markdown preview — visually distinct and scannable.

**Why not a YAML code block for properties?**

We explored putting all properties in `yaml` code blocks. Problems:
- Every node needs a code block even for `type: shell` — unnecessary ceremony.
- Shell commands, prompts, and Python code need their own language-specific code blocks for proper syntax highlighting. Putting them in YAML (with `|` block scalars) gives them wrong highlighting.

**Why parse as YAML instead of simple line splitting?**

LLMs will naturally try YAML nesting when they see `- key:` syntax (e.g., `- headers:` followed by indented sub-keys). If we use a simple splitter, nesting silently fails. Using a YAML parser means nesting works correctly when agents write it.

---

## Code Block Tag Pattern: `language param_name`

**Decision**: Code block info strings use the pattern `language param_name` where:
- **First word** = language identifier (for editor syntax highlighting)
- **Last word** = parameter name (for the parser to know where the content maps)
- If only one word, it serves as both

### Examples

| Code block | Highlights as | Maps to |
|---|---|---|
| ` ```shell command ` | bash | `params.command` |
| ` ```python code ` | Python | `params.code` |
| ` ```yaml batch ` | YAML | `batch` config |
| ` ```yaml headers ` | YAML | `params.headers` |
| ` ```yaml stdin ` | YAML | `params.stdin` |
| ` ```prompt ` | (plain text) | `params.prompt` |
| ` ```markdown prompt ` | markdown | `params.prompt` |
| ` ```source ` | (plain text) | output `source` |
| ` ```markdown source ` | markdown | output `source` |
| ` ```json source ` | JSON | output `source` |

**Key insight**: The agent chooses the language that matches their content:
- A prompt with markdown formatting → ` ```markdown prompt `
- A prompt that's plain text → ` ```prompt `
- An output template that's markdown → ` ```markdown source `
- An output template that's JSON → ` ```json source `

**Future simplification**: When `command` is renamed to `shell` and `code` is renamed to `python` in the IR, those blocks simplify to just ` ```shell ` and ` ```python ` — the tag becomes both language and param name. The `yaml *` blocks will always need the info string since `yaml` is a language, not a param name.

**How it was arrived at**: Initially we used the param name as the code block tag (` ```batch `, ` ```stdin `, ` ```headers `). This was consistent but meant no syntax highlighting for YAML-content blocks in editors. The user noted this was "a minor issue but annoying." We then adopted the CommonMark info string pattern where the first word is the language. This gives YAML highlighting for config blocks, bash highlighting for shell, Python highlighting for code, and the agent's choice for prompts and output templates.

---

## Content Types and Their Code Blocks

Different content types need different treatment:

| Content | Block type | Why |
|---|---|---|
| Shell commands | ` ```shell command ` | Bash syntax highlighting |
| Python code | ` ```python code ` | Python syntax highlighting |
| LLM prompts | ` ```prompt ` or ` ```markdown prompt ` | Clean text, no misleading highlighting |
| Output templates | ` ```source ` or ` ```markdown source ` | Template text with `${...}` refs |
| Batch config | ` ```yaml batch ` | Structured YAML data |
| Stdin objects | ` ```yaml stdin ` | Structured YAML data |
| Other complex params | ` ```yaml param_name ` | Any nested/complex param |

**Key principle**: Content should get the highlighting that matches its language. Shell code should look like shell code. Python should look like Python. Prompts are text. Config is YAML. Putting a shell command inside a YAML `|` block gives it YAML highlighting, which is wrong.

---

## Complex Outputs Need Code Blocks

**Decision**: Outputs whose `source` is a multi-line template use a `source` code block, not an inline property.

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

**Why this matters**: In JSON, a complex output template is a single escaped string: `"source": "# Release v${version}\n\n## Changelog\n${format.response}\n..."`. This is unreadable. In markdown, it's a code block with proper formatting and syntax highlighting.

**This is what forced outputs to use `###` headings** (same as nodes). If outputs need code blocks, they need their own heading sections. Which means they follow the same universal pattern as everything else.

---

## YAML Code Blocks for Complex Structured Data

**Decision**: Complex/nested structured data (batch config, stdin objects, headers, output schemas) goes in YAML code blocks tagged with the param name.

```yaml batch
items: ${extract-images.stdout}
parallel: true
max_concurrent: 40
error_handling: continue
```

```yaml stdin
config: ${fetch.result}
data: ${process.stdout}
```

**When to use inline vs code block**: Simple flat values stay as `- key: value` properties. When a value is a nested object, array of objects, or multi-line structure, it goes in a YAML code block.

**How it was arrived at**: We explored expressing nested structures through deeper headings (e.g., `####` for batch items). This works for cases where items have text content (batch items with long format_rules), but adds heading depth and complexity. The user and I agreed that YAML is the right tool for structured data — it handles nesting, arrays, and multi-line strings (`|`) naturally. Heading hierarchy is for named entities in the workflow, not for data structures.

---

## Nested Code Fences (Verified)

**Decision**: When content contains triple backticks (e.g., a prompt that shows code examples), use 4+ backticks for the outer fence.

`````markdown
````markdown prompt
Extract the information from this image.

- Diagram/flowchart: mermaid code only (```mermaid block)
- Chart/graph: data values and labels
````
`````

**Verified**: CommonMark spec supports this. Both `mistune` and `markdown-it-py` parse it correctly. The closing fence must have at least as many backticks as the opening fence.

**Risk**: An LLM that doesn't notice the content contains backticks will produce a broken document. Error messages should detect unclosed code blocks and suggest using more backticks.

---

## Complete Format Example

This is the webpage-to-markdown workflow converted from JSON to the final markdown format:

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

## Parsing Rules Summary

1. **Check for frontmatter** — if `---` markers at start of file, extract system metadata (saved workflows only). Strip before processing body.

2. **Split document by heading level:**
   - `#` = workflow title + all prose until first `##` becomes workflow `description`
   - `##` = section. Recognized names (case-insensitive): `Inputs`, `Steps`, `Outputs`. Unknown sections are silently ignored (treated as documentation). **Warning** for near-misses: `## Input`, `## Output`, `## Step` (missing 's') produce a warning — likely typos.
   - `###` = entity within a recognized section

3. **For each `###` entity:**
   - Extract code blocks (by fence markers, from anywhere in the entity)
   - Collect ALL `- ` prefixed lines from anywhere (and their indented continuations) = YAML properties
   - Parse as YAML sequence, merge into single dict
   - Remaining text = prose → `description` field for inputs/outputs, `purpose` field for nodes
   - YAML `#` comments on param lines are stripped by the YAML parser
   - For documentation bullet lists, `*` is used instead of `-`

4. **Validate descriptions:**
   - All entities (inputs, outputs, nodes) must have prose description text
   - Error message shows expected structure with concrete example

5. **Code block mapping:**
   - Info string: first word = language (ignored by parser), last word = param name
   - If one word: it's both language hint and param name
   - Content is mapped to the named parameter in the compiled dict
   - Code blocks without info string are validation errors (suggest likely tag based on node type)
   - A param defined both inline and as a code block is a validation error

6. **Edges:**
   - Generated from document order of `###` headings within `## Steps`
   - No explicit edge declarations (linear only)

7. **Name:**
   - Inferred from filename (strip extension)
   - `#` heading is documentation title, not the ID

---

## Still Open

### ~~File extension~~ → DECIDED
`.pflow.md` — gets GitHub rendering, IDE markdown support, and is distinguishable from regular markdown files via glob `*.pflow.md`.

### ~~Linting scope~~ → DECIDED
`ast.parse()` for Python code blocks at parse time. `yaml.safe_load()` for YAML config blocks (already doing this). Nothing for shell/prompt. Full linting (ruff, shellcheck, shell node refactor) is a separate future task.

### ~~Parser library~~ → DECIDED
Custom line-by-line state machine parser. No markdown library. The format is a DSL using markdown syntax — libraries optimize for rich text rendering, not structured data extraction. The hard part (`- ` line collection with YAML continuations) is custom logic regardless. Libraries risk silent failures from ambiguous markdown interpretation. ~250-350 lines, no dependencies beyond PyYAML.

### Resolved (from previous session)

- **Section name**: Decided as `## Steps`. "Steps" is the most natural documentation word (SOPs, runbooks, tutorials). "Workflow" was redundant, "Nodes" too technical, "Pipeline" too specific.
- **Saved workflow format**: Decided as markdown with YAML frontmatter for system metadata. See `design-decisions.md` Decision 17.
- **Case sensitivity**: Section names are case-insensitive. `## inputs`, `## Inputs`, `## INPUTS` all valid. Parser normalizes.
- **Unknown sections**: Silently ignored. Agents can add extra `##` sections (e.g., `## Notes`, `## Design Decisions`) as documentation. Only `Inputs`, `Steps`, `Outputs` are parsed. **Exception**: `## Input` and `## Output` (without 's') should produce a warning — these are almost certainly typos, not documentation sections.
- **Description concatenation**: All prose paragraphs within an entity are joined with `\n\n` (double newline), with leading/trailing whitespace stripped. For inputs/outputs/workflow, this becomes the `description` field. For nodes, prose is saved to the `purpose` field (not currently used by code) but is still required by the parser to force documentation.
