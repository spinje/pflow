# Implementation Plan: MCP Path Handling Migration

## Overview

**Goals**:
1. Move agent temp workspace from `.pflow/workflows/` (repo-relative) → `~/.pflow/temp-workflows/` (home-based)
2. Move MCP instruction files from `.pflow/instructions/` (repo root) → `src/pflow/mcp_server/resources/instructions/` (package resources)
3. Clean up repo `.pflow/` directory and add to gitignore

**Scope**: Documentation and path changes only - no new features

---

## Design Decisions (RESOLVED)

### 1. Minimal Approach
✅ **Confirmed**: Just change paths, no new features (auto-cleanup, special detection, CLI commands)

### 2. workflow_save() Behavior
✅ **Confirmed**: Keep temp files after save (manual cleanup by agent/user)

### 3. Validation Fix
✅ **Confirmed**: Remove tilde block from validation.py (cleanup dead code)

### 4. Directory Creation
✅ **Confirmed**: Agents create `~/.pflow/temp-workflows/` as needed (auto mkdir)

### 5. Repository Cleanup
✅ **Confirmed**: Delete `.pflow/` and add to `.gitignore`

### 6. Instruction Files Location
✅ **Confirmed**: Move to `src/pflow/mcp_server/resources/instructions/` (package resources)

---

## Changes Required

### Change 1: Move MCP Instruction Files

**Move files**:
```bash
# From (repo root - wrong location):
.pflow/instructions/MCP-AGENT_INSTRUCTIONS.md
.pflow/instructions/MCP_SANDBOX_AGENT_INSTRUCTIONS.md

# To (package resources - correct location):
src/pflow/mcp_server/resources/instructions/MCP-AGENT_INSTRUCTIONS.md
src/pflow/mcp_server/resources/instructions/MCP-SANDBOX-AGENT_INSTRUCTIONS.md
```

**Update loader logic** (`src/pflow/mcp_server/resources/instruction_resources.py:20-44`):
```python
def _get_instructions_path(filename: str) -> Path:
    """Get path to instructions file, checking multiple locations.

    Priority order:
    1. Package resources (shipped with pflow)
    2. User customization directory (optional overrides)
    3. Dev fallback (for development without install)
    """
    # 1. Try package resources (production/installed)
    # From: src/pflow/mcp_server/resources/instruction_resources.py
    # To:   src/pflow/mcp_server/resources/instructions/{filename}
    resource_path = Path(__file__).parent / "instructions" / filename
    if resource_path.exists():
        return resource_path

    # 2. Try user home (for custom instructions)
    user_path = Path.home() / ".pflow" / "instructions" / filename
    if user_path.exists():
        return user_path

    # 3. Dev fallback (old location, for backward compat during migration)
    project_root = Path(__file__).parent.parent.parent.parent.parent
    dev_path = project_root / ".pflow" / "instructions" / filename
    if dev_path.exists():
        return dev_path

    # Return resource path as default (will trigger fallback message if missing)
    return resource_path
```

**Rationale**:
- Package resources checked first (standard Python practice)
- User home allows customization (power users can override)
- Dev fallback temporary (can remove after migration)

---

### Change 2: Update MCP Instructions for Temp Workspace

**Files to update**:
- `src/pflow/mcp_server/resources/instructions/MCP-AGENT_INSTRUCTIONS.md`
- `src/pflow/mcp_server/resources/instructions/MCP-SANDBOX-AGENT_INSTRUCTIONS.md`

**Search and replace** (15 occurrences total):
```bash
# OLD paths:
.pflow/workflows/workflow.json
.pflow/workflows/new-workflow-name.json
.pflow/workflows/draft.json

# NEW paths:
~/.pflow/temp-workflows/workflow.json
~/.pflow/temp-workflows/new-workflow-name.json
~/.pflow/temp-workflows/draft.json
```

**Specific changes** (examples from instructions):

