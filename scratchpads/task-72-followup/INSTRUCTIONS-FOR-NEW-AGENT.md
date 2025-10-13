# Instructions for Completing MCP-AGENT_INSTRUCTIONS.md Manual Updates

## Mission
Fix remaining inaccuracies and add MCP-specific enhancements to `.pflow/instructions/MCP-AGENT_INSTRUCTIONS.md`. The automated converter handled 90% - you're finishing the critical 10%.

## Core Principle
**NEVER mention CLI commands in this document.** This is an MCP-only guide. Any reference to `uv run pflow` or CLI-style commands is a bug.

---

## Part 1: Understanding MCP Tools (Read This First)

### Actual MCP Tool Signatures

These are the ONLY tools available via MCP. Reference this when fixing the document:

```python
# Discovery
workflow_discover(query: str) -> dict
registry_discover(query: str) -> dict

# Workflow Operations
workflow_execute(workflow: str | dict, parameters: dict = {}) -> dict
workflow_validate(workflow: str | dict) -> dict
workflow_save(
    workflow: str | dict,
    name: str,
    description: str,
    generate_metadata: bool = False,
    delete_draft: bool = False
) -> dict
workflow_list(filter: str = None) -> dict
workflow_describe(name: str) -> dict

# Registry Operations
registry_run(
    node_type: str,
    parameters: dict,
    show_structure: bool = False  # OPTIONAL parameter, defaults to false
) -> dict
registry_describe(node_types: list[str]) -> dict
registry_search(pattern: str) -> dict
registry_list() -> dict
```

### CRITICAL: No Settings Tools for Agents

**Settings tools (`settings_get`, `settings_set`) were disabled for MCP agents.**

Agents should instruct USERS to set environment variables directly:
```bash
# User sets environment variable
export SLACK_TOKEN="xoxb-..."
export GITHUB_TOKEN="ghp_..."
```

Then declare as workflow input:
```json
{
  "inputs": {
    "slack_token": {
      "type": "string",
      "required": true,
      "description": "Slack API token"
    }
  }
}
```

Workflow will automatically read from env var with same name.

### Key MCP Behaviors (Always True)

1. **Traces always saved** - No flag needed, automatic to `~/.pflow/debug/`
2. **No auto-repair** - Errors are always explicit, never auto-fixed
3. **JSON responses** - All tools return structured data
4. **Structure info** - `registry_run` can optionally show structure with `show_structure=True`

---

## Part 2: Critical Accuracy Fixes Needed

### Issue 1: CLI References in Checklists (HIGH PRIORITY)

**Problem**: Checklists still say "I've run `uv run pflow ...`"

**Locations** (search for these exact strings):
- Line ~757: "I've run `uv run pflow workflow discover`"
- Line ~762: "I've run `uv run pflow registry discover`"
- Line ~763: "I have node specs (from discovery output or `uv run pflow registry describe`)"

**Fix Pattern**:
```markdown
# WRONG (CLI reference)
- [ ] I've run `uv run pflow workflow discover "user's request"`

# CORRECT (MCP version)
- [ ] I've called `workflow_discover(query="user's request")`
```

**Action**: Search file for ALL instances of:
1. `` `uv run pflow` ``
2. `Run `uv run`
3. `run pflow`
4. Backtick-wrapped CLI commands in checklists

Replace with MCP function call syntax.

### Issue 2: Settings Management Instructions (CRITICAL)

**Problem**: Document mentions MCP settings tools that don't exist.

**Locations to Update**:

1. **Authentication section** (~line 949-990):
   - Currently says: `uv run pflow settings set-env KEY value`
   - Should explain: Users set environment variables directly (no MCP tool)

2. **Command Cheat Sheet** section:
   - Remove any `settings_set()` or `settings_get()` examples

3. **Being Proactive with Authentication** (~line 993-1014):
   - Currently shows: `uv run pflow settings set-env SLACK_TOKEN "your-token"`
   - Should show: `export SLACK_TOKEN="your-token"` (user command, not MCP)

**Replacement Pattern**:

```markdown
# WRONG (implies MCP tool exists)
```python
settings_set(key="SLACK_TOKEN", value="your-token")
```

