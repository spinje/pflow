# Refined Specification for Subtask 11.1

## Clear Objective
Implement foundational read-file and write-file nodes that establish robust file I/O patterns for the pflow system, using PocketFlow's Node base class with retry capabilities and Tutorial-Cursor's error handling patterns.

## Context from Knowledge Base
- Building on: Tutorial-Cursor file operation patterns with (result, success) tuples
- Avoiding: Reserved logging field names ("filename"), complex internal dispatch
- Following: Natural shared store interfaces, test-as-you-go development
- **Cookbook patterns to apply**: Tutorial-Cursor file utilities, Node retry pattern, line number formatting

## Technical Specification

### read-file Node

#### Inputs
- `shared["file_path"]` (required) - Path to file to read (string)
- `shared["encoding"]` (optional) - File encoding, defaults to "utf-8" (string)
- `self.params` can provide fallback values if not in shared store

#### Outputs
- On success:
  - `shared["content"]` - File contents with line numbers (string)
  - Returns "default" action
- On failure:
  - `shared["error"]` - Error message with context (string)
  - Returns "error" action

#### Implementation Details
- Use `Node` base class for retry capabilities
- Apply line number formatting (1-indexed) to output
- Handle missing files gracefully with clear error messages
- Support both absolute and relative paths

### write-file Node

#### Inputs
- `shared["content"]` (required) - Content to write (string)
- `shared["file_path"]` (required) - Path to write to (string)
- `shared["encoding"]` (optional) - File encoding, defaults to "utf-8" (string)
- `self.params["append"]` (optional) - Append mode flag, defaults to False (boolean)

#### Outputs
- On success:
  - `shared["written"]` - Confirmation with file path (string)
  - Returns "default" action
- On failure:
  - `shared["error"]` - Error message with context (string)
  - Returns "error" action

#### Implementation Details
- Create parent directories automatically using `os.makedirs(exist_ok=True)`
- Support both write and append modes
- Validate content before writing
- Use (result, success) tuple pattern in exec()

### Implementation Constraints
- Must use: Node base class from pocketflow, tuple return pattern, UTF-8 default encoding
- Must avoid: "filename" in logging fields, raising exceptions in exec()
- Must maintain: Natural shared store keys, clear error messages

### Module Structure
```
src/pflow/nodes/file/
├── __init__.py       # Expose ReadFileNode and WriteFileNode
├── read_file.py      # ReadFileNode implementation
└── write_file.py     # WriteFileNode implementation
```

### Node Naming
- Classes: `ReadFileNode`, `WriteFileNode`
- Node names: Will auto-convert to "read-file", "write-file" via kebab-case

## Success Criteria
- [ ] Both nodes inherit from pocketflow.Node
- [ ] Tuple pattern (result, success) used in exec methods
- [ ] Line numbers added to read-file output
- [ ] Parent directories created automatically for write-file
- [ ] Comprehensive error handling with context
- [ ] All tests pass including error cases
- [ ] No regressions in registry discovery
- [ ] Nodes discoverable via __init__.py exports

## Test Strategy
- Unit tests in `tests/test_file_nodes.py`:
  - Test successful file read/write operations
  - Test missing file handling
  - Test permission errors (where applicable)
  - Test empty files and special characters
  - Test encoding parameter support
  - Test append mode for write-file
  - Test shared store vs params precedence
  - Test line number formatting
- Integration tests:
  - Test nodes work with registry scanner
  - Test nodes compose in simple flows
  - Test error action transitions
- Manual verification:
  - Verify nodes appear in registry
  - Test with pflow CLI when available

## Dependencies
- Requires: pocketflow framework, Node base class
- Impacts: Sets patterns for future file manipulation nodes (copy, move, delete)

## Decisions Made
- Use Node instead of BaseNode for retry capabilities (evaluated in evaluation.md)
- Implement tuple return pattern for consistent error handling (evaluated)
- Add line numbers by default to read-file output (evaluated)
- Support encoding parameter with UTF-8 default (evaluated)
- Text files only for MVP, no binary file support (evaluated)
- No path security validation for MVP (evaluated)

## Security Considerations
- File nodes can read/write any accessible path on the system
- No built-in path traversal prevention in MVP
- Document that these nodes should not be exposed to untrusted input
- Future versions may add path validation

## Example Usage
```python
# Read a file
flow = Flow(name="read-example")
flow.add_node(ReadFileNode())
flow.shared["file_path"] = "config.json"
flow.start()
# Result: shared["content"] contains file with line numbers

# Write a file
flow = Flow(name="write-example")
flow.add_node(WriteFileNode())
flow.shared["content"] = "Hello, world!"
flow.shared["file_path"] = "output.txt"
flow.start()
# Result: shared["written"] confirms file creation
```
