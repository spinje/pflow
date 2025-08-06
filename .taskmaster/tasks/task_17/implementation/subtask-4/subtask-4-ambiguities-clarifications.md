# GeneratorNode Implementation Guide - Final Decisions

## Core Understanding: The Parameter Flow Architecture

### The Correct Mental Model

```
ParameterDiscoveryNode
    ↓
Provides hints: {"filename": "report.csv", "limit": "20"}
    ↓
GeneratorNode (YOU HAVE COMPLETE FREEDOM HERE)
    ↓
Creates inputs field: {"input_file": {...}, "max_items": {...}}
    ↓
Uses templates: "$input_file", "$max_items"
    ↓
ParameterMappingNode
    ↓
Extracts "input_file" and "max_items" from user input (NOT "filename" and "limit")
```

**Critical Insight**: discovered_params are just hints about what parameters might exist. GeneratorNode has complete control over the inputs specification and template variable names.

## MVP Scope & Limitations

### What IS Supported
- Simple linear workflows (A → B → C)
- Single workflow-as-node composition
- Basic parameter extraction and mapping
- Template variables with simple paths ($var, $var.field)

### What is NOT Supported (MVP)
- ❌ Branching or conditional edges
- ❌ Error handling edges
- ❌ Retry loops
- ❌ Multiple nodes of the same type (shared store collision - Task 9 not implemented)
- ❌ Complex workflow patterns

## Design Decisions

### 1. Empty Planning Context Handling
**Decision**: Planning context should always be available. If not, it's an error.

```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    if not prep_res["planning_context"]:
        raise ValueError("Planning context is required but was empty")

    # Normal flow - planning_context is always available
    prompt = self._build_prompt(prep_res["planning_context"])
```

### 2. Parameter to Inputs Mapping
**Decision**: GeneratorNode has full control over the inputs specification.

The GeneratorNode can:
- **Rename parameters** for better clarity
- **Decide required vs optional** based on the parameter's nature
- **Add parameters** that weren't discovered but are needed
- **Omit parameters** that were discovered but aren't necessary

#### When to Make Parameters Optional (with defaults)

Make a parameter optional when:
- It's a **preference setting** (verbose, format)
- It has a **universally sensible default** (encoding="utf-8")
- The workflow **can function without it**
- It's for **advanced users**

Keep parameters required when:
- It's **critical to the operation** (input file, API key, repository name)
- The default would be **request-specific** (not universal)
- Different users would **expect different values**

```python
# discovered_params might have: {"filename": "report.csv", "limit": "20"}

# GeneratorNode creates better structure:
"inputs": {
    "input_file": {
        "description": "File to process",
        "required": True,  # Critical - no default
        "type": "string"
    },
    "max_items": {
        "description": "Maximum number of items",
        "required": False,  # Optional with universal default
        "type": "integer",
        "default": 10  # Universal default, NOT the discovered "20"!
    },
    "format": {
        "description": "Output format",
        "required": False,  # Preference with sensible default
        "type": "string",
        "default": "json"
    }
}

# Templates must match the inputs keys (not discovered_params):
"params": {"path": "$input_file", "limit": "$max_items", "format": "$format"}
```

### 3. Template Variable Naming
**Decision**: Template variables must match inputs field keys, NOT discovered_params.

- ✅ GeneratorNode renames for clarity: `filename` → `input_file`
- ✅ Templates use: `$input_file`
- ✅ ParameterMappingNode looks for: `input_file`

### 4. Workflow Composition
**Decision**: Use workflows as nodes with proper mapping.

The workflow names come from ComponentBrowsingNode's discovery of saved workflows in `~/.pflow/workflows/`. Use `workflow_name` (not `workflow_ref` or `workflow_ir`) to reference them.

```python
{
    "id": "analyze_text",
    "type": "workflow",
    "params": {
        "workflow_name": "text-analyzer",  # Name from browsed_components["workflow_names"]
        "param_mapping": {
            "text": "$document_content"  # Map parent param to child input
        },
        "output_mapping": {
            "analysis": "text_analysis"  # Map child output back to parent
        },
        "storage_mode": "mapped"  # Recommended default for isolation
    }
}
```