# CORRECT (user sets env var)
```bash
# User runs in their terminal:
export SLACK_TOKEN="xoxb-your-token-here"
```

Then declare as workflow input to use it:
```json
{
  "inputs": {
    "slack_token": {
      "type": "string",
      "required": true,
      "description": "Slack API token (reads from SLACK_TOKEN env var)"
    }
  }
}
```
```

**Critical Auth Flow Update** (~line 985-990):

Replace this:
```markdown
**The Complete Authentication Flow:**
1. Store credential in settings: `uv run pflow settings set-env SERVICE_TOKEN "secret123"`
2. Declare as workflow input (required field)
3. Pass at runtime: `uv run pflow workflow.json api_token="$SERVICE_TOKEN"`
4. Or let it use environment variable with same name automatically
```

With this:
```markdown
**The Complete Authentication Flow:**
1. **User sets environment variable**: `export SERVICE_TOKEN="secret123"`
2. **Agent declares as workflow input** (required field):
   ```json
   {
     "inputs": {
       "service_token": {
         "type": "string",
         "required": true,
         "description": "API token for external service"
       }
     }
   }
   ```
3. **Workflow automatically reads from env var** with matching name (SERVICE_TOKEN)
4. **Or pass explicitly**: `workflow_execute(workflow="...", parameters={"service_token": "$SERVICE_TOKEN"})`
```

### Issue 3: Registry Run Parameters (MEDIUM PRIORITY)

**Problem**: Some sections incorrectly show `--show-structure` as a flag.

**Context**: `show_structure` is an OPTIONAL boolean parameter (defaults to False).

**Locations to Check**:
- Line ~1206: Example exploration flow
- Line ~1239-1250: Testing workflow examples
- Line ~1295: Binary data testing

**Wrong Patterns**:
```python
# WRONG (flag syntax)
registry_run(node_type="mcp-tool", parameters={...}) --show-structure

# WRONG (separate argument)
workflow_execute(workflow="registry", parameters={}) run mcp-tool --show-structure
```

**Correct Patterns**:
```python
# CORRECT (optional parameter)
registry_run(node_type="mcp-tool", parameters={...}, show_structure=True)

# CORRECT (default is False, so omit when not needed)
registry_run(node_type="mcp-tool", parameters={...})
```

**Action**: Search for ` --show-structure` and fix all instances.

### Issue 4: Workflow Execution References (LOW PRIORITY)

**Problem**: Some test examples show confusing syntax like:
```python
workflow_execute(workflow="slack-qa.json", parameters={"channel": "C123", "limit": "15"}) sheet_id=abc123xyz
```

This mixes MCP parameter dict with CLI-style positional args.

**Fix**: All parameters must be in the `parameters` dict:
```python
# CORRECT
workflow_execute(
    workflow="slack-qa.json",
    parameters={
        "channel": "C123",
        "limit": 15,  # Note: number not string
        "sheet_id": "abc123xyz"
    }
)
```

**Locations**: Search for `workflow_execute` and check parameter syntax.

---

## Part 3: MCP Advantage Notes (ENHANCEMENT)

Add these contextual notes to help agents understand MCP benefits:

### Location 1: After "CRITICAL: MCP Nodes Have Deeply Nested Outputs" (~line 657)

Add note:
```markdown
> **MCP Advantage**: Unlike CLI which requires inspecting trace files,
> `registry_run` with `show_structure=True` returns the complete structure
> directly in the response. No separate file reading needed.
```

### Location 2: After workflow_validate example (~line 621)

Add note:
```markdown
> **MCP Advantage**: You can validate workflow dicts without saving files:
> ```python
> workflow_validate(workflow={"nodes": [...], "edges": [...]})
> ```
> This enables faster iteration compared to file-based workflows.
```

### Location 3: After workflow_save examples (~line 734)

Add note:
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

### Location 4: After workflow_execute example (~line 638)

Add note:
```markdown
> **MCP Note**: All executions automatically save traces to
> `~/.pflow/debug/workflow-trace-*.json`. No flag needed (built-in behavior).
> Check the response for `trace_path` field with exact location.
```

---

## Part 4: Section-Specific Fixes

### Section: "Quick Fixes" Table (~line 169)

**Current** (row 1):
```markdown
| `${var}` not found | `--trace` flag → check trace file | ... |
```

**Fix to**:
```markdown
| `${var}` not found | Check trace file at path in response | ... |
```

**Current** (row 3):
```markdown
| Output is `Any` | `registry run NODE --show-structure` | ... |
```

**Fix to**:
```markdown
| Output is `Any` | `registry_run(node_type="NODE", show_structure=True)` | ... |
```

### Section: "Common Validation Errors" Table (~line 1343)

**Current** (row 1):
```markdown
| "Unknown node type 'X'" | Run `uv run pflow registry discover "task that needs X"` |
```

**Fix to**:
```markdown
| "Unknown node type 'X'" | Call `registry_discover(query="task that needs X")` |
```

**Current** (row 5):
```markdown
| "Missing required parameter 'Y'" | Check node interface with `uv run pflow registry describe Z` |
```

**Fix to**:
```markdown
| "Missing required parameter 'Y'" | Call `registry_describe(node_types=["Z"])` |
```

### Section: "Execute Workflow" (~line 1307-1310)

**Remove these lines entirely**:
```python
workflow_execute(workflow="--no-repair", parameters={}) --trace workflow.json param1=value param2=value
```
```
> Using --no-repair --trace flags is mandatory when building workflows for AI agents.
```

**Replace with**:
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

### Section: "Level 1-3 Examples" (~line 1386, 1429, 1675)

**Remove these lines**:
```markdown
**Try it**: `uv run pflow level1.json question="What is 2+2?"`
**Try it**: `uv run pflow level2.json file_path="README.md"`
```

**Replace with**:
```markdown
**Try it**:
```python
workflow_execute(
    workflow="level1.json",
    parameters={"question": "What is 2+2?"}
)
```

