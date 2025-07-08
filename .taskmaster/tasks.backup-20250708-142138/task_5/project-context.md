# Project Context for Task 5: Implement node discovery via filesystem scanning

## Task Overview

Task 5 implements the foundation of pflow's node discovery system by creating a filesystem scanner that:
- Finds all classes inheriting from `pocketflow.BaseNode`
- Extracts basic metadata from discovered nodes
- Stores the registry in a persistent JSON file at `~/.pflow/registry.json`

This is a foundational component that enables dynamic node discovery and sets up the infrastructure for the IR compiler (Task 4) and metadata extraction (Task 7).

## Key Technical Concepts

### BaseNode vs Node Inheritance
The pocketflow framework provides two base classes:
- **BaseNode**: The fundamental class with prep/exec/post lifecycle
- **Node**: Extends BaseNode with retry logic and additional features

**CRITICAL**: Task 5 must detect classes inheriting from `pocketflow.BaseNode`, NOT `pocketflow.Node`. This is explicitly stated in the implementation details and ensures maximum flexibility for node implementations.

### Node Registry Architecture
The registry follows a simple but effective design:
- **Metadata-only storage**: Registry stores information about nodes, not class references
- **Dynamic imports**: Components using the registry must use importlib to load nodes
- **JSON persistence**: Simple file-based storage at `~/.pflow/registry.json`
- **Multiple lookup keys**: Nodes can be found by various naming conventions

### Node Naming Conventions
Nodes follow a two-tier naming approach:
1. **Explicit name**: Check for `name` class attribute first
2. **Kebab-case fallback**: Convert ClassName to kebab-case (e.g., ReadFileNode → read-file)

Example patterns:
- Platform-specific: `github-get-issue`, `github-create-pr`
- General purpose: `llm`, `read-file`, `write-file`

## Implementation Requirements

### Scope for MVP
- **Scan location**: Only `Path(pflow.__file__).parent / 'nodes'` (package nodes)
- **No user directories**: MVP excludes ~/.pflow/nodes/, /etc/pflow/nodes/, etc.
- **Security note**: Must document that importlib executes code on import

### Required Metadata Fields
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

### Test Node Requirement
Task 5 must create `src/pflow/nodes/test_node.py` with:
- A class inheriting from `pocketflow.BaseNode`
- Proper Interface docstring format
- Used for testing the discovery system

## Integration Points

### Upstream Dependencies
- **pocketflow framework**: Provides BaseNode class definition
- **Package structure**: Requires src/pflow/nodes/ directory (to be created)

### Downstream Consumers
1. **Task 4 (IR Compiler)**: Will use registry to dynamically import nodes
2. **Task 7 (Metadata Extraction)**: Will parse the raw docstrings we collect
3. **Task 10 (Registry Commands)**: Will provide CLI interface to registry data

## Technical Patterns from Research

### Module Organization Pattern
The research suggests a clear directory structure:
```
src/pflow/nodes/
├── file/
│   ├── __init__.py
│   ├── read_file.py
│   └── write_file.py
├── llm/
│   └── llm_node.py
└── test_node.py  # Required by Task 5
```

### Discovery Implementation Pattern
Key steps for the scanner:
1. Use pathlib for efficient file traversal
2. Filter for .py files (exclude __pycache__, etc.)
3. Use importlib.import_module() for dynamic loading
4. Use inspect.isclass() and issubclass() for detection
5. Extract metadata in a single pass
6. Handle import errors gracefully

### Testing Strategy Pattern
From Task 1's successful test-as-you-go approach:
- Write tests alongside implementation
- Use mock nodes to test discovery logic
- Test edge cases (no docstring, no name attribute)
- Mock importlib where needed to avoid side effects

## Potential Challenges and Mitigations

### Challenge: Import Side Effects
- **Risk**: importlib.import_module() executes module code
- **Mitigation**: For MVP with trusted package nodes, this is acceptable. Add clear security warning for future versions

### Challenge: Module Path Resolution
- **Risk**: Complex import paths and package structures
- **Mitigation**: Use fully qualified module paths based on pflow package root

### Challenge: Class Detection Edge Cases
- **Risk**: Multiple inheritance, abstract classes, etc.
- **Mitigation**: Strict check for direct BaseNode inheritance, exclude BaseNode itself

## Applied Knowledge from Previous Tasks

### From Task 1 (Package Setup)
- **Pattern**: Test-as-you-go development proven successful
- **Pattern**: Module organization with __init__.py and separate implementation files
- **Decision**: Use click.testing.CliRunner pattern for testing CLI integration

### From Knowledge Base
- **Pattern**: File-based storage preferred over complex databases
- **Pattern**: Keep systems simple and append-friendly
- **Decision**: Integrated testing within implementation tasks

## Success Criteria

1. Scanner correctly identifies all BaseNode subclasses
2. Metadata extraction includes all required fields
3. Registry persists to ~/.pflow/registry.json
4. Test node created and discovered successfully
5. Comprehensive test coverage including edge cases
6. Clear documentation of security considerations
7. Clean integration points for downstream tasks

## Key Documentation References

Essential pflow documentation:
- `docs/core-concepts/registry.md` - Complete registry design and architecture
- `docs/implementation-details/metadata-extraction.md` - Detailed extraction specifications
- `docs/core-node-packages/*.md` - Node specifications for future reference

PocketFlow documentation (if needed during implementation):
- `pocketflow/__init__.py` - BaseNode class definition
- `pocketflow/docs/core_abstraction/node.md` - Node lifecycle understanding

## Next Steps After Task 5

This task creates the foundation for:
1. Task 4 can use the registry to load nodes dynamically
2. Task 7 can enhance metadata extraction with parsed docstrings
3. Task 10 can provide user-facing registry commands
4. Future node implementations (Tasks 11-14) will be automatically discovered
