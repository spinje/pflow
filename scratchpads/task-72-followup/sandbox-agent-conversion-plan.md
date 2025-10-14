# Sandbox Agent Instructions Conversion Plan

## Goal
Create MCP_SANDBOX_AGENT_INSTRUCTIONS.md for agents in sandboxed environments (desktop apps, web services, browsers) where:
- NO filesystem access
- Work with dicts in memory
- Can't read trace files
- Can't set env vars for users
- Guide users to handle their own authentication

## Critical Changes Required

### 1. Header & Introduction ✅ (DONE)
**Already updated by user** - Changed pronouns from "I" to "You"

### 2. Workflow Operations - Dict Format (CRITICAL)

**Pattern**: Replace ALL file path references with dict format

**Old (Local Machine)**:
```python
# Write to file first
workflow_validate(workflow=".pflow/workflows/workflow.json")
workflow_execute(workflow=".pflow/workflows/workflow.json", parameters={...})
workflow_save(workflow=".pflow/workflows/workflow.json", name="...", description="...")
```

**New (Sandbox)**:
```python
# Build workflow dict in memory
workflow = {
    "nodes": [...],
    "edges": [...],
    "inputs": {...},
    "outputs": {...}
}

# Use dict directly
workflow_validate(workflow=workflow)
workflow_execute(workflow=workflow, parameters={...})
workflow_save(workflow=workflow, name="...", description="...")
```

**Locations to Update** (~20+ instances):
- Line 453: Build in phases test
- Line 583-588: VALIDATE section
- Line 604-609: TEST section
- Line 659-676: How to discover output structure
- Line 703-707: SAVE section
- Line 1310-1320: Execute workflow
- Line 1342-1347: Understanding template errors (trace file access)
- Line 1398-1402: Level 1 try it
- Line 1447-1451: Level 2 try it
- Line 1927-1946: Debugging playbook (trace file access)
- Line 2069-2077: Command cheat sheet
- Line 2205-2230: Complete example Steps 7-10

### 3. Remove Filesystem References (CRITICAL)

**Remove ALL mentions of**:
- `.pflow/workflows/` paths
- `~/.pflow/debug/` trace paths
- `~/.pflow/settings.json`
- `cat ~/.pflow/debug/workflow-trace-*.json | jq ...` commands
- File system access instructions

**Update to**:
- "Workflow objects in memory"
- "Traces are saved but not accessible to you"
- "Guide users to check their own trace files if needed"

### 4. Authentication Section (CRITICAL CHANGE)

**Old (Local Machine Agent)**:
```markdown
**When you discover a workflow needs credentials, help the user set them up:**

"To use it, set an environment variable:
  export SLACK_TOKEN="your-token-here"

The workflow will automatically read from this environment variable."
```

**New (Sandbox Agent)**:
```markdown
**When you discover a workflow needs credentials, guide the user:**

"This workflow needs a Slack token with chat:write permissions.

Here's how to get one:
1. Go to api.slack.com → Your App → OAuth Tokens
2. Copy the token

Since you're in a sandbox environment, I can't set environment variables for you.
Please set the token in your environment:
  export SLACK_TOKEN="your-token-here"

Then pass it as a workflow parameter:
  parameters={"slack_token": "your-token-value-here"}

Ready to continue?"
```

**Locations**:
- Line 922-935: Settings & credentials intro
- Line 970-984: Complete authentication flow
- Line 988-1010: Being proactive with authentication

### 5. Trace File Handling (CRITICAL)

**Old (Local Machine)**:
```python
# 1. Run workflow
workflow_execute(workflow=".pflow/workflows/workflow.json", parameters={})

# 2. Examine the trace file
cat ~/.pflow/debug/workflow-trace-*.json | jq '.nodes[0].outputs'
```