**Key Points**:
- Use `workflow_name` for saved workflows discovered by ComponentBrowsingNode
- Always include `param_mapping` to connect parent parameters to child workflow inputs
- Include `output_mapping` to extract specific outputs back to parent context
- Use `"storage_mode": "mapped"` for safety (isolates child from parent shared store)

### 5. Progressive Enhancement Strategy
**Decision**: Fix specific errors only (Option C - no progressive simplification).

On retry, focus ONLY on fixing the specific validation errors reported. Do not simplify the workflow or reduce complexity unless the error specifically requires it.

```python
if self.cur_retry > 0 and validation_errors:
    # Focus ONLY on fixing the specific errors - don't simplify
    prompt += f"\nThe previous attempt failed validation. Fix ONLY these specific issues:\n"
    for error in validation_errors[:3]:
        prompt += f"- {error}\n"
    prompt += "\nKeep the rest of the workflow unchanged."
```

### 6. Workflow Complexity
**Decision**: LINEAR WORKFLOWS ONLY for MVP.

```python
# ✅ ALLOWED - Simple linear flow:
"nodes": [
    {"id": "fetch", "type": "github-list-issues"},
    {"id": "process", "type": "llm"},
    {"id": "save", "type": "write-file"}
],
"edges": [
    {"from": "fetch", "to": "process"},
    {"from": "process", "to": "save"}
]

# ❌ NOT ALLOWED - Branching:
"edges": [
    {"from": "fetch", "to": "process"},
    {"from": "fetch", "to": "error_handler", "action": "error"}  # NO!
]
```

### 7. exec_fallback Behavior
**Decision**: Return error information for CLI to handle.

```python
def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
    logger.error(f"GeneratorNode failed: {exc}")
    return {
        "success": False,
        "error": str(exc),
        "workflow": None  # No fallback workflow
    }
```

### 8. Default Values in Inputs
**Decision**: Use LLM judgment - if confident a default is universally appropriate, use it.

The LLM should use its judgment about defaults. When the LLM feels confident that a parameter value would make a good universal default (not request-specific), it should include it. Most parameters should still be required.

```python
"inputs": {
    "file_path": {
        "required": True  # Critical - no default
    },
    "encoding": {
        "required": False,
        "default": "utf-8"  # Universal default - LLM confident this is sensible
    },
    "verbose": {
        "required": False,
        "default": False  # Preference - LLM judges this as good default
    },
    "limit": {
        "required": True  # Even though user said "20", don't use as default
        # The "20" was specific to THIS request, not universal
    }
}
```

**Key Principle**: The discovered value (like "20" for limit) should NOT become the default. Defaults must be universally sensible, not request-specific.

### 9. Model Configuration
**Decision**: Follow standard pattern (no changes from analysis).

```python
def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
    model_name = self.params.get("model", "anthropic/claude-sonnet-4-0")
    temperature = self.params.get("temperature", 0.0)
```

### 10. Node ID Strategy
**Decision**: Descriptive names, but avoid multiple nodes of same type (MVP limitation).

#### Understanding ID vs Type

- **`id`**: The unique instance identifier within the workflow (e.g., "fetch_issues", "analyze_data")
- **`type`**: The node class to instantiate (e.g., "github-list-issues", "llm", "read-file")

IDs are what edges reference, types determine what code runs:
```python
"nodes": [
    {"id": "fetch_issues", "type": "github-list-issues"},
    {"id": "analyze", "type": "llm"},
    {"id": "summarize", "type": "llm"}  # Same type, different ID
],
"edges": [
    {"from": "fetch_issues", "to": "analyze"},  # References by ID
    {"from": "analyze", "to": "summarize"}
]
```

#### MVP Limitation: Shared Store Collision

Without Task 9's proxy mapping, multiple nodes of the same type will overwrite each other's shared store values:

```python
# ⚠️ PROBLEM in MVP - Multiple same type causes collision:
"nodes": [
    {"id": "read_input", "type": "read-file"},   # Writes to shared["content"]
    {"id": "read_config", "type": "read-file"}   # OVERWRITES shared["content"]!
]

# ✅ WORKAROUND for MVP - Avoid multiple same type or ensure sequential consumption:
"nodes": [
    {"id": "read_data", "type": "read-file"},
    {"id": "process", "type": "llm"},  # Consumes content before next read
    {"id": "read_more", "type": "read-file"}  # Now safe to overwrite
]
```

