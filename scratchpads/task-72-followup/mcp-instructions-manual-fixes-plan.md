# MCP-AGENT_INSTRUCTIONS.md Manual Fixes - Ultrathinking Plan

## Mission Summary
Fix remaining inaccuracies and add MCP-specific enhancements after automated conversion completed 90% of the work. This document plans the systematic completion of the critical 10%.

## Scope Analysis

### Found Issues (via grep)

**CLI References Found: 17 instances**
- Line 11: Example comparison (OK - shows CLI vs MCP difference)
- Line 275-276: Manual discovery commands (NEED FIX)
- Line 491: Test command in phase building (NEED FIX)
- Line 757: Checklist item (CRITICAL FIX)
- Line 762: Checklist item (CRITICAL FIX)
- Line 763: Checklist item (CRITICAL FIX)
- Line 898: Rule statement (NEED FIX)
- Line 949: Settings management (CRITICAL FIX - section update)
- Line 986: Authentication flow (CRITICAL FIX - section update)
- Line 988: Authentication flow (CRITICAL FIX - section update)
- Line 1005: Authentication proactive (CRITICAL FIX - section update)
- Line 1343: Validation error table (NEED FIX)
- Line 1347: Validation error table (NEED FIX)
- Line 1386: Level 1 example (NEED FIX)
- Line 1429: Level 2 example (NEED FIX)
- Line 1838: Common mistakes (NEED FIX)
- Line 1841: Common mistakes (NEED FIX)

**Flag Syntax Found:**
- Line 171: Quick fixes table `--show-structure`
- Line 657: MCP outputs note `--show-structure`
- Line 670: Test with `--show-structure`
- Line 1210: registry_run with `--show-structure`
- Line 1238-1249: Testing workflow section
- Line 1307-1310: Execute workflow with `--no-repair --trace`

**Settings Tools: 0 instances found** ✓ (Good, but sections still need updating)

## Systematic Fixes Plan

### Phase 1: Critical Accuracy Fixes (MUST FIX)

#### 1.1 Pre-Build Checklist (Lines 757-775) - HIGH PRIORITY
**Current State:**
```markdown
- [ ] I've run `uv run pflow workflow discover "user's request"`
- [ ] I've run `uv run pflow registry discover "specific task description"`
- [ ] I have node specs (from discovery output or `uv run pflow registry describe`)
```

**Fixed State:**
```markdown
- [ ] I've called `workflow_discover(query="user's request")`
- [ ] I've called `registry_discover(query="specific task description")`
- [ ] I have node specs (from discovery output or `registry_describe(node_types=["node-type"])`)
```

**Impact:** Critical - these are checklists agents follow

#### 1.2 Authentication & Settings Section (Lines 949-1014) - CRITICAL
**Problem:** Implies MCP settings tools exist when they don't

**Current problematic lines:**
- Line 949: `**Manage**: uv run pflow settings set-env KEY value`
- Line 986-989: Complete authentication flow with CLI commands
- Line 1005: Proactive auth example with CLI

**Required Changes:**
1. Remove all `uv run pflow settings` references
2. Replace with user-side `export` commands
3. Explain workflow input declaration pattern
4. Update complete authentication flow (lines 985-990)
5. Update proactive authentication section (lines 993-1014)

**New Pattern:**
```markdown
**User sets environment variable:**
```bash
export SERVICE_TOKEN="secret123"
```

**Agent declares as workflow input:**
```json
{
  "inputs": {
    "service_token": {
      "type": "string",
      "required": true,
      "description": "API token"
    }
  }
}
```
```

#### 1.3 Common Mistakes Section (Lines 1838, 1841)
**Current:**
- `ALWAYS run uv run pflow workflow discover`
- `Run uv run pflow registry describe`

**Fixed:**
- `ALWAYS call workflow_discover(query="...")`
- `Call registry_describe(node_types=["node-type"])`

#### 1.4 Quick Fixes Table (Line ~169)
**Row 1:** `` `--trace` flag → check trace file ``
→ Fix: `Check trace file at path in response`

**Row 3:** `` `registry run NODE --show-structure` ``
→ Fix: `registry_run(node_type="NODE", show_structure=True)`

#### 1.5 Common Validation Errors Table (Line ~1343)
**Row 1:** ``Run `uv run pflow registry discover "task that needs X"` ``
→ Fix: `Call registry_discover(query="task that needs X")`

**Row 5:** ``Check node interface with `uv run pflow registry describe Z` ``
→ Fix: `Call registry_describe(node_types=["Z"])`

