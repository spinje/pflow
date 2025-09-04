# Task 55: Complete Manual Testing Plan
## Output Control & Error Message Improvements

### Overview
This testing plan verifies all output control features, error message improvements, and related fixes implemented in Task 55. Each test is atomic and self-contained with clear setup, execution, and expected results.

### Prerequisites
1. **Environment Setup**
   ```bash
   # Ensure you're in the project directory
   cd /Users/andfal/projects/pflow-fix-output-control-interactive

   # Install/update dependencies
   make install

   # Verify pflow is working
   uv run pflow --version
   # Expected: pflow version 0.0.1
   ```

2. **Test File Creation**
   Create these test files before starting:

   ```bash
   # Create a simple workflow file
   cat > /tmp/test_simple.json << 'EOF'
   {
     "ir_version": "0.1.0",
     "nodes": [
       {
         "id": "echo_node",
         "type": "shell",
         "params": {
           "command": "echo 'Hello from workflow'"
         }
       }
     ],
     "edges": []
   }
   EOF

   # Create a workflow with declared outputs
   cat > /tmp/test_output.json << 'EOF'
   {
     "ir_version": "0.1.0",
     "nodes": [
       {
         "id": "write_node",
         "type": "write-file",
         "params": {
           "path": "/tmp/test_output.txt",
           "content": "Test content"
         }
       }
     ],
     "edges": [],
     "outputs": {
       "result": {
         "description": "The written content",
         "type": "string"
       }
     }
   }
   EOF

   # Create a nested workflow
   cat > /tmp/test_nested.json << 'EOF'
   {
     "ir_version": "0.1.0",
     "nodes": [
       {
         "id": "sub_workflow",
         "type": "workflow",
         "params": {
           "workflow_name": "test-simple"
         }
       }
     ],
     "edges": []
   }
   EOF

   # Create MCP test workflow (will fail without MCP sync)
   cat > /tmp/test_bad_mcp.json << 'EOF'
   {
     "ir_version": "0.1.0",
     "nodes": [
       {
         "id": "mcp_node",
         "type": "mcp-slack-send_message",
         "params": {
           "channel": "#test",
           "text": "Test message"
         }
       }
     ],
     "edges": []
   }
   EOF
   ```

---

## Section 1: Interactive vs Non-Interactive Mode Detection

### Test 1.1: Terminal Mode (Interactive)
**Purpose**: Verify progress shows in normal terminal usage

**Execute**:
```bash
uv run pflow /tmp/test_simple.json
```

**Expected**:
- ✅ Shows "Executing workflow (1 nodes):" header
- ✅ Shows "  echo_node... ✓ X.Xs" progress
- ✅ Shows "Hello from workflow" result
- ✅ Progress messages go to stderr
- ✅ Result goes to stdout

### Test 1.2: Piped Stdin (Non-Interactive)
**Purpose**: Verify progress suppressed when stdin is piped

**Execute**:
```bash
echo "test" | uv run pflow /tmp/test_simple.json
```

**Expected**:
- ✅ NO "Executing workflow" header
- ✅ NO node progress indicators
- ✅ Only shows "Hello from workflow" result
- ✅ Clean stdout output suitable for piping

### Test 1.3: Piped Stdout (Non-Interactive)
**Purpose**: Verify progress suppressed when stdout is piped

**Execute**:
```bash
uv run pflow /tmp/test_simple.json | cat
```

**Expected**:
- ✅ NO progress indicators in output
- ✅ Only "Hello from workflow" visible
- ✅ No contamination in piped output

### Test 1.4: Both Pipes (Non-Interactive)
**Purpose**: Verify clean piping with both stdin and stdout piped

**Execute**:
```bash
echo "test" | uv run pflow /tmp/test_simple.json | cat
```

**Expected**:
- ✅ Only "Hello from workflow" in output
- ✅ No progress, no headers, no traces
- ✅ Exit code 0

### Test 1.5: Critical Pipe Test
**Purpose**: Verify the exact scenario from specification

**Execute**:
```bash
echo "test" | uv run pflow "echo hello" | cat
```

