# PocketFlow Patterns for Task 5: Node Discovery

## Task Context

- **Goal**: Scan filesystem for pocketflow.Node subclasses and extract metadata
- **Dependencies**: None (foundation task)
- **Constraints**: Must validate single-purpose design during discovery

## Core Patterns from Advanced Analysis

### Pattern: Module Organization for CLI Tools
**Found in**: All 7 repositories show consistent src/nodes/ structure
**Why It Applies**: Clear organization enables efficient scanning

```python
# Standard structure from analysis
project/
├── src/
│   └── nodes/
│       ├── github/
│       │   ├── __init__.py
│       │   ├── github_get_issue.py
│       │   └── github_create_pr.py
│       ├── llm/
│       │   ├── __init__.py
│       │   └── llm_node.py
│       └── file/
│           ├── __init__.py
│           ├── read_file.py
│           └── write_file.py
```

**Implementation Pattern**:
```python
from pathlib import Path
import importlib.util
import inspect
from pocketflow import Node

def scan_for_nodes(base_path: Path) -> List[NodeInfo]:
    """Scan organized structure for nodes"""
    nodes = []
    nodes_dir = base_path / "src" / "pflow" / "nodes"

    # Scan each category directory
    for category_dir in nodes_dir.iterdir():
        if category_dir.is_dir() and not category_dir.name.startswith("_"):
            nodes.extend(scan_category(category_dir))

    return nodes

def scan_category(category_path: Path) -> List[NodeInfo]:
    """Scan a category directory for node files"""
    nodes = []

    for py_file in category_path.glob("*.py"):
        if py_file.name.startswith("_"):
            continue

        # Import and inspect module
        module = import_module_from_path(py_file)

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Node) and obj != Node:
                # Validate single-purpose design
                if validates_single_purpose(obj):
                    nodes.append(extract_node_info(obj))
                else:
                    logger.warning(f"Node {name} violates single-purpose pattern")

    return nodes
```

### Pattern: Single-Purpose Validation During Discovery
**Found in**: Enforced by all successful repositories
**Why It Applies**: Ensures nodes follow pflow's philosophy from the start

```python
def validates_single_purpose(node_class) -> bool:
    """Validate node follows single-purpose pattern"""
    # Parse docstring for validation
    doc = node_class.__doc__ or ""

    # Rules from analysis:
    # 1. Single verb in description
    verb_count = count_action_verbs(doc)
    if verb_count > 1:
        return False

    # 2. Limited inputs/outputs
    metadata = extract_basic_metadata(node_class)
    if len(metadata.get("inputs", [])) > 3:
        return False
    if len(metadata.get("outputs", [])) > 2:
        return False

    # 3. Clear, focused purpose
    if "and" in doc.lower().split("\n")[0]:  # Multiple responsibilities
        return False

    return True

def count_action_verbs(text: str) -> int:
    """Count action verbs indicating responsibilities"""
    action_verbs = {
        "read", "write", "get", "create", "update", "delete",
        "analyze", "process", "transform", "validate", "execute",
        "fetch", "send", "parse", "format", "convert"
    }

    words = text.lower().split()
    return sum(1 for word in words if word in action_verbs)
```

### Pattern: Metadata Extraction with Natural Key Detection
**Found in**: Codebase Knowledge tutorial's clean extraction
**Why It Applies**: Helps Task 9 validate natural key usage

```python
def extract_node_info(node_class) -> NodeInfo:
    """Extract comprehensive node information"""
    # Basic metadata
    metadata = {
        "name": node_class.__name__,
        "module": node_class.__module__,
        "category": extract_category(node_class.__module__),
        "description": extract_description(node_class.__doc__),
        "inputs": [],
        "outputs": [],
        "params": [],
        "natural_keys": True  # Assume natural until proven otherwise
    }

    # Parse docstring for interface
    doc_info = parse_node_docstring(node_class.__doc__)
    metadata.update(doc_info)

    # Analyze prep/post methods for actual usage
    actual_usage = analyze_node_implementation(node_class)

    # Detect generic keys (anti-pattern)
    generic_keys = {"data", "input", "output", "result", "value"}
    used_keys = set(actual_usage.get("reads", [])) | set(actual_usage.get("writes", []))

    if used_keys & generic_keys:
        metadata["natural_keys"] = False
        metadata["warnings"] = [f"Uses generic keys: {used_keys & generic_keys}"]

    return NodeInfo(**metadata)
```

### Pattern: Fast Registry Building
**Found in**: All repositories use simple dict/JSON storage
**Why It Applies**: No need for complex indexing in MVP

```python
def build_node_registry(nodes: List[NodeInfo]) -> Dict[str, NodeInfo]:
    """Build simple registry for fast lookup"""
    registry = {}

    for node in nodes:
        # Multiple keys for lookup flexibility
        # By simple name: "llm" -> LLMNode
        simple_name = node.name.lower().replace("node", "")
        registry[simple_name] = node

        # By full name: "LLMNode" -> LLMNode
        registry[node.name] = node

        # By category-name: "github-get-issue" -> GitHubGetIssueNode
        category_name = f"{node.category}-{simple_name}".replace("_", "-")
        registry[category_name] = node

    return registry

def save_registry(registry: Dict[str, NodeInfo], path: Path):
    """Persist registry as simple JSON"""
    registry_data = {
        name: info.dict() for name, info in registry.items()
    }

    with open(path, "w") as f:
        json.dump(registry_data, f, indent=2)
```

