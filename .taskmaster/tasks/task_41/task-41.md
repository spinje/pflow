# Task 41: Implement Shell Node

## ID
41

## Title
Implement Shell Node

## Description
Create a shell node that allows users to execute arbitrary shell commands within pflow workflows, providing an escape hatch for operations not covered by domain-specific nodes. This enables integration with existing tools, rapid prototyping, and handling the long tail of automation needs without waiting for dedicated nodes to be created.

## Status
not started

## Dependencies
- Task 6: Define JSON IR schema - The shell node must conform to the established IR schema for nodes
- Task 11: Implement read-file and write-file nodes - Shell node follows similar patterns for parameter handling and shared store usage
- Task 16: Create planning context builder - Context builder needs to understand shell node's capabilities for natural language planning

## Priority
medium

## Details
The Shell Node will provide controlled access to shell command execution within pflow workflows. Based on our discussion, we identified that without a shell node, pflow becomes a walled garden that only supports pre-built operations, severely limiting its usefulness for real-world automation.

### Key Design Decisions (MVP Approach)
- **Safety by default**: Safe mode restricts to read-only commands unless explicitly disabled
- **No shell expansion**: Use `shell=False` in subprocess to prevent injection attacks
- **Structured output support**: Parse output as text, JSON, lines, or CSV based on `parse_as` parameter
- **Simple allowlist**: In safe mode, only permit known-safe commands (git, npm, docker, terraform with read-only flags)
- **Output limits**: Cap output at 100KB to prevent memory issues
- **30-second timeout**: Prevent hanging commands

### Interface Design
```python
Interface:
- Reads: shared["command"]: str  # Command to execute
- Reads: shared["parse_as"]: str  # Output format: "text", "json", "lines", "csv" (optional, default: text)
- Reads: shared["safe_mode"]: bool  # Restrict to read-only commands (optional, default: true)
- Reads: shared["working_directory"]: str  # Directory to run command (optional, default: current)
- Writes: shared["output"]: Any  # Command output (format depends on parse_as)
- Writes: shared["exit_code"]: int  # Command exit code
- Writes: shared["stderr"]: str  # Error output if any
```

### Safe Mode Allowlist (MVP)
When `safe_mode=true` (default), only allow:
- Read-only git commands (log, status, diff, show)
- npm/yarn list, audit, outdated (no install/run)
- docker ps, images, logs (no run/exec)
- terraform plan, show (no apply/destroy)
- curl/wget with GET only
- Standard Unix tools: ls, cat, grep, find, ps, df, du

### Parse Modes
- **text**: Return raw stdout as string
- **json**: Parse as JSON, error if invalid
- **lines**: Split output into array of lines
- **csv**: Parse as CSV into array of dicts

### Example Use Cases
```bash
# Quick prototype
shell --command="git log --oneline -5" --parse_as="lines"

# JSON-output commands
shell --command="npm list --json" --parse_as="json"

# Integration with existing scripts
shell --command="./scripts/analyze.sh" --safe_mode=false
```

### Technical Considerations
- Must follow PocketFlow retry pattern (let exceptions bubble up)
- Inherit from Node with max_retries=2 for transient failures
- Log commands executed for audit trail
- Sanitize command in error messages to avoid leaking secrets
- Consider adding `stdin` support in future (post-MVP)

## Test Strategy
Comprehensive testing focusing on security and reliability:

### Unit Tests
- Test safe mode allowlist enforcement
- Test each parse_as mode with valid and invalid output
- Test timeout handling
- Test output size limits
- Test working directory changes
- Test parameter validation

### Security Tests
- Verify shell injection prevention
- Test safe mode restrictions
- Ensure no shell expansion occurs
- Test with malicious command attempts

### Integration Tests
- Test with real commands (git, npm, etc.)
- Test error handling for missing commands
- Test parse modes with actual tool outputs
- Test within workflow execution

### Edge Cases
- Commands that output to stderr only
- Commands with non-zero exit codes but valid output
- Very large outputs hitting the limit
- Unicode and special characters in output
- Commands that prompt for input (should timeout)