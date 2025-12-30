# CLAUDE.md - Git Node Development Guide

## ⚠️ CRITICAL LIMITATIONS

1. **OPERATES ONLY ON CURRENT DIRECTORY**: Git nodes work ONLY in the directory where pflow is executed. Cannot target other repositories!
2. **NO JSON OUTPUT**: Git commands don't support JSON. Must parse text formats (porcelain, etc.)
3. **EXIT CODES HAVE MEANING**: Exit code 1 might mean "nothing to commit" (not an error)
4. **STATE-DEPENDENT**: Many operations require specific working tree state (clean, no conflicts, etc.)
5. **NO REMOTE OPERATIONS**: Cannot clone, fetch from, or operate on remote repos directly

## 🎯 Core Purpose

These nodes wrap native Git commands to provide version control operations within pflow workflows. They enable:
- Checking repository status
- Creating commits
- Pushing to remotes
- Managing branches (future)
- Stashing changes (future)

**Critical Design Gap**: These nodes lack a `working_directory` parameter, limiting them to the current directory. This is a known limitation that needs future enhancement.

## 🚨 Common Pitfalls

### 1. Assuming Remote Repository Operations
```python
# WRONG - Cannot operate on remote repos
def prep(self, shared):
    repo_path = shared.get("repo_path")  # NO! Can't change directory
    return {"repo": repo_path}

# RIGHT - Always operates on current directory
def prep(self, shared):
    # No directory parameter - always uses os.getcwd()
    return {}

# FUTURE - When working_directory is added
def prep(self, shared):
    working_dir = shared.get("working_directory", os.getcwd())
    return {"cwd": working_dir}
```

### 2. Expecting JSON Output
```python
# WRONG - Git doesn't support JSON
cmd = ["git", "status", "--json"]  # DOESN'T EXIST

# RIGHT - Use porcelain format for parsing
cmd = ["git", "status", "--porcelain=v2"]
# Returns machine-readable format:
# 1 .M N... 100644 100644 100644 abc123 def456 file.py
```

### 3. Treating Exit Code 1 as Error
```python
# WRONG - Exit code 1 might be normal
result = subprocess.run(["git", "commit", "-m", "msg"])
if result.returncode != 0:
    raise ValueError("Commit failed!")  # But maybe nothing to commit?

# RIGHT - Check stderr for actual errors
result = subprocess.run(["git", "commit", "-m", "msg"], capture_output=True, text=True)
if result.returncode != 0:
    if "nothing to commit" in result.stdout:
        return {"status": "nothing_to_commit", "sha": None}
    else:
        raise ValueError(f"Commit failed: {result.stderr}")
```

### 4. Not Checking Repository State
```python
# WRONG - Assuming we're in a git repo
cmd = ["git", "status"]

# RIGHT - Handle "not a git repository" gracefully
result = subprocess.run(cmd, capture_output=True, text=True)
if "not a git repository" in result.stderr:
    raise ValueError("Not in a git repository. Navigate to a git repository before running this workflow.")
```

## ✅ Required Patterns

### 1. Porcelain Format Parsing Pattern
```python
def exec(self, prep_res):
    cmd = ["git", "status", "--porcelain=v2", "--branch"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        if "not a git repository" in result.stderr:
            raise ValueError("Not in a git repository")
        raise ValueError(f"Git command failed: {result.stderr}")

    # Parse porcelain output
    status = {
        "modified": [],
        "staged": [],
        "untracked": [],
        "branch": "unknown",
        "ahead": 0,
        "behind": 0
    }

    for line in result.stdout.strip().split('\n'):
        if line.startswith("# branch.head"):
            status["branch"] = line.split()[-1]
        elif line.startswith("# branch.ab"):
            parts = line.split()
            status["ahead"] = int(parts[2].lstrip('+'))
            status["behind"] = abs(int(parts[3]))
        elif line.startswith("1") or line.startswith("2"):
            # File status line
            parts = line.split()
            xy_status = parts[1]
            filepath = parts[-1]

            if 'M' in xy_status[1]:  # Modified in working tree
                status["modified"].append(filepath)
            if xy_status[0] != '.':  # Staged
                status["staged"].append(filepath)
        elif line.startswith("?"):
            # Untracked file
            filepath = line.split()[-1]
            status["untracked"].append(filepath)

    return status
```

