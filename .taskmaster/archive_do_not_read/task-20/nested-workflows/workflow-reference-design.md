# Workflow Reference System Design

This document presents a comprehensive design for implementing workflow references in pflow, enabling workflows to be composed of other workflows as reusable components.

## Executive Summary

The workflow reference system extends pflow to support workflow composition through a new `WorkflowNode` type that can execute other workflows as sub-components. This design aligns with pflow's existing patterns while enabling powerful composition capabilities.

## Design Principles

1. **Consistency**: Follow existing node patterns and registry mechanisms
2. **Simplicity**: Workflows are just another type of reusable component
3. **Isolation**: Sub-workflows execute in controlled storage contexts
4. **Determinism**: Workflow references are versioned and lockfile-managed
5. **Transparency**: Clear debugging and error reporting through nested contexts

## Core Components

### 1. Workflow Reference Resolution

Workflows can be referenced in three ways:

```python
# 1. Registry ID (follows node naming pattern)
workflow_ref = "core/data-pipeline@1.0.0"

# 2. File path (relative or absolute)
workflow_ref = "./workflows/process-data.json"
workflow_ref = "/home/user/.pflow/workflows/analyze.json"

# 3. Inline definition (embedded IR)
workflow_ir = {
    "nodes": [...],
    "edges": [...],
    "mappings": {...}
}
```

### 2. WorkflowNode Implementation

```python
from pflow.runtime.compiler import compile_workflow
from pocketflow import Node

class WorkflowNode(Node):
    """Execute another workflow as a sub-component.

    This node enables workflow composition by running a complete workflow
    within the context of a parent workflow.

    Inputs:
        All inputs defined by the referenced workflow

    Outputs:
        All outputs defined by the referenced workflow

    Params:
        workflow_ref (str): Registry ID or file path to workflow
        workflow_ir (dict): Inline workflow definition (alternative to ref)
        input_mapping (dict): Map parent keys to sub-workflow inputs
        output_mapping (dict): Map sub-workflow outputs to parent keys
        storage_mode (str): Storage isolation strategy
        inherit_params (bool): Pass parent template params to sub-workflow

    Actions:
        - default: Sub-workflow completed successfully
        - workflow_failed: Sub-workflow encountered an error
        - workflow_not_found: Referenced workflow doesn't exist
    """

    def prep(self, shared):
        """Load and prepare the sub-workflow."""
        # Resolve workflow reference
        if self.params.get("workflow_ref"):
            workflow_ir = self._load_workflow_ref(self.params["workflow_ref"])
        elif self.params.get("workflow_ir"):
            workflow_ir = self.params["workflow_ir"]
        else:
            raise ValueError("Either workflow_ref or workflow_ir must be provided")

        # Create storage context based on mode
        storage_mode = self.params.get("storage_mode", "mapped")
        sub_storage = self._create_storage_context(shared, storage_mode)

        # Apply input mappings
        if input_mapping := self.params.get("input_mapping"):
            for parent_key, child_key in input_mapping.items():
                if parent_key in shared:
                    sub_storage[child_key] = shared[parent_key]

        return {
            "workflow_ir": workflow_ir,
            "sub_storage": sub_storage,
            "parent_shared": shared
        }

    def exec(self, prep_res):
        """Compile and execute the sub-workflow."""
        try:
            # Compile workflow with parent parameters if requested
            template_params = {}
            if self.params.get("inherit_params", True):
                # Extract template params from parent context
                template_params = prep_res.get("parent_template_params", {})

            # Compile the sub-workflow
            flow = compile_workflow(
                prep_res["workflow_ir"],
                template_params=template_params,
                context_path=self._get_context_path()
            )

            # Execute with sub-storage
            flow.run(prep_res["sub_storage"])

            return {
                "success": True,
                "sub_storage": prep_res["sub_storage"]
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }

    def post(self, shared, prep_res, exec_res):
        """Merge results back to parent storage."""
        if not exec_res["success"]:
            # Handle workflow execution failure
            self._log_error(exec_res)
            return "workflow_failed"

        # Apply output mappings
        if output_mapping := self.params.get("output_mapping"):
            sub_storage = exec_res["sub_storage"]
            for child_key, parent_key in output_mapping.items():
                if child_key in sub_storage:
                    shared[parent_key] = sub_storage[child_key]
        elif self.params.get("storage_mode") == "shared":
            # Shared mode - changes already reflected
            pass
        else:
            # Default: merge all outputs with prefix
            prefix = self.params.get("output_prefix", f"{self.id}_")
            for key, value in exec_res["sub_storage"].items():
                shared[f"{prefix}{key}"] = value

        return "default"
```