**New (Sandbox)**:
```python
# 1. Run workflow
workflow_execute(workflow=workflow_dict, parameters={})

# 2. Traces are saved by the system but not accessible to you
# Guide the user: "Check the trace_path in the response to inspect detailed execution logs"
# Or use show_structure=True when testing individual nodes to see output structure
```

**Locations**:
- Line 607-610: TEST section trace note
- Line 655-676: How to discover output structure
- Line 1320: Execute workflow note
- Line 1336-1347: Understanding template errors
- Line 1942-1946: Debugging playbook Step 2

### 6. Section: "Quick Fixes" Table (Line ~135)

**Update**:
```markdown
| `${var}` not found | Check error message for available fields | [Template Errors] |
```
(Remove "Check trace file at path in response" - sandbox agents can't access trace files)

### 7. Update Examples to Use Dicts

**All Learning Path Examples** (Lines 1365-1511):
- Level 1, 2, 3 examples should show dict format
- "Try it" sections should use dict format

**Complete Example** (Lines 2088-2253):
- Step 7: VALIDATE with dict
- Step 8: TEST with dict
- Step 10: SAVE with dict

### 8. Command Cheat Sheet (Line ~2060)

**Old**:
```python
workflow_validate(workflow=".pflow/workflows/workflow.json")
workflow_save(workflow=".pflow/workflows/workflow.json", name="...", description="...")
workflow_execute(workflow=".pflow/workflows/workflow.json", parameters={...})
```

**New**:
```python
# Work with dicts in memory
workflow_validate(workflow=workflow_dict)
workflow_save(workflow=workflow_dict, name="...", description="...")
workflow_execute(workflow=workflow_dict, parameters={...})
```

### 9. Reality vs Documentation Table (Line ~2367)

**Remove row**:
```markdown
| Test MCP nodes with `--show-structure` |
```
(No flag syntax, use parameter `show_structure=True`)

Already fixed in base document, should be fine.

### 10. Debugging Section Updates

**Line ~1322-1347: Understanding Template Errors**

**Old**:
```markdown
**2. Use the trace file for complete field list**:
```python
cat ~/.pflow/debug/workflow-trace-*.json | jq ...
```
```

**New**:
```markdown
**2. Guide user to check trace file**:
Traces are saved but not accessible in your sandbox environment.
Tell the user: "Please check the trace file at the path shown in the execution response for complete field details."

Or use `registry_run(node_type="...", show_structure=True)` to discover output structure.
```

## Implementation Priority

### Phase 1: Critical Operational Changes
1. ✅ Update header/intro (already done by user)
2. Update VALIDATE section (line 582-597) - dict format
3. Update TEST section (line 599-676) - dict format, remove trace access
4. Update SAVE section (line 696-726) - dict format
5. Update Execute Workflow (line 1307-1324) - dict format

### Phase 2: Authentication
6. Update Settings & Credentials intro (line 920-935)
7. Update Complete Authentication Flow (line 969-986)
8. Update Being Proactive (line 988-1010)

### Phase 3: Examples
9. Update Level 1-3 examples (lines 1365-1511)
10. Update Complete Example (lines 2088-2253)
11. Update Command Cheat Sheet (line 2060-2077)

### Phase 4: Cleanup
12. Update Quick Fixes table (line 133-141)
13. Update Understanding Template Errors (line 1322-1347)
14. Update Debugging Playbook (line 1919-1946)
15. Final verification - no filesystem paths remain

## Success Criteria

✅ Zero `.pflow/workflows/` references
✅ Zero `~/.pflow/debug/` references
✅ Zero `~/.pflow/settings.json` references
✅ Zero `cat ~/` or filesystem commands
✅ All workflow operations use dict format
✅ Authentication guides users (not agent sets env vars)
✅ Trace handling explains sandbox limitations
✅ All examples use dict format

## Estimated Changes

- ~25 file path references to convert
- ~8 trace file access instructions to update
- ~5 authentication guidance sections
- ~10 example code blocks
- Total: ~50 edits
