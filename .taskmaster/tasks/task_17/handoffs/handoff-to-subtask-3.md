# Handoff to Subtask 3: Parameter Management System

**⚠️ CRITICAL: Read this entire memo before starting. I discovered things that will save you hours.**

## 🎯 Core Outcomes You're Building On

### What Discovery Nodes Provide You
- **Path B arrives at your ParameterDiscoveryNode with**:
  - `shared["browsed_components"]` - Dict with `node_ids` and `workflow_names` lists
  - `shared["planning_context"]` - Detailed markdown OR empty string (if error occurred)
  - `shared["registry_metadata"]` - Full registry dict for validation
  - `shared["user_input"]` - Original natural language request

### What Both Paths Need From You
Your ParameterMappingNode is the **convergence point** where both paths meet:
- **Path A**: Has `shared["found_workflow"]` with full metadata
- **Path B**: Has generated workflow (will be in shared by the time it reaches you)
- **Both need**: Extracted parameters mapped to workflow inputs

## 🚨 Critical Discoveries That Will Bite You

### 1. LLM Structured Response is NESTED (MUST HANDLE)
```python
# ❌ WRONG - This will fail mysteriously
response = model.prompt(prompt, schema=YourModel)
data = response.json()  # This is NOT your data!

# ✅ CORRECT - Anthropic nests the data
response = model.prompt(prompt, schema=YourModel)
response_data = response.json()
if response_data is None:
    raise ValueError("LLM returned None response")
structured_data = response_data['content'][0]['input']  # HERE!
```

I wasted time debugging this. The `_parse_structured_response()` helper in nodes.py (line 153) handles this - **reuse it**.

### 2. Models MUST Be Lazy-Loaded
```python
# ❌ NEVER do this in __init__
self.model = llm.get_model("anthropic/claude-sonnet-4-0")

# ✅ Always in exec()
model = llm.get_model(prep_res["model_name"])
```

Models are configured via params now:
- `self.params.get("model", "anthropic/claude-sonnet-4-0")`
- `self.params.get("temperature", 0.0)`

### 3. Planning Context Can Be Error Dict
ComponentBrowsingNode writes `shared["planning_context"]` as either:
- String (markdown) on success
- Empty string if `build_planning_context()` returned error dict

Check for empty string, not just existence.

## 🔧 Patterns to Reuse

### Input Validation Pattern (FOLLOW THIS)
```python
def prep(self, shared):
    # Data flow: shared store first, then params fallback
    user_input = shared.get("user_input") or self.params.get("user_input", "")
    if not user_input:
        raise ValueError("Missing required 'user_input' in shared store or params")
```

### Available Helper Method
The `_parse_structured_response()` method at line 153 and 377 (duplicated) handles Anthropic's nested response. Consider extracting to module level or reusing.

## ⚠️ Architectural Constraints

### Your Role in the Convergence
**ParameterMappingNode is special** - it's where both paths converge:
- Must handle workflows from both Path A (found) and Path B (generated)
- Must do **INDEPENDENT EXTRACTION** - don't rely on discovered_params
- This independence makes you a verification gate

### Action Strings You Must Use
- ParameterDiscoveryNode: Returns to generator (Path B continues)
- ParameterMappingNode: `"params_complete"` or `"params_incomplete"`

## 📁 Critical Files & Code

### Your Node Implementations Go Here
- `/Users/andfal/projects/pflow/src/pflow/planning/nodes.py` - Add your nodes to this file (all nodes in one file)

### Models You'll Need
- `WorkflowDecision` and `ComponentSelection` are in nodes.py
- You'll need to create your own Pydantic models for parameter structures

### Test File to Update
- `/Users/andfal/projects/pflow/tests/test_planning/test_discovery.py` - Will need renaming to test_planning_nodes.py or create test_parameters.py

### Context Builder Functions
- Already imported in nodes.py, just use them
- `build_planning_context()` can return error dict with "error" key - handle it!

## 🐛 Subtle Issues to Avoid

1. **Don't trust discovered_params in ParameterMappingNode** - The spec emphasizes INDEPENDENT extraction for verification
2. **Empty planning_context is valid** - Don't fail, just work with what you have
3. **Template variables are sacred** - Never replace $var with actual values in workflows
4. **Test lazy loading** - Your tests must verify model is loaded in exec(), not __init__

## 📚 Invaluable Documentation

### Must Read First
- **Your spec**: `.taskmaster/tasks/task_17/starting-context/specs/task-17-subtask-3-spec.md`
- **Overall architecture**: `.taskmaster/tasks/task_17/starting-context/task-17-architecture-and-patterns.md`
- **Core concepts**: `.taskmaster/tasks/task_17/starting-context/task-17-core-concepts.md` (especially parameter extraction section)

### PocketFlow Patterns
- Look at existing nodes for patterns: `/Users/andfal/projects/pflow/src/pflow/nodes/llm/llm_node.py`
- Test patterns: Use mock_llm_with_schema fixture from conftest.py

## 🎭 Context About Parameter Extraction

The architecture has **two-phase parameter handling**:
1. **ParameterDiscoveryNode** (Path B only): Extracts named parameters from natural language BEFORE generation
2. **ParameterMappingNode** (Both paths): INDEPENDENTLY extracts values for workflow's defined inputs

This independence is BY DESIGN - it makes ParameterMappingNode a verification gate that ensures the workflow is actually executable.

## 🔮 What I'd Be Furious About Not Knowing

1. The nested LLM response pattern - you'll waste hours if you don't know
2. The lazy loading requirement - tests will fail mysteriously
3. The fact that ParameterMappingNode does INDEPENDENT extraction, not reusing discovered_params
4. That planning_context can be empty string (not missing, just empty)
5. That all nodes go in the single nodes.py file
6. That you must preserve template variables ($var) - never replace with values

## 💡 Final Insight

Your nodes are the bridge between discovery and generation. ParameterDiscoveryNode provides context to help the generator, but ParameterMappingNode is the gatekeeper that ensures workflows are actually executable. This dual approach is the key to the planner's reliability.

The discovery nodes are now exemplary implementations - follow their patterns for consistency.

---

*Good luck with the Parameter Management System! The convergence architecture is elegant once you understand it.*