### 2. Commit SHA Extraction Pattern
```python
def exec(self, prep_res):
    # Stage files
    files = prep_res["files"]
    for file in files:
        cmd = ["git", "add", file]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise ValueError(f"Failed to stage {file}: {result.stderr}")

    # Commit
    cmd = ["git", "commit", "-m", prep_res["message"]]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        if "nothing to commit" in result.stdout:
            return {"status": "nothing_to_commit", "sha": None}
        raise ValueError(f"Commit failed: {result.stderr}")

    # Extract SHA from output like: [main abc123] Commit message
    import re
    match = re.search(r'\[[\w\-/]+ ([a-f0-9]+)\]', result.stdout)
    if match:
        sha = match.group(1)
    else:
        # Fallback: get SHA with rev-parse
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
        sha = result.stdout.strip()

    return {"sha": sha, "message": prep_res["message"]}
```

### 3. Working Directory Documentation Pattern
```python
"""
Get git repository status.

NOTE: Operates only on the current directory where pflow is executed.
TODO: Future enhancement - add working_directory parameter.

Interface:
- Writes: shared["git_status"]: dict  # Repository status information
    - modified: list[str]  # Modified files
    - untracked: list[str]  # Untracked files
    - staged: list[str]  # Staged files
    - branch: str  # Current branch name
    - ahead: int  # Commits ahead of remote
    - behind: int  # Commits behind remote
- Actions: default (always)
"""
```

### 4. Idempotent Operations Pattern
```python
def exec(self, prep_res):
    # Make operations idempotent where possible
    cmd = ["git", "push", prep_res["remote"], prep_res["branch"]]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        if "Everything up-to-date" in result.stderr or "Everything up-to-date" in result.stdout:
            # Already pushed - this is success!
            return {"success": True, "message": "Already up-to-date"}
        elif "rejected" in result.stderr:
            # Non-fast-forward push
            raise ValueError("Push rejected: Remote has changes. Pull first or force push.")
        else:
            raise ValueError(f"Push failed: {result.stderr}")

    return {"success": True, "message": "Pushed successfully"}
```

## 🔒 Security Requirements

1. **ALWAYS use `shell=False`** in subprocess.run()
2. **Validate file paths** to prevent directory traversal
3. **Set timeout=30** to prevent hanging on network operations
4. **Never include credentials** in commands (use SSH keys or credential helpers)
5. **Sanitize commit messages** to prevent command injection
6. **Log commands at debug level** but redact sensitive data

## 📝 Interface Documentation Rules

```python
"""
Create a git commit.

NOTE: Operates only on the current directory where pflow is executed.
TODO: Future enhancement - add working_directory parameter.

Interface:
- Reads: shared["message"]: str  # Commit message
- Reads: shared["files"]: list[str]  # Files to add (optional, default: ["."])
- Writes: shared["commit_sha"]: str  # Commit SHA
- Writes: shared["commit_message"]: str  # Commit message (echoed)
- Actions: default (always)
"""
```

**Critical Rules**:
1. Always note the directory limitation
2. Include TODO for working_directory parameter
3. Use double quotes: `shared["key"]`
4. Don't document automatic param fallback

## 🧪 Testing Strategy

### Unit Tests (Required)
```python
@patch('subprocess.run')
def test_status_parsing(mock_run):
    # Mock porcelain v2 output
    mock_run.return_value = Mock(
        returncode=0,
        stdout="""# branch.head main
# branch.ab +2 -0
1 .M N... 100644 100644 100644 abc123 def456 file.py
? untracked.txt""",
        stderr=""
    )

    node = GitStatusNode()
    result = node.exec({})

    assert result["branch"] == "main"
    assert result["ahead"] == 2
    assert result["behind"] == 0
    assert "file.py" in result["modified"]
    assert "untracked.txt" in result["untracked"]
```

