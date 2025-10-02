# Task 71 Technical Implementation Reference

## Purpose

This document consolidates all technical research findings for implementing CLI commands that enable AI agents to discover and build pflow workflows. It provides the essential implementation details needed to reuse planner nodes and enhance error output.

---

## 1. Direct Node Reuse Pattern

### How PocketFlow Nodes Work Standalone

From `pocketflow/__init__.py:32-40`:
```python
def run(self, shared):
    if self.successors:
        warnings.warn("Node won't run successors. Use Flow.")
    return self._run(shared)  # Executes prep → exec → post
```

**Key Facts**:
- ✅ Nodes can run WITHOUT a Flow
- ✅ Just call `node.run(shared)` with a dict
- ✅ Full lifecycle (prep → exec → post) handled automatically
- ✅ Proven by 350+ test cases

### Basic Pattern

```python
# 1. Create node instance
node = SomeNode()

# 2. Optional: Configure parameters
node.set_params({"model": "gpt-4"})

# 3. Create shared store with required data
shared = {"user_input": "query"}

# 4. Run node
action = node.run(shared)

# 5. Access results from shared store
result = shared['some_result_key']
```

---

## 2. WorkflowDiscoveryNode for CLI Reuse

### What It Does
Performs semantic workflow matching using LLM to find existing workflows that match user intent.

### Required Setup

```python
from pflow.planning.nodes import WorkflowDiscoveryNode
from pflow.core.workflow_manager import WorkflowManager

# Create node
node = WorkflowDiscoveryNode()

# Create shared store
shared = {
    "user_input": "analyze GitHub pull requests",  # REQUIRED
    "workflow_manager": WorkflowManager(),         # RECOMMENDED
}

# Run discovery
action = node.run(shared)

# Access results
if action == "found_existing":
    discovery_result = shared['discovery_result']
    # Contains: found, workflow_name, confidence, reasoning
    found_workflow = shared['found_workflow']
    # Contains: Full workflow IR if match found
else:
    # action == "not_found"
    pass
```

### Returns
- Action: `"found_existing"` or `"not_found"`
- Writes to shared:
  - `discovery_result` (dict): LLM decision details
  - `found_workflow` (dict): Full workflow IR (only if found)

### Dependencies
- ✅ NONE from other planner nodes (entry point)
- ✅ Creates its own context internally

---

## 3. ComponentBrowsingNode for CLI Reuse

### What It Does
Uses LLM to filter 50+ nodes down to 3-5 relevant ones based on user intent, then builds complete interface context for those nodes.

### Required Setup

```python
from pflow.planning.nodes import ComponentBrowsingNode

# Create node
node = ComponentBrowsingNode()

# Create shared store
shared = {
    "user_input": "fetch GitHub issues and analyze them",  # REQUIRED
    # Optional: "workflow_manager": WorkflowManager(),
    # Optional: "requirements_result": {...},
}

# Run component browsing
action = node.run(shared)

# Access results
browsed_components = shared['browsed_components']
# Contains: node_ids, workflow_names (currently cleared until Task 59)

planning_context = shared['planning_context']
# Contains: Full interface details for selected nodes (markdown)

registry_metadata = shared['registry_metadata']
# Contains: Complete registry data
```

### Returns
- Action: Always `"generate"`
- Writes to shared:
  - `browsed_components` (dict): Selected node IDs and workflow names
  - `planning_context` (str): Complete node specifications in markdown
  - `registry_metadata` (dict): Full registry data

### Dependencies
- ✅ Can run WITHOUT `requirements_result` (uses empty dict)
- ✅ Creates its own Registry instance
- ✅ Self-contained

---

## 4. Context Builder Functions

These functions are used internally by the planner and can be reused directly for CLI output:

### build_nodes_context(node_ids, registry_metadata)
**Location**: `src/pflow/planning/context_builder.py`

**Returns**: Numbered list of nodes with descriptions, grouped by category

**Format**:
```markdown
# File Operations
1. read-file - Read contents of a file
2. write-file - Write content to a file
```

**Use Case**: Lightweight browsing lists for discovery commands

### build_planning_context(selected_node_ids, selected_workflow_names, registry_metadata)
**Location**: `src/pflow/planning/context_builder.py`

**Returns**: Full interface details for selected nodes (markdown)

**Format**:
```markdown
### read-file
**Description**: Read contents of a file
**Inputs**:
  - file_path: str (required) - Path to the file
**Outputs**:
  - content: str - File contents
**Example**:
  Input: {"file_path": "data.txt"}
  Output: {"content": "file contents"}
```

**Use Case**: Detailed node specifications for `registry describe` command

### build_workflows_context(workflow_names, workflow_manager)
**Location**: `src/pflow/planning/context_builder.py`

**Returns**: Rich workflow metadata with flow visualization

