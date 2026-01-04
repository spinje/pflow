# Task 107: Implement Markdown Workflow Format

## Description

A new workflow authoring format using markdown that compiles to the existing IR. Optimizes for LLM authoring with literate programming, lintable code blocks, and significant token efficiency gains. The format treats LLMs as the primary authors while accidentally being highly readable by humans.

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
- Can't lint
- Can't test
- Errors only at runtime
- Even LLMs struggle to read/modify

**Documentation is separate:**
- `workflow.json` + `README.md` = two files that drift apart
- No way to explain WHY a node exists

**Token inefficiency:**
- Escaped newlines (`\n`), quotes everywhere
- ~20-40% more tokens than necessary

## Solution

Markdown format with:

**YAML frontmatter** for structured metadata:
```yaml
---
name: generate-changelog
inputs:
  since_tag: { type: string, default: "" }
outputs:
  version: ${compute.stdout}
edges: [get-tag, analyze, refine, format]
---
```

**`## heading`** for node IDs with inline parameters:
```markdown
## analyze
type: llm
model: gpt-4
```

**Language-tagged code blocks** for content:
- ` ```prompt ` — LLM prompts (just text, no escaping)
- ` ```shell ` — Shell commands (lintable with shellcheck)
- ` ```python ` — Python code (lintable with ruff/mypy)
- ` ```batch ` — Batch configuration (YAML)
- ` ```stdin ` — Stdin object (YAML)

**Prose documentation inline:**
```markdown
## fetch
type: http
url: https://r.jina.ai/${target_url}

Uses [Jina Reader](https://r.jina.ai) for conversion. We chose Jina over
Trafilatura because it handles SPAs and paywalled content better.
```

## Design Decisions

**Markdown → IR, not → JSON:**
- Compile directly to internal representation
- JSON becomes an optional export, not the source format
- Like TypeScript → JavaScript

**LLMs are the users:**
- Humans rarely edit workflows directly
- When they do, it's tweaking prompts — which is just editing text
- "Novel format" concern is irrelevant if users never see it

**Python over jq (requires Task 104):**
- Most shell nodes exist for jq data transforms
- Python is readable, lintable, testable, familiar
- jq is powerful but cryptic

**Edges explicit in frontmatter:**
- Could infer from template references
- Explicit is clearer — frontmatter is the "wiring diagram"

**Literate workflows:**
- Documentation IS the workflow file
- Renders beautifully on GitHub
- Self-documenting by default

**Documentation flexibility (replaces `purpose` field):**
- JSON's `purpose` field: one line, no formatting, terse
- Markdown: free-form prose anywhere in the file
- Can explain WHY, not just WHAT
- Can include links, examples, blockquotes, lists
- Documentation can be:
  - Inline with each node (right after the heading)
  - At the end of the file (like a README appendix)
  - Mixed (brief inline, detailed at end)
- The format accommodates minimal or extensive documentation

**Labeled blocks for complex params:**
- Simple params inline: `type: llm`, `model: gpt-4`
- Complex configs in blocks: ` ```batch `, ` ```stdin `

## Dependencies

- **Task 104: Python Script Node** — Enables lintable data transformations, replaces most jq usage
- **Task 49: PyPI Release** — Complete v0.6.0 first, this is v0.7.0+

## Implementation Notes

### Parser approach

1. Use existing markdown library (mistune or markdown-it-py)
2. Extract YAML frontmatter (between `---` markers)
3. Split by `## ` headings to identify nodes
4. For each node:
   - Parse inline `key: value` lines as parameters
   - Extract code blocks by language tag
   - Collect prose as documentation (optional field in IR?)
5. Compile to existing IR structure

### Code block mapping

| Block type | Maps to |
|------------|---------|
| ` ```prompt ` | `params.prompt` |
| ` ```shell ` | `params.command` |
| ` ```python ` | `params.code` (Task 104) |
| ` ```batch ` | `batch` config |
| ` ```stdin ` | `params.stdin` |
| ` ```images ` | `params.images` |

### Error messages

Since markdown always parses successfully, all errors are semantic:
- "Node 'foo' missing required field 'type'" with line number
- "Unknown template reference '${bar.stdout}'" with line number
- "Edge references unknown node 'baz'"

### Linting integration

Code blocks can be extracted and linted:
```bash
# Shell blocks
shellcheck <(extract-blocks shell workflow.md)

# Python blocks
ruff check <(extract-blocks python workflow.md)
```

Existing tools work because we use standard language tags.

### Example: webpage-to-markdown workflow

See conversation for full example. Key insight: the workflow becomes self-documenting with inline prose explaining design decisions, tradeoffs, and usage.

## Verification

**Parser correctness:**
- Extracts frontmatter (inputs, outputs, edges)
- Identifies nodes by heading
- Parses inline parameters
- Extracts code blocks with correct types
- Handles edge cases (prompts containing markdown)

**Execution equivalence:**
- Convert existing JSON workflows to markdown
- Both produce identical execution results

**Linting works:**
- shellcheck catches errors in ` ```shell ` blocks
- ruff/mypy catch errors in ` ```python ` blocks
- Line numbers map back to markdown source

**Token efficiency:**
- Measure token count for same workflow in JSON vs markdown
- Expect 20-40% reduction

**LLM authoring:**
- Have Claude/GPT generate workflows in markdown format
- Compare error rate and quality vs JSON generation

## Open Questions

1. **Documentation field in IR?** — Should prose be preserved in IR or discarded after parsing?
2. **Multiple code blocks?** — What if a node has two ` ```shell ` blocks?
3. **Nested markdown in prompts?** — How to handle prompts that contain code block examples?
4. **File extension?** — `.md`, `.pflow.md`, `.pflow`?

## References

- Conversation explored JSON vs YAML vs XML vs Markdown tradeoffs
- `examples/real-workflows/generate-changelog/` — Complex workflow that motivated this
- `examples/real-workflows/webpage-to-markdown/` — Simpler workflow shown in markdown format
