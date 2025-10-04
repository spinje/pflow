# Task 71: Verified Decisions and Findings

**Date**: 2025-10-02
**Status**: ✅ All Critical Ambiguities Resolved
**Method**: Parallel codebase verification using pflow-codebase-searcher agents

---

## Executive Summary

All critical ambiguities have been investigated and resolved through direct codebase verification. The implementation path is now clear with verified architectural decisions.

---

## VERIFIED DECISIONS

### 1. ✅ Error Enhancement Architecture - RESOLVED (Severity 5)

**Decision**: Enhance errors at `_build_error_list()` line 248 by accessing `shared[failed_node]`

**Verification Results**:
- **Data Storage**: HTTP and MCP nodes write to `shared[node_id]["key"]` due to NamespacedNodeWrapper
- **Data Availability**: ✅ ALL error data is available in `shared[failed_node]` when `_build_error_list()` executes
- **Current Extraction**: Already accesses `shared[failed_node]` at line 317 in `_extract_node_level_error()`
- **Enhancement Opportunity**: Can add `status_code`, `response`, `error_details` to error dict

**Implementation Approach**:
```python
# In _build_error_list() after line 248
def _build_error_list(self, success, action_result, shared_store):
    if success:
        return []

    error_info = self._extract_error_info(action_result, shared_store)
    failed_node = error_info["failed_node"]

    # Build base error
    error = {
        "source": "runtime",
        "category": self._determine_error_category(error_info["message"]),
        "message": error_info["message"],
        "action": action_result,
        "node_id": failed_node,
        "fixable": True,
    }

    # ENHANCEMENT: Add rich error data
    if failed_node:
        node_output = shared_store.get(failed_node, {})
        if isinstance(node_output, dict):
            # HTTP node data
            if "status_code" in node_output:
                error["status_code"] = node_output["status_code"]
                error["raw_response"] = node_output.get("response")
                error["response_headers"] = node_output.get("response_headers")

            # MCP node data
            if "error_details" in node_output:
                error["mcp_error_details"] = node_output["error_details"]

            # Result data (for both HTTP and MCP)
            if "result" in node_output:
                error["result_data"] = node_output["result"]

    return [error]
```

**Evidence**:
- Research document: `scratchpads/error-data-availability/storage-pattern-analysis.md`
- Verified locations:
  - HTTP node storage: `src/pflow/nodes/http/http.py:168-183`
  - MCP node storage: `src/pflow/nodes/mcp/node.py:341-422`
  - Namespacing: `src/pflow/runtime/namespaced_wrapper.py:47`
  - Current extraction: `src/pflow/execution/executor_service.py:317-342`

---

### 2. ✅ Validation Parameter Requirements - RESOLVED (Severity 4)

**Decision**: `--validate-only` performs STATIC validation only (no params required)

**User Guidance**: "Use --validate-only for STATIC validation ONLY"

**Verification Results**:
- **WorkflowValidator.validate()** line 58: `if extracted_params is not None:` → skips template validation when None
- **Static validation** includes:
  - ✅ Layer 1: Structural validation (schema, required fields)
  - ✅ Layer 2: Data flow validation (execution order, acyclic graph)
  - ✅ Layer 4: Node types exist in registry
  - ❌ Layer 3: Template resolution (SKIPPED when `extracted_params=None`)

**Implementation**:
```python
# In --validate-only flag handler
shared = {
    "generated_workflow": workflow_ir,
    "workflow_inputs": None,  # None = skip template validation
}

validator = ValidatorNode()
action = validator.run(shared)
```

**What Gets Validated**:
- JSON schema structure
- Required fields present
- Node/edge references valid
- No circular dependencies
- Template syntax correct (`${...}` format)
- Node types exist in registry

**What Does NOT Get Validated** (requires params):
- Template variables resolve to actual values
- Required inputs are provided
- Parameter types match expectations

