# Task 41: Implement Shell Node

## Description
Create a shell node that executes shell commands within pflow workflows. This provides the essential escape hatch for operations not covered by domain-specific nodes, enabling integration with any CLI tool, Unix pipelines, and existing scripts.

## Status
done

## Completed
2025-08-25

## Dependencies
- Task 6: Define JSON IR schema - The shell node must conform to the established IR schema
- Task 9: Implement shared store collision detection - Shell node must use namespacing for inputs/outputs
- Task 11: Implement read-file and write-file nodes - Follow similar patterns for node implementation

## Priority
high (changed from medium - this is critical for MVP usefulness)

## Details

### Core Design Principle
The Shell Node is `subprocess.run()` with workflow integration. Nothing more, nothing less. Complexity belongs in composition, not in the node itself.

### Key Design Decisions (Simplified MVP)
- **shell=True by default**: Users expect shell features (pipes, globs, env vars)
- **Clear security warning**: Make dangers explicit, let users decide
- **Namespaced I/O**: Prevent collisions when multiple shell nodes exist
- **Configurable limits**: Timeout and output size caps
- **Audit logging**: Log all executed commands for transparency
- **No parsing**: Output text only, let other nodes handle structure

### Interface Design (Namespaced)
```python
Interface:
- Reads: shared[f"{node_id}.command"]: str  # Shell command to execute
- Reads: shared[f"{node_id}.cwd"]: str  # Working directory (optional)
- Reads: shared[f"{node_id}.env"]: dict  # Environment variables (optional)
- Reads: shared[f"{node_id}.timeout"]: int  # Timeout in seconds (optional, default: 30)
- Reads: shared[f"{node_id}.max_output"]: int  # Max output bytes (optional, default: 100000)
- Reads: shared[f"{node_id}.ignore_errors"]: bool  # Continue on non-zero exit (optional, default: false)

- Writes: shared[f"{node_id}.stdout"]: str  # Standard output
- Writes: shared[f"{node_id}.stderr"]: str  # Standard error
- Writes: shared[f"{node_id}.returncode"]: int  # Exit code
```

### Implementation (MVP)
```python
class ShellNode(Node):
    """Execute shell commands. Power and responsibility."""

    def prep(self, shared: dict) -> dict:
        # Get namespaced parameters
        node_id = self.id  # Provided by framework
        command = shared.get(f"{node_id}.command", shared.get("command"))  # Fallback for compatibility

        if not command:
            raise ValueError("Shell node requires 'command' parameter")

        # Log for audit trail
        logger.info(f"Shell node {node_id} will execute: {command[:100]}...")

        return {
            "command": command,
            "cwd": shared.get(f"{node_id}.cwd"),
            "env": shared.get(f"{node_id}.env", {}),
            "timeout": shared.get(f"{node_id}.timeout", 30),
            "max_output": shared.get(f"{node_id}.max_output", 100000),
            "ignore_errors": shared.get(f"{node_id}.ignore_errors", False)
        }

    def exec(self, prep_result: dict) -> dict:
        import subprocess
        import os

        # Merge environment variables
        env = {**os.environ, **prep_result["env"]}

        try:
            result = subprocess.run(
                prep_result["command"],
                shell=True,  # Yes, intentionally - users need pipes, globs, etc.
                capture_output=True,
                text=True,
                timeout=prep_result["timeout"],
                cwd=prep_result["cwd"],
                env=env
            )

            # Truncate output if needed
            stdout = result.stdout[:prep_result["max_output"]]
            if len(result.stdout) > prep_result["max_output"]:
                stdout += "\n... [Output truncated]"

            return {
                "stdout": stdout,
                "stderr": result.stderr[:prep_result["max_output"]],
                "returncode": result.returncode,
                "success": result.returncode == 0 or prep_result["ignore_errors"]
            }

        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": f"Command timed out after {prep_result['timeout']} seconds",
                "returncode": -1,
                "success": prep_result["ignore_errors"]
            }

    def post(self, shared: dict, prep_result: dict, exec_result: dict) -> str:
        node_id = self.id

        # Write namespaced outputs
        shared[f"{node_id}.stdout"] = exec_result["stdout"]
        shared[f"{node_id}.stderr"] = exec_result["stderr"]
        shared[f"{node_id}.returncode"] = exec_result["returncode"]

        # Compatibility: Also write to non-namespaced if no collision
        if "stdout" not in shared:
            shared["stdout"] = exec_result["stdout"]
            shared["stderr"] = exec_result["stderr"]
            shared["returncode"] = exec_result["returncode"]

        # Route based on success
        if not exec_result["success"]:
            return "error"  # Or raise exception based on ignore_errors
        return "next"
```

