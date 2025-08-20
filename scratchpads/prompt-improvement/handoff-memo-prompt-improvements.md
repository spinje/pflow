# Handoff Memo: Prompt Improvements and Test Philosophy

**TO THE NEXT AGENT**: Read this entire memo before starting. When done, confirm you're ready to begin. DO NOT start implementing until you understand the patterns and pitfalls described here.

## 🎯 Critical Context You Need to Know

### The Big Realization That Changed Everything
We started fixing a "simple" issue - the discovery prompt was showing nodes when it should only show workflows. But this revealed a deeper problem: **the entire test suite was testing implementation details rather than behavior**. Tests were checking if prompts contained exact strings like "COMPLETELY satisfies" or "even 20% relevance". This is insane - every minor prompt tweak broke tests.

### The Pattern We Established (Use This for Other Prompts)

1. **Data should be self-documenting via XML tags**:
   ```xml
   <available_nodes>
   {{nodes_context}}
   </available_nodes>

   <available_workflows>
   {{workflows_context}}
   </available_workflows>
   ```
   NOT redundant headers inside like `## Available Nodes`

2. **Use numbered lists for clarity**:
   ```
   1. node-name - description
   2. another-node - description
   ```
   NOT markdown headers everywhere

3. **Separate context builders for different data types**:
   - `build_nodes_context()` - just nodes
   - `build_workflows_context()` - just workflows
   - NOT one monolithic `build_discovery_context()` mixing everything

## ⚠️ Critical Files and Their Roles

### Prompt Files (`src/pflow/planning/prompts/`)
- **discovery.md** - Should ONLY receive workflows (for reuse decisions)
- **component_browsing.md** - Receives BOTH nodes and workflows (for generation)
- **workflow_generator.md** - Likely needs the same treatment
- **parameter_mapping.md** - Probably has similar issues
- **metadata_generation.md** - Check for redundant headers

### Node Files (`src/pflow/planning/nodes.py`)
- **WorkflowDiscoveryNode** - Lines 95-115: Uses `build_workflows_context()` ONLY
- **ComponentBrowsingNode** - Lines 285-310: Uses BOTH `build_nodes_context()` AND `build_workflows_context()`
- Other nodes probably need similar updates

### Context Builder (`src/pflow/planning/context_builder.py`)
- Lines 480-530: `build_nodes_context()` - Clean numbered list, no headers
- Lines 533-566: `build_workflows_context()` - Clean numbered list, no headers
- Lines 412-477: `build_discovery_context()` - DEPRECATED, kept for compatibility

## 🚨 Test Anti-Patterns to ELIMINATE

### BAD - Testing Prompt Strings:
```python
# DON'T DO THIS
assert "COMPLETELY satisfies" in prompt
assert "even 20% relevance" in prompt
assert "BE OVER-INCLUSIVE" in prompt
```

### GOOD - Testing Behavior:
```python
# DO THIS
assert result["found"] is True  # Test the outcome
assert "node_ids" in result      # Test the structure
assert shared["planning_context"] == mock_value  # Test data flow
```

### Files With Tests That Need This Treatment:
- `tests/test_planning/unit/test_shared_store_contracts.py` - FIXED, use as reference
- `tests/test_planning/unit/test_browsing_selection.py` - FIXED, use as reference
- `tests/test_planning/unit/test_discovery_error_handling.py` - FIXED, use as reference
- Other test files likely have the same issues

## 🔍 Discoveries That Will Save You Hours

1. **The linter auto-modifies files** - After any edit, files get trailing whitespace removed and newlines added. Don't fight it, just run `make check` twice.

2. **build_discovery_context doesn't exist anymore** - Tests looking for it will fail. Use `build_workflows_context` for discovery, or both `build_nodes_context` + `build_workflows_context` for browsing.

3. **The prompt frontmatter is sacred** - NEVER manually edit the YAML frontmatter in prompt .md files. It's auto-maintained by test tools.

4. **Test quality > quantity** - We removed several tests that were just checking constructor parameters or duplicate functionality. If you see `test_init_configurable_parameters`, delete it.

5. **The planning flow is two-path**:
   - Path A (fast): Discovery finds match → Parameter mapping → Done
   - Path B (slow): Discovery fails → Component browsing → Generation → Validation → Done
   - Discovery is the gatekeeper - its accuracy determines 2-second vs 20-second response

## 📂 Key Documentation

- `docs/CLAUDE.md` - Overall implementation guidance
- `pocketflow/CLAUDE.md` - PocketFlow framework patterns
- `tests/test_planning/CLAUDE.md` - Test organization guide (shows directory structure)
- `src/pflow/planning/prompts/README.md` - Prompt testing guidance

## 🎭 The Philosophy Change

The user said "quality over quantity" and they meant it. This applies to:
1. **Prompts**: Clear, simple, no redundancy
2. **Tests**: Test behavior, not implementation
3. **Code**: Better to have 10 excellent functions than 100 mediocre ones

## 🔗 Specific Patterns to Apply to Other Prompts

When you look at other prompts like `workflow_generator.md` or `parameter_mapping.md`:

1. **Check for redundant headers** - If the XML tag says `<available_components>`, you don't need `## Available Components` inside
2. **Check for mixed data** - Should this prompt see nodes? Workflows? Both? Neither?
3. **Update the node's prep()** - Use the appropriate context builder functions
4. **Fix the tests** - Remove string matching, focus on behavior
5. **Run the trace** - Use `scripts/analyze-trace/` to see what the prompts actually receive

## ⚡ Performance Implications

The discovery prompt is THE performance bottleneck:
- If it incorrectly returns `found=true` for a partial match → fails at parameter extraction
- If it incorrectly returns `found=false` for a good match → wastes time regenerating existing workflow

This same principle likely applies to other prompts in the chain.

## 🐛 Subtle Bugs We Found

1. **Test nodes showing in discovery** - We were showing ALL nodes to discovery when it should only see workflows
2. **Prompt text brittleness** - Tests broke on "20%" → "50%" change in prompt text
3. **Mock pollution** - Some test files had persistent mocks that broke other tests

## 🎬 Your Starting Point

1. Run `make test` to ensure everything still passes
2. Pick a prompt file (suggest `workflow_generator.md` or `parameter_mapping.md`)
3. Check what data it receives via the trace: `scripts/analyze-trace/`
4. Apply the patterns:
   - Remove redundant headers
   - Use numbered lists
   - Separate data types with clear XML tags
5. Update the corresponding node in `nodes.py`
6. Fix the tests to remove string matching
7. Run `make check` (twice, the linter will modify files)

## 🚫 Do NOT

- Change prompt frontmatter manually
- Test for specific prompt text
- Mix different data types in one context
- Create new monolithic context builders
- Keep tests that only verify constructor parameters

---

**REMEMBER**: The goal is prompts that are clear to LLMs and tests that verify the system works, not that prompts contain magic words. Quality over quantity in everything.

**TO THE NEXT AGENT**: Confirm you've read and understood this memo before starting implementation.