**Evidence**:
- Research document: `scratchpads/task-71/STATIC_VALIDATION_VERIFICATION.md`
- Code location: `src/pflow/runtime/workflow_validator.py:58`
- Validation layers: `src/pflow/runtime/workflow_validator.py:31-83`

**Documentation Updates Needed**:
- Remove "validates with partial params" from CLI_COMMANDS_SPEC.md
- Add "static validation only (no params required)" to all validation docs
- AGENT_INSTRUCTIONS.md: Explain static vs full validation

---

### 3. ✅ ExecutionResult None Scenarios - RESOLVED (Severity 2)

**Decision**: `result` is ALWAYS ExecutionResult, never None

**Verification Results**:
- **All code paths** in `execute_workflow()` return ExecutionResult
- **Exception handling**: Wraps exceptions in ExecutionResult with success=False
- **Current signature**: `def execute_workflow(...) -> ExecutionResult:` (no Optional)
- **Current call site**: Doesn't even pass `result` to `_handle_workflow_error()` yet!

**Type Signature Change**:
```python
# OLD (incorrect)
def _handle_workflow_error(
    result: ExecutionResult | None,  # WRONG
    ...
)

# NEW (correct)
def _handle_workflow_error(
    result: ExecutionResult,  # ALWAYS exists
    ...
)
```

**No None checks needed** - parameter guaranteed to be ExecutionResult instance.

