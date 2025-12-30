# Task 102 Review: Remove Parameter Fallback Pattern

## Metadata
- **Implementation Date**: 2024-12-30
- **Branch**: `fix/namespace-collision`
- **Related Tasks**: Task 9 (Namespacing), Task 11 (First file nodes where pattern originated)

## Executive Summary

Removed the "shared store fallback" pattern from all 20 platform nodes (~60 parameters) that caused silent failures when node IDs or workflow inputs matched parameter names. The fix aligns pflow with PocketFlow's original design philosophy where params and shared store are separate channels, with templates serving as the explicit data wiring mechanism.

## Implementation Overview

### What Was Built

**Original spec proposed 4 options:**
1. Filter namespaces from visibility (heuristic-based)
2. Invert priority (params first, then shared)
3. Add collision detection (compile-time errors)
4. Explicit namespace prefix (breaking change)

**What was actually implemented: None of the above.**

Through deep investigation, we discovered the root cause was the fallback pattern itself. The solution was simpler and more correct:
- **Remove the fallback entirely** - nodes read only from `self.params`
- **Templates handle all wiring** - `${var}` resolves from shared store into params
- **Collision detection unnecessary** - with params-only, naming collisions simply don't matter

### Implementation Approach

1. **Investigation Phase**: Launched 6 parallel subagents to understand:
   - NamespacedSharedStore implementation
   - All nodes using fallback pattern
   - Template resolution flow
   - Workflow input handling
   - PocketFlow's original design

2. **Key Discovery**: The fallback pattern was introduced in Task 11 (file nodes) with NO documented rationale. It predates templates and conflicts with namespacing (Task 9).

3. **Execution**: Parallel subagents for mechanical changes, manual review for complex parts.

## Files Modified/Created

### Core Changes

**Node Implementations (20 files)**
| Path | Parameters Changed |
|------|-------------------|
| `src/pflow/nodes/file/read_file.py` | file_path, encoding |
| `src/pflow/nodes/file/write_file.py` | content, file_path, encoding, content_is_binary |
| `src/pflow/nodes/file/copy_file.py` | source_path, dest_path |
| `src/pflow/nodes/file/move_file.py` | source_path, dest_path |
| `src/pflow/nodes/file/delete_file.py` | file_path |
| `src/pflow/nodes/git/*.py` (6 files) | branch, remote, working_directory, message, files, etc. |
| `src/pflow/nodes/github/*.py` (4 files) | repo, issue_number, title, body, head, base, state, limit, etc. |
| `src/pflow/nodes/http/http.py` | url, method, body, headers, params, timeout, auth_token, api_key |
| `src/pflow/nodes/llm/llm.py` | prompt, system, images |
| `src/pflow/nodes/shell/shell.py` | stdin |
| `src/pflow/nodes/claude/claude_code.py` | prompt, output_schema |
| `src/pflow/nodes/test/echo.py` | message, count, data |

**Interface Docstrings (23 files)**
Changed `- Reads: shared["key"]` to `- Params: key` format to accurately reflect new behavior.

**Documentation (9 files)**
- `src/pflow/nodes/CLAUDE.md` - New "Parameter-Only Pattern" section
- `architecture/core-concepts/shared-store.md` - Updated precedence rules
- `.taskmaster/knowledge/decisions.md` - Added architectural decision record

### Test Files

**New File Created:**
- `tests/test_runtime/test_namespace_collision_regression.py` - 15 critical regression tests

**Files Updated (~17):**
- Tests that put data in `shared` expecting nodes to read it
- Tests explicitly verifying "shared-first" behavior
- Integration tests across file/git/github/http/llm/shell/claude nodes

## Integration Points & Dependencies

### Incoming Dependencies
- **CLI** → Nodes via `compile_ir_to_flow()` - Passes initial_params which become template context
- **Planner** → Nodes via IR generation - Must generate templates for data flow
- **Template System** → Nodes via `TemplateAwareNodeWrapper` - Resolves `${var}` into params

### Outgoing Dependencies
- **Nodes** → `self.params` only - No more shared store reads for declared parameters
- **Nodes** → Shared store for outputs only - Write via `shared["key"] = value`

### Critical Coupling
**Template resolution MUST happen before node execution.**

The wrapper chain order is critical:
```
TemplateAwareNodeWrapper (resolves ${var} into params)
  → NamespacedNodeWrapper (isolates writes)
    → InstrumentedNodeWrapper (metrics/tracing)
      → ActualNode (reads from self.params)
```

## Architectural Decisions & Tradeoffs

### Key Decisions

| Decision | Reasoning | Alternative Rejected |
|----------|-----------|---------------------|
| Remove fallback entirely | Aligns with PocketFlow philosophy, templates handle wiring | Filter namespaces (heuristic-based, band-aid) |
| Params-only pattern | Explicit > implicit, no magic based on naming | Invert priority (still implicit fallback) |
| No collision detection | Unnecessary with params-only design | Would add complexity for no benefit |
| Update Interface docstrings | `Reads: shared["x"]` was now misleading | Leave as-is (confusing for future agents) |

