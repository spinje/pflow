# Research Prompt: pflow v0.6.0 Changelog Entry

## Objective

Research and verify the features, capabilities, and limitations of pflow for the initial v0.6.0 release changelog entry. The goal is to ensure the changelog accurately represents what users get and any caveats they should know about.

## Current Draft Location

`/Users/andfal/projects/pflow/docs/changelog.mdx`

## Research Tasks

### 1. Verify Current Features

For each category, confirm accuracy and identify anything missing:

**Workflow Engine**
- [ ] Natural language → workflow compilation (how does it work? what's the planner?)
- [ ] Template variables (`${variable}` syntax) - what can they reference?
- [ ] Validation system - what errors does it catch? repair suggestions?
- [ ] Execution traces - where are they saved? what info do they contain?
- [ ] Workflow save/load - named workflows, file-based workflows
- [ ] Any other workflow features?

**Built-in Nodes** (check `src/pflow/nodes/`)
- [ ] File nodes - which operations exactly? (read, write, copy, move, delete, list?)
- [ ] LLM node - how does it integrate with `llm` library? which models work?
- [ ] HTTP node - what capabilities? headers, auth, methods?
- [ ] Shell node - risk assessment system, how does it work?
- [ ] Claude Code node - what does "agentic development" mean specifically?
- [ ] MCP bridge node - how does it connect MCP servers?
- [ ] Any other nodes? (git, github, test, echo?)

**Agent Integration**
- [ ] CLI commands - which commands are user-facing? (`pflow run`, `pflow workflow`, etc.)
- [ ] MCP server - what tools does it expose? (`pflow mcp serve`)
- [ ] Instructions system - what is `pflow instructions`?
- [ ] Which AI tools are officially supported? Configuration for each?

**Discovery & Planning**
- [ ] How does natural language planning work?
- [ ] Node discovery - how does it find relevant nodes?
- [ ] Workflow discovery - searching saved workflows
- [ ] Two-phase discovery mentioned in docs - what is it?

**Developer Tools**
- [ ] Settings management - what can be configured?
- [ ] Node filtering (allow/deny lists)
- [ ] Registry system
- [ ] Debugging capabilities

### 2. Identify Limitations & Known Issues

Research what users should know before using pflow:

- [ ] API key requirements (which features need which keys?)
- [ ] Anthropic-only features vs general features
- [ ] Windows/Linux/macOS support status
- [ ] Experimental features (natural language mode, others?)
- [ ] Performance considerations
- [ ] Security considerations (shell execution, file access)
- [ ] Any known bugs or rough edges?

### 3. Compare with Documentation

Check consistency between:
- [ ] `README.md` - what does it promise?
- [ ] `docs/quickstart.mdx` - what's the getting started flow?
- [ ] `docs/index.mdx` - how is pflow described?
- [ ] `architecture/` docs - any user-facing features mentioned there?
- [ ] `CLAUDE.md` - current project status and completed tasks

### 4. Output

After research, provide:

1. **Verified feature list** - Accurate, complete list of v0.6.0 features
2. **Suggested changelog updates** - Any additions/corrections to the current draft
3. **Limitations section** - Comprehensive list of known limitations
4. **Questions for maintainer** - Anything that needs clarification

## Key Files to Research

```
src/pflow/
├── cli/                    # User-facing commands
├── nodes/                  # All node implementations
├── mcp_server/            # MCP server for agents
├── planning/              # Natural language planner
├── core/settings.py       # Settings management
└── registry/              # Node discovery

docs/
├── quickstart.mdx
├── index.mdx
├── guides/
├── integrations/
└── reference/

README.md
CLAUDE.md (project status)
```

## Research Approach

1. Start with `CLAUDE.md` to understand completed tasks
2. Read `README.md` for the public-facing description
3. Explore `src/pflow/nodes/` to verify node capabilities
4. Check `src/pflow/cli/` for user-facing commands
5. Review `docs/` for any features mentioned there
6. Look for TODO comments, experimental flags, or limitations in code
7. Check test files for edge cases and known issues

## Deliverable

Update the changelog entry at `docs/changelog.mdx` with:
- Complete, verified feature list
- Accurate limitations
- Any additional accordions if needed (e.g., "For developers", "Security notes")

Keep the format consistent with the current structure using Mintlify's `<Accordion>` components.
