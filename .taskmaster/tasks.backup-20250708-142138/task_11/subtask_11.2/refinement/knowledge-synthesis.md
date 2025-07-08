# Knowledge Synthesis for Subtask 11.2

## Relevant Patterns from Previous Tasks

### Truthiness-Safe Parameter Fallback (CRITICAL for this task)
- **Pattern**: Check key existence explicitly instead of using `or` operator
- **Where it was used**: Task 11.1 - file node parameter handling
- **Why it's relevant**: All file manipulation nodes will handle parameters that could be empty strings (e.g., empty file paths are invalid but still falsy)
- **Key learning**: `shared.get("path") or self.params.get("path")` fails with empty strings

### Tuple Return Pattern for Error Handling
- **Pattern**: Return `(result, success_bool)` from exec() methods
- **Where it was used**: Task 11.1 - ReadFileNode and WriteFileNode
- **Why it's relevant**: Copy/move/delete operations need consistent error handling
- **Enables**: Distinction between retryable and non-retryable errors

### Node vs BaseNode for I/O Operations
- **Pattern**: Use `Node` base class for automatic retry logic
- **Where it was used**: Task 11.1 - All file operations
- **Why it's relevant**: File operations can fail transiently (locked files, network drives)
- **Implementation**: `super().__init__(max_retries=3, wait=0.1)`

### Directory Creation Pattern
- **Pattern**: Use `os.makedirs(parent_dir, exist_ok=True)` before file operations
- **Where it was used**: Task 11.1 - WriteFileNode
- **Why it's relevant**: Copy and move operations may need to create destination directories

### Import Path Pattern for PocketFlow
- **Pattern**: Use sys.path.insert for pocketflow imports
- **Where it was used**: All node implementations
- **Why it's relevant**: Required until proper packaging is implemented
- **Example**: `sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))`

## Known Pitfalls to Avoid

### Empty String Truthiness Bug
- **Pitfall**: Using `or` operator for parameter fallback
- **Where it failed**: Task 11.1 - initial implementation
- **How to avoid**: Always check key existence explicitly

### Reserved Logging Field Names
- **Pitfall**: Using "filename" in logging extra dict
- **Where it failed**: Task 4.2
- **How to avoid**: Use "file_path" instead for file-related logging

### Non-Retryable vs Retryable Errors
- **Pitfall**: Raising exceptions for all errors
- **Where it failed**: Not directly observed but warned in handoff
- **How to avoid**: Return tuple immediately for non-retryable errors (file not found), raise RuntimeError only for retryable errors

## Established Conventions

### Error Message Format
- **Convention**: Include file paths in error messages
- **Where decided**: Task 11.1
- **Must follow**: All file operation errors should show the problematic path

### Shared Store Key Names
- **Convention**: Natural, self-documenting keys
- **Where decided**: Project documentation
- **Must follow**:
  - `source_path` and `dest_path` for copy/move
  - `file_path` for single file operations
  - `content` for file contents

### Comprehensive Docstrings
- **Convention**: Include Interface section with Reads/Writes/Actions
- **Where decided**: Simple node architecture pattern
- **Must follow**: All nodes must document their shared store interface

### Test-As-You-Go Development
- **Convention**: Write tests immediately with implementation
- **Where decided**: Task 1.3
- **Must follow**: Every node needs corresponding test cases

## Codebase Evolution Context

### File Node Foundation Established
- **What changed**: ReadFileNode and WriteFileNode implemented in 11.1
- **When**: Task 11.1 completion
- **Impact on this task**:
  - Established patterns to follow
  - Test structure already in place
  - Import patterns proven to work
  - Error handling approach validated

### Registry Integration Proven
- **What changed**: Node discovery works with new nodes
- **When**: Task 11.1
- **Impact on this task**: Must update __init__.py to export new nodes

### Testing Patterns Established
- **What changed**: test_file_nodes.py created with integration test pattern
- **When**: Task 11.1
- **Impact on this task**: Add tests to existing file, follow established patterns

## Technical Insights from Subtask 11.1

### Atomic Operations Complexity
- **Insight**: Move operations are NOT always atomic
- **Evidence**: os.rename only atomic on same filesystem
- **Application**: MoveFileNode needs fallback to copy+delete

### Safety Considerations
- **Insight**: Destructive operations need explicit safety checks
- **Evidence**: Spec mentions "safety parameter" but doesn't define behavior
- **Application**: Need to decide on safety mechanism (confirmation flag, dry-run mode, etc.)

### Cross-Platform Considerations
- **Insight**: File operations behave differently on Windows vs Unix
- **Evidence**: Symbolic links, permissions, atomic moves
- **Application**: Test on multiple platforms or document limitations

## Cookbook Patterns to Review

Based on the project context and subtask 11.1 experience:
- **Tutorial-Cursor/utils/**: Contains file operation patterns
- **Error handling patterns**: Tuple return style from Tutorial-Cursor
- **Node lifecycle patterns**: How to properly use prep/exec/post
