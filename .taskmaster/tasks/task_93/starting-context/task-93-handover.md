# Task 93 Handoff Memo: Mintlify Documentation

**Session Date**: 2025-12-11 (builds on 2025-12-09 session)

---

## The One Thing That Matters Most (NEW)

**Documentation is for humans, but documents commands that agents run.**

This creates a unique voice challenge. We solved it with a consistent pattern:

| Command Type | Voice | Example |
|--------------|-------|---------|
| Human setup commands | "you" | "Set your API key with `pflow settings set-env`" |
| Agent commands | "Your agent" / "Agents" | "Agents use `registry run` to test nodes" |
| Shared commands | Either | "Run workflows with `pflow my-workflow`" |

Every CLI reference page now has a **Note callout at the top** stating who runs these commands:

| Page | Note |
|------|------|
| index.mdx | "Most commands are run by your AI agent, not you directly..." |
| registry.mdx | "**Agent commands.** ...except `scan` - you run that..." |
| workflow.mdx | "**Agent commands.** ...`save` can be used by either..." |
| mcp.mdx | "**Setup commands.** You run `add/remove/sync`, agent uses `tools/info`" |
| settings.mdx | "**Your commands.** ...never by an AI agent." |

---

## Critical Rule: VERIFY BEFORE WRITING

**Before documenting ANY command:**
```bash
uv run pflow <command> --help
```

This rule is in `docs/CLAUDE.md`. We ran 5 parallel pflow-codebase-searcher agents to verify CLI docs and found real issues:

| Issue | Fix |
|-------|-----|
| `registry describe` documented as single node | Changed to `<NODE>...` (accepts multiple) |
| `registry describe` showed `--json` flag | Removed (doesn't exist in code) |
| Missing 5 planner options in index.mdx | Added in collapsed Accordion |
| Missing `pflow instructions` command | Added full documentation |

---

## Critical: Natural Language Mode is Experimental (NEW)

The user explicitly stated: `pflow "do something"` is **not stable**.

**What we did:**
- Collapsed into `<Accordion title="Natural language mode (experimental)">`
- Collapsed planner options into `<Accordion title="Planner options (experimental)">`
- Updated card: "Run workflows by name or file" (removed "or natural language")
- Changed stdin examples to use saved workflows

**The stable path is:**
1. Agent builds workflow JSON using registry/workflow commands
2. Agent runs `pflow workflow.json` or `pflow saved-name`

---

## Security: Never Let Agents Set API Keys (NEW)

Added explicit warnings:

```mdx
<Warning>
  **Security:** Always set API keys yourself - never let AI agents run this command.
</Warning>
```

This appears on `settings.mdx` at `set-env` and `list-env --show-values`.

---

## Key Technical Decisions (from previous session)

### Installation Method (pre-PyPI)
```bash
uv tool install git+https://github.com/spinje/pflow.git
pipx install git+https://github.com/spinje/pflow.git
```

### MCP Server Config Format
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
**Critical**: Args are `["mcp", "serve"]` NOT `["mcp"]`.

### API Key Configuration
```bash
pflow settings set-env ANTHROPIC_API_KEY "your-key"
```
NOT `export ANTHROPIC_API_KEY=...` (doesn't persist).

Added tip about `llm keys set anthropic` as alternative.

### API Key is Anthropic-Only
Discovery features use `install_anthropic_model()` - hardcoded to Anthropic.

### MCP Sync is NOT Needed
Auto-sync happens when workflows run. Don't tell users to run `pflow mcp sync` after adding servers.

---

## What the API Key is Actually For

**pflow's API key is for:**
- Discovery commands (`pflow registry discover`, `pflow workflow discover`)
- LLM nodes in workflows
- Smart filtering (automatic field selection for 31+ fields)

**pflow's API key is NOT for:**
- Creating workflows - the user's AGENT does this with its own LLM

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

## Config File Locations

| Tool | Location |
|------|----------|
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Cursor (global) | `~/.cursor/mcp.json` |
| Cursor (project) | `.cursor/mcp.json` |
| VS Code | `~/.vscode/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |

---

## MCP Concepts to Keep Straight

Two different things:
1. **pflow AS an MCP server** - AI tools connect to pflow via `pflow mcp serve`
2. **Adding MCP servers TO pflow** - Workflows use external tools via `pflow mcp add`

The integration pages cover #1. The `guides/adding-mcp-servers.mdx` covers #2.

---

## CLI/MCP Equivalence (NEW)

Added section to `integrations/overview.mdx`:

> "Both methods give your agent the same functionality - the MCP server mirrors the CLI commands with minor adjustments for structured tool use."

---

## guides/using-pflow.mdx (NEW)

**The user wrote this page.** It captures the mental model:
- "You don't need to learn the schema"
- "Your agent guides you when needed"
- "What happens behind the scenes" (workflow reuse pattern)

This is the **tone template** for remaining content.

---

## Current Status

**Complete (16 pages):**
- index.mdx, quickstart.mdx
- guides/using-pflow.mdx, guides/adding-mcp-servers.mdx
- 6 integration pages
- 5 CLI reference pages
- docs.json

**Placeholder (8 pages):**
- guides/debugging.mdx
- reference/nodes/* (6 pages)
- reference/configuration.mdx

---

## Node Interfaces (For Remaining Node Docs)

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

## Environment Variables (For configuration.mdx)

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | LLM provider for discovery features |
| `GITHUB_TOKEN` | For GitHub nodes |
| `PFLOW_INCLUDE_TEST_NODES` | Show test nodes in registry |
| `PFLOW_TEMPLATE_RESOLUTION_MODE` | strict/permissive |

**File locations:**
- Settings: `~/.pflow/settings.json`
- Workflows: `~/.pflow/workflows/`
- Traces: `~/.pflow/debug/`

---

## Documentation Layers

| Layer | For Who | Lives Where |
|-------|---------|-------------|
| Marketing/value prop | Prospects | README.md |
| User docs | Humans using pflow | `docs/` (Mintlify) |
| AI agent instructions | AI tools | `pflow instructions` command |
| Implementation details | Contributors | `architecture/` |

**You are building layer 2.** Don't duplicate layers 1, 3, or 4.

---

## Content Guidelines

1. **Non-salesy** - State problems factually, no marketing speak
2. **No specific numbers** - "94% token reduction" is for landing page
3. **macOS only** - pflow verified on macOS only
4. **Natural language is experimental** - Use Accordion, don't position as primary

---

## Don't Forget Checklist

1. **Icons in frontmatter** - Every page needs `icon: "..."` in YAML
2. **Note callout at top** - State who runs these commands
3. **Accordion for experimental** - Natural language, planner options
4. **Security warnings** - Anywhere API keys are mentioned
5. **"Agents use..." not "Use..."** - For agent commands
6. **Verify before writing** - Run pflow-codebase-searcher agents

---

## Key Files to Read

| File | Why |
|------|-----|
| `docs/guides/using-pflow.mdx` | Tone template (user wrote this) |
| `docs/reference/cli/settings.mdx` | Security warning pattern |
| `docs/reference/cli/index.mdx` | Voice pattern, Accordion pattern |
| `docs/CLAUDE.md` | Documentation guidelines |
| `.taskmaster/tasks/task_93/implementation/progress-log.md` | Full history |
| `.taskmaster/tasks/task_93/starting-context/mintlify-docs-spec.md` | Original structure spec |

---

## Branch

Work is on branch `task-93-mintlify-docs`.

---

**IMPORTANT**: Do not begin implementing immediately. Read this memo, `docs/guides/using-pflow.mdx` (tone template), and `docs/CLAUDE.md` first. Then confirm you're ready to continue.
