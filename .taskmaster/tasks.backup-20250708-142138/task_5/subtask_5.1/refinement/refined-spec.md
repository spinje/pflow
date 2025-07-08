# Refined Specification for Subtask 5.1

## Clear Objective
Create test nodes and implement the core filesystem scanner that discovers all classes inheriting from pocketflow.BaseNode and extracts basic metadata.

## Context from Knowledge Base
- Building on: Module organization patterns from Tasks 1-2, test-as-you-go development
- Avoiding: Over-engineering, complex abstractions for MVP
- Following: Python package conventions, error namespace patterns
- **Cookbook patterns to apply**: Minimal node pattern for test nodes, proper prep/exec/post lifecycle

## Technical Specification

### Inputs
- `directories`: List[Path] - Directories to scan for Python files
- For MVP: Will be called with `[Path(pflow.__file__).parent / 'nodes']`

### Outputs
- Returns: List[Dict[str, Any]] - List of discovered nodes with metadata
- Each dict contains:
  - `module`: str - Full import path (e.g., "pflow.nodes.test_node")
  - `class_name`: str - Class name (e.g., "TestNode")
  - `name`: str - Node identifier (explicit or kebab-case)
  - `docstring`: str - Raw class docstring
  - `file_path`: str - Absolute path to Python file

### Implementation Constraints
- Must use: importlib.import_module() for dynamic loading
- Must avoid: AST parsing, complex abstractions
- Must maintain: Clear separation from registry persistence (subtask 5.2)

## Success Criteria
- [ ] Create src/pflow/nodes/ directory structure
- [ ] Create test_node.py with BaseNode subclass
- [ ] Create test_node_retry.py with Node subclass
- [ ] Implement scan_for_nodes() in src/pflow/registry/scanner.py
- [ ] Add security warning comment about code execution
- [ ] Handle import errors gracefully with logging
- [ ] Extract all 5 metadata fields correctly
- [ ] All tests pass with good coverage

## Test Strategy
- Unit tests:
  - Test discovery of both test nodes
  - Test filtering of non-BaseNode classes
  - Test name extraction (explicit and kebab-case)
  - Test error handling with mocked import failures
  - Test empty directory handling
- Integration tests:
  - Test full scan of nodes directory
  - Test metadata completeness
- Manual verification:
  - Run scanner on test nodes
  - Verify metadata output format

## Dependencies
- Requires: pocketflow framework available
- Impacts: Subtask 5.2 will use scanner output for persistence

## Decisions Made
- Import path resolution: Add paths to sys.path temporarily (User decision pending)
- Test node structure: Create both BaseNode and Node examples for coverage
- Error handling: Log and continue scanning on import errors
- Directory creation: Create src/pflow/nodes/ as part of this task

## Implementation Steps

1. **Create directory structure**:
   - src/pflow/registry/__init__.py
   - src/pflow/registry/scanner.py
   - src/pflow/nodes/__init__.py

2. **Create test nodes**:
   - src/pflow/nodes/test_node.py (BaseNode)
   - src/pflow/nodes/test_node_retry.py (Node)
   - Include proper Interface docstrings

3. **Implement scanner**:
   - Path handling with pathlib
   - Dynamic imports with sys.path management
   - Class inspection with inspect module
   - Metadata extraction logic
   - Error handling and logging

4. **Write comprehensive tests**:
   - tests/test_scanner.py
   - Mock import failures
   - Test all edge cases

## Code Structure Preview

```python
# src/pflow/registry/scanner.py
import sys
import inspect
import importlib
from pathlib import Path
from typing import List, Dict, Any

def scan_for_nodes(directories: List[Path]) -> List[Dict[str, Any]]:
    """
    Scan directories for Python files containing BaseNode subclasses.

    SECURITY WARNING: This function uses importlib.import_module() which
    executes Python code. Only use with trusted source directories.
    """
    # Implementation here
```

## Cookbook Patterns to Apply

1. **Minimal Node Pattern**: Use for test_node.py - simple prep/exec/post
2. **Error Handling Pattern**: Graceful degradation from Task 2
3. **Module Organization**: Clean separation like CLI structure
