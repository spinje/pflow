# Task 4 Implementation Checklist

Quick reference checklist for implementing the IR-to-PocketFlow compiler.

## Pre-Implementation
- [ ] Read `docs/architecture/pflow-pocketflow-integration-guide.md` (CRITICAL)
- [ ] Read `pocketflow/__init__.py` to understand Flow and Node classes
- [ ] Review `src/pflow/core/ir_schema.py` to understand IR structure
- [ ] Check `src/pflow/nodes/test_node.py` for available test nodes
- [ ] Ensure package is installed with `pip install -e .` or `uv pip install -e .`

## Implementation Steps

### 1. Module Setup
- [ ] Create `src/pflow/runtime/` directory
- [ ] Create `src/pflow/runtime/__init__.py`
- [ ] Create `src/pflow/runtime/compiler.py`
- [ ] Import required modules:
  - `importlib`
  - `pocketflow` (for BaseNode, Node, Flow)
  - `typing` for type hints

### 2. Create CompilationError
- [ ] Custom exception class with helpful context
- [ ] Include node_id, node_type, and error details

### 3. Main Function: compile_ir_to_flow
- [ ] Function signature: `compile_ir_to_flow(ir_json: dict, registry: dict) -> pocketflow.Flow`
- [ ] Validate inputs exist
- [ ] Create empty nodes dict

### 4. Node Creation Loop
For each node in ir_json["nodes"]:
- [ ] Extract node_id, node_type, params
- [ ] Look up metadata in registry
- [ ] Handle missing node types with clear error
- [ ] Dynamic import with try/except for ImportError
- [ ] Get class with try/except for AttributeError
- [ ] Verify inheritance from BaseNode/Node
- [ ] Instantiate node
- [ ] Call node.set_params(params) if params exist
- [ ] Store in nodes dict with node_id as key

### 5. Edge Connection Loop
For each edge in ir_json["edges"]:
- [ ] Extract from_id, to_id, action
- [ ] Verify both nodes exist in nodes dict
- [ ] Use >> for default/empty action
- [ ] Use - action >> for specific actions
- [ ] Handle missing node references

### 6. Flow Creation
- [ ] Determine start node (explicit or first node)
- [ ] Create Flow with start node
- [ ] Return Flow object

### 7. Error Handling
- [ ] Clear messages for all failure modes
- [ ] Include context (node ID, type, import path)
- [ ] Test each error path

## Testing Checklist

### Unit Tests
- [ ] Test with valid IR and registry (happy path)
- [ ] Test with test nodes from test_node.py
- [ ] Test missing node type in registry
- [ ] Test import error (bad module path)
- [ ] Test attribute error (bad class name)
- [ ] Test non-BaseNode class
- [ ] Test invalid edge references
- [ ] Test with/without start_node
- [ ] Test with/without params
- [ ] Test action-based routing

### Integration Tests
- [ ] Test with actual test_node imports
- [ ] Verify compiled flow can execute
- [ ] Test parameter passing to nodes

## Code Quality
- [ ] Add docstrings to all functions
- [ ] Add type hints
- [ ] Keep under 200 lines
- [ ] No complex abstractions
- [ ] Clear variable names

## What NOT to Do
- [ ] DON'T resolve template variables ($var)
- [ ] DON'T implement execution logic
- [ ] DON'T create wrapper classes
- [ ] DON'T cache imports
- [ ] DON'T validate parameter contents
- [ ] DON'T implement features from other tasks

## Final Verification
- [ ] Run all tests
- [ ] Check imports work after fresh install
- [ ] Verify error messages are helpful
- [ ] Ensure no PocketFlow internals are reimplemented
- [ ] Document any security considerations
