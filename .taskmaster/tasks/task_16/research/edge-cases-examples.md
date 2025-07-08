# Task 16: Edge Cases and Real-World Examples

## Real Metadata Variations You'll Encounter

### Case 1: Perfect Metadata (from file nodes)
```python
# Input from Task 7
{
    'description': 'Read content from a file and add line numbers',
    'inputs': ['file_path', 'encoding'],
    'outputs': ['content', 'error'],
    'params': ['file_path', 'encoding'],
    'actions': ['default', 'error']
}

# Your output
"""
**read-file**: Read content from a file and add line numbers
- Reads: shared["file_path"], shared["encoding"]
- Writes: shared["content"], shared["error"]
- Actions: default, error
"""
```

### Case 2: Minimal Metadata (test nodes)
```python
# Input from Task 7
{
    'description': 'Test node',
    'inputs': [],
    'outputs': [],
    'params': [],
    'actions': []
}

# Your output
"""
**test-node**: Test node
- Reads: none
- Writes: none
"""
```

### Case 3: No Metadata (missing docstring)
```python
# Input from Task 7
{
    'description': 'No description',
    'inputs': [],
    'outputs': [],
    'params': [],
    'actions': []
}

# Your output
"""
**mystery-node**: No description (metadata incomplete)
"""
```

### Case 4: Complex Node (claude-code)
```python
# Input from Task 7
{
    'description': 'Comprehensive Claude Code node for AI-assisted development',
    'inputs': ['prompt', 'context', 'project_path'],
    'outputs': ['code_report', 'modified_files', 'error'],
    'params': ['model', 'temperature', 'max_tokens'],
    'actions': ['default', 'error', 'timeout']
}

# Your output
"""
**claude-code**: Comprehensive Claude Code node for AI-assisted development
- Reads: shared["prompt"], shared["context"], shared["project_path"]
- Writes: shared["code_report"], shared["modified_files"], shared["error"]
- Actions: default, error, timeout
"""
```

## Handling Special Cases

### Case 5: Duplicate Node Names
```python
# If registry has both:
nodes = {
    'llm': {'description': 'General LLM node'},
    'llm-v2': {'description': 'Updated LLM node'}
}

# Your output should include both:
"""
**llm**: General LLM node
- Reads: shared["prompt"]
- Writes: shared["response"]

**llm-v2**: Updated LLM node
- Reads: shared["prompt"]
- Writes: shared["response"]
"""
```

### Case 6: Required vs Optional Indicators
```python
# Some metadata might indicate required/optional
{
    'description': 'Node with requirements',
    'inputs': ['required_input', 'optional_input'],
    # Note: Task 7 strips this info, but if it didn't...
}

# Keep output simple (planner will figure it out):
"""
**requirement-node**: Node with requirements
- Reads: shared["required_input"], shared["optional_input"]
- Writes: shared["output"]
"""
```

## Category Edge Cases

### Case 7: Ambiguous Categories
```python
# Node name doesn't clearly fit a category
'process-data': {'description': 'Generic data processor'}

# Put in 'Other' or 'Data Processing':
"""
## Other Operations

**process-data**: Generic data processor
- Reads: shared["data"]
- Writes: shared["processed_data"]
"""
```

### Case 8: Multi-Category Nodes
```python
# Node could fit multiple categories
'github-git-sync': {'description': 'Sync GitHub with Git'}

# Pick primary category (GitHub in this case):
"""
## GitHub Operations

**github-git-sync**: Sync GitHub with Git
- Reads: shared["repo"], shared["branch"]
- Writes: shared["sync_status"]
"""
```

## Token Limit Handling

### Case 9: Too Many Nodes
```python
# If you have 100+ nodes and hit token limits

# Option 1: Truncate descriptions
"""
**read-file**: Read content from a file...
"""
# Becomes:
"""
**read-file**: Read file
"""

# Option 2: Skip less common nodes
if total_tokens > 1800:
    # Skip 'Other' category
    skip_categories = ['Other', 'Experimental']
```

### Case 10: Very Long Descriptions
```python
{
    'description': 'This node does X and Y and Z and also handles A, B, C with special considerations for D, E, F...' # 200+ chars
}

# Truncate intelligently:
"""
**complex-node**: This node does X and Y and Z and also handles...
- Reads: shared["input"]
- Writes: shared["output"]
"""
```

## Format Edge Cases

