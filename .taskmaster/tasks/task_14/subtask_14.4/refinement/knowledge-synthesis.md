# Knowledge Synthesis for Subtask 14.4

## Relevant Patterns from Previous Tasks

### Parser Enhancement Patterns (from 14.1)
- **Rich Format Transformation**: Always return rich format with defaults for backward compatibility - This allows API evolution without breaking consumers
- **Format Detection Pattern**: Check for type indicators (colons) to route to appropriate parser - Clean way to support multiple formats
- **Graceful Enhancement Pattern**: Transform output format while accepting old input - Maintains compatibility

### Context Builder Patterns (from 14.2)
- **Hierarchical Structure Formatting**: Recursive indentation for visual hierarchy with descriptions inline - Makes nested data intuitive
- **Modular Refactoring**: Extract processing from formatting logic - Prepares for future changes (Task 15)
- **Flexibility in Requirements**: Be ready to pivot when requirements change - Task 15 context changed everything

### Multi-line and Comma Handling (from 14.3)
- **Parser Fix Pattern**: When fixing list-building parsers, check if replacing vs extending - Critical for multi-line support
- **Context-aware Splitting**: Use regex with lookahead `re.split(r',\s*(?=shared\[)', content)` - Preserves commas in descriptions
- **Exclusive Params Pattern**: Only list params NOT in Reads - Eliminates redundancy

## Known Pitfalls to Avoid

### From Knowledge Base
- **Pitfall: String Parsing with Naive Split** (lines 162-185 in pitfalls.md)
  - The naive `content.split(",")` broke on commas in descriptions
  - Solution: Context-aware regex splitting that preserves commas within descriptions
  - Test with complex punctuation: commas, parentheses, colons

### From Previous Subtasks
- **Assuming Documentation is Accurate**: Parser had deep limitations not documented
- **Not Testing Edge Cases Early**: Multi-line format issues discovered late
- **Trying Workarounds Instead of Root Fixes**: Should fix parser bugs directly

## Established Conventions

### Enhanced Interface Format (from 14.3)
```python
Interface:
- Reads: shared["key1"]: type  # Description
- Reads: shared["key2"]: type  # Description (optional, default: value)
- Writes: shared["output"]: type  # Description
- Params: exclusive_param: type  # Only params NOT in Reads
- Actions: default, error
```

### Testing Conventions (from Task 7 and knowledge base)
- **Test-As-You-Go Development**: Write tests for each component as implemented
- **Use Real Node Imports**: Not mocks; test with actual codebase files
- **Phased Testing**: Validation → Extraction → Formatting phases
- **100% Coverage Including Edge Cases**: Especially for parser functionality

## Codebase Evolution Context

### What Changed in Task 14
1. **14.1**: Added enhanced format parsing with type annotations and structure support
2. **14.2**: Updated context builder to display types and hierarchical structures
3. **14.3**: Fixed parser bugs for multi-line support and comma handling, migrated all nodes

### Current State
- Parser supports both simple and enhanced formats
- All 7 nodes use enhanced format with exclusive params
- Context builder shows types and structure hierarchically
- No GitHub nodes exist yet (Task 13 not implemented)

### Missing Pieces (Not in Scope for 14.4)
- Structure parsing exists but only as scaffolding (`_has_structure` flag)
- No actual nested structure parsing implemented yet
- Platform nodes (GitHub, etc.) don't exist
- Examples folder not updated despite task description claims

## Test Gaps Identified

### Parser Edge Cases Not Yet Tested
1. Nested structures with commas in descriptions
2. Multiple params on one line with complex descriptions
3. Malformed enhanced format fallback behavior
4. Very deep nesting (though structure parsing not implemented)
5. Mixed format handling (simple and enhanced in same Interface)

### Integration Gaps
1. End-to-end flow from docstring → metadata → context → planner
2. Context size limits with many typed nodes
3. Exclusive params filtering verification

### Documentation Gaps
1. Enhanced Interface format specification missing
2. Migration guide for developers needed
3. `architecture/implementation-details/metadata-extraction.md` outdated
4. No clear guidance on when to use multi-line vs single-line

## Critical Implementation Details

### Parser Changes in 14.3
- **Line 177-211**: Changed from `result["inputs"] = ...` to `result["inputs"].extend(...)` for multi-line
- **Line 376**: Changed split to `re.split(r',\s*(?=shared\[)', content)` for comma preservation
- **Lines 444-470**: Similar fix for params splitting

### Key Methods to Test
- `_extract_interface_component()`: New enhanced parser
- `_process_interface_item()`: Format detection and merging
- `_extract_enhanced_shared_keys()`: Comma-aware parsing
- `_extract_enhanced_params()`: Param parsing with descriptions

### Test Updates Already Done
- `test_extract_from_read_file_node`: Now expects empty params list
- `test_real_read_file_node_interface`: Same change
- `test_real_move_file_node_interface`: Same change
- `test_real_delete_file_node_interface`: Same change