**Format**:
```markdown
**1. `pr-analyzer`** - Analyzes GitHub pull requests
   **Flow:** `github-get-pr → llm → write-file`
   **Can:** analyze code changes, identify issues
   **For:** code review automation
```

**Use Case**: Workflow discovery output

---

## 5. Error Context Enhancement

### Current Problem

When workflows fail, the CLI shows minimal error information:

**Text Mode**:
```
cli: Workflow execution failed - Node returned error action
cli: Check node output above for details
```

**JSON Mode**:
```json
{
  "error": "Workflow execution failed",
  "is_error": true,
  "execution_time_seconds": 1.23
}
```

### Rich Error Data Available (But Not Shown)

The `ExecutionResult.errors` contains structured error information:

```python
{
    "source": "runtime",              # Where error originated
    "category": "template_error",     # Error classification
    "message": "Field 'title' is required",
    "node_id": "create-issue",        # Which node failed
    "node_type": "mcp-github-create_issue",
    "fixable": True,                  # Whether repairable

    # Context fields (category-dependent):
    "attempted": ["${fetch.result.title}"],  # What was tried
    "available": ["${fetch.result.issues}", "${fetch.result.count}"],  # Available options
    "hint": "Check available fields",
    "sample": "..."                   # Sample data
}
```

### Checkpoint Information Also Available

Located in `result.shared_after["__execution__"]`:

```python
{
    "completed_nodes": ["fetch", "analyze"],  # What succeeded
    "node_actions": {
        "fetch": "default",
        "analyze": "default"
    },
    "failed_node": "send"  # Where failure occurred
}
```

### What Needs to Be Displayed

For each error in `result.errors`:
- Node ID where failure occurred
- Error category and message
- Attempted operations (for template/extraction errors)
- Available fields/options
- Whether error is fixable
- Checkpoint progress (completed nodes)

### Implementation Location

**File**: `src/pflow/cli/main.py`

**Function**: `_handle_workflow_error()` (around line 1034)

**Enhancement**:
```python
if result.errors:
    for error in result.errors:
        click.echo(f"✗ Workflow failed at node: {error.get('node_id')}", err=True)
        click.echo(f"  Category: {error.get('category')}", err=True)
        click.echo(f"  Message: {error.get('message')}", err=True)

        if error.get('attempted'):
            click.echo(f"  Attempted: {', '.join(error['attempted'])}", err=True)

        if error.get('available'):
            click.echo(f"  Available: {', '.join(error['available'])}", err=True)

        if error.get('fixable'):
            click.echo(f"  Fixable: Yes (enable repair without --no-repair)", err=True)
```

---

## 6. WorkflowManager.save() for CLI Reuse

### What It Does

Saves a workflow to the global library at `~/.pflow/workflows/` with built-in validation and atomic file operations.

### Method Signature

**Location**: `src/pflow/core/workflow_manager.py:119-172`

```python
def save(
    self,
    name: str,
    workflow_ir: dict[str, Any],
    description: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> str  # Returns absolute file path
```

### Built-in Features

