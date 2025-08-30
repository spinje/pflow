# Detailed Implementation Plan for Native Nested Workflow Support in pflow

## Executive Summary

This plan details the implementation of native nested workflow support in pflow, leveraging PocketFlow's existing capability where Flows can be nodes. The implementation will be phased, starting with core functionality and expanding to advanced features.

## Core Principle

PocketFlow already supports nested workflows - any `Flow` can be used as a node within another `Flow` because `Flow` inherits from `BaseNode`. Our task is to expose this capability through pflow's IR schema, compiler, and CLI interface.

## Phase 1: Foundation Components (Essential MVP)

### 1.1 WorkflowNode Implementation

**File**: `src/pflow/nodes/workflow/workflow_node.py`

```python
from pflow.nodes.base import BaseNode
from pflow.runtime.compiler import compile_ir_to_flow
from pflow.core.exceptions import WorkflowExecutionError
import copy
import json
from pathlib import Path
from typing import Optional, Dict, Any

class WorkflowNode(BaseNode):
    """
    A node that executes another workflow as a sub-workflow.

    This node enables workflow composition by allowing workflows to contain
    other workflows, with controlled parameter passing and storage isolation.

    Inputs:
        - Any keys defined in param_mapping will be read from shared store

    Outputs:
        - Keys defined in output_mapping will be written to shared store

    Parameters:
        - workflow_ref (str): Path to workflow file or registry ID
        - workflow_ir (dict): Inline workflow IR definition (optional)
        - param_mapping (dict): Map parent values to child parameters
        - output_mapping (dict): Map child outputs to parent keys
        - storage_mode (str): "mapped" (default), "scoped", "isolated", or "shared"
        - error_action (str): Action to return on child workflow error (default: "error")
    """

    def __init__(self):
        super().__init__()
        self.child_workflow = None
        self.parent_shared = None
        self.execution_context = []

    def prep(self, shared):
        """Load and compile the child workflow."""
        self.parent_shared = shared

        # Track execution context for error reporting
        parent_context = shared.get("__workflow_context__", [])
        current_id = self.params.get("id", "unnamed")
        self.execution_context = parent_context + [current_id]

        # Load workflow IR
        workflow_ir = None
        if "workflow_ir" in self.params:
            # Inline workflow definition
            workflow_ir = self.params["workflow_ir"]
        elif "workflow_ref" in self.params:
            # Load from file or registry
            workflow_ir = self._load_workflow(self.params["workflow_ref"])
        else:
            raise ValueError("WorkflowNode requires either 'workflow_ref' or 'workflow_ir'")

        # Prepare parameters for child workflow
        param_mapping = self.params.get("param_mapping", {})
        child_params = self._resolve_parameters(param_mapping, shared)

        # Compile child workflow with parameters
        try:
            self.child_workflow = compile_ir_to_flow(
                workflow_ir,
                initial_params=child_params,
                registry=shared.get("__registry__"),  # Pass registry if available
                validate_templates=True
            )
        except Exception as e:
            raise WorkflowExecutionError(
                f"Failed to compile child workflow",
                workflow_path=self.execution_context,
                original_error=e
            )

        return {
            "workflow_ir": workflow_ir,
            "child_params": child_params,
            "storage_mode": self.params.get("storage_mode", "mapped")
        }

    def exec(self, prep_res):
        """Execute the child workflow with appropriate storage isolation."""
        storage_mode = prep_res["storage_mode"]
        child_params = prep_res["child_params"]

        # Create appropriate storage based on mode
        if storage_mode == "mapped":
            # Only mapped inputs are available
            child_shared = {"__workflow_context__": self.execution_context}
            child_shared.update(child_params)
        elif storage_mode == "isolated":
            # Completely empty storage
            child_shared = {"__workflow_context__": self.execution_context}
        elif storage_mode == "scoped":
            # Filtered view of parent storage
            prefix = self.params.get("scope_prefix", f"workflow_{self.params.get('id', 'child')}")
            child_shared = self._create_scoped_storage(self.parent_shared, prefix)
            child_shared["__workflow_context__"] = self.execution_context
        elif storage_mode == "shared":
            # Direct access (not recommended)
            child_shared = self.parent_shared
            child_shared["__workflow_context__"] = self.execution_context
        else:
            raise ValueError(f"Unknown storage_mode: {storage_mode}")

        # Execute child workflow
        try:
            result = self.child_workflow.run(child_shared)
        except Exception as e:
            raise WorkflowExecutionError(
                f"Child workflow execution failed",
                workflow_path=self.execution_context,
                original_error=e
            )

        return {
            "child_result": result,
            "child_shared": child_shared,
            "storage_mode": storage_mode
        }

    def post(self, shared, prep_res, exec_res):
        """Extract outputs from child workflow and update parent storage."""
        output_mapping = self.params.get("output_mapping", {})
        child_shared = exec_res["child_shared"]
        child_result = exec_res["child_result"]

        # Map outputs back to parent
        for child_key, parent_key in output_mapping.items():
            if child_key in child_shared:
                shared[parent_key] = child_shared[child_key]

        # Handle child workflow action
        if isinstance(child_result, str) and child_result == "error":
            # Child workflow failed, return error action
            return self.params.get("error_action", "error")

        # Return success action or child's action
        return child_result or "default"

    def _load_workflow(self, workflow_ref: str) -> dict:
        """Load workflow from file or registry."""
        # Check if it's a file path
        if "/" in workflow_ref or workflow_ref.endswith(".json"):
            path = Path(workflow_ref)
            if not path.is_absolute():
                # Resolve relative to parent workflow location if available
                parent_path = self.parent_shared.get("__workflow_file__")
                if parent_path:
                    path = Path(parent_path).parent / path

            if not path.exists():
                raise FileNotFoundError(f"Workflow file not found: {path}")

            with open(path) as f:
                return json.load(f)
        else:
            # Load from registry (future implementation)
            raise NotImplementedError("Registry workflow loading not yet implemented")

    def _resolve_parameters(self, param_mapping: dict, shared: dict) -> dict:
        """Resolve parameter mappings using template resolution."""
        from pflow.runtime.template_resolver import resolve_templates

        # Use template resolution to handle $variable syntax
        resolved = resolve_templates(
            param_mapping,
            shared,
            self.params.get("__initial_params__", {})
        )
        return resolved

    def _create_scoped_storage(self, parent_shared: dict, prefix: str) -> dict:
        """Create a scoped view of parent storage."""
        scoped = {}
        for key, value in parent_shared.items():
            if key.startswith(prefix):
                # Remove prefix for child
                new_key = key[len(prefix)+1:]  # +1 for the dot
                scoped[new_key] = value
        return scoped
```

