# Task 21 Impact Summary for Task 24 (WorkflowManager)

## Key Findings

### 1. Enhanced Workflow Format ✅
Task 21 added `inputs` and `outputs` declarations directly to the workflow IR:
- Rich schemas with types, descriptions, required/optional flags
- Default values for optional inputs
- Single source of truth (no more duplicate metadata)

### 2. Format Mismatch Discovered ⚠️
- **Context Builder** expects: `{"name": "...", "description": "...", "ir": {...}}`
- **WorkflowExecutor** expects: `{...}` (just the IR)
- This mismatch means workflows can't be shared between components without transformation

### 3. WorkflowManager Now MORE Critical 🚨
Originally needed for:
- Name-to-path resolution
- Saving workflows (missing feature)
- Consolidating scattered logic

Now ALSO needed for:
- Format standardization
- Transforming between storage and execution formats
- Leveraging rich input/output schemas

## Design Implications for Task 24

### Core API Enhancement
```python
class WorkflowManager:
    # Original methods
    def save(name: str, workflow_ir: dict) -> str
    def load(name: str) -> dict  # Returns full metadata format
    def list_all() -> List[WorkflowMetadata]

    # NEW: Format bridging
    def load_ir(name: str) -> dict  # Returns just IR for execution

    # NEW: Interface queries (enabled by Task 21)
    def find_by_inputs(input_names: List[str]) -> List[str]
    def find_by_outputs(output_names: List[str]) -> List[str]
    def check_compatibility(workflow1: str, workflow2: str) -> bool
```

### Storage Format Decision
Use metadata wrapper format (Context Builder style):
```json
{
  "name": "fix-issue",
  "description": "Fixes GitHub issues",
  "ir": {
    "ir_version": "0.1.0",
    "inputs": {...},   // Task 21's rich schemas
    "outputs": {...},  // Task 21's rich schemas
    "nodes": [...],
    "edges": [...]
  },
  "created_at": "...",
  "version": "1.0.0"
}
```

Benefits:
- Preserves workflow identity (name, description)
- Allows additional metadata
- Already expected by Context Builder
- WorkflowManager can extract just IR when needed

## Action Items for Task 24

1. **Implement format bridging** - `load()` vs `load_ir()` methods
2. **Leverage rich schemas** - Use Task 21's input/output declarations for validation
3. **Enable interface discovery** - Find workflows by their inputs/outputs
4. **Standardize storage** - One format to rule them all

## Bottom Line

Task 21 makes WorkflowManager both simpler (no duplicate metadata) and more critical (format mismatch). It's no longer just a convenience - it's essential infrastructure for making workflows work across all components.