## Anti-Patterns to Avoid

### Anti-Pattern: Deep Nesting
**Found in**: Over-engineered attempts at organization
**Issue**: Makes discovery complex and slow
**Alternative**: Flat category structure (one level deep)

### Anti-Pattern: Runtime Code Generation
**Found in**: Dynamic node creation attempts
**Issue**: Breaks static analysis and discovery
**Alternative**: All nodes defined as static classes

### Anti-Pattern: Circular Imports
**Found in**: Poor module organization
**Issue**: Breaks import and discovery
**Alternative**: Clear dependency hierarchy

## Implementation Guidelines

1. **Scan Efficiently**: Use pathlib and glob patterns
2. **Validate Early**: Check single-purpose during discovery
3. **Extract Thoroughly**: Get all metadata in one pass
4. **Cache Results**: Don't rescan unchanged files
5. **Clear Errors**: Report discovery issues clearly

## Testing Strategy

```python
# Create test node structure
test_nodes/
├── good/
│   └── simple_node.py    # Valid single-purpose
└── bad/
    └── complex_node.py   # Violates patterns

def test_single_purpose_validation():
    """Test validation logic"""

    class GoodNode(Node):
        """Read file from disk."""
        pass

    class BadNode(Node):
        """Read file, parse CSV, analyze data, and generate report."""
        pass

    assert validates_single_purpose(GoodNode) == True
    assert validates_single_purpose(BadNode) == False

def test_natural_key_detection():
    """Test generic key detection"""

    class NaturalKeysNode(Node):
        def post(self, shared, prep_res, exec_res):
            shared["file_content"] = exec_res
            shared["file_path"] = prep_res

    class GenericKeysNode(Node):
        def post(self, shared, prep_res, exec_res):
            shared["data"] = exec_res
            shared["output"] = prep_res

    natural_info = analyze_node_implementation(NaturalKeysNode)
    assert natural_info["natural_keys"] == True

    generic_info = analyze_node_implementation(GenericKeysNode)
    assert generic_info["natural_keys"] == False
```

## Integration Points

### Connection to Task 4 (IR Converter)
Task 5 provides the registry Task 4 needs:
```python
# Task 5 provides
registry = build_node_registry(discovered_nodes)

# Task 4 uses
NodeClass = registry[node_spec["type"]]
```

### Connection to Task 7 (Metadata Extraction)
Task 5 does basic extraction, Task 7 goes deeper:
```python
# Task 5: Quick scan for registry
basic_metadata = extract_node_info(NodeClass)

# Task 7: Detailed analysis for planner
detailed_metadata = extract_detailed_metadata(NodeClass)
```

### Connection to Task 9 (Shared Store)
Task 5 can warn about nodes that will need proxy:
```python
if not node_info.natural_keys:
    warnings.append(f"Node {node.name} may require proxy mappings")
```

## Minimal Test Case

```python
# Save as test_node_discovery.py and run with pytest
import tempfile
import json
from pathlib import Path
from pocketflow import Node

def create_test_node_file(path: Path, content: str):
    """Helper to create node files"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)

def test_discovery_pattern():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)

        # Create test structure
        nodes_dir = base / "src" / "pflow" / "nodes"

        # Good node
        create_test_node_file(
            nodes_dir / "file" / "read_file.py",
            '''from pocketflow import Node

class ReadFileNode(Node):
    """Read file from disk."""

    def post(self, shared, prep_res, exec_res):
        shared["file_content"] = exec_res
        shared["read_from"] = prep_res["path"]
'''
        )

        # Bad node (too complex)
        create_test_node_file(
            nodes_dir / "bad" / "kitchen_sink.py",
            '''from pocketflow import Node

class KitchenSinkNode(Node):
    """Read file, parse data, transform, analyze, and write output."""

    def post(self, shared, prep_res, exec_res):
        shared["data"] = exec_res  # Generic key!
'''
        )

        # Run discovery
        nodes = scan_for_nodes(base)

        # Validate results
        assert len(nodes) == 1  # Only good node discovered
        assert nodes[0].name == "ReadFileNode"
        assert nodes[0].natural_keys == True

        # Build registry
        registry = build_node_registry(nodes)
        assert "read-file" in registry
        assert "readfile" in registry
        assert "file-read-file" in registry

        print("✓ Discovery patterns validated")

if __name__ == "__main__":
    test_discovery_pattern()
```

## Summary

Task 5 establishes critical patterns for node discovery:

1. **Module Organization** - Standard structure for efficient scanning
2. **Single-Purpose Validation** - Enforce during discovery, not later
3. **Natural Key Detection** - Warn about nodes needing proxy
4. **Simple Registry** - Fast lookup without over-engineering

These patterns ensure only high-quality, single-purpose nodes enter the pflow ecosystem.