### 3. Storage Isolation Strategies

#### Mapped Mode (Default)
- Explicit input/output mappings
- Most controlled and predictable
- Best for production workflows

```json
{
  "type": "WorkflowNode",
  "params": {
    "workflow_ref": "core/analyze-text@1.0.0",
    "storage_mode": "mapped",
    "input_mapping": {
      "document_text": "text",      // parent → child
      "analysis_type": "prompt"
    },
    "output_mapping": {
      "analysis": "result",         // child → parent
      "confidence": "score"
    }
  }
}
```

#### Scoped Mode
- Sub-workflow gets filtered view of parent storage
- Useful for workflows that need partial context
- Keys are prefixed/namespaced

```json
{
  "storage_mode": "scoped",
  "scope_prefix": "data.",          // Sub sees only data.* keys
  "output_prefix": "results."       // Outputs written as results.*
}
```

#### Isolated Mode
- Sub-workflow starts with empty storage
- Only explicit inputs passed
- Maximum isolation for security

#### Shared Mode
- Sub-workflow shares parent storage directly
- Risky but sometimes necessary
- Use with caution

### 4. Registry Extensions

#### Workflow Storage Structure
```
~/.pflow/
├── registry.json          # Node registry
├── workflows/
│   ├── registry.json     # Workflow registry
│   ├── core/            # Namespaced workflows
│   │   ├── analyze-text/
│   │   │   ├── 1.0.0.json
│   │   │   └── 1.1.0.json
│   │   └── data-pipeline/
│   │       └── 1.0.0.json
│   └── user/            # User workflows
│       └── my-workflow.json
└── lockfiles/
    └── workflows/
        └── data-pipeline.lock.json
```

#### Workflow Metadata Schema
```json
{
  "id": "core/analyze-text",
  "version": "1.0.0",
  "name": "analyze-text",
  "description": "Analyze text using LLM",
  "inputs": {
    "text": {
      "type": "str",
      "required": true,
      "description": "Text to analyze"
    },
    "prompt": {
      "type": "str",
      "required": true,
      "description": "Analysis instructions"
    }
  },
  "outputs": {
    "analysis": {
      "type": "str",
      "description": "Analysis results"
    },
    "confidence": {
      "type": "float",
      "description": "Confidence score"
    }
  },
  "ir": {
    "nodes": [...],
    "edges": [...],
    "mappings": {...}
  },
  "created_at": "2024-01-15T10:00:00Z",
  "updated_at": "2024-01-15T10:00:00Z",
  "tags": ["text-analysis", "llm"],
  "dependencies": {
    "nodes": {
      "core/llm": "1.0.0"
    },
    "workflows": {}
  }
}
```

### 5. Compiler Enhancements

#### Recursive Compilation
```python
def compile_workflow(ir_json, template_params=None, context_path=None, _depth=0):
    """Enhanced compiler with workflow reference support."""

    # Circular reference detection
    if _depth > MAX_WORKFLOW_DEPTH:
        raise CompilationError("Maximum workflow nesting depth exceeded")

    # Track compilation context for error reporting
    context = CompilationContext(path=context_path, depth=_depth)

    # Parse and validate IR
    ir_dict = _parse_ir_input(ir_json)
    _validate_ir_structure(ir_dict)

    # Process nodes
    for node_config in ir_dict["nodes"]:
        if node_config["type"] == "WorkflowNode":
            # Special handling for workflow nodes
            node = _compile_workflow_node(
                node_config,
                template_params,
                context,
                _depth + 1
            )
        else:
            # Regular node compilation
            node = _compile_regular_node(node_config, template_params)
```

#### Workflow Caching
```python
class WorkflowCache:
    """Cache compiled workflows for performance."""

    def __init__(self):
        self._cache = {}
        self._registry = WorkflowRegistry()

    def get_workflow(self, ref: str, version: str = None) -> dict:
        """Get workflow IR with caching."""
        cache_key = f"{ref}@{version or 'latest'}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        # Load from registry or file
        workflow_ir = self._load_workflow(ref, version)
        self._cache[cache_key] = workflow_ir

        return workflow_ir
```

### 6. Error Handling

