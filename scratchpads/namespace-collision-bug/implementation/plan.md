# Implementation Plan: Remove Parameter Fallback Pattern

## Summary

**Problem**: The pattern `shared.get("x") or self.params.get("x")` causes namespace collision bugs where node namespace dicts or workflow inputs with matching names override template-resolved parameters.

**Solution**: Remove the fallback pattern entirely. Nodes read only from `self.params` for declared parameters. The template system handles all data wiring explicitly.

**Rationale**:
- Aligns with PocketFlow's explicit separation philosophy
- Templates are the proper IR-level wiring mechanism
- Removes implicit behavior that causes bugs
- Simpler, more predictable mental model

---

## Scope

### Files to Modify

#### Node Implementations (20 files, ~60 parameters)

| File | Parameters to Change |
|------|---------------------|
| `src/pflow/nodes/git/push.py` | `branch`, `remote`, `working_directory` |
| `src/pflow/nodes/git/status.py` | `working_directory` |
| `src/pflow/nodes/git/checkout.py` | `branch`, `create`, `base`, `force`, `stash`, `working_directory` |
| `src/pflow/nodes/git/get_latest_tag.py` | `pattern`, `working_directory` |
| `src/pflow/nodes/git/commit.py` | `message`, `files`, `working_directory` |
| `src/pflow/nodes/git/log.py` | `since`, `until`, `author`, `grep`, `path`, `working_directory` |
| `src/pflow/nodes/http/http.py` | `url`, `method`, `body`, `headers`, `params`, `timeout`, `auth_token`, `api_key` |
| `src/pflow/nodes/github/get_issue.py` | `issue_number`, `repo` |
| `src/pflow/nodes/github/list_prs.py` | `repo`, `state`, `limit` |
| `src/pflow/nodes/github/list_issues.py` | `repo`, `state`, `limit`, `since` |
| `src/pflow/nodes/github/create_pr.py` | `title`, `body`, `head`, `base`, `repo` |
| `src/pflow/nodes/claude/claude_code.py` | `prompt`, `output_schema` |
| `src/pflow/nodes/shell/shell.py` | `stdin` |
| `src/pflow/nodes/file/write_file.py` | `file_path`, `encoding`, `content_is_binary`, `content` |
| `src/pflow/nodes/file/delete_file.py` | `file_path` |
| `src/pflow/nodes/file/move_file.py` | `source_path`, `dest_path` |
| `src/pflow/nodes/file/copy_file.py` | `source_path`, `dest_path` |
| `src/pflow/nodes/file/read_file.py` | `file_path`, `encoding` |
| `src/pflow/nodes/test/echo.py` | `message`, `count`, `data` |
| `src/pflow/nodes/llm/llm.py` | `prompt`, `system`, `images` |

#### Documentation (3 files)

| File | Change |
|------|--------|
| `src/pflow/nodes/CLAUDE.md` | Remove "Parameter Fallback" section, update guidance |
| `architecture/core-concepts/shared-store.md` | Remove "shared store takes precedence" |
| Any other docs referencing fallback | Search and update |

#### Tests (4+ files)

| File | Change |
|------|--------|
| `tests/test_nodes/test_llm/test_llm.py` | Update `test_llm_system_parameter_fallback` |
| `tests/test_runtime/test_namespacing.py` | Update test nodes using fallback |
| `tests/test_runtime/test_namespacing_integration.py` | Update test nodes using fallback |
| Other tests using fallback pattern | Search and update |

---

## Implementation Steps

### Phase 1: Update Node Implementations

For each node, change from:
```python
# Old pattern (vulnerable):
url = shared.get("url") or self.params.get("url")
# or
url = shared.get("url") if "url" in shared else self.params.get("url")
```

To:
```python
# New pattern (explicit):
url = self.params.get("url")
# or for required params:
url = self.params["url"]  # Raises KeyError if missing
```

#### Detailed Changes by Node

##### 1. LLM Node (`src/pflow/nodes/llm/llm.py`)

**Current** (lines ~106-124):
```python
prompt = shared.get("prompt") or self.params.get("prompt")
system = shared.get("system") or self.params.get("system")
images = shared.get("images") if "images" in shared else self.params.get("images", [])
```

**New**:
```python
prompt = self.params.get("prompt")
system = self.params.get("system")
images = self.params.get("images", [])
```

##### 2. HTTP Node (`src/pflow/nodes/http/http.py`)

