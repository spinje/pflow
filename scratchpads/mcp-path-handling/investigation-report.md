# MCP Path Handling Investigation & Options Analysis

## Investigation Summary

### Current State: What We Support

The MCP server's `workflow_validate`, `workflow_execute`, and `workflow_save` tools currently support **three input formats**:

1. **Workflow Name**: `"my-workflow"` → Resolves to `~/.pflow/workflows/my-workflow.json`
2. **File Path** (absolute or relative): `"./draft.json"` or `"/tmp/workflow.json"`
3. **Inline IR**: `{"nodes": [...], "edges": [...]}` → Used directly

**Key Implementation Details**:

- **Resolution Logic**: `src/pflow/mcp_server/utils/resolver.py:18-76`
  - Priority order: Library name → File path → Error with suggestions
  - Relative paths resolve from **MCP server's CWD** (not repo root)
  - No path validation performed (trusted local environment assumption)

- **Working Directory Context**:
  - Development: CWD = `/Users/andfal/projects/pflow` (repo root)
  - Installed: CWD = wherever agent launches from (typically `~`)
  - Claude Desktop: CWD = `~` (user home directory)

- **Storage Locations**:
  ```
  ~/.pflow/
  ├── workflows/        # Global library (WorkflowManager)
  ├── debug/            # Execution traces (auto-saved)
  ├── nodes/            # Custom node modules
  ├── settings.json     # Settings + API keys
  ├── registry.json     # Node registry cache
  └── mcp-servers.json  # MCP server configs
  ```
  **Missing**: No `temp/` or `drafts/` directory

---

## Current Limitations

### 1. No Temporary Workflow Storage
**Problem**: AI agents iterating on workflows must either:
- Use inline IR (ephemeral, lost between iterations)
- Save to global library (pollutes namespace with drafts)
- Write to arbitrary file paths (no centralized management)

**Example Pain Point**:
```python
# Agent iterating on workflow (3 attempts):
workflow_save({"nodes": [...]}, "test-draft-v1", ...)  # ❌ Clutters library
workflow_save({"nodes": [...]}, "test-draft-v2", ...)  # ❌ More clutter
workflow_save({"nodes": [...]}, "test-final", ...)     # ✅ Final version

# Library now has 3 workflows instead of 1
```

### 2. Path Context Ambiguity
**Problem**: Relative paths resolve differently based on how MCP server was launched.

| Launch Method | CWD | `"./draft.json"` Resolves To |
|--------------|-----|------------------------------|
| Dev (repo) | `/Users/andfal/projects/pflow/` | `<repo>/draft.json` |
| Installed (project) | `/Users/user/my-project/` | `<project>/draft.json` |
| Claude Desktop | `/Users/user/` | `~/draft.json` |

**Risk**: Workflows with relative paths break when MCP server launch context changes.

### 3. No Auto-Cleanup
**Problem**: No mechanism to clean up abandoned drafts or temporary workflows.

---

## Options for Adding Temp Directory Support

### Option 1: Add `~/.pflow/temp-workflows/` Directory

**Concept**: New standardized temp storage location for draft/iterative workflows.

**Implementation**:

```python
# New directory structure:
~/.pflow/
├── workflows/           # Final/published workflows
├── temp-workflows/      # Draft/temporary workflows (new!)
│   ├── agent-session-123-draft-1.json
│   ├── agent-session-123-draft-2.json
│   └── user-experiment.json
├── debug/
├── nodes/
└── ...

# Resolution order update:
# 1. Library name → ~/.pflow/workflows/
# 2. Temp name → ~/.pflow/temp-workflows/  (NEW)
# 3. File path → resolve from CWD
# 4. Inline IR → use directly
```

**Advantages**:
- ✅ Consistent location across dev/installed (always `~/.pflow/temp-workflows/`)
- ✅ Separates drafts from final workflows
- ✅ Enables auto-cleanup policies (e.g., delete files >7 days old)
- ✅ Works identically in development and installed scenarios
- ✅ No CWD ambiguity (always absolute path)

**Disadvantages**:
- ⚠️ Adds complexity to resolution logic (3-tier: library → temp → file)
- ⚠️ Need naming convention to distinguish temp workflows
- ⚠️ Need cleanup mechanism (when/how to delete?)

