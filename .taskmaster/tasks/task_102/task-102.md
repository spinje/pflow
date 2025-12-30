# Task 102: Remove Parameter Fallback Pattern

## Status: ✅ Completed

## Problem Statement

Node IDs or workflow inputs matching parameter names cause silent failures due to the "shared store fallback" pattern that all nodes use.

### Bug 1: Node ID Collision
```json
{
  "nodes": [
    {"id": "images", "type": "shell", "params": {"command": "echo '[]'"}},
    {"id": "llm", "type": "llm", "params": {"images": "${item}"}}
  ]
}
```
- Node "images" creates `shared["images"] = {stdout: ..., exit_code: ...}` (namespace dict)
- LLM node's fallback pattern `shared.get("images") or params.get("images")` finds the dict
- LLM fails with "Image must be a string, got: dict"

### Bug 2: Workflow Input Collision
```json
{
  "inputs": {"url": {"type": "string"}},
  "nodes": [{"type": "http", "params": {"url": "https://r.jina.ai/${url}"}}]
}
```
- Input creates `shared["url"] = "https://example.com"` at root level
- HTTP node's fallback pattern finds raw input, ignores template transformation
- HTTP calls wrong URL (missing Jina prefix)

### Root Cause

The "shared first" fallback pattern was introduced in Task 11 (first file nodes) without documented rationale. It conflicts with:
1. Automatic namespacing (Task 9) - creates `shared[node_id]` dicts
2. Template resolution - resolves `${var}` into `params`, but fallback checks shared first

## Proposed Solution

**Remove the fallback pattern entirely.** Nodes read only from `self.params`. Templates handle all data wiring explicitly.

### Before (Vulnerable)
```python
url = shared.get("url") or self.params.get("url")
```

### After (Safe)
```python
url = self.params.get("url")
```

### Rationale

1. **Aligns with PocketFlow's design** - PocketFlow treats params and shared store as separate channels
2. **Templates are the proper wiring mechanism** - `${var}` explicitly declares data flow
3. **Explicit > Implicit** - No magic based on naming coincidences
4. **No collision detection needed** - With params-only, naming collisions don't matter

## Acceptance Criteria

- [ ] All nodes read from `self.params` only (not shared store fallback)
- [ ] Bug reproduction cases pass
- [ ] Full test suite passes
- [ ] Documentation updated to reflect new pattern
- [ ] Regression tests added for collision scenarios

## Scope

- ~60 parameters across 20 node implementations
- Interface docstrings updated to use `- Params:` format
- Documentation updated in CLAUDE.md files
- Decision record added

## Related Tasks

- **Task 9**: Implement shared store collision detection using automatic namespacing
- **Task 11**: Implement read-file and write-file nodes (where fallback pattern was introduced)

## Resources

- Bug report: `scratchpads/namespace-collision-bug/bug-report.md`
- Reproduction cases: `scratchpads/namespace-collision-bug/reproduce*.json`
