# AI Agent Prompt for Removing MCP References from taskmaster-instructions.md

## Task Overview
You need to continue editing the file `.taskmaster/docs/taskmaster-instructions.md` to remove ALL references to MCP (Model Context Protocol) tools and focus ONLY on CLI commands. The user has already started this work on lines 1-11, and you need to complete the rest of the document.

## Critical Instructions

### 1. PRESERVE Everything Except MCP Content
- **DO NOT** change any wording, formatting, or structure unless it's directly related to MCP
- **DO NOT** rewrite sections or "improve" the documentation
- **DO NOT** change section numbers, headers, or organization
- **KEEP** all CLI commands, descriptions, and usage instructions exactly as they are
- **KEEP** the exact same line breaks, spacing, and markdown formatting

### 2. What to REMOVE (Delete These Lines/Sections Entirely)
For each command section, remove:
- Lines starting with `*   **MCP Tool:**`
- Lines starting with `*   **MCP Variant Description:**`
- Lines starting with `*   **Key MCP Parameters/Options:**`
- Lines starting with `*   **Usage (MCP):**`
- Any other lines that specifically mention MCP tools or MCP-specific functionality
- References to `mcp.json` files
- References to MCP/Cursor integration

### 3. What to KEEP
For each command section, keep:
- `### [Number]. [Command Name] ([command_name])`
- `*   **CLI Command:**`
- `*   **Description:**`
- `*   **Key CLI Options:**` (Note: Some sections say "Key Parameters/Options" - standardize to "Key CLI Options")
- `*   **Usage:**`
- `*   **Notes:**`
- `*   **Important:**`
- All other content that doesn't mention MCP

### 4. Specific Changes to Make

#### In the "Models" section (around line 269-295):
- Remove all MCP-specific parameter descriptions
- Keep only the CLI options and usage
- Update the API note to only mention .env files (remove mcp.json reference)

#### In the "Important" note (around line 221-222):
- Change: "Several CLI commands involve AI processing..."
- To: "Several commands involve AI processing..."
- Remove the sentence about "AI-powered tools include" since it references MCP tools

#### At the end of sections:
- Remove any warnings about preferring MCP tools over CLI
- Remove references to "MCP Variant" or "MCP tool"

#### In the Environment Variables section (around line 593-615):
- Remove references to `.cursor/mcp.json`
- Keep only the `.env` file references
- Update text to focus solely on CLI usage

### 5. Line-by-Line Instructions

Start from line 12 (after the user's edits) and continue through the entire document:

1. **Lines 12-34**: Keep as-is (standard workflow process)
2. **Lines 35-214**: Keep as-is (these sections don't have MCP references)
3. **Line 217 onwards**: This is where the detailed command reference starts. For EACH command section:
   - Delete the MCP Tool line
   - Keep the CLI Command line
   - Keep the Description
   - Delete MCP Variant Description
   - Keep Key CLI Options (rename from "Key Parameters/Options" if needed)
   - Delete Key MCP Parameters/Options
   - Keep Usage
   - Delete Usage (MCP)
   - Keep Notes, Important, etc.

### 6. Example Transformation

**BEFORE:**
```markdown
### 1. Initialize Project (`init`)

*   **MCP Tool:** `initialize_project`
*   **CLI Command:** `task-master init [options]`
*   **Description:** `Set up the basic Taskmaster file structure...`
*   **Key CLI Options:**
    *   `--name <name>`: `Set the name...`
*   **Usage:** Run this once at the beginning...
*   **MCP Variant Description:** `Set up the basic...`
*   **Key MCP Parameters/Options:**
    *   `projectName`: `Set the name...`
*   **Usage (MCP):** Run this once...
```

**AFTER:**
```markdown
### 1. Initialize Project (`init`)

*   **CLI Command:** `task-master init [options]`
*   **Description:** `Set up the basic Taskmaster file structure...`
*   **Key CLI Options:**
    *   `--name <name>`: `Set the name...`
*   **Usage:** Run this once at the beginning...
```

### 7. Final Review Checklist
After making changes:
- [ ] All MCP Tool references removed
- [ ] All MCP Variant descriptions removed
- [ ] All MCP Parameters removed
- [ ] All MCP Usage sections removed
- [ ] No references to mcp.json remain
- [ ] No references to MCP/Cursor integration remain
- [ ] All CLI content preserved exactly as it was
- [ ] Section numbers and structure unchanged
- [ ] Markdown formatting preserved

## CRITICAL: Minimal Changes Policy
Remember: The goal is to make the SMALLEST possible change to achieve the objective. Do not:
- Reword descriptions
- Reorganize content
- Add new information
- Remove content that isn't specifically about MCP
- Change formatting or spacing (except where MCP lines are deleted)

The user has specifically emphasized "change as little as possible" - respect this requirement above all else.
