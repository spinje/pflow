# Handoff to Subtask 4: Generation System

**⚠️ CRITICAL: Read this before starting. The convergence architecture is now complete.**

## 🎯 What Parameter Management Provides You

### The Convergence Point is Ready
**ParameterMappingNode** is THE verification gate where both paths meet:
- It performs INDEPENDENT extraction (doesn't trust discovered_params)
- It validates against workflow_ir["inputs"] specification
- It routes "params_complete" or "params_incomplete"
- Both Path A and Path B converge here successfully

### What Your GeneratorNode Will Receive (Path B)
When you implement the GeneratorNode, you'll have access to:
- `shared["discovered_params"]` - Parameter hints from ParameterDiscoveryNode
  - Example: `{"filename": "report.csv", "limit": "20"}`
  - Use these as context to create appropriate template variables
- `shared["browsed_components"]` - Selected nodes and workflows
- `shared["planning_context"]` - Detailed markdown (or empty string on error)
- `shared["registry_metadata"]` - Full registry for validation

### What You Must Provide for ParameterMappingNode
Your GeneratorNode must write to shared store:
- `shared["generated_workflow"]` - The complete workflow IR
  - Must include `inputs` field with parameter specifications
  - Example structure:
```python
{
    "inputs": {
        "filename": {
            "description": "Input file to process",
            "required": True,
            "type": "string"
        },
        "limit": {
            "description": "Maximum items",
            "required": False,
            "type": "integer",
            "default": 10
        }
    },
    "nodes": [...],  # Use template variables: $filename, $limit
    "edges": [...]
}
```

## 🚨 Critical Patterns You MUST Follow

### 1. Template Variables Are Sacred
```python
# ✅ CORRECT - Use template variables
"params": {"file": "$filename", "count": "$limit"}

# ❌ WRONG - Never hardcode extracted values
"params": {"file": "report.csv", "count": "20"}
```

### 2. The inputs Field is the Contract
ParameterMappingNode validates against workflow_ir["inputs"]:
- Each input has: description, required, type, and optional default
- ParameterMapping will verify ALL required inputs have values
- Missing required params trigger "params_incomplete" routing

### 3. Use discovered_params as Context, Not Truth
```python
# discovered_params provides hints about what parameters exist
# But ParameterMappingNode will do its own extraction for verification
# This independence is BY DESIGN - it's the verification gate
```

## 🔧 Patterns We've Established

### LLM Response Pattern (MUST USE)
```python
# The _parse_structured_response() helper is available
structured_data = self._parse_structured_response(response, YourModel)

# Or implement directly:
response_data = response.json()
if response_data is None:
    raise ValueError("LLM returned None response")
result = response_data['content'][0]['input']  # Anthropic nests here!
```

### Lazy Model Loading (REQUIRED)
```python
def exec(self, prep_res):
    model = llm.get_model(prep_res["model_name"])  # In exec, not __init__
    temperature = prep_res.get("temperature", 0.0)
```

### Node Naming Convention
```python
name = "generator"  # For registry discovery
```

## 📁 Files You'll Work With

### Add Your Node Here
- `/Users/andfal/projects/pflow/src/pflow/planning/nodes.py`
  - All nodes in one file (PocketFlow pattern)
  - ParameterDiscoveryNode at line 505
  - ParameterMappingNode at line 699 (convergence point)
  - ParameterPreparationNode at line 944

### Test Files to Extend
- `/Users/andfal/projects/pflow/tests/test_planning/unit/` - For isolated unit tests
- `/Users/andfal/projects/pflow/tests/test_planning/integration/` - For multi-component integration tests
- `/Users/andfal/projects/pflow/tests/test_planning/llm/` - For real LLM API tests

Note: We've reorganized tests for clarity:
- `unit/` contains only isolated single-component tests
- `integration/` contains multi-component tests with mocked LLM
- `llm/` contains tests requiring real LLM API calls

### Pydantic Models Available
- `ir_models.py` has FlowIR, NodeIR, EdgeIR models
- Add any generation-specific models to nodes.py

## 🐛 Things That Will Save You Hours

1. **Planning context can be empty string** - Check for empty, not just existence
2. **The nested LLM response** - Always use content[0]['input'] pattern
3. **Workflow IR structure** - The inputs field is critical for parameter validation
4. **discovered_params is optional context** - Generator should work even without it
5. **Template variable preservation** - NEVER replace $var with actual values
6. **Boolean values in Python** - Use True/False (becomes true/false in JSON)

## 📚 Critical Documentation

### Must Read
- **Your spec**: `.taskmaster/tasks/task_17/starting-context/specs/task-17-subtask-4-spec.md`
- **Implementation guide**: `.taskmaster/tasks/task_17/starting-context/task-17-implementation-guide.md`
- **Core concepts**: `.taskmaster/tasks/task_17/starting-context/task-17-core-concepts.md`

### Understanding the Flow
Path B: Discovery → Browsing → **Parameter Discovery** → **[YOUR GENERATOR]** → Validation → Metadata → **Parameter Mapping** → Preparation → Result

Your GeneratorNode sits between parameter discovery (hints) and parameter mapping (verification).

## 🎭 The Two-Phase Parameter Architecture

We've implemented sophisticated two-phase parameter handling:

1. **Phase 1 (Discovery)**: ParameterDiscoveryNode extracts hints
   - Provides context for your generator
   - Helps you know what template variables to create

2. **Phase 2 (Mapping)**: ParameterMappingNode verifies independently
   - Doesn't trust discovered_params
   - Validates against your workflow's inputs field
   - This independence ensures workflows are actually executable

Your generator bridges these phases by using discovered hints to create appropriate template variables.

## 🔮 What Success Looks Like

Your GeneratorNode should:
1. Use discovered_params as hints for what parameters exist
2. Create workflows with template variables ($var syntax)
3. Define clear inputs field with parameter specifications
4. Handle cases where discovered_params is empty
5. Support progressive enhancement on validation failures

## 💡 Key Insight

The parameter management system is designed for reliability through independence. ParameterDiscoveryNode provides hints to help generation, but ParameterMappingNode independently verifies executability. This dual approach ensures that every workflow - whether generated or reused - can actually run with the user's input.

Your generator is the creative engine that turns browsed components and parameter hints into executable workflows. The convergence architecture we've built ensures your generated workflows will be properly validated and parameterized.

## 📋 Testing Your Integration

Use North Star examples (generate-changelog, issue-triage-report, etc.) in your tests for consistency across Task 17.

When testing with ParameterMappingNode:
```python
# Your generator creates workflow
shared["generated_workflow"] = {
    "inputs": {"file": {"required": True, "type": "string"}},
    "nodes": [{"id": "n1", "params": {"path": "$file"}}],
    ...
}

# ParameterMappingNode will verify independently
# It extracts "file" value from user_input
# Routes "params_complete" if found, "params_incomplete" if missing
```

---

*Good luck with the Generation System! The convergence architecture is ready for your creative workflows.*
