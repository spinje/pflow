# Manual Test Plan: Smart Output Display for `registry run`

## Context

This document provides a comprehensive manual test plan for verifying the Smart Output Display feature implemented for `pflow registry run`. This feature modifies how node execution results are displayed, with three configurable modes.

### What Was Implemented

**Problem Solved**: Previously, `pflow registry run` only showed template paths (e.g., `${stdout} (str)`) without actual values. Users had to run a separate `pflow read-fields` command to see values, which was cumbersome for simple debugging.

**Solution**: Three output modes controlled via settings:
- **smart** (default): Show template paths WITH values, truncate large values, apply smart filtering
- **structure**: Show template paths only (original Task 89 behavior)
- **full**: Show all paths with full values, no filtering or truncation

### Files Modified

1. `src/pflow/core/settings.py` - Added `output_mode` to `RegistrySettings`
2. `src/pflow/cli/commands/settings.py` - Added `pflow settings registry output-mode` command
3. `src/pflow/execution/formatters/node_output_formatter.py` - Core formatting logic
4. `src/pflow/cli/registry_run.py` - Load and pass settings
5. `src/pflow/mcp_server/services/execution_service.py` - Load and pass settings

---

## Prerequisites

Before testing, ensure:
1. You are in the pflow project directory
2. Dependencies are installed: `make install`
3. Tests pass: `make test` (should show 2940+ passed)

---

## Test Plan

### Test 1: Verify Default Mode is "smart"

**Purpose**: Confirm that the default output mode is "smart" (shows values with truncation).

**Steps**:
```bash
# Check current output mode
uv run pflow settings registry output-mode
```

**Expected Output**:
```
Current output mode: smart

Modes:
  smart     - Show values with truncation, apply smart filtering (default)
  structure - Show template paths only, no values
  full      - Show all values, no filtering or truncation

To change: pflow settings registry output-mode <mode>
```

---

### Test 2: Smart Mode - Short Values Display

**Purpose**: Verify that short values are displayed inline with template paths.

**Steps**:
```bash
# Ensure smart mode is set
uv run pflow settings registry output-mode smart

# Run a simple shell command
uv run pflow registry run shell command="echo hello"
```

**Expected Output** (similar to):
```
✓ Node executed successfully

Execution ID: exec-XXXXXXXXXX-XXXXXXXX

Output:
  ✓ ${stdout} (str) = "hello"
  ✓ ${stderr} (str) = ""
  ✓ ${exit_code} (int) = 0
  ✓ ${stdout_is_binary} (bool) = false
  ✓ ${stderr_is_binary} (bool) = false

Execution time: XXms
```

**Verification Checklist**:
- [ ] Output shows "Output:" header (not "Available template paths:")
- [ ] Actual values are shown (e.g., `"hello"`, `0`, `false`)
- [ ] Template paths are shown with `${}` syntax
- [ ] Type annotations are shown (e.g., `(str)`, `(int)`, `(bool)`)

---

### Test 3: Smart Mode - Long String Truncation

**Purpose**: Verify that strings longer than 200 characters are truncated with `(truncated)` indicator.

**Steps**:
```bash
# Generate a long string (300+ chars)
uv run pflow registry run shell command="python -c \"print('x' * 300)\""
```

**Expected Output** (similar to):
```
✓ Node executed successfully

Execution ID: exec-XXXXXXXXXX-XXXXXXXX

Output:
  ✓ ${stdout} (str) = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx..." (truncated)
  ✓ ${stderr} (str) = ""
  ✓ ${exit_code} (int) = 0
  ...

Use `pflow read-fields exec-XXXXXXXXXX-XXXXXXXX <path>` for full values.

Execution time: XXms
```

**Verification Checklist**:
- [ ] Long string is truncated (ends with `...`)
- [ ] `(truncated)` indicator appears after the truncated value
- [ ] `pflow read-fields` hint is shown at the bottom
- [ ] Execution ID in hint matches the displayed Execution ID

---

### Test 4: Smart Mode - Large Dict Summarization

**Purpose**: Verify that dicts with more than 5 keys show `{...N keys}` summary.