**Current** (lines ~50-89):
```python
url = shared.get("url") or self.params.get("url")
method = shared.get("method") if "method" in shared else self.params.get("method")
body = shared.get("body") if "body" in shared else self.params.get("body")
base_headers = shared.get("headers") if "headers" in shared else self.params.get("headers", {})
params = shared.get("params") if "params" in shared else self.params.get("params")
raw_timeout = shared.get("timeout") if "timeout" in shared else self.params.get("timeout", 30)
auth_token = shared.get("auth_token") or self.params.get("auth_token")
api_key = shared.get("api_key") or self.params.get("api_key")
```

**New**:
```python
url = self.params.get("url")
method = self.params.get("method")
body = self.params.get("body")
base_headers = self.params.get("headers", {})
params = self.params.get("params")
raw_timeout = self.params.get("timeout", 30)
auth_token = self.params.get("auth_token")
api_key = self.params.get("api_key")
```

##### 3. Shell Node (`src/pflow/nodes/shell/shell.py`)

**Current** (line ~489):
```python
stdin = shared.get("stdin") or self.params.get("stdin")
```

**New**:
```python
stdin = self.params.get("stdin")
```

##### 4. File Nodes

**read_file.py** (lines ~45-55):
```python
# Current:
file_path = shared.get("file_path") or self.params.get("file_path")
encoding = shared.get("encoding") or self.params.get("encoding", "utf-8")

# New:
file_path = self.params.get("file_path")
encoding = self.params.get("encoding", "utf-8")
```

**write_file.py** (lines ~50-77):
```python
# Current (content uses explicit in-check pattern):
if "content" in shared:
    content = shared["content"]
elif "content" in self.params:
    content = self.params["content"]
else:
    raise ValueError("Missing required 'content'...")

file_path = shared.get("file_path") or self.params.get("file_path")
encoding = shared.get("encoding") or self.params.get("encoding", "utf-8")
is_binary = shared.get("content_is_binary") or self.params.get("content_is_binary", False)

# New:
content = self.params.get("content")
if content is None:
    raise ValueError("Missing required 'content' parameter")

file_path = self.params.get("file_path")
encoding = self.params.get("encoding", "utf-8")
is_binary = self.params.get("content_is_binary", False)
```

**copy_file.py** (lines ~46-51):
```python
# Current:
source_path = shared.get("source_path") or self.params.get("source_path")
dest_path = shared.get("dest_path") or self.params.get("dest_path")

# New:
source_path = self.params.get("source_path")
dest_path = self.params.get("dest_path")
```

**move_file.py** (lines ~48-53):
```python
# Current:
source_path = shared.get("source_path") or self.params.get("source_path")
dest_path = shared.get("dest_path") or self.params.get("dest_path")

# New:
source_path = self.params.get("source_path")
dest_path = self.params.get("dest_path")
```

**delete_file.py** (line ~48):
```python
# Current:
file_path = shared.get("file_path") or self.params.get("file_path")

# New:
file_path = self.params.get("file_path")
```

##### 5. Git Nodes

**push.py** (lines ~44-50):
```python
# Current:
branch = shared.get("branch") or self.params.get("branch", "HEAD")
remote = shared.get("remote") or self.params.get("remote", "origin")
cwd = shared.get("working_directory") or self.params.get("working_directory", ".")

# New:
branch = self.params.get("branch", "HEAD")
remote = self.params.get("remote", "origin")
cwd = self.params.get("working_directory", ".")
```

**status.py** (line ~46):
```python
# Current:
cwd = shared.get("working_directory") or self.params.get("working_directory", ".")

# New:
cwd = self.params.get("working_directory", ".")
```

**checkout.py** (lines ~196-213):
```python
# Current:
branch = shared.get("branch") or self.params.get("branch")
create = shared.get("create") or self.params.get("create", False)
base = shared.get("base") or self.params.get("base")
force = shared.get("force") or self.params.get("force", False)
stash = shared.get("stash") or self.params.get("stash", False)
cwd = shared.get("working_directory") or self.params.get("working_directory", ".")

# New:
branch = self.params.get("branch")
create = self.params.get("create", False)
base = self.params.get("base")
force = self.params.get("force", False)
stash = self.params.get("stash", False)
cwd = self.params.get("working_directory", ".")
```

