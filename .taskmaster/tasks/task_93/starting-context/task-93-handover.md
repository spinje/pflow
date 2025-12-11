# Task 93 Handoff Memo: Mintlify Documentation Setup

**Session Date**: 2025-12-09 (Updated)

## Critical Rule: VERIFY BEFORE WRITING

**This is the most important lesson from this session.**

I made a major mistake early on - wrote documentation based on assumptions about CLI behavior. The user caught errors like:
- `pflow "read the file README.md"` - outdated/deprecated pattern
- `--save` flag - **doesn't exist**
- Wrong MCP command syntax throughout README

**Before documenting ANY command:**
```bash
uv run pflow <command> --help
```

This rule is now in `docs/CLAUDE.md` - read it before writing any new content.

---

## Understanding pflow's Purpose (CORRECTED)

**Previous handover was partially wrong.** pflow docs are for HUMANS who:
1. Set up pflow for their AI tools (Claude Code, Cursor, etc.)
2. Configure and manage pflow (MCP servers, settings, workflows)

**NOT for:**
- AI agents reading docs (they use `pflow instructions usage`)
- Humans running pflow directly for tasks (agents do this)

**Two execution modes** (important for positioning):
1. **Agent-driven**: Agent discovers, creates, runs workflows
2. **Direct CLI**: Saved workflows are CLI commands for scripts/CI/CD/cron

Both are valid. "Plan Once, Run Forever" means compiled workflows become simple CLI commands.

---

## Key Technical Decisions Made This Session

### 1. Installation Method (pre-PyPI)
```bash
uv tool install git+https://github.com/spinje/pflow.git
pipx install git+https://github.com/spinje/pflow.git
```
NOT `pip install pflow` (not on PyPI yet).

### 2. MCP Server Config Format
```json
{
  "mcpServers": {
    "pflow": {
      "command": "pflow",
      "args": ["mcp", "serve"]
    }
  }
}
```
**Critical**: Args are `["mcp", "serve"]` NOT `["mcp"]`. I fixed this in multiple places in README.

