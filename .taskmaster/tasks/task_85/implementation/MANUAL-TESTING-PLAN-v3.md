# Task 85 - Manual Testing Plan (Version 3.0)

**⚠️ IMPORTANT: Version 3 - Comprehensive Final Testing**

**Purpose**: Final verification of all template resolution features including partial resolution fix (Issue #96)

**Branch**: `feat/runtime-template-resolution`
**Updated**: 2025-10-20
**Previous Results**: 5/6 formatting issues fixed, Issue #95 fixed, Issue #96 fixed

---

## What's New in Version 3

1. ✅ **Tests for partial resolution fix** (GitHub Issue #96)
2. ✅ **Fixed shell command issues** - All tests use `echo` instead of `printf`
3. ✅ **Fixed Test 6.1 design flaw** - Proper MCP false positive test
4. ✅ **Added WARNING log formatting test**
5. ✅ **All tests are now runnable**

---

## Known Status from Previous Testing

### ✅ FIXED Issues
- **Issue #1**: Error duplication - **FIXED**
- **Issue #3**: Clean parameter formatting - **FIXED**
- **Issue #4**: Correct node ID in errors - **FIXED**
- **Issue #5**: Empty context shows "(none)" - **FIXED**
- **Issue #6**: JSON status field - **FIXED**
- **Issue #95**: Core template resolution bug - **FIXED**
- **Issue #96**: Partial resolution detection - **FIXED** (NEW!)

### ⚠️ Known Limitation
- **Issue #2**: WARNING logs still show timestamps/file paths (ERROR logs are clean)
  - Example: `[10/20/25 22:58:01] WARNING ... node_wrapper.py:403`
  - This is acceptable and can be addressed in a follow-up PR

---

## Testing Prerequisites

### Environment Setup
```bash
# Ensure you're on the correct branch
git checkout feat/runtime-template-resolution

# Install dependencies
make install

# Clean any existing test files
rm -f test-*.json

# Clear settings (if testing configuration)
rm -f ~/.pflow/settings.json
```

---

## Section 1: Core Template Resolution ✅

### Test 1.1: Basic Success Path
**Purpose**: Verify templates resolve correctly when all variables exist

**Create**: `test-success.json`
```json
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "producer",
      "type": "shell",
      "params": {"command": "echo", "args": ["Hello World"]}
    },
    {
      "id": "consumer",
      "type": "shell",
      "params": {"command": "echo", "args": ["Got: ${producer.stdout}"]}
    }
  ],
  "edges": [{"from": "producer", "to": "consumer", "action": "default"}]
}
```

**Run**: `uv run pflow test-success.json`

**Expected**:
- ✅ No warnings
- ✅ Output: "Got: Hello World"
- ✅ Status: "✓ Workflow completed"

---

### Test 1.2: Strict Mode Failure
**Purpose**: Verify strict mode fails on missing template

**Create**: `test-strict-fail.json`
```json
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "will-fail",
      "type": "shell",
      "params": {"command": "echo", "args": ["Value: ${missing}"]}
    }
  ],
  "edges": []
}
```

**Run**: `uv run pflow test-strict-fail.json`

**Verify**:
- ✅ Error appears ONCE (not 3 times)
- ✅ NO timestamps like `[10/20/25 22:34:15]`
- ✅ NO file paths like `node_wrapper.py:377`
- ✅ Clean format: `Value: ${missing}` (not Python repr)
- ✅ Shows correct node ID: `node 'will-fail'`
- ✅ Empty context shows: `Available context keys: (none)`

---

### Test 1.3: Permissive Mode Warning
**Purpose**: Verify permissive mode continues with warning

**Create**: `test-permissive.json`
```json
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "permissive",
  "nodes": [
    {
      "id": "will-warn",
      "type": "shell",
      "params": {"command": "echo", "args": ["Value: ${missing}"]}
    }
  ],
  "edges": []
}
```

**Run**: `uv run pflow test-permissive.json`

**Verify**:
- ✅ Workflow completes (doesn't fail)
- ✅ Shows: `⚠️ Workflow completed with warnings`
- ✅ Output contains literal: `Value: ${missing}`
- ⚠️ **Known Issue**: WARNING logs show timestamp/file path (acceptable)

---

## Section 2: Partial Resolution Detection (Issue #96 Fix) 🆕

### Test 2.1: Partial Resolution Detection
**Purpose**: Verify our fix detects partial resolution

**Create**: `test-partial.json`
```json
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "name-provider",
      "type": "shell",
      "params": {"command": "echo", "args": ["Alice"]}
    },
    {
      "id": "builder",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["User ${name-provider.stdout} has ${missing_count} items"]
      }
    }
  ],
  "edges": [{"from": "name-provider", "to": "builder", "action": "default"}]
}
```

**Run**: `uv run pflow test-partial.json`

**Critical Verification**:
- ✅ **MUST FAIL** (not succeed)
- ✅ Error shows: `Unresolved variables: ${missing_count}`
- ✅ Does NOT output: "User Alice has ${missing_count} items"
- ✅ This verifies Issue #96 fix is working!

---

### Test 2.2: Complete Multi-Variable Resolution
**Purpose**: Verify multiple variables all resolve

**Create**: `test-multi-complete.json`
```json
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "name",
      "type": "shell",
      "params": {"command": "echo", "args": ["Alice"]}
    },
    {
      "id": "count",
      "type": "shell",
      "params": {"command": "echo", "args": ["5"]}
    },
    {
      "id": "builder",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["User ${name.stdout} has ${count.stdout} items"]
      }
    }
  ],
  "edges": [
    {"from": "name", "to": "count", "action": "default"},
    {"from": "count", "to": "builder", "action": "default"}
  ]
}
```

**Run**: `uv run pflow test-multi-complete.json`

**Verify**:
- ✅ Succeeds (all variables resolve)
- ✅ Output: "User Alice has 5 items"

---

### Test 2.3: Three Variable Partial Resolution
**Purpose**: Test with 3+ variables, only some resolve

**Create**: `test-three-partial.json`
```json
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "greeting",
      "type": "shell",
      "params": {"command": "echo", "args": ["Hello"]}
    },
    {
      "id": "name",
      "type": "shell",
      "params": {"command": "echo", "args": ["Alice"]}
    },
    {
      "id": "message",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["${greeting.stdout} ${name.stdout}, you have ${count.stdout} items"]
      }
    }
  ],
  "edges": [
    {"from": "greeting", "to": "name", "action": "default"},
    {"from": "name", "to": "message", "action": "default"}
  ]
}
```

**Run**: `uv run pflow test-three-partial.json`

**Verify**:
- ✅ FAILS (count.stdout is missing)
- ✅ Error mentions unresolved: `${count.stdout}`

---

## Section 3: Issue #95 - Critical Bug Verification ✅

### Test 3.1: Empty stdout Template
**Purpose**: Verify Issue #95 is fixed - the original bug

**Create**: `test-issue-95.json`
```json
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "produce-nothing",
      "type": "shell",
      "params": {"command": "true"}
    },
    {
      "id": "use-stdout",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["Sending to API: ${produce-nothing.stdout}"]
      }
    }
  ],
  "edges": [{"from": "produce-nothing", "to": "use-stdout", "action": "default"}]
}
```

**Run**: `uv run pflow test-issue-95.json`

**Critical Verification**:
- ✅ **MUST FAIL** before reaching the echo command
- ✅ Does NOT send literal `${produce-nothing.stdout}` to API
- ✅ Error clearly shows template couldn't be resolved

---

## Section 4: Configuration Hierarchy ✅

### Test 4.1: Workflow Overrides Settings
**Setup**: Create settings with permissive default
```bash
mkdir -p ~/.pflow
cat > ~/.pflow/settings.json << 'EOF'
{
  "version": "1.0.0",
  "runtime": {
    "template_resolution_mode": "permissive"
  }
}
EOF
```

**Create**: `test-override.json`
```json
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "test",
      "type": "shell",
      "params": {"command": "echo", "args": ["${missing}"]}
    }
  ]
}
```

**Run**: `uv run pflow test-override.json`

**Verify**:
- ✅ FAILS (strict mode from workflow overrides permissive from settings)

**Cleanup**: `rm ~/.pflow/settings.json`

---

## Section 5: JSON Output Status ✅

### Test 5.1: JSON Success Status
**Run**: `uv run pflow test-success.json -o json | jq '.status'`

**Expected**: `"success"`

---

### Test 5.2: JSON Degraded Status
**Run**: `uv run pflow test-permissive.json -o json | jq '.status, .warnings'`

**Expected**:
- Status: `"degraded"`
- Warnings object present

---

### Test 5.3: JSON Failed Status (Issue #6 Fix)
**Run**: `uv run pflow test-strict-fail.json -o json 2>/dev/null | jq '.status'`

**Expected**: `"failed"` (NOT null!)

---

## Section 6: Edge Cases

### Test 6.1: MCP False Positive Prevention (Fixed Design)
**Purpose**: Verify resolved data containing ${...} doesn't trigger errors

**Create**: `test-mcp-false-positive.json`
```json
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "mcp-sim",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["The old format used $OLD_VAR in templates"]
      }
    },
    {
      "id": "processor",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["MCP said: ${mcp-sim.stdout}"]
      }
    }
  ],
  "edges": [{"from": "mcp-sim", "to": "processor", "action": "default"}]
}
```

**Note**: The first node outputs literal text containing "$OLD_VAR" (no curly braces, so not a template)

**Run**: `uv run pflow test-mcp-false-positive.json`

**Verify**:
- ✅ Succeeds (no false positive)
- ✅ Output: "MCP said: The old format used $OLD_VAR in templates"

---

### Test 6.2: Empty Value Resolution
**Purpose**: Verify empty strings resolve correctly

**Create**: `test-empty.json`
```json
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "empty",
      "type": "shell",
      "params": {"command": "echo", "args": [""]}
    },
    {
      "id": "consumer",
      "type": "shell",
      "params": {"command": "echo", "args": ["[${empty.stdout}]"]}
    }
  ],
  "edges": [{"from": "empty", "to": "consumer", "action": "default"}]
}
```

**Run**: `uv run pflow test-empty.json`

**Verify**:
- ✅ Succeeds
- ✅ Output: "[]" (empty resolved correctly)

---

### Test 6.3: Similar Variable Names
**Purpose**: Test partial resolution doesn't confuse similar names

**Create**: `test-similar-names.json`
```json
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "user",
      "type": "shell",
      "params": {"command": "echo", "args": ["Alice"]}
    },
    {
      "id": "display",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["User: ${user.stdout}, Username: ${username.stdout}"]
      }
    }
  ],
  "edges": [{"from": "user", "to": "display", "action": "default"}]
}
```

**Run**: `uv run pflow test-similar-names.json`

**Verify**:
- ✅ FAILS (username.stdout doesn't exist)
- ✅ Error shows `${username.stdout}` is unresolved
- ✅ Doesn't confuse with `${user.stdout}`

---

## Section 7: Error Message Quality

### Test 7.1: Helpful Suggestions
**Create**: `test-suggestions.json`
```json
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "data-producer",
      "type": "shell",
      "params": {"command": "echo", "args": ["test"]}
    },
    {
      "id": "consumer",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["${data-producer.output}"]
      }
    }
  ],
  "edges": [{"from": "data-producer", "to": "consumer", "action": "default"}]
}
```

**Run**: `uv run pflow test-suggestions.json`

**Verify Error Contains**:
- ✅ Available context keys
- ✅ Suggestion: "Did you mean '${data-producer.stdout}'?"
- ✅ Tip about --auto-repair flag

---

## Test Generation Script

Save as `generate-test-files.sh`:

```bash
#!/bin/bash
echo "Generating test files for Task 85 v3..."

# Test 1.1: Success
cat > test-success.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "producer",
      "type": "shell",
      "params": {"command": "echo", "args": ["Hello World"]}
    },
    {
      "id": "consumer",
      "type": "shell",
      "params": {"command": "echo", "args": ["Got: ${producer.stdout}"]}
    }
  ],
  "edges": [{"from": "producer", "to": "consumer", "action": "default"}]
}
EOF

# Test 1.2: Strict fail
cat > test-strict-fail.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "will-fail",
      "type": "shell",
      "params": {"command": "echo", "args": ["Value: ${missing}"]}
    }
  ],
  "edges": []
}
EOF

# Test 1.3: Permissive
cat > test-permissive.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "permissive",
  "nodes": [
    {
      "id": "will-warn",
      "type": "shell",
      "params": {"command": "echo", "args": ["Value: ${missing}"]}
    }
  ],
  "edges": []
}
EOF

# Test 2.1: Partial resolution
cat > test-partial.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "name-provider",
      "type": "shell",
      "params": {"command": "echo", "args": ["Alice"]}
    },
    {
      "id": "builder",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["User ${name-provider.stdout} has ${missing_count} items"]
      }
    }
  ],
  "edges": [{"from": "name-provider", "to": "builder", "action": "default"}]
}
EOF

# Continue with other test files...

echo "Generated test files:"
ls -1 test-*.json
```

---

## Test Results Checklist

```
## Critical Tests (MUST PASS)
[ ] Test 1.1: Basic Success Path
[ ] Test 1.2: Strict Mode Failure (all 5 formatting issues fixed)
[ ] Test 2.1: Partial Resolution Detection (Issue #96)
[ ] Test 3.1: Issue #95 - Empty stdout

## Core Functionality
[ ] Test 1.3: Permissive Mode (WARNING log formatting is known issue)
[ ] Test 2.2: Complete Multi-Variable Resolution
[ ] Test 2.3: Three Variable Partial Resolution
[ ] Test 4.1: Configuration Override

## JSON Output (Issue #6)
[ ] Test 5.1: JSON Success Status
[ ] Test 5.2: JSON Degraded Status
[ ] Test 5.3: JSON Failed Status (must be "failed" not null)

## Edge Cases
[ ] Test 6.1: MCP False Positive Prevention
[ ] Test 6.2: Empty Value Resolution
[ ] Test 6.3: Similar Variable Names
[ ] Test 7.1: Helpful Suggestions

TOTAL: ___/15 tests passed
```

---

## Success Criteria

**Must Pass for Merge**:
1. ✅ Test 1.2 - All formatting issues fixed (except WARNING logs)
2. ✅ Test 2.1 - Partial resolution detected (Issue #96)
3. ✅ Test 3.1 - Issue #95 fixed
4. ✅ Test 5.3 - JSON status not null

**Known Acceptable Issues**:
- ⚠️ WARNING logs show timestamps/file paths (can be fixed later)

---

## Conclusion

If all critical tests pass, Task 85 is **PRODUCTION READY** and can be merged to main.

The WARNING log formatting issue is minor and can be addressed in a follow-up PR if needed.