# Node Reuse Analysis: Planner Nodes for CLI Commands

## Executive Summary

**YES - Direct node reuse is feasible and recommended** for CLI commands. PocketFlow nodes can be run standalone without a Flow using the `node.run(shared)` pattern. Both `WorkflowDiscoveryNode` and `ComponentBrowsingNode` can be directly reused with minimal setup.

## 1. Node Lifecycle Requirements

### How PocketFlow Nodes Work

From `pocketflow/__init__.py:32-40`:
```python
def _run(self, shared):
    p = self.prep(shared)
    e = self._exec(p)
    return self.post(shared, p, e)

def run(self, shared):
    if self.successors:
        warnings.warn("Node won't run successors. Use Flow.")
    return self._run(shared)
```

**Key Insights**:
- ✅ Nodes can run in isolation without a Flow
- ✅ Just call `node.run(shared)` with a dictionary
- ✅ The node handles the full prep → exec → post lifecycle
- ⚠️ Warning if node has successors, but still runs

### Minimal Setup Pattern

From test files (e.g., `tests/test_nodes/test_llm/test_llm.py:14-33`):
```python
# 1. Create node instance
node = LLMNode()

# 2. Set parameters (optional)
node.set_params({"model": "gpt-4"})

# 3. Create shared store
shared = {"prompt": "Test prompt"}

# 4. Run the node
action = node.run(shared)

# 5. Access results from shared store
assert shared["response"] == "Test response"
```

## 2. WorkflowDiscoveryNode Reuse

### What It Expects (from `nodes.py:90-135`)

**Required in Shared Store**:
- `user_input` (str) - The user's request
- `workflow_manager` (WorkflowManager, optional but recommended) - For loading workflows

**Optional in Shared Store**:
- `cache_planner` (bool, default: False) - Enable prompt caching

**What It Writes to Shared Store**:
- `discovery_context` (str) - Formatted workflow descriptions
- `discovery_result` (dict) - LLM decision with `found`, `workflow_name`, `confidence`, `reasoning`
- `found_workflow` (dict) - Full workflow IR (only if found=True)

**Returns**: Action string
- `"found_existing"` - Workflow match found (Path A)
- `"not_found"` - No match (Path B)

### Minimal Setup for CLI

```python
from pflow.planning.nodes import WorkflowDiscoveryNode
from pflow.core.workflow_manager import WorkflowManager

# Create node
node = WorkflowDiscoveryNode()

# Optional: Set LLM model
node.set_params({
    "model": "anthropic/claude-sonnet-4-0",
    "temperature": 0.0
})

# Create shared store
shared = {
    "user_input": "generate a changelog",
    "workflow_manager": WorkflowManager(),  # Auto-loads from ~/.pflow/workflows/
}

# Run discovery
action = node.run(shared)

# Access results
if action == "found_existing":
    print(f"Found: {shared['discovery_result']['workflow_name']}")
    print(f"Confidence: {shared['discovery_result']['confidence']}")
    workflow_ir = shared['found_workflow']
else:
    print("No matching workflow found")
```

**Dependencies**: NONE from other planner nodes! This is the entry point.

## 3. ComponentBrowsingNode Reuse

### What It Expects (from `nodes.py:345-412`)

**Required in Shared Store**:
- `user_input` (str) - The user's request

**Optional in Shared Store**:
- `workflow_manager` (WorkflowManager, optional) - For loading workflows
- `requirements_result` (dict, optional) - From RequirementsAnalysisNode
- `cache_planner` (bool, default: False) - Enable prompt caching

**What It Writes to Shared Store**:
- `browsed_components` (dict) - Selected node IDs and workflow names
- `planning_context` (str) - Combined context for workflow generator
- `registry_metadata` (dict) - Full registry data

**Returns**: Action string
- `"generate"` - Always (continues to generation path)

### Minimal Setup for CLI

```python
from pflow.planning.nodes import ComponentBrowsingNode
from pflow.core.workflow_manager import WorkflowManager

# Create node
node = ComponentBrowsingNode()

# Optional: Set LLM model
node.set_params({
    "model": "anthropic/claude-sonnet-4-0",
    "temperature": 0.0
})

# Create shared store - MINIMAL version
shared = {
    "user_input": "create a github issue triage report",
    # Optional: Add workflow_manager if you want workflow suggestions
    # "workflow_manager": WorkflowManager(),
}

# Run component browsing
action = node.run(shared)

# Access results
components = shared['browsed_components']
print(f"Selected nodes: {components.get('node_ids', [])}")
print(f"Selected workflows: {components.get('workflow_names', [])}")
print(f"\nContext preview:\n{shared['planning_context'][:500]}...")
```

**Dependencies**:
- ✅ Can run WITHOUT `requirements_result` (uses empty dict if missing)
- ✅ Creates its own Registry instance internally
- ✅ Builds contexts from scratch

## 4. Recommendations

### Direct Node Reuse: ✅ RECOMMENDED

**Reasons**:
1. **Proven Pattern**: Test suite shows nodes run independently 350+ times
2. **Minimal Setup**: Just create shared dict and call `run()`
3. **No Dependencies**: Each node is self-contained
4. **Easy Debugging**: Direct access to shared store
5. **Performance**: No Flow overhead

### Implementation Strategy

```python
# 1. Create node instance
node = WorkflowDiscoveryNode()  # or ComponentBrowsingNode()

# 2. Optional: Configure via params
node.set_params({"model": "anthropic/claude-sonnet-4-0"})

# 3. Setup shared store with required data
shared = {
    "user_input": query,
    "workflow_manager": WorkflowManager(),
}

# 4. Run node
action = node.run(shared)

# 5. Access results from shared store
result = shared['discovery_result']  # or shared['browsed_components']
```

### What NOT to Do

❌ **Don't extract logic from nodes** - Nodes are already designed for reuse
❌ **Don't create wrapper functions** - Just use the node directly
❌ **Don't create mini-flows** - Unnecessary complexity for CLI
❌ **Don't bypass the node lifecycle** - Always use `run()`, not individual methods

## 5. Complete Working Example

```python
# Example CLI command implementation

import click
from pflow.planning.nodes import WorkflowDiscoveryNode
from pflow.core.workflow_manager import WorkflowManager


@click.command()
@click.argument('query')
def discover(query: str):
    """Discover existing workflows matching the query."""
    node = WorkflowDiscoveryNode()
    shared = {
        "user_input": query,
        "workflow_manager": WorkflowManager(),
    }

    action = node.run(shared)

    if action == "found_existing":
        result = shared['discovery_result']
        click.echo(f"✓ Found: {result['workflow_name']}")
        click.echo(f"  Confidence: {result['confidence']:.0%}")
    else:
        click.echo("✗ No matching workflow")
```

## Conclusion

Direct node reuse is the optimal approach with minimal setup and proven reliability.
