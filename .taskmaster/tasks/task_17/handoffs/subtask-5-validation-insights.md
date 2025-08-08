# Subtask 5: Validation & Refinement System - Implementation Insights

**Critical Document**: Read this before implementing ValidatorNode and MetadataGenerationNode. This captures essential clarifications and discoveries that override or clarify the original specs.

## 🚨 Critical Realizations

### 1. ValidatorNode CANNOT Detect "Hardcoded Values"

**The Misconception**: The handoff document emphasizes catching "hardcoded values that should be templates."

**The Reality**: ValidatorNode has NO ACCESS to discovered_params and CANNOT determine if a value "should have been" a template variable. It only sees the generated workflow IR.

**What This Means**:
- ❌ CANNOT validate: "This should have been `$repo_name` instead of 'pflow'"
- ✅ CAN validate: "Is `$repo_name` resolvable from available sources?"
- ✅ CAN validate: "Are all declared inputs actually used?"

### 2. Template Variable Resolution Sources

**Template variables can be resolved from TWO sources** (in priority order):
1. **initial_params** (HIGH priority) - Parameters extracted by ParameterMappingNode from user query
2. **shared store** (LOW priority) - Including:
   - Node outputs from previous nodes
   - Stdin data (`$stdin`)
   - Any runtime data in shared store

**Key Insight**: The workflow's `inputs` field declares what ParameterMappingNode should extract into `initial_params`.

### 3. The Parameter Extraction Flow

Understanding this flow is CRITICAL for validation:

```
Path B Flow:
1. User Input: "fetch last 20 closed issues from pflow repo"
   ↓
2. ParameterDiscoveryNode: Extracts hints {"state": "closed", "limit": "20", "repo": "pflow"}
   ↓ (These are ONLY suggestions/context for the generator)
3. GeneratorNode: Creates workflow with its OWN inputs field:
   "inputs": {
     "repository": {...},    # Generator chose different names!
     "max_count": {...}      # These are the CONTRACT
   }
   ↓
4. ValidatorNode: Validates the workflow (our job!)
   ↓
5. ParameterMappingNode: INDEPENDENTLY extracts "repository" and "max_count" from original query
```

**Critical**: The generator has FULL CONTROL over the inputs field. The discovered_params are just hints.

## 🎯 What ValidatorNode Should Actually Do

### ValidatorNode is an ORCHESTRATOR, not a monolithic validator:

1. **Call existing validators**:
   - `validate_ir()` - For structural JSON schema validation
   - `TemplateValidator.validate_workflow_templates()` - For template resolution validation

2. **Add missing validations**:
   - **Node types exist** - Validate against registry (NOT done by existing validators)
   - **Format errors for retry** - Top 3 actionable errors for generator

