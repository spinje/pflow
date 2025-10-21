# Task 85 Review: Runtime Template Resolution Hardening

## Metadata
<!-- Implementation Date: 2025-10-20 -->
<!-- Branch: feat/runtime-template-resolution -->
<!-- Related Issues: GitHub #95 (original bug), GitHub #96 (partial resolution fix) -->

## Executive Summary
Implemented comprehensive template validation that prevents literal `${variable}` text from reaching production APIs when templates fail to resolve. Added tri-state workflow status (SUCCESS/DEGRADED/FAILED), configurable strict/permissive modes, and enhanced error messages. The implementation required fixing a critical recursive validation bug discovered during manual testing.

## Implementation Overview

### What Was Built
- **Core bug fix**: Simple templates (`${var}`) now properly validated (were being skipped)
- **Recursive validation**: Handles strings, lists, dicts, and deeply nested structures
- **Tri-state status system**: Workflows report SUCCESS/DEGRADED/FAILED instead of binary
- **Configuration system**: Strict (default) vs permissive mode at workflow/global levels
- **Enhanced error messages**: Shows available context keys and suggestions
- **Partial resolution detection**: Catches when some variables resolve but others don't (GitHub #96)
- **Namespacing integration**: Special `__*__` keys bypass namespacing for framework coordination

### Implementation Approach
Used recursive validation with equality checking: if `resolved_value == original_template` and contains `${`, then it's unresolved. For partial resolution, extract variables from both original and resolved strings and check for intersection. This avoids false positives from MCP data containing `${...}` syntax in resolved values.

## Files Modified/Created

### Core Changes
- `src/pflow/runtime/node_wrapper.py` - Added `_contains_unresolved_template()` recursive validation, enhanced error builder
- `src/pflow/core/workflow_status.py` - Created WorkflowStatus enum (SUCCESS/DEGRADED/FAILED)
- `src/pflow/execution/executor_service.py` - Added tri-state status determination and warnings extraction
- `src/pflow/runtime/workflow_trace.py` - Updated trace format to v1.2.0 with tri-state status
- `src/pflow/runtime/namespaced_store.py` - Fixed to bypass namespacing for `__*__` keys
- `src/pflow/runtime/compiler.py` - Added template_resolution_mode propagation through compilation
- `src/pflow/core/settings.py` - Added RuntimeSettings with template_resolution_mode
- `src/pflow/core/ir_schema.py` - Added template_resolution_mode to workflow schema
- `src/pflow/cli/main.py` - Fixed logging configuration to suppress third-party noise
- `src/pflow/execution/display_manager.py` - Added tri-state status display
- `src/pflow/execution/formatters/success_formatter.py` - Fixed "Nonems" bug, added warnings

### Test Files
- `tests/test_runtime/test_node_wrapper_template_validation.py` - 30 tests covering all edge cases
- `tests/test_integration/test_template_resolution_hardening.py` - 10 critical integration tests
- `tests/test_runtime/test_namespacing.py` - 7 tests for `__*__` key handling

## Integration Points & Dependencies

### Incoming Dependencies
- **Planner** → Task 85 (validates generated templates at runtime)
- **Repair System** → Task 85 (receives ValueError for unresolved templates)
- **Workflow Executor** → Task 85 (checks status to determine success/degradation)
- **MCP Nodes** → Task 85 (templates validated before MCP tool execution)

### Outgoing Dependencies
- Task 85 → **TemplateResolver** (extract_variables, resolve methods)
- Task 85 → **NamespacedSharedStore** (reads/writes special keys)
- Task 85 → **SettingsManager** (loads template_resolution_mode)
- Task 85 → **Logger** (enhanced error messages with context)

### Shared Store Keys
- `__template_errors__` - Stores template resolution errors in permissive mode (dict)
- `__warnings__` - API warnings that trigger DEGRADED status (dict)
- Framework keys that bypass namespacing: `__execution__`, `__llm_calls__`, `__cache_hits__`, `__modified_nodes__`, `__non_repairable_error__`, `__progress_callback__`

## Architectural Decisions & Tradeoffs

### Key Decisions
1. **Recursive validation instead of string conversion** → Avoids false positives from MCP data → Alternative: Converting everything to string caused false positives
2. **Strict mode as default** → Fail-hard for data integrity → Alternative: Permissive default would allow broken data in production
3. **Set intersection for partial resolution** → Detects when original variables remain → Alternative: Complex regex patterns would be fragile
4. **Special keys bypass namespacing** → Framework needs root-level coordination → Alternative: Prefixed keys would break existing patterns

