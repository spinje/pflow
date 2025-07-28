# Task 17 Discussion Synthesis: Clarifications and Resolutions

## Overview

This document synthesizes all clarifications, resolved ambiguities, and key insights from our comprehensive discussion about Task 17's Natural Language Planner implementation. These resolutions ensure the planner can be implemented without ambiguity while maintaining the "Plan Once, Run Forever" philosophy.

## Resolved Clarifications

### 1. Template Validation Timing Strategy

**Resolution**: Dual validation approach (Alternative 3 from the analysis document)

- **Planner validates** during workflow generation to enable retry/fixing
- **Runtime validates** as a safety check with actual execution parameters
- Both use the same `TemplateValidator` class for consistency

**Implementation Details**:
- ValidatorNode performs FULL validation after ParameterDiscoveryNode provides values
- Runtime re-validates with actual parameters as safety net
- Clear separation: planner asks "can this work?", runtime asks "will this work now?"

### 2. Two-Phase Parameter Extraction Architecture

**Resolution**: Implement two distinct parameter nodes with different purposes

#### ParameterDiscoveryNode (Path B only)
- **Purpose**: Extract raw values from natural language BEFORE workflow generation
- **When**: Early in Path B, after ComponentBrowsingNode
- **What it extracts**: Raw values without knowing final parameter names
  - "fix issue 1234" → extracts ["1234"]
  - "analyze report.pdf yesterday" → extracts ["report.pdf", "2024-01-15"]
- **Output**: Simple discovered values that GeneratorNode can use for context

#### ParameterMappingNode (Convergence point for both paths)
- **Purpose**: Map discovered/extracted values to workflow's expected parameters
- **When**: After workflow is found/generated, before execution
- **What it does**:
  - Maps raw values to template variable names
  - Verifies all required parameters are available
  - Routes to "params_incomplete" if missing parameters
- **Output**: Properly mapped parameter values for execution

### 3. Parameter Types Clarification

**Three distinct parameter concepts**:

1. **Node Configuration Parameters** (Registry)
   - Static configuration in node interface (e.g., `append: bool`)
   - Stored in registry under `interface.params`
   - Context builder shows only "exclusive params" not in Reads

2. **Initial Parameters** (Workflow-level)
   - Values extracted from natural language input
   - In MVP: Users NEVER type CLI syntax like `--issue=1234`
   - Everything comes through natural language: "fix issue 1234"
   - These become the `available_params` in validation

3. **Template Variables** (Runtime references)
   - Placeholders in workflow params: `$issue_number`, `$issue_data.title`
   - Resolved at runtime from initial params OR shared store
   - Enable workflow reusability

### 4. ValidatorNode Full Validation Capability

**Resolution**: ValidatorNode can perform FULL template validation

With ParameterDiscoveryNode providing extracted values BEFORE validation:
```python
def exec(self, prep_res):
    workflow = prep_res["workflow"]
    registry = prep_res["registry"]
    discovered_params = prep_res["discovered_params"]

    # 1. Structure validation
    validate_ir(workflow)

    # 2. FULL template validation
    errors = TemplateValidator.validate_workflow_templates(
        workflow,
        discovered_params,  # Values from ParameterDiscoveryNode
        registry
    )
```

This resolves the validation timing paradox completely.

### 5. Updated Path B Flow

The complete Path B (generation) flow with parameter discovery:

```
ComponentBrowsingNode: Find building blocks
↓
ParameterDiscoveryNode: Extract raw values ["1234", "pflow"]
↓
GeneratorNode: Generate workflow with context of available values
              Creates templates like $issue_number, $repo
↓
ValidatorNode: FULL validation (structure + templates)
↓
MetadataGenerationNode: Extract metadata from validated workflow
↓
ParameterMappingNode: Map "1234"→$issue_number, verify executability
                     Route to "params_incomplete" if missing
↓
ResultPreparationNode: Package for CLI
```

### 6. Missing Parameter Handling

**Resolution**: Unified approach for both paths

- If ParameterMappingNode detects missing parameters, it routes to "params_incomplete"
- ResultPreparationNode packages this information for CLI
- CLI prompts user for missing parameters
- This works identically whether workflow was found (Path A) or generated (Path B)

### 7. Node Output Key Behavior

**Clarification**: Nodes write to fixed keys based on their type, NOT their ID

- `github-get-issue` always writes to `shared["issue_data"]`
- Node IDs are for workflow clarity only
- No namespacing, no collision detection in MVP
- If same node type used multiple times, later overwrites earlier

### 8. Registry Access Pattern

**Clarification**: Registry CAN be accessed directly for validation

- Context builder is for discovery/browsing (LLM-friendly format)
- Registry can be accessed directly for validation and metadata
- This enables proper template validation using actual node interfaces

### 9. Complete Workflow Match Definition

**Clarification**: WorkflowDiscoveryNode matches based on INTENT, not parameter availability

- "fix github issue" matches "fix-issue" workflow even without issue number
- Parameter availability is checked later by ParameterMappingNode
- Enables workflow reuse with different parameters

### 10. MVP Natural Language Focus

**Critical context**: In MVP, ALL input goes through natural language

- No CLI parameter syntax from users (`--issue=1234`)
- Planner extracts all values from natural language
- Future versions will support direct CLI parameters
- This affects how we think about "initial_params"

## Key Architectural Insights

### The Validation Flow

1. **ParameterDiscoveryNode** provides raw extracted values
2. **GeneratorNode** creates workflow with template variables
3. **ValidatorNode** validates using discovered params (not final mapped params)
4. **ParameterMappingNode** does final mapping and availability check

### Template Variable Resolution

Templates are resolved from TWO sources at runtime:
- **Initial parameters**: Values provided to workflow (from planner extraction)
- **Node outputs**: Values written to shared store during execution

The validator checks BOTH sources to ensure all templates can be resolved.

### Separation of Concerns

- **Planner**: Generates workflows and prepares them for execution
- **Runtime**: Executes workflows with parameter substitution
- **Validation**: Happens at both levels with different purposes

## Implementation Implications

1. **Node Ordering**: ParameterDiscoveryNode MUST come before GeneratorNode in Path B
2. **Shared State**: discovered_params must be passed through the flow
3. **Validation Scope**: ValidatorNode does full validation, not partial
4. **Error Routing**: Both paths converge at ParameterMappingNode for missing param handling
5. **Template Freedom**: GeneratorNode can use any variable names that make sense

## Future Considerations

These clarifications set up clean paths for future enhancements:
- Direct CLI parameter support (post-MVP)
- Proxy mappings for collision handling (v2.0)
- More sophisticated parameter discovery
- Workflow composition patterns

The architecture now supports all these without fundamental changes.
