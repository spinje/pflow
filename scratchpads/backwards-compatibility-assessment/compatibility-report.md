# Backwards Compatibility Analysis: Skipping Unresolved Template Parameters

## Executive Summary

**COMPATIBILITY RISK: LOW to MEDIUM**

Based on analysis of the codebase, existing workflows, tests, and documentation, **skipping unresolved parameters would be a breaking change** but with **manageable impact**. The change would affect debugging workflows and some advanced use cases, but most production workflows should continue working unchanged.

## Current Behavior Analysis

### Template Resolution System

**Current behavior (from `src/pflow/runtime/template_resolver.py:199-201`):**
```python
# Variable doesn't exist - leave template as-is for debugging
logger.debug(f"Template variable '${{{var_name}}}' could not be resolved", extra={"var_name": var_name})
```

**Key finding**: Unresolved templates are intentionally preserved as `${variable}` for debugging purposes.

### Validation Layer

**Current validation is very strict** - it prevents workflows from running if any template cannot be resolved:
- Template validation occurs at compile-time
- Blocks execution entirely if any `${variable}` cannot be resolved
- Users cannot currently run workflows with missing parameters

## Affected Workflows Analysis

### 1. Existing Example Workflows

**Analyzed 45+ workflow files in `examples/` directory:**

**Most workflows use only resolvable templates:**
- Input parameters: `${file_path}`, `${content}`, `${repo_name}`
- Node outputs: `${read_file.content}`, `${fetch_issues.issues}`
- Workflow inputs: All declared in `inputs` section

**Found ZERO workflows that intentionally use unresolved templates** in the examples directory.

### 2. Test Expectations

**Two critical tests expect unresolved templates to remain:**

```python
# tests/test_runtime/test_template_resolver.py:154-158
def test_preserves_unresolved_templates(self):
    """Test that unresolved templates remain unchanged."""
    context = {"found": "yes"}
    template = "Found: ${found}, Missing: ${missing}"
    assert TemplateResolver.resolve_string(template, context) == "Found: yes, Missing: ${missing}"

# tests/test_runtime/test_node_wrapper.py:194-206
def test_unresolved_templates_remain(self):
    """Test that unresolved templates remain unchanged."""
    # ... expects: "'missing': '${undefined}'" in output
```

**Impact**: These tests would need updating to expect empty string or parameter skipping behavior.

### 3. Documentation References

**Key documentation about unresolved templates:**

From task history (`.taskmaster/tasks/task_18/`):
- "Debugging is possible: Unresolved templates remain visible as `${missing_var}`"
- "Unresolved templates visible in node execution for debugging"
- Design decision: Templates preserved for debugging visibility

## User-Visible Changes

### What Would Change

**Before (current behavior):**
```bash
# Template validation prevents execution
uv run pflow workflow.json param1=value
❌ Template validation failed: Template variable ${missing} has no valid source
```

**After (with parameter skipping):**
```bash
# Workflow executes, skipping unresolved parameters
uv run pflow workflow.json param1=value
✅ Workflow completed
# File content: "Found: value, Missing: " (empty)
```

### What Would Break

1. **Debugging workflows** that intentionally show unresolved templates
2. **Workflows expecting literal `${var}` in output** (very rare)
3. **Advanced templating patterns** where unresolved state provides information
4. **Tests that verify template preservation**

### What Would Continue Working

1. **All normal workflows** with proper input declarations
2. **Node output references** like `${node.output}`
3. **Properly declared input parameters**
4. **99% of production use cases**

## Migration Analysis

### Breaking Change Classification

**This is a BREAKING CHANGE because:**
- Changes observable behavior of template resolution
- Affects test assertions
- Changes debugging information available to users
- Modifies the "contract" that unresolved templates are preserved

### Migration Difficulty: LOW

**Most workflows require NO changes:**
- Workflows with proper input declarations work unchanged
- Node-to-node data flow works unchanged
- Only affects edge cases with missing parameters

## Migration Strategies

### Option 1: Breaking Change with Migration Period

**Recommended approach:**

```markdown
## Migration Steps:
1. **Update template resolver** to skip unresolved parameters
2. **Update tests** to expect new behavior
3. **Add migration guide** for debugging workflows
4. **Version bump** to indicate breaking change
5. **Update documentation** to reflect new behavior
```

**Migration for debugging workflows:**
```bash
# Old debugging approach
${undefined_var}  # Shows "${undefined_var}" in output

# New debugging approach
${undefined_var:default_value}  # Use default syntax (if implemented)
# OR check logs for template resolution messages
# OR use conditional logic in workflows
```

### Option 2: Backwards Compatible with Flag

**Add configuration option:**

```python
# In template resolver
@staticmethod
def resolve_string(template: str, context: dict[str, Any], skip_unresolved: bool = False) -> str:
    if skip_unresolved and resolved_value is None:
        # Skip this parameter entirely
        result = result.replace(f"${{{var_name}}}", "")
    else:
        # Keep current behavior - preserve unresolved templates
        # (existing code)
```

**Pros**: No breaking changes, gradual migration
**Cons**: More complex implementation, maintenance burden

### Option 3: Enhanced Default Values

**Extend template syntax:**

```json
{
  "params": {
    "message": "Found: ${existing}, Missing: ${missing:Not provided}"
  }
}
```

**Pros**: Backwards compatible, more flexible
**Cons**: Requires additional implementation work

## Recommended Approach

### Choice: Option 1 (Breaking Change)

**Rationale:**
1. **pflow is pre-1.0** - breaking changes are expected
2. **No users in production** - minimal real-world impact
3. **Cleaner long-term design** - simpler than maintaining dual behavior
4. **Easy migration** - most workflows unaffected

### Implementation Plan

```markdown
1. **Phase 1: Code Changes**
   - Update `TemplateResolver.resolve_string()` to skip unresolved
   - Update node wrapper to handle skipped parameters
   - Update validation to be less strict (optional parameters)

2. **Phase 2: Test Updates**
   - Fix `test_preserves_unresolved_templates()`
   - Fix `test_unresolved_templates_remain()`
   - Update related test assertions

3. **Phase 3: Documentation**
   - Update template variable documentation
   - Add migration guide for debugging patterns
   - Update examples if needed

4. **Phase 4: Validation**
   - Test with existing workflow examples
   - Verify no regressions in normal cases
   - Test edge cases thoroughly
```

## Risk Assessment

### Risk Level: LOW-MEDIUM

**Low risk factors:**
- No production users affected
- Most workflows use only resolvable templates
- Easy to implement and test
- Clear migration path

**Medium risk factors:**
- Changes fundamental debugging behavior
- Requires test updates
- Could affect advanced workflow patterns
- Documentation updates needed across multiple files

### Mitigation Strategies

1. **Comprehensive testing** of all example workflows
2. **Clear migration documentation**
3. **Gradual rollout** with feature flag initially
4. **Monitoring** for any unexpected issues
5. **Quick rollback plan** if needed

## Conclusion

**RECOMMENDATION: Proceed with breaking change (Option 1)**

The compatibility impact is manageable given pflow's current state:
- Zero production users
- Clear benefits for user experience
- Most workflows unaffected
- Proper migration path available

The change aligns with pflow's goal of being user-friendly and reducing friction, at the cost of some debugging visibility that can be replaced with better logging and validation messages.
