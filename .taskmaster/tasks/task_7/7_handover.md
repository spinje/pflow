# Handoff Memo: Task 7 - Extract Node Metadata from Docstrings

**TO THE IMPLEMENTING AGENT**: Read this entire memo before starting. When done, acknowledge you're ready to begin - DO NOT start implementing immediately.

## 🚨 Critical Context You're Inheriting

### The Non-Obvious Truth About This Task
Task 7 is about **runtime introspection**, not registry enhancement. The task description mentions "Takes a node CLASS as input (not registry data)" - this is crucial. You're building a tool that other components will use AFTER they've already imported a node class.

### What Task 5 Already Did (Don't Duplicate!)
Task 5's scanner (`src/pflow/registry/scanner.py`) already extracts basic metadata:
- Module path, class name, file path
- Raw docstring (unparsed)
- Basic node name from class or attribute

**Your job**: Parse the docstring deeply to extract structured interface information.

## 🎯 The Real Purpose

This metadata extractor enables:
1. **Task 17 (Natural Language Planner)**: PRIMARY CONSUMER - Needs to know what nodes read/write for intelligent chaining
2. **Task 10 (Registry CLI)**: Shows detailed node information to users
3. **Future tooling**: IDE support, documentation generation, validation

**Note**: Task 4 (IR Compiler) does NOT need this - it just imports and instantiates nodes.

## 💡 Key Discoveries from the Actual Codebase

### 1. The ACTUAL Docstring Format Being Used

All implemented nodes use this **single-line format**:

```python
"""One-line description.

Detailed description paragraph.

Interface:
- Reads: shared["file_path"] (required), shared["encoding"] (optional)
- Writes: shared["content"] on success, shared["error"] on failure
- Params: file_path, encoding (as fallbacks if not in shared)
- Actions: default (success), error (failure)

Security Note: Optional security warnings.
Performance Note: Optional performance notes.
"""
```

**Real examples from the codebase**:
- `/src/pflow/nodes/file/read_file.py` (lines 18-32)
- `/src/pflow/nodes/file/write_file.py` (lines 21-39)
- `/src/pflow/nodes/file/copy_file.py` (lines 21-36)

**Critical insight**: This is NOT the indented YAML-like format shown in some docs. Parse what's actually there!

### 2. Node Inheritance Pattern

From examining the codebase:
- **Production nodes** inherit from `Node` (for retry support)
- **Test nodes** may inherit from `BaseNode` (simpler)
- Both are valid pflow nodes

**Your metadata extractor should accept BOTH**:
```python
import pocketflow

def is_node_class(cls):
    try:
        return issubclass(cls, pocketflow.BaseNode)
    except TypeError:
        return False
```

### 3. Parameter Classification (pflow's Unique Pattern)

Nodes have a unique pattern where parameters can come from EITHER:
1. **Shared store keys** (listed under Reads/Writes)
2. **Node parameters** (set via `node.set_params()`)

Example from WriteFileNode:
```python
# In prep():
content = shared.get("content") or self.params.get("content")
```

**The ambiguity**: Some params can be EITHER shared store OR node params (like `content` above). The docstring doesn't always make this clear.

**How to extract params**: Use the "Params:" line in the docstring when present. This explicitly lists which parameters the node accepts as fallbacks.

## ⚠️ Critical Decisions and Recommendations

### 1. What to Parse
**Parse the ACTUAL format** used by all current nodes (single-line format shown above). Do NOT try to parse theoretical formats from documentation.

### 2. How to Extract Parameters
**Extract from the "Params:" line** in the Interface section. This is the most reliable source as it's explicitly documented by node authors.

**Alternatives considered but not recommended**:
- Inspecting class attributes (unreliable, not all params are attributes)
- Analyzing set_params() calls (complex, requires runtime inspection)
- AST parsing (overkill for this use case)

