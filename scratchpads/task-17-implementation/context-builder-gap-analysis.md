# Context Builder Gap Analysis for Task 17 Planner

## Executive Summary

After careful analysis, I've identified **3 critical gaps** in the context builder that need addressing for the planner implementation:

1. **No public access to workflow metadata objects** - only markdown strings
2. **No method to retrieve full workflow IR** after discovery
3. **No structure information for workflow outputs** affecting template validation

## Detailed Analysis

### What Each Planner Node Needs

#### 1. WorkflowDiscoveryNode
**Needs:**
- All saved workflows with descriptions for semantic matching
- Access to workflow metadata after match is found
- Full workflow IR to pass to ParameterMappingNode

**Current Support:**
- ✅ `build_discovery_context()` shows all workflows
- ❌ No way to get workflow object after LLM selects one
- ❌ `_load_saved_workflows()` is private

#### 2. ComponentBrowsingNode
**Needs:**
- Lightweight listing of all nodes and workflows
- Just names and descriptions for browsing

**Current Support:**
- ✅ `build_discovery_context()` provides exactly this
- ✅ Can include both nodes and workflows

#### 3. ParameterMappingNode (Convergence Point)
**Needs:**
- Workflow's expected inputs list
- For validation and missing parameter detection

**Current Support:**
- ❌ Markdown string doesn't provide structured access
- ❌ Would need to parse markdown or access metadata directly

#### 4. GeneratorNode
**Needs:**
- Detailed interface information for selected components
- Understanding of what each component produces

**Current Support:**
- ✅ `build_planning_context()` provides detailed interfaces
- ⚠️ Workflow outputs don't show structure (unlike nodes)

#### 5. ValidatorNode
**Needs:**
- Registry access for node validation
- Template path validation against available outputs

**Current Support:**
- ✅ Can use registry directly
- ⚠️ Workflow output structure not available for path validation

### Critical Gaps Identified

## Gap 1: No Public Workflow Metadata Access

The planner needs structured workflow data, not just markdown:

```python
# Current situation
discovery_context = build_discovery_context()  # Returns markdown string
# "### fix-issue (workflow)\nFixes a GitHub issue..."

# After LLM selects "fix-issue", planner needs:
workflow_metadata = ???  # No public method!
workflow_ir = workflow_metadata["ir"]
workflow_inputs = workflow_metadata["inputs"]
```

**Impact**: WorkflowDiscoveryNode and ParameterMappingNode can't access workflow data

## Gap 2: No Workflow IR Retrieval Method

After discovering a workflow, the planner must return its IR to the CLI:

```python
# Path A flow
user_input = "fix github issue 123"
# -> WorkflowDiscoveryNode finds "fix-issue" workflow
# -> Need to get full IR to return to CLI
# -> But _load_saved_workflows() is private!
```

**Impact**: Can't complete Path A without accessing private methods

## Gap 3: No Workflow Output Structure

Nodes show output structure for template validation:
```markdown
### github-get-issue
**Outputs**:
- `issue_data` (dict)
  - Structure: {"id": int, "title": str, "user": {"login": str}}
```

But workflows don't:
```markdown
### fix-issue (workflow)
**Outputs**:
- `pr_url`
- `pr_number`
# No structure information!
```

**Impact**: Can't validate template paths like `$fix_issue_result.pr_url`

### Proposed Solutions

## Solution 1: Add Public Workflow Access Methods

```python
# In context_builder.py

def get_workflow_metadata(workflow_name: str) -> Optional[WorkflowMetadata]:
    """Get structured metadata for a specific workflow.

    Returns None if workflow not found.
    """
    workflows = _load_saved_workflows()
    return next((w for w in workflows if w["name"] == workflow_name), None)

def get_all_workflow_metadata() -> List[WorkflowMetadata]:
    """Get all saved workflow metadata.

    Public wrapper for _load_saved_workflows().
    """
    return _load_saved_workflows()
```

## Solution 2: Enhance Discovery Response

Instead of just markdown, return both:

```python
@dataclass
class DiscoveryContext:
    markdown: str  # For LLM
    nodes: Dict[str, Any]  # Structured node data
    workflows: List[WorkflowMetadata]  # Structured workflow data

def build_discovery_context_enhanced(...) -> DiscoveryContext:
    """Returns both markdown and structured data."""
    ...
```

## Solution 3: Document Workflow Output Limitations

If workflow output structure is unknowable:
1. Document that workflow outputs are opaque
2. Template validator should allow any path on workflow outputs
3. Or require workflows to declare output structure

### Minimal Required Changes

For MVP, the absolute minimum needed:

1. **Make workflow loading public**:
   ```python
   # Rename _load_saved_workflows to load_saved_workflows
   # OR add a public wrapper
   ```

2. **Add single workflow getter**:
   ```python
   def get_workflow_metadata(workflow_name: str) -> Optional[WorkflowMetadata]:
       """Needed by WorkflowDiscoveryNode after LLM selection."""
   ```

3. **Document the pattern**:
   - Use markdown for LLM consumption
   - Use direct methods for structured data access
   - Workflow outputs are opaque for template validation

### Usage Pattern in Planner

With these minimal changes:

```python
class WorkflowDiscoveryNode(Node):
    def exec(self, prep_res):
        # 1. Get markdown for LLM
        discovery_context = build_discovery_context()

        # 2. LLM selects workflow
        selected = llm.select_workflow(discovery_context, prep_res["user_input"])

        # 3. Get actual workflow data
        if selected["type"] == "workflow":
            workflow = get_workflow_metadata(selected["name"])  # NEW!
            return {"found_workflow": workflow}

class ParameterMappingNode(Node):
    def exec(self, prep_res):
        workflow = prep_res["workflow"]
        # Can now access workflow["inputs"] directly
        required_inputs = set(workflow["inputs"])
        ...
```

## Verification of Current State

After examining the actual context_builder.py implementation:

### Current Public API:
1. `build_discovery_context()` - Returns markdown string
2. `build_planning_context()` - Returns markdown string or error dict

### Workflow Structure (from _load_saved_workflows):
```python
{
    "name": str,
    "description": str,
    "inputs": List[str],
    "outputs": List[str],
    "ir": dict,  # Full workflow IR
    # Optional: version, tags, created_at, updated_at
}
```

## Conclusion

The context builder is **almost complete** for planner needs. The gaps are real but minimal:

1. **Primary Gap**: No way to get structured workflow data after LLM selection
   - `_load_saved_workflows()` returns exactly what we need but is private
   - Simple fix: Make it public or add a wrapper

2. **Secondary Gap**: No single workflow getter
   - After LLM selects "fix-issue", need to get that specific workflow
   - Simple fix: Add `get_workflow_metadata(name: str)`

3. **Minor Gap**: Workflow output structure for validation
   - Can be documented as limitation for MVP
   - Workflow outputs treated as opaque

Without these changes, the planner would need to:
- Access private methods (fragile)
- Parse markdown to extract data (error-prone)
- Re-implement workflow loading (duplication)

The fix is straightforward: expose 1-2 public methods for structured data access.
