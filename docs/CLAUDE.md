# pflow Documentation Guidelines

This file provides guidance to AI agents when working on user-facing documentation in this folder.

## Critical: Verify Before Writing

**NEVER write documentation based on assumptions.** Before documenting any CLI command, flag, or behavior:

1. **Verify the command exists** - Run `pflow --help` or check `src/pflow/cli/` or `src/pflow/mcp_server/tools/`
2. **Verify flags exist** - Check the actual Click decorators in the code
3. **Test examples** - Every command you document must be runnable
4. **Check current usage patterns** - Run `pflow instructions usage` to see what we tell agents.

If you cannot verify something, ask the user or mark it as "needs verification" - do not guess.

---

## Overview

This is the Mintlify documentation for pflow. These docs are for **humans** who:
1. Set up pflow for their AI tools (Claude Code, Cursor, etc.)
2. Configure and manage pflow (MCP servers, settings, workflows)

**Primary use case**: Users install pflow so their AI agents can use it. The agent runs pflow commands or uses pflow's MCP server. Users rarely run pflow directly for tasks - their agents do.

**Important**: AI agents get instructions via `pflow instructions` command or MCP resources, not these docs.

---

## Documentation Structure

```
docs/
├── docs.json                    # Mintlify configuration
├── index.mdx                    # Homepage ("Welcome to pflow")
├── quickstart.mdx               # Installation and setup
├── changelog.mdx                # Product updates (uses <Update> components)
├── roadmap.mdx                  # Direction and priorities
├── guides/                      # How-to guides
├── integrations/                # AI tool setup
├── how-it-works/                # Technical deep-dives for curious users
└── reference/                   # CLI, nodes, config
```

### Navigation tabs

The docs have four main tabs:
- **Documentation** - Getting started, guides, integrations
- **Reference** - CLI commands, nodes, configuration
- **How it works** - Technical deep-dives for curious users who want to understand internals
- **Changelog & Roadmap** - Product updates and future plans

### External links

| Location | Links |
|----------|-------|
| Sidebar anchors | Website (pflow.run), Blog |
| Navbar (top right) | Blog, GitHub |
| Footer | GitHub |

See `.taskmaster/tasks/task_93/starting-context/mintlify-docs-spec.md` for complete specification.

---

## Content Philosophy

**Document what users need to USE pflow effectively.**

> **Critical perspective**: Just because you have implementation details in your context doesn't mean they're relevant to pflow users. Put yourself in their shoes before writing - most users just want their AI agent to accomplish tasks, not understand how pflow works internally.

| Include | Exclude |
|---------|---------|
| CLI commands and options | Planner internals |
| Core node interfaces | IR schema details |
| Configuration and env vars | Template resolution algorithm |
| Debugging and troubleshooting | Contributor guides |

**For implementation details**: Link to `architecture/` docs in pflow repo if not present in `how-it-works/`, don't duplicate.

**For technical deep-dives**: Use the "How it works" tab. Keep Reference and Guides focused on practical usage - save detailed explanations of internals, design decisions, and "why it works this way" for the "How it works" section. Use accordions in Reference/Guides only for truly helpful context, not to dump technical details.

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
icon: "icon-name"  # Optional - shows in sidebar
---
```

For changelog pages, also add `rss: true` to enable RSS feed generation.

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
pflow my-saved-workflow --input "some text"

# Bad - placeholder that won't work
pflow your-workflow --input "your text here"
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

### Setting expectations

Use Info or Note callouts to clarify who does what (pattern from CLI reference):

```mdx
<Info>
  **Your agent handles this.** [Brief explanation of what users see/experience]
</Info>
```

This helps users understand they don't need to memorize technical details - their agent does the work.

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
    uv tool install git+https://github.com/spinje/pflow.git
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
  ```bash uv (recommended)
  uv tool install git+https://github.com/spinje/pflow.git
  ```
  ```bash pipx
  pipx install git+https://github.com/spinje/pflow.git
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
| Changelog | `clock` |
| Roadmap | `map` |
| History | `history` |
| GitHub | `github` |
| Website | `app-window` |
| Blog/News | `newspaper` |
| Documentation | `book-open` |

