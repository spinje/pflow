# State Management Patterns for pflow

## Overview

This document extracts state management patterns from Wave 1 repository analyses, focusing on patterns that support pflow's CLI-first workflow compiler architecture. Each pattern demonstrates how the shared store enables deterministic workflow execution while maintaining simplicity.

## Pattern 1: Natural Key Naming Convention

- **Found in**: All repositories
- **Purpose**: Prevents key collisions without explicit namespacing
- **Key Design**: Use intuitive, self-documenting key names that reflect data purpose
- **Implementation**: Keys describe what data represents, not where it came from
- **Code Example**:
```python
# Good - Natural, descriptive keys
shared["transcript"] = youtube_content
shared["summary"] = llm_response
shared["issue_title"] = github_data["title"]

# Bad - Generic keys that collide
shared["data"] = content
shared["result"] = response
shared["output"] = data
```
- **Task Mapping**: Critical for Task 9 (Shared Store & Proxy) - natural naming eliminates most collision scenarios

## Pattern 2: Progressive State Building

- **Found in**: Website Chatbot, YouTube Made Simple, AI Paul Graham
- **Purpose**: Each node adds to shared state without destroying previous data
- **Key Design**: Nodes append new keys rather than overwriting existing ones
- **Implementation**: Build up context through the workflow, enabling debugging and tracing
- **Code Example**:
```python
# Initial state
shared = {"url": "https://github.com/repo"}

# After fetch node
shared["files"] = ["README.md", "main.py"]

# After analysis node
shared["abstractions"] = ["Node", "Flow", "SharedStore"]

# After generation node
shared["tutorial"] = "Complete tutorial content..."

# All previous state remains accessible
```
- **Task Mapping**: Supports Task 23 (Execution Tracing) - full state history available

## Pattern 3: Structured Input Sections

- **Found in**: Cold Email Personalization, Codebase Knowledge
- **Purpose**: Clear separation between configuration, runtime data, and outputs
- **Key Design**: Group related inputs under logical sections
- **Implementation**: Use nested dictionaries for complex configuration
- **Code Example**:
```python
shared = {
    # Configuration section
    "config": {
        "max_retries": 3,
        "temperature": 0.7,
        "output_format": "markdown"
    },

    # Runtime inputs (from CLI/stdin)
    "inputs": {
        "file_path": args.file,
        "prompt": args.prompt,
        "stdin": sys.stdin.read() if not sys.stdin.isatty() else None
    },

    # Working data (populated by nodes)
    "data": {},

    # Final outputs
    "outputs": {}
}
```
- **Task Mapping**: Helps Task 8 (Shell Integration) - clean stdin handling pattern

## Pattern 4: History-Based Audit Trail

- **Found in**: Tutorial-Cursor
- **Purpose**: Track all actions and decisions for debugging and replay
- **Key Design**: Append-only history list with full context
- **Implementation**: Each action records parameters and results
- **Code Example**:
```python
shared["history"] = []

# Node adds action
shared["history"].append({
    "node": "github-get-issue",
    "timestamp": datetime.now().isoformat(),
    "params": {"repo": "owner/repo", "issue": 123},
    "result": None  # Filled after execution
})

# Node updates with result
shared["history"][-1]["result"] = {
    "success": True,
    "data": issue_data
}
```
- **Task Mapping**: Essential for Task 23 (Execution Tracing) - built-in observability

## Pattern 5: Complex State Tracking

- **Found in**: Website Chatbot, Danganronpa Simulator
- **Purpose**: Manage sophisticated application state beyond simple key-value pairs
- **Key Design**: Use sets, lists, and nested structures for complex relationships
- **Implementation**: Leverage Python's data structures within shared store
- **Code Example**:
```python
shared = {
    # URL crawling state
    "visited_urls": set(),
    "pending_urls": ["https://example.com"],
    "url_content": {},  # url -> content mapping
    "url_graph": {},    # url -> linked urls

    # Iteration tracking
    "current_iteration": 0,
    "max_iterations": 5,

    # Conversation history
    "messages": [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"}
    ]
}
```
- **Task Mapping**: Shows advanced patterns for Task 9 (Proxy) - complex state without collisions

## Pattern 6: Template Variable Resolution

- **Found in**: Cold Email Personalization, AI Paul Graham
- **Purpose**: Enable dynamic content injection in prompts and outputs
- **Key Design**: Use consistent variable naming for template substitution
- **Implementation**: Template strings reference shared store keys
- **Code Example**:
```python
# Planner generates workflow with templates
prompt_template = """
Analyze the issue: $issue_content
Repository context: $repo_context
Previous fixes: $similar_issues
"""

# At execution, resolve from shared store
prompt = prompt_template.replace("$issue_content", shared["issue"]["body"])
prompt = prompt.replace("$repo_context", shared["repo_summary"])
prompt = prompt.replace("$similar_issues", shared["related_issues"])
```
- **Task Mapping**: Critical for Task 19 (Template Resolver) - natural variable mapping

## Pattern 7: File-Based State Persistence