### 1.2 IR Schema Extension

**File**: `src/pflow/core/ir_schema.py`

Add to the existing schema:

```python
class WorkflowNodeParams(BaseModel):
    """Parameters specific to WorkflowNode."""
    workflow_ref: Optional[str] = Field(None, description="Path to workflow file or registry ID")
    workflow_ir: Optional[Dict[str, Any]] = Field(None, description="Inline workflow definition")
    param_mapping: Dict[str, Any] = Field(default_factory=dict, description="Parameter mappings")
    output_mapping: Dict[str, str] = Field(default_factory=dict, description="Output mappings")
    storage_mode: Literal["mapped", "scoped", "isolated", "shared"] = Field(
        "mapped",
        description="Storage isolation mode"
    )
    error_action: str = Field("error", description="Action to return on error")

    @root_validator
    def validate_workflow_source(cls, values):
        if not values.get("workflow_ref") and not values.get("workflow_ir"):
            raise ValueError("Either workflow_ref or workflow_ir must be provided")
        if values.get("workflow_ref") and values.get("workflow_ir"):
            raise ValueError("Only one of workflow_ref or workflow_ir should be provided")
        return values
```

### 1.3 Compiler Enhancement

**File**: `src/pflow/runtime/compiler.py`

Modify the compiler to handle recursive compilation:

