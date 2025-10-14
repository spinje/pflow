# MCP Instructions Update Plan

## Verified MCP Tool Definitions (11 Production Tools)

Based on actual implementation in `src/pflow/mcp_server/tools/`:

### Discovery Tools (2)
1. **`workflow_discover(query: str)`**
   - Finds existing workflows
   - Returns: Markdown with confidence scores

2. **`registry_discover(task: str)`**
   - Finds nodes for building
   - Returns: Markdown planning context with node specs

### Execution Tools (4)
3. **`workflow_execute(workflow: str | dict, parameters: dict | None = None)`**
   - workflow: name, path, or inline IR dict
   - parameters: optional, defaults to None
   - Built-in: no repair, traces saved, auto-normalization
   - Returns: Formatted text (not JSON)

4. **`workflow_validate(workflow: str | dict)`**
   - workflow: name, path, or inline IR dict
   - No parameters needed
   - Returns: Formatted text (not JSON)

5. **`workflow_save(workflow: str | dict, name: str, description: str, force: bool = False, generate_metadata: bool = False)`**
   - workflow: path or inline IR dict
   - force: optional, defaults to False
   - generate_metadata: optional, defaults to False
   - Returns: Formatted text with execution hint

6. **`registry_run(node_type: str, parameters: dict | None = None)`**
   - node_type: exact registry identifier
   - parameters: optional, defaults to None
   - Built-in: ALWAYS shows structure (no flag needed!)
   - Returns: Formatted text with template paths

### Registry Tools (3)
7. **`registry_describe(nodes: list[str])`**
   - nodes: array of node type identifiers
   - Returns: Markdown with complete specs

8. **`registry_search(pattern: str)`**
   - pattern: search keyword
   - Returns: Markdown table

9. **`registry_list()`**
   - No parameters
   - Returns: Markdown grouped by package

### Workflow Tools (2)
10. **`workflow_list(filter_pattern: str | None = None)`**
    - filter_pattern: optional substring filter
    - Returns: Markdown table

11. **`workflow_describe(name: str)`**
    - name: workflow identifier
    - Returns: Markdown with interface details

### Disabled Tools (NOT available)
- ❌ `settings_get`, `settings_set`, `settings_show`, `settings_list_env` - DISABLED
- ❌ All test tools - DISABLED

## Issues Found in Current MCP-AGENT_INSTRUCTIONS.md

### Category 1: CLI Command References (HIGH PRIORITY)
**Lines with "uv run pflow" that need conversion:**

1. Line 169: `${var}` not found → `--trace` flag
2. Line 171: `registry run NODE --show-structure`
3. Line 173: `registry run NODE params`
4. Line 275: "uv run pflow registry describe node1 node2"
5. Line 276: "uv run pflow registry list"
6. Line 491: "Test": `uv run pflow workflow.json`
7. Line 757: Checklist: `uv run pflow workflow discover`
8. Line 762: Checklist: `uv run pflow registry discover`
9. Line 763: Checklist: `uv run pflow registry describe`
10. Line 898: Rule: `uv run pflow registry describe node-type`
11. Line 949: Manage: `uv run pflow settings set-env KEY value`
12. Line 986: Auth flow: `uv run pflow settings set-env SERVICE_TOKEN`
13. Line 988: Auth flow: `uv run pflow workflow.json api_token=`
14. Line 1005: Auth example: `uv run pflow settings set-env SLACK_TOKEN`
15. Line 1343: Validation error table: `uv run pflow registry discover`
16. Line 1347: Validation error table: `uv run pflow registry describe Z`
17. Line 1386: Try it: `uv run pflow level1.json`
18. Line 1429: Try it: `uv run pflow level2.json`
19. Line 1838: Mistake 1: `uv run pflow workflow discover`
20. Line 1841: Mistake 2: `uv run pflow registry describe`

### Category 2: Incorrect Parameters (HIGH PRIORITY)