**commit.py** (lines ~43-55):
```python
# Current:
message = shared.get("message") or self.params.get("message")
files = shared.get("files") or self.params.get("files", ["."])
cwd = shared.get("working_directory") or self.params.get("working_directory", ".")

# New:
message = self.params.get("message")
files = self.params.get("files", ["."])
cwd = self.params.get("working_directory", ".")
```

**log.py** (lines ~55-66):
```python
# Current:
since = shared.get("since") or self.params.get("since")
until = shared.get("until") or self.params.get("until")
author = shared.get("author") or self.params.get("author")
grep = shared.get("grep") or self.params.get("grep")
path = shared.get("path") or self.params.get("path")
cwd = shared.get("working_directory") or self.params.get("working_directory", ".")

# New:
since = self.params.get("since")
until = self.params.get("until")
author = self.params.get("author")
grep = self.params.get("grep")
path = self.params.get("path")
cwd = self.params.get("working_directory", ".")
```

**get_latest_tag.py** (lines ~46-49):
```python
# Current:
pattern = shared.get("pattern") or self.params.get("pattern")
cwd = shared.get("working_directory") or self.params.get("working_directory", ".")

# New:
pattern = self.params.get("pattern")
cwd = self.params.get("working_directory", ".")
```

##### 6. GitHub Nodes

**get_issue.py** (lines ~63-72):
```python
# Current:
issue_number = shared.get("issue_number") or self.params.get("issue_number")
repo = shared.get("repo") or self.params.get("repo")

# New:
issue_number = self.params.get("issue_number")
repo = self.params.get("repo")
```

**list_prs.py** (lines ~61-71):
```python
# Current:
repo = shared.get("repo") or self.params.get("repo")
state = shared.get("state") or self.params.get("state", "open")
limit = shared.get("limit") or self.params.get("limit", 30)

# New:
repo = self.params.get("repo")
state = self.params.get("state", "open")
limit = self.params.get("limit", 30)
```

**list_issues.py** (lines ~146-170):
```python
# Current:
repo = shared.get("repo") or self.params.get("repo")
state = shared.get("state") or self.params.get("state", "open")
limit = shared.get("limit") or self.params.get("limit", 30)
since = shared.get("since") or self.params.get("since")

# New:
repo = self.params.get("repo")
state = self.params.get("state", "open")
limit = self.params.get("limit", 30)
since = self.params.get("since")
```

**create_pr.py** (lines ~56-76):
```python
# Current:
title = shared.get("title") or self.params.get("title")
body = shared.get("body") or self.params.get("body", "")
head = shared.get("head") or self.params.get("head")
base = shared.get("base") or self.params.get("base", "main")
repo = shared.get("repo") or self.params.get("repo")

# New:
title = self.params.get("title")
body = self.params.get("body", "")
head = self.params.get("head")
base = self.params.get("base", "main")
repo = self.params.get("repo")
```

##### 7. Claude Code Node (`src/pflow/nodes/claude/claude_code.py`)

**Current** (lines ~335-338):
```python
prompt = self._validate_prompt(shared.get("prompt") or self.params.get("prompt"))
output_schema = self._validate_schema(shared.get("output_schema") or self.params.get("output_schema"))

# New:
prompt = self._validate_prompt(self.params.get("prompt"))
output_schema = self._validate_schema(self.params.get("output_schema"))
```

##### 8. Test Echo Node (`src/pflow/nodes/test/echo.py`)

**Current** (lines ~45-47):
```python
message = shared.get("message") or self.params.get("message") or "Hello, World!"
count = shared.get("count") or self.params.get("count") or 1
data = shared.get("data") or self.params.get("data")

# New:
message = self.params.get("message", "Hello, World!")
count = self.params.get("count", 1)
data = self.params.get("data")
```

---

### Phase 2: Update Documentation

#### `src/pflow/nodes/CLAUDE.md`

Remove the "Parameter Fallback" section (lines ~170-183) that mandates the old pattern.

Replace with:
```markdown
### Parameter Access

Nodes read parameters from `self.params`. The template system handles all data wiring:

```python
# Read from params (templates resolve shared store values here)
file_path = self.params.get("file_path")
timeout = self.params.get("timeout", 30)  # With default

# For required params, use direct access (raises KeyError if missing)
url = self.params["url"]
```

Do NOT read from shared store for declared parameters:
```python
# WRONG - creates implicit connections
file_path = shared.get("file_path") or self.params.get("file_path")

# CORRECT - explicit, predictable
file_path = self.params.get("file_path")
```

The template system in IR handles data flow:
- Static value: `"url": "https://api.com"`
- From input: `"url": "${user_url}"`
- From node: `"input": "${fetch.response}"`
```

