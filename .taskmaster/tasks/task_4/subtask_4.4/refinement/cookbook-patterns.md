# Cookbook Patterns for Subtask 4.4

## Relevant PocketFlow Patterns for Integration Testing

### 1. Test Node Creation Pattern
**Source**: pocketflow/tests/test_flow.py
**Purpose**: Create lightweight mock nodes for testing flow behavior

```python
class NumberNode(Node):
    def __init__(self, number):
        super().__init__()
        self.number = number

    def prep(self, shared_storage):
        shared_storage['current'] = self.number

    # post implicitly returns None for default transition
```

**How to apply**: Create similar mock nodes that simulate real pflow nodes (llm, read-file, etc.) but with deterministic behavior for testing.

### 2. Conditional Node Pattern
**Source**: pocketflow/tests/test_flow.py
**Purpose**: Test branching logic and action-based routing

```python
class CheckPositiveNode(Node):
    def post(self, shared_storage, prep_result, proc_result):
        if shared_storage['current'] >= 0:
            return 'positive'
        else:
            return 'negative'
```

**How to apply**: Use for testing edge cases with action strings in IR edges.

### 3. Error Simulation Pattern
**Source**: pocketflow/tests/test_fallback.py
**Purpose**: Test error handling and retry logic

```python
class FallbackNode(Node):
    def __init__(self, should_fail=True, max_retries=1):
        super().__init__(max_retries=max_retries)
        self.should_fail = should_fail

    def exec(self, prep_result):
        if self.should_fail:
            raise ValueError("Intentional failure")
        return "success"
```

**How to apply**: Create error nodes to test compiler error messages and flow error propagation.

### 4. Flow Testing Pattern
**Source**: pocketflow/tests/test_flow.py
**Purpose**: Test complete flow execution

```python
def test_sequence_with_rshift(self):
    shared_storage = {}
    n1 = NumberNode(5)
    n2 = AddNode(3)
    n3 = MultiplyNode(2)

    pipeline = Flow()
    pipeline.start(n1) >> n2 >> n3

    last_action = pipeline.run(shared_storage)
    self.assertEqual(shared_storage['current'], 16)
```

**How to apply**: After compiling IR to Flow, run the flow and verify shared storage state.

### 5. Performance Measurement Pattern
**Source**: pocketflow/tests/test_async_parallel_batch_node.py (adapted)
**Purpose**: Measure execution time for performance benchmarks

```python
import time

def test_compilation_performance(self):
    start_time = time.perf_counter()
    flow = compile_ir_to_flow(ir_json, registry)
    end_time = time.perf_counter()

    compilation_time = (end_time - start_time) * 1000  # Convert to ms
    assert compilation_time < 100, f"Compilation took {compilation_time}ms"
```

**How to apply**: Use for <100ms compilation benchmark tests.

### 6. Shared Storage Pattern
**Source**: All pocketflow tests
**Purpose**: Verify node communication and flow results

```python
shared_storage = {
    'input': test_data,
    'config': {'key': 'value'}
}

flow.run(shared_storage)

# Verify results
assert shared_storage['output'] == expected_result
```

**How to apply**: Use to verify that compiled flows execute correctly and produce expected results.

## Integration Test Structure Based on Patterns

```python
class TestCompilerIntegration(unittest.TestCase):
    def setUp(self):
        # Create test registry with mock nodes
        self.registry = self._create_mock_registry()

    def _create_mock_registry(self):
        # Registry with paths to mock nodes
        return {
            "basic-node": {
                "module": "tests.test_compiler_integration",
                "class_name": "BasicMockNode"
            },
            # ... more nodes
        }

    def test_end_to_end_compilation(self):
        # Load IR example
        # Compile to flow
        # Run flow
        # Verify results
```

## Key Insights from Patterns

1. **Node simplicity**: Test nodes should be minimal - just enough behavior to verify compilation
2. **Shared storage verification**: The primary way to verify flow execution results
3. **Direct testing**: No need for complex mocking - PocketFlow nodes are simple to create
4. **Performance timing**: Use time.perf_counter() for accurate sub-second measurements

These patterns provide a solid foundation for creating comprehensive integration tests that verify both compilation correctness and execution behavior.
