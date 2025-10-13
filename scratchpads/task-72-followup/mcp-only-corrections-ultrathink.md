# MCP-AGENT_INSTRUCTIONS.md - MCP-Only Corrections Ultrathink

## Core Problem Identified

The document still has "CLI contamination" that will confuse MCP agents:
1. References to CLI (even in comparison sections)
2. "MCP Advantage" notes that compare to CLI
3. Confusion about when to use workflow dicts vs paths
4. "Built-in behavior" notes that imply CLI comparison

## Core Principles for MCP-Only Document

### Principle 1: CLI Never Existed
- Write as if this is THE ONLY way to use pflow
- No comparisons, no "advantages", no "built-in behaviors"
- Just state how things work, period

### Principle 2: Agent Operating Environment
**Assumption**: Agents using this document are operating on the user's local machine via MCP

**This means:**
- Agents have filesystem access
- Agents should write intermediate workflows to `.pflow/workflows/workflow.json`
- Agents should reference workflows by path: `workflow=".pflow/workflows/workflow.json"`
- Agents are NOT in a sandbox environment

**Dict format (`workflow={"nodes": [...]}`) is ONLY for:**
- Sandbox environments (desktop apps, web services)
- NOT for agents on local machines

### Principle 3: Clear Operational Guidance
Instead of saying "MCP has this advantage", just state:
- "Write your workflow to `.pflow/workflows/workflow.json`"
- "Validate with: `workflow_validate(workflow=".pflow/workflows/workflow.json")`"
- "Traces are saved to `~/.pflow/debug/workflow-trace-*.json`"

No comparisons, no "built-in", just operational facts.

## Sections to Remove Entirely

### 1. "About MCP vs CLI" Section (Lines 6-30)
**Why**: Confuses agents by introducing CLI concept
**Action**: DELETE entire section

### 2. "MCP Built-in Behaviors" Note (Line 37)
**Current**: `> **MCP Built-in Behaviors**: MCP never auto-repairs (built-in) • MCP always saves traces (built-in)`
**Why**: "Built-in" implies comparison to something else
**Action**: REMOVE or replace with operational statement

### 3. Manual Discovery Commands (Lines 275-276)
**Current**: `- uv run pflow registry describe...` and `- Avoid uv run pflow registry list...`
**Why**: CLI commands in MCP document
**Action**: DELETE entirely

### 4. All "MCP Advantage" Notes (4 locations)
**Locations:**
- Line 682-684: After MCP nested outputs
- Line 624-628: After workflow_validate
- Line 647-649: After workflow_execute
- Line 750-758: After workflow_save

**Why**: Comparison notes confuse agents
**Action**: REMOVE all, replace with operational guidance where needed

## Sections to Rewrite

### 1. Replace "MCP Advantage" with Operational Guidance

#### Location: After workflow_validate (Lines 624-628)
**Current** (WRONG):
```markdown
> **MCP Advantage**: You can validate workflow dicts without saving files:
> ```python
> workflow_validate(workflow={"nodes": [...], "edges": [...]})
> ```
> This enables faster iteration compared to file-based workflows.
```

**New** (CORRECT):
```markdown
**Workflow File Location:**
Write your workflow to `.pflow/workflows/workflow.json` before validating:
```python
# Write workflow to file first (using Write tool or similar)
workflow_validate(workflow=".pflow/workflows/workflow.json")
```
```

**Reasoning**:
- Agents on local machines should use paths
- No comparison to anything else
- Clear operational instruction

#### Location: After workflow_execute (Lines 647-649)
**Current** (WRONG):
```markdown
> **MCP Note**: All executions automatically save traces to
> `~/.pflow/debug/workflow-trace-*.json`. No flag needed (built-in behavior).
> Check the response for `trace_path` field with exact location.
```

**New** (CORRECT):
```markdown
**Trace Files:**
Workflow executions save trace files to `~/.pflow/debug/workflow-trace-*.json`.
Check the response for the `trace_path` field with the exact location.
```

**Reasoning**:
- States what happens, no "built-in" comparison
- No "no flag needed" (implies CLI comparison)
- Just operational facts

#### Location: After workflow_save (Lines 750-758)
**Current** (WRONG):
```markdown
> **MCP Response**: Returns structured data including execution hints:
> ```json
> {
>   "success": true,
>   "name": "workflow-name",
>   "message": "Run with:\n  workflow-name param1=<type> param2=<type>",
>   "path": "~/.pflow/workflows/workflow-name.json"
> }
> ```
```

**New** (CORRECT):
```markdown
**Response Structure:**
Returns structured data:
```json
{
  "success": true,
  "name": "workflow-name",
  "path": "~/.pflow/workflows/workflow-name.json",
  "message": "Run with: workflow-name param1=<type> param2=<type>"
}
```
```

**Reasoning**:
- No "MCP Response" label
- Just shows response structure
- Operational information

#### Location: After MCP nested outputs (Lines 682-684)
**Current** (WRONG):
```markdown
> **MCP Advantage**: Unlike CLI which requires inspecting trace files,
> `registry_run` with `show_structure=True` returns the complete structure
> directly in the response. No separate file reading needed.
```