**Expected**:
- ✅ Only "hello" appears in output (after planner runs)
- ✅ No progress contamination
- ✅ Clean pipeline behavior

---

## Section 2: CLI Flag Testing

### Test 2.1: -p/--print Flag (Force Non-Interactive)
**Purpose**: Verify -p flag suppresses progress even in terminal

**Execute**:
```bash
uv run pflow -p /tmp/test_simple.json
```

**Expected**:
- ✅ NO progress indicators (despite being in terminal)
- ✅ Only shows "Hello from workflow"
- ✅ Behaves like piped mode

### Test 2.2: -p Flag with Natural Language
**Purpose**: Verify -p flag works with planner

**Execute**:
```bash
uv run pflow -p "echo hello world"
```

**Expected**:
- ✅ NO planner progress (workflow-discovery, generator, etc.)
- ✅ NO execution progress
- ✅ Only shows "hello world" result

### Test 2.3: JSON Mode (Implies Non-Interactive)
**Purpose**: Verify JSON format suppresses progress

**Execute**:
```bash
uv run pflow --output-format json /tmp/test_simple.json
```

**Expected**:
- ✅ NO progress indicators
- ✅ Valid JSON output only
- ✅ Can be piped to jq: `| jq .`

### Test 2.4: Combined Flags
**Purpose**: Verify flag precedence

**Execute**:
```bash
uv run pflow -p --output-format json /tmp/test_simple.json | jq .
```

**Expected**:
- ✅ Valid JSON output
- ✅ No progress (both flags force non-interactive)
- ✅ Clean pipeline behavior

---

## Section 3: Planner Progress Control

### Test 3.1: Planner Progress in Interactive Mode
**Purpose**: Verify planner shows progress in terminal

**Execute**:
```bash
uv run pflow "create a file called test.txt with hello world"
```

**Expected**:
- ✅ Shows "workflow-discovery... ✓ X.Xs"
- ✅ Shows "generator... ✓ X.Xs"
- ✅ Shows "✅ Validation... ✓ X.Xs"
- ✅ Shows execution progress after planning

### Test 3.2: Planner Progress Suppressed When Piped
**Purpose**: Verify planner progress hidden in pipes

**Execute**:
```bash
echo "test" | uv run pflow "echo hello" 2>&1 | grep -v "^$"
```

**Expected**:
- ✅ NO "workflow-discovery" messages
- ✅ NO "generator" messages
- ✅ Only shows "hello" result

### Test 3.3: Planner with -p Flag
**Purpose**: Verify -p suppresses planner progress

**Execute**:
```bash
uv run pflow -p "list files in current directory"
```

**Expected**:
- ✅ NO planner progress indicators
- ✅ Only shows file listing results

---

## Section 4: Save Workflow Prompts

### Test 4.1: Interactive Save Prompt
**Purpose**: Verify save prompt appears in terminal

**Setup**: Clear any existing saved workflow
```bash
rm -f ~/.pflow/workflows/test-workflow.json
```

**Execute** (in terminal, not piped):
```bash
uv run pflow "echo test message"
# When prompted "Save this workflow? (y/n)", type: n
```

**Expected**:
- ✅ Shows "Save this workflow? (y/n)" prompt
- ✅ Accepts user input
- ✅ Shows result after declining

### Test 4.2: No Save Prompt When Piped
**Purpose**: Verify no prompts when output is piped

**Execute**:
```bash
uv run pflow "echo test" | cat
```

**Expected**:
- ✅ NO save prompt
- ✅ NO hanging/waiting for input
- ✅ Only shows "test" result
- ✅ Exits cleanly

### Test 4.3: No Save Prompt with -p Flag
**Purpose**: Verify -p flag suppresses prompts

**Execute**:
```bash
uv run pflow -p "echo test"
```

**Expected**:
- ✅ NO save prompt
- ✅ Direct output of "test"
- ✅ Clean exit

---

## Section 5: Execution Progress Details

### Test 5.1: Multi-Node Progress
**Purpose**: Verify progress for workflows with multiple nodes

