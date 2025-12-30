# Namespace Collision Bug

## Two Types of Collision

### Type 1: Node ID Collision
```bash
# This will fail with "Image must be a string (URL or path), got: dict"
uv run pflow scratchpads/namespace-collision-bug/reproduce.json
```

**Root cause:** Node named `images` creates `shared["images"] = {stdout: ...}`, LLM node finds it and uses it instead of the template-resolved param.

### Type 2: Workflow Input Collision (NEW)
```bash
# This will call wrong URL (ignores the Jina prefix!)
uv run pflow scratchpads/namespace-collision-bug/reproduce-input.json url="https://example.com"
```

**Root cause:** Input named `url` creates `shared["url"] = "https://example.com"`, HTTP node finds it and uses it instead of the template `https://r.jina.ai/${url}`.

## The Fix (Workaround)

### For Node ID Collision
Rename the node from `images` to `extract-images`.

### For Input Collision
Rename the input from `url` to `target_url`.

## Full Bug Report

See [bug-report.md](./bug-report.md) for complete analysis including:
- Complete list of 50+ vulnerable parameters across all nodes
- Proposed fixes (4 options)
- Test cases needed

## Key Insight

Both bugs occur because nodes use this pattern:
```python
value = shared.get("param") or self.params.get("param")
```

If `shared["param"]` exists (from node namespace OR workflow input), it's used instead of the template-resolved param.

## Affected Names (Avoid These!)

**For node IDs AND workflow inputs:**
- `url`, `images`, `prompt`, `content`, `body`, `data`
- `file_path`, `source_path`, `dest_path`, `path`
- `message`, `title`, `repo`, `branch`, `base`, `head`
- `stdin`, `command`, `headers`, `params`, `timeout`
- `state`, `limit`, `count`, `files`, `pattern`