**OLD**:
```markdown
1. Write workflow IR to: `.pflow/workflows/new-workflow-name.json`
2. Validate: `workflow_validate(workflow=".pflow/workflows/workflow.json")`
3. Execute: `workflow_execute(workflow=".pflow/workflows/workflow.json", parameters={...})`
```

**NEW**:
```markdown
1. Write workflow IR to: `~/.pflow/temp-workflows/new-workflow-name.json`
2. Validate: `workflow_validate(workflow="~/.pflow/temp-workflows/workflow.json")`
3. Execute: `workflow_execute(workflow="~/.pflow/temp-workflows/workflow.json", parameters={...})`
```

**Additional documentation** (add to instructions):
```markdown
### Temporary Workspace

Agents should write draft workflows to `~/.pflow/temp-workflows/` during development:
- **Location**: `~/.pflow/temp-workflows/` (user's home directory)
- **Purpose**: Temporary workspace for iteration before saving to library
- **Cleanup**: Manual (agents/users can delete when done)
- **Auto-created**: Directory created automatically on first write

When satisfied with workflow, save to permanent library:
```python
workflow_save(
    workflow="~/.pflow/temp-workflows/draft.json",  # Source (temp)
    name="final-workflow",                          # Destination (library)
    description="Final version"
)
# Workflow now in: ~/.pflow/workflows/final-workflow.json
```

**Note**: Temp files are NOT automatically deleted after save. Agents should clean up manually if desired.
```

---

### Change 3: Fix MCP Validation (Remove Tilde Block)

**File**: `src/pflow/mcp_server/utils/validation.py:20-24`

**OLD**:
```python
ALWAYS_DANGEROUS_PATTERNS = [
    r"\.\.",  # Parent directory
    r"^~",  # Home directory expansion
    r"[\x00]",  # Null bytes
]
```

**NEW**:
```python
ALWAYS_DANGEROUS_PATTERNS = [
    r"\.\.",  # Parent directory
    # Tilde expansion is safe for local MCP servers (Python's Path handles it)
    r"[\x00]",  # Null bytes
]
```

**Rationale**:
- This validation is never called (dead code)
- Tilde expansion is safe for local MCP servers
- Prevents future confusion if someone adds validation calls
- Python's `Path.expanduser()` handles `~` correctly

---

### Change 4: Update .gitignore

**File**: `.gitignore` (repo root)

**Add**:
```gitignore
# User data directory (workflows, settings, traces)
.pflow/
```

**Rationale**:
- Prevents accidental commits of user data
- `.pflow/` in repo was temporary/accidental
- User data belongs in `~/.pflow/`, not repo

---

### Change 5: Delete Local .pflow/ Directory

**Command**:
```bash
rm -rf /Users/andfal/projects/pflow/.pflow/
```

**What gets deleted**:
```
.pflow/
├── instructions/
│   ├── MCP-AGENT_INSTRUCTIONS.md           (moved to src/)
│   └── MCP_SANDBOX_AGENT_INSTRUCTIONS.md   (moved to src/)
└── workflows/
    └── test-suite.json                     (accidental file, not used)
```

**Safety checks**:
1. Verify instruction files moved to `src/pflow/mcp_server/resources/instructions/`
2. Verify no other important files in `.pflow/`
3. Delete entire directory

---

### Change 6: Update Fallback Messages (Optional)

**File**: `src/pflow/mcp_server/resources/instruction_resources.py`

**Update fallback paths** (lines 175, 238):

**OLD**:
```python
return """# Agent Instructions Not Available

The instruction file could not be loaded from `~/.pflow/instructions/MCP-AGENT_INSTRUCTIONS.md`.
```

**NEW**:
```python
return """# Agent Instructions Not Available

The instruction file could not be loaded. Expected locations:
- Package: `src/pflow/mcp_server/resources/instructions/MCP-AGENT_INSTRUCTIONS.md`
- User customization: `~/.pflow/instructions/MCP-AGENT_INSTRUCTIONS.md`
```

**Rationale**: More accurate error message showing search paths.

---

## Implementation Steps

### Step 1: Create Package Resources Directory
```bash
mkdir -p src/pflow/mcp_server/resources/instructions/
```

