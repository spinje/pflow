# Task 87: Sandbox Runtime Research

> Research conducted: 2025-12-02
> Context: Security evaluation of pflow's command execution capabilities

## Executive Summary

pflow has two nodes that execute arbitrary commands:
1. **ClaudeCodeNode** - Spawns Claude Code agent with Bash access
2. **ShellNode** - Executes shell commands directly

Both are exposed via MCP server (Task 72), creating an attack vector where AI agents can trigger command execution. This research evaluates sandboxing approaches to mitigate this risk.

**Key Finding**: ClaudeCodeNode sandboxing is trivial (SDK has built-in support). ShellNode sandboxing requires platform-specific implementations.

---

## 1. Current State Analysis

### ClaudeCodeNode (`src/pflow/nodes/claude/claude_code.py`)

**Current configuration (line 351-361):**
```python
return ClaudeCodeOptions(
    model=prep_res["model"],
    max_thinking_tokens=prep_res["max_thinking_tokens"],
    allowed_tools=prep_res["allowed_tools"],
    system_prompt=system_prompt,
    max_turns=prep_res["max_turns"],
    cwd=prep_res["working_directory"],
    permission_mode="bypassPermissions",  # ← INSECURE: No permission prompts
    # No sandbox parameter                 # ← MISSING: No OS-level isolation
)
```

**Security issues:**
- `permission_mode="bypassPermissions"` - Bypasses all permission prompts
- No `sandbox` parameter - No filesystem/network isolation
- Default `allowed_tools` includes "Bash" - Full shell access
- Weak blocklist for dangerous patterns (easily bypassed)

### ShellNode (`src/pflow/nodes/shell/shell.py`)

**Current configuration (line 501-510):**
```python
result = subprocess.run(
    command,
    shell=True,  # ← Full shell interpretation
    capture_output=True,
    text=False,
    input=stdin_bytes,
    cwd=cwd,
    env=full_env,
    timeout=timeout,
)
```

**Security issues:**
- `shell=True` - Full shell access (intended behavior, but risky)
- Only defense is weak pattern blocklist (lines 119-148)
- No filesystem/network isolation
- Blocklist easily bypassed (e.g., blocks `rm -rf /` but not `rm -r -f /`)

### MCP Server Exposure (Task 72)

Both nodes exposed to AI agents via MCP server:
```
Untrusted prompt → AI Agent → MCP Server → ClaudeCodeNode/ShellNode → Arbitrary execution
```

---

## 2. Sandboxing Technologies Evaluated

### 2.1 Claude Code SDK Built-in Sandbox

**How it works:**
- Python SDK passes config to Claude Code CLI (Node.js)
- CLI uses OS-level sandboxing internally:
  - Linux: bubblewrap (bwrap)
  - macOS: sandbox-exec (Seatbelt)

**SDK Parameters:**
```python
ClaudeCodeOptions(
    permission_mode="acceptEdits",  # Or "default", "plan", "bypassPermissions"
    sandbox={
        "enabled": True,
        "autoAllowBashIfSandboxed": True,
        "excludedCommands": ["docker", "podman"],
        "allowUnsandboxedCommands": False,
        "network": {
            "allowLocalBinding": False,
            "allowUnixSockets": [],
        },
        "ignoreViolations": {
            "file": [],
            "network": [],
        },
        "enableWeakerNestedSandbox": False,  # For Docker environments
    }
)
```

**Verdict**: Best option for ClaudeCodeNode. Trivial to enable, Anthropic maintains it.

### 2.2 bubblewrap (bwrap)

**What it is:** Low-level Linux sandboxing tool used by Flatpak.

**How it works:**
- Uses Linux kernel namespaces (CLONE_NEWNET, CLONE_NEWPID, etc.)
- Can isolate filesystem, network, PIDs
- Bind-mounts specific paths for controlled access

**Example:**
```bash
bwrap \
    --ro-bind / / \              # Read-only root
    --bind $(pwd) $(pwd) \       # Read-write working dir
    --bind ~/.ssh ~/.ssh \       # SSH keys (for git)
    --unshare-net \              # No network
    --die-with-parent \
    sh -c "git commit -m 'fix'"
```

**Platform support:**
- Linux: ✅ Full support
- macOS: ❌ Not supported (requires Linux kernel namespaces)
- Windows: ❌ Not supported

