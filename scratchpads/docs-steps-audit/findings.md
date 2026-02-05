# Docs Steps Audit - Findings Log

## Audit Progress

Started: 2026-02-05

---

### 1. index.mdx
- **Status**: Audited
- **Current**: Conceptual intro with numbered list explaining how pflow helps (1. plan, 2. compile, 3. execute), plus CardGroup navigation
- **Sequential patterns found**: Numbered list under "How pflow helps" but it's conceptual explanation, not user procedure
- **Recommendation**: NO STEPS - Not procedural content, the numbered list explains a concept

---

### 2. quickstart.mdx
- **Status**: Audited
- **Current**: Uses Tabs for install alternatives, separate sections for API key setup and agent connection
- **Sequential patterns found**:
  - Install → Verify installation (2-step sequence)
  - Overall page flow: Install → Configure API → Connect agent
- **Recommendation**: MAYBE STEPS - Could wrap "Install pflow" + "Verify installation" in Steps. However, the rest uses Tabs/Options appropriately. Low priority since current structure is clear.

---

### 3. changelog.mdx
- **Status**: Audited
- **Current**: Uses Update components for timeline, Accordion for details
- **Sequential patterns found**: None - announcement/release notes format
- **Recommendation**: NO STEPS - Not procedural content

---

### 4. roadmap.mdx
- **Status**: Audited
- **Current**: Bullet lists of features by timeframe (Now/Next/Later/Vision)
- **Sequential patterns found**: None - planning/roadmap format
- **Recommendation**: NO STEPS - Not procedural content

---

### 5. guides/using-pflow.mdx
- **Status**: Audited
- **Current**: Conceptual guide explaining agent-driven workflow, commands examples, summary table
- **Sequential patterns found**: Numbered list under "What happens behind the scenes" (1-4 steps) but describes what the *agent* does, not user steps
- **Recommendation**: NO STEPS - Conceptual explanation, not user procedure

---

### 6. guides/adding-mcp-servers.mdx
- **Status**: Audited
- **Current**: Reference-style guide with multiple sections showing alternatives (from config file OR JSON), management commands, troubleshooting Accordions
- **Sequential patterns found**: None - shows alternatives and independent commands, not a single sequential flow
- **Recommendation**: NO STEPS - Reference-style with alternatives, not sequential procedure

---

### 7. guides/debugging.mdx
- **Status**: Audited
- **Current**: Conceptual guide about agent self-healing, trace files, what users need to fix (API keys, MCP issues, disk cleanup)
- **Sequential patterns found**: None - "What only you can fix" has independent scenarios, not sequential steps
- **Recommendation**: NO STEPS - Conceptual with independent troubleshooting scenarios

---

### 8. how-it-works/batch-processing.mdx
- **Status**: Audited
- **Current**: Technical deep-dive with configuration tables, code examples, output structures, examples
- **Sequential patterns found**: None - explains what pflow does internally, not user procedures
- **Recommendation**: NO STEPS - Technical explanation, not procedural

---

### 9. how-it-works/template-variables.mdx
- **Status**: Audited
- **Current**: Technical deep-dive on template syntax with examples, type preservation, JSON auto-parsing
- **Sequential patterns found**: Numbered list under "Nested access" (1-5 steps) explaining internal traversal
- **Recommendation**: NO STEPS - Technical explanation of internals, not user procedure

---

### 10. integrations/overview.mdx
- **Status**: Audited
- **Current**: Overview page with CardGroup navigation, explanation of two connection methods, comparison table
- **Sequential patterns found**: None - navigation and comparison page
- **Recommendation**: NO STEPS - Navigation/overview page, not procedural

---

### 11. integrations/claude-code.mdx
- **Status**: Audited
- **Current**: Setup guide with two options (CLI access or MCP server), each with separate sections
- **Sequential patterns found**: Option 2 has implicit steps (add command, verify) but structured as alternatives
- **Recommendation**: NO STEPS - Alternatives structure, not a single sequential procedure

---

### 12. integrations/claude-desktop.mdx
- **Status**: Audited
- **Current**: Setup guide with numbered heading sections: "1. Open your MCP config file", "2. Add pflow to your config", "3. Restart Claude Desktop", "4. Verify installation"
- **Sequential patterns found**: YES - Clear 4-step sequential setup procedure with numbered headings
- **Recommendation**: **USE STEPS** - Perfect candidate, 4-step sequential setup procedure

---

### 13. integrations/cursor.mdx
- **Status**: Audited
- **Current**: Has "One-click install", "Manual setup" with two options (MCP server or CLI access)
- **Sequential patterns found**: None explicit - alternatives structure
- **Recommendation**: NO STEPS - Alternatives structure (one-click vs manual, then MCP vs CLI)

---

### 14. integrations/vscode.mdx
- **Status**: Audited
- **Current**: Has "One-click install" and "Manual setup" with numbered sections: "1. Open your MCP config file", "2. Add pflow to your config", "3. Reload VS Code"
- **Sequential patterns found**: YES - Manual setup has clear 3-step sequential procedure with numbered headings
- **Recommendation**: **USE STEPS** - The "Manual setup" section is a good candidate for Steps component

---