### Step 2: Move Instruction Files
```bash
# Move files from repo root to package resources
mv .pflow/instructions/MCP-AGENT_INSTRUCTIONS.md \
   src/pflow/mcp_server/resources/instructions/

mv .pflow/instructions/MCP_SANDBOX_AGENT_INSTRUCTIONS.md \
   src/pflow/mcp_server/resources/instructions/
```

### Step 3: Update Instruction Files (Temp Workspace Paths)
- Find/replace: `.pflow/workflows/` → `~/.pflow/temp-workflows/`
- Add temporary workspace documentation section
- 15 occurrences across both files

### Step 4: Update Loader Logic
- Edit `src/pflow/mcp_server/resources/instruction_resources.py`
- Change `_get_instructions_path()` to check package resources first
- Update fallback messages (optional)

### Step 5: Fix Validation
- Edit `src/pflow/mcp_server/utils/validation.py`
- Remove `r"^~"` from `ALWAYS_DANGEROUS_PATTERNS`
- Add comment explaining why

### Step 6: Update .gitignore
```bash
echo "" >> .gitignore
echo "# User data directory (workflows, settings, traces)" >> .gitignore
echo ".pflow/" >> .gitignore
```

### Step 7: Delete Local .pflow/ Directory
```bash
# Verify files moved
ls -la src/pflow/mcp_server/resources/instructions/

# Delete repo .pflow/
rm -rf .pflow/
```

### Step 8: Test Changes
1. Start MCP server: `uv run pflow-mcp-server`
2. Test resource loading: Verify instructions load from new location
3. Test temp workspace: Agent writes to `~/.pflow/temp-workflows/`
4. Test workflow_save: Save from temp → library
5. Test tilde expansion: Paths with `~` work correctly

---

## Testing Plan

### Test 1: Instruction Resources Load
```python
# Test that resources load from new location
from src.pflow.mcp_server.resources.instruction_resources import (
    MCP_AGENT_INSTRUCTIONS_PATH,
    SANDBOX_AGENT_INSTRUCTIONS_PATH,
    get_instructions,
    get_sandbox_instructions,
)

# Verify paths point to package resources
assert "src/pflow/mcp_server/resources/instructions" in str(MCP_AGENT_INSTRUCTIONS_PATH)
assert MCP_AGENT_INSTRUCTIONS_PATH.exists()

# Verify content loads
content = get_instructions()
assert "~/.pflow/temp-workflows/" in content  # New path
assert ".pflow/workflows/" not in content     # Old path removed
```

### Test 2: Temp Workspace Creation
```bash
# Agent writes to temp workspace
echo '{"nodes": []}' > ~/.pflow/temp-workflows/test-draft.json

# Verify file exists
ls -la ~/.pflow/temp-workflows/test-draft.json

# Cleanup
rm ~/.pflow/temp-workflows/test-draft.json
```

### Test 3: Workflow Save (Temp → Library)
```bash
# Create temp workflow
uv run python -c "
from pathlib import Path
import json
Path('~/.pflow/temp-workflows/').expanduser().mkdir(parents=True, exist_ok=True)
Path('~/.pflow/temp-workflows/test-draft.json').expanduser().write_text(
    json.dumps({'ir_version': '0.1.0', 'nodes': [], 'edges': []})
)
"

# Save to library via MCP tool (would be async in real use)
uv run python -c "
from src.pflow.mcp_server.services.execution_service import ExecutionService
result = ExecutionService.save_workflow(
    workflow='~/.pflow/temp-workflows/test-draft.json',
    name='test-from-temp',
    description='Test save from temp',
    force=False,
    generate_metadata=False
)
print(result)
"

# Verify saved to library
ls -la ~/.pflow/workflows/test-from-temp.json

# Cleanup
rm ~/.pflow/workflows/test-from-temp.json
rm ~/.pflow/temp-workflows/test-draft.json
```