**Steps**:
```bash
# Create a JSON file with a large dict
echo '{"a":1,"b":2,"c":3,"d":4,"e":5,"f":6,"g":7}' > /tmp/test.json

# Read it
uv run pflow registry run read-file file_path=/tmp/test.json
```

**Expected Output** (similar to):
```
✓ Node executed successfully

Execution ID: exec-XXXXXXXXXX-XXXXXXXX

Output:
  ✓ ${content} (str) = "{"a":1,"b":2,"c":3,"d":4,"e":5,"f":6,"g":7}"
  ...

Execution time: XXms
```

**Alternative Test** (if above doesn't show dict directly):
```bash
uv run pflow registry run shell command="echo '{\"a\":1,\"b\":2,\"c\":3,\"d\":4,\"e\":5,\"f\":6}'"
```

---

### Test 5: Smart Mode - Large List Summarization

**Purpose**: Verify that lists with more than 5 items show `[...N items]` summary.

**Steps**:
```bash
uv run pflow registry run shell command="python -c \"import json; print(json.dumps(list(range(20))))\""
```

**Expected Output** should show the list output. If the node returns structured data with lists, they should show as `[...N items]` when over 5 items.

---

### Test 6: Structure Mode - Paths Only (No Values)

**Purpose**: Verify that structure mode shows only template paths without values.

**Steps**:
```bash
# Switch to structure mode
uv run pflow settings registry output-mode structure

# Run a command
uv run pflow registry run shell command="echo hello"
```

**Expected Output**:
```
✓ Node executed successfully

Execution ID: exec-XXXXXXXXXX-XXXXXXXX

Available template paths:
  ✓ ${exit_code} (int)
  ✓ ${stderr} (str)
  ✓ ${stdout} (str)
  ✓ ${stderr_is_binary} (bool)
  ✓ ${stdout_is_binary} (bool)

Use these paths in workflow templates.

Execution time: XXms
```

**Verification Checklist**:
- [ ] Output shows "Available template paths:" header
- [ ] NO actual values shown (no `= "hello"` etc.)
- [ ] Shows "Use these paths in workflow templates." hint
- [ ] Template paths and types are shown

---

### Test 7: Full Mode - All Values Without Truncation

**Purpose**: Verify that full mode shows all values without any truncation or filtering.

**Steps**:
```bash
# Switch to full mode
uv run pflow settings registry output-mode full

# Generate long output
uv run pflow registry run shell command="python -c \"print('x' * 300)\""
```

**Expected Output**:
```
✓ Node executed successfully

Execution ID: exec-XXXXXXXXXX-XXXXXXXX

Output (all 5 fields):
  ✓ ${stdout} (str) = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx...300 x's total...xxxxxxxxxxxxxxxxxxxx"
  ✓ ${stderr} (str) = ""
  ✓ ${exit_code} (int) = 0
  ...

Execution time: XXms
```

**Verification Checklist**:
- [ ] Output shows "Output (all N fields):" header
- [ ] Long strings are NOT truncated (full 300 chars shown)
- [ ] NO `(truncated)` indicator
- [ ] NO `pflow read-fields` hint
- [ ] All fields shown (no smart filtering)

---

### Test 8: Settings Persistence

**Purpose**: Verify that output mode setting persists across commands.

**Steps**:
```bash
# Set to structure mode
uv run pflow settings registry output-mode structure

# Verify it's set
uv run pflow settings registry output-mode

# Run a command (should use structure mode)
uv run pflow registry run shell command="echo test"

# Set back to smart
uv run pflow settings registry output-mode smart

# Verify it's back to smart
uv run pflow settings registry output-mode
```

**Verification Checklist**:
- [ ] `output-mode structure` shows "✓ Set registry output mode: structure"
- [ ] Subsequent `output-mode` (no arg) shows "Current output mode: structure"
- [ ] The registry run command uses the set mode
- [ ] Mode can be changed back to smart

---

### Test 9: Settings Show Command

**Purpose**: Verify output_mode appears in the full settings dump.

**Steps**:
```bash
uv run pflow settings show
```

**Expected Output** (partial):
```json
{
  "version": "1.0.0",
  "registry": {
    "nodes": {
      "allow": ["*"],
      "deny": ["pflow.nodes.git.*", "pflow.nodes.github.*"]
    },
    "include_test_nodes": false,
    "output_mode": "smart"
  },
  ...
}
```

**Verification Checklist**:
- [ ] `output_mode` field appears in `registry` section
- [ ] Value matches what was set

---

### Test 10: Invalid Mode Rejection

**Purpose**: Verify that invalid output modes are rejected.

**Steps**:
```bash
uv run pflow settings registry output-mode invalid
```

**Expected Output**:
```
Usage: pflow settings registry output-mode [OPTIONS] [MODE]
Try 'pflow settings registry output-mode --help' for help.

Error: Invalid value for 'MODE': 'invalid' is not one of 'smart', 'structure', 'full'.
```

**Verification Checklist**:
- [ ] Command fails with error
- [ ] Error message lists valid options

---

### Test 11: Smart Filtering Still Works in Smart Mode

**Purpose**: Verify that smart filtering (>25 fields) is applied in smart mode.

This test requires a node that produces many output fields. You can use an MCP node if configured, or create a test that produces many fields.

**Steps** (if you have an MCP node with many fields):
```bash
uv run pflow settings registry output-mode smart
uv run pflow registry run <mcp-node-with-many-fields>
```

**Expected Output**:
```
Output (8 of 54 shown):
  ✓ ${field1} (type) = value
  ...
```

**Verification Checklist**:
- [ ] "(N of M shown)" appears when filtering occurs
- [ ] Fewer fields shown than total

---

### Test 12: read-fields Command Still Works

**Purpose**: Verify that the read-fields command works with execution IDs.

**Steps**:
```bash
# Run a command and note the execution ID
uv run pflow registry run shell command="echo hello"
# Note the Execution ID (e.g., exec-1234567890-abc123)

# Retrieve specific field
uv run pflow read-fields exec-XXXXXXXXXX-XXXXXXXX stdout
```

**Expected Output**:
```
stdout: hello
```

**Verification Checklist**:
- [ ] read-fields returns the actual value
- [ ] Works with the execution ID from registry run

---

## Edge Cases to Verify

### Test 13: Empty Output

```bash
uv run pflow registry run shell command="exit 0"
```

Should not crash, should show empty stdout/stderr.

### Test 14: Binary Detection

```bash
uv run pflow registry run shell command="printf '\\x00\\x01\\x02'"
```

Should show `stdout_is_binary: true` or similar indicator.

### Test 15: Unicode Content

```bash
uv run pflow registry run shell command="echo '你好世界 🌍'"
```

Should display unicode correctly without crashing.

---

## Reset to Default

After testing, reset to default smart mode:
```bash
uv run pflow settings registry output-mode smart
```

---

## Summary

| Test | Mode | Key Verification |
|------|------|------------------|
| 1 | - | Default is "smart" |
| 2 | smart | Short values shown inline |
| 3 | smart | Long strings truncated with "(truncated)" |
| 4 | smart | Large dicts show `{...N keys}` |
| 5 | smart | Large lists show `[...N items]` |
| 6 | structure | Paths only, no values |
| 7 | full | All values, no truncation |
| 8 | - | Settings persist |
| 9 | - | Settings appear in `show` |
| 10 | - | Invalid modes rejected |
| 11 | smart | Smart filtering works |
| 12 | - | read-fields works |
| 13-15 | - | Edge cases |

---

## Automated Tests

The implementation includes 10 automated tests that verify core functionality:

```bash
# Run just the new tests
uv run pytest tests/test_execution/formatters/test_node_output_formatter.py::TestSmartOutputMode -v
uv run pytest tests/test_execution/formatters/test_node_output_formatter.py::TestOutputModeSettings -v
```

These tests cover:
- `test_smart_mode_shows_values` - Values displayed with paths
- `test_smart_mode_truncates_long_strings` - 200+ char truncation
- `test_smart_mode_summarizes_large_dicts` - Dict summary
- `test_smart_mode_summarizes_large_lists` - List summary
- `test_smart_mode_shows_primitives_fully` - Numbers/bools/null
- `test_smart_mode_shows_read_fields_hint_when_truncated` - Hint display
- `test_full_mode_shows_all_without_truncation` - Full mode
- `test_default_output_mode_is_smart` - Default setting
- `test_output_mode_validates_allowed_values` - Validation
- `test_output_mode_persists_in_settings` - Persistence