### 15. integrations/windsurf.mdx
- **Status**: Audited
- **Current**: Has "Option 1: CLI access" and "Option 2: MCP server" with numbered sections under Option 2: "1. Open your MCP config file", "2. Add pflow to your config", "3. Restart Windsurf"
- **Sequential patterns found**: YES - Option 2 has clear 3-step sequential procedure with numbered headings
- **Recommendation**: **USE STEPS** - The "Option 2: MCP server" section is a good candidate for Steps component

---

### 16. reference/configuration.mdx
- **Status**: Audited
- **Current**: Reference doc with settings structure, tables, env vars, node filtering, file locations
- **Sequential patterns found**: Numbered list (1-4) under "Evaluation order" but explains internal logic, not user steps
- **Recommendation**: NO STEPS - Reference documentation, keep terse

---

### 17. reference/experimental.mdx
- **Status**: Audited
- **Current**: Reference doc for experimental features (Git/GitHub nodes, planner, auto-repair)
- **Sequential patterns found**: None
- **Recommendation**: NO STEPS - Reference documentation

---

### 18. reference/cli/index.mdx
- **Status**: Audited
- **Current**: CLI overview with CardGroup navigation, command tables, parameter syntax, output modes
- **Sequential patterns found**: None
- **Recommendation**: NO STEPS - Reference documentation

---

### 19. reference/cli/mcp.mdx
- **Status**: Audited
- **Current**: CLI reference for mcp commands with examples, "Common workflows" section
- **Sequential patterns found**: "Initial setup" shows 3 commands but presented as example workflow, not numbered procedure
- **Recommendation**: NO STEPS - Reference documentation, examples are illustrative not step-by-step instructions

---

### 20. reference/cli/registry.mdx
- **Status**: Audited
- **Current**: CLI reference for registry commands (list, describe, discover, scan, run)
- **Sequential patterns found**: None
- **Recommendation**: NO STEPS - Reference documentation

---

### 21. reference/cli/settings.mdx
- **Status**: Audited
- **Current**: CLI reference for settings commands with comprehensive documentation
- **Sequential patterns found**: Numbered list (1-4) under "How node filtering works" but explains internal evaluation order
- **Recommendation**: NO STEPS - Reference documentation

---

### 22. reference/cli/skill.mdx
- **Status**: Audited
- **Current**: CLI reference for skill commands (save, list, remove)
- **Sequential patterns found**: Numbered list (1-2) inside Accordion "What happens during save" - explains internal behavior
- **Recommendation**: NO STEPS - Reference documentation

---

### 23. reference/cli/workflow.mdx
- **Status**: Audited
- **Current**: CLI reference for workflow commands (list, describe, history, discover, save)
- **Sequential patterns found**: None
- **Recommendation**: NO STEPS - Reference documentation

---

### 24. reference/nodes/index.mdx
- **Status**: Audited
- **Current**: Nodes overview with CardGroup, explains how nodes work
- **Sequential patterns found**: Numbered list (1-4) under "How nodes work" - explains internal node pattern
- **Recommendation**: NO STEPS - Reference documentation

---

### 25. reference/nodes/claude-code.mdx
- **Status**: Audited
- **Current**: Node reference with parameters, output, authentication options, examples
- **Sequential patterns found**: None
- **Recommendation**: NO STEPS - Reference documentation

---

### 26. reference/nodes/file.mdx
- **Status**: Audited
- **Current**: Node reference for file operations (read, write, copy, move, delete)
- **Sequential patterns found**: None
- **Recommendation**: NO STEPS - Reference documentation

---

### 27. reference/nodes/http.mdx
- **Status**: Audited
- **Current**: Node reference for HTTP requests
- **Sequential patterns found**: None
- **Recommendation**: NO STEPS - Reference documentation

---

### 28. reference/nodes/llm.mdx
- **Status**: Audited
- **Current**: Node reference for LLM calls with model support, plugins, examples
- **Sequential patterns found**: None
- **Recommendation**: NO STEPS - Reference documentation

---

### 29. reference/nodes/mcp.mdx
- **Status**: Audited
- **Current**: Node reference for MCP tools
- **Sequential patterns found**: Numbered list (1-4) under "How it works" - explains internal workflow
- **Recommendation**: NO STEPS - Reference documentation

---

### 30. reference/nodes/shell.mdx
- **Status**: Audited
- **Current**: Node reference for shell commands with security info
- **Sequential patterns found**: None
- **Recommendation**: NO STEPS - Reference documentation

---

## Summary

**Total files audited**: 30/30

**Files that should use Steps** (3 total):
1. **integrations/claude-desktop.mdx** - 4-step sequential setup procedure (Open config → Add pflow → Restart → Verify)
2. **integrations/vscode.mdx** - 3-step sequential procedure in "Manual setup" section
3. **integrations/windsurf.mdx** - 3-step sequential procedure in "Option 2: MCP server" section

**Files with MAYBE recommendation** (1 total):
1. **quickstart.mdx** - Could wrap "Install pflow" + "Verify installation" in Steps, but current structure is clear. Low priority.

**Files already using Steps** (1 total):
1. guides/publishing-skills.mdx (not audited - already confirmed)

**Pattern observed**: The integration setup guides are the primary candidates because they have clear "1. Do this, 2. Then this, 3. Finally this" flows for setting up MCP servers. Reference documentation uses numbered lists to explain internal behavior/patterns, not user procedures.

