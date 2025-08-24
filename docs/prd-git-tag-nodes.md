# Product Requirements Document: Git Tag Nodes

## Executive Summary

This PRD defines the implementation of git tag operations for pflow, enabling workflows to interact with git tags for release management, changelog generation, and version tracking. Following pflow's single-purpose node philosophy, we propose implementing focused nodes for specific tag operations.

## Background & Motivation

### Current State
- Git operations are partially implemented (status, commit, push, checkout, log)
- North star examples require tag operations for changelog generation
- Test files reference git-tag as a planned node
- Workflow generator tests mock git-tag functionality

### Problem Statement
Without git tag operations, pflow cannot:
1. Generate changelogs since the last release
2. Automate version-based workflows
3. Create release tags as part of CI/CD pipelines
4. Track project versions programmatically

### Use Cases from North Star Examples

1. **Changelog Generation** (Primary)
   ```bash
   # Get commits since last release
   git-get-latest-tag >>
   git-log --since="${tag}" >>
   llm --prompt="Generate changelog from ${commits}"
   ```

2. **Release Notes Creation**
   ```bash
   # Create release with tag
   git-tag-create --name="v${version}" --message="Release ${version}" >>
   git-push-tags >>
   github-create-release --tag="${tag_name}"
   ```

3. **Version-based Filtering**
   ```bash
   # Get issues since last version
   git-get-latest-tag >>
   github-list-issues --since="${tag_date}"
   ```

## Design Decision: Multiple Single-Purpose Nodes

Following pflow's established patterns and philosophy:

### ✅ **Recommended Approach: Multiple Focused Nodes**

Implement separate nodes for distinct operations:
1. `git-tag-list` - List all tags
2. `git-tag-create` - Create a new tag
3. `git-get-latest-tag` - Get the most recent tag (HIGH PRIORITY)
4. `git-tag-push` - Push tags to remote
5. `git-tag-delete` - Delete a tag (future)

**Rationale**:
- Aligns with single-purpose node philosophy
- Consistent with existing git nodes (git-status, git-commit, etc.)
- Clear, predictable interfaces
- Easy to compose in workflows
- No action-based dispatch complexity

### ❌ **Rejected Alternative: Single Mega Node**

A single `git-tag` node with action parameter:
```bash
git-tag --action=list
git-tag --action=create --name="v1.0"
```

**Why Rejected**:
- Violates single-purpose principle
- Complex parameter validation
- Harder to understand and document
- Inconsistent with existing patterns

## Detailed Node Specifications

### 1. git-get-latest-tag (Priority: HIGH 🔴)

**Purpose**: Retrieve the most recent tag from the repository

**Interface**:
```python
"""
Get the latest git tag from the repository.

Interface:
- Reads: shared["pattern"]: str  # Tag pattern filter (optional, e.g., "v*")
- Reads: shared["working_directory"]: str  # Directory to run git commands (optional, default: current)
- Writes: shared["latest_tag"]: dict  # Latest tag information
    - name: str  # Tag name (e.g., "v1.2.3")
    - sha: str  # Commit SHA the tag points to
    - date: str  # Tag/commit date (ISO format)
    - message: str  # Tag message (if annotated)
- Actions: default (always)

Note:
    Returns empty dict if no tags exist.
    For lightweight tags, message will be empty.
"""
```

**Implementation**:
```bash
# Get latest tag
git describe --tags --abbrev=0

# Get tag details
git show-ref --tags -d | grep "^$(git rev-list -n 1 <tag>)"
git log -1 --format=%ai <tag>  # Get date
```

**Error Handling**:
- No tags exist → Return empty dict with success
- Not a git repository → ValueError
- Invalid pattern → ValueError

### 2. git-tag-list (Priority: MEDIUM 🟡)

**Purpose**: List all tags with optional filtering

**Interface**:
```python
"""
List git tags from the repository.

Interface:
- Reads: shared["pattern"]: str  # Pattern filter (optional, e.g., "v*")
- Reads: shared["sort"]: str  # Sort order: version, date (optional, default: version)
- Reads: shared["limit"]: int  # Maximum tags to return (optional, default: 20)
- Reads: shared["working_directory"]: str  # Directory to run git commands (optional)
- Writes: shared["tags"]: list[dict]  # List of tag objects
    - name: str  # Tag name
    - sha: str  # Commit SHA
    - date: str  # Tag/commit date (ISO format)
    - message: str  # Tag message (if annotated)
- Actions: default (always)
"""
```

**Implementation**:
```bash
# List tags with pattern
git tag -l "v*" --sort=-version:refname

# Get details for each tag
git for-each-ref --format='%(refname:short)|%(objectname)|%(creatordate:iso)|%(contents:subject)' refs/tags
```

### 3. git-tag-create (Priority: MEDIUM 🟡)

**Purpose**: Create a new git tag

**Interface**:
```python
"""
Create a git tag.

Interface:
- Reads: shared["tag_name"]: str  # Tag name (required)
- Reads: shared["message"]: str  # Tag message (optional, creates annotated tag if provided)
- Reads: shared["commit"]: str  # Commit to tag (optional, default: HEAD)
- Reads: shared["force"]: bool  # Force create even if tag exists (optional, default: false)
- Reads: shared["working_directory"]: str  # Directory to run git commands (optional)
- Writes: shared["created_tag"]: dict  # Created tag information
    - name: str  # Tag name
    - sha: str  # Tagged commit SHA
    - annotated: bool  # Whether tag is annotated
    - message: str  # Tag message (if annotated)
- Actions: default (always)
"""
```

