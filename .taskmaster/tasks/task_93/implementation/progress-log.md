# Task 93 Implementation Progress Log

## 2025-12-09 - Session Start

Reading task context files and understanding the scope...

**Files read:**
- `task-93.md` - Main task definition
- `mintlify-docs-spec.md` - Detailed page structure (~22 pages planned)
- `task-93-handover.md` - Previous session's handover notes
- `task-93-spec.md` - Technical specification

**Initial understanding:**
- Goal: Set up Mintlify documentation for pflow in `/docs` folder
- Audience: Humans setting up pflow for their AI agents (NOT AI agents themselves)
- Structure: Two tabs (Documentation + Reference), ~22 MDX pages
- Logo files exist at `docs/logo/light.png` and `docs/logo/dark.png`

---

## 2025-12-09 - Open Questions Resolution

### Package name for installation

**Question:** What install command should docs show?

**Options discussed:**
1. `pip install pflow` - aspirational (not on PyPI yet)
2. `pip install pflow-cli` - what handover assumed
3. Install from source - accurate today

**Resolution:** Use `uv tool install` / `pipx install` from GitHub:
```bash
# Using uv (recommended)
uv tool install git+https://github.com/spinje/pflow.git

# Using pipx
pipx install git+https://github.com/spinje/pflow.git
```

💡 **Insight:** Both `uv tool install` and `pipx install` accept `git+https://...` URLs directly - no need to clone first. This is the modern Python CLI tool installation pattern.

### Decision: Skip "coming soon" for PyPI

User decided to show only what works today. No "coming soon" mentions - just update docs when PyPI is live.

---

## 2025-12-09 - README Installation Update

Updated README.md with correct installation commands in two places:
1. Quick Start section (line 57-62)
2. Installation section (line 273-281)

---

## 2025-12-09 - First Quickstart Attempt

Created `docs/quickstart.mdx` with:
- Install instructions
- API key setup
- Example commands

**❌ MAJOR DEVIATION - User Feedback**

User pointed out critical errors:
1. `pflow "read the file README.md and summarize it"` - outdated usage pattern
2. `--save` flag - **doesn't exist**
3. Documentation was based on assumptions, not verified CLI output

**Root cause:** I made assumptions about CLI behavior instead of verifying against actual `--help` output and source code.

💡 **Critical Insight:** pflow is designed to be used BY AI agents, not directly by humans for tasks. The primary use case is:
1. User installs pflow
2. User connects their AI agent (Claude Code, Cursor, etc.)
3. Agent runs `pflow instructions usage` to learn how to use it
4. Agent builds/runs workflows

---

## 2025-12-09 - Updated docs/CLAUDE.md with Verification Rules

Added critical section at top of `docs/CLAUDE.md`:

```markdown
## Critical: Verify Before Writing

**NEVER write documentation based on assumptions.** Before documenting any CLI command, flag, or behavior:

1. **Verify the command exists** - Run `pflow --help` or check `src/pflow/cli/`
2. **Verify flags exist** - Check the actual Click decorators in the code
3. **Test examples** - Every command you document must be runnable
4. **Check current usage patterns** - Run `pflow instructions usage` to see what we tell agents
```

Also updated the Overview section to clarify the primary use case.

---

## 2025-12-09 - CLI Verification

Ran actual CLI commands to understand real behavior:

```bash
uv run pflow --help
uv run pflow instructions usage
uv run pflow workflow --help
uv run pflow mcp --help
uv run pflow mcp add --help
uv run pflow mcp serve --help
```

**Key findings:**

| Command | Actual Syntax |
|---------|---------------|
| `pflow mcp add` | Takes config file or JSON, NOT positional args like `pflow mcp add name cmd args` |
| `pflow mcp sync` | Has `--all` flag, NOT `--force` |
| `pflow mcp serve` | Correct command for running pflow as MCP server |
| MCP config args | `["mcp", "serve"]` NOT `["mcp"]` |

**Workflow subcommands:**
- `pflow workflow list [FILTER_PATTERN]`
- `pflow workflow discover QUERY`
- `pflow workflow describe NAME`
- `pflow workflow save FILE`

---

## 2025-12-09 - Rewrote quickstart.mdx

New structure reflecting actual usage pattern:

1. Prerequisites (Python, uv/pipx)
2. Install pflow
3. Set up API key
4. **Connect to your AI agent** (the key section)
   - Option 1: CLI access - agent runs `pflow instructions usage`
   - Option 2: MCP server - add config to AI tool
5. What your agent can do
6. Troubleshooting

---

## 2025-12-09 - README.md Comprehensive Update

Fixed multiple sections with incorrect MCP commands:

### Quick Start (lines 53-104)
**Before:** Showed direct usage like `pflow "check my github PRs..."`
**After:** 3-step process: Install → API key → Connect to agent