### 3. Error Handling Strategy
**Be forgiving and extract what's available**:
- No docstring? → Return `{'description': 'No description', 'inputs': [], 'outputs': [], 'params': [], 'actions': []}`
- No Interface section? → Return empty lists for interface data
- Malformed section? → Extract what's parseable, skip the rest
- Not a node? → Raise clear `ValueError`

### 4. Output Format
The task specifies this output format - stick to it:
```python
{
    'description': 'Get GitHub issue',      # First line of docstring
    'inputs': ['issue_number', 'repo'],     # From "Reads:" line
    'outputs': ['issue'],                   # From "Writes:" line
    'params': ['token'],                    # From "Params:" line
    'actions': ['default', 'not_found']     # From "Actions:" line
}
```

## 🔍 Parser Implementation Guidance

### Core Architecture

```python
import re
import inspect
from typing import Dict, Any, List

class PflowMetadataExtractor:
    """Extract metadata from pflow node docstrings."""

    def extract_metadata(self, node_class: type) -> Dict[str, Any]:
        """Extract metadata from a node class.

        Args:
            node_class: A class that inherits from pocketflow.BaseNode

        Returns:
            Dictionary with description, inputs, outputs, params, actions

        Raises:
            ValueError: If node_class is not a valid pflow node
        """
        # Validate it's a node
        if not is_node_class(node_class):
            raise ValueError(f"{node_class.__name__} is not a pflow node")

        docstring = inspect.getdoc(node_class) or ""

        # Extract components
        description = self._extract_description(docstring)
        interface_data = self._parse_interface_section(docstring)

        return {
            'description': description,
            'inputs': interface_data.get('reads', []),
            'outputs': interface_data.get('writes', []),
            'params': interface_data.get('params', []),
            'actions': interface_data.get('actions', [])
        }
```

### Parsing the Interface Section

```python
def _parse_interface_section(self, docstring: str) -> Dict[str, List[str]]:
    """Parse the Interface: section of the docstring."""
    # Find the Interface section
    interface_match = re.search(r'Interface:\s*\n((?:[ \t]*-[^\n]+\n)*)', docstring, re.MULTILINE)
    if not interface_match:
        return {}

    interface_text = interface_match.group(1)
    result = {}

    # Parse each line type
    for line in interface_text.split('\n'):
        line = line.strip()
        if not line or not line.startswith('-'):
            continue

        if line.startswith('- Reads:'):
            result['reads'] = self._extract_keys_from_line(line, 'Reads:')
        elif line.startswith('- Writes:'):
            result['writes'] = self._extract_keys_from_line(line, 'Writes:')
        elif line.startswith('- Params:'):
            result['params'] = self._extract_params_from_line(line)
        elif line.startswith('- Actions:'):
            result['actions'] = self._extract_actions_from_line(line)

    return result

def _extract_keys_from_line(self, line: str, prefix: str) -> List[str]:
    """Extract shared store keys from Reads/Writes lines."""
    # Remove prefix
    content = line[len(f"- {prefix}"):].strip()

    # Find all shared["key"] patterns
    keys = re.findall(r'shared\["([^"]+)"\]', content)
    return keys

def _extract_params_from_line(self, line: str) -> List[str]:
    """Extract parameter names from Params line."""
    # Remove "- Params:" prefix
    content = line[len("- Params:"):].strip()

    # Split by commas and clean up
    params = []
    for param in content.split(','):
        # Remove parenthetical notes
        param = re.sub(r'\([^)]+\)', '', param).strip()
        if param and param != 'as fallbacks if not in shared':
            params.append(param)

    return params

def _extract_actions_from_line(self, line: str) -> List[str]:
    """Extract action names from Actions line."""
    # Remove "- Actions:" prefix
    content = line[len("- Actions:"):].strip()

    # Find all action names (word followed by optional parenthetical)
    actions = re.findall(r'(\w+)(?:\s*\([^)]+\))?', content)
    return actions
```

## 🚫 What NOT to Do

