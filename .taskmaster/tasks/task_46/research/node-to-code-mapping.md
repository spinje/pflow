# Complete Node-to-Code Generation Reference

**Purpose**: This document maps every pflow node type to its equivalent Python code, enabling workflow export to zero-dependency standalone scripts.

## Summary Table

| Node Type | External Deps | Stdlib Deps | Complexity | Key Challenge |
|-----------|--------------|-------------|------------|---------------|
| shell | None | subprocess, base64, os | Medium | Binary handling, stdin conversion |
| read-file | None | pathlib, base64, os | Low | Binary detection |
| write-file | None | pathlib, json, tempfile, shutil | Medium | Atomic writes |
| copy-file | None | shutil, os | Low | None |
| move-file | None | shutil, os | Low | None |
| delete-file | None | os | Low | None |
| llm | `llm` | None | Medium | JSON parsing |
| http | `requests` | json, base64 | Medium | Binary detection |
| mcp-* | `mcp`, `httpx` | asyncio, json | **HIGH** | Async/await, server config |
| git-* | System: `git` | subprocess, re | Medium | Porcelain parsing |
| github-* | System: `gh` CLI | subprocess, json, re | Medium | Two-step PR creation |

---

## 1. SHELL NODE (`shell`)

**Complexity**: Medium
**Source**: `src/pflow/nodes/shell/shell.py`

### Key Characteristics
- Executes arbitrary shell commands with full shell power
- Auto-converts structured data (dict/list) to JSON for stdin
- Handles binary output via base64 encoding
- Auto-handles "success" non-zero exits (grep no match, ls glob empty, which not found)

### Parameters
```python
command: str           # Shell command (required)
stdin: Any             # Input data (optional, auto-serialized)
cwd: str              # Working directory (optional)
env: dict             # Additional environment vars (optional)
timeout: int          # Max execution time (default: 30 seconds)
ignore_errors: bool   # Continue on non-zero exit (default: false)
```

### Shared Store I/O
**Reads**: `stdin` (optional)
**Writes**: `stdout`, `stdout_is_binary`, `stderr`, `stderr_is_binary`, `exit_code`, `error`

### Code Template
```python
import subprocess, os, base64, json

# Prepare stdin (auto-convert structured data to JSON)
stdin_value = {stdin_source}
if isinstance(stdin_value, (dict, list)):
    stdin_value = json.dumps(stdin_value, ensure_ascii=False)
elif stdin_value is not None:
    stdin_value = str(stdin_value)

# Execute
stdin_bytes = stdin_value.encode("utf-8") if stdin_value else None
result = subprocess.run(
    {command},
    shell=True,
    capture_output=True,
    text=False,
    input=stdin_bytes,
    cwd={cwd or None},
    env={{**os.environ, **{env}}} if {env} else None,
    timeout={timeout}
)

# Decode stdout (with binary fallback)
try:
    stdout = result.stdout.decode("utf-8")
    stdout_is_binary = False
except UnicodeDecodeError:
    stdout = base64.b64encode(result.stdout).decode("ascii")
    stdout_is_binary = True

# Decode stderr (with binary fallback)
try:
    stderr = result.stderr.decode("utf-8")
    stderr_is_binary = False
except UnicodeDecodeError:
    stderr = base64.b64encode(result.stderr).decode("ascii")
    stderr_is_binary = True

exit_code = result.returncode
```

---

## 2. FILE OPERATIONS

### 2.1 READ-FILE (`read-file`)

**Complexity**: Low
**Source**: `src/pflow/nodes/file/read_file.py`

