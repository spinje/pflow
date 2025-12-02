# Task 87: Key Insights Summary

## TL;DR

1. **ClaudeCodeNode sandbox is trivial** - Just add `sandbox={"enabled": True}` to SDK options. SDK handles Linux/macOS automatically.

2. **ShellNode sandbox is platform-specific** - bubblewrap (Linux), sandbox-exec (macOS). No good Windows option.

3. **Docker is WRONG for shell commands** - It isolates too much. Shell commands need host tools (git, ssh keys, etc.).

4. **Phase 1 should be ClaudeCodeNode only** - Biggest risk, minimal effort.

---

## Critical Insight

**Code execution** (run Python snippet) vs **Shell commands** (run git status):

| Aspect | Code Execution | Shell Commands |
|--------|---------------|----------------|
| Needs host filesystem | No | Yes |
| Needs host tools | Just interpreter | git, ssh, etc. |
| Needs user config | No | ~/.gitconfig, ~/.ssh |
| Ideal sandbox | Full container (Docker) | Partial isolation (bwrap) |

This is why Claude Code uses bubblewrap/seatbelt instead of Docker.

---

## Platform Support

| Tool | Linux | macOS | Windows |
|------|-------|-------|---------|
| Claude SDK sandbox | ✅ | ✅ | ❌ |
| bubblewrap | ✅ | ❌ | ❌ |
| sandbox-exec | ❌ | ✅ | ❌ |
| Docker | ✅ | ✅ | ✅ (but wrong tool) |

---

## Recommended Approach

### Phase 1 (Do First)
```python
# ClaudeCodeNode - just add this:
ClaudeCodeOptions(
    sandbox={"enabled": True},
    permission_mode="acceptEdits",  # Was "bypassPermissions"
)
```

### Phase 2 (Later)
- Linux: Call `bwrap` binary directly from Python
- macOS: Call `sandbox-exec` directly from Python
- Windows: Warn user, no sandbox

---

## Key Files to Modify

1. `src/pflow/nodes/claude/claude_code.py` - Add sandbox param (Phase 1)
2. `src/pflow/nodes/shell/shell.py` - Add sandbox wrapper (Phase 2)
3. `src/pflow/core/settings.py` - Add security settings
4. New: `src/pflow/nodes/shell/sandbox/` - Backend implementations

---

## Don't Forget

- Change `permission_mode` from `"bypassPermissions"` to `"acceptEdits"`
- Add graceful fallback when sandbox unavailable
- Consider stricter defaults for MCP server context
- Test that legitimate commands (git, grep) still work in sandbox