**Create test file**:
```bash
cat > /tmp/test_multi.json << 'EOF'
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "node1", "type": "shell", "params": {"command": "echo 'Step 1'"}},
    {"id": "node2", "type": "shell", "params": {"command": "echo 'Step 2'"}},
    {"id": "node3", "type": "shell", "params": {"command": "echo 'Step 3'"}}
  ],
  "edges": [
    {"from": "node1", "to": "node2"},
    {"from": "node2", "to": "node3"}
  ]
}
EOF
```

**Execute**:
```bash
uv run pflow /tmp/test_multi.json
```

**Expected**:
- ✅ Shows "Executing workflow (3 nodes):"
- ✅ Shows "  node1... ✓ X.Xs"
- ✅ Shows "  node2... ✓ X.Xs"
- ✅ Shows "  node3... ✓ X.Xs"
- ✅ All progress to stderr, results to stdout

### Test 5.2: Empty Workflow (0 nodes)
**Purpose**: Verify handling of empty workflows

**Create test file**:
```bash
cat > /tmp/test_empty.json << 'EOF'
{
  "ir_version": "0.1.0",
  "nodes": [],
  "edges": []
}
EOF
```

**Execute**:
```bash
uv run pflow /tmp/test_empty.json
```

**Expected**:
- ✅ Shows "Executing workflow (0 nodes):"
- ✅ Shows "Workflow executed successfully"
- ✅ No errors

### Test 5.3: Nested Workflow Indentation
**Purpose**: Verify nested workflows show proper indentation

**First save a simple workflow**:
```bash
cat > ~/.pflow/workflows/test-simple.json << 'EOF'
{
  "name": "test-simple",
  "workflow": {
    "ir_version": "0.1.0",
    "nodes": [
      {"id": "inner", "type": "shell", "params": {"command": "echo 'Inner workflow'"}}
    ],
    "edges": []
  }
}
EOF
```

**Execute**:
```bash
uv run pflow /tmp/test_nested.json
```

**Expected**:
- ✅ Shows "Executing workflow (1 nodes):"
- ✅ Shows "  sub_workflow... ✓ X.Xs"
- ✅ Nested execution may show additional indentation
- ✅ Shows "Inner workflow" result

---

## Section 6: Trace Output Control

### Test 6.1: Trace in Interactive Mode
**Purpose**: Verify trace file location shown in terminal

**Execute**:
```bash
uv run pflow --trace /tmp/test_simple.json
```

**Expected**:
- ✅ Shows progress indicators
- ✅ Shows "📊 Workflow trace saved: /path/to/trace.json"
- ✅ Trace message goes to stderr

### Test 6.2: Trace Suppressed with -p Flag
**Purpose**: Verify -p flag suppresses trace messages

**Execute**:
```bash
uv run pflow --trace -p /tmp/test_simple.json
```

**Expected**:
- ✅ NO "Workflow trace saved" message
- ✅ Only shows "Hello from workflow"
- ✅ Trace file still created (verify with ls)

### Test 6.3: Trace Suppressed When Piped
**Purpose**: Verify trace messages hidden in pipes

**Execute**:
```bash
echo "test" | uv run pflow --trace /tmp/test_simple.json | cat
```

**Expected**:
- ✅ NO trace messages in output
- ✅ Only "Hello from workflow" visible
- ✅ Trace file still created

### Test 6.4: Planner Trace
**Purpose**: Verify planner trace behavior

**Execute**:
```bash
uv run pflow --trace-planner "echo test"
```

**Expected (Interactive)**:
- ✅ Shows planner progress
- ✅ Shows "📝 Planner trace saved: /path/to/trace.json"

**Execute**:
```bash
uv run pflow --trace-planner -p "echo test"
```

**Expected (With -p flag)**:
- ✅ NO trace messages
- ✅ Only shows "test" result

---

## Section 7: MCP Output Control

**IMPORTANT NOTE**: MCP tests will show different behavior depending on whether MCP servers are configured and synced. The tests below document both scenarios.

### Test 7.1: MCP Error Messages (Improved)
**Purpose**: Verify user-friendly MCP error messages

**Execute**:
```bash
uv run pflow /tmp/test_bad_mcp.json
```