**Resolution Logic Changes**:
```python
def resolve_workflow(workflow: str | dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, str]:
    # 1. If dict → inline IR
    if isinstance(workflow, dict):
        return workflow, None, "direct"

    # 2. Try as saved workflow name
    manager = WorkflowManager()
    if manager.exists(workflow):
        return manager.load_ir(workflow), None, "library"

    # 3. Try as temp workflow name (NEW)
    temp_manager = TempWorkflowManager()  # new class
    if temp_manager.exists(workflow):
        return temp_manager.load_ir(workflow), None, "temp"

    # 4. Try as file path
    path = Path(workflow)
    if path.exists() and path.is_file():
        return json.load(path.open()), None, "file"

    # 5. Error with suggestions
    suggestions = get_workflow_suggestions(workflow)
    return None, suggestions, "error"
```

**Auto-Cleanup Options**:
1. **Age-based**: Delete temp workflows older than N days
2. **Manual**: New CLI command: `pflow workflow clean-temp`
3. **Session-based**: Delete when agent session ends (requires session tracking)
4. **On-demand**: Delete only when explicitly requested

---

### Option 2: Prefix Convention in Global Library

**Concept**: Use naming convention to mark temporary workflows in existing `~/.pflow/workflows/`.

**Implementation**:

```python
# No new directory, just naming convention:
~/.pflow/workflows/
├── my-final-workflow.json        # Published
├── another-workflow.json         # Published
├── temp-draft-123.json           # Temp (prefix: "temp-")
└── temp-experiment.json          # Temp (prefix: "temp-")

# Filtering in workflow_list:
def list_workflows(include_temp: bool = False):
    workflows = manager.list_all()
    if not include_temp:
        workflows = [w for w in workflows if not w.startswith("temp-")]
    return workflows
```

**Advantages**:
- ✅ No new directories or resolution logic
- ✅ Simple implementation (just naming convention)
- ✅ Works with existing infrastructure

**Disadvantages**:
- ❌ Still pollutes global library (just hidden)
- ❌ Agents must follow naming convention (not enforced)
- ❌ Cleanup still requires manual intervention
- ❌ No physical separation between drafts and finals

---

### Option 3: Use Inline IR Only (Status Quo)

**Concept**: Encourage agents to use inline IR dictionaries for drafts, only saving when finalized.

**Current Workflow**:
```python
# Agent iterates using inline IR:
result = workflow_validate({"nodes": [...]})  # Iteration 1
result = workflow_validate({"nodes": [...]})  # Iteration 2
result = workflow_validate({"nodes": [...]})  # Iteration 3

# Only save when final:
workflow_save({"nodes": [...]}, "my-workflow", "Final version")
```

**Advantages**:
- ✅ No changes needed (already works)
- ✅ No cleanup needed (nothing persisted)
- ✅ Simple mental model

