# pflow Documentation Guidelines

This file provides guidance to AI agents when working on user-facing documentation in this folder.

## Overview

This is the Mintlify documentation for pflow. These docs are for **humans** who use pflow directly or set it up for their AI tools.

**Important**: AI agents are NOT the audience for these docs. AI agents get instructions via `pflow instructions` command or MCP resources.

---

## Documentation Structure

```
docs/
├── docs.json                    # Mintlify configuration
├── index.mdx                    # Homepage
├── quickstart.mdx               # First workflow
├── installation.mdx             # Setup
├── guides/                      # How-to guides
├── integrations/                # AI tool setup
└── reference/                   # CLI, nodes, config
```

See `.taskmaster/tasks/task_93/starting-context/mintlify-docs-spec.md` for complete specification.

---

## Content Philosophy

**Document what users need to USE pflow effectively.**

| Include | Exclude |
|---------|---------|
| CLI commands and options | Planner internals |
| Core node interfaces | IR schema details |
| Configuration and env vars | Template resolution algorithm |
| Debugging and troubleshooting | Contributor guides |

**For implementation details**: Link to `architecture/` docs, don't duplicate.

---

## Terminology

Use consistent terms throughout all documentation.

| Term | Use | Don't use |
|------|-----|-----------|
| workflow | A saved, reusable pipeline | flow, pipeline, script |
| node | A single operation in a workflow | step, task, action |
| run (verb) | Execute a workflow | execute, invoke |
| MCP server | External tool provider | MCP tool, MCP plugin |
| shared store | Data passed between nodes | context, state, memory |
| template variable | `${variable}` syntax | placeholder, parameter |

---

## Writing Standards

### Voice and tone
- Second-person voice ("you can run..." not "users can run...")
- Active voice, direct language
- No promotional language - technical docs, not marketing
- No editorializing ("it's important to note", "in conclusion")

### Formatting
- Sentence case for all headings ("Getting started" not "Getting Started")
- No emoji or decorative elements
- Language tags on all code blocks (`bash`, `json`, etc.)
- Relative paths for internal links

### Structure
- Prerequisites at start of procedural content
- Lead with context - explain what something IS before showing usage
- Break complex instructions into numbered steps
- Put most commonly needed information first

### Frontmatter (required on every page)
```yaml
---
title: "Clear, descriptive page title"
description: "Concise summary for SEO/navigation"
---
```

---

## Page Structure Pattern

Use this pattern for reference pages (nodes, CLI commands):

```markdown
---
title: "Page title"
description: "One-line description"
---

Brief intro - what this does and when to use it.

## Basic usage

Simple example that works.

## Parameters

Table of all params with types and defaults.

## Examples

### Common use case
...

### With options
...

## Related

- Links to related nodes/guides
```

---

## Code Examples

**Every CLI example must be runnable.**

```bash
# Good - works if copy-pasted
pflow "summarize this text" < input.txt

# Bad - placeholder that won't work
pflow "your task here" < your-file.txt
```

Test all commands before publishing.

---

## Mintlify Components

### Callouts (use sparingly)

| Component | When to use | Example |
|-----------|-------------|---------|
| `<Note>` | Helpful supplementary info | "Note: This requires API key setup" |
| `<Tip>` | Best practices, pro tips | "Tip: Use `--verbose` for debugging" |
| `<Warning>` | Cautions, breaking changes | "Warning: This will overwrite files" |
| `<Info>` | Neutral context | "Info: Available since v0.1.0" |

```mdx
<Note>
  You need to set up an API key before using this feature.
</Note>
```

### Structure

| Component | When to use |
|-----------|-------------|
| `<Accordion>` | Collapsible details, troubleshooting, FAQ |
| `<Tabs>` | OS/language variants (macOS vs Linux) |
| `<Steps>` | Sequential procedures (installation) |
| `<Columns>` | Grid layouts for cards |
| `<Expandable>` | Nested property details |

```mdx
<Steps>
  <Step title="Install pflow">
    ```bash
    pip install pflow-cli
    ```
  </Step>
  <Step title="Verify installation">
    ```bash
    pflow --version
    ```
  </Step>
</Steps>
```

### Navigation

| Component | When to use |
|-----------|-------------|
| `<Card>` | Links with icons on index pages |
| `<Columns>` | Arrange cards in grid |

```mdx
<Columns cols={2}>
  <Card title="Quickstart" icon="rocket" href="/quickstart">
    Get running in 2 minutes
  </Card>
  <Card title="CLI reference" icon="terminal" href="/reference/cli">
    All commands documented
  </Card>
</Columns>
```

### Code

| Component | When to use |
|-----------|-------------|
| `<CodeGroup>` | Multiple code variants (bash vs zsh) |

```mdx
<CodeGroup>
  ```bash macOS/Linux
  pip install pflow-cli
  ```
  ```powershell Windows
  pip install pflow-cli
  ```
</CodeGroup>
```

### Media

| Component | When to use |
|-----------|-------------|
| `<Frame>` | Wrap images with captions |
| `<Mermaid>` | Flow diagrams |

### Icons

We use **Lucide** icons. All icons at https://lucide.dev/icons are available.

**Inline icon:**
```mdx
<Icon icon="terminal" size={24} />
```

**In Card:**
```mdx
<Card title="CLI reference" icon="terminal" href="/reference/cli">
  All commands documented
</Card>
```

**Common icons for pflow docs:**

| Use case | Icon name |
|----------|-----------|
| CLI/terminal | `terminal` |
| Workflows | `workflow` |
| Nodes | `box` |
| Files | `file`, `folder` |
| Settings | `settings` |
| Quick start | `rocket` |
| Installation | `download` |
| Debugging | `bug` |
| Success | `check-circle` |
| Warning | `alert-triangle` |
| Code | `code` |
| Search | `search` |
| External link | `external-link` |

### Other

| Component | When to use |
|-----------|-------------|
| `<Tooltip>` | Term definitions on hover |

### Components NOT needed for pflow

- `<ParamField>`, `<ResponseField>` - API playground (we're CLI-focused)
- `<RequestExample>`, `<ResponseExample>` - API examples
- `<Color>`, `<LaTeX>` - specialized use cases
- `<Badge>`, `<Banner>`, `<Update>` - not needed yet

---

## Node Documentation Scope

**Document these (core capabilities):**
- `file` - read/write/copy/move/delete
- `llm` - general LLM node
- `http` - HTTP requests
- `shell` - shell commands
- `claude-code` - agentic development
- `mcp` - MCP bridge

**Skip these:**
- `git`, `github` - specialized, not core
- `test`, `echo` - internal nodes

---

## Cross-References

- Link to `architecture/` for deep dives on internals
- Reference `examples/` folder for workflow patterns
- Don't duplicate README or architecture content

---

## Update Policy

When code changes affect user-facing behavior, update docs in the same PR.

- New CLI flag → update relevant CLI reference page
- New node → add to nodes reference (if core)
- Changed behavior → update affected guides
- Breaking change → add `<Warning>` callout

---

## Local Development

```bash
# Install Mintlify CLI
npm i -g mint

# Preview locally
cd docs
mint dev
# Opens http://localhost:3000

# Check for broken links
mint broken-links
```

---

## Do Not

- Skip frontmatter on any MDX file
- Use absolute URLs for internal links
- Include untested code examples
- Document planner internals or IR schema
- Write for AI agents (they use `pflow instructions`)
- Use emoji or decorative formatting
- Use title case in headings
