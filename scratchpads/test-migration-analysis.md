# Test Migration Analysis: context_builder.py

## Functions and Their Usage

### Core Functions Used by BOTH Old and New:
1. `_process_nodes()` - Core node processing with error handling
2. `_group_nodes_by_category()` - Used by discovery context
3. `_format_exclusive_parameters()` - Used by both formatters
4. `_load_saved_workflows()` - Used by both phases
5. `_validate_workflow_fields()` - Used by workflow loading
6. `_load_single_workflow()` - Used by workflow loading

### Functions ONLY in Old (Deprecated):
1. `build_context()` - Old single-phase builder
2. `_extract_navigation_paths()` - Deprecated navigation feature
3. `_format_structure()` - Old structure formatter
4. `_format_node_section()` - Old node formatter

### Functions ONLY in New:
1. `build_discovery_context()` - New discovery phase
2. `build_planning_context()` - New planning phase
3. `_format_structure_combined()` - New structure formatter
4. `_format_node_section_enhanced()` - New node formatter
5. `_format_interface_item()` - Helper for enhanced formatter
6. `_add_enhanced_structure_display()` - Structure display helper
7. `_check_missing_components()` - Validation helper
8. `_format_workflow_section()` - Workflow formatter

## Critical Test Gaps to Migrate

### 1. Input Validation (HIGH PRIORITY)
**Old tests**: `test_input_validation_none`, `test_input_validation_wrong_type`
**Coverage**: Tests that None/wrong type raises proper errors
**Migration**: Add to both `build_discovery_context` and `build_planning_context`

### 2. Dynamic Import Error Handling (CRITICAL)
**Old tests**: `test_handles_import_failures`, `test_handles_attribute_error`, `test_module_caching`
**Coverage**: Tests error handling in `_process_nodes()`
**Migration**: These test the core _process_nodes function which is used by BOTH

### 3. Node Filtering (IMPORTANT)
**Old test**: `test_skips_test_nodes`
**Coverage**: Tests that test nodes are filtered out
**Migration**: Add to discovery context tests

### 4. Helper Function Tests (KEEP)
**Old tests**: `test_parameter_filtering`, category tests
**Coverage**: Tests shared helper functions
**Migration**: Keep these as they test functions used by both

### 5. Edge Cases for Formatting (IMPORTANT)
**Old tests**: `test_missing_description`, `test_empty_description`, `test_whitespace_only_description`
**Coverage**: Tests edge cases in node formatting
**Migration**: Add for `_format_node_section_enhanced`

## Tests to Remove (Deprecated):
- All navigation path tests (`TestNavigationPaths` class)
- Old structure formatting tests (`TestFormatStructure` class)
- Structure hints tests (`TestStructureHints` class)
- Old `build_context` tests

## Tests Already Covered in New File:
- Discovery context with empty registry
- Discovery context with nodes
- Discovery context with workflows
- Planning context with missing nodes/workflows
- Planning context with valid selection
- Structure display (new format)
- Exclusive parameters
- Categories

## Migration Priority:
1. **CRITICAL**: Dynamic import error handling - Used by both old and new
2. **HIGH**: Input validation - Prevent crashes
3. **MEDIUM**: Node filtering, edge cases - Correctness
4. **LOW**: Category tests - Already partially covered

## Recommendation:

Create a new test class in the new file for shared functionality:
- `TestSharedFunctionality` - For _process_nodes, error handling, etc.
- Keep existing phase-specific tests
- Add edge case tests for enhanced formatter