**Implementation**:
```bash
# Lightweight tag
git tag v1.0.0

# Annotated tag
git tag -a v1.0.0 -m "Release version 1.0.0"

# Tag specific commit
git tag v1.0.0 abc1234

# Force tag
git tag -f v1.0.0
```

**Validation**:
- Tag name must be valid (no spaces, special chars)
- Check if tag already exists (unless force=true)
- Verify commit exists (if specified)

### 4. git-tag-push (Priority: LOW 🟢)

**Purpose**: Push tags to remote repository

**Interface**:
```python
"""
Push git tags to remote.

Interface:
- Reads: shared["tags"]: list[str]  # Specific tags to push (optional, default: all)
- Reads: shared["remote"]: str  # Remote name (optional, default: origin)
- Reads: shared["force"]: bool  # Force push tags (optional, default: false)
- Reads: shared["working_directory"]: str  # Directory to run git commands (optional)
- Writes: shared["pushed_tags"]: list[str]  # Successfully pushed tag names
- Actions: default (always)
"""
```

**Implementation**:
```bash
# Push specific tag
git push origin v1.0.0

# Push all tags
git push origin --tags

# Force push
git push origin v1.0.0 --force
```

## Implementation Guidelines

### 1. Follow Existing Patterns

All nodes must follow patterns from existing git nodes:
- Inherit from `Node` (pocketflow)
- Initialize with `max_retries=2, wait=0.5`
- Implement `prep()`, `exec()`, `exec_fallback()`, `post()`
- Use `subprocess.run()` with `shell=False`
- Handle "not a git repository" errors consistently
- Log at appropriate levels

### 2. Error Handling

```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    # ... command execution ...

    if result.returncode != 0:
        if "not a git repository" in result.stderr.lower():
            raise ValueError(f"Directory '{cwd}' is not a git repository")
        elif "no names found" in result.stderr.lower():
            # No tags exist - return empty result (not error)
            return {"tags": [], "status": "no_tags"}
        else:
            raise subprocess.CalledProcessError(...)
```

### 3. Testing Requirements

Each node needs comprehensive tests:
- Unit tests with mocked subprocess
- Parsing tests for git output
- Error condition tests
- Integration tests with temp git repos
- Retry behavior tests

Example test structure:
```python
class TestGitGetLatestTag:
    def test_successful_get_latest(self): ...
    def test_no_tags_exist(self): ...
    def test_with_pattern_filter(self): ...
    def test_not_git_repository(self): ...
    def test_parse_tag_details(self): ...
    def test_retry_on_transient_failure(self): ...
```

## Verification Checklist

### Assumptions to Verify

- [x] Git commands work consistently across platforms (macOS, Linux, Windows with Git Bash)
- [x] Tag date can be reliably extracted (use commit date for lightweight tags)
- [x] Pattern matching syntax is consistent (`git tag -l` uses glob patterns)
- [ ] Remote operations require authentication setup (document in node docstring)
- [ ] Force operations should require explicit confirmation (add warning in docstring)

### Edge Cases to Handle

- [x] Repository with no tags
- [x] Lightweight vs annotated tags
- [x] Tags pointing to non-commit objects (rare but possible)
- [x] Tags with multi-line messages
- [x] Special characters in tag names
- [x] Concurrent tag operations (let git handle locking)

## Implementation Priority

### Phase 1: MVP (Required for North Star) 🔴
1. **git-get-latest-tag** - Critical for changelog generation
2. **git-tag-create** - Needed for release workflows

### Phase 2: Complete Feature Set 🟡
3. **git-tag-list** - Useful for version management
4. **git-tag-push** - Complete the workflow

### Phase 3: Future Enhancements 🟢
5. **git-tag-delete** - Cleanup operations
6. **git-tag-verify** - GPG signature verification

## Success Metrics

- [ ] All north star changelog examples work
- [ ] Tests achieve >90% coverage
- [ ] Nodes follow established patterns exactly
- [ ] Documentation includes usage examples
- [ ] Performance: < 100ms for local operations

## Migration Path

For existing workflows using mocked git-tag:
1. Implement nodes following this spec
2. Update test mocks to use real nodes
3. Update workflow generator context
4. Verify north star examples still work

## Example Workflows

### Changelog Since Last Release
```json
{
  "nodes": [
    {"id": "get_tag", "type": "git-get-latest-tag", "params": {"pattern": "v*"}},
    {"id": "get_commits", "type": "git-log", "params": {"since": "${get_tag.latest_tag.name}"}},
    {"id": "generate", "type": "llm", "params": {"prompt": "Generate changelog from ${get_commits.commits}"}}
  ]
}
```

### Create Release Tag
```json
{
  "nodes": [
    {"id": "create_tag", "type": "git-tag-create", "params": {"tag_name": "v${version}", "message": "Release ${version}"}},
    {"id": "push_tag", "type": "git-tag-push", "params": {"tags": ["${create_tag.created_tag.name}"]}}
  ]
}
```

## Open Questions

1. Should we support GPG signing for tags? (Probably Phase 3)
2. Should tag operations auto-push like some git GUIs? (No, explicit is better)
3. How to handle version sorting vs chronological sorting? (Provide sort parameter)

## Conclusion

Implementing git tag nodes as separate single-purpose components aligns with pflow's philosophy and enables critical north star workflows. Priority should be on `git-get-latest-tag` as it unblocks the primary changelog generation use case.

The modular approach ensures each node is simple, testable, and composable while maintaining consistency with existing git node patterns.