### Integration Tests (Use Temp Repos)
```python
def test_real_git_operations(tmp_path):
    # Create temporary git repo
    os.chdir(tmp_path)
    subprocess.run(["git", "init"], check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], check=True)
    subprocess.run(["git", "config", "user.name", "Test"], check=True)

    # Test status node
    node = GitStatusNode()
    shared = {}
    node.run(shared)

    assert shared["git_status"]["branch"] in ["main", "master"]
    assert shared["git_status"]["modified"] == []
```

## 🚀 Extension Opportunities

### Implemented Nodes
1. **git-status**: Get repository status
2. **git-commit**: Create commits
3. **git-push**: Push to remote
4. **git-checkout**: Switch/create branches
5. **git-log**: Get commit history
6. **git-get-latest-tag**: Get the most recent tag ✅ (NEW)

### High-Priority Nodes to Add
1. **git-tag-create**: Create new tags (annotated or lightweight)
2. **git-tag-list**: List all tags with filtering
3. **git-tag-push**: Push tags to remote
4. **git-clone**: Clone repository (would change working directory!)
5. **git-branch**: List/manage branches
6. **git-pull**: Pull from remote
7. **git-merge**: Merge branches
8. **git-stash**: Stash changes
9. **git-rebase**: Rebase branches

### Working Directory Parameter Pattern
```python
# Standard pattern for all git nodes
def prep(self, shared):
    working_dir = self.params.get("working_directory")
    if working_dir:
        working_dir = os.path.abspath(os.path.expanduser(working_dir))
        if not os.path.isdir(working_dir):
            raise ValueError(f"Directory not found: {working_dir}")
    else:
        working_dir = os.getcwd()

    return {"cwd": working_dir}

def exec(self, prep_res):
    cmd = ["git", "status", "--porcelain=v2"]
    # Use cwd parameter in subprocess
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=prep_res["cwd"])
```

## 💡 Quick Reference

### Common Git Commands
```bash
# Status and Info
git status --porcelain=v2 --branch
git log --oneline -n 10
git branch --list
git remote -v

# Making Changes
git add .
git add file1 file2
git commit -m "Message"
git commit --amend -m "New message"

# Working with Remotes
git push origin main
git pull origin main
git fetch --all

# Branches
git checkout -b new-branch
git checkout main
git merge feature-branch
git rebase main
```

### Porcelain v2 Format Guide
```
# Header lines (start with #)
# branch.head main
# branch.upstream origin/main
# branch.ab +1 -0  (ahead/behind)

# File status lines
1 XY sub mH mI mW hH hI path
  X: staged status
  Y: unstaged status

Status codes:
M = modified
A = added
D = deleted
R = renamed
C = copied
. = unchanged
```

### Exit Codes
- 0: Success
- 1: General error OR nothing to commit (check output!)
- 128: Invalid command/option
- 129: Usage/help message

## ⚡ Performance Considerations

- Git operations are generally fast (<50ms for status)
- Network operations (push/pull) can be slow (use 30s timeout)
- Large repos may need longer timeouts
- Consider using `--no-pager` for log commands

## 🔄 Common Workflow Patterns

### Automated Commit & Push
1. `git-status` → Check for changes
2. `llm` → Generate commit message
3. `git-commit` → Commit changes
4. `git-push` → Push to remote

### Safety Check Before Operations
1. `git-status` → Ensure clean working tree
2. `git-pull` → Get latest changes
3. [Make changes]
4. `git-commit` → Commit
5. `git-push` → Push

## ⚠️ Current Limitations Summary

**The Big One**: These nodes can ONLY operate on the current directory where pflow is executed. This means:
- Cannot clone repos to specific locations
- Cannot work on multiple repos in one workflow
- Cannot target repos by path

**Workaround**: Run pflow from the target repository directory.

**Future Fix**: Add `working_directory` parameter to all git nodes, allowing operations on any local repository.

Remember: Document this limitation clearly in any workflow that uses git nodes!