### 3. API Key Configuration
```bash
pflow settings set-env ANTHROPIC_API_KEY "your-key"
```
NOT `export ANTHROPIC_API_KEY=...` (doesn't persist).

The `llm` CLI is a dependency but NOT exposed as a command after `uv tool install`. Users need `pflow settings set-env`.

### 4. API Key is Anthropic-Only (for now)
Discovery features (`registry discover`, `workflow discover`) use `install_anthropic_model()` - hardcoded to Anthropic. OpenAI won't work for these features.

### 5. MCP Sync is NOT Needed
`pflow mcp add` saves config. Auto-sync happens when workflows run. Don't tell users to run `pflow mcp sync` after adding servers - it's unnecessary complexity.

---

## What the API Key is Actually For

This was confusing and took discussion to clarify:

**pflow's API key is for:**
- Discovery commands (`pflow registry discover`, `pflow workflow discover`)
- LLM nodes in workflows
- Smart filtering (automatic field selection for 31+ fields)

**pflow's API key is NOT for:**
- Creating workflows - the user's AGENT does this with the agent's own LLM

**Why it matters:**
Intelligent discovery is the core value. Without API key + MCP servers, agent has to view ALL tools to find what it needs - defeats the purpose.

---

## One-Click Install Deeplinks (Verified)

### Cursor (base64 encoded)
```
cursor://anysphere.cursor-deeplink/mcp/install?name=pflow&config=eyJjb21tYW5kIjoicGZsb3ciLCJhcmdzIjpbIm1jcCIsInNlcnZlIl19
```

### VS Code (URL-encoded)
```
vscode:mcp/install?name=pflow&config=%7B%22type%22%3A%20%22stdio%22%2C%20%22command%22%3A%20%22pflow%22%2C%20%22args%22%3A%20%5B%22mcp%22%2C%20%22serve%22%5D%7D
```

Generation commands:
```bash
# Cursor (base64, no trailing newline)
echo -n '{"command":"pflow","args":["mcp","serve"]}' | base64

# VS Code (URL-encoded)
python3 -c "import urllib.parse; import json; config = json.dumps({'type':'stdio','command':'pflow','args':['mcp','serve']}); print(urllib.parse.quote(config))"
```

---

## Files Status

### Complete (10 pages)
- `docs/docs.json` - Navigation, orange colors (#f97316), logo paths
- `docs/index.mdx` - Introduction with problem/solution/cards
- `docs/quickstart.mdx` - Install, API key, connect to agent
- `docs/guides/adding-mcp-servers.mdx` - Full MCP guide
- `docs/integrations/overview.mdx` - Comparison table
- `docs/integrations/claude-code.mdx` - CLI + MCP options
- `docs/integrations/claude-desktop.mdx` - MCP setup (macOS only note)
- `docs/integrations/cursor.mdx` - One-click + manual
- `docs/integrations/vscode.mdx` - One-click + manual
- `docs/integrations/windsurf.mdx` - CLI + MCP options

### Placeholder Only (14 pages)
- `docs/guides/using-pflow.mdx`
- `docs/guides/debugging.mdx`
- `docs/reference/cli/index.mdx`
- `docs/reference/cli/workflow.mdx`
- `docs/reference/cli/registry.mdx`
- `docs/reference/cli/mcp.mdx`
- `docs/reference/cli/settings.mdx`
- `docs/reference/nodes/index.mdx`
- `docs/reference/nodes/file.mdx`
- `docs/reference/nodes/llm.mdx`
- `docs/reference/nodes/http.mdx`
- `docs/reference/nodes/shell.mdx`
- `docs/reference/nodes/claude-code.mdx`
- `docs/reference/nodes/mcp.mdx`
- `docs/reference/configuration.mdx`

### Files Updated
- `README.md` - Fixed Quick Start, MCP commands, installation
- `docs/CLAUDE.md` - Added verification rules

### Old Files Deleted
- `docs/index.md`, `docs/installation.md`, `docs/getting-started.md`
- `docs/examples.md`, `docs/nodes.md`
- `docs/mcp-http-transport.md`, `docs/mcp-server.md`

---

## Commands Verified This Session

These are accurate as of this session:
```bash
pflow --help
pflow mcp --help          # add, list, remove, sync, serve, tools, info
pflow mcp add --help      # Takes config file or JSON string
pflow mcp list --help
pflow mcp sync --help     # Has --all flag, NOT --force
pflow mcp serve --help
pflow mcp tools --help    # Has -a/--all and --json flags
pflow mcp info --help
pflow mcp remove --help
pflow workflow --help     # list, discover, describe, save
pflow workflow list --help
pflow workflow discover --help
pflow settings --help     # set-env, show, allow, deny, etc.
pflow settings set-env --help
pflow registry discover --help
```

---

## Content Guidelines (from user)

1. **Non-salesy** - State problems factually, no marketing speak
2. **No specific numbers** - "94% token reduction" is for landing page, not docs
3. **Structure-only for later** - Deep technical explanations go in blog posts
4. **macOS only** - pflow verified on macOS only, note this in Claude Desktop page
5. **`pflow "do something"` is deprecated** - Don't document natural language direct execution

---

## Anti-Patterns Found in README (Fixed)

The README had many incorrect commands I fixed:
- `pflow mcp add filesystem npx ...` → Wrong, use config file or JSON string
- `pflow mcp sync --force` → `--force` doesn't exist, use `--all`
- `["mcp"]` → `["mcp", "serve"]`
- `pip install pflow` → `uv tool install git+...`

---

## MCP Concepts to Keep Straight

Two different things:
1. **pflow AS an MCP server** - AI tools connect to pflow via `pflow mcp serve`
2. **Adding MCP servers TO pflow** - Workflows use external tools via `pflow mcp add`

The integration pages cover #1. The `guides/adding-mcp-servers.mdx` covers #2.

---

## Config File Locations (verified via web search)

| Tool | Location |
|------|----------|
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Cursor (global) | `~/.cursor/mcp.json` |
| Cursor (project) | `.cursor/mcp.json` |
| VS Code | `~/.vscode/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |

---

## Documentation Layers (User's Mental Model)

| Layer | For Who | Lives Where |
|-------|---------|-------------|
| Marketing/value prop | Prospects | README.md |
| User docs | Humans using pflow | `docs/` (Mintlify) |
| AI agent instructions | AI tools | `pflow instructions` command |
| Implementation details | Contributors | `architecture/` |

**You are building layer 2.** Don't duplicate layers 1, 3, or 4.

---

## CLI Structure Overview

From codebase research, the CLI has 6 command groups:

```
pflow [request]      # Default - natural language / file / saved workflow
pflow mcp            # 7 subcommands (add, list, remove, sync, serve, tools, info)
pflow registry       # 6 subcommands (list, describe, discover, search, scan, run)
pflow workflow       # 4 subcommands (list, discover, describe, save)
pflow settings       # 9 subcommands (set-env, show, allow, deny, etc.)
pflow instructions   # 2 subcommands (usage, create)
```

The `pflow instructions` command is NOT for user docs - that's for AI agents.

---

## Node Interfaces (From Previous Research)

Key nodes to document with their main params:

| Node | Key Parameters |
|------|----------------|
| `file` | `file_path`, `content`, `encoding` |
| `llm` | `prompt`, `system`, `model`, `temperature` |
| `http` | `url`, `method`, `body`, `headers`, `auth_token` |
| `shell` | `command`, `cwd`, `env`, `timeout` |
| `claude-code` | `task`, `context`, `output_schema`, `allowed_tools` |
| `mcp` | Virtual nodes created by `pflow mcp sync` |

**Verify these against actual code before documenting.**

---

## Environment Variables (From Previous Research)

Key ones to document in `reference/configuration.mdx`:

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | LLM provider for discovery features |
| `OPENAI_API_KEY` | Alternative LLM provider (limited support) |
| `GITHUB_TOKEN` | For GitHub nodes |
| `PFLOW_INCLUDE_TEST_NODES` | Show test nodes in registry |
| `PFLOW_TEMPLATE_RESOLUTION_MODE` | strict/permissive |

**File locations:**
- Settings: `~/.pflow/settings.json`
- Workflows: `~/.pflow/workflows/`
- Traces: `~/.pflow/debug/`

---

## Debugging Guide Context

Traces are automatically saved to `~/.pflow/debug/workflow-trace-*.json`.

Key debugging features:
- `--trace-planner` flag saves planner traces
- `--verbose` flag shows more output
- Trace files contain step-by-step execution details

This is valuable for the debugging guide - users can analyze traces when things go wrong.

---

## Content Migration Sources

| Docs Page | Pull Content From |
|-----------|-------------------|
| `index.mdx` | README.md hero (rewrite for doc style) |
| `quickstart.mdx` | README.md Quick Start |
| `guides/adding-mcp-servers.mdx` | README.md MCP sections |
| `integrations/*` | Web research + verified configs |
| `reference/cli/*` | `--help` output (verified) |
| `reference/nodes/*` | Codebase research (verify interfaces) |
| `reference/configuration.mdx` | Codebase research (verify env vars) |

**Don't copy-paste from README verbatim.** README is marketing-focused. Docs should be usage-focused.

---

## What Still Needs Verification

Before writing remaining pages, verify from code:
- Node interfaces (params, types, defaults)
- Trace file format and location
- All environment variables and their effects
- Settings file structure

---

## Next Priority Actions

1. **Test with Mintlify** - We have enough content
   ```bash
   npm install -g mintlify
   cd /Users/andfal/projects/pflow/docs
   mintlify dev
   ```

2. **CLI reference pages** - Can generate from `--help` output

3. **guides/using-pflow.mdx** - Agent workflow: discover → run → build

---

## Key Files to Read

- `.taskmaster/tasks/task_93/implementation/progress-log.md` - Full session history with all decisions
- `docs/CLAUDE.md` - Documentation guidelines and verification rules
- `docs/quickstart.mdx` - Template for how we structured content
- `docs/integrations/cursor.mdx` - Example of one-click install pattern
- `.taskmaster/tasks/task_93/starting-context/mintlify-docs-spec.md` - Original structure spec

---

## Questions the User Should Answer

1. Should debugging guide cover trace files, `--verbose`, or both?
2. What patterns should `using-pflow.mdx` cover? (discover → run → build flow?)
3. Any additional integrations beyond the current 5?

---

**IMPORTANT**: Do not begin implementing immediately. Read this memo, the progress log at `.taskmaster/tasks/task_93/implementation/progress-log.md`, and `docs/CLAUDE.md` first. Then confirm you're ready to continue.