**Expected Scenario A** (MCP tools ARE synced - node name exists):
- ✅ Error about wrong tool name or missing parameters
- ✅ Suggestions for correct node names
- ✅ NO internal `__mcp_server__` parameters exposed

**Expected Scenario B** (MCP tools NOT synced - typical case):
- ✅ Shows compilation error with available node types
- ✅ Lists actual available nodes (not the user-friendly message yet)
- ✅ This is expected as the error happens at compile time before MCPNode can provide better error

### Test 7.2: MCP Natural Language Requests (Skip if no MCP)
**Purpose**: Verify planner handling of MCP-related requests

**Execute**:
```bash
uv run pflow "send a message saying hello to slack"
```

**Expected** (without proper parameters):
- ✅ Shows "Missing required parameters" error
- ✅ Lists which parameters are needed (e.g., channel_id)
- ✅ Suggests providing these parameters

### Test 7.3: MCP Verbose Mode (Skip if no MCP configured)
**Purpose**: Verify verbose flag behavior with MCP

**Note**: This test only applies if you have MCP servers configured and synced. Otherwise skip.

**Execute** (only if MCP is available):
```bash
uv run pflow -v [existing-mcp-workflow]
```

**Expected with -v**:
- ✅ May show additional debug information
- ✅ Server messages (if any) go to stderr

### Test 7.4: MCP in Non-Interactive Mode
**Purpose**: Verify clean piping even with MCP errors

**Execute**:
```bash
echo "test" | uv run pflow /tmp/test_bad_mcp.json 2>/dev/null
```

**Expected**:
- ✅ No output (error went to stderr which we discarded)
- ✅ Exit code non-zero (check with `echo $?`)

---

## Section 8: Error Message Improvements

### Test 8.1: Basic Error Display
**Purpose**: Verify error formatting

**Execute** (intentionally bad workflow):
```bash
cat > /tmp/test_error.json << 'EOF'
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "bad", "type": "nonexistent-node", "params": {}}
  ],
  "edges": []
}
EOF
uv run pflow /tmp/test_error.json
```

**Expected**:
- ✅ Clear error message
- ✅ Suggests available node types
- ✅ No stack traces in default mode

### Test 8.2: Verbose Error Details
**Purpose**: Verify --verbose shows technical details

**Execute**:
```bash
uv run pflow --verbose /tmp/test_error.json
```

**Expected**:
- ✅ Shows additional technical details
- ✅ May include debug information
- ✅ Still user-friendly primary message

### Test 8.3: Missing Parameter Errors
**Purpose**: Verify parameter validation messages

**Execute**:
```bash
uv run pflow "send email to user@example.com"
```

**Expected** (if no email node available):
- ✅ Clear message about missing capability
- ✅ Suggestions for alternative approaches
- ✅ No internal error details

---

## Section 9: Named Workflows

### Test 9.1: Named Workflow Progress
**Purpose**: Verify progress shows for saved workflows

**Setup**:
```bash
# Save a test workflow
uv run pflow "echo hello from saved workflow"
# When prompted, save as: test-saved
```

**Execute**:
```bash
uv run pflow test-saved
```

**Expected**:
- ✅ Shows "Executing workflow (X nodes):"
- ✅ Shows node progress indicators
- ✅ Shows result

### Test 9.2: Named Workflow with -p Flag
**Purpose**: Verify -p flag works with named workflows

**Execute**:
```bash
uv run pflow -p test-saved
```

**Expected**:
- ✅ NO progress indicators
- ✅ Only shows result

---

## Section 10: Edge Cases

### Test 10.1: Rapid Execution
**Purpose**: Verify fast nodes still show progress

**Create test**:
```bash
cat > /tmp/test_fast.json << 'EOF'
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "fast1", "type": "shell", "params": {"command": "true"}},
    {"id": "fast2", "type": "shell", "params": {"command": "true"}},
    {"id": "fast3", "type": "shell", "params": {"command": "true"}}
  ],
  "edges": [
    {"from": "fast1", "to": "fast2"},
    {"from": "fast2", "to": "fast3"}
  ]
}
EOF
```

**Execute**:
```bash
uv run pflow /tmp/test_fast.json
```