**Python integration:**
- Can call `bwrap` binary via subprocess
- Libraries exist: [sandboxlib](https://github.com/CodethinkLabs/sandboxlib/blob/master/sandboxlib/bubblewrap.py)

**Verdict**: Good for Linux ShellNode, but not cross-platform.

### 2.3 sandbox-exec (Seatbelt)

**What it is:** macOS built-in sandboxing via Seatbelt profiles.

**How it works:**
- Uses macOS Seatbelt kernel extension
- Sandbox profiles define allowed operations
- Can restrict filesystem, network, IPC

**Example:**
```bash
sandbox-exec -p '(version 1)(deny default)(allow file-read*)' sh -c "ls"
```

**Status:** Deprecated by Apple (undocumented) but still functional. Claude Code uses it.

**Platform support:**
- Linux: ❌ Not supported
- macOS: ✅ Built-in
- Windows: ❌ Not supported

**Verdict**: Only option for macOS ShellNode, but deprecated status is concerning.

### 2.4 Docker/Podman

**What it is:** Container runtime providing full process isolation.

**Example (from mcp-server-code-execution-mode):**
```bash
podman run \
    --rm \
    --network=none \
    --read-only \
    --cap-drop=ALL \
    --user=65534:65534 \
    --memory=512m \
    --pids-limit=100 \
    image_name command
```

**Platform support:**
- Linux: ✅ Full support
- macOS: ✅ Via Docker Desktop
- Windows: ✅ Via Docker Desktop/WSL

**Verdict**: Cross-platform but **WRONG for shell commands** (see Section 3).

### 2.5 Anthropic sandbox-runtime (srt)

**What it is:** Standalone extraction of Claude Code's sandbox logic.

**Repository:** https://github.com/anthropic-experimental/sandbox-runtime

**How it works:**
- CLI tool that wraps any command
- Uses bwrap (Linux) or sandbox-exec (macOS) internally
- TypeScript/Node.js implementation

**Platform support:**
- Linux: ✅ Via bubblewrap
- macOS: ✅ Via sandbox-exec
- Windows: ❌ Not supported

**Verdict**: Good approach but requires Node.js dependency. We can implement same logic in Python.

---

## 3. Critical Insight: Code Execution vs Shell Commands

### Why Docker is WRONG for Shell Commands

**Code execution** (e.g., mcp-server-code-execution-mode):
```
"Run this Python snippet"
→ Self-contained
→ Doesn't need host filesystem
→ Just needs interpreter
→ Full container isolation is fine
```

**Shell commands** (pflow ShellNode):
```
"Run git status in my project"
→ Needs to see .git directory
→ Needs git binary from host
→ Needs SSH keys for git push
→ Needs user's environment
```

**Docker breaks shell commands:**
```bash
docker run -v $(pwd):/workspace alpine sh -c "git commit"
# ❌ git not installed in alpine
# ❌ No user git config (~/.gitconfig)
# ❌ No SSH keys (~/.ssh)
# ❌ Wrong user permissions
```

**bubblewrap/seatbelt preserves host access:**
```bash
bwrap \
    --ro-bind / / \                    # Has all tools (git, etc.)
    --bind $(pwd) $(pwd) \             # Read-write project dir
    --bind ~/.ssh ~/.ssh \             # SSH keys
    --bind ~/.gitconfig ~/.gitconfig \ # Git config
    --unshare-net \                    # But no network
    sh -c "git commit -m 'fix'"
# ✅ Works! Has tools, configs, but isolated network
```

**Key principle:** Shell commands need **partial isolation** (block dangerous paths/network) while preserving access to user's environment and tools.

---

## 4. Platform Support Matrix

| Approach | Linux | macOS | Windows | Best For |
|----------|-------|-------|---------|----------|
| Claude Code SDK sandbox | ✅ | ✅ | ❌ | ClaudeCodeNode |
| bubblewrap (bwrap) | ✅ | ❌ | ❌ | ShellNode (Linux) |
| sandbox-exec (Seatbelt) | ❌ | ✅ | ❌ | ShellNode (macOS) |
| Docker/Podman | ✅ | ✅ | ✅ | Code execution only |
| srt (Anthropic) | ✅ | ✅ | ❌ | Reference impl |

---

## 5. Recommended Implementation Approach

### Phase 1: ClaudeCodeNode (Trivial - 2-3 days)

Just enable SDK's built-in sandbox:

```python
def _build_claude_options(self, prep_res, system_prompt):
    return ClaudeCodeOptions(
        # ... existing params ...
        permission_mode="acceptEdits",  # Changed from "bypassPermissions"
        sandbox={
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
        },
    )
```

**Why this is sufficient:**
- SDK handles platform detection (bwrap on Linux, seatbelt on macOS)
- Covers the biggest risk (AI spawning AI with Bash)
- Zero custom sandbox code needed

### Phase 2: ShellNode (More complex - 5-7 days)

Implement platform-specific backends:

```python
# Linux: bubblewrap
class BubblewrapBackend(SandboxBackend):
    def run(self, command, cwd, timeout=30):
        bwrap_cmd = [
            "bwrap",
            "--ro-bind", "/", "/",
            "--bind", cwd, cwd,
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--unshare-net",
            "--die-with-parent",
            "--chdir", cwd,
            "sh", "-c", command
        ]
        return subprocess.run(bwrap_cmd, capture_output=True, timeout=timeout)

# macOS: sandbox-exec
class SeatbeltBackend(SandboxBackend):
    def run(self, command, cwd, timeout=30):
        profile = self._generate_profile(cwd)
        return subprocess.run(
            ["sandbox-exec", "-p", profile, "sh", "-c", command],
            capture_output=True,
            timeout=timeout,
            cwd=cwd
        )
```

**Factory with graceful fallback:**
```python
def get_sandbox_backend():
    system = platform.system()

    if system == "Linux" and shutil.which("bwrap"):
        return BubblewrapBackend()
    elif system == "Darwin":  # macOS
        return SeatbeltBackend()
    else:
        logger.warning("No sandbox available - proceeding unsandboxed")
        return None
```

---

## 6. Configuration Design

### Settings (`~/.pflow/settings.json`)

```json
{
  "security": {
    "sandbox": {
      "enabled": true,
      "claude_code": {
        "enabled": true,
        "permission_mode": "acceptEdits",
        "auto_allow_bash_if_sandboxed": true
      },
      "shell": {
        "enabled": true,
        "fallback_behavior": "warn",
        "network_isolation": true
      }
    }
  }
}
```

### Environment Variables

```bash
PFLOW_SANDBOX_ENABLED=true
PFLOW_CLAUDE_PERMISSION_MODE=acceptEdits
PFLOW_SHELL_SANDBOX_FALLBACK=warn
```

### Node Parameters (Workflow IR)

```json
{
  "id": "risky-op",
  "type": "claude-code",
  "params": {
    "sandbox_enabled": true,
    "permission_mode": "default"
  }
}
```

---

## 7. Security Considerations

### What Sandbox Provides

- **Filesystem isolation**: Block writes to system paths
- **Network isolation**: Prevent data exfiltration
- **Resource limits**: Prevent DoS (memory, CPU, PIDs)
- **Capability dropping**: Reduce attack surface

### What Sandbox Does NOT Provide

- Protection against logic bugs in user's workflow
- Protection against data in mounted directories
- Protection against side-channels
- Protection on unsupported platforms (Windows)

### MCP Server Context

Consider stricter defaults when running as MCP server:
- MCP: `sandbox_fallback="error"` (refuse to run unsandboxed)
- CLI: `sandbox_fallback="warn"` (warn but proceed)

---

## 8. Testing Strategy

### Unit Tests
- Sandbox config building
- Backend availability detection
- Fallback behavior
- Settings loading/merging

### Integration Tests
- Verify filesystem isolation (can't write to /etc)
- Verify network isolation (can't reach external hosts)
- Verify resource limits work
- Verify legitimate commands still work (git, grep, etc.)

### Security Tests
```python
def test_cannot_read_etc_passwd():
    """Sandbox should block reading sensitive files."""
    result = run_sandboxed("cat /etc/shadow")
    assert result.exit_code != 0 or "permission denied" in result.stderr.lower()

def test_cannot_reach_network():
    """Sandbox should block network access."""
    result = run_sandboxed("curl https://example.com")
    assert result.exit_code != 0
```

---

## 9. Open Questions for Implementation

1. **Default sandbox state**: ON by default? (Recommended: Yes for ClaudeCodeNode)

2. **ShellNode sandbox scope**: Which paths should be writable?
   - Current working directory
   - /tmp
   - What else?

3. **Network isolation exceptions**: Should localhost be allowed?

4. **Error handling**: What if sandbox setup fails mid-execution?

5. **Performance impact**: Is ~10ms overhead acceptable?

---

## 10. References

### Official Documentation
- [Claude Code Sandboxing - Anthropic Engineering](https://www.anthropic.com/engineering/claude-code-sandboxing)
- [Sandboxing - Claude Code Docs](https://code.claude.com/docs/en/sandboxing)
- [Python SDK Reference](https://platform.claude.com/docs/en/agent-sdk/python)
- [Handling Permissions - Claude Docs](https://code.claude.com/docs/en/sdk/sdk-permissions)

### Tools
- [bubblewrap - GitHub](https://github.com/containers/bubblewrap)
- [Bubblewrap Examples - ArchWiki](https://wiki.archlinux.org/title/Bubblewrap/Examples)
- [sandbox-runtime (srt) - Anthropic](https://github.com/anthropic-experimental/sandbox-runtime)

### Python Libraries
- [sandboxlib - Python bwrap wrapper](https://github.com/CodethinkLabs/sandboxlib/blob/master/sandboxlib/bubblewrap.py)
- [pytest-bwrap - Test isolation](https://pypi.org/project/pytest-bwrap/)

### Similar Projects
- [mcp-server-code-execution-mode](https://github.com/elusznik/mcp-server-code-execution-mode) - Uses Docker (good for code execution, not shell commands)

---

## 11. Implementation Plan Location

Detailed implementation plan with code examples available at:
`scratchpads/sandbox-implementation/implementation-plan.md`

---

## 12. Summary

| Component | Recommendation | Effort | Priority |
|-----------|---------------|--------|----------|
| ClaudeCodeNode | Enable SDK sandbox | 2-3 days | HIGH |
| ShellNode (Linux) | bubblewrap wrapper | 3-4 days | MEDIUM |
| ShellNode (macOS) | sandbox-exec wrapper | 3-4 days | MEDIUM |
| ShellNode (Windows) | Warn unsupported | 1 day | LOW |
| MCP context defaults | Stricter for MCP | 1-2 days | MEDIUM |

**Initial version (macOS-first):**
1. Enable ClaudeCodeNode SDK sandbox (trivial)
2. Defer ShellNode sandbox to Phase 2

This covers the biggest risk (AI with Bash) with minimal effort.
