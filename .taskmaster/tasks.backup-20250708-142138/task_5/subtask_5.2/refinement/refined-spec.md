# Refined Specification for Subtask 5.2

## Clear Objective
Implement a Registry class that persists scanner output to ~/.pflow/registry.json with proper JSON serialization and directory management.

## Context from Knowledge Base
- Building on: Scanner implementation from 5.1 that outputs metadata dictionaries
- Avoiding: Over-engineering with complex persistence mechanisms
- Following: Test-as-you-go pattern, simple JSON file storage convention
- **Scanner integration**: Use existing scanner output format without modifications

## Technical Specification

### Inputs
- Scanner output: List of metadata dictionaries with fields:
  - module (str): Full import path
  - class_name (str): Class name
  - name (str): Node identifier (kebab-case)
  - docstring (str): Raw docstring text
  - file_path (str): Absolute path to file

### Outputs
- Registry JSON file at `~/.pflow/registry.json`
- Format: Dictionary with node names as keys:
```json
{
  "node-name": {
    "module": "pflow.nodes.example",
    "class_name": "ExampleNode",
    "docstring": "...",
    "file_path": "/absolute/path.py"
  }
}
```

### Implementation Constraints
- Must use: Python standard json module
- Must avoid: External dependencies, complex locking mechanisms
- Must maintain: Exact field names from scanner output
- Location: Create new file `src/pflow/registry/registry.py`

## Implementation Details

### Registry Class Structure
```python
class Registry:
    def __init__(self, registry_path: Path = None):
        # Default to ~/.pflow/registry.json

    def load(self) -> dict[str, dict[str, Any]]:
        # Load existing registry, return empty dict if not found

    def save(self, nodes: dict[str, dict[str, Any]]) -> None:
        # Ensure directory exists, write JSON with indent=2

    def update_from_scanner(self, scan_results: list[dict[str, Any]]) -> None:
        # Convert scanner list to dict format, handle conflicts
```

### Key Behaviors
1. **Directory Creation**: Use `Path.mkdir(parents=True, exist_ok=True)`
2. **Name Conflicts**: Log warning if duplicate names found, last-wins
3. **Missing File**: Return empty dict from load(), don't error
4. **JSON Format**: Pretty-print with indent=2 for readability
5. **Update Strategy**: Complete replacement - scanner output becomes the new registry (no merging)

## Success Criteria
- [ ] Registry class created in `src/pflow/registry/registry.py`
- [ ] ~/.pflow/ directory created automatically if missing
- [ ] Scanner results correctly transformed to dict format
- [ ] JSON file readable and properly formatted
- [ ] Name conflicts logged with warnings
- [ ] All tests pass including edge cases
- [ ] No external dependencies added

## Test Strategy
- Unit tests: Registry methods (load, save, update)
- Edge cases: Missing file, corrupt JSON, permission errors
- Integration: Scanner output → Registry → JSON file
- Name conflicts: Verify warning logs
- Directory creation: Test auto-creation behavior

## Dependencies
- Requires: Scanner implementation from subtask 5.1
- Impacts: Future registry commands (Task 10) will read this file

## Decisions Made
- Regular class design (not singleton) for testability
- Complete replacement strategy for updates - no merging or timestamp checking (per user discussion)
- Warning logs for name conflicts but proceed with last-wins
- No file locking for MVP (document concurrent access limitation)
- Manual edits to registry.json will be lost on rescan (document this clearly)
