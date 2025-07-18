# Knowledge Synthesis for Subtask 15.1

## Relevant Patterns from Previous Tasks

### File I/O and JSON Loading Patterns
- **Graceful JSON Configuration Loading**: [Task 5.2] - Chain multiple fallbacks with specific error handling for missing files, empty files, corrupt JSON, and permission errors. Always return empty dict on failure for graceful degradation.
- **Atomic File Operations**: [Task 11] - Use tempfile + rename pattern for write integrity. Handle cross-platform path differences with Path normalization.
- **Directory Creation**: [Multiple tasks] - Use `Path.mkdir(parents=True, exist_ok=True)` for idempotent directory creation.

### Error Handling and Validation
- **Layered Validation**: [Task 6.1] - Separate JSON parsing, schema validation, and business logic validation with specific error types for each layer.
- **PocketFlow Node Error Handling**: [Task 11] - Let exceptions bubble up in exec() for automatic retry. Only catch in exec_fallback() after retries exhausted.

### Test Infrastructure
- **Tempfile-Based Dynamic Test Data**: [Task 5.3] - Create test files dynamically in each test for self-contained tests without fixture management.
- **Self-Contained Test Workflows**: [Task 8.2] - Embed all required data in node params, don't rely on shared store state.

### PocketFlow Cookbook Patterns
- **Directory Reading Pattern**: [pocketflow-map-reduce] - Clean pattern for loading multiple files from a directory with structured data extraction.
- **Validation Pattern**: [pocketflow-structured-output] - Structured data validation with assertions and clear error messages.
- **Utility Separation**: [pocketflow-tool-database] - Clean separation between utility functions and node logic.

## Known Pitfalls to Avoid

### String Processing Issues
- **Delimiter Conflicts**: [Task 14.3] - Commas, colons in descriptions break simple splitting. Always test with realistic data containing punctuation.

### Exception Handling Anti-patterns
- **Catching in exec()**: [Task 11] - Never catch exceptions in PocketFlow exec() method - it disables retry mechanism. Let exceptions bubble up.

### Logging Issues
- **Reserved Field Names**: [Task 4.2] - Don't use "module", "filename" in logging extra dict. Use alternatives like "module_path", "file_path".

## Established Conventions

### Path Handling
- **Absolute Paths**: [Multiple tasks] - Always use absolute paths via Path.resolve() for consistency.
- **Cross-platform**: [Task 11] - Use Path methods instead of string manipulation for Windows/Unix compatibility.

### Testing Conventions
- **Test-As-You-Go**: [CLAUDE.md] - Tests are part of implementation, not a separate task. Write tests alongside code.
- **Behavior Focus**: [Task 8.2] - Test behavior, not implementation details.

### Code Organization
- **Utility Functions**: [pocketflow-tool-database] - Separate file I/O utilities from business logic for cleaner architecture.
- **Registry Pattern**: [Task 5.2] - Store identifier as dict key, not in value to prevent redundancy.

## Codebase Evolution Context

### Context Builder Evolution
- **Task 16**: Created original single-phase context builder with `build_context()` function.
- **Task 14**: Enhanced metadata extractor with structure parsing - fully implemented recursive parser.
- **Task 15**: Now splitting into two-phase approach (discovery vs planning).

### Current State
- **Parser is Fragile**: [Task 14] - Regex patterns are extremely delicate. One wrong change can break 20+ tests.
- **All Nodes Migrated**: [Task 14.3] - All 7 nodes now use enhanced format with structure support.
- **No Backward Compatibility Needed**: [Task 15 ambiguities] - Can refactor build_context() freely.

### Workflow Infrastructure
- **First Implementation**: Task 15 is creating the workflow loading infrastructure that Task 17 will use for saving.
- **Chicken-and-Egg**: Loading workflows that don't exist yet - need to create test workflows for validation.
- **MVP Scope**: Simple flat directory structure, basic validation, no fancy features.

## Application to Subtask 15.1

This subtask needs to create the foundation for workflow loading:
1. Apply graceful JSON loading patterns from Task 5.2
2. Use directory reading pattern from pocketflow-map-reduce cookbook
3. Implement validation pattern from pocketflow-structured-output
4. Create test infrastructure using tempfile patterns from Task 5.3
5. Avoid catching exceptions that would disable retry mechanism
6. Use Path operations for cross-platform compatibility
7. Write tests alongside implementation (test-as-you-go strategy)