#### Nested Error Context
```python
class WorkflowExecutionError(Exception):
    """Enhanced error with workflow nesting context."""

    def __init__(self, message, workflow_path, node_id, parent_context=None):
        self.workflow_path = workflow_path
        self.node_id = node_id
        self.parent_context = parent_context

        # Build full context trace
        context_trace = self._build_context_trace()

        super().__init__(f"{message}\n\nExecution Context:\n{context_trace}")
```

Example error output:
```
WorkflowExecutionError: Failed to read file 'data.csv'

Execution Context:
  main-workflow.json
    └─ Node: process_data (WorkflowNode)
       └─ Sub-workflow: core/data-pipeline@1.0.0
          └─ Node: read_input (ReadFileNode)
             └─ Error: FileNotFoundError: data.csv
```

### 7. CLI Extensions

#### Workflow Management Commands
```bash
# List available workflows
pflow workflows list [--namespace=core] [--tag=analysis]

# Show workflow details
pflow workflows show core/analyze-text@1.0.0

# Validate workflow including sub-workflows
pflow validate workflow.json --recursive

# Create workflow from existing flow
pflow workflows create my-analysis \
  --from-file=analyze.json \
  --namespace=user \
  --version=1.0.0
```

#### Workflow Composition
```bash
# Use workflow in pipe syntax
pflow read-file data.txt >> workflow:core/analyze-text >> write-file results.txt

# With inline parameters
pflow workflow:analyze-text \
  --workflow.text="$INPUT" \
  --workflow.prompt="Summarize this"
```

### 8. Version Management

#### Lockfile Integration
Workflows participate in the existing lockfile system:

```json
// flow.versions.lock
{
  "nodes": {
    "core/llm": "1.0.0",
    "core/read-file": "1.0.0"
  },
  "workflows": {
    "core/analyze-text": "1.0.0",
    "user/my-pipeline": "2.1.0"
  }
}
```

#### Version Resolution
1. Explicit version: `core/analyze-text@1.0.0`
2. Major version: `core/analyze-text@1`
3. Lockfile version
4. Latest available (with warning)

### 9. Security Considerations

#### Resource Limits
```python
class WorkflowExecutor:
    MAX_DEPTH = 10          # Maximum nesting depth
    MAX_NODES = 1000        # Maximum nodes across all workflows
    TIMEOUT = 300           # 5 minute timeout
```

#### Access Control
- Workflows can only reference nodes they have permission to use
- User workflows cannot reference system workflows without permission
- Sandboxed execution for untrusted workflows

### 10. Implementation Phases

#### Phase 1: Core WorkflowNode (MVP)
- Basic WorkflowNode implementation
- File-based workflow references
- Mapped storage mode only
- Simple error handling

#### Phase 2: Registry Integration
- Workflow registry with versioning
- Namespace support
- Basic CLI commands
- Lockfile integration

#### Phase 3: Advanced Features
- All storage modes
- Recursive validation
- Performance optimization
- Enhanced debugging

#### Phase 4: Ecosystem
- Workflow marketplace
- Remote workflow repositories
- Dependency management
- Security sandboxing

## Benefits

1. **Reusability**: Common patterns become shareable workflows
2. **Composability**: Build complex flows from simple pieces
3. **Maintainability**: Update workflows in one place
4. **Testability**: Test workflows in isolation
5. **Discoverability**: Browse and search workflow library

## Example Use Cases

### Data Processing Pipeline
```json
{
  "nodes": [
    {
      "id": "fetch_data",
      "type": "WorkflowNode",
      "params": {
        "workflow_ref": "core/fetch-api-data@1.0.0",
        "input_mapping": {
          "api_key": "api_key",
          "endpoint": "data_endpoint"
        }
      }
    },
    {
      "id": "process",
      "type": "WorkflowNode",
      "params": {
        "workflow_ref": "core/transform-json@1.0.0",
        "storage_mode": "scoped",
        "scope_prefix": "raw_data."
      }
    }
  ]
}
```

### Multi-Stage Analysis
```bash
# Compose workflows via CLI
pflow read-file report.md \
  >> workflow:extract-sections \
  >> workflow:analyze-each \
  >> workflow:generate-summary \
  >> write-file summary.md
```

## Conclusion

The workflow reference system extends pflow's capabilities while maintaining its core principles of simplicity, determinism, and transparency. By treating workflows as first-class reusable components, we enable powerful composition patterns that scale from simple automation to complex enterprise workflows.
