# Flow-Level Resume: How It Would Actually Work

## The Core Challenge

PocketFlow's `Flow._orch()` method executes nodes sequentially until completion or failure. When a node fails, the flow stops, but the shared store contains all outputs from successful nodes. We need to resume from where we left off without re-executing successful nodes.

## Current PocketFlow Execution Model

```python
# Simplified version of PocketFlow's Flow._orch()
def _orch(self, shared):
    curr = self.start_node
    while curr:
        action = curr._run(shared)  # Runs prep, exec, post
        curr = self.get_next_node(curr, action)
    return action
```

Each node's `_run()` method:
1. Calls `prep(shared)` - prepares inputs
2. Calls `exec(prep_res)` - executes logic
3. Calls `post(shared, prep_res, exec_res)` - stores outputs in shared
4. Returns action string for routing

## The Resume Problem

When we resume, we need to:
1. Skip nodes that already executed successfully
2. Maintain correct action routing
3. Preserve the exact same data flow

## Proposed Solution: Execution Markers

### Key Insight
Add execution metadata to shared store that tracks:
- Which nodes completed
- What action they returned
- Whether they had side effects

### Modified Shared Store Structure
```python
shared = {
    # Node outputs (existing)
    "node1": {
        "result": {...},
        "output": {...}
    },

    # Execution metadata (new)
    "__execution__": {
        "completed_nodes": ["node1", "node2", "node3"],
        "node_actions": {
            "node1": "default",
            "node2": "default",
            "node3": "error"  # This is where we failed
        },
        "resume_point": "node4"
    }
}
```

## Implementation Approach

### Option 1: Wrapper-Based (Minimal Changes)

```python
def create_resumable_flow(flow, shared_state=None):
    """Wrap existing flow with resume capability."""

    if not shared_state or "__execution__" not in shared_state:
        # No resume needed, return original flow
        return flow

    # Wrap each node with resume checker
    execution_data = shared_state["__execution__"]
    completed = set(execution_data["completed_nodes"])

    for node_id in flow.get_all_nodes():
        if node_id in completed:
            # Replace node with pass-through version
            original_node = flow.get_node(node_id)
            flow.replace_node(node_id, PassThroughNode(original_node, execution_data))

    return flow

class PassThroughNode(Node):
    """Node that returns cached results without executing."""

    def __init__(self, original_node, execution_data):
        self.id = original_node.id
        self.action = execution_data["node_actions"].get(self.id, "default")

    def _run(self, shared):
        # Don't execute, just return cached action
        return self.action
```

### Option 2: Flow Subclass (Cleaner but Requires PocketFlow Change)

```python
class ResumableFlow(Flow):
    """Flow that can resume from a checkpoint."""

    def __init__(self, start=None):
        super().__init__(start)
        self.resume_data = None

    def set_resume_point(self, shared_state):
        """Configure resume from previous execution."""
        if "__execution__" in shared_state:
            self.resume_data = shared_state["__execution__"]

    def _orch(self, shared):
        curr = self.start_node

        while curr:
            if self._should_skip(curr):
                # Skip execution, use cached action
                action = self.resume_data["node_actions"].get(curr.id, "default")
                logger.info(f"Resuming {curr.id} with cached action: {action}")
            else:
                # Normal execution
                action = curr._run(shared)
                # Track for potential future resume
                self._track_execution(curr.id, action, shared)

            curr = self.get_next_node(curr, action)

        return action

    def _should_skip(self, node):
        """Check if node should be skipped (already executed)."""
        if not self.resume_data:
            return False
        return node.id in self.resume_data["completed_nodes"]

    def _track_execution(self, node_id, action, shared):
        """Track node execution for resume capability."""
        if "__execution__" not in shared:
            shared["__execution__"] = {
                "completed_nodes": [],
                "node_actions": {}
            }

        shared["__execution__"]["completed_nodes"].append(node_id)
        shared["__execution__"]["node_actions"][node_id] = action
```

## Critical Issue: Node Side Effects

### The Problem
Some nodes have side effects that we DON'T want to repeat:
- `send_slack_message` - Don't send duplicate
- `create_github_issue` - Don't create duplicate
- `write_file` - Don't overwrite

