# Progress Log: Namespace Collision Bug Fix

## Summary

**Bug**: Node IDs or workflow inputs matching parameter names caused silent failures. Template-resolved values were overwritten by namespace dicts or raw inputs.

**Solution**: Removed the "shared store fallback" pattern entirely. Nodes now read only from `self.params`. Templates are the explicit wiring mechanism.

---

## Timeline

### Phase 1: Investigation and Analysis

**Actions:**
1. Read bug report and reproduction cases in `scratchpads/namespace-collision-bug/`
2. Launched 6 parallel pflow-codebase-searcher subagents to investigate:
   - NamespacedSharedStore implementation
   - Parameter fallback pattern across all nodes
   - Template resolution flow
   - Workflow input handling
   - NamespacedNodeWrapper behavior
   - Existing validation systems

**Key Findings:**

1. **The pattern was NOT from PocketFlow** - PocketFlow treats params and shared store as completely separate channels. The fallback pattern was introduced in Task 11 (first file nodes) with no documented rationale.

2. **The pattern conflicts with namespacing** - Task 9 added namespacing which creates `shared[node_id] = {...}` dicts. The fallback pattern `"images" in shared` returns True when it finds the namespace dict.

3. **Templates make the fallback redundant** - The template system `${var}` already wires shared store values into params. The fallback was a pre-template convenience that's now causing bugs.

4. **~60 parameters across 20 nodes affected** - Every platform node uses the vulnerable pattern.

---

### Phase 2: Decision Making

**Options Considered:**

| Option | Description | Verdict |
|--------|-------------|---------|
| Filter namespaces | Hide node namespace dicts via heuristics | Rejected - band-aid, doesn't fix semantic issue |
| Invert priority | Check params first, then shared | Rejected - still has implicit fallback |
| **Remove fallback** | Nodes read only from params | **Chosen** - explicit, clean, aligns with PocketFlow |
| Add collision detection | Error at compile time | Not needed after removing fallback |

**Key Insight from Discussion:**

User asked: "Why would collision detection be needed if we use params-only?"

This led to the realization that **with params-only, naming collisions don't matter**. Templates explicitly declare data flow, so there's no implicit connection based on naming. Collision detection is unnecessary with the correct design.

---

### Phase 3: Implementation

**Approach:** Used parallel subagents for bulk mechanical changes, handled complex parts myself.

#### Batch 1: Node Implementation Updates (Subagents)

| Batch | Files | Subagent | Status |
|-------|-------|----------|--------|
| File nodes | 5 | code-implementer | ✅ |
| Git nodes | 6 | code-implementer | ✅ |
| GitHub nodes | 4 | code-implementer | ✅ |
| HTTP/Shell/Test/Claude | 4 | code-implementer | ✅ |

**Myself:** Updated LLM node (the bug reproduction case) manually.

#### Pattern Variants Replaced:

```python
# Variant 1: or pattern (most common)
shared.get("x") or self.params.get("x")  →  self.params.get("x")

# Variant 2: ternary pattern
shared.get("x") if "x" in shared else self.params.get("x")  →  self.params.get("x")

# Variant 3: explicit check pattern (write_file content)
if "x" in shared: ... elif "x" in self.params: ...  →  self.params.get("x")
```

#### Batch 2: Test Updates (Subagents)

Multiple rounds of test fixes were needed:

| Round | Tests Fixed | Subagent |
|-------|-------------|----------|
| 1 | HTTP, HTTP binary, LLM, Shell, GitHub tests | test-writer-fixer |
| 2 | Claude Code, Echo tests | test-writer-fixer |
| 3 | Git integration tests | test-writer-fixer |

**Total tests updated:** ~150 tests

#### Batch 3: Documentation Updates (Myself)

Updated these files:
- `src/pflow/nodes/CLAUDE.md` - New "Parameter-Only Pattern" section
- `src/pflow/nodes/github/CLAUDE.md` - Updated examples
- `architecture/core-concepts/shared-store.md` - "Parameters take precedence"
- `architecture/reference/node-reference.md` - New pattern documentation
- `architecture/features/simple-nodes.md` - Updated examples
- `architecture/guides/ai-agent-context.md` - Updated examples
- `architecture/implementation-details/metadata-extraction.md` - Updated examples

#### Batch 4: Decision Documentation (Myself)

Added comprehensive decision record to `.taskmaster/knowledge/decisions.md`

---

### Phase 4: Interface Docstring Updates

**Discovery:** During code review, realized that node Interface docstrings still used the old format:
```
- Reads: shared["url"]: str  # API endpoint
```

This was misleading because:
1. Nodes no longer read from shared store
2. The metadata extractor maps `Reads` to `inputs`, but everything is now in `params`
3. The context builder already merges `inputs` and `params` together anyway

**Solution:** Changed all `- Reads: shared["key"]` to `- Params: key` format.

