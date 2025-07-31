# Task 17 Patterns and Conventions

## Registry Access Pattern

All planner nodes must follow the PocketFlow standard for external service access:

### ✅ DO: Direct Import and Instantiation
```python
from pflow.registry import Registry
import llm

class PlannerNode(Node):
    def __init__(self):
        super().__init__()
        self.registry = Registry()
        self.model = llm.get_model("claude-sonnet-4-20250514")
```

### ❌ DON'T: Pass Through Shared Store
```python
# Never do this:
registry = shared.get("registry")
model = shared.get("llm_model")
```

### Rationale
This pattern is consistent with ALL PocketFlow examples:
- Database connections
- LLM clients
- Web crawlers
- MCP tools

The shared store is exclusively for data flow between nodes, never for service dependencies.

## prep() Method Patterns

### Simple Data Extraction
Most common pattern - extract specific values:
```python
def prep(self, shared):
    return shared["user_input"], shared["context"]
```

### Exception: Error Handling Access
When using exec_fallback that needs shared context:
```python
def prep(self, shared):
    # Return shared when exec_fallback needs access
    return shared

def exec_fallback(self, prep_res, exc):
    shared = prep_res  # Access shared through prep_res
    # Error handling logic
```

## Node Autonomy Principle

Each node manages its own dependencies:
- Import what you need
- Instantiate in `__init__`
- Keep shared store for data only
