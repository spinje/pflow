# Task 43: MCP Server Support - Implementation Handoff

## 🚨 Critical Discovery That Changes Everything

The registry is **MORE flexible than anyone assumed**. After deep investigation with the codebase searcher, I discovered:

- `Registry.save()` accepts **ANY** dictionary structure with **ZERO validation** (line 58-81 in `src/pflow/registry/registry.py`)
- Multiple registry entries CAN point to the same class - there's no check preventing this
- File paths don't need to exist - `"virtual://mcp"` works perfectly fine
- You can manually manipulate the registry JSON without going through the scanner

**This means what seemed like "hacks" are actually legitimate uses of public APIs.**

## 🎯 The Implementation Strategy We Chose (and Why)

After evaluating 8 different architectural options (see `.taskmaster/tasks/task_43/starting-context/architectural-assessment.md`), we chose **Option 1 + Option 8**:

1. **Direct Registry Manipulation** - Use `Registry.save()` to add MCP tools as virtual nodes
2. **Compiler Metadata Injection** - Follow the existing `__registry__` pattern (line 282-284 in compiler.py)

Why this combination wins:
- Only 3 lines needed in compiler
- Follows established patterns (not inventing new ones)
- Ships in ~2 days, not weeks
- No code generation, no complex factory patterns

## ⚠️ The Environment Variable Gap You MUST Address

**pflow does NOT have environment variable expansion yet!** The template resolver (`src/pflow/runtime/template_resolver.py`) uses `${var}` syntax but ONLY for context variables from the shared store, NOT environment variables.

You need to implement this. Look at `ShellNode` (line 186 in `src/pflow/nodes/shell/shell.py`) for the pattern:
```python
full_env = {**os.environ, **env} if env else None
```

But you'll also need to expand `${VAR}` syntax in the config. Consider using `os.path.expandvars()` or similar.

## 📍 Exact Code Locations You'll Touch

### Compiler Changes (3 lines!)
`src/pflow/runtime/compiler.py` around line 290:
```python
# Add this after the existing __registry__ injection
if node_type.startswith("mcp-"):
    params = params.copy()  # CRITICAL: Copy first like line 283 does!
    params["__mcp_server__"] = node_type.split("-")[1]
    params["__mcp_tool__"] = "-".join(node_type.split("-")[2:])
```

### Registry Manipulation
The registry is just JSON at `~/.pflow/registry.json`. You can load it, add entries, and save:
```python
registry = Registry()
nodes = registry.load()
nodes["mcp-github-create-issue"] = {
    "class_name": "MCPNode",
    "module": "pflow.nodes.mcp.node",
    "file_path": "virtual://mcp",  # This works!
    "interface": {...}
}
registry.save(nodes)
```

## 🔍 What I Verified vs What's Assumed

**Verified in codebase:**
- Registry accepts arbitrary structures ✅
- Compiler copies params dict before modifying ✅
- Nodes require parameterless constructors ✅
- `set_params()` method exists and works ✅
- Virtual file paths work ✅

**Still assumptions:**
- MCP servers follow JSON-RPC 2.0 exactly
- stdio servers only output valid JSON-RPC (no debug output mixed in)
- Environment variable expansion will work like shell expansion

## 🐛 Subtle Gotchas I Discovered

1. **The compiler MUST copy params** - Line 283 shows `params = params.copy()` with comment "Don't modify original". Follow this pattern or you'll have side effects.

2. **Node names with "mcp-" prefix** - The spec uses this for namespacing. Don't deviate or the compiler injection won't trigger.

3. **JSON-RPC messages MUST NOT contain embedded newlines** - They're newline-delimited. One message per line, no exceptions.

4. **Template pattern confusion** - `${var}` is already used by pflow but for different purposes. Don't accidentally break template resolution when adding env var support.

## 🏗️ Architectural Context

We explored generating Python files for each MCP tool (Option 3) but rejected it for clutter. We considered a factory pattern (Option 5) but it requires compiler changes. The beauty of our approach is that it uses existing infrastructure exactly as designed.

The key insight: **Virtual nodes** - registry entries that don't correspond to Python files but all execute through one `MCPNode` class.

## 📋 Implementation Checklist (Follow This Order!)

1. [ ] Create `MCPNode` class that reads `__mcp_server__` and `__mcp_tool__` from params
2. [ ] Add environment variable expansion (this is NEW functionality)
3. [ ] Add 3 lines to compiler for metadata injection
4. [ ] Create MCP configuration storage (`~/.pflow/mcp-servers.json`)
5. [ ] Implement `pflow mcp add` CLI command
6. [ ] Implement `pflow mcp sync` to discover and register tools
7. [ ] Test with a real MCP server (filesystem is simplest)

## 🔗 Essential Files to Study

- `.taskmaster/tasks/task_43/starting-context/architectural-assessment.md` - All 8 options we considered
- `.taskmaster/tasks/task_43/starting-context/mcp-implementation-strategy.md` - Detailed implementation plan
- `src/pflow/runtime/compiler.py` lines 282-296 - The __registry__ pattern to follow
- `src/pflow/registry/registry.py` lines 58-81 - How Registry.save() works
- `src/pflow/nodes/shell/shell.py` line 186 - Environment variable merging pattern

## 🎯 The Core Outcome

Task 43 enables pflow to execute ANY MCP server's tools as workflow nodes WITHOUT writing custom code for each one. Users configure an MCP server once, then all its tools become available as nodes like `mcp-github-create-issue`.

## ⚡ Why Speed Matters

MCP is only 2 months old (November 2024). Being first to market as "the MCP orchestrator" is more valuable than perfect architecture. Ship the MVP with stdio support, claim the space, iterate based on usage.

## 🔮 What Success Looks Like

```bash
# User configures once
$ pflow mcp add github -- npx @modelcontextprotocol/github

# Discovers all tools
$ pflow mcp sync github
→ Registered: mcp-github-create-issue, mcp-github-list-prs, ...

# Natural language just works
$ pflow "create github issue about the bug we found"
→ Planner selects mcp-github-create-issue node
→ Executes through universal MCPNode
```

---

**TO THE IMPLEMENTING AGENT:** Read this entire document, review the referenced files, and confirm you understand the strategy before beginning implementation. Do NOT start coding until you've absorbed the architectural context and understand why we chose Option 1 + Option 8. Say "I'm ready to implement Task 43 with the virtual node + compiler injection strategy" when you're prepared to begin.