### Test 4: Tilde Expansion
```python
# Test that tilde expansion works
from pathlib import Path

temp_path = Path("~/.pflow/temp-workflows/test.json")
expanded = temp_path.expanduser()

assert str(expanded).startswith("/Users/")
assert "~" not in str(expanded)
assert expanded.parent.name == "temp-workflows"
```

### Test 5: .gitignore Works
```bash
# Create test file in .pflow/
mkdir -p .pflow/test
echo "test" > .pflow/test/test.txt

# Check git status (should be ignored)
git status | grep -q ".pflow" && echo "FAIL: .pflow/ not ignored" || echo "PASS: .pflow/ ignored"

# Cleanup
rm -rf .pflow/
```

---

## Rollback Plan

If issues are discovered:

### Rollback Step 1: Restore Instruction Files
```bash
# Copy back from package resources to repo root
mkdir -p .pflow/instructions/
cp src/pflow/mcp_server/resources/instructions/MCP-AGENT_INSTRUCTIONS.md \
   .pflow/instructions/
cp src/pflow/mcp_server/resources/instructions/MCP-SANDBOX-AGENT_INSTRUCTIONS.md \
   .pflow/instructions/
```

### Rollback Step 2: Revert Loader Logic
```bash
git checkout src/pflow/mcp_server/resources/instruction_resources.py
```

### Rollback Step 3: Remove .gitignore Entry
```bash
# Edit .gitignore and remove ".pflow/" line
```

---

## Success Criteria

✅ **Instruction files**:
- Located in `src/pflow/mcp_server/resources/instructions/`
- Load correctly via MCP resources
- Contain updated paths (`~/.pflow/temp-workflows/`)

✅ **Temp workspace**:
- Agents write to `~/.pflow/temp-workflows/`
- Tilde expansion works in all scenarios
- workflow_save transfers temp → library correctly

✅ **Repository cleanup**:
- `.pflow/` deleted from repo
- `.pflow/` added to `.gitignore`
- No accidental commits of user data

✅ **Validation**:
- Tilde block removed from validation.py
- Dead code cleaned up

✅ **Testing**:
- All tests pass
- MCP server starts without errors
- Agent workflows function correctly

---

## Files Changed Summary

**Created**:
- `src/pflow/mcp_server/resources/instructions/` (directory)

**Moved**:
- `.pflow/instructions/MCP-AGENT_INSTRUCTIONS.md` → `src/pflow/mcp_server/resources/instructions/`
- `.pflow/instructions/MCP_SANDBOX_AGENT_INSTRUCTIONS.md` → `src/pflow/mcp_server/resources/instructions/`

**Modified**:
- `src/pflow/mcp_server/resources/instructions/MCP-AGENT_INSTRUCTIONS.md` (path updates)
- `src/pflow/mcp_server/resources/instructions/MCP-SANDBOX-AGENT_INSTRUCTIONS.md` (path updates)
- `src/pflow/mcp_server/resources/instruction_resources.py` (loader logic)
- `src/pflow/mcp_server/utils/validation.py` (remove tilde block)
- `.gitignore` (add `.pflow/`)

**Deleted**:
- `.pflow/` (entire directory from repo)

---

## Estimated Time

- Step 1-2: Create directory, move files (2 minutes)
- Step 3: Update instruction files (10 minutes)
- Step 4: Update loader logic (5 minutes)
- Step 5: Fix validation (2 minutes)
- Step 6-7: Update .gitignore, delete .pflow/ (2 minutes)
- Step 8: Testing (15 minutes)

**Total: ~35-40 minutes**

---

## Questions Resolved

1. ✅ Minimal approach vs enhanced features? → **Minimal**
2. ✅ Auto-delete temp files after save? → **No (manual cleanup)**
3. ✅ Fix validation.py? → **Yes (cleanup dead code)**
4. ✅ Who creates temp directory? → **Agents (auto mkdir)**
5. ✅ Clean up repo .pflow/? → **Yes (delete + gitignore)**
6. ✅ Where to store instruction files? → **Package resources**

---

## Ready to Implement

All ambiguities resolved. Plan is complete and actionable.