**Disadvantages**:
- ❌ Drafts lost between agent sessions/conversations
- ❌ No way to inspect intermediate iterations
- ❌ Large IR dictionaries bloat agent context
- ❌ Agent must re-generate entire IR each iteration (can't reference saved drafts)

---

### Option 4: Hybrid Approach (Temp Directory + Inline IR)

**Concept**: Support both temp directory AND inline IR, giving agents flexibility.

**Implementation**:

```python
# Resolution order:
# 1. Inline IR → use directly (no persistence)
# 2. Library name → ~/.pflow/workflows/ (persistent)
# 3. Temp name → ~/.pflow/temp-workflows/ (temporary persistence)
# 4. File path → resolve from CWD (external files)

# Agent workflow:
# Early iterations: inline IR (fast, ephemeral)
workflow_validate({"nodes": [...]})

# Mid-stage: save to temp (need persistence between calls)
workflow_save({"nodes": [...]}, "temp-my-draft", is_temp=True)
workflow_validate("temp-my-draft")  # Can reference by name

# Final: save to library (permanent)
workflow_save("temp-my-draft", "my-workflow", is_temp=False)
```

**Advantages**:
- ✅ Best of both worlds (flexibility)
- ✅ Agents choose appropriate level of persistence
- ✅ Temp storage for multi-step workflows
- ✅ Inline IR for simple iterations

**Disadvantages**:
- ⚠️ More complex mental model (3 storage options)
- ⚠️ Need to track temp vs permanent workflows
- ⚠️ Still need cleanup mechanism

---

## File Path Support: Current vs Ideal

### Current Behavior

**Absolute Paths**: ✅ Work correctly
```python
workflow_execute("/Users/user/my-project/workflow.json")
# → Reads /Users/user/my-project/workflow.json
```

**Relative Paths**: ⚠️ Context-dependent (CWD-based)
```python
workflow_execute("./workflow.json")
# Development: → /Users/andfal/projects/pflow/workflow.json
# Installed:   → /Users/user/current-directory/workflow.json
# Claude:      → /Users/user/workflow.json
```

**Tilde Expansion**: ❌ Not supported (blocked by unused validation)
```python
workflow_execute("~/my-project/workflow.json")
# → Error (validation.py blocks ~, but it's not called)
# → Would actually work if passed through (Python's Path expands ~)
```

### Ideal Behavior (IMO)

**For External File Paths**:
1. ✅ **Absolute paths**: Always work (high specificity, no ambiguity)
2. ⚠️ **Relative paths**: Document that they're CWD-dependent (accept as power-user feature)
3. ✅ **Tilde expansion**: Should work (expand `~` to user home)

**For Temp Workflows**:
- Store in `~/.pflow/temp-workflows/` (absolute, no CWD dependency)
- Reference by name: `"temp-my-draft"` → `~/.pflow/temp-workflows/temp-my-draft.json`

---

## Development vs Installed: Path Resolution

### Scenario Analysis

#### Scenario A: Developer Testing
```bash
# Context:
# Working on pflow repo: /Users/andfal/projects/pflow/
# MCP server running via: uv run pflow-mcp-server

# Agent calls:
workflow_execute("./test-workflow.json")

# Current resolution:
# → /Users/andfal/projects/pflow/test-workflow.json

# With temp directory:
# → First check ~/.pflow/temp-workflows/test-workflow.json
# → Then check /Users/andfal/projects/pflow/test-workflow.json
```

#### Scenario B: Installed User
```bash
# Context:
# User's project: /Users/user/my-project/
# MCP server running via: pflow-mcp-server (installed globally)
# CWD: /Users/user/my-project/

# Agent calls:
workflow_execute("./my-workflow.json")

# Current resolution:
# → /Users/user/my-project/my-workflow.json

# With temp directory:
# → First check ~/.pflow/temp-workflows/my-workflow.json
# → Then check /Users/user/my-project/my-workflow.json
```

#### Scenario C: Claude Desktop
```bash
# Context:
# MCP server launched by Claude Desktop
# CWD: /Users/user/ (home directory)

# Agent calls:
workflow_execute("draft-workflow.json")

# Current resolution:
# → /Users/user/draft-workflow.json  (⚠️ Weird location!)

# With temp directory:
# → First check ~/.pflow/temp-workflows/draft-workflow.json  (✅ Better!)
# → Then check /Users/user/draft-workflow.json
```

**Key Insight**: Temp directory eliminates CWD ambiguity for workflow names.

---

## Critical Design Questions

### Q1: How should temp workflows be referenced?

**Option A: Explicit prefix** (requires agent awareness)
```python
workflow_execute("temp-my-draft")  # Agent must use "temp-" prefix
```

**Option B: Automatic detection** (transparent to agent)
```python
workflow_execute("my-draft")  # System checks library, then temp, then file
```

**Option C: Explicit parameter** (explicit intent)
```python
workflow_execute("my-draft", use_temp=True)  # Agent specifies temp
```

**Recommendation**: Option B (automatic detection) - simplest for agents.

---

### Q2: When should temp workflows be cleaned up?

**Option A: Age-based** (7 days)
```bash
# Auto-cleanup on every MCP server start:
# Delete *.json files in ~/.pflow/temp-workflows/ older than 7 days
```

**Option B: Manual command**
```bash
pflow workflow clean-temp --older-than 7d
```

**Option C: On-save**
```python
# When saving temp → library, delete temp:
workflow_save("temp-my-draft", "final-workflow")
# → Deletes ~/.pflow/temp-workflows/temp-my-draft.json
```

**Option D: Never** (let user manage)

**Recommendation**: Combination of A + B (auto-cleanup with manual override).

---

### Q3: Should temp workflows have metadata?

**Option A: Same metadata as library workflows**
```json
{
  "workflow": {...},
  "metadata": {
    "name": "temp-my-draft",
    "description": "Draft workflow",
    "created_at": "...",
    "is_temporary": true
  }
}
```

**Option B: Minimal/no metadata** (just IR)
```json
{
  "nodes": [...],
  "edges": [...],
  "inputs": {...}
}
```

**Recommendation**: Option B (minimal) - temps are ephemeral, don't need full metadata.

---

### Q4: How do temp workflows affect existing tools?

**Current Tools**:
- `workflow_list` → Should it show temp workflows?
- `workflow_describe` → Should it work with temp workflows?
- `workflow_save` → Should it support saving to temp?
- `workflow_execute` → Already supports file paths (would work)
- `workflow_validate` → Already supports file paths (would work)

**Proposal**:
- `workflow_list` → Add optional `include_temp=false` parameter
- `workflow_describe` → Work with temp workflows (same as library)
- `workflow_save` → Add optional `is_temp=false` parameter
- `workflow_execute` → No changes (auto-detect temp)
- `workflow_validate` → No changes (auto-detect temp)

---

## Security Considerations

### Current Security Posture

**Path Validation**: Exists but unused (`validation.py:validate_file_path()`)
- Blocks: `..`, `~`, `\x00`, absolute paths (if flag set)
- **Status**: Commented out in resolver (trusted local environment)

**Parameter Validation**: Active (`validation.py:validate_execution_parameters()`)
- Blocks: Code injection (`__import__`, `eval`, `exec`)
- **Status**: Used by execution service

**Assumption**: MCP server runs locally, user is trusted

### With Temp Directory

**New Risks**:
1. **Path Traversal**: Agent creates `../../etc/passwd.json` in temp directory
   - **Mitigation**: Validate workflow names (no `/`, `..`, etc.)

2. **Storage Exhaustion**: Agent creates 1000s of temp workflows
   - **Mitigation**: Size limits + cleanup

3. **Name Collisions**: Multiple agents/sessions using same temp names
   - **Mitigation**: Session-based prefixes (e.g., `session-123-my-draft`)

**Recommendations**:
- Enforce filename rules for temp workflows (alphanumeric + hyphens only)
- Add size limit for temp directory (e.g., 100MB total)
- Auto-cleanup prevents unbounded growth

---

## Implementation Impact Assessment

### Files That Would Need Changes

**Core Changes** (if adding temp directory):

1. **`src/pflow/mcp_server/utils/resolver.py`** (lines 18-76)
   - Add temp directory resolution step
   - Update `resolve_workflow()` logic

2. **`src/pflow/core/workflow_manager.py`** (new or extend)
   - Create `TempWorkflowManager` class
   - Methods: `save_temp()`, `load_temp()`, `exists_temp()`, `cleanup_temp()`

3. **`src/pflow/mcp_server/tools/workflow_tools.py`** (lines 152-225)
   - Update `workflow_save` to support `is_temp` parameter

4. **`src/pflow/cli/commands/workflow.py`** (new command)
   - Add `pflow workflow clean-temp` command

**Documentation Changes**:

5. **`architecture/implementation-details/mcp-server.md`**
   - Document temp directory behavior

6. **`src/pflow/mcp_server/resources/instructions.py`**
   - Update agent instructions for temp workflow usage

**Testing Changes**:

7. **`tests/test_mcp_server/test_resolver.py`** (new or extend)
   - Test temp directory resolution
   - Test cleanup behavior

---

## Recommendation

### Proposed Solution: **Option 4 (Hybrid)** with **Q&A Answers**

**What to build**:
1. Add `~/.pflow/temp-workflows/` directory
2. Update resolver to check: Library → Temp → File path → Inline IR
3. Add `workflow_save(is_temp=True)` parameter
4. Add auto-cleanup (7 days) + manual `pflow workflow clean-temp` command
5. Minimal metadata for temp workflows (just IR + timestamp)
6. Temp workflows hidden from `workflow_list` by default

**Why this is best**:
- ✅ Solves agent iteration problem (persistent drafts)
- ✅ Works identically in dev/installed/Claude Desktop
- ✅ No CWD ambiguity (always `~/.pflow/temp-workflows/`)
- ✅ Auto-cleanup prevents clutter
- ✅ Simple for agents (automatic detection)
- ✅ Backward compatible (existing workflows unaffected)

**Implementation effort**: Medium (2-3 hours)
- New `TempWorkflowManager` class
- Resolver updates
- CLI command for cleanup
- Tests

---

## Questions for User

1. **Do you want temp directory support?** (vs keeping inline IR only)
2. **Preferred cleanup strategy?** (age-based auto, manual, both, never)
3. **Should temp workflows be visible in `workflow_list`?** (default: no)
4. **Naming convention preference?** (prefix like `temp-*`, suffix like `*-draft`, or no convention)
5. **Should we add session IDs to temp names?** (prevents collisions between agents)

---

## Next Steps

**If you decide to implement temp directory support**:
1. Review and confirm design decisions (Q1-Q4 above)
2. Create implementation plan with subtasks
3. Write tests first (TDD approach)
4. Implement `TempWorkflowManager` class
5. Update resolver logic
6. Add CLI cleanup command
7. Update documentation
8. Test in all three scenarios (dev, installed, Claude Desktop)

**If you want to keep status quo**:
- Document current behavior in `architecture/implementation-details/mcp-server.md`
- Add examples showing inline IR workflow for agents
- Consider adding warning in MCP instructions about relative path CWD dependency