### Phase 2: Registry Run Parameter Fixes (MEDIUM PRIORITY)

#### 2.1 Flag Syntax → Parameter Syntax
**Pattern to find and fix:**
- `--show-structure` flag → `show_structure=True` parameter
- `--trace` flag → (remove - built-in)
- `--no-repair` flag → (remove - built-in)

**Locations:**
- Line 171: Quick fixes table
- Line 1210: Meta-discovery example
- Line 1238-1249: Smart testing workflow section
- Line 1307-1310: Execute workflow section

**Example Fix:**
```python
# WRONG
registry_run(node_type="mcp-tool", parameters={}) --show-structure

# CORRECT
registry_run(node_type="mcp-tool", parameters={}, show_structure=True)
```

#### 2.2 Mixed Parameter Syntax in workflow_execute
**Line 1210:**
```python
# WRONG
registry_run(...) data='{"name":"test"}' --show-structure

# CORRECT
registry_run(node_type="...", parameters={"table": "users", "data": {"name": "test"}}, show_structure=True)
```

**Line 1241-1242:**
```python
# WRONG
workflow_execute(workflow="registry", parameters={}) run mcp-service-TOOL_NAME param1="value1" --show-structure

# CORRECT (Note: This looks wrong - needs clarification on what they meant)
registry_run(node_type="mcp-service-TOOL_NAME", parameters={"param1": "value1"}, show_structure=True)
```

**Line 1307:**
```python
# WRONG
workflow_execute(workflow="--no-repair", parameters={}) --trace workflow.json param1=value

# CORRECT
workflow_execute(workflow="workflow.json", parameters={"param1": "value", "param2": "value"})
```

### Phase 3: Level Examples (LOW PRIORITY)

#### 3.1 Level 1 Example (Line ~1386)
**Remove:**
```markdown
**Try it**: `uv run pflow level1.json question="What is 2+2?"`
```

**Replace with:**
```markdown
**Try it**:
```python
workflow_execute(
    workflow="level1.json",
    parameters={"question": "What is 2+2?"}
)
```
```

#### 3.2 Level 2 Example (Line ~1429)
**Remove:**
```markdown
**Try it**: `uv run pflow level2.json file_path="README.md"`
```

**Replace with:**
```markdown
**Try it**:
```python
workflow_execute(
    workflow="level2.json",
    parameters={"file_path": "README.md"}
)
```
```

### Phase 4: MCP Advantage Notes (ENHANCEMENT)

#### 4.1 After "CRITICAL: MCP Nodes Have Deeply Nested Outputs" (~line 657)
**Add:**
```markdown
> **MCP Advantage**: Unlike CLI which requires inspecting trace files,
> `registry_run` with `show_structure=True` returns the complete structure
> directly in the response. No separate file reading needed.
```

#### 4.2 After workflow_validate example (~line 621)
**Add:**
```markdown
> **MCP Advantage**: You can validate workflow dicts without saving files:
> ```python
> workflow_validate(workflow={"nodes": [...], "edges": [...]})
> ```
> This enables faster iteration compared to file-based workflows.
```

#### 4.3 After workflow_save examples (~line 734)
**Add:**
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

#### 4.4 After workflow_execute example (~line 638)
**Add:**
```markdown
> **MCP Note**: All executions automatically save traces to
> `~/.pflow/debug/workflow-trace-*.json`. No flag needed (built-in behavior).
> Check the response for `trace_path` field with exact location.
```

### Phase 5: Subtle Fixes

#### 5.1 Execute Workflow Section (Lines 1307-1310)
**Remove entire block:**
```python
workflow_execute(workflow="--no-repair", parameters={}) --trace workflow.json param1=value param2=value
```
```
> Using --no-repair --trace flags is mandatory when building workflows for AI agents.
```

**Replace with:**
```python
# Execute workflow (traces always saved, repair always disabled)
workflow_execute(
    workflow="workflow.json",
    parameters={
        "param1": "value",
        "param2": "value"
    }
)
```
```
> **Note**: MCP automatically saves traces and disables auto-repair (built-in behaviors).
> Check response for `trace_path` field with exact location.
```

#### 5.2 Testing Workflow Section (Lines 1238-1250)
**Fix mixed syntax on lines 1241-1242:**
```python
# WRONG
workflow_execute(workflow="registry", parameters={}) run mcp-service-TOOL_NAME \
  param1="value1" --show-structure

# CORRECT
registry_run(
    node_type="mcp-service-TOOL_NAME",
    parameters={"param1": "value1"},
    show_structure=True
)
```