**Try it**:
```python
workflow_execute(
    workflow="level2.json",
    parameters={"file_path": "README.md"}
)
```

### Section: "Common Mistakes" (~line 1838, 1841)

**Current** (Mistake 1 & 2):
```markdown
### ❌ Mistake 1: Skipping Workflow Discovery
**Fix**: ALWAYS run `uv run pflow workflow discover` first (Step 2)

### ❌ Mistake 2: Not Checking Node Output Structure
**Fix**: Run `uv run pflow registry describe node-type` BEFORE writing templates
```

**Fix to**:
```markdown
### ❌ Mistake 1: Skipping Workflow Discovery
**Fix**: ALWAYS call `workflow_discover(query="...")` first (Step 2)

### ❌ Mistake 2: Not Checking Node Output Structure
**Fix**: Call `registry_describe(node_types=["node-type"])` BEFORE writing templates
```

---

## Part 5: Verification Checklist

After making all changes, verify:

### Automated Checks

```bash
# 1. No CLI references remain
grep -n "uv run pflow" .pflow/instructions/MCP-AGENT_INSTRUCTIONS.md
# Expected: NO matches

# 2. No flag syntax remains
grep -n " --" .pflow/instructions/MCP-AGENT_INSTRUCTIONS.md | grep -v "^#" | grep -v "http"
# Expected: Only comment lines or URLs

# 3. Settings tools not mentioned as MCP calls
grep -n "settings_set(" .pflow/instructions/MCP-AGENT_INSTRUCTIONS.md
grep -n "settings_get(" .pflow/instructions/MCP-AGENT_INSTRUCTIONS.md
# Expected: NO matches

# 4. Export commands for env vars present
grep -n "export " .pflow/instructions/MCP-AGENT_INSTRUCTIONS.md
# Expected: Multiple matches showing user-side env var setting
```

### Manual Spot Checks

1. **Line ~37**: Built-in behaviors note present?
2. **Line ~620**: workflow_validate has advantage note?
3. **Line ~730**: workflow_save has response structure example?
4. **Line ~757-775**: All checklist items use MCP syntax?
5. **Line ~949-1014**: Authentication section explains env vars (no settings tools)?
6. **Line ~1206**: registry_run uses `show_structure=True` parameter?
7. **Line ~1343**: Validation errors table uses MCP calls?
8. **Line ~1386, 1429**: Example "Try it" sections use workflow_execute()?

### Content Accuracy Checks

