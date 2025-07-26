# Node IR Implementation: Critical Context from Template System

## Strategic Context for the Implementer

You're about to refactor the core metadata system. Here's what I learned implementing templates that will save you hours of debugging.

## Core Outcomes from Template System (Task 18) You Must Preserve

### 1. The Wrapper Pattern is Sacred
The `TemplateAwareNodeWrapper` (src/pflow/runtime/node_wrapper.py) establishes a critical pattern:
- Nodes are **never modified** - they're wrapped
- The wrapper intercepts at `_run()` - this is the ONLY reliable interception point
- All other methods/attributes delegate transparently

**Why this matters for Node IR**: When you change how metadata flows, DO NOT break this wrapper's assumptions about node behavior.

### 2. The Fallback Pattern is Universal
Every pflow node implements:
```python
value = shared.get("key") or self.params.get("key")
```

This is why templates work. Your Node IR must preserve this pattern's semantics.

## Critical Files and Their Hidden Dependencies

### 1. metadata_extractor.py - The Beast
**Location**: `src/pflow/registry/metadata_extractor.py`

**What the docs don't tell you**:
- Lines 482-501: Format normalization is fragile - it uses regex that assumes specific docstring formatting
- The extractor can return EITHER simple format `["output1"]` OR rich format `[{"key": "output1", "type": "str"}]`
- **You MUST handle both** or validation will crash at runtime

**Hard-earned lesson**: I initially assumed outputs were always dicts. Wrong. Crashed on simple format nodes.

### 2. scanner.py - The Circular Import Trap
**Location**: `src/pflow/registry/scanner.py`

**The trap**:
- scanner.py is imported by registry.py at module level
- If you import MetadataExtractor at module level in scanner, you get circular imports
- The function-level import suggestion in docs is risky - use dependency injection

**What actually works**:
```python
# Pass extractor as parameter through the call chain
def scan_directory(path, extractor=None):
    if extractor is None:
        extractor = get_cached_extractor()
```

### 3. context_builder.py - The Performance Hog
**Location**: `src/pflow/planning/context_builder.py`

**Current reality** (lines 75-110):
- Imports EVERY node module dynamically
- Creates new MetadataExtractor instance per request
- No caching whatsoever

**Why this matters**: Your Node IR will make this 10x faster, but you need to preserve the exact output format or the planner breaks.

## Edge Cases That Will Bite You

### 1. Nodes Without Interface Sections
Many nodes have no Interface docstring. Current code in `get_nodes_context()` (line 83):
```python
metadata = extractor.extract_metadata(node_class)
```

Returns `{"inputs": [], "outputs": [], ...}` for these nodes. Your scanner MUST handle this gracefully.

### 2. The Structure Format Ambiguity
MetadataExtractor can return structures in multiple formats:
```python
# Format 1: Nested dicts
"structure": {
    "field1": {"subfield": "str"},
    "field2": "int"
}

# Format 2: Type strings
"structure": {
    "field1": "dict",
    "field2": "int"
}
```

Your path traversal must handle both.

### 3. Import-Time Side Effects
Some nodes (test_node_retry.py) have import-time side effects. When scanner imports them:
- They might print to stdout
- They might check for environment variables
- They might fail if certain packages aren't installed

**What I originally thought**: Skip bad nodes to keep development smooth.
**What's actually right for MVP**: FAIL FAST. If a node can't be imported, that's a bug that must be fixed. Don't hide problems.

**Better solution**: Let imports fail loudly, but provide clear error messages:
```
Failed to scan node at pflow/nodes/broken_node.py:
ImportError: Missing required package 'requests'
Fix: Install missing dependencies or fix the import
```

## Performance Gotchas

### 1. Registry File Size
Current registry.json with just docstrings: ~50KB
With full parsed interfaces: ~500KB-1MB

**This matters because**:
- Registry is loaded on EVERY pflow command
- It's parsed from JSON each time
- No lazy loading

**Consider**: Implementing lazy loading or splitting registry into chunks.

### 2. The Scanning Death Spiral
If one node has a malformed docstring, current proposal fails entire scan. But during development:
- Nodes are constantly being edited
- Docstrings get malformed
- One typo breaks everything

**The tension**: Fail fast (good for quality) vs. developer experience (bad for iteration speed)

**For MVP**: Stay consistent - fail fast with excellent error messages:
```
Failed to parse interface for node 'process-data':
  File: pflow/nodes/data/process_data.py
  Line 15: Invalid format in "- Writes: shared[data]: dict"
  Fix: Use quotes around key: shared["data"]
```