**Expected**:
- ✅ Shows progress even for sub-100ms nodes
- ✅ Duration shows as "✓ 0.0s" or "✓ 0.1s"

### Test 10.2: Unicode and Special Characters
**Purpose**: Verify progress symbols display correctly

**Execute**:
```bash
uv run pflow "echo 'Test Unicode output'"
```

**Expected**:
- ✅ Progress checkmarks (✓) display correctly
- ✅ Results preserved accurately
- ✅ No encoding errors

**Note**: Windows-specific edge cases (sys.stdin/stdout being None) are handled in the code but don't need manual testing on non-Windows platforms.

---

## Section 11: Performance & Stress Testing

### Test 11.1: Large Workflow Progress
**Purpose**: Verify progress for workflows with many nodes

**Create large workflow**:
```bash
cat > /tmp/test_large.json << 'EOF'
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "n1", "type": "shell", "params": {"command": "echo '1'"}},
    {"id": "n2", "type": "shell", "params": {"command": "echo '2'"}},
    {"id": "n3", "type": "shell", "params": {"command": "echo '3'"}},
    {"id": "n4", "type": "shell", "params": {"command": "echo '4'"}},
    {"id": "n5", "type": "shell", "params": {"command": "echo '5'"}}
  ],
  "edges": [
    {"from": "n1", "to": "n2"},
    {"from": "n2", "to": "n3"},
    {"from": "n3", "to": "n4"},
    {"from": "n4", "to": "n5"}
  ]
}
EOF
```

**Execute**:
```bash
uv run pflow /tmp/test_large.json
```

**Expected**:
- ✅ Shows "Executing workflow (5 nodes):"
- ✅ Progress for each node visible
- ✅ No performance degradation

### Test 11.2: Concurrent Output Test
**Purpose**: Verify stderr/stdout separation

**Execute**:
```bash
uv run pflow /tmp/test_simple.json 2>/dev/null
```

**Expected**:
- ✅ Only "Hello from workflow" visible (progress went to stderr)

**Execute**:
```bash
uv run pflow /tmp/test_simple.json 2>&1 | grep "Executing"
```

**Expected**:
- ✅ Can filter for progress messages when redirecting stderr to stdout

---

## Regression Testing Checklist

After completing all tests above, verify these critical scenarios still work:

### ✅ Core Functionality
- [x] Basic workflow execution works
- [x] Natural language planning works
- [x] JSON output format works
- [x] Workflow saving/loading works
- [x] Registry commands work
- [x] MCP commands work (if configured)

### ✅ Backwards Compatibility
- [x] Existing workflows still execute
- [x] Old error messages still appear (for non-improved errors)
- [x] JSON output structure unchanged
- [x] Exit codes unchanged

### ✅ No Performance Regression
- [x] Planner responds within normal time
- [x] No noticeable execution slowdown
- [x] Progress callbacks don't delay execution

---

## Expected Test Report Format

**IMPORTANT**: After executing ALL tests, the AI agent (or human tester) must produce a **complete and detailed report** documenting:

### 1. Executive Summary
- Total tests executed
- Pass/fail counts
- Critical issues found
- Deployment readiness assessment

### 2. Detailed Test Results
For EACH test executed, document:
- Test ID and name
- Command executed
- Expected behavior (from plan)
- Actual behavior observed
- Pass/Fail status
- Screenshots or exact output when relevant

### 3. Failure Analysis
For ANY test that failed or showed unexpected behavior:
- Exact command that failed
- Complete error message or unexpected output
- Analysis of why it might have failed
- Potential impact on users
- Suggested fix or workaround

### 4. Test Report Template