**Fix line 1245-1249:**
```python
# WRONG
workflow_execute(workflow="registry", parameters={}) run http \
  url="https://api.example.com/endpoint" \
  method="POST" \
  headers='{"Authorization": "Bearer test"}' \
  --show-structure

# CORRECT
registry_run(
    node_type="http",
    parameters={
        "url": "https://api.example.com/endpoint",
        "method": "POST",
        "headers": {"Authorization": "Bearer test"}
    },
    show_structure=True
)
```

#### 5.3 Other Remaining CLI References
**Line 275-276:** Document discovery commands
- Keep as-is with note "Only use manual commands if AI discovery is unavailable"
- These are marked as fallback, acceptable

**Line 491:** Build in phases test command
- Change to MCP: `workflow_execute(workflow="workflow.json", parameters={})`

**Line 898:** Rule statement
- Change to: `**Rule**: ALWAYS call registry_describe(node_types=["node-type"]) before writing templates.`

## Verification Strategy

### Automated Checks
```bash
# 1. No CLI references remain (except in About MCP vs CLI section)
grep -n "uv run pflow" .pflow/instructions/MCP-AGENT_INSTRUCTIONS.md | grep -v "^11:" | grep -v "^275:" | grep -v "^276:"
# Expected: NO matches (except lines 11, 275-276 which are acceptable)

# 2. No flag syntax remains (except in curl commands and URLs)
grep -n " --" .pflow/instructions/MCP-AGENT_INSTRUCTIONS.md | grep -v "^#" | grep -v "http" | grep -v "curl" | grep -v "data-binary"
# Expected: Only comment lines or URLs or curl commands

# 3. Settings tools not mentioned as MCP calls
grep -n "settings_set(" .pflow/instructions/MCP-AGENT_INSTRUCTIONS.md
grep -n "settings_get(" .pflow/instructions/MCP-AGENT_INSTRUCTIONS.md
# Expected: NO matches

# 4. Export commands for env vars present
grep -n "export " .pflow/instructions/MCP-AGENT_INSTRUCTIONS.md
# Expected: Multiple matches in auth sections
```

### Manual Spot Checks
1. Line ~37: Built-in behaviors note present?
2. Line ~620: workflow_validate has advantage note?
3. Line ~730: workflow_save has response structure example?
4. Line ~757-775: All checklist items use MCP syntax?
5. Line ~949-1014: Authentication section explains env vars (no settings tools)?
6. Line ~1206: registry_run uses `show_structure=True` parameter?
7. Line ~1343: Validation errors table uses MCP calls?
8. Line ~1386, 1429: Example "Try it" sections use workflow_execute()?

## Implementation Order

1. **Phase 1: Critical Accuracy Fixes** (60 minutes)
   - Authentication sections (biggest change)
   - Checklists
   - Common mistakes
   - Validation tables
   - Quick fixes table

2. **Phase 2: Registry Run Parameter Fixes** (30 minutes)
   - Flag syntax throughout
   - Mixed parameter syntax

3. **Phase 3: Level Examples** (15 minutes)
   - Try it sections

4. **Phase 4: MCP Advantage Notes** (20 minutes)
   - Add 4 enhancement notes

5. **Phase 5: Verification** (15 minutes)
   - Run automated checks
   - Manual spot checks

**Total Estimated Time: 2h 20min**

## Critical Warnings

⚠️ **Lines 11, 275-276**: These contain CLI references but are INTENTIONAL
- Line 11: Comparison showing CLI vs MCP difference
- Lines 275-276: Marked as fallback manual commands
- DO NOT change these

⚠️ **curl commands**: Keep `--header`, `--data-binary` flags
- These are shell command flags, not pflow flags
- Part of shell node examples

⚠️ **About MCP vs CLI section** (lines 6-30): Keep as-is
- This section explains the difference
- Legitimate place for CLI examples

## Success Criteria

✅ All checklist items use MCP function call syntax
✅ Authentication section shows user env vars + workflow input pattern
✅ No settings MCP tools mentioned
✅ All `--show-structure` → `show_structure=True`
✅ All `--trace`, `--no-repair` removed (built-in)
✅ Example "Try it" sections use workflow_execute()
✅ 4 MCP advantage notes added
✅ All automated checks pass
✅ Manual spot checks pass

## Notes for Implementation

- Work line-by-line through each phase
- Use Edit tool for precise replacements
- Mark each todo as complete immediately after finishing
- Run verification checks after Phase 5
- Document any ambiguities or questions for user