### Security Model
1. **User Warning**: Display on first use: "Shell nodes can execute any command. Only run workflows from trusted sources."
2. **Audit Log**: All commands logged with timestamp and workflow context
3. **Resource Limits**: Timeout and output size prevent resource exhaustion
4. **Documentation**: Clear security section explaining risks and mitigations

### Example Use Cases
```python
# Simple command
shell_node.command = "ls -la"

# Pipeline with Unix tools
shell_node.command = "git log --oneline | head -10 | grep feat:"

# Integration with existing scripts
shell_node.command = "./deploy.sh production"
shell_node.env = {"API_KEY": "secret"}

# Conditional execution in workflow
shell_node.command = "grep ERROR app.log"
shell_node.ignore_errors = True  # Continue even if grep finds nothing

# Parse structured output with composition
flow = ShellNode("docker ps --format json") >> JSONParseNode() >> ProcessNode()
```

### What We're NOT Building (Yet)
- Safe mode / allowlists (user responsibility)
- Output parsing (use specialized nodes)
- Interactive command support (future)
- Streaming output (future)
- Background execution (future)
- Command builders/templates (use template variables)

### Migration Path
Start with this minimal version, then based on actual usage:
1. Add streaming if users need long-running commands
2. Add template support if users build complex commands
3. Add safety helpers if security becomes issue
4. Never add parsing - keep it composable

## Test Strategy

### Core Tests
```python
def test_basic_execution():
    # Test simple command works
    assert shell("echo hello").stdout == "hello\n"

def test_shell_features():
    # Test pipes work
    assert "txt" in shell("ls | grep txt").stdout

    # Test env vars work
    result = shell("echo $HOME", env={"HOME": "/test"})
    assert "/test" in result.stdout

    # Test glob expansion works
    shell("touch test1.txt test2.txt")
    assert "test1.txt" in shell("ls *.txt").stdout

def test_namespace_isolation():
    # Two shell nodes don't collide
    shared = {}
    node1 = ShellNode(id="shell1")
    node2 = ShellNode(id="shell2")
    # ... verify isolation

def test_timeout():
    # Command times out properly
    result = shell("sleep 60", timeout=1)
    assert result.returncode == -1
    assert "timed out" in result.stderr

def test_output_truncation():
    # Large output gets truncated
    result = shell("cat /dev/urandom | head -c 1000000", max_output=1000)
    assert len(result.stdout) <= 1100  # Some buffer for truncation message

def test_error_handling():
    # Non-zero exit handled properly
    result = shell("exit 1")
    assert result.returncode == 1

    # ignore_errors works
    result = shell("exit 1", ignore_errors=True)
    assert result.success == True
```

### Security Tests
```python
def test_command_logging():
    # Verify commands are logged for audit
    with capture_logs() as logs:
        shell("echo test")
        assert "will execute: echo test" in logs

def test_no_secret_leaking():
    # Secrets don't appear in error messages
    result = shell("fake_command --password=secret")
    assert "secret" not in str(result)
```

### Integration Tests
- Test within actual workflow execution
- Test with real CLI tools (git, docker, npm)
- Test working directory changes
- Test environment variable propagation

## Success Criteria
- Can execute any shell command a user would run manually
- Supports pipes, redirects, globs, env vars
- Properly isolated when multiple instances exist
- Clear about security implications
- Ships in 2 hours, not 2 weeks

## Note on Simplicity
This node does ONE thing: execute shell commands. It doesn't parse output, validate commands, or enforce security policies. Those concerns belong elsewhere in the system. This follows the Unix philosophy: do one thing well.

The power comes from composition:
```python
ShellNode("cat data.csv") >> CSVParseNode() >> AnalyzeNode()
ShellNode("git status --json") >> JSONParseNode() >> ConditionalNode()
```

Not from a complex shell node trying to be everything.