```markdown
# Task 55 Manual Testing Report - [DATE]

## Executive Summary
**Testing Completed**: [DATE and TIME]
**Tester**: [AI Agent ID or Human Name]
**Environment**: macOS/Linux, Python [version], Terminal [type]
**Overall Result**: ✅ PASS with minor issues / ⚠️ FAIL - blocking issues found

**Statistics**:
- Total tests planned: 50+
- Tests executed: [number]
- Tests passed: [number]
- Tests failed: [number]
- Tests skipped: [number] (e.g., MCP tests without MCP setup)

## Section-by-Section Results

### Section 1: Interactive vs Non-Interactive Mode (5 tests)

#### Test 1.1: Terminal Mode (Interactive)
**Command**: `uv run pflow /tmp/test_simple.json`
**Expected**: Shows progress indicators and result
**Actual**: [EXACT OUTPUT OBSERVED]
**Result**: ✅ PASS / ❌ FAIL
**Notes**: [Any observations]

#### Test 1.2: Piped Stdin (Non-Interactive)
**Command**: `echo "test" | uv run pflow /tmp/test_simple.json`
**Expected**: No progress, only result
**Actual**: [EXACT OUTPUT]
**Result**: ✅ PASS / ❌ FAIL
**Notes**: [Any observations]

[Continue for EVERY test...]

### Section 2: CLI Flags (4 tests)
[Document each test with same detail level]

### Section 3: Planner Progress (3 tests)
[Document each test]

[Continue through all 11 sections...]

## Critical Issues Found

### Issue #1: [Title]
**Severity**: High/Medium/Low
**Test**: [Which test exposed this]
**Description**: [Detailed description]
**Steps to Reproduce**:
1. [Step 1]
2. [Step 2]
**Expected**: [What should happen]
**Actual**: [What actually happened]
**Impact**: [User impact]
**Suggested Fix**: [If applicable]

### Issue #2: [Title]
[Same format...]

## Unexpected Behaviors (Non-Critical)

### Behavior #1: [Title]
**Test**: [Which test]
**Description**: [What was unexpected but not breaking]
**Impact**: Minor/None

## Performance Observations

- Planner response time: [typical duration]
- Node execution overhead: [observed overhead]
- Progress display latency: [any lag noticed]

## Regression Check Results

✅ Basic workflow execution: WORKING
✅ Natural language planning: WORKING
✅ JSON output format: WORKING
✅ Workflow saving/loading: WORKING
✅ Registry commands: WORKING
⚠️ MCP commands: NOT TESTED (no MCP setup)

## Deployment Readiness

### Ready for Production: YES / NO

**Justification**:
[Explain why the code is or isn't ready for deployment based on test results]

**Blocking Issues**:
1. [Any issue that must be fixed before deployment]
2. [Another blocking issue]

**Non-Blocking Issues** (can be fixed post-deployment):
1. [Minor issue]
2. [Another minor issue]

## Test Coverage Gaps

**Tests Not Executed**:
- [Test name] - Reason: [why skipped]
- MCP tests - Reason: No MCP servers configured

**Additional Tests Recommended**:
- [Suggested additional test]
- [Another suggestion]

## Raw Test Outputs

### Appendix A: Interactive Mode Test Outputs
```
[Paste actual terminal output for reference]
```

### Appendix B: Non-Interactive Mode Test Outputs
```
[Paste actual piped output for reference]
```

### Appendix C: Error Messages Observed
```
[Paste any error messages encountered]
```

## Conclusion

[Summary paragraph describing overall test results, confidence level, and recommendation for next steps]

---
Report generated by: [AI Agent/Human]
Date: [DATE]
Time taken: [Duration of testing]
```

---

## Notes for Testers

1. **Terminal vs Pipe Detection**: The key behavior difference is based on TTY detection. Use real terminal for interactive tests, use pipes (`|`) for non-interactive.

2. **Progress Timing**: Progress durations will vary based on system load. The important thing is that they appear in interactive mode and don't appear in non-interactive mode.

3. **MCP Testing**: Many MCP tests will show errors if MCP servers aren't configured. This is expected behavior - the important part is that the errors are user-friendly.

4. **File Cleanup**: Tests create files in /tmp/ which can be cleaned up after testing:
   ```bash
   rm -f /tmp/test_*.json /tmp/test_output.txt
   ```

5. **Debugging**: If unexpected behavior occurs:
   - Add `-v` flag for verbose output
   - Check stderr separately: `2>&1`
   - Use `--trace` to capture execution details
   - Check ~/.pflow/debug/ for trace files

---

This testing plan covers all aspects of Task 55 implementation. Execute each section systematically and document any deviations from expected behavior.