### Other

| Component | When to use |
|-----------|-------------|
| `<Tooltip>` | Term definitions on hover |

### Changelog components

Use `<Update>` for changelog entries. This creates the timeline layout automatically.

```mdx
<Update label="December 2024" description="v0.1.0" tags={["New releases"]}>
  ## Feature name

  Description of the feature.
</Update>
```

| Property | Purpose |
|----------|---------|
| `label` | Date shown in left timeline (e.g., "December 2024") |
| `description` | Version or subtitle (e.g., "v0.1.0") |
| `tags` | Filter tags shown in right sidebar |

### Components NOT needed for pflow

- `<ParamField>`, `<ResponseField>` - API playground (we're CLI-focused)
- `<RequestExample>`, `<ResponseExample>` - API examples
- `<Color>`, `<LaTeX>` - specialized use cases
- `<Badge>`, `<Banner>` - not needed

---

## Node Documentation Scope

**Document these (core capabilities):**
- `file` - read/write/copy/move/delete
- `llm` - general LLM node
- `http` - HTTP requests
- `shell` - shell commands
- `code` - Python data transformation
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

## Updating the Changelog

The changelog (`changelog.mdx`) uses Mintlify's `<Update>` component for a timeline layout.

### Adding a new entry

Add a new `<Update>` block at the **top** of the file (newest first):

```mdx
<Update label="January 2025" description="v0.7.0" tags={["New releases", "Improvements"]}>
  ## Release title

  Brief intro line.

  **Category 1**
  - Feature one
  - Feature two

  **Category 2**
  - Feature three

  <Accordion title="Quick start">
    Installation or getting started info.
  </Accordion>

  <Accordion title="Limitations">
    Any caveats users should know.
  </Accordion>
</Update>
```

**Structure guidelines:**
- Show main features directly (not in accordions)
- Use accordions for supplementary info (quick start, limitations, what's next)
- Keep feature lists scannable with bullet points

**Tone guidelines:**
- Keep it factual — changelogs announce what changed, not sell the product
- No taglines or marketing copy (e.g., "Plan once, run forever" belongs on the website, not here)
- Describe features by what they do, not why they're great

### Tag conventions

Use consistent tags across entries:

| Tag | When to use |
|-----|-------------|
| `New releases` | Major version releases, new features |
| `Improvements` | Enhancements, performance, UX |
| `Bug fixes` | Bug fixes |
| `Breaking changes` | Changes that require user action |

### Features you get automatically

- **Timeline navigation**: Left sidebar shows dates from `label` props
- **Tag filters**: Right sidebar filters by tags
- **RSS feed**: Auto-generated at `/changelog/rss.xml` (requires `rss: true` in frontmatter)
- **"Last updated" hover**: May show on sidebar when deployed (uses Git history)

---

## Updating the Roadmap

The roadmap (`roadmap.mdx`) documents pflow's direction and priorities.

### Structure

The roadmap uses these sections:
- **Current status** - What's working today
- **Now** - Current focus
- **Next** - Coming soon
- **Later** - Future plans
- **Vision** - Long-term exploratory ideas

### Guidelines

- Keep sections concise - bullet points, not paragraphs
- Update "Current status" when major features ship
- Move items between sections as priorities change
- Don't add time estimates - just relative priority
- Link to GitHub Discussions/Issues for community involvement

The docs roadmap (`docs/roadmap.mdx`) is the single source of truth. The README links to it.

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
- Use absolute URLs for internal links (use relative paths like `/quickstart`)
- Include untested code examples
- Document planner internals or IR schema
- Write for AI agents (they use `pflow instructions`)
- Use emoji or decorative formatting
- Use title case in headings

---

## Important URLs

| Purpose | URL |
|---------|-----|
| Docs (production) | `https://docs.pflow.run` |
| Website | `https://pflow.run` |
| Blog | `https://pflow.run/blog` |
| GitHub | `https://github.com/spinje/pflow` |

**Note**: Sidebar anchors and navbar links require full URLs (not relative paths). Internal page links within docs use relative paths.