**Name Validation** (automatic):
- Cannot be empty
- Max 50 characters
- No path separators (`/` or `\`)
- Only alphanumeric, dots, hyphens, underscores: `^[a-zA-Z0-9._-]+$`

**Atomicity**:
- Uses `tempfile.mkstemp()` + `os.link()` for atomic saves
- Fails if workflow already exists (prevents accidental overwrites)
- Automatic cleanup on failure

**Error Handling**:
- Raises `WorkflowValidationError` for invalid names
- Raises `WorkflowExistsError` if workflow already exists
- Raises `WorkflowValidationError` for other save failures

### Usage Pattern for CLI Command

```python
from pflow.core.workflow_manager import WorkflowManager
from pflow.core.ir_schema import validate_ir
from pflow.core.exceptions import WorkflowValidationError, WorkflowExistsError

# 1. Load workflow from file
with open(file_path, 'r') as f:
    data = json.load(f)
workflow_ir = data.get("ir", data)  # Handle wrapped or unwrapped IR

# 2. Validate IR before saving (WorkflowManager doesn't validate IR)
try:
    validated_ir = validate_ir(workflow_ir)
except ValidationError as e:
    click.echo(f"Error: Invalid workflow - {e}", err=True)
    raise click.Abort()

# 3. Save with WorkflowManager
wm = WorkflowManager()
try:
    file_path = wm.save(
        name=workflow_name,
        workflow_ir=validated_ir,
        description=description,  # Optional
        metadata=metadata         # Optional rich metadata
    )
    click.echo(f"✓ Saved workflow '{workflow_name}'")
    click.echo(f"  Location: {file_path}")
except WorkflowExistsError:
    click.echo(f"Error: Workflow '{workflow_name}' already exists", err=True)
    # Option: prompt for --force flag or different name
    raise click.Abort()
except WorkflowValidationError as e:
    click.echo(f"Error: {e}", err=True)
    raise click.Abort()
```

### Important Notes

**WorkflowManager does NOT validate IR**:
- You must call `validate_ir()` before `save()`
- IR validation is intentionally separated (different concern)
- Structural validation via `validate_ir_structure()` also available

**Metadata Structure** (optional):
```python
metadata = {
    "rich_metadata": {
        "search_keywords": ["tag1", "tag2"],
        "capabilities": ["capability1", "capability2"],
        "typical_use_cases": ["use case description"]
    }
}
```

**Service is Already Ready**:
- ✅ No Click dependencies
- ✅ Production-ready atomic operations
- ✅ Well-tested with comprehensive coverage
- ✅ Can be used directly from CLI commands

---

## 7. Service Layer Architecture (Already MCP-Ready)

### Key Finding from Task 68

pflow already has a **clean service layer** extracted in Task 68, which means:

**Services are decoupled from CLI**:
- ✅ `WorkflowManager` - Zero Click dependencies
- ✅ `Registry` - Pure data operations
- ✅ `WorkflowExecutorService` - Isolated execution
- ✅ `execute_workflow()` - Direct function call

**All services return structured data**:
- Dicts, lists, dataclasses (JSON-serializable)
- No Click/terminal formatting in service layer
- 99 `click.echo()` calls in CLI, 0 in services

**This means for Task 71**:
- Can directly import and use services
- No extraction or refactoring needed
- Just add Click wrappers for new commands
- Same services work for future MCP server (Task 72)

### Evidence: CLI Uses Service Layer

**Pattern used throughout existing commands**:
```python
# CLI command (thin wrapper)
@click.command()
def some_command():
    # 1. Call service
    wm = WorkflowManager()
    data = wm.some_method()

    # 2. Format for display
    click.echo(format_data(data))
```

**For Task 71 commands**: Follow same pattern
- WorkflowDiscoveryNode/ComponentBrowsingNode = Services
- Just add Click decorators and output formatting
- Keep all logic in the nodes/services

---

## 8. Validation Using ValidatorNode

### What ValidatorNode Does

Performs 4-layer validation:
1. **Schema Validation**: IR structure via Pydantic
2. **Template Validation**: All variables have sources
3. **Compilation Check**: Can build Flow object
4. **Runtime Validation**: Ready for execution (optional)

### Using ValidatorNode from CLI

```python
from pflow.planning.nodes import ValidatorNode

# Create node
node = ValidatorNode()

# Setup shared store
shared = {
    "generated_workflow": workflow_ir,  # The workflow to validate
    "workflow_inputs": params,          # Parameter values for template checking
}

# Run validation
action = node.run(shared)

# Access results
validation_result = shared.get("validation_result", {})

if validation_result.get("valid", False):
    # Validation passed
    print("✓ All validation checks passed")
else:
    # Validation failed
    errors = validation_result.get("errors", [])
    for error in errors:
        print(f"✗ {error}")
```

### Returns
- Action: `"metadata_generation"` (valid) or `"retry"` or `"failed"` (invalid)
- Writes to shared:
  - `validation_result` (dict): Contains `valid` (bool) and `errors` (list[str])
  - `validation_errors` (list[str]): Top 3 errors

**Note**: ValidatorNode returns only top 3 errors to avoid overwhelming retry loops. For CLI validation, we may want all errors.

---

## 9. Key Planner Nodes (Reference)

### The 11-Node Planner Pipeline

**Path A (Reuse)**:
```
START → WorkflowDiscoveryNode → ParameterMappingNode → Result
```

**Path B (Generate)**:
```
START → WorkflowDiscoveryNode
     ↓ (not_found)
     ParameterDiscoveryNode
     ↓
     RequirementsAnalysisNode
     ↓
     ComponentBrowsingNode
     ↓
     PlanningNode
     ↓
     WorkflowGeneratorNode
     ↓
     ParameterMappingNode
     ↓
     ValidatorNode
     ↓
     MetadataGenerationNode
     ↓
     ParameterPreparationNode
     ↓
     Result
```

### Nodes Relevant for Task 71

1. **WorkflowDiscoveryNode** - Semantic workflow matching
2. **ComponentBrowsingNode** - Intelligent node selection
3. **ValidatorNode** - Multi-layer validation
4. **MetadataGenerationNode** - Rich metadata generation (optional for save command)

---

## 10. What Agents Currently Cannot Access

### Missing CLI Capabilities

| Capability | Planner Has | CLI Has | Impact |
|-----------|-------------|---------|---------|
| Intelligent node discovery | ComponentBrowsingNode | `registry search` (keyword only) | Agents can't ask "what nodes for X?" |
| Intelligent workflow discovery | WorkflowDiscoveryNode | `workflow list` (no filtering) | Agents can't find relevant workflows |
| Pre-flight validation | ValidatorNode | Nothing (validation during execution only) | Agents can't validate before running |
| Bulk node details | build_planning_context() | `registry describe` (one at a time) | Must make multiple requests |
| Rich metadata generation | MetadataGenerationNode | Nothing | Can't generate discoverable metadata |

### Why This Matters

**Without these capabilities, agents must**:
- Browse entire node catalog manually (no intelligent filtering)
- Execute workflows to discover validation errors (no pre-flight check)
- Guess at node capabilities (no semantic search)
- Save workflows without rich metadata (poor discoverability)

**With Task 71 commands, agents can**:
- Discover relevant nodes/workflows semantically
- Validate workflows before execution
- Get complete interface details
- Save with auto-generated metadata

---

## 11. Implementation Checklist

### Commands to Implement

1. **`pflow workflow discover QUERY`**
   - Reuses: WorkflowDiscoveryNode directly
   - Returns: Matching workflows with metadata
   - Complexity: Medium (LLM integration exists)

2. **`pflow registry discover QUERY`**
   - Reuses: ComponentBrowsingNode directly
   - Returns: Relevant nodes with full interfaces
   - Complexity: Medium (LLM integration exists)

3. **`pflow registry describe NODE_ID [NODE_ID...]`**
   - Reuses: build_planning_context() directly
   - Returns: Complete node specifications
   - Complexity: Low (no LLM needed)

4. **`pflow --validate-only WORKFLOW [PARAMS...]`**
   - Reuses: ValidatorNode logic
   - Returns: Validation errors without execution
   - Complexity: Medium (needs CLI flag integration)

5. **`pflow workflow save FILE NAME DESC [--generate-metadata]`**
   - Reuses: WorkflowManager.save() + MetadataGenerationNode (optional)
   - Returns: Confirmation with saved location
   - Complexity: Low-Medium

### Enhancement to Implement

6. **Enhanced Error Output**
   - Location: `src/pflow/cli/main.py` → `_handle_workflow_error()`
   - Display: ExecutionResult.errors details
   - Complexity: Low (just formatting)

---

## 12. Key Implementation Patterns

### Pattern 1: Direct Node Invocation
```python
node = PlannerNode()
shared = {"user_input": query, ...required_data}
action = node.run(shared)
result = shared['result_key']
```

### Pattern 2: Context Building
```python
from pflow.planning.context_builder import build_planning_context
from pflow.registry.registry import Registry

registry = Registry()
metadata = registry.load()

context = build_planning_context(
    selected_node_ids=["read-file", "llm"],
    selected_workflow_names=[],
    registry_metadata=metadata
)

click.echo(context)  # Already formatted markdown
```

### Pattern 3: Error Display Enhancement
```python
if not result.success and result.errors:
    for error in result.errors:
        click.echo(f"✗ Node: {error.get('node_id')}", err=True)
        click.echo(f"  {error.get('message')}", err=True)
        # Show additional context fields...
```

---

## 13. Critical Technical Details

### LLM Model Configuration

Planner nodes expect model configuration via params:
```python
node.set_params({
    "model": "anthropic/claude-sonnet-4-0",
    "temperature": 0.0
})
```

### Shared Store Conventions

- System keys use double underscores: `__execution__`, `__warnings__`
- Node results typically under node ID key
- Template variables reference: `${node_id.output_key}`

### Error Categories

From `ExecutionResult.errors`:
- `template_error` - Unresolved template variables
- `api_validation` - API input validation failures
- `execution_failure` - Node execution errors
- `non_repairable` - Cannot be fixed by repair system

### File Path Detection (Existing)

From `src/pflow/cli/main.py`:
- Contains `/` OR ends with `.json` → File path
- Otherwise → Saved workflow name

---

## 14. Testing Considerations

### Node Execution Tests
- Test standalone node execution without Flow
- Verify shared store setup and result extraction
- Handle LLM failures gracefully

### CLI Integration Tests
- Verify correct syntax (flags before arguments)
- Test parameter parsing (key=value format)
- Validate error display shows rich context

### End-to-End Agent Workflow
- Discover → Create → Validate → Execute → Save
- Verify all information flows correctly
- Test error recovery with enhanced output

---

## Summary

This document provides all technical details needed to implement Task 71:

1. **Direct node reuse** is proven and recommended
2. **WorkflowDiscoveryNode** and **ComponentBrowsingNode** can be used directly with minimal setup
3. **Context builders** provide ready-made formatted output
4. **Error context** exists but needs CLI display enhancement
5. **ValidatorNode** enables pre-flight validation
6. **All infrastructure exists** - just needs CLI wrappers

The implementation is primarily about exposing existing capabilities through CLI commands, not building new functionality.