**New** (CORRECT):
```markdown
**Structure Discovery:**
Using `show_structure=True` returns the complete output structure directly in the response.
```

**Reasoning**:
- No CLI comparison
- States what the parameter does
- Clean operational fact

### 2. Replace "Built-in Behaviors" Note (Line 37)

**Current** (WRONG):
```markdown
> **MCP Built-in Behaviors**: MCP never auto-repairs (built-in) • MCP always saves traces (built-in)
```

**New** (CORRECT):
```markdown
**Important**: Workflows are never auto-repaired. Traces are always saved to `~/.pflow/debug/`.
```

**Reasoning**:
- No "MCP" label (this IS the MCP doc)
- No "built-in" (no comparison)
- States operational facts

### 3. Remove "About MCP vs CLI" Section (Lines 6-30)

**Action**: DELETE entire section including:
- Command Syntax comparison
- Response Format comparison
- Built-in Defaults comparison
- Workflow Input comparison
- Parameter Passing comparison

**Reasoning**:
- Entire section is CLI contamination
- Confuses agents by introducing CLI concept
- Document should stand alone without comparisons

**After deletion, document should start directly with:**
```markdown
# pflow Agent Instructions

## 🎯 What I Can Help You With

**Important**: Workflows are never auto-repaired. Traces are always saved to `~/.pflow/debug/`.
```

### 4. Update All workflow_validate Examples

**Pattern**: Agents should write to file first, then validate by path

**Locations to update:**
- Anywhere showing `workflow_validate(workflow={"nodes": [...]})`

**New pattern:**
```python
# Write workflow to file
# (using Write tool or equivalent)

# Validate by path
workflow_validate(workflow=".pflow/workflows/workflow.json")
```

### 5. Update workflow_save Examples

**Current pattern** (mixed):
```python
workflow_save(workflow=".pflow/workflows/your-draft.json", name="workflow-name", ...)
```

**This is CORRECT** - no changes needed for workflow_save

**Reasoning**: workflow_save takes a path as input, which is correct

### 6. Clarify workflow_execute Usage

**Pattern**: Should use paths for local machine agents

**Examples should show:**
```python
workflow_execute(workflow=".pflow/workflows/workflow.json", parameters={...})
# OR
workflow_execute(workflow="saved-workflow-name", parameters={...})
```

**Should NOT show:**
```python
workflow_execute(workflow={"nodes": [...]}, parameters={...})
```

**Reasoning**: Agents on local machines use paths, not dicts

## Implementation Plan

### Phase 1: Remove CLI Contamination
1. Delete "About MCP vs CLI" section (lines 6-30)
2. Replace "Built-in Behaviors" note (line 37)
3. Delete manual discovery commands (lines 275-276)

### Phase 2: Remove Comparison Notes
1. Remove all "MCP Advantage" notes (4 locations)
2. Remove "MCP Note", "MCP Response" labels
3. Replace with operational guidance where needed

### Phase 3: Update Examples
1. Update workflow_validate examples to use paths
2. Ensure workflow_execute examples use paths or names
3. Keep workflow_save examples as-is (already use paths)

### Phase 4: Verify Consistency
1. Search for remaining "MCP" labels (except in tool names)
2. Search for "CLI" mentions
3. Search for "built-in" comparisons
4. Search for "advantage" mentions

## Key Decision: Dict vs Path

**CRITICAL CLARIFICATION NEEDED FROM USER:**
The user said:
> "the mcp tools that can take a workflow ir directly like workflow={"nodes": [...]} is ONLY to be used by agents operating in a sandbox environment"

**Question**: Should the document:
A) Remove ALL dict examples and only show path usage?
B) Keep dict examples but add note "Only use dicts in sandbox environments"?
C) Remove dicts entirely - assume all agents use local machine?

**My Interpretation**: Based on "agents operating in a cli (on the users local machine) they should use the path", I believe the answer is:
- **Remove all dict examples from main instructions**
- Document should assume local machine operation
- Always use paths: `.pflow/workflows/workflow.json`

## Verification Criteria

After changes:
- ✅ Zero mentions of "CLI" in document
- ✅ Zero mentions of "MCP Advantage", "MCP Note"
- ✅ Zero comparison notes ("built-in", "unlike X")
- ✅ All workflow_validate examples use paths
- ✅ All workflow_execute examples use paths or names
- ✅ Document stands alone without external context
- ✅ Clear operational guidance for local machine agents

## Search Patterns for Verification

```bash
# Should return ZERO matches:
grep -i "cli" file.md
grep "MCP Advantage\|MCP Note\|MCP Response" file.md
grep "built-in behavior\|Unlike CLI" file.md
grep "workflow={\"nodes\"" file.md  # Dict format in examples

# Should return matches (legitimate):
grep "mcp-" file.md  # Node type names like mcp-slack-fetch
grep "\.pflow/workflows/" file.md  # File paths
```

## Tone and Style

**OLD** (Comparative):
"MCP has this advantage..."
"Unlike CLI which requires..."
"Built-in by default..."

**NEW** (Operational):
"Write workflows to `.pflow/workflows/workflow.json`"
"Traces are saved to `~/.pflow/debug/`"
"Use `show_structure=True` to see output structure"

**Principle**: State facts, not comparisons. This is not a sales pitch.