```python
class CompilationContext:
    """Track compilation state to prevent circular references."""
    def __init__(self):
        self.stack: List[str] = []
        self.compiled_workflows: Dict[str, Flow] = {}
        self.max_depth = 10

    def push(self, workflow_id: str):
        if workflow_id in self.stack:
            raise CircularReferenceError(
                f"Circular workflow reference detected: {' -> '.join(self.stack)} -> {workflow_id}"
            )
        if len(self.stack) >= self.max_depth:
            raise MaxNestingDepthError(
                f"Maximum nesting depth ({self.max_depth}) exceeded"
            )
        self.stack.append(workflow_id)

    def pop(self):
        if self.stack:
            self.stack.pop()

    def get_path(self) -> List[str]:
        return self.stack.copy()

def compile_ir_to_flow(
    ir: Union[str, Dict[str, Any]],
    initial_params: Optional[Dict[str, Any]] = None,
    registry: Optional[Registry] = None,
    validate_templates: bool = True,
    compilation_context: Optional[CompilationContext] = None
) -> Flow:
    """Enhanced compiler with nested workflow support."""

    # Create compilation context if not provided
    if compilation_context is None:
        compilation_context = CompilationContext()

    # ... existing compilation logic ...

    # When creating WorkflowNode instances, pass compilation context
    if node_type == "pflow.nodes.workflow.WorkflowNode":
        node.params["__compilation_context__"] = compilation_context
        node.params["__registry__"] = registry
```

### 1.4 Error Handling Enhancement

**File**: `src/pflow/core/exceptions.py`

```python
class WorkflowExecutionError(Exception):
    """Error that preserves nested workflow context."""
    def __init__(self, message: str, workflow_path: List[str], original_error: Exception):
        self.workflow_path = workflow_path
        self.original_error = original_error

        # Build context string
        path_str = " -> ".join(workflow_path)
        full_message = f"{message}\n  Workflow path: {path_str}\n  Original error: {str(original_error)}"
        super().__init__(full_message)

class CircularReferenceError(CompilationError):
    """Raised when circular workflow references are detected."""
    pass

class MaxNestingDepthError(CompilationError):
    """Raised when workflow nesting exceeds maximum depth."""
    pass
```

## Phase 2: CLI Integration

### 2.1 Workflow Management Commands

**File**: `src/pflow/cli/commands/workflow.py`

```python
@click.group()
def workflow():
    """Manage workflows."""
    pass

@workflow.command()
@click.argument("name")
@click.argument("workflow_file", type=click.Path(exists=True))
def save(name: str, workflow_file: str):
    """Save a workflow to the registry."""
    # Implementation for saving workflows
    pass

@workflow.command()
def list():
    """List available workflows."""
    # Show saved workflows
    pass

@workflow.command()
@click.argument("workflow_file", type=click.Path(exists=True))
@click.option("--max-depth", default=3, help="Maximum nesting depth to validate")
def validate(workflow_file: str, max_depth: int):
    """Validate a workflow including nested workflows."""
    # Recursive validation
    pass
```

### 2.2 Enhanced Run Command

Modify `src/pflow/cli/main.py` to support nested workflow debugging:

```python
@cli.command()
@click.option("--trace", is_flag=True, help="Show execution trace for nested workflows")
@click.option("--debug-storage", is_flag=True, help="Capture storage snapshots at workflow boundaries")
def run(workflow, params, stdin, output, verbose, trace, debug_storage):
    """Enhanced run command with nested workflow support."""
    if trace or debug_storage:
        shared["__trace_enabled__"] = trace
        shared["__debug_storage__"] = debug_storage
```

## Phase 3: Registry Enhancement

### 3.1 Workflow Registry

**File**: `src/pflow/registry/workflow_registry.py`

```python
class WorkflowRegistry:
    """Registry for managing reusable workflows."""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self._cache: Dict[str, WorkflowMetadata] = {}

    def register(self, workflow_id: str, workflow_ir: dict, metadata: dict):
        """Register a workflow with the registry."""
        # Validate workflow
        # Save to appropriate location
        # Update cache
        pass

    def resolve(self, workflow_ref: str) -> dict:
        """Resolve a workflow reference to IR."""
        # Handle different reference formats
        # Check cache first
        # Load from disk if needed
        pass

    def list_workflows(self, namespace: Optional[str] = None) -> List[WorkflowMetadata]:
        """List available workflows."""
        pass
```

## Phase 4: Documentation and Testing