1. Line 171: `--show-structure` flag (doesn't exist for MCP)
   - **FIX**: `registry_run` ALWAYS shows structure (built-in)

2. Line 173: "registry run NODE params" (wrong syntax)
   - **FIX**: `registry_run(node_type="NODE", parameters={"key": "value"})`

3. Line 657: `--show-structure` mentioned as optional
   - **FIX**: Remove this - it's always built-in behavior

4. Line 671: `registry_run(..., show_structure=True)`
   - **FIX**: Remove `show_structure` parameter (doesn't exist)

5. Line 1241-1249: Multiple instances of command syntax that looks wrong
   - **FIX**: Need to review and correct

### Category 3: Settings Tool References (MEDIUM PRIORITY)

Settings tools are DISABLED - all references need removal or clarification:

1. Line 949: `settings set-env` command
2. Line 986-989: Complete authentication flow using settings
3. Line 1005: Settings example
4. Lines 937-950: Entire "Authentication & Credentials" section mentions settings

**Decision needed**:
- Option A: Remove all settings references (users must use env vars directly)
- Option B: Clarify that settings are handled via environment variables (no MCP tool)

### Category 4: Missing MCP Advantages (LOW PRIORITY)

Add notes explaining MCP-specific behaviors:

1. **After `workflow_discover`** (line ~224):
   - "Returns markdown with confidence scores and reasoning"
   - "No need to parse - structured format for easy reading"

2. **After `registry_discover`** (line ~263):
   - "Returns complete planning context in markdown"
   - "Includes all interface specs needed for building"

3. **After `workflow_execute`** (line ~638):
   - "Built-in behaviors: no auto-repair, traces always saved, auto-normalization"
   - "Returns formatted text that's easy to read and parse"

4. **After `workflow_validate`** (line ~621):
   - "Can validate inline workflow dicts without saving to files first"

5. **After `registry_run`** (line ~392):
   - "Always includes complete output structure with template paths"
   - "No need to specify flags - structure display is built-in"

6. **After `workflow_save`** (line ~730):
   - "Returns formatted message with execution hint showing parameter types"

### Category 5: Minor Inconsistencies (LOW PRIORITY)

1. Line 37: Flag note mentions 2 flags but should clarify what they mean
2. Line 2334: `--show-structure` in Reality table
3. Lines 553-556: Mentions `--no-repair --trace` as "mandatory"
4. Line 1310: Mentions `--no-repair --trace` flags again

## Implementation Plan

### Phase 1: Critical CLI Reference Fixes (1.5 hours)
- Convert all `uv run pflow` commands to MCP tool calls
- Update all checklists
- Update validation error solutions
- Update "Common Mistakes" section
- Update "When Stuck" table

### Phase 2: Parameter Accuracy (1 hour)
- Remove all `--show-structure` references
- Add note that `registry_run` ALWAYS shows structure
- Fix parameter syntax in all examples
- Verify optional vs required parameters

### Phase 3: Settings Clarification (30 min)
- Decide on approach (remove vs clarify)
- Update "Authentication & Credentials" section
- Update auth flow examples
- Clarify environment variable usage

### Phase 4: MCP Advantages (1 hour)
- Add advantage notes after key tool explanations
- Explain built-in behaviors clearly
- Highlight differences from CLI

### Phase 5: Final Cleanup (30 min)
- Search for "uv run pflow" - should be zero
- Search for "CLI" - should only be in intro
- Search for "--" - should be zero
- Verify tool count (11, not 13)
- Final read-through

**Total Estimated Time: 4.5 hours**

## Verification Checklist

After updates:
- [ ] Zero instances of "uv run pflow" (except in intro comparison)
- [ ] Zero instances of "--flag" syntax
- [ ] All tool names match actual implementation
- [ ] All parameters match actual signatures
- [ ] Settings tools marked as unavailable or removed
- [ ] Tool count is 11 (not 13)
- [ ] MCP advantages clearly explained
- [ ] Only MCP syntax used throughout

## Key Decision Points

1. **Settings handling** - How to explain auth without MCP settings tools?
   - Recommendation: Clarify users should set env vars directly, MCP reads from environment

2. **Inline workflow validation** - Emphasize this MCP advantage?
   - Recommendation: Yes - this is a major benefit (iterate without file I/O)

3. **Structure display** - How strongly emphasize it's always built-in?
   - Recommendation: Add clear note in multiple places - this solves major CLI pain point

4. **Trace saving** - How to explain it's automatic?
   - Recommendation: Add to "Built-in Behaviors" section near top