**Future enhancement**: Add `--skip-errors` flag for development convenience, but default to strict.

## Architectural Decisions That Aren't Obvious

### 1. Why Registry Methods Return Full Metadata
`registry.get_nodes_metadata()` returns the entire metadata dict, not just what you asked for. This is intentional - consumers need different fields at different times.

### 2. The Module Path vs File Path Duality
Nodes store both:
- `module`: "pflow.nodes.file.read_file" (for importing)
- `file_path`: "/absolute/path/to/read_file.py" (for scanning)

Both are needed. Don't remove either.

### 3. Test Nodes Are Real Nodes
The registry includes test nodes (test_node.py, test_node_retry.py). This is intentional - they're used in integration tests. Your changes must not break them.

## Dependencies on Previous Tasks

### Task 9 (Node Metadata Schema)
Established the Interface docstring format. You're now parsing these at scan time instead of runtime.

### Task 14 (Enhanced Interface Format)
Created the structure syntax for nested data. This is what enables path validation.

### Task 16 (Planning Context Builder)
Currently does runtime parsing. After your changes, it should just read pre-parsed data.

## Subtle Bugs to Avoid

### 1. The None vs Missing Distinction
In template resolution, I learned:
- `shared["key"] = None` means key exists with null value
- Missing key throws KeyError

Your validation must preserve this semantic difference.

### 2. Registry Atomicity
The registry file is written by `pflow registry update` and read by running workflows. There's NO locking. Consider:
- What happens if update runs while workflow executes?
- Should you write to temp file and atomic rename?

### 3. Error Message Quality
Current validator says: "Missing required parameter: --name"
This assumes CLI parameter. With Node IR, you'll know the truth. Update messages:
- "Missing parameter: --name (required by CLI)"
- "Missing variable: $data (should be written by node 'processor')"

## Files You'll Touch But Docs Don't Mention

1. **tests/test_registry/test_metadata_extractor.py**
   - Has extensive tests for parser edge cases
   - Shows all supported docstring formats
   - Update these FIRST to understand parser behavior

2. **tests/test_planning/test_context_builder_phases.py**
   - Tests the current runtime parsing
   - Must still pass after your changes
   - Good for verifying output compatibility

3. **src/pflow/cli/commands/registry.py**
   - The `update` command that triggers scanning
   - Consider adding `--strict` (default) vs `--skip-errors` modes
   - Make error output actionable with file:line references

## What Would Make Me Furious If Not Mentioned

1. **The registry is loaded SYNCHRONOUSLY on every command**. Even `pflow --version`. Your 10-second scan time happens ONCE, but 1MB registry loads EVERY TIME.

2. **Nodes can have multiple classes per file**. Scanner finds ALL classes inheriting from BaseNode, not just the "main" one.

3. **The `name` field is NOT the class name**. It comes from either:
   - `metadata` class attribute
   - Docstring first line
   - Fallback to slugified class name
   Don't assume node type matches class name.

4. **Some interfaces use tabs, some spaces**. The regex in metadata_extractor is whitespace-sensitive. Test with both.

5. **The compiler already passes registry to validate**. Line 511 in compiler.py has the registry available. But current validator ignores it due to the signature.

## Your Simplest Path Forward

1. Start with metadata_extractor tests - understand ALL format variations
2. Implement the two-format handler (simple vs rich) FIRST
3. Add scanner changes with aggressive error handling
4. Update validator with full path traversal
5. THEN remove the old code

## Final Warning

The template system works because it's transparent to nodes. Your Node IR must be equally transparent. If nodes need modification to work with your changes, you've failed.

The beauty of moving parsing to scan-time is it's a pure optimization. The system behavior shouldn't change at all - it should just be faster and more accurate.

Good luck. The design is solid, but the details will try to kill you.

## Addendum: Code Snippets That Will Save Your Life

### 1. The Correct Way to Handle Both Output Formats

```python
# This is what I had to add to fix the validator:
for output in interface["outputs"]:
    if isinstance(output, str):
        # Simple format: ["result", "status"]
        node_outputs[output] = {"type": "any"}
    else:
        # Rich format: [{"key": "result", "type": "str"}]
        key = output["key"]
        node_outputs[key] = {
            "type": output.get("type", "any"),
            "structure": output.get("structure", {})
        }
```

### 2. The PocketFlow Copy Behavior You Must Understand