But their outputs might be needed by downstream nodes!

### The Solution: Output Preservation
When skipping a node, we need to ensure its outputs are still in shared:

```python
def _should_skip(self, node, shared):
    """Determine if node should be skipped."""

    # Check if node already executed
    if node.id not in self.resume_data["completed_nodes"]:
        return False

    # Check if outputs are present in shared
    if node.id not in shared:
        # Outputs missing! Need to restore them
        # This could happen if shared was partially cleared
        logger.warning(f"Node {node.id} marked complete but outputs missing")
        return False

    return True
```

## Real-World Example

### Initial Execution
```python
# Workflow: fetch → analyze → send → timestamp → update

shared = {}
flow.run(shared)

# Fails at timestamp, shared now contains:
{
    "fetch": {"messages": [...]},
    "analyze": {"questions": [...], "answers": [...]},
    "send": {"message_id": "123", "success": True},
    "__execution__": {
        "completed_nodes": ["fetch", "analyze", "send"],
        "node_actions": {
            "fetch": "default",
            "analyze": "default",
            "send": "default"
        }
    }
}
```

### Repair Execution
```python
# Create repaired workflow (fixed timestamp node)
repaired_flow = compile_repaired_workflow(ir)

# Set resume point
repaired_flow.set_resume_point(shared)

# Run - will skip fetch, analyze, send
repaired_flow.run(shared)

# Execution log:
# INFO: Resuming fetch with cached action: default
# INFO: Resuming analyze with cached action: default
# INFO: Resuming send with cached action: default
# INFO: Executing timestamp...
# INFO: Executing update...
```

## Edge Cases to Consider

### 1. Conditional Routing
If a node returns different actions based on execution:
```python
node1 - "success" → node2
      - "error" → error_handler
```
We must preserve the exact action to maintain correct flow.

### 2. Stateful Nodes
Some nodes might maintain internal state:
```python
class CounterNode(Node):
    def __init__(self):
        self.count = 0

    def exec(self, prep_res):
        self.count += 1  # State change!
        return {"count": self.count}
```
These need special handling or should not be resumed.

### 3. Partial Node Execution
If a node fails during `post()` after successful `exec()`:
- The side effect happened
- But outputs weren't stored
- Need careful handling

## Integration with Task 68

```python
class WorkflowExecutorService:
    def execute_workflow(self, workflow_ir, params, resume_state=None):
        # Compile workflow
        flow = compile_ir_to_flow(workflow_ir)

        # Prepare shared state
        if resume_state:
            # Continue from previous execution
            shared = resume_state.copy()
            # Configure flow for resume
            if hasattr(flow, 'set_resume_point'):
                flow.set_resume_point(shared)
        else:
            # Fresh start
            shared = {}

        # Execute
        try:
            action = flow.run(shared)
            success = not (action and action.startswith("error"))
        except Exception as e:
            success = False

        return ExecutionResult(
            success=success,
            shared_after=shared,  # Contains resume data!
        )
```

## Simpler Alternative: Node-Level Skip

Instead of modifying Flow, we could make nodes themselves resume-aware:

```python
class ResumableNode(Node):
    def _run(self, shared):
        # Check if we already executed
        if self._already_complete(shared):
            # Return cached action without re-execution
            exec_data = shared.get("__execution__", {})
            action = exec_data.get("node_actions", {}).get(self.id, "default")
            return action

        # Normal execution
        action = super()._run(shared)

        # Track execution
        self._track_completion(shared, action)

        return action
```

## Recommendation

**For Task 68 MVP**: Use the **Wrapper-Based Approach** (Option 1) because:
1. No changes to PocketFlow core required
2. Works with existing Flow implementation
3. Can be added transparently
4. Easy to test and debug

**Future Enhancement**: Consider Flow Subclass approach for cleaner implementation

## Key Principle

The shared store serves dual purpose:
1. **Data storage** - Node outputs (existing)
2. **Execution checkpoint** - Resume metadata (new)

This makes resume a natural extension of PocketFlow's existing architecture rather than a bolt-on feature.