# Task 93: Mintlify Documentation Specification

## Overview

Set up Mintlify as the documentation platform for pflow's user-facing documentation. The docs will live in the `/docs` folder within the main repo (monorepo approach).

---

## Key Decisions

### 1. Same Repo (Monorepo) Approach

**Decision**: Keep docs in `/docs` folder within the pflow repo.

**Reasoning**:
- AI agents can update docs atomically with code changes (single PR)
- Guaranteed version sync (docs always match code version)
- Simpler setup and maintenance for solo/small team
- Mintlify fully supports monorepo with `/docs` path configuration

**Rejected alternative**: Separate repo would cause docs drift and cross-repo coordination complexity.

### 2. Documentation Philosophy

**Focus**: Document what users need to USE pflow effectively.

**Include**:
- Usage patterns and commands
- Base capabilities (core nodes)
- Configuration and environment
- Debugging and troubleshooting

**Exclude**:
- Planner internals (lives in `architecture/`)
- IR schema details (agents handle this)
- Example workflows (agents use `examples/` internally)
- Contributor guides (lives in `CLAUDE.md`, `architecture/`)

### 3. Target Audiences

| Audience | What they need |
|----------|----------------|
| **CLI user** | How to run pflow, CLI reference |
| **AI-assisted user** | How to set up Claude/Cursor with pflow |
| **Debugging** | Traces, troubleshooting steps |

**Not a target audience**: AI agents reading docs (they get instructions via `pflow instructions` or MCP resources).

### 4. Node Documentation Scope

**Document fully** (base capabilities):
- `file` - read/write/copy/move/delete (universal)
- `llm` - general LLM node (core AI capability)
- `http` - API requests (useful without MCP)
- `shell` - Unix commands (powerful)
- `claude-code` - agentic development (unique differentiator)
- `mcp` - how MCP bridge works (extensibility)

**Skip** (specialized/internal):
- `git` nodes - not everyone uses git
- `github` nodes - requires GitHub setup
- `test`, `echo` - internal development nodes

---

## Documentation Structure

```
docs/
├── docs.json                    # Mintlify configuration
├── index.mdx                    # Homepage with value prop
├── quickstart.mdx               # First workflow in 2 min
├── installation.mdx             # pip install + verify
│
├── guides/
│   ├── using-pflow.mdx         # Day-to-day CLI usage
│   ├── adding-mcp-servers.mdx  # Expand capabilities
│   ├── configuration.mdx       # API keys, settings, filtering
│   └── debugging.mdx           # Traces, troubleshooting
│
├── integrations/
│   ├── overview.mdx            # Why + options
│   ├── claude-desktop.mdx      # MCP config snippet
│   └── cursor.mdx              # MCP config snippet
│
└── reference/
    ├── cli/
    │   ├── index.mdx           # Command overview
    │   ├── workflows.mdx       # pflow [run] + pflow workflow
    │   ├── registry.mdx        # pflow registry
    │   ├── mcp.mdx             # pflow mcp
    │   └── settings.mdx        # pflow settings
    │
    ├── nodes/
    │   ├── index.mdx           # What are nodes + overview
    │   ├── file.mdx            # read/write/copy/move/delete
    │   ├── llm.mdx             # General LLM node
    │   ├── http.mdx            # HTTP requests
    │   ├── shell.mdx           # Shell commands
    │   ├── claude-code.mdx     # Agentic development
    │   └── mcp.mdx             # MCP bridge (how it works)
    │
    └── environment.mdx         # All env vars + config reference
```

**Total**: ~22 pages

---

## Navigation Structure (docs.json)

```json
{
  "tabs": [
    {
      "tab": "Documentation",
      "groups": [
        {
          "group": "Getting Started",
          "pages": ["index", "quickstart", "installation"]
        },
        {
          "group": "Guides",
          "pages": [
            "guides/using-pflow",
            "guides/adding-mcp-servers",
            "guides/configuration",
            "guides/debugging"
          ]
        },
        {
          "group": "AI Tool Integration",
          "pages": [
            "integrations/overview",
            "integrations/claude-desktop",
            "integrations/cursor"
          ]
        }
      ]
    },
    {
      "tab": "Reference",
      "groups": [
        {
          "group": "CLI Commands",
          "pages": [
            "reference/cli/index",
            "reference/cli/workflows",
            "reference/cli/registry",
            "reference/cli/mcp",
            "reference/cli/settings"
          ]
        },
        {
          "group": "Nodes",
          "pages": [
            "reference/nodes/index",
            "reference/nodes/file",
            "reference/nodes/llm",
            "reference/nodes/http",
            "reference/nodes/shell",
            "reference/nodes/claude-code",
            "reference/nodes/mcp"
          ]
        },
        {
          "group": "Configuration",
          "pages": ["reference/environment"]
        }
      ]
    }
  ]
}
```

---

## Content Sources

| Docs Page | Primary Source |
|-----------|----------------|
| `index.mdx` | README.md hero + value prop |
| `quickstart.mdx` | README.md Quick Start section |
| `installation.mdx` | New (pip install + verify) |
| `guides/using-pflow.mdx` | New (CLI patterns) |
| `guides/adding-mcp-servers.mdx` | README.md MCP sections |
| `guides/configuration.mdx` | Codebase research (settings, API keys) |
| `guides/debugging.mdx` | Codebase research (traces) |
| `integrations/*` | docs/mcp-server.md + new |
| `reference/cli/*` | Codebase research (CLI structure) |
| `reference/nodes/*` | Codebase research (node interfaces) |
| `reference/environment.mdx` | Codebase research (env vars) |

