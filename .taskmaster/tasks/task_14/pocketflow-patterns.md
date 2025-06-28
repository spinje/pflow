# PocketFlow Patterns for Task 14: Implement git-commit Node

## Overview

The git-commit node demonstrates patterns for command execution, safety checks, and interactive confirmations. It's part of the git platform nodes that enable version control operations in workflows.

## Relevant Cookbook Examples

- `cookbook/pocketflow-tool-database`: Clean separation of tools and nodes
- `cookbook/pocketflow-workflow`: Multi-step processes with validation

## Patterns to Adopt

### Pattern: Safe Command Execution
**Source**: Best practices for destructive operations
**Compatibility**: ✅ Direct
**Description**: Execute git commands with safety checks

**Implementation for pflow**:
```python
from pocketflow import Node
import subprocess
import os

class GitCommitNode(Node):
    def __init__(self):
        # Git operations are generally reliable
        super().__init__(max_retries=2, wait=0)

    def prep(self, shared):
        # Required: commit message
        message = shared.get("message") or shared.get("commit_message")
        if not message:
            raise ValueError("Missing required input: message or commit_message")

        # Optional: specific files to commit
        files = shared.get("files") or self.params.get("files", [])

        # Safety parameters
        return {
            "message": message,
            "files": files,
            "auto_stage": self.params.get("auto_stage", True),
            "sign_commit": self.params.get("sign_commit", False),
            "interactive": self.params.get("interactive", False),
            "dry_run": self.params.get("dry_run", False)
        }

    def exec(self, prep_res):
        # Check if we're in a git repository
        if not os.path.exists(".git"):
            raise ValueError("Not in a git repository")

        # Auto-stage files if requested
        if prep_res["auto_stage"]:
            if prep_res["files"]:
                # Stage specific files
                for file in prep_res["files"]:
                    self._run_git_command(["add", file])
            else:
                # Stage all changes
                self._run_git_command(["add", "-A"])

        # Check if there's anything to commit
        status = self._run_git_command(["status", "--porcelain"])
        if not status.strip():
            return {"committed": False, "reason": "No changes to commit"}

        # Build commit command
        cmd = ["commit", "-m", prep_res["message"]]

        if prep_res["sign_commit"]:
            cmd.append("-S")

        if prep_res["dry_run"]:
            cmd.append("--dry-run")

        # Execute commit
        output = self._run_git_command(cmd)

        # Get the commit hash
        if not prep_res["dry_run"]:
            commit_hash = self._run_git_command(["rev-parse", "HEAD"]).strip()
            return {
                "committed": True,
                "commit_hash": commit_hash,
                "output": output
            }
        else:
            return {
                "committed": False,
                "reason": "Dry run",
                "output": output
            }

    def _run_git_command(self, args):
        """Execute a git command and return output."""
        cmd = ["git"] + args

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            # Provide helpful error messages
            if "nothing to commit" in e.stderr:
                return ""  # Not an error, just no changes
            elif "not a git repository" in e.stderr:
                raise ValueError("Not in a git repository")
            else:
                raise RuntimeError(f"Git command failed: {e.stderr}")

    def post(self, shared, prep_res, exec_res):
        if exec_res["committed"]:
            shared["commit_hash"] = exec_res["commit_hash"]
            shared["committed"] = True
        else:
            shared["committed"] = False
            shared["commit_reason"] = exec_res["reason"]

        # Store output for debugging
        shared["git_output"] = exec_res.get("output", "")

        return "default"
```

### Pattern: Interactive Confirmation
**Source**: Safety patterns for destructive operations
**Compatibility**: ✅ Direct
**Description**: Optionally confirm before committing

**Interactive mode implementation**:
```python
def exec(self, prep_res):
    if prep_res["interactive"] and not prep_res["dry_run"]:
        # Show what will be committed
        diff = self._run_git_command(["diff", "--cached", "--stat"])
        print(f"\nAbout to commit with message: {prep_res['message']}")
        print(f"Changes to be committed:\n{diff}")

        # Get user confirmation
        response = input("Proceed with commit? [y/N]: ")
        if response.lower() != 'y':
            return {
                "committed": False,
                "reason": "User cancelled"
            }

    # Continue with commit...
```

### Pattern: Subprocess Management
**Source**: Best practices for external commands
**Compatibility**: ✅ Direct
**Description**: Safe execution of system commands

