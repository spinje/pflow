# Task 58 Review: Transform Workflow Generator Tests from Fantasy to Reality

## Metadata
- **Implementation Date**: September 5-8, 2025
- **Session IDs**: e04bc6ff-e0a6-439c-834b-780c9faa9bf8 (primary implementation)
- **Pull Request**: https://github.com/spinje/pflow/pull/18
- **Test Accuracy Achievement**: 53.3% → 100%

## Executive Summary
Replaced 15+ non-existent mock nodes in workflow generator tests with real nodes from the registry, implementing a templatization system that prevents value leakage to the LLM. This fundamental shift ensures tests validate actual executable workflows rather than imaginary capabilities, achieving 100% test accuracy.

## Implementation Overview

### What Was Built
A complete overhaul of the workflow generator testing system that:
- **Templatization pipeline**: Replaces discovered parameter values with `${param_name}` placeholders before LLM processing
- **Reality-based test suite**: 15 test cases using only real nodes (except 2 Slack MCP mocks)
- **Shell workarounds**: Creative use of shell node for missing git/GitHub features
- **Parallel test execution**: Added pytest-xdist reducing runtime from 2-3 minutes to 10-20 seconds
- **Strict validation framework**: Deep inspection for hardcoded values in any context

**Major deviation from spec**: The spec didn't anticipate the templatization solution. Original approach was to fix validation, but the real problem was the LLM seeing actual values.

### Implementation Approach
Instead of patching symptoms (validation errors), we addressed the root cause: the workflow generator was seeing actual values like "anthropic/pflow" and being told not to use them. The solution was to never show these values at all, only templates like `${repo_owner}/${repo_name}`.

## Files Modified/Created

### Core Changes
- `src/pflow/planning/nodes.py` - Added `_templatize_user_input()` to ParameterDiscoveryNode, modified WorkflowGeneratorNode to use templatized input
- `src/pflow/planning/prompts/workflow_generator.md` - Removed ir_version requirement, updated examples
- `tests/test_planning/llm/prompts/test_workflow_generator_prompt.py` - Complete rewrite with 15 real test cases
- `src/pflow/planning/context_builder.py` - Fixed to support test infrastructure

### Test Files
- `tests/test_planning/unit/test_parameter_transformation.py` - Migrated from MetadataGenerationNode to ParameterDiscoveryNode
- `tests/test_planning/integration/test_parameter_transformation_integration.py` - Updated for new templatization approach
- `tests/test_planning/llm/prompts/CLAUDE.md` - Added critical parallel execution requirements

**Critical tests**: All 15 test cases in `test_workflow_generator_prompt.py` are critical - they validate real workflows that users would create.

## Integration Points & Dependencies

### Incoming Dependencies
- **MetadataGenerationNode** → ParameterDiscoveryNode (via `shared["templatized_input"]`)
- **WorkflowGeneratorNode** → ParameterDiscoveryNode (via `shared["templatized_input"]`)
- **Test infrastructure** → Registry (for real node validation)

### Outgoing Dependencies
- **ParameterDiscoveryNode** → User input parsing
- **WorkflowGeneratorNode** → Planning context, browsed components
- **Tests** → pytest-xdist for parallel execution

### Shared Store Keys
- `templatized_input` - User input with values replaced by ${param_name} placeholders
- `discovered_params` - Original discovered parameters (unchanged)
- `browsed_components` - Must use format: `{"node_ids": [...], "workflow_names": [...], "reasoning": "..."}`

## Architectural Decisions & Tradeoffs

### Key Decisions

1. **Templatization at discovery time** → Prevents value leakage → Alternative: Post-process workflows (too late, values already used)
2. **Reuse shared store for templatized input** → Single source of truth → Alternative: Duplicate templatization in each node
3. **Shell workarounds for missing nodes** → Real executable workflows → Alternative: Add more mock nodes (defeats purpose)
4. **Strict validation with flexibility** → Catch real issues, allow good engineering → Alternative: Exact matching (too rigid)

### Technical Debt Incurred
- **Shell workarounds fragile**: Using shell for `git tag` and `gh release create` - should implement proper nodes
- **MCP mocks hardcoded**: Only 2 Slack MCP mocks, need dynamic MCP discovery
- **Test coupling**: Tests directly use `_templatize_user_input()` private method

## Testing Implementation

### Test Strategy Applied
- **Reality-first**: Every test uses real nodes that exist in production
- **Natural language**: Brief, realistic prompts from actual user patterns
- **Flexible validation**: Allow extra nodes for good engineering practices
- **Parallel execution**: All tests run concurrently for speed

### Critical Test Cases
- `changelog_from_issues` - North star example, must always be first test
- `security_audit_pipeline` - Complex multi-tool integration (8-14 nodes)
- `repository_analytics_pipeline` - Most complex test (12-16 nodes)
- `slack_qa_automation` - Real MCP integration from production trace
- `validation_recovery_test` - Tests error recovery mechanism