---

## Depth Guidelines

| Section | Depth Level | Content Style |
|---------|-------------|---------------|
| Getting Started | Step-by-step | Must work first time |
| Guides | Task-focused | "How do I do X?" |
| Integrations | Minimal | Copy config, done |
| CLI Reference | Complete | Full command docs |
| Node Reference | Complete (core only) | Shows base capabilities |
| Environment | Complete | All env vars listed |

---

## What NOT to Document

| Topic | Why Excluded | Where It Lives |
|-------|--------------|----------------|
| Planner architecture | Internal implementation | `architecture/features/planner.md` |
| IR schema details | Agents build workflows | `architecture/core-concepts/schemas.md` |
| Template resolution internals | Implementation detail | `architecture/reference/template-variables.md` |
| Git/GitHub nodes | Specialized, not core | Discoverable via `pflow registry list` |
| Example workflows | For agents, not humans | `examples/` folder |
| Contributor guides | For developers | `CLAUDE.md`, `architecture/` |

---

## Mintlify Setup Requirements

### Files Needed

1. **`docs/docs.json`** - Site configuration (nav, theme, branding)
2. **`docs/*.mdx`** - Documentation pages
3. **`docs/logo/`** - Light/dark logo SVGs
4. **`docs/favicon.svg`** - Site icon

### Local Development

```bash
# Install Mintlify CLI
npm i -g mint

# Preview locally
cd docs
mint dev
# Opens http://localhost:3000
```

### Deployment

1. Connect GitHub repo to Mintlify dashboard
2. Enable monorepo mode with `/docs` path
3. Auto-deploys on push to main

---

## Research Materials

Located in `.taskmaster/tasks/task_93/research/mintlify-docs/`:

- `llms-full.txt` (920 KB) - Complete Mintlify docs as AI context
- `llms.txt` (18 KB) - Structured index of Mintlify docs
- `starter-reference/` - Mintlify starter kit for inspiration

---

## Documentation Guidelines

### Inherited from Mintlify

**Content strategy**:
- Document just enough for user success - not too much, not too little
- Prioritize accuracy and usability of information
- Make content evergreen when possible
- Search for existing information before adding new content (we have README, architecture/)
- Check existing patterns for consistency

**Writing standards**:
- Second-person voice ("you can run..." not "users can run...")
- Sentence case for all headings ("Getting started" not "Getting Started")
- Prerequisites at start of procedural content
- Test all code examples before publishing
- Language tags on all code blocks (`bash`, `json`, etc.)
- Relative paths for internal links
- Use broadly applicable examples rather than company-specific cases
- Lead with context - explain what something IS before showing how to use it

**Language and tone**:
- Avoid promotional language - technical docs, not marketing
- No editorializing ("it's important to note", "in conclusion")
- Prefer active voice and direct language
- Remove unnecessary words while maintaining clarity
- Break complex instructions into clear numbered steps

**Formatting**:
- No emoji or decorative elements
- Purposeful formatting only (bold/italics when it helps understanding)
- Clean structure

**Technical accuracy**:
- Verify all links (internal and external)
- Maintain consistent terminology throughout
- All code examples must be current and accurate

**Frontmatter requirements**:
- Every `.mdx` file must have `title` and `description`
- Title: Clear, descriptive page title
- Description: Concise summary for SEO/navigation

### pflow-Specific Rules

**Focus on usage, not internals**:
- Document HOW to use pflow, not how it works internally
- Planner architecture, IR schema, template resolution → lives in `architecture/`
- Link to `architecture/` docs for implementation details

**Node documentation scope**:
- Document core nodes only: file, llm, http, shell, claude-code, mcp
- Skip specialized nodes: git, github
- Skip internal nodes: test, echo

**Audience clarity**:
- AI agents are NOT the docs audience
- AI agents get instructions via `pflow instructions` command or MCP resources
- Docs are for humans who use pflow directly or set it up for their AI tools

**Code examples**:
- Every `pflow ...` command must be runnable if copy-pasted
- Show real, working examples (not placeholders)
- Test commands before publishing

**Cross-references**:
- Link to `architecture/` for deep dives
- Don't duplicate content from README or architecture docs
- Reference existing examples in `examples/` folder when relevant

---

## Codebase Research Summary

### CLI Commands (6 groups)

| Command | Subcommands |
|---------|-------------|
| `pflow [request]` | Natural language / file / saved workflow |
| `pflow mcp` | add, list, sync, remove, tools, info, serve |
| `pflow registry` | list, describe, search, scan, discover, run |
| `pflow workflow` | list, describe, show, delete, discover, save |
| `pflow settings` | init, show, allow, deny, remove, check, reset, set-env, unset-env, list-env |
| `pflow instructions` | usage, create |

### Core Nodes (6 categories to document)

| Category | Nodes |
|----------|-------|
| File | read-file, write-file, copy-file, move-file, delete-file |
| LLM | llm |
| HTTP | http |
| Shell | shell |
| Claude | claude-code |
| MCP | mcp-{server}-{tool} (universal bridge) |

### Configuration

- Settings file: `~/.pflow/settings.json`
- Workflows: `~/.pflow/workflows/`
- Traces: `~/.pflow/debug/`
- Key env vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GITHUB_TOKEN`, `PFLOW_*`

### Debugging

- Workflow traces: `~/.pflow/debug/workflow-trace-*.json`
- Planner traces: `--trace-planner` flag
- Verbose output: `--verbose` / `-v` flag
