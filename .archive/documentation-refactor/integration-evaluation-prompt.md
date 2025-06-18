# Prompt for Evaluating PocketFlow Integration

## Context
You are evaluating the integration between pflow and pocketflow. There is an analysis in `/Users/andfal/projects/pflow/scratchpads/pocketflow-integration-analysis.md` that suggests creating wrapper classes and an integration task (#30). However, we need to be EXTREMELY careful about this approach.

## Your Mission
Re-evaluate the entire integration strategy with these principles:
1. **Simplicity First**: Don't create abstractions unless absolutely necessary
2. **Direct Usage**: Use pocketflow directly when possible, don't wrap for the sake of wrapping
3. **Perfect Understanding**: You must understand BOTH systems deeply before making recommendations

## Critical Questions to Answer

### 1. Do we actually need wrapper classes?
- Task #30 suggests creating `PflowNode(pocketflow.Node)` and `PflowFlow(pocketflow.Flow)`
- But WHY? What concrete value do these wrappers add?
- Could we just `from pocketflow import Node, Flow` and use them directly?
- Example: If a node just needs prep/exec/post, why not directly inherit from pocketflow.Node?

### 2. What is the SharedStore situation really?
- PocketFlow uses a plain dictionary passed to nodes
- Task #2 wants to create a SharedStore class
- But do we need a class? Or just validation functions?
- Could we use a plain dict with helper functions instead of wrapping it in a class?
- What's the simplest way to add reserved key validation without overengineering?

### 3. What does "integration" actually mean?
- Is it just importing pocketflow correctly?
- Is it documentation to prevent confusion?
- Is it updating existing tasks to be aware of pocketflow?
- Or is it something else entirely?

## Deep Analysis Required

### Step 1: Read and understand pocketflow completely
- Read `/Users/andfal/projects/pflow/pocketflow/__init__.py` (100 lines)
- Read `/Users/andfal/projects/pflow/pocketflow/docs/core_abstraction/node.md`
- Read `/Users/andfal/projects/pflow/pocketflow/docs/core_abstraction/communication.md`
- Read `/Users/andfal/projects/pflow/pocketflow/docs/core_abstraction/flow.md`
- Understand EXACTLY what pocketflow provides and how it's meant to be used

### Step 2: Understand pflow's actual needs
- Read `/Users/andfal/projects/pflow/docs/architecture.md`
- Read `/Users/andfal/projects/pflow/docs/shared-store.md`
- Read `/Users/andfal/projects/pflow/docs/runtime.md`
- Identify what pflow ACTUALLY needs that pocketflow doesn't provide

### Step 3: Evaluate each "duplicate" task
For each task that might duplicate pocketflow functionality:
- Task #2 (SharedStore): What does pflow need beyond a dict?
- Task #21 (Execution engine): What does pflow need beyond Flow?
- Task #3 (NodeAwareSharedStore): Is this actually needed or overengineering?

### Step 4: Question task #30
- Why create base classes if we can use pocketflow directly?
- What concrete problems does this solve?
- Are we creating unnecessary abstraction layers?
- Could documentation alone solve the "awareness" problem?

## Specific Examples to Consider

### Example 1: Simple Node
```python
# Option A: Direct inheritance
from pocketflow import Node

class ReadFileNode(Node):
    def prep(self, shared):
        return shared.get("file_path")

    def exec(self, file_path):
        with open(file_path) as f:
            return f.read()

    def post(self, shared, prep_res, exec_res):
        shared["content"] = exec_res
        return "default"

# Option B: With wrapper (from task #30)
from pflow.core.base import PflowNode

class ReadFileNode(PflowNode):
    # Same implementation
```

What value does Option B add? Be specific.

### Example 2: Shared Store
```python
# Option A: Plain dict with validation functions
def validate_shared_store(shared):
    if "stdin" in shared and not isinstance(shared["stdin"], str):
        raise ValueError("stdin must be string")
    return True

shared = {}
validate_shared_store(shared)

# Option B: Wrapper class
class SharedStore(dict):
    def __setitem__(self, key, value):
        if key == "stdin" and not isinstance(value, str):
            raise ValueError("stdin must be string")
        super().__setitem__(key, value)
```

Which is simpler? Which is more pythonic?

## Final Deliverables

1. **Clear recommendation**: Should we keep, modify, or remove task #30?
2. **Updated task descriptions**: For tasks #2, #21, and any others that need pocketflow awareness
3. **Integration strategy**: The SIMPLEST way to ensure pflow uses pocketflow correctly
4. **Concrete examples**: Show exactly how nodes should be implemented

## Remember
- We're building a CLI tool, not a framework on top of a framework
- Pocketflow is already well-designed; we should use it as intended
- Every abstraction layer adds complexity - only add if there's clear value
- Documentation might solve more problems than code

## Key Insight to Validate
The user said: "Cant we just use the code when needed?"

This suggests that maybe we don't need an "integration task" at all. Maybe we just need:
1. Update existing tasks to mention pocketflow where relevant
2. Use pocketflow directly in our implementations
3. No wrapper classes, no integration layer, just direct usage

Evaluate if this simpler approach would work.