**For MVP**: Prefer avoiding multiple nodes of the same type until Task 9 implements proxy mapping.

### 11. Validation Error Format
**Decision**: Handle both formats (no changes from analysis).

### 12. Registry Metadata Usage
**Decision**: Completely ignore registry_metadata - it's not needed.

```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    # ONLY use planning_context for ALL component information
    prompt = self._build_prompt(prep_res["planning_context"])

    # COMPLETELY IGNORE registry_metadata:
    # - Don't use it for validation (ValidatorNode does that)
    # - Don't use it as fallback (planning_context is required)
    # - Don't even check if nodes exist (trust planning_context)
```

The ComponentBrowsingNode → context_builder → GeneratorNode pipeline works as a unit. If planning_context is empty, that's an exceptional error to be handled by exec_fallback.

## Implementation Patterns

### The Complete Parameter Flow

```python
# Step 1: Hints from discovery
discovered_params = {"filename": "data.csv", "maxItems": "50"}

# Step 2: GeneratorNode creates better structure
"inputs": {
    "data_file": {  # Renamed for clarity
        "description": "Input data file",
        "required": True,
        "type": "string"
    },
    "limit": {  # Renamed from maxItems
        "description": "Maximum items to process",
        "required": False,
        "type": "integer",
        "default": 100  # Universal default, not 50
    }
}

# Step 3: Templates match inputs keys
"params": {
    "input": "$data_file",  # Matches inputs key
    "max": "$limit"         # Matches inputs key
}

# Step 4: ParameterMappingNode extracts "data_file" and "limit"
```

### Linear Workflow Generation

```python
def _generate_linear_workflow(self, nodes_info: list[dict]) -> dict:
    """Generate a simple linear workflow."""

    nodes = []
    edges = []

    for i, node_info in enumerate(nodes_info):
        node_id = self._generate_descriptive_id(node_info)
        nodes.append({
            "id": node_id,
            "type": node_info["type"],
            "params": node_info.get("params", {})
        })

        # Linear edges only
        if i > 0:
            edges.append({
                "from": nodes[i-1]["id"],
                "to": node_id
            })

    return {"nodes": nodes, "edges": edges}
```

## Critical Implementation Rules

### MUST Follow
1. Planning context must be available (error if not)
2. Generate LINEAR workflows only (no branching)
3. Template variables must match inputs field keys
4. Avoid multiple nodes of same type (shared store collision)
5. Use workflow_name for saved workflows

### SHOULD Follow
6. Rename parameters for clarity when it improves understanding
7. Mark most parameters as required
8. Use defaults only for universal values
9. Fix specific validation errors on retry

### DON'T Do
10. Don't create fallback workflows in exec_fallback
11. Don't use registry_metadata at all
12. Don't generate complex workflow patterns
13. Don't use discovered param values as defaults

## Common Pitfalls to Avoid

### ❌ Wrong: Treating discovered_params as requirements
```python
# WRONG - Too rigid
for param in discovered_params:
    inputs[param] = {...}  # Must use exact name
```

### ✅ Right: Using discovered_params as hints
```python
# RIGHT - Freedom to improve
if "filename" in discovered_params:
    inputs["input_file"] = {...}  # Better name
```

### ❌ Wrong: Multiple nodes of same type
```python
# WRONG - Causes collision
{"id": "read1", "type": "read-file"},
{"id": "read2", "type": "read-file"}  # Overwrites shared["content"]
```

### ✅ Right: Different node types or sequential consumption
```python
# RIGHT - Different types
{"id": "read", "type": "read-file"},
{"id": "process", "type": "llm"}
```

## Summary

The GeneratorNode is the architect of the workflow, with complete freedom to:
- Define the inputs specification with clear, descriptive names
- Choose which parameters are required vs optional
- Set universal defaults where appropriate
- Create simple, linear workflows that accomplish the user's goal

Remember: discovered_params are hints, not requirements. The inputs field you create becomes the contract that ParameterMappingNode will verify.
