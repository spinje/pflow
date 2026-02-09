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

This is the Mintlify documentation for pflow. Users don't use pflow directly — their AI agents do. Users install pflow, configure it, and then their agent handles the rest: discovering nodes, building workflows, running them.

These docs serve two purposes:

1. **Setup and configuration** — Quickstart, integrations, settings, MCP server management. Things the user actually needs to do themselves.
2. **Understanding what your agent builds** — Node reference, CLI reference, "How it works" pages. Users open a `.pflow.md` file their agent created and want to understand what a code node or shell node does. They're reading their agent's work, not learning to write workflows themselves.

This distinction matters for how you write each type of page. Setup pages are procedural — do this, then this. Reference pages explain what things do and how they work, so users can read and understand the workflows their agent creates.

**Important**: AI agents get their own instructions via `pflow instructions` command or MCP resources, not these docs.

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

**Before writing anything, answer: will the user directly touch this?** The answer changes everything about what you write and how you write it.

| User's relationship | Examples | How to write it |
|---------------------|----------|-----------------|
| **User does this themselves** | Install, API keys, MCP config, settings | Procedural. Steps, commands, what success looks like. |
| **User reads what their agent built** | Node reference, template syntax, workflow format | Explanatory. What it does, how it behaves, why it's designed that way. |
| **User might do this directly** | Running saved workflows, CLI commands | Both. Explain what it does, then show how to use it. |

Most of the reference docs fall in the second category. The user isn't learning to write code nodes — their agent does that. They're opening a `.pflow.md` file and wanting to understand what they're looking at. Write for that reader.

| Include | Exclude |
|---------|---------|
| What nodes do and how they behave | Planner internals |
| CLI commands and configuration | IR schema details |
| How data flows between nodes | Template resolution algorithm |
| Debugging and troubleshooting | Contributor guides |

**For implementation details**: Link to `architecture/` docs in pflow repo if not present in `how-it-works/`, don't duplicate.

**For technical deep-dives**: Use the "How it works" tab. Reference and Guides stay focused on what things do and when you'd use them. Save detailed explanations of internals, design decisions, and "why it works this way" for the "How it works" section.

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

### Voice

Write like a developer explaining what they built to another developer — at a whiteboard, not a podium. Include the reasoning, not just the conclusion. The docs should feel like they come from the same person who wrote the README — just in reference format instead of narrative.

**The goal:** Someone reads the page and thinks "okay, I get what this does." Not "wow, impressive marketing."

**The register:** Second-person, direct, technical. Confident because you've tested it, not because you're performing confidence. When you state a rule, explain why it exists — a rule with reasoning sticks, a rule without reasoning gets ignored.

- "Use `object` when you don't know the type — it skips validation entirely" — not "You could consider using `object` if the type is uncertain"
- "Templates go in `inputs`, never in the code block — because the code block is literal Python, and `${var}` isn't valid Python syntax" — not "It is important to note that template variables should be placed in the inputs parameter"
- "Upstream JSON is auto-parsed before your code runs" — not "The system automatically handles JSON deserialization of upstream data"

**What to avoid:**
- Evaluation without mechanism ("this is important", "this is crucial") — explain how it works or when it fails instead
- Corporate passive voice ("type error detection is performed") — say who does what ("pflow catches type errors")
- Synonym loops — saying the same thing in different words across consecutive sentences
- Hedging when you should recommend ("you might want to consider" when you mean "use this")

**Banned words and phrases** — never use these:
- powerful, seamless, magic, revolutionary, game-changer, transformative, unlock, empower
- it's worth noting, interestingly, as you may know, let's dive in, at the end of the day, in conclusion
- delve, harness, leverage, utilize, illuminate, facilitate, bolster, streamline, navigate
- workflow orchestration, cognitive automation, composable (as marketing jargon)
- crucial, vital, essential (as standalone evaluations — fine if followed by mechanism)

### Substance

**Mechanism over evaluation.** Don't say something is "important" or "primary." Explain how it works, when it fails, or why it's designed that way. Evaluation tells readers what to feel. Mechanism helps them understand.

- Evaluates: "Type annotations are an important feature of the code node"
- Explains: "Type annotations let pflow catch wrong input types before your code runs — you see the error immediately, not after a 60-second workflow"

**Specificity over plausibility.** Include real error messages, real numbers, concrete examples. Generic details sound plausible. Specific details sound like someone actually used the tool.

- Vague: "You'll see an error if the type is wrong"
- Specific: "You'll see: `Input 'data' expects list but received dict`"

**Take positions.** Recommend, don't present menus. If there's a best practice, say it. Readers want guidance. Save the options for when there genuinely isn't a clear winner.

**Technical audience rules.** These docs are for developers. Jargon is fine if they know it — don't define "JSON", "API", or "stdin." Move faster. Show code. Higher density per paragraph. Skip analogies and hand-holding.

### Quality tests

Before any sentence, run these:

1. **Tired engineer test:** Would a tired engineer roll their eyes? Delete it.
2. **7am test:** Could someone half-asleep understand this? If not, rewrite it.
3. **Mechanism test:** Does this explain how something works, or just evaluate it as "important"? If the latter, add the mechanism or cut the evaluation.
4. **Only-about-pflow test:** Could this sentence appear on any product's docs? Too generic. Make it specific to pflow.

### Sentence rhythm

Let sentences be the length they need to be. Don't write short punchy fragments for drama (that's its own cliche). Don't write corporate-long compound sentences either. Words like "because", "but", and "so" are fine — they're how people actually explain things.

Reference sections (parameter tables, output tables) stay clean and scannable. Intro paragraphs, tips, and section transitions are where the voice lives.

### Formatting
- Sentence case for all headings ("Getting started" not "Getting Started")
- No emoji or decorative elements
- Language tags on all code blocks (`bash`, `json`, etc.)
- Relative paths for internal links

### Structure
- Lead with what something does and when you'd use it — not a formal definition
- Put most commonly needed information first
- Break complex instructions into numbered steps
- Prerequisites at start of procedural content

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

### Node reference pages

Every node page follows this skeleton. The middle section varies — that's where each node's unique concepts live.

```markdown
---
title: "Node name"
description: "What it does in one line"
icon: "icon-name"
---

<Note>
  **Agent commands.** Your AI agent uses this node in workflows.
  You don't configure it directly.
</Note>

Intro paragraph — what this node does, when you'd reach for it
instead of alternatives. Mechanism, not evaluation.

## Parameters

| Parameter | Type | Required | Default | Description |

## Output

| Key | Type | Description |

## [Key concepts — 1-3 sections specific to this node]

What makes THIS node different. For shell: stdin handling,
security. For code: type annotations, template placement.
For LLM: model support, plugins.

Explain how things work, not just rules. Show correct patterns
with code examples.

## Examples

Real .pflow.md workflow snippets. Start simple, build up.
Each example should demonstrate a distinct pattern.

## Security (if the node runs user code or has system access)

## Error handling

Common errors with causes and what the user actually sees.
Include real error messages when possible.
```

**Reference examples:** `code.mdx` (standard node), `shell.mdx` (node with security and validation details)

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
    uv tool install pflow-cli
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
  uv tool install pflow-cli
  ```
  ```bash pipx
  pipx install pflow-cli
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