**Evidence**:
- Research document: `scratchpads/task-71-executionresult-analysis/EXECUTIONRESULT_NONE_VERIFICATION.md`
- All return paths: `src/pflow/execution/executor_service.py:53-139`
- Exception handling: `src/pflow/execution/executor_service.py:422-452`
- Current call site: `src/pflow/cli/main.py:1204-1212` (doesn't pass result yet)

---

### 4. ✅ MetadataGenerationNode Input Key - RESOLVED (Severity 3)

**Decision**: Use `"generated_workflow"` key (matches code expectations)

**Verification**: VERIFIED_RESEARCH_FINDINGS.md Section 4
- Code expects: `shared.get("generated_workflow", {})`
- Docs incorrectly used: `"validated_workflow"`

**Implementation**:
```python
# Correct approach
shared = {
    "generated_workflow": validated_ir,  # Code expects this key
    "user_input": "",
    "cache_planner": False,
}

metadata_node = MetadataGenerationNode()
metadata_node.run(shared)
metadata = shared.get("workflow_metadata", {})
```

**Evidence**: `src/pflow/planning/nodes.py:2459-2483` (prep method)

---

### 5. ✅ Workflow Name Validation - RESOLVED (Severity 3)

**Decision**: Keep dual validation (CLI strict, WorkflowManager permissive) with clear documentation

**Verification Results**:
- **WorkflowManager**: `^[a-zA-Z0-9._-]+$`, max 50 chars (permissive)
- **CLI Recommendation**: `^[a-z0-9-]+$`, max 30 chars (strict, agent-friendly)
- **Rationale**:
  - CLI = best practices, fast fail, user-friendly
  - WorkflowManager = safety net, backward compatibility, technical flexibility
- **Precedent**: Similar pattern in parameter validation (`validation_utils.py`)

**CLI Validation Implementation**:
```python
# Strict CLI validation (before WorkflowManager.save())
if not re.match(r'^[a-z0-9-]+$', name):
    click.echo("Error: Name must be lowercase with hyphens only", err=True)
    click.echo("  Examples: 'my-workflow', 'pr-analyzer'", err=True)
    raise click.Abort()

if len(name) > 30:
    click.echo("Error: Name must be 30 characters or less", err=True)
    raise click.Abort()

# WorkflowManager provides backup validation
manager.save(name, workflow_ir, description)  # May raise WorkflowValidationError
```

**Rationale Documentation**:
```markdown
## Why Two Validation Rules?

**CLI (Strict)**: Enforces agent-friendly conventions
- Shell-safe: No escaping needed in bash/zsh
- URL-safe: Works in web interfaces without encoding
- Git-friendly: Compatible with branch naming conventions
- Fast-fail: Catch issues before expensive operations

**WorkflowManager (Permissive)**: Maintains flexibility
- Backward compatibility with existing workflows
- Supports advanced Python API usage
- Focuses on filesystem safety only
```

**Evidence**:
- Research document: `scratchpads/task-71-workflow-validation/WORKFLOW_NAME_VALIDATION_RESEARCH.md`
- WorkflowManager validation: `src/pflow/core/workflow_manager.py:37-59`
- Precedent: `src/pflow/core/validation_utils.py` (parameter validation)

---

### 6. ✅ Registry Discover vs Describe - CLARIFIED (Severity 2)

**Decision**: Keep both commands - different selection methods, same output format

**Clarification**:
- **`registry discover "query"`**: LLM selects relevant nodes from description → full specs
- **`registry describe node1 node2`**: User specifies exact nodes → full specs
- **Both return**: Complete interface specifications (planning context)
- **Difference**: HOW nodes are selected, not WHAT is displayed

**Use Cases**:
- **discover**: "I need to fetch GitHub data" → LLM finds relevant nodes
- **describe**: "Tell me about github-get-pr and llm" → Direct lookup

**Implementation**: Current design is correct - no changes needed.

**Evidence**: ComponentBrowsingNode already returns planning_context (full details)

---

### 7. ✅ HTTP vs MCP Error Storage - VERIFIED (Severity 2)

**Decision**: Check `shared[failed_node]` for ALL error types (defensive approach)

**Verification Results**:
- **Both HTTP and MCP**: Store data in `shared[node_id]["key"]` due to namespacing
- **Location**: `shared[failed_node]` contains all error context
- **Available data**:
  - HTTP: `status_code`, `response`, `response_headers`, `response_time`
  - MCP: `error_details`, `result`, `{server}_{tool}_result`

**Implementation**: Single access pattern works for both:
```python
node_output = shared_store.get(failed_node, {})
if isinstance(node_output, dict):
    # Works for both HTTP and MCP
    if "status_code" in node_output:
        # HTTP node
    if "error_details" in node_output:
        # MCP node
```

**Evidence**: Storage pattern analysis in scratchpads/error-data-availability/

---

## LOWER PRIORITY CLARIFICATIONS

### 8. Confidence Score Display (Severity 2)

**Decision**: Show as percentage with threshold warnings

**Format**: `Confidence: 95%`
**Add warning if <70%**: `Confidence: 45% (weak match - consider refining query)`

---

### 9. Delete Draft Safety (Severity 2)

**Decision**: Validate file is in `.pflow/workflows/` before deletion

**Implementation**:
```python
if delete_draft:
    file_path_obj = Path(file_path).resolve()
    draft_dir = Path.cwd() / ".pflow" / "workflows"

    if not file_path_obj.is_relative_to(draft_dir):
        click.echo("Warning: File not in draft directory, skipping deletion")
    else:
        file_path_obj.unlink()
```

**Rationale**: Prevents accidental deletion of files outside draft directory

---

### 10. Empty Discovery Results (Severity 1)

**Decision**: Keep simple message - no forced results

**Current approach is correct**: Clear message + suggestion to refine query or use `registry list`

---

## DOCUMENTATION UPDATES REQUIRED

### Critical Updates

1. **ERROR_FLOW_ANALYSIS.md**:
   - ❌ Remove references to `_extract_error_from_shared()` (doesn't exist)
   - ✅ Update to reference `_build_error_list()` at line 218
   - ✅ Add verified storage patterns (namespaced data)

2. **IMPLEMENTATION_REFERENCE.md**:
   - ✅ Update error enhancement to use correct function name
   - ✅ Add verified implementation code from research
   - ✅ Update MetadataGenerationNode to use `"generated_workflow"` key
   - ✅ Update `_handle_workflow_error()` signature (no Optional)

3. **CLI_COMMANDS_SPEC.md**:
   - ❌ Remove "validates with partial params"
   - ✅ Add "static validation only (no params required)"
   - ✅ Clarify validation layers (what's checked, what's not)
   - ✅ Document workflow name validation dual approach

4. **AGENT_INSTRUCTIONS.md** (to be created):
   - ✅ Add static vs full validation explanation
   - ✅ Add workflow naming conventions with rationale
   - ✅ Add discover vs describe usage guide
   - ✅ Add validation workflow example

### Documentation Corrections

| Document | Line(s) | Change |
|----------|---------|--------|
| ERROR_FLOW_ANALYSIS.md | Multiple | `_extract_error_from_shared()` → `_build_error_list()` |
| IMPLEMENTATION_REFERENCE.md | 360 | `"validated_workflow"` → `"generated_workflow"` |
| IMPLEMENTATION_REFERENCE.md | 481 | `ExecutionResult \| None` → `ExecutionResult` |
| CLI_COMMANDS_SPEC.md | 183 | Remove "partial params" reference |
| All validation docs | Multiple | Add "static validation" clarification |

---

## IMPLEMENTATION PRIORITIES

### Phase 1: Core Enhancements (High Priority)
1. ✅ Error enhancement in `_build_error_list()` - VERIFIED approach
2. ✅ Static validation for `--validate-only` - VERIFIED approach
3. ✅ Update type signatures (ExecutionResult required) - VERIFIED

### Phase 2: Safety Improvements (Medium Priority)
4. ✅ Delete draft path validation - VERIFIED approach
5. ✅ Workflow name CLI validation - VERIFIED approach
6. ✅ Confidence score display with thresholds

### Phase 3: Documentation (Required)
7. ✅ Update all docs with correct function names
8. ✅ Add AGENT_INSTRUCTIONS.md with complete guide
9. ✅ Update type hints and docstrings

---

## VERIFICATION STATUS

| Ambiguity | Status | Method | Evidence Document |
|-----------|--------|--------|-------------------|
| Error Enhancement Architecture | ✅ VERIFIED | Codebase search | error-data-availability/ |
| Validation Parameters | ✅ VERIFIED | Codebase search | STATIC_VALIDATION_VERIFICATION.md |
| ExecutionResult None | ✅ VERIFIED | Codebase search | EXECUTIONRESULT_NONE_VERIFICATION.md |
| MetadataGenerationNode Key | ✅ VERIFIED | Previous research | VERIFIED_RESEARCH_FINDINGS.md |
| Workflow Name Validation | ✅ VERIFIED | Codebase search | WORKFLOW_NAME_VALIDATION_RESEARCH.md |
| Registry Commands | ✅ CLARIFIED | Architecture review | N/A - design is correct |
| Error Storage Patterns | ✅ VERIFIED | Codebase search | storage-pattern-analysis.md |
| Confidence Display | ✅ DECIDED | Best practice | N/A - straightforward |
| Delete Draft Safety | ✅ DECIDED | Best practice | N/A - straightforward |
| Empty Results UX | ✅ DECIDED | Best practice | N/A - straightforward |

---

## READY FOR IMPLEMENTATION

All blocking ambiguities resolved. Implementation can proceed with:

1. **High confidence** in architectural decisions
2. **Verified approaches** through codebase analysis
3. **Clear documentation** of rationale
4. **No remaining unknowns** that would block progress

The epistemic process has successfully validated the implementation path. All "assumed true" statements have been verified against actual code.

---

## NEXT STEPS

1. ✅ Update documentation files with corrections
2. ✅ Begin implementation following verified approaches
3. ✅ Write tests based on verified behavior
4. ✅ Create AGENT_INSTRUCTIONS.md with complete workflow guide

**Confidence Level**: VERY HIGH - all critical paths verified through code