### Case 11: Special Characters in Descriptions
```python
{
    'description': 'Read "special" <file> & process'
}

# Escape or clean:
"""
**special-reader**: Read "special" file & process
- Reads: shared["file_path"]
- Writes: shared["content"]
"""
```

### Case 12: Empty Categories
```python
# After organizing, some categories might be empty
categories = {
    'File Operations': {...},  # has nodes
    'Database Operations': {}, # empty
    'GitHub Operations': {...} # has nodes
}

# Skip empty categories in output:
"""
## File Operations
...

## GitHub Operations
...
"""
# (Database Operations not shown)
```

## Integration Edge Cases

### Case 13: Registry Returns None
```python
# Registry might return None for missing nodes
registry_data = {
    'read-file': {...},
    'missing-node': None,
    'write-file': {...}
}

# Skip None entries:
for node_name, metadata in registry_data.items():
    if metadata is None:
        continue
    # format normally
```

### Case 14: Malformed Metadata Structure
```python
# Metadata might have unexpected structure
{
    'description': 'Normal',
    'interface': {  # Nested instead of flat
        'inputs': ['file_path'],
        'outputs': ['content']
    }
}

# Handle gracefully:
inputs = metadata.get('inputs', [])
if not inputs and 'interface' in metadata:
    inputs = metadata['interface'].get('inputs', [])
```

## Testing Edge Cases

### Test: Empty Registry
```python
def test_empty_registry():
    builder = PlannerContextBuilder({})
    context = builder.build_context()
    assert context == "# Available pflow Nodes\n"
```

### Test: Single Node
```python
def test_single_node():
    builder = PlannerContextBuilder({
        'only-node': {
            'description': 'The only node',
            'inputs': ['input'],
            'outputs': ['output'],
            'params': [],
            'actions': ['default']
        }
    })
    context = builder.build_context()
    assert '**only-node**' in context
    assert 'shared["input"]' in context
```

### Test: Malformed Metadata
```python
def test_malformed_metadata():
    builder = PlannerContextBuilder({
        'bad-node': {
            # Missing everything except description
            'description': 'Bad node'
        }
    })
    context = builder.build_context()
    # Should still include the node
    assert '**bad-node**' in context
    assert 'Bad node' in context
```

## Real-World Example: Mixed Registry

```python
# What you'll actually get from a real registry:
real_registry = {
    'read-file': {
        'description': 'Read content from a file',
        'inputs': ['file_path', 'encoding'],
        'outputs': ['content', 'error'],
        'params': ['file_path', 'encoding'],
        'actions': ['default', 'error']
    },
    'test-node': {
        'description': 'No description',
        'inputs': [],
        'outputs': [],
        'params': [],
        'actions': []
    },
    'github-get-issue': {
        'description': 'Get GitHub issue',
        'inputs': ['issue_number', 'repo'],
        'outputs': ['issue'],
        'params': ['token'],
        'actions': ['default', 'not_found']
    },
    'llm': {
        'description': 'General-purpose LLM processing',
        'inputs': ['prompt'],
        'outputs': ['response'],
        'params': ['model', 'temperature'],
        'actions': ['default', 'error']
    },
    'broken-node': None,  # Registry couldn't load this
    'write-file': {
        'description': 'Write content to a file',
        'inputs': ['content', 'file_path'],
        'outputs': ['written', 'error'],
        'params': ['content', 'file_path', 'append'],
        'actions': ['default', 'error']
    }
}

# Expected output:
"""
# Available pflow Nodes

## File Operations

**read-file**: Read content from a file
- Reads: shared["file_path"], shared["encoding"]
- Writes: shared["content"], shared["error"]
- Actions: default, error

**write-file**: Write content to a file
- Reads: shared["content"], shared["file_path"]
- Writes: shared["written"], shared["error"]
- Actions: default, error

## GitHub Operations

**github-get-issue**: Get GitHub issue
- Reads: shared["issue_number"], shared["repo"]
- Writes: shared["issue"]
- Actions: default, not_found

## AI Processing

**llm**: General-purpose LLM processing
- Reads: shared["prompt"]
- Writes: shared["response"]
- Actions: default, error

## Other

**test-node**: No description (metadata incomplete)
"""
```

## Remember

1. **Be defensive** - Assume metadata can be missing, None, or malformed
2. **Be inclusive** - Include nodes even with poor metadata
3. **Be consistent** - Same format for all nodes
4. **Be practical** - Focus on what helps the planner
5. **Test with real data** - Use actual registry output, not idealized examples

The planner is forgiving - it's better to include imperfect information than to exclude nodes entirely.