### Technical Debt Incurred

None. This task reduced technical debt by:
1. Removing undocumented pattern that conflicted with namespacing
2. Aligning with PocketFlow's design philosophy
3. Making data flow explicit through templates

## Testing Implementation

### Test Strategy Applied

1. **Regression tests first**: Created tests for exact bugs before implementation
2. **Behavioral tests**: Verified new semantics (static params win, falsy values preserved)
3. **Integration verification**: Full test suite must pass

### Critical Test Cases

| Test | What It Catches |
|------|-----------------|
| `test_node_named_images_does_not_collide_with_llm_images_param` | The exact LLM + namespace dict bug |
| `test_input_named_url_does_not_override_http_url_template` | The exact HTTP + raw input bug |
| `test_static_url_param_not_overridden_by_input` | Static params respected (new behavior) |
| `test_falsy_values_not_overridden_by_shared_store` | `0`, `False`, `""` preserved (behavioral change) |

## Unexpected Discoveries

### Gotchas Encountered

1. **Interface docstrings were misleading** - Discovered mid-implementation that `- Reads: shared["key"]` format was now wrong. Required updating 23 files.

2. **More tests than expected** - Initial grep found ~3 test files. Actual count was ~17 because many integration tests put data in `shared` expecting nodes to read it.

3. **Three pattern variants existed**:
   - `shared.get("x") or params.get("x")` (most common)
   - `shared.get("x") if "x" in shared else params.get("x")` (HTTP, LLM)
   - `if "x" in shared: ... elif "x" in params: ...` (write_file content)

### Edge Cases Found

1. **Falsy values**: Old `or` pattern fell through on `0`, `False`, `""`. New pattern preserves them.
2. **None values**: `self.params.get("x")` returns `None` if not set, which is correct behavior.
3. **Required params**: Nodes should use `self.params["x"]` (KeyError) or explicit check for required params.

## Patterns Established

### Reusable Patterns

**The Params-Only Pattern (MANDATORY for all nodes):**
```python
# ✅ CORRECT - Read from params only
url = self.params.get("url")
timeout = self.params.get("timeout", 30)  # With default

# ❌ WRONG - Never use fallback
url = shared.get("url") or self.params.get("url")
```

**Template Wiring in IR:**
```json
{
  "inputs": {"api_url": {"type": "string"}},
  "nodes": [{
    "type": "http",
    "params": {"url": "${api_url}"}  // Explicit wiring via template
  }]
}
```

**Interface Docstring Format:**
```python
"""
Interface:
- Params: url: str  # API endpoint (required)
- Params: timeout: int  # Request timeout in seconds (default: 30)
- Writes: shared["response"]: str  # HTTP response body
"""
```

### Anti-Patterns to Avoid

1. **Never add shared store fallback** - The bug will return
2. **Never assume naming = wiring** - Use explicit templates
3. **Never use `Reads: shared["x"]` in docstrings** - Use `Params: x` format

## Breaking Changes

### Behavioral Changes

| Before | After |
|--------|-------|
| `shared["url"]` overrides `params["url"]` | `params["url"]` always used |
| Falsy values (`0`, `False`, `""`) fall through | Falsy values preserved |
| Naming collision = silent bug | Naming collision = no effect |

### No API Changes
External interfaces unchanged. Internal node behavior fixed.

## Future Considerations

### Extension Points

When creating new nodes:
1. Use `self.params.get("x")` pattern exclusively
2. Use `- Params:` format in Interface docstrings
3. Write to shared store for outputs only

### Potential Improvements

1. **Linter rule**: Detect `shared.get(...) or self.params.get(...)` pattern
2. **Template validation**: Could warn if param name matches node ID (educational, not blocking)

## AI Agent Guidance

### Quick Start for Related Tasks

**When implementing a new node:**
1. Read `src/pflow/nodes/CLAUDE.md` first (updated with params-only pattern)
2. Use `src/pflow/nodes/http/http.py` as reference implementation
3. Never read from shared store for declared parameters

**When debugging "wrong value" issues:**
1. Check if node ID matches a parameter name → Not a problem anymore
2. Check if workflow input matches a parameter name → Not a problem anymore
3. Check template syntax → `${var}` must be correctly formed

**Key files to understand the system:**
- `src/pflow/runtime/node_wrapper.py` - Template resolution
- `src/pflow/runtime/namespaced_store.py` - Namespace isolation
- `tests/test_runtime/test_namespace_collision_regression.py` - Critical regression tests

### Common Pitfalls

1. **Don't copy old node code blindly** - It might have the old fallback pattern
2. **Don't assume `shared["param"]` works** - Use templates in IR
3. **Don't forget Interface docstrings** - They must say `Params:` not `Reads: shared[...]`

### Test-First Recommendations

When modifying any node:
1. Run `pytest tests/test_runtime/test_namespace_collision_regression.py` first
2. Run the specific node's test file
3. Run full suite before committing

---

*Generated from implementation context of Task 102*