## Unexpected Discoveries

### Gotchas Encountered

1. **Tests were passing by accident**: LLM was following instructions to not hardcode despite seeing values
2. **browsed_components format wrong**: Tests used `{"node-name": {"type": "node"}}` but real format is `{"node_ids": [...], ...}`
3. **pytest-xdist was never installed**: Despite code expecting it since Aug 2025, causing 10x slower tests
4. **Validation was too weak**: Only caught exact quoted values, missed compound strings, URLs, etc.
5. **Model was smarter than tests**: Adding validation nodes was good engineering, not errors

### Edge Cases Found
- **Runtime values vs parameters**: `$(date +%Y-%m-%d)` is runtime-generated, not a parameter
- **Shell can do anything**: No restrictions on git/gh commands, enabling creative workarounds
- **Template confusion**: Overly aggressive templatization (replacing "weather" everywhere when `mcp_server: "weather"`)

## Patterns Established

### Reusable Patterns

```python
# Templatization pattern - use before any LLM sees user input
def _templatize_user_input(self, user_input: str, params: dict) -> str:
    # Sort by length to avoid partial replacements
    sorted_params = sorted(params.items(),
                          key=lambda x: len(str(x[1])) if x[1] else 0,
                          reverse=True)
    for param_name, param_value in sorted_params:
        if param_value:
            user_input = user_input.replace(str(param_value), f"${{{param_name}}}")
    return user_input
```

```python
# Test validation pattern - flexible but comprehensive
critical_nodes=["must-have", "nodes"],  # Required
allowed_extra_nodes=["llm", "shell"],   # Optional extras for good engineering
```

### Anti-Patterns to Avoid
- **Don't tell LLM values then expect it not to use them** - Use templates instead
- **Don't duplicate templatization logic** - Use shared store
- **Don't validate exact node counts** - Allow flexibility for good engineering
- **Don't skip parallel execution** - Tests take 10x longer without `-n auto`

## Breaking Changes

### API/Interface Changes
- **ParameterDiscoveryNode** now creates `templatized_input` in shared store
- **WorkflowGeneratorNode** expects `templatized_input` instead of raw `user_input`
- **Test infrastructure** requires pytest-xdist for reasonable performance

### Behavioral Changes
- **Workflow generator never sees actual values** - Only sees templates
- **Validation much stricter** - Catches hardcoded values in any context
- **ir_version auto-added** - No longer generated by LLM

## Future Considerations

### Extension Points
- **Dynamic MCP discovery** - Replace hardcoded Slack mocks with dynamic MCP server detection
- **Proper git/GitHub nodes** - Replace shell workarounds with dedicated nodes
- **Gemini compatibility** - Schema transformation for Gemini's JSON Schema limitations

### Scalability Concerns
- **Shell workarounds maintenance** - As more features needed, shell commands become complex
- **Test parallelization limits** - Currently capped at 20 workers for rate limiting
- **MCP mock proliferation** - Need systematic approach for MCP testing

## AI Agent Guidance

### Quick Start for Related Tasks

**If modifying workflow generator**, read in this order:
1. `.taskmaster/tasks/task_58/implementation/progress-log.md` - Full implementation journey
2. `src/pflow/planning/nodes.py` - See `_templatize_user_input()` method
3. `tests/test_planning/llm/prompts/test_workflow_generator_prompt.py` - Understand test patterns

**Key pattern to follow**: Always templatize user input before LLM processing:
```python
param_node = ParameterDiscoveryNode()
templatized = param_node._templatize_user_input(user_input, discovered_params)
shared["templatized_input"] = templatized
```

### Common Pitfalls

1. **Forgetting `-n auto` flag**: Tests will take 2-3 minutes instead of 10-20 seconds
2. **Testing without templatization**: Will get hardcoding validation errors
3. **Using wrong browsed_components format**: Must be `{"node_ids": [...], "workflow_names": [...], "reasoning": "..."}`
4. **Being too strict on node counts**: Models adding extra validation is GOOD
5. **Not reading progress log**: Contains critical insights about what NOT to do

### Test-First Recommendations

When modifying workflow generator:
1. **Run structure test first**: `RUN_LLM_TESTS=0 pytest test_workflow_generator_prompt.py -n auto -v`
2. **Test single case**: `RUN_LLM_TESTS=1 pytest test_workflow_generator_prompt.py::test_workflow_generation[changelog_from_issues] -v`
3. **Use test accuracy script**: `RUN_LLM_TESTS=1 uv run python tools/test_prompt_accuracy.py workflow_generator`
4. **Check for hardcoded values**: Temporarily uncomment line 1190 to disable templatization and verify strict validation works

---

*Generated from implementation context of Task 58*