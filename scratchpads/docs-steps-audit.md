# Docs Audit: Steps Component Usage

## Task

Audit all docs/ files to identify where the `<Steps>` component would improve readability for sequential procedures.

## When to use Steps

Per docs/CLAUDE.md: `<Steps>` is for "Sequential procedures (installation)"

Good candidates:
- Multi-step setup procedures
- "First do X, then do Y" patterns
- Installation/configuration flows

NOT good for:
- Single commands
- Reference documentation (keep terse)
- Non-sequential information

## Files to audit

```
docs/
├── index.mdx                   # Landing page
├── quickstart.mdx              # Installation - likely candidate
├── changelog.mdx               # Changelog - probably not
├── roadmap.mdx                 # Roadmap - probably not
├── guides/
│   ├── using-pflow.mdx         # Conceptual - probably not
│   ├── publishing-skills.mdx   # ✅ Already using Steps (skip)
│   ├── adding-mcp-servers.mdx  # Likely candidate - setup flow
│   └── debugging.mdx           # Maybe - troubleshooting steps?
├── how-it-works/
│   ├── batch-processing.mdx    # Conceptual - probably not
│   └── template-variables.mdx  # Conceptual - probably not
├── integrations/
│   ├── overview.mdx            # Overview - probably not
│   ├── claude-code.mdx         # Setup steps?
│   ├── claude-desktop.mdx      # Setup steps?
│   ├── cursor.mdx              # Setup steps?
│   ├── vscode.mdx              # Setup steps?
│   └── windsurf.mdx            # Setup steps?
└── reference/                  # Probably keep terse, but audit to confirm
    ├── configuration.mdx
    ├── experimental.mdx
    ├── cli/
    │   ├── index.mdx
    │   ├── mcp.mdx
    │   ├── registry.mdx
    │   ├── settings.mdx
    │   ├── skill.mdx
    │   └── workflow.mdx
    └── nodes/
        ├── index.mdx
        ├── claude-code.mdx
        ├── file.mdx
        ├── http.mdx
        ├── llm.mdx
        ├── mcp.mdx
        └── shell.mdx
```

**Total: 31 files** (30 to audit, 1 already using Steps)

## Audit checklist

For each file:
1. [ ] Read the file
2. [ ] Identify any "First... Then..." or numbered step patterns
3. [ ] Evaluate if Steps would improve clarity
4. [ ] Note recommendation

## Findings

(To be filled in during audit)

### Root files

#### index.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### quickstart.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### changelog.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### roadmap.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

### guides/

#### guides/using-pflow.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### guides/adding-mcp-servers.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### guides/debugging.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

### how-it-works/

#### how-it-works/batch-processing.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### how-it-works/template-variables.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

### integrations/

#### integrations/overview.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### integrations/claude-code.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### integrations/claude-desktop.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### integrations/cursor.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### integrations/vscode.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### integrations/windsurf.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

### reference/

#### reference/configuration.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### reference/experimental.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### reference/cli/index.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### reference/cli/mcp.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### reference/cli/registry.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### reference/cli/settings.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### reference/cli/skill.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### reference/cli/workflow.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### reference/nodes/index.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### reference/nodes/claude-code.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### reference/nodes/file.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### reference/nodes/http.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### reference/nodes/llm.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### reference/nodes/mcp.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

#### reference/nodes/shell.mdx
- Status: Not audited
- Current: ?
- Recommendation: ?

## Summary

**Audit completed: 2026-02-05**

- Total files audited: **30/30**
- Files needing Steps: **3**
- Files with MAYBE recommendation: **1**
- Files already using Steps: **1** (guides/publishing-skills.mdx)

### Files that should use Steps

| File | Current Pattern | Recommendation |
|------|-----------------|----------------|
| `integrations/claude-desktop.mdx` | Numbered h3 headings: "1. Open...", "2. Add...", "3. Restart...", "4. Verify..." | **USE STEPS** - 4-step sequential setup |
| `integrations/vscode.mdx` | Numbered h3 headings in "Manual setup" section | **USE STEPS** - 3-step sequential setup |
| `integrations/windsurf.mdx` | Numbered h3 headings under "Option 2: MCP server" | **USE STEPS** - 3-step sequential setup |

### Maybe (low priority)

| File | Current Pattern | Recommendation |
|------|-----------------|----------------|
| `quickstart.mdx` | Install + Verify sections | Could use Steps, but current Tabs structure works fine |

### Key Pattern Observed

The integration guides for **Claude Desktop**, **VS Code**, and **Windsurf** all use numbered h3 headings (`### 1. Open...`, `### 2. Add...`, etc.) for their MCP server setup procedures. These are perfect candidates for the `<Steps>` component.

Reference documentation uses numbered lists to explain internal behavior/patterns (e.g., "How node filtering works"), NOT user procedures - these should stay as-is.

### Detailed findings

See `scratchpads/docs-steps-audit/findings.md` for per-file audit details.