#### Batch 5: Docstring Updates (Parallel Subagents)

| Batch | Files | Subagent | Status |
|-------|-------|----------|--------|
| File nodes | 5 | code-implementer | ✅ |
| Git nodes | 6 | code-implementer | ✅ |
| GitHub nodes | 4 | code-implementer | ✅ |
| HTTP/LLM/Shell/Claude | 4 | code-implementer | ✅ |
| Test nodes | 4 | code-implementer | ✅ |

**Pattern Changed:**
```python
# Before:
- Reads: shared["url"]: str  # API endpoint

# After:
- Params: url: str  # API endpoint
```

**Special Case - `confirm_delete`:**
```python
# New notation for security-required shared store values:
- Shared: confirm_delete: bool  # MUST be set in shared store (security requirement)
```

#### Test Fixes for Docstring Changes

Two tests expected `inputs` but now need `params`:
- `tests/test_registry/test_metadata_extractor.py` - Updated to check `params`
- `tests/test_nodes/test_http/test_http_discovery.py` - Updated to check `params`

---

### Phase 5: Final Verification

**Bug Reproduction Cases:**
```bash
# Node ID collision - FIXED ✅
uv run pflow scratchpads/namespace-collision-bug/reproduce.json
# Output: Workflow completed successfully, LLM processed image

# Workflow input collision - FIXED ✅
uv run pflow scratchpads/namespace-collision-bug/reproduce-input.json url="https://example.com"
# Output: Jina Reader markdown (proves URL was transformed correctly)
```

**Test Suite:** 3631 passed, 119 skipped ✅
**Make Check:** All passing ✅

---

## Deviations from Initial Plan

### 1. More Test Updates Than Expected

**Plan:** Update ~3 test files identified in grep search
**Reality:** Had to update ~15 test files across multiple subagent runs

**Why:** The initial grep only found tests with the pattern inline. Many tests put data in `shared` expecting nodes to read it (integration tests, feature tests), which wasn't caught by pattern matching.

### 2. Documentation More Extensive Than Planned

**Plan:** Update 3 docs (nodes/CLAUDE.md, shared-store.md, node-reference.md)
**Reality:** Updated 7 documentation files

**Why:** The fallback pattern was documented in multiple places as "THE pattern to use." All needed updating for consistency.

### 3. Test Naming Patterns Updated

**Plan:** Just fix test implementations
**Reality:** Also renamed tests to reflect new behavior

**Examples:**
- `test_prep_extracts_inputs_with_fallback` → `test_prep_extracts_inputs_from_params`
- `test_shared_takes_precedence_over_params` → Removed entirely
- `test_stdin_shared_takes_precedence` → `test_stdin_from_params_not_overridden_by_shared`

---

## Key Insights Learned

### 1. Implicit Behavior Creates Subtle Bugs

The fallback pattern seemed convenient ("just name things the same and it works!") but created a class of bugs that were:
- Silent (no error raised)
- Cryptic (type mismatch deep in execution)
- Non-obvious (naming ≠ the problem)

**Lesson:** Explicit > Implicit, even if it requires more typing.

### 2. Templates Are The Right Abstraction

Templates like `${node.output}` provide:
- Explicit data flow declaration
- Clear dependencies in IR
- No naming collisions possible
- Self-documenting workflows

The fallback pattern was a pre-template workaround that became technical debt.

### 3. PocketFlow's Design Was Right

PocketFlow's original design had clean separation:
- `params` = static configuration
- `shared` = explicit data flow in `prep()`/`post()`

pflow's "innovation" of mixing them created the bug. Returning to PocketFlow's philosophy fixed it.

### 4. Parallel Subagents Very Effective

Running 6 investigation subagents in parallel provided comprehensive context in one round trip. Running 5 test-fixing subagents in parallel fixed most tests quickly.

**Pattern:** For large mechanical changes, batch by category and parallelize.

### 5. Test Updates Reveal True Scope

The initial code change was ~200 lines across 20 files. The test updates were ~1000+ lines across ~15 files. Tests often reveal the true scope of a semantic change.

---

## Files Changed Summary

### Node Implementations (23 files)
- `src/pflow/nodes/file/*.py` (5 files) - code + docstrings
- `src/pflow/nodes/git/*.py` (6 files) - code + docstrings
- `src/pflow/nodes/github/*.py` (4 files) - code + docstrings
- `src/pflow/nodes/http/http.py` - code + docstrings
- `src/pflow/nodes/llm/llm.py` - code + docstrings (2 docstrings)
- `src/pflow/nodes/shell/shell.py` - code + docstrings
- `src/pflow/nodes/claude/claude_code.py` - code + docstrings (2 docstrings)
- `src/pflow/nodes/test/echo.py` - code + docstrings
- `src/pflow/nodes/test_node.py` - docstrings only
- `src/pflow/nodes/test_node_retry.py` - docstrings only
- `src/pflow/nodes/test_node_structured.py` - docstrings only