- **Found in**: AI Paul Graham, Codebase Knowledge
- **Purpose**: Simple persistence for CLI workflows without database complexity
- **Key Design**: Serialize state to JSON/YAML files between runs
- **Implementation**: Load state at startup, save at completion
- **Code Example**:
```python
import json
from pathlib import Path

# Load previous state
state_file = Path(".pflow/state.json")
if state_file.exists():
    with open(state_file) as f:
        shared = json.load(f)
else:
    shared = {"version": "1.0", "workflows": {}}

# Save state after execution
state_file.parent.mkdir(exist_ok=True)
with open(state_file, "w") as f:
    json.dump(shared, f, indent=2)
```
- **Task Mapping**: Supports Task 24 (Caching) - simple file-based persistence

## Pattern 8: Validation Checkpoints

- **Found in**: Danganronpa Simulator, Tutorial-Cursor
- **Purpose**: Fail fast with clear errors when required state is missing
- **Key Design**: Check preconditions early in prep phase
- **Implementation**: Validate required keys before processing
- **Code Example**:
```python
class ProcessNode(Node):
    def prep(self, shared):
        # Validate required inputs
        required_keys = ["input_file", "output_format"]
        missing = [k for k in required_keys if k not in shared]
        if missing:
            raise ValueError(f"Missing required keys: {missing}")

        # Validate data types
        if not isinstance(shared.get("max_retries", 0), int):
            raise TypeError("max_retries must be an integer")

        return shared["input_file"]
```
- **Task Mapping**: Essential for Task 9 (Proxy validation) - early error detection

## Pattern 9: Batch State Management

- **Found in**: YouTube Made Simple, Cold Email Personalization
- **Purpose**: Efficiently handle multiple items while maintaining simple interfaces
- **Key Design**: Convert single items to batches in prep, merge results in post
- **Implementation**: Keep batch complexity hidden from shared store consumers
- **Code Example**:
```python
class BatchProcessNode(BatchNode):
    def prep(self, shared):
        # Convert to batch format
        return [{"id": i, "url": url} for i, url in enumerate(shared["urls"])]

    def exec(self, item):
        # Process single item
        return {"id": item["id"], "content": fetch_content(item["url"])}

    def post(self, shared, prep_res, exec_res_list):
        # Merge results back
        shared["url_contents"] = {
            item["id"]: item["content"]
            for item in exec_res_list
        }
```
- **Task Mapping**: While batch processing is post-MVP, shows pattern for Task 28 (CI nodes)

## Pattern 10: Dynamic Key Generation

- **Found in**: Website Chatbot
- **Purpose**: Create keys based on runtime data for flexible storage
- **Key Design**: Use data-driven key names for dynamic collections
- **Implementation**: Generate keys from node execution results
- **Code Example**:
```python
# Store results with dynamic keys
for file_path in discovered_files:
    key = f"content_{file_path.replace('/', '_')}"
    shared[key] = read_file(file_path)

# Or use nested structure
shared["file_contents"] = {}
for file_path in discovered_files:
    shared["file_contents"][file_path] = read_file(file_path)
```
- **Task Mapping**: Advanced pattern for Task 9 (Proxy) - handles dynamic workflows

## Special Focus: Workflow Control Through Shared Store

For pflow's deterministic execution model, the shared store can control workflow behavior without complex conditionals:

### Pattern: Workflow Configuration
```python
shared = {
    # Workflow control flags
    "skip_tests": False,
    "verbose_output": True,
    "fail_fast": True,

    # Execution limits
    "max_iterations": 3,
    "timeout_seconds": 300,

    # Output control
    "output_format": "json",
    "include_metadata": True
}

# Nodes check these flags
if not shared.get("skip_tests", False):
    run_tests()
```

### Pattern: Error Accumulation
```python
shared["errors"] = []

# Nodes can add errors without failing
try:
    result = process_data()
except ValidationError as e:
    shared["errors"].append({
        "node": "validator",
        "error": str(e),
        "timestamp": datetime.now().isoformat()
    })
    # Continue execution with default
```

### Pattern: Conditional Data Flow
```python
# Without explicit conditionals, use data presence
if "github_token" in shared:
    # Authenticated API calls
    shared["rate_limit"] = 5000
else:
    # Anonymous API calls
    shared["rate_limit"] = 60
```

## Implementation Guidelines for pflow

1. **Start Simple**: Use flat key structures until nesting is needed
2. **Be Explicit**: Clear key names prevent confusion and collisions
3. **Document Keys**: Each node should document its input/output keys
4. **Validate Early**: Check required keys in prep phase
5. **Preserve History**: Don't overwrite data that might be useful later
6. **Use Standards**: Consistent patterns across all nodes
7. **Think CLI**: Keys should map naturally to command-line flags

## Proxy Pattern Considerations

Based on the analyses, the proxy pattern is rarely needed when following natural naming conventions. Consider proxy only when:

1. **Integrating incompatible nodes**: Third-party nodes with fixed interfaces
2. **Key collision is unavoidable**: Multiple nodes must write to same key
3. **Dynamic remapping needed**: Runtime determines key mappings

For MVP, focus on natural naming and defer proxy complexity until real collisions occur.

## Conclusion

These patterns from real-world PocketFlow applications demonstrate that sophisticated state management is achievable through simple, consistent conventions. The shared store's flexibility supports everything from basic file operations to complex multi-stage workflows, all while maintaining the deterministic execution that pflow requires for its "Plan Once, Run Forever" philosophy.
