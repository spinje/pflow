# Task 93 Handoff Memo: Mintlify Documentation Setup

## The Single Most Important Thing

**AI agents are NOT the audience for these docs.** The user said this multiple times. AI agents get instructions via `pflow instructions` command or MCP resources. These docs are for **humans** who:
1. Use pflow directly via CLI
2. Set up pflow for their AI tools (Claude Desktop, Cursor)

If you find yourself writing content that explains how to build workflows programmatically or how the planner works internally - STOP. That's not what these docs are for.

---

## Files That Already Exist (Read These First)

1. **`docs/CLAUDE.md`** - Writing guidelines are DONE. Contains terminology, components, page structure pattern. This is your style guide.

2. **`.taskmaster/tasks/task_93/starting-context/mintlify-docs-spec.md`** - Complete structure decisions, navigation JSON, content sources. This is your blueprint.

3. **`.taskmaster/tasks/task_93/starting-context/task-93-spec.md`** - Executable spec with 30 rules and 34 test criteria. This is your validation checklist.

4. **`.taskmaster/tasks/task_93/research/mintlify-docs/`** - Contains:
   - `llms-full.txt` (920KB) - Complete Mintlify docs as AI context
   - `llms.txt` (18KB) - Structured index
   - `starter-reference/` - Cloned Mintlify starter kit with working examples

---

## The User's Mental Model

The user thinks about pflow documentation in layers:

| Layer | For Who | Lives Where |
|-------|---------|-------------|
| Marketing/value prop | Prospects | README.md |
| User docs | Humans using pflow | `docs/` (Mintlify) |
| AI agent instructions | AI tools | `pflow instructions` command |
| Implementation details | Contributors | `architecture/` |

**You are building layer 2.** Don't duplicate layers 1, 3, or 4.

---

## Why Monorepo (The Real Reason)

The user chose monorepo because: "AI agents can update docs atomically with code changes (single PR)". This is the PRIMARY driver. The version sync and simplicity are secondary benefits.

This means: when you implement features in pflow, you update docs in the same PR. The update policy in CLAUDE.md reflects this.

---

## The "Base Capabilities" Framing

The user specifically framed the node documentation as "base capabilities" - what pflow can do BEFORE you add any MCP servers:

**Document these:**
- `file` (read/write/copy/move/delete) - Universal
- `llm` - Core AI capability
- `http` - API calls without MCP
- `shell` - Unix power
- `claude-code` - Unique differentiator
- `mcp` - The bridge concept

**Skip these (user explicitly said):**
- `git` nodes - "not everyone uses git"
- `github` nodes - "requires GitHub setup"
- `test`, `echo` - "internal development nodes"

---

## Style Gotchas That Are Easy to Forget

1. **Sentence case headings** - "Getting started" not "Getting Started". This is a Mintlify convention.

2. **Lucide icons** - Not Font Awesome. All icons at lucide.dev. Common ones: `terminal`, `rocket`, `download`, `settings`, `bug`.

3. **No emoji** - The user was explicit about this.

4. **Second-person voice** - "You can run..." not "Users can run..."

5. **Language tags on ALL code blocks** - Even for simple examples.

---

## Components to Use vs Skip

**Use these:**
- `<Steps>` - For installation, procedures
- `<Tabs>` - For OS-specific (macOS vs Linux)
- `<Accordion>` - For troubleshooting, FAQ
- `<Card>` + `<Columns>` - For navigation grids
- `<Note>`, `<Warning>`, `<Tip>` - Sparingly

**Skip these (API-focused, not needed):**
- `<ParamField>`, `<ResponseField>` - API playground
- `<RequestExample>`, `<ResponseExample>` - API examples
- `<Color>`, `<LaTeX>` - Specialized

---

## Content Migration Sources

| Docs Page | Pull Content From |
|-----------|-------------------|
| `index.mdx` | README.md hero section (rewrite for doc style) |
| `quickstart.mdx` | README.md Quick Start |
| `guides/adding-mcp-servers.mdx` | README.md MCP sections |
| `integrations/*` | `docs/mcp-server.md` (exists) |
| `reference/cli/*` | Codebase research results (in spec) |
| `reference/nodes/*` | Codebase research results (in spec) |
| `reference/environment.mdx` | Codebase research results (in spec) |

**Don't copy-paste verbatim.** README is marketing-focused. Docs should be usage-focused.

---

## The ~22 Page Count

We went through several iterations:
1. I proposed 30 pages (too many)
2. User pushed back, I reduced to 12 (too few)
3. Landed on ~22 as the right balance

