# Knowledge Synthesis for Subtask 8.4

## Relevant Patterns from Previous Tasks

### From Subtask 8.1 - Shell Integration Foundation
- **Utility Module Pattern**: Pure functions, no side effects, minimal dependencies - Can apply this pattern to binary detection and streaming functions
- **Explicit Empty Handling Pattern**: Check `== ""` not just truthiness - Critical for binary data detection
- **Clean module boundaries**: Minimal exports in __init__.py - Keep binary/streaming utilities focused

### From Subtask 8.2 - Dual-Mode stdin Validation
- **Test Workflow Pattern**: Use self-contained workflows with all required data - Important for testing binary/large file handling
- **Current stdin injection point**: Line 124 in main.py where `shared_storage["stdin"] = stdin_data`
- **Validation Pattern**: Test each input mode systematically with real commands - Apply to binary vs text detection

## Known Pitfalls to Avoid

### From Previous Handoff
1. **Empty stdin vs No stdin**: `read_stdin()` explicitly checks for empty string and returns None - DO NOT break this!
2. **CliRunner stdin behavior**: Makes stdin look piped even when empty - Critical for testing
3. **Backward compatibility**: JSON workflow mode (`echo '{"ir_version": "1.0"}' | pflow`) MUST continue to work
4. **Subprocess test fragility**: Real `pflow` command tests are important but fragile

### From Edge Cases Document (8.2)
1. **Memory exhaustion**: Current implementation loads entire stdin into memory
2. **Binary detection complexity**: Need heuristics, not just UTF-8 decode failure
3. **Cleanup requirements**: Temp files MUST be cleaned up properly
4. **Threading considerations**: Keep single-threaded for MVP

## Established Conventions

### Shell Integration Module Structure
- **Location**: `src/pflow/core/shell_integration.py`
- **Current functions**: `detect_stdin()`, `read_stdin()`, `determine_stdin_mode()`, `populate_shared_store()`
- **Import pattern**: Clean exports through `__init__.py`

### Shared Store Keys
- **Current**: `shared["stdin"]` - stores text data as string
- **Proposed new keys**:
  - `shared["stdin_binary"]` - for binary data (bytes)
  - `shared["stdin_path"]` - for temp file path (large files)

### Testing Patterns
- Use `unittest.mock` for stdin mocking
- Mock `sys.stdin.buffer.read` for binary data
- Create real temp files for integration tests
- Always test cleanup behavior

## Codebase Evolution Context

### Current State (After 8.1 and 8.2)
- Shell integration module exists with basic text stdin handling
- CLI properly injects stdin into shared storage
- Dual-mode stdin (workflow vs data) fully working
- All tests passing, backward compatibility maintained

### What's Missing (My Task)
- Binary data detection and handling
- Large file streaming to temp files
- Proper cleanup mechanisms
- Enhanced error handling for binary/large data

### Future Considerations (from edge cases doc)
- Thread safety (not for MVP)
- Advanced formats (JSON, YAML auto-detection)
- Security features (input validation)
- Performance metrics and tracing

## Key Technical Insights

### From Research Files
1. **Simon Willison's llm CLI patterns**: Uses `sys.stdin.buffer.read()` for binary handling
2. **10MB threshold**: Suggested for temp file usage but should be configurable
3. **Binary detection**: Check for null bytes as primary heuristic
4. **Temp file patterns**: Use `tempfile.NamedTemporaryFile` with proper cleanup

### From Current Implementation
1. **stdin reading happens once**: In `get_input_source()` at line 55 of main.py
2. **Single injection point**: Line 124 where stdin goes into shared storage
3. **Error handling**: Currently returns None on any read failure
4. **Type hints everywhere**: Maintain this standard

## Architecture Considerations

### Module Dependencies
- Keep using only standard library (sys, json, tempfile, os)
- No external dependencies for shell integration
- Maintain backward compatibility with existing API

### Integration Points
1. **Shell integration module**: Add new functions without breaking existing ones
2. **CLI main.py**: Modify stdin injection to handle new data types
3. **Shared store**: Add new keys without conflicting with existing usage

### Performance Implications
- Streaming prevents memory exhaustion
- Binary detection should use small sample (8KB suggested)
- Temp file creation is expensive - only for truly large files
- Consider making thresholds configurable