For each MCP tool mentioned, verify:
- ✅ Signature matches Part 1 reference
- ✅ Parameters are correct (not CLI flags)
- ✅ Optional parameters shown as Python defaults
- ✅ Examples show actual JSON response structures

---

## Part 6: High-Risk Areas (Double Check These)

### 1. Authentication & Settings (~line 936-1014)

**Why risky**: Settings tools were removed late in development. Original CLI version had `pflow settings` commands.

**What to check**:
- No `settings_set()` or `settings_get()` MCP calls
- Clear instructions for users to set env vars
- Workflow input declaration pattern correct

### 2. Testing & Debugging Section (~line 1216-1340)

**Why risky**: Mix of registry_run calls, trace file references, flag syntax.

**What to check**:
- `show_structure=True` (not `--show-structure`)
- Trace file access explained correctly
- No CLI testing commands

### 3. Checklists Throughout

**Why risky**: Easy to miss CLI syntax in checkbox items.

**What to check**:
- Search every `- [ ]` line
- Verify no backtick-wrapped CLI commands
- MCP function call syntax used

### 4. Complete Example Section (~line 2069-2213)

**Why risky**: Step-by-step example with many command invocations.

**What to check**:
- Every step uses MCP tools
- Parameter syntax correct throughout
- "Try it" examples use workflow_execute()

---

## Part 7: Style Guide for Additions

When adding MCP advantage notes:

### Good Examples

```markdown
> **MCP Advantage**: [One clear benefit in 1-2 sentences]

> **MCP Note**: [Clarifying detail about MCP-specific behavior]

> **MCP Response**: Returns structured data:
> ```json
> {"field": "example"}
> ```
```

### Bad Examples (Avoid)

```markdown
<!-- Too vague -->
> MCP is better here

<!-- Compares to CLI (wrong - never mention CLI) -->
> Unlike CLI which requires flags, MCP just works

<!-- Too verbose -->
> MCP provides a really great advantage here because of the way
> it handles responses which is different from other approaches...
```

---

## Part 8: Final Quality Check

Before marking complete:

1. **Read sections 2, 3, 7, 8** (most critical user-facing sections)
   - Do they make sense without CLI knowledge?
   - Are MCP tool calls accurate?
   - Is auth flow clear?

2. **Scan for "TODO" or conversion artifacts**
   ```bash
   grep -i "todo" .pflow/instructions/MCP-AGENT_INSTRUCTIONS.md
   grep "# WRONG" .pflow/instructions/MCP-AGENT_INSTRUCTIONS.md
   ```

3. **Verify no broken examples**
   - Every Python code block is valid syntax
   - Every JSON example is valid JSON
   - Parameters match tool signatures

4. **Check consistency**
   - All workflow_execute calls use same parameter format
   - All registry_run calls use same pattern
   - Terminology consistent (don't mix "call" and "run" and "execute")

---

## Success Criteria

You're done when:

1. ✅ Zero matches for `grep "uv run pflow"`
2. ✅ Zero references to settings MCP tools
3. ✅ All checklists use MCP syntax
4. ✅ Authentication section explains user env vars
5. ✅ Flag syntax removed (`--show-structure` → `show_structure=True`)
6. ✅ 3-5 MCP advantage notes added
7. ✅ All automated checks pass
8. ✅ Manual spot checks pass

---

## Estimated Time

- Part 2 fixes (accuracy): 3-4 hours
- Part 3 additions (advantages): 1-2 hours
- Part 4 section fixes: 2-3 hours
- Part 5 verification: 1 hour

**Total: 7-10 hours** (matches original estimate)

---

## Questions to Ask If Stuck

1. **"Does this tool exist in the MCP server?"**
   - Check Part 1 reference list
   - If not there, it doesn't exist for agents

2. **"Is this a parameter or a flag?"**
   - MCP uses Python: `param=value`
   - Never uses shell flags: `--param`

3. **"Should I mention CLI here?"**
   - NO. Never. This is MCP-only documentation.

4. **"How do users set credentials?"**
   - Users set env vars: `export TOKEN="..."`
   - Workflows declare inputs, read from env
   - No MCP settings tools for agents

Good luck! You've got this. 🚀