1. **Don't parse theoretical formats** - Only parse the actual single-line format used by nodes
2. **Don't modify the registry** - This is a standalone utility
3. **Don't import all nodes** - Work with classes passed to you
4. **Don't enforce strict formatting** - Be permissive in parsing
5. **Don't parse standard docstring params** - They don't match our Interface pattern
6. **Don't parse method docstrings** - Only the class docstring matters
7. **Don't try to understand the retry pattern** - That's runtime behavior, not metadata
8. **Don't use docstring_parser for Interface sections** - Our format is custom, use regex

## 📍 Testing Strategy

Create comprehensive tests with these cases:

### 1. Real Node Tests
```python
# Test with actual file nodes
from pflow.nodes.file.read_file import ReadFileNode
metadata = extractor.extract_metadata(ReadFileNode)
assert metadata['inputs'] == ['file_path', 'encoding']
assert metadata['outputs'] == ['content', 'error']
```

### 2. Edge Case Tests
- Node with no docstring → `{'description': 'No description', 'inputs': [], ...}`
- Node with description but no Interface → Empty lists for interface data
- Node with partial Interface (only Reads/Writes) → Extract what's available
- Malformed Interface section → Best effort extraction
- Non-node class → Should raise `ValueError`
- Multi-line descriptions in Interface → Handle continuation correctly

### 3. Both Inheritance Types
- Test with `Node` subclass (production pattern)
- Test with `BaseNode` subclass (test pattern)
- Test with both test nodes: `test_node.py` and `test_node_retry.py`

## 🎁 Helpful Code Snippets

### Regex Patterns
```python
# Match Interface section
INTERFACE_PATTERN = r'Interface:\s*\n((?:[ \t]*-[^\n]+\n)*)'

# Extract shared["key"] patterns
SHARED_KEY_PATTERN = r'shared\["([^"]+)"\]'

# Split actions (handle both simple and with descriptions)
ACTIONS_PATTERN = r'(\w+)(?:\s*\([^)]+\))?'
```

### Description Extraction
```python
def _extract_description(self, docstring: str) -> str:
    """Extract first line/paragraph as description."""
    if not docstring:
        return "No description"

    # Split into lines
    lines = docstring.strip().split('\n')

    # First non-empty line is the description
    for line in lines:
        line = line.strip()
        if line:
            return line

    return "No description"
```

## 🔍 Where to Look for Implementation Reference

### Working Node Examples
- `/src/pflow/nodes/file/*.py` - All have well-formatted docstrings
- Especially `write_file.py` - Complex with many parameters
- `/src/pflow/nodes/test_node.py` - Shows BaseNode inheritance
- `/src/pflow/nodes/test_node_retry.py` - Shows Node inheritance

### Test Infrastructure
- `/tests/test_nodes/test_file/` - Shows how nodes are used
- `/tests/test_registry/test_scanner.py` - Shows Task 5's approach

### Documentation
- `/docs/features/simple-nodes.md` - Defines the Interface pattern philosophy
- `/docs/implementation-details/metadata-extraction.md` - Your specification (but uses theoretical format)

## 📝 Final Implementation Checklist

- [ ] Create `src/pflow/registry/metadata_extractor.py` with `extract_metadata(node_class)` function
- [ ] Accepts both `Node` and `BaseNode` subclasses
- [ ] Parses the actual single-line Interface format
- [ ] Extracts params from "Params:" line when present
- [ ] Returns specified output format exactly
- [ ] Handles missing/malformed sections gracefully
- [ ] Raises ValueError for non-nodes
- [ ] Includes comprehensive tests
- [ ] Works with all existing file nodes

## Summary

You're building a docstring parser that understands pflow's specific Interface format. Focus on parsing what's actually there in the codebase, not theoretical formats from docs. Be forgiving in parsing but strict about the output format. The primary consumer is the Natural Language Planner (Task 17), which needs to understand what nodes read and write to chain them intelligently.

Good luck! 🚀

---

**Remember**: Acknowledge you've read this before starting implementation.
