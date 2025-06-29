# Task 5: Ready for Implementation ✓

## Summary
Task 5 is now fully specified and ready for implementation. All ambiguities have been resolved through user clarifications.

## Final Specification

### What to Build
`src/pflow/registry/scanner.py` with a `scan_for_nodes(directories)` function that:

1. **Scans** only package nodes at `Path(pflow.__file__).parent / 'nodes'`
2. **Finds** all classes inheriting from `pocketflow.BaseNode`
3. **Uses** importlib (with security note for future user nodes)
4. **Extracts** basic metadata:
   - `module`: Full import path (e.g., "pflow.nodes.file.read_file")
   - `class_name`: Class name (e.g., "ReadFileNode")
   - `name`: Node name from class.name attribute or kebab-case conversion
   - `docstring`: Raw docstring text (NOT parsed)
   - `file_path`: Path to the Python file
5. **Stores** in persistent JSON file (location TBD - likely ~/.pflow/registry.json)

### Output Format
```json
{
    "read-file": {
        "module": "pflow.nodes.file.read_file",
        "class_name": "ReadFileNode",
        "docstring": "Read file contents.\n\nInterface:\n- Reads: ...",
        "file_path": "/path/to/read_file.py"
    }
}
```

### Key Implementation Details
- Node naming: Check `class.name` attribute first, fallback to kebab-case
- Security: Add comment about importlib executing code on import
- Test node: Create `src/pflow/nodes/test_node.py` as part of this task
- No docstring parsing - that's Task 7's job
- MVP scope only - no user/system/local node directories

## Dependencies
✓ No blocking dependencies
✓ Creates foundation for Task 4 (compiler) and Task 7 (metadata extraction)

## Test Strategy
Comprehensive tests including:
- Real and mock node discovery
- BaseNode inheritance detection
- Name extraction (explicit and conversion)
- JSON persistence and loading
- Edge cases handling

## Next Steps
1. Implement the scanner following the specification
2. Create test node with proper Interface docstring
3. Write comprehensive tests
4. Document any discoveries for future tasks

The task is well-defined, scoped appropriately for MVP, and integrates cleanly with the overall architecture.
