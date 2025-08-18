# Task 36: Context Builder Update for Automatic Namespacing

## Quick Summary

**Problem**: With automatic namespacing enabled by default (Task 9), the context builder shows node information in a misleading way that confuses the LLM planner.

**Solution**: Update ONLY the context builder to present nodes clearly, showing that ALL parameters must be passed via the params field using template variables.

**Impact**: Single file change (`context_builder.py`) that dramatically improves clarity without touching any other system.

## Documents in This Folder

### 1. `implementation-plan.md`
Complete implementation plan including:
- Problem statement and impact
- Current vs proposed format
- Implementation strategy
- Risk assessment
- Timeline estimate

### 2. `problem-analysis.md`
Deep dive into the confusion caused by current format:
- Concrete examples of misleading output
- Mental model mismatch
- Real-world workflow generation errors
- Why "exclusive params" pattern no longer makes sense

### 3. `code-implementation-guide.md`
Exact code changes needed:
- Function-by-function modifications
- New functions to add
- Test updates required
- Edge cases to handle

### 4. `testing-validation-guide.md`
Comprehensive testing strategy:
- Pre-implementation testing
- Unit and integration tests
- Before/after comparison
- Success criteria

## Key Insight

The context builder is our **translation layer** between node metadata and LLM understanding. By fixing this translation, we solve the namespacing confusion without any system-wide changes.

## Before vs After Example

### Before (Confusing)
```markdown
### read-file
**Inputs**:
- `file_path: str` - Path to the file to read

**Parameters**: none  ❌ Misleading!
```

### After (Clear)
```markdown
### read-file
**Parameters** (all go in params field):
- `file_path: str` - Path to the file to read
- `encoding: str` - File encoding (optional, default: utf-8)

**Outputs** (access as ${node_id.output_key}):
- `content: str` - File contents with line numbers

**Example usage**:
```json
{"id": "read", "type": "read-file", "params": {"file_path": "${input_file}"}}
```
```

## Implementation Checklist

- [ ] Review all documents in this folder
- [ ] Backup current context_builder.py
- [ ] Implement new functions (_format_all_parameters, etc.)
- [ ] Update _format_node_section_enhanced
- [ ] Update tests for new format
- [ ] Run validation tests
- [ ] Create before/after comparison
- [ ] Document changes

## Critical Points

1. **No Breaking Changes**: Only presentation changes, no system impact
2. **Eliminate "Exclusive Params"**: This distinction is confusing with namespacing
3. **Always Show Examples**: Concrete usage patterns for every node
4. **Consistent Format**: All nodes use the same clear structure

## Success Metrics

- LLM generates correct workflows without "missing parameter" errors
- Clear understanding that everything goes in params field
- No confusion about what "Parameters: none" means
- Improved workflow generation for multiple same-type nodes

## Questions Resolved

✅ Should we change only context_builder? **Yes - minimal risk, maximum clarity**
✅ Should we eliminate "exclusive params"? **Yes - confusing with namespacing**
✅ Should we show examples for all nodes? **Yes - concrete patterns help**
✅ Should we rename "Inputs" to "Parameters"? **Yes - reflects reality**

## Next Steps

1. Implement changes following the code guide
2. Run tests to validate format
3. Test with real workflow generation
4. Document the improvement
5. Consider updating planner prompts to leverage clearer format

---

*This task makes the context builder output match the reality of how nodes work with automatic namespacing, eliminating a major source of confusion for the LLM planner.*