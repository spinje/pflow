# Task 17 Implementation Summary

## Core Requirements

Task 17 implements the Natural Language Planner - a meta-workflow that transforms user intent into executable workflows.

### Architecture
- Implemented as a PocketFlow workflow (not regular Python)
- Lives in `src/pflow/planning/` with nodes.py + flow.py pattern
- Two paths that converge: Path A (reuse existing) and Path B (generate new)

## Critical Decisions Discovered

### 1. Context Builder API Extension (Blocker)
**Need**: Public methods to access workflow metadata after LLM selection
**Solution**: Add minimal public methods:
```python
def get_workflow_metadata(workflow_name: str) -> Optional[dict]
def get_all_workflows_metadata() -> list[dict]
```

### 2. Workflow Reference Resolution (Blocker)
**Problem**: Name-based discovery vs file-based execution mismatch
**Current**: WorkflowExecutor requires file paths, doesn't expand ~
**Recommendation**: Create WorkflowManager (aligns with planned Task 24)

### 3. Workflow Input/Output Declarations (Critical Gap)
**Problem**: Task 21 only adds input declarations, but outputs are needed too
**Current State**:
- Metadata level: Simple string lists
- IR level: Task 21 adding detailed inputs only
- Runtime: No validation against reality
**Recommendation**: Expand Task 21 to include both inputs AND outputs in IR

### 4. WorkflowManager Design (Architectural Need)
**Need**: Centralized workflow lifecycle management
**Functions**:
- Save workflows after approval
- Load by name for execution
- Resolve names to paths
- List all for discovery
**Note**: Already planned as Task 24

## Implementation Dependencies

### Must Have Before Task 17:
1. Context builder public methods (minimal change)
2. Workflow reference strategy (WorkflowManager or workaround)

### Should Have:
1. Task 21 expanded to include outputs
2. WorkflowManager (Task 24) for clean architecture

### Nice to Have:
1. WorkflowExecutor tilde expansion (enables portable paths)

## The Planner Flow

### Path A: Reuse Existing Workflow
1. WorkflowDiscoveryNode finds complete match
2. get_workflow_metadata() retrieves IR (needs public method)
3. ParameterMappingNode validates parameters
4. Return workflow to CLI

### Path B: Generate New Workflow
1. ComponentBrowsingNode selects nodes/workflows
2. ParameterDiscoveryNode extracts parameters from NL
3. GeneratorNode creates IR with template variables
4. ValidatorNode checks structure and templates
5. MetadataGenerationNode extracts name/description
6. ParameterMappingNode validates parameters
7. Return workflow to CLI

## Key Insights

### 1. Workflow Composition Enabled
Task 20's WorkflowExecutor allows workflows to use other workflows via `type: "workflow"`. The planner can leverage this for sophisticated compositions.

### 2. Metadata vs Contract
- IR should contain the contract (inputs/outputs with types)
- Metadata should be derived (timestamps, costs, versions)
- Single source of truth prevents confusion

### 3. Name-Based Mental Model
Users and the planner think in workflow names, not file paths. The system should support this natural mental model.

## Recommended Implementation Order

1. **Immediate**: Add public methods to context builder
2. **Next**: Design WorkflowManager interface (even if basic)
3. **Then**: Implement planner with workarounds documented
4. **Future**: Complete Task 21 with outputs, full Task 24

## Critical User Decisions Needed

1. **Context Builder API Extension** - Add public methods?
2. **Workflow Reference Resolution** - How to handle name→path?
3. **Workflow Output Declarations** - Expand Task 21?
4. **WorkflowManager Design** - Minimal or full featured?

## Summary

Task 17 is implementable with minimal changes to context builder and a basic workflow reference strategy. However, the discoveries reveal deeper architectural needs around workflow management that should be addressed for a clean, maintainable system.

The planner itself is well-specified in the task documents, but its integration points need these architectural decisions resolved.
