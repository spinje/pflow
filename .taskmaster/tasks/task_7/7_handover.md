# Handoff Memo: Task 7 - Extract Node Metadata from Docstrings

**TO THE IMPLEMENTING AGENT**: Read this entire memo before starting. When done, acknowledge you're ready to begin - DO NOT start implementing immediately.

## 🚨 Critical Context You're Inheriting

### The Non-Obvious Truth About This Task
Task 7 is about **runtime introspection**, not registry enhancement. The task description mentions "Takes a node CLASS as input (not registry data)" - this is crucial. You're building a tool that other components will use AFTER they've already imported a node class.

### What Task 5 Already Did (Don't Duplicate!)
Task 5's scanner (`src/pflow/registry/scanner.py`) already extracts basic metadata:
- Module path, class name, file path
- Simple docstring extraction
- Basic node name from class or attribute

**Your job**: Parse the docstring deeply to extract structured interface information.

## 🎯 The Real Purpose

This metadata extractor enables:
1. **Task 4 (IR Compiler)**: After dynamic import, needs to understand node interfaces
2. **Task 17 (Planner)**: Needs to know what nodes read/write for intelligent chaining
3. **Future tooling**: IDE support, documentation generation, validation

## 💡 Key Discoveries from Related Work

### 1. Node Docstring Patterns (from Task 11)
Look at the file nodes for the ACTUAL docstring format being used:
- `/src/pflow/nodes/file/read_file.py` (lines 15-35)
- `/src/pflow/nodes/file/write_file.py` (lines 13-44)

```python
"""One-line description.

Detailed description paragraph.

Interface:
    Reads:
        - file_path: Path to file to read
    Writes:
        - content: File content with line numbers
        - error: Error message if read fails
    Actions:
        - default: Success
        - error: Read failure
"""
```

**Critical insight**: The Interface section uses a custom format, NOT standard Google/NumPy style!

### 2. Parameter Classification Challenge
Nodes have TWO types of parameters:
1. **Shared store keys** (listed under Reads/Writes)
2. **Node parameters** (set via `node.set_params()`)

Example from WriteFileNode:
- Reads from shared: `content` (or uses params)
- Params: `file_path`, `content`, `append`, `encoding`

**The ambiguity**: Some params can be EITHER (like `content` above). The docstring doesn't always make this clear.

### 3. BaseNode vs Node Inheritance
From Task 4's experience:
- PocketFlow has `BaseNode` (basic) and `Node` (with retry)
- Most nodes inherit from `Node`, not `BaseNode`
- **You need to check for both** when verifying inheritance

## ⚠️ Gotchas That Will Bite You

### 1. Docstring Parser Library Limitations
The task mentions "docstring_parser library" but our Interface format is custom. You'll need:
- Basic parsing for description
- Custom regex for Interface sections
- Don't try to force standard parsers to understand our format

### 2. Optional Sections
Not all nodes have all Interface subsections:
- Some nodes only Write, never Read
- Some nodes have no Actions (just return "default")
- Some nodes have no Params at all

### 3. Multi-line Descriptions in Interface
Look at WriteFileNode's Interface section - descriptions can span multiple lines:
```
    Writes:
        - written: Success message with file path (or error message
                  if write fails)
```

Your parser needs to handle this continuation.

## 🔍 Where to Look for Examples

### Working Node Examples
- `/src/pflow/nodes/file/*.py` - All have well-formatted docstrings
- Especially `write_file.py` - complex with many parameters

### Test Infrastructure
- `/tests/test_nodes/test_file/` - Shows how nodes are used
- `/tests/test_registry/test_scanner.py` - Shows Task 5's approach

### Documentation
- `/docs/features/simple-nodes.md` - Defines the Interface pattern
- `/docs/implementation-details/metadata-extraction.md` - Your specification

## 🚀 Quick Architecture Decisions

### 1. Function Signature
```python
def extract_metadata(node_class: type) -> dict[str, Any]:
    """Extract metadata from a node class."""
```
Takes a CLASS (not instance), returns structured dict.

### 2. Output Format
The task specifies:
```python
{
    'description': 'Get GitHub issue',
    'inputs': ['issue_number', 'repo'],  # From "Reads"
    'outputs': ['issue'],                # From "Writes"
    'params': ['token'],                 # From class inspection?
    'actions': ['default', 'not_found']  # From "Actions"
}
```

**Question for you**: How do you determine 'params'? The docstring might not list them.

### 3. Error Handling
What if:
- No docstring?
- No Interface section?
- Malformed Interface?
- Not a node class?

**Recommendation**: Return partial metadata rather than failing completely.

## 📍 Integration Points

### Who Will Use This
1. **IR Compiler** (`/src/pflow/runtime/compiler.py`):
   - After `module = import_module(module_path)`
   - Before `node = node_class()`
   - To validate parameters match IR

2. **Future Planner** (Task 17):
   - To understand what nodes produce/consume
   - To chain nodes intelligently

### Testing Strategy
Create test nodes with various docstring formats:
- Minimal (just description)
- Full (all Interface sections)
- Malformed (missing colons, bad indentation)
- Edge cases (no docstring, not a node)

## 🎁 Useful Code Snippets

### Checking Node Inheritance
```python
import pocketflow

def is_node_class(cls):
    try:
        return issubclass(cls, pocketflow.BaseNode)
    except TypeError:
        return False
```

### Basic Interface Section Regex
```python
interface_pattern = r'Interface:\s*\n((?:[ \t]+.+\n)*)'
reads_pattern = r'Reads:\s*\n((?:[ \t]+-[^\n]+\n(?:[ \t]+[^\n]+\n)*)*)'
```

### Handling Multi-line Values
The continuation lines in Interface sections are indented more than the bullet points.

## 🚫 What NOT to Do

1. **Don't modify the registry** - This is a standalone utility
2. **Don't import all nodes** - Work with classes passed to you
3. **Don't enforce strict formatting** - Be permissive in parsing
4. **Don't parse params from docstring** - They're not reliably documented there

## Final Note

This task bridges the gap between Task 5's basic discovery and Task 17's intelligent planning. Think of it as building a "docstring interpreter" that understands our specific node documentation format.

The hardest part isn't the parsing - it's deciding what to do when the docstring doesn't match expectations. Be resilient, extract what you can, and document your decisions.

Good luck! 🚀

---

**Remember**: Acknowledge you've read this before starting implementation.
