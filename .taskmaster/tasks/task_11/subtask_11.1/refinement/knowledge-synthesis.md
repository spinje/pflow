# Knowledge Synthesis for Subtask 11.1

## Relevant Patterns from Previous Tasks

### Node Implementation Pattern (Task 6, 4, 5)
- **Pattern**: Three-phase lifecycle (prep→exec→post) with clear separation of concerns
- **Where used**: test_node.py, all implemented nodes
- **Why relevant**: Establishes the standard for all node implementations

### Error Handling Pattern (Task 5.2, Tutorial-Cursor)
- **Pattern**: Return tuples `(result, success_bool)` from exec() for graceful error handling
- **Where used**: Tutorial-Cursor file utilities, authentication error handling
- **Why relevant**: File operations can fail - need robust error handling

### Test-As-You-Go Pattern (Task 1.3, 2.3, 4.3)
- **Pattern**: Write tests immediately with implementation, not as separate task
- **Where used**: Every successful task implementation
- **Why relevant**: Ensures quality and catches issues early

### Natural Interface Pattern (simple-nodes.md, Task 6)
- **Pattern**: Use intuitive shared store keys like `file_path`, `content`, `text`
- **Where used**: All platform nodes, IR compiler
- **Why relevant**: Makes nodes easy to compose and understand

### Documentation Pattern (test_node.py, Task 5)
- **Pattern**: Comprehensive docstrings with Interface section listing Reads/Writes/Actions
- **Where used**: All discoverable nodes
- **Why relevant**: Required for registry scanner to extract metadata

## Known Pitfalls to Avoid

### Reserved Field Name Pitfall (Task 4.2)
- **Pitfall**: Using "filename" in logging extra dict causes KeyError
- **Where failed**: Initial IR compiler implementation
- **How to avoid**: Use "file_path" instead in all logging contexts

### Missing File Handling (Task 5.2)
- **Pitfall**: Crashing on missing files instead of graceful handling
- **Where failed**: Early auth implementations
- **How to avoid**: Try/except with clear error messages and "error" action

### Complex Dispatch Anti-pattern (Task 6 discussions)
- **Pitfall**: Building complex internal routing in nodes
- **Where failed**: Initial node design proposals
- **How to avoid**: Keep nodes simple with single responsibility

### Parameter vs Shared Store Confusion (Task 4)
- **Pitfall**: Not checking shared store before params
- **Where failed**: Early node implementations
- **How to avoid**: Always check `shared.get("key") or self.params.get("key")`

## Established Conventions

### Node Naming Convention (Task 5)
- **Convention**: Use kebab-case for node names (read-file, write-file)
- **Where decided**: Registry implementation
- **Must follow**: Either set explicit `name` attribute or rely on class name conversion

### Shared Store Key Names (simple-nodes.md)
- **Convention**: Natural, self-documenting key names
- **Where decided**: Architecture documents
- **Must follow**: Use `file_path`, `content`, `encoding` for file operations

### Import Convention (Task 5, 6)
- **Convention**: Expose nodes in `__init__.py` for registry discovery
- **Where decided**: Registry scanner implementation
- **Must follow**: Without this, nodes won't be discovered

### UTF-8 Default (Tutorial-Cursor, best practices)
- **Convention**: Always specify encoding='utf-8' for text files
- **Where decided**: Cookbook examples and Python best practices
- **Must follow**: Prevents encoding issues across platforms

## Codebase Evolution Context

### BaseNode vs Node Evolution (Recent understanding)
- **What changed**: Clarified that Node extends BaseNode with retry capabilities
- **When**: During task analysis
- **Impact**: Should use Node for file operations due to potential transient failures

### Registry Scanner Requirements (Task 5)
- **What changed**: Registry now scans for BaseNode inheritance
- **When**: Task 5 implementation
- **Impact**: Must inherit from BaseNode or Node for discovery

### Shared Store Pattern Maturity (Task 6)
- **What changed**: Shared store pattern fully validated and documented
- **When**: IR schema and compiler implementation
- **Impact**: Can confidently use established patterns

### Testing Infrastructure (Task 1-6)
- **What changed**: Test patterns established with pytest and tempfile
- **When**: Throughout early tasks
- **Impact**: Clear patterns to follow for file operation testing

## Key Implementation Insights

### From Tutorial-Cursor File Utils
1. **Line numbers**: Add 1-indexed line numbers when displaying file content
2. **Directory creation**: Always use `os.makedirs(exist_ok=True)` for write operations
3. **Path validation**: Check file existence before operations
4. **Error messages**: Include file path in all error messages for debugging

### From PocketFlow Core
1. **Lifecycle separation**: prep validates, exec computes, post updates
2. **Pure exec**: The exec method should be side-effect free when possible
3. **Action returns**: Use "default" for success, "error" for failures
4. **Shared store trust**: The framework handles shared store lifecycle

### From Previous Implementations
1. **Parameter fallback**: Support both shared store and params for flexibility
2. **Logging structure**: Use phase tracking for debugging
3. **Early validation**: Fail fast in prep() with clear messages
4. **Comprehensive tests**: Test success, failures, and edge cases