### Documentation (9 files)
- `src/pflow/nodes/CLAUDE.md`
- `src/pflow/nodes/github/CLAUDE.md`
- `architecture/core-concepts/shared-store.md`
- `architecture/reference/node-reference.md`
- `architecture/features/simple-nodes.md`
- `architecture/guides/ai-agent-context.md`
- `architecture/implementation-details/metadata-extraction.md`
- `.taskmaster/knowledge/decisions.md`
- `scratchpads/namespace-collision-bug/implementation/plan.md`

### Tests (~17 files)
- `tests/test_nodes/test_file/*.py`
- `tests/test_nodes/test_git/*.py`
- `tests/test_nodes/test_github/*.py`
- `tests/test_nodes/test_http/*.py` (including test_http_discovery.py)
- `tests/test_nodes/test_llm/*.py`
- `tests/test_nodes/test_shell/*.py`
- `tests/test_nodes/test_claude/*.py`
- `tests/test_nodes/test_echo.py`
- `tests/test_runtime/test_namespacing*.py`
- `tests/test_integration/test_git_*.py`
- `tests/test_registry/test_metadata_extractor.py`

---

## Metrics

| Metric | Count |
|--------|-------|
| Node files updated (code) | 20 |
| Node files updated (docstrings) | 23 |
| Parameters changed (code) | ~60 |
| Interface entries changed (docstrings) | ~65 |
| Test files updated | ~17 |
| Tests modified | ~150 |
| Documentation files | 9 |
| Subagent runs | ~20 |
| Total implementation time | ~3 hours |

---

## What's Left To Do

### Immediate
- [x] Run final test suite - 3631 passed ✅
- [x] Run `make check` - All passing ✅
- [x] Manual verification - Bug reproduction cases fixed ✅

### Before Merge
- [x] Add high-value regression tests for the exact bugs fixed
- [x] Update all CLAUDE.md and reference docs with correct information
- [ ] Stage all changes (node code, docstrings, tests, docs)
- [ ] Commit with clear message
- [ ] Create PR if needed

### Post-Merge
- [ ] Monitor for regressions
- [ ] Update main CLAUDE.md task list if needed

---

## Regression Tests Added

### New Test File: `tests/test_runtime/test_namespace_collision_regression.py`

**15 tests** covering the exact bugs fixed and new semantic behaviors:

| Test Class | Tests | Purpose |
|------------|-------|---------|
| `TestNodeIDCollisionRegression` | 3 | Node ID matching param name doesn't cause collision |
| `TestWorkflowInputCollisionRegression` | 2 | Workflow input matching param name doesn't override template |
| `TestStaticParamNotOverridden` | 2 | Static params win over same-named inputs |
| `TestFalsyValuePreservation` | 5 | Falsy values (0, False, "", None) are preserved |
| `TestTemplateResolutionStillWorks` | 3 | Templates still resolve correctly |

**Critical regression tests:**
1. `test_node_named_images_does_not_collide_with_llm_images_param` - The exact LLM + images bug
2. `test_input_named_url_does_not_override_http_url_template` - The exact HTTP + url bug

**Semantic change tests:**
1. `test_static_url_param_not_overridden_by_input` - Verifies static params are respected
2. `test_falsy_values_not_overridden_by_shared_store` - Verifies falsy values aren't fallen through

These tests ensure the bug cannot be reintroduced without detection.

---

## Documentation Cleanup (Phase 6)

After adding regression tests, analyzed all CLAUDE.md and reference docs for outdated information.

### Files Updated

| File | Change |
|------|--------|
| `src/pflow/nodes/CLAUDE.md` | Removed "parameter fallback" from Key Rules (lines 148-151), aligned with Parameter-Only Pattern |
| `src/pflow/nodes/git/CLAUDE.md` | Updated example at line 303 to use `self.params.get()` |
| `architecture/reference/node-reference.md` | Updated 2 code examples (lines 74, 162) to params-only pattern |
| `architecture/reference/enhanced-interface-format.md` | Renamed "Exclusive Params Pattern" to "Params Pattern", updated example |
| `.taskmaster/knowledge/patterns.md` | Replaced "Truthiness-Safe Parameter Fallback" with "Parameter-Only Access (CURRENT)", marked "Shared Store Inputs as Automatic Parameter Fallbacks" as DEPRECATED, added "Template-Based Data Flow" pattern |

### Files Not Updated (by design)

- **`.taskmaster/tasks/`** - Historical task records (documents what was done)
- **`.taskmaster/knowledge/decision-deep-dives/`** - Historical research
- **`pocketflow/research/`** - External pattern analysis, not actively referenced
- **`scratchpads/`** - Bug fix documentation (already correct)

### Updated Test Count

- **Regression tests**: 15 passed
- **Full suite**: 3646 passed, 119 skipped