From `pocketflow/__init__.py` (line 99):
```python
curr = copy.copy(self.start_node)  # Shallow copy!
```

This is why the wrapper pattern works - PocketFlow makes a copy before calling `_run()`. Your Node IR changes must not break this assumption.

### 3. The Registry Loading Pattern

From `registry.py`:
```python
def load(self) -> dict[str, Any]:
    """Load registry from JSON file."""
    if self.registry_file.exists():
        with open(self.registry_file) as f:
            return json.load(f)
    return {}
```

No caching. No lazy loading. Every. Single. Time.

### 4. How Context Builder Currently Formats Output

From `context_builder.py` (lines 89-97):
```python
processed_nodes[node_type] = {
    "description": metadata.get("description", "No description available"),
    "inputs": metadata.get("inputs", []),
    "outputs": metadata.get("outputs", []),
    "params": metadata.get("params", []),
    "actions": metadata.get("actions", ["default"]),
    "registry_info": registry_info,
}
```

Your Node IR must produce EXACTLY this structure or you'll break the planner.

## The Bugs I Hit That You'll Hit Too

### 1. Circular Import When Testing
When you write tests for the new scanner with MetadataExtractor:
```python
# This will circular import in tests:
from pflow.registry.scanner import extract_metadata
from pflow.registry.metadata_extractor import MetadataExtractor
```

Solution: Mock the extractor in tests, don't import both.

### 2. JSON Serialization of Path Objects
The scanner uses `Path` objects. When storing in registry:
```python
"file_path": str(file_path.absolute())  # Must convert!
```

I forgot this. Registry write failed with "Path object is not JSON serializable".

### 3. The Docstring None Problem
```python
inspect.getdoc(cls)  # Returns None if no docstring
```

But MetadataExtractor expects string. Must use:
```python
inspect.getdoc(cls) or ""
```

## Performance Numbers That Matter

From my testing with template system:
- Loading 1MB JSON file: ~50ms
- Parsing 50 nodes with MetadataExtractor: ~10s
- Each workflow compilation: loads registry once

So with your Node IR:
- One-time cost: 10s scan (acceptable)
- Per-workflow cost: +50ms for larger registry (concerning)

Consider: Binary format? Lazy loading? Separate metadata cache?

## The Integration Points Nobody Talks About

### 1. Shell Completion (Future)
The registry powers shell completion. Larger registry = slower tab completion.

### 2. Error Messages
Currently, error messages reference node types. With full metadata, you could show:
- What the node expects
- What it outputs
- Why template validation failed

Don't miss this opportunity.

### 3. The Planner's LLM Context
The planner sends ALL node metadata to the LLM. 1MB registry = expensive API calls.

You might need to add metadata filtering for the planner.

## Tests That Saved My Life

During template implementation, these tests caught subtle bugs:

```bash
# This one test caught 3 integration bugs:
uv run python -m pytest tests/test_runtime/test_flow_construction.py::TestInstantiateNodes::test_instantiate_with_params -xvs

# This revealed the output format issue:
uv run python -m pytest tests/test_registry/test_metadata_extractor.py::TestPflowMetadataExtractor::test_extract_interface_components -xvs

# This found the circular import:
uv run python -m pytest tests/test_runtime/test_compiler_basic.py -xvs
```

**Pro tip**: When tests fail mysteriously, add print statements in the actual source files, not just tests. The test output will show them.

## If You Only Remember Three Things

1. **Handle both output formats or die** - Simple strings AND rich dicts
2. **The registry loads on EVERY command** - Size matters more than you think
3. **Preserve exact output format** - The planner is fragile

The rest you can figure out, but these three will end you if you forget.

## Quick Reference: File Locations

**Core files to modify**:
- `src/pflow/registry/scanner.py` - Add interface parsing
- `src/pflow/planning/context_builder.py` - Remove dynamic imports
- `src/pflow/runtime/template_validator.py` - Add full path validation
- `src/pflow/runtime/compiler.py` - Pass registry to validator

**Test files that will break**:
- `tests/test_registry/*` - Registry format changes
- `tests/test_planning/test_context_builder_*.py` - Expects runtime parsing
- `tests/test_runtime/test_template_validator.py` - Signature change

**Reference files (don't modify)**:
- `src/pflow/registry/metadata_extractor.py` - Understand output formats
- `src/pflow/runtime/node_wrapper.py` - See wrapper pattern
- `tests/test_registry/test_metadata_extractor.py` - All format examples