**Key principles**:
```python
# 1. Always use subprocess.run with arrays (no shell=True)
cmd = ["git", "commit", "-m", message]  # Safe from injection

# 2. Capture output for debugging
result = subprocess.run(cmd, capture_output=True, text=True)

# 3. Handle errors gracefully
if result.returncode != 0:
    if "specific error" in result.stderr:
        raise ValueError("Helpful message")
    else:
        raise RuntimeError(f"Command failed: {result.stderr}")

# 4. Never use os.system() or shell=True
```

### Pattern: Flexible Input Keys
**Source**: User convenience patterns
**Compatibility**: ✅ Direct
**Description**: Accept common variations of input keys

**Implementation**:
```python
# Accept multiple common names for the same input
message = (
    shared.get("message") or
    shared.get("commit_message") or
    shared.get("msg")
)

# This accommodates different user preferences:
# pflow git-commit --message="Fix bug"
# pflow git-commit --commit_message="Fix bug"
# Previous node might set shared["message"] or shared["commit_message"]
```

## Patterns to Avoid

### Pattern: Complex Git Operations
**Issue**: Rebasing, merging, cherry-picking
**Alternative**: Keep it simple - just commit

### Pattern: Direct Message Input
**Issue**: Commit messages with special characters
**Alternative**: Always use array form for subprocess

### Pattern: Workspace Manipulation
**Issue**: Changing branches, stashing, etc.
**Alternative**: Single-purpose node - only commit

## Implementation Guidelines

1. **Safety first**: Check repository state before operations
2. **Clear output**: Provide commit hash and status
3. **Flexible inputs**: Accept common key variations
4. **Good defaults**: Auto-stage changes by default
5. **Subprocess safety**: Never use shell=True

## Usage Examples

### Example 1: Simple Commit
```bash
# CLI usage
pflow git-commit --message="Fix authentication bug"

# In workflow
llm --prompt="Write commit message for: $code_changes" >> \
git-commit --auto_stage=true
```

### Example 2: Commit Specific Files
```python
shared = {
    "message": "Update documentation",
    "files": ["README.md", "docs/guide.md"]
}

node = GitCommitNode()
node.set_params({"auto_stage": True})
node.run(shared)

# Result:
# shared["commit_hash"] = "abc123..."
# shared["committed"] = True
```

### Example 3: Dry Run Mode
```python
# Test what would be committed
node = GitCommitNode()
node.set_params({"dry_run": True})

shared = {"message": "Test commit"}
node.run(shared)

# shared["committed"] = False
# shared["commit_reason"] = "Dry run"
# shared["git_output"] = (shows what would be committed)
```

## Testing Approach

```python
import pytest
from unittest.mock import patch, MagicMock
import tempfile
import os

def test_git_commit_success():
    node = GitCommitNode()

    # Mock git commands
    with patch.object(node, '_run_git_command') as mock_git:
        # Setup mock returns
        mock_git.side_effect = [
            "",  # add command (no output)
            "M file.txt",  # status --porcelain
            "1 file changed",  # commit output
            "abc123def456"  # rev-parse HEAD
        ]

        shared = {"message": "Test commit"}
        node.run(shared)

    assert shared["committed"] == True
    assert shared["commit_hash"] == "abc123def456"

def test_nothing_to_commit():
    node = GitCommitNode()

    with patch.object(node, '_run_git_command') as mock_git:
        mock_git.side_effect = [
            "",  # add command
            "",  # status --porcelain (nothing staged)
        ]

        shared = {"message": "Test commit"}
        node.run(shared)

    assert shared["committed"] == False
    assert shared["commit_reason"] == "No changes to commit"

def test_not_in_git_repo():
    node = GitCommitNode()

    with patch('os.path.exists', return_value=False):
        shared = {"message": "Test"}

        with pytest.raises(ValueError, match="Not in a git repository"):
            node.run(shared)

def test_with_real_git_repo():
    """Integration test with real git repo"""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        # Initialize repo
        subprocess.run(["git", "init"], check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"])
        subprocess.run(["git", "config", "user.name", "Test User"])

        # Create a file
        with open("test.txt", "w") as f:
            f.write("test content")

        # Run node
        node = GitCommitNode()
        shared = {"message": "Initial commit"}
        node.run(shared)

        assert shared["committed"] == True
        assert len(shared["commit_hash"]) == 40  # Valid SHA
```

This git-commit node provides safe, flexible version control operations within pflow workflows.