This count is:
- 3 getting started
- 4 guides
- 3 integrations
- 5 CLI reference
- 7 node reference

---

## What I Learned About CLI Structure

From codebase research, the CLI has 6 command groups:

```
pflow [request]      # Default - natural language / file / saved workflow
pflow mcp            # 7 subcommands
pflow registry       # 6 subcommands
pflow workflow       # 6 subcommands
pflow settings       # 9 subcommands
pflow instructions   # 2 subcommands
```

The reference pages should cover these, but focus on what users actually need. The `pflow instructions` command is NOT for user docs - that's for AI agents.

---

## Node Interfaces (From Research)

Key nodes to document with their main params:

**file nodes**: `file_path`, `content`, `encoding`
**llm**: `prompt`, `system`, `model`, `temperature`
**http**: `url`, `method`, `body`, `headers`, `auth_token`
**shell**: `command`, `cwd`, `env`, `timeout`
**claude-code**: `task`, `context`, `output_schema`, `allowed_tools`
**mcp**: Virtual nodes created by `pflow mcp sync`

---

## Environment Variables (From Research)

Key ones to document in `reference/environment.mdx`:

- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` - LLM providers
- `GITHUB_TOKEN` - For GitHub nodes
- `PFLOW_INCLUDE_TEST_NODES` - Show test nodes
- `PFLOW_TEMPLATE_RESOLUTION_MODE` - strict/permissive

Settings file: `~/.pflow/settings.json`
Workflows: `~/.pflow/workflows/`
Traces: `~/.pflow/debug/`

---

## The Debugging Guide Context

Traces are automatically saved to `~/.pflow/debug/workflow-trace-*.json`. The `--trace-planner` flag saves planner traces. The `--verbose` flag shows more output.

This is valuable for the debugging guide - users can analyze traces when things go wrong.

---

## Questions I Didn't Resolve

1. **Package name**: Assumed `pflow-cli` but not yet published. Verify before writing installation.mdx.

2. **Logo/favicon**: These need to be created. The spec assumes they exist in `docs/logo/` and `docs/favicon.svg`.

3. **Mintlify theme colors**: Used placeholder green values. May need brand colors.

4. **Mintlify dashboard**: Account setup is manual, not part of this task.

---

## Local Development Commands

```bash
npm i -g mint        # Install Mintlify CLI
cd docs
mint dev             # Preview at localhost:3000
mint broken-links    # Check for broken links
```

Requires Node.js 20.17.0+.

---

## Files to Create (Summary)

```
docs/
├── docs.json                    # CRITICAL - navigation config
├── favicon.svg                  # Needs design
├── logo/light.svg, dark.svg     # Needs design
├── index.mdx
├── quickstart.mdx
├── installation.mdx
├── guides/
│   ├── using-pflow.mdx
│   ├── adding-mcp-servers.mdx
│   ├── configuration.mdx
│   └── debugging.mdx
├── integrations/
│   ├── overview.mdx
│   ├── claude-desktop.mdx
│   └── cursor.mdx
└── reference/
    ├── cli/
    │   ├── index.mdx
    │   ├── workflows.mdx
    │   ├── registry.mdx
    │   ├── mcp.mdx
    │   └── settings.mdx
    ├── nodes/
    │   ├── index.mdx
    │   ├── file.mdx
    │   ├── llm.mdx
    │   ├── http.mdx
    │   ├── shell.mdx
    │   ├── claude-code.mdx
    │   └── mcp.mdx
    └── environment.mdx
```

`docs/CLAUDE.md` already exists - don't recreate it.

---

## Validation Checklist (Quick Reference)

Before considering done:
- [ ] `mint dev` runs without errors
- [ ] `mint broken-links` returns 0 broken links
- [ ] All MDX files have frontmatter with title + description
- [ ] All headings use sentence case
- [ ] All code blocks have language tags
- [ ] All internal links are relative
- [ ] No git, github, test, echo nodes documented
- [ ] No planner internals or IR schema documented

---

## Final Note

The user is thoughtful and will push back if something doesn't feel right. They care about:
1. Not over-engineering (MVP mindset)
2. Clear separation of concerns (docs vs architecture)
3. Practical utility (usage-focused, not theory)

When in doubt, ask yourself: "Would a human using pflow for the first time find this helpful?"

---

**IMPORTANT**: Do not begin implementing immediately. Read this memo, the spec, and `docs/CLAUDE.md` first. Then confirm you're ready to begin.