#### `architecture/core-concepts/shared-store.md`

Remove any references to "shared store takes precedence". Update to reflect that:
- Shared store is for node outputs (namespaced)
- Workflow inputs go to shared store at root level
- Templates wire shared store values into params
- Nodes read from params, not shared store directly

---

### Phase 3: Update Tests

#### Search for tests using fallback pattern

```bash
grep -rn "shared.get.*or.*params.get\|shared.get.*if.*in shared" tests/
```

#### Update test nodes

Tests that define custom nodes using the fallback pattern need updating:
- `tests/test_runtime/test_namespacing.py`
- `tests/test_runtime/test_namespacing_integration.py`

#### Update/remove fallback-specific tests

- `tests/test_nodes/test_llm/test_llm.py:test_llm_system_parameter_fallback` - Rename and update to test params-only behavior

---

### Phase 4: Verification

#### 4.1 Run Bug Reproduction Cases

```bash
# Should now work correctly
uv run pflow scratchpads/namespace-collision-bug/reproduce.json
uv run pflow scratchpads/namespace-collision-bug/reproduce-input.json url="https://example.com"
```

Expected: Template-resolved values are used, not namespace dicts or raw inputs.

#### 4.2 Run Full Test Suite

```bash
make test
make check
```

#### 4.3 Manual Testing

Test key workflows:
1. Static params work
2. Template resolution from inputs works
3. Template resolution from node outputs works
4. Batch processing with templates works

---

## Risk Assessment

### Low Risk
- No users yet (per CLAUDE.md)
- Templates handle all legitimate use cases
- Change is conceptually simple (remove fallback)

### Medium Risk
- Many files to change (20 nodes)
- Tests need updating
- Documentation needs updating

### Mitigations
- Comprehensive test coverage
- Bug reproduction cases as regression tests
- Code review before merge

---

## Rollback Plan

If issues discovered after implementation:
1. Revert all node changes
2. Revert documentation
3. Revert test changes
4. Consider alternative fix (Option 1: filter namespaces)

---

## Success Criteria

1. Bug reproduction cases pass (no namespace collision)
2. All existing tests pass (after updates)
3. Template resolution works correctly
4. Documentation is consistent
5. `make test` and `make check` pass

---

## Implementation Order

1. **Batch 1**: File nodes (5 files) - simplest, good for validating approach
2. **Batch 2**: LLM and HTTP nodes (2 files) - most commonly used
3. **Batch 3**: Git nodes (6 files)
4. **Batch 4**: GitHub nodes (4 files)
5. **Batch 5**: Shell, Claude, Test nodes (3 files)
6. **Batch 6**: Update tests
7. **Batch 7**: Update documentation
8. **Batch 8**: Final verification

---

## Questions/Decisions Needed

None - approach is clear from discussion.

---

## Estimated Effort

- Node changes: ~2-3 hours (mechanical, repetitive)
- Test updates: ~1 hour
- Documentation: ~30 minutes
- Verification: ~30 minutes

**Total: ~4-5 hours**

---

## Pattern Variants to Replace

Three variants exist in the codebase:

### Variant 1: `or` pattern (most common)
```python
# Before:
url = shared.get("url") or self.params.get("url")

# After:
url = self.params.get("url")
```

### Variant 2: Ternary `if in` pattern (HTTP, LLM nodes)
```python
# Before:
method = shared.get("method") if "method" in shared else self.params.get("method")

# After:
method = self.params.get("method")
```

### Variant 3: Explicit `in` check pattern (write_file content)
```python
# Before:
if "content" in shared:
    content = shared["content"]
elif "content" in self.params:
    content = self.params["content"]
else:
    raise ValueError("...")

# After:
content = self.params.get("content")
if content is None:
    raise ValueError("...")
```

---

## File Count Summary

| Category | Files | Parameters |
|----------|-------|------------|
| File nodes | 5 | ~12 |
| Git nodes | 6 | ~18 |
| GitHub nodes | 4 | ~12 |
| HTTP node | 1 | 8 |
| LLM node | 1 | 3 |
| Shell node | 1 | 1 |
| Claude node | 1 | 2 |
| Test node | 1 | 3 |
| **Total** | **20** | **~60** |

Plus:
- 2 CLAUDE.md documentation files (nodes/, github/)
- 1 architecture doc (shared-store.md)
- 3+ test files