3. **Things it should NOT do**:
   - ❌ Detect "hardcoded values" (impossible without discovered_params)
   - ❌ Enforce linear workflows (generator won't add branching unless prompted)
   - ❌ Duplicate existing validation logic

## 📊 Existing Validation Landscape

### What's Already Implemented:

| Validator | What It Does | Location |
|-----------|-------------|----------|
| `validate_ir()` | JSON schema, node ID uniqueness, edge integrity | `pflow/core/ir_schema.py` |
| `TemplateValidator` | Template syntax, resolution from sources, path validation | `pflow/runtime/template_validator.py` |
| `WorkflowValidator` | Input preparation, applies defaults | `pflow/runtime/workflow_validator.py` |

### What's Missing (Must Be Added):

1. **Unused Inputs Validation** ⚠️
   - Declared inputs that are never used as `$variables`
   - **Decision**: Add to TemplateValidator (it has all the data)
   - This catches clear generator bugs

2. **Node Type Validation**
   - Check all node types exist in registry
   - Generator trusts planning_context but might have typos

## 🔧 Implementation Strategy

### Step 1: Enhance TemplateValidator

Add unused inputs validation to `TemplateValidator.validate_workflow_templates()`:

```python
# Pseudocode for the enhancement
def validate_workflow_templates(workflow, initial_params, registry):
    errors = []

    # Existing: Extract all template variables
    template_vars = self._extract_all_templates(workflow)

    # NEW: Check for unused inputs
    declared_inputs = set(workflow.get("inputs", {}).keys())
    used_inputs = {var.split('.')[0] for var in template_vars
                   if var.split('.')[0] in declared_inputs}
    unused_inputs = declared_inputs - used_inputs

    if unused_inputs:
        errors.append(f"Workflow declares input(s) that are never used: {', '.join(sorted(unused_inputs))}")

    # Existing: Continue with template resolution validation...
    return errors
```

### Step 2: Implement ValidatorNode

```python
class ValidatorNode(Node):
    """Orchestrates validation for generated workflows."""

    def __init__(self):
        super().__init__()
        self.registry = Registry()  # Direct instantiation per PocketFlow pattern

    def exec(self, prep_res):
        workflow = prep_res["workflow"]
        errors = []

        # 1. Structural validation
        try:
            validate_ir(workflow)
        except ValidationError as e:
            errors.append(f"Structure: {e}")

        # 2. Template validation (includes unused inputs after enhancement)
        template_errors = TemplateValidator.validate_workflow_templates(
            workflow,
            {},  # No initial_params at generation time
            self.registry
        )
        errors.extend(template_errors)

        # 3. Node type validation (NEW)
        for node in workflow.get("nodes", []):
            if node["type"] not in self.registry.get_nodes_metadata():
                errors.append(f"Unknown node type: '{node['type']}'")

        # Return top 3 most actionable errors
        return {
            "valid": len(errors) == 0,
            "errors": errors[:3]  # Limit for LLM retry
        }
```

### Step 3: Implement MetadataGenerationNode

Only runs after successful validation. Extracts workflow metadata for saving.

## ⚠️ Common Pitfalls to Avoid

1. **Don't try to detect "hardcoded values"** - You can't know what "should" be parameterized
2. **Don't validate discovered_params** - You don't have access to them
3. **Don't enforce linear workflows** - Generator won't branch unless prompted
4. **Don't duplicate existing validation** - Use the existing validators
5. **Don't validate empty inputs as error** - Valid for simple workflows

## 🧪 Testing Strategy

### Critical Test Cases:

1. **Unused inputs detection**:
   ```python
   # Workflow declares "repo_name" but never uses it
   workflow = {
       "inputs": {"repo_name": {...}, "limit": {...}},
       "nodes": [{"params": {"count": "$limit"}}]  # repo_name never used!
   }
   # Should fail with "Workflow declares input(s) that are never used: repo_name"
   ```

2. **Node type validation**:
   ```python
   # Typo in node type
   workflow = {
       "nodes": [{"type": "github-list-issuez"}]  # Typo!
   }
   # Should fail with "Unknown node type: 'github-list-issuez'"
   ```

3. **Template resolution from both sources**:
   ```python
   # Valid: Templates from inputs AND node outputs
   workflow = {
       "inputs": {"repo": {...}},
       "nodes": [
           {"id": "fetch", "type": "github-list-issues", "params": {"repo": "$repo"}},
           {"id": "analyze", "type": "llm", "params": {"data": "$issues"}}  # From node output
       ]
   }
   ```

### Real LLM Testing:

The generator has 21 real LLM tests. ValidatorNode needs real LLM tests too for:
- Retry mechanism with actual error feedback
- Ensuring errors lead to successful retry
- Validation of real generated workflows

## 📝 Summary for Implementation

1. **First**: Enhance TemplateValidator with unused inputs validation
2. **Second**: Implement ValidatorNode as an orchestrator
3. **Third**: Implement MetadataGenerationNode for metadata extraction
4. **Throughout**: Focus on executable validation, not design judgment

The validator is a safety net for EXECUTION issues, not a critic of parameterization choices.

## 🔗 Key Files to Reference

- Generator implementation: `src/pflow/planning/nodes.py:1028-1236`
- Template validator: `src/pflow/runtime/template_validator.py`
- IR validation: `src/pflow/core/ir_schema.py`
- Registry: `src/pflow/registry/registry.py`
- Test examples: `tests/test_planning/llm/behavior/test_generator_core.py`

---

*This document captures the essential clarifications that fundamentally change how Subtask 5 should be implemented. The validator's role is simpler than originally described but still critical for ensuring workflow quality.*