### How AI Agents Use pflow (lines 294-327)
**Before:** Wrong MCP args `["mcp"]`
**After:** Correct args `["mcp", "serve"]`, CLI-first ordering

### MCP Integration - Quick Start (lines 340-370)
**Before:**
```bash
pflow mcp add filesystem npx @modelcontextprotocol/server-filesystem /Users/me/data
pflow mcp sync --force
```
**After:**
```bash
pflow mcp add ./github.mcp.json
pflow mcp add '{"filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/data"]}}'
```

### Added MCP transport mention
Added note that pflow supports both **local (stdio)** and **remote (HTTP)** MCP servers in "What is MCP?" section.

---

## 2025-12-09 - MCP Sync Discovery

**Question:** Is `pflow mcp sync` needed after `pflow mcp add`?

**Finding:** NO - auto-sync handles it automatically.

**How it works:**
1. `pflow mcp add` saves config to `~/.pflow/mcp-servers.json`
2. When any workflow runs, `_auto_discover_mcp_servers()` checks if sync needed
3. Smart detection via mtime + SHA256 hash of server list
4. Only syncs if config changed since last sync
5. Skips on warm starts (~500ms saved)

**When manual sync IS useful:**
- Testing connection immediately after add
- Debugging connection issues
- Forcing re-sync without running workflow

**Action taken:** Removed all `pflow mcp sync` from README quick start sections. Will keep in full CLI reference.

---

## 2025-12-09 - Color Decision

**Question:** What colors for Mintlify theme?

**Options discussed:**
1. Green (`#1b885f`, `#1c9f70`) - matches some branding
2. Orange (`#f97316` orange-500 family) - contrasts with gray logo

**Decision:** Use **orange as primary**, green for success states:

| Purpose | Color | Hex |
|---------|-------|-----|
| Primary/Brand | Orange | `#f97316` |
| Light accent | Orange | `#fb923c` |
| Links/hover | Orange | `#ea580c` |
| Success/positive | Green | `#1c9f70` (use when needed) |

**Reasoning:** Orange pops against the dark gray logo, conveys speed/action, more distinctive than green (many dev tools use green).

---

## 2025-12-09 - Created docs/docs.json

Created Mintlify configuration with:
- Colors: Orange primary (`#f97316`)
- Logo: PNG files at `/logo/light.png` and `/logo/dark.png`
- Two tabs: Documentation + Reference
- Navigation structure matching spec
- GitHub links in navbar and footer

---

## 2025-12-09 - API Key Deep Dive

**Critical clarification from user:** The API key understanding was wrong.

### What does NOT require pflow's API key:
- **Creating workflows** - the user's AGENT does this (Claude Code uses Claude, Cursor uses its models)
- Running saved workflows
- Running workflow files
- Registry list/describe/search
- MCP management
- Everything else

### What DOES require pflow's API key:
1. **Discovery commands** (`pflow registry discover`, `pflow workflow discover`) - LLM-powered intelligent search
2. **LLM nodes** - when workflows contain LLM nodes
3. **Structure-only smart filtering** - automatic field filtering for large responses (31+ fields)

### Why the API key matters (the core insight):

pflow's value is **intelligent discovery**. Without it:
- Agent has to view ALL available nodes/tools to find what it needs
- This defeats the purpose - back to the "MCP context tax" problem
- Technically works, but loses the main benefit

With it:
- `pflow registry discover "what I need"` → returns only relevant nodes
- `pflow workflow discover "what I want"` → finds matching workflows
- Progressive discovery: agent only sees what's actually needed

**When API key is critical:**
- When using MCP servers (they have many tools)
- When you have many saved workflows
- As your pflow library grows, intelligent discovery becomes essential

**Cost consideration:** pflow's discovery costs are minimal compared to running your agent directly. The small cost pays for itself many times over in reduced agent token usage, faster responses, and better output quality.

---

## 2025-12-09 - API Key Provider Discovery

**Question:** Which LLM providers does pflow support for its features?

**Finding:** Discovery features and structure-only are **Anthropic-only** currently.

**Evidence:** Code uses `install_anthropic_model()` throughout:
- `src/pflow/cli/registry.py` - registry discover
- `src/pflow/cli/commands/workflow.py` - workflow discover
- `src/pflow/cli/main.py` - planner

