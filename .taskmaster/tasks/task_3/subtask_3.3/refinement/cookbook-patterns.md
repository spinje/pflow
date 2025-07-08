# Cookbook Patterns for Subtask 3.3

## Relevant PocketFlow Patterns

### 1. Test Node Pattern (from `test_flow_basic.py`)
**Purpose**: Create minimal nodes for testing execution order and shared store manipulation

**Key Code**:
```python
class NumberNode(Node):
    def __init__(self, number):
        super().__init__()
        self.number = number
    def prep(self, shared_storage):
        shared_storage['current'] = self.number
```

**Application**: Create OrderTrackingNode that appends to a list in shared store to verify execution sequence

### 2. Shared Store Verification (from `pocketflow-communication`)
**Purpose**: Track and verify state across multiple node executions

**Key Pattern**:
- Use natural key names: `shared["content"]`, `shared["written"]`
- Initialize state if not present
- Accumulate values to track execution flow

**Application**: After flow.run(), assert expected keys and values exist in shared_storage

### 3. Flow Result Testing (from `test_flow_basic.py`)
**Purpose**: Verify flow execution results and final state

**Key Code**:
```python
last_action = pipeline.run(shared_storage)
self.assertEqual(shared_storage['current'], 16)
self.assertIsNone(last_action)
```

**Application**: Check both the return value (action string) and final shared store state

## How These Apply to Our Tests

1. **For execution order testing**: Create simple nodes that record their execution in a list
2. **For shared store testing**: Add assertions checking specific keys after flow.run()
3. **For error propagation**: Verify that error action strings are returned from flow.run()