### Code Template
```python
import os, base64
from pathlib import Path

# Normalize path
file_path = os.path.normpath(os.path.abspath(os.path.expanduser({file_path})))

# Binary extensions
BINARY_EXTS = {{".png", ".jpg", ".pdf", ".zip", ".mp3", ".exe", ".bin"}}
is_binary_ext = Path(file_path).suffix.lower() in BINARY_EXTS

if is_binary_ext:
    binary_content = Path(file_path).read_bytes()
    content = base64.b64encode(binary_content).decode("ascii")
    content_is_binary = True
else:
    try:
        with open(file_path, encoding={encoding}) as f:
            lines = f.readlines()
        content = "".join(f"{{i+1}}: {{line}}" for i, line in enumerate(lines))
        content_is_binary = False
    except UnicodeDecodeError:
        binary_content = Path(file_path).read_bytes()
        content = base64.b64encode(binary_content).decode("ascii")
        content_is_binary = True
```

### 2.2 WRITE-FILE (`write-file`)

**Complexity**: Medium (atomic writes)
**Source**: `src/pflow/nodes/file/write_file.py`

### Code Template
```python
import os, json, base64, tempfile, shutil

# Prepare content
content = {content}
if {content_is_binary} and isinstance(content, str):
    content = base64.b64decode(content)
elif not {content_is_binary}:
    if isinstance(content, (dict, list)):
        content = json.dumps(content, ensure_ascii=False, indent=2)
    else:
        content = str(content)

file_path = os.path.normpath(os.path.abspath(os.path.expanduser({file_path})))

# Create parent dirs
parent = os.path.dirname(file_path)
if parent:
    os.makedirs(parent, exist_ok=True)

if {append}:
    mode = "ab" if {content_is_binary} else "a"
    with open(file_path, mode, encoding={encoding if not binary else None}) as f:
        f.write(content)
else:
    # Atomic write
    fd, temp = tempfile.mkstemp(dir=os.path.dirname(file_path) or ".", text=not {content_is_binary})
    try:
        mode = "wb" if {content_is_binary} else "w"
        with os.fdopen(fd, mode, encoding={encoding if not binary else None}) as f:
            f.write(content)
        shutil.move(temp, file_path)
    except:
        if os.path.exists(temp):
            os.unlink(temp)
        raise
```

### 2.3-2.5 Simple File Operations

```python
# COPY-FILE
import shutil
shutil.copy2({source_path}, {dest_path})

# MOVE-FILE
import shutil
shutil.move({source_path}, {dest_path})

# DELETE-FILE
import os
os.remove({file_path})
```

---

## 3. LLM NODE (`llm`)

**Complexity**: Medium
**Source**: `src/pflow/nodes/llm/llm.py`
**External Dependency**: `pip install llm`

### Code Template
```python
import llm, json

model = llm.get_model({model})
kwargs = {{"stream": False, "temperature": {temperature}}}

if {system}:
    kwargs["system"] = {system}
if {max_tokens}:
    kwargs["max_tokens"] = {max_tokens}

# Images
if {images}:
    attachments = []
    for img in {images}:
        if img.startswith(("http://", "https://")):
            attachments.append(llm.Attachment(url=img))
        else:
            attachments.append(llm.Attachment(path=img))
    kwargs["attachments"] = attachments

# Call LLM
response = model.prompt({prompt}, **kwargs)
text = response.text()

# Parse JSON from response (including markdown blocks)
try:
    trimmed = text.strip()
    if "```" in trimmed:
        start = trimmed.find("```json") + 7 if "```json" in trimmed else trimmed.find("```") + 3
        end = trimmed.find("```", start)
        if end > start:
            trimmed = trimmed[start:end].strip()
    response_parsed = json.loads(trimmed)
except (json.JSONDecodeError, ValueError):
    response_parsed = text

# Usage metrics
usage = response.usage()
if usage:
    llm_usage = {{
        "model": {model},
        "input_tokens": usage.input or 0,
        "output_tokens": usage.output or 0,
        "total_tokens": (usage.input or 0) + (usage.output or 0)
    }}
else:
    llm_usage = {{}}
```

---

## 4. HTTP NODE (`http`)

**Complexity**: Medium
**Source**: `src/pflow/nodes/http/http.py`
**External Dependency**: `pip install requests`

### Code Template
```python
import requests, json, base64