**Action:** Simplified quickstart to show only Anthropic API key (removed OpenAI tabs since it wouldn't work for discovery).

---

## 2025-12-09 - API Key Configuration Method

**Question:** How should users configure their API key?

**Problem with `export`:** Only lasts for current shell session.

**Correct methods:**
1. `pflow settings set-env ANTHROPIC_API_KEY "your-key"` - persists in pflow settings
2. `llm keys set anthropic` - if user has Simon Willison's `llm` CLI installed separately

**Note:** `llm` is a dependency of pflow but NOT exposed as a command after `uv tool install`. Users would need to install `llm` separately to use `llm keys set`.

**Decision:** Show `pflow settings set-env` as primary method, mention llm compatibility in a tip.

---

## 2025-12-09 - Deprecated/Not Documented Features

**`pflow "do this thing"`** (natural language direct execution):
- Not the primary flow anymore
- Not documented in quickstart
- Users should let their agent create workflows, not run pflow directly for tasks

---

## 2025-12-09 - Marketing Copy Review

Read `~/.research-and-marketing/landing-page-copy.md` to understand messaging.

**Key insight for docs:** Landing page is sales-focused. Docs need substance without sizzle:
- Explain WHAT features do, not sell them
- Reference blog posts for deep-dives on "how it works"
- Keep technical, not promotional

**Deep-dive features** (structure-only, smart filtering, token savings):
- Mention when relevant (e.g., in API key explanation)
- Link to blog posts for details (when available)
- Don't over-explain in user docs

---

## 2025-12-09 - Documentation Content Strategy

**Decision:** Different content types belong in different places:

| Content Type | Where it Goes | Example |
|--------------|---------------|---------|
| How to use it | User docs (Mintlify) | "Run `pflow workflow discover`" |
| Why it's fast/cheap | Blog posts | "How pflow achieves 94% token reduction" |
| How it works internally | Architecture docs (`architecture/`) | Implementation specs |
| Contributor context | CLAUDE.md files | Implementation details for AI agents |

**Key rules for user docs:**
- Document observable behavior, not mechanisms
- Don't link to `architecture/` docs from Mintlify (wrong audience)
- Reference blog posts for deep-dives on "how it works"
- Keep it simple and user-focused

**Existing README links to fix:**
README currently links to `architecture/features/mcp-integration.md` and `architecture/features/debugging.md`. These should either:
- Be migrated to Mintlify docs, OR
- Be replaced with blog post links when available

---

## Files Modified This Session

1. **README.md** - Multiple sections: Quick Start, MCP commands, installation
2. **docs/CLAUDE.md** - Added verification rules, updated overview
3. **docs/quickstart.mdx** - Complete rewrite for agent-first approach
4. **docs/docs.json** - Created with navigation, colors, logo
5. **docs/installation.mdx** - Created then deleted (merged into quickstart)
6. **docs/installation.md** - Deleted (old placeholder)

---

## Key Insights for Future Agents

### 1. pflow is agent-first
Users don't run `pflow "do something"` directly. They:
1. Install pflow
2. Connect their AI agent via CLI or MCP
3. Agent uses `pflow instructions usage` to learn the commands
4. Agent creates and runs workflows

### 2. Always verify CLI commands
Before documenting ANY command:
```bash
uv run pflow <command> --help
```

### 3. MCP config format
Correct MCP server config for AI tools:
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

### 4. MCP add syntax
```bash
# From config file
pflow mcp add ./config.mcp.json

# From JSON string
pflow mcp add '{"server-name": {"command": "...", "args": [...]}}'
```

NOT: `pflow mcp add name command args...`

### 5. Installation command (pre-PyPI)
```bash
uv tool install git+https://github.com/spinje/pflow.git
pipx install git+https://github.com/spinje/pflow.git
```

### 6. API key is for pflow's features, not workflow creation
- Agent creates workflows using ITS OWN LLM
- pflow's API key is for discovery commands, LLM nodes, smart filtering
- Currently Anthropic-only for discovery features

### 7. API key configuration
```bash
pflow settings set-env ANTHROPIC_API_KEY "your-key"
```
NOT: `export ANTHROPIC_API_KEY=...` (doesn't persist)

### 8. MCP sync is automatic
Don't tell users to run `pflow mcp sync` after `pflow mcp add` - auto-sync handles it.

### 9. Discovery is the core value
Intelligent discovery (`registry discover`, `workflow discover`) is how pflow avoids the MCP context tax. Without an API key, you lose this benefit.

---

## 2025-12-09 - Integration Pages Created

Created all 6 integration pages with verified information:

**Research conducted:**
- Claude Desktop MCP config location: `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
- Cursor MCP config: `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project)
- VS Code MCP config: `~/.vscode/mcp.json` or `.vscode/mcp.json`
- Windsurf MCP config: `~/.codeium/windsurf/mcp_config.json`
- Claude Code: `claude mcp add` command

**One-click install deeplinks generated:**

Cursor deeplink (base64 encoded):
```
cursor://anysphere.cursor-deeplink/mcp/install?name=pflow&config=eyJjb21tYW5kIjoicGZsb3ciLCJhcmdzIjpbIm1jcCIsInNlcnZlIl19
```

VS Code deeplink (URL encoded):
```
vscode:mcp/install?name=pflow&config=%7B%22type%22%3A%20%22stdio%22%2C%20%22command%22%3A%20%22pflow%22%2C%20%22args%22%3A%20%5B%22mcp%22%2C%20%22serve%22%5D%7D
```

---

## Current Status - All Files Checklist

### Configuration
- [x] `docs/docs.json` - Navigation, colors (orange), logo paths

### Getting Started
- [x] `docs/quickstart.mdx` - **COMPLETE** - Install, API key, connect to agent
- [ ] `docs/index.mdx` - Placeholder only ("Documentation coming soon")

### Guides
- [ ] `docs/guides/using-pflow.mdx` - Placeholder only
- [ ] `docs/guides/adding-mcp-servers.mdx` - Placeholder only
- [ ] `docs/guides/debugging.mdx` - Placeholder only

### Integrations (ALL COMPLETE)
- [x] `docs/integrations/overview.mdx` - **COMPLETE** - Comparison table, links
- [x] `docs/integrations/claude-code.mdx` - **COMPLETE** - CLI + MCP options
- [x] `docs/integrations/claude-desktop.mdx` - **COMPLETE** - MCP setup, macOS note
- [x] `docs/integrations/cursor.mdx` - **COMPLETE** - One-click install + manual
- [x] `docs/integrations/vscode.mdx` - **COMPLETE** - One-click install + manual
- [x] `docs/integrations/windsurf.mdx` - **COMPLETE** - CLI + MCP options

### CLI Reference
- [ ] `docs/reference/cli/index.mdx` - Placeholder only
- [ ] `docs/reference/cli/workflow.mdx` - Placeholder only
- [ ] `docs/reference/cli/registry.mdx` - Placeholder only
- [ ] `docs/reference/cli/mcp.mdx` - Placeholder only
- [ ] `docs/reference/cli/settings.mdx` - Placeholder only

### Node Reference
- [ ] `docs/reference/nodes/index.mdx` - Placeholder only
- [ ] `docs/reference/nodes/file.mdx` - Placeholder only
- [ ] `docs/reference/nodes/llm.mdx` - Placeholder only
- [ ] `docs/reference/nodes/http.mdx` - Placeholder only
- [ ] `docs/reference/nodes/shell.mdx` - Placeholder only
- [ ] `docs/reference/nodes/claude-code.mdx` - Placeholder only
- [ ] `docs/reference/nodes/mcp.mdx` - Placeholder only

### Configuration Reference
- [ ] `docs/reference/configuration.mdx` - Placeholder only

### Other Files Updated
- [x] `README.md` - Quick Start, MCP commands, installation
- [x] `docs/CLAUDE.md` - Verification rules

### Deleted (old .md files)
- [x] `docs/index.md`
- [x] `docs/installation.md`
- [x] `docs/getting-started.md`
- [x] `docs/examples.md`
- [x] `docs/nodes.md`
- [x] `docs/mcp-http-transport.md`
- [x] `docs/mcp-server.md`

---

## Summary

**Complete (ready to use):** 8 pages
- quickstart.mdx
- integrations/overview.mdx
- integrations/claude-code.mdx
- integrations/claude-desktop.mdx
- integrations/cursor.mdx
- integrations/vscode.mdx
- integrations/windsurf.mdx
- docs.json (config)

**Placeholder (need content):** 15 pages
- index.mdx (homepage)
- 3 guide pages
- 5 CLI reference pages
- 6 node reference pages
- 1 configuration page

---

## 2025-12-09 - Introduction Page Strategy

**Discussion:** What should the index.mdx page contain?

**Decision:** Introduction page (not just navigation hub):
- What is pflow (brief explanation)
- Why it exists (the problem it solves)
- Who it's for
- Two execution modes
- Navigation cards at bottom

**Key insight - Two execution modes:**
pflow isn't just "for AI agents" - it has two modes:
1. **Agent-driven**: Agent discovers, creates, runs workflows
2. **Direct CLI**: Saved workflows are CLI commands for scripts, CI/CD, cron

This is important because "Plan Once, Run Forever" means the compiled workflow becomes a simple CLI command anyone (or any script) can run without an agent.

**Content guidelines for introduction:**
- Non-salesy - state problems factually
- No specific numbers (94% token reduction) - that's marketing
- Save "structure-only orchestration" for later (blog/deep-dive)
- Keep short (~200-300 words before cards)

---

## 2025-12-09 - UI Consistency Updates

**Prerequisites boxes:** Added `<Info>` prerequisites boxes to:
- All 6 integration pages ("Install pflow before continuing")
- quickstart.mdx (Python 3.10+ and uv/pipx)

This matches the standard Mintlify pattern for prerequisite callouts.

---

## Current Status - All Files Checklist

### Configuration
- [x] `docs/docs.json` - Navigation, colors (orange), logo paths

### Getting Started
- [x] `docs/index.mdx` - **COMPLETE** - Introduction with problem/solution/cards
- [x] `docs/quickstart.mdx` - **COMPLETE** - Install, API key, connect to agent

### Guides
- [x] `docs/guides/adding-mcp-servers.mdx` - **COMPLETE** - Full MCP guide
- [ ] `docs/guides/using-pflow.mdx` - Placeholder only
- [ ] `docs/guides/debugging.mdx` - Placeholder only

### Integrations (ALL COMPLETE)
- [x] `docs/integrations/overview.mdx` - **COMPLETE** - Comparison table, links
- [x] `docs/integrations/claude-code.mdx` - **COMPLETE** - CLI + MCP options
- [x] `docs/integrations/claude-desktop.mdx` - **COMPLETE** - MCP setup, macOS note
- [x] `docs/integrations/cursor.mdx` - **COMPLETE** - One-click install + manual
- [x] `docs/integrations/vscode.mdx` - **COMPLETE** - One-click install + manual
- [x] `docs/integrations/windsurf.mdx` - **COMPLETE** - CLI + MCP options

### CLI Reference
- [ ] `docs/reference/cli/index.mdx` - Placeholder only
- [ ] `docs/reference/cli/workflow.mdx` - Placeholder only
- [ ] `docs/reference/cli/registry.mdx` - Placeholder only
- [ ] `docs/reference/cli/mcp.mdx` - Placeholder only
- [ ] `docs/reference/cli/settings.mdx` - Placeholder only

### Node Reference
- [ ] `docs/reference/nodes/index.mdx` - Placeholder only
- [ ] `docs/reference/nodes/file.mdx` - Placeholder only
- [ ] `docs/reference/nodes/llm.mdx` - Placeholder only
- [ ] `docs/reference/nodes/http.mdx` - Placeholder only
- [ ] `docs/reference/nodes/shell.mdx` - Placeholder only
- [ ] `docs/reference/nodes/claude-code.mdx` - Placeholder only
- [ ] `docs/reference/nodes/mcp.mdx` - Placeholder only

### Configuration Reference
- [ ] `docs/reference/configuration.mdx` - Placeholder only

### Other Files Updated
- [x] `README.md` - Quick Start, MCP commands, installation
- [x] `docs/CLAUDE.md` - Verification rules

---

## Summary

**Complete (ready to use):** 15 pages
- index.mdx (Introduction)
- quickstart.mdx
- guides/adding-mcp-servers.mdx
- 6 integration pages
- 5 CLI reference pages (index, workflow, registry, mcp, settings)
- docs.json (config)

**Placeholder (need content):** 9 pages
- 2 guide pages (using-pflow, debugging)
- 6 node reference pages
- 1 configuration page

---

## 2025-12-11 - CLI Reference Pages Complete

Created all 5 CLI reference pages:

### reference/cli/index.mdx
- Command structure overview
- Card navigation to subcommands
- Global options table
- Parameter syntax and type inference
- Stdin input, output modes, validation mode
- Trace system documentation

### reference/cli/workflow.mdx
- `list` - Filter patterns, JSON output
- `describe` - Show workflow interface
- `discover` - AI-powered workflow search
- `save` - Save with metadata generation
- Workflow file format example

### reference/cli/registry.mdx
- `list` - Node listing with grouping
- `describe` - Node interface details
- `discover` - AI-powered node search
- `scan` - Custom node scanning
- `run` - Single node execution with structure mode

### reference/cli/mcp.mdx
- `add` - Config formats (simple, full MCP, HTTP)
- `list`, `remove` - Server management
- `sync` - Tool discovery
- `tools`, `info` - Tool inspection
- `serve` - Running pflow as MCP server
- Tool naming conventions

### reference/cli/settings.mdx
- `init`, `show`, `reset` - Settings management
- `set-env`, `unset-env`, `list-env` - API key management
- `allow`, `deny`, `remove`, `check` - Node filtering
- Filter precedence explanation
- Environment variable precedence

**Methodology:**
- Used 5 parallel pflow-codebase-searcher agents to research CLI implementations
- Cross-referenced Click decorators and docstrings in source code
- Followed Mintlify docs guidelines (sentence case headings, second-person voice)

---

## 2025-12-11 - CLI Reference Verification & Fixes

Ran 5 parallel pflow-codebase-searcher agents to verify CLI documentation against actual implementation.

**Issues found and fixed:**

| File | Issue | Fix |
|------|-------|-----|
| index.mdx | Missing 5 planner options | Added `--planner-timeout`, `--save/--no-save`, `--cache-planner`, `--planner-model`, `--no-update` in collapsible section |
| index.mdx | Missing `pflow instructions` command | Added documentation for `usage` and `create` subcommands |
| registry.mdx | `describe` documented as single node | Fixed to show it accepts multiple nodes (`<NODE>...`) |
| registry.mdx | `describe` showed `--json` flag | Removed (doesn't exist in implementation) |

**No changes needed:** settings.mdx (fully accurate), workflow.mdx subcommands (accurate), mcp.mdx (accurate - noted `--all` on tools is non-functional in code)

---

## 2025-12-11 - Natural Language Mode De-emphasized

User feedback: Natural language CLI mode (`pflow "do something"`) is experimental and not the recommended path.

**Changes made:**
- Collapsed natural language section into `<Accordion title="Natural language mode (experimental)">`
- Collapsed planner options into `<Accordion title="Planner options (experimental)">`
- Updated card description from "Run workflows by name, file, or natural language" → "Run workflows by name or file"
- Updated stdin examples to use saved workflows instead of natural language

---

## 2025-12-11 - Human vs Agent Voice Clarification

**Key insight:** Documentation is for humans, but most commands are run by agents. This was creating confusing language like "Use registry run to test..." when humans don't run that command.

**Solution:** Added Note callouts at top of each CLI reference page clearly stating who runs the commands:

| Page | Audience |
|------|----------|
| index.mdx | "Most commands are run by your AI agent, not you directly" |
| registry.mdx | "Agent commands" (except `scan`) |
| workflow.mdx | "Agent commands" (except `save`) |
| mcp.mdx | "Setup commands" - you run `add/remove/sync`, agent uses `tools/info` |
| settings.mdx | "Your commands" - never let agents run these |

**Also fixed:** Specific phrases like "Use X to..." → "Agents use X to..."

---

## 2025-12-11 - Security Warning for API Keys

Added explicit warnings that users should never let agents set API keys:
- `settings.mdx`: Warning callout on `set-env` command
- `settings.mdx`: Warning on `list-env --show-values`
- Changed example from `OPENAI_API_KEY` to `ANTHROPIC_API_KEY` (what pflow actually uses)
- Added tip about `llm keys set anthropic` as alternative

---

## 2025-12-11 - guides/using-pflow.mdx Created (by user)

User wrote this page explaining the mental model:
- "You don't need to learn the schema" - agent handles it
- "Your agent guides you when needed" - agent tells you commands to run
- "What happens behind the scenes" - workflow reuse pattern
- Summary table of who handles what

**Minor fixes applied:** Fixed duplicate step number (3→4), converted code blocks to blockquotes for agent dialogue.

---

## 2025-12-11 - CLI/MCP Equivalence Documented

Added section to `integrations/overview.mdx` explaining that CLI and MCP provide the same capabilities:

> "Both methods give your agent the same functionality - the MCP server mirrors the CLI commands with minor adjustments for structured tool use."

This helps users understand why there are two integration options.

---

## Current Status

**Complete:** 23 pages
- index.mdx, quickstart.mdx
- guides/using-pflow.mdx, guides/adding-mcp-servers.mdx
- 6 integration pages
- 5 CLI reference pages
- 7 node reference pages (index + 6 nodes)
- docs.json

**Placeholder:** 2 pages
- guides/debugging.mdx
- reference/configuration.mdx

---

## 2025-12-11 - Node Reference Pages Complete

Created all 7 node reference pages with comprehensive documentation:

### reference/nodes/index.mdx
- Overview of node system
- Card grid linking to all node pages
- Explanation of parameters vs shared store
- Node discovery commands
- MCP extension pattern

### reference/nodes/file.mdx
- 5 file nodes: read-file, write-file, copy-file, move-file, delete-file
- Complete parameter and output tables
- Binary handling (base64 encoding)
- Line numbering for text files
- Safety mechanism for delete-file (confirm_delete)
- Example workflows

### reference/nodes/llm.mdx
- Integration with Simon Willison's llm library
- All parameters: prompt, model, system, temperature, max_tokens, images
- Token usage output structure
- Model support table (OpenAI, Anthropic, Google, local)
- Automatic JSON parsing
- Image support for vision models
- Temperature guide

### reference/nodes/http.mdx
- All HTTP methods supported
- Authentication options (auth_token, api_key - mutually exclusive)
- Response handling (JSON, binary, text)
- Method auto-detection
- Query parameters
- Binary file download example

### reference/nodes/shell.mdx
- stdin for data (not command interpolation!)
- stdin type handling table
- Security: blocked patterns (rm -rf /, fork bombs, etc.)
- Security: warning patterns (sudo, shutdown)
- Smart error handling (grep exit code 1 as success)
- Environment variables and working directory

### reference/nodes/claude-code.mdx
- Task and execution parameters
- Authentication tabs (API key vs CLI)
- Structured output with output_schema
- Schema field types
- Tool permissions (Read, Write, Edit, Bash)
- Metadata structure (cost, duration, tokens)

### reference/nodes/mcp.mdx
- How MCP tools become nodes
- Node naming pattern: mcp-{server}-{tool}
- Output key structure (result, {server}_{tool}_result, extracted fields)
- Example workflow with GitHub + Slack
- Transport types (stdio, http)
- Authentication configuration
- Auto-sync behavior

**Research method:** Used 6 parallel pflow-codebase-searcher agents to gather accurate interface information from source code

---

## Key Insights for Future Work

### Documentation voice pattern
- **Human setup commands** (settings, mcp add/remove): Use "you"
- **Agent commands** (registry, workflow list/describe): Use "Your agent" or "Agents"
- **Shared commands** (running workflows): Can be either

### Natural language mode is experimental
Don't position `pflow "do something"` as primary usage. The stable path is:
1. Agent builds workflow JSON
2. Agent runs `pflow workflow.json` or `pflow saved-name`

### CLI and MCP are equivalent
Both provide same functionality - document this so users understand either works.

---

## 2025-12-12 - Debugging Page & Guides Refinement

### guides/debugging.mdx Created

**Core philosophy:** The debugging page is about **reassurance**, not a tutorial. Users don't debug pflow - their agents do.

**Structure:**
1. "Your agent handles most debugging" - agent gets structured errors
2. "What your agent sees" - JSON example with `available_fields`
3. "Trace files" - automatic, agents read them when stuck
4. "What only you can fix" - API keys, MCP setup, disk cleanup
5. Link to experimental features

**Key insight - Agent-first error design:**
pflow errors include `available_fields`, "Did you mean?" suggestions, and execution state - all designed for agent self-correction. The agent instructions (`pflow instructions create`) already teach agents how to use trace files.

**Trace file access note:** Added clarification that trace file inspection requires local filesystem access (works with Claude Code, Cursor; not with Claude Desktop/ChatGPT Desktop unless filesystem MCP is configured).

### guides/using-pflow.mdx Enhanced

**New sections added:**
1. **Split API vs MCP guidance:**
   - "Need to connect to an API?" → Agent uses http node, reads docs
   - "Need an MCP server?" → Agent helps find and install

2. **"Not everything needs a workflow"** - Documents `pflow registry run` for:
   - One-off tasks without full workflow
   - Testing nodes during workflow development

3. **MCP server creation tip:** If calling same API repeatedly, consider having agent create an MCP server for it.

4. **Debugging link:** "Something unexpected happen?" with link to debugging guide

**Closing message refined:** "Think of pflow as the infrastructure that makes this scalable - turning automation into reusable building blocks that are discoverable, composable, and ready for your agent to use again and again."

### guides/adding-mcp-servers.mdx Fixes

**Package name corrections:**
| Server | Old (Wrong) | New (Correct) |
|--------|-------------|---------------|
| GitHub | `@modelcontextprotocol/server-github` | `@github/mcp-server` |
| Brave | `@anthropic/mcp-server-brave-search` | `@brave/brave-search-mcp-server` |
| Filesystem | (unchanged) | `@modelcontextprotocol/server-filesystem` |

**Other improvements:**
- Changed common servers from hard-to-read one-liners to proper JSON config files
- Added env var expansion pattern (`${GITHUB_TOKEN}`) consistent with docs
- Filesystem note: Built-in file nodes cover basic operations; MCP server for advanced/sandboxing
- Added `pflow settings deny "pflow.nodes.file.*"` to disable built-ins if using MCP
- Added Tip about agents creating MCP servers for repeated API usage
- Fixed `set-env` syntax to use space (`KEY "value"`) not equals

### reference/experimental.mdx Created

**New page for experimental features:**

1. **Built-in git/github nodes** (disabled by default)
   - Recommendation: Use `git`/`gh` CLI via shell node (agents know these tools well)
   - Alternative: GitHub MCP server for complex operations
   - "If you still want to try" section with enable commands

2. **Natural language planner** - Experimental, external agents recommended

3. **Auto-repair** - Not enabled by default, `--auto-repair` flag

4. **Feedback section** - Links to Discussions (ideas) and Issues (bugs)

**Navigation:** Added "Experimental" group under Reference tab in docs.json

### Settings Pattern Format

**Correct format for node filtering:**
```bash
pflow settings deny "pflow.nodes.file.*"
```

NOT `file-*` or `*-file`. The module path format is used.

---

## Key Insights for Future Work

### Debugging docs = Reassurance, not tutorial
Users don't need to learn debugging. The message is: "Your agent handles it. Here's the few things only you can fix."

### Trace files are for agents
Agents read `~/.pflow/debug/workflow-trace-*.json` when stuck. Users don't need to inspect them manually.

### Agent-first error design
Structured errors with `available_fields` and suggestions enable self-correction. This is documented in the blog insights file for the agent-first design blog post.

### Building blocks philosophy
The closing message emphasizes: scalability through reusable, discoverable, composable building blocks. This differentiates pflow from one-off scripts.

### git/gh CLI over built-in nodes
Agents know `git` and `gh` extremely well from training. Shell node + CLI is the recommended path, not built-in git/github nodes.

### Experimental features separated
Keeps main docs clean. Cross-links from relevant places point to `/reference/experimental`.

---

## Current Status

**Complete:** 25 pages
- index.mdx, quickstart.mdx
- guides/using-pflow.mdx, guides/adding-mcp-servers.mdx, guides/debugging.mdx
- 6 integration pages
- 5 CLI reference pages
- 7 node reference pages
- reference/experimental.mdx
- docs.json

**Placeholder:** 1 page
- reference/configuration.mdx

---

## Files Created/Modified This Session

**Created:**
- `docs/guides/debugging.mdx`
- `docs/reference/experimental.mdx`
- `scratchpads/mintlify-docs/agent-first-design-debugging-insights.md` (blog research)

**Modified:**
- `docs/guides/using-pflow.mdx` - Multiple enhancements
- `docs/guides/adding-mcp-servers.mdx` - Package fixes, formatting
- `docs/docs.json` - Added Experimental group

---

## 2025-12-15 - Configuration Page & Final Polish

### reference/configuration.mdx Created

**Complete reference for all pflow configuration:**

1. **Settings file structure** - Full JSON schema with all fields
2. **Environment variables:**
   - API keys via `pflow settings set-env`
   - pflow config vars (`PFLOW_INCLUDE_TEST_NODES`, `PFLOW_TEMPLATE_RESOLUTION_MODE`, `PFLOW_SHELL_STRICT`)
   - Trace config vars (`PFLOW_TRACE_PROMPT_MAX`, etc.)
   - Precedence order: CLI params → settings.json → system env

3. **Node filtering:**
   - Pattern syntax (glob-style: `pflow.nodes.file.*`, `mcp-github-*`)
   - Evaluation order (test nodes → deny → allow → default)
   - Commands for allow/deny/remove/check
   - Verification with `pflow registry list`

4. **File locations:**
   - Complete `~/.pflow/` inventory
   - What's safe to delete table
   - MCP config reference (links to full guide)

### guides/using-pflow.mdx Final Enhancements

- Split "Need to use a new MCP or API?" into two items:
  - "Need to connect to an API?" → Agent uses http node
  - "Need an MCP server?" → Agent helps install
- Added Tip about creating MCP servers for repeated API usage
- Added http node cross-link

### guides/adding-mcp-servers.mdx Verification

- Verified npm package names via web search:
  - `@github/mcp-server` (official, GitHub moved it)
  - `@brave/brave-search-mcp-server` (Brave's official fork)
  - `@modelcontextprotocol/server-filesystem` (unchanged)
- Added note about built-in file nodes vs filesystem MCP
- Corrected `pflow settings deny` pattern format: `"pflow.nodes.file.*"` (module path)

### guides/debugging.mdx Refinements

- Clarified trace file access: works with Claude Code, Cursor; needs filesystem MCP for Claude Desktop
- Updated auto-repair section: not enabled by default, `--auto-repair` flag
- Clarified planner traces: experimental because whole planner is experimental
- Linked git/github nodes to `/reference/experimental#built-in-git-and-github-nodes`

### Decisions Made

1. **template_resolution_mode** - Kept in settings table but don't explain in detail (edge case)
2. **Cleanup commands removed** - "What's safe to delete" table is enough, users know `rm`
3. **Verification commands added** - Show `pflow registry list` to verify filtering

---

## Key Insights for Future Work

### Node filtering pattern format
Use module path format: `pflow.nodes.file.*`, NOT `file-*` or `*-file`

### MCP package names change
Always verify npm packages before documenting - they move/rename frequently:
- GitHub server moved from `@modelcontextprotocol` to `@github`
- Brave Search has official Brave fork now

### Configuration docs = Reference, not tutorial
Show structure and options. Don't over-explain edge cases like `template_resolution_mode`.

### git/github nodes are experimental
Link to `/reference/experimental` when mentioning them. Recommend shell + CLI instead.

---

## Current Status

**Complete:** 26 pages (ALL PAGES DONE)
- index.mdx, quickstart.mdx
- guides/using-pflow.mdx, guides/adding-mcp-servers.mdx, guides/debugging.mdx
- 6 integration pages
- 5 CLI reference pages
- 7 node reference pages
- reference/configuration.mdx
- reference/experimental.mdx
- docs.json

**Placeholder:** 0 pages

---

## 2025-12-15 - MCP Resources Update

Updated adding-mcp-servers.mdx:
- Replaced mcp.run/smithery.ai with official MCP registry + awesome-mcp-servers
- Fixed deprecated npm packages (GitHub, Brave Search)
- Added filesystem node note about built-in alternatives
- Future: HTTP MCP services guide (scratchpad created)

---

## Task 93 Complete

All documentation pages have been created and reviewed. Ready for final review and publication.
