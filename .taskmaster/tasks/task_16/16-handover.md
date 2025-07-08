# Handoff Memo: Task 16 - Create Planning Context Builder

**TO THE IMPLEMENTING AGENT**: Read this entire memo before starting. When done, acknowledge you're ready to begin - DO NOT start implementing immediately.

## 🎯 What Task 16 REALLY Needs to Do

Task 16 creates a context builder that formats node metadata for the LLM-based planner. You're building the bridge between Task 7's metadata extractor and Task 17's natural language planner. The LLM needs to understand what "tools" (nodes) are available to build workflows.

## 🔍 Critical Context from Task 7

### The Metadata You'll Be Working With

Task 7's `PflowMetadataExtractor` produces this exact format:
```python
{
    'description': 'Read content from a file and add line numbers for display.',
    'inputs': ['file_path', 'encoding'],
    'outputs': ['content', 'error'],
    'params': ['file_path', 'encoding'],
    'actions': ['default', 'error']
}
```

**Key insights:**
- `inputs` = keys read from shared store
- `outputs` = keys written to shared store
- `params` = parameters that can ALSO be set via node.set_params() as fallbacks
- `actions` = transition strings (usually just 'default' and 'error')

### How to Get This Metadata

You'll receive `registry_metadata` from Task 5's registry, but that only has basic info. To get the detailed metadata:

```python
from pflow.registry.metadata_extractor import PflowMetadataExtractor
from pflow.runtime.compiler import import_node_class

extractor = PflowMetadataExtractor()

# For each node in registry_metadata:
node_class = import_node_class(node_name, registry)
metadata = extractor.extract_metadata(node_class)
```

## 💣 Critical Design Decisions You Must Make

### 1. The "Params vs Shared Store" Complexity

Nodes in pflow have a unique dual-input pattern:
- They primarily read from shared store (`shared["key"]`)
- They can ALSO accept params via `node.set_params()` as fallbacks

Example: ReadFileNode can get `file_path` from:
1. `shared["file_path"]` (primary)
2. `node.set_params({"file_path": "/path"})` (fallback)

**Your context MUST explain this clearly to the LLM!**

### 2. Output Format for LLM Consumption

The spec suggests "markdown tables or structured text" but doesn't mandate a format. Based on my experience with LLMs, I recommend:

```markdown
## Available Nodes

### read-file
Reads content from a file and adds line numbers for display.

**Inputs** (from shared store):
- `file_path` - Path to the file to read
- `encoding` - Text encoding (optional, defaults to utf-8)

**Outputs** (to shared store):
- `content` - File contents with line numbers (on success)
- `error` - Error message (on failure)

**Parameters** (can also be set directly on node):
- `file_path` - Same as input
- `encoding` - Same as input

**Actions**: default (success), error (failure)
```

This format is:
- Clear for LLMs to parse
- Human-readable for debugging
- Includes the critical shared vs params distinction

## ⚠️ Warnings and Gotchas

### 1. Not All Nodes Have Interface Sections
Some nodes (like test nodes) have no Interface section. The metadata extractor returns empty lists. Your context builder should handle this gracefully - maybe skip them or mark as "utility nodes".

### 2. Registry Metadata is Incomplete
Task 5's registry only stores:
```python
{
    "module": "src.pflow.nodes.file.read_file",
    "class_name": "ReadFileNode",
    "name": "read-file",
    "type": "file",
    "description": "Read a file from disk"  # Just first line!
}
```

You MUST use the metadata extractor to get the full Interface details.

### 3. Dynamic Import Required
You'll need to dynamically import each node class. Use the pattern from `pflow.runtime.compiler`:
```python
from pflow.runtime.compiler import import_node_class

try:
    node_class = import_node_class(node_name, registry)
except ImportError:
    # Handle missing nodes gracefully
    pass
```

## 🔗 Key Files and References

### Must-Read Documentation
- `/docs/features/planner.md#6.1` - Context builder requirements
- `/docs/core-concepts/shared-store.md` - Understand shared vs params pattern

### Code You'll Need
- `/src/pflow/registry/metadata_extractor.py` - Task 7's extractor (use it!)
- `/src/pflow/runtime/compiler.py` - Has `import_node_class()` function
- `/src/pflow/registry/registry.py` - Registry interface

### Test Examples
- `/tests/test_registry/test_metadata_extractor.py` - Shows all the metadata formats you'll encounter

## 🎁 Implementation Suggestions

1. **Start Simple**: Get basic formatting working with just read-file and write-file nodes
2. **Handle Edge Cases**: Nodes without Interface, import failures, etc.
3. **Optimize for LLM**: The format should help the LLM understand node connections (outputs → inputs)
4. **Consider Grouping**: Maybe group nodes by type (file, transform, etc.) in the output

## 📊 Success Metrics

Your context builder succeeds when:
1. The LLM can understand what each node does
2. The LLM knows which shared store keys connect nodes
3. The params vs shared store distinction is clear
4. Edge cases (no Interface, import errors) don't crash

## 🚨 Do NOT:
- Try to create a complex JSON schema - keep it readable text
- Skip the metadata extractor - you NEED those Interface details
- Assume all nodes have complete metadata - many don't

## 🎯 Your First Step

Read the planner.md documentation to understand how your context builder fits into the larger planning system. The context you generate is literally the "available tools" the LLM uses to build workflows.

---

**IMPORTANT**: Read this entire memo, understand the context, then acknowledge you're ready to begin. Do NOT start implementing until you've fully grasped what Task 7 provides and what Task 17 needs.
