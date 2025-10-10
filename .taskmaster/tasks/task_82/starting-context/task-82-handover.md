# Task 82: Binary Data Support - Critical Context Handoff

**⚠️ READ THIS COMPLETELY BEFORE IMPLEMENTING - DO NOT START UNTIL YOU'VE ABSORBED THIS CONTEXT**

---

## 🔴 The Hidden Journey (What This Really Is)

This task started as a **bug fix** for a crash in `instrumented_wrapper.py:867`. We discovered it was actually exposing a **fundamental architectural gap** - pflow has ZERO binary data support. Every node assumes text. The HTTP node literally calls `response.text` on binary data, corrupting it.

The user originally just wanted their Spotify workflow to work (downloading album art). We went through Options A→B→C→D, ultimately choosing D-full (system-wide base64 contract) because partial solutions would create inconsistent behavior.

**Key insight**: The shared store CAN handle bytes perfectly (it's just a Python dict). The ONLY blocker is `template_resolver.py:284` which calls `str()` on everything. We're using base64 to avoid touching that core system.

---

## 🚨 The Namespacing Trap (You WILL Hit This)

**This will waste hours if you don't know**: You cannot pass metadata between nodes through the shared store.

I initially thought we could do:
```python
# HTTP node
shared["response_encoding"] = "base64"  # ❌ WRONG
```

But with namespacing (enabled by default), HTTP writes to `shared["http_node_id"]["response_encoding"]` and write-file can NEVER see it. Write-file only sees its own namespace and root level.

**The solution**: Use suffix convention on the SAME key:
```python
shared["response"] = base64_string
shared["response_is_binary"] = True  # ✅ Same namespace!
```

Templates `${node.response}` and `${node.response_is_binary}` both resolve correctly.

**Source proof**: `/Users/andfal/projects/pflow/scratchpads/base64-encoding-solution/namespacing-analysis.md`

---

## 🎯 The Real Test (Not Unit Tests)

The actual failing workflow is `.pflow/workflows/spotify-art-generator.json`. Nodes 11-18 download and save images. Currently crashes at node 11 (`download-seedream-orig`).

After your implementation, this command MUST work:
```bash
uv run pflow --trace .pflow/workflows/spotify-art-generator.json \
  sheet_id="1vON91vaoXqf4ITjHJd_yyMLLNK0R4FXVSfzGsi1o9_Y"
```

Success = 4 album art images saved to `generated-images/` directory.

---

## 💡 Surprising Discoveries About the Codebase

1. **No size limits anywhere** - The shared store has NO limits. Those `PFLOW_TRACE_*_MAX` variables only affect debug traces, not execution.

2. **Trace already handles bytes** - `workflow_trace.py:387-389` already detects and handles bytes, proving the system can work with them.

3. **Write-file has atomic writes** - It uses temp files, so you just need to add binary mode, the safety is already there.

4. **HTTP node structure** - It returns a dict from `exec()` with the response, then `post()` stores it. You need to pass `is_binary` through this chain.

5. **Shell node is stateful** - If you add `self._is_binary` in `exec()`, you can access it in `post()`.

---

## ⚠️ The Template Resolution Temptation

You might think "why not just fix template resolution to preserve bytes?" I spent hours investigating this. It would require:

1. Changing `resolve_string()` return type from `str` to `Any`
2. Updating type hints through the entire wrapper chain
3. Handling complex templates like `"Hello ${name}"` when name is bytes
4. Unknown downstream impacts

We chose base64 to avoid this rabbit hole. **Don't revisit this decision** - it's documented in the spec's Epistemic Appendix.

---

## 🐛 Testing Pitfalls I Discovered

1. **Mock at requests level** - Don't mock node methods for integration tests
2. **Binary corruption is silent** - Text mode on binary gives mojibake, not errors
3. **Platform differences** - Shell binary tests vary by OS (echo behavior)
4. **The wrapper chain** - InstrumentedWrapper is the OUTERMOST wrapper, it sees final output

---

## 🛑 What NOT to Change

1. **Template resolver** - Don't touch it, even if it seems like the "right" fix
2. **Shared store structure** - It stays as a dict
3. **Namespacing system** - Work within its constraints
4. **Existing text paths** - Must remain 100% unchanged for backward compatibility

---

## 📊 Performance Reality

Base64 adds 33% overhead. For the Spotify use case (500KB images), this is ~165KB extra per image. Totally acceptable. We documented a 50MB soft limit but there's no actual enforcement needed - just log a warning.

Python's base64 module is C-optimized, encoding/decoding is fast.

---

## 🔗 Critical Files You'll Need

- **The bug investigation**: `/Users/andfal/projects/pflow/scratchpads/pflow-binary-data-bug/`
- **Namespacing analysis**: `/Users/andfal/projects/pflow/scratchpads/base64-encoding-solution/`
- **Why not direct bytes**: `/Users/andfal/projects/pflow/scratchpads/binary-data-handling/alternative-approaches-analysis.md`
- **Performance analysis**: `/Users/andfal/projects/pflow/scratchpads/base64-binary-data-analysis/performance-and-size-analysis.md`

---

## 🧠 The Evolution of Thinking

We went through this progression:
1. **Option A**: Just fix the crash → Doesn't solve the problem
2. **Option B**: Direct bytes support → Requires template resolver changes
3. **Option C**: Base64 with auto-detection → Fragile heuristics
4. **Option D-minimal**: Just HTTP+write-file → Inconsistent
5. **Option D-full**: All 4 nodes → Correct choice for consistency

The user pushed for D-full because partial solutions create confusing behavior.

---

## 🎪 The Parallel Agent Research

I deployed 4 parallel agents to investigate. Key findings:
- Agent 1: Discovered namespacing blocks metadata
- Agent 2: Confirmed no size limits in execution path
- Agent 3: Found shared store already handles bytes perfectly
- Agent 4: Identified all nodes needing changes

This parallel investigation saved hours and revealed the namespacing issue early.

---

## 🔮 What Would Make Me Furious If I Forgot

1. **The crash is already fixed** - I added type guards to `instrumented_wrapper.py`. Don't revert this.

2. **Line 834 is the real problem** - `_unwrap_mcp_response()` returns `output.get("response")` which can be ANY type, not just dict.

3. **Binary flags are NOT optional** - Without them, write-file can't know to decode base64.

4. **The planner doesn't need changes** - It just sees new outputs in node metadata.

5. **You need to update Interface docs** - Or the planner won't know about `_is_binary` outputs.

---

## ✅ Pre-Implementation Checklist

Before you start:
1. □ Read the spec (task-82-spec.md)
2. □ Read the research findings (implementation-research-findings.md)
3. □ Review the code examples (code-examples.md)
4. □ Understand why namespacing blocks metadata
5. □ Accept that base64 overhead is fine
6. □ Know that the Spotify workflow is your real test

---

## 🎯 Success Criteria

You've succeeded when:
1. The Spotify workflow downloads and saves album art correctly
2. All existing text workflows still pass
3. Binary and text can coexist in the same workflow
4. The test suite covers both paths

---

**Remember**: This isn't elegant, but it's correct. We're adding base64 encoding to work around a single line in template resolution. That's pragmatic engineering.

---

**DO NOT START IMPLEMENTING YET** - First, confirm you understand:
1. Why we can't pass metadata between nodes
2. Why we're using base64 instead of bytes
3. What the real test workflow is
4. Why all 4 nodes need changes

Reply with "Ready to implement Task 82 with base64 contract" when you've absorbed this context.