### 4.1 Documentation Updates

1. **Conceptual Guide** (`architecture/features/nested-workflows.md`):
   - When and why to use nested workflows
   - Storage isolation strategies explained
   - Parameter passing patterns
   - Best practices for composition

2. **Reference Documentation** (`architecture/reference/workflow-node.md`):
   - WorkflowNode API reference
   - IR schema for nested workflows
   - Error handling guide
   - Performance considerations

3. **Examples** (`examples/nested/`):
   - Basic nested workflow
   - Parameter mapping examples
   - Error handling patterns
   - Multi-level nesting

### 4.2 Test Suite

**File**: `tests/test_nested_workflows/`

```python
def test_basic_nested_workflow():
    """Test executing a simple nested workflow."""
    parent_ir = {
        "nodes": [{
            "id": "child",
            "type": "pflow.nodes.workflow.WorkflowNode",
            "params": {
                "workflow_ir": {
                    "nodes": [{
                        "id": "inner",
                        "type": "pflow.nodes.core.PrintNode",
                        "params": {"message": "Hello from child"}
                    }],
                    "edges": []
                }
            }
        }],
        "edges": []
    }

    flow = compile_ir_to_flow(parent_ir)
    result = flow.run({})
    assert result == "default"

def test_parameter_mapping():
    """Test parameter passing to child workflows."""
    # Test template resolution
    # Test nested object mapping
    # Test missing parameter handling
    pass

def test_output_mapping():
    """Test extracting outputs from child workflows."""
    pass

def test_storage_isolation_modes():
    """Test different storage isolation strategies."""
    pass

def test_circular_reference_detection():
    """Test that circular references are caught."""
    pass

def test_max_nesting_depth():
    """Test maximum nesting depth enforcement."""
    pass

def test_error_propagation():
    """Test error handling in nested contexts."""
    pass
```

## Implementation Order

### Week 1: Core Implementation
1. Implement WorkflowNode class
2. Extend IR schema
3. Add compilation context tracking
4. Basic error handling

### Week 2: Storage and Parameters
1. Implement storage isolation modes
2. Add parameter mapping with template support
3. Output mapping implementation
4. Enhanced error context

### Week 3: CLI and Registry
1. Add workflow management commands
2. Implement workflow registry basics
3. Enhanced run command with debugging
4. Workflow validation command

### Week 4: Testing and Documentation
1. Comprehensive test suite
2. Documentation writing
3. Example workflows
4. Performance testing

## Key Design Decisions

1. **Storage Isolation by Default**: The "mapped" mode is default for safety
2. **Explicit Parameter Mapping**: No automatic inheritance to avoid surprises
3. **Action Propagation**: Child workflow actions bubble up naturally
4. **File-First Approach**: Start with file references, add registry later
5. **Template Compatibility**: Reuse existing template resolution system
6. **Fail-Fast Errors**: Stop on first error in MVP, add recovery later

## Risk Mitigation

1. **Performance**: Monitor compilation time, add caching in v2
2. **Complexity**: Clear documentation and examples
3. **Debugging**: Rich error messages with execution paths
4. **Security**: Storage isolation prevents data leaks
5. **Compatibility**: No breaking changes to existing workflows

## Success Metrics

1. **Functionality**: Can execute 3-level nested workflows
2. **Performance**: < 500ms compilation for typical workflows
3. **Usability**: Clear error messages with actionable fixes
4. **Testing**: > 90% code coverage for new components
5. **Documentation**: Complete guides and examples

## Future Enhancements (Post-MVP)

1. **Parallel Sub-workflows**: Execute independent children concurrently
2. **Workflow Versioning**: Semantic versioning with lockfiles
3. **Remote Workflows**: Load workflows from URLs/repositories
4. **Visual Debugging**: Workflow execution visualization
5. **Advanced Storage**: Transactional storage operations
6. **Workflow Marketplace**: Share and discover workflows

## Conclusion

This plan provides a clear path to implementing nested workflow support in pflow. The implementation leverages PocketFlow's existing capabilities while adding the necessary pflow-specific components for IR representation, compilation, storage isolation, and error handling. The phased approach ensures we can deliver value incrementally while maintaining system stability.