# Auto-detect method
method = {method} or ("POST" if {body} else "GET")

# Headers
headers = dict({headers}) if {headers} else {{}}
if {auth_token}:
    headers["Authorization"] = f"Bearer {{{auth_token}}}"
elif {api_key}:
    headers[{api_key_header or "X-API-Key"}] = {api_key}
if isinstance({body}, dict):
    headers.setdefault("Content-Type", "application/json")

# Request
response = requests.request(
    method=method.upper(),
    url={url},
    headers=headers,
    json={body} if isinstance({body}, dict) else None,
    data={body} if isinstance({body}, str) else None,
    params={params},
    timeout={timeout}
)

# Parse response
content_type = response.headers.get("content-type", "").lower()
BINARY_TYPES = ["image/", "video/", "audio/", "application/pdf", "application/octet-stream"]
is_binary = any(ct in content_type for ct in BINARY_TYPES)

if is_binary:
    response_data = base64.b64encode(response.content).decode("ascii")
    response_is_binary = True
elif "json" in content_type:
    try:
        response_data = response.json()
    except:
        response_data = response.text
    response_is_binary = False
else:
    response_data = response.text
    response_is_binary = False

status_code = response.status_code
response_headers = dict(response.headers)
response_time = response.elapsed.total_seconds()
```

---

## 5. GIT OPERATIONS

**Complexity**: Medium
**System Requirement**: `git` CLI must be installed
**Sources**: `src/pflow/nodes/git/*.py`

### 5.1 GIT-STATUS

```python
import subprocess, re

result = subprocess.run(
    ["git", "status", "--porcelain=v2", "--branch"],
    cwd={working_directory},
    capture_output=True,
    text=True,
    timeout=30,
    check=False
)

if result.returncode != 0:
    if "not a git repository" in result.stderr.lower():
        raise ValueError("Not a git repository")
    raise subprocess.CalledProcessError(result.returncode, result.args)

# Parse porcelain v2 output
status = {{"modified": [], "staged": [], "untracked": [], "branch": "main", "ahead": 0, "behind": 0}}

for line in result.stdout.strip().split('\n'):
    if line.startswith("# branch.head"):
        status["branch"] = line.split()[-1]
    elif line.startswith("# branch.ab"):
        parts = line.split()
        status["ahead"] = int(parts[2].lstrip('+'))
        status["behind"] = abs(int(parts[3]))
    elif line.startswith("1") or line.startswith("2"):
        parts = line.split()
        xy_status, filepath = parts[1], parts[8]
        if xy_status[0] != '.':
            status["staged"].append(filepath)
        if xy_status[1] == 'M':
            status["modified"].append(filepath)
    elif line.startswith("?"):
        status["untracked"].append(line.split()[-1])
```

### 5.2 GIT-COMMIT

```python
import subprocess, re

# Stage files
for file in {files}:
    result = subprocess.run(["git", "add", file], cwd={working_directory}, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise ValueError(f"Failed to stage {{file}}: {{result.stderr}}")

# Commit
result = subprocess.run(["git", "commit", "-m", {message}], cwd={working_directory}, capture_output=True, text=True, timeout=30, check=False)

if result.returncode == 1 and "nothing to commit" in result.stdout.lower():
    commit_sha = ""
    status = "nothing_to_commit"
else:
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, result.args)

    # Extract SHA from output like "[main abc123] message"
    sha_match = re.search(r"\[[\w/-]+ ([a-f0-9]+)\]", result.stdout)
    commit_sha = sha_match.group(1) if sha_match else ""

    if not commit_sha:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd={working_directory}, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            commit_sha = result.stdout.strip()[:7]

    status = "committed"
```

### 5.3 GIT-PUSH

```python
import subprocess

result = subprocess.run(
    ["git", "push", {remote}, {branch}],
    cwd={working_directory},
    capture_output=True,
    text=True,
    timeout=60,
    check=False
)

if result.returncode != 0:
    if "Everything up-to-date" in result.stderr or "Everything up-to-date" in result.stdout:
        success = True  # Already pushed
    elif "rejected" in result.stderr:
        raise ValueError("Push rejected: Remote has changes. Pull first or force push.")
    else:
        raise ValueError(f"Push failed: {{result.stderr}}")
else:
    success = True
```

---

## 6. GITHUB OPERATIONS

**Complexity**: Medium
**System Requirement**: `gh` CLI must be installed and authenticated
**Sources**: `src/pflow/nodes/github/*.py`

### 6.1 GITHUB-LIST-ISSUES

```python
import subprocess, json

# Check auth
auth_result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=10)
if auth_result.returncode != 0:
    raise ValueError("GitHub CLI not authenticated. Run 'gh auth login'")

# Build command
cmd = ["gh", "issue", "list", "--json", "number,title,state,author,labels,createdAt,updatedAt", "--state", {state}, "--limit", str({limit})]
if {repo}:
    cmd.extend(["--repo", {repo}])

# Execute
result = subprocess.run(cmd, capture_output=True, text=True, shell=False, timeout=30)
if result.returncode != 0:
    raise subprocess.CalledProcessError(result.returncode, cmd)

issues = json.loads(result.stdout) if result.stdout else []
```

### 6.2 GITHUB-CREATE-PR

**Note**: This requires a TWO-STEP process because `gh pr create` doesn't support `--json`.

```python
import subprocess, json, re

# Step 1: Create PR (returns URL only)
cmd = ["gh", "pr", "create", "--title", {title}, "--body", {body}, "--base", {base}, "--head", {head}]
if {repo}:
    cmd.extend(["--repo", {repo}])

result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
if result.returncode != 0:
    raise subprocess.CalledProcessError(result.returncode, cmd)

# Step 2: Parse URL and extract PR number
pr_url = result.stdout.strip()
match = re.search(r"/pull/(\d+)", pr_url)
if not match:
    raise ValueError(f"Could not parse PR number from URL: {{pr_url}}")
pr_number = match.group(1)

# Step 3: Get full PR data
cmd = ["gh", "pr", "view", pr_number, "--json", "number,url,title,state,author"]
if {repo}:
    cmd.extend(["--repo", {repo}])

result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
if result.returncode != 0:
    raise subprocess.CalledProcessError(result.returncode, cmd)

pr_data = json.loads(result.stdout)
pr_data["url"] = pr_url
pr_data["number"] = int(pr_number)
```

---

## 7. MCP NODE (`mcp-{server}-{tool}`)

**Complexity**: **HIGH** (most complex node to export)
**Source**: `src/pflow/nodes/mcp/node.py`
**External Dependencies**: `pip install mcp httpx`

### Why MCP is Complex
1. Requires async/await (all MCP SDK is async)
2. Needs MCP server configuration from `~/.pflow/mcp-servers.json`
3. Server-specific authentication (env vars, tokens)
4. Two transport types: stdio (subprocess) and HTTP
5. Structured content extraction (multiple content types)

### Code Template (Stdio Transport)
```python
import asyncio, json
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Load server config
config_path = Path("~/.pflow/mcp-servers.json").expanduser()
with open(config_path) as f:
    config = json.load(f)

server_config = config["mcpServers"][{server_name}]

# Prepare parameters
params = StdioServerParameters(
    command=server_config["command"],
    args=server_config.get("args", []),
    env=server_config.get("env")
)

# Execute tool
async def run_mcp_tool():
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool({tool_name}, {tool_arguments})

        # Extract structured content (priority order: structuredContent > isError > content blocks)
        if hasattr(result, "structuredContent") and result.structuredContent:
            return result.structuredContent
        elif hasattr(result, "isError") and result.isError:
            error_msg = str(result.content[0].text) if result.content else "Tool execution failed"
            return {{"error": error_msg, "is_tool_error": True}}
        elif hasattr(result, "content"):
            contents = []
            for content in result.content:
                if hasattr(content, "text"):
                    text = str(content.text)
                    try:
                        contents.append(json.loads(text.strip()))
                    except:
                        contents.append(text)
            return contents[0] if len(contents) == 1 else contents

        return str(result)

result = asyncio.run(run_mcp_tool())
```

### Code Template (HTTP Transport)
```python
import asyncio, json
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Load server config (same as stdio)
config_path = Path("~/.pflow/mcp-servers.json").expanduser()
with open(config_path) as f:
    config = json.load(f)

server_config = config["mcpServers"][{server_name}]
url = server_config["url"]

# Build auth headers
headers = {{}}
if auth_token := server_config.get("auth_token"):
    headers["Authorization"] = f"Bearer {{auth_token}}"
elif api_key := server_config.get("api_key"):
    headers[server_config.get("api_key_header", "X-API-Key")] = api_key

# Execute
async def run_mcp_tool():
    async with streamablehttp_client(url=url, headers=headers, timeout=30, sse_read_timeout=300) as (read, write, get_session_id), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool({tool_name}, {tool_arguments})

        # Same extraction logic as stdio...
        if hasattr(result, "structuredContent") and result.structuredContent:
            return result.structuredContent
        # ... (rest same as stdio)

result = asyncio.run(run_mcp_tool())
```

---

## Export Implementation Roadmap

### Phase 1: Simple Nodes (No External Deps)
**Estimated Complexity**: Low
- shell
- file operations (read, write, copy, move, delete)
- git operations (status, commit, push)
- github operations (list issues, create PR)

**Dependencies**: Only stdlib
**Challenges**: Binary handling, template resolution

### Phase 2: Python Package Nodes
**Estimated Complexity**: Medium
- llm (requires `pip install llm`)
- http (requires `pip install requests`)

**Dependencies**: pip packages
**Challenges**: Package detection, requirements.txt generation

### Phase 3: MCP Nodes
**Estimated Complexity**: HIGH
- mcp-* (requires `pip install mcp httpx`)

**Dependencies**: pip packages + server config
**Challenges**:
1. Async/await transformation
2. Server config embedding or external file
3. Transport-specific code generation
4. Authentication handling
5. Content type extraction

### Recommended Approach
1. **Start with Phase 1**: Export workflows that only use stdlib nodes
2. **Add Phase 2**: Detect pip dependencies and generate requirements.txt
3. **Defer Phase 3**: MCP nodes are complex enough to warrant separate implementation

---

## Critical Export Challenges

### 1. Template Variable Resolution
**Problem**: IR contains `${{variable}}`, runtime resolves to actual values
**Solution**: Generate code that:
- Reads workflow inputs
- Resolves template strings
- Handles nested paths (`${{node.result.data.field}}`)

### 2. Shared Store Simulation
**Problem**: Nodes communicate via shared dictionary
**Solution**: Generate `shared = {{}}` dict with explicit get/set

### 3. Error Handling
**Problem**: Nodes use PocketFlow retry mechanism
**Solution**: Wrap each step in try/except with manual retry loop

### 4. Binary Data
**Problem**: Binary data encoded as base64 in shared store
**Solution**: Include base64 encode/decode in generated code

### 5. Conditional Transitions
**Problem**: Nodes return "default" or "error" actions
**Solution**: Use if/else to route to next node

### 6. Output Routing
**Problem**: IR specifies which shared keys to output
**Solution**: Generate final print/return statement

---

## Next Steps

1. Build template variable resolver (handles `${{...}}` syntax)
2. Create code generator for each node type
3. Add dependency detector (stdlib vs pip)
4. Implement shared store simulator
5. Add error handling wrapper
6. Generate requirements.txt when needed
7. Test with real workflows from examples/

**Recommended starting point**: Export a simple workflow with only `read-file` → `llm` → `write-file` to validate the approach.