### Technical Debt Incurred
- **No escape syntax**: Can't write literal `${...}` in workflow IR (needs `\${var}` support)
- **Performance**: Recursive validation on every execution (could cache validation results)

## Testing Implementation

### Test Strategy Applied
Three-layer testing:
1. Unit tests for each validation scenario
2. Integration tests for Issue #95 prevention
3. Manual tests with real workflows to find integration bugs

### Critical Test Cases
- `test_unresolved_template_fails_before_external_api_strict_mode` - THE core fix for Issue #95
- `test_success_status_for_perfect_workflow` - Prevents false positives
- `test_multiple_templates_one_missing` - Partial resolution detection
- `test_no_false_positive_on_mcp_data` - MCP data can contain ${...} syntax

## Unexpected Discoveries

### Gotchas Encountered
1. **Phase 5 Bug**: Converting to string (`str(resolved_value)`) caused MCP false positives
2. **Namespacing Integration**: Special keys were being namespaced, breaking permissive mode status
3. **Partial Resolution Gap**: `"User ${name} has ${count}"` → `"User Alice has ${count}"` wasn't detected
4. **Test Environment**: Some tests passed individually but failed in full suite (logging config)

### Edge Cases Found
- Empty string resolution vs unresolved templates
- MCP responses containing literal `${...}` in data
- Multiple templates where some resolve to empty/None
- Deeply nested structures with templates at various levels

## Patterns Established

### Reusable Patterns
```python
# Recursive validation with type checking
def _contains_unresolved_template(self, resolved_value, original_template):
    if isinstance(resolved_value, str) and isinstance(original_template, str):
        # Check complete unresolution
        if resolved_value == original_template:
            return "${" in resolved_value

        # Check partial resolution (set intersection)
        if "${" in resolved_value:
            original_vars = extract_variables(original_template)
            remaining_vars = extract_variables(resolved_value)
            return bool(original_vars & remaining_vars)
```

### Anti-Patterns to Avoid
- Don't use `str(value)` to check for templates - causes false positives
- Don't check only unchanged values - misses partial resolution
- Don't validate arbitrary outputs - only validate declared parameters

## Breaking Changes

### API/Interface Changes
- Workflow execution now returns tri-state status instead of binary success
- `ExecutionResult` has new `status` and `warnings` fields
- Trace format version bumped to 1.2.0

### Behavioral Changes
- Workflows fail immediately on unresolved templates (was: continue with literal `${...}`)
- Default mode is strict (was: implicitly permissive)
- Special `__*__` keys always go to root store (was: namespaced)

## Future Considerations

### Extension Points
- Add escape syntax (`\${literal}`) support in TemplateResolver
- Add caching layer for validation results
- Support for conditional templates (`${var:-default}`)

### Scalability Concerns
- Recursive validation could be expensive for very deeply nested structures (>100 levels)
- No maximum recursion depth protection (Python's default is ~1000)

## AI Agent Guidance

### Quick Start for Related Tasks
1. **Read first**: `src/pflow/runtime/node_wrapper.py` lines 87-150 (core validation logic)
2. **Understand hierarchy**: Workflow IR → Settings → Environment → Default ("strict")
3. **Test pattern**: Always test with both MCP data containing `${...}` AND actual unresolved templates
4. **Key insight**: `resolved != original` means resolution happened, even if result contains `${...}`

### Common Pitfalls
- **Don't assume** `"${" in value` means unresolved - could be resolved data
- **Don't skip** validation for "simple" cases - that was the original bug
- **Don't forget** special `__*__` keys need root-level access
- **Watch for** partial resolution - multiple variables where only some resolve
- **Remember** Python's `==` handles circular references safely - no special handling needed

### Test-First Recommendations
Run these tests when modifying template resolution:
```bash
# Core validation logic
pytest tests/test_runtime/test_node_wrapper_template_validation.py -xvs

# Integration with Issue #95 prevention
pytest tests/test_integration/test_template_resolution_hardening.py -xvs

# Full runtime suite for regressions
pytest tests/test_runtime/ -x
```

---

*Generated from implementation context of Task 85*